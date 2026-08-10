# Task 18 표시 제목·인용문 부채 완료 보고서

- 완료 기록일: 2026-08-11
- 설계: [2026-08-06 Task 18 재설계](../superpowers/specs/2026-08-06-task18-display-labels-and-quote-debt-redesign.md)
- 계획: [2026-08-06 Task 18 구현 계획](../superpowers/plans/2026-08-06-task18-display-labels-and-quote-debt.md)

## 판정과 문서 경계

Task 18의 엔진 구현, BB2 표시 제목 적용, corpus-final snapshot 검증, engine·BB2 독립 최종
리뷰까지 통과했다. 이 보고서와 ROADMAP은 계획의 Task 13 Step 6에 해당한다.

마지막 closure는 이 두 문서를 독립 리뷰하고 commit한 뒤에만 create-only로 생성·검증한다.
따라서 아래 closure 파일은 이 보고서 작성 시점에 아직 생성하거나 검증하지 않았으며, 이
문서는 closure 완료를 주장하지 않는다.

- `attempt-005/task18-closure.json`
- `attempt-005/task18-closure-verify.json`

## 고정된 결과와 증빙

| 항목 | 값 |
|---|---|
| engine implementation HEAD | `5e08dc09514dd4961c7b211ab1a494884390b6aa` |
| BB2 corpus HEAD | `0e2a19e6ffad2f759890112d0efdb10e5fe2e051` |
| Task 18 binding SHA-256 | `a4cad18061dd29854db81d4adaca708114d65bf723ddfa881fc905f37f057229` |
| binding verify receipt SHA-256 | `680cc802b58a43f35d7e171cc5f0c0f8b66a0cfaeb3dbe97f7fba8eb2211fda8` |
| display migration manifest SHA-256 | `2c8c1f66a86ebe37ddffbd8bbf46d7a05e917de632a112cb4e64d09fb74a069a` |
| post report SHA-256 | `cd5efaf5eec6a61bf6e98cb888bef6d4e16c396d2c5ce0f95f57c24e863900ad` |
| corpus-final manifest SHA-256 | `dc8290bdc38fedb2a486370ee6109982728225f0ce26fb198cf0e30db88cc009` |
| corpus-final verify receipt SHA-256 | `6ce94ad4bd43196ea8b5f37d818af537518b30d74db9134f16a51330fe4ef2dc` |
| quote inventory SHA-256 | `9a815911b0d019d72132e0a1fd4b225a6f66cc99284e36819bea628a4abb140b` |

증빙 경로는 다음과 같다. `<BB2>`는 BB2 저장소 루트다.

- binding: `<BB2>/.snapshots/2026-08-06/task18-execution/attempt-005/task18-binding.json`
- binding verify receipt:
  `<BB2>/.snapshots/2026-08-06/task18-execution/attempt-005/binding-verify.json`
- display manifest:
  `<BB2>/.snapshots/2026-08-06/task18-execution/attempt-005/display-migration.manifest.json`
- post report:
  `<BB2>/brain/recovery/2026-08-06/task18-display-and-quote-debt/display-migration-result.json`
- corpus-final manifest:
  `<BB2>/.snapshots/2026-08-06/task18-execution/attempt-005/corpus-final/manifest.json`
- corpus-final verify receipt:
  `<BB2>/.snapshots/2026-08-06/task18-execution/attempt-005/corpus-final-verify.json`
- quote inventory:
  `<BB2>/brain/recovery/2026-08-06/task18-display-and-quote-debt/legacy-quote-debt-current-develop.json`

`corpus-final/manifest.json`은 version 2, 파일 11,168개와 모든 파일의 mode를 기록한다.
검증 receipt는 `ok=true`이며 위 engine·BB2 HEAD, 같은 파일 수, corpus fingerprint
`0a4ae10dcfbc21fef2696886fe409c109e729fa4a7b6639f2953673912c9a6e3`를 결속한다.

## 적용 결과

