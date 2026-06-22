# project-brain — 색인·임베딩·검색 동작 (구현 참조)

> 이 문서는 엔진이 **실제로 어떻게 색인하고 임베딩하고 회상하는가**를 코드 기준으로
> 설명한다. [design-canonical.md](design-canonical.md)가 "무엇을 왜 이렇게 만드는가"
> (설계 근거)라면, 이 문서는 "현재 코드가 어떻게 동작하는가"(구현 메커니즘)다.
>
> **코드가 정본이고 이 문서는 그것을 따라간다.** 모든 사실에 `파일:줄` 근거를 단다
> (경로는 `src/project_brain/` 기준). 코드가 바뀌면 이 문서도 갱신한다. 확인 범위·한계는
> §5에 분리해 둔다.

## 0. 큰 그림 — 저장소가 둘로 나뉜다

가장 중요한 출발점. 원본 저장소와 색인 저장소가 분리돼 있다.

- **진실의 원본은 JSON 파일이다.** `store.py`의 `BrainStore`가 `brain/` 아래 종류별
  폴더에 `id.json`으로 객체를 읽고 쓴다(`store.py:44,66`). 여기엔 임베딩·색인 코드가 없다.
- **색인은 그 JSON에서 만들어 내는 파생물이다.** `search_index.py`가 SQLite 단일 DB
  파일 하나에 검색용 색인을 빌드한다. 기본 경로는 `.brain-local/index.db`(git 추적 제외,
  `config.py`의 `resolve_db_path`). 코퍼스가 바뀌면 다시 만들면 되는 캐시 같은 존재라,
  망가져도 `index rebuild`로 복구된다.

그래서 "색인"은 곧 **JSON 원본 → SQLite 색인 변환**이고, "임베딩"은 그 변환 과정에서
텍스트를 벡터로 바꾸는 한 단계다.

## 1. 임베딩 (`embedder.py`)

텍스트를 벡터로 만드는 유일한 출입구는 `get_embedder()` 팩토리다.

- **실모델은 `BAAI/bge-m3`**, sentence-transformers로 로드하고 **1024차원** 벡터를
  낸다(`embedder.py:26,29`). 이 1024는 벡터 색인 테이블 정의(`embedding FLOAT[1024]`)와
  반드시 같아야 하는 약속이다(`search_index.py:100`).
- **L2 정규화**된 벡터다 — `encode(..., normalize_embeddings=True)`로 받는다
  (`embedder.py:102`). 정규화돼 있어 이후 거리 비교가 깔끔하다.
- **느긋한 로드(lazy load)**: 모델 객체는 첫 임베딩이 필요할 때 한 번만 올리고 계속
  재사용한다(`embedder.py:74-90`).
- **결정론 장치**: 모델 올리기 전 `torch.set_num_threads(1)`로 스레드를 1개로
  고정한다(`embedder.py:80`). 같은 입력이면 항상 같은 벡터가 나오게 하려는 것
  (torch import 실패 시 스레드 고정만 생략하고 진행).
- **배치 크기 8**: 기본값(32) 대신 8을 쓴다 — 긴 raw 청크에서 맥 GPU(MPS) 메모리 4GB
  한계를 넘겨 죽던 실측 이슈(2026-06-11) 때문(`embedder.py:99-104`). 배치 크기는 결과
  벡터 값에는 영향이 없다.
- **테스트용 가짜 임베더(`StubEmbedder`)**: 텍스트의 SHA-256 해시 앞 8바이트를 시드로
  가우시안 난수 벡터를 만들어 L2 정규화한다(`embedder.py:56-60`, model_name
  `stub:sha256-gaussian`). 모델 없이도 결정론이 보장돼 테스트에서 쓴다.
  `PROJECT_BRAIN_EMBEDDER=stub`로 켠다(`embedder.py:33`).
- **인스턴스 캐싱**: 실모델/스텁 여부를 키로 임베더를 1개씩 캐시한다 — 평가에서
  시나리오마다 실모델(~8초)을 새로 올리던 낭비를 없애려는 것(`embedder.py:108-123`).

## 2. 토큰화 (`tokenize_ko.py`)

한국어 키워드 검색의 핵심 보조 장치. `tokenize()` 하나를 **색인과 검색이 똑같이
공유**한다 — 둘이 다른 방식으로 쪼개면 매칭이 어긋나기 때문이다.

- **폴백 사다리**: `mecab-ko`(1순위) → `kiwipiepy`(2순위) → 정규식(최후) 순으로 설치된
  것을 한 번 골라 고정한다(`tokenize_ko.py:100-114`). kiwipiepy가 기본 동봉이라 보통
  여기까지는 동작하고, 형태소 분석기가 전부 없으면 정규식이 한글 덩어리를 통째로
  토큰화한다(형태소 분리 없음, `tokenize_ko.py:95`).
