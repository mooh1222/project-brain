# Branch-Aware Brain Ingest Audit Hardening Implementation Plan

> **완료 기록 — 2026-07-23:** Task 1~9 구현과 설계·품질 검토를 완료했다. 아래
> 체크박스와 RED/GREEN 명령은 당시 실행 계획을 보존하는 이력이며, 다음 세션이 다시
> 실행할 작업 목록이 아니다.
>
> Project Brain 작업은 `feat/brain-ingest-branch-audit-hardening`에서 `6bed114`까지
> 구현한 뒤 `main`에 fast-forward merge하고 `origin/main`으로 push했다. 최종 검증은
> pytest 674 + subtests 32, 설치 runtime unittest 75, shell syntax와 `git diff --check`
> 통과다. 기능 worktree와 merge된 로컬 브랜치는 정리했다.
>
> BB2는 `/Users/al03040455/Desktop/bb2_client`의
> `docs/bb2-brain-object-model`에서 엔진 installer로만 갱신했다. 설치 커밋
> `5e3d5c4a6f`, manifest 기록 `8a7d56323a`, 최종 runtime 동기화 `4894337958`을
> `origin/docs/bb2-brain-object-model`로 push했다. 두 번째 install은 변경 없음,
> `agents-doctor`는 통과했다. 기존 `Podfile.lock` 수정은 보존했고, BB2 Brain 객체
> 재생성·재적재·audit·eval은 비용과 승인 범위 때문에 실행하지 않았다.
>
> 전체 결과와 다음 적재로 넘긴 항목은
> [완료 보고서](../../reports/2026-07-23-brain-ingest-branch-audit-hardening-completion.md)를
> 본다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve valid commit SHA anchors across ordinary merges, expose unmerged branch scope independently from evidence review status, make audit/finalization fail closed, and safely refresh the BB2 skills through the engine installer without regenerating the existing in-game ingestion.

**Architecture:** Project Brain remains the source of truth for templates and runtime behavior. Git reachability, exact code-quote verification, and index durability are strengthened in the engine first; the updated skills are then installed into BB2 without `--force`. `reviewed` continues to mean that the evidence and interpretation were verified, while branch reachability is reported as a separate advisory axis.

**Tech Stack:** Python 3.9+, SQLite/FTS5, Git CLI, pytest, unittest, POSIX `fcntl`, Markdown skill templates.

---

## Agreed Design and Scope

This plan records the three-party agreement between the implementing agent, the architect subagent, and the critic subagent.

- `reviewed` is retained for the current 101 in-game expansion objects. It describes evidence quality, not whether a commit has reached the default branch.
- `candidate` remains reserved for uncertain evidence or uncertain interpretation. An unmerged but verified prototype is not downgraded to `candidate`.
- An ordinary fast-forward or merge commit does not replace the original commit SHA. If the original commit remains an ancestor of the configured default branch, the locator keeps its SHA.
- Squash, rebase, and cherry-pick may make the original SHA unreachable. Only those cases, or a conflict resolution that materially changes the anchored code, can require re-anchoring after code inspection.
- Unmerged reachability is a non-error advisory. Git execution failure or an unverifiable anchor is an audit failure.
- Exact quote verification is opt-in through `CodeLocator.verified_quote` and uses an exact byte substring of `git show <sha>:<path>`. Whitespace normalization is prohibited.
- Ingest finalization compares unmerged locators using a baseline-union contract:

  ```text
  post_target_head == baseline_target_head
  post_unmerged == baseline_unmerged ∪ expected_unmerged_locator_ids
  ```

- Index rebuild uses a sibling advisory lock, a same-directory temporary database, integrity/count checks, `fsync`, and atomic `os.replace`.
- Engine changes land first. BB2 receives the generated skills through `project-brain install`; copied skill files are not edited as their source of truth.

### Explicit non-goals

