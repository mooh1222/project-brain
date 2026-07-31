# Task 17 Canonical ID Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 검토된 156행 결정 원장과 제한된 `canonical_repair`를 사용해 BB2의
structured ID problem `155/158`을 `0/0`으로 만들고, dangling reference나 승인 밖
payload 변화 없이 Task 17 commit과 final snapshot binding을 남긴다.

**Architecture:** 엔진은 corpus별 ID를 고르지 않고 결정 원장, field diff, snapshot,
Git 상태와 corpus fingerprint를 검증한다. ID-only로 표현할 수 없는 DomainMapping
4개와 mixed ReviewRecord 1개를 먼저 repair하고 intermediate snapshot에 다시 묶은
ID-only migration으로 나머지를 처리한다. BB2 실행은 read-only Phase A, 의미 승인,
byte-exact staging 승인, stable-lock live 적용의 네 경계로 나뉜다.

**Tech Stack:** Python 3.12, dataclasses, argparse, pytest, unittest, `BrainStore`,
`MutationService`, Project Brain snapshot/transaction API, Git pathspec files.

## Global Constraints

- 구현을 시작할 때 `superpowers:using-git-worktrees`로 기존 isolated worktree
  `/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery`의
  branch와 clean 상태를 확인한다. 다른 worktree를 새로 만들거나 원본 checkout에서
  구현하지 않는다.
- 승인된 설계는
  `docs/superpowers/specs/2026-07-31-task17-canonical-id-recovery-design.md`,
  SHA-256
  `b58d5d382cf0064130abe9ea04e73740f199d58d833161d95ddba2fda01b45a4`다.
- 설계 commit `c7bacd6d7dd5a93f2657dac2f11058250abcc742` 이후 구현 시작 전까지 허용되는
  변경은 이 계획 문서뿐이다. 구현 시작 시 현재 HEAD를 `ENGINE_BASELINE_SHA`로
  기록하고 `c7bacd6..ENGINE_BASELINE_SHA`의 changed path가 이 계획 한 파일뿐인지
  확인한다.
- BB2 시작 HEAD는
  `53671bce5e94edf38a7afa11706963581065fb0f`다. Task 17 commit 전까지 HEAD가
  달라지면 중단한다.
- 검증된 post-ingame snapshot은 ID `post-ingame-20260728`, manifest SHA-256
  `e4093569753a26ea3f49adc6568c2942a52499e3dda695fe12fa95c4ff0feaa9`, file count
  `11134`다. 이 snapshot은 이전 engine SHA에 묶였으므로 새 migration apply
  receipt로 재사용하지 않는다.
- 2026-07-31 계획 완료 시점의 BB2 사용자 dirt 기준은 NUL status
  `32 records / 2209 bytes /
  4c227b67a7e040498003d9beeed5be73366981f33fe3bc8639dd055ab2cd0c23`, staged `0`이다.
  기존 기준 뒤 추가된 한 건은
  `.agents/skills/guardrails/agents/openai.yaml`, file SHA-256
  `55fafc73379acca7769e7a7d2f02409238f661ecede5a7b5c6154eac21454fcf`다. Task 17
  소유가 아닌 사용자 dirt로 보존한다.
- engine 원본 checkout 기준은 NUL status `17 records / 751 bytes /
  72d1449a578815cc57d86ad8c2022506b520c48e1ab3baca3350e7a5f418f93f`, staged `0`이다.
  두 dirty tree는 raw status뿐 아니라 각 path의 no-follow content receipt까지
  보존한다.
- 사용자가 이미 복구한 터미널 권한은 재진단하거나 재검증하지 않는다.
- 모든 Python 명령은 exact interpreter
  `/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery/.venv/bin/python`
  과 exact `PYTHONPATH`의 `src`를 사용한다. 테스트는
  `PYTHONDONTWRITEBYTECODE=1`로 실행한다.
- generic slugify, validation 완화, existing-target overwrite, 자동 merge,
  supersede, Task 18 display migration을 금지한다.
- index와 stale-set은 old→new 문자열 치환하지 않고 transaction에서 invalidate한 뒤
  검증된 corpus로 rebuild한다.
- Phase A evidence는 기존 `/private/tmp` JSON을 복사하지 않고 검토된 scanner로
  현재 corpus에서 다시 만든다. 기존 SHA는 semantic provenance 비교에만 쓴다.
- 기존 provenance SHA-256은 measurement
  `5834e968a5249fc8a77205da5f1f210aa73829f52164c9536b9b8c48e2f6a78f`,
  classification
  `7015e145848b8b69fbb173d89119d3fdc42d33cda29a68be12b45fa9c9fcbe48`,
  feasibility
  `8036e9aa4ba94592409902706659faf997397ec43611f993cb1bd36dc7eb7669`다.
- 사용자 승인 게이트 1 전에는 staging mutation을 만들지 않는다. 사용자 승인
  게이트 2 전에는 stable live lock을 잡거나 live corpus/index/stale를 바꾸지 않는다.
- staging은 격리된 DB에서 품질을 검증한다. live index는 승인 뒤 실제
  `BAAI/bge-m3`로 정확히 한 번 rebuild한다.
- live canonical repair 시작 뒤 BB2 commit 전 실패는 stable lock을 유지한 채
  verified pre-Task17 snapshot으로 corpus/index/stale만 복구한다.
- BB2 commit 뒤 final snapshot 실패는 reset, amend, revert하지 않는다. 같은
  HEAD에서 snapshot과 binding만 재시도한다.
- `/brain`은 BB2 `.git/info/exclude`에 있으므로 final stage는 반드시
  `git add -f --pathspec-from-file="$TASK17_STAGE_PATHS" --pathspec-file-nul`을
  사용한다.
- push, merge, PR 생성과 Task 18 실행은 이 계획 범위가 아니다.

Scope check: 엔진 기능과 BB2 복구는 별도 소유 경계지만 독립적인 두 프로젝트는
아니다. BB2 scanner, ledger, runner가 앞 task의 engine API와 SHA를 직접 소비하므로
하나의 순차 계획으로 유지한다. 각 경계는 독립 test 또는 receipt gate로 끝난다.

---

## File Map

### Engine

- Create: `src/project_brain/canonical_repair.py`
  - strict decision ledger decoder/validator
  - canonical repair plan/artifact/apply
  - intermediate ID rename receipt adapter
- Modify: `src/project_brain/mutation.py`
  - `CANONICAL_REPAIR`, intent dataclasses, exact diff guard
  - repair binding in transaction manifest
  - target-derived single ReviewRecord exception
- Modify: `src/project_brain/migration.py`
  - target-derived helper를 사용하는 기존 ID-only planner
- Modify: `src/project_brain/snapshot.py`
  - clean engine receipt와 dirty path content receipt
- Modify: `src/project_brain/corpus_io.py`
  - fail-fast stable lock과 anchored staging directory binding
- Modify: `src/project_brain/cli.py`
  - `migration canonical-repair plan|apply`
- Create: `tests/test_canonical_repair.py`
- Modify: `tests/test_mutation.py`
- Modify: `tests/test_migration.py`
- Modify: `tests/test_snapshot.py`
- Modify: `tests/test_corpus_io.py`
- Modify: `tests/test_cli.py`
- Modify: `docs/design-canonical.md`
- Modify: `ROADMAP.md`

### BB2 recovery bundle

- Create: `brain/recovery/2026-07-28/id-migration/scan_task17.py`
- Create: `brain/recovery/2026-07-28/id-migration/test_scan_task17.py`
- Create: `brain/recovery/2026-07-28/id-migration/phase-a-measurement.json`
- Create: `brain/recovery/2026-07-28/id-migration/phase-a-classification.json`
- Create: `brain/recovery/2026-07-28/id-migration/phase-a-feasibility.json`
- Create: `brain/recovery/2026-07-28/id-migration/canonicalization-decisions.json`
- Create: `brain/recovery/2026-07-28/id-migration/run_task17_live.py`
- Create: `brain/recovery/2026-07-28/id-migration/test_run_task17_live.py`
- Create: `brain/recovery/2026-07-28/id-migration/canonical-repair.manifest.json`
- Create: `brain/recovery/2026-07-28/id-migration/id-migration.manifest.json`
- Create: `brain/recovery/2026-07-28/id-migration/canonical-repair-dry-run-report.json`
- Create: `brain/recovery/2026-07-28/id-migration/dry-run-report.json`
- Create: `brain/recovery/2026-07-28/id-migration/canonical-repair-live-report.json`
- Create: `brain/recovery/2026-07-28/id-migration/live-report.json`
- Modify: 두 approved manifest가 열거하는 object와 `eval_scenarios.json`
- Invalidate/rebuild only: `.brain-local/index.db*`, `.brain-local/stale-set.json`

---

### Task 1: Target-derived single ReviewRecord closure를 TDD로 연다

**Files:**

- Modify: `src/project_brain/mutation.py:1064-1157`
- Modify: `src/project_brain/migration.py:645-748`
- Test: `tests/test_mutation.py`
- Test: `tests/test_migration.py`

**Interfaces:**

- Produces:

```text
is_target_derived_single_review_rename(before: Mapping[str, object],
  after: Mapping[str, object], replacements: Mapping[str, str]) -> bool
```

- [ ] **Step 1: 허용되는 두 live shape의 failing tests를 쓴다**

`tests/test_migration.py`에 target object와 현재-valid ReviewRecord를 함께 rename하는
fixture를 추가한다. `review_scope` key가 없는 경우와 exact `single_object`인 경우를
각각 검증한다.

```python
def test_id_plan_allows_target_derived_review_without_scope(tmp_path):
    args = _target_derived_review_plan_args(tmp_path, review_scope="absent")
    plan = plan_id_migration(**args)
    assert [row.kind for row in plan.rows] == ["GlossaryTerm", "ReviewRecord"]


def test_id_plan_allows_target_derived_review_with_single_scope(tmp_path):
    args = _target_derived_review_plan_args(
        tmp_path,
        review_scope="single_object",
    )
    assert plan_id_migration(**args).migration_kind == "id_only"
```

