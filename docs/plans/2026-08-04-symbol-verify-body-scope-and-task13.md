# 2026-08-04 실행 계획 — 심볼 검증 몸통 규칙 + Task 13 마무리

작성 시점 상태: Task 17(잘못된 객체 이름 158개 고치기)의 본래 목표는 달성됐다.
BB2 커밋 `e28ff4ee7d`, 엔진 커밋 `3a91f866`(main 머지 완료), 골든셋 15/15,
`brain/checks` 10개 통과, 색인 재구축 완료.

남은 것은 세 가지다. 이 문서는 그 세 가지의 실행 순서와 절차를 적는다.

---

## 0. 앞선 세션에서 내가 틀리게 말한 것 (정정)

계획을 읽기 전에 알아야 한다. 어제 대화에서 같은 사안을 두고 세 번 말을 바꿨고,
**마지막에 한 말이 틀렸다.** 지금 계획은 코드를 직접 읽고 전수 측정한 결과에 기반한다.

| 내가 했던 말 | 실제 |
|---|---|
| "audit이 빨간 건 인용문이 없어서다" | 틀림. 인용문 없음은 건너뛸 뿐 실패가 아니다 (`audit.py:267`) |
| "미머지 브랜치 때문에 검증이 깨진다" | 틀림. 검증은 카드에 적힌 커밋의 blob을 직접 읽으므로 브랜치와 무관하다 (`audit.py:132`) |
| **"데이터는 맞고 검증기가 틀렸다"** | **틀림. 검증기는 설계대로 동작했고, 5건 중 1건은 진짜 데이터 오류였다** |

세 번째가 이번 계획의 출발점이다. 아래 §1에 실측 근거를 적는다.

---

## 1. 실측으로 확정된 사실

### 1.1 심볼 검증기의 실제 규칙

`symbol_verify.py:190`

```python
def _quote_contains_node(node, start, end) -> bool:
    return node is not None and start <= node.start_byte and node.end_byte <= end
```

**심볼 이름 노드가 인용문 바이트 범위 안에 통째로 들어와야 통과**한다.
인용문이 그 함수 몸통 안에 있다는 것만으로는 부족하다.

이건 실수가 아니라 의도된 설계다. `tests/test_symbol_verify.py`에
`test_quote_must_contain_qualified_leaf_identifier_boundary`와
`test_quote_must_contain_unqualified_identifier_boundary`가 명시적으로 박혀 있다.
목적은 **인용문 조각 하나로 심볼 라벨을 참이라 주장하는 것을 막는 것**이다.

### 1.2 빨간 5건의 정체 — 4 대 1로 갈린다

BB2 코퍼스 앵커 3,809개 중 인용문을 가진 것은 502개. 그중 인용문 안에 심볼 이름이
없는 것이 21개다. 21개를 검증기에 직접 태운 결과:

- **16개**: tree-sitter 파싱 실패(ERROR)나 `operator` 계열 → "확인 불가" 판정.
  16개 **전부** `manual_symbol_verification`(사람이 확인한 구조화 근거)이 붙어 있어
  구제됐다.
- **5개**: 파싱은 깨끗했고 수동 근거도 없어서 "불일치" 판정.

그 5개를 실제 코드의 함수 경계와 대조한 결과:

| 카드 | 인용문 위치 | 실제로 감싸는 함수 | 카드 라벨 | 판정 |
|---|---|---|---|---|
| `--1` | 150행 | `SettingDataManager::getFloatValue` (148~157) | 같음 | 라벨 정확 |
| `--2` | 422행 | `BaseGameDirector::initWithStageObject` (340~445) | 같음 | 라벨 정확 |
| `--3` | 42행 | `calculateExpandedGameAreaRowCounts` (36~47) | `GameConstantsHelper::initExpandedGameArea` | **라벨 오류** |
| `--4` | 89행 | `BubbleMapData::BubbleMapData` (73~145) | 같음 | 라벨 정확 |
| `--5` | 563행 | `BaseUILayerTop::initDefaultDraw` (508~601) | 같음 | 라벨 정확 |

