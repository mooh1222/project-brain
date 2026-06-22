# BB2 Brain P2 1번 — 적재 스킬 정비 + 운영층(회상 절차서) 구성

- 날짜: 2026-06-10
- 정본: vault wiki `bb2-project-brain` (§5 로드맵 2차 = "적재 스킬 정비 포함", §7 미결 8)
- 추적 task: vault `bb2-project-brain-build`
- 사용자 결정 3건 (2026-06-10):
  1. 운영층 형태 = **룰 + 회상 스킬 조합**. 단 **룰은 예정안으로 보류** — 프로젝트 룰·스킬
     전반 정리를 brain 완성 후에 같이 하기로 함(§5).
  2. 미결 8 기준 = **독립 회상 가치**(§4).
  3. 회상 스킬 신설·적재 스킬 정정·정본/task 갱신(§1 표 전체)은 이번에 구현.

## §0 목적·범위

P2 1번을 닫는다: (a) 적재 스킬(`bb2-brain-ingest`)의 낡은 서술 정정 + 06-04 "LLM 판단
가이드 부재" 중 미결 8 기준 수록, (b) 운영층 — 어시스턴트가 brain을 **쓰는** 절차서
(회상 계약 + 사용 시점 승격) 신설. 코드(`scripts/bb2_brain/`) 변경은 0.

범위 밖: 룰 파일 생성(§5 예정안), scope 자동 라우팅(P2 3번), raw 본문 색인(P4),
인사이트 그릇 kind(P3 — 미결 1).

## §1 산출물

| # | 파일 | 동작 |
|---|---|---|
| 1 | `.claude/skills/bb2-brain-query/SKILL.md` | 신설 — 회상 절차서 (§2) |
| 2 | `.agents/skills/bb2-brain-query` | symlink 미러 (스킬 단일 원본 컨벤션) |
| 3 | `.claude/skills/bb2-brain-ingest/SKILL.md` | 수정 — stale 정정 + 미결 8 기준 (§3·§4) |
| 4 | `.claude/skills/bb2-brain-ingest/references/ingest-tools.md` | 수정 — CLI·절차 최신화 (§3) |
| 5 | 정본 §7 미결 8 닫음 표시 + task 갱신 | vault |

## §2 회상 스킬 `bb2-brain-query` 설계

벤치마크: hwi_PKM `/ask`(8~42줄 얇은 절차서 + CLI 호출). Hermes "memory-as-skill
non-pattern" 반례 검토 결과 — 경고의 본질은 "절차서 안에 저장 엔진 로직을 넣지 마라"이고,
우리는 엔진이 CLI로 분리돼 있어 절차서=얇은 wrapper 구조면 해당 없음(채택/거부 기록:
hwi_PKM 계약 채택, Hermes는 구조 가드로만 반영).

### 트리거 (description)

BB2 기능·도메인 질문("~가 뭐야", "어디 구현돼 있어", "왜 이렇게 바뀌었어"), QA 이슈
분석 시작, 기능 개발 착수, "brain에서 찾아/물어봐". **룰 보류 동안 이 description이
유일한 반사 진입점**이므로 넓게 잡는다.

### 회상 계약

1. **검색 먼저**: grep·vault·codanna 탐색 전에
   `cli search "<질문>"` (auto_worker venv, `--brain-root scripts/bb2_brain/brain`).
   색인 없으면 `cli index rebuild` 후 재시도.
2. **결과만으로 답한다**: 답의 모든 사실에 근거를 표시 — 매핑 적중은 동반된
   `linked.code_locators`(path:symbol)로 코드 위치까지. 검색 결과에 없는 내용을 brain의
   답인 것처럼 섞지 않는다.
3. **없으면 "brain에 없다"를 명시한 뒤 폴백**: hwi_PKM은 일반지식 폴백 금지지만, 우리는
   어시스턴트가 코드 탐색을 이어가야 하므로 금지하는 것은 폴백이 아니라 **"brain에 있는 척"**.
   "brain에 없음 — 코드에서 직접 확인" 한 줄을 박고 일반 탐색으로 넘어간다.
4. **채널 해석**: `results`(reviewed) = 확신 답 / `candidates` = **"확인 필요" 라벨 필수**
   / `needs_clarification` = 사용자에게 좁히기 질문.
5. **사용 시점 승격(C 루프)**: 답하다 사용자가 candidate를 "맞다" 확인하면 그 자리에서
   `cli promote --ids <id> --reviewer user-confirmed --reviewed-at <ISO8601>`.
   회상과 한 흐름이므로 이 스킬에 포함(일괄 승격 `promote-auto`는 적재 스킬 몫).
6. **이력 질문 가드**: `history_coverage=complete`가 아닌 매핑에 왜/그때 질문이 오면
   "변경 이력 미적재"로 답한다(적재 스킬과 같은 규칙 — 회상 쪽에서도 지킨다).