- [ ] **Step 2: red를 확인한다**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m pytest tests/test_migration.py \
  -k 'target_derived_review' -q
```

Expected: `id_only_legacy_source_not_invalid`로 FAIL.

- [ ] **Step 3: 거부 경계 tests를 쓴다**

```python
@pytest.mark.parametrize("scope", [None, "mapping_bundle", "other"])
def test_id_plan_rejects_target_derived_review_with_bad_scope(tmp_path, scope):
    args = _target_derived_review_plan_args(tmp_path, review_scope=scope)
    with pytest.raises(MigrationError) as exc:
        plan_id_migration(**args)
    assert exc.value.code == "id_only_legacy_source_not_invalid"


@pytest.mark.parametrize(
    "tamper",
    ["independent_self_id", "target_not_renamed", "payload", "bundle"],
)
def test_id_plan_rejects_non_exact_review_closure(tmp_path, tamper):
    args = _target_derived_review_plan_args(tmp_path, tamper=tamper)
    with pytest.raises(MigrationError):
        plan_id_migration(**args)
```

- [ ] **Step 4: 최소 helper와 기존 source gate 예외를 구현한다**

`parse_id(object_id, "ReviewRecord")`로 single variant를 확인하고 old/new target과 self
ID를 exact 비교한다. `_infer_id_only_renames()`의 기존-invalid source gate는 이
helper가 true인 경우에만 통과시킨다.

```python
is_allowed_source = (
    old_id in structured_id_problem_ids
    or is_target_derived_single_review_rename(
        existing_by_id[old_id],
        input_by_id[new_id],
        replacements,
    )
)
if not is_allowed_source:
    return (), _failure("id_only_legacy_source_not_invalid", detail)
```

- [ ] **Step 5: targeted와 기존 migration 회귀를 통과시킨다**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_mutation.py tests/test_migration.py -q
```

Expected: PASS.

- [ ] **Step 6: exact files만 commit한다**

```bash
git -C "$ENGINE" add \
  src/project_brain/mutation.py \
  src/project_brain/migration.py \
  tests/test_mutation.py \
  tests/test_migration.py
git -C "$ENGINE" diff --cached --check
git -C "$ENGINE" commit -m "fix(brain): close target-derived review migrations"
```

---

### Task 2: `CANONICAL_REPAIR` mutation 경계를 TDD로 추가한다

**Files:**

- Modify: `src/project_brain/mutation.py`
- Modify: `src/project_brain/corpus_io.py`
- Test: `tests/test_mutation.py`
- Test: `tests/test_corpus_io.py`

**Interfaces:**

- Produces:

```python
@dataclass(frozen=True)
class CanonicalFieldChange:
    pointer: str
    before: object
    after: object


@dataclass(frozen=True)
class CanonicalRepairIntent:
    source_id: str
    new_id: str
    reason_code: str
    field_changes: tuple[CanonicalFieldChange, ...]


class MutationOperation(StrEnum):
    CANONICAL_REPAIR = "canonical_repair"
```

- Extends `MutationRequest` with
  `canonical_repair_intents: tuple[CanonicalRepairIntent, ...] = ()` and
  `canonical_repair_binding: Mapping[str, str] | None = None`.
- Extends `MutationManifest` with
  `canonical_repair_binding: dict[str, object] | None`.
- The binding has the exact keys `decision_ledger_sha256` and
  `phase_a_classification_sha256`; both values are lowercase SHA-256. It is non-null
  only for `CANONICAL_REPAIR` and `_build_manifest()` copies it after shape validation.
- Produces private guard:

```python
def _validate_canonical_repair_request(
    request: MutationRequest,
    *,
    existing_by_id: Mapping[str, dict],
    input_by_id: Mapping[str, dict],
    rename_pairs: tuple[tuple[str, str], ...],
) -> MutationPlanResult | None:
```

- [ ] **Step 1: enum, request shape, operation isolation red tests를 쓴다**

```python
def test_canonical_repair_operation_and_manifest_binding_are_registered():
    assert MutationOperation.CANONICAL_REPAIR.value == "canonical_repair"
    assert "canonical_repair_binding" in {
        field.name for field in fields(MutationManifest)
    }


def test_canonical_intent_is_rejected_for_ingest(tmp_path):
    request = _mapping_repair_request(
        tmp_path,
        operation=MutationOperation.INGEST,
    )
    result = MutationService().plan(request.objects, request=request)
    assert result.error_code == "canonical_repair_intent_operation_invalid"
```

`tests/test_corpus_io.py`에는 manifest key set에 `canonical_repair_binding`이 항상
존재하는 test와 wrong key/SHA, canonical 이외 operation의 non-null binding,
canonical operation의 null binding을 transaction publish 전에 거부하는 test를
같이 추가한다.

- [ ] **Step 2: red를 확인하고 dataclass routing만 구현한다**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m pytest tests/test_mutation.py \
  -k 'canonical_repair_operation or canonical_intent' -q
```

`_validate_request_shape()`가 intent tuple과 각 dataclass field type을 filesystem
접근 전에 검사하도록 구현한다. 다른 operation의 non-empty intent와
`CANONICAL_REPAIR`의 empty intent는 각각 명시적 error code로 거부한다.

- [ ] **Step 3: DomainMapping exact repair red tests를 쓴다**

```python
def test_canonical_repair_allows_id_and_matching_mapping_key(tmp_path):
    request = _mapping_repair_request(tmp_path)
    result = MutationService().plan(request.objects, request=request)
    assert result.ok is True
    assert result.manifest.renames[0]["old_id"] == request.delete_ids[0]


@pytest.mark.parametrize("field", ["title", "meaning", "status"])
def test_canonical_repair_rejects_unlisted_mapping_change(tmp_path, field):
    request = _mapping_repair_request(tmp_path, tamper_field=field)
    result = MutationService().plan(request.objects, request=request)
    assert result.error_code == "canonical_repair_payload_changed"
```

추가 tests는 `/mapping_key` after가 parsed new ID key와 다름, intent before mismatch,
중복 source/target, existing target, merge/delete-only를 각각 거부해야 한다.

- [ ] **Step 4: mixed ReviewRecord exact shape red tests를 쓴다**

```python
def test_canonical_repair_allows_review_target_cleanup_only(tmp_path):
    request = _mixed_review_repair_request(tmp_path)
    result = MutationService().plan(request.objects, request=request)
    assert result.ok is True


@pytest.mark.parametrize(
    "tamper",
    ["add_target", "drop_mapping", "change_scope", "change_bundle_key"],
)
def test_canonical_repair_rejects_unapproved_review_shape(tmp_path, tamper):
    request = _mixed_review_repair_request(tmp_path, tamper=tamper)
    result = MutationService().plan(request.objects, request=request)
    assert result.error_code == "canonical_repair_payload_changed"
```

Review guard는 불변 `bundle_key`의 context와 key로 계산한 bundle ReviewRecord self ID를
요구한다. before에 실제 존재하는 DomainMapping target은 승인된 rename을 적용해
모두 보존하고, grammar상 non-DomainMapping인 target만 제거한다. after list는
non-empty, same-context canonical DomainMapping이어야 하며 target 추가·교체·순서만
바꾸는 변경은 거부한다. `projected_field_repair`와 `review_shape_repair` 이외 reason은
이 operation에서 거부한다.

- [ ] **Step 5: exact diff와 grandfather comparator를 구현한다**

`CANONICAL_REPAIR` explicit rename은 `CONTEXT_REPLACE`와 동일한 one-to-one,
source-delete/new-create 조건을 쓰되 intent가 exact source/new pair를 덮어야 한다.
registered reference rewrite를 먼저 적용한 before object에서 intent field change를
적용한 결과가 after object와 같아야 한다.

```python
expected, _ = rewrite_object_refs(before, dict(rename_pairs))
expected["id"] = intent.new_id
for change in intent.field_changes:
    _replace_exact_pointer(
        expected,
        change.pointer,
        before=change.before,
        after=change.after,
    )
if expected != after:
    return _failure("canonical_repair_payload_changed", intent.source_id)
```

reference-only invalid object의 raw hash가 달라져도 approved rename을 적용한 canonical
shape가 같으면 기존 structured problem을 grandfather한다. 이 comparator를 input
stage와 merged lint stage에서 같은 helper로 재사용한다.

`corpus_io.py`의 `_MUTATION_OPERATIONS`와 `_validate_manifest_model()`도
`canonical_repair` 및 `canonical_repair_binding` exact key를 인식해야 한다. binding은
canonical repair에서만 non-null이고 다른 operation에서 non-null이면 journal publish
전에 거부한다. 기존 manifest도 새 key가 null인 형태로만 허용해 partial-presence
ambiguity를 만들지 않는다.

- [ ] **Step 6: direct apply와 rollback red/green을 확인한다**

`MutationService.apply()`를 planner 우회로 직접 호출해도 intent drift를 거부하는
test와 `failure_injector` 각 transaction point에서 원본 corpus로 복구하는 test를
`tests/test_corpus_io.py`에 추가한다.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_mutation.py tests/test_corpus_io.py \
  -k 'canonical_repair' -q
```

Expected: PASS.

- [ ] **Step 7: exact files만 commit한다**

```bash
git -C "$ENGINE" add \
  src/project_brain/mutation.py \
  src/project_brain/corpus_io.py \
  tests/test_mutation.py \
  tests/test_corpus_io.py
git -C "$ENGINE" diff --cached --check
git -C "$ENGINE" commit -m "feat(brain): add bounded canonical repair mutation"
```

---

### Task 3: Git clean·dirty content receipts를 구현한다

**Files:**

- Modify: `src/project_brain/snapshot.py`
- Test: `tests/test_snapshot.py`

**Interfaces:**

- Produces:

```python
@dataclass(frozen=True)
class GitWorktreeReceipt:
    root: str
    head: str
    status_bytes: bytes
    status_sha256: str


@dataclass(frozen=True)
class GitDirtReceipt:
    root: str
    head: str
    status_bytes: bytes
    status_sha256: str
    entry_count: int
    content_manifest_bytes: bytes
    content_manifest_sha256: str


```

