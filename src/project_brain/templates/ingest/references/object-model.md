# 객체 모델 — 조립 계약

조립 노트와 build 결과는 이 문서의 필드·enum·연결 계약을 따른다.
엔진 `src/project_brain/schema.py`가 최종 검증자이며, 이 문서는 적재자가 놓치기 쉬운 계약을 간결하게 정리한다.

## 목차

- 공통 필드와 enum
- 주요 kind별 필수 필드
- 연결과 reviewed 근거
- EvidenceManifest redaction
- TemporalFact 시간·연결 계약
- DecisionRecord
- Insight 적재 규칙
- 논리 key와 완성 ID
- synonyms와 aliases 게이트

## 공통 필드와 enum

모든 객체에는 다음 필드가 필요하다.

```text
id, kind, schema_version, status, poc_priority, truth_role,
title, created_at, updated_at, tags, evidence_refs
```

- `status`: `candidate`, `reviewed`, `superseded`, `archived`, `rejected`
- `poc_priority`: `P0`, `P1`, `P2`
- `truth_role`: kind에 맞는 고정 역할을 쓴다. 임의의 역할을 붙이지 않는다.
- `evidence_refs`: 근거 참조 배열이다. reviewed `DomainMapping`과 `GlossaryTerm`은 비어 있으면 안 된다.

필수 필드의 누락, enum 밖 값, kind와 다른 `truth_role`은 ingest가 거부한다.
완성 객체를 손으로 조립할 때도 build와 같은 계약을 지켜야 한다.

## 주요 kind별 필수 필드

| kind | 공통 필드 외 필수 필드 |
|---|---|
| EvidenceManifest | `source_type`, `locator`, `captured_at`, `captured_by`, `sensitivity`, `acl`, `redaction_status` |
| EvidenceRef | `evidence_manifest_id`, `ref_type`, `locator`, `summary` |
| CodeLocator | `repo`, `path`, `locator_source`, `verified_at` |
| DomainContext | `context_key`, `project_id`, `display_name`, `boundary_summary`, `in_scope`, `out_of_scope`, `injection_profile`, `glossary_term_ids` |
| GlossaryTerm | `context_id`, `term`, `definition` |
| DomainMapping | `context_id`, `mapping_key`, `canonical_summary`, `meaning`, `boundary`, `glossary_term_ids`, `decision_record_ids` |
| TemporalFact | `subject`, `predicate`, `value`, `scope`, `valid_from`, `derived_from_event_id`, `confidence` |
| EventLedgerRecord | `event_type`, `happened_at`, `summary`, `related_objects` |
| ReviewRecord | `reviewer`, `reviewed_at`, `verdict` |
| DecisionRecord | `decision_type`, `summary`, `decision`, `source_object_ids`, `affected_context_ids`, `spec_reflected` |
| Insight | `body`, `source_object_ids` |

`source_type`은 `session`, `slack`, `jira`, `pr`, `commit`, `spec`, `build_log`, `code_search`, `wiki`, `context` 중 하나다.
`ref_type`, `locator_source`, `confidence`, `decision_type`, `spec_reflected`도 엔진 enum을 따른다.
확신이 낮은 사실에는 `confidence=low`를 쓰고, 이 값은 SKILL의 독립 적대 검증 대상이다.

## 연결과 reviewed 근거

`EvidenceRef.evidence_manifest_id`는 이번 source packet의 `EvidenceManifest`를 가리킨다.
`DomainMapping`은 context·용어·결정에 연결하고, 코드 근거가 있으면 CodeLocator와 EvidenceRef를 함께 남긴다.
`DomainContext.glossary_term_ids`와 mapping의 `glossary_term_ids`는 용어를 고아로 두지 않게 하는 연결이다.

연결을 늘릴 때는 의미상 primary 하나와 실제 공동 primary만 둔다.
약한 관련성을 이유로 모든 매핑에 같은 용어·앵커를 붙이지 않는다.

기존 객체를 갱신할 때는 `updates[]`의 `set` 또는 `union`을 쓰고, `expected_updated_at`으로 동시 변경을 확인한다.
새 후보가 아니라 기존 참조를 보강하는 일이라면 같은 ID를 재사용한다.

## EvidenceManifest redaction

`redaction_status`는 반드시 다음 중 하나다.

```text
raw_local, staged, approved, rejected
```

기본값을 추측하지 않는다. 특히 오래된 `none` 값은 허용되지 않는다.
답변에 원문 근거를 제한 없이 쓸 수 있는 상태는 `approved`뿐이며, 나머지는 접근 제한 표기를 유발할 수 있다.

## TemporalFact 시간·연결 계약

`scope`는 release·environment 같은 차원을 담는 객체다. `valid_from`은 현재 값이 시작된 시점이고,
`valid_until`이 없으면 open current fact다. 값 변경을 완료할 때 옛 fact는 reviewed를 유지하고
`valid_until`로 닫는다. `old status=superseded`는 기본 전환이 아니다.

