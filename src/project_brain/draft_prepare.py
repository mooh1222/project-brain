"""선택 초안 항목의 읽기 전용 적재 재료. 의미 검증과 실제 적재는 수행하지 않는다."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
from pathlib import Path

from project_brain.config import load_config
from project_brain.code_verify import GitError, make_git_blob_reader
from project_brain.draft import (
    DraftError, _atx_heading, _outside_fenced_code, _quote_status,
    _setext_heading_levels, show,
)
from project_brain.repo_context import RepoVerificationError, resolve_git_checkout, resolve_repo_context
from project_brain.snapshot import SnapshotError, _open_absolute_directory, read_regular_no_follow


MAX_EXCERPT_BYTES = 64 * 1024


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or path.as_posix() != value:
        raise ValueError("원문 path는 정규화된 상대 경로여야 합니다")
    return path


def _excerpt(payload: bytes, basis: str, **location) -> dict:
    if len(payload) > MAX_EXCERPT_BYTES:
        raise ValueError("excerpt_too_large: 발췌가 64 KiB를 넘습니다")
    return {"basis": basis, "text": payload.decode("utf-8"), "sha256": _hash(payload), **location}


def _raw_section(payload: bytes, section: str) -> dict:
    text = payload.decode("utf-8")
    lines = text.splitlines(keepends=True)
    outside = _outside_fenced_code(text.splitlines())
    if _setext_heading_levels(text.splitlines(), outside):
        raise ValueError("section_unsupported: Setext 제목이 있는 문서는 절 범위를 직접 확인해야 합니다")
    headings = [
        (index, heading)
        for index, line in outside
        if (heading := _atx_heading(line)) is not None
    ]
    requested = _atx_heading(section)
    matches = [(i, heading) for i, heading in headings if heading == requested or (requested is None and heading[1] == section)]
    if len(matches) != 1:
        raise ValueError("section_missing" if not matches else "section_ambiguous")
    start, heading = matches[0]
    end = next((index for index, other in headings if index > start and other[0] <= heading[0]), len(lines))
    start_byte = len("".join(lines[:start]).encode("utf-8"))
    end_byte = len("".join(lines[:end]).encode("utf-8"))
    return _excerpt(payload[start_byte:end_byte], "local_raw_section", start_byte=start_byte, end_byte=end_byte)


def _describe_bytes(source: dict, result: dict, payload: bytes, diagnose):
    observed_hash = source.get("observation", {}).get("sha256")
    result["file_hash_changed"] = observed_hash != _hash(payload) if observed_hash else None
    if result["file_hash_changed"]:
        diagnose("file_hash_differs", "관찰 원문과 확인한 원문의 bytes hash가 다릅니다. 의미 변화 판정은 아닙니다")
    if "quote" in source:
        result["quote_status"] = _quote_status(payload, source["quote"])
        if result["quote_status"] != "present":
            diagnose(f"quote_{result['quote_status']}", "저장 발췌의 원문 내 존재 상태입니다. 원인을 추정하지 않습니다")


def _source_material(source: dict, brain_root: Path, target) -> tuple[dict, list[dict]]:
    result = {key: value for key, value in source.items() if key != "quote"}
    result["excerpts"] = []
    diagnostics = []

    def diagnose(code, detail):
        diagnostics.append({"source_key": source["key"], "code": code, "detail": detail})

    if "quote" in source:
        try:
            result["excerpts"].append(_excerpt(source["quote"].encode("utf-8"), "stored_quote"))
        except ValueError as exc:
            diagnose("excerpt_unavailable", str(exc))
    locator = source["locator"]
    try:
        if source["kind"] == "code":
            if locator["repo"] != target.expected_repo_id:
                result["file_state"] = "repo_mismatch"
                diagnose("repo_mismatch", "원문 repo와 목표 checkout repo가 다릅니다")
                return result, diagnostics
            relative = _relative(locator["path"])
            tree = subprocess.run(
                ["git", "--literal-pathspecs", "ls-tree", "-z", target.target_revision_sha, "--", relative.as_posix()],
                cwd=target.repo_root, capture_output=True, timeout=30, check=True,
            )
            if not tree.stdout:
                result["file_state"] = "absent"
                diagnose("file_absent", "목표 revision에 파일이 없습니다")
                return result, diagnostics
            if tree.stdout.split(b" ", 1)[0] not in (b"100644", b"100755"):
                result["file_state"] = "unsupported_type"
                diagnose("file_type_unsupported", "목표 원문이 일반 blob 파일이 아닙니다")
                return result, diagnostics
            payload = make_git_blob_reader(target.repo_root)(target.target_revision_sha, relative.as_posix())
            result["file_state"] = "available"
            result["target_file_sha256"] = _hash(payload)
            _describe_bytes(source, result, payload, diagnose)
        elif source["kind"] == "document" and "path" in locator:
            relative = _relative(locator["path"])
            if relative.parts[:2] != ("raw", "sources") or relative.suffix != ".md":
                result["file_state"] = "pointer_only"
                diagnose("document_not_local_raw", "첫 발췌 범위는 brain root의 raw/sources Markdown입니다")
                return result, diagnostics
            path = brain_root / relative
            try:
                path.lstat()
            except FileNotFoundError:
                result["file_state"] = "absent"
                diagnose("file_absent", "로컬 원문 파일이 없습니다")
                return result, diagnostics
            payload, _ = read_regular_no_follow(path)
            result["file_state"] = "available"
            result["local_file_sha256"] = _hash(payload)
            _describe_bytes(source, result, payload, diagnose)
            if "section" not in locator:
                diagnose("section_missing", "유일한 Markdown 절 locator가 필요합니다")
            else:
                try:
                    result["excerpts"].append(_raw_section(payload, locator["section"]))
                except ValueError as exc:
                    diagnose("section_unavailable", str(exc))
        else:
            result["file_state"] = "pointer_only"
            if source["kind"] != "session" or "quote" not in source:
                diagnose("source_not_fetched", "locator만 보존했습니다. 원문은 ingest에서 확인합니다")
            elif "occurred_at" not in locator:
                diagnose("statement_time_unavailable", "원 발화 시각이 미확보입니다. 추측하지 않습니다")
    except (ValueError, OSError, SnapshotError, GitError, subprocess.SubprocessError) as exc:
        result["file_state"] = "unavailable"
        diagnose("source_unavailable", str(exc))
    return result, diagnostics


def _is_inside(fd: int, ancestor_fd: int) -> bool:
    """문자열 대소문자/경로 별칭과 무관하게 실제 디렉터리 조상을 확인한다."""
    target = os.fstat(ancestor_fd)
    identity = (target.st_dev, target.st_ino)
    cursor = os.dup(fd)
    try:
        while True:
            current = os.fstat(cursor)
            if (current.st_dev, current.st_ino) == identity:
                return True
            parent = os.open("..", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=cursor)
            above = os.fstat(parent)
            if (above.st_dev, above.st_ino) == (current.st_dev, current.st_ino):
                os.close(parent)
                return False
            os.close(cursor)
            cursor = parent
    finally:
        os.close(cursor)


def _write_packet(out: Path, brain_root: Path, payload: bytes):
    out = Path(out)
    if (
        not out.is_absolute() or out != Path(os.path.abspath(out))
        or out == brain_root or brain_root in out.parents
        or out.name in ("", ".", "..")
    ):
        raise DraftError("draft_output_invalid", "출력은 brain root 밖의 정규화된 absolute 경로여야 합니다")
    parent_fd = output_fd = file_fd = brain_fd = None
    created_file = False
    try:
        parent_fd = _open_absolute_directory(out.parent, create=False)
        brain_fd = _open_absolute_directory(brain_root, create=False)
        if _is_inside(parent_fd, brain_fd):
            raise DraftError("draft_output_invalid", "출력 부모는 실제 brain root 밖이어야 합니다")
        try:
            os.mkdir(out.name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        output_fd = os.open(out.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        if _is_inside(output_fd, brain_fd):
            raise DraftError("draft_output_invalid", "출력은 실제 brain root 밖이어야 합니다")
        fcntl.flock(output_fd, fcntl.LOCK_EX)
        if os.listdir(output_fd):
            raise DraftError("draft_output_not_empty", "출력 디렉터리가 비어 있지 않습니다")
        file_fd = os.open("materials.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=output_fd)
        created_file = True
        with os.fdopen(file_fd, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(output_fd)
    except (OSError, SnapshotError) as exc:
        if created_file:
            os.unlink("materials.json", dir_fd=output_fd)
        raise DraftError("draft_output_invalid", str(exc)) from exc
    finally:
        for fd in (file_fd, output_fd, parent_fd, brain_fd):
            if fd is not None:
                os.close(fd)


def prepare(brain_root: Path, topic_id: str, *, item_keys: list[str], repo_root: Path,
            target_revision: str, out: Path) -> dict:
    selected = show(brain_root, topic_id, full=True)
    if selected.get("format") != "json-v2":
        raise DraftError("draft_format_mismatch", "v1은 기본 show의 본문을 기존 ingest로 넘깁니다")
    document = selected["document"]
    items = {item["key"]: item for item in document["items"]}
    if not item_keys or len(item_keys) != len(set(item_keys)) or any(key not in items for key in item_keys):
        raise DraftError("draft_item_not_found", "선택 key가 없거나 중복됐습니다")
    try:
        checkout = resolve_git_checkout(Path(repo_root))
        config = load_config(start=checkout.root)
        if config is None or config["root"] != checkout.root or not config.get("repo"):
            raise DraftError("draft_repo_identity_mismatch", "목표 checkout 루트의 repo config가 필요합니다")
        target = resolve_repo_context(checkout.root, expected_repo_id=config["repo"],
                                      configured_repo_id=config["repo"], expected_revision_ref=target_revision)
    except (RepoVerificationError, ValueError, OSError) as exc:
        raise DraftError("draft_target_invalid", str(exc)) from exc
    chosen = [items[key] for key in item_keys]
    source_keys = {key for item in chosen for key in item["source_keys"]}
    materials = []
    diagnostics = [
        {"item_key": item["key"], "code": "evidence_missing", "detail": "근거 locator가 아직 없습니다"}
        for item in chosen if not item["source_keys"] and item["kind"] not in ("hypothesis", "question")
    ]
    for source in document["sources"]:
        if source["key"] in source_keys:
            material, problems = _source_material(source, Path(brain_root), target)
            materials.append(material)
            diagnostics.extend(problems)
    unresolved = [item for item in chosen if item["kind"] in ("hypothesis", "question")]
    packet = {
        "format": "project-brain-draft-materials-v1",
        "draft": {"topic_id": topic_id, "sha256": selected["sha256"], "selected_keys": item_keys},
        "target": {"repo": target.expected_repo_id, "repo_root": str(target.repo_root), "revision": target.target_revision_sha},
        "items": [item for item in chosen if item not in unresolved],
        "unresolved_items": unresolved, "sources": materials, "diagnostics": diagnostics,
        "partial": bool(diagnostics or unresolved),
    }
    payload = (json.dumps(packet, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    _write_packet(Path(out), Path(brain_root), payload)
    return {"topic_id": topic_id, "path": str(Path(out) / "materials.json"),
            "sha256": _hash(payload), "selected_keys": item_keys, "partial": packet["partial"],
            "diagnostics": diagnostics, "unresolved_keys": [item["key"] for item in unresolved]}
