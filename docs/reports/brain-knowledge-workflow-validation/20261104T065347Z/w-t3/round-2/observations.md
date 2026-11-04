> E3 당시 판정·관찰의 보존 사본이다. W-T1의 두 기록 세션은 개인 memory를 읽었으므로
> 이번 memory 비활성 통과 집계에서는 제외하고 재실행 결과로 교체한다.
> 작은 Markdown 산출물만 추적하며 JSONL·프로젝트·해시 원본은 로컬 전용이다.
> 링크는 추적 산출물로만 연결하고 원본 증거는 경로 텍스트로 표시했다.

# W-T3 round-2 관찰

## recall

- Session: `01a1a55e-9674-71f3-a149-2c1c0c80fe29`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](recall.request.md), 기존 세션 JSONL (로컬 원본: `w-t3/round-2/recall.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t3/round-2/recall.events.jsonl`), [답변](recall.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-query/SKILL.md' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md' `
- exit=0: `/bin/zsh -lc 'cat .project-brain.json' `
- exit=0: `/bin/zsh -lc 'nl -ba brain/backlog/development.md' `
- exit=0: `/bin/zsh -lc 'nl -ba brain/drafts/retry-paths.json' `
- exit=0: `/bin/zsh -lc 'nl -ba docs/retry-rules.md' `
- exit=0: `/bin/zsh -lc "rg --files -g '*retry*' -g '*development*' -g '*42*' -g 'AGENTS.md'" `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

기록에는 **공통화 제안**과 **그 전에 할 경계 테스트 작업**이 구분돼 있습니다.

- **제안한 것:** 즉시 실행·예약 실행의 **재시도 제한 계산 공통화**입니다. 두 경로를 따로 수정하다 한쪽을 빠뜨릴 위험을 줄이고, 함께 유지하기 쉽게 하자는 취지였습니다. 2026-11-04 기록이며, **제안 단계로 실행 확정은 아닙니다.** 제안 기록 (로컬 원본: `w-t3/round-2/brain/backlog/development.md`)
- **얘기가 나온 곳:** 재시도 운영 규칙의 ‘즉시 실행과 예약 실행’ 절 (로컬 원본: `w-t3/round-2/docs/retry-rules.md`)과 같은 날 사용자 기록 요청입니다. 문서에는 두 경로가 각각 최대 세 번 재시도하고 제한을 별도로 적용하므로, 변경할 때 두 진입 경로를 함께 확인해야 한다고 적혀 있습니다.
- **실제 작업으로 연결한 것:** **‘공통화 전 두 경로의 경계 테스트 추가’**를 별도 채택 작업인 [이슈 #42](https://example.invalid/demo/issues/42)로 연결했습니다. 공통화 자체를 채택한 기록과는 구분됩니다. 채택 링크 기록 (로컬 원본: `w-t3/round-2/brain/backlog/development.md`)

현재 확인되는 것은 **작업 링크로 연결했다는 사실까지**입니다. 테스트 구현·완료 여부는 확인하지 않았고, 실제 코드의 중복 정도와 공통화 비용도 미검증입니다. 출처 문서는 합성 자료이므로 실제 구현의 증거로 볼 수 없습니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-query` 스킬로 이전 개선 제안과 출처, 실제 작업으로 이어진 기록을 찾아보겠습니다.


## record

- Session: `01a1a55d-c301-7e41-a745-a786331b671b`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](record.request.md), 기존 세션 JSONL (로컬 원본: `w-t3/round-2/record.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t3/round-2/record.events.jsonl`), [답변](record.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-session-ingest/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md .agents/skills/demo-brain-draft/references/discovery.md .agents/skills/demo-brain-draft/references/v2-format.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-session-ingest/references/dev-ingest.md .project-brain.json docs/retry-rules.md' `
- exit=0: `/bin/zsh -lc 'git ls-files -- brain/backlog/development.md brain/drafts; rg --files brain/backlog brain/drafts; if [ -f brain/backlog/development.md ]; then cat brain/backlog/development.md; fi' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft list' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft create retry-paths --title "재시도 경로 이해" --scope "즉시 실행·예약 실행의 재시도 제한에 관한 문서상 이해와 구현 확인이 필요한 질문" --source "docs/retry-rules.md"' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show retry-paths --full' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import json ⏎ import tempfile ⏎ patch = { ⏎     'resume_summary': '초안(미검수 작업 기억). docs/retry-rules.mdの「즉시 실행과 예약 실행」절에서 두 경로가 각각 최대 세 번 재시도하며 별도로 제한을 적용한다고 확인했다. 실제 코드·실행은 확인하지 않았다. 다음 재개 시 구현 중복 정도와 공통화 비용을 확인해야 한다. 개선 행동과 별도 채택 작업 링크는 brain/backlog/development.md를 참조한다.', ⏎     'sources': [{'op': 'replace', 'value': { ⏎         'key': 'source-1', 'kind': 'document', ⏎         'locator': {'path': 'docs/retry-rules.md', 'section': '즉시 실행과 예약 실행'}, ⏎         'quote': '즉시 실행과 예약 실행 모두 최대 세 번 재시도한다. 각 경로는 별도로 제한을 적용한다.', ⏎         'context': '합성 운영 규칙 문서이며 실제 코드 또는 장치 실행의 증거가 아니다.' ⏎     }}], ⏎     'items': [ ⏎         {'op': 'add', 'value': { ⏎             'key': 'separate-retry-limits', 'kind': 'finding', ⏎             'text': '문서상 즉시 실행과 예약 실행은 모두 최대 세 번 재시도하며 각 경로가 별도로 제한을 적용한다.', ⏎             'source_keys': ['source-1'], ⏎             'limits': '문서에서 확인한 이해다. 실제 구현이나 실행 동작을 검증한 결과가 아니다.', ⏎             'recall_question': '즉시 실행과 예약 실행의 재시도 제한은 … (전체는 JSONL) `
- exit=0: `/bin/zsh -lc './tools/project-brain draft update retry-paths --expected-sha 74a94acc0a9fb0b042025ae71992239bf47b98ddb2514b88bb3562ccb40dad9b --patch-file /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/retry-draft-wub2t4nn.json' `
- exit=0: `/bin/zsh -lc 'cat brain/backlog/development.md brain/drafts/retry-paths.json; git diff --check; git status --short --branch' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft lint retry-paths' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft lint' `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

기록했습니다.

- 재시도 경로 초안 (로컬 원본: `w-t3/round-2/brain/drafts/retry-paths.json`): 문서상 현재 이해와 구현 중복·공통화 비용이 미검증임을 남겼습니다.
- 개선 제안 (로컬 원본: `w-t3/round-2/brain/backlog/development.md`): 공통화 제안, 한쪽 수정 누락 위험, 함께 유지하기 쉬워지는 기대 효과를 기록했습니다. 경계 테스트는 [이슈 #42](https://example.invalid/demo/issues/42) 링크만 연결했으며, 진행은 해당 이슈에서 관리합니다.

초안 형식 검사도 통과했습니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-draft`와 `demo-brain-session-ingest` 스킬을 사용해 현재 이해와 개선 제안을 기록하고, 채택된 경계 테스트 작업은 이슈 링크로 연결하겠습니다.


- initial 파일 해시 (로컬 원본: `w-t3/round-2/initial.sha256`), Git (로컬 원본: `w-t3/round-2/initial.git.txt`).
- before-recall 파일 해시 (로컬 원본: `w-t3/round-2/before-recall.sha256`), Git (로컬 원본: `w-t3/round-2/before-recall.git.txt`).
- after-recall 파일 해시 (로컬 원본: `w-t3/round-2/after-recall.sha256`), Git (로컬 원본: `w-t3/round-2/after-recall.git.txt`).
- before-recall → after-recall: 파일 해시 동일=True; Git 동일=True.
