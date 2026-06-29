# 객체 모델 — kind별 필수 필드·enum·연결

객체를 실제로 만들 때 이 파일을 따른다. **단일 진실은 엔진 레포의 `src/project_brain/schema.py`다** — 여기 적힌 게
schema.py와 어긋나 보이면 그 파일을 직접 읽어 확인하라(스킬 작성 시점 스냅샷일 수 있다).
`ingest`가 모든 객체에 `validate_object`를 돌리므로, 필수 필드 누락이나 잘못된 enum 값은 적재가 거부한다.

## 목차

- 모든 객체 공통 필드(BASE_REQUIRED)
- kind별 필수 필드
- truth_role 강제 매핑
- enum 값 집합
- 연결 필드(고아 방지)
- 실물 JSON 예시

## 모든 객체 공통 필드 (BASE_REQUIRED)

모든 객체는 이 11개를 반드시 가진다:

```
id, kind, schema_version, status, poc_priority,
truth_role, title, created_at, updated_at, tags, evidence_refs
```

- `status`: `candidate` | `reviewed` | `superseded` | `archived` | `rejected`
- `poc_priority`: `P0` | `P1` | `P2`
- `schema_version`: 현재 `"0.1"`
- `evidence_refs`: EvidenceRef id 배열(없으면 `[]`).
- `objbase.base()` 헬퍼가 `schema_version`/`poc_priority`/`created_at`/`updated_at`/`tags`/`evidence_refs`를
  `setdefault`로 채운다. `status`는 채우지 않으니 caller가 직접 박는다.
- caller가 `evidence_refs`/`tags`처럼 값을 채울 키는 `base()` 호출 **전에** obj에 미리 넣어라. setdefault라
  base가 빈 값으로 덮지는 않지만, 순서가 바뀌면 빈 `[]`가 박힌다(e2e 테스트 `_candidate_term` 패턴 참고).

## kind별 필수 필드

BASE_REQUIRED 외에 kind마다 추가 필수 필드(schema.py `KIND_REQUIRED` 그대로):

| kind | 추가 필수 필드 |
|---|---|
| EvidenceManifest | source_type, locator, captured_at, captured_by, sensitivity, acl, redaction_status |
| EvidenceRef | evidence_manifest_id, ref_type, locator, summary |
| ReviewRecord | reviewer, reviewed_at, verdict |
| EventLedgerRecord | event_type, happened_at, summary, related_objects |
| TemporalFact | subject, predicate, value, scope, valid_from, derived_from_event_id, confidence |
| CodeLocator | repo, path, locator_source, verified_at |
| DomainContext | context_key, project_id, display_name, boundary_summary, in_scope, out_of_scope, injection_profile, glossary_term_ids |
| GlossaryTerm | context_id, term, definition |
| SpecDocument | source_system, canonical_locator |
| SpecRevision | spec_document_id, revision_label, captured_at, slide_refs |
| SlideRef | spec_revision_id, slide_no |
| SlackThread | channel_id, thread_ts, participants, message_refs, summary |
| DecisionRecord | decision_type, summary, decision, source_object_ids, affected_context_ids, spec_reflected |
| DomainMapping | context_id, mapping_key, canonical_summary, meaning, boundary, glossary_term_ids, decision_record_ids |
| Insight | body, source_object_ids |

(소급 적재에서 잘 안 쓰는 kind는 schema.py에서 확인: ContextProjection, CurrentView, KnowledgePage, IndexRecord.)

CodeLocator의 `commit_sha`는 스키마상 선택 필드지만 **적재 시 기입 의무**(SKILL.md 절대 규칙 8) —
라인을 확인한 코드의 기준 커밋(`git rev-parse --short=10`). 비우면 코드 변경 감지 기준점이 없다
(2026-06-12 348개 공백 → 소급 백필 수습 사례).

## Insight 적재 규칙 (2026-06-15 신설 kind)

