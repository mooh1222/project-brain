# ContextAI 인덱싱·검색 파이프라인 코드 분석

조사 대상: `/private/tmp/.../scratchpad/context-ai` (커밋 로컬 clone). 모든 근거는 `src/` 하위 상대경로:줄번호. "코드 실증"은 해당 소스에서 직접 확인한 것, "문서 주장"은 주석/docstring/README 근거, 별도 표기 없으면 코드 실증이다.

## 전체 흐름 요약

ContextAI는 흩어진 소스를 하나의 **binder**로 묶어 답하는 NotebookLM 스타일 LangGraph 에이전트다. 소스는 두 종류로 나뉜다. **색인 소스**(Wiki=Confluence, Text=붙여넣기, Jira)는 청킹 후 OpenAI `text-embedding-3-large`(3072차원)로 임베딩해 PostgreSQL+pgvector에 적재하고, **런타임 소스**(Code=GHE 저장소, logs/k8s/mcp/context7/web search)는 임베딩하지 않고 조회 시점에 도구로 직접 접근한다(특히 코드는 로컬 git clone + ripgrep). 검색은 **에이전트 주도**로, LLM이 `knowledge_search` 도구를 (여러 키워드 변형 쿼리로) 호출하면 → 소스별 병렬 검색(각 소스는 dense 벡터 + 메타데이터 LIKE "identity"를 RRF로 융합) → 소스 간 병합(관련도 점수 융합이 아니라 소스 우선순위+신선도 정렬) → LLM 관련성 필터(keep/drop 정밀도 패스) → citation 부착 순으로 흐른다. 형태소 분석기나 BM25 전문검색은 없다.

---

## 1. 소스별 인덱싱

### Wiki (Confluence) — 벡터 색인, 증분 지원
- `confluence_client.chunk_by_headings(storage_html, view_html, page_title)`가 **제목 기준(heading-scoped) 청킹**을 한다(`sources/confluence_client.py:446`). 콘텐츠는 저작 원본인 `body.storage`에서만 뽑고, 섹션 앵커 id는 렌더링본 `body.view`의 heading id에서만 읽는다 — `include`/`excerpt` 매크로가 제한 페이지 내용을 렌더링본에 끌어와 청크에 섞이는 유출을 막으려는 의도(`confluence_client.py:409-418`, `wiki_index_store.py:54-61`).
- 각 청크에 breadcrumb("Page > H1 > H2")를 앞에 붙여 문맥을 보존하고, 섹션이 `SECTION_CAP_CHARS=4000`자를 넘으면 400자 겹침으로 재분할한다(`confluence_client.py:185-186`, `:519-530`).
- 청크 메타데이터: `source`(페이지 URL), `title`, `page_id`, `heading_anchor`, `heading_path`, `binder_source_id`, `viewerless_access`, 타임스탬프(`wiki_index_store.py:1156-1167`, `page_metadata` :570).
- **증분 재색인**: `WikiPageManifestRow`가 페이지별 `content_hash`/`metadata_hash`를 저장(`db/models.py:105-134`). `_split_incremental_pages`가 hash 비교로 changed/unchanged/removed를 가른다(`services/wiki_source_lifecycle.py:190-201`). **바뀐 페이지만 재임베딩**하고, 안 바뀐 페이지는 temp 컬렉션으로 **재임베딩 없이 행 복사**(temp→live 스왑 패턴; `providers.py:641-680`의 copy/patch 함수), 사라진 페이지는 제거(`wiki_source_lifecycle.py:820-846`).

### Code (GHE) — 벡터 색인 없음
- 파일 첫 줄에 명시: "Does NOT use vector search - code analysis is done via Read/Grep/Glob tools"(`sources/code.py:1-5`, 코드 실증). GHE 저장소를 로컬 파일시스템에 `git clone`하고(`sources/repo.py`의 `clone_repo_for_source` 등, `code.py:27-38`), 조회는 ripgrep 기반 도구로 한다(`tools/code.py:1-14`, `code_grep`는 `:321`, ripgrep 기반 `:339-348`).
- 증분: `git pull` + remote SHA 지문(`_remote_ref_sha` `code.py:64`, `_code_fingerprint` `:56`)으로 변경 저장소만 동기화(`sync_sources` `:571`).

### Text (붙여넣기) — 벡터 색인
- `_chunk_text(chunk_size=6000, overlap=500)` — **문자 기반 고정 분할**, 의미/구조 경계 무시(`sources/text.py:71-84`). 제목은 첫 줄 앞 50자로 추출(`:86-91`). 메타데이터: `source`, `title`, `text_id`, `chunk_index`.

