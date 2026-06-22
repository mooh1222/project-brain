---
title: BB2 Brain Object Model Design
date: 2026-05-27
status: draft-for-review
scope: object-model
---

# BB2 Brain Object Model Design

## 1. 목적

BB2 Brain은 Karpathy LLM Wiki의 raw-first 철학을 따르되, 실제 운영 truth는 단순 wiki 문서가 아니라 `EvidenceManifest`, reviewed event ledger, `TemporalFact / VersionedFact`, current view로 분리한다.

이 문서는 v0.1 PoC에 필요한 object model을 정의한다. 목표는 다음 질문에 근거와 함께 답하는 것이다.

| 질문 패턴 | 우선 객체 |
|---|---|
| 지금 스펙/구현/QA 상태가 뭐야? | `CurrentView`, `TemporalFact / VersionedFact` |
| 왜 바뀌었어? | `EventLedgerRecord`, `EvidenceRef` |
| 누가/어디서 확정했어? | `SlackThread`, `JiraIssue`, `PRRef`, `SpecRevision`, `EvidenceManifest` |
| 어디에 구현돼 있어? | `CodeLocator`, `CommitRef`, `PRRef` |
| 그때는 뭐였어? | `TemporalFact / VersionedFact` as-of query, `supersedes` chain |

## 2. 설계 원칙

1. **Evidence is source of truth**: raw 원본이나 citation bundle이 없으면 사실로 주장하지 않는다.
2. **Ledger is operational truth**: 검수된 사건과 버전 fact가 운영상 truth다.
3. **Wiki is synthesis**: `KnowledgePage`는 사람이 읽기 쉬운 합성물이며 단독 SoR이 아니다.
4. **Index is disposable**: `IndexRecord`와 SQLite/FTS/vector/trigram index는 재생성 가능해야 한다.
5. **No silent overwrite**: 스펙·QA·구현 상태가 바뀌면 기존 fact를 수정하지 않고 새 fact를 추가하고 이전 fact의 `valid_until`을 닫는다.
6. **Domain context is vocabulary**: Matt Pocock식 `CONTEXT.md`는 작업 지침이 아니라 용어 사전이다. Brain에는 `DomainContext` / `GlossaryTerm`으로 연결한다.

## 3. Scope

### 포함

- 19개 핵심 타입: `EvidenceManifest`, `EvidenceRef`, `ReviewRecord`, `EventLedgerRecord`, `TemporalFact`, `KnowledgePage`, `CurrentView`, `SpecDocument`, `SpecRevision`, `SlideRef`, `JiraIssue`, `SlackThread`, `PRRef`, `CommitRef`, `CodeLocator`, `BuildContext`, `ActorIdentity`, `SessionRun`, `IndexRecord`
- 보조 타입 2개: `DomainContext`, `GlossaryTerm`
- 타입별 책임, 필드, 관계, 불변조건
- stage clear token / entrance popup cluster 변경 케이스를 acceptance test로 사용

### 제외

- 저장소 레이아웃 상세
- query router 알고리즘 상세
- ingest/review UI
- vector/rerank 기본 채택
- Slack/Jira full connector 구현
- 자동 dream cycle

## 4. 핵심 용어

| 용어 | 의미 |
|---|---|
| Raw evidence | Slack 원문, Jira 원문, 기획서 원본, 빌드 로그, session transcript처럼 수정하지 않는 원본 |
| Citation bundle | 공유 가능한 범위로 redaction/ACL 검토를 마친 근거 묶음 |
| Candidate | AI가 만든 미검수 event/fact/wiki 초안 |
| Reviewed | 사람이 승인했거나 지정된 검수 규칙을 통과한 상태 |
| `TemporalFact / VersionedFact` | 특정 scope/version/time window에서 유효한 fact. “임시 사실”이 아니라 “버전/유효기간이 있는 확정 사실” |
| Current view | 현재 시점에 유효한 reviewed fact를 모아 만든 요약 |
| Domain context | `CONTEXT.md` 형태의 용어 사전. 코드 작업 방식이 아니라 용어 의미를 맞추는 계약 |

## 5. 공통 객체 계약

모든 Brain object는 공통 base를 가진다.

