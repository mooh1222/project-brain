"""주제별 지식 초안의 생성·발견·읽기·갱신·형식 검사."""

from __future__ import annotations

import hashlib
import json
import copy
import fcntl
import subprocess
import os
import re
import stat
import tempfile
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from project_brain.objbase import now_kst


DRAFT_MARKER = "<!-- project-brain-draft:v1 -->"
_SECTION_HEADINGS = (
    "범위",
    "출처",
    "확인된 이해",
    "어휘 관찰",
    "가설과 충돌",
    "열린 질문",
)
_TOPIC_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_SCOPE_PREVIEW_LIMIT = 240


class DraftError(RuntimeError):
    """draft 공개 인터페이스의 구조화 실패."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        actual_sha: str | None = None,
    ):
        self.code = code
        self.detail = detail
        self.actual_sha = actual_sha
        super().__init__(f"{code}: {detail}")

    def as_dict(self) -> dict[str, str]:
        payload = {"error_code": self.code, "error": self.detail}
        if self.actual_sha is not None:
            payload["actual_sha"] = self.actual_sha
        return payload


def _validate_topic_id(topic_id: object) -> str:
    if type(topic_id) is not str or _TOPIC_ID.fullmatch(topic_id) is None:
        raise DraftError(
            "draft_topic_id_invalid",
            "topic ID는 ASCII lowercase kebab-case여야 합니다",
        )
    return topic_id


def _valid_updated(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _draft_path(brain_root: Path, topic_id: str) -> Path:
    return Path(brain_root) / "drafts" / f"{_validate_topic_id(topic_id)}.md"


def _exact_brain_root(brain_root: Path) -> Path:
    root = Path(brain_root)
    if (
        not root.is_absolute()
        or root != Path(os.path.abspath(root))
        or root.resolve(strict=False) != root
    ):
        raise DraftError(
            "draft_path_invalid",
            "brain root는 symlink와 경로 이탈이 없는 exact absolute path여야 합니다",
        )
    try:
        root_mode = root.lstat().st_mode
    except FileNotFoundError:
        return root
    if not stat.S_ISDIR(root_mode):
        raise DraftError(
            "draft_path_invalid",
            "brain root는 symlink가 아닌 실제 디렉터리여야 합니다",
        )
    return root


def _ensure_write_root(brain_root: Path) -> Path:
    root = _exact_brain_root(brain_root)
    try:
        root_mode = root.lstat().st_mode
    except FileNotFoundError:
        root.mkdir(parents=True, exist_ok=True)
        root_mode = root.lstat().st_mode
    if not stat.S_ISDIR(root_mode):
        raise DraftError(
            "draft_path_invalid",
            "brain root는 symlink가 아닌 실제 디렉터리여야 합니다",
        )

    drafts_root = root / "drafts"
    try:
        drafts_mode = drafts_root.lstat().st_mode
    except FileNotFoundError:
        drafts_root.mkdir(exist_ok=True)
        drafts_mode = drafts_root.lstat().st_mode
    if not stat.S_ISDIR(drafts_mode):
        raise DraftError(
            "draft_path_invalid",
            "drafts 루트는 symlink가 아닌 실제 디렉터리여야 합니다",
        )
    return drafts_root


def _render(
    *,
    topic_id: str,
    title: str,
    scope: str,
    sources: Iterable[str],
    updated_at: str,
) -> str:
    source_lines = "\n".join(f"- {source}" for source in sources)
    return (
        f"{DRAFT_MARKER}\n"
        f"# {title}\n\n"
        f"Topic ID: {topic_id}\n"
        f"Updated: {updated_at}\n\n"
        "## 범위\n\n"
        f"{scope}\n\n"
        "## 출처\n\n"
        f"{source_lines}\n\n"
        "## 확인된 이해\n\n"
        "## 어휘 관찰\n\n"
        "## 가설과 충돌\n\n"
        "## 열린 질문\n"
    )


def _outside_fenced_code(lines: list[str]) -> list[tuple[int, str]]:
    """CommonMark fenced code 밖의 줄과 원래 줄 번호만 반환한다."""
    result: list[tuple[int, str]] = []
    fence: tuple[str, int] | None = None
    for index, line in enumerate(lines):
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        marker = stripped[:1]
        marker_length = 0
        if indent <= 3 and marker in {"`", "~"}:
            marker_length = len(stripped) - len(stripped.lstrip(marker))

        if fence is not None:
            fence_marker, minimum_length = fence
            if (
                marker == fence_marker
                and marker_length >= minimum_length
                and not stripped[marker_length:].strip()
            ):
                fence = None
            continue

        if marker_length >= 3:
            fence = (marker, marker_length)
            continue
        result.append((index, line))
    return result


def _atx_heading(line: str) -> tuple[int, str] | None:
    """CommonMark ATX heading의 level과 닫는 #을 뺀 내용을 반환한다."""
    stripped = line.lstrip(" ")
    if len(line) - len(stripped) > 3 or not stripped.startswith("#"):
        return None
    level = len(stripped) - len(stripped.lstrip("#"))
    if not 1 <= level <= 6:
        return None
    if len(stripped) > level and stripped[level] not in {" ", "\t"}:
        return None
    remainder = stripped[level:]
    if not remainder:
        return level, ""
    content = remainder.lstrip(" \t").rstrip(" \t")
    closing_start = len(content.rstrip("#"))
    if closing_start < len(content) and (
        closing_start == 0 or content[closing_start - 1] in {" ", "\t"}
    ):
        content = content[:closing_start].rstrip(" \t")
    return level, content