즉 **4건은 라벨이 맞는데도 빨갛고, 1건은 진짜로 틀렸다.**
`--3`이 가리킨 `initExpandedGameArea`는 같은 파일 109행에 따로 있고 인용문과 무관하다.

`--3`이 뒷받침하는 상위 매핑은 "확장 화면은 어드민의 상단 가림 행과 맵 올림 행을
분리 적용하고 두 값을 실제 가시 행 계산에 함께 반영한다"이고, 인용문은 정확히 그
계산을 하는 코드다. **인용문이 맞고 심볼 라벨만 틀렸다.**

### 1.3 audit이 빨간 유일한 원인

```
ok           : False
lint         : True / problems 0
isolated     : 15          (판정에 반영되지 않는 축)
stale_status : {'ok': True, 'skipped': False}
code_quotes  : ok=False  checked=502  skipped=3307
failures     : admin-row-adjustment--1 ~ --5, 전부 symbol_mismatch

id_format        {'valid': 3809}
references       {'intact': 3809}
code_quote       {'missing': 3307, 'verified': 502}
symbol_relation  {'unsupported': 3307, 'verified': 478, 'mismatch': 5, 'manual_verified': 19}
stale            {'unchanged': 3436, 'changed': 373}
```

**이 5건 말고 빨간 것은 하나도 없다.**

### 1.4 인용문은 신규 앵커에 필수다

`mutation.py:420-426` — 새 CodeLocator이거나 좌표(커밋·경로·심볼 등)가 바뀐
CodeLocator는 비어 있지 않은 `verified_quote`가 없으면 쓰기가 거부된다.

설계 문서(`docs/superpowers/specs/2026-07-28-brain-ingest-recovery-design.md`)에도
"새 CodeLocator와 근거 좌표를 바꾸는 CodeLocator는 비어 있지 않은 `verified_quote`가
필수다"라고 적혀 있다.

기존 3,307개가 인용문 없이 존재하는 것은 그 강제가 생기기 전에 들어왔기 때문이다.
**"인용문 없이 쓴다"는 신규 데이터에서는 불가능하다.**

---

## 2. 작업 순서와 그 이유

**Task 13을 먼저 한다.** 이유가 있다.

Task 13은 "지금 이 커밋 상태를 최종본으로 못 박는" 작업이다. 계획서 원문
(`docs/superpowers/plans/2026-07-31-task17-canonical-id-recovery.md`, Task 13 Step 2)이
**스냅샷 안의 저장소 HEAD가 `TASK17_COMMIT`과 정확히 같을 것**을 요구한다.

`--3` 라벨을 먼저 고치면 BB2에 새 커밋이 생겨 HEAD가 바뀌고, Task 13의 이 조건이
깨진다. 그러면 Task 13을 다시 설계해야 한다.

그래서 순서는 이렇다.

```
1) Task 13  — HEAD가 e28ff4ee7d인 지금 최종 스냅샷을 찍는다
2) 엔진 수정 — 심볼 검증에 "몸통 규칙" 추가 (승인 필요)
3) 데이터 수정 — --3 라벨 교정
4) 재검증    — audit ok=true 확인
5) 부수 정리 — 골든셋 서식, 엔진 미추적 문서
```

---

## 3. 작업 1 — Task 13: 최종 스냅샷과 다음 과제 연결점 고정

### 왜 하는가

Task 18(표시용 데이터 이전)이 시작하려면 "어느 상태에서 출발하는가"가 바이트 단위로
못 박혀 있어야 한다. Task 13이 그 못을 박는다.

### 선행 조건 (실행 전 확인)

