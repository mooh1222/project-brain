# stale 자동화 Step 1·2 구현 계획 (미머지 앵커 라벨 + query/show 노출)

> **상태(2026-06-25): ✅ 구현·푸시 완료(커밋 237096d·957d882).** 합성 519 통과(신규 13)·bb2 실코퍼스 검증·route architect 리뷰 CLEAR. 아래 `- [ ]` 체크박스는 작업 기록(전부 완료됨).
> 설계 근거: [2026-06-25-brain-stale-automation-bc.md](2026-06-25-brain-stale-automation-bc.md) §5·§6·§8.
> 이 문서는 그 §8 구현 순서의 **Step 1·2를 TDD 작업 단위로 분해**한다. Step 3(에이전트 트리아지 플로우)은 실코퍼스 회귀가 필요한 별개 작업이라 보류.

**Goal:** (1) stale-check이 "앵커 커밋이 develop에 아직 머지 안 됨"을 D/M 변경과 **별개 범주(`unmerged_anchors`)로 라벨**해 거짓 신호를 제거하고, (2) 그 stale-set을 `.brain-local/stale-set.json` 캐시로 떨군 뒤 query/show가 읽어 매핑별 **`stale_advisory`("코드 변경됨")**를 붙인다.

**Architecture:** stale_check.py는 git을 주입받는 순수 로직 유지. 캐시 파일 IO는 CLI 책임(색인·세션 마킹과 같은 `.brain-local` 관례). router는 파일·git을 모르고 CLI가 만들어 주입하는 `stale_advisories`(매핑id→advisory dict)만 소비 — 기존 `git_runner`/`current_head` 주입과 같은 패턴. 캐시 없으면 advisory 0건(query 동작 불변).

**Tech Stack:** Python, 표준 `subprocess`(git), `unittest`, `.venv/bin/python -m pytest`.

## Global Constraints

- 결정론: 테스트는 합성 입력 + 가짜 `git_runner`만. 실 git·네트워크·실모델 금지.
- 읽기 전용 계약: `stale-check`는 **brain 데이터(객체)** 를 안 건드린다. `--write-cache`가 쓰는 `.brain-local/stale-set.json`은 색인 DB처럼 **재생성 가능한 파생물**(gitignore 대상)이라 이 계약과 무관.
- 약식 sha 함정: 저장된 `commit_sha`는 약식(예: `b27a23e385`)일 수 있고 `git merge-base`는 전체 sha를 돌려준다 → 동등 비교 금지, **prefix 비교**.
- `now`는 코퍼스 datetime 표준(KST +09:00, microsecond 없음) — CLI는 `now_kst()` 사용.

---

## Step 1 — 미머지 앵커 구분 (`unmerged_anchors`)

### Task 1.1: `anchor_merged` + stale_check 분기

**Files:**
- Modify: `src/project_brain/stale_check.py` (새 함수 `anchor_merged`, `stale_check` 루프에 ancestry 분기 + 반환 키 `unmerged_anchors`)
- Test: `tests/test_stale_check.py` (`fake_git_runner`에 merge-base 응답 추가, 신규 테스트 2개)

**Interfaces:**
- Produces: `anchor_merged(git_runner, from_commit, target_head) -> bool` (merge-base 실패는 `GitError` 전파). `stale_check(...)` 반환 dict에 키 `"unmerged_anchors": [{locator_id, path, from_commit, reason}]` 추가. `reason ∈ {"not_ancestor", "anchor_unverifiable"}`.

- [ ] **Step 1: `fake_git_runner`에 merge-base 응답 추가**

`tests/test_stale_check.py`의 `fake_git_runner`를 확장한다(기본은 "머지됨" — 기존 테스트 보존):

