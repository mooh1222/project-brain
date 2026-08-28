---
name: {{PROJECT}}-brain-draft
description: |
  Use when {{PROJECT}} 기능·도메인 주제의 진행 중 이해, 어휘 관찰, 가설·충돌,
  열린 질문을 여러 세션·티켓에 걸쳐 이어갈 지식 초안을 만들거나 찾고, 읽고,
  재개하고, 갱신하고, 형식을 점검할 때. 완료된 지식의 정식 적재는
  {{PROJECT}}-brain-ingest, 현재·과거 세션의 재료 추출은
  {{PROJECT}}-brain-session-ingest가 맡는다.
---

# {{PROJECT}} 주제별 지식 초안

지식 초안은 기능·도메인 주제 하나의 바뀌는 이해를 다음 작업 구간으로 넘기는 Git 추적
Markdown이다. 정식 Brain 객체나 raw 원문, 일반 query의 근거가 아니다. 현재 작업과 관련된
초안만 명시적으로 찾고, 그 내용을 검증된 사실처럼 확대하지 않는다.

## 찾기와 선택

먼저 metadata만 본다.

```bash
project-brain draft list
```

- 현재 작업과 명확히 맞는 초안이 하나면 `project-brain draft show <topic-id>`로 읽어 재개한다.
- 여러 초안이 맞을 수 있으면 목록의 topic ID·제목·범위·갱신 시각만 사용자에게 보여 주고,
  선택받기 전에는 본문 전체를 읽지 않는다.
- 맞는 초안이 없으면 사용자가 생성을 요청했거나 작업이 여러 구간으로 이어질 필요가 분명할
  때만 만든다. 모든 작업에 초안을 의무화하지 않는다.

## 만들기

ASCII lowercase kebab-case topic ID와 선택에 충분한 제목·범위를 정한 뒤 엔진 template으로 만든다.

```bash
project-brain draft create <topic-id> \
  --title "<제목>" \
  --scope "<이번 초안이 다루는 범위>" \
  --source "<확인한 자료 식별자나 위치>"
```

`--source`는 필요한 만큼 반복할 수 있다. 생성 결과의 고정 구조를 다른 template로 복제하거나
직접 만든 파일로 대신하지 않는다.

어휘 관찰을 잠정 분류할 때만
`../{{PROJECT}}-brain-ingest/references/glossary-criteria.md`를 먼저 읽는다. 표현과 근거는
보존하되 이 초안에서 `GlossaryTerm`으로 확정하지 않고, 공통 기준 내용을 이 스킬에 복제하지
않는다.

## 읽기와 갱신

```bash
project-brain draft show <topic-id>
```

응답의 `draft.content`가 현재 본문이고 `draft.sha256`이 갱신 전제다. 한 초안에는 한 번에 한
writer만 둔다. 완전한 v1 Markdown을 임시 작업 파일에서 편집하며 엔진이 만든 고정 구조와
Topic ID를 보존하고 `Updated`를 실제 갱신 시각으로 바꾼다.

```bash
project-brain draft update <topic-id> \
  --expected-sha <show가 반환한 SHA> \
  --content-file <편집한 전체 Markdown 파일>
```

`draft_stale_sha`가 나오면 같은 내용을 재시도하지 않는다. 최신 초안을 다시 `show`하고 서로의
변경을 병합한 뒤, 새 SHA로 한 writer가 갱신한다. 엔진은 같은 디렉터리의 임시 파일을 원자
교체하며 장기 lock·journal·transaction receipt를 만들지 않는다.

갱신 뒤 해당 초안을 검사한다. 전체 drafts 영역을 확인해야 할 때는 topic ID를 생략한다.

```bash
project-brain draft lint <topic-id>
project-brain draft lint
```

lint는 형식·UTF-8·실제 경로만 판정한다. 본문의 사실성, 어휘 잠정 판단, 가설의 타당성은
소스와 사람의 검토로 확인한다.

## 내용과 역할 경계

- 확인된 이해, 어휘 관찰, 가설·충돌, 열린 질문을 해당 엔진 절 안에서 분리한다. 작업
  체크리스트나 세션 로그 보관소로 쓰지 않는다.
- `{{PROJECT}}-brain-session-ingest`는 현재·과거 세션에서 재료를 추출한다. 진행 중·미결
  내용은 이 스킬로, 충분히 확인된 지식은 `{{PROJECT}}-brain-ingest`로 넘긴다.
- 정식 객체 변환, close·종료, backlog·pending 자동 라우팅, append-only history와 세션 시작
  hook은 이 수명주기에 추가하지 않는다.
- 엔진은 초안 파일만 쓴다. Git stage·commit은 소비 프로젝트 정책과 사용자가 준 권한 안에서
  해당 초안 경로만 명시적으로 수행한다. 기존 사용자 변경과 겹치면 자동 commit·stash로
  정리하지 않고 겹친 범위를 보고한다.
