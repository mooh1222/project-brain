---
name: {{PROJECT}}-brain-audit
description: |
  Use when {{PROJECT}} brain 코퍼스 감사(건강검진)가 필요할 때 — develop를 당긴 뒤·대량 적재 후·
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

- develop를 당긴 뒤 — 코드가 바뀌면 brain의 의미가 낡았을 수 있다(stale이 그걸 잡는다).
- 한 묶음 대량 적재 후 마무리 점검.
- 회상이 이상할 때 — 끊긴 참조·고아로 회수가 흔들리나 확인.

## 한 줄 실행

```bash
project-brain audit             # lint + graph isolated + stale-check(캐시 기록)
project-brain audit --no-stale  # git 없는 환경 — lint·isolated만
```

출력은 `2>/dev/null | jq`로 읽는다(stdout=깨끗한 JSON, 노이즈는 stderr). `lint` 문제가 있으면 rc=1.

## 세 신호 읽기

| 필드 | 의미 | 처리 |
|---|---|---|
| `lint.problems` | 끊긴 참조(가리키는 대상 없음) | 비어야 정상. 있으면 참조를 잇거나 끊긴 객체 정정 |
| `isolated.isolated` | 아무도 안 가리키는 잎(CodeLocator·GlossaryTerm·EvidenceRef) | 명백한 건 에이전트가 (a)즉시 연결 (b)의도적 종착점 유지 (c)제거, 애매한 것만 사용자 확인(검수 정책 B+C) |
| `stale.detail` | 코드가 develop에서 바뀐 매핑(코드 드리프트). `cache_written`에 기록 | 후보는 B+C로 — 확실하면 의미 갱신, 애매하면 candidate. 처리는 아래 |

## stale 후보 처리 (검수 정책 B+C)

audit이 캐시를 쓰면 그 다음부터 query/show에 `stale_advisory`(코드 바뀐 매핑 표시)가 뜬다.
코드를 직접 보고 판정한다 — **자동 supersede는 없다, 에이전트가 B+C로 판정**한다.

- 의미가 정말 낡았으면 → `{{PROJECT}}-brain-session-ingest`의 "갱신 운용 규약"대로 supersede(매핑)/
  제자리 수정 + DecisionRecord 연결.
- 바뀐 게 의미 무관(리팩터·이동·테스트 변경)이면 → 의미는 그대로니 `mark-checked`로 그 시점
  develop sha 기준 검토 완료 표시(스냅샷만 갱신, 의미 불변):
  ```bash
  project-brain mark-checked --mappings <매핑id …> --checked-head <stale가 낸 target_head>
  ```
- 확실히 애매하면 candidate로 남기고 사용자 확인.
