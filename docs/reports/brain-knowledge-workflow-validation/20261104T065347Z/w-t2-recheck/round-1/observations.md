> E3 당시 판정·관찰의 보존 사본이다. W-T1의 두 기록 세션은 개인 memory를 읽었으므로
> 이번 memory 비활성 통과 집계에서는 제외하고 재실행 결과로 교체한다.
> 작은 Markdown 산출물만 추적하며 JSONL·프로젝트·해시 원본은 로컬 전용이다.
> 링크는 추적 산출물로만 연결하고 원본 증거는 경로 텍스트로 표시했다.

# W-T2-RECHECK round-1 관찰

## recall

- Session: `01a1a55c-af93-7d02-9c31-af44ffec7c20`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](recall.request.md), 기존 세션 JSONL (로컬 원본: `w-t2-recheck/round-1/recall.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t2-recheck/round-1/recall.events.jsonl`), [답변](recall.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-query/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat .project-brain.json' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md .agents/skills/demo-brain-draft/references/discovery.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft list' `
- exit=0: `/bin/zsh -lc './tools/project-brain search "재시도 제한 두 실행 경로 규칙 위험 근거 적용 범위"' `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.immediate' `
- exit=0: `/bin/zsh -lc './tools/project-brain show insight.retry.entry-limit-change-risk' `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.scheduled' `
- exit=0: `/bin/zsh -lc './tools/project-brain search "즉시 실행 예약 실행 재시도" --all-contexts' `
- exit=0: `/bin/zsh -lc './tools/project-brain show evref.retry.rules' `
- exit=0: `/bin/zsh -lc './tools/project-brain show manifest.retry.rules' `
- exit=0: `/bin/zsh -lc 'nl -ba docs/retry-rules.md' `
- exit=0: `/bin/zsh -lc "rg --files brain/objects | rg '(retry|entry-limit)'" `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

현재 문서 규칙상 **즉시 실행과 예약 실행 모두 최대 3회 재시도하며, 제한은 경로별로 따로 적용합니다.**

| 실행 경로 | 규칙 | 검수된 Brain 근거 |
|---|---|---|
| 즉시 실행 | 최대 3회 재시도, 경로별 제한 적용 | `mapping.retry.immediate` |
| 예약 실행 | 최대 3회 재시도, 경로별 제한 적용 | `mapping.retry.scheduled` |

**주의할 위험은 한쪽 경로의 변경을 빠뜨리는 것입니다.** 제한이 별도로 적용되므로, 수정할 때 두 진입 경로를 함께 확인해야 합니다. 검수된 교차 위험 기록 `insight.retry.entry-limit-change-risk`가 두 매핑을 근거로 이 주의를 명시합니다.

근거 사슬은 두 매핑 → `evref.retry.rules` → 원문 retry-rules.md (로컬 원본: `w-t2-recheck/round-1/project/docs/retry-rules.md`)이며, 원문 4~5행에서도 규칙과 누락 위험을 확인했습니다.

**적용 범위는 합성 운영 규칙에 따른 두 경로의 제한 변경·검토입니다.** 실제 구현 코드나 장치 동작은 검증되지 않았고 코드 위치 근거도 없습니다. 변경 이력 역시 조회되지 않아, 현재 값이 정해진 이유나 과거 값까지 설명하는 근거로는 사용할 수 없습니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-query` 스킬로 두 실행 경로의 재시도 규칙과 근거를 먼저 조회하겠습니다. 확인된 내용과 검증이 필요한 부분을 구분해 알려드리겠습니다.


## record

- Session: `01a1a55b-514f-7531-a1bb-680678269b06`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](record.request.md), 기존 세션 JSONL (로컬 원본: `w-t2-recheck/round-1/record.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t2-recheck/round-1/record.events.jsonl`), [답변](record.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat docs/retry-rules.md ⏎ cat .project-brain.json' `
- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/ingest-tools.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/object-model.md ⏎ cat .agents/skills/demo-brain-ingest/references/scope.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/completeness-checklist.md ⏎ rg --files brain tools .agents/skills/demo-brain-ingest | head -100' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/object-model.md' `
- exit=0: `/bin/zsh -lc "sed -n '140,360p' .agents/skills/demo-brain-ingest/references/ingest-tools.md" `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/object-templates/kinds/Insight.template.json ⏎ cat .agents/skills/demo-brain-ingest/references/object-templates/direct-coverage.template.json ⏎ cat brain/eval_scenarios.json ⏎ cat brain/checks/test_existing_rules.py ⏎ cat .agents/skills/demo-brain-ingest/scripts/run_ingest.sh' `
- exit=0: `/bin/zsh -lc 'cat tools/project-brain ⏎ cat tools/python ⏎ cat tools/sitecustomize.py ⏎ cat brain/objects/mappings/mapping.retry.immediate.json ⏎ cat brain/objects/mappings/mapping.retry.scheduled.json ⏎ cat brain/raw/manifests/manifest.retry.rules.json ⏎ cat brain/objects/evidence_refs/evref.retry.rules.json ⏎ cat brain/objects/domain/context.retry.json' `
- exit=0: `/bin/zsh -lc "sed -n '360,560p' .agents/skills/demo-brain-ingest/references/ingest-tools.md ⏎ cat .agents/skills/demo-brain-ingest/scripts/finalize_ingest.sh" `
- exit=2: `/bin/zsh -lc "git rev-parse HEAD ⏎ ./tools/project-brain --engine-identity ⏎ rg --files -g AGENTS.md -g README.md -g '*project-code-verification*' brain .agents ⏎ rg -n 'Insight|advisories|isolation_baseline|capture_baseline|intentional_terminal|recall_checks' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/ingest_finalization.py" `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py ⏎ ./tools/project-brain --help ⏎ ./tools/project-brain ingest --help' `
- exit=0: `/bin/zsh -lc "rg -n 'def .*preflight|expected_repo_id|engine_sha|direct' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/cli.py | head -85 ⏎ rg -n 'Insight|advisories' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/search.py ⏎ cat .agents/skills/demo-brain-ingest/scripts/engine_python.py" `
- exit=0: `/bin/zsh -lc "git -C /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3 rev-parse HEAD ⏎ sed -n '132,200p' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py ⏎ rg -n 'Insight|cross-cutting-risk|scope|caveats' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/schema.py ⏎ ./tools/project-brain show --help ⏎ ./tools/project-brain search --help" `
- exit=0: `/bin/zsh -lc "rg -n '"'^def validate'"' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/schema.py ⏎ sed -n '355,386p' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/schema.py ⏎ sed -n '50,142p' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/cli.py ⏎ sed -n '780,815p' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/cli.py" `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import json, os, subprocess, sys, tempfile ⏎ from datetime import datetime, timezone ⏎ from pathlib import Path ⏎ from project_brain.schema import validate_object ⏎ from project_brain.coverage import normalize_coverage ⏎  ⏎ root=Path.cwd() ⏎ work=Path(tempfile.mkdtemp(prefix='brain-retry-ingest-')) ⏎ now=datetime.now(timezone.utc).isoformat() ⏎ obj={ ⏎ 'id':'insight.retry.entry-limit-change-risk', 'kind':'Insight', ⏎ 'schema_version':'0.1','status':'reviewed','poc_priority':'P0','truth_role':'synthesis', ⏎ 'title':'재시도 제한 변경 시 즉시 실행·예약 실행 누락 위험', ⏎ 'created_at':now,'updated_at':now,'tags':['retry'], ⏎ 'evidence_refs':['evref.retry.rules'], ⏎ 'body':'즉시 실행과 예약 실행은 모두 최대 세 번 재시도하며, 각 경로가 재시도 제한을 별도로 적용한다. 재시도 제한을 수정할 때 한 경로만 확인하면 다른 경로의 제한 변경을 누락할 위험이 있으므로, 즉시 실행과 예약 실행의 두 진입 경로를 함께 확인해야 한다.', ⏎ 'source_object_ids':['mapping.retry.immediate','mapping.retry.scheduled'], ⏎ 'scope':'docs/retry-rules.md의 합성 운영 규칙에 따른 즉시 실행과 예약 실행의 재시도 제한 변경 및 검토에 적용한다. … (전체는 JSONL) `
- exit=0: `/bin/zsh -lc './tools/project-brain ingest --objects-file /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/brain-retry-ingest-zymehtlp/objects.json --coverage-file /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/brain-retry-ingest-zymehtlp/coverage.json --repo-root /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/.scratch/brain-knowledge-workflow-validation/20261104T065347Z/w-t2-recheck/round-1/project --expected-repo-id demo --expected-revision-ref main --engine-sha be75896a18efc076150708882c8af453ee970672 > /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/brain-retry-ingest-zymehtlp/receipt.json' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import json, os, subprocess, sys ⏎ from pathlib import Path ⏎ root=Path.cwd() ⏎ work=Path('/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/brain-retry-ingest-zymehtlp') ⏎ receipt=json.loads((work/'receipt.json').read_text()) ⏎ assert receipt['ok'] is True and receipt['committed'] is True,receipt ⏎ assert receipt['expected_objects']==receipt['verified_objects']==[{'id':'insight.retry.entry-limit-change-risk','kind':'Insight'}],receipt ⏎ print('receipt',json.dumps(receipt,ensure_ascii=False)) ⏎ env=dict(os.environ) ⏎ env['PATH']=str(root/'tools')+os.pathsep+env['PATH'] ⏎ cmd=[sys.executable,str(root/'.agents/skills/demo-brain-ingest/scripts/finalize_ingest.py'),'--config',str(work/'finalization.json'),'--baseline',str(work/'baseline.json'),'--transaction-result',str(work/'receipt.json')] ⏎ result=subprocess.run(cmd,env=env,text=True,capture_output=True) ⏎ (work/'finalization-result.json').write_text(result.stdout) ⏎ print('finalizer_exit',result.r … (전체는 JSONL) `
- exit=0: `/bin/zsh -lc 'git status --short --branch ⏎ git diff --stat ⏎ git diff -- brain/objects/mappings/mapping.retry.immediate.json brain/objects/mappings/mapping.retry.scheduled.json .project-brain.json docs/retry-rules.md' `
- exit=0: `/bin/zsh -lc "./tools/project-brain search '재시도 제한 수정 시 즉시 실행과 예약 실행을 함께 확인해야 하는 이유' > /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/brain-retry-ingest-zymehtlp/advisory-recall.json ⏎ ./tools/python - <<'PY' ⏎ import json ⏎ from pathlib import Path ⏎ work=Path('/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/brain-retry-ingest-zymehtlp') ⏎ payload=json.loads((work/'advisory-recall.json').read_text()) ⏎ expected='insight.retry.entry-limit-change-risk' ⏎ advisories=payload.get('advisories',[]) ⏎ assert any(hit.get('object_id')==expected for hit in advisories),payload ⏎ obj=json.loads((Path.cwd()/'brain/objects/insights'/f'{expected}.json').read_text()) ⏎ assert obj['source_object_ids']==['mapping.retry.immediate','mapping.retry.scheduled'] ⏎ assert obj['evidence_refs']==['evref.retry.rules'] ⏎ assert obj['status']=='reviewed' and obj['insight_type']=='cross-cutting-risk' ⏎ report=json.loads((work/'report.json').read_text()) ⏎ report['receipt']=json.loads((work/'receipt.json').read_te … (전체는 JSONL) `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

검수된 Insight (로컬 원본: `w-t2-recheck/round-1/project/brain/objects/insights/insight.retry.entry-limit-change-risk.json`)로 직접 적재했습니다.

- 위험: 경로별 제한을 별도로 적용하므로, 수정 시 두 진입 경로를 함께 확인해야 누락을 줄일 수 있음.
- 범위: 문서의 합성 운영 규칙. 실제 코드·장치 동작은 미검증.
- 기존 경로별 근거 객체 두 개를 연결했으며 새 어휘는 만들지 않았습니다.

lint, 회귀 평가, 기존 테스트와 `advisories` 회상을 통과했습니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-ingest` 스킬을 적용해 확정된 교훈을 적재하겠습니다. 기존 경로별 근거 객체를 확인하고, 새 어휘 정의 없이 위험과 적용 범위를 남기겠습니다.


- initial 파일 해시 (로컬 원본: `w-t2-recheck/round-1/initial.sha256`), Git (로컬 원본: `w-t2-recheck/round-1/initial.git.txt`).
- before-recall 파일 해시 (로컬 원본: `w-t2-recheck/round-1/before-recall.sha256`), Git (로컬 원본: `w-t2-recheck/round-1/before-recall.git.txt`).
- after-recall 파일 해시 (로컬 원본: `w-t2-recheck/round-1/after-recall.sha256`), Git (로컬 원본: `w-t2-recheck/round-1/after-recall.git.txt`).
- before-recall → after-recall: 파일 해시 동일=True; Git 동일=True.
