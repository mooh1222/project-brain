# 전반 점검 — 왜곡·누락·에이전트 오해 유발·설계 미흡 (2026-07-02)

evidence_refs 위생 티켓(`2026-07-01-decisionrecord-evidence-refs-hygiene.md`) 해결 중, 그 티켓이
"에이전트의 잘못된 이해가 데이터·분석에 스며든 사례"였다는 점에 착안해 엔진·스키마·스킬·실데이터를
같은 부류(이름·기본값·화이트리스트 함정, 문서-코드 불일치)로 추가 점검했다.

- 상태: **발견 1·2 해결(2026-07-02).** 사용자 승인("A+C 즉시, B는 리뷰 판정 위임") 후 실행.
  처리 내역은 발견 1의 "처리 결과" 절 참조. 발견 3은 계속 보류(필요 생기면 어휘 확장).
- 모든 수치는 2026-07-02 bb2 실데이터 + 엔진 함수 직접 실행으로 검증.

---

## 발견 1 (HIGH) — `redaction_status="none"` 함정: 객체 409개가 'restricted'로 오라벨

### 증상 (엔진 함수 직접 실행으로 확인)

bb2에서 초기 컨텍스트(luckybox-contents·main-map·ball-select·ingame·disturb-bubble)를 건드리는 모든
recall 답의 상태(`answer_status`)가 **최고 심각도 `"restricted"`**로 나온다.

```
decision.luckybox-contents.luckybox-server-sort   _restricted_for=True  -> claim_status='restricted'
mapping.main-map.jellyland-background-layer        _restricted_for=True  -> claim_status='restricted'
answer_status(이 답) = 'restricted'
```

`_restricted_for=True` 반환 객체 전수: **409개** = reviewed 404개(DomainMapping 130·GlossaryTerm 199·
DecisionRecord 7·ReviewRecord 68) + candidate GlossaryTerm 5개.

### 근본 원인 (셋이 겹침)

1. **화이트리스트 게이트 (의도된 설계).** router.py:764 `_restricted_for`는 manifest의 `redaction_status`가
   `(None, "approved")`가 아니면 restricted. `status.py`에서 `restricted`는 심각도 4(최고)이고
   `answer_status`는 max라, 답에 하나만 섞여도 답 전체가 restricted가 된다.
   session-extract.md:32도 "`approved`만 통과, 다른 값은 restricted 처리"라 설계 의도를 명시한다.
2. **기본값이 `"none"` (문자열).** assembly.py:169 `build_manifests`는 노트가 `redaction_status`를 안 주면
   `"none"`으로 채운다(test_assembly.py:125가 이 기본값을 못박음). 그런데 문자열 `"none"`은 화이트리스트에
   없어 → **restricted**. 즉 "명시적으로 approved라 안 한 manifest는 조용히 제한됨."
3. **이름이 의미를 뒤집는다 (footgun).** 사람·에이전트에게 `redaction_status="none"`은 "가릴 것 없음 =
   제한 없음"으로 읽힌다. 엔진은 정반대(제한)로 읽는다.

### 데이터 드리프트 확증

manifest 134개를 source_type × redaction_status로 교차하면, **같은 종류가 approved(다수) vs none(소수)로
갈린다** — 의도가 아니라 잔재라는 증거:

```
code_search  approved:20  none:7      commit  approved:8  none:1
jira         approved:20  none:1      pr      approved:42 none:1
(session·slack·spec·wiki 는 전부 approved)
```

"none" 10개는 전부 초기 적재 컨텍스트다. 후기 컨텍스트는 형제 manifest를 `"approved"`로 채웠는데,
초기 10개만 기본값 `"none"`으로 남았다. 사용자 판단상 앞으로 열람 제한을 쓸 일이 없으므로, 이 10개는
접근 통제 의도가 아니라 **미이관 드리프트**다.

### 영향 범위 (정확히)

- **콘텐츠는 억제되지 않는다.** recall 결과의 `sections`·`source_object_ids`는 claim_status와 독립으로
  조립된다. 그래서 골든셋 eval(내용 회상 여부 검사)은 통과해 왔다 — 그동안 안 잡힌 이유.
