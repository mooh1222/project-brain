# Brain 티켓 정리 진행 기록

- 범위: GitHub #2~#10 구현 후보를 현재 엔진 기준으로 재검수하고, 코드·문서·티켓 상태를 맞춘 뒤 #11~#13 진입 여부를 결정한다.
- 기준점: `c1b7293cb124d2b46bd37140e15d23b20cbc104e`
- 후보 1: `75e97fa98308b8bd7434070e05a99e69f2a5adef`
- 조율자: 현재 Codex 세션 한 곳
- 실행 방식: Brain 저장소와 GitHub Issues만 사용하며 agent-team 상태·실행기는 사용하지 않는다.
- 티켓당 사람 개입 없는 실행 시간: 90분
- 진행 판정 간격: 45분
- 티켓당 후보: 3개
- 티켓당 검수: 3회
- 티켓당 설계 복귀: 1회
- 티켓당 전체 검사: 2회
- 공통 현재 시각: 2026-08-25 Asia/Seoul

## 후보 1 검수 1 판정

- Standards: 중요 2건(아키텍처 지도, ROADMAP 드리프트), 판단 제안 2건(capability 정책 분산, 시간 검사 중복).
- Spec 계약 위반: #3 완료 marker 영수증 미검증, #6 일반 locator 변경 미감지, #6~#10 공개 ingest 전달 경로 누락. 기본 `ingest()`는 reviewed EvidenceManifest를 proof 없이 보내므로 `dedicated_proof_missing`으로 실패한다.
- Spec 계약 공백: #3 marker가 소비할 canonical report와 UUID 결속, #9·#10 capture/builder receipt의 발급 주체와 검증 원본이 정해지지 않음.
- 판정: 후보 1 불합격. #3과 #9·#10, 그리고 연결된 proof 전달 seam은 설계복귀하고, 명확한 locator 결속 위반과 문서 드리프트만 첫 수리 후보로 보낸다.
- 범위 확장: 발견 없음.

## #2 query·audit 읽기 전용 WIP 안정화

- 단계: 검수
- 후보: 1 / 3
- 검수: 1 / 3
- 설계복귀: 0 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: 현재 정리 루프에서는 없음
- 마지막 갱신: 2026-08-25
- 다음 행동: 공통 아키텍처 지도 보강 뒤 완료 조건별 근거표를 확인한다.

## #3 ingest·session runtime WIP 안정화

- 단계: 설계복귀
- 후보: 1 / 3
- 검수: 3 / 3
- 설계복귀: 1 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: 현재 정리 루프에서는 없음
- 마지막 갱신: 2026-08-25
- 다음 행동: 검수 상한 뒤 최신 수정본을 새 design ticket에서 최종 확인하고 구현 티켓으로 분리한다.

## #4 19종 capability registry 확장 단계

- 단계: 구현
- 후보: 1 / 3
- 검수: 1 / 3
- 설계복귀: 0 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: 현재 정리 루프에서는 없음
- 마지막 갱신: 2026-08-25
- 다음 행동: capability의 현재 역할과 아직 분산된 런타임 경계를 아키텍처 지도에 명시한다.

## #5 snapshot v1·v2의 19종 대상을 동결

- 단계: 검수
- 후보: 1 / 3
- 검수: 1 / 3
- 설계복귀: 0 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: 현재 정리 루프에서는 없음
- 마지막 갱신: 2026-08-25
- 다음 행동: 후보 2에서 snapshot 완료 조건별 표적 회귀를 다시 확인한다.

## #6 EvidenceRef로 공통 verification 첫 경로 완성

- 단계: 설계복귀
- 후보: 1 / 3
- 검수: 3 / 3
- 설계복귀: 1 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: 일반 EvidenceRef locator가 바뀌면 `stale/evidence_changed`로 다시 계산되고, 기존 v1 WIP evidence projection은 v2 규칙에서 stale 처리됨 (`tests/test_verification.py`, 18 passed)
- 마지막 갱신: 2026-08-25
- 다음 행동: 검수 상한 뒤 최신 evidence preparation 수정본을 새 design ticket에서 최종 확인한다.

