"""Synthetic public consumer probe, run inside the isolated release smoke environment.

No engine checkout import or real corpus. The caller supplies the installed CLI
and Python. Tests inject only the documented regex tokenizer seam and StubEmbedder.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def exercise_release(executable: Path, python: Path, root: Path, env: dict) -> dict:
    root = root.resolve()
    root.mkdir(parents=True)
    env = {key: value for key, value in env.items()
           if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}}
    env = {**env, "PATH": str(executable.parent) + os.pathsep + env["PATH"],
           "PROJECT_BRAIN_PYTHON": str(python), "PROJECT_BRAIN_EMBEDDER": "stub"}
    cases = {}

    def run(name, args, *, code=0, cwd=root, custom_env=None):
        result = subprocess.run(list(map(str, args)), cwd=cwd, env=env if custom_env is None else custom_env,
                                text=True, capture_output=True)
        cases[name] = {"command": list(map(str, args)), "exit": result.returncode,
                       "stdout": result.stdout, "stderr": result.stderr}
        (root / "probe-results.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2))
        if result.returncode != code:
            raise RuntimeError(f"consumer {name}: expected exit {code}, got {result.returncode}: "
                               f"{result.stdout[-4000:]} {result.stderr[-2000:]}")
        return result

    # Test injection lives outside project_brain and does not alter artifact files.
    site = Path(run("site", [python, "-c", "import sysconfig;print(sysconfig.get_path('purelib'))"]).stdout.strip())
    injection = site / "sitecustomize.py"
    if injection.exists():
        raise RuntimeError("isolated smoke sitecustomize already exists")
    injection.write_text("import project_brain.tokenize_ko as tk\n"
                         "tk._BACKEND_NAME = 'regex'\n"
                         "tk._KOREAN_SPLITTER = tk._regex_splitter\n")
    try:
        state = json.loads(run("identity", [executable, "--engine-identity"]).stdout)
        identity = state["engine_identity"]
        package = Path(state["engine_root"])
        run("install", [executable, "install", "--project", "demo", "--repo", "demo",
                        "--default-branch", "main"])
        second = json.loads(run("install-again", [executable, "install", "--project", "demo",
                                                   "--repo", "demo", "--default-branch", "main"]).stdout)
        if any(second[key] for key in ("created", "updated", "removed", "adopted", "skipped")):
            raise RuntimeError("consumer second install changed files")
        brain = root / "brain"
        (brain / "checks").mkdir(parents=True)
        # A meaningful consumer guard: expected exact synthetic corpus kinds/IDs.
        (brain / "checks/test_corpus.py").write_text(
            "import json, pathlib, unittest\nclass Corpus(unittest.TestCase):\n"
            " def test_contexts(self):\n"
            "  docs=[json.loads(p.read_text()) for p in pathlib.Path('brain/objects').rglob('*.json')]\n"
            "  self.assertEqual({d['id'] for d in docs}, {'context.alpha','context.beta'})\n")
        (brain / "eval_scenarios.json").write_text(json.dumps({"scenarios": [
            {"id": key, "query": "synthetic", "expect": {"top5_any": [f"context.{key}"]}}
            for key in ("alpha", "beta")]}))
        run("git-init", ["git", "init", "-q", "-b", "main"])
        run("git-add", ["git", "add", ".project-brain.json"])
        run("git-commit", ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                           "commit", "-qm", "synthetic consumer"])
        run("origin-ref", ["git", "update-ref", "refs/remotes/origin/main", "HEAD"])
        commit = run("head", ["git", "rev-parse", "HEAD"]).stdout.strip()
        finalization = {
            "recall_checks": [{"key": key, "query": "synthetic",
                               "expected_object_ids": [f"context.{key}"], "require_code_locators": False}
                              for key in ("alpha", "beta")],
            "intentional_terminal_ids": ["context.alpha", "context.beta"],
            "expected_unmerged_locator_ids": [],
        }
        for key in ("alpha", "beta"):
            coverage = {
                "version": 1, "mode": "assembled",
                "verify_groups": {"names": [], "empty_reason": "synthetic context only"},
                "context": {"key": key, "mode": "create"},
                "sections": {section: {field: [], "empty_reason": "synthetic context only"}
                             for section, field in dict(sources="ids", glossary="keys", code_anchors="keys",
                                 mappings="keys", decisions="items", refs="items", updates="ids",
                                 extra_objects="objects").items()},
                "expected_objects": [{"id": f"context.{key}", "kind": "DomainContext"}],
            }
            spec = dict(CTX=key, COMMIT=commit, REPO="demo", MANIFESTS={}, DISPLAY_NAME=f"synthetic domain {key}",
                        BOUNDARY_SUMMARY="synthetic context", IN_SCOPE=[key], OUT_OF_SCOPE=["other"],
                        HISTORY_COVERAGE="partial", COVERAGE=coverage)
            source = "\n".join(f"{k} = {v!r}" for k, v in spec.items()) + "\n"
            if key == "beta":
                # Trusted input's hook simulates package drift after parent preflight,
                # before the child CLI/write. Same immutable input resumes after repair.
                source += ("def HOOK(atoms):\n"
                           f" from pathlib import Path\n import project_brain\n"
                           f" if Path({str(root / 'armed')!r}).exists():\n"
                           "  p = Path(project_brain.__file__).parent / 'cli.py'\n"
                           "  p.write_bytes(p.read_bytes() + b'\\n# simulated engine drift\\n')\n"
                           " return atoms\n")
            (root / f"{key}.py").write_text(source)
            (root / f"{key}.json").write_text("[]\n")
        manifest_payload = dict(repo_root=str(root), expected_repo_id="demo", expected_revision_ref="HEAD",
                                engine_sha=identity["source_commit"], engine_identity=identity,
                                items=[dict(key=key, verify_json=f"{key}.json", domain_spec_py=f"{key}.py")
                                       for key in ("alpha", "beta")], finalization=finalization)
        manifest = root / "batch.json"
        manifest.write_text(json.dumps(manifest_payload))
        report = root / "report.json"
        scripts = root / ".agents/skills/demo-brain-ingest/scripts"
        batch = [python, scripts / "run_ingest_batch.py", manifest, "--report", report]

        def inventory():
            return {str(p.relative_to(brain)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in brain.rglob("*") if p.is_file()}

        def reject(name, args, *, custom_env=None):
            before = inventory()
            result = run(name, args, code=1, custom_env=custom_env)
            if inventory() != before:
                raise RuntimeError(f"consumer {name}: rejection changed brain files")
            return result

        bad = root / "bad.json"
        bad.write_text(json.dumps({**manifest_payload, "engine_identity": {
            **identity, "content_sha256": "0" * 64}}))
        reject("wrong-identity", [python, scripts / "run_ingest_batch.py", bad, "--report", root / "bad-report.json"])
        shadow = root / "shadow-bin"
        shadow.mkdir()
        shadow_cli = shadow / "project-brain"
        shadow_state = {**state, "engine_identity": {**identity, "content_sha256": "0" * 64}}
        shadow_cli.write_text(
            f"#!{python}\nimport json,sys,pathlib\n"
            "if sys.argv[1:]==['--engine-identity']:\n"
            f" print(json.dumps({shadow_state!r}))\n"
            "else:\n"
            f" p=pathlib.Path({str(brain / '.brain-local/shadow-write')!r});p.parent.mkdir(parents=True,exist_ok=True);p.touch()\n"
            " sys.exit(1)\n")
        shadow_cli.chmod(0o755)
        reject("wrong-path-cli", batch, custom_env={**env, "PATH": str(shadow) + os.pathsep + env["PATH"]})
        bad.write_text(json.dumps({k: v for k, v in manifest_payload.items() if k != "engine_identity"}))
        reject("legacy-unprovable", [python, scripts / "run_ingest_batch.py", bad, "--report", root / "bad-report.json"])
        runtime = scripts / "run_ingest.sh"
        runtime_bytes = runtime.read_bytes()
        runtime.write_bytes(runtime_bytes + b"\n# stale runtime\n")
        try:
            reject("stale-runtime", batch)
        finally:
            runtime.write_bytes(runtime_bytes)
        # Also prove an uninterrupted new batch, independently of recovery.
        fresh = root / "fresh-consumer"
        fresh.mkdir()
        run("fresh-install", [executable, "install", "--project", "demo", "--repo", "demo",
                              "--default-branch", "main"], cwd=fresh)
        shutil.copytree(brain / "checks", fresh / "brain/checks")
        shutil.copyfile(brain / "eval_scenarios.json", fresh / "brain/eval_scenarios.json")
        for name, args in (
            ("init", ["init", "-q", "-b", "main"]),
            ("add", ["add", ".project-brain.json"]),
            ("commit", ["-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture"]),
            ("origin", ["update-ref", "refs/remotes/origin/main", "HEAD"]),
        ):
            run("fresh-" + name, ["git", *args], cwd=fresh)
        fresh_commit = run("fresh-head", ["git", "rev-parse", "HEAD"], cwd=fresh).stdout.strip()
        for key in ("alpha", "beta"):
            (fresh / f"{key}.py").write_text((root / f"{key}.py").read_text().replace(repr(commit), repr(fresh_commit)))
            shutil.copyfile(root / f"{key}.json", fresh / f"{key}.json")
        (fresh / "batch.json").write_text(json.dumps({**manifest_payload, "repo_root": str(fresh)}))
        fresh_result = json.loads(run("fresh-batch", [python, fresh / scripts.relative_to(root) / "run_ingest_batch.py",
                                                       fresh / "batch.json", "--report", fresh / "report.json"], cwd=fresh).stdout)
        if not fresh_result["finalized"]:
            raise RuntimeError("consumer uninterrupted batch did not finalize")
        code_file = package / "cli.py"
        code_bytes = code_file.read_bytes()
        (root / "armed").touch()
        try:
            partial = json.loads(run("partial-engine-change", batch, code=1).stdout)
            if partial["succeeded"] != ["alpha"] or partial["finalized"]:
                raise RuntimeError("consumer partial execution did not preserve first receipt")
            first_receipt = partial["item_records"][0]["receipt"]
            reject("resume-changed-engine", [*batch, "--resume", report])
        finally:
            code_file.write_bytes(code_bytes)
            (root / "armed").unlink()
        guard = brain / "checks/test_corpus.py"
        guard_bytes = guard.read_bytes()
        guard.write_bytes(guard_bytes + b"\nraise RuntimeError('simulated semantic gate failure')\n")
        try:
            failed_gate = json.loads(run("finalizer-failure", [*batch, "--resume", report], code=1).stdout)
            if failed_gate["finalized"] or len(failed_gate["succeeded"]) != 2:
                raise RuntimeError("consumer finalizer failure lost terminal receipts")
        finally:
            guard.write_bytes(guard_bytes)
        successful = json.loads(run("resume", [*batch, "--resume", report]).stdout)
        if not successful["finalized"] or successful["item_records"][0]["receipt"] != first_receipt:
            raise RuntimeError("consumer resume did not preserve canonical receipt")
        object_bytes = {str(p): p.read_bytes() for p in (brain / "objects").rglob("*.json")}
        replay = json.loads(run("replay", [*batch, "--resume", report]).stdout)
        if replay["transactions"] != successful["transactions"] or any(
            p.read_bytes() != content for p, content in ((Path(p), b) for p, b in object_bytes.items())
        ):
            raise RuntimeError("consumer replay changed canonical objects/receipts")
        original_input = (root / "alpha.json").read_bytes()
        (root / "alpha.json").write_text("[{}]\n")
        reject("changed-input", [*batch, "--resume", report])
        (root / "alpha.json").write_bytes(original_input)
        run("advance-consumer", ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                                 "commit", "--allow-empty", "-qm", "advance synthetic revision"])
        reject("changed-consumer-revision", [*batch, "--resume", report])
        # Return the synthetic ref without resetting or touching a user's checkout.
        run("restore-consumer-ref", ["git", "update-ref", "refs/heads/main", commit])
        run("audit", [executable, "audit", "--no-fetch"])
        run("search", [executable, "search", "alpha"])
        run("show", [executable, "show", "context.alpha"])
        created = json.loads(run("draft-create", [executable, "draft", "create", "topic",
                                                   "--title", "Synthetic", "--scope", "release smoke"]).stdout)
        if created["draft"]["format"] != "json-v2":
            raise RuntimeError("consumer did not receive JSON v2 drafts")
        listed = json.loads(run("draft-list", [executable, "draft", "list"]).stdout)
        if not any(d["topic_id"] == "topic" for d in listed["drafts"]):
            raise RuntimeError("consumer JSON v2 not discovered")
        run("draft-show", [executable, "draft", "show", "topic"])
        patch = root / "draft-patch.json"
        patch.write_text(json.dumps({"items": [{"op": "add", "value": {
            "key": "open", "kind": "question", "text": "Synthetic open question", "source_keys": []}}]}))
        run("draft-update", [executable, "draft", "update", "topic", "--expected-sha",
                             created["draft"]["sha256"], "--patch-file", patch])
        run("draft-prepare", [executable, "draft", "prepare", "topic", "--item", "open",
                              "--repo-root", root, "--target-revision", commit, "--out", root / "materials"])
        transcripts = root / "transcripts"
        transcripts.mkdir()
        transcript = transcripts / "abc-123.jsonl"
        transcript.write_text(json.dumps({"type": "user", "sessionId": "abc-123", "cwd": str(root),
                                          "timestamp": "2026-01-01T01:00:00Z",
                                          "message": {"role": "user", "content": "synthetic session"}}) + "\n")
        run("session-list", [executable, "session", "list", "--transcript-root", transcripts])
        complete = [executable, "session", "complete", "abc-123", "--transcript", transcript,
                    "--manifest", manifest, "--report", report]
        run("session-complete", complete)
        run("session-replay", complete)
        return {"ok": True, "engine_identity": identity, "cases": {name: r["exit"] for name, r in cases.items()},
                "canonical_receipts": [r["receipt_id"] for r in replay["transactions"]],
                "rejections_preserved_brain": True, "partial_resume_preserved_receipt": True,
                "json_v2": True, "tokenizer": "regex injection", "embedder": "stub"}
    finally:
        injection.unlink()
