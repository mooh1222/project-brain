# 후보 검증·전용 증거 공개 쓰기 경계 보강 설계

- 작성일: 2026-08-25
- 상태: 설계 복귀 수정안, 최종 독립 재검수 대기
- 대상: GitHub #6·#7·#8·#9·#10과 부모 #1
- 기준 후보: `75e97fa98308b8bd7434070e05a99e69f2a5adef`
- 관련 결정: [후보 검증 보존 ADR](../adr/0004-keep-verification-on-candidates.md),
  [후보 확인과 승격 분리 ADR](../adr/0005-separate-candidate-confirmation-from-promotion.md)

## 1. 발견한 공백과 회귀

기준 후보에는 common verification과 dedicated proof의 계산·검증·mutation 관문이 있다. 하지만
공개 호출 경로와 이어지지 않아 완료가 아니라 통합 회귀 상태다.

- common preparation은 Python 함수뿐이고 `project-brain ingest`가 비엔진 check나 actor를 받지 않는다.
- 기본 `MutationService`는 reviewed EvidenceManifest create/update에 dedicated proof를 요구하지만
  공개 ingest는 proof를 만들거나 전달하지 않는다. 정상 bundle도 `dedicated_proof_missing`으로
  실패한다. CLI·ingest 테스트는 `dedicated_proof_profiles=()`를 주입해 이 회귀를 숨긴다.
- `prepare_capture_proof()`와 `prepare_derived_dedicated_proof()`는 caller가 임의의 64hex receipt ID와
  actor·engine SHA를 줄 수 있어 실제 실행 provenance를 증명하지 못한다.
- `project-brain promote`는 CodeLocator candidate를 검증하기 전에 repo context 없이 `promote()`를
  호출한다. 저장 당시 fresh했던 CodeLocator도 공개 CLI 승격 재검증에서 실패한다.
- `ContextProjection`은 `prompt_payload`가 common, `context_md`가 dedicated다. kind 하나로 mode를
  고를 수 없다.
- CurrentView·KnowledgePage·Insight의 실제 builder는 없다. 현재 코드는 caller가 만든 target과
  source를 대조할 뿐 생성 실행을 증명하지 않는다.

따라서 locator hash 결함과 CodeLocator CLI context 순서는 명확한 code repair로 닫고, 공개 evidence
준비는 아래 계약을 먼저 구현한다.

## 2. 유지할 기존 결정

### 2.1 common envelope v1 shape는 유지하고 evidence projection은 v2로 교정한다

부모 #1과 #6이 고정한 `candidate.verification` v1 exact shape와 `execution_sha256`은 유지한다.
`executed_at`도 계속 execution hash에 들어가며 새 receipt 필드를 envelope에 추가하지 않는다.

다만 기준 후보 `75e97fa`의 `verification-evidence-v1`은 EvidenceRef의 `/locator` 전체 값을 결속하지
않은 미출시 WIP 공식이었다. 정리 branch는 이를 조용히 재정의하지 않고
`verification-evidence-v2`로 올린다. v2는 `/locator` 전체 canonical value와 nested
`/locator/code_locator_id` 대상 bytes를 함께 결속한다. v1 projection으로 준비된 WIP envelope는
현재 rules/evidence와 달라 `stale`이 되며 승격 전에 새로 준비해야 한다. main에 출시된 과거
계약을 migration하는 것이 아니라 통합 후보 안의 결함을 main 반영 전에 한 번 교정하는 전환이다.

`prompt_payload` ContextProjection은 별도 content projection 전이가 필요하다. 현재
`verification-content-v1`은 `generated_at`을 내용 hash에 넣지만 mutation timestamp policy는
envelope를 seal한 뒤 exclusive lock에서 이 값을 찍는다. 그대로 구현하면 저장 직후
`content_changed`다. repair는 common preparation을 공개하기 전에 `verification-content-v2`를
도입하고 engine-owned 비의미 시각인 `generated_at`을 content projection에서 제외한다. rules
binding의 content projection discriminator도 v2로 올리므로 과거 prompt WIP envelope는
`rules_changed`로 stale 처리한다. `projection_hash`, `source_content_hash`, `reuse_payload`는 계속
내용 결속에 남고 `generated_at`만 mutation clock이 한 번 찍는다. 다른 kind에는 이 필드가 없으므로
의미 projection이 달라지지 않는다. 이 전이는 현재 코드 수리 완료가 아니라 evidence design
admission과 첫 구현 ticket의 필수 범위다.

