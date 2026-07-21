# 대량 적재 엔진·스킬 개선 설계

- 날짜: 2026-07-21
- 상태: 구현 전 설계
- 범위: `project-brain` 엔진과 단일 원본 적재 스킬 템플릿, BB2 설치본 전파
- 근거 세션: Claude Code `d56a5ab7-a945-4663-b50e-426bfd20902f`

## 1. 목표

대량 적재에서 실제로 드러난 실패를 엔진의 기계적 검증과 적재 스킬의 실행 계약으로 나눠 막는다.
동시에 389줄·3,201단어인 `templates/ingest/SKILL.md`를 실행 라우터로 줄이고, 상세 지식은 이미 있는
`references/`에 한 번만 둔다.

완료 기준은 다음과 같다.

- 전체 ID가 논리 key 자리에 들어가도 이중 접두 객체가 만들어지기 전에 `build`가 거부한다.
- 대량 raw 색인에서 토큰 근사가 한글·마크다운 기호를 0에 가깝게 세지 않으며, 실모델은 2,048 토큰
  상한을 회귀 테스트로 보장한다.
- 여러 항목을 적재할 때 항목마다 색인을 다시 만들지 않고, 전 항목 성공 후 한 번만 마무리 검증한다.
- 워크플로우의 최상위 상태가 `completed`여도 내부 실패·누락이 있으면 적재 단계로 넘어가지 않는다.
- 코드 흐름을 근거로 쓰는 매핑은 프로젝트별 코드 검증 계약을 따른다. BB2에서는 설치본의
  `references/project-code-verification.md`가 `bb2-code-search-routing`과 clangd callers 규칙을 연결한다.
- 기획서 raw 파일명은 버전형과 대량 보관형을 구분해 `analyze-spec-ppt` 규약과 충돌하지 않는다.
- `SKILL.md`는 130~170줄의 실행 라우터가 되고, 같은 정의를 본문·참조에 반복하지 않는다.
- `project-brain` 템플릿을 고친 뒤 installer로 BB2 설치본에 전파하며 직접 복사하지 않는다.

## 2. 확인된 문제

### 2.1 엔진

#### E1. 논리 key 형식 검증 부재

`derive_id(kind, ctx, key)`는 문자열을 그대로 이어 붙인다. 대량 적재 중 에이전트가 `key` 자리에
`g.disturb-bubble-system.bubble-attribution` 같은 전체 ID를 넣었고, 24개 객체가 이중 접두 ID로
생성됐다. 당시 조립기가 이를 통과시켰고, 65개 객체 삭제와 컨텍스트 복원 뒤 재적재해야 했다.

스키마는 완성된 ID가 문자열인지 볼 뿐, 조립 노트의 `key`가 논리 key인지 확인하지 않는다. 이 검증은
`validate_notes()`가 맡아야 한다.

#### E2. raw 토큰 근사의 과소계산

현재 `approx_tokens()`는 영문 단어 수와 한글 글자 수의 절반만 세며 마크다운 표 기호를 세지 않는다.
90개 기획서를 색인할 때 한 청크가 실모델에서 매우 긴 시퀀스가 되어 MPS가 24.29GiB 버퍼를 요구하며
중단됐다.

`4b3d02f`에서 `RealEmbedder.max_seq_length=2048` 상한은 반영됐다. 재발 방어선은 생겼지만 다음 두
구멍이 남아 있다.

- 상한을 보장하는 단위 테스트가 없다.
- 청커가 계속 과대한 청크를 만들면 2,048 토큰 뒤쪽이 잘려 검색 품질이 떨어질 수 있다.

#### E3. 단건 중심 실행 도구

`run_ingest.sh`는 한 항목마다 `index rebuild`와 전체 검증을 실행한다. 실제 136개 패밀리 적재에서는
세션 임시 `run_wave.sh`와 `finish_wave.sh`를 따로 만들어 색인을 웨이브당 한 번으로 줄였다. 재사용
도구에 대량 모드가 없어 매번 임시 러너를 다시 만드는 상태다.

### 2.2 스킬과 운영 계약

#### S1. 본문 과밀과 중복

