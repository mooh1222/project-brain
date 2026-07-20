# project-brain 역량 인벤토리

> 대상 커밋: `main` (4a9d109). 코드에서 직접 실증한 사실은 **[코드]**, 문서·로드맵의 주장(설계/계획/실측 기록)은 **[문서]**, 내 판단은 **[추정]**으로 표기한다. 경로는 저장소 루트 기준.

---

## 1. 목적과 지식 모델

**정체성 [문서].** "프로젝트 도메인 지식 brain 엔진" — 과거 개발 과정·기획서·슬랙·PR·커밋을 기억하는 "동료의 머리통"을 목표로 한다(`docs/design-canonical.md:24-26`). 코드 질문 답변뿐 아니라 **개발 착수 컨텍스트 조립**이 동격 목적이다(`design-canonical.md:34-39`). 출발점은 Karpathy LLM Wiki의 "RAG는 매번 새로 찾고 아무것도 안 쌓인다 → 누적되는 구조화 산물을 유지하라"이고, 마크다운 위키 대신 **구조화 객체 + 검수 사다리**로 차별화한다(`design-canonical.md:53-62`).

**지식 모델 = 검수 상태·근거가 붙은 객체 코퍼스 [코드].** 객체는 종류(kind)별로 `brain/<kind>/id.json`에 저장되고, `BrainStore`가 유일한 읽기/쓰기 출입구다(`docs/search-internals.md:0장`, `store.py`). 모든 객체는 공통 필수 필드를 갖는다: `id, kind, schema_version, status, poc_priority, truth_role, title, created_at, updated_at, tags, evidence_refs`(`schema.py:5-8`).

**객체 타입 [코드] — 19종**(`schema.py:10-36`, `KIND_REQUIRED`). 로드맵의 "18 kind + Insight"와 일치.

| 그룹 | kind | truth_role |
|---|---|---|
| 근거·출처 | `EvidenceManifest`(source), `EvidenceRef`(reference), `SlackThread`(source), `SpecDocument`/`SpecRevision`/`SlideRef`(reference) | 원문·인용 책갈피 |
| 코드 앵커 | `CodeLocator`(reference) | repo/path/symbol + commit_sha |
| 도메인 | `DomainContext`, `GlossaryTerm`, `DomainMapping`(domain) | 기능 경계·용어·코드↔기획 매핑 |
| 시간·이벤트 | `EventLedgerRecord`(event), `TemporalFact`(fact), `DecisionRecord`(event) | "왜/언제 바뀌었나" |
| 종합 | `CurrentView`, `KnowledgePage`, `Insight`(synthesis) | 현재 상태·교훈·위험 |
| 색인·파생 | `ContextProjection`(index), `IndexRecord`(index) | 재사용 브리핑·색인 기록 |
| 검토 | `ReviewRecord`(review) | 승격 감사 기록 |

**근거 이중 체계 [코드].** 두 근거 필드가 역할이 다르다. `evidence_refs`는 라우터의 신뢰/원문가용/restricted 판정과 provenance에 쓰는 보조 사본, `source_object_ids`는 DecisionRecord·Insight의 **정본 근거**다. 그래서 DecisionRecord·Insight의 `evidence_refs`는 빈 값이 정상이고 non-empty 강제는 GlossaryTerm·DomainMapping에만 건다(`ROADMAP.md:263-266`, `schema.py:262` 주석). `Insight`는 `source_object_ids` 개수까지 검증한다(`schema.py:253-262`).

**검수 사다리(status) [코드].** `candidate → reviewed → superseded/archived/rejected`(`schema.py:62`, `OBJECT_STATUS_VALUES`). "쓰면서 점점 정확해지는" 흐름 — candidate로 노출하다 실사용 중 promote(`design-canonical.md:58-61`).

**ingest/promote 흐름 [코드].**
- `ingest`: 객체 묶음을 스키마 검증 + lint로 원자적 적재(`cli.py:971`, `ingest.py`).
- `build`: "구조화 노트 → 객체 묶음" 조립 자동화. id 파생·연결·끊긴 참조 검사는 엔진, 판정은 노트가 담당. `build_decisions`가 노트 `decisions[]`를 `DecisionRecord`+`EvidenceRef`로 결정론 조립하고 매핑↔결정 양방향 링크(lint 8c)를 자동 충족(`assembly.py`, `ROADMAP.md:180-202`).
- `promote`: candidate → reviewed 승격 + `ReviewRecord` 생성(reviewer/reviewed_at은 호출자 주입, 도메인·시점 상수 0)(`promote.py:70-75`). `select_vouched_candidates`가 reviewed 매핑이 보증하는 candidate 용어를 기계 선별(`promote.py:46-49`).

