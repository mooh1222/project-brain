> E3 당시 판정·관찰의 보존 사본이다. W-T1의 두 기록 세션은 개인 memory를 읽었으므로
> 이번 memory 비활성 통과 집계에서는 제외하고 재실행 결과로 교체한다.
> 작은 Markdown 산출물만 추적하며 JSONL·프로젝트·해시 원본은 로컬 전용이다.
> 링크는 추적 산출물로만 연결하고 원본 증거는 경로 텍스트로 표시했다.

검수된 Insight (로컬 원본: `w-t2-recheck/round-1/project/brain/objects/insights/insight.retry.entry-limit-change-risk.json`)로 직접 적재했습니다.

- 위험: 경로별 제한을 별도로 적용하므로, 수정 시 두 진입 경로를 함께 확인해야 누락을 줄일 수 있음.
- 범위: 문서의 합성 운영 규칙. 실제 코드·장치 동작은 미검증.
- 기존 경로별 근거 객체 두 개를 연결했으며 새 어휘는 만들지 않았습니다.

lint, 회귀 평가, 기존 테스트와 `advisories` 회상을 통과했습니다.
