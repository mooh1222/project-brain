"""그래프 역인덱스·고립 탐지 — 인바운드(누가 나를 가리키는가) 분석.

store/lint/schema/build의 무결성 검사는 전부 아웃바운드(내가 가리키는 대상이 있나 =
dangling)만 본다. "아무도 나를 안 가리킴"(인바운드 0 = 고립)은 데이터 모델에 정의조차
없어, 역인덱스 1회 순회로 푼다. C1(`graph isolated` CLI)·C8(build 사후 고립 경고)이
이 모듈을 공유한다(역인덱스 중복 구현 금지).
"""

from project_brain.store import BrainStore

# 인바운드 엣지 필드 — 값이 brain 객체 id(또는 id 리스트)인 필드만 단·복수 모두 명시 열거.
# 접미사 매칭(_id/_ids) 금지: 외부 키가 섞여 거짓 인바운드를 만든다. 정본 추출 근거 =
# lint.py의 dangling 검사 참조 필드 ∪ schema.py의 단수 _id ∪ 실측(bb2_client 2444객체)으로
# 확인한 vouched_by_mapping_ids·related_objects. evidence_refs는 search의 _GRAPH_EDGE_FIELDS와
# 달리 포함한다 — EvidenceRef는 그것으로만 가리켜지므로 빼면 전부 거짓 고립이 된다.
# 의도적 제외(brain 객체 참조가 아님): channel_id(외부 Slack 채널)·project_id(프로젝트 키
# 문자열)·jira_issue_ids(외부 Jira 키, JiraIssue kind 없음). slide_refs·message_refs는
# 구조 모양이 미확인(데이터 레포에 SpecRevision·SlackThread 부재)이라 보수적으로 뺀다.
INBOUND_REF_FIELDS = frozenset({
    # 단수 (값 = 객체 id 하나)
    "context_id", "evidence_manifest_id", "derived_from_event_id",
    "spec_document_id", "spec_revision_id", "target_object_id",
    "source_object_id", "review_record_id",
    # 복수 (값 = 객체 id 리스트)
    "evidence_refs", "glossary_term_ids", "source_object_ids",
    "source_fact_ids", "source_event_ids", "decision_record_ids",
    "spec_revision_ids", "code_locator_ids", "supersedes_mapping_ids",
    "affected_context_ids", "affected_mapping_ids", "affected_glossary_term_ids",
    "target_object_ids", "vouched_by_mapping_ids", "related_objects",
    "slack_thread_ids",
})

# 고립 점검 대상 — "가리켜지려고 존재하는 잎" kind. 나머지 kind는 구조적으로 인바운드 0이
# 정상이라(루트 source/synthesis/index/event/fact/review/domain 매핑·컨텍스트) 점검 대상에
# 넣으면 코퍼스 전체가 고립으로 폭주한다(plan critic 검수 정정 — truth_role 술어 금지).
# SpecRevision·SpecDocument·SlideRef도 설계상 잎이지만 데이터 레포 적재 여부 미확정(실측
# 조건)이라 기본에서 뺀다 — 필요하면 --kind로 지정. 빠져도 거짓 음성(안전측).
ISOLATION_LEAF_KINDS = frozenset({"CodeLocator", "GlossaryTerm", "EvidenceRef"})


def _iter_ref_ids(value):
    """인바운드 필드 값에서 id 문자열을 뽑는다(단수 문자열·문자열 리스트만; dict 등 무시)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for el in value:
            if isinstance(el, str):
                yield el


def referenced_ids(store: BrainStore) -> set[str]:
    """store 1회 순회로 '한 번이라도 인바운드로 가리켜진' 객체 id 집합을 만든다(읽기 전용).

    각 객체의 INBOUND_REF_FIELDS 값에 담긴 id를 모은다. 자기 자신을 가리키는 self-ref는
    인바운드로 치지 않는다(supersedes 체인 등이 고립 판정을 왜곡하지 않게). C1·C8 공유 1차 헬퍼."""
    referenced: set[str] = set()
    for obj in store.all():
        oid = obj.get("id")
        for field in INBOUND_REF_FIELDS:
            value = obj.get(field)
            if value is None:
                continue
            for ref in _iter_ref_ids(value):
                if ref != oid:
                    referenced.add(ref)
    return referenced


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