- [x] BB2 HEAD = `e28ff4ee7da758bd7ab17c800fb1079fd4c62851`
- [x] BB2 HEAD의 부모 = `53671bce5e94edf38a7afa11706963581065fb0f` (계획서 요구와 일치)
- [x] 엔진 HEAD = `3a91f8682a3920617d4fd71594a75d52b6870f44`
- [x] 승인 영수증 존재: `task8-ledger-approval.json`,
      `task17-rebound-approval-4e7638afe82c.json`
- [ ] **엔진 미추적 문서 9개** — 완료 조건에 "엔진이 깨끗한 커밋 상태"가 있다.
      아래 §7에서 먼저 커밋한다.

### 절차

계획서 원문 Task 13 Step 1~5를 그대로 따른다. 요지만 적는다.

**Step 1** — 커밋을 포함한 전체 스냅샷 생성 후 즉시 검증

```bash
BB2=/Users/al03040455/Desktop/bb2_client
ENGINE=/Users/al03040455/Downloads/codes/project-brain
TASK17_RECEIPTS=/Users/al03040455/.project-brain-task17-receipts-81beb462fa00
FINAL_OUT="$BB2/.snapshots/2026-07-31/task17-final"

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m project_brain.cli snapshot create \
  --brain-root "$BB2/brain" --repo-root "$BB2" --engine-root "$ENGINE" \
  --output-root "$FINAL_OUT" --snapshot-id task17-final \
  > "$TASK17_RECEIPTS/final-snapshot-create.json"

# 생성된 manifest SHA로 곧바로 검증
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m project_brain.cli snapshot verify \
  --snapshot-root "$FINAL_OUT/task17-final" \
  --expected-manifest-sha256 "<위 JSON의 manifest_sha256>"
```

**Step 2** — 스냅샷이 담은 값이 살아 있는 상태와 같은지 대조

- 스냅샷 안 저장소 HEAD = `TASK17_COMMIT`
- 스냅샷 안 엔진 HEAD = `ENGINE_SHA`
- 코퍼스 지문 = `aba3940015ce9c2ffca954ef0950c9d92bfff1e2ac237dffd4d43f97789a5ad0`
  (`task17-live-applied-aba3940015ce.json`의 `outcome.fingerprint_after`)
- 색인 지문·stale 지문은 실행 시점에 뽑아 기록

**Step 3** — 스냅샷 **바깥**에 다음 과제 연결점을 JSON으로 기록

`$BB2/.snapshots/2026-07-31/task17-final/task18-binding.json`.
키를 정렬한 공백 없는 JSON + 끝에 줄바꿈 하나. 담을 값:

```
version, task17_commit, engine_sha, snapshot_id, snapshot_manifest_sha256,
corpus_fingerprint, index_fingerprint, stale_fingerprint,
bb2_user_dirt_status_sha256, bb2_user_dirt_content_sha256,
source_checkout_status_sha256, source_checkout_content_sha256, task18_allowed
```

쓰고 나서 이 파일 자체의 SHA-256을 따로 출력해 영수증에 남긴다.
**검증이 끝난 스냅샷 폴더 안에는 어떤 파일도 추가하지 않는다.**

**Step 4** — 실패해도 커밋은 건드리지 않는다

스냅샷 생성·검증이나 연결점 쓰기가 실패하면 `TASK17_COMMIT`을 되돌리거나 고쳐쓰지
않는다. 같은 HEAD를 유지한 채 원인을 고치고 Step 1~3만 다시 한다.

**Step 5** — 최종 완료 확인 (계획서 원문의 11개 항목 전부)

### 성공 기준

- 스냅샷 검증 통과
- 연결점 JSON의 SHA-256이 영수증에 기록됨
- BB2·엔진 양쪽의 기존 미커밋 변경이 그대로 보존됨
- push·머지·Task 18은 실행하지 않음

---

## 4. 작업 2 — 엔진: 심볼 검증에 "몸통 규칙" 추가

### 승인이 필요한 결정

이건 검증 의미를 바꾸는 변경이라 진행 전에 확인이 필요하다.