- **영문/심볼**도 `camelCase`, `snake_case`, `::`, 경로 구분자 기준으로 쪼개고 원형도 같이
  보존한다(`tokenize_ko.py:145-174`).
- 현재 백엔드 이름은 `active_backend()`가 `'mecab-ko'|'kiwipiepy'|'regex'`로 돌려주고,
  색인 meta 기록과 색인↔쿼리 비대칭 경고에 쓰인다(`tokenize_ko.py:117-124`).

**중요한 비대칭**: 토큰화 결과는 BM25(키워드) 레인에만 쓰고, **임베딩은 토큰화 전 원문
표면**을 그대로 넣는다. 둘은 입력이 다르다(§3 참조).

## 3. 색인 빌드 (`search_index.py`)

`rebuild()` 하나가 색인을 만드는 유일한 경로다. **"전체 재구축 = DB 파일을 지우고 처음부터
다시 만든다"가 불변 규칙**이다(`search_index.py:111`). 증분 갱신(바뀐 것만 다시 색인)
함수는 코드에 없다 — `content_hash`는 `documents`에 저장만 될 뿐 색인 갱신 비교에 쓰는
코드가 없다.

SQLite DB 안에 테이블이 4개 만들어진다(`search_index.py:80-108`, `SCHEMA_VERSION=4`):

| 테이블 | 역할 |
|--------|------|
| `documents` | 한 행 = 한 객체(또는 raw 청크). `tokenized_text`와 `surface_text`를 둘 다 보관 |
| `documents_fts` | FTS5 가상 테이블(`tokenize='unicode61'`). BM25 키워드 검색용 |
| `documents_vec` | sqlite-vec의 `vec0` 가상 테이블(`embedding FLOAT[1024]`). 벡터 저장 |
| `meta` | 스키마 버전·임베딩 모델명·토크나이저·코퍼스 지문 한 줄 |

빌드할 때 **같은 텍스트를 두 갈래로** 넣는 게 핵심이다:

- **FTS5에는** `tokenize(surface)`로 형태소 분리한 토큰을 공백으로 이어붙인
  `tokenized_text`(`search_index.py:154`).
- **벡터에는** 토큰화하지 않은 **원문 표면**을 모아서 `embed_many`로 한 번에 배치
  임베딩한 뒤, `sqlite_vec.serialize_float32`로 직렬화해 넣는다
  (`search_index.py:199-210,234-238`).

특징 몇 가지:

- 벡터 색인은 별도 파일이나 BLOB 컬럼이 아니라 **같은 SQLite DB 안의 `vec0` 가상
  테이블**이다. 검색 때 메모리로 따로 올리는 단계 없이 DB에서 바로 KNN 질의한다
  (`search_index.py:54-77,534-541`). `vec0`는 rowid 기반이라 `documents.row_id`로 KNN
  결과를 `object_id`로 되짚는다.
- 임베더를 안 넘기면(`None`) **FTS만 색인하고 벡터 테이블은 빈 채**로 둔다
  (`search_index.py:171-210`). 즉 임베딩은 선택이다(`meta.embed_model`이 빈 값).
- 색인 대상은 store 객체뿐 아니라 `raw/sources/<ctx>/*.md`를 잘게 나눈 **raw 청크**도
  포함한다(`raw_chunks.py:107-124`). 청킹은 목표 500토큰·15% 겹침으로 결정론적으로 자른다.
  raw 청크는 store에 없는 행이라 원문을 `surface_text`로 직접 운반한다(`kind=raw_chunk`,
  `status=raw`).
- **신선도 가드**: 색인할 때 코퍼스 전체의 지문(해시)을 `meta.corpus_fingerprint`에
  남기고(`compute_corpus_fingerprint`, `search_index.py:278-306`), 검색 시점에 현재 코퍼스
  지문과 다르면 "색인이 낡았다"며 거부하고 `rebuild`를 안내한다(`search.py:315-331`). 낡은
  색인으로 옛 상태를 회상하는 조용한 오답을 막으려는 장치다. 스키마 버전이 코드와 다를
  때도 `StaleIndexError`로 거부한다(`search_index.py:324-332`).

## 4. 검색 융합 (`search.py`)

색인 두 레인이 검색에서 만난다. 본체는 `recall()`이다(`search.py:334`).

1. **두 채널을 각각 검색**: BM25 키워드(`search_bm25`)와 벡터 KNN(`search_vector`)을 각각
   `CHANNEL_TOP_N=50`개 받는다(`search.py:71`).
