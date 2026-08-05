# Project Brain P0 Ingest Integrity Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 일반 적재가 선언 범위 누락·공백 필수값·caller 임의 lifecycle 시각을 조용히 통과하지 못하게 하고, no-op까지 객체 단위로 증명한 뒤 BB2 코퍼스를 건드리지 않은 상태로 새 runtime foundation을 배포한다.

**Architecture:** `CoverageContract → notes 대조 → 독립 expected planner → build 결과 대조 → MutationService 단일 쓰기/clock 경계 → coverage 결속 영수증 → item별 finalizer`를 한 줄로 연결한다. 신규 `write_semantics.py`가 operation/action별 LIVE·PRESERVE 정책과 legacy field-level grandfathering을 소유하고, 신규 `foundation.py`와 설치 wrapper가 일반 적재 finalizer·index rebuild 없이 엔진/BB2 불변성을 증명한다.

**Tech Stack:** Python 3.11+, dataclasses/StrEnum, pytest, unittest, JSON canonicalization, SHA-256, Git plumbing, Bash, SQLite metadata inspection

## Global Constraints

- 정본 설계는 `docs/superpowers/specs/2026-08-05-ingest-integrity-foundation-design.md`다. 설계와 이 계획이 충돌하면 설계를 따른다.
- 구현은 현재 dirty `main`에서 하지 않는다. Task 0에서 `superpowers:using-git-worktrees`를 사용해 실제 Git worktree를 만든다.
- TDD 순서는 매 Task마다 `RED 테스트 → 실패 원인 확인 → 최소 구현 → focused GREEN → path-limited commit`이다. 테스트가 다른 이유로 실패하면 구현으로 넘어가지 않는다.
- 일반 `INGEST`에는 coverage 없는 호환 fallback, `--skip-coverage`, 범용 timestamp preserve 플래그를 만들지 않는다.
- production CLI/domain spec으로 fixed clock을 주입하지 않는다. `MutationService(clock=...)`는 테스트에서만 쓴다.
- 일반 `INGEST`는 delete, rename, auxiliary update를 받지 않는다. 이 동작은 `CONTEXT_REPLACE` 또는 등록 migration만 소유한다.
- P0에서는 기존 10,941개 객체의 timestamp나 Task 18 표시 라벨·quote 부채를 고치지 않는다. 현재 Task 18 spec/plan/binding은 실행하지 않는다.
- P0는 검색 표면·임베딩 입력을 바꾸지 않으므로 실모델 `index rebuild`를 돌리지 않는다. 실제 코퍼스 mutation도 만들지 않는다.
- `git add -A`, `git add .`, `git commit -a`를 쓰지 않는다. 각 Task의 Files에 적은 경로만 stage한다.
- 원본 `main`의 아래 미추적 경로는 사용자 자산이다. 이동·수정·삭제·stage하지 않는다.

```text
decks/project-brain-new/
docs/plans/2026-07-27-ingest-fix-execution-plan.md
docs/reports/2026-07-27-plan-delta-bg.md
docs/reports/2026-07-27-two-ingest-session-review.md
docs/reports/2026-07-28-agents-doctor-global-skill-mirror-final-review.md
docs/reports/2026-07-28-agents-doctor-global-skill-mirror-ledger.md
docs/reports/2026-07-28-brain-ingest-redesign-review.html
docs/superpowers/plans/2026-07-27-handoff-consumer.md
docs/superpowers/plans/2026-07-28-agents-doctor-global-skill-mirror.md
docs/superpowers/plans/2026-07-28-brain-ingest-recovery.md
docs/superpowers/plans/2026-08-04-task18-display-labels-and-quote-backlog.md
docs/superpowers/specs/2026-08-04-task18-display-labels-and-quote-backlog-design.md
```

- 셸 변수는 명령 블록마다 다시 선언한다. Python은 항상 검증 중인 worktree의 `PYTHONPATH`와 `.venv/bin/python`을 함께 지정한다.
- 엔진 완료 게이트는 pytest와 설치 runtime unittest 둘 다다. BB2 최종 gate는 기존 DB를 쓰는 eval까지 포함하지만 finalizer와 rebuild는 포함하지 않는다.
- 최종 foundation gate 전에 엔진·BB2의 코드/runtime/docs commit을 모두 끝낸다. 최종 gate 뒤에는 두 레포 모두 commit하지 않는다.

## File Structure

| 책임 | 파일 |
|---|---|
| coverage shape·canonical bytes·독립 expected planner | `src/project_brain/coverage.py` |
| coverage 단위 테스트와 공용 fixture | `tests/test_coverage.py`, `tests/coverage_helpers.py` |
| notes/build 조립 | `src/project_brain/assembly.py`, `src/project_brain/cli.py` |
| operation/action·timestamp·write semantic 정본 | `src/project_brain/write_semantics.py` |
| 중앙 transaction/clock/manifest | `src/project_brain/mutation.py` |
| 입력·최종 schema | `src/project_brain/schema.py`, `src/project_brain/lint.py` |
| Git CodeLocator 검증 | `src/project_brain/code_verify.py`, `src/project_brain/stale_check.py` |
| promote/projection producer | `src/project_brain/promote.py`, `src/project_brain/context_projection.py` |
| 단일·batch receipt와 durable recovery | `src/project_brain/transaction_receipt.py`, `src/project_brain/corpus_io.py` |
| 설치 single/batch runtime | `src/project_brain/templates/ingest/scripts/{assemble_notes.py,run_ingest.sh,run_ingest_batch.py,finalize_ingest.py}` |
| installed domain spec·coverage fixture | `src/project_brain/templates/ingest/scripts/domain_spec.template.py`, `src/project_brain/templates/ingest/references/object-templates/*.json` |
| legacy 시간 진단 | `src/project_brain/audit.py`, `tests/test_audit.py` |
| CLI wiring·JSON 계약 공용 회귀 | `src/project_brain/cli.py`, `tests/test_cli.py` |
| 비변이 foundation 정본·wrapper | `src/project_brain/foundation.py`, `src/project_brain/templates/ingest/scripts/validate_foundation.py` |
| 비변이 foundation 테스트 | `tests/test_foundation.py`, `src/project_brain/templates/ingest/scripts/test_validate_foundation.py` |
| installer report/path parity | `src/project_brain/installer.py`, `tests/test_installer.py`, `tests/test_ingest_skill_contract.py` |
| 전체 지도·운영 계약 | `docs/architecture/{runtime-map.md,data-contracts.md,change-map.md}`, `ROADMAP.md` |
| 설치 문서 | `src/project_brain/templates/ingest/{SKILL.md,references/object-model.md,references/ingest-tools.md,references/object-templates/README.md}` |

---

### Task 0: 승인된 기준에서 격리 worktree와 baseline을 만든다

**Files:**
- Create: `docs/reports/2026-08-05-ingest-integrity-foundation-baseline.md`
- Read only: `AGENTS.md`
- Read only: `/Users/al03040455/.agents/shared-guidance.md`
- Read only: `/Users/al03040455/.agents/rules/response-discipline.md`
- Read only: `/Users/al03040455/.agents/rules/python-resolution.md`

**Interfaces:**
- Branch: `feat/ingest-integrity-foundation`
- Worktree: `/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation`
- Required ancestor: design commit `77f0898c132556e254fbdf2cd033dd2a03c2fe2c`

- [ ] **Step 1: worktree skill을 읽고 원본 경계를 확인한다**

```bash
ENGINE_SOURCE=/Users/al03040455/Downloads/codes/project-brain
test "$(git -C "$ENGINE_SOURCE" rev-parse --show-toplevel)" = "$ENGINE_SOURCE"
git -C "$ENGINE_SOURCE" merge-base --is-ancestor \
  77f0898c132556e254fbdf2cd033dd2a03c2fe2c HEAD
test -f "$ENGINE_SOURCE/docs/superpowers/plans/2026-08-05-ingest-integrity-foundation.md"
git -C "$ENGINE_SOURCE" check-ignore -q .worktrees
test ! -e "$ENGINE_SOURCE/.worktrees/ingest-integrity-foundation"
test -z "$(git -C "$ENGINE_SOURCE" branch --list feat/ingest-integrity-foundation)"
git -C "$ENGINE_SOURCE" status --short
```

Expected: design commit이 현재 HEAD의 ancestor이고 `.worktrees`가 ignore되며 대상 branch/path가 없다. 위 Global Constraints의 미추적 경로는 그대로 보인다.

- [ ] **Step 2: 현재 plan commit에서 새 branch/worktree를 만든다**

```bash
ENGINE_SOURCE=/Users/al03040455/Downloads/codes/project-brain
ENGINE_WORKTREE="$ENGINE_SOURCE/.worktrees/ingest-integrity-foundation"
BASE_SHA="$(git -C "$ENGINE_SOURCE" rev-parse HEAD)"
git -C "$ENGINE_SOURCE" worktree add \
  "$ENGINE_WORKTREE" \
  -b feat/ingest-integrity-foundation \
  "$BASE_SHA"
```

- [ ] **Step 3: instruction과 baseline suite를 worktree에서 다시 읽고 실행한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
sed -n '1,240p' AGENTS.md
sed -n '1,240p' /Users/al03040455/.agents/shared-guidance.md
sed -n '1,240p' /Users/al03040455/.agents/rules/response-discipline.md
sed -n '1,240p' /Users/al03040455/.agents/rules/python-resolution.md
uv sync --extra mecab
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest -q
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
```

Expected: 두 suite 모두 PASS. 실패하면 새 코드 작성 전에 baseline report에 정확한 실패를 기록하고 멈춘다.

- [ ] **Step 4: RED 재현 기준을 문서에 고정한다**

`docs/reports/2026-08-05-ingest-integrity-foundation-baseline.md`에 실제 출력으로 다음 키를 채운다.

```markdown
# P0 적재 무결성 구현 baseline

- source_head:
- worktree_head:
- source_tracked_dirty_paths:
- source_untracked_preserved_paths:
- baseline_pytest:
- baseline_runtime_unittest:
- production_now_call_sites:
- ingest_call_sites:
- mutation_request_call_sites:
```

마지막 세 값은 다음 명령의 실제 개수와 경로를 함께 적는다.

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
rg -n 'now_kst\(' "$ENGINE/src/project_brain"
rg -n '\bingest\(' "$ENGINE/src/project_brain" "$ENGINE/tests"
rg -n 'MutationRequest\(' "$ENGINE/src/project_brain" "$ENGINE/tests"
```

- [ ] **Step 5: baseline report만 commit한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
git add docs/reports/2026-08-05-ingest-integrity-foundation-baseline.md
git diff --cached --check
git commit -m "docs(brain): P0 적재 무결성 baseline 기록"
```

---

### Task 1: CoverageContract 정본과 canonical identity를 만든다

**Files:**
- Create: `src/project_brain/coverage.py`
- Create: `tests/test_coverage.py`
- Create: `tests/coverage_helpers.py`
- Test: `tests/test_id_grammar.py`

**Interfaces:**

```python
@dataclass(frozen=True, order=True)
class ObjectIdentity:
    id: str
    kind: str

@dataclass(frozen=True)
class CoverageBinding:
    contract: dict[str, object]
    canonical_bytes: bytes
    sha256: str
    mode: str
    expected_objects: tuple[ObjectIdentity, ...]

@dataclass(frozen=True)
class BuildArtifactBinding:
    version: int
    coverage_sha256: str
    expected_objects: tuple[ObjectIdentity, ...]
    actual_objects: tuple[ObjectIdentity, ...]
    objects_sha256: str

class CoverageError(ValueError):
    code: str
    section: str | None
    field: str | None
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]
    coverage_sha256: str | None
    detail: str

    def as_dict(self) -> dict[str, object]: ...

def normalize_coverage(value: Mapping[str, object]) -> CoverageBinding: ...
def read_coverage(path: Path) -> CoverageBinding: ...
def object_identities(objects: Sequence[Mapping[str, object]]) -> tuple[ObjectIdentity, ...]: ...
def plan_expected_objects(binding: CoverageBinding, store: BrainStore) -> tuple[ObjectIdentity, ...]: ...
def build_artifact_binding(binding: CoverageBinding, objects: Sequence[Mapping[str, object]]) -> BuildArtifactBinding: ...
def normalize_build_artifact_binding(value: Mapping[str, object]) -> BuildArtifactBinding: ...
```

`tests/coverage_helpers.py`는 production fallback이 아니라 테스트가 명시적으로 쓰는 helper다.

```python
def direct_coverage(*objects: Mapping[str, object]) -> dict[str, object]:
    return {
        "version": 1,
        "mode": "direct",
        "objects": sorted(
            ({"id": str(obj["id"]), "kind": str(obj["kind"])} for obj in objects),
            key=lambda item: (item["id"], item["kind"]),
        ),
    }
```

- [ ] **Step 1: exact shape·중복·empty reason RED 테스트를 작성한다**

```python
def test_direct_contract_rejects_mixed_mode_fields():
    with pytest.raises(CoverageError) as exc:
        normalize_coverage({
            "version": 1,
            "mode": "direct",
            "objects": [{"id": "ledger.ctx.one", "kind": "EventLedgerRecord"}],
            "expected_objects": [],
        })
    assert exc.value.code == "coverage_invalid"


def test_assembled_empty_list_requires_reason_and_nonempty_forbids_it():
    raw = assembled_coverage_fixture()
    raw["sections"]["updates"] = {"ids": []}
    with pytest.raises(CoverageError, match="empty_reason"):
        normalize_coverage(raw)
    raw["sections"]["updates"] = {
        "ids": ["mapping.ctx.one"],
        "empty_reason": "없음",
    }
    with pytest.raises(CoverageError, match="empty_reason"):
        normalize_coverage(raw)


@pytest.mark.parametrize(
    ("mutator", "field"),
    [
        (lambda c: c["verify_groups"]["names"].extend(["g1"]), "verify_groups.names"),
        (lambda c: c["sections"]["glossary"]["keys"].extend(["term-one"]), "sections.glossary.keys"),
        (lambda c: c["sections"]["refs"]["items"].append({
            "category": "mapping", "alias": "shared", "id": "mapping.ctx.one", "expect": {}
        }), "sections.refs.items.alias"),
    ],
)
def test_raw_duplicates_fail_before_set_folding(mutator, field):
    raw = assembled_coverage_fixture()
    mutator(raw)
    with pytest.raises(CoverageError) as exc:
        normalize_coverage(raw)
    assert exc.value.field == field


@pytest.mark.parametrize("mode", ["direct", "assembled"])
def test_final_object_lists_reject_duplicate_id_even_when_kind_differs(mode):
    raw = coverage_with_same_id_and_different_kinds(mode)
    with pytest.raises(CoverageError) as exc:
        normalize_coverage(raw)
    assert exc.value.field in {"objects.id", "expected_objects.id"}
```

refs fixture에는 서로 다른 category에서 같은 `alias="shared"`를 두어 전역 중복 실패도 독립 테스트한다.

- [ ] **Step 2: canonical bytes와 독립 planner RED 테스트를 작성한다**

```python
def test_normalization_sorts_identity_arrays_but_preserves_verify_group_order():
    raw = assembled_coverage_fixture(verify_groups=["second", "first"])
    binding = normalize_coverage(raw)
    assert binding.contract["verify_groups"]["names"] == ["second", "first"]
    assert binding.canonical_bytes.endswith(b"\n")
    assert binding.sha256 == hashlib.sha256(binding.canonical_bytes).hexdigest()
    assert json.loads(binding.canonical_bytes) == binding.contract


def test_planner_expands_code_anchor_and_deduplicates_decision_evidence(tmp_path):
    store = BrainStore({})
    binding = normalize_coverage(assembled_coverage_fixture())
    planned = plan_expected_objects(binding, store)
    assert ObjectIdentity("code.ctx.anchor-one", "CodeLocator") in planned
    assert ObjectIdentity("evref.ctx.anchor-one", "EvidenceRef") in planned
    assert planned.count(ObjectIdentity("evref.ctx.commit-abc", "EvidenceRef")) == 1
    assert planned == binding.expected_objects


def test_context_create_and_reuse_are_checked_against_store():
    create = normalize_coverage(assembled_coverage_fixture(context_mode="create"))
    with pytest.raises(CoverageError, match="already exists"):
        plan_expected_objects(create, BrainStore({"context.ctx": domain_context()}))
    reuse = normalize_coverage(assembled_coverage_fixture(context_mode="reuse"))
    with pytest.raises(CoverageError, match="DomainContext"):
        plan_expected_objects(reuse, BrainStore({}))
```

planner 구현에서 `project_brain.assembly.build()`를 import하거나 호출하면 안 된다는 source inspection 테스트도 둔다.

- [ ] **Step 3: RED를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_coverage.py tests/test_id_grammar.py -q
```

Expected: `project_brain.coverage` import 실패로 FAIL.

- [ ] **Step 4: strict normalizer와 planner를 최소 구현한다**

canonical 규칙을 다음처럼 고정한다.

- `version`은 정수 `1`만 허용한다. bool은 거부한다.
- `assembled` exact top-level fields는 `version,mode,verify_groups,context,sections,expected_objects`다.
- `direct` exact top-level fields는 `version,mode,objects`다.
- `verify_groups`는 non-empty `names`면 `empty_reason`을 금지하고, `names=[]`이면 공백 아닌 `empty_reason`을 요구한다.
- verify group 배열만 사용자 순서를 보존한다. 나머지 identity 배열은 정규화 뒤 `(id,kind)` 또는 명시 identity tuple로 정렬한다.
- `sections` exact keys는 `sources,glossary,code_anchors,mappings,decisions,refs,updates,extra_objects`다.
- decision evidence identity는 `(type,ref)`, refs identity는 전체 category를 가로지르는 `alias`다. 최종 객체의 정확 비교는 `(id,kind)`로 하되 모든 raw/final 객체 목록의 중복은 `id`만으로 검사한다. 같은 ID에 다른 kind를 붙인 입력도 set folding 전에 실패한다.
- `expected_objects`는 planner 산출과 exact match해야 하고 LIVE assembled/direct 집합은 비어 있을 수 없다.
- `context.create`는 없는 context를 하나 계획하고 `context.reuse`는 존재하는 올바른 kind를 요구하며 새 context를 계획하지 않는다.
- code anchor 하나는 CodeLocator+EvidenceRef 두 개, ref 항목은 객체 0개, 동일 decision evidence는 EvidenceRef 하나로 계산한다.

- [ ] **Step 5: focused suite를 통과시키고 commit한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_coverage.py tests/test_id_grammar.py -q
git add src/project_brain/coverage.py tests/test_coverage.py tests/coverage_helpers.py
git diff --cached --check
git commit -m "feat(brain): coverage 계약 정본 추가"
```

---

### Task 2: assemble와 build를 coverage에 결속한다

**Files:**
- Modify: `src/project_brain/coverage.py`
- Modify: `src/project_brain/templates/ingest/scripts/assemble_notes.py`
- Modify: `src/project_brain/templates/ingest/scripts/domain_spec.template.py`
- Modify: `src/project_brain/templates/ingest/scripts/run_ingest.sh`
- Modify: `src/project_brain/assembly.py`
- Modify: `src/project_brain/cli.py`
- Modify: `tests/test_assembly.py`
- Modify: `tests/test_coverage.py`
- Modify: `tests/test_cli.py`
- Modify: `src/project_brain/templates/ingest/scripts/test_assemble_notes.py`
- Modify: `src/project_brain/templates/ingest/scripts/test_batch_tools.py`

**Interfaces:**

```python
def _load_spec_bytes(payload: bytes, *, filename: str) -> dict[str, object]: ...
def _load_spec(path: Path) -> dict[str, object]: ...

def validate_assembled_inputs(
    *,
    binding: CoverageBinding,
    verify_data: object,
    notes: Mapping[str, object],
    store: BrainStore,
) -> None: ...

def verify_build_output(
    binding: CoverageBinding,
    objects: Sequence[Mapping[str, object]],
) -> BuildArtifactBinding: ...
```

CLI contract:

```text
project-brain build --notes NOTES --coverage-file COVERAGE --objects-file OBJECTS [--brain-root ROOT]
```

build JSON report exact 추가 필드:

```json
{
  "coverage_sha256": "<sha256>",
  "expected_objects": [{"id": "...", "kind": "..."}],
  "actual_objects": [{"id": "...", "kind": "..."}],
  "objects_sha256": "<canonical object bundle sha256>",
  "build_binding": {"version": 1, "coverage_sha256": "...", "expected_objects": [], "actual_objects": [], "objects_sha256": "..."}
}
```

- [ ] **Step 1: verify group·notes section 누락 RED 테스트를 작성한다**

```python
def test_normalize_requires_exact_verify_group_set_and_coverage_order():
    coverage = assembled_coverage_fixture(verify_groups=["g2", "g1"])
    verify = {"groups": [{"group": "g1"}, {"group": "extra"}, {"group": "g2"}]}
    with pytest.raises(CoverageError) as exc:
        assemble_notes(verify, spec_with_coverage(coverage))
    assert exc.value.code == "coverage_notes_mismatch"


@pytest.mark.parametrize(
    ("section", "identity"),
    [
        ("sources", "manifest.ctx.code"),
        ("glossary", "term-one"),
        ("code_anchors", "anchor-one"),
        ("mappings", "mapping-one"),
        ("updates", "mapping.ctx.old"),
    ],
)
def test_assemble_rejects_one_missing_declared_item(section, identity):
    coverage = assembled_coverage_fixture()
    notes = complete_notes_fixture()
    remove_identity(notes, section, identity)
    with pytest.raises(CoverageError) as exc:
        validate_assembled_inputs(
            binding=normalize_coverage(coverage),
            verify_data=complete_verify_fixture(),
            notes=notes,
            store=BrainStore({}),
        )
    assert exc.value.code == "coverage_notes_mismatch"
