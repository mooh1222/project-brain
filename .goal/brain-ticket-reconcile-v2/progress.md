# Brain 티켓 정리 v2 진행 기록

- 범위: #2~#13 후보 분리, #33~#39 설계 복귀, `context_md`와 session zero-work 계약 분리
- 기준점: `b35d351ee77093392ca170f799d0edc1a8414070`
- 조율자: 현재 Codex 세션 한 곳
- 실행 방식: Project Brain 저장소와 GitHub Issues만 사용. agent-team 스킬·엔진·Run은 사용하지 않음
- 과거 기록: `codex/brain-ticket-reconcile-20260825:.goal/brain-ticket-reconcile/progress.md`
- 티켓당 사람 개입 없는 실행 시간: 90분
- 진행 판정 간격: 45분
- 기본 후보: 3회
- 기본 검수: 3회
- 기본 설계복귀: 1회
- 기본 전체검사: 2회
- 승인된 예외: #2·#4·#5는 각각 현재 3/4이며 최종 후보 4를 한 번만 추가할 수 있음. 후보 4는 아직 생성하지 않음
- 2026-08-25 추가 승인: #33 설계복귀 상한 1→2·검수 상한 3→4, #34 설계복귀 상한 1→2
- #38·#39는 기존 설계복귀 1/1 안에서 후보 2를 만들며 상한을 늘리지 않음
- 2026-08-25 후보 3 추가 승인: #38 설계복귀 상한 1→2, #34 2→3, #39 1→2. 세 티켓의 검수 상한은
  3으로 유지하며 각각 남은 마지막 검수 1회만 사용함
- 후보 3 권한: 후보 2 독립 검수의 Major 네 가지에 해당하는 #38·#34·#39 설계 계약과 이 진행 기록만
  수정할 수 있음. 구현·#2·#4·#5 후보 생성·main 병합·PR·GitHub 변경은 포함하지 않음
- 기존 #2·#4·#5 예외의 권한 경계: 상한만 늘어났으며 이번 1단계에서 코드 후보를 만들 권한은 없음
- 정리 후보 1: `2db3de1bf430c4c663d087dc52ef033dd3923a31`
- 후보 1 독립 검수: Critical 0 / Major 6 / RETURN
- 정리 후보 2: `6c4a411c072f5d0546709779bdc0a8645e667d6a`
- 후보 2 구조 검수: Critical 0 / Major 0 / Minor 0 / PASS
- 공통 현재 시각: 2026-08-25 Asia/Seoul

## 정본·티켓 구조 정리

- 단계: 1단계 완료
- 후보: 2 / 3
- 검수: 2 / 3
- 설계복귀: 1 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: #38·#39 생성, label·dependency·본문 exact 역조회, 후보 2 구조 검수 PASS
- 마지막 갱신: 2026-08-25
- 다음 행동: 설계확정된 #33·#38·#34·#39의 구현 child issue·파일·실행 순서를 사용자에게 먼저 제시하고
  별도 승인을 기다린다.

## #2 query·audit 읽기 전용 WIP 안정화

- 단계: 준비
- 후보: 3 / 4
- 검수: 2 / 3
- 설계복귀: 0 / 1
- 전체검사: 1 / 2
- 마지막으로 닫힌 완료 조건: 없음
- 마지막 갱신: 2026-08-25
- 다음 행동: `main@b35d351` 위에 `9aefa36`의 정확한 파일 집합만 옮겨 최종 후보 4를 만든다.

## #4 19종 capability registry 확장 단계

- 단계: 준비
- 후보: 3 / 4
- 검수: 2 / 3
- 설계복귀: 0 / 1
- 전체검사: 1 / 2
- 마지막으로 닫힌 완료 조건: 없음
- 마지막 갱신: 2026-08-25
- 다음 행동: #2 종료 뒤 `698dc3e`의 registry와 단위 테스트만 최종 후보 4로 고정한다.

## #5 snapshot v1·v2의 19종 대상을 동결

- 단계: 준비
- 후보: 3 / 4
- 검수: 2 / 3
- 설계복귀: 0 / 1
- 전체검사: 1 / 2
- 마지막으로 닫힌 완료 조건: 없음
- 마지막 갱신: 2026-08-25
- 다음 행동: #4 종료 뒤 `160050c`의 snapshot 동결 범위만 최종 후보 4로 고정한다.

## #33 evidence preparation 설계 admission

- 단계: 설계확정
- 후보: 2 / 3
- 검수: 4 / 4
- 설계복귀: 2 / 2
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: 후보 2 독립 검수 A1 high·A2~A5 PASS·Critical 0 / Major 0
- 마지막 갱신: 2026-08-25
- 다음 행동: #38과 함께 E1~E15 child issue·progress 생성안을 사용자에게 제시하고 별도 승인을 기다린다.

## #34 session completion 설계 admission

- 단계: 설계확정
- 후보: 3 / 3
- 검수: 3 / 3
- 설계복귀: 3 / 3
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: UUID 공용 runner lock과 immutable normal receipt lineage로 과거 closure 검증 계약 고정
- 마지막 갱신: 2026-08-25
- 다음 행동: normal session completion 구현 child issue·파일·검증 순서를 #39보다 먼저 제시하고 별도 승인을 기다린다.