```ts
type ObjectId = string;
type ISODateTime = string;

type ObjectStatus =
  | "candidate"
  | "reviewed"
  | "superseded"
  | "archived"
  | "rejected";

type PocPriority = "P0" | "P1" | "P2";

type TruthRole =
  | "source"
  | "reference"
  | "review"
  | "event"
  | "fact"
  | "synthesis"
  | "domain"
  | "index";

interface BrainObjectBase {
  id: ObjectId;
  kind: string;
  schema_version: "0.1";
  status: ObjectStatus;
  poc_priority: PocPriority;
  truth_role: TruthRole;
  title: string;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  evidence_refs: ObjectId[];
  review_record_id?: ObjectId;
  tags: string[];
}
```

## 6. Core evidence / review / ledger objects

### 6.1 EvidenceManifest

**쉬운 설명**: 원본 보관증. 원본이 어디 있고, 공유해도 되는지, 변조되지 않았는지 기록한다.

```ts
interface EvidenceManifest extends BrainObjectBase {
  kind: "EvidenceManifest";
  truth_role: "source";
  poc_priority: "P0";
  source_type:
    | "session"
    | "slack"
    | "jira"
    | "pr"
    | "commit"
    | "spec"
    | "build_log"
    | "code_search"
    | "wiki"
    | "context";
  locator: string;
  content_hash?: string;
  source_version?: string;
  captured_at: ISODateTime;
  captured_by: string;
  sensitivity: "public" | "internal" | "restricted" | "secret";
  acl: string[];
  redaction_status: "raw_local" | "staged" | "approved" | "rejected";
  approved_bundle_path?: string;
}
```

불변조건:

- raw 원본은 수정하지 않는다.
- shared brain에는 `redaction_status = "approved"`인 citation bundle만 들어갈 수 있다.
- `content_hash`가 바뀌면 기존 manifest를 덮어쓰지 않고 새 manifest를 만든다.

### 6.2 EvidenceRef

**쉬운 설명**: 정확한 책갈피. 원본 중 어느 부분을 근거로 쓰는지 가리킨다.

```ts
interface EvidenceRef extends BrainObjectBase {
  kind: "EvidenceRef";
  truth_role: "reference";
  poc_priority: "P0";
  evidence_manifest_id: ObjectId;
  ref_type:
    | "slack_message"
    | "slack_thread"
    | "jira_comment"
    | "spec_slide"
    | "spec_section"
    | "code_locator"
    | "build_log_range"
    | "session_turn"
    | "wiki_section"
    | "context_term";
  locator: {
    path?: string;
    url?: string;
    channel_id?: string;
    thread_ts?: string;
    message_ts?: string;
    issue_key?: string;
    slide_no?: number;
    heading?: string;
    line_start?: number;
    line_end?: number;
    code_locator_id?: ObjectId;
  };
  quote?: string;
  summary: string;
}
```

불변조건:

- `EvidenceRef`는 원본 내용을 복사해 truth로 만들지 않는다. 항상 `EvidenceManifest`로 돌아갈 수 있어야 한다.
- `quote`는 짧은 인용만 허용한다. 민감한 원문 전체를 저장하지 않는다.

### 6.3 ReviewRecord

**쉬운 설명**: 검수 도장. candidate를 현재 지식으로 써도 되는지 승인한 기록이다.

```ts
interface ReviewRecord extends BrainObjectBase {
  kind: "ReviewRecord";
  truth_role: "review";
  poc_priority: "P0";
  target_object_id: ObjectId;
  reviewer: string;
  reviewed_at: ISODateTime;
  verdict: "approved" | "rejected" | "needs_changes";
  notes?: string;
  evidence_refs: ObjectId[];
}
```

불변조건:

- `CurrentView`에는 approved `ReviewRecord` 없는 fact를 넣지 않는다.
- 사람이 승인하지 않은 내용은 답변 시 `candidate` 또는 `raw-only`로 표시한다.

### 6.4 EventLedgerRecord

**쉬운 설명**: 사건 일지. 누가 언제 무엇을 확정/변경/구현/QA했는지 append-only로 남긴다.

```ts
interface EventLedgerRecord extends BrainObjectBase {
  kind: "EventLedgerRecord";
  truth_role: "event";
  poc_priority: "P0";
  event_type:
    | "spec_created"
    | "spec_revised"
    | "spec_clarified"
    | "decision_made"
    | "implementation_started"
    | "implementation_completed"
    | "qa_started"
    | "qa_result"
    | "bug_reported"
    | "debug_case"
    | "build_result"
    | "review_comment"
    | "domain_term_added";
  happened_at: ISODateTime;
  actor_id?: ObjectId;
  summary: string;
  body?: string;
  related_objects: ObjectId[];
  evidence_refs: ObjectId[];
}
```