- Do not rewrite a SHA merely because a branch was merged.
- Do not globally replace BB2 ACL values. Only the two current in-game expansion manifests receive the explicit `bb2-team` ACL.
- Do not regenerate, rebuild, re-ingest, audit, or eval the existing 101 in-game expansion objects in this workstream. Their targeted data correction is deferred until the next authorized ingestion.
- Do not change the global `session-snapshot` skill's local-command filtering in this workstream. It needs a separate plan.
- Do not add a `datetime.UTC` compatibility task. BB2 HEAD `3c86db389e` already removed that failure path and the stale runtime command works with system Python 3.9.
- Do not reset, amend, or revert BB2 commit `3c86db389e`.
- Do not push either repository unless the user separately authorizes a push during execution.

## Relevant File Map

### Project Brain engine

- `src/project_brain/config.py`
- `src/project_brain/stale_check.py`
- `src/project_brain/code_verify.py` (new)
- `src/project_brain/cli.py`
- `src/project_brain/router.py`
- `src/project_brain/assembly.py`
- `src/project_brain/search_index.py`
- `src/project_brain/templates/audit/SKILL.md`
- `src/project_brain/templates/ingest/scripts/assemble_notes.py`
- `src/project_brain/templates/ingest/scripts/finalize_ingest.py`
- `src/project_brain/templates/ingest/references/completeness-checklist.md`
- `src/project_brain/templates/ingest/references/ingest-tools.md`
- `src/project_brain/templates/session-ingest/references/dev-ingest.md`
- `src/project_brain/templates/ingest/scripts/domain_spec.template.py`
- `src/project_brain/templates/CHANGELOG.md`
- `README.md`
- `ROADMAP.md`

### Project Brain tests

- `tests/test_config.py`
- `tests/test_stale_check.py`
- `tests/test_code_verify.py` (new)
- `tests/test_cli.py`
- `tests/test_router.py`
- `tests/test_assembly.py`
- `tests/test_search_index.py`
- `tests/test_ingest_skill_contract.py`
- `tests/test_installer.py`
- `src/project_brain/templates/ingest/scripts/test_assemble_notes.py`
- `src/project_brain/templates/ingest/scripts/test_finalize_ingest.py`
- `src/project_brain/templates/ingest/scripts/test_batch_tools.py`

### BB2 generated skills

- `/Users/al03040455/Desktop/bb2_client/.agents/skills/bb2-brain-ingest/`
- `/Users/al03040455/Desktop/bb2_client/.agents/skills/bb2-brain-session-ingest/`
- `/Users/al03040455/Desktop/bb2_client/.agents/skills/bb2-brain-audit/`

## Task 1: Make the configured default branch authoritative

**Files:**

