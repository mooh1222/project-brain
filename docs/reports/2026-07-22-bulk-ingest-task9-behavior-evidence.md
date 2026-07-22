# Task 9 적재 스킬 행동 증거

이 문서는 `task9_implementer`가 직접 수행한 다섯 요청의 관찰 기록이다. 별도 언어 모델 작업자를 실행한 것처럼 표현하지 않았다. 각 대상에는 `project-brain install`로 `behavior-brain-ingest`를 설치했고, 실행 대상의 `AGENTS.md`, 설치된 `SKILL.md`, 필요한 reference를 읽은 뒤 행동했다. 재실행한 `run_ingest.sh`는 `PROJECT_BRAIN_BIN=.venv/bin/project-brain`을 지정하고 PATH 선두도 같은 디렉터리로 둔 상태에서 실행했다. `command -v project-brain`은 기능 워크트리의 `.venv/bin/project-brain`을 출력했다. 아래 경로는 모두 이 워크트리 기준 상대경로다.

실행 중 만들어진 `.task9-run/`은 이 기록을 작성한 뒤 제거한다. fixture 아래에는 실행 결과가 아니라 재실행 가능한 입력만 남긴다. 실제 replay 입력·driver·전사 기록은 [behavior-replay](2026-07-22-bulk-ingest-task9-behavior-replay/README.md)에 따로 보존했다.

## baseline 연결

이 행동 시나리오는 다음 계약 근거를 사용한다.

- `references/ingest-case-log.md`의 full ID 이중 접두 24개, 단건 runner 때문에 생긴 임시 wave runner, `completed`인데 내부 실패가 있던 workflow, callers 미추적 뒤 33개 수정 기록
- `docs/specs/2026-07-21-bulk-ingest-hardening-design.md`의 workflow 완료 경계, 프로젝트 코드 검증 overlay, raw 이름 분기, MPS 24.29GiB 사고
- `src/project_brain/templates/ingest/scripts/validate_workflow_result.py`와 `run_ingest_batch.py`의 validator·재개 경로

## raw 규약 TDD 기록

- RED: `.venv/bin/python -m pytest tests/test_ingest_skill_contract.py -q`를 확장된 token 계약으로 실행해 `1 failed, 4 passed`를 관찰했다. 실패 원인은 raw 정책 블록에 `fallback document`가 없었던 것이다.
- GREEN: 같은 명령은 raw 정책 절에 bundle root·canonical relative path·fallback 문구를 추가한 뒤 `5 passed`가 됐다. canonical template와 installer-rendered reference 모두 같은 절에서 확인한다.

## 1. 단건 입력

### 사용자 입력

`완료된 기능 sample-a를 brain에 적재해 줘. 현재 코드만 근거로 쓰고 변경 이력은 찾지 마.`

### 읽은 계약과 첫 보고

- `tests/fixtures/ingest_skill_behavior/single/AGENTS.md`
- 설치된 `.agents/skills/behavior-brain-ingest/SKILL.md`
- 설치된 `references/scope.md`, `references/object-model.md`, `references/ingest-tools.md`, `references/completeness-checklist.md`
- 첫 보고: `Source Intake | route=single | history_coverage=unsearched | 대상=sample-a | 소스 묶음=현재 source/sample_a.cpp | 코드 기준점=실행 대상 main의 source baseline commit`

### 실행과 관찰값

Replay 자료: [single](2026-07-22-bulk-ingest-task9-behavior-replay/single/transcript.md). synthetic target baseline commit은 `8362e8d9d09600cd8468e28e5a49c02dd78bd892`이고 replay `domain_spec.py`의 `COMMIT`도 이 값이다.

1. `clang++ -std=c++17 -fsyntax-only source/sample_a.cpp`는 종료 코드 0이었다.
2. 확인한 함수 본문을 한 개의 의미 원자로 만들고, `PROJECT_BRAIN_BIN=.venv/bin/project-brain PATH=.venv/bin:$PATH run_ingest.sh --defer-finalize verify.json domain_spec.py`를 실행했다.
3. `assemble_notes`는 mappings=1, anchors=1, terms=0을 출력했다.
4. build는 `ok=true`, built=5를 출력했고, ingest는 `ok=true`, ingested=5를 출력했다.
5. runner는 `--defer-finalize`를 출력하고 종료 코드 0으로 끝났다. 색인·eval·finalize는 다시 실행하지 않았다.

### 생성 파일과 판정

