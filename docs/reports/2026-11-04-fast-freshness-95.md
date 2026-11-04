# 해시 우선 신선도 판정 — BB2 work-tracker #95

정본: [BB2 #95](https://git.linecorp.com/minhyun-ji/bb2-work-tracker/issues/95).
기준 `f6b490a` (#94), 브랜치 `mooh1222/brain-fast-freshness-95`.
엔진 구현·전체 회귀·독립 검수와 안전 gate를 통과한 실측을 완료했다. 상주 검색 약 2초와
뚜렷한 클라이언트 메모리 절감 목표는 남아 있다. push/tag/release/PR과 BB2 수정은 없다.

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

모든 실행은 이 checkout의 `PYTHONPATH=<checkout>/src`와 Python 3.12.11 `.venv/bin/python`으로
고정했다. 합성 회귀는 stub/fake만 사용했고 토크나이저는 정규식 주입 경계를 유지했다.

| 검사 | 결과 |
|---|---|
| 전체 엔진 pytest | **2,499 passed, 174 subtests passed**, 645.78초 |
| 신규 #95 회귀 | **60 passed**, 0.76초 |
| 설치 runtime unittest | **151 tests OK**, 15.735초 |
| BB2 `/tmp` 복사본 checks | **15 통과, 기존 조건부 skip 1**, 36.165초 |
| 독립 검수 | Standards **0건**, Spec **0건** |
| 최종 문서 표적 검사 | architecture **16 passed**, 0.08초 |
| 실모델 골든셋 | **18/18**, failed 0 |
| 원본 파일 전후 SHA-256 | **12,370/12,370 동일**, 변경 0개 |

전체 pytest와 설치 runtime은 `PROJECT_BRAIN_EMBEDDER=stub`, `HF_HUB_OFFLINE=1`,
`TRANSFORMERS_OFFLINE=1` 환경에서 실행했다. Python 3.13의 기존 lint 문제는 범위 밖이다.

## 동치성 결과

정규식 토크나이저·합성 corpus에서 기존 기본 `compute_corpus_fingerprint`를 oracle로
비교했다. 아래 20가지 변경을 새 캐시와 캐시 없는 기존 v5 각각에서 실행해 **40/40** 통과했다.
판정은 freshness 통과 또는 `StaleIndexError`와 `index rebuild` 안내로 관찰했다.

| 변경 | 전체 계산 = 새 판정 | 빠른 경로 토큰화 상한 |
|---|---|---|
| 변경 없음 | 최신 | 0 |
| 객체 표면 수정 | stale | 1 |
| 상태만 변경 | stale | 0 |
| 객체 추가 / 삭제 | stale / stale | 1 / 0 |
| 토큰 있음 → 없음 / 없음 → 있음 | stale / stale | 1 / 1 |
| 빈 토큰 표면 → 다른 빈 토큰 표면 | 최신 | 1 |
| 빈 토큰 객체 추가 / 삭제 | 최신 / 최신 | 1 / 0 |
| 비색인 kind 수정 / 의미 밖 시각 수정 | 최신 / 최신 | 0 / 0 |
| raw 추가 / 수정 / 삭제 | stale / stale / stale | 1 / 1 / 0 |
| raw 토큰 있음 → 없음 / 없음 → 있음 | stale / stale | 1 / 1 |
| raw 빈 토큰 표면 수정 | 최신 | 1 |
| projection fresh → stale / stale → fresh | stale / stale | 0 / 1 |

추가 회귀는 빈 토큰 제외 항목까지 unchanged 토큰화 0회, 캐시 누락·손상 폴백,
CLI stale 안내, CLI eval 3개 질의의 freshness 계산 1회, 일반 검색·새 세션의 raw 변경 거부,
scope의 기존 결과 일치와 title-only 변경을 검증했다. scope 비교는 5개 질의 × 현재/변경된
표면의 **10/10** 통과다.

독립 Standards 검수 **0건**, Spec 검수 **0건**이다. Standards 검수자가 표적 9개를 별도
실행해 통과했다. Spec 검수자는 참조 어휘 별칭·상태·추가·삭제, ID 교체, 기존 표면의 객체·
raw 추가, 빈 토큰 객체 상태 변경을 `/tmp`에서 독립 재현해 **8/8** 동치성을 확인했다.

설치 runtime unittest는 **151개 통과**(15.735초). BB2 복사본 checks는 **16개 중 15개
통과·기존 조건부 skip 1개**(36.165초). 원본 Git objects는 읽기 전용 alternates로 참조하고
복사본에 독립 Git metadata를 두어 역사 근거 검사도 원본 쓰기 없이 실행했다.


## 최종 실측과 메모리 안전

실측 직전 `ps`에서 다른 project-brain/임베딩 프로세스는 0개였다. `memory_pressure`의
free percentage는 **45%**로 40% gate를 충족했다. swap used는 판단에 사용하지 않았다.
실측은 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`, 동시 실행 **1개**로 진행했다.
서비스 첫 검색 뒤 status에서 `running=true`, `model_loaded=true`를 확인했다.

BB2 원본 `feature-5.7-agent-env-share`의 `brain/`과 `.project-brain.json`을
`/tmp/pb95-accept-6h1a8a15`로 복사했다. 복사된 live DB를 제거한 뒤
`index rebuild --seed <원본>/brain/.brain-local/index.db`로 실모델 색인을 만들었다.
**8,444개 벡터 전부 seeded, reused 0, computed 0**, seed fallback 0이었다.
전체 색인 8,444행 중 raw는 2,753행이다. timing 전용 stub 색인은 별도 DB이며 골든셋
품질 근거로 사용하지 않았다.

아래 전 값은 #95가 제공한 2026-11-03 기준값이고, 후 값은 이번 1회 수용 세션이다.
검색 질의는 복사본 골든셋 첫 질의다. 시간은 `/usr/bin/time -l`의 real, 메모리는
**peak memory footprint(bytes / 10^9, decimal GB)**다. RSS와 서비스 메모리를 섞지 않았다.

| 항목 | 전: 제공된 기준 | 후: 이번 실측 |
|---|---|---|
| stub 검색 | 11.1초 | **1.91초** |
| freshness 가드 | 9.1초 | **0.414초** (추가 stub 프로파일) |
| 서비스 상주 실모델 검색 | 12.4초 | **5.55초** |
| 서비스 첫 기동을 포함한 검색 | 비교 기준 없음 | **11.43초** |
| 검색 클라이언트 peak footprint | 0.71~0.86GB | 상주 **0.801GB**, 첫 검색 **0.853GB** |
| stub 검색 클라이언트 peak footprint | 별도 기준 없음 | **0.619GB** |
| eval 시간 | 154.9초 | **6.75초** |
| eval 클라이언트 peak footprint | 별도 기준 없음 | **0.787GB** |
| 실모델 골든셋 | 18/18 | **18/18** |

추가 stub 프로파일의 전체 `infer_scope`는 0.429초이며 그중 현재 DomainContext 180개의
표면 처리는 합계 **0.001초**였다. query 토큰화/초기화는 여전히 필요하다.
모델 가중치를 읽지 않는 별도 identity probe에서 임베더 import 0.035초 + 신원 계산
2.052초 = **2.087초**였고 `_model is None`을 확인했다. 최종 실측 뒤 실모델을 다시
기동하지 않고 남은 클라이언트 초기화 비용만 확인한 결과다.

종료는 이 checkout의 `python -m project_brain.cli embedder stop`으로 실행했고
`stopped=true`, 서비스 PID 종료, 잔여 임베딩 프로세스 **0개**를 확인했다. 실측 뒤 free도
45%였다. 원본 brain 파일 12,369개와 config 1개의 전후 SHA-256이 모두 같았다.
검사·실측에 사용한 `/tmp` corpus 복사본은 **삭제 완료**했다.

## 로컬 커밋과 남은 일

- `e790f1e`: 선택 표면/범위 캐시, 기존 지문 동치성 보존, eval snapshot, 회귀와 문서.
- 이 보고서의 최종 문서 커밋까지 포함한 정확한 커밋 목록은 #95 완료 댓글에 남긴다.
- stub는 약 2초 목표에 도달했다. 서비스 상주 검색은 기준 대비 약 55% 빨라졌지만
  **5.55초로 약 2초 목표에는 미달**했다. 클라이언트 peak footprint도 기존 범위 안이므로
  **뚜렷한 메모리 절감을 입증하지 못했다**. 추가 개선은 weightless identity/import와
  토크나이저 초기화 비용을 대상으로 별도 범위를 정해야 한다. 이번에는 #94 서비스·신원·
  토크나이저 계약을 바꾸지 않았다.
- eval은 약 96% 단축됐고 골든셋은 18/18이다. 서비스 메모리나 동시 5개 aggregate
  메모리의 개선을 입증한 실측은 아니다.
- release 게시, BB2 release pin/조회 스킬 갱신과 소비 프로젝트 통합은 후속이다.
  이 브랜치에는 로컬 커밋만 남기며 원본 checkout·#93/#94 worktree·BB2 파일을 수정하지 않았다.