불변조건:

- event는 삭제/수정하지 않는다. 정정도 새 event로 남긴다.
- event 하나가 반드시 fact를 만들 필요는 없다. 단순 기록 event도 가능하다.

### 6.5 TemporalFact / VersionedFact

**쉬운 설명**: 버전/유효기간 있는 현재 규칙. 기획서·Slack·QA·PR로 확정된 사실을 특정 scope에서 유효한 fact로 저장한다.

```ts
interface TemporalFact extends BrainObjectBase {
  kind: "TemporalFact";
  truth_role: "fact";
  poc_priority: "P0";
  subject: string;
  predicate: string;
  value: unknown;
  scope: {
    project?: "bb2-client";
    release?: string;
    feature?: string;
    surface?: string;
    platform?: "ios" | "android" | "common";
    module?: string;
  };
  valid_from: ISODateTime;
  valid_until?: ISODateTime;
  supersedes?: ObjectId;
  derived_from_event_id: ObjectId;
  confidence: "high" | "medium" | "low" | "unknown";
}
```

해석 예:

```ts
{
  subject: "stage-clear-token.PopupEnter.eventCluster.effectBlinkRule",
  predicate: "uses",
  value: "blink_only_next_stage_effect_icon",
  scope: {
    project: "bb2-client",
    release: "5.5",
    feature: "stage-clear-token",
    surface: "PopupEnter"
  },
  valid_from: "2026-05-26T...",
  valid_until: undefined
}
```

불변조건:

- 같은 `subject + predicate + overlapping scope`에 새 fact가 생기면 기존 current fact의 `valid_until`을 닫는다.
- `valid_from`은 Brain 저장 시각이나 검수 시각이 아니라 도메인에서 해당 fact가 유효해진 시각이다. 저장/검수 시각은 `created_at`, `updated_at`, `ReviewRecord.reviewed_at`, `derived_from_event_id.happened_at`으로 구분한다.
- `overlapping scope`는 같은 feature/release/platform/module에 동시에 적용되는 범위다. 더 좁은 scope의 예외 fact가 항상 넓은 scope fact를 supersede하지는 않으며, 의도적으로 대체할 때만 `supersedes`를 연결한다.
- `valid_until`이 없는 reviewed fact만 current 후보가 된다.
- “기획서 내용”도 Brain 안에서는 versioned fact가 될 수 있다. 이유는 기획서 v1.3, Slack clarification, QA 중 변경, 다음 release 변경을 구분해야 하기 때문이다.

## 7. Synthesis objects

### 7.1 KnowledgePage

**쉬운 설명**: 사람이 읽는 지식 페이지. ledger/fact/evidence에서 합성되며 단독 truth가 아니다.

```ts
interface KnowledgePage extends BrainObjectBase {
  kind: "KnowledgePage";
  truth_role: "synthesis";
  poc_priority: "P0";
  category: "concept" | "module" | "workflow" | "spec" | "decision" | "incident" | "people" | "glossary";
  path: string;
  summary: string;
  source_object_ids: ObjectId[];
  stale_policy: "manual_review" | "rebuild_from_ledger";
}
```

### 7.2 CurrentView

**쉬운 설명**: 지금 기준 요약. 현재 유효한 reviewed fact를 모아 새 세션과 답변에 쓰는 작은 지도다.

```ts
interface CurrentView extends BrainObjectBase {
  kind: "CurrentView";
  truth_role: "synthesis";
  poc_priority: "P0";
  view_type:
    | "project_map"
    | "active_decisions"
    | "hot_issues"
    | "recent_reviewed_memory"
    | "feature_status"
    | "qa_status";
  as_of: ISODateTime;
  source_fact_ids: ObjectId[];
  source_event_ids: ObjectId[];
  summary: string;
}
```

불변조건:

- `CurrentView`는 손으로 만든 독립 truth가 아니다.
- `source_fact_ids`가 stale이면 view를 재생성해야 한다.

## 8. Spec objects

### 8.1 SpecDocument

**쉬운 설명**: 기획서라는 문서 단위. PPT, Confluence, dump markdown 등을 연결한다.

```ts
interface SpecDocument extends BrainObjectBase {
  kind: "SpecDocument";
  truth_role: "source";
  poc_priority: "P0";
  title: string;
  owner?: ObjectId;
  source_system: "ppt" | "confluence" | "markdown_dump" | "unknown";
  canonical_locator: string;
  current_revision_id?: ObjectId;
}
```

