import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from project_brain.config import (
    ConfigError,
    load_config,
    resolve_brain_root,
    resolve_default_branch,
    resolve_scenarios_path,
)
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
from project_brain.mutation import MutationOperation, corpus_fingerprint
from project_brain.repo_context import (
    RepoContext,
    RepoVerificationError,
    resolve_repo_context,
)


def _add_mutation_context_arguments(
    parser: argparse.ArgumentParser,
    *,
    engine_required: bool,
) -> None:
    parser.add_argument("--repo-root", help="검증할 Git worktree의 absolute root")
    parser.add_argument("--expected-repo-id", help="canonical repository identity")
    parser.add_argument("--expected-revision-ref", help="검증 대상 Git ref")
    parser.add_argument(
        "--engine-sha",
        required=engine_required,
        help="이 mutation을 수행하는 Project Brain exact commit SHA",
    )


def _resolve_mutation_context(
    args,
    brain_root: Path,
    *,
    required: bool,
) -> RepoContext | None:
    """명시 인자 또는 project config에서 mutation용 repo context를 해석한다."""
    cfg = load_config(start=brain_root)
    repo_root = (
        Path(args.repo_root).resolve()
        if args.repo_root
        else cfg["root"].resolve() if cfg is not None else None
    )
    configured_repo_id = cfg.get("repo") if cfg is not None else None
    expected_repo_id = args.expected_repo_id or configured_repo_id
    expected_revision_ref = args.expected_revision_ref
    if expected_revision_ref is None and cfg is not None:
        expected_revision_ref = (
            f"origin/{resolve_default_branch(start=brain_root)}"
        )
    if (
        not required
        and repo_root is None
        and expected_repo_id is None
        and expected_revision_ref is None
    ):
        return None
    missing = [
        name
        for name, value in (
            ("repo_root", repo_root),
            ("expected_repo_id", expected_repo_id),
            ("expected_revision_ref", expected_revision_ref),
        )
        if value is None or (isinstance(value, str) and not value.strip())
    ]
    if missing:
        raise ConfigError(
            "mutation repository context를 알 수 없다: "
            + ", ".join(missing)
            + " — 명시 플래그나 .project-brain.json 설정을 제공하라."
        )
    return resolve_repo_context(
        repo_root,
        expected_repo_id=expected_repo_id,
        configured_repo_id=configured_repo_id or expected_repo_id,
        expected_revision_ref=expected_revision_ref,
    )


def _apply_mutation(
    *,
    operation: MutationOperation,
    brain_root: Path,
    repo_context: RepoContext | None,
    engine_sha: str,
    objects,
    preconditions=None,
    expected_corpus_fingerprint=None,
    batch_binding=None,
    coverage=None,
    build_binding=None,
):
    return ingest(
        brain_root,
        objects,
        preconditions=preconditions,
        engine_sha=engine_sha,
        repo_context=repo_context,
        operation=operation,
        expected_corpus_fingerprint=expected_corpus_fingerprint,
        batch_binding=batch_binding,
        coverage=coverage,
        build_binding=build_binding,
    )