### Jira — 벡터 색인, 증분 지원
- 이슈를 섹션들로 만들어 임베딩(`sources/jira.py:599` `content_hash=hash_text(...sections...)`). 증분은 `JiraIssueManifestRow` `content_hash`/`metadata_hash`(`db/models.py:137-168`, `jira.py:780-796`).

### 색인 소스 공통 오케스트레이션
- 인덱싱→publish는 `binder_refresh_service`가 조율(`apiserver/services/binder_refresh_service.py:381-411`, `:721-757`), 예약 재색인은 `scheduled_reindex_service` + `BinderScheduledReindexSettingRow`(`db/models.py:82`).

---

## 2. 임베딩

- **모델**: OpenAI `text-embedding-3-large`, 싱글턴(`providers.py:350-358`, 코드 실증). **차원 3072** — 벡터 테이블 생성 시 `vector_size=3072` 하드코딩(`providers.py:414`).
- **호출 위치**: `langchain_openai.OpenAIEmbeddings`가 `base_url`로 호출. `base_url`은 `hack/base.yaml:28-29`에서 `https://us.api.openai.com/v1`이고 주석은 "OpenAI proxy (LY corp egress)". 즉 **사내 자체 호스팅 LLM/게이트웨이가 아니라, 사내 egress 프록시를 거쳐 진짜 OpenAI US API를 부르는 구조**로 보인다(config 필드 `openai_base_url` `config.py:298`, 채팅 기본 모델 `openai_model="gpt-5.5"` `:299`, 관련성 필터 모델은 별도 설정 가능 `:301`, `:531`).
- **한국어 대응**: 임베딩 단계에 한국어 전용 처리 없음. 다국어 모델인 `text-embedding-3-large`에 의존. 청크 4000자 상한도 "한국어처럼 토큰 밀도 높은 언어에서도 8191 토큰 임베딩 한계 아래에 들도록" 문자 기준으로 잡았다는 주석(`confluence_client.py:181-184`, 문서 주장이나 상수는 코드 실증).

---

## 3. 저장 (벡터스토어 / DB)

- **PostgreSQL + pgvector**를 `langchain-postgres`의 `PGVectorStore`/`PGEngine`로 사용(`providers.py:344`, `:370`, `:405-432`). 커넥션 풀 싱글턴.
- **컬렉션 = binder+source_type당 별도 테이블**: `bnd_{binder_id}_{source_type}`(`get_collection_name` `providers.py:361-364`). 예: `bnd_<id>_wiki`, `bnd_<id>_text`, `bnd_<id>_jira`. 컬럼은 id, content, `embedding vector(3072)`, 메타데이터 jsonb (SQL에서 `metadata->>` 접근 `providers.py:1071`, `:1086`).
- 벡터 테이블은 런타임에 `engine.ainit_vectorstore_table(...)`로 **동적 생성**되며 alembic이 관리하지 않는다(`providers.py:412-419`). 재색인 시 `_tmp` suffix 컬렉션을 만들어 채운 뒤 스왑(`create_vectorstore_async(..., suffix=)` `:382`, INSERT ... SELECT `:552`, `:599`).
- **alembic가 관리하는 관계형 스키마**(초기 마이그레이션 `alembic/versions/9a63c7f366b0_initial_ea_schema.py`가 `CREATE EXTENSION IF NOT EXISTS vector` 실행 `:38`): `binders`, `binder_sources`(config_json/published_config_json), `binder_reindex_runs`, `wiki_page_manifests`, `jira_issue_manifests`, `jira_issue_records`, `wiki_scope_sessions`/nodes, `confluence_permission_cache`, `user_tokens`, `chats` 등(`db/models.py` 전반). 즉 **벡터 데이터는 동적 pgvector 테이블, 메타/운영 데이터는 alembic 스키마**로 이원화.

---

## 4. 검색 (retrieval)

### dense 벡터
- 각 소스가 `vectorstore.asimilarity_search(query, k=...)` 호출. wiki/text는 후보 창 `candidate_window = max(n_results, 30)`(`text.py:24,459`, `wiki_index_store.py:1529`), jira는 `k=n_results` 그대로(`jira.py:112`).

