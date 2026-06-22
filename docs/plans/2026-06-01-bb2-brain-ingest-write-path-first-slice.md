# BB2 Brain 적재 쓰기 경로 + 첫 슬라이스 + Lint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** object-model 스키마로 reviewed 객체를 `brain/`에 적재하는 쓰기 경로와 무결성 Lint를 만들고, 스테이지 클리어 토큰 입장팝업 첫 슬라이스를 실데이터로 적재해 `cli.py` 질의가 fixture가 아닌 디스크 데이터에서 도는 것까지 검증한다.

**Architecture:** `store.py`는 지금 읽기(`load`)만 있다. 여기에 (1) `schema.py`(kind별 필수 필드 검증) + (2) `store.save_object`(검증 후 per-file JSON write) + (3) `lint.py`(전수 불변조건 검사, router의 `_conflicting_fact_groups` 재사용)를 더한다. 그다음 에이전트가 raw(`CONTEXT.md`/`INVENTORY.md`/슬랙 clarification/기획서)를 읽어 object-model §14·storage §9가 정한 객체들을 authoring해 `save_object`로 적재하고, Lint 통과 + `cli` 질의 통과로 검증한다.

**Tech Stack:** Python 3, `unittest`, per-file JSON (`store.load`의 `rglob("*.json")`). 게임 런타임과 분리된 `scripts/bb2_brain/` 프로토타입.

---

## 핵심 설계 결정 (사용자 리뷰 포인트)

| 결정 | 내용 | 근거 |
|---|---|---|
| **저장 형식** | per-file JSON, storage §4 디렉토리 layout | store.load가 이미 per-file `rglob`. design-hub §0 |
| **brain root 위치** | `scripts/bb2_brain/brain/` (cli `--brain-root`로 지정). **git 추적**(.gitignore에 brain 규칙 없음 확인) | 코드와 응집 + 실데이터 재현. fixture(`tests/fixtures/.../brain/`)와 구분 |
| **스키마 정합** | object-model **full schema** 채움. `schema.py`가 kind별 필수 필드 강제, Lint가 전수 검사 | router는 일부 필드만 읽지만(예: ReviewRecord는 존재만 확인), "스키마가 실 지식을 담는지" 검증하려면 spec대로 채워야 함 |
| **적재 주체** | 에이전트(Claude)가 raw 읽고 객체 authoring → `save_object` 호출. 사람·코드 자동수집기 아님 | deep-interview 결정. 미래 스킬(`knowledge-post`형)이 이 경로를 호출 |
| **시간 필드** | `created_at`/`updated_at`/`captured_at` 등은 **호출자가 ISO 문자열로 명시**(자동 생성 안 함) | 결정론 (router 스크립트는 `Date.now` 류 금지 관례) |
| **raw 저장 깊이** | 원문 통째 저장 안 함. `EvidenceManifest`=원본 위치+redaction, `EvidenceRef`=짧은 인용만 | object-model §6.2 불변조건 |

> ⚠ **리뷰 요청**: `brain root 위치`(`scripts/bb2_brain/brain/`)와 `git 추적` 두 가지는 운영 취향이라 실행 전 확인 바람. 나머지는 spec/코드/deep-interview가 결정.

---

## File Structure

- **Create** `scripts/bb2_brain/schema.py` — object-model kind별 필수 필드 표 + `validate_object`. 단일 책임: "객체가 스키마를 지키는가". store와 lint가 공유.
- **Modify** `scripts/bb2_brain/store.py` — `save_object(brain_root, obj)` 추가 (검증 후 kind→디렉토리 매핑하여 write). 기존 `load`/`get`/`by_kind`/`all` 유지.
- **Create** `scripts/bb2_brain/lint.py` — `lint_store(store)`: 스키마 위반 + 충돌 fact + 깨진 참조 전수 검사. router `_conflicting_fact_groups` 재사용.
- **Create** `scripts/bb2_brain/tests/test_schema.py`
- **Modify** `scripts/bb2_brain/tests/test_store.py` — `save_object` round-trip 테스트 추가
- **Create** `scripts/bb2_brain/tests/test_lint.py`
- **Create (데이터)** `scripts/bb2_brain/brain/` — 첫 슬라이스 객체 JSON (Task 4에서 authoring). storage §4 layout: `raw/manifests/`, `objects/{evidence_refs,reviews,ledger,facts,code,domain,specs,comms}/`, `views/current/`
- **raw 출처 (읽기 전용 입력)**: `docs/contexts/stage-clear-token/CONTEXT.md`, `docs/contexts/stage-clear-token/INVENTORY.md`, 슬랙 `p1779766838001279`(입장팝업 표시변경 clarification), 5.5 stage clear token 기획서 Slide 8~11

