# Project Brain 전체 지도

이 문서는 Project Brain을 처음 보는 사람과 에이전트가 현재 구조를 추측하지 않고 찾아가기
위한 유일한 지도 진입점이다. 새 설계 정본을 하나 더 만드는 문서가 아니다. 의도와 경계는
[설계 정본](../design-canonical.md), 현재 동작은 이 지도에서 연결한 코드·테스트·CLI로 되돌아가
확인한다.

## 한눈에 보는 시스템

Project Brain은 검수 상태와 근거가 붙은 프로젝트 지식을 객체로 쌓고, 에이전트가 `query`로
필요한 객체를 회수해 사용자에게 답하도록 돕는 엔진이다. 사람이 JSON 파일을 직접 읽는 방식은
기본 사용법이 아니다. `show`와 `graph export`는 점검과 탐색을 위한 보조 수단이다.

```mermaid
flowchart LR
    User[사용자] --> Agent[에이전트]
    Agent --> CLI[project-brain CLI]
    CLI --> Engine[엔진 레포]
    Engine --> Data[데이터 레포 brain]
    Data --> Objects[검수 객체와 raw]
    Objects --> Index[재생성 가능한 로컬 색인]
    Objects --> Query[정확 객체 경로]
    Index -. fresh일 때 보강 .-> Query
    Query --> Agent
    Agent --> User
```

