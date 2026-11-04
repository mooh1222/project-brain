# Brain KW-E3 실행 검증 (#117)

통합 code-review 보완 후 W-T1과 W-T3를 memory·hook 비활성 조건에서 각각 두 회차
재실행했다. W-T1 최초 두 기록은 개인 memory를 읽었으므로 신규 집계에서 제외한다.
재실행의 분리 판정 및 회귀 결과는 아래에 기록한다. W-T2·W-T4~W-T6은 기존 E3 증거를
유지하며, 이들을 이번 템플릿 변경 후 다시 실행했다는 뜻은 아니다.

기존 E3 검증 엔진은 `be75896a18efc076150708882c8af453ee970672`이고 결과 보고서
커밋은 `4582d1e6e3b3ae6388a445a58047ea57a0347453`이다. 이번 작업의 기준 HEAD는
그 보고서 커밋이며, 변경 diff와 설치 스킬 해시를 별도로 보존한다.

## 실행과 증거

실행·회상·판정은 Codex CLI 0.166.0의 `gpt-6.1-sol`, reasoning `high`로 고정했다.
Python 3.12.11에서 검색·색인에 StubEmbedder와 regex 토큰화를 사용했고 실모델
임베딩은 로드하지 않았다. 기존 E3의 기록·회상 26개 세션을 독립 합성 소비 프로젝트에서 실행했으며,
Codex는 동시에 최대 두 개만 실행했다. 회상에는 원래 대화·저장 경로·객체 ID·기대 답변을
제공하지 않았다.

작은 판정·관찰·요청·답변은 아래 추적 디렉터리에서 읽을 수 있다. 과거 판정은 당시
결과의 보존 사본이며, 각 사본의 머리말이 W-T1의 교체 집계를 명시한다.

- [기존 E3 summary](brain-knowledge-workflow-validation/20261104T065347Z/summary.md)
- [기존 1회차 판정](brain-knowledge-workflow-validation/20261104T065347Z/judge-1.answer.md)
- [기존 2회차 판정](brain-knowledge-workflow-validation/20261104T065347Z/judge-2.answer.md)
- [기존 종합 판정](brain-knowledge-workflow-validation/20261104T065347Z/judge-overall.answer.md)

대용량 원본(약 100MB: native JSONL·프로젝트·파일 해시·Git 상태 등)은 로컬 전용이다.
보존 사본 위치는 `/Users/al03040455/.copilot/session-state/546d51f6-df99-4c46-976e-9a9678a9ca55/files/brain-kw/evidence/20261104T065347Z`다.
이번 재실행 원본은 `.scratch/brain-knowledge-workflow-validation/20261104-review-fix/`에 둔다.
로컬 전용 원본에는 링크하지 않는다.

| 사례 | 결과 | 검증 기준 | 관찰한 동작 |
|---|---|---|---|
| W-T1 | 2/2 PASS | 이번 수정 후 재실행 | 단건 조사 주제 기록, 새 세션의 본문·출처·가설·미결 회수와 미검수 표시 |
| W-T2 | 2/2 PASS | 기존 E3 | 초안 선행 없는 Insight 직접 적재와 advisories·show 회수 |
| W-T3 | 2/2 PASS | 이번 수정 후 재실행 | 이해·개선 행동 분리, 제안 본문 직접 읽기, 상태 필드 미생성·채택 링크 |
| W-T4 | 2/2 PASS | 기존 E3 | 오래된 가설 대조, 실제 partial·권한·색인 실패 구분과 가능한 조회 지속 |
| W-T5 | 2/2 PASS | 기존 E3 | 다른 설정 루트, 기존 v1·검증 대기 인사이트(기존 기록) 보존, 정상 기록과 backlog 부재 무생성 |
| W-T6 | 2/2 PASS | 기존 E3 | 적재 후 실제 stale-SHA, 최신 SHA 복구, 동시 질문 보존, 성공 ingest 각 1회 |
| W-T7 | PASS | 이번 수정 후 재확인 | 두 번째 설치 변경 배열 모두 비어 있음, 사용자 수정 5개 skipped·보존, overlay 비관리 |

기존 E3의 읽기 세션 14개와 이번 읽기 세션 4개는 각각 읽을 수 있는 파일 해시·Git 상태가
전후 같았다. 기존 권한 차단 파일의 본문 해시에는 아래 한계를 적용한다.

## 통합 검수 수정 후 재검증

- [이번 summary](brain-knowledge-workflow-validation/20261104-review-fix/summary.md)
- [1회차 분리 판정](brain-knowledge-workflow-validation/20261104-review-fix/judge-1.answer.md)
- [2회차 분리 판정](brain-knowledge-workflow-validation/20261104-review-fix/judge-2.answer.md)
- [판정자 native 신원 후속 확인](brain-knowledge-workflow-validation/20261104-review-fix/judge-identity.md)
- [W-T7 재확인](brain-knowledge-workflow-validation/20261104-review-fix/w-t7.md)

