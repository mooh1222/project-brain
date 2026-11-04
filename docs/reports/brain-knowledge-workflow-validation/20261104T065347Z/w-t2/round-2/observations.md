> E3 당시 판정·관찰의 보존 사본이다. W-T1의 두 기록 세션은 개인 memory를 읽었으므로
> 이번 memory 비활성 통과 집계에서는 제외하고 재실행 결과로 교체한다.
> 작은 Markdown 산출물만 추적하며 JSONL·프로젝트·해시 원본은 로컬 전용이다.
> 링크는 추적 산출물로만 연결하고 원본 증거는 경로 텍스트로 표시했다.

# W-T2 round-2 관찰

## record

- Session: `01a1a558-e40e-79d1-ba9b-6a60d0a6e25e`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](record.request.md), 기존 세션 JSONL (로컬 원본: `w-t2/round-2/record.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t2/round-2/record.events.jsonl`), [답변](record.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'pwd && git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat docs/retry-rules.md && cat .project-brain.json' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/ingest-tools.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/completeness-checklist.md && rg --files brain tools | head -70' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md && cat .agents/skills/demo-brain-ingest/references/scope.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/object-model.md' `
- exit=0: `/bin/zsh -lc "sed -n '105,185p' .agents/skills/demo-brain-ingest/references/object-model.md && sed -n '1,230p' .agents/skills/demo-brain-ingest/references/ingest-tools.md" `
- exit=0: `/bin/zsh -lc 'cat brain/objects/domain/context.retry.json brain/objects/mappings/mapping.retry.immediate.json brain/objects/mappings/mapping.retry.scheduled.json brain/objects/evidence_refs/evref.retry.rules.json brain/raw/manifests/manifest.retry.rules.json && cat tools/project-brain tools/python && rg --files .agents/skills/demo-brain-ingest/scripts' `
- exit=1: `/bin/zsh -lc "sed -n '270,385p' .agents/skills/demo-brain-ingest/references/ingest-tools.md && cat .agents/skills/demo-brain-ingest/references/object-templates/kinds/insight.template.json .agents/skills/demo-brain-ingest/references/object-templates/coverage.direct.template.json" `
- exit=0: `/bin/zsh -lc "sed -n '1,250p' .agents/skills/demo-brain-ingest/scripts/run_ingest.sh && sed -n '1,200p' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py" `
- exit=0: `/bin/zsh -lc "./tools/project-brain --help && ./tools/project-brain ingest --help && ./tools/project-brain search '재시도 제한'" `
- exit=0: `/bin/zsh -lc "cat tools/sitecustomize.py && rg --files .agents/skills/demo-brain-ingest/references/object-templates | rg coverage && rg -n 'add_argument|project-brain|test_real|unittest|audit|advisories' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py" `
- exit=0: `/bin/zsh -lc "sed -n '1,160p' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.sh && rg -n 'Insight|scope|insight_type' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/schema.py && rg -n 'preconditions|expected_repo|normalize_coverage' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/cli.py" `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.immediate && ./tools/project-brain show mapping.retry.scheduled && ./tools/project-brain graph isolated && git rev-parse HEAD && git -C /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3 rev-parse HEAD' `
- exit=0: `/bin/zsh -lc "cat .agents/skills/demo-brain-ingest/references/object-templates/direct-coverage.template.json && sed -n '490,520p' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py && sed -n '560,615p' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py && sed -n '660,720p' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py && sed -n '730,820p' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py" `
- exit=1: `/bin/zsh -lc "./tools/project-brain audit --no-fetch && ./tools/project-brain eval && rg --files brain . | rg '(checks|test_|gitignore)' && sed -n '45,118p' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/cli.py" `
- exit=0: `/bin/zsh -lc "rg -n 'default_branch|origin/main|environ|DEFAULT' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/{cli.py,stale_check.py,config.py,audit.py} && cat .gitignore && ./tools/project-brain index rebuild --help" `
- exit=1: `/bin/zsh -lc "./tools/project-brain audit --help && ./tools/project-brain eval && rg --files --hidden brain | sort && sed -n '45,118p' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/cli.py" `
- exit=0: `/bin/zsh -lc "sed -n '45,115p' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/cli.py && rg --files --hidden brain && sed -n '1600,1658p' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/cli.py && rg -n 'preconditions|engine_sha' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/ingest.py" `
- exit=0: `/bin/zsh -lc 'git remote -v && git status --short --branch && ./tools/project-brain lint && ./tools/project-brain audit --no-stale --no-fetch' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import json ⏎ import tempfile ⏎ from pathlib import Path ⏎ from datetime import datetime, timezone ⏎ from project_brain.coverage import normalize_coverage ⏎ root = Path.cwd() ⏎ work = Path(tempfile.mkdtemp(prefix='retry-insight-ingest-')) ⏎ obj_id = 'insight.retry.cross-path-limit-change' ⏎ obj = { ⏎ 'id':obj_id, 'kind':'Insight', 'schema_version':'0.1', ⏎ 'status':'reviewed', 'poc_priority':'P0', 'truth_role':'synthesis', ⏎ 'title':'재시도 제한 변경 시 즉시 실행·예약 실행의 누락 위험', ⏎ 'created_at':datetime.now(timezone.utc).isoformat(), 'updated_at':datetime.now(timezone.utc).isoformat(), ⏎ 'tags':['retry'], 'evidence_refs':['evref.retry.rules'], ⏎ 'body':'즉시 실행과 예약 실행은 각각 최대 세 번의 재시도 제한을 별도로 적용한다. 한 경로의 제한만 수정하면 다른 경로의 확인·수정을 누락할 위험이 있으므로, 재시도 제한을 변경할 때는 두 진입 경로를 함께 확인해야 한다.', ⏎ 'source_object_ids':['mapping.retry.immediate','mapping.retry.scheduled'], ⏎ 'insight_type':'cross-cutting-risk', ⏎ 'scope':'docs/retry-rules.md의 합성 운영 규칙에 따른 즉시 실행·예약 실행의 재시도 제한 변경과 검토. … (전체는 JSONL) `
- exit=0: `/bin/zsh -lc './tools/python .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py --validate-config /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-insight-ingest-asge6t_v/finalization.json' `
- exit=0: `/bin/zsh -lc './tools/project-brain ingest --objects-file /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-insight-ingest-asge6t_v/objects.json --coverage-file /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-insight-ingest-asge6t_v/coverage.json --repo-root /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/.scratch/brain-knowledge-workflow-validation/20261104T065347Z/w-t2/round-2/project --expected-repo-id demo --expected-revision-ref main --engine-sha be75896a18efc076150708882c8af453ee970672 > /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-insight-ingest-asge6t_v/receipt.json' `
- exit=0: `/bin/zsh -lc 'cat /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-insight-ingest-asge6t_v/receipt.json && ./tools/project-brain index rebuild' `
- exit=1: `/bin/zsh -lc "./tools/python -m unittest discover -s brain/checks -p 'test_*.py'" `
- exit=0: `/bin/zsh -lc './tools/python .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py --validate-transaction /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-insight-ingest-asge6t_v/receipt.json && ./tools/project-brain show insight.retry.cross-path-limit-change && git status --short --branch' `
- exit=0: `/bin/zsh -lc "./tools/project-brain lint && ./tools/project-brain search '재시도 제한 변경 시 즉시 실행과 예약 실행을 함께 확인해야 하는 이유' && ./tools/project-brain graph isolated" `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import hashlib ⏎ import json ⏎ import subprocess ⏎ from pathlib import Path ⏎ root=Path.cwd() ⏎ work=Path('/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-insight-ingest-asge6t_v') ⏎ def call(*args): ⏎     p=subprocess.run(args,capture_output=True,text=True) ⏎     try: payload=json.loads(p.stdout) ⏎     except ValueError: payload=None ⏎     return {'exit_code':p.returncode,'payload':payload,'stderr':p.stderr} ⏎ query='재시도 제한 변경 시 즉시 실행과 예약 실행을 함께 확인해야 하는 이유' ⏎ recall=call('./tools/project-brain','search',query) ⏎ payload=recall['payload'] ⏎ assert payload['ok'] and any(x['object_id']=='insight.retry.cross-path-limit-change' for x in payload['advisories']) ⏎ assert {'mapping.retry.immediate','mapping.retry.scheduled'} <= {x['object_id'] for x in payload['results']} ⏎ receipt=json.loads((work/'receipt.json').read_text()) ⏎ assert receipt['committed'] and receipt['expected_objects']==receipt['verified_objects'] ⏎ checks={ ⏎ 'lint':call('./too … (전체는 JSONL) `
- exit=0: `/bin/zsh -lc 'git status --short --branch && git diff --stat && git diff -- docs/retry-rules.md brain/objects/domain/context.retry.json brain/objects/mappings/mapping.retry.immediate.json brain/objects/mappings/mapping.retry.scheduled.json brain/objects/evidence_refs/evref.retry.rules.json brain/raw/manifests/manifest.retry.rules.json' `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

Brain Insight (로컬 원본: `w-t2/round-2/project/brain/objects/insights/insight.retry.cross-path-limit-change.json`)를 `reviewed`로 저장했습니다.

- 두 경로의 기존 근거 객체를 연결했습니다.
- 각 경로가 제한을 별도로 적용하므로, 변경 시 두 진입 경로를 함께 확인해야 한다는 위험과 적용 범위를 기록했습니다.
- 합성 문서 규칙이며 실제 구현은 미검증임을 명시했습니다. 새 어휘는 만들지 않았습니다.

무결성·검색 회상은 통과했습니다. 전체 검증은 기준 ref와 평가·테스트 자료 부재로 미완료입니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-ingest` 스킬로 확정된 교훈을 적재하겠습니다. 문서와 각 경로의 기존 근거 객체를 확인해, 위험과 적용 범위를 연결하겠습니다.


- initial 파일 해시 (로컬 원본: `w-t2/round-2/initial.sha256`), Git (로컬 원본: `w-t2/round-2/initial.git.txt`).
