# BB2 Brain — B+C 검수 모델 설계 v2 (저신뢰 노출 + 자동 승격 + 사용 시점 promote)

- 상태: draft-for-review (2026-06-05 작성, 2026-06-06 v2 자체 적대검증 반영, **v2**)
- 브랜치: `docs/bb2-brain-object-model`
- **1차 문서**: `docs/superpowers/specs/2026-06-05-bb2-brain-bc-review-model-design.md` (보존 — 이 v2가 대체)
- 설계 근거: [[bb2-brain-design-hub]] §8, task `[[bb2-brain]]`, 본 세션 brainstorming + 적대 검증 워크플로우

---

## 0. v1 → v2 변경 이력 (왜 고쳤나)

v1 초안을 architect/critic 역할(외부 하네스 프롬프트 `oh-my-codex/prompts/architect.md`·`critic.md`)로 구성한 다이나믹 워크플로우(Run `wf_58d3033e-bf2`, 19 에이전트, opus, 발견 15건·거짓 양성 0)로 적대 검증했다. 검증 에이전트가 코드를 직접 실행해 확인했고(예: 제안 schema 규칙을 입혀 `validate_object` 실행, 삭제된 테스트 임시 복원). 그 결과 + 사용자 결정 2건으로 아래를 고쳤다.

### 핵심 변경 (설계 방향 전환)

1. **검수됨 자격 기준을 "코드앵커 유무" → "검증된 근거 + 적대검증 통과 + lint clean"으로 (v1 §5.2 철회).**
   v1은 "검수된 DomainMapping은 코드앵커(`code_locator_ids`) 필수"를 코드로 강제해 B와 C를 가르는 분류기로 삼았다. **이게 틀렸다** — 사용자 지적: "서버규칙은 코드가 클라이언트에 없을 뿐, 틀리거나 모호한 정보가 아니다." 검증된 1차 근거(기획서·서버위키 등)가 있고 적대검증을 통과한 서버규칙(예: NPC 이동은 서버 소유, 실측상 기획서 근거)은 확정 사실이라 검수됨 자격이 있다. "클라 코드앵커 없음"과 "근거 약함·충돌(저신뢰/모호)"은 다른 차원인데 v1(과 design-hub §227)이 둘을 뭉쳤다.
   → 코드앵커는 **근거의 한 종류**일 뿐 필수가 아니다. B/C를 가르는 건 적대검증(에이전트). 이게 design-hub 토대("판정은 영구히 에이전트 몫, 코드·lint는 신호만")와 더 일관된다.

2. **마이그레이션(v1 §6 서버규칙 강등) 철회 → 기존 reviewed 근거 점검으로 대체 (§7).**
   코드앵커 없는 서버규칙 6개를 후보로 강등할 이유가 없어졌다(근거+검증 있으면 검수됨 유지). 대신 근거(`evidence_refs`) 자체가 빈 검수됨이 있으면 그것만 점검.

3. **후보는 "노출만", 충돌·추론 로직 입력에는 검수된 것만 (워크플로우 발견 2·9, major).**
   v1 §3.2 "매칭/scope 필터를 후보에도 적용"이 모호했다. 후보를 충돌 해소(`_resolve_current_conflicts`)·view 신선도 판정(`_stale_view_warnings`)·scope 추론(`_query_scope_filters`) 입력에 흘려넣으면 그 로직의 의미가 깨진다. 후보는 답 노출 재료로만 합류시킨다.

4. **`candidate_object_ids` 재사용 금지 → 전용 필드 (발견 6).** 현재 이 필드는 검수된 CurrentView(보조 객체) 번호를 담지(`router.py:137,241`) status=candidate가 아니다. 승격 후보는 별도 필드로.

5. **`needs_clarification` 처리 명시 (발견 7).** 후보만 노출되는 답은 사람 확인을 유도하게 `needs_clarification=True`.

6. **§테스트: "기존 테스트 유지" → "새 설계에 맞게 재작성" (발견 5 + 사용자 결정).** 회귀 테스트 7개(test_router/status/schema/lint/store/intent/context_projection)가 작업 트리에서 삭제(staged) 상태인데, 이는 이전 세션의 의도된 삭제(하드코딩 정리 여파)이고 커밋만 누락됐다. 복원하지 않고 새 버전으로 재작성한다.