### 소스 내부 하이브리드 (wiki, text만) — RRF
- **wiki와 text는 dense + "identity"를 RRF(k=60)로 융합**(`text.py:505`, `wiki_index_store.py:1563`; `_rrf_merge` `text.py:326-336`).
- **identity 검색은 BM25 전문검색이 아니라 메타데이터 필드 대상 SQL `LIKE` 부분문자열 매칭**이다(`providers.query_collection_identity_candidates_async` `providers.py:1045-1108`, `lower(metadata->>field) LIKE :pattern`). 가중 필드는 wiki가 `title(8)/heading_path(6)/heading_anchor(5)/page_id(6)/source(4)`(`wiki_index_store.py:1447`), text가 `title(8)/source(6)/text_id(6)`(`text.py:369`). **청크 본문(content)은 identity 매칭 대상이 아니다** — 제목·경로·id 같은 메타만 본다.
- identity 쿼리 term은 `query.casefold()` 전체 + `re.findall(r"\w+")` 토큰(`text.py:295-305`). 한국어는 `\w`에 포함되나 형태소 분리는 없다.

### jira — dense 단독
- jira `search`는 `asimilarity_search`만 쓰고 identity/RRF 레그가 없다(`jira.py:104-123`). wiki/text와 비대칭.

### 소스 간 병합 · 정밀도 패스
- 소스별 결과를 모은 뒤 **관련도 점수 융합이 아니라 소스 우선순위+신선도로 정렬**: `_sort_by_source_and_freshness`, 우선순위 `wiki(0) > jira(1) > text(2) > context7(3)`(`knowledge_service.py:161-176`).
- 그 후 **LLM 관련성 필터**(`_filter_results_with_llm`, `LLMChainFilter` keep/drop)가 dense 위의 정밀도 패스로 동작. 판정 실패(빈 출력/파서 오류/provider 오류)는 1회 재시도 후에도 실패하면 **drop(fail-closed)**(`knowledge_service.py:983-989`, `:1521-1636`). 이게 유일한 "리랭킹"이며 **cross-encoder 리랭커·BM25·tsvector 전문검색은 저장소 전체에 없다**(전 소스 grep: RRF는 `text.py`/`wiki_index_store.py`뿐, bm25/tsvector/rerank 히트 없음).
- top-k: 도구 기본 `n_results=5`(소스·쿼리당). 에이전트가 `queries: list[str]`로 다중 쿼리를 넣을 수 있어(`tools/knowledge.py:64-71`) 사실상 쿼리 확장은 LLM이 담당.

### 필터링 · binder 스코핑
- **날짜**: `date_from`/`date_to`를 wiki는 `modified_at`, text는 source `updated_at` 범위로 메타 필터(`knowledge_service.py:709-712`, `wiki_index_store.py:1530`, `text.py:461-467`).
- **binder 소스 스코핑**: `RunnableConfig`의 `binder_id`+`data_sources`에서 소스 결정(`tools/knowledge.py:35-38`, `:117`). 검색 시 `allowed_wiki_source_ids`/`allowed_text_ids`로 특정 소스 행만 대상(`knowledge_service.py:728-757`); 런타임 wiki scope 세션(`wiki_scope_sessions`)으로 페이지 범위 제한 가능.
- **Confluence 뷰어 권한 필터**가 검색 경로에 깊게 결합 — 조회자 PAT 기반 접근 검증 + `confluence_permission_cache`(`knowledge_service.py:393-517`, `:820-874`). "no-PAT" 경로는 index-time public 판정으로 fail-closed.
- jira 소스 가용성은 binder에 `jiras` 설정 + `jira_source_available_for_binder`일 때만 검색(`knowledge_service.py:717-722`).

---

## 5. 한국어 처리

- **형태소 분석기/토크나이저 없음** — 전 소스 grep에서 nori/mecab/konlpy/형태소 히트 0. 인덱싱 경로에 토크나이저를 일부러 안 넣었다고 명시(`confluence_client.py:181-184`, 문서 주장).
- 한국어 질의 처리 경로:
  1. **의미 검색은 다국어 OpenAI 임베딩에 위임** — dense 레그가 한국어 의미를 처리하는 사실상 유일한 축.
  2. **어휘 매칭(identity)은 `casefold` 부분문자열 LIKE** — 조사가 붙은 한국어("인덱싱은", "에이전트를")는 어간("인덱싱","에이전트")과 부분문자열이 겹치면 걸리지만 형태소 분해·불용어 제거는 없어 취약. 게다가 **본문이 아니라 제목/경로/id 메타에만** 적용.
  3. **쿼리 확장은 LLM이 대행** — 도구가 여러 키워드 변형을 한 번에 넣도록 지시(`tools/knowledge.py:66-70`).
