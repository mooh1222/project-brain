> E3 당시 판정·관찰의 보존 사본이다. W-T1의 두 기록 세션은 개인 memory를 읽었으므로
> 이번 memory 비활성 통과 집계에서는 제외하고 재실행 결과로 교체한다.
> 작은 Markdown 산출물만 추적하며 JSONL·프로젝트·해시 원본은 로컬 전용이다.
> 링크는 추적 산출물로만 연결하고 원본 증거는 경로 텍스트로 표시했다.

# W-T2 round-1 관찰

## record

- Session: `01a1a558-e091-7dd0-bdc0-0994b7d4e07f`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](record.request.md), 기존 세션 JSONL (로컬 원본: `w-t2/round-1/record.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t2/round-1/record.events.jsonl`), [답변](record.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/ingest-tools.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/completeness-checklist.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/scope.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/object-model.md' `
- exit=0: `/bin/zsh -lc "sed -n '1,240p' .agents/skills/demo-brain-ingest/references/ingest-tools.md" `
- exit=0: `/bin/zsh -lc 'cat docs/retry-rules.md .project-brain.json' `
- exit=0: `/bin/zsh -lc 'rg --files brain .agents/skills/demo-brain-ingest | head -100' `
- exit=0: `/bin/zsh -lc 'git rev-parse main' `
- exit=0: `/bin/zsh -lc './tools/project-brain --help' `
- exit=0: `/bin/zsh -lc 'cat tools/project-brain tools/python .agents/skills/demo-brain-ingest/references/object-templates/kinds/Insight.template.json .agents/skills/demo-brain-ingest/references/object-templates/direct-coverage.template.json' `
- exit=0: `/bin/zsh -lc 'cat brain/objects/mappings/mapping.retry.immediate.json brain/objects/mappings/mapping.retry.scheduled.json brain/objects/evidence_refs/evref.retry.rules.json brain/raw/manifests/manifest.retry.rules.json brain/objects/domain/context.retry.json' `
- exit=0: `/bin/zsh -lc "sed -n '270,380p' .agents/skills/demo-brain-ingest/references/ingest-tools.md" `
- exit=0: `/bin/zsh -lc './tools/project-brain ingest --help' `
- exit=0: `/bin/zsh -lc "./tools/project-brain search '재시도 제한 즉시 실행 예약 실행'" `
- exit=0: `/bin/zsh -lc "sed -n '1,240p' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py" `
- exit=0: `/bin/zsh -lc "rg --files tools brain/checks .agents/skills/demo-brain-ingest/references | rg 'verification|test_|sitecustomize|finaliz'" `
- exit=0: `/bin/zsh -lc 'git -C /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3 rev-parse HEAD' `
- exit=0: `/bin/zsh -lc "./tools/python -c 'import project_brain; from pathlib import Path; print(Path(project_brain.__file__).resolve())'" `
- exit=0: `/bin/zsh -lc './tools/project-brain graph isolated' `
- exit=0: `/bin/zsh -lc "rg -n 'def |advisories|audit|checks|baseline|add_argument' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py" `
- exit=0: `/bin/zsh -lc 'cat tools/sitecustomize.py' `
- exit=2: `/bin/zsh -lc "rg -n 'def |precondition|repo_id|expected_repo|engine_sha' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/ingest.py /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/cli_ingest.py" `
- exit=0: `/bin/zsh -lc './tools/project-brain eval --help' `
- exit=0: `/bin/zsh -lc './tools/project-brain lint' `
- exit=0: `/bin/zsh -lc "sed -n '496,600p' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py" `
- exit=0: `/bin/zsh -lc "sed -n '668,718p' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py" `
- exit=0: `/bin/zsh -lc "rg -n 'expected_repo_id|engine_sha|repo_identity|canonical_repository' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/cli.py /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/repo*" `
- exit=1: `/bin/zsh -lc './tools/project-brain eval' `
- exit=1: `/bin/zsh -lc './tools/project-brain audit --no-fetch --write-stale-cache' `
- exit=0: `/bin/zsh -lc "sed -n '1,155p' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/eval_harness.py" `
- exit=0: `/bin/zsh -lc "sed -n '890,1015p' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/cli.py" `
- exit=0: `/bin/zsh -lc "rg -n 'Insight|scope|cross-cutting' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/schema.py /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/lint.py" `
- exit=0: `/bin/zsh -lc './tools/project-brain audit --help' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import hashlib,json,subprocess ⏎ from pathlib import Path ⏎ from datetime import datetime,timezone ⏎ from project_brain.coverage import normalize_coverage ⏎ from project_brain.schema import validate_object ⏎ root=Path.cwd() ⏎ report_dir=root/'brain/reports/retry-rules-ingest-20261104' ⏎ report_dir.mkdir(parents=True,exist_ok=False) ⏎ def save(name,data): ⏎     (report_dir/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\\n',encoding='utf-8') ⏎ now=datetime.now(timezone.utc).isoformat() ⏎ obj={ ⏎ 'id':'insight.retry.separate-limits-risk','kind':'Insight','schema_version':'0.1', ⏎ 'status':'reviewed','poc_priority':'P0','truth_role':'synthesis', ⏎ 'title':'再試行 / 재시도 제한 변경 시 즉시·예약 실행 경로 누락 위험', ⏎ 'created_at':now,'updated_at':now,'tags':['retry'], ⏎ 'evidence_refs':['evref.retry.rules'], ⏎ 'body':'즉시 실행과 예약 실행은 모두 최대 세 번 재시도하며, 각 경로가 재시도 제한을 별도로 적용한다. 제한을 수정할 때 한 진입 경로만 확인하면 다른 경로의 제한을 빠뜨릴 위험이 있으므로 두 진입 경로를 함께 확인해야 한다. docs/retry-rule … (전체는 JSONL) `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import json ⏎ from pathlib import Path ⏎ p=Path('brain/reports/retry-rules-ingest-20261104/objects.json') ⏎ objects=json.loads(p.read_text()) ⏎ objects[0]['title']='재시도 제한 변경 시 즉시·예약 실행 경로 누락 위험' ⏎ p.write_text(json.dumps(objects,ensure_ascii=False,indent=2)+'\\n') ⏎ PY" `
- exit=0: `/bin/zsh -lc './tools/project-brain ingest --objects-file brain/reports/retry-rules-ingest-20261104/objects.json --coverage-file brain/reports/retry-rules-ingest-20261104/coverage.json --repo-root "$PWD" --expected-repo-id demo --expected-revision-ref main --engine-sha be75896a18efc076150708882c8af453ee970672 > brain/reports/retry-rules-ingest-20261104/ingest-result.json' `
- exit=0: `/bin/zsh -lc 'cat brain/reports/retry-rules-ingest-20261104/ingest-result.json' `
- exit=1: `/bin/zsh -lc 'PATH="$PWD/tools:$PATH" ./tools/python .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py --config brain/reports/retry-rules-ingest-20261104/finalization-config.json --baseline brain/reports/retry-rules-ingest-20261104/baseline.json --transaction-result brain/reports/retry-rules-ingest-20261104/ingest-result.json > brain/reports/retry-rules-ingest-20261104/finalization-result.json' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import json ⏎ from pathlib import Path ⏎ r=json.loads(Path('brain/reports/retry-rules-ingest-20261104/finalization-result.json').read_text()) ⏎ print(json.dumps({'ok':r['ok'],'commands':{k:{'ok':v['ok'],'exit_code':v.get('exit_code'),'stderr':v.get('stderr','')} for k,v in r['commands'].items()},'isolation':r['isolation'],'recall_checks':r['recall_checks'],'errors':r['errors']},ensure_ascii=False,indent=2)) ⏎ PY" `
- exit=0: `/bin/zsh -lc './tools/project-brain show insight.retry.separate-limits-risk' `
- exit=0: `/bin/zsh -lc './tools/project-brain eval --scenarios brain/reports/retry-rules-ingest-20261104/eval-scenarios.json > brain/reports/retry-rules-ingest-20261104/targeted-eval-result.json' `
- exit=0: `/bin/zsh -lc "./tools/project-brain search '재시도 제한 수정할 때 두 진입 경로' > brain/reports/retry-rules-ingest-20261104/recall-result.json" `
- exit=0: `/bin/zsh -lc './tools/project-brain audit --no-fetch --no-stale > brain/reports/retry-rules-ingest-20261104/local-audit-result.json' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import hashlib,json,subprocess ⏎ from pathlib import Path ⏎ r=Path('brain/reports/retry-rules-ingest-20261104') ⏎ def load(n): return json.loads((r/n).read_text()) ⏎ source=load('source-check.json') ⏎ changed=[p for p,h in source['source_hashes'].items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()"'!=h] ⏎ assert not changed,changed ⏎ receipt=load('"'ingest-result.json') ⏎ assert receipt['committed'] and receipt['expected_objects']==receipt['verified_objects'] ⏎ recall=load('recall-result.json') ⏎ ids=[o['object_id'] for o in recall['advisories']] ⏎ assert 'insight.retry.separate-limits-risk' in ids,ids ⏎ eval_result=load('targeted-eval-result.json') ⏎ audit=load('local-audit-result.json') ⏎ assert audit['ok'],audit ⏎ print(json.dumps({'targeted_eval':eval_result,'advisory_ids':ids,'preserved_existing_sources':not changed,'local_audit_ok':audit['ok']},ensure_ascii=False,indent=2)) ⏎ summary={'stored':True,'object_id':'insight.retry.separat … (전체는 JSONL) `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

Brain에 reviewed Insight (로컬 원본: `w-t2/round-1/project/brain/objects/insights/insight.retry.separate-limits-risk.json`)로 저장했습니다.

- 각 경로가 제한을 별도로 적용하므로, 변경 시 두 진입 경로를 함께 확인해야 한다는 누락 위험을 기록했습니다.
- 기존 근거 객체 두 개를 연결하고, 적용 범위를 합성 운영 규칙으로 명시했습니다. 새 어휘는 만들지 않았습니다.

무결성과 두 경로의 주의사항 회상은 통과했습니다. 전체 검수는 기본 평가·테스트 파일과 `origin/main` 부재로 미완료입니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-ingest` 스킬로 확정된 교훈과 기존 근거 객체를 확인한 뒤, 위험과 적용 범위를 Brain에 적재하겠습니다.


- initial 파일 해시 (로컬 원본: `w-t2/round-1/initial.sha256`), Git (로컬 원본: `w-t2/round-1/initial.git.txt`).