```text
verify_git_root_clean(root: Path, *, label: str) -> GitWorktreeReceipt
capture_git_dirt_receipt(root: Path, *, label: str) -> GitDirtReceipt
verify_git_dirt_preserved(root: Path, *, baseline_status_bytes: bytes,
  baseline_content_manifest_bytes: bytes, label: str,
  allowed_extra_paths: Collection[str] = ()) -> GitDirtReceipt
```

- [ ] **Step 1: clean engine receipt red tests를 쓴다**

```python
def test_verify_git_root_clean_returns_exact_head_and_empty_status(tmp_path):
    root, head = _clean_git_repo(tmp_path)
    receipt = verify_git_root_clean(root, label="engine_root")
    assert receipt.head == head
    assert receipt.status_sha256 == hashlib.sha256(b"").hexdigest()


@pytest.mark.parametrize("dirt", ["tracked", "staged", "untracked"])
def test_verify_git_root_clean_rejects_all_nonignored_dirt(tmp_path, dirt):
    root = _git_repo_with_dirt(tmp_path, dirt)
    with pytest.raises(SnapshotError) as exc:
        verify_git_root_clean(root, label="engine_root")
    assert exc.value.code == "engine_worktree_dirty"
```

- [ ] **Step 2: NUL status와 content receipt red tests를 쓴다**

tracked edit, staged file, untracked regular, deleted path, rename의 두 path와 symlink
target을 포함한 fixture를 만든다. status code를 유지한 채 file bytes 또는 symlink
target만 바꾸면 content mismatch로 실패해야 한다.

```python
def test_git_dirt_receipt_detects_same_status_different_bytes(tmp_path):
    root = _dirty_git_repo(tmp_path)
    baseline = capture_git_dirt_receipt(root, label="user_dirt")
    (root / "untracked.txt").write_bytes(b"changed but still untracked")
    with pytest.raises(SnapshotError) as exc:
        verify_git_dirt_preserved(
            root,
            baseline_status_bytes=baseline.status_bytes,
            baseline_content_manifest_bytes=baseline.content_manifest_bytes,
            label="user_dirt",
        )
    assert exc.value.code == "git_dirt_content_changed"
```

special file, absolute/`..` path, intermediate symlink escape는
`git_dirt_path_unsafe`로 거부한다.

별도 test는 allowlist에 있는 새 path만 추가됐을 때 baseline 보존 PASS, allowlist
밖 새 path는 `git_dirt_unexpected_path` FAIL을 확인한다.

- [ ] **Step 3: anchored no-follow parser와 canonical manifest를 구현한다**

`git status --porcelain=v1 -z --untracked-files=all`을 bytes로 받고 rename/copy의 두
path를 NUL-safe하게 파싱한다. 각 lexical relative path를 repo root descriptor에서
component-wise `O_DIRECTORY|O_NOFOLLOW`로 연다. manifest row는 exact key set을 쓴다.

```python
{
    "path": relative_path,
    "status": status_code,
    "type": "regular" | "symlink" | "missing",
    "mode": mode,
    "size": size,
    "content_sha256": digest_or_none,
}
```

- [ ] **Step 4: targeted snapshot tests를 통과시킨다**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m pytest tests/test_snapshot.py \
  -k 'git_root_clean or git_dirt' -q
```

Expected: PASS.

- [ ] **Step 5: exact files만 commit한다**

```bash
git -C "$ENGINE" add src/project_brain/snapshot.py tests/test_snapshot.py
git -C "$ENGINE" diff --cached --check
git -C "$ENGINE" commit -m "feat(brain): bind git dirt content receipts"
```

---

### Task 4: Decision ledger와 canonical repair artifact를 구현한다

**Files:**

- Create: `src/project_brain/canonical_repair.py`
- Modify: `src/project_brain/migration.py`
- Create: `tests/test_canonical_repair.py`
- Modify: `tests/test_migration.py`

**Interfaces:**

- Produces:

```python
class CanonicalAction(StrEnum):
    ID_ONLY_RENAME = "id_only_rename"
    TARGET_DERIVED_REVIEW_RENAME = "target_derived_review_rename"
    REFERENCE_ONLY = "reference_only"
    PROJECTED_FIELD_REPAIR = "projected_field_repair"
    REVIEW_SHAPE_REPAIR = "review_shape_repair"
    COLLISION_DISTINCT_RENAME = "collision_distinct_rename"


@dataclass(frozen=True)
class CanonicalizationDecision:
    source_id: str
    source_kind: str
    source_sha256: str
    action: CanonicalAction
    new_id: str | None
    field_changes: tuple[CanonicalFieldChange, ...]
    decision_reason: str
    decision_evidence: tuple[str, ...]


@dataclass(frozen=True)
class CanonicalizationLedger:
    version: int
    phase_a_classification_sha256: str
    engine_sha: str
    repo_head: str
    corpus_fingerprint: str
    decisions: tuple[CanonicalizationDecision, ...]
    sha256: str
```

- Produces exact public functions:

```text
decode_canonicalization_ledger(payload: bytes) -> CanonicalizationLedger
validate_canonicalization_ledger(ledger: CanonicalizationLedger, *,
  classification_bytes: bytes, expected_classification_sha256: str,
  existing: BrainStore, engine_sha: str, repo_head: str)
  -> CanonicalizationLedger
parse_canonicalization_ledger(payload: bytes, *, classification_bytes: bytes,
  expected_classification_sha256: str, existing: BrainStore,
  engine_sha: str, repo_head: str) -> CanonicalizationLedger
canonical_repair_renames_from_ledger(ledger: CanonicalizationLedger)
  -> dict[str, str]
id_renames_from_ledger(ledger: CanonicalizationLedger) -> dict[str, str]
```

- Promotes the existing migration context helpers without changing behavior:

```text
validate_snapshot_binding(snapshot: SnapshotVerification) -> None
trusted_migration_context(*, brain_root: Path, repo_root: Path,
  engine_root: Path, engine_sha: str, snapshot: SnapshotVerification)
  -> RepoContext
validate_live_snapshot_corpus(existing: BrainStore,
  snapshot: SnapshotVerification) -> None
```

`plan_id_migration()` and `plan_display_migration()` use the promoted names, and
`canonical_repair.py` imports the same helpers instead of duplicating snapshot/Git/corpus
validation.

- Produces `CanonicalRepairPlan`, `CanonicalRepairArtifact`,
  `CanonicalRepairApplyResult` dataclasses and these functions:

```python
@dataclass(frozen=True)
class CanonicalRepairRow:
    source_id: str
    new_id: str
    kind: str
    reason_code: str
    field_changes: tuple[CanonicalFieldChange, ...]
    canonical_payload_hash: str
    reference_rewrites: tuple[dict, ...]
    snapshot_id: str


@dataclass(frozen=True)
class CanonicalRepairPlan:
    request: MutationRequest
    mutation_plan: MutationPlanResult
    rows: tuple[CanonicalRepairRow, ...]
    decision_ledger_sha256: str
    phase_a_classification_sha256: str
    id_renames: tuple[tuple[str, str], ...]
    snapshot_id: str
    snapshot_manifest_sha256: str
    engine_receipt: GitWorktreeReceipt


@dataclass(frozen=True)
class CanonicalRepairArtifact:
    manifest: dict
    manifest_bytes: bytes
    manifest_sha256: str


@dataclass(frozen=True)
class CanonicalRepairApplyResult:
    transaction_id: str
    action_count: int
    snapshot_id: str
    decision_ledger_sha256: str
```

```text
plan_canonical_repair(*, existing: BrainStore, brain_root: Path,
  repo_root: Path, engine_root: Path, engine_sha: str,
  ledger: CanonicalizationLedger, snapshot: SnapshotVerification)
  -> CanonicalRepairPlan

create_canonical_repair_artifact(plan: CanonicalRepairPlan)
  -> CanonicalRepairArtifact

apply_canonical_repair_artifact(*, manifest_bytes: bytes,
  expected_manifest_sha256: str, decisions_bytes: bytes,
  expected_decisions_sha256: str, classification_bytes: bytes,
  expected_classification_sha256: str, brain_root: Path, repo_root: Path,
  engine_root: Path, engine_sha: str, snapshot_root: Path,
  expected_snapshot_manifest_sha256: str,
  failure_injector: Callable[[str], None] | None = None)
  -> CanonicalRepairApplyResult

id_renames_from_trusted_repair_receipt(*, decisions_bytes: bytes,
  expected_decisions_sha256: str, classification_bytes: bytes,
  expected_classification_sha256: str, canonical_manifest_bytes: bytes,
  expected_canonical_manifest_sha256: str, existing: BrainStore,
  intermediate_snapshot: SnapshotVerification) -> dict[str, str]
```

- [ ] **Step 1: strict decoder red tests를 쓴다**

정상 156행 합성 ledger fixture와 함께 duplicate JSON key, unknown top-level key,
unknown row key/action, empty reason/evidence, malformed SHA, duplicate source, missing
new ID를 하나씩 거부한다.

```python
def test_decode_ledger_rejects_duplicate_json_key():
    payload = b'{"version":1,"version":1}'
    with pytest.raises(CanonicalRepairError) as exc:
        decode_canonicalization_ledger(payload)
    assert exc.value.code == "decision_ledger_invalid"
```

- [ ] **Step 2: classification/source binding red tests를 쓴다**

classification 156행 coverage, classification SHA, engine SHA, repo HEAD, corpus
fingerprint, `BrainStore.source_sha256(source_id)`를 각각 한 축씩 바꿔 fail-closed를
확인한다. target 중복과 current-store target collision도 거부하되 action이
`collision_distinct_rename`이고 선택 target이 비어 있으면 허용한다.

- [ ] **Step 3: decoder와 validator 최소 구현으로 green을 만든다**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m pytest tests/test_canonical_repair.py \
  -k 'ledger or classification or source_binding' -q
```

Expected: PASS.