- Modify: `src/project_brain/config.py`
- Modify: `src/project_brain/stale_check.py`
- Modify: `src/project_brain/cli.py`
- Test: `tests/test_config.py`
- Test: `tests/test_stale_check.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing configuration tests**

  Add tests proving `.project-brain.json` values survive loading and the legacy fallback remains `develop`:

  ```python
  def test_load_config_preserves_default_branch_and_repo(tmp_path):
      (tmp_path / ".project-brain.json").write_text(
          '{"project":"demo","brain_root":"brain",'
          '"default_branch":"main","repo":"demo_repo"}',
          encoding="utf-8",
      )

      config = load_config(tmp_path)

      assert config["default_branch"] == "main"
      assert config["repo"] == "demo_repo"


  def test_resolve_default_branch_falls_back_to_develop_without_config(tmp_path):
      assert resolve_default_branch(start=tmp_path) == "develop"
  ```

- [ ] **Step 2: Write failing Git command tests**

  In `tests/test_stale_check.py`, assert that `resolve_target_head(..., default_branch="main")` calls `fetch origin main` and resolves `origin/main`, never `develop`. Add the equivalent `trunk` case.

- [ ] **Step 3: Run the focused tests and confirm the red state**

  Run:

  ```bash
  .venv/bin/python -m pytest -q \
    tests/test_config.py \
    tests/test_stale_check.py \
    tests/test_cli.py
  ```

  Expected: failures show that `default_branch` and `repo` are discarded and target resolution still hardcodes `develop`.

- [ ] **Step 4: Implement configuration propagation**

  Keep old installations compatible while making explicit values authoritative:

  ```python
  def resolve_default_branch(
      explicit: str | None = None,
      *,
      start: Path | None = None,
  ) -> str:
      if explicit:
          return explicit
      config = load_config(start)
      value = str(config.get("default_branch") or "").strip()
      return value or "develop"
  ```

  Include `default_branch` and `repo` in `load_config()`'s returned dictionary. Change `resolve_target_head()` to accept `default_branch`:

  ```python
  def resolve_target_head(
      git_runner: GitRunner,
      *,
      default_branch: str,
      fetch: bool = True,
  ) -> str:
      if fetch:
          git_runner("fetch", "origin", default_branch)
      return git_runner("rev-parse", f"origin/{default_branch}").strip()
  ```

  Resolve the branch once in each CLI command and pass it into audit, stale-check, and mark-checked. Preserve existing CLI output fields.

- [ ] **Step 5: Add real temporary Git DAG coverage**

  Build a bare `origin` plus a working clone in a pytest fixture. Prove:

  - fast-forward and normal merge make the original SHA an ancestor;
  - squash, rebase, and cherry-pick copies do not make the original SHA an ancestor;
  - a normal merge with conflict resolution can leave the SHA reachable while changing the anchored path;
  - repositories using `main` or `trunk` work without an `origin/develop` ref.

- [ ] **Step 6: Run the focused tests**

  Run the same command from Step 3.

  Expected: all selected tests pass.

- [ ] **Step 7: Commit the default-branch change**

  ```bash
  git add \
    src/project_brain/config.py \
    src/project_brain/stale_check.py \
    src/project_brain/cli.py \
    tests/test_config.py \
    tests/test_stale_check.py \
    tests/test_cli.py
  git commit -m "fix(audit): honor configured default branch"
  ```

## Task 2: Represent unmerged scope as a separate advisory axis

**Files:**

- Modify: `src/project_brain/stale_check.py`
- Modify: `src/project_brain/router.py`
- Modify: `src/project_brain/cli.py`
- Test: `tests/test_stale_check.py`
- Test: `tests/test_router.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing advisory tests**

  Cover all combinations:

  - unchanged and merged: neither advisory;
  - changed and merged: `code_changed=true`;
  - unchanged and unmerged: `unmerged_anchor=true`;
  - changed and unmerged: both axes remain true;
  - one mapping aggregates multiple locator IDs, SHAs, paths, and reasons;
  - old cache files without the new fields still load.

  Use the following stable public shape:

  ```json
  {
    "code_changed": false,
    "unmerged_anchor": true,
    "unmerged_reasons": ["not_ancestor"],
    "locator_ids": ["code.example"],
    "from_commits": ["c97c0422d7"],
    "paths": ["LineBubble2/example.cpp"],
    "target_head": "abc123",
    "computed_at": "2026-07-23T18:02:33+09:00"
  }
  ```

- [ ] **Step 2: Run the focused tests and confirm the red state**

  ```bash
  .venv/bin/python -m pytest -q \
    tests/test_stale_check.py \
    tests/test_router.py \
    tests/test_cli.py
  ```

  Expected: unmerged locators are absent from mapping advisories and query/show cannot distinguish them from code changes.

- [ ] **Step 3: Preserve unmerged entries when building the stale cache**

  Add mapping IDs to each unmerged locator result, then aggregate two independent booleans:

  ```python
  advisory = {
      "code_changed": bool(changed_locator_ids),
      "unmerged_anchor": bool(unmerged_locator_ids),
      "unmerged_reasons": sorted(unmerged_reasons),
      "locator_ids": sorted(changed_locator_ids | unmerged_locator_ids),
      "from_commits": sorted(from_commits),
      "paths": sorted(paths),
      "target_head": target_head,
      "computed_at": computed_at,
  }
  ```

  Keep `stale_mapping_ids` limited to code-changed mappings so existing callers do not reinterpret every unmerged prototype as stale.