```

별도 테스트로 refs의 `category,alias,id,expect`, decision의 `key,evidence`, extra object의 `(id,kind)`, unexpected notes 항목도 exact 비교한다.

- [ ] **Step 2: build output 한 개 누락·추가 RED 테스트를 작성한다**

```python
def test_build_rejects_missing_or_unexpected_object(monkeypatch, tmp_path, capsys):
    notes_path, coverage_path, objects_path = write_complete_build_inputs(tmp_path)
    real_build = assembly.build

    def missing_locator(notes, store, now):
        result = real_build(notes, store, now)
        result["objects"] = [o for o in result["objects"] if o["kind"] != "CodeLocator"]
        return result

    monkeypatch.setattr(assembly, "build", missing_locator)
    assert cli._run_build([
        "--notes", str(notes_path),
        "--coverage-file", str(coverage_path),
        "--objects-file", str(objects_path),
        "--brain-root", str(tmp_path / "brain"),
    ]) == 1
    assert json.loads(capsys.readouterr().out)["error_code"] == "coverage_build_mismatch"
    assert not objects_path.exists()


def test_build_cli_requires_coverage_file(tmp_path):
    with pytest.raises(SystemExit):
        cli._run_build(["--notes", "notes.json", "--objects-file", "objects.json"])


def test_single_runner_forwards_assembled_coverage_to_build():
    result = run_single_runner_fixture(dry=True)
    assert "--coverage-out" in result.command("assemble_notes")
    assert "--coverage-file" in result.command("project-brain build")


def test_load_spec_bytes_uses_the_pinned_payload_not_the_live_path(tmp_path):
    path = tmp_path / "domain_spec.py"
    pinned = b'COVERAGE = {"version": 1, "mode": "direct", "objects": []}\n'
    path.write_bytes(b'raise AssertionError("live path was reopened")\n')
    loaded = assemble_notes._load_spec_bytes(pinned, filename=str(path))
    assert loaded["COVERAGE"]["version"] == 1


def test_load_spec_path_adapter_matches_bytes_loader(tmp_path):
    path = tmp_path / "domain_spec.py"
    payload = b'COVERAGE = {"version": 1, "mode": "direct", "objects": []}\n'
    path.write_bytes(payload)
    assert assemble_notes._load_spec(path) == assemble_notes._load_spec_bytes(
        payload, filename=str(path)
    )
```

- [ ] **Step 3: RED를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_assembly.py tests/test_cli.py -q
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest src.project_brain.templates.ingest.scripts.test_assemble_notes \
  src.project_brain.templates.ingest.scripts.test_batch_tools
```

Expected: coverage 인자/API가 없어 FAIL.

- [ ] **Step 4: assemble output을 세 artifact로 고정한다**

`assemble_notes.py`는 `GROUP_ORDER`를 삭제하고 `COVERAGE.verify_groups.names` 순서만 사용한다. CLI에 `--coverage-out`을 추가해 notes·finalization과 함께 canonical coverage bytes를 쓴다.

`_load_spec_bytes(payload, filename=...)`가 pinned Python bytes를 `compile(payload, filename, "exec")`로 실행하는 유일한 loader다. 기존 `_load_spec(path)`는 path를 no-follow로 한 번 읽은 뒤 이 함수에 위임한다. batch는 Task 9에서 snapshot에 고정한 bytes만 `_load_spec_bytes()`에 넘기며 원본 path를 다시 열지 않는다.

```text
assemble_notes.py VERIFY SPEC -o NOTES --coverage-out COVERAGE [--finalization-out FINALIZATION]
```

`domain_spec.template.py`는 `COVERAGE`를 필수 상수로 제공하고 `GROUP_ORDER`를 제거한다. `NOW`와 `context.now` 제거는 중앙 clock이 연결되는 Task 6에서 한다. `context.mode=reuse`일 때 notes context에는 key/commit/repo/claim_status만 내보내 신규 DomainContext를 만들 재료를 넣지 않는다.

`run_ingest.sh`는 coverage temp를 만들고 assemble의 `--coverage-out`과 build의 `--coverage-file`에 연결한다. ingest의 mandatory coverage 인자는 Task 3에서 같은 temp를 이어 붙인다.

- [ ] **Step 5: build CLI가 쓰기 전에 두 번 exact 비교하게 한다**

순서는 `read/normalize coverage → plan_expected_objects(assembly output 독립) → notes/coverage 대조 → assembly.build → expected/actual 대조 → objects file atomic write → report`다. mismatch면 objects file을 만들거나 덮어쓰지 않는다.

- [ ] **Step 6: focused suite를 통과시키고 commit한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_coverage.py tests/test_assembly.py tests/test_cli.py -q
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest src.project_brain.templates.ingest.scripts.test_assemble_notes \
  src.project_brain.templates.ingest.scripts.test_batch_tools
git add src/project_brain/coverage.py src/project_brain/assembly.py src/project_brain/cli.py \
  src/project_brain/templates/ingest/scripts/assemble_notes.py \
  src/project_brain/templates/ingest/scripts/domain_spec.template.py \
  src/project_brain/templates/ingest/scripts/run_ingest.sh \
  tests/test_coverage.py tests/test_assembly.py tests/test_cli.py \
  src/project_brain/templates/ingest/scripts/test_assemble_notes.py \
  src/project_brain/templates/ingest/scripts/test_batch_tools.py
git diff --cached --check
git commit -m "feat(brain): assemble과 build에 coverage 결속"
```

---

### Task 3: 일반 INGEST의 coverage/write operation gate를 닫는다

**Files:**
- Modify: `src/project_brain/mutation.py`
- Modify: `src/project_brain/ingest.py`
- Modify: `src/project_brain/cli.py`
- Modify: `tests/test_mutation.py`
- Modify: `tests/test_ingest.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_corpus_io.py`
- Modify: `tests/test_universal_ingest_e2e.py`
- Modify: `tests/test_update_rules_engine.py`
- Modify: `tests/test_object_contract_templates.py`
- Modify: `tests/test_stale_check.py`
- Modify: `src/project_brain/templates/ingest/scripts/test_finalize_ingest.py`
- Modify: `src/project_brain/templates/ingest/scripts/test_batch_tools.py`
- Modify: `src/project_brain/templates/ingest/scripts/run_ingest.sh`

**Interfaces:**

```python
@dataclass(frozen=True)
class MutationRequest:
    # 기존 필드 유지
    coverage: Mapping[str, object] | None = None
    build_binding: BuildArtifactBinding | Mapping[str, object] | None = None

@dataclass(frozen=True)
class MutationPlanResult:
    # 기존 필드 유지
    error_details: Mapping[str, object] = field(default_factory=dict)

@dataclass(frozen=True)
class MutationManifest:
    # 기존 필드 유지
    coverage_sha256: str | None
    expected_objects: tuple[dict[str, str], ...]
    verified_objects: tuple[dict[str, str], ...]
    changed_objects: tuple[dict[str, str], ...]

class IngestError(RuntimeError):
    code: str
    detail: str
    error_details: Mapping[str, object]

    def as_dict(self) -> dict[str, object]: ...
```

`MutationManifest.changed_objects`와 후속 receipt의 object action summary는 Task 8의 exact canonical shape를 사용한다. create/update/delete는 `{action,id,kind}`, rename은 `{action,old_id,new_id,kind}`이며 reference rewrite는 해당 object update에 포함하고 auxiliary file update는 제외한다.

```python
def ingest(
    brain_root: Path,
    objects: Sequence[dict],
    preconditions: Mapping[str, str] | None = None,
    *,
    engine_sha: str,
    coverage: Mapping[str, object] | None = None,
    build_binding: BuildArtifactBinding | Mapping[str, object] | None = None,
    repo_context: RepoContext | None = None,
    operation: MutationOperation = MutationOperation.INGEST,
    expected_corpus_fingerprint: str | None = None,
    batch_binding: BatchBinding | None = None,
): ...
```

CLI contract:

```text
project-brain ingest --objects-file OBJECTS --coverage-file COVERAGE \
  [--build-report BUILD_REPORT | --preconditions-file DIRECT_PRECONDITIONS] ...
```

assembled coverage는 `--build-report`가 필수이고 direct coverage는 이를 받지 않는다. direct update가 낙관적 잠금을 쓸 때만 `--preconditions-file`에 순수 ID→hash object를 준다.

- [ ] **Step 1: 누락·binding 변조·숨은 action RED 테스트를 작성한다**

```python
def test_ingest_requires_full_coverage_contract(tmp_path):
    request = mutation_request(tmp_path, objects=(event(),), coverage=None)
    result = MutationService().plan(request.objects, request=request)
    assert (result.ok, result.error_code) == (False, "coverage_required")
    assert result.error_details["missing"] == ["coverage"]


def test_mutation_recomputes_coverage_and_build_binding(tmp_path):
    obj = event()
    coverage = direct_coverage(obj)
    request = mutation_request(
        tmp_path,
        objects=(obj,),
        coverage=coverage,
        build_binding={
            "version": 1,
            "coverage_sha256": "0" * 64,
            "expected_objects": [{"id": obj["id"], "kind": obj["kind"]}],
            "actual_objects": [{"id": obj["id"], "kind": obj["kind"]}],
            "objects_sha256": "0" * 64,
        },
    )
    result = MutationService().plan(request.objects, request=request)
    assert (result.ok, result.error_code) == (False, "coverage_binding_mismatch")


def test_mutation_replans_assembled_expected_after_store_load(tmp_path):
    coverage, objects, build_binding = assembled_create_artifacts(tmp_path)
    store_domain_context_after_build(tmp_path, coverage["context"]["key"])
    request = mutation_request(
        tmp_path,
        objects=objects,
        coverage=coverage,
        build_binding=build_binding,
    )
    result = MutationService().plan(request.objects, request=request)
    assert (result.ok, result.error_code) == (
        False, "coverage_binding_mismatch"
    )
    assert result.error_details["section"] == "context"


def test_mutation_replans_reuse_against_loaded_store(tmp_path):
    coverage, objects, build_binding = assembled_reuse_artifacts(tmp_path)
    remove_reused_context_after_build(tmp_path, coverage["context"]["key"])
    request = mutation_request(
        tmp_path,
        objects=objects,
        coverage=coverage,
        build_binding=build_binding,
    )
    result = MutationService().plan(request.objects, request=request)
    assert (result.ok, result.error_code) == (
        False, "coverage_binding_mismatch"
    )


@pytest.mark.parametrize("field", ["delete_ids", "renames", "auxiliary_updates"])
def test_ingest_rejects_hidden_non_object_actions(tmp_path, field):
    obj = event()
    overrides = {field: forbidden_action_value(field)}
    request = mutation_request(
        tmp_path,
        objects=(obj,),
        coverage=direct_coverage(obj),
        **overrides,
    )
    result = MutationService().plan(request.objects, request=request)
    assert (result.ok, result.error_code) == (False, "operation_action_invalid")
```

추가 RED는 빈 expected LIVE ingest, request object의 kind mismatch, assembled coverage에 build binding 없음, direct coverage에 build binding 존재, caller 제공 expected/SHA만 맞춘 변조를 각각 고정한다.

- [ ] **Step 2: 기존 테스트 입력을 명시적 direct coverage로 전환한다**

production에는 fallback을 넣지 않는다. 각 테스트 helper가 `MutationOperation.INGEST`일 때 `tests.coverage_helpers.direct_coverage(*objects)`를 명시적으로 request에 넣게 바꾼다. coverage 거부를 검증하는 테스트만 `coverage=None`을 직접 만든다.

- [ ] **Step 3: RED를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_coverage.py tests/test_mutation.py tests/test_ingest.py \
  tests/test_cli.py tests/test_corpus_io.py tests/test_universal_ingest_e2e.py \
  tests/test_update_rules_engine.py tests/test_object_contract_templates.py \
  tests/test_stale_check.py -q
```

Expected: `MutationRequest.coverage`/operation gate가 없어 새 negative 테스트가 FAIL.

- [ ] **Step 4: MutationService의 pre-store·post-store 두 관문을 구현한다**

store를 읽기 전에는 외부 상태가 필요 없는 검사만 한다.

1. operation/request field 조합 exact 검증
2. INGEST coverage normalize·canonical SHA 재계산
3. direct/assembled mode와 build binding 조합 검증
4. 일반 INGEST의 delete/rename/auxiliary update 거부
5. duplicate raw object ID를 set folding 전에 거부

그 뒤 실제 apply에서는 `corpus_lock` 안에서 unfinished transaction 복구와 `BrainStore.load_unlocked()`를 끝내고 다음 post-store 검사를 한다. 읽기 전용 preview도 동일한 store snapshot 하나를 쓰되 성공 증거는 apply의 locked 재검증이다.

6. `plan_expected_objects(binding, loaded_store)`를 반드시 다시 실행
7. planner 결과와 authored `binding.expected_objects` exact 비교
8. assembled면 planner 결과와 normalized build binding의 `expected_objects`·`actual_objects` exact 비교
9. request object `(id,kind)`와 planner 결과 exact 비교
10. object bundle canonical SHA와 build binding `objects_sha256` exact 비교

따라서 build 뒤 `context.create` 대상이 생기거나 `context.reuse` 대상이 사라지거나 kind가 바뀌어도 transaction 전에 실패한다. 이 post-store planner는 request가 제공한 expected/SHA를 신뢰하거나 build 당시 store 결과를 재사용하지 않는다.

coverage는 manifest에 전체 복제하지 않고 canonical SHA와 세 identity 집합을 넣는다. 전체 canonical contract는 `MutationRequest`가 preflight 동안 보유한다.

coverage/operation failure는 `MutationPlanResult.error_details`에 `section,object_id,missing,unexpected,coverage_sha256` 중 해당 값을 구조화해 남긴다. `IngestError.as_dict()`와 CLI가 이를 그대로 보존하며 오류 문자열 하나로 접지 않는다.

- [ ] **Step 5: CLI가 coverage bytes와 build report를 다시 읽어 결속한다**

`_run_ingest`는 `--coverage-file`을 항상 요구한다. assembled면 build report의 `coverage_sha256, expected_objects, actual_objects, objects_sha256, preconditions`를 exact parser로 읽고, object file canonical SHA를 재계산한다. direct면 build report를 거부한다.

같은 Task에서 `run_ingest.sh`의 ingest argv에도 `--coverage-file "$COVERAGE" --build-report "$BUILD_REPORT"`를 연결해 standard installed write 경로가 mandatory gate를 우회하지 않게 한다.

- [ ] **Step 6: focused suite를 통과시키고 commit한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_coverage.py tests/test_mutation.py tests/test_ingest.py \
  tests/test_cli.py tests/test_corpus_io.py tests/test_universal_ingest_e2e.py \
  tests/test_update_rules_engine.py tests/test_object_contract_templates.py \
  tests/test_stale_check.py -q
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
git add src/project_brain/mutation.py src/project_brain/ingest.py \
  src/project_brain/cli.py tests/test_mutation.py \
  tests/test_ingest.py tests/test_cli.py tests/test_corpus_io.py \
  tests/test_universal_ingest_e2e.py tests/test_update_rules_engine.py \
  tests/test_object_contract_templates.py tests/test_stale_check.py \
  src/project_brain/templates/ingest/scripts/test_finalize_ingest.py \
  src/project_brain/templates/ingest/scripts/test_batch_tools.py \
  src/project_brain/templates/ingest/scripts/run_ingest.sh
git diff --cached --check
git commit -m "feat(brain): 일반 적재 coverage 관문 강제"
```

---

### Task 4: write semantic과 timestamp action 정본을 만든다

**Files:**
- Create: `src/project_brain/write_semantics.py`
- Create: `tests/test_write_semantics.py`
- Modify: `src/project_brain/schema.py`
- Modify: `src/project_brain/lint.py`
- Modify: `src/project_brain/assembly.py`
- Modify: `src/project_brain/mutation.py`
- Modify: `tests/test_schema.py`
- Modify: `tests/test_lint.py`
- Modify: `tests/test_assembly.py`
- Modify: `tests/test_mutation.py`
- Modify: `tests/test_object_contract_templates.py`

**Interfaces:**

```python
class TimestampPolicy(StrEnum):
    LIVE = "live"
    PRESERVE = "preserve"


class ObjectActionKind(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RENAME = "rename"
    REFERENCE_REWRITE = "reference_rewrite"
    NO_CHANGE = "no_change"


@dataclass(frozen=True)
class ObjectWriteAction:
    action: ObjectActionKind
    object_id: str
    object_kind: str
    source_id: str | None
    timestamp_policy: TimestampPolicy | None


@dataclass(frozen=True, order=True)
class VerifiedReferenceRewrite:
    object_id: str
    pointer: str
    before_id: str
    after_id: str


@dataclass(frozen=True, order=True)
class WriteSemanticProblem:
    code: str
    object_id: str
    field: str
    value_fingerprint: str
    message: str


@dataclass(frozen=True)
class WriteSemanticsReport:
    errors: tuple[WriteSemanticProblem, ...]
    grandfathered: tuple[WriteSemanticProblem, ...]


def engine_owned_input_fields(operation: str, kind: str) -> frozenset[str]: ...
def engine_owned_temporal_fields(kind: str) -> frozenset[str]: ...
def classify_object_actions(
    *,
    operation: str,
    existing_by_id: Mapping[str, Mapping[str, object]],
    transformed_by_id: Mapping[str, Mapping[str, object]],
    delete_ids: Collection[str],
    rename_pairs: Sequence[tuple[str, str]],
    verified_reference_rewrites: Sequence[VerifiedReferenceRewrite],
) -> tuple[ObjectWriteAction, ...]: ...
def reference_only_rewrite(
    before: Mapping[str, object],
    after: Mapping[str, object],
    replacements: Mapping[str, str],
) -> bool: ...
def apply_timestamp_policy(
    objects: Sequence[Mapping[str, object]],
    *,
    actions: Sequence[ObjectWriteAction],
    existing_by_id: Mapping[str, Mapping[str, object]],
    operation: str,
    verified_object_ids: Collection[str],
    event_time: str | None,
) -> tuple[dict, ...]: ...
def validate_write_semantics(
    *,
    before_by_id: Mapping[str, Mapping[str, object]],
    after_by_id: Mapping[str, Mapping[str, object]],
    source_id_by_after_id: Mapping[str, str],
) -> WriteSemanticsReport: ...
def collect_timestamp_diagnostics(
    objects: Iterable[Mapping[str, object]],
    *,
    include_object_ids: bool = False,
) -> dict[str, object]: ...
```

기존 schema API는 omitted 필드를 caller가 항상 명시하게 바꾼다.

```python
def validate_mutation_input_schema(
    obj: dict,
    *,
    omitted_required_fields: frozenset[str],
) -> list[str]: ...

def lint_mutation_input_store_report(
    store: BrainStore,
    workspace_root: Path | None = None,
    *,
    operation: str,
) -> tuple[LintProblem, ...]: ...
```

- [ ] **Step 1: ISO ownership과 nonblank RED 테스트를 작성한다**

```python
@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("2026-08-05T00:00:00+09:00", True),
        ("2026-08-05T00:00:00Z", True),
        ("2026-08-05T00:00:00", False),
        ("2026-08-05", False),
        ("not-a-time", False),
    ],
)
def test_timestamp_parser_requires_iso_and_timezone_but_accepts_midnight(value, valid):
    obj = event(happened_at=value)
    report = validate_write_semantics(
        before_by_id={}, after_by_id={obj["id"]: obj}, source_id_by_after_id={}
    )
    assert (not report.errors) is valid


def test_required_claim_string_rejects_whitespace_only():
    obj = mapping(meaning=" \n ")
    report = validate_write_semantics(
        before_by_id={}, after_by_id={obj["id"]: obj}, source_id_by_after_id={}
    )
    assert [(p.code, p.field) for p in report.errors] == [
        ("write_semantics_invalid", "meaning")
    ]
```

nonblank 대상은 설계 §7의 공통·Evidence·시간/검토·코드/도메인·합성/문서 문자열 필드 exact set으로 구현한다. 해당 kind의 `BASE_REQUIRED | KIND_REQUIRED[kind]`에 실제로 포함된 필드에만 적용하며 list/dict 일반 non-empty 규칙은 추가하지 않는다.

- [ ] **Step 2: field-value grandfathering RED 테스트를 작성한다**

```python
def test_write_semantics_grandfathers_same_object_field_value_only():
    old = manifest(captured_at="legacy-without-zone")
    same_legacy = {**old, "title": "관련 없는 제목 수정"}
    report = validate_write_semantics(
        before_by_id={old["id"]: old},
        after_by_id={old["id"]: same_legacy},
        source_id_by_after_id={old["id"]: old["id"]},
    )
    assert not report.errors
    assert [(p.object_id, p.field) for p in report.grandfathered] == [
        (old["id"], "captured_at")
    ]


def test_changed_invalid_captured_at_is_blocking():
    old = manifest(captured_at="legacy-without-zone")
    changed = {**old, "captured_at": "another-invalid-value"}
    report = validate_write_semantics(
        before_by_id={old["id"]: old},
        after_by_id={old["id"]: changed},
        source_id_by_after_id={old["id"]: old["id"]},
    )
    assert [(p.code, p.field) for p in report.errors] == [
        ("timestamp_invalid", "captured_at")
    ]
```

문제 identity는 `(object_id, field, value_fingerprint)`다. 다른 객체, 다른 필드, 달라진 값은 grandfather하지 않는다.

- [ ] **Step 3: operation/action 분류 RED 테스트를 작성한다**

```python
def test_context_replace_action_matrix_distinguishes_exact_move_from_live_rename():
    old = mapping(object_id="mapping.ctx.old", meaning="same")
    exact_move = {**old, "id": "mapping.ctx.new"}
    changed_move = {**exact_move, "meaning": "changed"}
    exact = classify_object_actions(
        operation="context_replace",
        existing_by_id={old["id"]: old},
        transformed_by_id={exact_move["id"]: exact_move},
        delete_ids=(old["id"],),
        rename_pairs=((old["id"], exact_move["id"]),),
        verified_reference_rewrites=(),
    )
    live = classify_object_actions(
        operation="context_replace",
        existing_by_id={old["id"]: old},
        transformed_by_id={changed_move["id"]: changed_move},
        delete_ids=(old["id"],),
        rename_pairs=((old["id"], changed_move["id"]),),
        verified_reference_rewrites=(),
    )
    assert exact[0].timestamp_policy is TimestampPolicy.PRESERVE
    assert live[0].timestamp_policy is TimestampPolicy.LIVE


