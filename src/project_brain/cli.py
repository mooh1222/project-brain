import argparse
import json
import sys
from pathlib import Path

from project_brain.config import ConfigError, resolve_brain_root, resolve_scenarios_path
from project_brain.embedder import get_embedder
from project_brain.eval_harness import (
    evaluate,
    load_recall_fn,
    load_scenarios,
)
from project_brain.ingest import IngestError, ingest
from project_brain.lint import lint_store, _has_only_legacy_evidence
from project_brain.promote import (
    promote,
    backfill_evidence,
    select_vouched_candidates,
)
from project_brain.router import QueryRouter
from project_brain.schema import validate_object
from project_brain.search_index import rebuild as index_rebuild
from project_brain.store import BrainStore


def _run_query(argv) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    parser.add_argument("--current-head")
    # 후속 c(2026-06-11): --db를 주면 라우터 recall(top-K·후보 채널)이 켜진다.
    # 기본은 미지정=기존 폴백 동작 — cli search와 달리 자동 기본 경로를 쓰지 않는
    # 이유는 색인이 있는 머신에서 기존 query 사용·테스트가 전부 실모델 로드를
    # 타게 되는 동작 변경이라서(보존 우선). 표준 색인은 <brain_root>/.brain-local/index.db.
    parser.add_argument("--db", help="색인 DB 경로 — 주면 recall이 켜진다 (예: brain/.brain-local/index.db)")
    parser.add_argument("--stub-embedder", action="store_true",
                        help="실모델 대신 stub 임베더 사용(테스트·CI 결정론, §5)")
    parser.add_argument("query", nargs="?")
    args = parser.parse_args(argv)

    brain_root = resolve_brain_root(args.brain_root)
    store = BrainStore.load(brain_root)
    if not args.query:
        parser.error("query is required")
    # embedder None이면 recall 층이 색인과 같은 팩토리(get_embedder)로 만든다.
    embedder = get_embedder(stub=True) if args.stub_embedder else None
    router = QueryRouter(
        store, current_head=args.current_head,
        db_path=Path(args.db) if args.db else None,
        embedder=embedder, brain_root=brain_root,
    )
    answer = router.answer(args.query)
    print(json.dumps(answer, ensure_ascii=False, indent=2))
    return 0


def _run_ingest(argv) -> int:
    parser = argparse.ArgumentParser(prog="cli ingest")
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    parser.add_argument("--objects-file", required=True)
    args = parser.parse_args(argv)

    brain_root = resolve_brain_root(args.brain_root)
    objects = json.loads(Path(args.objects_file).read_text(encoding="utf-8"))
    try:
        ingest(brain_root, objects)
    except IngestError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, "ingested": len(objects)}, ensure_ascii=False, indent=2))
    return 0