### 초기 입장 판정

- 결과: RETURN
- 이유: 완료 조건 7개로 A4 상한을 넘고, 조건별 정확한 검증 명령·기대 관측 연결이 없어 A3도 닫히지 않음
- 재개 조건: #33을 blocker로 추가하고 core와 zero-work를 각각 완료 조건 6개 이하로 분리

## #38 `context_md` object+artifact lifecycle 설계

- 단계: 설계확정
- 후보: 3 / 3
- 검수: 3 / 3
- 설계복귀: 2 / 2
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: #33 prepared evidence 원문을 target·Markdown·두 seal·불변 manifest·committed recovery에 결속
- 마지막 갱신: 2026-08-25
- 다음 행동: #33 evidence preparation 뒤에 실행할 `context_md` 구현 child issue·파일·검증 순서를 제시하고
  별도 승인을 기다린다.

## #39 session zero-work·unresolved closure 설계

- 단계: 설계확정
- 후보: 3 / 3
- 검수: 3 / 3
- 설계복귀: 2 / 2
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: UUID 공용 runner lock과 최초 유일 tip의 head-only crash recovery 계약 고정
- 마지막 갱신: 2026-08-25
- 다음 행동: #34 normal completion 뒤에 실행할 zero-work 구현 child issue·파일·검증 순서를 제시하고
  별도 승인을 기다린다.

## 설계복귀 후보 2 독립 검수 결과

- 파일: `docs/specs/2026-08-25-evidence-preparation-repair-design.md`
- 파일: `docs/specs/2026-08-25-context-md-artifact-transaction-design.md`
- 파일: `docs/specs/2026-08-25-session-completion-repair-design.md`
- 파일: `docs/specs/2026-08-25-session-zero-work-closure-design.md`
- 설계복귀 후보 2 SHA: d9d91391baece86f87ef3ea5612da76697e763ff
| issue | reviewed_sha | A1 | A2 | A3 | A4 | A5 | Critical | Major | verdict |
|---|---|---|---|---|---|---|---:|---:|---|
| #33 | `d9d91391baece86f87ef3ea5612da76697e763ff` | high | PASS | PASS | PASS | PASS | 0 | 0 | PASS |
| #38 | `d9d91391baece86f87ef3ea5612da76697e763ff` | high | RETURN | RETURN | PASS | RETURN | 0 | 1 | RETURN |
| #34 | `d9d91391baece86f87ef3ea5612da76697e763ff` | high | RETURN | RETURN | PASS | RETURN | 0 | 2 | RETURN |
| #39 | `d9d91391baece86f87ef3ea5612da76697e763ff` | high | RETURN | RETURN | PASS | RETURN | 0 | 2 | RETURN |
- 검수 횟수 반영: #33 4/4, #34·#38·#39 각 2/3
- Major 1: #38 immutable manifest가 #33 prepared evidence/proof를 보존하지 않음
- Major 2: normal/zero binding별 run root lock이 같은 UUID의 서로 다른 variant 실행을 직렬화하지 않음
- Major 3: #34 marker 전 live 전체-corpus fingerprint 재검증이 정상 후속 mutation 뒤 과거 closure를 깨뜨림
- Major 4: #39 첫 terminal report 뒤 zero head 기록 전 crash 복구가 정의되지 않음
- 판정: #33만 설계확정. #38·#34·#39는 설계복귀 상한 도달 상태로 중지하며 추가 수정·재검수하지 않음

## 설계복귀 후보 3 마지막 독립 검수 입력

- 파일: `docs/specs/2026-08-25-context-md-artifact-transaction-design.md`
- 파일: `docs/specs/2026-08-25-session-completion-repair-design.md`
- 파일: `docs/specs/2026-08-25-session-zero-work-closure-design.md`
- 선행 확정 계약: `docs/specs/2026-08-25-evidence-preparation-repair-design.md`의 #33 PASS 본문은 변경하지 않고
  #38 handoff 기준으로만 읽음
- 설계복귀 후보 3 SHA: 1224153b105871281147d502834249d59dbbf98b
- 검수 횟수: #38·#34·#39 각각 남은 마지막 1회를 사용해 3/3으로 셈
- 통과: 각 issue row가 `reviewed_sha=$CANDIDATE_SHA`, `A1=high`, `A2~A5=PASS`, `Critical=0`,
  `Major=0`, `verdict=PASS`
- 중지: 어느 row든 Major 또는 계약 공백이 하나라도 남으면 후보·검수·설계복귀 상한이 모두 끝났으므로
  추가 수정·재검수·구현·GitHub 변경 없이 사용자에게 반환함

