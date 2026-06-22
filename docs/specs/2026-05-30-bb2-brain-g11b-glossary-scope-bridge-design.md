# BB2 Brain G11b — Glossary Scope Bridge (한↔영 scope 다리)

- 작성일: 2026-05-30 (advisor 리뷰 반영 개정)
- 브랜치: `docs/bb2-brain-object-model`
- 대상 게이트: Tier 2 G11b (코어) + G11c (후속, 분리)
- 선행: G9(데이터 기반 scope 필터), G11a(scope 값 word-boundary 토큰 매칭)
- 관련 spec: object-model §11.2 / query-routing §4·§6.3
- 리뷰: BB2 advisor surface(2026-05-30) — 코어 방향 승인, 결함 7건 반영(아래 §9 changelog)

## 1. Purpose

한국어 쿼리에서 scope 필터가 작동하게 만든다. 사용자가 "입장팝업 현재 QA 기준은?"처럼 한국어 화면 이름으로 물으면, 브레인이 그 단어를 해당 화면의 scope 값으로 변환해 관련 fact만 거른다.

## 2. Grounding — 이건 신규 설계가 아니라 기존 명세의 구현

설계 근거는 현재 세션 대화가 아니라 repo spec + object model에 이미 있다 (vault base 우선 원칙):

- **query-routing §4 (preflight, L76-93)**: 모든 쿼리는 intent 라우팅 전에 `DomainContext`/`GlossaryTerm`으로 도메인 용어를 canonical 정규화한다.
- **query-routing §6.3 (L172-173)**: scope 필터는 6차원 conjunctive. "The router may infer **feature or surface** from a matched `GlossaryTerm` only when the context map has a single matching leaf. It must state the inferred scope in the answer when that scope affects the result." → **glossary가 추론을 허가받은 차원은 feature/surface 둘뿐**(D1 축소 근거).

### 데이터 출처 갭 (구현 못 한 이유)

- `GlossaryTerm`(object-model §11.2): `term/definition/avoid/synonyms/related_terms/related_objects` — scope 필드 없음.
- `DomainContext`(§11.1): `scope: {project, module?, directory?}` — feature/surface 없음.
- §6.3 L173이 추론하라는 feature/surface의 실데이터 출처가 객체에 없다.

### §6.3 "single matching leaf"는 surface granularity엔 부족

stage-clear-token CONTEXT.md 한 leaf가 `입장팝업` + `컨티뉴 팝업` 두 surface를 묶는다(CONTEXT.md L8). leaf 매칭만으론 surface 구분 불가 → term별 scope 데이터가 필요(leaf 단위 아님).

### 현재 토큰화 갭

브레인 유일 토크나이저 `_SCOPE_TOKEN_RE`(`router.py:7`, `[0-9A-Za-z._-]+`)는 ASCII만 추출 → 한글 scope를 못 잡는다. 나머지 라우터(`intent.py` `classify_query`/`normalize_terms`)는 substring `in` 매칭이라 한글 정상 — 브레인 확립 관례는 한글 substring.

## 3. 결정 (Decisions)

### D1. scope 매핑 = GlossaryTerm 신규 필드 `scope_hint`, **{feature?, surface?} 2차원만**

- 대안 a2(`related_objects` 간접)/a3(`DomainContext.scope` leaf 단위) 거부 — leaf 다중 surface 문제(§2).
- **차원 = feature/surface 둘만.** §6.3 L173이 glossary 추론을 허가한 차원이 정확히 이 둘. project/release/platform/module까지 넣는 건 권한 초과 + YAGNI(용어는 보통 릴리스 불변). 2차원 축소가 ASCII 안전성(D3)도 강화.

### D2. 한글 쿼리 → GlossaryTerm 매칭 = substring + **string-containment** longest-match

- `term in query` substring: 조사 무시. `intent.py` `normalize_terms` 관례와 동일.
- **longest-match 규칙 못박음(string-containment)**: 등록 term T의 매칭 문자열이 *다른 등록 term*의 매칭 문자열에 포함될 때만 T 제거. 예: `팝업` ⊂ `입장팝업` → `팝업` 제거. `컨티뉴 팝업` ⊄ `이벤트 클러스터` → 둘 다 유지(§5 다중 term과 정합). 전역-최장-1개 아님, 위치-스팬 아님.
- **잔여 충돌 한계 명시(과대보장 금지)**: longest-match는 *등록된* term끼리만 겹침을 해소한다. **미등록 상위어가 등록 term 문자열을 포함하면 막지 못한다** — 예: 등록 term `입장팝업`(→PopupEnter), 쿼리에 미등록 `입장팝업랭킹` → substring `입장팝업` ⊂ `입장팝업랭킹` → PopupEnter 오주입(longest-match 무력, 긴 쪽 미등록). 한글은 공백 토큰화 불가라 substring이 불가피하나, G11a가 ASCII에서 whole-token으로 막은 prefix 충돌이 한글에선 잔존한다. **유일한 방어는 통제 어휘 큐레이션**(GlossaryTerm 등록 시 상위어 충돌 점검). G11a급 보호를 준다고 보장하지 않는다.

