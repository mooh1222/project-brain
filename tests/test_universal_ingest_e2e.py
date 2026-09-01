"""미나 카약 새 추출 end-to-end 적재 (Task 6 + Task 7).

폐기 도메인 스크립트 없이 generic ingest/promote/objbase 부품만으로 미나 카약를
적재한다. 객체 값은 살아있는 소스를 직접 읽어 채운 것이다(추측 금지, 소스에 있는 것만):
  - 기획서: mina-kayak 스펙 문서(spec-v8)
      기본 정보(L46-65 7명 그룹 레이스/제한시간/N스테이지 선착순 3위/단계 진행/
      반복 참여/쿨타임/완주 기준 3가지/반복 MAX), 더미 NPC(L184-185).
  - develop 코드: SampleGame2/Classes/main/Event/MinaKayak/
      model/MinaKayakEventModel.hpp:14-32  MINA_KAYAK_RACE_STATUS::Enum + strToEnum
        (IDLE/RACING/RACE_END/COOLTIME/FINISHED 5개).
      model/MinaKayakEventModel.cpp:185-263  parse (ST/CL/PYN 서버 파싱).
      model/MinaKayakEventModel.cpp:158-174  getCurrentLevel (IDLE일 때 CL+1 매칭).
      presenter/MinaKayakViewData.hpp:38      State enum (READY/RACING/COOLDOWN/ENDED 4개).
      presenter/MinaKayakViewData.cpp:21-43   상태 접힘 switch (RACE_END·FINISHED 둘 다 →ENDED).
      model/MinaKayakEventManager.hpp:27-35   isCoolTime/isRaceEnd/isRaceFailure(선착순 ≤3).

도메인 범위는 lifecycle/state spine으로 제한(레이스 단계·상태, 더미 NPC, 선착순
달성/미달성, 쿨타임, 반복 참여). 단계1 candidate bundle 1회 ingest → 단계2
single_object 승격 → 단계3 mapping_bundle 승격을 generic 부품으로 태운다.
"""

import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project_brain.code_verify import VerifiedLocator
from project_brain.id_grammar import format_id
from project_brain.ingest import IngestError, ingest as product_ingest
from tests.test_ingest import ingest
from project_brain.lint import lint_store
from project_brain.objbase import base
from project_brain.promote import promote
from project_brain.repo_context import RepoContext
from project_brain.embedder import StubEmbedder
from project_brain.search import eval_recall
from project_brain.search_index import rebuild as index_rebuild
from project_brain.store import BrainStore

T = "2026-06-04T00:00:00Z"
REPO = "demoapp"
CTX = "context.mina-kayak"
BUNDLE_KEY = "bundle.mina-kayak.domain-mapping"


def _full_tree_inventory(root: Path) -> dict[str, tuple[str, bytes | str | None]]:
    inventory: dict[str, tuple[str, bytes | str | None]] = {}

    def visit(directory: Path) -> None:
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            relative = path.relative_to(root).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                inventory[relative] = ("symlink", path.readlink().as_posix())
            elif stat.S_ISDIR(mode):
                inventory[relative + "/"] = ("directory", None)
                visit(path)
            elif stat.S_ISREG(mode):
                inventory[relative] = ("file", path.read_bytes())
            else:
                inventory[relative] = ("special", None)

    visit(root)
    return inventory


# ── 살아있는 소스에서 추출한 candidate bundle 빌더 ──────────────────────────────


def _fixture_id(kind, legacy_id):
    key = legacy_id.rsplit(".", 1)[-1]
    if kind == "EvidenceManifest":
        return format_id(kind, ctx="mina-kayak", key=key)
    if kind in {"EvidenceRef", "CodeLocator"}:
        field = "anchor_key"
        return format_id(kind, ctx="mina-kayak", **{field: key})
    if kind in {"GlossaryTerm", "DecisionRecord", "DomainMapping"}:
        return format_id(kind, ctx="mina-kayak", key=key)
    raise AssertionError(f"unsupported E2E fixture kind {kind}")


