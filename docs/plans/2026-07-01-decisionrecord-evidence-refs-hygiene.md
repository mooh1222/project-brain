# DecisionRecord evidence_refs 비대칭 — 위생 티켓 (해결됨)

- 날짜: 2026-07-01 착수 / 2026-07-02 해결
- 상태: **RESOLVED** — 티켓의 규칙 추가 제안은 **폐기**, 대신 문서 보강만 수행.
- 배경: 안전장치 설계 B 검토 중 발견. B는 폐기됨(근거:
  `docs/plans/2026-06-30-ingest-skill-retro-improvements.md`의 "P0 후속" 절).
- 인용한 file:line은 2026-07-02 스냅샷. 이후 편집으로 드리프트할 수 있다.

## 한 줄 결론

티켓의 전제("근거 없이 적재된 reviewed 결정이 있다")가 **틀렸다**. 결정·인사이트의 정본(定本)
근거 필드는 `evidence_refs`가 아니라 `source_object_ids`이고, 이 필드는 실측상 100% 채워져 있었다.
빈 `evidence_refs`는 "근거 없음"이 아니라 "보조 사본이 안 채워짐"일 뿐이다. 따라서 규칙 추가·backfill을
하지 않고, 이 비대칭을 오해하지 않도록 문서만 보강한다.

---

## 1. 티켓 착수 전제 (원래 주장)

reviewed 객체가 근거(`evidence_refs`) 없이 적재되는 걸 막는 규칙이 GlossaryTerm·DomainMapping엔 있는데
DecisionRecord엔 없다. `schema.py`는 reviewed GlossaryTerm(186-187)·DomainMapping(217-218)이
`evidence_refs`가 비면 거부하는데, DecisionRecord 블록(199-205)엔 그 규칙이 없다. bb2 reviewed 결정
38개 중 4개가 `evidence_refs` 빈 채 적재돼 있으니 오버사이트일 것이다 → 규칙 미러 + backfill.

## 2. 실제로 확인된 것 (전제가 틀렸다)

실제 코드·데이터를 열어 확인한 결과:

- **`source_object_ids`가 결정·인사이트의 정본 근거 필드다.** 링크 무결성 검사(lint.py:200-214는
  `source_object_ids`를 봄), 그래프 1-hop·랭킹(search.py:55 — `evidence_refs`는 랭킹/그래프에서 제외,
  표시 전용)이 전부 이 필드를 소비한다. `evidence_refs`는 결정·인사이트에선 보조 사본이다.
- **schema 비대칭은 오버사이트가 아니라 by-design이다.** GlossaryTerm·DomainMapping은 `evidence_refs`가
  근거 원천 그 자체라 non-empty를 강제한다. 결정·인사이트는 근거를 `source_object_ids`로 관리하므로
  같은 규칙을 두지 않는다.
- **bb2 실측(2026-07-02 재검증):** reviewed 결정 38개 중 `evidence_refs` 빈 4개는 전부
  `source_object_ids`가 채워져 있다 — 근거 없는 게 아니다.
- **전체 store 재스캔:** "`source_object_ids`는 찼는데 `evidence_refs` 빈" 객체는 13개다.
  - DecisionRecord reviewed 4 (전부 근거가 EvidenceRef뿐)
  - DecisionRecord candidate 8 (7개 EvidenceRef뿐, 1개 `decision.disturb-mininest.config-key-separation`은
    근거가 CodeLocator 1개뿐 — `evidence_refs`에 넣을 EvidenceRef가 없으니 빈 게 맞음)
  - Insight reviewed 1 (`insight.dev-pipeline.verify-symbol-callers-before-ingest` — 근거가 다른 brain
    객체 여럿[DomainMapping 2·CodeLocator 1·GlossaryTerm 1]을 종합한 것이라 `evidence_refs` 복사는 오히려 틀림)
  - → 통짜 backfill이 아니라 "11개만 복사 가능, 2개는 손대면 위험"인 fiddly 작업이고, 얻는 건 순수 미관.

## 3. `evidence_refs`를 읽는 곳 (read-path)

`source_object_ids`가 정본이지만, `evidence_refs`를 읽는 코드도 있다 — 전 객체 공용 로직이라 결정도 통과한다:

- router.py:360 provenance 섹션 — `evidence_refs`의 EvidenceRef를 근거 표시에 덧붙인다.
- router.py:748 `_raw_available_for` — `evidence_refs`의 manifest raw 가용 여부.
- router.py:758 `_restricted_for` — **접근 제한 게이트.** `evidence_refs`의 manifest `redaction_status`가
  `None`·`"approved"`가 아니면 restricted 판정.

빈 `evidence_refs`면 이 셋은 각각 "근거 표시 0건 / raw 가용(안전측 기본) / 제한 없음"으로 흐른다.
결정에서 빈 `evidence_refs`는 여기서 무해하다. **단** 아래 4절의 별도 발견을 볼 것 — `_restricted_for`는
당초 "휴면"으로 판단됐으나 실제로는 살아있었다(이 결정의 근거를 무효화하진 않지만 정확히 기록해 둔다).

## 4. 최종 결정

