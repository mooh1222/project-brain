# BB2 Brain stale-check / mark-checked Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 엔진 레포 `project-brain`에 두 CLI 명령을 추가한다 — `stale-check`(남이 develop 코드를 고쳐 brain 매핑 의미가 낡았을 수 있는 곳을 읽기 전용으로 찾아 후보 제시)와 `mark-checked`(사람이 "의미 그대로"라고 판정한 매핑이 한 CodeLocator의 영향 매핑 전체를 덮으면 그 locator의 `commit_sha`/`verified_at`/`updated_at`를 갱신).

**Architecture:** 순수 로직은 새 모듈 `src/project_brain/stale_check.py`에, CLI 배선은 기존 `src/project_brain/cli.py`에 둔다(`promote`·`session` 서브커맨드와 같은 구조). git 호출(`fetch`/`rev-parse`/`diff`)은 `git_runner` 콜러블로 주입한다 — 실제 호출은 `make_git_runner(repo_root)`가 `subprocess`로 만들고, 테스트는 합성 입력을 돌려주는 가짜 runner를 주입해 네트워크·실레포 없이 결정론으로 돈다(embedder 주입 패턴과 동형). 기계는 "어느 파일이 바뀌어 어느 매핑이 영향권인가"를 찾기까지, "그 변경이 의미를 바꿨나"는 사람이 판정한다("코드 자동 비교 금지").

**Tech Stack:** Python 3, 표준 라이브러리만(`subprocess`, `datetime`, `argparse`, `json`). 테스트는 `unittest` + `unittest.mock`(엔진 레포 기존 테스트와 동일). 패키지 매니저 `uv`.

**Spec:** `docs/superpowers/specs/2026-06-14-bb2-brain-stale-check-design.md` (게임 레포). 이 plan은 그 spec을 구현 단위로 분해한 것이다.

**구현 위치:** 엔진 레포 `~/Downloads/codes/project-brain` (브랜치 `main`). 데이터 레포(`~/Desktop/bb2_client/brain`)는 Task 8 회귀에서만 만진다.

**선행 — 개발 환경 (한 번):**
```bash
cd ~/Downloads/codes/project-brain
uv sync --extra mecab
.venv/bin/python -m pytest tests/ -q   # 베이스라인: 전부 green이어야 시작
```

---

## File Structure

| 파일 | 역할 | 신규/수정 |
|---|---|---|
| `src/project_brain/stale_check.py` | stale-check / mark-checked 순수 로직 — closure 계산, coverage 리포트, git_runner, 변경 감지, locator 갱신. 도메인 무지(객체 dict만 다룸). | 신규 |
| `src/project_brain/cli.py` | `_run_stale_check` / `_run_mark_checked` 함수 + `main()` 서브커맨드 분기 2줄. | 수정 |
| `tests/test_stale_check.py` | 로직 단위 테스트 + CLI 배선 테스트(자기완결 — 인라인 빌더 + 가짜 git_runner). | 신규 |

`stale_check.py`는 git_runner를 인자로만 받아 `subprocess`를 함수 안에서만 부른다 — 로직 함수는 git을 모른다(테스트성·단일 책임). CLI가 `make_git_runner`로 실제 runner를 만들어 주입한다.

---

## 핵심 데이터 사실 (spec §6 — 구현 중 가정으로 삼지 말고 그대로 따른다)

- `path`/`commit_sha`를 가진 kind는 **CodeLocator**뿐(EvidenceRef는 stale 대상 아님 — §5). CodeLocator 363개 전부 `commit_sha` 보유.
- **DomainMapping의 `code_locator_ids`는 schema 필수 필드가 아니다**(`schema.py:33`엔 없음). 매핑 229개 중 208개만 가지고 21개는 비었거나 없다 → coverage 리포트로 가시화(자동 처리 안 함).
- **매핑 `status` 분포**: reviewed 222 / candidate 5 / superseded 2. closure의 **blocking은 `reviewed`만**, `superseded`는 제외(옛 사실), `candidate`는 mark를 안 막고 warning.
- 2개 이상 매핑이 공유하는 CodeLocator 57개 — 그래서 매핑 하나만 보고 locator의 `commit_sha`를 올리면 같은 locator의 다른 미검토 reviewed 매핑이 다음 점검에서 빠진다(closure 전체 검토를 갱신 조건으로 거는 이유).
- CodeLocator 갱신은 `commit_sha`(=checked_head sha) / `verified_at`·`updated_at`(=mark 실행 시각 ISO8601)만. **`line_start`/`line_end`는 불변**(Task 4 실측: 줄 어긋남은 회상에 무해).

---

## Task 1: closure 계산 (`compute_closure`)

한 CodeLocator를 `code_locator_ids`로 가리키는 매핑을 status로 분류한다. `mark-checked`의 "영향 매핑 전체를 덮었나" 판정과 `stale-check`의 locator_group 출력이 모두 이걸 쓴다.

**Files:**
- Create: `src/project_brain/stale_check.py`
- Test: `tests/test_stale_check.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_stale_check.py` 신규 생성:

```python
"""stale-check / mark-checked 로직·CLI 테스트.

자기완결: 인라인 객체 빌더 + 가짜 git_runner만 쓴다(실 git·네트워크 없음).
spec: docs/superpowers/specs/2026-06-14-bb2-brain-stale-check-design.md

★import은 Task별로 실제 쓰는 것만 둔다(엔진 레포 관행 — 쓰는 import만 상단). 이 Task 1은
unittest·BrainStore만 쓰고, io/json/tempfile/redirect_stdout/Path/mock/cli는 CLI 테스트가
처음 등장하는 Task 5에서 추가한다. 미래 Task용 import를 미리 두지 말 것(dead import).
"""
import unittest

from project_brain.store import BrainStore


def code_locator(cid, *, path, commit_sha, symbol="sym", line_start=10, line_end=20):
    from project_brain.objbase import base
    return base({
        "id": cid, "kind": "CodeLocator", "status": "reviewed", "truth_role": "reference",
        "title": f"Code: {symbol}", "repo": "bb2_client", "path": path, "symbol": symbol,
        "line_start": line_start, "line_end": line_end,
        "locator_source": "rg", "verified_at": "2026-06-12T00:00:00Z",
        "commit_sha": commit_sha, "evidence_refs": [],
    }, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")


def domain_mapping(mid, *, code_locator_ids, status="reviewed"):
    from project_brain.objbase import base
    obj = {
        "id": mid, "kind": "DomainMapping", "status": status, "truth_role": "domain",
        "title": f"Mapping {mid}", "context_id": "context.x", "mapping_key": mid,
        "canonical_summary": "요약", "meaning": "의미", "boundary": "경계",
        "glossary_term_ids": [], "decision_record_ids": [],
        "code_locator_ids": code_locator_ids,
        "evidence_refs": ["ev.x"] if status == "reviewed" else [],
    }
    if status == "candidate":
        obj["candidate"] = {"candidate_state": "ready_for_review", "candidate_source": "spec"}
    return base(obj, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")


def _store(*objs):
    return BrainStore({o["id"]: o for o in objs})


class ComputeClosureTest(unittest.TestCase):
    def test_blocking_is_reviewed_only_superseded_excluded_candidate_nonblocking(self):
        from project_brain.stale_check import compute_closure
        store = _store(
            code_locator("code.shared", path="a/X.cpp", commit_sha="SHA1"),
            domain_mapping("m.r1", code_locator_ids=["code.shared"], status="reviewed"),
            domain_mapping("m.r2", code_locator_ids=["code.shared"], status="reviewed"),
            domain_mapping("m.cand", code_locator_ids=["code.shared"], status="candidate"),
            domain_mapping("m.sup", code_locator_ids=["code.shared"], status="superseded"),
        )
        closure = compute_closure(store, "code.shared")
        self.assertEqual(closure["blocking"], ["m.r1", "m.r2"])
        self.assertEqual(closure["nonblocking"], ["m.cand", "m.sup"])

    def test_locator_with_no_referencing_mappings(self):
        from project_brain.stale_check import compute_closure
        store = _store(code_locator("code.lonely", path="a/Y.cpp", commit_sha="SHA1"))
        self.assertEqual(compute_closure(store, "code.lonely"),
                         {"blocking": [], "nonblocking": []})
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_stale_check.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'project_brain.stale_check'`

