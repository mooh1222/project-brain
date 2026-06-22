# Writing-Skills Revision Draft

## Baseline Failure Scenarios

1. Agent sees current code + current spec, promotes mappings, then answers why/as-of as if history were complete.
2. Agent remembers a prior session or design note and uses that remembered fact as object evidence.
3. Agent treats `code_locator_ids` non-empty as tool-enforced even though current schema/lint only check dangling ids.
4. Agent splits race status enum values too finely, creating retrieval fragments, or bundles unrelated rules into one feature blob.

## Skill Pressure Rules

```md
Red flag: "reviewed니까 complete다."
Correction: reviewed_current only says current meaning/value/boundary was checked. complete ingest requires history_coverage=complete.

Red flag: "이전 세션에서 이미 봤다."
Correction: memory/design/task history is not object evidence. Claim-bearing fields must point to EvidenceRef from the current source packet.

Red flag: "lint가 code_locator_ids를 강제한다."
Correction: current lint only rejects dangling code_locator_ids. Non-empty code anchors are an agent self-check until a schema/lint slice enforces them.
```

## Reconstruction Contract

```md
모든 객체를 매번 cold replay하지 않는다. 대신 claim-bearing fields(meaning, boundary, value, decision, caveat, code_locator)에 EvidenceRef를 붙이고, 고위험 객체만 재구성 감사를 한다.

고위험: DecisionRecord, supersede, spec_reflected=no, 낮은 confidence, 새 source type, code anchor, history_coverage=complete 선언.
```

## Risk

This draft is stronger against failures but too verbose if copied wholesale into `SKILL.md`. Final should use this for absolute rules and red flags, while moving details to references.
