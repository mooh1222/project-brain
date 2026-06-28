"""install — 프로젝트에 config + 스킬을 멱등 설치하고 manifest로 추적한다.

산출물:
  1. .project-brain.json — 없으면 생성(project·brain_root 기록), 있으면 보존.
  2. .claude/skills/<project>-brain-{query,ingest,session-ingest}/SKILL.md
     — templates/를 {{PROJECT}}/{{BRAIN_ROOT}} 치환해 주입.
  3. .project-brain-manifest.json — 심은 파일 경로+sha256.

파일 단위 보존(hwi_PKM manifest 멱등 패턴): 디스크 해시가 manifest 기록과 일치할
때만 갱신(도구 소유). 불일치(사용자 수정)·manifest 밖 기존 파일(사용자 소유)은
건드리지 않고 skipped로 보고한다 — 설치 직후 코퍼스에 맞춘 description 어휘 제안과
그 반영(스킬 맞춤)은 어시스턴트의 몫이고, 맞춤된 파일은 그때부터 사용자 소유가 된다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from project_brain.config import CONFIG_FILENAME

MANIFEST_FILENAME = ".project-brain-manifest.json"

# 템플릿 이름 → (파일명, 스킬 디렉토리 접미)
_TEMPLATES = {
    "query": ("query.md", "brain-query"),
    "ingest": ("ingest.md", "brain-ingest"),
    "session-ingest": ("session-ingest.md", "brain-session-ingest"),
    "checkup": ("checkup.md", "brain-checkup"),
}


def render_template(name: str, *, project: str, brain_root: str) -> str:
    filename, _ = _TEMPLATES[name]
    raw = (Path(__file__).parent / "templates" / filename).read_text(encoding="utf-8")
    return raw.replace("{{PROJECT}}", project).replace("{{BRAIN_ROOT}}", brain_root)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def install(target, *, project: str, brain_root: str = "brain") -> dict:
    """target 프로젝트 루트에 설치. 반환: {config, created, updated, skipped}."""
    target = Path(target)
    report = {"config": "kept", "created": [], "updated": [], "skipped": []}

    # 1. config — 있으면 그대로 보존(사용자 편집 대상), 없으면 생성.
    cfg_path = target / CONFIG_FILENAME
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        # 스킬 렌더는 실제 config를 따른다(인자와 다르면 config가 정답).
        project = cfg.get("project") or project
        brain_root = cfg.get("brain_root", brain_root)
    else:
        cfg_path.write_text(
            json.dumps({"project": project, "brain_root": brain_root},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        report["config"] = "created"

    # 2. manifest 로드 — 심었던 파일의 해시 기록.
    manifest_path = target / MANIFEST_FILENAME
    manifest = {"files": {}}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # 3. 스킬 주입(파일 단위 보존). manifest 키는 target 기준 상대 경로 —
    # 절대 경로를 박으면 다른 머신 checkout에서 도구 소유 파일을 못 알아본다.
    for name in _TEMPLATES:
        _, suffix = _TEMPLATES[name]
        rel_key = str(Path(".claude") / "skills" / f"{project}-{suffix}" / "SKILL.md")
        skill_path = target / rel_key
        rendered = render_template(name, project=project, brain_root=brain_root)
        recorded = manifest["files"].get(rel_key)
        if skill_path.exists():
            on_disk = _sha256(skill_path.read_text(encoding="utf-8"))
            if recorded != on_disk:
                # 사용자 수정(해시 불일치) 또는 install 밖에서 생긴 파일 — 보존.
                report["skipped"].append(str(skill_path))
                continue
            skill_path.write_text(rendered, encoding="utf-8")
            report["updated"].append(str(skill_path))
        else:
            skill_path.parent.mkdir(parents=True, exist_ok=True)
            skill_path.write_text(rendered, encoding="utf-8")
            report["created"].append(str(skill_path))
        manifest["files"][rel_key] = _sha256(rendered)

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
