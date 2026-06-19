"""FTS 색인 + 벡터 색인 빌드 + BM25/벡터 검색 (스펙 §3.3·§4·§6, 슬라이스 2·3).

spec: docs/superpowers/specs/2026-06-10-project-brain-search-layer-design.md

색인 DB는 SQLite. brain/ 객체에서 표면(surface.extract_surface)을 뽑아 토큰화
(tokenize_ko.tokenize)한 뒤, 사전 형태소 분리된 공백 결합 텍스트를 FTS5(unicode61)에
색인한다(§3.2). 색인과 쿼리가 같은 tokenize() 한 함수만 쓰므로 대칭이 보장된다(§6).

벡터(슬라이스 3): 표면 텍스트의 ★토큰화 전 원문★을 임베딩해 documents_vec(vec0,
FLOAT[1024])에 저장한다 — 임베딩은 형태소 분리 전 자연문이 적합하다(§3.3). vec0는
rowid 기반이라 documents 행마다 정수 rowid(row_id 컬럼)를 부여해 KNN 결과를
object_id로 되짚는다. embedder가 주어질 때만 벡터를 색인한다(embedder=None이면 FTS만).

★재생성 가능 = 1급 불변조건★(§4): 전체 재구축은 DB 파일을 삭제 후 재생성한다.
색인은 진실의 원본(SoR)이 아니라 brain/에서 따라 만드는 로컬 파생물이다 — DB 삭제는
데이터 손실이 아니다.
"""

import hashlib
import math
import sqlite3
from pathlib import Path

from project_brain.config import resolve_brain_root, resolve_db_path
from project_brain.embedder import EMBED_DIM
from project_brain.lint import projection_is_fresh
from project_brain.raw_chunks import RAW_KIND, RAW_STATUS, iter_raw_sources
from project_brain.store import BrainStore
from project_brain.surface import EXTRACTOR_VERSION, content_hash, extract_surface
from project_brain.tokenize_ko import active_backend, tokenize


class StaleIndexError(RuntimeError):
    """색인이 코퍼스/엔진과 안 맞아 rebuild가 해결책인 오류 — cli가 정상 안내로 처리."""


# 색인 스키마 자체의 버전(테이블 구조 변경 시 올린다 — meta 불일치 감지용).
# v2: documents.row_id 컬럼 + documents_vec(vec0) 추가(슬라이스 3 벡터 색인).
# v3: documents.surface_text 컬럼 + raw 청크 행(§2.2 raw 본문 색인 — raw 청크는
#     store에 없는 행이라 "원문 발췌"용 원문을 색인이 직접 운반해야 한다).
# v4: meta.corpus_fingerprint 추가 — 신선도 가드 1/2(§7). rebuild 시점의
#     색인 대상 전체(객체 표면 + raw 청크)를 sha256으로 기록해 두고, Task 5에서
#     검색 시점에 비교해 낡은 색인을 명확히 거부한다.
# (EMBED_DIM은 embedder.py와 일치해야 한다 — vec0 FLOAT[1024].)
SCHEMA_VERSION = 4

# 벡터 거리값 반올림 자릿수(§5 결정론 가드 — top-K 경계 흔들림 완화).
_DISTANCE_ROUND = 6

# 기본 색인 DB 경로는 프로젝트 config(.project-brain.json)에서 해석한다(§4).
# .brain-local/은 gitignore된 로컬 파생물.


def _vec_connect(db_path: str) -> sqlite3.Connection:
    """sqlite-vec 확장을 로드한 연결을 만든다(§3.3·§11).

    vec0 가상 테이블을 만들거나 KNN을 쓰려면 enable_load_extension + sqlite_vec.load가
    필요하다. import 실패는 명확한 에러로 알린다(§11 venv 전제 — auto_worker venv).
    """
    try:
        import sqlite_vec  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "sqlite-vec 미설치 — project-brain이 설치된 환경에서 실행해야 한다"
            "(스펙 §5·§11). `pip install sqlite-vec`."
        ) from exc
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return _vec_connect(str(db_path))


