# BB2 Brain Ingest Revision Comparison

## Version A: skill-creator

Strength:
- Cleaner progressive disclosure.
- Keeps SKILL.md smaller.
- Makes `reviewed_current`, `complete ingest`, and `history_coverage` easy to find.

Weakness:
- Weaker against the exact rationalizations that caused the 32-object failure.
- Does not emphasize evidence contamination enough.

## Version B: writing-skills

Strength:
- Directly blocks pressure failures.
- Explicitly separates reviewed current facts from complete history.
- Calls out current tool limits for `code_locator_ids`.

Weakness:
- Too much failure-mode text for the main skill body if copied directly.
- Better as "absolute rules + checklist" than as the whole skill structure.

## Final Promotion

Use Version A's structure and Version B's guardrails:

- Add a short `reviewed_current` vs `complete ingest` contract near the top of `SKILL.md`.
- Require fixed literals: `history_coverage=unsearched`, `history_coverage=partial`, `history_coverage=complete`.
- Rewrite symbol language: code symbols are discovery units; stored units are meaning atoms.
- Add evidence contamination as an absolute rule.
- Move reconstruction and code-anchor enforcement details to references.
- Do not claim current schema/lint enforce non-empty `code_locator_ids`; they only reject dangling references.
