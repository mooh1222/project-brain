"""FTS 색인 빌드 + BM25 검색 검증 (스펙 §4·§6, 슬라이스 2).

spec: docs/superpowers/specs/2026-06-10-project-brain-search-layer-design.md

합성 객체(test_surface.py 헬퍼 패턴)를 tmp brain root에 BrainStore.save_object로
적재 → rebuild → search_bm25로 한국어/심볼 질의 적중·결정론·멱등·색인 제외를
검증한다. 정규식 폴백을 강제해 mecab 없는 환경에서도 결정론으로 돈다.
(실코퍼스 행 수 가드는 데이터 레포 쪽 CLI 가드로 옮겨졌다 — 2-레포 분리.)
"""

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_brain.embedder import EMBED_DIM, StubEmbedder
from project_brain.objbase import base
from project_brain.search_index import (
    SCHEMA_VERSION,
    StaleIndexError,
    _bm25_rank_scoped,
    rebuild,
    search_bm25,
    search_bm25_scoped,
    search_vector,
)
from project_brain.store import BrainStore
from project_brain.surface import EXTRACTOR_VERSION
from project_brain import tokenize_ko

T = "2026-06-04T00:00:00Z"


def _b(obj):
    return base(obj, tags=["neutral"], created_at=T, updated_at=T)


def glossary_term(tid, *, term, definition="정의", status="reviewed", synonyms=None,
                  context_id="context.neutral"):
    obj = {
        "id": tid, "kind": "GlossaryTerm", "status": status, "truth_role": "domain",
        "title": f"Term: {term}", "context_id": context_id,
        "term": term, "definition": definition,
        "evidence_refs": ["ev.x"] if status == "reviewed" else [],
    }
    if synonyms is not None:
        obj["synonyms"] = synonyms
    if status == "candidate":
        obj["candidate"] = {"candidate_state": "ready_for_review", "candidate_source": "spec"}
    return _b(obj)


def code_locator(cid, *, path, symbol):
    return _b({
        "id": cid, "kind": "CodeLocator", "status": "reviewed", "truth_role": "reference",
        "title": "코드", "repo": "demoapp", "path": path, "symbol": symbol,
        "locator_source": "rg", "verified_at": T,
    })


def review_record(rid):
    # 색인 제외 kind(§2.1) — 색인에 들어가면 안 됨.
    return _b({
        "id": rid, "kind": "ReviewRecord", "status": "reviewed", "truth_role": "review",
        "title": "검수", "reviewer": "auto", "reviewed_at": T, "verdict": "approved",
        "target_object_id": "g.x",
    })


def projection(pid, *, context_id, title, reuse_payload, source_object_ids=None,
               status="candidate", source_objects=None):
    sids = source_object_ids or ["g.d1"]
    # source_objects(구성 객체 dict들)를 주면 fresh source_content_hash를 lint와
    # 같은 공식으로 계산한다 — A6 신선도 가드가 색인에서 빼지 않도록. 안 주면 옛
    # placeholder("x")라 stale 취급된다(낡음 검사 자체를 보는 테스트용).
    if source_objects is not None:
        from project_brain.hash_utils import source_content_hash as _sch
        content_hash = _sch(source_objects)
    else:
        content_hash = "x"
    return _b({
        "id": pid, "kind": "ContextProjection", "status": status, "truth_role": "index",
        "title": title, "context_id": context_id,
        "format": "prompt_payload", "reuse_payload": reuse_payload,
        "output_locator": f"indexes/context_projections/{pid}.txt",
        "source_object_ids": sids,
        "source_content_hash": content_hash, "projection_hash": "y",
        "generated_at": T, "generated_by": "test",
        "stale_policy": "fail_on_manual_edit",
        "evidence_refs": [],
    })


def build_store_dir(tmp: Path, objs) -> Path:
    for obj in objs:
        BrainStore.save_object(tmp, obj)
    return tmp


