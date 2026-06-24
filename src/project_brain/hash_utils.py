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


# 시각·버전 메타: 의미가 안 바뀌어도 갱신돼 source_content_hash를 깨던 필드들.
# created_at/updated_at/verified_at의 일괄 갱신(KST 표준화)이 projection을 stale로
# 오판해 eval 10→8 회귀를 냈다. schema_version은 스키마 버전 bump마다 전 projection이
# stale로 폭주하는 것을 막으려 함께 제외한다(_at 버그 범위를 넘는 의도적 확장).
HASH_EXCLUDE_KEYS = frozenset({
    "created_at", "updated_at", "verified_at", "captured_at", "schema_version",
})


def source_content_hash(objects) -> str:
    """source 객체들의 의미 내용으로 ContextProjection.source_content_hash를 계산한다.

    시각·버전 메타(HASH_EXCLUDE_KEYS)는 제외한다 — 의미가 그대로면 _at 갱신만으로
    projection이 stale로 오판되지 않게. 생성식(context_projection)·검증식(lint)이 이
    단일 함수를 공유해야 두 해시 공식이 어긋나지 않는다(드리프트 금지).

    context_md projection 소스(DomainContext·GlossaryTerm·DomainMapping)의 자동기입
    시각필드는 BASE의 created_at/updated_at뿐이라 전부 덮인다. build-reuse는 임의 kind를
    받지만(CodeLocator.verified_at·EvidenceManifest/SpecRevision.captured_at도 덮임),
    미덮인 시각필드가 있어도 최악은 불필요한 재생성(안전측 실패)이다.
    """
    return sha256_text("\n".join(
        stable_json({k: v for k, v in obj.items() if k not in HASH_EXCLUDE_KEYS})
        for obj in objects
    ))