- [ ] **Step 4: Surface distinct router and CLI messages**

  Keep the existing code-change warning. Add a separate branch-scope message such as:

  ```text
  Code anchor is not reachable from the configured default branch; check whether it is unmerged or history was rewritten.
  ```

  Query and show must attach both fields without changing the stored object's `status`.

- [ ] **Step 5: Run the focused tests**

  Run the command from Step 2.

  Expected: all selected tests pass, including backward-compatible cache fixtures.

- [ ] **Step 6: Commit the advisory change**

  ```bash
  git add \
    src/project_brain/stale_check.py \
    src/project_brain/router.py \
    src/project_brain/cli.py \
    tests/test_stale_check.py \
    tests/test_router.py \
    tests/test_cli.py
  git commit -m "feat(audit): expose unmerged code anchors"
  ```

## Task 3: Make status, provenance, and verified quotes explicit in assembly

**Files:**

- Modify: `src/project_brain/assembly.py`
- Modify: `src/project_brain/templates/ingest/scripts/domain_spec.template.py`
- Modify: `src/project_brain/templates/ingest/scripts/assemble_notes.py`
- Test: `tests/test_assembly.py`
- Test: `src/project_brain/templates/ingest/scripts/test_assemble_notes.py`

- [ ] **Step 1: Write failing assembly tests**

  Add coverage for:

  - `context.claim_status` defaults to `reviewed`;
  - glossary terms, mappings, and decisions accept per-item status overrides;
  - `candidate` glossary terms require candidate metadata;
  - supporting evidence objects remain `reviewed`;
  - source `acl` and `captured_at` are required and nonempty;
  - code anchors require `quote` and `verified_at`;
  - generated `CodeLocator` objects store `verified_quote`.

- [ ] **Step 2: Run the focused tests and confirm the red state**

  ```bash
  .venv/bin/python -m pytest -q \
    tests/test_assembly.py \
    src/project_brain/templates/ingest/scripts/test_assemble_notes.py
  ```

  Expected: tests fail on hardcoded `reviewed`, `demo-team`, current-time provenance, and missing `verified_quote`.

- [ ] **Step 3: Add explicit domain-spec inputs**

  Add these fields to `scripts/domain_spec.template.py`:

  ```python
  CLAIM_STATUS = "reviewed"
  SOURCE_ACL: list[str] = []
  CAPTURED_AT = ""
  VERIFIED_AT = ""
  EXPECT_UNMERGED_ANCHORS = False
  ```

  Document the required candidate metadata beside `CLAIM_STATUS`. Empty ACL or timestamps must cause an actionable assembly error rather than silently falling back to demo values or wall-clock time.

- [ ] **Step 4: Thread the values through assembly**

  Pass `CLAIM_STATUS`, `SOURCE_ACL`, `CAPTURED_AT`, and `VERIFIED_AT` from `assemble_notes.py` into the assembly functions. Use per-item `status` only when present:

  ```python
  status = item.get("status", context["claim_status"])
  locator = {
      **locator_base,
      "status": "reviewed",
      "verified_quote": anchor["quote"],
      "verified_at": anchor["verified_at"],
  }
  ```

  Do not normalize line endings or indentation in `verified_quote`.

- [ ] **Step 5: Run the focused tests**

  Run the command from Step 2.

  Expected: all selected tests pass.

- [ ] **Step 6: Commit the assembly contract**

  ```bash
  git add \
    src/project_brain/assembly.py \
    src/project_brain/templates/ingest/scripts/domain_spec.template.py \
    src/project_brain/templates/ingest/scripts/assemble_notes.py \
    tests/test_assembly.py \
    src/project_brain/templates/ingest/scripts/test_assemble_notes.py
  git commit -m "feat(ingest): require explicit evidence provenance"
  ```

## Task 4: Add byte-exact code verification and fail-closed audit

**Files:**

