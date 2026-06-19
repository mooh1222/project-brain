---
name: {{PROJECT}}-brain-query
description: |
  Use when {{PROJECT}} 기능·도메인 질문에 답하기 시작할 때 — "~가 뭐야", "어디에
  구현돼 있어", "왜 이렇게 동작해/바뀌었어", "이 값 기준이 뭐야" 같은 기능 의미·기획·코드
  위치·변경 이유 질문, 이슈 분석 착수, 기능 개발 착수, "brain에서 찾아/물어봐".
  grep 등 일반 탐색을 시작하기 전에 Brain 검색(project-brain search)으로 검수된
  도메인 지식을 먼저 조회한다. 적재(brain에 넣기)는 {{PROJECT}}-brain-ingest 몫 —
  이 스킬은 읽기(조회)와 사용 시점 승격만 다룬다.
---

# {{PROJECT}} Brain 조회 — 검색 먼저, 결과만으로, 없으면 없다

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
- **출력 읽기**: `project-brain`은 JSON을 stdout으로 내보내고 진행 로그·HF 경고는 stderr로 보낸다 →
  `project-brain search "<질문>" 2>/dev/null | jq` 로 읽는다(`2>&1`로 합쳐 손파싱하면 키 혼동·잔여줄로 깨짐).
  search 적중 배열 키는 `.results`(candidates·raw_excerpts·projection_reuse는 별도 채널), eval 요약은 `.summary`.

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
| `projection_reuse` | 재사용 후보(미검증, 이전 착수 브리핑) | 단정 답 아님 — **"재사용 후보(미검증)" 라벨 필수**. 개발 착수 시 §8 0단계 입력으로만 쓰고, 확신은 정본 객체(results) 적중으로 확인 |
| `needs_clarification: true` | 게이트 통과 reviewed 0건 | 아래 4번 — "없다"가 답이거나 질문을 좁힌다 (raw 발췌만 있으면 발췌 인용+"검수된 답 없음" 명시) |

superseded(대체됨) 객체는 위 채널 어디에도 안 나온다 — 현재 사실은 대체한 새 객체가 답하고,
"왜/언제 바뀌었어"는 새 객체의 supersedes 사슬(연결된 DecisionRecord·EventLedgerRecord)이 답한다.

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

- 조회와 한 흐름이라 이 스킬에 둔다. **일괄 승격(`promote-auto`)은 적재 스킬
  ({{PROJECT}}-brain-ingest) 몫** — 여기서 돌리지 않는다.
- 승격 후 색인 재생성(`project-brain index rebuild`)까지 해야 다음 검색에 status
  변화가 반영된다.

## 6. 이력 질문 가드

"왜 바뀌었어/그때는 어땠어" 질문인데 적중 매핑의 `caveats`에 `history_coverage=complete`가
없으면 "변경 이력 미적재"로 답한다 — 현재 사실(meaning/value/boundary)과 변경 이력은
다른 축이다(적재 스킬과 같은 규칙을 조회 쪽에서도 지킨다).

## 7. scope 자동 추론이 배선돼 있다

질의가 기능명을 단일하게 특정하면(컨텍스트 표면의 내용 토큰이 전부
질의에 포함 — 예: "<기능명> 보상") 그 컨텍스트로 하드 필터가
자동으로 걸린다. 기능 언급이 없거나 여러 기능을 같이 언급하면 필터
없이 전체 검색(연관도 가중만). 다른 기능 객체가 섞여 보이면 질의에
기능명을 정확히 넣어 재검색하고, 그래도 섞이면 결과의 context_id로
수동 필터해서 답한다.

## 8. 개발 착수 요구사항 — 조립 모드

단일 질문("X가 뭐야")이 아니라 **개발 요구사항**(기능 추가/수정 착수)을 받으면, 단발 검색으로
끝내지 말고 착수 컨텍스트를 조립한다. 목표 = 코드 뒤지기 전에 "어디를 만지고 무엇을 알아야
하는지"를 brain만으로 묶어내기.

0. **재사용 후보 먼저 확인** — `project-brain search`로 요구를 질의하면 출력의
   `projection_reuse` 채널("재사용 후보(미검증)")에 이전 착수 브리핑이 잡힐 수 있다.
   후보가 이번 요구와 맞으면(범위·5요소) 그 payload를 토대로 빈 곳만 보강하고 2~4단계
   전체 조립은 생략한다. 없거나 낡았거나 범위가 어긋나면 1~5단계로 새로 조립한다.
   후보는 항상 "확인 필요"로 다루고, 확신은 정본 객체(results) 적중으로 확인한다.

1. **도메인 특정** — 요구에서 기능·개념 단위 컨텍스트 후보를 집는다.
2. **분해 질의 (최소 3축)** — 한 번에 안 나온다. 구조·표시("X 팝업·화면 구조"), 데이터
   ("X 데이터 모델·출처"), 흐름·결정("X 흐름·분기·이력")을 각각 질의한다. 각 질의는 **도메인
   용어로 바꿔 1회 재시도**(자연어 단어가 도메인 용어와 어긋나면 미스 — 자연어 단어 대신
   코드/기획이 쓰는 도메인 용어로). 식별자를 알면 클래스명 직격(가장 정확). 1차가
   미스/`needs_clarification`이어도, 같은 컨텍스트의 인접 객체는 대개 회수되니 그 표면에서
   도메인 용어를 얻어 재질의한다 — **변형 재시도는 의무**(없다 단정은 재시도 후).