def _setext_heading_levels(
    lines: list[str],
    outside: list[tuple[int, str]],
) -> list[int]:
    """fenced code 밖 CommonMark Setext H1/H2 level을 반환한다."""
    outside_indices = {index for index, _ in outside}
    levels: list[int] = []
    for index, line in outside:
        match = re.fullmatch(r" {0,3}(=+|-+)[ \t]*", line)
        if match is None or index == 0 or index - 1 not in outside_indices:
            continue
        previous = lines[index - 1]
        if (
            not previous.strip()
            or len(previous) - len(previous.lstrip(" ")) > 3
            or _atx_heading(previous) is not None
        ):
            continue
        levels.append(1 if match.group(1).startswith("=") else 2)
    return levels


def _parse_content(
    path: Path,
    text: str,
) -> tuple[dict[str, str] | None, list[dict[str, str]]]:
    relative = f"drafts/{path.name}"
    problems: list[dict[str, str]] = []
    lines = text.splitlines()
    outside = _outside_fenced_code(lines)
    outside_lines = [line for _, line in outside]
    if outside_lines.count(DRAFT_MARKER) != 1 or not text.startswith(
        f"{DRAFT_MARKER}\n"
    ):
        problems.append({
            "path": relative,
            "code": "draft_marker_invalid",
            "detail": "project-brain-draft:v1 marker가 첫 줄에 정확히 하나 있어야 합니다",
        })
        return None, problems

    atx_entries = [
        (index, line, parsed)
        for index, line in outside
        if (parsed := _atx_heading(line)) is not None
    ]
    h1_entries = [entry for entry in atx_entries if entry[2][0] == 1]
    setext_levels = _setext_heading_levels(lines, outside)
    title = (
        h1_entries[0][2][1]
        if len(h1_entries) == 1
        else ""
    )
    title_layout_valid = (
        len(h1_entries) + setext_levels.count(1) == 1
        and len(h1_entries) == 1
        and bool(title.strip())
        and h1_entries[0][1] == f"# {title}"
        and len(lines) > 1
        and h1_entries[0][0] == 1
        and lines[1] == h1_entries[0][1]
    )
    if not title_layout_valid:
        problems.append({
            "path": relative,
            "code": "draft_title_invalid",
            "detail": "marker 다음 줄에 비어 있지 않은 H1 제목이 정확히 하나 있어야 합니다",
        })

    topic_id = ""
    updated = ""
    header_layout_valid = False
    if title_layout_valid:
        topic_line = lines[3] if len(lines) > 3 else ""
        topic_id = topic_line.removeprefix("Topic ID: ")
        topic_valid = (
            len(lines) > 3
            and lines[2] == ""
            and topic_line.startswith("Topic ID: ")
            and _TOPIC_ID.fullmatch(topic_id) is not None
        )
        if not topic_valid:
            problems.append({
                "path": relative,
                "code": "draft_topic_id_invalid",
                "detail": "ASCII kebab-case Topic ID가 v1 header의 고정 위치에 있어야 합니다",
            })
        elif topic_id != path.stem:
            problems.append({
                "path": relative,
                "code": "draft_topic_id_mismatch",
                "detail": "Topic ID가 초안 파일명과 일치해야 합니다",
            })
        else:
            updated_line = lines[4] if len(lines) > 4 else ""
            updated = updated_line.removeprefix("Updated: ")
            updated_valid = (
                updated_line.startswith("Updated: ")
                and _valid_updated(updated)
            )
            if not updated_valid:
                problems.append({
                    "path": relative,
                    "code": "draft_updated_invalid",
                    "detail": "timezone이 있는 ISO 8601 Updated가 v1 header의 고정 위치에 있어야 합니다",
                })
            else:
                header_layout_valid = True

    h2_entries = [
        (index, line.removeprefix("## "))
        for index, line, parsed in atx_entries
        if parsed[0] == 2
    ]
    h2_headings = [heading for _, heading in h2_entries]
    if (
        setext_levels.count(2)
        or tuple(h2_headings) != _SECTION_HEADINGS
    ):
        problems.append({
            "path": relative,
            "code": "draft_sections_invalid",
            "detail": "필수 H2 절이 정확히 한 번씩 정해진 순서로 있어야 합니다",
        })
    elif header_layout_valid and (
        len(lines) <= 5
        or lines[5] != ""
        or h2_entries[0][0] != 6
    ):
        problems.append({
            "path": relative,
            "code": "draft_sections_invalid",
            "detail": "첫 H2 절은 v1 header 바로 다음 고정 위치에 있어야 합니다",
        })
    if problems:
        return None, problems
    scope_start = h2_entries[0][0] + 1
    scope_end = h2_entries[1][0]
    return {
        "topic_id": topic_id,
        "title": title,
        "scope": "\n".join(lines[scope_start:scope_end]).strip(),
        "updated": updated,
    }, []