- Create: `src/project_brain/code_verify.py`
- Create: `tests/test_code_verify.py`
- Modify: `src/project_brain/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing byte-exact verification tests**

  Cover:

  - a tab-and-newline quote found in a raw blob passes;
  - the same text with collapsed whitespace fails;
  - locators without `verified_quote` are skipped;
  - empty quote, invalid commit, missing path, and Git failure become explicit failures;
  - verification checks the blob at the locator SHA, not the working tree.

  Keep blob access injectable:

  ```python
  def test_verify_quote_is_byte_exact():
      blob = b"\tfirst();\n\tsecond();\n"
      result = verify_code_quotes(
          [locator(verified_quote="\tfirst();\n\tsecond();")],
          blob_reader=lambda commit, path: blob,
      )
      assert result == {"ok": True, "checked": 1, "failures": []}
  ```

- [ ] **Step 2: Write failing CLI audit tests**

  Assert:

  - lint success plus stale-check success plus quote-check success returns `ok=true`, exit 0;
  - any global `GitError` returns `ok=false`, exit 1;
  - any `anchor_unverifiable` returns `ok=false`, exit 1;
  - `not_ancestor` remains an advisory and does not fail audit;
  - `--no-stale` is the only explicit Gitless skip.

- [ ] **Step 3: Run the focused tests and confirm the red state**

  ```bash
  .venv/bin/python -m pytest -q \
    tests/test_code_verify.py \
    tests/test_cli.py
  ```

  Expected: the verifier module is missing and audit still reports success after Git failure.

- [ ] **Step 4: Implement raw-blob verification**

  Implement `git show <sha>:<path>` as a binary read and use direct containment:

  ```python
  quote_bytes = verified_quote.encode("utf-8")
  if not quote_bytes:
      failures.append(failure(locator, "empty_verified_quote"))
  elif quote_bytes not in blob_bytes:
      failures.append(failure(locator, "quote_not_found"))
  ```

  Return only the contract needed by the audit:

  ```python
  {
      "ok": not failures,
      "checked": checked,
      "failures": failures,
  }
  ```

  Do not claim symbol-boundary verification; this feature proves exact source bytes only.

- [ ] **Step 5: Make top-level audit truth-functional**

  Compute:

  ```python
  audit_ok = (
      lint_result["ok"]
      and stale_result["ok"]
      and code_quotes_result["ok"]
  )
  ```

  A caught Git exception must populate a structured failure and set `stale_result["ok"] = False`. Keep `not_ancestor` in the successful stale result's advisory list.

- [ ] **Step 6: Run the focused tests**

  Run the command from Step 3.

  Expected: all selected tests pass.

- [ ] **Step 7: Commit the verifier and audit change**

  ```bash
  git add \
    src/project_brain/code_verify.py \
    src/project_brain/cli.py \
    tests/test_code_verify.py \
    tests/test_cli.py
  git commit -m "fix(audit): fail closed on unverifiable code anchors"
  ```

## Task 5: Enforce the unmerged baseline-union finalization contract

**Files:**

- Modify: `src/project_brain/templates/ingest/scripts/finalize_ingest.py`
- Modify: `src/project_brain/templates/ingest/scripts/assemble_notes.py`
- Modify: `src/project_brain/templates/ingest/scripts/test_finalize_ingest.py`
- Modify: `src/project_brain/templates/ingest/scripts/test_assemble_notes.py`
- Modify: `src/project_brain/templates/ingest/scripts/test_batch_tools.py`

- [ ] **Step 1: Write failing finalizer tests**

  Add fixture cases for:

  - seven baseline unmerged locators plus thirty expected locators passes;
  - an unexpected thirty-first locator fails;
  - disappearance of a baseline locator fails;
  - target HEAD changing between baseline and finalization fails;
  - a legacy list-only baseline passes only when the expected-unmerged set is empty;
  - audit failure blocks finalization even when lint and graph checks pass.

- [ ] **Step 2: Run the installed-runtime tests and confirm the red state**

  ```bash
  .venv/bin/python -m unittest discover \
    -s src/project_brain/templates/ingest/scripts \
    -p 'test_*.py'
  ```

  Expected: the current finalizer has no target-head/unmerged envelope and does not execute audit.

- [ ] **Step 3: Extend the baseline and finalization contracts**

  Store:

  ```json
  {
    "target_head": "abc123",
    "unmerged_locator_ids": ["code.preexisting"],
    "graph_ids": ["mapping.example"]
  }
  ```

  Add `expected_unmerged_locator_ids` to the finalization contract. When `EXPECT_UNMERGED_ANCHORS` is true, `assemble_notes.py` derives that list from the generated code anchors rather than duplicating IDs by hand.

- [ ] **Step 4: Implement exact set validation**

  ```python
  expected_post = baseline_unmerged | expected_unmerged
  unmerged_ok = (
      post_target_head == baseline_target_head
      and post_unmerged == expected_post
  )
  ```

  Report `baseline`, `expected`, `current`, `new`, `resolved`, and both target heads in the finalization JSON. Failure messages must name the exact added, missing, or changed values.

- [ ] **Step 5: Add audit without replacing cheap gates**

  Preserve existing index, lint, eval, graph, and corpus commands. Add:

  ```json
  {
    "audit": ["project-brain", "audit", "--no-fetch"]
  }
  ```

  Finalization requires audit `ok=true`. Do not remove the existing cheap lint/graph gates because existing reports and failure localization rely on them.

- [ ] **Step 6: Run the installed-runtime tests**

  Run the command from Step 2.

  Expected: every installed-runtime test passes.

- [ ] **Step 7: Commit the finalization contract**

  ```bash
  git add \
    src/project_brain/templates/ingest/scripts/finalize_ingest.py \
    src/project_brain/templates/ingest/scripts/assemble_notes.py \
    src/project_brain/templates/ingest/scripts/test_finalize_ingest.py \
    src/project_brain/templates/ingest/scripts/test_assemble_notes.py \
    src/project_brain/templates/ingest/scripts/test_batch_tools.py
  git commit -m "feat(ingest): verify unmerged anchor isolation"
  ```

## Task 6: Make index rebuild atomic and concurrency-safe

**Files:**

- Modify: `src/project_brain/search_index.py`
- Modify: `src/project_brain/cli.py`
- Modify: `tests/test_search_index.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing index safety tests**

  Prove:

  - a build failure leaves the old database byte-for-byte unchanged;
  - a validation failure leaves the old database unchanged;
  - a successful rebuild atomically replaces it;
  - temporary databases are removed after success and failure;
  - a concurrent nonblocking lock raises `IndexRebuildInProgressError`;
  - the CLI maps that exception to JSON `ok=false` and exit 1.

