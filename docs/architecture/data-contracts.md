# 데이터 계약 지도

이 문서는 Project Brain이 저장하는 19종 객체의 **현재 계약을 찾는 지도**다. 설계 의도보다 현재
동작을 확인해야 할 때는 다음 코드와 테스트가 이 문서보다 우선한다.

- shape·enum·상태 조건: `src/project_brain/schema.py`
- ID 문법과 ID-필드 결속: `src/project_brain/id_grammar.py`
- 참조로 인정하는 필드: `src/project_brain/reference_fields.py`
- build 입력과 자동 조립: `src/project_brain/assembly.py`
- coverage·독립 expected planner: `src/project_brain/coverage.py`, `src/project_brain/assembly.py`
- 신규·변경 쓰기 관문: `src/project_brain/mutation.py`, `src/project_brain/write_semantics.py`,
  `src/project_brain/code_verify.py`
- 합쳐진 store의 관계 점검: `src/project_brain/lint.py`
- 실제 검색 입력과 소비: `src/project_brain/surface.py`, `src/project_brain/router.py`,
  `src/project_brain/search.py`, `src/project_brain/audit.py`

실행 가능한 JSON 원본은
`src/project_brain/templates/ingest/references/object-templates/`에 있다. kind별 파일은 shape,
정상 graph는 관계, 두 coverage template은 assembled/direct binding, build notes는 조립 입력,
invalid manifest는 실패 층을 각각 검증한다. 이 `object-templates` 디렉터리가 설치 JSON의 단일 원본이다.

## 한 객체가 저장되기까지

```text
CoverageContract
  └─ independent expected planner + notes identity comparison
      └─ build notes
        └─ validate_notes
      └─ assembly.build (저장하지 않음)
          └─ 완성 객체 묶음
              └─ MutationService.plan
                  ├─ coverage/build binding + 입력 schema·ID·write semantics
                  ├─ 상태 전환·CodeLocator 검증
                  └─ 합쳐진 store lint
                      └─ MutationService 단일 clock
                          └─ corpus_io transaction 또는 no-op receipt
```

`BASE_REQUIRED`나 `KIND_REQUIRED`만 읽고 신규 쓰기 계약 전체를 판단하면 안 된다. schema는 객체 한
개의 모양을 검사한다. ID 결속, dangling, 관계의 양방향성, 상태 후퇴, CodeLocator의 실제 git
좌표는 뒤 관문에서 검사한다.

### 공통 필수 키

19종 모두 다음 키를 가진다.

```text
id, kind, schema_version, status, poc_priority, truth_role, title,
created_at, updated_at, tags, evidence_refs
```

- `status`: `candidate | reviewed | superseded | archived | rejected`
- `poc_priority`: `P0 | P1 | P2`
- `truth_role`: kind마다 아래 표의 고정값
- `evidence_refs`: 등록된 목록 참조다. reviewed `GlossaryTerm`과 `DomainMapping`에서만 1개 이상을
  schema가 강제한다.

required는 우선 **키 존재**를 뜻한다. 일반 문자열이 비어 있지 않은지, timestamp가 실제
ISO-8601인지, 자유 객체의 내부 구조가 무엇인지는 별도 조건이 없는 한 schema가 모두 보장하지
않는다.

### build 입력과 완성 저장 객체

assembled coverage는 `verify_groups`, context mode, 아래 8개 notes section identity,
`expected_objects`를 선언한다. direct coverage는 완성 객체의 exact `(id, kind)`만 선언한다.
coverage가 없거나 notes/planner/build 결과와 다르면 pre-write 실패한다. coverage는 원문 의미가
완전하다고 추론하지 않는다.

`build-notes.complete.template.json`의 9개 section은 책임이 다르다.

