# BB2 Brain — B+C 검수 모델 설계 (저신뢰 노출 + 자동 승격 + 사용 시점 promote)

- 상태: **superseded by v2** — 개정판 `docs/superpowers/specs/2026-06-05-bb2-brain-bc-review-model-design-v2.md`. 개정 이유: architect/critic 적대 검증(Run `wf_58d3033e-bf2`, 발견 15·거짓양성 0)이 "코드앵커 강제 = 검수됨 필수" 설계 결함을 잡고, 사용자가 "서버규칙은 코드가 클라에 없을 뿐 모호한 정보가 아니다 → 검수됨 자격 있음"으로 결정. 이 1차 문서는 히스토리로 보존(내용 미수정).
- 상태(원본 작성 시점): draft-for-review (2026-06-05)
- 브랜치: `docs/bb2-brain-object-model`
- 설계 근거: [[bb2-brain-design-hub]] §8 (검수 모델 B+C 하이브리드 확정), task `[[bb2-brain]]`, 본 세션 brainstorming
- 선행 코드 확인(develop 아닌 작업 브랜치 현재 파일 기준 — Brain 코드는 게임 코드와 달리 작업 브랜치가 최신):
  - `scripts/bb2_brain/status.py` — `SEVERITY` / `claim_status` / `answer_status`
  - `scripts/bb2_brain/router.py` — `QueryRouter.answer()`(L43~), `_reviewed_by_kind`(L248), 출력 dict(L236-246)
  - `scripts/bb2_brain/promote.py` — `promote(objects, ids, scope, *, bundle_key, reviewer, reviewed_at)`
  - `scripts/bb2_brain/ingest.py` — `ingest(brain_root, objects)`
  - `scripts/bb2_brain/cli.py` — `query` / `ingest` 서브커맨드 (promote 없음)
  - `scripts/bb2_brain/schema.py` — `validate_object`
  - `scripts/bb2_brain/lint.py` — `lint_store`

---

## 0. 배경과 목적

design-hub §8에서 **B+C 하이브리드**를 검수 방식으로 확정했다. 사람의 역할을 "저장된 것 전부 읽기"에서 "예외 판정 + 사용 시점 수정"으로 옮긴다는 결정이다.

- **B (자동 검수됨)**: 코드앵커 있음 + 적대검증 통과 + lint clean이면 사람 손 없이 검수됨(reviewed)으로 올린다.
- **C (저신뢰 노출)**: 코드앵커 없음 / 소스 충돌 / 저신뢰는 후보(candidate)로 두고, 답할 때 "확인 필요" 단서를 달아 노출한다.

design-hub §230이 적은 **현재 구현의 갭**: 라우터가 지금 "이진"이라 검수된 것만 답에 노출하고 후보는 아예 안 보인다. 그래서 후보로 두면 단서 노출이 아니라 **조용히 사라짐(silent)** 이 된다. "B"는 되지만 "C"는 빌드가 없다.

이 spec은 그 갭을 닫는다. C(저신뢰를 단서 달아 노출) + 사용 시점 promote 루프 + B(코드앵커를 기준으로 한 자동 승격)를 한 모델로 정의한다.

### 목적이 아닌 것 (왜 한 spec인가)

B와 C는 한 모델의 두 면이다. C 없이 B만 켜면, 자동 승격에서 탈락한 모호한 것이 후보로 떨어지는데 라우터가 후보를 안 보여줘서 그 지식이 답에서 사라진다. 그래서 세 경계 — 자동 승격(B) / 저신뢰 노출(C) / 모호 시 사람 질문(예외 큐) — 를 한곳에서 정의해야 일관된다.

---

## 1. 범위와 비범위

### 범위
- C: 라우터가 후보를 검수된 것과 함께 노출하도록 확장.
- 사용 시점 promote 루프: 라우터 답에 승격 후보 안내 + `cli promote` 신설.
- B: 적재 시 코드앵커를 기준으로 한 자동 승격 + 검수된 DomainMapping의 코드앵커 강제(schema).
- 마이그레이션: 코드앵커 없는 기존 검수됨을 후보로 강등.

