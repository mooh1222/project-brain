# BB2 Brain — 매핑 보증 용어 자동 승격 설계

- 날짜: 2026-06-08
- 상태: 설계 v2 (1라운드 적대 검토 반영)
- 브랜치: `docs/bb2-brain-object-model`
- 권위 상위 문서: `2026-06-05-bb2-brain-bc-review-model-design-v2.md` (B+C 검수 모델), design-hub §8
- 관련 코드: `scripts/bb2_brain/{promote,cli,router,ingest,schema,objbase,lint}.py`

## 0. 한 줄 요약

reviewed `DomainMapping`이 `glossary_term_ids`로 참조하는 candidate `GlossaryTerm` 중 충돌(conflict) 아닌 것을, **배치 적대검증으로 "용어 정의가 보증 매핑의 검증된 의미 안에 있는지(초과 주장 없는지)" 확인한 뒤**, 짝 매핑의 근거를 물려받아 reviewed로 승격한다. 자동(일괄)과 수동(사용 시점 `cli promote`) 두 경로가 "매핑 근거 물려받기" 부품을 공유한다.

## 1. 배경 — 무엇을 고치나

샐리 카누 적재 결과 코퍼스는 매핑 중심이다: `DomainMapping` 64 reviewed, `GlossaryTerm` 123 (122 candidate + 1 reviewed, 실측). 실측 사실:

- **매핑이 검수 단위다.** reviewed `DomainMapping`은 의미·코드앵커·근거를 다 갖고 `glossary_term_ids`로 용어를 참조한다. 라우터 `_matched_mappings`(router.py:342-360)는 candidate 용어의 표면 텍스트로 매핑을 찾아 **답은 reviewed 매핑에서** 낸다.
- **후보 노출은 의도된 정책이다(고칠 대상 아님).** spec v2 §4.2는 candidate를 "확인 필요" 라벨로 노출하게 했다 — 사용 시점 promote 루프(§5)가 돌려면 후보가 보여야 한다. 이 노출 자체는 옳다.
- **진짜 문제는 보증된 후보가 졸업 경로 없이 갇히는 것이다.** candidate 122개 전부 reviewed 매핑이 참조한다(미참조 0, 실측). 매핑의 검토가 이미 보증했는데도 용어는 candidate로 남아, 어시스턴트가 답할 때마다 불필요한 "확인 필요" 단서가 붙는다. 이걸 졸업시키는 자동 경로가 없다(ingest는 자동 승격을 안 하고 후퇴만 막음, ingest.py:31-32).
- **근거 빈 용어는 수동 승격이 깨진다.** candidate 122개 중 34개는 `evidence_refs`가 빈 배열이다. reviewed `GlossaryTerm`은 `evidence_refs`가 비면 안 되는데(schema.py:180-181), 현 `promote`는 backfill을 안 하고 있는 값만 복사한다(promote.py:43). 빈 용어를 그대로 승격하면 쓰기 전 검증에서 거부된다.
- **scope_hint·TemporalFact는 이 설계 밖이다.** 범위 좁히기(scope_hint)는 `TemporalFact`를 거르는데(router.py:394-398) 코퍼스에 0개라 작동 대상이 없다. 이 설계는 건드리지 않는다.

## 2. 사용 모델 (전제)

브레인은 **어시스턴트(Claude)가 운영하는 도구**다. 사용자는 자연어로 어시스턴트에게 묻고, 어시스턴트가 브레인을 질의하고 `CodeLocator`(파일:줄) 포인터를 따라 실제 코드를 확인해 답을 합성한다. 사용자는 브레인 cli를 직접 쓰지 않는다.

이 모델에서 reviewed/candidate의 의미는 **어시스턴트의 답 확신 수준**이다. reviewed → 단서 없이 분명히 답(기본). candidate → "…로 보입니다, 다만 후보라 실확인 필요" 단서를 달아 답. 이 설계는 매핑이 보증·검증 커버한 용어를 reviewed로 올려, **불필요한 "확인 필요"를 줄인다.**

라우터의 글자 단위 매칭은 사전 수준이며, 진짜 회상은 의미 검색·그래프(§7 IndexRecord, 별도 후속)가 들어와야 완성된다. 이 설계는 그 위에서 돌 데이터 품질을 먼저 올린다.

## 3. 목표와 비목표

목표
- reviewed 매핑이 보증하고 **배치 적대검증으로 커버 확인된** 비-conflict candidate 용어를 reviewed로 승격한다.
- 승격 시 짝 매핑의 근거를 물려받아 B 게이트를 통과시킨다.
- 자동(일괄)과 수동(사용 시점) 두 승격 경로가 backfill 부품을 공유한다.
- 자동 승격에 추적 가능한 검수 기록(어느 매핑이 보증했는지)을 남긴다.