- [ ] **Step 4: plan/artifact exact binding red tests를 쓴다**

합성 ledger의 DomainMapping 4개와 mixed ReviewRecord 1개만
`CanonicalRepairIntent`로 변환되는지, reference-only affected object가 request에
포함되는지, artifact가 ledger/classification SHA, engine clean receipt, snapshot
ID/SHA, before/expected-after fingerprint, pure ID rename map을 포함하는지 확인한다.
artifact의 `engine_receipt` JSON은 `root`, `head`, `status_sha256`만 직렬화하며
`status_bytes`는 clean 상태의 empty bytes임을 plan 시점에 검증하고 artifact에 직접
넣지 않는다. outer artifact exact keys는 MutationManifest fields에
`canonical_repair_version`, `migration_kind`, `rows`, `objects`,
`decision_ledger_sha256`, `phase_a_classification_sha256`, `id_renames`, `snapshot_id`,
`snapshot_manifest_sha256`, `engine_receipt`를 더한 집합이다.

```python
def test_plan_repairs_only_five_non_id_only_sources(fixture):
    plan = plan_canonical_repair(**fixture.plan_args)
    assert len(plan.rows) == 5
    assert {old_id for old_id, _ in plan.id_renames} == set(
        fixture.expected_id_only_sources
    )
```

- [ ] **Step 5: apply의 fresh replan과 byte equality tests를 쓴다**

manifest, ledger, classification, snapshot, engine HEAD/status, corpus fingerprint 중 한
bytes라도 바뀌면 첫 write 전에 실패해야 한다. 정상 apply는 supplied artifact를
fresh replan한 bytes와 비교한 뒤 `MutationService.apply()`를 정확히 한 번 호출한다.

```python
def test_apply_rejects_ledger_drift_before_mutation(fixture, monkeypatch):
    called = False
    monkeypatch.setattr(MutationService, "apply", _mark_called)
    with pytest.raises(CanonicalRepairError) as exc:
        apply_canonical_repair_artifact(
            **fixture.apply_args,
            decisions_bytes=fixture.tampered_decisions,
        )
    assert exc.value.code == "decision_ledger_sha256_mismatch"
    assert called is False
```

- [ ] **Step 6: module 구현 후 전체 파일을 통과시킨다**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_canonical_repair.py tests/test_mutation.py tests/test_migration.py -q
```

Expected: PASS.

- [ ] **Step 7: exact files만 commit한다**

```bash
git -C "$ENGINE" add \
  src/project_brain/canonical_repair.py \
  src/project_brain/migration.py \
  tests/test_canonical_repair.py \
  tests/test_migration.py
git -C "$ENGINE" diff --cached --check
git -C "$ENGINE" commit -m "feat(brain): plan repair from canonical decisions"
```

---
### Task 5: Fail-fast stable lock과 anchored staging binding을 구현한다

**Files:**

- Modify: `src/project_brain/corpus_io.py`
- Test: `tests/test_corpus_io.py`

**Interfaces:**

- Extends:

```text
stable_corpus_lock(brain_root: Path, *, exclusive: bool,
  blocking: bool = True) -> Iterator[None]
```

- Produces:

```python
@dataclass(frozen=True)
class DirectoryBinding:
    path: Path
    parent_device: int
    parent_inode: int
    device: int
    inode: int


```

```text
create_anchored_temp_directory(parent: Path, *, prefix: str,
  mode: int = 0o700) -> DirectoryBinding
create_anchored_directory(parent: DirectoryBinding, *, name: str,
  mode: int = 0o700) -> DirectoryBinding
verify_directory_binding(binding: DirectoryBinding) -> None
```

- [ ] **Step 1: nonblocking contention red test를 쓴다**

별도 child process가 same stable lock을 보유하게 하고 parent가
`blocking=False`로 즉시 실패하는지 측정한다. 같은-process nested lock과
`blocking=True` default 회귀도 유지한다.

```python
def test_stable_lock_nonblocking_reports_busy(tmp_path):
    brain_root = tmp_path / "brain"
    with _other_process_holding_stable_lock(brain_root):
        with pytest.raises(CorpusIOError) as exc:
            with stable_corpus_lock(
                brain_root,
                exclusive=True,
                blocking=False,
            ):
                raise AssertionError("lock body must not run")
    assert exc.value.code == "corpus_lock_busy"
```

- [ ] **Step 2: anchored staging red tests를 쓴다**

정상 direct child의 mode/type/binding을 확인한다. symlink parent, existing child,
FIFO, parent inode replacement, child replacement, 다른 filesystem은 첫 payload write
전에 실패해야 한다.

```python
def test_anchored_staging_detects_child_replacement(tmp_path):
    parent = _real_directory(tmp_path / "snapshots")
    child = create_anchored_temp_directory(parent, prefix=".task17-")
    _replace_directory_binding(child.path)
    with pytest.raises(CorpusIOError) as exc:
        verify_directory_binding(child)
    assert exc.value.code == "path_binding_changed"
```

- [ ] **Step 3: lock과 directory helpers를 최소 구현한다**

nonblocking mode는 `fcntl.LOCK_NB`를 추가하고 `EACCES`/`EAGAIN`만
`corpus_lock_busy`로 변환한다. directory 생성은 pinned parent fd에 relative한
`os.mkdir`만 사용하고 같은 fd에서 child를 `O_DIRECTORY|O_NOFOLLOW`로 다시 연 뒤
device/inode를 저장한다. `tempfile.mkdtemp()`와 path-based 선행 `mkdir`는 쓰지
않는다.

- [ ] **Step 4: targeted와 기존 corpus I/O 회귀를 통과시킨다**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m pytest tests/test_corpus_io.py \
  -k 'stable_corpus_lock or anchored' -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m pytest tests/test_corpus_io.py -q
```

Expected: PASS.

- [ ] **Step 5: exact files만 commit한다**

```bash
git -C "$ENGINE" add src/project_brain/corpus_io.py tests/test_corpus_io.py
git -C "$ENGINE" diff --cached --check
git -C "$ENGINE" commit -m "feat(brain): add fail-fast corpus coordination"
```

---

### Task 6: Canonical repair CLI와 엔진 문서를 마무리한다

**Files:**

- Modify: `src/project_brain/cli.py:1563-1690`
- Modify: `tests/test_cli.py`
- Modify: `docs/design-canonical.md`
- Modify: `ROADMAP.md`

**Interfaces:**

- Produces commands:

```text
project-brain migration canonical-repair plan
project-brain migration canonical-repair apply
```

- `plan` requires `--decisions-file`, `--classification-file`, both expected SHA
  args, explicit brain/repo/engine/snapshot roots, snapshot manifest SHA,
  `--engine-sha`, `--manifest`.
- `apply` requires the same trusted inputs plus `--expected-manifest-sha256`.
- Existing `migration id` and `migration display` flags remain backward compatible.

- [ ] **Step 1: CLI plan/apply red tests를 쓴다**

```python
def test_canonical_repair_cli_plan_is_read_only_and_apply_is_receipt_bound(
    tmp_path,
):
    fixture = _canonical_cli_fixture(tmp_path)
    before = corpus_fingerprint(BrainStore.load(fixture.brain_root))
    assert _run_cli(fixture.plan_argv) == 0
    assert corpus_fingerprint(BrainStore.load(fixture.brain_root)) == before
    assert _run_cli(fixture.apply_argv_with_wrong_sha) == 1
    assert _run_cli(fixture.apply_argv) == 0
```

stdout JSON은 `ok`, `migration_kind`, manifest path/SHA, transaction ID,
row/action count, ledger/classification SHA, snapshot ID/SHA를 exact key로 출력한다.
error JSON은 traceback 없이 `ok=false`, `error_code`, `error`를 출력한다.

- [ ] **Step 2: CLI parser와 routing을 구현한다**

`_run_migration()`의 mode에 `canonical-repair`를 추가하되 기존 id/display branch를
바꾸지 않는다. plan은 `parse_canonicalization_ledger()` 뒤
`plan_canonical_repair()`, apply는 `apply_canonical_repair_artifact()`만 호출한다.

- [ ] **Step 3: CLI targeted tests를 통과시킨다**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m pytest tests/test_cli.py \
  -k 'canonical_repair' -q
```

Expected: PASS.

- [ ] **Step 4: canonical design과 roadmap을 현재 계약으로 갱신한다**

`docs/design-canonical.md`에는 ID-only와 canonical repair의 분리, decision ledger,
intermediate snapshot, 두 사용자 gate를 기록한다. `ROADMAP.md`에는 Task 17이
구현 중이며 완료 조건이 engine commit, 두 승인, BB2 commit, final binding이라는
사실을 적는다. 아직 완료로 표시하지 않는다.

- [ ] **Step 5: 전체 엔진 회귀를 실행한다**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m pytest -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m unittest discover \
  -s "$ENGINE/src/project_brain/templates/ingest/scripts" -p 'test_*.py'
```

Expected: 두 명령 모두 exit 0, skip이나 collection error 없음.

- [ ] **Step 6: engine 변경을 독립 리뷰하고 수정 사항을 재검증한다**

리뷰 범위는 `ENGINE_BASELINE_SHA..HEAD`의 code/test/docs 전체다. 다음을 명시적으로
확인한다.

- strict ID grammar 불변
- canonical repair 허용 pointer가 2종뿐임
- existing target/merge/delete-only fail-closed
- source SHA, ledger, classification, snapshot, engine, corpus binding exact
- target-derived ReviewRecord 예외가 다른 valid object를 열지 않음
- default stable lock caller 동작 불변

리뷰에서 수정하면 해당 targeted tests와 Step 5 전체 회귀를 다시 실행한다.

- [ ] **Step 7: docs/CLI와 review fix만 commit한다**

```bash
git -C "$ENGINE" add \
  src/project_brain/cli.py \
  tests/test_cli.py \
  docs/design-canonical.md \
  ROADMAP.md
git -C "$ENGINE" diff --cached --check
git -C "$ENGINE" commit -m "docs(brain): document canonical id recovery"
ENGINE_SHA=$(git -C "$ENGINE" rev-parse HEAD)
test -z "$(git -C "$ENGINE" status --porcelain=v1 --untracked-files=all)"
```