### 비범위
- **빌드 3 (스킬 문구 다시 쓰기)**: design-hub §234의 "bb2-brain-ingest 스킬의 `candidate → 사용자 확인 → promote`를 B+C로 재서술". 코드가 확정된 뒤 맞추는 후속이라 이 spec 밖. 스킬 편집은 사용자 승인 후 별도 진행.
- **의미 검색 / IndexRecord (§7)**: 별개 층, 코퍼스 확대 후.
- **mixed-intent rationale-first (§5)**: 독립 항목.

---

## 2. 신뢰 라벨 모델 (현 상태 — 바꾸지 않음)

`status.py`는 이미 5단계 신뢰 라벨을 표현한다. 이 모델은 **그대로 둔다** — C가 필요로 하는 `candidate` 표현이 이미 있다.

```python
SEVERITY = {"reviewed": 0, "raw-only": 1, "candidate": 2, "raw-unavailable": 3, "restricted": 4}
```

- `claim_status(obj, *, raw_available, restricted)` — 객체 하나의 신뢰 라벨. `restricted`면 restricted, 검수됨이면 (근거 있는데 raw 못 읽으면 raw-unavailable, 아니면 reviewed), 후보면 candidate, 그 외 raw-only.
- `answer_status(statuses)` — 여러 라벨 중 **가장 심각한 것**(SEVERITY 최대)을 답 전체 라벨로 반환.

즉 후보가 답 재료에 섞이면 `answer_status`가 candidate(severity 2)를 답 전체 라벨로 자동 올린다. 신뢰 라벨 틀은 손대지 않고, **라우터가 후보를 재료에 넣느냐**만 바꾸면 된다.

---

## 3. C — 저신뢰 노출

### 3.1 현재 막힌 지점

`router.py`의 모든 의도 분기가 `_reviewed_by_kind(kind)`(L248)로 검수된 것만 답 재료로 모은다.

```python
def _reviewed_by_kind(self, kind):
    return [obj for obj in self.store.by_kind(kind) if obj.get("status") == "reviewed"]
```

후보는 애초에 재료에 안 들어가 답에서 사라진다. `candidate_object_ids`(출력 dict L241)는 답을 뒷받침한 보조 객체 번호일 뿐, 후보를 노출하는 경로가 아니다.

### 3.2 바꿀 것 — 검수 우선 + 후보 함께

라우터가 검수된 것과 후보를 **함께** 모으되, **검수된 것을 우선 정렬**한다. 후보는 숨기지 않고 "확인 필요" 라벨을 달아 노출한다.

- 질문 종류(의도)에 따라 후보를 숨기는 차등은 **두지 않는다**. 모든 의도에 일괄 적용.
- 후보가 항상 보여야 사용 시점 promote 루프(§4)가 작동한다 — 후보가 답에 안 나오면 사용자가 "이거 맞아?" 할 기회 자체가 없어 그 후보는 영원히 후보에 갇힌다.
- 검수된 것과 후보의 구분은 **숨김이 아니라 라벨**로 한다. 오인은 라벨로 막고, 승격 기회는 노출로 살린다.

정렬·매칭 규칙:
- 기존 매칭/scope 필터를 후보에도 동일 적용한다(질문에 걸리는 후보만 노출, 무관한 후보 노이즈 방지).
- 같은 의도 안에서 검수된 것 먼저, 그다음 후보.
- 검수된 게 전혀 없으면 후보만 노출.

### 3.3 답 구조 변경

`answer()` 출력 dict(L236-246)에 다음을 반영한다.

- `sections`의 각 객체 묶음에 신뢰 라벨을 표기(검수됨/후보 구분). 구체 형식은 plan에서 확정하되, 후보가 어느 것인지 호출하는 쪽이 식별 가능해야 한다.
- 후보가 섞이면 `warnings`에 담담한 단서 한 줄(예: "확인 필요한 후보 항목 포함"). "미확정 규칙!" 같은 과한 경고는 쓰지 않는다.
- `status`(답 전체 라벨)는 지금처럼 `answer_status`로 가장 심각한 것을 노출. 후보 섞이면 자연히 candidate로.

