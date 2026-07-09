# project-brain 공유 자료

## Meta
- **Topic**: project-brain이 무엇이고, 왜 만들었고, 현재 어떻게 쓰는지 공유
- **Target Audience**: project-brain을 같이 쓰거나 이해해야 하는 내부 협업자
- **Tone/Mood**: 가볍지만 정확한 내부 공유. 과장 없이 현재 동작과 운영 흐름 중심
- **Slide Count**: 11 slides
- **Aspect Ratio**: 16:9
- **style**: ppt-warm-minimal-diagram-deck
- **Primary Export Target**: PDF

## Slide Composition

### Slide 1 - Cover
- **Type**: Cover
- **Title**: project-brain
- **Subtitle**: 프로젝트 기억을 구조화하고 다시 꺼내 쓰는 엔진
- **Visual Note**: 따뜻한 배경 위에 얇은 라인으로 "raw -> objects -> search -> answer" 흐름을 작게 암시

### Slide 2 - 왜 필요한가
- **Type**: Problem
- **Key Message**: 프로젝트 지식은 코드, 기획서, 대화, PR, 결정 기록에 흩어지고 사람은 쉽게 잊는다.
- **Details**:
  - 새 세션마다 같은 배경 설명을 반복한다.
  - 문서가 있어도 질문 시점에 필요한 조각만 꺼내기 어렵다.
  - 잘못 기억한 답보다 "기록에 없다"는 답이 더 안전할 때가 있다.
- **Visual Note**: 흩어진 노드들이 하나의 얇은 라인 흐름으로 모이는 다이어그램

### Slide 3 - 한 줄 정체성
- **Type**: Core Concept
- **Key Message**: project-brain은 에이전트가 쓰는 프로젝트 도메인 지식 엔진이다.
- **Details**:
  - 사람이 CLI를 직접 쓰는 제품이 아니라, 에이전트가 질문에 맞춰 호출하는 도구다.
  - 지식은 raw 문서와 검수 상태가 붙은 구조화 객체로 나뉜다.
  - 답변은 근거, 검수 상태, 없으면 없음 원칙을 따라야 한다.
- **Visual Note**: 사용자 -> 에이전트 -> project-brain -> 근거 있는 답변의 4단 흐름

### Slide 4 - 저장 모델
- **Type**: Architecture Diagram
- **Key Message**: 엔진과 데이터는 분리된다.
- **Details**:
  - 이 저장소는 엔진 코드와 합성 테스트를 갖는다.
  - 각 프로젝트 저장소의 `brain/`이 실제 코퍼스와 골든셋을 가진다.
  - 색인은 JSON 원본에서 다시 만들 수 있는 파생물이다.
- **Visual Note**: 왼쪽 엔진, 오른쪽 프로젝트 `brain/`, 아래 `.brain-local/index.db` 캐시 구조

### Slide 5 - 엔진 설계
- **Type**: Engine Pipeline
- **Key Message**: 엔진은 원본을 저장하고, 색인을 만들고, 여러 검색 신호를 합쳐 답변 후보를 돌려준다.
- **Details**:
  - 원본은 `brain/` 아래 객체 JSON과 raw 원문이다.
  - `schema.py`와 `store.py`가 공통 필드, 타입별 필수 필드, 저장 위치를 맡는다.
  - `surface.py`가 타입별 검색 텍스트를 만들고, `search_index.py`가 SQLite 색인을 만든다.
  - 검색은 BM25, vector, RRF, 1-hop 그래프 지지, router gate로 이어진다.
  - 코드가 의미 판단을 자동으로 대체하지 않고, 상태 신호와 검증 가능한 구조를 제공한다.
- **Visual Note**: `brain/ JSON/raw -> schema/store -> surface -> BM25/vector index -> recall/router` 파이프라인

### Slide 6 - 왜 타입이 나뉘는가
- **Type**: Object Model
- **Key Message**: 각 노드 타입은 "무엇을 안다"가 아니라 "어떤 역할의 근거인가"를 구분한다.
- **Details**:
  - `EvidenceManifest` / `EvidenceRef`: 원본과 원본 안의 특정 근거 위치.
  - `DomainContext` / `GlossaryTerm`: 도메인 경계와 용어 사전.
  - `DomainMapping`: 기획·도메인 의미가 코드나 결정과 어떻게 이어지는지.
  - `CodeLocator`: 구현 위치를 줄번호가 아니라 파일·심볼·커밋 기준으로 가리키는 책갈피.
  - `DecisionRecord`: 왜 그렇게 정했는지 남기는 결정 기록.
  - `Insight`: 여러 객체를 가로지르는 위험이나 교훈.
  - `ContextProjection`: 다시 쓰기 좋게 조립한 착수 브리핑.
- **Visual Note**: Source / Domain / Mapping / Code / Decision / Insight / Projection 역할 모듈