def _run_promote(argv) -> int:
    parser = argparse.ArgumentParser(prog="cli promote")
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    parser.add_argument("--ids", required=True, nargs="+")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument("--scope", default="single_object",
                        choices=["single_object", "mapping_bundle"])
    parser.add_argument("--bundle-key")
    parser.add_argument("--conflict-resolution",
                        help="수동 conflict 용어 승격 시 정설 선택 근거(검수 기록에 기록, §4.4)")
    args = parser.parse_args(argv)

    brain_root = resolve_brain_root(args.brain_root)
    store = BrainStore.load(brain_root)
    missing = [i for i in args.ids if not store.has(i)]
    if missing:
        print(json.dumps({"ok": False, "error": f"unknown ids: {missing}"},
                         ensure_ascii=False, indent=2))
        return 1
    # 멱등 가드(§4.4): 이미 reviewed인 id를 다시 승격하면 review.<id> 기록을 덮어쓰는 사고 → 거부.
    already_reviewed = [i for i in args.ids if store.get(i).get("status") == "reviewed"]
    if already_reviewed:
        print(json.dumps({"ok": False, "error": f"already reviewed (idempotency guard): {already_reviewed}"},
                         ensure_ascii=False, indent=2))
        return 1
    review_extra_by_id = None
    if args.scope == "single_object":
        # backfill 공유(§4.4): 근거 빈 용어가 짝 매핑 근거를 물려받아 B 게이트(§6.4)를 통과.
        objects = [backfill_evidence(store.get(i), store) for i in args.ids]
        if args.conflict_resolution:
            review_extra_by_id = {
                i: {"conflict_resolution": args.conflict_resolution}
                for i in args.ids
                if (store.get(i).get("candidate") or {}).get("candidate_state") == "conflict"
            }
    else:
        objects = [store.get(i) for i in args.ids]
    # promote.py: (승격 객체, 검토 기록) 둘 다 반환 — 둘 다 저장해야 검토 기록 참조가 살아남는다(§5.2).
    # bundle_key 누락·잘못된 scope 등은 promote가 ValueError로 알리므로 잡아 rc=1로 돌린다(리뷰 minor 반영).
    try:
        promoted, records = promote(
            objects, args.ids, args.scope,
            bundle_key=args.bundle_key, reviewer=args.reviewer, reviewed_at=args.reviewed_at,
            review_extra_by_id=review_extra_by_id,
        )
    except (ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    # ★원자성(2026-06-08 사고 반영): 디스크에 쓰기 전 schema 검증 + 적용 후 store lint를 둘 다
    #   save 전에 한다. schema는 필드/enum만 보고, legacy-only·dangling 같은 store 관계 위반은
    #   lint가 잡으므로 lint를 save 뒤에 두면 부분 쓰기가 남는다. ingest.py처럼 merged store를
    #   메모리에서 lint해 통과해야만 save한다.
    to_write = promoted + records
    schema_errors = []
    for obj in to_write:
        schema_errors.extend(validate_object(obj))
    if schema_errors:
        print(json.dumps({"ok": False, "error": "; ".join(schema_errors)}, ensure_ascii=False, indent=2))
        return 1
    merged = {o["id"]: o for o in store.all()}
    for obj in to_write:
        merged[obj["id"]] = obj
    problems = lint_store(BrainStore(merged))
    if problems:
        print(json.dumps({"ok": False, "lint": problems}, ensure_ascii=False, indent=2))
        return 1
    for obj in to_write:
        BrainStore.save_object(brain_root, obj)
    print(json.dumps(
        {"ok": True, "promoted": [o["id"] for o in promoted], "reviews": [r["id"] for r in records]},
        ensure_ascii=False, indent=2))
    return 0


def _run_promote_auto(argv) -> int:
    parser = argparse.ArgumentParser(prog="cli promote-auto")
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    parser.add_argument("--ids", required=True, nargs="+",
                        help="배치 커버리지 검증 워크플로우가 산출한 pass 용어 id 목록(§4.2b)")
    parser.add_argument("--reviewed-at", required=True)
    args = parser.parse_args(argv)

    brain_root = resolve_brain_root(args.brain_root)
    store = BrainStore.load(brain_root)
    selection = select_vouched_candidates(store)  # {term_id: [보증 매핑 id]}

    # --ids를 1단계 기준으로 다시 가드 → 건너뛴 사유별 분류(조용한 누락 금지, §4.3).
    skipped = {"unknown_id": [], "not_glossary_term": [], "already_reviewed": [],
               "not_candidate": [], "conflict": [], "unreferenced": [],
               "no_evidence": [], "legacy_only_evidence": []}
    eligible = []
    seen = set()
    for tid in args.ids:
        if tid in seen:
            continue  # 입력 중복 dedup(§4.3)
        seen.add(tid)
        if not store.has(tid):
            skipped["unknown_id"].append(tid); continue
        obj = store.get(tid)
        if obj.get("kind") != "GlossaryTerm":
            skipped["not_glossary_term"].append(tid); continue
        if obj.get("status") == "reviewed":
            skipped["already_reviewed"].append(tid); continue
        if obj.get("status") != "candidate":
            skipped["not_candidate"].append(tid); continue
        if (obj.get("candidate") or {}).get("candidate_state") == "conflict":
            skipped["conflict"].append(tid); continue
        if tid not in selection:
            skipped["unreferenced"].append(tid); continue
        # 자동 승격은 non-legacy 근거를 확보할 수 있는 것만(2026-06-08 사고 반영): backfill 후에도
        # 근거가 비면 §6.4 schema 위반, wiki/context뿐이면 reviewed legacy-only(lint 6) 위반이라
        # 사후 lint에서 전체 배치를 막는다. 부적격을 여기서 걸러 정당분만 승격한다.
        bf = backfill_evidence(obj, store)
        if not bf.get("evidence_refs"):
            skipped["no_evidence"].append(tid); continue
        if _has_only_legacy_evidence(store, bf):
            skipped["legacy_only_evidence"].append(tid); continue
        eligible.append(tid)

    promoted, records = [], []
    if eligible:
        objects = [backfill_evidence(store.get(tid), store) for tid in eligible]
        review_extra = {tid: {"vouched_by_mapping_ids": selection[tid]} for tid in eligible}
        try:
            promoted, records = promote(
                objects, eligible, "single_object",
                reviewer="auto:mapping-vouched", reviewed_at=args.reviewed_at,
                review_extra_by_id=review_extra,
            )
        except (ValueError, KeyError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
        # 원자성(2026-06-08 사고 반영): 쓰기 전 schema + merged store lint를 둘 다 한다. lint를
        # save 뒤에 두면 legacy-only 같은 위반이 부분 쓰기를 남긴다. 통과해야만 save한다.
        to_write = promoted + records
        schema_errors = []
        for obj in to_write:
            schema_errors.extend(validate_object(obj))
        if schema_errors:
            print(json.dumps({"ok": False, "error": "; ".join(schema_errors)}, ensure_ascii=False, indent=2))
            return 1
        merged = {o["id"]: o for o in store.all()}
        for obj in to_write:
            merged[obj["id"]] = obj
        problems = lint_store(BrainStore(merged))
        if problems:
            print(json.dumps({"ok": False, "lint": problems}, ensure_ascii=False, indent=2))
            return 1
        for obj in to_write:
            BrainStore.save_object(brain_root, obj)

    # 승격 후 남은 보증 용어(보류된 커버리지 불통과분 등) 비차단 드리프트 신호(§4.6).
    from project_brain.lint import unpromoted_vouched_terms
    drift_remaining = unpromoted_vouched_terms(BrainStore.load(brain_root))
    skipped = {k: v for k, v in skipped.items() if v}  # 빈 사유 제거
    print(json.dumps(
        {"ok": True, "promoted": [o["id"] for o in promoted],
         "reviews": [r["id"] for r in records], "skipped": skipped,
         "drift_remaining": drift_remaining},
        ensure_ascii=False, indent=2))
    return 0


def _run_index(argv) -> int:
    """FTS + 벡터 색인 빌드 (스펙 §3.3·§4·§6, 슬라이스 2·3). 현재 하위명령은 rebuild만.

    `index rebuild [--brain-root <path>] [--db <path>] [--stub-embedder]` — brain/ 전
    객체에서 전체 재구축(DB 삭제 후 재생성). 미지정 경로는 config에서 해석.

    임베딩: 기본은 실모델(bge-m3) — 수백 개 배치 임베딩이라 시간이 걸리는 게 정상(§11).
    --stub-embedder 플래그 또는 PROJECT_BRAIN_EMBEDDER=stub 환경변수면 stub(테스트·CI용).
    """
    parser = argparse.ArgumentParser(prog="cli index")
    parser.add_argument("subcommand", choices=["rebuild"])
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    parser.add_argument("--db", help="색인 DB 경로 (기본: config)")
    parser.add_argument("--stub-embedder", action="store_true",
                        help="실모델 대신 stub 임베더 사용(테스트·CI 결정론, §5)")
    args = parser.parse_args(argv)

    # --stub-embedder 플래그면 강제 stub, 아니면 환경 플래그로 판정(get_embedder 기본).
    embedder = get_embedder(stub=True) if args.stub_embedder else get_embedder()
    stats = index_rebuild(args.brain_root, args.db, embedder=embedder)
    # raw_chunks를 함께 내보낸다 — 데이터 레포 쪽 실측 가드가 객체/raw 행 수를
    # 이 출력만으로 검증한다(엔진 import 없는 CLI 가드).
    print(json.dumps(
        {"ok": True, "indexed": stats["indexed"], "raw_chunks": stats["raw_chunks"],
         "tokenizer": stats["tokenizer"],
         "embed_model": stats["embed_model"], "db": stats["db"]},
        ensure_ascii=False, indent=2))
    return 0


def _run_search(argv) -> int:
    """의미 회상 명령 (스펙 §7) — 어시스턴트가 직접 쓰는 회상 진입점.

    `search "<query>" [--db <path>] [--brain-root <path>] [--stub-embedder]` —
    recall + 다신호 게이트(search.eval_recall)를 태운 결과를 검수 상태(reviewed/
    candidate)·linked(코드 위치)와 함께 JSON으로 낸다. needs_clarification은 게이트
    통과 reviewed 0건일 때 True("no evidence → 없다" §7). 색인 DB가 없으면 명확한
    에러로 끝낸다(`cli index rebuild` 먼저).
    """
    parser = argparse.ArgumentParser(prog="cli search")
    parser.add_argument("query")
    parser.add_argument("--db", help="색인 DB 경로 (기본: config)")
    parser.add_argument("--brain-root", help="brain root (그래프 1-hop store, 기본: config)")
    parser.add_argument("--stub-embedder", action="store_true",
                        help="실모델 대신 stub 임베더 사용(테스트·CI 결정론, §5)")
    args = parser.parse_args(argv)

    from project_brain.search import eval_recall

    embedder = get_embedder(stub=True) if args.stub_embedder else get_embedder()
    try:
        resp = eval_recall(
            args.query, db_path=args.db, embedder=embedder, brain_root=args.brain_root
        )
    except FileNotFoundError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    # raw 채널(§2.2): 청크 발췌에 신뢰 라벨을 항목마다 박는다 — 어시스턴트가 결과만
    # 보고도 "검수 안 된 원문 발췌"임을 놓치지 않게(candidate 채널 라벨 규약과 동형).
    raw_excerpts = [{**h, "trust_label": "원문 발췌(미검수)"}
                    for h in resp.get("raw_excerpts", [])]
    print(json.dumps(
        {"ok": True, "query": args.query,
         "results": resp["results"], "candidates": resp["candidates"],
         "raw_excerpts": raw_excerpts,
         "needs_clarification": resp["needs_clarification"]},
        ensure_ascii=False, indent=2))
    return 0


def _run_eval(argv) -> int:
    """검색층 평가 하네스 실행 (스펙 §8). 검색층 미구현이면 빈 응답 stub로
    빨간 베이스라인을 측정한다(슬라이스 1의 의도된 상태) — implemented=false 표기.

    --check-ids: 시나리오의 기대 object_id가 코퍼스에 실존하는지만 검사하고 끝낸다
    (모델·색인 불필요) — 데이터 레포 쪽 골든셋 가드가 쓰는 가벼운 무결성 검사."""
    parser = argparse.ArgumentParser(prog="cli eval")
    parser.add_argument("--scenarios", help="시나리오 파일 경로 (기본: config)")
    parser.add_argument("--check-ids", action="store_true",
                        help="기대 object_id의 코퍼스 실존만 검사(모델·색인 불필요)")
    parser.add_argument("--brain-root", help="--check-ids가 검사할 코퍼스 루트 (기본: config)")
    args = parser.parse_args(argv)

    path = resolve_scenarios_path(args.scenarios)
    scenarios = load_scenarios(path)
    if args.check_ids:
        from project_brain.eval_harness import expected_object_ids

        store = BrainStore.load(resolve_brain_root(args.brain_root))
        expected = expected_object_ids(scenarios)
        missing = sorted(oid for oid in expected if not store.has(oid))
        print(json.dumps(
            {"ok": not missing, "checked": len(expected), "missing": missing},
            ensure_ascii=False, indent=2))
        return 0 if not missing else 1
    recall_fn, implemented = load_recall_fn()
    report = evaluate(recall_fn, scenarios)
    report["implemented"] = implemented
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def _run_install(argv) -> int:
    """프로젝트에 config + 스킬 2종을 멱등 설치 (installer.py — manifest 추적).

    설치 직후 어시스턴트가 코퍼스를 보고 스킬 description 트리거 어휘를 맞춤
    제안하는 단계는 사람·에이전트 몫이다 — CLI는 범용 템플릿 주입까지만."""
    parser = argparse.ArgumentParser(prog="cli install")
    parser.add_argument("--target", help="프로젝트 루트 (기본: cwd)")
    parser.add_argument("--project", help="프로젝트 이름 (기본: target 디렉토리명)")
    parser.add_argument("--brain-root", default="brain",
                        help="코퍼스 상대 경로 (기본: brain)")
    args = parser.parse_args(argv)

    from project_brain.installer import install

    target = Path(args.target) if args.target else Path.cwd()
    project = args.project or target.resolve().name
    report = install(target, project=project, brain_root=args.brain_root)
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))
    return 0


