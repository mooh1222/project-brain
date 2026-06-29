---
name: {{PROJECT}}-brain-session-ingest
description: |
  Use when {{PROJECT}} 개발을 진행하면서 brain에 적재하거나(시나리오 가 — 기능 개발
  시작·개발 중 "이거 저장해두자"·저장된 객체 값 갱신), 과거 세션 기록에서 지식을 추출할 때
  (시나리오 다 — "이 세션에서 추출", "과거 세션에서 뽑아줘", "백필", "세션 지식 추출").
  "개발하면서 brain에", "기획서 후보 선점", "이 결정 저장해줘", "세션 백필"처럼 진행 중
  적재·세션 추출이 {{PROJECT}} 맥락에서 나오면 스킬 이름 없이도 이 스킬을 쓴다.
  완료된 기능의 소급 적재는 {{PROJECT}}-brain-ingest 몫이고, 조회(읽기)는 {{PROJECT}}-brain-query 몫이다.
---

# {{PROJECT}} Brain 세션 적재 — (가) 진행 중 개발 + (다) 과거 세션 추출

경계: 추출 판단(무엇을 지식으로 뽑나)은 이 스킬(Claude), 기록·마킹·스캔만 CLI.

## 어느 시나리오인가

| 상황 | 절차 |
|---|---|
| 기능 개발 시작·개발 중 적재·객체 값 갱신 | 아래 "(가) 진행 중 개발 적재" |
| 끝난 세션에서 지식 추출 (지정/주제/일괄) | 아래 "(다) 과거 세션 추출" |
| 이미 저장된 객체와 현실이 다름 | 아래 "갱신 운용 규약" — 양쪽 공통 |

## 공통 불변 규칙

- 적재 후 6단계: `project-brain ingest …` 성공 → `lint`(무결성 — 끊긴 참조 0) → `index rebuild` → `eval --check-ids && eval`(골든셋) → 샘플 `search` → 고립 재점검(`project-brain graph isolated`로 신규/잔여 고립을 나열 — 명백한 건 에이전트가 (a)즉시 연결 (b)의도적 종착점 유지 (c)제거로 처리하고, 애매한 것만 사용자 확인. 정본 절차는 `{{PROJECT}}-brain-ingest/references/ingest-tools.md` "적재 후 확인"). 색인 신선도 가드가 rebuild 누락을 막아주지만, 골든셋 회귀는 절차로만 잡힌다. eval/search 출력은 `2>/dev/null | jq`로 읽는다(stdout=깨끗한 JSON·노이즈는 stderr; eval 통과수=`.summary`의 passed/failed/total, search 적중=`.results`) — `2>&1`로 합쳐 손파싱 금지(키 혼동·잔여줄로 깨짐).
- 적재로 색인 행 수가 변하면 실코퍼스 가드 수치를 **의식적으로 갱신**하고 같은 커밋에 포함한다.
- 파괴 작업(promote·일괄 수정) 전 "커밋 먼저".
- 검수 상태: 사용자 명시 지시 = reviewed(reviewer=user-statement) / 어시스턴트 판단 = candidate. reviewed 객체의 의미 변경은 검토 라운드 없이 금지("갱신 운용 규약" 참고).
- 분류 3종: 팀 지식 → 적재 / 개인 메모리(주어가 사용자·어시스턴트·작업 방식) → 적재 안 함, auto-memory·handoff에 / 기존 kind로 못 담는 교훈·함정 → `raw/sources/insights/backlog.md`에 누적(날짜·출처 세션 uuid·한 줄 요약·핵심 인용. raw 색인 대상이라 추가 후 rebuild까지 한 동작).
- Insight: 여러 객체·구현·결정을 가로지르는 **검증된** 관찰/위험/교훈은 raw backlog가 아니라 Insight kind로 적재한다(candidate 거부·reviewed 직접·사용자 진술 근거. `source_object_ids` 개수는 `insight_type`별 — cross-cutting-risk는 2개 이상, operational-lesson은 1개 이상). 미검증 후보는 여전히 backlog.

---

# (가) 진행 중 개발 적재 — 시간차 흐름 4단계

발동: 기획서 기반 기능 개발 착수, 또는 개발 중 "이거 저장해두자".

1. **후보 선점** (개발 시작): 기획서 분석에서 저장 후보(용어·매핑·결정)를 candidate로 바로
   적재. 코드 앵커 없이 가능(candidate는 evidence 강제 없음). EvidenceRef는 기획서
   (`raw/sources/<context>/` 보관). DomainContext도 이때 신설.
