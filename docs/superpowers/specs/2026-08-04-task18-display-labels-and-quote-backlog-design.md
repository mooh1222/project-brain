# Task 18 표시 라벨 정리 + 인용문 부채 목록 — 설계

**작성일**: 2026-08-04
**대상 계획**: `docs/superpowers/plans/2026-07-28-brain-ingest-recovery.md` Task 18, Task 19 잔여분
**선행 상태**: Task 0~17 완료. Task 18 미착수, Task 19 부분 완료.
**개정**: 적대 검토 2회 반영 (1차 33건 — 블로커 3 / 2차 16건 — 블로커 2)

---

## 1. 목표

두 가지를 끝내고 복구 계획서를 닫는다.

1. **표시 라벨 정리** — CodeLocator 3,305장의 `title` 칸을 정본 규약(`title = symbol`)에 맞춘다.
2. **인용문 부채 목록** — 코드 원문 인용이 없는 앵커 3,307장을 목록으로 고정한다. 채워 넣지는 않는다.

여기에 Task 19의 남은 조각(스킬 재설치, 미커밋 2건 커밋, 최종 검증, 낡은 값 정정, 최종 스냅샷)과,
이번 조사에서 새로 드러난 두 건의 처리를 포함한다.

## 2. 고정 기준 (2026-08-04 실측)

착수 직전에 다시 재고, 다르면 진행하지 않고 원인을 먼저 기록한다.
**예외**: 엔진 미추적 문서 수는 이번 작업이 만드는 설계·계획 문서만큼 늘어나는 것이 정상이며
착수를 막지 않는다.

| 항목 | 값 |
|---|---|
| BB2 HEAD | `f00f448a2c4955ccf7e2d02f2a4db01c1a3865a5` (`docs/bb2-brain-object-model`, origin 대비 ahead 6) |
| BB2 `origin/develop` | `a6add8d7791a37a282d7af9e13a1b29fc1581e2c` — **코드 변경 판정의 비교 기준** |
| 엔진 HEAD | `76827c3fe3e09104e657db515e0b21a37eb55b18` (`main`, origin 대비 ahead 84) |
| 코퍼스 지문 (mutation) | `0e9a2d52c387a8c51b73635bf60de690e20110f59a70135d3865a1e2a5926f7c` |
| 색인 지문 (search_index) | `b6b3708f963dec1b382ef6cd7d03b8e7a4dfdb7b48b8510d3051e0daffa1734f` — 지금 신선함 |
| 신뢰 스냅샷 | `bb2_client/.snapshots/2026-08-04/task17-final/task17-final/` (폴더가 한 겹 더 들어간다), manifest `d4ac0ddf5124…`, 11,132 파일, verify PASS |
| Task 18 연결점 | `.snapshots/2026-08-04/task17-final/task18-binding.json`, sha `a27aa26e238c…`, 키 13개, `task18_allowed: true` |
| 전체 객체 | 10,941 |
| CodeLocator | 3,809 |
| 라벨 교체 대상 `T` (`title != canonical`) | **3,305** |
| 인용문 없음 `Q` | **3,307** (`T`와 겹치지 않는 항목 7개) |
| 심볼 형태 비정상 `B` | **289** (전체 기준) |
| `B∩T` 교체 대상 중 비정상 | **279** |
| `B∩Q` 부채 목록 중 비정상 | **285** ← `symbol_backlog`의 기대값 |
| 교체 대상 중 제목에 한국어가 든 것 | **859** (26%) |
| `B∩T` 279장 중 제목에 한국어가 든 것 | **214** (77%) |
| 앵커와 이어진 EvidenceRef 쌍 | 3,202 — 지금 제목 같은 쌍 **2,720**, 이미 어긋난 쌍 482 |
| `Q` 중 코드 변경(stale) — 앵커 단위 | **371** (캐시 `stale-set.json`은 368만 담음) |
| `Q` 중 줄 범위 잔존 | 592 |
| `Q` 중 미머지 앵커 | 34 |
| `Q` 중 `status = candidate` | 252 |
| BB2 미커밋 | 13건 (brain 아래는 `brain/checks/test_real_corpus.py` 하나) |
| 엔진 미커밋 | 미추적 문서 9개 + 이번 작업 산출물 (전부 보존 대상, **커밋 금지**). 추적 파일 수정은 0건 — S3·S4가 만드는 것이 처음이다 |

> **연결점의 더트 지문은 엔진 쪽 두 개만 어긋나 있다.** 이 설계 문서가 엔진 미추적 파일로
> 생기면서 `source_checkout_status_sha256`·`source_checkout_content_sha256`이 변했다.
> **엔진이 강제하는 조건이 아니다** — `trusted_migration_context`는 HEAD 두 개와 코퍼스 지문만
> 본다(`migration.py:154-200`, `204-214`). **지문을 맞추려고 미추적 문서를 커밋하거나 지우지 마라.**
>
> **반면 `bb2_user_dirt_status_sha256`·`bb2_user_dirt_content_sha256`과 `index_fingerprint`·
> `stale_fingerprint` 네 개는 지금도 정확히 일치한다.** 착수 직전 재측정에서 이 넷 중 하나라도
> 어긋나면 **멈추고 원인을 찾는다** — 사용자 변경이 유실됐거나 코퍼스가 건드려졌다는 신호다.

## 3. 순서와 커밋

