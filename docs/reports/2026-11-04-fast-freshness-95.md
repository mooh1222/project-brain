# 해시 우선 신선도 판정 — BB2 work-tracker #95

정본: [BB2 #95](https://git.linecorp.com/minhyun-ji/bb2-work-tracker/issues/95).
기준 `f6b490a` (#94), 브랜치 `mooh1222/brain-fast-freshness-95`.

## 설계

- 핵심 v5 형식은 유지하며 선택 캐시 `freshness_surfaces`·`freshness_meta`·`scope_surfaces`를
  원자 rebuild DB에 함께 기록한다. 벡터·임베딩·seed·서비스 계약은 그대로다.
- 현재 projection freshness·객체 표면·raw 청크는 매번 계산한다. 표면 SHA-256이 같은 경우만
  토큰 존재 여부를 재사용한다. 새 표면은 토큰화하며 빈 결과도 캐시한다. 현재 행의
  kind/id/status/surface를 종전 공식으로 정렬·직렬화하므로 지문의 의미는 바뀌지 않는다.
- 선택 캐시가 없거나 버전·지문·토크나이저·추출기가 다르면 기존 전체 계산으로 판정한다.
  기존 v5 DB는 rebuild 없이 검색할 수 있고, rebuild 후에만 빠른 경로를 쓴다.
- scope도 현재의 정확한 표면만 재사용한다. title-only 변경 등 표면 cache miss는 즉시
  토큰화한다. 추론의 구체 표면 우선·단일 특정 규칙은 바꾸지 않는다.
- `SearchSession`은 corpus와 index가 실행 중 바뀌지 않는 읽기 전용 배치다. CLI eval은
  한 실행에 store와 성공한 freshness 검사 1회를 공유한다. 변경 뒤에는 새 세션을 만든다.
  일반 search/recall/eval_recall과 다음 eval 실행은 다시 검사한다.

## 검증 상태

구현 표적 검사: 60개 신규 회귀 통과. 전체 엔진·설치 runtime·독립 검수·실코퍼스 검사와
메모리 안전 gate 뒤의 실측 결과는 검증 완료 후 이 문서에 기록한다.
