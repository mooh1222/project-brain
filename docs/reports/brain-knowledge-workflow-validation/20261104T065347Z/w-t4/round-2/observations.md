> E3 당시 판정·관찰의 보존 사본이다. W-T1의 두 기록 세션은 개인 memory를 읽었으므로
> 이번 memory 비활성 통과 집계에서는 제외하고 재실행 결과로 교체한다.
> 작은 Markdown 산출물만 추적하며 JSONL·프로젝트·해시 원본은 로컬 전용이다.
> 링크는 추적 산출물로만 연결하고 원본 증거는 경로 텍스트로 표시했다.

# W-T4 round-2 관찰

## fault

- Session: `01a1a561-5c31-78d3-accf-7aa490126950`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](fault.request.md), 기존 세션 JSONL (로컬 원본: `w-t4/round-2/fault.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t4/round-2/fault.events.jsonl`), [답변](fault.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/SKILL.md' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-query/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat .project-brain.json' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/discovery.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md' `
- exit=1: `/bin/zsh -lc 'cat brain/backlog/development.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft list' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show immediate-retry-limit-study' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study' `
- exit=1: `/bin/zsh -lc "./tools/project-brain search '시간 경계 즉시 실행 재시도 제한'" `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study --item sample-a-observation' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study --item next-investigation' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study --item network-delay-hypothesis' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show immediate-retry-limit-study --item compare-legacy-and-current' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show immediate-retry-limit-study --item legacy-five-retries' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show immediate-retry-limit-study --item current-documented-limit' `
- exit=0: `/bin/zsh -lc 'nl -ba docs/retry-rules.md' `
- exit=0: `/bin/zsh -lc 'nl -ba docs/time-study.md' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

현재 확인된 내용과 가설은 다음처럼 구분됩니다.

- **확인된 관찰:** 샘플 A에서 서버 응답 경계가 표시 시각보다 **2초 앞섰다는 기록**이 있습니다. 표본 하나의 관찰이며 일반적인 동작으로 확정할 수 없습니다. 시간 경계 문서 (로컬 원본: `w-t4/round-2/project/docs/time-study.md`)
- **미확인 가설:** 차이의 원인이 네트워크 지연이라는 설명은 아직 검증되지 않았습니다. 추가 표본과 서버·클라이언트 시계 동기화 조건도 미확보입니다. 초안에는 이를 확인할 다음 조사 질문이 있으며, 개발 개선 행동은 정해지지 않았습니다.
- **과거 재시도 기록과 현재 규칙의 차이:** 과거 **‘즉시 실행 최대 다섯 번’**은 사용자 전언을 보존한 미검증 가설입니다. 옛 메모 원문·작성 시점·적용 범위는 확보되지 않았습니다. 현재 문서는 **즉시 실행과 예약 실행 각각 최대 세 번**이라고 명시합니다. 따라서 수치 차이는 있지만, **다섯 번에서 세 번으로 변경됐다는 이력이나 이유는 확인할 수 없습니다.** 실제 코드·장치 동작도 검증한 상태가 아닙니다. 현재 재시도 규칙 (로컬 원본: `w-t4/round-2/project/docs/retry-rules.md`)

두 조사 초안은 모두 **미검수 작업 기억**이며, 갱신 시각은 2026-11-04 16:05:10(+09:00)입니다.

전에 재시도 쪽을 손보자던 제안은 설정된 `brain/backlog/development.md`를 직접 읽으려 했으나 **권한 오류로 확인하지 못했습니다. 제안이 없다는 뜻은 아닙니다.** 현재 규칙 문서에는 “제한 수정 시 두 진입 경로를 함께 확인해야 한다”는 주의사항이 있지만, 이것만으로 과거 개선 제안의 내용이나 채택 여부를 대신 판단할 수는 없습니다.

Brain 검색도 색인 DB 오류로 실패했고, 초안 목록은 손상 파일 하나 때문에 일부만 확인됐습니다. 복구·수정은 하지 않았으며, 종료 시 Git 상태는 시작 시와 같았습니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-query`와 `demo-brain-draft` 스킬로 기존 조사와 재시도 개선 기록을 읽겠습니다. 확인된 내용, 미확인 가설, 현재 규칙과 다른 과거 기록을 구분하고 파일은 수정하지 않겠습니다.


## healthy

- Session: `01a1a560-748b-7113-9f07-dfa2fc447fec`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](healthy.request.md), 기존 세션 JSONL (로컬 원본: `w-t4/round-2/healthy.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t4/round-2/healthy.events.jsonl`), [답변](healthy.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-query/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/discovery.md' `
- exit=0: `/bin/zsh -lc 'cat .project-brain.json' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md' `
- exit=1: `/bin/zsh -lc 'cat brain/backlog/development.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft list' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show immediate-retry-limit-study' `
- exit=0: `/bin/zsh -lc "./tools/project-brain search '시간 경계 재시도 제한'" `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study --item network-delay-hypothesis' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study --item sample-a-observation' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study --item next-investigation' `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.immediate' `
- exit=0: `/bin/zsh -lc './tools/project-brain show evref.retry.rules' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show immediate-retry-limit-study --item compare-legacy-and-current' `
- exit=0: `/bin/zsh -lc './tools/project-brain show mapping.retry.scheduled' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show immediate-retry-limit-study --item current-documented-limit' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show immediate-retry-limit-study --item legacy-five-retries' `
- exit=1: `/bin/zsh -lc 'nl -ba docs/time-study.md docs/retry-rules.md' `
- exit=0: `/bin/zsh -lc 'ls -ld brain' `
- exit=0: `/bin/zsh -lc "./tools/project-brain query '즉시 실행 재시도 제한의 과거 값과 현재 값'" `
- exit=0: `/bin/zsh -lc './tools/project-brain show context.retry' `
- exit=0: `/bin/zsh -lc './tools/project-brain show manifest.retry.rules' `
- exit=0: `/bin/zsh -lc "./tools/project-brain search '샘플 A 서버 응답 표시 시각 네트워크 지연' --all-contexts" `
- exit=0: `/bin/zsh -lc 'nl -ba docs/time-study.md' `
- exit=0: `/bin/zsh -lc 'nl -ba docs/retry-rules.md' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

읽은 내용은 다음처럼 구분됩니다. 두 조사 초안은 모두 **11월 4일 16:05 갱신된 미검수 작업 기억**입니다.

- **확인된 관찰:** 시간 경계 문서 (로컬 원본: `w-t4/round-2/project/docs/time-study.md`)에 “샘플 A에서 서버 응답 경계가 표시 시각보다 2초 앞섰다”는 기록이 있습니다. 표본은 하나이며 실제 측정 로그는 확보되지 않았습니다. 시간 경계 지식은 Brain 객체로 회수되지 않았고, 문서와 초안에 있습니다.
- **미확인 가설:** 네트워크 지연이 원인이라는 설명은 검증되지 않았습니다. 추가 표본과 서버·클라이언트 시계 동기화 조건이 필요합니다. 초안의 다음 질문도 “그 조건을 확보해도 같은 차이가 나타나는가?”이며, 개발 개선 행동은 정해지지 않았습니다.
- **과거 재시도 기록과 현재 규칙:** 재시도 조사 초안 (로컬 원본: `w-t4/round-2/project/brain/drafts/immediate-retry-limit-study.json`)의 **‘즉시 실행 다섯 번’은 사용자 전언으로 남긴 오래된 미검증 가설**입니다. 옛 메모 원문·작성 시점·적용 범위는 미확보입니다. 현재 규칙 문서 (로컬 원본: `w-t4/round-2/project/docs/retry-rules.md`)와 검수된 객체 `mapping.retry.immediate`, `mapping.retry.scheduled`는 **두 경로 모두 최대 세 번, 제한은 경로별 적용**으로 일치합니다. 변경 이력은 미적재 상태여서 ‘다섯 번에서 세 번으로 변경됐다’고 확정할 수는 없습니다. 실제 구현·장치 동작도 검증되지 않았습니다.
- **전에 손보자던 재시도 개선 제안:** 설정된 저장 위치 `brain/backlog/development.md`에 파일이 없어, **그 위치에서는 제안을 확인하지 못했습니다.** 다만 규칙 문서에는 “제한 수정 시 두 진입 경로를 함께 확인해야 누락 위험을 줄인다”는 주의사항이 있습니다. 이것만으로 과거 개선 제안이나 채택 사실을 입증하지는 않습니다.

읽기만 수행했으며, 시작·종료 시 Git 상태는 같습니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-query`와 `demo-brain-draft` 스킬로 기존 조사 초안과 재시도 관련 기록을 읽겠습니다. 확인된 내용, 미확인 가설, 과거 기록과 현재 규칙의 차이를 나누어 정리하겠습니다.


## record

- Session: `01a1a55f-0846-7a61-9ff1-e9629bcb1cb8`; actual model `gpt-6.1-sol`, effort `high`, CLI `0.166.0`.
- [입력 요청](record.request.md), 기존 세션 JSONL (로컬 원본: `w-t4/round-2/record.native.jsonl`), 명령 관찰 JSONL (로컬 원본: `w-t4/round-2/record.events.jsonl`), [답변](record.answer.md).

실제 명령과 종료 상태:

- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/SKILL.md' `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-session-ingest/SKILL.md' `
- exit=0: `/bin/zsh -lc 'cat /Users/al03040455/.agents/rules/response-discipline.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-session-ingest/references/dev-ingest.md .project-brain.json docs/time-study.md' `
- exit=0: `/bin/zsh -lc 'cat .agents/skills/demo-brain-draft/references/knowledge-workflow.md .agents/skills/demo-brain-draft/references/discovery.md .agents/skills/demo-brain-draft/references/v2-format.md' `
- exit=0: `/bin/zsh -lc "rg --files -g 'AGENTS.md' -g '*time*' -g '*proposal*' -g '*제안*' -g '*draft*' -g '"'!node_modules'"' -g '"'!.git'"'" `
- exit=0: `/bin/zsh -lc './tools/project-brain draft list' `
- exit=0: `/bin/zsh -lc 'rg --files brain docs | head -80' `
- exit=0: `/bin/zsh -lc 'cat docs/retry-rules.md docs/new-rule.md' `
- exit=0: `/bin/zsh -lc "rg -n '다섯|5회|5번|five|재시도|시간 경계' docs brain AGENTS.md" `
- exit=0: `/bin/zsh -lc './tools/project-brain draft create --help' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft create time-boundary-study --title "시간 경계 조사" --scope "샘플 A의 시간 경계 관찰, 미확인 네트워크 지연 가설, 표본·동기화 조건의 한계와 다음 조사 질문" --source docs/time-study.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft create immediate-retry-limit-study --title "즉시 실행 재시도 제한의 과거 가설 대조" --scope "출처 미확보인 과거 다섯 번 가설을 보존하고 현재 문서의 세 번 규칙과 대조할 조사 질문" --source docs/retry-rules.md' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show time-boundary-study' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft show immediate-retry-limit-study' `
- exit=0: `/bin/zsh -lc 'rg --files brain/drafts' `
- exit=0: `/bin/zsh -lc 'cat brain/drafts/time-boundary-study.json brain/drafts/immediate-retry-limit-study.json' `
- exit=0: `/bin/zsh -lc 'cat tools/project-brain tools/python' `
- exit=0: `/bin/zsh -lc "rg -n '\"limits\"|\"session_id\"|resume_summary' .agents/skills/demo-brain-draft -g '*.json' -g '*.md'" `
- exit=0: `/bin/zsh -lc "rg -n 'limits|session_id|source.*context' /Users/al03040455/orca/workspaces/project-brain/brain-kw-e3/src/project_brain/draft*" `
- exit=0: `/bin/zsh -lc "./tools/python - <<'PY' ⏎ import json ⏎ import subprocess ⏎ import tempfile ⏎ from pathlib import Path ⏎  ⏎ session_locator = {'session_id': 'current-session-2026-11-04', 'position': '사용자의 시간 경계 관찰 및 과거 재시도 가설 기록 요청'} ⏎ patches =  ⏎     ('time-boundary-study', 'b77712fdcd2774674077cb5adbd3f02da2be1026514b6b90db6a872f28b7e63c', { ⏎         'resume_summary': '초안(미검수 작업 기억). 샘플 A에서 서버 응답 경계가 표시 시각보다 2초 앞섰다는 단일 관찰만 있다. 네트워크 지연 원인은 미확인이며 추가 자료·표본과 시계 동기화 조건은 미확보다. 개발 개선 행동은 정해지지 않았다. 다음 조사에서는 추가 표본과 동기화 조건을 확보해 원인 가설을 검증한다.', ⏎         'sources': [ ⏎             {'op': 'replace', 'value': {'key': 'source-1', 'kind': 'document', 'locator': {'path': 'docs/time-study.md', 'section': '시간 경계 조사'}, 'quote': '관찰 하나: 샘플 A에서 서버 응답의 경계가 표시 시각보다 2초 앞섰다.\\n네트워크 지연 때문이라는 가설은 미확인이다. 추가 표본과 시계 동기화 조건은 아직 없다.', 'context': '2026-11-04 현재 로컬 문서를 읽어 보존한 관찰 서술. 실제 측정 로그·추가 표본은 확보하지 못했다.'}}, ⏎             {'op': 'add', 'value': {'key': 'user-limits', 'kind': 'session', 'locator': session_locator, … (전체는 JSONL) `
- exit=0: `/bin/zsh -lc 'git status --short --branch' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft lint time-boundary-study' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft lint' `
- exit=0: `/bin/zsh -lc './tools/project-brain draft lint immediate-retry-limit-study' `

관찰된 최종 답변 (회수 본문, 출처, 검수 표시):

다음 조사에서 이어 볼 수 있도록 **미검수 초안** 두 개로 기록했습니다.

- [시간 경계 조사 (로컬 원본: `w-t4/round-2/brain/drafts/time-boundary-study.json`): 샘플 A는 단일 관찰이며 네트워크 지연 원인은 미확인, 추가 자료 미확보, 개발 개선 행동 미결정임을 명시했습니다.
- 과거 재시도 가설 (로컬 원본: `w-t4/round-2/brain/drafts/immediate-retry-limit-study.json`): ‘다섯 번’ 가설의 원문·출처 미확보와 현재 문서의 ‘세 번’ 규칙과의 대조 필요성을 남겼습니다.

두 초안의 형식 검사를 통과했습니다.


실행자가 밝힌 스킬/진행 맥락:

`demo-brain-draft`와 `demo-brain-session-ingest` 스킬을 적용해, 관찰과 오래된 가설의 근거·검증 한계를 다음 조사에서 이어 볼 수 있게 기록하겠습니다. 먼저 기존 문서와 작업 상태를 확인하겠습니다.


- initial 파일 해시 (로컬 원본: `w-t4/round-2/initial.sha256`), Git (로컬 원본: `w-t4/round-2/initial.git.txt`).
- before-healthy 파일 해시 (로컬 원본: `w-t4/round-2/before-healthy.sha256`), Git (로컬 원본: `w-t4/round-2/before-healthy.git.txt`).
- after-healthy 파일 해시 (로컬 원본: `w-t4/round-2/after-healthy.sha256`), Git (로컬 원본: `w-t4/round-2/after-healthy.git.txt`).
- before-fault 파일 해시 (로컬 원본: `w-t4/round-2/before-fault.sha256`), Git (로컬 원본: `w-t4/round-2/before-fault.git.txt`).
- after-fault 파일 해시 (로컬 원본: `w-t4/round-2/after-fault.sha256`), Git (로컬 원본: `w-t4/round-2/after-fault.git.txt`).
- before-healthy → after-healthy: 파일 해시 동일=True; Git 동일=True.
- before-fault → after-fault: 파일 해시 동일=True; Git 동일=True.
