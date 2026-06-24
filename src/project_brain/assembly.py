"""범용 조립 코어 — 구조화 노트 → brain 객체 묶음.

판정은 에이전트(노트 작성), 변환은 기계적(이 모듈). supersede/강등/충돌 해소/이력
판정은 하지 않는다. objbase.base 위에 kind별 변환 + refs + updates + 2층 검증을 얹는다.
저장은 절대 안 한다 — build()는 객체 묶음 + diff만 반환하고 ingest가 저장한다.
"""
import copy

from project_brain.objbase import base
from project_brain.schema import validate_object
from project_brain.lint import lint_store
from project_brain.graph import ISOLATION_LEAF_KINDS, referenced_ids
from project_brain.store import BrainStore

# id 파생 규칙 (kind → prefix). 컨벤션: g.<ctx>.<key> / mapping.<ctx>.<key> 등.
_ID_PREFIX = {
    "GlossaryTerm": "g",
    "DomainMapping": "mapping",
    "CodeLocator": "code",
    "EvidenceRef": "evref",
    "DecisionRecord": "decision",
    "DomainContext": "context",
}


def derive_id(kind, ctx, key):
    """kind+컨텍스트+key로 객체 id를 만든다. 규칙은 _ID_PREFIX 고정."""
    return f"{_ID_PREFIX[kind]}.{ctx}.{key}"


def build_glossary_terms(notes, now):
    """노트의 glossary[] 항목을 reviewed GlossaryTerm 객체로 변환한다."""
    ctx = notes["context"]["key"]
    out = []
    for g in notes.get("glossary", []):
        obj = {
            "id": derive_id("GlossaryTerm", ctx, g["key"]),
            "kind": "GlossaryTerm",
            "status": "reviewed",
            "truth_role": "domain",
            "title": g["key"],
            "context_id": f"context.{ctx}",
            "term": g["term"],
            "definition": g["definition"],
            "evidence_refs": g.get("evidence_refs", []),
        }
        out.append(base(obj, tags=[ctx], created_at=now, updated_at=now, poc_priority="P2"))
    return out


def build_code_evidence(notes, now):
    """code_anchors[] 각 항목을 CodeLocator + EvidenceRef 쌍으로 펼친다."""
    cx = notes["context"]
    ctx, commit, repo = cx["key"], cx["commit"], cx.get("repo", "demoapp")
    out = []
    for a in notes.get("code_anchors", []):
        key = a["key"]
        quote = a.get("quote") or a["symbol"]
        loc = {
            "id": derive_id("CodeLocator", ctx, key),
            "kind": "CodeLocator", "status": "reviewed", "truth_role": "reference",
            "title": quote[:120], "repo": repo, "path": a["path"], "symbol": a["symbol"],
            "line_start": a["line_start"], "line_end": a["line_end"],
            "locator_source": a.get("locator_source", "rg"),
            "commit_sha": commit, "verified_at": now,
        }
        ev = {
            "id": derive_id("EvidenceRef", ctx, key),
            "kind": "EvidenceRef", "status": "reviewed", "truth_role": "reference",
            "title": quote[:120], "evidence_manifest_id": a["manifest"],
            "ref_type": "code_locator", "locator": f"{a['path']}:{a['line_start']}",
            "summary": quote[:500],
        }
        out.append(base(loc, tags=[ctx], created_at=now, updated_at=now, poc_priority="P2"))
        out.append(base(ev, tags=[ctx], created_at=now, updated_at=now, poc_priority="P2"))
    return out


