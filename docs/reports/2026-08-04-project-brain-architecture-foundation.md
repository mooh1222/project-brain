# Project Brain 전체 지도 기반 공사 완료 보고서

- 날짜: 2026-08-04
- 기준 HEAD: `76827c3fe3e09104e657db515e0b21a37eb55b18`
- 작업 위치: 격리된 detached worktree
- 범위: 아키텍처 지도, 19종 객체 계약, 실행 가능한 JSON 예시, 자동 드리프트 점검
- 제외: production 동작 변경, 소비 프로젝트 실데이터, Task 18, 발표 자료, 커밋·push

이 보고서는 살아 있는 설계 정본을 하나 더 만들기 위한 문서가 아니다. 구현 중 확인한 근거,
문맥 없는 새 에이전트 리허설, 독립 검토와 최종 실행 결과를 남기는 작업 영수증이다. 현재 구조를
찾을 때는 `docs/architecture/README.md`, 현재 동작을 확정할 때는 production 코드·테스트·CLI로
돌아간다.

## 코드 기반 정답표

### 시나리오 1 — 질문이 답변이 되는 경로

최소 정답은 다음과 같다.

1. 엔진 레포는 범용 코드와 합성 테스트를, 소비 데이터 레포의 `brain/`은 실제 객체·raw·checks와
   골든셋을 가진다.
2. `src/project_brain/cli.py::_run_query()`가 config 우선순위에 따라 `brain_root`를 해석하고
   `BrainStore.load()`로 객체 코퍼스를 읽는다. stale-set cache와 실제 존재하는 index DB도 선택적으로
   읽어 `router.QueryRouter`에 넘긴다.
3. `QueryRouter.answer()`가 `intent.classify_query()`로 의도를 분류한 뒤 현재 store의 정확 객체 경로를
   먼저 구성한다. `QueryRouter._recall()`은 DB가 있을 때만 `search.eval_recall()`을 호출하며, DB가
   없거나 stale이면 회상을 생략하고 정확 경로·보수적 폴백을 유지한다.
4. `search` 명령은 이 선택적 보강과 다르다. `search.eval_recall()`을 직접 노출하므로 DB가 없거나
   현재 코퍼스 지문과 다르면 rebuild 안내와 함께 실패한다.
5. `status.py`와 `router.py`가 검수 상태와 stale advisory를 조립한다. EvidenceManifest의
   `redaction_status`에 따른 restricted 신뢰 라벨은 `_restricted_for()`를 호출하는 일부 query
   경로에만 붙는다. EventLedgerRecord·TemporalFact의 여러 정확 경로와 `search` 다섯 채널에는 일반
   객체 수준 redaction 라벨이 없다. QueryRouter는 principal을 받지 않으므로 이 부분 적용도
   사용자별 ACL 집행으로 설명하면 틀리다.

직접 근거:

- production: `src/project_brain/cli.py::_run_query`, `src/project_brain/router.py::QueryRouter.answer`,
  `QueryRouter._recall`, `src/project_brain/intent.py::classify_query`,
  `src/project_brain/search.py::eval_recall`, `src/project_brain/search.py::_guard_index_freshness`
- tests: `tests/test_cli.py::test_cli_query_path_unchanged`,
  `test_explicit_query_subcommand_routes_without_becoming_query_text`,
  `test_cli_query_with_db_enables_recall`, `tests/test_router.py::test_unknown_no_index_falls_back_to_no_match`,
  `test_stale_db_implementation_fallback_returns_only_aggregate`,
  `tests/test_search.py::test_recall_raises_on_stale_index`

### 시나리오 2 — 한국어 tokenizer 변경

최소 정답은 다음과 같다.

1. 주 변경점은 `src/project_brain/tokenize_ko.py`다. `search_index.py`가 색인 생성과 BM25 질의 양쪽에서
   같은 `tokenize()`를 쓰고, `search.py`도 scope·anchor 신호 계산에 이를 쓴다. 색인/질의 대칭과
   정규식 fallback 결정론을 함께 지켜야 한다.
2. 먼저 `tests/test_tokenize_ko.py`, `tests/test_search_index.py`, `tests/test_search.py`에 실패하는 표적
   테스트를 만들고, 구현 뒤 엔진 전체 pytest를 실행한다. 합성 테스트에서는 실모델 대신
   `StubEmbedder` 또는 `PROJECT_BRAIN_EMBEDDER=stub`을 쓴다.
3. tokenizer는 실제 검색 품질과 색인 입력을 바꾸므로 소비 데이터 레포의 `brain/checks`, 실모델
   `index rebuild`, `eval`까지 필요하다. 검증할 checkout의 `PYTHONPATH`와 `.venv/bin/python`을 함께
   고정한다.
4. router의 색인 이후 결과 배치만 바뀌는 변경과 달리, tokenizer 변경은 기존 DB를 그대로 둔 채
   eval하면 안 된다. 실모델 rebuild가 필요한 변경이다.

직접 근거:

- production: `src/project_brain/tokenize_ko.py::tokenize`,
  `src/project_brain/search_index.py::rebuild`, `search_bm25`, `search_bm25_scoped`,
  `src/project_brain/search.py::compute_query_signals`
- tests: `tests/test_tokenize_ko.py`, `tests/test_search_index.py`, `tests/test_search.py`
- 작업 라우팅: `docs/architecture/change-map.md`의 한국어 tokenizer 행과 index rebuild 판단

### 시나리오 3 — CodeLocator 누락과 과거 읽기·신규 쓰기

최소 정답은 다음과 같다.

1. `schema.KIND_REQUIRED["CodeLocator"]`는 저장 객체 shape의 일부일 뿐 신규 쓰기 계약 전체가 아니다.
   최종 저장·일반 lint에는 `verified_at`가 필요하지만 `validate_mutation_input_schema()`는 verifier가
   채우기 전 CodeLocator 입력에서만 그 필드 누락을 허용한다.
2. 새 locator, 좌표가 바뀐 locator, `mark-checked`는 `mutation.MutationService`에서 비어 있지 않은
   `verified_quote`, 명시적 repo context, exact 40/64자 commit SHA, 실제 blob/path/symbol/quote 검증을
   요구한다. `code_verify.verify_locator_for_write()`가 성공하면 엔진이 `verified_at`와 표준 title을
   확정한다.
3. 좌표가 그대로인 기존 객체는 과거 quote 누락이나 축약 SHA를 읽고 보존할 수 있다. 이는 신규 ID나
   좌표 변경 쓰기의 완화가 아니다. 새 객체·좌표 변경은 각각 `quote_required`, exact commit 검증 실패를
   그대로 내야 한다.
4. shape 출발점은
   `src/project_brain/templates/ingest/references/object-templates/kinds/CodeLocator.template.json`, 정상
   write 예시는 `tests/test_object_contract_templates.py::test_code_locator_template_passes_official_write_gate_and_links_code_edges`,
   반례 setup은 `object-templates/invalid/manifest.json`에서 찾는다.

직접 근거:

- production: `src/project_brain/schema.py::KIND_REQUIRED`, `validate_mutation_input_schema`,
  `src/project_brain/mutation.py::MutationService.plan`,
  `src/project_brain/code_verify.py::verify_locator_for_write`
- tests: `tests/test_mutation.py::test_new_locator_is_verified_and_external_time_and_title_are_ignored`,
  `test_unverified_locator_missing_quote_fails_at_quote_gate_not_schema`,
  `test_coordinate_changed_locator_is_reverified`, `test_unchanged_ingest_locator_preserves_engine_fields`,
  `tests/test_code_verify.py`, `tests/test_object_contract_templates.py`의 legacy quote·short-SHA 짝 테스트

## 문맥 없는 새 에이전트 리허설

세 답변자는 모두 `fork_turns="none"`으로 실행한다. 대화 설계나 이 작업의 이전 메시지는 넘기지 않고,
worktree의 `AGENTS.md`와 저장소만 준다.

공통 지시:

```text
작업 위치는 /Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation 이다.
이 대화의 이전 문맥은 주어지지 않았다. 먼저 AGENTS.md와 그 파일이 위임한 필수 지침을 읽고,
저장소의 현재 문서·production 코드·직접 테스트만 근거로 아래 시나리오에 답하라. 날짜가 붙은 plan
하나를 현재 정본으로 쓰지 마라. 엔진 레포와 소비 데이터 레포의 책임을 구분하고, 관련 production
symbol과 직접 test path를 제시하라. 파일은 수정하지 말고 분석 결과만 한국어로 보고하라.
```

### 답변자 1 — query end-to-end

- task name: `cold_query_path_v1`
- fork context: `none`
- 최종 관문 사용 여부: 제외. 답변 내부에 저장소 밖 memory 사용 표기가 있어 길찾기 독립성 조건을
  만족하지 못했다. 아래 전문은 발견 과정 기록으로만 남기며, 최종 판정에는 뒤의 무기억 재실행만 쓴다.
- 개별 질문:

```text
사용자 질문이 `project-brain query`의 답변 JSON이 되기까지 경로를 설명하라. config, store,
의도 분류와 정확 객체 경로, 선택적 의미 회상, 검수 상태·redaction·stale 표시를 빠짐없이 연결하라.
`query`와 `search`의 fresh-index 요구 차이, 현재 principal별 ACL 집행 여부도 분명히 판단하라.
```

<details><summary>답변 전문</summary>

````markdown
## 결론

`project-brain query`는 **정확 객체 경로를 먼저 실행하고, 신선한 색인이 있을 때만 의미 회상을 덧붙이는 구조**입니다. 따라서 색인이 없거나 낡아도 대부분의 정확 경로는 계속 동작합니다. 반대로 `search`는 의미 회상 자체가 본체라서 **신선한 색인이 필수**입니다.

현재 `query`와 `search` 모두 **principal별 ACL을 집행하지 않습니다.** `redaction_status`는 일부 `query` 경로에서 `restricted` 신뢰 경고를 만드는 데만 쓰이고, 객체 내용 자체를 가리거나 차단하지 않습니다.

## 전체 호출 경로

```text
사용자 질문
  → 에이전트가 project-brain query 실행
  → cli.main()
  → _run_query()
  → config 해석
  → BrainStore 로드 + stale-set 로드
  → QueryRouter.answer()
  → 용어 정규화 + 의도 분류
  → 의도별 정확 객체 수집
  → 신선한 DB가 있으면 eval_recall()로 선택적 보강
  → 검수·redaction·stale 상태 조립
  → json.dumps()로 stdout 출력
```

1. [cli.py:1841](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/cli.py:1841)의 `main()`은 `project-brain query "..."`를 `_run_query()`로 보냅니다. 알려진 명령이 아니면 bare 질의도 같은 경로로 보냅니다.

2. [cli.py:163](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/cli.py:163)의 `_run_query()`가 `brain_root`, 선택적 `db`, `current_head`, 임베더를 해석합니다.

3. `.project-brain.json`은 현재 디렉터리부터 상위로 찾습니다. 상대 경로는 config 디렉터리 기준으로 절대화하며, 우선순위는 **명시 인자 > config > ConfigError**입니다. 관련 production symbol은 [config.py:28](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/config.py:28)의 `find_config()`, [config.py:39](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/config.py:39)의 `load_config()`, [config.py:66](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/config.py:66)의 `_resolve()`입니다.

4. [store.py:37](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/store.py:37)의 `BrainStore.load()`가 공유 잠금을 잡고 kind별 객체 디렉터리를 읽어 ID→객체 map을 만듭니다. 실제 객체 경로는 [store.py:141](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/store.py:141)의 `_KIND_DIR`와 `object_path()`가 결정합니다.

   객체 정본은 `objects/**`만이 아닙니다. `raw/manifests/**`, `indexes/context_projections/**`, `indexes/records/**`, `views/**`도 store 객체입니다. `raw/sources/**`와 `eval_scenarios.json`은 `BrainStore` 객체 스캔에서 제외됩니다.

   주의할 점은 load 자체가 전체 schema/lint를 다시 돌리지는 않는다는 점입니다. 파일 구조·JSON·ID 중복은 막지만, 의미 계약은 앞선 ingest/audit 상태를 전제로 합니다.

5. `_run_query()`는 `.brain-local/stale-set.json`을 읽어 mapping ID별 advisory로 바꾼 뒤 `QueryRouter`에 넣습니다. DB는 명시됐거나, config DB가 실제로 존재할 때만 라우터에 전달됩니다.

