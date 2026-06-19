---
name: {{PROJECT}}-brain-ingest
description: |
  Use when 완료된 {{PROJECT}} 기능/스펙을 Brain 지식 저장소에 객체 모델로 소급
  적재할 때. "이 기능 brain에 적재", "추출해서 채워줘", "ingest/promote로 brain
  채우기"처럼 Brain 적재·소급 적재·지식 추출·객체 모델 적재가 {{PROJECT}} 맥락에서
  나오면 스킬 이름을 명시하지 않아도 이 스킬을 쓴다. 진행 중 개발의 실시간 적재나
  과거 세션 로그 마이닝은 범위 밖이다.
---

# {{PROJECT}} Brain 적재 — 완료 스펙 소급

완료된 기능 하나를 골라, 그 기능의 프로젝트 지식을 Brain 저장소(`{{BRAIN_ROOT}}`)에
객체 그래프로 소급 적재한다. 코드에 앵커된 의미 매핑이 Brain을 쓸모있게 만든다.

## 역할 분담 — 먼저 머리에 박아라

추출은 **너(에이전트)의 일**이다. 무엇을 어떤 객체로 뽑고, 무엇에 연결하고, 무엇이
무엇을 대체/충돌/보완하는지의 **판정은 의미 판단이라 영구히 너의 몫**이다. 코드는
받아서 검증·저장·신호만 한다 — 판정을 코드에 넘기지 마라.

| 역할 | 담당 | 내용 |
|---|---|---|
| 판정 (대체/충돌/보완) | 너 (에이전트) | 의미 판단. 코드로 안 넘긴다 |
| 검증·저장 | `project-brain ingest`/`promote` | 스키마 + 연결 무결성 검사 후 저장 |
| 신호 | lint (ingest/promote에 내장) | 충돌·미반영 표시만 (판정 안 함) |

## 세 축을 분리한다

- `feature_done`: 기능이 소급 적재 대상일 만큼 완료됐다는 외부 상태.
- `current_ingest_done`: 현재 코드 + 현행 스펙으로 현재 meaning/value/boundary를
  적재·검수한 상태. "뭐야/어디/지금" 질문에 답한다.
- `history_coverage`: 변경 이력 확인 범위(`unsearched`/`partial`/`complete` literal로
  `DomainMapping.caveats`에). "왜/그때" 질문에만 영향을 준다.

기능이 완료됐어도 적재가 끝난 것이 아니고, 현재 사실 적재가 끝났어도 변경 이력까지
확인한 것이 아니다.

## 절대 규칙 (하나라도 어기면 적재 폐기하고 다시)

1. **세 축(`feature_done`/`current_ingest_done`/`history_coverage`)을 섞지 않는다.**
2. **기능명은 대상이지 근거가 아니다.** 소스 패킷(이번에 읽을 스펙·코드·문서 목록)을
   선언하거나 사용자에게 확인하기 전 객체 생성을 시작하지 마라.
3. **EvidenceRef는 이번 소스 패킷만 가리킨다.** 이전 세션·메모리에서 알아버린 사실은
   객체 근거가 아니다.
4. **추측 금지.** 소스에 있는 것만 적재한다. 없는 값은 비워 표시한다. 최신이 아닐 수
   있는 소스로 만든 객체는 `confidence`를 낮춘다.
5. **저장 대상에 코드 필터를 걸지 않는다.** 코드에 없는 지식(서버 판정·순수 규칙)도
   저장한다.
6. **계층이 소스를 가른다.** view 심볼 ↔ 화면 스펙, model 심볼 ↔ 데이터/서버 스펙.
   뒤바꿔 매칭하지 않는다.
7. **고아를 만들지 않는다.** 잇는 매핑·결정 없는 용어는 적재 전에 연결하거나 제거한다.
8. **코드 앵커는 기본 브랜치 기준 `commit_sha`.** 작업 브랜치 라인이 아니라 기본
   브랜치의 심볼·라인을 박는다. `mapping_key`는 논리적 의미, `code_locator`가 코드
   앵커다(심볼 rename에 견고하도록 의미와 앵커를 분리).

## 객체화 경계 — 독립 회상 가치

- **객체 저장 기준 = "독립적으로 질문되고, 독립 근거를 가질 수 있는가".** 코드 연관은
  기준이 아니라 근거의 한 종류일 뿐이다.
- **스펙의 개념 서술(세계관·컨셉·연출 설명)은 객체화하지 않는다** — raw 보관
  (`raw/sources/<context-slug>/`)이 커버하고, raw 본문 색인이 발췌 회수를 맡는다.
- **정의가 근거를 초과하면 안 된다** — 용어/매핑의 정의는 근거(EvidenceRef)가 보증하는
  범위까지만.

## 적재 실행 (B+C)

1. **검증·적대검증.** 추출한 묶음의 각 매핑이 검증된 근거(`evidence_refs`)를 갖고
   적대검증을 통과하는지 본다. 코드앵커는 근거의 한 종류일 뿐 필수가 아니다.