| section | 책임과 결과 |
|---|---|
| `context` | context key·commit·repo와 경계 입력. display/boundary가 있으면 `DomainContext`를 만든다 |
| `sources` | 출처·ACL·redaction을 받아 `EvidenceManifest`를 만든다 |
| `code_anchors` | path·symbol·quote를 받아 `CodeLocator`와 중첩 locator가 있는 `EvidenceRef`를 만든다 |
| `glossary` | 논리 key와 의미·근거를 받아 `GlossaryTerm`을 만든다 |
| `mappings` | 신규/기존 용어와 코드 key를 풀어 `DomainMapping`을 만든다 |
| `decisions` | 결정과 근거를 만들고 `affects`를 매핑의 `decision_record_ids`로 역채운다 |
| `refs` | store의 기존 ID를 kind/status 기대값과 함께 해소한다 |
| `updates` | `expected_updated_at`와 kind별 allowlist로 기존 객체를 갱신하고 precondition hash를 만든다 |
| `extra_objects` | ID·역할·timestamp까지 완성된 저장 객체를 그대로 받는 직접 입력 경로다 |

일반 section에서는 적재 에이전트가 의미·출처·경계를 쓰고 build가 ID, `truth_role`, 공통 metadata를
조립한다. `extra_objects[]`에는 build가 빠진 필드를 채워 주지 않는다. CodeLocator의
`verified_at`와 표준 `title`은 최종 write verifier가 실제 repo를 확인한 뒤 확정한다.

### 신규·변경 write semantics와 timestamp owner map

신규 또는 값이 바뀐 객체는 required 문자열이 비어 있지 않고 timestamp가 timezone-aware ISO인지
`write_semantics.py`에서 검사한다. 같은 source field/value의 legacy 문제는 읽기·무변경 보존만
허용되며 신규 쓰기의 완화로 전파하지 않는다.

| 필드 | 소유자 | 쓰기 의미 |
|---|---|---|
| `created_at`, `updated_at` | MutationService 단일 clock | live create/update에서 caller 값을 믿지 않고 같은 event time으로 stamp |
| `verified_at` | CodeLocator verifier + MutationService clock | 새 좌표·좌표 변경·mark-checked 검증 성공 시 기록 |
| `generated_at` | projection builder + MutationService clock | live projection 생성·갱신 event |
| `reviewed_at` | reviewer 명시 입력, 없으면 promote clock | 검토 사건 시각이며 lifecycle과 별도 의미 |
| `captured_at`, `happened_at`, `valid_from`, `valid_until`, `as_of`, `indexed_at` | caller/source | 원문·도메인 사건 시각이므로 실제 근거에서 가져옴 |

template에 든 고정 timestamp는 JSON shape fixture이지 실제 생성 시각의 증거가 아니다. 수기 JSON
편집은 이 write boundary를 우회하므로 즉시 탐지를 보장하지 않으며 **다음 audit** 전수 검사에서야
드러나는 문제가 있을 수 있다.

## ID와 참조 공통 규칙

slug는 소문자 영숫자와 단일 하이픈만 쓴다. `EvidenceRef`와 `CodeLocator`의 anchor key에는
중복 해소용 `--N` suffix가 허용된다. `SlideRef.slide_no`는 앞자리 0 없는 decimal이다.

| kind | 정식 ID와 결속 필드 |
|---|---|
| EvidenceManifest | `manifest.<ctx>.<key>` |
| EvidenceRef | `evref.<ctx>.<anchor-key>` |
| ReviewRecord | single `review.<target-object-id>` 또는 bundle `review.bundle.<ctx>.<key>` |
| EventLedgerRecord | `ledger.<ctx>.<key>` |
| TemporalFact | `fact.<ctx>.<key>` |
| CodeLocator | `code.<ctx>.<anchor-key>` |
| DomainContext | `context.<ctx>`; `context_key`가 `<ctx>`와 같아야 한다 |
| GlossaryTerm | `g.<ctx>.<key>`; `context_id`의 ctx가 같아야 한다 |
| ContextProjection | `projection.<ctx>.context-md` 또는 `projection.<ctx>.<requirement-key>.reuse`; `context_id`·`format` 결속 |
| CurrentView | `view.<view-type>.<key>`; `view_type` 결속 |
| KnowledgePage | `page.<category>.<key>`; `category` 결속 |
| IndexRecord | `index.<index-name>.<sha256(source_object_id) 앞 16자리>`; name·source digest 결속 |
| SpecDocument | `spec.<document-key>` |
| SpecRevision | `revision.<document-key>.<revision-key>`; document ID·revision label 결속 |
| SlideRef | `slide.<document-key>.<revision-key>.<decimal>`; revision ID·slide number 결속 |
| SlackThread | `slack.<ctx>.<key>` |
| DecisionRecord | `decision.<ctx>.<key>` |
| DomainMapping | `mapping.<ctx>.<key>`; `context_id`·`mapping_key` 결속 |
| Insight | `insight.<ctx>.<key>` |