2. **RRF로 융합**: 점수가 아니라 **순위**만 써서 `score = Σ 1/(60+rank)`로 합친다
   (`RRF_K=60`, `rrf_fuse`, `search.py:68,136-153`). 융합 후 `FUSED_TOP_N=30`으로 자른다.
   두 채널은 점수 척도가 달라서(BM25는 작을수록 좋고 벡터 거리도 작을수록 좋음) 순위 기반
   융합이 안전하다. rank는 1부터 센다(표준 RRF — 1등이 1/61).
3. **그래프 1-hop + 상호지지 재정렬**: top 30 안에서 객체들이 서로의 참조 필드(코드 위치·
   용어·결정·매핑)로 연결됐는지 본다. **"내 엣지가 적중집합 안 다른 적중을 가리킨
   수"(아웃바운드 도달, `graph_support`)**를 상한 `_GRAPH_SUPPORT_CAP=2`로 자른 값을 1순위
   정렬 키로 써서 재정렬한다(`_rerank_by_support`, `search.py:109,226-241`). RRF 점수에
   상수를 더하지 않고 순서만 바꾸는 게 원칙이다. 상한을 두는 이유는 엣지 100개 넘는 허브
   객체가 그래프 신호만으로 위로 굳어지는 걸 막기 위해서다. 양방향 `graph_hits`는 표시·진단
   전용이고 재정렬에는 안 쓴다(`search.py:195-223`).
4. **레인 분리**: raw 청크·`Insight`·`ContextProjection`은 객체 레인과 **따로 융합**해
   뒤에 붙인다(`_OBJECT_LANE_EXCLUDED`, `search.py:95,378-404`). 자유 텍스트 덩어리가 객체
   자리를 잠식해 그래프 재정렬을 약화시키던 회귀를 막으려는 것이다. raw·projection은
   `surface_text`가 원문을 운반하고 그래프·surface 승급이 없다.
5. **scope(범위) 좁히기**: 질의가 기능명을 단일 특정하면(`infer_scope`, `search.py:271`)
   그 `DomainContext`로 하드 필터를 건다. scope가 확정되면 객체 레인 BM25는
   `search_bm25_scoped`로 바뀐다 — 후보 집합 안에서 df를 다시 계산해 scope 밖 문서가 scope
   안 순위를 흔들지 못하게 한다(`search.py:392-393`).

`eval_recall`(`search.py:678`)은 평가·CLI 진입점으로, `recall` 결과를 **다신호 답변
게이트**(`_gate_pass`, `search.py:646-675`)에 통과시켜 채널로 가른다 — reviewed `results` /
candidate `candidates` / `raw_excerpts` / `advisories`(Insight) / `projection_reuse`. 게이트
세 신호는 RRF 절대 점수 바닥, 1·2등 점수 차(`margin`), **표면 앵커**(질의에서 가장 희소한
토큰의 문서 빈도, `_ANCHOR_DF_MAX=30`)다. 예컨대 '크리스마스'(코퍼스 빈도 0)처럼 핵심
엔티티가 코퍼스에 없으면, '보상'·'이벤트' 같은 흔한 토큰만 맞아도 게이트가 막아 거짓
양성을 거른다 — "근거 없으면 없다고 답한다"의 구현부다. reviewed 게이트 통과가 0건이면
`needs_clarification`을 켠다.

## 5. 확인 범위·한계

이 문서의 사실은 위 모듈을 **직접 읽어(read)** 확인했고, 4개 핵심 모듈
(`search`/`search_index`/`embedder`/`tokenize_ko`)이 깨끗하게 임포트되는 것까지 확인했다
(문법·모듈 로드 수준 무결).

코드 메커니즘 기준이라, 아래는 이 문서가 보장하지 않는다 — 별도 도구가 검증한다:

- **검색 품질·로직 정확성**: 합성 테스트(`tests/`, `pytest`)와 데이터 레포 골든셋
  (`project-brain eval`)이 검증한다. 이 문서는 "코드가 무엇을 하도록 쓰여 있는가"까지다.
- **형태소 분석기 실제 출력**: kiwipiepy/mecab-ko가 설치 환경에서 한국어를 어떻게
  쪼개는지는 외부 라이브러리 영역이라 코드만으로는 검증할 수 없다.
- **bge-m3 내부 동작**: sentence-transformers `encode`의 내부 토큰화·길이 자르기는 외부
  라이브러리 영역이다.

상수 캘리브레이션 값(`RRF_K`, `_GRAPH_SUPPORT_CAP`, `_ANCHOR_DF_MAX`, 점수 바닥)의 근거와
실측 이력은 `search.py` 주석과 `docs/specs/2026-06-10-bb2-brain-search-layer-design.md`
(설계 시점 히스토리)에 있다.