기록·회상 8개와 판정 2개 모두 Codex `gpt-6.1-sol` high, CLI 0.166.0이며 동시 최대 2개였다.
전 과정 memory·hook을 비활성화했고 native의 `memory_mode=disabled`와 실제 모델·effort를
확인했다. StubEmbedder·regex와 실모델 로드 차단을 유지했다. 설치 파일 66개씩의 해시가
네 프로젝트에서 현재 템플릿·manifest·저장된 해시와 일치했다.

ADR 0006의 재검토 이유를 [ADR 0010](../adr/0010-align-knowledge-recording-and-recall.md)에
기록하고 CONTEXT·spec·공통 판단·query의 용어를 맞췄다. 임베딩 안내는 ingest-tools를
정본으로 두고 query의 설치 후 상대 링크·앵커를 확인했다. P3의 미합의 후보 처리도 공통
reference에 보완했다. S4의 query §0 라우팅 재서술은 적용하지 않았다.

기존 계약 검사에서 pending 용어 불일치 2건을 먼저 재현한 뒤 수정했다.
통합 tip 병합 확인은 `Already up to date`였고, 이후 표적 스킬 계약·installer·구조 문서는
**94 passed, 16 subtests passed**였다. 전체 pytest와 runtime 결과는 아래 현재 회귀 수치에 기록한다.

P3의 실제 사용자 3라운드 대화를 새로 실행한 결과는 아니다. 공통 규칙의 보완과 영향 사례
W-T1·W-T3의 새 세션 기록·회상을 확인했다. 판정 준비 스크립트의 두 import 오류는 모델
호출 전에 종료했고 통과 집계에서 제외했다. 원래 hc 화면·종료 상태를 추가 보존했다.
판정자의 자기 native 미확인 표시는 원문에 남기고, 종료 후 실행 담당자가 실제 native로
보완했다. CLI marketplace 갱신 오류와 프로젝트 밖 임시 patch에 관한 범위 한계도
분리 판정에 보존했다.

## 이번 수정 후 회귀 결과

- [전체 pytest](brain-knowledge-workflow-validation/20261104-review-fix/pytest-full.log): **2527 passed, 174 subtests passed**, exit 0.
- [설치 ingest runtime unittest](brain-knowledge-workflow-validation/20261104-review-fix/runtime-unittest.log): **151 tests, OK**, exit 0.
- 스킬 계약·installer·구조 문서: **94 passed, 16 subtests passed**.
- 설치된 query 상대 링크·앵커, 임베딩 안내 단일 정본, P3 미합의 후보 처리와 두 번째 install 무변경 확인 PASS.
- `git diff --check` PASS. 엔진 Python·객체·검색 입력은 변경하지 않아 실코퍼스 회귀·rebuild는 수행하지 않았다.

## 기존 E3 회귀 결과

- 전체 pytest: **2527 passed, 174 subtests passed**.
- 설치 ingest runtime unittest: **151 tests, OK**.
- W-T7 installer·스킬 계약: **59 passed, 16 subtests passed**.
- 통합 tip 재병합 확인 후 installer·스킬 계약·구조 문서: **75 passed, 16 subtests passed**.
- 재병합 확인 후 설치 runtime: **151 tests, OK**.

최초 W-T2 두 시도는 합성 환경의 eval/checks·기준 ref 준비 누락으로 최종화가 미완료였다.
이 시도는 통과 집계에서 제외하고 보존했다. 환경 준비를 보완한 별도 프로젝트 두 곳에서
같은 자연어 요청을 재실행했다. 복구된 CLI 인자·출력 경로 오류도 원본 로그에 남겼다.

## 판정 범위

기존 W-T1 두 기록 세션 모두 host memory의 관련 지침을 읽었다. 해당 두 회차는
memory 비활성 검증에서 제외하며, 이번 새 기록·회상·판정 두 회차로 교체한다.
기존 W-T2·W-T4~W-T6과 W-T7 수치는 당시 검증 기준점의 결과로 구분한다.

W-T4 mode 000 파일은 실제 접근 실패·권한 유지·쓰기 명령 부재를 확인했지만, 전후 본문을
직접 재해시하지 못했다. 파일 해시에서 `.git` 내부와 `__pycache__`는 제외하며 Git 상태는
별도 비교했다. W-T6는 공개 SHA 갱신 호출을 교차시킨 결정론 충돌 주입이다. 독립 OS
프로세스의 병렬 스트레스 검증은 수행하지 않았다.

2회차 판정자는 W-T4 원답의 “변경 이력은 미적재” 표현이 query 결과만으로 증명되지
않는다고 지적했다. 이 결과가 확인한 범위는 해당 질의에서 이력을 회수하지 못했다는 것이다.
두 회차 모두 실제 5회에서 3회로 변경됐다는 결론은 내리지 않았다. CLI startup의 marketplace
자동 갱신 오류도 로그에 보존했다. 두 판정자는 현재 증거에서 KW 범위 템플릿 결함에 의한
기능 실패를 식별하지 않았다.

이 결과는 고정 모델·환경·요청의 재현 증거다. 합성 데이터 밖의 소비 프로젝트·실코퍼스·
전역 설치는 변경하지 않았으며, 실제 앱·장치·서버 동작이나 다른 모델·표현의 성공률까지
일반화하지 않는다.