세부 실행 순서와 저장 경계는 [런타임 지도](runtime-map.md), 객체 필드와 관계는
[데이터 계약](data-contracts.md), 변경할 파일과 검증 범위는 [변경 지도](change-map.md)를 본다.
Markdown 원문과 JSON 객체의 역할을 왜 분리했는지는
[설계 정본의 JSON 객체 선택 근거](../design-canonical.md#왜-json-객체를-정본으로-두는가)를 본다.

## 엔진 레포와 데이터 레포

| 경계 | 이 레포가 갖는 것 | 이 레포가 갖지 않는 것 |
|---|---|---|
| **엔진 레포** `project-brain` | 스키마, 적재·검수, mutation, 색인·검색·라우터, 설치 템플릿, 합성 테스트, 설계·로드맵 | 소비 프로젝트의 실제 지식 객체, 실제 raw 원문, 프로젝트별 골든셋 |
| **데이터 레포** 소비 프로젝트의 `brain/` | 실제 객체와 raw, `brain/checks/`, `brain/eval_scenarios.json`, 적재 이력 | 범용 엔진 구현과 엔진 발전 히스토리 |

경로는 코드에 고정하지 않는다. CLI가 `.project-brain.json`을 읽으며 해석 우선순위는
**명시 인자 > config > ConfigError**다. 여러 checkout이 있을 때는 검증하려는 엔진의
`PYTHONPATH`와 전용 `.venv/bin/python`을 함께 지정한다.

## 무엇이 현재 기준인가

현재 동작은 코드·테스트·CLI가 기준이다. 지도는 그 기준으로 빨리 찾아가게 하는 탐색면이며,
지도와 코드가 어긋나면 조용히 한쪽을 맞추지 말고 문서가 낡았는지 엔진이 설계 경계를 어겼는지
먼저 분리한다.

| 찾는 것 | 우선 확인할 곳 | 역할 |
|---|---|---|
| 현재 실행 동작 | `src/project_brain/`, 직접 테스트, CLI 실행 결과 | 실제 입력·출력과 실패 경계 |
| 전체 구조 | 이 문서와 [런타임 지도](runtime-map.md) | 현재 코드로 가는 길찾기 |
| 객체·쓰기 계약 | [데이터 계약](data-contracts.md)과 설치되는 JSON 예시 | 저장 호환과 신규 쓰기 관문의 차이 |
| 무엇을 왜 만드는가 | [설계 정본](../design-canonical.md) | 정체성, 철학, 안정적인 경계, 미결 |
| 완료·진행·미뤄둔 일 | [ROADMAP](../../ROADMAP.md) | 현재 상태와 발전 히스토리 |
| 설치·일상 사용 | [루트 README](../../README.md) | 설치와 대표 명령 |
| 검색 세부 | [검색 내부 구조](../search-internals.md) | 색인, BM25·벡터·RRF, 게이트 |
| 과거 결정과 당시 증거 | `docs/specs/`, `docs/plans/`, `docs/reports/` | 역사 자료. 현재 코드·테스트와 반드시 대조 |

의도에 대한 우선순위는 최신의 명시적 사용자 결정과 정정, 사용자 발언 원장, 설계 정본,
날짜가 붙은 설계·계획·보고서, 외부 참고 자료 순이다. 날짜 문서 한 장을 현재 구현의 증거로
삼지 않는다.

## 상황별 길찾기

| 하려는 일 | 먼저 읽을 곳 | 이어서 확인할 코드·테스트 |
|---|---|---|
| “이 기능이 지금 어떻게 동작해?” | [런타임 지도의 query와 search](runtime-map.md#query와-search는-다르다) | `intent.py`, `router.py`, `search.py`, `tests/test_router.py`, `tests/test_search.py` |
| 왜 Markdown 지식 문서가 아니라 JSON 객체를 쓰는지 확인 | [설계 정본의 JSON 객체 선택 근거](../design-canonical.md#왜-json-객체를-정본으로-두는가) | [초기 storage layout](../specs/2026-05-28-bb2-brain-storage-layout-design.md), [객체별 JSON 결정](../plans/2026-05-28-bb2-brain-p0-router.md#object-file-encoding-decision), [현재 데이터 계약](data-contracts.md) |
| 객체를 새로 적재하거나 기존 객체를 고치기 | [데이터 계약](data-contracts.md) | JSON 예시, `assembly.py`, `mutation.py`, `tests/test_assembly.py`, `tests/test_mutation.py` |
| CodeLocator를 쓰거나 갱신하기 | 데이터 계약의 CodeLocator 행과 정상·실패 예시 | `code_verify.py`, `mutation.py`, `tests/test_code_verify.py`, `tests/test_mutation.py` |
| 검색·색인·라우터를 바꾸기 | [변경 지도](change-map.md), [검색 내부 구조](../search-internals.md) | 해당 표적 테스트 뒤 소비 데이터 `brain/checks`와 `eval` |
| mutation·migration을 바꾸기 | [런타임 쓰기 경로](runtime-map.md#코퍼스-객체-쓰기)와 [변경 지도](change-map.md) | `mutation.py`, `corpus_io.py`, migration 관련 모듈과 테스트 |
| 설치 스킬이나 runtime을 바꾸기 | [변경 지도의 CLI·config·installer 행](change-map.md#변경별-검증-표) | `tests/test_installer.py`와 설치되는 runtime의 unittest |
| #4·#41~#43의 현재 상태 확인 | [런타임 지도의 실행 흐름 밖 내부 기반](runtime-map.md#현재-실행-흐름-밖의-내부-기반) | `capabilities.py`, `evidence_plan.py`, `evidence_preparation.py`와 직접 테스트. public caller가 없음을 별도로 확인 |
| 어휘 기준·지식 초안 변경 | [ROADMAP의 현재 replacement 범위](../../ROADMAP.md#현재-기준-재설정과-작은-replacement-spec-2026-08-28), [변경 지도](change-map.md) | `draft.py`, draft CLI·설치 스킬과 표적 테스트. 실제 BB2 파일럿은 #51에 대조 |
| 지금 끝난 일과 다음 후보 확인 | [ROADMAP](../../ROADMAP.md) | 연결된 완료 보고서와 현재 checkout 재검증 |

## 현재 경계에서 주의할 점

- `query`는 정확 객체 경로를 먼저 쓰므로 fresh index가 없어도 안전 폴백이 가능하지만,
  `search`는 fresh index가 필요하다.
- 일부 query 경로는 연결된 EvidenceManifest의 `redaction_status`가 `approved`가 아니면 restricted
  신뢰 라벨을 붙인다. 모든 의도와 `search`에 일괄 적용되는 장벽은 아니며, 현재 principal별 접근
  제어를 집행한다는 뜻도 아니다. 정확한 적용·미적용 경계는 런타임 지도를 본다.
- 저장 호환용 schema만 읽고 신규 쓰기 계약을 판단하지 않는다. mutation의 상태 전이,
  CodeLocator repo·SHA·symbol·quote 검증 같은 관문을 함께 봐야 한다.
- 검수 객체 정본은 `objects/**` 한 디렉터리로 한정되지 않는다. `BrainStore.object_path()`가
  kind별로 정하는 `objects/**`, `raw/manifests/**`, `indexes/**`, `views/**` 아래 JSON이 모두
  객체 코퍼스다. 검수 전 원문 정본은 `raw/sources/**`이고, `.brain-local/**`은 다시 만들거나
  다시 계산할 수 있는 로컬 산출물이다.
- `capabilities.py`, `evidence_plan.py`, `evidence_preparation.py`가 main에 있다는 사실만으로 공통
  verification이 공개 ingest·promote에 적용된다고 해석하지 않는다. 현재 production caller는 없다.
- 공통 어휘 기준 reference는 ingest·session-ingest·draft·audit 네 소비 경로가 조건부로 함께
  읽고 query는 읽지 않는다. `brain/drafts/<topic-id>.md`용 모듈·CLI·다섯 번째 설치 스킬은
  #50에서 구현됐고, 실제 BB2 파일럿은 #51의 로컬 전용 커밋과 완료 댓글로 검증됐다. BB2 원격
  push는 하지 않았다.

## 작은 계보 메모

계보는 현재 동작의 권위가 아니다. 아래는 이 레포 안에 이미 남은 명시적 근거만 분류한 것이며,
추가 외부 조사나 코드 기반 직접 적용을 추정하지 않는다.

| 분류 | 근거 | 현재 관계 |
|---|---|---|
| 설계 반영 | Karpathy LLM Wiki | 누적되는 구조화 산물과 raw-first 출발점. [설계 정본의 철학](../design-canonical.md#2-철학--왜-이-형태인가-1차-자료-검증-2026-06-10)에 큰 틀과 세부 구현의 차이를 명시했다. |
| 설계 반영 | Matt Pocock식 `CONTEXT.md` | 공유 도메인 어휘 아이디어가 `DomainContext`·`GlossaryTerm`으로 진화했고, generated `CONTEXT.md`는 버릴 수 있는 projection으로 분리했다. 근거는 [Domain Context v2 설계](../specs/2026-06-02-bb2-brain-domain-context-v2-design.md)다. |
| 초기 참고·부분 반영 | GBrain | Markdown/DB 분리 참고에서 DB·index를 다시 만들 수 있는 projection으로 두는 원칙을 채택했다. GBrain 코드 기반을 직접 적용했다고 주장하지 않는다. 근거는 [초기 storage layout의 source mapping](../specs/2026-05-28-bb2-brain-storage-layout-design.md#2-basis--source-mapping)이다. |
| 설계 반영 | Mnemosyne | `subject`·`predicate`·`value`와 `valid_from`·`valid_until`을 갖는 시간축 트리플이 `TemporalFact`의 직접 원형이 됐다. 근거는 [초기 storage layout의 source mapping](../specs/2026-05-28-bb2-brain-storage-layout-design.md#2-basis--source-mapping)이다. |
| 설계 반영 | Sentra | 사건 이력과 의미 사실을 분리하고, 값이 바뀌면 과거 사실을 지우지 않고 유효 시간을 닫는 방식에 반영됐다. 근거는 [초기 storage layout의 source mapping](../specs/2026-05-28-bb2-brain-storage-layout-design.md#2-basis--source-mapping)이다. |
| 내부 진화 | BB2 | BB2 내부 도구로 출발해 범용 엔진과 소비 데이터 레포를 분리했다. 현재 상태와 이력은 [ROADMAP](../../ROADMAP.md)에 있다. |
