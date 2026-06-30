# 적재 세션 회고 — ingest 스킬/문서 개선 요소

- 날짜: 2026-06-30
- 상태: **P0·P1 이번 구현 / P2·엔진앵커는 결정 후**
- 배경: bb2 럭키박스 구성품 표시(5.6) 적재 세션 회고. 적재→검증은 정상 완료(101객체 reviewed,
  lint 0, eval 10/10, 고립 0). 마찰은 전부 **스킬/문서 + 검증 절차** 쪽이고 엔진 코드 버그는 없다.
- 검증 방법: 4개 독립 리더가 단일 원본 templates(`src/project_brain/templates/ingest`)와 엔진
  소스를 file:line으로 대조. 그 결과를 실제 파일 재확인으로 보정.
- 인용한 file:line은 **작성 시점(2026-06-30) 스냅샷**이라 이후 편집으로 드리프트할 수 있다(날짜 기록).

## 발견 요약

| 순위 | 무엇 | 어디 | 성격 | 상태 |
|---|---|---|---|---|
| P0 | 고위험 객체 적대검증이 **재량** — 메모리를 근거로 쓴 허위 결정을 우연히만 잡음 | completeness-checklist.md 8번 | 실제 사고 방지 | 이번 구현 |
| P1 | 머지 전 적재 경계(커밋·푸시·PR오픈 + merge-commit)를 안 다룸 | scope.md | 매번 사용자에게 물음 | 이번 구현 |
| P1 | PR/jira manifest의 locator 형식 차이 + MANIFESTS 예시 pr 누락 | domain_spec.template.py, ingest-tools.md | 역설계 삽질 | 이번 구현 |
| P1- | decision용 evref id 형식 `evref.<ctx>.<type>-<ref>` 미문서 | ingest-tools.md | 사소 | 이번 구현 |
| P2 | SKILL.md ↔ references 중복(3축 표·판정 트리·history literal) → 길이 | SKILL.md + scope/judgment | 가독성 | **결정 후** |
| P3 | run_ingest exit 1이 "stale 가드 ≠ 적재 실패"를 안 알림 | run_ingest.sh | 일시 혼동 | 이번 구현(주석 1줄) |

## P0 — 적대검증이 의무가 아니다 (가장 중요)

세션의 유일한 치명 결함: 에이전트가 3일 전 메모리의 "주석을 4749→4800으로 정정했다"를 그대로
믿고 DecisionRecord를 만들었는데, 코드엔 4749가 한 군데도 없었다(적대검증자가 적재 직전 잡아 폐기·재작성).

- "메모리는 근거가 아니다"는 **이미 절대규칙 3 + checklist 8번에 있다**(SKILL.md:105-107). 그런데도 어겨졌다.
- 그 위반을 잡은 적대검증은 **파이프라인 의무 단계가 아니다**(run_ingest.sh에 없음, SKILL.md:262·291은
  B 조건으로 언급만). 이번엔 에이전트 재량으로 돌렸다. 안 돌렸으면 허위 reviewed 결정이 적재됐다.

→ 규칙은 있는데 어겨졌고, 잡은 안전장치는 우연이었다. **고위험 객체(DecisionRecord·supersede·
code anchor·history_coverage=complete)의 재구성 감사를 "선택"에서 "필수"로** 못 박는다.
checklist 8번 강화로 처리(엔진 자동 단계 추가는 후속 — 적대검증은 도메인 판단이라 코드로 강제하기 어려움).

## P0 후속 — 안전장치 B(verification_note 하드 게이트) 검토 후 폐기 (2026-07-01)

P0(적대검증 의무화)를 엔진측에서 더 받칠 안전장치로 "DecisionRecord에 verification_note 필드 신설 +
status=reviewed면 비어있을 때 거부"(설계 B)를 검토했다. 코드 짜기 전 4렌즈 적대 리뷰 + surface 리뷰 독립
교차검증(둘 다 인용 코드를 직접 대조) 결과 **전원 폐기 권고로 수렴 — 구현하지 않는다.**

- **왜 헛도장인가:** 럭키박스 결정은 evidence_refs가 비어있지 않았다(틀린 커밋이 달려 있었다). "비어있지
  않음" 검사는 그 사고를 못 잡는다 — verification_note든 evidence_refs든 "뭔가 채워라"일 뿐 "맞는 걸
  채워라"가 아니다. free-text라 lint dangling 검사조차 안 걸려 evidence_refs보다도 약하다. 엔진 schema는
  구문 층(빈값/존재)이라 "근거는 있는데 모순"이라는 의미 결함에 구조적으로 못 닿는다.
