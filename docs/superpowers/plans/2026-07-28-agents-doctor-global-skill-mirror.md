# agents-doctor 글로벌 스킬 미러 검사 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) 문법으로 추적한다.

**Goal:** `doctor.py --root ~/.agents`가 "허브에 있는데 Claude Code에서 안 보이는 스킬"을 WARN으로 잡게 하고, 현재 미보급 스킬 3개를 미러+off로 정리해 실환경을 ✅로 만든다.

**Architecture:** 글로벌 모드에 `check_global_skill_mirror` 검사 1개 추가. 허브(`~/.agents/skills/<name>`, SKILL.md 보유)마다 `~/.claude/skills` 심링크 미러를 요구하되, **켜진 Claude 플러그인이 같은 이름의 스킬을 제공하면 면제**(superpowers 7개가 오탐되는 걸 막음). Codex는 `~/.agents/skills`를 네이티브 스캔 루트로 직접 읽으므로(2026-07-28 Orca 실측) codex 미러는 검사하지 않는다.

**Tech Stack:** Python 3 표준 라이브러리만 (기존 doctor.py 관례). 테스트는 `test_doctor.py`의 `case_*` + `CASES` 등록 방식.

## Global Constraints

- 표준 라이브러리만 사용한다 — 외부 패키지 금지 (`test_doctor.py:4` "표준 라이브러리만 쓴다").
- `~/.agents`는 **git 레포가 아니다** (2026-07-28 확인: `git rev-parse` → fatal). 커밋 대신 수정 전 scratchpad 백업을 뜬다. 백업 디렉토리: `/private/tmp/claude-501/-Users-al03040455-Downloads-codes-project-brain/1073b43c-3cae-4b84-83c5-dd7e7652ddf1/scratchpad` (아래 `$S`로 표기).
- 진단 메시지는 기존 한국어 스타일을 따른다 (예: `"skill 'X' 의 claude 미러 심링크 없음"`).
- WARN은 종료 코드 1을 낸다 — 기존 report/exit 규약 그대로, 새 severity를 만들지 않는다.
- doctor.py는 어댑터 파일을 직접 쓰지 않는다 — 이 검사는 보고만 하고 `--fix`로 심링크를 만들지 않는다 (기존 `case_fix_does_not_create_skill_mirror`와 같은 철학).
- 스킬 파일 경로: `~/.agents/skills/agents-doctor/scripts/doctor.py`, 같은 디렉토리의 `test_doctor.py`. `~/.claude/skills/agents-doctor`는 이 디렉토리로 가는 심링크라 따로 손대지 않는다.
- 검증 명령(모든 태스크 공통): `python3 ~/.agents/skills/agents-doctor/scripts/test_doctor.py`

## 배경 (구현자가 알아야 할 사실)