- [ ] **Step 3: 최소 구현**

`src/project_brain/stale_check.py` 신규 생성:

```python
"""코드 변경 → 의미 갱신 대상 발견 (stale-check) 로직.

spec: docs/superpowers/specs/2026-06-14-bb2-brain-stale-check-design.md
git 호출은 git_runner 콜러블로 주입한다 — 로직 함수는 git을 모른다(테스트는
합성 입력으로 대체, 네트워크·실레포 무관). 기계는 "어느 파일이 바뀌어 어느
매핑이 영향권인가"까지 찾고, "의미가 진짜 낡았나"는 사람이 판정한다.
"""
from __future__ import annotations


def _mappings_referencing(store, locator_id):
    """code_locator_ids에 locator_id를 가진 DomainMapping 목록(id 정렬). compute_closure 전용 내부 헬퍼."""
    out = [m for m in store.by_kind("DomainMapping")
           if locator_id in (m.get("code_locator_ids") or [])]
    return sorted(out, key=lambda m: m["id"])


def compute_closure(store, locator_id):
    """locator를 가리키는 매핑을 status로 분류.

    blocking = status==reviewed (현재 진실 — mark 충족 대상).
    nonblocking = candidate/superseded/archived/rejected (mark를 막지 않음).
    """
    blocking, nonblocking = [], []
    for m in _mappings_referencing(store, locator_id):
        if m.get("status") == "reviewed":
            blocking.append(m["id"])
        else:
            nonblocking.append(m["id"])
    return {"blocking": blocking, "nonblocking": nonblocking}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/stale_check.py tests/test_stale_check.py
git commit -m "feat(stale-check): compute_closure — reviewed blocking, superseded/candidate nonblocking"
```

---

## Task 2: coverage 리포트 (`coverage_report`)

매핑을 `code_locator_ids` 유무로 나눈다. covered는 stale-check로 역추적 가능, uncovered는 사각(21개) — 팀 공유용이면 이 숫자 없이 "사각 없다"는 착각을 준다(spec §3).

**Files:**
- Modify: `src/project_brain/stale_check.py`
- Test: `tests/test_stale_check.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_stale_check.py`에 클래스 추가(`ComputeClosureTest` 아래):

```python
class CoverageReportTest(unittest.TestCase):
    def test_covered_vs_uncovered_with_reason_and_code_evref_flag(self):
        from project_brain.objbase import base
        from project_brain.stale_check import coverage_report
        # code를 가리키는 EvidenceRef(ref_type=='code_locator')만 가진 uncovered 매핑.
        code_evref = base({
            "id": "evref.code", "kind": "EvidenceRef", "status": "reviewed",
            "truth_role": "reference", "title": "code ref",
            "evidence_manifest_id": "ev.m", "ref_type": "code_locator",
            "locator": {"object_id": "code.z"}, "summary": "코드 근거",
        }, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")
        m_code_evref = domain_mapping("m.codeevref", code_locator_ids=[])
        m_code_evref["evidence_refs"] = ["evref.code"]
        store = _store(
            code_locator("code.a", path="a/X.cpp", commit_sha="SHA1"),
            domain_mapping("m.covered", code_locator_ids=["code.a"]),
            domain_mapping("m.empty", code_locator_ids=[]),
            code_evref, m_code_evref,
        )
        report = coverage_report(store)
        self.assertEqual(report["covered_mappings"], ["m.covered"])
        unc = {u["mapping_id"]: u for u in report["uncovered_mappings"]}
        self.assertEqual(set(unc), {"m.empty", "m.codeevref"})
        self.assertEqual(unc["m.empty"]["skipped_reason"], "no_code_locator_ids")
        self.assertFalse(unc["m.empty"]["has_code_evidence_ref"])
        # m.codeevref는 code_locator_ids는 없지만 code EvidenceRef를 가짐 → subset 가시화.
        self.assertTrue(unc["m.codeevref"]["has_code_evidence_ref"])

    def test_missing_code_locator_ids_field_is_uncovered(self):
        from project_brain.objbase import base
        from project_brain.stale_check import coverage_report
        # code_locator_ids 키 자체가 없는 매핑도 uncovered(빈 것과 동급).
        m = base({
            "id": "m.nofield", "kind": "DomainMapping", "status": "reviewed",
            "truth_role": "domain", "title": "t", "context_id": "context.x",
            "mapping_key": "k", "canonical_summary": "s", "meaning": "m",
            "boundary": "b", "glossary_term_ids": [], "decision_record_ids": [],
            "evidence_refs": ["ev.x"],
        }, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")
        store = _store(m)
        report = coverage_report(store)
        self.assertEqual([u["mapping_id"] for u in report["uncovered_mappings"]], ["m.nofield"])
        self.assertEqual(report["uncovered_mappings"][0]["skipped_reason"], "no_code_locator_ids")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py::CoverageReportTest -q`
Expected: FAIL — `ImportError: cannot import name 'coverage_report'`

- [ ] **Step 3: 최소 구현**

`src/project_brain/stale_check.py`에 `compute_closure` 아래 추가:

```python
def _has_code_evidence_ref(store, mapping):
    """매핑의 evidence_refs 중 코드를 가리키는 것(ref_type=='code_locator')이 있나."""
    for rid in (mapping.get("evidence_refs") or []):
        if store.has(rid) and store.get(rid).get("ref_type") == "code_locator":
            return True
    return False


def coverage_report(store):
    """매핑을 code_locator_ids 유무로 분류(spec §3·§6).

    covered_mappings = code_locator_ids 비어있지 않음(stale-check 역추적 가능)의 id 목록.
    uncovered_mappings = 비었거나 키 없음의 [{mapping_id, skipped_reason, has_code_evidence_ref}]
      — "왜 사각인지"(skipped_reason)와 code EvidenceRef만 가진 부분집합
      (has_code_evidence_ref)을 출력 계약에 박아 가시화한다. 자동 처리는 안 한다.
    """
    covered, uncovered = [], []
    for m in store.by_kind("DomainMapping"):
        if m.get("code_locator_ids"):
            covered.append(m["id"])
        else:
            uncovered.append({
                "mapping_id": m["id"],
                "skipped_reason": "no_code_locator_ids",
                "has_code_evidence_ref": _has_code_evidence_ref(store, m),
            })
    return {"covered_mappings": sorted(covered),
            "uncovered_mappings": sorted(uncovered, key=lambda u: u["mapping_id"])}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/project_brain/stale_check.py tests/test_stale_check.py
git commit -m "feat(stale-check): coverage_report — covered vs uncovered mappings"
```

---

## Task 3: git_runner + 변경 감지 (`make_git_runner` / `resolve_target_head` / `path_changed`)

git을 주입 가능하게 분리한다. `make_git_runner(repo_root)`가 실제 `subprocess` runner를 만들고, `resolve_target_head`는 `fetch` 후 `origin/develop` sha를, `path_changed`는 한 `(commit_sha, path)`가 target_head까지 바뀌었는지(`git diff --name-status`)를 판정한다.

**Files:**
- Modify: `src/project_brain/stale_check.py`
- Test: `tests/test_stale_check.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_stale_check.py` 상단 import 블록 바로 아래(빌더 함수들 위 또는 아래, 모듈 레벨)에 가짜 runner 헬퍼 추가:

