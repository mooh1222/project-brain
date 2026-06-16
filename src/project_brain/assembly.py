"""범용 조립 코어 — 구조화 노트 → brain 객체 묶음.

판정은 에이전트(노트 작성), 변환은 기계적(이 모듈). supersede/강등/충돌 해소/이력
판정은 하지 않는다. objbase.base 위에 kind별 변환 + refs + updates + 2층 검증을 얹는다.
저장은 절대 안 한다 — build()는 객체 묶음 + diff만 반환하고 ingest가 저장한다.
"""
import copy

from project_brain.objbase import base

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
    ctx, commit, repo = cx["key"], cx["commit"], cx.get("repo", "bb2_client")
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
            "acl": s.get("acl", ["bb2-team"]),
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
        "project_id": cx.get("repo", "bb2_client"), "display_name": cx["display_name"],
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
