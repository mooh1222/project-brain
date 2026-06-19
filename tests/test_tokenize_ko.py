"""한국어+심볼 토크나이저 테스트 (스펙 §6, 구현 슬라이스 2).

대칭 보장의 핵심 모듈이라 다음을 검증한다.
- 심볼 분리·정규식 폴백은 백엔드 무관 결정론 → 항상 도는 테스트.
- mecab 형태소 결과 단언은 active_backend()=="mecab-ko"일 때만(skipUnless) —
  mecab 없는 환경에서도 스위트 green이어야 한다.
- 백엔드 강제 주입(backend 인자)으로 정규식 폴백 경로를 mecab 있는 환경에서도 검증.
"""

import unittest

from project_brain.tokenize_ko import active_backend, tokenize


class SymbolSplitTest(unittest.TestCase):
    """심볼 분리는 형태소 백엔드와 무관한 결정론 규칙 (스펙 §6)."""

    def test_camel_case_splits_and_keeps_original(self):
        toks = tokenize("onClickNewRace")
        # 분리 토큰 (소문자)
        for piece in ("on", "click", "new", "race"):
            self.assertIn(piece, toks)
        # 원형 토큰 보존 (소문자 정규화)
        self.assertIn("onclicknewrace", toks)

    def test_snake_case_and_upper_abbrev_split_and_keep_original(self):
        toks = tokenize("MINA_KAYAK_RACE_STATUS")
        for piece in ("mina", "kayak", "race", "status"):
            self.assertIn(piece, toks)
        self.assertIn("mina_kayak_race_status", toks)

    def test_double_colon_separator_splits(self):
        toks = tokenize("MinaKayakViewData::getRaceStatus")
        for piece in ("mina", "kayak", "view", "data", "get", "race", "status"):
            self.assertIn(piece, toks)
        # :: 양쪽 원형도 보존
        self.assertIn("minakayakviewdata", toks)
        self.assertIn("getracestatus", toks)

    def test_path_separators_split_into_meaning_tokens(self):
        # CodeLocator path 형태 — /, . 가 의미 토큰으로 쪼개진다
        toks = tokenize("main/map/MinaKayakPopupEnterRaceInfoNode.cpp")
        for piece in ("main", "map", "mina", "kayak", "popup", "enter", "race", "info", "node"):
            self.assertIn(piece, toks)
        # 확장자도 토큰
        self.assertIn("cpp", toks)

    def test_alphanumeric_run_kept(self):
        # 숫자 섞인 약어/코드 (에러코드 15207 류)
        toks = tokenize("NO_REWARD 15207")
        self.assertIn("no", toks)
        self.assertIn("reward", toks)
        self.assertIn("15207", toks)

    def test_empty_and_blank(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("   "), [])

    def test_returns_list_of_str(self):
        toks = tokenize("onClickNewRace 보상")
        self.assertIsInstance(toks, list)
        self.assertTrue(all(isinstance(t, str) for t in toks))


class RegexFallbackTest(unittest.TestCase):
    """백엔드 강제 주입으로 정규식 폴백 경로를 항상 검증 (mecab 있어도)."""

    def test_regex_backend_splits_korean_run(self):
        # 정규식 폴백은 한글 연속을 하나의 토큰으로 (형태소 분리 안 함)
        toks = tokenize("미나의카약", backend="regex")
        self.assertIn("미나의카약", toks)

    def test_regex_backend_separates_korean_and_symbol(self):
        toks = tokenize("onClickNewRace 레이스", backend="regex")
        # 한글 런과 영문 심볼이 분리
        self.assertIn("레이스", toks)
        self.assertIn("onclicknewrace", toks)
        self.assertIn("race", toks)

    def test_regex_backend_korean_blocks_separated_by_space(self):
        toks = tokenize("카약 레이스 보상", backend="regex")
        self.assertIn("카약", toks)
        self.assertIn("레이스", toks)
        self.assertIn("보상", toks)


class IndexQuerySymmetryTest(unittest.TestCase):
    """단일 공유 함수가 색인·쿼리 대칭을 보장한다 (스펙 §6 핵심)."""

    def test_same_function_same_input_same_output(self):
        text = "MinaKayakViewData::getRaceStatus 레이스 보상"
        # 같은 백엔드면 색인 호출과 쿼리 호출이 동일 결과
        self.assertEqual(tokenize(text), tokenize(text))

    def test_symbol_query_overlaps_indexed_symbol_tokens(self):
        # 영문 약어로 색인하고 한국어/심볼 혼합 질의해도 분리 토큰이 겹친다
        indexed = set(tokenize("MINA_KAYAK_RACE_STATUS", backend="regex"))
        query = set(tokenize("race status 보상", backend="regex"))
        self.assertTrue(indexed & query)
        self.assertIn("race", indexed & query)
        self.assertIn("status", indexed & query)


class ActiveBackendTest(unittest.TestCase):
    def test_active_backend_is_known_value(self):
        self.assertIn(active_backend(), {"mecab-ko", "kiwipiepy", "regex"})


@unittest.skipUnless(
    active_backend() == "mecab-ko", "mecab-ko 백엔드가 활성일 때만 형태소 결과 단언"
)
class MecabMorphemeTest(unittest.TestCase):
    """mecab-ko 활성 환경에서만 한국어 형태소 분리 결과를 단언한다."""

    def test_josa_separated_from_noun(self):
        # "미나의" → 미나 + 의(조사) 로 분리되어야 한다
        toks = tokenize("미나의 카약 레이스 보상")
        self.assertIn("미나", toks)
        self.assertIn("카약", toks)
        self.assertIn("레이스", toks)
        self.assertIn("보상", toks)

    def test_morpheme_splits_compound_query(self):
        # 형태소 분리가 되면 "보상을"이 "보상" 토큰을 포함
        toks = tokenize("레이스 끝났는데 보상을 못 받았대")
        self.assertIn("보상", toks)
        self.assertIn("레이스", toks)


if __name__ == "__main__":
    unittest.main()