비목표
- conflict 용어 자동 승격 (사람만 — 수동 경로에서 override).
- `scope_hint` 채우기 / `TemporalFact` 적재 (별도 후속).
- 2번류 용어 정의 보강 (수동 콘텐츠 작업).
- 의미 검색·그래프(IndexRecord §7) (별도 후속).
- 매핑 자체의 승격·검수 (이미 reviewed).

## 4. 설계

### 4.1 공유 부품 — 매핑 근거 물려받기 (backfill)

새 순수 함수. 입력: candidate `GlossaryTerm` + store. 동작:

1. store에서 reviewed `DomainMapping` 중 `glossary_term_ids`에 이 용어 id를 포함한 것을 모은다.
2. 그 매핑들의 `evidence_refs`를 합집합(중복 제거)으로 모으되, **`store.has(ref_id)`로 실존하는 것만** 남긴다(깨진 참조 제외 — 적대 검토 반영).
3. 용어의 `evidence_refs`가 **비어 있을 때만** 그 합집합으로 채운다. 이미 있으면 손대지 않는다(최소 변경).

근거: reviewed 용어는 `evidence_refs` non-empty가 강제고(schema.py:180), `promote`는 backfill을 안 하므로(promote.py:43) 승격 전에 채워야 한다. 2026-06-06 `naming-canoe-race` 용어를 같은 방식으로 backfill한 선례가 있다. 이 함수는 자동·수동 경로가 둘 다 승격 직전 호출한다.

### 4.2 승격 자격 — 1단계 선별 (기계적)

candidate `GlossaryTerm`이 자동 승격 후보가 되는 조건(모두 충족):
- `status == "candidate"`
- reviewed `DomainMapping`이 `glossary_term_ids`로 이 용어를 참조함 (1개 이상)
- `candidate.candidate_state != "conflict"`

실측: candidate 122개 중 conflict 7개 제외 → **115개**가 1단계 통과. 미참조 0개. 선별은 승격 **전에** 한다(`promote`가 승격 시 `candidate` 블록을 제거하므로, promote.py:31).

### 4.2b 승격 자격 — 2단계 배치 커버리지 검증 (적대검증, §8 충족)

1단계를 통과한 용어들을, 승격 전에 **적대검증 워크플로우가 한 배치로** 검증한다. 판정 기준 하나: **"이 용어의 정의(definition)가 그 용어를 참조하는 reviewed 매핑의 검증된 의미·근거 안에 들어가는가(매핑이 입증하지 않는 초과 주장이 없는가)?"**

- 통과(커버됨) → 2단계 통과, 승격 대상.
- 불통과(매핑 의미를 초과하는 주장 있음) → 승격 보류, **사람 검토 큐로**(candidate 유지). 건너뛴 사유로 보고한다.

근거: spec v2 §8 "자동 승격(B)은 적대검증 통과한 것만", §6.2 "에이전트가 판정하는 것: 근거 충분성·적대검증 통과". 한 객체(매핑)의 검증이 다른 객체(용어)의 검증을 무조건 대신하지 않으므로(1라운드 적대 검토 A3 지적), 매핑 검증이 용어 정의를 실제로 덮는지를 배치로 확인해 §8을 충족한다. 적대검증은 코드가 아니라 워크플로우(에이전트)가 수행한다(spec v2 §6.3 "적대검증은 워크플로우가 끝낸 뒤 통과 객체를 적재"와 동일 패턴).

비용: 용어별 처음부터 재검증이 아니라, "정의가 매핑 의미를 초과하나"라는 한 가지 판정의 배치 1회라 가볍다.

**책임·순서(spec v2 §6.3 패턴)**: 2단계 판정은 **에이전트 워크플로우의 산출물**이다 — `{term_id, pass|보류, 사유}` 목록(저장 가능한 형태). cli 명령은 이 목록의 pass id를 `--ids`로 받아 **판정 없이 기계적으로 backfill+승격만** 한다. 즉 "판정은 에이전트, 적재는 코드"로 분리한다(코드가 "정의가 매핑 의미 안에 드는가"를 스스로 판정하지 않는다 — 그건 에이전트 몫, design-hub 토대).

### 4.3 자동 승격 — 운영 절차와 명령

자동 승격은 어시스턴트가 운영하는 **2단계 절차**다.
1. **검증 워크플로우**: 1단계 선별(§4.2)로 115개 → 2단계 배치 커버리지 검증(§4.2b) → 통과 용어 id 목록(pass) + 보류 목록(exceed).
2. **cli 명령**(예: `cli promote-auto`): pass 목록을 받아 각 용어에 §4.1 backfill 적용 → `promote(scope="single_object", reviewer="auto:mapping-vouched", reviewed_at=…)` → 쓰기 전 일괄 `validate_object`(원자성) → `save_object` → 사후 `lint_store` 1회 (기존 cli promote의 안전 패턴 cli.py:79-91 재사용).