```python
def fake_git_runner(target_head, changed):
    """changed: {(from_commit, path): change_type}. 없는 키는 '안 바뀜'(빈 출력).

    git diff args 형태: ["diff", "--name-status", "FROM..TARGET", "--", "PATH"].
    """
    calls = []

    def run(args):
        calls.append(args)
        if args[:1] == ["fetch"]:
            return ""
        if args[:1] == ["rev-parse"]:
            return target_head + "\n"
        if args[:2] == ["diff", "--name-status"]:
            from_commit = args[2].split("..")[0]
            path = args[4]
            ct = changed.get((from_commit, path))
            return f"{ct}\t{path}\n" if ct else ""
        raise AssertionError(f"unexpected git args: {args}")

    run.calls = calls
    return run
```

그리고 테스트 클래스 추가:

```python
class GitDetectionTest(unittest.TestCase):
    def test_resolve_target_head_fetches_then_rev_parse(self):
        from project_brain.stale_check import resolve_target_head
        runner = fake_git_runner("TARGETSHA", {})
        head = resolve_target_head(runner, fetch=True)
        self.assertEqual(head, "TARGETSHA")
        self.assertEqual(runner.calls[0], ["fetch", "origin", "develop"])
        self.assertEqual(runner.calls[1], ["rev-parse", "origin/develop"])

    def test_resolve_target_head_no_fetch_skips_fetch(self):
        from project_brain.stale_check import resolve_target_head
        runner = fake_git_runner("TARGETSHA", {})
        resolve_target_head(runner, fetch=False)
        self.assertEqual(runner.calls, [["rev-parse", "origin/develop"]])

    def test_path_changed_returns_change_type_when_changed(self):
        from project_brain.stale_check import path_changed
        runner = fake_git_runner("TARGET", {("SHA1", "a/X.cpp"): "M"})
        self.assertEqual(path_changed(runner, "SHA1", "TARGET", "a/X.cpp"), "M")

    def test_path_changed_returns_none_when_unchanged(self):
        from project_brain.stale_check import path_changed
        runner = fake_git_runner("TARGET", {})
        self.assertIsNone(path_changed(runner, "SHA1", "TARGET", "a/X.cpp"))

    def test_path_changed_rename_returns_status_token(self):
        # rename은 실제 git에서 R100\told\tnew 3컬럼이지만 path_changed는 첫 탭 토큰만 쓴다.
        from project_brain.stale_check import path_changed
        runner = fake_git_runner("TARGET", {("SHA1", "a/X.cpp"): "R100"})
        self.assertEqual(path_changed(runner, "SHA1", "TARGET", "a/X.cpp"), "R100")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py::GitDetectionTest -q`
Expected: FAIL — `ImportError: cannot import name 'resolve_target_head'`

- [ ] **Step 3: 최소 구현**

`src/project_brain/stale_check.py` 상단 `from __future__ import annotations` 아래에 import 추가:

```python
import subprocess
```

그리고 모듈 끝에 추가:

```python
class GitError(RuntimeError):
    pass


def make_git_runner(repo_root, *, timeout=60):
    """repo_root에서 git을 실행하는 runner를 만든다. 실패·타임아웃 시 GitError.

    timeout: git 호출(특히 fetch)이 네트워크 행으로 무한 블로킹하지 않게 하는 상한(초).
    """
    def run(args):
        try:
            result = subprocess.run(
                ["git"] + args, capture_output=True, text=True,
                cwd=str(repo_root), timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"git {' '.join(args)} timed out after {timeout}s") from exc
        if result.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout
    return run


def resolve_target_head(git_runner, *, fetch=True):
    """origin/develop의 현재 sha. fetch=True면 먼저 origin develop을 가져온다.

    brain 브랜치 워킹트리는 develop보다 구버전이라 비교 기준은 항상 origin/develop.
    """
    if fetch:
        git_runner(["fetch", "origin", "develop"])
    return git_runner(["rev-parse", "origin/develop"]).strip()


def path_changed(git_runner, from_commit, target_head, path):
    """from_commit 이후 target_head까지 path가 바뀌었으면 change_type(M/A/D/R…),
    안 바뀌었으면 None. --name-status로 rename/delete 종류까지 사람이 보게 한다."""
    out = git_runner(
        ["diff", "--name-status", f"{from_commit}..{target_head}", "--", path]
    ).strip()
    if not out:
        return None
    # 첫 줄의 첫 탭 토큰이 status(rename은 R100 등) — 대표값 그대로 운반.
    return out.splitlines()[0].split("\t")[0]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/project_brain/stale_check.py tests/test_stale_check.py
git commit -m "feat(stale-check): injectable git_runner + change detection (fetch/rev-parse/diff)"
```

---

## Task 4: stale-check 통합 (`stale_check`)

CodeLocator를 `(path, commit_sha)` 단위로 순회하며(같은 쌍은 한 번만 diff) 바뀐 locator를 찾고, 그 locator의 blocking 매핑을 후보로, locator마다 `locator_group`을, 전체 `coverage`와 `target_head`를 조립한다. **brain 데이터는 안 건드린다(읽기 전용).**

**Files:**
- Modify: `src/project_brain/stale_check.py`
- Test: `tests/test_stale_check.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_stale_check.py`에 클래스 추가:

```python
class StaleCheckTest(unittest.TestCase):
    def _corpus(self):
        return _store(
            code_locator("code.changed", path="a/Changed.cpp", commit_sha="SHA1"),
            code_locator("code.same", path="a/Same.cpp", commit_sha="SHA1"),
            domain_mapping("m.on_changed", code_locator_ids=["code.changed"]),
            domain_mapping("m.on_same", code_locator_ids=["code.same"]),
            domain_mapping("m.uncovered", code_locator_ids=[]),
        )

    def test_only_changed_file_mappings_become_candidates(self):
        from project_brain.stale_check import stale_check
        runner = fake_git_runner("TARGET", {("SHA1", "a/Changed.cpp"): "M"})
        report = stale_check(self._corpus(), git_runner=runner, fetch=True)
        self.assertEqual(report["target_head"], "TARGET")
        cand_ids = [c["mapping_id"] for c in report["candidates"]]
        self.assertEqual(cand_ids, ["m.on_changed"])  # 안 바뀐 code.same 매핑은 제외

    def test_locator_group_carries_closure_and_change_type(self):
        from project_brain.stale_check import stale_check
        runner = fake_git_runner("TARGET", {("SHA1", "a/Changed.cpp"): "M"})
        report = stale_check(self._corpus(), git_runner=runner, fetch=True)
        self.assertEqual(len(report["locator_group"]), 1)
        g = report["locator_group"][0]
        self.assertEqual(g["locator_id"], "code.changed")
        self.assertEqual(g["change_type"], "M")
        self.assertEqual(g["from_commit"], "SHA1")
        self.assertEqual(g["target_head"], "TARGET")
        self.assertEqual(g["blocking_affected_mapping_ids"], ["m.on_changed"])
        self.assertEqual(g["nonblocking_affected_mapping_ids"], [])

    def test_coverage_included(self):
        from project_brain.stale_check import stale_check
        runner = fake_git_runner("TARGET", {})
        report = stale_check(self._corpus(), git_runner=runner, fetch=True)
        uncovered_ids = {u["mapping_id"] for u in report["coverage"]["uncovered_mappings"]}
        self.assertIn("m.uncovered", uncovered_ids)
        self.assertEqual(report["candidates"], [])  # 아무것도 안 바뀌면 후보 0

    def test_explicit_target_head_skips_resolve(self):
        from project_brain.stale_check import stale_check
        runner = fake_git_runner("UNUSED", {("SHA1", "a/Changed.cpp"): "M"})
        report = stale_check(self._corpus(), git_runner=runner, target_head="GIVEN")
        self.assertEqual(report["target_head"], "GIVEN")
        # target_head 주면 fetch도 rev-parse도 안 함 — diff만 호출됨(회귀 방지로 둘 다 assert)
        self.assertTrue(all(c[0] != "fetch" for c in runner.calls))
        self.assertTrue(all(c[0] != "rev-parse" for c in runner.calls))

    def test_locator_without_commit_sha_skipped(self):
        from project_brain.stale_check import stale_check
        from project_brain.objbase import base
        loc_no_sha = base({
            "id": "code.nosha", "kind": "CodeLocator", "status": "reviewed",
            "truth_role": "reference", "title": "t", "repo": "bb2_client",
            "path": "a/NoSha.cpp", "symbol": "s", "locator_source": "rg",
            "verified_at": "2026-06-12T00:00:00Z", "evidence_refs": [],
        }, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")
        store = _store(loc_no_sha,
                       domain_mapping("m.x", code_locator_ids=["code.nosha"]))
        runner = fake_git_runner("TARGET", {})
        report = stale_check(store, git_runner=runner, target_head="TARGET")
        self.assertEqual(report["candidates"], [])  # 기준점 없는 locator는 건너뜀
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py::StaleCheckTest -q`
Expected: FAIL — `ImportError: cannot import name 'stale_check'`