```python
def fake_git_runner(target_head, changed, *, merge_base=None):
    """changed: {(from_commit, path): change_type}. merge_base: {from_commit: base_sha}.
    merge_base에 없는 from_commit은 자기 자신을 base로 반환 = 조상(머지됨)."""
    merge_base = merge_base or {}
    calls = []

    def run(args):
        calls.append(args)
        if args[:1] == ["fetch"]:
            return ""
        if args[:1] == ["rev-parse"]:
            return target_head + "\n"
        if args[:1] == ["merge-base"]:
            fc = args[1]
            return merge_base.get(fc, fc) + "\n"
        if args[:2] == ["diff", "--name-status"]:
            from_commit = args[2].split("..")[0]
            path = args[4]
            ct = changed.get((from_commit, path))
            return f"{ct}\t{path}\n" if ct else ""
        raise AssertionError(f"unexpected git args: {args}")

    run.calls = calls
    return run
```

- [ ] **Step 2: 실패 테스트 작성 (미머지 앵커는 후보 아님 + `unmerged_anchors`에)**

`StaleCheckTest`에 추가:

```python
def test_unmerged_anchor_excluded_from_candidates_and_listed(self):
    # 앵커 commit_sha=WORK가 develop 조상이 아니면(미머지) 거짓 신호 방지로 후보에서 빼고
    # unmerged_anchors에 별도 라벨. diff가 'D'를 내도 후보로 새지 않아야 한다.
    from project_brain.stale_check import stale_check
    store = _store(
        code_locator("code.work", path="a/Work.cpp", commit_sha="WORK"),
        domain_mapping("m.work", code_locator_ids=["code.work"]),
    )
    runner = fake_git_runner(
        "TARGET", {("WORK", "a/Work.cpp"): "D"}, merge_base={"WORK": "OLDBASE"})
    report = stale_check(store, git_runner=runner, target_head="TARGET")
    self.assertEqual(report["candidates"], [])          # 미머지 → 후보 아님
    self.assertEqual([u["locator_id"] for u in report["unmerged_anchors"]], ["code.work"])
    self.assertEqual(report["unmerged_anchors"][0]["reason"], "not_ancestor")

def test_abbreviated_anchor_sha_detected_as_merged(self):
    # 약식 sha 함정 회귀: commit_sha가 약식이고 merge-base가 전체 sha를 돌려줘도
    # prefix 비교로 '머지됨'으로 본다 → 정상적으로 변경 감지(후보)된다.
    from project_brain.stale_check import stale_check
    store = _store(
        code_locator("code.ab", path="a/Ab.cpp", commit_sha="b27a23e385"),
        domain_mapping("m.ab", code_locator_ids=["code.ab"]),
    )
    runner = fake_git_runner(
        "TARGET", {("b27a23e385", "a/Ab.cpp"): "M"},
        merge_base={"b27a23e385": "b27a23e38598ffcaffee0011"})  # 전체 sha
    report = stale_check(store, git_runner=runner, target_head="TARGET")
    self.assertEqual([c["mapping_id"] for c in report["candidates"]], ["m.ab"])
    self.assertEqual(report["unmerged_anchors"], [])
```

- [ ] **Step 3: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py -k "unmerged_anchor or abbreviated_anchor" -q`
Expected: FAIL — `KeyError: 'unmerged_anchors'`(아직 키 없음) / `anchor_merged` 미정의.

- [ ] **Step 4: `anchor_merged` 구현 + stale_check 분기**

`stale_check.py`에 함수 추가(`path_changed` 아래):

```python
def anchor_merged(git_runner, from_commit, target_head):
    """from_commit이 target_head(origin/develop)의 조상인가 = develop에 머지됨.

    merge-base가 from_commit(의 전체 sha)를 돌려주면 조상이다. 저장 commit_sha는
    약식일 수 있고 merge-base는 전체 sha를 내므로 prefix로 비교한다. merge-base가
    실패(커밋 미존재·무관 히스토리)하면 GitError가 전파된다 — 호출자가 미검증으로 분류.
    """
    base = git_runner(["merge-base", from_commit, target_head]).strip()
    return base.startswith(from_commit)
