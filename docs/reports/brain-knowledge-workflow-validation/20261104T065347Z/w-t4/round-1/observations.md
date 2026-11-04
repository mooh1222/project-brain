> E3 당시 판정·관찰의 보존 사본이다. W-T1의 두 기록 세션은 개인 memory를 읽었으므로
> 이번 memory 비활성 통과 집계에서는 제외하고 재실행 결과로 교체한다.
> 작은 Markdown 산출물만 추적하며 JSONL·프로젝트·해시 원본은 로컬 전용이다.
> 링크는 추적 산출물로만 연결하고 원본 증거는 경로 텍스트로 표시했다.

# W-T4 round-1 관찰

## fault

- Session: `01a1a560-b0c7-7563-9cf3-a442feaefcad`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](fault.request.md), 기존 세션 JSONL (로컬 원본: `w-t4/round-1/fault.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t4/round-1/fault.events.jsonl`), [답변](fault.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-query/SKILL.md .agents/skills/demo-brain-draft/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md .agents/skills/demo-brain-draft/references/discovery.md' `
- exit=0: `/bin/zsh -lc 'cat .project-brain.json' `
- exit=1: `/bin/zsh -lc 'cat brain/backlog/development.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft list' `
- exit=0: `/bin/zsh -lc './tools/project-brain --help' `
- exit=0: `/bin/zsh -lc 'cat tools/project-brain' `
- exit=0: `/bin/zsh -lc 'ls -ld brain brain/backlog brain/backlog/development.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study' `
- exit=0: `/bin/zsh -lc './tools/project-brain search --help' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study --item sample-a-boundary-observation' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study --item network-delay-hypothesis' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study --item historical-retry-five-hypothesis' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study --item next-boundary-investigation' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study --item verify-historical-retry-rule' `
- exit=2: `/bin/zsh -lc './tools/project-brain query "즉시 실행 재시도 제한 현재 규칙" --stub-embedder' `
- exit=1: `/bin/zsh -lc './tools/project-brain search "즉시 실행 재시도 시간 경계" --stub-embedder' `
- exit=0: `/bin/zsh -lc 'cat docs/time-study.md' `
- exit=2: `/bin/zsh -lc 'rg --files brain docs src' `
- exit=0: `/bin/zsh -lc './tools/project-brain query "즉시 실행 재시도 제한 현재 규칙"' `
- exit=0: `/bin/zsh -lc 'cat docs/retry-rules.md docs/new-rule.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.immediate' `
- exit=0: `/bin/zsh -lc './tools/project-brain show evref.retry.rules' `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.scheduled' `
- exit=0: `/bin/zsh -lc "rg -n '"'^'"' docs/time-study.md docs/retry-rules.md" `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc './tools/project-brain show context.retry' `
- exit=0: `/bin/zsh -lc './tools/project-brain show manifest.retry.rules' `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

현재 확인한 내용은 다음과 같습니다.

- **관찰된 내용:** 샘플 A 한 건에서 서버 응답 경계가 표시 시각보다 **2초 앞섰습니다**. 단일 표본이므로 일반적인 동작으로 확정할 수 없습니다. 조사 원문 (로컬 원본: `w-t4/round-1/project/docs/time-study.md`)
- **미확인 가설:** 네트워크 지연이 원인이라는 설명은 검증되지 않았습니다. 추가 표본·시계 동기화 조건·요청과 응답의 시각 및 지연 자료가 필요합니다. 초안 (로컬 원본: `w-t4/round-1/project/brain/drafts/time-boundary-study.json`)은 **미검수 작업 기억**이며, 갱신 시각은 2026-11-04 16:04:29입니다.
- **과거 재시도 기록:** 초안에는 “즉시 실행 재시도 제한이 **다섯 번**이라는 예전 가설”이 사용자 진술로 남아 있습니다. 과거 메모 원문·작성 시점·적용 범위는 미확보입니다.
- **현재 규칙과의 차이:** 검수된 Brain 객체 `mapping.retry.immediate`·`mapping.retry.scheduled`와 운영 규칙 원문 (로컬 원본: `w-t4/round-1/project/docs/retry-rules.md`)은 **즉시·예약 실행 모두 최대 세 번, 경로별로 별도 제한**이라고 일치합니다. 과거 가설과 숫자는 다르지만, **실제로 5회에서 3회로 변경됐다는 이력은 확인되지 않았습니다.** 구현 코드의 현행 동작도 이 근거로 검증된 것은 아닙니다.

전에 “재시도 쪽을 나중에 손보자”던 제안은 개선 제안 문서 (로컬 원본: `w-t4/round-1/project/brain/backlog/development.md`)의 **읽기 권한이 없어 확인하지 못했습니다.** 제안이 없다는 뜻은 아닙니다. 운영 문서에는 “제한 수정 시 두 진입 경로를 함께 확인해야 누락 위험을 줄인다”는 주의사항이 있지만, 이것만으로 과거 개선 제안이나 채택 여부를 판단할 수는 없습니다.

조회에는 제한이 있었습니다. 초안 목록은 손상 파일 1개 때문에 불완전했고, 일반 검색은 색인 DB 오류로 실패해 관련 객체를 직접 열었습니다. 파일·권한·색인은 변경하지 않았으며, 종료 시 Git 상태는 시작 시와 같았습니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-query`와 `demo-brain-draft` 스킬로 시간 경계 조사 초안과 재시도 관련 기존 기록을 읽겠습니다. 확인된 내용, 미확인 가설, 과거 기록과 현재 규칙의 차이를 구분하고 파일은 변경하지 않겠습니다.


## healthy

- Session: `01a1a55f-c42a-7123-90f8-669569444faf`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](healthy.request.md), 기존 세션 JSONL (로컬 원본: `w-t4/round-1/healthy.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t4/round-1/healthy.events.jsonl`), [답변](healthy.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-query/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/discovery.md' `
- exit=0: `/bin/zsh -lc 'cat .project-brain.json' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md' `
- exit=1: `/bin/zsh -lc 'cat brain/backlog/development.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft list' `
- exit=1: `/bin/zsh -lc 'ls -ld brain brain/backlog' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study' `
- exit=0: `/bin/zsh -lc "./tools/project-brain search '시간 경계 재시도'" `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/v2-format.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study --item sample-a-boundary-observation --item network-delay-hypothesis --item historical-retry-five-hypothesis --item next-boundary-investigation --item verify-historical-retry-rule' `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.immediate' `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.scheduled' `
- exit=0: `/bin/zsh -lc "./tools/project-brain search '샘플 A 서버 응답 표시 시각' --all-contexts" `
- exit=0: `/bin/zsh -lc 'cat docs/time-study.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study --item sample-a-boundary-observation' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study --item historical-retry-five-hypothesis' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study --item network-delay-hypothesis' `
- exit=0: `/bin/zsh -lc "./tools/project-brain query '즉시 실행 재시도 현재 규칙과 과거 이력'" `
- exit=0: `/bin/zsh -lc './tools/project-brain show evref.retry.rules' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study --item next-boundary-investigation' `
- exit=0: `/bin/zsh -lc './tools/project-brain show context.retry' `
- exit=0: `/bin/zsh -lc 'rg --files docs brain' `
- exit=0: `/bin/zsh -lc './tools/project-brain show manifest.retry.rules' `
- exit=0: `/bin/zsh -lc 'cat docs/retry-rules.md' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

읽기만 했고, 작업 전후 Git 상태는 같습니다.

- **확인된 관찰:** 시간 경계 문서 (로컬 원본: `w-t4/round-1/project/docs/time-study.md`)에는 샘플 A에서 서버 응답 경계가 표시 시각보다 **2초 앞섰다**고 기록돼 있습니다. 표본 한 건의 관찰이며, 일반적인 동작으로 확정할 수 없습니다.
- **미확인 가설:** 네트워크 지연이 원인이라는 설명은 미확인입니다. 추가 표본·시계 동기화 조건·요청과 응답 시각 및 지연 자료가 필요합니다. 조사 초안 (로컬 원본: `w-t4/round-1/project/brain/drafts/time-boundary-study.json`)은 **미검수 작업 기억**이며, 갱신 시각은 2026-11-04 16:04:29+09:00입니다. 시간 경계 내용은 정식 Brain 객체로 회수되지 않았습니다.

재시도 횟수는 다음처럼 구분됩니다.

| 구분 | 기록 내용 | 확인 수준 |
|---|---|---|
| 과거 기록에 대한 진술 | 즉시 실행 재시도 제한이 **다섯 번이라는 가설** | 사용자 진술만 보존. 과거 메모 원문·작성 시점·적용 범위 미확보 |
| 현재 운영 규칙 | 즉시 실행·예약 실행 **각각 최대 세 번**, 경로별 별도 적용 | 검수된 `mapping.retry.immediate`, `mapping.retry.scheduled`와 규칙 원문 (로컬 원본: `w-t4/round-1/project/docs/retry-rules.md`) 확인 |

따라서 과거 가설은 현재 문서 규칙과 다릅니다. 다만 **실제로 다섯 번에서 세 번으로 변경됐다고 단정할 수는 없습니다.** 변경 이력이 미적재돼 있고, 실제 구현 코드나 장치 실행도 검증되지 않았습니다.

“재시도 쪽을 나중에 손보자”는 **개선 제안은 설정된 저장 위치에서 확인되지 않았습니다.** `.project-brain.json`의 지식 루트는 `brain`이며, 그 아래 `backlog/development.md`가 없습니다. 다만 규칙 원문에는 “제한을 수정할 때 두 진입 경로를 함께 확인해야 누락 위험을 줄일 수 있다”는 주의사항이 있습니다. 이것만으로 과거 개선 제안의 채택 여부나 현재 해결 여부를 판단할 수는 없습니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-query`와 `demo-brain-draft` 스킬로 시간 경계 조사 기록과 재시도 개선 제안을 읽겠습니다. 확인된 사실, 미확인 가설, 과거 횟수 기록과 현재 규칙의 차이를 구분하고 파일은 수정하지 않겠습니다.


## record

- Session: `01a1a55e-bd73-7d72-9cfa-c2e186579683`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](record.request.md), 기존 세션 JSONL (로컬 원본: `w-t4/round-1/record.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t4/round-1/record.events.jsonl`), [답변](record.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-session-ingest/SKILL.md' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md .agents/skills/demo-brain-draft/references/discovery.md .agents/skills/demo-brain-draft/references/v2-format.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-session-ingest/references/dev-ingest.md .project-brain.json docs/time-study.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft list' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft create time-boundary-study --title "시간 경계 조사" --scope "샘플 A의 시간 경계 관찰과 원인 미확인, 과거 즉시 실행 재시도 제한 가설의 출처 확보 및 현행 규칙 대조" --source "docs/time-study.md"' `
- exit=0: `/bin/zsh -lc 'cat brain/drafts/time-boundary-study.json' `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import json, tempfile ⏎ from pathlib import Path ⏎ patch = { ⏎   'resume_summary': '초안(미검수 작업 기억). docs/time-study.md의 샘플 A 한 건에서 서버 응답 경계가 표시 시각보다 2초 앞선 것으로 관찰됐다. 네트워크 지연 원인은 미확인이며 추가 자료와 시계 동기화 조건은 확보하지 못했다. 이 관찰만으로 개발 개선 행동을 정하지 않았다. 과거 즉시 실행 재시도 제한이 다섯 번이라는 가설도 사용자 진술로 보존하되, 과거 메모 원문·출처가 미확보이고 현재 규칙과 대조하지 않았다. 다음 조사에서 추가 표본·시계 동기화 조건·지연 자료, 과거 메모 출처와 현행 재시도 규칙을 확보·대조한다.', ⏎   'sources':  ⏎     {'op': 'replace', 'value': { ⏎       'key': 'source-1', 'kind': 'document', ⏎       'locator': {'path': 'docs/time-study.md', 'section': '시간 경계 조사'}, ⏎       'quote': '관찰 하나: 샘플 A에서 서버 응답의 경계가 표시 시각보다 2초 앞섰다.\\n네트워크 지연 때문이라는 가설은 미확인이다. 추가 표본과 시계 동기화 조건은 아직 없다.', ⏎       'context': '현재 로컬 문서를 직접 읽었다. 샘플 A는 관찰 한 건이며 원인을 검증한 자료가 아니다.' ⏎     }}, ⏎     {'op': 'add', 'value': { ⏎       'key': 'user-record-request', 'kind': 'session', ⏎       'locator': {'session_id': 'current-session', 'position': '2026-11-04 시간 경계 조사 기록 요청 사용자 발화'}, ⏎       'quote': '시간 경계의 … (전체는 JSONL) `
- exit=0: `/bin/zsh -lc './tools/project-brain draft update time-boundary-study --expected-sha 75c03f1d0c963111b73913f927d7c20140c0e712e68f6ad45f99e6bbff56d3b2 --patch-file /var/folders/kf/nkj6_l416bd504d961v_w6wh0000gn/T/time-boundary-study-tcnbr5gp.json' `
- exit=0: `/bin/zsh -lc 'cat brain/drafts/time-boundary-study.json' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft lint time-boundary-study' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft lint' `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

[시간 경계 조사 초안 (로컬 원본: `w-t4/round-1/project/brain/drafts/time-boundary-study.json`)에 미검수 조사 기록으로 저장했습니다.

- 샘플 A: 단일 관찰이며 네트워크 지연 원인은 미확인, 추가 자료 미확보.
- ‘재시도 다섯 번’: 출처 미확보인 오래된 가설이며 현행 규칙과 대조 필요.
- 개발 개선 행동은 정하지 않았음을 명시하고, 다음 조사의 열린 질문을 남겼습니다.

초안 형식 검사를 통과했습니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-session-ingest`와 `demo-brain-draft` 스킬로 관찰과 오래된 가설의 한계를 보존하고, 다음 조사에서 이어 볼 수 있게 기록하겠습니다.


- initial 파일 해시 (로컬 원본: `w-t4/round-1/initial.sha256`), Git (로컬 원본: `w-t4/round-1/initial.git.txt`).
- before-healthy 파일 해시 (로컬 원본: `w-t4/round-1/before-healthy.sha256`), Git (로컬 원본: `w-t4/round-1/before-healthy.git.txt`).
- after-healthy 파일 해시 (로컬 원본: `w-t4/round-1/after-healthy.sha256`), Git (로컬 원본: `w-t4/round-1/after-healthy.git.txt`).
- before-fault 파일 해시 (로컬 원본: `w-t4/round-1/before-fault.sha256`), Git (로컬 원본: `w-t4/round-1/before-fault.git.txt`).
- after-fault 파일 해시 (로컬 원본: `w-t4/round-1/after-fault.sha256`), Git (로컬 원본: `w-t4/round-1/after-fault.git.txt`).
- before-healthy → after-healthy: 파일 해시 동일=True; Git 동일=True.
- before-fault → after-fault: 파일 해시 동일=True; Git 동일=True.