### Slide 7 - 실제 연결과 저장
- **Type**: Relationship + Storage Flow
- **Key Message**: 노드는 필드에 다른 객체 id를 담아 연결되고, kind별 규칙을 통과해야 저장된다.
- **Details**:
  - `DomainContext`는 여러 `GlossaryTerm`을 묶어 도메인 경계를 만든다.
  - `DomainMapping`은 `context_id`, `glossary_term_ids`, `decision_record_ids`, `code_locator_ids`로 의미·용어·결정·코드를 묶는다.
  - `DecisionRecord`와 `Insight`는 `source_object_ids`로 근거 객체 묶음을 가리킨다.
  - `schema.py`는 모든 객체의 공통 필드와 kind별 필수 필드, enum을 검증한다.
  - `store.py`는 kind에 따라 `objects/domain`, `objects/mappings`, `objects/code`, `objects/decisions` 같은 디렉토리에 저장한다.
- **Visual Note**: 가운데 `DomainMapping`, 주변 `GlossaryTerm`, `CodeLocator`, `DecisionRecord`, `EvidenceRef`, `Insight`가 연결된 그래프 + 아래 저장 경로

### Slide 8 - 불러올 때 어떻게 쓰이나
- **Type**: Recall Flow
- **Key Message**: 검색은 텍스트만 찾지 않고, 타입별 표면과 그래프 연결을 같이 쓴다.
- **Details**:
  - `surface.py`가 kind별로 검색에 넣을 텍스트 표면을 만든다.
  - FTS5 BM25는 토큰 기반 키워드 검색을 담당한다.
  - bge-m3 벡터는 표현이 달라도 의미가 가까운 내용을 찾는다.
  - RRF 융합과 1-hop 그래프 재정렬이 서로 지지하는 결과를 위로 올린다.
  - raw, Insight, projection은 일반 객체와 섞이지 않게 별도 통로로 다룬다.
- **Visual Note**: query -> kind별 surface -> BM25/vector -> graph support -> reviewed/candidate/raw/advisory/projection 통로

### Slide 9 - 운영 흐름
- **Type**: Process Flow
- **Key Message**: 기록은 근거에 따라 검수 상태를 정해 쌓이고, 근거가 확실하면 바로 reviewed로 들어간다.
- **Details**:
  - `build`는 구조화 노트에서 객체 묶음을 결정론적으로 조립한다.
  - `ingest`는 스키마와 무결성을 확인한 뒤 주어진 상태 그대로 저장한다(근거가 서면 reviewed 직접, reviewed→candidate 후퇴만 거부).
  - `promote`는 근거가 약해 candidate로 남은 것을 reviewed로 승격한다.
  - `audit`, `lint`, `graph isolated`, `stale-check`가 코퍼스 건강 상태를 점검한다.
  - `stale-check`와 `mark-checked`는 코드 변경 뒤 낡았을 수 있는 매핑을 드러내고 확인 상태를 갱신한다.
- **Visual Note**: note -> build -> ingest(근거 서면 reviewed) -> promote(candidate만 reviewed로) -> search/show -> audit 루프

### Slide 10 - 스킬로 에이전트가 쓰는 방식
- **Type**: Agent Skill Flow
- **Key Message**: project-brain install은 프로젝트에 스킬 4종을 심고, 에이전트가 언제 조회·적재·점검할지 정한다.
- **Details**:
  - `project-brain install`은 `.project-brain.json`과 `.project-brain-manifest.json`을 만든다.
  - `.agents/skills/<project>-brain-query`는 먼저 `search`/`show`를 보게 한다.
  - `.agents/skills/<project>-brain-ingest`는 완료된 기능을 객체 그래프로 적재하게 한다.
  - `.agents/skills/<project>-brain-session-ingest`는 개발 중 결정이나 세션 지식 갱신을 다룬다.
  - `.agents/skills/<project>-brain-audit`는 lint, isolated, stale-check 점검을 맡는다.
  - manifest가 설치 파일 소유권을 추적해서 사용자 수정 파일을 보존한다.
- **Visual Note**: `install -> config/manifest -> query/ingest/session-ingest/audit skill -> CLI 호출` 흐름

### Slide 11 - 같이 쓰려면
- **Type**: Closing
- **Key Message**: 핵심은 "많이 쌓기"가 아니라, 근거와 검수 상태를 유지하며 다시 쓸 수 있게 쌓는 것이다.
- **Details**:
  - 프로젝트에 설치하고 `brain/`을 git으로 관리한다.
  - 새 지식은 raw와 객체를 함께 남긴다.
  - 근거가 서면 reviewed로 올리고, 근거가 약해 candidate로 남은 것은 방치하지 않는다.
  - 팀 공유 전에는 권한, 검수 기준, 운영 루틴을 정해야 한다.
- **Visual Note**: 작은 운영 루프: capture -> review -> recall -> maintain
