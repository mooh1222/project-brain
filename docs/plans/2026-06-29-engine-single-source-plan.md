# 엔진 단일 관리 주체 구현 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** installer를 SKILL.md 한 장 주입에서 스킬 디렉토리(references/scripts 포함) 통째 walk 주입으로 키워, 엔진(project-brain)이 brain 스킬의 단일 관리 주체가 되게 한다.

**Architecture:** 엔진 `templates/<skill>/`를 소스로 두고 install이 `.agents/skills/<project>-brain-<suffix>/`로 walk·렌더·주입한다. 도메인 예시는 그대로 두고 이름/경로 변수만 치환(`{{PROJECT}}`·`{{BRAIN_ROOT}}`·`{{DEFAULT_BRANCH}}`·`{{REPO}}`). manifest 채택(adopt)으로 bb2 기존 파일을 도구 소유로 전환한다. 설계 근거: [spec](2026-06-29-engine-single-source-spec.md).

**Tech Stack:** Python 3 + stdlib(json/hashlib/pathlib)만. 테스트는 unittest(`tests/test_installer.py`). 두 레포에 걸침 — **엔진**(project-brain: Phase A 코드) / **데이터**(bb2_client: Phase B 역수입·삭제·회귀).

## Global Constraints

- **결정론**: 합성 테스트만. 이 작업은 임베더 무관(installer 코드). `tests/`에 실모델·실코퍼스 금지 — 합성 픽스처 디렉토리로 walk 검증.
- **경로**: 하드코딩 금지. 경로는 config(`.project-brain.json`) 해석(`src/project_brain/config.py`). 명시 인자 > config > ConfigError.
- **2-레포**: 엔진 코드 변경은 project-brain 레포에서만. bb2 역수입·삭제·회귀는 bb2_client 레포에서. 한 task는 한 레포 안에서 끝난다.
- **편집 설치**: 글로벌 `project-brain`은 이 클론의 편집 설치 → 코드 고치면 즉시 반영. `pyproject` 의존성이 바뀌면 `uv tool install -e . --with mecab-python3 --force`(이 plan은 의존성 안 바꿈).
- **TDD**: red 테스트 먼저, 그다음 구현. Phase A에 적용. Phase B(데이터)는 검증 게이트(spec §6)로 대체.
- **커밋**: plan에 커밋 스텝이 있으나, 실제 커밋·푸시는 사용자 승인 후. 기본 브랜치에서 작업하면 먼저 브랜치를 판다.
- **manifest 키**: 항상 target 기준 상대 경로(머신 이식성). 절대 경로 금지.
- **빈 변수 기본값 + 백스톱(critic F4)**: `install`의 `repo`·`default_branch` 기본값은 `""`(변수 미사용 프로젝트 허용). 변수를 쓰는 프로젝트(bb2)가 config에 값을 안 채우면 `{{REPO}}`→`""`로 빈 스킬이 조용히 생길 수 있다. **방어는 Task 7 Step 2**: bb2 config에 `repo`·`default_branch`를 먼저 채우고(필수), install report의 `skipped`에 brain 스킬 파일이 있으면 문제 신호로 멈춘다. (§6.3 diff는 이 케이스를 **못 잡는다** — 최초 채택 때 렌더 `""`≠디스크라 그 파일이 skip되고 install이 디스크를 안 써 diff=0이 되기 때문. 그래서 백스톱은 diff가 아니라 config 사전보강 + skip 신호다.) install에 토큰-존재-시-ConfigError 가드를 안 박는 이유: 합성 테스트가 실 templates를 쓰므로 모든 테스트에 두 값을 줘야 해 복잡도만 는다.

---

# Phase A — 엔진 코드 (project-brain 레포, TDD)

## Task 1: installer를 디렉토리 walk 주입으로 전환 (레이아웃 `.agents/skills`)

현재 `install()`은 스킬당 `SKILL.md` 한 장만 `.claude/skills/`에 렌더한다. 이를 `templates/<skill>/`
디렉토리를 통째 walk해 `.agents/skills/`로 렌더·주입하도록 바꾼다. 이 task는 변수 확장(Task 2)·
force/채택(Task 3) 전의 **walk 인프라 + 레이아웃 전환**만 다룬다.

**Files:**
- Move(git mv): `src/project_brain/templates/query.md` → `src/project_brain/templates/query/SKILL.md` (4종: query·ingest·session-ingest·audit)
- Modify: `src/project_brain/installer.py` (전체 재작성)
- Modify: `tests/test_installer.py`

**Interfaces:**
- Produces:
  - `_SKILLS: dict[str, str]` — 스킬 키 → 디렉토리 접미(`"query": "brain-query"` …)
  - `render_text(text: str, *, project: str, brain_root: str) -> str` — 텍스트 치환(Task 2에서 인자 확장)
  - `install(target, *, project: str, brain_root: str = "brain") -> dict` — 반환 `{config, created, updated, skipped}`. 스킬 디렉토리 전체를 `.agents/skills/<project>-<suffix>/`로 주입. manifest 키는 파일별 상대 경로.
  - 제외 필터 `_excluded(rel: Path) -> bool` — `__pycache__`·`fixtures` 디렉토리·`*.pyc`·`test_*.py` 미주입.

- [ ] **Step 1: 템플릿 디렉토리 재배치**

