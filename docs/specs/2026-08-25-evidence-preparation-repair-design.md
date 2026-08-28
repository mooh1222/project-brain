# 후보 검증·전용 증거 공개 준비 핵심 설계

- 작성일: 2026-08-25
- 상태: #33 후보 2 독립 검수 PASS — Critical 0 / Major 0, 검수 4/4·설계확정
- 대상: GitHub #33과 후속 #6·#7·#8·#9·#10
- 기준 코드 후보: `75e97fa98308b8bd7434070e05a99e69f2a5adef`
- 보존 입력: `codex/issue-33-evidence-design-admission`의 미커밋 spec
- 별도 설계: GitHub #38 [context_md object·artifact transaction](2026-08-25-context-md-artifact-transaction-design.md)

## 1. 범위

이 설계는 공개 명령이 caller 입력에서 brain 객체용 evidence를 준비하고, 현재 store·filesystem·Git과
실제로 로드한 engine·Adapter에 결속한 뒤 `MutationService` 하나가 적용하도록 만드는 공통 기반만
소유한다.

지원 범위는 다음과 같다.

- common candidate: EvidenceRef, EventLedgerRecord, TemporalFact, CodeLocator, DomainContext,
  DecisionRecord
- common projection: `prompt_payload` ContextProjection의 `projection build-reuse`
- dedicated local observation: EvidenceManifest, SpecDocument, SpecRevision, SlideRef, SlackThread
- derived output validation: CurrentView, KnowledgePage, Insight
- 저장된 fresh common candidate의 `promote`

아래 대상은 이 설계에서 명시적으로 제외한다.