기존 kind로 안 담기는 "2개 이상 객체·구현·결정을 가로지르는 관찰/위험/교훈". 적재가 특수하다:

- **candidate 저장 거부** → 검증 끝낸 것만 `status:"reviewed"`로 직접 `ingest`(promote 경로 없음 — `ingest`는 reviewed 직접 수용). 사용자 진술/합의가 전제이므로 검토 라운드(사용자 확인)를 거친 뒤 reviewed로 넣는다. ReviewRecord는 필수 아님(promote 경로가 없어 자동 생성도 안 됨) — 진술 추적은 아래 `evidence_refs`로 하고, 검수자를 명시하려면 ReviewRecord(`reviewer:"user-statement"`)를 별도로 만들 수 있으나 강제는 아니다.
- **필수**: `body`(자유 텍스트 본문) + `source_object_ids`. A형(`cross-cutting-risk` — 코드·구현·결정 사이 어긋남/위험) ≥2, B형(`operational-lesson` — 운영·프로세스 교훈) ≥1.
- **`source_object_ids` = 이 교훈/위험을 뒷받침하는 _이미 적재된_ 객체**(그 패턴이 실제로 나타난 DomainMapping·DecisionRecord 등). 진술 _출처_를 담는 `evidence_refs`와 역할이 다르다 — source는 "무엇을 가로지르는가", evidence는 "누가 어디서 말했나". 가리킬 객체가 store에 없으면 고아 방지 게이트(연결 필드 섹션)에 막히니, 뒷받침 객체부터 적재하거나 아직 없으면 미검증으로 보고 backlog로 보낸다. 예: "베타 이후 문서 미갱신" 교훈은 기획서 80%–코드 82% 매핑, 점수 클라서술–서버자동 매핑, 주석 stale 매핑 3건을 source로 가로지른다.
- **`scope`**(적용 범위, **자유 텍스트**): 선택 필드지만 검수 게이트가 존재를 본다(특히 B형 — 비우면 "좋은 말" 저장소로 전락).
- **`code_locator_ids`**(선택, A형 코드 앵커 — `source_object_ids`와 별도).
- **evidence_refs**: reviewed Insight는 강제 안 됨(non-empty는 reviewed GlossaryTerm·DomainMapping만). 단 출처가 사용자 진술이면 근거를 남긴다 — session EvidenceManifest(`source_type:"session"`, `redaction_status:"approved"`) + EvidenceRef(`ref_type:"session_turn"`)를 만들어 연결(꿀단지 data-first 선례).
- 저장 위치: 객체는 `objects/insights/`, 근거 manifest는 `raw/manifests/`(연결 무결성은 `project-brain lint`).
- 적재 후 `project-brain lint`로 `source_object_ids` dangling(가리키는 근거가 없거나 superseded) 점검.
- 회상은 일반 결과(results)가 아니라 advisories(곁들임) 별도 통로로만 노출된다(검색층 분리).

## truth_role 강제 매핑

`truth_role`은 kind마다 정해진 값이어야 한다(schema.py `KIND_TRUTH_ROLE`). 틀리면 거부:

| kind | truth_role |
|---|---|
| EvidenceManifest | source |
| EvidenceRef | reference |
| ReviewRecord | review |
| EventLedgerRecord | event |
| TemporalFact | fact |
| CodeLocator | reference |
| DomainContext | domain |
| GlossaryTerm | domain |
| SpecDocument / SpecRevision / SlideRef | reference |
| SlackThread | source |
| DecisionRecord | event |
| DomainMapping | domain |
| Insight | synthesis |

## enum 값 집합 (schema.py 단일 진실)

잘못된 값은 적재 거부된다. 추측하지 말고 이 목록에서 고른다.