## #7 사건·시간·코드 verification profile 연결

- 단계: 검수
- 후보: 1 / 3
- 검수: 1 / 3
- 설계복귀: 0 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: 공개 `promote`가 CodeLocator 준비 때와 mutation 때 같은 repo
  context를 사용함 (새 CLI 회귀 + 기존 promote 회귀 2개, 3 passed)
- 마지막 갱신: 2026-08-25
- 다음 행동: #6 설계복귀 결과를 반영한 공개 ingest 경로에서 표적 회귀를 확인한다.

## #8 도메인·결정·prompt projection verification profile 연결

- 단계: 검수
- 후보: 1 / 3
- 검수: 1 / 3
- 설계복귀: 0 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: 현재 정리 루프에서는 없음
- 마지막 갱신: 2026-08-25
- 다음 행동: #6 설계복귀 결과를 반영한 공개 ingest 경로에서 표적 회귀를 확인한다.

## #9 원출처 캡처 객체의 전용 증거 경로

- 단계: 설계복귀
- 후보: 1 / 3
- 검수: 3 / 3
- 설계복귀: 1 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: 현재 정리 루프에서는 없음
- 마지막 갱신: 2026-08-25
- 다음 행동: 최신 evidence preparation 수정본 최종 확인 뒤 local observation과 remote capture 티켓을 분리한다.

## #10 파생·종합 객체의 전용 증거 경로

- 단계: 설계복귀
- 후보: 1 / 3
- 검수: 3 / 3
- 설계복귀: 1 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: 현재 정리 루프에서는 없음
- 마지막 갱신: 2026-08-25
- 다음 행동: 최신 evidence preparation 수정본 최종 확인 뒤 output validation, 실제 builder, artifact transaction 티켓을 분리한다.

## #11 직접 reviewed 생성·의미 갱신과 단일 검수 이력

- 단계: 준비
- 후보: 0 / 3
- 검수: 0 / 3
- 설계복귀: 0 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: 없음
- 마지막 갱신: 2026-08-25
- 다음 행동: #2~#10 정리 후 입장 조건 A1~A5 판정을 반영한다.

### 입장 판정

- 결과: RETURN
- 이유: 상태 조합표·효과 소유자와 완료 조건별 정확한 검증 관측이 없고, legacy·재시도·시각 소유권 결정이 비어 있다.
- 재개 조건: #6 완료 후 direct reviewed 생성, 단일 ReviewRecord history, transaction·재시도 계약을 분리해 명세를 보강한다.

## #12 DomainMapping 묶음의 대상별 검수 이력

- 단계: 준비
- 후보: 0 / 3
- 검수: 0 / 3
- 설계복귀: 0 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: 없음
- 마지막 갱신: 2026-08-25
- 다음 행동: DomainMapping common profile 자체와 bundle 대상별 이력·부분 갱신을 분리해 재설계한다.

### 입장 판정

- 결과: RETURN
- 이유: capability는 common verification을 요구하지만 실제 DomainMapping profile이 없고, 이슈 본문은 이미 target별 verification이 있다고 전제한다.
- 재개 조건: profile 검사·authority·직접 근거 projection을 먼저 고정하고, 그 위에 bundle history 상태표와 legacy 전이를 올린다.

## #13 GlossaryTerm 공통 자격 관문과 verification profile

- 단계: 준비
- 후보: 0 / 3
- 검수: 0 / 3
- 설계복귀: 0 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: 없음
- 마지막 갱신: 2026-08-25
- 다음 행동: candidate 최소 문턱, reviewed 전체 자격, 독립 verifier, audit·migration 적용을 구현 티켓으로 나눌 설계를 만든다.

### 입장 판정

- 결과: RETURN
- 이유: 한 티켓이 모든 쓰기 경로와 migration·audit까지 묶지만 상태 조합, 각 효과 소유자, 90분 구현 경계가 없다.
- 재개 조건: #6과 #11 계약 뒤 candidate/reviewed 자격과 공개 관측을 분리해 다시 admission 한다.