```
S1-0  교체 전 제목 뜨기 (pre-titles.json)
S1    라벨 교체 3,305장            ← 시한 있음. 반드시 먼저
S1c   BB2 커밋 ①  라벨 + display-migration 산출물
────────────────────────────────── 이 지점 이후 커밋 제약 없음
S2    인용문 부채 목록 2종
S2c   BB2 커밋 ②  부채 목록 + 생성기 + 테스트
S3    그림 라벨 개선 (엔진 워킹트리만 수정. 커밋은 S4-6에서)
S4-1  스킬 재설치        → BB2 커밋 ③
S4-2  미커밋 2건         → BB2 커밋 ④
S4-3  낡은 값 정정 (엔진 문서 + BB2 README + 새 영수증)
S4-4  계획서 정정 + ROADMAP 미뤄둔 작업 2건 등재
S4-5  엔진 게이트(§6.3) → 엔진 커밋 ⑤  graph_viz + 테스트 + 문서 정정·등재
S4-6  최종 검증          → BB2 커밋 ⑥  final-verification.json
S4-7  최종 스냅샷 (audit **뒤에**)
S4-8  ROADMAP 완료 기록  → 엔진 커밋 ⑦  Task 18/19 완료 항목 + 최종 스냅샷 값
```

커밋은 **BB2 5회 + 엔진 2회 = 7회.** 엔진을 둘로 나눈 이유는, ROADMAP 완료 기록에 최종
스냅샷 sha와 게이트 결과가 들어가야 하는데 그 값이 S4-7에서야 나오기 때문이다.

**S1만 시한에 묶여 있다.** `plan_display_migration`은 `trusted_migration_context`로
세 조건을 강제한다(`migration.py:154-200`, `204-214`).

- 현재 BB2 HEAD == 스냅샷 `repo_head`
- 현재 엔진 HEAD == 스냅샷 `engine_head` == `--engine-sha`
- 현재 코퍼스 지문 == 스냅샷 `corpus_fingerprint`

즉 **어느 레포든 새 커밋을 얹거나 코퍼스를 건드리면 스냅샷을 다시 떠야 한다.**
`push`는 HEAD를 바꾸지 않으므로 안전하다. 워킹트리 수정도 HEAD를 안 바꾸므로 S3의 엔진 수정은
S1 이후라면 언제 해도 무방하다. S1이 끝나면 코퍼스 지문이 바뀌어 이 연결점은 소임을 다한다.

## 4. 산출물 경로

계획서는 전부 `brain/recovery/2026-07-28/…`로 적었으나, **실행일 기준 날짜 폴더**를 쓴다
(`2026-08-03/task17-migration/` 선례와 같은 규칙). 계획서와 경로가 다르다는 사실을 S4-4에서
계획서에 반영한다. 각 폴더는 **실행 전에 `mkdir -p`로 만든다.**

| 파일 | 경로 (`bb2_client/` 기준) | 만드는 단계 |
|---|---|---|
| 교체 전 제목 | `brain/recovery/2026-08-04/display-migration/pre-titles.json` | S1-0 |
| 마이그레이션 manifest | `brain/recovery/2026-08-04/display-migration/display-migration.manifest.json` | S1 |
| plan 표준출력 | `brain/recovery/2026-08-04/display-migration/plan-report.json` | S1 |
| apply 표준출력 | `brain/recovery/2026-08-04/display-migration/apply-report.json` | S1 |
| S1 검증 결과 | `brain/recovery/2026-08-04/display-migration/display-gate-report.json` | S1 |
| 부채 목록 | `brain/recovery/2026-08-04/display-migration/legacy-quote-backlog.json` | S2 |
| 부채 목록 생성기 | `brain/recovery/2026-08-04/display-migration/build_quote_backlog.py` (+ `test_build_quote_backlog.py`) | S2 |
| installer 1·2회차 | `brain/recovery/2026-08-04/installer/install-first.json`, `install-second.json` | S4-1 |
| 최종 검증 | `brain/recovery/2026-08-04/final-verification.json` | S4-6 |

부채 목록을 계획서의 `brain/recovery/<date>/legacy-quote-backlog.json`이 아니라
`display-migration/` 안에 두는 이유는 S2 산출물 세 개를 한 폴더로 모아 스테이징 실수를 줄이기
위함이다. 이것도 S4-4에서 계획서에 반영한다.

> `display-gate-report.json`은 Task 15/16이 만든 맥락별 `gate-report.json`
> (`brain/recovery/2026-07-28/{petskill-kamehameha,ingame-item-usage}/gate-report.json`)과
> **다른 파일이다.** 이름을 겹치지 않게 지었다.

## 5. 구성요소

### S1 — 라벨 교체

**입력**: 기존 `task17-final` 스냅샷 (새로 뜨지 않는다. 지금 상태와 정확히 일치하고 verify 통과)
**대상**: `kind == "CodeLocator"` 이면서 `title != _canonical_locator_title(obj)` 인 3,305장
**바뀌는 것**: `title` 칸 하나

정본 라벨 규칙은 심볼이 비어 있지 않으면 `title = symbol`, 비었으면 `basename(path):anchor_key`다
(`migration.py:774-786`). BB2에는 심볼 없는 앵커가 0장이라 폴백 경로는 안 탄다.

**S1-0 (선행, 필수) — 교체 전 제목을 뜬다.**

```
pre-titles.json = { "<locator_id>": "<현재 title>", ... }   3,305개 항목
```

