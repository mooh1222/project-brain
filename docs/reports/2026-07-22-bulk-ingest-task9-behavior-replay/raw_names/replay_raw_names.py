#!/usr/bin/env python3
"""Replay the raw-name policy against a target cwd containing sources/."""
from __future__ import annotations

import hashlib
import re
import sys
import unicodedata
from pathlib import Path, PurePosixPath


def canonical_relative(source_root: Path, path: Path) -> str:
    relative = path.relative_to(source_root)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("source bundle root 밖 경로")
    parts = [unicodedata.normalize("NFC", part) for part in relative.parts if part != "."]
    return str(PurePosixPath(*parts))


def stem_for(path: Path) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")
    return stem or "document"


def reject_symlinks(source_root: Path, sources: list[Path]) -> None:
    if source_root.is_symlink():
        raise ValueError("source bundle root symlink는 허용하지 않음")
    for source in sources:
        relative = source.relative_to(source_root)
        current = source_root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ValueError(f"source symlink는 허용하지 않음: {relative}")


def reject_destination_symlinks(root: Path, raw_root: Path) -> None:
    for component in (root / "brain", root / "brain" / "raw", raw_root):
        if component.is_symlink():
            raise ValueError(f"raw destination symlink는 허용하지 않음: {component.relative_to(root)}")


def copy_exclusive(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, destination.open("xb") as dst:
        while chunk := src.read(64 * 1024):
            dst.write(chunk)


def archive_destination(raw_root: Path, source_root: Path, source: Path) -> Path:
    canonical = canonical_relative(source_root, source)
    stem = stem_for(source)
    archive = raw_root / "legacy-archive"
    base = archive / f"{stem}.md"
    if not base.exists():
        return base
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    for width in range(12, 65):
        candidate = archive / f"{stem}-{digest[:width]}.md"
        if not candidate.exists():
            return candidate
    raise ValueError(f"collision suffix가 64 hex까지 모두 점유됨: {canonical}")


def find_exhausted_collision(raw_root: Path, source_root: Path, sources: list[Path]) -> None:
    for source in sources:
        if source.name in {"revision-one.md", "revision-two.md"}:
            continue
        archive_destination(raw_root, source_root, source)


def run(root: Path) -> None:
    source_root = root / "sources"
    raw_root = root / "brain" / "raw" / "sources"
    if not source_root.is_dir():
        raise ValueError("sources directory가 없음")
    sources = sorted(source_root.rglob("*.md"))
    reject_symlinks(source_root, sources)
    reject_destination_symlinks(root, raw_root)

    existing = list(raw_root.rglob("*")) if raw_root.exists() else []
    if existing:
        find_exhausted_collision(raw_root, source_root, sources)
        raise ValueError("raw target이 이미 있어 replay를 fail-closed로 중단함")

    revision_dir = raw_root / "feature-revisions"
    copy_exclusive(source_root / "revision-one.md", revision_dir / "spec-v1.md")
    copy_exclusive(source_root / "revision-two.md", revision_dir / "spec-v2.md")
    for source in sources:
        if source.name in {"revision-one.md", "revision-two.md"}:
            continue
        copy_exclusive(source, archive_destination(raw_root, source_root, source))


def main() -> int:
    try:
        run(Path.cwd())
    except (OSError, ValueError) as exc:
        print(f"replay raw failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
