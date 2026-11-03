# 임베딩 서비스·전역 슬롯 — BB2 work-tracker #94

정본: [BB2 #94](https://git.linecorp.com/minhyun-ji/bb2-work-tracker/issues/94).
기준 `d791972` (#93), 브랜치 `mooh1222/brain-embed-service-94`.
엔진 코드·합성 테스트만 변경한다. push/tag/release/PR과 BB2 수정은 하지 않는다.

## 설계

- `get_embedder()`가 실모델에 `ManagedEmbedder`를 반환한다. `ServiceClient`가 기본이며,
  서비스 transport/기동 실패 때만 `LockedLocal`이 전역 슬롯을 얻어 `RealEmbedder`를 쓴다.
  기본 stub는 직접 계산한다. 외부 모델 fake는 서비스에서 StubEmbedder를 계산한다.
- 키는 protocol v1과 `embedding_identity` 문자열의 SHA-256이다. 모델·revision·장치·dtype·
  패키지 버전 신원은 #93의 가중치 없는 계산을 유지한다. handshake 정확 일치 전에는
  텍스트를 보내지 않는다. 불일치는 해당 서비스를 거부하고 제한된 예비 경로를 쓴다.
- `/tmp/project-brain-embed-<uid>/` 0700 아래 신원별 socket/start/owner/log, 사용자 전체
  fallback 슬롯 파일을 둔다. TMPDIR·checkout·신원과 무관하게 같은 슬롯을 쓴다.
  start lock과 모델 생존 기간 owner lock으로 single-flight를 보장한다.
  lock inode는 삭제하지 않고 OS가 죽은 프로세스의 잠금을 회수한다. stale socket은
  owner lock을 얻은 서비스만 제거한다.
- 서비스는 직렬 계산, 스레드 1·batch_size=1·2048·정규화·float32를 유지한다.
  float32 bytes를 전달하고 32개 단위로 나눠 순서를 보존한다. 벡터·색인 계약은 바꾸지 않는다.
- 유휴 기본 600초. 예비 슬롯 기본 1, 대기 기본 300초. 슬롯은 캐시된 모델까지 포함해
  프로세스 종료까지 보유한다. 초과는 `embedder_busy`; 잠금 불가도 fail-closed다.
- `embedder status`/`stop`과 doctor `embed-service`가 기동 없이 현재 신원 상태를 보고한다.
  설정 환경 변수는 README의 임베딩 서비스 표에 있다.

## 검증 진행

가짜 모델 표적 회귀 71개 및 architecture+서비스 회귀 27개 통과.
전체 pytest·설치 runtime unittest·독립 검수와 수용 실측 결과는 완료 시 아래에 기록한다.