### 8.2 SpecRevision

**쉬운 설명**: 기획서 버전. v1.3, v8 같은 revision별 변경을 기록한다.

```ts
interface SpecRevision extends BrainObjectBase {
  kind: "SpecRevision";
  truth_role: "source";
  poc_priority: "P0";
  spec_document_id: ObjectId;
  revision_label: string;
  captured_at: ISODateTime;
  change_summary?: string;
  previous_revision_id?: ObjectId;
  slide_refs: ObjectId[];
}
```

### 8.3 SlideRef

**쉬운 설명**: 슬라이드 단위 책갈피. “Slide 10의 요정의 선물 규칙”처럼 정확히 가리킨다.

```ts
interface SlideRef extends BrainObjectBase {
  kind: "SlideRef";
  truth_role: "reference";
  poc_priority: "P0";
  spec_revision_id: ObjectId;
  slide_no: number;
  title?: string;
  section?: string;
  extracted_text_ref?: ObjectId;
  thumbnail_ref?: ObjectId;
}
```

## 9. Work tracking / communication objects

### 9.1 JiraIssue

```ts
interface JiraIssue extends BrainObjectBase {
  kind: "JiraIssue";
  truth_role: "source";
  poc_priority: "P1";
  issue_key: string;
  summary: string;
  issue_status: string;
  assignee_id?: ObjectId;
  url: string;
  related_events: ObjectId[];
  related_facts: ObjectId[];
}
```

### 9.2 SlackThread

```ts
interface SlackThread extends BrainObjectBase {
  kind: "SlackThread";
  truth_role: "source";
  poc_priority: "P0";
  workspace_id?: string;
  channel_id: string;
  thread_ts: string;
  url?: string;
  participants: ObjectId[];
  message_refs: ObjectId[];
  summary: string;
}
```

### 9.3 PRRef

```ts
interface PRRef extends BrainObjectBase {
  kind: "PRRef";
  truth_role: "source";
  poc_priority: "P1";
  repo: string;
  number: number;
  title: string;
  url: string;
  pr_status: "open" | "merged" | "closed";
  commit_refs: ObjectId[];
}
```

### 9.4 CommitRef

```ts
interface CommitRef extends BrainObjectBase {
  kind: "CommitRef";
  truth_role: "source";
  poc_priority: "P1";
  repo: string;
  sha: string;
  branch?: string;
  message: string;
  authored_at?: ISODateTime;
  pr_ref_id?: ObjectId;
}
```

## 10. Code / build / actor / session objects

### 10.1 CodeLocator

**쉬운 설명**: 코드 위치 포인터. 코드를 대량 ingest하지 않고 위치와 조사 결과만 저장한다.

```ts
interface CodeLocator extends BrainObjectBase {
  kind: "CodeLocator";
  truth_role: "reference";
  poc_priority: "P0";
  repo: string;
  branch?: string;
  commit_sha?: string;
  worktree?: string;
  path: string;
  symbol?: string;
  line_start?: number;
  line_end?: number;
  locator_source: "codanna" | "rg" | "clangd" | "manual";
  verified_at: ISODateTime;
}
```

불변조건:

- code locator는 코드 truth가 아니라 “조사 당시의 위치”다.
- `commit_sha`가 없으면 line number drift 가능성을 표시해야 한다.

### 10.2 BuildContext

```ts
interface BuildContext extends BrainObjectBase {
  kind: "BuildContext";
  truth_role: "event";
  poc_priority: "P0";
  platform: "ios" | "android";
  scheme?: string;
  flavor?: string;
  command: string;
  log_evidence_ref_id?: ObjectId;
  result: "success" | "failed" | "blocked" | "unknown";
  relevant_errors?: string[];
}
```

### 10.3 ActorIdentity

```ts
interface ActorIdentity extends BrainObjectBase {
  kind: "ActorIdentity";
  truth_role: "source";
  poc_priority: "P1";
  display_name: string;
  aliases: {
    system: "slack" | "jira" | "github" | "git" | "confluence" | "local";
    id: string;
    confidence: "confirmed" | "probable" | "unknown";
  }[];
}
```

### 10.4 SessionRun

```ts
interface SessionRun extends BrainObjectBase {
  kind: "SessionRun";
  truth_role: "event";
  poc_priority: "P0";
  session_id: string;
  cwd: string;
  branch?: string;
  started_at: ISODateTime;
  ended_at?: ISODateTime;
  summary?: string;
  related_events: ObjectId[];
  related_facts: ObjectId[];
}
```