재시도 비교에는 저장하지 않는 내부 `evidence_identity_sha256`을 사용한다. 이 값은 현재 target
semantic bytes, source, profile/rules, checks, actor claims, engine identity를 묶되 `executed_at`만
제외한다. 기존 envelope가 live 기준 fresh하고 이 identity가 같으면 envelope 전체를 byte 그대로
재사용한다. common에도 저장 receipt가 필요해지면 v2와 legacy 전이, 부모 #1·#6·ADR 변경을 먼저
승인받는다.

### 2.2 명령 소유권을 유지한다

- `ingest`: candidate verification 준비와 일반 object mutation
- `promote`: 저장된 fresh candidate envelope를 lock 안에서 다시 검증해 승격
- projection build/refresh: 각 projection variant의 생성·갱신
- #11 이후: direct reviewed common create/update

모든 것을 새 mega-ingest 명령으로 합치지 않는다. 각 public command가 공용 내부 preparation seam을
조율한다.

### 2.3 증명 범위를 과장하지 않는다

현재 actor identity는 인증 체계가 없는 `{kind,id,version}` 주장이다. receipt는 주장된 actor를
결속할 뿐 그 사람이 실제 누구인지 인증하지 않는다. engine/adapter identity는 caller가 아니라
실제로 로드한 코드에서 얻는다.

## 3. 의존 방향과 Interface

```text
evidence_contracts
   ↑              ↑
mutation      evidence_preparation
   ↑              ↑
   └──── ingest/projection coordinator
```

`evidence_contracts.py`는 stdlib와 공용 enum만 import한다. `mutation.py`와
`evidence_preparation.py`는 서로 import하지 않는다.

```python
@dataclass(frozen=True)
class BasePreparedAction:
    target_id: str
    target_kind: str
    target_variant: str | None
    action: Literal["create", "update", "delete", "no_change"]
    before_bytes: bytes | None
    base_unstamped_bytes: bytes | None
    before_semantic_sha256: str | None
    base_after_semantic_sha256: str | None

@dataclass(frozen=True)
class BaseMutationPreparation:
    operation: str
    consumer_repo_root: Path
    consumer_repo_root_device: int
    consumer_repo_root_inode: int
    brain_root: Path
    brain_root_device: int
    brain_root_inode: int
    config_path: Path
    config_sha256: str
    store_fingerprint: str
    repo_identity: str | None
    target_revision_sha: str | None
    actions: tuple[BasePreparedAction, ...]

@dataclass(frozen=True)
class EvidencePlanEntry:
    target_id: str
    source: CommonClaims | RawSourceObservation | ExistingSources
    claimed_producer: ActorIdentity
    claimed_verifiers: tuple[ActorIdentity, ...]

@dataclass(frozen=True)
class EvidencePlan:
    version: Literal[1]
    entries: tuple[EvidencePlanEntry, ...]

@dataclass(frozen=True)
class PreparedEvidence:
    preparation_identity_sha256: str
    target_results: tuple[PreparedTargetEvidence, ...]

@dataclass(frozen=True)
class PreparedProjectionArtifactAction:
    target_id: str
    path: str
    action: Literal["create", "update", "delete", "no_change"]
    before_exists: bool
    before_sha256: str | None
    after_bytes: bytes | None
    after_sha256: str | None

@dataclass(frozen=True)
class SealedPreparedAction:
    target_id: str
    target_kind: str
    target_variant: str | None
    action: Literal["create", "update", "delete", "no_change"]
    before_bytes: bytes | None
    sealed_unstamped_bytes: bytes | None
    before_semantic_sha256: str | None
    final_after_semantic_sha256: str | None

@dataclass(frozen=True)
class SealedMutationPreparation:
    base: BaseMutationPreparation
    evidence: PreparedEvidence
    final_actions: tuple[SealedPreparedAction, ...]
    projection_artifacts: tuple[PreparedProjectionArtifactAction, ...]
    sealed_identity_sha256: str
```

