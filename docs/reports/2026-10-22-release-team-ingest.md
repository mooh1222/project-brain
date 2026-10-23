# Release 팀 적재 #113 — 로컬 실행 및 인계

상태(2026-10-23): **E1 완료, E2 완료, E3 게시·다운로드 artifact 검증 완료**.
소비 프로젝트의 최종 통합은 별도 작업이다.

## 실행 경계

E1/E2 기준 HEAD는 `7031619a02ce77d000a2d8c4c9dc189cc38b6eea`다. 기존 untracked
문서·스펙·발표자료를 보존하고, E3에서는 별도 작업 트리에 #113 소유 25개 파일만 이관해
승인된 로컬 commit과 정식 artifact build·격리 smoke를 수행했다. 원본 작업 트리는 수정하지
않았다. 처음에는 원격 작업을 보류했고, 후속 사용자 승인으로 작업 branch·main·tag·release를
게시하고 다운로드 artifact를 검증했다. 이슈 종료는 해당 검증 뒤 기록한다. 소비 프로젝트는
수정하지 않으며 실데이터 대신 합성 Git 소비자만 검증한다.

## E1 관측

게시 v0.1.0을 다운로드해 checksum을 확인하고 Git 저장소 밖 별도 uv tool 디렉터리에
wheel + constraints로 설치했다. 프로세스에서 PYTHONPATH/PYTHONHOME/VIRTUAL_ENV/
UV_PROJECT_ENVIRONMENT를 제거했다. 실제 import는
`<isolated>/tools/project-brain/lib/python3.13/site-packages/project_brain/__init__.py`.
개발 venv·editable·전역 설치를 사용하지 않았다.

- wheel SHA256: `a40980c64ba0b4c27810497fb3b9b8333d307ac56c9b527f7b2029adf5df8ae5`
- constraints SHA256: `f51f915a3dc1be9c817debc41a42d4d374beb18e9803eb76aedb4bb715d40425`
- 공개 출처: <https://github.com/mooh1222/project-brain/releases/tag/v0.1.0>

| 공개 경로 | 종료 | 관측 |
|---|---:|---|
| `project-brain install --target <consumer> --project demo --repo demo --default-branch main` | 0 | 설치 runtime 생성 |
| `run_ingest_batch.py batch.json --report batch-report.json` | 1 | `execution_state_invalid` → `not_git_repo`; 실제 import 위치의 Git 탐색에서 실패, 적재 전 |
| `run_ingest.sh --defer-finalize <mutation context> verify.json domain.py` | 0 | context 1개 canonical receipt 적재. batch Git identity 검사가 없는 별도 경로 |
| `project-brain audit --no-fetch` | 0 | 합성 `origin/main` ref 준비 뒤 성공. 엔진 checkout 필요 없음 |
| `project-brain session list --transcript-root <synthetic>` | 0 | 엔진 checkout 없이 scan 경로 실행. 실제 transcript 해석은 스킬 책임. 정식 적재는 sibling ingest 경로 공유 |
| JSON v2 파일이 있는 `draft list` / `draft show topic` | 0 / 1 | list 누락 / `draft_not_found`; v0.1.0의 실제 기능 누락 확인 |
| `validate_foundation.py baseline <isolated paths>` | 1 | 별도 P0 프로젝트 설정 계약에서 거부 |
| foundation identity helper 직접 호출 | 1 | `engine_identity_unavailable` / `git_head_invalid`; 일반 batch/audit의 필수 호출이 아님 |

일반 finalizer는 index/lint/eval/graph/audit/corpus checks/recall을 호출한다. Foundation을
호출하지 않는다. 최초 실험의 잘못된 batch 옵션과 합성 origin ref 누락은 바로잡아 다시
검증했으며 위 표는 수정된 실제 호출 결과다. 원시 로컬 로그는 ignored `dist/113-e1/`의
location.json이 가리키는 격리 디렉터리에 있다. 공개 자료에 로컬 경로나 실제 데이터를 넣지 않는다.