- `context_md` 객체와 생성 Markdown 파일의 쓰기·삭제·복구
- 원격 source fetch가 원본과 같다는 증명
- CurrentView·KnowledgePage·Insight의 실제 builder 구현
- direct reviewed common create/update와 ReviewRecord history(#11·#35)
- 아직 profile이 없는 DomainMapping·GlossaryTerm(#12·#13·#36·#37)

제외 대상은 `지원됨`으로 조용히 통과하지 않는다. `evidence_profile_unavailable` 또는
`evidence_adapter_unavailable`로 corpus·index·journal·receipt 0-write 실패한다. core에는 artifact
action·consumer-root config·artifact 전용 오류 타입을 넣지 않는다.

## 2. EvidencePlan과 유지할 verification 계약

모든 plan hash 입력은 UTF-8 canonical JSON(`ensure_ascii=False`, `allow_nan=False`, key sort, compact
separator, newline 없음)이다. `evidence_plan_sha256`은 이 newline 없는 canonical bytes를 hash한다. plan
파일은 같은 bytes 뒤 newline 하나만 허용한다. parser는 알 수
없는 key, duplicate JSON key, 비정규 수, canonical bytes 불일치를 모두 거부한다.

`EvidencePlanV1` top-level exact key는 `version`, `entries`다. `version=1`이고 entry exact key는
`target_id`, `source`, `claimed_producer`, `claimed_verifiers`다. 파일을 준 경우 entries는 비어 있지 않고
`target_id` 오름차순이며 ID가 중복되면 실패한다. 모든 문자열은 trim 뒤 NFC와 byte-exact 같아야 한다.
`claimed_verifiers`는 `(kind,id,version)` 오름차순·중복 없는 배열이다. actor exact shape와 권한은 5절을
따른다.

`source`는 다음 세 exact variant만 허용한다.

| `source.type` | source exact key | 내부 항목 exact key·제약 | 허용 profile |
|---|---|---|---|
| `common_claims` | `type`, `checks` | check는 `id,outcome,authority,summary`; ID 오름차순·중복 없음, `outcome=pass\|fixed`, `authority=human\|agent`, summary 비어 있지 않음 | common 6종, `prompt_payload` |
| `raw_source_observation` | `type`, `path` | `path`는 brain-root-relative POSIX 경로이고 `raw/sources/` 아래 정규 파일 하나 | local raw 5종 |
| `existing_sources` | `type` | 추가 key 없음. profile이 target의 `source_fact_ids`, `source_event_ids`, `source_object_ids` 중 등록된 field에서 source 집합을 계산 | CurrentView·KnowledgePage·Insight 검증, 전용 `context_md` builder |

common profile registry가 check ID의 필수 집합과 authority를 정한다. plan의 authority는 registry와 같아야
하고 engine-owned check를 plan에 넣으면 `evidence_check_authority_forbidden`이다. `existing_sources`는
caller가 source ID·hash를 따로 덮어쓸 수 없다. kind·variant와 source variant가 맞지 않으면
`evidence_source_variant_mismatch`로 0-write 실패한다.

`raw_source_observation.path`는 absolute·빈 segment·`.`·`..`·backslash와 POSIX pathname API에
전달할 수 없는 NUL(`U+0000`)을 거부하며, 이 parser-level 위반은
`evidence_plan_schema_invalid`이다. brain root pin에서 각 component를 no-follow로 열고 마지막 대상이
`link_count=1`인 정규 파일인지 확인한다. 준비 시 metadata → bytes → metadata를 읽어 같은 값인지 확인하고
다음 exact snapshot을 만든다.

```text
root={path,device,inode}, path, parent_bindings,
file={device,inode,link_count,mode,size,bytes_sha256}
```

snapshot top-level exact key는 `root`, `path`, `parent_bindings`, `file`이다. `root`는 capture 당시
normalized brain root의 `{path,device,inode}`이고,
`parent_bindings`는 `raw`부터 direct parent까지 `{path,device,inode}`를 깊이 순으로 가진다. apply lock
안에서도 같은 anchored read를 반복한다. root binding, parent, path,
inode, link count, mode, size, bytes 중 하나가 달라지면 Adapter 실행이나 journal 전에
`evidence_snapshot_changed`다. raw file bytes를 journal에 복사하거나 caller가 준 hash를 신뢰하지 않는다.

caller는 source claim만 주며 raw `candidate.verification`, profile·Adapter ID, action, engine SHA, proof,
receipt ID는 만들 수 없다. 닫힌 registry가 kind·variant에서 mode·profile·source variant를 하나만 고른다.

### 2.1 E1 parser·matcher의 고정 public contract

E1의 public seam은 `parse_evidence_plan(data) -> EvidencePlanV1`, `EvidencePlanV1.canonical_bytes()`,
`EvidencePlanV1.match(requirements)`뿐이다. `canonical_bytes()`는 parse 때 검증한 newline 없는 canonical
payload bytes를 그대로 돌려준다. `parse_evidence_plan`의 `data`는 `bytes`여야 하며, non-bytes, UTF-8/JSON,
canonical form, top-level 또는 nested shape의 모든 caller 입력 위반은 raw `TypeError`·`KeyError`·decoder 예외를
새지 않고 `EvidencePlanError("evidence_plan_schema_invalid")` 하나로 끝난다.

`match(requirements)`의 `requirements`는 한 번 순회할 수 있는 iterable이고, 각 항목은 오직
`EvidencePlanRequirement(target_id: str, requirement: str, forbidden_code: str | None = None)` 인스턴스여야
한다. mapping·tuple·문자열 등 duck-typed 항목, 순회할 수 없는 값, 세 필드의 type/값 위반은 모두
`evidence_plan_schema_invalid`이다. `requirement`의 닫힌 enum은 정확히
`optional_unverified|required|forbidden`이다. `target_id`는 plan entry와 같은 non-empty Python `str`이며,
trim 뒤 NFC인 값을 caller가 이미 넘겨야 한다; matcher가 trim·normalize하지 않는다. requirement 입력 순서는
의미가 없고 matcher가 이 canonical `target_id`를 Python `str` code-point 오름차순으로 정렬해 판정한다.
같은 exact `target_id`가 두 번 나오면 `evidence_plan_schema_invalid`이며, 성공 결과의 `entries`와
`omitted_optional_target_ids`도 같은 오름차순이다.

`optional_unverified`와 `required`의 `forbidden_code`는 반드시 `None`이다. `forbidden`은 반드시
`plan_base`의 닫힌 target classifier가 고른 아래 exact closed set의 한 값만 가진다.

| classifier가 판정한 target | `forbidden_code` |
|---|---|
| delete | `evidence_plan_delete_target` |
| direct-reviewed common create/update | `direct_reviewed_evidence_unavailable` |
| generic `context_md` 또는 등록 profile이 없는 kind/profile | `evidence_profile_unavailable` |
| 등록 profile의 선택된 Adapter가 unavailable | `evidence_adapter_unavailable` |

즉 JSON plan·CLI·일반 caller가 임의 문자열을 선택할 수 없고, set 밖의 값·누락한 값은
`evidence_plan_schema_invalid`이다. matcher는 이 값을 새로 고르거나 바꾸지 않고, 검증된 값을 가진
forbidden target에 entry가 있을 때 그 exact code를 그대로 관측시킨다. 이 소유권 설명은 `plan_base`의
새 interface·adapter를 추가로 설계하지 않으며, 현재 `EvidencePlanRequirement` 세 필드를 그대로 동결한다.

parse와 requirement validation이 끝난 뒤의 match 오류 우선순위는 입력 순서와 무관하게
`forbidden entry present`(위 classifier code) → `required entry missing`(`evidence_plan_missing`) → 남은
plan entry(`evidence_plan_target_unused`)다. 같은 단계에서 둘 이상이면 가장 작은 `target_id`를 먼저
고른다. 따라서 required 누락·forbidden entry·unused entry가 한 호출에 함께 있어도 forbidden code가
먼저 나고, structural/canonical requirement 위반은 이 판정보다 앞서 `evidence_plan_schema_invalid`이다.

common envelope v1의 저장 shape와 `executed_at`을 포함하는 execution hash는 유지하되 다음 두
projection만 v2로 고정한다.

- EvidenceRef의 `/locator` 전체와 nested CodeLocator target bytes를 결속하는 evidence projection은
  `verification-evidence-v2`다. 과거 WIP v1 envelope는 `rules_changed` 또는 `evidence_changed`로 stale다.
- `prompt_payload`에만 `verification-content-v2`를 적용하고 engine-owned `generated_at`을 content
  projection에서 제외한다. 다른 common profile의 v1 discriminator와 freshness는 유지한다.

`projection_hash`, `source_content_hash`, `reuse_payload`는 content 결속에 남는다. deterministic
retry identity만 `executed_at`을 제외한다. 현재 envelope가 fresh하고 나머지 identity가 같을 때만
기존 envelope bytes를 그대로 재사용한다.

## 3. 객체 상태와 효과 소유자

```text
plan_base -> ProjectedStore -> prepare_evidence -> seal -> apply_prepared
```

| 단계 | 입력 | 산출물 | 외부 효과 소유 |
|---|---|---|---|
| `plan_base` | live store, caller objects, 선택적 repo context | action별 before/base unstamped bytes와 semantic SHA | 없음 |
| `ProjectedStore` | live store + 모든 after-image - planned delete | same-batch source를 읽는 불변 view | 없음 |
| `prepare_evidence` | projected view, plan claims, current raw/repo/loaded code | common checks 또는 dedicated execution evidence | 없음 |
| `seal` | base plan + evidence | envelope/proof가 들어간 sealed unstamped object bytes와 identity | 없음 |
| `apply_prepared` | sealed plan + live 재관측 | stamped object, journal, mutation receipt, index invalidation | `MutationService` 하나 |

### 3.1 E2 base plan 입력·snapshot·semantic identity 계약

`plan_base(...)`와 `ProjectedStore`의 현재 작은 object-only interface는 유지한다. action 판정은 기존
`classify_object_actions`, capability 판정은 기존 `CAPABILITY_REGISTRY`, semantic SHA는
`hash_utils.py`의 `source_content_hash`가 각각 정본이다. 이 계약은 새 Adapter·파일 관측·E3 이후 책임을
추가하지 않는다.

- 두 E2 공개 seam은 `after_images`의 각 ID와 `delete_ids`의 각 ID를 먼저 같은 순수 preflight로
  검증한다. ID는 `str()` 변환·trim·NFC normalize를 하지 않은 non-empty exact Python `str`이어야 하고,
  각 집합 안에는 중복이 없어야 하며 두 집합은 disjoint여야 한다. 모든 delete ID는 live store에 존재해야
  한다. 이 structural/state 위반은 다른 처리를 하지 않고 결정론적으로
  `EvidencePreparationError.code=evidence_base_plan_invalid` 하나로 실패한다. 경우별 error code를
  추가하지 않는다.
- `plan_base(...)`는 이 preflight가 끝난 뒤에만 action과 `EvidencePlanRequirement`를 만든다. 성공한
  plan에서는 target마다 exact target ID를 가진 requirement가 정확히 하나이고, 둘의 target 집합도 같다.
  입력 오류와 성공 모두 file·clock·Adapter·journal·receipt에 0효과여야 한다.
- `ProjectedStore`는 읽기 전용 interface만이 아니라, 생성 시점의 live store와 after-image(계획된 delete
  제외)를 보관하는 deep immutable snapshot이다. caller·live store·중첩 mapping/list의 이후 mutation이
  보관 상태로 스며들 수 없고, `get`·`all`·`by_kind`는 호출마다 fresh deep copy를 돌려준다. 반환값을
  중첩해서 바꿔도 snapshot이나 다음 호출의 반환값은 바뀌지 않는다.
- object semantic SHA는 언제나 exact `source_content_hash((unstamped_object,))`다. delete는 before bytes와
  before SHA만, create는 base bytes와 base SHA만, update는 둘 다 가진다. no_change의 before/base bytes와
  before/base SHA는 의미상 동등한 수준이 아니라 exact 동일해야 한다.
- E2 public seam 테스트는 delete의 before SHA를 계산 helper나 다른 target 값이 아닌 독립 literal로,
  no_change의 before/base bytes와 SHA를 서로 비교만 하지 않는 독립 literal로 고정한다. 같은 exact ID의
  after-image/delete 충돌은 `evidence_base_plan_invalid` code와 error-path의 file·clock·Adapter·journal·receipt
  0효과를 public seam에서 함께 고정한다.

base action exact enum은 `create|update|delete|no_change`다. delete는 evidence entry를 받지 않고 현재
delete 권한을 넓히지 않는다. ProjectedStore에서는 제거된 것으로 보인다. base plan을 전부 만든 뒤 각
target을 다음 세 requirement로 분류하고 나서 entry를 matching한다.

- `optional_unverified`: common candidate create/update와 common exact no-change. create/update에서 entry를
  생략하면 verification을 제거한 `unverified` candidate를 저장한다. exact no-change에서 생략하면 현재
  bytes를 그대로 보존한다. entry가 있으면 evidence를 준비한다.
- `required`: dedicated reviewed create/update/no-change. entry가 없으면 `evidence_plan_missing`이다.
- `forbidden`: delete, direct-reviewed common create/update, generic `context_md`, 미지원 kind/profile. entry가
  있으면 각각 `evidence_plan_delete_target`, `direct_reviewed_evidence_unavailable`,
  `evidence_profile_unavailable` 또는 registry 고정 오류다.

따라서 한 batch에서 plan이 있는 target과 없는 common target을 섞을 수 있다. top-level plan 자체가
없어도 모든 optional target은 위 생략 규칙을 따르지만 required target이 하나라도 있으면 실패한다.
matching 뒤 남는 entry는 `evidence_plan_target_unused`, target ID 중복은 parse 오류다. 어떤 오류든 batch
전체가 corpus·index·journal·receipt 0-write다.

`MutationService.apply_prepared()`는 exclusive corpus lock에서 기존 recovery를 먼저 수행한다. 같은
lock 안에서 base plan, ProjectedStore, repo/raw/loaded-code 관측, engine-owned check와 sealed unstamped
bytes를 다시 만들고 준비본과 byte-exact 비교한다. 불일치는 `evidence_snapshot_changed`로
corpus·index·journal·receipt 0-write 실패한다. apply 중 실패만 기존 단일-root journal recovery로
전체를 되돌린다.

| 현재 상태 | 입력 | 결과 |
|---|---|---|
| common candidate, envelope 없음 | plan 없음 | candidate 저장, `unverified` |
| common candidate 의미 변경 | plan 없음 | 이전 verification 제거 뒤 candidate 저장 |
| common candidate | valid claims | fresh envelope 저장 또는 exact 기존 envelope 재사용 |
| raw envelope 입력 | 어떤 상태든 | `verification_input_forbidden`, 0-write |
| fresh candidate | promote | lock 안 live 재검증 뒤 target+single ReviewRecord 원자 쓰기 |
| dedicated reviewed create/update/no-change | plan 없음 | `evidence_plan_missing`, 0-write |
| dedicated reviewed | valid plan | target+proof manifest 원자 쓰기, ReviewRecord 없음 |
| dedicated exact target | valid plan, live source 같음 | evidence 재검증 뒤 no-change, mutation journal 없음 |
| 준비 뒤 store/repo/raw/code 변경 | 어떤 plan이든 | `evidence_snapshot_changed`, 0-write |
| generic `ingest`의 `context_md` target | 어떤 plan이든 | `evidence_profile_unavailable`, 0-write; 전용 공개 명령으로 안내 |
| object delete | plan entry 없음 | 기존 delete precondition으로 적용, 새 evidence/proof 없음 |

## 4. 공개 입력과 설치 batch 결속

Python과 CLI는 같은 exact parser를 쓴다.

```python
def ingest(
    store: BrainStore,
    objects: list[dict],
    *,
    evidence_plan: EvidencePlanV1 | None,
    repo_context: RepoContext | None,
) -> IngestReport: ...
```

```text
project-brain ingest ... --evidence-plan-file <canonical-json-path>
project-brain projection build-reuse ... --evidence-plan-file <canonical-json-path>
project-brain projection build-context ... --evidence-plan-file <canonical-json-path>
project-brain promote ...               # 새 plan을 받지 않음
```

caller용 `dedicated_proofs` 입력은 제거한다. 호환 때문에 내부 함수에 남겨야 한다면 public Python·CLI가
접근하지 못하는 prepared-only 타입으로 제한한다.

설치 ingest의 `domain_spec.py`는 의미 데이터 선언 `EVIDENCE_PLAN`만 소유한다.
`assemble_notes.py --evidence-plan-out <path>`가 이를 exact `EvidencePlanV1` canonical JSON으로
직렬화하며 proof·receipt는 만들지 않는다. batch runner는 item 디렉터리 기준 상대 경로를 no-follow
regular-file anchored read로 읽고 다음 모두에 canonical plan bytes SHA-256을 결속한다.

- item fingerprint
- `BatchBinding`
- durable item report와 최종 batch report

resume은 item 실행 전에 `domain_spec.py`에서 plan을 다시 만들고 staged plan SHA와 비교한다. 불일치면
어떤 item도 실행하지 않는다. plan 변경은 새 item identity이며 이전 receipt를 재사용하지 않는다.
legacy batch는 “plan 없음”으로만 읽을 수 있고, 재개 중 새 plan을 주입할 수 없다. evidence가 필요한
legacy item은 새 manifest로 처음부터 다시 시작한다.

`projection build-reuse`는 plan entry의 `claimed_producer.id`를 저장 객체의 `generated_by`로 쓴다.
새 Python seam에는 별도 `generated_by` 인자가 없다. 기존 CLI `--generated-by`는 한 호환 주기 동안
assertion으로만 남고 `claimed_producer.id`와 다르면 `projection_generated_by_mismatch`로 0-write다.
caller payload의 `generated_by`를 그대로 저장하거나 engine·Adapter ID로 대신하는 경로는 없다.

same-batch acceptance가 실제로 실행 가능하도록 구현 순서는 반드시 다음을 지킨다.

1. exact parser·identity·registry
2. object-only base plan·ProjectedStore·seal·apply
3. common public Python·CLI plan 전달
4. local raw observation Adapter
5. EvidenceManifest public ingest
6. 새 EvidenceManifest+EvidenceRef same-batch 회귀
7. 나머지 profile과 installed batch resume

### 전용 `context_md` coordinator handoff

generic `ingest`는 `context_md` target을 계속 `evidence_profile_unavailable`로 거부한다. 유일한 create/update
진입점은 #38의 `projection build-context`다. coordinator는 config/root/output을 해석한 뒤 순수 builder로
target ID와 Markdown bytes를 만들고, target ID와 정확히 일치하며 `source.type=existing_sources`인 plan
entry 하나를 요구한다.

coordinator가 evidence core에 넘기는 `ContextProjectionBuildRequestV1` exact key는 다음과 같다.

```text
version, context_id, output_locator, projection_id,
source_object_ids, source_content_hash, markdown_sha256,
claimed_producer, claimed_verifiers
```

`claimed_producer`와 `claimed_verifiers`는 coordinator가 matched EvidencePlan entry에서 byte-exact로 복사한다.
CLI나 builder가 request용 actor를 별도로 받지 않으며 두 actor source를 비교·선택하는 경로 자체가 없다.
저장 `generated_by`, prepared evidence, proof authority는 모두 이 복사본 하나를 사용한다.

`projection_id`, source ID·hash, Markdown hash는 caller 입력이 아니라 pinned projected store와 현재
`context_projection.py` builder bytes에서 계산한다. 저장 `generated_by`는 `claimed_producer.id`다. 닫힌
`context_md_builder_output_v1` profile은 reviewed source 상태, source hash, rendered bytes, projection hash,
실제로 로드한 builder module identity를 engine authority로 확인한다. 이 profile에서
`claimed_verifiers=[]`는 허용하지만 caller가 engine check를 주장할 수는 없다.

evidence core의 반환값은 object-only `PreparedObjectPlanV1`이며 exact key는 `version`, `base_action`,
`before_unstamped_sha256`, `after_unstamped_bytes`, `prepared_evidence`, `sealed_object_identity_sha256`다.
artifact path·bytes·root·action은 이 타입에 들어가지 않는다. #38 coordinator가 이 준비본과 artifact plan을
결합해 `MutationService.apply_context_projection()`에 한 번 넘긴다. generic `apply_prepared()`와 caller는
이 전용 apply를 호출할 수 없다.

이 예외는 #35의 direct-reviewed 권한을 넓히지 않는다. `format=context_md`, official builder가 만든 bytes,
reviewed source만, 고정 profile, 필수 artifact action이라는 다섯 조건을 모두 만족하는 전용 projection만
reviewed로 준비한다. caller가 만든 임의 reviewed object, artifact 없는 context projection, 다른 kind는
계속 금지한다. delete는 새 evidence를 만들지 않고 #38의 저장 hash precondition으로만 처리한다.

## 5. 신원과 actor authority

### 실제로 로드한 engine·Adapter

engine identity는 새 Git 공식을 만들지 않고 `foundation.py`의 checkout 검증,
`engine_core_dirty` 거부, tracked core tree SHA 공식을 재사용한다. exact identity는 engine root의
path·device·inode, HEAD, `core_tracked_tree_sha256`, 실제 import된 `project_brain` 파일과 CLI source
경로를 결속한다.

- 실제 import·CLI 경로가 선택한 engine checkout 아래가 아니면 0-write다.
- tracked engine core가 dirty하거나 HEAD·tree SHA가 준비 뒤 바뀌면 0-write다.
- v1은 Git checkout으로 확인할 수 없는 package 설치를 지원하지 않고 `engine_identity_unavailable`로
  fail-closed한다.
- 호환 `--engine-sha`는 실제 관측 HEAD와 같아야 하는 assertion일 뿐 receipt 신원 입력이 아니다.

Adapter identity exact key는 `id`, `version`, `module_path`, `module_sha256`이다. 닫힌 registry가
kind·variant에서 Adapter를 고르고 실제 로드한 module bytes를 hash한다. caller는 Adapter ID·version·
module path를 지정할 수 없다. 준비 뒤 module bytes가 달라지면 0-write다.

### 5.1 E3 loaded identity와 handoff 고정 계약

E3의 public seam은 순수 capture/verify뿐이다. `EvidenceLoadedIdentity`의 생성은 capture factory만
수행하며, engine·adapter·raw snapshot 전체를 깊게 불변인 값으로 보관한다. 따라서 nested mapping·list를
남기지 않고, caller는 속성이나 내부 값을 바꾸거나 새 관측값으로 baseline을 대체할 수 없다. verify는 이
capture factory가 만든 값만 기준으로 현재 관측값을 비교한다.

Adapter selector의 입력은 `plan_base`가 만든 `BasePlanTarget`과 E1이 검증한 source뿐이다. caller의
`target_kind`나 Adapter ID를 받지 않고, target ID를 `parse_id`로 해석한 exact
`(kind, variant, source.type)`를 registry key로 쓴다. local raw 다섯 kind
(`EvidenceManifest`, `SpecDocument`, `SpecRevision`, `SlideRef`, `SlackThread`)에는
`(kind, default, raw_source_observation)`만 닫힌 row로 등록한다. kind·variant·source 불일치는
`evidence_source_variant_mismatch`, 등록되지 않은 row는 `evidence_adapter_unavailable`이며, 선택 결과는
실제로 로드한 Adapter module의 path와 bytes SHA-256을 identity에 기록한다.

raw snapshot capture와 재관측은 `evidence_preparation`에서 FD 순회를 다시 구현하지 않고, `snapshot`
모듈의 하나의 canonical rooted primitive가 전부 소유한다. 이 primitive는 pinned root의 device·inode를
기준으로 모든 parent와 leaf FD의 device가 같음을 확인하고, 깊이 순서의 parent bindings, regular file의
`link_count=1`, metadata → bytes → metadata 일치를 함께 만든다. 끝에서는 root path를 no-follow로 다시
열어 original root의 device·inode와 비교한다. caller path shape 오류는 `evidence_plan_schema_invalid`, 최초
관측의 symlink·hardlink·filesystem mismatch는 `evidence_raw_source_invalid`, 최초 read 불가는
`evidence_raw_source_unavailable`이다. 준비 뒤 engine·module·root·parent·file 중 하나가 바뀌거나 재관측에
실패하면 언제나 `evidence_snapshot_changed`다.

E4의 prepared value는 raw source target마다 이 immutable E3 identity를 필수 field로 그대로 보존한다.
E5의 `apply_prepared()`는 exclusive lock 안에서 Adapter 실행, clock 사용, journal·receipt·mutation보다 먼저
그 identity를 byte-exact로 재관측한다. E3는 pure capture/verify unit만 소유하고, 실제 effect-order
integration은 E5가 소유한다.

후보 2의 최소 완료 회귀는 다음을 고정한다.

- nested engine·adapter·raw snapshot mutation 시도가 verifier baseline을 바꾸지 못한다.
- kind·variant·source mismatch와 닫힌 registry 밖 선택은 고정 오류로 실패한다.
- cross-device 이동과 root rebind를 rooted primitive가 거부한다.
- engine·module·root·parent·file drift는 E5 lock 안에서 잡히며 Adapter·clock·journal·receipt·mutation 0-effect다.

CodeLocator처럼 repo evidence가 필요한 profile만 기존 `RepoContext`의 선택적 repo
root·device·inode·configured repo ID·target revision을 요구한다. 이 root는 코드 근거 관측용이며
`context_md` 생성 파일을 쓰는 consumer root가 아니다.

### actor와 check authority

actor exact key는 `kind`, `id`, `version`이고 모두 비어 있지 않은 문자열이다.

- caller actor kind는 `human|agent`만 허용한다. `engine|adapter|system` 주장을 거부한다.
- `authority=human` check는 human claimed verifier가, `authority=agent` check는 agent claimed verifier가
  최소 한 명 있어야 한다.
- claimed producer는 verifier를 대신하지 않는다. Insight는 producer와 다른 synthesis verifier를
  최소 한 명 요구한다.
- engine authority check는 engine이 projected store·filesystem·Git에서 직접 계산한다.

## 6. 의미 hash와 clock

object semantic SHA는 `hash_utils.py`의 source 의미 projection을 단일 공식으로 쓴다. base identity는
before/base unstamped bytes와 semantic SHA, evidence identity는 source·rules·actor·실제 code 신원,
sealed identity는 envelope/proof가 들어간 unstamped bytes를 결속한다. final mutation identity만 실제
stamp와 receipt를 추가한다. 뒤 단계 값을 앞 단계 hash에 넣지 않는다.

- 새 evidence 실행을 준비할 때 evidence clock을 정확히 한 번 호출한다. lock 안 재검증에서
  `executed_at`을 다시 만들지 않는다.
- fresh common envelope를 byte-reuse하는 경로는 evidence clock을 호출하지 않는다.
- dedicated exact no-change도 Adapter를 다시 실행하되 prepared evidence의 시각을 재사용하고 mutation
  clock·mutation journal을 만들지 않는다.
- object create/update처럼 실제 object bytes를 쓸 때만 apply가 mutation clock을 정확히 한 번
  호출한다. 같은 event time을 해당 plan의 모든 engine-owned stamp에 쓴다.
- 준비 실패·drift·0-write 오류는 두 clock을 apply에서 호출하지 않는다.

dedicated execution receipt ID는 다음 exact projection의 canonical SHA-256이다.

```text
version, receipt_kind, target_id, target_kind, target_variant, operation, action,
before_semantic_sha256, after_semantic_sha256, profile, rules_sha256,
sources, inputs, checks, claimed_producer, claimed_verifiers,
identity_assurance, engine, adapter
```

`identity_assurance=claimed`다. 진단용 실행 시각은 receipt ID에서 제외한다. 같은 의미 실행은 같은 ID,
source·code·profile·actor·action 중 하나가 달라지면 다른 ID다. common envelope에는 새 execution
receipt를 넣지 않는다.

## 7. 지원 표와 구현 순서

| 종류 | v1 공개 경로 | 준비 주체 | 지원 결과 |
|---|---|---|---|
| common 6종 | `ingest`, `promote` | common registry | candidate envelope 생성/제거/reuse, fresh promote |
| `prompt_payload` | `projection build-reuse` | common projection profile | content v2 freshness |
| local raw 5종 | `ingest` | local observation Adapter | target+proof manifest 원자 적용 |
| CurrentView·KnowledgePage·Insight | `ingest` | derived validation profile | caller가 만든 output 검증만 지원 |
| `context_md` generic ingest | 없음 | 없음 | 고정 오류, 0-write |
| `context_md` build/delete | `projection build-context|delete-context` | 전용 coordinator + 고정 builder profile | #38 multi-root transaction에 object 준비본 handoff |
| 원격 fetch 동일성 | 없음 | 별도 source Adapter | 고정 오류, 0-write |
| derived 실제 builder | 없음 | 후속 #10 child | 고정 오류, 0-write |
| profile 없는 kind | 없음 | 후속 admission | 고정 오류, 0-write |

구현 child는 아래 순서이며 각 행은 별도 child issue·progress block을 쓰고 90분을 넘기지 않는다.

1. E1 `evidence-plan-parser`: exact parser·canonical bytes·mixed required/optional set
2. E2 `evidence-base-plan`: object-only base plan·`ProjectedStore`
3. E3 `evidence-loaded-identity`: loaded engine/Adapter identity·raw parent/file snapshot
4. E4 `evidence-common-preparation`: common preparation·authority·v2·clock
5. E5 `evidence-sealed-apply`: seal·`apply_prepared` live 재계획과 TOCTOU
6. E6 `evidence-ref-public`: EvidenceRef public ingest
7. E7 `evidence-common-remaining`: 나머지 common 5종
8. E8 `evidence-reuse-projection`: `build-reuse`·`generated_by`
9. E9 `evidence-local-raw-adapter`: local raw Adapter foundation
10. E10 `evidence-manifest-public`: EvidenceManifest public ingest
11. E11 `evidence-same-batch`: 새 EvidenceManifest+EvidenceRef same-batch
12. E12 `evidence-local-raw-remaining`: 나머지 local raw 4종
13. E13 `evidence-derived-validation`: derived output-validation seam
14. E14 `evidence-context-handoff`: `context_md_builder_output_v1` profile과 object-only handoff unit 계약
15. E15 `evidence-installed-batch`: installed batch binding·legacy/resume

admission PASS 뒤 구현 전에 각 stable ID로 별도 GitHub child issue와 같은 ID의 progress block을 먼저
만든다. issue 번호가 생기기 전에는 구현을 시작하지 않는다. 90분에 닿으면 다음 행을 흡수하지 않고
중지한다. E14는 core profile과 `PreparedObjectPlanV1`까지만 소유하고 artifact type·public
`build-context`·multi-root transaction은 넣지 않는다. #38 C1은 #33이 고정한 E14 seam을 소비해 통합한다.
한 child가 90분을 넘기거나 표 밖의 kind·remote fetch·artifact 쓰기가 필요하면 중지하고 새 ticket으로
분리한다.

## 8. 완료 조건과 검증 연결

| 완료 조건 | 정확한 명령 | 기대 관측 |
|---|---|---|
| 1. exact source union·mixed target set과 object-only 상태·효과 소유자를 완결한다 | `.venv/bin/python -m pytest -q tests/test_evidence_plan.py tests/test_evidence_preparation.py tests/test_mutation.py -k 'canonical or source_variant or mixed or projected_store or seal or apply_prepared'` | key/order/source mismatch 거부, optional omission·required missing·same-batch·delete 규칙 exact, apply 실패 전체 rollback |
| 2. Python·CLI·installed batch가 plan 생성·전달·SHA binding·resume와 `generated_by`를 같은 계약으로 쓴다 | `.venv/bin/python -m pytest -q tests/test_ingest.py tests/test_cli.py tests/test_ingest_skill_behavior_replay.py -k 'evidence_plan or same_batch or resume or legacy or generated_by'` | public plan 성공, 새 Manifest+EvidenceRef 성공, producer projection exact, plan 변경·legacy 주입은 item 전 거부 |
| 3. 실제 engine/Adapter·raw parent/file 신원과 actor authority가 caller 사칭·drift를 막는다 | `.venv/bin/python -m pytest -q tests/test_evidence_preparation.py tests/test_evidence_plan.py tests/test_foundation.py -k 'loaded or engine_core or adapter or raw_snapshot or authority'` | checkout·engine dirt·module/parent/file drift·hardlink·actor mismatch 각각 고정 code로 0-write |
| 4. semantic/action/clock·v2 범위와 receipt identity가 exact다 | `.venv/bin/python -m pytest -q tests/test_evidence_preparation.py tests/test_verification.py tests/test_verification_domain_profiles.py -k 'semantic or action or clock or content_v2 or receipt'` | evidence/mutation clock 횟수, exact retry, prompt-only v2, locator/repo drift 결과 일치 |
| 5. 지원 표와 DAG가 public profile과 미지원 범위를 fail-closed로 구분한다 | `.venv/bin/python -m pytest -q tests/test_cli.py tests/test_ingest.py tests/test_dedicated_proof_capture.py tests/test_dedicated_proof_derived.py tests/test_context_projection.py -k 'public or unavailable or zero_write or no_change or prepared_handoff'` | local raw·derived validation 성공, generic ingest context_md·remote·builder·missing profile 0-write, E14 object-only handoff unit 성공, public build-context integration은 #38 소유, no-change journal 없음 |
| 6. 설치와 전체 엔진 계약이 고정 후보에서 함께 통과한다 | `PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py' && PYTHONPATH=src .venv/bin/python -m pytest -q` | 설치 runtime과 전체 pytest 성공. installer 변경 시 임시 대상 두 번째 설치 report의 변경 배열이 모두 빈 값 |

독립 검증 묶음은 1) object state·transaction, 2) public·installed plan, 3) identity·semantic,
4) profile·전체 회귀 네 개다. 한 묶음의 통과를 다른 완료 조건의 근거로 대신하지 않는다.

