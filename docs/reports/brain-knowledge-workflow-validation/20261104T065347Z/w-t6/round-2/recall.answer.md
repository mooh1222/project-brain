> E3 당시 판정·관찰의 보존 사본이다. W-T1의 두 기록 세션은 개인 memory를 읽었으므로
> 이번 memory 비활성 통과 집계에서는 제외하고 재실행 결과로 교체한다.
> 작은 Markdown 산출물만 추적하며 JSONL·프로젝트·해시 원본은 로컬 전용이다.
> 링크는 추적 산출물로만 연결하고 원본 증거는 경로 텍스트로 표시했다.

정식 지식에는 **“예약 실행의 재시도 간격은 8초이며, 최대 세 번 재시도한다는 횟수 규칙과 독립적이다”**가 반영돼 있습니다.

| 구분 | 현재 확인된 내용 | 출처 |
|---|---|---|
| **정식 지식(reviewed)** | `mapping.retry.scheduled-interval`에 8초 간격 규칙이 반영됨. 갱신: 2026-11-04 16:10:25 KST | 정식 객체 (로컬 원본: `w-t6/round-2/project/brain/objects/mappings/mapping.retry.scheduled-interval.json`), 보존 원문 (로컬 원본: `w-t6/round-2/project/brain/raw/sources/retry/new-rule.md`) |
| **조사 미결 — 초안(미검수 작업 기억)** | 화면 표시가 지연되는 원인(`lag`)은 미확인 | 초안의 해당 질문 (로컬 원본: `w-t6/round-2/project/brain/drafts/retry-interval.json`) |
| **조사 미결 — 초안(미검수 작업 기억)** | 재시도 간격과 화면 표시 동기화의 관계(`concurrent-question`)는 미확인 | 동시 조사자가 추가한 질문 (로컬 원본: `w-t6/round-2/project/brain/drafts/retry-interval.json`) |

정식 지식의 근거 사슬은 `evref.retry.interval → manifest.retry.interval → 보존 원문`입니다. 다만 **구현 코드와 실제 실행 간격은 검증되지 않았고, 8초 규칙으로 화면 표시 지연을 설명할 수는 없습니다.** 변경 이력도 `history_coverage=unsearched`로 남아 있습니다. 정식 객체의 검증 범위 (로컬 원본: `w-t6/round-2/project/brain/objects/mappings/mapping.retry.scheduled-interval.json`)

초안은 2026-11-04 16:11:10 KST 기준이며, 두 미결 항목에는 별도 근거 출처가 연결돼 있지 않습니다. 이번에는 읽기만 수행했고 Git 상태는 시작 시점과 같습니다.