review fix가 다른 engine source/test를 바꿨다면 exact path를 같은 commit에 추가하고
cached allowlist를 기록한다. `ENGINE_SHA`가 이후 모든 Phase A, snapshot, staging,
live receipt의 유일한 engine binding이다.

---

### Task 7: Durable Phase A scanner와 새 pre-Task17 snapshot을 만든다

**Files:**

- Create in BB2:
  `brain/recovery/2026-07-28/id-migration/scan_task17.py`
- Create in BB2:
  `brain/recovery/2026-07-28/id-migration/test_scan_task17.py`
- Create in BB2:
  `brain/recovery/2026-07-28/id-migration/phase-a-measurement.json`
- Create in BB2:
  `brain/recovery/2026-07-28/id-migration/phase-a-classification.json`
- Create in BB2:
  `brain/recovery/2026-07-28/id-migration/phase-a-feasibility.json`
- Create outside Git:
  `$BB2/.snapshots/2026-07-31/task17-pre-canonical/task17-pre-canonical/`

**Interfaces:**

- `scan_task17.py` produces:

```python
@dataclass(frozen=True)
class PhaseABinding:
    schema_version: int
    engine_sha: str
    repo_head: str
    corpus_fingerprint: str
    eval_sha256: str
    stale_sha256: str | None
```

```text
scan_phase_a(*, brain_root: Path, repo_root: Path, engine_root: Path,
  engine_sha: str) -> tuple[dict, dict, dict]
write_phase_a(outputs: tuple[dict, dict, dict], *, output_root: Path)
  -> dict[str, str]
```

각 output은 top-level `binding`에 `PhaseABinding`의 canonical dict를 넣는다. 나머지
measurement/classification/feasibility key와 row schema는 기존 Phase A semantic
projection을 유지하고 unknown key를 만들지 않는다.

- [ ] **Step 1: 사용자 dirt와 source checkout content baseline을 먼저 캡처한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery
BB2=/Users/al03040455/Desktop/bb2_client
SOURCE_CHECKOUT=/Users/al03040455/Downloads/codes/project-brain
TASK17_RECEIPTS=$(mktemp -d /private/tmp/project-brain-task17-receipts-XXXXXXXX)
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -c \
  'from pathlib import Path
from project_brain.snapshot import capture_git_dirt_receipt
import sys
for label, root, stem in (("bb2", sys.argv[1], "bb2"), ("source", sys.argv[2], "source")):
    receipt = capture_git_dirt_receipt(Path(root), label=label)
    out = Path(sys.argv[3])
    (out / f"{stem}.status").write_bytes(receipt.status_bytes)
    (out / f"{stem}.content.json").write_bytes(receipt.content_manifest_bytes)
    (out / f"{stem}.receipt.txt").write_text(
        f"{receipt.entry_count} {len(receipt.status_bytes)} {receipt.status_sha256} {receipt.content_manifest_sha256}\n",
        encoding="utf-8",
    )' \
  "$BB2" "$SOURCE_CHECKOUT" "$TASK17_RECEIPTS"
```

Expected: BB2 status tuple
`32/2209/4c227b67a7e040498003d9beeed5be73366981f33fe3bc8639dd055ab2cd0c23`, source tuple
`17/751/72d1449a578815cc57d86ad8c2022506b520c48e1ab3baca3350e7a5f418f93f`, staged path 0. content SHA는 이 시점에 새로 발급하고 이후 모든
gate에서 exact 재사용한다.

이 tuple이 실행 전에 다시 달라졌다면 새 변화를 Task 17 소유로 간주하지 않는다.
어떤 path가 달라졌는지 보고하고 사용자에게 새 baseline 포함 여부를 확인받기 전에는
scanner/test/recovery 파일도 만들지 않는다.

- [ ] **Step 2: post-ingame snapshot과 현재 live를 대조한다**

```bash
POST_INGAME_ROOT="$BB2/.snapshots/2026-07-28/brain-ingest-recovery-post-ingame/post-ingame-20260728"
POST_INGAME_SHA=e4093569753a26ea3f49adc6568c2942a52499e3dda695fe12fa95c4ff0feaa9
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m project_brain.cli snapshot verify \
  --snapshot-root "$POST_INGAME_ROOT" \
  --expected-manifest-sha256 "$POST_INGAME_SHA"
```

snapshot manifest의 brain file hashes와 현재 live object/eval/index/stale hashes를
read-only 비교한다. 불일치가 하나라도 있으면 새 snapshot을 만들지 않는다.

- [ ] **Step 3: 새 engine-bound pre-Task17 snapshot을 만들고 verify한다**

```bash
PRE_TASK17_OUT="$BB2/.snapshots/2026-07-31/task17-pre-canonical"
PRE_TASK17_ID=task17-pre-canonical
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m project_brain.cli snapshot create \
  --brain-root "$BB2/brain" \
  --repo-root "$BB2" \
  --engine-root "$ENGINE" \
  --output-root "$PRE_TASK17_OUT" \
  --snapshot-id "$PRE_TASK17_ID" \
  > "$TASK17_RECEIPTS/pre-task17-create.json"
PRE_TASK17_SHA=$(
  "$ENGINE/.venv/bin/python" -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["manifest_sha256"])' \
  "$TASK17_RECEIPTS/pre-task17-create.json"
)
PRE_TASK17_ROOT="$PRE_TASK17_OUT/$PRE_TASK17_ID"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m project_brain.cli snapshot verify \
  --snapshot-root "$PRE_TASK17_ROOT" \
  --expected-manifest-sha256 "$PRE_TASK17_SHA"
```

새 manifest의 `repo_head`는 BB2 기준 HEAD, `engine_head`는 `ENGINE_SHA`여야 한다.
brain scope/corpus/index/stale는 post-ingame snapshot과 exact여야 한다.

- [ ] **Step 4: scanner synthetic red test를 쓴다**

합성 fixture는 invalid source, current-valid dependent ReviewRecord, registry ref,
eval ref, stale ref, existing-target collision, mapping-key mismatch, mixed review를
각각 하나 이상 포함한다.

```python
def test_scan_phase_a_classifies_without_mutating_fixture(tmp_path):
    fixture = make_phase_a_fixture(tmp_path)
    before = tree_fingerprint(fixture.brain_root)
    measurement, classification, feasibility = scan_phase_a(**fixture.args)
    assert measurement["summary"]["invalid_object_count"] == 7
    assert classification["summary"]["classification_row_count_including_induced_review"] == 8
    assert feasibility["outcome"] == "blocked"
    assert tree_fingerprint(fixture.brain_root) == before
```

- [ ] **Step 5: scanner를 구현하고 synthetic test를 통과시킨다**

scanner는 Project Brain lint, ID grammar, registered reference iterator와 existing
planner를 import한다. ID 제안은 기존 object에 canonical projected field가 이미 있는
경우만 계산하고, 109개 semantic row에는 `proposed_new_id_or_null: null`을 유지한다.

```bash
cd "$BB2"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m unittest \
  brain/recovery/2026-07-28/id-migration/test_scan_task17.py -v
```

Expected: PASS.

- [ ] **Step 6: 현재 corpus에서 durable evidence 세 개를 생성한다**

```bash
PHASE_A_ROOT="$BB2/brain/recovery/2026-07-28/id-migration"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" "$PHASE_A_ROOT/scan_task17.py" \
  --brain-root "$BB2/brain" \
  --repo-root "$BB2" \
  --engine-root "$ENGINE" \
  --engine-sha "$ENGINE_SHA" \
  --output-root "$PHASE_A_ROOT" \
  > "$TASK17_RECEIPTS/phase-a-run.json"
```

Expected exact semantic baseline:

- store objects 10,943
- invalid objects/problems 155/158
- classification rows 156
- safe ID-only self renames 31
- safe closure 뒤 invalid/problems 125/128
- 109 human-ID decisions, 4 mapping repairs, 2 collisions, 1 mixed review

기존 임시 JSON이 읽히면 binding metadata를 제외한 semantic projection을 비교한다.
기존 bytes에 의존하거나 새 파일을 임시 bytes에 맞춰 수정하지 않는다.

- [ ] **Step 7: live 불변과 recovery allowlist만 늘었는지 확인한다**

`corpus_fingerprint`, eval/index/stale SHA, BB2 HEAD, staged path는 시작과 exact여야
한다. 새 status entry는 scanner/test/Phase A JSON 다섯 path만 허용하며 기존 32개
status/content receipt는 그대로여야 한다.

---

### Task 8: 156행 결정 원장을 완성하고 사용자 승인 게이트 1에서 멈춘다

**Files:**

- Create in BB2:
  `brain/recovery/2026-07-28/id-migration/canonicalization-decisions.json`
- Read: durable Phase A JSON 세 개와 그 행이 가리키는 source/evidence files
- Does not modify: object, eval, index, stale files

**Interfaces:**

- Produces one canonical JSON ledger accepted by
  `parse_canonicalization_ledger()` with unresolved row 0.
- Top-level exact keys are `version`, `phase_a_classification_sha256`,
  `engine_sha`, `repo_head`, `corpus_fingerprint`, `decisions`.
- Every decision row has exact keys `source_id`, `source_kind`, `source_sha256`,
  `action`, `new_id`, `field_changes`, `decision_reason`, `decision_evidence`.

- [ ] **Step 1: Phase A 156행에서 review worksheet를 만든다**

worksheet는 Git 밖 `$TASK17_RECEIPTS/decision-review.json`에 만들고 source row,
object payload, inbound/outbound refs, path/symbol/title/context/evidence, target 존재
여부를 함께 담는다. 이 파일은 ID를 제안하지 않는다.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" "$PHASE_A_ROOT/scan_task17.py" \
  --brain-root "$BB2/brain" \
  --repo-root "$BB2" \
  --engine-root "$ENGINE" \
  --engine-sha "$ENGINE_SHA" \
  --review-workbook "$TASK17_RECEIPTS/decision-review.json"
```

