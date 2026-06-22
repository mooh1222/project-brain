# BB2 Brain 세션 적재 경로 설계 — (가) 진행 중 개발 + (다) 과거 세션 추출 + 갱신 규약

2026-06-11. 적재 3경로 중 미구현 2경로와 공통 갱신 운용 규약을 구축한다.
배경: 지금까지의 적재는 전부 (나) 완료 스펙 소급(bb2-brain-ingest)이었다. 5.6 개발이
곧 시작되므로 (가) 진행 중 개발 적재가 실전 투입되기 전에 절차·도구를 완성한다.

관련 문서: 정본 vault [[bb2-project-brain]] §3 L4 / 발언 원장 06-04(적재 3경로·시간차 흐름·세션 raw 비보관) /
적재 시나리오 경계 `.claude/skills/bb2-brain-ingest/references/scope.md` /
참조 소비: hwi_PKM 딥다이브(세션 추출 스킬 2종·mark-processed·cwd payload 정본), mnemosyne(시간성 — supersedes 사슬로 동일 효과 확인, 스키마 변경 불요), mem0(ADD-only — 의미 변경=supersede 분기와 일치), supermemory(멱등 — 적재 멱등 판정은 에이전트 몫 기존 결정 유지).

## §0 목표·통과 기준

1. **(다) 실세션 완주**: 과거 세션 1개 이상에서 추출 → 검토 라운드 → 적재 → 재회상까지 완주. 골든셋 7/7 유지.
2. **(가) 절차 완비**: 신설 스킬이 후보 선점 → 코드 연결 → 갱신 → 완료 마무리 4단계 절차를 보유. 실전 검증은 5.6 첫 기능 개발에서(인위 시나리오 검증은 골든셋과 중복이라 안 함 — 기존 판단 유지).
3. **CLI 동작**: `project-brain session list / mark-processed`가 동작하고 엔진 합성 테스트 green + 게임 레포 가드 5 passed.
   **색인 신선도 가드 동작**: 객체 변경 후 rebuild 없이 검색하면 명시 에러+rebuild 안내가 난다(stale 침묵 오답 차단).
4. **기존 보장 불변**: 골든셋 7/7, 실코퍼스 가드, 기존 (나) 경로(bb2-brain-ingest 절차) 무변경.

## §1 사용자 결정 기록 (2026-06-11, 이 설계 세션)

| # | 결정 | 내용 |
|---|---|---|
| 1 | 범위 | 전체 그림 한 스펙 — (가)+(다)+갱신 규약+L5 경계. 구현은 슬라이스로 분할 |
| 2 | 갱신 규약 | 혼합 — 변경의 의미에 따라 분기 (§5 분기표) |
| 3 | (다) 입력 | 3모드 전부 — 세션 지정 / 주제·기능 단위 / 일괄 백필. 코어 절차는 하나 |
| 4 | 조립 | 접근법 A — 신설 스킬 1종이 (가)+(다) 담당, 기존 ingest는 (나) 전담 유지, CLI는 보조 명령만 |
| 5 | hook(미결 6) | **보류** — 후보안(UserPromptSubmit 세션당 1회 조건부 주입)은 §9에 기록만 |
| 6 | 시점 | 5.6 개발이 곧 시작 — (가) 실전 검증 시점이 5.6 첫 기능으로 잡힘 |

전제 발언(발언 원장): "개발을 진행하면서 브레인에 채우겠지(기능1) / 완성된 스펙 적재(기능2) /
세션 대화 중 '이거 브레인에 추가해줘'(기능3)" (06-04) / "개발중에는 코드가 생기기도 하고 변경되기도
하는거잖아 … 저장할 요소를 미리 후보로 정해두고 작업하면서 코드가 생기면 연결" (06-04) /
"세션 로그는 어차피 하드디스크에 저장되어 있어서 … raw데이터를 brain에 저장하는건 아니야" (06-04) /
세션 산출물은 자유 텍스트만이 아니라 **기존 객체의 값 갱신**도 포함 (2026-06-11 이 세션).

## §2 전체 그림