## E1 확정 계약

버전은 안내용이다. release build가 커밋된 archive에서 source commit, version,
패키지 전체 파일의 SHA256·실행 비트를 담은 신원 파일을 만든다. 신원 digest는 이 목록과
출처의 canonical JSON 해시다. wheel SHA256/constraints는 기존 배포 checksum이 묶고,
설치 smoke는 실제 설치 bytes를 wheel과 대조한다. 신원은 서명이나 신뢰할 출처의 대체물이 아니다.

새 release batch manifest에는 `engine_sha`(원본 commit, 기존 의미 유지)와
`engine_identity`(release 내용 신원)를 함께 선언한다. 실제 로드 위치와 패키지 내용,
설치 runtime을 시작·각 item·쓰기 직전·finalizer 전후에 재검증한다. 이 신원은 item binding과
기존 durable intent/journal에 그대로 들어가며 canonical receipt 자체의 계산식은 유지한다.
소비 코드 revision, coverage, 입력 bytes, root 경로/device/inode 결속은 바꾸지 않는다.

| 입력/실행 | 새 실행 | 완료 report 재검증 / 부분 재개 |
|---|---|---|
| 기존 checkout manifest + 같은 checkout HEAD/root | 기존 계약 유지 | 기존 계약 유지 |
| legacy manifest/receipt + release 설치 | 증명 불가, 무쓰기 거부 | 증명 불가, 무쓰기 거부; 원본 보존 후 새 실행 준비 |
| 새 release 신원 + 동일 내용/commit/runtime/root | 허용 | durable receipt 검증 후 완료 item 건너뜀; pending만 실행 |
| 같은 version이나 다른 파일/실행 비트/commit | 거부 | 거부 |
| release 신원과 CLI가 로드한 엔진 불일치 | 쓰기 전 거부 | 거부 |
| 입력/coverage/소비 revision 변경 | 기존 결속에 따라 거부 | 거부 |
| 엔진이 단계 사이 변경됨 | 다음 경계에서 거부 | 원본 신원 복원 없이는 거부 |
| 소비 경로·brain inode 또는 엔진 설치 root/inode 변경 | 새 실행만 준비 가능 | 증명 불가, 거부; receipt 수기 패치 금지 |
| pre-coverage 역사 binding | 신규 쓰기 불가 | 기존 명시적 읽기 전용 recovery만 유지 |

기존 실행 의미를 바꾸거나 자동 이관하지 않는다. 새로운 release 형식만 추가하므로 사용자
정책 선택은 남지 않았다. 설치 runtime 불일치는 갱신 안내와 함께 쓰기 전에 거부하고,
installer가 건너뛴 사용자 파일을 강제 덮어쓰지 않는다.

## 범위 검수 영수증

검토 대상: #113 E1 identity 계약. 완료산출물: 고정 release만으로 일반 팀 적재를 하고
결속 오류를 무쓰기 거부하는 엔진. 첫 사용 가능 결과: E2의 합성 공개 batch 성공/거부.
결과 반례: 같은 버전의 다른 bytes를 허용하면 실제 로드 동일성이 깨지므로 통과 불가.
추가 의무 연결/소유 확인: artifact 신원 파일·binding의 선택적 release 필드·읽기 전용 신원
출력은 실제 공개 호출의 선언/검증에 필요하다. 기존 receipt lifecycle과 installer를 재사용한다.
제외 목록: foundation 개편, 일반 migration release 지원, registry/서비스, 자동 legacy 이관,
소비 실코퍼스 변경. 허용 불완전성: 증명 불가 재개 거부와 미게시 로컬 검증.
계약 공백: 없음. 기존 사용자 정책을 바꾸는 선택 없음.
이 제외 목록과 허용 불완전성은 후속 설계·검수·입장 판정의 기준 계약이며, 제외 항목의
재포함에는 현재 요청과의 연결 근거가 필요하다.

## E2 구현·검수