---

## 4. 사용 시점 promote 루프

design-hub §224의 "사람의 역할 = 예외 판정 + **사용 시점 수정**"을 실제로 굴리는 고리. 후보를 미리 전부 검수하지 않고, 답하다가 마주칠 때 사람이 그 자리에서 확정한다(§228 "가능하면 필요할 때(lazy)").

### 4.1 라우터는 읽기 전용 유지

라우터는 답만 하고 저장하지 않는다(현재 불변조건). promote를 라우터가 직접 실행하지 않는다.

- 답 dict에 "승격 가능한 후보 번호"를 담는다(기존 `candidate_object_ids` 자리 활용 또는 전용 필드, plan에서 확정).
- 이 번호 + "확인하면 검수됨으로 올릴 수 있다"는 안내가 사용자/에이전트에게 행동 가능한 정보가 된다.

### 4.2 `cli promote` 신설

`cli.py`에는 현재 `query`·`ingest`만 있고 promote 진입점이 없다. 새로 만든다.

- 입력: brain-root, 승격할 후보 번호 목록, 검수자(reviewer), 검수 시각.
- 동작: `promote.py`의 `promote(..., scope="single_object", ...)`로 후보를 검수됨으로 변환 + 검토 기록(ReviewRecord) 생성 → store 저장.
- 단건 위주. 매핑 여러 개를 한 번에 확정하면 `scope="mapping_bundle"` 재사용.

### 4.3 흐름

```
질의 → (검수된 답 + 후보 함께, 후보는 "확인 필요" 라벨)
     → 사용자가 후보 보고 "맞다 / 이게 맞다"
     → cli promote (또는 에이전트가 promote 호출)
     → promote.py 단건 변환 + ReviewRecord
     → store 저장
     → 다음 질의부터 그 항목은 검수됨으로 노출
```

`promote.py`는 이미 candidate 키를 떼고 status를 reviewed로 바꾸며 ReviewRecord를 만든다(현재 코드). 재사용한다. 사용 시점 promote의 검수자는 그 자리에서 확인한 **사람**이다(B의 자동 승격과 검수자가 다름 — §5.4).

---

## 5. B — 적재 시 자동 승격

### 5.1 현재 적재 흐름

`ingest.py`는 객체 status를 **그대로 저장**하고, 후퇴(검수됨→후보 강등)만 막는다.

```
validate_object (per-object) → 후퇴 가드(reviewed→candidate 거부)
   → merged store lint(참조 무결성) → 통과 시 save
```

즉 지금도 `status: "reviewed"`로 적재하면 검수됨으로 저장된다. 후보→검수됨 승격(올리는 방향)은 가드에 안 걸린다. 그래서 "자동 승격"은 완전히 새 장치가 아니라, **검증 통과 객체를 검수됨 status로 적재 + 코드가 자격을 강제**하는 흐름이다.

### 5.2 코드앵커 강제 = B와 C를 가르는 분류기

핵심 장치. **검수된 DomainMapping은 `code_locator_ids`가 비면 안 된다**를 코드로 강제한다.

- 코드앵커 있음 → 검수됨 자격 → 자동 승격(B).
- 코드앵커 없음(서버 규칙·순수 규칙·충돌) → 검수됨 자격 없음 → 후보 → C로 노출 + 사용 시점 promote.

이러면 "모호한 건 사람에게 질문 유지"가 **코드 게이트로 보장**된다. 코드앵커 없는 모호한 것은 자동 승격 문을 구조적으로 못 지나기 때문이다.

#### 강제 위치
- `schema.py`의 `validate_object`에 "kind가 DomainMapping이고 status가 reviewed면 `code_locator_ids` non-empty" 규칙 추가. 객체 한 개로 판정 가능(객체 자체 필드).
- `lint.py` 8a의 기존 깨진 참조(없는 번호 가리킴) 검사는 그대로 둔다(보완 관계).
- `ingest.py`는 schema+lint 통과만 저장하므로, 위 규칙이 적재 게이트로 자동 작동한다(코드 변경 없이 따라옴).

