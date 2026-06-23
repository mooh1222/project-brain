# BB2 Brain 고립 노드 정비 회고 후속 — 엔진/스킬 보강 계획

> **For agentic workers:** 이 계획서가 다음 세션의 **작업 순서 단일 출처**다. 엔진 코드 Task(C1·C2·C3·C4·C8)는 테스트 우선(TDD) — 실패 테스트 먼저, 그다음 구현. 스킬·문서 Task(C6·C7·C9·C10)는 체크리스트다(통짜 TDD를 욱여넣지 않는다). 실행은 `superpowers:executing-plans`로 Task 단위. 정확한 줄 번호는 코드가 바뀌므로 구현 직전 재확인한다.

**Goal:** bb2_client 고립 노드 정비 4세션(2026-06-23)을 회고해 도출·검증한 보강안 9건을, 우선순위대로 엔진(project-brain) 코드와 bb2-brain-* 스킬에 반영한다. 진짜 버그(C2 해시 회귀)와 빠진 도구(C1 고립 탐지)가 핵심이고, 나머지는 가드·문서다.

**Architecture:** brain은 2-레포다 — 엔진(`~/Downloads/codes/project-brain`, `project-brain` CLI, 합성 테스트만)과 데이터·스킬 레포(`bb2_client`의 `brain/`·`.agents/skills/bb2-brain-*`). 고립 "발견·집계·해시"는 결정론이고 모든 데이터 레포 공통이라 **엔진**이 흡수하고, "어디에 union할지" 같은 도메인 판단은 **스킬**이 사람·서브에이전트 LLM에게 맡긴다. 이 분담이 타깃 결정의 기준이다.

**Tech Stack:** Python 3.11+ (project-brain, pytest), SQLite FTS5 + sqlite-vec, mecab-ko. 스킬은 마크다운 SKILL.md.

## Global Constraints

- 엔진 레포 테스트: `.venv/bin/python -m pytest tests/ -q` — **현재 470개 수집(collected) 회귀 금지**.
- 엔진 수정 후 **데이터 레포 회귀 필수**(엔진 합성 테스트만으론 검색 품질·색인을 못 막는다): `cd bb2_client && python3 -m unittest discover -s brain/checks && project-brain index rebuild && project-brain eval`(골든셋). 회귀 0 확인 전엔 완료 아님.
- 결정론 유지: 테스트에서 실모델 금지(StubEmbedder / `PROJECT_BRAIN_EMBEDDER=stub`).
- 경로·시각 하드코딩 금지(config 해석, `now_kst()`).

### 이 회고에서 확정한 설계 제약 (구현 전 반드시 인지)

