# 장치 판정 캐시 — BB2 work-tracker #96

정본: [BB2 #96](https://git.linecorp.com/minhyun-ji/bb2-work-tracker/issues/96).
기준 `e3e0e02` (#93·#94·#95 포함), 브랜치 `mooh1222/brain-device-cache-96`.
엔진 구현·전체 회귀·독립 검수·실모델 수용 실측을 완료했다. 서비스 상주 검색은 **2.91초**로
3초 기준을 충족했고, 골든셋은 **18/18**이다. push/tag/release/PR과 BB2 반영은 하지 않았다.

## 설계

- `RealEmbedder._execution_device()`에서 장치 캐시를 조회하며, v2 신원 JSON의 필드·정렬·공백·값을 유지했다. 캐시 히트는 torch·sentence_transformers를 import하지 않는다. 모델 로더는 캐시를 우회해 실제 장치를 판정하며 기존 float32·revision·batch_size=1로 계산한다.
- #94의 0700 runtime 디렉터리 아래 `device-<sha256>.json`에 둔다. Python executable realpath·venv·Python 버전, torch/ST/transformers 및 선택 backend 패키지 버전, machine·OS release/version, CUDA/PYTORCH/HIP/ROCR/NPU/XPU/HPU 관련 환경과 LOCAL_RANK·RANK·WORLD_SIZE·동적 라이브러리 경로를 키에 넣었다. sentence-transformers 5.6.1의 `get_device_name()`과 transformers의 NPU 판정을 소스로 확인했다. 초기화된 distributed 내부 rank는 공유 캐시를 읽거나 쓰지 않는다.
- 0600 임시 파일을 원자 교체한다. JSON·형식·device 값·권한·소유자·파일 종류·크기 불일치는 미스다. symlink는 따라가지 않는다. `/tmp` 캐시는 재부팅 때 자연 소멸하는 선택 힌트다.
- `embedding_identity_changed`에만 캐시 삭제·실제 재판정·1회 재시도를 한다. 이전 서비스는 새 모델 기동 전에 종료한다. 예비 경로는 적재된 모델과 수명 슬롯을 유지한다. 두 번째 불일치와 다른 오류는 거부한다.
- 독립 검수에서 발견한 rebuild 회복 공백도 수정했다. 장치만 다른 정확한 교정 전후 신원 쌍일 때만 임시 DB를 버리고 previous/seed 선택부터 최대 한 번 다시 시작한다. 교정 전 신원으로 고른 벡터를 새 신원에 섞지 않는다. 일반 dtype/revision 변경은 계속 fail-closed다. #93 seed 선택·검증, #95 freshness 공식, #94 프로토콜·소켓 키·검증은 유지했다.

## 로컬 커밋

- `677146a` — 장치 캐시, ML import 없는 히트, 서비스/예비 신원 회복, 회귀·문서.
- `0e6092f` — 교정 후 rebuild의 안전한 전체 재시도, 혼합 seed hit/miss와 실제 동시 writer 회귀, 문서 근거 보완.
- 이 보고서와 ROADMAP의 최종 문서 커밋까지 포함한 목록은 #96 완료 댓글에 기록한다.

## 검증

Python **3.12.11**, 이 checkout의 `PYTHONPATH=<checkout>/src`와 `.venv/bin/python`을 사용했다.
합성 검사는 `PROJECT_BRAIN_EMBEDDER=stub HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`이며,
실모델은 마지막 수용 실측 세션에서만 사용했다. Python 3.13의 기존 lint 문제는 범위 밖이다.

| 검사 | 결과 |
|---|---|
| 최종 전체 엔진 pytest | **2,525 passed, 174 subtests passed**, 614.23초 |
| embedder/service/seed/vector reuse/search index/architecture 표적 | **187 passed**, 48.62초 |
| 설치 runtime unittest | **151 tests OK**, 14.359초 |
| BB2 `/tmp` 복사본 checks | **15 통과, 기존 조건부 skip 1**, 35.694초 |
| 독립 재검수 | Standards **0건**, Spec **0건** |
| 실모델 골든셋 | **18/18**, failed 0 |
| BB2 원본 파일 전후 SHA-256 | **12,370/12,370 동일**, 변경 0개 |

신규 26개 회귀는 기존 v2 bytes(cpu/MPS/CUDA), 캐시 히트 ML import 차단·sys.modules,
손상 JSON/형식/device/권한/symlink, 환경·실행 경로·venv·패키지·machine·OS 키 불일치,
5개 프로세스의 barrier 동시 기록, 서비스/예비의 잘못된 장치 회복과 두 번째 실패,
상주 서비스의 ML 없는 클라이언트, seed hit/miss가 섞인 rebuild 회복을 검증한다.

독립 Standards 검수자는 신규 **26개**를 별도 실행했다. Spec 검수자는 관련 4개 suite
**80개**와 negative probe를 확인했다. 교정 표식 없는 일반 신원 변경은 즉시 거부하고,
반복 교정은 두 번째 rebuild에서 종료하며 두 경우 모두 DB 미생성·임시 파일 0개였다.

## 실측 전후 비교

실측 직전 다른 project-brain/임베딩 프로세스 **0개**, `memory_pressure` free **54%**로
40% gate를 충족했다. swap used는 판단 기준으로 사용하지 않았다. 오프라인 환경에서
#94 서비스 경로, 동시 실행 **1개**로 측정했다. 기동 뒤 status에서 `running=true`,
`model_loaded=true`, 신원 `mps:0`를 확인했다.

원본 BB2 `feature-5.7-agent-env-share`의 `brain/`과 config를
`/tmp/pb96-accept-qq6b5f3c`에 복사했다. 독립 Git metadata는 원본 objects를 읽기 전용
alternates로 참조했다. 원본 색인을 `--seed`로 지정한 첫 rebuild는 **8,444개 전부 seeded,
reused 0, computed 0, seed fallback 0**이었다(16.32초). raw는 2,753행이다.
별도 stub DB는 시간 측정 전용이며 골든셋 품질 근거가 아니다.

전 값은 [#95 보고서](2026-11-04-fast-freshness-95.md)의 실측이며, 후 값은 이번 단일
수용 세션이다. 검색은 동일 골든셋 첫 질의다. 시간은 `/usr/bin/time -l`의 real,
메모리는 **peak memory footprint(bytes / 10^9, decimal GB)**로, RSS·서비스 메모리와
섞지 않았다. 표본 1회 측정이므로 모든 머신·반복 실행의 상한을 보장하는 수치는 아니다.

| 항목 | 전: #95 | 후: #96 |
|---|---|---|
| 서비스 상주 실모델 검색 | 5.55초 | **2.91초** (약 48% 감소, 3초 기준 충족) |
| 서비스 기동 포함 검색 | 11.43초 | **6.64초** |
| stub 검색 | 1.91초 | **1.86초** |
| 상주 검색 클라이언트 peak footprint | 0.801GB | **0.621GB** (620,807,176 bytes, 약 22% 감소) |
| 기동 포함 검색 클라이언트 peak footprint | 0.853GB | **0.622GB** |
| stub 검색 클라이언트 peak footprint | 0.619GB | **0.620GB** |
| eval 시간 | 6.75초 | **4.05초** |
| eval 클라이언트 peak footprint | 0.787GB | **0.575GB** |
| 골든셋 | 18/18 | **18/18** |

## 상주 검색 구간별 프로파일

같은 수용 세션에서 **eval 후 추가 상주 검색 1회**를 함수 wrapper로 계측했다. 이 요청은
**1.86초**, Python 내부 **1.808초**다. 앞의 무계측 상주 검색 **2.91초**와는 별도 요청이며,
OS 파일·모델 실행 캐시가 더 따뜻한 상태라 이 표를 2.91초의 분해로 해석하면 안 된다.
전 프레임 profiler의 큰 오버헤드를 피하고 지정 함수 경계만 감쌌다. 중첩 함수는 빼서
아래 합계를 구성했다. 프로파일은 `.snapshots/96/profile.py`와 같은 디렉터리의 원시 로그에
로컬 보존했다. 실제 클라이언트 `sys.modules`에서도 **torch/ST 모두 미로드**였다.

| 구간 | 초 |
|---|---:|
| 프로세스/인터프리터 시작 및 측정 경계 차이 (wall - Python) | 0.052 |
| import | 0.060 |
| BrainStore 로드 | 0.330 |
| kiwipiepy 초기화 | 0.387 |
| 범위 추론 (질의 토큰화 포함) | 0.409 |
| 신선도 판정 | 0.252 |
| 임베딩 신원 계산 | 0.003 |
| 임베딩 요청·연결·통신 (신원 계산 제외) | 0.074 |
| 벡터 검색 (임베딩 요청 제외) | 0.011 |
| BM25 (전체/범위) | 0.037 |
| 출력 직렬화·쓰기 | 0.001 |
| 기타 초기화·회수 조립·사실 필드 계산 등 잔여 | 0.242 |
| 합계 (반올림 전) | **1.860** |

#95의 별도 identity probe **2.087초**와 이번 프로파일의 **0.003초**는 측정 경계가 다르다.
두 결과를 직접적인 동일 조건 배율로 주장하지 않으며, 비용 제거는 ML import 차단 테스트와
실제 상주 프로파일의 미로드 사실로 함께 확인했다. 프로토콜 변경이나 대규모 구조 변경 없이
3초 수용 기준을 충족해 추가 production 최적화는 넣지 않았다.

## 반영하지 않은 개선과 남은 일

- Kiwi 초기화와 첫 질의 토큰화가 프로파일의 큰 비중이다. 장수 검색 프로세스/토크나이저
  재사용은 수명·동시성 계약 검토가 필요하므로 제안으로만 남긴다. 토큰 규칙·모델 옵션은 바꾸지 않았다.
- BrainStore 파일 읽기와 잔여 회수 조립의 상세 분석, corpus snapshot 공유는 별도 티켓
  후보이다. #95 freshness 의미나 코퍼스 보안 검사 생략을 이번 최적화에 넣지 않았다.
- 3초 기준은 이번 머신의 단일 수용 세션에서 충족했다. 2초 안팎의 항상 일정한 지연,
  동시 5개 aggregate 메모리 개선, 다른 OS/가속기의 실장치 성능은 입증하지 않았다.
- release·BB2 release pin/설치·소비 프로젝트 반영은 범위 밖이다. 이 브랜치에는 로컬
  커밋만 남겼다. 원본 checkout·#93/#94/#95 worktree·BB2를 수정하지 않았다.
- 종료 명령에서 `stopped=true`, 서비스 PID 종료·잔여 임베딩 프로세스 **0개**, 종료 뒤 free
  **54%**를 확인했다. 원본 brain 12,369개 + config 1개의 해시가 모두 같고 `/tmp` 복사본은
  **삭제 완료**했다. 엔진 구현·검증에 남은 필수 작업은 없다.