**지금 규칙**: 인용문 안에 심볼 이름이 들어 있어야 통과.
**추가할 규칙**: 인용문이 어떤 함수 **몸통** 안에 통째로 들어 있고 그 함수 이름이
심볼과 같으면 통과.

### 왜 "몸통"으로 좁히는가 — 실패한 첫 시도

처음엔 "감싸는 함수 이름이 같으면 통과"로 넓게 잡았다. **기존 테스트 두 개가 깨진다.**

- `void Foo::bar() { return; }`에서 인용문 `":"` 한 글자, 심볼 `Foo::bar`
  → 넓은 규칙은 통과시킨다. 하지만 콜론 한 글자는 아무 근거도 못 된다.
- `int compute_value() { return 1; }`에서 인용문 `"c"` 한 글자도 마찬가지.

두 인용문 모두 **함수 시그니처 부분**에 걸쳐 있다. 그래서 "몸통(`body` 필드) 안에
완전히 포함될 때만" 으로 좁혔다. 시그니처를 스치는 조각은 규칙이 적용되지 않는다.

좁힌 규칙으로 기존 테스트 4개를 다시 태운 결과 — **하나도 건드리지 않는다.**

| 인용문 | 심볼 | 새 규칙 적용? | 기존 기대 |
|---|---|---|---|
| `":"` | `Foo::bar` | 아니오 | 불일치 유지 ✓ |
| `"c"` | `compute_value` | 아니오 | 불일치 유지 ✓ |
| `"READY"` | `READ` | 아니오 (감싸는 함수 없음) | 불일치 유지 ✓ |
| 함수 전체 | `compute_value` | 아니오 (기존 경로로 통과) | 통과 유지 ✓ |

### 실데이터 전수 시뮬레이션 결과

BB2 인용문 보유 502건 전부에 좁힌 규칙을 적용:

```
전 : verified 478, unsupported 19, mismatch 5
후 : verified 482, unsupported 19, mismatch 1
```

- 새로 통과: `--1`, `--2`, `--4`, `--5` (라벨이 정확한 4건)
- 남는 불일치: `--3` 하나 — 라벨이 진짜 틀린 것
- **기존 통과분 회귀 0**

즉 이 규칙은 **거짓 경보만 없애고 진짜 오류는 그대로 잡는다.**

### 검증력이 약해지는가 — 아니다

"인용문이 그 함수 몸통 안에 있다"는 "인용문 어딘가에 그 이름이 적혀 있다"보다 오히려
강한 주장이다. 지금 규칙은 그 함수를 **호출하는** 줄만 인용해도 통과하지만, 몸통
규칙은 그 함수에 실제로 **속해** 있어야 통과한다.

### 구현 (TDD)

**red 테스트 먼저.** `tests/test_symbol_verify.py`에 추가:

1. `test_quote_inside_function_body_verifies_by_enclosing_definition`
   — 몸통 안 한 줄 인용 + 정확한 심볼 → 통과 기대 (현재 불일치라 red)
2. `test_enclosing_body_rule_rejects_wrong_symbol`
   — 몸통 안 인용 + 다른 함수 이름 → 불일치 유지
3. `test_enclosing_body_rule_ignores_signature_overlap`
   — 시그니처에 걸친 조각은 규칙 미적용 (기존 두 테스트의 명시적 재확인)
4. `test_enclosing_body_rule_handles_in_class_method_definition`
   — 클래스 안에서 정의된 메서드는 이름이 `method`로만 나오므로 바깥 클래스
     이름을 합쳐 `Class::method`와 맞춰야 한다
5. `test_enclosing_body_rule_handles_anonymous_namespace_free_function`
   — 이름 없는 namespace 안 자유 함수 (`--3`이 이 모양이다)
6. `test_enclosing_body_rule_prefers_innermost_definition`
   — 람다·중첩 정의가 있으면 가장 안쪽을 고른다

