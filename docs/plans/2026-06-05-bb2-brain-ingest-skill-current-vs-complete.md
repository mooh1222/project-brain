# BB2 Brain Ingest Skill Current-vs-Complete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update `bb2-brain-ingest` so agents keep `reviewed_current` separate from `complete ingest`, use fixed `history_coverage` literals, and store meaning atoms rather than raw code symbols.

**Architecture:** Documentation-only skill update. Draft two alternatives in ignored scratch files, compare them, then promote the final wording into `.claude/skills/bb2-brain-ingest/` only. Verify against live `schema.py` and `lint.py` so the skill does not claim enforcement that the tools do not provide.

**Tech Stack:** Markdown skills, BB2 Brain Python schema/lint references, ignored `docs/superpowers/skill-drafts/` scratch artifacts.

---

### Task 1: Capture The Target Contract

**Files:**
- Create: `docs/superpowers/skill-drafts/2026-06-05-bb2-brain-ingest-revision-skill-creator.md`
- Create: `docs/superpowers/skill-drafts/2026-06-05-bb2-brain-ingest-revision-writing-skills.md`
- Create: `docs/superpowers/skill-drafts/2026-06-05-bb2-brain-ingest-revision-comparison.md`

- [x] **Step 1: Write the skill-creator version**

Use a concise progressive-disclosure structure:

```md
Decision:
- Keep SKILL.md lean.
- Move field-level details to references/object-model.md and references/completeness-checklist.md.
- Define reviewed_current, complete ingest, and history_coverage once near the top.
```

- [x] **Step 2: Write the writing-skills version**

Use failure-pressure language:

```md
Pressure failures to block:
- "1층만 했지만 reviewed니까 complete다."
- "이전 세션에서 안 사실을 EvidenceRef처럼 써도 된다."
- "code_locator_ids는 lint가 강제한다."
```

- [x] **Step 3: Compare and choose final merge**

Run:

```bash
rg -n "reviewed_current|complete ingest|history_coverage|code_locator_ids|EvidenceRef" docs/superpowers/skill-drafts
```

Expected: all three new scratch files contain the required terms.

### Task 2: Apply Final Skill Edits

**Files:**
- Modify: `.claude/skills/bb2-brain-ingest/SKILL.md`
- Modify: `.claude/skills/bb2-brain-ingest/references/completeness-checklist.md`
- Modify: `.claude/skills/bb2-brain-ingest/references/object-model.md`
- Modify: `.claude/skills/bb2-brain-ingest/references/scope.md`
- Modify: `.claude/skills/bb2-brain-ingest/references/worked-example.md`
- Modify: `.claude/skills/bb2-brain-ingest/references/ingest-tools.md`

- [x] **Step 1: Add the state split**

Insert this contract near the top of `SKILL.md`:

```md
- reviewed_current: current develop code + current spec + server wiki validate the current meaning/value/boundary.
- complete ingest: reviewed_current + checked Jira/Slack/PR/commit history.
```

- [x] **Step 2: Add fixed history literals**

Use exactly:

```md
history_coverage=unsearched
history_coverage=partial
history_coverage=complete
```

- [x] **Step 3: Replace symbol storage language**

Use this split rule:

```md
코드 심볼은 발견 단위이고, 저장 단위는 의미 원자다.
독립적으로 질문되고, 독립 근거를 가지며, 독립 변경 이력을 가질 수 있으면 별도 DomainMapping으로 저장한다.
```

- [x] **Step 4: Correct tool-enforcement claims**

State that current schema/lint only check dangling `code_locator_ids`; non-empty code anchors are an agent self-check and future enforcement slice.

### Task 3: Verify

**Files:**
- Read: `scripts/bb2_brain/schema.py`
- Read: `scripts/bb2_brain/lint.py`
- Read: `.claude/skills/bb2-brain-ingest/`

- [x] **Step 1: Check live schema/lint facts**

Run:

```bash
rg -n "DomainMapping|code_locator_ids|SOURCE_TYPE_VALUES|DECISION_TYPE_VALUES" scripts/bb2_brain/schema.py scripts/bb2_brain/lint.py
```

Expected: `DomainMapping` required fields do not include `code_locator_ids`; lint checks dangling references only.

- [x] **Step 2: Check final wording**

Run:

```bash
rg -n "reviewed_current|complete ingest|history_coverage=unsearched|history_coverage=partial|history_coverage=complete" .claude/skills/bb2-brain-ingest
```

Expected: required terms appear in SKILL.md and references.

- [x] **Step 3: Check skill mirror**

Run:

```bash
test -L .agents/skills/bb2-brain-ingest && readlink .agents/skills/bb2-brain-ingest
```

Expected: `.agents/skills/bb2-brain-ingest` points to `../../.claude/skills/bb2-brain-ingest`.