참조 registry는 다음을 공통으로 순회해 type, dangling, graph edge, migration rewrite에 쓴다.

- 단일: `context_id`, `derived_from_event_id`, `evidence_manifest_id`, `review_record_id`,
  `source_object_id`, `spec_document_id`, `spec_revision_id`, `supersedes`, `target_object_id`
- 목록: `affected_context_ids`, `affected_glossary_term_ids`, `affected_mapping_ids`,
  `code_locator_ids`, `decision_record_ids`, `evidence_refs`, `glossary_term_ids`, `related_objects`,
  `slack_thread_ids`, `source_event_ids`, `source_fact_ids`, `source_object_ids`, `spec_revision_ids`,
  `supersedes_mapping_ids`, `target_object_ids`, `vouched_by_mapping_ids`
- 중첩: `/locator/code_locator_id`

registry는 참조 대상 ID가 존재하는지는 검사하지만, 대부분의 필드에서 **대상 kind까지 일반적으로
강제하지 않는다.** 아래 표의 대상 kind는 현재 생산자·ID 결속·소비 의미가 정한 의도다.

## 19종 계약표

표의 `R`은 공통 키 외 필수 키, `O`는 선택 키다. “직접 입력”은 완성 객체를
`extra_objects[]`나 ingest payload로 넘기는 경로다.

