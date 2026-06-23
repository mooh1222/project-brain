"""세션 transcript 스캔·처리 마킹 — (다) 과거 세션 추출의 CLI 보조(스펙 §7).

경계 불변: transcript 본문 해석·지식 추출은 CLI가 하지 않는다. 여기는
결정론 로직(스캔·집계·마킹)만 — 추출 판단은 스킬(Claude) 몫.

★jsonl 파싱 요구(스펙 §7, 실측)★: 세션 파일 선두는 mode/queue-operation/
file-history-snapshot 같은 cwd 없는 메타 라인인 경우가 보통이다. cwd는
"cwd 키가 있는 첫 라인"에서 읽고(디렉토리명은 인코딩 손실이라 정본 아님 —
워크트리 세션은 다른 디렉토리에 쌓인다), 시작시각·메시지 수는
type ∈ {user, assistant} 라인 기준으로 산출한다.
"""
from __future__ import annotations

import json
from pathlib import Path

from project_brain.objbase import now_kst

DEFAULT_TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"
_MESSAGE_TYPES = {"user", "assistant"}


def scan_sessions(
    transcript_root=None,
    project_filter: str | None = None,
    brain_root=None,
) -> list[dict]:
    """transcript_root 아래 모든 세션 jsonl의 요약 목록.

    반환 원소: {uuid, path, cwd, started_at, message_count}.
    project_filter: cwd에 이 부분 문자열이 포함된 세션만(예: "demoapp").
    brain_root: 지정하면 processed 플래그를 함께 반환한다.
    """
    root = Path(transcript_root) if transcript_root else DEFAULT_TRANSCRIPT_ROOT
    sessions = []
    for path in sorted(root.glob("*/*.jsonl")):
        info = _summarize(path)
        if project_filter and project_filter not in (info["cwd"] or ""):
            continue
        if brain_root is not None:
            info["processed"] = is_processed(info["uuid"], brain_root)
        sessions.append(info)
    return sessions


def _marks_dir(brain_root) -> Path:
    return Path(brain_root) / ".brain-local" / "sessions"


def is_processed(uuid: str, brain_root) -> bool:
    """해당 uuid 세션이 처리 완료로 마킹되어 있으면 True."""
    return (_marks_dir(brain_root) / f"{uuid}.json").exists()


def mark_processed(uuid: str, brain_root, note: str | None = None) -> dict:
    """처리 완료 마킹 — 같은 uuid 재호출은 덮어쓴다(재실행 안전)."""
    d = _marks_dir(brain_root)
    d.mkdir(parents=True, exist_ok=True)
    record = {
        "uuid": uuid,
        "processed_at": now_kst(),
        "note": note,
    }
    (d / f"{uuid}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return record


def _summarize(path: Path) -> dict:
    cwd = None
    started_at = None
    message_count = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue  # 깨진 라인은 집계에서 제외(스캔은 보수적으로 계속)
            if cwd is None and payload.get("cwd"):
                cwd = payload["cwd"]
            if payload.get("type") in _MESSAGE_TYPES:
                message_count += 1
                if started_at is None:
                    started_at = payload.get("timestamp")
    return {
        "uuid": path.stem,
        "path": str(path),
        "cwd": cwd,
        "started_at": started_at,
        "message_count": message_count,
    }
