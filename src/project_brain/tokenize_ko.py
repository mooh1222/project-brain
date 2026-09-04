"""한국어+심볼 토크나이저 (스펙 §6).

★단일 공유 함수★ tokenize() 하나만 색인과 쿼리가 함께 쓴다(대칭 보장).
모듈 밖에서 다른 분리 로직을 두지 않는다 — 색인 쪽과 쿼리 쪽이 다른 토큰화를
하면 매칭이 깨진다(스펙 §6 "색인·쿼리 비대칭 발동이 진짜 위험").

토큰화 두 축:
1. 영문 심볼 분리 = 한국어와 동등한 1급. camelCase / snake_case·대문자 약어 /
   `::` / 경로 구분자(/, .)를 쪼개고, ★원형 토큰도 함께 보존★한다.
2. 한국어 형태소 = ★kiwipiepy 단일 백엔드★(#79). 형태소 조각에 더해 같은 어절 안에서
   연속한 명사 조각을 이어 붙인 결합형 토큰도 보존한다 — 심볼에서 camelCase 조각과
   원형을 같이 남기는 것과 같은 규칙이다. 폴백 사다리는 없다: 설치 환경마다 다른
   토큰이 나오면 색인↔쿼리가 조용히 어긋나므로, 없으면 폴백이 아니라 오류다.
   정규식 분리는 backend="regex" 명시 주입(테스트) 전용으로만 남는다.

active_backend()로 현재 백엔드를 노출하고, tokenizer_signature()가 백엔드 이름과
규칙 버전을 묶어 색인 meta 기록·색인↔쿼리 불일치 거부에 쓴다(§4·§6).
"""

import re
from itertools import groupby

# 토큰 산출 규칙의 버전. ★백엔드 이름이 같아도 규칙이 바뀌면 옛 색인의 토큰과 새 질의의
# 토큰이 조용히 어긋난다★ — 규칙(분리 방식·보존 토큰 종류 등)을 바꿀 때 올린다.
# 올리면 기존 색인은 검색 진입에서 StaleIndexError로 거부되고 rebuild가 필요해진다.
# 버전 1 = 형태소 표면만. 버전 2 = 어절 안 명사 결합형 토큰 추가(#79) — 실제로 산출
# 토큰이 늘어난 규칙 변경이라 change map "한국어 tokenizer" 행의 실모델 rebuild가 발동한다.
TOKENIZER_RULES_VERSION = 2

# meta에 적는 정체성 문자열의 구분자. 이름에는 쓰이지 않는 문자여야 한다.
_SIGNATURE_SEP = "@"

# 유일한 한국어 형태소 백엔드 이름. 정규식은 테스트 주입 전용이라 기본이 될 수 없다.
_KIWI_BACKEND = "kiwipiepy"
_REGEX_BACKEND = "regex"

# 활성 백엔드 이름과 분리 함수. import 시가 아니라 첫 사용 때 1회 결정·캐시한다
# (Kiwi 로드가 ~0.5초라 import만으로 물리지 않게).
_BACKEND_NAME: str | None = None
_KOREAN_SPLITTER = None
# backend="kiwipiepy" 명시 주입과 기본 경로가 같은 Kiwi 인스턴스를 쓰도록 따로 캐시한다.
_KIWI_SPLITTER = None

# 결합형을 만들 수 있는 kiwi 품사 태그 — 명사류만(spec #72에서 프로토타입으로 확정).
# NNG 일반명사 / NNP 고유명사 / NNB 의존명사 / XR 어근 / SL 외국어 / SN 숫자.
# 조사·어미·동사 조각은 여기 없으므로 결합에 섞이지 않는다.
_COMPOUND_TAGS = frozenset({"NNG", "NNP", "NNB", "XR", "SL", "SN"})

# 한글 연속을 잡는 정규식 (정규식 분리·한글 토큰 필터 공통).
_HANGUL_RUN = re.compile(r"[가-힣]+")
# camelCase 경계: 소문자→대문자, 또는 약어 끝 대문자→대문자+소문자(HTTPServer→HTTP, Server).
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _eojeol_surfaces(tokens) -> list[str]:
    """한 어절의 형태소 토큰들 → 조각 표면들 + 그 어절의 명사 결합형들 (#79).

    ★조각을 지우지 않고 결합형을 더한다★ — "인게임"으로 물어도 "게임"으로 물어도
    같은 문서가 잡혀야 하기 때문이다. 연속한 명사류 조각이 2개 이상일 때만 이어 붙이고,
    조사·어미·동사 조각이나 한글 없는 조각이 나오면 연속이 끊긴다. 결합형은 그 어절의
    조각들 뒤에 붙인다(spec #72 프로토타입 출력 순서).
    """
    surfaces: list[str] = []
    compounds: list[str] = []
    run: list[str] = []

    for token in tokens:
        form = token.form
        if not form:
            continue
        surfaces.append(form)
        if token.tag in _COMPOUND_TAGS and _HANGUL_RUN.search(form):
            run.append(form)
            continue
        if len(run) > 1:
            compounds.append("".join(run))
        run = []

    if len(run) > 1:
        compounds.append("".join(run))
    return surfaces + compounds