- [ ] **Step 2: Run the focused tests and confirm the red state**

  ```bash
  .venv/bin/python -m pytest -q \
    tests/test_search_index.py \
    tests/test_cli.py
  ```

  Expected: the current rebuild unlinks the real database before the new index is proven valid.

- [ ] **Step 3: Implement lock, temporary build, and atomic replacement**

  Use a sibling lock path and same-directory temporary path:

  ```python
  with lock_path.open("a+b") as lock_file:
      try:
          fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
      except BlockingIOError as exc:
          raise IndexRebuildInProgressError(str(db_path)) from exc

      temp_path = db_path.with_name(f".{db_path.name}.{os.getpid()}.tmp")
      build_index(temp_path)
      validate_index(temp_path)
      fsync_file(temp_path)
      os.replace(temp_path, db_path)
      fsync_directory(db_path.parent)
  ```

  `validate_index()` must run SQLite quick/integrity checks and compare document, FTS, and metadata counts before replacement. Cleanup only the explicit temporary path in `finally`; never unlink the existing database on failure.

- [ ] **Step 4: Run the focused tests**

  Run the command from Step 2.

  Expected: all selected tests pass.

- [ ] **Step 5: Commit the index durability change**

  ```bash
  git add \
    src/project_brain/search_index.py \
    src/project_brain/cli.py \
    tests/test_search_index.py \
    tests/test_cli.py
  git commit -m "fix(index): rebuild atomically under lock"
  ```

