# Brain Ingest Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Project Brain의 모든 제품 쓰기를 검증·journal transaction 경계로 통합하고, BB2의 `petskill-kamehameha`와 `ingame-item-usage`를 안전하게 복구한 뒤 전수 ID/display 부채를 정리한다.

**Architecture:** 엔진은 `ID registry → reference registry → Git quote/symbol verifier → MutationService → journaled corpus I/O` 순으로 fail-closed한다. 조회는 검수된 DomainMapping을 의미 정본으로 사용하고 CodeLocator는 `object_id/path/symbol/quote_access`만 제공한다. BB2 복구는 전체 재적재가 아니라 full snapshot에서 만든 staging manifest를 context별로 적용하고, 각 단계 사이에 새 snapshot과 회귀 게이트를 둔다.

**Tech Stack:** Python 3.11+, pytest/unittest, `fcntl`, Git plumbing, SQLite/FTS5, Tree-sitter Python binding + C++ grammar, JSON, Bash, jq

---

## 구현 기준과 금지선

- 정본 설계는 `docs/superpowers/specs/2026-07-28-brain-ingest-recovery-design.md`다.
- 이 계획은 기존 `docs/plans/2026-07-27-ingest-fix-execution-plan.md`를 대체한다. 이전 계획의 T6/T7 warning 방식, 선삭제 후 재적재, 의미형 anchor 103개 작명, 일부 title 백필은 실행하지 않는다.
- 현재 원본 worktree의 미커밋 변경은 승인된 구현이 아니다. 깨끗한 worktree에서 테스트로 다시 구현한다.
- 원본 worktree에서 재사용할 판단은 세 가지뿐이다.
  - CodeLocator `title=symbol`
  - dict fold 전 중복 완성 ID와 논리 key 거부
  - 사전조건 대상 소실 거부
- 원본 worktree의 다음 변경은 그대로 가져오지 않는다.
  - 외부 입력 `verified_at` 필수
  - EvidenceRef title을 일반 update allowlist로 개방
  - no-DB 폴백에서 CodeLocator 전량 ID 반환
- 전체 코퍼스 재적재, `--no-quote-verify`, `--allow-unverifiable`, 자동 roll-forward는 금지한다.
- BB2 객체를 사람이 직접 읽는 흐름을 메인 UX로 만들지 않는다. 사용자는 query로 묻고, 에이전트가 검수된 의미와 공개 가능한 근거를 소비한다. graph/show는 점검용 보조 수단이다.
- `docs/superpowers/plans/2026-07-27-handoff-consumer.md`의 Task 3과 이 계획이 충돌한다. `corpus_io.py`와 mutation 경계는 이 계획이 먼저 소유한다. handoff consumer 구현 시 그 Task 3을 독립 구현하지 말고 이 계획의 API를 재사용하도록 계획을 갱신한다.

## 현재 고정 기준

구현 시작 시 다시 측정하되, 달라졌으면 진행하지 말고 baseline report에 원인을 기록한다.

| 항목 | 2026-07-28 기준 |
|---|---:|
| 엔진 시작 commit | `36baa7347f3f5b6e24c1da21475150b882e413e6` |
| BB2 repo commit | `d1294e7032d6304fe4371e7792b7a8e3010f3e5c` |
| 전체 객체 | 11,097 |
| CodeLocator | 3,886 |
| quote 보유 / 누락 | 579 / 3,307 |
| 광선발사 / 인게임 | 456 / 945 |
| 19종 grammar 위반 후보 | 119 |
| 위반 ID 객체 참조 | 65파일 187회 |
| eval 포함 참조 | 66파일 190회 |
| stale-set 위반 ID | 27 |

BB2 현재 작업공간에는 별도의 사용자 변경이 있다. 특히 `brain/checks/test_real_corpus.py`와
disturb-bubble/ingame-area-expansion CodeLocator 변경은 보존해야 한다. 또한 로컬
`.git/info/exclude`의 `/brain` 때문에 새 광선발사 객체 456개는 디스크에 있지만 Git에서
추적되지 않는다. 복구 성공 후 manifest의 최종 output 경로만 정확히 force-add해야 한다.

## 파일 지도

| 책임 | 파일 |
|---|---|
| 19종 ID 정본 | `src/project_brain/id_grammar.py` |
| 객체 참조 정본 | `src/project_brain/reference_fields.py` |
| repo/Git/quote/symbol 검증 | `src/project_brain/code_verify.py`, `src/project_brain/repo_context.py`, `src/project_brain/symbol_verify.py` |
| 저수준 lock/fsync/journal | `src/project_brain/corpus_io.py` |
| 공통 제품 쓰기 경계 | `src/project_brain/mutation.py` |
| snapshot/context replace | `src/project_brain/snapshot.py`, `src/project_brain/context_replace.py` |
| ID/display migration | `src/project_brain/migration.py` |
| audit 상태축 | `src/project_brain/audit.py`, `src/project_brain/quote_access.py` |
| CLI | `src/project_brain/cli.py` |
| 조회 계약 | `src/project_brain/search.py`, `src/project_brain/router.py`, `src/project_brain/graph_viz.py` |
| 조립/적재/승격 | `src/project_brain/assembly.py`, `src/project_brain/ingest.py`, `src/project_brain/promote.py`, `src/project_brain/stale_check.py` |
| 설치 원본 | `src/project_brain/templates/{ingest,query,audit}/` |
| BB2 복구 산출물 | `brain/recovery/2026-07-28/` |
| BB2 새 회귀 | `brain/checks/test_ingest_recovery.py` |

### Task 0: 깨끗한 엔진 worktree와 재현 가능한 baseline을 만든다

**Files:**
- Create: `docs/reports/2026-07-28-ingest-recovery-baseline.md`
- Read only: `/Users/al03040455/Downloads/codes/project-brain/AGENTS.md`
- Read only: `/Users/al03040455/.agents/shared-guidance.md`
- Read only: `/Users/al03040455/.agents/rules/response-discipline.md`
- Read only: `/Users/al03040455/.agents/rules/python-resolution.md`

- [ ] **Step 1: 원본 dirty 상태를 기록하고 worktree 경로가 안전한지 확인한다**

```bash
ENGINE_SOURCE=/Users/al03040455/Downloads/codes/project-brain
git -C "$ENGINE_SOURCE" status --short
git -C "$ENGINE_SOURCE" rev-parse HEAD
git -C "$ENGINE_SOURCE" check-ignore -q .worktrees
test "$(git -C "$ENGINE_SOURCE" rev-parse HEAD)" = 36baa7347f3f5b6e24c1da21475150b882e413e6
test ! -e "$ENGINE_SOURCE/.worktrees/brain-ingest-recovery"
```

Expected: HEAD가 정확히 `36baa73…`, `.worktrees`가 ignore됨, 대상 경로가 없음. 원본 dirty
파일은 수정·stash·commit하지 않는다.

- [ ] **Step 2: 전용 branch/worktree를 만든다**

```bash
ENGINE_SOURCE=/Users/al03040455/Downloads/codes/project-brain
ENGINE_WORKTREE="$ENGINE_SOURCE/.worktrees/brain-ingest-recovery"
git -C "$ENGINE_SOURCE" worktree add \
  "$ENGINE_WORKTREE" \
  -b fix/brain-ingest-recovery \
  36baa7347f3f5b6e24c1da21475150b882e413e6
```

- [ ] **Step 3: dependency와 baseline 테스트를 고정한다**

```bash
ENGINE_WORKTREE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery
cd "$ENGINE_WORKTREE"
uv sync --extra mecab
PYTHONPATH="$ENGINE_WORKTREE/src" "$ENGINE_WORKTREE/.venv/bin/python" -m pytest -q
PYTHONPATH="$ENGINE_WORKTREE/src" "$ENGINE_WORKTREE/.venv/bin/python" \
  -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
```

Expected: 두 suite 모두 PASS. 실패하면 새 구현으로 넘어가지 않고 baseline failure를 보고한다.

- [ ] **Step 4: baseline report에 양쪽 SHA와 dirty 경계를 적는다**

다음 필드를 실제 출력값으로 채운다.

```markdown
engine_source_head:
engine_worktree_head:
engine_source_dirty_paths:
bb2_head:
bb2_dirty_paths:
bb2_local_exclude_brain: true
baseline_pytest:
baseline_template_unittest:
```

- [ ] **Step 5: baseline report만 commit한다**

```bash
git add docs/reports/2026-07-28-ingest-recovery-baseline.md
git commit -m "docs(brain): record ingest recovery baseline"
```

### Task 1: 19종 ID parser/formatter registry를 단일 정본으로 만든다

**Files:**
- Create: `src/project_brain/id_grammar.py`
- Create: `tests/test_id_grammar.py`
- Modify: `src/project_brain/schema.py`
- Modify: `src/project_brain/assembly.py`
- Modify: `src/project_brain/context_projection.py`
- Modify: `src/project_brain/promote.py`
- Test: `tests/test_schema.py`
- Test: `tests/test_assembly.py`
- Test: `tests/test_context_projection.py`
- Test: `tests/test_promote.py`

- [ ] **Step 1: 19종 coverage와 특수 variant RED 테스트를 작성한다**

테스트는 최소한 다음 계약을 고정한다.

```python
def test_registry_exactly_covers_schema_kinds():
    assert frozenset(ID_GRAMMARS) == VALID_KINDS

def test_review_record_variants_round_trip():
    assert parse_id("review.mapping.ctx.key", "ReviewRecord").variant == "single"
    assert parse_id("review.bundle.ctx.key", "ReviewRecord").variant == "bundle"

def test_context_projection_variants_round_trip():
    assert parse_id("projection.ctx.context-md", "ContextProjection").variant == "context_md"
    assert parse_id("projection.ctx.requirement.reuse", "ContextProjection").variant == "reuse"

def test_anchor_suffix_is_not_pollution():
    assert parse_id("code.ctx.shoot-action--6", "CodeLocator").anchor_key == "shoot-action--6"

def test_uppercase_jira_internal_key_is_rejected():
    assert validate_id_fields({
        "id": "evref.ctx.jira-LGBBTWO-234",
        "kind": "EvidenceRef",
    })
```

