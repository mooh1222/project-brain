# Task 18 표시 제목·인용문 부채 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** legacy CodeLocator 3,305개와 짝 EvidenceRef 3,186개의 표시 제목만 현재 적재 규칙에 맞추고, quote 부채 3,307개를 재현 가능한 목록으로 고정하되 검색 색인과 기존 사용자 변경은 그대로 보존한다.

**Architecture:** 엔진은 표시 제목 closure, 독립 MutationService 검증, `display_migration` 전용 파생 파일 보존 거래, quote 부채 목록, Task 18 binding 생성·독립 검증을 제공한다. BB2는 영속 quote 부채 목록과 실코퍼스 check를 먼저 커밋하고, 모든 구현·설계·계획 문서와 inventory 커밋 뒤 새 snapshot과 final binding을 만든 다음 결속된 manifest 하나를 복구 가능한 거래로 적용한다. 적용 뒤에는 snapshot의 before image와 binding을 기준으로 실제 변경 집합·title-only·색인 바이트·사용자 dirt를 독립 검증한다. corpus commit을 포함한 snapshot과 독립 최종 리뷰가 통과한 뒤에만 완료 보고서를 커밋하고, 별도 closure receipt가 최종 두 HEAD와 모든 증빙을 결속한다.

**Tech Stack:** Python 3.12, pytest, unittest, project-brain CLI, Git plumbing, canonical JSON receipts

**Canonical Design:** [2026-08-06 Task 18 재설계](../specs/2026-08-06-task18-display-labels-and-quote-debt-redesign.md)

## Global Constraints

- 작업 레포는 engine `/Users/al03040455/Downloads/codes/project-brain`, 데이터 레포는 BB2 `/Users/al03040455/Desktop/bb2_client`, corpus root는 `/Users/al03040455/Desktop/bb2_client/brain`이다.
- 실행은 사용자가 지정한 현재 engine `main` checkout에서 한다. final binding이 현재 checkout의 사용자 dirt까지 묶어야 하므로 별도 engine worktree로 옮기지 않는다. SDD 기록만 이 계획 전용 ignored 경로 `.superpowers/sdd/2026-08-06-task18-display-labels-and-quote-debt/`에 둔다.
- 현재 target 복구 실행 기준은 engine `d4b746ad2a4b2f28f1935a9f3969f9b67ef2755d`, BB2 `979cc01bca7a76c96addcd7bc4dfe6f800be3c78`, local·remote develop `47fd83e3b10a21e1294ed00f9259bf356f9259da`다. 이 문서 커밋 때문에 engine HEAD는 달라지며 final binding은 실행 당시 최종 HEAD를 다시 결속한다.
- 재측정 정본은 `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-06/task18-remeasurement-current-develop/attempt-001/measurement.json`, SHA-256은 `f3f95505fd93a1e78c3ce225bbf2db984c090adebfc51c5598d0736d20a25834`다.
- 현재 예상치는 CodeLocator 3,305개 + EvidenceRef 3,186개 = UPDATE 6,491개, quote 부채 3,307개, 비정본 symbol 289개, paired mismatch 0/3,202다. final binding에서 수치가 다르면 자동으로 새 수치에 맞추지 말고 중단해 설계 차이를 기록한다.
- legacy quote 부채는 `reviewed at ingest, not mechanically re-checkable now`로 해석한다. “검증된 적 없음”, 신규 schema failure, 전체 code quote 검증 완료로 표현하지 않는다.
- quote, symbol, commit SHA, path, locator 좌표, lifecycle timestamp, 검색·라우터·임베딩 계약은 바꾸지 않는다. `index rebuild`와 finalizer를 실행하지 않는다.
- engine의 기존 사용자 dirt `docs/architecture/README.md`, `docs/design-canonical.md`와 기존 미추적 13개, BB2의 기존 dirty 12개를 삭제·원복·수정·스테이지하지 않는다. 특히 BB2 `brain/checks/test_real_corpus.py`는 수정하지 않는다.
- 옛 미추적 Task 18 문서 `docs/superpowers/plans/2026-08-04-task18-display-labels-and-quote-backlog.md`와 `docs/superpowers/specs/2026-08-04-task18-display-labels-and-quote-backlog-design.md`는 역사 자료로 보존하고 수정·스테이지하지 않는다.
- `git add -A`, `git add .`, `git commit -a`는 금지한다. 각 Task는 아래에 적은 소유 path만 스테이지하고 `git diff --cached --name-only`가 정확히 그 집합인지 확인한다.
- 각 Task를 dispatch하기 직전에 controller는 그 Task의 기존 `Modify` path가 모두 현재 HEAD와 같음을 `git diff --quiet HEAD --`와 정확한 path 목록으로 확인하고 HEAD blob SHA를 ledger에 기록한다. implementer가 끝난 뒤에는 그 시작 blob과 Task diff를 대조한다. 시작부터 dirty인 path나 Task 중 다른 주체가 바꾼 path가 하나라도 있으면 같은 파일 전체를 stage하지 말고 중단한다.
- 구현 Task는 순차 실행한다. Task마다 fresh implementer가 focused RED→GREEN과 자기 점검을 마치고 path-limited commit한 뒤, 별도 reviewer가 고정 candidate SHA의 설계 준수와 코드 품질을 모두 승인해야 다음 Task로 간다. 문서·운영 gate에는 억지 RED를 만들지 않는다.
- 최종 binding 전에는 실코퍼스 객체를 쓰지 않는다. quote 부채 JSON과 전용 check만 먼저 커밋할 수 있다. final binding 뒤에는 plan/verify-plan/apply가 쓰는 ignored control artifact 외 커밋이나 corpus write를 끼우지 않는다.
- 셸 상태는 명령 사이에 남지 않는다고 가정한다. Python은 항상 engine의 `.venv/bin/python`과 명시적 `PYTHONPATH=/Users/al03040455/Downloads/codes/project-brain/src`를 함께 쓴다.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `src/project_brain/display_contract.py` | canonical locator title, paired ref 포인터, title 제외 hash 같은 낮은 수준의 표시 계약 |
| `src/project_brain/quote_debt.py` | 범용·결정론적 quote 부채 목록 생성과 pre/post 검증 |
| `src/project_brain/task18_state.py` | cached path, local/remote ref, 안전한 파일 receipt 같은 낮은 수준의 상태 수집 |
| `src/project_brain/task18_binding.py` | final binding create-only 생성기 |
| `src/project_brain/task18_binding_verify.py` | 생성기와 별도로 현재 상태를 다시 계산하는 binding 검증기 |
| `src/project_brain/task18_verify.py` | 적용 뒤 exact changed set, title-only, 부채·색인·dirt 불변 검증 |
| `src/project_brain/migration.py` | paired display plan, display 전용 manifest v3, verify-plan/apply seam |
| `src/project_brain/mutation.py` | `DISPLAY_MIGRATION` exact closure와 write 종류 fail-closed 검증 |
| `src/project_brain/corpus_io.py` | 검증된 display title-only 거래에서만 파생 파일을 byte-for-byte 보존 |
| `src/project_brain/graph_viz.py` | CodeLocator 표시 label·tooltip과 30자 충돌 해소 |
| `src/project_brain/cli.py` | quote-debt, binding, display plan/verify-plan/apply/post-verify 명령 |
| `brain/recovery/2026-08-06/task18-display-and-quote-debt/legacy-quote-debt.json` | 실패한 attempt-001이 사용한 옛 quote 부채 정본. 역사 증빙으로 보존 |
| `brain/recovery/2026-08-06/task18-display-and-quote-debt/legacy-quote-debt-current-develop.json` | 현재 develop target에 다시 결속한 migration 전 quote 부채 정본 |
| `brain/checks/test_task18_quote_debt.py` | 현재 목록이 실코퍼스와 맞고 title migration 전후에도 유효한지 확인 |
| `.snapshots/2026-08-06/task18-execution/attempt-001/` | 실패한 snapshot, binding, manifest, receipt를 담은 역사 증빙. 삭제·덮어쓰기 금지 |
| `.snapshots/2026-08-06/task18-execution/attempt-002/` | engine cwd에서 eval 0/15로 실패한 snapshot, binding, manifest, verify receipt, pathspec 등 역사 증빙. 삭제·덮어쓰기 금지 |
| `.snapshots/2026-08-06/task18-execution/attempt-003/` | binding·독립 검증·plan·apply는 성공했지만 production post-verify에서 EvidenceRef 단독 target 검증 버그가 드러난 역사 증빙. v2 restore 성공. 삭제·덮어쓰기·재사용 금지 |
| `.snapshots/2026-08-06/task18-execution/attempt-004/` | 현재 실행의 snapshot, binding, manifest, verify receipt, pathspec 등 ignored control artifact |

### Task 0: 실행 기준선과 SDD 복구 기록을 고정한다

**Files:**
- Create: `.superpowers/sdd/2026-08-06-task18-display-labels-and-quote-debt/progress.md` (ignored)
- Read only: engine·BB2 Git 상태, measurement receipt, 승인된 설계와 이 계획

**Interfaces:**
- Produces: 이후 모든 Task가 비교할 final preflight 기록과 Task별 reviewer ledger

- [ ] **Step 1: 계획 전용 SDD workspace와 ledger를 만든다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
PLAN="$ENGINE/docs/superpowers/plans/2026-08-06-task18-display-labels-and-quote-debt.md"
/Users/al03040455/.codex/plugins/cache/superpowers-dev/superpowers/6.2.0/skills/subagent-driven-development/scripts/sdd-workspace "$PLAN"
```

첫 줄은 정확히 다음이어야 한다.

```text
# SDD ledger — plan: docs/superpowers/plans/2026-08-06-task18-display-labels-and-quote-debt.md
```

- [ ] **Step 2: 현재 HEAD·staged·remote와 측정 receipt를 다시 검증한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
git -C "$ENGINE" rev-parse HEAD
git -C "$BB2" rev-parse HEAD
git -C "$BB2" rev-parse refs/remotes/origin/develop^{commit}
git -C "$BB2" ls-remote --exit-code origin refs/heads/develop
git -C "$ENGINE" diff --cached --name-only
git -C "$BB2" diff --cached --name-only
shasum -a 256 "$BB2/.snapshots/2026-08-06/task18-remeasurement-current-develop/attempt-001/measurement.json"
```

Expected: 두 staged 목록은 비어 있고, measurement SHA와 local·remote develop은 Global Constraints의 값과 같다. 복구 계획 커밋 때문에 engine HEAD는 `d4b746ad2a4b2f28f1935a9f3969f9b67ef2755d`의 후속이어야 한다.

- [ ] **Step 3: 승인 설계와 이 계획이 실제 commit blob과 같은지 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
DESIGN_REL=docs/superpowers/specs/2026-08-06-task18-display-labels-and-quote-debt-redesign.md
PLAN_REL=docs/superpowers/plans/2026-08-06-task18-display-labels-and-quote-debt.md
git -C "$ENGINE" diff --quiet HEAD -- "$DESIGN_REL" "$PLAN_REL" ROADMAP.md
DESIGN_COMMIT=$(git -C "$ENGINE" log -1 --format=%H -- "$DESIGN_REL")
PLAN_COMMIT=$(git -C "$ENGINE" log -1 --format=%H -- "$PLAN_REL")
git -C "$ENGINE" merge-base --is-ancestor "$DESIGN_COMMIT" HEAD
git -C "$ENGINE" merge-base --is-ancestor "$PLAN_COMMIT" HEAD
test "$(git -C "$ENGINE" show "$DESIGN_COMMIT:$DESIGN_REL" | shasum -a 256 | awk '{print $1}')" = \
  "$(shasum -a 256 "$ENGINE/$DESIGN_REL" | awk '{print $1}')"
test "$(git -C "$ENGINE" show "$PLAN_COMMIT:$PLAN_REL" | shasum -a 256 | awk '{print $1}')" = \
  "$(shasum -a 256 "$ENGINE/$PLAN_REL" | awk '{print $1}')"
```

Expected: 모든 명령 exit 0. plan이 미추적이거나 design/plan working bytes가 commit blob과 다르면 Task 1을 시작하지 않는다.

- [ ] **Step 4: 모든 향후 Modify path의 시작 blob을 확인하고 ledger에 기록한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
cd "$ENGINE"
OWNED=(
  src/project_brain/migration.py src/project_brain/mutation.py
  src/project_brain/corpus_io.py src/project_brain/graph_viz.py
  src/project_brain/symbol_verify.py src/project_brain/foundation.py
  src/project_brain/snapshot.py src/project_brain/cli.py
  tests/test_migration.py tests/test_mutation.py tests/test_write_semantics.py
  tests/test_corpus_io.py tests/test_graph_viz.py tests/test_symbol_verify.py
  tests/test_surface.py tests/test_foundation.py tests/test_snapshot.py
  tests/test_cli.py tests/test_architecture_docs.py
  docs/architecture/runtime-map.md docs/architecture/change-map.md
  docs/architecture/data-contracts.md ROADMAP.md
)
git diff --quiet HEAD -- "${OWNED[@]}"
for path in "${OWNED[@]}"; do
  printf '%s %s\n' "$path" "$(git rev-parse "HEAD:$path")"
done
```