def _content_problems(path: Path, text: str) -> list[dict[str, str]]:
    return _parse_content(path, text)[1]


def _document(path: Path, payload: bytes) -> dict[str, str]:
    text = payload.decode("utf-8")
    parsed, problems = _parse_content(path, text)
    if parsed is None:
        problem = problems[0]
        raise DraftError(problem["code"], problem["detail"])
    return {
        **parsed,
        "path": f"drafts/{path.name}",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "content": text,
    }


def create(
    brain_root: Path,
    *,
    topic_id: str,
    title: str,
    scope: str,
    sources: Iterable[str] = (),
    updated_at: str | None = None,
) -> dict[str, str]:
    """새 v1 초안을 만들고 현재 문서와 SHA를 반환한다."""
    if (
        type(title) is not str
        or not title.strip()
        or "\n" in title
        or "\r" in title
    ):
        raise DraftError(
            "draft_title_invalid",
            "title은 줄바꿈 없는 비어 있지 않은 H1 제목이어야 합니다",
        )
    updated_at = now_kst() if updated_at is None else updated_at
    if not _valid_updated(updated_at):
        raise DraftError(
            "draft_updated_invalid",
            "updated_at은 timezone이 있는 ISO 8601 시각이어야 합니다",
        )
    path = _draft_path(brain_root, topic_id)
    content = _render(
        topic_id=topic_id,
        title=title,
        scope=scope,
        sources=sources,
        updated_at=updated_at,
    )
    problems = _content_problems(path, content)
    if problems:
        problem = problems[0]
        raise DraftError(problem["code"], problem["detail"])
    payload = content.encode("utf-8")
    _create_file(brain_root, topic_id, ".md", payload)
    return show(brain_root, topic_id)


@contextmanager
def _directory(brain_root: Path, *, write: bool = False):
    """공유 디렉터리 fd를 고정하며 writer만 짧게 잠근다."""
    try:
        root = _exact_brain_root(brain_root)
        directory = _ensure_write_root(root) if write else root / "drafts"
        if not stat.S_ISDIR(directory.lstat().st_mode):
            raise DraftError("draft_path_invalid", "drafts 루트는 symlink가 아닌 실제 디렉터리여야 합니다")
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        if write:
            raise
        yield None
        return
    except OSError as exc:
        raise DraftError("draft_read_failed", f"초안 루트를 조회할 수 없습니다: {exc}") from exc
    try:
        if write:
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield fd
    except OSError as exc:
        raise DraftError("draft_write_failed" if write else "draft_read_failed", str(exc)) from exc
    finally:
        os.close(fd)


def _names(fd: int) -> list[str]:
    with os.scandir(fd) as entries:
        return sorted(
            (entry.name for entry in entries if entry.name.endswith((".md", ".json"))),
            key=lambda name: (Path(name).stem, name),
        )