class RebuildTest(unittest.TestCase):
    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"

    def tearDown(self):
        self._td.cleanup()

    def test_rebuild_indexes_only_supported_kinds(self):
        build_store_dir(self.brain, [
            glossary_term("g.race", term="레이스", definition="카약 경주"),
            code_locator("code.foo", path="a/b/C.cpp", symbol="onClickNewRace"),
            review_record("review.x"),  # 색인 제외
        ])
        stats = rebuild(self.brain, self.db)
        self.assertEqual(stats["indexed"], 2)  # 용어 1 + 코드 1, ReviewRecord 제외
        self.assertEqual(stats["total_objects"], 3)
        self.assertEqual(stats["skipped"], 1)

    def test_rows_carry_context_id(self):
        # §2.1 행 메타 — 슬라이스 3+ scope 후처리가 store 재로드 없이 행만으로
        # 거를 수 있어야 한다(리뷰 반영: §2.1↔§4 모순을 §2.1 쪽으로 정합).
        build_store_dir(self.brain, [glossary_term("g.race", term="레이스")])
        rebuild(self.brain, self.db)
        conn = sqlite3.connect(str(self.db))
        try:
            row = conn.execute(
                "SELECT context_id FROM documents WHERE object_id = 'g.race'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], "context.neutral")
        out = search_bm25(self.db, "레이스")
        self.assertEqual(out["results"][0]["context_id"], "context.neutral")

    def test_rebuild_writes_meta(self):
        build_store_dir(self.brain, [glossary_term("g.race", term="레이스")])
        rebuild(self.brain, self.db)
        conn = sqlite3.connect(str(self.db))
        try:
            row = conn.execute(
                "SELECT schema_version, embed_model, tokenizer, extractor_version, "
                "corpus_fingerprint FROM meta"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], SCHEMA_VERSION)
        self.assertEqual(row[1], "")  # embedder=None(FTS 전용 rebuild)이라 빈 값
        self.assertEqual(row[2], tokenize_ko.active_backend())
        self.assertEqual(row[3], EXTRACTOR_VERSION)
        # v4: corpus_fingerprint가 64자리 sha256 hex로 기록됨(§7 신선도 가드).
        self.assertIsNotNone(row[4])
        self.assertEqual(len(row[4]), 64)

    def test_rebuild_deletes_and_recreates_db(self):
        # 첫 빌드 → 객체 줄여 재빌드하면 옛 행이 남지 않는다(DB 삭제 후 재생성, §4)
        build_store_dir(self.brain, [
            glossary_term("g.race", term="레이스"),
            glossary_term("g.reward", term="보상"),
        ])
        rebuild(self.brain, self.db)
        # g.reward 파일 삭제 후 재빌드
        (self.brain / "objects" / "domain" / "g.reward.json").unlink()
        stats = rebuild(self.brain, self.db)
        self.assertEqual(stats["indexed"], 1)
        conn = sqlite3.connect(str(self.db))
        try:
            ids = [r[0] for r in conn.execute("SELECT object_id FROM documents").fetchall()]
        finally:
            conn.close()
        self.assertEqual(ids, ["g.race"])

    def test_rebuild_idempotent(self):
        # 두 번 rebuild → 같은 documents 행 집합(멱등)
        build_store_dir(self.brain, [
            glossary_term("g.race", term="레이스", definition="카약 경주"),
            code_locator("code.foo", path="a/b/C.cpp", symbol="onClickNewRace"),
        ])
        rebuild(self.brain, self.db)

        def snapshot():
            conn = sqlite3.connect(str(self.db))
            try:
                return conn.execute(
                    "SELECT object_id, kind, status, content_hash, tokenized_text "
                    "FROM documents ORDER BY object_id"
                ).fetchall()
            finally:
                conn.close()

        first = snapshot()
        rebuild(self.brain, self.db)
        self.assertEqual(first, snapshot())


class SearchBM25Test(unittest.TestCase):
    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        build_store_dir(self.brain, [
            glossary_term("g.race", term="레이스", definition="카약 경주 진행"),
            glossary_term("g.reward", term="보상", definition="레이스 종료 보상 지급"),
            code_locator("code.new", path="main/map/MinaKayak.cpp",
                         symbol="onClickNewRace"),
            review_record("review.x"),
        ])
        rebuild(self.brain, self.db)

    def tearDown(self):
        self._td.cleanup()

    def test_korean_query_hits(self):
        out = search_bm25(self.db, "카약 경주 보상")
        ids = {r["object_id"] for r in out["results"]}
        self.assertIn("g.race", ids)
        self.assertIn("g.reward", ids)

    def test_symbol_query_hits(self):
        # camelCase 심볼 질의가 on/click/new/race 토큰으로 코드 위치에 적중
        out = search_bm25(self.db, "onClickNewRace")
        ids = {r["object_id"] for r in out["results"]}
        self.assertIn("code.new", ids)

    def test_excluded_kind_not_in_results(self):
        out = search_bm25(self.db, "검수")  # ReviewRecord 표면이었던 텍스트
        ids = {r["object_id"] for r in out["results"]}
        self.assertNotIn("review.x", ids)

    def test_result_shape(self):
        out = search_bm25(self.db, "레이스")
        self.assertIn("results", out)
        self.assertIn("warnings", out)
        for r in out["results"]:
            self.assertEqual(
                set(r.keys()),
                {"object_id", "kind", "status", "context_id", "score", "surface_text"},
            )

    def test_deterministic_ordering(self):
        a = search_bm25(self.db, "레이스 보상")["results"]
        b = search_bm25(self.db, "레이스 보상")["results"]
        self.assertEqual(a, b)

    def test_empty_query_returns_empty(self):
        out = search_bm25(self.db, "!!!")  # 토큰 0개로 분해되는 질의
        self.assertEqual(out["results"], [])

    def test_top_n_limit(self):
        out = search_bm25(self.db, "레이스 보상 카약", top_n=1)
        self.assertLessEqual(len(out["results"]), 1)