- **무결성 검사가 단방향이다.** lint·store·schema·build 전부 아웃바운드(나가는 끊긴 참조=dangling)만 본다. "아무도 나를 안 가리킴"(인바운드 0 = 고립)은 개념조차 없다(`lint.py:112-270` 전 항목 `store.has(ref)`). → 고립은 lint 확장이 아니라 **별도 명령(C1)** 으로 푼다. lint는 읽기 전용 차단 게이트라, 적재 직후 잠깐 고립인 candidate를 막으면 안 된다.
- **"고립 = 검색 손해"는 약하다.** 회수 집합(top-30)은 그래프 신호 계산 *전에* RRF로만 잘린다(`search.py:428` vs `434`). 그래프 재정렬은 순서만 바꾸고 추월 폭이 캡 2(`_GRAPH_SUPPORT_CAP`)로 묶여, 손해는 eval_recall top-5 채널의 5등↔6등 경계뿐. **고립 정비의 가치는 회수율이 아니라 지식 그래프의 완전성·추적성**(근거 연결, 누락 PR 인용)이다 — 이걸 명분으로 삼는다.
- **인바운드 엣지 필드는 단·복수를 모두 명시 열거해야 한다(접미사 매칭 금지).** ⚠ critic 검수(2026-06-23)로 정정. `search.py:65 _GRAPH_EDGE_FIELDS`는 `evidence_refs`를 의도적으로 제외(랭킹 오염 방지)하지만, 고립 판정에는 **evidence_refs를 포함**해야 한다(EvidenceRef는 그것으로만 가리켜짐 — 빼면 전부 거짓 고립). 복수 `_ids`만 세면 단수 참조 필드 — `context_id`(schema.py:21,22,33), `evidence_manifest_id`(:13), `derived_from_event_id`(:17), `spec_document_id`(:28), `spec_revision_id`(:29), `target_object_id`(:254), `source_object_id`(:26), `review_record_id`(lint.py:136) — 로만 가리켜지는 객체가 거짓 고립으로 잡힌다. 반대로 `channel_id`(SlackThread 외부 슬랙 채널, schema.py:30)·`project_id`(DomainContext 프로젝트 키 문자열, :19)는 brain 객체 참조가 아니라 인바운드로 세면 안 된다. → 접미사가 아니라 **필드별로 'brain 객체 참조인가'를 분류한 명시 목록**을 schema.py에서 정본 추출. C1·C8 공유.
- **면제·점검 범위는 truth_role 술어가 아니라 명시 kind 목록으로.** ⚠ critic 검수로 정정. `truth_role=="source"` 필터는 코드와 안 맞는다 — DomainContext는 `truth_role="domain"`(schema.py:48)이라 면제 안 되고, SlackThread가 source(:57)라 딸려 면제됨. 게다가 CurrentView·KnowledgePage·IndexRecord·Insight·EventLedgerRecord·미참조 DomainMapping·TemporalFact는 **구조적으로 인바운드 0이 정상**이라, 면제 {EvidenceManifest, DomainContext}로는 못 거른다 → "전체 코퍼스 고립 0"은 도달 불가. 해법: **고립 점검 대상을 '가리켜지려고 존재하는 잎 kind' 화이트리스트**(CodeLocator·EvidenceRef·GlossaryTerm·SpecRevision 등)로 한정(권장). 또는 고립=인바운드0 ∧ 아웃바운드0(완전 단절)로 재정의 — 어느 쪽이든 구조적 인바운드0 kind를 폭주로 잡으면 안 됨.

---

## 이 계획이 나온 경로 (세션 이력·근거)

- 정비 작업 세션 4개(모두 `~/.claude/projects/-Users-al03040455-Desktop-bb2-client/`, 2026-06-23):
  - `66a571e0-ccd1-4c80-ba9f-c6a967312c29` — 시작·핸드오프 진입·시범 데모(continue-popup-renewal) + KST 표준화 + 스킬 문서 정정
  - `a4e15c35-fac1-4b83-851a-23ce28c52fb8` — union 1차
  - `e3d1441a-244f-4caa-99de-8701479455d1` — ingame-view 22 + ingame-logic 20 union, GameStatus 매핑 신설, line_end 언더카운트 발견
  - `f4098e84-030a-47e4-b793-438ebf5aaaa9` — frame/continue 변경이력 적재 마무리
- 회고 방법: 워크플로 23 에이전트(`wf_a43299c4-c37`) — 4세션 회고(대화 TXT + jsonl grep) + 엔진/스킬 7영역 코드 매핑 → 종합 11후보 → 후보별 회의적 검증.
- **상세 근거 문서(정본 분석):** `project-brain/.snapshots/2026-06-23/brain-cleanup-postmortem.review.md`. 원본 대화 TXT·워크플로 결과(`tasks/wea02y2es.output`)도 같은 폴더. 이 plan은 그 분석의 실행 계획판이다.

## 배경 — 핵심 발견 (다음 세션이 또 헷갈리지 않게)

- 사용자 예상 시나리오(고립 처리 / 적재 후 점검 / lint 확장)는 다 실재했고, lint 한 곳만 방향 교정(위 설계 제약 1).
- 시나리오 밖에서 더 큰 게 나옴: **C2 진짜 버그**(`_at` 일괄 변환이 projection 해시를 깨 eval 10→8 회귀). 가장 시급.
- 반복 수작업: 고립 탐지 ad-hoc 파이썬(4세션 전부), `EXPECTED_OBJECT_ROWS` 손 갱신, union 검증 5단계 재현.
- 스킬 약점(user-correction 군집): 연결 정책·complete 판정 기준이 스킬에 없어 LLM 기본 성향(최소 변경 편향)이 작업 목표(연결성↑)를 이김 → C7에 판정 기준 명문화로 가드.

## 고립 노드 운영 방향 (이 회고로 확정한 방침)