현재 본문은 389줄·3,201단어다. 적용 범위, 세 상태축, 절대 규칙, 객체화 기준, Source Intake, 5단계
추출, 판정 트리, 완료 점검, 실행 명령, 실수 목록, 동의어, raw 정책을 한 파일에 모두 담는다.

같은 내용이 `scope.md`, `object-model.md`, `completeness-checklist.md`, `judgment.md`,
`ingest-tools.md`, `worked-example.md`에도 반복된다. 특히 `feature_done/current_ingest_done/
history_coverage`와 history literal이 네 파일 이상에 중복된다.

#### S2. 워크플로우 최상위 상태를 완료로 오인

세션 한도에 걸린 워크플로우가 `status=completed`로 끝났지만 내부 결과는 38명 중 11명 완료,
27명 실패였다. 다른 웨이브에서도 `completed`인데 실제 결과는 11/27이고 verify가 전멸했다.

완료 판정은 최상위 상태가 아니라 예상 항목 수, 성공 수, 실패 배열, 빈 결과, verify 판정을 모두 봐야 한다.

#### S3. 코드 흐름 확인 강제 부족

첫 검증에서는 코드로 확인 가능한 내용도 모호하다고 남았다. 이후 `bb2-code-search-routing`을 프롬프트에
넣고 clangd callers 실행 기록을 필수로 하자 68개 항목이 pass 35·fixed 33·needs_user 0으로 닫혔다.

대규모 시스템 playbook에는 이 검색 계약이 필수 단계로 연결돼 있지 않다. 다만 이는 BB2에서 확인된
구체 사례다. 범용 `project-brain` 템플릿은 특정 스킬이나 검색 엔진 이름을 직접 요구하지 않고,
프로젝트가 제공한 코드 검증 계약을 읽고 작업자 프롬프트까지 전달하는 책임만 가져야 한다.

#### S4. raw 파일명 규약 충돌

`bb2-brain-ingest`는 `<원본 파일명>` 보존을 말하고, `analyze-spec-ppt`는 개정 이력 추적을 위해
`spec-v<N>.md`를 요구한다. 실제 대량 보관은 서로 다른 옛 기획서 90개를 한 디렉터리에 넣는 작업이라
원본 basename 보존이 필요했다. 두 작업을 한 규칙으로 표현한 것이 문제다.

#### S5. 템플릿과 설치본의 소유권

단일 원본은 `project-brain/src/project_brain/templates/ingest/`다. BB2의
`.agents/skills/bb2-brain-ingest/`는 `.project-brain-manifest.json`이 추적하는 설치본이다.
BB2 설치본만 직접 고치면 다음 install에서 드리프트 또는 skip이 생긴다.

## 3. 검토한 접근

### 접근 A. 문서만 줄이기

`SKILL.md`를 references로 옮기기만 한다.

- 장점: 변경량이 작고 빠르다.
- 단점: 이중 접두 key, 반복 색인, 부분 완료 오인, MPS 회귀를 막지 못한다.
- 결론: 실제 사고를 재발 방지하지 못하므로 채택하지 않는다.

### 접근 B. BB2 설치본을 직접 고치기

BB2 스킬과 스크립트만 수정한다.

- 장점: 당장 BB2에는 빠르게 반영된다.
- 단점: engine template 단일 원본과 갈라지고 installer 소유권 계약을 어긴다. key 검증과 청커 문제도
  엔진에 남는다.
- 결론: 채택하지 않는다.

### 접근 C. 엔진 가드 + 단일 원본 템플릿 + installer 전파

엔진이 형식과 자원 한계를 막고, 템플릿은 실행 순서·의미 판단·대량 운영 계약을 담는다. BB2는 installer로
전파한다.

- 장점: 실패를 가장 가까운 계층에서 막고, 이후 설치 프로젝트에도 같은 개선이 적용된다.
- 단점: 엔진과 템플릿을 함께 바꾸므로 테스트와 전파 검증이 필요하다.
- 결론: 이 접근을 채택한다.

## 4. 설계

### 4.1 책임 경계

