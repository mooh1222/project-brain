#!/usr/bin/env python3
"""적재 조립기: verify 출력 + domain_spec → project-brain build 노트 dict.

세 층: (1) 입력 정규화(verify 형태 흡수·폴백·CORRECTIONS·HOOK),
(2) 공통 조립 루프(atom→code_anchors/glossary/mappings),
(3) decisions[] 패스스루(엔진 build_decisions가 조립 — 여기선 해석 안 함).
조립 로직은 적재마다 재작성하지 않는다. 적재별 데이터는 domain_spec.py가 담는다.
stdlib만 사용(json). 금지선: 그룹 분해·결정 내용·EXCLUDE·history_coverage는 추론 금지(spec이 데이터로 줌)."""
import json
import sys


def normalize(verify_data, spec):
    """verify 출력 → 정렬·보정된 atom 리스트."""
    # CASE: verify 결과가 list(main-map) 또는 {"groups": [...]}(ball-select) — 둘 다 흡수 (근거: ball-select·main-map 2026-06). 새 래핑은 여기 추가.
    groups = verify_data["groups"] if isinstance(verify_data, dict) else verify_data
    by_group = {}
    for g in groups:
        # CASE: verify가 corrected_atoms를 비워 반환하면 extract.atoms로 폴백 (근거: main-map map-stage-episode 2026-06-25). 새 폴백은 여기 추가.
        atoms = (g.get("verify") or {}).get("corrected_atoms") or (g.get("extract") or {}).get("atoms") or []
        by_group[g["group"]] = atoms
    ordered = []
    for name in spec["GROUP_ORDER"]:
        ordered += by_group.get(name, [])
    # CASE: per-atom 선언적 보정(verify 의미 보정·용어 제외) — 사람이 spec에 데이터로 (근거: main-map NEW_MEANING 2건 2026-06-25).
    corrections = spec.get("CORRECTIONS") or {}
    for a in ordered:
        c = corrections.get(a["mapping_key"])
        if not c:
            continue
        if "meaning" in c:
            a["meaning"] = c["meaning"]
        if "drop_terms" in c:
            drop = set(c["drop_terms"])
            a["glossary_terms"] = [t for t in a.get("glossary_terms", []) if t["term_key"] not in drop]
    # 진짜 novel 변칙만 HOOK 탈출구(선언적으로 표현 불가일 때). 사람이 그 적재 보고 작성.
    hook = spec.get("HOOK")
    if hook:
        ordered = hook(ordered)
        print("WARNING: domain_spec.HOOK 사용 — references/ingest-case-log.md에 변칙을 기록하세요", file=sys.stderr)
    return ordered


def build_notes(atoms, spec):
    """정규화된 atoms + spec → notes dict(context/sources/code_anchors/glossary/mappings/decisions)."""
    ctx = spec["CTX"]
    code_anchors, glossary, term_first_anchor, mappings = [], {}, {}, []
    for a in atoms:
        mk = a["mapping_key"]
        akeys = []
        for i, ca in enumerate(a.get("code_anchors", [])):
            ak = f"{mk}--{i}"  # 키 규약(2 표본 입증)
            akeys.append(ak)
            code_anchors.append({"key": ak, "path": ca["path"], "symbol": ca["symbol"],
                                 "manifest": spec["MANIFESTS"]["code"], "quote": ca.get("quote", "")})
        tkeys = []
        for t in a.get("glossary_terms", []):
            tk = t["term_key"]
            if tk in (spec.get("EXCLUDE_TERMS") or set()):
                continue
            tkeys.append(tk)
            if tk not in glossary:
                glossary[tk] = {"term": t["term"], "definition": t["definition"]}
                term_first_anchor[tk] = akeys[0] if akeys else None
        mappings.append({"key": mk, "canonical_summary": a["canonical_summary"],
                         "meaning": a["meaning"], "boundary": a["boundary"],
                         "caveats": [f"history_coverage={spec['HISTORY_COVERAGE']}"],
                         "glossary_keys": tkeys, "code_evref_keys": akeys})
    glossary_section, gids = [], []
    for tk, info in glossary.items():
        ak = term_first_anchor[tk]
        ev = [f"evref.{ctx}.{ak}"] if ak else []
        glossary_section.append({"key": tk, "term": info["term"],
                                 "definition": info["definition"], "evidence_refs": ev})
        gids.append(f"g.{ctx}.{tk}")
    context = {"key": ctx, "commit": spec["COMMIT"], "repo": spec.get("REPO", "{{REPO}}"),
               "display_name": spec["DISPLAY_NAME"], "boundary_summary": spec["BOUNDARY_SUMMARY"],
               "in_scope": spec["IN_SCOPE"], "out_of_scope": spec["OUT_OF_SCOPE"],
               "glossary_term_ids": gids}
    if spec.get("NOW"):
        context["now"] = spec["NOW"]  # CLI(project-brain build)가 context.now를 읽어 build()의 now 인자로 넘김 → churn 0
    sources = [{"id": mid, "source_type": _SOURCE_TYPE.get(kind, "code_search"),
                "title": f"{spec['DISPLAY_NAME']} {kind} 소스", "locator": f"{spec.get('REPO','{{REPO}}')}@{spec['COMMIT']}"}
               for kind, mid in spec["MANIFESTS"].items()]
    return {"context": context, "sources": sources, "code_anchors": code_anchors,
            "glossary": glossary_section, "mappings": mappings,
            "decisions": spec.get("DECISIONS", [])}  # 패스스루 — 엔진 build_decisions가 조립


_SOURCE_TYPE = {"code": "code_search", "commit": "commit", "jira": "jira", "pr": "pr",
                "spec": "spec", "wiki": "wiki"}


def assemble_notes(verify_data, spec):
    return build_notes(normalize(verify_data, spec), spec)


def _load_spec(path):
    ns = {}
    with open(path, encoding="utf-8") as f:
        exec(compile(f.read(), path, "exec"), ns)
    return {k: ns[k] for k in ns if k.isupper() or k == "HOOK"}


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="verify 출력 + domain_spec → notes.json")
    ap.add_argument("verify_json")
    ap.add_argument("domain_spec_py")
    ap.add_argument("-o", "--out", default="notes.json")
    args = ap.parse_args(argv)
    with open(args.verify_json, encoding="utf-8") as f:
        verify_data = json.load(f)
    spec = _load_spec(args.domain_spec_py)
    notes = assemble_notes(verify_data, spec)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)
    print(f"notes 조립: mappings={len(notes['mappings'])} anchors={len(notes['code_anchors'])} "
          f"terms={len(notes['glossary'])} decisions={len(notes['decisions'])} → {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