```

`stale_check()` 루프를 수정한다. `change_cache = {}` 다음에 `ancestor_cache = {}`, `unmerged_anchors = []` 추가. `from_commit` 확보 직후(현재 127행 `key = (path, from_commit)` 앞)에 ancestry 분기를 넣는다:

```python
        if from_commit not in ancestor_cache:
            try:
                ancestor_cache[from_commit] = anchor_merged(
                    git_runner, from_commit, target_head)
            except GitError:
                ancestor_cache[from_commit] = None  # 미존재·무관 — 검증 불가
        merged = ancestor_cache[from_commit]
        if merged is not True:
            # 미머지/검증불가 앵커: from..develop diff가 거짓 변경을 내므로 후보에서 빼고
            # 별개 범주로 라벨(차단 아님). 머지되면 다음 실행에서 자동 해소(설계 §5).
            unmerged_anchors.append({
                "locator_id": loc["id"], "path": path, "from_commit": from_commit,
                "reason": "not_ancestor" if merged is False else "anchor_unverifiable",
            })
            continue
        key = (path, from_commit)
```

반환 dict(현재 161-166행)에 키 추가:

```python
    return {
        "target_head": target_head,
        "candidates": candidates,
        "locator_group": locator_group,
        "unmerged_anchors": sorted(unmerged_anchors, key=lambda u: u["locator_id"]),
        "coverage": coverage_report(store),
    }
```

- [ ] **Step 5: 전체 stale_check 테스트 통과 확인 (기존 + 신규)**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py -q`
Expected: PASS — 기존 테스트(merge_base 기본=머지됨이라 불변) + 신규 2개.

- [ ] **Step 6: CLI가 `unmerged_anchors`를 그대로 노출하는지 테스트**

`_run_stale_check`는 `{"ok": True, **report}`를 출력하므로 키가 자동 흐른다. 회귀 가드만 추가(`CliStaleCheckTest`):

```python
def test_stale_check_surfaces_unmerged_anchors(self):
    for obj in (
        code_locator("code.work", path="a/Work.cpp", commit_sha="WORK"),
        domain_mapping("m.work", code_locator_ids=["code.work"]),
    ):
        BrainStore.save_object(self.root, obj)
    runner = fake_git_runner(
        "TARGET", {("WORK", "a/Work.cpp"): "D"}, merge_base={"WORK": "OLDBASE"})
    rc, payload = self._run(
        ["stale-check", "--brain-root", str(self.root), "--no-fetch"], runner)
    self.assertEqual(rc, 0)
    self.assertEqual(payload["candidates"], [])
    self.assertEqual([u["locator_id"] for u in payload["unmerged_anchors"]], ["code.work"])
```

Run: `.venv/bin/python -m pytest tests/test_stale_check.py -q` → PASS.

- [ ] **Step 7: 커밋**

```bash
git add src/project_brain/stale_check.py tests/test_stale_check.py
git commit -m "feat(stale-check): 미머지 앵커를 변경과 별개 범주로 라벨(거짓 신호 제거)"
```

---

## Step 2 — stale-set 캐시 + query/show advisory

### Task 2.1: 캐시 빌더·IO·advisory 매퍼 (stale_check.py)

**Files:**
- Modify: `src/project_brain/stale_check.py` (`build_stale_set`, `stale_set_path`, `write_stale_set`, `load_stale_set`, `advisories_by_mapping`)
- Test: `tests/test_stale_check.py` (신규 `StaleSetCacheTest`)

**Interfaces:**
- Produces:
  - `build_stale_set(report, *, now) -> {target_head, computed_at, stale_mapping_ids, detail}` (순수)
  - `stale_set_path(brain_root) -> Path` = `<brain_root>/.brain-local/stale-set.json`
  - `write_stale_set(brain_root, stale_set) -> Path`
  - `load_stale_set(brain_root) -> dict | None` (없으면 None)
  - `advisories_by_mapping(stale_set) -> {mapping_id: {code_changed, change_types, paths, target_head, computed_at}}`

- [ ] **Step 1: 실패 테스트 작성**