입력 `source/sample_a.cpp`는 brain 객체로 변환된 근거라 바이트 보존 대상이 아니다. 생성된 JSON과 실행 뒤 SHA-256은 다음과 같다.

| 결과 경로 | SHA-256 |
| --- | --- |
| `brain/objects/code/code.sample-a.core-behavior--0.json` | `5da9108e6e5a25653c9d6a867cce1b1e25060b28b2d15912856bebf8acf18fab` |
| `brain/objects/domain/context.sample-a.json` | `249228c93eac5d55f677733c675576732c15e455fae39872bd3f8c795597b8a0` |
| `brain/objects/evidence_refs/evref.sample-a.core-behavior--0.json` | `67f533c85014a237242bf205b06d3dc98a91ec4dc416c7c9028f5df548f1e1e7` |
| `brain/objects/mappings/mapping.sample-a.core-behavior.json` | `78e8f987d1d2603b002e58cec29fe928232a28712fe91b1e882f7369058fb482` |
| `brain/raw/manifests/manifest.sample-a.code.json` | `601069ba5a31605c1e339387913abc8e32f3bbae2fccfd408bd61db5f296c67f` |

판정: 조립과 ingest는 기능 워크트리 바이너리로 실행됐다. 마무리 검증은 `--defer-finalize`로 보류했다.

## 2. 부분 실패 batch 입력

### 사용자 입력

`세 항목을 동적 워크플로우로 추출했다. 최상위 상태는 completed지만 한 항목 verify가 error다. 이 상태에서 적재를 마무리해 줘.`

### 읽은 계약과 첫 보고

- `tests/fixtures/ingest_skill_behavior/batch_partial_failure/AGENTS.md`
- 설치된 `SKILL.md`, `references/system-domain-playbook.md`, `references/completeness-checklist.md`
- 설치된 `scripts/validate_workflow_result.py`
- 첫 보고: `Source Intake | route=batch | history_coverage=unsearched | 대상=동적 workflow 세 항목 | 소스 묶음=workflow-result.json | 코드 기준점=해당 없음`

### 실행과 관찰값

Replay 자료: [batch partial failure](2026-07-22-bulk-ingest-task9-behavior-replay/batch_partial_failure/transcript.md).

`scripts/validate_workflow_result.py workflow-result.json`을 실행했다. 종료 코드는 1이었고 출력은 다음 한 항목이었다.

```json
{"ok": false, "errors": ["items[1].verify_status가 ok가 아닙니다"]}
```

### 생성 파일과 판정

brain 객체·batch report·finalization 파일은 생성하지 않았다. workflow 결과 검증 명령에서 멈췄다. 같은 workflow 입력과 run ID에서 verify 오류 항목을 고친 뒤 validator를 다시 통과시키고, 그 다음에 batch manifest runner를 시작해야 한다.

## 3. 코드 흐름 입력

### 사용자 입력

`일반 C++ 메서드가 실제 런타임에서 호출되는지 확인해 매핑으로 적재해 줘.`

### 읽은 계약과 첫 보고

- `tests/fixtures/ingest_skill_behavior/code_flow/AGENTS.md`
- 설치된 `SKILL.md`, `references/project-code-verification.md`, `references/system-domain-playbook.md`, `references/object-model.md`, `references/ingest-tools.md`
- 로컬 `bb2-code-search-routing` fixture skill
- 첫 보고: `Source Intake | route=single | history_coverage=unsearched | 대상=runtime C++ 호출 흐름 | 소스 묶음=source/runtime.cpp, compile_commands.json, project-code-verification overlay | 코드 기준점=실행 대상 main의 source baseline commit`

### 실행과 관찰값

Replay 자료: [code flow](2026-07-22-bulk-ingest-task9-behavior-replay/code_flow/transcript.md)와 [stdlib JSON-RPC driver](2026-07-22-bulk-ingest-task9-behavior-replay/code_flow/clangd_call_hierarchy.py). synthetic target baseline commit은 `5c880d519c6bc3ae1a0cbcdc4e1d831241ba084f`이고 replay `domain_spec.py`의 `COMMIT`도 이 값이다.