def build_mappings(notes, refs_map, now):
    """mappings[]를 DomainMapping으로. 신규 용어(glossary_keys) + 기존 용어(glossary_term_refs)
    를 합쳐 glossary_term_ids로, code_evref_keys를 locator/evref로 연결한다."""
    ctx = notes["context"]["key"]
    out = []
    for m in notes.get("mappings", []):
        gids = [derive_id("GlossaryTerm", ctx, k) for k in m.get("glossary_keys", [])]
        gids += [refs_map[r] for r in m.get("glossary_term_refs", [])]
        code_ids = [derive_id("CodeLocator", ctx, k) for k in m.get("code_evref_keys", [])]
        evref_ids = [derive_id("EvidenceRef", ctx, k) for k in m.get("code_evref_keys", [])]
        obj = {
            "id": derive_id("DomainMapping", ctx, m["key"]),
            "kind": "DomainMapping", "status": "reviewed", "truth_role": "domain",
            "title": m["canonical_summary"][:120], "context_id": f"context.{ctx}",
            "mapping_key": m["key"], "canonical_summary": m["canonical_summary"],
            "meaning": m["meaning"], "boundary": m["boundary"],
            "caveats": m.get("caveats", ["history_coverage=unsearched"]),
            "glossary_term_ids": sorted(set(gids)),
            "decision_record_ids": [derive_id("DecisionRecord", ctx, k)
                                    for k in m.get("decision_keys", [])],
            "code_locator_ids": code_ids, "evidence_refs": evref_ids,
        }
        out.append(base(obj, tags=[ctx], created_at=now, updated_at=now, poc_priority="P2"))
    return out


def build_manifests(notes, now):
    """sources[] → EvidenceManifest. id는 노트에 직접 기입(컨벤션 manifest.<ctx>.<...>)."""
    ctx = notes["context"]["key"]
    out = []
    for s in notes.get("sources", []):
        obj = {
            "id": s["id"], "kind": "EvidenceManifest", "status": "reviewed",
            "truth_role": "source", "title": s["title"], "source_type": s["source_type"],
            "locator": s["locator"], "captured_at": s.get("captured_at", now),
            "captured_by": s.get("captured_by", "agent"),
            "sensitivity": s.get("sensitivity", "internal"),
            "acl": s.get("acl", ["demo-team"]),
            "redaction_status": s.get("redaction_status", "none"),
        }
        out.append(base(obj, tags=[ctx], created_at=now, updated_at=now, poc_priority="P2"))
    return out


def build_context(notes, now):
    """노트 context에 display_name·boundary_summary가 있으면 신규 DomainContext 생성.
    없으면(key·commit만) 빈 리스트 — 기존 컨텍스트 갱신은 updates[]가 담당."""
    cx = notes["context"]
    if "display_name" not in cx or "boundary_summary" not in cx:
        return []
    ctx = cx["key"]
    obj = {
        "id": f"context.{ctx}", "kind": "DomainContext", "status": "reviewed",
        "truth_role": "domain", "title": cx["display_name"][:80], "context_key": ctx,
        "project_id": cx.get("repo", "demoapp"), "display_name": cx["display_name"],
        "boundary_summary": cx["boundary_summary"], "in_scope": cx.get("in_scope", []),
        "out_of_scope": cx.get("out_of_scope", []),
        "injection_profile": {"default_audience": "coding-agent"},
        "glossary_term_ids": cx.get("glossary_term_ids", []),
    }
    return [base(obj, tags=[ctx], created_at=now, updated_at=now, poc_priority="P2")]


def resolve_refs(notes, store):
    """refs 섹션의 로컬 키를 실제 id로 해소. id 직접 기입 + expect 검증.

    반환: (refs_map {로컬키: 실제id}, report {로컬키: 실제id}, errors[]).
    id가 store에 없거나 expect(kind/status)가 어긋나면 errors에 담는다.
    """
    refs_map, report, errors = {}, {}, []
    refs = notes.get("refs", {})
    for _section, entries in refs.items():
        for local_key, spec in entries.items():
            obj_id = spec.get("id")
            if obj_id is None:
                errors.append(f"refs.{local_key}: id 미기입 (1차는 id 직접 기입만)")
                continue
            if not store.has(obj_id):
                errors.append(f"refs.{local_key}: {obj_id} store에 없음")
                continue
            obj = store.get(obj_id)
            expect = spec.get("expect", {})
            for field, want in expect.items():
                if obj.get(field) != want:
                    errors.append(
                        f"refs.{local_key}: {obj_id} expect {field}={want!r} "
                        f"but got {obj.get(field)!r}")
            refs_map[local_key] = obj_id
            report[local_key] = obj_id
    return refs_map, report, errors