```python
class StaleSetCacheTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_build_stale_set_from_report(self):
        from project_brain.stale_check import build_stale_set
        report = {
            "target_head": "TARGET",
            "candidates": [{
                "mapping_id": "m.a", "mapping_key": "m.a",
                "stale_locators": [
                    {"locator_id": "code.x", "path": "a/X.cpp",
                     "change_type": "M", "from_commit": "SHA1"}],
            }],
        }
        ss = build_stale_set(report, now="2026-06-25T12:00:00+09:00")
        self.assertEqual(ss["target_head"], "TARGET")
        self.assertEqual(ss["computed_at"], "2026-06-25T12:00:00+09:00")
        self.assertEqual(ss["stale_mapping_ids"], ["m.a"])
        self.assertEqual(ss["detail"]["m.a"], {"change_types": ["M"], "paths": ["a/X.cpp"]})

    def test_write_then_load_roundtrip(self):
        from project_brain.stale_check import write_stale_set, load_stale_set, stale_set_path
        self.assertIsNone(load_stale_set(self.root))  # 없으면 None
        ss = {"target_head": "T", "computed_at": "t", "stale_mapping_ids": [], "detail": {}}
        path = write_stale_set(self.root, ss)
        self.assertEqual(path, stale_set_path(self.root))
        self.assertEqual(load_stale_set(self.root), ss)

    def test_advisories_by_mapping(self):
        from project_brain.stale_check import advisories_by_mapping
        ss = {"target_head": "T", "computed_at": "t2",
              "stale_mapping_ids": ["m.a"],
              "detail": {"m.a": {"change_types": ["M"], "paths": ["a/X.cpp"]}}}
        adv = advisories_by_mapping(ss)
        self.assertEqual(adv["m.a"], {
            "code_changed": True, "change_types": ["M"], "paths": ["a/X.cpp"],
            "target_head": "T", "computed_at": "t2"})

    def test_advisories_by_mapping_empty_when_no_cache(self):
        from project_brain.stale_check import advisories_by_mapping
        self.assertEqual(advisories_by_mapping(None), {})
        self.assertEqual(advisories_by_mapping({}), {})
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py -k StaleSetCache -q`
Expected: FAIL — ImportError(함수 미정의).

- [ ] **Step 3: 구현**

`stale_check.py` 상단 import에 `import json`, `from pathlib import Path` 추가(현재 `subprocess`만 있음). 파일 끝(또는 `mark_checked` 위)에 추가:

```python
def build_stale_set(report, *, now):
    """stale_check() 리포트를 query 캐시 형태로 압축한다(순수). computed_at은 주입."""
    detail = {}
    for c in report["candidates"]:
        detail[c["mapping_id"]] = {
            "change_types": sorted({sl["change_type"] for sl in c["stale_locators"]}),
            "paths": sorted({sl["path"] for sl in c["stale_locators"]}),
        }
    return {
        "target_head": report["target_head"],
        "computed_at": now,
        "stale_mapping_ids": sorted(detail),
        "detail": detail,
    }


def stale_set_path(brain_root):
    """query가 읽는 stale 캐시 경로. 색인 DB·세션 마킹과 같은 .brain-local 파생물 위치."""
    return Path(brain_root) / ".brain-local" / "stale-set.json"


def write_stale_set(brain_root, stale_set):
    path = stale_set_path(brain_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stale_set, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_stale_set(brain_root):
    """캐시 dict 또는 None(파일 없음). query/show가 advisory 부착에 쓴다."""
    path = stale_set_path(brain_root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def advisories_by_mapping(stale_set):
    """캐시를 매핑id→advisory dict로. 캐시 None/빈 dict면 {}(advisory 0건)."""
    out = {}
    for mid, d in ((stale_set or {}).get("detail") or {}).items():
        out[mid] = {
            "code_changed": True,
            "change_types": d["change_types"],
            "paths": d["paths"],
            "target_head": (stale_set or {}).get("target_head"),
            "computed_at": (stale_set or {}).get("computed_at"),
        }
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py -k StaleSetCache -q` → PASS.

### Task 2.2: `stale-check --write-cache`

**Files:**
- Modify: `src/project_brain/cli.py` (`_run_stale_check`에 `--write-cache` 플래그)
- Test: `tests/test_stale_check.py` (`CliStaleCheckTest`)

