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
  낸다(`embedder.py:31,34`). 이 1024는 벡터 색인 테이블 정의(`embedding FLOAT[1024]`)와
  반드시 같아야 하는 약속이다(`search_index.py:126`).
- **L2 정규화**된 벡터다 — `encode(..., normalize_embeddings=True)`로 받는다
  (`embedder.py:157-160`). 정규화돼 있어 이후 거리 비교가 깔끔하다.
- **느긋한 로드(lazy load)**: `RealEmbedder`는 계산 전용 adapter로 첫 임베딩 때
  가중치를 올린다. `get_embedder()`는 실모델에 `ManagedEmbedder`를 반환해, 기본으로
  사용자별 상주 서비스에 텍스트를 보낸다. public 인터페이스와 기존 embedding identity는
  그대로다(`embedder.py:78,165,180`의 계산·팩토리·adapter).
- **결정론 장치**: 기존 `torch.set_num_threads(1)`·float32·정규화·최대 시퀀스 2,048·
  모델 실행 batch_size=1을 서비스와 직접 경로에서 공유한다. 서비스는 계산한 float32
  bytes를 base64로 전달하고 클라이언트는 숫자 재계산 없이 복원한다.
  #58에서 확인한 MPS의 혼합 배치 하위 비트 차이를 피하는 설정을 유지한다
  (`embedder.py:100,149`; `embedding_service.py:210,288`).
- **서비스의 키·수명**: embedding identity 문자열과 protocol version을 키로 한다.
  연결 직후 version·identity를 정확히 대조하고, 다르면 텍스트를 보내지 않는다.
  기동/수명 flock으로 동시에 첫 요청을 보내도 신원당 모델 하나만 올린다.
  임베딩 요청 없이 기본 600초가 지나면 종료한다. status는 유휴 시간을 연장하지 않는다.
  소켓·로그·잠금은 사용자별 `/tmp/project-brain-embed-<uid>/`(0700)에 둔다
  (`embedding_service.py:51,62,141,164,288`).
- **예비 경로**: 소켓 차단·서비스 기동 실패 때 `LockedLocal`이 전역 슬롯(기본 1)을
  얻은 뒤 모델을 올린다. 프로세스 종료까지 슬롯을 보유해 캐시된 모델도 제한 안에 둔다.
  기본 300초 대기 뒤 `embedder_busy` 오류로 끝내며 잠금이 불가능해도 로드를 거부한다.
  flock 파일은 삭제하지 않고 OS가 죽은 소유자의 잠금을 회수한다. stale 소켓은 수명
  잠금을 얻은 서비스만 제거한다(`embedding_service.py:93,236`).
