# 후보 검증·전용 증거 공개 준비 핵심 설계

- 작성일: 2026-08-25
- 상태: #33 재입장 후보, 독립 검수 전
- 대상: GitHub #33과 후속 #6·#7·#8·#9·#10
- 기준 코드 후보: `75e97fa98308b8bd7434070e05a99e69f2a5adef`
- 보존 입력: `codex/issue-33-evidence-design-admission`의 미커밋 spec
- 별도 설계: [context_md object·artifact transaction](2026-08-25-context-md-artifact-transaction-design.md)

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

`EvidencePlanV1` top-level exact key는 `version`, `entries`다. entry exact key는 `target_id`, `source`,
`claimed_producer`, `claimed_verifiers`다. target ID와 actor는 canonical 순서이고 중복을 거부한다.
caller는 kind·variant와 근거 claim만 주며 raw `candidate.verification`, profile·Adapter ID, action,
engine SHA, proof, receipt ID는 만들 수 없다. 닫힌 registry가 kind·variant에서 mode와 profile을 하나만
고른다.

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

base action exact enum은 `create|update|delete|no_change`다. delete는 evidence entry를 받지 않고 현재
delete 권한을 넓히지 않는다. ProjectedStore에서는 제거된 것으로 보인다. create/update/no-change에
필요한 entry가 없으면 `evidence_plan_missing`, 남는 entry는 `evidence_plan_target_unused`다.

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
| `context_md` target | 어떤 plan이든 | `evidence_profile_unavailable`, 0-write; 전용 공개 명령으로 안내 |
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

same-batch acceptance가 실제로 실행 가능하도록 구현 순서는 반드시 다음을 지킨다.

1. exact parser·identity·registry
2. object-only base plan·ProjectedStore·seal·apply
3. common public Python·CLI plan 전달
4. local raw observation Adapter
5. EvidenceManifest public ingest
6. 새 EvidenceManifest+EvidenceRef same-batch 회귀
7. 나머지 profile과 installed batch resume

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
| `context_md` | 없음 | 별도 artifact 설계 | 고정 오류, 0-write |
| 원격 fetch 동일성 | 없음 | 별도 source Adapter | 고정 오류, 0-write |
| derived 실제 builder | 없음 | 후속 #10 child | 고정 오류, 0-write |
| profile 없는 kind | 없음 | 후속 admission | 고정 오류, 0-write |

구현 child는 각각 90분 이내로 1) parser·object-only preparation, 2) common public 전달,
3) local raw+EvidenceManifest, 4) same-batch+나머지 profile, 5) installed batch 결속으로 나눈다.
한 child가 90분을 넘기거나 표 밖의 kind·remote fetch·artifact 쓰기가 필요하면 중지하고 새 ticket으로
분리한다.

## 8. 완료 조건과 검증 연결

| 완료 조건 | 정확한 명령 | 기대 관측 |
|---|---|---|
| 1. core에서 artifact action·consumer-root config 타입을 제거하고 object-only 상태·효과 소유자를 완결한다 | `.venv/bin/python -m pytest -q tests/test_evidence_preparation.py tests/test_mutation.py -k 'projected_store or seal or apply_prepared or snapshot_changed'` | same-batch source 성공, delete source 거부, drift 0-write, apply 실패 전체 rollback |
| 2. Python·CLI·installed batch가 plan 생성·전달·SHA binding·resume를 같은 계약으로 쓴다 | `.venv/bin/python -m pytest -q tests/test_ingest.py tests/test_cli.py tests/test_ingest_skill_behavior_replay.py -k 'evidence_plan or same_batch or resume or legacy'` | public plan 성공, 새 Manifest+EvidenceRef 성공, plan 변경·legacy 주입은 item 실행 전 거부 |
| 3. 실제 engine/Adapter 신원과 actor authority가 caller 사칭·drift를 막는다 | `.venv/bin/python -m pytest -q tests/test_evidence_preparation.py tests/test_foundation.py -k 'loaded or engine_core or adapter or authority'` | 잘못된 checkout·engine dirt·module drift·actor mismatch 각각 고정 code로 0-write |
| 4. semantic/action/clock·v2 범위와 receipt identity가 exact다 | `.venv/bin/python -m pytest -q tests/test_evidence_preparation.py tests/test_verification.py tests/test_verification_domain_profiles.py -k 'semantic or action or clock or content_v2 or receipt'` | evidence/mutation clock 횟수, exact retry, prompt-only v2, locator/repo drift 결과 일치 |
| 5. 지원 표와 DAG가 public profile과 미지원 범위를 fail-closed로 구분한다 | `.venv/bin/python -m pytest -q tests/test_cli.py tests/test_ingest.py tests/test_dedicated_proof_capture.py tests/test_dedicated_proof_derived.py -k 'public or unavailable or zero_write or no_change'` | local raw·derived validation 성공, context/remote/builder/missing profile 0-write, no-change journal 없음 |
| 6. 설치와 전체 엔진 계약이 고정 후보에서 함께 통과한다 | `PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py' && PYTHONPATH=src .venv/bin/python -m pytest -q` | 설치 runtime과 전체 pytest 성공. installer 변경 시 임시 대상 두 번째 설치 report의 변경 배열이 모두 빈 값 |

독립 검증 묶음은 1) object state·transaction, 2) public·installed plan, 3) identity·semantic,
4) profile·전체 회귀 네 개다. 한 묶음의 통과를 다른 완료 조건의 근거로 대신하지 않는다.
