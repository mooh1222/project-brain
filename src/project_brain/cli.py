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
from project_brain.objbase import now_kst
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
    parser.add_argument("--preconditions-file",
                        help="build 리포트 JSON (preconditions 키 — 저장 직전 낙관적 잠금 재검사)")
    args = parser.parse_args(argv)

    brain_root = resolve_brain_root(args.brain_root)
    objects = json.loads(Path(args.objects_file).read_text(encoding="utf-8"))
    preconditions = None
    if args.preconditions_file:
        report = json.loads(Path(args.preconditions_file).read_text(encoding="utf-8"))
        preconditions = report.get("preconditions", report)
    try:
        ingest(brain_root, objects, preconditions=preconditions)
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
    parser.add_argument("--reviewed-at", help="생략 시 현재 KST를 엔진이 자동으로 박는다")
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
            bundle_key=args.bundle_key, reviewer=args.reviewer, reviewed_at=args.reviewed_at or now_kst(),
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
    parser.add_argument("--reviewed-at", help="생략 시 현재 KST를 엔진이 자동으로 박는다")
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
                reviewer="auto:mapping-vouched", reviewed_at=args.reviewed_at or now_kst(),
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


def _run_session(argv) -> int:
    """세션 transcript 스캔·처리 마킹 (스펙 §7) — (다) 과거 세션 추출의 CLI 보조.

    `session list [--unprocessed] [--project <substr>] [--transcript-root <p>] [--brain-root <p>]`
    `session mark-processed <uuid> [--note <text>] [--brain-root <p>]`

    추출 판단은 스킬(Claude) 몫 — 여기는 결정론 스캔·마킹만(경계 불변).
    """
    parser = argparse.ArgumentParser(prog="cli session")
    sub = parser.add_subparsers(dest="action", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--unprocessed", action="store_true",
                        help="처리 마킹 없는 세션만")
    p_list.add_argument("--project", help="cwd 부분 문자열 필터 (예: demoapp)")
    p_list.add_argument("--transcript-root", help="기본: ~/.claude/projects")
    p_list.add_argument("--brain-root", help="brain root (마킹 대조, 기본: config)")

    p_mark = sub.add_parser("mark-processed")
    p_mark.add_argument("uuid")
    p_mark.add_argument("--note", help="비고 (예: '미합의 2건' — 스펙 §4)")
    p_mark.add_argument("--brain-root", help="brain root (기본: config)")

    args = parser.parse_args(argv)
    from project_brain.session import mark_processed, scan_sessions

    brain_root = resolve_brain_root(args.brain_root)
    if args.action == "list":
        sessions = scan_sessions(
            transcript_root=args.transcript_root,
            project_filter=args.project,
            brain_root=brain_root,
        )
        if args.unprocessed:
            sessions = [s for s in sessions if not s["processed"]]
        print(json.dumps({"ok": True, "sessions": sessions}, ensure_ascii=False, indent=2))
        return 0
    record = mark_processed(args.uuid, brain_root=brain_root, note=args.note)
    print(json.dumps({"ok": True, "record": record}, ensure_ascii=False, indent=2))
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
    from project_brain.search_index import StaleIndexError

    embedder = get_embedder(stub=True) if args.stub_embedder else get_embedder()
    try:
        resp = eval_recall(
            args.query, db_path=args.db, embedder=embedder, brain_root=args.brain_root
        )
    # rebuild가 해결책인 오류(누락 색인·stale 색인 가드)만 정상 JSON 안내로 —
    # 환경 장애(sqlite-vec 미설치·모델 로드 실패 등 RuntimeError)는 그대로 드러낸다.
    except (FileNotFoundError, StaleIndexError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    # raw 채널(§2.2): 청크 발췌에 신뢰 라벨을 항목마다 박는다 — 어시스턴트가 결과만
    # 보고도 "검수 안 된 원문 발췌"임을 놓치지 않게(candidate 채널 라벨 규약과 동형).
    raw_excerpts = [{**h, "trust_label": "원문 발췌(미검수)"}
                    for h in resp.get("raw_excerpts", [])]
    # projection_reuse 채널(spec 2026-06-17 Task A5): 이전 착수 브리핑 재사용 후보를
    # 신뢰 라벨과 함께 낸다 — 채널은 candidate·reviewed 공통이고 라벨만 status로 가른다
    # (reviewed=검증된 브리핑, candidate=미검증 후보). raw_excerpts 라벨 규약과 동형.
    projection_reuse = [
        {**h, "trust_label": ("재사용 브리핑(검증됨)" if h.get("status") == "reviewed"
                              else "재사용 후보(미검증)")}
        for h in resp.get("projection_reuse", [])
    ]
    print(json.dumps(
        {"ok": True, "query": args.query,
         "results": resp["results"], "candidates": resp["candidates"],
         "raw_excerpts": raw_excerpts,
         "projection_reuse": projection_reuse,
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


def _run_lint(argv) -> int:
    """코퍼스 무결성 검사 (lint.py lint_store) — 가리키는 대상이 없는 끊긴 참조를
    보고한다. ingest는 부분 배치라 적재 시점엔 자동 실행하지 않는다(나중에 채울
    참조를 끊긴 것으로 오판). 한 묶음 적재가 끝난 뒤 전체를 점검하는 독립 명령."""
    parser = argparse.ArgumentParser(prog="cli lint")
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    args = parser.parse_args(argv)
    store = BrainStore.load(resolve_brain_root(args.brain_root))
    problems = lint_store(store)
    print(json.dumps({"ok": not problems, "problems": problems},
                     ensure_ascii=False, indent=2))
    return 0 if not problems else 1


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


def _run_build(argv) -> int:
    parser = argparse.ArgumentParser(prog="cli build")
    parser.add_argument("--notes", required=True, help="구조화 노트 JSON 경로")
    parser.add_argument("--objects-file", required=True, help="조립 결과 객체 묶음 출력 경로")
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    args = parser.parse_args(argv)

    from project_brain.assembly import build
    from project_brain.store import BrainStore

    brain_root = resolve_brain_root(args.brain_root)
    notes = json.loads(Path(args.notes).read_text(encoding="utf-8"))
    # 객체 created_at/updated_at/verified_at 시점. 노트에 context.now를 적으면 그 값을
    # 쓰고(소급·테스트 override), 없으면 엔진이 현재 KST를 자동으로 박는다.
    now = notes.get("context", {}).get("now") or now_kst()
    store = BrainStore.load(brain_root)
    result = build(notes, store, now)
    if result["errors"]:
        print(json.dumps({"ok": False, "errors": result["errors"]},
                         ensure_ascii=False, indent=2))
        return 1
    Path(args.objects_file).write_text(
        json.dumps(result["objects"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "built": len(result["objects"]),
                      "objects_file": args.objects_file, "diff": result["diff"],
                      "resolved_refs": result["resolved_refs"],
                      "preconditions": result["preconditions"],
                      "warnings": result.get("warnings", [])},
                     ensure_ascii=False, indent=2))
    return 0


def _run_projection_refresh(args) -> int:
    """저장된 ContextProjection의 source_content_hash를 현재 store로 재계산해 같은
    status로 ingest() 경유 재저장한다 (C2 해시식 변경 후 전수 마이그레이션·일반 갱신).

    dangling(구성 객체가 store에 없음)은 재계산으로도 못 고치고 store에 남아 ingest의
    merged lint(전수)를 막으므로, skipped_dangling으로 보고하고 빠른 실패한다 — 먼저 누락
    소스를 해소하라(전수 refresh는 코퍼스가 해시 외엔 lint-clean이어야 한다). 이미 신선한
    projection은 건너뛴다(불필요한 쓰기 방지). 변경분은 한 번의 ingest로 배치 저장 —
    마이그레이션 자가치유(한 개씩 ingest하면 아직 옛 해시인 나머지가 merged lint mismatch를
    일으켜 깨진다). reviewed→reviewed 멱등 재적재는 ingest가 허용한다(promote의 가드와 달리)."""
    from project_brain.lint import _compute_source_content_hash

    brain_root = resolve_brain_root(args.brain_root)
    store = BrainStore.load(brain_root)

    if args.ids:
        missing = [pid for pid in args.ids if not store.has(pid)]
        if missing:
            print(json.dumps({"ok": False, "error": f"unknown ids: {missing}"},
                             ensure_ascii=False, indent=2))
            return 1
        targets = [store.get(pid) for pid in args.ids]
        not_projection = [p["id"] for p in targets if p.get("kind") != "ContextProjection"]
        if not_projection:
            print(json.dumps({"ok": False, "error": f"not ContextProjection: {not_projection}"},
                             ensure_ascii=False, indent=2))
            return 1
    else:
        targets = list(store.by_kind("ContextProjection"))

    refreshed, unchanged, skipped_dangling, to_ingest = [], [], [], []
    for proj in targets:
        sids = proj.get("source_object_ids") or []
        if any(not store.has(oid) for oid in sids):
            skipped_dangling.append(proj["id"])
            continue
        new_hash = _compute_source_content_hash(store, sids)
        if new_hash == proj.get("source_content_hash"):
            unchanged.append(proj["id"])
            continue
        updated = dict(proj)
        updated["source_content_hash"] = new_hash
        to_ingest.append(updated)
        refreshed.append(proj["id"])

    # dangling이 있으면 store에 남아 ingest의 merged lint(전수)를 막아 갱신 가능분까지 통째로
    # 깨진다. 혼란스러운 IngestError 대신 여기서 명확히 빠른 실패 — skipped_dangling을 출력에
    # 담고 누락 소스를 먼저 해소하라고 안내한다. (healthy 코퍼스면 skipped_dangling이 비어 통과.)
    if skipped_dangling:
        print(json.dumps(
            {"ok": False,
             "error": (f"{len(skipped_dangling)} dangling projection(s) block refresh — "
                       "구성 객체가 store에 없어 merged lint를 막는다; 누락 소스를 먼저 해소하라"),
             "skipped_dangling": skipped_dangling,
             "refreshable": refreshed, "unchanged": unchanged},
            ensure_ascii=False, indent=2))
        return 1

    if to_ingest:
        try:
            ingest(brain_root, to_ingest)
        except IngestError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1

    print(json.dumps(
        {"ok": True, "refreshed": refreshed, "unchanged": unchanged,
         "skipped_dangling": skipped_dangling},
        ensure_ascii=False, indent=2))
    return 0


def _run_projection(argv) -> int:
    """ContextProjection 빌드·저장 (외부 리뷰 Important 3, codex 합의 A안).

    `projection build-reuse` — 요구 부분집합 재사용 브리핑(prompt_payload candidate
    projection)을 도구가 만든다. hash·source_content_hash·projection_hash는 인자로
    받지 않고 build_reuse_projection이 계산한다(수작업 JSON이 hash/source를 틀려
    dangling을 만드는 것을 차단). --write면 ingest() 경유로 저장한다(schema+merged
    lint+후퇴 가드를 타려고 save_object 직접 호출 금지). --write 없으면 미리보기만."""
    parser = argparse.ArgumentParser(prog="cli projection")
    sub = parser.add_subparsers(dest="action", required=True)

    p_reuse = sub.add_parser("build-reuse")
    p_reuse.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    p_reuse.add_argument("--context-id", required=True)
    p_reuse.add_argument("--requirement-key", required=True)
    p_reuse.add_argument("--source-object-ids", required=True, nargs="+",
                         help="브리핑 근거가 된 객체 id 1개 이상(전부 store에 있어야 함)")
    p_reuse.add_argument("--title", required=True)
    p_reuse.add_argument("--payload-file", required=True,
                         help="reuse_payload 본문(착수 브리핑 텍스트)을 읽을 파일 경로")
    p_reuse.add_argument("--generated-by", required=True)
    p_reuse.add_argument("--write", action="store_true",
                         help="없으면 생성될 projection JSON 미리보기만(저장 안 함)")
    p_reuse.add_argument("--replace", action="store_true",
                         help="같은 projection id가 store에 이미 있을 때만 교체 허용")

    p_refresh = sub.add_parser(
        "refresh",
        help="저장 projection의 source_content_hash를 현재 store로 재계산해 재저장(C2 후 전수 마이그레이션)")
    p_refresh.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    p_refresh.add_argument("--ids", nargs="+",
                           help="대상 projection id (생략 시 전체 ContextProjection)")
    args = parser.parse_args(argv)

    if args.action == "refresh":
        return _run_projection_refresh(args)

    from project_brain.context_projection import build_reuse_projection

    brain_root = resolve_brain_root(args.brain_root)
    store = BrainStore.load(brain_root)

    # 생성 시점 dangling 차단(codex 합의): source가 하나라도 store에 없으면 멈춘다.
    missing = [oid for oid in args.source_object_ids if not store.has(oid)]
    if missing:
        print(json.dumps({"ok": False, "error": f"unknown source-object-ids: {missing}"},
                         ensure_ascii=False, indent=2))
        return 1
    if not store.has(args.context_id):
        print(json.dumps({"ok": False, "error": f"unknown context-id: {args.context_id}"},
                         ensure_ascii=False, indent=2))
        return 1

    payload = Path(args.payload_file).read_text(encoding="utf-8")
    # mark-checked와 같은 방식의 현재 시각(코퍼스 datetime 표준 KST +09:00, microsecond 없음).
    now = now_kst()
    projection = build_reuse_projection(
        store,
        context_id=args.context_id,
        requirement_key=args.requirement_key,
        source_object_ids=args.source_object_ids,
        reuse_payload=payload,
        title=args.title,
        generated_at=now,
        generated_by=args.generated_by,
    )

    if not args.write:
        print(json.dumps({"ok": True, "preview": True, "projection": projection},
                         ensure_ascii=False, indent=2))
        return 0

    # 같은 id가 이미 있으면 기본 거부 — --replace 줄 때만 교체(codex 합의).
    if store.has(projection["id"]) and not args.replace:
        print(json.dumps(
            {"ok": False,
             "error": f"{projection['id']} already exists — pass --replace to overwrite"},
            ensure_ascii=False, indent=2))
        return 1
    # reviewed reuse projection은 --replace로도 재생성 막힘(정책 A: 재검증 강제, 스펙 §3.4).
    # build-reuse는 항상 candidate를 만들고, ingest 후퇴 가드가 reviewed→candidate를 거부한다.
    # 그 가드의 불친절한 IngestError 전에 길 안내를 준다 — 낡은 reviewed 브리핑은 같은 id
    # 재생성이 아니라 query-skill §8 재조립으로 풀고, 갱신 메커니즘은 후속 과제(스펙 §7).
    if store.has(projection["id"]) and store.get(projection["id"]).get("status") == "reviewed":
        print(json.dumps(
            {"ok": False,
             "error": (f"{projection['id']} is reviewed; regeneration is intentionally blocked "
                       "(re-review policy). If stale, reassemble via query-skill §8 instead of "
                       "regenerating the same id. reviewed-projection update is a follow-up (spec §7).")},
            ensure_ascii=False, indent=2))
        return 1
    # ingest() 경유 저장: schema + merged lint + reviewed→candidate 후퇴 가드를 탄다.
    try:
        ingest(brain_root, [projection])
    except IngestError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, "id": projection["id"]}, ensure_ascii=False, indent=2))
    return 0


def _run_graph(argv) -> int:
    """그래프 분석 (읽기 전용 — store 변경 0). 하위명령: isolated · export.

    `graph isolated [--brain-root <path>] [--kind <Kind> ...]` — 코퍼스 전체에서
    인바운드 0(아무도 안 가리킴 = 고립)인 잎 객체 id를 JSON으로 낸다. 기본 점검 대상은
    '가리켜지려고 존재하는 잎' kind(CodeLocator·GlossaryTerm·EvidenceRef); --kind로 한정 가능.
    발견 전용이라 차단하지 않는다 — 어디에 무엇을 연결할지는 사람·스킬 몫(C7).

    `graph export <out.html> [--brain-root <path>]` — 코퍼스를 vis-network 단일 HTML로
    써서 브라우저로 탐색한다. 엣지는 isolated와 같은 정본 정의(INBOUND_REF_FIELDS)라
    어떤 잎이 왜 고립인지 화면에서 그대로 보인다. vis-network는 CDN에서 받으므로 볼 때
    인터넷이 필요하다. 읽기 전용 — store는 불변, 출력 파일만 쓴다."""
    parser = argparse.ArgumentParser(prog="cli graph")
    sub = parser.add_subparsers(dest="action", required=True)
    p_iso = sub.add_parser("isolated")
    p_iso.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    p_iso.add_argument("--kind", nargs="+",
                       help="점검 대상 kind 한정 (기본: CodeLocator·GlossaryTerm·EvidenceRef 잎 kind). "
                            "주의: 기본 잎 밖 kind(예: SlideRef)는 인바운드 엣지(slide_refs 등)가 "
                            "INBOUND_REF_FIELDS에 없어 거짓 고립이 날 수 있다")
    p_exp = sub.add_parser("export")
    p_exp.add_argument("out", help="출력 HTML 경로")
    p_exp.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    args = parser.parse_args(argv)

    store = BrainStore.load(resolve_brain_root(args.brain_root))

    if args.action == "export":
        from project_brain.graph_viz import build_payload, payload_to_html
        payload = build_payload(store)
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload_to_html(payload), encoding="utf-8")
        print(json.dumps(
            {"ok": True, "out": str(out_path),
             "nodes": len(payload["nodes"]), "edges": len(payload["edges"]),
             "kinds": dict(sorted(payload["kinds"].items(), key=lambda x: -x[1]))},
            ensure_ascii=False, indent=2))
        return 0

    from project_brain.graph import find_isolated
    isolated = find_isolated(store, kinds=args.kind)
    by_kind: dict = {}
    for oid in isolated:
        by_kind[store.get(oid).get("kind")] = by_kind.get(store.get(oid).get("kind"), 0) + 1
    print(json.dumps(
        {"ok": True, "isolated_count": len(isolated),
         "by_kind": {k: by_kind[k] for k in sorted(by_kind)},
         "isolated": isolated},
        ensure_ascii=False, indent=2))
    return 0


