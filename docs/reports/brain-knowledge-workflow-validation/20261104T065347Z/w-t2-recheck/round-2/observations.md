> E3 당시 판정·관찰의 보존 사본이다. W-T1의 두 기록 세션은 개인 memory를 읽었으므로
> 이번 memory 비활성 통과 집계에서는 제외하고 재실행 결과로 교체한다.
> 작은 Markdown 산출물만 추적하며 JSONL·프로젝트·해시 원본은 로컬 전용이다.
> 링크는 추적 산출물로만 연결하고 원본 증거는 경로 텍스트로 표시했다.

# W-T2-RECHECK round-2 관찰

## recall

- Session: `01a1a55d-3792-74d3-82eb-6856b64c811a`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](recall.request.md), 기존 세션 JSONL (로컬 원본: `w-t2-recheck/round-2/recall.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t2-recheck/round-2/recall.events.jsonl`), [답변](recall.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-query/SKILL.md' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/discovery.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md' `
- exit=0: `/bin/zsh -lc 'cat .project-brain.json' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft list' `
- exit=0: `/bin/zsh -lc './tools/project-brain search "재시도 제한 두 실행 경로 규칙 위험 근거 적용 범위"' `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.immediate' `
- exit=0: `/bin/zsh -lc './tools/project-brain show insight.retry.entry-path-limit-risk' `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.scheduled' `
- exit=0: `/bin/zsh -lc 'nl -ba docs/retry-rules.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain show evref.retry.rules' `
- exit=0: `/bin/zsh -lc './tools/project-brain show context.retry' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

현재 **문서 규칙상 두 경로 모두 최대 3회 재시도하며, 제한은 경로별로 별도 적용**됩니다.

| 실행 경로 | 규칙 | 검수된 Brain 근거 |
|---|---|---|
| 즉시 실행 | 최대 3회 재시도, 해당 경로에 별도 적용 | `mapping.retry.immediate` |
| 예약 실행 | 최대 3회 재시도, 해당 경로에 별도 적용 | `mapping.retry.scheduled` |

공통 원문은 재시도 운영 규칙 4행 (로컬 원본: `w-t2-recheck/round-2/project/docs/retry-rules.md`)이며, 두 객체 모두 `evref.retry.rules`를 근거로 연결합니다.

변경 시 주의할 위험은 **한 경로만 수정·확인하고 다른 진입 경로의 제한을 누락하는 것**입니다. 두 경로를 함께 확인해야 합니다. 이는 검수된 교차 위험 기록 `insight.retry.entry-path-limit-risk`와 원문 5행 (로컬 원본: `w-t2-recheck/round-2/project/docs/retry-rules.md`)에 명시돼 있습니다.

적용 범위는 **이 합성 운영 규칙의 즉시 실행·예약 실행 제한 변경**입니다. 실제 코드의 현재 구현이나 장치 실행은 검증되지 않았고, 구현 위치도 연결되어 있지 않습니다. 다른 실행 경로로 일반화할 수 없으며, 네트워크 전송 구현은 해당 지식 범위 밖입니다. 따라서 구현 변경에 앞서 두 진입 경로의 실제 제한 적용 지점을 확인해야 합니다.

이번에는 읽기 전용으로 조회했으며, 기존 미커밋 변경은 그대로 보존했습니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-query` 스킬로 두 실행 경로의 재시도 규칙과 근거를 먼저 조회하고, 변경 시 위험과 적용 범위를 확인하겠습니다.


## record

- Session: `01a1a55b-5429-7c62-b719-a2d9a176ae32`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](record.request.md), 기존 세션 JSONL (로컬 원본: `w-t2-recheck/round-2/record.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t2-recheck/round-2/record.events.jsonl`), [답변](record.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'cat docs/retry-rules.md; cat .project-brain.json' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc "cat '.agents/skills/demo-brain-draft/references/knowledge-workflow.md'" `
- exit=0: `/bin/zsh -lc "cat '.agents/skills/demo-brain-ingest/references/ingest-tools.md'" `
- exit=0: `/bin/zsh -lc "cat '.agents/skills/demo-brain-ingest/references/object-model.md'" `
- exit=0: `/bin/zsh -lc "cat '.agents/skills/demo-brain-ingest/references/completeness-checklist.md'" `
- exit=0: `/bin/zsh -lc "cat '.agents/skills/demo-brain-ingest/references/scope.md'" `
- exit=0: `/bin/zsh -lc './tools/project-brain --help' `
- exit=0: `/bin/zsh -lc "sed -n '210,460p' .agents/skills/demo-brain-ingest/references/ingest-tools.md" `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/object-model.md' `
- exit=0: `/bin/zsh -lc 'rg --files brain .agents/skills/demo-brain-ingest/scripts tools; cat tools/project-brain; cat tools/python' `
- exit=0: `/bin/zsh -lc "./tools/project-brain search '즉시 실행 예약 실행 재시도 제한'" `
- exit=0: `/bin/zsh -lc './tools/project-brain --engine-identity; ./tools/project-brain ingest --help' `
- exit=1: `/bin/zsh -lc 'cat brain/checks/test_existing_rules.py; cat brain/eval_scenarios.json; cat tools/sitecustomize.py; cat .agents/skills/demo-brain-ingest/references/object-templates/kinds/insight.template.json; cat .agents/skills/demo-brain-ingest/references/object-templates/coverage.direct.template.json' `
- exit=0: `/bin/zsh -lc "sed -n '1,210p' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py; sed -n '1,160p' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.sh; rg -n 'baseline|direct|finalize|receipt|def main' .agents/skills/demo-brain-ingest/scripts/run_ingest.sh" `
- exit=0: `/bin/zsh -lc "./tools/python -c 'import project_brain, pathlib; print(pathlib.Path(project_brain.__file__).parent)'" `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.immediate; ./tools/project-brain show mapping.retry.scheduled; ./tools/project-brain show evref.retry.rules; ./tools/project-brain show manifest.retry.rules' `
- exit=0: `/bin/zsh -lc "rg -n 'def capture|def main|add_argument|def finalize|baseline|advisories|require_code' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py" `
- exit=0: `/bin/zsh -lc "sed -n '450,570p' .agents/skills/demo-brain-ingest/references/ingest-tools.md; cat .agents/skills/demo-brain-ingest/references/object-templates/coverage-direct.template.json; cat .agents/skills/demo-brain-ingest/scripts/engine_python.py" `
- exit=0: `/bin/zsh -lc "rg -n 'Insight|cross-cutting-risk|scope' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/schema.py; sed -n '1,160p' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/coverage.py; git -C /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3 rev-parse HEAD; git rev-parse --show-toplevel HEAD main" `
- exit=0: `/bin/zsh -lc "sed -n '420,560p' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py; sed -n '670,730p' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py; rg -n 'def _default_runner|audit|real_corpus|unittest|project-brain' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py; cat .gitignore" `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import json, tempfile ⏎ from pathlib import Path ⏎ from datetime import datetime, timezone ⏎ from project_brain.coverage import normalize_coverage ⏎ from project_brain.schema import validate_object ⏎ work=Path(tempfile.mkdtemp(prefix='retry-lesson-ingest-')) ⏎ now=datetime.now(timezone.utc).isoformat() ⏎ obj={ ⏎ 'id':'insight.retry.entry-path-limit-risk','kind':'Insight','schema_version':'0.1', ⏎ 'status':'reviewed','poc_priority':'P0','truth_role':'synthesis', ⏎ 'title':'재시도 제한 변경 시 즉시 실행과 예약 실행을 함께 확인', ⏎ 'created_at':now,'updated_at':now,'tags':['retry'], ⏎ 'evidence_refs':['evref.retry.rules'], ⏎ 'body':'즉시 실행과 예약 실행은 모두 최대 세 번 재시도하며 각 경로가 별도로 제한을 적용한다. 재시도 제한을 수정할 때 한 경로만 확인하면 다른 진입 경로의 제한을 누락할 위험이 있으므로 두 진입 경로를 함께 확인해야 한다.', ⏎ 'source_object_ids':['mapping.retry.immediate','mapping.retry.scheduled'], ⏎ 'insight_type':'cross-cutting-risk', ⏎ 'scope':'docs/retry-rules.md의 합성 운영 규칙에서 즉시 실행과 예약 실행의 재시도 제한을 수정하는 경우에 적용한다. 문서 규칙의 의미는 사용자가 문장 단위로  … (전체는 JSONL) `
- exit=0: `/bin/zsh -lc './tools/python .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py --validate-config /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/finalization-config.json' `
- exit=0: `/bin/zsh -lc 'PATH="$PWD/tools:$PATH" ./tools/python .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py --capture-baseline > /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/baseline.json' `
- exit=0: `/bin/zsh -lc 'cat /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/baseline.json; git status --short --branch' `
- exit=0: `/bin/zsh -lc './tools/project-brain ingest --objects-file /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/objects.json --coverage-file /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/coverage.json --repo-root "$PWD" --expected-repo-id demo --expected-revision-ref main --engine-sha be75896a18efc076150708882c8af453ee970672 > /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/ingest-result.json' `
- exit=0: `/bin/zsh -lc 'cat /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/ingest-result.json' `
- exit=1: `/bin/zsh -lc 'PATH="$PWD/tools:$PATH" ./tools/python .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py --config /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/finalization-config.json --baseline /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/baseline.json --transaction-result /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/ingest-result.json --repo-root "$PWD" > /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/finalization.json' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import json ⏎ from pathlib import Path ⏎ p=Path('/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/finalization.json') ⏎ x=json.loads(p.read_text()) ⏎ print(json.dumps(x,ensure_ascii=False,indent=2)) ⏎ PY" `
- exit=0: `/bin/zsh -lc "sed -n '728,807p' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py" `
- exit=0: `/bin/zsh -lc 'PATH="$PWD/tools:$PATH" ./tools/python .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py --config /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/finalization-config.json --baseline /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/baseline.json --transaction-result /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/ingest-result.json > /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/finalization.json' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import json ⏎ from pathlib import Path ⏎ x=json.loads(Path('/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/finalization.json').read_text()) ⏎ print(json.dumps({'ok':x['ok'],'commands':{k:{'ok':v['ok'],'stderr':v.get('stderr'),'payload':v.get('payload')} for k,v in x['commands'].items()},'isolation':x['isolation'],'recall_checks':x['recall_checks'],'errors':x['errors']},ensure_ascii=False,indent=2)) ⏎ PY" `
- exit=0: `/bin/zsh -lc 'git status --short --branch; git diff --stat; rg --files brain/objects/insights; cat brain/objects/insights/insight.retry.entry-path-limit-risk.json' `
- exit=0: `/bin/zsh -lc "./tools/project-brain search '재시도 제한을 수정할 때 두 진입 경로를 함께 확인해야 하는 이유' > /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/recall.json; cat /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7/recall.json" `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import json, hashlib ⏎ from datetime import datetime, timezone ⏎ from pathlib import Path ⏎ work=Path('/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-lesson-ingest-y1eoiuy7') ⏎ recall=json.loads((work/'recall.json').read_text()) ⏎ expected='insight.retry.entry-path-limit-risk' ⏎ assert expected in {o['object_id'] for o in recall['advisories']} ⏎ receipt=json.loads((work/'ingest-result.json').read_text()) ⏎ assert receipt['expected_objects']==receipt['verified_objects']==[{'id':expected,'kind':'Insight'}] ⏎ final=json.loads((work/'finalization.json').read_text()) ⏎ assert final['ok'] and not final['isolation']['unexpected_new_ids'] ⏎ report={ ⏎  'verified_at':datetime.now(timezone.utc).isoformat(), ⏎  'route':'single','mode':'direct','feature_done':True,'current_ingest_done':True,'history_coverage':'unsearched', ⏎  'source_packet':'docs/retry-rules.md','mapping.retry.immediate','mapping.retry.scheduled','evref.retry.rules','manifest.retry … (전체는 JSONL) `
- exit=0: `/bin/zsh -lc 'git diff --exit-code -- docs/retry-rules.md .project-brain.json brain/objects/mappings brain/objects/evidence_refs brain/raw/manifests .agents/skills; git status --short --branch' `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

Brain에 `reviewed` Insight로 직접 적재했습니다: `insight.retry.entry-path-limit-risk`.

- 위험: 경로별로 제한을 적용하므로, 수정 시 두 진입 경로를 함께 확인해야 누락을 줄일 수 있음.
- 적용 범위: 즉시 실행·예약 실행의 재시도 제한 변경. 합성 문서 규칙이며 실제 구현은 미검증.
- 기존 경로별 근거 객체 2개를 연결했고, 새 어휘는 생성하지 않았습니다.

lint·평가·기존 검사와 검색 `advisories` 회수를 확인했습니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-ingest` 스킬로 확정된 교훈과 기존 경로별 근거를 확인한 뒤 Brain에 적재하겠습니다. 새 어휘는 정의하지 않고, 위험과 적용 범위를 기록하겠습니다.


- [initial 파일 해시 (로컬 원본: `w-t2-recheck/round-2/initial.sha256`), Git (로컬 원본: `w-t2-recheck/round-2/initial.git.txt`).
- before-recall 파일 해시 (로컬 원본: `w-t2-recheck/round-2/before-recall.sha256`), Git (로컬 원본: `w-t2-recheck/round-2/before-recall.git.txt`).
- after-recall 파일 해시 (로컬 원본: `w-t2-recheck/round-2/after-recall.sha256`), Git (로컬 원본: `w-t2-recheck/round-2/after-recall.git.txt`).
- before-recall → after-recall: 파일 해시 동일=True; Git 동일=True.