- **신뢰 라벨이 틀린다.** 프로젝트가 "단일 진실"로 삼는 신뢰 라벨 모델(status.py)이 플래그십 코퍼스의
  상당 부분에 대해 "restricted"(소비자에겐 "접근 통제됨 = raw 보류"로 읽힘)를 잘못 보고한다.
  → 이것이 "왜곡·에이전트 오해 유발"의 실사례다.
- **lint/checkup이 못 잡는다.** "reviewed 객체가 인용하는 manifest의 redaction_status가 approved/null이
  아님"을 잡는 가드가 없어 조용히 방치됐다.

### 개선안 (미실행 — 승인 필요)

세 층으로 나뉘고, 서로 독립이다:

- **A. bb2 데이터 이관 (가장 직접적, 저위험):** "none" 10개를 `"approved"`로 바꾼다. 형제 124개와
  일치하고 사용자 의도(제한 안 함)에 맞는다. 데이터레포 변경이라 사용자 승인 후 실행.
- **B. 엔진 기본값·의미 정합 (설계 결정 필요):** 둘 중 하나 —
  - (B1) `_restricted_for` 화이트리스트에 `"none"` 추가 → 문자열 "none"이 직관대로 "제한 없음"이 됨.
    가장 작은 변경이지만 신뢰 게이트 의미를 바꾸므로 test_status/의도 재확인 필요.
  - (B2) assembly 기본값을 `"none"` → `"approved"`(또는 `None`)로 바꿔 "미지정 = 제한 없음"으로.
    test_assembly.py:125를 함께 고쳐야 함.
  - ※ B는 신뢰 게이트 의미 변경이라 단독 판단하지 않고 surface(review) 교차검토를 권장.
- **C. 문서 보강 (발견 2와 합침):** 아래 발견 2 참조.
- **D. lint 가드 (선택):** "reviewed 객체가 인용하는 manifest가 approved/null이 아니면 경고." B로 기본값을
  고치면 신규 드리프트는 안 생기므로 필수는 아님.

**권고:** A(데이터 정정) + C(문서) 우선. B는 의미 변경이라 별도 검토. D는 B 후 불필요.

### 처리 결과 (2026-07-02, 적대 검증 4-agent 리뷰 후 실행)

- **A 실행.** bb2 `raw/manifests/` 10개 파일 `"none"`→`"approved"`. 엔진 함수 재실측으로
  `_restricted_for` 대상 409개→**0개** 확인. store는 매 실행 디스크 재로드(store.py `load`)이고
  redaction은 색인·projection·코퍼스 지문에 안 들어가므로(라이브 실험으로 지문 동일 확인)
  index rebuild 불필요 — 즉시 소급 교정.
- **B2(기본값 approved) 기각, B3(기본값 폐지) 채택.** 근거: (1) 06-11 session-ingest spec은
  approved "명시"를 요구 — 기본값이 몰래 찍는 approved는 규약 위반이고 명시 approved와 바이트
  동일해 미래에 제한을 도입하면 구분 불가. (2) 현 실패 모드(과잉 restricted)는 시끄러워서 이번에
  발견됐지만 B2의 실패 모드(자동 approved)는 영원히 무신호. (3) 위 B2 항목의 "None은 필수필드라
  불가"는 사실 오류의 산물 — schema가 필드를 필수 강제하므로 기본값만 빼면 미지정이 "불가"가
  아니라 **적재 시점의 시끄러운 에러**가 된다(원하던 성질). 구현: assembly `build_manifests`가
  미지정 시 키 생략 → build/ingest의 validate가 missing field로 거부.
- **schema enum 추가(B3 보강).** `REDACTION_STATUS_VALUES = raw_local|staged|approved|rejected`
  (spec §6.1)를 source_type과 같은 패턴으로 검증 — `"none"`·오타가 적재 시점에 거부된다.
- **C 실행.** object-model.md 필수 필드 표 아래에 redaction_status 게이트 안내 추가(발견 2 해소).
- **B1·게이트 제거·D 기각.** B1은 spec enum 밖 값 승격이고 A가 소급을 이미 해결. D(lint 가드)는
  B3+enum으로 조용히 새는 경로가 사라져 불필요 — 단 ingest를 안 거치는 수기 JSON은 여전히
  사각(잔여 위험으로 기록만).