```bash
test -z "$(git status --porcelain)"
test "$(git rev-parse "$RECEIPT_SHA^")" = "$CANDIDATE_SHA"
test "$(git diff --name-only "$CANDIDATE_SHA..$RECEIPT_SHA")" = \
  ".goal/brain-ticket-reconcile-v2/progress.md"
git show "$RECEIPT_SHA:.goal/brain-ticket-reconcile-v2/progress.md" | \
  grep -F -- "설계복귀 후보 3 SHA: $CANDIDATE_SHA"
for spec in \
  docs/specs/2026-08-25-context-md-artifact-transaction-design.md \
  docs/specs/2026-08-25-session-completion-repair-design.md \
  docs/specs/2026-08-25-session-zero-work-closure-design.md; do
  git show "$CANDIDATE_SHA:$spec" >/dev/null
done
git diff --check aca39f4.."$CANDIDATE_SHA" -- \
  .goal/brain-ticket-reconcile-v2/progress.md docs/specs/2026-08-25-*-design.md
git diff --check "$CANDIDATE_SHA..$RECEIPT_SHA" -- \
  .goal/brain-ticket-reconcile-v2/progress.md
```

기대값은 clean fixed candidate, progress-only 직계 receipt, diff 오류 0개다. reviewer는 candidate blob만
설계 본문으로 보고 receipt는 candidate SHA와 횟수 확인에만 사용한다.

## 설계복귀 후보 3 마지막 독립 검수 결과

- 검토 후보: `1224153b105871281147d502834249d59dbbf98b`
- progress-only 직계 receipt: `09204683bc9938c0fdce3dce560e34e606d569b8`
- 검토 경계: 새 독립 문맥이 candidate blob만 설계 본문으로 읽고 receipt는 후보 SHA·횟수 확인에만 사용함
- 구조 확인: candidate는 `aca39f4`의 직계 자식이며 progress와 대상 spec 3개만 변경, receipt는 candidate의
  직계 자식이며 progress의 후보 SHA 한 줄만 변경, 두 범위 `git diff --check` 오류 0개
- A1 표기: reviewer 응답의 `PASS`는 세 티켓을 모두 high risk로 분류한 것이 맞다는 뜻이며 아래 gate 값은
  goal-loop 원형대로 `high`로 기록함

| issue | reviewed_sha | A1 | A2 | A3 | A4 | A5 | Critical | Major | verdict |
|---|---|---|---|---|---|---|---:|---:|---|
| #38 | `1224153b105871281147d502834249d59dbbf98b` | high | PASS | PASS | PASS | PASS | 0 | 0 | PASS |
| #34 | `1224153b105871281147d502834249d59dbbf98b` | high | PASS | PASS | PASS | PASS | 0 | 0 | PASS |
| #39 | `1224153b105871281147d502834249d59dbbf98b` | high | PASS | PASS | PASS | PASS | 0 | 0 | PASS |

- #38: #33 `prepared_evidence` 원문·target·Markdown hash·두 seal을 immutable manifest에 결속하고
  receipt/report가 같은 manifest를 참조하며 committed recovery는 live evidence를 다시 실행하지 않음
- #34: UUID 공용 `runner.lock`이 normal·zero를 binding·variant 경계 너머로 직렬화하고 immutable receipt
  lineage와 report fsync가 이후 정상 mutation과 무관한 historical closure 기준점을 제공함
- #39: 최초 유일 tip은 head-only create, parent head 뒤 유일 child tip은 head-only advance로 report→head
  사이 crash를 복구하며 비최초 head 누락·다중 tip은 conflict로 닫음
- 별도 저장소 표준 축: 위반·설계 냄새 0건
- 검수 횟수 반영: #38·#34·#39 모두 3/3
- 판정: #33·#38·#34·#39 모두 설계확정. 이 판정은 구현·child issue 생성·GitHub 변경·main 병합 권한을
  추가하지 않음

## 보존 확인

- main WIP 상태 목록 SHA-256: `7be3dcf9c6a119de8c273c7ea804962f477d9921f809dd8161eb3ad75a6a04b9`
- #33 원본 WIP diff SHA-256: `8d9385dab45cd9ea159353354a18fbd1316b79ea6116bc845ecaaac339936b32`
- 후보 1 고정 뒤 재확인: 두 hash 모두 기준값과 exact 일치
- 후보 2 commit 전·GitHub 변경 뒤 재확인: 두 hash 모두 기준값과 exact 일치
- 설계복귀 후보 2 commit 전 재확인: main status는 `git status --short --untracked-files=all`, #33은
  `git diff` 기준으로 두 hash 모두 exact 일치
- 설계복귀 후보 3 최종 검수 뒤 재확인: main status와 #33 WIP diff 두 hash 모두 exact 일치

## GitHub 적용 확인

- #3 blocked by `[34,39]`
- #10 blocked by `[4,6,33,38]`
- #33 blocked by `[]`
- #34 blocked by `[33]`
- #38 blocked by `[33]`
- #39 blocked by `[34]`
- #3·#10·#33·#34·#38·#39: 모두 OPEN, labels exact `enhancement,needs-triage`
- Wayfinder 다섯 label이 붙은 issue: 모두 0개
- local main·origin/main·실제 원격 main: `b35d351ee77093392ca170f799d0edc1a8414070`