7. **문구 정정 (발견 8, overstated).** "후보 섞이면 status 자연히 candidate" → raw-unavailable/restricted가 함께면 그 상위 라벨이 우선. 후보 식별은 status 값이 아니라 sections 라벨 + warnings로.

8. **promote 저장 경로·고아 검토기록 처리 명시 (발견 3·promote 저장).**

### v2 자체 적대검증 반영 (2026-06-06)

v2 draft를 같은 architect/critic 워크플로우(Run `wf_e1dba09b-5a7`, 26 에이전트, opus, 발견 22건·거짓양성 0)로 다시 검증했다. v1의 치명적 모순(코드앵커 강제↔서버규칙)은 해소 확인됐고(critical 0), 아래 5종을 반영했다(나머지 minor는 plan/구현 단계로).

- **A. candidate 용어 노출 경로 (발견 1·2)**: 현 코퍼스 후보는 전부 candidate GlossaryTerm(122개)인데 §4.2 안에서 "후보 일괄 노출"과 "candidate GlossaryTerm 정의 비노출 선례"가 충돌. 용어 정의 후보를 노출 대상으로 확정(§4.2).
- **B. 근거 강제 비대칭 (발견 4)**: §6.4가 DomainMapping만 근거 강제했으나 cli promote가 실제 다루는 건 GlossaryTerm. GlossaryTerm도 근거 강제(§6.4).
- **C. promote 검토기록 동반 저장 (발견 3)**: promote가 반환하는 검토 기록을 함께 저장 안 하면 없는 기록을 가리킴. 둘 다 저장 명시(§5.2/§5.3).
- **D. 사람 promote vs 자동 승격 경계 (발견 5)**: "모호 안 삼킴"은 자동 승격(B) 전용, 사용 시점 promote(C)는 사람이 판정(§5.2/§8).
- **E. §7 근거 표현 (발견 6)**: 서버규칙 근거를 "서버위키"로 단정했으나 실측상 다수가 기획서 근거. "검증된 1차 근거(무엇이든)"로 일반화(§7).

### design-hub 갱신 필요 (후속)
사용자 지적이 design-hub §8/§227의 분류 오류("코드앵커 없음 = 저신뢰 candidate")를 드러냈다. 이 spec 확정 후 design-hub §8(검수 자격 기준)·§227(서버규칙 5개 분류)을 "검증된 근거 + 적대검증" 기준으로 보강한다.

---

## 1. 배경과 목적

design-hub §8에서 **B+C 하이브리드**를 검수 방식으로 확정했다. 사람의 역할을 "저장된 것 전부 읽기"에서 "예외 판정 + 사용 시점 수정"으로 옮긴다.

- **B (자동 검수됨)**: 검증된 근거 + 적대검증 통과 + lint clean이면 사람 손 없이 검수됨으로.
- **C (저신뢰 노출)**: 근거 약함 / 소스 충돌 / 적대검증 실패는 후보로 두고, 답할 때 "확인 필요" 단서를 달아 노출.

현재 구현의 갭(design-hub §230): 라우터가 "이진"이라 검수된 것만 노출하고 후보는 안 보인다 → 후보로 두면 조용히 사라짐(silent). "B"는 되지만 "C"는 빌드가 없다. 이 spec이 그 갭을 닫는다.

### 왜 한 spec인가
C 없이 B만 켜면, 자동 승격에서 빠진 것이 후보로 떨어지는데 라우터가 후보를 안 보여줘서 사라진다. 세 경계(자동 승격 B / 저신뢰 노출 C / 모호 시 사람 질문 = 예외 큐)를 한곳에서 정의해야 일관된다.

---

## 2. 범위와 비범위

### 범위
- C: 라우터가 후보를 검수된 것과 함께 노출(노출만, 추론 로직 입력엔 안 넣음).
- 사용 시점 promote 루프: 답에 승격 후보 안내(전용 필드) + `cli promote` 신설.
- B: 적재 시 "검증된 근거 + 적대검증 통과 + lint clean" 기준 자동 승격.
- 기존 reviewed 근거 점검(v1 마이그레이션 대체).

### 비범위
- **빌드 3 (스킬 문구 재서술)**: 코드 확정 후 후속, 스킬 편집은 사용자 승인 후.
- 의미 검색 / IndexRecord (§7), mixed-intent (§5): 별개 항목.

---

## 3. 신뢰 라벨 모델 (현 상태 — 바꾸지 않음)

`status.py`는 이미 5단계 라벨을 표현한다. **그대로 둔다.**

