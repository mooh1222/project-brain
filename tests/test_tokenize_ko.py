"""한국어+심볼 토크나이저 테스트 (스펙 §6, 구현 슬라이스 2).

대칭 보장의 핵심 모듈이라 다음을 검증한다.
- 심볼 분리·정규식 주입은 백엔드 무관 결정론 → 항상 도는 테스트.
- 한국어 백엔드는 kiwipiepy 하나로 고정돼 있고 버전이 pyproject에 고정돼 있으므로
  (#79) 형태소 결과 단언을 skip 없이 항상 돌린다. kiwipiepy가 없으면 폴백이 아니라
  오류이므로 스위트가 붉게 터지는 것이 옳다.
- 백엔드 강제 주입(backend="regex")으로 정규식 경로를 항상 검증.
"""

import unittest

from project_brain.tokenize_ko import (
    TOKENIZER_RULES_VERSION,
    active_backend,
    parse_tokenizer_signature,
    tokenize,
    tokenizer_signature,
)


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


class RegexInjectionTest(unittest.TestCase):
    """백엔드 강제 주입으로 정규식 경로를 항상 검증 (기본 백엔드가 kiwipiepy여도)."""

    def test_regex_backend_splits_korean_run(self):
        # 정규식 주입은 한글 연속을 하나의 토큰으로 (형태소 분리 안 함)
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
    def test_active_backend_is_kiwipiepy(self):
        # #79: 한국어 백엔드는 kiwipiepy 하나다. 폴백 사다리가 없으므로 환경마다
        # 다른 이름이 나올 수 없고, 없으면 조용한 폴백이 아니라 오류다.
        self.assertEqual(active_backend(), "kiwipiepy")


class TokenizerSignatureTest(unittest.TestCase):
    """색인 meta에 적는 토크나이저 정체성 문자열의 왕복 계약 (#75).

    색인 쪽이 signature를 적고 검색 쪽이 parse해 (이름, 규칙 버전)으로 비교한다 —
    두 함수가 어긋나면 색인↔쿼리 불일치 가드가 잘못 판정한다.
    """

    def test_signature_is_backend_name_and_rules_version(self):
        self.assertEqual(
            tokenizer_signature(),
            f"{active_backend()}@{TOKENIZER_RULES_VERSION}",
        )

    def test_rules_version_is_4_after_suffix_compounds(self):
        # #79 결합형(2) → 숫자·외국어 결합·명사형 표면(3) → 명사+파생 접미사 결합(#82, 4).
        # 규칙이 바뀔 때마다 올라가야 옛 색인이 거부된다.
        self.assertEqual(TOKENIZER_RULES_VERSION, 4)

    def test_current_signature_is_kiwipiepy_at_4(self):
        self.assertEqual(tokenizer_signature(), "kiwipiepy@4")

    def test_signature_round_trips_through_parse(self):
        self.assertEqual(
            parse_tokenizer_signature(tokenizer_signature()),
            (active_backend(), TOKENIZER_RULES_VERSION),
        )

    def test_value_without_rules_version_reads_as_version_1(self):
        # 규칙 버전을 도입하기 전 색인은 이름만 적었다 — 버전 1로 읽는다.
        # 현재 규칙은 2라 이 값은 호출부에서 불일치로 거부된다(#79 rebuild 유도).
        self.assertEqual(parse_tokenizer_signature("kiwipiepy"), ("kiwipiepy", 1))

    def test_explicit_rules_version_is_read_as_int(self):
        self.assertEqual(parse_tokenizer_signature("kiwipiepy@2"), ("kiwipiepy", 2))

    def test_non_integer_tail_is_not_read_as_a_version(self):
        # 손으로 망가뜨린 meta는 예외로 터지지 않고 값 전체를 이름으로 본다 —
        # 현재 백엔드와 같을 수 없으므로 호출부에서 불일치로 거부된다.
        self.assertEqual(parse_tokenizer_signature("regex@알수없음"),
                         ("regex@알수없음", 1))


class KiwiMorphemeTest(unittest.TestCase):
    """kiwipiepy 형태소 분리 결과 — 백엔드·버전이 고정돼 있어 항상 돈다(#79)."""

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


class NominalSurfaceTokenTest(unittest.TestCase):
    """규칙 버전 3 — 동사 어간+명사형 전성어미(ETN) 어절은 원문 표면도 토큰으로 보존한다.

    kiwi는 "알림"을 뒷말에 따라 명사(NNG)로도 알리+ㅁ으로도 읽는다(문맥 의존). 색인과 질의가
    다른 쪽으로 읽혀도 같은 토큰 "알림"을 공유해야 한다.
    """

    def test_nominalized_verb_keeps_surface_next_to_fragments(self):
        self.assertEqual(tokenize("알림 안내"), ["알리", "알림", "안내"])
        self.assertEqual(tokenize("알림"), ["알리", "알림"])

    def test_noun_reading_and_nominalized_reading_share_the_surface_token(self):
        # "알림을"은 kiwi가 명사로 읽어 알림이 조각 자체다 — 표면 토큰은 중복 없이 하나.
        toks = tokenize("알림을 보낸다")
        self.assertEqual(toks[:3], ["알림", "을", "보내"])
        self.assertEqual(toks.count("알림"), 1)
        self.assertTrue(set(tokenize("알림 안내")) & set(tokenize("알림을 보낸다")) >= {"알림"})

    def test_gi_nominalization_and_auxiliary_chain(self):
        self.assertEqual(tokenize("만들기 버튼"), ["만들", "기", "만들기", "버튼"])
        self.assertEqual(tokenize("보여주기 옵션"), ["보이", "어", "주", "기", "보여주기", "옵션"])

    def test_plain_verb_endings_do_not_create_a_surface(self):
        # EF·EC·ETM 뒤에는 명사형 표면을 만들지 않는다.
        self.assertEqual(tokenize("보상을 받았대"), ["보상", "을", "받", "었", "대"])
        self.assertEqual(tokenize("레이스 끝났는데 보상"), ["레이스", "끝나", "었", "는데", "보상"])