> 이번 고립 발견은 사용자가 시각화(그래프 HTML)를 요청하다 **우연히** 드러난 것이다. 앞으로는 우연에 기대지 않는다. 시범(4세션)을 거쳐 다음 분담으로 정한다.

- **발견·집계는 엔진이 상시 책임진다.** `graph isolated`(C1)로 코퍼스 전체 고립을 언제든 뽑고, 적재 시점엔 build가 비차단 경고(C8). 그래프 시각화 HTML(`graph_export.py`)은 사람이 눈으로 보는 보조 수단이지 발견의 정본이 아니다.
- **처리(어디에 어떻게 연결할지)는 스킬 워크플로가 맡는다.** 호출처 grep·역할 판정은 도메인 판단이라 엔진이 강제하지 않는다(C7). 엔진은 "여기 고립이 있다"까지만, "이걸 X에 붙여라"는 사람·서브에이전트 몫.
- **지향점: 점검 대상 잎 kind(CodeLocator·EvidenceRef·GlossaryTerm 등 '가리켜지려고 존재하는' kind)의 고립 0.** CurrentView·Insight·IndexRecord·EventLedgerRecord·EvidenceManifest(루트)처럼 구조적으로 인바운드 0이 정상인 kind는 점검 대상에서 제외한다 — "전체 코퍼스 고립 0"은 도달 불가하므로 목표로 삼지 않는다(critic 검수 정정).

---

## Phase 0 — P0 (진짜 버그 + 빠진 핵심 도구)

### Task C2+C3: source_content_hash에서 시각 필드 제외 + 재계산 명령 (engine)

C2·C3은 짝이다. C2만 내면 기존 저장 projection이 전부 stale가 되므로 C3 재계산을 함께 출시한다.

**Files:**
- Modify: `src/project_brain/hash_utils.py`(또는 `_stable_json` 옆) — `exclude_keys` 지원 단일 헬퍼
- Modify: `src/project_brain/context_projection.py`(:113 생성식, :159 build_reuse_projection)
- Modify: `src/project_brain/lint.py`(:18-21 `_compute_source_content_hash` 검증식)
- Modify: `src/project_brain/cli.py` — `projection refresh [--ids ...]` 서브커맨드
- Test: `tests/test_context_projection.py`, `tests/test_lint.py`, `tests/test_cli.py`

**근거:** `_sha256_text('\n'.join(_stable_json(obj) for obj in source_objects))`가 객체 전체(=`created_at`/`updated_at`/`verified_at` 포함)를 해시. 스킬 `update-rules.md:11`이 "verified_at만 갱신"을 정규 루틴으로 둬 재발 구조. 실측 회귀: eval 8/10, `source_content_hash mismatch` 3건.

- [ ] **C2 Step 1 (실패 테스트):** 의미 필드는 그대로 두고 `updated_at`만 바꾼 source 객체로 projection을 만들면 해시가 **불변**임을 검증하는 테스트(현재는 바뀜). 기존 `test_context_projection.py:140-144`(meaning 변형 → stale)는 그대로 통과해야 함(의도 보존).
- [ ] **C2 Step 2 (구현):** 생성식 2곳·검증식 1곳이 같은 입력을 쓰도록 단일 헬퍼로 정본화. 제외 키 = `created_at, updated_at, verified_at, captured_at, schema_version`(구현 시 BASE 메타 전수 확인). 중복 구현 금지.
- [ ] **C2 Step 3 (소스 범위 점검 — critic 검수 추가):** `build_reuse_projection`은 임의 `source_object_ids`를 받는다(`cli.py:528`). projection 소스가 될 수 있는 kind를 명시하고, 그 kind들의 자동기입 시각필드(`reviewed_at`=ReviewRecord, `happened_at`=EventLedgerRecord, `generated_at`=ContextProjection, `as_of`=CurrentView, `indexed_at`=IndexRecord 등)가 exclude 집합에 다 덮이는지 1줄 점검. denylist(제외목록)는 "모르면 재생성"으로 안전측 실패라 방향은 옳음. `schema_version` 제외는 `_at` 버그 범위를 넘는 의도적 확장(버전 bump마다 stale 폭주 방지)이니 **별도 테스트로 의도를 박을 것.**
- [ ] **C3 Step 1 (실패 테스트):** source가 바뀐(dangling 아님) projection에 대해 `projection refresh`가 source_content_hash를 현재 store로 재계산해 저장하고, 이후 lint가 clean임을 검증. **reviewed projection도 refresh됨**을 함께 검증(아래 확인 반영).
- [ ] **C3 Step 2 (구현):** `projection refresh`는 기존 projection 객체를 읽어 **해시만 재계산해 같은 status로 ingest() 경유 저장**(schema+merged lint+후퇴 가드 통과). ✅ **ingest 멱등 확인 완료(critic 검수)**: `ingest.py:31-32`는 `reviewed→candidate` 강등만 거부하고 **reviewed→reviewed 재적재는 허용**(docstring "멱등 갱신 허용")하므로 reviewed projection refresh가 막히지 않는다 — promote(`cli.py:100-105`의 reviewed 거부)와 달리 ingest엔 그 가드가 없다. 그래서 promote가 아니라 ingest 경유가 정답. `build_reuse_projection` 재사용 금지(candidate/payload 기반이라 reviewed context-md를 못 다루고 `cli.py:586-593`의 reviewed 차단에 막힘). save_object 직접 호출 금지(부분 쓰기·후퇴 위험). 단 `ingest.py:33-37` 낙관적 잠금(preconditions)에 현재 `updated_at`을 정확히 넘기거나 preconditions 없이 호출.
- [ ] **C3 Step 3:** C2로 해시식이 바뀌었으니 `projection refresh`로 기존 코퍼스 전수 재계산(데이터 레포에서 실행).
- [ ] **회귀:** 엔진 470 + 데이터 레포 unittest·rebuild·eval(10/10 복구 확인).