unknown kind/prefix, underscore, 빈 조각, leading zero decimal, 잘못된 IndexRecord digest,
ReviewRecord target 불일치, SpecRevision/SlideRef 참조 key 불일치도 각각 독립 테스트로 둔다.

- [ ] **Step 2: RED를 확인한다**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_id_grammar.py tests/test_schema.py \
  tests/test_assembly.py tests/test_context_projection.py tests/test_promote.py -q
```

Expected: `id_grammar` import 실패와 기존 permissive ID 때문에 FAIL.

- [ ] **Step 3: exact public API를 구현한다**

`id_grammar.py`의 외부 API는 이 모양으로 고정한다.

```python
@dataclass(frozen=True)
class ParsedId:
    kind: str
    object_id: str
    variant: str
    fields: Mapping[str, str | int]

class IdGrammarError(ValueError):
    pass

ID_GRAMMARS: Mapping[str, IdGrammar]

def parse_id(object_id: str, kind: str | None = None) -> ParsedId:
    raise IdGrammarError

def format_id(kind: str, **fields: str | int) -> str:
    raise IdGrammarError

def validate_id_fields(obj: Mapping[str, object]) -> list[str]:
    return []
```

registry의 exact 형식:

| Kind | 형식 |
|---|---|
| EvidenceManifest | `manifest.{ctx}.{key}` |
| EvidenceRef | `evref.{ctx}.{anchor_key}` |
| ReviewRecord | `review.{target_object_id}` 또는 `review.bundle.{ctx}.{key}` |
| EventLedgerRecord | `ledger.{ctx}.{key}` |
| TemporalFact | `fact.{ctx}.{key}` |
| CodeLocator | `code.{ctx}.{anchor_key}` |
| DomainContext | `context.{ctx}` |
| GlossaryTerm | `g.{ctx}.{key}` |
| ContextProjection | `projection.{ctx}.context-md` 또는 `projection.{ctx}.{requirement_key}.reuse` |
| CurrentView | `view.{view_type}.{key}` |
| KnowledgePage | `page.{category}.{key}` |
| IndexRecord | `index.{index_name}.{source_id_digest}` |
| SpecDocument | `spec.{document_key}` |
| SpecRevision | `revision.{document_key}.{revision_key}` |
| SlideRef | `slide.{document_key}.{revision_key}.{decimal}` |
| SlackThread | `slack.{ctx}.{key}` |
| DecisionRecord | `decision.{ctx}.{key}` |
| DomainMapping | `mapping.{ctx}.{key}` |
| Insight | `insight.{ctx}.{key}` |

prefix만 보고 통과시키는 fallback은 두지 않는다. `assembly.derive_id`, projection ID 생성,
ReviewRecord ID 생성은 문자열 결합 대신 `format_id()`를 호출한다.

- [ ] **Step 4: schema가 ID와 객체 필드의 일치를 강제하게 한다**

`validate_object()`의 enum/필수 필드 검사 뒤에 `validate_id_fields()`를 붙인다.
`VALID_KINDS != ID_GRAMMARS.keys()`이면 import 시점이나 테스트 수집 시점에 즉시 실패시킨다.

- [ ] **Step 5: focused suite를 통과시키고 commit한다**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_id_grammar.py tests/test_schema.py \
  tests/test_assembly.py tests/test_context_projection.py tests/test_promote.py -q
git add src/project_brain/id_grammar.py src/project_brain/schema.py \
  src/project_brain/assembly.py src/project_brain/context_projection.py \
  src/project_brain/promote.py tests/test_id_grammar.py tests/test_schema.py \
  tests/test_assembly.py tests/test_context_projection.py tests/test_promote.py
git commit -m "feat(brain): enforce canonical object id grammar"
```

### Task 2: 객체 참조 필드를 한 registry로 통합한다

**Files:**
- Create: `src/project_brain/reference_fields.py`
- Create: `tests/test_reference_fields.py`
- Modify: `src/project_brain/graph.py`
- Modify: `src/project_brain/lint.py`
- Test: `tests/test_graph.py`
- Test: `tests/test_lint.py`

- [ ] **Step 1: scalar/list/nested reference와 외부 ID 구분 RED 테스트를 작성한다**

```python
def test_nested_code_locator_reference_is_discovered():
    obj = {
        "id": "evref.ctx.anchor",
        "kind": "EvidenceRef",
        "locator": {"code_locator_id": "code.ctx.anchor"},
    }
    assert list(iter_object_refs(obj)) == [
        ObjectRef("/locator/code_locator_id", "code.ctx.anchor")
    ]

def test_external_ids_are_not_brain_references():
    obj = {
        "jira_issue_ids": ["LGBBTWO-234"],
        "channel_id": "C123",
        "project_id": "bb2",
    }
    assert list(iter_object_refs(obj)) == []
```

`target_object_id(s)`, `source_object_id(s)`, `review_record_id`, `context_id`,
`evidence_manifest_id`, `derived_from_event_id`, mapping/decision/insight/projection 관련 list,
`related_objects`, `vouched_by_mapping_ids`, nested locator를 전부 parameterized test로 고정한다.

- [ ] **Step 2: exact registry와 JSON pointer rewrite를 구현한다**

외부 API:

```python
@dataclass(frozen=True)
class ObjectRef:
    pointer: str
    object_id: str

SCALAR_REFERENCE_FIELDS: frozenset[str]
LIST_REFERENCE_FIELDS: frozenset[str]
NESTED_REFERENCE_POINTERS: tuple[str, ...]

def iter_object_refs(obj: Mapping[str, object]) -> Iterator[ObjectRef]:
    yield from ()

def rewrite_object_refs(
    obj: Mapping[str, object],
    replacements: Mapping[str, str],
) -> tuple[dict, tuple[ObjectRef, ...]]:
    return dict(obj), ()
```

rewrite는 registry에 없는 문자열을 건드리지 않고, 실제 바뀐 JSON pointer와 old ID를
결정론적으로 정렬해 돌려준다.

- [ ] **Step 3: graph와 lint가 같은 registry를 쓰게 한다**

`graph.INBOUND_REF_FIELDS`의 중복 정의를 없애고 `iter_object_refs()`로 edges와 isolated
인덱스를 만든다. `lint_store()`의 수동 dangling loop도 같은 helper로 교체하되 기존
도메인별 메시지와 lifecycle 검사는 유지한다.

- [ ] **Step 4: focused suite와 회귀를 통과시키고 commit한다**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_reference_fields.py tests/test_graph.py tests/test_lint.py -q
git add src/project_brain/reference_fields.py src/project_brain/graph.py \
  src/project_brain/lint.py tests/test_reference_fields.py \
  tests/test_graph.py tests/test_lint.py
git commit -m "refactor(brain): centralize object reference fields"
```

### Task 3: repo identity, quote, C++ symbol 검증을 구조화한다

**Files:**
- Create: `src/project_brain/repo_context.py`
- Create: `src/project_brain/symbol_verify.py`
- Create: `tests/test_repo_context.py`
- Create: `tests/test_symbol_verify.py`
- Modify: `src/project_brain/code_verify.py`
- Modify: `tests/test_code_verify.py`
- Modify: `src/project_brain/config.py`
- Modify: `tests/test_config.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: dependency와 오류 분류 RED 테스트를 작성한다**