class CompoundNounTokenTest(unittest.TestCase):
    """어절 안 연속 명사 조각의 결합형을 조각과 함께 보존한다 (#79, spec #72).

    영문 심볼에서 camelCase 조각과 원형을 같이 남기는 것과 같은 규칙을 한글에 적용한
    것이다. 순서는 어절 단위로 조각 먼저, 그 어절의 결합형이 뒤에 붙는다 — 색인·질의가
    같은 함수를 쓰므로 순서 자체가 매칭을 바꾸지는 않지만, 규칙이 조용히 흔들리지 않게
    출력 전체를 고정한다.
    """

    def test_compound_kept_with_fragments_and_josa_excluded(self):
        # 조사 "에서"는 결합에 섞이지 않고, 결합형 "인게임"이 조각과 함께 남는다.
        self.assertEqual(
            tokenize("인게임에서 아이템 사용하면"),
            ["인", "게임", "에서", "인게임", "아이템", "사용", "하", "면"],
        )

    def test_compound_from_two_noun_fragments_in_one_eojeol(self):
        self.assertEqual(
            tokenize("럭키박스 아이콘"),
            ["럭키", "박스", "럭키박스", "아이콘"],
        )

    def test_compound_does_not_cross_word_boundary(self):
        # "게임아이템"은 한 어절이라 결합하고, 띄어 쓴 "버튼"은 붙지 않는다.
        self.assertEqual(
            tokenize("게임아이템 버튼"),
            ["게임", "아이템", "게임아이템", "버튼"],
        )

    def test_space_separated_nouns_are_not_compounded(self):
        # 어절이 다르면 연속이 끊긴다 — 결합형이 아예 생기지 않는다.
        self.assertEqual(
            tokenize("스테이지 클리어 토큰"),
            ["스테이지", "클리어", "토큰"],
        )

    def test_single_fragment_eojeol_has_no_compound(self):
        self.assertEqual(tokenize("아이콘"), ["아이콘"])

    def test_verb_stem_and_ending_do_not_form_a_compound(self):
        # 동사 조각·어미는 명사류가 아니므로 어떤 결합형도 만들지 않는다.
        toks = tokenize("보상을 받았대")
        self.assertNotIn("보상을", toks)
        self.assertNotIn("받았대", toks)

    def test_digit_and_foreign_fragments_join_when_a_hangul_fragment_is_present(self):
        # 규칙 버전 3: SN(숫자)·SL(외국어) 조각도 한글 조각과 이어지면 결합형이 된다(소문자 정규화).
        self.assertEqual(tokenize("3단계 오픈 팝업"), ["단계", "3단계", "오픈", "팝업", "3"])
        self.assertEqual(tokenize("2차 레이스"), ["차", "2차", "레이스", "2"])
        self.assertEqual(tokenize("UI버튼 클릭"), ["버튼", "ui버튼", "클릭", "ui"])

    def test_digit_and_foreign_only_eojeol_is_not_compounded(self):
        # 한글 조각이 없는 어절은 심볼 경로가 처리하므로 결합형을 만들지 않는다.
        toks = tokenize("3.7new 패키지")
        self.assertNotIn("3.7new패키지", toks)
        self.assertEqual([t for t in toks if "new" in t], ["7new", "3.7new"])
        toks = tokenize("v8 기획서")
        self.assertEqual(toks, ["기획서", "v8"])

    def test_noun_plus_derivational_suffix_forms_a_compound(self):
        # 규칙 버전 4(#82): 명사류 연속 뒤에 바로 붙은 파생 접미사(XSN)는 같은 덩어리다.
        # kiwi는 "시간제"를 시간(NNG)+제(XSN)로 읽어 규칙 3까지는 "시간제" 토큰이 없었다.
        # 조각(시간·제)은 그대로 남고 어절 표면이 결합형으로 더해진다.
        self.assertEqual(tokenize("시간제 아이템"), ["시간", "제", "시간제", "아이템"])
        self.assertEqual(tokenize("스테이지별 보상"), ["스테이지", "별", "스테이지별", "보상"])
        self.assertEqual(tokenize("이벤트용 아이템"), ["이벤트", "용", "이벤트용", "아이템"])

    def test_suffix_inside_one_eojeol_keeps_joining_following_nouns(self):
        # 한 어절 "시간제아이템"은 접미사 뒤 명사까지 한 덩어리로 이어진다 — 어절 안 결합형은
        # 어절 하나에 하나만 만든다는 규칙 2의 출력 모양을 유지한다.
        self.assertEqual(tokenize("시간제아이템"), ["시간", "제", "아이템", "시간제아이템"])

    def test_suffix_without_a_preceding_noun_fragment_does_not_start_a_compound(self):
        # 접미사는 연속을 시작하지 못한다 — 대명사(NP) 뒤의 "들"은 앞에 명사류 조각이 없어
        # 결합형이 생기지 않는다. 조각은 그대로다.
        self.assertEqual(tokenize("우리들 보상"), ["우리", "들", "보상"])

    def test_same_input_twice_is_identical(self):
        text = "인게임에서 럭키박스 아이템 사용하면"
        self.assertEqual(tokenize(text), tokenize(text))


if __name__ == "__main__":
    unittest.main()