출력은 ledger의 `Task 0 owned baseline blobs` 아래에 저장한다. 각 Task는 자기 `Modify` 목록만 같은 방식으로 다시 캡처해 시작 HEAD와 함께 기록한다.

- [ ] **Step 5: 기존 사용자 dirt를 NUL-safe receipt로 캡처한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" - <<'PY'
from pathlib import Path
from project_brain.snapshot import capture_git_dirt_receipt
for label, root in (("engine", Path("/Users/al03040455/Downloads/codes/project-brain")),
                    ("bb2", Path("/Users/al03040455/Desktop/bb2_client"))):
    r = capture_git_dirt_receipt(root, label=f"task18_{label}_baseline")
    print(label, r.entry_count, r.status_sha256, r.content_manifest_sha256)
PY
```

Expected starting point: engine 15 entries, BB2 12 entries. 계획 커밋 뒤 engine entry 수가 달라졌다면 실제 목록을 기록하되 기존 사용자 소유 15개 내용이 보존됐는지 따로 확인한다.

- [ ] **Step 6: preflight contradiction scan을 마치고 ledger에 기록한다**

`Task 0: complete (preflight clean, no corpus write)`를 기록한다. 설계·계획 충돌, 다른 staged path, receipt drift가 있으면 구현을 시작하지 않는다.

커밋 없음.

### Task 1: paired display closure와 MutationService fail-closed 계약을 만든다

**Files:**
- Create: `src/project_brain/display_contract.py`
- Create: `tests/test_display_contract.py`
- Modify: `src/project_brain/migration.py:774-854`
- Modify: `src/project_brain/mutation.py:899-1160`
- Modify: `tests/test_migration.py:1004`
- Modify: `tests/test_mutation.py`
- Modify: `tests/test_write_semantics.py`

**Interfaces:**
- Produces: `canonical_locator_title(locator) -> str`, `paired_code_locator_id(obj) -> str | None`, `non_title_sha256(obj) -> str`, 내부 `plan_display_migration_unbound`가 반환하는 `MigrationPlan`, 정확한 CodeLocator+EvidenceRef display closure
- Consumes: `BrainStore`, `MutationOperation.DISPLAY_MIGRATION`, 기존 PRESERVE timestamp 정책

- [ ] **Step 1: closure와 거부 경계를 RED로 고정한다**

```python
def test_display_plan_builds_exact_locator_and_paired_evidence_ref_closure(display_store):
    plan = plan_display_migration_unbound(existing=display_store, **display_context())
    assert [(o["kind"], o["id"], o["title"]) for o in plan.mutation_plan.after_objects] == [
        ("CodeLocator", "locator.ctx.a", "Ns::run"),
        ("EvidenceRef", "evidence.ctx.a", "Ns::run"),
    ]

def test_display_migration_rejects_missing_extra_or_non_title_closure(display_request):
    for tamper in (drop_paired_ref, add_unpaired_ref, change_summary, rewrite_locator, add_delete):
        result = MutationService().preview(*tamper(display_request))
        assert result.ok is False
        assert result.error_code == "display_contract_invalid"

def test_display_migration_preserves_locator_and_evidence_ref_timestamps_exactly(display_store):
    result = MutationService(clock=lambda: "2099-01-01T00:00:00+09:00").plan(
        display_inputs(display_store), request=display_request(display_store)
    )
    assert lifecycle_fields(result.after_objects) == lifecycle_fields(display_inputs(display_store))
```

또한 unpaired, dangling, `ref_type != code_locator` EvidenceRef 제외와 `symbol`이 없을 때 `basename(path):anchor_key` 폴백을 별도 test case로 고정한다.

- [ ] **Step 2: focused RED를 확인한다**

```bash
.venv/bin/python -m pytest -q \
  tests/test_display_contract.py tests/test_migration.py \
  tests/test_mutation.py tests/test_write_semantics.py -k 'display'
```

Expected: paired EvidenceRef가 빠지고 임의 display request가 통과하는 이유로 FAIL.

- [ ] **Step 3: 낮은 수준 계약과 독립 서비스 검증을 구현한다**

```python
# src/project_brain/display_contract.py
def canonical_locator_title(locator: Mapping[str, object]) -> str:
    symbol = locator.get("symbol")
    if isinstance(symbol, str) and symbol:
        return symbol
    path = locator.get("path")
    basename = PurePosixPath(path).name if isinstance(path, str) and path else "unknown"
    object_id = locator.get("id")
    anchor_key = object_id.rsplit(".", 1)[-1] if isinstance(object_id, str) and object_id else "unknown"
    return f"{basename}:{anchor_key}"

def paired_code_locator_id(obj: Mapping[str, object]) -> str | None:
    if obj.get("kind") != "EvidenceRef" or obj.get("ref_type") != "code_locator":
        return None
    locator = obj.get("locator")
    if not isinstance(locator, Mapping):
        return None
    value = locator.get("code_locator_id")
    return value if isinstance(value, str) and value else None

def non_title_sha256(obj: Mapping[str, object]) -> str:
    payload = {key: value for key, value in obj.items() if key != "title"}
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()
```

planner는 전체 store에서 canonical title이 다른 CodeLocator와 실제 locator를 가리키며 title이 다른 EvidenceRef를 정렬해 한 closure로 만든다. MutationService는 planner의 결과를 신뢰하지 않고 `existing_by_id`에서 같은 closure를 다시 만들어 입력 ID, kind, precondition, before fingerprint, title-only after를 exact 비교한다. create/delete/rename/reference rewrite/auxiliary update가 하나라도 있으면 `display_contract_invalid`로 실패한다.

- [ ] **Step 4: focused GREEN과 기존 migration 회귀를 확인한다**

```bash
.venv/bin/python -m pytest -q \
  tests/test_display_contract.py tests/test_migration.py \
  tests/test_mutation.py tests/test_write_semantics.py
```

- [ ] **Step 5: 소유 path만 커밋하고 독립 리뷰를 통과한다**

```bash
git add -- \
  src/project_brain/display_contract.py src/project_brain/migration.py \
  src/project_brain/mutation.py tests/test_display_contract.py \
  tests/test_migration.py tests/test_mutation.py tests/test_write_semantics.py
git diff --cached --name-only
git commit -m "feat(brain): 표시 제목 짝 계약 강화"
```

### Task 2: display 거래에서만 index·stale 파일을 보존한다

**Files:**
- Modify: `src/project_brain/corpus_io.py:2648-2965,3508-4262`
- Modify: `src/project_brain/mutation.py:425-520`
- Modify: `tests/test_corpus_io.py`
- Modify: `tests/test_mutation.py`

**Interfaces:**
- Produces: `DerivedFilePolicy.INVALIDATE | PRESERVE`, `apply_transaction`의 기본 `derived_policy=INVALIDATE`
- Consumes: Task 1이 보증한 update-only CodeLocator/EvidenceRef title closure

- [ ] **Step 1: 바이트 보존·rollback·구 journal 호환을 RED로 고정한다**

```python
def test_display_migration_preserves_derived_files_byte_for_byte(display_transaction):
    before = derived_bytes(display_transaction.brain_root)
    display_transaction.apply()
    assert derived_bytes(display_transaction.brain_root) == before

def test_display_migration_failure_rolls_back_objects_and_preserves_derived_files(display_transaction):
    before_objects = object_bytes(display_transaction.brain_root)
    before_derived = derived_bytes(display_transaction.brain_root)
    with pytest.raises(RuntimeError):
        display_transaction.apply(failure_injector=raise_after_first_live_replace)
    recover_unfinished_transaction(display_transaction.brain_root)
    assert object_bytes(display_transaction.brain_root) == before_objects
    assert derived_bytes(display_transaction.brain_root) == before_derived

def test_preserve_policy_rejects_non_display_or_non_title_transactions(transaction_fixture):
    for manifest, after_files in transaction_fixture.invalid_preserve_cases():
        with pytest.raises((ValueError, CorpusIOError)):
            apply_transaction(
                transaction_fixture.brain_root,
                manifest=manifest,
                after_files=after_files,
                derived_policy=DerivedFilePolicy.PRESERVE,
            )

def test_legacy_journal_without_derived_policy_reads_as_invalidate(transaction_fixture):
    journal = transaction_fixture.legacy_v1_journal()
    _validate_journal_model(journal, journal["transaction_id"], legacy_manifest_read=True)
    assert normalized_derived_policy(journal) is DerivedFilePolicy.INVALIDATE

@pytest.mark.parametrize("failure_point", [
    "preparing_before_snapshots",
    "prepared",
    "committing_before_renames",
    "committing_after_first_before_rename",
    "committing_after_first_live_replace",
    "committing_after_derived_invalidation",
])
def test_unfinished_v1_journal_recovers_as_invalidate_after_upgrade(
    transaction_fixture, failure_point,
):
    transaction_fixture.install_unfinished_v1_journal(failure_point)
    recovered = recover_unfinished_transaction(transaction_fixture.brain_root)
    assert recovered.transaction_ids == (transaction_fixture.transaction_id,)
    assert object_bytes(transaction_fixture.brain_root) == transaction_fixture.before_objects
    assert derived_bytes(transaction_fixture.brain_root) == transaction_fixture.before_derived

@pytest.mark.parametrize("terminal_state", ["committed", "rolled_back"])
def test_terminal_v1_journal_remains_readable_after_upgrade(transaction_fixture, terminal_state):
    journal = transaction_fixture.terminal_v1_journal(terminal_state)
    _validate_journal_model(journal, journal["transaction_id"], legacy_manifest_read=True)
    assert normalized_derived_policy(journal) is DerivedFilePolicy.INVALIDATE
```

- [ ] **Step 2: focused RED를 확인한다**

```bash
.venv/bin/python -m pytest -q tests/test_corpus_io.py tests/test_mutation.py \
  -k 'derived and (display or preserve or legacy_journal)'
```

- [ ] **Step 3: journal policy와 low-level 방어를 구현한다**

```python
class DerivedFilePolicy(StrEnum):
    INVALIDATE = "invalidate"
    PRESERVE = "preserve"

def apply_transaction(
    brain_root: Path,
    *,
    manifest: Mapping[str, object],
    after_files: Mapping[str, bytes],
    derived_policy: DerivedFilePolicy = DerivedFilePolicy.INVALIDATE,
    failure_injector: Callable[[str], None] | None = None,
    preparation_injector: Callable[[str], None] | None = None,
) -> None:
    policy = DerivedFilePolicy(derived_policy)
    if policy is DerivedFilePolicy.PRESERVE:
        _validate_preserve_derived_request(brain_root, manifest, after_files)
    # 기존 transaction 본문은 policy를 journal에 기록하고 아래 검증값을 사용한다.
    expected_after_derived_fingerprint = (
        before_derived_fingerprint
        if policy is DerivedFilePolicy.PRESERVE
        else _empty_derived_fingerprint()
    )
```

`PRESERVE`는 manifest operation이 `display_migration`이고 기존 CodeLocator/EvidenceRef JSON의 update만 있으며 before/after에서 `title`만 다를 때만 허용한다. 새 journal은 version 2와 `derived_policy`를 기록하고 preserve일 때 `expected_after_derived_fingerprint == before_derived_fingerprint`로 두며 derived snapshot·이동·삭제·applied marker를 만들지 않는다. rollback, committed-state 검증, 재시작 recovery도 현재 derived fingerprint가 before와 같은지 확인한다. reader는 version 1의 원래 exact key/applied-marker 계약과 version 2의 새 exact 계약을 각각 분기해 검증하고, version 1은 PREPARING·PREPARED·COMMITTING·terminal 어느 상태든 invalidate로 복구한다. MutationService만 Task 1 검증을 통과한 `DISPLAY_MIGRATION`에 preserve를 넘긴다.

- [ ] **Step 4: focused GREEN과 기존 invalidate 회귀를 확인한다**

```bash
.venv/bin/python -m pytest -q tests/test_corpus_io.py tests/test_mutation.py
```

- [ ] **Step 5: 소유 path만 커밋하고 독립 리뷰를 통과한다**

```bash
git add -- src/project_brain/corpus_io.py src/project_brain/mutation.py \
  tests/test_corpus_io.py tests/test_mutation.py