1. fixture의 `references/project-code-verification.md`와 `.agents/skills/bb2-code-search-routing/SKILL.md`를 읽었다.
2. Apple clangd 16을 JSON-RPC로 시작해 `textDocument/prepareCallHierarchy`를 `source/runtime.cpp`의 `runtime::transform`(0-based line 2, character 5)에 질의했다. 이어 `callHierarchy/incomingCalls`를 두 번 질의했다. 응답은 `transform ← dispatch`와 `dispatch ← run`이었고, 모두 `runtime.cpp` 안의 호출 범위였다. 끊긴 경계는 관찰하지 못했다.
3. `clangd --check=source/runtime.cpp --compile-commands-dir=.`도 실행했다. compile_commands.json을 읽었고 `All checks completed, 0 errors`, 종료 코드 0이었다. `rg`로도 `runtime::run → runtime::dispatch → runtime::transform`을 교차 확인했다.
4. `PROJECT_BRAIN_BIN=.venv/bin/project-brain PATH=.venv/bin:$PATH run_ingest.sh --defer-finalize verify.json domain_spec.py`를 실행했다. assemble_notes는 mappings=1, anchors=2, terms=0, build는 `ok=true`, built=7, ingest는 `ok=true`, ingested=7을 출력했다. `--defer-finalize` 때문에 색인·eval·finalize는 실행하지 않았다.

### 생성 파일과 판정

입력 `source/runtime.cpp`는 brain 객체로 변환된 근거라 바이트 보존 대상이 아니다. 생성된 JSON과 실행 뒤 SHA-256은 다음과 같다.

| 결과 경로 | SHA-256 |
| --- | --- |
| `brain/objects/code/code.runtime-flow.runtime-call-flow--0.json` | `16ecc086a9ea995a0e7d96247aa9e97792d5c549c764844a3df8a6a0654faedf` |
| `brain/objects/code/code.runtime-flow.runtime-call-flow--1.json` | `453a113cb01c590c0920180ec75d88174c404dbe97c42fee05931e101a8967d8` |
| `brain/objects/domain/context.runtime-flow.json` | `40563d5eb35513fd4a550c9438b25041bb17af5430ff4d0cfc277f76b3fff07e` |
| `brain/objects/evidence_refs/evref.runtime-flow.runtime-call-flow--0.json` | `3a306ae93a8e185df2a3a8c9d6b9ee0c9bd18e76f92bf75f396c67dffd238a5e` |
| `brain/objects/evidence_refs/evref.runtime-flow.runtime-call-flow--1.json` | `9ea811060a9dea92ad3c580058aa3d8458bbd558205a42c92eac62d9e197301b` |
| `brain/objects/mappings/mapping.runtime-flow.runtime-call-flow.json` | `ef7f02ef1a037340a1e0d5e0bf068e85eab9df84b6b436d8268e921619f9538d` |
| `brain/raw/manifests/manifest.runtime-flow.code.json` | `98388db2decc6f53218d12e5b6dd8936650310f639a8e3577b179a69301e0995` |

판정: 실제 LSP callers 질의와 대체 구문·소스 확인 기록을 남긴 뒤, 기능 워크트리 바이너리로 build·ingest까지 실행됐다. 마무리 검증은 의도적으로 보류했다.

## 4. logical key 입력

### 사용자 입력

`mapping key로 mapping.sample-a.core-behavior를 사용해 적재해 줘.`

### 읽은 계약과 첫 보고

- `tests/fixtures/ingest_skill_behavior/logical_key/AGENTS.md`
- 설치된 `SKILL.md`, `references/object-model.md`, `references/ingest-tools.md`
- 첫 보고: `Source Intake | route=single | history_coverage=unsearched | 대상=sample-a mapping key | 소스 묶음=request.txt와 source/sample_a.cpp | 코드 기준점=실행 대상 main의 source baseline commit`

### 실행과 관찰값

Replay 자료: [logical key](2026-07-22-bulk-ingest-task9-behavior-replay/logical_key/transcript.md). synthetic target baseline commit은 `32b33afe30787125a66078dd7c4e2911622558a0`이고 replay `domain_spec.py`의 `COMMIT`도 이 값이다.

요청에 들어 있던 `mapping.sample-a.core-behavior`를 고치지 않고 그대로 verify 입력의 `mapping_key`에 넣었다. `PROJECT_BRAIN_BIN=.venv/bin/project-brain PATH=.venv/bin:$PATH run_ingest.sh --dry verify.json domain_spec.py`를 실행했다. assemble_notes는 mappings=1, anchors=1, terms=0을 출력한 뒤, 기능 워크트리 engine build가 다음 세 key를 논리 key가 아니라고 거부했다: `mapping.sample-a.core-behavior`, 조립기가 만든 `mapping.sample-a.core-behavior--0`, 그 code evidence reference key. runner 종료 코드는 1이었다.

### 생성 파일과 판정

