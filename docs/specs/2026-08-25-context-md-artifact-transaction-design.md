# context_md ContextProjection 객체·생성 파일 생명주기 설계

- 작성일: 2026-08-25
- 상태: 신규 design admission 후보 1 RETURN — Critical 0 / Major 2, #33 계약 보강 전 구현 금지
- 선행 계약: [evidence preparation 핵심](2026-08-25-evidence-preparation-repair-design.md)
- 대상: `ContextProjection(format=context_md)`와 생성 `docs/contexts/generated/**/CONTEXT.md`

## 1. 이름과 범위

`context_md`는 파일명이 아니라 `ContextProjection.format` 값이다. `ContextProjection` JSON 객체는
brain root에 있고, 생성 Markdown artifact는 consumer repo root의
`docs/contexts/generated/**/CONTEXT.md`에 있다. 루트의 수동 `CONTEXT.md`와 지식 초안
`brain/drafts/<topic-id>.md`는 이 설계의 입력·출력·삭제 대상이 아니다.

이 설계는 현재 내부 함수인 `build_context_projection()`을 전용 공개 명령에 연결하고 JSON 객체와
생성 파일의 create/update/delete/no-change, 누락 파일 복구, locator 이동, rollback, crash recovery를
한 transaction으로 닫는다. `prompt_payload`, CurrentView·KnowledgePage·Insight builder, 서로 다른
filesystem을 잇는 2단계 복구는 범위 밖이다.

## 2. config와 두 root 결속

```text
project-brain projection build-context \
  --context-id <id> \
  --output docs/contexts/generated/<context-key>/CONTEXT.md \
  [--project-config <absolute-.project-brain.json>] \
  [--brain-root <absolute-path>]

project-brain projection delete-context \
  --projection-id <id> \
  [--project-config <absolute-.project-brain.json>] \
  [--brain-root <absolute-path>]
```

consumer root를 소유하는 `.project-brain.json`은 두 명령에서 필수다. `--project-config`가 없으면 현재
디렉터리부터 기존 discovery로 하나만 찾는다. config의 parent가 consumer root다. `--brain-root`가
없으면 config 값을 쓰고, 있으면 config가 가리키는 brain root와 path·device·inode가 정확히 같아야
한다. 명시 brain root가 config를 우회해 다른 consumer root를 고르는 경로는 없다.

config는 symlink·비정규 파일·hardlink를 거부하고 anchored no-follow read 두 번의 metadata와 bytes가
같아야 한다. config snapshot exact key는 `path`, `device`, `inode`, `link_count`, `mode`, `size`,
`bytes_sha256`이다. root binding exact key는 `kind`, `selector`, `path`, `device`, `inode`이며 `kind`는
`brain|consumer`, brain selector는 `config|explicit_match`, consumer selector는 `owning_config`다.

준비 identity에는 config snapshot과 두 root binding을 넣는다. apply lock 안에서 다시 관측해 config나
root가 바뀌었으면 journal 전에 `projection_artifact_snapshot_changed`로 0-write 실패한다. 두 root의
`st_dev`가 다르면 `projection_artifact_filesystem_mismatch`로 실패한다.

artifact는 consumer root 기준 `docs/contexts/generated/**/CONTEXT.md` 정규 파일만 허용한다. 절대 경로,
`..`, symlink, hardlink, root 밖 해석, 한 plan의 중복 destination, 다른 projection이 소유한 destination을
거부한다. 모든 read/write/delete는 root pin에서 anchored open으로 수행한다.

## 3. 객체와 artifact 상태표

artifact의 exact 정상 bytes는 현재 저장 객체의 `projection_hash`와 일치하는 UTF-8 content다.
`stale_policy=fail_on_manual_edit`이므로 존재하는 파일의 bytes가 이 hash와 다르면 수동 수정으로 본다.