| kind / 역할 | R·조건·금지 | ID·정상 생성·필드 작성자 | 참조와 의도 대상 | 소비처·과거 읽기와 신규 쓰기 |
|---|---|---|---|---|
| **EvidenceManifest** / `source` | R `source_type`, `locator`, `captured_at`, `captured_by`, `sensitivity`, `acl`, `redaction_status`. source와 redaction enum 강제 | `manifest.<ctx>.<key>`. 보통 `sources[]` → build. 적재자가 출처·locator·ACL·redaction을 쓰고 build가 공통 meta를 만든다 | 공통 `evidence_refs` 0+; 다른 `EvidenceRef.evidence_manifest_id`가 이 객체를 가리킨다 | provenance와 일부 query 경로의 restricted 판정. 모든 query/search 결과의 ACL 장벽은 아니다. 과거 `redaction_status=none`도 현재 schema/lint에서는 비정상이며 신규 쓰기는 `raw_local|staged|approved|rejected`만 허용 |
| **EvidenceRef** / `reference` | R `evidence_manifest_id`, `ref_type`, `locator`, `summary`; `ref_type` enum | `evref.<ctx>.<anchor-key>`. code anchor·decision build 또는 직접 입력. 적재자가 원문 위치·요약을 주고 build가 ID/meta·code nested ref를 만든다 | manifest 1; O `/locator/code_locator_id` → CodeLocator 1; 공통 evidence 0+ | provenance, raw/restricted, graph·audit 역연결. 일반 schema·ID·dangling을 통과해야 하며 별도 legacy 완화 없음 |
| **ReviewRecord** / `review` | R `reviewer`, `reviewed_at`, `verdict`. single은 `target_object_id` 필수이며 bundle 필드 금지. bundle은 `review_scope=mapping_bundle`, `target_object_ids` 1+, `bundle_key`, `confirmation_key` 필수이고 single target 금지 | single `review.<target-id>`, bundle `review.bundle.<ctx>.<key>`. 정상 경로는 `promote()`. 검토자가 판단·대상을 주고 엔진이 record와 대상의 `review_record_id`를 함께 만든다 | single target → canonical object 1; bundle targets/vouched IDs → DomainMapping; 공통 evidence 0+ | promotion·graph·audit. bundle target은 같은 ctx의 DomainMapping이어야 한다. 손작성보다 promote 결과를 사용하며 신규 쓰기에 과거 shape 완화 없음 |
| **EventLedgerRecord** / `event` | R `event_type`, `happened_at`, `summary`, `related_objects`; event_type은 현재 자유 문자열 | `ledger.<ctx>.<key>`. 전용 assembly 없음, 직접 입력. 적재자가 사건·시점·관련 객체를 쓴다 | `related_objects` → canonical object 0+; evidence 0+ | 변경 사유 router, TemporalFact의 원인, 검색 표면. 일반 strict write; 기존의 별도 grandfather 규칙 없음 |
| **TemporalFact** / `fact` | R `subject`, `predicate`, `value`, `scope`, `valid_from`, `derived_from_event_id`, `confidence`; O `valid_until`, `supersedes`; confidence enum. 같은 open reviewed subject/predicate의 다른 값은 충돌 | `fact.<ctx>.<key>`. 전용 assembly 없음, 직접 입력. 적재자가 값·범위·유효시점·파생 사건을 쓴다 | event 1; O supersedes → TemporalFact 1; evidence 0+ | current/as-of/why-changed router, conflict lint, 검색 표면. 과거 값은 보통 reviewed를 유지하고 `valid_until`로 닫는다; 신규 묶음은 dangling·conflict를 통과해야 한다 |
| **CodeLocator** / `reference` | schema R `repo`, `path`, `locator_source`, `verified_at`; locator source enum. 새/좌표변경/mark-checked에서는 추가로 full `commit_sha`, `symbol`, `verified_quote`, repo context 필요 | `code.<ctx>.<anchor-key>`. `code_anchors[]` build 또는 직접 입력 후 mutation verifier. 적재자가 좌표·quote를 주고 엔진이 실제 git 확인 뒤 `verified_at`와 symbol 기반 title을 확정 | 다른 객체의 `code_locator_ids`, EvidenceRef nested locator가 가리킨다; evidence 0+ | 구현 위치, 검색 표면, stale/quote/symbol audit. `verified_at` 누락은 verifier 전 mutation 입력에만 임시 허용. 좌표 불변 기존 객체는 quote·축약 SHA를 보존할 수 있지만 신규/좌표 변경에는 같은 완화를 적용하지 않는다 |
| **DomainContext** / `domain` | R `context_key`, `project_id`, `display_name`, `boundary_summary`, `in_scope`, `out_of_scope`, `injection_profile`, `glossary_term_ids`; audience/export format enum. 과거 `path`, `source_format` 금지 | `context.<ctx>`와 `context_key` 결속. context notes에 display/boundary가 있으면 build. 적재자가 경계·scope를 쓰고 build가 기본 audience/meta를 만든다 | glossary IDs → GlossaryTerm 0+; evidence 0+ | scope 추론, glossary·projection source, 검색 표면. legacy `path`/`source_format`은 load 자체와 별개로 현재 lint에서 비정상이며 새 정본에 쓸 수 없다 |
| **GlossaryTerm** / `domain` | R `context_id`, `term`, `definition`. candidate면 `candidate_state`·`candidate_source`; rejected면 `rejection`; reviewed면 evidence 1+. reviewed가 conflict/open questions를 유지하면 금지. synonyms/aliases는 3자 이상이며 blocklist 일반명사 금지 | `g.<ctx>.<key>`와 context 결속. glossary build, 직접 입력, promote. 적재자가 의미·근거·후보 상태를 쓰고 engine이 ID/meta, promote 시 review 연결을 만든다 | context 1; O review record 1, supersedes 1; evidence → EvidenceRef reviewed 1+ | 정확 의미·질의 정규화·매핑 표면·projection·promotion. 신규 변경은 lifecycle 조건을 모두 통과해야 하고, 과거 ID 문제 보존 외 schema 완화 없음 |
| **ContextProjection** / `index` | R `context_id`, `format`, `source_object_ids`, `source_content_hash`, `projection_hash`, `generated_at`, `generated_by`, `stale_policy`; format enum, stale policy는 `fail_on_manual_edit`만. ID variant와 format 결속 | context-md builder는 reviewed Context/terms/mappings, reuse builder는 prompt payload를 만든다. 엔진이 ID·hash·locator·시각을 계산하고 적재자는 source 선택/reuse payload를 준다 | context 1; source objects schema상 0+, 공식 creator는 실제 source 전제; evidence 0+ | hash/manual-edit/file lint, context-md export, prompt_payload 전용 reuse 검색 lane. hash를 손으로 추측하지 않는다; stale repair도 허용 필드만 바꾼다 |
| **CurrentView** / `synthesis` | R `view_type`, `as_of`, `source_fact_ids`, `source_event_ids`, `summary`; view type과 ID 결속 | `view.<view-type>.<key>`. 전용 creator 없음, 직접 입력. 적재자가 집계 시점·요약·sources를 모두 쓴다 | facts → TemporalFact 0+; events → EventLedgerRecord 0+; evidence 0+ | current-status router가 facts와 비교해 stale warning, 검색 표면. 직접 입력은 schema·ID·dangling만으로 전용 집계 정확성이 보장되지 않는다 |
| **KnowledgePage** / `synthesis` | R `category`, `path`, `summary`, `source_object_ids`, `stale_policy`; category-ID 결속. stale policy enum 없음 | `page.<category>.<key>`. 전용 creator 없음, 직접 입력 | sources → canonical objects 0+; evidence 0+ | 현재 storage·generic graph 중심이며 검색 surface dispatch 없음. `manual` 예시는 shape 통과값일 뿐 제품 정책을 확정하지 않으며 legacy/write 별도 완화 없음 |
| **IndexRecord** / `index` | R `index_name`, `source_object_id`, `indexed_at`, `content_hash`; index name enum과 ID digest 결속. content hash 의미·형식은 별도 강제 없음 | `index.<index-name>.<source ID digest>`. 전용 creator 없음, 직접 입력; 실제 검색 DB rebuild가 이 kind를 만들지는 않는다 | source object 1; evidence 0+ | storage·generic graph·ID 검증 중심, 검색 surface 없음. 예시 content hash는 정식 ID digest 계산값이지 제품 수준 content hash 계약을 새로 정의하지 않는다 |
| **SpecDocument** / `reference` | R `source_system`, `canonical_locator`; 전용 enum 없음 | `spec.<document-key>`. 전용 creator 없음, 직접 입력 | evidence 0+; SpecRevision이 이 객체를 가리킨다 | storage·SpecRevision parent·generic graph, 검색 surface 없음. 직접 입력 strict contract 외 별도 legacy 완화 없음 |
| **SpecRevision** / `reference` | R `spec_document_id`, `revision_label`, `captured_at`, `slide_refs`; document key·revision label-ID 결속. `slide_refs` 요소 구조는 미검증 | `revision.<document-key>.<revision-key>`. 전용 creator 없음, 직접 입력 | spec document 1; `slide_refs`는 의도상 SlideRef지만 registry 밖; evidence 0+ | storage·SlideRef parent·generic graph, 검색 surface 없음. 빈 `slide_refs` 예시는 기능 완성 주장이 아니다 |
| **SlideRef** / `reference` | R `spec_revision_id`, `slide_no`; revision keys·decimal slide-ID 결속 | `slide.<document-key>.<revision-key>.<decimal>`. 전용 creator 없음, 직접 입력 | spec revision 1; evidence 0+ | storage·generic graph, 검색 surface 없음. ID 결속은 강제하지만 revision 객체의 존재는 합친 store lint에서 확인한다 |
| **SlackThread** / `source` | R `channel_id`, `thread_ts`, `participants`, `message_refs`, `summary`; participants/message_refs 요소 구조·비공백 규칙 없음 | `slack.<ctx>.<key>`. 전용 creator 없음, 직접 입력 | `message_refs`는 registry 밖; evidence 0+ | storage·generic graph, 검색 surface 없음. 빈 목록 예시는 실제 메시지 모델이나 dangling 검증을 확정하지 않는다 |
| **DecisionRecord** / `event` | R `decision_type`, `summary`, `decision`, `source_object_ids`, `affected_context_ids`, `spec_reflected`; 두 enum 강제. evidence는 비어도 정상 | `decision.<ctx>.<key>`. decisions build 또는 직접 입력. 적재자가 판단·근거·affects를 쓰고 build가 IDs/meta와 affected context를 만든다 | sources 보통 EvidenceRef 0+; contexts 0+; O mappings/glossary 0+; evidence 0+ | why-changed, 매핑-결정 관계 lint, 검색 표면. `source_object_ids`가 정본 근거이고 `evidence_refs`는 provenance 보조다. reviewed mapping을 affect하면 mapping의 decision 역참조가 필요 |
| **DomainMapping** / `domain` | R `context_id`, `mapping_key`, `canonical_summary`, `meaning`, `boundary`, `glossary_term_ids`, `decision_record_ids`; reviewed면 evidence 1+. O `review_state`는 정해진 4개 boolean 키만 | `mapping.<ctx>.<key>`와 context/key 결속. mappings build, 직접 입력, bundle promote. 적재자가 의미·경계·refs를 쓰고 build가 ID/meta 및 decision inverse를 만든다 | context 1; glossary/decision 0+; O code locators/superseded mappings 0+, review record 1; evidence reviewed 1+ | 핵심 query 객체, graph rerank, projection, term promotion, supersession/decision lint. reviewed↔candidate 후퇴 금지; superseded target lifecycle도 merged lint를 통과해야 한다 |
| **Insight** / `synthesis` | R `body`, `source_object_ids`. candidate 금지. O `insight_type=cross-cutting-risk|operational-lesson`; 전자는 sources 2+, 그 밖은 1+ | `insight.<ctx>.<key>`. 전용 assembly 없음, 검증 뒤 직접 입력. 적재자가 종합 판단·scope·sources를 쓴다 | sources → canonical objects 1+; O code locators 0+; evidence 0+ | reviewed 전용 `advisories` lane과 검색 표면. candidate는 노출 통로가 없어 신규 쓰기에서 거부하며 별도 legacy 후보 보존 정책 없음 |