```
(나) 완료 스펙 소급   →  bb2-brain-ingest (기존, 무변경)
(가) 진행 중 개발     →  신설 스킬 bb2-brain-session-ingest(가칭)가 둘 다 담당
(다) 과거 세션 추출   →  (입력·시점만 다르고 추출 판단 코어는 같음)
공통: 갱신 운용 규약  →  §5 — 이 스펙이 권위, 신설 스킬 references가 절차 운반
공통: CLI 보조        →  project-brain session list / mark-processed (엔진 추가)
```

경계 불변: **추출 판단(무엇을 지식으로 뽑나)은 Claude(스킬), 기록·마킹만 CLI** — hwi_PKM과
같은 로직 경계이자 우리 기존 구조("적재 도구는 도메인 모르는 범용 부품" 06-03 합의).

세션 로그 raw는 brain에 저장하지 않는다(06-04 발언). 근거는 EvidenceManifest
`source_type=session`, locator는 `claude-session:<session-uuid>#<날짜>` 스킴
(기존 실물 `manifest.petskill-honeyjar.session-user-statement-20260611` 규약 그대로).
`redaction_status`는 반드시 `"approved"`를 명시한다 — 라우터 `_restricted_for`는
`(None, "approved")`만 통과시키는 **의도된 화이트리스트 게이트**라, 문자열 `"none"` 등
다른 값을 넣으면 그 근거가 달린 답이 전부 restricted 처리된다(버그가 아니라 정상 동작 —
적대 리뷰 정정. 코퍼스 17개 manifest 전부 approved, none 전례 0건).

## §3 (가) 진행 중 개발 적재 — 시간차 흐름 4단계

발동: 기획서 기반 기능 개발 착수 시(기획서 분석 시점), 또는 개발 중 "이거 저장해두자".

1. **후보 선점** (개발 시작): 기획서 분석에서 저장 후보(용어·매핑·결정)를 **candidate 객체로
   바로 적재**. 코드 앵커 없이 — candidate는 evidence 강제가 없어(reviewed만 schema 강제)
   스키마 그대로 가능. EvidenceRef는 기획서(raw/sources/<context>/ 보관). DomainContext도 이때 신설.
2. **코드 연결** (개발 중): 코드가 생기면 CodeLocator 추가 + 매핑에 연결. 이 시점 코드는
   develop 머지 전 작업 브랜치다 — locator는 기존 결정 그대로 경로+심볼 힌트이고(라인=조사
   당시 스냅샷, `verified_at`이 시점 기록), **develop 머지 시 스냅샷 갱신(제자리, §5 3행)으로
   정정**한다. 머지 후에만 달면 "개발 중 연결"의 가치가 없다. (나)의 "develop 기준" 원칙은
   완료 소급 적재의 판정 기준이며 (가)의 진행 중 연결과 충돌하지 않는다 — 완료 마무리
   단계(4)에서 develop 기준으로 수렴. 스키마 변경 없음(commit_sha 같은 필드 추가 안 함).
3. **갱신** (값·구조가 바뀔 때): §5 공통 규약 적용.
4. **완료 마무리** (기능 완료 시): reviewed 승격 검토 + history 보강 — (나) 수준으로 닫는다.
   이미 적재된 객체와의 중복·병합 판정은 에이전트(기존 ingest 멱등 결정 그대로, 별도 명령 없음).

**폐기 경로(적대 리뷰 반영)**: 기능이 폐기·기획 취소되면 그 context의 후보 선점 candidate를
**일괄 status=`rejected`로 전환**한다(사유는 노트로). 코드 앵커 없는 candidate가 무기한
잔존하면 회상 후보 채널에 실재하지 않는 기능의 용어·매핑이 계속 떠 오답을 유도하기 때문.

적재 후 4단계 절차(lint → index rebuild → eval → search)는 기존 규약 그대로 매 적재에 적용.
적재로 색인 행 수가 변하므로 **실코퍼스 가드 수치(`brain/checks/` — 현 457/96)도 매 적재마다
의식적으로 갱신**한다 — 갱신 없이는 가드가 깨지고, 무지성 수치 올리기는 가드 가치를 죽인다
(기존 관례의 스펙 명문화, 적대 리뷰 반영).