### D3. 토크나이저 미변경

fixture scope 값은 전부 ASCII canonical(`release: "5.5"`, `surface: "PopupEnter"/"PopupContinue"`, object-model §10 동일). 한글은 쿼리에만 등장하고 glossary 경유로 ASCII scope_hint로 변환된다. `_SCOPE_TOKEN_RE`는 ASCII 그대로. mecab/형태소는 §7 Phase3.
- 단, `BrainStore.load`(`store.py:14-21`)는 스키마 검증 없이 JSON을 읽는다. 한글 scope/scope_hint 값이 들어오면 crash 없이 조용히 필터 누락된다. 오늘은 전부 ASCII라 문제없으나 막는 장치도 없음 → §5에 ASCII 단언 테스트 추가.

### D4. 범위 = **분할** (G11b 코어 / G11c 후속) — Karpathy surgical

advisor 리뷰: AVOIDED_TERMS 제거 + normalize 시그니처 일반화는 코어(한글 scope 필터)에 0 기여이고 intent public API 변경 + test_intent.py 파손 = 최대 폭발반경. 분리한다.

- **G11b (코어)**: scope_hint 필드 + `_query_scope_filters`의 scope_hint 추론 + fixture(term rename + scope_hint + 용어가드). 시그니처 변경 없음 → test_intent.py 무영향.
- **G11c (후속, 별도 게이트)**: `normalize_terms`/`classify_query` 시그니처 일반화 + `GlossaryTerm.avoid` 읽기 + 하드코딩 `AVOIDED_TERMS` 제거 + `avoided_terms→avoid` rename + test_intent.py 갱신. 하드코딩↔fixture 중복 제거는 여기서.

## 4. 변경 사항 (G11b 코어)

### 4.1 Object model (GlossaryTerm 한정)

- 신규 필드: `scope_hint?: { feature?: string; surface?: string }`. 값은 ASCII canonical 식별자, 동일 차원 `TemporalFact.scope` 값과 일치.
- 불변조건 추가: "`scope_hint`의 feature/surface 값은 동일 차원의 `TemporalFact.scope` 값과 같은 ASCII canonical 식별자여야 한다."
- 다른 객체(DomainContext 포함) 무변경.

### 4.2 Router (`scripts/bb2_brain/router.py`)

`_query_scope_filters(query)` 확장:

1. 기존: reviewed `TemporalFact`의 scope 값 ↔ query ASCII 토큰(G11a) 매칭 — 유지.
2. 신규: reviewed `GlossaryTerm` 중 `term`이 query에 substring 포함되는 것 수집 → string-containment longest-match(D2)로 겹침 제거 → 채택 term의 `scope_hint`(feature/surface) 값을 동일 차원 필터 set에 합류.
3. 합류 결과는 기존 `_scoped_facts`가 사용(차원 내 set=OR, 차원 간 AND).

추론 공시(§6.3 L173 의무, 조건부): 주입한 glossary scope가 **fact set을 실제로 좁혔을 때만** 공시. 채널은 기존 `warnings`(G9 release-모호 공시 선례) 재사용하되 문구로 "추론(문제 아님)" 구분 — 예 `용어 '입장팝업'에서 scope 추론 → surface=PopupEnter`. (전용 필드 분리는 G11c 이후 검토, 코어 범위 밖.)

### 4.3 Preflight / intent

**G11b에서 변경 없음.** 하드코딩 `AVOIDED_TERMS` + `normalize_terms`/`classify_query` 시그니처는 G11c로 이관. G11b는 intent 모듈을 건드리지 않는다(test_intent.py 무영향).

### 4.4 데이터 (`scripts/bb2_brain/tests/test_router.py` fixture)

- 기존 GlossaryTerm "입장팝업": `canonical_term → term` rename(코어가 `.term`을 읽으므로 필수, 동시에 object-model §11.2 명칭 정합) + `scope_hint: {surface: "PopupEnter"}` 추가. `avoided_terms`/`synonyms`는 그대로 둠(avoid rename은 G11c).
- 신규 GlossaryTerm: "컨티뉴 팝업" `scope_hint: {surface: "PopupContinue"}`, "이벤트 클러스터" `scope_hint: {surface: "PopupEnter"}`(입장팝업 내 UI).

### 4.5 문서 정합 (query-routing §6.3)