---

## Task 1: schema.py — kind별 필수 필드 검증

**Files:**
- Create: `scripts/bb2_brain/schema.py`
- Test: `scripts/bb2_brain/tests/test_schema.py`

- [ ] **Step 1: 실패 테스트 작성**

`scripts/bb2_brain/tests/test_schema.py`:

```python
import unittest

from scripts.bb2_brain.schema import validate_object, SchemaError


class SchemaTest(unittest.TestCase):
    def _base(self, **over):
        obj = {
            "id": "fact.x", "kind": "TemporalFact", "schema_version": "0.1",
            "status": "reviewed", "poc_priority": "P0", "truth_role": "fact",
            "title": "x", "created_at": "2026-05-26T00:00:00+09:00",
            "updated_at": "2026-05-26T00:00:00+09:00", "tags": [], "evidence_refs": [],
            "subject": "s", "predicate": "p", "value": "v",
            "scope": {"release": "5.5"}, "valid_from": "2026-05-26T00:00:00+09:00",
            "derived_from_event_id": "event.x",
        }
        obj.update(over)
        return obj

    def test_valid_object_has_no_errors(self):
        self.assertEqual(validate_object(self._base()), [])

    def test_missing_base_field_reported(self):
        obj = self._base()
        del obj["created_at"]
        errors = validate_object(obj)
        self.assertTrue(any("created_at" in e for e in errors))

    def test_missing_kind_specific_field_reported(self):
        obj = self._base()
        del obj["valid_from"]
        errors = validate_object(obj)
        self.assertTrue(any("valid_from" in e for e in errors))

    def test_unknown_kind_reported(self):
        errors = validate_object({"id": "z.1", "kind": "Bogus"})
        self.assertTrue(any("unknown kind" in e for e in errors))
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_schema -v`
Expected: FAIL — `ModuleNotFoundError: scripts.bb2_brain.schema`

- [ ] **Step 3: schema.py 구현**

`scripts/bb2_brain/schema.py`:

```python
"""object-model 스키마의 kind별 필수 필드 검증 (첫 슬라이스 13종).
spec: docs/superpowers/specs/2026-05-27-bb2-brain-object-model-design.md
router가 실제로 읽는 필드는 일부지만, 적재 무결성을 위해 spec 필수 필드 전체를 강제한다."""

BASE_REQUIRED = (
    "id", "kind", "schema_version", "status", "poc_priority",
    "truth_role", "title", "created_at", "updated_at", "tags", "evidence_refs",
)

KIND_REQUIRED = {
    "EvidenceManifest": ("source_type", "locator", "captured_at", "captured_by",
                         "sensitivity", "acl", "redaction_status"),
    "EvidenceRef": ("evidence_manifest_id", "ref_type", "locator", "summary"),
    "ReviewRecord": ("target_object_id", "reviewer", "reviewed_at", "verdict"),
    "EventLedgerRecord": ("event_type", "happened_at", "summary", "related_objects"),
    "TemporalFact": ("subject", "predicate", "value", "scope", "valid_from",
                     "derived_from_event_id"),
    "CodeLocator": ("repo", "path", "locator_source", "verified_at"),
    "DomainContext": ("path", "scope", "source_format", "glossary_term_ids"),
    "GlossaryTerm": ("term", "definition"),
    "CurrentView": ("view_type", "as_of", "source_fact_ids", "source_event_ids", "summary"),
    "SpecDocument": ("source_system", "canonical_locator"),
    "SpecRevision": ("spec_document_id", "revision_label", "captured_at", "slide_refs"),
    "SlideRef": ("spec_revision_id", "slide_no"),
    "SlackThread": ("channel_id", "thread_ts", "participants", "message_refs", "summary"),
}

VALID_KINDS = frozenset(KIND_REQUIRED)


class SchemaError(ValueError):
    pass


def validate_object(obj: dict) -> list[str]:
    """위반 메시지 목록을 반환한다(빈 목록 = 통과). Lint가 모아 보고하도록 예외 대신 목록."""
    kind = obj.get("kind")
    if kind not in VALID_KINDS:
        return [f"{obj.get('id', '?')}: unknown kind {kind!r}"]
    errors = []
    for field in BASE_REQUIRED:
        if field not in obj:
            errors.append(f"{obj['id']}: missing base field {field!r}")
    for field in KIND_REQUIRED[kind]:
        if field not in obj:
            errors.append(f"{obj['id']}: {kind} missing field {field!r}")
    return errors
```

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_schema -v`
Expected: PASS (4 tests)

- [ ] **Step 5: 커밋**

```bash
git add scripts/bb2_brain/schema.py scripts/bb2_brain/tests/test_schema.py
git commit -m "feat: bb2-brain schema.py — object-model kind별 필수 필드 검증"
```

---

## Task 2: store.save_object — 검증 후 per-file JSON write

**Files:**
- Modify: `scripts/bb2_brain/store.py`
- Test: `scripts/bb2_brain/tests/test_store.py`

- [ ] **Step 1: 실패 테스트 작성** (test_store.py에 추가)

```python
    def test_save_object_validates_and_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            obj = {
                "id": "glossary.popup-enter", "kind": "GlossaryTerm",
                "schema_version": "0.1", "status": "reviewed", "poc_priority": "P0",
                "truth_role": "domain", "title": "입장팝업", "tags": [],
                "created_at": "2026-05-26T00:00:00+09:00",
                "updated_at": "2026-05-26T00:00:00+09:00", "evidence_refs": [],
                "term": "입장팝업", "definition": "스테이지 진입 시 뜨는 팝업.",
            }
            BrainStore.save_object(root, obj)
            store = BrainStore.load(root)
            self.assertEqual(store.get("glossary.popup-enter")["term"], "입장팝업")

    def test_save_object_rejects_schema_violation(self):
        from scripts.bb2_brain.schema import SchemaError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            with self.assertRaises(SchemaError):
                BrainStore.save_object(root, {"id": "g.x", "kind": "GlossaryTerm"})
```

(상단에 `from scripts.bb2_brain.store import BrainStore`, `from pathlib import Path`, `import tempfile`가 이미 있음 — 확인만.)

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_store -v`
Expected: FAIL — `AttributeError: type object 'BrainStore' has no attribute 'save_object'`

- [ ] **Step 3: store.py에 save_object 추가**

`store.py` 상단 import는 그대로(`json`, `Path` 있음). `BrainStore` 클래스에 classmethod 추가:

```python
    # kind → brain root 기준 상대 디렉토리 (storage §4 layout)
    _KIND_DIR = {
        "EvidenceManifest": "raw/manifests",
        "EvidenceRef": "objects/evidence_refs",
        "ReviewRecord": "objects/reviews",
        "EventLedgerRecord": "objects/ledger",
        "TemporalFact": "objects/facts",
        "CodeLocator": "objects/code",
        "DomainContext": "objects/domain",
        "GlossaryTerm": "objects/domain",
        "CurrentView": "views/current",
        "SpecDocument": "objects/specs",
        "SpecRevision": "objects/specs",
        "SlideRef": "objects/specs",
        "SlackThread": "objects/comms",
    }

    @classmethod
    def save_object(cls, brain_root: Path, obj: dict) -> Path:
        """schema 검증 통과 후 kind별 디렉토리에 <id>.json으로 쓴다. id는 호출자 책임."""
        from scripts.bb2_brain.schema import validate_object, SchemaError
        errors = validate_object(obj)
        if errors:
            raise SchemaError("; ".join(errors))
        rel = cls._KIND_DIR[obj["kind"]]
        path = Path(brain_root) / rel / f"{obj['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
```

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_store -v`
Expected: PASS (기존 + 신규 2 tests)

- [ ] **Step 5: 커밋**

```bash
git add scripts/bb2_brain/store.py scripts/bb2_brain/tests/test_store.py
git commit -m "feat: bb2-brain store.save_object — 스키마 검증 후 per-file JSON 적재"
```

---

## Task 3: lint.py — 전수 무결성 검사

**Files:**
- Create: `scripts/bb2_brain/lint.py`
- Test: `scripts/bb2_brain/tests/test_lint.py`

object-model L298 불변조건(같은 subject+predicate에 valid_until 없는 reviewed fact 2+가 값 상이) + 깨진 참조를 store 전수로 잡는다. 런타임 ⑤(router `_resolve_current_conflicts`)는 쿼리 시점만, Lint는 전수 선제. 충돌 탐지는 router의 순수 함수 `_conflicting_fact_groups`를 그대로 재사용(중복 구현 금지).

- [ ] **Step 1: 실패 테스트 작성**

`scripts/bb2_brain/tests/test_lint.py`:

```python
import tempfile
import unittest
from pathlib import Path

from scripts.bb2_brain.lint import lint_store
from scripts.bb2_brain.store import BrainStore
from scripts.bb2_brain.tests.test_router import write_object


def _fact(fid, value, **over):
    obj = {
        "id": fid, "kind": "TemporalFact", "schema_version": "0.1",
        "status": "reviewed", "poc_priority": "P0", "truth_role": "fact",
        "title": fid, "tags": [], "evidence_refs": [],
        "created_at": "2026-05-26T00:00:00+09:00",
        "updated_at": "2026-05-26T00:00:00+09:00",
        "subject": "s", "predicate": "p", "value": value,
        "scope": {"release": "5.5"}, "valid_from": "2026-05-26T00:00:00+09:00",
        "derived_from_event_id": "event.x",
    }
    obj.update(over)
    return obj