규칙:
- **용어 dedup**: 한 용어가 여러 reviewed 매핑에 참조돼도(실측 비-conflict 2개: npc-movement-npc, ranking-raceinfo-rpmap) **한 번만** 승격한다. 검수 기록의 `vouched_by_mapping_ids`에 보증 매핑을 **모두** 담는다(§4.5).
- **건너뛴 사유 보고(조용한 누락 금지)**: conflict 제외 N개(+보증 매핑), 커버리지 불통과 보류 M개, 매핑 미참조 0개를 함께 출력한다.
- **멱등**: 1단계가 `status==candidate`만 거르므로 재실행 시 이미 reviewed는 빠진다(재실행 안전).

### 4.4 수동 승격 통합 (기존 cli promote)

기존 `cli promote --ids …`(cli.py:47-95, 사용 시점·사람 판정)는 그대로 두되 세 가지를 추가한다.
- **backfill 공유**: `promote()` 호출 전에 각 대상 용어에 §4.1 backfill 적용 → 근거 빈 용어(레이스 레인 등)가 B 게이트에서 안 깨진다.
- **멱등 가드(적대 검토 반영)**: 대상 id가 이미 `status==reviewed`면 거부/스킵해, 같은 `review.<id>` 기록을 덮어쓰는 사고를 막는다.
- **conflict 해소 기록(적대 검토 A4 반영)**: 수동으로 conflict 용어를 승격할 때(spec v2 §5.2가 사람 판정으로 허용), 어느 소스를 정설로 골랐는지를 검수 기록 extra(예: `conflict_resolution`)에 남긴다. `promote`가 candidate 블록을 제거해도(promote.py:31, 의도된 동작) **해소 근거가 검수 기록에 남아 추적 가능**하다.

수동 경로는 자동과 달리 conflict 용어도 허용한다(사람이 판정자, spec v2 §5.2·§8).

### 4.5 검수 기록 (출처 추적)

자동 승격된 용어마다 검수 기록(ReviewRecord)을 만든다(single_object 경로가 이미 용어별 기록 생성, promote.py:34-44). 자동임을 명시한다.
- `reviewer = "auto:mapping-vouched"` (사람 reviewer와 prefix로 구분 — 충돌 없음)
- `verdict = "approved"`
- **`vouched_by_mapping_ids: list[str]`** — 이 용어를 보증한 reviewed 매핑 id 목록(다중 참조면 복수). `review_record(…, **extra)`가 추가 필드를 merge하므로(objbase.py:40,62) 넣을 수 있다.
- 스키마: ReviewRecord 필수는 `reviewer/reviewed_at/verdict`뿐(schema.py:14)이고 검증이 추가 필드를 막지 않는다. **단 "우발적 허용"에 의존하지 않도록, `vouched_by_mapping_ids`를 ReviewRecord의 정의된 선택 필드로 spec·schema 주석에 명시한다(적대 검토 minor 반영). 스키마 버전 bump은 불필요(필수 아님).**

검수 기록 id는 `review.<term_id>`(promote.py:32)로 용어당 하나 — dedup과 함께라 다중 매핑이어도 기록 1개에 보증 매핑 전부 담긴다.

### 4.6 드리프트 lint (이 설계에서 신규 구현)

`lint.py`에 검사 추가(현재 없음 — 이 작업 범위에 포함): "reviewed 매핑이 `glossary_term_ids`로 참조하는데 아직 `status==candidate`이고 `candidate_state != conflict`인 용어"를 비차단 경고로 보고. 적재 후 자동 승격 절차를 안 돌렸을 때 이 lint가 잡아 §4.3 "한 번 더 돌려야 함"을 보완한다. 자동 승격(+커버리지 통과분) 후 이 경고는 0이어야 한다(보류된 커버리지 불통과분은 conflict처럼 별도 신호로 구분).

### 4.7 구현 산출물 (신규 코드 — 구현 단계 대상)