```bash
cd src/project_brain/templates
for s in query ingest session-ingest audit; do
  mkdir -p "$s"
  git mv "$s.md" "$s/SKILL.md"
done
ls -R .   # query/SKILL.md … audit/SKILL.md + CHANGELOG.md(그대로)
```

`CHANGELOG.md`는 스킬이 아니므로 그대로 둔다(`_SKILLS`에 없음 → walk 대상 아님).

- [ ] **Step 2: 합성 walk 테스트를 먼저 쓴다 (실패하도록)**

`tests/test_installer.py`의 `InstallTest`를 `.agents` 레이아웃 + walk 검증으로 교체하고, 새 테스트를 추가한다. `_skill()` helper의 경로를 `.claude`→`.agents`로 바꾼다.

```python
    def _skill_dir(self, name):
        return self.target / ".agents" / "skills" / name

    def _skill(self, name):
        return self._skill_dir(name) / "SKILL.md"

    def test_walk_injects_references_and_scripts(self):
        # 합성 템플릿: query 스킬에 references/scripts와 제외 대상까지 둔다.
        import project_brain.installer as inst
        tdir = Path(self._td.name) / "fake_templates"
        q = tdir / "query"
        (q / "references").mkdir(parents=True)
        (q / "scripts" / "fixtures").mkdir(parents=True)
        (q / "scripts" / "__pycache__").mkdir(parents=True)
        (q / "SKILL.md").write_text("name: {{PROJECT}}-brain-query\n", encoding="utf-8")
        (q / "references" / "guide.md").write_text("see {{PROJECT}}\n", encoding="utf-8")
        (q / "scripts" / "run.sh").write_text("echo {{PROJECT}}\n", encoding="utf-8")
        (q / "scripts" / "test_run.py").write_text("# dev test\n", encoding="utf-8")
        (q / "scripts" / "fixtures" / "data.py").write_text("X = 1\n", encoding="utf-8")
        (q / "scripts" / "__pycache__" / "x.pyc").write_text("junk\n", encoding="utf-8")
        orig_dir, orig_skills = inst._TEMPLATES_DIR, inst._SKILLS
        inst._TEMPLATES_DIR, inst._SKILLS = tdir, {"query": "brain-query"}
        try:
            install(self.target, project="demo")
        finally:
            inst._TEMPLATES_DIR, inst._SKILLS = orig_dir, orig_skills
        base = self._skill_dir("demo-brain-query")
        self.assertEqual((base / "SKILL.md").read_text(encoding="utf-8"),
                         "name: demo-brain-query\n")
        self.assertEqual((base / "references" / "guide.md").read_text(encoding="utf-8"),
                         "see demo\n")
        self.assertEqual((base / "scripts" / "run.sh").read_text(encoding="utf-8"),
                         "echo demo\n")
        # 제외: test_*.py · fixtures/ · __pycache__
        self.assertFalse((base / "scripts" / "test_run.py").exists())
        self.assertFalse((base / "scripts" / "fixtures").exists())
        self.assertFalse((base / "scripts" / "__pycache__").exists())
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_installer.py::InstallTest::test_walk_injects_references_and_scripts -v`
Expected: FAIL (현재 install은 `.claude`에 SKILL.md만, `_TEMPLATES_DIR`/`_SKILLS` 속성 없음)

- [ ] **Step 4: installer.py를 walk 버전으로 재작성**

