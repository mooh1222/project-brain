# KW 통합 code-review 수정 재검증 (#115·#117)

W-T1·W-T3는 각각 모든 하위 성공 조건 **2/2 PASS**다. 기록·회상과 분리한 Codex 판정
두 개가 회차별 실제 저장·본문 회수·답변·전후 상태를 확인했다. 기존 W-T1 두 기록 세션은
개인 memory를 읽었으므로 이번 집계에서 제외하고 아래 신규 실행으로 교체한다.

- 기준 HEAD `4582d1e6e3b3ae6388a445a58047ea57a0347453`, branch `mooh1222/brain-kw-fix`.
- Codex CLI 0.166.0, `gpt-6.1-sol` high. 기록·회상 8개 세션과 분리 판정 2개, 동시 최대 2개.
- 전 과정 memory·hook 비활성. 실제 세션 메타데이터의 `memory_mode=disabled`, 실제 모델·effort·CLI를 확인했다.
- StubEmbedder·regex, 실모델 로드 차단. 합성 프로젝트만 수정했고 소비 프로젝트·실코퍼스·전역 설치는 변경하지 않았다.

| 사례 | 1회차 | 2회차 | 관찰 |
|---|---|---|---|
| W-T1 | [PASS](w-t1/round-1/observations.md) | [PASS](w-t1/round-2/observations.md) | 단일 관찰의 조사 주제, 새 세션 발견·항목 본문·출처·가설·미결 회수, 미검수 표시 |
| W-T3 | [PASS](w-t3/round-1/observations.md) | [PASS](w-t3/round-2/observations.md) | 지식·개선 행동 분리, 제안 본문 직접 읽기, 실행 미확정·채택 링크·현재 확인 한계 구분 |
| W-T7 | [PASS](w-t7.md) | 결정론 1세트 | 두 번째 설치 5개 변경 배열 모두 빈 배열, 사용자 수정 5개 skipped·보존, overlay·기존 pending 보존 |

- [1회차 독립 판정](judge-1.answer.md), [2회차 독립 판정](judge-2.answer.md).
- [환경](environment.md), [설치본·조회 상태 교차 확인](cross-checks.md), [판정자 신원 후속 대조](judge-identity.md).
- 조회 4개 세션의 전후·현재 파일 해시와 Git 상태가 모두 일치한다. `.git` 내부·`__pycache__`는 본문 해시에서 제외하고 Git 상태는 따로 대조했다.
- 현재 템플릿과 설치 파일 66개씩의 해시가 네 프로젝트에서 일치한다. 임베딩 안내는 정본 하나이고 설치 후 query 상대 링크와 앵커가 유효하다.
- P3의 3라운드 뒤 미합의 후보 규칙은 공통 reference의 초안 미결·세션 보고 분기로 보완했다. 이번 W-T1/W-T3는 영향 사례의 기록·회상 회귀이며, 실제 사용자와의 3라운드 대화를 실행한 검증은 아니다.

작은 Markdown 판정·관찰·요청·답변과 회귀 로그는 이 디렉터리에 추적한다. JSONL·합성
프로젝트·설치 해시·조회 전후 원본은 로컬 전용 `.scratch/brain-knowledge-workflow-validation/20261104-review-fix/`에 보존하며 링크하지 않는다.
`source-sha256.json`은 링크 정규화 전 원본 산출물의 해시다.

## 보존한 오류와 한계

- 판정 준비의 시스템 Python numpy import와 스크립트 파일명 import 오류는 실제 Codex 호출 전에 종료했다. `preparation-errors.md`와 원래 hc 화면·종료 상태(`preparation-t2g/t2h/t2j/t2k-*.log`)를 보존했다. 기능 실패·통과 세션으로 세지 않는다. 판정자는 원래 실패 화면을 캡처하기 전에 검수했으므로 답변에 당시 한계를 남겼다.
- 2회차 판정자는 자기 세션의 native 메타데이터가 지정 증거에 아직 없음을 NOT_EXECUTED로 표시했다. 종료 후 실행 담당자가 두 판정 native의 실제 모델·effort·CLI·memory disabled를 확인했다. 판정 답변 원문을 고쳐 해당 한계를 숨기지 않는다.
- CLI startup의 기존 bb2-agent-env marketplace 갱신 오류는 native에 남아 있다. 로컬 스킬 기록·회상은 exit 0이다. 프로젝트 밖 갱신 시도·임시 patch 잔존까지 전역 파일시스템 무변경으로 확대하지 않는다.
- 1회차 W-T3는 기록 전 부재한 백로그를 읽어 exit 1이었고, 허용된 기록 단계에서 생성한 뒤 회상했다. 조회 실패를 기록 부재로 오인한 사례는 아니다.
- 고정한 합성 환경·요청·모델의 재현 결과다. 다른 모델·표현이나 실제 앱·장치·서버 동작의 성공률을 보장하지 않는다.
- 기존 W-T2·W-T4~W-T6은 이전 기준점의 E3 증거를 유지하며 이번에 재실행하지 않았다. 기존 E3의 W-T1 판정을 신규 memory 비활성 근거로 사용하지 않는다.

## 현재 회귀 결과

- 전체 pytest (로컬 원본: `pytest-full.log`): **2527 passed, 174 subtests passed**, exit 0 (604.74s).
- 설치 runtime unittest (로컬 원본: `runtime-unittest.log`): **151 tests, OK**, exit 0.
- 통합 tip 병합 확인 후 스킬 계약·installer·구조 문서: **94 passed, 16 subtests passed**.
- 설치 상대 참조 검사 (로컬 원본: `installed-reference-check.log`): query → ingest-tools 링크·앵커, 임베딩 안내 단일 정본, P3 미합의 후보 처리, 두 번째 install 무변경 PASS.
- git diff --check PASS. W-T7과 소비 프로젝트 설치는 합성 대상에서만 실행했으며 실코퍼스 회귀·rebuild는 수행하지 않았다.