git diff --cached --name-only
git commit -m "feat(brain): 표시 이행 색인 바이트 보존"
```

### Task 3: graph CodeLocator 표시를 충돌 없이 구분한다

**Files:**
- Modify: `src/project_brain/graph_viz.py:35-78`
- Modify: `tests/test_graph_viz.py`

**Interfaces:**
- Produces: CodeLocator label `anchor_key · symbol leaf`, symbol 없는 폴백 `basename(path):anchor_key`, symbol+path tooltip
- Consumes: 기존 30자 label 제한과 다른 kind 표시 규칙

- [ ] **Step 1: 같은 symbol과 긴 공통 prefix 충돌을 RED로 고정한다**

```python
def test_code_locator_labels_stay_unique_after_thirty_character_limit(store_with_long_locators):
    payload = build_payload(store_with_long_locators)
    labels = [n["label"] for n in payload["nodes"] if n["group"] == "CodeLocator"]
    assert len(labels) == len(set(labels))
    assert all(len(label) <= 30 for label in labels)

def test_code_locator_tooltip_contains_full_symbol_and_path(locator_store):
    node = only_locator_node(build_payload(locator_store))
    assert "Ns::Widget::run" in node["title"]
    assert "src/widget.cpp" in node["title"]
```

- [ ] **Step 2: RED를 확인한다**

```bash
.venv/bin/python -m pytest -q tests/test_graph_viz.py
```

- [ ] **Step 3: CodeLocator 전용 label과 결정론적 충돌 suffix를 구현한다**

같은 30자 candidate끼리 묶고 object id 순서의 `·1`, `·2` suffix를 붙이되 suffix 길이만큼 앞부분을 줄인다. collision group 밖 다른 kind는 기존 title 우선 규칙을 유지한다. details와 edges는 바꾸지 않는다.

- [ ] **Step 4: GREEN을 확인한다**

```bash
.venv/bin/python -m pytest -q tests/test_graph_viz.py
```

- [ ] **Step 5: 소유 path만 커밋하고 독립 리뷰를 통과한다**

```bash
git add -- src/project_brain/graph_viz.py tests/test_graph_viz.py
git diff --cached --name-only
git commit -m "feat(brain): 코드 그래프 라벨 구분"
```

### Task 4: quote 부채 목록 생성·검증 계약을 만든다

**Files:**
- Create: `src/project_brain/quote_debt.py`
- Create: `tests/test_quote_debt.py`
- Modify: `src/project_brain/symbol_verify.py:38`
- Modify: `tests/test_symbol_verify.py`
- Modify: `tests/test_surface.py`

**Interfaces:**
- Produces: `is_canonical_symbol_shape(symbol) -> bool`, `build_quote_debt_inventory`, phase가 필수인 `verify_quote_debt_inventory`
- Consumes: `foundation.canonical_receipt_bytes`, Task 1 title/hash primitives, explicit `stale_report`, measurement receipt

- [ ] **Step 1: 결정론·축 분류·pre/post 허용 범위를 RED로 고정한다**

```python
def test_quote_inventory_is_canonical_and_deterministic(quote_fixture):
    first = build_quote_debt_inventory(**quote_fixture, generated_at="2026-08-06T12:00:00+09:00")
    second = build_quote_debt_inventory(**quote_fixture, generated_at="2026-08-06T12:00:00+09:00")
    assert canonical_receipt_bytes(first) == canonical_receipt_bytes(second)
    assert [row["locator_id"] for row in first["rows"]] == sorted(first["quote_debt_ids"])

def test_quote_inventory_records_stale_unmerged_line_candidate_and_symbol_axes(quote_fixture):
    value = build_quote_debt_inventory(
        **quote_fixture, generated_at="2026-08-06T12:00:00+09:00"
    )
    by_id = {row["locator_id"]: row for row in value["rows"]}
    assert by_id["locator.ctx.stale"]["axes"]["stale"] is True
    assert by_id["locator.ctx.unmerged"]["axes"]["unmerged_or_unverifiable"] is True
    assert by_id["locator.ctx.lines"]["axes"]["line_range"] is True
    assert by_id["locator.ctx.candidate"]["axes"]["candidate"] is True
    assert by_id["locator.ctx.bad_symbol"]["axes"]["noncanonical_symbol"] is True

def test_quote_inventory_rejects_measurement_sha_or_id_set_mismatch(quote_fixture):
    with pytest.raises(QuoteDebtError, match="measurement"):
        build_quote_debt_inventory(**{
            **quote_fixture,
            "expected_measurement_sha256": "0" * 64,
            "generated_at": "2026-08-06T12:00:00+09:00",
        })

def test_post_migration_verify_allows_only_bound_title_changes(quote_fixture):
    value = build_quote_debt_inventory(
        **quote_fixture, generated_at="2026-08-06T12:00:00+09:00"
    )
    migrated = quote_fixture["existing"].with_titles(quote_fixture["expected_titles"])
    assert verify_quote_debt_inventory(
        value, existing=migrated, stale_report=quote_fixture["stale_report"],
        phase="post_migration", authorized_titles=quote_fixture["expected_titles"],
    )["ok"] is True

def test_code_locator_title_change_does_not_change_surface_or_hash(locator):
    before_store = BrainStore({locator["id"]: locator})
    changed = {**locator, "title": "canonical"}
    after_store = BrainStore({changed["id"]: changed})
    assert extract_surface(locator, before_store) == extract_surface(changed, after_store)
    assert content_hash(locator, before_store) == content_hash(changed, after_store)
```

- [ ] **Step 2: RED를 확인한다**

```bash
.venv/bin/python -m pytest -q \
  tests/test_quote_debt.py tests/test_symbol_verify.py tests/test_surface.py
```

- [ ] **Step 3: 범용 inventory builder와 두 phase verifier를 구현한다**

```python
def build_quote_debt_inventory(
    existing: BrainStore,
    *,
    measurement_path: Path,
    expected_measurement_sha256: str,
    stale_report: Mapping[str, object],
    engine_sha: str,
    repo_sha: str,
    target_revision_sha: str,
    brain_root: Path,
    index_db_path: Path,
    generated_at: str,
) -> dict[str, object]:
    measurement = read_and_verify_measurement(
        measurement_path, expected_measurement_sha256
    )
    rows = build_sorted_quote_debt_rows(existing, stale_report=stale_report)
    verify_measurement_id_sets(measurement, rows)
    return canonical_inventory_value(
        rows=rows,
        engine_sha=engine_sha,
        repo_sha=repo_sha,
        target_revision_sha=target_revision_sha,
        brain_root=brain_root,
        index_db_path=index_db_path,
        measurement_path=measurement_path,
        measurement_sha256=expected_measurement_sha256,
        generated_at=generated_at,
    )

def verify_quote_debt_inventory(
    value: Mapping[str, object],
    *,
    existing: BrainStore,
    stale_report: Mapping[str, object],
    phase: Literal["pre_migration", "post_migration"],
    authorized_titles: Mapping[str, str] | None = None,
) -> dict[str, object]:
    current = build_current_debt_projection(existing, stale_report=stale_report)
    if phase == "pre_migration" and authorized_titles is not None:
        raise QuoteDebtError("pre_migration_does_not_accept_authorization")
    if phase == "post_migration" and authorized_titles is None:
        raise QuoteDebtError("post_migration_requires_authorized_titles")
    assert_inventory_matches_projection(
        value, current, phase=phase, authorized_titles=authorized_titles,
    )
    return inventory_verification_receipt(value, phase=phase)
```

row는 locator의 migration 전 title과 non-title hash, 유효하게 연결된 `paired_refs: []`의 id/title/non-title hash, context/path/symbol/commit/status/source와 다섯 부채 축을 담는다. `paired_refs`는 일반 엔진에서 1:N을 허용하되 실제 locator id를 정확히 가리키는 ref만 포함한다. stale-set 캐시를 원본으로 쓰지 않고 `stale_check`에 exact `target_head`와 `fetch=False`를 넘긴 결과를 전달한다. `verify_code_quotes`는 quote가 있는 객체에만 쓰며 부채 3,307개 전체 검증으로 확대하지 않는다.

- [ ] **Step 4: GREEN을 확인한다**

```bash
.venv/bin/python -m pytest -q \
  tests/test_quote_debt.py tests/test_symbol_verify.py tests/test_surface.py
```

- [ ] **Step 5: 소유 path만 커밋하고 독립 리뷰를 통과한다**

```bash
git add -- src/project_brain/quote_debt.py src/project_brain/symbol_verify.py \
  tests/test_quote_debt.py tests/test_symbol_verify.py tests/test_surface.py
git diff --cached --name-only
git commit -m "feat(brain): 기존 인용문 부채 계약 추가"
```

### Task 5: final binding용 낮은 수준 상태 receipt를 공개한다

**Files:**
- Create: `src/project_brain/task18_state.py`
- Create: `tests/test_task18_state.py`
- Modify: `src/project_brain/foundation.py:540-740`
- Modify: `src/project_brain/snapshot.py:899-1370`
- Modify: `tests/test_foundation.py`
- Modify: `tests/test_snapshot.py`

**Interfaces:**
- Produces: NUL-safe cached paths, local/remote ref SHA, no-follow regular-file receipt, corpus/index/stale receipt
- Consumes: `capture_git_dirt_receipt`, `canonical_receipt_bytes`, 기존 root identity와 snapshot safe-read 구현

- [ ] **Step 1: staged·remote·symlink drift를 RED로 고정한다**

```python
def test_capture_cached_paths_is_nul_safe_and_sorted(git_repo):
    git_repo.stage("name with newline\ninside.json", b"payload")
    assert capture_cached_paths(git_repo.root) == ("name with newline\ninside.json",)

def test_capture_remote_ref_requires_local_and_ls_remote_exact_match(git_remote):
    receipt = capture_remote_ref(
        git_remote.root, local_ref="refs/remotes/origin/develop",
        remote="origin", remote_ref="refs/heads/develop",
    )
    assert receipt.local_sha == receipt.remote_sha == git_remote.develop_sha

def test_read_bound_file_rejects_symlink_leaf_or_parent(tmp_path):
    target = tmp_path / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    (tmp_path / "link.json").symlink_to(target)
    with pytest.raises(Task18StateError):
        capture_bound_file(tmp_path / "link.json")

def test_capture_task18_corpus_state_includes_objects_raw_index_and_stale(brain_root):
    state = capture_task18_corpus_state(brain_root)
    assert set(state) == {"corpus", "search_index", "stale_set"}
    assert state["search_index"]["live_corpus_fingerprint"] == state["search_index"]["meta_corpus_fingerprint"]

def test_capture_committed_input_rejects_dirty_or_non_ancestor_bytes(git_repo):
    committed = git_repo.commit_file("docs/plan.md", b"committed\n")
    git_repo.write("docs/plan.md", b"dirty\n")
    with pytest.raises(Task18StateError, match="committed_input"):
        capture_committed_input(git_repo.root, Path("docs/plan.md"), committed)
```

- [ ] **Step 2: RED를 확인한다**

```bash
.venv/bin/python -m pytest -q \
  tests/test_task18_state.py tests/test_foundation.py tests/test_snapshot.py
```

- [ ] **Step 3: high-level binding collector 없이 primitive만 구현한다**

```python
@dataclass(frozen=True)
class RemoteRefReceipt:
    local_ref: str
    local_sha: str
    remote: str
    remote_ref: str
    remote_sha: str

def capture_cached_paths(root: Path) -> tuple[str, ...]:
    payload = run_git_bytes(root, "diff", "--cached", "--name-only", "-z")
    return tuple(sorted(decode_nul_paths(payload)))

def capture_remote_ref(root: Path, *, local_ref: str, remote: str, remote_ref: str) -> RemoteRefReceipt:
    local_sha = resolve_exact_commit(root, local_ref)
    remote_sha = ls_remote_exact_commit(root, remote, remote_ref)
    if local_sha != remote_sha:
        raise Task18StateError("remote_ref_mismatch")
    return RemoteRefReceipt(local_ref, local_sha, remote, remote_ref, remote_sha)

def capture_bound_file(path: Path) -> Mapping[str, object]:
    data, mode = read_regular_no_follow(path)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "mode": mode}

def capture_task18_corpus_state(brain_root: Path) -> Mapping[str, object]:
    corpus = capture_corpus_receipt(brain_root)
    index = capture_search_index_receipt(brain_root)
    stale = capture_stale_set_receipt(brain_root)
    return {"corpus": corpus, "search_index": index, "stale_set": stale}

