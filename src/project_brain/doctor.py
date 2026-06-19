"""doctor — 의존성·백엔드·프로젝트 상태 진단 (hwi_PKM doctor 패턴).

required: 엔진이 돌기 위한 환경(파이썬·필수 패키지·FTS5·sqlite-vec).
optional: 품질·프로젝트 상태(mecab·임베딩 모델 캐시·config·코퍼스·색인·골든셋)
          — 글로벌 설치 직후(프로젝트 밖)에는 실패가 정상이라 rc에 안 들어간다.

--download(diagnose(download=True))는 실모델을 한 번 로드해 캐시를 채운다.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from project_brain.config import load_config

# bge-m3의 HuggingFace 캐시 디렉토리 이름 (sentence-transformers가 받아두는 위치).
_MODEL_CACHE_DIRNAME = "models--BAAI--bge-m3"


def _check(name: str, severity: str, fn) -> dict:
    try:
        ok, detail = fn()
    except Exception as exc:  # 진단은 죽지 않고 실패로 기록한다.
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    return {"name": name, "ok": bool(ok), "severity": severity, "detail": detail}


def _import_check(module: str):
    def fn():
        __import__(module)
        return True, "import OK"
    return fn


def _fts5_check():
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(c)")
        return True, "FTS5 사용 가능"
    finally:
        conn.close()


def _sqlite_vec_check():
    import sqlite_vec

    conn = sqlite3.connect(":memory:")
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        return True, "sqlite-vec 확장 로드 OK"
    finally:
        conn.close()


def _tokenizer_check():
    from project_brain.tokenize_ko import active_backend

    backend = active_backend()
    # 정규식 폴백으로도 동작은 하지만 한국어 품질이 떨어진다 — 백엔드 이름을 그대로 보고.
    return backend in ("mecab-ko", "kiwipiepy"), f"활성 백엔드: {backend}"


def _model_cache_check(download: bool):
    def fn():
        if download:
            from project_brain.embedder import get_embedder

            emb = get_embedder(stub=False)
            emb.embed_many(["다운로드 확인"])
            return True, f"실모델 로드 OK ({emb.model_name})"
        hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
        cached = (hf_home / "hub" / _MODEL_CACHE_DIRNAME).exists()
        return cached, (
            "모델 캐시 있음" if cached
            else "모델 캐시 없음 — `project-brain doctor --download`로 미리 받거나 첫 색인 때 자동 다운로드"
        )
    return fn


def _project_checks(start) -> list[dict]:
    cfg = load_config(start=start)
    if cfg is None:
        return [_check("config", "optional",
                       lambda: (False, "config(.project-brain.json) 없음 — `project-brain install`"))]
    checks = [_check("config", "optional", lambda: (True, str(cfg["path"])))]

    def corpus():
        from project_brain.store import BrainStore

        if not (cfg["brain_root"] / "objects").exists():
            return False, f"코퍼스 없음: {cfg['brain_root']}"
        store = BrainStore.load(cfg["brain_root"])
        return True, f"객체 {len(list(store.all()))}개"

    def index():
        if not cfg["db"].exists():
            return False, f"색인 없음: {cfg['db']} — `project-brain index rebuild`"
        conn = sqlite3.connect(str(cfg["db"]))
        try:
            rows = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            return True, f"색인 {rows}행"
        finally:
            conn.close()

    def scenarios():
        from project_brain.eval_harness import load_scenarios

        if not cfg["scenarios"].exists():
            return False, f"골든셋 없음: {cfg['scenarios']}"
        return True, f"시나리오 {len(load_scenarios(cfg['scenarios']))}개"

    checks.append(_check("corpus", "optional", corpus))
    checks.append(_check("index", "optional", index))
    checks.append(_check("scenarios", "optional", scenarios))
    return checks


def diagnose(start=None, *, download: bool = False) -> dict:
    """진단 실행. 반환: {ok, checks:[{name, ok, severity, detail}]} —
    ok는 required 체크가 전부 통과했는지(optional 실패는 안 들어간다)."""
    checks = [
        _check("python", "required",
               lambda: (sys.version_info >= (3, 11), f"{sys.version.split()[0]}")),
        _check("numpy", "required", _import_check("numpy")),
        _check("sentence-transformers", "required",
               _import_check("sentence_transformers")),
        _check("fts5", "required", _fts5_check),
        _check("sqlite-vec", "required", _sqlite_vec_check),
        _check("tokenizer-ko", "optional", _tokenizer_check),
        _check("embed-model", "optional", _model_cache_check(download)),
    ]
    checks.extend(_project_checks(start))
    ok = all(c["ok"] for c in checks if c["severity"] == "required")
    return {"ok": ok, "checks": checks}