**L0 raw 층 [코드].** 기획서 원문을 `raw/sources/<context>/*.md`로 추적·색인하되, 지식 층("brain이 안다고 답하는 것")은 구조화 객체로만 한정 — AI가 유지보수하는 마크다운 문서 층은 안 만든다(`design-canonical.md:68-70`).

---

## 2. 검색 스택 상세 [주로 코드]

`docs/search-internals.md`가 모든 사실에 `파일:줄` 근거를 달아둔 구현 참조 문서이고, 내가 원본 모듈로 교차 확인했다.

**임베딩(`embedder.py`).** 실모델 `BAAI/bge-m3`, sentence-transformers, **1024차원 L2 정규화** 벡터(`embedder.py:26,29,102`). 벡터 테이블 정의 `embedding FLOAT[1024]`와 강결합(`search_index.py:100`). 결정론 장치로 `torch.set_num_threads(1)` 고정(`embedder.py:80`), 배치 크기 8(MPS 4GB 한계 회피, `embedder.py:99-104`). 테스트용 `StubEmbedder`는 SHA-256 시드 가우시안 벡터로 모델 없이 결정론 보장(`embedder.py:56-60`, `PROJECT_BRAIN_EMBEDDER=stub`).

**한국어 토큰화(`tokenize_ko.py`).** 폴백 사다리 `mecab-ko(1순위) → kiwipiepy(기본 동봉) → 정규식(최후)`(`tokenize_ko.py:100-114`). **색인과 검색이 같은 `tokenize()`를 공유**해 매칭 어긋남 방지. camelCase/snake_case/`::`/경로 구분자로 영문·심볼 분해 + 원형 보존(`tokenize_ko.py:145-174`). 핵심 비대칭: **토큰화 결과는 BM25 레인에만, 임베딩은 토큰화 전 원문 표면**을 넣는다.

**색인 빌드(`search_index.py`).** 단일 SQLite DB에 테이블 4개(`SCHEMA_VERSION=4`, `search_index.py:80-108`): `documents`(원문+토큰화 텍스트) / `documents_fts`(FTS5 `unicode61`, BM25) / `documents_vec`(sqlite-vec `vec0`, 1024차원 KNN) / `meta`(모델명·토크나이저·코퍼스 지문). **전체 재구축만 존재**(DB 삭제 후 재생성) — 증분 갱신 없음(`search_index.py:111`). 임베더 미주입 시 FTS만 색인(벡터 선택적). store 객체뿐 아니라 raw 청크(500토큰·15% 겹침 결정론 청킹)도 색인(`raw_chunks.py:107-124`). **신선도 가드**: `corpus_fingerprint`가 현재 코퍼스와 다르면 `StaleIndexError`로 거부하고 rebuild 안내 — 낡은 색인의 조용한 오답 차단(`search.py:315-331`, `search_index.py:324-332`).

**검색 융합(`search.py`, 본체 `recall()` `search.py:334`).**
1. **두 채널 각 50개**: BM25(`search_bm25`) + 벡터 KNN(`search_vector`), `CHANNEL_TOP_N=50`(`search.py:71`).
2. **RRF 융합**: 점수 아닌 순위로 `score = Σ 1/(60+rank)`, `RRF_K=60`, 융합 후 `FUSED_TOP_N=30`(`search.py:68,136-153`). BM25·벡터 척도가 달라 순위 기반이 안전.
3. **그래프 1-hop 상호지지 재정렬**: top30 안에서 참조 필드(코드위치·용어·결정·매핑)로 서로 연결됐는지 보고, 아웃바운드 도달 수 `graph_support`를 상한 `_GRAPH_SUPPORT_CAP=2`로 잘라 1순위 정렬 키. 점수 안 더하고 **순서만** 바꿈. 허브 객체 굳어짐 방지가 상한 이유(`search.py:109,226-241`).
4. **레인 분리**: raw 청크·`Insight`·`ContextProjection`은 객체 레인과 따로 융합해 뒤에 붙임 — 자유 텍스트가 객체 자리 잠식·그래프 신호 약화 방지(`search.py:95,378-404`).
5. **scope 좁히기**: 질의가 기능명을 단일 특정하면 `DomainContext` 하드 필터 + `search_bm25_scoped`(후보 집합 내 df 재계산, scope 밖 문서가 순위 못 흔들게)(`search.py:271,392-393`).