def capture_committed_input(root: Path, relative_path: Path, commit_sha: str) -> Mapping[str, object]:
    require_commit_is_ancestor(root, commit_sha, "HEAD")
    committed_bytes = git_show_blob(root, commit_sha, relative_path)
    working_bytes, mode = read_regular_no_follow(root / relative_path)
    if committed_bytes != working_bytes:
        raise Task18StateError("committed_input_bytes_mismatch")
    return {
        "path": str((root / relative_path).resolve()),
        "commit_sha": commit_sha,
        "file_sha256": hashlib.sha256(working_bytes).hexdigest(),
        "mode": mode,
    }
```

`capture_task18_corpus_state`는 objects/raw tree, corpus mutation fingerprint, live/meta search fingerprint, index DB SHA, stale-set SHA만 계산한다. engine/BB2/git/inputs를 한 번에 모으는 shared collector는 만들지 않는다. binding 생성기와 검증기가 이 primitive를 호출하는 순서와 expected 비교는 각자 구현한다.

- [ ] **Step 4: GREEN을 확인한다**

```bash
.venv/bin/python -m pytest -q \
  tests/test_task18_state.py tests/test_foundation.py tests/test_snapshot.py
```

- [ ] **Step 5: 소유 path만 커밋하고 독립 리뷰를 통과한다**

```bash
git add -- src/project_brain/task18_state.py src/project_brain/foundation.py \
  src/project_brain/snapshot.py tests/test_task18_state.py \
  tests/test_foundation.py tests/test_snapshot.py
git diff --cached --name-only
git commit -m "feat(brain): Task 18 상태 결속 기반 추가"
```

### Task 6: Task 18 final binding 생성기와 독립 검증기를 만든다

**Files:**
- Create: `src/project_brain/task18_binding.py`
- Create: `src/project_brain/task18_binding_verify.py`
- Create: `tests/test_task18_binding.py`
- Create: `tests/test_task18_binding_verify.py`

**Interfaces:**
- Produces: `Task18BindingRequest`, `create_task18_binding`, `Task18BindingVerification`, `verify_task18_binding`
- Consumes: Task 1 표시 primitive, Task 4 inventory, Task 5 상태 primitive, `atomic_create_receipt`, `verify_snapshot`

- [ ] **Step 1: create-only·독립 drift 검증을 RED로 고정한다**

```python
def test_create_task18_binding_records_exact_inputs_and_display_closure(task18_fixture):
    result = create_task18_binding(task18_fixture.request, clock=fixed_clock)
    assert result.value["task18_allowed"] is True
    assert result.value["migration"]["total_count"] == 2
    assert result.value["migration"]["targets"][1]["kind"] == "EvidenceRef"

@pytest.mark.parametrize("drift", [
    drift_engine_head, drift_bb2_dirt, add_cached_path, drift_remote_ref,
    drift_inventory, drift_snapshot, drift_index_bytes, drop_display_target,
])
def test_verify_task18_binding_rejects_each_bound_state_drift(task18_binding, drift):
    drift()
    with pytest.raises(Task18BindingError):
        verify_task18_binding(**task18_binding.verify_args)

def test_create_binding_rejects_live_closure_that_differs_from_measurement(task18_fixture):
    for drift in (
        task18_fixture.drop_measured_locator,
        task18_fixture.add_unmeasured_locator,
        task18_fixture.change_pair_row,
        task18_fixture.change_quote_debt_ids,
    ):
        drift()
        with pytest.raises(Task18BindingError, match="measurement_closure_mismatch"):
            create_task18_binding(task18_fixture.request, clock=fixed_clock)
        task18_fixture.restore()

def test_create_and_verify_reject_target_path_overlapping_baseline_user_dirt(task18_fixture):
    task18_fixture.make_one_display_target_dirty_before_binding()
    with pytest.raises(Task18BindingError, match="target_overlaps_user_dirt"):
        create_task18_binding(task18_fixture.request, clock=fixed_clock)
```

- [ ] **Step 2: RED를 확인한다**

```bash
.venv/bin/python -m pytest -q \
  tests/test_task18_binding.py tests/test_task18_binding_verify.py
```

- [ ] **Step 3: exact schema와 별도 generator/verifier를 구현한다**

```python
@dataclass(frozen=True)
class Task18BindingRequest:
    binding_path: Path
    engine_root: Path
    repo_root: Path
    brain_root: Path
    expected_engine_head: str
    expected_repo_head: str
    expected_engine_status_sha256: str
    expected_engine_dirt_content_sha256: str
    expected_repo_status_sha256: str
    expected_repo_dirt_content_sha256: str
    local_target_ref: str
    remote: str
    remote_target_ref: str
    target_revision_sha: str
    p0_handoff_path: Path
    expected_p0_handoff_sha256: str
    measurement_path: Path
    expected_measurement_sha256: str
    design_path: Path
    design_commit_sha: str
    expected_design_file_sha256: str
    plan_path: Path
    plan_commit_sha: str
    expected_plan_file_sha256: str
    quote_debt_path: Path
    expected_quote_debt_sha256: str
    snapshot_root: Path
    expected_snapshot_manifest_sha256: str
    snapshot_verify_receipt_path: Path
    expected_snapshot_verify_receipt_sha256: str

TASK18_BINDING_KEYS = {
    "version", "purpose", "created_at", "task18_allowed", "roots",
    "engine", "bb2", "target_revision", "corpus", "search_index",
    "stale_set", "inputs", "pre_mutation_snapshot", "migration",
}

@dataclass(frozen=True)
class Task18BindingCreateResult:
    path: Path
    sha256: str
    value: Mapping[str, object]

@dataclass(frozen=True)
class Task18BindingVerification:
    path: str
    sha256: str
    task18_allowed: bool
    snapshot_root: Path
    snapshot_manifest_sha256: str
    migration_targets: tuple[Mapping[str, object], ...]

def create_task18_binding(
    request: Task18BindingRequest,
    *,
    clock: Callable[[], str] = now_kst,
) -> Task18BindingCreateResult:
    assert_request_paths_are_exact_absolute(request)
    actual = collect_generator_state_in_generator_order(request)
    assert_actual_matches_caller_expectations(actual, request)
    assert_live_closure_matches_measurement_exactly(
        actual.display_closure,
        measurement=actual.measurement,
        required_locator_count=3305,
        required_evidence_ref_count=3186,
    )
    capture_committed_input(
        request.engine_root,
        request.design_path.relative_to(request.engine_root),
        request.design_commit_sha,
    )
    capture_committed_input(
        request.engine_root,
        request.plan_path.relative_to(request.engine_root),
        request.plan_commit_sha,
    )
    value = build_binding_value(actual, created_at=clock())
    if set(value) != TASK18_BINDING_KEYS or value["task18_allowed"] is not True:
        raise Task18BindingError("binding_schema_invalid")
    binding_sha256 = atomic_create_receipt(request.binding_path, value)
    return Task18BindingCreateResult(request.binding_path, binding_sha256, value)

def verify_task18_binding(
    *,
    binding_path: Path,
    expected_binding_sha256: str,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
) -> Task18BindingVerification:
    binding_bytes = read_bound_bytes_before_json(binding_path)
    if hashlib.sha256(binding_bytes).hexdigest() != expected_binding_sha256:
        raise Task18BindingError("binding_sha256_mismatch")
    value = parse_exact_binding_schema(binding_bytes, TASK18_BINDING_KEYS)
    actual = collect_verifier_state_in_independent_order(
        engine_root=engine_root, repo_root=repo_root, brain_root=brain_root,
    )
    assert_binding_matches_current_state(value, actual)
    snapshot = value["pre_mutation_snapshot"]
    migration = value["migration"]
    return Task18BindingVerification(
        path=str(binding_path),
        sha256=expected_binding_sha256,
        task18_allowed=True,
        snapshot_root=Path(snapshot["path"]),
        snapshot_manifest_sha256=str(snapshot["manifest_sha256"]),
        migration_targets=tuple(migration["targets"]),
    )
```

schema는 `version`, `purpose`, `created_at`, `task18_allowed`, roots, engine/BB2 HEAD·status bytes base64·dirt manifest/hash·cached paths, local/remote develop, corpus/index/stale, P0/measurement/design/plan/quote inputs, pre-mutation snapshot, sorted migration targets를 exact key 집합으로 검증한다. engine과 BB2 cached paths는 모두 비어 있어야 한다. target row는 `id`, `kind`, `paired_locator_id`, `before_object_sha256`, `before_non_title_sha256`, `expected_title`을 가진다. migration summary는 `target_ids_sha256`, `targets_sha256`, `code_locator_count`, `evidence_ref_count`, `total_count`, `before_corpus_fingerprint`, `expected_after_corpus_fingerprint`를 가진다. 생성기와 검증기는 migration target의 실제 BB2 object relative path 집합이 binding 전 dirt manifest path 집합과 완전히 분리됐는지 각각 확인한다. 하나라도 겹치면 기존 사용자 변경을 corpus commit에 흡수할 수 있으므로 `target_overlaps_user_dirt`로 실패한다. 생성기는 caller expected 값과 현재 값을 먼저 비교하고, live locator target IDs/count/hash가 measurement `display_labels`와 같고 live pair rows hash가 measurement `evidence_ref_pairs.pair_rows_sha256`와 같으며 quote debt IDs/hash가 measurement와 committed inventory 양쪽에 같을 때만 3,305/3,186/6,491 closure를 결속한다. design/plan은 지정 commit이 현재 HEAD의 조상이고 `git show`로 읽은 그 commit의 해당 파일 bytes가 working-tree bytes와 같아야 한다. 그 뒤에만 `atomic_create_receipt`로 쓴다. 검증기도 같은 관계를 별도 순회로 다시 증명하며 binding 파일 SHA를 JSON parse보다 먼저 확인하고 생성기의 payload builder를 호출하지 않는다.

- [ ] **Step 4: GREEN을 확인한다**

```bash
.venv/bin/python -m pytest -q \
  tests/test_task18_binding.py tests/test_task18_binding_verify.py
```

- [ ] **Step 5: 소유 path만 커밋하고 독립 리뷰를 통과한다**

```bash
git add -- src/project_brain/task18_binding.py \
  src/project_brain/task18_binding_verify.py \
  tests/test_task18_binding.py tests/test_task18_binding_verify.py
git diff --cached --name-only
git commit -m "feat(brain): Task 18 최종 결속 추가"
```

### Task 7: display manifest v3를 final binding에 묶고 snapshot-only 우회를 닫는다

**Files:**
- Modify: `src/project_brain/migration.py:797-1015`
- Modify: `tests/test_migration.py`

**Interfaces:**
- Produces: `create_display_migration_artifact`, `verify_display_migration_artifact`, `apply_display_migration_artifact`
- Consumes: Task 6 `verify_task18_binding`, Task 1 paired plan, 기존 ID migration artifact v2

- [ ] **Step 1: binding 필수·live replan·generic 우회 차단을 RED로 고정한다**

```python
def test_display_artifact_records_exact_task18_binding_path_and_sha(bound_display_plan):
    artifact = create_display_migration_artifact(bound_display_plan)
    assert artifact.manifest["task18_binding_path"] == str(bound_display_plan.binding_path)
    assert artifact.manifest["task18_binding_sha256"] == bound_display_plan.binding_sha256

def test_display_verify_plan_reverifies_binding_snapshot_and_live_plan(bound_display_artifact):
    result = verify_display_migration_artifact(**bound_display_artifact.verify_args)
    assert result.ok is True
    bound_display_artifact.drift_live_title()
    with pytest.raises(MigrationError, match="revalidation"):
        verify_display_migration_artifact(**bound_display_artifact.verify_args)

def test_display_apply_reverifies_binding_before_mutation(bound_display_artifact):
    bound_display_artifact.drift_engine_status()
    with pytest.raises(Task18BindingError):
        apply_display_migration_artifact(**bound_display_artifact.apply_args)
    assert bound_display_artifact.object_bytes_unchanged()

def test_generic_apply_rejects_display_artifact_without_task18_binding(bound_display_artifact):
    with pytest.raises(MigrationError, match="display artifact requires"):
        apply_migration_artifact(**bound_display_artifact.generic_apply_args)
```

- [ ] **Step 2: RED를 확인한다**

```bash
.venv/bin/python -m pytest -q tests/test_migration.py -k 'display'
```

- [ ] **Step 3: display 전용 v3 seam을 구현한다**

```python
DISPLAY_ARTIFACT_KEYS = {
    "migration_version", "migration_kind", "intent", "snapshot_id",
    "snapshot_manifest_sha256", "task18_binding_path", "task18_binding_sha256",
}