#### 강제 범위 (DomainMapping 한정)
- TemporalFact(현재 규칙 값)·GlossaryTerm(용어 뜻) 등은 코드앵커가 본질이 아니라 근거(evidence_refs)가 핵심이라 이 강제 대상이 아니다.
- 이 항목은 task `[[bb2-brain]]`의 "다음 follow-up — schema에 reviewed DomainMapping code_locator_ids 필수화"와 정확히 같다. 자동 승격이 코드앵커를 신뢰 기반으로 쓰므로 이번에 함께 넣는다.

### 5.3 적대검증은 에이전트(스킬 절차)가 보장

- 코드가 강제하는 것: 코드앵커 있음(schema) + lint clean(ingest의 merged lint).
- 코드가 못 하는 것: "서로 반박하며 검증(적대검증) 통과"인지. 이건 의미 판단이라 코드가 수행/판단할 수 없다 — design-hub의 "판정은 영구히 에이전트 몫"과 같은 선.
- 그래서 자동 승격 = 워크플로우(에이전트)가 적대검증을 끝낸 객체를 검수됨 status로 적재. 코드는 코드앵커+lint를 최종 확인해 자격 없는 것을 거부.
- 별도 "검증 통과 필드"는 두지 않는다. 필드를 둬도 그걸 박는 건 에이전트라 실제 검증 여부를 코드가 모르고, 형식적 표시에 그치기 때문이다.

### 5.4 추적 (ReviewRecord)

자동 승격도 검토 기록을 남겨 "누가/언제/어떻게 검수됐나"를 추적한다.

- 검수자(reviewer)를 사람이 아니라 "적대검증 워크플로우"(또는 워크플로우 식별자)로 표시.
- 사용 시점 promote(§4)의 검수자는 그 자리의 사람. 둘은 검수자 값으로 구분된다.
- 구현 방법: 검증 통과 객체를 reviewed status + 동반 ReviewRecord로 함께 적재하거나, `promote.py`를 워크플로우가 호출(검수자 주입). plan에서 한 방법으로 확정.

---

## 6. 마이그레이션 — 코드앵커 없는 기존 검수됨

코드앵커 강제(§5.2)를 켜면, 지금 코드앵커 없이 검수됨인 것들이 schema 규칙 위반이 된다.

- 대상(design-hub §227 명시): `npc-movement-server-owned`, `error-codes-reward-gate`, `alert-popups-pyn-forced-order`, `how-to-banner-auto-popup-rule`, `how-to-banner-new-banner` (서버 규칙·순수 규칙 5개).
- 처리: 이들을 후보로 강등한다. C(§3)가 후보를 단서 달아 노출하니 답에서 사라지지 않는다 — design-hub §236의 "빌드 1 완료 후 저신뢰군을 후보로 내림"과 같은 순서.
- 강등 후: 사용 시점 promote(§4)로 사람이 "맞다" 확인하면 검수됨으로 다시 올릴 수 있다(서버 규칙이라 코드앵커가 영원히 없어도 사람 검수로 승격 가능 — 예외 큐의 lazy 처리).
- 마이그레이션은 plan의 C 단계 끝(또는 B 단계 시작)에 둔다 — C가 먼저 있어야 강등된 것이 silent가 안 되기 때문.

> 강등 대상 5개는 적재 시점 데이터라 실제 brain store에서 현재 status·code_locator_ids를 재확인한 뒤 강등한다(이 spec의 5개 목록은 design-hub 기록이므로, 구현 시 store 실측으로 검증).

---

## 7. 불변조건과 경계