`BaseMutationPreparation`은 효과 없이 caller payload를 정규화하고 caller가 넣은 engine-owned
verification과 mutation event time을 제거한 `base_unstamped_bytes`까지만 고정한다. 아직 common
envelope와 mutation clock이 없으므로 이를
최종 저장 bytes라고 부르지 않는다. target ID·variant 순으로 정렬하고 중복을 금지한다.
`delete`는 before bytes/hash만 있고 두 after 값은 `None`이다. create/update/no-change는 반대로
정규화한 after bytes/hash가 있어야 한다. 기존 delete 권한을 넓히지 않으며 delete action은 evidence
entry나 새 proof를 받지 않는다. 대신 같은 batch의 source 수명주기와 transaction identity를 다시
만들 수 있도록 base/sealed action에 끝까지 남긴다.

`ProjectedStore`는 live store에 base plan의 모든 after-image를 덮은 읽기 전용 view다. 같은 ID는
base after-image가 우선하고 planned delete는 없는 객체로 본다. source reference가 planned delete를
가리키면 준비를 거부한다. 같은 bundle의 새 EvidenceManifest를 새 EvidenceRef가 가리키거나 새
source를 DecisionRecord가 가리키는 경우에는 이 view에서 source를 해석한다. verification 자체처럼
engine-owned 필드는 source 의미 projection에서 제외한다.

Evidence Adapter는 live store를 직접 받지 않고 이 `ProjectedStore`만 받는다. evidence를 만든 뒤
`MutationService.seal()`이 common envelope를 base target에 삽입하고 dedicated proof를 결속해 최종
canonical unstamped bytes와 action을 갖는 `SealedMutationPreparation`을 만든다. `created_at`,
`updated_at`, `generated_at`처럼 mutation clock이 소유하는 값은 이 단계에 찍지 않는다. 따라서 base
bytes, sealed intent, 실제 저장 bytes를 서로 같은 것으로 오해하지 않는다. `PreparedEvidence`와
sealed plan은 저장 객체가 아니며 apply에서 재검증할 입력이다.

caller는 mode, profile, Adapter ID/version, action, engine SHA, envelope, `DedicatedProof`, receipt ID를
지정하지 않는다. target kind·variant와 닫힌 registry가 정확히 하나를 고른다. 호환용
`--engine-sha`가 남아 있으면 실제 engine checkout에서 해석한 SHA와 같은지 확인하는 assertion일
뿐 receipt 입력이 아니다.

## 4. EvidencePlan v1

관련 CLI는 `--evidence-plan <json>`을 받는다. top-level exact key는 `version`, `entries`다. entry
exact key는 `target_id`, `source`, `claimed_producer`, `claimed_verifiers`다. target ID와 verifier는
정렬·중복 없이 둔다.

actor exact key는 `kind`, `id`, `version`이고 세 값은 비어 있지 않은 문자열이다. actor는 claimed
identity라는 한계를 help·report에 표시한다.

base plan을 만든 뒤 evidence entry는 증거가 필요한 create/update/no-change action과 정확히 맞아야
한다. delete target entry는 `evidence_plan_delete_target`으로 0-write 거부한다. delete는
`ProjectedStore`에서 제거된 객체로 보이고 live 재계획·journal·receipt에는 계속 결속된다.

### 4.1 common claims

아래 JSON은 입력 구조만 보여 주는 축약 모양이다. 실제 profile 하나를 통과하는 전체 check 집합이
아니며 그대로 저장하거나 실행할 수 있는 fixture가 아니다.

```json
{
  "type": "common_claims",
  "checks": [
    {
      "id": "common.content-supported",
      "outcome": "pass",
      "authority": "agent",
      "summary": "현재 원문이 내용을 직접 뒷받침한다."
    }
  ]
}
```

caller는 profile의 비엔진 check만 정확히 제공한다. engine authority check는 projected store·
filesystem·Git에서 실행한다. 현재 common profile 전체, 즉 EvidenceRef, EventLedgerRecord,
TemporalFact, CodeLocator, DomainContext, DecisionRecord, `prompt_payload` ContextProjection을 같은
내부 EvidencePreparation seam으로 연결한다. 외부 명령 소유권은 비-projection 6종이
`project-brain ingest`, `prompt_payload`가 `project-brain projection build-reuse`, 승격이
`project-brain promote`다. `INGEST`가 ContextProjection을 거부하는 현재 경계를 완화하지 않는다.