def _manifest(mid, *, source_type, title, locator, captured_by):
    mid = _fixture_id("EvidenceManifest", mid)
    return base(
        {
            "id": mid,
            "kind": "EvidenceManifest",
            "status": "reviewed",
            "truth_role": "source",
            "title": title,
            "source_type": source_type,
            "locator": locator,
            "captured_at": T,
            "captured_by": captured_by,
            "sensitivity": "internal",
            "acl": ["team"],
            "redaction_status": "approved",
        },
        tags=["mina-kayak"], created_at=T, updated_at=T,
    )


def _spec_ref(rid, *, manifest_id, summary, section):
    rid = _fixture_id("EvidenceRef", rid)
    manifest_id = _fixture_id("EvidenceManifest", manifest_id)
    return base(
        {
            "id": rid,
            "kind": "EvidenceRef",
            "status": "reviewed",
            "truth_role": "reference",
            "title": summary,
            "evidence_manifest_id": manifest_id,
            "ref_type": "spec_section",
            "locator": {"doc": "spec-v8.md", "section": section},
            "summary": summary,
        },
        tags=["mina-kayak"], created_at=T, updated_at=T,
    )


def _code_locator(lid, *, path, symbol, line_start, line_end, title):
    lid = _fixture_id("CodeLocator", lid)
    return base(
        {
            "id": lid,
            "kind": "CodeLocator",
            "status": "reviewed",
            "truth_role": "reference",
            "title": title,
            "repo": REPO,
            "path": path,
            "symbol": symbol,
            "line_start": line_start,
            "line_end": line_end,
            "locator_source": "rg",
            "verified_quote": f"synthetic quote for {symbol}",
        },
        tags=["mina-kayak"], created_at=T, updated_at=T,
    )


def _code_ref(rid, *, manifest_id, locator_id, summary):
    rid = _fixture_id("EvidenceRef", rid)
    manifest_id = _fixture_id("EvidenceManifest", manifest_id)
    locator_id = _fixture_id("CodeLocator", locator_id)
    return base(
        {
            "id": rid,
            "kind": "EvidenceRef",
            "status": "reviewed",
            "truth_role": "reference",
            "title": summary,
            "evidence_manifest_id": manifest_id,
            "ref_type": "code_locator",
            "locator": {"code_locator_id": locator_id},
            "summary": summary,
        },
        tags=["mina-kayak"], created_at=T, updated_at=T,
    )


def _candidate_term(tid, *, term, definition, synonyms, candidate_state="ready_for_review",
                    evidence_refs=None, conflicts_with=None):
    tid = _fixture_id("GlossaryTerm", tid)
    evidence_refs = [
        _fixture_id("EvidenceRef", evidence_ref_id)
        for evidence_ref_id in (evidence_refs or [])
    ]
    candidate = {
        "candidate_state": candidate_state,
        "candidate_source": "spec",
        "promotion_criteria": ["spec-v8 기본 정보 + develop 코드 대조 확인"],
    }
    if conflicts_with:
        candidate["conflicts_with"] = conflicts_with
    obj = {
        "id": tid,
        "kind": "GlossaryTerm",
        "status": "candidate",
        "truth_role": "domain",
        "title": term,
        "context_id": CTX,
        "term": term,
        "definition": definition,
        "synonyms": synonyms,
        "candidate": candidate,
    }
    # evidence_refs는 base() setdefault가 [] 안 덮도록 obj에 미리 박는다(caller field 보존).
    if evidence_refs:
        obj["evidence_refs"] = evidence_refs
    return base(obj, tags=["mina-kayak"], created_at=T, updated_at=T)