## Task 7: Update engine templates, documentation, and installer contracts

**Files:**

- Modify: `src/project_brain/templates/audit/SKILL.md`
- Modify: `src/project_brain/templates/ingest/references/completeness-checklist.md`
- Modify: `src/project_brain/templates/ingest/references/ingest-tools.md`
- Modify: `src/project_brain/templates/session-ingest/references/dev-ingest.md`
- Modify: `src/project_brain/templates/CHANGELOG.md`
- Modify: `README.md`
- Modify: `ROADMAP.md`
- Modify: `tests/test_ingest_skill_contract.py`
- Modify: `tests/test_installer.py`

- [ ] **Step 1: Write failing skill-contract and installer tests**

  Require generated docs to say:

  - ordinary merge reachability preserves the original SHA;
  - squash/rebase/cherry-pick may require inspected re-anchoring;
  - `reviewed` and unmerged reachability are independent;
  - audit uses the actual `stale` fields plus `code_quotes`, not the nonexistent `stale.detail`;
  - finalization uses the baseline-union contract;
  - install remains idempotent.

- [ ] **Step 2: Run the focused tests and confirm the red state**

  ```bash
  .venv/bin/python -m pytest -q \
    tests/test_ingest_skill_contract.py \
    tests/test_installer.py
  ```

  Expected: documentation still contains the obsolete post-merge SHA rewrite guidance and the wrong audit field.

- [ ] **Step 3: Update the canonical engine templates**

  Use one consistent rule in audit, ingest, and session-ingest documentation:

  ```text
  After integration, rerun audit against the configured default branch.
  Keep an original SHA that is still reachable and still identifies the intended
  code. Re-anchor only when reachability was rewritten or the code itself changed.
  ```

  Document audit failure semantics, exact quotes, the unmerged advisory, finalizer union checks, and atomic index behavior. Record the changes in the template changelog and public README/roadmap.

- [ ] **Step 4: Run the focused tests**

  Run the command from Step 2.

  Expected: all selected tests pass.

- [ ] **Step 5: Commit the canonical documentation**

  ```bash
  git add \
    src/project_brain/templates/audit/SKILL.md \
    src/project_brain/templates/ingest/references/completeness-checklist.md \
    src/project_brain/templates/ingest/references/ingest-tools.md \
    src/project_brain/templates/session-ingest/references/dev-ingest.md \
    src/project_brain/templates/CHANGELOG.md \
    README.md \
    ROADMAP.md \
    tests/test_ingest_skill_contract.py \
    tests/test_installer.py
  git commit -m "docs(brain): define merge-safe anchor audits"
  ```

## Task 8: Run the complete engine gate and a disposable install

**Files:**

- Verify only: all Project Brain files changed in Tasks 1-7

- [ ] **Step 1: Run the complete engine test gate**

  ```bash
  uv sync --extra mecab
  .venv/bin/python -m pytest -q
  .venv/bin/python -m unittest discover \
    -s src/project_brain/templates/ingest/scripts \
    -p 'test_*.py'
  bash -n src/project_brain/templates/ingest/scripts/*.sh
  git diff --check
  ```

  Expected: every command exits 0; pytest and unittest report no failures.

- [ ] **Step 2: Perform a first install into a disposable target**

  ```bash
  INSTALL_CHECK_DIR="$(mktemp -d)"
  PYTHONPATH=/Users/al03040455/Downloads/codes/project-brain/src \
  /Users/al03040455/Downloads/codes/project-brain/.venv/bin/python \
    -m project_brain.cli install \
    --target "$INSTALL_CHECK_DIR" \
    --project demo \
    --brain-root brain \
    --default-branch main \
    --repo demo_repo
  ```

  Expected: exit 0, `skipped=[]`, and the report lists only managed files under the disposable target.

- [ ] **Step 3: Prove install idempotence**

  Run the exact command from Step 2 a second time.

  Expected: `created`, `updated`, `removed`, `adopted`, and `skipped` are all empty.