7. **scope 자동 라우팅 미배선 인지**: 질의에 기능명을 명시해도 연관도 가중만 작동
   (P2 3번에서 배선). 기능 간 혼선이 보이면 결과를 기능명으로 수동 필터.

## §3 적재 스킬 stale 정정 목록

| 위치 | 현재 (낡음) | 정정 |
|---|---|---|
| SKILL.md "raw·저장 정책" / ingest-tools.md "기획서 원문 보관 (열린 항목)" | "정확한 자리는 사용자와 확정 뒤" | P1 해소 반영: `raw/sources/<context-slug>/<원본 파일명>` 텍스트만 git 추적, locator는 brain root 상대. 규약 출처 = `scripts/bb2_brain/brain/README.md` (커밋 `5c24dd4a8d`) |
| ingest-tools.md CLI 목록 | ingest·promote만 | `promote-auto`(매핑 보증 일괄 승격 — pass id 재가드·backfill·원자 검증, 06-08) + `index rebuild` + `eval` + `search` 추가 |
| ingest-tools.md "적재 후 확인" | lint + query 회상만 | 확장: lint clean → `cli index rebuild`(색인 재생성 — 검색층이 생겨 필수) → `cli eval`(골든셋 회귀 — P2 2번이 기능마다 요구) → `cli search` 샘플 회상 |
| (부재) | — | "brain/ 파괴적 일괄 작업(promote-auto·일괄 변환) 전 **커밋 먼저**" 규약 한 줄 (06-09 사고 교훈, brain/README.md 규약) |

## §4 미결 8 기준 — 독립 회상 가치 (SKILL.md에 수록)

- **객체 저장 기준 = "독립적으로 질문되고, 독립 근거를 가질 수 있는가"** — 기존 의미 원자
  승격 기준과 같은 축. 코드 연관은 기준이 아니라 **근거의 한 종류**(규칙 5 유지 — 서버
  판정·순수 규칙은 코드 없어도 저장).
- **기획서 개념 서술(세계관·컨셉 설명)은 객체화 금지** — "어차피 기획서에 다 있음"(06-04
  원장). raw 보관(`raw/sources/`)이 커버하고, 본문 검색은 P4 raw 색인에서. 그때까지
  개념 서술은 검색에 안 잡히는 공백을 감수한다(사용자 합의).
- **정의가 근거를 초과하면 안 된다** — 06-09 커버리지 검증 hold 24건(폰트 상수·멤버
  선언·매크로 등 매핑 검증 의미를 넘는 정의)을 경계 예시로 수록.
- **인사이트는 적재 보류** — "인사이트는 객체로"(Q1)는 유효하나 그릇 kind가 미결 1(P3).
  kind 결정 전까지 인사이트성 지식은 적재하지 않고 보류 표시.

## §5 예정안 (보류) — 룰 `.agents/rules/bb2-brain-first.md`

brain 완성 후 프로젝트 룰·스킬 전반 정리 때 함께 만든다(사용자 결정 2026-06-10). 초안:

- BB2 도메인 질문·QA 이슈 분석·기능 개발 착수 시 `cli search` 먼저 (bb2-brain-query 위임).
- bb2-vault-first와 분담: 도메인 지식(기능 의미·기획·코드 위치·변경 이유) = brain 먼저 /
  코드 작업 패턴(API 호출법·팝업 패턴 vault note) = vault-first 그대로. 겹치면 brain 먼저.
- 루트 `CLAUDE.md` import 1줄 + `.claude/rules/` symlink.

보류 영향: P0 "QA 이슈 때 brain 먼저"의 반사 트리거가 항상-읽힘 룰 없이 가므로, 그동안
회상 스킬 description(§2)이 유일한 자동 진입점.

## §6 검증

코드 변경 0이므로:

1. `pytest scripts/bb2_brain/tests/ -q` 258 green 유지(회귀 없음 확인).
2. **회상 스킬 실연**: 실코퍼스에 질의 2개 — reviewed 적중 1건 + candidate 포함 1건 —
   를 새 절차서대로 따라가며 계약(근거 표시·채널 라벨·없으면 없다)이 지켜지는지 확인.
3. brain/README.md 규약·정본 §7과 모순 없는지 대조.

## §7 영향·원본 위치 (스킬 수정 승인 기록)

- 원본: 프로젝트 스킬 = `.claude/skills/`(단일 원본), `.agents/skills/`는 symlink 미러.
- 본 스펙이 승인 기록이다 — 수정 2파일(`bb2-brain-ingest/SKILL.md`·`references/ingest-tools.md`),
  신설 1스킬(`bb2-brain-query`), 룰은 만들지 않음.
- 코드·테스트·brain 데이터 무변경. 무관 더티 4개(UserGameDataManager.cpp 등)는 커밋 제외 유지.
