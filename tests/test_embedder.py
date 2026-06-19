"""임베더 검증 (스펙 §5, 슬라이스 3).

spec: docs/superpowers/specs/2026-06-10-project-brain-search-layer-design.md

전부 stub embedder(결정론)로만 검증한다 — 실모델 테스트는 만들지 않는다(슬라이스
3.5에서 컨트롤러가 골든셋으로 실측, §5·§10). stub 결정론(같은 텍스트=같은 벡터,
L2 노름≈1)·차원·get_embedder 팩토리 분기·lazy 로드(생성만으로 모델 미로드)를 본다.
"""

import os
import unittest

import numpy as np

from project_brain.embedder import (
    EMBED_DIM,
    REAL_MODEL_NAME,
    STUB_ENV_FLAG,
    STUB_MODEL_NAME,
    RealEmbedder,
    StubEmbedder,
    get_embedder,
)


class StubEmbedderTest(unittest.TestCase):
    def test_same_text_same_vector(self):
        e = StubEmbedder()
        a = e.embed("레이스 보상 못 받음")
        b = e.embed("레이스 보상 못 받음")
        self.assertTrue(np.array_equal(a, b))

    def test_different_text_different_vector(self):
        e = StubEmbedder()
        a = e.embed("레이스 보상")
        b = e.embed("완전히 다른 텍스트")
        self.assertFalse(np.array_equal(a, b))

    def test_l2_normalized(self):
        e = StubEmbedder()
        v = e.embed("onClickNewRace 왜 바뀌었어")
        self.assertAlmostEqual(float(np.linalg.norm(v)), 1.0, places=5)

    def test_dimension(self):
        e = StubEmbedder()
        v = e.embed("미나 카약")
        self.assertEqual(v.shape, (EMBED_DIM,))
        self.assertEqual(v.dtype, np.float32)

    def test_embed_many_matches_embed(self):
        e = StubEmbedder()
        texts = ["레이스", "보상", "레인"]
        many = e.embed_many(texts)
        self.assertEqual(len(many), 3)
        for text, vec in zip(texts, many):
            self.assertTrue(np.array_equal(vec, e.embed(text)))

    def test_model_name_is_stub_prefixed(self):
        # meta.embed_model 기록 시 stub을 실모델과 구분(§4·§5).
        self.assertTrue(StubEmbedder.model_name.startswith("stub:"))
        self.assertEqual(StubEmbedder.model_name, STUB_MODEL_NAME)


class GetEmbedderTest(unittest.TestCase):
    def test_explicit_stub_true(self):
        self.assertIsInstance(get_embedder(stub=True), StubEmbedder)

    def test_explicit_stub_false_is_real(self):
        # 실모델 객체 생성만 — lazy라 모델은 안 올라간다(아래 lazy 테스트가 보증).
        self.assertIsInstance(get_embedder(stub=False), RealEmbedder)

    def test_env_flag_selects_stub(self):
        saved = os.environ.get(STUB_ENV_FLAG)
        os.environ[STUB_ENV_FLAG] = "stub"
        try:
            self.assertIsInstance(get_embedder(), StubEmbedder)
        finally:
            if saved is None:
                os.environ.pop(STUB_ENV_FLAG, None)
            else:
                os.environ[STUB_ENV_FLAG] = saved

    def test_env_flag_absent_is_real(self):
        saved = os.environ.get(STUB_ENV_FLAG)
        os.environ.pop(STUB_ENV_FLAG, None)
        try:
            self.assertIsInstance(get_embedder(), RealEmbedder)
        finally:
            if saved is not None:
                os.environ[STUB_ENV_FLAG] = saved

    def test_caches_instance_per_setting(self):
        # ★단일 인스턴스 캐시★: 같은 설정이면 같은 인스턴스를 재사용해 모델 중복 로딩을
        # 막는다(eval이 시나리오 8개마다 모델을 새로 올려 ~56s 낭비하던 회귀 방지).
        # 설정(stub True/False)이 다르면 별개 인스턴스.
        self.assertIs(get_embedder(stub=True), get_embedder(stub=True))
        self.assertIs(get_embedder(stub=False), get_embedder(stub=False))
        self.assertIsNot(get_embedder(stub=True), get_embedder(stub=False))


class RealEmbedderLazyTest(unittest.TestCase):
    def test_construct_does_not_load_model(self):
        # ★lazy 로드(§5)★: 생성만으로 모델을 올리지 않는다(_model is None).
        e = RealEmbedder()
        self.assertIsNone(e._model)
        self.assertEqual(e.model_name, REAL_MODEL_NAME)


if __name__ == "__main__":
    unittest.main()