### Task C1: 고립 노드(연결 0) 탐지 CLI `graph isolated` (engine)

**Files:**
- Modify: `src/project_brain/cli.py` — `graph isolated [--brain-root] [--kind ...]` 서브커맨드(main 디스패치 `cli.py:689-723`에 추가)
- New/Modify: 역인덱스 헬퍼(인바운드 집계) — C8과 공유. 위치는 `assembly.py` 또는 신규 `graph.py` 중 구현 시 결정.
- Test: `tests/test_cli.py`(또는 신규 `tests/test_graph.py`)

**근거:** 역참조/무엣지 검사가 엔진 어디에도 없음(`grep isolated/orphan/inbound` 0건). store는 id·kind 인덱스만(엣지/차수 인덱스 없음). search 그래프 신호는 질의 top-30 한정이라 코퍼스 전수 고립에 못 씀. 유일 수단은 데이터 레포 git-미추적 프로토타입 `graph_export.py`(고립을 프로그램으로 리포트조차 안 함). 4세션 전부 ad-hoc 파이썬으로 손계산.

> ⚠ **critic 검수(2026-06-23)로 정의 3곳을 확정 — "구현 시 결정"으로 비워두면 합성 테스트는 통과하되 실코퍼스에서 폭주한다.** 아래 정의는 Global Constraints의 인바운드/면제 제약과 한 쌍이다.

