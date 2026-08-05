# Project Brain 전체 지도·데이터 계약 기반 구현 계획

> **실행 지침:** 이 계획은 `superpowers:test-driven-development`,
> `superpowers:verification-before-completion`, `superpowers:requesting-code-review`를 적용한다.
> 사용자가 커밋·push를 금지했으므로 각 작업의 정상적인 commit 단계는 생략하고, 아래 표적 테스트와
> `.superpowers/architecture-foundation/progress.md` 원장으로 체크포인트를 남긴다.

**목표:** 새 에이전트가 Project Brain의 전체 실행 구조, 19종 객체 계약, 변경별 검증 범위와
문서 권위를 한 진입점에서 찾고, 실제 JSON 예시와 자동 드리프트 검증으로 오판을 막게 한다.

**아키텍처:** production 동작은 바꾸지 않는다. 현재 코드·테스트·CLI를 정본으로 읽어
`docs/architecture/`에 검증된 탐색면을 만들고, 설치되는 ingest reference 아래에 source 정본 JSON을
둔다. 테스트는 문서의 전체 CLI/하위 명령/`MutationOperation` 집합, 19종 kind 집합, shape·ID 문법,
정상 연결 그래프, 층별 실패 반례와 installer 전파를 직접 대조한다.

**기술 스택:** Python 3.12, pytest, unittest, argparse, JSON, Markdown/Mermaid, 현재
`project_brain.schema`·`id_grammar`·`reference_fields`·`lint`·`mutation`·`installer` API.

## 실행 경계

- 작업 위치: `/Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation`
- 기준 HEAD: `76827c3fe3e09104e657db515e0b21a37eb55b18`
- 설계 정본:
  `docs/superpowers/specs/2026-08-04-project-brain-architecture-foundation-design.md`
- production Python 동작, 소비 프로젝트 데이터, Task 18, 실모델 index, 발표 자료는 범위 밖이다.
- `docs/design-canonical.md:152-227`의 Task 17 상세는 이번 작업에서 축약하지 않는다.
- 추가 계보 조사는 하지 않는다. 현재 repo에 명시된 Karpathy LLM Wiki, Matt Pocock
  `CONTEXT.md`, GBrain, BB2 내부 진화 흔적만 보조 메모로 분류한다.
- 테스트를 먼저 추가해 의도한 이유로 RED를 확인한 뒤 문서·JSON을 만든다.
- 구현 중 공식 경로의 실제 동작 구멍을 찾으면 production을 고치지 않고 `ENGINE_GAP`으로 보고한다.

## 공통 검증 명령

모든 명령은 위 worktree 루트에서 실행한다.

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest -q
PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
git diff --check
```

이번 변경은 문서·template·test뿐이므로 실코퍼스 `brain/checks`, `eval`, 실모델 rebuild는 실행하지
않는다. production 검색·색인 계약을 뜻밖에 수정하게 되면 이 판단을 폐기하고 별도 승인부터 받는다.

---

## Task 0: 구현 전 isolated baseline 고정

**파일**

- 수정: `.superpowers/architecture-foundation/progress.md` (작업 중 scratch 원장, 최종 정리 대상)

### 0.1 engine 전체 baseline

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest -q
```

이 worktree에서 구현 전 실행한 결과는 `1522 passed, 105 subtests passed`다.

### 0.2 installed ingest runtime baseline

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
```

worktree에 `.venv` 경로가 없던 첫 실행은 runtime subprocess가 system Python을 잡아
`tree_sitter`를 찾지 못해 3건 실패했다. product defect가 아니라 checkout-local interpreter
경로 문제임을 확인하고, 원본 checkout의 기존 `.venv`를 worktree `.venv` symlink로 연결한 뒤
같은 명령에서 `Ran 99 tests ... OK`를 확인했다. 이 setup symlink는 최종 allowlist 전에 제거한다.

두 결과와 환경 실패 원인을 scratch 원장에 기록한 상태에서만 Task 1로 간다. 최종 suite 실패는 이
baseline과 비교해 회귀인지 환경 문제인지 분류한다.

---

## Task 1: 전체 지도 구조와 기계 판독 계약을 테스트로 고정

**파일**

- 생성: `tests/test_architecture_docs.py`
- 생성: `docs/architecture/README.md`
- 생성: `docs/architecture/runtime-map.md`
- 생성: `docs/architecture/data-contracts.md`
- 생성: `docs/architecture/change-map.md`

### 1.1 RED — 문서·machine contract가 없으면 실패하는 테스트

`tests/test_architecture_docs.py`에 다음 골격을 먼저 추가한다.

```python
import json
import re
from pathlib import Path

import pytest

from project_brain import cli
from project_brain.mutation import MutationOperation


ROOT = Path(__file__).parents[1]
ARCH = ROOT / "docs" / "architecture"
REQUIRED_DOCS = {
    "README.md",
    "runtime-map.md",
    "data-contracts.md",
    "change-map.md",
}