def _run_stale_check(argv) -> int:
    """코드 변경 → 의미 갱신 대상 발견 (spec §3). 읽기 전용 — brain 데이터 불변."""
    parser = argparse.ArgumentParser(prog="cli stale-check")
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config)")
    parser.add_argument("--repo-root", help="git 레포 루트 (기본: brain-root의 부모 — brain이 레포 루트 직하라 가정)")
    parser.add_argument("--no-fetch", action="store_true",
                        help="git fetch 생략(오프라인·테스트)")
    args = parser.parse_args(argv)

    from project_brain.stale_check import GitError, make_git_runner, stale_check

    brain_root = resolve_brain_root(args.brain_root)
    store = BrainStore.load(brain_root)
    repo_root = Path(args.repo_root) if args.repo_root else brain_root.parent
    git_runner = make_git_runner(repo_root)
    try:
        report = stale_check(store, git_runner=git_runner, fetch=not args.no_fetch)
    except GitError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))
    return 0


def _run_mark_checked(argv) -> int:
    """검토 완료 매핑으로 locator closure를 mark (spec §4). 갱신 locator만 저장."""
    parser = argparse.ArgumentParser(prog="cli mark-checked")
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config)")
    parser.add_argument("--repo-root", help="git 레포 루트 (기본: brain-root의 부모 — brain이 레포 루트 직하라 가정)")
    parser.add_argument("--mappings", required=True, nargs="+",
                        help="'의미 그대로'로 검토 완료한 매핑 id 목록")
    parser.add_argument("--checked-head", required=True,
                        help="검토 기준 develop sha (stale-check가 낸 target_head)")
    parser.add_argument("--no-fetch", action="store_true",
                        help="git fetch 생략(오프라인·테스트). 주의: write 명령이라 "
                             "checked_head 경합 가드가 로컬 origin/develop 기준으로 약해진다")
    args = parser.parse_args(argv)

    from project_brain.stale_check import (
        GitError,
        make_git_runner,
        mark_checked,
        resolve_target_head,
    )

    brain_root = resolve_brain_root(args.brain_root)
    store = BrainStore.load(brain_root)
    repo_root = Path(args.repo_root) if args.repo_root else brain_root.parent
    git_runner = make_git_runner(repo_root)
    if args.no_fetch:
        print("warning: --no-fetch는 checked_head 경합 가드를 로컬 origin/develop 기준으로 "
              "약화시킨다(쓰기 명령 — 최신 develop 미반영 위험).", file=sys.stderr)
    try:
        current_head = resolve_target_head(git_runner, fetch=not args.no_fetch)
    except GitError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    # 코퍼스 datetime 표준(KST +09:00, microsecond 없음)에 맞춘다.
    now = now_kst()
    result = mark_checked(store, mapping_ids=args.mappings,
                          checked_head=args.checked_head, current_head=current_head, now=now)
    if not result["ok"]:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    # 쓰기 전 schema 검증 후에만 save(promote의 '쓰기 전 검증' 원칙). CodeLocator의
    # commit_sha/verified_at/updated_at만 갱신해 관계가 안 바뀌므로 store lint는 불필요
    # (promote는 관계를 바꿔 merged lint까지 하지만 여긴 해당 없음).
    schema_errors = []
    for loc in result["updated"]:
        schema_errors.extend(validate_object(loc))
    if schema_errors:
        print(json.dumps({"ok": False, "error": "; ".join(schema_errors)},
                         ensure_ascii=False, indent=2))
        return 1
    for loc in result["updated"]:
        BrainStore.save_object(brain_root, loc)
    print(json.dumps(
        {"ok": True, "updated": [loc["id"] for loc in result["updated"]],
         "blocked": result["blocked"], "warnings": result["warnings"]},
        ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    argv = sys.argv[1:]
    try:
        # 첫 인자가 서브커맨드면 해당 경로, 아니면 기존 query 경로 호환 유지(AC6)
        if argv and argv[0] == "build":
            return _run_build(argv[1:])
        if argv and argv[0] == "ingest":
            return _run_ingest(argv[1:])
        if argv and argv[0] == "index":
            return _run_index(argv[1:])
        if argv and argv[0] == "session":
            return _run_session(argv[1:])
        if argv and argv[0] == "search":
            return _run_search(argv[1:])
        if argv and argv[0] == "eval":
            return _run_eval(argv[1:])
        if argv and argv[0] == "lint":
            return _run_lint(argv[1:])
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
        if argv and argv[0] == "projection":
            return _run_projection(argv[1:])
        if argv and argv[0] == "graph":
            return _run_graph(argv[1:])
        if argv and argv[0] == "stale-check":
            return _run_stale_check(argv[1:])
        if argv and argv[0] == "mark-checked":
            return _run_mark_checked(argv[1:])
        return _run_query(argv)
    except ConfigError as exc:
        # 경로 미지정 + config 부재 — traceback 대신 해결책이 담긴 메시지로 끝낸다.
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