- [ ] **Step 2: 기계적으로 결정 가능한 31개와 reference-only 행을 기록한다**

Phase A의 safe one-to-one target만 `id_only_rename`으로 옮긴다. bundle review의
self ID는 유지하고 `reference_only`로 기록한다. 모든 source SHA와 reason은 Phase A
row에서 exact 복사한다.

- [ ] **Step 3: 109개 canonical ID를 근거와 함께 검토한다**

CodeLocator는 path, symbol, title, context와 anchor 의미를, EvidenceRef는 evidence
종류와 연결 locator/manifest를, GlossaryTerm은 term/context/연결 mapping을 함께 본다.
각 행의 `decision_reason`은 선택한 context/key/anchor를 설명하고
`decision_evidence`는 실제 worksheet pointer 또는 BB2 source path를 한 개 이상
가진다. 문법 통과만을 이유로 쓰지 않는다.

- [ ] **Step 4: 네 mapping, 두 collision, mixed review를 결정한다**

- Sally DomainMapping 4개는 new ID와 `/mapping_key` before/after를 exact 기록한다.
- collision 2개는 기존 target과 source payload 비교 근거를 남기고 서로 다른 비어
  있는 ID를 `collision_distinct_rename`으로 선택한다.
- merge/supersede가 필요하면 ledger를 완성하지 않고 Task 17을 중단한다.
- mixed ReviewRecord는 기존 DomainMapping target을 보존하고 invalid non-mapping
  target만 제거하는 exact `/target_object_ids` before/after를 기록한다. 이 규칙으로
  해결되지 않으면 중단한다.

- [ ] **Step 5: 종속 ReviewRecord와 eval 기대값을 계산한다**

승인 후보 target map에서 11개 single ReviewRecord self ID를 `review.` prefix와
각 new target ID의 결합으로 계산해 `target_derived_review_rename`으로 기록한다.
eval 3 pointers가 old→new로 정확히 닫히는지 별도 report로 출력한다.

- [ ] **Step 6: strict engine validator를 read-only 실행한다**

```bash
DECISIONS="$PHASE_A_ROOT/canonicalization-decisions.json"
CLASSIFICATION="$PHASE_A_ROOT/phase-a-classification.json"
DECISIONS_SHA=$(LC_ALL=C shasum -a 256 "$DECISIONS" | awk '{print $1}')
CLASSIFICATION_SHA=$(LC_ALL=C shasum -a 256 "$CLASSIFICATION" | awk '{print $1}')
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -c \
  'from pathlib import Path
from project_brain.canonical_repair import parse_canonicalization_ledger
from project_brain.store import BrainStore
import sys
ledger = parse_canonicalization_ledger(
    Path(sys.argv[1]).read_bytes(),
    classification_bytes=Path(sys.argv[2]).read_bytes(),
    expected_classification_sha256=sys.argv[3],
    existing=BrainStore.load(Path(sys.argv[4])),
    engine_sha=sys.argv[5],
    repo_head=sys.argv[6],
)
print(ledger.sha256, len(ledger.decisions))' \
  "$DECISIONS" "$CLASSIFICATION" "$CLASSIFICATION_SHA" \
  "$BB2/brain" "$ENGINE_SHA" 53671bce5e94edf38a7afa11706963581065fb0f
```

Expected: 156행, duplicate/missing/unresolved 0, target collision 0, target-derived
closure exact, live object/eval/index/stale 불변.

- [ ] **Step 7: 사용자에게 의미 승인 자료를 제시하고 멈춘다**

제시할 내용:

- ledger SHA와 classification SHA
- action/kind/context별 counts
- 109개 ID old→new와 근거
- mapping 4개 field diff
- collision 2개 payload 비교와 distinct target
- mixed review exact diff
- dependent ReviewRecord 11개와 eval 3 pointers
- engine/BB2 HEAD, live fingerprint, 사용자 dirt 불변 receipt

**승인 게이트 1:** 사용자가 이 ledger bytes를 명시적으로 승인하기 전에는 Task 9를
시작하지 않는다. ledger bytes가 바뀌면 기존 승인은 무효다.

---

### Task 9: BB2 one-shot runner를 합성 fixture로 구현하고 staging canonical repair를 검증한다

**Files:**

- Create in BB2:
  `brain/recovery/2026-07-28/id-migration/run_task17_live.py`
- Create in BB2:
  `brain/recovery/2026-07-28/id-migration/test_run_task17_live.py`
- Create in BB2:
  `brain/recovery/2026-07-28/id-migration/canonical-repair.manifest.json`
- Create in BB2:
  `brain/recovery/2026-07-28/id-migration/canonical-repair-dry-run-report.json`
- Create outside Git: anchored staging and staging intermediate snapshot

**Interfaces:**

- `run_task17_live.py` produces:

```python
@dataclass(frozen=True)
class Task17Config:
    brain_root: Path
    repo_root: Path
    engine_root: Path
    engine_sha: str
    source_checkout_root: Path
    pre_snapshot_root: Path
    pre_snapshot_sha256: str
    decisions_path: Path
    decisions_sha256: str
    classification_path: Path
    classification_sha256: str
    canonical_manifest_path: Path
    id_manifest_path: Path
    receipts_root: Path


```

```text
run_staging(config: Task17Config) -> dict[str, object]
run_live(config: Task17Config, *,
  failure_injector: Callable[[str], None] | None = None)
  -> dict[str, object]
```

runner는 engine API만 호출하고 ID를 추론하거나 ledger를 수정하지 않는다.

- [ ] **Step 1: runner preflight와 failure matrix red tests를 쓴다**

합성 Git repo/engine, corpus, snapshot, 8행 ledger를 사용한다. failure point는
`before_canonical_apply`, `after_canonical_apply`, `after_intermediate_snapshot`,
`before_id_apply`, `after_id_apply`, `after_rebuild`, `after_checks`다.

```python
@pytest.mark.parametrize("point", LIVE_FAILURE_POINTS)
def test_live_runner_restores_pre_snapshot_before_commit(tmp_path, point):
    fixture = make_runner_fixture(tmp_path)
    before = fixture.full_brain_fingerprint()
    with pytest.raises(Task17RunnerError):
        run_live(fixture.config, failure_injector=fail_at(point))
    assert fixture.full_brain_fingerprint() == before
```

preflight drift는 `MutationService.apply`와 `restore_snapshot` 모두 호출되지 않아야
한다. post-canonical failure부터는 restore가 정확히 한 번 호출돼야 한다.

- [ ] **Step 2: runner preflight와 restore state machine을 구현한다**

`run_live()`는
`stable_corpus_lock(config.brain_root, exclusive=True, blocking=False)`를 한 번 잡고
끝까지 유지한다. lock 안에서 engine clean, BB2/source dirt, HEAD, snapshot,
corpus/index/stale, ledger/manifest receipt를 다시 확인한다. 첫 live write 뒤 exception은
같은 lock scope에서 `restore_snapshot()`을 호출하고 restored fingerprint를 검증한 뒤
원래 error와 restore receipt를 함께 보고한다.

- [ ] **Step 3: synthetic runner tests를 모두 통과시킨다**

```bash
cd "$BB2"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m pytest \
  brain/recovery/2026-07-28/id-migration/test_run_task17_live.py -q
```

Expected: PASS. 합성 test는 실제 BB2 live corpus나 실모델을 사용하지 않는다.

- [ ] **Step 4: anchored staging을 만들고 pre-snapshot을 복원한다**

`create_anchored_temp_directory(Path("$BB2/.snapshots"),
prefix=".task17-staging-")`와 `create_anchored_directory()`만 사용한다. staging root는
exact `.snapshots` direct child이고 live brain과 동일·상위·하위가 아니어야 한다.
binding을 restore 전후 재검증한다.

- [ ] **Step 5: staging canonical repair plan/apply를 실행한다**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m project_brain.cli migration canonical-repair plan \
  --brain-root "$STAGING_BRAIN" \
  --repo-root "$BB2" \
  --engine-root "$ENGINE" \
  --snapshot-root "$PRE_TASK17_ROOT" \
  --expected-snapshot-manifest-sha256 "$PRE_TASK17_SHA" \
  --decisions-file "$DECISIONS" \
  --expected-decisions-sha256 "$DECISIONS_SHA" \
  --classification-file "$CLASSIFICATION" \
  --expected-classification-sha256 "$CLASSIFICATION_SHA" \
  --manifest "$PHASE_A_ROOT/canonical-repair.manifest.json" \
  --engine-sha "$ENGINE_SHA"
