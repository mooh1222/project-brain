---
title: BB2 Brain 추출 가이드 설계 (소급 적재 · 코드 뼈대)
date: 2026-06-04
scope: extraction-guide
status: draft-1 (deep-interview 합의, 실제 적재하며 보강)
related:
  - docs/superpowers/specs/2026-06-04-bb2-brain-universal-ingest-design.md
  - docs/superpowers/specs/2026-06-02-bb2-brain-domain-mapping-lifecycle-design.md
  - docs/superpowers/specs/2026-05-28-bb2-brain-storage-layout-design.md
  - ~/Desktop/vault/wiki/bb2-client/bb2-development-process.md
---

# BB2 Brain 추출 가이드 설계

`universal-ingest` spec이 코드 밖 follow-up으로 미뤄둔 **"raw 소스 → 객체 묶음"
추출 절차**의 설계다. 저장·검증 코드(`ingest`/`promote`/`schema`/`lint`)는 이미
완성·도메인 무관이고, 이 문서는 **에이전트(세션의 LLM)가 무엇을 어떤 객체로 뽑고,
무엇에 연결하고, 무엇을 대체로 볼지** 판단하는 규칙을 정한다. 최종적으로는 스킬로
구현한다(이 문서가 그 스킬의 입력).

2026-06-04 deep-interview 합의 기록. **draft-1** — 1차로 이 골격으로 샐리를 적재해
보고, 디테일은 적재하며 붙인다.

## 1. brain의 위치와 추출의 위상

- **brain = 프로젝트 지식의 단일 저장소.** vault를 프로젝트 지식용으로 대체한다.
  코드에 앵커된 의미 매핑이 brain을 쓸모있게 만드는 핵심이다.
- **추출은 에이전트(LLM)의 일, 코드는 받아서 검증·저장만.** 무엇이 무엇을 대체/
  충돌/보완하는지의 **판정은 의미 판단이라 영구히 에이전트 몫**이다(논리적 맥락이라
  코드 자동 비교로는 멀쩡한 사실을 잘못 닫는다). 코드는 검증·저장(`ingest`)과
  신호(`lint`의 충돌·미반영 감지)만 하고 판정은 안 한다.

| 역할 | 담당 | 내용 |
|---|---|---|
| 판정 (대체/충돌/보완) | 에이전트(LLM) — 영구 | 의미 판단, 코드로 안 넘김 |
| 검증·저장 | 코드 `ingest` | 스키마 + 연결 무결성 검사 후 저장 |
| 신호 | 코드 `lint` | "충돌/미반영 있음" 표시만 |

## 2. 핵심 원칙 (deep-interview 2026-06-04 합의)

1. **저장 대상 무제한.** 코드 연결 여부는 저장 필터가 아니다. 코드에 없는 지식
   (서버 판정 규칙·순수 게임 규칙 등)도 저장하고, 관련 코드가 있으면 연결한다.
2. **무엇을 저장할지 판단 = 사람.** 세션 중 "이거 저장하자"(스킬 발동), 또는
   기획서 분석 때 적재 대상을 리스트업하고 모호한 건 사용자와 대화로 정한 뒤 저장.
   (LLM이 후보를 자동 제안하는 기능은 추가 기능 — §10.)
3. **코드에 붙을 수 있는 건 코드에 연결한다.** `mapping_key`는 논리적 의미,
   `code_locator`는 코드 앵커(심볼 + `commit_sha`, develop 기준). 코드 심볼명은
   키가 아니라 앵커다(rename에 견고하도록).
4. **의미는 한 번에 안 채워도 된다.** 소스가 들어올 때마다 같은 의미 객체에 연결이
   쌓인다. 끊어 적재해도 `ingest`가 멱등 갱신 + 추가 + 연결검증으로 받는다.
5. **추측 금지.** 소스에 있는 것만 적재한다. 휘발/불명 소스는 비워 표시한다.
   서버 위키처럼 최신이 아닐 수 있는 소스는 confidence를 낮춘다.

## 3. 적재 시나리오와 이 문서의 범위

| 시나리오 | 뼈대 | 지금 다루나 |
|---|---|---|
| (가) 진행 중 개발 (세션 도중 적재) | 기획서로 저장 후보 선점 → 코드 생기며 연결 | 아니오 (follow-up) |
| (나) 완료 스펙 소급 적재 | **코드** | **예 — 샐리 카누** |
| (다) 과거 세션 히스토리에서 추출 | 끝난 세션 로그 마이닝 | 아니오 (follow-up) |

> (가) 주의: **"코드가 없다"가 아니다.** 개발 중에는 코드가 생기고 변경된다. 개발
> 시작에 기획서 분석으로 저장 후보를 미리 잡아두고, 작업하며 코드가 생기면 그 후보에
> 연결하는 식이다. (가)와 (다)는 "세션에 어떤 코드를 봤는지 흔적이 남는다"는 점에서
> 이어진다 — 추후 절차를 붙일 때 함께 다룬다.

