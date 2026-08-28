---
status: accepted
decision_date: 2026-08-14
implementation: implemented_issue_50
contract_status: mvp_implemented_2026-08-28
superseded_by: null
---

# 주제별 지식 초안은 정식 코퍼스 밖에서 이어서 다듬는다

여러 세션에 걸쳐 바뀌는 개발 지식을 성급하게 Brain 객체로 확정하지 않으면서도 다음 작업 구간에서 잃지 않기 위해, 소비 프로젝트에 기능·도메인 주제별 지식 초안을 Git 추적·비색인 작업물로 둔다. 개발 전 기획서·문서에서 시작할 수도 있고 작업 중 사용자 대화와 현재 코드에서 시작할 수도 있으며, 모든 작은 작업에 의무화하거나 고정된 크기 문턱을 두지 않는다. 초안은 확인된 사실·가설·충돌·열린 질문·근거 위치를 구분하고, 발견한 표현에는 공통 어휘 기준을 잠정 적용하되 표현을 버리거나 `GlossaryTerm`으로 확정하지 않는다.

기본 위치 제안은 `brain/drafts/<topic-id>.md`다. 초안은 정식 Brain 객체·raw 원문·일반 query 답변 근거·snapshot 입력이 아니며, 관련 작업이나 명시적인 이어가기 요청에서만 찾아 별도의 진행 중 초안으로 읽는다. 첫 버전에는 세션 시작 훅을 두지 않는다.

첫 버전은 생성·발견·읽기·재개·갱신·기본 lint까지만 제공한다. 정식 Brain 객체 변환, close와 종료 경로, backlog·pending 자동 라우팅, append-only history, 별도 receipt, 공통 verification과 migration 연결은 실제 초안 하나를 사용한 뒤 필요가 확인될 때 설계한다.

초안은 사람이 읽는 Markdown으로 두고 `project-brain-draft:v1` marker, H1 제목, `Topic ID`, `Updated`, `범위`, `출처`, `확인된 이해`, `어휘 관찰`, `가설과 충돌`, `열린 질문`을 고정한다. 비어 있는 절은 허용하지만 확인된 내용과 가설을 섞거나 작업 체크리스트·세션 로그를 본문에 넣지 않는다. Matt식 `CONTEXT.md`의 짧고 고정된 구조는 참고하되, 안정된 용어 사전 형식을 변하는 지식 초안에 그대로 복사하지 않는다.

작은 엔진 draft 모듈과 CLI가 `brain/drafts/`의 경로 해석·template 생성·읽기·갱신·lint를 소유한다. 설치되는 model-invoked `<project>-brain-draft` 스킬은 언제 초안을 만들고 어떤 내용을 기록할지를 안내하며 이 인터페이스를 호출한다. session-ingest는 현재 세션과 과거 세션에서 지식 또는 초안 재료를 추출하고, 진행 중이거나 미결인 내용은 brain-draft에 넘기며 충분히 확인된 내용은 ingest의 정식 적재 경로로 넘긴다. session-ingest가 초안의 발견·재개·갱신 수명주기를 중복 소유하지 않는다. 템플릿은 엔진이 생성하고 검사하는 단일 정본으로 두며 스킬 reference에 복사하지 않는다. 첫 스킬은 `SKILL.md` 하나로 시작하고, 실제 사례와 분기가 본문을 흐릴 만큼 늘어날 때에만 별도 content guide를 추가한다.

draft 모듈은 초안의 `topic_id`·제목·범위·갱신 시각 목록을 반환하고, 스킬이 현재 작업과의 의미상 관련성을 판단한다. 명확한 초안 하나는 읽어 재개하고 여러 개가 맞을 수 있으면 본문을 모두 읽지 않은 채 목록을 보여 선택받는다. 맞는 초안이 없을 때는 명시적인 생성 요청이나 여러 작업 구간으로 이어질 필요가 분명한 경우에만 만들며, 모든 초안을 색인하거나 세션 시작마다 읽는 훅은 두지 않는다.

한 초안에는 한 번에 한 writer만 둔다. 읽기는 현재 파일 SHA를 함께 반환하고 갱신은 `expected_sha`가 일치할 때만 같은 디렉터리의 임시 파일을 원자 교체하며, 불일치하면 아무것도 쓰지 않고 최신 내용을 다시 읽어 병합하게 한다. 첫 버전에는 장기 lock·journal·transaction receipt를 추가하지 않는다.

엔진은 초안 파일만 쓰고 Git stage·commit을 수행하지 않는다. 설치 스킬은 소비 프로젝트의 정책과 사용자가 준 권한 안에서만 초안 경로를 명시적으로 커밋한다. BB2의 현재 테스트 브랜치는 path-limited 초안 checkpoint를 허용하지만, 이를 다른 소비 프로젝트의 기본 동작으로 일반화하지 않는다.

lint는 `project-brain-draft:v1` marker 하나, 파일명과 일치하는 ASCII kebab-case `Topic ID`, H1 제목, 유효한 `Updated` 시각, 필수 H2 절의 단일성과 순서, UTF-8 일반 파일, drafts 루트 안의 실제 경로만 검사한다. 비어 있는 절과 H3 이하의 세부 구분은 허용하고, 본문 내용의 사실성이나 어휘 잠정 판단은 기계적으로 판정하지 않는다.

첫 실사용은 BB2의 `sally-canoe-glossary-audit`다. 초기 초안은 `manifest.sally-canoe.spec-v8`, `manifest.sally-canoe.wiki-event-api`, `manifest.sally-canoe.wiki-join-api`를 source packet으로 삼고 코드는 이후 의미·구현 대조 단계에서 추가한다. 기획서 원문은 로컬 raw를 사용하고, 서버 위키는 live 원문에 접근할 수 있으면 그것을 우선한다. 접근할 수 없으면 기존 reviewed EvidenceRef 발췌만 사용했다는 한계를 초안에 남기며 전체 위키를 확인했다고 표현하지 않는다.

파일럿은 실제 BB2에 초안을 만들고, 다른 새 세션이 과거 대화 전체 없이 발견·설명·갱신하며, 정상 expected-SHA 갱신과 stale-SHA 무변경 거부를 확인해야 한다. 같은 초안이 BrainStore·raw 검색·index·일반 query·snapshot에 들어가지 않고 사용자가 실제 재개에 도움이 됐다고 판단해야 성공이다. 한 세션 안의 명령 통과만으로 여러 세션 사용성을 검증했다고 보지 않는다.