```python
SEVERITY = {"reviewed": 0, "raw-only": 1, "candidate": 2, "raw-unavailable": 3, "restricted": 4}
```

- `claim_status(obj, *, raw_available, restricted)` — 객체 하나의 라벨.
- `answer_status(statuses)` — 여러 라벨 중 **가장 심각한 것**(SEVERITY 최대)을 답 전체 라벨로.

후보가 답 재료에 섞이면 `answer_status`가 **적어도** candidate(severity 2) 이상을 답 전체 라벨로 반영한다. 단 같은 답에 raw-unavailable·restricted가 함께 있으면 그 상위 라벨이 우선한다(실측: `answer_status(['restricted','candidate'])`='restricted'). **그래서 후보 포함 여부는 status 값이 아니라 §4.3의 sections 라벨·warnings로 판별한다.**

---

## 4. C — 저신뢰 노출

### 4.1 현재 막힌 지점

`router.py`의 의도 분기가 `_reviewed_by_kind(kind)`(L248)로 검수된 것만 답 재료로 모은다. 후보는 재료에 안 들어가 사라진다. `candidate_object_ids`(출력 L241)는 답을 뒷받침한 보조 객체(검수된 CurrentView) 번호일 뿐, 후보 노출 경로가 아니다(L137에서 채워짐).

### 4.2 바꿀 것 — 검수 우선 + 후보 함께 (노출만)

검수된 것과 후보를 함께 모으되 검수 우선 정렬. 후보는 숨기지 않고 "확인 필요" 라벨로 노출한다.

- 질문 종류(의도)별로 후보를 숨기는 차등은 두지 않는다(일괄 적용).
- 후보가 항상 보여야 사용 시점 promote 루프(§5)가 작동한다.
- 검수/후보 구분은 숨김이 아니라 라벨로.
- 검수된 게 전혀 없으면 후보만 노출.

**★핵심 경계 (워크플로우 발견 2·9) — 후보는 "노출 재료"로만 합류, "충돌·추론 로직 입력"에는 검수된 것만:**

라우터에는 검수된 것만 보는 로직이 여럿 박혀 있다. 이들은 **검수 전용을 유지**한다 — 후보를 넣으면 의미가 깨진다.
- `_resolve_current_conflicts`(L386) / `_conflicting_fact_groups`(L11): 충돌 해소·탐지. `kept`(L393)가 status를 안 보므로 후보를 합류시키면 후보가 "현재 사실"로 섞인다.
- `_stale_view_warnings`(L412): view 신선도 판정.
- `_avoid_corrections`(L267): 용어 보정.
- `_query_scope_filters`(L333) / `_glossary_scope_disclosures`: scope 추론·공시.

이건 의도별 차등이 아니라 **모든 의도 공통 규칙**이다 — 모든 의도에서 후보를 노출하되, 어느 의도든 충돌·추론 로직 입력에는 검수된 것만 쓴다. 합의("의도별 차등 없음")와 모순되지 않는다.

**구현 권고**: `_scoped_facts`/`_current_facts`를 직접 후보 포함으로 바꾸지 말 것. current_status 분기(L120-141)에서 검수된 fact로 충돌 해소·`kept` 산출을 끝낸 뒤, 노출 단계에서 별도 후보 수집기(신규, 매칭·scope 필터만 적용)로 후보를 sections에 라벨 붙여 추가한다. 이렇게 `kept`에 후보가 섞이는 사고를 구조적으로 막는다.

**★candidate 용어 정의 노출 (v2 검증 발견 1·2 — C의 실효성 핵심)**: 현 코퍼스의 후보는 사실상 전부 candidate GlossaryTerm(122개; DomainMapping 64개는 전부 검수됨)이다. 따라서 이들을 노출하지 않으면 C가 현 데이터에서 거의 실효가 없다. **candidate GlossaryTerm의 정의(meaning)도 "확인 필요" 라벨을 달아 노출 대상으로 삼는다.**