## 11. Domain context objects

### 11.1 DomainContext

**쉬운 설명**: Brain 안의 도메인 용어 네임스페이스와 경계다. `CONTEXT.md` 파일 경로가 아니라 reviewed `GlossaryTerm` 묶음의 소유자다.

```ts
interface DomainContext extends BrainObjectBase {
  kind: "DomainContext";
  truth_role: "domain";
  poc_priority: "P0";

  context_key: string;
  project_id: string;
  display_name: string;

  parent_context_id?: ObjectId;
  child_context_ids?: ObjectId[];

  boundary_summary: string;
  in_scope: string[];
  out_of_scope: string[];

  injection_profile: {
    default_audience: "coding-agent" | "planner" | "reviewer" | "search-router";
    max_terms?: number;
    include_candidates?: boolean;
  };

  export_targets?: {
    format: "context_md" | "prompt_payload";
    locator?: string;
  }[];

  glossary_term_ids: ObjectId[];
}
```

### 11.2 GlossaryTerm

**쉬운 설명**: Brain-native ubiquitous language의 한 단어다. 후보도 같은 객체를 쓰되, reviewed로 승격되기 전에는 agent-facing context export에 들어가지 않는다.

```ts
interface GlossaryTerm extends BrainObjectBase {
  kind: "GlossaryTerm";
  truth_role: "domain";
  poc_priority: "P0";

  context_id: ObjectId;
  term: string;
  definition: string;

  avoid?: string[];
  synonyms?: string[];
  scope_hint?: { feature?: string; surface?: string; release?: string };

  related_terms?: ObjectId[];
  related_objects?: ObjectId[];

  candidate?: {
    candidate_state:
      | "observed"
      | "evidence_verified"
      | "needs_user_confirmation"
      | "conflict"
      | "ready_for_review";
    candidate_source:
      | "spec"
      | "code"
      | "session"
      | "slack"
      | "jira"
      | "legacy_context"
      | "legacy_wiki"
      | "manual";
    open_questions?: string[];
    conflicts_with?: ObjectId[];
    promotion_criteria?: string[];
  };

  rejection?: {
    rejection_reason: string;
    canonical_replacement_id?: ObjectId;
  };
}
```

### 11.3 ContextProjection

**쉬운 설명**: Brain vocabulary에서 만든 disposable export metadata다. generated `CONTEXT.md`나 prompt payload를 추적하지만, evidence나 source of truth가 아니다.

```ts
interface ContextProjection extends BrainObjectBase {
  kind: "ContextProjection";
  truth_role: "index";
  poc_priority: "P0";

  context_id: ObjectId;
  format: "context_md" | "prompt_payload";
  output_locator?: string;

  source_object_ids: ObjectId[];
  source_content_hash: string;
  projection_hash: string;
  generated_at: ISODateTime;
  generated_by: string;

  stale_policy: "fail_on_manual_edit";
  manual_edit_detected?: boolean;
}
```

불변조건:

- `DomainContext`는 `path` / `source_format`을 canonical field로 사용하지 않는다.
- `GlossaryTerm(status="candidate")`는 `candidate` metadata를 가져야 한다.
- `GlossaryTerm(status="reviewed")`는 unresolved `open_questions` 또는 `candidate_state="conflict"`를 가질 수 없다.
- Reviewed term은 agent-facing context export에 들어갈 수 있다.
- Candidate term은 review queue, diagnostics, explicit candidate view에만 들어간다.
- `ContextProjection`은 삭제 후 재생성 가능해야 하며 evidence로 인용하지 않는다.
- generated `CONTEXT.md` 수동 편집은 P0에서 lint 실패다.
- `scope_hint`의 feature/surface/release 값은 동일 차원의 `TemporalFact.scope` 값과 같은 ASCII canonical 식별자여야 한다.

## 12. Index object

### 12.1 IndexRecord

**쉬운 설명**: 검색용 포인터. 빠르게 찾기 위한 캐시이며 truth가 아니다.

```ts
interface IndexRecord extends BrainObjectBase {
  kind: "IndexRecord";
  truth_role: "index";
  poc_priority: "P0";
  index_name: "fts" | "timeline" | "entity" | "code_locator" | "trigram" | "vector";
  source_object_id: ObjectId;
  indexed_at: ISODateTime;
  content_hash: string;
  query_terms?: string[];
}
```