def _create_schema(conn: sqlite3.Connection) -> None:
    # documents: 원본 객체 메타 + 토큰화 텍스트(증분 비교는 content_hash로).
    # context_id는 §2.1 행 메타 — 슬라이스 3+의 scope 후처리(over-fetch 후 필터)가
    # store 재로드 없이 행만으로 거를 수 있게 동반한다(2026-06-10 리뷰 반영).
    # row_id(v2): vec0가 rowid 기반이라 KNN 결과를 object_id로 되짚는 정수 키.
    # surface_text(v3): 토큰화 전 원문 표면 — raw 청크는 store에 없는 행이라
    # recall이 "원문 발췌"를 보여주려면 색인이 원문을 직접 들고 있어야 한다(§2.2).
    conn.execute(
        "CREATE TABLE documents ("
        "row_id INTEGER PRIMARY KEY, object_id TEXT UNIQUE, kind TEXT, status TEXT, "
        "context_id TEXT, content_hash TEXT, tokenized_text TEXT, surface_text TEXT)"
    )
    # documents_fts: 사전 형태소 분리된 공백 결합 텍스트를 unicode61로 색인(§3.2).
    # object_id는 매칭에 안 쓰므로 UNINDEXED.
    conn.execute(
        "CREATE VIRTUAL TABLE documents_fts USING fts5("
        "object_id UNINDEXED, tokenized_text, tokenize='unicode61')"
    )
    # documents_vec(v2): 표면 원문 임베딩(1024차원 L2 정규화, §3.3). rowid는 documents.row_id.
    conn.execute(
        f"CREATE VIRTUAL TABLE documents_vec USING vec0(embedding FLOAT[{EMBED_DIM}])"
    )
    # meta: 단일 행. embed_model은 embedder 주입 시 모델명, 없으면 빈 값.
    # corpus_fingerprint(v4): 색인 대상 전체(객체 표면 + raw 청크) sha256 — §7 신선도 가드.
    conn.execute(
        "CREATE TABLE meta ("
        "schema_version INTEGER, embed_model TEXT, tokenizer TEXT, "
        "extractor_version INTEGER, corpus_fingerprint TEXT)"
    )