이 문서는 **(나) 소급 적재**만 다룬다. 샐리는 베타 QA까지 끝나 리얼 QA 중이라
모든 소스(기획서 원문·코드·Jira·슬랙·PR·서버 위키)가 한자리에 다 있다. 이미 일어난
변경(4570 버그수정·4604 개선)도 "시간차 갱신"이 아니라 **완결된 이력으로 한 번에
적재**한다(supersede 체인·`EventLedgerRecord`를 에이전트가 구성해 `ingest`).

## 4. 추출 절차 (코드 뼈대 5단계)

### 4.0 사전: 도메인 컨텍스트 + 소스 매니페스트

- `DomainContext` 1개: `context.sally-canoe` (경계·in/out scope).
- 소스마다 `EvidenceManifest` 1개:
  - 기획서 `spec-v8.md` — `source_type=spec`, **마크다운 원문을 brain raw에 보관**(§8).
  - 서버 위키 3종(event/join/test api) — `source_type=wiki`, **링크만**(locator=URL),
    최신이 아닐 수 있어 connected 객체 confidence 주의.
  - 코드(develop SallyCanoe) — `source_type=code_search`.
  - Jira 이슈(4570·4604 등) — `source_type=jira`.
  - 슬랙 스레드 — `source_type=slack`.
  - 수정 PR — `source_type=pr` 또는 `commit`.

### 4.1 코드 심볼 인벤토리 (뼈대 세우기)

develop 기준 `SallyCanoe/` 11 클래스를 계층별로 나열한다. **그 심볼이 어느 계층이냐가
어느 소스를 봐야 하는지를 알려준다:**

| 계층 | 대표 심볼 | 매칭 소스 |
|---|---|---|
| view (UI·흐름) | `SallyCanoeEventAlertPopup`, `…PopupEnterRaceInfoNode`, `…RaceFinishNoticePopup`, `PopupSallyCanoeResult`, `…RaceFailurePopup`, `…HowToPlayPopup`, `…FloatingButton`, `…MainLayer`, `…RaceAreaNode`, `…RaceLaneNode` | **기획서 기능** |
| model (데이터) | `SallyCanoeEventModel`, `…RaceInfo`, `…RankingModel`, `…EventLevel`, `…EventManager` | **서버 위키 API** |
| presenter (변환) | `SallyCanoePresenter`, `SallyCanoeViewData` | 둘을 잇는 가공 |