- 의도별로 어느 종류의 후보를 노출 수집기에 넣는지 1:1로 명시한다. 실데이터상 후보가 존재하는 유일 종류는 GlossaryTerm이고, 그 노출 경로는 `glossary_meaning` 의도다(`router.py:191`의 glossary_objects 수집을 검수 전용 → 검수 우선 + candidate 라벨 합류로 확장).
- **오독 방지**: `_matched_mappings`(router.py:298-302)의 "candidate GlossaryTerm을 매칭 표면으로만 쓰고 정의는 노출 안 함"은 **검수된 매핑이 답을 댈 때 candidate 용어를 매칭에만 쓰는 별개 맥락**이다. 검수된 매핑이 없을 때 candidate 용어 정의를 노출하는 것을 막지 않는다 — 둘을 분리해 다룬다("매칭 표면 사용" ≠ "정의 노출 금지").
- 단 노출하는 candidate 정의 텍스트는 후보 라벨 / `promotable_candidate_ids`에만 담고, 충돌·scope 추론 입력(위 목록)에는 넣지 않는다.

### 4.3 답 구조 변경

- `sections`의 각 객체 묶음에 신뢰 라벨 표기(검수됨/후보 구분). 후보가 어느 것인지 호출하는 쪽이 식별 가능해야 함.
- 후보가 섞이면 `warnings`에 담담한 단서 한 줄("확인 필요한 후보 항목 포함"). 과한 경고 금지.
- 답 전체 라벨(`status`)은 `answer_status`로 가장 심각한 것. **단 후보 포함 판별을 status 값에 의존하지 않는다**(§3 — 상위 라벨이 가릴 수 있음).
- **`needs_clarification`(L245)**: 검수된 게 전혀 없고 후보만 노출되는 답은 사람 확인을 유도하기 위해 `True`로 둔다. 따라서 후보 번호는 `source_ids`가 아니라 후보 전용 필드(§5.1)에 담아 `needs_clarification` 식을 건드리지 않는다.

---

## 5. 사용 시점 promote 루프

design-hub §224 "사람의 역할 = 예외 판정 + 사용 시점 수정"을 굴리는 고리. 후보를 미리 다 검수하지 않고, 답하다가 마주칠 때 사람이 그 자리에서 확정(§228 lazy).

### 5.1 라우터는 읽기 전용 유지

라우터는 답만 하고 저장하지 않는다.
- 답 dict에 "승격 가능한 후보 번호"를 **전용 신규 필드**(예: `promotable_candidate_ids`)에 담는다. **기존 `candidate_object_ids`를 재사용하지 않는다** — 그 필드는 검수된 CurrentView(보조 객체) 번호를 담아(router.py:137,241), 한 필드에 "보조 view"와 "승격 대상 후보" 두 이질적 의미가 섞이면 호출하는 쪽이 구분 못 한다.
- `candidate_object_ids`는 current_status 의도 분기(router.py:120-141)에서만 채워진다(L137). 따라서 새 `promotable_candidate_ids`는 그 current_status 전용 채움 패턴을 따르지 말고, 의도와 무관하게 후보를 노출하는 모든 의도에서 채운다.

### 5.2 `cli promote` 신설

`cli.py`에 현재 promote 진입점이 없다(query·ingest만). 새로 만든다.
- 입력: brain-root, 승격할 후보 번호, 검수자, 검수 시각.
- 동작: `promote.py`의 `promote(..., scope="single_object", ...)`는 (승격 객체, 검토 기록) **두 가지**를 반환한다. **둘 다** `BrainStore.save_object`로 직접 저장한다 — 승격 객체가 검토 기록을 가리키므로, 검토 기록을 함께 저장하지 않으면 없는 기록을 가리켜 사후 lint가 깨진다 + 사후 `lint_store` 1회.
  - `ingest()` 경유로 두지 않는다 — `ingest.py:26-32` 후퇴 가드가 reviewed↔candidate 흐름을 따로 다루고, 사용 시점 promote는 단건 승격이라 ingest의 묶음 검증이 불필요. `save_object`(store.py:60-63)가 `validate_object`를 부르므로 schema 검증은 유지되고, lint(참조 무결성)는 사후 1회로 보완.
- 단건 위주. 매핑 여러 개 한 번에 확정하면 `scope="mapping_bundle"`.
- **사람 판정 경계**: 사용 시점 promote의 검수자는 사람이므로(§5.3, §6.2 — 모호/충돌 판정은 사람·에이전트 몫), 충돌 상태·미해결 질문·근거 약한 후보도 사람 판단으로 승격을 허용한다. 이는 §8 "모호 안 삼킴"과 충돌하지 않는다 — 그 불변조건은 적재 시 자동 승격(B) 전용이고, 사용 시점 promote(C)는 사람이 판정자다. (그래서 `promote.py`가 candidate 메타데이터를 제거하는 것은 의도된 동작이며, cli promote는 코드 가드로 후보 자격을 막지 않는다.)

