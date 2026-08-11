# Task 18 표시 라벨 정리 + 인용문 부채 목록 — 실행 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BB2 코드 앵커 3,305장의 표시 라벨을 코드 심볼로 통일하고, 인용문 없는 앵커 3,307장의 부채 목록을 고정한 뒤, 남은 Task 19 뒷정리(스킬 재설치·미커밋 2건 커밋·낡은 값 정정·최종 검증·최종 스냅샷)를 마쳐 복구 계획서를 닫는다.

**Architecture:** 엔진의 `migration display plan → apply`가 라벨 교체를 담당한다. 이 경로는 `title` 외 칸이 바뀌면 계획 단계에서 거부하고, `apply`는 살아 있는 코퍼스로 다시 계획해 manifest 바이트가 같아야만 통과한다. 부채 목록은 엔진에 기능이 없어 데이터 레포에 읽기 전용 생성기 하나를 새로 만든다. 그림 라벨 개선만 엔진 코드 변경(`graph_viz.py`)이다.

**Tech Stack:** Python 3.12, pytest / unittest, project-brain CLI, Git plumbing, jq

**정본 설계:** [2026-08-04 Task 18 설계](../specs/2026-08-04-task18-display-labels-and-quote-backlog-design.md)

---

## Global Constraints

절대 경로와 고정값이다. 모든 Task가 이 값을 쓴다.

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
BRAIN=/Users/al03040455/Desktop/bb2_client/brain
SNAP=/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-04/task17-final/task17-final
OUT=/Users/al03040455/Desktop/bb2_client/brain/recovery/2026-08-04
SNAP_SHA=d4ac0ddf512405d63ac9bfdf606af2fb650f343e5ac6d5b1d184902b30156331
ENGINE_SHA=76827c3fe3e09104e657db515e0b21a37eb55b18
TARGET_HEAD=a6add8d7791a37a282d7af9e13a1b29fc1581e2c
```

**셸 상태는 명령 사이에 남지 않는다.** 각 bash 블록 맨 위에서 필요한 변수를 다시 선언한다.

- **파이썬은 항상** `PYTHONPATH=$ENGINE/src $ENGINE/.venv/bin/python`. bare `python`·`project-brain` 금지 (다른 checkout을 물 수 있다).
- **Task 1~4가 끝나기 전에는 어느 레포에도 커밋하지 않는다.** 라벨 교체는 BB2 HEAD `f00f448a2c…`, 엔진 HEAD `76827c3…`, 코퍼스 지문 `0e9a2d52…` 세 값이 스냅샷과 같을 때만 돈다.
- **`git add -A` / `git add .` / `git commit -a` 전면 금지.** 엔진에는 보존 대상 미추적 문서가, BB2에는 무관한 사용자 변경 12건과 미추적 복구 번들 13개가 깔려 있다.
- **`brain/` 아래를 stage하려면 `git add -f`가 필요하다** (`.git/info/exclude`에 `/brain`). `.agents/skills/` 아래와 `.project-brain-manifest.json`은 `-f` 없이 된다.
- **`project-brain audit`은 읽기 전용이 아니다** — `--no-stale` 없이 돌리면 `brain/.brain-local/stale-set.json`을 덮어쓴다. 중간 점검은 `--no-stale`로만. 최종 스냅샷은 전체 audit **뒤에** 뜬다.
- **`index rebuild`를 돌리지 않는다.** 라벨은 검색 표면에 없어 색인 지문이 안 바뀐다. 계획서에 남은 rebuild 지시는 Task 11에서 삭제한다.
- 엔진 미추적 문서(이 계획서와 설계 문서 포함)는 **보존 대상이다. 커밋하지 않는다.**

**커밋은 총 7회다** — BB2 5회(Task 4, 6, 8, 9, 13), 엔진 2회(Task 12, 15).

---

## File Structure

| 파일 | 책임 | Task |
|---|---|---|
| `$OUT/display-migration/pre-titles.json` | 교체 전 제목 3,305개 보존 | 2 |
| `$OUT/display-migration/display-migration.manifest.json` | 엔진이 만드는 교체 계획 | 3 |
| `$OUT/display-migration/plan-report.json` / `apply-report.json` | CLI 표준출력 보존 | 3, 4 |
| `$OUT/display-migration/display-gate-report.json` | 라벨 교체 전후 검증 결과 | 4 |
| `$OUT/display-migration/build_quote_backlog.py` | 부채 목록 생성기 (읽기 전용) | 5 |
| `$OUT/display-migration/test_build_quote_backlog.py` | 그 생성기의 unittest | 5 |
| `$OUT/display-migration/legacy-quote-backlog.json` | 부채 목록 2종 | 6 |
| `$OUT/installer/install-first.json` / `install-second.json` | 설치 1·2회차 보고 | 8 |
| `$OUT/final-verification.json` | 최종 게이트 결과 | 13 |
| `$ENGINE/src/project_brain/graph_viz.py` | 그림 노드 라벨·툴팁 | 7 |
| `$ENGINE/tests/test_graph_viz.py` | 그 회귀 테스트 | 7 |

---

### Task 1: 착수 게이트를 재측정한다

지난 세션 보고를 믿지 않고 직접 잰다. **하나라도 다르면 진행하지 않고 원인을 먼저 기록한다.**

**Files:**
- Read only: 두 레포의 git 상태, `$BRAIN`, `$SNAP`

**Interfaces:**
- Produces: 아래 8개 값이 기대와 일치한다는 확인. 이후 모든 Task가 이 전제 위에 선다.

- [ ] **Step 1: 두 레포의 HEAD와 미커밋 상태를 잰다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
git -C "$BB2" rev-parse HEAD
git -C "$BB2" rev-parse origin/develop
git -C "$BB2" status --porcelain | wc -l
git -C "$ENGINE" rev-parse HEAD
git -C "$ENGINE" status --porcelain | grep -cv '^??'
```

Expected:
```
f00f448a2c4955ccf7e2d02f2a4db01c1a3865a5
a6add8d7791a37a282d7af9e13a1b29fc1581e2c
13
76827c3fe3e09104e657db515e0b21a37eb55b18
0
```

엔진 미추적 파일 수는 세지 않는다 — 이 작업이 만드는 문서만큼 늘어나는 게 정상이다.

- [ ] **Step 2: 코퍼스 지문과 색인 신선도를 잰다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BRAIN=/Users/al03040455/Desktop/bb2_client/brain
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" - <<'PY'
from pathlib import Path
from project_brain.store import BrainStore
from project_brain.mutation import corpus_fingerprint
from project_brain.search_index import compute_corpus_fingerprint, read_meta_fingerprint
brain = Path("/Users/al03040455/Desktop/bb2_client/brain")
store = BrainStore.load(brain)
print("corpus   ", corpus_fingerprint(store))
print("surface  ", compute_corpus_fingerprint(store, brain))
print("index.db ", read_meta_fingerprint(brain / ".brain-local" / "index.db"))
PY
```

Expected: `corpus`가 `0e9a2d52c387a8c51b73635bf60de690e20110f59a70135d3865a1e2a5926f7c`,
`surface`와 `index.db`가 둘 다 `b6b3708f963dec1b382ef6cd7d03b8e7a4dfdb7b48b8510d3051e0daffa1734f`
(= 색인이 신선하다).

- [ ] **Step 3: 스냅샷과 연결점을 검증한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BRAIN=/Users/al03040455/Desktop/bb2_client/brain
SNAP=/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-04/task17-final/task17-final
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli snapshot verify \
  --snapshot-root "$SNAP" \
  --expected-manifest-sha256 d4ac0ddf512405d63ac9bfdf606af2fb650f343e5ac6d5b1d184902b30156331
shasum -a 256 /Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-04/task17-final/task18-binding.json
```

Expected: `{"ok": true, "snapshot_id": "task17-final", "file_count": 11132, ...}` 와
`a27aa26e238c5e0a1bf76fb48080b9b019873e0f08b93519cc86029cc6e56e5f`.

- [ ] **Step 4: 대상 수를 센다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" - <<'PY'
import re
from pathlib import Path
from project_brain.store import BrainStore
from project_brain.migration import _canonical_locator_title
from project_brain.symbol_verify import _SIMPLE_IDENTIFIER
store = BrainStore.load(Path("/Users/al03040455/Desktop/bb2_client/brain"))
objs = list(store.all())
locs = [o for o in objs if o.get("kind") == "CodeLocator"]
canon = lambda o: all(_SIMPLE_IDENTIFIER.fullmatch(p) for p in o["symbol"].split("::"))
T = {o["id"] for o in locs if o["title"] != _canonical_locator_title(o)}
Q = {o["id"] for o in locs if not o.get("verified_quote")}
B = {o["id"] for o in locs if not canon(o)}
print("objects", len(objs), "locators", len(locs))
print("T", len(T), "Q", len(Q), "B", len(B))
print("B&T", len(B & T), "B&Q", len(B & Q), "Q-T", len(Q - T))
PY
```

Expected: `objects 10941 locators 3809` / `T 3305 Q 3307 B 289` / `B&T 279 B&Q 285 Q-T 7`.

- [ ] **Step 5: 연결점의 지문 네 개가 그대로인지 확인한다**

설계 §2가 요구하는 확인이다. BB2 사용자 변경 지문 두 개와 색인·stale 지문은 지금도
연결점과 정확히 일치해야 한다. **어긋나면 사용자 변경이 유실됐거나 코퍼스가 건드려진 것이다.**
(엔진 checkout 지문 두 개는 이 작업이 만든 문서 때문에 이미 다르다 — 정상이고 엔진이 안 읽는다.)

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" - <<'PY'
import hashlib, json
from pathlib import Path
from project_brain.snapshot import capture_git_dirt_receipt

BB2 = Path("/Users/al03040455/Desktop/bb2_client")
binding = json.loads(
    (BB2 / ".snapshots/2026-08-04/task17-final/task18-binding.json")
    .read_text(encoding="utf-8"))
dirt = capture_git_dirt_receipt(BB2, label="bb2_user_dirt")
local = BB2 / "brain/.brain-local"
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
checks = {
    "bb2_user_dirt_status_sha256": dirt.status_sha256,
    "bb2_user_dirt_content_sha256": dirt.content_manifest_sha256,
    "index_fingerprint": sha(local / "index.db"),
    "stale_fingerprint": sha(local / "stale-set.json"),
}
for key, got in checks.items():
    want = binding[key]
    print(("OK  " if got == want else "DIFF"), key, got, "" if got == want else f"(기대 {want})")
print("entry_count", dirt.entry_count, "(기대 13)")
PY
```

Expected: 네 줄 전부 `OK`, `entry_count 13`.