**구현 위치**: `symbol_verify.py`의 기존 루프가 끝난 뒤, 불일치를 돌려주기 직전.
파싱 오류 검사(`_syntax_problem_overlaps`)는 지금처럼 맨 앞에 그대로 둔다 —
파싱이 깨진 파일은 계속 "확인 불가"로 남아 수동 근거 경로를 쓴다.

**구현 시 주의 (프로토타입에서 확인한 함정)**

- 함수 이름을 뽑을 때 문자열을 `(`로 자르는 방식은 쓰지 않는다. 포인터 반환형이나
  템플릿에서 깨진다. `function_definition` → `declarator` → `function_declarator`를
  타고 내려가 이름 노드에 도달해야 한다.
- 클래스 밖 정의(`void Foo::bar()`)는 이름 노드가 `qualified_identifier`라 기존
  `_qualified_identifier_segments`를 그대로 재사용할 수 있다.
- 클래스 안 정의는 이름이 단순 식별자라 `_lexical_scope_segments`로 바깥 이름을
  합쳐야 한다.
- 이름 없는 namespace는 `child_by_field_name("name")`이 `None`이라 자동으로
  건너뛰어진다 — 이미 맞게 동작한다.

**검증 명령**

```bash
cd /Users/al03040455/Downloads/codes/project-brain
uv sync --extra mecab
.venv/bin/python -m pytest -q
.venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
```

둘 다 통과해야 완료다.

---

## 5. 작업 3 — 데이터: `--3` 심볼 라벨 교정

### 무엇을 고치는가

`brain/objects/code/code.ingame-area-expansion.admin-row-adjustment--3.json`

```
symbol: "GameConstantsHelper::initExpandedGameArea"
     →  "calculateExpandedGameAreaRowCounts"
```

인용문·경로·커밋은 그대로 둔다. 인용문이 맞고 라벨만 틀렸다.

### 함께 볼 것 — 제목이 인용문 복사본이다

이 카드의 `title`이 인용문 앞부분을 그대로 잘라 붙인 것이다.

```
"rowCounts.physicalExtraRowCount = screenExtraRowCount + mapRaiseRowCount;\n\t\t
 rowCounts.mapDataStartExtraRowCount = screen"
```

설계 문서가 "인용문 전체나 앞부분을 제목으로 복사하지 않는다"고 금지한 바로 그
모양이다. 같은 컨텍스트의 `evref` 카드도 같은 상태다.

엔진 쪽은 이미 `a20b1c5`("앵커 제목을 심볼에 맞춘다")로 고쳐졌지만 **기존 데이터는
소급 적용되지 않았다.** 이번에 `--3`을 건드리는 김에 이 카드의 제목도 사람이 읽을 수
있는 문장으로 바꾼다.

### 주의 — 좌표를 바꾸면 인용문 재검증이 돈다

`symbol`은 좌표 항목이라(`mutation.py:_COORDINATE_FIELDS`) 값을 바꾸면 쓰기 시점에
인용문 원문 대조가 다시 실행된다. 이건 원하는 동작이다. **작업 2(엔진 몸통 규칙)가
먼저 들어가 있어야** 이 쓰기가 통과한다. 순서를 지킨다.

### 파급 범위

`--3`을 참조하는 파일은 3개(카드 자신, `evref`, 상위 매핑). `ingame-area-expansion`
컨텍스트 전체는 112개 객체지만 이번에 건드리는 것은 `--3` 계열뿐이다.

---

## 6. 작업 4 — 재검증

```bash
BB2=/Users/al03040455/Desktop/bb2_client
ENGINE=/Users/al03040455/Downloads/codes/project-brain

# 1) audit이 완전히 초록인지
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli audit \
  --brain-root "$BB2/brain" --repo-root "$BB2" --no-fetch
#   기대: ok=true, code_quotes.failures=[], symbol_relation mismatch 0

# 2) 실코퍼스 가드
cd "$BB2"
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest discover -s brain/checks -p "test_*.py"
#   기대: 10개 통과, 건너뜀 0

# 3) 골든셋
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m project_brain.cli eval
#   기대: 15/15
```