**다신호 답변 게이트 + 명부 인식 앵커(`_gate_pass`, `search.py:671`).** 게이트 boolean = **RRF 절대 점수 바닥 AND (명부 매칭 OR 표면 앵커)**.
- **명부 매칭(`registry_match`)**: 질의에 GlossaryTerm term/synonyms/aliases 표면형(3자+)이 통째 부분문자열로 등장하면 참(`compute_query_signals`가 store로 계산).
- **표면 앵커(`anchor_df`)**: 질의 최희소 토큰의 문서 빈도, `_ANCHOR_DF_MAX=30`. 명부 매칭 없을 때의 폴백.
- 이 OR 보강이 "럭키박스 거짓음성"의 근본 수정 [문서/코드] — "럭키"·"박스"가 흔한 토큰이라 빈도만 보면 차단되던 잘 적재된 엔티티를 명부 표면형으로 통과시키고, 미적재 엔티티(크리스마스 등, 빈도 0·명부 미등재)는 여전히 차단해 "근거 없으면 없다" 유지(`docs/search-internals.md:4장`, `ROADMAP.md:282-301`). 빈도 무관이라 코퍼스 성장에 안 무너짐(빈도 조정 4안이 실패한 근본 원인 제거).
- reviewed 통과 0건이면 `needs_clarification` ON.

**`eval_recall`(`search.py:707`)이 채널 분리 진입점**: reviewed→`results` / candidate→`candidates` / raw→`raw_excerpts` / Insight→`advisories` / projection→`projection_reuse`.

---

## 3. 소비 방식

**로컬 CLI `project-brain` [코드].** 서버·데몬·HTTP 없음 — `grep`으로 flask/fastapi/uvicorn/socket/websocket/daemon 전부 0건 확인. 순수 로컬 CLI + git 추적 데이터. 최상위 명령(`cli.py:969-1004`): `build, ingest, index, session, search, show, eval, lint, audit, promote-auto, promote, install, doctor, bootstrap, projection, graph, stale-check, mark-checked` + 서브커맨드 없는 기본 `query` 경로.

**사용 모델 [문서].** 사용자가 CLI를 직접 안 쓴다 — "나는 너에게 질문하고 너(어시스턴트)가 cli를 사용한다"(`design-canonical.md:30-33`). 즉 CLI는 에이전트 도구다.

**에이전트 스킬 통합 [코드].** `install`이 `templates/<skill>/` 디렉토리 4종을 통째 walk해 주입: `query`(조회) / `ingest`(적재) / `session-ingest`(과거 세션 추출) / `audit`(코퍼스 건강검진)(`README.md:50-55`, `src/project_brain/templates/`). SKILL.md 한 장이 아니라 `references/`·`scripts/`까지 주입(`__pycache__`·`fixtures`·`test_*.py` 제외). 변수 치환은 `{{PROJECT}}`·`{{BRAIN_ROOT}}`·`{{DEFAULT_BRANCH}}`·`{{REPO}}` 4개만, 나머지 도메인 예시는 리터럴(`ROADMAP.md:236`). **manifest 파일단위 추적·보존·채택**: `.project-brain-manifest.json`이 파일별 주입 기록, 디스크 내용이 렌더 결과와 같으면 채택, 사용자 수정·manifest 밖 파일은 보존(`--force`도 manifest 밖은 안 건드림)(`ROADMAP.md:238-244`). 스킬은 채널을 신뢰도별로 해석하는 계약을 담는다 — reviewed=확신, candidate="확인 필요" 라벨, raw="발췌 자료", advisories="참고", projection="재사용 후보(미검증)"(`templates/query/SKILL.md` 3장).

**context projection 재사용층 [문서/코드].** 한 기능 안에서 조립한 착수 브리핑을 `ContextProjection`(format=prompt_payload)으로 저장해 재방문 시 재조립을 줄이는 별도 검색 레인(`projection_reuse` 채널). `source_content_hash`가 시각·버전 메타를 빼고 의미 내용만 해시해 무의미한 stale 오판 방지(생성식 2곳·검증식 1곳이 `hash_utils.source_content_hash` 단일 헬퍼 공유)(`ROADMAP.md:72-79,99-105`, `context_projection.py`).

