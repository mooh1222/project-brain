# 갱신 운용 규약 — 이미 저장된 객체와 현실이 다를 때

분기 판단 한 줄: **"과거 시점 질문('전엔 어땠어/왜 바뀌었어')의 답이 되는 변경인가?"**
그렇다 → supersede(매핑)/TemporalFact 묶음(값). 아니다 → 제자리 수정.

| 변경 유형 | 처리 | 예 |
|---|---|---|
| 매핑 의미 변경 (DomainMapping) | supersede: 새 매핑 + `supersedes_mapping_ids` 연결, 옛 매핑 status=`superseded` — lint 8d가 잔존 차단 | 매핑 대상 교체 |
| 값 변경 (수치·enum) | **3객체 묶음**: EventLedgerRecord(원인) + 새 TemporalFact(`derived_from_event_id`=그 event, `supersedes`=옛 fact id). TemporalFact는 derived_from_event_id 필수 + why_changed 회상은 event 파생 fact만 사슬을 탐 — EventLedgerRecord 없이는 적재도 회상도 안 됨 | 광고 버튼 82%→85% |
| 그 외 kind 의미 변경 (GlossaryTerm 정의 등) | 제자리 수정 + DecisionRecord 연결 (supersede 장치는 매핑·fact 전용 — 용어엔 없음. "왜"는 DecisionRecord가, 과거 표현은 git 이력이 담당) | 용어 정의 변경·개칭 |
| 스냅샷 갱신 (코드 위치·라인·verified_at·오타) | 제자리 수정 + updated_at만 | 함수 이동, 라인 드리프트 |
| 원인이 있는 변경 | 위 처리 + DecisionRecord 연결. lint(8c)는 **reviewed 매핑에만** 발화 — candidate 구간은 이 절차가 책임 | 기획 변경 |

## 원자성 의무 (06-09 부분쓰기 사고 계열 차단)

supersede 묶음 = **새 객체 + status=superseded로 바꾼 옛 객체 + (값 변경이면) EventLedgerRecord를
한 번들로 `project-brain ingest`**. ingest는 번들 객체만 쓴다 — 옛 객체를 번들에서 빠뜨리면
디스크에 reviewed로 잔존해 옛 정설이 계속 회상된다. 적재 후 index rebuild까지가 한 동작.

## reviewed 객체의 의미 변경

반드시 검토 라운드(사용자 확인)를 거쳐 **reviewed 유지**로 수정한다. 어시스턴트 단독으로는
reviewed 의미 변경 금지(새 candidate 제안만 가능) — ingest의 reviewed→candidate 강등 거부
가드와 정합(강등 시나리오를 만들지 않는다).

## 값 변경 3객체 묶음 견본 (스펙 §5 — 코퍼스에 전례 0건이라 첫 실전용 견본)

광고 버튼 82%→85% 가정. 한 번들로 `project-brain ingest`:

```json
[
  {
    "id": "event.stage-clear-token.ad-button-scale-20260701",
    "kind": "EventLedgerRecord", "schema_version": "0.1", "status": "candidate",
    "poc_priority": "P2", "truth_role": "event",
    "title": "광고 버튼 스케일 82%→85% 변경",
    "event_type": "spec_revision", "happened_at": "2026-07-01T00:00:00+09:00",
    "summary": "기획 개정으로 광고 버튼 setScale 0.82f→0.85f",
    "related_objects": ["fact.stage-clear-token.ad-button-scale-v2"],
    "created_at": "2026-07-01T00:00:00+09:00", "updated_at": "2026-07-01T00:00:00+09:00",
    "tags": ["stage-clear-token"], "evidence_refs": []
  },
  {
    "id": "fact.stage-clear-token.ad-button-scale-v2",
    "kind": "TemporalFact", "schema_version": "0.1", "status": "candidate",
    "poc_priority": "P2", "truth_role": "fact",
    "title": "광고 버튼 스케일 = 85%",
    "subject": "mapping.stage-clear-token.ad-button", "predicate": "scale",
    "value": "0.85", "scope": "context.stage-clear-token",
    "valid_from": "2026-07-01T00:00:00+09:00",
    "derived_from_event_id": "event.stage-clear-token.ad-button-scale-20260701",
    "confidence": "high",
    "supersedes": "fact.stage-clear-token.ad-button-scale-v1",
    "created_at": "2026-07-01T00:00:00+09:00", "updated_at": "2026-07-01T00:00:00+09:00",
    "tags": ["stage-clear-token"], "evidence_refs": []
  }
]
```

(옛 fact가 이미 있으면 `supersedes`로 잇고, 옛 fact는 번들에 status=`superseded`로 동봉 —
원자성 의무. 옛 fact가 없으면(첫 기록) supersedes 생략. subject·id는 실제 대상 객체에 맞출 것.)
