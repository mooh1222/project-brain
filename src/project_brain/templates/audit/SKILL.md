---
name: {{PROJECT}}-brain-audit
description: |
  Use when {{PROJECT}} Brain 코퍼스의 무결성, 고립 객체, 오래된 코드 근거, 인용문 상태를
  점검할 때. "brain 점검", "코퍼스 상태", "stale 체크", "고아 객체" 요청에서는
  읽기 전용 진단을 먼저 실행하고 수정은 sibling ingest 스킬로 넘긴다.
---

# {{PROJECT}} Brain 코퍼스 감사 (audit)

감사는 코퍼스 상태를 **먼저 보고**하는 진단 절차다. 무결성, 고립 객체, 코드 드리프트와
정확한 코드 인용 검증을 함께 보되, 기본 실행은 읽기 전용이다. 객체 연결·수정·제거는 감사
결과와 명시적인 수정 요청이 모두 있을 때 `{{PROJECT}}-brain-ingest`로 넘긴다.

## 기본 실행

```bash
project-brain audit 2>/dev/null | jq
```

이 명령은 현재 로컬 Git 상태를 기준으로 lint, 고립 객체, stale/reachability, exact quote를
검사하지만 원격 fetch와 stale cache 쓰기는 하지 않는다. Git 오류나 `anchor_unverifiable`은
성공으로 바꾸지 않는다. `not_ancestor`는 아직 기본 브랜치에 합쳐지지 않은 앵커를 알리는
경고이며, 그 자체로 실패나 상태 강등 사유가 아니다.

사용자가 최신 원격 기준 검사와 query/show용 stale advisory 갱신을 명시적으로 요청한 경우에만
다음 쓰기 실행을 사용한다.

```bash
project-brain audit --fetch --write-stale-cache 2>/dev/null | jq
```

Git 저장소가 없는 환경에서는 `project-brain audit --no-stale`을 쓴다. 이때 Git 기반 검사와
exact quote 검사를 건너뛰므로 `code_quotes.check_skipped=true`가 통과를 뜻하지 않는다.

`audit`, `stale-check`, `mark-checked`는 config의 `default_branch`를 그대로 쓴다. 여기의
`{{DEFAULT_BRANCH}}`는 설치 시 그 configured default_branch로 렌더된다. 특정 브랜치 이름을 규칙으로
가정하지 않는다.

## 세 신호 읽기

| 필드 | 의미 | 처리 |
|---|---|---|
| `lint.problems` | 끊긴 참조(가리키는 대상 없음) | 비어야 정상. 있으면 참조를 잇거나 끊긴 객체 정정 |
| `isolated.isolated` | 아무도 안 가리키는 잎(CodeLocator·GlossaryTerm·EvidenceRef) | 연결·의도적 종착점·제거 후보와 근거를 보고 |
| `stale.target_head` | 확인에 사용한 {{DEFAULT_BRANCH}} HEAD | `mark-checked --checked-head`에 그대로 쓴다 |
| `stale.unmerged_anchors` | 기본 브랜치 조상이 아닌 앵커와 이유 | `not_ancestor`는 advisory, `anchor_unverifiable`은 실패로 처리 |
| `locators[].stale` | 코드 좌표의 변경 상태 | quote 유무와 독립적으로 항상 판정 |
| `locators[].code_quote` | exact quote 상태 | `code_quote=missing`은 stale이 아니라 인용 부채 |
| `locators[].quote_access` | 인용 공개 가능 상태 | stale·quote 일치와 독립적으로 판단 |
| `code_quotes.checked` | 저장된 인용문을 실제로 대조한 수 | 검사 완료 수로 보고 |
| `code_quotes.skipped` | 인용문 부재 등으로 대조하지 않은 수 | 옛 인용 부채로 따로 보고 |
| `code_quotes.failures` | 불일치·오류 목록 | ID와 이유를 보고 |

## stale 후보 처리 (검수 정책 B+C)

코드를 직접 보고 판정한다. 자동 supersede나 객체 수정은 없다.

- 의미가 정말 낡았으면 → `{{PROJECT}}-brain-ingest/references/judgment.md`로 의미를 판정하고
  `{{PROJECT}}-brain-ingest/references/update-rules.md`의 kind별 흐름으로 넘긴다. audit은 자동 판정·갱신하지 않는다.
- 바뀐 게 의미 무관(리팩터·이동·테스트 변경)이면 → `mark-checked` 후보와 근거를 먼저 보고한다.
- 확실히 애매하면 candidate로 남기고 사용자 확인.

## 정확한 코드 인용과 앵커 범위

`stale`과 quote 상태는 독립 축이다. `verified_quote`가 없어 `code_quote=missing`이어도 stale 검사를
건너뛰지 않는다. missing quote는 별도의 인용 부채로 보고, 좌표가 실제로 바뀐 stale과 섞어 세지 않는다.
quote가 있으면 locator의 commit/path가 가리키는 Git blob 바이트에서 exact match를 확인하며
공백·줄바꿈을 정규화하지 않는다. 인용을 새로 만들거나 고치려면 먼저 그 blob을 읽고 바이트 단위로
같은 텍스트를 기록한다. `quote_access`는 인용을 공개해도 되는지를 나타내는 또 다른 독립 축이다.

`reviewed`는 근거와 해석을 검증했다는 뜻이다. 작업 브랜치의 `unmerged` 여부는 별도의 범위
advisory다. 아직 합쳐지지 않았다는 이유만으로 검증된 prototype을 candidate로 내리지 않는다.

`ok=true`여도 모든 인용이 검사됐다고 말하지 않는다. `checked`, `skipped`, `failures`와 lint·고립·
stale 결과를 각각 보고한다. 실제 사용 품질과 검색 결과의 유용성은 별도 확인 대상이다.