**2-레포 모델 [문서/코드].** 엔진(이 레포) = 스키마·적재·lint·색인·검색·라우터·평가 하네스 + **합성 데이터 테스트만**. 데이터(각 프로젝트 레포 `brain/`) = 코퍼스(objects/raw) + 골든셋(`eval_scenarios.json`) + 실측 가드(`brain/checks/`) + 색인(`.brain-local/`, 로컬). 경로는 루트 `.project-brain.json` config가 해석(명시 인자 > config > `ConfigError`)(`design-canonical.md:105-117`, `config.py`, `README.md:13-21`). 엔진은 `uv tool install -e`로 **편집 설치**라 코드 수정이 모든 프로젝트에 즉시 반영.

**접근 제어 실집행 [코드].** `router._restricted_for`가 evidence 사슬을 타 `EvidenceManifest.redaction_status != "approved"`면 restricted 처리 — **fail-closed**(None·키 누락 포함 전부 차단, `router.py:758-769`). 단 이건 **콘텐츠별 단일 신뢰 라벨**이지 사용자별 권한이 아니다: 스키마에 `acl`·`sensitivity` 필드가 있으나 **router.py에서 `acl`/`sensitivity`를 읽는 코드는 0건**(grep 확인). 즉 "누가 볼 수 있나"의 다중 사용자 권한 판정은 실집행되지 않는다.

---

## 4. 품질 체계

**합성 테스트 [코드].** `tests/`에 `def test_` 함수 **556개**(로드맵의 "합성 556 통과"와 일치). 27개 테스트 모듈이 각 엔진 모듈 대응. 결정론 강제 — `StubEmbedder`/`PROJECT_BRAIN_EMBEDDER=stub` 사용 53회, 실모델 금지(`CLAUDE.md` 개발 루프, grep 확인). 실코퍼스 불필요(`.venv/bin/python -m pytest tests/ -q`).

**골든셋 eval [코드].** `eval_harness.py`가 데이터 레포 `eval_scenarios.json`을 돌린다. 판정 키: `top5_any`, `any_channel_top5_any`, `advisories_top5_any`, `projection_reuse_top5_any`, `linked_any_groups`, `max_results`, `no_answer`(게이트 작동 = `needs_clarification=True` + results 0건)(`eval_harness.py:32,64-73,133-164`). 시나리오 파일 오타를 조용히 통과시키지 않게 `ASSERTION_KEYS` 미허용 키 거부(`eval_harness.py:25,58`). `eval --check-ids`는 기대 id 실존만 검사(모델 불필요)(`README.md:65`).

**실측 가드 [문서].** 데이터 레포 `brain/checks/`가 PATH의 `project-brain`만 subprocess 호출(엔진 import 0)해 CLI 종단을 검증(`design-canonical.md:115-116`). 엔진 수정 후 검색·색인·라우터를 건드렸으면 데이터 레포에서 `unittest` 가드 + `index rebuild` + `eval`(골든셋, 실모델) 회귀가 완료 조건(`CLAUDE.md` "엔진 수정 후 실코퍼스 회귀").

**읽기 전용 점검 4종 [코드/문서].** `lint`(끊긴 참조=아웃바운드 무결성) · `graph isolated`(고립 잎=인바운드 0) · `stale-check`(코드 변경→갱신 후보, 미머지 앵커는 `unmerged_anchors`로 라벨해 거짓 신호 제거) · `doctor`(환경). `mark-checked`가 유일한 stale 해소(쓰기, commit_sha/verified_at 갱신). `audit`이 셋을 한 패스로 돌려 stale 캐시를 채운다(`README.md:70-75`, `ROADMAP.md:87-92,168-178`).

**검수 정책 [문서].** B+C 하이브리드 — 근거 확실하면 에이전트 자동 reviewed, 애매하면 candidate, 완전 애매만 사용자. 완전 자동 supersede·hook은 안 함(stale Step 3 보류)(`ROADMAP.md:174,360-369`).

---

## 5. 강점 3 / 약점 3 (서버형 팀 제품 대비)

전제: 비교 대상 = 멀티유저 계정, 실시간 소스 동기화(슬랙/지라/깃 웹훅), 사용자·역할별 권한 모델을 갖춘 서버형 팀 지식 제품.

### 강점