- [ ] **Step 0 (정의 확정 — 구현 전 필수):**
  - **(a) 인바운드 필드 집합** — 복수 `_ids` + 단수 brain-참조 `_id`(`context_id, evidence_manifest_id, derived_from_event_id, spec_document_id, spec_revision_id, target_object_id, source_object_id, review_record_id`) + **`evidence_refs` 포함**. 외부 키 `channel_id`·`project_id`는 **제외**. schema.py에서 정본 추출해 목록을 코드 상수로 박기.
  - **(b) 점검 대상 kind 화이트리스트 — 19 kind 전수 분류(critic 2차 권고로 "등" 제거).** 면제를 `truth_role` 술어로 하면 안 됨(DomainContext는 domain이라 안 걸리고 SlackThread가 source라 딸려옴). 아래 표가 정본:

    | kind | truth_role | 점검? | 분류 근거 |
    |------|-----------|------|-----------|
    | CodeLocator | reference | ✅ 점검 | `code_locator_ids`로 가리켜지는 잎 — 도구 주목적 |
    | GlossaryTerm | domain | ✅ 점검 | `glossary_term_ids`로 가리켜지는 잎 — 도구 주목적 |
    | EvidenceRef | reference | ✅ 점검 | `evidence_refs`로만 가리켜지는 잎 |
    | SpecRevision | reference | ✅ 점검(실측 조건) | `spec_revision_ids` 종착점 |
    | SpecDocument | reference | ✅ 점검(실측 조건) | `spec_document_id` 종착점 |
    | SlideRef | reference | ✅ 점검(실측 조건) | reference 종착점 |
    | EvidenceManifest | source | ❌ 면제 | 근거 원본(루트) — 인바운드 0이 정상 |
    | DomainContext | domain | ❌ 면제 | 컨텍스트 루트 |
    | SlackThread | source | ❌ 면제 | 외부 소스 |
    | CurrentView | synthesis | ❌ 면제 | 구조적 인바운드0 |
    | KnowledgePage | synthesis | ❌ 면제 | 구조적 인바운드0 |
    | Insight | synthesis | ❌ 면제 | 대부분 인바운드0 정상 |
    | IndexRecord | index | ❌ 면제 | 구조적 인바운드0 |
    | ContextProjection | index | ❌ 면제 | 미참조 정상(별도 레인) |
    | EventLedgerRecord | event | ❌ 면제 | `derived_from_event_id`로만, 미참조 정상 |
    | DecisionRecord | event | ❌ 면제 | 독립 결정 가능 — 미참조 정상 |
    | ReviewRecord | review | ❌ 면제 | 미참조 정상 |
    | DomainMapping | domain | ❌ 면제 | 최상위 매핑 — 미참조 정상 |
    | TemporalFact | fact | ❌ 면제 | 뷰 미포함 정상 |

    **실측 조건:** `SpecRevision·SpecDocument·SlideRef`가 데이터 레포에 실제 적재돼 있는지는 엔진 schema만으론 미확정(critic 단서) — 구현 시 데이터 레포에서 적재 여부 확인 후 점검 대상 확정. 빠져도 거짓 음성(안전측)이라 도구 주목적(CodeLocator·GlossaryTerm·EvidenceRef)엔 영향 없음.
- [ ] **Step 1 (실패 테스트):** 두 가지를 한 번에 — ① 매핑 없는 CodeLocator는 고립으로 **잡힘**, evidence_refs로만 가리켜진 EvidenceRef·단수 `_id`로만 가리켜진 객체는 고립으로 **안 잡힘**. ② **구조적 인바운드0 kind(CurrentView·Insight)는 고립으로 안 잡힘**(이게 핵심 — 지금 폭주 방지 테스트가 없으면 CodeLocator만 보고 거짓 통과한다).
- [ ] **Step 2 (구현):** store 1회 순회로 역인덱스 생성(Step 0(a) 필드 집합 기준 "어떤 객체가 무엇을 가리키는지") → 점검 대상 kind(Step 0(b)) 중 인바운드 0인 id를 JSON 출력. **읽기 전용**(store 변경 0).
- [ ] **회귀:** 엔진 470 + 데이터 레포에서 `graph isolated` 출력 실측. **단 graph_export(프로토타입)와 엣지 정의가 다르면**(graph_export는 "값이 id면 엣지"라 외부 키도 포함) 수치가 안 맞는 게 정상 — 대조 전 두 엣지 집합 차이를 먼저 설명하고 일치/차이를 명시.

---

## Phase 1 — P1

### Task C7: 적재 후 고립 잎 재점검 + 연결 정책 명문화 (skill) — C1 종속

**Files:** `bb2_client/.agents/skills/bb2-brain-ingest/references/ingest-tools.md`(:179-201 적재 후 확인), `SKILL.md`, `bb2-brain-session-ingest`(폐기 candidate 정리). 스킬 수정은 사전 승인 필요(skill-and-project-files 규칙).

**근거:** 고아 처리가 전부 적재 *전*(규칙7/자가점검7/체크리스트6)이거나 lint 구조검사. 적재 후 확인 4단계(lint·index·eval·search)에 고립 잎 역점검 없음. "고립 정비가 새 매핑 적재로 번질 수 있음" 교훈 반복.