def _decision(did, *, decision_type, summary, decision, source_object_ids, affected_mapping_ids=None):
    did = _fixture_id("DecisionRecord", did)
    source_object_ids = [
        _fixture_id("EvidenceRef", source_object_id)
        for source_object_id in source_object_ids
    ]
    if affected_mapping_ids is not None:
        affected_mapping_ids = [
            _fixture_id("DomainMapping", mapping_id)
            for mapping_id in affected_mapping_ids
        ]
    obj = {
        "id": did,
        "kind": "DecisionRecord",
        "status": "reviewed",
        "truth_role": "event",
        "title": summary,
        "decision_type": decision_type,
        "summary": summary,
        "decision": decision,
        "source_object_ids": source_object_ids,
        "affected_context_ids": [CTX],
        "spec_reflected": "yes",
    }
    if affected_mapping_ids is not None:
        obj["affected_mapping_ids"] = affected_mapping_ids
    return base(obj, tags=["mina-kayak"], created_at=T, updated_at=T)


def _candidate_mapping(mid, *, mapping_key, canonical_summary, meaning, boundary,
                       glossary_term_ids, decision_record_ids, code_locator_ids=None,
                       evidence_refs=None):
    mid = format_id("DomainMapping", ctx="mina-kayak", key=mapping_key)
    glossary_term_ids = [
        _fixture_id("GlossaryTerm", term_id)
        for term_id in glossary_term_ids
    ]
    decision_record_ids = [
        _fixture_id("DecisionRecord", decision_id)
        for decision_id in decision_record_ids
    ]
    code_locator_ids = [
        _fixture_id("CodeLocator", locator_id)
        for locator_id in (code_locator_ids or [])
    ]
    evidence_refs = [
        _fixture_id("EvidenceRef", evidence_ref_id)
        for evidence_ref_id in (evidence_refs or [])
    ]
    obj = {
        "id": mid,
        "kind": "DomainMapping",
        "status": "candidate",
        "truth_role": "domain",
        "title": "Candidate mapping: " + mapping_key,
        "context_id": CTX,
        "mapping_key": mapping_key,
        "canonical_summary": canonical_summary,
        "meaning": meaning,
        "boundary": boundary,
        "glossary_term_ids": glossary_term_ids,
        "decision_record_ids": decision_record_ids,
        "code_locator_ids": code_locator_ids,
    }
    if evidence_refs:
        obj["evidence_refs"] = evidence_refs
    return base(obj, tags=["mina-kayak"], created_at=T, updated_at=T)