def test_reference_only_rewrite_requires_same_pointer_shape():
    before = mapping(evidence_refs=["evref.ctx.old"])
    after = {**before, "evidence_refs": ["evref.ctx.new"]}
    assert reference_only_rewrite(before, after, {"evref.ctx.old": "evref.ctx.new"})
    assert not reference_only_rewrite(
        before,
        {**after, "evidence_refs": ["evref.ctx.new", "evref.ctx.extra"]},
        {"evref.ctx.old": "evref.ctx.new"},
    )
```

- [ ] **Step 4: RED를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_write_semantics.py tests/test_schema.py tests/test_lint.py \
  tests/test_assembly.py tests/test_mutation.py \
  tests/test_object_contract_templates.py -q
```

Expected: `project_brain.write_semantics` import 실패로 FAIL.

- [ ] **Step 5: 순수 정책 모듈과 operation-aware pre-schema를 구현한다**

kind별 caller-owned 사건시각은 다음 exact map으로 검사한다.

```python
CALLER_TEMPORAL_FIELDS = {
    "EvidenceManifest": frozenset({"captured_at"}),
    "SpecRevision": frozenset({"captured_at"}),
    "ReviewRecord": frozenset({"reviewed_at"}),
    "EventLedgerRecord": frozenset({"happened_at"}),
    "TemporalFact": frozenset({"valid_from", "valid_until"}),
    "CurrentView": frozenset({"as_of"}),
    "IndexRecord": frozenset({"indexed_at"}),
}
```

`thread_ts`는 이 map에 넣지 않고 모든 kind의 lifecycle은 engine-owned로 분류한다. 이 Task는 operation-aware pre-schema가 omission allowlist를 받을 API와 순수 `VerifiedReferenceRewrite` 비교 함수까지만 만든다. 기존 production omission 동작은 바꾸지 않는다. `PROMOTE|PROMOTE_AUTO` ReviewRecord, CodeLocator 검증, ContextProjection의 새 allowlist 활성화는 producer와 request가 함께 바뀌는 Task 6에서 한다. CONTEXT_REPLACE request binding과 exact reference-only PRESERVE 활성화는 Task 7에서 planner·artifact와 한 commit으로 연결한다.

- [ ] **Step 6: focused suite를 통과시키고 commit한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_write_semantics.py tests/test_schema.py tests/test_lint.py \
  tests/test_assembly.py tests/test_mutation.py \
  tests/test_object_contract_templates.py -q
git add src/project_brain/write_semantics.py src/project_brain/schema.py \
  src/project_brain/lint.py src/project_brain/assembly.py \
  src/project_brain/mutation.py tests/test_write_semantics.py \
  tests/test_schema.py tests/test_lint.py tests/test_assembly.py \
  tests/test_mutation.py tests/test_object_contract_templates.py
git diff --cached --check
git commit -m "feat(brain): 쓰기 의미값과 시간 정책 정본 추가"
```

---

### Task 5: MutationService를 단일 transaction clock 경계로 바꾼다

**Files:**
- Modify: `src/project_brain/transaction_receipt.py`
- Modify: `src/project_brain/mutation.py`
- Modify: `src/project_brain/ingest.py`
- Modify: `tests/test_mutation.py`
- Modify: `tests/test_context_replace.py`
- Modify: `tests/test_ingest.py`

**Interfaces:**

```python
# project_brain/transaction_receipt.py
class MutationOutcome(StrEnum):
    COMMITTED = "committed"
    NO_CHANGES = "no_changes"


@dataclass(frozen=True)
class MutationPlanResult:
    # 기존 필드 유지
    outcome: MutationOutcome | None = None


class MutationService:
    def __init__(self, *, clock: Callable[[], str] = now_kst) -> None:
        self._clock = clock

    def preview(
        self,
        objects: Sequence[dict],
        *,
        request: MutationRequest,
    ) -> MutationPlanResult:
        """시간을 만들지 않는 preflight와 unstamped intent를 반환한다."""

    def plan(
        self,
        objects: Sequence[dict],
        *,
        request: MutationRequest,
    ) -> MutationPlanResult:
        """preview 뒤 stamp/manifest까지 만들되 corpus는 쓰지 않는 호환 API."""

    def apply(
        self,
        objects: Sequence[dict],
        *,
        request: MutationRequest,
        failure_injector: Callable[[str], None] | None = None,
    ) -> MutationPlanResult:
        """corpus lock 안에서 재검증·stamp·manifest·journal을 한 번 수행한다."""


# project_brain/ingest.py의 테스트 전용 private seam. CLI/env에는 노출하지 않는다.
def _new_mutation_service() -> MutationService:
    return MutationService()
```

`MutationRequest`에는 timestamp policy, preserve bool, clock override를 추가하지 않는다. `preview()`는 coverage·schema·operation transform·substantive action을 검증하지만 lifecycle/verified/generated 값을 만들거나 final mutation manifest를 발급하지 않는다. 기존 low-level 테스트용 `plan()`은 preview 뒤 clock·stamp·manifest까지 만들되 corpus는 쓰지 않는 호환 API로 남긴다. Task 7 완료 뒤 production artifact/CLI 경로는 `plan()`을 호출하지 않으며, 실제 corpus를 쓰는 `apply()` 한 호출의 wall-clock 공급자는 corpus lock 안 최종 경계 하나뿐이다.

`MutationOutcome`은 기존 의존 방향(`mutation → transaction_receipt`)을 유지하도록 `transaction_receipt.py`가 소유한다. `preview()`와 호환 `plan()`의 `outcome`은 아직 corpus 결과가 아니므로 `None`이다. `MutationOutcome.COMMITTED|NO_CHANGES`는 실제 `apply()`가 transaction 경계에서만 확정하며, Task 8의 receipt builder는 `outcome is None`인 결과를 거부한다.

- [ ] **Step 1: LIVE create/update/no-op RED 테스트를 작성한다**

```python
def test_live_create_uses_one_injected_clock_for_all_engine_timestamps(tmp_path):
    calls = []
    clock = lambda: calls.append(FIXED_TIME) or FIXED_TIME
    first = event(created_at="2000-01-01T00:00:00+09:00", updated_at="2000-01-01T00:00:00+09:00")
    second = manifest(created_at="2001-01-01T00:00:00+09:00", updated_at="2001-01-01T00:00:00+09:00")
    request = mutation_request(
        tmp_path, objects=(first, second), coverage=direct_coverage(first, second)
    )
    result = MutationService(clock=clock).apply(request.objects, request=request)
    assert result.ok
    assert calls == [FIXED_TIME]
    assert {
        (obj["created_at"], obj["updated_at"]) for obj in result.after_objects
    } == {(FIXED_TIME, FIXED_TIME)}


def test_live_update_preserves_created_and_bumps_updated_only_for_substantive_change(tmp_path):
    old = stored_mapping(tmp_path, meaning="old", created_at=OLD, updated_at=OLD)
    changed = {**old, "meaning": "new", "created_at": "caller", "updated_at": "caller"}
    result = apply_ingest(tmp_path, changed, clock=lambda: NEW)
    assert result.after["created_at"] == OLD
    assert result.after["updated_at"] == NEW


def test_live_noop_does_not_call_clock_and_existing_bytes_win(tmp_path):
    old = stored_mapping(tmp_path, meaning="same", created_at=OLD, updated_at=OLD)
    caller = {**old, "created_at": "2099-01-01T00:00:00+09:00", "updated_at": "2099-01-01T00:00:00+09:00"}
    def forbidden_clock():
        raise AssertionError("no-op opened the clock")
    result = apply_ingest(tmp_path, caller, clock=forbidden_clock)
    assert result.ok
    assert result.outcome is MutationOutcome.NO_CHANGES
    assert result.after == old
    assert result.manifest is not None
    assert not result.manifest.creates
    assert not result.manifest.updates
```

- [ ] **Step 2: 한 transaction clock과 final schema 순서 RED 테스트를 작성한다**

```python
def test_live_pre_schema_allows_engine_fields_but_final_schema_requires_stamp(tmp_path):
    draft = event_without("created_at", "updated_at")
    request = mutation_request(tmp_path, objects=(draft,), coverage=direct_coverage(draft))
    result = MutationService(clock=lambda: FIXED_TIME).apply(request.objects, request=request)
    assert result.ok
    assert result.after["created_at"] == result.after["updated_at"] == FIXED_TIME


def test_invalid_injected_clock_fails_before_manifest(tmp_path):
    draft = event_without("created_at", "updated_at")
    request = mutation_request(tmp_path, objects=(draft,), coverage=direct_coverage(draft))
    result = MutationService(clock=lambda: "2026-08-05T12:00:00").apply(
        request.objects, request=request
    )
    assert (result.ok, result.error_code, result.manifest) == (
        False, "timestamp_invalid", None
    )


def test_preview_never_opens_transaction_clock(tmp_path):
    draft = event_without("created_at", "updated_at")
    request = mutation_request(tmp_path, objects=(draft,), coverage=direct_coverage(draft))
    preview = MutationService(clock=forbidden_clock).preview(
        request.objects, request=request
    )
    assert preview.ok
    assert preview.manifest is None


def test_ingest_apply_with_internal_preflight_calls_clock_once(tmp_path):
    calls = []
    draft = event_without("created_at", "updated_at")
    request = mutation_request(tmp_path, objects=(draft,), coverage=direct_coverage(draft))
    result = MutationService(
        clock=lambda: calls.append(FIXED_TIME) or FIXED_TIME
    ).apply(request.objects, request=request)
    assert result.ok
    assert calls == [FIXED_TIME]


def test_valid_caller_event_time_change_is_substantive_and_bumps_updated(tmp_path):
    old = stored_manifest(
        tmp_path, captured_at=OLD_EVENT_TIME, created_at=OLD, updated_at=OLD
    )
    changed = {**old, "captured_at": NEW_EVENT_TIME}
    calls = []
    result = apply_ingest(
        tmp_path,
        changed,
        clock=lambda: calls.append(FIXED_TIME) or FIXED_TIME,
    )
    stored = object_by_id(result.after_objects, old["id"])
    assert result.outcome is MutationOutcome.COMMITTED
    assert calls == [FIXED_TIME]
    assert stored["captured_at"] == NEW_EVENT_TIME
    assert stored["created_at"] == OLD
    assert stored["updated_at"] == FIXED_TIME


def test_invalid_changed_caller_event_time_is_blocking(tmp_path):
    old = stored_manifest(tmp_path, captured_at=OLD_EVENT_TIME)
    changed = {**old, "captured_at": "2026-08-05T12:00:00"}
    result = apply_ingest(tmp_path, changed, clock=lambda: FIXED_TIME)
    assert (result.ok, result.error_code, result.manifest) == (
        False, "timestamp_invalid", None
    )
```

- [ ] **Step 3: RED를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_write_semantics.py tests/test_mutation.py \
  tests/test_context_replace.py tests/test_ingest.py -q
```

Expected: caller lifecycle이 그대로 남고 no-op timestamp도 caller 값으로 달라져 FAIL.

- [ ] **Step 4: preview와 실제 apply의 clock 경계를 분리한다**

`preview()`는 아래 1~5까지만 수행하고 clock·최종 timestamp·manifest·corpus를 건드리지 않는다. 호환 `plan()`은 preview 결과에 6~9를 적용하지만 corpus를 쓰지 않는다. `apply()`는 corpus lock을 잡고 unfinished transaction을 복구한 뒤 store를 `load_unlocked()`로 읽어 1~5를 다시 실행한다. substantive action 또는 operation event가 있으면 6~9를 모두 수행한다. canonical no-op이면 6~7을 건너뛰고 before bytes를 canonical after로 삼아 8~9를 수행하며, clock과 corpus/journal write 없이 zero-action manifest와 `MutationOutcome.NO_CHANGES`를 발급한다. changed/event apply는 `MutationOutcome.COMMITTED`를 발급한다.

1. request·coverage·operation-kind 검사
2. before store 로드
3. `engine_owned_input_fields()`를 쓴 pre-schema
4. 시각 없는 operation transform과 CodeLocator 실제 검증
5. engine-owned temporal을 제외한 substantive diff와 operation event 계산
6. substantive action 또는 operation event가 있을 때만 `self._clock()` 정확히 한 번 호출
7. LIVE stamp 또는 exact PRESERVE source timestamp 적용
8. write semantic → strict final schema → refs → merged lint
9. canonical manifest·fingerprint·outcome 생성(no-op도 zero-action manifest를 가짐)

`apply()`는 내부 preview 결과를 다시 `plan()`에 넘겨 재계획하지 않는다. lock 안에서 만든 하나의 unstamped plan을 그대로 stamp하고 journal에 적용한다. 따라서 일반 ingest 한 번의 실제 apply 전체에서 wall-clock 호출은 변경이면 1회, canonical no-op이면 0회다. artifact preview/revalidation의 clock 경계는 Task 7에서 같은 원칙으로 연결한다.

전체 no-op은 before 객체 전체를 canonical after로 복원한다. MARK_CHECKED 외에는 caller가 보낸 **engine-owned** temporal field 차이 자체가 action을 만들지 않는다. `captured_at`, `reviewed_at`, `happened_at`, `valid_from`, `valid_until`, `as_of`, `indexed_at`처럼 caller-owned 사건시각의 유효한 변경은 substantive action이고 LIVE `updated_at`을 갱신한다. 유효하지 않은 변경은 `timestamp_invalid`로 거부한다.

테스트에서 특정 객체를 찾을 때는 `object_by_id(result.after_objects, object_id)`라는 로컬 test helper를 쓴다. 이 이름은 production `MutationPlanResult` API가 아니며, 테스트 편의를 위해 결과 클래스에 `object()`나 `only_object()` 메서드를 추가하지 않는다.

- [ ] **Step 5: manifest가 stamped 객체와 실제 action만 보게 한다**

`changed_objects`는 create/update/delete/rename object action의 canonical 목록이다. reference rewrite는 그 객체의 update에 포함하며 별도 changed row로 중복 기록하지 않는다. `verified_objects`는 coverage와 request/store 검증이 끝난 `(id,kind)` 전체이고 `expected_objects`와 같아야 한다. no-op은 빈 `changed_objects`다.

- [ ] **Step 6: focused suite를 통과시키고 commit한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_write_semantics.py tests/test_mutation.py \
  tests/test_context_replace.py tests/test_ingest.py -q
git add src/project_brain/transaction_receipt.py \
  src/project_brain/mutation.py src/project_brain/ingest.py \
  tests/test_mutation.py tests/test_context_replace.py tests/test_ingest.py
git diff --cached --check
git commit -m "refactor(brain): mutation clock을 중앙 경계로 통합"
```

---

### Task 6: verifier·promote·projection의 외부 timestamp 생산을 제거한다

**Files:**
- Modify: `src/project_brain/mutation.py`
- Modify: `src/project_brain/write_semantics.py`
- Modify: `src/project_brain/schema.py`
- Modify: `src/project_brain/code_verify.py`
- Modify: `src/project_brain/stale_check.py`
- Modify: `src/project_brain/promote.py`
- Modify: `src/project_brain/objbase.py`
- Modify: `src/project_brain/context_projection.py`
- Modify: `src/project_brain/cli.py`
- Modify: `src/project_brain/assembly.py`
- Modify: `src/project_brain/templates/ingest/scripts/assemble_notes.py`
- Modify: `src/project_brain/templates/ingest/scripts/domain_spec.template.py`
- Modify: `tests/test_mutation.py`
- Modify: `tests/test_write_semantics.py`
- Modify: `tests/test_schema.py`
- Modify: `tests/test_code_verify.py`
- Modify: `tests/test_stale_check.py`
- Modify: `tests/test_promote.py`
- Modify: `tests/test_context_projection.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_universal_ingest_e2e.py`
- Modify: `tests/test_object_contract_templates.py`
- Modify: `src/project_brain/templates/ingest/scripts/test_assemble_notes.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class VerifiedLocator:
    locator: dict
    quote_sha256: str
    symbol_status: str

def promote(
    objects, ids, scope, *, bundle_key=None, reviewer,
    reviewed_at: str | None, review_extra_by_id=None,
): ...

def build_context_projection(
    store: BrainStore,
    context_id: str,
    *,
    output_locator: str,
    generated_by: str,
) -> tuple[dict, str]: ...

def build_reuse_projection(
    store: BrainStore,
    *,
    context_id: str,
    requirement_key: str,
    source_object_ids: list,
    reuse_payload: str,
    title: str,
    generated_by: str,
) -> dict: ...
```

- [ ] **Step 1: producer가 시간을 만들지 않는 RED 테스트를 작성한다**

```python
def test_success_returns_verification_without_timestamp(repo_context):
    verified = verify_locator_for_write(locator_without_verified_at(), repo=repo_context)
    assert "verified_at" not in verified.locator
    assert not hasattr(verified, "verified_at")


def test_omitted_reviewed_at_remains_unset_until_mutation():
    promoted, reviews = promote(
        [candidate_term()], ["g.ctx.term"], "single_object",
        reviewer="alice", reviewed_at=None,
    )
    assert "updated_at" not in promoted[0]
    assert "reviewed_at" not in reviews[0]
    assert "created_at" not in reviews[0]
    assert "updated_at" not in reviews[0]


def test_projection_builder_has_no_fabricated_timestamp(store):
    projection, _ = build_context_projection(
        store, "context.ctx", output_locator="CONTEXT.md", generated_by="project-brain"
    )
    assert not ({"created_at", "updated_at", "generated_at"} & projection.keys())
```

- [ ] **Step 2: CLI가 event intent를 중앙 서비스까지 보존하는 RED 테스트를 작성한다**

```python
def test_promote_omitted_reviewed_at_uses_transaction_clock(monkeypatch, cli_store):
    monkeypatch.setattr(
        ingest_module,
        "_new_mutation_service",
        lambda: MutationService(clock=lambda: FIXED_TIME),
    )
    assert run_promote_without_reviewed_at(cli_store) == 0
    stored = BrainStore.load(cli_store).get("review.g.ctx.term")
    assert stored["reviewed_at"] == FIXED_TIME
    assert stored["created_at"] == stored["updated_at"] == FIXED_TIME


def test_context_now_cannot_override_build_clock(tmp_path):
    notes = complete_notes_fixture()
    notes["context"]["now"] = "2000-01-01T00:00:00+09:00"
    rc, report = run_build_cli(tmp_path, notes)
    assert rc == 1
    assert report["error_code"] == "notes_invalid"


def test_promote_explicit_reviewed_at_is_preserved_from_lifecycle_clock(tmp_path):
    result = apply_promote(
        tmp_path, reviewed_at=USER_TIME, clock=lambda: FIXED_TIME
    )
    review = object_by_id(result.after_objects, "review.g.ctx.term")
    assert review["reviewed_at"] == USER_TIME
    assert review["created_at"] == review["updated_at"] == FIXED_TIME


def test_plain_ingest_cannot_omit_review_record_reviewed_at(tmp_path):
    review = review_record_without("reviewed_at", "created_at", "updated_at")
    result = apply_direct_ingest(tmp_path, review, clock=lambda: FIXED_TIME)
    assert (result.ok, result.error_code) == (False, "schema_invalid")


def test_new_locator_uses_verifier_transaction_time_not_caller_time(tmp_path):
    locator = locator_draft(verified_at=USER_TIME)
    result = apply_verified_locator(tmp_path, locator, clock=lambda: FIXED_TIME)
    stored = object_by_id(result.after_objects, locator["id"])
    assert stored["created_at"] == stored["updated_at"] == FIXED_TIME
    assert stored["verified_at"] == FIXED_TIME


def test_changed_locator_preserves_created_and_aligns_verified_updated(tmp_path):
    old = stored_locator(tmp_path, created_at=OLD, updated_at=OLD, verified_at=OLD)
    changed = {**old, "symbol": "new_symbol", "verified_at": USER_TIME}
    result = apply_verified_locator(tmp_path, changed, clock=lambda: FIXED_TIME)
    stored = object_by_id(result.after_objects, old["id"])
    assert stored["created_at"] == OLD
    assert stored["updated_at"] == stored["verified_at"] == FIXED_TIME


def test_unchanged_locator_is_noop_and_preserves_verified_at(tmp_path):
    old = stored_locator(tmp_path, verified_at=OLD)
    result = apply_verified_locator(tmp_path, dict(old), clock=forbidden_clock)
    assert result.outcome is MutationOutcome.NO_CHANGES
    assert object_by_id(result.after_objects, old["id"])["verified_at"] == OLD


def test_mark_checked_same_coordinates_is_a_new_event_with_one_clock(tmp_path):
    old = stored_locator(tmp_path, updated_at=OLD, verified_at=OLD)
    calls = []
    result = apply_mark_checked(
        tmp_path,
        old,
        clock=lambda: calls.append(FIXED_TIME) or FIXED_TIME,
    )
    assert calls == [FIXED_TIME]
    stored = object_by_id(result.after_objects, old["id"])
    assert stored["updated_at"] == FIXED_TIME
    assert stored["verified_at"] == FIXED_TIME


def test_projection_create_stamps_all_three_engine_times(tmp_path):
    result = apply_projection(tmp_path, payload="first", clock=lambda: FIXED_TIME)
    assert len(result.after_objects) == 1
    projection = result.after_objects[0]
    assert projection["created_at"] == FIXED_TIME
    assert projection["updated_at"] == FIXED_TIME
    assert projection["generated_at"] == FIXED_TIME


def test_projection_update_and_noop_use_clock_only_for_change(tmp_path):
    old = stored_projection(
        tmp_path, created_at=OLD, updated_at=OLD, generated_at=OLD
    )
    changed = apply_projection(tmp_path, payload="new", clock=lambda: FIXED_TIME)
    changed_object = object_by_id(changed.after_objects, old["id"])
    assert changed_object["created_at"] == OLD
    assert changed_object["updated_at"] == FIXED_TIME
    assert changed_object["generated_at"] == FIXED_TIME
    noop = apply_projection(tmp_path, payload="new", clock=forbidden_clock)
    assert noop.outcome is MutationOutcome.NO_CHANGES
