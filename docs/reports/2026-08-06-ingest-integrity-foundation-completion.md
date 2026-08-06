# P0 적재 무결성 기반 완료 보고서

- **완료일:** 2026-08-05
- **문서 반영일:** 2026-08-06
- **상태:** Task 0~15 구현·설치·독립 검토 완료
- **엔진 완료 HEAD:** `e84d4ed371a59de158c65beb9c5b05a2e9bef7f1`
- **BB2 runtime 완료 HEAD:** `fbcbc861f9a9b43c3ac483e43b8d706c9c4d2b01`

## 1. 완료 범위

신규 적재가 선언 범위 누락, 공백 필수값, 호출자 임의 lifecycle 시각, build 결과 불일치,
검증되지 않은 CodeLocator 변경을 성공으로 끝내지 못하게 했다. 핵심 흐름은 다음과 같다.

`CoverageContract → notes 대조 → 독립 expected planner → build 대조 → MutationService 단일 쓰기·clock → coverage 결속 receipt → item별 finalizer → foundation gate`

일반 `INGEST`는 coverage 없이 쓸 수 없고 delete·rename·auxiliary update를 허용하지 않는다.
변경 없는 재실행도 expected·verified 객체를 결속한 no-op receipt를 남긴다. batch는 항목별 결과와
resume 상태를 같은 coverage에 묶으며, receipt 게시 경쟁에서 다른 실행의 성공 결과를 지우지 않는다.

기존 legacy 객체는 계속 읽을 수 있다. ingest 당시 검토됐지만 `verified_quote` 같은 과거 계약 정보가
없어 지금 기계적으로 다시 검사할 수 없는 객체는 부채로 구분하며, 이를 신규 객체의 계약 우회로
사용하지 않는다.

## 2. 엔진 검증

최종 엔진 수정은 artifact root의 부모 디렉터리를 task 외부 snapshot 변경으로 오인하던 문제까지
포함한다. artifact 조상만 제외하고 같은 날짜의 형제 파일·디렉터리와 안전하지 않은 경로 변화는
계속 감지한다.

```text
.venv/bin/python -m pytest -q
1808 passed, 127 subtests passed

.venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
Ran 120 tests
OK
```

독립 최종 리뷰는 Critical·Important·새 Minor 없이 통과했다. 기존에 미뤄둔 두 Minor는 이번 P0
실행을 막지 않았다.

- snapshot absent-path 경쟁에서 일부 중간 `os.open()` 오류가 구조화되지 않은 채 나올 수 있음
- 성공 명령이 잘못된 UTF-8 bytes를 출력하면 handoff가 안전하게 실패할 수 있음

## 3. BB2 제한 설치와 비변이 gate

첫 설치가 드러낸 artifact 부모 경로 문제는 실패 산출물을 삭제하지 않고 별도 archive에 보존한 뒤
엔진에서 수정했다. 실패한 BB2 설치 커밋은 원 54개 관리 경로만 되돌렸고, 새 baseline에서 같은
54개 경로를 다시 설치했다. 기존 사용자 modified 9개와 untracked 3개는 stage·commit하지 않았다.

설치본 gate는 다음 여섯 명령을 순서대로 실행했고 모두 성공했다.

1. installed runtime unittest
2. BB2 corpus checks
3. lint
4. `audit --no-fetch`
5. 기존 DB를 사용하는 eval
6. 임시 디렉터리 coverage build dry smoke

finalizer와 index rebuild는 실행하지 않았다. baseline·gate 전후에 corpus objects, raw, index DB,
엔진 핵심 파일, 설치 runtime, 기존 사용자 작업과 artifact 밖 snapshot이 같았다. audit가 관리하는
`brain/.brain-local/stale-set.json`만 허용된 로컬 변경으로 갱신됐다.

## 4. Snapshot과 handoff

P0 rollback snapshot은 11,168개 파일을 담고 실제 manifest와 create·verify receipt의 SHA-256이
모두 다음 값으로 일치했다.

```text
0ec3d3874bcb7fa3b7e41d60b4a7035ddd385e012af899b44a7841c271f4f5a5
```

주요 미추적 완료 증거는 BB2의 `.snapshots/2026-08-05/p0-foundation/`에 있다.

| 증거 | SHA-256 |
|---|---|
| `foundation-baseline.json` | `3046ee056d4fd233a0255f7f26ade78628f069e54d7e6616478edfc3ad828f22` |
| `foundation-gate.json` | `af772f7ebd1a27bc77d17f0d92815ff87fb6bf861a299d1db8e8e3906d2f8cbb` |
| `snapshot-create.json` | `1562acc11bbd606a5a136b8caa8a0e6c31fce5a93b2ba9a307fbcde4aa5bc824` |
| `snapshot-verify.json` | `287dd2c78727f8320741b08a2c9232d0e26d31ffa1ee68d27391ff631f530678` |
| `p0-handoff.json` | `55df01d2ed40aa8bee93ded3df378c3733bb00be30fbc8a8a9da21138590761b` |

handoff는 baseline·gate·snapshot을 다시 교차 확인했고 두 번의 최종 재검사가 정확히 같았다.
Task 18 상태는 `blocked_pending_new_measurement_design_binding`이다.

## 5. 완료 뒤 문서화와 Task 18 경계

위 handoff는 engine `e84d4ed…`, BB2 `fbcbc861…`에서 확정된 P0 완료 증거다. 이 보고서와
`ROADMAP.md` 상태 정정은 handoff 뒤 사용자가 별도로 승인한 문서 작업이므로 그 immutable
handoff를 다시 쓰거나 현재 HEAD용 binding으로 확대하지 않는다.

기존 `2026-08-04-task18-display-labels-and-quote-backlog` 설계·계획·binding은 당시 측정의 역사
자료로 보존한다. 다음 Task 18은 현재 engine·BB2 HEAD, `origin/develop`, 표시 라벨 대상과 quote
backlog를 읽기 전용으로 다시 측정한 receipt에서 새 설계와 계획을 만든다. 사용자 승인, migration
gate 구현, 새 pre-mutation snapshot과 최종 binding 검증 전에는 실코퍼스를 수정하지 않는다.