# kind별 allowlist — set(scalar 교체)/union(list 합치기)으로 고칠 수 있는 필드만.
# status·id·kind·created_at·context_id 등 정체성·생명주기 필드는 어느 kind에서도 불가.
_SET_ALLOWLIST = {
    "DomainMapping": {"meaning", "boundary", "canonical_summary", "title"},
    "GlossaryTerm": {"term", "definition", "title"},
    "DomainContext": {"display_name", "boundary_summary", "title"},
}
_UNION_ALLOWLIST = {
    "DomainMapping": {"glossary_term_ids", "code_locator_ids", "decision_record_ids",
                      "evidence_refs", "caveats"},
    "GlossaryTerm": {"evidence_refs"},
    "DomainContext": {"glossary_term_ids", "in_scope", "out_of_scope"},
}
# 의미 주장 필드(kind 무관) — 고치면 근거 동반 강제.
_CLAIM_FIELDS = {"meaning", "boundary", "canonical_summary", "definition",
                 "boundary_summary"}


def apply_updates(notes, store, now):
    """updates[]를 기존 객체에 적용한 '갱신 반영 객체'를 만든다. store는 안 바꾼다.

    가드: expected_updated_at 일치 / set·union은 cur["kind"]별 allowlist 안에서만 /
    claim 필드 수정 시 evidence_refs 변경 또는 evidence_unchanged:true 필수 / status·id
    등 정체성 필드는 allowlist 밖이라 자동 거부. union 대상 id의 실존 검사는 store뿐 아니라
    이번 묶음(new_objs)도 봐야 하므로 build()가 담당한다(여기선 안 함).
    반환: (updated_objs[], diffs[], errors[]). diff는 필드별 before/after 값을 담는다.
    """
    out, diffs, errors = [], [], []
    for up in notes.get("updates", []):
        oid = up["id"]
        if not store.has(oid):
            errors.append(f"updates {oid}: store에 없음")
            continue
        cur = store.get(oid)
        if cur.get("updated_at") != up.get("expected_updated_at"):
            errors.append(f"updates {oid}: expected_updated_at 불일치 "
                          f"(노트 {up.get('expected_updated_at')!r} != 현재 {cur.get('updated_at')!r})")
            continue
        kind = cur.get("kind")
        set_allow = _SET_ALLOWLIST.get(kind, set())
        union_allow = _UNION_ALLOWLIST.get(kind, set())
        new = copy.deepcopy(cur)
        set_fields = up.get("set", {})
        union_fields = up.get("union", {})
        # kind별 allowlist 검사
        for f in set_fields:
            if f not in set_allow:
                errors.append(f"updates {oid}: set 필드 {f!r}는 {kind} allowlist 밖")
        for f in union_fields:
            if f not in union_allow:
                errors.append(f"updates {oid}: union 필드 {f!r}는 {kind} allowlist 밖")
        # claim 필드 수정 시 근거 동반 강제
        touched_claims = (set(set_fields) | set(union_fields)) & _CLAIM_FIELDS
        evidence_touched = ("evidence_refs" in set_fields or "evidence_refs" in union_fields
                            or up.get("evidence_unchanged") is True)
        if touched_claims and not evidence_touched:
            errors.append(f"updates {oid}: claim 필드 {sorted(touched_claims)} 수정엔 "
                          f"evidence_refs 변경 또는 evidence_unchanged:true 필요")
        # 실제 적용 + 필드별 before/after diff (errors 있어도 diff 위해 적용은 함; build()가 errors로 막음)
        changes = {}
        for f, v in set_fields.items():
            changes[f] = {"before": cur.get(f), "after": v}
            new[f] = v
        for f, vs in union_fields.items():
            merged_list = sorted(set(new.get(f, []) + vs))
            changes[f] = {"before": cur.get(f, []), "after": merged_list}
            new[f] = merged_list
        new["updated_at"] = now
        out.append(new)
        diffs.append({"id": oid, "changes": changes,
                      "before_updated_at": cur.get("updated_at")})
    return out, diffs, errors


