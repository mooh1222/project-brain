# 대량 적재 강화 문서 최신화 설계

**상태:** 승인됨  
**작성일:** 2026-07-23  
**대상 저장소:** Project Brain 엔진 `main`

## 목적

2026-07-21~23 대량 적재 강화 작업으로 바뀐 엔진·installer·스킬 계약을 현재 사용자와
유지보수자가 실제로 읽는 문서에 반영한다. 코드와 테스트를 정본으로 삼고, 과거 계획의 당시
명령과 판단 근거는 역사 기록으로 보존한다.

## 문서 정책

문서는 두 종류로 나눈다.

1. **살아 있는 정본 문서**는 현재 동작을 직접 설명하도록 고친다.
   - `README.md`
   - `ROADMAP.md`
   - `docs/design-canonical.md`
   - `docs/search-internals.md`
   - `CLAUDE.md`
   - `src/project_brain/templates/CHANGELOG.md`
2. **날짜가 붙은 설계·계획 문서**는 당시 RED/GREEN 순서와 경로를 다시 쓰지 않는다.
   이번 작업의 실제 완료 상태, 실행 경로 차이, 최종 검증값을 맨 앞의 완료 기록으로 덧붙인다.
   - `docs/specs/2026-07-21-bulk-ingest-hardening-design.md`
   - `docs/plans/2026-07-21-bulk-ingest-hardening.md`

오래된 다른 `docs/specs/`·`docs/plans/`, 비교 보고서, 발표 자료는 이번 변경의 현재 운영
정본이 아니므로 수정하지 않는다. BB2 데이터와 설치본도 이 저장소 문서 작업에서는 수정하지
않는다.

## 갱신 내용

### 사용자·운영 문서

`README.md`에는 다음 현재 계약을 추가한다.

- 논리 key는 완성 객체 ID가 아니라 조립 전 상대 key다.
- 단건은 `run_ingest.sh`, 여러 항목은 `run_ingest_batch.py`로 실행하고 전체 성공 뒤
  semantic finalization을 한 번만 수행한다.
- workflow 최상위 상태가 아니라 항목별 `extract_status=ok`,
  `verify_status=ok`와 기대 개수 일치를 완료 기준으로 쓴다.
- installer는 관리 파일의 생성·갱신·채택뿐 아니라 템플릿에서 퇴역한 파일도 안전하게
  제거한다. 사용자 수정 파일과 프로젝트 overlay는 보존하며, 중단된 퇴역은 rollback한다.

### 엔진 정본·히스토리

`ROADMAP.md`에는 2026-07-22~23 완료 단계를 새로 기록한다. 논리 key 가드, 보수적 raw
청킹, 재개 가능한 batch, semantic finalizer, workflow validator, compact router,
installer 퇴역 정리와 rollback, BB2 실코퍼스 결과를 한 묶음으로 남긴다. 상단 문서 개수와
층별 현황도 현재 파일 수와 기능 상태로 맞춘다.

`docs/design-canonical.md`에는 L4 적재 완료 경계와 installer 소유권 경계를 추가한다.
사용자 판단을 대신하지 않는다는 기존 철학은 유지하고, 엔진이 강제하는 구문·완료·파일
안전 경계만 명시한다.

`docs/search-internals.md`에는 raw 토큰 근사가 ASCII 단어 + 한글 음절 + 기타 비공백 기호의
보수적 합이며, 단일 과대 유닛도 목표 크기 아래로 분할한다는 현재 구현을 기록한다.
실모델의 2,048 토큰 상한과 배치 크기 8의 관계도 코드와 맞춘다.

### 개발·변경 이력

`CLAUDE.md`에는 전체 pytest와 템플릿 unittest를 모두 개발 완료 게이트로 넣고, 실코퍼스
검증 예시를 현재 15개 골든셋 기준으로 고친다. installer 변경 시 퇴역·overlay·멱등
계약을 함께 검증하도록 한다.

`src/project_brain/templates/CHANGELOG.md`에는 기존 2026-07-22 항목의 후속으로 최종
안전 보강을 기록한다. update-rules 소유권 이동, exact workflow gate, report 입력 충돌
차단, 실행 비트 채택, 안전한 퇴역·rollback을 포함한다.

### 완료 증거

`docs/reports/2026-07-23-bulk-ingest-hardening-completion.md`를 만들어 다음을 한 곳에 모은다.

- Task 1~12 결과와 대표 커밋
- Task 9 다섯 행동 시나리오
- BB2 설치본 전파와 프로젝트 overlay 경계
- 실제 코퍼스 7,092 문서·1,577 raw chunk·15/15 eval
- 엔진 611 pytest + 26 subtests, 템플릿 59 unittest
- installer 퇴역 rollback 실패 주입과 최종 품질 승인
- 글로벌 편집 설치와 모델 캐시 운용 주의

## 검증

문서 변경 뒤 다음을 모두 통과해야 한다.

- 상대 Markdown 링크가 실제 파일을 가리키는지 검사
- 현재 정본 문서에서 옛 테스트 수, 옛 골든셋 수, 한글 `/2` 근사, 퇴역 미지원 설명 검색
- `git diff --check`
- `.venv/bin/python -m pytest -q`
- `.venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'`
- `bash -n src/project_brain/templates/ingest/scripts/*.sh`

검증 뒤 문서 커밋을 만들고, fetch로 확인한 `origin/main`에 새 원격 커밋이 없을 때
`main`을 push한다. 기능 worktree와 브랜치는 삭제하지 않는다.