@dataclass(frozen=True)
class MigrationArtifactVerification:
    ok: bool
    artifact: Mapping[str, object]
    plan: MigrationPlan

def plan_display_migration(
    *,
    existing: BrainStore,
    brain_root: Path,
    repo_root: Path,
    engine_root: Path,
    task18_binding_path: Path,
    expected_task18_binding_sha256: str,
) -> MigrationPlan:
    binding = verify_task18_binding(
        binding_path=task18_binding_path,
        expected_binding_sha256=expected_task18_binding_sha256,
        engine_root=engine_root, repo_root=repo_root, brain_root=brain_root,
    )
    if str(task18_binding_path) != binding.path or not binding.task18_allowed:
        raise MigrationError("task18_binding_mismatch")
    return build_bound_display_plan(existing=existing, binding=binding)

def verify_display_migration_artifact(
    *,
    manifest_bytes: bytes,
    expected_manifest_sha256: str,
    task18_binding_path: Path,
    expected_task18_binding_sha256: str,
    brain_root: Path,
    repo_root: Path,
    engine_root: Path,
) -> MigrationArtifactVerification:
    artifact = parse_display_v3_after_sha_check(manifest_bytes, expected_manifest_sha256)
    if set(artifact) != DISPLAY_ARTIFACT_KEYS:
        raise MigrationError("display_manifest_invalid")
    binding = verify_task18_binding(
        binding_path=task18_binding_path,
        expected_binding_sha256=expected_task18_binding_sha256,
        engine_root=engine_root, repo_root=repo_root, brain_root=brain_root,
    )
    assert_manifest_binding_matches_caller(artifact, binding)
    verify_bound_snapshot(binding)
    replanned = build_bound_display_plan(existing=BrainStore.load(brain_root), binding=binding)
    if create_display_migration_artifact(replanned).manifest_bytes != manifest_bytes:
        raise MigrationError("manifest_revalidation_failed")
    return MigrationArtifactVerification(ok=True, artifact=artifact, plan=replanned)

def apply_display_migration_artifact(
    *,
    manifest_bytes: bytes,
    expected_manifest_sha256: str,
    task18_binding_path: Path,
    expected_task18_binding_sha256: str,
    brain_root: Path,
    repo_root: Path,
    engine_root: Path,
) -> MigrationApplyResult:
    verified = verify_display_migration_artifact(
        manifest_bytes=manifest_bytes,
        expected_manifest_sha256=expected_manifest_sha256,
        task18_binding_path=task18_binding_path,
        expected_task18_binding_sha256=expected_task18_binding_sha256,
        brain_root=brain_root, repo_root=repo_root, engine_root=engine_root,
    )
    intent = verified.artifact["intent"]
    intent_bytes = _canonical_json_bytes(intent)
    result = MutationService().apply_bound_intent(
        request=verified.plan.request,
        artifact_intent=intent,
        expected_intent_sha256=hashlib.sha256(intent_bytes).hexdigest(),
    )
    if not result.ok or result.manifest is None:
        raise MigrationError(result.error_code or "mutation_apply_failed")
    action_count = sum(len(rows) for rows in (
        result.manifest.creates, result.manifest.updates, result.manifest.deletes,
        result.manifest.renames, result.manifest.auxiliary_updates,
    ))
    return MigrationApplyResult(
        transaction_id=result.manifest.transaction_id,
        action_count=action_count,
        snapshot_id=verified.plan.snapshot_id,
    )
```

display manifest v3는 `task18_binding_path`, `task18_binding_sha256`, snapshot id/SHA, intent를 exact key로 가진다. 순서는 manifest bytes SHA → caller binding path/SHA → manifest binding exact match → fresh `verify_task18_binding` → snapshot verify → live replan → manifest bytes exact 비교다. apply는 verify-plan의 과거 PASS를 받지 않고 같은 검증을 다시 실행한 뒤 `MutationService.apply_bound_intent`를 호출한다. 기존 `apply_migration_artifact`와 v2 parser는 ID migration만 받고 display artifact를 명시적으로 거부한다.

- [ ] **Step 4: GREEN과 ID migration 회귀를 확인한다**

```bash
.venv/bin/python -m pytest -q tests/test_migration.py
```

- [ ] **Step 5: 소유 path만 커밋하고 독립 리뷰를 통과한다**

```bash
git add -- src/project_brain/migration.py tests/test_migration.py
git diff --cached --name-only
git commit -m "feat(brain): 표시 이행을 최종 결속에 연결"
```

### Task 8: CLI·post verifier·architecture 문서를 연결한다

**Files:**
- Create: `src/project_brain/task18_verify.py`
- Create: `tests/test_task18_verify.py`
- Modify: `src/project_brain/cli.py:2296-2550`
- Modify: `tests/test_cli.py:3952`
- Modify: `docs/architecture/runtime-map.md`
- Modify: `docs/architecture/change-map.md`
- Modify: `docs/architecture/data-contracts.md`
- Modify: `tests/test_architecture_docs.py`

**Interfaces:**
- Produces: CLI `migration quote-debt build|verify`, `migration display binding-create|binding-verify|plan|verify-plan|apply|post-verify|closure-create|closure-verify`; 모든 Task 18 report는 required `--report`에 create-only 저장
- Consumes: Tasks 4, 6, 7 public seams; Task 6 binding의 before hashes와 snapshot

- [ ] **Step 1: CLI 필수 옵션과 post 검증을 RED로 고정한다**

```python
def test_display_plan_and_apply_require_absolute_binding_and_expected_sha(cli_runner):
    for action in ("plan", "verify-plan", "apply"):
        result = cli_runner("migration", "display", action, "--brain-root", "/tmp/brain")
        assert result.exit_code == 2
        assert "--task18-binding" in result.stderr
        assert "--expected-task18-binding-sha256" in result.stderr

def test_generic_apply_cannot_dispatch_display_manifest(cli_runner, display_manifest):
    result = cli_runner("migration", "id", "apply", "--manifest", str(display_manifest))
    assert result.exit_code == 1
    assert "display artifact requires" in result.stdout

def test_task18_cli_refuses_to_overwrite_existing_report(cli_runner, existing_report):
    result = cli_runner(
        "migration", "display", "binding-verify",
        "--report", str(existing_report),
        *complete_binding_verify_args(),
    )
    assert result.exit_code == 1
    assert "report_exists" in result.stdout

def test_post_verify_rejects_missing_extra_or_non_title_object_change(task18_post_fixture):
    task18_post_fixture.change_summary_on_one_target()
    with pytest.raises(Task18VerificationError, match="non-title"):
        verify_task18_applied(**task18_post_fixture.args)

def test_post_verify_preserves_quote_symbol_index_and_user_dirt(task18_post_fixture):
    result = verify_task18_applied(**task18_post_fixture.args)
    assert result.quote_debt_unchanged is True
    assert result.noncanonical_symbols_unchanged is True
    assert result.index_db_unchanged is True
    assert result.user_dirt_preserved is True

def test_post_authorization_requires_exact_binding_sha_and_returns_only_bound_titles(
    task18_post_fixture,
):
    value = load_task18_post_authorization(**task18_post_fixture.authorization_args)
    assert value.expected_titles == task18_post_fixture.bound_titles
    assert value.target_ids_sha256 == task18_post_fixture.target_ids_sha256

def test_closure_receipt_binds_reviewed_snapshot_final_heads_and_committed_docs(
    task18_closure_fixture,
):
    receipt = create_task18_closure_receipt(**task18_closure_fixture.create_args)
    assert verify_task18_closure_receipt(
        **task18_closure_fixture.verify_args(receipt)
    ).ok is True
    task18_closure_fixture.drift_completion_report()
    with pytest.raises(Task18VerificationError, match="committed_docs"):
        verify_task18_closure_receipt(**task18_closure_fixture.verify_args(receipt))
```

- [ ] **Step 2: RED를 확인한다**

```bash
.venv/bin/python -m pytest -q \
  tests/test_cli.py tests/test_task18_verify.py tests/test_architecture_docs.py \
  -k 'task18 or display or quote_debt or architecture'
```

- [ ] **Step 3: CLI action과 적용 뒤 검증기를 구현한다**

```python
@dataclass(frozen=True)
class Task18PostVerification:
    update_count: int
    quote_debt_unchanged: bool
    noncanonical_symbols_unchanged: bool
    index_db_unchanged: bool
    user_dirt_preserved: bool
    report_path: Path
    report_sha256: str

@dataclass(frozen=True)
class Task18PostAuthorization:
    binding_path: Path
    binding_sha256: str
    expected_titles: Mapping[str, str]
    target_ids_sha256: str

def load_task18_post_authorization(
    *,
    binding_path: Path,
    expected_binding_sha256: str,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
) -> Task18PostAuthorization:
    binding = parse_task18_binding_for_post_verify(
        binding_path=binding_path,
        expected_binding_sha256=expected_binding_sha256,
        engine_root=engine_root, repo_root=repo_root, brain_root=brain_root,
    )
    return Task18PostAuthorization(
        binding_path=binding_path,
        binding_sha256=expected_binding_sha256,
        expected_titles={row.id: row.expected_title for row in binding.migration_targets},
        target_ids_sha256=binding.target_ids_sha256,
    )

def verify_task18_applied(
    *,
    binding_path: Path,
    expected_binding_sha256: str,
    manifest_path: Path,
    expected_manifest_sha256: str,
    quote_debt_path: Path,
    expected_quote_debt_sha256: str,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
    report_path: Path,
    pathspec_output: Path,
    generated_at: str,
) -> Task18PostVerification:
    binding = parse_task18_binding_for_post_verify(
        binding_path=binding_path,
        expected_binding_sha256=expected_binding_sha256,
        engine_root=engine_root, repo_root=repo_root, brain_root=brain_root,
    )
    manifest = read_display_manifest(manifest_path, expected_manifest_sha256)
    changed = compare_snapshot_before_to_live(binding.pre_mutation_snapshot, brain_root)
    assert_exact_target_paths_and_title_only(changed, binding.migration_targets, manifest)
    assert_quote_symbol_index_and_graph_invariants(
        binding=binding,
        quote_debt_path=quote_debt_path,
        expected_quote_debt_sha256=expected_quote_debt_sha256,
        brain_root=brain_root,
    )
    allowed = tuple(sorted(changed.paths | {str(report_path.relative_to(repo_root))}))
    verify_git_dirt_preserved(
        repo_root,
        baseline_status_bytes=binding.bb2_status_bytes,
        baseline_content_manifest_bytes=binding.bb2_dirt_manifest_bytes,
        label="task18_post_apply",
        allowed_extra_paths=allowed,
    )
    report_sha = atomic_create_receipt(report_path, build_post_report(binding, changed, generated_at))
    atomic_create_pathspec(pathspec_output, changed.paths)
    return Task18PostVerification(
        update_count=len(changed.paths),
        quote_debt_unchanged=True,
        noncanonical_symbols_unchanged=True,
        index_db_unchanged=True,
        user_dirt_preserved=True,
        report_path=report_path,
        report_sha256=report_sha,
    )