**Interfaces:**
- Consumes: Task 2.1의 `build_stale_set`, `write_stale_set`, `now_kst`(cli 기존).
- Produces: `--write-cache` 시 `.brain-local/stale-set.json` 생성 + 출력에 `"cache_written": <path>`.

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_stale_check_write_cache_persists_stale_set(self):
    from project_brain.stale_check import load_stale_set
    for obj in (
        code_locator("code.changed", path="a/Changed.cpp", commit_sha="SHA1"),
        domain_mapping("m.on_changed", code_locator_ids=["code.changed"]),
    ):
        BrainStore.save_object(self.root, obj)
    runner = fake_git_runner("TARGET", {("SHA1", "a/Changed.cpp"): "M"})
    rc, payload = self._run(
        ["stale-check", "--brain-root", str(self.root), "--no-fetch", "--write-cache"],
        runner)
    self.assertEqual(rc, 0)
    self.assertIn("cache_written", payload)
    ss = load_stale_set(self.root)
    self.assertEqual(ss["stale_mapping_ids"], ["m.on_changed"])
    self.assertEqual(ss["target_head"], "TARGET")
```

- [ ] **Step 2: 실패 확인** — `--write-cache` 미정의로 argparse 에러.

- [ ] **Step 3: 구현**

`_run_stale_check`의 parser에 추가:

```python
    parser.add_argument("--write-cache", action="store_true",
                        help="결과 stale-set을 .brain-local/stale-set.json에 떨궈 query/show가 읽게 함")
```

import 줄에 `build_stale_set, write_stale_set` 추가하고, 성공 출력 직전을 수정:

```python
    payload = {"ok": True, **report}
    if args.write_cache:
        stale_set = build_stale_set(report, now=now_kst())
        path = write_stale_set(brain_root, stale_set)
        payload["cache_written"] = str(path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
```

(`now_kst`는 cli에 이미 import됨 — mark-checked가 사용.)

- [ ] **Step 4: 통과 확인** — `pytest tests/test_stale_check.py -q` 전체 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/project_brain/stale_check.py tests/test_stale_check.py src/project_brain/cli.py
git commit -m "feat(stale-check): stale-set 캐시 빌더/IO + --write-cache 플래그"
```

### Task 2.3: router가 `stale_advisories`를 매핑에 부착

**Files:**
- Modify: `src/project_brain/router.py` (`__init__`에 `stale_advisories` 주입, `mapping_details`에 `stale_advisory` 부착 + warning)
- Test: `tests/test_router.py` (신규 테스트)

**Interfaces:**
- Consumes: CLI가 주입하는 `stale_advisories: {mapping_id: advisory_dict}`(Task 2.1 `advisories_by_mapping` 출력). 기본 None.
- Produces: glossary_meaning 섹션 `mappings[*]`에 매핑 id가 stale면 `"stale_advisory": {...}` 키 추가. stale 매핑이 답에 1개 이상이면 `warnings`에 한 줄.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_router.py` 패턴(기존 glossary_meaning 매핑 테스트)을 따른다. reviewed DomainMapping이 답에 뜨고, 그 id가 `stale_advisories`에 있으면 mapping 원소에 `stale_advisory`가 붙는지 검증:

```python
def test_stale_advisory_attached_to_mapping_when_in_stale_set(self):
    # glossary_meaning 매핑 답에 stale_advisories에 든 매핑이 있으면 stale_advisory 부착.
    store = _store_with_reviewed_mapping_matching("강화폭탄")  # 기존 헬퍼 패턴 사용
    adv = {"m.boost": {"code_changed": True, "change_types": ["M"],
                       "paths": ["a/X.cpp"], "target_head": "T", "computed_at": "t"}}
    router = QueryRouter(store, stale_advisories=adv)
    answer = router.answer("강화폭탄 무슨 뜻")
    gm = next(s for s in answer["sections"] if s["intent"] == "glossary_meaning")
    m = next(x for x in gm["mappings"] if x["id"] == "m.boost")
    self.assertEqual(m["stale_advisory"]["change_types"], ["M"])
    self.assertTrue(any("코드 변경" in w for w in answer["warnings"]))

def test_no_stale_advisory_without_cache(self):
    store = _store_with_reviewed_mapping_matching("강화폭탄")
    router = QueryRouter(store)  # stale_advisories 미주입
    answer = router.answer("강화폭탄 무슨 뜻")
    gm = next(s for s in answer["sections"] if s["intent"] == "glossary_meaning")
    self.assertNotIn("stale_advisory", gm["mappings"][0])
```

> 주의: `_store_with_reviewed_mapping_matching`는 test_router.py의 기존 매핑-적중 픽스처에 맞춘 자리표시자다. 구현 시 test_router.py에서 reviewed DomainMapping이 glossary_meaning으로 매칭되게 만드는 **기존 헬퍼/패턴을 그대로 재사용**한다(새 픽스처 빌더를 만들지 말 것 — 매핑 id만 stale_advisories 키와 일치시키면 됨).

- [ ] **Step 2: 실패 확인** — `QueryRouter(... stale_advisories=...)` TypeError(미지원 인자).

- [ ] **Step 3: 구현**

`__init__` 시그니처(33-42행)에 키워드 인자 추가하고 저장:

```python
        brain_root=None,
        stale_advisories=None,
    ):
        ...
        self.brain_root = Path(brain_root) if brain_root is not None else None
        self.stale_advisories = stale_advisories or {}