3. **적중 객체 원문 열람** — 검색 surface는 잘린다. 핵심 매핑은 객체 JSON 원문
   (meaning·boundary·caveats)까지 읽는다.
4. **5요소로 조립** — (1) 데이터 출처(어느 모델/테이블이 무엇을) (2) 구조·표시 패턴
   (재사용 후보 포함) (3) 확장 지점(신규/수정 시 만지는 곳) (4) 기존 규칙·함정(보정·타이밍·
   컨벤션) (5) 과거 결정(왜 이 구조). 각 사실에 근거(객체 id) 표기.
5. **없는 것 명시** — "brain에 없음" 목록(신규 UI 배치·미적재 시그니처 등. 기존 4번 계약 그대로).

**과잉 금지**: 단발/소수 질의가 5요소를 이미 채우면 거기서 멈춘다. 잘 적재된 도메인(확장 지점을
한 매핑에 모아둔 경우 등)은 분해 질의가 불필요할 수 있다 — 기준은 5요소가 차는지이지 질의 횟수가
아니다.

6. **재사용 저장(조건 충족 시에만)** — 조립이 (가) 한 기능(context)으로 수렴 (나) 5요소를 다 채움
   (다) 구성 객체 id가 확정된 경우에만, candidate projection으로 저장한다.
   **수작업 JSON 작성 금지** — 반드시 아래 CLI를 사용한다(hash·source_content_hash·projection_hash는
   엔진이 계산하므로 직접 기입하면 틀린다):

   ```bash
   # payload를 파일로 먼저 저장한 뒤 CLI에 넘긴다
   project-brain projection build-reuse \
     --context-id <context_id> \
     --requirement-key <requirement_key> \
     --source-object-ids <id1> <id2> ... \
     --title "<브리핑 제목>" \
     --payload-file <payload.json 경로> \
     --generated-by query-skill \
     --write
   ```

   - `--write` 없이 실행하면 저장 없이 미리보기만 출력된다(조건 점검 용도).
   - 같은 `context_id + requirement_key`로 이미 저장된 projection이 있으면 `--replace`를 추가해야
     교체된다(없으면 CLI가 거부하고 종료).
   - 단 기존 projection이 **reviewed면 `--replace`로도 교체되지 않는다**(정책: 재검증 강제). reviewed
     브리핑이 낡았으면 같은 id 재생성이 아니라 1~5단계로 **새로 조립**한다(새 candidate). 갱신 메커니즘은
     후속 과제다.
   - 저장 성공 후 반드시 색인을 재생성한다:
     ```bash
     project-brain index rebuild
     ```
   - 구성 객체(`source_object_ids`)가 바뀌면 rebuild가 자동으로 그 projection을 색인에서 뺀다(낡음).
   - 부분 조립·needs_clarification 단계에선 저장하지 않는다.

7. **사용 시점 승격** — 0단계에서 회수한 재사용 후보가 이번 요구에 실제로 맞았으면 reviewed로
   promote한다(`project-brain promote` — 범용 승격기라 ContextProjection도 그대로 승격되며,
   낡은 candidate는 lint 단계에서 거부된다). reviewed가 돼도 projection은 정본 results가 아니라
   projection_reuse 채널로만 노출되고(채널 이동 없음), 라벨만 "재사용 후보(미검증)"→"재사용
   브리핑(검증됨)"으로 바뀐다. 어긋났으면 promote하지 않는다.

## Common Mistakes

| 실수 | 바로잡기 |
|---|---|
| 도메인 질문에 바로 일반 탐색부터 | `project-brain search` 먼저. 폴백은 "brain에 없음" 명시 후 |
| candidate 적중을 확신처럼 답함 | "확인 필요" 라벨 필수. 사용자 확인 시 promote |
| 검색 결과에 없는 사실을 brain 답에 섞음 | brain 출처와 일반 지식을 구분해 말한다 |
| reviewed니까 "왜 바뀌었는지"도 답함 | `history_coverage=complete` 없으면 이력 질문 차단 |
| promote 후 바로 재검색 | 색인 재생성(`index rebuild`) 후에야 status 반영 |
| 개발 요구사항에 단발 검색 하나로 답함 | 8번 조립 모드 — 분해 질의 3축·원문 열람·5요소. 단 단발이 5요소 채우면 멈춤(과잉 금지) |
| 조립 끝났는데 재사용 저장 안 함 | 한 기능 수렴+5요소+source 확정이면 candidate projection 저장. 부분/clarifying은 금지 |
| 재사용 후보를 확신처럼 답함 | "재사용 후보(미검증)" 라벨 필수. 정본 results 적중으로 확인 후 promote |
