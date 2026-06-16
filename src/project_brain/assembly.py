"""범용 조립 코어 — 구조화 노트 → brain 객체 묶음.

판정은 에이전트(노트 작성), 변환은 기계적(이 모듈). supersede/강등/충돌 해소/이력
판정은 하지 않는다. objbase.base 위에 kind별 변환 + refs + updates + 2층 검증을 얹는다.
저장은 절대 안 한다 — build()는 객체 묶음 + diff만 반환하고 ingest가 저장한다.
"""
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