- [ ] **Step 3: 최소 구현**

`src/project_brain/stale_check.py` 모듈 끝에 추가:

```python
def stale_check(store, *, git_runner, target_head=None, fetch=True):
    """바뀐 파일을 가리키는 매핑 후보 + locator_group + coverage + target_head.

    target_head를 주면 git fetch/rev-parse를 건너뛴다(테스트·재실행). 읽기 전용 —
    brain 데이터는 절대 안 건드린다. 구현 키는 (path, commit_sha) 쌍이다(같은 path를
    commit_sha 다른 locator가 가리키면 각각 판정).
    """
    if target_head is None:
        target_head = resolve_target_head(git_runner, fetch=fetch)

    change_cache = {}  # (path, commit_sha) → change_type or None
    locator_group = []
    candidate_mapping_ids = set()
    for loc in store.by_kind("CodeLocator"):
        path = loc.get("path")
        from_commit = loc.get("commit_sha")
        if not path or not from_commit:
            continue  # 기준점 없는 locator는 비교 불가 — 건너뜀
        key = (path, from_commit)
        if key not in change_cache:
            change_cache[key] = path_changed(git_runner, from_commit, target_head, path)
        change_type = change_cache[key]
        if change_type is None:
            continue
        closure = compute_closure(store, loc["id"])
        locator_group.append({
            "locator_id": loc["id"],
            "path": path,
            "from_commit": from_commit,
            "target_head": target_head,
            "change_type": change_type,
            "blocking_affected_mapping_ids": list(closure["blocking"]),
            "nonblocking_affected_mapping_ids": list(closure["nonblocking"]),
        })
        candidate_mapping_ids.update(closure["blocking"])

    locator_group.sort(key=lambda g: g["locator_id"])
    candidates = []
    for mid in sorted(candidate_mapping_ids):
        m = store.get(mid)
        locs = [g for g in locator_group
                if mid in g["blocking_affected_mapping_ids"]]
        candidates.append({
            "mapping_id": mid,
            "mapping_key": m.get("mapping_key"),
            "stale_locators": [
                {"locator_id": g["locator_id"], "path": g["path"],
                 "change_type": g["change_type"], "from_commit": g["from_commit"]}
                for g in locs
            ],
        })

    return {
        "target_head": target_head,
        "candidates": candidates,
        "locator_group": locator_group,
        "coverage": coverage_report(store),
    }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py -q`
Expected: PASS (14 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/project_brain/stale_check.py tests/test_stale_check.py
git commit -m "feat(stale-check): stale_check — candidates + locator_group + coverage (read-only)"
```

---

## Task 5: stale-check CLI 배선 (`_run_stale_check`)

`cli.py`에 서브커맨드를 더한다(`promote`·`session`과 같은 구조). 실제 git_runner는 `make_git_runner(repo_root)`로 만들고, 기본 `repo_root`는 brain-root의 부모(데이터 레포 루트)다. `--no-fetch`로 오프라인·테스트를 지원한다.

**Files:**
- Modify: `src/project_brain/cli.py`
- Test: `tests/test_stale_check.py`

- [ ] **Step 1: 실패하는 테스트 작성**

먼저 `tests/test_stale_check.py` 상단 import 블록에 CLI 테스트가 쓰는 import를 추가한다. 기존 `import unittest` / `from project_brain.store import BrainStore`와 합쳐 최종 블록이 아래 형태가 되도록(표준 라이브러리 먼저, 빈 줄, 로컬):

```python
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from project_brain import cli
from project_brain.store import BrainStore
```

그리고 CLI 테스트 클래스 추가:

```python
class CliStaleCheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, argv, runner):
        out = io.StringIO()
        # CLI가 make_git_runner로 만드는 실제 runner를 가짜로 바꿔치기.
        with mock.patch("project_brain.stale_check.make_git_runner", return_value=runner), \
             mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        return rc, json.loads(out.getvalue())

    def test_stale_check_outputs_candidates_and_coverage(self):
        for obj in (
            code_locator("code.changed", path="a/Changed.cpp", commit_sha="SHA1"),
            domain_mapping("m.on_changed", code_locator_ids=["code.changed"]),
            domain_mapping("m.uncovered", code_locator_ids=[]),
        ):
            BrainStore.save_object(self.root, obj)
        runner = fake_git_runner("TARGET", {("SHA1", "a/Changed.cpp"): "M"})
        rc, payload = self._run(
            ["stale-check", "--brain-root", str(self.root), "--no-fetch"], runner)
        self.assertEqual(rc, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual([c["mapping_id"] for c in payload["candidates"]], ["m.on_changed"])
        uncovered_ids = {u["mapping_id"] for u in payload["coverage"]["uncovered_mappings"]}
        self.assertIn("m.uncovered", uncovered_ids)
        self.assertEqual(payload["target_head"], "TARGET")
        # 읽기 전용: locator의 commit_sha가 그대로다(stale-check는 갱신 안 함).
        self.assertEqual(BrainStore.load(self.root).get("code.changed")["commit_sha"], "SHA1")

    def test_stale_check_git_error_returns_rc1(self):
        # --no-fetch 없이 실행 → resolve_target_head의 fetch 단계에서 GitError → rc=1.
        BrainStore.save_object(
            self.root, code_locator("code.a", path="a/X.cpp", commit_sha="SHA1"))

        def boom(args):
            from project_brain.stale_check import GitError
            raise GitError("git rev-parse origin/develop failed: unknown revision")

        rc, payload = self._run(
            ["stale-check", "--brain-root", str(self.root)], boom)
        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("failed", payload["error"])
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py::CliStaleCheckTest -q`
Expected: FAIL — `argparse`가 `stale-check`를 위치인자 query로 처리해 rc≠0 또는 KeyError (서브커맨드 분기 없음)

- [ ] **Step 3: 최소 구현**

`src/project_brain/cli.py`의 `_run_bootstrap` 함수 정의 끝(line 449 `return ...` 다음 빈 줄)과 `def main()` 사이에 새 함수 추가:

```python
def _run_stale_check(argv) -> int:
    """코드 변경 → 의미 갱신 대상 발견 (spec §3). 읽기 전용 — brain 데이터 불변."""
    parser = argparse.ArgumentParser(prog="cli stale-check")
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config)")
    parser.add_argument("--repo-root", help="git 레포 루트 (기본: brain-root의 부모 — brain이 레포 루트 직하라 가정)")
    parser.add_argument("--no-fetch", action="store_true",
                        help="git fetch 생략(오프라인·테스트)")
    args = parser.parse_args(argv)

    from project_brain.stale_check import GitError, make_git_runner, stale_check

    brain_root = resolve_brain_root(args.brain_root)
    store = BrainStore.load(brain_root)
    repo_root = Path(args.repo_root) if args.repo_root else brain_root.parent
    git_runner = make_git_runner(repo_root)
    try:
        report = stale_check(store, git_runner=git_runner, fetch=not args.no_fetch)
    except GitError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))
    return 0