| 계층 | 책임 | 하지 않는 일 |
|---|---|---|
| 엔진 `assembly.py` | 논리 key 형식, 필수 필드, 참조 가능한 노트 형식 거부 | 의미 경계·대체/보완 판정 |
| 엔진 `raw_chunks.py` | 보수적 토큰 근사와 과대 유닛 분할 | 실제 모델 토크나이저 로드 |
| 엔진 `embedder.py` | 실모델 입력 길이 최종 상한 | 청크 의미 분할 |
| 스킬 `SKILL.md` | 실행 순서, 필수 게이트, 조건별 reference 라우팅 | 객체 필드 전체 설명·CLI 전체 설명 |
| 스킬 `references/` | 범위·객체·판정·도구·대량 운영의 각 단일 원본 | 서로 같은 정의 반복 |
| 프로젝트 전용 overlay | 프로젝트의 정확한 검색 스킬·도구·예외 규칙 | 범용 템플릿에 프로젝트 이름을 역주입 |
| 스킬 `scripts/` | 조립, 대량 실행, 결과 검증, 최종화의 결정론적 작업 | 도메인 의미 추론 |
| installer | 템플릿을 프로젝트별 값으로 렌더하고 설치본 소유권 추적 | 사용자 수정 파일의 무조건 덮어쓰기 |

### 4.2 논리 key 계약

논리 key는 완성 ID가 아니다. 섹션별 허용 형식은 다음과 같다.

- `context.key`, `glossary[].key`, `mappings[].key`, `decisions[].key`:
  `^[a-z0-9]+(?:-[a-z0-9]+)*$`
- `code_anchors[].key`: 위 형식 또는 조립기가 붙이는 `--<순번>` 접미
- 같은 형식을 적용할 참조 필드:
  `glossary_keys[]`, `code_evref_keys[]`, `decision_keys[]`, `decisions[].affects[]`
- `sources[].id`, `refs`, `updates[].id`는 이미 완성 ID를 받으므로 이 검사 대상이 아니다.

오류에는 정확한 위치와 값, 기대 형식을 포함한다. 자동으로 접두를 제거하지 않는다. 자동 보정은 잘못된
컨텍스트의 전체 ID를 정상 key처럼 바꿀 수 있기 때문이다.

### 4.3 raw 청크 안전

근사는 외부 토크나이저 없이 결정론을 유지한다.

- ASCII 영숫자/밑줄 묶음: 1
- 한글 음절: 1
- 나머지 비공백 문자: 2자당 1, 최소 1
- 한 유닛 자체가 목표치를 넘으면 문자 경계의 작은 조각으로 먼저 나눈다.

이 값은 정확한 토큰 수가 아니라 과대 청크를 피하는 보수적 예산이다. 실모델의 2,048 상한은 마지막
방어선으로 유지한다.

### 4.4 단건·대량 실행

실행 도구를 세 책임으로 나눈다.

1. `run_ingest.sh`: 한 항목의 assemble → build → ingest. `--dry`와 `--defer-finalize`를 지원한다.
2. `run_ingest_batch.py`: manifest의 여러 항목을 순서대로 실행하고 상태 JSON을 남긴다. 실패가 하나라도
   있으면 finalization을 호출하지 않는다. `--resume <report>`는 성공 항목만 건너뛴다.
3. `finalize_ingest.sh`: 전체 묶음이 성공한 뒤 index rebuild → lint → eval → search → graph →
   real-corpus unittest를 한 번 실행한다.

batch manifest 계약:

```json
{
  "items": [
    {"key": "disturb-a", "verify_json": "out/a.json", "domain_spec_py": "spec/a.py"}
  ]
}
```

report 계약:

```json
{
  "expected": 1,
  "succeeded": ["disturb-a"],
  "failed": [],
  "finalized": true
}
```

### 4.5 동적 워크플로우 완료 게이트

동적 워크플로우는 최종 결과를 다음 공통 모양으로 정규화한다.

```json
{
  "expected": 2,
  "items": [
    {"key": "a", "extract_status": "ok", "verify_status": "ok", "verdict": "pass"},
    {"key": "b", "extract_status": "ok", "verify_status": "ok", "verdict": "fixed"}
  ],
  "failures": []
}
```

`validate_workflow_result.py`는 다음을 모두 만족해야 성공한다.

- `len(items) == expected`
- key 중복 없음
- `failures`가 비어 있음
- 모든 extract/verify 상태가 `ok`
- verdict가 `pass` 또는 `fixed`