class LintTest(unittest.TestCase):
    def test_clean_store_has_no_problems(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            write_object(root, "objects/facts/a.json", _fact("fact.a", "v1"))
            self.assertEqual(lint_store(BrainStore.load(root)), [])

    def test_open_conflicting_facts_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            write_object(root, "objects/facts/a.json", _fact("fact.a", "v1"))
            write_object(root, "objects/facts/b.json", _fact("fact.b", "v2"))
            problems = lint_store(BrainStore.load(root))
            self.assertTrue(any("conflict" in p and "fact.a" in p for p in problems))

    def test_dangling_evidence_ref_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            write_object(root, "objects/facts/a.json", _fact("fact.a", "v1", evidence_refs=["ref.ghost"]))
            problems = lint_store(BrainStore.load(root))
            self.assertTrue(any("dangling evidence_ref" in p and "ref.ghost" in p for p in problems))

    def test_dangling_source_fact_id_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            write_object(root, "views/current/v.json", {
                "id": "view.v", "kind": "CurrentView", "schema_version": "0.1",
                "status": "reviewed", "poc_priority": "P0", "truth_role": "synthesis",
                "title": "v", "tags": [], "evidence_refs": [],
                "created_at": "2026-05-26T00:00:00+09:00",
                "updated_at": "2026-05-26T00:00:00+09:00",
                "view_type": "feature_status", "as_of": "2026-05-26T00:00:00+09:00",
                "source_fact_ids": ["fact.ghost"], "source_event_ids": [], "summary": "v",
            })
            problems = lint_store(BrainStore.load(root))
            self.assertTrue(any("dangling source_fact_id" in p and "fact.ghost" in p for p in problems))
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_lint -v`
Expected: FAIL — `ModuleNotFoundError: scripts.bb2_brain.lint`

- [ ] **Step 3: lint.py 구현**

`scripts/bb2_brain/lint.py`:

```python
"""오프라인 무결성 검사. store 전체를 스캔해 object-model 불변조건 위반을 모아 보고한다.
런타임(router ⑤ _resolve_current_conflicts)은 쿼리 시점 충돌만, Lint는 전수 선제 검사.
충돌 탐지는 router의 순수 함수 _conflicting_fact_groups를 재사용한다(중복 구현 금지)."""

from scripts.bb2_brain.router import _conflicting_fact_groups
from scripts.bb2_brain.schema import validate_object
from scripts.bb2_brain.store import BrainStore


def lint_store(store: BrainStore) -> list[str]:
    problems: list[str] = []
    objs = store.all()

    # 1) 스키마 위반 (kind별 필수 필드)
    for obj in objs:
        problems.extend(validate_object(obj))

    # 2) 같은 subject+predicate에 valid_until 없는 reviewed fact가 값 갈리며 2+ (object-model L298)
    for group in _conflicting_fact_groups(store.by_kind("TemporalFact")):
        ids = ", ".join(sorted(f["id"] for f in group))
        problems.append(f"conflict: open reviewed facts [{ids}] share subject+predicate but differ in value")

    # 3) CurrentView가 없는 fact를 가리킴
    for view in store.by_kind("CurrentView"):
        for fid in view.get("source_fact_ids", []):
            if not store.has(fid):
                problems.append(f"{view['id']}: dangling source_fact_id {fid}")

    # 4) dangling evidence_refs / review_record_id
    for obj in objs:
        for ref in obj.get("evidence_refs", []):
            if not store.has(ref):
                problems.append(f"{obj['id']}: dangling evidence_ref {ref}")
        rrid = obj.get("review_record_id")
        if rrid and not store.has(rrid):
            problems.append(f"{obj['id']}: dangling review_record_id {rrid}")

    return problems
```

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_lint -v`
Expected: PASS (4 tests)

- [ ] **Step 5: 커밋**

```bash
git add scripts/bb2_brain/lint.py scripts/bb2_brain/tests/test_lint.py
git commit -m "feat: bb2-brain lint.py — 스키마·충돌·dangling 참조 전수 검사 (_conflicting_fact_groups 공유)"
```

---

## Task 4: 첫 슬라이스 적재 (데이터 authoring)

이 task는 코드가 아니라 **데이터 authoring**이다. 에이전트가 raw를 읽고 object-model §14·storage §9가 정한 객체들을 만들어 `save_object`로 적재한다. 객체 내용(슬랙 요약·fact value·코드 위치)은 raw에서 추출하되, **추측 금지** — raw에 없는 값은 만들지 않는다.

**Files:**
- Create: `scripts/bb2_brain/brain/...` (아래 인벤토리)
- Create: `scripts/bb2_brain/seed_first_slice.py` (적재 스크립트 — 객체 dict들을 `save_object`로 호출. 재실행 가능하게 idempotent)

**적재 객체 인벤토리** (object-model §14 + storage §9):

| kind | 개수(목표) | 내용 | raw 출처 |
|---|---|---|---|
| `DomainContext` | 1 | stage-clear-token 컨텍스트 | `docs/contexts/stage-clear-token/CONTEXT.md` |
| `GlossaryTerm` | 5 | 입장팝업/컨티뉴 팝업/이벤트 클러스터/해피블록/요정의 선물 | `CONTEXT.md` |
| `SpecDocument` | 1 | 5.5 stage clear token 기획서 | 기획서 |
| `SpecRevision` | 1 | 해당 revision | 기획서 |
| `SlideRef` | 1~4 | Slide 8~11 책갈피 | 기획서 |
| `SlackThread` | 1 | 표시변경 clarification 스레드 | 슬랙 `p1779766838001279` |
| `EvidenceManifest` | 3~4 | spec / slack / code-search / context 각 원본 보관증 | 각 raw |
| `EvidenceRef` | 4~6 | 슬라이드/세션턴/코드로케이터 책갈피 | 각 raw |
| `EventLedgerRecord` | 2~3 | UI 공간이슈→이벤트클러스터 변경, 아이템 사용가능 UI clarification, glossary clarification | 슬랙 |
| `TemporalFact` | 2~4 | 현재 UI 규칙(displayRule=drawEventCluster 등) + 이전 규칙(valid_until 닫힘) | 슬랙+기획서 |
| `CodeLocator` | 1~3 | 입장팝업/이벤트클러스터 코드 앵커 | `INVENTORY.md` |
| `ReviewRecord` | 각 reviewed 객체당 1 | 승인 도장 | (적재 시 생성) |
| `CurrentView` | 1 | feature_status "구현 완료, QA 중" | 종합 |

- [ ] **Step 1: raw 정독**

Read: `docs/contexts/stage-clear-token/CONTEXT.md`, `docs/contexts/stage-clear-token/INVENTORY.md`. 슬랙 `p1779766838001279`는 slack MCP로 스레드 조회(채널 id 확인 필요 — INVENTORY나 task 이력에서). 기획서 Slide 8~11은 접근 가능하면 읽고, 불가하면 `EvidenceManifest`에 locator만 두고 `redaction_status: "raw_local"`로 둔다(원문 미저장).

- [ ] **Step 2: seed_first_slice.py 작성**

각 객체를 dict로 구성해 `BrainStore.save_object(BRAIN_ROOT, obj)` 호출. 모든 객체는 `status: "reviewed"`, `schema_version: "0.1"`, base 필드 전부 채움. id 규칙은 fixture 관례 따름(`fact.<slug>`, `event.<slug>`, `glossary.<slug>`, `manifest.<slug>`, `ref.<slug>`, `locator.<slug>`, `review.<target-id>`, `view.<slug>`). 시간 필드는 raw 근거 시각(슬랙 ts 등)을 ISO로.

**예시 (TemporalFact 현재 규칙 — fixture `fact.current-rule`을 full schema로 승격):**

```python
BRAIN_ROOT = Path(__file__).parent / "brain"

save = lambda o: BrainStore.save_object(BRAIN_ROOT, o)

save({
    "id": "fact.eventcluster-displayrule-current", "kind": "TemporalFact",
    "schema_version": "0.1", "status": "reviewed", "poc_priority": "P0",
    "truth_role": "fact", "title": "입장팝업 이벤트 클러스터 표시 규칙(현재)",
    "tags": ["stage-clear-token"], "evidence_refs": ["ref.slack-display-change"],
    "review_record_id": "review.fact.eventcluster-displayrule-current",
    "created_at": "2026-05-26T00:00:00+09:00", "updated_at": "2026-05-26T00:00:00+09:00",
    "subject": "stage-clear-token.PopupEnter.eventCluster.displayRule",
    "predicate": "uses", "value": "drawEventCluster",
    "scope": {"project": "bb2-client", "release": "5.5",
              "feature": "stage-clear-token", "surface": "PopupEnter"},
    "valid_from": "2026-05-26T00:00:00+09:00",
    "supersedes": "fact.eventcluster-displayrule-old",
    "derived_from_event_id": "event.ui-space-pressure",
})
```

나머지 객체(GlossaryTerm 5, EventLedgerRecord 2~3, EvidenceManifest/Ref, CodeLocator, SpecDocument/Revision/SlideRef, SlackThread, ReviewRecord, CurrentView)도 같은 방식으로 raw에서 추출해 작성. **관계 일관성 필수**: `derived_from_event_id`·`supersedes`·`source_fact_ids`·`evidence_refs`·`review_record_id`가 실제 적재되는 id를 가리켜야 함(Lint Task 3이 깨진 참조를 잡음).

- [ ] **Step 3: 적재 실행**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m scripts.bb2_brain.seed_first_slice`
Expected: 예외 없이 완료. `scripts/bb2_brain/brain/` 아래 객체 JSON 생성.

- [ ] **Step 4: 커밋**

```bash
git add scripts/bb2_brain/seed_first_slice.py scripts/bb2_brain/brain/
git commit -m "feat: bb2-brain 첫 슬라이스 적재 — 스테이지 클리어 토큰 입장팝업 실데이터"
```

---

## Task 5: end-to-end 검증 (Lint 통과 + cli 질의)

**Files:**
- (검증만, 신규 파일 없음. 필요 시 `tests/test_first_slice_e2e.py` 추가)

- [ ] **Step 1: Lint 통과 확인**

```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -c "
from pathlib import Path
from scripts.bb2_brain.store import BrainStore
from scripts.bb2_brain.lint import lint_store
problems = lint_store(BrainStore.load(Path('scripts/bb2_brain/brain')))
print('\n'.join(problems) if problems else 'LINT CLEAN')
"
```
Expected: `LINT CLEAN` (위반 있으면 Task 4로 돌아가 객체 수정)

- [ ] **Step 2: cli로 "왜 바뀌었나 + 지금 규칙" 질의**

```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m scripts.bb2_brain.cli --brain-root scripts/bb2_brain/brain "5.5 기준 입장팝업 표시가 왜 바뀌었고 현재 QA 기준은 뭐야?"
```
Expected: JSON 출력에서 `"intents": ["why_changed", "current_status"]`, `"status": "reviewed"`, `source_object_ids`에 적재한 event·fact id 포함, `needs_clarification: false`.

- [ ] **Step 3: 기존 acceptance와 동등성 확인 (선택: e2e 테스트)**

`tests/test_router.py`의 `test_stage_clear_token_acceptance_answer`가 인메모리 fixture로 검증하는 것과 **같은 intent 분해·status·근거 구조**가 디스크 데이터에서도 나오는지 대조. 차이가 있으면 fixture와 실데이터 스키마 격차이므로 기록.

```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m scripts.bb2_brain.cli --brain-root scripts/bb2_brain/brain "5.5 기준 입장팝업의 요정의 선물/해피블록 표시가 왜 drawEventCluster 형태로 바뀌었고, 현재 QA 기준 동작은 뭐야?"
```
Expected: `"intents": ["why_changed", "current_status", "implementation_location"]`, `"status": "reviewed"`.

- [ ] **Step 4: 전체 테스트 회귀 확인**

```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store scripts.bb2_brain.tests.test_schema scripts.bb2_brain.tests.test_lint -v
```
Expected: 전부 PASS (기존 70 + schema 4 + lint 4 + store 2 신규)

- [ ] **Step 5: 커밋 (e2e 테스트 추가한 경우)**

```bash
git add scripts/bb2_brain/tests/test_first_slice_e2e.py
git commit -m "test: bb2-brain 첫 슬라이스 e2e — 디스크 데이터로 acceptance 질의 통과"
```

---

## Self-Review

**1. Spec coverage** (deep-interview 결론 대비):
- 목적(ingest 절차 + 스키마 검증) → Task 1~3(스키마·쓰기경로·Lint) + Task 5(e2e) ✓
- 대상(스테이지 클리어 토큰) → Task 4 인벤토리 ✓
- 저장 형식(JSON 객체) → Task 2 `_KIND_DIR` + per-file write ✓
- 적재 방식(에이전트가 raw 읽고 채움 + 무결성 강제) → Task 4 + Lint Task 3 ✓
- 완료 기준(적재→Lint→cli 질의) → Task 5 ✓
- 미래 자리(스킬/세션추출) → `save_object`가 그 진입점. 본 plan 범위 밖(명시적 제외) ✓

**2. Placeholder scan:** 코드 task(1~3)는 실제 코드 전량 포함. Task 4는 데이터 authoring이라 "raw에서 추출" 지시가 본질(placeholder 아님) — 단 객체 내용은 raw 정독 후 결정되므로 예시 1개만 박고 나머지는 인벤토리+스키마+출처로 명세. 이는 데이터 task의 정당한 형태.

**3. Type consistency:** `validate_object`(목록 반환), `SchemaError`(store가 raise), `save_object(brain_root, obj)`, `lint_store(store)`, `_conflicting_fact_groups`(router 기존) — Task 간 시그니처 일치 확인. `_KIND_DIR` 키 13종 = `KIND_REQUIRED` 키 13종 일치.

**알려진 제약:**
- `_conflicting_fact_groups`는 scope를 보지 않음(주석 명시) → Lint도 scope 무관 충돌만 잡음. scope별 충돌은 G9/⑤ 런타임 소관, Lint 범위 밖.
- 첫 슬라이스 객체 개수는 "목표"이며 raw 실제 내용에 따라 가감. Lint가 관계 일관성을 보장하므로 개수보다 참조 정합이 우선.