```

apply는 위 plan이 출력한 exact manifest SHA를 요구한다. supplied bytes와 fresh replan
bytes가 다르면 staging도 쓰지 않는다.

- [ ] **Step 6: staging intermediate snapshot과 repair gate를 검증한다**

intermediate snapshot은 pre snapshot과 다른 ID/SHA를 사용하고 staging brain,
현재 BB2 HEAD, `ENGINE_SHA`에 묶는다. 다음을 report에 기록한다.

- repair source 5개 canonical
- 정확히 repair 대상 structured problems만 감소
- 남은 grandfathered problem ID/message exact
- dangling 0, 새 non-ID lint 0
- ledger 밖 payload diff 0
- canonical manifest, ledger, classification, snapshot SHA
- live corpus/index/stale와 기존 dirt 불변

하나라도 실패하면 staging을 폐기하고 Task 10으로 넘어가지 않는다.

---

### Task 10: Staging ID-only migration과 전체 품질 gate를 통과시킨다

**Files:**

- Create in BB2:
  `brain/recovery/2026-07-28/id-migration/id-migration.manifest.json`
- Create in BB2:
  `brain/recovery/2026-07-28/id-migration/dry-run-report.json`
- Modify: staging copy only
- Read-only verify: live BB2, engine, source checkout

**Interfaces:**

- Consumes approved decision ledger, canonical repair artifact and verified staging
  intermediate snapshot.
- Produces an ID-only artifact whose rename map comes only from
  `id_renames_from_trusted_repair_receipt()`.
- Produces user approval gate 2 report. No live mutation.

- [ ] **Step 1: intermediate receipt에서 pure ID rename map을 파생한다**

```python
renames = id_renames_from_trusted_repair_receipt(
    decisions_bytes=decisions_path.read_bytes(),
    expected_decisions_sha256=decisions_sha256,
    classification_bytes=classification_path.read_bytes(),
    expected_classification_sha256=classification_sha256,
    canonical_manifest_bytes=canonical_manifest_path.read_bytes(),
    expected_canonical_manifest_sha256=canonical_manifest_sha256,
    existing=BrainStore.load(staging_brain),
    intermediate_snapshot=verified_intermediate_snapshot,
)
```

이 함수는 canonical artifact의 expected-after fingerprint가 staging current
fingerprint 및 intermediate snapshot fingerprint와 모두 같고, ledger/classification
SHA와 pure rename map이 artifact bytes에 고정된 경우만 반환한다.

- [ ] **Step 2: ID-only plan/apply를 staging에서 실행한다**

`plan_id_migration()`에 위 map과 staging intermediate snapshot을 전달한다.
`create_migration_artifact()` 결과를 `id-migration.manifest.json`에 canonical bytes로
쓰고 SHA를 별도 receipt에 기록한다. apply 전에 같은 inputs로 fresh replan한 bytes가
exact인지 확인한다.

```python
plan = plan_id_migration(
    existing=BrainStore.load(staging_brain),
    brain_root=staging_brain,
    repo_root=bb2_root,
    engine_root=engine_root,
    engine_sha=engine_sha,
    renames=renames,
    snapshot=verified_intermediate_snapshot,
)
artifact = create_migration_artifact(plan)
```

- [ ] **Step 3: 최종 staging 구조 gate를 실행한다**

다음을 모두 machine-readable dry-run report에 기록한다.

- structured ID problem 0
- dangling reference 0
- source→target one-to-one, target pre-existence 0
- object/eval 변경이 두 manifests의 action/pointer와 exact
- self ID, registered refs, approved repair pointer 밖 payload drift 0
- Phase A 156행 전부가 canonical repair 또는 ID manifest에 정확히 한 번 귀속
- eval expected ID missing 0
- index/stale invalidation이 manifest에 기록되고 staging derived files가 stale로 남지 않음

- [ ] **Step 4: staging용 checks/config를 no-follow로 복사한다**

verified BB2 root에서 `.project-brain.json`, `brain/checks`와 checks가 직접 읽는 recovery
evidence를 exact regular-file allowlist로 staging root에 복사한다. symlink, special
file, source SHA drift는 거부한다. checks 안의 `REPO_ROOT`가 staging root를 가리키는지
test discovery 전에 확인한다.

- [ ] **Step 5: 실코퍼스 unittest를 staging에 실행한다**

```bash
cd "$STAGING_ROOT"
PATH="$ENGINE/.venv/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m unittest discover \
  -s "$STAGING_BRAIN/checks" -p 'test_*.py' -v \
  > "$TASK17_RECEIPTS/staging-real-corpus-tests.txt" 2>&1
```

Expected: `RealCorpusRebuildGuard.test_rebuild_row_counts`가 `ok`, skipped 0,
failure/error 0. `project-brain`은 exact engine venv의 executable이어야 한다.

- [ ] **Step 6: 격리된 staging index를 실제 모델로 rebuild하고 eval한다**

```bash
cd "$STAGING_ROOT"
/usr/bin/env -u PROJECT_BRAIN_EMBEDDER \
  PATH="$ENGINE/.venv/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m project_brain.cli index rebuild \
  --brain-root "$STAGING_BRAIN" \
  --db "$STAGING_BRAIN/.brain-local/index.db" \
  > "$TASK17_RECEIPTS/staging-index-rebuild.json"
/usr/bin/env -u PROJECT_BRAIN_EMBEDDER \
  PATH="$ENGINE/.venv/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m project_brain.cli eval \
  --scenarios "$STAGING_BRAIN/eval_scenarios.json" \
  > "$TASK17_RECEIPTS/staging-eval.json"
```

Expected: rebuild `embed_model == "BAAI/bge-m3"`, eval `15/15`, targeted
query/recall에서 renamed object와 근거가 expected channel로 회수됨.

- [ ] **Step 7: audit/lint와 live 불변을 확인한다**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m project_brain.cli lint \
  --brain-root "$STAGING_BRAIN"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m project_brain.cli audit \
  --brain-root "$STAGING_BRAIN" \
  --repo-root "$BB2" \
  --no-fetch
```

live corpus/index/stale, BB2 HEAD, engine HEAD/clean, source/BB2 baseline dirt
content receipts, staged path 0이 모두 이전과 exact여야 한다.

- [ ] **Step 8: staging 결과를 독립 검토한다**

검토자는 decision ledger→canonical manifest→intermediate snapshot→ID manifest의
SHA chain, two-operation payload diff, runner failure tests, staging commands의 exact
interpreter, rebuild model, checks skipped 0, eval 15/15, live 불변을 확인한다.

- [ ] **Step 9: 사용자 승인 게이트 2에서 멈춘다**

사용자에게 두 manifest bytes/SHA, intermediate snapshot receipt, dry-run report,
checks/audit/lint/eval/rebuild 출력, live/user dirt 불변 receipt를 제시한다.

**승인 게이트 2:** 사용자가 이 exact staging bundle을 명시적으로 승인하기 전에는
Task 11을 시작하지 않는다. ledger, manifest, runner, engine SHA, snapshot receipt 중
하나라도 바뀌면 staging을 다시 만들고 재승인받는다.

---

### Task 11: Stable lock 아래 live 두 operation을 적용하고 검증한다

**Files:**

- Create in BB2:
  `brain/recovery/2026-07-28/id-migration/canonical-repair-live-report.json`
- Create in BB2:
  `brain/recovery/2026-07-28/id-migration/live-report.json`
- Modify: approved manifests에 열거된 live objects와 `eval_scenarios.json`
- Invalidate/rebuild: live `.brain-local/index.db*`, stale-set
- Create outside Git: live intermediate snapshot and transient staging child

**Interfaces:**

- Consumes the exact user-approved Task 10 bundle.
- Produces final verified but uncommitted live state.
- The runner owns the complete lock/apply/restore chain; shell에서 live mutation CLI를
  따로 호출하지 않는다.

- [ ] **Step 1: 승인된 inputs를 lock 밖에서 먼저 확인한다**

확인값:

- engine HEAD `ENGINE_SHA`, tracked/staged/nonignored untracked 0
- BB2 HEAD `53671bce5e94edf38a7afa11706963581065fb0f`, staged 0
- source/BB2 baseline status와 content receipts exact
- pre-Task17 snapshot explicit verify
- ledger/classification/two manifest/runner/test SHA가 gate 2와 exact
- live corpus/index/stale가 pre-Task17 baseline과 exact
- `PROJECT_BRAIN_EMBEDDER` unset

불일치 시 stable lock을 잡지 않고 중단한다.

- [ ] **Step 2: reviewed runner를 live mode로 정확히 한 번 실행한다**

runner는 verified BB2 Git root descriptor에서 lexical `brain`을
`O_DIRECTORY|O_NOFOLLOW`로 열고 device/inode를 stable lock 전체에서 재검증한다.
symlink alias나 binding replacement는 첫 live write 전에 거부한다.

```bash
/usr/bin/env -u PROJECT_BRAIN_EMBEDDER \
  PATH="$ENGINE/.venv/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" \
  "$PHASE_A_ROOT/run_task17_live.py" live \
  --brain-root "$BB2/brain" \
  --repo-root "$BB2" \
  --engine-root "$ENGINE" \
  --engine-sha "$ENGINE_SHA" \
  --source-checkout-root "$SOURCE_CHECKOUT" \
  --pre-snapshot-root "$PRE_TASK17_ROOT" \
  --pre-snapshot-sha256 "$PRE_TASK17_SHA" \
  --decisions "$DECISIONS" \
  --decisions-sha256 "$DECISIONS_SHA" \
  --classification "$CLASSIFICATION" \
  --classification-sha256 "$CLASSIFICATION_SHA" \
  --canonical-manifest "$PHASE_A_ROOT/canonical-repair.manifest.json" \
  --canonical-manifest-sha256 "$CANONICAL_MANIFEST_SHA" \
  --id-manifest "$PHASE_A_ROOT/id-migration.manifest.json" \
  --id-manifest-sha256 "$ID_MANIFEST_SHA" \
  --baseline-receipts "$TASK17_RECEIPTS" \
  --report-root "$PHASE_A_ROOT"
```

- [ ] **Step 3: runner의 lock 안 실행 순서를 receipt로 확인한다**

live report event sequence는 exact 다음 순서다.

1. `stable_lock_acquired`
2. `locked_preflight_verified`
3. `canonical_replan_equal`
4. `canonical_apply_complete`
5. `intermediate_snapshot_verified`
6. `id_staging_replan_equal`
7. `id_apply_complete`
8. `derived_invalidated`
9. `real_index_rebuild_complete`
10. `checks_complete`
11. `final_live_verified`
12. `stable_lock_released`

intermediate ID artifact는 live intermediate snapshot ID/SHA에 새로 묶되 Task 10의
approved ID artifact bytes와 exact여야 한다. child process는 pinned staging root만
받고 live brain을 읽거나 잠그지 않는다.

- [ ] **Step 4: live 최종 gate를 독립 명령으로 재검증한다**

```bash
PATH="$ENGINE/.venv/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m unittest discover \
  -s "$BB2/brain/checks" -p 'test_*.py' -v \
  > "$TASK17_RECEIPTS/live-real-corpus-tests.txt" 2>&1
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m project_brain.cli audit \
  --brain-root "$BB2/brain" --repo-root "$BB2" --no-fetch
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m project_brain.cli eval \
  --scenarios "$BB2/brain/eval_scenarios.json"
```

Expected: structured ID 0, dangling 0, payload drift 0, checks skipped 0,
eval 15/15, live rebuild report `BAAI/bge-m3`, user dirt exact, staged 0.