`capture_git_dirt_receipt`는 `label` 키워드가 필수이고 dataclass를 돌려준다 —
필드는 `status_sha256` / `content_manifest_sha256` / `entry_count`다
(`snapshot.py:104-111`, `:803`). 연결점의 `bb2_user_dirt_content_sha256`에 대응하는 것은
`content_sha256`이 아니라 **`content_manifest_sha256`**이다.

- [ ] **Step 6: 어긋난 값이 있으면 멈춘다**

전부 일치하면 다음 Task로 간다. **하나라도 다르면 진행하지 말고** 무엇이 언제 왜 달라졌는지
확인해 보고한다. 특히 코퍼스 지문이 다르면 이미 누군가 코퍼스를 건드렸다는 뜻이라
스냅샷부터 다시 떠야 한다.

커밋 없음.

---

### Task 2: 교체 전 제목을 파일로 뜬다

라벨 교체는 되돌릴 수 없게 제목을 덮어쓴다. 3,305장 중 859장에 한국어가 들어 있어
(사람이 쓴 설명과 코드·주석 복사본이 섞여 있다) 부채 목록이 참조할 수 있게 먼저 보존한다.

**Files:**
- Create: `$OUT/display-migration/pre-titles.json`

**Interfaces:**
- Produces: `{ "<locator_id>": "<현재 title>" }` 형태 JSON, 정확히 3,305개 항목.
  Task 5의 `build_quote_backlog.py`가 `--pre-titles`로 읽는다.

- [ ] **Step 1: 산출물 폴더를 만든다**

```bash
mkdir -p /Users/al03040455/Desktop/bb2_client/brain/recovery/2026-08-04/display-migration
mkdir -p /Users/al03040455/Desktop/bb2_client/brain/recovery/2026-08-04/installer
```

- [ ] **Step 2: 교체 대상의 현재 제목을 덤프한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" - <<'PY'
import json
from pathlib import Path
from project_brain.store import BrainStore
from project_brain.migration import _canonical_locator_title

OUT = Path("/Users/al03040455/Desktop/bb2_client/brain/recovery/2026-08-04"
           "/display-migration/pre-titles.json")