6. [router.py:92](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/router.py:92)의 `QueryRouter.answer()`가 reviewed `GlossaryTerm.avoid` 치환표로 질의를 정규화하고 [intent.py:28](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/intent.py:28)의 `classify_query()`로 복수 의도를 분류합니다.

7. 최종 dict는 [router.py:493](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/router.py:493)에서 다음 키로 조립됩니다.

   - `query`, `canonical_query`, `intents`
   - `status`
   - `candidate_object_ids`, `promotable_candidate_ids`
   - `source_object_ids`
   - `sections`, `advisories`, `warnings`
   - `needs_clarification`

   `_run_query()`가 이를 그대로 `json.dumps(..., ensure_ascii=False, indent=2)`로 출력합니다. `search`와 달리 `query` 최상위에는 `ok` 필드가 없습니다.

## 의도별 정확 객체 경로

| 의도 | 현재 production 경로 |
|---|---|
| `why_changed` | reviewed `EventLedgerRecord`를 시간순으로 읽고, 여기서 파생된 reviewed `TemporalFact`를 붙입니다. 용어·매핑이 정확히 맞으면 해당 anchor를 가리키는 reviewed `DecisionRecord`도 붙입니다. EventLedger 쪽은 질의별로 좁히지 않고 전량 읽는 현재 한계가 있습니다. |
| `current_status` | reviewed `TemporalFact`를 release/feature/surface/platform/module 범위로 좁힌 뒤 `valid_until`이 없는 현재 fact만 남깁니다. `supersedes`로 충돌을 풀고, 못 풀면 경쟁 fact를 모두 노출하며 확인 필요로 표시합니다. `CurrentView`의 source fact가 없거나 미검수·종료 상태면 stale 경고를 냅니다. |
| `as_of_history` | 같은 범위 필터를 적용한 reviewed `TemporalFact` 전체를 반환합니다. |
| `implementation_location` | 중요한 예외입니다. locator 상세는 정확 문자열 스캔이 아니라 `eval_recall()` 적중과 그래프의 `linked.code_locators`에 의존합니다. DB가 없거나 낡으면 상세를 숨기고 `CodeLocator` 개수와 `details_omitted_reason=no_db|stale_db`만 냅니다. |
| `glossary_meaning` | 질의에 나온 term/synonym이 참조된 reviewed `DomainMapping`을 정확히 찾고 `meaning`, `boundary`, `caveats`, code locator ID를 냅니다. candidate `GlossaryTerm`은 term/synonym/alias 정확 매칭으로 별도 `확인 필요` 채널에 둡니다. 나머지 `DomainContext`·`GlossaryTerm`은 fresh recall top-K를 쓰고, recall이 없으면 reviewed 전량 폴백입니다. |
| `evidence_provenance` | 함께 분류된 의도의 수집기를 재사용하고 각 객체의 `review_record_id`, `evidence_refs`를 따라갑니다. 단독 근거 질의는 scoped fact로 폴백합니다. |
| `unknown` | 정확 경로가 없으므로 의미 회상만 사용합니다. DB가 없거나 낡으면 `No matching intent`, 빈 객체 목록, 확인 필요 상태로 끝납니다. |

관련 production collector는 [router.py:507](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/router.py:507)의 reviewed kind 수집, [router.py:529](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/router.py:529)의 구현 위치 수집, [router.py:603](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/router.py:603)의 glossary 보강, [router.py:677](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/router.py:677)의 정확 mapping 매칭입니다.

## 선택적 의미 회상

[router.py:59](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/router.py:59)의 `_recall()`은 DB가 없으면 `no_db`, `StaleIndexError`면 `stale_db`로 기록하고 `None`을 반환합니다. 같은 답변 안에서 여러 의도가 호출해도 질의별 cache로 한 번만 계산합니다.

fresh DB일 때는 [search.py:357](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/search.py:357)의 `recall()`이 다음 순서로 동작합니다.

- 질의에서 단일 `DomainContext` 범위를 추론
- BM25와 벡터 검색
- RRF 융합
- 객체 그래프 1-hop과 graph support 재정렬
- 객체, raw, Insight, ContextProjection 레인을 분리
- [search.py:724](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/search.py:724)의 `eval_recall()`이 점수·표면 anchor 게이트를 적용

`eval_recall()`의 다섯 채널은 `results`, `candidates`, `raw_excerpts`, `advisories`, `projection_reuse`입니다. 다만 `query`는 이 중 reviewed/candidate 적중과 `advisories`만 의도별로 소비합니다. `raw_excerpts`와 `projection_reuse`를 그대로 보고 싶으면 `search`를 써야 합니다.

색인 신선도는 [search.py:338](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/search.py:338)의 `_guard_index_freshness()`가 DB meta 지문과 현재 코퍼스 지문을 비교합니다. 지문은 [search_index.py:414](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/search_index.py:414)의 `compute_corpus_fingerprint()`가 index 대상 객체의 kind·ID·status·surface와 raw chunk로 계산합니다. 따라서 여기서 말하는 fresh는 “모든 JSON byte가 같다”가 아니라 “현재 색인 입력과 맞는다”는 뜻입니다.

## 검수 상태, redaction, stale 표시

### 검수 상태

[status.py:10](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/status.py:10)의 `claim_status()`가 `reviewed`, `candidate`, `raw-only`, `raw-unavailable`, `restricted`를 만들고, `answer_status()`가 가장 심한 상태를 답 전체 `status`로 올립니다.

candidate는 `source_object_ids`가 아니라 `promotable_candidate_ids`와 `확인 필요` 항목으로 분리됩니다. reviewed source가 없거나 충돌·범위 모호성이 있으면 `needs_clarification=true`입니다.

`raw-unavailable` 지원은 현재 CLI 경로에서 사실상 배선되지 않았습니다. `QueryRouter`는 `missing_raw_manifest_ids`를 받을 수 있지만 `_run_query()`는 이를 전달하지 않아 기본 빈 집합입니다. 따라서 함수 단위 상태 모델은 있어도 실제 `project-brain query`가 raw 파일 부재를 자동 탐지해 이 상태를 만드는 경로는 없습니다.

### redaction

[router.py:819](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/router.py:819)의 `_restricted_for()`는 EvidenceRef가 가리키는 기존 EvidenceManifest의 `redaction_status`가 정확히 `approved`가 아니면 restricted로 봅니다. 기존 manifest에서 키가 빠진 경우도 fail-closed입니다.

하지만 현재 동작은 접근 차단이 아닙니다.

- restricted는 주로 답 전체 `status`에 반영되는 **신뢰 경고**입니다.
- mapping의 `meaning`, `boundary` 같은 본문은 그대로 `sections`에 들어갑니다.
- 직접 production 호출로 확인했을 때 `status="restricted"`인 동시에 `meaning="제한 본문"`이 JSON에 그대로 남았습니다.
- EventLedgerRecord와 TemporalFact의 여러 분기는 `_restricted_for()`를 호출하지 않고 `restricted=False`를 넘깁니다.
- manifest 자체가 아예 끊겨 있으면 `_restricted_for()`는 restricted로 만들지 않습니다. 이 경우는 별도 lint가 잡아야 합니다.
- `search` 결과에는 이 restricted 조립 경로 자체가 없습니다.

따라서 “approved가 아니면 정보가 숨겨진다”거나 “redaction으로 접근 제어가 된다”고 보면 안 됩니다.

### stale

현재 stale 표시는 서로 다른 네 축입니다.

- **색인 stale**: `query`는 의미 회상을 생략하고 정확 경로로 폴백합니다. 구현 위치만 `details_omitted_reason=stale_db`를 명시합니다. 일반 glossary/unknown 경로에는 stale recall 생략을 알리는 공통 경고가 없습니다.
- **코드 변경 stale-set**: `.brain-local/stale-set.json`을 읽어 정확히 매칭된 `DomainMapping`에 `stale_advisory`를 붙이고 `computed_at`, 변경 path/type, 미머지·검증 불가 anchor 경고를 냅니다.
- **CodeLocator SHA 드리프트**: `commit_sha`가 없거나 명시한 `--current-head`와 다르면 전체 상태를 candidate 쪽으로 낮추고 경고합니다. `current_head`는 자동 Git 조회가 아니라 CLI 인자입니다.
- **CurrentView stale**: source fact 부재, 미검수, `valid_until` 종료를 별도 경고로 표시합니다.

## `query`와 `search`의 fresh-index 차이

| 항목 | `query` | `search` |
|---|---|---|
| DB 없음 | 정확 경로로 계속 동작 | `ok=false`, rebuild 안내, 종료 코드 1 |
| DB stale | `StaleIndexError`를 잡아 recall 생략 | `ok=false`, rebuild 안내, 종료 코드 1 |
| 의미 회상 | 선택적 보강 | 명령의 본체 |
| 출력 | 의도별 `sections` 중심, 최상위 `ok` 없음 | 다섯 검색 채널과 `ok=true` |
| raw/projection 채널 | 그대로 노출하지 않음 | 직접 노출 |
| 자동 rebuild | 없음 | 없음 |

직접 회귀는 [test_router.py:521](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_router.py:521)의 no/missing/stale DB 폴백, [test_search.py:1641](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_search.py:1641)의 fingerprint 가드, [test_cli.py:1712](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_cli.py:1712)의 missing/stale search JSON 실패가 고정합니다.

## principal별 ACL 판단

**현재 집행하지 않습니다.**

근거는 다음과 같습니다.

- `EvidenceManifest.acl`은 schema 필수 필드지만 `QueryRouter` 생성자와 `answer()`에는 principal이나 ACL evaluator 인자가 없습니다.
- `_restricted_for()`는 ACL을 읽지 않고 `redaction_status`만 봅니다.
- [search.py:159](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/search.py:159)의 `_build_linked()`는 `evaluate_quote_access()`에 항상 `principal=None`, `acl_evaluator=None`을 넘깁니다.
- 그 결과 linked CodeLocator의 `quote_access`는 `indeterminate`이고 quote는 숨깁니다. 이는 quote 한 필드의 보수적 미노출이지 사용자별 객체 ACL 집행은 아닙니다.
- [quote_access.py:50](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/quote_access.py:50)의 평가 함수 자체는 principal/evaluator 주입을 지원하지만 제품 `query`·`search` 경로에 연결돼 있지 않습니다.
- audit CLI도 principal/evaluator에 `None`을 넘깁니다.

따라서 ACL 값이 서로 다른 principal 두 명이 같은 명령을 실행해도 현재 객체 회수 결과가 사용자별로 달라지지 않습니다. 제한된 CodeLocator quote만 양쪽 모두 `indeterminate`로 빠집니다.

## 엔진 레포와 소비 데이터 레포 책임

- **이 엔진 레포**: `config`, `BrainStore`, schema, intent/router, 색인·검색, 상태·redaction 표시 코드, 설치 템플릿, 합성 테스트를 소유합니다.
- **소비 데이터 레포**: `.project-brain.json`, 실제 `brain/` 객체와 raw, `.brain-local/index.db`, stale-set, `brain/eval_scenarios.json`, `brain/checks/`를 소유합니다.

그러므로 이 worktree에서 확인한 것은 엔진 계약과 합성 회귀입니다. 실제 프로젝트의 어떤 객체가 답으로 나오는지, 실제 stale-set과 골든셋 결과는 소비 데이터 레포에서 별도로 확인해야 합니다.

## 직접 검증 결과

파일 수정 없이 다음 범위를 직접 실행했습니다.

- config/store/status/quote access
- router의 redaction·stale·정확 매칭·no/missing/stale DB 폴백·unknown recall
- search 채널·linked quote·index freshness
- CLI query/search 진입과 JSON 실패 계약

결과는 **83 passed, 2 subtests passed**였습니다. 아키텍처 문서 계약 테스트도 **9 passed**였습니다. 전체 엔진 테스트는 실행하지 않았습니다.

주요 직접 테스트 경로는 다음과 같습니다.

- [tests/test_config.py:32](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_config.py:32)
- [tests/test_store.py:20](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_store.py:20)
- [tests/test_cli.py:89](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_cli.py:89)
- [tests/test_router.py:55](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_router.py:55)
- [tests/test_router.py:316](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_router.py:316)
- [tests/test_router.py:521](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_router.py:521)
- [tests/test_search.py:500](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_search.py:500)
- [tests/test_search.py:579](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_search.py:579)
- [tests/test_quote_access.py:35](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_quote_access.py:35)
- [tests/test_status.py:10](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_status.py:10)