**색인 재구축이 필요하다.** `surface.py:131-133`이 `path`와 `symbol`을 검색 표면에
함께 넣기 때문에, `--3`의 심볼을 바꾸면 그 앵커의 색인 내용이 달라진다.

```bash
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m project_brain.cli index rebuild
```

실모델(bge-m3) 재구축이라 비용이 크다. 작업 3의 데이터 수정을 **한 번에 모아서**
끝낸 뒤 재구축을 한 번만 돌린다. 재구축 뒤 골든셋을 다시 확인한다 — 색인이 바뀌면
검색 결과가 움직일 수 있다.

---

## 7. 부수 작업

### 7.1 엔진 미추적 문서 9개 — **커밋하지 않는다** (판단 정정)

처음엔 "완료 조건에 엔진이 깨끗한 커밋 상태가 있으니 먼저 커밋한다"고 적었다.
**틀렸다.** 계획서 원문을 다시 읽고 영수증을 실측한 결과:

- 원문에서 `ENGINE`은 **워크트리** `.worktrees/brain-ingest-recovery`이고,
  메인 클론은 별개로 `SOURCE_CHECKOUT`이다 (원문 1066~1070행).
- `task9-user-dirt-exception-...json`의 `protected_git`을 보면 `engine`(워크트리)은
  `entry_count: 0`으로 깨끗해야 하는 쪽이고, `source`(메인 클론)는 **dirt를 지문으로
  기록해 보존을 증명하는 쪽**이다.
- 실측: 워크트리는 지금도 완전히 깨끗하다(변경 0줄, HEAD `1742c09d`).
  미추적 문서 9개는 메인 클론에 있고, **어제 세션 시작 시점부터 이미 source dirt의
  일부**였다.

즉 커밋하면 보존해야 할 것을 없애는 셈이다. **그대로 둔다.**

Task 13 바인딩의 `source_checkout_status_sha256`·`source_checkout_content_sha256`는
이 dirt를 포함한 **현재 상태를 그대로 캡처**해 기록한다. 예전 baseline과 같을 필요는
없다 — 어제 사용자 승인 아래 커밋(`a20b1c5`)과 머지(`3a91f866`)를 했으므로 source의
HEAD와 dirt는 이미 정당하게 바뀌었다.

<details>
<summary>원래 적었던 내용 (폐기)</summary>

```
docs/plans/2026-07-27-ingest-fix-execution-plan.md
docs/reports/2026-07-27-plan-delta-bg.md
docs/reports/2026-07-27-two-ingest-session-review.md
docs/reports/2026-07-28-agents-doctor-global-skill-mirror-final-review.md
docs/reports/2026-07-28-agents-doctor-global-skill-mirror-ledger.md
docs/reports/2026-07-28-brain-ingest-redesign-review.html
docs/superpowers/plans/2026-07-27-handoff-consumer.md
docs/superpowers/plans/2026-07-28-agents-doctor-global-skill-mirror.md
docs/superpowers/plans/2026-07-28-brain-ingest-recovery.md
```

Task 13의 완료 조건에 "엔진이 깨끗한 커밋 상태"가 있어서 먼저 처리한다.
전부 다른 세션이 만든 문서다.

</details>

### 7.1b 엔진 정본이 워크트리에서 메인 클론으로 옮겨간 사실 기록

원문 계획은 워크트리에서 작업하고 메인 클론은 손대지 않는 구조였다. 어제 머지로
정본이 메인 클론 `main`(`3a91f866`)으로 옮겨갔고, 코퍼스 검증·색인 재구축·전역 도구
재설치가 전부 그쪽으로 이뤄졌다.