def _runtime_contract() -> dict:
    text = (ARCH / "runtime-map.md").read_text(encoding="utf-8")
    match = re.search(
        r"<!-- architecture-contract:start -->\s*```json\s*(.*?)\s*```\s*"
        r"<!-- architecture-contract:end -->",
        text,
        re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def _top_level_commands() -> set[str]:
    source = (ROOT / "src/project_brain/cli.py").read_text(encoding="utf-8")
    return set(re.findall(r'argv\[0\] == "([^"]+)"', source))


def _help_choices(runner, argv: list[str], capsys) -> set[str]:
    with pytest.raises(SystemExit) as exc:
        runner([*argv, "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    match = re.search(r"\{([^{}]+)\}", output)
    assert match is not None, output
    return set(match.group(1).split(","))
```

아래 테스트를 함께 둔다.

- `test_required_architecture_documents_exist`
- `test_runtime_contract_matches_all_top_level_cli_commands`
- `test_runtime_contract_matches_all_subcommand_paths`
- `test_runtime_contract_matches_mutation_operations`
- `test_architecture_contract_paths_exist`
- `test_living_architecture_docs_do_not_pin_test_counts`

하위 명령은 `--help`에서 실제 argparse choice를 읽어 다음 flat path와 비교한다.

```python
{
    "index rebuild",
    "session list",
    "session mark-processed",
    "projection build-reuse",
    "projection refresh",
    "graph isolated",
    "graph export",
    "snapshot create",
    "snapshot verify",
    "snapshot restore",
    "context-replace plan",
    "context-replace apply",
    "migration id plan",
    "migration id apply",
    "migration display plan",
    "migration display apply",
    "migration canonical-repair plan",
    "migration canonical-repair apply",
}
```

실행한다.

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest \
  tests/test_architecture_docs.py -q
```

기대 RED: `docs/architecture/` 네 파일이 없어서 실패한다. import나 환경 오류라면 테스트를 고쳐
의도한 missing-doc failure가 먼저 보이게 한다.

### 1.2 GREEN — 네 문서 골격과 정확한 runtime contract 생성

`runtime-map.md`에 다음 JSON block을 그대로 두고, 테스트가 이 block만 기계 판독하게 한다.

```json
{
  "schema_version": 1,
  "top_level_commands": [
    "audit", "bootstrap", "build", "context-replace", "doctor", "eval", "graph",
    "index", "ingest", "install", "lint", "mark-checked", "migration", "projection",
    "promote", "promote-auto", "query", "search", "session", "show", "snapshot",
    "stale-check"
  ],
  "subcommand_paths": [
    "context-replace apply", "context-replace plan", "graph export", "graph isolated",
    "index rebuild", "migration canonical-repair apply", "migration canonical-repair plan",
    "migration display apply", "migration display plan", "migration id apply",
    "migration id plan", "projection build-reuse", "projection refresh",
    "session list", "session mark-processed", "snapshot create", "snapshot restore",
    "snapshot verify"
  ],
  "mutation_operations": [
    "canonical_repair", "context_replace", "display_migration", "id_only_migration",
    "ingest", "mark_checked", "projection", "projection_repair", "promote",
    "promote_auto"
  ],
  "source_paths": [
    "src/project_brain/assembly.py", "src/project_brain/audit.py",
    "src/project_brain/cli.py", "src/project_brain/config.py",
    "src/project_brain/context_projection.py", "src/project_brain/corpus_io.py",
    "src/project_brain/id_grammar.py", "src/project_brain/installer.py",
    "src/project_brain/lint.py", "src/project_brain/mutation.py",
    "src/project_brain/reference_fields.py", "src/project_brain/router.py",
    "src/project_brain/schema.py", "src/project_brain/search.py",
    "src/project_brain/search_index.py", "src/project_brain/session.py",
    "src/project_brain/snapshot.py", "src/project_brain/store.py",
    "src/project_brain/surface.py"
  ],
  "test_paths": [
    "tests/test_architecture_docs.py", "tests/test_assembly.py", "tests/test_audit.py",
    "tests/test_cli.py", "tests/test_code_verify.py", "tests/test_context_projection.py",
    "tests/test_context_replace.py", "tests/test_corpus_io.py", "tests/test_id_grammar.py",
    "tests/test_ingest.py", "tests/test_installer.py", "tests/test_lint.py",
    "tests/test_migration.py", "tests/test_mutation.py", "tests/test_router.py",
    "tests/test_schema.py", "tests/test_search.py", "tests/test_search_index.py",
    "tests/test_session.py", "tests/test_snapshot.py", "tests/test_stale_check.py"
  ],
  "doc_paths": [
    "AGENTS.md", "README.md", "ROADMAP.md", "docs/design-canonical.md",
    "docs/search-internals.md", "docs/architecture/README.md",
    "docs/architecture/runtime-map.md", "docs/architecture/data-contracts.md",
    "docs/architecture/change-map.md"
  ]
}
```

`README.md`, `data-contracts.md`, `change-map.md`에는 이후 작업이 채울 실제 섹션 제목을 먼저 만든다.
`README.md`에는 목적, 2-레포, 전체 흐름, 권위, 시나리오별 길찾기, 계보 메모를 둔다.

테스트를 다시 실행해 GREEN을 확인한다.

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest \
  tests/test_architecture_docs.py -q
```

### 1.3 체크포인트

- 문서에 선언한 명령 집합이 코드에서 계산한 집합과 정확히 같아야 한다.
- bare argv가 legacy query로 처리되는 호환 경로는 표 아래에 별도 설명한다.
- `MutationOperation` 값은 CLI 표시 이름이 아니라 enum value의 underscore 형태로 기록한다.
- 진행 원장에 RED 원인과 GREEN 결과를 남긴다.

---

## Task 2: runtime·변경 라우팅·문서 권위 지도를 현재 코드로 채우기

**파일**

- 수정: `tests/test_architecture_docs.py`
- 수정: `docs/architecture/README.md`
- 수정: `docs/architecture/runtime-map.md`
- 수정: `docs/architecture/change-map.md`
- 수정: `README.md`

### 2.1 RED — 핵심 경계가 빠지면 실패하는 문서 계약

다음 현재 동작을 문서 테스트로 먼저 요구한다.

```python
def test_runtime_map_states_non_corpus_write_boundaries():
    text = (ARCH / "runtime-map.md").read_text(encoding="utf-8")
    for phrase in (
        "build는 저장하지 않는다",
        "코퍼스 객체 변경만 MutationService",
        "query는 fresh index가 없어도",
        "search는 fresh index가 필요",
        "redaction_status 기반 restricted 라벨",
        "principal별 ACL을 집행하지 않는다",
        "session mark-processed",
        "audit은 stale-set cache를 쓴다",
    ):
        assert phrase in text


def test_architecture_entry_states_authority_and_two_repo_boundary():
    text = (ARCH / "README.md").read_text(encoding="utf-8")
    assert "명시 인자 > config > ConfigError" in text
    assert "엔진 레포" in text and "데이터 레포" in text
    assert "현재 동작은 코드·테스트·CLI" in text
```

실행해 아직 비어 있는 문장 때문에 RED가 나는지 확인한다.

### 2.2 GREEN — runtime map 작성

`runtime-map.md`를 다음 축으로 채운다.

1. Mermaid 전체 흐름: build/ingest/mutation/corpus, raw/index, query exact+optional recall,
   search five channels, inspection/health, auxiliary artifacts.
2. 저장면 권위 표:
   - `brain/objects/**`: 검수 객체 정본, 데이터 레포 추적
   - `brain/raw/**`: 원문 정본, 데이터 레포 추적
   - `.brain-local/index.db`: 재생성 가능한 기본 파생 색인
   - `.brain-local/stale-set.json`: query/show용 파생 cache
   - `.brain-local/sessions/*.json`: session 처리 marker
   - build/context-replace/migration manifest, snapshot, graph HTML, installer manifest: 목적별 별도 artifact
3. query: `classify_query()` → exact object route → fresh일 때만 recall → status/redaction/stale 표기.
   QueryRouter가 principal별 ACL을 집행하지 않는 현재 경계를 `ENGINE_GAP`으로 표시한다.
4. search: fresh DB 필수, `results/candidates/raw_excerpts/advisories/projection_reuse` 다섯 채널.
5. 코퍼스 쓰기: 모든 `MutationOperation`의 plan/apply와 `corpus_io` transaction, index/cache invalidation.
6. 비코퍼스 쓰기: index rebuild, stale cache, session marker, snapshot create/restore, plan manifest,
   graph export, install/bootstrap, doctor download.
7. 전체 CLI와 설치 스킬 표.

### 2.3 GREEN — change map 작성

`change-map.md`의 각 행은 production 파일, 직접 테스트, 설치 runtime test, 데이터 레포 checks,
eval, rebuild 조건, 횡단 계약을 담는다. 최소 행은 다음과 같다.

| 변경 축 | 주요 production | 엔진 표적 테스트 | 소비 데이터 회귀 | 실모델 rebuild |
|---|---|---|---|---|
| schema·ID·reference | `schema.py`, `id_grammar.py`, `reference_fields.py`, `store.py`, `lint.py` | schema/id/reference/lint/mutation | checks + lint/audit | 색인 surface가 안 바뀌면 불필요 |
| assembly·ingest | `assembly.py`, `ingest.py`, `mutation.py`, ingest templates | assembly/ingest/mutation/runtime | checks + lint/audit | 색인 입력이 바뀔 때만 |
| mutation·transaction | `mutation.py`, `corpus_io.py`, `transaction_receipt.py` | mutation/corpus_io/ingest | checks + eval | object surface/hash 입력이 바뀔 때만 |
| tokenizer | `tokenize_ko.py` | tokenizer/search_index/search | checks + eval | 필요 |
| surface·raw chunk·index schema | `surface.py`, `raw_chunks.py`, `search_index.py` | surface/raw/search_index/search | checks + eval | 필요 |
| embedder | `embedder.py`, `search_index.py` | embedder/search_index/search | checks + eval | 필요 |
| router·gate·ranking | `router.py`, `search.py` | router/search/eval harness | checks + eval | 색인 입력 불변이면 불필요 |
| projection | `context_projection.py`, `hash_utils.py`, `lint.py`, `search.py` | projection/lint/search | checks + eval | indexed payload/fingerprint 변경 시 필요 |
| stale·mark-checked·code verify·audit | `stale_check.py`, `code_verify.py`, `audit.py`, `cli.py` | stale/code/audit/mutation | checks + audit | 불필요 |
| CLI·config·installer | `cli.py`, `config.py`, `installer.py`, templates | cli/config/installer/runtime | 설치 smoke | 불필요 |
| snapshot·migration | snapshot/context-replace/migration/canonical modules | 대응 test 전부 | 실제 적용 작업에서 별도 승인 회귀 | 적용 artifact가 색인 입력을 바꾸면 적용 후 필요 |

문서-only/template-only 변경은 engine suite + runtime + installer만 요구한다고 명시한다.

### 2.4 README 진단 명령 드리프트 수정

`README.md` 상단에 architecture map 링크를 추가하고 명령 목록에 `project-brain audit`을 추가한다.
“점검·진단 4종 모두 읽기 전용” 문장은 다음 사실에 맞게 바꾼다.

- `lint`, `graph isolated`, 기본 `stale-check`는 코퍼스 불변 점검이다.
- `stale-check --write-cache`는 `.brain-local/stale-set.json`을 쓴다.
- `audit`은 기본 stale 검사 결과를 같은 cache에 쓰고 `--no-stale`이면 생략한다.
- `doctor --download`는 모델 cache를 채운다.
- `graph export`는 코퍼스는 안 바꾸지만 지정한 HTML 파일을 쓴다.

테스트를 다시 실행한다.

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest \
  tests/test_architecture_docs.py tests/test_cli.py tests/test_audit.py -q
```

---

## Task 3: 19종 저장 객체 shape template을 source 계약으로 만들기

**파일**

- 생성: `tests/test_object_contract_templates.py`
- 수정: `tests/test_installer.py`
- 생성: `src/project_brain/templates/ingest/references/object-templates/README.md`
- 생성: `src/project_brain/templates/ingest/references/object-templates/kinds/*.template.json` 19개
- 수정: `docs/architecture/data-contracts.md`

### 3.1 RED — kind 집합·required key·schema·ID 검증

먼저 다음 테스트를 추가한다.

```python
import json
from pathlib import Path

from project_brain.schema import (
    BASE_REQUIRED,
    KIND_REQUIRED,
    VALID_KINDS,
    validate_object,
    validate_object_id,
)


ROOT = Path(__file__).parents[1]
TEMPLATES = (
    ROOT / "src/project_brain/templates/ingest/references/object-templates"
)
KINDS = TEMPLATES / "kinds"


def _kind_name(path: Path) -> str:
    return path.name.removesuffix(".template.json")


def test_kind_template_file_set_exactly_matches_schema():
    assert {_kind_name(path) for path in KINDS.glob("*.template.json")} == VALID_KINDS


def test_each_kind_template_has_required_keys_and_valid_shape_and_id():
    for path in sorted(KINDS.glob("*.template.json")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        kind = _kind_name(path)
        assert obj["kind"] == kind
        assert set(obj) >= (set(BASE_REQUIRED) | set(KIND_REQUIRED[kind]))
        assert "{{" not in path.read_text(encoding="utf-8")
        assert validate_object(obj) == []
        assert validate_object_id(obj) == []
```

같은 RED 단계에서 Task 5의 실제-install 테스트도 먼저 `tests/test_installer.py`에 추가한다.
source object-template 디렉터리가 아직 없으므로 19종 kind, build notes, core graph, invalid manifest/case
경로 확인이 missing-file로 실패해야 한다. installer recursive walk 자체는 기존 동작이므로 이 순서로만
새 산출물 전파에 대한 실제 RED→GREEN을 만든다.

실행해 source와 실제 설치 결과가 모두 없는 이유로 RED인지 확인한다.

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest \
  tests/test_object_contract_templates.py \
  tests/test_installer.py::InstallTest::test_installs_complete_object_contract_reference_and_second_install_is_noop \
  -q
```

두 테스트의 missing-file/set-mismatch 실패를 각각 scratch 원장에 기록한다.

### 3.2 RED — shape template이 정상 write 전용 경로에도 연결되는지 고정

파일이 아직 없는 같은 RED run에 다음 두 테스트를 함께 둔다.

1. **CodeLocator 정상 mutation fixture**
   - temp git repo를 만들고 `Foo.cpp`에 `void Foo::bar() {}`를 commit한다.
   - `CodeLocator.template.json`을 읽어 repo/path/symbol은 유지하고, runtime full SHA와
     `verified_quote="void Foo::bar() {}"`를 넣는다.
   - `resolve_repo_context()`로 expected repo `demoapp`과 target SHA를 묶는다.
   - `request = MutationRequest(operation=MutationOperation.INGEST,
     brain_root=tmp_path / "brain", repo_context=repo_context, engine_sha="e" * 40,
     objects=(locator,))`를 만들고 `MutationService().plan((locator,), request=request)`를 호출한다.
     결과가 성공하고 engine이
     `verified_at`와 canonical title `Foo::bar`를 확정하는지 확인한다.
   - 이 테스트는 shape-only `validate_object()` 통과를 새 write 성공으로 오해하지 않게 한다.
2. **ReviewRecord 정상 promotion fixture**
   - `GlossaryTerm.template.json`을 candidate로 바꾸고
     `candidate={"candidate_state":"ready_for_review","candidate_source":"spec"}`를 넣는다.
   - `promote([candidate], [candidate["id"]], "single_object", reviewer="user-confirmed",
     reviewed_at="2026-06-04T00:00:00Z")`를 호출한다.
   - promoted term의 `review_record_id`, ReviewRecord의 `target_object_id`, 양쪽 schema/ID 문법을
     확인한다.

두 테스트는 production 동작을 새로 요구하는 게 아니라, 새 JSON template이 현재 공식 write 경로와
정상적으로 연결되는지 검증한다.

### 3.3 GREEN — 고정 합성값 19종 생성

모든 파일은 다음 공통값을 생략 없이 가진다.

```json
{
  "schema_version": "0.1",
  "status": "reviewed",
  "poc_priority": "P0",
  "created_at": "2026-06-04T00:00:00Z",
  "updated_at": "2026-06-04T00:00:00Z",
  "tags": ["ctx"],
  "evidence_refs": []
}
```

파일별 ID와 전용값은 현재 테스트 helper에서 검증된 아래 조합을 쓴다.

| 파일 | ID / variant | 전용 필드 요약 |
|---|---|---|
| `EvidenceManifest.template.json` | `manifest.ctx.source` | `source_type=spec`, `locator=spec://neutral`, approved redaction, internal/team |
| `EvidenceRef.template.json` | `evref.ctx.ref` | manifest ref, `ref_type=spec_section`, locator section 1, summary |
| `ReviewRecord.template.json` | `review.g.ctx.term` | single `target_object_id=g.ctx.term`, approved verdict |
| `EventLedgerRecord.template.json` | `ledger.ctx.event` | rule_change, happened_at, summary, empty related_objects |
| `TemporalFact.template.json` | `fact.ctx.state` | enabled=true, release=test, event ref, high confidence |
| `CodeLocator.template.json` | `code.ctx.loc` | repo demoapp, Foo.cpp, Foo::bar, rg, verified_at; shape-only 경고 |
| `DomainContext.template.json` | `context.ctx` | project demoapp, context key/boundary/scopes/injection/glossary ids |
| `GlossaryTerm.template.json` | `g.ctx.term` | context ref, term/definition, `evref.ctx.ref` evidence |
| `ContextProjection.template.json` | `projection.ctx.context-md` | context_md, context source, 실제 source/projection hash, fail_on_manual_edit |
| `CurrentView.template.json` | `view.feature-status.main` | `view_type=feature_status`, as_of, empty fact/event sources, summary |
| `KnowledgePage.template.json` | `page.guide.main` | category guide, docs/guide.md, source IDs, `stale_policy=manual` |
| `IndexRecord.template.json` | `index.code-locator.21a0af6db18b5997` | index name code_locator, source `mapping.ctx.source`, indexed_at/content_hash |
| `SpecDocument.template.json` | `spec.game-spec` | source_system spec, canonical locator |
| `SpecRevision.template.json` | `revision.game-spec.v2` | spec document ref, label v2, captured_at, empty slide_refs |
| `SlideRef.template.json` | `slide.game-spec.v2.3` | revision ref, slide_no 3 |
| `SlackThread.template.json` | `slack.ctx.thread` | channel/thread, empty participants/message_refs, summary |
| `DecisionRecord.template.json` | `decision.ctx.decision` | clarification, decision text, empty sources/contexts, not_applicable |
| `DomainMapping.template.json` | `mapping.ctx.mapping` | context, key/summary/meaning/boundary, empty glossary/decisions, evidence ref |
| `Insight.template.json` | `insight.ctx.risk` | reviewed cross-cutting-risk, two mapping sources, body/scope |

`ContextProjection` hash는 임의 문자열을 쓰지 않고 현재
`build_context_projection()` 산출값을 한 번 재계산해 고정한다. KnowledgePage stale policy,
IndexRecord content hash 의미, `slide_refs`/`message_refs` 요소 구조는 현재 schema가 정하지 않는다는
경고를 README와 data-contracts에 남긴다.

### 3.4 GREEN — object template README와 19종 계약표

template README에 다음을 명확히 적는다.

- kind 파일은 저장 객체 shape 참고용이지 단독 ingest 보장이 아니다.
- `{{...}}` placeholder가 없고 복사 뒤 ID와 ID-결속 필드를 함께 바꿔야 한다.
- 일반 build section과 `extra_objects[]`의 차이.
- schema/lint와 신규 write verifier의 차이, 특히 CodeLocator.
- 정상 graph와 invalid manifest 사용법.

`data-contracts.md`의 19종 각 행은 공통 외 required, 조건부/금지, truth role, ID 결속, 생성 경로,
참조 cardinality/의도 target, 필드 작성자, 소비자, legacy/write 차이를 갖는다. 다음 현재 빈틈을
검증된 동작처럼 쓰지 않는다.

- reference registry는 대부분 target kind를 강제하지 않는다.
- `slide_refs`, `message_refs`는 registry 밖이다.
- KnowledgePage/IndexRecord/SpecDocument/SpecRevision/SlideRef/SlackThread는 direct-extra-object와
  storage/graph 중심이고 전용 creator/search surface가 없다.
- ContextProjection source IDs는 schema상 empty가 가능하지만 공식 creator는 non-empty를 전제한다.

테스트를 GREEN으로 만든다.

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest \
  tests/test_object_contract_templates.py tests/test_schema.py tests/test_id_grammar.py -q
```

---

## Task 4: 정상 build·연결 그래프와 층별 실패 반례 만들기

**파일**

- 수정: `tests/test_object_contract_templates.py`
- 생성: `src/project_brain/templates/ingest/references/object-templates/build-notes.complete.template.json`
- 생성: `src/project_brain/templates/ingest/references/object-templates/object-graph.complete.template.json`
- 생성: `src/project_brain/templates/ingest/references/object-templates/invalid/manifest.json`
- 생성: `src/project_brain/templates/ingest/references/object-templates/invalid/*.json`

### 4.1 RED — 정상 graph의 연결·typed expectation·lint 검증

`object-graph.complete.template.json`의 top-level을 다음으로 고정하는 테스트를 먼저 쓴다.

```python
{
    "schema_version": 1,
    "name": "core-ingest-graph",
    "objects": [],
}
```

빈 배열은 top-level type만 설명하는 예시다. 실제 파일은 4.2의 여섯 완성 객체를 공통·kind 필드
생략 없이 담고, 테스트는 빈 배열을 허용하지 않는다.

테스트는 다음을 모두 확인한다.

1. object ID 중복이 없다.
2. 모든 object가 `validate_object()`와 ID grammar를 통과한다.
3. `iter_object_refs()`를 무방향 edge로 보았을 때 여섯 객체가 단일 연결 요소다.
4. 아래 pointer별 대상 kind가 정확하다.

```python
EXPECTED_TARGET_KINDS = {
    ("EvidenceRef", "/evidence_manifest_id"): "EvidenceManifest",
    ("DomainContext", "/glossary_term_ids/0"): "GlossaryTerm",
    ("GlossaryTerm", "/context_id"): "DomainContext",
    ("GlossaryTerm", "/evidence_refs/0"): "EvidenceRef",
    ("DomainMapping", "/context_id"): "DomainContext",
    ("DomainMapping", "/glossary_term_ids/0"): "GlossaryTerm",
    ("DomainMapping", "/evidence_refs/0"): "EvidenceRef",
    ("DomainMapping", "/decision_record_ids/0"): "DecisionRecord",
    ("DecisionRecord", "/affected_context_ids/0"): "DomainContext",
    ("DecisionRecord", "/affected_mapping_ids/0"): "DomainMapping",
    ("DecisionRecord", "/source_object_ids/0"): "EvidenceRef",
    ("DecisionRecord", "/evidence_refs/0"): "EvidenceRef",
}
```

5. `store = BrainStore({obj["id"]: obj for obj in objects})`로 구성하고
   `lint_store_report(store) == ()`인지 확인한다.

파일이 없어서 RED인지 확인한다.

### 4.2 GREEN — 여섯 객체 core graph

정확히 다음 객체를 연결한다.

- `manifest.ctx.source`
- `evref.ctx.ref → manifest.ctx.source`
- `context.ctx → g.ctx.term`
- `g.ctx.term → context.ctx, evref.ctx.ref`
- `mapping.ctx.behavior → context.ctx, g.ctx.term, evref.ctx.ref, decision.ctx.change`
- `decision.ctx.change → context.ctx, mapping.ctx.behavior, evref.ctx.ref`

모두 reviewed이며 EvidenceManifest redaction은 approved다. CodeLocator/ReviewRecord/Projection은 실제
repo verifier, promotion, hash 경계가 다르므로 core graph에 억지로 섞지 않는다.

### 4.3 RED — build notes가 실제 `validate_notes()`와 `build()`를 통과하는지 검증

테스트는 `object-graph.complete.template.json`을 seed `BrainStore`로 쓰고,
`build-notes.complete.template.json`을 직접 `validate_notes()`와 `build()`에 넘긴다.
`build()` 결과의 `errors == []`, `preconditions`에 update 대상이 존재함,
`decision.ctx-build.change`가 `mapping.ctx-build.behavior`에 역채움됐음을 확인한다.

### 4.4 GREEN — 아홉 notes section이 모두 보이는 build template

notes에는 다음 고정 합성 시나리오를 넣는다.

- `context`: key `ctx-build`, repo `demoapp`, full 40자 `a` commit, 고정 now, display/boundary/scope,
  새 glossary ID.
- `sources`: `manifest.ctx-build.code`, `manifest.ctx-build.commit`, approved/team.
- `code_anchors`: `handler`, `Foo.cpp`, `Foo::bar`, `void Foo::bar() {}`, code manifest.
- `glossary`: `term`, evidence `evref.ctx-build.handler`.
- `mappings`: `behavior`, glossary key `term`, code key `handler`.
- `decisions`: `change`, clarification, 40자 `b` commit evidence, affects `behavior`.
- `refs`: 현재 `resolve_refs()`의 두 단계 구조를 그대로 써
  `{"glossary": {"existing-term": {"id": "g.ctx.term", "expect": {"kind": "GlossaryTerm", "status": "reviewed"}}}}`.
- `updates`: seed `mapping.ctx.behavior` title 변경, exact `expected_updated_at`,
  `evidence_unchanged=true`.
- `extra_objects`: 완성된 `ledger.ctx-build.note` EventLedgerRecord.

README에 일반 section은 build가 ID/meta를 만들지만 `extra_objects[]`는 완성 저장 객체를 그대로 받는
탈출구이며, 자동 역채움은 `decisions[].affects → DomainMapping.decision_record_ids`로 한정된다고 적는다.

### 4.5 RED — invalid manifest adapter

manifest top-level과 각 case의 계약을 먼저 테스트한다.

```json
{
  "schema_version": 1,
  "cases": [{
    "name": "notes-missing-context-commit",
    "file": "notes-missing-context-commit.json",
    "layer": "notes",
    "validator": "validate_notes",
    "setup": {"mode": "standalone", "base_fixture_files": []},
    "expected": {"code": null, "message_fragment": "context.key·context.commit 필수"},
    "purpose": "build 입력의 context commit 누락을 조용히 통과시키지 않는다"
  }]
}
```

나머지 case도 설계의 layer/validator/setup enum을 사용한다.

- notes/schema: non-empty `message_fragment` 필수.
- lint/mutation: non-empty `code` 필수.
- manifest가 가리킨 파일은 모두 존재해야 한다.
- case를 해당 validator에 태웠을 때 약속한 이유로 실패해야 한다.

### 4.6 GREEN — 실패 반례 10종

다음 파일과 첫 실패 층을 고정한다.

| 파일 | 층 / 기대 |
|---|---|
| `notes-missing-context-commit.json` | notes / `context.key·context.commit 필수` 메시지 |
| `missing-base-required.json` | schema / `title` 필수 누락 메시지 |
| `missing-kind-required.json` | schema / EvidenceManifest `redaction_status` 누락 메시지 |
| `candidate-without-metadata.json` | schema / candidate GlossaryTerm metadata 메시지 |
| `reviewed-without-evidence.json` | schema / reviewed GlossaryTerm evidence 메시지 |
| `invalid-redaction-status.json` | schema / redaction enum 메시지 |
| `dangling-reference.json` | lint / `dangling_reference` |
| `code-locator-without-quote.json` | mutation / `quote_required` |
| `code-locator-coordinate-change-without-quote.json` | mutation / `quote_required` |
| `reviewed-to-candidate.json` | mutation / core의 reviewed `mapping.ctx.behavior` 전체 payload를 candidate로 바꾼 유효 DomainMapping, `status_transition_invalid` |

mutation case adapter는 기존 `tests/test_mutation.py`의 temp git repo/RepoContext helper 계약을
재사용한다. 동적 commit SHA를 JSON placeholder로 만들지 말고 setup adapter가 repo fixture의 full SHA를
주입한 뒤 production `MutationService.plan()`을 호출한다.

### 4.7 legacy 읽기와 신규 쓰기 짝 테스트

같은 테스트 파일에 다음 두 pair를 추가한다.

1. quote 없는 기존 CodeLocator JSON은 `verified_at`가 있으면 `BrainStore.load()`로 읽을 수 있고,
   좌표 불변 ingest에서는 기존 엔진 title/time/quote 부재가 보존된다. 신규·좌표 변경은
   `quote_required`다.
2. 축약 commit SHA인 기존 locator는 load 가능하지만, 신규·좌표 변경 write에 valid quote를 넣고
   verifier를 태우면 exact SHA gate의 `commit_missing`이다. structured object-ID grandfathering과
   섞지 않는다.

기존 `tests/test_mutation.py:1905-2020`와 `tests/test_code_verify.py`의 full-SHA 계약을 링크하고,
새 테스트는 템플릿 시나리오가 그 계약에서 드리프트하지 않게 하는 얇은 adapter로 유지한다.

표적 검증:

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest \
  tests/test_object_contract_templates.py tests/test_assembly.py \
  tests/test_lint.py tests/test_mutation.py tests/test_code_verify.py -q
```

---

## Task 5: 설치 전파와 기존 ingest reference를 새 정본에 연결

**파일**

- 수정: `tests/test_installer.py`
- 수정: `src/project_brain/templates/ingest/references/object-model.md`
- 수정: `src/project_brain/templates/ingest/references/worked-example.md`

### 5.1 GREEN — Task 3에서 먼저 RED로 만든 실제 install 계약 확인

아래 `InstallTest`는 Task 3의 source template 생성 전에 추가해 missing-file RED를 이미 확인한다.
Task 4까지 모든 artifact가 생긴 뒤 같은 테스트를 다시 실행해 GREEN으로 만든다.

```python
def test_installs_complete_object_contract_reference_and_second_install_is_noop(self):
    first = install(self.target, project="demo")
    second = install(self.target, project="demo")
    root = (
        self._skill_dir("demo-brain-ingest")
        / "references/object-templates"
    )
    expected_non_kind = {
        "README.md",
        "build-notes.complete.template.json",
        "object-graph.complete.template.json",
        "invalid/manifest.json",
        "invalid/notes-missing-context-commit.json",
        "invalid/missing-base-required.json",
        "invalid/missing-kind-required.json",
        "invalid/candidate-without-metadata.json",
        "invalid/reviewed-without-evidence.json",
        "invalid/invalid-redaction-status.json",
        "invalid/dangling-reference.json",
        "invalid/code-locator-without-quote.json",
        "invalid/code-locator-coordinate-change-without-quote.json",
        "invalid/reviewed-to-candidate.json",
    }
    self.assertTrue(all((root / rel).is_file() for rel in expected_non_kind))
    kind_files = {p.name.removesuffix(".template.json")
                  for p in (root / "kinds").glob("*.template.json")}
    from project_brain.schema import VALID_KINDS
    self.assertEqual(kind_files, VALID_KINDS)
    invalid_manifest = json.loads(
        (root / "invalid/manifest.json").read_text(encoding="utf-8")
    )
    self.assertEqual(
        {case["file"] for case in invalid_manifest["cases"]},
        {Path(rel).name for rel in expected_non_kind if rel.startswith("invalid/")
         and rel != "invalid/manifest.json"},
    )
    for path in root.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
    for key in ("created", "updated", "removed", "adopted", "skipped"):
        self.assertEqual(second[key], [])
```

### 5.2 GREEN — installer는 기존 recursive 배포를 그대로 사용

production installer는 수정하지 않는다. source reference가 ingest template 아래 생기면 기존 recursive
walk가 자동 배포해야 한다. JSON에 임의 `{{...}}`가 없어
`test_real_templates_render_with_synthetic_values`도 통과해야 한다.

`object-model.md`는 11종 “주요 kind” 표가 전체 계약처럼 보이지 않게 19종 정본과 installed
object template 경로를 안내한다. 이 파일은 소비 프로젝트에도 설치되므로 엔진 repo 상대 Markdown
링크를 만들지 않는다. 설치본에서는 같은 `references/object-templates/`를 상대 링크하고,
엔진 checkout의 상세 정본 경로 `docs/architecture/data-contracts.md`는 코드 경로로 병기한다.
`worked-example.md`는 prose example만 남기지 말고 실제 `build-notes.complete.template.json`,
`object-graph.complete.template.json`, invalid manifest를 실행 순서대로 링크한다.

표적 검증:

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest \
  tests/test_installer.py tests/test_ingest_skill_contract.py -q
PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
```

---

## Task 6: AGENTS·README·ROADMAP 길찾기와 작은 계보 메모 완성

**파일**

- 수정: `tests/test_architecture_docs.py`
- 수정: `AGENTS.md`
- 수정: `README.md`
- 수정: `ROADMAP.md`
- 수정: `docs/architecture/README.md`

### 6.1 RED — 세 진입점이 architecture map을 가리키는지 검증

다음을 먼저 테스트한다.

```python
def test_primary_entrypoints_link_to_architecture_map():
    for rel in ("AGENTS.md", "README.md", "ROADMAP.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "docs/architecture/README.md" in text
```

아직 링크가 없어 RED인지 확인한다.

### 6.2 GREEN — 작업 종류별 진입표

`AGENTS.md`에 세부 계약을 복제하지 않고 다음 라우팅을 추가한다.

- 전체 구조·데이터 흐름 → architecture README/runtime map
- 적재 객체·필드·관계 → data contracts + JSON templates
- 검색·라우터 → change map 검색 행 + search internals
- mutation·migration → runtime write path + change map
- 의도·설계 경계 → design canonical
- 현재 완료·미뤄둔 일 → ROADMAP
- 과거 이유 → 연결된 dated spec/plan/report, 단 current code/test 대조 필수

README와 ROADMAP 상단에도 architecture map 링크 한 줄만 추가한다.

### 6.3 현재 repo 근거만 쓴 계보 메모

architecture README 하단에 작은 표 하나만 둔다.

| 분류 | 근거 | 현재 관계 |
|---|---|---|
| 설계 반영 | Karpathy LLM Wiki | raw-first·누적 구조화 산물 원칙; design canonical/object-model spec 링크 |
| 설계 반영 | Matt Pocock식 `CONTEXT.md` | 공유 도메인 어휘 아이디어가 DomainContext/GlossaryTerm으로 진화, generated CONTEXT는 disposable projection |
| 초기 참고·부분 반영 | GBrain | Markdown/DB 분리 참고에서 DB/index를 disposable projection으로 채택; GBrain 코드 기반 직접 적용 주장은 하지 않음 |
| 내부 진화 | BB2 | 내부 도구에서 2026-06-11 범용 엔진으로 분리; ROADMAP 링크 |

추가 외부 링크 조사나 발표용 서사는 만들지 않는다. 구현 적용을 직접 입증하지 못한 항목은
`구현 적용`으로 올리지 않는다.

표적 검증:

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest \
  tests/test_architecture_docs.py -q
git diff --check
```

---

## Task 7: 문맥 없는 cold-agent 리허설을 실제 완료 관문으로 실행

**파일**

- 생성: `docs/reports/2026-08-04-project-brain-architecture-foundation.md`
- 수정 가능: `docs/architecture/*.md`, `AGENTS.md` — 리허설 실패 원인만 보강

### 7.1 먼저 코드 기반 정답표 작성

보고서에 세 시나리오의 최소 정답을 현재 production symbol/test path와 함께 적는다.

1. query: config → store → classify/exact route → optional recall → redaction/stale/status → 답변.
   search와 fresh-index 요구를 분리한다.
2. tokenizer: `tokenize_ko.py`와 index/search 관련 테스트, 엔진 suite, 소비 checks/eval,
   index 입력이 달라지므로 실모델 rebuild 필요.
3. CodeLocator: load/schema와 mutation verifier 비대칭, quote/full SHA/repo context, 정상 template와
   mutation tests.

### 7.2 fork context 없는 답변자 3명을 병렬 실행

각 agent는 `fork_turns="none"`으로 만들고 다음 공통 지시만 준다.

```text
작업 위치는 /Users/al03040455/Downloads/codes/project-brain/.worktrees/architecture-foundation 이다.
이 대화의 이전 문맥은 주어지지 않았다. 먼저 AGENTS.md를 읽고, 저장소의 현재 문서·코드·테스트만
근거로 시나리오에 답하라. 날짜 plan 하나를 현재 정본으로 쓰지 말고 production symbol과 직접
test path를 제시하라. 파일은 수정하지 마라.
```

각 agent에게 시나리오 하나만 준다. 보고서에는 정확한 prompt, `fork_turns=none`, task name,
답변 전문을 남긴다.

### 7.3 독립 판정자 실행

세 답을 보고서에 쓴 뒤 다른 agent를 `fork_turns="none"`으로 실행한다. 판정자는 report,
AGENTS, architecture docs, production code/test를 읽고 설계 §9의 PASS 기준별로 각 답을 판정한다.

- 세 시나리오 모두 PASS여야 진행한다.
- 하나라도 FAIL이면 해당 문서만 보강하고 새 task name의 cold agent로 실패 시나리오를 다시 실행한다.
- 외부 blocker로 반복할 수 없으면 Goal을 complete가 아니라 blocked로 끝낸다.

### 7.4 보고서에 gap 분류

다음을 구분해 기록한다.

- `DOC_DRIFT`: 이번에 수정한 README/기존 reference 오해
- `TEMPLATE_GAP`: 이번에 채운 19종/graph/invalid examples
- `ENGINE_GAP`: query principal ACL 미집행, untyped refs, registry 밖 slide/message refs,
  creator/search surface 없는 6종, projection empty-source 불명확성
- `LEGACY_DEBT`: 기존 실코퍼스 quote/full-SHA 누락은 수치 재조사·수정하지 않음
- `HISTORICAL_ONLY`: 과거 계획과 현재 동작이 다른 설명

---

## Task 8: 광범위 독립 리뷰와 fresh verification

**파일**

- 수정 가능: 위 작업 파일 중 리뷰 blocker가 있는 파일
- 수정: `.superpowers/architecture-foundation/progress.md`

### 8.1 병렬 독립 리뷰

서로 다른 reviewer에게 다음을 맡긴다.

1. architecture docs vs CLI/runtime/code/test 정확성, 문서 권위·2-레포·query/search·aux writes.
2. 19종 JSON/graph/build/invalid/legacy-write 테스트 정확성, installer 전파.
3. 범위 준수: production behavior 무변경, Task 17 canon 보존, 계보 과장 없음, no consumer data.

각 reviewer는 blocker/important/minor와 `READY`/`CHANGES_REQUIRED`를 단정한다. blocker와 important를
수정한 뒤 해당 reviewer에게 재검토를 요청한다.

### 8.2 표적 테스트

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest -q \
  tests/test_architecture_docs.py \
  tests/test_object_contract_templates.py \
  tests/test_installer.py
```

### 8.3 전체 engine·installed runtime fresh run

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest -q
PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
git diff --check
```

출력의 pass 수는 완료 보고서의 실행 증거에는 적되 살아 있는 architecture 문서에는 고정하지 않는다.

### 8.4 변경 범위·setup 정리

```bash
git status --short
git diff --stat
git diff -- AGENTS.md README.md ROADMAP.md docs src/project_brain/templates tests
```

allowlist를 실행하기 전에 task-owned setup/scratch를 다음 순서로 정리한다.

1. `progress.md`, `object-kind-matrix.md`, `template-fixture-blueprint.md`,
   `runtime-map-evidence.md`에서 최종 보고서와 architecture 문서에 보존할 근거가 모두 옮겨졌는지
   확인한다.
2. `apply_patch`로 다음 네 task-owned scratch 파일만 명시적으로 삭제한다.
   - `.superpowers/architecture-foundation/progress.md`
   - `.superpowers/architecture-foundation/object-kind-matrix.md`
   - `.superpowers/architecture-foundation/template-fixture-blueprint.md`
   - `.superpowers/architecture-foundation/runtime-map-evidence.md`
3. `rmdir .superpowers/architecture-foundation .superpowers`로 빈 task-owned 디렉터리만 제거한다.
4. `test -L .venv`와
   `test "$(readlink .venv)" = "/Users/al03040455/Downloads/codes/project-brain/.venv"`로 우리가 만든
   symlink임을 확인하고,
   `test -x /Users/al03040455/Downloads/codes/project-brain/.venv/bin/python`으로 원본 interpreter를
   검증한 뒤 `unlink .venv`로 링크만 제거한다.
5. `git status --porcelain=v1 --untracked-files=all`에 `.superpowers`와 `.venv`가 없음을 확인한다.

위 `git diff` 명령은 tracked 수정만 보여 주므로, 다음 read-only allowlist 검사로 untracked 새 파일까지
정확히 고정한다.

```bash
PYTHONPATH="$PWD/src" /Users/al03040455/Downloads/codes/project-brain/.venv/bin/python - <<'PY'
import subprocess
from pathlib import Path

from project_brain.schema import VALID_KINDS

modified = {
    "AGENTS.md",
    "README.md",
    "ROADMAP.md",
    "src/project_brain/templates/ingest/references/object-model.md",
    "src/project_brain/templates/ingest/references/worked-example.md",
    "tests/test_installer.py",
}
new = {
    "docs/superpowers/specs/2026-08-04-project-brain-architecture-foundation-design.md",
    "docs/superpowers/plans/2026-08-04-project-brain-architecture-foundation.md",
    "docs/architecture/README.md",
    "docs/architecture/runtime-map.md",
    "docs/architecture/data-contracts.md",
    "docs/architecture/change-map.md",
    "docs/reports/2026-08-04-project-brain-architecture-foundation.md",
    "tests/test_architecture_docs.py",
    "tests/test_object_contract_templates.py",
    "src/project_brain/templates/ingest/references/object-templates/README.md",
    "src/project_brain/templates/ingest/references/object-templates/build-notes.complete.template.json",
    "src/project_brain/templates/ingest/references/object-templates/object-graph.complete.template.json",
    "src/project_brain/templates/ingest/references/object-templates/invalid/manifest.json",
}
invalid_names = {
    "notes-missing-context-commit.json",
    "missing-base-required.json",
    "missing-kind-required.json",
    "candidate-without-metadata.json",
    "reviewed-without-evidence.json",
    "invalid-redaction-status.json",
    "dangling-reference.json",
    "code-locator-without-quote.json",
    "code-locator-coordinate-change-without-quote.json",
    "reviewed-to-candidate.json",
}
new |= {
    f"src/project_brain/templates/ingest/references/object-templates/invalid/{name}"
    for name in invalid_names
}
new |= {
    "src/project_brain/templates/ingest/references/object-templates/"
    f"kinds/{kind}.template.json"
    for kind in VALID_KINDS
}

actual = set(subprocess.run(
    ["git", "status", "--porcelain=v1", "--untracked-files=all"],
    check=True,
    capture_output=True,
    text=True,
).stdout.splitlines())
expected = {f" M {path}" for path in modified} | {f"?? {path}" for path in new}
assert actual == expected, {
    "unexpected": sorted(actual - expected),
    "missing": sorted(expected - actual),
}

for relative in sorted(new):
    text = Path(relative).read_text(encoding="utf-8")
    assert text.endswith("\n"), f"missing final newline: {relative}"
    for line_no, line in enumerate(text.splitlines(), 1):
        assert line == line.rstrip(" \t"), f"trailing whitespace: {relative}:{line_no}"
PY
git diff --check
```

확인 사항:

- 위 porcelain 결과가 exact allowlist와 같아야 하며, untracked 새 파일도 전부 독립 리뷰와
  trailing-whitespace/final-newline 검사를 통과해야 한다.
- `src/project_brain/*.py` production 동작 파일에는 diff가 없어야 한다.
- `docs/design-canonical.md:152-227` Task 17 상세가 보존돼야 한다.
- 소비 프로젝트와 원래 dirty checkout의 미추적 파일은 건드리지 않는다.
- worktree setup용 `.venv` symlink를 제거하고 `git status --short`에 남지 않게 한다.
- 커밋·push·PR을 만들지 않는다.

### 8.5 완료 판정

다음이 모두 참일 때만 Goal을 complete로 갱신한다.

- 독립 spec review READY
- 새 산출물을 먼저 요구한 artifact 테스트의 RED→GREEN 증거와, 기존 동작을 고정한
  characterization 테스트의 즉시 GREEN 근거
- cold-agent 세 시나리오 전부 PASS + 독립 판정
- 최종 reviewer 전부 READY 또는 남은 minor가 보고서에 분리됨
- engine 전체와 installed runtime 전체 PASS
- installer 두 번째 실행 no-op PASS
- `git diff --check` PASS
- setup symlink 제거, no commit/push, production/consumer data 무변경