```python
"""install — 프로젝트에 config + 스킬을 멱등 설치하고 manifest로 추적한다.

산출물:
  1. .project-brain.json — 없으면 생성, 있으면 보존.
  2. .agents/skills/<project>-brain-{query,ingest,session-ingest,audit}/...
     — templates/<skill>/ 디렉토리를 통째 walk·렌더 주입(SKILL.md + references/ + scripts/).
  3. .project-brain-manifest.json — 심은 파일 경로+sha256.

파일 단위 보존(hwi_PKM 멱등): 디스크 해시가 manifest 기록과 일치할 때만 갱신(도구 소유),
불일치(사용자 수정)·manifest 밖(사용자 소유)은 보존. (--force·채택은 Task 3에서 추가.)
스킬 런타임에 안 쓰이는 개발 자산(test_*.py)·죽은 산출물(fixtures/)·생성물(__pycache__/.pyc)은
주입하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from project_brain.config import CONFIG_FILENAME

MANIFEST_FILENAME = ".project-brain-manifest.json"
_TEMPLATES_DIR = Path(__file__).parent / "templates"

# 스킬 키 → 디렉토리 접미. templates/<key>/ 가 소스.
_SKILLS = {
    "query": "brain-query",
    "ingest": "brain-ingest",
    "session-ingest": "brain-session-ingest",
    "audit": "brain-audit",
}

_TEXT_SUFFIXES = {".md", ".py", ".js", ".sh", ".json"}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_text(text: str, *, project: str, brain_root: str) -> str:
    """텍스트의 치환 변수를 채운다. {{VAR}} 토큰이라 순서 무관."""
    return text.replace("{{BRAIN_ROOT}}", brain_root).replace("{{PROJECT}}", project)


def _excluded(rel: Path) -> bool:
    """install 미주입: 개발 자산·죽은 산출물·생성물."""
    parts = set(rel.parts)
    if "__pycache__" in parts or "fixtures" in parts:
        return True
    if rel.suffix == ".pyc":
        return True
    if rel.name.startswith("test_") and rel.suffix == ".py":
        return True
    return False


def _rendered_bytes(src: Path, *, project: str, brain_root: str) -> bytes:
    """텍스트면 렌더 후 utf-8 바이트, 아니면 원본 바이트(바이너리 복사)."""
    if src.suffix in _TEXT_SUFFIXES:
        text = render_text(src.read_text(encoding="utf-8"),
                           project=project, brain_root=brain_root)
        return text.encode("utf-8")
    return src.read_bytes()


def install(target, *, project: str, brain_root: str = "brain") -> dict:
    """target 프로젝트 루트에 설치. 반환: {config, created, updated, skipped}."""
    target = Path(target)
    report = {"config": "kept", "created": [], "updated": [], "skipped": []}

    # 1. config — 있으면 보존(스킬 렌더는 config를 따른다), 없으면 생성.
    cfg_path = target / CONFIG_FILENAME
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        project = cfg.get("project") or project
        brain_root = cfg.get("brain_root", brain_root)
    else:
        cfg_path.write_text(
            json.dumps({"project": project, "brain_root": brain_root},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        report["config"] = "created"

    # 2. manifest 로드
    manifest_path = target / MANIFEST_FILENAME
    manifest = {"files": {}}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # 3. 스킬 디렉토리 walk 주입(파일 단위 보존)
    for skill, suffix in _SKILLS.items():
        src_root = _TEMPLATES_DIR / skill
        if not src_root.is_dir():
            continue
        skill_dir_name = f"{project}-{suffix}"
        for src in sorted(src_root.rglob("*")):
            if not src.is_file():
                continue
            rel = src.relative_to(src_root)
            if _excluded(rel):
                continue
            rel_key = str(Path(".agents") / "skills" / skill_dir_name / rel)
            dst = target / rel_key
            rendered = _rendered_bytes(src, project=project, brain_root=brain_root)
            rendered_hash = _sha256_bytes(rendered)
            recorded = manifest["files"].get(rel_key)
            if dst.exists():
                on_disk = _sha256_bytes(dst.read_bytes())
                if recorded != on_disk:
                    # 사용자 수정 또는 manifest 밖 — 보존. (채택은 Task 3)
                    report["skipped"].append(str(dst))
                    continue
                dst.write_bytes(rendered)
                report["updated"].append(str(dst))
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(rendered)
                report["created"].append(str(dst))
            manifest["files"][rel_key] = rendered_hash

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
```

- [ ] **Step 5: 기존 RenderTemplateTest를 새 시그니처로 교체**

`render_template(name, ...)`가 사라졌으므로(`render_text(text, ...)`로 대체) import와 테스트를 고친다.

```python
from project_brain.installer import MANIFEST_FILENAME, install, render_text


class RenderTextTest(unittest.TestCase):
    def test_substitutes_project_and_brain_root(self):
        out = render_text("name: {{PROJECT}}-brain-query → {{BRAIN_ROOT}}/x",
                          project="demo", brain_root="knowledge")
        self.assertEqual(out, "name: demo-brain-query → knowledge/x")
        self.assertNotIn("{{PROJECT}}", out)
        self.assertNotIn("{{BRAIN_ROOT}}", out)
```

기존 `InstallTest`의 나머지 테스트는 `_skill()`이 `.agents`를 보도록 바뀐 helper로 통과한다. 단
`test_fresh_install_creates_config_skills_manifest`의 `len(...)==4` 고정 단언은 Phase B 역수입으로
파일이 늘면 깨진다(critic F2). **지금 동적 카운트로 바꿔** Phase B 후에도 안 깨지게 한다.

`InstallTest`에 헬퍼 추가:
```python
    def _expected_count(self):
        import project_brain.installer as inst
        n = 0
        for skill in inst._SKILLS:
            root = inst._TEMPLATES_DIR / skill
            if not root.is_dir():
                continue
            for src in root.rglob("*"):
                if src.is_file() and not inst._excluded(src.relative_to(root)):
                    n += 1
        return n
```
그리고 `test_fresh_install_creates_config_skills_manifest`의 두 카운트 단언을 교체:
```python
        self.assertEqual(len(manifest["files"]), self._expected_count())
        # … (report["config"] 단언 그대로) …
        self.assertEqual(len(report["created"]), self._expected_count())
```
(Task 1 시점엔 SKILL.md 4개라 4, Phase B 역수입 후엔 늘어난 수 — 양쪽 다 맞는다.)