- **왜 이 검사가 필요한가**: Claude Code는 `~/.claude/skills/`만 스캔하고 `~/.agents/skills/`(허브 원본)는 안 본다. 스킬 설치 도구(`~/.agents/.skill-lock.json`)의 대상 에이전트 목록에 Claude Code가 빠져 있어서, 2026-07-14 설치된 4개 스킬 중 수동 미러를 만든 orca-cli만 Claude에 보였다. doctor 글로벌 모드에는 rule 미러 검사(`check_global_rule_coverage`)만 있고 skill 미러 검사가 없어서 이걸 못 잡았다 (프로젝트 모드에는 `check_project_skill_mirror`가 있음).
- **플러그인 면제가 필요한 이유**: 허브의 `brainstorming` 등 7개는 `~/.codex/superpowers/skills/`로 가는 심링크다(Codex 보급용). Claude는 같은 스킬을 superpowers **플러그인**(현재 6.2.0, 더 최신 본문)으로 받는다. 여기에 미러를 만들면 같은 이름이 두 개 떠서 중복이 된다. 그래서 "켜진 플러그인이 같은 이름을 제공하면 미러 불요"로 면제한다.
- **면제 판단 데이터**: `~/.claude/settings.json`의 `enabledPlugins`(`"<plugin>@<marketplace>": true`)와 플러그인 캐시 `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/skills/<name>/SKILL.md`. 버전 디렉토리가 여러 개 쌓일 수 있는데, 면제 목적에는 "어느 버전이든 그 이름을 제공하나"만 보면 되므로 최신 버전 선별 로직은 넣지 않는다 (YAGNI).
- **doctor.py의 홈 해석**: 글로벌 모드에서 `home = root.parent` (`check_global_broken` 참고). 테스트가 임시 디렉토리로 홈을 흉내 낼 수 있는 이유다.
- **구현 후 실환경 예상 — WARN 9건**: superpowers 7개는 플러그인 면제, `superpowers` 디렉토리 링크는 최상위 SKILL.md 없어 스킵. 남는 건 (a) 미러 자체가 없는 `computer-use`, `diagnosing-bugs`, `find-skills` 3개 + (b) 미러 자리에 심링크가 아니라 **실물 사본 디렉토리**가 있는 `pkm-vault`, `slides-grab`(및 -plan/-design/-card-news/-export) 6개. (b)는 2026-07-28 전수 비교로 hub와 바이트 단위 동일임을 확인했다(아직 안 갈라진 중복 사본) — 검사가 이걸 WARN하는 게 맞고, Task 3에서 심링크로 교체한다. 정리 후 ✅.

---

### Task 1: 빨간 테스트 — 글로벌 스킬 미러 검사 기대치 추가

**Files:**
- Modify: `~/.agents/skills/agents-doctor/scripts/test_doctor.py` (`make_global_agents` 168–184행, `CASES` 375–393행, 새 case 2개는 `case_global_root_healthy` 뒤 373행 부근)

**Interfaces:**
- Produces: fixture `make_global_agents`가 `home/.claude/skills/demo` 미러 심링크를 기본 생성 (Task 2의 검사가 healthy fixture를 계속 ✅로 판정하기 위한 전제)
- Produces: `case_global_missing_skill_mirror`, `case_global_plugin_provided_skill_exempt` — Task 2 구현이 통과시켜야 할 계약

- [ ] **Step 1: 수정 전 백업**

```bash
cp ~/.agents/skills/agents-doctor/scripts/test_doctor.py "$S/test_doctor.py.bak"
cp ~/.agents/skills/agents-doctor/scripts/doctor.py "$S/doctor.py.bak"
```

- [ ] **Step 2: `make_global_agents`에 demo 스킬의 claude 미러 추가**

183행 `write_json(root / ".skill-lock.json", ...)` 바로 앞에 추가:

```python
    (home / ".claude/skills").mkdir(parents=True, exist_ok=True)
    os.symlink(os.path.relpath(root / "skills/demo", home / ".claude/skills"),
               home / ".claude/skills/demo")
```

기존 rule 미러 생성(179–182행)과 같은 `os.path.relpath` 관례를 따른다.

- [ ] **Step 3: 새 case 2개 추가**

`case_global_root_healthy`(368–372행) 뒤에 추가:

```python
def case_global_missing_skill_mirror(root):
    agents = make_global_agents(Path(root) / ".agents")
    (agents / "skills/lonely").mkdir(parents=True)
    (agents / "skills/lonely/SKILL.md").write_text("# lonely\n", encoding="utf-8")
    r = run_doctor(agents)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "lonely" in r.stdout and "미러" in r.stdout


def case_global_plugin_provided_skill_exempt(root):
    agents = make_global_agents(Path(root) / ".agents")
    home = agents.parent
    (agents / "skills/fromplugin").mkdir(parents=True)
    (agents / "skills/fromplugin/SKILL.md").write_text("# fromplugin\n", encoding="utf-8")
    write_json(home / ".claude/settings.json",
               {"enabledPlugins": {"sp@mkt": True}})
    plugin_skill = home / ".claude/plugins/cache/mkt/sp/1.0.0/skills/fromplugin"
    plugin_skill.mkdir(parents=True)
    (plugin_skill / "SKILL.md").write_text("# fromplugin\n", encoding="utf-8")
    r = run_doctor(agents)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "fromplugin" not in r.stdout
```