def rebuild(brain_root=None, db_path=None, embedder=None) -> dict:
    """brain/ 전 객체에서 FTS(+벡터) 색인을 전체 재구축한다(§4).

    ★전체 재구축 = DB 삭제 후 재생성★ — 재생성 가능 1급 불변조건. extract_surface가
    None을 돌려주는 객체(색인 제외 kind·빈 표면)는 색인하지 않는다.

    brain_root/db_path 미지정이면 config(.project-brain.json)에서 해석한다.

    embedder: 주면 표면 원문(토큰화 전 §3.3)을 임베딩해 documents_vec에 저장한다.
    None이면 FTS만 색인(벡터 테이블은 비어 있음) — 무회귀 FTS 테스트·CI용. embedder가
    있으면 표면들을 한 번에 batch 임베딩하고 meta.embed_model에 모델명을 기록한다(§4).

    반환: {indexed, total_objects, skipped, tokenizer, embed_model, db} 통계.
    """
    db_path = resolve_db_path(db_path)
    if db_path.exists():
        db_path.unlink()

    # resolve 결과를 양쪽(store 로드 + raw 소스 순회)이 같이 쓴다 — 원래 인자
    # (None일 수 있음)를 raw 순회에 흘리면 안 된다.
    brain_root = resolve_brain_root(brain_root)
    store = BrainStore.load(brain_root)
    tokenizer = active_backend()
    embed_model = embedder.model_name if embedder is not None else ""

    conn = _connect(db_path)
    try:
        _create_schema(conn)

        # 색인 대상을 먼저 모은다(임베딩은 배치라 표면 원문을 따로 보관). row_id는
        # 등장 순서대로 1부터 부여 — store.all()은 dict 삽입 순서라 결정론(멱등).
        indexed = 0
        total = 0
        pending_vectors: list[tuple[int, str]] = []  # (row_id, 표면 원문)
        for obj in store.all():
            total += 1
            # 낡은 ContextProjection(구성 객체가 바뀌어 source_content_hash 불일치)은
            # 색인 제외 — 이전 착수 브리핑이 더는 정확하지 않다. fingerprint도 동일.
            if obj.get("kind") == "ContextProjection" and not projection_is_fresh(store, obj):
                continue
            surface = extract_surface(obj, store)
            if surface is None:
                continue
            tokens = tokenize(surface)
            if not tokens:
                continue
            tokenized_text = " ".join(tokens)
            indexed += 1
            row_id = indexed
            conn.execute(
                "INSERT INTO documents (row_id, object_id, kind, status, context_id, "
                "content_hash, tokenized_text, surface_text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (row_id, obj["id"], obj.get("kind"), obj.get("status"),
                 obj.get("context_id"), content_hash(obj, store), tokenized_text, surface),
            )
            conn.execute(
                "INSERT INTO documents_fts (object_id, tokenized_text) VALUES (?, ?)",
                (obj["id"], tokenized_text),
            )
            if embedder is not None:
                pending_vectors.append((row_id, surface))
        object_indexed = indexed
        # raw 원문 청크(§2.2): raw/sources/<ctx>/*.md를 같은 색인에 넣는다 —
        # kind=raw_chunk, status=raw, 원문은 surface_text로 운반(store에 없는 행).
        # content_hash는 객체 행의 공식(표면+status SHA-256)과 동형으로 텍스트에서 계산.
        raw_chunks = 0
        for ch in iter_raw_sources(Path(brain_root)):
            tokens = tokenize(ch["text"])
            if not tokens:
                continue
            tokenized_text = " ".join(tokens)
            indexed += 1
            raw_chunks += 1
            row_id = indexed
            chunk_hash = hashlib.sha256(
                (ch["text"] + "\n" + RAW_STATUS).encode("utf-8")).hexdigest()
            conn.execute(
                "INSERT INTO documents (row_id, object_id, kind, status, context_id, "
                "content_hash, tokenized_text, surface_text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (row_id, ch["chunk_id"], RAW_KIND, RAW_STATUS,
                 ch["context_id"], chunk_hash, tokenized_text, ch["text"]),
            )
            conn.execute(
                "INSERT INTO documents_fts (object_id, tokenized_text) VALUES (?, ?)",
                (ch["chunk_id"], tokenized_text),
            )
            if embedder is not None:
                pending_vectors.append((row_id, ch["text"]))
        # 벡터는 ★토큰화 전 원문 표면★을 embed_many로 한 번에 배치 임베딩(§3.3) —
        # 실모델(bge-m3)에서 객체당 encode 1회보다 훨씬 빠르다(2026-06-10 리뷰 반영:
        # 주석만 "배치"라던 것을 실구현으로).
        if embedder is not None and pending_vectors:
            vectors = embedder.embed_many([s for _, s in pending_vectors])
            conn.executemany(
                "INSERT INTO documents_vec (rowid, embedding) VALUES (?, ?)",
                [(row_id, _serialize(v))
                 for (row_id, _), v in zip(pending_vectors, vectors)],
            )
        # 지문은 색인 대상을 모두 INSERT한 뒤 계산해 meta 단일 행에 기록한다(§7).
        fingerprint = compute_corpus_fingerprint(store, Path(brain_root))
        conn.execute(
            "INSERT INTO meta (schema_version, embed_model, tokenizer, "
            "extractor_version, corpus_fingerprint) VALUES (?, ?, ?, ?, ?)",
            (SCHEMA_VERSION, embed_model, tokenizer, EXTRACTOR_VERSION, fingerprint),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        # indexed = 객체 행 + raw 청크 행(전체 색인 행 수). skipped는 객체 기준.
        "indexed": indexed,
        "total_objects": total,
        "skipped": total - object_indexed,
        "raw_chunks": raw_chunks,
        "tokenizer": tokenizer,
        "embed_model": embed_model,
        "db": str(db_path),
    }


