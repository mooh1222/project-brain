"""임베더 (스펙 §3.3·§5, 슬라이스 3).

spec: docs/superpowers/specs/2026-06-10-project-brain-search-layer-design.md

표면 텍스트를 1024차원 L2 정규화 벡터로 만든다. 색인 빌드와 쿼리가 ★같은
임베더 경로★를 써야 매칭이 성립하므로 get_embedder() 팩토리 하나로만 만든다.

두 종류:
1. RealEmbedder — bge-m3 로컬(sentence-transformers). ★lazy 로드★: import·생성
   시점에는 모델을 안 올리고, 첫 임베딩 또는 identity 조회에서 1회 로드 후 상주한다(§5·§11).
   로드 비용이 크므로(초회 수 초~수십 초) 색인 배치·세션 반복 질의에 분할 상환.
2. StubEmbedder — 텍스트 SHA-256 시드 가짜 벡터(결정론). 모델·네트워크 없이
   테스트가 결정론으로 돈다(§5). 같은 텍스트→같은 벡터, L2 노름≈1 유지.

★실모델 결정론 가드(§5)★: 모델 로드 시 torch 스레드 수를 1로 고정한다(BLAS·스레드에
따라 부동소수점 하위 비트가 흔들려 top-K 경계가 바뀌는 것을 줄임). 거리/유사도 값은
search_vector에서 소수 6자리 반올림 후 정렬에 쓴다.
"""

import hashlib
import json
import os
from importlib.metadata import version

import numpy as np

# 임베딩 차원. bge-m3는 1024차원(§3.3·§5). vec0 테이블 FLOAT[1024]와 일치해야 함.
EMBED_DIM = 1024

# 실모델 식별자. meta.embed_model 기록용(§4). stub은 "stub:..." 접두로 구분(§5).
REAL_MODEL_NAME = "BAAI/bge-m3"
# Immutable Hugging Face artifact revision; upgrade deliberately.
REAL_MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
MAX_SEQUENCE_LENGTH = 2048
STUB_MODEL_NAME = "stub:sha256-gaussian"

# 환경 플래그: 색인 빌드·테스트에서 stub을 강제(CI·결정론, §5).
STUB_ENV_FLAG = "PROJECT_BRAIN_EMBEDDER"


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    """L2 정규화. 0벡터는 그대로 둔다(0 나눗셈 방지)."""
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        return vec
    return vec / norm


class StubEmbedder:
    """텍스트 SHA-256 시드 가짜 벡터(결정론, 모델 없이 테스트 §5).

    같은 텍스트→같은 벡터, L2 노름≈1. 의미는 담지 못하므로 회귀 가드 전용이다
    (의미 회상 품질은 슬라이스 3.5 실모델 측정 — 스펙 §5·§8).
    """

    model_name = STUB_MODEL_NAME

    def __init__(self, dim: int = EMBED_DIM):
        self._dim = dim

    @property
    def embedding_identity(self) -> str:
        return f"{self.model_name}:v1:dim={self._dim}:numpy={np.__version__}"

    def embed(self, text: str) -> np.ndarray:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        vec = rng.standard_normal(self._dim).astype(np.float32)
        return _l2_normalize(vec)

    def embed_many(self, texts: list[str]) -> list[np.ndarray]:
        return [self.embed(t) for t in texts]