`--dry` 실행 뒤 `brain/` 아래 파일은 없었다. 따라서 brain 객체와 finalization 파일은 생성하지 않았다.

## 5. raw 이름 분기 입력

### 사용자 입력

`한 기능의 개정 기획서 2개와 서로 다른 옛 기획서 20개를 raw에 보관해 줘.`

### 읽은 계약과 첫 보고

- `tests/fixtures/ingest_skill_behavior/raw_names/AGENTS.md`
- 설치된 `SKILL.md`, `references/ingest-tools.md`
- 첫 보고: `Source Intake | route=batch | history_coverage=unsearched | 대상=개정 기획서 2개와 옛 기획서 20개 | 소스 묶음=sources/ 아래 Markdown 22개 | 코드 기준점=해당 없음`

### 실행과 관찰값

Replay 자료: [raw names](2026-07-22-bulk-ingest-task9-behavior-replay/raw_names/transcript.md)와 [raw driver](2026-07-22-bulk-ingest-task9-behavior-replay/raw_names/replay_raw_names.py). 두 개의 개정 입력과 20개 옛 문서를 읽은 뒤 installed ingest-tools의 raw 보관 규칙에 따라 복사했다. 서로 다른 `collision-a/Collision Notes.md`와 `collision-b/Collision Notes.md`가 같은 sanitized stem으로 충돌했고, 두 번째는 source bundle root 아래 canonical relative path `collision-b/Collision Notes.md`의 SHA-256 앞 12글자 `01967d62e17e`를 suffix로 썼다. `한글 문서.md`는 ASCII-only stem이 비어 fallback `document`를 썼다. `/usr/bin/openssl dgst -sha256`과 `cmp -s`로 다시 계산했고, 각 원본과 결과의 `cmp -s` 종료 코드는 모두 0이었다.

### 원본과 결과 파일

아래 SHA-256은 복사 뒤에 계산했다. 모든 행의 바이트 보존은 `cmp -s` 종료 코드 0으로 확인했다.