def _object_preconditions(
    store: BrainStore,
    object_ids,
) -> dict[str, str]:
    return {
        object_id: hashlib.sha256(
            BrainStore.object_bytes(store.get(object_id))
        ).hexdigest()
        for object_id in object_ids
    }


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _run_query(argv) -> int:
    # 최상위 파서는 query 폴백을 겸한다(서브커맨드는 main에서 수동 분기). --help에서
    # 서브커맨드를 발견할 수 있게 epilog로 목록을 싣는다 — 상세는 각 명령 --help.
    parser = argparse.ArgumentParser(
        epilog=(
            "서브커맨드 (상세는 `project-brain <명령> --help`):\n"
            "  적재·검수   build  ingest  promote  promote-auto  session\n"
            "  검색·색인   search  show  index  eval  projection\n"
            "  그래프      graph (isolated · export)\n"
            "  점검·진단   lint  doctor  bootstrap  stale-check  mark-checked\n"
            "  설치        install\n"
            "인자로 준 자유 텍스트는 질의(query)로 처리됩니다."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    parser.add_argument("--current-head")
    parser.add_argument("--db", help="색인 DB 경로 (기본: config에 있고 실제 존재하는 DB)")
    parser.add_argument("--stub-embedder", action="store_true",
                        help="실모델 대신 stub 임베더 사용(테스트·CI 결정론, §5)")
    parser.add_argument("query", nargs="?")
    args = parser.parse_args(argv)

    cwd_config = (
        None
        if args.brain_root is not None and args.db is not None
        else load_config()
    )
    brain_root = resolve_brain_root(args.brain_root)
    store = BrainStore.load(brain_root)
    if not args.query:
        parser.error("query is required")
    # embedder None이면 recall 층이 색인과 같은 팩토리(get_embedder)로 만든다.
    embedder = get_embedder(stub=True) if args.stub_embedder else None
    # stale-set 캐시(.brain-local/stale-set.json)가 있으면 매핑id→advisory로 주입.
    # 파일 IO는 CLI 책임 — router는 dict만 소비(git·파일 모름). 없으면 {}(동작 불변).
    from project_brain.stale_check import advisories_by_mapping, load_stale_set
    stale_advisories = advisories_by_mapping(load_stale_set(brain_root))
    configured = None
    if args.db is None:
        configured = (
            cwd_config
            if cwd_config is not None and cwd_config["brain_root"] == brain_root
            else load_config(start=brain_root)
        )
        if configured is not None and configured["brain_root"] != brain_root:
            configured = None
    db_path = (
        Path(args.db)
        if args.db
        else configured["db"]
        if configured is not None and configured["db"].exists()
        else None
    )
    router = QueryRouter(
        store, current_head=args.current_head,
        db_path=db_path,
        embedder=embedder, brain_root=brain_root,
        stale_advisories=stale_advisories,
    )
    answer = router.answer(args.query)
    print(json.dumps(answer, ensure_ascii=False, indent=2))
    return 0


def _index_rebuild_error_report(exc: Exception) -> dict:
    """재구축 실패의 교체 여부를 CLI JSON으로 명시한다."""
    return {
        "ok": False,
        "error": str(exc),
        "committed": getattr(exc, "committed", False),
    }


def _run_ingest(argv) -> int:
    parser = argparse.ArgumentParser(prog="cli ingest")
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    parser.add_argument("--objects-file", required=True)
    parser.add_argument("--coverage-file", required=True)
    parser.add_argument("--build-report")
    parser.add_argument("--preconditions-file",
                        help="direct 적재용 순수 ID→hash JSON")
    parser.add_argument("--batch-binding-file")
    parser.add_argument("--verify-json")
    parser.add_argument("--domain-spec-py")
    _add_mutation_context_arguments(parser, engine_required=True)
    args = parser.parse_args(argv)

    from project_brain.coverage import (
        CoverageError,
        build_artifact_binding,
        normalize_build_artifact_binding,
        read_coverage,
    )

    try:
        coverage_binding = read_coverage(Path(args.coverage_file))
    except CoverageError as exc:
        print(json.dumps(
            {"ok": False, "error_code": exc.code, **exc.as_dict()},
            ensure_ascii=False,
            indent=2,
        ))
        return 1
    if coverage_binding.mode == "assembled":
        if args.build_report is None:
            parser.error("assembled coverage에는 --build-report가 필요합니다")
        if args.preconditions_file is not None:
            parser.error(
                "assembled coverage는 --preconditions-file을 받지 않습니다"
            )
    elif args.build_report is not None:
        parser.error("direct coverage는 --build-report를 받지 않습니다")

    brain_root = resolve_brain_root(args.brain_root).resolve()
    objects = json.loads(Path(args.objects_file).read_text(encoding="utf-8"))
    build_binding = None
    preconditions = None
    try:
        if args.build_report is not None:
            report = json.loads(
                Path(args.build_report).read_text(encoding="utf-8")
            )
            if not isinstance(report, Mapping):
                raise ValueError("build report must contain an object")
            required = {
                "coverage_sha256",
                "expected_objects",
                "actual_objects",
                "objects_sha256",
                "build_binding",
                "preconditions",
            }
            missing = sorted(required - set(report))
            if missing:
                raise ValueError(
                    "build report is missing fields: " + ", ".join(missing)
                )
            if not isinstance(report["build_binding"], Mapping):
                raise ValueError("build_binding must contain an object")
            build_binding = normalize_build_artifact_binding(
                report["build_binding"]
            )
            binding_dict = build_binding.as_dict()
            for field_name in (
                "coverage_sha256",
                "expected_objects",
                "actual_objects",
                "objects_sha256",
            ):
                if report[field_name] != binding_dict[field_name]:
                    raise ValueError(
                        f"build report {field_name} does not match build_binding"
                    )
            preconditions = report["preconditions"]
            recalculated = build_artifact_binding(coverage_binding, objects)
            if recalculated != build_binding:
                raise CoverageError(
                    "coverage_binding_mismatch",
                    "objects file does not match build report",
                    section="objects",
                    coverage_sha256=coverage_binding.sha256,
                )
        elif args.preconditions_file is not None:
            preconditions = json.loads(
                Path(args.preconditions_file).read_text(encoding="utf-8")
            )
        if preconditions is not None and (
            not isinstance(preconditions, Mapping)
            or not all(
                isinstance(object_id, str)
                and isinstance(expected_hash, str)
                and len(expected_hash) == 64
                and all(char in "0123456789abcdef" for char in expected_hash)
                for object_id, expected_hash in preconditions.items()
            )
        ):
            raise ValueError("preconditions must be a pure ID→SHA-256 object")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, CoverageError) as exc:
        if isinstance(exc, CoverageError):
            payload = {
                "ok": False,
                "error_code": exc.code,
                **exc.as_dict(),
            }
        else:
            payload = {
                "ok": False,
                "error_code": "coverage_binding_mismatch",
                "error": str(exc),
                "error_details": {
                    "section": "build_report"
                    if args.build_report is not None
                    else "preconditions"
                },
            }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    batch_binding = None
    batch_paths = (
        args.batch_binding_file,
        args.verify_json,
        args.domain_spec_py,
    )
    if any(value is not None for value in batch_paths):
        if not all(value is not None for value in batch_paths):
            parser.error(
                "--batch-binding-file, --verify-json, --domain-spec-py는 "
                "함께 필요합니다"
            )
        from project_brain.transaction_receipt import (
            read_batch_binding,
            verify_batch_input_files,
        )
        try:
            batch_binding = read_batch_binding(
                Path(args.batch_binding_file)
            )
            verify_batch_input_files(
                batch_binding,
                verify_json=Path(args.verify_json),
                domain_spec_py=Path(args.domain_spec_py),
            )
        except (OSError, ValueError) as exc:
            print(json.dumps(
                {"ok": False, "error": f"batch binding invalid: {exc}"},
                ensure_ascii=False,
            ))
            return 1
    repo_context = _resolve_mutation_context(
        args,
        brain_root,
        required=(
            batch_binding is not None
            or any(obj.get("kind") == "CodeLocator" for obj in objects)
        ),
    )
    if batch_binding is not None:
        from project_brain.config import load_config
        from project_brain.repo_context import resolve_git_checkout

        try:
            if args.brain_root is None:
                raise ValueError("batch ingest requires explicit --brain-root")
            engine_state = resolve_git_checkout(Path(__file__))
            if repo_context is None:
                raise ValueError("batch ingest requires repo context")
            configured = load_config(start=repo_context.repo_root)
            if (
                configured is None
                or configured["root"].resolve() != repo_context.repo_root
                or configured["brain_root"].resolve() != brain_root
                or brain_root != Path(batch_binding.brain_root)
            ):
                raise ValueError("batch binding brain_root/config mismatch")
            brain_stat = brain_root.stat()
            expected_state = {
                "repo_root": str(repo_context.repo_root),
                "brain_root": str(brain_root),
                "brain_root_device": brain_stat.st_dev,
                "brain_root_inode": brain_stat.st_ino,
                "expected_repo_id": repo_context.expected_repo_id,
                "expected_revision_ref": repo_context.expected_revision_ref,
                "target_revision_sha": repo_context.target_revision_sha,
                "engine_root": str(engine_state.root),
                "engine_sha": engine_state.head_sha,
            }
            for field_name, expected_value in expected_state.items():
                if getattr(batch_binding, field_name) != expected_value:
                    raise ValueError(
                        f"batch binding {field_name} mismatch"
                    )
            if args.engine_sha != batch_binding.engine_sha:
                raise ValueError("batch binding engine_sha mismatch")
        except (RepoVerificationError, ValueError) as exc:
            print(json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
            ))
            return 1
    try:
        result = _apply_mutation(
            operation=MutationOperation.INGEST,
            brain_root=brain_root,
            repo_context=repo_context,
            engine_sha=args.engine_sha,
            objects=objects,
            preconditions=preconditions,
            batch_binding=batch_binding,
            coverage=coverage_binding.contract,
            build_binding=build_binding,
        )
    except IngestError as exc:
        print(json.dumps(
            {"ok": False, **exc.as_dict()},
            ensure_ascii=False,
            indent=2,
        ))
        return 1
    if batch_binding is not None:
        from project_brain.corpus_io import (
            CorpusIOError,
            recover_committed_receipt,
        )
        from project_brain.transaction_receipt import (
            verify_batch_input_files,
        )

        try:
            verify_batch_input_files(
                batch_binding,
                verify_json=Path(args.verify_json),
                domain_spec_py=Path(args.domain_spec_py),
            )
            payload = recover_committed_receipt(
                brain_root,
                batch_binding,
            )
        except (CorpusIOError, OSError, ValueError) as exc:
            print(json.dumps(
                {"ok": False, "error": str(exc), "committed": False},
                ensure_ascii=False,
            ))
            return 1
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    manifest = result.manifest
    if manifest is None:
        print(json.dumps(
            {
                "ok": False,
                "error": "mutation result is missing its manifest",
                "committed": False,
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 1
    actions = (
        manifest.creates
        + manifest.updates
        + manifest.deletes
        + manifest.renames
        + manifest.auxiliary_updates
    )
    payload = {
        "ok": True,
        "transaction_id": manifest.transaction_id,
        "operation": manifest.operation,
        "committed": bool(actions),
        "manifest_sha256": result.manifest_sha256,
        "before_fingerprint": manifest.before_fingerprint,
        "after_fingerprint": manifest.expected_after_fingerprint,
        "ingested_ids": [obj["id"] for obj in result.after_objects],
        "ingested_count": len(result.after_objects),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
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
    _add_mutation_context_arguments(parser, engine_required=True)
    args = parser.parse_args(argv)

    brain_root = resolve_brain_root(args.brain_root)
    store = BrainStore.load(brain_root)
    selection_fingerprint = corpus_fingerprint(store)
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
    to_write = promoted + records
    repo_context = _resolve_mutation_context(
        args,
        brain_root,
        required=any(obj.get("kind") == "CodeLocator" for obj in to_write),
    )
    try:
        _apply_mutation(
            operation=MutationOperation.PROMOTE,
            brain_root=brain_root,
            repo_context=repo_context,
            engine_sha=args.engine_sha,
            objects=to_write,
            preconditions=_object_preconditions(store, args.ids),
            expected_corpus_fingerprint=selection_fingerprint,
        )
    except IngestError as exc:
        print(json.dumps(
            {"ok": False, "error": str(exc)},
            ensure_ascii=False,
            indent=2,
        ))
        return 1
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
    _add_mutation_context_arguments(parser, engine_required=True)
    args = parser.parse_args(argv)

    brain_root = resolve_brain_root(args.brain_root)
    store = BrainStore.load(brain_root)
    selection_fingerprint = corpus_fingerprint(store)
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
        to_write = promoted + records
        repo_context = _resolve_mutation_context(
            args,
            brain_root,
            required=any(obj.get("kind") == "CodeLocator" for obj in to_write),
        )
        try:
            _apply_mutation(
                operation=MutationOperation.PROMOTE_AUTO,
                brain_root=brain_root,
                repo_context=repo_context,
                engine_sha=args.engine_sha,
                objects=to_write,
                preconditions=_object_preconditions(store, eligible),
                expected_corpus_fingerprint=selection_fingerprint,
            )
        except IngestError as exc:
            print(json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            ))
            return 1

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
    객체에서 전체 재구축(검증한 새 DB로 원자 교체). 미지정 경로는 config에서 해석.

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

    try:
        # --stub-embedder 플래그면 강제 stub, 아니면 환경 플래그로 판정(get_embedder 기본).
        embedder = get_embedder(stub=True) if args.stub_embedder else get_embedder()
        stats = index_rebuild(args.brain_root, args.db, embedder=embedder)
    except Exception as exc:
        print(json.dumps(_index_rebuild_error_report(exc), ensure_ascii=False, indent=2))
        return 1
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
    # advisories 채널(spec 2026-06-15 §4.6): reviewed Insight를 신뢰 라벨과 함께 낸다 —
    # eval_recall이 이미 반환하나(search.py) 출력에서 빠져 있던 비대칭 누락 복구.
    # projection_reuse/raw_excerpts 라벨 규약과 동형(검수된 통찰이라 "검증됨" 라벨).
    advisories = [{**h, "trust_label": "가로지르는 위험·교훈(검증됨)"}
                  for h in resp.get("advisories", [])]
    print(json.dumps(
        {"ok": True, "query": args.query,
         "results": resp["results"], "candidates": resp["candidates"],
         "raw_excerpts": raw_excerpts,
         "advisories": advisories,
         "projection_reuse": projection_reuse,
         "needs_clarification": resp["needs_clarification"]},
        ensure_ascii=False, indent=2))
    return 0


def _run_show(argv) -> int:
    """단일 객체를 id로 펼쳐본다 — 본문 + 1-hop 이웃을 [종류] object_id — 제목 데이터로 낸다.

    `show <id> [--brain-root <path>]` — 회상(search)으로 찾은 객체에서 그래프 연결을
    손수 따라가 탐색하기 위한 입구(객체 JSON 파일을 직접 열던 것을 대체). 이웃은
    객체의 어떤 필드든 ★저장소에 실존하는 참조 id★만 모은다 — 외부 식별자·라벨
    문자열·끊긴 참조는 store에 없어 자연히 걸러진다. neighbors[*] = {edge(필드명),
    object_id, kind, title}. 어시스턴트는 이를 `[kind] object_id — title`로 보여주면 된다.
    """
    parser = argparse.ArgumentParser(prog="cli show")
    parser.add_argument("id", help="펼쳐볼 객체 id")
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    args = parser.parse_args(argv)
    brain_root = resolve_brain_root(args.brain_root)
    store = BrainStore.load(brain_root)
    if not store.has(args.id):
        print(json.dumps({"ok": False, "error": f"object not found: {args.id}"},
                         ensure_ascii=False, indent=2))
        return 1
    obj = store.get(args.id)
    neighbors = []
    seen = set()
    for field, value in obj.items():
        if field == "id":  # 자기 id는 이웃 아님
            continue
        for ref in (value if isinstance(value, list) else [value]):
            if not isinstance(ref, str) or ref == args.id or ref in seen:
                continue
            if not store.has(ref):
                continue
            seen.add(ref)
            n = store.get(ref)
            neighbors.append({
                "edge": field,
                "object_id": ref,
                "kind": n.get("kind"),
                "title": n.get("title"),
                "display_only": True,
            })
    # stale-set 캐시에 이 객체가 들면 코드 변경·브랜치 범위 advisory를 최상위에 곁들인다(객체 본문 불변).
    from project_brain.stale_check import advisories_by_mapping, load_stale_set
    payload = {
        "ok": True,
        "object": {**obj, "display_only": True},
        "neighbors": neighbors,
        "display_only": True,
    }
    advisory = advisories_by_mapping(load_stale_set(brain_root)).get(args.id)
    if advisory:
        payload["stale_advisory"] = advisory
    print(json.dumps(payload, ensure_ascii=False, indent=2))
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


def _run_audit(argv) -> int:
    """인자를 해석하고 독립 audit 서비스의 결과를 직렬화한다."""
    parser = argparse.ArgumentParser(prog="cli audit")
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    parser.add_argument("--repo-root", help="git 레포 루트 (기본: brain-root의 부모)")
    parser.add_argument("--no-fetch", action="store_true", help="git fetch 생략(오프라인·테스트)")
    parser.add_argument("--no-stale", action="store_true",
                        help="stale-check 생략(git 없는 환경) — lint·isolated만 돈다")
    args = parser.parse_args(argv)

    brain_root = resolve_brain_root(args.brain_root)
    default_branch = resolve_default_branch(start=brain_root)
    store = BrainStore.load(brain_root)
    from project_brain.audit import run_audit

    report = run_audit(
        store,
        brain_root=brain_root,
        repo_root=Path(args.repo_root) if args.repo_root else brain_root.parent,
        default_branch=default_branch,
        fetch=not args.no_fetch,
        no_stale=args.no_stale,
        principal=None,
        acl_evaluator=None,
        now=now_kst(),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def _run_install(argv) -> int:
    """프로젝트에 config + 스킬 4종을 멱등 설치 (installer.py — manifest 추적).

    설치 직후 어시스턴트가 코퍼스를 보고 스킬 description 트리거 어휘를 맞춤
    제안하는 단계는 사람·에이전트 몫이다 — CLI는 범용 템플릿 주입까지만."""
    parser = argparse.ArgumentParser(prog="cli install")
    parser.add_argument("--target", help="프로젝트 루트 (기본: cwd)")
    parser.add_argument("--project", help="프로젝트 이름 (기본: target 디렉토리명)")
    parser.add_argument("--brain-root", default="brain",
                        help="코퍼스 상대 경로 (기본: brain)")
    parser.add_argument("--default-branch", default="", help="스킬 템플릿의 {{DEFAULT_BRANCH}} 값")
    parser.add_argument("--repo", default="", help="스킬 템플릿의 {{REPO}} 값")
    parser.add_argument("--force", action="store_true",
                        help="manifest 추적 파일의 사용자 수정도 덮어 갱신(엔진이 소스)")
    args = parser.parse_args(argv)

    from project_brain.installer import InstallConflictError, install

    target = Path(args.target) if args.target else Path.cwd()
    project = args.project or target.resolve().name
    try:
        report = install(target, project=project, brain_root=args.brain_root,
                         default_branch=args.default_branch, repo=args.repo, force=args.force)
    except InstallConflictError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
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
        try:
            embedder = get_embedder(stub=True) if args.stub_embedder else get_embedder()
            rebuilt = index_rebuild(cfg["brain_root"], cfg["db"], embedder=embedder)
        except Exception as exc:
            print(json.dumps(_index_rebuild_error_report(exc), ensure_ascii=False, indent=2))
            return 1
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
    parser.add_argument("--coverage-file", required=True, help="coverage JSON 경로")
    parser.add_argument("--objects-file", required=True, help="조립 결과 객체 묶음 출력 경로")
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    args = parser.parse_args(argv)

    from project_brain import assembly
    from project_brain.coverage import CoverageError, plan_expected_objects, read_coverage
    from project_brain.store import BrainStore

    try:
        binding = read_coverage(Path(args.coverage_file))
        brain_root = resolve_brain_root(args.brain_root)
        store = BrainStore.load(brain_root)
        plan_expected_objects(binding, store)
        notes = json.loads(Path(args.notes).read_text(encoding="utf-8"))
        if binding.mode == "assembled":
            group_names = binding.contract["verify_groups"]["names"]
            assembly.validate_assembled_inputs(
                binding=binding,
                verify_data={"groups": [{"group": name} for name in group_names]},
                notes=notes,
                store=store,
            )
        # 객체 created_at/updated_at 시점. 노트에 context.now를 적으면 그 값을 쓰고
        # (소급·테스트 override), 없으면 엔진이 현재 KST를 자동으로 박는다.
        now = notes.get("context", {}).get("now") or now_kst()
        result = assembly.build(notes, store, now)
        if result["errors"]:
            print(json.dumps({"ok": False, "errors": result["errors"]},
                             ensure_ascii=False, indent=2))
            return 1
        artifact = assembly.verify_build_output(binding, result["objects"])
    except CoverageError as exc:
        print(json.dumps(
            {"ok": False, "error_code": exc.code, **exc.as_dict()},
            ensure_ascii=False,
            indent=2,
        ))
        return 1
    _atomic_write_bytes(
        Path(args.objects_file),
        json.dumps(result["objects"], ensure_ascii=False, indent=2).encode("utf-8"),
    )
    build_binding = artifact.as_dict()
    print(json.dumps({"ok": True, "built": len(result["objects"]),
                      "objects_file": args.objects_file, "diff": result["diff"],
                      "resolved_refs": result["resolved_refs"],
                      "preconditions": result["preconditions"],
                      "warnings": result.get("warnings", []),
                      "coverage_sha256": artifact.coverage_sha256,
                      "expected_objects": build_binding["expected_objects"],
                      "actual_objects": build_binding["actual_objects"],
                      "objects_sha256": artifact.objects_sha256,
                      "build_binding": build_binding},
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
        repo_context = _resolve_mutation_context(
            args,
            brain_root,
            required=any(
                obj.get("kind") == "CodeLocator"
                for obj in to_ingest
            ),
        )
        try:
            preconditions = {
                obj["id"]: hashlib.sha256(
                    BrainStore.object_bytes(store.get(obj["id"]))
                ).hexdigest()
                for obj in to_ingest
            }
            _apply_mutation(
                operation=MutationOperation.PROJECTION_REPAIR,
                brain_root=brain_root,
                repo_context=repo_context,
                engine_sha=args.engine_sha,
                objects=to_ingest,
                preconditions=preconditions,
            )
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
    _add_mutation_context_arguments(p_reuse, engine_required=False)

    p_refresh = sub.add_parser(
        "refresh",
        help="저장 projection의 source_content_hash를 현재 store로 재계산해 재저장(C2 후 전수 마이그레이션)")
    p_refresh.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    p_refresh.add_argument("--ids", nargs="+",
                           help="대상 projection id (생략 시 전체 ContextProjection)")
    _add_mutation_context_arguments(p_refresh, engine_required=True)
    args = parser.parse_args(argv)

    if args.action == "refresh":
        return _run_projection_refresh(args)
    if args.write and not args.engine_sha:
        parser.error("--engine-sha is required with --write")

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
    repo_context = _resolve_mutation_context(
        args,
        brain_root,
        required=projection.get("kind") == "CodeLocator",
    )

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
        _apply_mutation(
            operation=MutationOperation.PROJECTION,
            brain_root=brain_root,
            repo_context=repo_context,
            engine_sha=args.engine_sha,
            objects=[projection],
        )
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
    써서 브라우저로 탐색한다. 엣지는 isolated와 같은 정본 reference_fields registry라
    어떤 잎이 왜 고립인지 화면에서 그대로 보인다. vis-network는 CDN에서 받으므로 볼 때
    인터넷이 필요하다. 읽기 전용 — store는 불변, 출력 파일만 쓴다."""
    parser = argparse.ArgumentParser(prog="cli graph")
    sub = parser.add_subparsers(dest="action", required=True)
    p_iso = sub.add_parser("isolated")
    p_iso.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    p_iso.add_argument("--kind", nargs="+",
                       help="점검 대상 kind 한정 (기본: CodeLocator·GlossaryTerm·EvidenceRef 잎 kind). "
                            "주의: 기본 잎 밖 kind(예: SlideRef)는 인바운드 엣지(slide_refs 등)가 "
                            "reference_fields registry에 없어 거짓 고립이 날 수 있다")
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
    parser.add_argument("--write-cache", action="store_true",
                        help="결과 stale-set을 .brain-local/stale-set.json에 떨궈 query/show가 읽게 함")
    args = parser.parse_args(argv)

    from project_brain.stale_check import (
        GitError,
        build_stale_set,
        make_git_runner,
        stale_check,
        write_stale_set,
    )

    brain_root = resolve_brain_root(args.brain_root)
    default_branch = resolve_default_branch(start=brain_root)
    store = BrainStore.load(brain_root)
    repo_root = Path(args.repo_root) if args.repo_root else brain_root.parent
    git_runner = make_git_runner(repo_root)
    try:
        report = stale_check(
            store, git_runner=git_runner, default_branch=default_branch,
            fetch=not args.no_fetch)
    except GitError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    payload = {"ok": True, **report}
    if args.write_cache:
        path = write_stale_set(brain_root, build_stale_set(report, now=now_kst()))
        payload["cache_written"] = str(path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _run_mark_checked(argv) -> int:
    """검토 완료 매핑으로 locator closure를 mark (spec §4). 갱신 locator만 저장."""
    parser = argparse.ArgumentParser(prog="cli mark-checked")
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config)")
    parser.add_argument("--mappings", required=True, nargs="+",
                        help="'의미 그대로'로 검토 완료한 매핑 id 목록")
    parser.add_argument("--checked-head", required=True,
                        help="검토 기준 기본 브랜치 sha (stale-check가 낸 target_head)")
    parser.add_argument("--no-fetch", action="store_true",
                        help="git fetch 생략(오프라인·테스트). 주의: write 명령이라 "
                             "checked_head 경합 가드가 로컬 기본 브랜치 기준으로 약해진다")
    _add_mutation_context_arguments(parser, engine_required=True)
    args = parser.parse_args(argv)

    from project_brain.stale_check import (
        GitError,
        MarkCheckedError,
        make_git_runner,
        plan_mark_checked,
        resolve_target_head,
    )

    brain_root = resolve_brain_root(args.brain_root)
    repo_context = _resolve_mutation_context(args, brain_root, required=True)
    default_branch = resolve_default_branch(start=brain_root)
    store = BrainStore.load(brain_root)
    git_runner = make_git_runner(repo_context.repo_root)
    if args.no_fetch:
        print(f"warning: --no-fetch는 checked_head 경합 가드를 로컬 origin/{default_branch} 기준으로 "
              f"약화시킨다(쓰기 명령 — 최신 {default_branch} 미반영 위험).", file=sys.stderr)
    try:
        current_head = resolve_target_head(
            git_runner, default_branch=default_branch, fetch=not args.no_fetch)
    except GitError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    checked_context = RepoContext(
        repo_root=repo_context.repo_root,
        expected_repo_id=repo_context.expected_repo_id,
        expected_revision_ref=repo_context.expected_revision_ref,
        target_revision_sha=current_head,
    )
    try:
        plan = plan_mark_checked(
            store,
            mapping_ids=args.mappings,
            checked_head=args.checked_head,
            repo_context=checked_context,
            engine_sha=args.engine_sha,
        )
    except MarkCheckedError as exc:
        payload = {
            "ok": False,
            "error_code": exc.code,
            "error": exc.detail,
            "locator_ids": list(exc.locator_ids),
            "updated": [],
            "blocked": [],
            "warnings": [],
        }
        if exc.invalid_inputs:
            payload["invalid_inputs"] = list(exc.invalid_inputs)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    try:
        if plan.updated:
            _apply_mutation(
                operation=MutationOperation.MARK_CHECKED,
                brain_root=brain_root,
                repo_context=plan.repo_context,
                engine_sha=plan.engine_sha,
                objects=plan.updated,
                preconditions=plan.preconditions,
                expected_corpus_fingerprint=(
                    plan.expected_corpus_fingerprint
                ),
            )
    except IngestError as exc:
        print(json.dumps(
            {"ok": False, "error": str(exc)},
            ensure_ascii=False,
            indent=2,
        ))
        return 1
    print(json.dumps(
        {"ok": True, "updated": [loc["id"] for loc in plan.updated],
         "blocked": list(plan.blocked), "warnings": list(plan.warnings)},
        ensure_ascii=False, indent=2))
    return 0


def _run_snapshot(argv) -> int:
    parser = argparse.ArgumentParser(prog="cli snapshot")
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("create")
    create.add_argument("--brain-root", required=True)
    create.add_argument("--repo-root", required=True)
    create.add_argument("--engine-root", required=True)
    create.add_argument("--output-root", required=True)
    create.add_argument("--snapshot-id", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--snapshot-root", required=True)
    verify.add_argument("--expected-manifest-sha256", required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--snapshot-root", required=True)
    restore.add_argument("--brain-root", required=True)
    restore.add_argument("--expected-manifest-sha256", required=True)
    args = parser.parse_args(argv)

    from project_brain.snapshot import (
        SnapshotError,
        SnapshotRequest,
        create_snapshot,
        restore_snapshot,
        verify_snapshot,
    )

    try:
        if args.action == "create":
            result = create_snapshot(SnapshotRequest(
                brain_root=Path(args.brain_root).absolute(),
                repo_root=Path(args.repo_root).absolute(),
                engine_root=Path(args.engine_root).absolute(),
                output_root=Path(args.output_root).absolute(),
                snapshot_id=args.snapshot_id,
            ))
            payload = {
                "ok": True,
                "snapshot_id": result.snapshot_id,
                "snapshot_root": str(result.snapshot_root),
                "manifest_path": str(result.manifest_path),
                "manifest_sha256": result.manifest_sha256,
                "file_count": result.file_count,
                "restore_scope": "brain_only",
            }
        elif args.action == "verify":
            result = verify_snapshot(
                Path(args.snapshot_root).absolute(),
                expected_manifest_sha256=args.expected_manifest_sha256,
            )
            payload = {
                "ok": result.ok,
                "snapshot_id": result.snapshot_id,
                "manifest_sha256": result.manifest_sha256,
                "file_count": result.file_count,
            }
        else:
            result = restore_snapshot(
                Path(args.snapshot_root).absolute(),
                Path(args.brain_root).absolute(),
                expected_manifest_sha256=args.expected_manifest_sha256,
            )
            payload = {
                "ok": True,
                "snapshot_id": result.snapshot_id,
                "brain_root": str(result.brain_root),
                "restored_files": list(result.restored_files),
                "restore_scope": "brain_only",
            }
    except SnapshotError as exc:
        print(json.dumps(
            {"ok": False, "error_code": exc.code, "error": exc.detail},
            ensure_ascii=False,
            indent=2,
        ))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _read_json_argument(path: str | None, default):
    if path is None:
        return default
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _run_context_replace(argv) -> int:
    parser = argparse.ArgumentParser(prog="cli context-replace")
    sub = parser.add_subparsers(dest="action", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--brain-root", required=True)
    plan.add_argument("--context-id", required=True)
    plan.add_argument("--desired-objects-file", required=True)
    plan.add_argument("--expected-drop-ids-file")
    plan.add_argument("--expected-moves-file")
    plan.add_argument("--external-reference-rewrites-file")
    plan.add_argument("--manifest", required=True)
    _add_mutation_context_arguments(plan, engine_required=True)
    apply = sub.add_parser("apply")
    apply.add_argument("--brain-root", required=True)
    apply.add_argument("--manifest", required=True)
    apply.add_argument("--expected-manifest-sha256", required=True)
    _add_mutation_context_arguments(apply, engine_required=True)
    args = parser.parse_args(argv)

    from project_brain.context_replace import (
        ContextReplaceError,
        apply_context_replace_artifact,
        create_context_replace_artifact,
        plan_context_replace,
    )

    brain_root = resolve_brain_root(args.brain_root).resolve()
    try:
        if args.action == "plan":
            desired = _read_json_argument(args.desired_objects_file, [])
            drops = _read_json_argument(args.expected_drop_ids_file, [])
            moves = _read_json_argument(args.expected_moves_file, {})
            rewrites = _read_json_argument(
                args.external_reference_rewrites_file,
                {},
            )
            repo_context = _resolve_mutation_context(
                args,
                brain_root,
                required=(
                    isinstance(desired, list)
                    and any(
                        isinstance(obj, dict)
                        and obj.get("kind") == "CodeLocator"
                        for obj in desired
                    )
                ),
            )
            request = plan_context_replace(
                context_id=args.context_id,
                existing=BrainStore.load(brain_root),
                brain_root=brain_root,
                repo_context=repo_context,
                engine_sha=args.engine_sha,
                desired_objects=desired,
                expected_drop_ids=drops,
                expected_moves=moves,
                external_reference_rewrites=rewrites,
            )
            artifact = create_context_replace_artifact(request)
            manifest_path = Path(args.manifest)
            _atomic_write_bytes(manifest_path, artifact.manifest_bytes)
            print(json.dumps({
                "ok": True,
                "manifest": str(manifest_path),
                "manifest_sha256": artifact.manifest_sha256,
                "transaction_id": artifact.manifest["transaction_id"],
                "creates": len(artifact.manifest["creates"]),
                "updates": len(artifact.manifest["updates"]),
                "deletes": len(artifact.manifest["deletes"]),
                "renames": len(artifact.manifest["renames"]),
            }, ensure_ascii=False, indent=2))
            return 0

        manifest_path = Path(args.manifest)
        manifest_bytes = manifest_path.read_bytes()
        try:
            preview = json.loads(manifest_bytes)
        except (UnicodeError, json.JSONDecodeError):
            preview = {}
        objects = preview.get("objects", []) if isinstance(preview, dict) else []
        repo_context = _resolve_mutation_context(
            args,
            brain_root,
            required=(
                isinstance(objects, list)
                and any(
                    isinstance(obj, dict)
                    and obj.get("kind") == "CodeLocator"
                    for obj in objects
                )
            ),
        )
        result = apply_context_replace_artifact(
            manifest_bytes=manifest_bytes,
            expected_manifest_sha256=args.expected_manifest_sha256,
            brain_root=brain_root,
            repo_context=repo_context,
            engine_sha=args.engine_sha,
        )
        print(json.dumps({
            "ok": True,
            "transaction_id": result.transaction_id,
            "action_count": result.action_count,
        }, ensure_ascii=False, indent=2))
        return 0
    except (ContextReplaceError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps(
            {
                "ok": False,
                "error_code": getattr(exc, "code", "context_replace_failed"),
                "error": getattr(exc, "detail", str(exc)),
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 1


def _run_migration(argv) -> int:
    parser = argparse.ArgumentParser(prog="cli migration")
    modes = parser.add_subparsers(dest="mode", required=True)
    for mode in ("id", "display"):
        mode_parser = modes.add_parser(mode)
        actions = mode_parser.add_subparsers(dest="action", required=True)
        plan = actions.add_parser("plan")
        plan.add_argument("--brain-root", required=True)
        plan.add_argument("--repo-root", required=True)
        plan.add_argument("--engine-root", required=True)
        plan.add_argument("--snapshot-root", required=True)
        plan.add_argument(
            "--expected-snapshot-manifest-sha256",
            required=True,
        )
        plan.add_argument("--manifest", required=True)
        plan.add_argument("--engine-sha", required=True)
        if mode == "id":
            plan.add_argument("--renames-file", required=True)
        apply = actions.add_parser("apply")
        apply.add_argument("--brain-root", required=True)
        apply.add_argument("--repo-root", required=True)
        apply.add_argument("--engine-root", required=True)
        apply.add_argument("--snapshot-root", required=True)
        apply.add_argument(
            "--expected-snapshot-manifest-sha256",
            required=True,
        )
        apply.add_argument("--manifest", required=True)
        apply.add_argument("--expected-manifest-sha256", required=True)
        apply.add_argument("--engine-sha", required=True)
    canonical = modes.add_parser("canonical-repair")
    canonical_actions = canonical.add_subparsers(
        dest="action",
        required=True,
    )
    for action in ("plan", "apply"):
        action_parser = canonical_actions.add_parser(action)
        action_parser.add_argument("--brain-root", required=True)
        action_parser.add_argument("--repo-root", required=True)
        action_parser.add_argument("--engine-root", required=True)
        action_parser.add_argument("--snapshot-root", required=True)
        action_parser.add_argument(
            "--expected-snapshot-manifest-sha256",
            required=True,
        )
        action_parser.add_argument("--decisions-file", required=True)
        action_parser.add_argument(
            "--expected-decisions-sha256",
            required=True,
        )
        action_parser.add_argument("--classification-file", required=True)
        action_parser.add_argument(
            "--expected-classification-sha256",
            required=True,
        )
        action_parser.add_argument("--manifest", required=True)
        action_parser.add_argument("--engine-sha", required=True)
        if action == "apply":
            action_parser.add_argument(
                "--expected-manifest-sha256",
                required=True,
            )
    args = parser.parse_args(argv)

    from project_brain.canonical_repair import (
        CanonicalRepairError,
        apply_canonical_repair_artifact,
        create_canonical_repair_artifact,
        parse_canonicalization_ledger,
        plan_canonical_repair,
    )
    from project_brain.corpus_io import CorpusIOError
    from project_brain.migration import (
        MigrationError,
        apply_migration_artifact,
        create_migration_artifact,
        plan_display_migration,
        plan_id_migration,
        verify_snapshot,
    )
    from project_brain.snapshot import SnapshotError
    from project_brain.store import StoreLoadError

    brain_root = resolve_brain_root(args.brain_root).resolve()
    try:
        if args.action == "plan":
            snapshot = verify_snapshot(
                Path(args.snapshot_root).absolute(),
                expected_manifest_sha256=(
                    args.expected_snapshot_manifest_sha256
                ),
            )
            store = BrainStore.load(brain_root)
            if args.mode == "canonical-repair":
                decisions_bytes = Path(args.decisions_file).read_bytes()
                classification_bytes = Path(
                    args.classification_file
                ).read_bytes()
                ledger = parse_canonicalization_ledger(
                    decisions_bytes,
                    classification_bytes=classification_bytes,
                    expected_classification_sha256=(
                        args.expected_classification_sha256
                    ),
                    existing=store,
                    engine_sha=args.engine_sha,
                    repo_head=snapshot.repo_head,
                )
                if ledger.sha256 != args.expected_decisions_sha256:
                    raise CanonicalRepairError(
                        "decision_ledger_sha256_mismatch",
                        "decision ledger bytes do not match the trusted receipt",
                    )
                plan = plan_canonical_repair(
                    existing=store,
                    brain_root=brain_root,
                    repo_root=Path(args.repo_root).absolute(),
                    engine_root=Path(args.engine_root).absolute(),
                    engine_sha=args.engine_sha,
                    ledger=ledger,
                    snapshot=snapshot,
                )
                artifact = create_canonical_repair_artifact(plan)
                manifest_path = Path(args.manifest)
                _atomic_write_bytes(manifest_path, artifact.manifest_bytes)
                print(json.dumps({
                    "ok": True,
                    "migration_kind": "canonical_repair",
                    "manifest": str(manifest_path),
                    "manifest_sha256": artifact.manifest_sha256,
                    "transaction_id": (
                        plan.mutation_plan.manifest.transaction_id
                    ),
                    "row_count": len(plan.rows),
                    "action_count": (
                        len(plan.mutation_plan.manifest.creates)
                        + len(plan.mutation_plan.manifest.updates)
                        + len(plan.mutation_plan.manifest.deletes)
                        + len(plan.mutation_plan.manifest.renames)
                        + len(plan.mutation_plan.manifest.auxiliary_updates)
                    ),
                    "decision_ledger_sha256": ledger.sha256,
                    "phase_a_classification_sha256": (
                        ledger.phase_a_classification_sha256
                    ),
                    "snapshot_id": snapshot.snapshot_id,
                    "snapshot_manifest_sha256": snapshot.manifest_sha256,
                }, ensure_ascii=False, indent=2))
                return 0
            if args.mode == "id":
                renames = _read_json_argument(args.renames_file, {})
                plan = plan_id_migration(
                    existing=store,
                    brain_root=brain_root,
                    repo_root=Path(args.repo_root).absolute(),
                    engine_root=Path(args.engine_root).absolute(),
                    engine_sha=args.engine_sha,
                    renames=renames,
                    snapshot=snapshot,
                )
            else:
                plan = plan_display_migration(
                    existing=store,
                    brain_root=brain_root,
                    repo_root=Path(args.repo_root).absolute(),
                    engine_root=Path(args.engine_root).absolute(),
                    engine_sha=args.engine_sha,
                    snapshot=snapshot,
                )
            artifact = create_migration_artifact(plan)
            manifest_path = Path(args.manifest)
            _atomic_write_bytes(manifest_path, artifact.manifest_bytes)
            print(json.dumps({
                "ok": True,
                "migration_kind": plan.migration_kind,
                "manifest": str(manifest_path),
                "manifest_sha256": artifact.manifest_sha256,
                "transaction_id": plan.mutation_plan.manifest.transaction_id,
                "row_count": len(plan.rows),
                "action_count": (
                    len(plan.mutation_plan.manifest.creates)
                    + len(plan.mutation_plan.manifest.updates)
                    + len(plan.mutation_plan.manifest.deletes)
                    + len(plan.mutation_plan.manifest.renames)
                    + len(plan.mutation_plan.manifest.auxiliary_updates)
                ),
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_manifest_sha256": snapshot.manifest_sha256,
            }, ensure_ascii=False, indent=2))
            return 0

        manifest_bytes = Path(args.manifest).read_bytes()
        if args.mode == "canonical-repair":
            classification_bytes = Path(args.classification_file).read_bytes()
            result = apply_canonical_repair_artifact(
                manifest_bytes=manifest_bytes,
                expected_manifest_sha256=args.expected_manifest_sha256,
                decisions_bytes=Path(args.decisions_file).read_bytes(),
                expected_decisions_sha256=args.expected_decisions_sha256,
                classification_bytes=classification_bytes,
                expected_classification_sha256=(
                    args.expected_classification_sha256
                ),
                brain_root=brain_root,
                repo_root=Path(args.repo_root).absolute(),
                engine_root=Path(args.engine_root).absolute(),
                engine_sha=args.engine_sha,
                snapshot_root=Path(args.snapshot_root).absolute(),
                expected_snapshot_manifest_sha256=(
                    args.expected_snapshot_manifest_sha256
                ),
            )
            manifest_payload = json.loads(manifest_bytes)
            print(json.dumps({
                "ok": True,
                "migration_kind": "canonical_repair",
                "manifest": str(Path(args.manifest)),
                "manifest_sha256": args.expected_manifest_sha256,
                "transaction_id": result.transaction_id,
                "row_count": len(manifest_payload["rows"]),
                "action_count": result.action_count,
                "decision_ledger_sha256": (
                    result.decision_ledger_sha256
                ),
                "phase_a_classification_sha256": (
                    args.expected_classification_sha256
                ),
                "snapshot_id": result.snapshot_id,
                "snapshot_manifest_sha256": (
                    args.expected_snapshot_manifest_sha256
                ),
            }, ensure_ascii=False, indent=2))
            return 0
        result = apply_migration_artifact(
            manifest_bytes=manifest_bytes,
            expected_manifest_sha256=args.expected_manifest_sha256,
            brain_root=brain_root,
            repo_root=Path(args.repo_root).absolute(),
            engine_root=Path(args.engine_root).absolute(),
            engine_sha=args.engine_sha,
            snapshot_root=Path(args.snapshot_root).absolute(),
            expected_snapshot_manifest_sha256=(
                args.expected_snapshot_manifest_sha256
            ),
        )
        print(json.dumps({
            "ok": True,
            "transaction_id": result.transaction_id,
            "action_count": result.action_count,
            "snapshot_id": result.snapshot_id,
        }, ensure_ascii=False, indent=2))
        return 0
    except (StoreLoadError, CorpusIOError) as exc:
        if args.mode != "canonical-repair":
            raise
        print(json.dumps({
            "ok": False,
            "error_code": exc.code,
            "error": exc.detail,
        }, ensure_ascii=False, indent=2))
        return 1
    except (
        CanonicalRepairError,
        MigrationError,
        SnapshotError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({
            "ok": False,
            "error_code": getattr(exc, "code", "migration_failed"),
            "error": getattr(exc, "detail", str(exc)),
        }, ensure_ascii=False, indent=2))
        return 1


def main() -> int:
    argv = sys.argv[1:]
    try:
        # 첫 인자가 서브커맨드면 해당 경로, 아니면 기존 query 경로 호환 유지(AC6)
        if argv and argv[0] == "build":
            return _run_build(argv[1:])
        if argv and argv[0] == "query":
            return _run_query(argv[1:])
        if argv and argv[0] == "ingest":
            return _run_ingest(argv[1:])
        if argv and argv[0] == "index":
            return _run_index(argv[1:])
        if argv and argv[0] == "session":
            return _run_session(argv[1:])
        if argv and argv[0] == "search":
            return _run_search(argv[1:])
        if argv and argv[0] == "show":
            return _run_show(argv[1:])
        if argv and argv[0] == "eval":
            return _run_eval(argv[1:])
        if argv and argv[0] == "lint":
            return _run_lint(argv[1:])
        if argv and argv[0] == "audit":
            return _run_audit(argv[1:])
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
        if argv and argv[0] == "snapshot":
            return _run_snapshot(argv[1:])
        if argv and argv[0] == "context-replace":
            return _run_context_replace(argv[1:])
        if argv and argv[0] == "migration":
            return _run_migration(argv[1:])
        return _run_query(argv)
    except (ConfigError, RepoVerificationError) as exc:
        # 경로 미지정 + config 부재 — traceback 대신 해결책이 담긴 메시지로 끝낸다.
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
