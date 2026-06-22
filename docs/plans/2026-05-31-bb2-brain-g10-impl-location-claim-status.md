# BB2 Brain G10 — implementation_location claim_status 통일 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `implementation_location` 분기가 status를 하드코딩하는 대신 `claim_status()`를 경유하게 해 CodeLocator도 raw-unavailable/restricted를 산출하고, commit_sha 드리프트 시 §8 precedence로 최소 candidate를 보장한다.

**Architecture:** 다른 5개 intent(current/as_of/why/glossary/evidence)는 전부 `claim_status(obj, raw_available=..., restricted=...)`를 경유하는데 impl_location만 누락. base status를 claim_status로 산출 후, 드리프트(commit_sha 없음 OR HEAD 불일치) 시 `answer_status([base, "candidate"])` max-severity 합성으로 candidate 이상을 보장하되 더 severe한 restricted/raw-unavailable는 유지. import 추가 없음(`claim_status`/`answer_status` 둘 다 `router.py:4` 기존).

**Tech Stack:** Python, unittest. `scripts/bb2_brain/`.

**근거:** spec query-routing §6.4(impl location read order/rules — "code not verified → candidate", "commit_sha missing → must warn"), §8(status precedence `restricted > raw-unavailable > candidate > raw-only > reviewed` = `status.py` SEVERITY). 비자명 분기(드리프트 candidate vs claim_status 결과 충돌)는 §8 precedence가 결정 → `answer_status` max-severity 재사용.

---

### Task 1: implementation_location을 claim_status 경유로 통일

**Files:**
- Modify: `scripts/bb2_brain/router.py:89-102` (implementation_location 분기)
- Test: `scripts/bb2_brain/tests/test_router.py` (신규 테스트 3건 append)

**기존 테스트(회귀 가드, 유지)**: `test_code_locator_without_current_head_verification_is_candidate`(HEAD 불일치→candidate), `test_code_locator_without_commit_sha_warns_line_drift`(commit_sha 없음→candidate), `test_stage_clear_token_acceptance_answer`(current_head=None + commit_sha 있음 → 드리프트 미발동 → reviewed 유지).

- [ ] **Step 1: 실패 테스트 3건 작성**

`test_router.py` 끝에 append:

```python
    def test_code_locator_with_restricted_evidence_is_restricted(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/code/locator.json", {
            "id": "locator.restricted",
            "kind": "CodeLocator",
            "status": "reviewed",
            "truth_role": "reference",
            "path": "LineBubble2/Classes/main/popup_enter/OriginalPopupEnter.cpp",
            "symbol": "OriginalPopupEnter::drawEventCluster",
            "commit_sha": "HEAD_NOW",
            "evidence_refs": ["ref.code"],
        })
        write_object(root, "objects/evidence_refs/ref_code.json", {
            "id": "ref.code",
            "kind": "EvidenceRef",
            "status": "reviewed",
            "truth_role": "reference",
            "summary": "Code locator reference",
            "evidence_manifest_id": "manifest.restricted",
            "evidence_refs": [],
        })
        write_object(root, "objects/raw/manifest_restricted.json", {
            "id": "manifest.restricted",
            "kind": "EvidenceManifest",
            "status": "reviewed",
            "truth_role": "source",
            "redaction_status": "pending",
            "evidence_refs": [],
        })
        router = QueryRouter(BrainStore.load(root), current_head="HEAD_NOW")
        answer = router.answer("drawEventCluster 어디 구현돼 있어?")
        self.assertEqual(answer["intents"], ["implementation_location"])
        self.assertEqual(answer["status"], "restricted")

    def test_code_locator_missing_raw_bundle_is_raw_unavailable(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/code/locator.json", {
            "id": "locator.raw-unavailable",
            "kind": "CodeLocator",
            "status": "reviewed",
            "truth_role": "reference",
            "path": "LineBubble2/Classes/main/popup_enter/OriginalPopupEnter.cpp",
            "symbol": "OriginalPopupEnter::drawEventCluster",
            "commit_sha": "HEAD_NOW",
            "evidence_refs": ["ref.code"],
        })
        write_object(root, "objects/evidence_refs/ref_code.json", {
            "id": "ref.code",
            "kind": "EvidenceRef",
            "status": "reviewed",
            "truth_role": "reference",
            "summary": "Code locator reference",
            "evidence_manifest_id": "manifest.code",
            "evidence_refs": [],
        })
        write_object(root, "objects/raw/manifest_code.json", {
            "id": "manifest.code",
            "kind": "EvidenceManifest",
            "status": "reviewed",
            "truth_role": "source",
            "redaction_status": "approved",
            "evidence_refs": [],
        })
        router = QueryRouter(
            BrainStore.load(root),
            current_head="HEAD_NOW",
            missing_raw_manifest_ids={"manifest.code"},
        )
        answer = router.answer("drawEventCluster 어디 구현돼 있어?")
        self.assertEqual(answer["intents"], ["implementation_location"])
        self.assertEqual(answer["status"], "raw-unavailable")

    def test_code_locator_drift_does_not_mask_restricted_status(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/code/locator.json", {
            "id": "locator.restricted-no-sha",
            "kind": "CodeLocator",
            "status": "reviewed",
            "truth_role": "reference",
            "path": "LineBubble2/Classes/main/popup_enter/OriginalPopupEnter.cpp",
            "symbol": "OriginalPopupEnter::drawEventCluster",
            "evidence_refs": ["ref.code"],
        })
        write_object(root, "objects/evidence_refs/ref_code.json", {
            "id": "ref.code",
            "kind": "EvidenceRef",
            "status": "reviewed",
            "truth_role": "reference",
            "summary": "Code locator reference",
            "evidence_manifest_id": "manifest.restricted",
            "evidence_refs": [],
        })
        write_object(root, "objects/raw/manifest_restricted.json", {
            "id": "manifest.restricted",
            "kind": "EvidenceManifest",
            "status": "reviewed",
            "truth_role": "source",
            "redaction_status": "pending",
            "evidence_refs": [],
        })
        router = QueryRouter(BrainStore.load(root))
        answer = router.answer("drawEventCluster 어디 구현돼 있어?")
        self.assertEqual(answer["status"], "restricted")
        self.assertTrue(any("드리프트" in w for w in answer["warnings"]))
```