## 공통 legacy ID 문법과 신규 쓰기 경계

CodeLocator 외 kind에도 읽기 호환과 신규 쓰기의 비대칭이 있다.

1. `BrainStore.load()`가 과거 JSON을 읽었다는 사실은 그 ID가 현재 문법에 맞는다는 뜻이 아니다.
2. 기존 객체의 `invalid_id` 또는 `unknown_grammar`는 입력 객체의 안정 해시와 ID 문제 목록이 기존값과
   정확히 같을 때만 mutation에서 임시 보존된다.
3. 같은 legacy ID 객체의 의미 필드를 바꾸거나, 같은 문제를 가진 새 객체를 추가하거나, ID 문제 목록을
   바꾸면 `new_or_modified_lint_problem`으로 거부한다. ID가 아닌 기존 lint 문제는 이 규칙으로
   보존하지 않는다.
4. `id_only_migration`은 예외를 계속 남기는 우회가 아니라, 적용 뒤 grandfathered ID 문제를 0건으로
   끝내야 하는 정리 경로다.

따라서 19종 template은 모두 현재 ID 문법을 통과하는 신규 쓰기 출발점이다. 기존 비정상 ID를 template로
복제하거나, load 성공을 새 정본 허용으로 일반화하지 않는다. 직접 회귀는
`tests/test_mutation.py::test_unchanged_preexisting_id_problem_is_temporarily_grandfathered`,
`test_changed_or_new_invalid_id_is_rejected`, `test_unchanged_unknown_grammar_is_grandfathered_with_exact_problem_binding`,
`test_id_migration_completion_gate_requires_zero_grandfathered_problems`가 고정한다.