새 fact의 `supersedes`는 옛 fact ID 하나를 담는 scalar이고, `derived_from_event_id`는 변경 사건인
EventLedgerRecord ID다. 현재 엔진의 대상 kind·존재·cycle 검증 빈틈과 실제 갱신 묶음은
`update-rules.md`를 따른다.

## DecisionRecord

`DecisionRecord`는 결정의 내용과 영향을 기록한다.
`source_object_ids`가 정본 근거 연결이며, `evidence_refs`가 빈 경우도 있을 수 있다.
`decision_type`은 `spec_clarification`, `spec_revision`, `improvement`, `qa_issue`, `sanity_change`,
`hotfix_change`, `naming_decision`, `implementation_boundary` 중 하나를 쓴다.
`spec_reflected`는 `yes`, `no`, `unknown`, `not_applicable` 중 하나고, `no`는 독립 적대 검증 대상이다.

DecisionRecord와 EventLedgerRecord는 역할이 다르며 모든 변경에 자동으로 만들지 않는다.

## Insight 적재 규칙

Insight는 단일 객체의 재진술이 아니라 여러 객체·구현·결정을 가로지르는 검증된 위험이나 교훈이다.

- candidate Insight는 엔진이 거부하므로 검증 뒤 `status=reviewed`로 직접 적재한다.
- `insight_type`은 `cross-cutting-risk` 또는 `operational-lesson`이다. 전자는 `source_object_ids`가 둘 이상, 후자는 최소 하나 필요하다.
- `scope`는 적용 범위이며, `code_locator_ids`는 선택 코드 앵커다.
- `source_object_ids`는 내용을 뒷받침하는 기존 객체이고 `evidence_refs`는 진술 출처다. 둘을 바꾸어 쓰지 않는다.
- 사용자 진술이 출처면 approved session EvidenceManifest와 session_turn EvidenceRef를 연결한다.
- source 또는 code locator dangling은 lint가 막는다. 먼저 근거 객체를 적재하지 못하면 backlog에 둔다.
- 저장 뒤 Insight는 일반 results가 아니라 `advisories` 회상 통로에 나온다.

## 논리 key

논리 key는 조립기가 Context와 kind를 붙여 완성 ID를 만들기 전의 짧은 이름이다.
다음 정규식만 허용한다.

```text
^[a-z0-9]+(?:-[a-z0-9]+)*$
```

소문자 영숫자와 단일 하이픈만 쓰며, 앞뒤 하이픈·빈 조각·점·밑줄은 허용하지 않는다.
다음 노트 위치가 이 형식을 쓴다.

- `context.key`, `glossary[].key`, `mappings[].key`, `decisions[].key`
- `glossary_keys[]`, `code_evref_keys[]`, `decision_keys[]`, `decisions[].affects[]`

## 코드 앵커 예외

`code_anchors[].key`와 이를 참조하는 `code_evref_keys[]`는 조립기가 같은 이름을 나눌 때 붙이는 `--N` 접미를 허용한다.

```text
^[a-z0-9]+(?:-[a-z0-9]+)*(?:--[0-9]+)?$
```

`--N`은 조립기가 붙인 순번일 뿐 사람이 임의의 완성 ID 형식을 흉내 내는 방법이 아니다.
기준 코드의 심볼과 {{DEFAULT_BRANCH}} 이력에서 도달 가능한 commit SHA는 별도 코드 앵커 정보로 남긴다.

## 완성 ID와의 차이

`mapping.<context>.<key>`나 `g.<context>.<key>`처럼 점으로 계층을 가진 값은 완성 ID다.
그 값은 `sources[].id`, `refs`, `updates[].id`처럼 이미 존재하는 객체를 가리키는 필드에만 쓴다.

완성 ID를 논리 key 자리에 넣으면 build가 다시 접두를 붙여 이중 ID를 만들 수 있다.
자동으로 접두를 떼어 고치지 않는다. 잘못된 Context의 ID를 정상 key로 바꿔 조용히 연결을 틀릴 수 있기 때문이다.

## synonyms와 aliases 게이트

`GlossaryTerm`의 `synonyms`와 `aliases`는 사용자가 실제로 쓰는 다른 표면형을 질의 게이트에 연결한다.
용어 본문에 없는 한국어·영문 등가어, 기획서 표현, 충분히 구체적인 식별자 변형만 넣는다.

다음은 넣지 않는다.

- 세 글자 미만 표면형
- 단독 일반명사
- definition 본문에 이미 들어 있어 색인되는 표현

대표 용어에는 사용자가 기능이나 도메인을 부르는 고유한 이름을 넣는다.
기존 용어에 표면형을 더할 때는 기존 값을 덮지 말고 union으로 합친다.