```

`parse_task18_binding_for_post_verify`는 binding file SHA·exact schema·roots·engine/BB2 HEAD·remote·입력 파일·snapshot을 다시 확인하되, binding이 허가한 target object 변화만 live corpus 차이로 허용한다. 정상 pre-apply `verify_task18_binding`의 corpus equality 검사를 느슨하게 재사용하지 않는다. post verifier는 binding target과 Git object 변경 path가 exact match인지, snapshot before 객체와 live 객체에서 title 제외 canonical bytes가 같은지, after corpus fingerprint·object count·reference graph·lint·paired mismatch·quote debt IDs·quote 유무·비정본 symbol IDs·live/meta fingerprint·index DB bytes·기존 dirt content가 같은지 확인한다. `verify_git_dirt_preserved`에는 exact 6,491 object path와 result report path만 `allowed_extra_paths`로 넘긴다. report와 NUL pathspec은 create-only control output으로 만든다.

`create_task18_closure_receipt`는 검증된 corpus-final snapshot manifest와 그 verify receipt, binding·display manifest·post report의 path/SHA, snapshot에 기록된 engine implementation HEAD와 BB2 corpus HEAD, 현재 engine docs HEAD와 같은 BB2 corpus HEAD, 양쪽 cached-empty 및 baseline dirt hash, 완료 보고서·ROADMAP의 현재 HEAD blob SHA를 exact schema로 결속한다. 생성 전에 corpus-final snapshot을 다시 검증하고, 완료 보고서·ROADMAP working bytes가 현재 engine HEAD blob과 같으며 두 레포 staged가 비었는지 확인한다. `verify_task18_closure_receipt`는 생성기의 payload builder를 재사용하지 않고 이 관계와 현재 상태를 독립 재계산한다. receipt와 verify receipt는 모두 `atomic_create_receipt`로만 만들며 기존 path를 덮어쓰지 않는다.

CLI는 모든 path와 expected SHA를 명시적으로 받는다. `binding-create`는 expected engine/BB2 HEAD·dirt hash·target SHA·각 input SHA까지 요구하고, `plan`·`verify-plan`·`apply`는 `--task18-binding`과 `--expected-task18-binding-sha256`를 필수로 한다. `binding-verify`, `plan`, `verify-plan`, `apply`, `post-verify`, `closure-create`, `closure-verify`는 absolute `--report`를 필수로 받고 `atomic_create_receipt`로만 쓴다. 기존 report가 있으면 명령을 실행하지 않고 실패한다.

- [ ] **Step 4: architecture 문서에 새 쓰기·복구 경계를 기록한다**

`runtime-map.md`에는 quote inventory → pre-snapshot → binding → plan/verify-plan/apply → post-verify 흐름을, `change-map.md`에는 표시 migration과 binding 변경 시 함께 볼 파일을, `data-contracts.md`에는 paired locator/ref title 불변식과 legacy quote 의미를 기록한다. 사용자 dirty인 `docs/architecture/README.md`와 `docs/design-canonical.md`는 건드리지 않는다.

- [ ] **Step 5: GREEN을 확인한다**

```bash
.venv/bin/python -m pytest -q \
  tests/test_cli.py tests/test_task18_verify.py tests/test_architecture_docs.py
```

- [ ] **Step 6: 소유 path만 커밋하고 독립 리뷰를 통과한다**

```bash
git add -- src/project_brain/task18_verify.py src/project_brain/cli.py \
  tests/test_task18_verify.py tests/test_cli.py \
  docs/architecture/runtime-map.md docs/architecture/change-map.md \
  docs/architecture/data-contracts.md tests/test_architecture_docs.py
git diff --cached --name-only
git commit -m "feat(brain): Task 18 실행 경계 연결"
```

### Task 9: engine 전체 gate와 whole-branch 리뷰를 통과한다

**Files:**
- Read only: engine 전체
- Write: 계획 전용 SDD review package·ledger만 (ignored)

**Interfaces:**
- Produces: 실코퍼스 파일을 만들기 전에 engine 구현이 독립 승인된 고정 HEAD

- [ ] **Step 1: engine 합성·설치 runtime 전체 회귀를 실행한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
cd "$ENGINE"
.venv/bin/python -m pytest -q
.venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
```

Expected: 실패 0.

- [ ] **Step 2: plan 시작 SHA부터 현재 HEAD까지 whole-branch review를 받는다**

reviewer는 paired closure, 독립 binding verifier, snapshot-only 우회 차단, derived preserve recovery, quote 의미, graph 충돌, 사용자 dirt/path-limited 경계를 함께 본다. Critical·Important는 한 번의 fix wave와 scoped re-review로 닫는다.

- [ ] **Step 3: gate 상태를 ledger에 기록한다**

`Task 9: complete (engine full gates pass, whole-branch review clean)`를 기록한다.

커밋 없음.

### Task 10: BB2 quote 부채 정본과 독립 실코퍼스 check를 먼저 커밋한다

**Files:**
- Historical read only: `/Users/al03040455/Desktop/bb2_client/brain/recovery/2026-08-06/task18-display-and-quote-debt/legacy-quote-debt.json`
- Create: `/Users/al03040455/Desktop/bb2_client/brain/recovery/2026-08-06/task18-display-and-quote-debt/legacy-quote-debt-current-develop.json`
- Modify: `/Users/al03040455/Desktop/bb2_client/brain/checks/test_task18_quote_debt.py`

**Interfaces:**
- Produces: migration 전 제목·부채 축을 고정한 persistent JSON과 pre/post 모두 유효한 check
- Consumes: Task 4 CLI, current-develop measurement receipt, exact target revision `47fd83e3b10a21e1294ed00f9259bf356f9259da`

기존 `legacy-quote-debt.json`은 target `6607c458a635ab96ac31acf04c3474fa4ea7eeff`와
실패한 attempt-001을 설명하는 역사 증빙이다. 고치거나 덮어쓰지 않고, 현재 target에는 새
파일과 그 파일을 가리키는 전용 check를 사용한다.

- [ ] **Step 1: audit로 current stale report를 만들고 quote inventory를 create-only 생성한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
OUT="$BB2/brain/recovery/2026-08-06/task18-display-and-quote-debt/legacy-quote-debt-current-develop.json"
GENERATED_AT=$(PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -c \
  'from project_brain.objbase import now_kst; print(now_kst())')
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli audit \
  --brain-root "$BB2/brain" --repo-root "$BB2" --no-fetch --no-stale-cache-write
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli \
  migration quote-debt build \
  --brain-root "$BB2/brain" --repo-root "$BB2" \
  --target-revision 47fd83e3b10a21e1294ed00f9259bf356f9259da \
  --measurement "$BB2/.snapshots/2026-08-06/task18-remeasurement-current-develop/attempt-001/measurement.json" \
  --expected-measurement-sha256 f3f95505fd93a1e78c3ce225bbf2db984c090adebfc51c5598d0736d20a25834 \
  --generated-at "$GENERATED_AT" --output "$OUT"
```

실행 시 실제 생성 시각을 명시하되 재실행은 같은 시각과 새 output path를 써 byte equality를 확인한다. Expected counts: quote debt 3,307, stale 396, unmerged/unverifiable 34, line range 592, candidate 252, noncanonical symbol 289.

- [ ] **Step 2: 기존 dirty test를 건드리지 않고 새 file-based check를 작성한다**

```python
class Task18QuoteDebtContract(unittest.TestCase):
    def test_inventory_immutable_fields_match_current_corpus(self):
        result = verify_quote_debt_immutable_fields(
            load_inventory(), existing=load_store(), stale_report=build_stale_report(),
        )
        self.assertEqual(result["quote_debt_count"], 3307)
        self.assertEqual(result["noncanonical_symbol_count"], 289)

    def test_explicit_execution_phase(self):
        phase = os.environ.get("PROJECT_BRAIN_TASK18_PHASE")
        if phase is None:
            self.skipTest("Task 18 execution phase is not active")
        if phase == "pre_migration":
            result = verify_quote_debt_inventory(
                load_inventory(), existing=load_store(), stale_report=build_stale_report(),
                phase="pre_migration",
            )
        elif phase == "post_migration":
            binding_path = Path(os.environ["PROJECT_BRAIN_TASK18_BINDING"])
            binding_sha = os.environ["PROJECT_BRAIN_TASK18_BINDING_SHA256"]
            authorization = load_task18_post_authorization(
                binding_path=binding_path,
                expected_binding_sha256=binding_sha,
                engine_root=ENGINE_ROOT,
                repo_root=BB2_ROOT,
                brain_root=BRAIN_ROOT,
            )
            result = verify_quote_debt_inventory(
                load_inventory(), existing=load_store(), stale_report=build_stale_report(),
                phase="post_migration", authorized_titles=authorization.expected_titles,
            )
        else:
            self.fail(f"invalid PROJECT_BRAIN_TASK18_PHASE: {phase}")
        self.assertTrue(result["ok"])
```

check는 ID, quote 유무, path/symbol/status/source/ref link와 non-title hash를 항상 고정한다. 단계는 현재 title을 보고 추정하지 않는다. 실행 gate가 `pre_migration` 또는 `post_migration`을 명시하고, post phase는 binding path/SHA를 검증해 얻은 exact target→expected title mapping만 허용한다. 일부만 적용된 혼합 상태는 pre와 post 양쪽에서 실패한다.

- [ ] **Step 3: BB2 check와 engine inventory test를 실행한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
PROJECT_BRAIN_TASK18_PHASE=pre_migration \
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m unittest \
  discover -s "$BB2/brain/checks" -p 'test_*.py'
```

- [ ] **Step 4: 두 신규 path만 강제 추가해 BB2에 커밋한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
git -C "$BB2" add -f -- \
  brain/recovery/2026-08-06/task18-display-and-quote-debt/legacy-quote-debt-current-develop.json \
  brain/checks/test_task18_quote_debt.py
"$ENGINE/.venv/bin/python" - <<'PY'
import subprocess
from pathlib import Path
root = Path("/Users/al03040455/Desktop/bb2_client")
expected = {
    "brain/recovery/2026-08-06/task18-display-and-quote-debt/legacy-quote-debt-current-develop.json",
    "brain/checks/test_task18_quote_debt.py",
}
payload = subprocess.run(
    ["git", "diff", "--cached", "--name-only", "-z"],
    cwd=root, check=True, stdout=subprocess.PIPE,
).stdout
actual = {part.decode("utf-8") for part in payload.split(b"\0") if part}
assert actual == expected, (sorted(actual - expected), sorted(expected - actual))
PY
git -C "$BB2" commit -m "docs(brain): 현재 인용문 부채 기준 갱신"
```

독립 reviewer는 persistent JSON SHA/counts와 check의 pre/post 의미를 검토한다. corpus object는 아직 바뀌면 안 된다.

### Task 11: 실코퍼스 gate와 pre-mutation snapshot을 만든다

**Files:**
- Create: `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-06/task18-execution/attempt-004/pre-mutation/` (ignored)
- Create: `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-06/task18-execution/attempt-004/pre-mutation-verify.json` (ignored)

**Interfaces:**
- Produces: 모든 engine/BB2 code·docs·inventory commit 뒤의 검증된 pre-mutation snapshot

- [ ] **Step 0: 새 attempt root가 비어 있음을 확인한다**

```bash
BB2=/Users/al03040455/Desktop/bb2_client
ATTEMPT="$BB2/.snapshots/2026-08-06/task18-execution/attempt-004"
test ! -e "$ATTEMPT"
mkdir -p "$ATTEMPT"
```

attempt-002는 engine cwd에서 실행한 eval이 색인 DB를 찾지 못해 0/15로 실패한 역사 증빙이다. attempt-003은 binding·독립 검증·plan·apply까지 성공했지만 production post-verify가 이미 정본 제목인 비대상 CodeLocator와 짝인 EvidenceRef 단독 target을 잘못 거부했고, v2 restore가 성공한 역사 증빙이다. 둘 다 지우거나 재사용하지 않는다. 이후 실패해 재시도할 때도 기존 디렉터리를 지우거나 재사용하지 않고 다음 번호의 새 attempt root를 쓴다. 선택한 번호를 SDD ledger에 기록하고 Task 11~13의 모든 `ROOT`를 같은 번호로 바꾼다.

- [ ] **Step 1: BB2 gate를 명시적 checkout으로 실행한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
PROJECT_BRAIN_TASK18_PHASE=pre_migration \
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m unittest \
  discover -s "$BB2/brain/checks" -p 'test_*.py'
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli audit \
  --brain-root "$BB2/brain" --repo-root "$BB2" --no-fetch --no-stale-cache-write
(
  cd "$BB2"
  PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli eval \
    --brain-root "$BB2/brain" \
    --scenarios "$BB2/brain/eval_scenarios.json"
)
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli graph export \
  "$BB2/.snapshots/2026-08-06/task18-execution/attempt-004/pre-mutation-graph.html" \
  --brain-root "$BB2/brain"
```

Expected: checks 실패 0, audit 성공, eval 15/15, graph export 성공. `index rebuild`는 실행하지 않는다.

- [ ] **Step 2: present quote 502개 검증 범위를 확인한다**

audit의 code quote 결과는 quote가 저장된 502개와 현재 blob을 대상으로 한다. quote 없는 3,307개 전체가 기계 검증됐다고 기록하지 않는다.

- [ ] **Step 3: snapshot을 create-only 생성하고 별도 명령으로 검증한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
SNAP_PARENT="$BB2/.snapshots/2026-08-06/task18-execution/attempt-004"
SNAP="$SNAP_PARENT/pre-mutation"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli snapshot create \
  --output-root "$SNAP_PARENT" --snapshot-id pre-mutation \
  --brain-root "$BB2/brain" --repo-root "$BB2" --engine-root "$ENGINE"