```

production clock monkeypatch는 테스트 전용 factory seam에서만 하고 CLI flag/env/domain spec으로는 노출하지 않는다.

- [ ] **Step 3: RED를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_code_verify.py tests/test_stale_check.py tests/test_promote.py \
  tests/test_context_projection.py tests/test_cli.py tests/test_mutation.py \
  tests/test_write_semantics.py tests/test_schema.py \
  tests/test_universal_ingest_e2e.py tests/test_object_contract_templates.py -q
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest src.project_brain.templates.ingest.scripts.test_assemble_notes
```

Expected: verifier/promote/projection/CLI가 각각 `now_kst()` 또는 caller now를 써 FAIL.

- [ ] **Step 4: producer는 검증·의미 draft만 만들게 한다**

- `verify_locator_for_write()`는 repo/blob/symbol 검증 결과만 반환한다.
- `plan_mark_checked()`는 closure·commit intent·precondition만 만들고 verifier와 stamp는 MutationService가 한다.
- promote는 explicit `reviewed_at`만 보존하고 omission은 키 자체를 생략한다.
- projection builder는 lifecycle과 generated_at을 생략한다. `PROJECTION` operation이 모두 채운다.
- `objbase.base()`/`review_record()`는 engine-owned 값이 `None`이면 key를 쓰지 않는다.
- build preview는 `context.now`가 아니라 CLI가 한 번 읽은 현재 시각만 쓴다. 이는 저장 증거가 아니며 실제 ingest에서 덮인다.

`schema.py`와 `write_semantics.py`의 pre-schema allowlist도 이 Task에서 함께 바꾼다. `PROMOTE|PROMOTE_AUTO`의 새 ReviewRecord만 `reviewed_at` omission을 허용하고 명시 값은 사건시각으로 그대로 보존한다. 일반 INGEST의 누락은 계속 실패한다. `tests/test_universal_ingest_e2e.py`의 `VerifiedLocator` 생성자와 `tests/test_object_contract_templates.py`의 projection builder 호출도 이 Task에서 timestamp-free producer API로 바꿔 중간 전체 suite를 깨뜨리지 않는다.

- [ ] **Step 5: operation별 engine stamp를 연결한다**

- PROMOTE/AUTO: target lifecycle LIVE; 새 ReviewRecord lifecycle LIVE; `reviewed_at=None`이면 같은 transaction time.
- MARK_CHECKED: 같은 commit/좌표라도 명시적 verification event로 clock을 열고 `verified_at == updated_at`.
- PROJECTION: create/substantive update에서 `generated_at == updated_at == transaction time`; create면 created도 같다.
- 일반 INGEST의 ContextProjection create/substantive update는 `operation_kind_invalid`로 거부한다.
- CodeLocator 신규·좌표 변경은 caller `verified_at`을 버리고 transaction clock을 쓴다. 좌표가 같은 일반 INGEST no-op은 기존 값을 보존하고 clock 0회이며, 같은 commit·좌표의 MARK_CHECKED는 명시적 event라 clock 1회다.
- explicit ReviewRecord `reviewed_at`은 보존하고 lifecycle만 transaction clock을 쓴다. omission이면 `reviewed_at == created_at == updated_at`이다.
- PROJECTION no-op은 기존 `created_at,updated_at,generated_at`을 모두 보존하고 clock 0회다.

- [ ] **Step 6: focused suite를 통과시키고 commit한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_code_verify.py tests/test_stale_check.py tests/test_promote.py \
  tests/test_context_projection.py tests/test_cli.py tests/test_mutation.py \
  tests/test_write_semantics.py tests/test_schema.py \
  tests/test_universal_ingest_e2e.py tests/test_object_contract_templates.py -q
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest src.project_brain.templates.ingest.scripts.test_assemble_notes
git add src/project_brain/code_verify.py src/project_brain/stale_check.py \
  src/project_brain/mutation.py src/project_brain/write_semantics.py \
  src/project_brain/schema.py \
  src/project_brain/promote.py src/project_brain/objbase.py \
  src/project_brain/context_projection.py src/project_brain/cli.py \
  src/project_brain/assembly.py \
  src/project_brain/templates/ingest/scripts/assemble_notes.py \
  src/project_brain/templates/ingest/scripts/domain_spec.template.py \
  tests/test_code_verify.py tests/test_stale_check.py tests/test_promote.py \
  tests/test_context_projection.py tests/test_cli.py tests/test_mutation.py \
  tests/test_write_semantics.py tests/test_schema.py \
  tests/test_universal_ingest_e2e.py tests/test_object_contract_templates.py \
  src/project_brain/templates/ingest/scripts/test_assemble_notes.py
git diff --cached --check
git commit -m "refactor(brain): timestamp 생산을 mutation 경계로 이동"
```

---

### Task 7: PRESERVE operation과 CONTEXT_REPLACE action matrix를 고정한다

**Files:**
- Modify: `src/project_brain/write_semantics.py`
- Modify: `src/project_brain/mutation.py`
- Modify: `src/project_brain/context_replace.py`
- Modify: `src/project_brain/migration.py`
- Modify: `src/project_brain/canonical_repair.py`
- Modify: `src/project_brain/context_projection.py`
- Modify: `src/project_brain/cli.py`
- Modify: `tests/test_write_semantics.py`
- Modify: `tests/test_mutation.py`
- Modify: `tests/test_context_replace.py`
- Modify: `tests/test_migration.py`
- Modify: `tests/test_canonical_repair.py`
- Modify: `tests/test_context_projection.py`
- Modify: `tests/test_cli.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class MutationRequest:
    # 기존 필드 유지
    external_reference_rewrites: Mapping[str, str] = field(default_factory=dict)


def canonical_unstamped_intent(
    request: MutationRequest,
    preview: MutationPlanResult,
) -> tuple[dict[str, object], bytes, str]: ...

class MutationService:
    def apply_bound_intent(
        self,
        *,
        request: MutationRequest,
        artifact_intent: Mapping[str, object],
        expected_intent_sha256: str,
        failure_injector: Callable[[str], None] | None = None,
    ) -> MutationPlanResult: ...
```

`plan_context_replace()`는 검증을 끝낸 정렬된 `external_reference_rewrites`를 request에 남긴다. CONTEXT_REPLACE 외 operation의 non-empty 값은 request shape 단계에서 실패한다. artifact는 미리 stamp한 after object나 final mutation manifest가 아니라 canonical unstamped intent, before fingerprint, source hash, expected action을 보존한다.

- [ ] **Step 1: exact PRESERVE payload RED 테스트를 작성한다**

```python
@pytest.mark.parametrize(
    "operation",
    [
        MutationOperation.PROJECTION_REPAIR,
        MutationOperation.ID_ONLY_MIGRATION,
        MutationOperation.DISPLAY_MIGRATION,
        MutationOperation.CANONICAL_REPAIR,
    ],
)
def test_preserve_operations_keep_all_temporal_fields_byte_exact(tmp_path, operation):
    before, request = preserve_fixture(tmp_path, operation)
    calls = []
    result = MutationService(clock=lambda: calls.append(FIXED_TIME) or FIXED_TIME).apply(
        request.objects, request=request
    )
    assert result.ok
    assert calls == [FIXED_TIME]
    after = object_for_source(result.after_objects, before["id"])
    for field in (
        "created_at", "updated_at", "captured_at", "reviewed_at",
        "happened_at", "valid_from", "valid_until", "as_of",
        "indexed_at", "verified_at", "generated_at", "thread_ts",
    ):
        if field in before:
            assert after[field] == before[field]


@pytest.mark.parametrize(
    "field",
    [
        "created_at", "updated_at", "captured_at", "reviewed_at",
        "happened_at", "valid_from", "valid_until", "as_of",
        "indexed_at", "verified_at", "generated_at", "thread_ts",
    ],
)
def test_preserve_kind_field_matrix_covers_every_temporal_field(tmp_path, field):
    before, request = preserve_field_fixture(tmp_path, field=field)
    result = MutationService(clock=lambda: FIXED_TIME).apply(
        request.objects, request=request
    )
    after = object_for_source(result.after_objects, before["id"])
    assert after[field] == before[field]


def test_preserve_source_authority_is_exact_for_same_rename_and_survivor(tmp_path):
    same = apply_same_id_preserve(tmp_path)
    assert same.action.source_id == same.after_id
    renamed = apply_exact_rename_with_distinct_source_time(tmp_path)
    assert renamed.action.source_id == renamed.old_id
    assert renamed.after["created_at"] == renamed.old_before["created_at"]
    merged = apply_canonical_collision_with_distinct_times(tmp_path)
    assert merged.action.source_id == merged.canonical_target_id
    assert merged.after["created_at"] == merged.target_before["created_at"]
    assert merged.after["created_at"] != merged.deleted_source["created_at"]
```

- [ ] **Step 2: context replace의 네 action RED 테스트를 작성한다**

```python
def test_context_replace_exact_move_preserves_source_timestamps(tmp_path):
    before, request = context_replace_exact_move_fixture(tmp_path)
    calls = []
    result = MutationService(
        clock=lambda: calls.append(FIXED_TIME) or FIXED_TIME
    ).apply(request.objects, request=request)
    moved = object_by_id(result.after_objects, request.renames[before["id"]])
    assert calls == [FIXED_TIME]
    assert temporal_values(moved) == temporal_values(before)


def test_context_replace_move_with_meaning_change_is_live(tmp_path):
    before, request = context_replace_changed_move_fixture(tmp_path)
    result = MutationService(clock=lambda: FIXED_TIME).apply(
        request.objects, request=request
    )
    moved = object_by_id(result.after_objects, request.renames[before["id"]])
    assert moved["created_at"] == before["created_at"]
    assert moved["updated_at"] == FIXED_TIME


def test_context_replace_reference_only_rewrite_preserves_timestamps(tmp_path):
    before, request = context_replace_external_rewrite_fixture(tmp_path)
    calls = []
    result = MutationService(
        clock=lambda: calls.append(FIXED_TIME) or FIXED_TIME
    ).apply(request.objects, request=request)
    rewritten = object_by_id(result.after_objects, before["id"])
    assert calls == [FIXED_TIME]
    assert temporal_values(rewritten) == temporal_values(before)


def test_context_replace_standalone_create_is_live(tmp_path):
    request = context_replace_create_fixture(tmp_path)
    calls = []
    result = MutationService(
        clock=lambda: calls.append(FIXED_TIME) or FIXED_TIME
    ).apply(request.objects, request=request)
    created = object_by_id(result.after_objects, request.objects[0]["id"])
    assert calls == [FIXED_TIME]
    assert created["created_at"] == created["updated_at"] == FIXED_TIME


@pytest.mark.parametrize("mutation", ["remove", "add", "retarget"])
def test_context_replace_artifact_rejects_external_rewrite_binding_tamper(
    tmp_path, mutation
):
    artifact = context_replace_reference_artifact(tmp_path)
    tampered = mutate_external_reference_binding(artifact, mutation)
    result = apply_context_replace_artifact_result(tmp_path, tampered)
    assert (result.ok, result.error_code) == (
        False, "reference_rewrite_binding_mismatch"
    )


@pytest.mark.parametrize(
    "runner",
    [
        apply_context_replace_live_artifact,
        apply_migration_artifact_fixture,
        apply_canonical_repair_artifact_fixture,
    ],
)
def test_artifact_apply_opens_one_clock_across_internal_revalidation(
    tmp_path, runner
):
    calls = []
    result = runner(
        tmp_path,
        clock=lambda: calls.append(FIXED_TIME) or FIXED_TIME,
    )
    assert result.ok
    assert calls == [FIXED_TIME]


def test_context_replace_artifact_noop_never_opens_clock(tmp_path):
    result = apply_context_replace_noop_artifact(tmp_path, clock=forbidden_clock)
    assert result.outcome is MutationOutcome.NO_CHANGES


def test_canonical_artifact_keeps_failure_injection_and_recovery_rollback(tmp_path):
    artifact = create_canonical_repair_artifact_fixture(tmp_path)
    before = corpus_fingerprint_for_test(tmp_path)
    with pytest.raises(RuntimeError, match="injected"):
        apply_canonical_repair_artifact(
            artifact,
            failure_injector=fail_after_journal_prepared,
        )
    recover_unfinished_transaction(tmp_path)
    assert corpus_fingerprint_for_test(tmp_path) == before
    assert not unfinished_transaction_exists(tmp_path)


def test_production_artifact_paths_do_not_use_detached_plan_or_direct_io():
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in (
            PROJECT / "src/project_brain/context_replace.py",
            PROJECT / "src/project_brain/migration.py",
            PROJECT / "src/project_brain/canonical_repair.py",
        )
    }
    assert all(".plan(" not in text for text in sources.values())
    assert "apply_transaction(" not in sources["context_replace.py"]


@pytest.mark.parametrize(
    "operation", [MutationOperation.INGEST, MutationOperation.CONTEXT_REPLACE]
)
def test_context_projection_write_is_rejected_outside_projection_operation(
    tmp_path, operation
):
    projection = projection_draft()
    request = request_for_operation(tmp_path, operation, objects=(projection,))
    result = MutationService(clock=lambda: FIXED_TIME).plan(request.objects, request=request)
    assert (result.ok, result.error_code) == (False, "operation_kind_invalid")
```

각 한 줄 test는 before/after의 모든 temporal 필드와 실제 artifact apply 전체 clock 호출 횟수까지 assert한다. delete는 timestamp action을 만들지 않는 테스트를 별도로 둔다.

- [ ] **Step 3: RED를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_write_semantics.py tests/test_mutation.py tests/test_context_replace.py \
  tests/test_migration.py tests/test_canonical_repair.py \
  tests/test_context_projection.py tests/test_cli.py -q
```

Expected: 기존 repair/migration이 caller timestamp를 그대로 통과시키거나 context replace action을 구분하지 못해 FAIL.

- [ ] **Step 4: operation/action matrix를 exact allowlist로 구현한다**

| Operation | Action | 정책 |
|---|---|---|
| `INGEST` | create/substantive update | LIVE |
| `PROMOTE`, `PROMOTE_AUTO` | target update/ReviewRecord create | LIVE |
| `MARK_CHECKED` | CodeLocator verification event | LIVE |
| `PROJECTION` | ContextProjection create/substantive update | LIVE |
| `PROJECTION_REPAIR` | source_content_hash-only update | PRESERVE |
| `ID_ONLY_MIGRATION` | exact rename/reference rewrite | PRESERVE |
| `DISPLAY_MIGRATION` | CodeLocator title-only update | PRESERVE |
| `CANONICAL_REPAIR` | validated rename/merge/reference action | PRESERVE |
| `CONTEXT_REPLACE` | standalone create/same-ID semantic update | LIVE |
| `CONTEXT_REPLACE` | exact expected move/reference-only rewrite | PRESERVE |
| 모든 operation | canonical no-op | before 전체 보존, clock 0회 |
| delete | delete | timestamp 없음 |

등록되지 않은 operation/action 조합은 `timestamp_policy_missing`으로 시작 전에 실패한다. move가 ID/등록 참조 외 payload도 바꾸면 rename action은 LIVE다.

timestamp source 권위는 다음 exact 규칙이다. same-ID update/reference rewrite는 같은 ID의 before 객체, exact rename/move는 old/source ID의 before 객체, canonical collision merge는 삭제되는 source가 아니라 이미 존재하던 canonical target/survivor 객체를 쓴다. create에는 source가 없다. source가 없거나 둘로 해석되면 `timestamp_source_invalid`로 transaction 전에 실패한다.

CONTEXT_REPLACE의 reference-only PRESERVE는 실제 pointer별 `(object_id,pointer,before_id,after_id)` delta가 request의 `external_reference_rewrites`에서 기계적으로 펼친 `VerifiedReferenceRewrite`와 exact할 때만 허용한다. mapping에 없는 rewrite, 사용되지 않은 mapping, target 변조는 모두 실패한다.

- [ ] **Step 5: artifact를 unstamped intent로 바꾸고 중앙 apply를 관통시킨다**

`create_context_replace_artifact()`, `create_migration_artifact()`, `create_canonical_repair_artifact()`는 `MutationService.preview()`만 호출하고 clock을 열지 않는다. artifact에는 canonical unstamped request/action/source binding을 넣고 최종 lifecycle 값과 mutation manifest는 넣지 않는다.

`apply_context_replace_artifact()`, `apply_migration_artifact()`, `apply_canonical_repair_artifact()`는 live store에서 같은 unstamped intent를 재계산해 artifact bytes와 exact 비교한 뒤 `MutationService.apply_bound_intent()`를 정확히 한 번 호출한다. `apply_context_replace_artifact()`가 `apply_transaction()`을 직접 호출하는 기존 우회와 migration/canonical의 `plan() → apply() 내부 재plan` 이중 경로를 제거한다. 최종 stamp, `MutationManifest`, transaction ID와 receipt는 corpus lock 안의 이 한 번의 apply에서만 만들어진다.

세 artifact apply public API의 기존 테스트용 `failure_injector` seam은 `apply_bound_intent()`까지 그대로 전달한다. canonical repair에서 journal prepared 직후 실패를 주입한 뒤 `recover_unfinished_transaction()`으로 원래 fingerprint를 복원하는 회귀를 유지해 중앙화 과정에서 원자성 검증을 잃지 않는다.

- [ ] **Step 6: focused suite를 통과시키고 commit한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_write_semantics.py tests/test_mutation.py tests/test_context_replace.py \
  tests/test_migration.py tests/test_canonical_repair.py \
  tests/test_context_projection.py tests/test_cli.py -q
git add src/project_brain/write_semantics.py src/project_brain/mutation.py \
  src/project_brain/context_replace.py src/project_brain/migration.py \
  src/project_brain/canonical_repair.py src/project_brain/context_projection.py \
  src/project_brain/cli.py \
  tests/test_write_semantics.py tests/test_mutation.py \
  tests/test_context_replace.py tests/test_migration.py \
  tests/test_canonical_repair.py tests/test_context_projection.py \
  tests/test_cli.py
git diff --cached --check
git commit -m "feat(brain): operation별 timestamp 보존 정책 고정"
```

---

### Task 8: committed와 no-op을 같은 canonical receipt로 증명한다

**Files:**
- Modify: `src/project_brain/transaction_receipt.py`
- Modify: `src/project_brain/corpus_io.py`
- Modify: `src/project_brain/mutation.py`
- Modify: `src/project_brain/cli.py`
- Modify: `src/project_brain/templates/ingest/scripts/finalize_ingest.py`
- Modify: `src/project_brain/templates/ingest/scripts/run_ingest.sh`
- Modify: `tests/test_corpus_io.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_mutation.py`
- Modify: `src/project_brain/templates/ingest/scripts/test_finalize_ingest.py`
- Modify: `src/project_brain/templates/ingest/scripts/test_batch_tools.py`

**Interfaces:**

```python
# Task 5에서 정의한 project_brain.transaction_receipt.MutationOutcome을 그대로 재사용한다.

if TYPE_CHECKING:
    from project_brain.mutation import MutationPlanResult


@dataclass(frozen=True)
class MutationReceipt:
    version: int
    receipt_id: str
    ok: bool
    outcome: MutationOutcome
    operation: str
    committed: bool
    transaction_id: str | None
    manifest_sha256: str
    coverage_sha256: str | None
    expected_objects: tuple[ObjectIdentity, ...]
    verified_objects: tuple[ObjectIdentity, ...]
    changed_objects: tuple[Mapping[str, object], ...]
    before_fingerprint: str
    after_fingerprint: str


def receipt_from_result(
    result: "MutationPlanResult",
    *,
    committed: bool,
) -> MutationReceipt: ...
def normalize_mutation_receipt(value: object) -> MutationReceipt: ...
def mutation_receipt_dict(
    value: MutationReceipt | Mapping[str, object],
) -> dict[str, object]: ...
```

`transaction_receipt.py`는 runtime에 `mutation.py`를 import하지 않는다. `MutationPlanResult`는 `TYPE_CHECKING` 아래 형식 힌트로만 참조하고, builder는 결과의 명시된 필드만 읽어 기존 `mutation → transaction_receipt` 의존 방향을 유지한다.

`changed_objects`의 canonical projection은 다음 exact shape만 쓴다. `kind`는 create/update는 after 객체, delete/rename은 before 객체에서 얻는다.

```jsonl
{"action":"create|update|delete","id":"...","kind":"..."}
{"action":"rename","old_id":"...","new_id":"...","kind":"..."}
```

허용 action과 고정 순서는 `create → update → delete → rename`이다. 같은 action 안에서는 create/update/delete를 `(id,kind)`, rename을 `(old_id,new_id,kind)`로 정렬한다. reference rewrite는 해당 object update에 포함하고 별도 action으로 중복하지 않으며 auxiliary file update도 객체 집합이 아니므로 `changed_objects`에 넣지 않는다. duplicate row나 action별 extra/missing field는 normalizer가 거부한다.

no-op batch proof API:

```python
def record_no_change_receipt(
    brain_root: Path,
    *,
    binding: BatchBinding,
    receipt: MutationReceipt,
    verified_source_sha256_by_id: Mapping[str, str],
) -> None: ...

def recover_batch_receipt(
    brain_root: Path,
    binding: BatchBinding | Mapping[str, object],
    *,
    expected_receipt: Mapping[str, object] | None = None,
    verification_mode: str = "strict_commit",
) -> dict[str, object]: ...

def recover_batch_receipts(
    brain_root: Path,
    bindings: Iterable[BatchBinding | Mapping[str, object]],
    *,
    expected_receipts: Iterable[Mapping[str, object] | None],
    verification_mode: str = "strict_commit",
) -> tuple[dict[str, object] | None, ...]: ...
```

- [ ] **Step 1: receipt invariant RED 테스트를 작성한다**

```python
def test_no_change_receipt_proves_expected_objects_without_claiming_commit(tmp_path):
    obj = stored_event(tmp_path)
    result = apply_ingest(tmp_path, dict(obj), clock=forbidden_clock)
    receipt = receipt_from_result(result, committed=False)
    assert receipt.outcome is MutationOutcome.NO_CHANGES
    assert receipt.committed is False
    assert receipt.transaction_id is None
    assert receipt.changed_objects == ()
    assert receipt.before_fingerprint == receipt.after_fingerprint
    assert receipt.expected_objects == receipt.verified_objects
    assert receipt.receipt_id == normalize_mutation_receipt(
        mutation_receipt_dict(receipt)
    ).receipt_id


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: {**r, "committed": True},
        lambda r: {**r, "changed_objects": [{"action": "update", "id": "x", "kind": "Insight"}]},
        lambda r: {**r, "after_fingerprint": "0" * 64},
        lambda r: {**r, "verified_objects": []},
    ],
)
def test_no_change_receipt_rejects_invariant_tampering(no_change_receipt, mutation):
    with pytest.raises(ValueError):
        normalize_mutation_receipt(mutation(no_change_receipt))