- [ ] C1의 `graph isolated`가 선행 완료됐는지 확인(없으면 텍스트만 넣어도 적재 전 수동 스캔과 동일해 공허).
- [ ] "적재 후 확인"에 `graph isolated` 출력으로 신규/잔여 고립을 나열 → 각각 (a)즉시 연결 (b)의도적 종착점이라 둠 (c)rejected/제거를 사람이 판정하는 단계 추가. "어느 매핑에 union할지는 사람 몫" 명시.
- [ ] **연결 정책 명문화**(워크플로 약점 가드): primary/공동primary/secondary 희석 기준, `history_coverage=complete` 판정 기준(4종 다 필요 아님 — 알려진 변경집합 전부 연결인가)을 스킬에 박아 LLM 기본 성향이 작업 목표를 이기지 못하게.

### Task C4: 시점 자동기입 회귀 테스트 (engine)

**Files:** `tests/test_cli.py`. 코드 본체는 이미 반영됨(`cli.py:123,207,496,558,663` `or now_kst()`), 누락 write 경로 없음(전수 확인).

- [ ] **실패 테스트:** build 노트에 `context.now`를 **생략**했을 때 엔진이 `now_kst()`로 created_at/updated_at을 자동 기입하는지 검증(현재 `test_cli.py:777-811`엔 없음 — 항상 now 명시 또는 context 누락 에러만). 신규 코드 0줄.

---

## Phase 2 — P2 (가드·문서)

### Task C8: build() 사후 비차단 고립 경고 (engine)
- **Files:** `assembly.py`(:339-364 사후검사 구간 + :366-367 반환 dict에 `warnings`), `cli.py`(:505-509 `_run_build` 출력에 warnings). C1과 역인덱스 헬퍼 공유.
- [ ] merged store에서 이번 묶음 신규 잎 중 인바운드 0인 것을 찾아 report `warnings`로 담기. **차단 아님**(candidate 일시 고립은 정상). 점검 대상·면제는 **C1 Step 0(b)의 19 kind 화이트리스트를 그대로 공유**(truth_role 술어 아님). 역인덱스 헬퍼도 C1과 공유. 실패 테스트 → 구현.

### Task C6: 객체행 카운트 자동화 (skill)
- **근거:** 엔진은 이미 `{indexed, raw_chunks}` 출력(`cli.py:266-270`). 엔진 추가 불필요(카운트 검증 명령 신설은 오버빌드).
- [ ] 데이터 레포 가드를 하드코딩 `EXPECTED_OBJECT_ROWS` 대신 report 기반 검증으로 바꾸도록 `ingest-tools.md`에 절차 명문화 + **색인 제외 kind 표**(EvidenceRef·EvidenceManifest 등)를 박아 암산 제거.

### Task C9: search 결과 키 명문화 (skill)
- **Files:** `src/project_brain/templates/query.md`(정본 템플릿 — install이 배포본 `bb2-brain-query/SKILL.md`로 동기화).
- [ ] **한 줄 노트**만 추가: 결과 원소 키는 `object_id`(id 아님), 코드 위치는 `linked.code_locators[].path:symbol`. 전체 스키마 표는 graph_* 내부 랭킹 신호까지 동기화 부채라 오버빌드 — 금지. `linked.code_locators`·`context_id`는 이미 명시돼 중복 금지.

### Task C10: pytest→unittest 문서 정정 (engine)
- **Files:** 이 레포 `CLAUDE.md`(실코퍼스 회귀 절, `pytest brain/checks/ -q`).
- [ ] `python3 -m unittest discover -s brain/checks -p "test_*.py"`로 정정(스킬 2곳은 커밋 35e7ad4로 이미 정정됨). 데이터 레포 `brain/checks/test_real_corpus.py:7` docstring에도 같은 불일치 1건 더 있음 — 함께 고려.

---

## 안 할 것 (기각 — 이미 존재, 작업 대상 없음)

- **C5 (build 노트 검증 단일화):** cli에 노트 검증 0건, `validate_notes`(`assembly.py:259-308`)가 이미 유일 정본. 커밋 e2786d4가 분산의 유일 사례(context.now 필수)를 폴백으로 교체하며 제거함. 흡수할 대상 없음.
- **C11 (truth_role enum 사전 안내):** `object-model.md:76-94`에 kind별 truth_role 강제 표가 이미 있고 문제 행 `:83 EvidenceRef | reference`도 존재. SKILL.md가 3곳에서 이 표로 라우팅. 안내 부재가 아니라 작성자가 안 본 것 + 2층 schema가 안전히 막는 1회 재시도라 1층 중복 검증은 simplicity 위반.
