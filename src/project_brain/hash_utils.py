"""공유 해시 유틸리티.

context_projection.py 와 lint.py 에서 동일한 해시 계산 로직을 사용하기 위해 추출한 모듈.
두 곳이 다른 함수를 사용하면 해시 값이 달라지는 드리프트 위험이 생기므로 여기서 단일 구현을 유지한다.
"""

import hashlib
import json


def sha256_text(text: str) -> str:
    """UTF-8 인코딩 텍스트에 대한 SHA-256 헥스 다이제스트를 반환한다."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_json(obj: dict) -> str:
    """dict를 키 정렬·ASCII 비이스케이프·최소 공백 형식으로 직렬화한다."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