- [ ] **Step 4: `CASES` 목록에 등록**

`case_global_root_healthy,` 줄(392행) 뒤에 추가:

```python
    case_global_missing_skill_mirror,
    case_global_plugin_provided_skill_exempt,
```

- [ ] **Step 5: 테스트 실행 — 빨간 확인**

```bash
python3 ~/.agents/skills/agents-doctor/scripts/test_doctor.py
```

기대: `FAIL case_global_missing_skill_mirror` (검사가 아직 없어 rc 0이 나와 `assert r.returncode == 1` 실패). `case_global_plugin_provided_skill_exempt`는 이 시점에도 PASS다(검사 자체가 없으니 당연히 조용함) — 이 케이스는 빨간 테스트가 아니라 **Task 2 구현이 과잉 경고하지 않는지 지키는 가드**다. 나머지 기존 17개는 전부 PASS여야 한다. 기존 케이스가 깨지면 Step 2의 fixture 수정이 잘못된 것이니 여기서 멈추고 고친다.

---

### Task 2: `check_global_skill_mirror` 구현

**Files:**
- Modify: `~/.agents/skills/agents-doctor/scripts/doctor.py` (새 함수 2개는 `check_global_rule_coverage` 끝 325행 뒤, 배선은 `main()`의 글로벌 분기 400–404행)

**Interfaces:**
- Consumes: 기존 헬퍼 `report(severity, message)`, `read_json(path)`, `symlink_targets(directory)` — 시그니처 변경 없음
- Produces: `plugin_skill_names(home: Path) -> set[str]`, `check_global_skill_mirror(root: Path) -> None`

- [ ] **Step 1: 함수 2개 추가**

`check_global_rule_coverage` 함수(305–324행) 바로 뒤에:

```python
def plugin_skill_names(home):
    settings = read_json(home / ".claude/settings.json")
    if not isinstance(settings, dict):
        return set()
    names = set()
    cache = home / ".claude/plugins/cache"
    for key, enabled in (settings.get("enabledPlugins") or {}).items():
        if enabled is not True:
            continue
        plugin, sep, marketplace = key.partition("@")
        if not sep:
            continue
        for skill_md in cache.joinpath(marketplace, plugin).glob("*/skills/*/SKILL.md"):
            names.add(skill_md.parent.name)
    return names


def check_global_skill_mirror(root):
    home = root.parent
    src_dir = root / "skills"
    if not src_dir.is_dir():
        return
    mirrors = symlink_targets(home / ".claude/skills")
    provided = plugin_skill_names(home)
    for src in sorted(src_dir.iterdir()):
        if src.name.startswith(".") or not src.is_dir():
            continue
        if not (src / "SKILL.md").is_file():
            continue
        if src.name in provided:
            continue
        if str(src.resolve()) not in mirrors:
            report("WARN", f"global skill '{src.name}' 의 claude 미러 심링크 없음 "
                           f"(claude는 ~/.agents/skills 를 직접 스캔하지 않음)")
```

설계 근거 세 가지, 코드 리뷰 때 유의:
- `(src / "SKILL.md").is_file()` 필터가 허브의 `superpowers` 디렉토리 링크(하위에 스킬 여러 개, 최상위 SKILL.md 없음)를 자연스럽게 스킵한다. 별도 예외 목록이 필요 없다.
- `src.is_dir()`와 `src.resolve()`는 심링크를 따라가므로, 허브 항목이 심링크여도(예: `brainstorming` → `~/.codex/superpowers/...`) 동작이 같다.
- `enabled is not True`: `enabledPlugins`는 `false`로 명시 비활성화를 표현하므로 truthy 검사가 아니라 `True` 동일성으로 거른다.

