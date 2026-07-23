---
name: {{PROJECT}}-brain-audit
description: |
  Use when {{PROJECT}} brain 코퍼스 감사(건강검진)가 필요할 때 — {{DEFAULT_BRANCH}}를 당긴 뒤·대량 적재 후·
  주기 점검. "brain 점검", "코퍼스 상태 확인", "오래된 매핑/낡은 데이터 찾기", "stale 체크",
  "고아 객체 점검"처럼 {{PROJECT}} 맥락의 점검 요청이 나오면 스킬 이름 없이도 이 스킬을 쓴다.
  적재(쓰기)는 {{PROJECT}}-brain-ingest, 조회(읽기)는 {{PROJECT}}-brain-query 몫이다.
---

# {{PROJECT}} Brain 코퍼스 감사 (audit)

코퍼스의 세 건강 신호를 한 패스로 본다 — 무결성(끊긴 참조) · 고아(아무도 안 가리키는 잎) ·
코드 드리프트(brain이 가리키는 코드가 바뀜). stale은 결과를 캐시에 써서, 이후 query/show가
`stale_advisory`로 곁들이게 하는 **도는 주체**다(읽기·쓰기 양끝은 있는데 캐시를 채울 주체가 없으면
채널이 죽어 advisory가 한 번도 안 뜬다).

## 언제

- {{DEFAULT_BRANCH}}를 당긴 뒤 — 코드가 바뀌면 brain의 의미가 낡았을 수 있다(stale이 그걸 잡는다).
- 한 묶음 대량 적재 후 마무리 점검.
- 회상이 이상할 때 — 끊긴 참조·고아로 회수가 흔들리나 확인.

## 한 줄 실행

```bash
project-brain audit             # lint + graph isolated + stale-check(캐시 기록)
project-brain audit --no-stale  # Git 없는 환경에서만 stale/reachability를 명시적으로 건너뜀
```

출력은 `2>/dev/null | jq`로 읽는다(stdout=깨끗한 JSON, 노이즈는 stderr). 성공은 `lint + Git stale/reachability + exact quote`
검사가 모두 통과한 경우다. `--no-stale`는 Git 없는 환경에서만 명시적으로 건너뛴다. Git 오류나
`anchor_unverifiable`은 성공으로 처리하지 않는다. `not_ancestor`는 아직 기본 브랜치에 합쳐지지 않은
앵커를 알리는 advisory이며, 그 자체로 실패나 상태 강등 사유가 아니다.

`audit`, `stale-check`, `mark-checked`는 config의 `default_branch`를 그대로 쓴다. 여기의
`{{DEFAULT_BRANCH}}`는 설치 시 그 configured default_branch로 렌더된다. 특정 브랜치 이름을 규칙으로
가정하지 않는다.

## 세 신호 읽기

| 필드 | 의미 | 처리 |
|---|---|---|
| `lint.problems` | 끊긴 참조(가리키는 대상 없음) | 비어야 정상. 있으면 참조를 잇거나 끊긴 객체 정정 |
| `isolated.isolated` | 아무도 안 가리키는 잎(CodeLocator·GlossaryTerm·EvidenceRef) | 명백한 건 에이전트가 (a)즉시 연결 (b)의도적 종착점 유지 (c)제거, 애매한 것만 사용자 확인(검수 정책 B+C) |
| `stale.target_head` | 확인에 사용한 {{DEFAULT_BRANCH}} HEAD | `mark-checked --checked-head`에 그대로 쓴다 |
| `stale.unmerged_anchors` | 기본 브랜치 조상이 아닌 앵커와 이유 | `not_ancestor`는 advisory, `anchor_unverifiable`은 실패로 처리 |
| `code_quotes` | opt-in `verified_quote`의 정확한 인용 검사 결과 | 실패가 있으면 원문과 앵커를 다시 확인 |

## stale 후보 처리 (검수 정책 B+C)

audit이 캐시를 쓰면 그 다음부터 query/show에 `stale_advisory`(코드 바뀐 매핑 표시)가 뜬다.
코드를 직접 보고 판정한다 — **자동 supersede는 없다, 에이전트가 B+C로 판정**한다.

- 의미가 정말 낡았으면 → `{{PROJECT}}-brain-ingest/references/judgment.md`로 의미를 판정하고
  `{{PROJECT}}-brain-ingest/references/update-rules.md`의 kind별 흐름으로 넘긴다. audit은 자동 판정·갱신하지 않는다.
- 바뀐 게 의미 무관(리팩터·이동·테스트 변경)이면 → 의미는 그대로니 `mark-checked`로 그 시점
  {{DEFAULT_BRANCH}} sha 기준 검토 완료 표시(스냅샷만 갱신, 의미 불변):
  ```bash
  project-brain mark-checked --mappings <매핑id …> --checked-head <stale가 낸 target_head>
  ```
- 확실히 애매하면 candidate로 남기고 사용자 확인.

## 정확한 코드 인용과 앵커 범위

`verified_quote`가 있는 locator만 exact quote 검사 대상이다. 확인은 locator의 commit/path가 가리키는
Git blob 바이트에서 하며 공백·줄바꿈을 정규화하지 않는다. 인용을 새로 만들거나 고치려면 먼저 그 blob을
읽고 바이트 단위로 같은 텍스트를 기록한다.

`reviewed`는 근거와 해석을 검증했다는 뜻이다. 작업 브랜치의 `unmerged` 여부는 별도의 범위 advisory다.
아직 합쳐지지 않았다는 이유만으로 검증된 prototype을 candidate로 내리지 않는다. candidate는 근거나
의미가 불확실할 때만 쓴다.
