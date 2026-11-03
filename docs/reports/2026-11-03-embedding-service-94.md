# 임베딩 서비스·전역 슬롯 — BB2 work-tracker #94

정본: [BB2 #94](https://git.linecorp.com/minhyun-ji/bb2-work-tracker/issues/94).
기준 `d791972` (#93), 브랜치 `mooh1222/brain-embed-service-94`.
엔진 구현·합성 회귀·독립 검수를 완료했다. 실모델 수용 실측은 아래 메모리 안전 사유로
생략했다. push/tag/release/PR과 BB2 수정은 수행하지 않았다.

## 설계: adapter·키·위치·수명

- `get_embedder()`가 실모델에 `ManagedEmbedder`를 반환한다. `ServiceClient`가 기본이며,
  서비스 transport/기동 실패 때만 `LockedLocal`이 전역 슬롯을 얻어 `RealEmbedder`를 쓴다.
  기본 stub는 직접 계산한다. 테스트는 외부 SentenceTransformer 경계에 stub 계산 fake를
  주입하므로 서비스에서도 실제 가중치를 읽지 않는다.
- 키는 protocol v1 + `embedding_identity` 문자열의 SHA-256이다. 모델·revision·장치·dtype·
  패키지 버전 신원은 #93의 가중치 없는 계산을 유지한다. handshake 정확 일치 전에는
  텍스트를 보내지 않는다. 불일치는 해당 서비스를 거부하고 제한된 예비 경로를 쓴다.
  서비스와 예비 adapter 모두 로드 후 실제 모델 신원을 검사한다.
- `/tmp/project-brain-embed-<uid>/` 0700 아래 신원별 socket/start/owner/log, 사용자 전체
  fallback 슬롯 파일을 둔다. TMPDIR은 터미널마다 달라질 수 있어 공용 `/tmp` + uid로
  고정한다. checkout·신원과 무관하게 같은 예비 슬롯을 쓴다.
  start lock과 모델 생존 기간 owner lock으로 single-flight를 보장한다.
  lock inode는 삭제하지 않고 OS가 죽은 프로세스의 잠금을 회수한다. stale socket은
  owner lock을 얻은 서비스만 제거한다. PID 재사용도 잠금 소유권을 대신하지 못한다.
- 단일 모델 worker가 계산을 직렬화하고 listener는 계산 중에도 status/stop을 받는다.
  스레드 1·batch_size=1·2048·정규화·float32를 유지한다. float32 bytes를 전달하고
  32개 단위로 나눠 순서를 보존한다. 벡터·색인·#93 seed 계약은 바꾸지 않았다.
- 유휴 기본 600초이며 상태 조회는 유휴 시간을 연장하지 않는다. 예비 슬롯 기본 1,
  대기 기본 300초. 슬롯은 캐시된 모델까지 포함해 프로세스 종료까지 보유한다.
  초과는 `embedder_busy`; 잠금 불가도 fail-closed다. 자동 키워드 강등은 없다.
- `embedder status`/`stop`과 doctor `embed-service`가 기동 없이 현재 신원 상태·PID·RSS를
  보고한다. stop은 ACK 뒤 서비스를 종료하고 owner lock 회수를 기다린다. native 계산
  중에도 프로세스 종료로 메모리를 회수한다. 진행 중인 클라이언트는 재시도로 서비스를
  다시 띄울 수 있다. 설정 환경 변수는 README의 임베딩 서비스 표에 있다.

## 로컬 커밋

- `1487358`: 서비스·전역 슬롯·CLI·doctor·문서·하위 프로세스 회귀 구현.
- `e4bc026`: 로드 후 신원 검사와 계산 중 상태·종료 보완, RED 재현 회귀 추가.
- 최종 검증 결과는 이 보고서를 갱신하는 로컬 문서 커밋에 기록한다.

## 테스트

검증은 이 checkout의 `PYTHONPATH=<checkout>/src`와 Python 3.12.11 `.venv/bin/python`으로
고정했다. Python 3.13의 #93 기존 lint 문제는 수정하지 않았다. 실모델 실행은 0회다.

| 검사 | 결과 |
|---|---|
| 전체 엔진 pytest | **2,439 passed, 174 subtests passed**, 624.67초 |
| 설치 runtime unittest discover | 151 tests OK, 15.463초 |
| 서비스 public seam 회귀 | 13 passed, 25.07초 |
| 독립 재검수 | Standards 0건 / Spec 0건 미해결 |
| `/tmp` 실코퍼스 checks | 16개 중 15개 통과, 1개 기존 조건부 skip, 43.566초 |
| 문서 최종 표적 회귀 | architecture 16 passed, 0.09초 |
| `git diff --check` | 통과 |

실코퍼스 checks는 원본 corpus 12,369개 파일을 `/tmp/pb94-accept-6jjjpqdj/brain`으로
복사해서 실행했다. checks의 PATH도 이 checkout의 `.venv/bin`을 먼저 사용한다. rebuild
가드는 명시 stub이며 나머지는 모델 없는 파일·근거 검사다. Task18의 과거 Git 비교를 위해
복사본에 독립 `.git`을 만들고 원본 objects를 읽기 전용 alternates로 참조했다. 최초의
Git 문맥 없는 복사본에서는 debt-axis 가드가 실패했고, 이 테스트 전제 보완 후 통과했다.
원본 Git metadata·BB2 파일·색인에는 쓰지 않았다. 원본 12,369개 파일의 전후 SHA-256
전수 비교도 변경 0개였다. 조건부 skip은 Task18 실행 단계가
활성화되지 않은 경우의 기존 검사다. 골든셋 회수 품질 검증을 대신하지 않는다.

가짜 모델의 `get_embedder()`/CLI 및 실제 하위 프로세스로 다음을 확인했다.

| 스펙 | 관찰 |
|---|---|
| (a) 동시 첫 요청 | 클라이언트 5개 모두 성공, 모델 로드 1회 |
| (b) 결정론 | 서비스/프로세스 내 벡터 float32 bytes 정확 일치 |
| (c) 신원·버전 | 서로 다른 peer를 거부, 일치 전 텍스트 전송 없음 |
| (d) 소켓 차단 | 동시 5개에서 예비 모델 최대 1개/설정 슬롯 2개 검증 |
| (e) 대기 초과 | `embedder_busy`와 재시도/환경 변수 안내 |
| (f) 유휴 종료 | 짧은 TTL 뒤 종료, 다음 요청에서 재기동 |
| (g) kill 복구 | SIGKILL 뒤 다음 요청 성공 |
| (h) stale 파일 | 남은 socket/start/owner 파일이 있어도 복구 |
| (i) rebuild | 직접/서비스의 저장 벡터 bytes와 검색 JSON 동등 |

추가로 70개 입력 분할·기동 실패 예비 경로·모델 캐시 유휴 중 슬롯 유지·doctor 무기동
진단·실제 신원 변경 시 색인 미게시·계산 중 status/stop을 검증했다.

## Standards

독립 Sol 검수 최초 2건: 예비 모델의 신원 감춤, 계산 중 서비스를 종료 상태로 오보고.
두 문제를 public CLI fake 테스트로 RED 재현 후 수정했다. 보완 재검수 **미해결 0건**,
검수자가 가짜 모델 표적 3개도 별도로 실행해 통과했다.

## Spec

독립 Sol 검수 최초 2건(위와 동일한 두 원인): #93 신원 변경 검사의 우회, 계산 중 운영
명령의 실패. 보완 재검수 **미해결 0건**이며 신규 CLI 표적 2개를 독립 실행해 통과했다.
범위 확장 지적은 없었다. 두 검수 모두 실모델 실행과 파일 수정 없이 수행했다.

## 실제 소켓·잠금 및 샌드박스

현재 Codex 도구 환경은 filesystem 제한이 해제돼 있다. 선택한 실제 production 경로
`/tmp/project-brain-embed-501/`에서 외부 모델 fake로 동시 5개를 실행해 5/5 성공,
모델 로드 1회, 상태·PID·RSS 조회를 확인했다. 이 경로는 fixture의 임시 runtime 대체를
제거한 상태에서 확인했다.

추가로 macOS `sandbox-exec -p '(version 1)(allow default)(deny network*)'`를 적용했다.
AF_UNIX bind가 실제 `PermissionError: [Errno 1] Operation not permitted`로 막힘을
별도 probe로 확인했다. 같은 production runtime 경로에서 가짜 모델 클라이언트 5개가
모두 성공했고, 예비 모델 최대 동시 수 1·최종 생존 수 0이었다. 따라서 실제 OS 소켓
차단에서도 flock과 예비 경로가 작동했다. Codex의 다른 sandbox policy까지 확인한 것은 아니다.
검증용 서비스는 모두 stop/종료했고, 실제 bge-m3 서비스는 띄우지 않았다.

## 실모델 수용 실측: 메모리 안전상 생략

실측 전 `ps`, `sysctl vm.swapusage`, `vm_stat`을 확인했다. 다른 실모델 임베딩 명령은
발견하지 못했지만 처음 스냅샷은 swap 6,144MB 중 5,151.44MB 사용 / 992.56MB 여유였다.
18:15:59 KST 재확인도 사용 5,111.44MB / 여유 1,032.56MB에 불과했다. 36GiB 머신에서
과거 단일 모델 peak footprint가 4.47GB였고 당일 강제 종료 사고가 있었으므로, 지시서의
“위험하면 실측을 생략” 규칙을 적용했다. 실행한 실모델 수는 **0회**다.

| 수용 항목 | 이번 결과 |
|---|---|
| 첫 검색 시간·peak footprint | 미측정 — 실모델 미실행 |
| 두 번째 검색 시간·peak footprint | 미측정 — 1초 안팎 목표 미검증 |
| 서비스 동시 검색 5개 전체 최대 메모리 | 미측정 — 가짜 모델 상한 검증과 구분 |
| 실모델 골든셋 18/18·회상 13/13 동등성 | 이번 세션 미검증 |
| 서비스/직접 벡터 바이트 동등성 | 가짜 모델 통과, 실모델 비교는 미실시 |

실모델을 실행하지 않았으므로 `/usr/bin/time -l` 측정 수치도 없으며 과거 15.5초/4.47GB를
새 서비스 측정값으로 재사용하지 않는다. 가중치·차원·벡터 계약을 바꾸지 않아 실모델 rebuild도
하지 않았다. 실모델 수용은 안전한 자원 여유가 있는 후속 1회에 남긴다.

## BB2 통합 및 남은 일

- 엔진 release 후 `scripts/agents/brain-release.json`의 version/status/release URL,
  wheel·constraints·SHA256SUMS 파일명·SHA256을 실제 게시 값으로 갱신한다. tag/commit도
  확인한다. 이번 작업은 로컬 커밋까지만이며 release·push·PR을 수행하지 않는다.
- release가 BB2 도구에 설치되고 안전한 실측을 통과하면 `8494b04654`의 임시 병렬 금지
  지침을 서비스 기반 병렬 조회 허용·첫 로드 비용·예비 경로 슬롯/`embedder_busy` 안내로
  바꾼다. TEAM_SETUP/조회 스킬에 status/stop과 유휴 회수를 안내한다.
- 안전한 시점에 다른 임베딩 프로세스 부재·swap 여유를 다시 확인한다. 원본을 수정하지
  않는 `/tmp` corpus 복사본, HF cache `~/.cache/huggingface`, `HF_HUB_OFFLINE=1`
  `TRANSFORMERS_OFFLINE=1`로 실모델을 딱 한 수용 세션만 실행한다. `/usr/bin/time -l`로
  서비스와 클라이언트 peak footprint를 분리 기록하고 동시 5개 aggregate peak도 측정한다.
  첫/두 번째 검색·골든셋 18/18·회상 13/13을 확인한 뒤 서비스를 반드시 종료한다.
- #93 seed 재사용·bb2-setup 통합 후속은 #93 보고서의 범위를 따른다. BB2 코드·스킬·
  release pin은 이 워크트리에서 변경하지 않았다.