class RealEmbedder:
    """bge-m3 로컬 임베더 (sentence-transformers, lazy 로드 §5).

    생성 시점엔 모델을 안 올린다. 첫 embed/embed_many 또는 embedding_identity 조회에서
    1회 로드 후 상주한다.
    """

    model_name = REAL_MODEL_NAME

    def __init__(self):
        self._model = None  # lazy — 첫 호출에서 로드

    def _ensure_model(self):
        if self._model is not None:
            return
        # ★결정론 가드(§5)★: 스레드 수를 1로 고정한 뒤 모델을 올린다.
        try:
            import torch  # type: ignore

            torch.set_num_threads(1)
        except Exception:
            # torch 없이도 sentence-transformers가 동작할 수 있으면 진행(스레드 고정만 생략).
            pass
        from sentence_transformers import SentenceTransformer  # type: ignore

        self._model = SentenceTransformer(self.model_name, revision=REAL_MODEL_REVISION)
        # ★메모리 방어선★: 청커의 approx_tokens는 ASCII 단어, 한글 글자 하나씩, 나머지
        # 비공백 기호 두 글자당 하나를 보수적으로 센다. 그래도 이 근사식은 실제 BAAI/bge-m3
        # tokenizer와 같지 않아 일부 입력은 실토큰 수가 더 클 수 있으므로, 2048 상한이 MPS
        # 메모리의 최종 방어선이다. 이 상한이 없으면 긴 청크가 배치에 섞일 때 어텐션 버퍼가
        # Metal(MPS) 한계를 넘어 죽을 수 있다(2026-07-17 실측 — 방해버블 기획서 raw 90건에서
        # "Invalid buffer size: 24.29 GiB"). 당시 512-근사 청크는 실토큰이 한글 기준
        # 약 1000-2000까지 커졌고, 2048 절단이 생겨도 손실은 입력 꼬리에만 한정된다.
        # 색인·질의가 같은 임베더를 쓰므로 결정론에 영향 없음(같은 텍스트 → 같은 벡터).
        self._model.max_seq_length = MAX_SEQUENCE_LENGTH

    @property
    def embedding_identity(self) -> str:
        # Load is permitted on a full hit: the identity describes the actual execution
        # configuration as well as the pinned model/tokenizer/pooling artifact.
        self._ensure_model()
        return json.dumps({
            "model": self.model_name,
            "revision": REAL_MODEL_REVISION,
            "max_seq_length": self._model.max_seq_length,
            "normalize_embeddings": True,
            "output_dtype": "float32",
            "dimension": EMBED_DIM,
            "device": str(self._model.device),
            "model_dtype": str(self._model.dtype),
            "implementation": 2,
            "packages": {name: version(name) for name in (
                "sentence-transformers", "transformers", "torch", "numpy",
            )},
        }, sort_keys=True)

    def embed(self, text: str) -> np.ndarray:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[np.ndarray]:
        self._ensure_model()
        # normalize_embeddings=True로 L2 정규화된 1024차원 벡터를 받는다(§3.3).
        # One sample per model batch makes padding and kernel shape independent of
        # other miss surfaces. With batch_size=8 the same text differed by ~1e-7
        # between mixed and single-text calls on MPS, violating exact vector reuse.
        # The rebuild still submits all misses through one embed_many/encode call.
        arr = self._model.encode(
            texts, batch_size=1, normalize_embeddings=True, convert_to_numpy=True
        )
        return [row.astype(np.float32) for row in arr]


_EMBEDDER_CACHE: dict[bool, object] = {}


def get_embedder(stub: bool | None = None):
    """임베더 팩토리 — 색인 빌드와 쿼리가 같은 경로를 쓰게 하는 단일 진입점(§5).

    stub: None이면 환경 플래그(PROJECT_BRAIN_EMBEDDER=stub)로 판정, True/False면 명시 선택.
    같은 설정(stub True/False)이면 인스턴스를 캐시해 재사용한다 — 임베더는 stateless이고
    실모델 로딩이 ~8s라, 한 프로세스에서 여러 번 부르는 eval이 시나리오마다 모델을 새로
    올리던 낭비(~56s)를 없앤다. 모델 적재 자체는 RealEmbedder의 lazy 로드가 그대로 담당한다.
    """
    if stub is None:
        stub = os.environ.get(STUB_ENV_FLAG, "").strip().lower() == "stub"
    if stub not in _EMBEDDER_CACHE:
        _EMBEDDER_CACHE[stub] = StubEmbedder() if stub else RealEmbedder()
    return _EMBEDDER_CACHE[stub]