2. **적재.** `project-brain ingest --objects-file <json>`로 묶음을 적재한다(스키마·연결
   무결성 통과 시 저장, 실패 시 아무것도 안 쓰는 원자적 동작; 같은 id 재적재 멱등).
   - 검증 통과 + lint clean → `status:"reviewed"`로 직접 적재(B, 사람 0).
   - 근거 약함·충돌·검증 실패 → `candidate`로 적재(C — 질의 시 "확인 필요" 라벨로
     노출되고, 사용 시점에 `project-brain promote`로 확정).
3. **예외만 사람에게.** 시스템이 스스로 못 가른 충돌·경계 불명확만 예외 큐로 묶어
   사용자 확인에 올린다(전수 검수 아님).

raw 원문은 `{{BRAIN_ROOT}}/raw/sources/<context-slug>/`에 텍스트만 보관한다.
**파괴적 일괄 작업(promote-auto 등) 전 커밋 먼저** — 되돌릴 기준을 만든 뒤 돌린다.

## CLI 호출 상세 — ingest / promote

엔진(`project-brain`)은 도메인을 모른다. 받은 객체 묶음을 검증·저장만 한다. 레포 안 어느
디렉토리에서든 실행 가능하다 — 루트 `.project-brain.json` config가 brain root를 해석한다
(`--brain-root`로 덮어쓸 수 있음).

### ingest

```bash
project-brain ingest --objects-file <묶음.json>
```

- `--objects-file`: 객체 dict들의 **JSON 배열** 한 파일. 필수 필드·enum은 엔진
  `src/project_brain/schema.py`가 단일 진실 — ingest가 `validate_object`로 위반을 거부한다.
- 성공 시 `{"ok": true, "ingested": N}`, 실패 시 `{"ok": false, "error": "..."}` + 종료코드 1.
- 게이트 3개를 원자적으로 묶는다 — per-object 스키마 검증 → 병합 store 연결무결성 lint(없는 id를
  가리키는 dangling 링크 거부) → 저장. 어느 게이트든 실패하면 아무것도 안 쓴다.
- 멱등: 같은 id를 다시 ingest하면 덮어쓴다. 단 reviewed→candidate 후퇴는 거부한다.

### promote — 사용 시점 단건 확정 / 묶음 승격

candidate를 reviewed로 올린다. 승격 객체 + 검토 기록을 둘 다 저장하고, 쓰기 전 일괄 schema 검증·사후
lint까지 한 번에 한다.

```bash
project-brain promote \
  --ids <승격할 id...> --reviewer <reviewer> --reviewed-at <ISO8601> \
  [--scope mapping_bundle --bundle-key bundle.<도메인>.domain-mapping]
```

- `--scope`는 기본 `single_object`(단건 독립 승격). 여러 매핑을 한 검토 묶음으로면
  `mapping_bundle` + `--bundle-key`(없으면 거부).
- 성공 시 `{"ok": true, "promoted": [...], "reviews": [...]}`, 근거 부재·dangling 등은
  `{"ok": false, ...}` + 종료코드 1.
- `--ids`는 여러 인자를 받는다(`--ids a b c`). 셸 변수로 넘길 때 단어분리에 주의(zsh는 비따옴표
  변수를 분리하지 않는다 — 리터럴 나열이나 배열로).

## 적재 후 확인 (4단계)

```bash
project-brain index rebuild        # 색인 재생성 (실모델 배치 임베딩 — 수십 초 정상)
project-brain eval --check-ids     # 골든셋 기대 id 실존 가드
project-brain eval                 # 골든셋 회귀 (실모델)
project-brain search "<새 적재 내용 질문>"   # 새 store가 스스로 답하는지 실연
```

eval/search 출력은 `2>/dev/null | jq`로 읽는다(eval 통과수=`.summary`, search 적중=`.results`).
stdout은 깨끗한 JSON이고 노이즈는 stderr로 나가므로 `2>&1` 손파싱을 하지 마라.

적재로 색인 행 수가 변하면 실측(real-corpus) 가드 수치를 **의식적으로 갱신**하고 같은 커밋에 포함한다.

## Common Mistakes

| 실수 | 바로잡기 |
|---|---|
| 기능이 완료됐으니 적재도 완료됐다고 말함 | 세 축을 분리한다 |
| 기능명만 듣고 바로 코드 검색 | 소스 패킷을 선언한 뒤 탐색한다 |
| 이전 세션에서 안 사실을 근거로 씀 | EvidenceRef는 이번 소스 패킷만 가리킨다 |
| 코드 없는 규칙을 건너뜀 | 저장한다(규칙 5) |
| 용어만 만들고 매핑에 안 엮음 | 고아. 연결하거나 제거(규칙 7) |
| 스펙 개념 서술을 객체로 쪼갬 | 객체화 금지 — raw 보관이 커버 |
| 검증 없이 바로 reviewed | 검증된 근거 + 적대검증 + lint clean일 때만 B. 아니면 candidate(C) |
| 적재 후 색인 안 돌림 | `index rebuild` 없이는 검색에 반영 안 된다 |