2. **코드 연결** (개발 중): 코드가 생기면 CodeLocator 추가 + 매핑 연결. locator는 경로+심볼
   (verified_at이 조사 시점) — 작업 브랜치 기준으로 달고, 기본 브랜치 머지 시 스냅샷
   갱신(제자리)으로 정정한다. `commit_sha`는 여기서도 기입 의무(심볼을 확인한 그 브랜치
   커밋 — 머지 정정 때 기본 브랜치 sha로 교체). 비우면 변경 감지 기준점이 없다.
3. **갱신** (이미 있는 걸 고칠 때 — 가장 흔한 흐름): **추출(뭐가 바뀜) → `search`로 기존 객체 있는지 찾기 → 아래 "갱신 운용 규약" 분기표로 처리 판정**. ingest는 '저장'만 한다 — '찾기'와 '판정'은 에이전트 몫. '찾기'는 자동 전수조사가 아니라 **자기 수정 범위를 알고 그 단어로 search**하는 것(개발자는 자기가 뭘 고쳤는지 안다). 기존 객체가 없으면(search 0건) 그냥 신설. 점검·개선 수정이면 원인이 있으니 DecisionRecord(decision_type=`improvement`) 연결.
4. **완료 마무리** (기능 완료): reviewed 승격 검토 + history 보강 — 완료 소급({{PROJECT}}-brain-ingest)
   수준으로 닫는다. 기본 브랜치 기준으로 locator 수렴. 중복·병합 판정은 에이전트.

**폐기 경로**: 기능 폐기·기획 취소 시 그 context의 후보 선점 candidate를 일괄
status=`rejected`로 전환(사유 노트). 코드 앵커 없는 candidate가 잔존하면 회상 후보 채널에
실재하지 않는 기능이 계속 떠 오답을 유도한다.

---

# (다) 과거 세션 추출 — 코어 절차 + 입력 3모드

## 입력 3모드 (코어는 동일)

| 모드 | 흐름 |
|---|---|
| 세션 직접 지정 | 사용자가 지목한 세션에 코어 절차 |
| 주제·기능 단위 | `project-brain session list --project {{PROJECT}}`로 후보 발견 → 관련성 판단(요약·grep) → 관련 세션들에 코어 반복 |
| 일괄 백필 | `session list --unprocessed` 순회 → 세션마다 코어. 마킹 덕에 중단·재개 안전 |

## 코어 절차

1. transcript Read — 세션 경로는 `session list` 출력의 path. cwd는 CLI가 payload 기준으로
   판별해 줌(디렉토리명은 정본 아님 — 워크트리 세션 포함).
2. kind별 후보 추출: DecisionRecord·GlossaryTerm·DomainMapping·TemporalFact(값 변경이면
   아래 "갱신 운용 규약"의 3객체 묶음). 기존 kind로 못 담는 교훈·함정 → `raw/sources/insights/backlog.md`
   누적(버리지 않는다). 개인 메모리(주어가 사용자·어시스턴트)는 적재 안 함, 표시만.
3. **검토 라운드** (최대 3): 후보를 표로 일괄 제시 → 사용자 자연어 일괄 응답 → 반영.
   중복 의심은 경고 표시만(자동 제외 금지). **3라운드 소진 후 미합의 후보는 적재하지 않고**
   mark-processed `--note`("미합의 N건")로 남긴다 — 사용자가 결정하지 않은 것은 코퍼스에
   넣지 않는다.
4. ingest → 적재 후 5단계(위 "공통 불변 규칙") → `project-brain session mark-processed <uuid>`.

## 가드

- **과거 진술 주의**: 세션 내용은 "그 시점 사실" — 현재 기본 브랜치 코드와 대조 전에는 reviewed
  금지. 충돌 시 코드 정설 + caveat. 단 코드에 없는 지식(의도·결정)의 사용자 진술 자체는
  reviewer=user-statement로 reviewed 가능.
- **id 안정성**: 추출물 id는 의미 기반 결정론(`kind.context.slug`) — 같은 대상은 재추출에서도
  같은 id(부분 적재 후 재실행이 ingest 멱등과 결합돼 중복을 안 만든다).
- **EvidenceManifest**: source_type=session, locator=`claude-session:<uuid>#<날짜>`,
  redaction_status=**"approved" 명시**(화이트리스트 게이트 — 다른 값은 답이 restricted 처리됨).
  세션 로그 raw는 brain에 저장하지 않는다(참조만).

---

# 갱신 운용 규약 — 이미 저장된 객체와 현실이 다를 때

