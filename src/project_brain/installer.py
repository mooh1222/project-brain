"""install — 프로젝트에 config + 스킬을 멱등 설치하고 manifest로 추적한다.

산출물:
  1. .project-brain.json — 없으면 생성, 있으면 보존.
  2. .agents/skills/<project>-brain-{query,ingest,session-ingest,audit}/...
     — templates/<skill>/ 디렉토리를 통째 walk·렌더 주입(SKILL.md + references/ + scripts/).
  3. .project-brain-manifest.json — 심은 파일 경로+sha256.

파일 단위 보존(hwi_PKM 멱등): 디스크 해시가 manifest 기록과 일치할 때만 갱신(도구 소유),
불일치(사용자 수정)·manifest 밖(사용자 소유)은 보존. (--force·채택은 Task 3에서 추가.)
스킬 런타임에 안 쓰이는 개발 자산(test_*.py)·죽은 산출물(fixtures/)·생성물(__pycache__/.pyc)은
주입하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from project_brain.config import CONFIG_FILENAME

MANIFEST_FILENAME = ".project-brain-manifest.json"
_TEMPLATES_DIR = Path(__file__).parent / "templates"

# 스킬 키 → 디렉토리 접미. templates/<key>/ 가 소스.
_SKILLS = {
    "query": "brain-query",
    "ingest": "brain-ingest",
    "session-ingest": "brain-session-ingest",
    "audit": "brain-audit",
}

_TEXT_SUFFIXES = {".md", ".py", ".js", ".sh", ".json"}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_text(text: str, *, project: str, brain_root: str,
                default_branch: str = "", repo: str = "") -> str:
    """텍스트의 치환 변수를 채운다. {{VAR}} 토큰이라 순서 무관."""
    return (text.replace("{{REPO}}", repo)
                .replace("{{DEFAULT_BRANCH}}", default_branch)
                .replace("{{BRAIN_ROOT}}", brain_root)
                .replace("{{PROJECT}}", project))


def _excluded(rel: Path) -> bool:
    """install 미주입: 개발 자산·죽은 산출물·생성물."""
    parts = set(rel.parts)
    if "__pycache__" in parts or "fixtures" in parts:
        return True
    if rel.suffix == ".pyc":
        return True
    if rel.name.startswith("test_") and rel.suffix == ".py":
        return True
    return False


def _rendered_bytes(src: Path, *, project: str, brain_root: str,
                    default_branch: str, repo: str) -> bytes:
    """텍스트면 렌더 후 utf-8 바이트, 아니면 원본 바이트(바이너리 복사)."""
    if src.suffix in _TEXT_SUFFIXES:
        text = render_text(src.read_text(encoding="utf-8"), project=project,
                           brain_root=brain_root, default_branch=default_branch, repo=repo)
        return text.encode("utf-8")
    return src.read_bytes()


def install(target, *, project: str, brain_root: str = "brain",
            default_branch: str = "", repo: str = "") -> dict:
    """target 프로젝트 루트에 설치. 반환: {config, created, updated, skipped}."""
    target = Path(target)
    report = {"config": "kept", "created": [], "updated": [], "skipped": []}

    # 1. config — 있으면 보존(스킬 렌더는 config를 따른다), 없으면 생성.
    cfg_path = target / CONFIG_FILENAME
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        project = cfg.get("project") or project
        brain_root = cfg.get("brain_root", brain_root)
        default_branch = cfg.get("default_branch", default_branch)
        repo = cfg.get("repo", repo)
    else:
        cfg_path.write_text(
            json.dumps({"project": project, "brain_root": brain_root,
                        "default_branch": default_branch, "repo": repo},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        report["config"] = "created"

    # 2. manifest 로드
    manifest_path = target / MANIFEST_FILENAME
    manifest = {"files": {}}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # 3. 스킬 디렉토리 walk 주입(파일 단위 보존)
    for skill, suffix in _SKILLS.items():
        src_root = _TEMPLATES_DIR / skill
        if not src_root.is_dir():
            continue
        skill_dir_name = f"{project}-{suffix}"
        for src in sorted(src_root.rglob("*")):
            if not src.is_file():
                continue
            rel = src.relative_to(src_root)
            if _excluded(rel):
                continue
            rel_key = str(Path(".agents") / "skills" / skill_dir_name / rel)
            dst = target / rel_key
            rendered = _rendered_bytes(src, project=project, brain_root=brain_root,
                                       default_branch=default_branch, repo=repo)
            rendered_hash = _sha256_bytes(rendered)
            recorded = manifest["files"].get(rel_key)
            if dst.exists():
                on_disk = _sha256_bytes(dst.read_bytes())
                if recorded != on_disk:
                    # 사용자 수정(해시 불일치) 또는 manifest 밖에서 생긴 파일 — 보존.
                    report["skipped"].append(str(dst))
                    continue
                dst.write_bytes(rendered)
                report["updated"].append(str(dst))
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(rendered)
                report["created"].append(str(dst))
            manifest["files"][rel_key] = rendered_hash

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