```

create 출력과 별개로 생성된 canonical manifest bytes에서 SHA를 다시 계산하고, verify 출력은 `pre-mutation-verify.json`에 저장한다.

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
SNAP="$BB2/.snapshots/2026-08-06/task18-execution/attempt-004/pre-mutation"
VERIFY_RECEIPT="$(dirname "$SNAP")/pre-mutation-verify.json"
SNAP_SHA=$(shasum -a 256 "$SNAP/manifest.json" | awk '{print $1}')
PYTHONPATH="$ENGINE/src" SNAP="$SNAP" SNAP_SHA="$SNAP_SHA" \
  VERIFY_RECEIPT="$VERIFY_RECEIPT" "$ENGINE/.venv/bin/python" - <<'PY'
import os
from pathlib import Path
from project_brain.foundation import atomic_create_receipt
from project_brain.snapshot import verify_snapshot
value = verify_snapshot(Path(os.environ["SNAP"]), expected_manifest_sha256=os.environ["SNAP_SHA"])
atomic_create_receipt(
    Path(os.environ["VERIFY_RECEIPT"]),
    {
        "ok": value.ok, "snapshot_id": value.snapshot_id,
        "manifest_sha256": value.manifest_sha256, "file_count": value.file_count,
        "repo_head": value.repo_head, "engine_head": value.engine_head,
        "corpus_fingerprint": value.corpus_fingerprint,
    },
)
PY
```

`SNAP_SHA`가 create 출력의 `manifest_sha256`과 같은지 확인한다. 기존 snapshot을 덮어쓰지 않는다.

- [ ] **Step 4: snapshot 이후 staged/corpus drift가 없는지 확인한다**

```bash
git -C /Users/al03040455/Downloads/codes/project-brain diff --cached --name-only
git -C /Users/al03040455/Desktop/bb2_client diff --cached --name-only
```

커밋 없음.

### Task 12: final binding → plan → 독립 verify-plan → apply를 끊김 없이 실행한다

**Files:**
- Create: `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-06/task18-execution/attempt-004/task18-binding.json` (ignored)
- Create: 같은 root의 `binding-verify.json`, `display-migration.manifest.json`, `plan-report.json`, `verify-plan-report.json`, `apply-report.json` (ignored)
- Modify: exact 6,491 corpus object JSON (아직 커밋하지 않음)

**Interfaces:**
- Produces: final binding에 결속된 단일 recoverable display transaction 결과
- Consumes: Tasks 6~8 CLI, Task 10 inventory commit, Task 11 snapshot

- [ ] **Step 1: 최종 HEAD·dirt·input SHA를 명시해 binding을 create-only 생성한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
ROOT="$BB2/.snapshots/2026-08-06/task18-execution/attempt-004"
PLAN_REL=docs/superpowers/plans/2026-08-06-task18-display-labels-and-quote-debt.md
DESIGN_REL=docs/superpowers/specs/2026-08-06-task18-display-labels-and-quote-debt-redesign.md
PLAN="$ENGINE/$PLAN_REL"
DESIGN="$ENGINE/$DESIGN_REL"
QUOTE="$BB2/brain/recovery/2026-08-06/task18-display-and-quote-debt/legacy-quote-debt-current-develop.json"
P0="$BB2/.snapshots/2026-08-05/p0-foundation/p0-handoff.json"
ENGINE_HEAD=$(git -C "$ENGINE" rev-parse HEAD)
BB2_HEAD=$(git -C "$BB2" rev-parse HEAD)
ENGINE_STATUS=$(PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -c \
  'from pathlib import Path; from project_brain.snapshot import capture_git_dirt_receipt; print(capture_git_dirt_receipt(Path("/Users/al03040455/Downloads/codes/project-brain"), label="task18_engine").status_sha256)')
ENGINE_DIRT=$(PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -c \
  'from pathlib import Path; from project_brain.snapshot import capture_git_dirt_receipt; print(capture_git_dirt_receipt(Path("/Users/al03040455/Downloads/codes/project-brain"), label="task18_engine").content_manifest_sha256)')
BB2_STATUS=$(PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -c \
  'from pathlib import Path; from project_brain.snapshot import capture_git_dirt_receipt; print(capture_git_dirt_receipt(Path("/Users/al03040455/Desktop/bb2_client"), label="task18_bb2").status_sha256)')
BB2_DIRT=$(PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -c \
  'from pathlib import Path; from project_brain.snapshot import capture_git_dirt_receipt; print(capture_git_dirt_receipt(Path("/Users/al03040455/Desktop/bb2_client"), label="task18_bb2").content_manifest_sha256)')
SNAP_SHA=$(shasum -a 256 "$ROOT/pre-mutation/manifest.json" | awk '{print $1}')
SNAP_VERIFY_SHA=$(shasum -a 256 "$ROOT/pre-mutation-verify.json" | awk '{print $1}')
GENERATED_AT=$(PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -c \
  'from project_brain.objbase import now_kst; print(now_kst())')
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli \
  migration display binding-create \
  --binding "$ROOT/task18-binding.json" \
  --brain-root "$BB2/brain" --repo-root "$BB2" --engine-root "$ENGINE" \
  --expected-engine-head "$ENGINE_HEAD" --expected-repo-head "$BB2_HEAD" \
  --expected-engine-status-sha256 "$ENGINE_STATUS" \
  --expected-engine-dirt-content-sha256 "$ENGINE_DIRT" \
  --expected-repo-status-sha256 "$BB2_STATUS" \
  --expected-repo-dirt-content-sha256 "$BB2_DIRT" \
  --local-target-ref refs/remotes/origin/develop \
  --remote origin --remote-target-ref refs/heads/develop \
  --target-revision-sha 47fd83e3b10a21e1294ed00f9259bf356f9259da \
  --p0-handoff "$P0" \
  --expected-p0-handoff-sha256 55df01d2ed40aa8bee93ded3df378c3733bb00be30fbc8a8a9da21138590761b \
  --measurement "$BB2/.snapshots/2026-08-06/task18-remeasurement-current-develop/attempt-001/measurement.json" \
  --expected-measurement-sha256 f3f95505fd93a1e78c3ce225bbf2db984c090adebfc51c5598d0736d20a25834 \
  --design "$DESIGN" --design-commit-sha "$(git -C "$ENGINE" log -1 --format=%H -- "$DESIGN_REL")" \
  --expected-design-file-sha256 "$(shasum -a 256 "$DESIGN" | awk '{print $1}')" \
  --plan "$PLAN" --plan-commit-sha "$(git -C "$ENGINE" log -1 --format=%H -- "$PLAN_REL")" \
  --expected-plan-file-sha256 "$(shasum -a 256 "$PLAN" | awk '{print $1}')" \
  --quote-debt "$QUOTE" \
  --expected-quote-debt-sha256 "$(shasum -a 256 "$QUOTE" | awk '{print $1}')" \
  --snapshot-root "$ROOT/pre-mutation" --expected-snapshot-manifest-sha256 "$SNAP_SHA" \
  --snapshot-verify-receipt "$ROOT/pre-mutation-verify.json" \
  --expected-snapshot-verify-receipt-sha256 "$SNAP_VERIFY_SHA" \
  --generated-at "$GENERATED_AT"
```

생성 직후 `BINDING_SHA=$(shasum -a 256 "$ROOT/task18-binding.json" | awk '{print $1}')`로 SHA를 고정한다.

- [ ] **Step 2: 별도 `binding-verify` 호출이 현재 상태를 다시 계산해 PASS하는지 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
ROOT="$BB2/.snapshots/2026-08-06/task18-execution/attempt-004"
BINDING_SHA=$(shasum -a 256 "$ROOT/task18-binding.json" | awk '{print $1}')
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli \
  migration display binding-verify \
  --brain-root "$BB2/brain" --repo-root "$BB2" --engine-root "$ENGINE" \
  --task18-binding "$ROOT/task18-binding.json" \
  --expected-task18-binding-sha256 "$BINDING_SHA" \
  --report "$ROOT/binding-verify.json"
```

Expected: `task18_allowed=true`, locator 3,305, EvidenceRef 3,186, total 6,491.

- [ ] **Step 3: bound display plan과 manifest를 create-only 생성한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
ROOT="$BB2/.snapshots/2026-08-06/task18-execution/attempt-004"
BINDING_SHA=$(shasum -a 256 "$ROOT/task18-binding.json" | awk '{print $1}')
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli migration display plan \
  --brain-root "$BB2/brain" --repo-root "$BB2" --engine-root "$ENGINE" \
  --task18-binding "$ROOT/task18-binding.json" \
  --expected-task18-binding-sha256 "$BINDING_SHA" \
  --manifest "$ROOT/display-migration.manifest.json" \
  --report "$ROOT/plan-report.json"
```

- [ ] **Step 4: manifest SHA를 고정해 독립 verify-plan을 실행한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
ROOT="$BB2/.snapshots/2026-08-06/task18-execution/attempt-004"
BINDING_SHA=$(shasum -a 256 "$ROOT/task18-binding.json" | awk '{print $1}')
MANIFEST_SHA=$(shasum -a 256 "$ROOT/display-migration.manifest.json" | awk '{print $1}')
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli migration display verify-plan \
  --brain-root "$BB2/brain" --repo-root "$BB2" --engine-root "$ENGINE" \
  --task18-binding "$ROOT/task18-binding.json" \
  --expected-task18-binding-sha256 "$BINDING_SHA" \
  --manifest "$ROOT/display-migration.manifest.json" \
  --expected-manifest-sha256 "$MANIFEST_SHA" \
  --report "$ROOT/verify-plan-report.json"
```

- [ ] **Step 5: 그 사이 Git/corpus drift가 없을 때만 apply한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
ROOT="$BB2/.snapshots/2026-08-06/task18-execution/attempt-004"
BINDING_SHA=$(shasum -a 256 "$ROOT/task18-binding.json" | awk '{print $1}')
MANIFEST_SHA=$(shasum -a 256 "$ROOT/display-migration.manifest.json" | awk '{print $1}')
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli migration display apply \
  --brain-root "$BB2/brain" --repo-root "$BB2" --engine-root "$ENGINE" \
  --task18-binding "$ROOT/task18-binding.json" \
  --expected-task18-binding-sha256 "$BINDING_SHA" \
  --manifest "$ROOT/display-migration.manifest.json" \
  --expected-manifest-sha256 "$MANIFEST_SHA" \
  --report "$ROOT/apply-report.json"
```

각 SHA는 같은 Task 앞 단계의 create-only artifact bytes에서 다시 계산하고 명령 출력값과 비교한다. binding 뒤 새 커밋, inventory 수정, audit, graph, 다른 corpus write를 끼우지 않는다. drift가 나면 기존 파일을 고치지 말고 새 snapshot과 새 binding 경로로 Task 11부터 다시 한다.

### Task 13: 적용 결과를 검증·커밋하고 snapshot·review·closure 순서로 닫는다

**Files:**
- Create: `/Users/al03040455/Desktop/bb2_client/brain/recovery/2026-08-06/task18-display-and-quote-debt/display-migration-result.json`
- Create: ignored `changed-object-paths.zlist`, final graph, `corpus-final/` snapshot, snapshot verify receipt, closure·closure verify receipt
- Modify: exact 6,491 BB2 object JSON
- Create: `docs/reports/2026-08-06-task18-display-labels-and-quote-debt-completion.md`
- Modify: `ROADMAP.md`

**Interfaces:**
- Produces: 검증된 BB2 corpus commit, 그 commit을 담은 corpus-final snapshot, 독립 최종 리뷰, engine 완료 문서 commit, 두 최종 HEAD를 결속한 closure receipt

- [ ] **Step 1: post phase를 명시해 full engine/runtime/BB2 gate를 다시 실행한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
ROOT="$BB2/.snapshots/2026-08-06/task18-execution/attempt-004"
BINDING_SHA=$(shasum -a 256 "$ROOT/task18-binding.json" | awk '{print $1}')
cd "$ENGINE"
.venv/bin/python -m pytest -q
.venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
PROJECT_BRAIN_TASK18_PHASE=post_migration \
PROJECT_BRAIN_TASK18_BINDING="$ROOT/task18-binding.json" \
PROJECT_BRAIN_TASK18_BINDING_SHA256="$BINDING_SHA" \
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m unittest \
  discover -s "$BB2/brain/checks" -p 'test_*.py'
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli audit \
  --brain-root "$BB2/brain" --repo-root "$BB2" --no-fetch --no-stale-cache-write
(
  cd "$BB2"
  PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli eval \
    --brain-root "$BB2/brain" \
    --scenarios "$BB2/brain/eval_scenarios.json"
)
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli graph export \
  "$ROOT/final-graph.html" --brain-root "$BB2/brain"
```

Expected: 모든 test 실패 0, audit 성공, eval 15/15, graph export 성공. rebuild 없음. post check는 현재 title을 보고 단계를 추정하지 않고 SHA가 맞는 binding의 exact authorization만 사용한다.