- [ ] **Step 5: 실패 경계를 판정한다**

- runner가 첫 live write 전에 실패했다면 live 불변만 확인하고 restore하지 않는다.
- 첫 live write 뒤 실패했다면 pre-Task17 snapshot restore receipt와
  corpus/index/stale exact 복원을 확인한다. recovery bundle과 사용자 dirt는 복구
  대상이 아니다.
- restore 자체가 실패하면 자동 재시도나 수동 덮어쓰기를 하지 않고 recovery state와
  evidence path를 보존한 채 중단한다.

- [ ] **Step 6: verified live diff를 독립 리뷰한다**

리뷰자는 two manifests와 actual object/eval diff, transaction receipts, live
intermediate snapshot, index model/counts, ID/dangling/lint/audit/eval, source/BB2 dirt,
commit 후보 allowlist를 비교한다. PASS 전에는 Task 12로 가지 않는다.

---

### Task 12: Task 17 exact paths만 강제 stage하고 BB2 commit을 만든다

**Files:**

- Stage/commit: two live manifests가 열거한 object/eval paths와 File Map의 recovery
  bundle 14 files only
- Update before stage:
  `brain/recovery/2026-07-28/id-migration/live-report.json`
- Exclude: `.brain-local/**`, `.snapshots/**`, transient staging/check copies,
  `/private/tmp` receipts, 기존 사용자 dirt

**Interfaces:**

- Produces a NUL-delimited `TASK17_STAGE_PATHS` whose decoded path set exactly equals
  the Task 17 commit tree diff.
- Produces one BB2 commit with parent
  `53671bce5e94edf38a7afa11706963581065fb0f`.

- [ ] **Step 1: pre-commit live report를 `pending_post_commit`으로 고정한다**

report에 final expected snapshot ID, two approvals, engine SHA, two manifest SHA,
final corpus/index/stale fingerprints, checks/eval receipts와
`final_snapshot_status: "pending_post_commit"`을 기록한다. post-commit 값을 미리
성공으로 쓰지 않는다.

- [ ] **Step 2: NUL exact pathspec을 생성하고 검증한다**

canonical/id live manifest의 creates, updates, deletes, renames 양쪽과 recovery bundle
14 files를 정렬·중복 제거한다. 모든 path는 lexical BB2-relative이고 symlink가 아니며
실행 시 캡처한 기존 dirt path와 disjoint여야 한다.

```bash
TASK17_STAGE_PATHS="$TASK17_RECEIPTS/task17-stage-paths.zlist"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" "$PHASE_A_ROOT/run_task17_live.py" stage-paths \
  --repo-root "$BB2" \
  --canonical-manifest "$PHASE_A_ROOT/canonical-repair.manifest.json" \
  --id-manifest "$PHASE_A_ROOT/id-migration.manifest.json" \
  --output "$TASK17_STAGE_PATHS" \
  --baseline-receipts "$TASK17_RECEIPTS"
```

- [ ] **Step 3: ignored `/brain` paths를 exact force-stage한다**

```bash
git -C "$BB2" --literal-pathspecs add -f \
  --pathspec-from-file="$TASK17_STAGE_PATHS" \
  --pathspec-file-nul
git -C "$BB2" diff --cached --check
git -C "$BB2" diff --cached --name-only -z \
  > "$TASK17_RECEIPTS/cached-paths.zlist"
cmp "$TASK17_STAGE_PATHS" "$TASK17_RECEIPTS/cached-paths.zlist"
```

`cmp`가 실패하면 commit하지 않는다. 승인된 Task 17 path만 다음 명령으로 unstage한
뒤 원인을 조사한다.

```bash
git -C "$BB2" --literal-pathspecs restore --staged \
  --pathspec-from-file="$TASK17_STAGE_PATHS" \
  --pathspec-file-nul
```

- [ ] **Step 4: staged bytes와 사용자 dirt를 마지막으로 확인한다**

cached object/eval bytes가 verified live files와 같고 recovery JSON/Python SHA가
reviewed receipts와 exact인지 확인한다. BB2 기존 dirt와 source checkout content
receipt는 그대로이고, Task 17 allowlist 밖 staged path는 0이어야 한다.

- [ ] **Step 5: BB2 Task 17 commit을 만든다**

```bash
test "$(git -C "$BB2" rev-parse HEAD)" = \
  53671bce5e94edf38a7afa11706963581065fb0f
git -C "$BB2" commit -m "fix(brain): canonicalize corpus object ids"
TASK17_COMMIT=$(git -C "$BB2" rev-parse HEAD)
test "$(git -C "$BB2" rev-parse "$TASK17_COMMIT^")" = \
  53671bce5e94edf38a7afa11706963581065fb0f
```

- [ ] **Step 6: commit tree와 live 상태를 검증한다**

`git diff-tree --no-commit-id --name-only -r -z "$TASK17_COMMIT"`을 pathspec과
exact 비교한다. commit 뒤 staged 0, 기존 사용자 dirt status/content exact,
structured ID/dangling 0/0, eval 15/15, engine clean을 확인한다.

---

### Task 13: Final snapshot과 Task 18 external binding을 고정한다

**Files:**

- Create outside Git:
  `$BB2/.snapshots/2026-07-31/task17-final/task17-final/`
- Create outside verified snapshot root:
  `$BB2/.snapshots/2026-07-31/task17-final/task18-binding.json`
- Does not modify: Task 17 commit

**Interfaces:**

- Produces final snapshot manifest SHA and canonical external binding SHA.
- Task 18 may start only after re-verifying both bytes and current live state.

- [ ] **Step 1: commit을 포함한 final full snapshot을 만든다**

```bash
FINAL_OUT="$BB2/.snapshots/2026-07-31/task17-final"
FINAL_ID=task17-final
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m project_brain.cli snapshot create \
  --brain-root "$BB2/brain" \
  --repo-root "$BB2" \
  --engine-root "$ENGINE" \
  --output-root "$FINAL_OUT" \
  --snapshot-id "$FINAL_ID" \
  > "$TASK17_RECEIPTS/final-snapshot-create.json"
FINAL_SNAPSHOT_ROOT="$FINAL_OUT/$FINAL_ID"
FINAL_SNAPSHOT_SHA=$(
  "$ENGINE/.venv/bin/python" -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["manifest_sha256"])' \
  "$TASK17_RECEIPTS/final-snapshot-create.json"
)
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m project_brain.cli snapshot verify \
  --snapshot-root "$FINAL_SNAPSHOT_ROOT" \
  --expected-manifest-sha256 "$FINAL_SNAPSHOT_SHA"
```

- [ ] **Step 2: final snapshot binding을 live와 대조한다**

manifest의 repo HEAD가 `TASK17_COMMIT`, engine HEAD가 `ENGINE_SHA`, corpus/index/stale
fingerprint가 Task 11 final report와 exact여야 한다. file count와 source fingerprint를
기록한다.

- [ ] **Step 3: snapshot 바깥에 Task 18 binding을 canonical JSON으로 쓴다**

```json
{
  "version": 1,
  "task17_commit": "40 lowercase hex",
  "engine_sha": "40 lowercase hex",
  "snapshot_id": "task17-final",
  "snapshot_manifest_sha256": "64 lowercase hex",
  "corpus_fingerprint": "64 lowercase hex",
  "index_fingerprint": "64 lowercase hex",
  "stale_fingerprint": "64 lowercase hex",
  "bb2_user_dirt_status_sha256": "64 lowercase hex",
  "bb2_user_dirt_content_sha256": "64 lowercase hex",
  "source_checkout_status_sha256": "64 lowercase hex",
  "source_checkout_content_sha256": "64 lowercase hex",
  "task18_allowed": true
}
```

binding은 sort-keys compact JSON + newline으로 쓰고 SHA-256을 별도 출력한다. verified
snapshot root 내부에는 어떤 파일도 추가하지 않는다.

- [ ] **Step 4: post-commit failure 정책을 지킨다**

snapshot create/verify 또는 binding write가 실패하면 `TASK17_COMMIT`을 reset, amend,
revert하지 않는다. 같은 HEAD와 verified live 상태를 유지하고 Task 17 incomplete,
Task 18 blocked로 보고한다. 원인을 고친 뒤 Step 1~3만 같은 HEAD에서 재시도한다.

- [ ] **Step 5: 최종 완료 gate를 실행한다**

다음을 모두 확인한다.

- engine clean commit과 전체 엔진 테스트 PASS
- durable Phase A scanner/test/evidence와 156행 ledger가 BB2 commit에 포함
- 사용자 승인 게이트 1·2 receipt 존재
- BB2 exact-path commit parent/path set exact
- structured ID/dangling/payload drift `0/0/0`
- real-corpus checks skipped 0, eval 15/15
- live `BAAI/bge-m3` rebuild receipt
- final snapshot verify PASS와 external binding SHA
- 기존 BB2/source dirt content 보존
- push/merge/Task 18 미실행

이 gate가 모두 PASS일 때만 Task 17을 완료로 보고한다.

---

## Plan Self-Review Gate

구현 승인 요청 전 계획 작성자가 직접 확인한다.

- 설계 1~9절의 각 요구사항이 Task 1~13 중 한 곳에 연결됨
- engine 기능, corpus 판단, staging, live, commit, post-commit snapshot 경계가 분리됨
- Phase A 임시 JSON 복사나 generic ID 자동 결정 없음
- 109 IDs, 4 mapping repairs, 2 collisions, 1 mixed review, dependent reviews가
  승인 게이트 1에 포함됨
- staging 전체 증거와 live 불변이 승인 게이트 2에 포함됨
- `/brain` 신규 파일 stage에 `-f`와 NUL exact pathspec 사용
- pre-commit restore와 post-commit no-reset 정책이 서로 섞이지 않음
- terminal permission 재검증, push, merge, Task 18 실행이 없음
- placeholder, undefined interface, task 간 signature mismatch 없음

이 계획 자체가 승인되기 전에는 Task 1의 failing test도 작성하지 않는다.
