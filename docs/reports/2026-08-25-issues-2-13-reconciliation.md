# GitHub #2~#13 구현·계약·티켓 재정리 보고서

- 작성일: 2026-08-25
- 범위: Project Brain 엔진 코드, 테스트, 문서, `mooh1222/project-brain` Issues
- 제외: agent-team 엔진, Run, task, terminal 상태
- main 기준: `c1b7293cb124d2b46bd37140e15d23b20cbc104e`
- 재검수한 구현 후보: `75e97fa98308b8bd7434070e05a99e69f2a5adef`
- 정리 branch: `codex/brain-ticket-reconcile-20260825`

## 결론

`75e97fa`는 #2~#10의 코드 기반을 크게 구현했지만 그대로 main에 넣고 티켓을 닫을 수 있는
후보는 아니다. 독립 Standards·Spec 검수에서 다음 세 종류가 분리됐다.

1. 명세가 이미 충분한 구현 결함: EvidenceRef의 일반 locator 변경이 verification의 evidence
   binding에 들어가지 않았고, 공개 `promote`는 CodeLocator readiness를 계산한 뒤에야 repo
   context를 해석했다.
2. 구현보다 계약이 먼저 필요한 공백: session marker와 canonical completion report의 결속,
   공개 ingest/projection 명령에서 verification·dedicated proof를 준비하는 경계, execution
   receipt의 발급 주체와 provenance. 이 공백 때문에 현재 후보의 기본 `ingest()`는 정상
   EvidenceManifest bundle도 `dedicated_proof_missing`으로 거부한다.
3. 문서 상태 드리프트: capability, candidate verification, ReviewRecord, dedicated proof,
   snapshot 동결 범위가 architecture와 ROADMAP에 충분히 반영되지 않았다.

따라서 #2~#10은 모두 open을 유지한다. 명확한 locator 결함은 TDD로 먼저 고쳤고, 나머지는 두
repair design으로 설계 복귀했다. #11~#13은 현재 본문만으로 구현에 들어가지 않고 `RETURN`으로
돌려 세부 상태·효과 소유자와 공개 관측점을 먼저 고정한다.

## 기준 후보에서 구현된 것

| 이슈 | 구현 후보 | 현재 코드에 존재하는 동작 | 아직 완료로 보지 않는 이유 |
|---|---|---|---|
| #2 | `9aefa36`, `d5ae24a` | query 단순 확인의 no-write 경계, 기본 audit의 read-only 동작과 명시적 fetch/cache 쓰기 | 정리 branch에서 architecture·ROADMAP을 동기화했으며 최종 후보 검수·main 반영이 남음 |
| #3 | `55efcd0`, `29f48ea`, `32b0b4e` | 조립 검증 묶음의 명시 판정, batch `no_changes` finalization, 실패 시 재개 정보, session-ingest 안내 보강 | `session mark-processed`가 canonical 영수증 없이 쓸 수 있고 zero-work·unresolved 계약이 닫히지 않음 |
| #4 | `698dc3e`, `bac51f7` | 19종 capability registry와 mutation·promotion 소비 경계 | 정리 branch에서 문서 지도를 맞췄고 최종 exact-candidate 검수·main 반영이 남음. 일부 profile policy는 아직 여러 모듈의 staged registry로 나뉨 |
| #5 | `160050c`, `71430a9` | snapshot v1·v2가 동결된 19종 kind/storage 범위를 쓰고 v1 mode 한계를 fail-closed 처리 | 전체 회귀와 main 반영 전에는 종료하지 않음 |
| #6 | `6b3c4fe`, `b8d8926` | common candidate verification v1, 현재 store 기준 ready/unverified/stale/blocked 계산, promote 시 ReviewRecord 결속 | locator 결함이 있었고, 설치 CLI에서 verification을 준비하는 공개 경로가 없음 |
| #7 | `4c69f61`, `5549f1b`, `c15ef5e` | EventLedgerRecord·TemporalFact·CodeLocator profile과 종류별 현재 근거 결속 | 기준 후보의 CodeLocator CLI context 전달 결함은 정리 branch에서 수리했지만 #6 공개 준비 경계 회귀가 남음 |
| #8 | `0ba91db`, `45bbe2f`, `d1c2bf0` | DomainContext·DecisionRecord·`prompt_payload` projection profile | #6 경계와 projection variant별 공개 경로 검증이 남음. GlossaryTerm과 DomainMapping은 각각 #13·#12 범위임 |
| #9 | `415c600` 이후 dedicated proof 묶음 | EvidenceManifest·SpecDocument·SpecRevision·SlideRef·SlackThread capture material과 mutation gate | caller가 raw receipt ID를 줄 수 있고 공개 ingest가 proof를 준비·전달하지 않음 |
| #10 | `06597d5` 이후 dedicated proof 묶음 | CurrentView·KnowledgePage·Insight·`context_md` projection의 source 결속과 mutation gate | 실제 builder가 없는 종류의 Adapter 역할, receipt provenance, projection 공개 경로가 남음 |

