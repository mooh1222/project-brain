> E3 당시 판정·관찰의 보존 사본이다. W-T1의 두 기록 세션은 개인 memory를 읽었으므로
> 이번 memory 비활성 통과 집계에서는 제외하고 재실행 결과로 교체한다.
> 작은 Markdown 산출물만 추적하며 JSONL·프로젝트·해시 원본은 로컬 전용이다.
> 링크는 추적 산출물로만 연결하고 원본 증거는 경로 텍스트로 표시했다.

# W-T6 round-1 관찰

## recall

- Session: `01a1a564-fe94-7bc1-94d9-adf7acd43569`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](recall.request.md), 기존 세션 JSONL (로컬 원본: `w-t6/round-1/recall.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t6/round-1/recall.events.jsonl`), [답변](recall.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-query/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/discovery.md' `
- exit=0: `/bin/zsh -lc 'cat .project-brain.json' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft list' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval' `
- exit=0: `/bin/zsh -lc './tools/project-brain search "예약 재시도 간격"' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval --item interval' `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.scheduled' `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.interval' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval --item lag' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval --item concurrent-question' `
- exit=0: `/bin/zsh -lc 'rg --files brain/objects brain/raw docs brain/drafts' `
- exit=0: `/bin/zsh -lc './tools/project-brain show evref.retry.rules' `
- exit=0: `/bin/zsh -lc './tools/project-brain show evref.retry.interval' `
- exit=0: `/bin/zsh -lc 'nl -ba docs/new-rule.md' `
- exit=0: `/bin/zsh -lc 'nl -ba docs/time-study.md' `
- exit=0: `/bin/zsh -lc 'nl -ba brain/raw/sources/retry/new-rule.md' `
- exit=0: `/bin/zsh -lc 'nl -ba docs/retry-rules.md' `
- exit=0: `/bin/zsh -lc 'nl -ba brain/drafts/retry-interval.json' `
- exit=0: `/bin/zsh -lc './tools/project-brain show manifest.retry.interval' `
- exit=0: `/bin/zsh -lc './tools/project-brain show manifest.retry.rules' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

현재 **8초 간격 규칙은 정식 반영됐고, 화면 표시 지연 관련 조사 두 건은 미결**입니다.

| 구분 | 확인 내용과 출처 |
|---|---|
| **정식 지식 · reviewed** | 예약 실행의 재시도 간격은 **8초**이며, 최대 세 번이라는 횟수 제한과 독립된 규칙입니다. 정식 객체는 mapping.retry.interval (로컬 원본: `w-t6/round-1/project/brain/objects/mappings/mapping.retry.interval.json`)입니다. 근거 사슬은 `evref.retry.interval → manifest.retry.interval → 보존 원문`이며, 원문 2행 (로컬 원본: `w-t6/round-1/project/brain/raw/sources/retry/new-rule.md`)에서도 확인됩니다. |
| **조사 미결 · 초안(미검수 작업 기억)** | **화면 표시 지연의 원인**은 미확인입니다. 8초 규칙만으로 지연 원인을 설명할 수 없다고 명시돼 있습니다. 초안 `lag` (로컬 원본: `w-t6/round-1/project/brain/drafts/retry-interval.json`) |
| **조사 미결 · 초안(미검수 작업 기억)** | **재시도 간격과 화면 표시 동기화의 관계**도 미확인입니다. 동시 조사자가 추가한 질문으로 보존돼 있습니다. 초안 `concurrent-question` (로컬 원본: `w-t6/round-1/project/brain/drafts/retry-interval.json`) |

초안 갱신 시각은 **2026-11-04 16:10:04 +09:00**입니다. 두 미결 항목에는 연결된 원문 출처가 없습니다. 별도 시간 경계 조사 원문 (로컬 원본: `w-t6/round-1/project/docs/time-study.md`)에는 샘플 A에서 서버 응답 경계가 표시 시각보다 2초 앞섰다는 관찰이 있지만, 네트워크 지연 가설은 미확인이며 추가 표본과 시계 동기화 조건도 없습니다.

정식화 범위는 **문서 기반 합성 운영 규칙**입니다. 실제 구현·장치 실행·즉시 실행 간격은 검증되지 않았습니다.

읽기만 수행했으며, 시작·종료 시 Git 변경 목록은 동일합니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-query` 스킬로 예약 재시도 간격의 정식 지식과 조사 미결을 조회하겠습니다. 출처를 구분해 확인하고, 파일은 변경하지 않겠습니다.


## record

- Session: `01a1a563-0695-7641-80e0-ea4566ee22f0`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](record.request.md), 기존 세션 JSONL (로컬 원본: `w-t6/round-1/record.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t6/round-1/record.events.jsonl`), [답변](record.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat .project-brain.json' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md .agents/skills/demo-brain-draft/references/discovery.md .agents/skills/demo-brain-draft/references/v2-format.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/draft-materials.md .agents/skills/demo-brain-ingest/references/ingest-tools.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/object-model.md .agents/skills/demo-brain-ingest/references/scope.md .agents/skills/demo-brain-ingest/references/completeness-checklist.md' `
- exit=0: `/bin/zsh -lc "rg --files -g AGENTS.md -g '"'!'"\\.git' -g 'project-code-verification.md'" `
- exit=0: `/bin/zsh -lc 'git rev-parse main' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft list' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/object-model.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/ingest-tools.md' `
- exit=0: `/bin/zsh -lc 'rg --files brain docs .agents/skills/demo-brain-ingest/scripts' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval' `
- exit=0: `/bin/zsh -lc './tools/project-brain --help' `
- exit=0: `/bin/zsh -lc "sed -n '235,365p' .agents/skills/demo-brain-ingest/references/ingest-tools.md" `
- exit=0: `/bin/zsh -lc 'cat docs/new-rule.md docs/retry-rules.md docs/time-study.md brain/objects/mappings/mapping.retry.scheduled.json brain/objects/mappings/mapping.retry.immediate.json brain/objects/domain/context.retry.json brain/raw/manifests/manifest.retry.rules.json brain/objects/evidence_refs/evref.retry.rules.json brain/checks/test_existing_rules.py brain/eval_scenarios.json' `
- exit=0: `/bin/zsh -lc 'cat tools/project-brain tools/python' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/update-rules.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval --item interval' `
- exit=0: `/bin/zsh -lc './tools/python .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py --help' `
- exit=1: `/bin/zsh -lc './tools/project-brain --engine-identity' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval --item lag' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py .agents/skills/demo-brain-ingest/scripts/engine_python.py' `
- exit=0: `/bin/zsh -lc 'cat tools/kw_cli.py' `
- exit=1: `/bin/zsh -lc 'cat .agents/skills/demo-brain-ingest/references/object-templates/coverage.direct.template.json .agents/skills/demo-brain-ingest/references/judgment.md' `
- exit=0: `/bin/zsh -lc 'git -C /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3 rev-parse HEAD' `
- exit=0: `/bin/zsh -lc './tools/project-brain graph isolated' `
- exit=0: `/bin/zsh -lc './tools/project-brain ingest --help' `
- exit=0: `/bin/zsh -lc "sed -n '380,625p' .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py" `
- exit=0: `/bin/zsh -lc "sed -n '1,180p' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/coverage.py" `
- exit=0: `/bin/zsh -lc "rg -n 'def ingest|raw_|manifest|locator' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/ingest.py" `
- exit=0: `/bin/zsh -lc 'rg --files .agents/skills/demo-brain-ingest/references/object-templates' `
- exit=0: `/bin/zsh -lc "./tools/python -c 'import project_brain; print(project_brain.__file__)'" `
- exit=0: `/bin/zsh -lc './tools/project-brain draft prepare retry-interval --help' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import json, tempfile ⏎ from pathlib import Path ⏎ from datetime import datetime ⏎ from zoneinfo import ZoneInfo ⏎ from project_brain.coverage import normalize_coverage ⏎ out=Path(tempfile.mkdtemp(prefix='retry-interval-ingest-')) ⏎ now=datetime.now(ZoneInfo('Asia/Seoul')).isoformat() ⏎ common=dict(schema_version='0.1', status='reviewed', poc_priority='P0', created_at=now, updated_at=now, tags=['retry'], evidence_refs=[]) ⏎ objects=[ ⏎  dict(common,id='manifest.retry.interval',kind='EvidenceManifest',truth_role='source',title='new-rule.md',source_type='spec',locator='raw/sources/retry/new-rule.md',captured_at=now,captured_by='project-brain/source-copy',sensitivity='public',acl=['all'],redaction_status='approved'), ⏎  dict(common,id='evref.retry.interval',kind='EvidenceRef',truth_role='reference',title='예약 실행 재시도 8초 간격 원문',evidence_manifest_id='manifest.retry.interval',ref_type='spec_section',locator={'path':'raw/sources/retry/new-rule.md','sectio … (전체는 JSONL) `
- exit=0: `/bin/zsh -lc './tools/python .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py --validate-config /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55/finalization.json' `
- exit=1: `/bin/zsh -lc './tools/project-brain draft prepare retry-interval --item interval --repo-root /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/.scratch/brain-knowledge-workflow-validation/20261104T065347Z/w-t6/round-1/project --target-revision 51d2c24aa7f527824ceff11890024df69fde3959 --out /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55/materials' `
- exit=0: `/bin/zsh -lc 'PATH="$PWD/tools:$PATH" ./tools/python .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py --capture-baseline > /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55/baseline.json ⏎ cat /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55/baseline.json' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft prepare retry-interval --item interval --repo-root /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/.scratch/brain-knowledge-workflow-validation/20261104T065347Z/w-t6/round-1/project --target-revision 51d2c24aa7f527824ceff11890024df69fde3959 --out /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55/materials' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import hashlib,json ⏎ from pathlib import Path ⏎ out=Path('/private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55') ⏎ packet=json.loads((out/'materials/materials.json').read_text()) ⏎ print(json.dumps(packet,ensure_ascii=False,indent=2)) ⏎ source=Path('docs/new-rule.md').read_bytes() ⏎ assert '예약 실행의 재시도 간격은 8초이다.' in source.decode() ⏎ assert '최대 횟수 세 번 규칙과는 독립된 간격 규칙이다.' in source.decode() ⏎ paths=['docs/new-rule.md','docs/retry-rules.md','docs/time-study.md','brain/objects/mappings/mapping.retry.immediate.json','brain/objects/mappings/mapping.retry.scheduled.json','brain/objects/domain/context.retry.json','brain/raw/manifests/manifest.retry.rules.json','brain/objects/evidence_refs/evref.retry.rules.json','brain/checks/test_existing_rules.py','brain/eval_scenarios.json'] ⏎ (out/'preserved-hashes.json').write_text(json.dumps({p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths},indent=2)+'\\n') ⏎ tar … (전체는 JSONL) `
- exit=0: `/bin/zsh -lc './tools/project-brain ingest --objects-file /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55/objects.json --coverage-file /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55/coverage.json --repo-root /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/.scratch/brain-knowledge-workflow-validation/20261104T065347Z/w-t6/round-1/project --expected-repo-id demo --expected-revision-ref main --engine-sha be75896a18efc076150708882c8af453ee970672 > /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55/ingest-result.json ⏎ cat /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55/ingest-result.json' `
- exit=0: `/bin/zsh -lc 'PATH="$PWD/tools:$PATH" ./tools/python .agents/skills/demo-brain-ingest/scripts/finalize_ingest.py --config /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55/finalization.json --baseline /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55/baseline.json --transaction-result /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55/ingest-result.json > /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55/finalization-result.json ⏎ cat /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55/finalization-result.json' `
- exit=1: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import json ⏎ from pathlib import Path ⏎ out=Path('/private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55') ⏎ result=json.loads((out/'ingest-result.json').read_text()) ⏎ final=json.loads((out/'finalization-result.json').read_text()) ⏎ assert result['ok'] and result['committed'] and result['expected_objects']==result['verified_objects'] ⏎ assert final['ok'] and final['isolation']['unexpected_new_ids']==[] ⏎ patch={ ⏎  'resume_summary':'원문 docs/new-rule.md와 사용자 승인을 확인한 8초 간격 규칙만 reviewed 정식 지식 mapping.retry.interval로 반영했다(근거 evref.retry.interval → manifest.retry.interval, 원문 보존 raw/sources/retry/new-rule.md). 최대 세 번 횟수 제한 지식은 보존했다. 남은 미결은 lag: 화면 표시 지연 원인은 여전히 미확인이다. 간격 규칙으로 지연 원인을 설명하거나 조사를 닫지 않는다. 새 어휘 없음. history_coverage=unsearched. lint·eval 2건·기존 코퍼스 검사·회상·신규 고립 0건 확인 완료. 검색 검증은 프로젝트 도구에 설정된 stub 임베딩 기준이다.', ⏎  'sources':[ ⏎   {'op':'replace','value':{'key':'rule','kind':'document','locator':{'path':'docs/new- … (전체는 JSONL) `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval --item interval' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval --item lag' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-interval --item concurrent-question' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import json ⏎ from pathlib import Path ⏎ path=Path('/private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55/draft-patch.json') ⏎ patch=json.loads(path.read_text()) ⏎ patch['resume_summary']=patch['resume_summary'].replace('남은 미결은 lag: 화면 표시 지연 원인은 여전히 미확인이다.','남은 미결은 lag: 화면 표시 지연 원인, concurrent-question: 재시도 간격과 화면 표시 동기화 관계이며 둘 다 아직 미확인이다. 동시 조사자가 추가한 질문을 그대로 보존했다.') ⏎ path.write_text(json.dumps(patch,ensure_ascii=False,indent=2)+'\\n') ⏎ PY ⏎ ./tools/project-brain draft update retry-interval --expected-sha ee9db8864b492f820a8ac6e6b69d9cf91ebaaa04c3dba01f6a68d140245c8e6b --patch-file /private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55/draft-patch.json" `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'git diff -- brain/drafts/retry-interval.json' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft lint' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import hashlib,json ⏎ from pathlib import Path ⏎ out=Path('/private/var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-interval-ingest-eqdzqk55') ⏎ old=json.loads((out/'preserved-hashes.json').read_text()) ⏎ assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in old.items()) ⏎ assert Path('docs/new-rule.md').read_bytes()==Path('brain/raw/sources/retry/new-rule.md').read_bytes() ⏎ draft=json.loads(Path('brain/drafts/retry-interval.json').read_text()) ⏎ items={i['key']:i for i in draft['items']} ⏎ assert items['lag']['kind']=='question' ⏎ assert items['concurrent-question']=={'key':'concurrent-question','kind':'question','text':'동시 조사자가 추가: 재시도 간격과 화면 표시 동기화 관계는 아직 미확인이다。'.replace('。','.'),'source_keys':[]} ⏎ assert any(s['kind']=='object' and s['locator']['object_id']=='mapping.retry.interval' for s in draft['sources']) ⏎ assert not list(Path('brain/objects/domain').glob('g.*.json')) ⏎ print(json.dumps({'ok':True,'p … (전체는 JSONL) `
- exit=0: `/bin/zsh -lc './tools/project-brain draft lint retry-interval' `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

승인된 **예약 재시도 간격 8초**만 정식 지식 `mapping.retry.interval`에 반영했습니다.

조사 기록에는 실제 반영 객체와 원문 근거를 연결했습니다. 표시 지연 원인 질문과 동시 추가된 동기화 관계 질문은 미결로 보존했습니다. 기존 세 번 제한은 유지했고, 새 어휘는 만들지 않았습니다.

lint·평가·코퍼스·회상 검사를 통과했습니다. 회상 검증은 프로젝트의 stub 임베딩 기준입니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-draft`와 `demo-brain-ingest` 스킬로 조사 기록과 원문을 확인하겠습니다. 확인된 간격 규칙을 정식 지식에 반영하고, 조사 기록에 반영 결과와 표시 지연 미결 질문을 연결하겠습니다.


- initial 파일 해시 (로컬 원본: `w-t6/round-1/initial.sha256`), Git (로컬 원본: `w-t6/round-1/initial.git.txt`).
- before-recall 파일 해시 (로컬 원본: `w-t6/round-1/before-recall.sha256`), Git (로컬 원본: `w-t6/round-1/before-recall.git.txt`).
- after-recall 파일 해시 (로컬 원본: `w-t6/round-1/after-recall.sha256`), Git (로컬 원본: `w-t6/round-1/after-recall.git.txt`).
- before-recall → after-recall: 파일 해시 동일=True; Git 동일=True.