- **큰 입력·운영**: `embed_many`는 32개씩 나누어 보내고 순서를 보존한다.
  `embedder status`/`stop`과 doctor의 `embed-service`가 현재 신원의 PID·identity·RSS를
  보고하며 status가 새 서비스를 띄우지는 않는다. 설정은 [README](../README.md#임베딩-서비스)
  (`cli.py:1802`, `doctor.py:122`).
- **테스트용 가짜 임베더(`StubEmbedder`)**: 텍스트 SHA-256 시드의 정규화된 가짜 벡터를
  만든다. `PROJECT_BRAIN_EMBEDDER=stub`는 서비스/잠금 없이 직접 계산한다. 서비스 회귀는
  외부 모델 경계에 이 stub을 쓰는 fake를 주입해 실모델을 실행하지 않는다
  (`embedder.py:52`; `tests/test_embedding_service.py:1`).
- **인스턴스 캐싱**: 프로세스 내에서는 실모델/스텁 여부를 키로 임베더 하나씩 캐시하고,
  프로세스 간에는 동일 신원의 서비스가 가중치를 공유한다(`embedder.py:162-177`).

## 2. 토큰화 (`tokenize_ko.py`)

한국어 키워드 검색의 핵심 보조 장치. `tokenize()` 하나를 **색인과 검색이 똑같이
공유**한다 — 둘이 다른 방식으로 쪼개면 매칭이 어긋나기 때문이다.

- **단일 백엔드**: 한국어 형태소는 `kiwipiepy` 하나만 쓴다(#79). 폴백 사다리는 없다 —
  설치 환경에 따라 다른 분석기가 골라지면 사람마다 다른 토큰이 나와 색인과 질의가 조용히
  어긋나기 때문이다. 버전은 `pyproject.toml`에 `kiwipiepy==0.23.2`,
  `kiwipiepy_model==0.23.0`으로 고정한다. 설치돼 있지 않으면 폴백하지 않고 `RuntimeError`로
  알린다. Kiwi 인스턴스는 첫 사용 때 한 번 만들어 캐시하고, 사용자 사전·오타 교정은 쓰지
  않는 기본 옵션이다.
- **어절 안 명사 결합형**: 형태소 조각을 그대로 두고, 같은 어절(kiwi `word_position`) 안에서
  연속한 명사류 조각(`NNG`·`NNP`·`NNB`·`XR`·`SN`·`SL`)이 2개 이상이고 그중 한글 조각이 하나
  이상이면 이어 붙인 토큰을 소문자로 **추가**한다. 명사류 뒤에 바로 붙은 파생 접미사(`XSN`:
  -제·-별·-용·-화·-성 등)는 같은 연속에 포함되지만 연속을 시작하지는 못한다(규칙 버전 4, #82 —
  kiwi가 `시간제`를 시간+제로 읽어 `시간제` 토큰이 어디에도 없던 문제). 조각이 하나뿐이거나 한글
  조각이 없으면 추가하지 않고, 조사·어미·동사 조각이 나오거나 어절이 바뀌면 연속이 끊긴다. 영문
  심볼에서 camelCase 조각과 원형을 같이 남기는 것과 같은 규칙이다. 예: `인게임에서 아이템 사용하면` →
  인·게임·에서·**인게임**·아이템·사용·하·면 / `럭키박스 아이콘` → 럭키·박스·**럭키박스**·아이콘 /
  `3단계 오픈 팝업` → 단계·**3단계**·오픈·팝업·3 / `UI버튼 클릭` → 버튼·**ui버튼**·클릭·ui /
  `시간제 아이템` → 시간·제·**시간제**·아이템 / `활성화 플래그` → 활성·화·**활성화**·플래그 /
  띄어 쓴 `스테이지 클리어 토큰`, 한글 없는 `3.7new`, 대명사 뒤 접미사 `우리들`은 결합형이 생기지 않는다.
- **명사형 전성어미 표면**: kiwi는 `알림`을 뒷말에 따라 명사(`NNG`)로도 `알리`+`ㅁ`(`VV`+`ETN`)
  으로도 읽는다(문맥 의존 중의성, BB2 실측). 색인과 질의가 다른 쪽으로 읽히면 같은 말이 어긋나므로,
  동사·형용사 어간(`VV`·`VA`·`VX`·`XSV`·`XSA`, 사이의 `EP`·`EC` 포함) 뒤에 `ETN`이 오는 어절은
  원문에서 어간부터 `ETN`까지의 표면을 잘라 토큰으로 함께 보존한다. 예: `알림 안내` → 알리·**알림**·
  안내 / `만들기 버튼` → 만들·기·**만들기**·버튼 / `보여주기 옵션` → 보이·어·주·기·**보여주기**·옵션.
  명사로 읽힌 `알림을`은 조각 자체가 알림이라 중복 없이 같은 토큰을 공유한다. 종결·연결·관형형
  어미(`EF`·`EC`·`ETM`) 뒤에는 표면을 만들지 않는다.
- **정규식 분리**는 폴백이 아니라 `tokenize(..., backend="regex")` 명시 주입 전용이다 —
  형태소 분리 없이 한글 덩어리를 통째로 토큰화하며, 테스트가 백엔드와 무관한 결정론
  경로를 강제할 때만 쓴다.
- **영문/심볼**도 `camelCase`, `snake_case`, `::`, 경로 구분자 기준으로 쪼개고 원형도 같이
  보존한다.
- 현재 백엔드 이름은 `active_backend()`가 돌려준다(정상 경로에서는 항상 `'kiwipiepy'`).
- **규칙 버전**: 백엔드 이름이 같아도 토큰 산출 규칙이 바뀌면 옛 색인과 새 질의가 조용히
  어긋나므로, 규칙에 `TOKENIZER_RULES_VERSION`(현재 **4** — 2: 결합형 토큰 도입, 3: 숫자·외국어 조각 결합과 명사형 전성어미 표면 보존, 4: 명사류 뒤 파생 접미사 결합)을 매긴다.
  `tokenizer_signature()`가 `'<백엔드>@<규칙 버전>'`을 만들어 색인 meta에 기록하고, 검색
  진입에서 이 값이 다르면 경고가 아니라 `StaleIndexError`로 거부한다(§3 신선도 가드).
  규칙 버전 표기가 없는 옛 meta는 규칙 버전 1로 읽으므로(`parse_tokenizer_signature`)
  현재 버전에서는 이름이 같아도 거부되고 `index rebuild`가 필요하다(버전 2·3 색인도 마찬가지).

**중요한 비대칭**: 토큰화 결과는 BM25(키워드) 레인에만 쓰고, **임베딩은 토큰화 전 원문
표면**을 그대로 넣는다. 둘은 입력이 다르다(§3 참조).

## 3. 색인 빌드 (`search_index.py`)

`rebuild()` 하나가 색인을 만드는 유일한 경로다. **새 DB를 완성·검증한 뒤 원자 교체**하며,
live DB를 제자리에서 증분 갱신하지 않는다. `content_hash`는 문서 metadata로 저장하고,
벡터 재사용에는 `surface_text`를 쓴다.

SQLite DB는 핵심 v5 테이블과 선택적인 신선도 캐시를 함께 만든다(`_create_schema`,
`SCHEMA_VERSION=5`, `FRESHNESS_CACHE_VERSION=1`):

| 테이블 | 역할 |
|--------|------|
| `documents` | 한 행 = 한 객체(또는 raw 청크). `tokenized_text`와 `surface_text`를 둘 다 보관 |
| `documents_fts` | FTS5 가상 테이블(`tokenize='unicode61'`). BM25 키워드 검색용 |
| `documents_vec` | sqlite-vec의 `vec0` 가상 테이블(`embedding FLOAT[1024]`). 벡터 저장 |
| `meta` | 스키마 버전·임베딩 모델명·embedding identity·토크나이저(`이름@규칙 버전`)·코퍼스 지문 한 줄 |
| `freshness_surfaces` | 표면 SHA-256별 토큰 존재 여부. 빈 토큰으로 제외한 객체·raw 표면도 기록 |
| `freshness_meta` | 선택 캐시 버전과 생성 시 코퍼스 지문 |
| `scope_surfaces` | DomainContext의 정확한 scope 표면별 토큰. display_name·접미 제거 title·하이픈 분리 context_key |

선택 캐시는 핵심 v5·벡터·seed 계약을 바꾸지 않는다. 캐시 없는 기존 v5 DB도 rebuild
없이 전체 지문 계산으로 판정한다. 캐시 버전·코퍼스 지문·토크나이저 신원·추출기 버전이
일치할 때만 빠른 경로를 사용하며 누락·손상된 캐시는 전체 계산으로 돌아간다. 캐시 규칙이
바뀌면 `FRESHNESS_CACHE_VERSION`을 올린다.

빌드할 때 **같은 텍스트를 두 갈래로** 넣는 게 핵심이다:

- **FTS5에는** `tokenize(surface)`로 형태소 분리한 토큰을 공백으로 이어붙인
  `tokenized_text`(`search_index.py:154`).
- **벡터에는** 토큰화하지 않은 **원문 표면**을 모아서 `embed_many`로 한 번에 배치
  임베딩한 뒤, `sqlite_vec.serialize_float32`로 직렬화해 넣는다
  (`search_index.py:199-210,234-238`).

### 자동 벡터 재사용 (#57·#58, BB2 work-tracker #93)

새 DB와 FTS는 매번 전체를 다시 만든다. 벡터만 자기 마지막 정상 완료 live index → seed 순서로
**정확히 같은 `surface_text`**를 키로 복사하며, miss만 한 번의 `embed_many`로 계산한다.
객체·raw가 같은 규칙을 쓰며 ID·status·content hash·corpus fingerprint는 벡터 재사용 키가 아니다.

Embedder가 `embedding_identity`를 소유한다. 실모델은 불변 Hugging Face revision
`5617a9f61b028005a4858fdac845db406aefb181`에 고정하고 최대 길이, 정규화, 출력 차원·dtype,
실행 device·모델 dtype, 라이브러리 버전을 identity에 포함한다. 배치 크기를 사용자가 조절하지 않으며, 실행 의미 버전 2로 배치 독립 계산을 구분한다.
신원 조회는 가중치를 로드하지 않는다. 로더에도 동일한 device·float32를 명시하며 실제
임베딩 뒤 신원이 사전 신원과 달라지면 교체를 거부한다. 전량 재사용이면 모델을 로드하지 않는다.

seed 선택은 반복 가능한 `index rebuild --seed <DB>` > `.project-brain.json`의
`index_seeds` 경로 배열 > 자동 탐색이다. CLI 상대 경로는 cwd, config 상대 경로는 config
위치 기준이다. `index_seeds: []`(Python API는 `seeds=[]`)로 자동 탐색을 끌 수 있다.
명시 목록은 하위 우선순위 목록과 합치지 않는다.

`index_seeds.py`는 대상 코퍼스가 속한 Git 공용 디렉터리의 다른 checkout만 탐색한다.
Git worktree 목록의 원본 checkout을 우선하고 각 checkout의 config에서 DB 위치를 읽는다.
config가 없으면 대상 DB의 checkout 상대 위치를 대응시킨다. 임시 rebuild DB는 후보가 아니다.
config의 DB 실경로가 별도 Git clone에 속하면 자동 후보에서 제외한다. 비-Git 외부 cache는
config가 지정한 경로를 허용하며, CLI/config의 명시 seed 목록에는 자동 탐색 제한을 적용하지 않는다.
다른 checkout의 corpus 경로·지문을 현재 corpus와 같다고 가정하지 않고 벡터만 가져온다.

자기 이전 DB와 seed 모두 URI `mode=ro`로 열어 schema·identity·tokenizer·extractor의 현재값 일치,
SQLite 무결성, 단일 metadata, 문서/FTS 일치,
문서/벡터 row ID 일치, 벡터 길이·유한값, 동일 surface의 벡터 충돌을 검사한다. 하나라도
실패하면 해당 DB **전체**를 포기한다. seed 실패는 사유를 기록하고 다음 seed로 진행하며,
SQLite 잠금은 기다리지 않고 fallback한다. 중단된 임시 DB는 읽지 않는다. 기능 도입 전 색인은
identity가 없으므로 첫 실행은 전체 계산이다. 기존 lock·임시 DB 검사·fsync·원자 교체는 유지한다.

`index rebuild` 완료 JSON의 추가 필드:

| 필드 | 의미 |
|---|---|
| `vectors_total` | 현재 벡터 대상 행 수 |
| `vectors_reused` | 이전 정상 색인에서 복사한 행 수 |
| `vectors_seeded` | seed에서 복사한 행 수 |
| `seed_paths` | 실제 벡터를 제공한 seed의 절대 DB 경로 배열 |
| `seed_fallbacks` | 사용할 수 없던 seed의 `{path, reason}` 배열 |
| `vectors_computed` | 새로 계산한 행 수 |
| `vector_reuse_fallback` | 자기 이전 색인이 정상이면 `null`, 아니면 자기 이전 색인 폴백 사유(seed 사용과 독립) |
| `elapsed_seconds` | 경로 해석부터 교체·동기화까지 총 시간(초) |

사유는 `no_previous_index`, `legacy_index`, `fts_only_index`,
`embedding_identity_mismatch`, `tokenizer_mismatch`, `extractor_version_mismatch`, `invalid_previous_index`,
`conflicting_surface_vectors`, `unreadable_previous_index`다.
FTS 전용 API 호출은 `embedding_disabled`와 벡터 통계 0을 반환한다.
자동 탐색 실패는 `seed_discovery_failed`, 타 checkout의 잘못된 config는 `invalid_seed_config`다.
자동 후보 DB가 별도 clone에 속하면 `seed_clone_mismatch`다.
전체 = 자기 재사용 + seed 재사용 + 새 계산이며, 이 통계는 DB metadata에 저장하지 않아
cold/warm 결과가 같다. seed가 있다는 사실만으로 computed=0이나 짧은 실행 시간이 보장되지는 않는다.

특징 몇 가지:

- 벡터 색인은 별도 파일이나 BLOB 컬럼이 아니라 **같은 SQLite DB 안의 `vec0` 가상
  테이블**이다. 검색 때 메모리로 따로 올리는 단계 없이 DB에서 바로 KNN 질의한다
  (`search_index.py:54-77,534-541`). `vec0`는 rowid 기반이라 `documents.row_id`로 KNN
  결과를 `object_id`로 되짚는다.
- 임베더를 안 넘기면(`None`) **FTS만 색인하고 벡터 테이블은 빈 채**로 둔다
  (`search_index.py:171-210`). 즉 임베딩은 선택이다(`meta.embed_model`이 빈 값).
- 색인 대상은 store 객체뿐 아니라 `raw/sources/<ctx>/*.md`를 잘게 나눈 **raw 청크**도
  포함한다(`raw_chunks.py:132-150`). 청킹은 목표 500토큰·15% 겹침으로 결정론적으로 자른다.
  근사 토큰은 ASCII 단어 1 + 한글 음절 1 + 그 밖의 비공백 기호 2글자당 1로 센다
  (`raw_chunks.py:26-39`). 헤더→줄/문장 경계로 나눈 한 유닛이 목표를 넘으면 문자 경계에서
  다시 쪼개므로, 긴 마크다운 표 한 줄도 목표를 무시한 단일 청크가 되지 않는다
  (`raw_chunks.py:61-113`).
  raw 청크는 store에 없는 행이라 원문을 `surface_text`로 직접 운반한다(`kind=raw_chunk`,
  `status=raw`).
- **신선도 가드**: 색인할 때 코퍼스 전체의 지문(해시)을 `meta.corpus_fingerprint`에
  남기고(`compute_corpus_fingerprint`, `search_index.py:427-455`), 검색 시점에 현재 코퍼스
  지문과 다르면 "색인이 낡았다"며 거부하고 `rebuild`를 안내한다
  (`_guard_index_freshness`, `search.py:338-354`). 낡은
  색인으로 옛 상태를 회상하는 조용한 오답을 막으려는 장치다. 스키마 버전이 코드와 다를
  때도 `StaleIndexError`로 거부한다(`_guard_schema_version`). **토크나이저 가드**도 같은
  자리에 있다 — `meta.tokenizer`의 백엔드 이름이나 규칙 버전이 질의 시점과 다르면
  `StaleIndexError`로 거부한다(`_guard_tokenizer`, BM25 두 레인 진입). 예전처럼 경고만
  달고 검색을 계속하지 않는다.
- **해시 우선 신선도 판정(BB2 #95)**: 현재 store의 projection freshness와 표면을 매번
  계산하고 raw도 현재 파일에서 청킹한다. 표면 해시가 캐시에 있으면 저장된 토큰 존재
  여부를 재사용하고, 새 표면만 토큰화한다. 포함된 행의 `(kind, id, status, surface)`를
  기존과 똑같이 정렬·직렬화하므로 전체 계산과 같은 지문이다. 빈 토큰 표면의 추가·삭제·
  변경은 제외 규칙을 그대로 따른다. scope 추론도 현재 표면의 정확 일치로만 캐시를 읽고,
  바뀐 title처럼 색인 표면에 없는 변경은 즉시 새 토큰을 계산한다.
- **eval snapshot**: `load_recall_fn()`은 호출마다 새 `SearchSession`을 만든다. 한 eval
  동안 corpus와 index가 바뀌지 않는다는 전제로 store·scope 캐시와 성공한 freshness 판정을
  한 번만 계산한다. mutation/rebuild 뒤에는 세션을 폐기하고 새로 만들어야 한다.
  일반 `search`·`recall`·`eval_recall`은 호출마다 판정하며 전역적인 freshness 면제는 없다.
- `DomainMapping` 표면은 자체 의미·경계뿐 아니라 reviewed 참조 `GlossaryTerm`의
  `term`·`synonyms`·`aliases`를 함께 받고, candidate 참조에서는 기존 `term`·`synonyms`만
  유지한다(`surface.py:59-68,84-101`). 별칭 위임을 추가한 추출기 버전은 4다
  (`surface.py:26-28`). rebuild는 이 버전과 표면 기반 코퍼스 fingerprint를 meta에 기록하고
  (`search_index.py:329-335,414-442`), aliases가 있는 affected corpus의 예전 DB는 live
  fingerprint 불일치로 거부한다(`search.py:338-353`).

## 4. 검색 융합 (`search.py`)

색인 두 레인이 검색에서 만난다. 본체는 `recall()`이다(`search.py:335`).

1. **두 채널을 각각 검색**: BM25 키워드(`search_bm25`)와 벡터 KNN(`search_vector`)을 각각
   `CHANNEL_TOP_N=50`개 받는다(`search.py:76`).
2. **RRF로 융합**: 점수가 아니라 **순위**만 써서 `score = Σ 1/(60+rank)`로 합친다
   (`RRF_K=60`, `rrf_fuse`, `search.py:73,117-134`). 융합 후 `FUSED_TOP_N=30`으로 자른다.
   두 채널은 점수 척도가 달라서(BM25는 작을수록 좋고 벡터 거리도 작을수록 좋음) 순위 기반
   융합이 안전하다. rank는 1부터 센다(표준 RRF — 1등이 1/61).
3. **그래프 1-hop + 상호지지 재정렬**: top 30 안에서 객체들이 서로의 참조 필드(코드 위치·
   용어·결정·매핑)로 연결됐는지 본다. **"내 엣지가 적중집합 안 다른 적중을 가리킨
   수"(아웃바운드 도달, `graph_support`)**를 상한 `_GRAPH_SUPPORT_CAP=2`로 자른 값을 1순위
   정렬 키로 써서 재정렬한다(`_rerank_by_support`, `search.py:114,227-242`). RRF 점수에
   상수를 더하지 않고 순서만 바꾸는 게 원칙이다. 상한을 두는 이유는 엣지 100개 넘는 허브
   객체가 그래프 신호만으로 위로 굳어지는 걸 막기 위해서다. 양방향 `graph_hits`는 표시·진단
   전용이고 재정렬에는 안 쓴다(`search.py:196-224`).
4. **레인 분리**: raw 청크·`Insight`·`ContextProjection`은 객체 레인과 **따로 융합**해
   뒤에 붙인다(`_OBJECT_LANE_EXCLUDED`, `search.py:100,379-405`). 자유 텍스트 덩어리가 객체
   자리를 잠식해 그래프 재정렬을 약화시키던 회귀를 막으려는 것이다. raw·projection은
   `surface_text`가 원문을 운반하고 그래프·surface 승급이 없다.
5. **scope(범위) 좁히기**: 질의가 기능명을 단일 특정하면(`infer_scope`, `search.py:272`)
   그 `DomainContext`로 하드 필터를 건다. scope가 확정되면 객체 레인 BM25는
   `search_bm25_scoped`로 바뀐다 — 후보 집합 안에서 df를 다시 계산해 scope 밖 문서가 scope
   안 순위를 흔들지 못하게 한다(`search.py:393-394`). 호출자는 이 추론을 덮어쓸 수 있다
   (#74): `search --context-id <id>`는 그 컨텍스트로 고정하고, `--all-contexts`는 추론
   없이 전체를 회수한다. 네 갈래(`explicit`/`inferred`/`disabled`/`none`)를
   `_resolve_scope`가 한 자리에서 정해 `recall`에 넘기고 같은 값을 응답의 `scope` 사실로
   신고하므로, 신고값과 실제로 걸린 필터가 갈라지지 않는다. `disabled`(호출자가 껐다)와
   `none`(추론이 단일 특정에 실패)은 `context_id=None`으로 결과가 같지만 이유가 달라 값을
   가른다. 코퍼스가 모르는 id는 `UnknownScopeError`로 거부한다 — 조용한 전 채널 0건이
   오타와 미적재를 섞지 않게. 채널별 노출 개수도 호출 인자다
   (`eval_recall(channel_top_k=)`, 하네스 기본 5 / CLI `--top-k` 기본 10).

### 회수 계약 — 엔진은 회수하고 에이전트가 답변을 판정한다

`eval_recall`(`search.py:680`)이 평가·CLI 진입점이다. `recall` 결과를 **검수 상태(status)와
객체 종류(kind)만으로** 다섯 채널로 가른다 — reviewed 객체는 `results`, candidate 객체는
`candidates`, raw 청크는 `raw_excerpts`, reviewed `Insight`는 `advisories`(가로지르는 위험·교훈
곁들임), `ContextProjection`은 `projection_reuse`(status 무관 한 통로)다. 채널마다 top-5
(`EVAL_CHANNEL_TOP_K`, `search.py:80`). **회수한 객체를 엔진 판정으로 숨기는 층은 없다.**

2026-06-10의 다신호 답변 게이트(RRF 절대 점수 바닥 + 명부 매칭 OR 앵커 df 상한)와
`needs_clarification` 플래그는 폐지했다(#77). 엔진은 LLM이 아니라 "이 객체가 이 질문의 답인가"를
판단할 수 없고, 어휘 일치는 답 존재의 근거가 아니다. 게이트는 질의 단위 전부-아니면-전무
스위치로 작동해 총칭 질문의 검수 객체를 통째로 숨겼고, 잘 적재된 개념일수록 토큰이 흔해져 더
막혔다. 결정 기록은 [ADR 0008](adr/0008-engine-recalls-agent-judges-answers.md)에 있다.

판정을 뺀 자리에는 **결정론 사실**이 들어간다(#73). 어떤 값도 boolean 판정이 아니다.

- `query_tokens` — 질의 토큰 분해와 토큰별 `object_df`·`raw_df`
  (`compute_query_token_facts`, `search.py:628`). `object_df`는 raw 청크·`Insight`·
  `ContextProjection`을 뺀 색인 문서 수(`_document_frequency`, `search.py:597`), `raw_df`는
  raw 청크 수(`_raw_document_frequency`, `search.py:614`)다. 둘을 갈라야 "객체로는 회수되지
  않았지만 기획서 원문에는 있다"와 "어디에도 없다"가 구분된다. 토큰 순서·중복 제거는
  `tokenize()` 출력 그대로라(길이 필터 없음) 형태소 쪼개짐 때문에 부재가 오탐일 수 있음을
  에이전트가 직접 본다.
- 적중마다 `matched_query_tokens` — 질의 토큰 중 그 적중의 색인 본문(`tokenized_text`)에
  실제로 있는 것만(`_matched_query_tokens_by_id`, `search.py:653`). raw 발췌에도 붙는다.
- `scope` — `{context_id, origin}`. 자동 추론이면 `origin="inferred"`, 없으면 `"none"`이다.
  신고하는 값과 실제로 적용된 하드 필터가 같은 값이도록 `eval_recall`이 scope를 한 번 풀어
  `recall`에 넘긴다.

`eval_recall()`의 다섯 채널과 사실 필드는 explicit `search`와 서브커맨드 없는 자유질의가
키 하드코딩 없이 그대로 노출한다(`cli.py`의 `_run_search`가 응답을 통과시키고 신뢰 라벨만
덧입힌다). reviewed와 candidate는 각각 `results`와 `candidates`에 남아 관련성과 검수 상태가
섞이지 않는다. 일반 질문을 처리하는 설치 조회 스킬은 이 결과에서 핵심 객체를 고르고 `show`로
본문과 1-hop 이웃을 확인한 뒤 답할지 없다고 할지를 판정한다. `QueryRouter.answer()`는 이
recall을 소비하지 않으며 변경 이유·현재·과거·근거 사슬만 BrainStore에서 결정론적으로
계산한다(`query` 라우터의 `needs_clarification`은 결정론 충돌·모호성 신고라 이름만 같은 별개
필드다). 이 분리는 ranking·채널 top-K·scope 추론·색인 표면과 DB 형식을 바꾸지 않는다.

## 5. 확인 범위·한계

이 문서의 사실은 위 모듈을 **직접 읽어(read)** 확인했고, 4개 핵심 모듈
(`search`/`search_index`/`embedder`/`tokenize_ko`)이 깨끗하게 임포트되는 것까지 확인했다
(문법·모듈 로드 수준 무결).

코드 메커니즘 기준이라, 아래는 이 문서가 보장하지 않는다 — 별도 도구가 검증한다:

- **검색 품질·로직 정확성**: 합성 테스트(`tests/`, `pytest`)와 데이터 레포 골든셋
  (`project-brain eval`)이 검증한다. 이 문서는 "코드가 무엇을 하도록 쓰여 있는가"까지다.
- **형태소 분석기 실제 출력**: kiwipiepy가 한국어를 어떻게 쪼개는지는 외부 라이브러리
  영역이라 코드만으로는 검증할 수 없다. 버전이 고정돼 있어 결과는 결정론이며, 결합형
  규칙은 `tests/test_tokenize_ko.py`가 실제 출력으로 고정한다.
- **bge-m3 내부 동작**: sentence-transformers `encode`의 내부 토큰화·길이 자르기는 외부
  라이브러리 영역이다.

상수 캘리브레이션 값(`RRF_K`, `_GRAPH_SUPPORT_CAP`)의 근거와 실측 이력은 `search.py`
주석과 `docs/specs/2026-06-10-bb2-brain-search-layer-design.md`(설계 시점 히스토리)에 있다.
그 설계가 함께 고정했던 앵커 df 상한과 채널별 점수 바닥은 #77에서 폐지돼 코드에 없다.