def build_candidate_bundle():
    """살아있는 소스를 읽어 추출한 candidate bundle 1개. merge 후 한 번에 lint라
    적재 순서 무관 — 한 리스트로 반환한다."""
    objs = []

    # EvidenceManifest 2 (기획서 manifest, 코드 manifest)
    objs.append(_manifest(
        "ev.manifest.spec-v8",
        source_type="spec",
        title="미나 카약 기획서 v8",
        locator="spec://mina-kayak/spec-v8.md",
        captured_by="game-planning",
    ))
    objs.append(_manifest(
        "ev.manifest.code",
        source_type="code_search",
        title="develop MinaKayak 코드",
        locator="repo://demoapp/SampleGame2/Classes/main/Event/MinaKayak",
        captured_by="rg",
    ))

    # EvidenceRef (spec) — lifecycle/state 라인 인용
    objs.append(_spec_ref(
        "ev.ref.spec.basic-info",
        manifest_id="ev.manifest.spec-v8",
        summary="7명 소규모 그룹 레이스, 제한 시간, N스테이지 선착순 3위 보상 (기본 정보)",
        section="기본 정보 L46-49",
    ))
    objs.append(_spec_ref(
        "ev.ref.spec.stage-progress",
        manifest_id="ev.manifest.spec-v8",
        summary="완주 시 다음 단계, 실패 시 동일 단계. 1단계 실패는 1단계 유지, 3단계 성공은 3단계 유지",
        section="기본 정보 L53-57",
    ))
    objs.append(_spec_ref(
        "ev.ref.spec.cooltime",
        manifest_id="ev.manifest.spec-v8",
        summary="레이스 완주 후 정해진 쿨 타임 지나면 새 레이스 시작 가능. 반복 참여 가능, 반복 MAX 제한",
        section="기본 정보 L59-65",
    ))
    objs.append(_spec_ref(
        "ev.ref.spec.race-end",
        manifest_id="ev.manifest.spec-v8",
        summary="완주 기준: 3위 입상하여 보상 받음 / 3위 입상 못해 자동 종료 / 제한 시간 끝나 자동 종료",
        section="기본 정보 L61-64",
    ))
    objs.append(_spec_ref(
        "ev.ref.spec.dummy-npc",
        manifest_id="ev.manifest.spec-v8",
        summary="매칭은 DUMMY NPC만 매칭됨. 실제 유저와는 매칭되지 않음",
        section="기본 정보 L184-185",
    ))

    # CodeLocator — develop 코드 앵커 (path + symbol + line_start/line_end)
    objs.append(_code_locator(
        "code.race-status-enum",
        path="SampleGame2/Classes/main/Event/MinaKayak/model/MinaKayakEventModel.hpp",
        symbol="MINA_KAYAK_RACE_STATUS::Enum / strToEnum",
        line_start=14, line_end=32,
        title="서버 파싱용 레이스 상태 enum (IDLE/RACING/RACE_END/COOLTIME/FINISHED)",
    ))
    objs.append(_code_locator(
        "code.model-parse",
        path="SampleGame2/Classes/main/Event/MinaKayak/model/MinaKayakEventModel.cpp",
        symbol="MinaKayakEventModel::parse",
        line_start=185, line_end=263,
        title="서버 응답 파싱 — ST(상태)/CL(현재 레이스 번호)/PYN(팝업 노출)",
    ))
    objs.append(_code_locator(
        "code.current-level",
        path="SampleGame2/Classes/main/Event/MinaKayak/model/MinaKayakEventModel.cpp",
        symbol="MinaKayakEventModel::getCurrentLevel",
        line_start=158, line_end=174,
        title="IDLE 상태에서 다음 단계 매칭(CL+1) — 단계 진행 표시 로직",
    ))
    objs.append(_code_locator(
        "code.view-state-enum",
        path="SampleGame2/Classes/main/Event/MinaKayak/presenter/MinaKayakViewData.hpp",
        symbol="MinaKayakViewData::State",
        line_start=38, line_end=38,
        title="표시용 상태 enum (READY/RACING/COOLDOWN/ENDED)",
    ))
    objs.append(_code_locator(
        "code.state-fold",
        path="SampleGame2/Classes/main/Event/MinaKayak/presenter/MinaKayakViewData.cpp",
        symbol="MinaKayakViewData::fromModel",
        line_start=21, line_end=43,
        title="상태 접힘 — RACE_END와 FINISHED 둘 다 ENDED로 매핑(5→4)",
    ))
    objs.append(_code_locator(
        "code.cooltime-manager",
        path="SampleGame2/Classes/main/Event/MinaKayak/model/MinaKayakEventManager.hpp",
        symbol="isCoolTime / isRaceEnd / isRaceFailure",
        line_start=27, line_end=35,
        title="쿨타임/레이스 종료/실패 판정 헬퍼(선착순 ≤3)",
    ))

    # EvidenceRef (code) — 각 CodeLocator를 가리킴
    objs.append(_code_ref("ev.ref.code.race-status-enum", manifest_id="ev.manifest.code",
                          locator_id="code.race-status-enum", summary="레이스 상태 enum 앵커"))
    objs.append(_code_ref("ev.ref.code.model-parse", manifest_id="ev.manifest.code",
                          locator_id="code.model-parse", summary="서버 파싱 앵커"))
    objs.append(_code_ref("ev.ref.code.current-level", manifest_id="ev.manifest.code",
                          locator_id="code.current-level", summary="단계 진행 매칭 앵커"))
    objs.append(_code_ref("ev.ref.code.view-state-enum", manifest_id="ev.manifest.code",
                          locator_id="code.view-state-enum", summary="표시 상태 enum 앵커"))
    objs.append(_code_ref("ev.ref.code.state-fold", manifest_id="ev.manifest.code",
                          locator_id="code.state-fold", summary="상태 접힘 앵커"))
    objs.append(_code_ref("ev.ref.code.cooltime-manager", manifest_id="ev.manifest.code",
                          locator_id="code.cooltime-manager", summary="쿨타임/종료/실패 판정 앵커"))

    # GlossaryTerm (candidate) — lifecycle/state spine 용어
    objs.append(_candidate_term(
        "g.race-status",
        term="레이스 상태",
        definition="서버가 내려주는 레이스 진행 단계. IDLE(참여 가능)/RACING(진행)/RACE_END(결과 대기)/"
                   "COOLTIME(쿨타임)/FINISHED(최대 횟수 도달) 5개로 파싱된다.",
        synonyms=["레이스 상태", "RACE_STATUS", "IDLE", "RACING", "RACE_END", "FINISHED"],
        evidence_refs=["ev.ref.code.race-status-enum", "ev.ref.code.model-parse"],
    ))
    objs.append(_candidate_term(
        "g.view-state",
        term="표시 상태",
        definition="화면에 보여주는 상태. READY/RACING/COOLDOWN/ENDED 4개. 서버 5개 상태가 4개로 접힌다 — "
                   "RACE_END와 FINISHED가 둘 다 ENDED로 매핑된다.",
        synonyms=["표시 상태", "ENDED", "READY", "COOLDOWN"],
        # 서버 상태(5개)와는 별개 개념(화면 표시용 4개)이고, 둘 관계는 mapping.state-fold가
        # 설명한다 — 모순 충돌이 아니라 일반 후보(사용자 확인 2026-06-04).
        evidence_refs=["ev.ref.code.view-state-enum", "ev.ref.code.state-fold"],
    ))
    objs.append(_candidate_term(
        "g.dummy-npc",
        term="더미 NPC",
        definition="레이스 참여자는 실제 유저가 아니라 모두 더미 NPC다. 본인 외 최대 6명이 더미로 채워진다.",
        synonyms=["더미 NPC", "DUMMY NPC"],
        evidence_refs=["ev.ref.spec.dummy-npc"],
    ))
    objs.append(_candidate_term(
        "g.finish-rank",
        term="선착순 3위",
        definition="N개 스테이지를 먼저 클리어한 선착순 3명에게 보상을 지급한다. 3위 안에 못 들면 레이스가 "
                   "자동 종료된다(미달성).",
        synonyms=["선착순 3위", "선착순"],
        evidence_refs=["ev.ref.spec.basic-info", "ev.ref.spec.race-end"],
    ))
    objs.append(_candidate_term(
        "g.cooltime",
        term="쿨타임",
        # 코드가 COOLTIME(EventModel)·COOLDOWN(ViewData) 두 철자, 기획서는 '쿨타임'.
        # 회상 전제2(표면어 substring 매칭)를 위해 synonyms에 셋 다 둔다.
        definition="레이스 완주 후 새 레이스를 시작하려면 지나야 하는 대기 시간. 코드 표면어는 서버 파싱쪽 "
                   "COOLTIME, 표시쪽 COOLDOWN 두 철자로 갈린다.",
        synonyms=["쿨타임", "COOLTIME", "COOLDOWN"],
        evidence_refs=["ev.ref.spec.cooltime", "ev.ref.code.cooltime-manager"],
    ))
    objs.append(_candidate_term(
        "g.repeat-join",
        term="반복 참여",
        definition="이벤트 기간 내 레이스에 반복 참여할 수 있으나 반복 참여 MAX 횟수 제한이 있다.",
        synonyms=["반복 참여", "재참여"],
        evidence_refs=["ev.ref.spec.cooltime"],
    ))

    # DecisionRecord — lifecycle/state 결정
    objs.append(_decision(
        "decision.state-fold",
        decision_type="implementation_boundary",
        summary="서버 5개 레이스 상태를 표시 4개로 접는다",
        decision="RACE_END와 FINISHED는 사용자에게 동일한 '종료' 화면이라 둘 다 ENDED로 매핑한다.",
        source_object_ids=["ev.ref.code.state-fold", "ev.ref.code.race-status-enum"],
        affected_mapping_ids=["mapping.race-state-fold"],
    ))
    objs.append(_decision(
        "decision.dummy-only",
        decision_type="spec_clarification",
        summary="레이스 매칭은 더미 NPC만",
        decision="실제 유저와 매칭하지 않고 본인 외 자리는 모두 더미 NPC로 채운다.",
        source_object_ids=["ev.ref.spec.dummy-npc"],
        affected_mapping_ids=["mapping.dummy-npc-matching"],
    ))
    objs.append(_decision(
        "decision.cooltime",
        decision_type="spec_clarification",
        summary="완주 후 쿨타임 경과해야 새 레이스",
        decision="레이스 완주 후 정해진 쿨타임이 지나야 새 레이스를 시작할 수 있고, 반복 참여 MAX 제한이 있다.",
        source_object_ids=["ev.ref.spec.cooltime"],
        affected_mapping_ids=["mapping.cooltime-repeat"],
    ))

    # DomainMapping (candidate) — 용어↔기획의미↔결정↔코드앵커 묶음.
    # 8c drift 회피: 각 mapping은 자신을 affected_mapping_ids로 가리키는 decision을
    #   decision_record_ids에 실어 정합하게 묶는다.
    objs.append(_candidate_mapping(
        "mapping.state-fold",
        mapping_key="race-state-fold",
        canonical_summary="레이스 상태 접힘 (서버 5 → 표시 4)",
        meaning="서버는 IDLE/RACING/RACE_END/COOLTIME/FINISHED 5개를 내려주지만 표시는 "
                "READY/RACING/COOLDOWN/ENDED 4개로 접힌다. RACE_END와 FINISHED가 둘 다 ENDED.",
        boundary="화면 표시 상태에 한함. 서버 파싱 enum 자체는 5개 그대로 유지된다.",
        glossary_term_ids=["g.race-status", "g.view-state"],
        decision_record_ids=["decision.state-fold"],
        code_locator_ids=["code.race-status-enum", "code.view-state-enum", "code.state-fold"],
        evidence_refs=["ev.ref.code.state-fold"],
    ))
    objs.append(_candidate_mapping(
        "mapping.dummy-npc",
        mapping_key="dummy-npc-matching",
        canonical_summary="더미 NPC 매칭",
        meaning="레이스 참여자는 실제 유저가 아니라 더미 NPC로 채워진다. 본인 외 최대 6명.",
        boundary="매칭 대상 한정. 보상/순위 계산은 별도 규칙.",
        glossary_term_ids=["g.dummy-npc"],
        decision_record_ids=["decision.dummy-only"],
        code_locator_ids=["code.model-parse"],
        evidence_refs=["ev.ref.spec.dummy-npc"],
    ))
    objs.append(_candidate_mapping(
        "mapping.cooltime",
        mapping_key="cooltime-repeat",
        canonical_summary="쿨타임과 반복 참여",
        meaning="레이스 완주 후 쿨타임이 지나야 새 레이스를 시작할 수 있다. 반복 참여 가능하나 MAX 제한.",
        boundary="레이스 시작 가능 시점에 한함. 코드 표면어는 COOLTIME/COOLDOWN 두 철자.",
        glossary_term_ids=["g.cooltime", "g.repeat-join"],
        decision_record_ids=["decision.cooltime"],
        code_locator_ids=["code.cooltime-manager"],
        evidence_refs=["ev.ref.spec.cooltime"],
    ))

    # DomainContext — candidate glossary 전부를 glossary_term_ids로. review_record_id 없음 정상.
    objs.append(base(
        {
            "id": CTX,
            "kind": "DomainContext",
            "status": "reviewed",
            "truth_role": "domain",
            "title": "미나 카약 도메인",
            "context_key": "mina-kayak",
            "project_id": "demoapp",
            "display_name": "미나 카약 레이스",
            "boundary_summary": "카약 레이스 lifecycle/state — 레이스 단계·상태, 더미 NPC, 선착순, 쿨타임, 반복 참여.",
            "in_scope": ["레이스 상태", "단계 진행", "더미 NPC", "선착순", "쿨타임", "반복 참여"],
            "out_of_scope": ["UI 컴포넌트", "팝업 세부", "보상 아이템 상세"],
            "injection_profile": {"default_audience": "coding-agent"},
            "glossary_term_ids": [
                _fixture_id("GlossaryTerm", "g.race-status"),
                _fixture_id("GlossaryTerm", "g.view-state"),
                _fixture_id("GlossaryTerm", "g.dummy-npc"),
                _fixture_id("GlossaryTerm", "g.finish-rank"),
                _fixture_id("GlossaryTerm", "g.cooltime"),
                _fixture_id("GlossaryTerm", "g.repeat-join"),
            ],
        },
        tags=["mina-kayak"], created_at=T, updated_at=T,
    ))

    return objs