따라서 Task 13 바인딩의 `engine_sha`는 원문의 `1742c09d`가 아니라 **지금 살아 있는
정본 `3a91f866`**을 쓴다. Task 18이 출발점으로 삼아야 할 엔진이 그것이기 때문이다.
이 이탈 사실과 이유를 영수증에 함께 남긴다.

### 7.2 골든셋 서식 복원

`brain/eval_scenarios.json`이 216줄에서 1줄로 눌렸다. 엔진이 정규화하면서 생긴
결과다. 내용은 정상이고 15/15도 통과한다. 사람이 읽고 고치기 어려우니 줄바꿈 있는
형태로 되돌린다. **다만 Task 13 스냅샷을 찍은 뒤에 한다** — 지금 바꾸면 코퍼스
바이트가 달라진다.

### 7.3 미루는 것 — 수동 근거 16건 재검토

파싱 실패로 "확인 불가"가 된 16건은 전부 수동 근거가 붙어 구제된 상태다. 몸통 규칙이
들어가도 이들은 파싱 오류 검사가 먼저 걸려 그대로다. 지금 건드릴 이유가 없다.
tree-sitter 파싱이 왜 깨지는지(cocos2d 매크로로 추정)는 별도 과제로 둔다.

---

## 8. 어제 받은 질문에 대한 답

**"인용문 그냥 없이 쓰면 되는 거야? 신규 데이터에만 인용문 들어가는 거고?"**

신규는 인용문이 **필수**다. 새 앵커나 좌표가 바뀐 앵커는 인용문이 없으면 쓰기 자체가
거부된다(`mutation.py:420`). 기존 3,307개가 인용문 없이 있는 건 그 강제가 생기기 전에
들어왔기 때문이다.

그리고 인용문을 넣을 때는 규약이 하나 붙는다 — **인용문이 심볼 이름을 담거나, 그
심볼 함수 몸통 안에 있어야 한다.** 지금은 앞쪽만 인정해서 이번 4건 같은 거짓 경보가
난다. 작업 2가 뒤쪽도 인정하게 만드는 일이다.

**"다른 브랜치에서 머지 전에 코드가 추가될 수 있다. 이걸 감안할 장치가 필요한가?"**

이미 있다. audit의 `stale.unmerged_anchors`가 현재 40건을 `not_ancestor`(주 브랜치에
아직 안 올라온 커밋)로 표시하고, **stale 검사는 이걸 실패로 치지 않는다.**
`ingame-area-expansion` 앵커들도 거기 들어 있다.

그리고 이번 5건은 브랜치 문제가 아니었다. 인용문·심볼 검증은 카드에 적힌 커밋의
blob을 직접 읽으므로 현재 브랜치와 무관하다. 실제로 인용문은 전부 찾아졌다
(`code_quote: verified`).

**"Task 17이 끝났는데 왜 Task 13이 안 끝났나? 순서가 이상한 것 아닌가?"**

번호 체계가 두 층이다.

- **Task 17** = 할 일 목록의 17번 과제 = "잘못된 객체 이름 158개 고치기"
- **Task 1~13** = 그 17번 과제를 수행하는 실행 계획서 안의 단계

즉 Task 13은 Task 17의 13번째 단계다. 목표(158→0)는 달성됐고 마지막 단계가 남았다.
내가 "Task 17 완료"라고 말한 게 부정확했다.

---

## 9. 확인이 필요한 지점

작업 2(엔진 몸통 규칙)는 검증 의미를 바꾸는 변경이라 진행 전 승인이 필요하다.
나머지는 이미 정해진 계획을 따르는 실행이다.

대안은 데이터만 고치는 길인데, 실측해보니 좋지 않다. `--2`는 인용문을 함수
시그니처까지 늘리면 4,007바이트가 되고 그래도 파싱 오류로 "확인 불가"가 되어
수동 근거가 또 필요하다. `--5`는 3,132바이트가 된다. 근거로 쓰기엔 너무 크고,
"인용문을 넣을수록 손해"라는 거꾸로 된 유인이 남는다.