- release content 신원은 `engine_identity.py`, 실제 실행 코드 관측은 release 전용
  `__init__.py` bootstrap이 소유한다. checkout에는 관측 hook을 추가하지 않는다.
- 새 `ReleaseBatchBinding`만 content 신원과 engine root device/inode를 추가한다.
  기존 binding 직렬화·canonical mutation/no-op receipt·역사 recovery 형식은 유지한다.
- runner/실제 PATH CLI/runtime/MutationService 쓰기 경계와 session marker에 검증을 연결했다.
  설치된 helper는 timestamp 기반 `.pyc` 대신 source를 직접 실행한다.
- 모든 item이 terminal인 release report 재개는 이미 생성된 index/audit 파생물을 허용하는
  `post_gate_object_tail` 검증 후 semantic gate를 다시 실행한다. 부분 적재에는 strict 검증을
  유지한다. 보고서의 완료 flag만 믿고 gate를 생략하지 않는다.
- TDD로 content/mode/extra-file 오류, 신원 보존·재실행, 실제 메모리의 구 코드와 복원된 source,
  캐시 삭제/교체, 설치 runtime stale-cache 반례를 red→green으로 확인했다.
- Standards/Spec 독립 검수에서 메모리 코드/디스크 캐시 혼동, runtime stale-cache,
  PATH CLI 불일치의 baseline 선쓰기를 발견해 수정했다. 두 축 잔여 finding 0건이다.

## E1/E2 검증 결과

| 검증 | 결과 |
|---|---|
| 엔진 전체 pytest | 2,410개 + subtest 174개 통과, 536.62초 |
| 설치 ingest runtime unittest | 151 통과 |
| installer 표적 | 사용자 수정 skip, overlay 비관리, 실행 비트 채택, 퇴역·rollback 회귀 통과 |
| 격리 설치 smoke | 실제 import가 전용 tool site-packages, 설치 RECORD와 wheel 일치, constraints 일치 |
| 현재 소스 대 후보 wheel | 패키지 파일 129개 SHA256·실행 비트 일치, mismatch 0 |
| installer 2회 | 65개 관리 파일, 두 번째 created/updated/removed/adopted/skipped 모두 `[]` |
| 새 공개 batch | 중단 없는 새 batch + canonical receipts + semantic finalization 성공 |
| 부분 실행 | 첫 item 성공 뒤 엔진 변경으로 둘째 거부; 원본 복원 뒤 receipt를 보존해 재개 |
| finalizer 중단 | semantic check 실패 뒤 두 terminal receipt 보존, 원인 복구 후 재개 성공 |
| 정상 재실행 | 같은 receipt·객체 bytes 유지, semantic gate 재검증 성공 |
| 무쓰기 거부 | 잘못된 신원/PATH CLI/runtime, legacy 증명 불가, 입력/소비 revision 변경, 변경된 엔진 재개; Brain 전체 파일 hash 동일 |
| 조회·초안·세션 | audit, search→show, JSON v2 create/list/show/update/prepare, session list/complete/replay 성공 |