- [ ] **Step 2: `main()` 글로벌 분기에 배선**

```python
    elif mode == "global":
        check_global_broken(root)
        check_global_rule_coverage(root)
        check_global_skill_mirror(root)
        check_global_skill_lock(root)
        check_global_hooks(root)
```

(기존 402행 `check_global_rule_coverage(root)` 다음 줄에 한 줄 삽입.)

- [ ] **Step 3: 테스트 실행 — 전부 초록 확인**

```bash
python3 ~/.agents/skills/agents-doctor/scripts/test_doctor.py
```

기대: `19 passed, 0 failed` (기존 17 + 새 2).

- [ ] **Step 4: 실환경에서 검사가 구멍을 잡는지 확인**

```bash
python3 ~/.agents/skills/agents-doctor/scripts/doctor.py --root ~/.agents; echo "EXIT=$?"
```

기대: WARN 정확히 9건 — `computer-use`, `diagnosing-bugs`, `find-skills`(미러 없음) + `pkm-vault`, `slides-grab`, `slides-grab-plan`, `slides-grab-design`, `slides-grab-card-news`, `slides-grab-export`(실물 사본이라 심링크 미러로 인정 안 됨) — 그리고 EXIT=1. superpowers 계열 7개나 `orchestration`이 WARN에 나오면 면제/미러 인식 버그이므로 Task 3로 넘어가지 말고 여기서 고친다.

---

### Task 3: 실환경 정리 — computer-use·diagnosing-bugs 미러+on, find-skills 제거, 실물 사본 6개는 심링크로 교체

**Files:**
- Create: `~/.claude/skills/computer-use`, `~/.claude/skills/diagnosing-bugs` (심링크, 켠 상태로)
- Delete: `~/.agents/skills/find-skills/` + `~/.agents/.skill-lock.json`의 `find-skills` 항목 (함께 제거해야 skill-lock 검사가 안 깨짐)
- Replace: `~/.claude/skills/pkm-vault`, `~/.claude/skills/slides-grab{,-plan,-design,-card-news,-export}` (실물 디렉토리 → 심링크)

**Interfaces:**
- Consumes: Task 2의 doctor 검사 (이 태스크의 완료 판정 기준)
- Produces: `doctor.py --root ~/.agents` → ✅ exit 0인 실환경

3개 판정 근거 (2026-07-28 사용자 확인):
- `computer-use` — **미러+on.** orca-cli·orchestration 스킬이 "Orca 밖 데스크톱 UI는 Computer Use로"라고 명시적으로 가리키는 짝꿍 스킬. off면 그 참조가 끊긴다. 목록 비용 ~141토큰.
- `diagnosing-bugs` — **미러+on.** superpowers:systematic-debugging과 중복 아님을 본문 대조로 확인: systematic-debugging은 "고치기 전 근본 원인" 규율, diagnosing-bugs는 "피드백 루프(재현·검증 장치) 구축법" — 보완 관계. frontmatter `disable-model-invocation: true`라 사용자가 `/diagnosing-bugs`로 부를 때만 뜨므로 모델 목록 비용도 사실상 0.
- `find-skills` — **허브에서 제거.** 사용자가 설치한 적 없음 — 7/14 orca 스킬 설치 때 설치 도구(`npx skills`, vercel-labs)가 끼워 넣은 자기 생태계 홍보용 스킬 (lock의 `dismissed.findSkillsPrompt` 플래그가 증거). off로 두면 Codex에는 계속 보이므로 미러 대신 원본을 지운다. lock 항목을 같이 지워야 `check_global_skill_lock`이 ERROR를 안 낸다.