커밋 표는 구현이 어느 후보에 들어 있는지 찾기 위한 지도다. 개별 커밋이나 과거 테스트 통과를
완료 증거로 쓰지 않는다.

## 독립 검수 결과

### Standards — 기준 후보 검수 당시

- 중요: `candidate.verification`, 확장된 ReviewRecord, mutation manifest의 dedicated proof가
  data/runtime/change map에 없다.
- 중요: ROADMAP이 여전히 "진행 중인 작업 없음"으로 되어 있어 #2~#10 후보와 남은 공백을
  가린다.
- 판단 제안: capability registry와 verification/dedicated proof profile registry의 역할을
  staged policy로 명시하거나 후속 ticket에서 한 resolver로 모아야 한다.
- 판단 제안: timezone-aware 실행 시각 검사가 common verification 모듈 사이에 중복돼 있다.

### Spec

- 치명: 일반 EvidenceRef locator가 바뀌어도 evidence binding이 같아 `ready`가 유지됐다.
- 치명: 공개 `promote`가 repo context 없이 CodeLocator verification을 먼저 평가해, 내부 API에서
  준비 완료인 후보도 CLI에서는 `verification_not_ready: evidence_changed`로 실패했다.
- 치명: verification·dedicated proof 생성 함수는 Python 내부에만 있고 공개 `ingest` 입력과
  이어지지 않았다. 기본 `MutationService`는 reviewed EvidenceManifest create/update에 proof를
  요구하므로 기존 정상 bundle도 `dedicated_proof_missing`으로 실패한다. 일반 CLI·ingest 테스트는
  `MutationService(dedicated_proof_profiles=())`를 주입해 이 회귀를 숨긴다.
- 치명: session 완료 marker가 canonical batch/finalization receipt를 검증하지 않는다.
- 계약 공백: capture·derived receipt ID를 누가 어떤 현재 source와 실행 정보에서 발급하는지가
  닫혀 있지 않다.
- 계약 공백: capability가 common으로 선언한 `DomainMapping`은 구현 profile이 없는데 #12가 이미
  target별 verification이 있다고 전제한다. #12 재설계가 profile 자체를 먼저 포함해야 한다.
- 범위 확장: 발견하지 못했다.

## 이번 정리 branch에서 먼저 닫은 결함

EvidenceRef locator 변경은 아래 public Python seam에서 RED를 만든 뒤 최소 수정했다.

```text
prepare_candidate_verification
  -> locator 변경
  -> evaluate_candidate_verification
  -> stale / evidence_changed
```

`verification._direct_evidence_rows()`가 nested code locator뿐 아니라 `/locator` 전체의 stable JSON
hash도 결속한다. evidence projection은 기존 표시를 조용히 재정의하지 않고
`verification-evidence-v2`로 올렸다. v1 WIP envelope가 `stale/evidence_changed+rules_changed`가 되는
전이와 locator 변경 회귀를 함께 고정했다. 현재 표적 결과는 `tests/test_verification.py` 18 passed다.

이 수리는 locator 전체 값의 변경 감지만 닫는다. locator가 가리키는 외부 source bytes를 실제로
다시 해석하는 capture Adapter 계약은 공개 evidence preparation repair가 따로 소유한다.

CodeLocator 공개 승격은 아래 CLI seam에서 별도 RED를 만든 뒤 최소 수정했다.

```text
cli promote
  -> repo context 해석
  -> promote(..., repo_context=...)
  -> fresh verification을 ReviewRecord에 결속
  -> 같은 repo context로 mutation 적용
```

기준 후보에서는 `promote()` 호출 뒤에 repo context를 해석해
`verification_not_ready: evidence_changed`로 실패했다. 정리 branch는 context를 먼저 해석해
검증과 mutation에 같은 값을 넘긴다. 새 공개 CLI 회귀와 기존 promote 2개를 함께 실행한 표적 결과는
`3 passed`다.

## 설계 복귀 결과

- [후보 검증·전용 증거 공개 쓰기 경계 보강 설계](../specs/2026-08-25-evidence-preparation-repair-design.md)
  - 기존 `ingest`·`promote`·projection 명령의 소유권을 유지한다.
  - 공통 내부 `EvidencePreparation` seam과 base snapshot → projected store → evidence → sealed
    unstamped intent 단계를 둔다.
  - evidence는 lock 밖에서 준비하고 exclusive lock 안에서 action·before·source·profile을 다시
    확인한 뒤 mutation clock을 한 번만 적용한다.
  - execution receipt와 mutation receipt를 분리하고 caller가 proof/receipt ID를 만들지 못하게
    한다.
  - `context_md` object와 generated file을 같은 journal로 적용·복구하고 locator 변경 시 이전
    artifact도 같은 transaction에서 제거한다.
- [세션 적재 완료와 처리 marker 결속 보강 설계](../specs/2026-08-25-session-completion-repair-design.md)
  - `session complete --transcript --report`만 marker v2를 쓸 수 있다.
  - transcript, 검증 groups, planned objects, batch receipts, finalization을 closure ID로 결속한다.
  - committed, no_changes, zero_objects, unresolved 상태와 재시도·legacy marker 의미를 분리하고,
    unresolved가 하나라도 있으면 v1은 item 실행 전 멈춘다.