테스트 의도:
- A(restricted): 드리프트 없는 locator(commit_sha=HEAD 일치)인데 evidence manifest `redaction_status=pending` → restricted. claim_status restricted 경로 도달 증명. **하드코딩 시절엔 reviewed**(else 분기)라 실패.
- B(raw-unavailable): 드리프트 없음 + reviewed + manifest가 `missing_raw_manifest_ids` → raw-unavailable. claim_status raw-unavailable 경로 도달 증명. **하드코딩 시절엔 reviewed**라 실패.
- C(드리프트+restricted): commit_sha 없음(드리프트) + restricted manifest → restricted(NOT candidate). `answer_status([restricted, candidate])=restricted` max-severity 합성 + §8 precedence 증명. **하드코딩 시절엔 candidate**라 실패. 드리프트 경고 동시 유지(§6.4 must warn).

- [ ] **Step 2: 실패 확인**

Run:
```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router -v 2>&1 | rg "restricted|raw_unavailable|drift_does_not_mask|FAIL|OK"
```
Expected: 3 신규 테스트 FAIL — A는 `'reviewed' != 'restricted'`, B는 `'reviewed' != 'raw-unavailable'`, C는 `'candidate' != 'restricted'`.

- [ ] **Step 3: impl_location 분기 구현**

`router.py:89-102` 분기를 아래로 교체:

```python
            elif intent == "implementation_location":
                locators = self._reviewed_by_kind("CodeLocator")
                for locator in locators:
                    source_ids.append(locator["id"])
                    status = claim_status(
                        locator,
                        raw_available=self._raw_available_for(locator),
                        restricted=self._restricted_for(locator),
                    )
                    commit_sha = locator.get("commit_sha")
                    if commit_sha is None:
                        status = answer_status([status, "candidate"])
                        warnings.append(f"{locator['id']}: commit_sha 없음, 라인 번호 드리프트 가능")
                    elif self.current_head is not None and commit_sha != self.current_head:
                        status = answer_status([status, "candidate"])
                        warnings.append(f"{locator['id']}: locator commit {commit_sha}가 현재 HEAD와 달라 현재 라인 정확도 미검증")
                    claim_statuses.append(status)
                sections.append({"intent": intent, "object_ids": [locator["id"] for locator in locators], "summary": "Code locators"})
```

변경 핵심: base status를 `claim_status()`로 산출(다른 intent와 동일). 드리프트 2갈래는 하드코딩 `"candidate"` append 대신 `answer_status([status, "candidate"])`로 candidate 합성(이미 더 severe한 restricted/raw-unavailable는 유지). 경고는 그대로.

- [ ] **Step 4: impl_location 테스트 통과 확인**

Run:
```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router -v 2>&1 | rg "locator|drift|FAIL|OK|Ran"
```
Expected: 신규 3건 + 기존 code_locator 테스트(without_current_head→candidate, without_commit_sha→candidate, acceptance→reviewed) 전부 PASS.

- [ ] **Step 5: 전체 스위트 회귀 확인**

Run:
```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store
```
Expected: `OK`, 49 tests(46 + 신규 3).

- [ ] **Step 6: 커밋**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py docs/superpowers/plans/2026-05-31-bb2-brain-g10-impl-location-claim-status.md
git commit -m "feat: route impl_location CodeLocator through claim_status (G10 §6.4/§8)"
```

---

## Self-Review

**Spec coverage:** §6.4 "code not verified → candidate"(드리프트 candidate 합성), "commit_sha missing → must warn"(경고 유지), §8 precedence(`answer_status` max-severity) — Task 1이 전부 구현. §6.4 read order 2~5(related fact/EvidenceRef/CommitRef/IndexRecord)는 evidence 소스 확장(④, 다음 게이트)·IndexRecord(⑧) 범위라 G10 스코프 밖.

**Placeholder scan:** 없음. 모든 코드/명령 실체 포함.

**Type consistency:** `claim_status(obj, *, raw_available, restricted)`/`answer_status(list)` — `status.py` 시그니처 일치. `_raw_available_for`/`_restricted_for` 기존 헬퍼(evidence_provenance에서 사용 중) 재사용. `current_head`/`missing_raw_manifest_ids`는 `QueryRouter.__init__` 기존 파라미터.