교체 대상 3,305장 중 **859장(26%)은 제목에 한국어가 들어 있다.** 사람이 쓴 설명과, 코드 원문·
주석을 그대로 복사한 것이 섞여 있다(예: `case kMeteor: return "운석";`,
`// +, - 방해버블은 볼터진후 한번에 몰아서 sum값을 UI에 표현해 줘야 한다.`).
심볼이 비정상인 279장 중에서는 **214장(77%)**이 그렇다. 마이그레이션이 덮어쓰면 커밋 이력이나
스냅샷을 뒤지지 않는 한 읽을 수 없으므로, S2 부채 목록이 `previous_title`로 담아 나중에
인용문을 복원하거나 카드를 쪼갤 때 실마리로 쓴다. **S1보다 반드시 먼저 실행한다.**

**279장을 제외하지 않는 이유**는 하나뿐이다 — 제외하려면 엔진 대상 선정 규칙을 고쳐야 하고,
제외한 279장은 계획을 돌릴 때마다 영원히 미완 대상으로 잡혀 "끝난 상태"가 없어진다.
정본 정책도 사람이 쓴 라벨을 금지한다(`assembly.py:63-77` — `title = symbol` 고정,
외부 입력 title을 받지 않는다).

**안전장치는 엔진에 이미 있다.**

- 제목 외 칸이 하나라도 바뀌면 계획 단계에서 `display_payload_changed`로 거부한다
  (`migration.py:789-794`, `841-847`).
- `apply`는 넘겨받은 manifest를 믿지 않고 살아 있는 코퍼스로 다시 계획해
  바이트가 같아야만 통과한다 (`migration.py:990-1002`).
- 좌표 칸(`repo/path/commit_sha/symbol/verified_quote`, `mutation.py:48-54`)이 그대로라
  인용문·심볼 재검증 경로를 안 탄다(`mutation.py:411-418`). 축약 커밋 해시 벽
  (ROADMAP 미뤄둔 8번)에 걸리지 않는다.

**색인은 다시 만들지 않는다.** CodeLocator의 검색 표면은 `path`와 `symbol` 둘뿐이라
`title`이 안 들어가고(`surface.py:129-137`), 색인 신선도 지문 재료에도 없다
(`search_index.py:414-442`). 실측으로 3,305장 제목을 메모리에서 전부 바꿔도 색인 지문이
`b6b3708f96…` 그대로임을 확인했다. 계획서 Task 18 Step 3과 Task 19 Step 3의 `index rebuild`를
둘 다 삭제한다(S4-4).

> **지문 두 종류를 섞지 말 것.**
> 색인 신선도 지문(`search_index.compute_corpus_fingerprint`, 표면 기반) — **안 바뀐다.**
> 마이그레이션 사전조건 지문(`mutation.corpus_fingerprint`, 객체 바이트 전체) — **바뀐다.**
> 후자의 예상 적용 후 값은 `8d71e3ce45e5a72c…`이며 **스냅샷과 plan 사이에 다른 쓰기가 끼면
> 무효다.** 확정 검증은 manifest의 `expected_after_fingerprint`와 적용 후 실측값 대조로 한다.

**짝 EvidenceRef는 이번 범위 밖이다.** 적재기는 앵커와 근거 카드에 같은 라벨을 넣는데
(`assembly.py:63-77`), 이 마이그레이션은 CodeLocator만 대상으로 잡는다. 앵커와 이어진 쌍은
3,202개이고 지금 제목이 같은 것이 2,720쌍인데, **그중 2,704쌍이 새로 어긋난다**(적용 후에도
제목이 같은 쌍은 16개만 남는다). 이미 어긋나 있던 482쌍까지 합치면 **총 3,186쌍이 어긋난 채
남는다.** `plan_display_migration`을 EvidenceRef까지 확장하려면 엔진 변경이 필요하다.
S4-4에서 ROADMAP 미뤄둔 작업에 "앵커/근거 카드 짝 라벨 재동기화"로 등재한다.

**S1c — BB2 커밋 ①.**

```
git -C bb2_client add -f -- brain/objects/code
git -C bb2_client add -f -- brain/recovery/2026-08-04/display-migration
git -C bb2_client commit -m "fix(brain): normalize code locator display labels"
```

`brain/objects/code`는 3,809개 전부 추적 중이지만 `.git/info/exclude`에 `/brain`이 있어
디렉터리 pathspec에는 **`-f`가 필수다**(실측: `-f` 없이 dry-run하면 ignored로 거부된다).

`git add -A`·`git add .`·`git commit -a` **금지** — `brain/recovery/` 아래 미추적 13개
(Task 17 번들 12 + README)와 `.agents/skills/guardrails` 등 무관한 dirty가 딸려 들어간다.
스테이징 뒤 `git status --short`와 `git diff --cached --stat`으로 대상만 들었는지 확인한다.

### S2 — 인용문 부채 목록

`audit` 출력만으로는 만들 수 없다. audit의 앵커별 항목은 7개 상태축
(`locator_id / stale / code_quote / symbol_relation / quote_access / id_format / references`)뿐이고
**맥락 이름·파일 경로·심볼 문자열이 없다**(`audit.py:172-201`).

`build_quote_backlog.py` 한 개와 그 unittest를 만든다. 코퍼스를 `BrainStore`로 직접 읽고
(audit JSON을 입력으로 받지 않는다), JSON을 표준출력으로 내보낸다.

출력 최상위 키 세 개.

| 키 | 내용 | 기대 개수 |
|---|---|---:|
| `summary` | 모수·축별 집계·기준 파라미터·생성 시각 | — |
| `quote_backlog` | 인용문 없는 앵커 | **3,307** |
| `symbol_backlog` | 그중 심볼 형태 비정상 | **285** |