- [ ] **Step 2: audit까지 끝난 상태에서 post-verify receipt와 exact pathspec을 생성한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
ROOT="$BB2/.snapshots/2026-08-06/task18-execution/attempt-004"
BINDING_SHA=$(shasum -a 256 "$ROOT/task18-binding.json" | awk '{print $1}')
MANIFEST_SHA=$(shasum -a 256 "$ROOT/display-migration.manifest.json" | awk '{print $1}')
QUOTE="$BB2/brain/recovery/2026-08-06/task18-display-and-quote-debt/legacy-quote-debt-current-develop.json"
QUOTE_SHA=$(shasum -a 256 "$QUOTE" | awk '{print $1}')
GENERATED_AT=$(PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -c \
  'from project_brain.objbase import now_kst; print(now_kst())')
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli migration display post-verify \
  --brain-root "$BB2/brain" --repo-root "$BB2" --engine-root "$ENGINE" \
  --task18-binding "$ROOT/task18-binding.json" \
  --expected-task18-binding-sha256 "$BINDING_SHA" \
  --manifest "$ROOT/display-migration.manifest.json" \
  --expected-manifest-sha256 "$MANIFEST_SHA" \
  --quote-debt "$QUOTE" --expected-quote-debt-sha256 "$QUOTE_SHA" \
  --report "$BB2/brain/recovery/2026-08-06/task18-display-and-quote-debt/display-migration-result.json" \
  --pathspec-output "$ROOT/changed-object-paths.zlist" \
  --generated-at "$GENERATED_AT"
```

Expected: updates 6,491, paired mismatch 0/3,202, title 외 변경 0, quote debt 3,307 불변, noncanonical symbol 289 불변, live/meta fingerprint 일치, index DB와 stale-set SHA가 binding과 같고 기존 사용자 dirt가 내용까지 같다.

- [ ] **Step 3: 검증된 object pathspec과 result report만 BB2에 커밋한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
PATHS="$BB2/.snapshots/2026-08-06/task18-execution/attempt-004/changed-object-paths.zlist"
git -C "$BB2" add -f --pathspec-from-file="$PATHS" --pathspec-file-nul
git -C "$BB2" add -f -- \
  brain/recovery/2026-08-06/task18-display-and-quote-debt/display-migration-result.json
"$ENGINE/.venv/bin/python" - <<'PY'
import subprocess
from pathlib import Path
root = Path("/Users/al03040455/Desktop/bb2_client")
paths = root / ".snapshots/2026-08-06/task18-execution/attempt-004/changed-object-paths.zlist"
expected = {part.decode("utf-8") for part in paths.read_bytes().split(b"\0") if part}
expected.add("brain/recovery/2026-08-06/task18-display-and-quote-debt/display-migration-result.json")
payload = subprocess.run(
    ["git", "diff", "--cached", "--name-only", "-z"],
    cwd=root, check=True, stdout=subprocess.PIPE,
).stdout
actual = {part.decode("utf-8") for part in payload.split(b"\0") if part}
assert len(expected) == 6492
assert actual == expected, (sorted(actual - expected), sorted(expected - actual))
PY
git -C "$BB2" diff --cached --check
git -C "$BB2" commit -m "fix(brain): 기존 표시 제목 동기화"
test -z "$(git -C "$BB2" diff --cached --name-only)"
```

staged 목록은 object 6,491개 + result report 1개뿐이어야 한다. 사용자 dirt나 `test_real_corpus.py`가 섞이면 commit하지 않는다.

- [ ] **Step 4: BB2 corpus commit과 engine implementation HEAD를 corpus-final snapshot으로 고정·검증한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
FINAL_PARENT="$BB2/.snapshots/2026-08-06/task18-execution/attempt-004"
FINAL="$FINAL_PARENT/corpus-final"
FINAL_VERIFY="$FINAL_PARENT/corpus-final-verify.json"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli snapshot create \
  --output-root "$FINAL_PARENT" --snapshot-id corpus-final \
  --brain-root "$BB2/brain" --repo-root "$BB2" --engine-root "$ENGINE"
FINAL_SHA=$(shasum -a 256 "$FINAL/manifest.json" | awk '{print $1}')
PYTHONPATH="$ENGINE/src" FINAL="$FINAL" FINAL_SHA="$FINAL_SHA" \
  FINAL_VERIFY="$FINAL_VERIFY" \
  "$ENGINE/.venv/bin/python" - <<'PY'
import os
from pathlib import Path
from project_brain.foundation import atomic_create_receipt
from project_brain.snapshot import verify_snapshot
value = verify_snapshot(
    Path(os.environ["FINAL"]), expected_manifest_sha256=os.environ["FINAL_SHA"]
)
atomic_create_receipt(
    Path(os.environ["FINAL_VERIFY"]),
    {
        "ok": value.ok, "snapshot_id": value.snapshot_id,
        "manifest_sha256": value.manifest_sha256, "file_count": value.file_count,
        "repo_head": value.repo_head, "engine_head": value.engine_head,
        "corpus_fingerprint": value.corpus_fingerprint,
    },
)
PY
```

snapshot verify receipt는 `ok=true`여야 하고, `repo_head`는 방금 만든 BB2 corpus commit, `engine_head`는 독립 승인된 engine implementation HEAD와 같아야 한다. 기존 snapshot이나 receipt를 덮어쓰지 않는다.

- [ ] **Step 5: 고정 candidate를 각각 독립 최종 리뷰한다**

engine reviewer는 Task 0 시작 SHA부터 corpus-final snapshot의 `engine_head`까지 whole branch를 보고, BB2 reviewer는 quote inventory commit부터 snapshot의 exact `repo_head`까지와 binding·manifest·post report·snapshot verify receipt를 함께 본다. exact 6,491 object diff가 title-only인지, quote/symbol/index/dirt가 불변인지, paired closure·복구·우회 차단이 설계를 충족하는지 확인한다. load-bearing finding이 남으면 완료 문서를 쓰지 않는다. 수정이 필요하면 현재 attempt artifact를 재사용하지 않고 새 attempt 번호로 Task 11부터 다시 시작한다.

- [ ] **Step 6: 리뷰가 깨끗한 뒤에만 engine 완료 보고서와 ROADMAP을 커밋한다**

두 path를 수정하기 직전에 모두 HEAD와 같음을 확인한다. 완료 보고서는 설계/계획, engine implementation SHA, BB2 corpus SHA, binding/manifest/post report SHA, corpus-final snapshot manifest·verify receipt SHA, 실제 counts, 검증 명령 결과, 독립 리뷰 verdict, index DB SHA 불변, 사용자 dirt 보존, 마지막 closure path를 기록한다. 별도 reviewer가 이 두 문서의 주장과 증빙을 대조해 승인한 뒤에만 커밋한다.

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
git -C "$ENGINE" diff --quiet HEAD -- ROADMAP.md
test ! -e "$ENGINE/docs/reports/2026-08-06-task18-display-labels-and-quote-debt-completion.md"
# 위 검증 결과로 두 문서를 작성하고 독립 docs review를 통과한 뒤 실행한다.
git -C "$ENGINE" add -- \
  docs/reports/2026-08-06-task18-display-labels-and-quote-debt-completion.md \
  ROADMAP.md
"$ENGINE/.venv/bin/python" - <<'PY'
import subprocess
from pathlib import Path
root = Path("/Users/al03040455/Downloads/codes/project-brain")
expected = {
    "docs/reports/2026-08-06-task18-display-labels-and-quote-debt-completion.md",
    "ROADMAP.md",
}
payload = subprocess.run(
    ["git", "diff", "--cached", "--name-only", "-z"],
    cwd=root, check=True, stdout=subprocess.PIPE,
).stdout
actual = {part.decode("utf-8") for part in payload.split(b"\0") if part}
assert actual == expected, (sorted(actual - expected), sorted(expected - actual))
PY
git -C "$ENGINE" diff --cached --check
git -C "$ENGINE" commit -m "docs(brain): Task 18 완료 기록"
test -z "$(git -C "$ENGINE" diff --cached --name-only)"
```

- [ ] **Step 7: 최종 두 HEAD와 모든 증빙을 closure receipt로 결속하고 독립 검증한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
ROOT="$BB2/.snapshots/2026-08-06/task18-execution/attempt-004"
FINAL="$ROOT/corpus-final"
FINAL_SHA=$(shasum -a 256 "$FINAL/manifest.json" | awk '{print $1}')
FINAL_VERIFY_SHA=$(shasum -a 256 "$ROOT/corpus-final-verify.json" | awk '{print $1}')
BINDING_SHA=$(shasum -a 256 "$ROOT/task18-binding.json" | awk '{print $1}')
MANIFEST_SHA=$(shasum -a 256 "$ROOT/display-migration.manifest.json" | awk '{print $1}')
POST="$BB2/brain/recovery/2026-08-06/task18-display-and-quote-debt/display-migration-result.json"
POST_SHA=$(shasum -a 256 "$POST" | awk '{print $1}')
ENGINE_HEAD=$(git -C "$ENGINE" rev-parse HEAD)
BB2_HEAD=$(git -C "$BB2" rev-parse HEAD)
GENERATED_AT=$(PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -c \
  'from project_brain.objbase import now_kst; print(now_kst())')
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli migration display closure-create \
  --engine-root "$ENGINE" --repo-root "$BB2" --brain-root "$BB2/brain" \
  --corpus-snapshot "$FINAL" --expected-snapshot-manifest-sha256 "$FINAL_SHA" \
  --snapshot-verify "$ROOT/corpus-final-verify.json" \
  --expected-snapshot-verify-sha256 "$FINAL_VERIFY_SHA" \
  --task18-binding "$ROOT/task18-binding.json" \
  --expected-task18-binding-sha256 "$BINDING_SHA" \
  --display-manifest "$ROOT/display-migration.manifest.json" \
  --expected-display-manifest-sha256 "$MANIFEST_SHA" \
  --post-report "$POST" --expected-post-report-sha256 "$POST_SHA" \
  --completion-report "$ENGINE/docs/reports/2026-08-06-task18-display-labels-and-quote-debt-completion.md" \
  --roadmap "$ENGINE/ROADMAP.md" \
  --expected-engine-head "$ENGINE_HEAD" --expected-bb2-head "$BB2_HEAD" \
  --generated-at "$GENERATED_AT" --report "$ROOT/task18-closure.json"
CLOSURE_SHA=$(shasum -a 256 "$ROOT/task18-closure.json" | awk '{print $1}')
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli migration display closure-verify \
  --engine-root "$ENGINE" --repo-root "$BB2" --brain-root "$BB2/brain" \
  --closure "$ROOT/task18-closure.json" \
  --expected-closure-sha256 "$CLOSURE_SHA" \
  --report "$ROOT/task18-closure-verify.json"
```

closure verify는 corpus-final snapshot의 engine implementation HEAD와 BB2 corpus HEAD, 현재 engine docs HEAD와 같은 BB2 corpus HEAD, 양쪽 cached-empty와 baseline 사용자 dirt, 현재 HEAD에 커밋된 완료 보고서·ROADMAP bytes를 각각 다시 확인해야 한다. 두 receipt 모두 create-only다.

- [ ] **Step 8: SDD ledger를 닫고 계획 workspace를 제거한다**

closure verify까지 깨끗할 때 `Task 13: complete`와 engine docs commit, BB2 corpus commit, corpus-final manifest SHA, closure SHA를 기록한 뒤 이 계획의 `.superpowers/sdd/2026-08-06-task18-display-labels-and-quote-debt/` 디렉터리만 제거한다. 사용자 파일이나 다른 계획 workspace는 건드리지 않는다.

---

## Completion Gate

다음이 모두 확인돼야 Task 18 완료다.

- engine 전체 pytest와 설치 runtime unittest 실패 0
- BB2 checks 실패 0, audit 성공, eval 15/15, graph export 성공
- final binding 독립 검증 `task18_allowed=true`
- CodeLocator 3,305 + EvidenceRef 3,186 = UPDATE 6,491, create/delete/rename/aux 0
- paired mismatch 0/3,202, title 외 payload와 lifecycle timestamp 변경 0
- quote 부채 3,307과 비정본 symbol 289의 ID·내용 불변
- index rebuild 없이 live/meta fingerprint 일치, index DB bytes 불변
- 기존 사용자 dirt 내용 불변, Task 소유 path만 commit
- corpus-final snapshot verify PASS, snapshot의 engine implementation HEAD·BB2 corpus HEAD 일치
- 독립 최종 리뷰와 completion docs review에 열린 Critical·Important 없음
- closure verify PASS, final engine docs HEAD·같은 BB2 corpus HEAD·committed completion bytes 일치