## CodeLocator의 과거 읽기와 신규 쓰기 경계

이 비대칭이 가장 자주 오해를 만든다.

1. 최종 저장 객체와 일반 lint에는 `verified_at`가 필요하다.
2. mutation 입력 precheck에서만 verifier가 채울 `verified_at` 누락을 임시 허용한다.
3. 새 locator, 좌표 변경, `mark-checked`는 repo context와 full SHA, `verified_quote`, symbol을 요구하고
   실제 commit/blob/path/symbol/quote를 확인한다.
4. 성공하면 엔진이 입력의 낡은 `verified_at`와 사람이 쓴 title을 믿지 않고 새 시각과 symbol title을
   확정한다.
5. 좌표가 그대로인 기존 locator는 과거 quote 누락이나 축약 SHA를 그대로 보존할 수 있다. 이 경로는
   새 ID나 좌표 변경 쓰기의 우회로가 아니다.

`BrainStore.load()`가 JSON을 읽을 수 있다는 사실과 `MutationService`가 새 정본으로 받아들인다는
사실을 분리해서 말해야 한다.

## 정상 연결 그래프

`object-graph.complete.template.json`은 다음 6개 reviewed 객체를 한 연결 요소로 만든다.

```text
EvidenceManifest ← EvidenceRef
                       ↑
DomainContext ↔ GlossaryTerm
      ↑             ↑
      └──── DomainMapping ↔ DecisionRecord
                  ↑          ↑
                  └──────────┘
```