> 세 범위의 숫자를 혼동하지 말 것 — **전체 기준 289 / 부채 목록 기준 285 / 라벨 교체 대상 기준 279.**
> `symbol_backlog`는 부채 목록의 부분집합이므로 **285**다.

앵커별 필드:
`locator_id / context / path / symbol / symbol_state / previous_title / status / stale /
unmerged_anchor / affected_mapping_ids / has_line_range / locator_source / priority / reason`

`previous_title`은 S1-0이 뜬 `pre-titles.json`에서 읽는다. **그 파일에 없는 앵커가 정확히 7개**
있다(원래 `title == symbol`이던 504장 중 인용문 없는 것). 그 7개는 현재 `title`을 그대로 쓴다.
심볼이 빈 앵커가 0장이라 이 값이 비는 경우는 없다.

**코드 변경(stale) 판정은 캐시가 아니라 `stale_check()` 직접 호출로 한다.**
캐시(`stale-set.json`)는 매핑 단위로 압축돼 있어 차단 매핑이 없는 앵커가 빠진다
(`stale_check.py:186-191`, `230-237`). 실측 차이는 캐시 368 대 앵커 단위 371이고,
빠진 3건은 전부 인용문 없는 앵커다.

호출 파라미터를 고정하고 `summary`에 기록한다.

```
target_head    = a6add8d7791a37a282d7af9e13a1b29fc1581e2c   ← origin/develop 의 sha
default_branch = develop
fetch          = False        (네트워크 접근 없음)
git_runner     = repo_root 기준
```

> **`target_head`는 BB2 HEAD가 아니다.** 엔진의 비교 기준은 항상 `origin/<기본브랜치>`이고
> (`stale_check.py:100-107`, `122-131`), 살아 있는 캐시의 `target_head`도 같은 값이다.
> BB2 HEAD(`f00f448a2c`, brain 문서 브랜치)를 넣으면 stale이 371이 아니라 **236**, 미머지가
> 34가 아니라 **37**로 나와 기대값이 재현되지 않는다.
> `origin/develop`은 로컬 커밋으로 움직이지 않으므로 **fetch만 하지 않으면 S1c 커밋 전후로
> 값이 고정된다** — S2가 S1c 뒤에 도는 것은 문제가 되지 않는다.

git 호출이 들어가 20~25초쯤 걸린다.

**우선순위는 계획서와 다르게 간다.** 계획서 2순위 "자주 조회되는 핵심 context"에 필요한
조회 횟수는 **엔진에 기록하는 코드 자체가 없다**(넓은 grep 0건). 실제로 순위가 갈리는 축으로
대체한다.

1. **줄 범위가 남아 있는 592장** — 옛 좌표가 있어 인용문 복원이 가장 쉽다
2. **코드가 변한 371장** — mark-checked가 필요하다
3. **`status = candidate` 252장** — 아직 검수 전
4. 맥락별 인용문 없는 앵커 수 상위 (ball-select 131, main-map 122, sally-canoe 112 …)

`priority`는 위 축의 조합으로 정하고, `reason`에 어느 축에 걸렸는지 문자열로 남긴다.

**심볼 형태 판정 기준**: `symbol_verify._SIMPLE_IDENTIFIER`(`~?[A-Za-z_][A-Za-z0-9_]*`)를
`"::"`로 쪼갠 조각마다 fullmatch. 이건 **어휘 판정**이고 엔진 자체 판정과 다르다
(엔진은 미지원 확장자를 `UNSUPPORTED`로 빼고 `operator*` 계열도 예외로 둔다).

**unittest가 고정할 것** (`test_build_quote_backlog.py`):

- 심볼 형태 판정 경계 — `~Foo`(소멸자) 통과, `A::B::C` 통과, 공백·슬래시·한글·쉼표 포함 거부,
  빈 문자열 처리
- stale 판정이 캐시가 아니라 주입한 `stale_check` 결과를 쓰는지 (가짜 리포트 주입)
- `previous_title`이 `pre-titles.json`에 있으면 그 값을, 없으면 현재 title을 쓰는지
- `symbol_backlog ⊆ quote_backlog` 불변식
- `summary`의 집계가 각 배열 길이와 일치하는지
- 우선순위 축 결정 로직 (같은 앵커가 여러 축에 걸릴 때의 순서)

**S2c — BB2 커밋 ②.**

```
git -C bb2_client add -f -- \
  brain/recovery/2026-08-04/display-migration/legacy-quote-backlog.json \
  brain/recovery/2026-08-04/display-migration/build_quote_backlog.py \
  brain/recovery/2026-08-04/display-migration/test_build_quote_backlog.py
git -C bb2_client commit -m "docs(brain): record legacy quote backlog"
```

Task 17 번들(`run_migration.py` 등)은 공유 방식 미정으로 미추적으로 남아 있다.
**이번 산출물은 커밋한다** — 부채 목록은 앞으로 계속 참조할 기준이라 사라지면 안 된다.

### S3 — 그림 라벨 개선 (엔진)

라벨 교체 뒤 `graph export` 그림에서 노드 글자가 더 많이 겹친다. 30자 절단 기준 실측:

| 라벨 방식 | 서로 다른 글자 | 겹치는 카드 | 최악 |
|---|---:|---:|---:|
| 지금 (`title`) | 2,819종 | 1,394장 | 89장 |
| 교체 후 (`symbol`) | 1,776종 | 2,604장 | 89장 |
| `id` 꼬리 (`맥락.앵커키`) | 1,126종 | 3,409장 | 86장 |
| **`앵커키 · 심볼끝마디`** | **2,747종** | **1,356장** | **19장** |

