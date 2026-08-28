"""주제별 지식 초안의 생성·발견·읽기·갱신·형식 검사."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from collections.abc import Iterable
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
        root.mkdir(parents=True)
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
        drafts_root.mkdir()
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

    h1_lines = [line for _, line in outside if line.startswith("# ")]
    title = (
        h1_lines[0].removeprefix("# ")
        if len(h1_lines) == 1
        else ""
    )
    title_layout_valid = (
        len(h1_lines) == 1
        and bool(title.strip())
        and len(lines) > 1
        and lines[1] == h1_lines[0]
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
        for index, line in outside
        if line.startswith("## ")
    ]
    h2_headings = [heading for _, heading in h2_entries]
    if tuple(h2_headings) != _SECTION_HEADINGS:
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
    _ensure_write_root(brain_root)
    payload = content.encode("utf-8")
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise DraftError(
            "draft_exists",
            f"이미 존재하는 초안입니다: {topic_id}",
        ) from exc
    return show(brain_root, topic_id)


def show(brain_root: Path, topic_id: str) -> dict[str, str]:
    """초안 본문과 현재 SHA를 반환한다."""
    path = _draft_path(brain_root, topic_id)
    problems = lint(brain_root, topic_id=topic_id)
    if problems:
        problem = problems[0]
        raise DraftError(problem["code"], problem["detail"])
    return _document(path, path.read_bytes())


def list_drafts(brain_root: Path) -> list[dict[str, str]]:
    """선택에 필요한 초안 metadata만 topic ID 순으로 반환한다."""
    drafts_root = Path(brain_root) / "drafts"
    problems = lint(brain_root)
    if problems:
        problem = problems[0]
        raise DraftError(problem["code"], problem["detail"])
    if not drafts_root.exists():
        return []
    result = []
    for path in sorted(drafts_root.glob("*.md"), key=lambda item: item.name):
        document = show(brain_root, path.stem)
        result.append({
            key: document[key]
            for key in ("topic_id", "title", "scope", "updated")
        })
    return result


def update(
    brain_root: Path,
    topic_id: str,
    *,
    expected_sha: str,
    content: str,
) -> dict[str, str]:
    """expected SHA와 같은 초안만 같은 디렉터리에서 원자 교체한다."""
    if type(expected_sha) is not str or _SHA256.fullmatch(expected_sha) is None:
        raise DraftError(
            "draft_expected_sha_invalid",
            "expected_sha는 lowercase SHA-256이어야 합니다",
        )
    current = show(brain_root, topic_id)
    if current["sha256"] != expected_sha:
        raise DraftError(
            "draft_stale_sha",
            f"초안 SHA가 달라졌습니다: {topic_id}",
            actual_sha=current["sha256"],
        )

    path = _draft_path(brain_root, topic_id)
    if type(content) is not str:
        raise DraftError(
            "draft_utf8_invalid",
            "갱신 content는 UTF-8로 쓸 수 있는 문자열이어야 합니다",
        )
    problems = _content_problems(path, content)
    if problems:
        problem = problems[0]
        raise DraftError(problem["code"], problem["detail"])
    existing_mode = stat.S_IMODE(path.lstat().st_mode)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fchmod(stream.fileno(), existing_mode)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return show(brain_root, topic_id)


def lint(
    brain_root: Path,
    *,
    topic_id: str | None = None,
) -> list[dict[str, str]]:
    """drafts 영역의 v1 구조 문제를 반환한다."""
    try:
        root = _exact_brain_root(brain_root)
    except DraftError as exc:
        return [{
            "path": "drafts",
            "code": exc.code,
            "detail": exc.detail,
        }]
    drafts_root = root / "drafts"
    try:
        drafts_mode = drafts_root.lstat().st_mode
    except FileNotFoundError:
        drafts_mode = None
    if drafts_mode is not None and not stat.S_ISDIR(drafts_mode):
        return [{
            "path": "drafts",
            "code": "draft_path_invalid",
            "detail": "drafts 루트는 symlink가 아닌 실제 디렉터리여야 합니다",
        }]
    if topic_id is not None:
        paths = [_draft_path(brain_root, topic_id)]
    else:
        if drafts_mode is None:
            return []
        paths = sorted(drafts_root.glob("*.md"), key=lambda item: item.name)

    problems = []
    for path in paths:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            problems.append({
                "path": f"drafts/{path.name}",
                "code": "draft_not_found",
                "detail": "초안 파일이 없습니다",
            })
            continue
        if not stat.S_ISREG(mode):
            problems.append({
                "path": f"drafts/{path.name}",
                "code": "draft_path_invalid",
                "detail": "초안 경로는 symlink가 아닌 일반 파일이어야 합니다",
            })
            continue
        if _TOPIC_ID.fullmatch(path.stem) is None:
            problems.append({
                "path": f"drafts/{path.name}",
                "code": "draft_path_invalid",
                "detail": "초안 파일명은 <ASCII-kebab-topic-id>.md여야 합니다",
            })
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            problems.append({
                "path": f"drafts/{path.name}",
                "code": "draft_utf8_invalid",
                "detail": "초안은 UTF-8 Markdown이어야 합니다",
            })
            continue
        problems.extend(_content_problems(path, text))
    return problems
