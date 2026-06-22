# 매핑 보증 용어 자동 승격 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** reviewed `DomainMapping`이 보증하고 배치 적대검증으로 커버 확인된 비-conflict candidate `GlossaryTerm`을, 짝 매핑의 근거를 물려받아 reviewed로 승격하는 코드(자동·수동 두 경로 공유)를 만든다.

**Architecture:** 새 순수 함수 3개(`vouching_mappings` / `backfill_evidence` / `select_vouched_candidates`)를 `promote.py`에 두고, 기존 `promote()`에 검수기록 extra 주입 인자를 추가한다. `cli.py`에 자동 일괄 승격 진입점 `promote-auto`를 신설하고 기존 `promote`(수동)에 backfill·멱등가드·conflict 해소기록을 통합한다. `lint.py`에는 `lint_store`(차단)와 분리된 비차단 드리프트 경고 함수를 추가한다. 판정(어느 용어가 매핑 의미를 초과하나)은 적대검증 워크플로우(에이전트)가, 적재(backfill+승격)는 cli가 한다.

**Tech Stack:** Python 3, `unittest`, 기존 bb2_brain 엔진(`store`/`schema`/`objbase`/`ingest`/`lint`).

**권위 spec:** `docs/superpowers/specs/2026-06-08-bb2-brain-mapping-vouched-term-promotion-design.md` (커밋 `94fcda71e5`)

