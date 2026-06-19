"""한국어+심볼 토크나이저 (스펙 §6).

★단일 공유 함수★ tokenize() 하나만 색인과 쿼리가 함께 쓴다(대칭 보장).
모듈 밖에서 다른 분리 로직을 두지 않는다 — 색인 쪽과 쿼리 쪽이 다른 토큰화를
하면 매칭이 깨진다(스펙 §6 "색인·쿼리 비대칭 발동이 진짜 위험").

토큰화 두 축:
1. 영문 심볼 분리 = 한국어와 동등한 1급. camelCase / snake_case·대문자 약어 /
   `::` / 경로 구분자(/, .)를 쪼개고, ★원형 토큰도 함께 보존★한다.
2. 한국어 형태소 폴백 사다리 = mecab-ko(1순위) → kiwipiepy(2순위, import 시도만)
   → 정규식(한글 연속, 최후). 백엔드는 모듈 로드 시 1회 결정·캐시한다.

active_backend()로 현재 백엔드를 노출해 색인 meta 기록·비대칭 경고에 쓴다(§4·§6).
"""

import re

# 형태소 백엔드별로 한글 연속 덩어리를 분리하는 함수. 모듈 로드 시 1회 결정·캐시.
_BACKEND_NAME: str | None = None
_KOREAN_SPLITTER = None

# mecab-ko 사전·설정 경로 후보. brew 경로를 1순위로 자동 탐지한다(스펙 §6 환경 실측).
_MECAB_RC_CANDIDATES = ("/opt/homebrew/etc/mecabrc", "/usr/local/etc/mecabrc")
_MECAB_DIC_CANDIDATES = (
    "/opt/homebrew/lib/mecab/dic/mecab-ko-dic",
    "/usr/local/lib/mecab/dic/mecab-ko-dic",
)

# 한글 연속을 잡는 정규식 (정규식 폴백·한글 토큰 필터 공통).
_HANGUL_RUN = re.compile(r"[가-힣]+")
# camelCase 경계: 소문자→대문자, 또는 약어 끝 대문자→대문자+소문자(HTTPServer→HTTP, Server).
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _build_mecab_splitter():
    """mecab-ko Tagger를 사전 경로 후보로 탐지해 한글 분리 함수를 만든다.

    경로 명시 없이는 RuntimeError가 나므로(스펙 §6 환경 실측) -r mecabrc -d 사전
    인자를 붙여 호출한다. 실패하면 None을 반환해 다음 폴백으로 넘어간다.
    """
    import os

    try:
        import MeCab  # type: ignore
    except Exception:
        return None

    rc = next((p for p in _MECAB_RC_CANDIDATES if os.path.exists(p)), None)
    dic = next((p for p in _MECAB_DIC_CANDIDATES if os.path.exists(p)), None)
    if rc is None or dic is None:
        return None

    try:
        tagger = MeCab.Tagger(f"-r {rc} -d {dic}")
        # 로드 직후 1회 파싱으로 실제 동작 확인(경로 연결 실패는 여기서 드러남).
        tagger.parse("확인")
    except Exception:
        return None

    def split(text: str) -> list[str]:
        # mecab 출력은 "표면\t품질,..." 줄들 + 마지막 EOS. 표면(surface)만 취한다.
        # ★전체 문맥을 한 번에 넘긴다★ — "미나의"만 떼서 주면 동사 읽기로 오분석되지만
        # "미나의 카약 ..." 전체를 주면 인명+조사로 바르게 쪼갠다(형태소 중의성, 실측).
        tokens: list[str] = []
        for line in tagger.parse(text).splitlines():
            if line == "EOS" or not line:
                continue
            surface = line.split("\t", 1)[0]
            if surface:
                tokens.append(surface)
        return tokens

    return split


def _build_kiwi_splitter():
    """kiwipiepy 백엔드. 설치돼 있으면 형태소 표면을 분리한다(import 시도만)."""
    try:
        from kiwipiepy import Kiwi  # type: ignore
    except Exception:
        return None

    try:
        kiwi = Kiwi()
        kiwi.tokenize("확인")
    except Exception:
        return None

    def split(text: str) -> list[str]:
        return [t.form for t in kiwi.tokenize(text) if t.form]

    return split


def _regex_splitter(text: str) -> list[str]:
    """최후 폴백: 형태소 분리 없이 한글 연속 덩어리들을 그대로 토큰으로 둔다."""
    return _HANGUL_RUN.findall(text)


def _resolve_backend() -> tuple[str, object]:
    """폴백 사다리로 백엔드를 1회 결정한다 (mecab-ko → kiwipiepy → regex)."""
    splitter = _build_mecab_splitter()
    if splitter is not None:
        return "mecab-ko", splitter
    splitter = _build_kiwi_splitter()
    if splitter is not None:
        return "kiwipiepy", splitter
    return "regex", _regex_splitter