`projection build-reuse --write`에서 target의 `generated_by`는 EvidencePlan
`claimed_producer.id`를 엔진이 투영한 값 하나만 쓴다. 실제 실행 코드 신원은 target 필드가 아니라
receipt의 registry `adapter` identity다. 기존 `--generated-by`는 plan 없는 preview의 claimed 값으로만
남기거나, plan과 함께 쓰면 같은 값인지 확인하는 호환 assertion으로 제한한다. 둘이 다르면
`projection_generated_by_mismatch`로 0-write 실패한다.

- plan 없는 새 candidate는 envelope 없이 `unverified`로 저장할 수 있다.
- raw `candidate.verification`을 create/change 입력으로 주면 `verification_input_forbidden`이다.
- 의미·근거가 바뀐 candidate에 plan이 없으면 이전 verification은 엔진이 제거한 after bytes로
  준비하고, caller가 보존을 강요할 수 없다.
- 기존 candidate의 exact bytes 재시도는 live freshness를 계산한 뒤 no-change로 닫는다. stale여도
  쓰지는 않으며 현재 status를 report한다.
- plan이 있고 기존 envelope가 fresh하며 내부 evidence identity가 같으면 기존 envelope를 재사용한다.
- candidate promotion은 새 plan을 받지 않고 저장 envelope를 repo context 포함 live 상태에서 다시
  검증한다.

direct reviewed common create/update와 ReviewRecord history는 #11 전에는 허용 범위를 넓히지 않는다.
capability가 common으로 선언했지만 profile이 아직 없는 GlossaryTerm·DomainMapping은 plan 없이 기존
unverified 경로를 유지한다. 두 kind에 plan을 주면 `evidence_profile_unavailable`로 0-write 실패한다.
profile 정의는 각각 #13과 #12가 소유하며 이 repair가 임의로 검사 목록을 만들지 않는다.

### 4.2 raw source observation

```json
{
  "type": "raw_source_observation",
  "path": "raw/sources/spec/checkout-v42.md"
}
```

v1 engine은 원격 spec·Slack·wiki를 직접 capture하지 않는다. 설치 스킬이나 사람이 준비한
`raw/sources/**` 정규 파일을 Adapter가 관측하고 exact bytes에 결속한다. 그래서 이 receipt의 이름과
증명 범위는 `raw-source-observation`이며 "원격 원문과 동일함"을 증명하지 않는다. #9의 capture
receipt가 원격 fetch 실행까지 뜻한다면 별도 source-specific capture Adapter ticket이 필요하고 #9는
그 전까지 완료가 아니다.

path는 brain root 기준 canonical 상대 경로다. 절대 경로, `..`, symlink를 거부하고 anchored open 뒤
device, inode, link count, mode, size, bytes SHA를 결속한다. hardlink는 `st_nlink != 1`이면 거부한다.
EvidenceManifest의 locator·ACL·redaction과 spec/revision/slide/thread 관계는 profile별 engine check가
검증한다.

### 4.3 existing sources

```json
{"type": "existing_sources"}
```

source ID와 Adapter는 caller가 적지 않는다. profile이 target의 `source_fact_ids`,
`source_event_ids`, `source_object_ids`에서 exact 집합과 기대 kind를 파생한다.

- `context_md`: 엔진의 실제 `build_context_projection()`을 실행해 object와 Markdown output을 함께
  만든다. projection 객체만 검증하고 output 파일을 별도 쓰는 것으로 완료하지 않으며, 아래
  projection artifact transaction 기반 뒤에 전용 projection 명령을 연결한다.
- CurrentView·KnowledgePage·Insight: 실제 builder가 생기기 전에는 `builder-output-validation`
  receipt만 발급한다. 이는 caller target과 현재 sources가 맞다는 증거이지 builder 실행 증거가
  아니다. #10 acceptance를 이 제한에 맞게 보강하거나 각 실제 builder ticket이 끝날 때까지 #10을
  open으로 둔다.
- Insight는 claimed producer와 별개 claimed synthesis verifier를 최소 한 명 요구하고 두 ID가 달라야
  한다.

## 5. preparation identity와 dedicated execution receipt

common envelope에는 새 receipt를 저장하지 않는다. dedicated proof의 `execution.receipt.id`만 엔진이
계산한다. exact receipt projection은 다음 key를 쓴다.

```text
version, receipt_kind, target_id, target_kind, target_variant, operation, action,
before_semantic_sha256, after_semantic_sha256, profile, rules_sha256,
sources, inputs, checks, claimed_producer, claimed_verifiers,
identity_assurance, engine, adapter
```

