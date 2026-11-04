> E3 당시 판정·관찰의 보존 사본이다. W-T1의 두 기록 세션은 개인 memory를 읽었으므로
> 이번 memory 비활성 통과 집계에서는 제외하고 재실행 결과로 교체한다.
> 작은 Markdown 산출물만 추적하며 JSONL·프로젝트·해시 원본은 로컬 전용이다.
> 링크는 추적 산출물로만 연결하고 원본 증거는 경로 텍스트로 표시했다.

# KW-E3 W-T1~W-T7 실행 검증 (#117)

W-T1~W-T6 각각 모든 하위 조건 2/2, W-T7 결정론 설치 조건 PASS다. 분리 판정 두 회차와 summary 연결 재검수까지 종합 PASS로 확인됐다.

- 브랜치: `mooh1222/brain-kw-e3`; 검증 엔진·통합 기준점: `be75896a18efc076150708882c8af453ee970672` (E1 #115 + E2 #116).
- Codex `gpt-6.1-sol`, reasoning `high`, CLI `0.166.0`, Python `3.12.11`. 최종 기록·회상 26개와 독립 판정 2개; 동시 Codex 최대 2개.
- 검색·색인은 StubEmbedder와 regex 토큰화로 실행했다. 실모델 임베딩을 로드하지 않았다.
- [환경·실행 방법](environment.md) · [설치 해시·색인 메타데이터 대조](cross-checks.md) · 버전 (로컬 원본: `versions.txt`).

| 사례 | 1회차 | 2회차 | 핵심 관찰 |
|---|---|---|---|
| W-T1 | [PASS](w-t1/round-1/observations.md) | [PASS](w-t1/round-2/observations.md) | 관찰 1건의 조사 주제를 초안으로 기록하고 새 세션이 선택 본문·출처·가설·미결을 회수, 미검수 표시 |
| W-T2 | [PASS](w-t2-recheck/round-1/observations.md) | [PASS](w-t2-recheck/round-2/observations.md) | 초안 선행 없이 기존 ingest로 reviewed Insight 적재, 새 검색 advisories와 핵심 show로 근거·범위 확인 |
| W-T3 | [PASS](w-t3/round-1/observations.md) | [PASS](w-t3/round-2/observations.md) | 이해와 개선 행동 분리, 제안 본문 직접 회상, 상태 필드 없음, 채택 작업 링크 한 줄 |
| W-T4 | [PASS](w-t4/round-1/observations.md) | [PASS](w-t4/round-2/observations.md) | 오래된 가설과 현재 규칙 구분; healthy 회수 및 partial·접근·색인 실패 실제 발동과 가능한 결과 지속 |
| W-T5 | [PASS](w-t5/round-1/observations.md) | [PASS](w-t5/round-2/observations.md) | 다른 설정 루트·기존 v1 유지, 과거 pending 보존·미검증 회수, 정상 기록 유지와 backlog 부재 무생성 |
| W-T6 | [PASS](w-t6/round-1/observations.md) | [PASS](w-t6/round-2/observations.md) | 적재 후 실제 stale-SHA 발생, 최신 SHA로 보완, 동시 질문·미결·실제 적재 참조 보존, 성공 ingest 각 1회 |

- [1회차 독립 판정: 모든 하위 조건 PASS](judge-1.answer.md) · [2회차 독립 판정: 모든 하위 조건 PASS](judge-2.answer.md). 각 판정자는 상대 회차와 당시 미생성 summary를 완료로 간주하지 않았으며, 이 문서가 양 회차를 연결한다.
- 판정 원본: 1 JSONL (로컬 원본: `judge-1.native.jsonl`) · 2 JSONL (로컬 원본: `judge-2.native.jsonl`). 각 관찰 기록은 입력 요청·실제 명령/종료 상태·답변과 출처/검수 표시·기존 native JSONL·조회 전후 해시/Git를 연결한다.
- 읽기 14개 세션에서 읽을 수 있는 파일 해시와 Git 상태가 전후 같았다. 판정 세션 종료 뒤 12개 프로젝트의 상태도 재대조해 동일함을 확인했다. 권한 차단 파일의 별도 한계는 아래에 명시한다.

## W-T7 연결과 현 브랜치 재확인

- E1의 기존 W-T7 증거 요약 (로컬 원본: `/Users/al03040455/.copilot/session-state/546d51f6-df99-4c46-976e-9a9678a9ca55/files/brain-kw/evidence/kw-e1-w-t7/summary.md`).
- 현 브랜치 재확인 report (로컬 원본: `w-t7-current/reports.json`) · 실행 로그 (로컬 원본: `w-t7-current.log`) · 상대 참조 8개 확인 (로컬 원본: `w-t7-current/relative-links.json`) · 실행 스크립트 (로컬 원본: `w-t7-check.py`).
- 깨끗한 두 번째 설치의 created/updated/removed/adopted/skipped가 모두 빈 배열이다. 네 SKILL과 공통 reference의 사용자 수정 5개를 보존하고 skipped 5개로 보고했다. overlay는 manifest 비관리이며 기존 pending bytes도 보존했다. backlog는 생성하지 않았다. skipped는 새 지침 적용 성공으로 집계하지 않았다.

## 회귀

- 전체 pytest (로컬 원본: `pytest-full.log`): **2527 passed, 174 subtests passed** (635.23s).
- 최초 installer·스킬 계약 (로컬 원본: `w-t7-pytest.log`): **59 passed, 16 subtests passed**.
- 설치 ingest runtime (로컬 원본: `runtime-unittest.log`): **151 tests, OK**.
- 통합 tip 재병합 확인은 Already up to date (로컬 원본: `final-merge.txt`). 이후 installer·스킬 계약·구조 문서 (로컬 원본: `final-pytest-targeted.log`) **75 passed, 16 subtests passed**, runtime 재확인 (로컬 원본: `final-runtime-unittest.log`) **151 tests, OK**.
- 엔진 코드·설치 템플릿 수정은 없다. 합성 데이터 밖의 소비 프로젝트·실코퍼스·전역 설치는 변경하지 않았다.

## 보존한 실패와 판정 한계

- 최초 W-T2 두 시도는 합성 환경의 eval/checks·기준 ref 누락으로 최종화 미완료였다. [최초 1](w-t2/round-1/observations.md) · [최초 2](w-t2/round-2/observations.md)를 보존하고 통과 집계에서 제외했다. 환경 준비를 보완한 별도 초기 프로젝트 두 곳에서 같은 요청을 다시 실행했다. 실행 중 복구된 CLI 인자·출력 경로 오류도 원본 로그에 남겼다.
- W-T1 최초 기록 세션은 host MEMORY.md의 관련 지침도 참고했다. 회상 세션 전체와 이후 기록·판정은 memory/hook 비활성으로 실행했다. W-T1 기록의 효과에는 이 환경 조건이 포함된다.
- W-T4 mode 000 파일의 실제 Permission denied와 권한 유지·쓰기 명령 부재를 확인했다. 전후 해시 목록은 PermissionError이므로 해당 파일 본문을 직접 재해시해 동일성을 증명한 결과는 아니다. `.git` 내부·`__pycache__`는 본문 해시 대상에서 제외하고 Git 상태는 별도 비교했다.
- W-T6는 실제 공개 SHA 갱신 두 호출을 교차시켜 stale-SHA를 발생시킨 결정론 주입이다. 독립 OS 프로세스 병렬 스트레스 검증은 실행하지 않았다.
- 2회차 판정자는 W-T4 답변의 “변경 이력은 미적재” 표현이 query 결과만으로 증명되지 않는다고 지적했다. 이 증거가 확인한 범위는 해당 질의에서 이력을 회수하지 못했다는 것이다. 과거 5회가 현재 3회로 실제 변경됐다는 결론은 두 회차 모두 내리지 않았다.
- CLI startup의 marketplace 자동 갱신 오류가 로그에 있다. 과제 명령의 외부 원격 서비스 호출과 구분한다. 두 판정자 모두 현재 증거에서 KW 범위 템플릿 결함에 의한 기능 실패를 식별하지 않았다.
- 작업 진입 최초 git status에는 변경이 없었다. 파일로 저장한 engine-status.txt는 evidence 디렉터리를 만든 뒤의 스냅샷이며 `?? .scratch/`를 포함한다. tracked diff는 비어 있었다. 결과 보고서만 선택적으로 커밋하며 evidence는 로컬에 보존한다.
- 이 결과는 고정 모델·환경·자연어 요청의 재현 증거다. 다른 모델·표현 전체의 성공률, 실제 앱·장치·서버 동작, 독립 프로세스 경합까지 일반화하지 않는다.

## 종합 판정

[기존 독립 판정 세션의 종합 재검수](judge-overall.answer.md)는 필수 증거 누락이나 추가 기능 실패 없이 **종합 PASS**로 판정했다. 원본 JSONL (로컬 원본: `judge-overall.native.jsonl`)과 [재검수 요청](judge-overall.request.md)을 보존한다. 양 회차 원본 대조, E1 해시 일치, summary 당시 로컬 링크 32개 실존을 확인했다. W-T4 원답의 과도한 이력 표현과 환경·증거 한계는 위에 그대로 공개한다.

결과 보고서 커밋: `4582d1e6e3b3ae6388a445a58047ea57a0347453`. 엔진 코드·템플릿을 바꾸지 않은 로컬 보고서 커밋이며 push·main 이동·tag·release·issue close는 수행하지 않았다.
