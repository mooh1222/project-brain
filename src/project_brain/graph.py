"""그래프 역인덱스·고립 탐지 — 인바운드(누가 나를 가리키는가) 분석.

store/lint/schema/build의 무결성 검사는 전부 아웃바운드(내가 가리키는 대상이 있나 =
dangling)만 본다. "아무도 나를 안 가리킴"(인바운드 0 = 고립)은 데이터 모델에 정의조차
없어, 역인덱스 1회 순회로 푼다. C1(`graph isolated` CLI)·C8(build 사후 고립 경고)이
이 모듈을 공유한다(역인덱스 중복 구현 금지).
"""

from project_brain.reference_fields import iter_object_refs
from project_brain.store import BrainStore

# 고립 점검 대상 — "가리켜지려고 존재하는 잎" kind. 나머지 kind는 구조적으로 인바운드 0이
# 정상이라(루트 source/synthesis/index/event/fact/review/domain 매핑·컨텍스트) 점검 대상에
# 넣으면 코퍼스 전체가 고립으로 폭주한다(plan critic 검수 정정 — truth_role 술어 금지).
# SpecRevision·SpecDocument·SlideRef도 설계상 잎이지만 데이터 레포 적재 여부 미확정(실측
# 조건)이라 기본에서 뺀다 — 필요하면 --kind로 지정. 빠져도 거짓 음성(안전측).
ISOLATION_LEAF_KINDS = frozenset({"CodeLocator", "GlossaryTerm", "EvidenceRef"})


def referenced_ids(store: BrainStore) -> set[str]:
    """store 1회 순회로 '한 번이라도 인바운드로 가리켜진' 객체 id 집합을 만든다(읽기 전용).

    공용 참조 registry가 찾은 id를 모은다. 자기 자신을 가리키는 self-ref는 인바운드로
    치지 않는다(supersedes 체인 등이 고립 판정을 왜곡하지 않게). C1·C8 공유 1차 헬퍼."""
    referenced: set[str] = set()
    for obj in store.all():
        oid = obj.get("id")
        for ref in iter_object_refs(obj):
            if ref.object_id != oid:
                referenced.add(ref.object_id)
    return referenced


def edges(store: BrainStore) -> list[tuple[str, str]]:
    """공용 참조 registry 기준 from→to 엣지 목록을 정렬해 반환한다(읽기 전용).

    referenced_ids와 같은 필드·self-ref 규칙을 공유하되, 양 끝이 store에 존재하는
    엣지만 만든다(끊긴 참조는 그릴 노드가 없다). 한 객체가 같은 대상을 여러 필드로
    가리켜도 엣지는 하나다. 시각화(graph export)가 isolated와 같은 엣지 정의를 쓰게
    하는 단일 출처."""
    ids = {obj["id"] for obj in store.all() if obj.get("id")}
    result: set[tuple[str, str]] = set()
    for obj in store.all():
        oid = obj.get("id")
        if oid not in ids:        # from도 store에 존재해야 한다(id 없는 객체 제외) — to 가드와 대칭
            continue
        for ref in iter_object_refs(obj):
            if ref.object_id != oid and ref.object_id in ids:
                result.add((oid, ref.object_id))
    return sorted(result)


def find_isolated(store: BrainStore, kinds=None) -> list[str]:
    """점검 대상 kind 중 인바운드 0(아무도 안 가리킴)인 객체 id를 정렬해 반환한다. 읽기 전용.

    kinds=None이면 ISOLATION_LEAF_KINDS(기본 잎 kind), 아니면 주어진 kind 집합으로 한정.
    구조적 인바운드0 kind(CurrentView·Insight·IndexRecord 등)는 기본 대상에서 빠져 폭주하지 않는다."""
    target_kinds = ISOLATION_LEAF_KINDS if kinds is None else set(kinds)
    referenced = referenced_ids(store)
    return sorted(
        obj["id"] for obj in store.all()
        if obj.get("kind") in target_kinds and obj["id"] not in referenced
    )