두 문서는 목표 계약이며 현재 구현됐다고 읽으면 안 된다. 세 차례 독립 설계 검수에서 나온 마지막
Major를 반영했지만, 검수 상한 뒤 최신 수정본의 최종 독립 확인은 별도 design ticket으로 넘긴다.
그 ticket이 닫히기 전에는 90분 구현 child를 발행하거나 dispatch하지 않는다.

## 티켓 상태 결정

| 범위 | 현재 판정 | 처리 원칙 |
|---|---|---|
| #1 | 진행 중 parent | 날짜가 붙은 진행표와 repair child를 연결하되 전체 child와 human gate 전에는 닫지 않음 |
| #2~#10 | 부분 구현, open 유지 | 최종 후보가 main에 들어가고 exact-candidate review·정해진 회귀 증거가 남은 뒤에만 종료 |
| #3 | 설계 복귀·triage | session completion design ticket이 최신 수정본을 최종 확인한 뒤 구현 child를 발행 |
| #6·#9·#10 | 설계 복귀·triage | evidence preparation design ticket이 최신 수정본을 최종 확인한 뒤 foundation/public Adapter child를 발행 |
| #7·#8 | profile 부분 구현, #6 의존 | 종류별 내부 계산은 있으나 public preparation repair 뒤 공개 경계 회귀가 필요 |
| #11 | `RETURN` | direct reviewed create와 meaningful update/history를 상태표와 구현 ticket으로 분리 |
| #12 | `RETURN` | bundle target별 history·부분 갱신·legacy 계약을 설계와 구현으로 분리 |
| #13 | `RETURN` | GlossaryTerm candidate/reviewed 자격, 독립 verifier, 모든 쓰기 경로·audit 적용을 분리 |
| #14~#32 | 미착수 유지 | 기존 dependency 순서를 바꾸지 않고 앞 계약이 닫힐 때 하나씩 admission 재검토 |

#11~#13은 동시에 코드를 쓰지 않는다. 서로 dependency가 풀리더라도 verification, mutation,
schema, promote 파일이 겹치므로 한 shared-checkout writer가 #11 → #12 → #13 순서로 처리한다.
읽기 전용 설계·검수만 병렬화한다.

## 현재 정리 후보 검증

- 엔진 합성 회귀: `2186 passed, 136 subtests passed`
- 설치 ingest runtime: `Ran 125 tests`, `OK`
- architecture 문서 계약: `15 passed`
- locator v2·CodeLocator promote·문서 표적 묶음: `43 passed`
- `git diff --check`: 통과

설치 runtime의 첫 실행에서는 격리 worktree에 `.venv`가 없어 batch runner 자식 프로세스가 다른
Python을 잡았고 `tree_sitter` import 실패 3건이 났다. 엔진 checkout의 `.venv/bin`을 `PATH`와
`PYTHONPATH`에 함께 명시해 동일 3건과 전체 125건을 다시 실행하자 통과했다. 후보 동작 실패가 아니라
검증 환경 provenance 문제였으므로 성공 명령에는 두 경로를 모두 명시한다.

이번 정리 branch는 index 입력이나 실코퍼스 schema를 새로 바꾸지 않았고, 아직 public evidence
preparation을 구현하지도 않았다. 따라서 실모델 rebuild나 소비 데이터 전체 회귀는 실행하지 않는다.

## 다음 실행 순서

1. architecture·ROADMAP 현행화와 GitHub 진행 댓글·라벨·dependency 정리
2. 두 repair design 최신 수정본의 최종 독립 확인 ticket 처리
3. 확인된 session completion과 evidence preparation을 90분 이하 child ticket으로 순차 발행
4. 각 child를 TDD → 후보 commit 고정 → exact-candidate Standards/Spec review → 필요 시 새 수리 후보
   순서로 처리
5. #2~#10 통합 후보를 다시 고정하고 전체 엔진·설치 runtime 회귀
6. 필요 축만 소비 데이터 회귀하고, index 입력을 바꾸지 않았으므로 실모델 rebuild는 하지 않음
7. main 반영·push 뒤 증거 댓글과 dependency 순서로 #2~#10 종료
8. #11의 설계 ticket admission부터 자체 ticket loop 시작

현재 단계에서는 main merge, main push, #2~#10 close를 실행하지 않는다.

### public ingest 재현

현재 checkout의 product `ingest()`에 `EvidenceManifest`, `EvidenceRef`, `DomainContext`, candidate
`GlossaryTerm`의 정상 direct coverage bundle을 넘기면 다음 결과가 난다.

```text
dedicated_proof_missing
manifest.neutral.source: reviewed create/update requires dedicated proof
```

따라서 `75e97fa`는 단순 기능 미완성이 아니라 기존 공개 적재 경로 회귀를 포함한 통합 후보이며,
evidence preparation repair 전에는 main에 반영하면 안 된다.