**실행 환경:** Python은 `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python`. 테스트는 레포 루트(`/Users/al03040455/Desktop/bb2_client`)에서 실행(import가 `scripts.bb2_brain.*` 절대경로라 루트가 작업 디렉토리여야 함).

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests -q
```

**브랜치:** `docs/bb2-brain-object-model` (이미 체크아웃됨, 검증 후 auto-commit OK). `brain/` 코퍼스는 설계상 git 미추적이라 코드 커밋과 무관.

---

## File Structure

코드 단위와 책임. spec §4.7 산출물을 파일별로 매핑한다.

| 파일 | 변경 | 책임 |
|------|------|------|
| `scripts/bb2_brain/promote.py` | 수정 | 순수 함수 `vouching_mappings`/`backfill_evidence`/`select_vouched_candidates` 추가 + `promote()`에 `review_extra_by_id` 인자 추가 (§4.1, §4.2, §4.5) |
| `scripts/bb2_brain/cli.py` | 수정 | `promote-auto` 진입점 신설(§4.3) + 기존 `promote`(수동)에 backfill·멱등가드·conflict 해소기록 통합(§4.4) |
| `scripts/bb2_brain/lint.py` | 수정 | 비차단 드리프트 경고 `unpromoted_vouched_terms` 추가 — `lint_store`와 분리(§4.6) |
| `scripts/bb2_brain/schema.py` | 수정 | ReviewRecord `vouched_by_mapping_ids`/`conflict_resolution` 선택 필드 주석(§4.5, 강제 아님·버전 bump 없음) |
| `scripts/bb2_brain/tests/test_promote.py` | 수정 | 순수 함수 + `review_extra_by_id` 단위 테스트 |
| `scripts/bb2_brain/tests/test_cli.py` | 수정 | `promote-auto` 일괄/dedup/skip/멱등 + 수동 통합(backfill/멱등/conflict) 테스트 |
| `scripts/bb2_brain/tests/test_lint.py` | 수정 | 드리프트 경고 테스트 |

**왜 `promote.py`에 모으나:** 세 순수 함수는 전부 "어느 매핑이 어느 용어를 보증하나"라는 한 가지 관계를 다루고 승격 직전에 쓰인다. 승격 로직과 같이 변하므로 같이 둔다. `promote()`는 store를 모르는 채 유지하고(객체 리스트만 받음), store-aware 헬퍼는 별도 함수로 분리한다.

**왜 드리프트를 `lint_store`에서 분리하나:** `ingest`(ingest.py:37-39)와 `promote`(cli.py:88-91)가 `lint_store` 결과를 **차단(블로킹)**으로 쓴다. candidate 용어는 적재 직후 정상이지만 드리프트 대상이기도 하므로, 드리프트를 `lint_store`에 넣으면 candidate를 적재하는 모든 ingest가 깨진다. 따라서 드리프트는 비차단 별도 함수로 둔다.

---

## Task 1: promote.py 순수 함수 (vouching_mappings / backfill_evidence / select_vouched_candidates)

매핑↔용어 보증 관계를 다루는 store-aware 순수 함수 3개. `promote()`는 건드리지 않는다(Task 2).

**Files:**
- Modify: `scripts/bb2_brain/promote.py` (함수 추가, 기존 `promote()` 유지)
- Test: `scripts/bb2_brain/tests/test_promote.py`

- [ ] **Step 1: 실패하는 테스트 작성 (test_promote.py 상단 import + 새 클래스 추가)**

기존 `test_promote.py`의 import 블록(8~9행)을 아래로 교체한다:

```python
from scripts.bb2_brain.objbase import base
from scripts.bb2_brain.promote import (
    promote,
    vouching_mappings,
    backfill_evidence,
    select_vouched_candidates,
)
from scripts.bb2_brain.schema import validate_object
from scripts.bb2_brain.store import BrainStore
```

파일 끝의 `if __name__ == "__main__":` 직전에 아래 헬퍼 + 테스트 클래스를 추가한다:

```python
def _ev_ref(rid):
    """store.has 통과용 최소 EvidenceRef (backfill은 store.has만 본다)."""
    return base(
        {
            "id": rid,
            "kind": "EvidenceRef",
            "status": "reviewed",
            "truth_role": "reference",
            "title": "ref",
            "evidence_manifest_id": "ev.manifest",
            "ref_type": "spec_section",
            "locator": {"section": "1"},
            "summary": "인용",
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


def _reviewed_mapping(mid, *, term_ids, evidence_refs, mapping_key="key"):
    """짝 매핑 — reviewed DomainMapping."""
    return base(
        {
            "id": mid,
            "kind": "DomainMapping",
            "status": "reviewed",
            "truth_role": "domain",
            "title": "매핑",
            "context_id": "context.neutral",
            "mapping_key": mapping_key,
            "canonical_summary": "요약",
            "meaning": "의미",
            "boundary": "경계",
            "glossary_term_ids": term_ids,
            "decision_record_ids": [],
            "evidence_refs": evidence_refs,
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


def _empty_candidate(tid, *, term="용어", candidate_state="evidence_verified"):
    """evidence_refs 빈 candidate GlossaryTerm."""
    return base(
        {
            "id": tid,
            "kind": "GlossaryTerm",
            "status": "candidate",
            "truth_role": "domain",
            "title": "Candidate term: 용어",
            "context_id": "context.neutral",
            "term": term,
            "definition": "정의",
            "evidence_refs": [],
            "candidate": {"candidate_state": candidate_state, "candidate_source": "spec"},
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


def _store(*objs):
    return BrainStore({o["id"]: o for o in objs})


class TestBackfillEvidence(unittest.TestCase):
    def test_empty_term_filled_from_paired_mapping(self):
        store = _store(
            _ev_ref("evref.a"),
            _empty_candidate("g.e"),
            _reviewed_mapping("m.e", term_ids=["g.e"], evidence_refs=["evref.a"]),
        )
        out = backfill_evidence(store.get("g.e"), store)
        self.assertEqual(out["evidence_refs"], ["evref.a"])
        # 원본 불변 (새 dict 반환)
        self.assertEqual(store.get("g.e")["evidence_refs"], [])

    def test_term_with_evidence_unchanged(self):
        term = _empty_candidate("g.e")
        term["evidence_refs"] = ["evref.existing"]
        store = _store(
            _ev_ref("evref.existing"),
            term,
            _reviewed_mapping("m.e", term_ids=["g.e"], evidence_refs=["evref.a"]),
        )
        out = backfill_evidence(store.get("g.e"), store)
        self.assertEqual(out["evidence_refs"], ["evref.existing"])

    def test_no_paired_mapping_stays_empty(self):
        store = _store(_empty_candidate("g.e"))
        out = backfill_evidence(store.get("g.e"), store)
        self.assertEqual(out["evidence_refs"], [])

    def test_dangling_mapping_ref_excluded(self):
        store = _store(
            _ev_ref("evref.a"),
            _empty_candidate("g.e"),
            # evref.gone 은 store에 없음 → backfill에서 제외
            _reviewed_mapping("m.e", term_ids=["g.e"], evidence_refs=["evref.a", "evref.gone"]),
        )
        out = backfill_evidence(store.get("g.e"), store)
        self.assertEqual(out["evidence_refs"], ["evref.a"])

    def test_candidate_mapping_does_not_vouch(self):
        # candidate 상태 매핑은 보증하지 않는다 (reviewed만).
        cand_map = _reviewed_mapping("m.c", term_ids=["g.e"], evidence_refs=["evref.a"])
        cand_map["status"] = "candidate"
        store = _store(_ev_ref("evref.a"), _empty_candidate("g.e"), cand_map)
        out = backfill_evidence(store.get("g.e"), store)
        self.assertEqual(out["evidence_refs"], [])


class TestSelectVouchedCandidates(unittest.TestCase):
    def test_includes_observed_and_evidence_verified(self):
        store = _store(
            _ev_ref("evref.a"),
            _empty_candidate("g.obs", candidate_state="observed"),
            _empty_candidate("g.ev", candidate_state="evidence_verified"),
            _reviewed_mapping("m1", term_ids=["g.obs", "g.ev"], evidence_refs=["evref.a"]),
        )
        sel = select_vouched_candidates(store)
        self.assertEqual(set(sel), {"g.obs", "g.ev"})

    def test_excludes_conflict(self):
        store = _store(
            _ev_ref("evref.a"),
            _empty_candidate("g.c", candidate_state="conflict"),
            _reviewed_mapping("m1", term_ids=["g.c"], evidence_refs=["evref.a"]),
        )
        self.assertEqual(select_vouched_candidates(store), {})

    def test_excludes_unreferenced(self):
        store = _store(_empty_candidate("g.lonely"))
        self.assertEqual(select_vouched_candidates(store), {})

    def test_multi_mapping_collects_all_sorted(self):
        store = _store(
            _ev_ref("evref.a"),
            _ev_ref("evref.b"),
            _empty_candidate("g.multi"),
            _reviewed_mapping("m.z", term_ids=["g.multi"], evidence_refs=["evref.b"], mapping_key="z"),
            _reviewed_mapping("m.a", term_ids=["g.multi"], evidence_refs=["evref.a"], mapping_key="a"),
        )
        sel = select_vouched_candidates(store)
        self.assertEqual(sel, {"g.multi": ["m.a", "m.z"]})  # 정렬됨

    def test_candidate_mapping_does_not_select(self):
        cand_map = _reviewed_mapping("m.c", term_ids=["g.e"], evidence_refs=["evref.a"])
        cand_map["status"] = "candidate"
        store = _store(_ev_ref("evref.a"), _empty_candidate("g.e"), cand_map)
        self.assertEqual(select_vouched_candidates(store), {})


class TestVouchingMappings(unittest.TestCase):
    def test_returns_reviewed_mappings_sorted_by_id(self):
        store = _store(
            _ev_ref("evref.a"),
            _empty_candidate("g.x"),
            _reviewed_mapping("m.b", term_ids=["g.x"], evidence_refs=["evref.a"], mapping_key="b"),
            _reviewed_mapping("m.a", term_ids=["g.x"], evidence_refs=["evref.a"], mapping_key="a"),
        )
        ms = vouching_mappings("g.x", store)
        self.assertEqual([m["id"] for m in ms], ["m.a", "m.b"])
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_promote.py -q`
Expected: FAIL — `ImportError: cannot import name 'vouching_mappings'`

- [ ] **Step 3: promote.py에 순수 함수 3개 추가**

`promote.py`의 `from scripts.bb2_brain.objbase import review_record` 줄 아래, `def promote(...)` 정의 **위에** 추가:

```python
def vouching_mappings(term_id, store):
    """이 용어를 glossary_term_ids로 참조하는 reviewed DomainMapping 목록(id 오름차순).

    candidate 매핑은 보증하지 않는다(reviewed만). 결정론을 위해 id로 정렬한다.
    """
    matched = [
        m for m in store.by_kind("DomainMapping")
        if m.get("status") == "reviewed" and term_id in (m.get("glossary_term_ids") or [])
    ]
    return sorted(matched, key=lambda m: m["id"])


def backfill_evidence(term, store):
    """candidate term의 evidence_refs가 비면 짝 reviewed 매핑 evref 합집합으로 채운 새 dict 반환.

    합집합은 중복 제거 + store.has 실존하는 것만(깨진 참조 제외, spec §4.1). 이미 근거가
    있으면 손대지 않는다(최소 변경). 원본은 불변(dict 복사 반환).
    """
    out = dict(term)
    if out.get("evidence_refs"):
        return out
    union = []
    seen = set()
    for mapping in vouching_mappings(term["id"], store):
        for ref in mapping.get("evidence_refs") or []:
            if ref not in seen and store.has(ref):
                seen.add(ref)
                union.append(ref)
    out["evidence_refs"] = union
    return out


def select_vouched_candidates(store):
    """1단계 기계 선별(spec §4.2): reviewed 매핑이 참조하는 비-conflict candidate GlossaryTerm.

    반환: {term_id: [보증 reviewed 매핑 id 오름차순]}. 매핑 미참조·conflict·reviewed는 제외.
    실코퍼스 기준 115개(122 candidate − 7 conflict, 미참조 0)를 산출한다.
    """
    vouchers = {}  # term_id -> set(mapping_id)
    for mapping in store.by_kind("DomainMapping"):
        if mapping.get("status") != "reviewed":
            continue
        for tid in mapping.get("glossary_term_ids") or []:
            vouchers.setdefault(tid, set()).add(mapping["id"])
    result = {}
    for term in store.by_kind("GlossaryTerm"):
        if term.get("status") != "candidate":
            continue
        if (term.get("candidate") or {}).get("candidate_state") == "conflict":
            continue
        tid = term["id"]
        if tid in vouchers:
            result[tid] = sorted(vouchers[tid])
    return result
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_promote.py -q`
Expected: PASS (기존 + 신규 전부)

- [ ] **Step 5: 커밋**

```bash
cd /Users/al03040455/Desktop/bb2_client
git add scripts/bb2_brain/promote.py scripts/bb2_brain/tests/test_promote.py
git commit -m "feat(brain): add vouching_mappings/backfill_evidence/select_vouched_candidates (mapping-vouched promotion §4.1-4.2)"
```

---

## Task 2: promote()에 review_extra_by_id 인자 추가 + schema 주석

검수기록에 per-id 추가 필드(`vouched_by_mapping_ids` 자동 / `conflict_resolution` 수동)를 주입할 통로를 `promote()` single_object 경로에 만든다.

**Files:**
- Modify: `scripts/bb2_brain/promote.py:11` (시그니처), `scripts/bb2_brain/promote.py:23-47` (single_object 루프)
- Modify: `scripts/bb2_brain/schema.py:213` (ReviewRecord 주석)
- Test: `scripts/bb2_brain/tests/test_promote.py`

- [ ] **Step 1: 실패하는 테스트 작성 (test_promote.py `TestSingleObject` 클래스에 추가)**

`TestSingleObject` 클래스 안에 메서드 추가:

```python
    def test_single_object_merges_review_extra(self):
        objs = [candidate_term("g.x")]
        promoted, records = promote(
            objs, ["g.x"], "single_object",
            reviewer="auto:mapping-vouched", reviewed_at=T,
            review_extra_by_id={"g.x": {"vouched_by_mapping_ids": ["m.z", "m.a"]}},
        )
        rr = records[0]
        self.assertEqual(rr["reviewer"], "auto:mapping-vouched")
        self.assertEqual(rr["vouched_by_mapping_ids"], ["m.z", "m.a"])
        # 추가 필드가 있어도 스키마 통과
        self.assertEqual(validate_object(rr), [])

    def test_single_object_no_extra_when_absent(self):
        objs = [candidate_term("g.x")]
        _, records = promote(
            objs, ["g.x"], "single_object", reviewer="user-confirmed", reviewed_at=T,
        )
        self.assertNotIn("vouched_by_mapping_ids", records[0])
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_promote.py::TestSingleObject -q`
Expected: FAIL — `TypeError: promote() got an unexpected keyword argument 'review_extra_by_id'`

- [ ] **Step 3: promote() 시그니처 + single_object 루프 수정**

`promote.py`의 시그니처(11행)를 교체:

```python
def promote(objects, ids, scope, *, bundle_key=None, reviewer, reviewed_at,
            review_extra_by_id=None):
```

single_object 분기(현재 23~47행)를 교체. `review_record(...)` 호출에 per-id extra를 merge한다:

```python
    index = {o["id"]: o for o in objects}
    if scope == "single_object":
        extra_by_id = review_extra_by_id or {}
        promoted_objects = []
        review_records = []
        for tid in ids:
            obj = index[tid]  # 없는 id면 KeyError
            reviewed = dict(obj)
            reviewed["status"] = "reviewed"
            reviewed["updated_at"] = reviewed_at
            reviewed.pop("candidate", None)
            review_id = "review." + reviewed["id"]
            reviewed["review_record_id"] = review_id
            rr = review_record(
                review_id,
                target_object_id=reviewed["id"],
                reviewer=reviewer,
                reviewed_at=reviewed_at,
                verdict="approved",
                tags=reviewed.get("tags", []),
                created_at=reviewed_at,
                updated_at=reviewed_at,
                evidence_refs=reviewed.get("evidence_refs", []),
                **extra_by_id.get(tid, {}),
            )
            promoted_objects.append(reviewed)
            review_records.append(rr)
        return promoted_objects, review_records
```

(`review_record`의 `**extra`가 `obj.update(extra)`로 merge — objbase.py:62. mapping_bundle 분기와 docstring은 그대로 둔다.)

`promote.py` 모듈 docstring 끝에 한 줄 추가(`review_extra_by_id` 설명):

```python
    review_extra_by_id(single_object 전용)는 {object_id: {추가필드}}로, 각 검수기록에 per-id로
    merge한다 — 자동 승격의 vouched_by_mapping_ids(§4.5), 수동 conflict 해소 기록(§4.4)에 쓴다.
```

- [ ] **Step 4: schema.py에 선택 필드 주석 추가**

`schema.py`의 `elif kind == "ReviewRecord":`(213행) 바로 아래에 주석 추가:

```python
    elif kind == "ReviewRecord":
        # 선택 필드(검증·강제 안 함, 버전 bump 없음, spec §4.5):
        #   vouched_by_mapping_ids: list[str] — auto:mapping-vouched 승격이 보증한 reviewed 매핑 id.
        #   conflict_resolution: str — 수동 conflict 용어 승격 시 정설 선택 근거.
        review_type = obj.get("review_type")
```

- [ ] **Step 5: 테스트 통과 확인 (전체 promote 테스트로 회귀까지)**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_promote.py -q`
Expected: PASS (mapping_bundle 기존 테스트 포함 전부)

- [ ] **Step 6: 커밋**

```bash
cd /Users/al03040455/Desktop/bb2_client
git add scripts/bb2_brain/promote.py scripts/bb2_brain/schema.py scripts/bb2_brain/tests/test_promote.py
git commit -m "feat(brain): promote() review_extra_by_id for per-id review fields + ReviewRecord optional-field doc (§4.5)"
```

---

## Task 3: cli promote-auto 진입점 (자동 일괄 승격)

검증 워크플로우가 산출한 pass 목록을 `--ids`로 받아, 각 용어를 1단계 기준으로 다시 가드 → backfill → `reviewer="auto:mapping-vouched"` + `vouched_by_mapping_ids`로 일괄 승격한다. 건너뛴 사유를 보고한다(조용한 누락 금지).

**Files:**
- Modify: `scripts/bb2_brain/cli.py` (`_run_promote_auto` 추가, `main()` 라우팅)
- Test: `scripts/bb2_brain/tests/test_cli.py`

- [ ] **Step 1: 실패하는 테스트 작성 (test_cli.py 끝에 추가)**

`test_cli.py`의 import 블록(17~24행)은 그대로 두고, 파일 끝 `if __name__ == "__main__":` 직전에 추가:

```python
def _ar_evref(rid, manifest_id="ev.manifest"):
    from scripts.bb2_brain.objbase import base
    return base(
        {
            "id": rid, "kind": "EvidenceRef", "status": "reviewed", "truth_role": "reference",
            "title": "ref", "evidence_manifest_id": manifest_id, "ref_type": "spec_section",
            "locator": {"section": "1"}, "summary": "인용",
        },
        tags=["neutral"], created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z",
    )


def _ar_term(tid, *, term, candidate_state="evidence_verified", evidence_refs=None):
    from scripts.bb2_brain.objbase import base
    return base(
        {
            "id": tid, "kind": "GlossaryTerm", "status": "candidate", "truth_role": "domain",
            "title": f"Candidate term: {term}", "context_id": "context.neutral",
            "term": term, "definition": "후보 정의",
            "evidence_refs": evidence_refs if evidence_refs is not None else [],
            "candidate": {"candidate_state": candidate_state, "candidate_source": "spec"},
        },
        tags=["neutral"], created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z",
    )


def _ar_mapping(mid, *, term_ids, evidence_refs, mapping_key):
    from scripts.bb2_brain.objbase import base
    return base(
        {
            "id": mid, "kind": "DomainMapping", "status": "reviewed", "truth_role": "domain",
            "title": "매핑", "context_id": "context.neutral", "mapping_key": mapping_key,
            "canonical_summary": "요약", "meaning": "의미", "boundary": "경계",
            "glossary_term_ids": term_ids, "decision_record_ids": [], "evidence_refs": evidence_refs,
        },
        tags=["neutral"], created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z",
    )


class TestCliPromoteAuto(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _ingest_corpus(self):
        from scripts.bb2_brain.ingest import ingest
        bundle = [
            manifest(),
            _ar_evref("evref.a"), _ar_evref("evref.b"),
            context(),
            _ar_term("g.empty", term="빈근거"),                       # 빈 근거 → backfill 대상
            _ar_term("g.has", term="근거있음", evidence_refs=["evref.b"]),
            _ar_term("g.conflict", term="충돌", candidate_state="conflict"),
            _ar_term("g.multi", term="다중참조"),                     # 매핑 2개가 참조
            _ar_mapping("m.empty", term_ids=["g.empty"], evidence_refs=["evref.a"], mapping_key="me"),
            _ar_mapping("m.has", term_ids=["g.has"], evidence_refs=["evref.b"], mapping_key="mh"),
            _ar_mapping("m.conflict", term_ids=["g.conflict"], evidence_refs=["evref.a"], mapping_key="mc"),
            _ar_mapping("m.z", term_ids=["g.multi"], evidence_refs=["evref.b"], mapping_key="z"),
            _ar_mapping("m.a", term_ids=["g.multi"], evidence_refs=["evref.a"], mapping_key="a"),
        ]
        ingest(self.root, bundle)

    def _run(self, ids):
        argv = ["promote-auto", "--brain-root", str(self.root),
                "--ids", *ids, "--reviewed-at", "2026-06-08T00:00:00Z"]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        return rc, json.loads(out.getvalue())

    def test_batch_promotes_eligible_skips_conflict_and_unknown(self):
        self._ingest_corpus()
        rc, result = self._run(["g.empty", "g.has", "g.conflict", "g.multi", "g.nope"])
        self.assertEqual(rc, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(set(result["promoted"]), {"g.empty", "g.has", "g.multi"})
        self.assertEqual(result["skipped"]["conflict"], ["g.conflict"])
        self.assertEqual(result["skipped"]["unknown_id"], ["g.nope"])
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.empty")["status"], "reviewed")
        # backfill: 빈 근거 용어가 짝 매핑 evref로 채워짐
        self.assertEqual(store.get("g.empty")["evidence_refs"], ["evref.a"])
        from scripts.bb2_brain.lint import lint_store
        self.assertEqual(lint_store(store), [])

    def test_review_record_records_auto_reviewer_and_vouched_by(self):
        self._ingest_corpus()
        self._run(["g.empty", "g.multi"])
        store = BrainStore.load(self.root)
        rr_empty = store.get("review.g.empty")
        self.assertEqual(rr_empty["reviewer"], "auto:mapping-vouched")
        self.assertEqual(rr_empty["vouched_by_mapping_ids"], ["m.empty"])
        # 다중 참조: 보증 매핑 전부, 정렬됨
        rr_multi = store.get("review.g.multi")
        self.assertEqual(rr_multi["vouched_by_mapping_ids"], ["m.a", "m.z"])

    def test_dedup_multi_mapping_promotes_once(self):
        self._ingest_corpus()
        rc, result = self._run(["g.multi", "g.multi"])
        self.assertEqual(rc, 0)
        self.assertEqual(result["promoted"], ["g.multi"])

    def test_rerun_is_idempotent(self):
        self._ingest_corpus()
        self._run(["g.empty", "g.has", "g.multi"])
        rc, result = self._run(["g.empty", "g.has", "g.multi"])
        self.assertEqual(rc, 0)
        self.assertEqual(result["promoted"], [])
        self.assertEqual(set(result["skipped"]["already_reviewed"]), {"g.empty", "g.has", "g.multi"})
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_cli.py::TestCliPromoteAuto -q`
Expected: FAIL — `promote-auto`가 query 경로로 빠져 에러(서브커맨드 미인식)

- [ ] **Step 3: cli.py에 _run_promote_auto 추가 + main() 라우팅**

`cli.py` import 블록(6~11행)에 backfill·드리프트·선별 함수 추가:

```python
from scripts.bb2_brain.ingest import IngestError, ingest
from scripts.bb2_brain.lint import lint_store
from scripts.bb2_brain.promote import (
    promote,
    backfill_evidence,
    select_vouched_candidates,
)
from scripts.bb2_brain.router import QueryRouter
from scripts.bb2_brain.schema import validate_object
from scripts.bb2_brain.store import BrainStore
```

`_run_promote`(47~95행) 정의 **아래**에 `_run_promote_auto` 추가:

```python
def _run_promote_auto(argv) -> int:
    parser = argparse.ArgumentParser(prog="cli promote-auto")
    parser.add_argument("--brain-root", required=True)
    parser.add_argument("--ids", required=True, nargs="+",
                        help="배치 커버리지 검증 워크플로우가 산출한 pass 용어 id 목록(§4.2b)")
    parser.add_argument("--reviewed-at", required=True)
    args = parser.parse_args(argv)

    brain_root = Path(args.brain_root)
    store = BrainStore.load(brain_root)
    selection = select_vouched_candidates(store)  # {term_id: [보증 매핑 id]}

    # --ids를 1단계 기준으로 다시 가드 → 건너뛴 사유별 분류(조용한 누락 금지, §4.3).
    skipped = {"unknown_id": [], "not_glossary_term": [], "already_reviewed": [],
               "not_candidate": [], "conflict": [], "unreferenced": []}
    eligible = []
    seen = set()
    for tid in args.ids:
        if tid in seen:
            continue  # 입력 중복 dedup(§4.3)
        seen.add(tid)
        if not store.has(tid):
            skipped["unknown_id"].append(tid); continue
        obj = store.get(tid)
        if obj.get("kind") != "GlossaryTerm":
            skipped["not_glossary_term"].append(tid); continue
        if obj.get("status") == "reviewed":
            skipped["already_reviewed"].append(tid); continue
        if obj.get("status") != "candidate":
            skipped["not_candidate"].append(tid); continue
        if (obj.get("candidate") or {}).get("candidate_state") == "conflict":
            skipped["conflict"].append(tid); continue
        if tid not in selection:
            skipped["unreferenced"].append(tid); continue
        eligible.append(tid)

    promoted, records = [], []
    if eligible:
        objects = [backfill_evidence(store.get(tid), store) for tid in eligible]
        review_extra = {tid: {"vouched_by_mapping_ids": selection[tid]} for tid in eligible}
        try:
            promoted, records = promote(
                objects, eligible, "single_object",
                reviewer="auto:mapping-vouched", reviewed_at=args.reviewed_at,
                review_extra_by_id=review_extra,
            )
        except (ValueError, KeyError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
        # 원자성: 쓰기 전 일괄 schema 검증(backfill 후에도 근거 빈 용어가 있으면 여기서 막힘).
        to_write = promoted + records
        schema_errors = []
        for obj in to_write:
            schema_errors.extend(validate_object(obj))
        if schema_errors:
            print(json.dumps({"ok": False, "error": "; ".join(schema_errors)}, ensure_ascii=False, indent=2))
            return 1
        for obj in to_write:
            BrainStore.save_object(brain_root, obj)
        problems = lint_store(BrainStore.load(brain_root))  # 사후 lint 1회(참조 무결성)
        if problems:
            print(json.dumps({"ok": False, "lint": problems}, ensure_ascii=False, indent=2))
            return 1

    # 승격 후 남은 보증 용어(보류된 커버리지 불통과분 등) 비차단 드리프트 신호(§4.6).
    from scripts.bb2_brain.lint import unpromoted_vouched_terms
    drift_remaining = unpromoted_vouched_terms(BrainStore.load(brain_root))
    skipped = {k: v for k, v in skipped.items() if v}  # 빈 사유 제거
    print(json.dumps(
        {"ok": True, "promoted": [o["id"] for o in promoted],
         "reviews": [r["id"] for r in records], "skipped": skipped,
         "drift_remaining": drift_remaining},
        ensure_ascii=False, indent=2))
    return 0
```

`main()`(98~105행)에 라우팅 추가 — `promote` 검사 위/아래 무관(정확 일치):

```python
def main() -> int:
    argv = sys.argv[1:]
    # 첫 인자가 서브커맨드면 해당 경로, 아니면 기존 query 경로 호환 유지(AC6)
    if argv and argv[0] == "ingest":
        return _run_ingest(argv[1:])
    if argv and argv[0] == "promote-auto":
        return _run_promote_auto(argv[1:])
    if argv and argv[0] == "promote":
        return _run_promote(argv[1:])
    return _run_query(argv)
```

(주의: `_run_promote_auto`가 `unpromoted_vouched_terms`를 import하므로 Task 5에서 이 함수가 lint.py에 생긴 뒤 테스트가 통과한다. 같은 PR 내라 순서상 Task 5 구현 전이면 이 import가 `ImportError`. 따라서 **이 Task의 Step 4(통과 확인)는 Task 5 구현 후로 미룬다** — 아래 Step 4 참고.)

- [ ] **Step 4: 테스트 통과 확인 (Task 5 `unpromoted_vouched_terms` 구현 의존)**

`_run_promote_auto`가 `unpromoted_vouched_terms`를 부르므로 **Task 5의 Step 3까지 끝낸 뒤** 실행한다:

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_cli.py::TestCliPromoteAuto -q`
Expected: PASS

> 빠른 진행을 위해 Task 5를 먼저 구현해도 된다(둘은 같은 PR). 순서가 거슬리면 Task 3 → Task 5 순으로 코드를 넣고 두 테스트를 한 번에 돌린다.

- [ ] **Step 5: 커밋 (Task 5 통과 후)**

```bash
cd /Users/al03040455/Desktop/bb2_client
git add scripts/bb2_brain/cli.py scripts/bb2_brain/tests/test_cli.py
git commit -m "feat(brain): add 'cli promote-auto' batch promotion with skip-reason report + dedup + idempotency (§4.3)"
```

---

## Task 4: cli promote 수동 경로 통합 (backfill + 멱등 가드 + conflict 해소 기록)

기존 `cli promote`(사용 시점·사람 판정)에 세 가지를 더한다: 짝 매핑 근거 backfill, 이미 reviewed면 거부(멱등), conflict 용어 승격 시 해소 근거 기록.

**Files:**
- Modify: `scripts/bb2_brain/cli.py` (`_run_promote`)
- Test: `scripts/bb2_brain/tests/test_cli.py` (`TestCliPromote` 확장)

- [ ] **Step 1: 실패하는 테스트 작성 (test_cli.py `TestCliPromote` 클래스에 메서드 추가)**

`TestCliPromote` 클래스 안에 추가(상단 `_ar_evref`/`_ar_term`/`_ar_mapping` 헬퍼는 Task 3에서 이미 정의됨):

```python
    def test_promote_backfills_empty_evidence_from_mapping(self):
        # 빈 근거 candidate + 짝 reviewed 매핑 → 수동 promote가 backfill해 §6.4 통과.
        from scripts.bb2_brain.ingest import ingest
        ingest(self.root, [
            manifest(), _ar_evref("evref.a"), context(),
            _ar_term("g.empty", term="빈근거"),
            _ar_mapping("m.empty", term_ids=["g.empty"], evidence_refs=["evref.a"], mapping_key="me"),
        ])
        argv = ["promote", "--brain-root", str(self.root),
                "--ids", "g.empty", "--reviewer", "user-confirmed",
                "--reviewed-at", "2026-06-08T00:00:00Z"]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.empty")["status"], "reviewed")
        self.assertEqual(store.get("g.empty")["evidence_refs"], ["evref.a"])

    def test_promote_rejects_already_reviewed(self):
        # 멱등 가드: 같은 id 두 번 promote → 두 번째 rc=1.
        self._ingest()  # candidate g.x (term=갈고리, evidence 보유)
        base_argv = ["promote", "--brain-root", str(self.root),
                     "--ids", "g.x", "--reviewer", "user-confirmed",
                     "--reviewed-at", "2026-06-06T00:00:00Z"]
        with mock.patch("sys.argv", ["cli"] + base_argv), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + base_argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 1)
        self.assertIn("already reviewed", json.loads(out.getvalue())["error"])

    def test_promote_conflict_records_resolution(self):
        # 수동 conflict 승격(spec §5.2 사람 판정 허용) → 해소 근거가 검수 기록에 남음.
        from scripts.bb2_brain.ingest import ingest
        conflict_term = _ar_term("g.c", term="충돌", candidate_state="conflict",
                                 evidence_refs=["evref.a"])
        ingest(self.root, [manifest(), _ar_evref("evref.a"), context(), conflict_term])
        argv = ["promote", "--brain-root", str(self.root),
                "--ids", "g.c", "--reviewer", "user-confirmed",
                "--reviewed-at", "2026-06-08T00:00:00Z",
                "--conflict-resolution", "위키 정설 채택"]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.c")["status"], "reviewed")
        self.assertEqual(store.get("review.g.c")["conflict_resolution"], "위키 정설 채택")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_cli.py::TestCliPromote -q`
Expected: FAIL — backfill 미적용(§6.4 위반 rc=1) / 멱등 가드 없음(두 번째도 rc=0) / `--conflict-resolution` 미인식

- [ ] **Step 3: _run_promote 수정**

`cli.py` `_run_promote`의 argparse 블록(48~56행)에 `--conflict-resolution` 추가:

```python
    parser.add_argument("--bundle-key")
    parser.add_argument("--conflict-resolution",
                        help="수동 conflict 용어 승격 시 정설 선택 근거(검수 기록에 기록, §4.4)")
    args = parser.parse_args(argv)
```

missing-id 검사(60~64행) **아래**, `objects = [...]`(65행)을 다음으로 교체. 멱등 가드 + backfill + conflict 해소 기록을 추가한다:

```python
    missing = [i for i in args.ids if not store.has(i)]
    if missing:
        print(json.dumps({"ok": False, "error": f"unknown ids: {missing}"},
                         ensure_ascii=False, indent=2))
        return 1
    # 멱등 가드(§4.4): 이미 reviewed인 id를 다시 승격하면 review.<id> 기록을 덮어쓰는 사고 → 거부.
    already_reviewed = [i for i in args.ids if store.get(i).get("status") == "reviewed"]
    if already_reviewed:
        print(json.dumps({"ok": False, "error": f"already reviewed (idempotency guard): {already_reviewed}"},
                         ensure_ascii=False, indent=2))
        return 1
    review_extra_by_id = None
    if args.scope == "single_object":
        # backfill 공유(§4.4): 근거 빈 용어가 짝 매핑 근거를 물려받아 B 게이트(§6.4)를 통과.
        objects = [backfill_evidence(store.get(i), store) for i in args.ids]
        if args.conflict_resolution:
            review_extra_by_id = {
                i: {"conflict_resolution": args.conflict_resolution}
                for i in args.ids
                if (store.get(i).get("candidate") or {}).get("candidate_state") == "conflict"
            }
    else:
        objects = [store.get(i) for i in args.ids]
```

그 다음 `promote(...)` 호출(69~72행)에 `review_extra_by_id` 전달:

```python
    try:
        promoted, records = promote(
            objects, args.ids, args.scope,
            bundle_key=args.bundle_key, reviewer=args.reviewer, reviewed_at=args.reviewed_at,
            review_extra_by_id=review_extra_by_id,
        )
    except (ValueError, KeyError) as exc:
```

(이하 원자성 검증·save·사후 lint·출력 블록 79~95행은 그대로 둔다.)

- [ ] **Step 4: 테스트 통과 확인 (수동 + 기존 회귀)**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_cli.py -q`
Expected: PASS — 신규 3개 + 기존(`test_promote_round_trip`, `test_promote_zero_evidence_rejected`, `test_promote_requery_*`) 전부. 특히 `test_promote_zero_evidence_rejected`는 `g.noev`에 짝 매핑이 없어 backfill no-op → 여전히 rc=1로 유지.

- [ ] **Step 5: 커밋**

```bash
cd /Users/al03040455/Desktop/bb2_client
git add scripts/bb2_brain/cli.py scripts/bb2_brain/tests/test_cli.py
git commit -m "feat(brain): manual 'cli promote' backfill + idempotency guard + conflict-resolution record (§4.4)"
```

---

## Task 5: lint.py 비차단 드리프트 경고 (unpromoted_vouched_terms)

reviewed 매핑이 보증하는데 아직 candidate인 비-conflict 용어를 비차단 경고로 보고하는 함수. `lint_store`(차단 무결성)와 **분리**한다 — 차단에 넣으면 candidate를 적재하는 ingest가 깨진다.

**Files:**
- Modify: `scripts/bb2_brain/lint.py` (함수 추가, `lint_store`는 불변)
- Test: `scripts/bb2_brain/tests/test_lint.py`

- [ ] **Step 1: 실패하는 테스트 작성 (test_lint.py에 클래스 추가)**

`test_lint.py` import 블록(6~12행)을 교체:

```python
from scripts.bb2_brain.lint import lint_store, unpromoted_vouched_terms
from scripts.bb2_brain.objbase import base
from scripts.bb2_brain.store import BrainStore
from scripts.bb2_brain.tests.test_ingest import (
    candidate_term,
    evidence_ref,
    manifest,
)

T = "2026-06-04T00:00:00Z"
```

파일 끝 `if __name__ == "__main__":` 직전에 추가:

```python
def _drift_mapping(mid, *, term_ids, status="reviewed"):
    return base(
        {
            "id": mid, "kind": "DomainMapping", "status": status, "truth_role": "domain",
            "title": "매핑", "context_id": "context.neutral", "mapping_key": mid,
            "canonical_summary": "요약", "meaning": "의미", "boundary": "경계",
            "glossary_term_ids": term_ids, "decision_record_ids": [], "evidence_refs": ["evref.a"],
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


def _drift_term(tid, *, status="candidate", candidate_state="evidence_verified"):
    obj = {
        "id": tid, "kind": "GlossaryTerm", "status": status, "truth_role": "domain",
        "title": "용어", "context_id": "context.neutral", "term": "용어", "definition": "정의",
        "evidence_refs": ["evref.a"],
    }
    if status == "candidate":
        obj["candidate"] = {"candidate_state": candidate_state, "candidate_source": "spec"}
    return base(obj, tags=["neutral"], created_at=T, updated_at=T)


class TestUnpromotedVouchedTerms(unittest.TestCase):
    def test_warns_candidate_vouched_by_reviewed_mapping(self):
        store = store_of(_drift_term("g.cand"), _drift_mapping("m", term_ids=["g.cand"]))
        warnings = unpromoted_vouched_terms(store)
        self.assertEqual(len(warnings), 1)
        self.assertIn("g.cand", warnings[0])

    def test_no_warning_for_reviewed_term(self):
        store = store_of(_drift_term("g.rev", status="reviewed"),
                         _drift_mapping("m", term_ids=["g.rev"]))
        self.assertEqual(unpromoted_vouched_terms(store), [])

    def test_no_warning_for_conflict_term(self):
        store = store_of(_drift_term("g.c", candidate_state="conflict"),
                         _drift_mapping("m", term_ids=["g.c"]))
        self.assertEqual(unpromoted_vouched_terms(store), [])

    def test_no_warning_for_unreferenced_candidate(self):
        store = store_of(_drift_term("g.lonely"))
        self.assertEqual(unpromoted_vouched_terms(store), [])

    def test_lint_store_does_not_block_on_drift(self):
        # 드리프트는 lint_store(차단)에 들어가면 안 된다 — candidate 적재가 안 깨지게.
        store = store_of(_drift_term("g.cand"), _drift_mapping("m", term_ids=["g.cand"]))
        # _drift_mapping의 evref.a/context.neutral 미존재라 lint_store는 dangling을 보고하지만,
        # 드리프트 경고 자체는 lint_store 결과에 섞이지 않는다.
        self.assertFalse(any("still candidate" in p for p in lint_store(store)))
```

(`store_of`는 기존 test_lint.py 15~16행 헬퍼.)

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_lint.py -q`
Expected: FAIL — `ImportError: cannot import name 'unpromoted_vouched_terms'`

- [ ] **Step 3: lint.py에 함수 추가**

`lint.py` import 블록(5~11행)에 추가:

```python
from scripts.bb2_brain.hash_utils import sha256_text as _sha256_text
from scripts.bb2_brain.hash_utils import stable_json as _stable_json
from scripts.bb2_brain.promote import select_vouched_candidates
from scripts.bb2_brain.router import _conflicting_fact_groups
from scripts.bb2_brain.schema import validate_object
from scripts.bb2_brain.store import BrainStore
```

(import 안전: `promote`는 `objbase`만 import → 순환 없음.)

`lint_store` 함수 정의(79행) **위에** 새 함수 추가:

```python
def unpromoted_vouched_terms(store: BrainStore) -> list[str]:
    """비차단 드리프트 경고(spec §4.6): reviewed 매핑이 보증하는데 아직 candidate인 비-conflict 용어.

    lint_store(차단 무결성)와 분리한다 — candidate는 적재 직후 정상이라 차단하면 모든 ingest가
    깨진다. 자동 승격(promote-auto) + 커버리지 통과분 적재 후엔 0이어야 하며, 남는 것은
    커버리지 보류분(사람 검토 큐, §8). conflict는 selection에서 제외돼 여기 안 뜬다(별도 신호).
    """
    warnings = []
    for tid, mapping_ids in sorted(select_vouched_candidates(store).items()):
        warnings.append(
            f"{tid}: vouched by reviewed mapping {mapping_ids} but still candidate; "
            f"run promote-auto after coverage verification (non-blocking drift)"
        )
    return warnings
```

`lint_store` 본문(80~219행)은 **변경하지 않는다**(드리프트를 차단 problems에 넣지 않음).

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_lint.py -q`
Expected: PASS

- [ ] **Step 5: Task 3 promote-auto 테스트 동반 통과 확인**

`promote-auto`가 `unpromoted_vouched_terms`를 부르므로 이제 함께 통과한다:

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_cli.py::TestCliPromoteAuto scripts/bb2_brain/tests/test_lint.py -q`
Expected: PASS

- [ ] **Step 6: 전체 테스트 회귀 확인 + 커밋**

Run: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests -q`
Expected: PASS — 기존 58 + 신규 전부 그린

```bash
cd /Users/al03040455/Desktop/bb2_client
git add scripts/bb2_brain/lint.py scripts/bb2_brain/tests/test_lint.py
git commit -m "feat(brain): non-blocking drift warning unpromoted_vouched_terms, separate from lint_store (§4.6)"
```

(Task 3 promote-auto 커밋을 미뤘다면 이 시점에 함께 커밋한다.)

---

## Task 6: 실코퍼스 배치 커버리지 검증 + promote-auto 실행 (운영 — 코드 검증·승인 후)

코드가 전부 그린이 된 뒤, 실코퍼스(`scripts/bb2_brain/brain/`, git 미추적) 115개 후보를 적대검증 워크플로우로 커버리지 판정 → pass 목록을 `promote-auto`에 먹여 승격한다. **이 단계는 실데이터를 바꾸므로 사용자 승인 후 실행한다.** 판정은 에이전트(워크플로우), 적재는 cli — "판정은 에이전트, 적재는 코드"(spec §4.2b·§6.3).

- [ ] **Step 1: 1단계 후보 + 판정 재료 덤프**

각 후보 용어의 정의를, 그 용어를 보증하는 reviewed 매핑의 의미·근거와 나란히 뽑아 커버리지 판정 재료를 만든다:

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python - <<'PY'
import json
from pathlib import Path
from scripts.bb2_brain.store import BrainStore
from scripts.bb2_brain.promote import select_vouched_candidates

store = BrainStore.load(Path("scripts/bb2_brain/brain"))
sel = select_vouched_candidates(store)
rows = []
for tid, mapping_ids in sorted(sel.items()):
    term = store.get(tid)
    rows.append({
        "term_id": tid,
        "term": term.get("term"),
        "definition": term.get("definition"),
        "vouching_mappings": [
            {"id": mid, "meaning": store.get(mid).get("meaning"),
             "canonical_summary": store.get(mid).get("canonical_summary")}
            for mid in mapping_ids
        ],
    })
Path("/tmp/bb2_brain_coverage_input.json").write_text(
    json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"후보 {len(rows)}개 → /tmp/bb2_brain_coverage_input.json")
PY
```

Expected: `후보 115개 → /tmp/bb2_brain_coverage_input.json`

- [ ] **Step 2: 배치 커버리지 검증 워크플로우 실행 (에이전트 판정)**

`/tmp/bb2_brain_coverage_input.json`의 각 후보를 배치로 적대검증한다. 판정 기준 하나: **"용어의 정의가 그 용어를 보증하는 reviewed 매핑의 검증된 의미·근거 안에 들어가는가(매핑이 입증하지 않는 초과 주장이 없는가)?"** (spec §4.2b)

- 통과(커버됨) → pass.
- 불통과(매핑 의미를 초과하는 주장) → hold(사람 검토 큐), 사유 기록.

워크플로우는 `{term_id, verdict: pass|hold, reason}` 목록을 산출한다(저장 가능한 형태). 적대검증은 코드가 아니라 에이전트가 한다 — `default refuted` 성향으로 초과 주장을 잡고, 다수결로 pass/hold 결정. 이 워크플로우는 사용자가 `ultracode`/`use a workflow`로 명시 동의할 때만 `Workflow` 도구로 돌린다(아니면 후보 수가 적으면 인라인 에이전트 배치로 판정).

산출된 pass 용어 id를 모은다:

```bash
# 워크플로우 결과(pass 목록)를 공백 구분 id로 준비. 예:
PASS_IDS="g.sally-canoe.racing-main-page-lane g.sally-canoe.npc-movement-npc ..."
```

- [ ] **Step 3: promote-auto로 pass 목록 일괄 승격**

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m scripts.bb2_brain.cli promote-auto \
  --brain-root scripts/bb2_brain/brain \
  --ids $PASS_IDS \
  --reviewed-at 2026-06-08T00:00:00Z
```

Expected: `{"ok": true, "promoted": [...], "reviews": [...], "skipped": {...}, "drift_remaining": [...]}` — promoted = pass 개수, skipped.conflict 7개 미포함(애초에 pass에 없음), drift_remaining = hold(커버리지 보류)분만.

- [ ] **Step 4: 검증 — lint clean + 드리프트가 보류분만 + 테스트 그린**

```bash
cd /Users/al03040455/Desktop/bb2_client
# 1) 코퍼스 차단 lint 0
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python - <<'PY'
from pathlib import Path
from scripts.bb2_brain.store import BrainStore
from scripts.bb2_brain.lint import lint_store, unpromoted_vouched_terms
store = BrainStore.load(Path("scripts/bb2_brain/brain"))
problems = lint_store(store)
drift = unpromoted_vouched_terms(store)
print("lint problems:", len(problems))
for p in problems: print("  ", p)
print("drift_remaining (hold/보류분):", len(drift))
PY
# 2) 코드 테스트 회귀
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests -q
```

Expected: `lint problems: 0` / `drift_remaining`은 hold된 보류분 개수(전부 pass면 0) / 테스트 전부 그린.

- [ ] **Step 5: 결과 보고 + 메모리/task 갱신 (커밋 아님 — 코퍼스는 git 미추적)**

승격 N개 / conflict 제외 7개(수동 §4.4 대상) / 커버리지 보류 M개(사람 검토 큐)를 사용자에게 보고한다. `brain/` 코퍼스는 설계상 git 미추적이라 커밋하지 않는다. task 파일 Tier 3 체크박스(매핑 보증 용어 자동 승격 구현)를 완료로 갱신하고 작업 이력에 승격 수치를 기록한다.

---

## Self-Review

**1. Spec coverage** — spec 각 절을 태스크로 매핑:

| spec | 태스크 |
|------|--------|
| §4.1 backfill 공유 부품 | Task 1 (`backfill_evidence`) |
| §4.2 1단계 기계 선별 | Task 1 (`select_vouched_candidates`) |
| §4.2b 2단계 배치 커버리지 검증(에이전트, pass 목록) | Task 6 Step 2 (워크플로우 판정), cli는 pass만 기계 적재 |
| §4.3 자동 승격 명령 promote-auto | Task 3 |
| §4.4 수동 promote 통합(backfill·멱등·conflict 기록) | Task 4 |
| §4.5 검수 기록(reviewer/vouched_by_mapping_ids) + schema 주석 | Task 2(인자·주석) + Task 3(자동 배선) |
| §4.6 드리프트 lint | Task 5 |
| §4.7 구현 산출물 전부 | Task 1~5 |
| §5 데이터 흐름 | Task 6 (운영 종합) |
| §6 오류·원자성 | Task 3·4 (쓰기 전 일괄 validate + store.has 필터 + 멱등) |
| §7 테스트 항목 | 각 태스크 Step 1 |
| §8 비목표·후속(conflict 수동/보류 큐/scope_hint/IndexRecord) | 범위 밖 명시 |

빠진 spec 요구 없음.

**2. Placeholder scan** — "TBD/적절히 처리/handle edge cases" 류 없음. 모든 코드 스텝에 실제 코드 블록 포함. Task 6 Step 2의 에이전트 판정은 본질적으로 워크플로우 산출물이라 코드가 아님(spec §4.2b가 명시한 "판정은 에이전트") — 플레이스홀더가 아니라 의도된 비-코드 단계.

**3. Type consistency** — 함수명·시그니처 일관성 확인:
- `vouching_mappings(term_id, store)` / `backfill_evidence(term, store)` / `select_vouched_candidates(store) -> {term_id: [mapping_id]}` — Task 1 정의, Task 3·5에서 동일하게 호출.
- `promote(..., review_extra_by_id=None)` — Task 2 정의, Task 3(`review_extra`)·Task 4(`review_extra_by_id`)에서 동일 키워드로 전달.
- `unpromoted_vouched_terms(store)` — Task 5 정의, Task 3에서 `from scripts.bb2_brain.lint import unpromoted_vouched_terms`로 호출.
- `reviewer="auto:mapping-vouched"` — Task 3에서 하드코딩, spec §4.5와 일치.
- 검수 기록 추가 필드명 `vouched_by_mapping_ids`(자동)·`conflict_resolution`(수동) — Task 2 주석·Task 3·Task 4에서 동일.

**알려진 태스크 순서 의존**: Task 3의 `_run_promote_auto`가 Task 5의 `unpromoted_vouched_terms`를 import한다. Task 3 Step 4(통과 확인)·Step 5(커밋)는 Task 5 구현 후로 명시. subagent-driven 실행 시 Task 5를 Task 3보다 먼저 돌리거나 둘을 한 묶음으로 처리하면 깔끔하다.

---

**다음:** 이 플랜으로 구현. 실행 방식은 아래 핸드오프 참고.