- `identity_assurance`는 v1에서 `claimed`다.
- `engine`은 실제 checkout/package에서 해석한 ID·version·SHA다.
- `adapter`는 닫힌 registry가 실제 로드한 ID·version이다.
- source와 check는 pointer/ID 순, actor는 `(kind,id,version)` 순이다.
- null은 허용한 field에 명시적으로 남기며 field 생략으로 표현하지 않는다.
- canonical JSON은 UTF-8, `ensure_ascii=False`, `allow_nan=False`, key sort, compact separator, hash 입력
  newline 없음이다. ID는 이 projection의 SHA-256이다.

실행 시각은 proof 진단 필드로 남길 수 있지만 receipt ID에는 넣지 않는다. 같은 의미 실행의 retry가
새 ID를 만들지 않게 하기 위해서다. proof hash와 mutation transaction ID는 현재 dedicated proof
전체와 before/after corpus fingerprint를 계속 결속한다.

## 6. lock 전후 exact snapshot과 효과 소유자

서로 다른 시점의 값을 한 identity에 순환시켜 넣지 않는다. 네 층을 분리한다.

1. `base_snapshot_identity_sha256`: live object snapshot, config에서 해석한 consumer repo root와
   brain root의 path·device·inode, config bytes SHA, repo identity/revision, base unstamped intent
2. `evidence_snapshot_identity_sha256`: projected source, raw/repo 관측, profile/rules,
   engine/adapter, claimed actors와 checks. common `executed_at`은 envelope v1 실행 결속에는 들어가지만
   deterministic retry 비교 identity에서는 기존 결정대로 제외
3. `sealed_intent_identity_sha256`: base identity, evidence identity, common envelope가 들어간 sealed
   unstamped object bytes, dedicated proof, artifact actions
4. 최종 mutation receipt/transaction ID: exclusive lock에서 clock을 정확히 한 번 호출해 stamp한 object
   bytes와 before/after corpus fingerprint를 결속

세 identity의 exact projection은 다음을 합쳐 각 단계 입력까지만 포함한다.

```text
operation
target id, kind, variant, base action
before/base unstamped/sealed unstamped canonical object bytes SHA와 semantic SHA
direct source pointer, ID, canonical bytes/semantic SHA
raw path, device, inode, link count, mode, size, bytes SHA
config path·bytes SHA, consumer repo root와 brain root의 device/inode
repo identity와 target revision SHA
profile, rules, engine, adapter identity
projection artifact path, action, before 존재 여부와 SHA, after SHA
```

순서는 다음과 같다.

1. `MutationService.plan_base()`가 짧은 shared corpus lock에서 recovery 필요 여부를 확인하고
   `BaseMutationPreparation`과 `ProjectedStore`를 효과 없이 만든다.
2. coordinator가 lock 밖에서 projected view만 넘겨 `EvidencePreparation` Adapter를 실행한다.
3. `MutationService.seal()`이 envelope를 삽입하고 proof·artifact action을 결속해 sealed unstamped
   object bytes의
   `SealedMutationPreparation`을 만든다.
4. `MutationService.apply_prepared()`가 exclusive lock에서 journal recovery를 먼저 수행한다.
5. live store에서 base plan과 projected view를 다시 만들고 store·repo·raw·artifact snapshot 및
   engine-owned check를 재검증한다. caller claims와 준비 시각을 새로 만들지는 않고 준비된 envelope의
   deterministic identity가 같은지 확인한다.
6. 다시 seal한 intent identity와 unstamped bytes가 준비본과 byte-exact 같을 때 mutation clock을
   정확히 한 번 호출한다. 그 event time으로 object를 한 번 stamp한 뒤 target, 필요한 ReviewRecord,
   dedicated proof와 projection artifact를 한 journal로 적용한다. 준비된 common envelope의
   `executed_at`은 다시 만들거나 mutation event time으로 덮지 않는다.

corpus·index invalidation·journal·mutation receipt의 유일한 효과 소유자는 `MutationService`다.
projection command는 target bytes를 생성·조율하지만 corpus 적용은 `MutationService`에 위임한다.
`raw/sources/**` 쓰기는 evidence preparation 범위가 아니며 설치 스킬/사람이 별도 소유한다.