`intent.py`만 따로 겨냥한 `test_intent.py`는 없고, 현재 의도 분류는 router/CLI 통합 테스트로 검증됩니다. principal별 ACL도 제품 경로가 없기 때문에 end-to-end 테스트가 없습니다.

현재 `docs/architecture/**`는 이 worktree에서 아직 미추적 상태라 단독 정본으로 삼지 않았습니다. 날짜 plan도 근거로 쓰지 않았고, 문서 주장은 위 production 코드와 직접 테스트로 모두 대조했습니다.

````

</details>

### 답변자 2 — tokenizer 변경

- task name: `cold_tokenizer_change_v1`
- fork context: `none`
- 최종 관문 사용 여부: 제외. 답변 내부에 저장소 밖 memory 사용 표기가 있어 길찾기 독립성 조건을
  만족하지 못했다. 아래 전문은 발견 과정 기록으로만 남기며, 최종 판정에는 뒤의 무기억 재실행만 쓴다.
- 개별 질문:

```text
한국어 tokenizer 동작을 바꾸라는 요청을 받았다. 먼저 고칠 production 파일과 함께 봐야 할 호출부,
TDD 표적 테스트, 엔진 전체 검증, 소비 데이터 레포의 checks/eval, 실모델 index rebuild 필요 여부를
판단하라. rebuild를 왜 하거나 하지 않는지도 현재 코드 계약으로 설명하라.
```

<details><summary>답변 전문</summary>

````markdown
결론부터 말하면, **먼저 고칠 곳은 `src/project_brain/tokenize_ko.py`이고 소비 데이터 레포의 실모델 `index rebuild`는 필수**입니다. 기존 DB에는 이전 규칙으로 만든 BM25 토큰이 저장돼 있기 때문입니다.

### Production 코드와 호출부

- 주 변경 파일: [`tokenize_ko.py`](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/tokenize_ko.py:100)

  - `_resolve_backend()`: `mecab-ko → kiwipiepy → regex` 선택
  - `active_backend()`: 현재 백엔드 이름 노출
  - `_split_symbol()`: 영문·심볼 분해
  - `tokenize()`: 색인과 질의가 함께 쓰는 단일 토큰 계약

- 반드시 같이 볼 직접 호출부: [`search_index.py`](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/search_index.py:226)

  - `rebuild()`: 객체와 raw 청크를 `tokenize()`해 `documents.tokenized_text`와 FTS5에 저장
  - `search_bm25()`, `search_bm25_scoped()`: 질의를 같은 `tokenize()`로 분해
  - `compute_corpus_fingerprint()`: 토큰이 비는 행을 제외할 때 tokenizer를 사용
  - 색인 메타에는 `active_backend()` 결과만 기록

- 회수 동작 영향: [`search.py`](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/search.py:272)

  - `_context_surface_token_sets()`·`infer_scope()`: 자동 scope 판정
  - `compute_query_signals()`: `anchor_df` 계산
  - `recall()`·`eval_recall()`: BM25 결과가 RRF와 답변 게이트까지 전달됨

- 진단·CLI 계약도 확인:

  - [`doctor._tokenizer_check()`](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/doctor.py:58)
  - [`cli._run_index()`](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/cli.py:588)

백엔드나 의존성 자체를 바꾸는 요청이면 `pyproject.toml`·`uv.lock`도 범위에 들어갑니다. 단순 토큰 규칙 변경이면 먼저 건드릴 필요는 없습니다.

### TDD 표적

1. [`tests/test_tokenize_ko.py`](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_tokenize_ko.py:15)에 새 기대 동작을 먼저 실패 테스트로 추가합니다. 실제 형태소 모델에 기대지 말고 기존 `backend="regex"` 강제 패턴처럼 결정론적으로 고정해야 합니다.
2. [`tests/test_search_index.py`](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_search_index.py:413)에서 다음을 확인합니다.

   - rebuild가 새 토큰을 저장하는지
   - 한국어 질의가 그 토큰으로 실제 적중하는지
   - 정규식 폴백과 색인·질의 대칭이 유지되는지
   - tokenizer 메타·불일치 경고 계약

3. [`tests/test_search.py`](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_search.py:343)에서 scope 추론과 `anchor_df`·게이트 결과가 달라지지 않는지 확인합니다.

메타나 CLI 출력까지 바꾸면 `tests/test_cli.py`, 백엔드 이름·진단 계약을 바꾸면 `tests/test_doctor.py`도 추가 대상입니다.

현재 변경 전 기준선은 직접 실행 결과 다음과 같습니다.

- 표적 3개 모듈: `178 passed`
- 엔진 전체: `1542 passed, 105 subtests passed`
- 설치되는 ingest runtime: `99 tests, OK`

이는 변경 전 기준선이며, 구현 완료 증거는 아닙니다.

### 완료 검증

엔진 레포에서는 다음을 모두 실행해야 합니다.

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest -q
PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
git diff --check
```

tokenizer 변경만이면 installer 전용 회귀는 보통 추가하지 않습니다. 다만 의존성·템플릿까지 바꾸면 `tests/test_installer.py`와 설치 검증도 필요합니다.

소비 데이터 레포는 실객체·raw·`brain/checks/`·`brain/eval_scenarios.json`을 소유합니다. 검증할 엔진 checkout을 명시해서 실행해야 합니다.

```bash
cd <소비 프로젝트 루트>

PYTHONPATH=<engine-root>/src <engine-root>/.venv/bin/python \
  -m unittest discover -s brain/checks -p 'test_*.py'

PYTHONPATH=<engine-root>/src <engine-root>/.venv/bin/python \
  -m project_brain.cli index rebuild

PYTHONPATH=<engine-root>/src <engine-root>/.venv/bin/python \
  -m project_brain.cli eval