- **EvidenceManifest.source_type**: `session` `slack` `jira` `pr` `commit` `spec` `build_log`
  `code_search` `wiki` `context`
  - `sanity`/`hotfix`는 `source_type` 값이 아니다. Jira/Slack/PR/commit EvidenceManifest를 만들고,
    의미는 `DecisionRecord.decision_type=sanity_change|hotfix_change`로 표현한다.
- **EvidenceRef.ref_type**: `slack_message` `slack_thread` `jira_comment` `spec_slide` `spec_section`
  `code_locator` `build_log_range` `session_turn` `wiki_section` `context_term`
  `commit` `pr` `jira_issue`
- **Insight.insight_type**: `cross-cutting-risk` `operational-lesson` — 선택 필드지만 A형(`cross-cutting-risk`)의 `source_object_ids` ≥2 승격 게이트가 이 값을 본다
- **CodeLocator.locator_source**: `codanna` `rg` `clangd` `manual`
- **TemporalFact.confidence**: `high` `medium` `low` `unknown`
  (서버 위키처럼 최신 보장 안 되는 소스 → `medium`/`low`)
- **DecisionRecord.decision_type**: `spec_clarification` `spec_revision` `improvement` `qa_issue`
  `sanity_change` `hotfix_change` `naming_decision` `implementation_boundary`
- **DecisionRecord.spec_reflected**: `yes` `no` `unknown` `not_applicable`
- **ReviewRecord.review_type**: `meaning_review` `evidence_review` `implementation_review`
  `projection_review` `supersession_review`
- **ReviewRecord.review_scope**: `single_object` | `mapping_bundle`
- **DomainMapping.review_state** 키: `meaning_reviewed` `evidence_reviewed` `implementation_reviewed`
  `projection_reviewed` (각 값은 boolean. 덮지 않은 차원은 키 자체를 생략 — false로 박지 마라)
- **DomainContext.injection_profile.default_audience**: `coding-agent` `planner` `reviewer` `search-router`
- **GlossaryTerm candidate.candidate_state**: `observed` `evidence_verified` `needs_user_confirmation`
  `conflict` `ready_for_review`
- **GlossaryTerm candidate.candidate_source**: `spec` `code` `session` `slack` `jira` `legacy_context`
  `legacy_wiki` `manual`

### DomainMapping caveats — history_coverage 고정 literal

`current_ingest_done`과 변경 이력 확인 범위를 구분하려고 `DomainMapping.caveats`에는 아래 literal 중 정확히
하나를 넣는다. 자유 문장으로 바꾸지 마라.

- `history_coverage=unsearched`: 현재 {{DEFAULT_BRANCH}} 코드 + 현행 기획서 + 서버위키만 확인했다.
- `history_coverage=partial`: 변경 이력 소스 일부만 확인했다.
- `history_coverage=complete`: Jira/Slack/PR/commit 변경 이력까지 확인·연결했다.

`status="reviewed"`는 현재 meaning/value/boundary의 검수 상태다. `history_coverage=complete`가 없으면
why/as-of 질의를 답하면 안 된다.

schema는 reviewed `DomainMapping`·`GlossaryTerm`의 `evidence_refs` non-empty를 강제한다(§6.4, 2026-06-06 — 근거 빈
reviewed는 거부). 단 `code_locator_ids` non-empty는 강제하지 않는다 — 코드앵커는 근거의 한 종류일 뿐이고 서버규칙은
코드앵커가 본질적으로 없을 수 있어서다. lint는 `code_locator_ids`가 있을 때 없는 id를 가리키는지(dangling)만 검사한다.

### GlossaryTerm candidate 규칙

- `status="candidate"`이면 `candidate` 메타데이터(최소 `candidate_state`+`candidate_source`)가 있어야 한다.
- `status="reviewed"`로 승격하려면 `candidate_state`가 `conflict`이면 안 되고, `open_questions`가 남으면
  안 된다. `promote`가 `candidate` 키를 통째로 제거한다(개별 필드만 빼면 schema가 거부).
- `status="rejected"`이면 `rejection` 메타데이터가 있어야 한다.