분기 판단 한 줄: **"과거 시점 질문('전엔 어땠어/왜 바뀌었어')의 답이 되는 변경인가?"**
그렇다 → supersede(매핑)/TemporalFact 묶음(값). 아니다 → 제자리 수정.

| 변경 유형 | 처리 | 예 |
|---|---|---|
| 매핑 의미 변경 (DomainMapping) | supersede: 새 매핑 + `supersedes_mapping_ids` 연결, 옛 매핑 status=`superseded` — lint 8d가 잔존 차단 | 매핑 대상 교체 |
| 값 변경 (수치·enum) | **3객체 묶음**: EventLedgerRecord(원인) + 새 TemporalFact(`derived_from_event_id`=그 event, `supersedes`=옛 fact id). TemporalFact는 derived_from_event_id 필수 + why_changed 회상은 event 파생 fact만 사슬을 탐 — EventLedgerRecord 없이는 적재도 회상도 안 됨 | 버튼 스케일 82%→85% |
| 그 외 kind 의미 변경 (GlossaryTerm 정의 등) | 제자리 수정 + DecisionRecord 연결 (supersede 장치는 매핑·fact 전용 — 용어엔 없음. "왜"는 DecisionRecord가, 과거 표현은 git 이력이 담당) | 용어 정의 변경·개칭 |
| 스냅샷 갱신 (코드 위치·verified_at·오타) | 제자리 수정 + updated_at만 | 함수 이동, 경로·심볼 변경 |
| 원인이 있는 변경 | 위 처리 + DecisionRecord 연결. lint(8c)는 **reviewed 매핑에만** 발화 — candidate 구간은 이 절차가 책임 | 기획 변경 |

## 원자성 의무 (부분쓰기 사고 차단)

supersede 묶음 = **새 객체 + status=superseded로 바꾼 옛 객체 + (값 변경이면) EventLedgerRecord를
한 번들로 `project-brain ingest`**. ingest는 번들 객체만 쓴다 — 옛 객체를 번들에서 빠뜨리면
디스크에 reviewed로 잔존해 옛 정설이 계속 회상된다. 적재 후 index rebuild까지가 한 동작.

## reviewed 객체의 의미 변경

반드시 검토 라운드(사용자 확인)를 거쳐 **reviewed 유지**로 수정한다. 어시스턴트 단독으로는
reviewed 의미 변경 금지(새 candidate 제안만 가능) — ingest의 reviewed→candidate 강등 거부
가드와 정합(강등 시나리오를 만들지 않는다).

## 값 변경 3객체 묶음 견본 (코퍼스에 전례 0건이라 첫 실전용 견본)

버튼 스케일 82%→85% 가정. 한 번들로 `project-brain ingest`(아래 id·context·subject 값은
중립 예시 — 실제 대상 객체에 맞춰 바꿀 것):

```json
[
  {
    "id": "event.<context-slug>.ad-button-scale-20260701",
    "kind": "EventLedgerRecord", "schema_version": "0.1", "status": "candidate",
    "poc_priority": "P2", "truth_role": "event",
    "title": "버튼 스케일 82%→85% 변경",
    "event_type": "spec_revision", "happened_at": "2026-07-01T00:00:00+09:00",
    "summary": "기획 개정으로 버튼 setScale 0.82f→0.85f",
    "related_objects": ["fact.<context-slug>.ad-button-scale-v2"],
    "created_at": "2026-07-01T00:00:00+09:00", "updated_at": "2026-07-01T00:00:00+09:00",
    "tags": ["<context-slug>"], "evidence_refs": []
  },
  {
    "id": "fact.<context-slug>.ad-button-scale-v2",
    "kind": "TemporalFact", "schema_version": "0.1", "status": "candidate",
    "poc_priority": "P2", "truth_role": "fact",
    "title": "버튼 스케일 = 85%",
    "subject": "mapping.<context-slug>.ad-button", "predicate": "scale",
    "value": "0.85", "scope": "context.<context-slug>",
    "valid_from": "2026-07-01T00:00:00+09:00",
    "derived_from_event_id": "event.<context-slug>.ad-button-scale-20260701",
    "confidence": "high",
    "supersedes": "fact.<context-slug>.ad-button-scale-v1",
    "created_at": "2026-07-01T00:00:00+09:00", "updated_at": "2026-07-01T00:00:00+09:00",
    "tags": ["<context-slug>"], "evidence_refs": []
  }
]
```

(옛 fact가 이미 있으면 `supersedes`로 잇고, 옛 fact는 번들에 status=`superseded`로 동봉 —
원자성 의무. 옛 fact가 없으면(첫 기록) supersedes 생략. subject·id는 실제 대상 객체에 맞출 것.)