def test_changed_object_projection_has_fixed_action_order_and_receipt_id():
    forward = receipt_from_result(result_with_all_object_actions(), committed=True)
    reversed_ = receipt_from_result(
        result_with_all_object_actions(reverse_manifest_rows=True), committed=True
    )
    assert [row["action"] for row in forward.changed_objects] == [
        "create", "update", "delete", "rename"
    ]
    assert forward.changed_objects == reversed_.changed_objects
    assert forward.receipt_id == reversed_.receipt_id


@pytest.mark.parametrize("bad", [
    {"action": "reference_rewrite", "id": "x", "kind": "Insight"},
    {"action": "rename", "old_id": "a", "new_id": "b"},
    {"action": "update", "id": "x", "kind": "Insight", "extra": True},
])
def test_changed_object_projection_rejects_unknown_or_nonexact_shape(bad):
    with pytest.raises(ValueError, match="changed_objects"):
        normalize_mutation_receipt(receipt_with_changed_objects([bad]))


def test_changed_object_projection_rejects_duplicate_rows():
    row = {"action": "update", "id": "x", "kind": "Insight"}
    with pytest.raises(ValueError, match="changed_objects"):
        normalize_mutation_receipt(
            receipt_with_changed_objects([row, dict(row)])
        )
```

- [ ] **Step 2: durable no-op과 later batch item RED 테스트를 작성한다**

```python
def test_batch_no_change_receipt_survives_later_disjoint_commit(tmp_path):
    first_binding, first_receipt = record_existing_noop(tmp_path, object_id="ledger.ctx.one")
    commit_disjoint_item(tmp_path, object_id="ledger.ctx.two")
    recovered = recover_batch_receipt(
        tmp_path, first_binding, expected_receipt=first_receipt
    )
    assert recovered == first_receipt


def test_batch_no_change_receipt_detects_verified_object_tamper(tmp_path):
    binding, receipt = record_existing_noop(tmp_path, object_id="ledger.ctx.one")
    overwrite_object_without_transaction(tmp_path, "ledger.ctx.one")
    with pytest.raises(CorpusIOError) as exc:
        recover_batch_receipt(tmp_path, binding, expected_receipt=receipt)
    assert exc.value.code == "receipt_state_mismatch"
```

no-op proof는 기존 `.brain-local/batch-intents/<batch_intent_id>.json`에 canonical version 2 intent로 기록한다. payload는 `outcome,binding,receipt,verified_source_sha256_by_id`를 갖고 corpus object 파일은 쓰지 않는다. 기존 committed version 1 intent read 회귀도 유지한다.

- [ ] **Step 3: finalizer의 mixed receipt RED 테스트를 작성한다**

```python
def test_validate_transaction_results_accepts_committed_and_no_changes():
    rows = validate_transaction_results([COMMITTED_RECEIPT, NO_CHANGE_RECEIPT])
    assert [row["outcome"] for row in rows] == ["committed", "no_changes"]


def test_finalizer_compares_expected_and_verified_per_item():
    bad = dict(NO_CHANGE_RECEIPT, verified_objects=[])
    with self.assertRaisesRegex(ValueError, "expected_objects.*verified_objects"):
        validate_transaction_results([bad])


def test_single_cli_serializes_canonical_committed_receipt(capsys):
    result = run_single_ingest_cli(changed=True)
    assert result.exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == mutation_receipt_dict(
        receipt_from_result(result.apply_result, committed=True)
    )


def test_single_cli_no_change_is_exit_zero_without_commit(capsys):
    result = run_single_ingest_cli(changed=False)
    assert result.exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "no_changes"
    assert payload["committed"] is False
    assert payload["transaction_id"] is None
```

기존 `ingested_ids`/`ingested_count`는 receipt schema와 finalizer 비교에서 제거한다.
CLI는 `changed_objects`나 `receipt_id`를 자체 조립하지 않고 최종 apply 결과의 `receipt_from_result()`를 `mutation_receipt_dict()`로 직렬화만 한다.

- [ ] **Step 4: RED를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_mutation.py tests/test_corpus_io.py tests/test_cli.py -q
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest src.project_brain.templates.ingest.scripts.test_finalize_ingest \
  src.project_brain.templates.ingest.scripts.test_batch_tools
```

Expected: no-op이 기존 committed receipt 규약에서 거부되고 durable proof가 없어 FAIL.

- [ ] **Step 5: canonical receipt와 outcome dispatch를 구현한다**

`receipt_id`는 `receipt_id`를 제외한 normalized payload의 canonical JSON SHA-256이다. committed는 실제 journal transaction ID를 쓰고 `committed=true`; no_changes는 `transaction_id=null`, `committed=false`, `changed_objects=[]`, before==after를 강제한다. 둘 다 expected==verified여야 한다.

`MutationService.apply()`는 action이 없을 때 object/journal을 쓰지 않되 batch binding이 있으면 no-op intent만 원자적으로 기록한다. action이 있으면 기존 journal 경로를 유지하고 새 receipt shape로 recover한다.

- [ ] **Step 6: CLI와 finalizer를 새 receipt로 교체한다**

single CLI도 `receipt_from_result()`만 직렬화한다. batch CLI는 `recover_batch_receipt()` 결과만 출력한다. finalizer public 함수명 `validate_transaction_results()`는 설치 behavior replay 호환을 위해 유지하되 내부 exact schema는 새 receipt다.

- [ ] **Step 7: focused suite를 통과시키고 commit한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_mutation.py tests/test_corpus_io.py tests/test_cli.py -q
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest src.project_brain.templates.ingest.scripts.test_finalize_ingest \
  src.project_brain.templates.ingest.scripts.test_batch_tools
git add src/project_brain/transaction_receipt.py src/project_brain/corpus_io.py \
  src/project_brain/mutation.py src/project_brain/cli.py \
  src/project_brain/templates/ingest/scripts/finalize_ingest.py \
  src/project_brain/templates/ingest/scripts/run_ingest.sh \
  tests/test_mutation.py tests/test_corpus_io.py tests/test_cli.py \
  src/project_brain/templates/ingest/scripts/test_finalize_ingest.py \
  src/project_brain/templates/ingest/scripts/test_batch_tools.py
git diff --cached --check
git commit -m "feat(brain): no-op까지 증명하는 mutation receipt 추가"
```

---

### Task 9: batch item을 coverage·receipt 단위로 격리한다

**Files:**
- Modify: `src/project_brain/transaction_receipt.py`
- Modify: `src/project_brain/corpus_io.py`
- Modify: `src/project_brain/templates/ingest/scripts/run_ingest.sh`
- Modify: `src/project_brain/templates/ingest/scripts/run_ingest_batch.py`
- Modify: `src/project_brain/templates/ingest/scripts/finalize_ingest.py`
- Modify: `tests/test_corpus_io.py`
- Modify: `tests/test_cli.py`
- Modify: `src/project_brain/templates/ingest/scripts/test_batch_tools.py`
- Modify: `src/project_brain/templates/ingest/scripts/test_finalize_ingest.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class LegacyBatchBindingV1:
    batch_manifest_sha256: str
    item_key: str
    item_input_fingerprint: str
    verify_json_sha256: str
    domain_spec_py_sha256: str
    repo_root: str
    brain_root: str
    brain_root_device: int
    brain_root_inode: int
    expected_repo_id: str
    expected_revision_ref: str
    target_revision_sha: str
    engine_root: str
    engine_sha: str


@dataclass(frozen=True)
class BatchBinding(LegacyBatchBindingV1):
    coverage_sha256: str


def normalize_batch_binding(
    value: BatchBinding | LegacyBatchBindingV1 | Mapping[str, object] | None,
    *,
    allow_legacy_v1: bool = False,
) -> BatchBinding | LegacyBatchBindingV1 | None: ...


def normalize_legacy_batch_binding_v1(
    value: Mapping[str, object],
) -> LegacyBatchBindingV1: ...


def batch_binding_dict(
    value: BatchBinding | LegacyBatchBindingV1 | Mapping[str, object] | None,
    *,
    allow_legacy_v1: bool = False,
) -> dict[str, object] | None: ...


def batch_intent_id(
    value: BatchBinding | LegacyBatchBindingV1 | Mapping[str, object],
    *,
    allow_legacy_v1: bool = False,
) -> str: ...


def recover_batch_receipt(
    brain_root: Path,
    binding: BatchBinding | LegacyBatchBindingV1 | Mapping[str, object],
    *,
    expected_receipt: Mapping[str, object] | None = None,
    verification_mode: str = "strict_commit",
) -> dict[str, object]: ...


def recover_batch_receipts(
    brain_root: Path,
    bindings: Iterable[
        BatchBinding | LegacyBatchBindingV1 | Mapping[str, object]
    ],
    *,
    expected_receipts: Iterable[Mapping[str, object] | None],
    verification_mode: str = "strict_commit",
) -> tuple[dict[str, object] | None, ...]: ...
```

`normalize_batch_binding()`은 기본적으로 `coverage_sha256`까지 포함한 현재 exact shape만 쓴다. 기존 committed version 1 batch-intent/journal을 읽을 때만 `corpus_io`가 `allow_legacy_v1=True`로 호출하고 내부 `normalize_legacy_batch_binding_v1()`로 분기한다. legacy parser는 옛 필드 집합을 exact 검사하고 다시 직렬화할 때 기존 bytes shape를 보존하며 coverage SHA를 만들어 붙이지 않는다. legacy 증거는 역사 복구에만 쓰고 새 P0 coverage 성공 증거나 새 batch resume 입력으로 승격하지 않는다. v2 `batch_intent_id`와 item fingerprint에는 coverage SHA가 반드시 들어간다. `batch_binding_dict(None)`은 non-batch manifest 계약으로 그대로 `None`을 반환한다. `allow_legacy_v1`은 legacy 객체에만 영향을 주며 `None` 처리와 무관하다.

item record exact shape:

```json
{
  "binding": {},
  "status": "pending|failed|committed|no_changes",
  "failure": null,
  "expected_objects": [],
  "verified_objects": [],
  "changed_objects": [],
  "receipt": null
}
```

상태 invariant는 `pending: failure=null,receipt=null`, `failed: failure만 존재`, `committed|no_changes: failure=null, exact receipt 존재, status==receipt.outcome`이다. `_new_item_record`, resume parser, `_recover_item_records`, finalizer의 authoritative 이름은 모두 `item_records[*].receipt`다. 이전 top-level `transactions` 호환 출력이 필요하면 receipt에서만 파생하고 성공 판정에는 사용하지 않으며 item record의 옛 `transaction` 필드는 제거한다.

- [ ] **Step 1: coverage가 batch identity와 resume에 들어가는 RED 테스트를 작성한다**

```python
def test_batch_resume_rejects_changed_coverage_bytes(tmp_path):
    state = create_bound_batch_state(tmp_path, coverage=coverage_one())
    rewrite_domain_spec_coverage(tmp_path, coverage_two_same_objects())
    with self.assertRaisesRegex(ValueError, "item_input_fingerprint"):
        resume_batch(state)


def test_batch_coverage_loader_uses_domain_snapshot_payload_only(tmp_path):
    snapshot = pin_domain_spec(tmp_path, coverage=coverage_one())
    snapshot.source_path.write_text(
        'raise AssertionError("live domain spec reopened")\n', encoding="utf-8"
    )
    binding = coverage_from_domain_snapshot(snapshot)
    assert binding.sha256 == normalize_coverage(coverage_one()).sha256


def test_batch_binding_rechecks_coverage_sha_before_and_after_item(tmp_path):
    binding = make_binding(tmp_path, coverage_sha256="0" * 64)
    with self.assertRaisesRegex(ValueError, "coverage_sha256"):
        verify_item_inputs(binding, pinned_item(tmp_path))


def test_version_one_committed_intent_remains_readable_after_binding_v2(tmp_path):
    write_legacy_committed_intent_v1(tmp_path)
    recovered = recover_batch_receipt(
        tmp_path,
        legacy_binding_v1(),
        verification_mode="strict_commit",
    )
    assert recovered["committed"] is True


def test_new_binding_writers_require_explicit_legacy_read_mode():
    legacy = legacy_binding_v1()
    with pytest.raises(ValueError, match="legacy"):
        batch_binding_dict(legacy)
    with pytest.raises(ValueError, match="legacy"):
        batch_intent_id(legacy)
    assert batch_binding_dict(legacy, allow_legacy_v1=True) == legacy_binding_v1_dict()
    assert batch_intent_id(legacy, allow_legacy_v1=True) == legacy_batch_intent_id()


def test_batch_binding_dict_preserves_non_batch_none():
    assert batch_binding_dict(None) is None
```

- [ ] **Step 2: item expected overlap RED 테스트를 작성한다**

```python
def test_batch_rejects_overlapping_expected_ids_before_first_item(tmp_path):
    manifest = batch_manifest(
        item("one", expected=[("mapping.ctx.shared", "DomainMapping")]),
        item("two", expected=[("mapping.ctx.shared", "DomainMapping")]),
    )
    result = run_batch_preflight(tmp_path, manifest)
    assert result["ok"] is False
    assert result["error_code"] == "batch_expected_object_overlap"
    assert not any_transaction_or_baseline_artifact(tmp_path)


def test_batch_rejects_same_id_with_different_kinds_before_first_item(tmp_path):
    manifest = batch_manifest(
        item("one", expected=[("shared.ctx.id", "Insight")]),
        item("two", expected=[("shared.ctx.id", "DecisionRecord")]),
    )
    result = run_batch_preflight(tmp_path, manifest)
    assert result["error_code"] == "batch_expected_object_overlap"
    assert not any_transaction_or_baseline_artifact(tmp_path)
```

새 batch preflight는 execution state 해석과 pinned domain spec bytes 로드 뒤, 첫 baseline/item 실행 전에 초기 BrainStore로 모든 item planner를 돌린다. item 사이에는 kind와 무관하게 **object ID 하나라도** 겹치면 실패한다. 이 최초 planner 결과·coverage SHA·item input fingerprint를 pending item record에 durable하게 결속한 뒤에만 첫 item을 시작한다.

- [ ] **Step 3: mixed no-op/commit과 per-item finalizer RED 테스트를 작성한다**

```python
def test_batch_accepts_mixed_committed_and_no_changes_items(tmp_path):
    report = run_two_item_batch(tmp_path, outcomes=("no_changes", "committed"))
    assert report["finalized"] is True
    assert report["failed"] == []
    assert [row["status"] for row in report["item_records"]] == [
        "no_changes", "committed"
    ]


def test_finalizer_rejects_item_level_identity_mismatch_even_if_union_matches():
    records = swap_verified_objects_between_two_items()
    with self.assertRaisesRegex(ValueError, "item.*expected_objects"):
        validate_item_records(records)


def test_resume_recovers_context_create_committed_before_report_update(tmp_path):
    state = crash_after_context_create_receipt_before_report_update(tmp_path)
    resumed = resume_batch(state)
    first = resumed["item_records"][0]
    assert first["status"] == "committed"
    assert first["expected_objects"] == first["receipt"]["expected_objects"]


def test_resume_rejects_existing_create_target_without_durable_receipt(tmp_path):
    state = pending_context_create_state(tmp_path)
    create_context_outside_batch(tmp_path, state.item_context_id)
    with self.assertRaisesRegex(ValueError, "context.*external drift"):
        resume_batch(state)
    assert no_additional_transaction(tmp_path)


def test_resume_accepts_pending_context_create_when_target_is_still_absent(tmp_path):
    state = pending_context_create_state(tmp_path)
    resumed = resume_batch(state)
    assert resumed["item_records"][0]["status"] in {
        "committed", "no_changes"
    }


def test_resume_replans_only_pending_items_and_compares_saved_expected(tmp_path):
    state = stop_after_first_committed_item(tmp_path)
    mutate_store_dependency_for_pending_item(tmp_path)
    with self.assertRaisesRegex(ValueError, "pending_expected_objects"):
        resume_batch(state)


def test_resume_accepts_terminal_prefix_followed_by_pending_suffix(tmp_path):
    state = state_with_statuses(tmp_path, "committed", "no_changes", "pending")
    resumed = resume_batch(state)
    assert [row["status"] for row in resumed["item_records"][:2]] == [
        "committed", "no_changes"
    ]


def test_resume_rejects_terminal_item_after_first_nonterminal(tmp_path):
    state = state_with_statuses(tmp_path, "committed", "pending", "committed")
    with self.assertRaisesRegex(ValueError, "non-terminal.*terminal"):
        resume_batch(state)


def test_resume_retries_failed_item_before_pending_suffix(tmp_path):
    state = state_with_statuses(tmp_path, "committed", "failed", "pending")
    resumed = resume_batch(state)
    assert resumed["item_records"][0]["status"] == "committed"
    assert all(
        row["status"] in {"committed", "no_changes"}
        for row in resumed["item_records"][1:]
    )
```

- [ ] **Step 4: coverage temp cleanup RED 테스트를 작성한다**

`RunIngestCleanupTest`의 fake `mktemp` 목록에 COVERAGE를 추가하고 assemble/build/ingest/finalizer 각 실패 지점에서 notes, coverage, objects, build report, finalization, baseline, transaction result가 모두 삭제되는지 assert한다.

- [ ] **Step 5: RED를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_corpus_io.py tests/test_cli.py -q
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest src.project_brain.templates.ingest.scripts.test_batch_tools \
  src.project_brain.templates.ingest.scripts.test_finalize_ingest
```

Expected: BatchBinding과 fingerprint에 coverage가 없고 status가 committed만 허용해 FAIL.

- [ ] **Step 6: pinned bytes에서 coverage를 만들고 item binding에 넣는다**

`run_ingest_batch.py`는 원본 domain spec path를 재open하지 않는다. `_domain_snapshot.payload`을 `assemble_notes._load_spec_bytes()`로 실행해 normalized CoverageContract를 만들고 canonical bytes를 `_manifest_fingerprint`, `_item_input_fingerprint`, BatchBinding에 넣는다. item 전후 재검증도 pinned verify/spec/coverage 세 값을 모두 확인한다.

resume은 새 batch preflight와 다르게 처리한다. durable state의 `committed|no_changes` prefix는 원래 저장한 expected objects, exact receipt, pinned binding, `recover_batch_receipt()`의 현재 source hash 증거로만 재검증하고 현재 store에서 `context.create` planner를 다시 돌리지 않는다. `pending|failed`로 시작하는 non-terminal suffix만 현재 store에서 planner를 다시 실행하며, 결과는 최초 state에 결속된 expected objects와 exact match해야 한다. `failed` item은 binding·coverage·saved expected 재검증을 통과한 뒤 `pending`으로 전이해 재시도하고, 뒤의 pending item은 앞 item이 성공한 뒤 순서대로 실행한다. `committed|no_changes` terminal prefix 뒤의 non-terminal suffix는 정상 미완료 상태다. 첫 non-terminal item 뒤에 다시 terminal item이 나타나는 경우만 resume contract 오류다.

- [ ] **Step 7: runner와 finalizer를 item receipt 기준으로 바꾼다**

`run_ingest.sh`는 coverage temp를 생성하고 다음 exact 흐름을 쓴다.

```text
assemble --coverage-out → build --coverage-file → ingest --coverage-file --build-report → receipt validate
```

batch record의 authoritative success는 status `committed|no_changes`와 exact receipt다. 전체 union은 summary에만 싣고 성공 판정에는 사용하지 않는다.

- [ ] **Step 8: focused suite를 통과시키고 commit한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_corpus_io.py tests/test_cli.py -q
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest src.project_brain.templates.ingest.scripts.test_batch_tools \
  src.project_brain.templates.ingest.scripts.test_finalize_ingest
git add src/project_brain/transaction_receipt.py src/project_brain/corpus_io.py \
  src/project_brain/templates/ingest/scripts/run_ingest.sh \
  src/project_brain/templates/ingest/scripts/run_ingest_batch.py \
  src/project_brain/templates/ingest/scripts/finalize_ingest.py \
  tests/test_corpus_io.py tests/test_cli.py \
  src/project_brain/templates/ingest/scripts/test_batch_tools.py \
  src/project_brain/templates/ingest/scripts/test_finalize_ingest.py
git diff --cached --check
git commit -m "feat(brain): batch를 item별 coverage receipt로 결속"
```

---

### Task 10: legacy timestamp 부채와 자정 밀도를 비차단 진단으로 분리한다

**Files:**
- Modify: `src/project_brain/write_semantics.py`
- Modify: `src/project_brain/audit.py`
- Modify: `src/project_brain/cli.py`
- Modify: `tests/test_write_semantics.py`
- Modify: `tests/test_audit.py`
- Modify: `tests/test_cli.py`

**Interfaces:**

```text
project-brain audit ... [--timestamp-details-file ABSOLUTE_JSON_PATH]
```

기본 stdout `timestamps` shape:

```json
{
  "timestamp_format_legacy": {
    "count": 0,
    "by_field": {},
    "by_reason": {},
    "by_date": {}
  },
  "midnight_density": {
    "total_timestamp_values": 0,
    "midnight_values": 0,
    "ratio": 0.0,
    "by_field": {},
    "by_context": {},
    "by_date": {}
  }
}
```

details file은 위 summary와 `object_ids_by_bucket`을 추가한 canonical JSON이다.

- [ ] **Step 1: 비차단과 opt-in detail RED 테스트를 작성한다**

```python
def test_audit_reports_invalid_timestamp_without_changing_ok(tmp_path):
    store = clean_store_with(manifest(captured_at="legacy"))
    report = run_audit_without_git(store, tmp_path)
    assert report["ok"] is True
    assert report["timestamps"]["timestamp_format_legacy"]["count"] == 1