### 5.3 흐름

```
질의 → (검수된 답 + 후보 함께, 후보는 "확인 필요" 라벨, 후보 번호는 promotable_candidate_ids)
     → 사용자가 "맞다 / 이게 맞다"
     → cli promote → promote.py 단건 변환 + 검토 기록 → 둘 다 save_object + 사후 lint
     → 다음 질의부터 검수됨으로
```

검수자는 그 자리의 사람(B의 자동 승격과 검수자 값으로 구분 — §6.3).

---

## 6. B — 적재 시 자동 승격 (재설계)

### 6.1 검수됨 자격 = 검증된 근거 + 적대검증 통과 + lint clean

v1의 "코드앵커 필수"를 철회한다(§0 변경 1). 검수됨 자격은:

- **검증된 1차 근거(`evidence_refs`)가 있을 것** — 코드앵커**든** 서버위키**든** 슬랙이든. 코드앵커는 근거의 한 종류이지 필수가 아니다.
- **적대검증 통과** — 에이전트(워크플로우)가 수행. 코드는 못 함.
- **lint clean** — 적재가 이미 확인.

이렇게 하면 서버규칙(서버위키 근거 + 검증)도 정당하게 검수됨이다. 코드앵커 없음은 후보 기준이 아니다.

### 6.2 B와 C를 가르는 것 = 적대검증 (코드 아님)

- **검수됨(B)**: 근거 있음 + 적대검증 통과 + lint clean.
- **후보(C)**: 적대검증 실패 / 소스 충돌 / 근거 부재 / 저신뢰.

**코드가 강제하는 것**: `evidence_refs` 비어있지 않음 + lint clean. (근거 없는 검수됨은 자격 미달.)
**에이전트가 판정하는 것**: 근거 충분성·적대검증 통과·모호/충돌 여부.

이건 design-hub 토대("판정은 영구히 에이전트 몫, 코드·lint는 신호만")와 일관된다. "코드가 강제로 모호를 막는다"는 안전장치는 약해지지만(에이전트 정직성에 의존), 그게 founding 원칙이다. 모호·충돌은 (a) lint 신호 (b) 적대검증 (c) 예외 큐(사람)로 막는다.

### 6.3 자동 승격 흐름

- `ingest.py`는 객체 status를 그대로 저장하고 후퇴(검수됨→후보)만 막는다(L26-32). 즉 검증 통과 객체를 `status:"reviewed"`로 적재하면 검수됨으로 저장된다. 후보→검수됨(올림)은 가드에 안 걸린다.
- 코드가 적재 게이트에서 확인: `evidence_refs` non-empty(schema 또는 ingest) + lint clean(merged lint).
- 적대검증은 워크플로우(에이전트)가 끝낸 뒤, 통과 객체를 검수됨으로 적재.
- 별도 "검증 통과 필드"는 두지 않는다 — 필드를 박는 것도 에이전트라 실제 검증 여부를 코드가 모르고 형식적 표시에 그친다.

### 6.4 코드가 강제할 근거 규칙 (schema)

v1 §5.2(코드앵커 강제)를 **근거 강제**로 일반화한다.
- `schema.py`에 "검수된 DomainMapping·GlossaryTerm은 `evidence_refs`가 비면 안 됨"을 추가(객체 한 개로 판정 가능). **GlossaryTerm을 포함하는 이유**: 현 코퍼스 후보가 전부 candidate GlossaryTerm이고 그중 다수가 근거가 빈 상태라(사용 시점 promote가 실제로 다루는 게 이것), DomainMapping만 강제하면 §6.1(모든 검수됨은 근거 필요)이 주 경로에서 새어버린다. 다른 종류(CodeLocator/TemporalFact 등)는 후보 적재 경로가 현재 없어 이번 범위 밖.
- 코드앵커(`code_locator_ids`) 비강제 유지 — 서버규칙은 코드앵커가 본질적으로 없을 수 있으므로.
- `lint.py` 8a의 깨진 참조 검사는 그대로(보완).

> 미해결: "검증된 근거"의 코드 정의가 `evidence_refs` non-empty면 충분한지(거의 모든 객체가 근거를 가져 게이트가 약함), 아니면 근거 종류·검증 표시까지 봐야 하는지는 plan에서 좁힌다. 핵심은 코드앵커를 유일 필수로 강제하지 않는 것.

