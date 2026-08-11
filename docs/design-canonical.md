# project-brain — 설계 정본 (범용 프로젝트 브레인)

> 이 문서는 brain의 **정체성·철학·아키텍처·미결 사항**을 담은 설계 정본이다.
> BB2 게임(LineBubble2 — Cocos2d-x 버블슈터)의 내부 도구로 출발해 2026-06에
> 범용 엔진으로 분리됐다. 도메인 데이터·적재 이력은 각 프로젝트 레포(`brain/`)에
> 남고, 이 레포는 엔진과 그 설계 히스토리만 갖는다.
>
> 진행 단계·완료 이력·미뤄둔 작업은 [ROADMAP.md](../ROADMAP.md)에 있다. 이 문서는
> "무엇을 왜 이렇게 만드는가"의 설계 근거를 담는다.

## 0. 전제 출처

- 모든 설계 전제는 **사용자 발언 원장**으로 역추적된다(vault 보관, 개인 raw):
  `/Users/al03040455/Desktop/vault/inbox/dumps/bb2-brain/2026-06-10-user-statement-ledger.md`
- 사용자 발언에 근거한 항목은 **[발언]**, LLM 제안(승인 전이거나 골격 수준 동의)은
  **[제안]**으로 표시한다.
- 이 정본은 2026-06-10 재정립판이다. 2026-05-27~06-09 사이 쌓인 초기 설계 문서들은
  LLM 작성 과정에서 추측·범위 좁힘이 누적돼 신뢰가 떨어졌다는 판단에 따라, 발언 원장
  복원 → 사용자 확인 → 표적 인터뷰 → 재작성 절차로 만들어졌다. 초기 문서들은
  `docs/specs/`·`docs/plans/`에 히스토리로 보존된다(전제로 쓰지 말 것).

## 1. 정체성 — 무엇을 만드는가 [발언]

> "현재 프로젝트를 같이 개발한 동료… 과거의 개발 과정, 기획서, 슬랙 대화 내역, 코드 PR,
> 커밋 과정을 기억하는 머리통. 우리는 망각하지만 기록하고 기억하는 거지" (05-23, 최초 구상)

- **범용 프로젝트 브레인**. 도메인(BB2 샐리 카누 등)은 그 위의 첫 데이터 한 조각일
  뿐이고, 코드만 들어가는 것도 아니다(코드 작업 없는 세션의 인사이트 포함). QA 처리
  전용도, "왜?" 전용도 아니다.
- **사용 모델**: 사용자가 어시스턴트에게 질문하면 **어시스턴트가 brain을 사용해**
  근거와 함께 답한다. "브레인 cli를 내가 사용하는 게 아니야. 나는 너에게 질문하고
  너가 cli를 사용하는 거야" (06-08). 완성 후엔 훅/스킬로 감싸 질문에 필요한 지식만
  로드한다 (06-02).
- **개발 기여가 동격 목적** [발언 06-12]: "단순히 어떻게 동작하는지를 묻는 게 아니라,
  a기능 추가·b기능 수정 등이 요구사항일 때 brain에서 필요한 내용을 찾아 context를 만들
  수 있어야 해. 그래야 매번 컨텍스트 설명을 하지 않아도 되고, 개발할 수 있는 지식이
  쌓이면 점점 프로젝트 이해도가 높아지잖아. 실제 개발자가 프로젝트 지식이 있어야
  개발하고 답변도 하는 것처럼 마찬가지 역할" — 기존 적재물 포함 brain 전체의 역할
  기준. 질문 답변만 검증하던 골든셋에 **개발 착수 시나리오**가 추가되어야 하는 근거.
- **팀 공유가 최종 목적**: "팀원들과 최종적으로 같이 사용해서 같이 데이터를 쌓는 게
  목적" (06-09). 단 현재는 혼자 시험 제작 단계 — 팀 공개 시점은 사용자가 정한다 (06-10).
- **개인 브레인은 나중에** 이 코어를 재사용해 별도로 만든다 (06-09).
- **존재 이유 기준**: 동료의 PKM(HwiCortex/hwi_PKM)보다 브레인 관점 성능이 못하면
  만들 이유가 없다 (06-02).

### 스코프 가드 — 좁히기 금지 [발언]

설계·구현 과정에서 LLM이 반복한 좁힘 4형태를 금지한다(여러 세션 반복돼 사용자가 명시
교정): (1) 범위 좁힘("QA용", "왜?축") (2) 도메인 박기(특정 기능을 인프라 자체로) (3)
특정 객체만 저장(DomainMapping 중심) (4) 요약 맹신(2차 문서를 raw 대신 근거로). 새 작업
전 이 문서와 발언 원장으로 복귀할 것.