| object 상태 | artifact 상태 | 요청 | object action | artifact action | 결과·시각 |
|---|---|---|---|---|---|
| 없음 | 없음 | build | create | create | object clock 1회 |
| fresh, locator A | exact A | 같은 build | no_change | no_change | byte-preserving, clock·journal 없음 |
| fresh, locator A | A 없음 | 같은 build | no_change | create | 누락 파일 복구, object 시각 보존 |
| fresh, locator A | A bytes drift | 같은 build | no_change | 없음 | `projection_artifact_manual_edit`, 0-write |
| stale/source 변경, locator A | exact old A | build A | update | update | object clock 1회 |
| stale/source 변경, locator A | A 없음 | build A | update | create | object clock 1회 |
| stale/source 변경, locator A | A bytes drift | build A | 없음 | 없음 | 수동 수정 보호, 0-write |
| locator A | exact A, B 없음 | build B | update | A delete+B create | object clock 1회, 한 transaction |
| locator A | A 없음·drift 또는 B 존재 | build B | 없음 | 없음 | precondition/collision 오류, 0-write |
| object 존재 | exact artifact | delete | delete | delete | 한 transaction, 새 object stamp 없음 |
| object 존재 | artifact 없음·drift | delete | 없음 | 없음 | `projection_artifact_delete_precondition_failed`, object 보존 |
| object 없음 | artifact 존재 | build/delete | 없음 | 없음 | `projection_artifact_orphan`, 0-write |
| 준비 뒤 object/source/config/root/artifact drift | 어떤 요청 | apply | 없음 | 없음 | `projection_artifact_snapshot_changed`, 0-write |

일반 build는 수동 수정 파일을 덮어쓰거나 지우지 않는다. 누락 artifact만 엔진이 저장 객체 또는 현재
reviewed source에서 다시 만든 exact bytes로 복구한다. locator A→B와 object delete는 A가 저장 hash와
정확히 맞을 때만 허용한다.

## 4. journal과 recovery

brain corpus lock이 유일한 조정 lock이다. apply와 recovery는 다음 순서를 고정한다.

1. brain corpus lock을 잡는다.
2. brain root를 path·device·inode가 같은 open directory handle로 pin한다.
3. consumer root를 두 번째 open directory handle로 pin한다.
4. 준비본의 config·root·object·source·artifact snapshot과 같은 filesystem을 다시 확인한다.
5. brain root의 `.brain-local/transactions/<transaction-id>/`에 journal을 create-only로 만든다.

consumer 전용 두 번째 lock은 만들지 않는다. root pin과 before hash precondition으로 외부 수정을
탐지하며, 모든 Project Brain artifact writer가 brain corpus lock을 사용한다.

manifest top-level exact key는 다음과 같다.

```text
version, transaction_id, operation, prepared_config, root_bindings,
object_actions, artifact_actions, before_corpus_fingerprint,
sealed_identity_sha256, phase, applied_actions
```

각 action은 `root=brain|consumer`, bound-root-relative path, before 존재 여부와 bytes SHA, after 존재
여부와 bytes SHA를 가진다. manifest에는 절대 apply path를 저장하지 않는다. transaction ID와 sealed
identity는 config·두 root selector·모든 action을 결속한다.

apply 순서는 journal·manifest fsync → before bytes backup → temp write+fsync → object actions → artifact
actions → 두 root directory fsync → committed phase 기록이다. 어느 단계에서든 실패하면
`applied_actions` 역순으로 두 root를 복구하고 recovery 완료를 fsync한다. 같은 filesystem이므로
consumer artifact의 before bytes도 brain-root journal과 atomic rename으로 이동·복원할 수 있다.

crash recovery는 현재 config로 consumer root를 다시 해석하지 않는다. journal에 결속된 path를 열어
기록된 device·inode와 비교하고 같은 root면 config가 없어졌거나 바뀌었어도 rollback/roll-forward를
끝낸다. bound root가 없거나 교체됐으면 journal을 삭제하거나 새 mutation을 시작하지 않고
`RECOVERY_REQUIRED`와 두 recorded root path를 보고한다. 사용자가 원래 root를 복구한 뒤 같은 brain
root로 다시 실행해야 한다.

준비 뒤 apply 전 config drift는 0-write 오류지만, partial apply 뒤 recovery에서는 config drift가
rollback을 막지 않는다. 이 둘을 같은 상태로 취급하지 않는다.