| 원본 경로 | 결과 경로 | SHA-256 |
| --- | --- | --- |
| `sources/revision-one.md` | `brain/raw/sources/feature-revisions/spec-v1.md` | `2f84de119bbbf853dd03bb553fbfb8863d1c9d2b038b9a056b34c535f8c28ea2` |
| `sources/revision-two.md` | `brain/raw/sources/feature-revisions/spec-v2.md` | `af74c89ddecf4fdcab8b73f4c0d9a947bd48f8ced06ecea28a03bc81c04af1f2` |
| `sources/collision-a/Collision Notes.md` | `brain/raw/sources/legacy-archive/collision-notes.md` | `3d9da81e35def52e472f3d80c9709886522622eb214631f6dc2dae8bfc0d3a79` |
| `sources/collision-b/Collision Notes.md` | `brain/raw/sources/legacy-archive/collision-notes-01967d62e17e.md` | `5f1417e2bc761ec75d1682c0f360258c9f843af3b7b43dd55be2cbb4df482eed` |
| `sources/한글 문서.md` | `brain/raw/sources/legacy-archive/document.md` | `4802063ee382e72cdc04f591a68ae9c026d20192054a96820be10dda233f9cbc` |
| `sources/Legacy Plan 01.md` | `brain/raw/sources/legacy-archive/legacy-plan-01.md` | `ac34797a75d32e8bd7e40dce09d37eb61821c4f2186d2125532efdbc1d275241` |
| `sources/Legacy Plan 02.md` | `brain/raw/sources/legacy-archive/legacy-plan-02.md` | `5a02769e8c99f32479528f27ced4349ba2d476915112469bbf2980bf2700221a` |
| `sources/Legacy Plan 03.md` | `brain/raw/sources/legacy-archive/legacy-plan-03.md` | `936348b2559285d9486c248d89bca11224d1ffffd5ef311fe2d603caa1ec35f4` |
| `sources/Legacy Plan 04.md` | `brain/raw/sources/legacy-archive/legacy-plan-04.md` | `b0678019f7a76be481353acdd97992b4d26555e309edebead86c64c4762e0661` |
| `sources/Legacy Plan 05.md` | `brain/raw/sources/legacy-archive/legacy-plan-05.md` | `154ea902427ee2abaffa8e430f2d1f8bd331505d2a774b7b0ac11add72cdbaa8` |
| `sources/Legacy Plan 06.md` | `brain/raw/sources/legacy-archive/legacy-plan-06.md` | `ded8313c791ea46d8c33c3d623eb3b53c2927a19a3132558c5fd9c18d5899336` |
| `sources/Legacy Plan 07.md` | `brain/raw/sources/legacy-archive/legacy-plan-07.md` | `80e261f0b07901a9d239fb195b508b66b4f591ea5263d08c5b0a70d592e9d129` |
| `sources/Legacy Plan 08.md` | `brain/raw/sources/legacy-archive/legacy-plan-08.md` | `28a09b5bdd075cd45d836e84499719d2740d472e4d04b244503ccb29f6d2a0ca` |
| `sources/Legacy Plan 09.md` | `brain/raw/sources/legacy-archive/legacy-plan-09.md` | `bc91ac309bf781f2bd1dea7825c4355e179381889e4e9753de268b95fc6385aa` |
| `sources/Legacy Plan 10.md` | `brain/raw/sources/legacy-archive/legacy-plan-10.md` | `6fa414e486d7e50159e7b048cbd6a328ccb3eea4d3a261f385d3a25a0da44ccd` |
| `sources/Legacy Plan 11.md` | `brain/raw/sources/legacy-archive/legacy-plan-11.md` | `299c07e362433fd7d90d58c77a01c1c67c26cbeff770e3593f94ac91dfc3a12d` |
| `sources/Legacy Plan 12.md` | `brain/raw/sources/legacy-archive/legacy-plan-12.md` | `6df078869aa845fb71a94113b356a98535aa5fcf7bbf20ec30bfbc7008418d8d` |
| `sources/Legacy Plan 13.md` | `brain/raw/sources/legacy-archive/legacy-plan-13.md` | `e8cba501601b9cb2887a82909fc77b06912c230178f146ab5bbfc506ef13260d` |
| `sources/Legacy Plan 14.md` | `brain/raw/sources/legacy-archive/legacy-plan-14.md` | `375a55c1ca64e8573d1d068969110fa17faddfcab80b3602c0147856816444e0` |
| `sources/Legacy Plan 15.md` | `brain/raw/sources/legacy-archive/legacy-plan-15.md` | `0cb4613ca6b5fb75bbfd5f4032170bb986982cd21880d9e184b5b80a479634dd` |
| `sources/Legacy Plan 16.md` | `brain/raw/sources/legacy-archive/legacy-plan-16.md` | `74886aedb1cf64bdd20e2e1dadc10bda6c22416ce5236a50a3fe1c71328ce13b` |
| `sources/Legacy Plan 17.md` | `brain/raw/sources/legacy-archive/legacy-plan-17.md` | `6078d14ba9ed0cb6df0e0940be2663157aad69cabba83b6bcfde3dfeec9e04ac` |

## 보존한 파일과 중립성 점검

보존 fixture는 `tests/fixtures/ingest_skill_behavior/` 아래의 다섯 시나리오 입력이다.

- `single`: AGENTS 지시, 사용자 입력, C++ 원본 1개
- `batch_partial_failure`: AGENTS 지시, 사용자 입력, workflow 결과 JSON 1개
- `code_flow`: AGENTS 지시, 사용자 입력, C++ 원본, compile_commands.json, 코드 검증 overlay, 최소 routing skill
- `logical_key`: AGENTS 지시, 사용자 입력, C++ 원본
- `raw_names`: AGENTS 지시, 사용자 입력, revision 2개와 old 문서 20개(동일 basename collision 2개, non-ASCII basename 1개 포함)

fixture 입력은 결과 파일 목록, 실행 전 SHA-256, 정답 hash를 포함하지 않는다. `rg` 자체 점검은 아래 명령으로 수행하며, `raw/sources`와 `mapping.sample-a.core-behavior`는 각각 routing 지시와 사용자 원문 입력에 포함된 문자열로 따로 확인한다.

```bash
rg -n -i 'sha-?256|expected output|expected result|output file|정답|예상.*(출력|파일|해시)' tests/fixtures/ingest_skill_behavior
```

## 환경 한계와 정리 대상

- 이전 단건 runner는 Task 9 범위를 넘겨 index rebuild에 진입했다. 기존 Hugging Face bge-m3 캐시(약 6.4G)는 관찰됐지만, Task 9 실행일에는 모델 파일이나 관련 캐시 변경이 없어 새 다운로드 근거가 없다. 기존 캐시 재사용으로 판단했고 캐시는 삭제하지 않았다. 이번 재실행은 `--defer-finalize` 또는 `--dry`만 사용했다.
- `.task9-run/`은 임시 실행 대상이므로 이 문서 작성 뒤 제거한다.