```

그리고 `main()`의 `if argv and argv[0] == "bootstrap":` 블록 바로 아래에 분기 추가:

```python
        if argv and argv[0] == "stale-check":
            return _run_stale_check(argv[1:])
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py -q`
Expected: PASS (16 passed)

- [ ] **Step 5: 회귀 + 커밋**

```bash
.venv/bin/python -m pytest tests/ -q   # 기존 CLI 경로 안 깨졌는지 전체
git add src/project_brain/cli.py tests/test_stale_check.py
git commit -m "feat(stale-check): cli stale-check subcommand"
```
Expected: 전체 green (기존 + 신규)

---

## Task 6: mark-checked 로직 (`mark_checked`)

사람이 "의미 그대로"로 판정한 매핑(`mapping_ids`)이 어떤 CodeLocator의 **blocking closure 전부**를 덮으면 그 locator를 갱신한다(`commit_sha`=checked_head / `verified_at`·`updated_at`=now, **`line_*` 불변**). 하나라도 빠지면 `blocked`로 반환(공유 locator의 안 본 reviewed 매핑이 조용히 빠지는 사각 방지). `checked_head`가 현재 origin/develop과 다르면 즉시 실패(head 이동 경합 가드). 저장은 안 한다 — 갱신된 객체만 반환(CLI가 schema 검증 후 save).

**Files:**
- Modify: `src/project_brain/stale_check.py`
- Test: `tests/test_stale_check.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_stale_check.py`에 클래스 추가:

```python
class MarkCheckedTest(unittest.TestCase):
    def _shared(self):
        # code.shared를 reviewed 매핑 둘이 공유 + candidate 1 + superseded 1이 가리킴.
        return _store(
            code_locator("code.shared", path="a/X.cpp", commit_sha="OLD",
                         line_start=40, line_end=80),
            domain_mapping("m.r1", code_locator_ids=["code.shared"]),
            domain_mapping("m.r2", code_locator_ids=["code.shared"]),
            domain_mapping("m.cand", code_locator_ids=["code.shared"], status="candidate"),
            domain_mapping("m.sup", code_locator_ids=["code.shared"], status="superseded"),
        )

    def test_full_closure_updates_keeps_lines_warns_candidate_only(self):
        from project_brain.stale_check import mark_checked
        store = self._shared()
        result = mark_checked(store, mapping_ids=["m.r1", "m.r2"],
                              checked_head="NEW", current_head="NEW",
                              now="2026-06-14T12:00:00Z")
        self.assertTrue(result["ok"])
        self.assertEqual([l["id"] for l in result["updated"]], ["code.shared"])
        loc = result["updated"][0]
        self.assertEqual(loc["commit_sha"], "NEW")
        self.assertEqual(loc["verified_at"], "2026-06-14T12:00:00Z")
        self.assertEqual(loc["updated_at"], "2026-06-14T12:00:00Z")
        self.assertEqual(loc["line_start"], 40)  # line 불변
        self.assertEqual(loc["line_end"], 80)
        # warning은 candidate만 — superseded(m.sup)는 현재 사실 아니라 제외(spec §4).
        self.assertEqual(result["warnings"],
                         [{"locator_id": "code.shared", "candidate_mapping_ids": ["m.cand"]}])
        # store 불변(저장은 CLI 책임) — 핵심 갱신 경로에서 원본 commit_sha가 안 바뀜.
        self.assertEqual(store.get("code.shared")["commit_sha"], "OLD")

    def test_partial_closure_blocks_and_does_not_update(self):
        from project_brain.stale_check import mark_checked
        result = mark_checked(self._shared(), mapping_ids=["m.r1"],
                              checked_head="NEW", current_head="NEW",
                              now="2026-06-14T12:00:00Z")
        self.assertTrue(result["ok"])
        self.assertEqual(result["updated"], [])  # m.r2가 빠져 갱신 안 함
        self.assertEqual(result["blocked"],
                         [{"locator_id": "code.shared", "missing_mapping_ids": ["m.r2"]}])

    def test_head_moved_guard(self):
        from project_brain.stale_check import mark_checked
        result = mark_checked(self._shared(), mapping_ids=["m.r1", "m.r2"],
                              checked_head="A", current_head="B",
                              now="2026-06-14T12:00:00Z")
        self.assertFalse(result["ok"])
        self.assertIn("head moved", result["error"])
        self.assertEqual(result["updated"], [])

    def test_rejects_non_reviewed_inputs(self):
        # blocker 방지(spec §4): 입력은 존재하는 reviewed DomainMapping만. candidate/
        # superseded/unknown이 섞이면 ok:False로 거부 — candidate가 빈 reviewed closure를
        # vacuous하게 통과시켜 commit_sha를 갱신하는 사각을 입력 단에서 막는다.
        from project_brain.stale_check import mark_checked
        result = mark_checked(self._shared(),
                              mapping_ids=["m.r1", "m.cand", "m.sup", "m.nope"],
                              checked_head="NEW", current_head="NEW",
                              now="2026-06-14T12:00:00Z")
        self.assertFalse(result["ok"])
        reasons = {x["id"]: x["reason"] for x in result["invalid_inputs"]}
        self.assertEqual(reasons["m.cand"], "status_candidate")
        self.assertEqual(reasons["m.sup"], "status_superseded")
        self.assertEqual(reasons["m.nope"], "unknown_id")
        self.assertEqual(result["updated"], [])  # 거부 시 아무것도 안 건드림

    def test_non_code_locator_id_in_code_locator_ids_skipped(self):
        # future bad data 방어(재리뷰 major): code_locator_ids에 비-CodeLocator id가 섞여도
        # commit_sha를 엉뚱한 kind 객체에 쓰지 않는다. reviewed 매핑이 GlossaryTerm을 잘못 가리킨 상황.
        from project_brain.objbase import base
        from project_brain.stale_check import mark_checked
        not_a_loc = base({
            "id": "g.notaloc", "kind": "GlossaryTerm", "status": "reviewed",
            "truth_role": "domain", "title": "용어", "context_id": "context.x",
            "term": "용어", "definition": "정의", "evidence_refs": ["ev.x"],
        }, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")
        store = _store(
            domain_mapping("m.bad", code_locator_ids=["g.notaloc"]), not_a_loc)
        result = mark_checked(store, mapping_ids=["m.bad"],
                              checked_head="NEW", current_head="NEW",
                              now="2026-06-14T12:00:00Z")
        self.assertTrue(result["ok"])
        self.assertEqual(result["updated"], [])  # 비-CodeLocator는 건너뜀
        self.assertEqual(store.get("g.notaloc")["updated_at"], "2026-06-12T00:00:00Z")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py::MarkCheckedTest -q`
Expected: FAIL — `ImportError: cannot import name 'mark_checked'`

- [ ] **Step 3: 최소 구현**

`src/project_brain/stale_check.py` 모듈 끝에 추가:

```python
def mark_checked(store, *, mapping_ids, checked_head, current_head, now):
    """검토 완료 reviewed 매핑이 어떤 locator의 blocking closure를 전부 덮으면 갱신.

    입력은 존재하는 reviewed DomainMapping만 허용한다(spec §4 'reviewed-only blocking').
    unknown/candidate/superseded/non-mapping이 섞이면 ok:False로 거부한다 — candidate가
    reviewed closure 빈 locator를 vacuous하게 통과시켜 commit_sha를 갱신하는 사각을 입력
    단에서 차단한다. 그래서 후보 locator의 blocking은 항상 입력 매핑을 포함해 비지 않는다.

    반환(체크 순서대로):
      head 이동: {"ok": False, "error": "head moved", "checked_head", "current_head", ...빈}
      거부: {"ok": False, "error": ..., "invalid_inputs": [{id, reason}...], updated/blocked/warnings 빈}
      정상: {"ok": True, "updated": [갱신 locator 객체...],
             "blocked": [{locator_id, missing_mapping_ids}...],
             "warnings": [{locator_id, candidate_mapping_ids}...]}
    저장은 호출자(CLI). line_* 불변. warnings는 candidate만(superseded 제외, spec §4).
    """
    empty = {"updated": [], "blocked": [], "warnings": []}
    if checked_head != current_head:
        return {"ok": False, "error": "head moved",
                "checked_head": checked_head, "current_head": current_head, **empty}

    # 입력 검증: 존재하는 reviewed DomainMapping만(spec §4 — vacuous pass 차단).
    invalid_inputs = []
    for mid in mapping_ids:
        if not store.has(mid):
            invalid_inputs.append({"id": mid, "reason": "unknown_id"})
        elif store.get(mid).get("kind") != "DomainMapping":
            invalid_inputs.append({"id": mid, "reason": "not_domain_mapping"})
        elif store.get(mid).get("status") != "reviewed":
            invalid_inputs.append(
                {"id": mid, "reason": f"status_{store.get(mid).get('status')}"})
    if invalid_inputs:
        return {"ok": False, "error": "mappings must be existing reviewed DomainMapping",
                "invalid_inputs": invalid_inputs, **empty}

    input_set = set(mapping_ids)
    candidate_locator_ids = set()
    for mid in mapping_ids:
        for lid in (store.get(mid).get("code_locator_ids") or []):
            candidate_locator_ids.add(lid)

    updated, blocked, warnings = [], [], []
    for lid in sorted(candidate_locator_ids):
        # 갱신 대상은 실제 CodeLocator만 — schema/lint는 code_locator_ids의 "존재"만 보고
        # "CodeLocator인가"는 강제하지 않으므로(엔진 lint.py), future bad data에서 비-CodeLocator
        # id가 섞여도 commit_sha/verified_at/updated_at를 엉뚱한 객체에 쓰지 않게 막는다.
        if not store.has(lid) or store.get(lid).get("kind") != "CodeLocator":
            continue
        closure = compute_closure(store, lid)
        missing = sorted(m for m in closure["blocking"] if m not in input_set)
        if missing:
            blocked.append({"locator_id": lid, "missing_mapping_ids": missing})
            continue
        # warning은 candidate만 — superseded는 현재 사실이 아니라 제외(spec §4).
        # sorted로 명시(missing_mapping_ids와 일관 — _mappings_referencing 정렬에 암묵 의존하지 않음).
        candidate_only = sorted(
            m for m in closure["nonblocking"]
            if store.get(m).get("status") == "candidate")
        if candidate_only:
            warnings.append({"locator_id": lid, "candidate_mapping_ids": candidate_only})
        loc = dict(store.get(lid))
        loc["commit_sha"] = checked_head
        loc["verified_at"] = now
        loc["updated_at"] = now
        updated.append(loc)
    return {"ok": True, "updated": updated, "blocked": blocked, "warnings": warnings}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py -q`
Expected: PASS (21 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/project_brain/stale_check.py tests/test_stale_check.py
git commit -m "feat(stale-check): mark_checked — locator closure update, blocked, head guard"
```

---

## Task 7: mark-checked CLI 배선 (`_run_mark_checked`)

`cli.py`에 갱신 서브커맨드를 더한다. 현재 origin/develop을 `resolve_target_head`로 확인해 `--checked-head`와 비교(경합 가드)하고, `mark_checked`가 돌려준 갱신 locator를 쓰기 전 schema 검증 후 저장한다(promote의 '쓰기 전 검증' 원칙. 단 CodeLocator 3필드만 갱신해 관계가 안 바뀌므로 merged lint는 불필요). `now`는 `datetime.now(timezone.utc).isoformat()`(session.py `mark_processed`와 동일 패턴).

**Files:**
- Modify: `src/project_brain/cli.py`
- Test: `tests/test_stale_check.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_stale_check.py`에 CLI 테스트 클래스 추가:

```python
class CliMarkCheckedTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for obj in (
            code_locator("code.shared", path="a/X.cpp", commit_sha="OLD",
                         line_start=40, line_end=80),
            domain_mapping("m.r1", code_locator_ids=["code.shared"]),
            domain_mapping("m.r2", code_locator_ids=["code.shared"]),
            domain_mapping("m.cand", code_locator_ids=["code.shared"], status="candidate"),
        ):
            BrainStore.save_object(self.root, obj)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, argv, runner):
        out = io.StringIO()
        with mock.patch("project_brain.stale_check.make_git_runner", return_value=runner), \
             mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        return rc, json.loads(out.getvalue())

    def test_full_closure_persists_updated_locator(self):
        runner = fake_git_runner("NEW", {})  # 현재 develop = NEW
        rc, payload = self._run(
            ["mark-checked", "--brain-root", str(self.root),
             "--mappings", "m.r1", "m.r2", "--checked-head", "NEW", "--no-fetch"],
            runner)
        self.assertEqual(rc, 0)
        self.assertEqual(payload["updated"], ["code.shared"])
        # 디스크에 갱신 반영 — commit_sha=NEW, line 불변.
        loc = BrainStore.load(self.root).get("code.shared")
        self.assertEqual(loc["commit_sha"], "NEW")
        self.assertEqual(loc["line_start"], 40)
        self.assertEqual(loc["line_end"], 80)
        # candidate가 같은 locator를 가리키므로 CLI 출력 warnings에 전달된다.
        self.assertEqual(payload["warnings"],
                         [{"locator_id": "code.shared", "candidate_mapping_ids": ["m.cand"]}])

    def test_partial_closure_blocked_rc0_disk_unchanged(self):
        runner = fake_git_runner("NEW", {})
        rc, payload = self._run(
            ["mark-checked", "--brain-root", str(self.root),
             "--mappings", "m.r1", "--checked-head", "NEW", "--no-fetch"],
            runner)
        self.assertEqual(rc, 0)
        self.assertEqual(payload["updated"], [])
        self.assertEqual(payload["blocked"],
                         [{"locator_id": "code.shared", "missing_mapping_ids": ["m.r2"]}])
        # 갱신 안 됐으니 commit_sha 그대로.
        self.assertEqual(BrainStore.load(self.root).get("code.shared")["commit_sha"], "OLD")

    def test_head_moved_returns_rc1_disk_unchanged(self):
        runner = fake_git_runner("NEW", {})  # 현재 develop은 NEW인데
        rc, payload = self._run(
            ["mark-checked", "--brain-root", str(self.root),
             "--mappings", "m.r1", "m.r2", "--checked-head", "STALE", "--no-fetch"],
            runner)
        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("head moved", payload["error"])
        self.assertEqual(BrainStore.load(self.root).get("code.shared")["commit_sha"], "OLD")

    def test_candidate_input_rejected_rc1_disk_unchanged(self):
        # candidate 매핑을 --mappings로 주면 입력 검증에서 거부(rc=1), locator 불변(blocker 방지).
        runner = fake_git_runner("NEW", {})
        rc, payload = self._run(
            ["mark-checked", "--brain-root", str(self.root),
             "--mappings", "m.cand", "--checked-head", "NEW", "--no-fetch"],
            runner)
        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["invalid_inputs"][0]["reason"], "status_candidate")
        self.assertEqual(BrainStore.load(self.root).get("code.shared")["commit_sha"], "OLD")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py::CliMarkCheckedTest -q`
Expected: FAIL — 서브커맨드 분기 없어 `mark-checked`가 query 경로로 빠짐(rc≠0 / KeyError)

- [ ] **Step 3: 최소 구현**

먼저 `src/project_brain/cli.py` 상단 import에 `from datetime import datetime, timezone`을 추가한다(표준 라이브러리는 상단 관례). 그리고 `_run_stale_check`(Task 5에서 추가) 함수 정의 끝과 `def main()` 사이에 새 함수 추가:

```python
def _run_mark_checked(argv) -> int:
    """검토 완료 매핑으로 locator closure를 mark (spec §4). 갱신 locator만 저장."""
    parser = argparse.ArgumentParser(prog="cli mark-checked")
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config)")
    parser.add_argument("--repo-root", help="git 레포 루트 (기본: brain-root의 부모 — brain이 레포 루트 직하라 가정)")
    parser.add_argument("--mappings", required=True, nargs="+",
                        help="'의미 그대로'로 검토 완료한 매핑 id 목록")
    parser.add_argument("--checked-head", required=True,
                        help="검토 기준 develop sha (stale-check가 낸 target_head)")
    parser.add_argument("--no-fetch", action="store_true",
                        help="git fetch 생략(오프라인·테스트). 주의: write 명령이라 "
                             "checked_head 경합 가드가 로컬 origin/develop 기준으로 약해진다")
    args = parser.parse_args(argv)

    from project_brain.stale_check import (
        GitError,
        make_git_runner,
        mark_checked,
        resolve_target_head,
    )

    brain_root = resolve_brain_root(args.brain_root)
    store = BrainStore.load(brain_root)
    repo_root = Path(args.repo_root) if args.repo_root else brain_root.parent
    git_runner = make_git_runner(repo_root)
    try:
        current_head = resolve_target_head(git_runner, fetch=not args.no_fetch)
    except GitError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    # 코퍼스 datetime 표준(...Z, microsecond 없음)에 맞춘다.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = mark_checked(store, mapping_ids=args.mappings,
                          checked_head=args.checked_head, current_head=current_head, now=now)
    if not result["ok"]:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    # 쓰기 전 schema 검증 후에만 save(promote의 '쓰기 전 검증' 원칙). CodeLocator의
    # commit_sha/verified_at/updated_at만 갱신해 관계가 안 바뀌므로 store lint는 불필요
    # (promote는 관계를 바꿔 merged lint까지 하지만 여긴 해당 없음).
    schema_errors = []
    for loc in result["updated"]:
        schema_errors.extend(validate_object(loc))
    if schema_errors:
        print(json.dumps({"ok": False, "error": "; ".join(schema_errors)},
                         ensure_ascii=False, indent=2))
        return 1
    for loc in result["updated"]:
        BrainStore.save_object(brain_root, loc)
    print(json.dumps(
        {"ok": True, "updated": [loc["id"] for loc in result["updated"]],
         "blocked": result["blocked"], "warnings": result["warnings"]},
        ensure_ascii=False, indent=2))
    return 0
```

그리고 `main()`의 `if argv and argv[0] == "stale-check":` 블록 바로 아래에 분기 추가:

```python
        if argv and argv[0] == "mark-checked":
            return _run_mark_checked(argv[1:])
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py -q`
Expected: PASS (25 passed)

- [ ] **Step 5: 전체 회귀 + 커밋**

```bash
.venv/bin/python -m pytest tests/ -q
git add src/project_brain/cli.py tests/test_stale_check.py
git commit -m "feat(stale-check): cli mark-checked subcommand (atomic locator update)"
```
Expected: 전체 green

---

## Task 8: 실코퍼스 스모크 + 회귀 가드 (데이터 레포)

엔진 테스트는 합성뿐이라(CLAUDE.md), 실제 brain 코퍼스에서 명령이 돌고 기존 검색·색인 가드가 안 깨졌는지 확인해야 완료다. **편집 설치라 엔진 코드 변경은 `project-brain` 명령에 즉시 반영된다**(재설치 불필요).

**Files:** 없음 (검증만 — 코드 변경 없음)

- [ ] **Step 1: stale-check 실코퍼스 스모크**

```bash
cd ~/Desktop/bb2_client
project-brain stale-check --brain-root brain | python3 -c "import sys,json; d=json.load(sys.stdin); print('ok', d['ok']); print('target_head', d['target_head']); print('candidates', len(d['candidates'])); print('uncovered', len(d['coverage']['uncovered_mappings'])); print('code_evref_only', sum(1 for u in d['coverage']['uncovered_mappings'] if u['has_code_evidence_ref']))"
```
Expected: `ok True` / `target_head`는 40자 sha / `uncovered`는 **21**, `code_evref_only`는 **2** (spec §6 — uncovered 21개 중 code EvidenceRef만 가진 게 2개). candidates 수는 백필(6-12) 이후 develop 변경량에 따라 가변(0 이상이면 정상 — spec §8 "첫 실행 후보 많을 수 있음").

> **해석 확인 포인트**: `has_code_evidence_ref`는 매핑의 evidence_refs 중 `ref_type=="code_locator"`인 EvidenceRef가 있는지로 판정한다(Task 2). 만약 `code_evref_only`가 2가 아니면 그 2개 매핑의 실제 EvidenceRef `ref_type`을 `brain/objects/mappings/`에서 확인해 판정 기준을 맞춘다(spec §6의 "code EvidenceRef"가 다른 ref_type일 가능성).

만약 `git fetch` 네트워크 실패 시: `--no-fetch`를 붙여 로컬 `origin/develop` ref로 스모크(결과는 마지막 fetch 시점 기준).

- [ ] **Step 2: mark-checked dry 동작 확인 (head 가드)**

`--checked-head`에 일부러 틀린 sha를 줘 head 가드가 rc=1로 막는지 확인(brain 데이터 불변 검증):

```bash
cd ~/Desktop/bb2_client
project-brain mark-checked --brain-root brain --mappings mapping.ad-skip-product.item-definition --checked-head deadbeef --no-fetch; echo "rc=$?"
```
Expected: `{"ok": false, "error": "head moved", ...}` + `rc=1`. (`mapping.ad-skip-product.item-definition`는 실코퍼스에 존재하는 reviewed 매핑 — Task 사전조사에서 확인됨. 다른 id로 바뀌었으면 `project-brain stale-check`의 candidates에서 실제 id 하나를 골라 대체.)

- [ ] **Step 3: 기존 가드 회귀 (stale-check는 검색·색인 안 건드림 → 변화 없어야 함)**

```bash
cd ~/Desktop/bb2_client
pytest brain/checks/ -q
project-brain eval
```
Expected: `brain/checks/` 전부 pass, `project-brain eval`은 골든셋 그대로(현재 8/8 — task 파일 "이어서 25" 기준). stale-check/mark-checked는 색인·검색 경로를 안 건드리므로 회귀가 있으면 안 된다.

- [ ] **Step 4: 엔진 레포 push**

```bash
cd ~/Downloads/codes/project-brain
.venv/bin/python -m pytest tests/ -q   # 최종 전체 green 확인
git log --oneline -6                    # Task 1~7 커밋 확인
git push
```
Expected: 전체 green, 7개 feat 커밋(Task 1~7 각 1개), push 성공(`mooh1222/project-brain` main).

---

## Self-Review (작성자 점검 — 2026-06-14)

**1. Spec coverage** — spec 각 절을 task에 대응:
- §3 stale-check 동작(변경 감지·매핑 후보·locator_group·coverage·target_head) → Task 1·2·3·4·5 ✅
- §4 mark-checked closure mark(입력 reviewed DomainMapping 검증·거부·reviewed-only blocking·superseded 제외·candidate warning·전체 충족 시만 갱신·blocked·checked_head 가드·commit_sha+verified_at+updated_at·line 불변) → Task 6·7 ✅
- §5 경계(line 안 건드림 → Task 6 `line_*` 불변 테스트 / EvidenceRef 제외 → CodeLocator만 순회 Task 4 / 자동 supersede 안 함 → mark는 사람이 준 `--mappings`만 / 트리거 코어 밖 → 명령만 추가) ✅
- §6 데이터 사실(reviewed blocking·21 uncovered·57 공유) → Task 1·2 로직 + Task 8 스모크 expected에 21 박음 ✅
- §7 테스트(변경 감지·closure 갱신·checked_head 가드·coverage·git 주입) → Task 1~7 TDD 전부 ✅
- §8 미결(commit_sha 없는 locator → Task 4 skip 테스트 / git fetch 실패 → Task 5 GitError rc=1 + Task 8 `--no-fetch` fallback / 출력 정렬 → locator_group·candidates id 정렬 / CLI 위치 → cli.py 서브커맨드) ✅

**2. Placeholder scan** — "TODO/적절히/등"류 없음. 모든 step에 실제 코드·실제 명령·기대 출력. ✅

**3. Type consistency** — 함수명·반환 키를 task 간 대조:
- `compute_closure` → `{"blocking", "nonblocking"}` (Task 1 정의, Task 4·6 사용) ✅
- `coverage_report` → `{"covered_mappings": [id...], "uncovered_mappings": [{mapping_id, skipped_reason, has_code_evidence_ref}...]}` (Task 2 정의, Task 4·5·8 사용 — uncovered는 id 배열이 아니라 dict 목록) ✅
- `stale_check` → `{"target_head", "candidates", "locator_group", "coverage"}` (Task 4 정의, Task 5 CLI가 `{"ok": True, **report}`로 펼침) ✅
- `mark_checked` → 정상 `{"ok": True, "updated", "blocked", "warnings"}` / 거부 `{"ok": False, "error", "invalid_inputs", updated·blocked·warnings 빈}` / head 이동 `{"ok": False, "error": "head moved", ...}` (Task 6 정의, Task 7 CLI는 `ok==False`면 그대로 rc=1, `result["updated"]`는 객체 리스트라 출력은 id로 변환) ✅
- `make_git_runner`/`resolve_target_head`/`path_changed`/`GitError` (Task 3 정의, Task 4·5·7 사용) ✅
- 가짜 runner `fake_git_runner(target_head, changed)` (Task 3 헬퍼, Task 4·5·7 재사용) ✅
- `git_runner(args: list[str]) -> str` 계약 일관: `["fetch","origin","develop"]` / `["rev-parse","origin/develop"]` / `["diff","--name-status","FROM..TARGET","--","PATH"]` (Task 3 구현 ↔ fake 파싱 ↔ Task 4 호출) ✅

이상 없음.

---

## codex(gpt-5.5) 계획 리뷰 반영 기록 (2026-06-14)

계획 작성 후 엔진 레포 4개 파일(`cli.py`·`store.py`·`schema.py`·`objbase.py`)과 spec을 직접 대조한 codex 적대 리뷰를 받아 반영:

| 심각도 | 지적 | 반영 |
|---|---|---|
| blocker | `mark_checked`가 입력 검증 없어 candidate-only 매핑이 reviewed closure 빈 locator를 vacuous pass로 갱신 | Task 6 — 입력을 존재하는 reviewed DomainMapping만 허용, 아니면 `ok:False` 거부(`invalid_inputs`). 입력이 reviewed 매핑이면 후보 locator의 blocking이 항상 그 매핑을 포함해 빌 수 없으므로 "blocking 빈 갱신 금지" 별도 가드는 도달 불가 죽은 코드라 넣지 않음(karpathy) |
| major | `warnings`에 candidate만 아니라 superseded도 포함됨 | Task 6 — `warnings`는 nonblocking 중 `status=="candidate"`만 필터 |
| major | coverage 출력이 spec보다 좁음(`skipped_reason`·code EvidenceRef-only subset 누락) | Task 2 — `uncovered_mappings`를 `{mapping_id, skipped_reason, has_code_evidence_ref}`로 확장 + Task 8 스모크에 `code_evref_only` 검증 |
| minor | mark-checked `--no-fetch`가 head 가드 약화 | Task 7 — help에 "write 명령이라 가드 약화" 명시 |
| minor | `target_head` 명시 테스트가 rev-parse 금지 미확인 | Task 4 — rev-parse 미호출 assert 추가 |
| minor | "promote 패턴" 표현 부정확(promote는 merged lint까지) | Task 7 — 주석을 "쓰기 전 schema 검증, 관계 안 바뀌어 lint 불필요"로 |

API 대조는 통과: `BrainStore.load/get/has/by_kind/save_object`, `validate_object`(list 반환), `objbase.base()`, `cli.main()` 분기 모두 호환 확인. YAGNI 판단(AST/symbol diff·line 갱신·자동 supersede·hook 제외)도 유지 승인.

**2차 재리뷰(반영본, 2026-06-14)**: 새 blocker 없음. blocker "죽은 코드" 논증 타당 확인, `has_code_evidence_ref == ref_type=="code_locator"` 해석이 schema·실코퍼스 모두에 맞음 확인(sally-canoe·line-game-lounge 매핑 실측). 추가 반영 2건:

| 심각도 | 지적 | 반영 |
|---|---|---|
| major | `mark_checked` 갱신 대상 `lid`의 `kind=="CodeLocator"` 미확인 — schema/lint가 `code_locator_ids`의 타입을 강제 안 해, future bad data에서 비-CodeLocator id에 `commit_sha`를 쓸 위험 | Task 6 — 갱신 루프에 `kind=="CodeLocator"` 가드 + 테스트(`test_non_code_locator_id_in_code_locator_ids_skipped`). 빈 blocking 가드와 달리 이건 엔진이 보장 안 하는 외부 데이터 가정이라 방어 정당 |
| minor | Task 7 **도입 문장**만 "promote와 같은 원자성 패턴" 잔존(주석·기록은 정정됨) | Task 7 — 문장 정정 |

---

## 최종 통합 리뷰 반영 (2026-06-15, 구현 완료 후)

8개 Task 구현 완료(엔진 커밋 `d37766a`~`de314d4`, 7개) 후 전체를 opus로 통합 리뷰 — **Critical 0, "merge-quality, 문서/테스트 보강 권장"**. 각 Task는 spec→quality 2단계 개별 리뷰를 이미 통과했고, 통합 관점에서 단일 `compute_closure` 두 경로(읽기·쓰기) 일관·3겹 방어 load-bearing(kind 가드가 lint/schema 미검사를 메움)·CLI 원자성(`_run_promote` 패턴)·읽기 전용 디스크 검증·dead code 0 확인. 보강 4건을 별도 커밋 `aa4f0de`(엔진)로 반영:

| 항목 | 반영 |
|---|---|
| I-1 mark-checked staleness 미재확인(의도)의 명시성 | `mark_checked` docstring + spec §5에 "closure 충족이 유일 조건, 안 바뀐 locator도 갱신되나 checked_head는 ancestor라 무해" 명시 |
| I-3 mark-checked `--no-fetch`가 head 가드 약화 | `_run_mark_checked`에 `--no-fetch` 시 stderr 런타임 경고 |
| Minor 7 통합 테스트 | `CliMarkCheckedTest`에 한 호출 update+block 혼재 테스트 |
| missing #2 통합 테스트 | `StaleCheckTest`에 한 매핑이 여러 stale locator 가리키는 테스트 |
| I-2 head 가드 stateless 한계 | spec §4에 A→B→A revert 한계 명시(수용 — 현실 위험 낮음) |

엔진 테스트 25→27, 전체 378 passed. **실코퍼스 검증**(데이터 레포): stale-check 스모크(uncovered 21·code_evref_only 2 — spec §6 일치) + mark-checked head 가드 dry run(rc1, brain/ 변경 0) + 기존 가드 회귀(`brain/checks` 5 passed·골든셋 `eval` ok True) 전부 통과. `git fetch`는 이 세션 환경에서 실패해 `--no-fetch` fallback이 GitError로 깔끔히 작동(기능 정상, 환경 문제).

---

## 못 잡는 것 (구현 후에도 — spec §8, 사용자 인지용)

- **백필(`edde40210c`, 6-12) 이전에 이미 낡은 매핑**은 못 잡는다 — 이 기능은 각 locator의 commit_sha **이후** 변경만 본다. 백필은 줄 재검증이지 "의미 재검토"가 아니므로, 백필 이전 의미 어긋남은 별도 초기 감사가 필요(이 P0 범위 밖).
- **`code_locator_ids` 없는 매핑 21개**(그중 2개는 code EvidenceRef만)는 coverage 리포트로 "안 보고 있다"를 가시화만 한다(자동 처리 없음).
- **부분 검토 상태는 저장 안 함** — closure 미충족 locator는 다음 stale-check에 다시 뜬다(정상). 매핑별 검토 플래그를 새 스키마로 만들지 않은 의도적 선택(spec §4).
</content>
</invoke>
