# Ingest Recovery Baseline

engine_source_head: `36baa7347f3f5b6e24c1da21475150b882e413e6`

engine_worktree_head: `36baa7347f3f5b6e24c1da21475150b882e413e6`

engine_source_dirty_paths:

- `M CLAUDE.md`
- `M src/project_brain/assembly.py`
- `M src/project_brain/ingest.py`
- `M src/project_brain/router.py`
- `M tests/test_assembly.py`
- `M tests/test_ingest.py`
- `M tests/test_router.py`
- `?? AGENTS.md`
- `?? docs/plans/2026-07-27-ingest-fix-execution-plan.md`
- `?? docs/reports/2026-07-27-plan-delta-bg.md`
- `?? docs/reports/2026-07-27-two-ingest-session-review.md`
- `?? docs/reports/2026-07-28-brain-ingest-redesign-review.html`
- `?? docs/superpowers/plans/2026-07-27-handoff-consumer.md`
- `?? docs/superpowers/plans/2026-07-28-brain-ingest-recovery.md`

bb2_head: `d1294e7032d6304fe4371e7792b7a8e3010f3e5c`

bb2_dirty_paths:

- `M .agents/skills/guardrails/SKILL.md`
- `M .agents/skills/guardrails/hooks/block-dangerous-git.sh`
- `M .agents/skills/guardrails/hooks/block-pbxproj-settings.sh`
- `M .agents/skills/guardrails/hooks/tests/test_block_dangerous_git.py`
- `M Podfile.lock`
- `M brain/checks/test_real_corpus.py`
- `M brain/objects/code/code.disturb-bubble-system.bubble-object-factory-disturb-creation-0.json`
- `M brain/objects/code/code.disturb-bubble-system.bubble-object-factory-disturb-creation-1.json`
- `M brain/objects/code/code.disturb-bubble-system.bubble-object-factory-disturb-creation-2.json`
- `M brain/objects/code/code.disturb-bubble-system.bubble-object-factory-disturb-creation-3.json`
- `M brain/objects/code/code.disturb-bubble-system.disturb-base-class.json`
- `M brain/objects/code/code.disturb-bubble-system.disturb-list.json`
- `M brain/objects/code/code.disturb-bubble-system.disturb-support-list-0.json`
- `M brain/objects/code/code.disturb-bubble-system.disturb-support-list-1.json`
- `M brain/objects/code/code.disturb-bubble-system.disturb-support-list-2.json`
- `M brain/objects/code/code.disturb-bubble-system.disturb-support-list-3.json`
- `M brain/objects/code/code.disturb-bubble-system.ext-enum-factory.json`
- `M brain/objects/code/code.disturb-bubble-system.ext-sprite-tutorial.json`
- `M brain/objects/code/code.disturb-bubble-system.ext-stagecode.json`
- `M brain/objects/code/code.disturb-bubble-system.score-init.json`
- `M brain/objects/code/code.disturb-bubble-system.term-bubble-object-factory.json`
- `M brain/objects/code/code.disturb-bubble-system.term-create-bubble-object-disturb.json`
- `M brain/objects/code/code.disturb-bubble-system.term-disturb-support-list-field.json`
- `M brain/objects/code/code.disturb-bubble-system.term-disturb-support-type.json`
- `M brain/objects/code/code.disturb-bubble-system.term-initilize-with-game-start-object.json`
- `M brain/objects/code/code.ingame-area-expansion.admin-row-adjustment--4.json`
- `?? .agents/skills/guardrails/hooks/tests/run-tests.sh`
- `?? .agents/skills/guardrails/hooks/tests/test_block_pbxproj_settings.py`

bb2_local_exclude_brain: true

검증 근거: `git check-ignore -v brain/objects/code/code.petskill-kamehameha.aim-degree-limit--0.json`은 `.git/info/exclude:18:/brain`을 반환했다.

baseline_pytest: `PASS — 674 passed, 32 subtests passed in 16.40s`

baseline_template_unittest: `PASS — Ran 75 tests in 8.837s`