```

`mapping_details.append({...})`(271-278행)를 만든 직후, 부착:

```python
                    detail = {
                        "id": mapping["id"],
                        "mapping_key": mapping.get("mapping_key"),
                        "meaning": mapping.get("meaning", ""),
                        "boundary": mapping.get("boundary", ""),
                        "caveats": mapping.get("caveats") or [],
                        "code_locator_ids": mapping.get("code_locator_ids") or [],
                    }
                    adv = self.stale_advisories.get(mapping["id"])
                    if adv:
                        detail["stale_advisory"] = adv
                    mapping_details.append(detail)
```

`candidate_details`/glossary 섹션 append 뒤(315행 이후, 의도 루프 안)에서 warning 한 번:

```python
                if any("stale_advisory" in m for m in mapping_details):
                    warnings.append("코드 변경 감지된 매핑 포함 — stale-check 기준 시점 확인 필요")
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_router.py -q` → PASS(신규 + 기존 불변).

### Task 2.4: CLI query가 캐시를 읽어 router에 주입

**Files:**
- Modify: `src/project_brain/cli.py` (`_run_query`)
- Test: `tests/test_cli.py` (신규 — 캐시 떨군 뒤 query에 advisory 뜨는지)

**Interfaces:**
- Consumes: Task 2.1 `load_stale_set`/`advisories_by_mapping`, Task 2.3 `QueryRouter(stale_advisories=...)`.

- [ ] **Step 1: 실패 테스트 작성** (`tests/test_cli.py`)

기존 query CLI 테스트 패턴(reviewed DomainMapping 적재 → query → JSON)을 따르고, 사이에 `write_stale_set`으로 캐시를 떨군다:

```python
def test_query_surfaces_stale_advisory_from_cache(self):
    from project_brain.stale_check import write_stale_set
    # (기존 query 테스트 픽스처대로 reviewed 매핑 m.* 를 brain-root에 적재)
    # ... 적재 ...
    write_stale_set(self.root, {
        "target_head": "T", "computed_at": "t",
        "stale_mapping_ids": ["<적재한 매핑 id>"],
        "detail": {"<적재한 매핑 id>": {"change_types": ["M"], "paths": ["a/X.cpp"]}}})
    rc, payload = self._run_query(["<적중 질의>", "--brain-root", str(self.root)])
    gm = next(s for s in payload["sections"] if s["intent"] == "glossary_meaning")
    m = next(x for x in gm["mappings"] if x["id"] == "<적재한 매핑 id>")
    self.assertIn("stale_advisory", m)
```

> 자리표시자(`<...>`)는 test_cli.py의 기존 query 픽스처에 맞춰 채운다(매핑 id·질의는 기존 테스트가 쓰는 값 재사용).

- [ ] **Step 2: 실패 확인** — advisory 미부착으로 `assertIn` 실패.

- [ ] **Step 3: 구현**

`_run_query`에서 router 생성 직전에 캐시 로드, 생성 시 주입:

```python
    from project_brain.stale_check import load_stale_set, advisories_by_mapping
    stale_advisories = advisories_by_mapping(load_stale_set(brain_root))
    router = QueryRouter(
        store, current_head=args.current_head,
        db_path=Path(args.db) if args.db else None,
        embedder=embedder, brain_root=brain_root,
        stale_advisories=stale_advisories,
    )