_VALID_SECTIONS = {"context", "sources", "glossary", "code_anchors", "mappings",
                   "refs", "updates", "extra_objects"}  # decisions는 2차(Task 4 노트 참고)
_LIST_SECTIONS = {"sources", "glossary", "code_anchors", "mappings", "updates", "extra_objects"}
_DICT_SECTIONS = {"context", "refs"}
_UPDATE_KEYS = {"id", "expected_updated_at", "set", "union", "evidence_unchanged"}
# 섹션 항목별 필수 필드(중첩 검증). 변환 함수가 default 채우는 필드는 여기 안 넣는다.
_ITEM_REQUIRED = {
    # glossary는 항상 reviewed로 만들어지므로 evidence_refs 필수(2층 schema가 막는 걸 1층에서 친절히).
    "glossary": ("key", "term", "definition", "evidence_refs"),
    "code_anchors": ("key", "path", "symbol", "line_start", "line_end", "manifest"),
    "mappings": ("key", "canonical_summary", "meaning", "boundary"),
    "sources": ("id", "source_type", "title", "locator"),
}


def validate_notes(notes):
    """1층: 노트 형식 검증. 모르는 섹션·필수 누락·잘못된 타입·미지원 연산은 경고가 아니라 실패."""
    errors = []
    for section, value in notes.items():
        if section not in _VALID_SECTIONS:
            errors.append(f"노트: 알 수 없는 섹션 {section!r} (허용: {sorted(_VALID_SECTIONS)})")
            continue
        if section in _LIST_SECTIONS and not isinstance(value, list):
            errors.append(f"노트: 섹션 {section!r}는 list여야 함 (현재 {type(value).__name__})")
        if section in _DICT_SECTIONS and not isinstance(value, dict):
            errors.append(f"노트: 섹션 {section!r}는 object여야 함 (현재 {type(value).__name__})")
    cx = notes.get("context")
    if not isinstance(cx, dict) or "key" not in cx or "commit" not in cx:
        errors.append("노트: context.key·context.commit 필수")
    # 섹션 항목 중첩 필수 필드
    for section, required in _ITEM_REQUIRED.items():
        value = notes.get(section)
        if not isinstance(value, list):
            continue
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                errors.append(f"노트: {section}[{i}]는 object여야 함")
                continue
            for field in required:
                if field not in item:
                    errors.append(f"노트: {section}[{i}] 필수 필드 {field!r} 누락")
    # glossary는 reviewed로 생성되므로 evidence_refs가 비어 있어도 안 됨(2층 schema:186을 1층에서 친절히).
    # _ITEM_REQUIRED는 키 존재만 보므로 빈 리스트는 여기서 별도로 잡는다.
    glossary = notes.get("glossary")
    for i, g in enumerate(glossary if isinstance(glossary, list) else []):
        if isinstance(g, dict) and "evidence_refs" in g and not g["evidence_refs"]:
            errors.append(f"노트: glossary[{i}] evidence_refs가 비어 있음 (reviewed 용어는 근거 필수)")
    # updates: 연산 키 화이트리스트(remove·조건·계산 차단) + 타입
    updates = notes.get("updates")
    for up in updates if isinstance(updates, list) else []:
        if not isinstance(up, dict):
            errors.append("노트: updates 항목은 object여야 함")
            continue
        for key in up:
            if key not in _UPDATE_KEYS:
                errors.append(f"updates {up.get('id')}: 미지원 연산 키 {key!r} "
                              f"(허용: {sorted(_UPDATE_KEYS)} — remove·조건·계산 없음)")
        if "expected_updated_at" not in up:
            errors.append(f"updates {up.get('id')}: expected_updated_at 필수")
        if not (up.get("set") or up.get("union")):
            errors.append(f"updates {up.get('id')}: set 또는 union 중 하나 필요")
        for op in ("set", "union"):
            if op in up and not isinstance(up[op], dict):
                errors.append(f"updates {up.get('id')}: {op}은 object여야 함")
    return errors