`context_md` output은 일반 `auxiliary_updates`를 재사용하지 않는다. consumer repo root는
`brain_root.parent`로 추론하지 않고 config에서 해석해 root path·device·inode와 config bytes SHA를
base snapshot에 결속한다. 전용 artifact action은 그 root 기준 `docs/contexts/generated/**` 아래의
canonical 상대 경로만 허용하고 absolute path,
`..`, symlink, root 밖 해석, 비정규 파일, hardlink를 거부한다. before 파일의 존재 여부와 bytes SHA,
after bytes SHA를 sealed identity와 mutation manifest에 넣는다. object와 output file은 같은 journal의
backup·apply·rollback·recovery 범위에 있으며 report는 object action과 artifact action을 분리해
노출한다. 이 전용 허용 목록은 ID migration의 `eval_scenarios.json` update와 섞지 않는다.

artifact action은 target ID와 path를 함께 소유한다. 서로 다른 target이 같은 destination을 쓰거나 한
plan에 path가 중복되면 거부한다. 같은 ContextProjection의 `output_locator`가 A에서 B로 바뀌면 A
delete와 B create, projection update를 같은 journal에 넣는다. A의 before snapshot과 B의 create
precondition 중 하나라도 달라지면 전체가 0-write다.

준비 실패와 live identity 불일치는 corpus·index·receipt를 전혀 쓰지 않는다. apply 중 실패는 기존
journal recovery로 전체를 되돌린다.

## 7. 상태표와 no-change

| 현재 상태 | plan | 결과 |
|---|---|---|
| 새/기존 candidate, envelope 없음 | 없음 | candidate 저장 가능, `unverified` |
| common candidate 의미 변경 | 없음 | 이전 verification 제거 뒤 candidate 저장 |
| common candidate | 유효 claims | fresh v1 envelope 저장 또는 exact 기존 envelope 재사용 |
| common candidate | raw envelope 입력 | `verification_input_forbidden`, 0-write |
| fresh candidate | promote | repo context 포함 lock 안 재검증 뒤 target+single ReviewRecord 원자 쓰기 |
| dedicated reviewed create/update/no-change | 없음 | `evidence_plan_missing`, 0-write |
| dedicated reviewed | 유효 plan | target+proof manifest 원자 쓰기, ReviewRecord 없음 |
| dedicated 동일 bytes | 유효 plan, live evidence 동일 | proof를 재검증한 뒤 no-change, 새 journal 없음 |
| 준비 뒤 store/repo/raw 변경 | 어떤 plan이든 | `evidence_snapshot_changed`, 0-write |
| context_md object와 artifact 모두 동일 | 유효 plan, live source 동일 | object·artifact no-change, 새 journal 없음 |
| context_md output만 다름 | 유효 plan | object와 artifact를 같은 journal에서 갱신 |
| context_md output_locator A→B | 유효 plan | A 삭제+B 생성+object 갱신을 같은 journal에서 적용 |
| object delete | plan entry 없음 | 기존 delete precondition으로 적용하고 projected source에서는 제거, 새 evidence/proof 없음 |
| 준비 뒤 artifact 생성·변경·삭제 | 어떤 plan이든 | `projection_artifact_snapshot_changed`, 0-write |

동일 target bytes라도 dedicated source가 바뀌었으면 no-change로 닫지 않는다. 일반 direct ingest의
과거 transaction receipt를 재발행한다고 주장하지 않으며 durable batch no-change는 기존
`BatchBinding` 계약을 따른다.

## 8. 공개 오류

CLI는 첫 실패 하나를 반환한다. 여러 target이면 target ID 순으로 가장 앞선 실패를 고른다. JSON
`error_details` exact key는 `target_id`, `stage`, `reason_codes`이고 reason은 profile의 고정 순서다.

- `evidence_plan_invalid`
- `evidence_plan_target_missing`
- `evidence_plan_delete_target`
- `evidence_plan_target_unused`
- `evidence_mode_conflict`
- `evidence_profile_unavailable`
- `evidence_source_missing`
- `evidence_adapter_unavailable`
- `evidence_execution_failed`
- `evidence_snapshot_changed`
- `projection_artifact_path_invalid`
- `projection_artifact_snapshot_changed`
- `projection_generated_by_mismatch`
- `verification_input_forbidden`
- `verification_not_ready`
- `dedicated_proof_not_ready`

## 9. 90분 구현 티켓 경계