def _read_regular(fd: int, name: str) -> bytes:
    if not stat.S_ISREG(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode):
        raise DraftError("draft_path_invalid", "초안은 symlink가 아닌 일반 파일이어야 합니다")
    file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(file_fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise DraftError("draft_path_invalid", "초안은 일반 파일이어야 합니다")
        return stream.read()


def _read_topic(fd: int | None, topic_id: str) -> tuple[str, bytes]:
    _validate_topic_id(topic_id)
    names = [] if fd is None else [name for name in _names(fd) if Path(name).stem == topic_id]
    if len(names) > 1:
        raise DraftError("draft_topic_conflict", f"동일 topic의 v1/v2가 함께 있습니다: {topic_id}")
    if not names:
        raise DraftError("draft_not_found", f"초안 파일이 없습니다: {topic_id}")
    return names[0], _read_regular(fd, names[0])


def _replace_file(brain_root: Path, fd: int, name: str, payload: bytes, mode: int = 0o600):
    descriptor, temporary_name = tempfile.mkstemp(dir=Path(brain_root) / "drafts", prefix=f".{name}.", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(temporary.name, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary.name, dir_fd=fd)
        except FileNotFoundError:
            pass


def _create_file(brain_root: Path, topic_id: str, suffix: str, payload: bytes):
    with _directory(brain_root, write=True) as fd:
        if any(Path(name).stem == topic_id for name in _names(fd)):
            raise DraftError("draft_exists", f"이미 존재하는 초안입니다: {topic_id}")
        _replace_file(brain_root, fd, topic_id + suffix, payload)


def _json_bytes(document: dict) -> bytes:
    try:
        return (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    except (ValueError, TypeError, UnicodeEncodeError) as exc:
        raise DraftError("draft_json_invalid", str(exc)) from exc


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"중복 JSON 필드: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str):
    raise ValueError(f"JSON에 허용되지 않는 상수: {value}")


def _quote_status(payload: bytes, quote: str) -> str:
    encoded = quote.encode("utf-8")
    first = payload.find(encoded)
    if first < 0:
        return "absent"
    return "multiple" if payload.find(encoded, first + 1) >= 0 else "present"


def _check_v2(document: dict, topic_id: str):
    expected = {"version", "topic_id", "title", "scope", "resume_summary", "updated", "items", "sources"}
    if (
        type(document) is not dict or set(document) != expected
        or type(document["version"]) is not int or document["version"] != 2
        or document["topic_id"] != topic_id or not _valid_updated(document["updated"])
        or any(type(document[key]) is not str for key in ("title", "scope", "resume_summary"))
        or not document["title"].strip() or any(c in document["title"] for c in "\r\n")
        or len(document["scope"]) > 240 or len(document["resume_summary"]) > 2000
    ):
        raise ValueError("v2 metadata가 잘못됐습니다 (scope 최대 240자, resume_summary 최대 2000자)")
    for field in ("items", "sources"):
        values = document[field]
        if type(values) is not list:
            raise ValueError(f"{field}는 배열이어야 합니다")
        keys = []
        for entry in values:
            if type(entry) is not dict or type(entry.get("key")) is not str or _TOPIC_ID.fullmatch(entry["key"]) is None:
                raise ValueError(f"{field} key는 ASCII kebab-case여야 합니다")
            keys.append(entry["key"])
        if len(keys) != len(set(keys)):
            raise ValueError(f"중복 {field} key")
    source_keys = {entry["key"] for entry in document["sources"]}
    for entry in document["items"]:
        if (
            not {"key", "kind", "text", "source_keys"} <= set(entry)
            or set(entry) - {"key", "kind", "text", "source_keys", "limits", "recall_question"}
            or entry["kind"] not in {"finding", "concept", "decision", "hypothesis", "question"}
            or type(entry["text"]) is not str or not entry["text"].strip()
            or type(entry["source_keys"]) is not list
            or any(type(key) is not str for key in entry["source_keys"])
            or len(entry["source_keys"]) != len(set(entry["source_keys"]))
            or not set(entry["source_keys"]) <= source_keys
            or any(type(entry[key]) is not str for key in ("limits", "recall_question") if key in entry)
        ):
            raise ValueError(f"항목 구조·근거 참조가 잘못됐습니다: {entry['key']}")
    for source in document["sources"]:
        if (
            not {"key", "kind", "locator"} <= set(source)
            or set(source) - {"key", "kind", "locator", "quote", "observation", "context"}
            or source["kind"] not in {"code", "document", "session", "object"}
            or type(source["locator"]) is not dict or not source["locator"]
            or any(type(value) is not str or not value.strip() for value in source["locator"].values())
            or any(type(source[key]) is not str for key in ("quote", "context") if key in source)
        ):
            raise ValueError(f"source 구조가 잘못됐습니다: {source['key']}")
        locator = source["locator"]
        required = {"code": {"repo", "path"}, "session": {"session_id", "position"}, "object": {"object_id"}}
        if not required.get(source["kind"], set()) <= set(locator):
            raise ValueError(f"source locator 필드가 누락됐습니다: {source['key']}")
        if source["kind"] == "document" and not set(locator) & {"path", "url", "uri"}:
            raise ValueError("문서 locator는 path/url/uri가 필요합니다")
        if "occurred_at" in locator and not _valid_updated(locator["occurred_at"]):
            raise ValueError("발화 시각은 timezone을 포함해야 합니다")
        if "observation" in source:
            observation = source["observation"]
            if type(observation) is not dict or observation.get("status") not in {"current", "historical", "unavailable"}:
                raise ValueError("관찰 status가 잘못됐습니다")
            if set(observation) - {"status", "repo_root", "repo", "head_sha", "observed_at", "path_dirty", "sha256", "quote_status", "detail"}:
                raise ValueError("알 수 없는 관찰 필드입니다")
            if "sha256" in observation and (type(observation["sha256"]) is not str or _SHA256.fullmatch(observation["sha256"]) is None):
                raise ValueError("관찰 hash가 잘못됐습니다")
            if "head_sha" in observation and (type(observation["head_sha"]) is not str or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", observation["head_sha"]) is None):
                raise ValueError("관찰 HEAD는 정확한 full SHA여야 합니다")
            if "observed_at" in observation and not _valid_updated(observation["observed_at"]):
                raise ValueError("관찰 시각은 timezone을 포함해야 합니다")
            if "path_dirty" in observation and type(observation["path_dirty"]) is not bool:
                raise ValueError("path_dirty는 boolean입니다")
            if "quote_status" in observation and observation["quote_status"] not in ("present", "absent", "multiple"):
                raise ValueError("quote_status가 잘못됐습니다")
            if observation["status"] == "current" and not {"repo_root", "repo", "head_sha", "observed_at", "path_dirty", "sha256"} <= set(observation):
                raise ValueError("현재 관찰 필드가 누락됐습니다")
        if "quote" in source and not source["quote"]:
            raise ValueError("quote는 비어 있을 수 없습니다")


def _parse_v2(path: Path, payload: bytes) -> dict:
    try:
        document = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_json, parse_constant=_reject_json_constant)
        _check_v2(document, path.stem)
        _json_bytes(document)  # JSON escape에 숨은 고립 surrogate도 UTF-8 출력 전에 거부한다.
        return document
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise DraftError("draft_json_invalid", str(exc)) from exc


def parse_patch(text: str) -> object:
    try:
        return json.loads(text, object_pairs_hook=_unique_json, parse_constant=_reject_json_constant)
    except ValueError as exc:
        raise DraftError("draft_patch_invalid", str(exc)) from exc


def _v2_view(path: Path, payload: bytes, *, item: str | None = None, full: bool = False) -> dict:
    document = _parse_v2(path, payload)
    result = {
        key: document[key] for key in ("topic_id", "title", "scope", "updated", "resume_summary")
    }
    result.update(format="json-v2", path=f"drafts/{path.name}", sha256=hashlib.sha256(payload).hexdigest())
    if full:
        result["document"] = document
    elif item is not None:
        selected = next((entry for entry in document["items"] if entry["key"] == item), None)
        if selected is None:
            raise DraftError("draft_item_not_found", f"항목이 없습니다: {item}")
        result["item"] = selected
        result["sources"] = [source for source in document["sources"] if source["key"] in selected["source_keys"]]
    else:
        result["items"] = [
            {"key": entry["key"], "kind": entry["kind"], "preview": entry["text"][:120]}
            for entry in document["items"]
        ]
    return result


def create_v2(
    brain_root: Path, *, topic_id: str, title: str, scope: str,
    sources: Iterable[str] = (),
) -> dict:
    """CLI의 신규 topic을 JSON v2로 만든다. 기존 create는 Python v1 호환용이다."""
    _validate_topic_id(topic_id)
    if type(title) is not str or not title.strip() or "\n" in title or "\r" in title:
        raise DraftError("draft_title_invalid", "title은 비어 있지 않은 한 줄이어야 합니다")
    path = _draft_path(brain_root, topic_id).with_suffix(".json")
    document = {
        "version": 2, "topic_id": topic_id, "title": title, "scope": scope,
        "resume_summary": "", "updated": now_kst(), "items": [],
        "sources": [
            {"key": f"source-{index}", "kind": "document", "locator": {"uri": source}}
            for index, source in enumerate(sources, 1)
        ],
    }
    payload = _json_bytes(document)
    _parse_v2(path, payload)
    _create_file(brain_root, topic_id, ".json", payload)
    return _v2_view(path, payload)


def show(brain_root: Path, topic_id: str, *, item: str | None = None, full: bool = False) -> dict:
    """v1은 기존 전체 본문, v2는 요약·선택 항목을 반환한다."""
    try:
        with _directory(brain_root) as fd:
            name, payload = _read_topic(fd, topic_id)
        path = Path(name)
        if path.suffix == ".json":
            return _v2_view(path, payload, item=item, full=full)
        if item is not None or full:
            raise DraftError("draft_format_mismatch", "v1은 기본 show로 전체 본문을 읽습니다")
        return _document(path, payload)
    except FileNotFoundError as exc:
        raise DraftError("draft_not_found", f"초안 파일이 없습니다: {topic_id}") from exc
    except UnicodeDecodeError as exc:
        raise DraftError("draft_utf8_invalid", "초안은 UTF-8이어야 합니다") from exc
    except OSError as exc:
        raise DraftError("draft_read_failed", str(exc)) from exc


def _problem(name: str, exc: Exception) -> dict[str, str]:
    if isinstance(exc, DraftError):
        code, detail = exc.code, exc.detail
    elif isinstance(exc, UnicodeDecodeError):
        code, detail = "draft_utf8_invalid", "초안은 UTF-8이어야 합니다"
    elif isinstance(exc, FileNotFoundError):
        code, detail = "draft_not_found", "초안 파일이 없습니다"
    else:
        code, detail = "draft_read_failed", str(exc)
    return {"path": f"drafts/{name}", "code": code, "detail": detail}


def _metadata(name: str, payload: bytes) -> dict:
    path = Path(name)
    if _TOPIC_ID.fullmatch(path.stem) is None:
        raise DraftError("draft_path_invalid", "초안 파일명은 ASCII-kebab-topic-id여야 합니다")
    if path.suffix == ".json":
        document = _parse_v2(path, payload)
        return {key: document[key] for key in ("topic_id", "title", "scope", "updated")} | {"format": "json-v2"}
    document = _document(path, payload)
    return {key: document[key] for key in ("topic_id", "title", "scope", "updated")} | {"format": "markdown-v1"}


def list_drafts(brain_root: Path) -> dict[str, object]:
    """정상 v1/v2 metadata와 파일별 진단을 반환한다."""
    drafts, diagnostics = [], []
    try:
        with _directory(brain_root) as fd:
            names = [] if fd is None else _names(fd)
            markdown_topics = {Path(name).stem for name in names if name.endswith(".md")}
            conflicts = markdown_topics & {Path(name).stem for name in names if name.endswith(".json")}
            for name in names:
                try:
                    if Path(name).stem in conflicts:
                        raise DraftError("draft_topic_conflict", "동일 topic의 v1/v2가 함께 있습니다")
                    metadata = _metadata(name, _read_regular(fd, name))
                    scope = metadata["scope"]
                    drafts.append({**metadata, "scope": scope[:_SCOPE_PREVIEW_LIMIT], "scope_truncated": len(scope) > _SCOPE_PREVIEW_LIMIT})
                except (DraftError, OSError, UnicodeDecodeError) as exc:
                    diagnostics.append(_problem(name, exc))
    except OSError as exc:
        raise DraftError("draft_read_failed", str(exc)) from exc
    return {"drafts": drafts, "diagnostics": diagnostics, "partial": bool(diagnostics)}


def _expected_sha(expected_sha: str, payload: bytes, topic_id: str):
    if type(expected_sha) is not str or _SHA256.fullmatch(expected_sha) is None:
        raise DraftError("draft_expected_sha_invalid", "expected_sha는 lowercase SHA-256이어야 합니다")
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha:
        raise DraftError("draft_stale_sha", f"초안 SHA가 달라졌습니다: {topic_id}", actual_sha=actual)


def update(brain_root: Path, topic_id: str, *, expected_sha: str, content: str) -> dict:
    """기존 v1 전체 갱신·응답을 공통 배타 구간에서 유지한다."""
    _validate_topic_id(topic_id)
    # 존재하지 않는 초안의 update가 디렉터리를 만들지 않게 먼저 확인한다.
    show(brain_root, topic_id)
    with _directory(brain_root, write=True) as fd:
        name, payload = _read_topic(fd, topic_id)
        if not name.endswith(".md"):
            raise DraftError("draft_format_mismatch", "v2는 --patch-file로 갱신합니다")
        _expected_sha(expected_sha, payload, topic_id)
        if type(content) is not str:
            raise DraftError("draft_utf8_invalid", "갱신 content는 UTF-8 문자열이어야 합니다")
        try:
            new_payload = content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise DraftError("draft_utf8_invalid", str(exc)) from exc
        _document(Path(name), new_payload)
        mode = stat.S_IMODE(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode)
        _replace_file(brain_root, fd, name, new_payload, mode)
        return _document(Path(name), new_payload)


def _patch_entries(entries: list[dict], operations: object) -> tuple[list[dict], list[str]]:
    if type(operations) is not list:
        raise DraftError("draft_patch_invalid", "items/sources patch는 연산 배열이어야 합니다")
    values = {entry["key"]: entry for entry in entries}
    changed = []
    for operation in operations:
        if type(operation) is not dict or operation.get("op") not in ("add", "replace", "delete"):
            raise DraftError("draft_patch_invalid", "연산은 add/replace/delete 중 하나여야 합니다")
        action = operation["op"]
        expected = {"op", "key"} if action == "delete" else {"op", "value"}
        value = operation.get("value")
        key = operation.get("key") if action == "delete" else value.get("key") if type(value) is dict else None
        if set(operation) != expected or type(key) is not str or _TOPIC_ID.fullmatch(key) is None or key in changed:
            raise DraftError("draft_patch_invalid", "연산 필드·key·중복 변경이 잘못됐습니다")
        if (action == "add" and key in values) or (action != "add" and key not in values):
            raise DraftError("draft_patch_precondition", f"key 전제 불일치: {key}")
        if action == "delete":
            del values[key]
        else:
            values[key] = copy.deepcopy(value)
        changed.append(key)
    return list(values.values()), changed


def update_patch(brain_root: Path, topic_id: str, *, expected_sha: str, patch: object, repo_root: Path | None = None) -> dict:
    """v2 patch를 검증해 한 번에 교체하고 변경 key와 SHA만 반환한다."""
    _validate_topic_id(topic_id)
    if type(patch) is not dict or not patch or set(patch) - {"title", "scope", "resume_summary", "items", "sources"}:
        raise DraftError("draft_patch_invalid", "patch 허용 필드가 잘못됐습니다")
    before = show(brain_root, topic_id, full=True)
    if before.get("format") != "json-v2":
        raise DraftError("draft_format_mismatch", "v1은 --content-file로 전체 갱신합니다")
    # Git/파일 관찰은 잠금 밖에서 한다. 실제 write 시 expected SHA를 다시 확인한다.
    patch = _observe_sources(patch, before["document"], repo_root)
    with _directory(brain_root, write=True) as fd:
        name, payload = _read_topic(fd, topic_id)
        if not name.endswith(".json"):
            raise DraftError("draft_format_mismatch", "v1은 --content-file로 전체 갱신합니다")
        _expected_sha(expected_sha, payload, topic_id)
        document = _parse_v2(Path(name), payload)
        for key in ("title", "scope", "resume_summary"):
            if key in patch:
                document[key] = patch[key]
        changes = {}
        for field in ("items", "sources"):
            document[field], changes[field] = _patch_entries(document[field], patch.get(field, []))
        document["updated"] = now_kst()
        new_payload = _json_bytes(document)
        _parse_v2(Path(name), new_payload)
        mode = stat.S_IMODE(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode)
        _replace_file(brain_root, fd, name, new_payload, mode)
        return {"topic_id": topic_id, "format": "json-v2", "sha256": hashlib.sha256(new_payload).hexdigest(), "updated": document["updated"], "changed_items": changes["items"], "changed_sources": changes["sources"]}


def _observe_code(source: dict, repo_root: Path | None) -> dict:
    from project_brain.repo_context import RepoVerificationError, resolve_git_checkout
    from project_brain.config import load_config

    try:
        checkout = resolve_git_checkout(Path.cwd() if repo_root is None else repo_root)
        config = load_config(start=checkout.root)
        if config is None or config["root"] != checkout.root or config.get("repo") != source["locator"]["repo"]:
            raise DraftError("draft_repo_identity_mismatch", "작업 checkout의 config repo와 source locator repo를 확인할 수 없습니다")
        relative = source["locator"]["path"]
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != relative:
            raise DraftError("draft_source_path_invalid", "source path는 checkout 안의 상대 경로여야 합니다")
        path = checkout.root / path
        if path.resolve() != path:
            raise DraftError("draft_source_path_invalid", "source path의 symlink를 따라가지 않습니다")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise DraftError("draft_source_path_invalid", "source는 일반 파일이어야 합니다")
            payload = stream.read()
        git = subprocess.run(
            ["git", "--literal-pathspecs", "status", "--porcelain", "--untracked-files=all", "--", relative],
            cwd=checkout.root, capture_output=True, timeout=30, check=True,
        )
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or stream.read() != payload:
                raise DraftError("draft_observation_changed", "관찰 중 파일이 바뀌었습니다")
        if resolve_git_checkout(checkout.root).head_sha != checkout.head_sha:
            raise DraftError("draft_observation_changed", "관찰 중 checkout 또는 파일이 바뀌었습니다")
        head_blob = subprocess.run(
            ["git", "show", f"{checkout.head_sha}:{relative}"], cwd=checkout.root,
            capture_output=True, timeout=30,
        )
        observation = {
            "status": "current", "repo_root": str(checkout.root), "repo": config["repo"],
            "head_sha": checkout.head_sha, "observed_at": now_kst(),
            "path_dirty": bool(git.stdout) or head_blob.returncode != 0 or head_blob.stdout != payload,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        if "quote" in source:
            observation["quote_status"] = _quote_status(payload, source["quote"])
        return observation
    except (DraftError, RepoVerificationError, OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError) as exc:
        return {"status": "unavailable", "detail": str(exc)}


def _observe_sources(patch: dict, current_document: dict, repo_root: Path | None) -> dict:
    patch = copy.deepcopy(patch)
    operations = patch.get("sources", [])
    # key·연산 전제를 외부 관찰 전에 확인한다. write 시에도 같은 전제를 다시 검사한다.
    _patch_entries(current_document["sources"], operations)
    existing = {source["key"]: source for source in current_document["sources"]}
    for operation in operations:
        if type(operation) is not dict or type(operation.get("value")) is not dict:
            continue
        source = operation["value"]
        observe = source.pop("observe", False)
        if type(observe) is not bool:
            raise DraftError("draft_patch_invalid", "observe는 boolean이어야 합니다")
        try:
            _check_v2({**current_document, "items": [], "sources": [source]}, current_document["topic_id"])
        except (ValueError, TypeError) as exc:
            raise DraftError("draft_patch_invalid", str(exc)) from exc
        if observe:
            if source.get("kind") != "code":
                raise DraftError("draft_patch_invalid", "현재 관찰은 code source에 지정합니다")
            source["observation"] = _observe_code(source, repo_root)
        else:
            observation = source.get("observation", {})
            if type(observation) is dict and observation.get("status") == "current":
                old = existing.get(source.get("key"))
                if old != source:
                    raise DraftError("draft_observation_invalid", "current 관찰은 observe:true로 엔진이 기록합니다")
            if "observation" not in source:
                source["observation"] = {"status": "unavailable"}
    return patch


def lint(brain_root: Path, *, topic_id: str | None = None) -> list[dict[str, str]]:
    """v1/v2 형식과 경로·참조를 검사하며 의미 검증은 수행하지 않는다."""
    if topic_id is None:
        try:
            return list_drafts(brain_root)["diagnostics"]
        except DraftError as exc:
            return [{"path": "drafts", "code": exc.code, "detail": exc.detail}]
    _validate_topic_id(topic_id)
    try:
        show(brain_root, topic_id)
        return []
    except DraftError as exc:
        # 개별 오류에서도 기존 v1의 상대 경로 표시를 유지한다.
        try:
            with _directory(brain_root) as fd:
                names = [] if fd is None else [name for name in _names(fd) if Path(name).stem == topic_id]
        except (DraftError, OSError):
            names = []
        name = names[0] if len(names) == 1 else topic_id
        return [{"path": f"drafts/{name}", "code": exc.code, "detail": exc.detail}]