```

- [ ] **Step 4: 통과 확인** — `pytest tests/test_cli.py -q` PASS.

### Task 2.5: show가 stale 매핑에 advisory 부착

**Files:**
- Modify: `src/project_brain/cli.py` (`_run_show`)
- Test: `tests/test_cli.py` (`_run_show` 테스트 그룹)

**Interfaces:**
- Produces: show 출력 payload에 대상 객체가 stale-set에 들면 최상위 `"stale_advisory": {...}` 키 추가(객체 본문은 불변).

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_show_attaches_stale_advisory_for_stale_mapping(self):
    from project_brain.stale_check import write_stale_set
    # m.foo(DomainMapping) 적재 + 캐시에 m.foo를 stale로
    # ... 적재 ...
    write_stale_set(self.root, {
        "target_head": "T", "computed_at": "t", "stale_mapping_ids": ["m.foo"],
        "detail": {"m.foo": {"change_types": ["M"], "paths": ["a/X.cpp"]}}})
    rc, payload = self._run_show(["m.foo", "--brain-root", str(self.root)])
    self.assertEqual(rc, 0)
    self.assertEqual(payload["stale_advisory"]["change_types"], ["M"])

def test_show_no_advisory_when_not_stale(self):
    # 캐시 없거나 대상이 stale 아니면 stale_advisory 키 없음.
    # ... m.foo 적재, 캐시 안 떨굼 ...
    rc, payload = self._run_show(["m.foo", "--brain-root", str(self.root)])
    self.assertNotIn("stale_advisory", payload)
```

- [ ] **Step 2: 실패 확인** — `stale_advisory` 키 없어 실패.

- [ ] **Step 3: 구현**

`_run_show`의 최종 출력(현재 `print(json.dumps({"ok": True, "object": obj, "neighbors": neighbors}...))`)을 수정:

```python
    from project_brain.stale_check import load_stale_set, advisories_by_mapping
    advisories = advisories_by_mapping(load_stale_set(resolve_brain_root(args.brain_root)))
    payload = {"ok": True, "object": obj, "neighbors": neighbors}
    if args.id in advisories:
        payload["stale_advisory"] = advisories[args.id]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
```

> `resolve_brain_root(args.brain_root)`는 `_run_show` 상단에서 이미 호출해 store를 만든다 — 같은 값을 재사용하도록 그 결과를 지역변수로 잡아 두 번 호출하지 않게 정리(surgical: store 만들 때 한 번만 resolve).

- [ ] **Step 4: 통과 확인** — `pytest tests/test_cli.py -q` PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/project_brain/router.py src/project_brain/cli.py tests/test_router.py tests/test_cli.py
git commit -m "feat(query/show): stale-set 캐시 기반 코드변경 advisory 부착"
```

---

## 최종 검증

- [ ] 합성 전체: `.venv/bin/python -m pytest tests/ -q` → 전부 PASS.
- [ ] **실코퍼스 회귀(router·검색 경로 변경이라 필수, CLAUDE.md)**: 데이터 레포에서
  `python3 -m unittest discover -s brain/checks -p "test_*.py"` + 캐시 떨군 뒤 query 1회 수동 확인.
  (실모델·실 git 필요 — 엔진 레포에선 못 함. 사용자가 데이터 레포에서 실행하거나 위임.)
- [ ] 문서: README "주요 명령"의 `stale-check`에 `--write-cache` 한 줄 + 설계 §8 Step 1·2 완료 반영(ROADMAP). ← 구현 green 후.

## 비목표(이 계획에서 안 함)

- Step 3(에이전트 트리아지 자동 정리 플로우) — 실코퍼스 회귀 필요, 별개.
- 캐시 신선도 가드(corpus_fingerprint 재사용해 "코퍼스 변경 후 캐시 낡음" 감지) — v1은 `computed_at`/`target_head` 노출로 사람이 판단. 필요해지면 추가.
- 자동 hook(develop pull 시 자동 캐시 갱신) — 수동 `stale-check --write-cache`로 충분.