의존 순서대로 다음 ticket을 만든다. 한 행은 한 writer가 90분 안에 표적 RED와 구현을 닫을 수 있는
경계다.

1. common v1 envelope shape 호환, evidence projection v2 유지, `generated_at`을 제외하는 content
   projection v2 전이와 deterministic retry identity
2. `evidence_contracts.py` 순수 타입·exact parser·오류
3. 실제 engine identity와 닫힌 Adapter registry
4. `BaseMutationPreparation`과 same-batch `ProjectedStore`
5. evidence 뒤 최종 bytes를 만드는 `seal()`과 sealed identity
6. `apply_prepared()` lock 재계획·TOCTOU·0-write
7. EvidenceRef public ingest와 새 Manifest+EvidenceRef same-batch 회귀
8. EventLedgerRecord·TemporalFact public ingest
9. CodeLocator public ingest와 repo drift
10. DomainContext·DecisionRecord public ingest와 새 source same-batch 회귀
11. `prompt_payload`의 `projection build-reuse` evidence-plan 연결
12. raw source observation·path/symlink/hardlink 기반
13. EvidenceManifest local raw observation public ingest
14. SpecDocument·SpecRevision local source chain
15. SlideRef local source observation
16. SlackThread local source observation
17. derived `builder-output-validation` 공통 기반
18. CurrentView output validation 경로
19. KnowledgePage output validation 경로
20. Insight synthesis verifier·replace 경로
21. projection artifact의 config-root·path·create/update/delete/no-change 계약
22. projection artifact transaction manifest·apply·recovery
23. artifact failure injection·rollback·locator rename·no-change
24. `context_md` 실제 builder의 object+artifact projection CLI 연결

#9의 원격 원문 동일성 acceptance는 local raw observation과 별개 source-specific capture Adapter
ticket들에 의존한다. #10의 실제 생성 실행 acceptance도 CurrentView·KnowledgePage·Insight 각각의 실제
builder ticket에 의존한다. 이 후속이 없으면 output validation까지만 구현하고 부모 #9·#10은 닫지
않는다. 설계와 현재 issue body가 맞춰지기 전에는 #9·#10의 `ready-for-agent`를 제거하고
`needs-triage`로 둔다.

CodeLocator CLI repo context 순서 결함은 이 기반과 독립인 작은 TDD repair로 먼저 닫는다. 각 ticket은
최대 후보 3개, 검수 3회, 설계 복귀 1회, 전체 검사 2회 상한을 유지한다.

## 10. 완료 시 문서와 검증

구현 ticket은 public CLI와 저장 bytes, 0-write, rollback을 최고 자동 검증 경계로 삼는다. 내부 proof
validator만 통과시키거나 default profile을 비활성화한 CLI 테스트로 완료하지 않는다. 최소 회귀는
다음을 포함한다.

- 정상 assembled EvidenceManifest bundle이 기본 `MutationService`로 public ingest 성공
- ingest 소유 common 6종과 `projection build-reuse` 소유 `prompt_payload`의 plan 준비,
  candidate envelope 생성/제거/reuse
- 새 Manifest+EvidenceRef와 새 source+DecisionRecord를 같은 bundle에서 projected-store로 검증
- CodeLocator public promote의 repo context 전달과 lock 안 재검증
- raw file symlink/hardlink/source drift, repo revision drift, store TOCTOU의 0-write
- dedicated no-change의 live evidence 재검증과 journal 비생성
- prepare와 apply clock이 달라도 sealed unstamped intent가 같으면 성공하고, exact retry는 no-change
- `prompt_payload`는 apply가 `generated_at`을 찍은 뒤에도 fresh이고, content v1 WIP envelope는
  rules drift로 stale
- `context_md` public builder의 object+artifact 원자 적용·rollback과 proof,
  `prompt_payload` common projection 경로 분리
- context_md locator A→B의 old artifact 삭제와 new artifact 생성, path 충돌·config/root drift 0-write
- plan producer와 `--generated-by` 불일치 0-write 및 adapter identity 분리
- installer runtime unittest와 두 번째 install 무변경

같은 변경에서 `data-contracts.md`, `runtime-map.md`, `change-map.md`, ROADMAP, ADR 0004/0005의
implementation note, 설치 ingest/projection reference를 현재 코드와 맞춘다. index 입력이나 실제
corpus를 바꾸지 않은 합성 repair만으로 실모델 rebuild를 실행하지 않는다.