세션 한도처럼 재개 가능한 실패는 `blocked`가 아니라 미완료 report로 남긴다. 같은 입력과 run ID로 재개한
뒤 다시 게이트를 통과해야 적재할 수 있다.

### 4.6 코드 흐름 검증 계약

범용 템플릿은 특정 프로젝트의 검색 스킬이나 도구를 직접 의존하지 않는다. 대신 다음 계약을 강제한다.

- 프로젝트 `AGENTS.md`와 프로젝트 전용 코드 검색 규칙을 우선한다.
- 코드 흐름을 근거로 쓸 때는 호출처 추적 기록이나, 호출처 추적이 불가능한 경계와 대체 확인 기록을 남긴다.
- `references/project-code-verification.md`가 있으면 코드 기반 extract/verify 전에 반드시 읽는다.
- 동적 workflow나 하위 작업자에게 코드 검증을 맡기면 읽은 프로젝트 계약을 작업자 프롬프트에도 전달한다.
- 코드로 확인 가능한데 프로젝트 계약에 맞는 query 기록이 없으면 `needs_user`가 아니라 검증 실패다.

`project-code-verification.md`는 installer가 생성하거나 manifest로 관리하지 않는 선택적 프로젝트 덧붙임
파일(overlay)이다.
BB2 설치본에는 이 파일을 두고 다음을 소유하게 한다.

- 필수 하위 스킬: `bb2-code-search-routing`
- 일반 함수·메서드 호출처: clangd callers 우선
- 매크로 생성 심볼: `rg`
- notification/callback 경계: 발신과 수신을 `rg`로 잇고, 양쪽 심볼 callers를 가능한 범위에서 확인
- 결과 atom: 실행한 query, 시작 심볼, 확인한 경계, 끊긴 지점 기록

BB2의 `AGENTS.md`와 `bb2-code-search-routing/SKILL.md`에는 이미 이 라우팅 계약이 있으므로 이번 작업에서
수정하지 않는다. 적재 스킬 overlay는 기존 프로젝트 규칙을 적재·검증 단계에 연결하는 얇은 어댑터다.

### 4.7 SKILL.md 축소와 reference 소유권

`SKILL.md`는 다음 다섯 부분만 남긴다.

1. 적용 범위와 다른 brain 스킬과의 경계
2. 절대 규칙 6~8개
3. Source Intake → extract → adversarial verify → build/ingest → finalize 흐름
4. 단건/대량 분기와 완료 게이트
5. 상황별 reference 라우팅

목표는 130~170줄이다. `references/`의 소유권은 다음처럼 고정한다.

| 파일 | 유일하게 소유할 내용 |
|---|---|
| `scope.md` | 적용 시나리오, 세 상태축, 머지 전/후 경계 |
| `object-model.md` | 객체 필드, 연결, logical key, 동의어 계약 |
| `judgment.md` | 대체·보완·충돌과 이력 판정 |
| `ingest-tools.md` | CLI, raw 저장, 단건·대량 스크립트 사용법 |
| `system-domain-playbook.md` | 대규모 분할, 동적 workflow, 프로젝트 코드 검증 계약 전달, 재개·완료 게이트 |
| `completeness-checklist.md` | 적재 직전/직후 통과 조건만 |
| `worked-example.md` | 작은 end-to-end 예시 하나 |
| `ingest-case-log.md` | 재사용 코드로 승격할 실제 변칙 기록 |
| `project-code-verification.md` | 선택적 프로젝트 overlay. 정확한 검색 스킬·도구·예외 규칙이며 템플릿에는 포함하지 않음 |

100줄을 넘는 reference에는 짧은 목차를 둔다.

### 4.8 raw 이름 규칙

두 모드를 분리한다.

- 한 기능의 개정 기획서: `brain/raw/sources/<context>/spec-v<N>.md`. 버전 번호는
  `analyze-spec-ppt` 규약을 따른다. 이전 버전을 덮어쓰지 않는다.
- 서로 다른 옛 문서의 대량 보관 또는 내부 버전이 불명확한 자료 묶음:
  `brain/raw/sources/<context>/<sanitized-original-basename>.md`. manifest에 원본 파일명과 변환 방식을
  남긴다.

