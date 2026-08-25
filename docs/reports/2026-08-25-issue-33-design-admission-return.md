# #33 evidence preparation 설계 admission 반송

- 판정일: 2026-08-25
- 검수 설계: `3e08a3be8c3d838654979e062aeda416e0f26043`
- 판정: **RETURN**
- 구현·구현 child·main 병합: 실행하지 않음

## 입장 판정

| 관문 | 결과 | 근거 |
|---|---|---|
| A1 위험 등급 | 높음 | 상태 조합, identity, 재시도, TOCTOU, 다중 root transaction 효과를 다룬다. |
| A2 설계 기록 | RETURN | state table은 있으나 다중 root 쓰기와 context artifact delete의 효과 소유·복구 조합이 닫히지 않았다. |
| A3 검증 연결 | RETURN | 기존 7개 완료 조건 각각에 정확한 명령과 기대 관측값이 연결돼 있지 않다. |
| A4 크기 | RETURN | 완료 조건이 7개라 6개 상한을 넘는다. |
| A5 빈 결정 | RETURN | 같은 입력에서 구현자가 서로 다른 외부 동작을 선택할 수 있는 Major 계약 공백 8건이 확인됐다. |

A1~A5 중 하나라도 실패하면 목표에 넣지 않는 규칙에 따라 후보 번호와 공식 검수 횟수는 올리지
않는다. 아래 조사는 고정 설계와 현재 코드를 대조한 입장 전 독립 조사이며, 구현 후보 검수로
승격하지 않는다.

## Major 계약 공백

### 1. 다중 root artifact transaction

설계는 consumer root의 `docs/contexts/generated/**`와 brain root 객체를 같은 journal로
적용·rollback·recovery한다고 정하지만, root selector가 있는 manifest shape, 두 root pin/lock 순서,
journal 위치, 복구 시 config·consumer root 교체·부재, 서로 다른 filesystem의 지원 또는 거부를
정하지 않았다.

현재 [`apply_transaction()`](../../src/project_brain/corpus_io.py)은 brain root 하나와 그 아래 상대
경로만 받고, [`MutationService._commit_planned()`](../../src/project_brain/mutation.py)도 같은 단일 root
API를 호출한다. 이 상태에서는 “같은 journal”의 atomicity와 recovery를 구현자가 새로 결정해야 한다.

### 2. ContextProjection delete lifecycle

설계는 `output_locator` A→B만 A artifact delete를 정의한다. 기존 `context_md` 객체 자체를 delete할
때 old artifact도 같은 journal에서 지울지, artifact를 보존할지, delete를 거부할지 정하지 않았다.
object delete와 artifact delete를 모두 다루는 acceptance 아래에서 orphan 파일과 권한 확대 중 하나를
구현자가 선택하게 된다.

### 3. public ingest·installed batch 입력과 ticket DAG

설계는 `--evidence-plan`만 선언하고 Python `ingest()` signature, CLI, 설치된 assembled/batch runner의
plan 생성·전달·snapshot·binding·resume 계약을 닫지 않았다. 현재
[`ingest()`](../../src/project_brain/ingest.py)은 caller가 만든 `dedicated_proofs`를 받고,
[`_run_ingest()`](../../src/project_brain/cli.py)에는 evidence plan 인자가 없으며, 설치 batch의 item
fingerprint는 verify/spec/coverage만 결속한다.

구현 순서도 ticket 7의 “새 Manifest+EvidenceRef same-batch”가 raw observation 기반 ticket 12와
EvidenceManifest public ingest ticket 13보다 먼저라서 ticket 7 acceptance를 그 순서대로 실행할 수
없다.

### 4. config·consumer root binding

설계 타입은 config path·SHA만 넣고 consumer root는 config에서 얻는다고 하지만, explicit
`--brain-root`가 우선인 경로에서 config가 없거나 다른 config가 발견될 때의 선택·실패 규칙이 없다.
config 파일 자체의 regular/no-follow, device/inode/link count/mode, anchored read와 apply 시 재검증도
정하지 않았다. 현재 [`config.py`](../../src/project_brain/config.py)는 `resolve()`와
`is_file()`/`read_text()`로 symlink를 따른다.

### 5. 실제 로드된 engine·adapter identity

설계는 caller가 아닌 실제 로드 코드의 identity라고 하지만 clean requirement나 loaded source/content
digest를 정하지 않았다. 현재 [`resolve_git_checkout()`](../../src/project_brain/repo_context.py)은
root·HEAD·device·inode만 반환하므로 dirty tracked/untracked 엔진 코드로 실행해도 clean HEAD receipt가
나올 수 있다. 기존 foundation의 engine core dirt 거부 seam을 재사용할지 별도 digest를 쓸지도
결정돼 있지 않다.

### 6. caller check authority와 claimed actor 결속

EvidencePlan actor는 non-empty `kind/id/version`, check는 허용된 authority 문자열만 요구한다. 어느
check가 어느 verifier/producer 주장에 결속되는지, `authority=human`이면 human actor claim이
필수인지, caller가 engine/adapter kind를 주장할 수 없는지 정하지 않았다. 현재
[`verification.py`](../../src/project_brain/verification.py)도 authority allowlist와 actor 목록을 서로
결속하지 않는다.

### 7. semantic/action/clock exact 정의

identity가 쓰는 before/base/final semantic SHA의 exact projection·discriminator와
`base_unstamped_bytes`에서 제거하거나 보존할 필드 목록이 없다. artifact만 drift한 context_md에서
object action이 no-change인지 update인지, `generated_at/updated_at`을 다시 찍는지도 불명확하다.
현재 [`write_semantics.py`](../../src/project_brain/write_semantics.py)는 no-change bytes를 보존하고
projection update에만 `generated_at`을 stamp한다. 또한 common `executed_at`을 caller가 못 정한다는
결정과 달리 EvidencePreparation clock의 소유자·호출 횟수도 없다.

### 8. `verification-content-v2` 적용 범위

설계는 `prompt_payload`의 `generated_at` 문제를 고치기 위해 content-v2를 도입한다고 하지만,
discriminator를 전체 common profile에 적용할지 ContextProjection profile에만 적용할지 정하지 않았다.
현재 [`_rules_sha256()`](../../src/project_brain/verification.py)은 모든 profile에 전역
`content_projection` discriminator를 넣는다. 이를 그대로 v2로 올리면 prompt가 아닌 모든 v1 WIP도
`rules_changed`가 되고, prompt에만 적용하면 profile별 discriminator 공식이 새로 필요하다. legacy
stale 범위가 달라지는 두 외부 동작 중 하나를 설계가 선택해야 한다.

## 확인한 현재 회귀 기반

아래 표적 묶음은 현재 verification/proof/mutation 기반이 깨지지 않았음을 확인했다.

```text
316 passed, 4 subtests passed
architecture docs: 15 passed
```

이 통과는 공개 evidence preparation 구현 완료 근거가 아니다. 정상 public ingest의
`dedicated_proof_missing`과 content-v2·preparation·artifact transaction 미구현은 그대로 남아 있다.

## 재입장 조건

위 8건을 설계의 state/effect-owner 표, exact input/identity projection, public API·installed batch
계약, ticket DAG에 반영한다. 그다음 완료 조건을 6개 이하, 독립 검증 묶음을 4개 이하로 줄이고 각
조건에 정확한 명령과 기대 관측을 붙여 #33을 다시 `ready-for-agent`로 올린다.

그 전에는 엔진 구현, 24개 child 발행, #34 진입, 정리 브랜치의 main 병합을 하지 않는다.