class MetaGuardTest(unittest.TestCase):
    """§4 "불일치 감지 시 rebuild 안내" 가드(2026-06-10 슬라이스 3 리뷰 major 반영).

    stale 스키마·FTS 전용 색인에 벡터 질의·임베딩 모델 비대칭이 원시 sqlite 에러나
    무경고 빈/엉터리 결과로 조용히 깨지지 않는지 본다."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        build_store_dir(self.brain, [glossary_term("g.race", term="레이스")])

    def tearDown(self):
        self._td.cleanup()

    def test_schema_version_mismatch_raises_rebuild_guidance(self):
        rebuild(self.brain, self.db, embedder=StubEmbedder())
        conn = sqlite3.connect(str(self.db))
        try:
            conn.execute("UPDATE meta SET schema_version = 1")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(RuntimeError) as ctx:
            search_bm25(self.db, "레이스")
        self.assertIn("rebuild", str(ctx.exception))
        with self.assertRaises(RuntimeError) as ctx:
            search_vector(self.db, "레이스", embedder=StubEmbedder())
        self.assertIn("rebuild", str(ctx.exception))

    def test_v3_meta_without_fingerprint_column_raises_rebuild_guidance(self):
        # 진짜 v3 색인은 meta에 corpus_fingerprint 컬럼 자체가 없다(2026-06-11
        # 4701 세션 실사고 모양). 버전 값 불일치보다 먼저 SELECT가 OperationalError로
        # 터지면 가드가 도달 불가 — 이 경우도 StaleIndexError + rebuild 안내여야 한다.
        rebuild(self.brain, self.db, embedder=StubEmbedder())
        conn = sqlite3.connect(str(self.db))
        try:
            conn.execute("ALTER TABLE meta RENAME TO meta_v4")
            conn.execute(
                "CREATE TABLE meta (schema_version INTEGER, embed_model TEXT, "
                "tokenizer TEXT, extractor_version INTEGER)"
            )
            conn.execute(
                "INSERT INTO meta SELECT schema_version, embed_model, tokenizer, "
                "extractor_version FROM meta_v4"
            )
            conn.execute("UPDATE meta SET schema_version = 3")
            conn.execute("DROP TABLE meta_v4")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(StaleIndexError) as ctx:
            search_bm25(self.db, "레이스")
        self.assertIn("rebuild", str(ctx.exception))
        with self.assertRaises(StaleIndexError) as ctx:
            search_vector(self.db, "레이스", embedder=StubEmbedder())
        self.assertIn("rebuild", str(ctx.exception))

    def test_vector_search_on_fts_only_index_warns_empty(self):
        # embedder 없이 rebuild(FTS 전용) → 벡터 질의는 빈 결과 + rebuild 안내 경고.
        rebuild(self.brain, self.db)
        out = search_vector(self.db, "레이스", embedder=StubEmbedder())
        self.assertEqual(out["results"], [])
        self.assertTrue(any("rebuild" in w for w in out["warnings"]))

    def test_embed_model_asymmetry_warns(self):
        rebuild(self.brain, self.db, embedder=StubEmbedder())

        class OtherEmbedder(StubEmbedder):
            model_name = "stub:other-model"

        out = search_vector(self.db, "레이스", embedder=OtherEmbedder())
        self.assertTrue(any("embed_model 비대칭" in w for w in out["warnings"]))


class RegexFallbackTest(unittest.TestCase):
    """정규식 폴백 강제 환경 시뮬레이션 — mecab 있는 환경에서도 결정론으로 돈다.

    rebuild/search_bm25는 tokenize(backend=None)를 쓰므로 모듈 전역 백엔드를
    'regex'로 고정해 폴백 경로를 검증한다.
    """

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        # 모듈 캐시 백엔드를 regex로 강제(스펙 §6 폴백 경로 가드).
        # 복원은 addCleanup으로 — setUp이 뒤에서 실패해도(rebuild 등) tearDown과
        # 달리 반드시 실행돼 전역 백엔드가 다른 테스트로 누수되지 않는다(리뷰 반영).
        self._saved_name = tokenize_ko._BACKEND_NAME
        self._saved_split = tokenize_ko._KOREAN_SPLITTER
        tokenize_ko._BACKEND_NAME = "regex"
        tokenize_ko._KOREAN_SPLITTER = tokenize_ko._regex_splitter
        self.addCleanup(self._restore_backend)
        build_store_dir(self.brain, [
            glossary_term("g.race", term="레이스", definition="카약 경주"),
            code_locator("code.new", path="a/b/C.cpp", symbol="onClickNewRace"),
        ])
        rebuild(self.brain, self.db)

    def _restore_backend(self):
        tokenize_ko._BACKEND_NAME = self._saved_name
        tokenize_ko._KOREAN_SPLITTER = self._saved_split

    def tearDown(self):
        self._td.cleanup()

    def test_meta_records_regex_tokenizer(self):
        conn = sqlite3.connect(str(self.db))
        try:
            tok = conn.execute("SELECT tokenizer FROM meta").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(tok, "regex")

    def test_korean_query_hits_under_regex(self):
        # regex 폴백은 한글 연속 통째 토큰 — "레이스"(통째)는 매칭됨
        out = search_bm25(self.db, "레이스")
        ids = {r["object_id"] for r in out["results"]}
        self.assertIn("g.race", ids)

    def test_symbol_query_hits_under_regex(self):
        # 심볼 분리는 백엔드 무관 결정론이라 regex 폴백에서도 동일하게 적중
        out = search_bm25(self.db, "onClickNewRace")
        ids = {r["object_id"] for r in out["results"]}
        self.assertIn("code.new", ids)


class TokenizerMismatchWarningTest(unittest.TestCase):
    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        build_store_dir(self.brain, [glossary_term("g.race", term="레이스")])
        rebuild(self.brain, self.db)

    def tearDown(self):
        self._td.cleanup()

    def test_mismatch_emits_warning(self):
        # 색인 meta tokenizer를 다른 값으로 바꿔 비대칭 경고 발동을 확인(§6 가드)
        conn = sqlite3.connect(str(self.db))
        try:
            conn.execute("UPDATE meta SET tokenizer = 'fake-tokenizer'")
            conn.commit()
        finally:
            conn.close()
        out = search_bm25(self.db, "레이스")
        self.assertTrue(out["warnings"])
        self.assertTrue(any("비대칭" in w for w in out["warnings"]))


class SchemaVersionTest(unittest.TestCase):
    def test_schema_version_is_4(self):
        # v2: 벡터 테이블 추가(슬라이스 3). v3: documents.surface_text 컬럼(raw 본문
        # 색인 — raw 청크는 store에 없는 행이라 원문을 색인이 직접 운반, §2.2).
        # v4: meta.corpus_fingerprint 추가(§7 신선도 가드 1/2).
        self.assertEqual(SCHEMA_VERSION, 4)


class RawIndexTest(unittest.TestCase):
    """raw 원문 청크 색인(스펙 §2.2, 2026-06-11) — raw/sources/<ctx>/*.md가
    kind=raw_chunk·status=raw 행으로 같은 색인에 들어가고 원문(surface_text)을
    운반한다. 전부 stub embedder."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()
        build_store_dir(self.brain, [
            glossary_term("g.race", term="레이스", definition="카약 경주 진행"),
        ])
        src = self.brain / "raw" / "sources" / "foo-ctx"
        src.mkdir(parents=True)
        (src / "spec-v1.md").write_text(
            "# 광고 버튼 기획 의도\n광고 시청 버튼은 빈 보유량 상태에서 노출 비율을 줄인다.\n",
            encoding="utf-8")

    def tearDown(self):
        self._td.cleanup()

    def test_rebuild_indexes_raw_chunks_with_meta(self):
        stats = rebuild(self.brain, self.db, embedder=self.embedder)
        self.assertEqual(stats["raw_chunks"], 1)
        conn = sqlite3.connect(str(self.db))
        try:
            row = conn.execute(
                "SELECT kind, status, context_id, surface_text FROM documents "
                "WHERE object_id = 'raw.foo-ctx.spec-v1#000'"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "raw_chunk")
        self.assertEqual(row[1], "raw")
        self.assertEqual(row[2], "context.foo-ctx")
        self.assertIn("광고 시청 버튼", row[3])

    def test_bm25_returns_raw_rows_with_surface_text(self):
        rebuild(self.brain, self.db, embedder=self.embedder)
        out = search_bm25(self.db, "광고 시청 버튼 노출 비율")
        raw_hits = [r for r in out["results"] if r["kind"] == "raw_chunk"]
        self.assertTrue(raw_hits)
        self.assertIn("광고 시청 버튼", raw_hits[0]["surface_text"])

    def test_vector_returns_raw_rows(self):
        rebuild(self.brain, self.db, embedder=self.embedder)
        out = search_vector(self.db, "광고 시청 버튼은 빈 보유량 상태에서 노출 비율을 줄인다.",
                            embedder=self.embedder)
        ids = [r["object_id"] for r in out["results"]]
        self.assertIn("raw.foo-ctx.spec-v1#000", ids)

    def test_no_raw_dir_keeps_stats_zero(self):
        # raw 디렉토리 없는 brain(기존 합성 테스트 전부)은 raw_chunks 0 — 무회귀.
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        brain = Path(td.name) / "brain"
        db = Path(td.name) / "index.db"
        build_store_dir(brain, [glossary_term("g.x", term="레이스")])
        stats = rebuild(brain, db)
        self.assertEqual(stats["raw_chunks"], 0)


class VectorIndexTest(unittest.TestCase):
    """벡터 색인·KNN·scope 후처리 — 전부 stub embedder(결정론, §5·§10)."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()
        build_store_dir(self.brain, [
            glossary_term("g.race", term="레이스", definition="카약 경주 진행"),
            glossary_term("g.reward", term="보상", definition="레이스 종료 보상 지급"),
            code_locator("code.new", path="main/map/MinaKayak.cpp", symbol="onClickNewRace"),
            review_record("review.x"),  # 색인 제외
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)

    def tearDown(self):
        self._td.cleanup()

    def test_meta_records_stub_embed_model(self):
        conn = sqlite3.connect(str(self.db))
        try:
            embed_model = conn.execute("SELECT embed_model FROM meta").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(embed_model, "stub:sha256-gaussian")
        self.assertTrue(embed_model.startswith("stub:"))

    def test_vec_rows_match_indexed_count(self):
        # 색인된 documents 행 수 == documents_vec 행 수(색인 제외 객체는 둘 다 빠짐).
        conn = sqlite3.connect(str(self.db))
        conn.enable_load_extension(True)
        import sqlite_vec
        sqlite_vec.load(conn)
        try:
            doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            vec_count = conn.execute("SELECT COUNT(*) FROM documents_vec").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(doc_count, 3)  # 용어 2 + 코드 1, ReviewRecord 제외
        self.assertEqual(vec_count, 3)

    def test_knn_returns_indexed_object(self):
        # stub은 의미를 못 담지만, 같은 텍스트 임베딩은 자기 자신을 거리 0 근처로 찾는다.
        out = search_vector(self.db, "카약 경주 진행", embedder=self.embedder)
        ids = [r["object_id"] for r in out["results"]]
        self.assertIn("g.race", ids)
        # g.race가 자기 표면과 동일 임베딩이라 거리 최소(맨 앞).
        self.assertEqual(ids[0], "g.race")

    def test_result_shape_mirrors_bm25(self):
        out = search_vector(self.db, "레이스", embedder=self.embedder)
        self.assertIn("results", out)
        self.assertIn("warnings", out)
        for r in out["results"]:
            self.assertEqual(
                set(r.keys()),
                {"object_id", "kind", "status", "context_id", "score", "surface_text"},
            )

    def test_score_is_rounded_six_places(self):
        out = search_vector(self.db, "레이스", embedder=self.embedder)
        for r in out["results"]:
            self.assertEqual(r["score"], round(r["score"], 6))

    def test_deterministic_ordering(self):
        a = search_vector(self.db, "레이스 보상", embedder=self.embedder)["results"]
        b = search_vector(self.db, "레이스 보상", embedder=self.embedder)["results"]
        self.assertEqual(a, b)

    def test_top_n_limit(self):
        out = search_vector(self.db, "레이스", top_n=1, embedder=self.embedder)
        self.assertLessEqual(len(out["results"]), 1)

    def test_empty_query_returns_empty(self):
        out = search_vector(self.db, "", embedder=self.embedder)
        self.assertEqual(out["results"], [])

    def test_vec_table_dimension(self):
        # documents_vec 컬럼 차원이 EMBED_DIM(1024)과 일치 — 임베더와 테이블 정합(§3.3).
        conn = sqlite3.connect(str(self.db))
        conn.enable_load_extension(True)
        import sqlite_vec
        sqlite_vec.load(conn)
        try:
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'documents_vec'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertIn(f"FLOAT[{EMBED_DIM}]", sql)


class VectorScopeTest(unittest.TestCase):
    """scope 후처리(over-fetch 후 context_id 필터, §3.3) — stub embedder."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()
        build_store_dir(self.brain, [
            glossary_term("g.a", term="레이스", context_id="context.kayak"),
            glossary_term("g.b", term="레이스", context_id="context.other"),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)

    def tearDown(self):
        self._td.cleanup()

    def test_scope_filters_to_matching_context(self):
        out = search_vector(self.db, "레이스", scope="context.kayak", embedder=self.embedder)
        ids = {r["object_id"] for r in out["results"]}
        self.assertIn("g.a", ids)
        self.assertNotIn("g.b", ids)
        for r in out["results"]:
            self.assertEqual(r["context_id"], "context.kayak")

    def test_no_scope_returns_both(self):
        out = search_vector(self.db, "레이스", embedder=self.embedder)
        ids = {r["object_id"] for r in out["results"]}
        self.assertIn("g.a", ids)
        self.assertIn("g.b", ids)


class FtsRegressionWithVecTableTest(unittest.TestCase):
    """벡터 테이블이 있는 DB에서도 BM25 검색이 무회귀로 동작한다(슬라이스 2 보존)."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        build_store_dir(self.brain, [
            glossary_term("g.race", term="레이스", definition="카약 경주"),
            code_locator("code.new", path="a/b/C.cpp", symbol="onClickNewRace"),
        ])
        rebuild(self.brain, self.db, embedder=StubEmbedder())

    def tearDown(self):
        self._td.cleanup()

    def test_bm25_still_works_with_vec_table(self):
        out = search_bm25(self.db, "레이스")
        ids = {r["object_id"] for r in out["results"]}
        self.assertIn("g.race", ids)

    def test_bm25_symbol_with_vec_table(self):
        out = search_bm25(self.db, "onClickNewRace")
        ids = {r["object_id"] for r in out["results"]}
        self.assertIn("code.new", ids)


if __name__ == "__main__":
    unittest.main()


class CorpusFingerprintTest(unittest.TestCase):
    def _make_candidate_obj(self):
        return glossary_term("g.t.a", term="용어", definition="정의",
                             status="candidate", context_id="context.t")

    def test_rebuild_writes_corpus_fingerprint(self):
        with TemporaryDirectory() as td:
            brain_root = Path(td)
            BrainStore.save_object(brain_root, self._make_candidate_obj())
            db = brain_root / "idx.db"

            rebuild(brain_root=brain_root, db_path=db)

            conn = sqlite3.connect(db)
            fp = conn.execute("SELECT corpus_fingerprint FROM meta").fetchone()[0]
            conn.close()
            self.assertTrue(fp)  # 64자리 sha256 hex
            self.assertEqual(len(fp), 64)

    def test_fingerprint_changes_when_object_changes(self):
        with TemporaryDirectory() as td:
            brain_root = Path(td)
            BrainStore.save_object(brain_root, self._make_candidate_obj())
            db = brain_root / "idx.db"
            rebuild(brain_root=brain_root, db_path=db)
            conn = sqlite3.connect(db)
            fp1 = conn.execute("SELECT corpus_fingerprint FROM meta").fetchone()[0]
            conn.close()

            # status 플립 = supersede 계열 변경 — 지문도 달라져야 한다.
            obj2 = glossary_term("g.t.a", term="용어", definition="정의",
                                 status="reviewed", context_id="context.t")
            BrainStore.save_object(brain_root, obj2)
            rebuild(brain_root=brain_root, db_path=db)
            conn = sqlite3.connect(db)
            fp2 = conn.execute("SELECT corpus_fingerprint FROM meta").fetchone()[0]
            conn.close()

            self.assertNotEqual(fp1, fp2)

    def test_compute_fingerprint_is_deterministic(self):
        from project_brain.search_index import compute_corpus_fingerprint
        with TemporaryDirectory() as td:
            brain_root = Path(td)
            BrainStore.save_object(brain_root, self._make_candidate_obj())
            store = BrainStore.load(brain_root)
            a = compute_corpus_fingerprint(store, brain_root)
            b = compute_corpus_fingerprint(store, brain_root)
            self.assertEqual(a, b)

    def test_fingerprint_excludes_rows_that_tokenize_empty(self):
        # rebuild는 표면이 비-None이어도 토큰화가 []인 행은 색인하지 않는다(두 번째
        # 필터). 지문도 같은 필터여야 한다 — 안 그러면 색인엔 없는 객체의 변경이
        # 지문만 바꿔 Task 5 가드가 멀쩡한 색인을 낡았다고 오판한다(거짓 양성).
        # 한자 표면은 mecab-ko·정규식 폴백 양쪽에서 빈 토큰(실측 2026-06-11).
        from project_brain.search_index import compute_corpus_fingerprint
        with TemporaryDirectory() as td:
            brain_root = Path(td)
            BrainStore.save_object(brain_root, self._make_candidate_obj())
            cjk1 = glossary_term("g.t.cjk", term="一二三", definition="四五六",
                                 status="candidate", context_id="context.t")
            BrainStore.save_object(brain_root, cjk1)
            # 전제 확인: rebuild는 빈 토큰 객체를 색인하지 않는다(일반 객체 1행만).
            stats = rebuild(brain_root=brain_root, db_path=brain_root / "idx.db")
            self.assertEqual(stats["indexed"], 1)
            store = BrainStore.load(brain_root)
            fp_with = compute_corpus_fingerprint(store, brain_root)

            # 빈 토큰 객체의 내용만 바꿔도(여전히 빈 토큰) 지문 불변.
            cjk2 = glossary_term("g.t.cjk", term="一二三", definition="七八九",
                                 status="candidate", context_id="context.t")
            BrainStore.save_object(brain_root, cjk2)
            store2 = BrainStore.load(brain_root)
            self.assertEqual(fp_with, compute_corpus_fingerprint(store2, brain_root))

            # 더 강하게: 그 객체가 아예 없는 코퍼스와도 지문이 같다(색인 집합 동치).
            (brain_root / "objects" / "domain" / "g.t.cjk.json").unlink()
            store3 = BrainStore.load(brain_root)
            self.assertEqual(fp_with, compute_corpus_fingerprint(store3, brain_root))


class StaleProjectionTest(unittest.TestCase):
    """rebuild·fingerprint가 낡은(source_content_hash 불일치) projection을 색인/지문에서 뺀다.

    구성 객체가 바뀌면(매핑 표면 변형) 저장된 source_content_hash가 재계산값과
    어긋난다. 그런 projection은 이전 착수 브리핑이 더는 정확하지 않으므로 색인에서
    빠져야 한다. fresh projection(해시 일치)은 그대로 색인된다.
    rebuild와 compute_corpus_fingerprint가 같은 입력을 봐야 신선도 가드가 어긋나지 않는다.
    """

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"

    def tearDown(self):
        self._td.cleanup()

    def _fresh_hash(self, source_object_ids):
        # 저장된 store 내용으로 source_content_hash를 재계산(lint 헬퍼 재사용).
        from project_brain.lint import _compute_source_content_hash
        store = BrainStore.load(self.brain)
        return _compute_source_content_hash(store, source_object_ids)

    def _index_object_ids_of_kind(self, kind):
        conn = sqlite3.connect(str(self.db))
        try:
            return {
                r[0] for r in conn.execute(
                    "SELECT object_id FROM documents WHERE kind = ?", (kind,)
                ).fetchall()
            }
        finally:
            conn.close()

    def test_stale_projection_excluded_from_rebuild(self):
        # 구성 용어를 적재 → fresh 해시로 projection 저장 → 그 용어의 표면을 바꿔
        # source_content_hash 불일치 유발 → rebuild → projection이 색인에서 빠진다.
        build_store_dir(self.brain, [
            glossary_term("g.src", term="알림클리어", definition="알림 클리어 팝업"),
        ])
        fresh = self._fresh_hash(["g.src"])
        proj = projection("projection.stale", context_id="context.neutral",
                          title="알림 클리어 재사용 브리핑",
                          reuse_payload="알림 클리어 팝업 재사용 착수 데이터",
                          source_object_ids=["g.src"])
        proj["source_content_hash"] = fresh
        BrainStore.save_object(self.brain, proj)
        # 구성 용어 변형 → source_content_hash 불일치(낡음).
        BrainStore.save_object(self.brain, glossary_term(
            "g.src", term="알림클리어", definition="완전히 다른 정의로 변경"))
        rebuild(self.brain, self.db)
        self.assertNotIn(
            "projection.stale", self._index_object_ids_of_kind("ContextProjection"))

    def test_fresh_projection_included_in_rebuild(self):
        # 구성 용어를 적재 → fresh 해시로 projection 저장 → 변형 없이 rebuild →
        # projection이 색인에 포함된다.
        build_store_dir(self.brain, [
            glossary_term("g.src", term="알림클리어", definition="알림 클리어 팝업"),
        ])
        fresh = self._fresh_hash(["g.src"])
        proj = projection("projection.fresh", context_id="context.neutral",
                          title="알림 클리어 재사용 브리핑",
                          reuse_payload="알림 클리어 팝업 재사용 착수 데이터",
                          source_object_ids=["g.src"])
        proj["source_content_hash"] = fresh
        BrainStore.save_object(self.brain, proj)
        rebuild(self.brain, self.db)
        self.assertIn(
            "projection.fresh", self._index_object_ids_of_kind("ContextProjection"))

    def test_stale_projection_excluded_from_fingerprint(self):
        # rebuild와 지문이 같은 입력을 봐야 한다 — stale projection은 지문에서도 빠진다.
        from project_brain.search_index import compute_corpus_fingerprint
        build_store_dir(self.brain, [
            glossary_term("g.src", term="알림클리어", definition="알림 클리어 팝업"),
        ])
        fresh = self._fresh_hash(["g.src"])
        proj = projection("projection.fp", context_id="context.neutral",
                          title="알림 클리어 재사용 브리핑",
                          reuse_payload="알림 클리어 팝업 재사용 착수 데이터",
                          source_object_ids=["g.src"])
        proj["source_content_hash"] = fresh
        BrainStore.save_object(self.brain, proj)
        store_fresh = BrainStore.load(self.brain)
        fp_with_fresh = compute_corpus_fingerprint(store_fresh, self.brain)

        # projection을 낡게(해시 불일치) 만든다 — 색인 집합에서 빠지므로 지문 불변이어야.
        proj_stale = dict(proj)
        proj_stale["source_content_hash"] = "deadbeef"
        BrainStore.save_object(self.brain, proj_stale)
        store_stale = BrainStore.load(self.brain)
        fp_with_stale = compute_corpus_fingerprint(store_stale, self.brain)

        # projection 자체를 아예 지운 코퍼스의 지문과 stale 코퍼스의 지문이 같아야 한다.
        (self.brain / "indexes" / "context_projections" / "projection.fp.json").unlink()
        store_gone = BrainStore.load(self.brain)
        fp_gone = compute_corpus_fingerprint(store_gone, self.brain)
        self.assertEqual(fp_with_stale, fp_gone)
        self.assertNotEqual(fp_with_fresh, fp_with_stale)


class RebuildConfigFallbackTest(unittest.TestCase):
    def test_rebuild_without_args_resolves_from_config(self):
        # 분리 후 실사용 경로: 인자 없이 rebuild() → config(.project-brain.json)
        # 해석. raw 소스 순회까지 resolve된 brain_root를 써야 한다(2026-06-11
        # 실전 첫 실행에서 raw 순회가 원래 인자 None을 받아 죽은 회귀).
        import json as _json
        import os

        with TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / ".project-brain.json").write_text("{}", encoding="utf-8")
            brain = root / "brain"
            build_store_dir(brain, [
                glossary_term("g.cfg", term="설정폴백", definition="정의"),
            ])
            src = brain / "raw" / "sources" / "feature-x"
            src.mkdir(parents=True)
            (src / "spec.md").write_text("# 개요\n설정 폴백 검증 본문.", encoding="utf-8")
            prev = os.getcwd()
            os.chdir(root)
            try:
                stats = rebuild()
            finally:
                os.chdir(prev)
            self.assertEqual(stats["indexed"] - stats["raw_chunks"], 1)
            self.assertGreaterEqual(stats["raw_chunks"], 1)
            self.assertTrue((brain / ".brain-local" / "index.db").exists())


class ScopedBm25PureTest(unittest.TestCase):
    """_bm25_rank_scoped 순수 함수 — BM25 성질(tf·idf 단조성, 결정론)을 손꼽이 코퍼스로 검증."""

    def test_higher_tf_scores_higher(self):
        # 같은 토큰을 더 많이 가진 문서가 위 (길이 보정 후에도 tf 2 > tf 1).
        docs = [("d1", ["알림", "팝업"]), ("d2", ["클리어", "팝업", "팝업"])]
        ranked = dict(_bm25_rank_scoped(docs, {"팝업"}))
        self.assertGreater(ranked["d2"], ranked["d1"])

    def test_rarer_token_scores_higher(self):
        # 후보 집합 안에서 "클리어" df=1 < "알림" df=2 → 희소 토큰 매칭 문서가 위.
        docs = [
            ("d1", ["알림", "팝업"]),
            ("d2", ["클리어", "팝업"]),
            ("d3", ["알림", "안내"]),
        ]
        ranked = dict(_bm25_rank_scoped(docs, {"알림", "클리어"}))
        self.assertGreater(ranked["d2"], ranked["d1"])

    def test_unmatched_docs_excluded_and_tiebreak_by_object_id(self):
        # 질의 토큰 미포함 문서는 제외, 동점은 object_id 오름차순(§5 결정론).
        docs = [("d.b", ["팝업"]), ("d.a", ["팝업"]), ("d.x", ["무관"])]
        ranked = _bm25_rank_scoped(docs, {"팝업"})
        self.assertEqual([oid for oid, _ in ranked], ["d.a", "d.b"])

    def test_empty_docs_returns_empty(self):
        self.assertEqual(_bm25_rank_scoped([], {"팝업"}), [])


class ScopedBm25SearchTest(unittest.TestCase):
    """search_bm25_scoped — ★scope 밖 적재 면역 불변식★(s1 회귀 2026-06-12의 가드).

    FTS5 bm25()는 전역 df 기반이라 scope 밖 적재가 scope 안 순위를 흔든다(대조
    테스트가 그 현상을 박제). scoped 재계산은 같은 상황에서 결과(id·score)가
    완전 불변이어야 한다.
    """

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        # context.a: 질의 "알림 클리어" 기준 a 내부 df가 알림=2(d1·d3)·클리어=1(d2)
        # → scoped에선 희소한 "클리어"를 가진 d2가 d1보다 항상 위.
        self.base_objs = [
            glossary_term("g.d1", term="알림 팝업", context_id="context.a"),
            glossary_term("g.d2", term="클리어 팝업", context_id="context.a"),
            glossary_term("g.d3", term="알림 안내", context_id="context.a"),
        ]
        # scope 밖(context.b) 어휘 중첩 — 전역 df(클리어)를 1→5로 역전시킨다.
        self.noise_objs = [
            glossary_term(f"g.n{i}", term="클리어 보상", context_id="context.b")
            for i in range(4)
        ]

    def tearDown(self):
        self._td.cleanup()

    def _rebuild(self, objs):
        # brain root에 객체를 누적 저장 후 전체 재색인(FTS만 — scoped는 임베더 불필요).
        build_store_dir(self.brain, objs)
        rebuild(self.brain, self.db)

    def test_scoped_results_immune_to_out_of_scope_ingest(self):
        # ★핵심 불변식★: context.b 적재 전후 scoped 결과(id·score)가 완전 동일.
        self._rebuild(self.base_objs)
        before = search_bm25_scoped(self.db, "알림 클리어", scope="context.a")["results"]
        self.assertTrue(before)
        self._rebuild(self.noise_objs)
        after = search_bm25_scoped(self.db, "알림 클리어", scope="context.a")["results"]
        self.assertEqual(before, after)

    def test_global_fts_bm25_shifts_with_out_of_scope_ingest(self):
        # 대조 박제: 같은 합성에서 기존 전역 search_bm25는 a 내부 순위가 뒤집힌다
        # (초기 전역 df: 클리어1 < 알림2 → d2 우위 / b 추가 후: 클리어5 > 알림2 →
        #  d1 우위). 이 현상이 s1 회귀의 원인이고 scoped 레인의 존재 이유다.
        def a_rank(results):
            return [r["object_id"] for r in results
                    if r["object_id"] in ("g.d1", "g.d2")]

        self._rebuild(self.base_objs)
        before = a_rank(search_bm25(self.db, "알림 클리어")["results"])
        self._rebuild(self.noise_objs)
        after = a_rank(search_bm25(self.db, "알림 클리어")["results"])
        self.assertEqual(before, ["g.d2", "g.d1"])
        self.assertEqual(after, ["g.d1", "g.d2"])

    def test_scope_excludes_other_context_and_raw(self):
        # scope 행만 후보 — 다른 컨텍스트·raw 청크는 결과에도 df에도 안 들어간다.
        build_store_dir(self.brain, self.base_objs + [
            glossary_term("g.out", term="알림 팝업", context_id="context.b"),
        ])
        src = self.brain / "raw" / "sources" / "a"
        src.mkdir(parents=True)
        (src / "spec.md").write_text("# 개요\n알림 팝업 클리어 서술.", encoding="utf-8")
        rebuild(self.brain, self.db)
        results = search_bm25_scoped(self.db, "알림 팝업", scope="context.a")["results"]
        ids = {r["object_id"] for r in results}
        self.assertIn("g.d1", ids)
        self.assertNotIn("g.out", ids)
        self.assertTrue(all(r["kind"] != "raw_chunk" for r in results))

    def test_deterministic(self):
        self._rebuild(self.base_objs)
        a = search_bm25_scoped(self.db, "알림 클리어 팝업", scope="context.a")
        b = search_bm25_scoped(self.db, "알림 클리어 팝업", scope="context.a")
        self.assertEqual(a, b)

    def test_no_tokens_returns_empty(self):
        self._rebuild(self.base_objs)
        self.assertEqual(
            search_bm25_scoped(self.db, "", scope="context.a")["results"], [])

    def test_scoped_bm25_excludes_projection(self):
        # scope 객체 레인(search_bm25_scoped)이 projection 행을 안 집는다 — 직접 검증.
        # projection을 scope 안(context.a)에 fresh source_content_hash로 두어 색인에
        # ★실제로 들어간 상태★를 만들고(A6 신선도 가드 통과), reuse_payload에 질의
        # 토큰을 담는다. 제외 SQL(kind NOT IN)이 없으면 results에 ContextProjection이
        # 섞인다 — 그 제외를 직접 검증한다(projection은 별도 재사용 레인 소관).
        src = self.base_objs[0]  # g.d1 (context.a, "알림 팝업")
        proj = projection("projection.a.reuse", context_id="context.a",
                          title="알림 클리어 재사용 브리핑",
                          reuse_payload="알림 클리어 팝업 재사용 착수 데이터",
                          source_object_ids=["g.d1"], source_objects=[src])
        self._rebuild(self.base_objs + [proj])
        # 전제: fresh hash라 projection이 색인 documents에 실제로 들어갔다.
        conn = sqlite3.connect(str(self.db))
        try:
            indexed = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE object_id = ? AND kind = ?",
                ("projection.a.reuse", "ContextProjection"),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(indexed, 1)
        out = search_bm25_scoped(self.db, "알림 클리어", scope="context.a")
        self.assertTrue(out["results"])
        self.assertTrue(
            all(r.get("kind") != "ContextProjection" for r in out["results"]))