Tree-sitter의 Python API는 `Language(tree_sitter_cpp.language())`와
`Parser(language)` 형태로 고정한다. 참고:
[py-tree-sitter 공식 README](https://github.com/tree-sitter/py-tree-sitter/blob/master/README.md).

`pyproject.toml`에는 다음을 추가하고 `uv lock`으로 lockfile을 갱신한다.

```toml
"tree-sitter>=0.25,<0.26",
"tree-sitter-cpp==0.23.4",
```

RED 테스트는 다음 error code를 각각 재현한다.

```text
not_git_repo
repo_identity_mismatch
commit_missing
shallow_or_unfetched
commit_not_reachable
path_missing_at_commit
blob_read_failed
quote_not_found
symbol_mismatch
symbol_verification_missing
```

- [ ] **Step 2: RepoContext와 VerificationFailure API를 구현한다**

```python
@dataclass(frozen=True)
class RepoContext:
    repo_root: Path
    expected_repo_id: str
    expected_revision_ref: str
    target_revision_sha: str

@dataclass(frozen=True)
class VerificationFailure:
    locator_id: str
    code: str
    detail: str

def resolve_repo_context(
    repo_root: Path,
    *,
    expected_repo_id: str,
    configured_repo_id: str,
    expected_revision_ref: str,
) -> RepoContext:
    raise RepoVerificationError
```

`repo_root`와 `brain_root`는 absolute path만 허용한다. `git rev-parse --show-toplevel`의
resolve 결과가 `repo_root`와 정확히 같아야 한다. config의 `repo`, 각 CodeLocator의
`repo`, `expected_repo_id`가 모두 같아야 한다.

- [ ] **Step 3: full blob의 quote byte range와 AST symbol relation을 검증한다**

`symbol_verify.py`는 `.c/.cc/.cpp/.cxx/.h/.hh/.hpp`만 자동 지원한다.
quote를 blob에서 찾은 byte range와 교차하는 AST node를 검사한다.

```python
class SymbolStatus(StrEnum):
    VERIFIED = "verified"
    MANUAL_VERIFIED = "manual_verified"
    MISMATCH = "mismatch"
    UNSUPPORTED = "unsupported"

@dataclass(frozen=True)
class SymbolVerification:
    status: SymbolStatus
    canonical_symbol: str
    evidence: str

def verify_symbol_relation(
    *,
    path: str,
    blob: bytes,
    quote_start: int,
    quote_end: int,
    symbol: str,
) -> SymbolVerification:
    return SymbolVerification(SymbolStatus.UNSUPPORTED, symbol, "unsupported extension")
```

`Foo::bar`는 leaf `bar`와 scope `Foo`를 모두 확인한다. enum/상수는 identifier node 경계를
확인한다. `/`, 괄호 설명, 한글 설명이 섞인 old symbol은 자동 통과시키지 않는다.
미지원 파일은 구조화된 `manual_symbol_verification` 없이는 신규 쓰기를 막는다. 수동
증거에는 `reviewer/repo/commit/path/symbol/quote_sha256/rationale`를 모두 요구한다.

- [ ] **Step 4: code verifier가 quote와 symbol을 한 번에 확인하게 한다**

검증 성공 시 caller timestamp를 받지 않고 엔진 `now_kst()`를 찍어 다음 결과를 돌려준다.

```python
@dataclass(frozen=True)
class VerifiedLocator:
    locator: dict
    quote_sha256: str
    verified_at: str
    symbol_status: str

def verify_locator_for_write(
    locator: Mapping[str, object],
    *,
    repo: RepoContext,
    manual_symbol_verification: Mapping[str, object] | None = None,
) -> VerifiedLocator:
    raise CodeVerificationError
```

- [ ] **Step 5: focused tests를 통과시키고 commit한다**

```bash
uv lock
uv sync --extra mecab
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_repo_context.py tests/test_symbol_verify.py \
  tests/test_code_verify.py tests/test_config.py -q
git add pyproject.toml uv.lock src/project_brain/repo_context.py \
  src/project_brain/symbol_verify.py src/project_brain/code_verify.py \
  src/project_brain/config.py tests/test_repo_context.py \
  tests/test_symbol_verify.py tests/test_code_verify.py tests/test_config.py
git commit -m "feat(brain): verify repository quotes and symbols"
```

### Task 4: MutationService의 순수 preflight와 manifest를 구현한다

**Files:**
- Create: `src/project_brain/mutation.py`
- Create: `tests/test_mutation.py`
- Modify: `src/project_brain/store.py`
- Modify: `src/project_brain/schema.py`
- Modify: `src/project_brain/lint.py`
- Modify: `tests/test_lint.py`

- [ ] **Step 1: 검증 순서와 sequence 중복 RED 테스트를 작성한다**

최소 테스트:

```python
def test_duplicate_full_id_is_rejected_before_dict_fold():
    result = service.plan([object_a, object_a_copy], request=request)
    assert result.error_code == "duplicate_object_id"

def test_missing_precondition_target_is_rejected():
    assert service.plan([replacement], request=request).error_code == "precondition_target_missing"

def test_external_verified_at_is_ignored():
    planned = service.plan([locator_with_fake_time], request=request)
    assert planned.after["verified_at"] != locator_with_fake_time["verified_at"]

def test_legacy_id_only_is_the_only_no_quote_exception():
    assert normal_result.error_code == "quote_required"
    assert id_only_result.ok is True

def test_unchanged_preexisting_id_problem_is_temporarily_grandfathered():
    assert plan.grandfathered_problems_after <= plan.grandfathered_problems_before

def test_changed_or_new_invalid_id_is_rejected():
    assert result.error_code == "new_or_modified_lint_problem"
```

검증 순서가 바뀌지 않도록 각 단계에 동시에 문제가 있는 fixture도 둔다.

- [ ] **Step 2: exact request/manifest model을 구현한다**

```python
class MutationOperation(StrEnum):
    INGEST = "ingest"
    PROMOTE = "promote"
    PROMOTE_AUTO = "promote_auto"
    MARK_CHECKED = "mark_checked"
    PROJECTION = "projection"
    CONTEXT_REPLACE = "context_replace"
    ID_ONLY_MIGRATION = "id_only_migration"
    DISPLAY_MIGRATION = "display_migration"

@dataclass(frozen=True)
class MutationRequest:
    operation: MutationOperation
    brain_root: Path
    repo_context: RepoContext | None
    engine_sha: str
    objects: tuple[dict, ...]
    delete_ids: tuple[str, ...] = ()
    preconditions: Mapping[str, str] = field(default_factory=dict)
    expected_corpus_fingerprint: str | None = None

@dataclass(frozen=True)
class MutationManifest:
    transaction_id: str
    operation: str
    engine_sha: str
    creates: tuple[dict, ...]
    updates: tuple[dict, ...]
    deletes: tuple[dict, ...]
    renames: tuple[dict, ...]
    reference_rewrites: tuple[dict, ...]
    before_fingerprint: str
    expected_after_fingerprint: str
    grandfathered_problems_before: tuple[dict, ...]
    grandfathered_problems_after: tuple[dict, ...]
```

manifest JSON은 key 정렬, UTF-8, trailing newline 한 개로 직렬화하고 byte SHA-256을
result에 포함한다. 모든 action의 `path`는 `brain_root` 기준 상대 경로다. action별 최소
필드는 다음과 같다.

```json
{
  "object_id": "code.ctx.anchor",
  "path": "objects/code/code.ctx.anchor.json",
  "before_sha256": null,
  "after_sha256": "sha256"
}
```

rename은 `old_id/new_id/old_path/new_path/before_sha256/after_sha256`을 모두 가진다.

- [ ] **Step 3: 설계 §6.3의 13단계 preflight를 그대로 구현한다**

특히 다음을 지킨다.

- 입력 sequence를 tuple로 유지한 채 duplicate full ID 검사
- logical key/source ID 중복 검사 뒤에만 object map 생성
- 신규·좌표 변경 CodeLocator만 quote+symbol verifier 필수
- ID-only migration만 quote 없는 legacy 허용
- CodeLocator title은 입력을 버리고 canonical symbol로 결정
- merged store의 모든 참조와 lint를 디스크 쓰기 전에 검사
- 기존 119건처럼 복구 전에 이미 있던 `invalid_id` 문제만
  `object_id/problem/object_hash`로 baseline을 고정하고, 동일 hash의 동일 문제만 잠시
  grandfather한다
- `unknown_grammar`, dangling, enum, lifecycle 등 다른 문제는 기존 문제여도 grandfather하지
  않고 즉시 실패한다
- 새 문제, 수정된 객체의 문제, after에서 늘어난 문제는 모두 거부한다
- context replace가 해결한 문제는 after에서 줄어드는 것만 허용하고 되살리지 않는다
- ID migration 완료 gate에서는 grandfathered problem이 0이어야 한다
- before object hash가 plan 시점과 apply 시점에 모두 같아야 함

lint delta를 문자열 parsing으로 구현하지 않는다. `lint.py`에 구조화된 내부 API를 추가하고
기존 `lint_store()`는 호환용 message list wrapper로 유지한다.

```python
@dataclass(frozen=True, order=True)
class LintProblem:
    code: str
    object_ids: tuple[str, ...]
    message: str

def lint_store_report(
    store: BrainStore,
    workspace_root: Path | None = None,
) -> tuple[LintProblem, ...]:
    return ()
```

grandfather hash는 `object_ids`에 든 모든 객체의 안정 직렬화 hash를 정렬해 계산한다.

- [ ] **Step 4: store에 결정론적 object path/bytes helper를 추가한다**

`BrainStore.save_object()`는 제품 코드에서 호출하지 않는다. 대신 다음 순수 helper를 둔다.

```python
@classmethod
def object_path(cls, brain_root: Path, obj: Mapping[str, object]) -> Path:
    return brain_root / cls._KIND_DIR[str(obj["kind"])] / f"{obj['id']}.json"

@staticmethod
def object_bytes(obj: Mapping[str, object]) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
```

- [ ] **Step 5: focused suite를 통과시키고 commit한다**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_mutation.py tests/test_store.py tests/test_ingest.py tests/test_lint.py -q
git add src/project_brain/mutation.py src/project_brain/store.py \
  src/project_brain/schema.py src/project_brain/lint.py \
  tests/test_mutation.py tests/test_store.py tests/test_ingest.py tests/test_lint.py
git commit -m "feat(brain): add mutation preflight manifest"
```

### Task 5: single-writer lock과 rollback-only journal transaction을 구현한다

**Files:**
- Create: `src/project_brain/corpus_io.py`
- Create: `tests/test_corpus_io.py`
- Modify: `src/project_brain/mutation.py`
- Modify: `src/project_brain/store.py`
- Test: `tests/test_mutation.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: lock, crash, reader visibility RED 테스트를 작성한다**

failure injection 지점은 최소 다음과 같다.

```text
after_temp_fsync
after_journal_prepared
after_state_committing
after_first_before_rename
after_first_live_replace
after_derived_invalidation
before_post_commit_gate
```

각 실패 뒤 다음 mutation이 자동 rollback하고 이전 corpus/index/stale fingerprint를
복원하는지 확인한다. writer 중 reader는 partial corpus를 읽지 못해야 한다.

- [ ] **Step 2: low-level API를 구현한다**

```python
class JournalState(StrEnum):
    PREPARING = "preparing"
    PREPARED = "prepared"
    COMMITTING = "committing"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    RECOVERY_REQUIRED = "recovery_required"

@contextmanager
def corpus_lock(brain_root: Path, *, exclusive: bool) -> Iterator[None]:
    yield

def fsync_file(path: Path) -> None:
    return None

def fsync_directory(path: Path) -> None:
    return None

def recover_unfinished_transaction(brain_root: Path) -> RecoveryResult:
    raise RecoveryRequiredError
```

lock은 `brain_root/.brain-local/corpus.lock`, transaction은
`brain_root/.brain-local/transactions/{transaction_id}/`에 둔다. temp/before image는
live와 같은 filesystem에 있어야 한다.

- [ ] **Step 3: reader와 writer lock 경계를 연결한다**

`BrainStore.load()`는 shared lock을 잡는다. MutationService는 exclusive lock 안에서
`BrainStore.load_unlocked()`를 사용해 self-deadlock을 피한다. unfinished journal이 있으면
일반 reader는 `RecoveryRequiredError`로 fail-closed하고 partial 객체를 반환하지 않는다.

- [ ] **Step 4: apply/rollback을 구현한다**

순서는 설계 §6.4와 정확히 같다.

1. temp file write + file fsync
2. before image + journal write + directory fsync
3. `prepared`
4. `committing`
5. 기존 live를 before로 atomic rename
6. temp를 live로 atomic replace
7. index DB/sidecar와 stale-set invalidate
8. post-commit fingerprint
9. `committed`

`prepared`나 `committing` 복구는 항상 rollback이다. 자동 roll-forward 코드는 만들지 않는다.

- [ ] **Step 5: focused suite를 통과시키고 commit한다**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_corpus_io.py tests/test_mutation.py tests/test_store.py -q
git add src/project_brain/corpus_io.py src/project_brain/mutation.py \
  src/project_brain/store.py tests/test_corpus_io.py \
  tests/test_mutation.py tests/test_store.py
git commit -m "feat(brain): make corpus mutations crash recoverable"
```

### Task 6: ingest/promote/promote-auto/projection을 공통 쓰기 경계로 옮긴다

**Files:**
- Modify: `src/project_brain/ingest.py`
- Modify: `src/project_brain/promote.py`
- Modify: `src/project_brain/context_projection.py`
- Modify: `src/project_brain/assembly.py`
- Modify: `src/project_brain/cli.py`
- Modify: `tests/test_ingest.py`
- Modify: `tests/test_promote.py`
- Modify: `tests/test_context_projection.py`
- Modify: `tests/test_assembly.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: 네 제품 writer와 projection의 routing RED 테스트를 작성한다**

`BrainStore.save_object`를 mock해 호출되면 실패시키고, 각 CLI가
`MutationService.apply()`를 한 번만 호출하는지 검사한다. `src/project_brain` AST를 스캔해
`store.py`, `mutation.py` 외 제품 코드의 `BrainStore.save_object` 호출을 0으로 고정한다.

- [ ] **Step 2: assembly 입력 계약을 바꾼다**

`code_anchors` 필수값은 `key/path/symbol/manifest/quote`다. 외부 `verified_at`과 title을
받지 않는다. `build_code_evidence()`는 `title=symbol`을 만들되 `verified_at`은 넣지 않고,
MutationService 검증 결과가 저장 직전에 채운다. 함께 생성하는 EvidenceRef의 title도
새 객체에 한해 같은 symbol에서 결정론적으로 만들지만, 일반 update allowlist로는 열지 않는다.

- [ ] **Step 3: CLI에 명시적 repo context와 engine SHA를 전달한다**

`ingest`, `promote`, `promote-auto`, `projection build-reuse --write`에 공통으로 다음을
해석한다.

```text
--brain-root
--repo-root
--expected-repo-id
--expected-revision-ref
--engine-sha
```

config에서 해석한 값도 최종 request에는 absolute path와 resolved SHA로 박는다.
`--engine-sha`는 생략을 허용하지 않는다. cwd나 `brain_root.parent` 추론은 제거한다.

- [ ] **Step 4: 기존 precondition과 status guard를 MutationService policy로 옮긴다**

`ingest.py`와 CLI에 중복된 schema/lint/save loop를 삭제한다. promote의 already-reviewed,
mapping bundle, review record 생성은 유지하되 최종 bundle 전체를 한 transaction으로 쓴다.

- [ ] **Step 5: focused suite를 통과시키고 commit한다**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_ingest.py tests/test_promote.py tests/test_context_projection.py \
  tests/test_assembly.py tests/test_cli.py -q
git add src/project_brain/ingest.py src/project_brain/promote.py \
  src/project_brain/context_projection.py src/project_brain/assembly.py \
  src/project_brain/cli.py tests/test_ingest.py tests/test_promote.py \
  tests/test_context_projection.py tests/test_assembly.py tests/test_cli.py
git commit -m "refactor(brain): route product writes through mutation service"
```

### Task 7: audit 상태축, quote access, mark-checked를 재설계한다

**Files:**
- Create: `src/project_brain/audit.py`
- Create: `src/project_brain/quote_access.py`
- Create: `tests/test_audit.py`
- Create: `tests/test_quote_access.py`
- Modify: `src/project_brain/stale_check.py`
- Modify: `src/project_brain/cli.py`
- Modify: `tests/test_stale_check.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: 6개 상태축과 역방향 EvidenceRef RED 테스트를 작성한다**

audit result의 locator 항목은 이 키를 항상 가진다.

```python
{
    "stale": "unchanged",
    "code_quote": "missing",
    "symbol_relation": "unsupported",
    "quote_access": "indeterminate",
    "id_format": "valid",
    "references": "intact",
}
```

quote가 없어도 stale은 실행되어야 한다. EvidenceRef가 locator를 역방향으로 가리키는 경우,
manifest 누락/비승인, principal 누락, evaluator 오류를 각각 검사한다.

- [ ] **Step 2: quote access 3상태 API를 구현한다**

```python
class AccessState(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    INDETERMINATE = "indeterminate"

@dataclass(frozen=True)
class QuoteAccess:
    redaction: AccessState
    principal_acl: AccessState
    final: AccessState

def evaluate_quote_access(
    locator_id: str,
    store: BrainStore,
    *,
    principal: object | None,
    acl_evaluator: Callable[[object, Mapping[str, object]], AccessState] | None,
) -> QuoteAccess:
    return QuoteAccess(
        AccessState.INDETERMINATE,
        AccessState.INDETERMINATE,
        AccessState.INDETERMINATE,
    )
```

현재 principal 모델이 없으므로 제품 기본값은 항상 quote 생략이다.

- [ ] **Step 3: audit CLI를 thin wrapper로 바꾼다**

`_run_audit()`의 조립 로직을 `audit.py`로 이동한다. `--no-stale`은 Git 관련 상태를
`unverifiable`로 표시할 뿐 quote 검증 성공으로 간주하지 않는다. unknown ID grammar와
`anchor_unverifiable`은 exit 1이다.

- [ ] **Step 4: mark-checked를 quote/symbol 재검증 transaction으로 바꾼다**

signature:

```python
def plan_mark_checked(
    store: BrainStore,
    *,
    mapping_ids: Sequence[str],
    checked_head: str,
    repo_context: RepoContext,
    engine_sha: str,
) -> MarkCheckedPlan:
    raise MarkCheckedError
```

quote 없는 locator는 `refused_unverifiable`, 하나라도 실패하면 전체 bundle은 쓰지 않는다.
성공 locator의 `commit_sha/verified_at/updated_at`은 엔진이 같은 검증 사건에서 찍는다.

- [ ] **Step 5: focused suite를 통과시키고 commit한다**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_audit.py tests/test_quote_access.py \
  tests/test_stale_check.py tests/test_cli.py -q
git add src/project_brain/audit.py src/project_brain/quote_access.py \
  src/project_brain/stale_check.py src/project_brain/cli.py \
  tests/test_audit.py tests/test_quote_access.py \
  tests/test_stale_check.py tests/test_cli.py
git commit -m "feat(brain): separate audit and quote access states"
```

### Task 8: query/search 출력과 no-DB/stale-DB fallback을 안전하게 줄인다

**Files:**
- Modify: `src/project_brain/search.py`
- Modify: `src/project_brain/router.py`
- Modify: `src/project_brain/graph_viz.py`
- Modify: `src/project_brain/cli.py`
- Modify: `tests/test_search.py`
- Modify: `tests/test_router.py`
- Modify: `tests/test_graph_viz.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: linked locator 정본과 fallback RED 테스트를 작성한다**

정상 recall의 linked locator:

```python
{
    "object_id": "code.ctx.anchor",
    "path": "LineBubble2/Classes/game/Foo.cpp",
    "symbol": "Foo::bar",
    "quote_access": "indeterminate",
}
```

`title`과 `verified_quote`는 없어야 한다. DB 없음과 stale DB는 각각:

```python
{
    "kind_counts": {"CodeLocator": 3886},
    "object_ids": [],
    "details_omitted_reason": "no_db",
}
```

```python
{
    "kind_counts": {"CodeLocator": 3886},
    "object_ids": [],
    "details_omitted_reason": "stale_db",
}
```

- [ ] **Step 2: search linked shape에서 title을 제거하고 access 상태를 붙인다**

quote는 `quote_access=allow`인 미래 경로에만 선택적으로 추가할 수 있게 하되, 현재
principal이 없으므로 테스트는 항상 quote 미노출을 고정한다.

- [ ] **Step 3: router fallback이 전량 CodeLocator를 로드하지 않게 한다**

`_implementation_locators()`의 no-recall 분기는 전체 객체 배열 대신 aggregate result를
돌린다. stale index 예외도 같은 fallback으로 바꾸고 사유만 `stale_db`로 구분한다.

- [ ] **Step 4: query가 config DB를 기본 사용하게 한다**

명시 `--db`가 없더라도 config의 DB가 존재하면 recall을 사용한다. DB가 없으면 안전한
aggregate fallback으로 간다. graph/show의 title에는 `display_only=true`를 함께 표시한다.

- [ ] **Step 5: focused suite를 통과시키고 commit한다**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_search.py tests/test_router.py tests/test_graph_viz.py tests/test_cli.py -q
git add src/project_brain/search.py src/project_brain/router.py \
  src/project_brain/graph_viz.py src/project_brain/cli.py \
  tests/test_search.py tests/test_router.py tests/test_graph_viz.py tests/test_cli.py
git commit -m "fix(brain): bound locator details in recall and fallback"
```

### Task 9: full snapshot과 context replace manifest를 제품 기능으로 만든다

**Files:**
- Create: `src/project_brain/snapshot.py`
- Create: `src/project_brain/context_replace.py`
- Create: `tests/test_snapshot.py`
- Create: `tests/test_context_replace.py`
- Modify: `src/project_brain/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: snapshot 범위와 rollback RED 테스트를 작성한다**

snapshot fixture에는 objects 19종, `raw/manifests`, `raw/sources`, index DB+WAL+SHM,
stale-set, eval, config를 모두 넣는다. snapshot 도중 fingerprint가 바뀌면 실패해야 한다.

- [ ] **Step 2: snapshot API와 manifest schema를 구현한다**

```python
@dataclass(frozen=True)
class SnapshotRequest:
    brain_root: Path
    repo_root: Path
    engine_root: Path
    output_root: Path
    snapshot_id: str

def create_snapshot(request: SnapshotRequest) -> SnapshotResult:
    raise SnapshotError

def verify_snapshot(snapshot_root: Path) -> SnapshotVerification:
    raise SnapshotError

def restore_snapshot(snapshot_root: Path, brain_root: Path) -> RestoreResult:
    raise SnapshotError
```

`raw/sources`는 파일 내용을 복제하지 않아도 되지만 모든 file hash inventory는 반드시
snapshot manifest에 포함한다. 설치 managed-file hash도 기록한다.

- [ ] **Step 3: context replace diff를 구현한다**

```python
def plan_context_replace(
    *,
    context_id: str,
    existing: BrainStore,
    desired_objects: Sequence[dict],
    expected_drop_ids: Collection[str],
    expected_moves: Mapping[str, str],
    external_reference_rewrites: Mapping[str, str],
) -> MutationRequest:
    raise ContextReplaceError
```

old/new 객체 수를 맞추지 않는다. 모든 차이는 create/update/delete/rename으로 설명하고,
외부 역참조가 남은 delete는 거부한다.

- [ ] **Step 4: CLI를 추가한다**

```text
project-brain snapshot create
project-brain snapshot verify
project-brain snapshot restore
project-brain context-replace plan
project-brain context-replace apply
```

`plan`은 manifest를 쓰지만 live corpus를 수정하지 않는다. `apply`는 plan 때 나온
manifest SHA와 `--expected-manifest-sha256`이 같아야 한다.

- [ ] **Step 5: focused suite를 통과시키고 commit한다**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_snapshot.py tests/test_context_replace.py tests/test_cli.py -q
git add src/project_brain/snapshot.py src/project_brain/context_replace.py \
  src/project_brain/cli.py tests/test_snapshot.py \
  tests/test_context_replace.py tests/test_cli.py
git commit -m "feat(brain): add snapshots and context replacement plans"
```

### Task 10: ID-only와 display-only migration을 구현한다

**Files:**
- Create: `src/project_brain/migration.py`
- Create: `tests/test_migration.py`
- Modify: `src/project_brain/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: semantic no-op와 dependent artifact RED 테스트를 작성한다**

다음은 통과해야 한다.

- object ID와 registry 참조만 one-to-one 변경
- quote 없는 legacy CodeLocator rename
- eval expected ID rewrite
- stale-set/index invalidation

다음은 거부해야 한다.

- merge/split
- title/meaning/status/quote/path/symbol/commit/verified_at 동시 변경
- registry 밖 문자열 치환
- canonical payload hash 불일치
- duplicate new ID

- [ ] **Step 2: canonical payload hash를 구현한다**

기존 `hash_utils.stable_json()`을 재사용한다. self ID는 `$SELF`, manifest의 첫 old/new
reference pair는 `$REF:000001`, 다음 pair는 `$REF:000002`처럼 정렬 순번 token으로 치환한
뒤 SHA-256을 계산한다. raw string replace는 금지한다.

- [ ] **Step 3: migration manifest를 구현한다**

각 행은 정확히 다음 필드를 가진다.

```json
{
  "old_id": "code.ctx.old",
  "new_id": "code.ctx.new",
  "kind": "CodeLocator",
  "canonical_payload_hash": "sha256",
  "reference_rewrites": [],
  "dependent_artifacts": [],
  "snapshot_id": "snapshot-id"
}
```

`reference_rewrites`는 JSON pointer 단위로 전수 열거한다. stale-set의 27 ID와 index document
ID는 rewrite가 아니라 invalidation으로 기록한다.

- [ ] **Step 4: display-only planner를 구현한다**

canonical symbol이 있으면 `title=symbol`, symbol이 없는 legacy만
`basename(path):anchor-key`다. title 외 field hash가 달라지면 거부한다. EvidenceRef title은
이 migration 대상이 아니다.

- [ ] **Step 5: CLI와 focused suite를 통과시키고 commit한다**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_migration.py tests/test_cli.py -q
git add src/project_brain/migration.py src/project_brain/cli.py \
  tests/test_migration.py tests/test_cli.py
git commit -m "feat(brain): add id-only and display-only migrations"
```

### Task 11: 설치되는 ingest/query/audit 계약과 batch report를 맞춘다

**Files:**
- Modify: `src/project_brain/templates/ingest/SKILL.md`
- Modify: `src/project_brain/templates/ingest/references/object-model.md`
- Modify: `src/project_brain/templates/ingest/references/ingest-tools.md`
- Modify: `src/project_brain/templates/ingest/references/completeness-checklist.md`
- Modify: `src/project_brain/templates/ingest/references/system-domain-playbook.md`
- Modify: `src/project_brain/templates/ingest/references/update-rules.md`
- Modify: `src/project_brain/templates/ingest/scripts/assemble_notes.py`
- Modify: `src/project_brain/templates/ingest/scripts/domain_spec.template.py`
- Modify: `src/project_brain/templates/ingest/scripts/extract_template.js`
- Modify: `src/project_brain/templates/ingest/scripts/run_ingest_batch.py`
- Modify: `src/project_brain/templates/ingest/scripts/finalize_ingest.py`
- Modify: `src/project_brain/templates/query/SKILL.md`
- Modify: `src/project_brain/templates/audit/SKILL.md`
- Modify: `tests/test_ingest_skill_contract.py`
- Modify: `tests/test_ingest_skill_behavior_replay.py`
- Modify: `tests/test_installer.py`
- Modify: `src/project_brain/templates/ingest/scripts/test_assemble_notes.py`
- Modify: `src/project_brain/templates/ingest/scripts/test_batch_tools.py`
- Modify: `src/project_brain/templates/ingest/scripts/test_finalize_ingest.py`

- [ ] **Step 1: 문서-코드 계약 RED 테스트를 먼저 쓴다**

다음을 exact assertion으로 둔다.

- `code_evref_keys`는 `anchor-key`
- code anchor input에 title과 verified_at 없음
- batch report에 absolute `repo_root`, `expected_repo_id`, `expected_revision_ref`,
  `engine_sha`, `manifest_sha256` 존재
- `needs_user`는 success/finalized로 승격되지 않음
- 일반 quote 우회 flag 없음
- query skill이 CodeLocator title/quote를 의미 근거로 쓰지 않음
- audit skill이 stale과 missing quote를 구분함

- [ ] **Step 2: assemble/finalize runtime 입력을 새 계약으로 바꾼다**

`assemble_notes.py`는 anchor key/path/symbol/quote만 전달한다. `finalize_ingest.py`는
transaction result와 manifest hash가 없으면 완료를 거부한다.

- [ ] **Step 3: batch resume가 같은 engine/repo/manifest만 재개하게 한다**

resume report의 engine SHA, repo identity, revision ref, input hash가 하나라도 다르면
`resume_contract_mismatch`로 거부한다.

- [ ] **Step 4: template runtime unittest와 installer tests를 통과시킨다**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_ingest_skill_contract.py \
  tests/test_ingest_skill_behavior_replay.py \
  tests/test_installer.py -q
PYTHONPATH=src .venv/bin/python \
  -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
```

- [ ] **Step 5: commit한다**

```bash
git add src/project_brain/templates tests/test_ingest_skill_contract.py \
  tests/test_ingest_skill_behavior_replay.py tests/test_installer.py
git commit -m "docs(brain): align installed ingest and query contracts"
```

### Task 12: 엔진 전체 gate를 통과하고 exact engine SHA를 고정한다

**Files:**
- Modify: `docs/reports/2026-07-28-ingest-recovery-baseline.md`

- [ ] **Step 1: 전체 엔진 테스트를 실행한다**

```bash
ENGINE_WORKTREE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery
PYTHONPATH="$ENGINE_WORKTREE/src" "$ENGINE_WORKTREE/.venv/bin/python" -m pytest -q
PYTHONPATH="$ENGINE_WORKTREE/src" "$ENGINE_WORKTREE/.venv/bin/python" \
  -m unittest discover -s "$ENGINE_WORKTREE/src/project_brain/templates/ingest/scripts" -p 'test_*.py'
```

- [ ] **Step 2: placeholder와 direct writer를 스캔한다**

```bash
rg -n 'TODO|FIXME|NotImplemented|pass\\s*(#.*)?$' src/project_brain tests
rg -n 'BrainStore\\.save_object' src/project_brain
```

Expected: 의도된 abstract/test fixture 외 placeholder 0, 제품 direct writer 0.

- [ ] **Step 3: static type/shape 자체 점검을 한다**

`MutationOperation`, journal state, audit/access enum이 CLI JSON에서 같은 문자열을 쓰는지,
manifest field 이름이 template runtime과 같은지 수동 대조해 report에 기록한다.

- [ ] **Step 4: 최종 engine SHA를 report에 고정하고 commit한다**

```bash
git rev-parse HEAD
git status --short
git add docs/reports/2026-07-28-ingest-recovery-baseline.md
git commit -m "docs(brain): record recovery engine verification"
git rev-parse HEAD
```

마지막 출력 SHA가 이후 모든 BB2 staging/live command의 `ENGINE_SHA`다. 이 SHA 이후 엔진
코드를 고치면 BB2 staging을 처음부터 다시 만든다.

### Task 13: BB2 live를 건드리지 않고 full snapshot과 staging 기준선을 만든다

**Files:**
- Create: `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-07-28/brain-ingest-recovery/pre-recovery-20260728/`
- Create in staging only: `brain/recovery/2026-07-28/baseline/`
- Read only: `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-07-27/ingest-backup/`
- Read only: `/Users/al03040455/Desktop/bb2_client/brain/`

- [ ] **Step 1: BB2 instructions와 current dirt를 다시 읽는다**

```bash
BB2_ROOT=/Users/al03040455/Desktop/bb2_client
sed -n '1,260p' "$BB2_ROOT/AGENTS.md"
git -C "$BB2_ROOT" status --short
git -C "$BB2_ROOT" rev-parse HEAD
git -C "$BB2_ROOT" diff --cached --quiet
git -C "$BB2_ROOT" check-ignore -v \
  brain/objects/code/code.petskill-kamehameha.aim-degree-limit--0.json
```

Expected: 기존 사용자 dirty가 그대로 있고, 광선발사 예시 파일은 local `/brain` exclude에
걸리며 기존 staged change는 없다. status가 baseline report와 달라졌거나 staged change가
있으면 snapshot 전에 중단한다. 사용자 staging을 임의로 해제하지 않는다.

- [ ] **Step 2: full snapshot을 만든다**

```bash
ENGINE_WORKTREE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery
BB2_ROOT=/Users/al03040455/Desktop/bb2_client
SNAPSHOT_ROOT="$BB2_ROOT/.snapshots/2026-07-28/brain-ingest-recovery"
PYTHONPATH="$ENGINE_WORKTREE/src" "$ENGINE_WORKTREE/.venv/bin/python" \
  -m project_brain.cli snapshot create \
  --brain-root "$BB2_ROOT/brain" \
  --repo-root "$BB2_ROOT" \
  --engine-root "$ENGINE_WORKTREE" \
  --output-root "$SNAPSHOT_ROOT" \
  --snapshot-id pre-recovery-20260728
```

snapshot ID와 manifest SHA를 별도 텍스트로 복사하지 말고 CLI JSON 결과 파일 자체를 보존한다.
이후 BB2 code evidence 검증은 `expected_repo_id=bb2_client`,
`expected_revision_ref=origin/develop`을 고정한다.

- [ ] **Step 3: 실제 live brain의 검증용 복제 staging을 만든다**

```bash
STAGING_PROJECT=/private/tmp/project-brain-ingest-recovery-20260728
test ! -e "$STAGING_PROJECT"
mkdir -p "$STAGING_PROJECT"
ditto /Users/al03040455/Desktop/bb2_client/brain "$STAGING_PROJECT/brain"
cp /Users/al03040455/Desktop/bb2_client/.project-brain.json \
  "$STAGING_PROJECT/.project-brain.json"
```

staging은 임시 Git repo로 만들지 않는다. quote 검증의 `repo_root`는 계속 실제 BB2 root다.

- [ ] **Step 4: baseline audit/eval/query를 구조화 파일로 저장한다**

`brain/recovery/2026-07-28/baseline/` 아래에 다음 파일을 만든다.

```text
audit.json
eval.json
query-stage-clear-token.json
query-hammer-5-5.json
query-kamehameha.json
query-ingame-item-usage.json
corpus-summary.json
```

명령은 모두 engine worktree python과 `PYTHONPATH`를 명시한다. 기존 eval은 시나리오별
15개 결과를 보존하고 summary만 저장하지 않는다.

- [ ] **Step 5: 기준 개수와 hidden/untracked 광선발사 상태를 assert한다**

`corpus-summary.json`에 11,097 / 3,886 / 579 / 3,307 / 456 / 945와 Git tracked 여부를
기록한다. 값이 다르면 설계 숫자를 강제로 맞추지 말고 차이 원인을 조사한다.

### Task 14: 광선발사 staging bundle과 exact context manifest를 만든다

**Files:**
- Create in staging: `brain/recovery/2026-07-28/petskill-kamehameha/normalized-notes.json`
- Create in staging: `brain/recovery/2026-07-28/petskill-kamehameha/symbol-map.json`
- Create in staging: `brain/recovery/2026-07-28/petskill-kamehameha/context-replace.manifest.json`
- Create in staging: `brain/recovery/2026-07-28/petskill-kamehameha/gate-report.json`
- Create in staging: `brain/checks/test_ingest_recovery.py`

- [ ] **Step 1: 보존 입력 hash와 exact DROP/MOVE를 고정한다**

입력:

```text
.snapshots/2026-07-27/ingest-backup/kamehameha-session/notes.json
.snapshots/2026-07-27/ingest-backup/kamehameha-session/verify.json
.snapshots/2026-07-27/ingest-backup/kamehameha-session/domain_spec.py
.snapshots/2026-07-27/ingest-backup/kamehameha-session/drop_anchors.json
```

`drop_anchors.json.drop`은 정확히 77개, move는 정확히
`shot-bubble-sprite--6 → shoot-action` 한 개여야 한다.

- [ ] **Step 2: old→new symbol map을 전수 작성한다**

광선발사 180개 CodeLocator 전체를 행으로 만들고 상태를
`verified/manual_verified/rejected` 중 하나로 둔다. 괄호 66개와 한글 혼합 128개의 합집합을
전부 분류한다. 단순 괄호 앞 자르기는 금지한다.

세 Jira 내부 key는 다음처럼 소문자로 만든다.

```text
LGBBTWO-234  -> jira-lgbbtwo-234
LGBBTWO-3292 -> jira-lgbbtwo-3292
LGBBTWO-3736 -> jira-lgbbtwo-3736
```

locator URL과 Jira 원형 문자열은 그대로 보존한다.

- [ ] **Step 3: 새 계약으로 build하고 context replace manifest를 만든다**

외부 verified_at을 제거하고 engine verifier가 실제 blob 확인 직후 시간을 찍게 한다.
`광선 발사`와 `KAMEHAMEHA`는 서로 독립된 term/synonym/alias 표면으로 연결한다.
`--N` ID는 유지하고 의미형 anchor ID를 새로 작명하지 않는다.

- [ ] **Step 4: staging transaction과 failure injection을 통과시킨다**

같은 manifest로 정상 apply와 중간 실패 rollback을 각각 staging 복제본에서 실행한다.
두 실행의 manifest byte SHA가 같아야 하고 rollback 뒤 baseline corpus/index/stale
fingerprint가 같아야 한다.

- [ ] **Step 5: 광선발사 gate를 통과시킨다**

확인 항목:

- DROP 77
- MOVE 1
- Jira 3 lowercase
- 신규/좌표 변경 CodeLocator quote+symbol 100%
- dangling 0
- 신규 ID 위반 0
- 기존 eval 15개 시나리오별 무회귀
- `광선 발사`, `KAMEHAMEHA` query target hit
- 두 무관 query 기준선보다 악화 없음
- second finalize no-op

### Task 15: 광선발사를 live transaction으로 적용하고 새 checkpoint를 만든다

**Files:**
- Create live: `brain/recovery/2026-07-28/petskill-kamehameha/`
- Create live: `brain/checks/test_ingest_recovery.py`
- Modify/Delete/Create: manifest에 정확히 열거된 `brain/` 파일
- Create: `.snapshots/2026-07-28/brain-ingest-recovery-post-kamehameha/post-kamehameha-20260728/`

- [ ] **Step 1: live fingerprint와 staging manifest SHA를 재검증한다**

snapshot 이후 live writer가 있었으면 적용하지 않는다. engine SHA, BB2 SHA, source input
hash, before corpus fingerprint, manifest SHA가 staging report와 모두 같아야 한다. gate를
통과한 staging artifact와 회귀 테스트를 byte-preserving copy로 live recovery 경로에 먼저
옮기고 각 hash를 다시 확인한다.

```bash
STAGING_PROJECT=/private/tmp/project-brain-ingest-recovery-20260728
BB2_ROOT=/Users/al03040455/Desktop/bb2_client
mkdir -p "$BB2_ROOT/brain/recovery/2026-07-28/petskill-kamehameha"
for artifact in normalized-notes.json symbol-map.json \
  context-replace.manifest.json gate-report.json; do
  cp -p \
    "$STAGING_PROJECT/brain/recovery/2026-07-28/petskill-kamehameha/$artifact" \
    "$BB2_ROOT/brain/recovery/2026-07-28/petskill-kamehameha/$artifact"
done
cp -p "$STAGING_PROJECT/brain/checks/test_ingest_recovery.py" \
  "$BB2_ROOT/brain/checks/test_ingest_recovery.py"
```

- [ ] **Step 2: 같은 manifest로 한 번만 apply한다**

`context-replace apply`에 staging manifest SHA를 `--expected-manifest-sha256`로 전달한다.
명령이 새 plan을 암묵적으로 재생성하지 않게 한다.

```bash
ENGINE_WORKTREE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery
BB2_ROOT=/Users/al03040455/Desktop/bb2_client
MANIFEST="$BB2_ROOT/brain/recovery/2026-07-28/petskill-kamehameha/context-replace.manifest.json"
GATE_REPORT="$BB2_ROOT/brain/recovery/2026-07-28/petskill-kamehameha/gate-report.json"
ENGINE_SHA="$(jq -r '.engine_sha' "$GATE_REPORT")"
MANIFEST_SHA="$(jq -r '.manifest_sha256' "$GATE_REPORT")"
test "$(git -C "$ENGINE_WORKTREE" rev-parse HEAD)" = "$ENGINE_SHA"
test "$(shasum -a 256 "$MANIFEST" | awk '{print $1}')" = "$MANIFEST_SHA"
PYTHONPATH="$ENGINE_WORKTREE/src" "$ENGINE_WORKTREE/.venv/bin/python" \
  -m project_brain.cli context-replace apply \
  --brain-root "$BB2_ROOT/brain" \
  --repo-root "$BB2_ROOT" \
  --expected-repo-id bb2_client \
  --expected-revision-ref origin/develop \
  --engine-sha "$ENGINE_SHA" \
  --manifest "$MANIFEST" \
  --expected-manifest-sha256 "$MANIFEST_SHA"
```

- [ ] **Step 3: live audit/eval/query와 second finalize를 실행한다**

staging과 같은 gate를 live에서 반복한다. exit 0만 보지 말고 exact object IDs,
`needs_clarification`, top-k, delta list를 비교한다.

- [ ] **Step 4: Git persistence를 manifest 경로로 제한한다**

manifest action path는 `brain_root` 기준이므로 Git pathspec을 만들 때 `brain/`을 붙인다.
삭제/rename old path와, transaction 뒤 존재해야 할 create/update/rename new path를 서로
다른 NUL 파일로 만든다. 광선발사 기존 456개는 Git 미추적이므로 `updates`도 `git add -u`가
아니라 exact force-add 출력 목록에 포함해야 한다.

```bash
MANIFEST=/Users/al03040455/Desktop/bb2_client/brain/recovery/2026-07-28/petskill-kamehameha/context-replace.manifest.json
jq -j '
  [.deletes[].path, .renames[].old_path]
  | unique[]
  | "brain/\(.)\u0000"
' "$MANIFEST" > /private/tmp/kamehameha-tracked-paths.nul
jq -j '
  [.creates[].path, .updates[].path, .renames[].new_path]
  | unique[]
  | "brain/\(.)\u0000"
' "$MANIFEST" > /private/tmp/kamehameha-output-paths.nul
git -C /Users/al03040455/Desktop/bb2_client add -u \
  --pathspec-from-file=/private/tmp/kamehameha-tracked-paths.nul \
  --pathspec-file-nul
git -C /Users/al03040455/Desktop/bb2_client add -f \
  --pathspec-from-file=/private/tmp/kamehameha-output-paths.nul \
  --pathspec-file-nul
git -C /Users/al03040455/Desktop/bb2_client add -f -- \
  brain/recovery/2026-07-28/petskill-kamehameha \
  brain/checks/test_ingest_recovery.py
{
  tr '\0' '\n' < /private/tmp/kamehameha-tracked-paths.nul
  tr '\0' '\n' < /private/tmp/kamehameha-output-paths.nul
  (
    cd /Users/al03040455/Desktop/bb2_client
    rg --files brain/recovery/2026-07-28/petskill-kamehameha
  )
  printf '%s\n' brain/checks/test_ingest_recovery.py
} | LC_ALL=C sort -u > /private/tmp/kamehameha-expected-stage.txt
git -C /Users/al03040455/Desktop/bb2_client diff --cached --name-only \
  | LC_ALL=C sort -u > /private/tmp/kamehameha-actual-stage.txt
diff -u /private/tmp/kamehameha-expected-stage.txt \
  /private/tmp/kamehameha-actual-stage.txt
```

`git add -f brain`이나 `git add -A`는 금지한다. stage된 파일 목록이 manifest와 다르면
commit하지 않는다.

- [ ] **Step 5: 광선발사 data commit과 post snapshot을 만든다**

```bash
git -C /Users/al03040455/Desktop/bb2_client commit \
  -m "fix(brain): recover kamehameha corpus"
```

commit에는 원래 사용자 dirty 파일이 들어가면 안 된다. commit 후 full snapshot을 새로 만들고
그 snapshot을 인게임의 기준점으로 쓴다.

### Task 16: 인게임 아이템 사용을 비교·복구하고 두 번째 checkpoint를 만든다

**Files:**
- Create live/staging: `brain/recovery/2026-07-28/ingame-item-usage/normalized-notes.json`
- Create live/staging: `brain/recovery/2026-07-28/ingame-item-usage/symbol-map.json`
- Create live/staging: `brain/recovery/2026-07-28/ingame-item-usage/context-replace.manifest.json`
- Create live/staging: `brain/recovery/2026-07-28/ingame-item-usage/gate-report.json`
- Modify/Delete/Create: manifest에 정확히 열거된 `brain/` 파일
- Create: `.snapshots/2026-07-28/brain-ingest-recovery-post-ingame/post-ingame-20260728/`

- [ ] **Step 1: post-kamehameha snapshot에서 새 staging을 만든다**

이전 baseline staging을 재사용하지 않는다. 광선발사 live checkpoint 복제본에서 시작한다.

```bash
INGAME_STAGING_PROJECT=/private/tmp/project-brain-ingest-recovery-post-kamehameha-20260728
test ! -e "$INGAME_STAGING_PROJECT"
mkdir -p "$INGAME_STAGING_PROJECT"
ditto /Users/al03040455/Desktop/bb2_client/brain \
  "$INGAME_STAGING_PROJECT/brain"
cp /Users/al03040455/Desktop/bb2_client/.project-brain.json \
  "$INGAME_STAGING_PROJECT/.project-brain.json"
```

- [ ] **Step 2: 보존 입력과 기존 945개를 구조적으로 비교한다**

입력:

```text
.snapshots/2026-07-27/ingest-backup/item-usage-session/ingest/domain_spec.py
.snapshots/2026-07-27/ingest-backup/item-usage-session/ingest/verify.json
.snapshots/2026-07-27/ingest-backup/item-usage-session/ingest/verify-raw.json
.snapshots/2026-07-27/ingest-backup/item-usage-session/ingest/axis-lifecycle.json
.snapshots/2026-07-27/ingest-backup/item-usage-session/ingest/axis-objects.json
.snapshots/2026-07-27/ingest-backup/item-usage-session/ingest/axis-receiver.json
.snapshots/2026-07-27/ingest-backup/item-usage-session/ingest/axis-side.json
.snapshots/2026-07-27/ingest-backup/item-usage-session/ingest/axis-trigger.json
```

차이를 `contract_change`와 `unexpected_semantic_change`로 분류한다. 후자가 하나라도 있으면
live apply를 중단한다.

- [ ] **Step 3: 393 CodeLocator quote/symbol을 전수 검증한다**

괄호 3개와 한글 혼합 4개의 합집합을 symbol map에 넣고, 모든 locator가 parser 또는
구조화된 manual verification을 가져야 한다. 자정 verified_at은 폐기한다.

- [ ] **Step 4: staging gate와 second finalize no-op을 통과시킨다**

기존 15 eval, 두 무관 query, 광선발사 query, 인게임 신규 query를 모두 확인한다.
정당한 분산 anchor 수를 줄이기 위한 delete는 허용하지 않는다.

- [ ] **Step 5: live apply, exact force-add, commit, post snapshot을 수행한다**

광선발사와 같은 live fingerprint/manifest SHA/staged-path gate를 사용한다.

```bash
git -C /Users/al03040455/Desktop/bb2_client commit \
  -m "fix(brain): recover ingame item usage corpus"
```

commit 후 두 번째 full snapshot을 만든다.

### Task 17: context 복구 뒤 ID-only migration을 재측정하고 적용한다

**Files:**
- Create: `brain/recovery/2026-07-28/id-migration/id-migration.manifest.json`
- Create: `brain/recovery/2026-07-28/id-migration/dry-run-report.json`
- Create: `brain/recovery/2026-07-28/id-migration/live-report.json`
- Modify: manifest에 열거된 object/eval 파일
- Invalidate: `.brain-local/stale-set.json`, `.brain-local/index.db*`

- [ ] **Step 1: 19종 grammar를 live 기준으로 다시 측정한다**

광선발사의 대문자 Jira 3건이 context replace로 해결됐다면 예상 잔여 후보는 116개다.
그러나 116을 강제 입력하지 말고 실제 결과를 manifest로 만든다. `resolved_by_context_replace`
3행은 별도 기록한다.

- [ ] **Step 2: 모든 old→new와 참조 pointer를 dry-run manifest로 고정한다**

기준선:

- context replace 전 후보 119
- object field 65파일 187회
- eval 포함 66파일 190회
- ReviewRecord identity rename 후보 11
- eval expected ID 3
- stale-set invalidation 대상 old ID 27

context replace 뒤 숫자가 줄거나 파일이 바뀌면 각 차이를 manifest reason으로 설명한다.

- [ ] **Step 3: canonical payload hash와 one-to-one 조건을 전수 검증한다**

ID/registry 참조 외 payload가 하나라도 바뀌면 해당 행뿐 아니라 migration 전체를 거부한다.

- [ ] **Step 4: staging/live manifest hash 일치 후 transaction을 적용한다**

stale-set과 index는 string replace하지 않고 invalidate한다. ContextProjection source ID가
바뀌면 stale로 만들고 regenerate한다.

- [ ] **Step 5: ID 위반 0, dangling 0을 확인하고 commit한다**

```bash
git -C /Users/al03040455/Desktop/bb2_client commit \
  -m "fix(brain): canonicalize corpus object ids"
```

### Task 18: CodeLocator display migration과 quote 부채 report를 만든다

**Files:**
- Create: `brain/recovery/2026-07-28/display-migration/display-migration.manifest.json`
- Create: `brain/recovery/2026-07-28/display-migration/gate-report.json`
- Create: `brain/recovery/2026-07-28/legacy-quote-backlog.json`
- Modify: manifest에 열거된 CodeLocator JSON

- [ ] **Step 1: post-ID-migration 기준 대상 수를 다시 잰다**

현재 3,886과 title!=symbol 3,879를 완료 목표로 고정하지 않는다. context/ID 복구 뒤 실제
수를 사용한다.

- [ ] **Step 2: display-only manifest를 만들고 non-title hash를 비교한다**

canonical symbol이면 `title=symbol`이다. symbol 자체가 비정상이면 title로 숨기지 않고
backlog에 남긴다.

- [ ] **Step 3: staging/live transaction을 적용하고 index를 재생성한다**

display migration은 quote 보강을 요구하지 않지만 title 외 field가 바뀌면 실패한다.

- [ ] **Step 4: quote 없는 legacy를 context/usage 기준으로 backlog화한다**

우선순위:

1. stale + mark-checked 필요
2. 자주 조회되는 핵심 context
3. quote 보유율 낮고 코드 의존성 높은 context

전면 quote 백필은 하지 않는다. backlog에는 locator ID, context, stale 상태,
last-query count가 있을 때 그 값, reason만 넣는다.

- [ ] **Step 5: display migration을 commit한다**

```bash
git -C /Users/al03040455/Desktop/bb2_client commit \
  -m "fix(brain): normalize code locator display labels"
```

### Task 19: 설치, 실코퍼스 회귀, 최종 snapshot과 인계를 완료한다

**Files:**
- Modify managed files: `.agents/skills/bb2-brain-ingest/`
- Modify managed files: `.agents/skills/bb2-brain-query/`
- Modify managed files: `.agents/skills/bb2-brain-audit/`
- Modify: `.project-brain-manifest.json`
- Preserve: 프로젝트 고유 overlay와 현재 사용자 dirty
- Create: `brain/recovery/2026-07-28/final-verification.json`
- Create: `.snapshots/2026-07-28/brain-ingest-recovery-final/final-20260728/`

- [ ] **Step 1: global edit install을 건드리지 않고 engine worktree로 installer 1회를 실행한다**

```bash
ENGINE_WORKTREE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery
BB2_ROOT=/Users/al03040455/Desktop/bb2_client
mkdir -p "$BB2_ROOT/brain/recovery/2026-07-28/installer"
PYTHONPATH="$ENGINE_WORKTREE/src" "$ENGINE_WORKTREE/.venv/bin/python" \
  -m project_brain.cli install \
  --target "$BB2_ROOT" \
  --project bb2 \
  --brain-root brain \
  --default-branch develop \
  --repo bb2_client \
  > "$BB2_ROOT/brain/recovery/2026-07-28/installer/install-first.json"
```

첫 report의 `skipped`는 빈 배열이어야 한다. 비어 있지 않으면 `--force`로 덮지 말고 사용자
수정과 template 차이를 따로 조정한다.

- [ ] **Step 2: installer 2회차 완전 멱등을 확인한다**

같은 명령을 다시 실행해 `created/updated/removed/adopted/skipped`가 모두 빈 배열인지
확인한다. 프로젝트 overlay hash는 설치 전후 같아야 한다. 그 뒤 installer가 보고한 managed
path와 `.project-brain-manifest.json`만 stage해 별도 commit한다.

```bash
ENGINE_WORKTREE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery
BB2_ROOT=/Users/al03040455/Desktop/bb2_client
PYTHONPATH="$ENGINE_WORKTREE/src" "$ENGINE_WORKTREE/.venv/bin/python" \
  -m project_brain.cli install \
  --target "$BB2_ROOT" \
  --project bb2 \
  --brain-root brain \
  --default-branch develop \
  --repo bb2_client \
  > "$BB2_ROOT/brain/recovery/2026-07-28/installer/install-second.json"
FIRST_REPORT="$BB2_ROOT/brain/recovery/2026-07-28/installer/install-first.json"
jq -j --arg prefix "$BB2_ROOT/" '
  [.created[], .updated[]]
  | unique[]
  | sub("^" + $prefix; "")
  | . + "\u0000"
' "$FIRST_REPORT" > /private/tmp/brain-installer-output-paths.nul
jq -j --arg prefix "$BB2_ROOT/" '
  [.removed[]]
  | unique[]
  | sub("^" + $prefix; "")
  | . + "\u0000"
' "$FIRST_REPORT" > /private/tmp/brain-installer-removed-paths.nul
if test -s /private/tmp/brain-installer-output-paths.nul; then
  git -C "$BB2_ROOT" add -f \
    --pathspec-from-file=/private/tmp/brain-installer-output-paths.nul \
    --pathspec-file-nul
fi
if test -s /private/tmp/brain-installer-removed-paths.nul; then
  git -C "$BB2_ROOT" add -u \
    --pathspec-from-file=/private/tmp/brain-installer-removed-paths.nul \
    --pathspec-file-nul
fi
git -C "$BB2_ROOT" add -f -- \
  .project-brain-manifest.json \
  brain/recovery/2026-07-28/installer/install-first.json \
  brain/recovery/2026-07-28/installer/install-second.json
git -C "$BB2_ROOT" commit \
  -m "chore(brain): install recovered skill contracts"
```

`guardrails` 등 다른 `.agents` dirty가 staged되면 commit하지 않는다.

- [ ] **Step 3: BB2 실코퍼스 전체 gate를 실행한다**

```bash
ENGINE_WORKTREE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery
BB2_ROOT=/Users/al03040455/Desktop/bb2_client
cd "$BB2_ROOT"
PYTHONPATH="$ENGINE_WORKTREE/src" "$ENGINE_WORKTREE/.venv/bin/python" \
  -m unittest discover -s "$BB2_ROOT/brain/checks" -p 'test_*.py'
PYTHONPATH="$ENGINE_WORKTREE/src" "$ENGINE_WORKTREE/.venv/bin/python" \
  -m project_brain.cli index rebuild
PYTHONPATH="$ENGINE_WORKTREE/src" "$ENGINE_WORKTREE/.venv/bin/python" \
  -m project_brain.cli eval
PYTHONPATH="$ENGINE_WORKTREE/src" "$ENGINE_WORKTREE/.venv/bin/python" \
  -m project_brain.cli audit \
  --brain-root "$BB2_ROOT/brain" \
  --repo-root "$BB2_ROOT"
```

명령 cwd는 BB2 root다. 결과는 `final-verification.json`에 구조화해 저장한다.

- [ ] **Step 4: exact 최종 조건을 확인한다**

- 기존 eval 15/15 시나리오별 유지
- 두 대상 query 통과
- 두 무관 query 무회귀
- ID invalid 0
- dangling 0
- 두 context quote/symbol 전수 통과
- `verified_at`이 엔진 검증 사건에서 생성
- second finalize no-op
- installer 2회차 완전 no-op
- 광선발사 create 파일이 Git tracked
- 원래 사용자 dirty가 별도 보존

- [ ] **Step 5: 최종 snapshot과 Git 범위를 확인한다**

full snapshot을 만든 뒤 다음을 실행한다.

```bash
git -C /Users/al03040455/Desktop/bb2_client status --short
git -C /Users/al03040455/Desktop/bb2_client log --oneline -5
git -C /Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery \
  status --short
git -C /Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery \
  log --oneline -12
```

`final-verification.json`과 각 recovery report 중 아직 commit되지 않은 exact 파일만 stage해
마지막 data report commit을 만든다. 기존 사용자 dirty는 포함하지 않는다.

```bash
git -C /Users/al03040455/Desktop/bb2_client add -f -- \
  brain/recovery/2026-07-28/final-verification.json
git -C /Users/al03040455/Desktop/bb2_client commit \
  -m "docs(brain): record ingest recovery verification"
```

push, merge, global `uv tool install -e`는 하지 않는다. 사용자에게 engine branch/SHA,
BB2 data commits, 남아 있는 사용자 dirty, snapshot IDs, rollback 명령을 인계한다.

## 최종 자체 검토 체크리스트

- [ ] 정본 설계 §1~§15의 모든 결정이 최소 한 Task와 연결됨
- [ ] 19종 ID grammar와 ReviewRecord/ContextProjection variant가 테스트됨
- [ ] 모든 제품 object writer가 MutationService를 통과함
- [ ] quote/stale/symbol/access/id/reference 상태가 분리됨
- [ ] principal 부재 시 quote가 모든 query/search 경로에서 빠짐
- [ ] reader가 committing 중 partial corpus를 보지 못함
- [ ] crash recovery는 rollback-only이며 roll-forward 코드가 없음
- [ ] context별 staging manifest SHA와 live manifest SHA가 같음
- [ ] 광선발사 DROP 77/MOVE 1/Jira 3이 exact gate임
- [ ] 인게임 945 비교와 393 locator 검증이 독립 gate임
- [ ] ID migration은 context replace 뒤 재측정함
- [ ] stale/index는 ID string replace가 아니라 invalidate/rebuild함
- [ ] display migration은 title 외 payload를 못 바꿈
- [ ] legacy quote 전면 백필을 하지 않음
- [ ] BB2 `/brain` local exclude 때문에 생기는 새 파일 영속화가 exact pathspec으로 해결됨
- [ ] 기존 사용자 dirty를 commit/stash/overwrite하지 않음
- [ ] 전체 테스트, template unittest, real corpus checks, eval, audit, installer 2회 검증이 있음
- [ ] 계획 안에 `TODO`, `FIXME`, 설명 없는 placeholder가 없음
