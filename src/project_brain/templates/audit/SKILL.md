---
name: {{PROJECT}}-brain-audit
description: |
  Use when {{PROJECT}} Brain 코퍼스의 무결성, 고립 객체, 오래된 코드 근거, 인용문 상태를
  점검할 때. 기본 브랜치 변경 뒤, 한 묶음 적재 뒤, 회수 이상 진단과 "brain 점검",
  "코퍼스 상태", "stale 체크", "고아 객체" 요청에서는 먼저 읽기 전용 진단을 실행하고,
  수정은 sibling ingest 스킬로 넘긴다.
---

# {{PROJECT}} Brain 코퍼스 감사

감사는 코퍼스 상태를 **먼저 보고**하는 진단 절차다. 코퍼스의 세 건강 신호인 무결성,
고립 객체, 코드 드리프트와 별도의 정확한 코드 인용 검증을 함께 본다. 객체 연결·수정·제거는
감사 결과와 명시적인 수정 요청이 모두 있을 때 `{{PROJECT}}-brain-ingest`로 넘긴다.

## 기본 실행

읽기 전용 진단은 fetch와 stale cache 쓰기를 모두 끈다.

```bash
project-brain audit --no-fetch --no-stale-cache-write 2>/dev/null | jq
```

이 명령은 현재 로컬 Git 상태를 기준으로 lint, 고립 객체, stale/reachability, 정확한 코드 인용을
검사하되 원격 브랜치를 당기거나 stale cache를 쓰지 않는다.

기본 명령이 보고하는 검사 범위는 `lint + Git stale/reachability + exact quote`다. Git 오류나
`anchor_unverifiable`은 성공으로 바꾸지 않는다. `not_ancestor`는 아직 기본 브랜치에 합쳐지지
않은 앵커를 알리는 advisory이며, 그 자체로 실패나 상태 강등 사유가 아니다.

사용자가 최신 원격 기준 감사와 이후 query/show의 stale advisory 갱신까지 요청하면
원격·캐시 갱신 audit을 실행한다.

```bash
project-brain audit 2>/dev/null | jq
```

Git 저장소가 없는 환경에서는 `project-brain audit --no-stale`을 쓴다. `--no-stale`는 Git 없는 환경에서만
사용하며, Git stale/reachability와 exact quote/`code_quotes` 검사를 함께 명시적으로 건너뛴다.
`code_quotes.check_skipped=true`는 코드 인용이 통과했다는 뜻이 아니다.

`audit`, `stale-check`, `mark-checked`는 config에 설정된 `default_branch`(configured default_branch)를 따른다.
설치 시 렌더된 `{{DEFAULT_BRANCH}}` 이름을 다른 브랜치로 추측해 바꾸지 않는다.

## 세 신호 읽기

| 필드 | 뜻 | 보고 방식 |
|---|---|---|
| `lint.problems` | 끊긴 참조·스키마 문제 | 개수와 객체 ID를 보고 |
| `isolated.isolated` | 아무도 가리키지 않는 잎 | 종류·ID·가능한 원인을 보고 |
| `stale.target_head` | 검사 기준 default branch HEAD | 이후 검토 기준으로 보존 |
| `stale.unmerged_anchors` | 기본 브랜치 조상이 아닌 앵커 | `not_ancestor`는 범위 경고, `anchor_unverifiable`은 실패 |
| `locators[].stale` | 저장된 코드 좌표 뒤 변경 여부 | quote 상태와 분리 |
| `locators[].code_quote` | 저장된 exact quote 상태 | missing·verified·mismatch를 분리 |
| `locators[].quote_access` | 인용 공개 가능 상태 | stale·quote 일치와 분리 |
| `code_quotes.checked` | 실제 인용문을 대조한 수 | 검사 완료 수로 보고 |
| `code_quotes.skipped` | 인용문 부재 등으로 대조하지 않은 수 | 별도 옛 부채로 보고 |
| `code_quotes.failures` | 불일치·오류 목록 | 실패 원인과 ID를 보고 |

`audit ok=true`는 구조·현재 실행한 코드 근거 검사가 통과했다는 뜻이다. `skipped`가 있으면 모든
인용문을 검증했다는 뜻이 아니다. 다음처럼 분리해 말한다.

- 저장된 인용문 중 `checked` 대상의 일치 여부
- 인용문이 없어 `skipped`된 옛 객체 수
- `failures`의 ID와 이유
- lint·고립·stale 결과

자동 관문은 코퍼스 구조와 저장된 코드 앵커 상태를 증명한다. 실제 사용 품질, 검색 결과의 유용성,
원문의 의도, 현재 서비스 입력에서의 동적 동작은 별도 확인 대상이다.

## stale 후보 판정

코드를 직접 확인한 뒤 다음 중 하나로 분류해 먼저 보고한다.

- 의미가 달라짐: DomainMapping 갱신 후보
- 코드 위치만 이동하거나 의미 없는 리팩터링: `mark-checked` 후보
- 판단 불가: 근거와 확인이 필요한 후보

`not_ancestor`는 아직 기본 브랜치에 합쳐지지 않은 범위 경고다. 그 이유만으로 reviewed 객체를
candidate로 내리지 않는다.

옛 `verified_quote` 누락은 적재 당시 검토됐지만 현재 저장 정보만으로 자동 재검증하기 어려운
상태인 별도의 인용 부채(`code_quote=missing`)다. 이를 처음부터 미검수라고 표현하지 않는다.
quote가 있으면 locator의 commit/path가 가리키는 Git blob 바이트에서 exact match를 확인하며
공백·줄바꿈을 정규화하지 않는다. 좌표·symbol·quote를 새로 쓰거나
`mark-checked`할 때는 현재 쓰기 계약인 full commit SHA, 실제 symbol·quote, 접근 가능한 기준
브랜치를 모두 만족해야 한다.

## 수정 경계

감사 결과만으로 객체를 바꾸지 않는다. 사용자가 수정을 요청하면 다음 순서로 진행한다.

1. 바꿀 객체와 근거, 승인 경로를 확정한다.
2. 의미 변경은 `{{PROJECT}}-brain-ingest/references/judgment.md`로 분류한다.
3. 실제 변경은 `{{PROJECT}}-brain-ingest/references/update-rules.md`와 적재 완료 게이트를 따른다.
4. `mark-checked`는 quote·full SHA·기준 브랜치 계약을 먼저 확인한 뒤 별도 쓰기로 실행한다.

고립 객체도 같은 경계다. 연결·의도적 종착점·제거 후보를 나눠 보고하고, 승인된 변경만 적재
흐름으로 처리한다. 고립 수를 0으로 만들기 위한 의미 없는 연결은 만들지 않는다.

## Common mistakes

| 실수 | 바로잡기 |
|---|---|
| 상태 확인 요청에서 원격·캐시 갱신 audit로 fetch/cache까지 변경 | 읽기 전용 명령으로 먼저 진단 |
| 고립 객체를 감사 중 바로 연결·제거 | 후보와 근거를 보고한 뒤 별도 수정 요청으로 처리 |
| `ok=true`를 전체 인용 검증 완료로 설명 | checked·skipped·failures를 따로 보고 |
| quote missing을 처음부터 미검수로 표현 | 옛 자동 재검증 부채로 설명 |
| stale과 quote·접근 권한을 한 상태로 합침 | 세 축을 독립 판정 |
| 자동 감사 통과를 실사용 품질 통과로 확대 | 검색·현재 코드·실제 입력 검증을 별도 관문으로 유지 |