실물 사본 6개 교체 근거: 2026-07-28 파일 트리 해시 전수 비교로 hub 원본과 바이트 단위 동일 확인(pkm-vault 1개 / slides-grab 2 / -plan 4 / -design 6 / -card-news 1 / -export 5 파일). 아직 안 갈라졌지만 사본인 이상 언젠가 갈라진다 — 오늘 superpowers vendored 사본이 플러그인과 갈라져 있던 것과 같은 경로. 심링크로 바꾸면 원본 한 곳만 남는다. slides-grab 5개는 이미 `skillOverrides` off라 Claude 동작 변화 없음, pkm-vault는 on 유지(실사용 중).

- [ ] **Step 1: 실물 사본 6개 백업 후 심링크로 교체**

```bash
mkdir -p "$S/realdir-backup"
for n in pkm-vault slides-grab slides-grab-plan slides-grab-design slides-grab-card-news slides-grab-export; do
  cp -R ~/.claude/skills/$n "$S/realdir-backup/$n"
  rm -rf ~/.claude/skills/$n
  ln -s ../../.agents/skills/$n ~/.claude/skills/$n
done
ls -la ~/.claude/skills/ | grep -E 'pkm-vault|slides-grab'
readlink -f ~/.claude/skills/pkm-vault
```

기대: 6줄 모두 `-> ../../.agents/skills/<name>` 심링크, `readlink -f`가 hub 경로를 출력. 교체 전 사본은 `$S/realdir-backup/`에 보존.

- [ ] **Step 2: computer-use·diagnosing-bugs 심링크 생성 (켠 상태 = skillOverrides 안 건드림)**

```bash
ln -s ../../.agents/skills/computer-use  ~/.claude/skills/computer-use
ln -s ../../.agents/skills/diagnosing-bugs ~/.claude/skills/diagnosing-bugs
ls -la ~/.claude/skills/ | grep -E 'computer-use|diagnosing-bugs'
```

기대: 2줄 모두 `-> ../../.agents/skills/<name>` 형태 (기존 미러들과 같은 상대경로 관례). `~/.claude/settings.json`은 이 태스크에서 수정하지 않는다.

- [ ] **Step 3: find-skills 허브에서 제거 (디렉토리 + lock 항목 함께)**

lock은 손으로 편집하지 않고 임시 파일 + jq로 안전하게 고친다:

```bash
cp ~/.agents/.skill-lock.json "$S/skill-lock.json.bak"
cp -R ~/.agents/skills/find-skills "$S/find-skills.bak"
O=$(mktemp "$S/lock.XXXXXX.json")
jq 'del(.skills["find-skills"])' ~/.agents/.skill-lock.json > "$O"
jq empty "$O" && test "$(jq -r '.skills | length' "$O")" = "3" && mv "$O" ~/.agents/.skill-lock.json
rm -rf ~/.agents/skills/find-skills
jq -r '.skills | keys | join(", ")' ~/.agents/.skill-lock.json
ls ~/.agents/skills/find-skills 2>&1
```

기대: lock의 skills 키가 `computer-use, orca-cli, orchestration` 3개, `ls`는 "No such file or directory". 검증 실패 시 mv가 실행되지 않아 lock 원본은 안전하다. (find-skills는 `~/.claude/skills`·`~/.codex/skills` 어디에도 미러가 없음을 2026-07-28 확인 — 지울 심링크 없음.)

- [ ] **Step 4: 실환경 doctor ✅ 확인**

```bash
python3 ~/.agents/skills/agents-doctor/scripts/doctor.py --root ~/.agents; echo "EXIT=$?"
```

기대: `✅ agents-doctor: /Users/al03040455/.agents 정합성 이상 없음`, EXIT=0.

---

### Task 4: agents-doctor 스킬 문서에 새 검사 항목 기재

**Files:**
- Modify: `~/.agents/skills/agents-doctor/SKILL.md` ("점검 항목 → 글로벌 `~/.agents`" 절 — 현재 1. 깨진 심링크 / 2. rule 어댑터 커버리지 / 3. skill-lock 세 항목)