def _serialize(vec) -> bytes:
    """numpy 1024차원 벡터를 vec0가 받는 float32 바이트로 직렬화한다."""
    import sqlite_vec  # type: ignore

    return sqlite_vec.serialize_float32([float(x) for x in vec])


def _escape_token(token: str) -> str:
    """FTS5 토큰을 안전하게 따옴표로 감싼다. 내부 따옴표는 두 번으로 이스케이프.

    토큰을 각각 "..." 개별 인용으로 묶으면 FTS5 특수문자(따옴표·연산자 등)가
    구문으로 해석되지 않는다(§4 요구). prefix는 쓰지 않는다(§6). 단, 구분자를
    품은 복합 원형 토큰(예: "a/b/c.cpp", "x::y")은 인용돼도 unicode61이 다중
    토큰으로 재분리해 사실상 phrase로 해석된다 — 같은 tokenize()가 조각 토큰을
    항상 OR로 동반시키고 색인측도 동일하게 전개하므로 재현율 손실·색인-쿼리
    비대칭은 없다(2026-06-10 리뷰 실측, 스펙 §6 보강).
    """
    return '"' + token.replace('"', '""') + '"'


def _read_meta(conn: sqlite3.Connection) -> dict | None:
    try:
        row = conn.execute(
            "SELECT schema_version, embed_model, tokenizer, extractor_version, "
            "corpus_fingerprint FROM meta LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        # 구버전(v3 이하) meta는 corpus_fingerprint 컬럼 자체가 없어 SELECT가
        # 버전 가드보다 먼저 터진다(2026-06-11 실사고). 버전만 읽어 돌려주면
        # _guard_schema_version이 rebuild 안내로 거부한다. meta 테이블 자체가
        # 없는 DB는 여기서도 OperationalError — 기존 동작 그대로 둔다.
        row = conn.execute("SELECT schema_version FROM meta LIMIT 1").fetchone()
        if row is None:
            return None
        return {"schema_version": row[0], "embed_model": None,
                "tokenizer": None, "extractor_version": None,
                "corpus_fingerprint": None}
    if row is None:
        return None
    return {"schema_version": row[0], "embed_model": row[1],
            "tokenizer": row[2], "extractor_version": row[3],
            "corpus_fingerprint": row[4]}


def compute_corpus_fingerprint(store, brain_root) -> str:
    """색인 대상 전체(객체 표면 + raw 청크)의 결정론 지문 — 신선도 가드(§7)용.

    rebuild가 색인하는 것과 같은 입력(extract_surface 표면 + iter_raw_sources
    청크)을 같은 규칙으로 직렬화해 sha256. 색인에 반영 안 되는 변경(예: 색인
    제외 kind의 필드)은 지문도 안 바뀐다 — 가드는 "색인이 코퍼스의 색인 대상
    내용과 일치하나"만 묻는다.

    rebuild의 두 필터를 모두 거울처럼 적용한다: 표면 None 제외 + 토큰화가 빈
    행 제외(스펙 리뷰 반영 — 빈 토큰 행을 지문에 넣으면 색인엔 없는 객체의
    변경이 지문만 바꿔 가드가 거짓 양성을 낸다). 지문은 이제 토큰화 비용을
    포함한다(rebuild와 같은 필터 — 색인 집합과 동치 보장).
    """
    rows = []
    for obj in store.all():
        # rebuild와 동일하게 낡은 ContextProjection을 지문 입력에서도 뺀다 — 두 곳이
        # 같은 입력을 봐야 신선도 가드가 어긋나지 않는다.
        if obj.get("kind") == "ContextProjection" and not projection_is_fresh(store, obj):
            continue
        surface = extract_surface(obj, store)
        if surface is None or not tokenize(surface):
            continue
        rows.append(f"{obj['kind']}\t{obj['id']}\t{obj.get('status', '')}\t{surface}")
    for ch in iter_raw_sources(Path(brain_root)):
        if not tokenize(ch["text"]):
            continue
        rows.append(f"{RAW_KIND}\t{ch['chunk_id']}\t{RAW_STATUS}\t{ch['text']}")
    payload = "\n".join(sorted(rows))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_meta_fingerprint(db_path) -> "str | None":
    """색인 meta의 코퍼스 지문. 색인/meta/컬럼이 없으면 None."""
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        row = _read_meta(conn)
        return row["corpus_fingerprint"] if row else None
    except (sqlite3.OperationalError, KeyError, IndexError):
        return None
    finally:
        conn.close()


def _guard_schema_version(meta_row) -> None:
    """§4 "불일치 감지 시 rebuild 안내" — stale 색인(예: 구버전 DDL)이 원시 sqlite
    에러나 무경고 빈 결과로 조용히 깨지지 않게 명확히 거부한다(2026-06-10 슬라이스 3
    리뷰 major 반영)."""
    if meta_row is not None and meta_row["schema_version"] != SCHEMA_VERSION:
        raise StaleIndexError(
            f"색인 스키마 버전 불일치: 색인 v{meta_row['schema_version']} ≠ "
            f"코드 v{SCHEMA_VERSION} — `cli index rebuild`로 재구축 필요(§4)."
        )


# BM25 표준 계수(scoped 재계산 — Okapi 표준값. FTS5 bm25() 기본값과 동일 계열).
_BM25_K1 = 1.2
_BM25_B = 0.75


def _bm25_rank_scoped(doc_token_lists, query_tokens):
    """후보 집합 안에서만 df·avgdl을 계산하는 표준 BM25 — 순수 함수(단위 테스트용).

    doc_token_lists: [(object_id, [token, ...]), ...] — 후보 전체(매칭 여부 무관).
    query_tokens: 질의 토큰 집합(중복 제거).
    반환: 질의 토큰을 1개 이상 포함한 문서만 [(object_id, score)] —
          점수 내림차순 → 동점 object_id 오름차순(§5 결정론), 점수 6자리 반올림.

    IDF는 ln(1 + (N - df + 0.5)/(df + 0.5)) — 항상 양수인 Lucene 형태. FTS5
    bm25()(Okapi 원형, df > N/2면 음수)와 식이 달라도 무방하다: recall은 채널
    결과의 ★순서만★ 소비한다(RRF가 rank만 씀).
    """
    n_docs = len(doc_token_lists)
    if n_docs == 0:
        return []
    avgdl = sum(len(toks) for _, toks in doc_token_lists) / n_docs
    df = {t: 0 for t in query_tokens}
    for _, toks in doc_token_lists:
        tok_set = set(toks)
        for t in query_tokens:
            if t in tok_set:
                df[t] += 1
    scored = []
    for object_id, toks in doc_token_lists:
        tf: dict[str, int] = {}
        for tok in toks:
            if tok in query_tokens:
                tf[tok] = tf.get(tok, 0) + 1
        if not tf:
            continue
        dl = len(toks)
        score = 0.0
        for t, freq in tf.items():
            idf = math.log(1.0 + (n_docs - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * (freq * (_BM25_K1 + 1.0)) / (
                freq + _BM25_K1 * (1.0 - _BM25_B + _BM25_B * dl / avgdl))
        scored.append((object_id, round(score, 6)))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored


def search_bm25_scoped(db_path, query: str, scope: str, top_n: int = 50) -> dict:
    """scope 후보(context_id=scope, raw 제외) 안에서만 BM25를 재계산한다(§3.2 scoped 레인).

    s1 회귀(2026-06-12)의 근본 해법: FTS5 bm25()는 전역 df 기반이라 scope 밖
    적재가 scope 안 순위를 흔든다. 후보 집합의 tokenized_text로 df·avgdl을 그
    안에서만 계산하면 scope 밖에 무엇이 적재되든 결과가 수학적으로 불변이다
    (불변식 테스트가 가드). 후보는 컨텍스트당 수백 행 — 파이썬 직접 계산으로
    충분하고 FTS5 색인 구조는 읽지도 않는다(documents 테이블만 조회).

    반환 형태는 search_bm25와 대칭({results, warnings}). ★점수 방향이 다르다★ —
    여기는 클수록 좋음(표준 BM25), search_bm25는 FTS5 그대로(작을수록 좋음).
    recall은 채널 결과의 순서만 소비하므로(RRF가 rank만 씀) 영향 없다.
    """
    db_path = Path(db_path)
    tokens = tokenize(query)
    warnings: list[str] = []

    conn = sqlite3.connect(str(db_path))
    try:
        meta_row = _read_meta(conn)
        _guard_schema_version(meta_row)
        indexed_tokenizer = meta_row["tokenizer"] if meta_row else None
        query_tokenizer = active_backend()
        if indexed_tokenizer is not None and indexed_tokenizer != query_tokenizer:
            warnings.append(
                f"tokenizer 비대칭: 색인={indexed_tokenizer} 쿼리={query_tokenizer} "
                "— 색인과 쿼리 토크나이저가 달라 형태소 매칭 품질이 떨어질 수 있음(§6)"
            )
        if not tokens:
            return {"results": [], "warnings": warnings}
        # RAW·ContextProjection 제외(2026-06-17) — raw 청크는 별도 발췌 레인,
        # projection은 별도 재사용 레인이라 scope 객체 BM25 후보에 섞이면 안 된다.
        # Insight는 객체라 의도적으로 scope 레인에 남긴다.
        rows = conn.execute(
            "SELECT object_id, kind, status, context_id, tokenized_text, surface_text "
            "FROM documents WHERE context_id = ? AND kind NOT IN (?, ?) ORDER BY object_id",
            (scope, RAW_KIND, "ContextProjection"),
        ).fetchall()
    finally:
        conn.close()

    doc_token_lists = [(r[0], (r[4] or "").split()) for r in rows]
    ranked = _bm25_rank_scoped(doc_token_lists, set(tokens))

    meta_by_id = {r[0]: r for r in rows}
    results = []
    for object_id, score in ranked[:top_n]:
        r = meta_by_id[object_id]
        results.append({
            "object_id": object_id, "kind": r[1], "status": r[2],
            "context_id": r[3], "score": score, "surface_text": r[5],
        })
    return {"results": results, "warnings": warnings}


def search_bm25(db_path, query: str, top_n: int = 50) -> dict:
    """쿼리를 같은 tokenize()로 토큰화해 FTS5 BM25로 검색한다(§6).

    ★FTS5 질의는 phrase/prefix 없이 토큰 OR만★(§6). bm25() 점수는 작을수록 좋음 —
    오름차순 정렬, 동률은 object_id 정렬로 결정론(§3.4).

    반환: {results: [{object_id, kind, status, context_id, score}], warnings: [...]}.
    색인 meta의 tokenizer와 쿼리 시점 active_backend()가 다르면 비대칭 경고를
    warnings에 담는다(§6 비대칭 가드).
    """
    db_path = Path(db_path)
    tokens = tokenize(query)
    warnings: list[str] = []

    conn = sqlite3.connect(str(db_path))
    try:
        meta_row = _read_meta(conn)
        _guard_schema_version(meta_row)
        indexed_tokenizer = meta_row["tokenizer"] if meta_row else None
        query_tokenizer = active_backend()
        if indexed_tokenizer is not None and indexed_tokenizer != query_tokenizer:
            warnings.append(
                f"tokenizer 비대칭: 색인={indexed_tokenizer} 쿼리={query_tokenizer} "
                "— 색인과 쿼리 토크나이저가 달라 형태소 매칭 품질이 떨어질 수 있음(§6)"
            )

        if not tokens:
            return {"results": [], "warnings": warnings}

        match_expr = " OR ".join(_escape_token(t) for t in tokens)
        # bm25(fts) 오름차순(작을수록 좋음) → 동률 object_id 정렬로 결정론 tie-break.
        rows = conn.execute(
            "SELECT f.object_id, d.kind, d.status, d.context_id, "
            "bm25(documents_fts) AS score, d.surface_text "
            "FROM documents_fts f JOIN documents d ON d.object_id = f.object_id "
            "WHERE documents_fts MATCH ? "
            "ORDER BY score ASC, f.object_id ASC LIMIT ?",
            (match_expr, top_n),
        ).fetchall()
    finally:
        conn.close()

    results = [
        {"object_id": r[0], "kind": r[1], "status": r[2], "context_id": r[3],
         "score": r[4], "surface_text": r[5]}
        for r in rows
    ]
    return {"results": results, "warnings": warnings}


def search_vector(db_path, query: str, top_n: int = 50, scope=None, embedder=None) -> dict:
    """쿼리를 임베딩해 documents_vec(vec0) KNN으로 검색한다(§3.3).

    ★색인 빌드와 같은 임베더 경로★를 써야 한다 — embedder 미지정이면 get_embedder()로
    동일 팩토리에서 만든다(stub/실모델은 환경 플래그·주입으로 통일, §5).

    ★scope 필터는 over-fetch 후 후처리★(§3.3): vec0는 WHERE를 못 받으므로 KNN을 넉넉히
    (top_n×4, 최소 200) 가져온 뒤 documents.context_id로 거른다 — store 재로드 없이
    documents 행만으로 거른다(§4 행 메타).

    거리는 6자리 반올림(§5 결정론 가드) → 동률 object_id 정렬. 반환 형태는 search_bm25와
    대칭({results, warnings}). results 원소: {object_id, kind, status, context_id, score}.
    score는 거리(작을수록 가까움).
    """
    db_path = Path(db_path)
    warnings: list[str] = []
    if embedder is None:
        from project_brain.embedder import get_embedder

        embedder = get_embedder()

    if not query:
        return {"results": [], "warnings": warnings}

    conn = _vec_connect(str(db_path))
    try:
        # §4 불일치 감지(2026-06-10 리뷰 major 반영): stale 스키마는 거부, 벡터 미색인
        # (FTS 전용 색인)·임베딩 모델 비대칭은 무경고로 의미 없는 결과를 돌려주는 대신
        # rebuild 안내 경고를 단다.
        meta_row = _read_meta(conn)
        _guard_schema_version(meta_row)
        indexed_model = meta_row["embed_model"] if meta_row else ""
        if not indexed_model:
            warnings.append(
                "벡터 미색인(embed_model 빈 값 — FTS 전용 색인): embedder와 함께 "
                "`cli index rebuild` 필요(§4)."
            )
            return {"results": [], "warnings": warnings}
        if indexed_model != embedder.model_name:
            warnings.append(
                f"embed_model 비대칭: 색인={indexed_model} 쿼리={embedder.model_name} "
                "— 같은 모델로 rebuild하지 않으면 KNN 거리가 의미 없음(§4·§5)."
            )

        vec = embedder.embed(query)
        over_fetch = max(top_n * 4, 200)

        # vec0 KNN: rowid·distance. scope가 있으면 over-fetch 후 documents.context_id로 후처리.
        rows = conn.execute(
            "SELECT v.rowid, v.distance, d.object_id, d.kind, d.status, d.context_id, "
            "d.surface_text "
            "FROM documents_vec v JOIN documents d ON d.row_id = v.rowid "
            "WHERE v.embedding MATCH ? AND k = ? "
            "ORDER BY v.distance",
            (_serialize(vec), over_fetch),
        ).fetchall()
    finally:
        conn.close()

    scoped = []
    for r in rows:
        _, distance, object_id, kind, status, context_id, surface_text = r
        if scope is not None and context_id != scope:
            continue
        scoped.append({
            "object_id": object_id, "kind": kind, "status": status,
            "context_id": context_id,
            # 거리 6자리 반올림 → top-K 경계 흔들림 완화(§5).
            "score": round(float(distance), _DISTANCE_ROUND),
            "surface_text": surface_text,
        })

    # 거리 오름차순(가까울수록 앞) → 동률 object_id 정렬로 결정론(§5).
    scoped.sort(key=lambda h: (h["score"], h["object_id"]))
    return {"results": scoped[:top_n], "warnings": warnings}