## §4 (다) 과거 세션 추출 — 입력 3모드, 코어 하나

**코어 절차** (입력 모드와 무관하게 동일):

1. transcript Read (cwd는 디렉토리명이 아니라 **메시지 payload의 cwd가 정본** — 디렉토리명
   인코딩은 손실이 있고, 워크트리 세션은 다른 디렉토리에 쌓인다. hwi_PKM 교훈 채택)
2. kind별 후보 추출: DecisionRecord·GlossaryTerm·DomainMapping·TemporalFact + **기존 kind로
   못 담는 것은 버리지 않고 인사이트 백로그(§6)에 기록** + 개인 메모리 분류(§6)는 표시만
3. **검토 라운드**: 후보를 표로 일괄 제시 → 사용자 자연어 일괄 응답 → 반영. 중복 의심은
   경고 표시만 하고 **자동 제외 금지**. 최대 3라운드 (hwi_PKM code-seeding 검토 라운드 채택).
   **3라운드 소진 후 미합의 후보는 적재하지 않는다** — 자동 제외 금지는 "라운드 안에서
   에이전트가 멋대로 빼지 마라"이고, 미합의는 사용자가 결정하지 않은 것이므로 코퍼스 침투
   금지. 미적재 사실은 mark-processed `--note`("미합의 N건")로 남겨 재방문 가능하게 한다.
4. ingest (원자 적재·lint 차단 기존 그대로) → `session mark-processed <uuid>`.
   **id 안정성 규약**: 추출물 id는 의미 기반 결정론(`kind.context.slug` 기존 네이밍)으로
   부여 — 같은 대상은 재추출에서도 같은 id를 받아, 부분 적재 후 중단·재실행이 ingest의
   같은-id 덮어쓰기(멱등)와 결합돼 중복을 만들지 않는다.

**입력 3모드**:

| 모드 | 흐름 |
|---|---|
| 세션 직접 지정 | 사용자가 세션을 지목 → 코어 절차 |
| 주제·기능 단위 | `session list`로 후보 세션 발견(요약·grep로 관련성 판단) → 관련 세션들에 코어 절차 반복 |
| 일괄 백필 | `session list --unprocessed` 순회 → 세션마다 코어 절차. **마킹 덕에 중단·재개 가능, 같은 세션 재처리 없음** |

**과거 진술 가드**: 세션 내용은 "그 시점 사실"이다 — 현재 develop 코드와 대조하기 전에는
reviewed로 올리지 않는다. 충돌하면 코드 정설 + caveat 기록(기존 관례). 단 사용자 진술
자체를 적재하는 경우(의도·결정 등 코드에 없는 지식)는 reviewer=user-statement로 reviewed
가능 — 이어서 13 전례(`decision.petskill-honeyjar.data-first-processing-order`).

## §5 갱신 운용 규약 (공통 — (가)·(다)·기존 (나) 재적재 모두 적용)

개발·추출 중 "이미 저장된 객체와 현실이 다르다"를 만나면 이 분기표로 처리한다.
(★적대 리뷰 반영 2026-06-11: supersede 장치는 **DomainMapping·TemporalFact 전용**이라는
실측 — lint 8d는 `supersedes_mapping_ids`(DomainMapping)만 검사, GlossaryTerm 등에는
supersede 필드 자체가 없음 — 에 맞춰 kind별로 분기를 분리했다. 스키마 변경 0 유지의 길.)

