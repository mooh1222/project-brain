import re
from collections import defaultdict
from pathlib import Path

from project_brain.intent import classify_query
from project_brain.status import answer_status, claim_status
from project_brain.store import BrainStore

_SCOPE_TOKEN_RE = re.compile(r"[0-9A-Za-z._-]+")


def _conflicting_fact_groups(facts: list[dict]) -> list[list[dict]]:
    """store 비의존 순수 함수. open(valid_until 없음) + reviewed fact 중
    같은 (subject, predicate)인데 value가 2종 이상 갈리는 묶음만 반환한다.
    scope·supersedes는 보지 않는다(해소 단계가 처리). 런타임(⑤)과 Lint(3a)가 공유."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for fact in facts:
        if fact.get("status") != "reviewed" or fact.get("valid_until"):
            continue
        subject, predicate = fact.get("subject"), fact.get("predicate")
        if subject is None or predicate is None:
            continue
        groups[(subject, predicate)].append(fact)
    result = []
    for members in groups.values():
        values = {repr(m.get("value")) for m in members}
        if len(members) >= 2 and len(values) >= 2:
            result.append(members)
    return result


class QueryRouter:
    def __init__(
        self,
        store: BrainStore,
        *,
        current_head: str | None = None,
        missing_raw_manifest_ids: set[str] | None = None,
        db_path=None,
        embedder=None,
        brain_root=None,
        stale_advisories=None,
    ):
        self.store = store
        self.current_head = current_head
        # CLI가 .brain-local/stale-set.json을 읽어 만든 매핑id→advisory dict(Step 2).
        # router는 파일·git을 모르고 주입된 dict만 소비한다(git_runner/current_head와 같은 패턴).
        self.stale_advisories = stale_advisories or {}
        self.missing_raw_manifest_ids = missing_raw_manifest_ids or set()
        # 의미 회상(§7) 입력. db_path가 None이거나 색인 DB가 없으면 recall을 끄고
        # ★정확 매칭 경로만으로★ 동작한다(안전 폴백) — 색인 없는 tmp store로 도는
        # 기존 테스트들이 green을 유지하는 열쇠다. recall은 색인 DB가 있을 때만 켠다.
        self.db_path = Path(db_path) if db_path is not None else None
        self.embedder = embedder
        self.brain_root = Path(brain_root) if brain_root is not None else None
        self._recall_cache: dict[str, dict | None] = {}

    def _recall(self, query: str) -> dict | None:
        """질의를 의미 회상층에 태워 게이트 적용 결과를 돌려준다(§7).

        반환: search.eval_recall의 dict({results, candidates, needs_clarification}) —
        results는 게이트 통과 reviewed 적중, candidates는 게이트 통과 candidate 적중.
        ★색인 DB가 없으면 None★(recall 비활성 = 안전 폴백). 같은 query는 answer()
        한 호출 안에서 여러 intent가 부를 수 있으니 1회만 계산해 캐시한다.
        self.store를 주입해 질의마다 코퍼스를 다시 읽지 않는다(후속 b) — 생성자에
        준 store와 brain_root가 같은 코퍼스라는 전제(다르면 호출자 구성 오류).
        """
        if self.db_path is None or not self.db_path.exists():
            return None
        if query in self._recall_cache:
            return self._recall_cache[query]
        from project_brain.search import eval_recall
        result = eval_recall(
            query, db_path=self.db_path, embedder=self.embedder, brain_root=self.brain_root,
            store=self.store,
        )
        self._recall_cache[query] = result
        return result

    def answer(self, query: str) -> dict:
        avoid_map = self._avoid_corrections()
        classified = classify_query(query, avoid_map)
        # 라우팅·매칭은 정규화된 canonical로 한다 (시작팝업→입장팝업 등 도메인 용어 보정 반영). 원본 query는 출력 echo에만 사용.
        canonical = classified.normalized.canonical_query
        candidate_ids: list[str] = []
        promotable_ids: list[str] = []
        source_ids: list[str] = []
        sections: list[dict] = []
        claim_statuses: list[str] = []
        warnings: list[str] = []
        clarification_needed = False

        # §4 rule 3: 회피 용어가 canonical로 보정된 경우 warnings에 공시
        if classified.normalized.avoided_terms:
            corrected = ", ".join(sorted(set(classified.normalized.avoided_terms)))
            warnings.append(f"용어 보정 적용: {corrected} → canonical 질의로 라우팅")

        for intent in classified.intents:
            if intent == "why_changed":
                # §6.2: 변경 이력은 단일 event가 아니라 happened_at 순 복수 event다.
                # G4: spec_revised(기획 원문)/spec_clarified(슬랙)를 event_type 인라인으로 분리.
                # G6: (1) event에서 파생된 TemporalFact의 supersedes 사슬로 before→after(L145),
                #     (2) qa_result는 후속 변경을 유발했을 때만 원인(L154),
                #     (3) 원인이 복수 event 추론이면 causal_basis=inferred로 라벨(L153).
                events = sorted(
                    self._reviewed_by_kind("EventLedgerRecord"),
                    key=lambda e: e.get("happened_at", ""),
                )
                if events:
                    happened = {e["id"]: e.get("happened_at", "") for e in events}
                    event_ids = set(happened)
                    derived = sorted(
                        self._facts_derived_from(event_ids),
                        key=lambda f: (happened[f["derived_from_event_id"]], f["id"]),
                    )
                    deriving_event_ids = {f["derived_from_event_id"] for f in derived}
                    event_details = []
                    for event in events:
                        source_ids.append(event["id"])
                        claim_statuses.append(claim_status(event, raw_available=self._raw_available_for(event), restricted=False))
                        event_details.append({
                            "id": event["id"],
                            "event_type": event.get("event_type"),
                            "summary": event.get("summary", ""),
                            "role": self._event_role(event, deriving_event_ids),
                        })
                    fact_changes = []
                    for fact in derived:
                        source_ids.append(fact["id"])
                        claim_statuses.append(claim_status(fact, raw_available=self._raw_available_for(fact), restricted=False))
                        reached = self._supersedes_reachable(fact)
                        before_value = self.store.get(reached[0]).get("value") if reached else None
                        fact_changes.append({
                            "fact_id": fact["id"],
                            "subject": fact.get("subject"),
                            "predicate": fact.get("predicate"),
                            "before_value": before_value,
                            "after_value": fact.get("value"),
                            "derived_from_event_id": fact["derived_from_event_id"],
                        })
                    # 변경이 event에서 직접 파생됐으면(deriving event가 하나라도 있으면) 원인이
                    # 직접 명시된 것 = stated. 파생 fact가 하나도 없고 event가 복수면, 원인을
                    # event 나열에서 읽어 추론한 것 = inferred(L153). event 1개면 그 event가 직접 명시.
                    causal_basis = "inferred" if (not deriving_event_ids and len(events) >= 2) else "stated"
                    if causal_basis == "inferred":
                        warnings.append("원인이 단일 event로 직접 명시되지 않음 — 복수 event에서 추론(inference)")
                    for ev in event_details:
                        if ev["event_type"] == "qa_result" and ev["role"] == "supporting_context":
                            warnings.append(f"{ev['id']}: qa_result는 후속 변경을 직접 유발하지 않아 보조 맥락(원인 아님)")
                    sections.append({
                        "intent": intent,
                        "object_ids": [e["id"] for e in events],
                        "events": event_details,
                        "fact_changes": fact_changes,
                        "causal_basis": causal_basis,
                        "summary": "Change rationale (chronological)",
                    })
                # DecisionRecord(lifecycle §8.3): 질의에 매칭된 용어/매핑을 affected_*로 가리키는
                # reviewed 결정을 surface한다. 매처로 좁히므로 전량 반환이 아니다(질의 무관 결정 제외).
                # EventLedger가 0개여도 동작 — "왜 바뀌었나"의 결정 모델을 스펙대로 읽는다.
                matched_decision_anchors = (
                    {t["id"] for t in self._matched_glossary_terms(canonical)}
                    | {t["id"] for t in self._matched_candidate_terms(canonical)}
                    | {m["id"] for m in self._matched_mappings(canonical)}
                )
                decisions = [
                    d for d in self._reviewed_by_kind("DecisionRecord")
                    if matched_decision_anchors & (
                        set(d.get("affected_glossary_term_ids") or [])
                        | set(d.get("affected_mapping_ids") or [])
                    )
                ]
                if decisions:
                    decision_details = []
                    for decision in decisions:
                        source_ids.append(decision["id"])
                        claim_statuses.append(claim_status(
                            decision,
                            raw_available=self._raw_available_for(decision),
                            restricted=self._restricted_for(decision),
                        ))
                        decision_details.append({
                            "id": decision["id"],
                            "decision_type": decision.get("decision_type"),
                            "summary": decision.get("summary", ""),
                            "decision": decision.get("decision", ""),
                            "spec_reflected": decision.get("spec_reflected"),
                        })
                    sections.append({
                        "intent": intent,
                        "object_ids": [d["id"] for d in decisions],
                        "decisions": decision_details,
                        "summary": "Change decisions (scoped to matched terms/mappings)",
                    })
            elif intent == "current_status":
                facts = self._current_facts(canonical)
                kept, conflict_entries, any_unresolved = self._resolve_current_conflicts(facts)
                ambiguous = self._release_ambiguous(kept, canonical)
                if ambiguous:
                    clarification_needed = True
                    warnings.append(f"release 모호: {', '.join(sorted(ambiguous))} 중 지정 필요")
                if any_unresolved:
                    clarification_needed = True
                for entry in conflict_entries:
                    ids = ", ".join(entry["fact_ids"])
                    vals = ", ".join(entry["values"])
                    warnings.append(f"충돌 reviewed fact: {ids} ({entry['predicate']} 값 상이: {vals})")
                all_views = self._reviewed_by_kind("CurrentView")
                warnings.extend(self._stale_view_warnings(all_views))
                warnings.extend(self._glossary_scope_disclosures(canonical))
                relevant_views = self._views_for_current_facts(all_views, kept)
                candidate_ids.extend(view["id"] for view in relevant_views)
                for fact in kept:
                    source_ids.append(fact["id"])
                    claim_statuses.append(claim_status(fact, raw_available=self._raw_available_for(fact), restricted=False))
                sections.append({"intent": intent, "object_ids": [fact["id"] for fact in kept], "conflicts": conflict_entries, "summary": "Current reviewed facts"})
            elif intent == "as_of_history":
                facts = self._scoped_facts(canonical)
                ambiguous = self._release_ambiguous(facts, canonical)
                if ambiguous:
                    clarification_needed = True
                    warnings.append(f"release 모호: {', '.join(sorted(ambiguous))} 중 지정 필요")
                warnings.extend(self._glossary_scope_disclosures(canonical))
                for fact in facts:
                    source_ids.append(fact["id"])
                    claim_statuses.append(claim_status(fact, raw_available=self._raw_available_for(fact), restricted=False))
                sections.append({"intent": intent, "object_ids": [fact["id"] for fact in facts], "summary": "As-of historical facts"})
            elif intent == "implementation_location":
                # §7 전량 적재 → top-K 전이: 색인이 있으면 recall 점수 top-K로 좁히고
                # (06-05 "110개 무더기" 원인 제거), 없으면 기존 전량 적재로 폴백한다.
                locators = self._implementation_locators(canonical)
                for locator in locators:
                    source_ids.append(locator["id"])
                    # CodeLocator도 다른 intent와 동일하게 claim_status 경유 → restricted/raw-unavailable 산출.
                    status = claim_status(
                        locator,
                        raw_available=self._raw_available_for(locator),
                        restricted=self._restricted_for(locator),
                    )
                    # commit_sha 드리프트(없음/HEAD 불일치)는 §8 precedence로 candidate 합성.
                    # max-severity라 reviewed는 candidate로 강등되지만 restricted/raw-unavailable는 유지된다.
                    commit_sha = locator.get("commit_sha")
                    if commit_sha is None:
                        status = answer_status([status, "candidate"])
                        warnings.append(f"{locator['id']}: commit_sha 없음, 라인 번호 드리프트 가능")
                    elif self.current_head is not None and commit_sha != self.current_head:
                        status = answer_status([status, "candidate"])
                        warnings.append(f"{locator['id']}: locator commit {commit_sha}가 현재 HEAD와 달라 현재 라인 정확도 미검증")
                    claim_statuses.append(status)
                # 후보 채널(2026-06-11 사용자 결정): candidate locator는 침묵 드롭 대신
                # "확인 필요" 라벨로 노출 — glossary candidate_terms(C 정책)와 같은 모양.
                # source_ids에는 안 넣어 needs_clarification 식(§4.3)을 보존한다.
                candidate_locator_details = []
                for locator in self._implementation_candidate_locators(canonical):
                    promotable_ids.append(locator["id"])
                    claim_statuses.append(claim_status(locator, raw_available=self._raw_available_for(locator), restricted=self._restricted_for(locator)))
                    candidate_locator_details.append({
                        "id": locator["id"],
                        "path": locator.get("path"),
                        "symbol": locator.get("symbol"),
                        "trust_label": "확인 필요",
                    })
                if candidate_locator_details:
                    warnings.append("확인 필요한 후보 항목 포함 — 사용 시점에 확정(promote) 가능")
                sections.append({"intent": intent, "object_ids": [locator["id"] for locator in locators], "candidate_locators": candidate_locator_details, "summary": "Code locators"})
            elif intent == "glossary_meaning":
                # spec §7: "내가 이 용어 말하면 무슨 뜻?" → reviewed DomainMapping 우선, GlossaryTerm은 alias.
                matched_mappings = self._matched_mappings(canonical)
                section_ids: list[str] = []
                mapping_details = []
                for mapping in matched_mappings:
                    source_ids.append(mapping["id"])
                    section_ids.append(mapping["id"])
                    claim_statuses.append(claim_status(mapping, raw_available=self._raw_available_for(mapping), restricted=self._restricted_for(mapping)))
                    detail = {
                        "id": mapping["id"],
                        "mapping_key": mapping.get("mapping_key"),
                        "meaning": mapping.get("meaning", ""),
                        "boundary": mapping.get("boundary", ""),
                        "caveats": mapping.get("caveats") or [],
                        "code_locator_ids": mapping.get("code_locator_ids") or [],
                    }
                    adv = self.stale_advisories.get(mapping["id"])
                    if adv:
                        detail["stale_advisory"] = adv
                    mapping_details.append(detail)
                # §7 전량 적재 → top-K 전이: 색인이 있으면 recall 점수 top-K로 좁히고,
                # 없으면 기존 전량 적재(DomainContext + GlossaryTerm)로 폴백한다. 정확
                # 매칭이 이미 잡은 매핑(section_ids)은 의미 확장에서 중복 적재하지 않는다.
                glossary_objects = self._glossary_meaning_objects(canonical, exclude=set(section_ids))
                for obj in glossary_objects:
                    source_ids.append(obj["id"])
                    section_ids.append(obj["id"])
                    claim_statuses.append(claim_status(obj, raw_available=self._raw_available_for(obj), restricted=False))
                # C (spec §4.2): candidate GlossaryTerm 정의를 "확인 필요" 라벨로 노출.
                # source_ids에 넣지 않아 needs_clarification 식(§4.3)을 보존하고,
                # 별도 수집기(매칭만)라 충돌·scope 추론 입력에는 들어가지 않는다.
                candidate_details = []
                for term in self._matched_candidate_terms(canonical):
                    promotable_ids.append(term["id"])
                    claim_statuses.append(claim_status(term, raw_available=self._raw_available_for(term), restricted=self._restricted_for(term)))
                    candidate_details.append({
                        "id": term["id"],
                        "term": term.get("term"),
                        "definition": term.get("definition", ""),
                        "trust_label": "확인 필요",
                    })
                if candidate_details:
                    warnings.append("확인 필요한 후보 항목 포함 — 사용 시점에 확정(promote) 가능")
                    # spec §4.3: 후보만 노출되고 매칭된 검수 답(matched_mappings)이 없으면 사람 확인 유도.
                    # (not source_ids)에 기대지 않는다 — reviewed DomainContext가 매칭 무관하게
                    # source_ids에 무조건 들어가(router.py:191-195) 실코퍼스에서도 source_ids는 안 빈다.
                    if not matched_mappings:
                        clarification_needed = True
                if any("stale_advisory" in m for m in mapping_details):
                    warnings.append("코드 변경 감지된 매핑 포함 — stale-check 기준 시점 확인 필요")
                summary = "Glossary definition (reviewed mappings prioritized)" if matched_mappings else "Glossary definition"
                # 검수/후보 구분은 키로: object_ids·mappings = 검수됨, candidate_terms = 후보(각 trust_label).
                sections.append({
                    "intent": intent,
                    "object_ids": section_ids,
                    "mappings": mapping_details,
                    "candidate_terms": candidate_details,
                    "summary": summary,
                })
            elif intent == "evidence_provenance":
                # 정밀 규칙(§6.6): 함께 분류된 의도가 가리키는 source object의 출처 사슬만 defend.
                # 각 의도 collector를 재사용해 재수집하므로 루프 순서와 무관하다.
                # 단독 evidence(다른 의도 없음)는 scope 매칭 사실로 fallback(기존 동작 보존).
                intents_present = set(classified.intents)
                sources: list[dict] = []
                if "why_changed" in intents_present:
                    # EventLedgerRecord는 색인 제외 kind라 recall로 못 좁힌다 — 전량 유지.
                    sources.extend(self._reviewed_by_kind("EventLedgerRecord"))
                if "implementation_location" in intents_present:
                    # §7 전량 → top-K: 동반 의도 section과 같은 공급원을 재사용한다
                    # (색인 없으면 헬퍼 내부에서 전량 폴백).
                    sources.extend(self._implementation_locators(canonical))
                if "glossary_meaning" in intents_present:
                    sources.extend(self._glossary_meaning_objects(canonical, exclude=set()))
                if "current_status" in intents_present:
                    sources.extend(self._current_facts(canonical))
                if "as_of_history" in intents_present:
                    sources.extend(self._scoped_facts(canonical))
                if intents_present == {"evidence_provenance"}:
                    sources = self._scoped_facts(canonical)
                section_ids: list[str] = []
                seen: set[str] = set()
                for obj in sources:
                    if obj["id"] in seen:
                        continue
                    seen.add(obj["id"])
                    section_ids.append(obj["id"])
                    review_id = obj.get("review_record_id")
                    if review_id and self.store.has(review_id):
                        section_ids.append(review_id)
                    for ref_id in obj.get("evidence_refs", []):
                        if self.store.has(ref_id):
                            section_ids.append(ref_id)
                    claim_statuses.append(claim_status(obj, raw_available=self._raw_available_for(obj), restricted=self._restricted_for(obj)))
                source_ids.extend(section_ids)
                sections.append({"intent": intent, "object_ids": section_ids, "summary": "Evidence provenance"})
            elif intent == "unknown":
                # §7 일반 회상: 맥락만 던진 질의("project-brain은 너가 사용해서 알려주는거야",
                # 06-09)를 의미 회상으로 답한다. 게이트 통과 reviewed=확신(source_ids),
                # candidate=후보(promotable_ids + "확인 필요" 라벨, 기존 C 정책 계승).
                # 색인이 없으면 recall=None → 기존 "No matching intent"로 폴백한다.
                recalled = self._recall(canonical)
                if recalled is None:
                    sections.append({"intent": intent, "object_ids": [], "summary": "No matching intent"})
                else:
                    object_ids: list[str] = []
                    candidate_details = []
                    for hit in recalled["results"]:
                        oid = hit["object_id"]
                        if not self.store.has(oid):
                            continue
                        obj = self.store.get(oid)
                        source_ids.append(oid)
                        object_ids.append(oid)
                        claim_statuses.append(claim_status(
                            obj, raw_available=self._raw_available_for(obj),
                            restricted=self._restricted_for(obj)))
                    for hit in recalled["candidates"]:
                        oid = hit["object_id"]
                        if not self.store.has(oid):
                            continue
                        obj = self.store.get(oid)
                        promotable_ids.append(oid)
                        claim_statuses.append(claim_status(
                            obj, raw_available=self._raw_available_for(obj),
                            restricted=self._restricted_for(obj)))
                        candidate_details.append({
                            "id": oid,
                            "kind": obj.get("kind"),
                            "surface": hit.get("surface", ""),
                            "trust_label": "확인 필요",
                        })
                    if candidate_details:
                        warnings.append("확인 필요한 후보 항목 포함 — 사용 시점에 확정(promote) 가능")
                    # "no evidence → 없다"(§7): 게이트 통과 reviewed 0건이면 확신 답 없음.
                    # source_ids로 흘러가 최종 needs_clarification 식이 처리하지만, 후보만
                    # 있고 reviewed가 없는 경우(source_ids 안 참)도 확인 유도를 명시한다.
                    if not object_ids:
                        clarification_needed = True
                    sections.append({
                        "intent": intent,
                        "object_ids": object_ids,
                        "candidate_terms": candidate_details,
                        "summary": "Semantic recall (reviewed prioritized)"
                                   if object_ids else "Semantic recall",
                    })

        # advisories(spec 2026-06-15 §4.6): reviewed Insight를 별도 통로로 곁들인다.
        # recall이 켜졌을 때만(색인 있음) 채워지고, 없으면 빈 리스트. needs_clarification에는
        # 영향 주지 않는다(곁들임 — eval_recall이 advisories를 needs_clarification 식에서 제외).
        advisories: list[dict] = []
        recalled = self._recall(canonical)
        if recalled is not None:
            for hit in recalled.get("advisories", []):
                oid = hit["object_id"]
                if not self.store.has(oid):
                    continue
                obj = self.store.get(oid)
                advisories.append({
                    "id": oid,
                    "insight_type": obj.get("insight_type"),
                    "surface": hit.get("surface", ""),
                    "code_locators": hit.get("linked", {}).get("code_locators", []),
                    # Insight 정체성("가로지름")은 source_object_ids 자체 — 공용 _build_linked가
                    # 안 따라가는 필드라 여기서 직접 노출한다(critic 검토 4).
                    "source_object_ids": obj.get("source_object_ids", []),
                })

        return {
            "query": query,
            "canonical_query": classified.normalized.canonical_query,
            "intents": classified.intents,
            "status": answer_status(claim_statuses),
            "candidate_object_ids": sorted(set(candidate_ids)),
            "promotable_candidate_ids": sorted(set(promotable_ids)),
            "source_object_ids": sorted(set(source_ids)),
            "sections": sections,
            "advisories": advisories,
            "warnings": warnings,
            "needs_clarification": (not source_ids) or clarification_needed,
        }

    def _reviewed_by_kind(self, kind: str) -> list[dict]:
        return [obj for obj in self.store.by_kind(kind) if obj.get("status") == "reviewed"]

    def _recalled_objects_of_kind(self, query: str, kinds: set[str]) -> list[dict] | None:
        """recall 게이트 통과 reviewed 적중 중 지정 kind인 store 객체를 회상 순서로
        돌려준다(§7 top-K). 색인이 없으면 None(호출처가 전량 적재로 폴백). eval_recall
        results는 이미 채널·게이트·top-K(5)를 통과한 reviewed 적중이다."""
        recalled = self._recall(query)
        if recalled is None:
            return None
        objs = []
        seen: set[str] = set()
        for hit in recalled["results"]:
            oid = hit["object_id"]
            if oid in seen or not self.store.has(oid):
                continue
            obj = self.store.get(oid)
            if obj.get("kind") in kinds:
                seen.add(oid)
                objs.append(obj)
        return objs

    def _implementation_locators(self, query: str) -> list[dict]:
        """implementation_location source가 적재할 CodeLocator(§7 전량→top-K).

        ★색인이 없으면★ 기존 reviewed CodeLocator 전량으로 폴백한다(색인 없는 tmp store
        테스트 보존). 색인이 있으면 06-05 "110개 무더기"를 제거하고 recall top-K로 좁히되,
        ★핀포인트는 두 경로로 모은다★(§3.5·§8 "매핑 적중 → code_locator 동반"):
          (1) recall 적중이 CodeLocator 자체인 경우(심볼 직접 적중),
          (2) recall 적중 매핑 등이 linked.code_locators로 동반한 CodeLocator(그래프 1-hop).
        둘을 회상 순서로 dedup해 모은다 — 코드 위치 답은 (2)가 주 경로다(매핑이 점수
        상위라 (1) 단독이면 0건이 흔하다, 실코퍼스 실측)."""
        recalled = self._recall(query)
        if recalled is None:
            return self._reviewed_by_kind("CodeLocator")
        locators: list[dict] = []
        seen: set[str] = set()
        for hit in recalled["results"]:
            oid = hit["object_id"]
            # (1) 적중이 CodeLocator 자체.
            if self.store.has(oid) and self.store.get(oid).get("kind") == "CodeLocator":
                if oid not in seen:
                    seen.add(oid)
                    locators.append(self.store.get(oid))
            # (2) 적중이 linked.code_locators로 동반한 CodeLocator(그래프 1-hop 핀포인트).
            for c in hit.get("linked", {}).get("code_locators", []):
                cid = c.get("object_id")
                if not cid or cid in seen or not self.store.has(cid):
                    continue
                locator = self.store.get(cid)
                # 확신 채널(source) 규약(§7): 폴백 경로(_reviewed_by_kind)와 같게
                # reviewed만 적재 — reviewed 매핑이 candidate locator를 참조하는 잠재
                # 케이스에서 미검수가 source로 새는 비대칭을 막는다(2026-06-10 리뷰,
                # 현 실코퍼스는 CodeLocator 110/110 reviewed라 잠재 가드).
                if locator.get("status") != "reviewed":
                    continue
                seen.add(cid)
                locators.append(locator)
        return locators

    def _implementation_candidate_locators(self, query: str) -> list[dict]:
        """구현위치 섹션의 후보 채널(2026-06-11 사용자 결정 — C 정책 적용).

        reviewed-only 가드(_implementation_locators)가 침묵 드롭하던 candidate
        CodeLocator를 "확인 필요" 라벨 노출용으로 모은다 — (1) 후보 채널 직접 적중,
        (2) 적중(확신·후보)이 linked.code_locators로 동반한 candidate. 확신 채널과
        겹칠 일은 없다(같은 객체가 reviewed이면서 candidate일 수 없음). 색인이
        없으면 빈 리스트 — 폴백 경로는 기존 확신 채널 전량 그대로 둔다."""
        recalled = self._recall(query)
        if recalled is None:
            return []
        out: list[dict] = []
        seen: set[str] = set()
        for hit in recalled["results"] + recalled["candidates"]:
            oid = hit["object_id"]
            if oid not in seen and self.store.has(oid):
                obj = self.store.get(oid)
                if obj.get("kind") == "CodeLocator" and obj.get("status") == "candidate":
                    seen.add(oid)
                    out.append(obj)
            for c in hit.get("linked", {}).get("code_locators", []):
                cid = c.get("object_id")
                if not cid or cid in seen or not self.store.has(cid):
                    continue
                locator = self.store.get(cid)
                if locator.get("status") == "candidate":
                    seen.add(cid)
                    out.append(locator)
        return out

    def _glossary_meaning_objects(self, query: str, exclude: set[str]) -> list[dict]:
        """glossary_meaning source가 적재할 DomainContext/GlossaryTerm(§7 전량→top-K).

        색인이 있으면 recall top-K 중 DomainContext/GlossaryTerm만, 없으면 기존
        전량(DomainContext + reviewed GlossaryTerm)으로 폴백한다. 정확 매칭 매핑과의
        중복은 kind 필터가 구조적으로 막고(두 공급원 다 매핑을 못 돌려줌), exclude는
        그 보증이 바뀔 때를 위한 방어선이다(2026-06-10 리뷰 — 서술 정정)."""
        recalled = self._recalled_objects_of_kind(query, {"DomainContext", "GlossaryTerm"})
        if recalled is None:
            recalled = self._reviewed_by_kind("DomainContext") + self._reviewed_by_kind("GlossaryTerm")
        return [obj for obj in recalled if obj["id"] not in exclude]

    def _facts_derived_from(self, event_ids: set[str]) -> list[dict]:
        """주어진 event들에서 파생된 reviewed TemporalFact. fact는 derived_from_event_id로
        자신을 만든 event를 가리킨다(object-model §6.5). 미검수 fact·다른 event 파생 fact는 제외."""
        return [
            fact for fact in self._reviewed_by_kind("TemporalFact")
            if fact.get("derived_from_event_id") in event_ids
        ]

    def _event_role(self, event: dict, deriving_event_ids: set[str]) -> str:
        """qa_result는 reviewed fact를 파생(후속 규칙/구현 변경을 유발)했을 때만 'cause',
        아니면 'supporting_context'(§6.2 L154). 그 외 event_type은 §6.2 읽기순서상
        rationale 자체이므로 'cause'."""
        if event.get("event_type") == "qa_result":
            return "cause" if event["id"] in deriving_event_ids else "supporting_context"
        return "cause"

    def _avoid_corrections(self) -> dict[str, str]:
        """reviewed GlossaryTerm의 avoid 목록을 {회피용어: canonical term} 보정 map으로 모은다."""
        corrections: dict[str, str] = {}
        for term in self._reviewed_by_kind("GlossaryTerm"):
            canonical = term.get("term")
            if not canonical:
                continue
            for avoided in term.get("avoid") or []:
                corrections[avoided] = canonical
        return corrections

    _SCOPE_DIMENSIONS = ("release", "feature", "surface", "platform", "module")
    _SCOPE_HINT_DIMENSIONS = ("feature", "surface")

    def _matched_glossary_terms(self, query: str) -> list[dict]:
        matched = [
            term for term in self._reviewed_by_kind("GlossaryTerm")
            if term.get("term") and term["term"] in query
        ]
        result = []
        for term in matched:
            text = term["term"]
            # 더 긴 매칭 term에 부분문자열로 포함되는 짧은 term은 드롭 (예: "팝업" ⊂ "입장팝업")
            contained = any(
                other is not term and len(other["term"]) > len(text) and text in other["term"]
                for other in matched
            )
            if not contained:
                result.append(term)
        return result

    def _matched_candidate_terms(self, query: str) -> list[dict]:
        """query 텍스트에 term/synonyms/aliases가 등장하는 candidate GlossaryTerm.
        노출 전용(spec §4.2) — 충돌 해소·scope 추론 입력에는 절대 넣지 않는다.
        검수된 GlossaryTerm은 제외(이미 _reviewed_by_kind 경로로 노출됨)."""
        result = []
        for term in self.store.by_kind("GlossaryTerm"):
            if term.get("status") != "candidate":
                continue
            surfaces = {term.get("term")}
            surfaces.update(term.get("synonyms") or [])
            surfaces.update(term.get("aliases") or [])
            if any(surface and surface in query for surface in surfaces):
                result.append(term)
        return result

    def _matched_mappings(self, query: str) -> list[dict]:
        """query에 등장하는 용어 텍스트로 reviewed DomainMapping을 찾는다.
        매핑이 검수 단위이므로, 참조하는 GlossaryTerm이 candidate여도 그 term/synonym 텍스트를
        매핑의 언어 표면(language surface)으로 써서 매칭한다 (spec §3.3/§9). 답변 내용은 후보 용어
        정의가 아니라 reviewed 매핑에서 나오므로 candidate 정의가 노출되지는 않는다."""
        result = []
        for mapping in self._reviewed_by_kind("DomainMapping"):
            surfaces: set[str] = set()
            for term_id in mapping.get("glossary_term_ids", []):
                if not self.store.has(term_id):
                    continue
                term = self.store.get(term_id)
                if term.get("term"):
                    surfaces.add(term["term"])
                for synonym in term.get("synonyms") or []:
                    surfaces.add(synonym)
            if any(surface and surface in query for surface in surfaces):
                result.append(mapping)
        return result

    def _glossary_scope_disclosures(self, query: str) -> list[str]:
        """glossary 용어 유래 scope 추론이 실제로 다른 팩트를 걸러냈을 때만 경고를 반환한다."""
        messages: list[str] = []
        all_facts = self._reviewed_by_kind("TemporalFact")
        for term in self._matched_glossary_terms(query):
            hint = term.get("scope_hint", {})
            for dim in self._SCOPE_HINT_DIMENSIONS:
                value = hint.get(dim)
                if not value:
                    continue
                # 해당 dim에 다른 non-null 값을 가진 팩트가 존재할 때만 공시
                if any(f.get("scope", {}).get(dim) not in (None, value) for f in all_facts):
                    messages.append(f"용어 '{term['term']}'에서 scope 추론 → {dim}={value}")
        return messages

    def _query_scope_filters(self, query: str) -> dict[str, set[str]]:
        tokens = set(_SCOPE_TOKEN_RE.findall(query))
        filters: dict[str, set[str]] = {}
        for fact in self._reviewed_by_kind("TemporalFact"):
            scope = fact.get("scope", {})
            for dim in self._SCOPE_DIMENSIONS:
                value = scope.get(dim)
                if value and value in tokens:
                    filters.setdefault(dim, set()).add(value)
        for term in self._matched_glossary_terms(query):
            hint = term.get("scope_hint", {})
            for dim in self._SCOPE_HINT_DIMENSIONS:
                value = hint.get(dim)
                if value:
                    filters.setdefault(dim, set()).add(value)
        return filters

    def _scoped_facts(self, query: str) -> list[dict]:
        facts = self._reviewed_by_kind("TemporalFact")
        for dim, values in self._query_scope_filters(query).items():
            facts = [fact for fact in facts if fact.get("scope", {}).get(dim) in values]
        return facts

    def _release_ambiguous(self, facts: list[dict], query: str) -> set[str]:
        if "release" in self._query_scope_filters(query):
            return set()
        releases = {fact.get("scope", {}).get("release") for fact in facts}
        releases.discard(None)
        return releases if len(releases) > 1 else set()

    def _supersedes_reachable(self, fact: dict) -> list[str]:
        """fact가 supersedes 스칼라 사슬로 도달하는 id 목록. cycle/missing-id 가드."""
        reached, visited, current = [], set(), fact
        while True:
            sid = current.get("supersedes")            # 스칼라(결정 4)
            if not sid or sid in visited or not self.store.has(sid):
                break
            visited.add(sid)
            reached.append(sid)
            current = self.store.get(sid)
        return reached

    def _supersedes_winner(self, group: list[dict]) -> dict | None:
        """(A) 그룹 안에서 supersedes 사슬로 다른 fact를 대체해 유일하게 남는 fact. 없으면 None."""
        ids_in_group = {f["id"] for f in group}
        dominated = set()
        for fact in group:
            for reached in self._supersedes_reachable(fact):
                if reached in ids_in_group:
                    dominated.add(reached)
        survivors = [f for f in group if f["id"] not in dominated]
        return survivors[0] if len(survivors) == 1 else None

    def _resolve_current_conflicts(self, facts: list[dict]) -> tuple[list[dict], list[dict], bool]:
        """returns (kept_facts, conflict_entries, any_unresolved).
        kept_facts: 충돌 무관 fact + 각 충돌그룹의 승자(A). 미해소 그룹은 승자 없이 그룹 전체를
                    kept에 포함(경쟁 fact 투명 노출)하고 any_unresolved=True.
        conflict_entries: [{fact_ids, predicate, values}] — 탐지된 모든 그룹."""
        groups = _conflicting_fact_groups(facts)
        conflicting_ids = {f["id"] for group in groups for f in group}
        kept = [f for f in facts if f["id"] not in conflicting_ids]
        entries, any_unresolved = [], False
        for group in groups:
            winner = self._supersedes_winner(group)          # (A) — 못 가르면 바로 (C)
            entries.append({
                "fact_ids": sorted(f["id"] for f in group),
                "predicate": group[0].get("predicate"),
                "values": sorted({repr(f.get("value")) for f in group}),
            })
            if winner is not None:
                kept.append(winner)
            else:
                kept.extend(group)
                any_unresolved = True
        return kept, entries, any_unresolved

    def _current_facts(self, query: str) -> list[dict]:
        return [fact for fact in self._scoped_facts(query) if not fact.get("valid_until")]

    def _stale_view_warnings(self, views: list[dict]) -> list[str]:
        messages: list[str] = []
        for view in views:
            for fact_id in view.get("source_fact_ids", []):
                if not self.store.has(fact_id):
                    messages.append(f"{view['id']}: source fact {fact_id} 부재, view stale")
                    continue
                fact = self.store.get(fact_id)
                if fact.get("status") != "reviewed":
                    messages.append(f"{view['id']}: source fact {fact_id} 미검수, view stale")
                elif fact.get("valid_until"):
                    messages.append(f"{view['id']}: source fact {fact_id} 닫힘(superseded), view stale")
        return messages

    def _views_for_current_facts(self, views: list[dict], facts: list[dict]) -> list[dict]:
        fact_ids = {fact["id"] for fact in facts}
        return [view for view in views if set(view.get("source_fact_ids", [])) & fact_ids]

    def _raw_available_for(self, obj: dict) -> bool:
        for ref_id in obj.get("evidence_refs", []):
            if not self.store.has(ref_id):
                continue
            ref = self.store.get(ref_id)
            manifest_id = ref.get("evidence_manifest_id")
            if manifest_id in self.missing_raw_manifest_ids:
                return False
        return True

    def _restricted_for(self, obj: dict) -> bool:
        for ref_id in obj.get("evidence_refs", []):
            if not self.store.has(ref_id):
                continue
            manifest_id = self.store.get(ref_id).get("evidence_manifest_id")
            if manifest_id and self.store.has(manifest_id):
                if self.store.get(manifest_id).get("redaction_status") not in (None, "approved"):
                    return True
        return False
