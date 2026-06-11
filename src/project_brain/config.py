"""프로젝트 config(.project-brain.json) 해석 — cwd 상향 탐색.

엔진이 글로벌 도구로 분리되면서(2-레포 모델: 엔진/데이터) 기본 경로의 기준이
'엔진 파일 위치'에서 '데이터를 가진 프로젝트'로 바뀌었다. 프로젝트 루트의
.project-brain.json이 그 기준점이고, install이 생성한다.

필드(전부 선택, 상대 경로는 config 파일 위치 기준으로 절대화):
  brain_root: 코퍼스 루트 (기본 "brain")
  db:         색인 DB (기본 <brain_root>/.brain-local/index.db)
  scenarios:  골든셋 시나리오 (기본 <brain_root>/eval_scenarios.json)
  project:    스킬 주입 시 표시할 프로젝트 이름 (install이 사용)

우선순위는 항상 명시 인자 > config > ConfigError — 침묵 기본값으로 엉뚱한
코퍼스를 읽는 사고를 막는다.
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_FILENAME = ".project-brain.json"


class ConfigError(RuntimeError):
    """config도 명시 인자도 없을 때 — 해결책을 메시지에 담는다."""


def find_config(start=None) -> Path | None:
    """start(기본 cwd) 디렉토리부터 부모로 올라가며 첫 config 파일 경로를 돌려준다."""
    cur = Path(start) if start is not None else Path.cwd()
    cur = cur.resolve()
    for d in (cur, *cur.parents):
        candidate = d / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_config(start=None) -> dict | None:
    """config를 읽어 경로 필드를 절대화해 돌려준다. 파일이 없으면 None.

    반환: {path, root, brain_root, db, scenarios, project}
    """
    cfg_path = find_config(start=start)
    if cfg_path is None:
        return None
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    root = cfg_path.parent
    brain_root = (root / raw.get("brain_root", "brain")).resolve()
    db = (root / raw["db"]).resolve() if "db" in raw \
        else brain_root / ".brain-local" / "index.db"
    scenarios = (root / raw["scenarios"]).resolve() if "scenarios" in raw \
        else brain_root / "eval_scenarios.json"
    return {
        "path": cfg_path,
        "root": root,
        "brain_root": brain_root,
        "db": db,
        "scenarios": scenarios,
        "project": raw.get("project"),
    }


def _resolve(explicit, key: str, what: str, start=None) -> Path:
    if explicit is not None:
        return Path(explicit)
    cfg = load_config(start=start)
    if cfg is not None:
        return cfg[key]
    raise ConfigError(
        f"{what} 경로를 알 수 없다 — 플래그로 직접 주거나, 프로젝트 루트에 "
        f"{CONFIG_FILENAME}을 만들어라(`project-brain install`이 생성)."
    )


def resolve_brain_root(explicit=None, start=None) -> Path:
    return _resolve(explicit, "brain_root", "brain 코퍼스", start=start)


def resolve_db_path(explicit=None, start=None) -> Path:
    return _resolve(explicit, "db", "색인 DB", start=start)


def resolve_scenarios_path(explicit=None, start=None) -> Path:
    return _resolve(explicit, "scenarios", "골든셋 시나리오", start=start)