- **라우터 읽기 전용**: `answer()`는 store를 변경하지 않는다. promote는 별도 진입점(`cli promote`)에서만.
- **자동 승격은 코드앵커 있는 것만**: 코드앵커 없는 것은 자동으로 검수됨이 될 수 없다(모호를 삼키지 않음).
- **모호 시 사람 질문 유지**: 두 곳에서 보장된다 — (1) 적재 입구의 예외 큐(소스 충돌·소스 부재·경계 불명확, bb2-brain-ingest 스킬 절차), (2) 사용 시점 promote(후보를 답하고 사람이 확정). B 구현이 이 둘을 제거하지 않는다.
- **빌드 2번 문구 주의**: design-hub §233 빌드 2가 "스킬 흐름에서 인간 게이트 제거"라 적혔지만, 이는 "명확한 것의 승격 자동화"이지 "예외 큐 제거"가 아니다. plan에 이 경계를 명시한다.
- **신뢰 라벨 모델 불변**: `status.py`의 SEVERITY/claim_status/answer_status는 손대지 않는다.

---

## 8. 구현 단계 (plan 분할 가이드)

한 spec, 구현은 두 단계. C가 B의 안전망이라 C 먼저.

### 단계 1 — C (저신뢰 노출) + 사용 시점 promote
1. 라우터가 검수+후보 함께 모으되 검수 우선 정렬(§3.2). 매칭/scope 필터를 후보에도 적용.
2. 답 구조에 신뢰 라벨 + 후보 단서(§3.3).
3. 답에 승격 가능 후보 번호(§4.1).
4. `cli promote` 신설(§4.2), `promote.py` 재사용.
- 검증: 후보가 답에 노출되는지(silent 제거), 검수 우선 정렬, 검수 없으면 후보만, promote 왕복(질의→promote→재질의 검수됨), 라우터 읽기 전용 회귀.

### 단계 2 — B (자동 승격) + 코드앵커 강제 + 마이그레이션
1. `schema.py`에 검수된 DomainMapping 코드앵커 non-empty 강제(§5.2).
2. 자동 승격 흐름 + ReviewRecord 검수자 표시(§5.3, §5.4).
3. 기존 코드앵커 없는 검수됨 후보 강등(§6) — store 실측 후.
- 검증: 코드앵커 없는 검수된 DomainMapping 적재 거부, 있으면 통과, 후보→검수됨 승격 적재, 마이그레이션 강등 후 C로 노출.

---

## 9. 테스트 전략

brain 테스트는 `scripts/bb2_brain/tests`의 unittest. 각 단계 TDD.

- **C 노출**: 검수+후보 함께 모음 / 검수 우선 정렬 / 검수 없으면 후보만 / 답 신뢰 라벨·후보 단서 / 무관한 후보 노이즈 배제(scope 필터 적용).
- **promote 루프**: `cli promote` 왕복 — 질의 답에서 후보 번호 확보 → promote → 재질의 시 검수됨으로. 단건/묶음.
- **B 자동 승격**: 코드앵커 없는 reviewed DomainMapping 적재 거부(IngestError) / 코드앵커 있으면 통과 / candidate→reviewed 승격 적재(후퇴 가드 무관) / ReviewRecord 검수자 표시.
- **마이그레이션**: 코드앵커 없는 기존 검수됨이 강등되고 C로 노출되는지(silent 아님).
- **읽기 전용 회귀**: `answer()` 호출 전후 store 불변.
- **신뢰 라벨 불변**: status.py 동작 회귀(기존 테스트 유지).

---

## 10. 미해결·후속

- **빌드 3 (스킬 문구 재서술)**: 코드 확정 후. 사용자 승인 후 별도.
- **답 구조의 후보 표기 형식**: `sections` 안 라벨 vs 전용 필드 — plan에서 확정.
- **자동 승격 적재 방법**: reviewed로 직접 적재 vs candidate 후 자동 promote — plan에서 한 방법으로.
- **사용 시점 promote의 "수정"(supersede) 경로**: 사용자가 "틀리다, 이게 맞다" 할 때 — 이번엔 "맞다→승격"만 범위. 수정은 기존 supersede 흐름(judgment.md) 재사용, 별도 정밀화는 후속.