§6.3 본문은 leaf 기반 추론 + "single matching leaf" 가드. G11b가 이를 term-`scope_hint`로 대체하므로 **query-routing §6.3 문구를 갱신**(leaf 추론 → matched GlossaryTerm.scope_hint 추론)하거나 최소 "추론 메커니즘 G11b에서 scope_hint로 대체" 한 줄 추가. object-model ↔ query-routing 모순 방지.

## 5. 테스트 (G11b)

- 한국어 쿼리 scope 필터: "입장팝업 현재 QA 기준" → surface=PopupEnter 적용, 무관 surface fact 제외.
- string-containment longest-match: `팝업`+`입장팝업` 등록 시 `입장팝업`만 주입 / `컨티뉴 팝업`+`이벤트 클러스터` 둘 다 유지.
- 잔여 충돌(문서화된 한계): 미등록 상위어 케이스는 테스트로 막지 않음 — 큐레이션 책임임을 주석.
- 조건부 공시: 주입 scope가 fact set 좁혔을 때만 warnings 문구.
- 다중 term: 컨티뉴 → PopupContinue, 클러스터 → PopupEnter.
- **ASCII 단언 테스트**: 모든 reviewed fact.scope + GlossaryTerm.scope_hint 값이 ASCII canonical인지 단언(store 검증 부재 보완, D3).
- **회귀 정확성**: 기존 test_router "입장팝업" 쿼리들이 G11b 후 surface=PopupEnter 주입받아도 깨지지 않음 — 근거는 fixture fact(current/old-rule)가 둘 다 PopupEnter(`test_router.py:39,53`)라 주입 surface ⊇ 기존 fact surface(우연 안전 아님, 명시). test_intent.py는 G11b가 intent 모듈 미변경이므로 무영향.
- 기존 34 테스트 통과 유지(test_router 25 + intent/status/store 9). **(개정: "그대로 통과"는 시그니처 변경 없는 G11b 한정 참. G11c에서 test_intent 갱신 필요.)**

## 6. 엣지 / 불변 (G11b)

- glossary 매칭 0개: 기존 동작(ASCII 토큰 매칭만).
- 같은 차원 복수 surface(입장팝업+컨티뉴 동시): set(OR) — 충돌 아님.
- string-containment longest-match로 등록 term 간 짧은 term 오매칭 차단. 미등록 상위어 충돌은 못 막음(D2 한계, 큐레이션 방어).
- `_SCOPE_TOKEN_RE` 불변(ASCII).

## 7. Out of scope (deferred)

- **G11c (별도 게이트)**: normalize/classify 시그니처 일반화 + GlossaryTerm.avoid 읽기 + 하드코딩 AVOIDED_TERMS 제거 + avoided_terms→avoid + test_intent.py 갱신.
- mecab/형태소 토크나이저, 의미기반/벡터 검색 → §7 Phase 3(IndexRecord). 레퍼런스: HwiCortex(`[[2026-05-30-bb2-brain-external-memory-systems-mapping]]`).

## 8. References

- object-model §11.1 DomainContext / §11.2 GlossaryTerm / §10 TemporalFact.scope
- query-routing §4 preflight / §6.3 (L172-173 scope 추론, feature/surface 한정)
- 코드: `scripts/bb2_brain/router.py`(`_SCOPE_TOKEN_RE` L7, `_query_scope_filters` L116, `_scoped_facts` L127), `intent.py`(`AVOIDED_TERMS` L17 — G11c), `store.py`(`load` L14-21, 스키마 검증 없음)
- fixture: `scripts/bb2_brain/tests/test_router.py` L116-129 / `test_intent.py` L8,13,17(G11c 영향)
- 설계 맥락 허브: vault `[[bb2-brain-design-hub]]`

## 9. Advisor 리뷰 반영 (2026-05-30)

| # | 지적 | 반영 |
|---|------|------|
| 1 | §5 "34 통과" 거짓 (test_intent 시그니처 파손) | 시그니처 변경을 G11c로 분리 → G11b는 test_intent 무영향. §5 문구 정정 |
| 2 | substring이 한글 prefix 충돌 재오픈, 과대보장 | D2에 잔여 충돌 한계 + 큐레이션 방어 명시 |
| 3 | longest-match 모호 | D2 string-containment로 못박음 |
| 4 | scope_hint 6차원 권한 초과·YAGNI | D1 {feature?, surface?} 2차원 축소 (최고 가치 수정) |
| 5 | §6.3 문서 드리프트 | §4.5 query-routing §6.3 갱신 deliverable 추가 |
| 6 | warnings 채널 + 무조건 공시 | §4.2 조건부 공시(set 좁혔을 때만), 채널은 G9 선례 유지 |
| 7 | AVOIDED_TERMS 제거 폭발반경 | D4 G11b/G11c 분할 |
| 🟡 | store 검증 부재 → 한글 silent drop | §5 ASCII 단언 테스트 |