- `agent/language.py`는 **응답 언어 강제용**(유니코드 스크립트로 Hangul→ko 판정 후 SystemMessage 부착; `agent/language.py:1-9`, `_is_hangul` `:26`)이지 질의 토큰화와 무관.

---

## 6. Citation (원문 인용) 생성

- **응답 로컬·메시지 소유** 방식. `content_and_artifact` 포맷 도구(`knowledge_search`/`knowledge_get`/`web_search`/`code_read`; `utils/citation.py:10-17`)가 결과와 함께 `{citations:[...]}` artifact를 반환(`tools/knowledge.py:50-61`, `:189-219`).
- `CitationTurn`이 슬롯을 부여(`get_citation_turn` `services/citation_turn.py`)하고, 에이전트는 본문에 `[ref:N]` 마커를 찍는다(`REF_MARKER_RE = \[ref:(\d+)...\]` `utils/citation.py:22`).
- **Wiki 섹션 딥링크**: `cite_url = source_url + "#" + anchor`(heading_anchor), 별도 `section` 라벨은 heading_path의 말단(leaf) heading으로 부여 — 한 페이지의 여러 섹션이 구분됨. 페이지 레벨 `source_url`은 dedup/권한 판정용으로 유지(`tools/knowledge.py:195-219`, `KnowledgeSearchResult.anchor/heading_path` `knowledge_service.py:121-127`).
- **Code 인용**: `build_github_permalink`로 저장소+SHA+경로(+라인 범위) permalink 생성(`tools/code.py:250`, `:303-308`).

---

## 검색 품질 관점 강점 / 약점

### 강점
- **다국어 dense 임베딩(3072차원)**으로 한국어를 별도 토크나이저 없이 의미 검색 — 초기 구현으로 합리적.
- **heading 기반 wiki 청킹 + breadcrumb + 섹션 앵커 딥링크** — 문맥 보존과 citation 정밀도가 높다(페이지가 아니라 섹션으로 점프).
- **증분 재색인**(content_hash manifest, 안 바뀐 페이지는 재임베딩 없이 복사) — 임베딩 비용·시간 절약.
- **RRF 하이브리드**가 dense가 놓치는 정확 일치(제목/heading/page_id/티켓성 토큰)를 구제.
- **LLM 관련성 필터가 fail-closed**(판정 실패 시 drop) — 미검증 벡터 히트가 문맥을 오염시키지 않음.
- **뷰어 권한 필터가 검색에 결합** — 접근 통제가 retrieval 단계에서 강제.

### 약점
- **진짜 전문검색(BM25/tsvector) 부재.** 어휘 레그(identity)가 **본문이 아닌 제목/경로/id 메타에만** LIKE로 걸린다. 본문에만 등장하는 희귀 한국어 용어는 어휘 구제가 전혀 없어 dense recall에 전적으로 의존 — 한국어에서 가장 큰 리스크.
- **형태소 분석 없음.** 조사·복합어가 붙은 한국어는 부분문자열 매칭이 깨지기 쉽고, dense도 형태 변형에 취약할 수 있는데 이를 받쳐줄 어휘 백업이 약하다.
- **소스 간 병합이 관련도 융합이 아니라 우선순위+신선도 정렬**(`knowledge_service.py:161`) — 매우 관련 높은 text/jira 히트가 한계선의 wiki 히트보다 아래로 갈 수 있다. LLM 필터와 소스별 top-k만이 이를 완화.
- **jira는 dense 단독**(identity/RRF 없음) — wiki/text와 비대칭. 티켓 키 정확 매칭이 retrieval에서 보장되지 않음(구조화 jira 도구가 별도로 보완하긴 함).
- **기본 top-k=5(소스·쿼리당)로 작다.** 후보창 30은 RRF 전 단계일 뿐, 최종적으로 LLM 필터→에이전트로 넘어가는 폭이 넓은 질문엔 빠듯.
- **LLM 필터의 지연·비용·recall 리스크.** 후보 문서 수만큼 per-doc LLM 호출(abatch)이라 비용이 스케일하고, 판정 실패 drop이 조용히 recall을 깎을 수 있다.
- **코드는 아예 임베딩 안 함** — "코드 검색"이 에이전트의 ripgrep 정규식/경로 추측에 의존. 자연어→코드 의미 검색이 불가.
- **text 청킹이 문자 고정(6000/500)** — 의미·구조 경계 무시. RRF `k=60` 고정, dense·identity 동일 가중으로 소스별 튜닝 여지 없음.
