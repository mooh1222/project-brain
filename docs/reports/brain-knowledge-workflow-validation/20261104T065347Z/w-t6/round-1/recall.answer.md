> E3 당시 판정·관찰의 보존 사본이다. W-T1의 두 기록 세션은 개인 memory를 읽었으므로
> 이번 memory 비활성 통과 집계에서는 제외하고 재실행 결과로 교체한다.
> 작은 Markdown 산출물만 추적하며 JSONL·프로젝트·해시 원본은 로컬 전용이다.
> 링크는 추적 산출물로만 연결하고 원본 증거는 경로 텍스트로 표시했다.

현재 **8초 간격 규칙은 정식 반영됐고, 화면 표시 지연 관련 조사 두 건은 미결**입니다.

| 구분 | 확인 내용과 출처 |
|---|---|
| **정식 지식 · reviewed** | 예약 실행의 재시도 간격은 **8초**이며, 최대 세 번이라는 횟수 제한과 독립된 규칙입니다. 정식 객체는 mapping.retry.interval (로컬 원본: `w-t6/round-1/project/brain/objects/mappings/mapping.retry.interval.json`)입니다. 근거 사슬은 `evref.retry.interval → manifest.retry.interval → 보존 원문`이며, 원문 2행 (로컬 원본: `w-t6/round-1/project/brain/raw/sources/retry/new-rule.md`)에서도 확인됩니다. |
| **조사 미결 · 초안(미검수 작업 기억)** | **화면 표시 지연의 원인**은 미확인입니다. 8초 규칙만으로 지연 원인을 설명할 수 없다고 명시돼 있습니다. 초안 `lag` (로컬 원본: `w-t6/round-1/project/brain/drafts/retry-interval.json`) |
| **조사 미결 · 초안(미검수 작업 기억)** | **재시도 간격과 화면 표시 동기화의 관계**도 미확인입니다. 동시 조사자가 추가한 질문으로 보존돼 있습니다. 초안 `concurrent-question` (로컬 원본: `w-t6/round-1/project/brain/drafts/retry-interval.json`) |

초안 갱신 시각은 **2026-11-04 16:10:04 +09:00**입니다. 두 미결 항목에는 연결된 원문 출처가 없습니다. 별도 시간 경계 조사 원문 (로컬 원본: `w-t6/round-1/project/docs/time-study.md`)에는 샘플 A에서 서버 응답 경계가 표시 시각보다 2초 앞섰다는 관찰이 있지만, 네트워크 지연 가설은 미확인이며 추가 표본과 시계 동기화 조건도 없습니다.

정식화 범위는 **문서 기반 합성 운영 규칙**입니다. 실제 구현·장치 실행·즉시 실행 간격은 검증되지 않았습니다.

읽기만 수행했으며, 시작·종료 시 Git 변경 목록은 동일합니다.