최종 필수 명령은 이 checkout의 `PYTHONPATH`와 `.venv/bin/python`을 고정했다:

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest -q
PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
```

E2 검수 최종 결과: Standards 0건 / Spec 0건. 당시 모든 수정은 unstaged로 보존했고,
아래 E3 단계에서 동일 bytes·mode를 확인한 뒤 지정한 25개 파일만 로컬 커밋했다.

합성 소비자 smoke는 `tools/release_consumer.py`가 수행하고 `tools/release.py smoke`에도
연결했다. StubEmbedder와 정규식 tokenizer만 사용했다. 실제 소비 데이터·실모델 rebuild/eval은
실행하지 않았다. 변경은 저장 객체나 검색 입력을 바꾸지 않으므로 change-map상 불필요하다.
ignored `dist/113-validation/`에 게시 v0.1.0 재현 로그, local wheel smoke, 후보 artifact와
checksums를 보관한다. 이 경로의 원시 로그는 로컬 점검용이며 원격 게시 대상이 아니다.

## E3 커밋 기준 로컬 빌드와 소비자 인계 경계

다음 minor 버전은 additive release binding과 JSON v2 기능을 담는 **v0.2.0**이다.
[설치·runtime 갱신·호환표](../releases/v0.2.0.md)에 로컬 검증 artifact의 해시를 기록했다.
로컬 단계의 상태는 **committed local build verified; unpublished**였으며, 아래 게시·다운로드
검증을 마친 뒤 E3 완료로 전환했다.

빌드 source commit: `c43c46f2e35b7a9b0ecf4d92c7e516d74319e994`.
이 커밋의 25개 task-owned 파일은 E1/E2 최종 소스 manifest의 bytes·mode와 모두 일치한다.
새 엔진 동작은 추가하지 않았다. 전체 pytest 2,410개 + subtest 174개의 기존 E2 결과는
`prior-validation-summary.json` 및 복원 동일성 확인 `restore-verification.json`을 근거로
재사용했다. 현재 작업 트리의 소스는 `PYTHONPATH`로, interpreter는 원본 엔진의
`.venv/bin/python`으로 함께 고정해 다음 검사를 새로 실행했다.

| 현재 E3 검사 | 결과 |
|---|---|
| release / identity / installer 표적 pytest | 82개 + subtest 18개 통과 |
| 설치 ingest runtime unittest | 151개 통과 |
| 정식 `tools/release.py build --tag v0.2.0` | clean tracked HEAD를 archive한 wheel·constraints·checksum 생성 |
| wheel 신원 | 실제 nonzero source commit 일치, 패키지 파일 129개 포함 |
| 격리 `tools/release.py smoke --tag v0.2.0` | 전용 tool site-packages import, wheel RECORD·constraints 일치 |
| installer 2회 | 65개 관리 파일, 두 번째 5개 변경 배열 모두 `[]` |
| 새 공개 batch / 재실행 | canonical receipt 성공, replay에서 객체·receipt 보존 |
| 부분 실행 / finalizer 실패 복구 | 원본 엔진 복원 뒤 pending 재개, 기존 receipt 보존 |
| 거부 경로 | 잘못된 identity/PATH CLI/runtime, legacy 증명 불가, 변경된 엔진·입력·소비 revision 거부 및 Brain hash 보존 |
| 공개 조회·초안·세션 | audit, search→show, JSON v2 create/list/show/update/prepare, session list/complete/replay 성공 |

첫 runtime 실행에서는 새 작업 트리에 `.venv/bin`이 없어 fixture의 `#!/usr/bin/env python3`가
시스템 Python을 선택했고 `tree_sitter` import 실패로 CLI fixture 3개가 실패했다. 제품 코드는
바꾸지 않았다. 원본 `.venv/bin`을 PATH에도 명시한 전체 runtime 재실행은 151개 모두 통과했다.
최초 실패 로그와 원인 report도 보존했다.

| 로컬 artifact | SHA256 |
|---|---|
| wheel | `f6ec9863d872c95c9385aa51efe8663b2fa2bcc7cf0ceea6b5b90de7a7a5fd3a` |
| constraints | `f51f915a3dc1be9c817debc41a42d4d374beb18e9803eb76aedb4bb715d40425` |
| SHA256SUMS | `7ec191e96769238ef65f7408649f20460bf4328e5f07b5dbf5939a469537bac2` |
| package content identity | `6242d595b4607ca8199edf3d968563fff8b54bcb0de1d23d0f4ba194017e474a` |

과거 all-zero source commit의 합성 후보는 이 artifact가 아니며 인계 대상에서 제외한다.
위 source commit을 실제 빌드한 뒤 이 보고서와 release 안내만 별도 문서 커밋에서 갱신한다.
문서 커밋의 HEAD를 wheel의 source commit으로 바꾸거나 자기참조 커밋을 만들지 않는다.