이 설계가 새로 만들 코드 단위. **현재 코드에는 없으며 구현 단계(writing-plans)에서 만든다** — 기존 `promote.py`/`cli.py`/`lint.py`에 이게 없는 것은 정상이다.
- `promote.py`(또는 신규 모듈): `backfill(term, store)` 순수 함수(§4.1).
- `cli.py`: `promote-auto` 진입점(§4.3) — pass 목록을 `--ids`로 받아 backfill+promote. 기존 `cli promote`에 멱등 가드 + backfill 호출 + (conflict 시)해소 기록 배선(§4.4).
- `promote.py`: 자동 경로에서 `reviewer="auto:mapping-vouched"` + `vouched_by_mapping_ids` extra 배선(§4.5).
- `lint.py`: 드리프트 검사(§4.6).
- `schema.py`: ReviewRecord `vouched_by_mapping_ids` 선택 필드 주석(§4.5, 강제 아님이라 버전 bump 없음).
- 2단계 배치 커버리지 검증은 코드가 아니라 **적대검증 워크플로우(에이전트)**가 수행, pass 목록을 산출(§4.2b).

## 5. 데이터 흐름

```
적재(ingest, 작성된 대로)
  → [자동 승격 절차]
      1단계 선별(§4.2, 115) → 2단계 배치 커버리지 검증(§4.2b) → pass / 보류
      → cli promote-auto(pass): backfill(§4.1) → promote single_object → 원자적 쓰기 → lint
      → 보고: 승격 N / conflict 제외 7 / 커버리지 보류 M
대화 중 사용자 "이거 승격" → 어시스턴트가 cli promote --ids
  → 멱등 가드 → backfill(§4.1) → (conflict면 해소 기록) → promote → 원자적 쓰기 → lint
lint(상시) → 미승격 보증 용어 경고(§4.6)
```

## 6. 오류 처리·원자성

- 쓰기 전 `to_write` 전체 `validate_object`, 하나라도 실패면 아무것도 안 쓰고 rc=1 (기존 cli.py:79-85 패턴).
- backfill은 `store.has()`로 깨진 근거를 걸러 dangling을 안 만든다(§4.1).
- 멱등: 자동은 candidate-only 선별로, 수동은 reviewed 가드로 재실행/재승격 안전(§4.3·§4.4).
- backfill 후에도 빈 용어(짝 매핑 근거도 빔)는 자동에선 보류·수동에선 명확 오류로 거부, 사유 출력. (실측상 빈 34개 전부 짝 reviewed 매핑에 근거 있어 backfill 소스 100% 존재, 방어적 처리.)

## 7. 테스트

- backfill: 빈 용어가 짝 매핑 evref로 채워짐 / 이미 근거 있으면 불변 / 짝 매핑 없으면 빈 채 / dangling ref는 제외.
- 1단계 선별: conflict 제외, observed·evidence_verified 포함, 매핑 미참조 제외. (실측 115개.)
- 2단계 커버리지: 매핑 의미 안에 든 정의 통과 / 초과 주장 있는 정의 보류.
- 자동 명령: pass 일괄 승격 + 검수기록 + dedup(다중 매핑 1회) + 건너뛴 사유(conflict·보류) 보고 + 멱등(재실행 0건).
- 수동 통합: 근거 빈 용어 backfill 후 승격 성공, 이미 reviewed 거부(멱등), conflict 용어 승격 시 해소 기록 남음.
- 검수기록: `reviewer="auto:mapping-vouched"` + `vouched_by_mapping_ids`(복수 포함) 기록, 스키마 통과.
- 드리프트 lint: 미승격 보증 용어 경고, conflict·이미 reviewed·커버리지 보류는 적절히 구분.
- 회귀: 실코퍼스에 절차 적용 후 lint 0(보류분 제외 경고), 기존 58 테스트 그린.

## 8. 비목표·후속

- conflict 용어: 사람 수동 판정만 (term 1 RK 사례), 해소 기록 남김(§4.4).
- 커버리지 보류 용어: 사람 검토 큐 → 수동 승격 또는 정의 수정 후 재시도.
- scope_hint + TemporalFact 적재: 별도 후속.
- 의미 검색·그래프(IndexRecord §7): 별도 후속, 코퍼스 성장 후.
- 2번류 용어 정의 보강: 수동 콘텐츠 작업.

## 9. 미해결·위험

- backfill "비었을 때만"(최소 변경) 유지. 수동 경로는 사용자가 승격 후 용어 한정 근거를 더 붙일 수 있어, 매핑 근거가 거친 경우를 보완한다. "항상 합집합"은 이미 있는 용어 한정 근거를 매핑 근거로 희석할 수 있어 안 쓴다.
- 검수기록 수: 승격 ~100여 개면 기록도 그만큼. 용어별 추적 가치가 비용을 넘는다고 봄(대안 번들 공유는 추적 약화).
- 2단계 커버리지 검증의 판정 일관성은 적대검증 에이전트 품질에 의존(spec v2 §6.2 founding 원칙 — 판정은 에이전트 몫). 배치 결과는 사람이 보류 목록으로 사후 확인 가능.