## 9. 별도 design admission gate

이 gate는 위 구현 완료 조건 6개나 검증 묶음 4개에 포함하지 않는다. commit은 자기 SHA를 자기 파일에
담을 수 없으므로 두 commit을 쓴다. `CANDIDATE_SHA`는 네 spec과 후보 카운터를 고정하고,
`RECEIPT_SHA`는 그 직계 자식으로 progress의 `설계복귀 후보 2 SHA` 한 줄만 채운다. 독립 reviewer는
candidate의 네 spec과 receipt의 progress를 한 번만 읽는다.

```bash
test -z "$(git status --porcelain)"
test "$(git rev-parse "$CANDIDATE_SHA")" = "$CANDIDATE_SHA"
test "$(git rev-parse "$RECEIPT_SHA^")" = "$CANDIDATE_SHA"
test "$(git diff --name-only "$CANDIDATE_SHA..$RECEIPT_SHA")" = \
  ".goal/brain-ticket-reconcile-v2/progress.md"
git show "$RECEIPT_SHA:.goal/brain-ticket-reconcile-v2/progress.md" | \
  grep -F -- "설계복귀 후보 2 SHA: $CANDIDATE_SHA"
for spec in \
  docs/specs/2026-08-25-evidence-preparation-repair-design.md \
  docs/specs/2026-08-25-context-md-artifact-transaction-design.md \
  docs/specs/2026-08-25-session-completion-repair-design.md \
  docs/specs/2026-08-25-session-zero-work-closure-design.md; do
  git show "$CANDIDATE_SHA:$spec" >/dev/null
done
git diff --check 0db29d9762c99ae0a2d9c0d5dd35868f831332a0.."$CANDIDATE_SHA" -- \
  .goal/brain-ticket-reconcile-v2/progress.md docs/specs/2026-08-25-*-design.md
git diff --check "$CANDIDATE_SHA..$RECEIPT_SHA" -- \
  .goal/brain-ticket-reconcile-v2/progress.md
```

명령 기대값은 clean fixed candidate, progress-only 직계 receipt, diff 오류 0개다. reviewer receipt는 issue별 exact
`issue`, `reviewed_sha`, `A1`, `A2`, `A3`, `A4`, `A5`, `Critical`, `Major`, `verdict` row를 가진다.
네 row 모두 `reviewed_sha=$CANDIDATE_SHA`, `A1=high`, `A2~A5=PASS`, `Critical=0`, `Major=0`,
`verdict=PASS`여야 설계를 확정한다. 이 한 review는 #33 4/4, #34·#38·#39 각 2/3으로 센다. 어느
row든 Major가 남으면 모든 설계복귀 상한이 이미 끝났으므로 추가 수정·재검수 없이 중지하고 사용자에게
반환한다.