- [ ] **Step 6: 전체 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_installer.py -v`
Expected: PASS (walk·제외·레이아웃·기존 보존 전부)

- [ ] **Step 7: 커밋**

```bash
git add src/project_brain/templates src/project_brain/installer.py tests/test_installer.py
git commit -m "feat(installer): 디렉토리 walk 주입 + .agents/skills 레이아웃 + 제외 필터"
```

---

## Task 2: 치환 변수 확장 (`{{DEFAULT_BRANCH}}`·`{{REPO}}`) + config

역수입할 bb2 스킬은 `develop`(DEFAULT_BRANCH)·`bb2_client`(REPO)를 변수로 갖는다. install이 config에서
읽어 채우게 한다.

**Files:**
- Modify: `src/project_brain/installer.py`
- Modify: `tests/test_installer.py`

**Interfaces:**
- Produces: `render_text(text, *, project, brain_root, default_branch="", repo="") -> str`; `install(target, *, project, brain_root="brain", default_branch="", repo="") -> dict` — config에 `default_branch`·`repo` 키 읽기/생성.

- [ ] **Step 1: 변수 치환 테스트 추가(실패)**

```python
    def test_render_text_substitutes_branch_and_repo(self):
        out = render_text("{{REPO}}@{{DEFAULT_BRANCH}} for {{PROJECT}}",
                          project="demo", brain_root="brain",
                          default_branch="main", repo="myrepo")
        self.assertEqual(out, "myrepo@main for demo")

    def test_install_writes_new_config_keys(self):
        install(self.target, project="demo", default_branch="main", repo="myrepo")
        cfg = json.loads((self.target / CONFIG_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(cfg["default_branch"], "main")
        self.assertEqual(cfg["repo"], "myrepo")
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_installer.py::InstallTest::test_install_writes_new_config_keys -v`
Expected: FAIL (render_text가 default_branch/repo 인자 없음, config에 키 없음)

- [ ] **Step 3: render_text·_rendered_bytes·install 확장**

`render_text`:
```python
def render_text(text: str, *, project: str, brain_root: str,
                default_branch: str = "", repo: str = "") -> str:
    """텍스트의 치환 변수를 채운다. {{VAR}} 토큰이라 순서 무관."""
    return (text.replace("{{REPO}}", repo)
                .replace("{{DEFAULT_BRANCH}}", default_branch)
                .replace("{{BRAIN_ROOT}}", brain_root)
                .replace("{{PROJECT}}", project))
```

`_rendered_bytes` 시그니처에 `default_branch`·`repo` 추가하고 `render_text`에 전달:
```python
def _rendered_bytes(src: Path, *, project: str, brain_root: str,
                    default_branch: str, repo: str) -> bytes:
    if src.suffix in _TEXT_SUFFIXES:
        text = render_text(src.read_text(encoding="utf-8"), project=project,
                           brain_root=brain_root, default_branch=default_branch, repo=repo)
        return text.encode("utf-8")
    return src.read_bytes()
```

`install` 시그니처·config·호출 갱신:
```python
def install(target, *, project: str, brain_root: str = "brain",
            default_branch: str = "", repo: str = "") -> dict:
```
config 분기에서 읽기/생성:
```python
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        project = cfg.get("project") or project
        brain_root = cfg.get("brain_root", brain_root)
        default_branch = cfg.get("default_branch", default_branch)
        repo = cfg.get("repo", repo)
    else:
        cfg_path.write_text(
            json.dumps({"project": project, "brain_root": brain_root,
                        "default_branch": default_branch, "repo": repo},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        report["config"] = "created"
```
walk 루프의 `_rendered_bytes` 호출에 인자 전달:
```python
            rendered = _rendered_bytes(src, project=project, brain_root=brain_root,
                                       default_branch=default_branch, repo=repo)
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_installer.py -v`
Expected: PASS

- [ ] **Step 5: cli install에 옵션 노출**

`src/project_brain/cli.py` `_run_install`(537~)에 인자 추가:
```python
    parser.add_argument("--default-branch", default="", help="스킬 템플릿의 {{DEFAULT_BRANCH}} 값")
    parser.add_argument("--repo", default="", help="스킬 템플릿의 {{REPO}} 값")
```
```python
    report = install(target, project=project, brain_root=args.brain_root,
                     default_branch=args.default_branch, repo=args.repo)
```

- [ ] **Step 6: 커밋**

```bash
git add src/project_brain/installer.py src/project_brain/cli.py tests/test_installer.py
git commit -m "feat(installer): {{DEFAULT_BRANCH}}·{{REPO}} 변수 + config 키"
```

---

## Task 3: `--force` + manifest 채택(adopt)

엔진이 소스이므로 (a) manifest 기록 파일의 사용자 수정을 `--force`로 덮고, (b) 디스크 내용이 렌더와
같으면 manifest에 **채택**(도구 소유 전환)해야 한다. 채택이 "manifest 채우기"의 정체다(spec §3.4).

**Files:**
- Modify: `src/project_brain/installer.py`
- Modify: `src/project_brain/cli.py`
- Modify: `tests/test_installer.py`

**Interfaces:**
- Produces: `install(..., force: bool = False) -> {config, created, updated, adopted, skipped}` (`adopted` 키 신설). 채택: 디스크==렌더면 등록(안 씀). force: manifest 기록 파일의 불일치도 덮음; manifest 밖은 force여도 보존.

- [ ] **Step 1: 채택·force 테스트 추가(실패)**

```python
    def test_adopts_matching_disk_file_into_manifest(self):
        # manifest 밖 파일이 렌더 결과와 내용이 같으면 채택(도구 소유 등록).
        install(self.target, project="demo")  # 1회 설치로 파일·manifest 생성
        # manifest를 비워 "사용자 소유"로 되돌린 뒤 재설치 → 내용 같으니 채택
        (self.target / MANIFEST_FILENAME).write_text('{"files": {}}', encoding="utf-8")
        report = install(self.target, project="demo")
        self.assertTrue(report["adopted"])
        self.assertEqual(report["skipped"], [])
        manifest = json.loads((self.target / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        self.assertTrue(len(manifest["files"]) >= 4)

    def test_force_overwrites_manifest_tracked_user_edit(self):
        install(self.target, project="demo")
        skill = self._skill("demo-brain-query")
        skill.write_text("사용자 수정본", encoding="utf-8")  # manifest 기록 있음 + 수정
        report = install(self.target, project="demo", force=True)
        self.assertIn("name: demo-brain-query", skill.read_text(encoding="utf-8"))
        self.assertIn(str(skill), report["updated"])

    def test_force_preserves_manifest_outside_file(self):
        # manifest 밖(사용자 소유) 파일은 force여도 보존.
        skill = self._skill("demo-brain-query")
        skill.parent.mkdir(parents=True)
        skill.write_text("기존 사용자 스킬", encoding="utf-8")
        report = install(self.target, project="demo", force=True)
        self.assertEqual(skill.read_text(encoding="utf-8"), "기존 사용자 스킬")
        self.assertIn(str(skill), report["skipped"])
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_installer.py::InstallTest::test_adopts_matching_disk_file_into_manifest -v`
Expected: FAIL (install에 force 인자·adopted 키 없음, 채택 로직 없음)

- [ ] **Step 3: install에 force·채택 분기 추가**

`report` 초기화에 `adopted` 추가:
```python
    report = {"config": "kept", "created": [], "updated": [],
              "adopted": [], "skipped": []}
```
`install` 시그니처에 `force`:
```python
def install(target, *, project: str, brain_root: str = "brain",
            default_branch: str = "", repo: str = "", force: bool = False) -> dict:
```
walk 루프의 `if dst.exists():` 분기를 아래로 교체:
```python
            if dst.exists():
                on_disk = _sha256_bytes(dst.read_bytes())
                if on_disk == rendered_hash:
                    # 내용 동일 → 채택(manifest 밖이었으면)·유지. 안 씀.
                    if recorded != rendered_hash:
                        report["adopted"].append(str(dst))
                    manifest["files"][rel_key] = rendered_hash
                    continue
                if recorded == on_disk or (recorded is not None and force):
                    # 도구 소유 갱신, 또는 manifest 기록 있고 force(사용자 수정 덮기)
                    dst.write_bytes(rendered)
                    report["updated"].append(str(dst))
                else:
                    # manifest 밖(사용자 소유) 또는 사용자 수정 + not force — 보존
                    report["skipped"].append(str(dst))
                    continue
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(rendered)
                report["created"].append(str(dst))
            manifest["files"][rel_key] = rendered_hash
```

- [ ] **Step 4: 통과 확인 (기존 보존 테스트 회귀 포함)**

Run: `.venv/bin/python -m pytest tests/test_installer.py -v`
Expected: PASS. 특히 `test_reinstall_is_idempotent`는 이제 재설치 시 내용 동일 → updated가 아니라 채택 경로일 수 있다. 확인: 첫 설치는 manifest에 기록되므로 `recorded == rendered_hash` → `on_disk == rendered_hash` 분기에서 `recorded == rendered_hash`라 `adopted`에 안 들어가고 그냥 유지. `updated`는 빈다. **`test_reinstall_is_idempotent`의 `len(report["updated"]) == 4` 단언을 `report["updated"] == [] and report["adopted"] == []`로 고친다**(내용 동일·이미 도구 소유 → 무변경).

- [ ] **Step 5: cli install·bootstrap에 `--force` 노출**

`_run_install`:
```python
    parser.add_argument("--force", action="store_true",
                        help="manifest 추적 파일의 사용자 수정도 덮어 갱신(엔진이 소스)")
```
```python
    report = install(target, project=project, brain_root=args.brain_root,
                     default_branch=args.default_branch, repo=args.repo, force=args.force)
```
`_run_bootstrap`(572~)의 `install(...)` 호출은 force 없이 그대로(부트스트랩은 신규 설치라 채택/생성만).

- [ ] **Step 6: 커밋**

```bash
git add src/project_brain/installer.py src/project_brain/cli.py tests/test_installer.py
git commit -m "feat(installer): --force + manifest 채택(adopt)"
```

---

# Phase B — 데이터 작업 (bb2_client 레포, 절차 + 검증 게이트)

Phase B는 코드 TDD가 아니라 "역수입·삭제 절차 + spec §6 게이트"다. 각 task는 검증 명령으로 끝난다.
**작업 전 bb2_client에서 path-limited 브랜치를 판다**(예: `docs/bb2-brain-object-model` 계열).

## Task 4: bb2 죽은 산출물 삭제 + orphan 정리

**Files (bb2_client 레포):**
- Delete: `.agents/skills/bb2-brain-ingest/scripts/fixtures/` 전체 + `scripts/__pycache__/`
- Modify: `.agents/skills/bb2-brain-ingest/references/ingest-tools.md`(fixtures 경로 가리키는 줄)

- [ ] **Step 1: 삭제 전 참조 재확인 (안전)**

```bash
cd /Users/al03040455/Desktop/bb2_client/.agents/skills/bb2-brain-ingest
grep -rn "fixtures/" SKILL.md references scripts/*.py scripts/*.sh scripts/*.js 2>/dev/null
```
Expected: `references/ingest-tools.md`의 "채운 예:" 한 줄만 fixtures 경로를 가리킨다(다른 코드 참조 0).

- [ ] **Step 2: 죽은 산출물 삭제**

```bash
cd /Users/al03040455/Desktop/bb2_client/.agents/skills/bb2-brain-ingest/scripts
git rm -r fixtures
rm -rf __pycache__
```

- [ ] **Step 3: orphan 참조 정리**

`references/ingest-tools.md`에서 fixtures 경로를 가리키는 줄(현재 ~189):
```
채운 예: `scripts/fixtures/ball-select.domain_spec.py`(14결정·{groups}형), `main-map.domain_spec.py`(0결정·list형·CORRECTIONS).
```
→ 경로 없는 형태 설명으로 교체:
```
채운 예(형태): 14결정·{groups} 래핑형 / 0결정·list형(CORRECTIONS 사용). 변칙은 references/ingest-case-log.md 참고.
```

- [ ] **Step 4: 검증 — fixtures 참조·파일 0**

```bash
cd /Users/al03040455/Desktop/bb2_client/.agents/skills/bb2-brain-ingest
test ! -d scripts/fixtures && echo "fixtures 삭제 OK"
grep -rn "scripts/fixtures" . && echo "FAIL: 남은 참조" || echo "참조 0 OK"
```
Expected: "fixtures 삭제 OK" + "참조 0 OK".

- [ ] **Step 5: 커밋 (bb2_client)**

```bash
cd /Users/al03040455/Desktop/bb2_client
git add -A .agents/skills/bb2-brain-ingest/scripts .agents/skills/bb2-brain-ingest/references/ingest-tools.md
git commit -m "chore(brain-ingest): 죽은 fixtures 삭제 + orphan 참조 정리"
```

---

## Task 5: bb2 정합본 역수입 → 엔진 templates

bb2 스킬 4종의 주입 자산(제외분 빼고)을 엔진 `templates/<skill>/`로 옮기며 변수화한다.
**긴 리터럴부터 치환**(부분문자열 충돌 방지).

**Files (project-brain 레포):**
- Create: `src/project_brain/templates/{ingest,session-ingest}/references/*` + `templates/ingest/scripts/*`(실행 4종)
- Modify: `templates/{query,ingest,session-ingest,audit}/SKILL.md`(bb2 정합본으로 갱신)

- [ ] **Step 1: 역수입 + 변수화 스크립트 (긴 것부터 치환)**

bb2 각 스킬을 엔진 templates로 복사한 뒤 치환. 제외분(test_*.py·fixtures·__pycache__)은 복사 안 함.

```bash
BB2=/Users/al03040455/Desktop/bb2_client/.agents/skills
ENG=/Users/al03040455/Downloads/codes/project-brain/src/project_brain/templates
# 스킬 키 ↔ bb2 디렉토리
declare -A MAP=( [query]=bb2-brain-query [ingest]=bb2-brain-ingest \
                 [session-ingest]=bb2-brain-session-ingest [audit]=bb2-brain-audit )
for key in "${!MAP[@]}"; do
  src="$BB2/${MAP[$key]}"; dst="$ENG/$key"
  rm -rf "$dst"; mkdir -p "$dst"
  # 통째 복사 후 제외분 삭제(rsync 비의존)
  cp -R "$src"/. "$dst"/
  find "$dst" -type d \( -name "__pycache__" -o -name "fixtures" \) -prune -exec rm -rf {} +
  find "$dst" -type f \( -name "*.pyc" -o -name "test_*.py" \) -delete
  # bb2-brain-<suffix> 디렉토리명을 SKILL 헤더에서 {{PROJECT}}-brain-<suffix>로,
  # 긴 리터럴부터: bb2_client → {{REPO}}, develop → {{DEFAULT_BRANCH}}, bb2 → {{PROJECT}}
  find "$dst" -type f \( -name "*.md" -o -name "*.py" -o -name "*.js" -o -name "*.sh" -o -name "*.json" \) -print0 \
   | while IFS= read -r -d '' f; do
       perl -i -pe 's/bb2_client/{{REPO}}/g; s/\bdevelop\b/{{DEFAULT_BRANCH}}/g; s/\bbb2\b/{{PROJECT}}/g; s/(?<!-)\bbrain\//{{BRAIN_ROOT}}\//g' "$f"
     done
done
```
주의:
- `brain/` 경로만 `{{BRAIN_ROOT}}/`로. **`(?<!-)` 음수 룩비하인드 필수** — 없으면 `project-brain/bin`(글로벌 도구명)의 `-brain/`까지 잡혀 `project-{{BRAIN_ROOT}}/bin`으로 오염된다(critic F1: `system-domain-playbook.md:62`에 실재). 하이픈 앞만 막으면 bare `brain/raw`·`brain/checks`·`brain/objects`는 정상 치환, `project-brain/bin`은 보존.
- `BB2`(대문자)·`LineBubble2`는 `\bbb2\b`(소문자·단어경계)에 안 걸려 리터럴로 남는다(spec §3.2 의도).
- `develop`는 단어경계라 `developer`/`development` 미오염(bb2 데이터에서 confirmed 깨끗).

- [ ] **Step 2: 치환 정확성 — 합성값 렌더 스모크 테스트 추가 (§6.1, 항구)**

일회성 스크립트가 아니라 `tests/test_installer.py`에 항구 테스트로 넣어, 역수입된 실제 templates가
합성값으로 미치환 토큰 없이 렌더되는지(왕복 항등성 함정 회피) 회귀로 잡는다. 이 테스트는 templates에
`{{REPO}}`·`{{DEFAULT_BRANCH}}`가 생긴 역수입 후라야 의미 있어 Phase B에서 추가한다.

```python
    def test_real_templates_render_with_synthetic_values(self):
        # 역수입된 실제 templates를 합성값으로 렌더 → (a) 미치환 토큰 0(현재 brain 스킬엔
        # 정당한 {{ 리터럴이 없음 — 확인됨), (b) 도구명 오염(project-{{BRAIN_ROOT}}) 부재.
        import project_brain.installer as inst
        for skill in inst._SKILLS:
            root = inst._TEMPLATES_DIR / skill
            for src in root.rglob("*"):
                if not src.is_file() or inst._excluded(src.relative_to(root)):
                    continue
                if src.suffix not in inst._TEXT_SUFFIXES:
                    continue
                raw = src.read_text(encoding="utf-8")
                out = inst.render_text(raw, project="zzz", brain_root="kkk",
                                       default_branch="ttt", repo="qqq")
                self.assertNotIn("{{", out, f"미치환 토큰: {src}")
                # F1 오염 백스톱: perl이 project-brain/bin의 -brain/까지 잡아 템플릿이
                # project-{{BRAIN_ROOT}}로 깨졌다면 합성 렌더에서 project-kkk가 나타난다.
                # 정상(리터럴 project-brain)에선 안 나오므로 '부재'를 단언한다.
                # assertIn("project-brain")은 항진명제 — render가 리터럴을 안 건드려 항상
                # 참이라 정작 오염을 놓친다. 부재 검사라야 실제로 잡는다(critic F3).
                self.assertNotIn("project-kkk", out,
                                 f"도구명 오염(project-brain→project-<root>): {src}")
```

Run: `.venv/bin/python -m pytest tests/test_installer.py::InstallTest::test_real_templates_render_with_synthetic_values -v`
Expected: PASS. FAIL 케이스 — `{{...}}` 잔여(치환 누락) 또는 `project-brain`이 `project-kkk`로 깨짐(F1 오염). 미치환만 보던 약한 버전이 F1을 놓쳤으므로 도구명 보존 단언을 함께 둔다.

- [ ] **Step 3: 리터럴 0 + 변수 등장 (§5.3)**

```bash
ENG=/Users/al03040455/Downloads/codes/project-brain/src/project_brain/templates
echo "-- bb2_client/develop 리터럴(0이어야) --"; grep -rn "bb2_client\|\bdevelop\b" "$ENG" || echo "리터럴 0 OK"
echo "-- 변수 실제 등장(있어야) --"; grep -rln "{{REPO}}" "$ENG"; grep -rln "{{DEFAULT_BRANCH}}" "$ENG"
```
Expected: 리터럴 0 **이면서** `{{REPO}}`·`{{DEFAULT_BRANCH}}`가 실제 파일에 등장(0건만 보면 잘못 치환돼도 통과 — 둘 다 봐야 함, spec §6.1).

- [ ] **Step 4: 파일 집합 동등성 (§6.2)**

`{엔진 템플릿 렌더 파일 집합} == {bb2 스킬 파일 − 제외분}`.

```bash
BB2=/Users/al03040455/Desktop/bb2_client/.agents/skills
ENG=/Users/al03040455/Downloads/codes/project-brain/src/project_brain/templates
for key in query ingest session-ingest audit; do
  case $key in query) b=bb2-brain-query;; ingest) b=bb2-brain-ingest;;
    session-ingest) b=bb2-brain-session-ingest;; audit) b=bb2-brain-audit;; esac
  eng=$(cd "$ENG/$key" && find . -type f ! -path "*/fixtures/*" ! -path "*/__pycache__/*" ! -name "*.pyc" ! -name "test_*.py" | sort)
  bb=$(cd "$BB2/$b" && find . -type f ! -path "*/fixtures/*" ! -path "*/__pycache__/*" ! -name "*.pyc" ! -name "test_*.py" | sort)
  if [ "$eng" = "$bb" ]; then echo "$key: 파일집합 일치 OK"; else echo "$key: MISMATCH"; diff <(echo "$eng") <(echo "$bb"); fi
done
```
Expected: 4종 모두 "파일집합 일치 OK". MISMATCH면 역수입 누락 — 그 파일을 마저 옮긴다.

- [ ] **Step 5: 커밋 (project-brain)**

```bash
cd /Users/al03040455/Downloads/codes/project-brain
git add src/project_brain/templates tests/test_installer.py
git commit -m "feat(templates): bb2 정합본 역수입 (references/scripts, 변수화) + 합성렌더 스모크"
```

---

## Task 6: 엔진 머지 — 세션 정합 항목 후퇴 방지 (diff 백스톱)

Task 5의 역수입이 엔진 templates를 bb2 내용으로 덮었다. 이번 세션이 엔진에 넣은 정합 항목이
후퇴하지 않았는지 **기계적 diff**로 확인한다(spec §5 step4).

**Files (project-brain 레포):** 필요 시 `templates/<skill>/`의 후퇴분 보강.

- [ ] **Step 1: 역수입 직전 templates와 비교**

Task 5 직전 커밋(`edc2f88` 시점의 평면 templates는 Task 1에서 `<skill>/SKILL.md`로 이동됨)과 역수입 후를 diff.

```bash
cd /Users/al03040455/Downloads/codes/project-brain
# Task 1(재배치) 커밋과 Task 5(역수입) 커밋 사이 templates diff에서 "삭제된 줄" 검토
git log --oneline -- src/project_brain/templates | head
git diff <Task1_커밋> <Task5_커밋> -- src/project_brain/templates | grep '^-' | grep -v '^---' | less
```
Expected: 삭제된 줄(엔진에만 있던 내용) 전수 검토. 이번 세션 정합 항목(줄번호 제거·audit 신설 등 templates 텍스트 영향분)이 사라졌으면 보강 대상.

- [ ] **Step 2: 체크리스트 대조**

이번 세션 정합 항목별로 bb2 디스크(=역수입된 templates)에 이미 반영됐는지 확인:
- **줄번호 제거**: bb2가 2026-06-28 재정정 → 반영됨(메모리 확인). templates에서 EvidenceRef 줄번호 표기 0건이면 OK.
- **audit 신설**: `templates/audit/SKILL.md` 존재 → OK.
- **UTC Z→KST·graph isolated B+C·advisories 채널**: 주로 `src/` 코드 변경이라 templates를 안 건드림 → 후퇴 위험 없음(diff에 안 나옴).

```bash
grep -rn ":[0-9]\+-[0-9]\+\b" src/project_brain/templates/*/  # 줄번호 잔재 점검(0 기대)
test -f src/project_brain/templates/audit/SKILL.md && echo "audit OK"
```

- [ ] **Step 3: 후퇴분 보강 + 커밋 (있을 때만)**

후퇴한 항목이 있으면 해당 templates 파일을 고쳐 되살린다.
```bash
git add src/project_brain/templates
git commit -m "fix(templates): 역수입 후 세션 정합 항목 보강"
```
후퇴 없으면 이 커밋은 생략.

---

## Task 7: install 채택 + 실측 회귀 (§6.3·§6.4)

엔진을 소스로 한 install이 bb2를 원래대로 재생성하는지 확인한다.

**Files:** 없음(검증·재설치만). bb2_client에서 실행.

- [ ] **Step 1: 엔진 편집 설치 반영 (의존성 무변경이라 재설치 불필요)**

```bash
cd /Users/al03040455/Downloads/codes/project-brain
.venv/bin/python -m pytest tests/test_installer.py -q   # Phase A 회귀 재확인
```
Expected: PASS.

- [ ] **Step 2: bb2에 install — 채택 확인 (§3.4)**

bb2 config에 `repo`·`default_branch`가 있어야 치환이 복원된다. 없으면 추가.
```bash
cd /Users/al03040455/Desktop/bb2_client
# config 확인/보강
.venv/bin/python - <<'PY'
import json, pathlib
p = pathlib.Path(".project-brain.json"); c = json.loads(p.read_text())
c.setdefault("repo", "bb2_client"); c.setdefault("default_branch", "develop")
p.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n")
print("config:", c)
PY
project-brain install        # force 없이 — 역수입 정확하면 디스크==렌더라 자동 채택
```
Expected: report에 `adopted`가 채워지고 `skipped`는 비거나 무관 파일만. 불일치(skipped에 brain 스킬 파일)면 역수입 누락 → Task 5로 복귀.

- [ ] **Step 3: 내용 후퇴 없음 — diff 0 (§6.3, 보조)**

```bash
cd /Users/al03040455/Desktop/bb2_client
git diff --stat .agents/skills/bb2-brain-*
```
Expected: **변경 0**(install이 디스크와 같은 내용을 채택만 하고 안 씀). 차이가 나오면 치환/역수입 오류 — §6.1·§6.2로 원인 추적.

- [ ] **Step 4: 실측 회귀 (§6.4)**

```bash
cd /Users/al03040455/Desktop/bb2_client
python3 -m unittest discover -s brain/checks -p "test_*.py"
```
Expected: PASS. (색인·라우터 무영향 — 스킬 문서만 바뀜. eval/index rebuild 불요.)

- [ ] **Step 5: manifest 채택 결과 커밋 (bb2_client)**

```bash
cd /Users/al03040455/Desktop/bb2_client
git add .project-brain.json .project-brain-manifest.json
git commit -m "chore(brain): 엔진 단일원본 채택 — manifest 시딩 + config repo/branch"
```

- [ ] **Step 6: 규율 기록**

이후 bb2 brain 스킬은 **직접 수정 금지** — 엔진 `templates/`에서 고치고 `project-brain install --force`로 전파. (운영 규율, README/메모리 반영은 별도.)

---

## 완료 기준

- Phase A: `tests/test_installer.py` 전부 green (walk·제외·변수·force·채택).
- Phase B: §6 삼각형 통과 — 6.1 합성 렌더 스모크, 6.2 파일집합 동등성, 6.3 diff 0, 6.4 bb2 brain/checks.
- bb2 brain 스킬이 엔진 install 생성물이 되고, 이후 편집은 엔진 단일 소스에서.
