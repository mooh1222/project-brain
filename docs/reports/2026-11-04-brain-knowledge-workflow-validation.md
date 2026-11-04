# Brain KW-E3 실행 검증 (#117)

W-T1~W-T6의 모든 하위 성공 조건을 각각 두 회차에서 확인했고, W-T7 설치 조건도
통과했다. 기록·회상과 분리된 Codex 판정 세션 두 개가 회차별로 PASS를 판정했으며,
양 회차 원본과 증거 요약을 다시 연결한 종합 판정도 PASS다.

검증 엔진은 `be75896a18efc076150708882c8af453ee970672`이다. E1 #115와 E2 #116이
반영된 통합 브랜치와 같은 기준점에서 실행했다. 완료 전 통합 tip 병합 확인은
`Already up to date`였으며, 엔진 코드·설치 템플릿은 수정하지 않았다.

## 실행과 증거

실행·회상·판정은 Codex CLI 0.166.0의 `gpt-6.1-sol`, reasoning `high`로 고정했다.
Python 3.12.11에서 검색·색인에 StubEmbedder와 regex 토큰화를 사용했고 실모델
임베딩은 로드하지 않았다. 기록·회상 26개 세션을 독립 합성 소비 프로젝트에서 실행했으며,
Codex는 동시에 최대 두 개만 실행했다. 회상에는 원래 대화·저장 경로·객체 ID·기대 답변을
제공하지 않았다.

증거는 로컬 `.scratch/brain-knowledge-workflow-validation/20261104T065347Z/`에 보존한다.
아래 링크는 이 checkout의 로컬 증거를 가리킨다. 원본 native JSONL, 요청·명령·답변,
설치 스킬 해시, 조회 전후 파일 해시·Git 상태와 실패 시도는 요약에서 연결한다.
E1의 기존 W-T7 증거와 현 브랜치 재확인 결과도 요약에 연결했다.

- [전체 summary](../../.scratch/brain-knowledge-workflow-validation/20261104T065347Z/summary.md)
- [1회차 독립 판정](../../.scratch/brain-knowledge-workflow-validation/20261104T065347Z/judge-1.answer.md)
- [2회차 독립 판정](../../.scratch/brain-knowledge-workflow-validation/20261104T065347Z/judge-2.answer.md)
- [종합 판정](../../.scratch/brain-knowledge-workflow-validation/20261104T065347Z/judge-overall.answer.md)

| 사례 | 결과 | 관찰한 동작 |
|---|---|---|
| W-T1 | 2/2 PASS | 단건 조사 주제 기록, 새 세션의 본문·출처·가설·미결 회수와 미검수 표시 |
| W-T2 | 2/2 PASS | 초안 선행 없는 Insight 직접 적재와 advisories·show 회수 |
| W-T3 | 2/2 PASS | 이해·개선 행동 분리, 제안 본문 직접 읽기, 상태 필드 미생성·채택 링크 |
| W-T4 | 2/2 PASS | 오래된 가설 대조, 실제 partial·권한·색인 실패 구분과 가능한 조회 지속 |
| W-T5 | 2/2 PASS | 다른 설정 루트, 기존 v1·과거 pending 보존, 정상 기록과 backlog 부재 무생성 |
| W-T6 | 2/2 PASS | 적재 후 실제 stale-SHA, 최신 SHA 복구, 동시 질문 보존, 성공 ingest 각 1회 |
| W-T7 | PASS | 두 번째 설치 변경 배열 모두 비어 있음, 사용자 수정 5개 skipped·보존, overlay 비관리 |

읽기 세션 14개에서 읽을 수 있는 파일 해시와 Git 상태가 전후 같았다. 판정 종료 뒤에도
합성 프로젝트 상태를 재대조했다. 권한 차단 파일의 본문 해시는 아래 한계를 적용한다.

## 회귀 결과

- 전체 pytest: **2527 passed, 174 subtests passed**.
- 설치 ingest runtime unittest: **151 tests, OK**.
- W-T7 installer·스킬 계약: **59 passed, 16 subtests passed**.
- 통합 tip 재병합 확인 후 installer·스킬 계약·구조 문서: **75 passed, 16 subtests passed**.
- 재병합 확인 후 설치 runtime: **151 tests, OK**.

최초 W-T2 두 시도는 합성 환경의 eval/checks·기준 ref 준비 누락으로 최종화가 미완료였다.
이 시도는 통과 집계에서 제외하고 보존했다. 환경 준비를 보완한 별도 프로젝트 두 곳에서
같은 자연어 요청을 재실행했다. 복구된 CLI 인자·출력 경로 오류도 원본 로그에 남겼다.

## 판정 범위

W-T1 최초 기록 세션은 host memory의 관련 지침도 참고했다. 모든 회상과 이후 기록·판정은
memory/hook 비활성으로 실행했다. W-T1 기록 효과에는 이 환경 조건이 포함된다.

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
