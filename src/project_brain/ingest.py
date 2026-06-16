"""범용 적재 진입점 — 도메인 무지(domain-agnostic).

bundle을 받아 per-object schema validate → merged store lint → save 를 원자적으로
묶는다(spec §3.1, §4.2). 어느 게이트든 실패하면 IngestError를 raise하고 아무것도
쓰지 않는다. 멱등 갱신은 허용하고, reviewed→candidate 후퇴만 진입점에서 거부한다
(유일 신규 로직, spec §4.1). 엔진 부품(validate_object/lint_store/BrainStore)을
재사용하며 도메인 상수는 두지 않는다.
"""

from project_brain.lint import lint_store
from project_brain.schema import validate_object
from project_brain.store import BrainStore


class IngestError(RuntimeError):
    pass


def ingest(brain_root, objects, preconditions=None):
    # 1) per-object schema validation (bundle 전체 선검사)
    errors = []
    for obj in objects:
        errors.extend(validate_object(obj))
    if errors:
        raise IngestError("; ".join(errors))
    # 후퇴 가드 + preconditions 재검사 (저장 직전 TOCTOU 방지)
    existing = BrainStore.load(brain_root)
    for obj in objects:
        if existing.has(obj["id"]):
            prev = existing.get(obj["id"])
            if prev.get("status") == "reviewed" and obj.get("status") == "candidate":
                raise IngestError(f"{obj['id']}: refuse reviewed→candidate demotion")
    for oid, expected in (preconditions or {}).items():
        if existing.has(oid) and existing.get(oid).get("updated_at") != expected:
            raise IngestError(
                f"{oid}: precondition 불일치 — build 기대 updated_at {expected!r} != "
                f"현재 {existing.get(oid).get('updated_at')!r} (build 이후 store가 바뀜, 재build 필요)")
    # 2) merged store lint
    merged = {o["id"]: o for o in existing.all()}
    for obj in objects:
        merged[obj["id"]] = obj
    problems = lint_store(BrainStore(merged))
    if problems:
        raise IngestError("; ".join(problems))
    # 3) 통과 후에만 쓰기
    for obj in objects:
        BrainStore.save_object(brain_root, obj)