| 변경 유형 | 처리 | 예 |
|---|---|---|
| **매핑 의미 변경** — DomainMapping이 가리키는 대상·역할 교체 | supersede: 새 매핑 생성 + `supersedes_mapping_ids` 연결, 옛 매핑 status=`superseded` — lint 8d(superseded인데 reviewed 잔존 차단)가 지킴 | 매핑이 가리키는 구현 위치·기획 의미 재배치 |
| **값 변경** — 수치·enum 등 | **3객체 묶음**: EventLedgerRecord(원인 사건) + 새 TemporalFact(`derived_from_event_id`=그 event, `supersedes`=옛 fact id) — TemporalFact는 derived_from_event_id가 **필수 필드**이고, why_changed 회상(라우터 G6)은 event에서 파생된 fact만 사슬을 타므로 EventLedgerRecord 없이는 적재도 회상도 안 된다 | 광고 버튼 82%→85% |
| **그 외 kind 의미 변경** — GlossaryTerm 정의, DomainContext 경계 등 | **제자리 수정 + DecisionRecord 연결** — supersede 장치가 없는 kind는 사슬 대신 결정 기록이 "왜 바뀌었나"를 담당(꿀통 개칭 전례). 과거 표현 자체는 git 이력이 보존 | 용어 정의 변경, 개칭 |
| **스냅샷 갱신** — 코드 위치·라인 힌트·verified_at·오타 | 제자리 수정 + updated_at만 | 함수가 다른 파일로 이동, 라인 드리프트 |
| **원인이 있는 변경** | 위 처리 + **DecisionRecord 연결** | 기획 변경 결정으로 값이 바뀜 |

- **분기 판단 한 줄**: "과거 시점 질문('전엔 어땠어 / 왜 바뀌었어')의 답이 되는 변경인가?" —
  그렇다 → supersede(매핑)/TemporalFact 묶음(값). 아니다 → 제자리.
- **원자성 의무**: supersede 묶음은 **새 객체 + status=superseded로 바꾼 옛 객체 + (값 변경이면)
  EventLedgerRecord를 한 번들로 `ingest`** 한다. ingest는 번들 객체만 쓰므로 옛 객체를
  번들에서 빠뜨리면 디스크에 reviewed로 잔존해 옛 정설이 계속 회상된다 — 06-09 부분쓰기
  사고와 같은 계열의 분할 쓰기 금지. 적재 후 색인 재생성(기존 4단계)까지가 한 동작.
- **reviewed 객체의 의미 변경**: 반드시 검토 라운드(사용자 확인)를 거쳐 **reviewed 유지**로
  수정한다. 어시스턴트 단독으로는 reviewed 의미 변경 금지(새 candidate 제안만 가능) —
  ingest의 reviewed→candidate 강등 거부 가드와 정합(강등 시나리오 자체를 만들지 않는다).
- **lint 커버리지의 정직한 한계**: unincorporated-decision(8c)은 **reviewed 매핑에 한해**
  발화한다 — (가) 진행 중(후보가 candidate인 구간)에는 침묵하므로 그 구간은 절차(검토
  라운드·완료 마무리)가 책임지고, 8c는 완료 마무리(reviewed 승격) 시점의 안전망이다.
- **스키마 변경 0** — supersedes_mapping_ids·TemporalFact(derived_from_event_id+supersedes)·
  EventLedgerRecord·status enum(superseded)·lint 8c/8d 전부 기존 장치 재사용.
  mnemosyne의 valid_until 자동 닫기는 우리 supersedes 사슬이 같은 효과라 미채택.
  참고: 코퍼스에 TemporalFact·EventLedgerRecord 실데이터 0건 — 값 변경 분기는 이 스펙이
  첫 실전이므로 구현 플랜에서 3객체 묶음 견본을 포함할 것.

## §6 L5 경계 + 인사이트 백로그