```

### 실모델 rebuild가 필요한 이유

필요합니다.

- 색인에는 과거 `tokenize(surface)` 결과가 `tokenized_text`로 저장돼 있습니다.
- 코드 변경 뒤 질의는 새 `tokenize(query)` 결과를 사용합니다.
- rebuild하지 않으면 색인과 질의가 서로 다른 토큰 규칙을 쓰게 됩니다.
- 현재 `meta.tokenizer`는 구현 버전이 아니라 `mecab-ko` 같은 백엔드 이름만 저장합니다. 같은 백엔드 이름 아래 규칙만 바뀌면 불일치 경고가 잡지 못합니다.
- `compute_corpus_fingerprint()`도 대부분 원문 표면을 해시하므로, 토큰 내용만 달라지고 빈 행 여부가 같으면 stale 가드가 변화를 감지하지 못합니다.

토큰 변경은 벡터 입력에는 직접 영향을 주지 않습니다. 벡터는 토큰화 전 원문을 임베딩합니다. 하지만 현재 production rebuild는 FTS와 벡터를 한 DB에 전체 재구축하며, 증분 FTS 갱신 경로가 없습니다. `embedder=None`은 벡터 테이블을 비우고 `--stub-embedder`는 실제 검색 품질 검증이 아니므로, 소비 데이터 검증에서는 기본 실모델 rebuild를 한 번 실행해야 합니다.

추가로, 새 코드가 오래된 같은-이름 tokenizer 색인을 자동 거부해야 한다면 `search_index.py`에 별도 tokenizer 계약 버전과 가드를 설계하고 `test_search_index.py`에서 먼저 실패 테스트를 만들어야 합니다. 단순 코드 변경만으로는 현재 그 자동 감지가 없습니다.

파일은 수정하지 않았습니다.

````

</details>

### 답변자 3 — CodeLocator 계약

- task name: `cold_code_locator_contract_v1`
- fork context: `none`
- 개별 질문:

```text
초기 적재 데이터에서 CodeLocator의 quote나 full commit SHA가 빠졌다는 문제를 맡았다. 과거 객체를
읽고 좌표 불변으로 보존하는 계약과, 새 객체·좌표 변경·mark-checked의 쓰기 관문을 분리해 설명하라.
정상 JSON 출발 파일과 실패 예시, production validator/verifier, 직접 테스트 경로를 제시하라.
`KIND_REQUIRED`만 보고 결론내려도 되는지도 판단하라.
```

<details><summary>답변 전문</summary>

````markdown
## 결론

초기 적재의 새 `CodeLocator`에 `verified_quote`나 전체 `commit_sha`가 빠졌다면 현재 쓰기 계약상 정상 데이터가 아닙니다. 다만 이미 저장된 과거 객체는 읽기 호환을 위해 좌표가 바뀌지 않는 동안 그대로 보존할 수 있습니다. 이 둘을 같은 허용 규칙으로 보면 안 됩니다.

### 과거 객체 읽기·보존

- `BrainStore.load_unlocked()`는 JSON, `id`, `kind`, 중복 ID만 확인하고 객체 schema 전체를 재검증하지 않습니다: `src/project_brain/store.py:48-123`.
- `KIND_REQUIRED["CodeLocator"]`에는 `repo`, `path`, `locator_source`, `verified_at`만 있습니다. `commit_sha`, `symbol`, `verified_quote`는 없습니다: `src/project_brain/schema.py:23-32`.
- `MutationService.plan()`은 다음 다섯 값을 좌표로 봅니다: `repo`, `path`, `commit_sha`, `symbol`, `verified_quote`: `src/project_brain/mutation.py:48-54`.
- 같은 ID의 기존 객체에서 이 다섯 값이 모두 같으면 쓰기 검증을 다시 하지 않습니다. 외부 입력이 `title`이나 `verified_at`를 바꿔도 기존 저장값으로 되돌립니다: `mutation.py:401-465`.
- 따라서 quote가 없거나 SHA가 축약된 과거 객체도 좌표가 그대로면 보존됩니다. 이는 새 객체에 적용할 수 있는 우회로가 아닙니다.
- 감사용 `verify_code_quotes()`도 `verified_quote` 필드가 없는 과거 객체는 의도적으로 `skipped` 처리합니다: `src/project_brain/code_verify.py:369-417`.

직접 고정한 테스트는 다음입니다.

- `tests/test_object_contract_templates.py::test_legacy_quote_omission_loads_and_unchanged_ingest_preserves_it_but_new_write_fails`
- `tests/test_object_contract_templates.py::test_legacy_short_sha_loads_and_unchanged_ingest_preserves_it_but_write_gate_is_exact`
- `tests/test_mutation.py::test_unchanged_ingest_locator_preserves_engine_fields`

### 새 객체·좌표 변경 쓰기

다음 중 하나면 엄격한 재검증 대상입니다.

- 같은 ID가 store에 없는 새 객체
- 위 다섯 좌표 값 중 하나라도 변경
- operation이 `MARK_CHECKED`

`MutationService.plan()`은 먼저 비어 있지 않은 `verified_quote`와 명시적 `RepoContext`를 요구하고, `verify_locator_for_write()`로 넘깁니다. 실패 코드는 각각 `quote_required`, `repo_context_required`입니다: `mutation.py:412-445`.

`verify_locator_for_write()`는 다음을 실제 Git 저장소에서 확인합니다.

- `repo`가 해석된 repo ID와 같은지
- `commit_sha`가 정확한 40자 또는 64자 전체 SHA인지
- `rev-parse` 결과가 입력 SHA와 정확히 같은지
- 기준 revision에서 해당 commit에 도달 가능한지
- `path`가 해당 commit의 실제 blob인지
- `verified_quote`가 blob에 정확한 UTF-8 바이트로 존재하는지
- quote와 `symbol` 관계가 AST 또는 구조화된 수동 검증 근거로 확인되는지

근거는 `src/project_brain/code_verify.py:89-297`입니다. 성공하면 외부 `verified_at`를 믿지 않고 엔진 시각으로 덮어쓰며, 일반 ingest에서는 title도 symbol 기반 표준값으로 확정합니다.

직접 테스트는 다음입니다.

- `tests/test_mutation.py::test_new_locator_is_verified_and_external_time_and_title_are_ignored`
- `tests/test_mutation.py::test_new_locator_without_verified_at_reaches_verifier_and_gets_engine_time`
- `tests/test_mutation.py::test_unverified_locator_missing_quote_fails_at_quote_gate_not_schema`
- `tests/test_mutation.py::test_coordinate_changed_locator_is_reverified`
- `tests/test_code_verify.py::VerifyLocatorForWriteTest`
- 특히 SHA 축약 거부: `VerifyLocatorForWriteTest::test_sha256_commit_abbreviation_is_not_an_exact_commit_sha`

### `mark-checked`

`plan_mark_checked()`는 단순히 SHA만 덮어쓰지 않습니다.

- reviewed `DomainMapping`의 locator closure가 모두 선택됐는지 확인
- 저장된 quote가 없으면 전체 묶음을 `refused_unverifiable`로 거부
- `commit_sha`를 현재 `checked_head`로 바꿈
- `verify_locator_for_write()`로 quote와 symbol을 새 head의 blob에서 재확인
- precondition과 corpus fingerprint를 묶음
- 이후 `MutationOperation.MARK_CHECKED`로 다시 mutation 관문을 통과

production 경로는 `src/project_brain/stale_check.py:330-496`, CLI 배선은 `src/project_brain/cli.py:1266-1344`, mutation의 강제 재검증과 시각 갱신은 `src/project_brain/mutation.py:412-474`입니다. 같은 SHA여도 `MARK_CHECKED`면 재검증합니다.

직접 테스트는 다음입니다.

- `tests/test_stale_check.py::MarkCheckedTest::test_full_closure_reverifies_quote_and_symbol_with_one_event_time`
- `...::test_quote_missing_refuses_entire_bundle_before_any_plan_is_returned`
- `...::test_same_sha_apply_reverifies_and_stamps_one_new_event_time`
- `...::test_same_sha_symbol_failure_refuses_entire_apply_bundle`

따라서 quote가 없는 과거 locator는 읽을 수는 있어도 그대로 `mark-checked`할 수 없습니다. 소비 데이터 레포에서 실제 전체 SHA와 원문 quote를 보충한 검증 쓰기로 먼저 고쳐야 합니다.

## JSON 출발점과 실패 예시

초기 적재의 정상 출발점은 다음입니다.

- `src/project_brain/templates/ingest/references/object-templates/build-notes.complete.template.json`
  - `context.commit`: 40자 SHA 형태
  - `code_anchors[].quote`: 비어 있지 않은 원문
  - `code_anchors[].symbol`, `path` 포함
- `assembly.validate_notes()`는 `context.commit` 키와 quote·symbol의 비어 있지 않은 값을 검사합니다.
- `assembly.build_code_evidence()`가 `context.commit → CodeLocator.commit_sha`, `quote → verified_quote`로 옮깁니다: `src/project_brain/assembly.py:55-83, 320-450`.
- 다만 notes 단계는 commit 문자열이 실제 전체 SHA인지는 확인하지 않습니다. 최종 ingest의 `verify_locator_for_write()`가 확인합니다.

`kinds/CodeLocator.template.json`은 저장 shape 참고용일 뿐 새 쓰기 완성 payload가 아닙니다. 이 파일은 의도적으로 `commit_sha`와 `verified_quote`가 없습니다. 실제 쓰기 테스트도 이 파일을 읽은 뒤 동적 전체 SHA와 실제 quote를 추가해 mutation 관문에 태웁니다: `tests/test_object_contract_templates.py:166-207`.

실패 예시는 다음입니다.

- 신규 quote 누락: `invalid/code-locator-without-quote.json`
- 기존 좌표 변경 뒤 quote 누락: `invalid/code-locator-coordinate-change-without-quote.json`
- 실행 조건과 기대 코드: `invalid/manifest.json:68-83`
  - 둘 다 repo fixture에서 동적 전체 SHA를 넣은 뒤 `MutationService.plan()`의 `quote_required`를 확인하므로, 다른 오류에 가려진 가짜 반례가 아닙니다.
- 전체 SHA 누락·축약은 별도 고정 JSON보다 위의 mutation/code verifier 직접 테스트가 보장합니다.

이 설치 JSON 전체를 production 관문에 직접 태우는 테스트는 `tests/test_object_contract_templates.py`입니다.

## `KIND_REQUIRED`만 봐도 되는가

안 됩니다. 오히려 `CodeLocator.template.json`이 `commit_sha`와 quote 없이 schema를 통과한다는 점이 반증입니다.

전체 쓰기 계약은 다음 층을 함께 봐야 합니다.

1. `assembly.validate_notes()` — build 입력
2. `schema.validate_mutation_input_schema()` — verifier 전에는 `verified_at` 누락만 임시 허용
3. ID 문법과 필드 결속
4. `MutationService.plan()` — 기존 객체 비교, 상태 전환, 좌표 변경 판정
5. `verify_locator_for_write()` — repo·전체 SHA·blob·quote·symbol 실검증
6. 합쳐진 store의 최종 schema·lint
7. transaction apply

즉 `KIND_REQUIRED`는 객체 모양의 일부일 뿐 신규 정본 쓰기 계약이 아닙니다.

## 엔진 레포와 소비 데이터 레포 책임

- 엔진 레포는 schema, assembly, mutation/verifier, mark-checked, 설치 JSON과 합성 테스트를 소유합니다.
- 실제 누락된 quote·SHA와 `brain/objects/code/**` 코퍼스는 소비 데이터 레포가 소유합니다.
- 현재 엔진은 새 쓰기를 이미 엄격히 막으므로, 기존 누락분을 엔진 레포의 실데이터로 고치거나 자동 추측해 채우면 안 됩니다. 소비 데이터 레포에서 실제 repo 근거로 값을 복구하고 그 checkout의 `PYTHONPATH`와 `.venv/bin/python`을 고정해 mutation·실코퍼스 회귀를 거쳐야 합니다.

확인한 표적 테스트 결과는 `38 passed, 7 subtests passed`였습니다. 파일은 수정하지 않았습니다.
````

</details>

### 유효 재실행 1 — query end-to-end (저장소 밖 memory 금지)

- task name: `cold_query_path_v2`
- fork context: `none`
- 금지 사항: Codex memory 파일, memory summary, rollout summary, 과거 세션 회상과
  인터넷을 어떤 용도로도 읽거나 사용하지 않음.
- 개별 질문:

```text
사용자 질문이 `project-brain query`의 답변 JSON이 되기까지 경로를 설명하라. config, store,
의도 분류와 정확 객체 경로, 선택적 의미 회상, 검수 상태·redaction·stale 표시를 빠짐없이 연결하라.
`query`와 `search`의 fresh-index 요구 차이, 현재 principal별 ACL 집행 여부, redaction restricted가
모든 query/search 경로에 일관되게 적용되는지도 분명히 판단하라. 답변 끝에 사용 근거가 worktree
파일뿐이었음을 명시하라.
```

<details><summary>답변 전문</summary>

````markdown
결론부터 말하면, `project-brain query`는 소비 프로젝트의 `brain/` 객체를 직접 읽는 경로를 중심으로 답을 만들고, 신선한 색인이 있을 때만 의미 회상을 덧붙입니다. 반면 `search`는 신선한 색인이 없으면 실패합니다. 현재 principal별 ACL 집행은 없고, `redaction_status` 기반 `restricted`도 일부 `query` 경로에만 붙는 신뢰 라벨일 뿐 전체 `query/search`의 내용 차단 장벽은 아닙니다.

## 전체 호출 경로

```text
project-brain
  → pyproject.toml의 project_brain.cli:main
  → cli.main()
  → _run_query()
  → config 해석
  → BrainStore.load()
  → stale-set cache 로드
  → QueryRouter.answer()
     → 의도 분류
     → 의도별 객체 직접 순회·ID 참조
     → 신선한 index가 있으면 선택적 eval_recall()
     → status / restricted / stale 표시 조립
  → json.dumps(answer)
```

- CLI 진입점: `pyproject.toml:19-20`
- 명시적 `project-brain query "..."`와 기존 호환형 `project-brain "..."` 모두 `cli._run_query()`로 갑니다: `src/project_brain/cli.py:1841-1889`.
- `query` 성공 JSON에는 `ok`가 없고, `QueryRouter.answer()` 반환값을 그대로 출력합니다: `src/project_brain/cli.py:217-225`.
- 직접 테스트: `tests/test_cli.py::TestCli::test_cli_query_path_unchanged`, `test_explicit_query_subcommand_routes_without_becoming_query_text`.

## 엔진 레포와 데이터 레포 경계

이 worktree는 엔진 코드·합성 테스트·구조 문서만 가집니다. 실제 답변 재료는 소비 프로젝트의 데이터 레포 `brain/`에 있습니다.

- `.project-brain.json`은 소비 프로젝트 쪽 연결 설정입니다.
- `config.find_config()`가 현재 디렉터리에서 부모로 올라가 첫 설정을 찾습니다.
- 경로 우선순위는 명시 인자 > config > `ConfigError`입니다.
- 기본값은 `brain_root=<project>/brain`, `db=<brain_root>/.brain-local/index.db`입니다.
- production: `src/project_brain/config.py::find_config`, `load_config`, `resolve_brain_root`, `resolve_db_path`.
- 직접 테스트: `tests/test_config.py::FindConfigTest`, `LoadConfigTest`, `ResolveTest`.

`_run_query()`는 먼저 `brain_root`를 확정해 `BrainStore.load()`를 호출합니다. `--db`가 없으면 현재 config 또는 `brain_root`에서 다시 발견한 같은 config의 DB가 실제 존재할 때만 recall DB로 채택합니다. 설정에서 DB를 못 찾거나 파일이 없으면 `db_path=None`으로 두고 정확 객체 경로만 사용합니다: `src/project_brain/cli.py:186-221`.

## Store와 실제 객체 경로

`BrainStore.load()`는 소비 데이터 레포의 코퍼스 공유 잠금을 잡고, `_KIND_DIR`에 등록된 디렉터리만 읽어 ID와 kind별 메모리 맵을 만듭니다: `src/project_brain/store.py:37-135`.

질의에 직접 관련된 물리 경로는 다음과 같습니다.

| kind | 데이터 레포 경로 |
|---|---|
| `EventLedgerRecord` | `brain/objects/ledger/*.json` |
| `TemporalFact` | `brain/objects/facts/*.json` |
| `CodeLocator` | `brain/objects/code/*.json` |
| `DomainContext`, `GlossaryTerm` | `brain/objects/domain/*.json` |
| `DomainMapping` | `brain/objects/mappings/*.json` |
| `DecisionRecord` | `brain/objects/decisions/*.json` |
| `Insight` | `brain/objects/insights/*.json` |
| `EvidenceRef` | `brain/objects/evidence_refs/*.json` |
| `ReviewRecord` | `brain/objects/reviews/*.json` |
| `EvidenceManifest` | `brain/raw/manifests/*.json` |
| `CurrentView` | `brain/views/current/*.json` |
| `ContextProjection` | `brain/indexes/context_projections/*.json` |

`raw/sources/**`는 `BrainStore` 객체가 아닙니다. 원문 청크는 index rebuild 때 별도 검색 레인으로 들어갑니다. `eval_scenarios.json` 같은 root JSON도 store가 무시합니다.

- production: `src/project_brain/store.py::BrainStore.load`, `load_unlocked`, `object_path`.
- 직접 테스트: `tests/test_store.py::LoadScanBoundaryTest::test_object_path_is_kind_routed_under_brain_root`, `test_non_object_json_at_root_is_ignored`, `test_non_object_json_under_raw_sources_is_ignored`.

## 의도 분류와 의도별 객체 경로

`QueryRouter.answer()`는 먼저 reviewed `GlossaryTerm.avoid`를 canonical 용어로 바꾼 뒤 `classify_query()`를 호출합니다. 한 질문이 여러 의도로 분류될 수 있습니다.

- `왜`, `이유`, `바뀌` → `why_changed`
- `현재`, `지금`, `QA 기준` → `current_status`
- `그때`, `당시`, `as-of` → `as_of_history`
- `어디 구현`, `어느 함수` 등 → `implementation_location`
- `무슨 뜻`, `용어` → `glossary_meaning`
- `근거`, `누가 확정`, `출처` → `evidence_provenance`
- 아무 신호도 없으면 `unknown`

production은 `src/project_brain/intent.py::normalize_terms`, `classify_query`, `src/project_brain/router.py::QueryRouter.answer`입니다.

의도별 실제 객체 선택은 다음과 같습니다.

- `why_changed`
  - reviewed `EventLedgerRecord` 전체를 시간순으로 읽습니다.
  - 해당 event에서 파생된 reviewed `TemporalFact`와 `supersedes` 사슬을 읽습니다.
  - 질의에 정확히 매칭된 용어·매핑을 가리키는 reviewed `DecisionRecord`를 추가합니다.
- `current_status`
  - 질의의 release/feature/surface 범위에 맞는 open reviewed `TemporalFact`를 읽습니다.
  - 충돌과 `supersedes` 승자를 계산합니다.
  - 관련 `CurrentView` ID를 후보로 붙이고 view stale 경고를 계산합니다.
- `as_of_history`
  - 같은 범위의 reviewed `TemporalFact`를 읽되, 닫힌 과거 fact도 포함합니다.
- `implementation_location`
  - 상세 `CodeLocator` 선택은 의미 회상에 의존합니다.
  - fresh index가 없으면 locator ID·path·symbol을 직접 내지 않고 전체 `CodeLocator` 개수와 `details_omitted_reason=no_db|stale_db`만 냅니다.
- `glossary_meaning`
  - 질의에 나온 reviewed/candidate `GlossaryTerm`의 term·synonym을 통해 reviewed `DomainMapping`을 정확 매칭합니다.
  - fresh recall이 있으면 관련 `DomainContext`·reviewed `GlossaryTerm` top-K로 의미를 확장합니다.
  - recall이 없으면 reviewed `DomainContext`·`GlossaryTerm` 전체로 폴백합니다.
  - 직접 매칭된 candidate term은 `확인 필요`로 따로 냅니다.
- `evidence_provenance`
  - 함께 분류된 의도의 source 객체를 다시 모은 뒤 `review_record_id`와 `evidence_refs` ID를 직접 따라갑니다.
  - 단독 출처 질문이면 범위에 맞는 fact를 출발점으로 삼습니다.
- `unknown`
  - 정확 경로가 없고 의미 회상만 사용합니다. 색인이 없거나 stale이면 `No matching intent`와 확인 필요 상태로 끝납니다.

따라서 구조 문서의 “정확 객체 경로 우선”은 모든 의도에서 같은 뜻은 아닙니다. fact·event·mapping·evidence 경로는 store의 kind/ID 관계를 직접 읽지만, `implementation_location`의 상세와 `unknown`은 fresh recall이 있어야 나옵니다.

직접 테스트는 `tests/test_router.py`의 다음 경로입니다.

- `TestWhyChangedDecisions`
- `TestRouterRecallTopK`
- `TestRouterRecallFallback`
- `TestRouterUnknownRecall`
- `TestCandidateExposure`

## 선택적 의미 회상

`QueryRouter._recall()`은 DB가 실제 존재할 때만 `search.eval_recall()`을 부릅니다. 같은 답변 안의 여러 의도와 마지막 advisory 조립은 한 번 계산한 결과를 캐시해 재사용합니다: `src/project_brain/router.py:59-90`.

회상 내부는 다음 순서입니다.

```text
eval_recall()
  → recall()
  → 현재 store + raw source의 색인 대상 지문 확인
  → BM25 + vector
  → RRF 융합
  → graph 1-hop 동반 및 support 재정렬
  → 질의 신호 gate
  → results / candidates / raw_excerpts / advisories / projection_reuse
```

production:

- `src/project_brain/search.py::recall`
- `src/project_brain/search.py::_guard_index_freshness`
- `src/project_brain/search.py::eval_recall`
- `src/project_brain/search_index.py::compute_corpus_fingerprint`, `read_meta_fingerprint`

`query`가 이 다섯 채널을 모두 그대로 내는 것은 아닙니다.

- 의도별 source 선택에는 주로 `results`, `candidates`, linked CodeLocator를 씁니다.
- top-level `advisories`에는 reviewed `Insight`를 넣습니다.
- `raw_excerpts`와 `projection_reuse`는 `query` JSON에는 직접 노출하지 않고 `search`가 노출합니다.

## `query`와 `search`의 fresh-index 차이

판단은 분명합니다.

- `query`: fresh index가 필수가 아닙니다.
  - DB 없음 → `_recall()`이 `None`, 정확 경로/폴백 유지.
  - stale DB → `StaleIndexError`를 잡아 recall만 생략.
  - 구현 위치에서는 `details_omitted_reason`으로 차이를 드러냅니다.
  - 다른 의도에서는 별도 전역 `recall omitted` 경고 없이 폴백할 수 있습니다.
- `search`: fresh index가 필수입니다.
  - `eval_recall()`이 DB가 없으면 `FileNotFoundError`.
  - 현재 색인 대상 지문과 DB meta 지문이 다르면 `StaleIndexError`.
  - `_run_search()`가 둘만 잡아 `{"ok": false, "error": "...rebuild..."}` JSON과 종료 코드 1을 냅니다.

직접 테스트:

- query 폴백: `tests/test_router.py::TestRouterRecallFallback::test_no_db_path_falls_back_to_full_load`, `test_missing_db_file_falls_back`, `test_stale_db_implementation_fallback_returns_only_aggregate`
- search freshness: `tests/test_search.py::IndexFreshnessGuardTest`
- CLI 실패 계약: `tests/test_cli.py::TestCliSearch::test_search_missing_index_errors`, `test_search_stale_index_errors_clean_json`

## 검수 상태와 stale 표시

각 source 객체는 `claim_status()`를 거치며, 답 전체는 가장 심각한 값을 `answer_status()`로 고릅니다.

```text
reviewed < raw-only < candidate < raw-unavailable < restricted
```

- `restricted`가 최우선입니다.
- reviewed 객체에 evidence가 있고 raw가 없다고 주입되면 `raw-unavailable`입니다.
- candidate는 `candidate`입니다.
- source가 없으면 답 기본 상태는 `raw-only`입니다.
- production: `src/project_brain/status.py::claim_status`, `answer_status`.
- 직접 테스트: `tests/test_status.py::TestClaimStatus`, `TestAnswerStatus`.

다만 CLI의 `QueryRouter` 생성은 `missing_raw_manifest_ids`를 주입하지 않습니다. 따라서 현재 `project-brain query` 경로는 raw 파일 부재를 직접 스캔해 `raw-unavailable`로 만들지 않습니다. 이 값은 현재 library 수준의 주입 경로에 가깝습니다.

stale 표시는 서로 다른 세 갈래입니다.

1. 색인 stale
   - query는 recall을 생략하고, 구현 위치에서는 `details_omitted_reason=stale_db`.
   - search는 실패합니다.
2. 코드 stale cache
   - `_run_query()`가 `brain/.brain-local/stale-set.json`을 읽고 매핑별 advisory로 바꿉니다.
   - 정확 매칭된 `DomainMapping` 상세에만 `stale_advisory`를 붙이고 warning을 추가합니다.
   - 이 advisory 자체는 저장 객체 status를 바꾸지 않습니다.
   - production: `src/project_brain/stale_check.py::load_stale_set`, `advisories_by_mapping`; `router.py`의 `glossary_meaning`.
   - 직접 테스트: `tests/test_cli.py::TestCli::test_cli_query_surfaces_stale_advisory_from_cache`, `test_cli_query_surfaces_unmerged_advisory_without_changing_status`.
3. 객체 관계 stale
   - `current_status`는 모든 reviewed `CurrentView`의 source fact가 없거나 미검수이거나 닫혔으면 warning을 냅니다.
   - 구현 위치는 `CodeLocator.commit_sha`가 없거나 `--current-head`와 다르면 답 status를 최소 candidate로 올리고 경고합니다.

## redaction과 ACL 판단

### 일부 query 경로의 `restricted`

`QueryRouter._restricted_for()`는 객체의 `evidence_refs`를 따라 기존 `EvidenceRef`와 기존 `EvidenceManifest`를 찾습니다. manifest가 존재하면 `redaction_status == "approved"`만 통과하고, 다른 값이나 필드 누락은 `restricted=True`입니다. 다만 끊긴 EvidenceRef/manifest는 건너뛰며 별도 lint가 잡는 구조입니다: `src/project_brain/router.py:819-830`.

`_restricted_for()`를 실제 호출하는 경로:

- 매칭된 `DecisionRecord`
- reviewed/candidate `CodeLocator`
- 정확 매칭 `DomainMapping`
- candidate `GlossaryTerm`
- `evidence_provenance` source 객체
- `unknown` 의미 회상의 reviewed/candidate 객체

직접 테스트: `tests/test_router.py::TestRestrictedForFailClosed`.

### 적용하지 않는 query 경로

다음은 명시적으로 `restricted=False`를 넘기거나 redaction status 계산 자체를 하지 않습니다.

- `why_changed`의 `EventLedgerRecord`, `TemporalFact`
- `current_status`, `as_of_history`의 `TemporalFact`
- glossary 의미 확장의 `DomainContext`, reviewed `GlossaryTerm`
- top-level reviewed `Insight` advisory

따라서 같은 non-approved manifest를 참조하더라도 의도 경로에 따라 답 status가 달라질 수 있습니다.

더 중요한 점은 `restricted`가 내용 차단이 아니라 답 전체 신뢰 상태입니다. 해당 객체의 section과 의미·경로 필드를 제거하지 않습니다.

### search에는 일반 restricted 처리가 없음

`search.eval_recall()`의 `results`, `candidates`, `raw_excerpts`, `advisories`, `projection_reuse`는 저장된 `status`와 채널 라벨만 유지합니다. 일반 객체에 `_restricted_for()`를 적용하지 않습니다.

linked `CodeLocator`의 quote만 별도 `evaluate_quote_access()`를 거칩니다. 하지만 `search._build_linked()`가 `principal=None`, `acl_evaluator=None`을 하드코딩하므로 결과는 `quote_access=indeterminate`이고 quote를 빼는 데 그칩니다. path와 symbol, 검색 객체 본문 전체를 ACL로 막는 것은 아닙니다.

- production: `src/project_brain/search.py::_build_linked`, `src/project_brain/quote_access.py::evaluate_quote_access`.
- 직접 테스트:
  - `tests/test_search.py::GraphOneHopTest::test_linked_locator_never_leaks_title_or_verified_quote_without_principal`
  - `tests/test_quote_access.py::test_missing_principal_keeps_approved_redaction_but_omits_quote`
  - `tests/test_cli.py::TestCliSearch::test_search_returns_results_with_status_and_linked`

### principal별 ACL 집행 여부

현재 CLI `query/search`에서는 집행하지 않습니다.

- `QueryRouter` 생성자와 `answer()`에는 principal이나 ACL evaluator 입력이 없습니다.
- `EvidenceManifest.acl`은 저장되지만 query 라우터가 평가하지 않습니다.
- `search`의 quote 평가도 principal/evaluator를 `None`으로 넘깁니다.
- `evaluate_quote_access()` 자체는 principal과 evaluator가 주어졌을 때 allow/deny를 계산할 수 있지만, 현재 CLI 제품 경로에 연결되지 않았습니다.

따라서 최종 판단은 다음과 같습니다.

- principal별 ACL 집행: **아니요.**
- redaction `restricted`의 모든 query 경로 일관 적용: **아니요.**
- search까지 포함한 일관된 redaction/ACL 내용 차단: **아니요.**
- 현재 보장되는 것: 일부 query 경로의 신뢰 라벨과, principal이 없어 판정 불가인 linked CodeLocator quote의 보수적 미노출뿐입니다.
- 구조 문서도 이를 `ENGINE_GAP`으로 명시합니다: `docs/architecture/runtime-map.md:180-204`.

이 답변의 사실 근거는 `/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation` 안의 현재 `AGENTS.md`, `docs/architecture/**`, production 코드와 직접 테스트 파일뿐이며, memory·과거 세션·인터넷은 사용하지 않았고 요청에 따라 테스트도 실행하지 않았습니다.

사용한 근거: 이 worktree의 파일만 사용함.
````

</details>

마지막 `사용한 근거: 이 worktree의 파일만 사용함.` 문장은 답변에 이미 명시된 최종 근거 진술을
정해진 표기로 맞춘 사무적 정규화이며, 사실관계를 바꾼 것이 아니다.

### 유효 재실행 2 — tokenizer 변경 (저장소 밖 memory 금지)

- task name: `cold_tokenizer_change_v2`
- fork context: `none`
- 금지 사항: Codex memory 파일, memory summary, rollout summary, 이전 chat/session transcript,
  인터넷을 읽거나 사용하지 않음.
- 개별 질문:

```text
한국어 토크나이저를 바꾸려면 어디를 수정하고, 어떤 영향 범위를 확인하고, 엔진 레포와 소비 데이터 레포에서 각각 무엇을 검증해야 해?
```

<details><summary>답변 전문</summary>

````markdown
결론부터 말하면, 한국어 토크나이저의 정본은 `src/project_brain/tokenize_ko.py`입니다. 다만 영향은 BM25만이 아니라 scope 추론, 앵커 게이트, raw 검색, 라우터의 의미 보강까지 번집니다. 그래서 엔진 합성 회귀만으로 끝내면 안 되고, 소비 데이터 레포에서 실모델 색인을 다시 만든 뒤 `brain/checks`와 골든셋 `eval`까지 확인해야 합니다.

## 먼저 볼 정본

현재 기준은 다음 순서로 보면 됩니다.

- 구조와 2-레포 경계: `AGENTS.md`, `docs/architecture/README.md`
- 실행 흐름과 `query`/`search` 차이: `docs/architecture/runtime-map.md`
- 변경 파일·검증 범위·rebuild 기준: `docs/architecture/change-map.md`
- 현재 검색 구현 설명: `docs/search-internals.md`
- 안정적인 설계 경계: `docs/design-canonical.md`
- 현재 완료 상태: `ROADMAP.md`
- 실제 동작의 최종 기준: `src/project_brain/`와 `tests/`

`docs/specs/2026-06-10-bb2-brain-search-layer-design.md`는 단일 토크나이저와 색인·질의 대칭을 정한 이유를 확인하는 역사 자료입니다. 현재 동작 판단은 날짜 문서보다 코드와 테스트가 우선입니다.

## 확인된 현재 동작

핵심 구현은 `src/project_brain/tokenize_ko.py`입니다.

- `tokenize()` 하나를 색인과 질의가 같이 씁니다.
- 기본 백엔드는 모듈 로드 후 한 번 결정·캐시됩니다.
- 폴백 순서는 `mecab-ko → kiwipiepy → regex`입니다.
- 영문 심볼도 여기서 `camelCase`, `snake_case`, `::`, `/`, `.` 기준으로 분해하며 원형 토큰을 함께 보존합니다.
- `active_backend()` 값은 색인 `meta.tokenizer`에 기록되고, 색인 시점과 질의 시점 백엔드가 다르면 경고에 쓰입니다.

색인 경로는 `src/project_brain/search_index.py`입니다.

- `rebuild()`가 객체의 `extract_surface()` 결과와 `raw/sources/**` 청크를 모두 `tokenize()`합니다.
- 토큰은 공백으로 합친 `tokenized_text`가 되어 FTS5 `unicode61` 색인에 들어갑니다.
- 전역 BM25의 `search_bm25()`와 scope 내부 BM25의 `search_bm25_scoped()`가 질의도 같은 `tokenize()`로 처리합니다.
- 벡터 레인은 토큰화 결과가 아니라 토큰화 전 원문을 임베딩합니다. 따라서 토크나이저 변경의 직접 영향은 BM25 쪽이지만, 전체 색인 DB 재구축 명령은 벡터도 함께 다시 만듭니다.
- 증분 색인 경로는 없습니다. `index rebuild`는 새 DB 전체를 만든 뒤 검사하고 원자 교체합니다.

`src/project_brain/search.py`에서도 토크나이저를 직접 씁니다.

- `infer_scope()`가 질의와 `DomainContext` 표면을 토큰화해 단일 scope를 고릅니다.
- scope가 잡히면 객체 BM25는 전역 FTS 점수 대신 `search_bm25_scoped()`로 바뀝니다.
- `compute_query_signals()`가 질의를 토큰화해 `anchor_df`를 구합니다. 이 값은 reviewed/candidate 결과를 통과시킬지 결정하는 답변 게이트에 들어갑니다.
- 따라서 토큰 경계가 달라지면 적중 순위뿐 아니라 scope 선택, `needs_clarification`, no-answer 거짓양성·거짓음성도 바뀔 수 있습니다.
- raw, Insight, ContextProjection은 별도 레인이지만 BM25 입력 자체는 같은 토크나이저를 거칩니다.

`query`와 `search`의 실패 양상도 다릅니다.

- `search`는 fresh index가 필수라 DB 부재나 코퍼스 stale이면 실패하고 rebuild를 안내합니다.
- `query`는 정확 객체 경로가 우선이라 DB가 없거나 stale이면 의미 회상을 생략하고 보수적으로 폴백합니다. 이때 구현 위치 상세나 unknown 의미 회상은 빠질 수 있습니다.

중요한 현재 한계도 있습니다. `meta.tokenizer`에는 백엔드 이름만 기록되고, `corpus_fingerprint`는 실제 토큰 배열을 해시하지 않습니다. 따라서 같은 백엔드 이름을 유지한 채 분해 규칙만 바꾸면 기존 DB가 자동으로 stale 판정되지 않을 수 있습니다. 백엔드 이름이 달라져도 현재 BM25 경로는 거부가 아니라 경고만 냅니다. 그래서 토크나이저 계약 변경 뒤 rebuild는 선택이 아니라 필수입니다.

## 어디를 수정해야 하나

최소 변경은 다음과 같습니다.

- 토큰 분해·정규화·폴백 우선순위 변경:
  - `src/project_brain/tokenize_ko.py`
  - `tests/test_tokenize_ko.py`
- 새 라이브러리 추가·삭제 또는 optional dependency 변경:
  - `pyproject.toml`
  - `uv.lock`
  - 필요하면 `README.md`, `AGENTS.md`의 설치·개발 명령
- 새 백엔드 이름을 추가하는 경우:
  - `active_backend()` 계약
  - `src/project_brain/doctor.py`의 정상 백엔드 판정
  - `tests/test_tokenize_ko.py`의 허용값
  - `tests/test_search_index.py`의 meta·불일치 경고 가드
  - `docs/search-internals.md`
- DB에 토크나이저 계약 버전을 별도 기록하거나 기존 DB를 강제로 거부하도록 만들 경우:
  - `src/project_brain/search_index.py`의 `meta` 스키마, `_read_meta()`, 버전 가드
  - 필요하면 `SCHEMA_VERSION` 상승
  - `tests/test_search_index.py`의 구버전 DB/rebuild 안내 테스트
- `tokenize()` 호출 계약 자체를 바꾸는 경우:
  - `src/project_brain/search_index.py`
  - `src/project_brain/search.py`

단순 백엔드 교체라면 `surface.py`, `raw_chunks.py`, `embedder.py`의 동작을 같이 바꿀 필요는 없습니다. 다만 객체 표면과 raw 청크 모두 새 토크나이저를 통과하므로 결과 영향은 반드시 확인해야 합니다.

## 엔진 레포에서 검증할 것

TDD 기준으로 먼저 새 기대 동작을 red 테스트로 고정합니다.

- `tests/test_tokenize_ko.py`
  - 조사·어미·복합어 등 바꾸려는 한국어 경계
  - 영문 심볼 분해와 원형 보존
  - 빈 입력, 중복 제거, 소문자화
  - regex 폴백 결정론
  - 새 백엔드의 `active_backend()` 값
- `tests/test_search_index.py`
  - 한국어·심볼 BM25 적중
  - 색인과 질의의 같은 토큰 계약
  - regex 강제 환경
  - `meta.tokenizer`
  - 토크나이저 불일치 경고
  - scoped BM25
  - 객체와 raw의 색인 포함·제외 및 지문 경계
- `tests/test_search.py`
  - `infer_scope()` 단일 특정과 구체 표면 우선
  - `anchor_df`와 답변 게이트
  - BM25/벡터 RRF 순위
  - raw·Insight·projection 레인 분리
  - no-answer 및 `needs_clarification`

관찰 가능한 query/CLI 결과까지 달라진다면 `tests/test_router.py`의 recall top-K·stale/no-DB 폴백·unknown 회상과 `tests/test_cli.py::TestCliSearch`의 5채널 출력도 표적으로 확인하는 게 안전합니다.

그 뒤 엔진 전체 완료 기준은 다음입니다.

```bash
cd <engine-root>

PYTHONPATH="$PWD/src" .venv/bin/python -m pytest -q

PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'

git diff --check
```

테스트에서는 실모델을 쓰지 않고 `StubEmbedder` 또는 `PROJECT_BRAIN_EMBEDDER=stub`을 써야 합니다. 토크나이저 폴백 테스트는 기존 `tests/test_search_index.py`처럼 모듈 전역 백엔드를 regex로 강제하고 반드시 복원하는 패턴을 따르면 됩니다.

의존성이 그대로면 편집 설치라 재설치는 필요 없습니다. `pyproject.toml`이 바뀌면 다음처럼 도구 환경을 갱신해야 합니다.

```bash
uv sync --extra mecab
uv tool install -e . --with mecab-python3 --force
```

## 소비 데이터 레포에서 검증할 것

엔진 레포에는 실코퍼스와 프로젝트별 골든셋이 없습니다. 소비 프로젝트 루트의 다음 자산이 실데이터 품질 검증을 소유합니다.

- `brain/checks/`
- `brain/eval_scenarios.json`
- 실제 `brain/` 객체와 raw
- 로컬 파생물 `brain/.brain-local/index.db`

여러 checkout의 엔진이 섞이지 않도록 bare `project-brain`이나 시스템 `python3` 대신 검증 대상 checkout을 명시합니다.

```bash
cd <소비 프로젝트 루트>

PYTHONPATH=<engine-root>/src <engine-root>/.venv/bin/python \
  -m unittest discover -s brain/checks -p "test_*.py"

PYTHONPATH=<engine-root>/src <engine-root>/.venv/bin/python \
  -m project_brain.cli index rebuild

PYTHONPATH=<engine-root>/src <engine-root>/.venv/bin/python \
  -m project_brain.cli eval
```

토크나이저 변경은 `docs/architecture/change-map.md`가 실모델 rebuild 필수로 분류합니다. `eval`을 먼저 돌려 기존 DB 결과를 보는 절차는 잘못입니다.

추가로 권장하는 점검은 다음과 같습니다.

```bash
PYTHONPATH=<engine-root>/src <engine-root>/.venv/bin/python \
  -m project_brain.cli doctor

PYTHONPATH=<engine-root>/src <engine-root>/.venv/bin/python \
  -m project_brain.cli search "<대표 한국어 질의>"

PYTHONPATH=<engine-root>/src <engine-root>/.venv/bin/python \
  -m project_brain.cli query "<대표 한국어 질의>"
```

`doctor`에서는 의도한 활성 백엔드가 잡혔는지 확인하고, 대표 질의는 최소한 다음을 포함하는 게 좋습니다.

- 조사·어미가 붙은 한국어 질의
- 복합 명사와 띄어쓰기 변형
- 한국어와 코드 심볼 혼합 질의
- scope가 정확히 하나 잡혀야 하는 질의
- 존재하지 않는 엔티티 질의
- raw 원문을 찾아야 하는 질의

새 토크나이저 도입으로 특정 골든 시나리오만 우연히 좋아지고 no-answer 가드가 무너질 수 있으므로, 전체 `eval` 결과와 실패별 실제 반환 ID·채널·`needs_clarification`을 같이 봐야 합니다. 과거 문서의 통과 개수는 현재 checkout의 검증 영수증이 아닙니다.

## 2-레포 경계

- 엔진 레포에서 바꾸는 것:
  - 토크나이저 코드
  - 의존성
  - 검색·색인 계약
  - 합성 테스트
  - 아키텍처·운영 문서
- 소비 데이터 레포에서 확인하는 것:
  - 실제 객체/raw에 대한 토큰 분포
  - 프로젝트별 corpus guard
  - 골든셋 검색 품질
  - 실모델 색인 재구축 결과

실코퍼스나 골든셋을 엔진 레포로 옮기면 안 됩니다. 반대로 범용 토크나이저 구현을 소비 데이터 레포에 복제해서도 안 됩니다. `.brain-local/index.db`는 다시 만들 수 있는 로컬 파생물이므로 데이터 정본이나 커밋 대상이 아닙니다.

사용한 근거: 이 worktree의 파일만 사용함.
````

</details>

## 발견한 구멍 분류

### DOC_DRIFT — 이번에 바로잡음

- 기존 진입 문서에는 전체 지도가 없었고, query와 search, 객체 코퍼스와 파생물, 점검 명령의
  코퍼스 밖 쓰기 효과를 한 경로에서 찾기 어려웠다.
- README의 “점검·진단은 모두 읽기 전용” 설명을 옵션별 실제 쓰기 효과에 맞게 고쳤다.
- 기존 설치 reference의 11종 표가 19종 전체 계약처럼 읽히지 않게 범위를 분명히 했다.

### TEMPLATE_GAP — 이번에 채움

- `VALID_KINDS`와 정확히 맞는 19종 저장 객체 shape JSON
- build의 9개 입력 section과 최종 저장 객체를 구분하는 정상 build notes
- 참조 대상 kind까지 확인하는 6-object 연결 그래프
- notes·schema·lint·mutation 네 층에서 의도대로 실패하는 10개 반례와 실행 setup
- CodeLocator 과거 읽기/신규 쓰기, promotion, projection hash를 실제 production 경로에 태우는 테스트

### ENGINE_GAP — 동작은 바꾸지 않고 드러냄

- QueryRouter는 `redaction_status` 기반 restricted 라벨을 만들지만 principal별 ACL은 집행하지 않는다.
- 그 restricted 계산도 모든 query 의도에 일관되게 배선되지 않았다. EventLedgerRecord·TemporalFact와
  일부 DomainContext/GlossaryTerm 경로는 `restricted=False`를 직접 넘기고, 끊긴 manifest는
  `_restricted_for()`가 건너뛴 뒤 lint에 의존한다.
- `search` 다섯 채널은 일반 객체 수준 redaction 라벨을 만들지 않는다. linked CodeLocator quote의
  `indeterminate` 미노출만으로 객체 전체 ACL 집행을 주장할 수 없다.
- 공통 reference registry는 대부분 참조 대상의 존재만 검사하고 의도 target kind까지 강제하지 않는다.
- `SpecRevision.slide_refs`, `SlackThread.message_refs`는 공통 registry 밖이다.
- `KnowledgePage`, `IndexRecord`, `SpecDocument`, `SpecRevision`, `SlideRef`, `SlackThread`에는 전용
  creator와 검색 surface가 없다.
- `ContextProjection.source_object_ids=[]`는 schema상 가능하지만 공식 creator의 의미는 실제 source를
  전제로 한다.

### LEGACY_DEBT — 기존 근거만 연결

- 과거 실코퍼스에 quote 또는 full SHA가 없는 CodeLocator가 있었다는 이전 확인은 보존한다.
- 이번 작업은 소비 데이터 레포를 다시 세거나 수정하지 않았다. 현재 신규·좌표 변경 쓰기가 이를
  조용히 허용한다고 일반화하지도 않았다.

### HISTORICAL_ONLY — 현재 동작과 분리

- 날짜가 붙은 과거 plan·handoff의 설명은 당시 의사결정 근거다. 현재 CLI·operation·소비 경로와
  다르면 production 코드와 직접 테스트를 현재 기준으로 삼는다.
- Task 17 상세는 이번 범위에서 축약하지 않았고, Task 18 실행은 시작하지 않았다.

## 독립 판정과 최종 검증

### 문맥 없는 독립 판정자

- task name: `cold_rehearsal_judge_v1`
- fork context: `none`
- 답변자와의 관계: 세 답변자의 대화 문맥을 상속하지 않은 별도 agent
- 판정 prompt:

```text
작업 위치는 /Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation 이다.
이전 대화 문맥은 주어지지 않았다. 먼저 AGENTS.md와 위임된 필수 지침을 읽고,
`docs/reports/2026-08-04-project-brain-architecture-foundation.md`의 코드 기반 정답표·정확한
prompts·세 답변 전문을 읽어라. 그런 다음 `docs/architecture/**`, 현재 production 코드와 직접
테스트를 독립적으로 대조해 각 답변자(query, tokenizer, CodeLocator)를 PASS 또는 FAIL로 판정하라.
판정 기준은 (1) 엔진/소비 데이터 2-레포 경계를 혼동하지 않음, (2) 날짜 plan을 현재 동작 정본으로
쓰지 않음, (3) build가 직접 corpus를 저장한다고 말하지 않음, (4) KIND_REQUIRED만으로 신규 write를
단정하지 않음, (5) 현재 production symbol과 직접 test path 제시, (6) rebuild 조건 과잉·과소 판단
없음이다. 시나리오별 핵심 사실도 확인하라: query의 exact-first/optional recall과 search fresh-index
차이 및 principal ACL 미집행, tokenizer의 색인/질의 대칭과 소비 checks/eval/실모델 rebuild,
CodeLocator의 legacy unchanged 보존과 new/coordinate/mark-checked verifier 경계. 사소한 표현과 실제
실패를 구분하고, 각 시나리오에 근거·빠진 점·최종 PASS/FAIL을 적은 뒤 전체 관문
READY/CHANGES_REQUIRED를 단정하라. 파일 수정이나 전체 테스트 실행은 하지 마라.
```

판정자가 실행 중 발견된 보강분까지 읽도록 다음 메시지를 같은 turn에 추가 전달했다.

```text
추가 교차 확인: 독립 data 리뷰 뒤 현재 diff에 (1) 모든 kind legacy invalid_id/unknown_grammar
grandfather 경계, (2) core graph exact 전체 참조 집합, (3) GlossaryTerm/ReviewRecord template의
promote plan 결속을 보완했습니다. 최종 판정 전에 이 세 항목도 blocker/important 해소 여부를 짧게
확인해 주세요.
```

<details><summary>판정 전문</summary>

````markdown
전체 관문은 **READY**입니다. 세 답변 모두 PASS이며, 판정을 뒤집을 누락이나 사실 오류는 없었습니다.

### 답변자 1 — query: PASS

- `_run_query()`의 config·store 로드부터 `QueryRouter.answer()`의 의도 분류, 정확 객체 경로, `_recall()`의 선택적 `eval_recall()`까지 현재 코드와 맞습니다.
- `query`는 DB 없음·stale에서 정확 경로로 폴백하고, `search`는 missing/stale index를 rebuild 안내와 함께 실패한다는 구분도 정확합니다.
- `QueryRouter`에는 principal·ACL evaluator가 없고, 검색의 quote 접근도 `principal=None`이므로 principal별 ACL을 집행하지 않는다는 판정이 맞습니다.
- `implementation_location`과 `unknown`이 recall 의존 예외라는 점, `raw-unavailable`가 CLI에 연결되지 않았다는 한계까지 빠짐없이 밝혔습니다.
- 빠진 필수 항목은 없습니다. principal별 제품 경로 자체가 없어 ACL 미집행을 고정하는 end-to-end 테스트가 없다는 점은 답변도 이미 명시했습니다.
- 직접 표적 테스트: **14 passed**.

근거: [cli.py](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/cli.py:163), [router.py](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/router.py:59), [search.py](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/search.py:338), [test_router.py](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_router.py:521), [test_cli.py](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/tests/test_cli.py:1712)

### 답변자 2 — tokenizer: PASS

- `tokenize_ko.py`의 단일 `tokenize()`를 색인 생성과 BM25 질의가 함께 쓰는 대칭 계약을 정확히 짚었습니다.
- `search.py`의 scope 추론과 `anchor_df`까지 영향 범위를 넓혀 본 것도 맞습니다.
- tokenizer 변경은 기존 DB의 `tokenized_text`와 새 질의 규칙을 어긋나게 하며, 현재 fingerprint와 backend 이름만으로 같은 backend 안의 규칙 변경을 잡지 못하므로 실모델 rebuild가 필요하다는 판단이 정확합니다.
- 엔진 표적·전체 회귀와 소비 데이터 레포의 `brain/checks`·rebuild·eval을 분리했고, 2-레포 경계도 지켰습니다.
- 사소한 보강점은 있습니다. backend 내부를 직접 바꿀 때는 `_build_mecab_splitter()` 등도 표적이 될 수 있고, `search_bm25*()`의 tokenizer 경고는 현재 `recall()` 상위로 전달되지 않습니다. 또한 실모델 실행 시 `PROJECT_BRAIN_EMBEDDER=stub`이 꺼져 있는지 확인하면 더 안전합니다. 모두 PASS를 뒤집을 문제는 아닙니다.
- 제가 선별 실행한 표적 테스트는 **17 passed**였습니다.

근거: [tokenize_ko.py](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/tokenize_ko.py:100), [search_index.py](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/search_index.py:226), [search.py](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/search.py:651), [change-map.md](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/docs/architecture/change-map.md:28)

### 답변자 3 — CodeLocator: PASS

- `KIND_REQUIRED`를 신규 쓰기 계약 전체로 보지 않았고, `validate_mutation_input_schema()`가 verifier 전 `verified_at` 누락만 임시 허용한다는 경계를 정확히 설명했습니다.
- 좌표 불변 legacy 객체는 quote 누락·축약 SHA를 보존하지만, 신규·좌표 변경·`MARK_CHECKED`는 quote, repo context, 정확한 40/64자 SHA, blob/path/symbol/quote 검증을 거친다는 설명이 production과 일치합니다.
- build notes, 저장 shape template, invalid manifest를 서로 다른 출발점으로 구분했습니다. `assembly.build_code_evidence()`를 설명했을 뿐 build가 코퍼스를 직접 저장한다고 하지 않았습니다.
- 실제 데이터 복구 뒤 search/eval까지 한다면 mutation이 DB를 무효화하므로 rebuild가 뒤따라야 한다는 문장을 덧붙일 수는 있습니다. 다만 주어진 시나리오의 필수 질문은 아니며 잘못된 rebuild 판단도 없습니다.
- 직접 표적 테스트: **14 passed**.

근거: [schema.py](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/schema.py:399), [mutation.py](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/mutation.py:401), [code_verify.py](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/code_verify.py:89), [stale_check.py](/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation/src/project_brain/stale_check.py:330)

추가 교차 확인한 세 보완점도 모두 해소됐습니다.

- 모든 kind의 legacy `invalid_id`·`unknown_grammar` 보존 경계가 문서에 추가됐고 production 계약과 일치합니다.
- 정상 core graph는 일부 포함 검사가 아니라 전체 참조 튜플 집합의 정확한 동등성을 검사합니다.
- `GlossaryTerm.template.json`과 `ReviewRecord.template.json`이 실제 `promote()` 결과와 mutation plan에 직접 묶였습니다.
- 이 보완점 관련 표적 테스트도 **7 passed**였습니다.

이번에 실행한 표적 노드는 합계 **52 passed**이며, 지시대로 전체 테스트와 파일 수정은 하지 않았습니다.

````

</details>

이 1차 판정은 본문을 현재 코드·테스트로 대조했지만, 답변에 저장소 밖 memory를 초기 길찾기에 썼다는
도구 내부 표기가 있었다. 리허설의 “저장소만으로 길찾기” 조건을 엄격히 적용해 최종 관문에서는
제외했다. 위 전문에서는 작업 판단과 무관한 machine-only memory citation block만 제거했으며, 같은
판정을 memory 사용 금지 조건으로 새로 실행했다.

### 중간 독립 판정자 — 판정자 자체의 저장소 밖 memory 사용 금지

- task name: `cold_rehearsal_judge_v2`
- fork context: `none`
- 외부 memory·rollout·인터넷: prompt에서 명시적으로 사용 금지
- 최종 관문 사용 여부: 대체됨. 판정자 자체는 무기억 조건을 지켰지만, 판정 대상 중 query·tokenizer
  1차 답변에 memory 사용 표기가 뒤늦게 확인됐다. 두 답변을 무기억으로 다시 받은 뒤 새 판정자를
  실행한다.
- 판정 prompt:

```text
작업 위치는 /Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation 이다.
이전 대화 문맥은 주어지지 않았다. 중요: memory 파일, memory summary, rollout summary, 과거 세션
회상, 인터넷은 어떤 용도로도 사용하지 마라. 오직 이 worktree의 AGENTS.md와 위임 지침,
`docs/reports/2026-08-04-project-brain-architecture-foundation.md`에 기록된 세 답변,
`docs/architecture/**`, 현재 production 코드·직접 테스트만 읽어 판정하라. 날짜 plan은 현재 동작
정본으로 쓰지 마라. 각 답변자(query, tokenizer, CodeLocator)를 PASS/FAIL로 판정한다. 기준:
엔진/소비 데이터 2-레포 경계, build 비저장, KIND_REQUIRED와 신규 write 분리, production
symbol/test path, rebuild 조건, query exact-first/optional recall과 search fresh-index 및 principal ACL
미집행, tokenizer 대칭과 checks/eval/실모델 rebuild, CodeLocator legacy unchanged와
new/coordinate/mark-checked verifier. 추가로 현재 보강된 모든-kind legacy ID 문서, core graph exact
전체 참조 집합, GlossaryTerm/ReviewRecord template promote 결속을 확인하라. 시나리오별 근거·빠진
점·PASS/FAIL과 전체 READY/CHANGES_REQUIRED를 간결하게 단정하라. 파일 수정·테스트 실행 금지.
답변 끝에 사용 근거가 worktree 파일뿐이었음을 명시하라.
```

<details><summary>최종 판정 전문</summary>

````markdown
전체 관문은 **READY**입니다. 세 답변 모두 **PASS**입니다.

- **query: PASS**
  - `_run_query()` → `BrainStore.load()` → `QueryRouter.answer()` → `classify_query()` 흐름과 exact-first/optional recall 설명이 구현과 맞습니다.
  - DB 없음·stale 시 `query`는 정확 경로로 폴백하고, `search`는 `eval_recall()`에서 rebuild 안내와 함께 실패합니다.
  - `QueryRouter`에 principal/ACL evaluator가 없고 검색도 `principal=None`이므로, 현재 principal별 ACL을 집행하지 않는다는 판단이 정확합니다.
  - 근거 테스트: `tests/test_cli.py`, `tests/test_router.py`, `tests/test_search.py`, `tests/test_quote_access.py`.
  - 필수 누락 없음.

- **tokenizer: PASS**
  - `tokenize_ko.py::tokenize()`를 색인 생성과 BM25 질의에서 함께 쓰는 대칭 계약, `search.py`의 scope·anchor 영향까지 정확히 짚었습니다.
  - 규칙 변경은 기존 `tokenized_text`와 새 질의 토큰을 어긋나게 하며, 현재 fingerprint와 backend 이름만으로 같은 backend 내부 규칙 변경을 잡지 못하므로 실모델 rebuild가 필요합니다.
  - 엔진 전체 회귀와 소비 데이터 레포의 `brain/checks`·rebuild·eval도 올바르게 분리했습니다.
  - 근거 테스트: `tests/test_tokenize_ko.py`, `tests/test_search_index.py`, `tests/test_search.py`.
  - 실모델 검증 때 stub 환경이 꺼졌는지 명시하면 더 안전하지만 PASS를 뒤집을 누락은 아닙니다.

- **CodeLocator: PASS**
  - `KIND_REQUIRED`를 신규 쓰기 계약 전체로 오해하지 않았습니다.
  - 좌표 불변 legacy 객체의 quote 누락·축약 SHA 보존과, 신규·좌표 변경·`MARK_CHECKED`의 quote/repo/full SHA/blob/path/symbol 검증 경계를 정확히 구분했습니다.
  - build notes와 저장 shape template, invalid fixture를 분리했으며 build가 코퍼스를 직접 저장한다고 설명하지 않았습니다.
  - 근거 테스트: `tests/test_mutation.py`, `tests/test_code_verify.py`, `tests/test_stale_check.py`, `tests/test_object_contract_templates.py`.
  - 실제 복구 mutation 뒤 search/eval까지 한다면 무효화된 DB rebuild가 필요하다는 후속 문장을 덧붙일 수 있지만, 주어진 질문의 필수 누락은 아닙니다.

추가 보강 세 항목도 해소됐습니다.

- 공통 legacy ID 문서는 19종 전체에 적용되는 `invalid_id`·`unknown_grammar`의 안정 해시·문제 목록 결속과 신규/변경 거부 경계를 설명하며, `mutation.py`와 직접 테스트가 이를 뒷받침합니다.
- core graph 테스트는 참조 일부 포함이 아니라 `actual_references == EXPECTED_CORE_REFERENCES`로 전체 참조 튜플 집합을 정확히 비교합니다.
- `GlossaryTerm.template.json`과 `ReviewRecord.template.json`은 실제 `promote()` 결과, `MutationOperation.PROMOTE` plan, 최종 lint까지 직접 결속돼 있습니다.

파일 수정과 테스트 실행은 하지 않았습니다. 사용한 근거는 지정된 worktree의 `AGENTS.md`, 보고서, `docs/architecture/**`, 현재 production 코드와 테스트 파일뿐입니다.
````

</details>

### 최종 독립 판정자 — 유효 답변 세트·저장소 밖 memory 사용 금지

- task name: `cold_rehearsal_judge_v3`
- fork context: `none`
- 금지 사항: Codex memory 파일, memory summary, rollout summary, 과거 chat/session transcript,
  인터넷을 어떤 용도로도 읽거나 사용하지 않음.
- 이 v3 판정만 최종 cold gate다. 앞선 판정자 구간은 대체된 이력으로만 보존하며 현재 판정의
  근거나 권위로 사용하지 않는다.
- 판정 대상은 다음 세 답변만이다.
  1. `유효 재실행 1 — query end-to-end (저장소 밖 memory 금지)` / `cold_query_path_v2`
  2. `유효 재실행 2 — tokenizer 변경 (저장소 밖 memory 금지)` / `cold_tokenizer_change_v2`
  3. `답변자 3 — CodeLocator 계약` / `cold_code_locator_contract_v1`

판정 질문과 기준:

```text
지정된 세 답변만 docs/architecture/**, 현재 production 코드, 직접 테스트 파일과 독립 대조한다.
각 답변에 PASS 또는 FAIL을 주고 전체 READY 또는 CHANGES_REQUIRED를 판정한다. 엔진/데이터
2-레포 경계, 날짜 문서·plan의 현재 runtime 정본 오인 여부, build를 코퍼스 직접 쓰기로 설명했는지,
KIND_REQUIRED를 신규 쓰기 전체 계약으로 오인했는지, 현재 production 심볼과 직접 테스트 경로,
rebuild 조건의 과장·누락을 확인한다. query의 exact-first/선택적 recall과 search fresh-index,
경로별 redaction 및 principal ACL 미집행, tokenizer의 색인·질의 대칭과 scope·anchor 영향 및
실모델 rebuild 뒤 소비 데이터 checks/eval, CodeLocator의 좌표 불변 legacy 보존과
신규·좌표 변경·MARK_CHECKED verifier 경계를 확인한다. 또한 모든 kind legacy
invalid_id/unknown_grammar 문서, core graph의 정확한 전체 참조 집합, GlossaryTerm/ReviewRecord
template의 실제 PROMOTE plan 결속을 검증한다. 경미한 표현과 실제 실패를 구분하고 남은 구멍을
명시한다. 테스트는 실행하지 않고 파일도 수정하지 않는 read-only 판정이다.
```

<details><summary>최종 판정 전문</summary>

````markdown
## 최종 판정

- `cold_query_path_v2`: **PASS**
  - 2-레포 경계, exact-first와 선택적 recall, `query`/`search`의 fresh-index 차이, 경로별 redaction 불균형, principal ACL 미집행을 현재 코드와 직접 테스트에 맞게 설명했습니다.
  - `evidence_provenance`가 “의도별 source를 다시 모은다”는 표현은 조금 넓습니다. 실제 glossary 결합 경로는 정확 매칭 mapping이 아니라 `_glossary_meaning_objects()`를 다시 사용하지만, 핵심 판단을 뒤집는 오류는 아닙니다.

- `cold_tokenizer_change_v2`: **PASS**
  - `tokenize_ko.py`의 색인·질의 대칭, `search_index.py`의 객체/raw BM25 입력, `search.py`의 scope·`anchor_df` 영향, 벡터 입력과의 구분이 정확합니다.
  - 토크나이저 계약 변경은 소비 데이터에서 실모델 rebuild가 필수이고, 그 뒤 `eval`해야 한다는 조건도 맞습니다. router-only 변경까지 rebuild 대상으로 과장하지 않았습니다.

- `cold_code_locator_contract_v1`: **PASS**
  - 좌표가 그대로인 legacy 객체 보존과 신규·좌표 변경·`MARK_CHECKED` 재검증을 정확히 나눴습니다.
  - `KIND_REQUIRED`를 전체 신규 쓰기 계약으로 보지 않았고, `MutationService.plan()`과 `verify_locator_for_write()`의 full SHA·blob·quote·symbol 검증 및 직접 테스트 경로도 현재 파일과 일치합니다.
  - 같은 좌표의 title 보존 설명에는 `DISPLAY_MIGRATION` 예외가 있지만, 일반 ingest의 legacy 보존 시나리오에서는 맞는 설명이라 경미한 표현 문제입니다.

추가 보강 세 항목도 확인했습니다.

- 공통 legacy `invalid_id`·`unknown_grammar` 경계는 19종 모두에 적용되는 일반 mutation 코드로 구현돼 있고, 안정 해시·정확한 문제 목록 결속과 신규/변경 거부가 문서 및 대표 직접 테스트와 맞습니다.
- core graph는 `actual_references == EXPECTED_CORE_REFERENCES`로 12개 전체 참조 튜플 집합을 정확히 비교합니다.
- `GlossaryTerm.template.json`과 `ReviewRecord.template.json`은 실제 `promote()` 결과, `MutationOperation.PROMOTE` plan, 최종 lint에 직접 묶여 있습니다.

**전체 판정: READY**

남은 비차단 구멍은 두 가지입니다. legacy ID 직접 테스트가 19종별 행렬은 아니고 일반 코드와 대표 kind 테스트로 보장되며, 이번 판정에서는 지시대로 테스트를 실행하지 않았으므로 답변자 3의 `38 passed, 7 subtests passed` 수치는 독립 재확인하지 않았습니다.

사용한 근거: 이 worktree의 파일만 사용함.
````

</details>

## 구현·검토 영수증

### RED에서 GREEN으로

- 격리 worktree의 기준 HEAD는 `76827c3fe3e09104e657db515e0b21a37eb55b18`이고, 변경 전 엔진
  기준선은 `1522 passed, 105 subtests passed`였다.
- 설치 runtime 첫 기준선은 worktree에 `.venv`가 없어 subprocess가 system Python을 잡고
  `tree_sitter`를 찾지 못해 3건 실패했다. product 결함이 아니라 interpreter 경로 문제로 분리했고,
  원본 checkout의 기존 전용 venv를 임시 symlink로 연결한 같은 명령에서 99건 통과를 확인했다.
- architecture 테스트는 네 지도 문서와 세 진입 링크가 없어서 정확히 9건 RED였다.
- object/installer 계약은 template source와 설치 산출물이 없어서 정확히 10건 RED였다.
- 구현 뒤 architecture/object/installer 통합 표적은 `58 passed, 10 subtests passed`가 됐다.

### 독립 검토에서 고친 것

- 설계 검토에서 query/search 혼합, 빠진 CLI·코퍼스 밖 쓰기, 판정 관문이 아닌 cold rehearsal,
  placeholder JSON, 잘못된 DecisionRecord edge, CodeLocator 과거 읽기/신규 쓰기 혼동을 먼저 고쳤다.
- architecture 구현 검토는 build objects 출력과 apply manifest를 한 행으로 묶은 표현 1건을 찾아
  각각의 파일·stdout 책임으로 분리한 뒤 READY였다.
- data 계약 검토는 추가 엉뚱한 참조를 허용하던 core graph 부분집합 검사, 모든 kind에 적용되는
  legacy ID 보존 규칙 누락, promotion 테스트와 실제 kind template의 느슨한 결속을 찾았다. 전체 참조
  tuple exact 비교, 공통 ID 경계 문서, 실제 GlossaryTerm/ReviewRecord template 결속으로 고쳤다.
- cold query 답변은 redaction restricted 계산이 일부 query 경로에만 있고 search에는 일반 객체 수준
  라벨이 없다는 추가 `ENGINE_GAP`을 찾아냈다. 지도가 모든 결과에 적용되는 것처럼 읽히지 않게
  runtime/data/change map과 드리프트 테스트를 보강했다.
- 저장소 밖 memory 사용 표기가 있던 1차 query·tokenizer 답변과 1차 판정은 최종 관문에서 제외했다.
  두 답변을 memory·rollout·과거 세션·인터넷 금지 조건으로 다시 받고, 별도 판정자 v3가 유효 답변
  세 건을 모두 PASS, 전체 READY로 판정했다.

### fresh 실행 결과

| 관문 | 결과 |
|---|---|
| architecture + object contract + installer 전체 | `58 passed, 10 subtests passed` |
| 엔진 전체 pytest | `1542 passed, 105 subtests passed` |
| 설치되는 ingest runtime unittest | `Ran 99 tests`, `OK` |
| 유효 cold query / tokenizer / CodeLocator | `PASS / PASS / PASS` |
| 저장소 밖 memory 금지 최종 독립 판정 v3 | `READY` |

이번 변경은 문서·설치 reference·JSON 예시·테스트뿐이다. production Python, 검색·색인 입력 계약,
소비 프로젝트의 실제 코퍼스를 바꾸지 않았으므로 실코퍼스 `brain/checks`, `eval`, 실모델 rebuild는
실행하지 않았다. Task 17 정본 상세는 그대로 두었고 Task 18, 발표 자료, 커밋·push도 실행하지 않았다.