불변조건:

- index는 언제든 삭제 후 재생성 가능해야 한다.
- 답변은 index hit가 아니라 source object의 evidence/ledger/fact를 근거로 해야 한다.

## 13. 관계 요약

```text
EvidenceManifest 1 ── N EvidenceRef
EvidenceRef       N ── N EventLedgerRecord
EventLedgerRecord 1 ── N TemporalFact / VersionedFact
TemporalFact      N ── N CurrentView

SpecDocument 1 ── N SpecRevision 1 ── N SlideRef
SlackThread  1 ── N EvidenceRef
JiraIssue    N ── N EventLedgerRecord
PRRef        1 ── N CommitRef
CodeLocator  N ── N EventLedgerRecord
BuildContext N ── N EventLedgerRecord

DomainContext 1 ── N GlossaryTerm
GlossaryTerm  N ── N KnowledgePage / SpecRevision / CodeLocator

IndexRecord ──> source_object_id
```

## 14. Acceptance test: stage clear token entrance popup cluster

용어 사전 기준: Brain reviewed `DomainContext(context_key="stage-clear-token")` + reviewed `GlossaryTerm` objects. Existing `docs/contexts/stage-clear-token/CONTEXT.md` is legacy migration hint only and cannot be sole evidence for reviewed terms.

샘플 질문:

> 입장팝업의 요정의선물/해피블록 표시가 왜 drawEventCluster 형태로 바뀌었고, 현재 QA 기준 동작은 뭐야?

Brain은 다음 순서로 답해야 한다.

1. Brain `DomainContext`에서 도메인 경계를 확인하고, reviewed `GlossaryTerm`에서 “입장팝업”, “이벤트 클러스터”, “해피블록”, “요정의 선물” 용어를 확인한다. Candidate terms are visible only in review/diagnostic surfaces.
2. `SpecDocument` / `SpecRevision` / `SlideRef`에서 5.5 stage clear token 기획서 Slide 8~11 근거를 찾는다.
3. `SlackThread`에서 clarification 근거를 찾는다.
   - 해피블록은 공간 이슈로 블럭 모양 대신 버프 정보 표시
   - 다음 단계 효과만 깜박임
   - 플라워 포인트 표시 UI 삭제
   - 보스 모드는 다음 단계 표시 + 깜박임
4. 각 clarification을 `EventLedgerRecord`로 보여준다.
5. 현재 유효한 UI 규칙은 `TemporalFact / VersionedFact`로 보여준다.
6. 구현 위치는 `CodeLocator`로 연결한다.
7. 현재 작업 상태는 `CurrentView`에서 “구현 완료, QA 중”처럼 보여준다.
8. 답변 끝에는 reviewed/candidate/raw-only 상태와 evidence link를 붙인다.

성공 기준:

- 기획서 원문과 Slack clarification을 섞어 말하되, 어느 쪽이 근거인지 분리한다.
- “현재 규칙”과 “변경 이유”를 구분한다.
- 코드 전체를 brain에 저장하지 않고 locator로만 연결한다.
- 나중에 5.6에서 규칙이 바뀌면 기존 5.5 fact를 삭제하지 않고 as-of로 조회할 수 있다.

## 15. PoC 우선순위

| Priority | Objects |
|---|---|
| P0 | `EvidenceManifest`, `EvidenceRef`, `ReviewRecord`, `EventLedgerRecord`, `TemporalFact`, `KnowledgePage`, `CurrentView`, `SpecDocument`, `SpecRevision`, `SlideRef`, `SlackThread`, `CodeLocator`, `BuildContext`, `SessionRun`, `IndexRecord`, `DomainContext`, `GlossaryTerm` |
| P1 | `JiraIssue`, `PRRef`, `CommitRef`, `ActorIdentity` |
| P2 | 자동 identity matching, vector index, rerank metadata, full connector metadata |

## 16. Open decisions for later specs

| Decision | Why deferred |
|---|---|
| Storage file layout | `docs/superpowers/specs/2026-05-28-bb2-brain-storage-layout-design.md`에서 결정 |
| Query routing weights | 별도 Query Routing Spec에서 결정 |
| Review UI / approval UX | PoC 운영 방식 확인 후 결정 |
| Slack/Jira ACL redaction policy | P0 privacy/redaction research 필요 |
| CJK + code mixed retrieval baseline | P0 retrieval research 필요 |
| PPT slide diff extraction detail | P1 spec extraction research 필요 |
