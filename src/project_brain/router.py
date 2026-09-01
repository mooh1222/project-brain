import re
from collections import defaultdict

from project_brain.intent import classify_query
from project_brain.status import answer_status, claim_status
from project_brain.store import BrainStore
from project_brain.surface import glossary_name_surfaces

_SCOPE_TOKEN_RE = re.compile(r"[0-9A-Za-z._-]+")
_DETERMINISTIC_FACETS = {
    "why_changed",
    "current_status",
    "as_of_history",
    "evidence_provenance",
}


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
        missing_raw_manifest_ids: set[str] | None = None,
    ):
        self.store = store
        self.missing_raw_manifest_ids = missing_raw_manifest_ids or set()

    def answer(self, query: str) -> dict:
        avoid_map = self._avoid_corrections()
        classified = classify_query(query, avoid_map)
        # 라우팅·매칭은 정규화된 canonical로 한다 (시작팝업→입장팝업 등 도메인 용어 보정 반영). 원본 query는 출력 echo에만 사용.
        canonical = classified.normalized.canonical_query
        facet_intents = [
            intent
            for intent in classified.intents
            if intent in _DETERMINISTIC_FACETS
        ]
        unsupported_intents = [
            intent
            for intent in classified.intents
            if intent not in _DETERMINISTIC_FACETS
        ]
        warnings: list[str] = []
        if classified.normalized.avoided_terms:
            corrected = ", ".join(sorted(set(classified.normalized.avoided_terms)))
            warnings.append(f"용어 보정 적용: {corrected} → canonical 질의로 라우팅")
        if not facet_intents:
            warnings.append(
                "일반 의미·구현 위치 질문은 search 결과에서 핵심 객체를 고른 뒤 show로 확인하세요."
            )
            return {
                "query": query,
                "canonical_query": canonical,
                "intents": classified.intents,
                "status": "raw-only",
                "candidate_object_ids": [],
                "source_object_ids": [],
                "sections": [{
                    "intent": "search_show",
                    "object_ids": [],
                    "summary": "General recall is handled by search, then show",
                    "guidance": [
                        f'project-brain search "{canonical}"',
                        "project-brain show <object_id>",
                    ],
                }],
                "warnings": warnings,
                "needs_clarification": True,
            }
        candidate_ids: list[str] = []
        source_ids: list[str] = []
        sections: list[dict] = []
        claim_statuses: list[str] = []
        clarification_needed = False

        for intent in facet_intents:
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
                    {t["id"] for t in self._matched_reviewed_name_terms(canonical)}
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
            elif intent == "evidence_provenance":
                # 정밀 규칙(§6.6): 함께 분류된 의도가 가리키는 source object의 출처 사슬만 defend.
                # 각 의도 collector를 재사용해 재수집하므로 루프 순서와 무관하다.
                # 단독 evidence(다른 의도 없음)는 scope 매칭 사실로 fallback(기존 동작 보존).
                intents_present = set(facet_intents)
                sources: list[dict] = []
                if "why_changed" in intents_present:
                    sources.extend(self._reviewed_by_kind("EventLedgerRecord"))
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

        if unsupported_intents:
            sections.append({
                "intent": "search_show",
                "object_ids": [],
                "summary": "General recall is handled by search, then show",
                "guidance": [
                    f'project-brain search "{canonical}"',
                    "project-brain show <object_id>",
                ],
            })
            warnings.append(
                "일반 의미·구현 위치 부분은 query가 계산하지 않습니다. search 결과에서 핵심 객체를 고른 뒤 show로 확인하세요."
            )

        return {
            "query": query,
            "canonical_query": classified.normalized.canonical_query,
            "intents": classified.intents,
            "status": answer_status(claim_statuses),
            "candidate_object_ids": sorted(set(candidate_ids)),
            "source_object_ids": sorted(set(source_ids)),
            "sections": sections,
            "warnings": warnings,
            "needs_clarification": (not source_ids) or clarification_needed,
        }

    def _reviewed_by_kind(self, kind: str) -> list[dict]:
        return [obj for obj in self.store.by_kind(kind) if obj.get("status") == "reviewed"]

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

    def _matched_reviewed_name_terms(self, query: str) -> list[dict]:
        """대표어·동의어·별칭이 query에 등장한 reviewed GlossaryTerm을 찾는다.

        glossary 응답·변경 결정·scope 추론이 공유한다. 한 질의에서 여러 표면이
        맞으면 각 어휘의 가장 긴 표면을 기준으로, 더 긴 다른 어휘 표면에 포함되는
        짧은 매칭은 제외한다.
        """
        matched: list[tuple[dict, str]] = []
        for term in self._reviewed_by_kind("GlossaryTerm"):
            surfaces = glossary_name_surfaces(term)
            matching = [surface for surface in surfaces if surface and surface in query]
            if matching:
                matched.append((term, max(matching, key=len)))

        return [
            term for term, surface in matched
            if not any(
                other is not term
                and len(other_surface) > len(surface)
                and surface in other_surface
                for other, other_surface in matched
            )
        ]

    def _matched_candidate_terms(self, query: str) -> list[dict]:
        """query 텍스트에 term/synonyms/aliases가 등장하는 candidate GlossaryTerm.
        reviewed DecisionRecord의 affected anchor 연결에만 쓰며 candidate 자체를 답에
        노출하거나 충돌 해소·scope 추론 입력으로 쓰지 않는다."""
        result = []
        for term in self.store.by_kind("GlossaryTerm"):
            if term.get("status") != "candidate":
                continue
            surfaces = glossary_name_surfaces(term)
            if any(surface and surface in query for surface in surfaces):
                result.append(term)
        return result

    def _matched_mappings(self, query: str) -> list[dict]:
        """query에 등장하는 용어 텍스트로 reviewed DomainMapping을 찾는다.
        변경 이유 facet에서 DecisionRecord의 affected mapping anchor를 찾는 용도다.
        참조하는 GlossaryTerm이 candidate면 term/synonym만, reviewed면 aliases까지 이름
        표면으로 쓰며 mapping 자체는 query 일반 의미 답에 노출하지 않는다."""
        result = []
        for mapping in self._reviewed_by_kind("DomainMapping"):
            surfaces: set[str] = set()
            for term_id in mapping.get("glossary_term_ids", []):
                if not self.store.has(term_id):
                    continue
                term = self.store.get(term_id)
                surfaces.update(glossary_name_surfaces(
                    term,
                    include_aliases=term.get("status") == "reviewed",
                ))
            if any(surface and surface in query for surface in surfaces):
                result.append(mapping)
        return result

    def _glossary_scope_disclosures(self, query: str) -> list[str]:
        """glossary 용어 유래 scope 추론이 실제로 다른 팩트를 걸러냈을 때만 경고를 반환한다."""
        messages: list[str] = []
        all_facts = self._reviewed_by_kind("TemporalFact")
        for term in self._matched_reviewed_name_terms(query):
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
        for term in self._matched_reviewed_name_terms(query):
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
                # 신뢰 게이트 fail-closed: "approved"가 아니면(None·키 누락 포함) restricted로 본다.
                # schema.py 화이트리스트 주석 의도와 일치 — 정상 데이터는 redaction_status 필수·enum이라
                # None은 lint 전 수기편집 같은 비정상 상태다. 의심스러우면 막는 쪽(거짓양성>거짓음성).
                if self.store.get(manifest_id).get("redaction_status") != "approved":
                    return True
        return False
