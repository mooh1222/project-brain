"""P0 foundation baseline, immutable-state checks, and bound receipts."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Collection, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

import project_brain
from project_brain import cli, mutation, search_index, snapshot
from project_brain.installer import MANIFEST_FILENAME
from project_brain.snapshot import SnapshotError
from project_brain.store import BrainStore


_SHA256 = frozenset("0123456789abcdef")
_CORE_PATHS = ("src/project_brain", "pyproject.toml", "uv.lock")
_BASELINE_KEYS = {
    "version",
    "purpose",
    "roots",
    "artifact_root",
    "artifact_inventory",
    "ignored_snapshots_inventory",
    "engine",
    "bb2",
    "corpus",
    "search_index",
    "runtime",
    "stale_set",
}


class FoundationError(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        paths: tuple[Path, ...] = (),
        cause_code: str | None = None,
    ):
        self.code = code
        self.detail = detail
        self.paths = paths
        self.cause_code = cause_code
        super().__init__(f"{code}: {detail}")


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


def _fail(
    code: str,
    detail: str,
    *,
    paths: tuple[Path, ...] = (),
    cause_code: str | None = None,
) -> None:
    raise FoundationError(
        code,
        detail,
        paths=paths,
        cause_code=cause_code,
    )


def _from_snapshot(exc: SnapshotError, *, code: str | None = None) -> FoundationError:
    return FoundationError(
        code or exc.code,
        exc.detail,
        paths=exc.paths,
        cause_code=exc.code,
    )


def canonical_receipt_bytes(value: Mapping[str, object]) -> bytes:
    if not isinstance(value, Mapping):
        _fail("receipt_json_invalid", "receipt must be a JSON object")
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        _fail("receipt_json_invalid", f"receipt is not strict JSON: {exc}")
    return text.encode("utf-8") + b"\n"


def _tree_receipt(root: Path, entries: tuple[snapshot.SafeTreeEntry, ...]) -> TreeReceipt:
    converted = tuple(TreeEntryReceipt(**asdict(entry)) for entry in entries)
    payload = {"entries": [asdict(entry) for entry in converted]}
    return TreeReceipt(
        root=str(root),
        entries=converted,
        sha256=hashlib.sha256(canonical_receipt_bytes(payload)).hexdigest(),
    )


def _tree_dict(receipt: TreeReceipt) -> dict[str, object]:
    return {
        "root": receipt.root,
        "entries": [asdict(entry) for entry in receipt.entries],
        "sha256": receipt.sha256,
    }


def capture_tree_receipt(
    root: Path,
    relative_paths: Collection[str],
    *,
    excluded_paths: Collection[Path] = (),
) -> TreeReceipt:
    root = Path(root)
    try:
        entries = snapshot.capture_tree_entries(
            root,
            relative_paths,
            excluded_paths=excluded_paths,
        )
    except SnapshotError as exc:
        raise _from_snapshot(exc, code="tree_path_invalid" if exc.code == "tree_path_invalid" else None) from exc
    return _tree_receipt(root, entries)


def _scan_tree_receipt(
    root: Path,
    *,
    excluded_paths: Collection[Path] = (),
) -> TreeReceipt:
    root = Path(root)
    try:
        entries = snapshot.scan_tree_entries(root, excluded_paths=excluded_paths)
    except SnapshotError as exc:
        raise _from_snapshot(exc) from exc
    return _tree_receipt(root, entries)


def _absolute_relative(root: Path, path: Path, *, label: str) -> str:
    path = Path(path)
    if not path.is_absolute() or path != Path(os.path.abspath(path)):
        _fail("artifact_inventory_invalid", f"{label} must be exact absolute: {path}")
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        _fail("artifact_inventory_invalid", f"{label} escapes artifact root: {path}")
    pure = PurePosixPath(relative)
    if relative in {"", "."} or pure.is_absolute() or ".." in pure.parts:
        _fail("artifact_inventory_invalid", f"unsafe {label}: {path}")
    return relative


def verify_artifact_inventory(
    artifact_root: Path,
    *,
    allowed_files: Collection[Path],
    verified_snapshot_root: Path | None = None,
) -> TreeReceipt:
    artifact_root = Path(artifact_root)
    allowed_regular = {
        _absolute_relative(artifact_root, Path(path), label="allowed artifact")
        for path in allowed_files
    }
    if verified_snapshot_root is not None:
        verified_snapshot_root = Path(verified_snapshot_root)
        snapshot_relative = _absolute_relative(
            artifact_root,
            verified_snapshot_root,
            label="verified snapshot root",
        )
        try:
            manifest = capture_tree_receipt(
                verified_snapshot_root,
                ["manifest.json"],
            )
            manifest_sha = manifest.entries[0].sha256
            snapshot.verify_snapshot(
                verified_snapshot_root,
                expected_manifest_sha256=manifest_sha,
            )
            verified_tree = _scan_tree_receipt(verified_snapshot_root)
        except (FoundationError, SnapshotError) as exc:
            cause = exc.code if isinstance(exc, (FoundationError, SnapshotError)) else None
            paths = getattr(exc, "paths", ())
            _fail(
                "artifact_inventory_invalid",
                f"verified snapshot inventory failed: {getattr(exc, 'detail', exc)}",
                paths=paths,
                cause_code=cause,
            )
        allowed_regular.update(
            f"{snapshot_relative}/{entry.path}"
            for entry in verified_tree.entries
            if entry.entry_type == "regular"
        )
    try:
        receipt = _scan_tree_receipt(artifact_root)
    except FoundationError as exc:
        raise FoundationError(
            "artifact_inventory_invalid",
            f"artifact inventory is unsafe: {exc.detail}",
            paths=exc.paths,
            cause_code=exc.cause_code or exc.code,
        ) from exc
    actual_regular = {
        entry.path for entry in receipt.entries if entry.entry_type == "regular"
    }
    expected_directories = {
        parent.as_posix()
        for relative in allowed_regular
        for parent in PurePosixPath(relative).parents
        if parent.as_posix() not in {"", "."}
    }
    actual_directories = {
        entry.path for entry in receipt.entries if entry.entry_type == "directory"
    }
    if actual_regular != allowed_regular or actual_directories != expected_directories:
        unexpected = sorted(
            (actual_regular - allowed_regular)
            | (actual_directories - expected_directories)
        )
        missing = sorted(
            (allowed_regular - actual_regular)
            | (expected_directories - actual_directories)
        )
        _fail(
            "artifact_inventory_invalid",
            f"artifact inventory mismatch; unexpected={unexpected!r}, missing={missing!r}",
            paths=tuple(artifact_root / path for path in unexpected),
        )
    return receipt


def resolved_project_brain_file() -> Path:
    return Path(project_brain.__file__).resolve()


def resolved_cli_source_file() -> Path:
    return Path(cli.__file__).resolve()


def _root_identity(path: Path, *, label: str) -> dict[str, object]:
    path = Path(path)
    if not path.is_absolute() or path != Path(os.path.abspath(path)):
        _fail(
            "root_invalid",
            f"{label} root must be an exact normalized absolute path: {path}",
            paths=(path,),
        )
    try:
        descriptor = snapshot._open_absolute_directory(path, create=False)
    except SnapshotError as exc:
        raise _from_snapshot(exc, code="root_invalid") from exc
    try:
        current = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    return {
        "path": str(path),
        "device": current.st_dev,
        "inode": current.st_ino,
        "label": label,
    }


def _git_dict(receipt: snapshot.GitDirtReceipt) -> dict[str, object]:
    return {
        "root": receipt.root,
        "head": receipt.head,
        "status_sha256": receipt.status_sha256,
        "status_porcelain_v1_z_base64": base64.b64encode(receipt.status_bytes).decode("ascii"),
        "dirt_content_manifest": json.loads(receipt.content_manifest_bytes),
        "dirt_content_sha256": receipt.content_manifest_sha256,
    }


def _capture_git(root: Path, *, label: str) -> snapshot.GitDirtReceipt:
    try:
        return snapshot.capture_git_dirt_receipt(root, label=label)
    except SnapshotError as exc:
        raise _from_snapshot(exc) from exc


def _is_core_path(path: str) -> bool:
    return any(path == core or path.startswith(core + "/") for core in _CORE_PATHS)


def _reject_engine_core_dirt(receipt: snapshot.GitDirtReceipt) -> None:
    rows = json.loads(receipt.content_manifest_bytes)
    dirty = sorted({row["path"] for row in rows if _is_core_path(row["path"])})
    if dirty:
        _fail(
            "engine_core_dirty",
            f"engine core contains tracked or untracked dirt: {dirty!r}",
            paths=tuple(Path(receipt.root) / path for path in dirty),
        )


def _git_core_tree_sha(engine_root: Path, head: str) -> str:
    before = _root_identity(engine_root, label="engine")
    try:
        result = subprocess.run(
            ["git", "-C", str(engine_root), "ls-tree", "-r", "-z", head, "--", *_CORE_PATHS],
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        _fail("engine_core_invalid", f"cannot list engine tracked core: {exc}")
    if result.returncode != 0:
        _fail("engine_core_invalid", "cannot list engine tracked core")
    rows: list[dict[str, object]] = []
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            raw_mode, entry_type, raw_oid = metadata.split(b" ", 2)
            path = os.fsdecode(raw_path)
            mode = int(raw_mode, 8)
            oid = raw_oid.decode("ascii")
        except (ValueError, UnicodeError) as exc:
            _fail("engine_core_invalid", f"malformed tracked core entry: {exc}")
        if entry_type != b"blob" or not _is_core_path(path):
            _fail("engine_core_invalid", f"unexpected tracked core entry: {path!r}")
        blob = subprocess.run(
            ["git", "-C", str(engine_root), "cat-file", "blob", oid],
            capture_output=True,
            check=False,
        )
        if blob.returncode != 0:
            _fail("engine_core_invalid", f"cannot read tracked core blob: {path}")
        rows.append({"path": path, "mode": mode, "sha256": hashlib.sha256(blob.stdout).hexdigest()})
    if not rows:
        _fail("engine_core_invalid", "engine tracked core is empty")
    after = _root_identity(engine_root, label="engine")
    try:
        current_head = snapshot.verify_git_root_head(engine_root, label="engine_root")
    except SnapshotError as exc:
        raise _from_snapshot(exc, code="engine_core_invalid") from exc
    if before != after or current_head != head:
        _fail(
            "engine_core_invalid",
            "engine checkout changed during tracked core capture",
            paths=(engine_root,),
        )
    return hashlib.sha256(canonical_receipt_bytes({"entries": sorted(rows, key=lambda row: row["path"])})).hexdigest()


def _ensure_engine_checkout(engine_root: Path) -> tuple[str, str]:
    package_root = engine_root / "src/project_brain"
    import_file = Path(resolved_project_brain_file())
    cli_file = Path(resolved_cli_source_file())
    for label, path in (("import_file", import_file), ("cli_source_file", cli_file)):
        try:
            path.relative_to(package_root)
        except ValueError:
            _fail(
                "engine_checkout_mismatch",
                f"{label} does not belong to the designated engine checkout: {path}",
                paths=(path, engine_root),
            )
    return str(import_file), str(cli_file)


def _file_receipt(root: Path, relative: str, *, optional: bool = False) -> dict[str, object]:
    try:
        receipt = capture_tree_receipt(root, [relative])
    except FoundationError as exc:
        if optional and (exc.cause_code or exc.code) == "source_unavailable":
            return {"path": relative, "sha256": "", "size": 0, "mode": None}
        raise
    if len(receipt.entries) != 1 or receipt.entries[0].entry_type != "regular":
        _fail("file_receipt_invalid", f"expected one regular file: {root / relative}")
    entry = receipt.entries[0]
    return {"path": relative, "sha256": entry.sha256, "size": entry.size, "mode": entry.mode}


def _runtime_inventory(repo_root: Path) -> dict[str, object]:
    manifest_receipt = _file_receipt(repo_root, MANIFEST_FILENAME)
    try:
        raw = snapshot._read_regular(repo_root, MANIFEST_FILENAME)
        value = json.loads(raw)
        files = value["files"]
    except (SnapshotError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        _fail("runtime_manifest_invalid", f"invalid installer manifest: {exc}")
    if not isinstance(files, dict):
        _fail("runtime_manifest_invalid", "installer manifest files must be an object")
    managed: list[dict[str, object]] = []
    for path, recorded_sha in sorted(files.items()):
        if not isinstance(path, str) or not isinstance(recorded_sha, str):
            _fail("runtime_manifest_invalid", "managed path/hash must be strings")
        file_receipt = _file_receipt(repo_root, path)
        if recorded_sha != file_receipt["sha256"]:
            _fail(
                "runtime_manifest_mismatch",
                f"managed runtime hash differs from manifest: {path}",
                paths=(repo_root / path,),
            )
        managed.append({
            "path": path,
            "recorded_sha256": recorded_sha,
            "actual_sha256": file_receipt["sha256"],
            "mode": file_receipt["mode"],
            "size": file_receipt["size"],
        })
    return {"manifest_sha256": manifest_receipt["sha256"], "managed_files": managed}


def _capture_corpus(brain_root: Path) -> tuple[dict[str, object], dict[str, object]]:
    objects = _scan_tree_receipt(brain_root / "objects")
    raw = _scan_tree_receipt(brain_root / "raw")
    store = BrainStore.load(brain_root)
    mutation_fingerprint = mutation.corpus_fingerprint(store)
    live_fingerprint = search_index.compute_corpus_fingerprint(store, brain_root)
    objects_after = _scan_tree_receipt(brain_root / "objects")
    raw_after = _scan_tree_receipt(brain_root / "raw")
    if objects.sha256 != objects_after.sha256 or raw.sha256 != raw_after.sha256:
        _fail("corpus_changed_during_capture", "corpus changed during foundation capture")
    db_before = _file_receipt(brain_root, ".brain-local/index.db")
    meta_fingerprint = search_index.read_meta_fingerprint(brain_root / ".brain-local/index.db")
    db_after = _file_receipt(brain_root, ".brain-local/index.db")
    if db_before != db_after:
        _fail("index_changed_during_capture", "index DB changed during foundation capture")
    return (
        {
            "mutation_fingerprint": mutation_fingerprint,
            "objects_tree_sha256": objects.sha256,
            "raw_tree_sha256": raw.sha256,
        },
        {
            "live_corpus_fingerprint": live_fingerprint,
            "meta_corpus_fingerprint": meta_fingerprint,
            "db_file_sha256": db_before["sha256"],
        },
    )


def _stale_receipt(brain_root: Path) -> dict[str, object]:
    receipt = _file_receipt(brain_root, ".brain-local/stale-set.json", optional=True)
    return {"sha256": receipt["sha256"]}


def capture_foundation_baseline(
    *,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
    artifact_root: Path,
    ignored_snapshots_root: Path,
) -> dict[str, object]:
    engine_root = Path(engine_root)
    repo_root = Path(repo_root)
    brain_root = Path(brain_root)
    artifact_root = Path(artifact_root)
    ignored_snapshots_root = Path(ignored_snapshots_root)
    roots = {
        "engine": _root_identity(engine_root, label="engine"),
        "bb2": _root_identity(repo_root, label="bb2"),
        "brain": _root_identity(brain_root, label="brain"),
    }
    engine_git = _capture_git(engine_root, label="engine_root")
    _reject_engine_core_dirt(engine_git)
    import_file, cli_source_file = _ensure_engine_checkout(engine_root)
    engine = _git_dict(engine_git)
    engine.update({
        "core_paths": list(_CORE_PATHS),
        "core_tracked_tree_sha256": _git_core_tree_sha(engine_root, engine_git.head),
        "import_file": import_file,
        "cli_source_file": cli_source_file,
        "entrypoint": "project_brain.cli:main",
    })
    corpus, index = _capture_corpus(brain_root)
    runtime = _runtime_inventory(repo_root)
    artifact = _scan_tree_receipt(artifact_root)
    ignored = _scan_tree_receipt(
        ignored_snapshots_root,
        excluded_paths=(artifact_root,),
    )
    ignored_dict = _tree_dict(ignored)
    ignored_dict["excluded_subtree"] = artifact_root.relative_to(ignored_snapshots_root).as_posix()
    # Corpus readers may materialize their persistent lock file. Capture user
    # dirt only after all read-only baseline collectors have run so verification
    # compares the state actually left by this capture.
    bb2 = _git_dict(_capture_git(repo_root, label="bb2_root"))
    return {
        "version": 1,
        "purpose": "p0-foundation-baseline",
        "roots": roots,
        "artifact_root": str(artifact_root),
        "artifact_inventory": _tree_dict(artifact),
        "ignored_snapshots_inventory": ignored_dict,
        "engine": engine,
        "bb2": bb2,
        "corpus": corpus,
        "search_index": index,
        "runtime": runtime,
        "stale_set": _stale_receipt(brain_root),
    }


def _decode_status(value: Mapping[str, object]) -> tuple[bytes, bytes]:
    try:
        status = base64.b64decode(value["status_porcelain_v1_z_base64"], validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        _fail("baseline_invalid", f"invalid Git receipt: {exc}")
    # snapshot stores the canonical rows directly, not wrapped in an object.
    manifest = (
        json.dumps(
            value["dirt_content_manifest"],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    if (
        value.get("status_sha256") != hashlib.sha256(status).hexdigest()
        or value.get("dirt_content_sha256")
        != hashlib.sha256(manifest).hexdigest()
    ):
        _fail("baseline_invalid", "Git receipt hashes do not match their payloads")
    return status, manifest


def _git_changed_paths(root: Path, before: str, after: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", "-z", before, after],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        _fail("bb2_head_invalid", "cannot derive BB2 commit path delta")
    return sorted(os.fsdecode(path) for path in result.stdout.split(b"\0") if path)


def _runtime_delta(before: Mapping[str, object], after: Mapping[str, object]) -> list[str]:
    before_rows = {row["path"]: row for row in before["managed_files"]}
    after_rows = {row["path"]: row for row in after["managed_files"]}
    return sorted(
        path
        for path in set(before_rows) | set(after_rows)
        if before_rows.get(path) != after_rows.get(path)
    )


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
) -> dict[str, object]:
    if not isinstance(baseline, Mapping) or set(baseline) != _BASELINE_KEYS or baseline.get("purpose") != "p0-foundation-baseline":
        _fail("baseline_invalid", "foundation baseline top-level shape or purpose is invalid")
    errors: list[str] = []
    observed = {"expected_local_mutation": [], "bb2_commit_paths": []}
    caller_managed = sorted(set(allowed_managed_paths))
    caller_control = sorted(set(allowed_installer_control_paths))
    allowed = {
        "managed_runtime_paths": [],
        "installer_control_paths": caller_control,
    }

    def add(code: str) -> None:
        if code not in errors:
            errors.append(code)

    engine_root = Path(engine_root)
    repo_root = Path(repo_root)
    brain_root = Path(brain_root)
    artifact_root = Path(artifact_root)
    ignored_snapshots_root = Path(ignored_snapshots_root)
    if str(artifact_root) != baseline["artifact_root"]:
        add("artifact_root_mismatch")
    if str(ignored_snapshots_root) != baseline["ignored_snapshots_inventory"]["root"]:
        add("ignored_snapshots_root_mismatch")

    try:
        current_roots = {
            "engine": _root_identity(engine_root, label="engine"),
            "bb2": _root_identity(repo_root, label="bb2"),
            "brain": _root_identity(brain_root, label="brain"),
        }
        if current_roots != baseline["roots"]:
            add("root_identity_changed")
    except FoundationError:
        add("root_identity_changed")

    try:
        import_file, cli_file = _ensure_engine_checkout(engine_root)
        if import_file != baseline["engine"]["import_file"] or cli_file != baseline["engine"]["cli_source_file"]:
            add("engine_checkout_mismatch")
    except FoundationError:
        add("engine_checkout_mismatch")

    try:
        baseline_status, baseline_manifest = _decode_status(baseline["engine"])
        engine_git = snapshot.verify_git_dirt_preserved(
            engine_root,
            baseline_status_bytes=baseline_status,
            baseline_content_manifest_bytes=baseline_manifest,
            label="engine_root",
        )
        _reject_engine_core_dirt(engine_git)
        if engine_git.head != baseline["engine"]["head"]:
            add("engine_head_changed")
        if _git_core_tree_sha(engine_root, engine_git.head) != baseline["engine"]["core_tracked_tree_sha256"]:
            add("engine_core_changed")
    except FoundationError as exc:
        add("engine_core_dirty" if exc.code == "engine_core_dirty" else "engine_state_changed")
    except SnapshotError:
        add("engine_state_changed")

    runtime_current: dict[str, object] | None = None
    try:
        runtime_current = _runtime_inventory(repo_root)
        derived_managed = _runtime_delta(baseline["runtime"], runtime_current)
        allowed["managed_runtime_paths"] = derived_managed
        if derived_managed != caller_managed:
            add("managed_runtime_allowlist_mismatch")
    except (FoundationError, KeyError, TypeError):
        add("runtime_changed")
        derived_managed = []

    try:
        baseline_status, baseline_manifest = _decode_status(baseline["bb2"])
        bb2_git = snapshot.verify_git_dirt_preserved(
            repo_root,
            baseline_status_bytes=baseline_status,
            baseline_content_manifest_bytes=baseline_manifest,
            label="bb2_root",
        )
        if bb2_git.head != baseline["bb2"]["head"]:
            changed = _git_changed_paths(repo_root, baseline["bb2"]["head"], bb2_git.head)
            observed["bb2_commit_paths"] = changed
            if changed != sorted(set(derived_managed) | set(caller_control)):
                add("bb2_commit_paths_invalid")
        elif derived_managed or runtime_current != baseline["runtime"]:
            add("runtime_changed")
    except (FoundationError, SnapshotError, KeyError, TypeError):
        add("user_dirt_changed")

    try:
        current_objects = _scan_tree_receipt(brain_root / "objects")
        if current_objects.sha256 != baseline["corpus"]["objects_tree_sha256"]:
            add("objects_changed")
    except (FoundationError, KeyError, TypeError):
        add("objects_changed")

    try:
        current_raw = _scan_tree_receipt(brain_root / "raw")
        if current_raw.sha256 != baseline["corpus"]["raw_tree_sha256"]:
            add("raw_changed")
    except (FoundationError, KeyError, TypeError):
        add("raw_changed")

    try:
        current_db = _file_receipt(brain_root, ".brain-local/index.db")
        if current_db["sha256"] != baseline["search_index"]["db_file_sha256"]:
            add("index_db_changed")
    except (FoundationError, KeyError, TypeError):
        add("index_db_changed")

    try:
        corpus, index = _capture_corpus(brain_root)
        if corpus["objects_tree_sha256"] != baseline["corpus"]["objects_tree_sha256"]:
            add("objects_changed")
        if corpus["raw_tree_sha256"] != baseline["corpus"]["raw_tree_sha256"]:
            add("raw_changed")
        if corpus["mutation_fingerprint"] != baseline["corpus"]["mutation_fingerprint"]:
            add("corpus_fingerprint_changed")
        if index["db_file_sha256"] != baseline["search_index"]["db_file_sha256"]:
            add("index_db_changed")
        if index["live_corpus_fingerprint"] != baseline["search_index"]["live_corpus_fingerprint"]:
            add("index_input_changed")
        if index["meta_corpus_fingerprint"] != baseline["search_index"]["meta_corpus_fingerprint"]:
            add("index_meta_changed")
    except Exception:
        add("corpus_state_invalid")

    try:
        stale = _stale_receipt(brain_root)
        if stale != baseline["stale_set"]:
            observed["expected_local_mutation"] = ["brain/.brain-local/stale-set.json"]
    except FoundationError:
        add("stale_set_invalid")

    try:
        verify_artifact_inventory(
            artifact_root,
            allowed_files=allowed_artifact_files,
            verified_snapshot_root=verified_snapshot_root,
        )
    except FoundationError:
        add("unexpected_dirt_path")

    try:
        ignored = _scan_tree_receipt(
            ignored_snapshots_root,
            excluded_paths=(artifact_root,),
        )
        if ignored.sha256 != baseline["ignored_snapshots_inventory"]["sha256"]:
            add("ignored_snapshots_changed")
    except (FoundationError, KeyError, TypeError):
        add("ignored_snapshots_changed")

    return {
        "ok": not errors,
        "errors": errors,
        "allowed_changes": allowed,
        "observed_changes": observed,
    }


def _validate_output_path(path: Path, *, label: str) -> tuple[int, str]:
    path = Path(path)
    if not path.is_absolute() or path != Path(os.path.abspath(path)) or path.name in {"", ".", ".."}:
        _fail(f"{label}_path_invalid", f"{label} path must be exact absolute: {path}")
    try:
        parent_fd = snapshot._open_absolute_directory(path.parent, create=True)
    except SnapshotError as exc:
        raise _from_snapshot(exc, code=f"{label}_parent_invalid") from exc
    return parent_fd, path.name


def _preflight_absent(parent_fd: int, name: str, *, label: str) -> None:
    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(current.st_mode):
        _fail(f"{label}_symlink", f"{label} output symlink exists")
    _fail(f"{label}_exists", f"{label} output already exists")


def _create_at(parent_fd: int, name: str, data: bytes, *, label: str) -> os.stat_result:
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
    except OSError as exc:
        _fail(f"{label}_create_failed", f"{label} create failed: {exc}")
    created = os.fstat(descriptor)
    failure: BaseException | None = None
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                _fail(f"{label}_create_failed", f"{label} write made no progress")
            view = view[written:]
        os.fsync(descriptor)
        created = os.fstat(descriptor)
    except (OSError, FoundationError) as exc:
        failure = exc
    finally:
        os.close(descriptor)
    if failure is not None:
        removed = _unlink_if_owned(parent_fd, name, created)
        detail = f"{label} create failed: {failure}"
        if not removed:
            detail += "; partial output could not be safely removed"
        raise FoundationError(
            f"{label}_create_failed",
            detail,
            cause_code=getattr(failure, "code", type(failure).__name__),
        ) from failure
    try:
        os.fsync(parent_fd)
    except OSError as exc:
        removed = _unlink_if_owned(parent_fd, name, created)
        detail = f"{label} parent fsync failed: {exc}"
        if not removed:
            detail += "; output could not be safely removed"
        raise FoundationError(
            f"{label}_create_failed",
            detail,
            cause_code=type(exc).__name__,
        ) from exc
    return created


def _unlink_if_owned(parent_fd: int, name: str, owned: os.stat_result) -> bool:
    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != (owned.st_dev, owned.st_ino):
        return False
    try:
        os.unlink(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except OSError:
        return False
    else:
        return True


def atomic_create_receipt(path: Path, value: Mapping[str, object]) -> str:
    data = canonical_receipt_bytes(value)
    digest = hashlib.sha256(data).hexdigest()
    parent_fd, name = _validate_output_path(path, label="receipt")
    try:
        _preflight_absent(parent_fd, name, label="receipt")
        _create_at(parent_fd, name, data, label="receipt")
    finally:
        os.close(parent_fd)
    return digest


def _binding_value(
    receipt_path: Path,
    receipt_sha: str,
    value: Mapping[str, object],
) -> dict[str, object]:
    purpose = value.get("purpose")
    try:
        if purpose == "p0-foundation-baseline":
            binding_purpose = "p0-foundation-baseline-binding"
            engine_head = value["engine"]["head"]
            bb2_head = value["bb2"]["head"]
        elif purpose == "p0-foundation-gate":
            binding_purpose = "p0-foundation-gate-binding"
            engine_head = value["heads"]["engine"]
            bb2_head = value["heads"]["bb2_after"]
        else:
            _fail("binding_purpose_invalid", f"unsupported receipt purpose: {purpose!r}")
    except (KeyError, TypeError) as exc:
        _fail("binding_head_invalid", f"receipt head source is missing: {exc}")
    for label, head in (("engine_head", engine_head), ("bb2_head", bb2_head)):
        if not isinstance(head, str) or len(head) != 40 or any(ch not in _SHA256 for ch in head):
            _fail("binding_head_invalid", f"{label} must be lowercase 40-hex")
    return {
        "version": 1,
        "purpose": binding_purpose,
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha,
        "engine_head": engine_head,
        "bb2_head": bb2_head,
    }


def _before_binding_create_hook() -> None:
    """Deterministic test seam immediately before the second exclusive create."""


def atomic_create_bound_receipt(
    *,
    receipt_path: Path,
    binding_path: Path,
    value: Mapping[str, object],
) -> tuple[str, str]:
    receipt_path = Path(receipt_path)
    binding_path = Path(binding_path)
    receipt_data = canonical_receipt_bytes(value)
    receipt_sha = hashlib.sha256(receipt_data).hexdigest()
    binding = _binding_value(receipt_path, receipt_sha, value)
    binding_data = canonical_receipt_bytes(binding)
    binding_sha = hashlib.sha256(binding_data).hexdigest()
    receipt_parent, receipt_name = _validate_output_path(receipt_path, label="receipt")
    binding_parent, binding_name = _validate_output_path(binding_path, label="binding")
    created: os.stat_result | None = None
    try:
        _preflight_absent(receipt_parent, receipt_name, label="receipt")
        _preflight_absent(binding_parent, binding_name, label="binding")
        created = _create_at(receipt_parent, receipt_name, receipt_data, label="receipt")
        try:
            _before_binding_create_hook()
            _create_at(binding_parent, binding_name, binding_data, label="binding")
        except (FoundationError, OSError) as exc:
            removed = _unlink_if_owned(receipt_parent, receipt_name, created)
            detail = f"binding_create_failed: {getattr(exc, 'detail', exc)}"
            if not removed:
                detail += "; owned receipt could not be safely rolled back"
            raise FoundationError(
                "binding_create_failed",
                detail,
                paths=(receipt_path, binding_path),
                cause_code=getattr(exc, "code", type(exc).__name__),
            ) from exc
    finally:
        os.close(binding_parent)
        os.close(receipt_parent)
    return receipt_sha, binding_sha


def _read_canonical_json(path: Path, *, label: str) -> tuple[dict[str, object], bytes]:
    try:
        data = snapshot._read_regular(path.parent, path.name)
        value = json.loads(data)
    except (SnapshotError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"{label}_invalid", f"cannot read {label}: {exc}", paths=(path,))
    if not isinstance(value, dict) or canonical_receipt_bytes(value) != data:
        _fail(f"{label}_invalid", f"{label} is not a canonical JSON object", paths=(path,))
    return value, data


def _parse_canonical_json_bytes(
    data: bytes,
    *,
    path: Path,
    label: str,
) -> dict[str, object]:
    try:
        value = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"{label}_invalid", f"cannot parse {label}: {exc}", paths=(path,))
    if not isinstance(value, dict) or canonical_receipt_bytes(value) != data:
        _fail(f"{label}_invalid", f"{label} is not a canonical JSON object", paths=(path,))
    return value


def verify_bound_receipt(
    *,
    receipt_path: Path,
    binding_path: Path,
    expected_purpose: str,
) -> dict[str, object]:
    receipt_path = Path(receipt_path)
    binding_path = Path(binding_path)
    if any(
        not path.is_absolute() or path != Path(os.path.abspath(path))
        for path in (receipt_path, binding_path)
    ):
        _fail(
            "binding_path_invalid",
            "receipt and binding paths must be exact normalized absolute paths",
        )
    binding, _ = _read_canonical_json(binding_path, label="binding")
    expected_keys = {
        "version",
        "purpose",
        "receipt_path",
        "receipt_sha256",
        "engine_head",
        "bb2_head",
    }
    if set(binding) != expected_keys or binding.get("version") != 1:
        _fail("binding_invalid", "binding exact shape is invalid")
    if binding["purpose"] != expected_purpose:
        _fail("binding_invalid", "purpose mismatch")
    if binding["receipt_path"] != str(receipt_path):
        _fail("binding_invalid", "receipt_path mismatch")
    try:
        receipt_data = snapshot._read_regular(receipt_path.parent, receipt_path.name)
    except SnapshotError as exc:
        raise _from_snapshot(exc, code="receipt_invalid") from exc
    if binding["receipt_sha256"] != hashlib.sha256(receipt_data).hexdigest():
        _fail("binding_invalid", "receipt_sha256 mismatch")
    receipt = _parse_canonical_json_bytes(
        receipt_data,
        path=receipt_path,
        label="receipt",
    )
    expected = _binding_value(receipt_path, binding["receipt_sha256"], receipt)
    if expected["purpose"] != expected_purpose:
        _fail("binding_invalid", "purpose does not match receipt purpose")
    if binding["engine_head"] != expected["engine_head"]:
        _fail("binding_invalid", "engine_head mismatch")
    if binding["bb2_head"] != expected["bb2_head"]:
        _fail("binding_invalid", "bb2_head mismatch")
    return receipt