def test_audit_midnight_density_is_informational(tmp_path):
    store = clean_store_with(event(created_at="2026-08-05T00:00:00+09:00"))
    report = run_audit_without_git(store, tmp_path)
    assert report["ok"] is True
    assert report["timestamps"]["midnight_density"]["midnight_values"] >= 1


def test_timestamp_details_are_opt_in(tmp_path, capsys):
    details = tmp_path / "timestamp-details.json"
    assert run_audit_cli(tmp_path, "--timestamp-details-file", str(details)) == 0
    stdout = json.loads(capsys.readouterr().out)
    assert "object_ids_by_bucket" not in json.dumps(stdout)
    assert "object_ids_by_bucket" in json.loads(details.read_text())
```

- [ ] **Step 2: 필드 분류 RED 테스트를 작성한다**

```python
def test_thread_ts_is_not_iso_validated():
    assert not timestamp_problems(slack_thread(thread_ts="1712345678.123456"))


@pytest.mark.parametrize("kind,field", [
    ("TemporalFact", "valid_until"),
    ("CurrentView", "as_of"),
    ("IndexRecord", "indexed_at"),
])
def test_optional_and_caller_temporal_fields_require_timezone_when_changed(kind, field):
    assert timestamp_problem_for(template(kind, **{field: "2026-08-05T12:00:00"}), field)
```

- [ ] **Step 3: RED를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_write_semantics.py tests/test_audit.py tests/test_cli.py -q
```

Expected: audit report에 timestamps 축과 CLI detail 경로가 없어 FAIL.

- [ ] **Step 4: 진단을 audit `ok` 계산 밖에 추가한다**

`collect_timestamp_diagnostics()`는 parse/timezone 문제와 정상 자정 빈도를 분리한다. 자정은 문제로 세지 않는다. `run_audit()`의 기존 lint/stale/quote `ok` 식은 바꾸지 않고 return payload에 `timestamps`만 추가한다.

details 파일은 absolute regular output path만 받고 atomic create한다. 기본 stdout에는 객체 ID를 넣지 않는다.

- [ ] **Step 5: focused suite를 통과시키고 commit한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_write_semantics.py tests/test_audit.py tests/test_cli.py -q
git add src/project_brain/write_semantics.py src/project_brain/audit.py \
  src/project_brain/cli.py tests/test_write_semantics.py \
  tests/test_audit.py tests/test_cli.py
git diff --cached --check
git commit -m "feat(brain): legacy 시간 부채 진단 추가"
```

---

### Task 11: installed runtime·JSON template·아키텍처 문서를 새 계약에 맞춘다

**Files:**
- Create: `src/project_brain/templates/ingest/references/object-templates/build-coverage.complete.template.json`
- Create: `src/project_brain/templates/ingest/references/object-templates/direct-coverage.template.json`
- Modify: `src/project_brain/templates/ingest/references/object-templates/build-notes.complete.template.json`
- Modify: `src/project_brain/templates/ingest/references/object-templates/README.md`
- Modify: `src/project_brain/templates/ingest/SKILL.md`
- Modify: `src/project_brain/templates/ingest/references/object-model.md`
- Modify: `src/project_brain/templates/ingest/references/ingest-tools.md`
- Modify: `src/project_brain/templates/ingest/references/completeness-checklist.md`
- Modify: `src/project_brain/templates/ingest/references/worked-example.md`
- Modify: `src/project_brain/templates/session-ingest/SKILL.md`
- Modify: `src/project_brain/templates/session-ingest/references/dev-ingest.md`
- Modify: `docs/architecture/runtime-map.md`
- Modify: `docs/architecture/data-contracts.md`
- Modify: `docs/architecture/change-map.md`
- Modify: `ROADMAP.md`
- Modify: `tests/test_object_contract_templates.py`
- Modify: `tests/test_ingest_skill_contract.py`
- Modify: `tests/test_ingest_skill_behavior_replay.py`
- Modify: `tests/test_universal_ingest_e2e.py`
- Modify: `tests/test_installer.py`
- Modify: `tests/test_architecture_docs.py`

**Interfaces:**
- Consumes: `normalize_coverage()`, `validate_assembled_inputs()`, `validate_write_semantics()`, canonical mutation receipt와 installed runtime 계약
- Produces: assembled/direct coverage JSON fixture, 설치된 문서/runtime와 repo 원본의 byte parity, 전체 지도에 반영된 P0 write path

- [ ] **Step 1: coverage template parity RED 테스트를 작성한다**

```python
def test_coverage_templates_cover_both_modes_and_are_canonical():
    assembled = read_json(TEMPLATES / "build-coverage.complete.template.json")
    direct = read_json(TEMPLATES / "direct-coverage.template.json")
    assert normalize_coverage(assembled).mode == "assembled"
    assert normalize_coverage(direct).mode == "direct"


def test_complete_notes_and_coverage_have_exact_same_section_identities():
    notes = read_json(TEMPLATES / "build-notes.complete.template.json")
    coverage = normalize_coverage(
        read_json(TEMPLATES / "build-coverage.complete.template.json")
    )
    validate_assembled_inputs(
        binding=coverage,
        verify_data=complete_verify_template_fixture(),
        notes=notes,
        store=BrainStore({}),
    )


def test_kind_templates_pass_final_schema_and_write_semantics():
    for path in sorted(KIND_TEMPLATES.glob("*.template.json")):
        obj = read_json(path)
        assert validate_object(obj) == [], path
        assert not validate_write_semantics(
            before_by_id={}, after_by_id={obj["id"]: obj}, source_id_by_after_id={}
        ).errors, path
```

기존 `BASE_REQUIRED|KIND_REQUIRED` key 제거 mutation 테스트는 유지한다. JSON template에 별도 필수 키 목록을 추가하지 않는다.

- [ ] **Step 2: installed workflow behavior RED 테스트를 작성한다**

```python
def test_ingest_skill_requires_coverage_at_assemble_build_ingest_and_finalize():
    text = installed_ingest_contract_text()
    for token in (
        "COVERAGE", "--coverage-out", "--coverage-file",
        "expected_objects", "verified_objects", "no_changes",
    ):
        assert token in text
    assert "GROUP_ORDER" not in text
    assert "context.now" not in text
    assert "NOW =" not in text
```

behavior replay는 coverage 없는 single/batch가 pre-write 실패하고 정상 direct/assembled dry run이 objects/raw/index를 쓰지 않는지 확인한다.

- [ ] **Step 3: RED를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_object_contract_templates.py tests/test_ingest_skill_contract.py \
  tests/test_ingest_skill_behavior_replay.py tests/test_universal_ingest_e2e.py \
  tests/test_installer.py -q
```

Expected: coverage JSON templates와 새 문서 계약이 없어 FAIL.

- [ ] **Step 4: 두 coverage JSON과 시간 예시 경계를 작성한다**

- `build-coverage.complete.template.json`: 8개 sections, context mode, verify groups, expected objects를 complete notes와 exact 맞춘다.
- `direct-coverage.template.json`: 최소 한 객체의 `(id,kind)`를 선언한다.
- kind template의 고정 시간은 JSON shape fixture일 뿐 실제 생성 시각 증거가 아니라고 README에 명시한다.
- installed docs는 coverage가 원문 의미 완전성을 추론하지 못한다는 한계와 수기 JSON은 다음 audit 전까지 탐지되지 않는다는 한계를 함께 적는다.

- [ ] **Step 5: 전체 지도의 write path를 실제 구현으로 갱신한다**

- `runtime-map.md`: coverage/expected planner/MutationService clock/no-op receipt/foundation gate 흐름
- `data-contracts.md`: 신규·변경 write semantic, timestamp owner map, template 단일 원본 경계
- `change-map.md`: coverage·timestamp·receipt·runtime 변경 시 focused/full/BB2 검증과 rebuild 불필요 조건
- `ROADMAP.md`: P0 완료 기준과 Task 18 blocked handoff. Task 18 migration을 완료로 표시하지 않는다.

- [ ] **Step 6: installer 2회 parity를 테스트한다**

임시 target에 install을 두 번 실행해 새 coverage JSON과 수정 runtime/docs가 manifest에 들어가고, 두 번째 report의 `created,updated,removed,adopted,skipped`가 모두 `[]`인지 assert한다. 사용자 수정 파일 skip/overlay 비관리/실행 비트/rollback 기존 테스트도 유지한다.

- [ ] **Step 7: focused suite와 installed unittest를 통과시키고 commit한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_object_contract_templates.py tests/test_ingest_skill_contract.py \
  tests/test_ingest_skill_behavior_replay.py tests/test_universal_ingest_e2e.py \
  tests/test_installer.py tests/test_architecture_docs.py -q
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
git add src/project_brain/templates/ingest/SKILL.md \
  src/project_brain/templates/ingest/references/object-templates/build-coverage.complete.template.json \
  src/project_brain/templates/ingest/references/object-templates/direct-coverage.template.json \
  src/project_brain/templates/ingest/references/object-templates/build-notes.complete.template.json \
  src/project_brain/templates/ingest/references/object-templates/README.md \
  src/project_brain/templates/ingest/references/object-model.md \
  src/project_brain/templates/ingest/references/ingest-tools.md \
  src/project_brain/templates/ingest/references/completeness-checklist.md \
  src/project_brain/templates/ingest/references/worked-example.md \
  src/project_brain/templates/session-ingest/SKILL.md \
  src/project_brain/templates/session-ingest/references/dev-ingest.md \
  docs/architecture/runtime-map.md docs/architecture/data-contracts.md \
  docs/architecture/change-map.md ROADMAP.md \
  tests/test_object_contract_templates.py tests/test_ingest_skill_contract.py \
  tests/test_ingest_skill_behavior_replay.py tests/test_universal_ingest_e2e.py \
  tests/test_installer.py tests/test_architecture_docs.py
git diff --cached --check
git commit -m "docs(brain): coverage와 시간 소유권 운영 계약 반영"
```

---

### Task 12: foundation baseline·불변성 검증 정본을 만든다

**Files:**
- Create: `src/project_brain/foundation.py`
- Create: `tests/test_foundation.py`
- Modify: `src/project_brain/snapshot.py`
- Modify: `tests/test_snapshot.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class TreeEntryReceipt:
    path: str
    entry_type: str
    mode: int
    size: int
    sha256: str


@dataclass(frozen=True)
class TreeReceipt:
    root: str
    entries: tuple[TreeEntryReceipt, ...]
    sha256: str


def capture_tree_receipt(
    root: Path,
    relative_paths: Collection[str],
    *,
    excluded_paths: Collection[Path] = (),
) -> TreeReceipt: ...

def verify_artifact_inventory(
    artifact_root: Path,
    *,
    allowed_files: Collection[Path],
    verified_snapshot_root: Path | None = None,
) -> TreeReceipt: ...

def capture_foundation_baseline(
    *,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
    artifact_root: Path,
    ignored_snapshots_root: Path,
) -> dict[str, object]: ...

def verify_foundation_invariants(
    baseline: Mapping[str, object],
    *,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
    allowed_managed_paths: Collection[str],
    allowed_installer_control_paths: Collection[str],
    artifact_root: Path,
    ignored_snapshots_root: Path,
    allowed_artifact_files: Collection[Path],
    verified_snapshot_root: Path | None,
) -> dict[str, object]: ...

def canonical_receipt_bytes(value: Mapping[str, object]) -> bytes: ...
def atomic_create_receipt(path: Path, value: Mapping[str, object]) -> str: ...
def atomic_create_bound_receipt(
    *,
    receipt_path: Path,
    binding_path: Path,
    value: Mapping[str, object],
) -> tuple[str, str]: ...

def verify_bound_receipt(
    *,
    receipt_path: Path,
    binding_path: Path,
    expected_purpose: str,
) -> dict[str, object]: ...
```

binding exact shape는 다음이다. gate binding은 purpose만 `p0-foundation-gate-binding`으로 바뀐다.

```json
{
  "version": 1,
  "purpose": "p0-foundation-baseline-binding",
  "receipt_path": "/absolute/path/foundation-baseline.json",
  "receipt_sha256": "<sha256>",
  "engine_head": "<git-sha>",
  "bb2_head": "<git-sha>"
}
```

baseline binding의 HEAD는 baseline receipt `engine.head`와 `bb2.head`, gate binding의 HEAD는 gate receipt `heads.engine`과 `heads.bb2_after`에서 가져온다. binding verifier는 purpose별 source field를 exact하게 고정하고 임의 fallback key를 찾지 않는다.

baseline exact 상위 shape:

```json
{
  "version": 1,
  "purpose": "p0-foundation-baseline",
  "roots": {},
  "artifact_root": "/absolute/task-owned/subtree",
  "artifact_inventory": {"root": "", "entries": [], "sha256": ""},
  "ignored_snapshots_inventory": {
    "root": "",
    "excluded_subtree": "2026-08-05/p0-foundation",
    "entries": [],
    "sha256": ""
  },
  "engine": {
    "head": "",
    "status_sha256": "",
    "status_porcelain_v1_z_base64": "",
    "dirt_content_manifest": [],
    "dirt_content_sha256": "",
    "core_paths": ["src/project_brain", "pyproject.toml", "uv.lock"],
    "core_tracked_tree_sha256": "",
    "import_file": "",
    "cli_source_file": "",
    "entrypoint": "project_brain.cli:main"
  },
  "bb2": {},
  "corpus": {
    "mutation_fingerprint": "",
    "objects_tree_sha256": "",
    "raw_tree_sha256": ""
  },
  "search_index": {
    "live_corpus_fingerprint": "",
    "meta_corpus_fingerprint": "",
    "db_file_sha256": ""
  },
  "runtime": {
    "manifest_sha256": "",
    "managed_files": []
  },
  "stale_set": {"sha256": ""}
}
```

- [ ] **Step 1: no-follow tree receipt RED 테스트를 작성한다**

```python
def test_tree_receipt_rejects_symlink_and_parent_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "safe.json").write_text("{}", encoding="utf-8")
    (root / "link.json").symlink_to(root / "safe.json")
    with pytest.raises(SnapshotError, match="symlink"):
        capture_tree_receipt(root, ["link.json"])
    with pytest.raises(SnapshotError, match="relative"):
        capture_tree_receipt(root, ["../outside"])


def test_tree_receipt_detects_file_replacement_during_read(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "object.json"
    target.write_text("before", encoding="utf-8")
    monkeypatch.setattr(snapshot, "_after_read_hook", lambda _: target.write_text("after"))
    with pytest.raises(SnapshotError, match="changed while reading"):
        capture_tree_receipt(root, ["object.json"])
```

기존 snapshot의 directory pinning, `O_NOFOLLOW`, before/after stat 비교를 public helper로 최소 승격해 재사용한다. foundation에 약한 별도 hash walker를 만들지 않는다.

- [ ] **Step 2: 잘못된 checkout·core dirt RED 테스트를 작성한다**

```python
def test_baseline_rejects_engine_core_dirt(foundation_fixture):
    (foundation_fixture.engine / "src/project_brain/new_untracked.py").write_text("x=1")
    with pytest.raises(FoundationError) as exc:
        capture_baseline(foundation_fixture)
    assert exc.value.code == "engine_core_dirty"


def test_baseline_rejects_import_from_another_checkout(foundation_fixture, monkeypatch):
    monkeypatch.setattr(foundation, "resolved_project_brain_file", lambda: Path("/tmp/other/project_brain/__init__.py"))
    with pytest.raises(FoundationError) as exc:
        capture_baseline(foundation_fixture)
    assert exc.value.code == "engine_checkout_mismatch"
```

core hash는 ignored `__pycache__`가 아니라 Git tracked path/mode/content로 계산한다. 별도로 core 아래 tracked/untracked dirt가 0인지 검사한다.

- [ ] **Step 3: corpus·raw·index·user dirt 불변 RED 테스트를 작성한다**

```python
@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (mutate_one_object, "objects_changed"),
        (mutate_one_raw_file, "raw_changed"),
        (mutate_index_db_bytes, "index_db_changed"),
        (mutate_preexisting_user_dirt, "user_dirt_changed"),
    ],
)
def test_foundation_verify_rejects_immutable_drift(foundation_fixture, mutator, code):
    baseline = capture_baseline(foundation_fixture)
    mutator(foundation_fixture)
    report = verify_invariants(foundation_fixture, baseline)
    assert report["ok"] is False
    assert code in report["errors"]


def test_foundation_verify_allows_only_stale_set_local_mutation(foundation_fixture):
    baseline = capture_baseline(foundation_fixture)
    mutate_stale_set(foundation_fixture)
    report = verify_invariants(foundation_fixture, baseline)
    assert report["ok"] is True
    assert report["observed_changes"]["expected_local_mutation"] == [
        "brain/.brain-local/stale-set.json"
    ]
```

- [ ] **Step 4: managed runtime commit allowlist·self exclusion RED 테스트를 작성한다**

```python
def test_allowed_bb2_head_change_is_derived_from_manifest_delta(foundation_fixture):
    baseline = capture_baseline(foundation_fixture)
    install_and_commit_managed_runtime_only(foundation_fixture)
    report = verify_invariants(foundation_fixture, baseline)
    assert report["ok"] is True
    assert set(report["observed_changes"]["bb2_commit_paths"]) == set(
        report["allowed_changes"]["managed_runtime_paths"]
        + report["allowed_changes"]["installer_control_paths"]
    )
    assert report["allowed_changes"]["installer_control_paths"] == [
        ".project-brain-manifest.json"
    ]


def test_receipt_excludes_only_exact_declared_artifact_paths(foundation_fixture):
    artifact = foundation_fixture.repo / ".snapshots/2026-08-05/p0-foundation/baseline.json"
    baseline = capture_foundation_baseline(
        **foundation_fixture.args,
        artifact_root=artifact.parent,
        ignored_snapshots_root=foundation_fixture.repo / ".snapshots",
    )
    create_other_file_in_same_directory(artifact.parent)
    report = verify_foundation_invariants(
        baseline, **foundation_fixture.args,
        allowed_managed_paths=(), allowed_installer_control_paths=(),
        artifact_root=artifact.parent,
        ignored_snapshots_root=foundation_fixture.repo / ".snapshots",
        allowed_artifact_files=[artifact], verified_snapshot_root=None,
    )
    assert report["ok"] is False
    assert "unexpected_dirt_path" in report["errors"]


def test_foundation_rejects_ignored_snapshot_drift_outside_artifact_root(
    foundation_fixture,
):
    baseline = capture_baseline(foundation_fixture)
    outside = foundation_fixture.repo / ".snapshots/2026-08-04/extra.json"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("{}\n", encoding="utf-8")
    report = verify_invariants(foundation_fixture, baseline)
    assert "ignored_snapshots_changed" in report["errors"]


@pytest.mark.parametrize("entry_kind", ["file", "symlink", "fifo"])
def test_artifact_inventory_rejects_unlisted_or_special_entry(
    foundation_fixture, entry_kind
):
    create_unlisted_artifact_entry(foundation_fixture, entry_kind)
    with pytest.raises(FoundationError, match="artifact_inventory"):
        verify_artifact_inventory(
            foundation_fixture.artifact_root,
            allowed_files=foundation_fixture.declared_artifacts,
        )


def test_artifact_inventory_allows_only_manifest_verified_snapshot_subtree(
    foundation_fixture,
):
    snapshot = create_and_verify_fixture_snapshot(foundation_fixture)
    receipt = verify_artifact_inventory(
        foundation_fixture.artifact_root,
        allowed_files=foundation_fixture.declared_artifacts,
        verified_snapshot_root=snapshot.snapshot_root,
    )
    assert receipt.entries


def test_atomic_create_bound_receipt_refuses_existing_or_symlink(tmp_path):
    receipt = tmp_path / "receipt.json"
    binding = tmp_path / "binding.json"
    receipt.write_text("{}\n", encoding="utf-8")
    with pytest.raises(FoundationError, match="exists"):
        atomic_create_bound_receipt(
            receipt_path=receipt,
            binding_path=binding,
            value=foundation_receipt_fixture(),
        )
    receipt.unlink()
    binding.symlink_to(tmp_path / "outside.json")
    with pytest.raises(FoundationError, match="symlink"):
        atomic_create_bound_receipt(
            receipt_path=receipt,
            binding_path=binding,
            value=foundation_receipt_fixture(),
        )


def test_atomic_create_bound_receipt_rolls_back_first_file_on_second_failure(
    tmp_path, monkeypatch
):
    receipt = tmp_path / "receipt.json"
    binding = tmp_path / "binding.json"
    fail_second_create(monkeypatch, binding)
    with pytest.raises(FoundationError, match="binding_create_failed"):
        atomic_create_bound_receipt(
            receipt_path=receipt,
            binding_path=binding,
            value=foundation_receipt_fixture(),
        )
    assert not receipt.exists()
    assert not binding.exists()


@pytest.mark.parametrize(
    "mutator,match",
    [
        (mutate_bound_receipt_bytes, "receipt_sha256"),
        (mutate_binding_receipt_path, "receipt_path"),
        (mutate_binding_purpose, "purpose"),
        (mutate_binding_engine_head, "engine_head"),
        (mutate_binding_bb2_head, "bb2_head"),
    ],
)
def test_verify_bound_receipt_rejects_tamper_path_purpose_or_head(
    tmp_path, mutator, match
):
    receipt, binding = create_bound_foundation_fixture(tmp_path)
    mutator(receipt, binding)
    with pytest.raises(FoundationError, match=match):
        verify_bound_receipt(
            receipt_path=receipt,
            binding_path=binding,
            expected_purpose="p0-foundation-baseline-binding",
        )
```

`.snapshots/`는 BB2 `.gitignore` 대상이라 Git status만으로는 이 테스트를 만족할 수 없다. `verify_artifact_inventory()`가 artifact root를 no-follow로 별도 재귀 스캔하고 exact allowed file set과 비교한다. snapshot subtree는 `verify_snapshot()`이 확인한 manifest entries만 허용한다. 같은 ignored directory의 선언하지 않은 sibling도 실패다.

- [ ] **Step 5: RED를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_snapshot.py tests/test_foundation.py -q
```

