# Task 18 표시 제목·인용문 부채 완료 보고서

- 완료 기록일: 2026-08-11
- 설계: [2026-08-06 Task 18 재설계](../superpowers/specs/2026-08-06-task18-display-labels-and-quote-debt-redesign.md)
- 계획: [2026-08-06 Task 18 구현 계획](../superpowers/plans/2026-08-06-task18-display-labels-and-quote-debt.md)

## 판정과 문서 경계

attempt-006에서 Task 18의 엔진 구현, BB2 표시 제목 적용, corpus-final
snapshot 검증, engine·BB2 독립 최종 리뷰까지 통과했다. 이 보고서와
ROADMAP은 계획의 Task 13 Step 6에 해당한다.

마지막 closure는 이 두 문서를 독립 리뷰하고 commit한 뒤에만 create-only로 생성·검증한다.
따라서 아래 closure 파일은 이 보고서 작성 시점에 아직 생성하거나 검증하지 않았으며, 이
문서는 closure 완료를 주장하지 않는다.

- `attempt-006/task18-closure.json`
- `attempt-006/task18-closure-verify.json`

## attempt-005 실패와 복구 이력

attempt-005는 모든 gate·apply·post-verify·corpus commit·corpus-final snapshot·
독립 최종 리뷰·완료 문서 commit까지 성공했다. 그러나 그 다음 create-only
closure-create가 descendant ref 계약 위반을 드러내며
`git_ref_invalid: local_ref must be one full refs/ name`으로 한 번 실패했다.
closure-verify는 실행하지 않았다.

엔진 수정 commit `bc2b8de82b0cf31a9b1cea6550cae5981ed4c7b6`이 이 계약을
바로잡았다. BB2는 exact revert 복구 commit
`c924843e1bc80ae1cff9a3efe7fbb16bd793647a`과 canonical v2 restore로 attempt-005
적용 전 corpus 상태에 돌아갔고, attempt-005 주요 산출물 13개는 바이트
단위로 보존됐다. 그 다음 attempt-006이 전체 gate·apply·리뷰 순서를 다시
실행해 아래 결과를 남겼다.

## 고정된 결과와 증빙

| 항목 | 값 |
|---|---|
| engine implementation HEAD | `bc2b8de82b0cf31a9b1cea6550cae5981ed4c7b6` |
| BB2 corpus HEAD | `7ed3cc687fb3ba09fc0f3ebe274cbfc1cd1bd2d5` |
| Task 18 binding SHA-256 | `e839a1ad720eaabcdc80ab726546f792f4ab013ac7cea1811691598751c11e03` |
| binding verify receipt SHA-256 | `5192f358b80f4d81cc60e1e8e45d1a7e8ac99b6ee99d7b74bac5b2da8987ba67` |
| display migration manifest SHA-256 | `f1c74b5b9812703c8c1ca927dd9740bd671349bb015878298422cb6d19e02ff0` |
| post report SHA-256 | `4b68caee2923f1465bb05a18bba4b9c79708e87e589dea6db3c6871ef7855751` |
| corpus-final manifest SHA-256 | `b31dcff4e0be388939578865f08c75adfe09c064ffa08a3eeadaef4f25d7a9e6` |
| corpus-final verify receipt SHA-256 | `6fbbbc664cd25ac9f61b65984c276ee7a1750976fdda4d2b6a4614cf525d3837` |
| quote inventory SHA-256 | `9a815911b0d019d72132e0a1fd4b225a6f66cc99284e36819bea628a4abb140b` |

증빙 경로는 다음과 같다. `<BB2>`는 BB2 저장소 루트다.

- binding: `<BB2>/.snapshots/2026-08-06/task18-execution/attempt-006/task18-binding.json`
- binding verify receipt:
  `<BB2>/.snapshots/2026-08-06/task18-execution/attempt-006/binding-verify.json`
- display manifest:
  `<BB2>/.snapshots/2026-08-06/task18-execution/attempt-006/display-migration.manifest.json`
- post report:
  `<BB2>/brain/recovery/2026-08-06/task18-display-and-quote-debt/display-migration-result.json`
- corpus-final manifest:
  `<BB2>/.snapshots/2026-08-06/task18-execution/attempt-006/corpus-final/manifest.json`
- corpus-final verify receipt:
  `<BB2>/.snapshots/2026-08-06/task18-execution/attempt-006/corpus-final-verify.json`
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
이번 작업에서 backfill하거나 고치지 않았다. legacy 인용문은 적재 당시 검토됐지만
현재 저장 정보만으로 기계 재검증할 수 없는 항목이다. 이를 "검증된 적 없음", 신규 schema
실패, 또는 전체 code quote 검증 완료로 확대 해석하지 않는다.

## 최종 게이트

- `binding-create -> binding-verify -> plan -> verify-plan -> apply`: 각 한 번 실행해 PASS —
  binding verification `ok=true`, `task18_allowed=true`; plan·verify-plan·apply `ok=true`
- `.venv/bin/python -m pytest -q`: PASS — 2,077 passed, subtests 136 passed
- 설치 ingest runtime unittest: PASS — 120 tests, `OK`
- `PROJECT_BRAIN_TASK18_PHASE=post_migration` BB2 checks: PASS — 12 tests, `OK`
- `project_brain.cli audit --no-fetch --no-stale-cache-write`: PASS — `ok=true`, lint 0,
  `cache_written=null`
- BB2 root `project_brain.cli eval`: PASS — 15/15, failed 0
- `project_brain.cli graph export`: PASS — 노드 10,941개, 간선 23,666개
- canonical post-verify: PASS — exact target·title-only·mode·부채·색인·사용자 변경 보존 확인
- corpus-final snapshot create와 `verify_snapshot`: 각각 한 번 실행해 PASS

## 불변 경계와 독립 리뷰

- index DB SHA-256
  `b5aa3b3d846752107f651a2393b4169fdf07a0db82c5f1d47ab1b0e535d381a4`는 적용 전후
  같았다.
- stale-set SHA-256
  `84c02baeac5973ab5396e4278641b4b184110799b646157ddfbd56279b687cef`도 같았다.
- 고정 baseline의 기존 사용자 변경은 engine 15건, BB2 12건이며 내용까지 그대로
  보존됐다. BB2 corpus commit에는 승인된 object 6,491개와 post result receipt 1개만
  들어갔고, commit 직후 staged path는 0개였다.
- engine 독립 최종 리뷰: 전체 branch spec·코드 품질 APPROVED,
  Critical/Important/Minor 0/0/0
- BB2·Task 13 독립 최종 리뷰: 이력·최종 diff·증빙 품질 APPROVED,
  Critical/Important/Minor 0/0/0

이번 최종 적용·문서화 범위에서는 index rebuild, finalizer, install, push, PR을 실행하지
않았다. 완료 문서 작성 중에도 test, migration, snapshot, corpus read/write를 다시 실행하지
않았다.

## 남은 closure 순서

별도 reviewer가 이 보고서와 ROADMAP의 주장·SHA·수치를 승인한 뒤 두 문서만 commit한다.
그 commit의 engine HEAD와 위 BB2 corpus HEAD를 포함해 다음 create-only receipt를 순서대로
만들고 독립 검증한다.

1. `<BB2>/.snapshots/2026-08-06/task18-execution/attempt-006/task18-closure.json`
2. `<BB2>/.snapshots/2026-08-06/task18-execution/attempt-006/task18-closure-verify.json`

두 파일의 생성·검증은 이 문서 commit 이후 단계다.