def build(notes, store, now):
    """노트 → 완성 객체 묶음 + diff + preconditions. 저장은 안 한다.

    반환 dict: objects[], diff[], resolved_refs{}, preconditions{id: expected_updated_at},
               errors[]. errors가 비어야 안전하게 ingest 가능.
    """
    errors = list(validate_notes(notes))
    if errors:
        return {"objects": [], "diff": [], "resolved_refs": {},
                "preconditions": {}, "errors": errors, "warnings": []}

    refs_map, resolved, ref_errors = resolve_refs(notes, store)
    errors += ref_errors

    new_objs = []
    new_objs += build_manifests(notes, now)        # Task 4 Step 6
    new_objs += build_code_evidence(notes, now)    # Task 2
    new_objs += build_glossary_terms(notes, now)   # Task 1
    new_objs += build_mappings(notes, refs_map, now)  # Task 4
    new_objs += build_context(notes, now)          # Task 4 Step 6 (신규 context)
    new_objs += list(notes.get("extra_objects", []))  # 탈출구: 완성 객체 직접

    upd_objs, diffs, upd_errors = apply_updates(notes, store, now)
    errors += upd_errors
    preconditions = {up["id"]: up["expected_updated_at"] for up in notes.get("updates", [])}

    all_objs = new_objs + upd_objs

    # 2층: 객체 스키마 + dangling + merged lint
    for o in all_objs:
        errors += validate_object(o)
    merged = {o["id"]: o for o in store.all()}
    for o in all_objs:
        merged[o["id"]] = o

    # EvidenceRef → EvidenceManifest dangling (lint.py 사각지대 — lint는 EvidenceRef가
    # 가리키는 manifest 실존을 안 본다. _source_type_for_evidence_ref는 None만 반환).
    for o in all_objs:
        if o.get("kind") == "EvidenceRef":
            mid = o.get("evidence_manifest_id")
            if mid and mid not in merged:
                errors.append(f"{o['id']}: dangling evidence_manifest_id {mid}")

    # updates union 대상 id 실존 (lint.py 사각지대 — lint는 DomainMapping 링크만 보므로
    # DomainContext.glossary_term_ids 등은 직접 검사. id 리스트 필드만, 자유텍스트 list 제외).
    for up in notes.get("updates", []):
        for f, vs in (up.get("union") or {}).items():
            if f.endswith("_ids") or f == "evidence_refs":
                for v in vs:
                    if v not in merged:
                        errors.append(f"updates {up.get('id')}: union {f} 대상 {v} 없음 "
                                      f"(store·이번 묶음 어디에도)")

    merged_store = BrainStore(merged)
    errors += lint_store(merged_store)

    # C8: 이번 묶음 신규 잎 중 인바운드 0(아무도 안 가리킴)을 비차단 경고로 담는다 — 차단
    # 아님(candidate 일시 고립은 정상). 역인덱스·점검 잎 kind는 graph.py를 C1과 공유.
    referenced = referenced_ids(merged_store)
    warnings = sorted(
        f"{o['id']}: isolated {o['kind']} (no inbound reference; non-blocking)"
        for o in all_objs
        if o.get("kind") in ISOLATION_LEAF_KINDS and o["id"] not in referenced
    )

    return {"objects": all_objs, "diff": diffs, "resolved_refs": resolved,
            "preconditions": preconditions, "errors": errors, "warnings": warnings}