## 2. 철학 — 왜 이 형태인가 (1차 자료 검증 2026-06-10)

- **출발점은 Karpathy LLM Wiki** [발언: "큰틀의 전신이 카파시 llm wiki라는거고 세부
  구현은 다르다" 05-27]. gist 원문의 핵심은 "RAG는 매 질문마다 처음부터 다시 찾고
  **아무것도 쌓이지 않는다** — 대신 누적되는 구조화 산물을 유지하라"이다.
- **우리 세부 구현의 차별** [발언+실사용 확립]: 마크다운 위키 대신 **구조화 객체 +
  검수 사다리**. 후보(candidate)는 후보라고 표시해 노출하고, 실 사용 중 "promote ok"로
  검수(reviewed) 승격 — "쓰면서 점점 정확해지는" 시스템 (06-08). 근거(EvidenceRef)와
  시간축(왜/그때)이 객체에 붙는다.
- **답변 규약** [발언+승인]: 검수 상태를 표시하고, 근거를 링크하고, 기록이 없으면
  없다고 답한다. 출처 간 신뢰 우선순위 존재(예: 모델 키값은 코드 > 서버위키, 06-09).
- **검색 색인은 필수 1급 인프라** [발언: "단어 일치만 되는 건 사전이지 브레인이
  아니잖아" 06-08 / "벡터·sqlite 과투자 판정은 잘못, 무조건 해야 하는 것" 06-09]. 단
  색인은 객체·raw에서 언제든 재생성 가능한 파생물이지 진실이 아니다 [제안 — v0부터 일관].
- **마크다운의 역할 구분** [발언, Q1 결정]: 마크다운은 **raw 형식**(기획서 변환 원문·긴
  분석문 보관, 불변, 색인, 근거 링크 대상)으로 쓴다. **지식 층(brain이 "안다"고 답하는
  것)은 검수 사다리를 타는 구조화 객체로만** 한다 — AI가 유지보수하는 "지식 마크다운
  문서" 층은 만들지 않는다.

> ★주의 — 과거 문서 오염원: "raw 먼저 / AI 마크다운 가중치 0"이라는 과거 발언은
> **brain 설계 작업 시 LLM이 참고할 자료를 고르는 규칙**이었다(2026-06-10 정정). brain
> 운영 신뢰 모델로 오용하지 말 것. 운영 신뢰는 위의 검수 사다리가 만든다.

### 왜 JSON 객체를 정본으로 두는가

**구조화 객체를 지식 단위로 삼는 결정**과 **객체당 JSON 파일 하나로 저장하는 결정**은
관련은 있지만 같은 결정이 아니다.

- **지식 모델은 구조화 객체다.** 현재 규칙, 특정 시점의 상태(as-of), 변경 이유를 안정적으로
  답하려면 검수 상태·근거·타입이 있는 관계·유효 시간 같은 칸이 명시돼야 한다. 자유 텍스트와
  타입 없는 링크만으로는 이 경계를 엔진이 검사하거나 결정론적으로 질의하기 어렵다. 이 결정은
  §0 사용자 발언 원장의 2026-06-10 재설계 인터뷰 Q1에서 구조화 객체 안으로 확정됐다.
- **물리 저장은 per-file JSON이다.** 객체 경계가 파일 경계와 같아 초기 PoC에서 Git diff,
  사람의 점검, 객체별 로딩과 수동 복구가 쉬웠다. 단일 가변 위키 페이지는 사건·사실의 출처와
  과거 시점 답변을 약하게 만들고, SQLite만 정본으로 두는 방식은 초기 단계의 diff·검토·복구를
  어렵게 해 기각했다. 당시 비교와 결론은
  [storage layout 설계](specs/2026-05-28-bb2-brain-storage-layout-design.md#3-recommended-approach)와
  [P0 router 계획](plans/2026-05-28-bb2-brain-p0-router.md#object-file-encoding-decision)에 남아 있다.
- **저장 형식과 검색 색인은 별개다.** JSON 객체와 Markdown raw에서 BM25·벡터 검색 색인을
  만들고, 객체의 타입 관계를 그래프로 탐색할 수 있다. SQLite와 검색 색인은 원본에서 다시 만들
  수 있는 파생물이며 지식의 정본이 아니다.
- **Markdown은 버리지 않았다.** 기획서 변환본·긴 분석문 같은 raw 원문, 근거 링크 대상,
  사람이 읽는 projection에 쓴다. 다만 AI가 따로 유지보수하는 지식 Markdown 문서를 독립 정본으로
  두지는 않는다.

이 형태의 계보는 한 자료를 그대로 복제한 것이 아니다. Karpathy LLM Wiki에서는 raw-first와
누적되는 산물이라는 철학을, GBrain에서는 원본과 다시 만들 수 있는 검색층의 분리를,
Mnemosyne에서는 `TemporalFact`의 시간축 트리플을, Sentra에서는 사건과 사실의 분리 및 과거 사실을
덮어쓰지 않고 닫는 방식을 가져왔다. 출처별 반영 범위는
[초기 storage layout의 source mapping](specs/2026-05-28-bb2-brain-storage-layout-design.md#2-basis--source-mapping)에
남아 있으며, 각 프로젝트의 코드 기반을 직접 가져왔다고 확대 해석하지 않는다.

> **2026-08-06 회고 보충:** 사용자는 초기 개인 지식관리에서 Markdown 한 페이지에 내용을 계속
> 모으면서 관리가 어려워진 경험도 출발 배경으로 기억한다. 이 표현 자체는 당시 문서에서 확인되지
> 않았으므로, 위 설계 근거를 대신하는 동시대 기록이 아니라 나중에 보충한 사용자 회고로 구분한다.

## 3. 아키텍처 — 층 구조 [제안 골격, Q1~Q3 결정 반영]

```
L0 Raw            기획서 md 원문(brain 보관)·위키/세션(링크만)·불변·색인 대상
L1 지식 객체       18 kind + Insight(신설·2026-06-15) · 검수 사다리 · 시간축 · 코드↔기획 매핑
L2 검색 색인       BM25 + 벡터 + RRF(+재랭킹 검토) · 한국어 형태소 · 객체+raw 커버 · 재생성 가능
L3 회상·답변       어시스턴트가 운영 · 의도 분류 + 검색 → 내용+검수상태+근거로 답 · 후보 표시→promote
L4 적재 경로       (1)개발 중 (2)완성 스펙 소급 (3)세션 중 "저장하자" · single/batch 완료 게이트 · 추출=LLM(스킬)/도구=범용 부품
공유 모델          [Q3→2026-06-11 분리 실행] 엔진/데이터 2-레포: 엔진=project-brain(글로벌 도구) · 데이터=프로젝트 레포 brain/ git 추적(raw 텍스트 포함) · 색인만 로컬
```

층별 근거 발언:

- **L0**: "기획서 raw 원문 보관 + md 변환 자료도 brain 폴더에 / 서버위키·세션로그는
  링크만 / 세션 대화 파일은 하드디스크에 있으니 brain에 raw 저장 안 함" (06-04). "raw는
  brain에 저장해두고 인덱싱해도 되고" (06-04) — raw 색인 [발언, Q1 후속].
- **L1**: "기획서의 개념 설명은 객체로 중복 저장 불필요(어차피 기획서에 다 있음) —
  코드를 가리키는 연결이 기획↔코드 일치" (06-04) + "코드 앵커 없는 지식(서버 판정 규칙,
  인사이트)도 저장 대상" (06-04 정정) + Q1: 인사이트도 자유 텍스트 본문의 **객체**로.
  "완료된 스펙은 코드가 뼈대, 코드에 없는 지식은 별도 저장+연결" (06-04).
- **L2**: "의미기반으로도 찾을 수 있어야 — 기억 안 나고 맥락만 던졌을 때 비슷한 것도"
  (05-29). 긴 인사이트 문서는 추출 품질이 관건이고, raw가 많아지면 raw 색인 필요(06-10).
- **L3**: 사용 모델(§1). 후보 노출→promote 흐름(06-05·06-08). "기록 없으면 없다"
  [승인 05-27].
- **L4**: 적재 3경로 + jira/confluence/슬랙(06-04). 세션 종료 hook에서 "저장할까요?"
  제안은 추가 기능(06-04, 후순위). 적재 도구는 도메인 모르는 범용 부품, 추출(판단)은
  LLM이 세션에서 하고 스킬로 감싼다(06-03 합의). 접근 순서는 기능 코드 리스트업 → 큰틀
  기획·서버 매칭 → 하위 지식화(06-05).

### 3.1 엔진/데이터 2-레포 분리 (2026-06-11 실행, B안)

"디렉토리 독립" 전망이 실제 분리로 집행됐다 — 범용 브레인(§1) 구조의 물리적 실현.

- **엔진 = `project-brain`(이 레포)**: 스키마·적재(ingest/promote)·lint·색인·검색·라우터·
  평가 하네스. 패키지 `project_brain`(src 레이아웃) + pyproject.
  `uv tool install -e <클론>`로 글로벌 도구 설치 — 편집 설치라 엔진 수정이 전 프로젝트에
  즉시 반영. install(스킬 템플릿 주입+manifest)·doctor·bootstrap 동봉. 합성 데이터
  테스트만 갖는다.
- **데이터 = 각 프로젝트 레포 루트 `brain/`**: 코퍼스(objects/raw) + 골든셋
  (eval_scenarios.json) + 실코퍼스 가드(checks/ — PATH의 `project-brain`만 subprocess
  호출, 엔진 import 0) + 색인(.brain-local, 로컬). 경로 해석은 레포 루트
  `.project-brain.json` config(cwd 상향 탐색, 명시 인자 > config > 에러).
- **적재 조립 자동화 `build`**: 기능 적재마다 손으로 짜던 "구조화 노트→객체 묶음" 조립을
  `project-brain build`로 대체. id 파생·객체 연결·끊긴 참조 검사는 엔진이, 판정
  (supersede·이력)은 노트에 명시(에이전트 몫). 조립 전 key는 `mapping.<context>.<key>`
  같은 완성 ID가 아니라 context 안의 logical key만 허용한다.
- **`build_decisions` — decisions[] 결정 조립** (2026-06-26): 위 `build`의 연장.
  `extra_objects` 탈출구로 손조립하던 `DecisionRecord`를 노트 `decisions[]` 1급 섹션으로 받아
  `DecisionRecord` + `EvidenceRef`(commit/jira/pr)로 결정론 조립(`build_decisions(notes, now)`).
  각 결정의 `affects[]`를 매핑 `decision_keys`로 역채움 → lint 8c(매핑↔결정 양방향) 자동 충족,
  단일 `now`로 churn 0. 같은 분업 유지(id 파생·연결·검증은 엔진, 무엇이·왜·어디에는 노트).
  왜: 손조립 DecisionRecord가 재적재마다 타임스탬프 churn + 양방향 수동 정합이라 엔진이 흡수.
  커밋 7c2f87c·91a9a6c·37d0da9.

### 3.2 L4 완료 경계와 installer 소유권 (2026-07-23)

적재의 의미 판단은 계속 LLM 스킬과 사람이 맡는다. 엔진과 설치 runtime은 판단을 대신하지
않고, 조용한 부분 성공이나 파일 유실을 막는 경계만 강제한다.

- **single/batch 분리**: 단건 runner는 assemble → build → ingest를 수행하고, batch item은
  `--defer-finalize`로 색인·평가를 미룬다. batch runner가 전체 item의 성공을 확인한 뒤
  index rebuild·lint·eval·graph·corpus tests·예상 객체 회수를 한 번만 실행한다.
- **완료는 구조화 결과로 판정**: workflow 최상위 `completed`는 근거가 아니다. 기대 item
  수와 각 item의 정확한 extract/verify `ok`, batch의 빈 실패 목록, semantic finalizer의
  구조화된 `ok=true`, 최종 `finalized=true`가 함께 있어야 닫는다.
- **설치 소유권**: manifest는 범용 템플릿이 만든 파일만 추적한다. 프로젝트 고유 코드 검증
  overlay처럼 manifest 밖 파일은 프로젝트 소유이며 `--force`도 건드리지 않는다.
- **퇴역도 보존 우선**: 템플릿에서 사라진 파일은 manifest 해시와 디스크가 일치할 때만
  설치 경로와 manifest에서 제거한다. 원본은 먼저 같은 디렉토리 backup으로 옮기고,
  manifest 확정이 실패하면 역순 복원한다. 사용자 수정 파일, 안전하지 않은 경로,
  일반 파일이 아닌 대상은 쓰기 전에 중단한다.

구체적인 실행 계약과 검증값은
[대량 적재 강화 설계](specs/2026-07-21-bulk-ingest-hardening-design.md)와
[완료 보고서](reports/2026-07-23-bulk-ingest-hardening-completion.md)에 있다.

### 3.3 Canonical ID 복구 경계 (2026-07-31)

ID 복구는 payload를 그대로 둔 **ID-only migration**과, ID에서 투영된 필드까지
최소한으로 바로잡는 **canonical repair**를 분리한다. strict ID grammar는 완화하지 않는다.
ID-only는 self ID와 등록 참조의 일대일 치환만 맡고, canonical repair는 승인된
DomainMapping의 `/mapping_key`와 bundle ReviewRecord의 `/target_object_ids` 두 pointer만
추가로 바꿀 수 있다. 그 밖의 payload 변경과 일반 delete-only는 모두 닫힌 쪽으로
실패한다. 이미 존재하는 target으로 합치는 경우도 아래의 검증된
`collision_merge_into_existing` 경로만 허용하며, 임의 덮어쓰기나 일반 목적 merge는
허용하지 않는다.

`review_shape_repair`의 bundle ReviewRecord source는 두 legacy 철자만 허용한다. 첫째는
`review.bundle.Neutral.domain-mapping`처럼 소문자로 바꾸면 bundle ReviewRecord로 파싱되고
그 `bundle_key`가 payload와 정확히 같은 대소문자 부채 형태다. 둘째는
`review.neutral.domain-mapping`처럼 `bundle.` 표지만 빠진 byte-exact
`review.{bundle_key.removeprefix('bundle.')}` 형태이며, 원래 source ID가 ReviewRecord로
파싱되지 않고 `target_object_id`도 없을 때만 허용한다. 검증은 항상 문법 파싱을 먼저 하므로
`review.context.neutral` 같은 유효한 single ReviewRecord를 bundle source로 다시 해석하지
않는다. canonical target은 두 경우 모두 exact `review.{bundle_key}`다.

엔진은 canonical ID를 추론하지 않는다. 데이터 레포가 Phase A 분류의 모든 행을 정확히
한 번 덮는 **canonicalization decision ledger**를 보존하고, 사람이 ID·허용 field diff·근거를
검토한다. 엔진은 그 원장 bytes와 classification bytes의 SHA, source object SHA, engine SHA,
repo HEAD, snapshot manifest SHA, corpus fingerprint가 모두 맞는지만 검증한 뒤 계획하고
적용한다.

canonical repair와 ID-only 사이에는 검증된 **intermediate snapshot**을 둔다. 앞 단계의
manifest와 expected-after fingerprint가 이 snapshot의 corpus와 정확히 맞아야만 원장에서
순수 ID rename map을 꺼낼 수 있다. 따라서 두 mutation은 같은 복구 작업에 속하지만 서로
다른 manifest와 snapshot 경계로 다시 계획·검증된다.

#### 기존 canonical target으로 합치는 충돌 복구

`collision_merge_into_existing`은 승인된 collision source를 이미 존재하는 canonical
survivor에 합치는 canonical repair action이다. 원장에서 뽑은 pair는
`project_collision_merges()`가 planner와 mutation validator 양쪽에서 같은 방식으로 다시
계산한다. source는 삭제하고 existing target은 update 입력으로 항상 `MutationRequest.objects`에
포함한다. 다만 `MutationManifest.updates`는 survivor의 before/after bytes가 실제로 달라질
때만 생긴다. 따라서 no-op survivor도 요청·live SHA·`CanonicalRepairRow`의
`canonical_payload_hash`·`merge_receipt`에는 계속 묶이지만 update 행은 없어야 한다.

병합 결과는 target의 `title`, `canonical_summary`, `meaning`, `boundary`, `poc_priority`를
정본으로 유지한다. `code_locator_ids`, `decision_record_ids`, `evidence_refs`,
`glossary_term_ids`, `tags`는 target 순서를 먼저 보존하고 source에만 있는 근거를 source
순서대로 붙인다. `history_coverage`는 `unsearched < partial < complete` 순서에서 두 입력 중
더 보수적인 값을 택한다. merge source와 target의 raw file bytes는 plan 전에 canonical
serialization과 일치해야 한다. 원본 `ContextProjection`이 merge source를 등록 참조 어디로든
가리키거나 byte-exact 변경 대상을 `source_object_ids`로 의존하면 중단하며,
`ContextProjection` 자체는 절대 다시 쓰지 않는다.

참조 감사 기록은 역할을 나눈다. `reference_rewrites`는 scalar 치환과 길이가 변하지 않는
list 치환의 정확한 before/after ID와 pointer를 기록한다. source와 target이 같은 list에
있어 source 항목을 제거하는 축약은 뒤 인덱스 이동을 pointer 치환으로 꾸미지 않고
`CanonicalRepairRow.merge_receipt.reference_collapses`에 before/after 배열과 제거 위치를
기록한다. `object_id`·`before_ids`·`removed_index`는 transaction 이전 좌표이고,
`after_ids`는 merge 단계 종료 뒤 field-repair 적용 전 좌표다. 한 list field에는 최대 한
merge pair만 올 수 있고 merge source는 collapse referrer가 될 수 없다. intermediate trusted
receipt 검증은 source가 live store에서 사라졌는지와 artifact delete의 before SHA를
원장·`merge_receipt`에 함께 대조한다. survivor bytes가 달라졌으면 artifact update의
before/after SHA를 요구하고, 같으면 update 행을 금지한다. 두 경우 모두 live survivor SHA,
row `canonical_payload_hash`, `merge_receipt.target_after_sha256`를 같은 값으로 묶는다.
collapse의 `object_id`와 `after_ids`는 승인된 field-repair rename map으로 최종 좌표에 투영한
뒤 live referrer 배열과 대조한다. merge target ID는 endpoint overlap 게이트로 불변이다.
이 검증을 통과한 뒤 merge source는 이후 순수 ID rename map에서 제외된다.

실코퍼스 적용에는 사용자 승인이 두 번 필요하다.

- **승인 게이트 1**: 읽기 전용 분류, 전체 decision ledger, 충돌 비교와 허용 field diff를
  검토·승인한다. 승인 전에는 canonical repair staging도 만들지 않는다.
- **승인 게이트 2**: byte-exact staging, 두 manifest와 SHA, intermediate snapshot,
  ID/dangling/payload 가드 및 전체 실코퍼스 회귀 결과를 검토·승인한다. 승인 전에는 live lock이나
  live corpus/index/stale-set을 바꾸지 않는다.

세부 계약과 Task 17 완료 조건은
[canonical ID 복구 설계](superpowers/specs/2026-07-31-task17-canonical-id-recovery-design.md)와
[collision merge 설계](superpowers/specs/2026-08-02-task17-collision-merge-design.md)에 있다.

## 4. 미결 사항 — 이름 박고 미룸

- **팀 확장 시 reviewed 승격 권한**(미결 5): 각자 promote vs 검수자 지정 (추후 논의 항목 — 팀 공개 시점에).
- **세션 종료 hook 저장 제안 기능**(미결 6): 시점·형태 (추후 논의 항목, 후순위).

해소된 미결(기록):

- **인사이트 그릇 kind**(미결 1): ✅ 2026-06-15 신설 `Insight` kind 엔진 구현 완료.
  설계 = [docs/specs/2026-06-15-bb2-brain-insight-kind-design.md](specs/2026-06-15-bb2-brain-insight-kind-design.md).
- **raw 보관 규약**(미결 2): ✅ 2026-06-10 — `raw/sources/<context>/` 텍스트만 추적,
  locator는 brain root 상대.
- **git 추적 경계**(미결 3): ✅ 2026-06-10 — brain/ 전체 추적, 색인+바이너리만 로컬.
- **project_id 범용화**(미결 4): ✅ 2026-06-10 닫힘 — 프로젝트 경계 = 레포 경계, 한
  brain에 다중 프로젝트 안 섞음.
- **코드 무관 지식의 경계 운용**(미결 8): ✅ 2026-06-10 — 기준 = **독립 회상 가치**
  (독립적으로 질문되고 독립 근거를 가질 수 있는가).
- **개인 메모리 상세 설계**(미결 7): ❌ 2026-07-06 안 만듦 — 엔진 L5(개인 메모리 층)는
  만들지 않는다. 단기(작업 연속성)·장기(개인 교훈·선호) 모두 handoff·auto-memory·vault task가
  이미 담당하며, 엔진에 두면 4번째 중복 저장 레인이 된다. 아키텍처 층 구조(§3)에서도 L5를 뺐다.

## 5. 작업 규율 — 재발 방지 가드

- **좁히기 금지**(§1 스코프 가드 4형태). 새 세션은 이 문서 §1·§2부터 읽는다.
- **전제는 발언 원장으로 역추적**. LLM이 만든 문서(이 문서 포함)의 단정이 의심되면
  원장과 raw로 복귀. "현재 세션에서 말한 것만 참고 포인트가 되지 않도록" (05-29).
- **검증 후 작성**: "검증하거나 체크할 게 남았으면 리포트를 왜 써? 검증을 하고 써야지"
  (05-26).
- **품질 우선**: "토큰 효율이 아니라 최고의 품질" (05-27).
- 설계 변경 시 이 문서를 갱신하고, 변경 근거(발언/검증)를 남긴다.
