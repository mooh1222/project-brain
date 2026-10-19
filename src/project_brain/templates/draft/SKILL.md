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

지식 초안은 정식 적재 전의 이해를 이어가는 Git 추적 작업 공간이다. 정식 Brain 객체나 raw 원문이 아니다.
신규 topic은 JSON v2로 기록하고 기존 Markdown v1은 변환 없이 계속 읽고 갱신한다.
일반 조회에서는 초안(미검수 작업 기억)으로 구분해 참고한다.

## 찾기와 재개

`references/discovery.md`를 먼저 읽고 metadata로 관련 topic을 찾는다.

```bash
project-brain draft list
project-brain draft show <topic-id>
```

- 명확한 topic은 재개한다. 갱신할 초안이 여러 개라 모호하면 목록으로 선택받고,
  선택받기 전에는 본문 전체를 읽지 않는다. 읽기 전용 조회는 discovery 규칙으로 처리한다.
- JSON v2 기본 show는 재개 요약·항목 목차·SHA다. 필요한 항목을
  `project-brain draft show <topic-id> --item <key>`로 읽는다. 전체는 명시적 `--full`이다.
- Markdown v1의 `draft.content`는 전체 본문이며 `draft.sha256`은 현재 SHA다.
  v1에는 `--item`을 쓰지 않는다. 같은 topic의 두 형식이 함께 있으면 충돌을 해결하기 전 쓰지 않는다.

## 만들기

기획서나 현행 문서가 있으면 그 자료를 초기 source packet으로 삼는다.
없으면 사용자 대화와 현재 코드에서 시작한다. 다음 명령은 단일 JSON v2를 만든다.

```bash
project-brain draft create <topic-id> --title "<제목>" --scope "<짧은 범위>" \
  --source "<확인한 자료 식별자나 위치>"
```

ASCII lowercase kebab-case topic ID를 쓴다. `--source`는 반복 가능한 문서 locator이며,
코드·사용자 발화 등의 구조화 근거는 아래 patch로 추가한다. 모든 작은 작업에 초안을 만들지 않는다.
어휘 관찰을 잠정 분류할 때만
`../{{PROJECT}}-brain-ingest/references/glossary-criteria.md`를 먼저 읽는다.
표현·근거는 보존하되 여기서 `GlossaryTerm`이나 candidate로 확정하지 않는다.

## 기록과 갱신

한 초안에는 한 번에 한 writer만 둔다. JSON v2의 항목·근거·patch 구조는
`references/v2-format.md`를 읽는다. 갱신할 항목과 source의 현재 내용을 선택 조회하고 patch를 준비한다.

```bash
project-brain draft update <topic-id> --expected-sha <현재 SHA> --patch-file <patch.json>
```

응답은 새 SHA·갱신 시각·변경 key다. 본문을 다시 모두 읽지 않는다.
현재 코드 관찰을 요청한 source만 엔진이 실제 작업 checkout 기준으로 관찰한다.
관찰 작업 위치가 cwd와 다르면 `--repo-root <작업 checkout>`을 명시한다.

기존 v1은 완전한 Markdown을 임시 파일에서 편집하고 고정 구조·Topic ID를 보존하며
Updated를 실제 갱신 시각으로 바꾼다. 기존 전체 응답도 유지한다.

```bash
project-brain draft update <topic-id> --expected-sha <현재 SHA> --content-file <전체 Markdown>
```

`draft_stale_sha`면 최신 내용을 다시 읽고 변경을 병합한 뒤 새 SHA로 갱신한다.
엔진은 v1/v2 공통의 짧은 배타 구간에서 SHA를 재확인하고 원자 교체한다.
장기 lock·journal·작업 배정은 두지 않는다. 갱신 뒤 검사한다.

```bash
project-brain draft lint <topic-id>
project-brain draft lint
```

## 내용과 완료 경계

- 의미 있는 새 이해·결정이 생겼거나 작업 구간을 끝낼 때 항목과 재개 요약을 갱신한다.
  순수 조회와 모든 도구 호출을 기록하지 않는다. 이해가 바뀌면 같은 key를 replace한다.
- 기능·도메인의 이해·가설·미결은 draft, 개발 개선 제안은 기존 backlog, 여러 대상을 가로지르는
  미검증 합성 분석은 기존 pending에 둔다. 자동 이동·이중 기록을 하지 않는다.
- `{{PROJECT}}-brain-session-ingest`는 현재·과거 세션 재료를 추출해 draft/ingest로 넘긴다.
  개발 중 기본 기록은 draft이며 명시적인 즉시 정식 적재 요청은 기존 ingest로 간다.
- lint·quote 존재·hash 일치는 형식/bytes 점검이다. 의미 검증이나 검수 승인이 아니다.
  정식화는 `{{PROJECT}}-brain-ingest`가 원문 대조·개념 승인·객체 설계·coverage·최종화를 소유한다.
  prepare는 후속 구현이다. 현재는 v1/v2 본문과 원문 위치를 기존 ingest에 넘긴다.
- 기존 v1을 강제 변환하지 않는다. 별도 전환 요청 시 미커밋 원문까지 drafts·BrainStore·raw·색인
  입력 밖의 사용자 승인 위치에 보존한 뒤 단일 활성 파일로 바꾼다. 선커밋을 강제하지 않는다.
- 엔진은 초안 파일만 쓴다. Git stage·commit은 소비 프로젝트 정책과 사용자가 준 권한 안에서
  해당 초안 경로만 수행한다. 기존 사용자 변경과 겹치면 자동 commit·stash로 정리하지 않는다.