추출 후보마다 3분류한다 (Q2 결정의 숙제 — "세션 추출물이 팀 지식인지 개인 메모리인지
경계 기준은 적재 경로 설계에 포함"):

| 분류 | 기준(주어 테스트) | 처리 |
|---|---|---|
| 팀 지식 | 주어가 프로젝트·코드·기획 — "BB2의 X는 Y다" | brain 적재 (§4 코어) |
| 개인 메모리 | 주어가 사용자·어시스턴트·작업 방식 — "다음 세션에 X 이어서", "사용자는 Y 선호" | **이번엔 적재 안 함, 표시만** — auto-memory·handoff가 현재 이 역할. L5 구현은 후순위 유지(미결 7) |
| 인사이트 | 기존 kind로 못 담는 교훈·함정·패턴 | `brain/raw/sources/insights/backlog.md`에 누적 (2026-06-12 raw 레인으로 이동 — 검색 가시성, P3 전 임시) |

**인사이트 백로그**: 항목마다 날짜·출처 세션(uuid)·한 줄 요약·핵심 원문 인용. 이 백로그가
쌓이면 **P3(인사이트 그릇 kind)의 "실사용 실례 확보 후 설계" 가드 요건이 충족**된다 —
머리로 짓지 않고 실례로 설계하는 경로. brain/README.md 추적 경계 표에 이 파일 행 추가.

## §7 CLI 변경 (엔진 project-brain)

```
project-brain session list [--unprocessed] [--project <substr>]
    ~/.claude/projects/**/*.jsonl 스캔 → 세션별 uuid·시작시각·payload cwd·메시지 수·처리 여부
project-brain session mark-processed <uuid> [--note <text>]
    .brain-local/sessions/<uuid>.json 마킹 기록
```

- **jsonl 파싱 요구사항(적대 리뷰 실측 반영)**: 세션 파일 선두는 `mode`·`queue-operation`·
  `file-history-snapshot` 같은 **cwd 없는 메타 라인**인 경우가 보통이다(실측: cwd 첫 등장이
  1~4번째 줄에 흩어짐, 전체 라인의 20~40%가 cwd 결측). 따라서 cwd는 "cwd 키가 있는 첫
  라인"에서, 시작시각·메시지 수는 `type ∈ {user, assistant}` 라인 기준으로 산출한다.
  첫 줄을 순진하게 읽으면 cwd=None·시각 오집계·메시지 수 부풀림이 난다.
- 마킹은 `.brain-local/`(git 제외, hwi_PKM 동일). **세션 jsonl 자체가 머신 로컬 자산**이라
  (다른 머신에는 그 세션 파일이 없다) 처리 마킹도 머신 로컬이 자연스럽다 — 적대 리뷰의
  "팀 공유 안 됨" 지적은 이 근거로 반려. 단 README의 `.brain-local/` 규정("재생성 가능한
  파생물")과 달리 마킹은 비파생 운영 상태이므로, README 추적 경계 표에 "세션 처리 마킹 —
  로컬, 소실 시 재백필 비용만(데이터 무손상)" 예외 행을 추가한다.
- cwd 판별은 payload 기준 구현(결정론 로직이라 CLI 몫). transcript 본문 해석·지식 추출은
  CLI가 하지 않는다(경계 불변).

**색인 신선도 가드 (엔진 — 사용자 지시로 범위 승격 2026-06-11)**: superseded 전환 등 객체
변경이 색인에 반영되지 않은 stale 색인은 옛 정설을 정설로 회상하는 침묵 오답을 만든다.
다른 머신이 객체 JSON만 git pull한 경우(팀 공유의 핵심 시나리오)와 적재 후 rebuild를
깜빡한 경우(절차 실수) 둘 다 같은 구멍이다. **이걸 미리 갖춰야 팀 공유가 가능하다 —
"팀 공개 시점에 설계"는 순서가 거꾸로**(전제 조건을 공개 후에 만드는 셈).

- 색인 meta에 **빌드 시점의 코퍼스 지문**을 기록하고, 검색 진입 시 현재 brain/ 상태와
  대조 — 불일치면 기존 스키마 버전 가드와 동일하게 **명시 에러 + rebuild 안내**
  (자동 rebuild는 실모델 로드 수십 초가 검색 경로에 숨어들어 예측 불가 지연을 만들므로 안내 방식).
- 지문 구성(객체 수·최신 updated_at·raw 파일 지문 등)은 구현 플랜에서 확정. 대조는 검색
  경로에 이미 store 로드가 있어 비용 거의 0.
- 기존 meta 가드(schema_version·embed_model)의 확장 — IndexRecord kind(정의만 존재,
  실사용 0)는 쓰지 않고 meta 테이블 확장으로 (객체 단위가 아니라 코퍼스 단위 지문 하나).
- 이로써 팀 공개(미결 5)에 남는 기술 전제는 없어지고 정책 결정(승격 권한)만 남는다.

- 엔진 작업 의무: 엔진 합성 테스트(TDD) + 게임 레포 가드 5·골든셋 7/7 회귀까지 돌아야 완료
  (엔진 레포 CLAUDE.md 절차). 엔진 push는 인자 없는 `git push`(보호 훅 우회 관례).

## §8 신설 스킬 — bb2-brain-session-ingest (가칭)

- 담당: (가) 진행 중 개발 적재 + (다) 과거 세션 추출. 기존 `bb2-brain-ingest`는 (나) 전담
  유지하되 scope.md의 (가)(다) 행을 "신설 스킬로" 갱신(follow-up 문구 해소).
- description 트리거(넓게): "개발하면서 brain에", "이 세션에서 추출/저장", "과거 세션에서
  뽑아줘", "백필", "세션 지식 추출" 등 — 룰 보류 동안 스킬 description이 유일한 자동 진입점.
- references 구성: 갱신 규약(§5 운반), (가) 절차, (다) 절차+검토 라운드, L5 분류표(§6).
- 위치 규약: `.claude/skills/` 원본 + `.agents/skills/` symlink (기존 관례).
- **라인업 보류와의 관계**: 이 작업에 필요한 최소 신설만 한다. 슬래시 커맨드·스킬 전체
  라인업 재편은 여전히 보류(2026-06-11 사용자 결정 그대로).

## §9 hook (미결 6) — 보류 기록

사용자 결정(2026-06-11): **보류**. 검토했던 후보안만 기록해 둔다 — Claude Code 제약상
SessionEnd 시점엔 제안을 받을 수 없으므로(어시스턴트 응답 기회 없음), UserPromptSubmit
hook이 3조건(brain 레포 + 세션 진행 임계 + 미제안) 충족 시 세션당 1회 "저장 제안 검토"
컨텍스트를 주입하는 근사안. 재개 시 이 후보안부터.

## §10 비범위

- P3 인사이트 그릇 kind 설계·구현 (§6 백로그 수집까지만 — 백로그가 P3의 입력)
- L5 개인 메모리 구현 (분류 기준까지만 — 미결 7 유지)
- 슬래시·스킬 전체 라인업 재편 (보류 결정 유지)
- (가)의 실전 검증 (5.6 첫 기능 개발에서 — P0 트리거형의 구체화)
- hook 구현 (§9 보류)
- 다른 에이전트 세션(codex 등) transcript 지원 — claude-code jsonl만 (필요 시 재방문)
- ~~다중 머신 색인 무효화~~ → **범위로 승격**(§7 색인 신선도 가드 — 사용자 지시 2026-06-11:
  팀 공유의 전제 조건을 공개 시점에 만들면 순서가 거꾸로)

## §11 구현 슬라이스 (안)

1. **엔진 — session 명령 + 색인 신선도 가드**: scan(payload cwd, 메타 라인 처리 §7)·list·
   mark-processed + meta 코퍼스 지문·검색 진입 대조(§7) + 합성 테스트
2. **게임 레포 — 신설 스킬 + 기존 스킬 정정**: bb2-brain-session-ingest 본문+references
   (갱신 분기표·값 변경 3객체 묶음 견본 포함), bb2-brain-ingest scope.md 갱신,
   brain/README 갱신(백로그 행·마킹 예외 행)
3. **(다) 실세션 검증**: 세션 1개 추출 완주(추출→검토→적재→재회상) + 골든셋 7/7 +
   **가드 수치 의식적 갱신 후** 가드 green
4. 회상 스킬(bb2-brain-query) 보강 검토(승인 필요) — 기준선: raw_excerpts 채널 해석은
   **이미 반영돼 있음**(SKILL.md 실측, task 이력의 "미적용" 메모가 stale — 적대 리뷰 정정).
   이번 검토 대상은 갱신 규약(superseded·why_changed 경로) 인지 한 줄뿐