## 5. 효과·시각·receipt 소유자

- `build_context_projection()`은 reviewed source에서 object와 Markdown bytes를 만드는 순수 builder다.
- projection coordinator는 config/root/output 요청을 해석하고 evidence core에 object preparation을
  요청한다.
- `MutationService`만 corpus lock, 두 root pin, journal, apply, rollback/recovery를 소유한다.
- 설치 스킬, caller, 일반 `auxiliary_updates`, ID migration은 generated artifact를 쓰거나 지우지 않는다.

object create/update가 있을 때만 mutation clock을 정확히 한 번 호출해 `generated_at`과 object
`created_at`/`updated_at`에 같은 event time을 쓴다. artifact-only create는 object bytes·시각과 index를
보존한다. artifact에는 별도 시각을 넣지 않는다. object+artifact exact no-change에는 journal과 receipt가
없다.

`ProjectionArtifactTransactionReportV1`은 transaction ID, root binding SHA, object actions, artifact
actions, before/after corpus fingerprint, object mutation receipt ID 또는 null, artifact receipt ID 또는
null을 exact 결속한다. object bytes가 바뀔 때만 기존 mutation receipt와 index invalidation을 만들고,
artifact action이 있을 때는 별도 create-only artifact receipt를 만든다. artifact-only 누락 복구는
object receipt·index invalidation 없이 artifact receipt만 남긴다. report와 두 receipt는 같은 manifest
SHA를 가져 서로 다른 실행을 조합할 수 없다.

## 6. 완료 조건과 검증 연결

| 완료 조건 | 정확한 명령 | 기대 관측 |
|---|---|---|
| 1. 이름과 config/root/path 계약이 범위와 same-filesystem 경계를 fail-closed로 고정한다 | `.venv/bin/python -m pytest -q tests/test_projection_artifact_transaction.py -k 'config or root or path or filesystem or scope'` | 다섯 대상 구분, config 부재·불일치·symlink·root drift·cross-device·path escape가 journal 전 0-write |
| 2. 상태표가 create/update/no-change/missing/manual edit/delete/locator 이동/orphan·collision을 유일하게 정한다 | `.venv/bin/python -m pytest -q tests/test_projection_artifact_transaction.py -k 'create or update or no_change or missing or manual_edit or rename or delete or orphan or collision'` | 표의 object/artifact action과 object 시각 횟수가 exact 일치 |
| 3. 단일 lock·두 root pin·journal이 실패 주입과 crash recovery에서 전체를 되돌린다 | `.venv/bin/python -m pytest -q tests/test_projection_artifact_transaction.py tests/test_corpus_io.py -k 'rollback or recovery or failure_injection or root_pin'` | 각 apply 단계 실패 뒤 두 root 원복, config drift와 recovery root mismatch가 서로 다른 결과 |
| 4. public builder와 delete가 실제 reviewed source로 객체·Markdown을 함께 관리한다 | `.venv/bin/python -m pytest -q tests/test_cli.py tests/test_context_projection.py -k 'build_context or delete_context or prompt_payload'` | public create/update/delete·누락 복구 성공, source/projection hash 일치, prompt 경로 불변 |
| 5. report·receipt·lint·index가 artifact-only와 object mutation을 구분한다 | `.venv/bin/python -m pytest -q tests/test_lint.py tests/test_search_index.py tests/test_mutation.py tests/test_projection_artifact_transaction.py -k 'report or receipt or artifact_only or manual_edit or index'` | artifact-only는 object bytes/index 불변, object update만 invalidation, drift/orphan lint 실패 |
| 6. 설치와 전체 엔진 회귀가 고정 후보에서 함께 통과한다 | `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_installer.py && PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py' && PYTHONPATH=src .venv/bin/python -m pytest -q` | public 명령 설치와 두 번째 설치 무변경, runtime unittest와 전체 pytest 성공 |

독립 검증 묶음은 1) scope·root/path, 2) lifecycle·clock, 3) transaction recovery,
4) public·receipt·전체 회귀 네 개다.