## 연결 필드 (고아 방지)

`ingest`의 두 번째 게이트(`lint_store`)가 **없는 id를 가리키는 링크**를 전부 잡아 거부한다. 묶음을 짤 때
가리키는 객체가 같은 묶음 안이나 이미 store에 있어야 한다.

- 모든 객체: `evidence_refs[]`(EvidenceRef id), `review_record_id`(있으면 존재해야).
- DomainMapping: `context_id`, `glossary_term_ids[]`, `decision_record_ids[]`, `spec_revision_ids[]`,
  `code_locator_ids[]`, `supersedes_mapping_ids[]` — 전부 존재해야.
- DecisionRecord: `source_object_ids[]`, `affected_context_ids[]`, `affected_mapping_ids[]`,
  `affected_glossary_term_ids[]`, `spec_revision_ids[]`, `jira_issue_ids[]`, `slack_thread_ids[]`,
  `code_locator_ids[]` — 전부 존재해야.
- ReviewRecord: `target_object_id`(단수) 또는 `target_object_ids[]`(복수) — 존재해야.
- CurrentView: `source_fact_ids[]` — 존재해야.

EvidenceRef는 `evidence_manifest_id`로 그 소스의 EvidenceManifest를 가리킨다. 즉 소스 하나당
Manifest 1개, 그 소스에서 인용한 조각마다 EvidenceRef를 만들어 Manifest를 가리키게 한다.

## CodeLocator — 코드 앵커

- `repo`, `path`(레포 루트 기준), `symbol`(클래스/메서드명),
  `locator_source`(`rg`/`codanna`/`clangd`/`manual`), `verified_at`.
- 앵커는 **{{DEFAULT_BRANCH}} 기준**으로 고정한다. 작업 브랜치는 stale일 수 있으니 `git show`로 확정한다.
- 앵커는 path+symbol이 본질 — 줄번호는 쓰지 않는다(엔진이 저장·회상 안 함). 위치 변화는 commit_sha 기준 stale-check가 잡는다.

## 실물 JSON 예시

### DomainMapping (candidate)

```json
{
  "id": "mapping.join-availability",
  "kind": "DomainMapping",
  "status": "candidate",
  "truth_role": "domain",
  "title": "Candidate mapping: join-availability-repeat",
  "context_id": "context.sally-canoe",
  "mapping_key": "join-availability-repeat",
  "canonical_summary": "참여 가능 조건과 반복 참여",
  "meaning": "레이스 완주 후 정해진 참여 가능 조건을 만족해야 새 레이스를 시작할 수 있다. 반복 참여 가능하나 MAX 제한.",
  "boundary": "레이스 시작 가능 시점에 한함. 실제 조건명과 값은 기획서·서버위키 근거로만 채운다.",
  "caveats": ["history_coverage=unsearched"],
  "glossary_term_ids": ["g.join-availability", "g.repeat-join"],
  "decision_record_ids": ["decision.join-availability"],
  "code_locator_ids": ["code.join-availability-manager"],
  "evidence_refs": ["ev.ref.spec.join-availability"],
  "schema_version": "0.1",
  "poc_priority": "P0",
  "created_at": "2026-06-04T00:00:00+09:00",
  "updated_at": "2026-06-04T00:00:00+09:00",
  "tags": ["sally-canoe"]
}
```

### CodeLocator

```json
{
  "id": "code.join-availability-manager",
  "kind": "CodeLocator",
  "status": "reviewed",
  "truth_role": "reference",
  "title": "참여 가능 조건/레이스 종료/실패 판정 헬퍼(선착순 ≤3)",
  "repo": "{{REPO}}",
  "path": "LineBubble2/Classes/main/Event/SallyCanoe/model/SallyCanoeEventManager.hpp",
  "symbol": "참여 가능 조건 판정 헬퍼 / isRaceEnd / isRaceFailure",
  "locator_source": "rg",
  "verified_at": "2026-06-04T00:00:00+09:00",
  "schema_version": "0.1",
  "poc_priority": "P0",
  "created_at": "2026-06-04T00:00:00+09:00",
  "updated_at": "2026-06-04T00:00:00+09:00",
  "tags": ["sally-canoe"],
  "evidence_refs": []
}
```