- **B3 regression 발견·수정(메인 독립 검증 단계).** surface 실행분은 엔진 단위 테스트(픽스처를
  손으로 approved로 고침)만 통과했을 뿐, 실제 도구 경로를 안 봤다. `assemble_notes.py`(domain 적재
  notes 생성기)는 `sources[]`에 `redaction_status`를 방출하지 않아, B3(기본값 폐지) 하에서
  `build_manifests`가 키를 생략 → `validate_object`가 `missing field 'redaction_status'`로 **domain
  적재를 전부 거부**하는 회귀가 있었다(엔진 함수로 재현 확인). 엔진 pytest는 `testpaths=["tests"]`라
  이 템플릿 스크립트를 수집조차 안 해 surface 검증을 통과했다. **수정**: `assemble_notes.py`가 source마다
  `redaction_status:"approved"`를 명시(도메인 근거는 내부 공유 승인 성격)하도록 고치고, `test_assemble_notes.py`에
  가드 단언 추가. 4종 source(code/commit/jira/pr) 전부 ingest 통과 재현.
- **bb2 전파 실행.** `project-brain install`로 object-model.md + `assemble_notes.py`를 bb2 설치본에
  반영(completeness-checklist는 이전 회차에서 이미 최신). bb2 실측 가드 5개 통과. 엔진 전체 540 +
  템플릿 테스트 11 + installer 14 통과(전부 메인이 직접 재실행).

---

## 발견 2 (MEDIUM) — 문서 갭: 일반 적재 경로에 `redaction_status` 값 가이드가 없다

`redaction_status`의 화이트리스트 함정을 경고하는 문서는 **session-ingest 경로(session-extract.md:32)
하나뿐**이다. 일반 적재가 보는 `object-model.md`는 40행에서 `redaction_status`를 EvidenceManifest 필수
필드로 나열만 하고, 어떤 값이 통과하는지("approved만, 나머지는 restricted") 아무 안내가 없다.

→ 일반 적재 에이전트가 `object-model.md`만 보고 `sources[]`에 `redaction_status`를 안 쓰면 → build 기본값
`"none"` → 조용히 restricted. **발견 1의 드리프트를 낳은 문서 원인이 바로 이 갭이다.**

**개선안(→ 실행됨 2026-07-02):** `object-model.md`의 EvidenceManifest 설명에 게이트 안내 추가 —
필수 명시(기본값 없음), 허용 enum, approved만 화이트리스트 통과. B3 채택에 맞춘 문구
(발견 1 "처리 결과" 참조).

---

## 발견 3 (LOW, 기존 인지) — 결정 근거 어휘가 commit/jira/pr로 좁다

assembly.py:371 `_DECISION_REF_TYPE` 검증이 결정 근거 type을 `commit|jira|pr`만 받는다(object-model.md:258에
문서화됨). spec/wiki 근거로만 정당화되는 결정은 노트의 `decisions[].evidence`로 표현할 수 없다. 이건 조용한
오라벨이 아니라 **적재 시 명시적으로 거부**되므로 함정은 아니고, 이미 인지된 스코프 한계다
(원 티켓 §"2줄 미러가 아닌 이유" 참조). 필요가 실제로 생기면 그때 어휘 확장.

---

## 메타 교훈 (이번 점검의 방법론)

발견 1은 evidence_refs 티켓의 이전 결론("redaction 휴면, 제한값 0개")을 **뒤집었다.** 그 결론은 메인·surface
둘 다 통과시킨 것이었다. 잡힌 계기는 "영구 문서에 박기 전 수치를 다시 실측한다"는 규율 하나였다.
`m.get("redaction_status")`를 그냥 세었더니 `'none': 10`이 나왔고, 그게 엔진 화이트리스트에 걸린다는 걸
코드로 확인하면서 드러났다. → 요약·이전 라운드 결론을 근거로 재사용하지 말 것. 특히 "0개/없음/휴면" 같은
음성 단정은 매번 실측으로만 확정한다.
