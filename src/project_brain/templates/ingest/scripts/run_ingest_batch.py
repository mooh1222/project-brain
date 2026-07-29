#!/usr/bin/env python3
"""여러 적재 항목을 순서대로 실행하고 재개 가능한 상태 보고서를 남긴다."""
from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, NamedTuple


ItemRunner = Callable[[dict[str, Any]], Any]
Finalizer = Callable[[dict[str, Any], dict[str, Any], list[dict[str, Any]]], Any]
BaselineCollector = Callable[[], Any]
ReceiptRecoverer = Callable[
    ...,
    tuple[dict[str, Any] | None, ...],
]
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ENGINE_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")

_UNSUPPORTED_PARENT_FSYNC_ERRNOS = {errno.EINVAL}
for _errno_name in ("ENOTSUP", "EOPNOTSUPP"):
    _errno_value = getattr(errno, _errno_name, None)
    if _errno_value is not None:
        _UNSUPPORTED_PARENT_FSYNC_ERRNOS.add(_errno_value)


class _FileSnapshot(NamedTuple):
    root: Path
    relative_path: str
    path: Path
    payload: bytes
    root_device: int
    root_inode: int
    device: int
    inode: int
    size: int
    sha256: str


def _stderr_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else str(value)


def _fsync_parent_directory(path: Path) -> None:
    directory_fd: int | None = None
    try:
        directory_fd = os.open(path, os.O_RDONLY)
        os.fsync(directory_fd)
    except OSError as exc:
        if exc.errno in _UNSUPPORTED_PARENT_FSYNC_ERRNOS:
            return
        raise
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _write_report(path: Path, report: dict) -> None:
    temporary_path: Path | None = None
    try:
        if path.exists() and path.is_dir():
            raise OSError(f"report 경로가 디렉터리입니다: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as f:
            temporary_path = Path(f.name)
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        _fsync_parent_directory(path.parent)
    except OSError as exc:
        raise ValueError(f"report를 저장할 수 없습니다: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _finalizer_module():
    script = Path(__file__).resolve().with_name("finalize_ingest.py")
    spec = importlib.util.spec_from_file_location("project_brain_semantic_finalizer", script)
    if spec is None or spec.loader is None:
        raise ValueError("semantic finalizer를 불러올 수 없습니다")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _has_symlink_component(path: Path) -> bool:
    # macOS의 /var -> /private/var 같은 시스템 경로 별칭은 허용하되,
    # 호출자가 지정한 마지막 경로 자체가 link인 경우는 거부한다.
    return path.absolute().is_symlink()


def _canonical_input_file(path: Path, *, field: str) -> Path:
    absolute = path.absolute()
    if _has_symlink_component(absolute):
        raise ValueError(f"{field} 경로에 symbolic link가 있습니다")
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{field} 경로가 없습니다: {absolute}: {exc}") from exc
    if not resolved.is_file():
        raise ValueError(f"{field} 경로가 regular file이 아닙니다: {resolved}")
    return resolved


def _read_fd_bytes(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _read_relative_snapshot(
    root: Path,
    relative_path: str,
    *,
    field: str,
    expected_root: tuple[int, int] | None = None,
) -> _FileSnapshot:
    relative = Path(relative_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or ".." in relative.parts
        or "." in relative.parts
        or relative.as_posix() != relative_path
    ):
        raise ValueError(f"{field} 경로는 canonical relative path여야 합니다")
    root_fd = -1
    directory_fd = -1
    file_fd = -1
    try:
        root_fd = os.open(
            root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        root_stat = os.fstat(root_fd)
        if (
            expected_root is not None
            and (root_stat.st_dev, root_stat.st_ino) != expected_root
        ):
            raise ValueError(f"input_binding_changed: {field} root")
        directory_fd = os.dup(root_fd)
        for part in relative.parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
            directory_stat = os.fstat(directory_fd)
            if directory_stat.st_dev != root_stat.st_dev:
                raise ValueError(f"{field} 경로가 filesystem을 벗어납니다")
        file_stat = os.stat(
            relative.name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError(f"{field} 경로가 regular file이 아닙니다")
        if file_stat.st_dev != root_stat.st_dev:
            raise ValueError(f"{field} 파일이 다른 filesystem에 있습니다")
        file_fd = os.open(
            relative.name,
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=directory_fd,
        )
        opened = os.fstat(file_fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (file_stat.st_dev, file_stat.st_ino)
        ):
            raise ValueError(f"input_binding_changed: {field}")
        payload = _read_fd_bytes(file_fd)
        after_read = os.fstat(file_fd)
        after_path = os.stat(
            relative.name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        binding = (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
        )
        if (
            (after_read.st_dev, after_read.st_ino, after_read.st_size)
            != binding
            or (after_path.st_dev, after_path.st_ino, after_path.st_size)
            != binding
            or len(payload) != opened.st_size
        ):
            raise ValueError(f"input_binding_changed: {field}")
        return _FileSnapshot(
            root=root,
            relative_path=relative_path,
            path=root / relative,
            payload=payload,
            root_device=root_stat.st_dev,
            root_inode=root_stat.st_ino,
            device=opened.st_dev,
            inode=opened.st_ino,
            size=opened.st_size,
            sha256=hashlib.sha256(payload).hexdigest(),
        )
    except OSError as exc:
        raise ValueError(f"{field} 경로를 no-follow로 읽을 수 없습니다: {exc}") from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if directory_fd >= 0:
            os.close(directory_fd)
        if root_fd >= 0:
            os.close(root_fd)


def _snapshot_manifest(path: Path) -> _FileSnapshot:
    absolute = path.absolute()
    if absolute.is_symlink():
        raise ValueError("manifest 경로에 symbolic link가 있습니다")
    try:
        parent = absolute.parent.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"manifest parent를 확인할 수 없습니다: {exc}") from exc
    return _read_relative_snapshot(
        parent,
        absolute.name,
        field="manifest",
    )


def _verify_snapshot(snapshot: _FileSnapshot, *, field: str) -> None:
    current = _read_relative_snapshot(
        snapshot.root,
        snapshot.relative_path,
        field=field,
        expected_root=(snapshot.root_device, snapshot.root_inode),
    )
    if (
        current.device,
        current.inode,
        current.size,
        current.sha256,
    ) != (
        snapshot.device,
        snapshot.inode,
        snapshot.size,
        snapshot.sha256,
    ):
        raise ValueError(f"input_binding_changed: {field}")


def _write_staged_file(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o400,
    )
    try:
        view = memoryview(payload)
        written = 0
        while written < len(view):
            written += os.write(descriptor, view[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


@contextmanager
def _stage_item_inputs(items: list[dict[str, Any]]):
    stage_root = Path(tempfile.mkdtemp(prefix="project-brain-batch-inputs-"))
    staged_items: list[dict[str, Any]] = []
    try:
        for index, item in enumerate(items):
            item_root = stage_root / f"item-{index:04d}"
            item_root.mkdir(mode=0o700)
            verify_path = item_root / item["_verify_snapshot"].path.name
            domain_name = item["_domain_snapshot"].path.name
            if domain_name == verify_path.name:
                domain_name = f"domain-{domain_name}"
            domain_path = item_root / domain_name
            binding_path = item_root / "batch-binding.json"
            _write_staged_file(
                verify_path,
                item["_verify_snapshot"].payload,
            )
            _write_staged_file(
                domain_path,
                item["_domain_snapshot"].payload,
            )
            _write_staged_file(
                binding_path,
                _canonical_bytes(item["batch_binding"]),
            )
            verify_snapshot = _read_relative_snapshot(
                item_root,
                verify_path.name,
                field=f"{item['key']}.staged.verify_json",
            )
            domain_snapshot = _read_relative_snapshot(
                item_root,
                domain_path.name,
                field=f"{item['key']}.staged.domain_spec_py",
            )
            binding_snapshot = _read_relative_snapshot(
                item_root,
                binding_path.name,
                field=f"{item['key']}.staged.batch_binding",
            )
            item_root.chmod(0o500)
            staged_items.append({
                **item,
                "verify_json": verify_path,
                "domain_spec_py": domain_path,
                "batch_binding_file": binding_path,
                "_staged_verify_snapshot": verify_snapshot,
                "_staged_domain_snapshot": domain_snapshot,
                "_staged_binding_snapshot": binding_snapshot,
            })
        stage_root.chmod(0o500)
        yield staged_items
    finally:
        for directory in sorted(
            (path for path in stage_root.rglob("*") if path.is_dir()),
            reverse=True,
        ):
            try:
                directory.chmod(0o700)
            except OSError:
                pass
        try:
            stage_root.chmod(0o700)
        except OSError:
            pass
        shutil.rmtree(stage_root, ignore_errors=True)


def _verify_item_inputs(
    manifest_snapshot: _FileSnapshot,
    item: dict[str, Any],
) -> None:
    _verify_snapshot(manifest_snapshot, field="manifest")
    _verify_snapshot(
        item["_verify_snapshot"],
        field=f"{item['key']}.verify_json",
    )
    _verify_snapshot(
        item["_domain_snapshot"],
        field=f"{item['key']}.domain_spec_py",
    )
    _verify_snapshot(
        item["_staged_verify_snapshot"],
        field=f"{item['key']}.staged.verify_json",
    )
    _verify_snapshot(
        item["_staged_domain_snapshot"],
        field=f"{item['key']}.staged.domain_spec_py",
    )
    _verify_snapshot(
        item["_staged_binding_snapshot"],
        field=f"{item['key']}.staged.batch_binding",
    )


def _repo_contract(payload: dict[str, Any]) -> dict[str, Any]:
    repo_root_value = payload.get("repo_root")
    if not isinstance(repo_root_value, str) or not Path(repo_root_value).is_absolute():
        raise ValueError("manifest.repo_root는 absolute path여야 합니다")
    repo_root_path = Path(repo_root_value)
    if _has_symlink_component(repo_root_path):
        raise ValueError("manifest.repo_root는 symbolic link를 포함할 수 없습니다")
    try:
        repo_root = repo_root_path.resolve(strict=True)
        repo_stat = repo_root.stat()
    except OSError as exc:
        raise ValueError(f"manifest.repo_root를 확인할 수 없습니다: {exc}") from exc
    if not repo_root.is_dir():
        raise ValueError("manifest.repo_root는 directory여야 합니다")
    expected_repo_id = payload.get("expected_repo_id")
    expected_revision_ref = payload.get("expected_revision_ref")
    engine_sha = payload.get("engine_sha")
    if not isinstance(expected_repo_id, str) or not expected_repo_id.strip():
        raise ValueError("manifest.expected_repo_id가 없습니다")
    if not isinstance(expected_revision_ref, str) or not expected_revision_ref.strip():
        raise ValueError("manifest.expected_revision_ref가 없습니다")
    if not isinstance(engine_sha, str) or _ENGINE_SHA.fullmatch(engine_sha) is None:
        raise ValueError("manifest.engine_sha는 exact lowercase Git SHA여야 합니다")
    return {
        "repo_root": str(repo_root),
        "expected_repo_id": expected_repo_id,
        "expected_revision_ref": expected_revision_ref,
        "engine_sha": engine_sha,
        "repo_root_device": repo_stat.st_dev,
        "repo_root_inode": repo_stat.st_ino,
    }


def _resolve_execution_state(
    declared: dict[str, Any],
) -> dict[str, Any]:
    try:
        import project_brain
        from project_brain.config import load_config
        from project_brain.repo_context import (
            resolve_git_checkout,
            resolve_repo_context,
        )

        repo_root = Path(declared["repo_root"])
        configured = load_config(start=repo_root)
        if (
            configured is None
            or configured["root"].resolve() != repo_root
        ):
            raise ValueError(
                "repo_root의 .project-brain.json을 찾을 수 없습니다"
            )
        brain_root = configured["brain_root"].resolve(strict=True)
        if not brain_root.is_dir():
            raise ValueError("configured brain_root가 directory가 아닙니다")
        brain_stat = brain_root.stat()
        repo_context = resolve_repo_context(
            repo_root,
            expected_repo_id=declared["expected_repo_id"],
            configured_repo_id=configured.get("repo"),
            expected_revision_ref=declared["expected_revision_ref"],
        )
        engine_module = Path(project_brain.__file__)
        engine = resolve_git_checkout(engine_module)
    except Exception as exc:
        raise ValueError(f"execution state를 확정할 수 없습니다: {exc}") from exc
    if engine.head_sha != declared["engine_sha"]:
        raise ValueError(
            "declared engine_sha가 actual engine HEAD와 다릅니다"
        )
    repo_stat = repo_context.repo_root.stat()
    return {
        "repo_root": str(repo_context.repo_root),
        "brain_root": str(brain_root),
        "brain_root_device": brain_stat.st_dev,
        "brain_root_inode": brain_stat.st_ino,
        "expected_repo_id": repo_context.expected_repo_id,
        "expected_revision_ref": repo_context.expected_revision_ref,
        "target_revision_sha": repo_context.target_revision_sha,
        "repo_root_device": repo_stat.st_dev,
        "repo_root_inode": repo_stat.st_ino,
        "engine_root": str(engine.root),
        "engine_sha": engine.head_sha,
        "engine_root_device": engine.device,
        "engine_root_inode": engine.inode,
    }


def _revalidate_execution_state(
    resolver: Callable[[dict[str, Any]], dict[str, Any]],
    declared: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    try:
        current = resolver(declared)
    except Exception as exc:
        raise ValueError(
            f"execution_state_changed: {exc}"
        ) from exc
    if not isinstance(current, dict) or set(current) != set(expected):
        raise ValueError(
            "execution_state_changed: state fields"
        )
    for field_name, expected_value in expected.items():
        if current.get(field_name) != expected_value:
            raise ValueError(
                f"execution_state_changed: {field_name}"
            )


def _load_manifest(
    snapshot: _FileSnapshot,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], str]:
    try:
        manifest_bytes = snapshot.payload
        payload = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"manifest를 읽을 수 없습니다: {exc}") from exc
    required_fields = {
        "repo_root",
        "expected_repo_id",
        "expected_revision_ref",
        "engine_sha",
        "items",
        "finalization",
    }
    if not isinstance(payload, dict):
        raise ValueError("manifest 필드가 정확하지 않습니다")
    if "finalization" not in payload:
        raise ValueError("manifest.finalization이 없습니다")
    if set(payload) != required_fields:
        raise ValueError("manifest 필드가 정확하지 않습니다")
    if not isinstance(payload.get("items"), list):
        raise ValueError("manifest.items는 배열이어야 합니다")
    if not payload["items"]:
        raise ValueError("manifest.items는 최소 1개여야 합니다")

    keys: set[str] = set()
    items: list[dict[str, Any]] = []
    for index, raw_item in enumerate(payload["items"]):
        if not isinstance(raw_item, dict):
            raise ValueError(f"items[{index}]는 객체여야 합니다")
        key = raw_item.get("key")
        if not isinstance(key, str) or not key:
            raise ValueError(f"items[{index}].key가 없습니다")
        if key in keys:
            raise ValueError(f"중복 key: {key}")
        keys.add(key)
        resolved: dict[str, Any] = {"key": key}
        for field in ("verify_json", "domain_spec_py"):
            value = raw_item.get(field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"items[{index}].{field}가 없습니다")
            relative = Path(value)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or "." in relative.parts
                or relative.as_posix() != value
            ):
                raise ValueError(f"items[{index}].{field} 경로는 manifest-relative여야 합니다")
            source_snapshot = _read_relative_snapshot(
                snapshot.root,
                value,
                field=f"items[{index}].{field}",
                expected_root=(
                    snapshot.root_device,
                    snapshot.root_inode,
                ),
            )
            resolved[field] = source_snapshot.path
            resolved[
                "_verify_snapshot"
                if field == "verify_json"
                else "_domain_snapshot"
            ] = source_snapshot
        items.append(resolved)
    try:
        finalization = _finalizer_module().validate_contract(payload.get("finalization"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"manifest.finalization이 올바르지 않습니다: {exc}") from exc
    return (
        items,
        finalization,
        _repo_contract(payload),
        hashlib.sha256(manifest_bytes).hexdigest(),
    )


def _manifest_fingerprint(items: list[dict[str, Any]], finalization: dict[str, Any]) -> str:
    fingerprint_items = []
    for item in items:
        fingerprint_items.append({
            "key": item["key"],
            "verify_json_path": str(item["verify_json"]),
            "verify_json_sha256": item["_verify_snapshot"].sha256,
            "domain_spec_py_path": str(item["domain_spec_py"]),
            "domain_spec_py_sha256": item["_domain_snapshot"].sha256,
        })
    canonical = json.dumps({"items": fingerprint_items, "finalization": finalization},
                           ensure_ascii=True, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _item_input_fingerprint(item: dict[str, Any]) -> str:
    identity = {
        "key": item["key"],
        "verify_json_path": item["_verify_snapshot"].relative_path,
        "verify_json_sha256": item["_verify_snapshot"].sha256,
        "domain_spec_py_path": item["_domain_snapshot"].relative_path,
        "domain_spec_py_sha256": item["_domain_snapshot"].sha256,
    }
    return hashlib.sha256(_canonical_bytes(identity)).hexdigest()


def _bind_items(
    items: list[dict[str, Any]],
    *,
    manifest_sha256: str,
    execution_state: dict[str, Any],
) -> list[dict[str, Any]]:
    from project_brain.transaction_receipt import (
        BatchBinding,
        batch_binding_dict,
    )

    bound: list[dict[str, Any]] = []
    for item in items:
        binding = BatchBinding(
            batch_manifest_sha256=manifest_sha256,
            item_key=item["key"],
            item_input_fingerprint=_item_input_fingerprint(item),
            verify_json_sha256=item["_verify_snapshot"].sha256,
            domain_spec_py_sha256=item["_domain_snapshot"].sha256,
            repo_root=execution_state["repo_root"],
            brain_root=execution_state["brain_root"],
            brain_root_device=execution_state["brain_root_device"],
            brain_root_inode=execution_state["brain_root_inode"],
            expected_repo_id=execution_state["expected_repo_id"],
            expected_revision_ref=execution_state[
                "expected_revision_ref"
            ],
            target_revision_sha=execution_state[
                "target_revision_sha"
            ],
            engine_root=execution_state["engine_root"],
            engine_sha=execution_state["engine_sha"],
        )
        bound.append({
            **item,
            "batch_binding": batch_binding_dict(binding),
        })
    return bound


def _new_item_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "binding": dict(item["batch_binding"]),
        "status": "pending",
        "failure": None,
        "transaction": None,
    }


def _sync_compatibility_fields(report: dict[str, Any]) -> None:
    records = report["item_records"]
    report["succeeded"] = [
        record["binding"]["item_key"]
        for record in records
        if record["status"] == "committed"
    ]
    report["failed"] = [
        {
            "key": record["binding"]["item_key"],
            **record["failure"],
        }
        for record in records
        if record["status"] == "failed"
    ]
    report["transactions"] = [
        record["transaction"]
        for record in records
        if record["status"] == "committed"
    ]


def _default_receipt_recoverer(
    repo_root: Path,
    bindings: tuple[dict[str, Any], ...],
    expected_receipts: tuple[dict[str, Any] | None, ...],
    *,
    verification_mode: str,
) -> tuple[dict[str, Any] | None, ...]:
    from project_brain.config import load_config
    from project_brain.corpus_io import recover_committed_receipts

    configured = load_config(start=repo_root)
    if not bindings:
        raise ValueError("receipt verification bindings are empty")
    brain_roots = {binding.get("brain_root") for binding in bindings}
    if len(brain_roots) != 1:
        raise ValueError("receipt verification brain_root mismatch")
    brain_root = Path(next(iter(brain_roots)))
    try:
        brain_stat = brain_root.stat()
    except OSError as exc:
        raise ValueError(f"receipt verification brain_root unavailable: {exc}") from exc
    if (
        configured is None
        or configured["root"].resolve() != repo_root
        or configured["brain_root"].resolve() != brain_root
        or any(
            binding.get("brain_root_device") != brain_stat.st_dev
            or binding.get("brain_root_inode") != brain_stat.st_ino
            for binding in bindings
        )
    ):
        raise ValueError("receipt verification config is unavailable")
    return recover_committed_receipts(
        brain_root,
        bindings,
        expected_receipts=expected_receipts,
        verification_mode=verification_mode,
    )


def _recover_item_records(
    records: list[dict[str, Any]],
    *,
    repo_root: Path,
    recoverer: ReceiptRecoverer,
    verification_mode: str = "strict_commit",
) -> None:
    bindings = tuple(record["binding"] for record in records)
    expected = tuple(
        record["transaction"]
        if record["status"] == "committed"
        else None
        for record in records
    )
    receipts = recoverer(
        repo_root,
        bindings,
        expected,
        verification_mode=verification_mode,
    )
    if len(receipts) != len(records):
        raise ValueError("receipt verifier result length mismatch")
    for record, receipt in zip(records, receipts):
        if receipt is None:
            if record["status"] == "committed":
                raise ValueError(
                    "committed item record has no durable receipt"
                )
            continue
        record["status"] = "committed"
        record["failure"] = None
        record["transaction"] = dict(receipt)


def _reject_report_input_collision(report_path: Path, manifest_path: Path,
                                   items: list[dict[str, Any]]) -> None:
    inputs = [manifest_path]
    for item in items:
        inputs.extend((item["verify_json"], item["domain_spec_py"]))
    if any(report_path == input_path for input_path in inputs):
        raise ValueError("report 경로가 manifest 또는 항목 입력과 같습니다")


def _default_item_runner(item: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().with_name("run_ingest.sh")
    return subprocess.run(
        [
            str(script),
            "--defer-finalize",
            "--repo-root",
            item["repo_root"],
            "--brain-root",
            item["brain_root"],
            "--expected-repo-id",
            item["expected_repo_id"],
            "--expected-revision-ref",
            item["expected_revision_ref"],
            "--engine-sha",
            item["engine_sha"],
            "--batch-binding-file",
            str(item["batch_binding_file"]),
            str(item["verify_json"]),
            str(item["domain_spec_py"]),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def _default_baseline_collector() -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().with_name("finalize_ingest.sh")
    return subprocess.run([str(script), "--capture-baseline"], text=True,
                          capture_output=True, check=False)


def _default_finalizer(
    contract: dict[str, Any],
    baseline: dict[str, Any],
    item_records: list[dict[str, Any]],
) -> subprocess.CompletedProcess[str]:
    if not item_records:
        raise ValueError("finalizer item records가 비어 있습니다")
    repo_roots = {
        record.get("binding", {}).get("repo_root")
        for record in item_records
        if isinstance(record, dict)
    }
    if len(repo_roots) != 1 or not all(isinstance(root, str) and root for root in repo_roots):
        raise ValueError("finalizer item records의 repo_root가 정확하지 않습니다")
    repo_root = next(iter(repo_roots))
    script = Path(__file__).resolve().with_name("finalize_ingest.sh")
    with tempfile.TemporaryDirectory(prefix="project-brain-finalize-") as td:
        root = Path(td)
        config_path = root / "config.json"
        baseline_path = root / "baseline.json"
        item_records_path = root / "item-records.json"
        config_path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
        baseline_path.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
        item_records_path.write_text(
            json.dumps(item_records, ensure_ascii=False),
            encoding="utf-8",
        )
        return subprocess.run(
            [
                str(script),
                "--config",
                str(config_path),
                "--baseline",
                str(baseline_path),
                "--item-records",
                str(item_records_path),
                "--repo-root",
                repo_root,
            ],
            text=True, capture_output=True, check=False)


def _transaction_details(
    result: Any,
) -> tuple[dict[str, Any] | None, int, str]:
    if isinstance(result, int) and not isinstance(result, bool) and result != 0:
        return None, result, ""
    if (
        isinstance(result, tuple)
        and len(result) == 2
        and isinstance(result[0], int)
        and not isinstance(result[0], bool)
        and result[0] != 0
        and isinstance(result[1], str)
    ):
        return None, result[0], result[1]
    if isinstance(result, dict):
        payload = result
        exit_code = 0 if payload.get("ok") is True else 1
        stderr = ""
    elif isinstance(result, subprocess.CompletedProcess):
        exit_code = (
            result.returncode
            if isinstance(result.returncode, int) and not isinstance(result.returncode, bool)
            else 1
        )
        stderr = _stderr_text(result.stderr)
        try:
            payload = json.loads(_stderr_text(result.stdout))
        except (TypeError, json.JSONDecodeError):
            payload = None
    else:
        return None, 1, f"구조화 transaction 결과가 아님: {result!r}"
    if exit_code != 0:
        return None, exit_code, stderr
    try:
        normalized = _finalizer_module().validate_transaction_results([payload])
    except (OSError, ValueError) as exc:
        return None, 1, str(exc)
    return normalized[0], 0, stderr


def _run_item(
    runner: ItemRunner,
    item: dict[str, Any],
) -> tuple[dict[str, Any] | None, int, str]:
    try:
        return _transaction_details(runner(item))
    except Exception as exc:  # 실행 오류도 항목 실패로 남겨야 재개할 수 있다.
        return None, 1, str(exc)


def _json_payload(result: Any) -> tuple[dict[str, Any] | None, int, str]:
    if isinstance(result, dict):
        payload = result
        exit_code = 0 if payload.get("ok") is True else 1
        return payload, exit_code, ""
    if isinstance(result, subprocess.CompletedProcess):
        exit_code = (result.returncode if isinstance(result.returncode, int)
                     and not isinstance(result.returncode, bool) else 1)
        try:
            stdout = _stderr_text(result.stdout)
            payload = json.loads(stdout)
        except (TypeError, json.JSONDecodeError):
            payload = None
        return payload if isinstance(payload, dict) else None, exit_code, _stderr_text(result.stderr)
    return None, 1, f"구조화 JSON 실행 결과가 아님: {result!r}"


def _baseline_details(result: Any, expected_unmerged_locator_ids: list[str]) -> tuple[dict[str, Any] | None, str]:
    payload, exit_code, stderr = _json_payload(result)
    if exit_code != 0 or not isinstance(payload, dict) or payload.get("ok") is not True:
        return None, stderr or "고립 baseline 결과가 올바르지 않습니다"
    try:
        normalized = _finalizer_module().normalize_baseline(
            payload, expected_unmerged_locator_ids)
    except (OSError, ValueError) as exc:
        return None, str(exc)
    if not normalized["git_baseline_available"]:
        return {"ok": True, "isolated_ids": normalized["isolated_ids"]}, ""
    return {key: normalized[key] for key in
            ("ok", "isolated_ids", "target_head", "unmerged_locator_ids")}, ""


def _finalization_details(result: Any) -> tuple[dict[str, Any], int, str]:
    payload, exit_code, stderr = _json_payload(result)
    required = {
        "ok",
        "transactions",
        "commands",
        "isolation",
        "unmerged",
        "recall_checks",
        "errors",
    }
    valid = (isinstance(payload, dict) and set(payload) == required
             and isinstance(payload.get("ok"), bool)
             and isinstance(payload.get("transactions"), list)
             and isinstance(payload.get("commands"), dict)
             and isinstance(payload.get("isolation"), dict)
             and isinstance(payload.get("unmerged"), dict)
             and isinstance(payload.get("recall_checks"), list)
             and isinstance(payload.get("errors"), list)
             and all(isinstance(error, str) for error in payload.get("errors", [])))
    if not valid:
        failure = {"ok": False, "transactions": [], "commands": {},
                   "isolation": {}, "unmerged": {}, "recall_checks": [],
                   "errors": [stderr or "finalizer가 구조화 결과를 반환하지 않았습니다"]}
        return failure, 1, stderr
    if payload["ok"] is not (exit_code == 0):
        payload = dict(payload)
        payload["ok"] = False
        payload["errors"] = [*payload["errors"], "finalizer 종료 코드와 ok가 일치하지 않습니다"]
        return payload, 1, stderr
    return payload, exit_code, stderr


def _load_resume_state(
    path: Path,
    *,
    expected_records: list[dict[str, Any]],
    manifest_fingerprint: str,
    manifest_sha256: str,
    repo_contract: dict[str, Any],
    expected_unmerged_locator_ids: list[str],
    recoverer: ReceiptRecoverer,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        resume_file = _canonical_input_file(path, field="resume report")
        with resume_file.open(encoding="utf-8") as f:
            previous = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"resume report를 읽을 수 없습니다: {exc}") from exc
    required = {
        "repo_root",
        "brain_root",
        "brain_root_device",
        "brain_root_inode",
        "expected_repo_id",
        "expected_revision_ref",
        "target_revision_sha",
        "engine_sha",
        "engine_root",
        "repo_root_device",
        "repo_root_inode",
        "engine_root_device",
        "engine_root_inode",
        "manifest_sha256",
        "manifest_fingerprint",
        "expected",
        "item_records",
        "succeeded",
        "failed",
        "transactions",
        "isolation_baseline",
        "finalized",
        "finalization",
        "finalize_failure",
    }
    if not isinstance(previous, dict) or set(previous) != required:
        raise ValueError("resume_contract_mismatch: report fields")
    expected_contract = {
        **repo_contract,
        "manifest_sha256": manifest_sha256,
        "manifest_fingerprint": manifest_fingerprint,
    }
    for field, expected_value in expected_contract.items():
        if previous.get(field) != expected_value:
            raise ValueError(f"resume_contract_mismatch: {field}")
    if (not isinstance(previous["expected"], int)
            or isinstance(previous["expected"], bool)
            or previous["expected"] != len(expected_records)):
        raise ValueError("resume_contract_mismatch: expected")
    raw_records = previous["item_records"]
    if (
        not isinstance(raw_records, list)
        or len(raw_records) != len(expected_records)
    ):
        raise ValueError("resume_contract_mismatch: item_records")
    records: list[dict[str, Any]] = []
    for index, (raw, expected_record) in enumerate(
        zip(raw_records, expected_records)
    ):
        if not isinstance(raw, dict) or set(raw) != {
            "binding",
            "status",
            "failure",
            "transaction",
        }:
            raise ValueError(
                f"resume_contract_mismatch: item_records[{index}]"
            )
        if raw.get("binding") != expected_record["binding"]:
            raise ValueError(
                f"resume_contract_mismatch: item_records[{index}].binding"
            )
        status = raw.get("status")
        failure = raw.get("failure")
        transaction = raw.get("transaction")
        if status == "pending":
            valid_state = failure is None and transaction is None
        elif status == "failed":
            valid_state = (
                isinstance(failure, dict)
                and set(failure) == {"exit_code", "stderr"}
                and isinstance(failure.get("exit_code"), int)
                and not isinstance(failure.get("exit_code"), bool)
                and isinstance(failure.get("stderr"), str)
                and transaction is None
            )
        elif status == "committed":
            valid_state = failure is None and isinstance(
                transaction,
                dict,
            )
        else:
            valid_state = False
        if not valid_state:
            raise ValueError(
                f"resume_contract_mismatch: item_records[{index}].status"
            )
        records.append({
            "binding": dict(raw["binding"]),
            "status": status,
            "failure": (
                None if failure is None else dict(failure)
            ),
            "transaction": (
                None if transaction is None else dict(transaction)
            ),
        })
    compatibility = {"item_records": records}
    _sync_compatibility_fields(compatibility)
    for field_name in ("succeeded", "failed", "transactions"):
        if previous[field_name] != compatibility[field_name]:
            raise ValueError(
                f"resume_contract_mismatch: {field_name}"
            )
    if not isinstance(previous["finalized"], bool):
        raise ValueError("resume_contract_mismatch: finalized")
    try:
        _recover_item_records(
            records,
            repo_root=Path(repo_contract["repo_root"]),
            recoverer=recoverer,
        )
    except Exception as exc:
        raise ValueError(
            f"resume_contract_mismatch: receipts: {exc}"
        ) from exc
    try:
        normalized = _finalizer_module().normalize_baseline(
            previous["isolation_baseline"], expected_unmerged_locator_ids)
    except (OSError, ValueError) as exc:
        raise ValueError(f"resume_contract_mismatch: isolation_baseline: {exc}") from exc
    if not normalized["git_baseline_available"]:
        return (
            records,
            {"ok": True, "isolated_ids": normalized["isolated_ids"]},
        )
    baseline = {key: normalized[key] for key in
                ("ok", "isolated_ids", "target_head", "unmerged_locator_ids")}
    return records, baseline


def run_batch(manifest_path, report_path, *, resume_path=None,
              item_runner=None, finalizer=None, baseline_collector=None,
              state_resolver=None, receipt_recoverer=None) -> dict:
    """manifest의 항목을 실행하고 항목마다 원자적으로 report를 갱신한다.

    ``item_runner``는 절대 경로가 들어간 ``key``, ``verify_json``, ``domain_spec_py`` 항목
    dict를 받고, 정확한 transaction dict나 stdout이 그 JSON인
    ``subprocess.CompletedProcess``를 반환한다. bool이 아닌 종료 코드(int)와
    ``(종료 코드, stderr 문자열)`` tuple은 실패 경로 테스트용으로만 허용한다.
    """
    manifest_snapshot = _snapshot_manifest(Path(manifest_path))
    manifest = manifest_snapshot.path
    report_file = Path(report_path).resolve()
    if report_file.exists() and report_file.is_dir():
        raise ValueError(f"report 경로가 디렉터리입니다: {report_file}")
    items, finalization_contract, declared_contract, manifest_sha256 = (
        _load_manifest(manifest_snapshot)
    )  # 실행 전 전체 입력을 검사한다.
    _reject_report_input_collision(report_file, manifest, items)
    manifest_fingerprint = _manifest_fingerprint(items, finalization_contract)
    resolver = (
        _resolve_execution_state
        if state_resolver is None
        else state_resolver
    )
    try:
        repo_contract = resolver(declared_contract)
    except Exception as exc:
        prefix = (
            "resume_contract_mismatch"
            if resume_path is not None
            else "execution_state_invalid"
        )
        raise ValueError(f"{prefix}: {exc}") from exc
    items = _bind_items(
        items,
        manifest_sha256=manifest_sha256,
        execution_state=repo_contract,
    )
    expected_records = [
        _new_item_record(item)
        for item in items
    ]
    recoverer: ReceiptRecoverer = (
        _default_receipt_recoverer
        if receipt_recoverer is None
        else receipt_recoverer
    )

    item_records: list[dict[str, Any]]
    isolation_baseline: dict[str, Any]
    if resume_path is not None:
        item_records, isolation_baseline = _load_resume_state(
            Path(resume_path),
            expected_records=expected_records,
            manifest_fingerprint=manifest_fingerprint,
            manifest_sha256=manifest_sha256,
            repo_contract=repo_contract,
            expected_unmerged_locator_ids=finalization_contract[
                "expected_unmerged_locator_ids"
            ],
            recoverer=recoverer,
        )
    else:
        item_records = expected_records
        collect: BaselineCollector = (_default_baseline_collector if baseline_collector is None
                                      else baseline_collector)
        try:
            isolation_baseline, baseline_error = _baseline_details(
                collect(), finalization_contract["expected_unmerged_locator_ids"])
        except Exception as exc:
            isolation_baseline, baseline_error = None, str(exc)
        if isolation_baseline is None:
            raise ValueError(f"적재 전 isolation baseline 수집 실패: {baseline_error}")

    with _stage_item_inputs(items) as staged_items:
        report = {
            **repo_contract,
            "manifest_sha256": manifest_sha256,
            "expected": len(staged_items),
            "manifest_fingerprint": manifest_fingerprint,
            "item_records": item_records,
            "succeeded": [],
            "failed": [],
            "transactions": [],
            "isolation_baseline": isolation_baseline,
            "finalized": False,
            "finalization": None,
            "finalize_failure": None,
        }
        _sync_compatibility_fields(report)
        _write_report(report_file, report)
        runner: ItemRunner = (
            _default_item_runner
            if item_runner is None
            else item_runner
        )
        records_by_key = {
            record["binding"]["item_key"]: record
            for record in item_records
        }
        for item in staged_items:
            record = records_by_key[item["key"]]
            if record["status"] == "committed":
                continue
            record["status"] = "pending"
            record["failure"] = None
            record["transaction"] = None
            _sync_compatibility_fields(report)
            _write_report(report_file, report)
            try:
                _revalidate_execution_state(
                    resolver,
                    declared_contract,
                    repo_contract,
                )
                _verify_item_inputs(manifest_snapshot, item)
                item_input = {**item, **repo_contract}
                transaction, exit_code, stderr = _run_item(
                    runner,
                    item_input,
                )
                _verify_item_inputs(manifest_snapshot, item)
            except ValueError as exc:
                transaction = None
                exit_code = 1
                stderr = str(exc)
            if exit_code == 0 and transaction is not None:
                record["status"] = "committed"
                record["transaction"] = transaction
                try:
                    _recover_item_records(
                        item_records,
                        repo_root=Path(repo_contract["repo_root"]),
                        recoverer=recoverer,
                    )
                except Exception as exc:
                    record["status"] = "failed"
                    record["transaction"] = None
                    record["failure"] = {
                        "exit_code": 1,
                        "stderr": str(exc)[-2000:],
                    }
            else:
                try:
                    _recover_item_records(
                        item_records,
                        repo_root=Path(repo_contract["repo_root"]),
                        recoverer=recoverer,
                    )
                except Exception as exc:
                    stderr = f"{stderr}; receipt verification: {exc}"
                if record["status"] != "committed":
                    record["status"] = "failed"
                    record["failure"] = {
                        "exit_code": exit_code,
                        "stderr": stderr[-2000:],
                    }
                    record["transaction"] = None
            _sync_compatibility_fields(report)
            _write_report(report_file, report)
            if record["status"] == "failed":
                break

        if report["failed"]:
            return report

        try:
            _revalidate_execution_state(
                resolver,
                declared_contract,
                repo_contract,
            )
            for item in staged_items:
                _verify_item_inputs(manifest_snapshot, item)
            _recover_item_records(
                report["item_records"],
                repo_root=Path(repo_contract["repo_root"]),
                recoverer=recoverer,
            )
            _sync_compatibility_fields(report)
            if any(
                record["status"] != "committed"
                for record in report["item_records"]
            ):
                raise ValueError(
                    "finalizer 전에 모든 item record가 committed여야 합니다"
                )
        except Exception as exc:
            report["finalize_failure"] = {
                "exit_code": 1,
                "stderr": str(exc)[-2000:],
            }
            _write_report(report_file, report)
            return report

        finish: Finalizer = (
            _default_finalizer
            if finalizer is None
            else finalizer
        )
        try:
            finalization, final_exit_code, final_stderr = (
                _finalization_details(
                    finish(
                        finalization_contract,
                        isolation_baseline,
                        report["item_records"],
                    )
                )
            )
        except Exception as exc:
            finalization = {
                "ok": False,
                "transactions": [],
                "commands": {},
                "isolation": {},
                "unmerged": {},
                "recall_checks": [],
                "errors": [str(exc)],
            }
            final_exit_code = 1
            final_stderr = str(exc)
        report["finalization"] = finalization
        try:
            _revalidate_execution_state(
                resolver,
                declared_contract,
                repo_contract,
            )
            for item in staged_items:
                _verify_item_inputs(manifest_snapshot, item)
            _recover_item_records(
                report["item_records"],
                repo_root=Path(repo_contract["repo_root"]),
                recoverer=recoverer,
                verification_mode="post_gate_object_tail",
            )
            _sync_compatibility_fields(report)
        except Exception as exc:
            finalization["ok"] = False
            finalization["errors"] = [
                *finalization.get("errors", []),
                f"post-finalizer verification failed: {exc}",
            ]
            final_exit_code = 1
            final_stderr = str(exc)
        transactions_match = (
            finalization.get("transactions")
            == report["transactions"]
        )
        if not transactions_match:
            finalization["ok"] = False
            finalization["errors"] = [
                *finalization.get("errors", []),
                "finalizer transaction results가 batch report와 다릅니다",
            ]
            if final_exit_code == 0:
                final_exit_code = 1
        report["finalized"] = (
            final_exit_code == 0
            and finalization["ok"] is True
            and transactions_match
            and bool(report["transactions"])
        )
        if not report["finalized"]:
            report["finalize_failure"] = {
                "exit_code": final_exit_code,
                "stderr": final_stderr[-2000:],
            }
        _write_report(report_file, report)
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="여러 적재 항목을 순서대로 실행합니다")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_batch(args.manifest, args.report, resume_path=args.resume)
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "finalized": False,
            "errors": [str(exc)],
        }, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not report["failed"] and report["finalized"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