def _run_doctor(argv) -> int:
    """의존성·백엔드·프로젝트 상태 진단 (doctor.py). required 실패 시 rc=1."""
    parser = argparse.ArgumentParser(prog="cli doctor")
    parser.add_argument("--download", action="store_true",
                        help="임베딩 실모델을 한 번 로드해 캐시를 채운다(시간 소요)")
    args = parser.parse_args(argv)

    from project_brain.doctor import diagnose

    report = diagnose(download=args.download)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def _run_bootstrap(argv) -> int:
    """install → (코퍼스 있으면) index rebuild → doctor 멱등 래퍼."""
    parser = argparse.ArgumentParser(prog="cli bootstrap")
    parser.add_argument("--project", help="프로젝트 이름 (기본: cwd 디렉토리명)")
    parser.add_argument("--brain-root", default="brain")
    parser.add_argument("--stub-embedder", action="store_true",
                        help="색인 단계에서 실모델 대신 stub 사용")
    args = parser.parse_args(argv)

    from project_brain.config import load_config
    from project_brain.installer import install

    install_report = install(
        Path.cwd(), project=args.project or Path.cwd().resolve().name,
        brain_root=args.brain_root,
    )
    cfg = load_config()
    rebuilt = None
    if cfg is not None and (cfg["brain_root"] / "objects").exists():
        embedder = get_embedder(stub=True) if args.stub_embedder else get_embedder()
        rebuilt = index_rebuild(cfg["brain_root"], cfg["db"], embedder=embedder)
        rebuilt = {"indexed": rebuilt["indexed"], "raw_chunks": rebuilt["raw_chunks"]}

    from project_brain.doctor import diagnose

    doctor_report = diagnose()
    print(json.dumps(
        {"ok": doctor_report["ok"], "install": install_report, "index": rebuilt,
         "doctor": doctor_report["checks"]},
        ensure_ascii=False, indent=2))
    return 0 if doctor_report["ok"] else 1


def main() -> int:
    argv = sys.argv[1:]
    try:
        # 첫 인자가 서브커맨드면 해당 경로, 아니면 기존 query 경로 호환 유지(AC6)
        if argv and argv[0] == "ingest":
            return _run_ingest(argv[1:])
        if argv and argv[0] == "index":
            return _run_index(argv[1:])
        if argv and argv[0] == "search":
            return _run_search(argv[1:])
        if argv and argv[0] == "eval":
            return _run_eval(argv[1:])
        if argv and argv[0] == "promote-auto":
            return _run_promote_auto(argv[1:])
        if argv and argv[0] == "promote":
            return _run_promote(argv[1:])
        if argv and argv[0] == "install":
            return _run_install(argv[1:])
        if argv and argv[0] == "doctor":
            return _run_doctor(argv[1:])
        if argv and argv[0] == "bootstrap":
            return _run_bootstrap(argv[1:])
        return _run_query(argv)
    except ConfigError as exc:
        # 경로 미지정 + config 부재 — traceback 대신 해결책이 담긴 메시지로 끝낸다.
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