- [ ] **Step 4: Inspect the Project Brain worktree**

  ```bash
  git status --short --branch
  git log --oneline --decorate -8
  ```

  Expected: only the intended engine commits are present; no disposable target or unrelated file is tracked.

## Task 9: Install the engine-generated skills into BB2

**Files:**

- Modify through installer: `/Users/al03040455/Desktop/bb2_client/.agents/skills/`
- Verify: `/Users/al03040455/Desktop/bb2_client/.agents/skills/agents-doctor/`

- [ ] **Step 1: Capture the exact BB2 starting state**

  ```bash
  git -C /Users/al03040455/Desktop/bb2_client status --short --branch
  git -C /Users/al03040455/Desktop/bb2_client rev-parse HEAD
  ```

  Expected: HEAD is at or descends from `3c86db389e`; record all pre-existing changes and do not overwrite them.

- [ ] **Step 2: Run the official install from the Project Brain checkout**

  ```bash
  PYTHONPATH=/Users/al03040455/Downloads/codes/project-brain/src \
  /Users/al03040455/Downloads/codes/project-brain/.venv/bin/python \
    -m project_brain.cli install \
    --target /Users/al03040455/Desktop/bb2_client \
    --project bb2 \
    --brain-root brain \
    --default-branch develop \
    --repo bb2_client
  ```

  Expected: exit 0 and `skipped=[]`. Do not add `--force`.

- [ ] **Step 3: Run the same install a second time**

  Expected: `created`, `updated`, `removed`, `adopted`, and `skipped` are all empty.

- [ ] **Step 4: Validate repository adapters and generated skills**

  ```bash
  cd /Users/al03040455/Desktop/bb2_client
  python3 .agents/skills/agents-doctor/scripts/doctor.py --root "$PWD"
  ```

  Expected: doctor exits 0 and reports no canonical/generated drift.

- [ ] **Step 5: Review and commit only installed managed files**

  Inspect the installer report and stage its exact managed paths. Do not use `git add -A`.

  ```bash
  git diff --check
  git diff --cached --name-only
  git commit -m "chore(skills): install branch-aware Brain audits"
  ```

  Expected: the commit contains generated skill/runtime changes only, not ingestion data and not unrelated BB2 work.

## Deferred BB2 Data Follow-up

The following work is intentionally not executed by this plan:

- regenerating `notes-base.json`, `notes.json`, or `objects.json`;
- rebuilding or re-ingesting the existing 101 in-game expansion objects;
- running full BB2 Brain audit, eval, corpus, recall, or finalization gates;
- updating the 30 locators, 3 evidence references, or 2 manifests identified by the review;
- post-merge validation of those 30 locators.

When the user separately authorizes the next real ingestion, carry forward these requirements:

- keep all 101 existing objects `reviewed`;
- use byte-exact source text for the three known collapsed quotes;
- add `verified_quote` and `verified_at` to the 30 code locators;
- use `acl=["bb2-team"]` and the recorded capture time only for the two relevant manifests;
- preserve the five existing `EventLedgerRecord` extra objects;
- after an ordinary merge, keep the original reachable SHA and check only whether these 30 locators leave the unmerged set;
- after squash/rebase/cherry-pick or a material conflict resolution, inspect affected code before re-anchoring.

## Final Completion Checklist

- [ ] Every Project Brain focused test was observed red before implementation and green afterward.
- [ ] The full Project Brain pytest, installed-runtime unittest, shell syntax, and diff checks pass.
- [ ] Audit fails closed for Git and exact-quote verification errors.
- [ ] `reviewed` objects remain reviewed while unmerged reachability is independently visible.
- [ ] Index rebuild failure and concurrency leave the prior database intact.
- [ ] Disposable installation is idempotent.
- [ ] BB2 installation came from the exact Project Brain checkout command without `--force`.
- [ ] BB2 agents-doctor passes and the second install is a no-op.
- [ ] Existing BB2 Brain objects and local ingestion artifacts are unchanged.
- [ ] Project Brain and BB2 changes are committed separately with explicit staging.
- [ ] Neither repository is pushed without a new explicit user instruction.