1. **근거·검수 상태가 1급 타입인 신뢰 모델 [코드].** 모든 답이 채널(reviewed/candidate/raw/advisories)로 갈리고, 게이트가 "근거 없으면 없다"를 강제하며(`search.py:671`, `needs_clarification`), restricted 판정이 fail-closed다(`router.py:767`). 대다수 팀 RAG 제품이 검색 상단을 그냥 답으로 뱉는 것과 달리, **미검수/미승인 콘텐츠를 구조적으로 구분**한다. [추정] 헛소리(hallucination) 억제가 설계 중심에 박혀 있어 신뢰가 중요한 팀에 유리.

2. **한국어 도메인에 특화된 하이브리드 검색 [코드].** mecab-ko/kiwi 형태소 + 색인·검색 토큰화 공유 + camelCase/snake_case 분해로 한↔영 코드명 갭을 다룬다(`tokenize_ko.py`). 명부 인식 앵커 게이트는 **빈도 무관**이라 코퍼스가 커져도 안 무너진다(`search.py`, 빈도 조정 4안 실패 후 도출). 범용 임베딩만 쓰는 영어 중심 제품 대비 한국어 코드·기획 혼재 코퍼스에서 강점.

3. **결정론과 재현성 [코드].** 색인은 언제든 재생성 가능한 파생물, 전체 재구축만 존재(`search_index.py:111`), 임베딩 스레드 고정(`embedder.py:80`), 조립·해시가 단일 `now`·단일 헬퍼로 churn 0(`hash_utils`, `assembly.py`). 556개 합성 테스트가 실모델 없이 돈다. [추정] 서버형 제품은 실시간 인덱싱·분산 상태 때문에 이런 완전 재현성 확보가 어렵다.

### 약점

1. **멀티유저·권한 모델 부재 [코드].** 서버·계정·세션이 없다(HTTP/daemon grep 0건). 스키마에 `acl`·`sensitivity`가 있으나 **router가 읽지 않아 사용자별 접근 제어가 실집행 안 됨**(grep 0건). restricted는 콘텐츠 단일 신뢰 라벨일 뿐. 팀 승격 권한(각자 promote vs 검수자 지정)은 미결 상태(`design-canonical.md:131`, `ROADMAP.md:325-332`). → 역할별 열람 제한이 필요한 팀엔 그대로 못 쓴다.

2. **실시간 소스 동기화 없음, 수동 배치 적재 [코드/문서].** 색인은 증분 갱신이 없고 전체 재구축뿐(`search_index.py:111`), 적재는 에이전트가 세션에서 노트를 만들어 `build`/`ingest`로 태우는 수동 흐름. 슬랙/지라/깃에 붙는 자동 커넥터·웹훅이 없다(EvidenceRef의 slack/jira/pr는 수기 참조). 세션 종료 hook 자동 저장 제안도 미구현(추후 논의, `ROADMAP.md:322-323`). → 최신 슬랙·PR을 실시간 흡수하는 서버 제품 대비 코퍼스가 사람 손을 타야 갱신된다.

3. **단일 소비처·수동 협업 경계 [문서/코드].** 실제 소비처가 bb2 하나뿐이라 도메인 예시가 리터럴로 박혀 있고(`ROADMAP.md:234`), 데이터 공유는 git 레포 push/pull에 의존한다(실시간 협업·동시 편집·충돌 병합 메커니즘 없음 — 데이터가 그냥 git 추적 JSON). 스킬 트리거 어휘도 프로젝트마다 수동 맞춤이 필요(`README.md:51-55`). [추정] 혼자 시험 제작 단계(`design-canonical.md:41`)의 산물이라, 팀 규모로 켜면 동시 적재 시 JSON 병합 충돌·id 경합 같은 문제가 드러날 가능성이 크다(현재 코드에 락·트랜잭션·충돌 해소 없음).

---

## 부록 — 핵심 근거 파일

- 설계 정본: `docs/design-canonical.md` / 히스토리: `ROADMAP.md` / 구현 참조(파일:줄 근거): `docs/search-internals.md`
- 검색: `src/project_brain/search.py`(recall 334, 게이트 671, eval_recall 707), `search_index.py`, `embedder.py`, `tokenize_ko.py`
- 지식 모델: `schema.py`(kind 10-36, enum 62-90), `store.py`, `assembly.py`, `promote.py`
- 소비·라우팅: `cli.py`(명령 969-1004), `router.py`(restricted 758-769), `templates/{query,ingest,session-ingest,audit}/`
- 품질: `tests/`(556 test 함수), `eval_harness.py`, `graph.py`, `stale_check.py`