원시 로그와 artifact는 저장소 밖 로컬 실행 디렉터리의 `release-v0.2.0/` 아래 보존했다.
통합 작업 트리의 ignored `dist/113-e3/`에도 같은 파일을 복사해 인계한다:
`build.json`, `build.stderr.log`, `targeted-pytest.log`, `runtime-unittest.log`,
`runtime-initial-failure-detail.json`, `runtime-unittest-with-venv-path.log`, `smoke.json`,
`smoke.stderr.log`, `smoke-subprocess.jsonl`, `wheel-release-identity.json`,
`artifact-identity-summary.json`, `restore-verification.json`, `v0.2.0/`.
`smoke-subprocess.jsonl`은 공개 명령별 stdout/stderr·종료 코드와 Python 경로 환경 제거 여부를
기록한다. 격리 소비자에서 editable·PYTHONPATH·PYTHONHOME 혼입은 없었고 StubEmbedder·정규식
주입만 사용했다. 전역 설치·실모델·실코퍼스 실행은 하지 않았다.

### E3 게시와 다운로드 검증

후속 사용자 승인으로 integration branch를 push하고 원격 `main`에 fast-forward로 반영했다.
원본 `main` checkout의 기존 36개 dirty/untracked 파일은 bytes·mode·심링크 종류가 모두
시작 상태와 일치한다. 이를 보존하기 위해 원본 checkout의 로컬 `main`은 이동하지 않았다.

빌드 원본 `c43c46f2e35b7a9b0ecf4d92c7e516d74319e994`를 가리키는 annotated tag
`v0.2.0`과 [release](https://github.com/mooh1222/project-brain/releases/tag/v0.2.0)를 게시했다.
후속 검증 문서 commit은 별도로 main에 반영하며 tag와 wheel의 source commit을 바꾸지 않는다.
게시한 wheel·constraints·SHA256SUMS 세 파일을 다시 다운로드해 위 해시와 전부 일치함을 확인했다.

```bash
python tools/release.py smoke --tag v0.2.0 --from-release
```

위 명령을 개발 경로 환경이 없는 프로세스에서 실행했다. 결과는 `ok: true`다.
실제 import는 별도 tool site-packages, 설치 내용과 wheel RECORD 및 constraints 일치,
installer 65개 관리 파일의 두 번째 변경 배열은 전부 `[]`였다. 새 batch/canonical receipt,
정상 재실행·부분 재개·finalizer 복구, JSON v2 create/list/show/update/prepare, audit,
search→show, session list/complete/replay가 성공했다. 잘못된 identity/PATH CLI/runtime,
legacy 증명 불가, 변경된 엔진·입력·소비 revision은 거부했고 Brain hash를 보존했다.
합성 소비자·StubEmbedder·정규식 tokenizer만 사용했다.

현재 근거는 ignored `dist/113-e3/published-artifact-checks.json`, `published-smoke.json`,
`published-smoke.stderr.log`, `published-artifacts/`에 보존한다. 이전 c43c46f 고정 diff의
독립 Standards/Spec 검수는 각각 0건이다. 이번 후속 단계의 제품 코드는 바꾸지 않았다.

**E3 완료**다. 소비자에게 위 고정 버전·URL·해시 및 release 안내의 runtime 갱신법·호환표를
인계할 수 있다. 운영 코퍼스·BB2 파일·전역 설치는 바꾸지 않았다. BB2 B4는 기존 #80 결과와
이 E3를 함께 받는 별도 단계이며 이번 게시 검증으로 재개하거나 완료 처리하지 않았다.

## 변경 소유 범위

engine: `__init__.py`, `engine_identity.py`, `transaction_receipt.py`, `cli.py`, `mutation.py`,
`session.py`. runtime: ingest-tools 안내, batch/assemble/finalize/engine_python 및 공유 bootstrap,
관련 runtime tests. 배포: `tools/release.py`, `tools/release_consumer.py`, `pyproject.toml`,
`uv.lock`, release/identity tests. 문서: README, runtime/change map, 이 보고서와 v0.2.0 안내.
기존 untracked 스펙·검토 문서·발표 자료는 수정하지 않았고 stage/commit하지 않았다.