---

## 7. 기존 reviewed 근거 점검 (v1 마이그레이션 대체)

v1 §6(코드앵커 없는 검수됨 6개를 후보로 강등)을 **철회**한다 — 서버규칙은 근거+검증 있으면 검수됨 유지.

대신 점검 대상은 좁다.
- **근거(`evidence_refs`) 자체가 빈 검수됨**이 있으면 그것만 점검(근거 없는 검수됨은 §6.4 규칙 위반). store 실측으로 확인.
- **이번 PM 세션 교훈**: 적대 검증 단계에 위키 본문을 안 줘서 NPC 이동 같은 근거 사실이 약화·드롭된 일이 있었다. 코드앵커 없는 기존 검수됨(예: `npc-movement-server-owned`, `event-naming` 등 store 실측 6건)이 **검증된 1차 근거(코드앵커·서버위키·슬랙·기획서 무엇이든) + 적대검증을 통과한 상태인지** 객체별로 점검한다. (실측상 이 6건은 다수가 기획서 근거다 — "서버위키"로 좁혀 적으면 기획서 근거 규칙이 "근거 없음"으로 오분류되니 근거 종류를 좁히지 않는다.) 통과면 검수됨 유지, 근거 자체가 없거나 미검증이면 후보로(이건 강등이 아니라 자격 재확인). **store 실측상 근거가 빈 검수됨은 현재 0건이라, 이 점검은 빈 손이면 그대로 통과로 본다.**
- 이 점검은 코퍼스 데이터 작업이지 코드 변경이 아니다. plan의 B 단계에서 store 실측으로 수행.

> 강등이 필요한 객체가 나오면(근거 없는 검수됨), 그 쓰기는 `ingest()`(후퇴 가드에 막힘)가 아니라 일회성 스크립트가 `BrainStore.save_object`로 status=candidate 직접 기록 + 사후 lint 1회로 한다. 그리고 고아 검토기록 처리(§11) 규칙을 따른다.

---

## 8. 불변조건과 경계

- **라우터 읽기 전용**: `answer()`는 store를 변경하지 않는다. promote는 `cli promote`에서만.
- **후보는 노출만**: 충돌 해소·view 신선도·avoid 보정·scope 추론(§4.2 목록)은 검수 전용 유지. 후보는 답 노출 재료로만 합류.
- **검수됨 자격**: 검증된 근거 + 적대검증 통과 + lint clean. 코드앵커는 근거의 한 종류(유일 필수 아님).
- **자동 승격(B)은 검증 통과한 것만**(모호 안 삼킴). 모호·충돌은 적대검증·lint·예외 큐로. **단 사용 시점 promote(C)는 사람이 판정자라** 모호 후보도 사람 판단으로 승격 가능 — "모호 안 삼킴"은 B(자동) 전용이다.
- **모호 시 사람 질문 유지**: 적재 입구 예외 큐 + 사용 시점 promote 둘 다. B 구현이 이 둘을 제거하지 않는다.
- **신뢰 라벨 모델 불변**: `status.py` 손대지 않음.

---

## 9. 구현 단계 (plan 분할 가이드)

한 spec, 구현 두 단계. C가 B의 안전망이라 C 먼저.

### 단계 0 — 회귀 테스트 베이스라인 (선행)
삭제된 7개 회귀 테스트는 복원하지 않고(§0 변경 6), C/promote/B가 손댈 모듈(router.answer·status.py·schema·lint)에 대한 **새 테스트를 재작성**해 베이스라인을 세운 뒤 단계 1 착수. 누락된 삭제 커밋은 이번 작업 커밋에 포함.

### 단계 1 — C (저신뢰 노출) + 사용 시점 promote
1. 라우터가 검수+후보 함께 모으되 검수 우선 정렬. **후보는 노출 수집기에만, 충돌·추론 로직 입력엔 검수 전용 유지**(§4.2).
2. 답 구조에 신뢰 라벨 + 후보 단서(§4.3). 후보만 노출 시 `needs_clarification=True`.
3. 답에 승격 후보 전용 필드 `promotable_candidate_ids`(§5.1).
4. `cli promote` 신설 — save_object 직접 + 사후 lint(§5.2).
- 검증: 후보 노출(silent 제거, **candidate GlossaryTerm 정의 포함**) / 검수 우선 정렬 / 검수 없으면 후보만 + needs_clarification / **후보가 충돌 해소·kept에 안 섞임** / promote 왕복(**검토 기록 동반 저장 + 없는 기록 가리킴 0건**) / 라우터 읽기 전용.