`id` 꼬리는 맥락 이름이 30자 예산을 먹어 오히려 나쁘다. 채택안은 **`앵커키 · 심볼끝마디`**로,
지금보다 최악 사례가 89장 → 19장으로 줄어든다.

**변경 범위**: `src/project_brain/graph_viz.py`

- CodeLocator에 한해 라벨을 `f"{anchor_key} · {symbol.split('::')[-1]}"`로 만든다.
  **`anchor_key`는 객체 필드가 아니다** — `str(o["id"]).rsplit(".", 1)[-1]`로 파생한다
  (`migration.py:785-786`과 같은 규칙). 다른 kind는 기존 `LABEL_FIELDS` 순서를 그대로 쓴다.
- **symbol이 빈 CodeLocator 폴백**: 정본 규칙과 맞춰 `f"{basename(path)}:{anchor_key}"`를 쓴다.
  BB2에는 0장이지만 `graph_viz.py`는 엔진 공통 코드다.
- **툴팁**: 현재 본문은 `next()`로 후보 중 **한 칸만** 고른다(`graph_viz.py:54`).
  `TIP_FIELDS`에 추가하는 것만으로는 symbol 하나만 뜨고 path는 안 나온다.
  CodeLocator일 때 툴팁 조립 자체를 바꿔 `symbol`과 `path` 두 줄을 모두 붙인다.
- 상세 패널은 이미 `id`를 포함한 전 필드를 찍으므로(`graph_viz.py:189-200`) 손대지 않는다.

**red 테스트** (`tests/test_graph_viz.py`) — fixture 조건을 명시한다.

> **S1 적용 후 상태를 흉내내 두 CodeLocator 모두 `title == symbol`로 두고, id의 앵커 키만
> 다르게 한다.** 이때 현재 코드는 두 노드 라벨이 같아 실패한다. fixture의 title을 서로 다르게
> 두면 현재 코드도 통과해버려 red가 되지 않는다(`graph_viz.py:28` — `LABEL_FIELDS`가 title을
> 1순위로 쓴다).

red 확인: `.venv/bin/python -m pytest tests/test_graph_viz.py -q` → 신규 테스트 실패.
고정할 것 — 같은 심볼·다른 앵커키면 라벨이 다르다 / 툴팁에 symbol과 path가 **둘 다** 들어간다 /
symbol이 비면 `basename:anchor_key` 폴백 / 다른 kind의 라벨은 변하지 않는다.

**이 단계는 워킹트리만 고친다. 커밋은 S4-5에서 한 번에 한다.**

### S4 — Task 19 잔여

**S4-1 스킬 재설치 → BB2 커밋 ③.** 계획서는 워크트리로 하라고 했으나 그 워크트리는
`1742c09`에 멈춰 있고 정본은 메인 클론 `main`이다. **메인 클론으로 실행한다.** 글로벌 편집 설치
(`_editable_impl_project_brain.pth`)가 이미 메인 클론 `src`를 가리키므로 uv tool 설치본을
다시 만들 필요가 없다.

```
mkdir -p /Users/al03040455/Desktop/bb2_client/brain/recovery/2026-08-04/installer
PYTHONPATH=<engine>/src <engine>/.venv/bin/python -m project_brain.cli install \
  --target /Users/al03040455/Desktop/bb2_client \
  --project bb2 --brain-root brain --default-branch develop --repo bb2_client \
  > /Users/al03040455/Desktop/bb2_client/brain/recovery/2026-08-04/installer/install-first.json
```

읽기 전용 예측: **1회차 `updated` 14개, `created`/`removed`/`adopted`/`skipped` 전부 0개,
config는 `kept`. 2회차는 다섯 배열 모두 빈 배열.** 관리 대상 23개 파일의 manifest 기록 해시가
디스크와 23/23 일치해 "사용자 수정"으로 걸릴 파일이 없다. `.agents/skills/guardrails`·
`agents-doctor` 등 BB2 자체 스킬은 관리 범위 밖이라 안 건드린다(`_safe_managed_path`).

규모: `run_ingest_batch.py` **+1128/−137**, `finalize_ingest.py` +293/−10,
14개 파일 합계 **+1621/−201**. 적재 런타임이 사실상 교체된다.
**진행 중인 적재 배치가 없는 시점에 돌린다.**
`--force` 금지(지금 해시가 전부 일치해 불필요하고, 켜면 이후 누가 손댄 파일까지 조용히 덮는다).
`bootstrap` 서브커맨드 금지(뒤에 색인 재구축이 붙는다).

설치 전에 `src/project_brain/templates/ingest/references/ingest-tools.md`의 예시 명령이
현재 CLI 필수 인자(`--repo-root`/`--expected-repo-id`/`--expected-revision-ref`/`--engine-sha`)를
반영하는지 확인하고, 어긋나면 먼저 고쳐 한 번에 반영한다. **고쳤으면 그 파일은 엔진 추적
파일이므로 S4-5 엔진 커밋 목록에 반드시 넣는다.**

2회차를 돌려 `install-second.json`을 남긴 뒤 커밋한다. **보고서의 경로는 절대경로다.**

```
jq -r '(.created + .updated)[]' <install-first.json> \
  | xargs -I{} git -C /Users/al03040455/Desktop/bb2_client add -- {}
git -C bb2_client add -- .project-brain-manifest.json
git -C bb2_client add -f -- brain/recovery/2026-08-04/installer
git -C bb2_client commit -m "chore(brain): install recovered skill contracts"
```