Expected: foundation module/public tree receipt가 없어 FAIL.

- [ ] **Step 6: 기존 안전 primitive를 재사용해 baseline을 구현한다**

- Git dirt는 porcelain `-z` raw bytes(base64)+SHA와 path/type/mode/size/content SHA를 모두 보존한다.
- object mutation fingerprint는 `mutation.corpus_fingerprint()`, live index input은 `search_index.compute_corpus_fingerprint()`, DB meta는 `read_meta_fingerprint()`, DB file은 별도 raw SHA다.
- managed runtime은 `.project-brain-manifest.json` bytes SHA와 각 recorded/actual file SHA를 보존한다.
- engine/BB2 root와 brain root는 absolute resolved path와 device/inode를 기록한다.
- receipt는 sort keys, compact separators, UTF-8, 마지막 LF 한 개다. 기존 output은 덮어쓰지 않는다.
- `atomic_create_bound_receipt()`는 state와 artifact inventory를 먼저 수집한 뒤 output parent를 만들고 receipt와 `{version,purpose,receipt_path,receipt_sha256,engine_head,bb2_head}` binding을 함께 atomic-create한다. 이후 단계는 receipt를 다시 해시해 자기 승인하지 않고 이 선행 binding의 SHA를 사용한다.
- `atomic_create_bound_receipt()`는 두 output을 모두 preflight한 뒤 `O_CREAT|O_EXCL|O_NOFOLLOW`로 만들고 file·parent directory를 fsync한다. 두 번째 생성이 실패하면 이번 호출이 만든 첫 파일만 안전하게 회수하고, 기존 경로는 절대 덮어쓰거나 지우지 않는다.
- `verify_bound_receipt()`는 path, purpose, receipt bytes SHA와 receipt 내부 engine/BB2 HEAD를 binding과 exact 비교한다. baseline의 BB2 HEAD는 설치 전 값이므로 현재 HEAD를 expected로 받지 않는다. 현재 상태 비교는 gate/handoff invariant가 별도로 수행한다. 이후 단계는 receipt를 사용 직전에 다시 해시해 그 값을 새 expected로 쓰지 않는다.
- baseline은 `.snapshots` 전체를 no-follow로 스캔하되 task-owned artifact subtree 하나만 exact 제외한다. verify/handoff는 제외 subtree 밖 inventory를 baseline과 exact 비교하고, task subtree는 선언 artifact와 verify된 snapshot manifest subtree만 허용한다.
- Git dirt 비교에서는 ignored artifact directory가 보인다고 가정하지 않는다. baseline/verify/handoff마다 ignored snapshot inventory와 exact task artifact inventory를 별도로 검증한다.

- [ ] **Step 7: focused suite를 통과시키고 commit한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_snapshot.py tests/test_foundation.py -q
git add src/project_brain/foundation.py src/project_brain/snapshot.py \
  tests/test_foundation.py tests/test_snapshot.py
git diff --cached --check
git commit -m "feat(brain): 비변이 foundation baseline 정본 추가"
```

---

### Task 13: 설치되는 foundation gate와 handoff receipt를 만든다

**Files:**
- Create: `src/project_brain/templates/ingest/scripts/validate_foundation.py`
- Create: `src/project_brain/templates/ingest/scripts/test_validate_foundation.py`
- Modify: `src/project_brain/foundation.py`
- Modify: `src/project_brain/installer.py`
- Modify: `tests/test_foundation.py`
- Modify: `tests/test_installer.py`
- Modify: `src/project_brain/templates/ingest/references/ingest-tools.md`
- Modify: `docs/architecture/runtime-map.md`
- Modify: `docs/architecture/change-map.md`
- Modify: `ROADMAP.md`

**Interfaces:**

```text
validate_foundation.py baseline
  --engine-root ABS --repo-root ABS --brain-root ABS
  --artifact-root ABS
  --output ABS --binding-output ABS

validate_foundation.py verify
  --engine-root ABS --repo-root ABS --brain-root ABS
  --artifact-root ABS
  --baseline PATH --baseline-binding PATH
  --install-report-1 PATH --install-report-2 PATH
  --output ABS --binding-output ABS

validate_foundation.py handoff
  --engine-root ABS --repo-root ABS --brain-root ABS
  --artifact-root ABS
  --baseline PATH --baseline-binding PATH
  --gate PATH --gate-binding PATH
  --snapshot-root ABS --snapshot-create-receipt PATH
  --snapshot-verify-receipt PATH --output ABS
```

```python
def normalize_installer_report_path(
    target_root: Path,
    value: str,
) -> str: ...

BB2_MANAGED_SKILL_ROOTS = (
    ".agents/skills/bb2-brain-query/",
    ".agents/skills/bb2-brain-ingest/",
    ".agents/skills/bb2-brain-session-ingest/",
    ".agents/skills/bb2-brain-audit/",
)

def task15_stage_paths(report: Mapping[str, object]) -> list[str]: ...
def validate_task15_cached_paths(
    *,
    preexisting_cached_paths: Sequence[str],
    cached_paths: Sequence[str],
    allowed_paths: Sequence[str],
) -> None: ...
```

새 installer report path 배열은 target-relative POSIX로 출력한다. gate는 전환 전 절대경로 report도 `normalize_installer_report_path()`로 읽는다. target 밖 절대경로, parent escape, 빈 값, 예상 밖 부모 symlink는 stage나 allowlist 계산 전에 실패한다.

installer report는 `target_root`와 `installer_control_paths`를 추가한다. `.project-brain-manifest.json`은 항상 control path다. `.project-brain.json`은 실제 created/updated일 때만 control path에 들어가며, BB2 P0에서는 baseline config가 이미 exact해야 하므로 first/second report의 control path는 정확히 `['.project-brain-manifest.json']`이어야 한다.

verify receipt exact 상위 shape:

```json
{
  "version": 1,
  "purpose": "p0-foundation-gate",
  "baseline": {"path": "", "sha256": ""},
  "heads": {"engine": "", "bb2_before": "", "bb2_after": ""},
  "install": {"first": {}, "second": {}},
  "commands": [],
  "before": {},
  "after": {},
  "allowed_changes": {},
  "observed_changes": {},
  "ok": true
}
```

command row exact shape는 `id,argv,cwd,exit_code,stdout,stdout_sha256,stderr,stderr_sha256,ok`다.
`allowed_changes` exact keys는 `managed_runtime_paths,installer_control_paths,expected_local_mutation_paths`다. BB2 commit path는 앞의 두 배열 합집합과 exact해야 하고, P0의 `installer_control_paths`는 `['.project-brain-manifest.json']`다.

- [ ] **Step 1: wrapper input와 command allowlist RED 테스트를 작성한다**

```python
def test_verify_rejects_tampered_baseline_with_unchanged_binding(runtime_module, fixture):
    fixture.baseline_path.write_bytes(fixture.baseline_path.read_bytes() + b" ")
    rc, report = runtime_module.main_result([
        "verify", *fixture.verify_args,
    ])
    assert rc == 1
    assert report["error_code"] == "baseline_sha256_mismatch"


def test_verify_rejects_non_noop_second_install(runtime_module, fixture):
    fixture.install_two["updated"] = [".agents/skills/bb2-brain-ingest/SKILL.md"]
    rc, report = runtime_module.main_result(["verify", *fixture.verify_args])
    assert rc == 1
    assert report["error_code"] == "installer_not_idempotent"


def test_foundation_command_set_forbids_finalizer_and_rebuild():
    argv_rows = foundation_command_specs(foundation_fixture())
    rendered = "\n".join(" ".join(row.argv) for row in argv_rows)
    assert "finalize_ingest" not in rendered
    assert "index rebuild" not in rendered


def test_normalize_installer_report_path_accepts_relative_and_target_absolute(tmp_path):
    target = tmp_path / "bb2"
    target.mkdir()
    relative = ".agents/skills/bb2-brain-ingest/SKILL.md"
    assert normalize_installer_report_path(target, relative) == relative
    assert normalize_installer_report_path(target, str(target / relative)) == relative


@pytest.mark.parametrize("value", ["../outside", "/tmp/outside", ""])
def test_normalize_installer_report_path_rejects_escape(tmp_path, value):
    target = tmp_path / "bb2"
    target.mkdir()
    with pytest.raises(InstallError, match="installer report path"):
        normalize_installer_report_path(target, value)


def test_install_report_lists_control_paths_exactly(installer_fixture):
    first = installer_fixture.install()
    assert first["target_root"] == str(installer_fixture.target.resolve())
    assert first["installer_control_paths"] == [
        ".project-brain-manifest.json", ".project-brain.json"
    ]
    second = installer_fixture.install()
    assert second["installer_control_paths"] == [
        ".project-brain-manifest.json"
    ]


def test_foundation_gate_normalizes_all_installer_change_arrays(gate_fixture):
    make_first_report_paths_absolute(gate_fixture)
    report = run_foundation_gate(gate_fixture)
    assert report["allowed_changes"]["managed_runtime_paths"] == sorted(
        gate_fixture.expected_relative_runtime_paths
    )


def test_task15_stage_allowlist_accepts_manifest_and_rejects_other_control_paths(
    gate_fixture,
):
    assert task15_stage_paths(gate_fixture.first_report) == sorted(
        gate_fixture.expected_relative_runtime_paths
        + [".project-brain-manifest.json"]
    )
    gate_fixture.first_report["installer_control_paths"].append(".project-brain.json")
    with pytest.raises(FoundationError, match="installer_control_paths"):
        task15_stage_paths(gate_fixture.first_report)


def test_task15_stage_rejects_preexisting_cached_paths(gate_fixture):
    with pytest.raises(FoundationError, match="preexisting cached"):
        validate_task15_cached_paths(
            preexisting_cached_paths=["user-owned.txt"],
            cached_paths=[],
            allowed_paths=task15_stage_paths(gate_fixture.first_report),
        )


def test_task15_stage_accepts_only_four_exact_managed_skill_roots(gate_fixture):
    for root in BB2_MANAGED_SKILL_ROOTS:
        gate_fixture.first_report["created"] = [f"{root}SKILL.md"]
        assert f"{root}SKILL.md" in task15_stage_paths(
            gate_fixture.first_report
        )
    gate_fixture.first_report["created"] = [
        ".agents/skills/bb2-brain-unlisted/SKILL.md"
    ]
    with pytest.raises(FoundationError, match="managed runtime path"):
        task15_stage_paths(gate_fixture.first_report)


def test_task15_cached_paths_are_subset_of_normalized_report_paths_and_controls(
    gate_fixture,
):
    allowed = task15_stage_paths(gate_fixture.first_report)
    with pytest.raises(FoundationError, match="empty cached"):
        validate_task15_cached_paths(
            preexisting_cached_paths=[],
            cached_paths=[],
            allowed_paths=allowed,
        )
    validate_task15_cached_paths(
        preexisting_cached_paths=[],
        cached_paths=allowed[:1],
        allowed_paths=allowed,
    )
    with pytest.raises(FoundationError, match="cached path"):
        validate_task15_cached_paths(
            preexisting_cached_paths=[],
            cached_paths=["brain/objects/user-owned.json"],
            allowed_paths=allowed,
        )
```

- [ ] **Step 2: installed runtime과 coverage dry smoke RED 테스트를 작성한다**

```python
def test_runtime_test_can_load_installed_script_from_env(monkeypatch, tmp_path):
    installed = tmp_path / "validate_foundation.py"
    installed.write_bytes(SOURCE_RUNTIME.read_bytes())
    monkeypatch.setenv("PROJECT_BRAIN_FOUNDATION_RUNTIME", str(installed))
    module = load_runtime_under_test()
    assert Path(module.__file__).resolve() == installed.resolve()


def test_coverage_smoke_writes_only_temporary_output(runtime_fixture):
    before = runtime_fixture.brain_fingerprints()
    result = runtime_fixture.run_coverage_smoke()
    assert result.returncode == 0
    assert runtime_fixture.brain_fingerprints() == before
```

`test_validate_foundation.py` 자체는 installer에서 제외한다. `PROJECT_BRAIN_FOUNDATION_RUNTIME`이 있으면 source test가 설치된 production script를 importlib로 로드해 같은 contract를 검증한다.

- [ ] **Step 3: failed command·invariant drift·handoff RED 테스트를 작성한다**

```python
def test_verify_records_nonzero_command_and_fails_gate(foundation_fixture):
    report = run_gate_with_command_result(foundation_fixture, command_id="lint", exit_code=1)
    assert report["ok"] is False
    assert next(c for c in report["commands"] if c["id"] == "lint")["ok"] is False


def test_handoff_rejects_tampered_gate_with_unchanged_binding(handoff_fixture):
    handoff_fixture.gate_path.write_bytes(
        handoff_fixture.gate_path.read_bytes() + b" "
    )
    with pytest.raises(FoundationError, match="gate_sha256"):
        build_handoff(handoff_fixture)


@pytest.mark.parametrize(
    "mutator",
    [
        mutate_snapshot_create_manifest_path,
        mutate_snapshot_create_manifest_sha,
        mutate_snapshot_verify_receipt_sha,
    ],
)
def test_handoff_rejects_snapshot_receipt_or_actual_manifest_mismatch(
    handoff_fixture, mutator
):
    mutator(handoff_fixture)
    with pytest.raises(FoundationError, match="snapshot"):
        build_handoff(handoff_fixture)


@pytest.mark.parametrize(
    "mutator, code",
    [
        (mutate_engine_head_after_gate, "engine_head_changed"),
        (mutate_engine_dirt_after_gate, "engine_dirt_changed"),
        (mutate_engine_core_after_gate, "engine_core_changed"),
        (mutate_engine_import_source_after_gate, "engine_checkout_mismatch"),
        (mutate_bb2_head_after_gate, "bb2_head_changed"),
        (mutate_bb2_user_dirt_after_gate, "user_dirt_changed"),
        (mutate_objects_after_snapshot, "objects_changed"),
        (mutate_raw_after_snapshot, "raw_changed"),
        (mutate_index_after_snapshot, "index_db_changed"),
        (mutate_runtime_after_gate, "runtime_changed"),
        (mutate_stale_set_after_gate, "stale_set_changed"),
        (mutate_ignored_snapshot_sibling, "ignored_snapshots_changed"),
        (mutate_task_artifact_sibling, "artifact_inventory_changed"),
    ],
)
def test_handoff_rechecks_final_state_and_writes_nothing_on_failure(
    handoff_fixture, mutator, code
):
    mutator(handoff_fixture)
    with pytest.raises(FoundationError, match=code):
        build_handoff(handoff_fixture)
    assert not handoff_fixture.output.exists()


@pytest.mark.parametrize(
    "mutator,code",
    [
        (mutate_engine_dirt_after_gate, "engine_dirt_changed"),
        (mutate_engine_import_source_after_gate, "engine_checkout_mismatch"),
        (mutate_runtime_after_gate, "runtime_changed"),
        (mutate_stale_set_after_gate, "stale_set_changed"),
    ],
)
def test_handoff_rechecks_engine_dirt_import_runtime_and_stale_set(
    handoff_fixture, mutator, code
):
    mutator(handoff_fixture)
    with pytest.raises(FoundationError, match=code):
        build_handoff(handoff_fixture)
    assert not handoff_fixture.output.exists()


def test_handoff_detects_drift_between_final_recheck_and_publish(
    handoff_fixture, monkeypatch
):
    monkeypatch.setattr(
        foundation,
        "_before_handoff_publish_hook",
        lambda: mutate_engine_core_after_gate(handoff_fixture),
    )
    with pytest.raises(FoundationError, match="engine_core_changed"):
        build_handoff(handoff_fixture)
    assert not handoff_fixture.output.exists()


def test_handoff_post_write_inventory_failure_removes_only_just_created_output(
    handoff_fixture, monkeypatch
):
    sibling = handoff_fixture.artifact_root / "unexpected-user-file.json"
    monkeypatch.setattr(
        foundation,
        "_after_handoff_write_hook",
        lambda: sibling.write_text("{}\n", encoding="utf-8"),
    )
    with pytest.raises(FoundationError, match="artifact_inventory"):
        build_handoff(handoff_fixture)
    assert not handoff_fixture.output.exists()
    assert sibling.exists()


def test_handoff_reruns_snapshot_verify_instead_of_trusting_receipt(
    handoff_fixture, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        foundation,
        "verify_snapshot",
        lambda *a, **kw: calls.append((a, kw)) or handoff_fixture.verification,
    )
    build_handoff(handoff_fixture)
    assert len(calls) == 1
```

- [ ] **Step 4: RED를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_foundation.py tests/test_installer.py -q
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest src.project_brain.templates.ingest.scripts.test_validate_foundation
```

Expected: wrapper와 gate command receipts가 없어 FAIL.

- [ ] **Step 5: fixed command set과 canonical gate를 구현한다**

verify는 아래 여섯 command만 exact interpreter/PYTHONPATH로 실행한다.

1. source unittest를 `PROJECT_BRAIN_FOUNDATION_RUNTIME=<installed script>`로 실행
2. BB2 `brain/checks` unittest
3. `project_brain.cli lint`
4. `project_brain.cli audit --no-fetch`
5. 기존 DB를 쓰는 `project_brain.cli eval`
6. 임시 brain/output에 installed complete notes+coverage를 쓰는 build dry smoke

각 command 전후와 전체 마지막에 objects/raw/index DB/engine core/user dirt invariant를 검사한다. audit의 stale-set만 expected local mutation으로 분류한다. baseline/gate binding은 receipt와 다른 파일로 create-only 고정되며 verify/handoff는 `verify_bound_receipt()`로 binding에 든 path·purpose·SHA·HEAD를 검사한다. receipt 파일을 사용 직전에 다시 해시한 값을 새 expected 값으로 쓰지 않는다.

verify 시작 artifact inventory는 baseline receipt/binding과 install-1/install-2 네 파일 exact, verify 종료 inventory는 여기에 gate receipt/binding 두 파일을 더한 exact 집합이다. `.snapshots` 전체의 task subtree 밖 inventory도 baseline과 같아야 한다. 첫 install의 `skipped`는 빈 배열이어야 하고, normalized change paths와 `installer_control_paths` 합집합만 BB2 commit 허용 경로가 된다.

- [ ] **Step 6: installer report path와 control path parity를 고정한다**

`installer.py`의 report path 배열은 target-relative POSIX로 바꾸고, reader는 이전 절대경로 report도 안전하게 정규화한다. `tests/test_installer.py`에서 다음을 고정한다.

- `validate_foundation.py`가 실행 비트와 manifest SHA를 갖고 설치됨
- `test_validate_foundation.py`는 설치되지 않음
- coverage templates도 managed manifest에 포함
- 두 번째 install의 5개 change 배열이 모두 비어 있음
- installer config가 `project=bb2, brain_root=brain, repo=bb2_client, default_branch=develop`와 exact 일치함
- `target_root`와 `installer_control_paths` exact shape
- target 밖 absolute/relative escape와 부모 symlink 거부
- first report의 `skipped=[]`, BB2 control path는 `.project-brain-manifest.json` 하나

- [ ] **Step 7: docs에 P0 gate와 Task 18 금지선을 반영한다**

`ingest-tools.md`, runtime/change map, ROADMAP에 foundation은 finalizer/rebuild를 호출하지 않고 P0 snapshot은 Task 18 migration binding이 아니라는 점을 명시한다.

handoff는 gate receipt만 읽고 끝내지 않는다. snapshot create/verify 뒤 engine HEAD·전체 dirt·core tracked tree·core dirt·import/CLI source, BB2 HEAD·기존 user dirt, objects tree·mutation fingerprint, raw tree, index DB SHA·live/meta fingerprint, runtime manifest·managed files, stale-set, ignored `.snapshots`, task artifact inventory를 새로 측정해 gate의 `after`와 exact 대조한다. canonical output bytes를 만든 뒤 `_before_handoff_publish_hook` 다음, create-only publish 직전에 같은 측정을 한 번 더 수행해 첫 final recheck 및 gate와 exact 대조한다. snapshot create receipt의 actual manifest path/SHA를 교차 검증하고 `verify_snapshot()`도 다시 실행한다.

artifact root의 허용 집합은 baseline/gate receipt와 두 binding, install-1/2, snapshot-create/verify receipt, manifest가 증명한 snapshot subtree뿐이다. handoff output은 두 번째 recheck가 성공한 뒤 `O_CREAT|O_EXCL|O_NOFOLLOW`로 쓰고 file·parent를 fsync한다. post-write inventory에서는 자기 output 한 경로만 추가 허용한다. post-write 검사가 실패하면 이번 호출이 만든 output의 device/inode를 확인한 뒤 그 파일만 회수하고, 새로 생긴 sibling이나 기존 파일은 지우지 않는다. receipt에는 복사한 gate 값이 아니라 두 recheck에서 일치한 새 측정값을 `final_recheck`로 넣는다. `_before_handoff_publish_hook`과 `_after_handoff_write_hook`은 테스트에서만 monkeypatch하는 no-op private seam이며 CLI에는 노출하지 않는다.

- [ ] **Step 8: focused suite를 통과시키고 commit한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest \
  tests/test_foundation.py tests/test_snapshot.py tests/test_installer.py \
  tests/test_architecture_docs.py -q
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest src.project_brain.templates.ingest.scripts.test_validate_foundation
git add src/project_brain/foundation.py \
  src/project_brain/installer.py \
  src/project_brain/templates/ingest/scripts/validate_foundation.py \
  src/project_brain/templates/ingest/scripts/test_validate_foundation.py \
  src/project_brain/templates/ingest/references/ingest-tools.md \
  tests/test_foundation.py tests/test_installer.py \
  docs/architecture/runtime-map.md docs/architecture/change-map.md ROADMAP.md