정확한 방향은 다음과 같다.

- `EvidenceRef.evidence_manifest_id` → EvidenceManifest
- `DomainContext.glossary_term_ids` → GlossaryTerm
- `GlossaryTerm.context_id` → DomainContext
- GlossaryTerm/DomainMapping/DecisionRecord의 `evidence_refs` → EvidenceRef
- `DomainMapping.context_id` → DomainContext
- `DomainMapping.glossary_term_ids` → GlossaryTerm
- `DomainMapping.decision_record_ids` ↔ `DecisionRecord.affected_mapping_ids`
- `DecisionRecord.affected_context_ids` → DomainContext
- `DecisionRecord.source_object_ids` → EvidenceRef

CodeLocator는 git 검증, ReviewRecord는 promote, ContextProjection은 hash 생성 경계가 따로 있으므로 이
최소 graph에 가짜로 섞지 않는다. 별도 테스트가 CodeLocator template을 실제 git write gate에,
GlossaryTerm·ReviewRecord template을 promote plan에, ContextProjection template을 공식 builder의
재계산 결과에 각각 결속한다.

## 검증된 실패 예시

`invalid/manifest.json`은 반례를 단순 샘플이 아니라 실행 계약으로 기록한다.

| 첫 실패 층 | 대표 반례 | 기대 결과 |
|---|---|---|
| notes | context commit 누락 | `validate_notes()` 메시지 |
| schema | 공통/kind 키 누락, candidate metadata, reviewed evidence, redaction enum | `validate_object()` 메시지 |
| lint | 등록 참조 dangling | `dangling_reference` |
| mutation | 신규/좌표변경 CodeLocator quote 누락, reviewed→candidate | `quote_required`, `status_transition_invalid` |

mutation 반례는 setup이 중요하다. CodeLocator는 임시 git repo와 동적 full SHA가 필요하고, 좌표 변경과
상태 후퇴는 기존 store 객체가 필요하다. JSON에 가짜 placeholder를 넣지 않고 테스트 adapter가 이
실행 환경만 주입한다.

## 현재 확인된 엔진 빈틈

다음은 문서나 template로 해결됐다고 주장하지 않는다.

- **대상 kind 미강제:** reference registry는 대부분 존재만 확인한다. 의도와 다른 kind를 가리켜도
  ID 결속이 별도로 없는 필드는 통과할 수 있다.
- **registry 밖 목록:** `SpecRevision.slide_refs`, `SlackThread.message_refs`는 type, dangling, rewrite,
  graph edge를 공통으로 검사하지 않는다.
- **전용 creator/검색 표면 없음:** `KnowledgePage`, `IndexRecord`, `SpecDocument`, `SpecRevision`,
  `SlideRef`, `SlackThread`는 direct-extra-object와 storage/graph 중심이다.
- **자유 의미 필드:** `KnowledgePage.stale_policy`, `IndexRecord.content_hash`, participants/message/slide
  요소 구조는 현재 schema가 제품 정책을 확정하지 않는다.
- **projection source cardinality:** schema는 `ContextProjection.source_object_ids=[]`도 허용하지만 공식
  creator와 신선도 의미는 실제 source를 전제로 한다.

이 항목은 `ENGINE_GAP`이다. 이번 전체 지도는 빈틈을 드러내고 테스트 예시가 거짓 보장을 하지 않게
만들 뿐 production 동작은 바꾸지 않는다.

## 변경할 때 확인할 곳

- kind·required·enum을 바꾸면 `schema.py`, ID grammar, 19종 JSON 집합, invalid case를 함께 본다.
- 참조 필드를 바꾸면 `reference_fields.py`, lint, graph, migration rewrite, 정상 graph를 함께 본다.
- build section을 바꾸면 `validate_notes()`, assembly 결과, build notes, 설치 ingest runtime을 함께 본다.
- CodeLocator 계약을 바꾸면 schema precheck와 final schema, mutation, code verifier, audit, legacy pair를
  함께 본다.
- 검색 소비를 바꾸면 surface extractor, router/search lane과 소비 데이터 레포 checks/eval 범위를
  `change-map.md`에서 고른다.