**Interfaces:**
- Consumes: Task 2의 검사 동작 (문서가 코드와 일치해야 함)
- Produces: 없음 (문서 마감)

- [ ] **Step 1: 백업 + 글로벌 점검 항목에 4번 추가**

```bash
cp ~/.agents/skills/agents-doctor/SKILL.md "$S/agents-doctor-SKILL.md.bak"
```

"3. **skill-lock**" 항목 뒤에 다음 항목을 추가 (Edit 도구 사용):

```markdown
4. **skill 미러 커버리지** — `~/.agents/skills/<name>`(SKILL.md 보유)마다
   `~/.claude/skills` 미러 심링크가 있는지. 켜진 Claude 플러그인이 같은 이름의
   skill을 제공하면 면제(미러를 만들면 이름 중복). Codex는 `~/.agents/skills`를
   skill root로 직접 스캔하므로 codex 미러는 검사하지 않는다.
```

- [ ] **Step 2: 최종 전체 검증**

```bash
python3 ~/.agents/skills/agents-doctor/scripts/test_doctor.py
python3 ~/.agents/skills/agents-doctor/scripts/doctor.py --root ~/.agents; echo "EXIT=$?"
python3 ~/.agents/skills/agents-doctor/scripts/doctor.py --root /Users/al03040455/Downloads/codes/project-brain 2>&1 | tail -3
```

기대: 테스트 19 passed / 글로벌 ✅ EXIT=0 / 프로젝트 모드 기존 동작 무변화(이 레포는 `.agents` 구조가 없으므로 기존과 같은 출력).

---

## 완료 기준 요약

1. `test_doctor.py` 19 passed, 0 failed
2. `doctor.py --root ~/.agents` → ✅ exit 0 (구현 직후 시점엔 WARN 9건으로 구멍을 실제로 잡았다는 증거를 먼저 확인)
3. 허브 스킬 전수(제거 후 30개): 기존 심링크 미러(14) / 플러그인 면제(7) / SKILL.md 없어 대상 외(superpowers 디렉토리 링크) / 실물 사본→심링크 교체(6) / 신규 미러+on(2: computer-use, diagnosing-bugs) / 허브에서 제거(1: find-skills) — WARN 0
4. `~/.claude/skills`에 hub 스킬의 실물 사본 0개 (심링크 아니면 Claude 전용뿐)
5. `~/.agents/.skill-lock.json` skills = computer-use, orca-cli, orchestration (find-skills 항목 없음)
6. 문서(SKILL.md)가 검사 4개를 기재

## 이 계획이 다루지 않는 것 (의도적 제외)

- `--fix`로 미러 자동 생성 — doctor는 보고만 한다는 기존 철학 유지. 미러 생성의 유일한 자동화 통로를 만들려면 installer 쪽 작업인데, 재발 빈도(스킬 설치는 월 단위)에 비해 과투자라 뺐다.
- `.skill-lock.json`의 `lastSelectedAgents`에 claude 추가 — 그 파일은 외부 설치 도구의 상태 파일이라 선택 목록까지 손대면 도구와 어긋날 수 있다. 다음 설치 때 도구 UI에서 claude를 선택하면 되고, 빠뜨려도 이제 doctor가 잡는다. (Task 3의 find-skills 항목 삭제는 예외 — 디렉토리와 lock 기록을 한 쌍으로 지우는 일관 제거라 도구 상태가 어긋나지 않는다.)
- `~/.claude/skills`의 실물 디렉토리(orphan) INFO 보고 — 프로젝트 모드에는 있지만 글로벌은 pkm-vault, slides-grab류 의도적 Claude 전용이 많아 소음만 늘린다. 필요해지면 별도 추가.
- Codex 미러 검사 — Codex는 허브를 네이티브 스캔(2026-07-28 실측)하므로 검사 대상이 아니다.