**심볼 선정 단위**: 기본 = 클래스. 단 **독립된 규칙/동작을 담은 public 메서드는
별도 매핑으로 승격**(예: `_attachPreviewJoinRewardBalloon` = "최초 레이스 도전 시
아이템 지급", `getTimePerStage(targetStages)` = "스테이지당 시간"). private 헬퍼·
UI 좌표·스프라이트명 같은 단순 구현 디테일은 매핑하지 않는다(필요하면 코드를 직접 읽음).

### 4.2 심볼마다 소스를 붙여 매핑 만들기

심볼 하나를 잡고, 그 심볼이 "무엇이고 어떤 규칙인가"를 매칭 소스에서 찾아
객체를 만들고 그 자리에서 연결한다(§5의 객체 구성). view면 기획서, model이면 위키.

### 4.3 코드에 안 잡힌 규칙 보충 (누락 점검)

기획서 기능 목차(약 28개 섹션)를 체크리스트로 훑어, 코드 뼈대에서 안 잡힌 규칙
(선착순 3위 보상·완주 기준·참가 7명 등 서버·순수 규칙)을 찾는다. 이들도 객체로
저장하되, **관련 코드(값을 받아 표시하는 지점 등)가 있으면 거기에 "클라 경계"로
연결**한다. 코드 흔적이 정말 0인 것만 코드 연결 없이 둔다.

### 4.4 변경 이력 박기 (Jira/슬랙/PR)

4570·4604 같은 결정을 `DecisionRecord`로 만들고 영향받는 매핑/사실에 연결한다.
값이 바뀐 것(예: 규칙 변경)은 §6 판정 규칙대로 supersede 체인 + `EventLedgerRecord`로
완결된 형태로 구성한다.

### 4.5 완전성 점검 후 적재·승격

§7 점검 통과 후 `ingest`로 묶음 저장. 사용자 확인이 끝난 도메인 슬라이스는
`promote`(`mapping_bundle`)로 reviewed 승격.

## 5. 심볼별 객체 구성

### view 클래스 (= 기획서 기능)
- `DomainMapping` — `mapping_key`(논리 의미), `code_locator_ids`(심볼), `meaning`,
  `boundary`, `caveats`, `glossary_term_ids`, `decision_record_ids`, `spec_revision_ids`.
- `GlossaryTerm` — 용어 + 별칭(예: "이벤트 시작 알림 팝업" canonical, "오픈 팝업"은
  QA alias[4570 근거]).
- `TemporalFact` — 규칙·값(예: "재참여 쿨타임 N분"), `derived_from_event_id`로 결정/사건에서 파생.
- `CodeLocator` — 심볼 + path + `commit_sha`(develop).
- `EvidenceRef` — 기획서 슬라이드(`spec_slide`/`spec_section`), 코드(`code_locator`).

### model 클래스 (= 서버 위키)
- `DomainMapping` — `meaning`=서버 데이터 의미, `boundary`=서버 책임 경계
  (예: Join API "NPC 매칭·이동 스케줄은 서버 생성, 클라는 표시"). `code_locator_ids`=model 클래스.
- `TemporalFact` — 서버가 내리는 값/규칙.
- `EvidenceRef` — 위키 섹션(`wiki_section`). confidence 주의.

### 소스 객체 (위 매핑들이 가리키는 근거)
- `SpecDocument` + `SpecRevision`(v8) + `SlideRef`(섹션) — 기획서 구조.
- `SlackThread` — 슬랙 결정.
- `DecisionRecord` — Jira/QA/sanity/개선 결정. `decision_type`(`qa_issue`/`improvement`/
  `sanity_change`/…), `spec_reflected`(yes/no/unknown), `affected_mapping_ids`.
- `EventLedgerRecord` — 규칙이 바뀐 사건(왜·언제).

## 6. 판정 규칙 (대체 / 충돌 / 보완)

에이전트가 판단한다. 코드는 신호만 준다.

- **대체(supersede)**: 같은 `subject`+`predicate`인데 값이 바뀌었고 새 값이 옛 값을
  대신한다고 판단되면 — 옛 객체 `status=superseded` + 새 객체 + `supersedes` 링크 +
  변경 사건 `EventLedgerRecord`. (예: 쿨타임 60→30분)
- **보완(추가)**: 기존 동작에 더해지는 것(예: 4604 "레이스 중 순위영역 터치 시 이동
  추가")은 supersede가 아니라 **새 `DecisionRecord` + 기존 매핑에 연결**.
- **충돌(판단 불가)**: 어느 게 맞는지 확신 안 서면 둘 다 두고, `lint`가
  needs_clarification 신호를 띄운다 → 사용자에게 확인.

## 7. 완전성 점검 (도구가 못 보는 부분, 에이전트가 자가 점검)

`ingest`/`lint`는 "없는 id 참조"만 잡고 "규칙이 빠졌다"는 못 잡으므로 에이전트가 점검:

1. 코드 심볼 인벤토리(11 클래스 + 승격 메서드)가 전부 매핑됐나.
2. 기획서 기능 목차 대비 빠진 규칙이 없나(§4.3).
3. 각 reviewed `DomainMapping`이 `code_locator`를 가졌나(코드 앵커 원칙).
4. 고아가 없나 — 잇는 매핑/결정 없는 용어, 결정 0개인 변경 흔적 등(32객체 실패 패턴).

## 8. raw · 저장 정책

- **기획서**: 마크다운 변환본 원문을 **brain 폴더에 보관**한다.
  → 보관 자리(`brain/raw/` 하위 신규 디렉토리 등)는 `storage-layout` spec과 대조해
  확정한다(현재 `brain/raw/manifests`만 존재). **열린 항목 — §11.**
- **서버 위키·세션**: 링크만(`EvidenceManifest.locator`). 원문 미보관.
- 세션 대화 파일에서 지식을 뽑는 자동화는 별도(§10). 세션 대화 보관 기간 불확실은
  열린 질문(§11).

## 9. 샐리 1차 적재 범위

- `context.sally-canoe` + 11 클래스 매핑 + 승격 메서드 매핑.
- 기획서 누락 규칙 보충(선착순/완주/참가 인원 등).
- 4570(QA 버그)·4604(개선) `DecisionRecord` + 연결.
- 기획서 원문 보관 + 위키/Jira/슬랙/PR 링크.
- candidate로 적재 → 사용자 확인 → bundle promote.

## 10. 범위 밖 (named follow-up)

- 진행 중 개발(세션 도중 적재) 절차 (가) — 기획서로 저장 후보 선점 + 코드 생기며 연결.
- 과거 세션 히스토리에서 지식 추출 (다) — 끝난 대화 로그 마이닝.
- LLM 자동 저장 제안 — 세션 종료 hook + 스킬로 후보 제시.
- update ingest **코드 자동 비교** — 안 만든다(판정은 에이전트). 신호 보강만 가능.
- 검색층(BM25/벡터) — design-hub §7 Phase 3. vault 대체가 완성되려면 결국 필요.

## 11. 열린 질문

- 기획서 원문 brain 보관 자리(`storage-layout` spec과 대조해 디렉토리·객체형 확정).
- 세션 대화 파일 보관 기간(링크 영속성).
- "독립 규칙 메서드 승격" 경계의 구체 기준(적재하며 다듬음).