### 단계 2 — B (자동 승격) + 근거 강제 + 기존 reviewed 점검
1. `schema.py`에 검수된 DomainMapping·GlossaryTerm `evidence_refs` non-empty 강제(§6.4). 코드앵커는 비강제.
2. 자동 승격 흐름 + ReviewRecord 검수자 표시(§6.3).
3. 기존 검수됨 근거 점검(§7) — store 실측, 근거 없는 것만 후보로.
- 검증: 근거 없는 검수된 DomainMapping 적재 거부 / 근거 있으면(코드앵커 없어도) 통과 / 서버규칙 검수됨 유지 / 후보→검수됨 승격 적재.

---

## 10. 테스트 전략

brain 테스트는 `scripts/bb2_brain/tests`의 unittest. 삭제된 7개는 복원 안 하고 새로 작성(§0 변경 6). 현 디스크 베이스라인은 29 passed(메모리의 156 아님).

- **C 노출**: 검수+후보 함께 / 검수 우선 정렬 / **검수 매핑 없을 때 candidate GlossaryTerm 정의 노출 + `needs_clarification=True`** / 검수 없으면 후보만 / 무관 후보 노이즈 배제 / **후보가 `_resolve_current_conflicts`·`kept`·`_stale_view_warnings` 입력에 안 들어감**.
- **promote 루프**: `cli promote` 왕복(질의→promote→재질의 검수됨). 승격 객체 + 검토 기록 둘 다 save_object + 사후 lint(없는 기록 가리킴 0건).
- **B 자동 승격**: 근거 빈 검수된 DomainMapping·GlossaryTerm 적재 거부(합성 객체로 검증) / 근거 있으면(코드앵커 유무 무관) 통과 / 기획서·위키 등 근거 가진 서버규칙 검수됨 유지 / 후보→검수됨 승격.
- **기존 reviewed 점검**: 근거 없는 검수됨만 후보로, 서버규칙(근거 있음)은 유지(§7).
- **읽기 전용 회귀**: `answer()` 전후 store 불변.
- **신뢰 라벨**: status.py 동작(새 테스트로).

---

## 11. 미해결·후속

- **"검증된 근거"의 코드 정의**(§6.4): `evidence_refs` non-empty로 충분한지 / 근거 종류·검증 표시까지 볼지 — **plan 단계2의 선결 결정**으로 매듭. 현 코퍼스에서 이 게이트가 거르는 객체는 0건이라, 게이트는 B/C 분류기가 아니라 근거가 통째로 빈 적재만 막는 회귀 바닥이다(단계2 테스트는 합성 객체로 검증).
- **고아 검토기록 lint (발견 3)**: 후보로 내린 매핑이 'approved' 검토 기록(ReviewRecord)을 계속 가리키면 출처가 어긋나는데 현재 lint가 못 잡는다. 점검(§7)에서 후보로 내릴 때 세 가지(status=candidate / `review_record_id`·`review_state` 제거 / 번들 검토 기록 `target_object_ids`에서 제외)를 한 번에 수행하고 사후 lint 1회. 단건 검토 기록(예: event-naming)이면 그 전용 기록이 고아가 되므로 함께 삭제 또는 superseded 처리. "candidate가 approved 검토 기록을 가리키면 lint problem" 검사 추가는 후속으로. (단 §7 강등 대상이 현재 0건이라 이 경로는 당장 발동하지 않는다.)
- **답 구조 후보 표기 형식**: sections 라벨 vs 전용 필드 — plan에서 확정(단 승격 후보 번호는 `candidate_object_ids`와 분리된 전용 필드).
- **자동 승격 적재 방법**: reviewed로 직접 적재 vs candidate 후 자동 promote — plan에서.
- **사용 시점 "수정"(supersede) 경로**: "틀리다, 이게 맞다"는 기존 supersede 흐름(judgment.md) 재사용, 별도 정밀화는 후속. 이번엔 "맞다→승격"만.
- **design-hub 갱신**: §8(검수 자격을 "검증된 근거+적대검증"으로)·§227(서버규칙 분류) 보강 — 이 spec 확정 후.
- **빌드 3 (스킬 문구 재서술)**: 코드 확정 후, 사용자 승인 후.
