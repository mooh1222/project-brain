---
name: {{PROJECT}}-brain-recall
description: |
  Use when {{PROJECT}} 기능·도메인 질문에 답하기 시작할 때 — "~가 뭐야", "어디에
  구현돼 있어", "왜 이렇게 동작해/바뀌었어", "이 값 기준이 뭐야" 같은 기능 의미·기획·코드
  위치·변경 이유 질문, 이슈 분석 착수, 기능 개발 착수, "brain에서 찾아/물어봐".
  grep 등 일반 탐색을 시작하기 전에 Brain 검색(project-brain search)으로 검수된
  도메인 지식을 먼저 회상한다. 적재(brain에 넣기)는 {{PROJECT}}-brain-ingest 몫 —
  이 스킬은 읽기(회상)와 사용 시점 승격만 다룬다.
---

# {{PROJECT}} Brain 회상 — 검색 먼저, 결과만으로, 없으면 없다

Brain은 {{PROJECT}} 프로젝트 지식의 단일 저장소다(검수 상태·근거가 붙은 객체 그래프).
이 절차서는 어시스턴트가 brain을 **쓰는** 쪽 계약이다 — 절차는 얇게, 판단·답변은 검색
결과 위에서만.

## 1. 검색 먼저

도메인 질문을 받으면 일반 탐색(grep 등)보다 먼저:

```bash
project-brain search "<질문>"
```

- 프로젝트 안 어느 디렉토리에서든 실행 가능 — `.project-brain.json` config가
  경로(brain root `{{BRAIN_ROOT}}`·색인 DB)를 해석한다.
- "색인 DB가 없다" 에러면 먼저 재생성 후 재시도(실모델 배치 임베딩이라 수십 초
  걸리는 게 정상):
  ```bash
  project-brain index rebuild
  ```

## 2. 결과만으로 답한다

- 답의 모든 사실에 근거를 표시한다. 매핑 적중은 동반된 `linked.code_locators`
  (path:symbol)로 코드 위치까지 핀포인트.
- **검색 결과에 없는 내용을 brain의 답인 것처럼 섞지 않는다.** 내 일반 지식·이전 세션
  기억으로 보강한 부분은 brain 출처가 아니라고 구분해 말한다.

## 3. 채널 해석

| 응답 필드 | 의미 | 답변 처리 |
|---|---|---|
| `results` | reviewed(검수됨) 적중 | 확신 답. 근거·코드 위치 동반 |
| `candidates` | candidate(미검수) 적중 | **"확인 필요" 라벨 필수** — 확신처럼 말하지 않는다 |
| `raw_excerpts` | 원문 발췌(미검수, 기획서 청크) | 단정 답이 아니라 **발췌 자료**로 취급 — "기획서 원문에 이런 서술이 있다"로 인용. 객체화 안 된 기획 배경·의도 질문은 이 채널이 답 |
| `needs_clarification: true` | 게이트 통과 reviewed 0건 | 아래 4번 — "없다"가 답이거나 질문을 좁힌다 (raw 발췌만 있으면 발췌 인용+"검수된 답 없음" 명시) |

## 4. 없으면 "brain에 없다"를 명시한 뒤 폴백

- 적중이 없거나 빈약하면 **"brain에 없음 — 코드에서 직접 확인"** 한 줄을 박고 일반
  탐색으로 넘어간다.
- 금지는 폴백이 아니라 **"brain에 있는 척"**이다. brain이 답하지 못한 질문을 brain이
  답한 것처럼 포장하지 않는다.
- 질문이 모호해서 못 찾은 것 같으면 사용자에게 좁히기 질문을 먼저 한다.

## 5. 사용 시점 승격 (C 루프)

candidate를 근거로 답했는데 사용자가 "맞다"고 확인하면, 그 자리에서 승격한다:

```bash
project-brain promote --ids <candidate id> \
  --reviewer user-confirmed --reviewed-at <ISO8601>
```

- 회상과 한 흐름이라 이 스킬에 둔다. **일괄 승격(`promote-auto`)은 적재 스킬
  ({{PROJECT}}-brain-ingest) 몫** — 여기서 돌리지 않는다.
- 승격 후 색인 재생성(`project-brain index rebuild`)까지 해야 다음 검색에 status
  변화가 반영된다.

## 6. 이력 질문 가드

"왜 바뀌었어/그때는 어땠어" 질문인데 적중 매핑의 `caveats`에 `history_coverage=complete`가
없으면 "변경 이력 미적재"로 답한다 — 현재 사실(meaning/value/boundary)과 변경 이력은
다른 축이다(적재 스킬과 같은 규칙을 회상 쪽에서도 지킨다).

## 7. scope 자동 추론이 배선돼 있다

질의가 기능명을 단일하게 특정하면(컨텍스트 표면의 내용 토큰이 전부 질의에 포함)
그 컨텍스트로 하드 필터가 자동으로 걸린다. 기능 언급이 없거나 여러 기능을 같이
언급하면 필터 없이 전체 검색(연관도 가중만). 다른 기능 객체가 섞여 보이면 질의에
기능명을 정확히 넣어 재검색하고, 그래도 섞이면 결과의 context_id로 수동 필터해서
답한다.

## Common Mistakes

| 실수 | 바로잡기 |
|---|---|
| 도메인 질문에 바로 일반 탐색부터 | `project-brain search` 먼저. 폴백은 "brain에 없음" 명시 후 |
| candidate 적중을 확신처럼 답함 | "확인 필요" 라벨 필수. 사용자 확인 시 promote |
| 검색 결과에 없는 사실을 brain 답에 섞음 | brain 출처와 일반 지식을 구분해 말한다 |
| reviewed니까 "왜 바뀌었는지"도 답함 | `history_coverage=complete` 없으면 이력 질문 차단 |
| promote 후 바로 재검색 | 색인 재생성(`index rebuild`) 후에야 status 반영 |