git diff --cached --check
git commit -m "feat(brain): 비변이 foundation 검증 gate 추가"
```

---

### Task 14: 전체 엔진 회귀·독립 리뷰 뒤 `main`에 통합한다

**Files:**
- Modify only if a verified defect is found: Tasks 1-13 listed files
- Read only: both engine worktrees and their Git state

**Interfaces:**
- Consumes: `feat/ingest-integrity-foundation`의 Task 0-13 path-limited commits와 두 full test suite
- Produces: fast-forward된 engine `main`, clean tracked state, Task 15가 baseline에 결속할 최종 engine HEAD

- [ ] **Step 1: `superpowers:verification-before-completion`을 읽고 full gate를 실행한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
cd "$ENGINE"
uv sync --extra mecab
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest -q
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
git status --short
git diff --check
```

Expected: 두 suite PASS, tracked/untracked worktree clean. 실패하면 해당 소유 Task로 돌아가 RED 재현→수정→focused/full 재검증→path-limited commit한다.

- [ ] **Step 2: installer를 임시 target에 실제로 두 번 적용한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/ingest-integrity-foundation
TARGET="$(mktemp -d -t project-brain-p0-install.XXXXXX)"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli install \
  --target "$TARGET" --project demo --brain-root brain > "$TARGET/install-1.json"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli install \
  --target "$TARGET" --project demo --brain-root brain > "$TARGET/install-2.json"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" - "$TARGET/install-2.json" <<'PY'
import json, sys
report = json.load(open(sys.argv[1], encoding="utf-8"))
for field in ("created", "updated", "removed", "adopted", "skipped"):
    assert report[field] == [], (field, report[field])
PY
```

Expected: 두 번째 report 5개 배열 모두 empty. 임시 target은 사용자 레포가 아니므로 검증 후 남겨둘 필요가 없다. 제거는 `mktemp`가 출력한 exact path를 다시 확인한 뒤에만 한다.

- [ ] **Step 3: `superpowers:requesting-code-review`로 설계 대비 독립 리뷰를 받는다**

reviewer에게 다음 blocker checklist를 그대로 준다.

```text
1. coverage planner가 assembly.build output을 읽지 않는가
2. INGEST coverage/delete/rename/aux gate에 fallback이 없는가
3. no-op이 clock/corpus를 안 건드리고 durable receipt를 남기는가
4. operation/action timestamp matrix가 설계와 exact한가
5. finalizer가 item별 expected==verified를 검사하는가
6. foundation gate가 finalizer/index rebuild를 호출하지 않는가
7. BB2 objects/raw/index/user dirt 불변을 증명할 수 있는가
8. Task 18 코드·binding·코퍼스를 건드리지 않았는가
9. baseline/gate를 immutable binding으로만 소비하고 사용 시점 재해시로 자기 승인하지 않는가
10. handoff가 snapshot 뒤 heads/dirt/core/objects/raw/index/ignored snapshots/artifacts를 새로 측정하는가
```

Blocker가 있으면 수정한 Task의 focused suite와 Step 1 full gate를 다시 돈다. 단순 의견은 설계 범위를 넓히지 않는다.

- [ ] **Step 4: `superpowers:finishing-a-development-branch`를 읽고 fast-forward 통합 전 상태를 확인한다**

```bash
ENGINE_SOURCE=/Users/al03040455/Downloads/codes/project-brain
ENGINE_WORKTREE="$ENGINE_SOURCE/.worktrees/ingest-integrity-foundation"
test -z "$(git -C "$ENGINE_SOURCE" status --porcelain --untracked-files=no)"
git -C "$ENGINE_SOURCE" merge-base --is-ancestor main feat/ingest-integrity-foundation
git -C "$ENGINE_WORKTREE" status --short
```

Expected: 원본 main tracked clean, feature worktree clean. 원본 main의 기존 untracked 파일은 그대로 보존한다.

- [ ] **Step 5: `main`을 fast-forward하고 main checkout에서 full gate를 다시 실행한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
git -C "$ENGINE" merge --ff-only feat/ingest-integrity-foundation
cd "$ENGINE"
uv sync --extra mecab
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest -q
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
git status --short --branch
```

Expected: full PASS, `main` tracked clean. 이 시점 이후 엔진 commit을 만들지 않는다.

---

### Task 15: BB2 runtime을 제한 설치하고 비변이 gate·snapshot·handoff를 확정한다

**Files:**
- Modify and commit in BB2 only: installer first report가 열거한 `.agents/skills/bb2-brain-query/`, `.agents/skills/bb2-brain-ingest/`, `.agents/skills/bb2-brain-session-ingest/`, `.agents/skills/bb2-brain-audit/` 아래 managed runtime paths and `.project-brain-manifest.json`
- Create, do not commit: `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-05/p0-foundation/foundation-baseline.json`
- Create, do not commit: `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-05/p0-foundation/foundation-baseline.binding.json`
- Create, do not commit: `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-05/p0-foundation/install-1.json`
- Create, do not commit: `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-05/p0-foundation/install-2.json`
- Create, do not commit: `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-05/p0-foundation/foundation-gate.json`
- Create, do not commit: `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-05/p0-foundation/foundation-gate.binding.json`
- Create, do not commit: `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-05/p0-foundation/snapshot-create.json`
- Create, do not commit: `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-05/p0-foundation/snapshot-verify.json`
- Create, do not commit: `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-05/p0-foundation/p0-handoff.json`
- Preserve: all pre-existing BB2 user dirt and Task 18 artifacts

**Interfaces:**
- Consumes: Task 13의 installed `validate_foundation.py`, immutable baseline/gate binding, installer report path normalizer, snapshot create/verify receipt
- Produces: BB2 managed runtime-only commit, verified foundation gate, P0 rollback snapshot, final recheck가 결속된 `p0-handoff.json`

**Fixed paths:**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
PY=/Users/al03040455/Downloads/codes/project-brain/.venv/bin/python
ARTIFACTS=/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-05/p0-foundation
SOURCE_GATE=/Users/al03040455/Downloads/codes/project-brain/src/project_brain/templates/ingest/scripts/validate_foundation.py
INSTALLED_GATE=/Users/al03040455/Desktop/bb2_client/.agents/skills/bb2-brain-ingest/scripts/validate_foundation.py
```

- [ ] **Step 1: 최종 engine HEAD에서 BB2를 건드리기 전 baseline을 만든다**

```bash
set -euo pipefail
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
PY="$ENGINE/.venv/bin/python"
ARTIFACTS="$BB2/.snapshots/2026-08-05/p0-foundation"
SOURCE_GATE="$ENGINE/src/project_brain/templates/ingest/scripts/validate_foundation.py"
test ! -e "$ARTIFACTS"
PYTHONPATH="$ENGINE/src" "$PY" "$SOURCE_GATE" baseline \
  --engine-root "$ENGINE" \
  --repo-root "$BB2" \
  --brain-root "$BB2/brain" \
  --artifact-root "$ARTIFACTS" \
  --output "$ARTIFACTS/foundation-baseline.json" \
  --binding-output "$ARTIFACTS/foundation-baseline.binding.json"
```

Expected: baseline `ok=true`; create-only binding의 path/purpose/SHA/engine·BB2 HEAD가 baseline과 일치; engine core clean; `project_brain.__file__`와 CLI source가 `$ENGINE/src/project_brain` 아래; BB2 config가 `project=bb2, brain_root=brain, repo=bb2_client, default_branch=develop`와 exact 일치; BB2 objects/raw/index/meta/runtime/user dirt와 artifact subtree 밖 ignored `.snapshots` 지문이 모두 기록됨. 하나라도 아니면 설치 전에 멈춘다.

- [ ] **Step 2: baseline SHA를 독립 계산하고 installer를 정확히 두 번 실행한다**

```bash
set -euo pipefail
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
PY="$ENGINE/.venv/bin/python"
ARTIFACTS="$BB2/.snapshots/2026-08-05/p0-foundation"
cd "$BB2"
PYTHONPATH="$ENGINE/src" "$PY" - \
  "$ARTIFACTS/foundation-baseline.json" \
  "$ARTIFACTS/foundation-baseline.binding.json" <<'PY'
import hashlib, json, sys
from pathlib import Path

receipt_path = Path(sys.argv[1]).resolve()
binding_path = Path(sys.argv[2]).resolve()
receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
binding = json.loads(binding_path.read_text(encoding="utf-8"))
assert set(binding) == {
    "version", "purpose", "receipt_path", "receipt_sha256",
    "engine_head", "bb2_head",
}
assert binding["version"] == 1
assert binding["purpose"] == "p0-foundation-baseline-binding"
assert binding["receipt_path"] == str(receipt_path)
assert binding["receipt_sha256"] == hashlib.sha256(receipt_path.read_bytes()).hexdigest()
assert binding["engine_head"] == receipt["engine"]["head"]
assert binding["bb2_head"] == receipt["bb2"]["head"]
PY
PYTHONPATH="$ENGINE/src" "$PY" -m project_brain.cli install \
  --target "$BB2" --project bb2 --brain-root brain \
  --default-branch develop --repo bb2_client \
  > "$ARTIFACTS/install-1.json"
PYTHONPATH="$ENGINE/src" "$PY" -m project_brain.cli install \
  --target "$BB2" --project bb2 --brain-root brain \
  --default-branch develop --repo bb2_client \
  > "$ARTIFACTS/install-2.json"
PYTHONPATH="$ENGINE/src" "$PY" - "$BB2" \
  "$ARTIFACTS/install-1.json" "$ARTIFACTS/install-2.json" <<'PY'
import json, sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
first = json.load(open(sys.argv[2], encoding="utf-8"))
second = json.load(open(sys.argv[3], encoding="utf-8"))
for report in (first, second):
    assert report["ok"] is True
    assert Path(report["target_root"]).resolve() == root
    assert report["installer_control_paths"] == [
        ".project-brain-manifest.json"
    ]
assert first["skipped"] == []
for field in ("created", "updated", "removed", "adopted", "skipped"):
    assert second[field] == [], (field, second[field])
PY
```

`project-brain bootstrap`은 index rebuild를 포함하므로 쓰지 않는다.

- [ ] **Step 3: first install의 managed path만 BB2에 stage하고 commit한다**

다음 strict-shell Python은 기존 cached set이 있거나 report path가 네 exact managed root 밖이면 stage 전에 실패한다. stage 뒤에도 실제 cached set이 normalized report/control allowlist의 비어 있지 않은 부분집합인지 검사하고, 같은 exact pathspec으로만 commit한다.

```bash
set -euo pipefail
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
PY="$ENGINE/.venv/bin/python"
REPORT="$BB2/.snapshots/2026-08-05/p0-foundation/install-1.json"
PYTHONPATH="$ENGINE/src" "$PY" - "$BB2" "$REPORT" <<'PY'
import json, subprocess, sys
from pathlib import Path
from project_brain.foundation import (
    task15_stage_paths,
    validate_task15_cached_paths,
)

def cached_paths(root: Path) -> list[str]:
    raw = subprocess.check_output(
        ["git", "-C", str(root), "diff", "--cached", "--name-only", "-z"]
    )
    return [value.decode("utf-8") for value in raw.split(b"\0") if value]

root = Path(sys.argv[1]).resolve()
report = json.load(open(sys.argv[2], encoding="utf-8"))
if Path(report["target_root"]).resolve() != root:
    raise SystemExit("installer target_root mismatch")
if report.get("skipped") != []:
    raise SystemExit(f"installer skipped managed files: {report.get('skipped')}")
preexisting = cached_paths(root)
if preexisting:
    raise SystemExit(f"refusing preexisting cached paths: {preexisting}")
stage = task15_stage_paths(report)
subprocess.run(["git", "-C", str(root), "add", "--", *stage], check=True)
cached = cached_paths(root)
validate_task15_cached_paths(
    preexisting_cached_paths=preexisting,
    cached_paths=cached,
    allowed_paths=stage,
)
subprocess.run(["git", "-C", str(root), "diff", "--cached", "--check"], check=True)
print("\n".join(cached))
subprocess.run(
    [
        "git", "-C", str(root), "commit", "--only",
        "-m", "chore(brain): P0 적재 무결성 runtime 갱신",
        "--", *stage,
    ],
    check=True,
)
PY
```

Expected: commit path는 install report의 네 managed runtime root와 manifest뿐이다. 기존 cached set이 하나라도 있으면 commit 전에 멈추며 기존 user dirt나 `brain/`은 포함되지 않는다.

- [ ] **Step 4: installed gate로 비변이 final verify를 실행한다**

```bash
set -euo pipefail
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
PY="$ENGINE/.venv/bin/python"
ARTIFACTS="$BB2/.snapshots/2026-08-05/p0-foundation"
INSTALLED_GATE="$BB2/.agents/skills/bb2-brain-ingest/scripts/validate_foundation.py"
PYTHONPATH="$ENGINE/src" "$PY" "$INSTALLED_GATE" verify \
  --engine-root "$ENGINE" \
  --repo-root "$BB2" \
  --brain-root "$BB2/brain" \
  --artifact-root "$ARTIFACTS" \
  --baseline "$ARTIFACTS/foundation-baseline.json" \
  --baseline-binding "$ARTIFACTS/foundation-baseline.binding.json" \
  --install-report-1 "$ARTIFACTS/install-1.json" \
  --install-report-2 "$ARTIFACTS/install-2.json" \
  --output "$ARTIFACTS/foundation-gate.json" \
  --binding-output "$ARTIFACTS/foundation-gate.binding.json"
```

Expected: receipt `ok=true`; baseline bytes는 선행 binding과 일치하고 gate receipt/binding은 create-only; installed runtime unittest, BB2 checks, lint, audit --no-fetch, eval, coverage dry smoke 모두 0; objects/raw/index DB/engine core/기존 user dirt와 artifact subtree 밖 ignored `.snapshots` 불변; stale-set만 expected local mutation. BB2 commit path는 normalized managed runtime + `.project-brain-manifest.json` exact이고 finalizer와 index rebuild command row는 0개다.

- [ ] **Step 5: audit 뒤 P0 rollback snapshot을 만들고 verify한다**

```bash
set -euo pipefail
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
PY="$ENGINE/.venv/bin/python"
ARTIFACTS="$BB2/.snapshots/2026-08-05/p0-foundation"
PYTHONPATH="$ENGINE/src" "$PY" -m project_brain.cli snapshot create \
  --brain-root "$BB2/brain" \
  --repo-root "$BB2" \
  --engine-root "$ENGINE" \
  --output-root "$ARTIFACTS" \
  --snapshot-id p0-foundation-corpus \
  > "$ARTIFACTS/snapshot-create.json"
SNAPSHOT_ROOT="$(PYTHONPATH="$ENGINE/src" "$PY" -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["snapshot_root"])' \
  "$ARTIFACTS/snapshot-create.json")"
SNAPSHOT_MANIFEST="$(PYTHONPATH="$ENGINE/src" "$PY" -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["manifest_path"])' \
  "$ARTIFACTS/snapshot-create.json")"
RECEIPT_SNAPSHOT_SHA="$(PYTHONPATH="$ENGINE/src" "$PY" -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["manifest_sha256"])' \
  "$ARTIFACTS/snapshot-create.json")"
PYTHONPATH="$ENGINE/src" "$PY" - "$SNAPSHOT_ROOT" "$SNAPSHOT_MANIFEST" <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
manifest = Path(sys.argv[2]).resolve()
assert manifest == root / "manifest.json", (manifest, root)
PY
ACTUAL_SNAPSHOT_SHA="$(shasum -a 256 "$SNAPSHOT_MANIFEST" | awk '{print $1}')"
test "$ACTUAL_SNAPSHOT_SHA" = "$RECEIPT_SNAPSHOT_SHA"
PYTHONPATH="$ENGINE/src" "$PY" -m project_brain.cli snapshot verify \
  --snapshot-root "$SNAPSHOT_ROOT" \
  --expected-manifest-sha256 "$ACTUAL_SNAPSHOT_SHA" \
  > "$ARTIFACTS/snapshot-verify.json"
```

Expected: create/verify 둘 다 `ok=true`; create receipt path는 실제 `$SNAPSHOT_ROOT/manifest.json`이고 receipt SHA·독립 `shasum`·verify receipt SHA가 exact 일치. 이 snapshot은 P0 rollback·불변 증거이며 Task 18 migration snapshot으로 쓰지 않는다.

- [ ] **Step 6: gate·snapshot을 결속한 handoff receipt를 만든다**

```bash
set -euo pipefail
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
PY="$ENGINE/.venv/bin/python"
ARTIFACTS="$BB2/.snapshots/2026-08-05/p0-foundation"
INSTALLED_GATE="$BB2/.agents/skills/bb2-brain-ingest/scripts/validate_foundation.py"
SNAPSHOT_ROOT="$(PYTHONPATH="$ENGINE/src" "$PY" -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["snapshot_root"])' \
  "$ARTIFACTS/snapshot-create.json")"
PYTHONPATH="$ENGINE/src" "$PY" "$INSTALLED_GATE" handoff \
  --engine-root "$ENGINE" \
  --repo-root "$BB2" \
  --brain-root "$BB2/brain" \
  --artifact-root "$ARTIFACTS" \
  --baseline "$ARTIFACTS/foundation-baseline.json" \
  --baseline-binding "$ARTIFACTS/foundation-baseline.binding.json" \
  --gate "$ARTIFACTS/foundation-gate.json" \
  --gate-binding "$ARTIFACTS/foundation-gate.binding.json" \
  --snapshot-root "$SNAPSHOT_ROOT" \
  --snapshot-create-receipt "$ARTIFACTS/snapshot-create.json" \
  --snapshot-verify-receipt "$ARTIFACTS/snapshot-verify.json" \
  --output "$ARTIFACTS/p0-handoff.json"
```

Expected: handoff가 선행 baseline/gate binding을 소비하고 snapshot create receipt·actual manifest·verify receipt를 다시 교차 검증한다. canonical output 생성 전과 create-only publish 직전에 heads/dirt/core/import, objects/raw/index, runtime, stale-set, ignored `.snapshots`, task artifact inventory를 각각 새로 측정해 gate after 및 서로 exact 대조한 `final_recheck`를 담으며, `task18_status="blocked_pending_new_measurement_design_binding"`, `ok=true`다. 재검사 실패 시 output은 생성되지 않고, post-write inventory 실패 시 이번 호출이 방금 만든 output만 안전하게 회수한다.

- [ ] **Step 7: 마지막 상태를 읽기 전용으로 확인하고 멈춘다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
ARTIFACTS="$BB2/.snapshots/2026-08-05/p0-foundation"
git -C "$ENGINE" status --short --branch
git -C "$BB2" status --short --branch
shasum -a 256 \
  "$ARTIFACTS/foundation-baseline.json" \
  "$ARTIFACTS/foundation-baseline.binding.json" \
  "$ARTIFACTS/foundation-gate.json" \
  "$ARTIFACTS/foundation-gate.binding.json" \
  "$ARTIFACTS/snapshot-create.json" \
  "$ARTIFACTS/snapshot-verify.json" \
  "$ARTIFACTS/p0-handoff.json"
```

여기서 끝낸다. gate 뒤 commit, index rebuild, Task 18 binding 생성, migration plan/apply, corpus timestamp 보정은 하지 않는다.

---

## Task 18 Handoff Contract

P0 handoff 뒤 Task 18은 다음 순서가 아니면 시작하지 않는다.

1. 표시 라벨 대상·quote backlog·`origin/develop`을 새로 측정하고 receipt를 만든다.
2. 새 Task 18 설계와 실행 계획을 commit하고 사용자 승인을 받는다.
3. binding 생성기·독립 verifier·migration gate를 TDD로 구현하고 commit한다.
4. `audit --no-fetch`를 실행한다.
5. 새 Task 18 pre-mutation snapshot을 만들고 verify한다.
6. 그 snapshot과 최종 engine/BB2 HEAD를 묶은 binding을 마지막에 발급하고 독립 검증한다.
7. 그 뒤 commit이나 다른 corpus write 없이 migration plan/apply로 이어간다.

기존 `docs/superpowers/specs/2026-08-04-task18-display-labels-and-quote-backlog-design.md`, 계획, binding은 역사 자료로만 보존한다. P0 구현에서 수정하거나 실행하지 않는다.

## Spec Coverage Self-Review

| 설계 요구 | 구현 Task |
|---|---|
| assembled/direct CoverageContract, independent planner | 1-3 |
| 일반 INGEST coverage·operation gate | 3 |
| 신규/변경 write semantic + field-value grandfathering | 4-5 |
| LIVE/PRESERVE/context action timestamp matrix | 5-7 |
| preview 무시계·실제 apply 단일 clock·artifact 우회 제거 | 5-7 |
| no-op/committed canonical receipt | 8 |
| batch coverage SHA, overlap, resume, item exactness | 9 |
| timestamp legacy/midnight nonblocking diagnostics | 10 |
| JSON templates, installed runtime, architecture map | 11 |
| non-mutating baseline/gate/installer parity | 12-13 |
| immutable receipt binding·ignored snapshots·artifact exact inventory | 12-15 |
| full engine review and main integration | 14 |
| BB2 install, invariant proof, snapshot, P0 handoff | 15 |
| Task 18 blocked order | Task 15 + handoff contract |

구현 종료 전 다음 plan 자체 점검도 다시 실행한다.

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
PLAN="$ENGINE/docs/superpowers/plans/2026-08-05-ingest-integrity-foundation.md"
rg -n 'TO[D]O|TB[D]|나중에[[:space:]]+채움|similar[[:space:]]+to|write[[:space:]]+tests' "$PLAN"
rg -n 'skip-coverage|preserve-timestamps|index rebuild|finalize_ingest' "$PLAN"
```

첫 명령은 0 matches여야 한다. 두 번째는 금지선 설명과 Task 13의 검증용 문자열 검사에만 나타나야 하며 실제 P0 gate command에는 없어야 한다.

## Execution Handoff

이 계획은 하나의 쓰기 경계를 순서대로 바꾸므로 Task 1→15 순서를 지킨다. 실행 방식은 다음 둘 중 하나다.

1. **Subagent-Driven (recommended):** 이 세션에서 Task별 구현 agent와 spec/code-review agent를 분리하고, 매 Task 커밋 뒤 다음 Task로 간다.
2. **Inline Execution:** 새 세션에서 `superpowers:executing-plans`로 checkpoint 단위 실행한다.