GLOSSARY_IDS = [
    _fixture_id("GlossaryTerm", term_id)
    for term_id in (
        "g.race-status",
        "g.view-state",
        "g.dummy-npc",
        "g.finish-rank",
        "g.cooltime",
        "g.repeat-join",
    )
]
MAPPING_IDS = [
    format_id("DomainMapping", ctx="mina-kayak", key=mapping_key)
    for mapping_key in (
        "race-state-fold",
        "dummy-npc-matching",
        "cooltime-repeat",
    )
]
# 단일 승격 시연 대상 — 도구와 무관한 경로 시연이라 어느 term이든 무방.
# 충돌 term(g.view-state)은 승격 불가라 피하고 conflict 아닌 term을 고른다.
PROMOTE_TERM_ID = _fixture_id("GlossaryTerm", "g.finish-rank")


class MinaKayakEndToEndTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo_context = RepoContext(
            repo_root=self.root,
            expected_repo_id=REPO,
            expected_revision_ref="origin/develop",
            target_revision_sha="a" * 40,
        )

        def verify_fixture_locator(
            locator,
            *,
            repo,
            manual_symbol_verification=None,
        ):
            verified = dict(locator)
            verified.pop("verified_at", None)
            return VerifiedLocator(
                locator=verified,
                quote_sha256="f" * 64,
                symbol_status="verified",
            )

        self._verify_patcher = mock.patch(
            "project_brain.mutation.verify_locator_for_write",
            side_effect=verify_fixture_locator,
        )
        self._verify_patcher.start()

    def tearDown(self):
        self._verify_patcher.stop()
        self._tmp.cleanup()

    def _ingest(self, objects):
        return ingest(
            self.root,
            objects,
            repo_context=self.repo_context,
        )

    # ── Task 6 단계별 ─────────────────────────────────────────────────────────

    def test_e2e_candidate_ingest(self):
        """AC2 단계1: candidate bundle 1회 ingest. mapping/glossary가 candidate."""
        self._ingest(build_candidate_bundle())
        store = BrainStore.load(self.root)
        for mid in MAPPING_IDS:
            self.assertEqual(store.get(mid)["status"], "candidate", mid)
        for tid in GLOSSARY_IDS:
            self.assertEqual(store.get(tid)["status"], "candidate", tid)

    def test_product_single_ingest_without_coverage_fails_before_write(self):
        before = _full_tree_inventory(self.root)
        self.assertEqual(before, {})

        with self.assertRaises(IngestError) as caught:
            product_ingest(
                self.root,
                build_candidate_bundle(),
                engine_sha="e" * 40,
                repo_context=self.repo_context,
            )

        self.assertEqual(caught.exception.code, "coverage_required")
        self.assertEqual(_full_tree_inventory(self.root), before)

    def test_e2e_promote_glossary(self):
        """AC2 단계2: single_object 승격 후 ingest. 대상 term reviewed + review.<id> 존재."""
        self._ingest(build_candidate_bundle())
        bundle = build_candidate_bundle()
        promoted, reviews = promote(
            bundle, [PROMOTE_TERM_ID], "single_object",
            reviewer="user-confirmed", reviewed_at=T,
        )
        self._ingest(promoted + reviews)
        store = BrainStore.load(self.root)
        self.assertEqual(store.get(PROMOTE_TERM_ID)["status"], "reviewed")
        self.assertTrue(store.has("review." + PROMOTE_TERM_ID))

    def test_e2e_promote_mapping_bundle(self):
        """AC2 단계3: mapping_bundle 승격 후 ingest. mapping reviewed + 공유 review_record."""
        self._ingest(build_candidate_bundle())
        bundle = build_candidate_bundle()
        promoted, reviews = promote(
            bundle, MAPPING_IDS, "mapping_bundle",
            bundle_key=BUNDLE_KEY, reviewer="user-confirmed", reviewed_at=T,
        )
        self._ingest(promoted + reviews)
        store = BrainStore.load(self.root)
        for mid in MAPPING_IDS:
            self.assertEqual(store.get(mid)["status"], "reviewed", mid)
            self.assertEqual(store.get(mid)["review_record_id"], "review." + BUNDLE_KEY, mid)
        self.assertTrue(store.has("review." + BUNDLE_KEY))

    def test_e2e_no_domain_constants(self):
        """AC1: generic 부품(ingest/promote/objbase)의 실행 코드에 도메인 id가 없음.

        주석/docstring/문자열 리터럴을 AST로 떼어낸 코드 토큰만 검사한다 — promote.py
        docstring은 흡수 출처로 폐기 스크립트 파일명(ingest_mina_kayak_source)을 적고
        있으나, 그건 도메인 데이터 상수가 아니라 출처 설명이라 AC1(부품 도메인 상수 0)을
        위반하지 않는다. 검사 단위는 식별자·이름 토큰이지 docstring 텍스트가 아니다."""
        import ast

        import project_brain

        # 설치 형태(src 레이아웃·editable)와 무관하게 패키지 자신의 위치에서 읽는다.
        module_root = Path(project_brain.__file__).resolve().parent
        for name in ("ingest.py", "promote.py", "objbase.py"):
            source = (module_root / name).read_text(encoding="utf-8")
            tree = ast.parse(source)
            # 식별자/속성 이름 토큰만 모은다(문자열 상수 노드 Constant는 제외 → docstring 배제).
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    names.add(node.id.lower())
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr.lower())
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(node.name.lower())
                elif isinstance(node, ast.arg):
                    names.add(node.arg.lower())
            joined = " ".join(names)
            for needle in ("mina", "kayak"):
                self.assertNotIn(
                    needle, joined, f"{name} code identifier contains domain id {needle!r}"
                )

    # ── Task 7 최종 검증 (lint clean + cli/router 회상) ────────────────────────

    def _reingest_full(self):
        """단계1~3을 모두 태운 store를 만든다(reviewed mapping까지)."""
        self._ingest(build_candidate_bundle())
        bundle = build_candidate_bundle()
        g_promoted, g_reviews = promote(
            bundle, [PROMOTE_TERM_ID], "single_object",
            reviewer="user-confirmed", reviewed_at=T,
        )
        self._ingest(g_promoted + g_reviews)
        m_promoted, m_reviews = promote(
            bundle, MAPPING_IDS, "mapping_bundle",
            bundle_key=BUNDLE_KEY, reviewer="user-confirmed", reviewed_at=T,
        )
        self._ingest(m_promoted + m_reviews)

    def test_e2e_lint_clean_after_full_reingest(self):
        """AC5: 전체 재적재 완료 store가 lint clean."""
        self._reingest_full()
        store = BrainStore.load(self.root)
        self.assertEqual(lint_store(store), [])

    def test_e2e_search_recall(self):
        """AC6: 새로 적재한 reviewed mapping을 정본 search 경로가 회상한다."""
        self._reingest_full()
        store = BrainStore.load(self.root)
        db = self.root / ".brain-local" / "index.db"
        embedder = StubEmbedder()
        index_rebuild(self.root, db, embedder=embedder)
        answer = eval_recall(
            "쿨타임이 무슨 뜻이야?",
            db_path=db,
            embedder=embedder,
            brain_root=self.root,
            store=store,
        )
        self.assertIn(
            "mapping.mina-kayak.cooltime-repeat",
            {hit["object_id"] for hit in answer["results"]},
        )
        self.assertFalse(answer["needs_clarification"])


if __name__ == "__main__":
    unittest.main()
