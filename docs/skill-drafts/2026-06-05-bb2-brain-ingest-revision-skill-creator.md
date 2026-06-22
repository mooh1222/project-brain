# Skill-Creator Revision Draft

## Bias

Keep the skill easy to load and navigate. Put the irreversible rules in `SKILL.md`; put detailed checks in references.

## Proposed Core Contract

```md
현재 사실 검수와 완전 적재를 분리한다.

- reviewed_current: 현재 develop 코드 + 현행 기획서 + 서버위키로 현재 meaning/value/boundary가 확인된 상태다. "뭐야/어디/지금" 질문에 답할 수 있다.
- complete ingest: reviewed_current에 Jira/Slack/PR/commit 변경 이력까지 확인·연결된 상태다. "왜/그때" 질문에 답할 수 있다.

history_coverage는 자유 메모가 아니라 고정 literal 하나를 쓴다.
- history_coverage=unsearched
- history_coverage=partial
- history_coverage=complete
```

## Proposed Structure

- `SKILL.md`: state split, meaning atom rule, evidence contamination rule, high-level workflow.
- `references/object-model.md`: `DomainMapping.caveats` fixed literal, `EvidenceManifest.source_type` vs `DecisionRecord.decision_type`.
- `references/completeness-checklist.md`: self-checks that lint cannot enforce.
- `references/worked-example.md`: show how a current-only slice differs from complete history.

## Proposed Meaning Unit Wording

```md
코드 심볼은 발견 단위이고, 저장 단위는 의미 원자다.
독립적으로 질문되고, 독립 근거를 가지며, 독립 변경 이력을 가질 수 있으면 별도 DomainMapping으로 저장한다.
enum 값은 기본적으로 한 의미 원자의 값 목록이다. 특정 값이 독립 행동 규칙, 독립 근거, 독립 변경 이력을 가지면 별도 의미 원자로 승격한다.
```

## Risk

This draft is concise but may not block rationalization under pressure. In particular, an agent may still read `reviewed` as "all history complete" unless the red flags call that out explicitly.
