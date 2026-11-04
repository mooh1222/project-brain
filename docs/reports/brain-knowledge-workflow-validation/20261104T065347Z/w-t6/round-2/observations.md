> E3 당시 판정·관찰의 보존 사본이다. W-T1의 두 기록 세션은 개인 memory를 읽었으므로
> 이번 memory 비활성 통과 집계에서는 제외하고 재실행 결과로 교체한다.
> 작은 Markdown 산출물만 추적하며 JSONL·프로젝트·해시 원본은 로컬 전용이다.
> 링크는 추적 산출물로만 연결하고 원본 증거는 경로 텍스트로 표시했다.

# W-T6 round-2 관찰

## recall

- Session: `01a1a566-1813-71e1-9ef8-08c9f7c762e2`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](recall.request.md), 기존 세션 JSONL (로컬 원본: `w-t6/round-2/recall.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t6/round-2/recall.events.jsonl`), [답변](recall.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-query/SKILL.md' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/discovery.md' `
- exit=0: `/bin/zsh -lc 'cat .project-brain.json' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain --help' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft list' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval' `
- exit=0: `/bin/zsh -lc "./tools/project-brain search '예약 재시도 간격'" `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.scheduled' `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.scheduled-interval' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval --item interval' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval --item lag' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval --item concurrent-question' `
- exit=0: `/bin/zsh -lc 'nl -ba brain/drafts/retry-interval.json' `
- exit=0: `/bin/zsh -lc 'nl -ba docs/new-rule.md' `
- exit=0: `/bin/zsh -lc 'nl -ba brain/objects/mappings/mapping.retry.scheduled-interval.json' `
- exit=0: `/bin/zsh -lc './tools/project-brain show evref.retry.rules' `
- exit=0: `/bin/zsh -lc './tools/project-brain show context.retry' `
- exit=0: `/bin/zsh -lc './tools/project-brain show evref.retry.interval' `
- exit=0: `/bin/zsh -lc 'nl -ba brain/raw/sources/retry/new-rule.md' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc './tools/project-brain show manifest.retry.interval' `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

정식 지식에는 **“예약 실행의 재시도 간격은 8초이며, 최대 세 번 재시도한다는 횟수 규칙과 독립적이다”**가 반영돼 있습니다.

| 구분 | 현재 확인된 내용 | 출처 |
|---|---|---|
| **정식 지식(reviewed)** | `mapping.retry.scheduled-interval`에 8초 간격 규칙이 반영됨. 갱신: 2026-11-04 16:10:25 KST | 정식 객체 (로컬 원본: `w-t6/round-2/project/brain/objects/mappings/mapping.retry.scheduled-interval.json`), 보존 원문 (로컬 원본: `w-t6/round-2/project/brain/raw/sources/retry/new-rule.md`) |
| **조사 미결 — 초안(미검수 작업 기억)** | 화면 표시가 지연되는 원인(`lag`)은 미확인 | 초안의 해당 질문 (로컬 원본: `w-t6/round-2/project/brain/drafts/retry-interval.json`) |
| **조사 미결 — 초안(미검수 작업 기억)** | 재시도 간격과 화면 표시 동기화의 관계(`concurrent-question`)는 미확인 | 동시 조사자가 추가한 질문 (로컬 원본: `w-t6/round-2/project/brain/drafts/retry-interval.json`) |

정식 지식의 근거 사슬은 `evref.retry.interval → manifest.retry.interval → 보존 원문`입니다. 다만 **구현 코드와 실제 실행 간격은 검증되지 않았고, 8초 규칙으로 화면 표시 지연을 설명할 수는 없습니다.** 변경 이력도 `history_coverage=unsearched`로 남아 있습니다. 정식 객체의 검증 범위 (로컬 원본: `w-t6/round-2/project/brain/objects/mappings/mapping.retry.scheduled-interval.json`)

초안은 2026-11-04 16:11:10 KST 기준이며, 두 미결 항목에는 별도 근거 출처가 연결돼 있지 않습니다. 이번에는 읽기만 수행했고 Git 상태는 시작 시점과 같습니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-query` 스킬로 정식 지식과 조사 기록을 조회하고, 출처를 확인해 남은 미결과 구분하겠습니다. 파일은 변경하지 않겠습니다.


## record

- Session: `01a1a563-9516-77a3-9798-d6eb888107a9`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](record.request.md), 기존 세션 JSONL (로컬 원본: `w-t6/round-2/record.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t6/round-2/record.events.jsonl`), [답변](record.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat .project-brain.json' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/discovery.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/v2-format.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/ingest-tools.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/draft-materials.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft list' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/object-model.md' `
- exit=0: `/bin/zsh -lc 'git rev-parse HEAD' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/scope.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/completeness-checklist.md' `
- exit=0: `/bin/zsh -lc "sed -n '1,190p' .agents/skills/demo-brain-ingest/references/ingest-tools.md" `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval' `
- exit=0: `/bin/zsh -lc 'cat tools/project-brain tools/python' `
- exit=0: `/bin/zsh -lc 'rg --files brain docs tools .agents/skills/demo-brain-ingest/scripts .agents/skills/demo-brain-ingest/references/object-templates' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval --item lag' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval --item interval' `
- exit=0: `/bin/zsh -lc "./tools/project-brain search '예약 재시도 간격'" `
- exit=0: `/bin/zsh -lc 'cat tools/kw_cli.py' `
- exit=0: `/bin/zsh -lc 'cat docs/new-rule.md docs/retry-rules.md docs/time-study.md' `
- exit=0: `/bin/zsh -lc 'cat brain/objects/domain/context.retry.json brain/raw/manifests/manifest.retry.rules.json brain/objects/evidence_refs/evref.retry.rules.json brain/checks/test_existing_rules.py brain/eval_scenarios.json' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/update-rules.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/object-templates/direct-coverage.template.json .agents/skills/demo-brain-ingest/references/object-templates/kinds/EvidenceManifest.template.json .agents/skills/demo-brain-ingest/references/object-templates/kinds/EvidenceRef.template.json .agents/skills/demo-brain-ingest/references/object-templates/kinds/DomainMapping.template.json' `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.scheduled' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py .agents/skills/demo-brain-ingest/scripts/engine_python.py' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/judgment.md' `
- exit=0: `/bin/zsh -lc "sed -n '190,285p' .agents/skills/demo-brain-ingest/references/ingest-tools.md" `
- exit=0: `/bin/zsh -lc './tools/project-brain ingest --help' `
- exit=1: `/bin/zsh -lc './tools/project-brain --engine-identity' `
- exit=0: `/bin/zsh -lc './tools/project-brain graph isolated' `
- exit=0: `/bin/zsh -lc 'cat tools/sitecustomize.py' `
- exit=0: `/bin/zsh -lc "rg -n 'def capture_isolation_baseline|def run_finalization|project-brain|subprocess|audit|brain_root|lint' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py" `
- exit=0: `/bin/zsh -lc "./tools/python -c 'import project_brain, pathlib, subprocess; p=pathlib.Path(project_brain.__file__).resolve(); print(p); print(subprocess.check_output([\"git\",\"-C\",str(p.parent),\"rev-parse\",\"HEAD\"],text=True).strip())'" `
- exit=0: `/bin/zsh -lc './tools/project-brain draft prepare --help' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ from pathlib import Path ⏎ import tempfile,json ⏎ p=Path(tempfile.mkdtemp(prefix='retry-interval-ingest-')) ⏎ (p/'finalization.json').write_text(json.dumps({'recall_checks':[{'key':'scheduled-interval','query':'예약 실행 재시도 간격은 몇 초인가?','expected_object_ids':['mapping.retry.scheduled-interval'],'require_code_locators':False}],'intentional_terminal_ids':[]},ensure_ascii=False,indent=2)+'\\n') ⏎ print(p) ⏎ PY" `
- exit=0: `/bin/zsh -lc 'PATH="$PWD/tools:$PATH" ./tools/python .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py --validate-config /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/finalization.json' `
- exit=1: `/bin/zsh -lc './tools/project-brain draft prepare retry-interval --item interval --repo-root "$PWD" --target-revision 2d12b869a92c3f685f0806397982532197bc7d95 --out /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/materials' `
- exit=0: `/bin/zsh -lc 'PATH="$PWD/tools:$PATH" ./tools/python .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py --capture-baseline > /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/baseline.json' `
- exit=1: `/bin/zsh -lc 'cat /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/baseline.json /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/materials/materials.json' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft prepare retry-interval --item interval --repo-root "$PWD" --target-revision 2d12b869a92c3f685f0806397982532197bc7d95 --out /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/materials' `
- exit=0: `/bin/zsh -lc 'cat /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/materials/materials.json' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ from pathlib import Path ⏎ from datetime import datetime,timezone ⏎ import json,hashlib ⏎ p=Path('/private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb') ⏎ template=Path('.agents/skills/demo-brain-ingest/references/object-templates/kinds') ⏎ now=datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds') ⏎ raw='raw/sources/retry/new-rule.md' ⏎ source=Path('docs/new-rule.md').read_bytes() ⏎ assert source.decode() == '# 재시도 간격\\n예약 실행의 재시도 간격은 8초이다. 합성 운영 규칙으로 문장 단위 검토가 끝났다.\\n최대 횟수 세 번 규칙과는 독립된 간격 규칙이다.\\n' ⏎ manifest=json.loads((template/'EvidenceManifest.template.json').read_text()) ⏎ manifest.update(id='manifest.retry.interval',title='new-rule.md',locator=raw,captured_at=now,captured_by='codex:byte-copy',sensitivity='public',acl=['all'],tags=['retry','scheduled-interval'],created_at=now,updated_at=now) ⏎ ref=json.loads((template/'EvidenceRef.template.json').read_text()) ⏎ ref.update(id='evref.retry.in … (전체는 JSONL) `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ from pathlib import Path ⏎ import json ⏎ from project_brain.schema import validate_object ⏎ p=Path('/private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb') ⏎ objects=json.loads((p/'objects.json').read_text()) ⏎ for obj in objects: ⏎     validate_object(obj) ⏎ print('3 objects: schema pass') ⏎ PY" `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ from pathlib import Path ⏎ import hashlib,json ⏎ p=Path('/private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb') ⏎ r=json.loads((p/'verification.json').read_text()) ⏎ r['verification']['rule']='원문은 예약 실행의 재시도 간격을 8초로 명시한다.' ⏎ (p/'verification.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\\n') ⏎ source=Path('docs/new-rule.md').read_bytes() ⏎ assert hashlib.sha256(source).hexdigest()==r['source_intake']['source_sha256'] ⏎ target=Path('brain/raw/sources/retry/new-rule.md') ⏎ target.parent.mkdir(parents=True,exist_ok=True) ⏎ with target.open('xb') as f: f.write(source) ⏎ assert target.read_bytes()==source ⏎ print('원문 동일 bytes 보존:',target) ⏎ PY" `
- exit=0: `/bin/zsh -lc './tools/project-brain ingest --objects-file /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/objects.json --coverage-file /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/coverage.json --repo-root "$PWD" --expected-repo-id demo --expected-revision-ref main --engine-sha be75896a18efc076150708882c8af453ee970672 > /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/receipt.json' `
- exit=0: `/bin/zsh -lc 'cat /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/receipt.json' `
- exit=0: `/bin/zsh -lc "./tools/python -m unittest discover -s brain/checks -p 'test_*.py'" `
- exit=0: `/bin/zsh -lc 'PATH="$PWD/tools:$PATH" ./tools/python .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py --config /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/finalization.json --baseline /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/baseline.json --transaction-result /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/receipt.json > /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/finalized.json' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ from pathlib import Path ⏎ import json ⏎ p=Path('/private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/finalized.json') ⏎ r=json.loads(p.read_text()) ⏎ print(json.dumps({k:v for k,v in r.items() if k"'!='"'commands'},ensure_ascii=False,indent=2)) ⏎ for k,v in r.get('commands',{}).items(): ⏎  print(json.dumps({'command':k,**v},ensure_ascii=False,indent=2)) ⏎ PY" `
- exit=0: `/bin/zsh -lc "rg -n 'limits|source_keys' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/draft.py" `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ from pathlib import Path ⏎ import json ⏎ p=Path('/private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb') ⏎ patch={'resume_summary':'원문 docs/new-rule.md에서 확인하고 사용자가 검토·승인한 예약 실행 재시도 간격 8초를 reviewed 정식 지식 mapping.retry.scheduled-interval로 반영했다. 원문 근거 evref.retry.interval → manifest.retry.interval, 보존 원문 raw/sources/retry/new-rule.md. 표시 지연 원인(lag)은 미결이며 간격 규칙만으로 설명할 수 없다. history_coverage=unsearched. 어휘 변경 없음. 적재 후 무결성·회귀 평가·계약 회상·고립 객체 검사 통과.', 'sources':[{'op':'replace','value':{'key':'rule','kind':'document','locator':{'path':'docs/new-rule.md','section':'재시도 간격'},'quote':'예약 실행의 재시도 간격은 8초이다.','context':'사용자가 이번 요청에서 이 문장을 검토·승인한 운영 규칙이라고 명시했다. 원문 전체를 직접 확인하고 동일 bytes를 brain/raw/sources/retry/new-rule.md에 보존했다.'}},{'op':'add','value':{'key':'formal-interval','kind':'object','locator':{'object_id':'mapping.retry.scheduled-interval'},'context':'이번 적재의 실제 reviewed DomainMapping. 간격 규칙만 설명하며 표시 지연 원인은 설명하지 않는다.'}}] … (전체는 JSONL) `
- exit=1: `/bin/zsh -lc './tools/project-brain draft update retry-interval --expected-sha 25ce7e1cc5d7cb79f141e3fe1c57dfa94dc181dc010104cac790acfd831c691b --patch-file /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/draft-patch.json' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval --item interval' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval --item lag' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval --item concurrent-question' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ from pathlib import Path ⏎ import json ⏎ p=Path('/private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/draft-patch.json') ⏎ r=json.loads(p.read_text()) ⏎ r['resume_summary']=r['resume_summary'].replace('표시 지연 원인(lag)은 미결이며 간격 규칙만으로 설명할 수 없다.','표시 지연 원인(lag)과 동시 조사자가 추가한 간격·화면 표시 동기화 관계(concurrent-question)는 모두 미결이다. 8초 간격 규칙만으로 설명할 수 없다.') ⏎ r['items'][0]['value']['text']=r['items'][0]['value']['text'].replace('남은 미결은 lag(화면 표시 지연 원인)이다.','남은 미결은 lag(화면 표시 지연 원인)와 concurrent-question(재시도 간격과 화면 표시 동기화 관계)이다.') ⏎ r['items'][1]['value']['text']='화면 표시 지연 원인은 미확인이다.' ⏎ r['items'][1]['value']['limits']='관련 정식 지식 mapping.retry.scheduled-interval은 예약 실행 재시도 간격 8초만 확인한다. 표시 지연 원인과 동기화 관계(concurrent-question)는 설명하지 않으므로 질문을 유지한다.' ⏎ p.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\\n') ⏎ PY" `
- exit=0: `/bin/zsh -lc './tools/project-brain draft update retry-interval --expected-sha c3107d27699d3913f61a53f9c32e283370a1ce8d96e1eb74c4c91ab2c2fa5f91 --patch-file /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-nx5ya7pb/draft-patch.json' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft lint retry-interval' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft lint' `
- exit=0: `/bin/zsh -lc 'git diff --stat' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ from pathlib import Path ⏎ import json,subprocess ⏎ root=Path.cwd() ⏎ d=json.loads(Path('brain/drafts/retry-interval.json').read_text()) ⏎ items={x['key']:x for x in d['items']} ⏎ assert items['lag']['kind']=='question' and items['lag']['text']=='화면 표시 지연 원인은 미확인이다.' ⏎ assert items['concurrent-question']=={'key':'concurrent-question','kind':'question','text':'동시 조사자가 추가: 재시도 간격과 화면 표시 동기화 관계는 아직 미확인이다.','source_keys':[]} ⏎ assert 'mapping.retry.scheduled-interval' in items['interval']['text'] ⏎ assert 'formal-interval' in items['interval']['source_keys'] ⏎ for p in ['brain/objects/mappings/mapping.retry.immediate.json','brain/objects/mappings/mapping.retry.scheduled.json','docs/new-rule.md']: ⏎  assert Path(p).read_bytes()==subprocess.check_output(['git','show','HEAD:'+p]) ⏎ assert Path('brain/raw/sources/retry/new-rule.md').read_bytes()==Path('docs/new-rule.md').read_bytes() ⏎ p=Path('/private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retr … (전체는 JSONL) `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

예약 재시도 간격 **8초**를 승인된 원문 근거와 함께 정식 지식(`mapping.retry.scheduled-interval`, reviewed)으로 반영했습니다.

조사 기록에 실제 반영 객체와 남은 미결을 연결했습니다. 표시 지연 원인과 동시 추가된 화면 동기화 관계 질문을 모두 보존했고, 새 어휘는 만들지 않았습니다.

무결성·검색 회수·회귀 평가·기존 검사 모두 통과했습니다.


실행자가 밝힌 스킬/진행 맥락:

관련 조사 기록과 원문을 확인한 뒤, 확인된 간격 규칙만 정식 지식에 반영하겠습니다. `demo-brain-draft`와 `demo-brain-ingest` 스킬로 조사 기록에 반영 결과와 남은 질문을 연결하겠습니다.


- initial 파일 해시 (로컬 원본: `w-t6/round-2/initial.sha256`), Git (로컬 원본: `w-t6/round-2/initial.git.txt`).
- before-recall 파일 해시 (로컬 원본: `w-t6/round-2/before-recall.sha256`), Git (로컬 원본: `w-t6/round-2/before-recall.git.txt`).
- after-recall 파일 해시 (로컬 원본: `w-t6/round-2/after-recall.sha256`), Git (로컬 원본: `w-t6/round-2/after-recall.git.txt`).
- before-recall → after-recall: 파일 해시 동일=True; Git 동일=True.