### DecisionRecord

```json
{
  "id": "decision.join-availability",
  "kind": "DecisionRecord",
  "status": "reviewed",
  "truth_role": "event",
  "title": "완주 후 참여 가능 조건을 만족해야 새 레이스",
  "decision_type": "spec_clarification",
  "summary": "완주 후 참여 가능 조건을 만족해야 새 레이스",
  "decision": "레이스 완주 후 정해진 참여 가능 조건을 만족해야 새 레이스를 시작할 수 있고, 반복 참여 MAX 제한이 있다.",
  "source_object_ids": ["ev.ref.spec.join-availability"],
  "affected_context_ids": ["context.sally-canoe"],
  "spec_reflected": "yes",
  "affected_mapping_ids": ["mapping.join-availability"],
  "schema_version": "0.1",
  "poc_priority": "P0",
  "created_at": "2026-06-04T00:00:00+09:00",
  "updated_at": "2026-06-04T00:00:00+09:00",
  "tags": ["sally-canoe"],
  "evidence_refs": []
}
```

### decisions[] 노트 섹션 (엔진 build_decisions가 조립 — 손조립 금지)

DecisionRecord는 손으로 `extra_objects`에 만들지 않는다. 노트의 `decisions[]` 섹션에 데이터만 쓰면
엔진 `build_decisions`가 DecisionRecord + EvidenceRef로 조립하고 매핑 양방향(lint 8c)을 자동으로 채운다.

각 결정 항목:
- `key`(kebab), `decision_type`(spec_clarification/spec_revision/improvement/qa_issue/sanity_change/hotfix_change/naming_decision/implementation_boundary), `title`, `summary`, `decision`.
- `spec_reflected`(yes/no/unknown/not_applicable, 생략 시 not_applicable).
- `affects`: 이 결정이 거는 매핑 key 목록(실존해야 함 — build 무결성 검사).
- `evidence`: `[{type: commit|jira|pr, ref, summary?, locator?}]`. commit locator는 엔진이 `{repo,sha}` 자동, jira/pr은 `locator`(인스턴스 URL)를 노트가 제공.

엔진이 자동 채움: id(`decision.<ctx>.<key>`)·status(reviewed)·truth_role(event)·source_object_ids·evidence_refs·affected_context_ids·affected_mapping_ids·단일 now.

### DomainContext

```json
{
  "id": "context.sally-canoe",
  "kind": "DomainContext",
  "status": "reviewed",
  "truth_role": "domain",
  "title": "샐리 카누 도메인",
  "context_key": "sally-canoe",
  "project_id": "{{REPO}}",
  "display_name": "샐리 카누 레이스",
  "boundary_summary": "카누 레이스 lifecycle/state — 레이스 단계·상태, 더미 NPC, 선착순, 참여 가능 조건, 반복 참여.",
  "in_scope": ["레이스 상태", "단계 진행", "더미 NPC", "선착순", "참여 가능 조건", "반복 참여"],
  "out_of_scope": ["UI 컴포넌트", "팝업 세부", "보상 아이템 상세"],
  "injection_profile": { "default_audience": "coding-agent" },
  "glossary_term_ids": ["g.race-status", "g.view-state", "g.dummy-npc", "g.finish-rank", "g.join-availability", "g.repeat-join"],
  "schema_version": "0.1",
  "poc_priority": "P0",
  "created_at": "2026-06-04T00:00:00+09:00",
  "updated_at": "2026-06-04T00:00:00+09:00",
  "tags": ["sally-canoe"],
  "evidence_refs": []
}
```