1. **티켓의 `evidence_refs` non-empty 규칙 = 폐기.** 빈값만 겨냥해 정작 정본(`source_object_ids`)은 안 보고,
   근거 멀쩡한 결정을 하드 거부하며(candidate 폴백도 없음), 설계 B와 같은 병(빈값 채우면 통과 = 헛도장)이다.
2. **데이터 구조·스키마 = 그대로.** `evidence_refs` 필드 제거·candidate 폴백 신설 안 함
   (제거하면 provenance·raw·restricted 제네릭 리더가 결정을 특수분기해야 해 커플링이 오히려 는다).
3. **lint sync-가드 = 폐기.** 정당한 근거가 없다.
4. **bb2 backfill = 안 함.** 미관뿐이고, MIXED 2개는 손대면 틀리며, 데이터를 안 건드리는 게 안전.
5. **문서만 보강 — 두 청중:**
   - **엔진 개발자:** `schema.py` DecisionRecord 블록에 주석 — 왜 규칙을 안 두는지 + `evidence_refs`를 읽는
     세 곳(router provenance/raw/restricted) 명시. 미래에 "결정에도 규칙 넣자"는 이 티켓의 실수를 하려는
     사람이 딱 이 자리를 열 것이라 거기서 차단.
   - **적재·감사 에이전트:** `object-model.md`의 DecisionRecord 절에 면제 서술 추가(에이전트는 엔진 코드가
     아니라 스킬을 읽으므로) + `completeness-checklist.md` §5에 포인터 한 줄. 전문 이중기재 금지.

## 5. 이 결정에 이르기까지의 오류 기록 (왜곡 방지 — 정직하게)

이 티켓은 여러 라운드에서 **양쪽(메인 에이전트·surface 리뷰어)이 반복해 틀렸다.** 최종안이 옳은 이유만큼
틀렸던 과정을 남겨야 같은 실수를 반복하지 않는다. 미화하지 않고 적는다.

**메인 에이전트(나)의 오류**
1. 초기에 티켓 방향(schema 미러 + lint + backfill)으로 기울었다 — 정본 필드(`source_object_ids`)를 안 보고
   빈값만 좇는, 폐기된 설계 B와 같은 실수.
2. "회상은 `source_object_ids`로 한다"고 과일반화했다. 실제로는 랭킹·그래프·lint만 그렇고, router의
   provenance·`_raw_available_for`·`_restricted_for`는 `evidence_refs`를 읽는다. (surface가 지적, 코드로 확인)
3. 문서 문안에 "build_decisions가 자동 조립 → `evidence_refs` 비어도 정상"이라 썼다 — **거짓.**
   build_decisions는 `evidence_refs`를 오히려 채우고(assembly.py:148 `source_object_ids=evidence_refs=ref_ids`),
   Insight는 만들지도 않는다. 빈 13개는 build 산출물이 아니라 수기 적재분이다. (surface가 지적, 확인)
4. backfill을 "실행"으로 추천했다가 스코프가 4→13(2개는 MIXED로 손대면 위험)로 커진 뒤에야 철회했다.

**surface(리뷰어)의 오류**
1. 라운드1에서 "redaction 미사용"을 `objects/`만 grep해 단정했다 — `raw/manifests/`를 안 봤다.
   내가 manifest 134개를 직접 확인해 정정했다(이 교차검증이 표준 규율의 값을 입증).

**그 정정조차 불완전했다 (가장 중요 — 이번 재검증에서 드러남)**
- 정정 후 "manifest 134개 중 제한값 0개 → `_restricted_for` 휴면"이라 결론냈는데, **이것도 틀렸다.**
  `redaction_status="none"`(문자열) manifest가 10개 있고, 엔진 화이트리스트(`None`·`"approved"`만 통과)는
  문자열 "none"을 제한값으로 읽는다. → `_restricted_for`는 휴면이 아니라 살아있고, 객체 409개(reviewed
  404 + candidate 5)가 restricted로 오라벨된다(엔진 함수 직접 실행해 확인). 상세·개선안은 별도 문서:
  `docs/plans/2026-07-02-broad-review-findings.md`.
- 이 발견은 위 3절의 "빈 `evidence_refs`는 무해"라는 판단의 근거 중 하나("게이트가 휴면이라 안전")를
  무효화한다. **단 최종 결정 자체는 바뀌지 않는다** — 규칙 폐기·backfill 안 함의 진짜 근거는
  "`source_object_ids`가 정본이라 결정은 근거 없는 게 아니다"이지 "게이트가 휴면"이 아니기 때문이다.
  (오히려 빈 `evidence_refs`인 4개 결정은 `_restricted_for`가 False라 오라벨을 피한다.)

**무엇이 이 오류들을 잡았나**
독립 재검증(요약·이전 결론을 믿지 않고 코드·데이터를 매번 직접 열기) + surface 교차검토. 어느 한쪽도
혼자서는 다 못 잡았다. 특히 "0 restricting/휴면"은 나·surface 둘 다 통과시킨 것을, 영구 문서화 직전의
실측 재검증이 잡았다. **교훈: 숫자는 매번 실제로 센다. 이전 라운드의 결론을 근거로 재사용하지 않는다.**