관리 파일 14개는 `.agents/skills/` 아래라 `-f`가 **불필요**하고, `.project-brain-manifest.json`은
exclude에 있지만 추적 중이라 역시 불필요하다(실측 확인). `brain/` 아래만 `-f`가 필요하다.
`.agents/skills/guardrails`·`agents-doctor` 등 다른 dirty가 staged되면 커밋하지 않는다.

**S4-2 미커밋 2건 → BB2 커밋 ④.** 한 커밋으로 묶는다.

```
git -C bb2_client add -f -- \
  brain/checks/test_real_corpus.py \
  brain/raw/sources/petskill-kamehameha/spec-v1.1.md
git -C bb2_client commit -m "fix(brain): commit raw chunk guard and its source"
```

상수 `EXPECTED_RAW_CHUNKS` 1577 → 1586과 그 +9의 근거 원문은 짝이다. 원문 없이 상수만
커밋하면 다음 사람이 왜 1586인지 알 수 없다. **`-f` 필수**, 정확한 두 경로만 지정한다.

**S4-3 낡은 값 정정.**

| 대상 | 내용 | 방식 |
|---|---|---|
| `ROADMAP.md:403-404` | 스냅샷 `ad657ec5…`→`d4ac0ddf…`, 연결점 `135ce054…`→`a27aa26e…`, engine `148c9e7d`→`76827c3` | 제자리 수정 + 경위 한 줄 |
| `docs/plans/2026-08-04-symbol-verify-body-scope-and-task13.md:133, :151, :561-562` | 같은 값들. `:151`은 "148c9e7d로 찍었다"를 "최종본은 76827c3로 다시 찍었다(148c9e7d는 그 전 판)"로 | 제자리 수정 |
| `bb2_client/brain/recovery/README.md` | "남은 문제 (2026-08-04 기준)" 절이 audit 미통과라고 적고 있으나 지금은 통과 | 제자리 수정 (**미추적이라 되돌리기 불가 — 수정 전 사본 확보**) |
| `~/.project-brain-task17-receipts-…/task17-complete-2026-08-04.json` | `engine_sha_note`와 `deviations_from_plan[2]`가 `148c9e7d`를 담고 있다 | **제자리 수정 금지.** 아래 참조 |

> **완료된 영수증은 고치지 않는다.** 이 폴더의 관행은 새 세대를 덧붙이는 것이다 —
> `final-snapshot-create.json` / `-2026-08-04.json` / `-2026-08-04-post-fix.json` 세 파일이
> 나란히 있고, `task9-snapshot-drift-pre-move.json`/`-post-move.json`도 짝 구조다.
> 새 영수증 `task17-complete-2026-08-04-engine-sha-correction.json`을 추가해 이전 파일의
> `engine_sha_note`가 스냅샷 재촬영 뒤 무효가 됐음을 적고 `related_receipts`로 잇는다.
> **`deviations_from_plan`은 어떤 경우에도 수정하지 않는다** — 실제로 일어난 계획 이탈 기록이다.

**S4-4 계획서 정정 + ROADMAP 등재.** `docs/superpowers/plans/2026-07-28-brain-ingest-recovery.md`

1. Task 18 Step 3 (1599-1601행) `index를 재생성한다` **삭제** — 근거 없음 (S1 참조)
2. Task 19 Step 3 (1709-1710행) `cli index rebuild` 명령줄 **삭제** — 같은 이유
3. Task 19 명령의 워크트리 경로(1635, 1658, 1704, 1742-1745행)를 메인 클론으로 교체
4. Task 19 Step 4 (1732행) "광선발사 create 파일이 Git tracked" 문구 수정 — 해당 manifest의
   `creates`는 0이고 실제 산출물은 `updates` 299 + `renames` 3 = 302개다. 지금 문구는
   "creates 0이니 통과"라는 공허한 초록을 낸다
5. Task 19 Step 4 (1729행) `verified_at`이 엔진 검증 사건에서 생성 — **조건 삭제.**
   저장된 객체에 생성 주체 표시가 없어 사후 증명 수단이 없다. 정황만 기록으로 남긴다
6. Task 18 Step 1·4 (1584-1586, 1605-1612행) 산출물 경로(§4 표)와 우선순위 축을 이 설계에 맞춰 갱신

**ROADMAP 미뤄둔 작업 2건 등재:**

- **검색 회귀** — S5 참조
- **앵커/근거 카드 짝 라벨 재동기화** — S1이 CodeLocator만 바꿔 3,186쌍이 어긋난 채 남는다
  (그중 2,704쌍이 이번에 새로 어긋난 것). 착수 조건: `plan_display_migration`을 EvidenceRef까지
  확장하는 엔진 변경이 정당화될 때

**S4-5 엔진 게이트 → 엔진 커밋 ⑤.** §6.3의 세 게이트를 통과시킨 뒤 커밋한다.

```
git -C project-brain add \
  src/project_brain/graph_viz.py tests/test_graph_viz.py \
  ROADMAP.md docs/plans/2026-08-04-symbol-verify-body-scope-and-task13.md
# S4-1에서 고쳤으면 함께:
#   src/project_brain/templates/ingest/references/ingest-tools.md
git -C project-brain commit -m "fix(brain): disambiguate code locator graph labels"
```

**`git add -A`·`git add .`·`git commit -a` 금지** — 보존 대상 미추적 문서가 통째로 딸려 들어간다.
계획서(`docs/superpowers/plans/2026-07-28-…`)와 이 설계 문서·실행 계획서는
**미추적 보존 대상이므로 stage하지 않는다.**