- UPDATE 6,491건: CodeLocator 3,305건 + EvidenceRef 3,186건
- create/delete/rename/auxiliary update: 모두 0건
- paired closure: 3,202쌍, mismatch 0건
- 바뀐 필드: `title`만 6,491건
- 객체 수: 10,941개로 불변
- 인용문 부채: 3,307건으로 불변
- 비정본 symbol: 289건으로 불변
- lifecycle timestamp, path, commit SHA, locator 좌표, 인용문, 참조 그래프: 불변
- v2 pre-mutation snapshot과 적용 뒤 live object의 path·file mode: 전부 일치

인용문 부채 3,307건과 비정본 symbol 289건은 재현 가능한 목록으로 고정하고 그대로 보존했다.
이번 작업에서 backfill하거나 의미를 바꾸지 않았다. legacy 인용문은 적재 당시 검토됐지만
현재 저장 정보만으로 기계 재검증할 수 없는 항목이다. 이를 "검증된 적 없음", 신규 schema
실패, 또는 전체 code quote 검증 완료로 확대 해석하지 않는다.

## 최종 게이트

- `binding-create -> binding-verify -> plan -> verify-plan -> apply`: 각 한 번 실행해 PASS —
  binding verification `ok=true`, `task18_allowed=true`; plan·verify-plan·apply `ok=true`
- `.venv/bin/python -m pytest -q`: PASS — 2,076 passed, subtests 136 passed
- 설치 ingest runtime unittest: PASS — 120 tests, `OK`
- `PROJECT_BRAIN_TASK18_PHASE=post_migration` BB2 checks: PASS — 12 tests, `OK`
- `project_brain.cli audit --no-fetch --no-stale-cache-write`: PASS — `ok=true`, lint 0,
  `cache_written=null`
- BB2 root `project_brain.cli eval`: PASS — 15/15, failed 0
- `project_brain.cli graph export`: PASS — 노드 10,941개, 간선 23,666개
- canonical post-verify: PASS — exact target·title-only·mode·부채·색인·사용자 변경 보존 확인
- corpus-final snapshot create와 `verify_snapshot`: 각각 한 번 실행해 PASS

최종 graph SHA-256은
`7108fea4e67ea7818a64f75caa8ecdcf78e5208600de06a4d254947f609bffac`이다.

## 불변 경계와 독립 리뷰

- index DB SHA-256
  `b5aa3b3d846752107f651a2393b4169fdf07a0db82c5f1d47ab1b0e535d381a4`는 적용 전후
  같았다.
- stale-set SHA-256
  `84c02baeac5973ab5396e4278641b4b184110799b646157ddfbd56279b687cef`도 같았다.
- 고정 baseline의 기존 사용자 변경은 engine 15건, BB2 12건이며 내용까지 그대로
  보존됐다. BB2 corpus commit에는 승인된 object 6,491개와 post result receipt 1개만
  들어갔고, commit 직후 staged path는 0개였다.
- engine 독립 최종 리뷰: 설계·spec PASS, 코드 품질 PASS, Critical/Important/Minor 0/0/0
- BB2·Task 13 독립 최종 리뷰: 설계·spec PASS, 증빙 품질 PASS,
  Critical/Important/Minor 0/0/0

이번 최종 적용·문서화 범위에서는 index rebuild, finalizer, install, push, PR을 실행하지
않았다. 완료 문서 작성 중에도 test, migration, snapshot, corpus read/write를 다시 실행하지
않았다.

## 남은 closure 순서

별도 reviewer가 이 보고서와 ROADMAP의 주장·SHA·수치를 승인한 뒤 두 문서만 commit한다.
그 commit의 engine HEAD와 위 BB2 corpus HEAD를 포함해 다음 create-only receipt를 순서대로
만들고 독립 검증한다.

1. `<BB2>/.snapshots/2026-08-06/task18-execution/attempt-005/task18-closure.json`
2. `<BB2>/.snapshots/2026-08-06/task18-execution/attempt-005/task18-closure-verify.json`

두 파일의 생성·검증은 이 문서 commit 이후 단계다.