store = BrainStore.load(Path("/Users/al03040455/Desktop/bb2_client/brain"))
pre = {
    o["id"]: o["title"]
    for o in sorted(store.all(), key=lambda x: x["id"])
    if o.get("kind") == "CodeLocator" and o["title"] != _canonical_locator_title(o)
}
OUT.write_text(json.dumps(pre, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("wrote", len(pre), "entries")
PY
```

Expected: `wrote 3305 entries`

- [ ] **Step 3: 코퍼스가 안 바뀌었는지 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -c "
from pathlib import Path
from project_brain.store import BrainStore
from project_brain.mutation import corpus_fingerprint
print(corpus_fingerprint(BrainStore.load(Path('/Users/al03040455/Desktop/bb2_client/brain'))))"
```

Expected: `0e9a2d52c387a8c51b73635bf60de690e20110f59a70135d3865a1e2a5926f7c` (그대로).

커밋 없음 — Task 4에서 함께 커밋한다.

---

### Task 3: 라벨 교체 계획을 만들고 검증한다

`plan`은 manifest 파일을 쓰지만 **코퍼스는 건드리지 않는다.**

**Files:**
- Create: `$OUT/display-migration/display-migration.manifest.json`
- Create: `$OUT/display-migration/plan-report.json`

**Interfaces:**
- Consumes: Task 1이 확인한 세 고정값 (BB2 HEAD, 엔진 HEAD, 코퍼스 지문)
- Produces: manifest 파일과 그 sha256. Task 4의 `apply`가 `--expected-manifest-sha256`으로 쓴다.

- [ ] **Step 1: 계획을 만든다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
OUT="$BB2/brain/recovery/2026-08-04"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli migration display plan \
  --brain-root "$BB2/brain" \
  --repo-root "$BB2" \
  --engine-root "$ENGINE" \
  --snapshot-root "$BB2/.snapshots/2026-08-04/task17-final/task17-final" \
  --expected-snapshot-manifest-sha256 d4ac0ddf512405d63ac9bfdf606af2fb650f343e5ac6d5b1d184902b30156331 \
  --manifest "$OUT/display-migration/display-migration.manifest.json" \
  --engine-sha 76827c3fe3e09104e657db515e0b21a37eb55b18 \
  > "$OUT/display-migration/plan-report.json"
cat "$OUT/display-migration/plan-report.json"
```

Expected: `"ok": true`, `"migration_kind": "display_only"`, `"action_count": 3305`, `"row_count": 0`,
`"snapshot_id": "task17-final"`.

실패하면 `error_code`를 본다. `snapshot_repo_head_mismatch`·`snapshot_engine_head_mismatch`·
`snapshot_corpus_fingerprint_mismatch` 중 하나면 그 사이에 누가 커밋했거나 코퍼스를 건드린 것이다.
**되돌리려 하지 말고 멈추고 보고한다.**

- [ ] **Step 2: manifest 내용이 계획대로인지 확인한다**

```bash
OUT=/Users/al03040455/Desktop/bb2_client/brain/recovery/2026-08-04
M="$OUT/display-migration/display-migration.manifest.json"
jq '{updates: (.mutation_manifest.updates | length),
     creates: (.mutation_manifest.creates | length),
     deletes: (.mutation_manifest.deletes | length),
     renames: (.mutation_manifest.renames | length),
     aux: (.mutation_manifest.auxiliary_updates | length),
     before: .mutation_manifest.before_fingerprint,
     after: .mutation_manifest.expected_after_fingerprint}' "$M"
```

Expected: `updates 3305`, `creates`/`deletes`/`renames`/`aux` 전부 `0`,
`before` = `0e9a2d52c387a8c51b73635bf60de690e20110f59a70135d3865a1e2a5926f7c`.

`after` 값을 적어둔다 — Task 4에서 적용 후 실측값과 대조한다.
(설계 문서의 예상값은 `8d71e3ce45e5a72c…`이지만 **manifest가 낸 값이 정본**이다.)

> jq 경로가 다르면 `jq 'keys' "$M"`으로 실제 구조를 먼저 본다. manifest는
> `create_migration_artifact`가 만든 형태다.

- [ ] **Step 3: manifest 해시를 기록한다**

```bash
OUT=/Users/al03040455/Desktop/bb2_client/brain/recovery/2026-08-04
shasum -a 256 "$OUT/display-migration/display-migration.manifest.json"
jq -r .manifest_sha256 "$OUT/display-migration/plan-report.json"
```

Expected: 두 값이 같다. 이 값이 Task 4의 `--expected-manifest-sha256`이다.

- [ ] **Step 4: 코퍼스가 아직 안 바뀌었는지 확인한다**

```bash
git -C /Users/al03040455/Desktop/bb2_client status --porcelain -- brain/objects | wc -l
```

Expected: `0` — `plan`은 코퍼스를 안 건드린다.

커밋 없음.

---

### Task 4: 라벨 교체를 적용하고 커밋한다 (BB2 커밋 ①)

**Files:**
- Modify: `$BRAIN/objects/code/*.json` 3,305개 (`title` 칸만)
- Create: `$OUT/display-migration/apply-report.json`
- Create: `$OUT/display-migration/display-gate-report.json`

**Interfaces:**
- Consumes: Task 3의 manifest와 그 sha256
- Produces: 교체된 코퍼스. 새 코퍼스 지문. Task 5 이후 모든 검증의 기준.

- [ ] **Step 1: 적용 전 바이트 해시를 떠둔다**

`title`을 뺀 나머지가 안 바뀌었는지 대조하려면 적용 전 값이 필요하다. `brain/objects/code`는
3,809개 전부 추적 중이고 지금 수정 0이라 `git show HEAD:`가 정확한 적용 전 상태다.

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" - <<'PY'
import hashlib, json, subprocess
from pathlib import Path
from project_brain.hash_utils import stable_json

BB2 = Path("/Users/al03040455/Desktop/bb2_client")
OUT = BB2 / "brain/recovery/2026-08-04/display-migration/pre-nontitle-hashes.json"
ids = json.loads((BB2 / "brain/recovery/2026-08-04/display-migration"
                  / "pre-titles.json").read_text(encoding="utf-8")).keys()
res = {}
for oid in ids:
    raw = subprocess.run(
        ["git", "-C", str(BB2), "show", f"HEAD:brain/objects/code/{oid}.json"],
        capture_output=True, check=True).stdout
    obj = json.loads(raw)
    obj.pop("title", None)
    res[oid] = hashlib.sha256(stable_json(obj).encode("utf-8")).hexdigest()
OUT.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
print("hashed", len(res))
PY
```

Expected: `hashed 3305`

- [ ] **Step 2: 적용한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
OUT="$BB2/brain/recovery/2026-08-04"
MSHA=$(jq -r .manifest_sha256 "$OUT/display-migration/plan-report.json")
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli migration display apply \
  --brain-root "$BB2/brain" \
  --repo-root "$BB2" \
  --engine-root "$ENGINE" \
  --snapshot-root "$BB2/.snapshots/2026-08-04/task17-final/task17-final" \
  --expected-snapshot-manifest-sha256 d4ac0ddf512405d63ac9bfdf606af2fb650f343e5ac6d5b1d184902b30156331 \
  --manifest "$OUT/display-migration/display-migration.manifest.json" \
  --expected-manifest-sha256 "$MSHA" \
  --engine-sha 76827c3fe3e09104e657db515e0b21a37eb55b18 \
  > "$OUT/display-migration/apply-report.json"
cat "$OUT/display-migration/apply-report.json"
```

Expected: `"ok": true`, `"action_count": 3305`.

`manifest_revalidation_failed`가 나오면 plan 이후 코퍼스가 바뀐 것이다. 멈추고 보고한다.

- [ ] **Step 3: 제목 외 칸이 안 바뀌었는지 전수 대조한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" - <<'PY'
import hashlib, json
from pathlib import Path
from project_brain.hash_utils import stable_json

D = Path("/Users/al03040455/Desktop/bb2_client/brain/recovery/2026-08-04/display-migration")
CODE = Path("/Users/al03040455/Desktop/bb2_client/brain/objects/code")
before = json.loads((D / "pre-nontitle-hashes.json").read_text(encoding="utf-8"))
bad = []
for oid, h in before.items():
    obj = json.loads((CODE / f"{oid}.json").read_text(encoding="utf-8"))
    obj.pop("title", None)
    if hashlib.sha256(stable_json(obj).encode("utf-8")).hexdigest() != h:
        bad.append(oid)
print("compared", len(before), "mismatched", len(bad))
if bad:
    print(bad[:10])
PY
```

Expected: `compared 3305 mismatched 0`

**하나라도 어긋나면 되돌린다** — `git -C $BB2 checkout -- brain/objects/code`.

- [ ] **Step 4: 지문·객체 수·lint를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
OUT="$BB2/brain/recovery/2026-08-04"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" - <<'PY'
import json
from pathlib import Path
from project_brain.store import BrainStore
from project_brain.mutation import corpus_fingerprint
from project_brain.search_index import compute_corpus_fingerprint, read_meta_fingerprint
from project_brain.migration import _canonical_locator_title
brain = Path("/Users/al03040455/Desktop/bb2_client/brain")
store = BrainStore.load(brain)
objs = list(store.all())
locs = [o for o in objs if o.get("kind") == "CodeLocator"]
m = json.loads((brain / "recovery/2026-08-04/display-migration"
                / "display-migration.manifest.json").read_text(encoding="utf-8"))
print("objects       ", len(objs))
print("still-mismatch", sum(1 for o in locs if o["title"] != _canonical_locator_title(o)))
print("corpus now    ", corpus_fingerprint(store))
print("surface       ", compute_corpus_fingerprint(store, brain))
print("index.db      ", read_meta_fingerprint(brain / ".brain-local" / "index.db"))
PY
cd "$BB2" && PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli lint
```

Expected:
- `objects 10941`
- `still-mismatch 0` — 다시 돌려도 대상 0개다
- `corpus now`가 Task 3 Step 2에서 적어둔 `expected_after_fingerprint`와 **같다**
- `surface`와 `index.db`가 여전히 `b6b3708f96…`로 **서로 같다** (색인 재구축 불필요 확인)
- lint 문제 0, 끊긴 참조 0

- [ ] **Step 5: 표본으로 diff 모양을 눈으로 본다**

```bash
BB2=/Users/al03040455/Desktop/bb2_client
git -C "$BB2" diff --numstat -- brain/objects/code | awk '$1!=1 || $2!=1' | head
git -C "$BB2" diff --stat -- brain/objects/code | tail -1
```

Expected: 첫 명령이 **빈 출력** (모든 파일이 정확히 1줄 추가·1줄 삭제).
둘째가 `3305 files changed, 3305 insertions(+), 3305 deletions(-)`.

- [ ] **Step 6: 검증 결과를 파일로 남긴다**

위 Step 3~5의 실제 값을 `$OUT/display-migration/display-gate-report.json`에 담는다.

```json
{
  "step": "S1 display migration",
  "applied_at": "<실제 실행 시각 KST>",
  "action_count": 3305,
  "objects_total": 10941,
  "still_mismatch": 0,
  "non_title_hash_mismatch": 0,
  "corpus_fingerprint_before": "0e9a2d52c387a8c51b73635bf60de690e20110f59a70135d3865a1e2a5926f7c",
  "corpus_fingerprint_after": "<Step 4 실측값>",
  "manifest_expected_after": "<Task 3 Step 2 값 — 위와 같아야 한다>",
  "surface_fingerprint": "b6b3708f963dec1b382ef6cd7d03b8e7a4dfdb7b48b8510d3051e0daffa1734f",
  "index_meta_fingerprint": "b6b3708f963dec1b382ef6cd7d03b8e7a4dfdb7b48b8510d3051e0daffa1734f",
  "index_rebuild_needed": false,
  "lint_problems": 0,
  "dangling_refs": 0,
  "diff_files": 3305,
  "diff_non_one_line_files": 0
}
```

- [ ] **Step 7: 커밋한다 (BB2 커밋 ①)**

```bash
BB2=/Users/al03040455/Desktop/bb2_client
git -C "$BB2" add -f -- brain/objects/code
git -C "$BB2" add -f -- brain/recovery/2026-08-04/display-migration
git -C "$BB2" status --short
git -C "$BB2" diff --cached --stat | tail -3
```

`git status --short`에 `.agents/`·`Podfile.lock`·`tools/`가 **staged로 보이면 안 된다**
(` M` 표시로 남아 있는 건 정상 — 그건 unstaged다).

```bash
BB2=/Users/al03040455/Desktop/bb2_client
git -C "$BB2" commit -m "fix(brain): normalize code locator display labels"
git -C "$BB2" log --oneline -1
```

---

### Task 5: 부채 목록 생성기를 만든다 (TDD)

엔진에 이 기능이 없다. 데이터 레포에 읽기 전용 생성기를 새로 만든다.

**Files:**
- Create: `$OUT/display-migration/build_quote_backlog.py`
- Create: `$OUT/display-migration/test_build_quote_backlog.py`

**Interfaces:**
- Consumes: `pre-titles.json` (Task 2), `BrainStore`, `project_brain.stale_check.{stale_check, make_git_runner}`
- Produces:
  ```python
  def symbol_is_canonical(symbol: str) -> bool
  def build_backlog(
      store, *, pre_titles: dict[str, str], stale_report: dict, generated_at: str
  ) -> dict   # {"summary": {...}, "quote_backlog": [...], "symbol_backlog": [...]}
  ```
  `build_backlog`는 순수 함수다 — git도 파일도 건드리지 않는다. 호출부(`main`)가
  store 로드·stale_check 호출·표준출력을 담당한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`$OUT/display-migration/test_build_quote_backlog.py`:

```python
"""build_quote_backlog 단위 테스트 — 순수 함수만 검증한다(git·디스크 접근 없음)."""
import unittest

from build_quote_backlog import build_backlog, symbol_is_canonical


def _loc(oid, **kw):
    base = {
        "id": oid, "kind": "CodeLocator", "status": "reviewed",
        "title": "T", "symbol": "Foo::bar", "path": "a/A.cpp",
        "repo": "bb2_client", "commit_sha": "0a6a13c185",
    }
    base.update(kw)
    return base


class _Store:
    def __init__(self, *objs):
        self._objs = list(objs)

    def all(self):
        return list(self._objs)


class TestSymbolShape(unittest.TestCase):
    def test_plain_and_scoped_identifiers_pass(self):
        self.assertTrue(symbol_is_canonical("bar"))
        self.assertTrue(symbol_is_canonical("A::B::C"))

    def test_destructor_passes(self):
        self.assertTrue(symbol_is_canonical("Foo::~Foo"))

    def test_slash_space_hangul_comma_fail(self):
        self.assertFalse(symbol_is_canonical("a / b"))
        self.assertFalse(symbol_is_canonical("Foo bar"))
        self.assertFalse(symbol_is_canonical("kBoostedBomb 인식"))
        self.assertFalse(symbol_is_canonical("a, b"))

    def test_empty_is_not_canonical(self):
        self.assertFalse(symbol_is_canonical(""))

    def test_matches_engine_rule(self):
        # 엔진과 같은 규칙이어야 한다. 엔진이 바뀌면 이 테스트가 깨져서 알려준다.
        from project_brain.symbol_verify import _SIMPLE_IDENTIFIER
        self.assertEqual(_SIMPLE_IDENTIFIER.pattern, r"~?[A-Za-z_][A-Za-z0-9_]*\Z")


class TestBuildBacklog(unittest.TestCase):
    def _report(self, stale_ids=(), unmerged_ids=()):
        return {
            "target_head": "a6add8d7791a37a282d7af9e13a1b29fc1581e2c",
            "locator_group": [
                {"locator_id": i, "path": "a/A.cpp", "change_type": "M",
                 "from_commit": "0a6a13c185"} for i in stale_ids
            ],
            "unmerged_anchors": [{"locator_id": i} for i in unmerged_ids],
            "candidates": [],
        }

    def test_only_locators_without_quote_are_listed(self):
        store = _Store(
            _loc("code.ctx.no-quote"),
            _loc("code.ctx.has-quote", verified_quote="int x = 1;"),
            {"id": "mapping.ctx.m", "kind": "DomainMapping", "title": "m"},
        )
        out = build_backlog(store, pre_titles={}, stale_report=self._report(),
                            generated_at="2026-08-04T00:00:00+09:00")
        self.assertEqual([e["locator_id"] for e in out["quote_backlog"]],
                         ["code.ctx.no-quote"])

    def test_symbol_backlog_is_a_subset_of_quote_backlog(self):
        store = _Store(
            _loc("code.ctx.bad", symbol="a / b"),
            _loc("code.ctx.good"),
            _loc("code.ctx.bad-but-quoted", symbol="a / b", verified_quote="q"),
        )
        out = build_backlog(store, pre_titles={}, stale_report=self._report(),
                            generated_at="2026-08-04T00:00:00+09:00")
        quote_ids = {e["locator_id"] for e in out["quote_backlog"]}
        symbol_ids = {e["locator_id"] for e in out["symbol_backlog"]}
        self.assertEqual(symbol_ids, {"code.ctx.bad"})
        self.assertTrue(symbol_ids <= quote_ids)

    def test_previous_title_prefers_pre_titles_then_current(self):
        store = _Store(_loc("code.ctx.a", title="Foo::bar"),
                       _loc("code.ctx.b", title="Foo::bar"))
        out = build_backlog(store, pre_titles={"code.ctx.a": "옛 제목"},
                            stale_report=self._report(),
                            generated_at="2026-08-04T00:00:00+09:00")
        got = {e["locator_id"]: e["previous_title"] for e in out["quote_backlog"]}
        self.assertEqual(got, {"code.ctx.a": "옛 제목", "code.ctx.b": "Foo::bar"})

    def test_stale_comes_from_injected_report_not_a_cache(self):
        store = _Store(_loc("code.ctx.a"), _loc("code.ctx.b"))
        out = build_backlog(store, pre_titles={},
                            stale_report=self._report(stale_ids=["code.ctx.b"],
                                                      unmerged_ids=["code.ctx.a"]),
                            generated_at="2026-08-04T00:00:00+09:00")
        got = {e["locator_id"]: (e["stale"], e["unmerged_anchor"])
               for e in out["quote_backlog"]}
        self.assertEqual(got, {"code.ctx.a": (False, True),
                               "code.ctx.b": (True, False)})

    def test_priority_ranks_line_range_above_stale_above_candidate(self):
        store = _Store(
            _loc("code.ctx.line", line_start=10, line_end=20),
            _loc("code.ctx.stale"),
            _loc("code.ctx.cand", status="candidate"),
            _loc("code.ctx.none"),
        )
        out = build_backlog(store, pre_titles={},
                            stale_report=self._report(stale_ids=["code.ctx.stale"]),
                            generated_at="2026-08-04T00:00:00+09:00")
        got = {e["locator_id"]: e["priority"] for e in out["quote_backlog"]}
        self.assertEqual(got["code.ctx.line"], 1)
        self.assertEqual(got["code.ctx.stale"], 2)
        self.assertEqual(got["code.ctx.cand"], 3)
        self.assertEqual(got["code.ctx.none"], 4)

    def test_summary_counts_match_array_lengths(self):
        store = _Store(_loc("code.ctx.a"), _loc("code.ctx.bad", symbol="a / b"),
                       _loc("code.ctx.q", verified_quote="q"))
        out = build_backlog(store, pre_titles={}, stale_report=self._report(),
                            generated_at="2026-08-04T00:00:00+09:00")
        s = out["summary"]
        self.assertEqual(s["quote_backlog_count"], len(out["quote_backlog"]))
        self.assertEqual(s["symbol_backlog_count"], len(out["symbol_backlog"]))
        self.assertEqual(s["total_locators"], 3)
        self.assertEqual(s["target_head"],
                         "a6add8d7791a37a282d7af9e13a1b29fc1581e2c")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
D=/Users/al03040455/Desktop/bb2_client/brain/recovery/2026-08-04/display-migration
cd "$D" && PYTHONPATH="$ENGINE/src:$D" "$ENGINE/.venv/bin/python" -m unittest test_build_quote_backlog -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'build_quote_backlog'`

- [ ] **Step 3: 생성기를 구현한다**

`$OUT/display-migration/build_quote_backlog.py`:

```python
#!/usr/bin/env python3
"""인용문 없는 코드 앵커의 부채 목록을 만든다 — 읽기 전용.

Task 18 Step 4 산출물. 인용문을 채워 넣지는 않는다(계획서가 전면 백필을 금지한다).
엔진 공개 API만 쓰고 brain 데이터를 절대 안 건드린다.

실행:
  PYTHONPATH=<engine>/src <engine>/.venv/bin/python build_quote_backlog.py \
    --brain-root /Users/al03040455/Desktop/bb2_client/brain \
    --repo-root /Users/al03040455/Desktop/bb2_client \
    --pre-titles ./pre-titles.json \
    --target-head a6add8d7791a37a282d7af9e13a1b29fc1581e2c \
    > ./legacy-quote-backlog.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

# 엔진 symbol_verify._SIMPLE_IDENTIFIER 와 같은 규칙(어휘 판정).
# 엔진이 바뀌면 test_matches_engine_rule 이 깨져서 알려준다.
_IDENT = re.compile(r"~?[A-Za-z_][A-Za-z0-9_]*\Z")


def symbol_is_canonical(symbol) -> bool:
    """"::" 로 쪼갠 조각이 전부 단순 식별자면 True."""
    if not isinstance(symbol, str) or not symbol:
        return False
    return all(_IDENT.fullmatch(part) for part in symbol.split("::"))


def _context_of(object_id: str) -> str:
    parts = str(object_id).split(".")
    return parts[1] if len(parts) > 2 else ""


def _priority(entry: dict) -> int:
    """1=줄범위 있음(복원 최우선) 2=코드변경 3=검수 전 4=그 외."""
    if entry["has_line_range"]:
        return 1
    if entry["stale"]:
        return 2
    if entry["status"] == "candidate":
        return 3
    return 4


_REASON = {
    1: "line_range_present — 옛 좌표가 남아 있어 인용문 복원이 가장 쉽다",
    2: "code_changed — mark-checked 가 필요하다",
    3: "candidate — 아직 검수 전이다",
    4: "no_quote — 인용문만 없다",
}


def build_backlog(store, *, pre_titles, stale_report, generated_at) -> dict:
    """순수 함수. git·디스크 접근 없음."""
    stale_ids = {g["locator_id"] for g in stale_report.get("locator_group") or []}
    unmerged_ids = {a["locator_id"]
                    for a in stale_report.get("unmerged_anchors") or []}

    locators = [o for o in store.all() if o.get("kind") == "CodeLocator"]
    mappings = [o for o in store.all() if o.get("kind") == "DomainMapping"]
    affected = {}
    for m in mappings:
        for lid in m.get("code_locator_ids") or []:
            affected.setdefault(lid, []).append(m["id"])

    quote_backlog = []
    for o in sorted(locators, key=lambda x: x["id"]):
        if isinstance(o.get("verified_quote"), str) and o["verified_quote"]:
            continue
        oid = o["id"]
        entry = {
            "locator_id": oid,
            "context": _context_of(oid),
            "path": o.get("path", ""),
            "symbol": o.get("symbol", ""),
            "symbol_state": ("canonical" if symbol_is_canonical(o.get("symbol"))
                             else "non_canonical"),
            "previous_title": pre_titles.get(oid, o.get("title", "")),
            "status": o.get("status", ""),
            "stale": oid in stale_ids,
            "unmerged_anchor": oid in unmerged_ids,
            "affected_mapping_ids": sorted(affected.get(oid, [])),
            "has_line_range": o.get("line_start") is not None,
            "locator_source": o.get("locator_source", ""),
        }
        entry["priority"] = _priority(entry)
        entry["reason"] = _REASON[entry["priority"]]
        quote_backlog.append(entry)

    symbol_backlog = [e for e in quote_backlog if e["symbol_state"] == "non_canonical"]

    by_context = {}
    for e in quote_backlog:
        by_context[e["context"]] = by_context.get(e["context"], 0) + 1

    summary = {
        "generated_at": generated_at,
        "target_head": stale_report.get("target_head", ""),
        "default_branch": "develop",
        "fetch": False,
        "total_locators": len(locators),
        "quote_backlog_count": len(quote_backlog),
        "symbol_backlog_count": len(symbol_backlog),
        "with_line_range": sum(1 for e in quote_backlog if e["has_line_range"]),
        "stale": sum(1 for e in quote_backlog if e["stale"]),
        "unmerged_anchor": sum(1 for e in quote_backlog if e["unmerged_anchor"]),
        "candidate": sum(1 for e in quote_backlog if e["status"] == "candidate"),
        "by_context_top": dict(sorted(by_context.items(),
                                      key=lambda kv: (-kv[1], kv[0]))[:10]),
        "note": ("인용문을 채워 넣지 않는다. 목록만 고정한다. "
                 "symbol_state 는 어휘 판정이며 엔진의 미지원 확장자·operator 예외는 반영하지 않는다."),
    }
    return {"summary": summary,
            "quote_backlog": quote_backlog,
            "symbol_backlog": symbol_backlog}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--brain-root", required=True)
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--pre-titles", required=True)
    ap.add_argument("--target-head", required=True)
    ap.add_argument("--default-branch", default="develop")
    args = ap.parse_args(argv)

    from project_brain.objbase import now_kst
    from project_brain.store import BrainStore
    from project_brain.stale_check import make_git_runner, stale_check

    store = BrainStore.load(Path(args.brain_root))
    report = stale_check(
        store,
        git_runner=make_git_runner(Path(args.repo_root)),
        target_head=args.target_head,
        default_branch=args.default_branch,
        fetch=False,
    )
    pre_titles = json.loads(Path(args.pre_titles).read_text(encoding="utf-8"))
    out = build_backlog(store, pre_titles=pre_titles, stale_report=report,
                        generated_at=now_kst())
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

> `now_kst`는 `project_brain.objbase:13`, `stable_json`은 `project_brain.hash_utils:16`에 있다
> (실측 확인). 다른 모듈에서 찾지 마라.

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
D=/Users/al03040455/Desktop/bb2_client/brain/recovery/2026-08-04/display-migration
cd "$D" && PYTHONPATH="$ENGINE/src:$D" "$ENGINE/.venv/bin/python" -m unittest test_build_quote_backlog -v
```

Expected: `OK` — 11개 테스트 전부 통과.

커밋은 Task 6에서 산출물과 함께 한다.

---

### Task 6: 부채 목록을 만들고 커밋한다 (BB2 커밋 ②)

**Files:**
- Create: `$OUT/display-migration/legacy-quote-backlog.json`

**Interfaces:**
- Consumes: Task 5의 생성기, Task 2의 `pre-titles.json`
- Produces: 부채 목록. 이후 인용문 복원·카드 쪼개기 작업의 기준이 된다.

- [ ] **Step 1: 생성기를 돌린다**

git 호출이 들어가 20~25초쯤 걸린다.

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
D="$BB2/brain/recovery/2026-08-04/display-migration"
cd "$D" && PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" build_quote_backlog.py \
  --brain-root "$BB2/brain" \
  --repo-root "$BB2" \
  --pre-titles "$D/pre-titles.json" \
  --target-head a6add8d7791a37a282d7af9e13a1b29fc1581e2c \
  > "$D/legacy-quote-backlog.json"
jq .summary "$D/legacy-quote-backlog.json"
```

Expected `summary`:
```
target_head            a6add8d7791a37a282d7af9e13a1b29fc1581e2c
total_locators         3809
quote_backlog_count    3307
symbol_backlog_count   285
with_line_range        592
stale                  371
unmerged_anchor        34
candidate              252
```

`stale`이 236으로 나오면 `--target-head`를 BB2 HEAD로 잘못 준 것이다. 기준은
`origin/develop`이지 현재 체크아웃 HEAD가 아니다.

- [ ] **Step 2: 불변식과 previous_title을 확인한다**

```bash
D=/Users/al03040455/Desktop/bb2_client/brain/recovery/2026-08-04/display-migration
jq '{
  subset: ([.symbol_backlog[].locator_id] - [.quote_backlog[].locator_id] | length),
  empty_prev: ([.quote_backlog[] | select(.previous_title == "")] | length),
  from_pre_titles: ([.quote_backlog[] | select(.previous_title != .symbol)] | length)
}' "$D/legacy-quote-backlog.json"
```

Expected: `subset 0` (부분집합 성립), `empty_prev 0`.

- [ ] **Step 3: 코퍼스가 안 바뀌었는지 확인한다**

```bash
git -C /Users/al03040455/Desktop/bb2_client status --porcelain -- brain/objects | wc -l
```

Expected: `0` — 생성기는 읽기 전용이다.

- [ ] **Step 4: 커밋한다 (BB2 커밋 ②)**

```bash
BB2=/Users/al03040455/Desktop/bb2_client
git -C "$BB2" add -f -- \
  brain/recovery/2026-08-04/display-migration/legacy-quote-backlog.json \
  brain/recovery/2026-08-04/display-migration/build_quote_backlog.py \
  brain/recovery/2026-08-04/display-migration/test_build_quote_backlog.py
git -C "$BB2" diff --cached --name-only
git -C "$BB2" commit -m "docs(brain): record legacy quote backlog"
```

Expected: staged 파일이 정확히 3개.

---

### Task 7: 그림 노드 라벨을 구별되게 고친다 (엔진, TDD)

라벨 교체 뒤 `graph export` 그림에서 같은 심볼을 가진 노드가 전부 같은 글자를 달게 된다
(최악 89장). `앵커키 · 심볼끝마디`로 바꾸면 최악이 19장으로 준다.

**Files:**
- Modify: `$ENGINE/src/project_brain/graph_viz.py:28-56`
- Modify: `$ENGINE/tests/test_graph_viz.py`

**Interfaces:**
- Produces: `build_payload(store)`의 노드 `label`·`title`(툴팁) 모양 변경.
  다른 kind의 라벨과 `details`·`edges`는 그대로다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`$ENGINE/tests/test_graph_viz.py`의 `TestBuildPayload` 클래스 안에 붙인다.
**fixture의 title을 심볼과 같게 둬야 red가 된다** — 현재 코드는 title을 1순위로 쓰므로
title이 서로 다르면 지금도 통과해버린다.

```python
    def test_code_locators_sharing_a_symbol_get_distinct_labels(self):
        # S1 적용 후 상태를 흉내낸다 — title == symbol.
        store = _store(
            _obj("code.disturb-angel.core--1", "CodeLocator",
                 title="Factory::createDisturb", symbol="Factory::createDisturb",
                 path="a/Factory.cpp"),
            _obj("code.disturb-bat.reskin--2", "CodeLocator",
                 title="Factory::createDisturb", symbol="Factory::createDisturb",
                 path="a/Factory.cpp"),
        )
        labels = [n["label"] for n in build_payload(store)["nodes"]]
        self.assertEqual(len(set(labels)), 2)
        self.assertIn("core--1 · createDisturb", labels)
        self.assertIn("reskin--2 · createDisturb", labels)

    def test_code_locator_tooltip_carries_symbol_and_path(self):
        store = _store(
            _obj("code.ctx.anchor", "CodeLocator",
                 title="Foo::bar", symbol="Foo::bar", path="a/Foo.cpp"),
        )
        tip = build_payload(store)["nodes"][0]["title"]
        self.assertIn("Foo::bar", tip)
        self.assertIn("a/Foo.cpp", tip)

    def test_code_locator_without_symbol_falls_back_to_basename(self):
        store = _store(
            _obj("code.ctx.legacy", "CodeLocator", title="", path="a/b/Legacy.cpp"),
        )
        self.assertEqual(build_payload(store)["nodes"][0]["label"],
                         "Legacy.cpp:legacy")

    def test_other_kinds_keep_their_title_label(self):
        store = _store(
            _obj("mapping.ctx.m", "DomainMapping", title="아이템 버튼 판정"),
        )
        self.assertEqual(build_payload(store)["nodes"][0]["label"], "아이템 버튼 판정")
```

- [ ] **Step 2: 실패를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
cd "$ENGINE" && PYTHONPATH=src .venv/bin/python -m pytest tests/test_graph_viz.py -q
```

Expected: 새 테스트 4개 중 최소 3개 FAIL.
- 첫 테스트: 두 라벨이 `Factory::createDisturb`로 같아 `len(set(labels)) == 1`
- 둘째: 툴팁이 `[CodeLocator]`만 담아 symbol·path 없음
- 셋째: title이 비면 symbol→path 순으로 떨어져 `a/b/Legacy.cpp`가 나옴
- 넷째는 지금도 통과한다(회귀 방지용)

- [ ] **Step 3: 구현한다**

`graph_viz.py`의 라벨·툴팁 조립부(현재 47-56행)를 바꾼다. `LABEL_FIELDS`·`TIP_FIELDS`
상수는 다른 kind가 계속 쓰므로 지우지 않는다.

```python
def _anchor_key(object_id: str) -> str:
    """id 꼬리. migration._canonical_locator_title 과 같은 파생 규칙."""
    return str(object_id).rsplit(".", 1)[-1] or "unknown"


def _code_locator_label(o: dict) -> str:
    """같은 심볼을 공유하는 앵커가 많아 심볼만으로는 구별이 안 된다.

    앵커 키를 앞에 붙여 30자 절단 뒤에도 갈리게 한다. 심볼이 없으면 정본 라벨 규칙
    (migration._canonical_locator_title)과 같은 basename 폴백을 쓴다."""
    anchor = _anchor_key(o.get("id", ""))
    symbol = o.get("symbol")
    if isinstance(symbol, str) and symbol:
        return f"{anchor} · {symbol.split('::')[-1]}"
    path = o.get("path")
    basename = PurePosixPath(path).name if isinstance(path, str) and path else "unknown"
    return f"{basename}:{anchor}"
```

`build_payload` 안의 라벨 줄을 이렇게 바꾼다.

```python
        if kind == "CodeLocator":
            label = _code_locator_label(o)
        else:
            label = next((str(o[f]) for f in LABEL_FIELDS if o.get(f)),
                         oid.split(".")[-1])
        if len(label) > 30:
            label = label[:29] + "…"
```

툴팁은 `next()`가 후보 중 한 칸만 고르므로 CodeLocator만 따로 조립한다.

```python
        tip = [f"[{kind}] {status}".strip()]
        if kind == "CodeLocator":
            if o.get("symbol"):
                tip.append(str(o["symbol"]))
            if o.get("path"):
                tip.append(str(o["path"]))
        else:
            body = next((str(o[f]) for f in TIP_FIELDS if o.get(f)), "")
            if body:
                tip.append(body[:160] + ("…" if len(body) > 160 else ""))
```

파일 맨 위 import에 `from pathlib import PurePosixPath`를 추가한다(이미 있으면 생략).

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
cd "$ENGINE" && PYTHONPATH=src .venv/bin/python -m pytest tests/test_graph_viz.py -q
```

Expected: 전부 PASS (기존 6개 + 신규 4개 = 10개).

기존 `test_label_falls_back_to_id_tail_when_label_fields_empty`가 깨지면 그 테스트의
fixture가 CodeLocator인지 본다. CodeLocator라면 새 규칙이 맞으므로 그 테스트의 기대값을
`basename:anchor_key` 형태로 갱신하고, 다른 kind라면 구현이 잘못된 것이다.

- [ ] **Step 5: 실코퍼스에서 라벨 분포를 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" - <<'PY'
import collections
from pathlib import Path
from project_brain.store import BrainStore
from project_brain.graph_viz import build_payload
store = BrainStore.load(Path("/Users/al03040455/Desktop/bb2_client/brain"))
labels = [n["label"] for n in build_payload(store)["nodes"]
          if n["id"].startswith("code.")]
c = collections.Counter(labels)
dup = {k: v for k, v in c.items() if v > 1}
print("distinct", len(c), "dup-cards", sum(dup.values()), "worst", max(c.values()))
PY
```

Expected: `distinct 2747 dup-cards 1356 worst 19` 근처.
숫자가 크게 다르면 라벨 조립이 설계와 다르다.

커밋은 Task 12에서 엔진 게이트를 통과시킨 뒤 한다.

---

### Task 8: 스킬을 재설치하고 커밋한다 (BB2 커밋 ③)

**Files:**
- Modify: `$BB2/.agents/skills/bb2-brain-{query,ingest,audit,session-ingest}/` 관리 파일 14개
- Modify: `$BB2/.project-brain-manifest.json`
- Create: `$OUT/installer/install-first.json`, `install-second.json`

**Interfaces:**
- Produces: 엔진 `main` 템플릿과 동기화된 BB2 스킬. Task 12의 엔진 커밋 목록이
  `ingest-tools.md` 수정 여부에 따라 달라진다.

- [ ] **Step 1: 진행 중인 적재 배치가 없는지 확인한다**

```bash
ls -la /Users/al03040455/Desktop/bb2_client/brain/.brain-local/ | grep -i ingest || echo "진행 중 배치 없음"
```

`ingest-<context>` 폴더가 있으면 그 배치가 끝난 뒤에 진행한다. 이번 설치는
`run_ingest_batch.py`를 +1128/−137로 바꾼다.

- [ ] **Step 2: ingest 문서의 예시 명령이 현재 CLI와 맞는지 본다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
grep -n "cli ingest\|project-brain ingest" \
  "$ENGINE/src/project_brain/templates/ingest/references/ingest-tools.md" | head
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli ingest --help | head -20
```

예시에 `--repo-root`/`--expected-repo-id`/`--expected-revision-ref`/`--engine-sha`가
빠져 있으면 **지금 고친다.** 설치 뒤에 고치면 BB2에 두 번 반영해야 한다.
고쳤으면 Task 12의 엔진 커밋 목록에 이 파일을 넣는다.

- [ ] **Step 3: 1회차를 설치한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
mkdir -p "$BB2/brain/recovery/2026-08-04/installer"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli install \
  --target "$BB2" --project bb2 --brain-root brain \
  --default-branch develop --repo bb2_client \
  > "$BB2/brain/recovery/2026-08-04/installer/install-first.json"
jq '{config, created: (.created|length), updated: (.updated|length),
     removed: (.removed|length), adopted: (.adopted|length),
     skipped: (.skipped|length)}' \
  "$BB2/brain/recovery/2026-08-04/installer/install-first.json"
```

Expected: `created 0`, `updated 14`, `removed 0`, `adopted 0`, `skipped 0`, `config "kept"`.

`skipped`가 비어 있지 않으면 **`--force`로 덮지 말고 멈춘다** — 누군가 관리 파일을 손댄 것이다.

- [ ] **Step 4: 2회차가 완전 무변화인지 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli install \
  --target "$BB2" --project bb2 --brain-root brain \
  --default-branch develop --repo bb2_client \
  > "$BB2/brain/recovery/2026-08-04/installer/install-second.json"
jq '{created: (.created|length), updated: (.updated|length),
     removed: (.removed|length), adopted: (.adopted|length),
     skipped: (.skipped|length)}' \
  "$BB2/brain/recovery/2026-08-04/installer/install-second.json"
```

Expected: 다섯 값이 **전부 0**.

- [ ] **Step 5: 프로젝트 고유 파일이 안 건드려졌는지 확인한다**

```bash
BB2=/Users/al03040455/Desktop/bb2_client
git -C "$BB2" status --porcelain -- .agents/skills/guardrails .agents/skills/agents-doctor
```

Expected: 이번 설치 전과 **같은 출력** (guardrails 4 수정 + 3 미추적, agents-doctor 3 수정).
새 항목이 생겼으면 설치가 범위를 넘은 것이다.

- [ ] **Step 6: 커밋한다 (BB2 커밋 ③)**

보고서의 경로는 **절대경로**다.

```bash
BB2=/Users/al03040455/Desktop/bb2_client
F="$BB2/brain/recovery/2026-08-04/installer/install-first.json"
jq -r '(.created + .updated)[]' "$F" | xargs -I{} git -C "$BB2" add -- {}
git -C "$BB2" add -- .project-brain-manifest.json
git -C "$BB2" add -f -- brain/recovery/2026-08-04/installer
git -C "$BB2" diff --cached --name-only
```

Expected: staged 파일이 정확히 17개 (관리 14 + manifest 1 + 설치 보고 2).
`.agents/skills/guardrails`나 `agents-doctor`가 보이면 **커밋하지 말고** 원인을 찾는다.

```bash
BB2=/Users/al03040455/Desktop/bb2_client
git -C "$BB2" commit -m "chore(brain): install recovered skill contracts"
```

---

### Task 9: 미커밋 가드와 그 근거 원문을 커밋한다 (BB2 커밋 ④)

`brain/checks/test_real_corpus.py`의 `EXPECTED_RAW_CHUNKS`가 1577 → 1586으로 고쳐진 채
커밋되지 않았고, 그 +9의 근거 원문도 git 밖에 있다. 둘은 짝이라 한 커밋으로 묶는다.

**Files:**
- Modify(commit): `$BB2/brain/checks/test_real_corpus.py`
- Add: `$BB2/brain/raw/sources/petskill-kamehameha/spec-v1.1.md`

- [ ] **Step 1: 두 파일의 상태를 확인한다**

```bash
BB2=/Users/al03040455/Desktop/bb2_client
git -C "$BB2" diff -- brain/checks/test_real_corpus.py
git -C "$BB2" ls-files --error-unmatch brain/raw/sources/petskill-kamehameha/spec-v1.1.md 2>&1 | head -2
ls -la "$BB2/brain/raw/sources/petskill-kamehameha/"
```

Expected: diff가 `EXPECTED_RAW_CHUNKS` 1577 → 1586 한 덩어리 + 사유 주석 한 줄.
`ls-files`는 `did not match any file(s) known to git` (아직 미추적).
`spec-v1.1.md`가 디스크에 있다.

- [ ] **Step 2: 실코퍼스 가드가 지금 통과하는지 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
cd "$BB2" && PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest discover -s brain/checks -p "test_*.py" 2>&1 | tail -5
```

Expected: `OK` — 10개 통과, 건너뜀 0.

실패하면 상수가 지금 코퍼스와 안 맞는 것이다. **상수를 고치기 전에** 실제 raw 청크 수가
왜 다른지 확인한다(다른 적재가 있었는지).

- [ ] **Step 3: 커밋한다 (BB2 커밋 ④)**

`/brain`이 제외 목록에 있어 `-f`가 필수다.

```bash
BB2=/Users/al03040455/Desktop/bb2_client
git -C "$BB2" add -f -- \
  brain/checks/test_real_corpus.py \
  brain/raw/sources/petskill-kamehameha/spec-v1.1.md
git -C "$BB2" diff --cached --name-only
git -C "$BB2" commit -m "fix(brain): commit raw chunk guard and its source"
```

Expected: staged 파일이 정확히 2개.

---

### Task 10: 낡은 값을 정정한다

문서 세 곳이 폐기된 스냅샷·연결점 값을 가리키고 있다. 영수증은 **고치지 않고 새 세대를 얹는다.**

**Files:**
- Modify: `$ENGINE/ROADMAP.md:403-404`
- Modify: `$ENGINE/docs/plans/2026-08-04-symbol-verify-body-scope-and-task13.md:133, :151, :561-562`
- Modify: `$BB2/brain/recovery/README.md` ("남은 문제" 절)
- Create: `~/.project-brain-task17-receipts-81beb462fa00/task17-complete-2026-08-04-engine-sha-correction.json`

- [ ] **Step 1: 되돌릴 수 없는 파일의 사본을 떠둔다**

`brain/recovery/README.md`는 git 미추적이라 복원이 안 된다.

```bash
BB2=/Users/al03040455/Desktop/bb2_client
cp "$BB2/brain/recovery/README.md" /tmp/recovery-README.before.md
ls -la /tmp/recovery-README.before.md
```

- [ ] **Step 2: 낡은 값이 있는 자리를 전부 찾는다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
grep -rn "ad657ec5\|135ce054\|148c9e7" "$ENGINE/ROADMAP.md" \
  "$ENGINE/docs/plans/2026-08-04-symbol-verify-body-scope-and-task13.md"
```

Expected: `ROADMAP.md`에 403-404행, plans 문서에 133·151·561-562행.

- [ ] **Step 3: 엔진 문서 두 개를 고친다**

바꿀 값:

| 낡은 값 | 새 값 |
|---|---|
| 최종 스냅샷 `ad657ec5…` | `d4ac0ddf512405d63ac9bfdf606af2fb650f343e5ac6d5b1d184902b30156331` |
| Task 18 연결점 `135ce054…` | `a27aa26e238c5e0a1bf76fb48080b9b019873e0f08b93519cc86029cc6e56e5f` |
| engine `148c9e7d…` | `76827c3fe3e09104e657db515e0b21a37eb55b18` |

각 자리에 경위를 한 줄 붙인다 — "`--3` 정정 커밋 `f00f448a2c` 뒤 12:10에 스냅샷을 다시 찍어
`ad657ec5…`·`135ce054…`는 폐기됐다."

plans 문서 `:151`은 값만 바꾸지 말고 문장을 고친다 —
"최종 스냅샷은 `148c9e7d`로 찍었다" → "최종본은 `76827c3`로 다시 찍었다(`148c9e7d`는 그 전 판)".

- [ ] **Step 4: BB2 복구 README의 "남은 문제" 절을 고친다**

지금 "audit이 아직 초록이 아니다"라고 적혀 있으나 Task 17 마무리에서 해결됐다.
그 절을 "2026-08-04 해결됨 — 심볼 불일치 5건을 4 대 1로 갈라 처리(엔진 `ab27a9c` 몸통 규칙 4건,
`--3` 데이터 교정 1건). `audit ok = true`."로 바꾼다.

- [ ] **Step 5: 영수증에 새 세대를 얹는다**

**기존 파일은 고치지 않는다.** 특히 `deviations_from_plan`은 실제로 일어난 계획 이탈 기록이라
어떤 경우에도 수정하지 않는다.

`~/.project-brain-task17-receipts-81beb462fa00/task17-complete-2026-08-04-engine-sha-correction.json`:

```json
{
  "kind": "correction",
  "created_at": "<실제 실행 시각 KST>",
  "corrects": "task17-complete-2026-08-04.json",
  "related_receipts": [
    "task17-complete-2026-08-04.json",
    "final-snapshot-create-2026-08-04-post-fix.json"
  ],
  "what_was_stale": {
    "engine_sha_note.binding_value": "148c9e7d676d239b614fd742edfe3a596fa33219",
    "engine_sha_note.engine_head_after_binding": "288d58127e1af733fb33a39f7dcb4b1888594374",
    "deviations_from_plan[2].detail": "ENGINE_SHA 로 148c9e7d 를 썼다고 서술"
  },
  "why": "--3 정정 커밋 f00f448a2c 뒤 12:10에 최종 스냅샷과 Task 18 연결점을 다시 만들었고, 그때 engine_sha 가 76827c3 로 재바인딩됐다. 위 두 블록은 재바인딩 전 서술이라 현재 연결점과 어긋난다.",
  "actual_values": {
    "binding.engine_sha": "76827c3fe3e09104e657db515e0b21a37eb55b18",
    "binding.task17_commit": "f00f448a2c4955ccf7e2d02f2a4db01c1a3865a5",
    "binding.sha256": "a27aa26e238c5e0a1bf76fb48080b9b019873e0f08b93519cc86029cc6e56e5f",
    "final_snapshot.manifest_sha256": "d4ac0ddf512405d63ac9bfdf606af2fb650f343e5ac6d5b1d184902b30156331"
  },
  "not_modified": "원본 영수증은 그대로 둔다. deviations_from_plan 은 수정 금지."
}
```

- [ ] **Step 6: 남은 낡은 값이 없는지 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
grep -rn "ad657ec5\|135ce054" "$ENGINE/ROADMAP.md" \
  "$ENGINE/docs/plans/2026-08-04-symbol-verify-body-scope-and-task13.md" \
  "$BB2/brain/recovery/README.md" || echo "남은 낡은 값 없음"
```

Expected: `남은 낡은 값 없음` — 경위 설명 안에 "폐기된 값"으로 인용하는 건 남아도 된다.
그 경우 어느 줄인지 확인하고 의도된 인용인지 본다.

커밋은 Task 12에서 한다.

---

### Task 11: 계획서를 정정하고 미뤄둔 작업 2건을 등재한다

**Files:**
- Modify: `$ENGINE/docs/superpowers/plans/2026-07-28-brain-ingest-recovery.md`
- Modify: `$ENGINE/ROADMAP.md` (미뤄둔 작업 절)

> 계획서는 **미추적 보존 대상**이다. 파일은 고치되 **커밋하지 않는다.**

- [ ] **Step 1: 근거 없는 색인 재구축 지시 두 곳을 지운다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
grep -n "index rebuild\|index를 재생성" \
  "$ENGINE/docs/superpowers/plans/2026-07-28-brain-ingest-recovery.md"
```

Expected: Task 18 Step 3(1599-1601행 근처)과 Task 19 Step 3(1709-1710행 근처).

둘 다 지우고 그 자리에 근거를 남긴다 — "앵커 제목은 검색 표면에 없어(`surface.py:129-137`)
색인 지문이 안 바뀐다. 실측으로 3,305장을 바꿔도 `b6b3708f96…` 그대로였다. 재구축하지 않는다."

- [ ] **Step 2: 워크트리 경로를 메인 클론으로 바꾼다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
grep -n "worktrees/brain-ingest-recovery" \
  "$ENGINE/docs/superpowers/plans/2026-07-28-brain-ingest-recovery.md"
```

Task 19 안의 `ENGINE_WORKTREE=…/.worktrees/brain-ingest-recovery`를
`ENGINE=/Users/al03040455/Downloads/codes/project-brain`로 바꾸고, 그 이유를 한 줄 적는다 —
"워크트리는 `1742c09`에 멈춰 있고 작업은 `3a91f86`으로 `main`에 머지됐다. 정본은 메인 클론이다."

- [ ] **Step 3: 공허한 조건과 증명 불가 조건을 고친다**

Task 19 Step 4에서:

- "광선발사 create 파일이 Git tracked" → "광선발사 산출물(`updates` 299 + `renames` 3 = 302개)이
  Git tracked". 해당 manifest의 `creates`는 0이라 지금 문구는 무조건 통과한다.
- "`verified_at`이 엔진 검증 사건에서 생성" → **조건 삭제.** 저장된 객체에 생성 주체 표시가
  없어 사후 증명 수단이 없다. 대신 "정황만 기록: 자정값 3,007 / 3,809"로 바꾼다.

- [ ] **Step 4: Task 18의 산출물 경로와 우선순위를 갱신한다**

Task 18 **Files** 절의 `brain/recovery/2026-07-28/…` 경로를 실제 산출 경로로 바꾼다
(설계 문서 §4 표와 같게). Step 4의 우선순위에서 "자주 조회되는 핵심 context"와
"last-query count"를 지우고 실제 축으로 바꾼다 — 줄 범위 592 / 코드 변경 371 /
검수 전 252 / 맥락별 개수. 이유를 한 줄 적는다 — "엔진에 조회 횟수를 기록하는 코드가 없다."

- [ ] **Step 5: ROADMAP 미뤄둔 작업에 2건을 등재한다**

`ROADMAP.md`의 "미뤄둔 작업" 절 끝에 9번, 10번으로 추가한다. 기존 항목과 같은 형식
("왜 미뤘는가 / 착수 트리거")을 지킨다.

**9번 — 회상 회귀: 아이템 버튼 질문이 엉뚱한 객체를 돌려준다**

```
질문   "아이템 버튼이 눌리지 않는 이유"
기대   mapping.ingame-item-usage.item-button-ready-touch-axis
실제   ledger.ingame-area-expansion.{android-fixed-width, final-boss-exception,
       top-safe-area, visible-row-unified, whole-row-foundation}
       + ledger.sally-canoe.event-end-popup-exclude
증상   질문 의도를 why_changed 로 판정 (status reviewed, candidate 0건)
경위   Task 16 검증 시점에는 통과. 그 사이 Task 17(이름 158개 변경 + 참조 71곳)이
       있었으나 인과 미확정
재현   cd bb2_client && PYTHONPATH=<engine>/src <engine>/.venv/bin/python \
       -m project_brain.cli query "아이템 버튼이 눌리지 않는 이유"
```

같은 항목에 광선발사 gate 기준 이탈 1건도 적는다 — 대상 질의 5개 중 `pop-entry-flow` 이탈,
`disturb-electric-bomb` 유입. **착수 트리거: Task 19 뒷정리 완료 직후.** 원인이 라우팅
(질문 의도 판정) 쪽이라 별개 조사가 필요하다.

**10번 — 앵커/근거 카드 짝 라벨 재동기화**

적재기는 앵커와 근거 카드에 같은 라벨을 넣는데(`assembly.py:63-77`), Task 18 라벨 교체는
CodeLocator만 대상으로 잡았다. 앵커와 이어진 쌍 3,202개 중 제목이 같던 2,720쌍에서
**2,704쌍이 새로 어긋났고**, 이미 어긋나 있던 482쌍까지 합쳐 **3,186쌍이 어긋난 채 남는다.**
**착수 트리거:** `plan_display_migration`을 EvidenceRef까지 확장하는 엔진 변경이 정당화될 때.

- [ ] **Step 6: 계획서가 stage되지 않게 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
git -C "$ENGINE" status --porcelain
```

Expected: `ROADMAP.md`와 `docs/plans/2026-08-04-…`가 ` M`(수정), `graph_viz.py`와
`tests/test_graph_viz.py`가 ` M`, 나머지는 `??`(미추적).
`docs/superpowers/plans/2026-07-28-…`는 계속 `??`여야 한다 — 고쳤어도 미추적이다.

커밋은 Task 12에서 한다.

---

### Task 12: 엔진 게이트를 통과시키고 커밋한다 (엔진 커밋 ⑤)

**Files:**
- Commit: `graph_viz.py`, `tests/test_graph_viz.py`, `ROADMAP.md`,
  `docs/plans/2026-08-04-symbol-verify-body-scope-and-task13.md`,
  (Task 8 Step 2에서 고쳤으면) `templates/ingest/references/ingest-tools.md`

- [ ] **Step 1: 엔진 전체 테스트를 돌린다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
cd "$ENGINE" && PYTHONPATH=src .venv/bin/python -m pytest -q 2>&1 | tail -5
```

Expected: 실패 0. 기준선은 1,522개 + Task 7의 신규 4개.

- [ ] **Step 2: 적재 런타임 테스트를 돌린다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
cd "$ENGINE" && PYTHONPATH=src .venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py' 2>&1 | tail -5
```

Expected: `OK` — 99개 통과.

- [ ] **Step 3: 템플릿을 고쳤으면 설치 테스트를 돌린다**

Task 8 Step 2에서 `ingest-tools.md`를 고쳤을 때만.

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
cd "$ENGINE" && PYTHONPATH=src .venv/bin/python -m pytest tests/test_installer.py -q 2>&1 | tail -5
```

Expected: 실패 0.

- [ ] **Step 4: 커밋한다 (엔진 커밋 ⑤)**

**경로를 하나씩 적는다.** `git add -A`·`git add .`·`git commit -a`를 쓰면 보존 대상
미추적 문서가 통째로 들어간다.

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
git -C "$ENGINE" add \
  src/project_brain/graph_viz.py \
  tests/test_graph_viz.py \
  ROADMAP.md \
  docs/plans/2026-08-04-symbol-verify-body-scope-and-task13.md
# Task 8 Step 2에서 고쳤으면 아래 한 줄을 추가로 실행한다:
#   git -C "$ENGINE" add src/project_brain/templates/ingest/references/ingest-tools.md
git -C "$ENGINE" diff --cached --name-only
```

Expected: staged 파일이 4개(또는 템플릿 포함 5개). `docs/superpowers/`가 하나도 없어야 한다.

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
git -C "$ENGINE" commit -m "fix(brain): disambiguate code locator graph labels"
git -C "$ENGINE" status --porcelain | grep -cv '^??'
```

Expected: 마지막 명령이 `0` — 추적 변경이 남지 않았다.

---

### Task 13: 최종 게이트를 돌리고 커밋한다 (BB2 커밋 ⑥)

**Files:**
- Create: `$OUT/final-verification.json`

- [ ] **Step 1: eval을 전체 출력으로 받는다**

`tail`로 자르면 JSON이 깨져 통과 수를 셀 수 없다.

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
cd "$BB2" && PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m project_brain.cli eval > /tmp/eval-final.json
jq '{passed, total, failures: [.scenarios[] | select(.passed == false) | .id]}' /tmp/eval-final.json
```

Expected: `passed 15`, `total 15`, `failures []`.

> jq 경로가 다르면 `jq 'keys' /tmp/eval-final.json`으로 실제 구조를 먼저 본다.

- [ ] **Step 2: 실코퍼스 가드 10개를 돌린다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
cd "$BB2" && PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest discover -s brain/checks -p "test_*.py" 2>&1 | tail -5
```

Expected: `OK` — 10개 통과, 건너뜀 0.

> `test_ingest_recovery.py`의 5개는 **얼어붙은 보고서만 읽는 영수증 검사**라 코퍼스가
> 망가져도 통과한다. 판정 근거로 쓰지 말고 돌리기만 한다.

- [ ] **Step 3: lint와 audit을 돌린다**

여기서는 전체 audit을 쓴다(stale 캐시를 갱신한다). **최종 스냅샷은 이 뒤에 뜬다.**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
cd "$BB2" && PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli lint
cd "$BB2" && PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli audit \
  --brain-root "$BB2/brain" --repo-root "$BB2" > /tmp/audit-final.json
jq '{ok, lint: (.lint|length), isolated: (.isolated|length),
     code_quotes: .code_quotes,
     locator_states: ([.locators[].symbol_relation] | group_by(.)
                      | map({(.[0]): length}) | add)}' /tmp/audit-final.json
```

Expected: `ok true`, `lint 0`, `code_quotes.ok true`.
`symbol_relation` 분포는 `verified 464 + manual_verified 19 + unsupported 3307` 근처
(정확한 값은 실측해 기록한다).

- [ ] **Step 4: 두 맥락의 자기동일 재계획이 액션 0인지 확인한다**

Task 14/16의 staging 입력은 삭제됐다. 현재 코퍼스를 그대로 desired로 넣어 "바꿀 게 없다"를
확인한다. **기존 manifest를 덮어쓰지 않게 새 임시 경로를 쓴다.**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
for CTX in petskill-kamehameha ingame-item-usage; do
  PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" - "$CTX" <<'PY'
import json, sys
from pathlib import Path
from project_brain.store import BrainStore
ctx = sys.argv[1]
store = BrainStore.load(Path("/Users/al03040455/Desktop/bb2_client/brain"))
objs = [o for o in store.all() if f".{ctx}." in o["id"] or o["id"].endswith(f".{ctx}")]
out = Path(f"/tmp/desired-{ctx}.json")
out.write_text(json.dumps(objs, ensure_ascii=False, indent=2), encoding="utf-8")
print(ctx, len(objs))
PY
done
```

Expected: `petskill-kamehameha 302` 근처, `ingame-item-usage 945` 근처
(정확한 수는 실측해 기록한다).

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
ESHA=$(git -C "$ENGINE" rev-parse HEAD)
for CTX in petskill-kamehameha ingame-item-usage; do
  PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli context-replace plan \
    --brain-root "$BB2/brain" --context-id "$CTX" \
    --desired-objects-file "/tmp/desired-$CTX.json" \
    --manifest "/tmp/replan-$CTX.manifest.json" \
    --repo-root "$BB2" --engine-sha "$ESHA"
done
```

Expected: 각각 `creates`/`updates`/`deletes`/`renames`가 **전부 0**.

> **manifest 해시를 사전 고정값으로 대조하지 않는다.** 해시 재료에 코퍼스 지문과 engine_sha가
> 들어가는데 라벨 교체와 엔진 커밋이 둘 다 그 값을 바꿨다. 이번 실행에서 나온 값을 실측으로 기록한다.

- [ ] **Step 5: 남은 사용자 변경이 12건인지 확인한다**

```bash
BB2=/Users/al03040455/Desktop/bb2_client
git -C "$BB2" status --short
git -C "$BB2" status --porcelain | wc -l
```

Expected: `12`. 목록은 `.agents/skills/agents-doctor` 3, `guardrails` 4 + 미추적 3,
`Podfile.lock`, `tools/codesearch-eval/README.md`.

13이면 커밋 하나가 빠진 것이고, 12보다 적으면 **남의 변경을 커밋한 것이다** — 어느 커밋인지
찾아 되돌린다.

- [ ] **Step 6: 결과를 파일에 담는다**

`$OUT/final-verification.json`. 모든 값은 위 단계의 **실측값**으로 채운다.

```json
{
  "verified_at": "<실제 실행 시각 KST>",
  "engine_sha": "<Task 12 커밋 후 엔진 HEAD>",
  "bb2_head": "<Task 9 커밋 후 BB2 HEAD>",
  "corpus_fingerprint": "<실측>",
  "conditions": {
    "eval": {"passed": 15, "total": 15, "failures": []},
    "real_corpus_checks": {"tests": 10, "skipped": 0, "result": "OK",
                           "note": "test_ingest_recovery.py 5개는 얼어붙은 영수증 검사라 판정 근거에서 제외"},
    "target_queries": {
      "baseline": "brain/recovery/2026-07-28/ingame-item-usage/gate-report.json",
      "hits": "3/3",
      "known_failures": [
        {"query": "아이템 버튼이 눌리지 않는 이유",
         "expected": "mapping.ingame-item-usage.item-button-ready-touch-axis",
         "actual": "ledger.ingame-area-expansion.* 5 + ledger.sally-canoe.event-end-popup-exclude",
         "tracked_in": "ROADMAP.md 미뤄둔 작업 9번"},
        {"query": "<광선발사 gate 의 pop-entry-flow 질의>",
         "note": "광선발사 gate 기준 5개 중 1개 이탈. 같은 ROADMAP 항목에 등재"}
      ]
    },
    "unrelated_queries": {"baseline_same": true, "detail": "<실측>"},
    "id_invalid": 0,
    "dangling_refs": 0,
    "two_context_quote_symbol": {
      "machine_verified": "<실측>", "manual_verified": 19,
      "not_checked_no_quote": 3307, "failed": 0,
      "note": "전수 검증이 아니다. 인용문 없는 앵커는 검사에서 빠진다"
    },
    "verified_at_provenance": {
      "verdict": "확인 수단 없음",
      "note": "저장된 객체에 생성 주체 표시가 없다. 정황: 자정값 3007 / 3809"
    },
    "second_finalize_noop": {
      "petskill-kamehameha": {"actions": 0, "manifest_sha256": "<이번 실측>"},
      "ingame-item-usage": {"actions": 0, "manifest_sha256": "<이번 실측>"}
    },
    "installer_second_run_noop": true,
    "kamehameha_outputs_tracked": {"updates": 299, "renames": 3, "total": 302,
                                   "all_tracked": true},
    "user_dirt_preserved": {"expected": 12, "actual": "<실측>", "list": []}
  },
  "task18": {
    "labels_migrated": 3305,
    "quote_backlog": 3307,
    "symbol_backlog": 285,
    "index_rebuild_needed": false
  },
  "deferred": [
    "ROADMAP 미뤄둔 작업 9번 — 회상 회귀",
    "ROADMAP 미뤄둔 작업 10번 — 앵커/근거 카드 짝 라벨 3,186쌍"
  ]
}
```

- [ ] **Step 7: 커밋한다 (BB2 커밋 ⑥)**

```bash
BB2=/Users/al03040455/Desktop/bb2_client
git -C "$BB2" add -f -- brain/recovery/2026-08-04/final-verification.json
git -C "$BB2" diff --cached --name-only
git -C "$BB2" commit -m "docs(brain): record ingest recovery verification"
```

Expected: staged 파일이 정확히 1개.

---

### Task 14: 최종 스냅샷을 뜬다

**audit보다 뒤에** 떠야 한다(Task 13 Step 3에서 audit이 `stale-set.json`을 갱신했다).

**Files:**
- Create: `$BB2/.snapshots/2026-08-04/task18-final/`

- [ ] **Step 1: 스냅샷을 만든다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli snapshot create \
  --brain-root "$BB2/brain" \
  --repo-root "$BB2" \
  --engine-root "$ENGINE" \
  --output-root "$BB2/.snapshots/2026-08-04/task18-final" \
  --snapshot-id task18-final \
  > /tmp/task18-snapshot-create.json
cat /tmp/task18-snapshot-create.json
```

Expected: `"ok": true`와 `manifest_sha256`, `file_count`.
두 값은 Task 15의 ROADMAP 완료 기록에 들어간다.

- [ ] **Step 2: 검증한다**

해시는 손으로 옮기지 말고 위 출력에서 뽑는다.

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
MSHA=$(jq -r .manifest_sha256 /tmp/task18-snapshot-create.json)
echo "manifest_sha256 = $MSHA"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli snapshot verify \
  --snapshot-root "$BB2/.snapshots/2026-08-04/task18-final/task18-final" \
  --expected-manifest-sha256 "$MSHA"
```

Expected: `{"ok": true, "snapshot_id": "task18-final", ...}`

- [ ] **Step 3: 옛 스냅샷은 지우지 않는다**

`task17-final`은 라벨 교체 이전 상태로 되돌릴 유일한 수단이다. **그대로 둔다.**

```bash
ls -d /Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-04/*/
du -sh /Users/al03040455/Desktop/bb2_client/.snapshots/
```

커밋 없음 — `.snapshots/`는 git 밖이다.

---

### Task 15: ROADMAP에 완료를 기록한다 (엔진 커밋 ⑦)

**Files:**
- Modify: `$ENGINE/ROADMAP.md` ("완료 단계" 절, "진행 중" 절)

- [ ] **Step 1: 완료 항목을 쓴다**

`ROADMAP.md:377`의 `### Task 17 canonical ID 복구` 항목 **위에** 같은 형식으로 추가한다.

```markdown
### Task 18/19 표시 라벨 정리 + 인용문 부채 목록 — 복구 계획서 종료 (2026-08-04)

CodeLocator 표시 라벨을 정본 규약(`title = symbol`)에 맞추고, 인용문 없는 앵커의
부채 목록을 고정한 뒤 복구 계획서의 남은 뒷정리를 마쳤다.

- **라벨 교체**: 대상 3,305장, `title` 칸만. 엔진이 제목 외 변경을 계획 단계에서 거부하고
  적용 단계에서 살아 있는 코퍼스로 재계획해 바이트 일치를 요구한다. 제목 외 해시 전수 대조
  불일치 0. 색인은 재구축하지 않았다 — 라벨이 검색 표면에 없어 지문(`b6b3708f96…`)이 불변임을
  실측했고, 계획서의 근거 없는 rebuild 지시 두 곳을 삭제했다.
- **부채 목록**: 인용문 없는 앵커 3,307장 + 그중 심볼 형태 비정상 285장.
  코드 변경 판정은 캐시(368)가 아니라 `stale_check()` 직접 호출(371)을 썼다 —
  캐시는 차단 매핑이 없는 앵커 3건을 빠뜨린다. 조회 횟수 축은 엔진에 기록이 없어
  줄 범위 592 / 코드 변경 371 / 검수 전 252로 대체했다.
- **그림 라벨**: 심볼만 쓰면 한 글자에 노드 89개가 몰려, `앵커키 · 심볼끝마디`로 바꿔
  최악을 19개로 줄였다(`graph_viz.py`).
- **뒷정리**: 스킬 재설치(갱신 14개, 2회차 완전 무변화), 미커밋 가드와 근거 원문 커밋,
  낡은 스냅샷·연결점 값 정정. 영수증은 고치지 않고 새 세대를 얹었다.
- **최종 상태**: eval 15/15, 실코퍼스 checks 10(건너뜀 0), lint 0, `audit ok=true`,
  최종 스냅샷 `<Task 14 manifest_sha256>`(`<file_count>` 파일) 검증 통과.
  engine `<엔진 HEAD>`, BB2 `<BB2 HEAD>`.
- **남긴 것**: 회상 회귀 1건과 앵커/근거 카드 짝 라벨 3,186쌍은 아래 미뤄둔 작업 9·10번.
- 설계: [Task 18 설계](docs/superpowers/specs/2026-08-04-task18-display-labels-and-quote-backlog-design.md) ·
  계획: [Task 18 실행 계획](docs/superpowers/plans/2026-08-04-task18-display-labels-and-quote-backlog.md)
```

`<…>` 자리를 전부 실측값으로 채운다. **하나라도 자리표시자가 남으면 안 된다.**

- [ ] **Step 2: "진행 중" 절을 갱신한다**

`ROADMAP.md:36-43`의 "진행 중인 항목이 없다…" 문단에서 다음에 손댈 후보를 갱신한다 —
7번·8번에 더해 **9번(회상 회귀, 착수 트리거가 "지금")**을 앞세운다.

- [ ] **Step 3: 자리표시자가 없는지 확인한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
grep -n "TBD\|TODO\|<Task \|<엔진 HEAD>\|<BB2 HEAD>\|<file_count>" "$ENGINE/ROADMAP.md" \
  || echo "자리표시자 없음"
```

Expected: `자리표시자 없음`

- [ ] **Step 4: 커밋한다 (엔진 커밋 ⑦)**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
git -C "$ENGINE" add ROADMAP.md
git -C "$ENGINE" diff --cached --name-only
git -C "$ENGINE" commit -m "docs(brain): record task 18 display label migration"
git -C "$ENGINE" status --porcelain | grep -cv '^??'
```

Expected: staged 파일이 `ROADMAP.md` 하나. 마지막 명령이 `0`.

- [ ] **Step 5: 최종 상태를 보고한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain
BB2=/Users/al03040455/Desktop/bb2_client
echo "engine HEAD $(git -C "$ENGINE" rev-parse HEAD)"
git -C "$ENGINE" log --oneline -3
echo "bb2 HEAD    $(git -C "$BB2" rev-parse HEAD)"
git -C "$BB2" log --oneline -6
git -C "$BB2" status --porcelain | wc -l
git -C "$ENGINE" rev-list --left-right --count origin/main...main
git -C "$BB2" rev-list --left-right --count origin/docs/bb2-brain-object-model...HEAD
```

사용자에게 인계할 것 — 양쪽 HEAD, 커밋 7개 목록, 남은 사용자 변경 12건, 최종 스냅샷 ID와 해시,
그리고 **아직 결정 대기인 두 가지**: push 여부, 복구 번들 12개 공유 방식.

`push`·`merge`·`uv tool install -e`는 **하지 않는다.**

---

## 실행 중 멈춰야 하는 신호

| 신호 | 뜻 | 할 일 |
|---|---|---|
| Task 1의 값이 하나라도 다름 | 누가 코퍼스나 레포를 건드렸다 | 진행 중단, 원인 보고 |
| `snapshot_*_mismatch` | 같은 원인 | 되돌리려 하지 말고 보고 |
| `display_payload_changed` | 제목 외 칸이 바뀌려 한다 | 엔진이 막은 것. 입력을 다시 본다 |
| `manifest_revalidation_failed` | plan 이후 코퍼스가 바뀌었다 | plan부터 다시 |
| 제목 외 해시 불일치 > 0 | 마이그레이션이 다른 칸을 건드렸다 | `git checkout -- brain/objects/code`로 되돌림 |
| installer `skipped`가 비어 있지 않음 | 누가 관리 파일을 손댔다 | `--force` 금지. 차이를 먼저 조정 |
| BB2 남은 변경이 12건 미만 | 남의 변경을 커밋했다 | 어느 커밋인지 찾아 되돌림 |
| staged 목록에 `.agents/skills/guardrails` | 범위를 넘었다 | `git restore --staged` 후 다시 |