def _ensure_default_backend() -> None:
    global _BACKEND_NAME, _KOREAN_SPLITTER
    if _BACKEND_NAME is None:
        _BACKEND_NAME, _KOREAN_SPLITTER = _resolve_backend()


def active_backend() -> str:
    """현재 활성 한국어 형태소 백엔드 이름 ("mecab-ko" | "kiwipiepy" | "regex").

    색인 meta 기록·비대칭 경고용(스펙 §4·§6).
    """
    _ensure_default_backend()
    assert _BACKEND_NAME is not None
    return _BACKEND_NAME


def _korean_splitter_for(backend: str | None):
    """backend 인자가 주어지면 그 백엔드 분리 함수를, 없으면 캐시된 기본값을 쓴다.

    테스트가 정규식 폴백 경로를 mecab 있는 환경에서도 강제하기 위한 주입 지점(§10).
    """
    if backend is None:
        _ensure_default_backend()
        return _KOREAN_SPLITTER
    if backend == "regex":
        return _regex_splitter
    if backend == "mecab-ko":
        return _build_mecab_splitter() or _regex_splitter
    if backend == "kiwipiepy":
        return _build_kiwi_splitter() or _regex_splitter
    raise ValueError(f"알 수 없는 backend: {backend}")


# 심볼 세그먼트: 영숫자 + 심볼 구분자(_ :: / .). 최소 한 글자의 영숫자를 포함해야 한다.
_SYMBOL_SEGMENT = re.compile(r"[A-Za-z0-9]+(?:[_:./]+[A-Za-z0-9]+)*")
# 심볼 세그먼트 내부 구분자 (snake_case·:: ·경로·확장자).
_SYMBOL_SEP = re.compile(r"[_:./]+")


def _split_symbol(segment: str) -> list[str]:
    """심볼 세그먼트를 의미 토큰으로 쪼개고 ★원형 토큰도 보존★한다 (스펙 §6).

    처리 대상: camelCase(`onClickNewRace`) / snake_case·대문자 약어
    (`MINA_KAYAK_RACE_STATUS`) / `::`(`A::b`) / 경로·확장자(`a/b/c.cpp`).
    구분자로 나뉜 각 조각은 다시 camelCase로 쪼개고, 분리가 실제로 일어났으면
    구분자 조각의 소문자 원형(`getracestatus`)과 세그먼트 전체 원형
    (`mina_kayak_race_status`)을 함께 더한다.
    """
    tokens: list[str] = []
    parts = [p for p in _SYMBOL_SEP.split(segment) if p]
    had_separator = len(parts) > 1

    for part in parts:
        camel = [c.lower() for c in _CAMEL_BOUNDARY.split(part) if c]
        tokens.extend(camel)
        # 구분자 조각이 camelCase로 더 쪼개졌으면 그 조각의 소문자 원형도 보존.
        if len(camel) > 1:
            tokens.append(part.lower())

    # 구분자(_ :: / .)로 나뉜 세그먼트는 전체 소문자 원형도 보존.
    if had_separator:
        tokens.append(segment.lower())

    return tokens


def tokenize(text: str, backend: str | None = None) -> list[str]:
    """텍스트를 검색 토큰 리스트로 분리한다 (색인·쿼리 공유 단일 함수, 스펙 §6).

    한글은 형태소 백엔드(또는 강제 backend)로, 영문 심볼은 심볼 규칙으로 분리한다.
    한국어 백엔드에는 ★전체 텍스트를 한 번에★ 넘겨 형태소 중의성을 문맥으로 해소한다.
    모든 토큰은 소문자로 정규화(대소문자 무관 매칭). 등장 순서를 보존하되 중복 제거.

    backend: None이면 캐시된 기본 백엔드. "regex"/"mecab-ko"/"kiwipiepy"로 강제 주입
    가능(테스트용).
    """
    if not text:
        return []

    tokens: list[str] = []

    # 1) 한국어 형태소: 전체 텍스트를 백엔드에 한 번 넘기고, 한글 포함 표면만 취한다
    #    (영문은 아래 심볼 경로가 1급으로 처리하므로 백엔드의 비한글 출력은 버린다).
    korean_split = _korean_splitter_for(backend)
    for surface in korean_split(text):
        if _HANGUL_RUN.search(surface):
            tokens.append(surface)

    # 2) 영문 심볼: 심볼 세그먼트마다 분리 + 원형 보존.
    for match in _SYMBOL_SEGMENT.finditer(text):
        tokens.extend(_split_symbol(match.group(0)))

    # 등장 순서 보존 + 중복 제거.
    seen: set[str] = set()
    result: list[str] = []
    for tok in tokens:
        if tok and tok not in seen:
            seen.add(tok)
            result.append(tok)
    return result