**S4-6 최종 검증 → BB2 커밋 ⑥.** §6.4의 게이트를 돌려 `final-verification.json`에 담는다.

```
git -C bb2_client add -f -- brain/recovery/2026-08-04/final-verification.json
git -C bb2_client commit -m "docs(brain): record ingest recovery verification"
```

**S4-7 최종 스냅샷.** `audit`을 전체로 돌린 **뒤에** 뜬다.
`audit`은 읽기 전용이 아니라 `brain/.brain-local/stale-set.json`을 덮어쓴다
(`audit.py:218-223`). 스냅샷을 audit보다 먼저 뜨면 stale 지문이 어긋난다.
중간 점검은 `--no-stale`로만 한다.

**S4-8 ROADMAP 완료 기록 → 엔진 커밋 ⑦.** `ROADMAP.md`에 Task 18/19 완료 항목을 추가한다 —
최종 스냅샷 sha·파일 수, 게이트 결과, 라벨 교체 3,305장, 부채 목록 3,307/285.
`ROADMAP.md:377`의 Task 17 항목과 같은 형식으로 쓴다.

### S5 — 검색 회귀 등재

이번 조사에서 계획서 조건 밖의 실제 회귀 1건을 찾았다. **이번 범위에서 고치지 않고
`ROADMAP.md` 미뤄둔 작업에 항목으로 등재한다**(S4-4).

```
질문   "아이템 버튼이 눌리지 않는 이유"
기대   mapping.ingame-item-usage.item-button-ready-touch-axis
실제   ledger.ingame-area-expansion.{android-fixed-width, final-boss-exception,
       top-safe-area, visible-row-unified, whole-row-foundation}
       + ledger.sally-canoe.event-end-popup-exclude
증상   질문 의도를 why_changed 로 판정 (status: reviewed, candidate 0건)
경위   Task 16 검증 시점에는 통과. 그 사이 Task 17(이름 158개 변경 + 참조 71곳 갱신)이
       있었으나 인과는 미확정
재현   cd bb2_client && PYTHONPATH=<engine>/src <engine>/.venv/bin/python \
       -m project_brain.cli query "아이템 버튼이 눌리지 않는 이유"
```

같은 항목에 광선발사 gate 기준 이탈 1건도 함께 적는다 — 대상 질의 5개 중 `pop-entry-flow`
이탈, `disturb-electric-bomb` 유입.

착수 조건: **Task 19 뒷정리 완료 직후.** 원인이 라우팅(질문 의도 판정) 쪽이라 별개 조사가 필요하다.

## 6. 검증 게이트

### 6.1 S1 적용 직후

| 항목 | 명령 / 기대값 |
|---|---|
| plan 규모 | plan 표준출력의 `action_count == 3305`, `row_count == 0`. manifest의 `creates`/`deletes`/`renames`/`auxiliary_updates` 전부 0 |
| 지문 일치 | `jq -r .expected_after_fingerprint <manifest>` == 적용 후 `corpus_fingerprint(BrainStore.load(brain_root))` |
| 제목 외 불변 | **적용 전 바이트는 `git -C bb2_client show HEAD:brain/objects/code/<id>.json`에서 얻는다** (3,809개 전부 추적 중이고 지금 수정 0·미추적 0이라 HEAD가 정확한 적용 전 상태다). 그 바이트와 적용 후 바이트에서 각각 `title`을 뺀 sha256이 3,305장 **전부** 동일 |
| 객체 수 | 10,941 불변 |
| lint | 문제 0, 끊긴 참조 0 |
| 색인 신선도 | `read_meta_fingerprint(index.db)` == `compute_corpus_fingerprint(store, brain_root)` == `b6b3708f96…` — **rebuild 없이 일치해야 한다.** 불일치할 때만 rebuild (인자 두 개다 — `search_index.py:414`) |
| 표본 확인 | `git diff --stat -- brain/objects/code`에서 표본 20장이 파일당 1줄 변경인지 |

> `audit --no-stale`의 `code_quote` 분포 대조는 **게이트로 쓰지 않는다.** `code_quote`는
> `verified_quote`가 비었는지만 보는 값이라(`audit.py:176-181`) title만 바꾸는 마이그레이션에서는
> 정의상 변할 수 없다. 통과가 보장된 검사는 아무것도 못 잡는다.

### 6.2 S2 산출물 게이트

`quote_backlog` 3,307 / `symbol_backlog` 285 / `summary.total_locators` 3,809 /
줄 범위 592 / stale 371 / candidate 252 / 미머지 34 / `symbol_backlog ⊆ quote_backlog` /
`previous_title`이 빈 항목 0 / `summary.target_head == a6add8d779…`.

### 6.3 엔진 게이트 (S4-5 엔진 커밋 직전)

프로젝트 규약(`AGENTS.md` 개발 루프)이 요구하는 것이다. 이 시점이면 S4-1의 템플릿 수정 여부가
이미 확정돼 세 번째 행의 조건을 평가할 수 있다.

| 항목 | 명령 | 기대 |
|---|---|---|
| 엔진 전체 테스트 | `.venv/bin/python -m pytest -q` | 실패 0 (기준선 1,522 + S3 신규분) |
| 적재 런타임 테스트 | `python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'` | 99개 통과 |
| 설치 테스트 | `pytest tests/test_installer.py -q` | S4-1에서 `ingest-tools.md`를 고쳤을 때만. 실패 0 |

### 6.4 최종 게이트 (S4-6)

계획서 Task 19 Step 4의 조건 11개를 아래처럼 조정해 `final-verification.json`에 담는다.

