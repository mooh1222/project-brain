# Release 팀 적재 #113 — 로컬 실행 및 인계

상태: **E1 완료, E2 완료, E3 준비만 완료(미커밋·미게시)**.

## 실행 경계

기준 HEAD `7031619a02ce77d000a2d8c4c9dc189cc38b6eea`. 기존 untracked 문서와
스펙은 보존한다. 원격 변경·commit·tag·게시와 소비 프로젝트 수정은 승인 범위 밖이다.
소비 프로젝트의 실데이터는 사용하지 않으며 합성 Git 소비자만 검증한다.

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

## 검증 결과

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

검수 최종 결과: Standards 0건 / Spec 0건. 모든 수정은 unstaged 상태로 보존했다.

합성 소비자 smoke는 `tools/release_consumer.py`가 수행하고 `tools/release.py smoke`에도
연결했다. StubEmbedder와 정규식 tokenizer만 사용했다. 실제 소비 데이터·실모델 rebuild/eval은
실행하지 않았다. 변경은 저장 객체나 검색 입력을 바꾸지 않으므로 change-map상 불필요하다.
ignored `dist/113-validation/`에 게시 v0.1.0 재현 로그, local wheel smoke, 후보 artifact와
checksums를 보관한다. 이 경로의 원시 로그는 로컬 점검용이며 원격 게시 대상이 아니다.

## E3 준비와 소비자 인계 경계

다음 버전은 additive release binding과 JSON v2 기능을 담는 **v0.2.0**으로 준비했다.
[설치·runtime 갱신·호환표](../releases/v0.2.0.md)는 검토용이며 아직 게시되지 않았다.

현재 로컬 후보의 식별값:

| 대상 | SHA256 |
|---|---|
| wheel | `5fd18be38898a6da4ae8490562d2f168dc3cb098f2ca789221579f2c14348ac9` |
| constraints | `f51f915a3dc1be9c817debc41a42d4d374beb18e9803eb76aedb4bb715d40425` |
| package content identity | `0d06b00c9193b754749d73e51b017f723533c193703f63993861addea7f24d2b` |

이 후보의 source_commit은 테스트용 `0000000000000000000000000000000000000000`이다.
미커밋 소스를 특정 실제 commit에서 나온 release로 가장하지 않기 위한 합성 provenance다.
**배포하거나 소비 프로젝트에 고정할 artifact가 아니다.** 실제 import/설치 내용 검증은 통과했지만
커밋된 엔진 코드의 wheel·게시 artifact 검증과는 별개다.

정식 `tools/release.py build --tag v0.2.0`도 dirty tracked 상태를 exit 1로 거부했고
정식 산출물은 만들지 않았다. build는 승인된 commit을 한 번 고정해 archive·provenance·템플릿
비교에 같은 commit을 사용한다.

남은 순서: task-owned 변경 검토 및 commit 승인 → 커밋된 HEAD에서 wheel/constraints/checksum
생성 → 격리 smoke → push/tag/release 게시 승인 → 다운로드 artifact smoke → 최종 고정 해시와
설치 안내 전달. 각 원격 행위는 이번 승인 범위 밖이다. **E3 미완료**이며 소비자 최종 통합의
재개 입력으로 넘기지 않는다. 사용자 정책 결정은 남지 않았고 commit/게시 승인만 남았다.

## 변경 소유 범위

engine: `__init__.py`, `engine_identity.py`, `transaction_receipt.py`, `cli.py`, `mutation.py`,
`session.py`. runtime: ingest-tools 안내, batch/assemble/finalize/engine_python 및 공유 bootstrap,
관련 runtime tests. 배포: `tools/release.py`, `tools/release_consumer.py`, `pyproject.toml`,
`uv.lock`, release/identity tests. 문서: README, runtime/change map, 이 보고서와 v0.2.0 검토안.
기존 untracked 스펙·검토 문서·발표 자료는 수정하지 않았고 stage/commit하지 않았다.