def _build_kiwi_splitter():
    """kiwipiepy Kiwi를 1회 로드해 어절 단위 분리 함수를 만든다 (#79 단일 백엔드).

    기본 옵션만 쓴다 — 사용자 사전·오타 교정은 켜지 않는다(spec #72 Out of Scope).
    설치돼 있지 않으면 조용히 폴백하지 않고 오류로 알린다: 사람마다 다른 토큰이 나오면
    색인과 질의가 어긋나 잘못된 회수 결과가 정상처럼 보인다.
    """
    try:
        from kiwipiepy import Kiwi  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "한국어 토크나이저 백엔드 kiwipiepy를 import할 수 없다 — 폴백은 없다"
            "(§6 색인↔쿼리 대칭). `uv sync` 또는 "
            "`uv tool install -e . --force`로 고정 버전을 설치한다."
        ) from exc

    kiwi = Kiwi()

    def split(text: str) -> list[str]:
        # ★전체 문맥을 한 번에 넘긴다★ — "미나의"만 떼서 주면 동사 읽기로 오분석되지만
        # "미나의 카약 ..." 전체를 주면 인명+조사로 바르게 쪼갠다(형태소 중의성, 실측).
        # 어절 경계는 (문장 번호, 어절 번호)다 — word_position은 문장마다 0부터 다시
        # 시작하므로 문장 번호를 함께 묶지 않으면 문장 경계에서 어절이 합쳐진다.
        tokens: list[str] = []
        for _, group in groupby(
            kiwi.tokenize(text), key=lambda t: (t.sent_position, t.word_position)
        ):
            tokens.extend(_eojeol_surfaces(list(group)))
        return tokens

    return split


def _kiwi_splitter():
    """Kiwi 분리 함수의 모듈 캐시 — 인스턴스를 1회만 로드한다."""
    global _KIWI_SPLITTER
    if _KIWI_SPLITTER is None:
        _KIWI_SPLITTER = _build_kiwi_splitter()
    return _KIWI_SPLITTER


def _regex_splitter(text: str) -> list[str]:
    """테스트 주입 전용: 형태소 분리 없이 한글 연속 덩어리들을 그대로 토큰으로 둔다."""
    return _HANGUL_RUN.findall(text)


def _ensure_default_backend() -> None:
    global _BACKEND_NAME, _KOREAN_SPLITTER
    if _BACKEND_NAME is None:
        _BACKEND_NAME, _KOREAN_SPLITTER = _KIWI_BACKEND, _kiwi_splitter()


def active_backend() -> str:
    """현재 활성 한국어 형태소 백엔드 이름 — 정상 경로에서는 항상 "kiwipiepy".

    색인 meta 기록·색인↔쿼리 불일치 판정용(스펙 §4·§6). 테스트가 모듈 전역을
    "regex"로 바꿔치기하는 주입 경로가 있어 값은 전역을 그대로 읽는다.
    """
    _ensure_default_backend()
    assert _BACKEND_NAME is not None
    return _BACKEND_NAME


def tokenizer_signature() -> str:
    """색인 meta에 적는 현재 토크나이저 정체성 — "<백엔드 이름>@<규칙 버전>".

    이름만으로는 규칙 변경(같은 백엔드, 다른 토큰)을 감지할 수 없어 규칙 버전을
    함께 담는다. 색인 스키마는 그대로 두고 기존 tokenizer 컬럼의 값 형태만 넓힌다.
    """
    return f"{active_backend()}{_SIGNATURE_SEP}{TOKENIZER_RULES_VERSION}"


def parse_tokenizer_signature(value: str) -> tuple[str, int]:
    """meta에 저장된 토크나이저 값을 (백엔드 이름, 규칙 버전)으로 읽는다.

    ★규칙 버전 표기가 없는 값은 규칙 버전 1로 읽는다★ — 규칙 버전을 도입하기 전에
    만들어진 색인(이름만 기록)은 버전 1 규칙으로 만들어진 것이기 때문이다. 현재 규칙은
    2(#79 결합형 토큰)라 그런 색인은 호출부에서 불일치로 거부되고 rebuild가 필요하다.
    정수가 아닌 꼬리표는 해석하지 않고 값 전체를 이름으로 본다(불일치로 거부됨).
    """
    name, sep, version = value.rpartition(_SIGNATURE_SEP)
    if not sep:
        return value, 1
    try:
        return name, int(version)
    except ValueError:
        return value, 1


def _korean_splitter_for(backend: str | None):
    """backend 인자가 주어지면 그 백엔드 분리 함수를, 없으면 캐시된 기본값을 쓴다.

    테스트가 형태소 분리 없는 경로를 kiwipiepy 있는 환경에서도 강제하기 위한
    주입 지점(§10).
    """
    if backend is None:
        _ensure_default_backend()
        return _KOREAN_SPLITTER
    if backend == _REGEX_BACKEND:
        return _regex_splitter
    if backend == _KIWI_BACKEND:
        return _kiwi_splitter()
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

    한글은 kiwipiepy(또는 강제 backend)로, 영문 심볼은 심볼 규칙으로 분리한다.
    한국어 백엔드에는 ★전체 텍스트를 한 번에★ 넘겨 형태소 중의성을 문맥으로 해소한다.
    모든 토큰은 소문자로 정규화(대소문자 무관 매칭). 등장 순서를 보존하되 중복 제거.

    backend: None이면 캐시된 기본 백엔드(kiwipiepy). "regex"는 테스트가 형태소 분리
    없는 경로를 강제할 때만 쓴다.
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