| 조건 | 확인 방법 | 기대값 |
|---|---|---|
| eval 시나리오별 유지 | `cli eval` 전체 stdout을 **파일로 받아** 파싱 (`tail`로 자르면 JSON이 깨진다) | 15/15 |
| 두 대상 query | **정본 기준선 = 인게임 `gate-report.json`.** 광선발사 gate의 `pop-entry-flow` 1건은 알려진 회귀로 S5에 등재하고, 이름·기대 ID·이탈 사유를 `known_failures`에 기록한 뒤 통과로 본다 | 인게임 3/3, known-failure 1건 |
| 두 무관 query | Task 16 영수증(`brain/recovery/2026-07-28/ingame-item-usage/gate-report.json`)에서 질문 문자열과 기대 상위 ID를 읽어 대조 | 기준선과 동일 |
| ID 위반 / 끊긴 참조 | `cli lint`, `cli audit` | 0 / 0 |
| 두 맥락 인용문·심볼 | **"전수"가 아니다.** 쪼개 적는다 | 기계 검증 483 / 사람 증거 19 / 미검사 3,307 / 실패 0 |
| `verified_at` 출처 | **게이트에서 제외** (S4-4 정정 5번). `notes`에 정황만 | 자정값 3,007 / 3,809 |
| second finalize no-op | 두 맥락 `context-replace plan`을 새 임시 manifest 경로로 실행. **기존 manifest를 덮어쓰지 않는다.** 판정은 stdout의 `creates`/`updates`/`deletes`/`renames`가 전부 0인지로 한다 | 액션 0. **manifest 해시를 사전 고정값으로 두지 않는다** — 해시 재료에 코퍼스 지문과 engine_sha가 들어가 S1·엔진 커밋 이후에는 정의상 값이 달라진다. 이번 실행에서 실측해 기록한다 |
| installer 2회차 no-op | `install-second.json` | 다섯 배열 전부 빈 배열 |
| 광선발사 산출물 tracked | 문구 수정 후 (S4-4 정정 4번) | `updates` 299 + `renames` 3 = 302개 전부 tracked |
| 사용자 dirty 보존 | 커밋 ①~⑥ 후 `git -C bb2_client status --short` | **남는 12건.** 지금 13건 중 S4-2가 `brain/checks/test_real_corpus.py` 하나만 커밋한다. 나머지 커밋 대상은 지금 깨끗해서 13건에 없다. 목록: `.agents/skills/agents-doctor` 3, `guardrails` 4 + 미추적 3, `Podfile.lock`, `tools/codesearch-eval/README.md` |
| 최종 스냅샷 | audit **뒤에** 생성(S4-7), verify PASS | 파일 수·manifest sha 기록 |

`brain/checks/test_ingest_recovery.py`는 **최종 근거로 쓰지 않는다.** 얼어붙은 gate-report
JSON만 읽는 영수증 검사라(`ENGINE_SHA=90c53a70…`, `REPO_SHA=a6add8d7…` 고정) 현재 코퍼스가
망가져도 계속 통과한다. `discover`로 10개를 다 돌리되 판정 근거는 나머지에 둔다.

## 7. 이번에 하지 않는 것

- 인용문 채워 넣기 — 목록만 만든다 (계획서가 전면 백필 금지)
- 심볼 문자열 교정 — 인용문이 선행 조건이고 해당 앵커는 전부 인용문이 없다
- 한 카드가 두 함수를 가리키는 구조 문제 해결
- **앵커/근거 카드 짝 라벨 재동기화** — S1 후 3,186쌍(3,202쌍 중)이 어긋난 채 남는다. ROADMAP 등재
- 검색 회귀 원인 규명 — S5로 분리 등재
- `push` — HEAD를 바꾸지 않아 S1과 무관하나, 사용자 결정 대기 항목
- 복구 번들 12개 공유 방식 — 사용자 결정 대기 항목
- 엔진 미추적 문서 커밋 — 보존 대상. **이 설계 문서와 실행 계획서도 포함**

## 8. 되돌리기

| 시점 | 방법 |
|---|---|
| S1 적용 도중 실패 | 엔진이 자동 롤백. roll-forward 코드는 없다 |
| S1 적용 후, S1c 커밋 전 | `git -C bb2_client checkout -- brain/objects/code` |
| S1c 커밋 후 | `snapshot restore` (`task17-final`, 11,132 파일) |
| S4-1 설치 후, 커밋 전 | `jq -r '(.created + .updated)[]' install-first.json`으로 경로를 뽑아 `git -C bb2_client checkout -- <그 경로들> .project-brain-manifest.json` |
| **S2 산출물·스크립트** | 신규 파일이라 되돌릴 원본이 없다. 지우면 끝 |
| **S4-3 `brain/recovery/README.md`** | **미추적이라 git 복원 불가.** 수정 전 사본을 작업 폴더에 떠둔다 |
| **S4-4 계획서** (미추적 보존 대상) | **git 복원 불가.** 같은 취급 |

`brain/recovery/` 아래 미추적 파일은 git으로 복원되지 않는다. 되돌리기 명령에 `brain/` 전체를
지정하지 않도록 경로를 정확히 쓴다.

## 9. 열린 항목 (사용자 결정 대기)

1. 엔진·BB2 push 여부
2. 복구 번들 12개 + README 공유 방식

> 최종 게이트의 "두 대상 query" 정본 기준선은 **인게임 gate로 이 문서에서 확정했다**(6.4 참조).
> 다르게 가려면 그 행만 바꾸면 된다.