같은 컨텍스트에서 두 모드를 섞을 때 파일 충돌이 없도록 하고, 바이너리는 계속 Git에 넣지 않는다.

### 4.9 단일 원본 전파

수정 순서는 고정한다.

1. `project-brain` 엔진과 `src/project_brain/templates/ingest/` 수정
2. 엔진·템플릿 테스트 통과
3. `project-brain install --target <bb2-root>` 실행
4. BB2 설치본에 installer 관리 밖의 `references/project-code-verification.md` 추가
5. installer를 다시 실행해 overlay 내용이 그대로이고 manifest에 들어가지 않는지 확인
6. report의 `skipped`가 비어 있는지 확인
7. BB2의 `.agents/skills/bb2-brain-ingest` diff 검토
8. `agents-doctor`로 `.claude/skills` 심링크와 프로젝트 구조 확인

installer report에 managed skill 파일이 `skipped`로 나오면 `--force`로 즉시 덮지 않는다. 설치본의 사용자
수정인지 먼저 diff하고, 템플릿에 역반영할 내용인지 결정한다.

## 5. 테스트 전략

### RED: 실제 실패를 작은 재현으로 고정

- 전체 ID를 `mappings[].key`에 넣으면 현재 build가 이중 접두 ID를 만든다.
- 한글·기호가 많은 긴 표가 목표 토큰 이하로 과소계산된다.
- 워크플로우 `completed` 결과에 내부 실패가 있어도 별도 validator가 없어 통과한다.
- batch 기능이 없어 각 항목이 색인을 반복한다.
- 현재 범용 스킬은 프로젝트 전용 코드 검증 계약을 읽거나 하위 작업자에게 전달하지 않는다.

### GREEN: 최소 구현

- `validate_notes`의 key 검사
- 보수적 `approx_tokens`와 과대 유닛 분할
- 실모델 상한 단위 테스트
- batch/finalize/workflow validator 스크립트
- 130~170줄 실행 라우터와 reference 재배치

### REFACTOR: 전파와 독립 사용 검증

- installer 테스트로 새 파일 포함·개발 테스트 제외 확인
- installer 재실행이 프로젝트 전용 overlay를 보존하고 manifest에 넣지 않는지 확인
- BB2 설치본에 전파하고 `agents-doctor` 실행
- 작은 가상 적재 5개 시나리오로 수정 전/후 에이전트 행동 비교
- 기존 엔진 전체 테스트와 BB2 brain corpus 검증 실행

## 6. 범위 밖

- 136개 방해버블 데이터 자체의 재작성
- Claude Workflow의 세션 사용량 제한 제거
- 도메인 의미를 엔진이 자동 판정하는 기능
- 실제 모델 토크나이저를 청커에 로드하는 변경
- `analyze-spec-ppt`의 버전 규칙 변경
- 다른 brain 스킬의 전면 다이어트

## 7. 위험과 대응

| 위험 | 대응 |
|---|---|
| key 정규식이 기존 합법 key를 거부 | 실코퍼스와 테스트 fixture에서 key 문자 집합을 먼저 스캔하고 RED 테스트를 추가 |
| 청크 수 증가로 real-corpus 상수 변화 | stub 임베더로 raw chunk 수를 재측정하고 데이터 레포 가드는 의식적으로 갱신 |
| batch 중 일부 ingest 후 실패 | report에 성공 목록을 남기고 finalize 금지, 같은 NOW로 `--resume` |
| 스킬 축소 중 안전 규칙 유실 | 요구사항-파일 추적표와 계약 테스트로 각 규칙의 새 위치 확인 |
| installer가 사용자 변경을 건너뜀 | `skipped`가 하나라도 있으면 중단하고 diff, 즉시 `--force` 금지 |
| 프로젝트 overlay를 읽지 않고 코드 검증 시작 | `SKILL.md`의 조건부 라우팅과 BB2 행동 시나리오로 차단 |
| installer가 프로젝트 overlay를 덮거나 소유권에 포함 | 재설치 전후 해시 비교와 manifest 부재 테스트로 차단 |
| BB2에서 clangd가 macro/callback 경계에서 끊김 | BB2 overlay에 기존 `bb2-code-search-routing`의 rg 예외와 양방향 추적을 연결 |