- **역효과:** 하드 게이트가 생기면 에이전트가 필드를 채우고 끝내, 럭키박스를 실제로 잡았던 자발적 적대검증을
  오히려 밀어낼 수 있다.
- **그래서 안전장치 본체는 P0다.** 단 리뷰가 짚은 한 가지: P0도 "적대검증 완료" 도장으로 퇴화하면 B와 같은
  실패다 — 핵심은 단계 존재가 아니라 진짜 반박 시도이고 코드로 강제 못 하는 행동 완화책이다(checklist 8번에
  이 한 줄 보강 완료).
- **별건으로 분리된 것:** DecisionRecord에만 reviewed→evidence_refs 규칙이 없는 비대칭은 진짜 위생 갭이나
  럭키박스 해법이 아니고 "2줄 미러"도 아니다(build_decisions가 candidate 폴백 없이 reviewed 무조건 → 하드
  거부 위험 + 기존 store는 validate가 안 봐 lint 스윕 별도 필요). 후순위 별도 티켓으로 분리:
  `docs/plans/2026-07-01-decisionrecord-evidence-refs-hygiene.md`.

## P1 — 머지 전 적재 경계

scope.md(17-18)는 "코드가 {{DEFAULT_BRANCH}}에 들어가 있다"만 조건으로 둔다. 이번처럼 "커밋·
푸시됨 + PR 오픈 + 머지 전 + merge-commit 레포(머지 후 SHA 보존)" 경계를 안 다뤄, 에이전트가
멈춰 물었고 squash 가정으로 한 번 오판했다(사용자 정정).

→ scope.md에 1-2줄: merge-commit이면 PR HEAD SHA를 앵커로 박아도 머지 후 보존되나, squash/rebase면
사라지니 레포 머지 정책 확인 후 시작.

## P1 — PR manifest 문서 (실제 갭은 좁았음)

리더는 "PR 지원이 거의 없다"고 봤으나, 실제로는 `domain_spec.template.py:22`의 evidence 타입에
이미 `commit|jira|pr`이 있고 `ingest-tools.md:51`도 "commit/jira/pr EvidenceRef"를 언급한다.
**진짜 갭은** (a) MANIFESTS 딕셔너리 예시(template:6-9)에 pr이 없음, (b) locator 형식 차이
(commit은 {repo,sha} 자동, jira/pr은 노트가 locator 제공)가 명시 안 됨.

→ domain_spec.template.py에 pr MANIFESTS 예시 한 줄 + ingest-tools.md build_decisions 설명에
locator 형식 차이 한 줄.

## P2 — SKILL.md ↔ references 중복 (결정 후)

SKILL.md 383줄 + references 935줄. 같은 내용을 본문과 참조에서 두 번 가르치는 곳:

- 3축(feature_done/current_ingest_done/history_coverage): SKILL.md:73-94 + scope.md:25-36 + checklist:19-28
- 판정 트리(대체/보완/충돌): SKILL.md:242-257 다이어그램 + judgment.md 산문
- history_coverage 리터럴: SKILL.md:84-89 + scope.md + checklist + object-model

→ 참조를 정본으로 두고 SKILL.md 본문을 핵심+포인터로 축소하면 길이가 준다. 단 이건 가독성·
교육 흐름에 영향 주는 **큰 surgical 작업**이라 미룬다. 미루는 근거는 "안전(P0/P1)보다 가독성이
뒤"라는 것이지 "엔진 앵커/리랭커와 함께"가 아니다 — SKILL.md 다이어트와 검색 가드 수정은 기술적
의존이 0이라, 엔진 결정을 기다리며 문서 정리가 인질로 잡혀선 안 된다. **독립적으로 결정·진행한다.**
도구는 /writing-skills 규율(스킬은 간결, 깊이는 참조)이 적합.

(역설 메모 — surface 리뷰 지적: 이번 회고 작업 자체가 그 줄이려는 파일들(checklist·scope·
ingest-tools)에 ~15줄 + CHANGELOG 한 단락을 더했다. P2 다이어트 때 이번에 추가한 줄도 같이 본다.)

공통화(스크립트 재사용)는 이미 건강하다: domain_spec.template.py(데이터) + extract_template.js
(추출) + assemble_notes.py normalize()(조립 — CASE 변형 영구 흡수) + ingest-case-log.md(추적).
추가 공통화 불필요, "변형 2회+ 반복 시 normalize()로 승격" 원칙만 유지.

## 검증

스킬 templates 수정 후: `tests/test_installer.py`로 manifest 보존(사용자 수정 파일 skip) 안 깨지는지
확인. bb2 반영은 별도 — 데이터 레포에서 install 재실행(채택)해야 사본에 전파됨.
