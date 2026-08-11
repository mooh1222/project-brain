# 2026-07-27 적재 정비 실행 계획

> 2026-07-27 적재 2건(`petskill-kamehameha`·`ingame-item-usage`)에서 드러난 결함을 고치는
> 구현 계획이다. 사실 원장·진단·결정 근거는
> [리포트](../reports/2026-07-27-two-ingest-session-review.md)에 있다.
> 이 문서는 **구현자가 그대로 따르는 절차**만 담는다.
>
> 만든 과정: 실측 4축(에이전트 4명) → 1차 적대검증 13건 → 통합 계획 24개 → 2차 적대검증 21건.
> 2차 검증의 blocker 3건·serious 5건·minor 3건은 각 task의 **심사 반영**에 들어 있다.
> **심사 반영이 붙은 task는 원안대로 구현하면 안 된다.**

## 순서

```
구간 1  엔진 코어   T1~T9    편집 설치라 저장 즉시 반영 → T15의 심사 반영을 먼저 읽어라
구간 2  템플릿·문서 T10~T14  파일 사본이라 install 없이는 bb2에 안 닿는다
구간 3  경계        T15~T17  엔진 검증·커밋 → bb2 재설치 → 스냅샷
구간 4  데이터      T18~T28  kamehameha 재적재 → item-usage 재적재 → 백필 → 골든셋 → 지식
```

**T18(kamehameha 삭제)을 title 백필보다 먼저 끝낸다.** `ingest.py:33`이 사전조건 대상이
사라진 경우를 조용히 건너뛰어, build 후 삭제하면 지운 앵커가 옛 순번 키로 되살아난다
(스크래치에서 3건 재현, 전량이면 180건, 오류·경고 0, lint·audit 통과). T1이 이걸 막는다.

---

## T1 — ingest preconditions: 대상 객체가 사라졌으면 오류로 승격

**레포** engine · **선행** 없음

**왜**: 1차 검증에서 실제로 재현된 좀비 부활의 유일한 기계적 차단선이다. ingest.py:33이 `if existing.has(oid) and ...`라서 build 이후 누가 그 객체를 지우면 검사를 조용히 건너뛰고, 지운 앵커가 옛 키 그대로 되살아난다(스크래치 3건 재현, 전량이면 180건, 오류·경고 0, lint 통과). 순서로만 막으면 병렬 세션이 지운 어떤 객체든 같은 방식으로 부활한다.

**파일**: `src/project_brain/ingest.py` · `tests/test_ingest.py`

**red 테스트**: tests/test_ingest.py에 `test_precondition_target_missing_is_error` 추가 — store에 객체 A를 저장하고 preconditions={A.id: A.updated_at}를 만든 뒤 A의 파일을 지우고 다른 객체만 담아 ingest 호출. 현재는 통과하므로 `with self.assertRaises(IngestError)`가 red가 된다.

**변경**: ingest.py:33-37 루프를 두 갈래로 나눈다. `if not existing.has(oid): raise IngestError(f"{oid}: precondition 대상이 사라짐 — build 이후 store에서 삭제됨, 재build 필요")`를 먼저 두고, 기존 updated_at 불일치 검사는 그대로 뒤에 둔다. 메시지는 기존 불일치 메시지와 같은 톤으로 '재build 필요'를 붙인다.

**검증**: `.venv/bin/python -m pytest -q tests/test_ingest.py` 통과 + 전체 `.venv/bin/python -m pytest -q`가 기준선(674 passed, 32 subtests) 이상

---

## T2 — CodeLocator·EvidenceRef title 폴백을 symbol로, 노트 title은 선택 입력

**레포** engine · **선행** 없음

**왜**: 지금 title은 quote[:120]이라 잘린 코드 조각이 설명처럼 읽힌다(코퍼스 3886개 중 길이 정확히 120인 것 691개). 폴백을 symbol로 바꾸면 새로 적재되는 앵커는 처음부터 항상 참인 라벨을 갖는다. 노트 passthrough를 선택으로 열되 조립기는 자동 생성하지 않는다 — 사람이 새로 쓴 문장은 읽는 쪽이 진위를 대조할 수 없다(D3에서 유지된 부분).

**파일**: `src/project_brain/assembly.py` · `tests/test_assembly.py`

**red 테스트**: tests/test_assembly.py의 BuildCodeEvidenceTest에 3건 추가 — (1) title 미지정 앵커 → `loc["title"] == a["symbol"]`이고 `ev["title"] == a["symbol"]`, (2) 앵커에 `title: "사람 라벨"` → 그 값이 실림, (3) 앵커 `symbol: ""` → validate_notes가 `code_anchors[0].symbol은 비어 있지 않은 값 필수`를 낸다. (4) 앵커 `title: []` → 형식 오류. 현재 (1)(2)는 quote[:120]이 나오고 (3)(4)는 오류 0이라 전부 red다.

**변경**: build_code_evidence(assembly.py:57-81)의 for 루프 안 `quote = a["quote"]` 직후에 `title = a.get("title") or a["symbol"]` 한 줄을 넣고, :68과 :75의 `"title": quote[:120]`을 둘 다 `"title": title`로 바꾼다. :77의 `summary = quote[:500]`은 그대로 둔다(schema가 EvidenceRef.summary를 필수로 요구하고 답변 경로에 안 실리며 인용 원문이 남는 유일한 자리다). validate_notes의 code_anchors 값 검사 루프(assembly.py:416-423)에 quote·verified_at과 같은 모양으로 두 검사를 더한다 — symbol이 문자열이 아니거나 strip 후 비면 오류, title 키가 있는데 문자열이 아니거나 strip 후 비면 오류. `_ITEM_REQUIRED`는 손대지 않는다(title을 필수로 만들면 안 된다).

**검증**: `.venv/bin/python -m pytest -q` 674+ passed. 그리고 `.venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'` → Ran 75 tests OK (title 기대를 하는 테스트는 tests/ 전체에 0건이라 깨지는 것이 없어야 한다)

> **심사 반영 — 노트 `title` 입구를 열지 않는다.** 값을 넣을 경로가 스캐폴드 어디에도 안 생긴다(T11·T10·T13 전부 앵커 title 없음). 열면 `notes.json`을 손으로 고쳐야만 닿는 죽은 칸이 되고, T14의 3자 일치 대조가 그 죽은 상태를 고정한다.
> → 폴백을 `a["symbol"]` **단일**로 둔다. `title` 타입 검사도 필요 없어진다. `symbol` 빈값 검사는 그대로 넣는다.

---

## T3 — 노트 5개 키 섹션의 key/id 중복을 오류로

**레포** engine · **선행** 없음

**왜**: 같은 key 2개면 같은 id 객체 2개가 만들어지고 ingest가 마지막 것만 저장한다 — 오류·경고 0, lint도 못 잡는다(build가 merged store를 dict로 접으면서 하나가 사라져 lint 입력에 애초에 1개만 들어간다). 지금은 키가 `{mapping_key}--{i}`라 자동으로 안 겹치지만, T10에서 의미형 키 선택 입력을 열면 사람이 이름을 붙이므로 충돌 가능성이 처음으로 실재한다. 그리고 구멍은 code_anchors만이 아니다 — glossary·mappings·sources도 같은 방식으로 조용히 사라진다(재현 확인).

**파일**: `src/project_brain/assembly.py` · `tests/test_assembly.py`

**red 테스트**: tests/test_assembly.py에 5건 추가 — code_anchors·glossary·mappings·decisions는 같은 `key` 2개, sources는 같은 `id` 2개를 넣고 validate_notes가 `code_anchors[1].key='x' 중복` 형태 오류를 내는지. 현재 5건 전부 오류 0이라 red다.

**변경**: `_ITEM_REQUIRED`를 도는 루프(assembly.py:353-403) 안에 섹션별 `seen: dict[str,int] = {}`을 두고, 식별 필드(glossary·code_anchors·mappings·decisions는 `key`, sources는 `id`)의 값이 이미 seen에 있으면 `errors.append(f"노트: {section}[{i}].{field}={value!r} 중복 — {seen[value]}번 항목과 같음(같은 id 객체 2개가 만들어지고 뒤의 것만 저장된다)")`. 새 루프를 만들지 말고 이미 index i를 들고 있는 기존 루프를 쓴다.

**검증**: `.venv/bin/python -m pytest -q` 674+ passed (패치본에서 674 passed 실측 확인됨)

---

## T4 — _SET_ALLOWLIST에 CodeLocator.title 추가

**레포** engine · **선행** 없음

**왜**: bb2 title 백필의 유일한 안전 통로다. 현재 CodeLocator는 allowlist에 키 자체가 없어 updates로 아무 필드도 못 고치고, 남은 길은 extra_objects(완성 객체 통째 주입)뿐인데 그건 preconditions가 비고 diff도 []여서 낙관적 잠금·변경 보고가 전부 없다(무신호 덮어쓰기).

**파일**: `src/project_brain/assembly.py` · `tests/test_assembly.py`

**red 테스트**: tests/test_assembly.py에 `test_code_locator_title_set_update` — store에 CodeLocator 하나를 두고 `updates: [{id, expected_updated_at, set: {title: "Foo::run"}}]`을 build. 현재는 `set 필드 'title'는 CodeLocator allowlist 밖` 오류라 red. 함께 `evidence_unchanged` 없이도 통과함을 단정한다(title은 _CLAIM_FIELDS 밖이라 근거 동반이 강제되지 않는다).

**변경**: assembly.py:236-240의 `_SET_ALLOWLIST`에 `"CodeLocator": {"title"}` 한 줄 추가. `_CLAIM_FIELDS`(:248)는 손대지 않는다 — title은 의미 주장이 아니라 표시 라벨이고, DomainMapping·GlossaryTerm·DomainContext도 이미 같은 이유로 title이 set allowlist에 있다.

**검증**: `.venv/bin/python -m pytest -q` 674+ passed

> **심사 반영 — `"EvidenceRef": {"title"}`을 함께 넣는다.** CodeLocator만 넣으면 코드 근거 EvidenceRef 3811개 중 코드조각 title 2919개를 영구히 못 고친다. `show` 이웃 목록(`cli.py:442-443`)과 graph 노드 라벨(`graph_viz.py:29` `LABEL_FIELDS` 첫 항목)이 EvidenceRef title을 읽는다 — T22가 개선한다는 바로 그 두 화면이다.

---

## T5 — 라우터 검수완료 구현위치 섹션에 path·symbol 동반 (D3 개정 (a))

**레포** engine · **선행** 없음

**왜**: 사용자 불만('답변의 코드 위치가 ID로도 title로도 구분 안 된다')의 실제 발생지다. router.py:265의 검수완료 섹션은 bare id만 내는데, 바로 위 :257-262의 candidate_locators는 이미 {id, path, symbol, trust_label}을 낸다 — 같은 함수 안의 비대칭이다. 이 한 곳을 고치는 것이 3879건 데이터를 덮어쓰는 것보다 작고 되돌리기 쉽고 라벨 붕괴가 없다. 그리고 저장 title을 어떻게 바꿔도 이 화면은 안 변하므로, 이걸 안 하면 B갈래 전체가 사용자에게 닿지 않는다.

**파일**: `src/project_brain/router.py` · `tests/test_router.py`

**red 테스트**: tests/test_router.py에 `test_reviewed_implementation_section_carries_path_symbol` — reviewed CodeLocator를 가진 store로 implementation 의도 질의를 돌려 해당 section에 `locators` 키가 있고 각 항목이 {id, path, symbol}을 담는지 단정. 현재는 object_ids만 있어 red.

**변경**: router.py:265의 `sections.append(...)`에 `"locators": [{"id": l["id"], "path": l.get("path"), "symbol": l.get("symbol")} for l in locators]`를 더한다. 기존 `object_ids`는 그대로 남긴다(소비자 호환). candidate_locators와 같은 필드 이름·순서를 쓴다. cli.py의 query 출력이 이 섹션을 렌더하는 지점에서 새 필드를 함께 내보내는지 확인하고, 안 내보내면 그 한 줄도 함께 고친다.

**검증**: `.venv/bin/python -m pytest -q` 674+ passed. bb2에서 `PYTHONPATH=<engine>/src <engine>/.venv/bin/python -m project_brain.cli query "아이템 버튼 터치 게이팅" --db brain/.brain-local/index.db`를 돌려 구현위치 섹션에 path·symbol이 실제로 실리는지 눈으로 확인(색인 변경 없음, 읽기만)

> **심사 반영 (blocker) — 폴백 경로에서는 붙이지 않는다.** `query/SKILL.md:25`가 지시하는 그대로 `--db` 없이 돌리면 지금도 출력이 **417KB**다(색인이 없으면 `router.py:503-504`가 reviewed CodeLocator 3634개를 붓는다). 여기에 `path`·`symbol`을 더하면 그 섹션이 191KB→919KB로 부풀어 전체 **1.1MB**가 된다. 즉 '구분이 안 된다'를 고치려는 변경이 사용자가 실제로 쓰는 경로에서는 답을 더 못 읽게 만든다. 그리고 원안 verify가 `--db`를 붙여 돌리게 돼 있어 **이 폭발을 원리상 관측하지 못한다**(`--db`를 주면 게이트가 닫혀 0개, 534바이트다).
> → (1) `recalled is not None`일 때만 `locators`를 붙인다. 폴백 경로는 지금처럼 id만.
> → (2) 폴백 자체에 상한 + `truncated: <전체수>` 표시를 둔다. 3634개 bare id 덤프는 T5 이전에도 답이 아니다.
> → (3) **`depends_on`에 T13(문서 `--db` 안내)을 추가한다** — 문서가 안 고쳐진 상태로 T5만 나가면 순손실이다.
> → (4) verify를 `--db` 없이/있이 두 번 돌려 바이트 수를 함께 기록한다.

---

## T6 — lint 키·id 형식 검사를 ok와 분리된 warning으로 + finalize 최상위 노출

**레포** engine · **선행** 없음

**왜**: 기존 코퍼스에 82개 위반(꿀통형 --낱말 73 + 점3단 9)이 있어 lint_store에 넣으면 무해한 멱등 재적재 1건조차 IngestError로 죽는다(실측: 메시지 11799자, build 오류 116건). ok에 안 섞는 선례가 이미 있다 — `unpromoted_vouched_terms`(lint.py:97-110)의 docstring이 '차단하면 모든 ingest가 깨진다'고 같은 논리를 적어 놨다. 다만 audit JSON 새 키에만 담으면 아무도 안 읽으니(finalize errors는 '<name> failed' 한 줄, bb2 checks에 lint/audit JSON 검사 0건) 사람이 보라고 지시받은 자리까지 올려야 한다.

**파일**: `src/project_brain/lint.py` · `src/project_brain/cli.py` · `src/project_brain/templates/audit/SKILL.md` · `tests/test_lint.py`

**red 테스트**: tests/test_lint.py에 `test_key_format_warnings_does_not_block` — 꿀통형 키(`code.ctx.honeypot--jar`)와 점3단(`code.a.b.c`)을 가진 store에 대해 (1) `lint_store(store) == []`, (2) `key_format_warnings(store)`가 2건을 낸다. 현재 함수가 없어 ImportError로 red.

**변경**: lint.py에 `key_format_warnings(store) -> list[str]` 신규 추가 — 객체 id를 `.`으로 나눠 3조각인지 보고, 3조각이면 마지막 조각을 anchor 계열은 `_ANCHOR_KEY_RE`, 나머지는 `_LOGICAL_KEY_RE`로 검사한다. 3조각이 아니면 그 자체를 위반으로 센다(점3단 9개가 이렇게 잡힌다). lint_store는 건드리지 않는다. cli.py의 `_run_lint`(:486-497)·`_run_audit`(:500-580) 출력 JSON에 `"key_format_warnings": [...]`를 별도 키로 담되 `ok` 계산식(:567)에는 넣지 않는다. audit/SKILL.md:44-48 필드 표에 한 줄 추가.

**검증**: `.venv/bin/python -m pytest -q` 통과. bb2에서 `PYTHONPATH=<engine>/src <engine>/.venv/bin/python -m project_brain.cli audit`를 돌려 `ok: true`가 유지되면서 `key_format_warnings`에 82건이 나오는지 확인(읽기 전용)

> **심사 반영 (blocker) — 판정 규칙을 '조각 수'에서 떼어낸다.** 원안 규칙대로면 위반이 82건이 아니라 **498건**이 나오고 그중 **382건(77%)이 설계상 정상인 id**다 — `context.<key>`(2조각), `review.<대상 전체 id>`(4~5조각), `projection.<ctx>.<req>.reuse`(4조각), jira 근거(`assembly.py:133`이 대문자 Jira 키를 그대로 붙인다). 그러면 이 경고 채널은 첫날부터 잡음 382건에 진짜 82건이 묻힌 상태로 태어나고, T12가 최상위로 올리면 **모든 적재 리포트에 498줄이 영구히 붙는다** — '사람이 보라고 지시받은 자리에 올리면 읽힌다'는 근거가 스스로 무너진다.
> → (1) **kind별 id 문법을 따로 선언**하고 그 문법에 안 맞는 것만 위반으로 센다.
> → (2) 경고 대상을 **CodeLocator/EvidenceRef 앵커 키로 좁혀** 첫날부터 82건에서 시작한다.
> → (3) verify를 '82건'이 아니라 **kind별 집계**(`{"CodeLocator": 82}`이고 DomainContext·ReviewRecord는 0건)로 바꾼다.

---

## T7 — extra_objects·ingest --objects-file 경로의 신규 id 형식 하드 게이트

**레포** engine · **선행** T6

**왜**: T6의 warning이 못 막는 입구가 여기다. assembly.py:511의 extra_objects는 validate_object만 타는데 schema.py:130-151에 id 형식 검사가 없고, `ingest --objects-file`은 validate_notes를 아예 안 탄다. 그래서 이 두 통로로는 어떤 모양의 키도 조용히 들어온다 — '유산은 경고·신규는 차단'이 성립하려면 이 게이트가 필요하다.

**파일**: `src/project_brain/ingest.py` · `src/project_brain/lint.py` · `tests/test_ingest.py`

**red 테스트**: tests/test_ingest.py에 2건 — (1) 형식 위반 id를 가진 신규 객체를 ingest → IngestError, (2) 이미 store에 있는 유산 위반 id(`code.ctx.honeypot--jar`)를 같은 내용으로 재적재 → 통과. 현재 (1)이 통과해서 red.

**변경**: ingest()의 게이트 구간(lint_store 호출 앞)에 `for obj in objects: if not existing.has(obj["id"]) and key_format_problem(obj["id"]): errors.append(...)`를 넣는다. 판정 함수는 T6에서 만든 것을 id 하나 단위로 쓸 수 있게 `key_format_problem(object_id) -> str | None`로 쪼개 재사용한다. store에 이미 있는 id는 통과시킨다(유산 82개가 멱등 재적재를 못 하게 되면 안 된다).

**검증**: `.venv/bin/python -m pytest -q` 통과 + T18(kamehameha 삭제) 이후 T20의 302객체 ingest가 통과(의미형 키 103개가 전부 `_ANCHOR_KEY_RE` fullmatch 통과함은 실측됨)

> **심사 반영 (blocker) — 앵커 키에만 건다.** 원안대로면 T20/T28의 재적재가 **통째로 거부된다**: 신규 `context.petskill-kamehameha`(2조각)와 jira 근거 3개(`evref.petskill-kamehameha.jira-LGBBTWO-234` 등, 마지막 조각에 대문자)가 걸리고, T18에서 파일을 지웠으니 '유산 예외' 통과권도 없다. 게다가 이건 유산 데이터 문제가 아니라 **엔진 자기 코드가 만드는 모양**이다. 앞으로 새 컨텍스트를 만드는 모든 적재, jira/pr 근거를 가진 모든 적재, `ingest()`를 경유하는 projection 저장(`cli.py:756·861`)까지 영구히 막는다.
> → 하드 게이트는 **CodeLocator와 짝 EvidenceRef의 앵커 키에만** 건다(원래 막고 싶었던 꿀통형 `--낱말`이 거기에만 있다).
> → **red 테스트에 정상 케이스를 반드시 넣는다** — 새 DomainContext 1개 + jira evref 1개를 담은 ingest가 통과. 원안 red 테스트는 위반 케이스만 봐서 이 실패를 못 잡는다.

---

## T8 — ingest 앞단 quote 원문 대조 게이트 (신규·변경만, blob 캐시)

**레포** engine · **선행** T1

**왜**: 지금 verified_quote 원문 대조는 audit에서만 돈다 — 쓰기가 검증보다 앞서고 사후 실패는 롤백하지 않는다. 실측 비용은 kamehameha 재적재 규모(180앵커)에서 1.53초라 옵션으로 뺄 필요조차 없다. 단, 덮는 범위는 앵커 3886개 중 verified_quote를 가진 579개(15%)뿐이라는 사실을 문서에 숫자로 적어야 한다 — 안 적으면 '검증 추가 완료'가 남은 85% 무검증을 덮는다.

**파일**: `src/project_brain/cli.py` · `src/project_brain/code_verify.py` · `tests/test_cli.py`

**red 테스트**: tests/test_cli.py에 `test_ingest_rejects_tampered_quote` — git 저장소를 만들고 파일을 커밋한 뒤, 그 파일에 없는 문장을 verified_quote에 넣은 CodeLocator를 `--objects-file`로 ingest. 현재는 저장되고 종료코드 0이라 red(기대: 종료코드 1 + store에 파일이 안 생김).

**변경**: `_run_ingest`(cli.py:89-109)에 `--repo-root`(기본 `brain_root.parent`, audit·mark-checked와 같은 규약)와 `--no-quote-verify`를 달고, ingest() 호출 **앞에** 검사한다. 엔진 함수 ingest() 안에는 넣지 않는다 — git 없는 tmpdir에서 도는 테스트가 수십 곳이라 다 깨지고, 우회 인자를 두면 '안 넘기면 조용히 건너뜀'이라는 지금 고치려는 실패 모양이 다시 생긴다. 대상 선정: `existing = BrainStore.load(brain_root)`로 store에 없거나 verified_quote·commit_sha·path 중 하나가 다른 CodeLocator만. code_verify에 (commit, path)별 blob 캐시를 씌운다(전수 16.3초→3.9초, 신규 180앵커 5.09초→1.53초 실측). 실패면 아무것도 안 쓰고 `{ok: false, quote_failures: [...]}`를 stdout에 내고 1로 끝낸다.

**검증**: `.venv/bin/python -m pytest -q` 통과. T20의 kamehameha 재적재에서 이 게이트가 실제로 돌고 failures 0인지 리포트로 확인

---

## T9 — mark-checked: verified_quote 없는 앵커의 검증 주장 갱신 거부

**레포** engine · **선행** 없음

**왜**: stale_check.py:359-361이 quote 재검증 없이 commit_sha를 새 head로 갈아 끼운다 — verified_quote는 그대로인데 그 quote를 확인했다고 주장하는 commit이 바뀐다. 가상 위험이 아니다: 지금 bb2 워킹트리의 미커밋 드리프트 20개가 mark-checked 결과이고 그중 19개가 verified_quote 없이 commit_sha만 최신으로 갈렸다. T8을 ingest에만 넣으면 이 입구는 계속 열려 있다.

**파일**: `src/project_brain/stale_check.py` · `src/project_brain/cli.py` · `tests/test_stale_check.py`

**red 테스트**: tests/test_stale_check.py에 `test_mark_checked_refuses_unverifiable` — verified_quote 없는 CodeLocator에 mark-checked를 걸어 commit_sha가 바뀌지 않고 거부 목록에 담기는지. 현재는 조용히 갱신되어 red.

**변경**: mark-checked 저장부에서 verified_quote가 없거나 문자열이 아닌 locator는 commit_sha·verified_at 갱신을 건너뛰고 `refused_unverifiable: [id...]`로 리포트한다. `--allow-unverifiable`을 주면 기존 동작. 최근 커밋 593112e가 finalizer에 대해 쓴 것과 같은 모양(명시 플래그 없으면 검증 불가 상태를 거부)이다.

**검증**: `.venv/bin/python -m pytest -q` 통과. bb2에서는 이 명령을 돌리지 않는다(워킹트리 드리프트 20개는 D6에 기록만)

---

## T10 — 조립기 배관 3줄 — 앵커 key 선택 입력 + glossary synonyms/aliases 통과

**레포** engine · **선행** 없음

**왜**: 현재 assemble_notes.py:63-67이 용어를 `{term, definition}`만 담고 통과 필드가 (status, candidate) 둘뿐이라 synonyms를 조용히 버린다. 엔진 build는 이미 `g.get("synonyms")`를 읽으므로(assembly.py:48-49) 막힌 곳은 조립기 한 곳이다. 이게 명부가 안 채워진 파이프라인 구멍의 실체다(GlossaryTerm 1181개 중 synonyms 32개=2.7%). key 선택 입력은 D2의 kamehameha 의미형 키를 정식 경로로 만든다.

**파일**: `src/project_brain/templates/ingest/scripts/assemble_notes.py` · `src/project_brain/templates/ingest/scripts/test_assemble_notes.py`

**red 테스트**: test_assemble_notes.py에 3건 추가 — (1) atom의 code_anchor에 `anchor_key`를 주면 그 값이 앵커 key로 쓰이고 mappings의 code_evref_keys·glossary evidence_refs가 그 키를 가리킨다, (2) 미지정이면 여전히 `{mk}--{i}`, (3) glossary_term에 synonyms·aliases를 주면 노트 glossary 항목에 그대로 실리고, 같은 term_key가 두 atom에 나오면 표면형이 합쳐진다(union). 현재 (1)(3)이 실패해 red.

**변경**: assemble_notes.py:52를 `ak = ca.get("anchor_key") or f"{mk}--{i}"`로. glossary[tk] 생성부(:63-68)에서 `synonyms`·`aliases`를 받고, 통과 필드 튜플 `("status", "candidate")`이 있는 두 곳(:65 근처와 :82-84)에 두 이름을 더한다. 단 status·candidate는 '첫 정의 승자'가 맞지만 표면형은 리스트라 union으로 합친다 — 뒤 atom이 준 표면형을 버리면 게이트 통과권이 사라진다. 기본 키 규약은 순번형 그대로 둔다(D2 개정 답: 아래 T13의 결정 근거 참조).

**검증**: `.venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'` → Ran 78 tests OK (기존 75 + 신규 3). 선택형이라 기존 4곳(:30·:32·:39·:180)의 기대값은 안 바뀐다(실측 확인)

---

## T11 — extract_template.js 스키마·작명 규약 — 용어가 코드 심볼로 기우는 원인 차단

**레포** engine · **선행** 없음

**왜**: 실측으로 편차가 6%~97%다(ingame-item-usage 한국어 term 6% / main-map 97%, 같은 골격·같은 파이프라인). 골격이 심볼을 강제하는 게 아니라 방치한다 — SCHEMAS에서 실제 예시값이 채워진 곳은 code_anchor 하나뿐이고 전부 코드 모양이며, term은 빈 문자열이고 extractPrompt는 TODO다. 백필만 하면 다음 적재에 그대로 재발한다(F 갈래의 핵심).

**파일**: `src/project_brain/templates/ingest/scripts/extract_template.js` · `tests/test_ingest_skill_contract.py`

**red 테스트**: tests/test_ingest_skill_contract.py에 `test_extract_schema_covers_assembler_fields` — extract_template.js의 SCHEMAS 리터럴을 정규식으로 파싱해 glossary_term 키 집합이 {term_key, term, definition, synonyms, aliases}를 덮고, code_anchor 키 집합이 {path, symbol, quote, anchor_key}를 덮는지 단정. 현재 synonyms·aliases·anchor_key가 없어 red.

**변경**: extract_template.js:8을 `glossary_term: { term_key: "kebab", term: "사용자가 부르는 한국어 이름(예: 광선 발사)", definition: "", synonyms: ["다른 한국어 표면형"], aliases: ["KAMEHAMEHA"] }`로. :9에 `anchor_key: "kebab (생략하면 순번 자동)"` 추가. extractPrompt(:22) 위에 상수 `const TERM_NAMING`을 만들어 프롬프트 문자열에 `${TERM_NAMING}`으로 끼운다 — 내용은 세 줄: term은 기획서·QA·사용자가 그 기능을 부르는 한국어 이름으로 쓴다 / 클래스명·메서드명·enum·상수는 term이 아니라 definition 본문이나 aliases로 옮긴다 / `KAMEHAMEHA (광선 발사)`처럼 괄호 병기를 term에 쓰지 않는다(회상 게이트는 표면형 전체를 통째로 찾으므로 병기형은 어떤 자연스러운 질의에도 안 걸린다 — 실측으로 kamehameha 확인 질의 5개 중 3개가 이것 때문에 명부 미매칭이었다). TODO 슬롯을 지워도 규약이 프롬프트에 남게 하는 것이 핵심이다.

**검증**: `.venv/bin/python -m pytest -q tests/test_ingest_skill_contract.py` 통과 + 전체 pytest 통과. JS 테스트 러너가 없어 이 파일을 덮는 기존 테스트는 0개이므로 새 계약 테스트가 유일한 가드다

> **심사 반영 — `anchor_key`를 추출 스키마에 넣지 않는다.** 추출 스키마에 칸이 생기면 추출 작업자가 채운다 — `term` 칸이 빈 문자열이라 코드 심볼이 들어찬 것과 **같은 기제**다(같은 골격에서 한국어 term 비율이 6%~97%로 튄 그 이유). 그러면 다음 적재부터 손으로 붙인 의미형 키가 들어오는데, 유일성 검사와 수동 지정표는 kamehameha의 `domain_spec` 안에만 있고 템플릿에는 없다. 결과: T3의 중복 게이트가 build를 세우고, 적재자는 계획에 없던 '판별어 손 큐레이션'을 처음 만나며, 그 절차가 어디에도 문서화돼 있지 않다.
> → `glossary_term`의 `synonyms`·`aliases`와 `TERM_NAMING` 규약만 넣는다. 앵커 키는 T10의 조립기 선택 입력 + `domain_spec` HOOK 경로로 한정하고, `object-model.md`에 '앵커 키는 순번이 기본, 의미형은 spec HOOK으로만, 그때는 유일성 검사와 수동 지정표가 함께 필요하다'를 적는다.

---

## T12 — finalize·batch 러너가 버리는 진단 4종 전달

**레포** engine · **선행** T6

**왜**: 오진의 직접 원인이다. (1) finalize_ingest.py:290-295가 search payload에서 results만 읽어 needs_clarification을 버린다 — 게이트가 닫혀 reviewed 0건인 경우와 순위가 밀린 경우가 똑같은 리포트로 나온다. (2) :206이 audit 실패를 'audit failed' 한 줄로 접는다(payload에 이유는 남지만 사람이 보라고 지시받은 자리는 errors다 — ingest-tools.md:275). (3) run_ingest_batch가 build/ingest 실패의 stdout을 버리는데 build는 오류 JSON을 stdout에 낸다. (4) 코퍼스 테스트 출력이 2000자로 잘려 앞쪽 실패가 사라진다.

**파일**: `src/project_brain/templates/ingest/scripts/finalize_ingest.py` · `src/project_brain/templates/ingest/scripts/run_ingest_batch.py` · `src/project_brain/templates/ingest/scripts/test_finalize_ingest.py`

**red 테스트**: test_finalize_ingest.py에 2건 — (1) 가짜 러너가 audit을 lint 문제 1건 + code_quotes 실패 2건으로 실패시킬 때 report.errors가 `audit failed: code_quotes 2건(code.k.spawn quote_not_found …), lint 1건, stale ok` 형태를 담는지, (2) recall check가 needs_clarification=true로 실패할 때 recall_reports 항목에 `needs_clarification: true`와 `found_in_candidates`가 담기고 errors 메시지가 '게이트 통과 reviewed 0건' 갈래로 갈리는지. 현재 (1)은 'audit failed', (2)는 needs_clarification 부재라 red.

**변경**: finalize_ingest.py:206을 `_audit_git_state`(:138-168)가 payload["stale"]을 파고드는 것과 같은 모양으로 바꿔 audit·lint payload에서 이유를 뽑는다. :290-295에서 payload의 `needs_clarification`·`candidates`·`raw_excerpts`도 읽어 recall_reports 항목에 `needs_clarification`·`found_in_candidates`·`raw_excerpt_count` 3개를 더하고, needs_clarification=true이면서 missing이 있으면 errors 메시지를 게이트 갈래로 갈라 쓴다. T6의 key_format_warnings를 리포트 최상위 `warnings` 배열로 올린다(errors 옆). run_ingest_batch.py의 `_result_details`(:184-194)가 stdout도 돌려주게 하고 failed 항목에 `stdout[-2000:]`을, 파싱되면 `build_errors`로 승격해 담는다. `_run_command`의 2000자 절단은 유지하되 `FAILED (failures=N)` 요약 줄을 따로 뽑아 둔다.

**검증**: `.venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'` OK

> **심사 반영 — 최상위 `warnings`에 올리는 것은 '이번 적재가 새로 만든 위반'만.** store에 이미 있던 id는 제외한다. 안 그러면 매 적재 리포트에 498줄이 붙어 아무도 안 읽고, 신규 위반이 499번째 줄로 섞인다. 그래야 보통 0줄이 되고 0이 아닐 때만 눈에 들어온다.
> 
> **추가 — 회상 질문 바꿔치기 흔적을 기계로 남긴다.** `finalize_ingest.py:286`의 config에 질문 잠금이 없어 이번 사고의 원인 중 하나가 재발 가능하다. 완전한 잠금은 범위 밖이지만 **'리포트에 이전 질문을 함께 남긴다'**는 여기서 넣을 수 있다.

---

## T13 — 설치되는 문서층 일괄 정정 (G 갈래 전체)

**레포** engine · **선행** T11

**왜**: 거짓 안내·상충하는 압력·설명 부재가 그대로 있으면 다음 적재가 같은 결과를 낸다. 특히 회상 게이트 설명이 설치 문서 전체에 0건이어서('명부'·'anchor_df'·'df 상한' grep 0), 적재자에게 남은 가설이 '색인이 낡았나 / 질의 단어가 어긋났나' 둘뿐이다 — 그 세션이 정확히 그 둘만 돌려 봤다.

**파일**: `src/project_brain/templates/ingest/references/object-model.md` · `src/project_brain/templates/ingest/references/ingest-tools.md` · `src/project_brain/templates/ingest/references/completeness-checklist.md` · `src/project_brain/templates/ingest/references/system-domain-playbook.md` · `src/project_brain/templates/ingest/references/judgment.md` · `src/project_brain/templates/ingest/references/update-rules.md` · `src/project_brain/templates/ingest/references/scope.md` · `src/project_brain/templates/ingest/references/ingest-case-log.md` · `src/project_brain/templates/ingest/scripts/domain_spec.template.py` · `src/project_brain/templates/query/SKILL.md` · `src/project_brain/templates/session-ingest/SKILL.md` · `src/project_brain/templates/session-ingest/references/dev-ingest.md` · `tests/test_ingest_skill_contract.py`

**red 테스트**: tests/test_ingest_skill_contract.py에 토큰 단정 추가 — object-model.md에 '앵커 df'·'명부'·'괄호 병기'·'code_anchors[].key는 유일'이 있고, ingest-tools.md에 'verified_at은 자동값이 없다'가 있고 'created_at/updated_at/verified_at에 자동으로'는 **없고**, query/SKILL.md에 '--db'가 있고 'install.sh'는 **없고**, completeness-checklist.md에 'code_quotes'가 있는지. 그리고 midnight 예시 금지: `T00:00:00`이 domain_spec.template.py·ingest-tools.md에 **없는지**. 전부 현재 red.

**변경**: 한 커밋으로 묶는다. (1) object-model.md:155를 두 문장으로 쪼갠다 — term에는 사용자가 부르는 한국어 이름, 코드 심볼은 definition 본문이나 aliases. 그 아래 synonyms·aliases 배열까지 채우라는 뜻임을 명시. (2) 같은 파일 :149-153을 '엔진이 거부하는 것(strip 후 3글자 미만, blocklist 7개 — 이벤트·아이콘·카테고리·레이아웃·리스트·메시지·프로필)'과 '조언(definition에 이미 있는 표현)'으로 갈라 쓰고, 목록이 명백한 실수만 막는 유한 목록이라 스테이지·레이스·말풍선 같은 고유명은 통과하지만 단독으로 아무 질의에나 걸릴 만큼 흔하면 넣지 않는 판단은 적재자 몫임을 적는다. (3) 같은 섹션 맨 앞에 회상 게이트 설명 4단락을 넣는다 — 게이트 = 명부 통째 부분문자열 매칭 OR 최소 anchor_df≤30 / term 작명이 통과권 / 괄호 병기는 죽은 표면형 / 도메인이 커지면 df가 올라 이전에 열렸던 질의가 나중에 닫힌다. (4) '## 코드 앵커 예외' 앞에 앵커 자격·상한 단락 추가 — 그 매핑의 주장을 확인하는 데 실제로 쓴 위치만, 경유 파일 금지, 5개 넘으면 원자를 쪼갠다, 자격 기준은 '이 앵커의 quote를 지우면 meaning 중 무엇이 근거를 잃는지 한 문장으로 말할 수 있는가'. (5) 같은 섹션에 'code_anchors[].key는 한 노트 안에서 유일해야 한다'(T3가 기계로 막지만 규약도 적는다). (6) :64 뒤에 updates allowlist 표 3행(DomainMapping·GlossaryTerm·DomainContext)과 '그 밖의 kind는 updates로 못 고치고 amend를 쓴다'. (7) completeness-checklist.md:14에 '이 항목은 앵커를 늘리라는 뜻이 아니다 — 근거가 문서·서버 규칙뿐이면 그렇게 적는 것이 통과다'를 붙이고, 게이트 목록에 audit 항목 추가(commands.audit.payload의 lint.problems·stale_status.ok·code_quotes.ok 확인, code_quotes는 verified_quote를 가진 앵커만 검사하므로 현재 코퍼스 기준 3886개 중 579개(15%)만 덮는다는 숫자를 함께 적는다). (8) ingest-tools.md:38-39의 verified_at 자동 안내를 정정문으로 교체(노트가 직접 줘야 하고 누락·빈 값이면 build가 거부, 조립기는 domain_spec.VERIFIED_AT을 쓴다). :110의 `2026-06-04T00:00:00Z`를 `2026-07-27T14:30:00+09:00`로. (9) domain_spec.template.py:17 NOW 주석에서 자정 예시 제거 + '자정 값을 쓰면 실제 작업 시각을 잃는다', :25-26 주석을 VERIFIED_AT 설명으로 교체(코드 앵커를 실제 파일 원문과 대조한 시각, 자동값 없음), :27-28의 '아직 해석하지 않는다'를 사실로 교체(assemble_notes.finalization_contract가 읽는다). (10) system-domain-playbook.md:36-37 필드 목록을 실제 계약으로 통일(glossary_terms[{term_key, term, definition, synonyms, aliases}] 등)하고 :109-110의 EXISTING_TERM_IDS 지시를 refs 섹션 + glossary_term_refs로 교체, :64·:67의 '라인' 제거. (11) judgment.md:3·update-rules.md:22·extract_template.js:10·domain_spec.template.py:14-15·session-ingest/SKILL.md:29의 '사람이 판정'을 검수 정책 B+C 표현으로 통일(근거 확실→에이전트 자동 reviewed / 애매→candidate / 완전히 갈리면 사용자). (12) query/SKILL.md — `--db {{BRAIN_ROOT}}/.brain-local/index.db` 명시(안 주면 recall이 꺼져 reviewed CodeLocator 전량 폴백), :29의 `./{{BRAIN_ROOT}}/install.sh`를 uv tool install 안내로 교체, 4번 절에 needs_clarification 진단 3단(색인 낡음 → 용어 어긋남 → 게이트 닫힘, 3번까지 확인 전에 '없다' 단정 금지), BB2 하드코딩 5곳을 `{{PROJECT}}`로. (13) session-ingest/SKILL.md:4·8의 BB2를 `{{PROJECT}}`로, dev-ingest.md:9의 '라인' 제거. (14) scope.md에 history_coverage×검수상태 조합 표 4행 추가(unsearched+reviewed가 정상이라는 사실을 보이게). (15) ingest-case-log.md에 2026-07-27 두 적재 행 추가 — 앵커 키 형식 거부·노이즈 앵커 77개·대표명 누락.

**검증**: `.venv/bin/python -m pytest -q` 통과(문구 존재를 고정하는 기존 테스트가 함께 갱신됐는지 확인 — 특히 test_semantic_finalization 계열이 ingest-tools.md 토큰을 요구한다). SKILL.md 170행 상한 테스트도 통과해야 하므로 query/SKILL.md 추가분이 상한을 넘으면 references로 뺀다

> **심사 반영 (blocker) — `depends_on`에 T4를 추가한다.** 원안 change 6번이 `object-model.md`에 '`updates`는 세 kind만 받는다'는 표를 넣는데, **같은 릴리스의 T4가 그 문장을 거짓으로 만든다**(`CodeLocator.title`·`EvidenceRef.title` 추가하고 T22가 그 경로로 백필한다). 이번에 고치려던 거짓 안내(`ingest-tools.md`의 `verified_at` 자동)와 **정확히 같은 종류의 결함**이다. 잡히지 않는 이유도 구조적이다 — 원안 `depends_on`은 T11뿐이고 T14의 기계 대조에도 allowlist 항목이 없다.
> → 표에 `CodeLocator | title | (없음)`·`EvidenceRef | title | (없음)` 행을 추가하고 '앵커의 `path`·`symbol`·`quote`는 여전히 `updates`로 못 고친다 — `amend`를 쓴다'를 붙인다. `update-rules.md:54-58`의 CodeLocator 절에도 title을 언급한다(지금은 `path`·`symbol`만 말해서 문서 두 곳을 다 읽어도 정답에 도달하지 못한다).

---

## T14 — 문서-코드 기계 대조 계약 테스트 6종

**레포** engine · **선행** T13

**왜**: test_ingest_skill_contract.py는 문서를 문서와만 비교한다(코드 import는 installer.install 하나뿐). 그래서 '문서에 적힌 필드명이 실제 스키마에 있는가'를 볼 수 없고, 더 나쁘게는 거짓 문장을 보호한다 — 토큰 존재를 고정하니 거짓을 고치는 방향으로는 압력이 없고 지우는 방향으로는 저항이 생긴다. 이번에 찾은 불일치 대부분이 이 6종으로 기계 검출된다.

**파일**: `tests/test_ingest_skill_contract.py`

**red 테스트**: 6개 테스트를 먼저 쓴다 — (1) object-model.md:116·130의 정규식 문자열 == assembly._LOGICAL_KEY_RE.pattern / _ANCHOR_KEY_RE.pattern, (2) object-model.md의 status·source_type·redaction_status·decision_type·spec_reflected·insight_type enum 목록 == schema의 각 VALUES 집합, (3) object-model.md:37-49 kind별 필수 필드 표 == schema.KIND_REQUIRED, (4) extract_template.js SCHEMAS ↔ assemble_notes가 읽는 키 ↔ system-domain-playbook 필드 목록 3자 일치, (5) 설치되는 md의 `project-brain <sub> --flag` 패턴이 cli.py 파서에 실존 + query 예시에 --db 존재, (6) md가 참조하는 상대 경로 파일이 install 결과 트리에 실존. (1)(2)(3)은 현재 우연히 일치하므로 회귀 가드로 green, (4)(5)(6)은 T11·T13 없이는 red.

**변경**: 각 테스트를 파싱 + 집합 비교로 구현한다. 정규식·enum·필수필드는 문서 코드블록/백틱 토큰을 정규식으로 뽑아 코드 상수와 직접 비교한다. (6)은 tempdir에 install한 뒤 md에서 `./`·`scripts/` 상대경로를 걷어 존재 확인.

**검증**: `.venv/bin/python -m pytest -q tests/test_ingest_skill_contract.py` 통과 + 전체 pytest 통과

> **심사 반영 — 7번째 기계 대조를 추가한다.** `object-model.md`의 updates allowlist 표를 파싱해 `assembly._SET_ALLOWLIST`·`_UNION_ALLOWLIST`와 **kind·필드 단위 집합 비교**. 이게 없으면 다음에 allowlist를 손댈 때 같은 어긋남이 또 생기고 아무 테스트도 안 잡는다 — 이번에 실제로 안 잡혔다.

---

## T15 — 엔진 전체 검증 → 커밋 → 워킹트리 청결 확인

**레포** engine · **선행** T1, T2, T3, T4, T5, T6, T7, T8, T9, T10, T11, T12, T13, T14

**왜**: install은 관리 파일 23개를 한꺼번에 갱신하므로, 엔진 레포에 이번 건과 무관한 미완성 템플릿 수정이 남아 있으면 그것까지 bb2로 나간다. 그리고 엔진 코어(T1~T9)는 편집 설치라 이미 `project-brain` 명령에 반영돼 있지만 템플릿(T10~T13)은 파일 사본이라 install이 있어야 반영된다 — 이 경계를 여기서 못 박는다.

**red 테스트**: 해당 없음(검증 관문 task). 실패를 보여줄 명령: `git -C /Users/al03040455/Downloads/codes/project-brain status --porcelain`이 이번 변경 외 항목을 담고 있으면 멈춘다.

**변경**: 엔진 테스트 2종을 돌리고, T1~T14를 논리 단위로 커밋한다(코어 / 템플릿 배관 / 문서 / 계약 테스트 4덩이 권장). pyproject 의존성은 안 바뀌므로 `uv tool install --force`는 불필요. 커밋 후 워킹트리가 비었는지 확인한다.

**검증**: `.venv/bin/python -m pytest -q` → 674+ passed / `.venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'` → OK / `git status --porcelain` → 빈 출력

> **심사 반영 — 엔진 편집 구간은 병렬 세션에 대한 무통보 배포다.** 글로벌 `project-brain`은 이 클론의 편집 설치이고 `_editable_impl_project_brain.pth`가 클론 `src`를 그대로 가리킨다. 그래서 **파일을 저장하는 순간** 다른 세션의 `build`/`ingest`/`audit`, finalize 스크립트, bb2 corpus 가드까지 전부 새 코드로 돈다. 커밋도 install도 필요 없다. 원안은 T1~T14를 '엔진 레포 안의 격리된 작업'처럼 배치했다.
> 구체적 사고 경로: T7 저장 직후 다른 세션이 새 도메인을 적재하면 `context.<새키>` 때문에 실패한다. T2 저장 뒤에는 그 세션 앵커 title이 조용히 symbol로 바뀐다(그 세션은 규약이 바뀐 걸 모른다). T8 저장 뒤에는 갑자기 git blob 대조를 타서 repo-root 해석이 다르면 거부된다. 오늘 실제로 두 세션이 병렬로 돌았고 `mark-checked`가 객체 21개를 건드렸다.
> → 엔진 편집을 **별도 워크트리**에서 하고 검증은 `PYTHONPATH=<워크트리>/src <워크트리>/.venv/bin/python`으로만 한다. 부담이면 최소한 **T1 앞에 '엔진 편집 구간 동안 bb2 적재 금지' 합의 단계를 task로 세우고**, verify에 '그 구간에 bb2에서 돈 ingest가 없음(`brain` git status·파일 mtime)'을 넣는다.
> 
> **추가 — 엔진 해석 경로를 하나로 통일하는 결정을 여기서 못 박는다.** 데이터 단계는 `PYTHONPATH=<engine>/src`를 쓰는데 finalize는 bare `project-brain`·bare `python3`를 부른다(`finalize_ingest.py:189-201`). 지금은 둘이 같은 클론을 가리키지만 다른 checkout이 글로벌 도구를 가로채면 게이트가 조용히 달라진다.

---

## T16 — bb2 재설치 — 엔진↔데이터 레포 경계

**레포** bb2 · **선행** T15

**왜**: 여기가 계획의 경계선이다. bb2의 assemble_notes.py·extract_template.js·문서는 installer 렌더본이라 `project-brain install`을 손으로 돌려야 반영된다. bb2 brain/install.sh:83-85가 install을 의도적으로 빼놨으므로 '설치했다고 착각'이 쉽다. 그리고 bb2 사본을 손으로 고치면 manifest 해시와 어긋나 이후 모든 install에서 영구 skip된다 — 우회 편집은 절대 설치본에 하지 않는다.

**파일**: `/Users/al03040455/Desktop/bb2_client/.project-brain-manifest.json`

**red 테스트**: 설치 전에 `python3 -c` 한 줄로 bb2 사본 assemble_notes.py에 `ca.get("anchor_key")`가 없음을 확인한다 — 있으면 이미 설치됐거나 손편집된 것이다.

**변경**: bb2 루트에서 `project-brain install`. 리포트에서 `updated`에 assemble_notes.py·extract_template.js·object-model.md·ingest-tools.md·completeness-checklist.md·system-domain-playbook.md·domain_spec.template.py·finalize_ingest.py·run_ingest_batch.py·query/SKILL.md·session-ingest/SKILL.md이 들어 있고 `skipped`가 **빈 배열**인지 확인한다. skipped에 뭐라도 있으면 그 파일은 사용자 수정본으로 판정된 것이므로 멈추고 원인을 찾는다(설치 전 실측으로 5개 파일 전부 사용자 미수정임이 확인됐으니 빈 배열이 정상). `references/project-code-verification.md`는 bb2 소유 overlay라 관리 대상이 아니므로 리포트에 안 나오는 것이 정상이다.

**검증**: install 리포트의 skipped == [] 확인 + `grep -c 'anchor_key' /Users/al03040455/Desktop/bb2_client/.agents/skills/bb2-brain-ingest/scripts/assemble_notes.py` → 1 이상 + 두 번째 install에서 created/updated/removed/adopted/skipped 전부 빈 배열(멱등)

---

## T17 — brain 스냅샷 확보 — git으로 못 돌아오는 범위 고정

**레포** bb2 · **선행** 없음

**왜**: kamehameha 456개는 .git/info/exclude의 `/brain` 때문에 git 미추적이라 `git restore`로 안 돌아온다(`git ls-files brain/objects/code | grep -c petskill-kamehameha` → 0, 디스크 180). 게다가 brain은 상시 커밋 상태가 아니다(현재 21개 미커밋: test_real_corpus.py 1 + mark-checked 드리프트 20). 백업본은 kamehameha만 담고 있으므로 title 백필 대상 410개의 원복 수단이 따로 필요하다.

**파일**: `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-07-27/pre-cleanup/`

**red 테스트**: 해당 없음. 실패를 보여줄 측정: `git -C /Users/al03040455/Desktop/bb2_client ls-files brain/objects/code | wc -l`(3706)과 `ls brain/objects/code | wc -l`(3886)의 차 180이 git으로 복구 불가한 범위다.

**변경**: `.snapshots/2026-07-27/pre-cleanup/`에 `brain/objects/`와 `brain/raw/manifests/`를 통째 복사한다. 그리고 기존 백업본(`.snapshots/2026-07-27/ingest-backup`)의 kamehameha 6개 디렉토리가 라이브와 바이트 동일한지 삭제 직전 시점 기준으로 다시 확인한다(파일명 diff 0줄 + cmp 불일치 0개).

**검증**: `ls .snapshots/2026-07-27/pre-cleanup/objects/code | wc -l` → 3886 + 백업 대조 스크립트가 불일치 0 보고

> **심사 반영 — 스냅샷에 `brain/.brain-local/index.db`와 `stale-set.json`을 넣는다.** 빠지면 되돌리기가 파일 복사에서 **실모델 index rebuild**로 승격되고, 그 동안 bb2의 `search`·`query`·`eval`·finalize recall이 전부 stale로 거부돼 **병렬 세션까지 멈춘다**. 둘은 그냥 파일이라 한 번 복사면 끝난다 — 값싼 되돌리기 수단을 스스로 버릴 이유가 없다.
> → rollback도 '(3) rebuild' 대신 **'(3) 스냅샷 `index.db`·`stale-set.json` 되돌리기 → (4) `search`로 stale 오류 없음 확인, 지문이 어긋나면 그때만 rebuild'**로 바꾼다.
> → `isolated_report.md`는 2026-06-23자로 낡았으니(고립 81 vs 현재 15) 스냅샷에 넣지 말고 판정 근거에서 뺀다.

---

## T18 — kamehameha 456객체 삭제 (raw 원문은 남긴다)

**레포** bb2 · **선행** T16, T17

**왜**: D2. 엔진에 객체 퇴역 명령이 없어 파일을 지운다. 이걸 title 백필보다 **먼저** 끝내야 한다 — build로 preconditions를 뜬 뒤 삭제하면 T1 이전에는 좀비가 조용히 부활했고(3건 재현), T1 이후에는 하드 오류로 3879건 작업이 통째로 헛돌기 때문이다. 먼저 지우면 백필 노트 생성 시점에 kamehameha 옛 id가 아예 없어 apply_updates가 'store에 없음'으로 큰소리로 막는다.

**파일**: `/Users/al03040455/Desktop/bb2_client/brain/objects/` · `/Users/al03040455/Desktop/bb2_client/brain/raw/manifests/`

**red 테스트**: 삭제 전 7개 glob의 파일 수 합이 정확히 456인지 센다(code 180 / evidence_refs 203 / domain g 36 / domain context 1 / mappings 25 / decisions 6 / raw/manifests 5). 456이 아니면 멈춘다.

**변경**: 7개 glob을 rm한다: `brain/objects/code/code.petskill-kamehameha.*.json`, `brain/objects/evidence_refs/evref.petskill-kamehameha.*.json`, `brain/objects/domain/g.petskill-kamehameha.*.json`, `brain/objects/domain/context.petskill-kamehameha.json`, `brain/objects/mappings/mapping.petskill-kamehameha.*.json`, `brain/objects/decisions/decision.petskill-kamehameha.*.json`, `brain/raw/manifests/manifest.petskill-kamehameha.*.json`. **`brain/raw/sources/petskill-kamehameha/spec-v1.1.md`는 지우지 않는다** — 실코퍼스 가드의 EXPECTED_RAW_CHUNKS=1586에 이 파일 몫 +9가 들어가 있어 지우면 가드가 깨진다(객체가 아니라 raw 청크 원문이다).

**검증**: `PYTHONPATH=<engine>/src <engine>/.venv/bin/python -m project_brain.cli lint` → problems [] (삭제 시뮬레이션에서 lint 0건·정확히 456개 감소 실측, 외부 참조 0개라 끊긴 참조 없음). 이 시점 검색은 색인이 stale이라 정지 구간에 들어간다 — T20의 rebuild까지 이어서 진행한다

---

## T19 — kamehameha 재조립 — 노이즈 77 제거 · MOVE 1 · meaning 2 · 의미형 키 103 · synonyms · 실시각

**레포** bb2 · **선행** T18

**왜**: D2+D4. 백업본 verify.json으로 재조립하면 patch_sources.py까지 돌렸을 때 기존 notes.json과 바이트 동일함이 실측됐다(코드 재순회 불필요). 여기에 심사 결과(KEEP 102 / DROP 77 / MOVE 1)와 대표명을 얹는다. patch_sources.py를 빼먹으면 EvidenceManifest 5개가 조용히 달라진다 — 대조 스크립트가 실제로 이걸 잡아냈다.

**파일**: `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-07-27/ingest-backup/kamehameha-session/domain_spec.py`

**red 테스트**: 조립 직후 `notes.json`을 열어 (1) `mappings=25 anchors=103 terms=36 decisions=6` 출력, (2) 앵커 키 103개가 전부 `^[a-z0-9]+(?:-[a-z0-9]+)*$` fullmatch이고 유일(충돌 가드가 SystemExit로 죽으면 수동 지정표를 채운다), (3) `g.petskill-kamehameha.kamehameha`의 synonyms에 4개가 실림. 하나라도 어긋나면 멈춘다.

**변경**: domain_spec_v2.py를 만든다(기존 spec 복사 후 수정). HOOK에서 순서대로: (1) `_RENAME_MAPPING` 적용 후 `{mk}--{i}`를 재구성해 drop_anchors.json의 drop 77개와 대조해 제거, (2) MOVE 1건(shot-bubble-sprite--6 → shoot-action)을 목적지 원자의 code_anchors 뒤에 붙임, (3) 살아남은 앵커마다 `anchor_key`를 심는다 — 규칙은 심볼 유래(첫 구분자에서 머리/꼬리 분리 → `::` 마지막 두 조각, 생성자는 클래스+`ctor` → ASCII 식별자 런만 뽑아 camelCase·대문자연속·숫자 경계로 쪼갬 → 소문자, `case` 제거, 이웃 중복 병합 → `{mk}-단어...`를 총 112자 상한에서 단어 단위로 끊음, 단어 0개면 `-anchor`). 이중 하이픈 금지. 자동으로 부딪히는 4개(vs-superpunch-pop-algorithm--0/--2, shooter-beam-effect--7/--8)는 `_ANCHOR_KEY_OVERRIDE` 수동 지정표로 판별어를 준다. 조립 직전 전수 유일성 검사를 넣어 충돌이면 SystemExit. (4) 용어 근거가 첫 앵커 드롭으로 옮겨가는 3개(force-pop-enabled, shooter-throw-beam, bdsk-kamehameha-sounds)는 해당 원자의 code_anchors 순서를 바꿔 정의를 떠받치는 앵커를 0번에 둔다 — 특히 shooter-throw-beam·bdsk-kamehameha-sounds가 붙게 되는 GameBubbleShooterLayer::onEnter(알림 수신 등록)는 정의와 결이 약하므로 사람이 골라 넣는다. (5) prune.json의 meaning_gaps 2건(beam-rect-hit-test, shot-bubble-sprite)의 suggested_sentence를 기존 `_APPEND_MEANING` 사전에 이어 붙인다. (6) `g.petskill-kamehameha.kamehameha`에 synonyms `["광선 발사", "광선발사", "카메하메하"]` + aliases `["kamehameha"]`를 심는다 — 띄어쓰기 두 형태가 모두 필요하다(recall check는 붙여쓴 '광선발사', display_name은 띄어쓴 '광선 발사'. 부분문자열 매칭이라 한쪽만 넣으면 다른 쪽이 죽는다). (7) `NOW = ""`로 비운다 — 재적재는 실제로 객체를 다시 만드는 일이니 엔진이 실행 시각(KST)을 박는 게 맞다. (8) `VERIFIED_AT`·`CAPTURED_AT`은 기존 값 유지 — D4로 재검증을 안 하므로 갱신하면 하지도 않은 검증을 오늘 했다고 주장하는 셈이다(두 값은 비울 수 없다, 엔진이 빈 값을 거부한다). 조립 후 `patch_sources.py notes.json`을 반드시 돌린다.

**검증**: `python3 <bb2>/.agents/skills/bb2-brain-ingest/scripts/assemble_notes.py verify.json domain_spec_v2.py -o notes.json --finalization-out finalization.json` → `mappings=25 anchors=103 terms=36 decisions=6` + `python3 patch_sources.py notes.json` 성공

---

## T20 — kamehameha build → baseline → ingest → finalize (색인 재생성 1회) → 회상 실패 3갈래 분류

**레포** bb2 · **선행** T19, T8

**왜**: D2 완료 단계. finalize가 index rebuild를 첫 명령으로 돌아 T18의 정지 구간을 여기서 닫는다. 그리고 recall_checks는 **ingest 전에 확정하고 이후 바꾸지 않는다** — 지난 세션이 실패한 질문을 게이트 통과형으로 바꿔 ok=true를 만든 기록이 있다(run2 '인게임 아이템 사용 로직은 어디서 실행되나' 실패 → run3 '액티브 아이템 사용을 실제로 실행하는 곳' 통과, 기대 id 동일).

**파일**: `/Users/al03040455/Desktop/bb2_client/brain/objects/` · `src/project_brain/templates/ingest/references/ingest-case-log.md`

**red 테스트**: build 리포트에서 `built: 302`, errors 없음. 그리고 백업 objects.json(456)과 새 objects.json(302)을 `compare_reingest.py`로 대조해 24개 검사 전부 통과 — 같아야 하는 것(DecisionRecord 6·EvidenceManifest 5 시각 뺀 내용 동일, GlossaryTerm 36 term·definition 동일, DomainMapping 25 canonical_summary·boundary 동일, 새 CodeLocator 103개 전부가 옛 앵커와 (path, symbol, verified_quote) 동일한 짝을 가짐)과 달라야 하는 것(synonyms 추가 1, meaning 변경 정확히 2, code_locator_ids 축소 24·증가 0·유지 1, CodeLocator 180→103, EvidenceRef 203→126, 제거된 앵커 근거 75종)을 개수까지 찍어 확인한다. 실패 검출력도 확인됐다 — patch_sources를 빼먹으면 EvidenceManifest 5개 불일치를 정확히 집어낸다.

**변경**: 순서대로: (1) `project-brain build --notes notes.json --objects-file objects.json > build-report.json`, (2) `scripts/finalize_ingest.sh --capture-baseline > isolation-baseline.json` — 반드시 삭제 뒤·ingest 앞, (3) `project-brain ingest --objects-file objects.json --preconditions-file build-report.json`(T8의 quote 게이트가 여기서 신규 103앵커를 실제 git blob과 대조한다, 실측 1.53초), (4) `scripts/finalize_ingest.sh --config finalization.json --baseline isolation-baseline.json > finalize.json`. run_ingest.sh는 patch_sources 단계가 없어 한 방에 못 쓰므로 나눠 돈다. finalize의 recall check 5개는 백업 세션의 원문 질문을 그대로 쓴다(물음표 자연문). 실패한 것은 세 갈래로 분류해 ingest-case-log.md에 적는다 — **게이트 차단**(명부 미매칭 + anchor_df>30, 대표명 보강으로 고침), **순위 밀림**(게이트는 열렸는데 기대 id가 top5 밖), **기대 id 오류**(더 맞는 답이 top5에 있음). 예상: 활성화는 게이트만 막고 있었고(df 47, 게이트 열면 4위) synonyms로 통과, 제거범위는 게이트를 열어도 18위(순위 밀림 — 질의가 '어떤 버블을 제거 대상으로 고르나'인데 5위 pop-target-filter가 이름 그대로 제거 대상 필터라 기대 id 오류 의심), 폭탄연쇄는 게이트가 이미 '방해버블'로 열려 있는데 검수완료 적중 26개 안에 기대 매핑이 없다(순위 밀림 — 일반 방해버블 도메인이 광선발사 전용 매핑을 이긴다). **질문을 바꿔 ok=true를 만들지 않는다.** 순위·기대치 문제는 ok=false 그대로 남기고 로그에 기록한다.

**검증**: ingest `{ok: true, ingested: 302}` + 파일 수 302 + finalize.json에서 index_rebuild ok(indexed 7412→7335 예상, CodeLocator 77개 감소분) / lint problems [] / eval 15/15 / graph isolated 15(변화 없음 — 삭제 후·재적재 후 모두 15, 새로 생긴 고립 0 실측) / audit ok / raw_chunks 1586 불변. 고립 판정은 `project-brain graph isolated` 출력만 쓴다 — `brain/.brain-local/isolated_report.md`는 2026-06-23자로 '고립 81개'라 적혀 있어 근거로 쓰면 오판한다

---

## T21 — 대표명 백필 — 차단 3개 + 경계선 1개 (updates union) → 색인 재생성 2회차

**레포** bb2 · **선행** T20

**왜**: A 갈래의 실측 종착점. 명부에 없고 anchor_df 하나로만 버티다 오늘 적재로 새로 막힌 컨텍스트를 정식 경로로 연다. synonyms는 GlossaryTerm 색인 표면에 들어가 코퍼스 지문을 바꾸므로 rebuild가 **필수**다 — 안 하면 bb2의 search·query·eval·finalize recall check가 전부 StaleIndexError로 죽는다(스크래치에서 실증). 그래서 ingest와 rebuild를 같은 단계에 묶고 rebuild 없이 세션을 끝내지 않는다.

**파일**: `/Users/al03040455/Desktop/bb2_client/brain/objects/domain/`

**red 테스트**: 백필 전 측정으로 실패를 보인다 — `PYTHONPATH=<engine>/src <engine>/.venv/bin/python -m project_brain.cli search "인게임 아이템 사용 로직은 어디서 실행되나"` → needs_clarification true, reviewed 0건. 같은 방식으로 '클리어 토큰 쓰면 점수가 어떻게 되지?', '버디스킬 망치 발동 모션 어떻게 바뀌었어?'도 0건임을 기록한다.

**변경**: 노트 하나에 updates 4~6건을 담아 build→ingest한다. 형식: `{"context": {"key": "<논리키>", "commit": "<sha>"}, "updates": [{"id": ..., "expected_updated_at": "<대상의 현재 updated_at>", "union": {"synonyms": [...]}}]}`. **반드시 union**이다(set은 GlossaryTerm allowlist 밖으로 거부된다). `evidence_unchanged`는 필요 없다(synonyms가 _CLAIM_FIELDS 밖). expected_updated_at은 필수이고 값이 틀리면 build·ingest가 각각 거부하므로 대상 객체의 현재 값을 읽는 스크립트로 만든다. 여러 컨텍스트를 한 노트에 묶어도 안전하다(display_name·boundary_summary를 안 주면 새 DomainContext를 만들지 않는다). 대상: `g.ingame-item-usage.item-standby`에 **"인게임 아이템 사용"**(좁은 안 — 넓은 안 '아이템 사용'은 '출석 아이템 버튼 어디 있어' 같은 혼합 질의 누수를 만드는데, 좁은 안은 문제였던 질의를 그대로 열면서 그 누수를 피한다. 맨 '아이템 사용' 질의는 계속 막히는 것을 감수한다), `g.stage-clear-token.clear-pass-ticket-item`에 `["스테이지 클리어 토큰", "클리어 토큰"]`, `g.petskill-hammer-motion.create-hammer-skill`에 `["망치 스킬", "버디스킬 망치", "망치 발동"]`('망치'만은 2글자라 schema가 막는다), `g.ad-skip-product.no-ad-item`에 `["광고 스킵", "광고 제거"]`(지금 df 24로 겨우 버티는 경계선, 여유 6이라 광고 관련 적재 하나에 닫힌다 → 선제 백필). **enter-popup-ui는 백필하지 않는다** — 이미 synonyms 3개가 있고 실제 질문 4개가 전부 통과한다. display_name '입장(시작) 팝업 UI 개선'만 막히는데 그건 괄호 병기가 부분문자열 매칭을 깨는 것뿐이고, display_name은 질의가 아니다. kamehameha는 T19에서 재적재로 넣었으므로 여기 없다. ingest 직후 같은 단계에서 `project-brain index rebuild`를 돌린다.

**검증**: ingest ok + `project-brain lint` problems [] + rebuild 완료 후 위 red 측정 3개 질의가 reviewed 5건으로 열리는지 재실행(실모델 실측으로 0→5 확인됨). 회귀 확인: s5·s13·s14·s15가 여전히 0건(부재 엔티티 가드 온전), s1·s3·s6·s16·s17이 여전히 5건. 그리고 `project-brain eval` 15/15 유지

> **심사 반영 — 대상에서 `ingame-item-usage`가 빠진다(D1 재결정).** 재조립 때 `synonyms`를 직접 심으므로 여기서는 `g.stage-clear-token.clear-pass-ticket-item`·`g.petskill-hammer-motion.create-hammer-skill` 2개 + 경계선 `g.ad-skip-product.no-ad-item` 1개만 남는다.
> 
> **추가 — verify에 실코퍼스 가드를 넣는다**: `PYTHONPATH=<engine>/src <engine>/.venv/bin/python -m unittest discover -s brain/checks -p "test_*.py"`. stub 임베더로 임시 DB에 재구축하니 실모델 비용이 없다(`test_real_corpus.py:70-76`). 색인 행 수 대조가 여기서 안 돌면 T23까지 미뤄진다.

---

## T22 — title 백필 410건 — 잘린 인용임이 증명되는 집합만 (D3 개정 (b))

**레포** bb2 · **선행** T21, T4

**왜**: D3 개정. 'title != symbol' 3879건 통짜 적용은 기각됐다 — 같은 매핑 안에서 (symbol, path)가 완전히 같아지는 앵커가 1356개(460 매핑)라 6줄이 글자 하나까지 같아지고, 한글 title 932개는 symbol보다 정보량이 커서 덮으면 손실이다. 그래서 '잘린 인용'이라고 기계로 증명되는 집합만 고친다. 색인 표면은 path+symbol이고 content_hash는 표면+status만 해싱하므로 **rebuild가 불필요**하다 — 원본과 title 3879개 교체본의 코퍼스 지문이 완전히 같음을 실측했다(faa1b03e…027a 동일).

**파일**: `/Users/al03040455/Desktop/bb2_client/brain/objects/code/`

**red 테스트**: 대상 집합을 측정으로 확정한다 — (title 길이가 정확히 120인 691건 ∪ title == verified_quote[:120]인 578건) = 1064건에서, title에 한글이 있는 932건과 symbol 괄호 안에 한글이 든 98건과 같은 매핑 안에서 (symbol, path)가 중복되는 1356건을 뺀다. **실측 결과 507건**(44개 컨텍스트, 상위 ingame-item-usage 224 / petskill-kamehameha 97 / main-map 84 / ball-select 31). kamehameha 97건은 T20에서 이미 새 title=symbol로 재적재됐으므로 빠져 **최종 410건**이다. 백필 전 표본 3건의 title이 코드 조각임을 출력해 남긴다.

**변경**: 노트 생성 스크립트를 짠다 — 대상 410개마다 현재 updated_at을 읽어 `{"id": ..., "expected_updated_at": ..., "set": {"title": <그 객체의 symbol>}}`을 만든다. 노트 생성→build→ingest를 **한 스크립트로 붙인다**(사람 검토는 사전 표본 dry-run으로 옮긴다) — build 리포트가 stdout으로 42680줄/1.65MB가 나올 수 있으니 반드시 `> report.json`으로 파일에 받는다. 병렬 세션이 대상 중 하나라도 건드리면 preconditions 불일치로 통째로 죽으므로(부분 저장은 없어 데이터는 안전하다) 컨텍스트 단위로 쪼개 재작업 단위를 작게 한다 — 성능 이유는 없다(전량도 build 0.05초/ingest 0.91초). 백필 동안 bb2 brain에 다른 세션이 쓰지 않도록 사전에 합의한다(객체 쓰기에 락이 없다). 제외된 것들: 같은 매핑 안 (symbol, path) 중복 226건은 잘린 인용이 유일한 판별자라 그대로 둔다(D3 개정 (c) 결론 — 라벨 구분은 T5의 라우터 보강으로 해결하고, 중복 라벨을 만들지 않는다), 한글 title 932건과 괄호 한글 symbol 98건은 out_of_scope로 기록한다(98건은 '라인 2158' 같은 좌표를 품고 있어 옮기면 폐기한 줄번호가 답변 라벨로 승격된다).

**검증**: ingest ok + 재로드 후 대상 410건의 title == symbol 확인 + `project-brain lint` problems [] + **코퍼스 지문 불변 확인**(`compute_corpus_fingerprint` 백필 전후 비교) → rebuild 불필요 + `project-brain search "쐐기 발아 인접 팝"`이 stale 오류 없이 ok:true. 부작용 기록: 대상 410개의 updated_at이 적재 시각으로 바뀌고 파일이 다시 써진다(content_hash는 불변이라 색인 영향 없음)

> **심사 반영 — 대상이 507건에서 186건으로 줄고, verify를 목록 파일 동치로 바꾼다.**
> (1) **규모 축소**: D1 재결정으로 `ingame-item-usage` 224 + `petskill-kamehameha` 97 = **321건이 재적재로 처리된다**(엔진 폴백이 build 시점에 `title=symbol`을 넣는다). 남는 건 **186건**. 최종 수는 재적재 후 다시 측정한다.
> (2) **숫자 정정**: 원안 본문의 507/97/98은 재현값 **509/99/94**다.
> (3) **verify를 숫자 동치에서 목록 동치로**: 백필 직전에 대상 id 목록을 `.snapshots/2026-07-27/title-backfill-targets.json`으로 떨어뜨리고, verify는 '그 파일의 모든 id가 `title==symbol`이고 **파일 밖 CodeLocator는 title이 변하지 않았다**'를 확인한다. 숫자 동치로 두면 규칙 구현이 조금 달라졌을 때 실행자가 숫자를 조용히 맞추는 쪽으로 갈 여지가 있고, 그러면 무엇을 백필했는지가 사후에 재구성 불가능해진다.
> (4) **범위 확대 판단 (미결)**: 좁은 규칙으로는 코드조각 title 2950개 중 **2441개(83%)가 남는다**. 사유는 잘린 증거 없음 2170 / 중복 226 / 괄호 45. 2170개는 `verified_quote`가 없어(2261개가 아예 없다) '잘렸음'을 기계로 증명할 수 없을 뿐 내용은 명백히 코드다(예: `if(pParentBB && dynamic_cast<BubbleObjectDisturbDandelion*>(pParentBB)`). → 범위를 **'코드처럼 보이는 title'**(`;`·`{`·`}`·`->`·`::`·`==`·`if(`·`return ` 중 하나를 품고 한글 없음)로 넓히되 **중복 226과 괄호 45는 계속 제외**한다. 표본 200개로 오판율을 재고 넘어간다. 넓히지 않기로 하면 `out_of_scope`에 2170개를 **숫자와 예시까지** 적는다.
> (5) **verify에 `brain/checks` 추가** + change에 '대상 CodeLocator가 어떤 ContextProjection의 `source_object_ids`에 들어 있는지 먼저 확인하고, 있으면 `project-brain projection refresh`를 함께 돌린다' 한 줄. `source_content_hash`는 시각 메타만 빼고 다 해싱하므로, 소스에 CodeLocator가 든 projection이 하나라도 생기면 title 백필이 그걸 조용히 stale로 만들어 색인에서 떨어뜨린다.

---

## T23 — 골든셋 s18~s21 추가 + 실코퍼스 가드 개수 갱신

**레포** bb2 · **선행** T22

**왜**: 게이트가 열린 것을 회귀로 고정한다. 지금 s7('스테이지 클리어 토큰은 어떤 기획 배경...')은 검수완료 채널이 닫힌 상태(adf 33)로 raw 발췌만으로 통과하고 있었다 — 골든셋이 게이트 차단을 못 보고 있었다는 뜻이다. 기대 id는 rebuild 후 실측값으로 확정해야 한다(순위가 흔들린다).

**파일**: `/Users/al03040455/Desktop/bb2_client/brain/eval_scenarios.json` · `/Users/al03040455/Desktop/bb2_client/brain/checks/test_real_corpus.py`

**red 테스트**: 시나리오를 먼저 추가하면 `brain/checks/test_real_corpus.py:110`의 `assertEqual(len(self.scenarios), 15)`가 실패한다 — 이게 red다(의식적 갱신을 강제하는 가드다).

**변경**: scenarios 배열 끝에 4개 추가(비어 있는 번호가 s8·s10·s18 이후이니 혼동을 피해 s18~s21). **s18-item-usage-domain-name**: query는 run2에서 실패해 바꿔치기된 원문 그대로 '인게임 아이템 사용 로직은 어디서 실행되나', expect.top5_any에 item-standby 계열 매핑 여러 개를 후보로 열거한다(단일 id로 쓰면 안 된다 — 게이트 고침은 '아무 답도 없음'을 '맞는 컨텍스트의 다른 핀포인트'로 바꿔주는 것까지이고, 실측에서 열린 5건에 item-standby-execute-delegation이 없었다). **s19-kamehameha-beam-name**: '광선발사는 어떤 버블을 제거 대상으로 고르나?', 기대 id는 T20 재적재 후 실측으로 확정. **s20-hammer-motion-name**: '버디스킬 망치 발동 모션 어떻게 바뀌었어?'. **s21-clear-token-short-name**: '클리어 토큰 쓰면 점수가 어떻게 되지?'. 같은 커밋에서 test_real_corpus.py:110의 15를 19로 올린다. 부재 엔티티 안전망은 추가하지 않는다 — 백필 전후로 s5·s13·s14·s15가 전부 0건 유지임을 확인했다. 혼합 질의('핼러윈 클리어 토큰 이벤트 뭐였지' 0→5건)는 명부 OR 보강의 설계된 동작이라 no_answer 시나리오로 넣으면 안 된다.

**검증**: `PYTHONPATH=<engine>/src <engine>/.venv/bin/python -m unittest discover -s brain/checks -p "test_*.py"` 통과 + `PYTHONPATH=<engine>/src <engine>/.venv/bin/python -m project_brain.cli eval` → 19/19

> **심사 반영 — 기대 id는 재적재·백필·rebuild가 전부 끝난 뒤 실측으로 확정한다.** 원안의 제안값은 백필 전 색인 기준이라 그대로 쓰면 실패한다. s19(kamehameha)와 item-usage 시나리오는 재적재가 선행이다. 그리고 D1 재결정으로 item-usage 시나리오도 재적재 후 기준이 된다.

---

## T24 — 지식층 정정 — bb2 메모리 · ROADMAP 조건 · 사례 로그

**레포** bb2 · **선행** T23

**왜**: D 갈래. 메모리의 메커니즘 설명이 틀렸다('여러 컨텍스트에 걸치는 토큰은 점수가 분산돼 게이트를 못 넘는다'). 점수는 충분했다 — '인게임 아이템 사용 로직은 어디서 실행되나'의 융합 top 점수가 0.030118로 reviewed 바닥 0.005의 6배였고 막은 건 앵커뿐이다(최소 df 38 + 명부 미매칭). 틀린 설명을 두면 다음에 또 색인·질의만 의심한다. 그리고 ROADMAP의 명부 게이트 절은 '게이트를 고쳤다'만 적고 '명부가 채워져야 작동한다'는 조건을 안 적었다 — 그 조건 미충족이 이번 사고다.

**파일**: `/Users/al03040455/.claude/projects/-Users-al03040455-Desktop-bb2-client/memory/brain_search_gate_drops_abstract_query.md` · `ROADMAP.md` · `src/project_brain/templates/ingest/references/ingest-case-log.md`

**red 테스트**: 해당 없음(문서 작업). 실패를 보여줄 측정: 메모리 원문에서 '점수가 분산돼'를 grep하면 나오고, ROADMAP의 명부 게이트 절(≈291-300)에서 '명부가 비면'·'대표명'을 grep하면 0건이다.

**변경**: 메모리는 frontmatter의 name·metadata를 두고 description과 본문을 교체한다 — 게이트 두 조건(명부 통째 부분문자열 매칭 OR 최소 anchor_df≤30), 정정 1(점수 분산이 아니다, 실측 수치 포함), 정정 2(구체 표현이 통하는 이유는 구체적이어서가 아니라 희소 토큰이 끼어서다 — '아이템 버튼 터치 게이팅'은 최소 df 19라 통과), 진짜 해결책은 명부 채우기(정식 경로 updates union, expected_updated_at 필수, evidence_unchanged 불필요, 넣은 뒤 index rebuild 필수), 골든셋·recall_checks는 실제 질문으로 쓰고 게이트 통과하도록 다듬는 것은 금지, display_name은 질의가 아니다(enter-popup-ui 허상 사례). 그리고 대표명 하나가 만능이 아님을 적는다 — 백필해도 '아이템 객체 상속 계층'(adf 41)·'게임 아이템'(adf 209)·'인게임 상태 전이 로직 있나'(adf 99)는 여전히 닫힌다. ROADMAP의 명부 게이트 절에 조건 3줄 추가: 이 게이트는 명부(GlossaryTerm term+synonyms+aliases)가 채워진 만큼만 작동한다 / 2026-07-27 현재 GlossaryTerm 1181개 중 synonyms 보유 32개(2.7%)이고 추출·조립 배관이 표면형을 버려 왔다(T10·T11에서 닫음) / 컨텍스트 대표명이 명부에 없으면 잘 적재된 도메인도 그 이름으로 물었을 때 답이 빈다. 2026-07-06의 백필로 넣은 세 표면형은 되돌리면 안 되는 의존 지점임을 함께 못 박는다 — `g.disturb-bubble-system.create-bubble-object-disturb`의 ['방해버블']이 3개 컨텍스트의 유일한 통과권이고, `g.luckybox-contents.popup-luckybox-info`의 ['럭키박스']는 골든셋 s16·s17이 걸려 있다. 사례 로그(T13에서 시작한 행)에 이번 정비 결과와 recall check 3갈래 분류를 마무리로 적는다.

**검증**: 메모리 파일에서 '점수가 분산돼' grep 0건 + ROADMAP에서 '명부가 채워진 만큼만' grep 1건 + ingest-case-log.md에 2026-07-27 행 2개 존재

---
## T25 — item-usage 재조립 대조 dry-run (읽기 전용)

**레포** bb2 · **선행** 없음 — **가장 먼저 돌린다**

**왜**: D1 재결정(백필만 → 재적재)의 유일한 미확인 전제다. kamehameha는 백업
`verify.json`으로 재조립하면 기존 `notes.json`과 **바이트 동일**함이 실측됐지만
item-usage는 그 대조를 아직 안 돌렸다. 이게 통과하면 재적재는 안전한 기계 작업이고,
어긋나면 왜 어긋나는지부터 봐야 한다(D4 — 코드 재순회는 하지 않는다).

**파일**: `.snapshots/2026-07-27/ingest-backup/item-usage-session/ingest/` (읽기만)
— `verify.json` · `verify-raw.json` · `domain_spec.py` · 축별 원자 6개(`axis-*.json`) · `atoms-summary.md`

**측정 (red 대신)**: 라이브 객체 실측값이 기준선이다 —
`code 393 / evidence_refs 393 / domain 92(글로서리 91 + 컨텍스트 1) / mappings 66 /
decisions 0 / insights 0 / raw manifests 1` = **945개**.

**변경**: 아무것도 안 바꾼다. 스크래치 사본에서만 돈다.
1. 백업 `ingest/`를 스크래치로 복사한다.
2. 그 세션이 쓴 조립기로 `assemble_notes.py verify.json domain_spec.py -o notes.json`.
   **주의**: item-usage 세션은 ingest를 3회 돌렸다(`ingest-run2.log`·`ingest-run3.log`).
   백업 `domain_spec.py`가 **마지막 회차 것인지 먼저 확인한다** — 아니면 재조립 결과가
   라이브와 어긋나는데 그건 결함이 아니라 입력 불일치다.
3. `build --notes notes.json --objects-file objects.json`.
4. kamehameha에서 쓴 `compare_reingest.py`와 같은 모양으로 라이브 945개와 대조한다 —
   **같아야 하는 것**(GlossaryTerm 91의 term·definition, DomainMapping 66의
   `canonical_summary`·`boundary`, CodeLocator 393의 `(path, symbol, verified_quote)`)과
   **달라야 하는 것**(`verified_at` 자정 → 실시각, 앵커 키)을 개수까지 찍는다.

**검증**: 대조 스크립트가 '같아야 하는 것' 전부 일치를 보고한다.
불일치가 나오면 **T26 이후를 착수하지 않고** 원인을 먼저 본다.

> **미결 — 노이즈 앵커 목록의 출처.** kamehameha는 심사 결과가
> `drop_anchors.json`·`prune.json`으로 백업에 남아 있는데 **item-usage 백업에는 그에 해당하는
> 파일이 없다**. "노이즈 23개(6%)"는 그 세션 스냅샷 본문에서 읽은 숫자다.
> 목록을 스냅샷에서 복원할 수 있는지 T25에서 함께 확인하고, 없으면
> **앵커 구성은 그대로 두고 키·시각만 정상화한다**(D4 정신: 순회한 데이터 자체는 참이다).
> 앵커 심사를 처음부터 다시 하는 것은 이번 범위가 아니다.

---

## T26 — item-usage 945객체 삭제

**레포** bb2 · **선행** T25(대조 통과) · T17(스냅샷) · T20(kamehameha 재적재 완료)

**왜**: D1. 순번형 키 393개와 자정 `verified_at` 393개는 백필로 못 고친다 —
id는 파일명이자 참조 대상이고 `verified_at`은 `updates` allowlist 밖이다.
**T20이 끝난 뒤에 시작한다** — 삭제부터 재적재 finalize의 rebuild까지가 검색 정지 구간이라
두 재적재의 정지 구간을 겹치지 않게 한다.

**red 대신 측정**: 삭제 전 glob별 파일 수 합이 **945**인지 센다(위 T25의 분포).
945가 아니면 멈춘다.

**변경**: glob으로 삭제한다 — `brain/objects/code/code.ingame-item-usage.*.json`,
`brain/objects/evidence_refs/evref.ingame-item-usage.*.json`,
`brain/objects/domain/g.ingame-item-usage.*.json`,
`brain/objects/domain/context.ingame-item-usage.json`,
`brain/objects/mappings/mapping.ingame-item-usage.*.json`,
`brain/raw/manifests/manifest.ingame-item-usage.*.json`.
**`brain/raw/sources/` 아래 원문은 지우지 않는다** — 실코퍼스 가드의
`EXPECTED_RAW_CHUNKS`에 그 몫이 들어가 있어 지우면 가드가 깨진다(객체가 아니라 raw 청크다).

**검증**: `lint` problems `[]` + 정확히 945개 감소.
**되돌리기가 kamehameha보다 안전하다** — 945개 전부 git 추적이라
`git restore brain/objects/ brain/raw/manifests/`로 커밋 `d1294e7032` 상태로 정확히 돌아온다.

---

## T27 — item-usage 재조립 (의미형 키 · 실시각 · synonyms)

**레포** bb2 · **선행** T26

**왜**: D1+D4. 재조립으로 순번 키·자정 시각·코드조각 title이 한 번에 정상화된다
(title은 엔진 폴백이 build 시점에 `symbol`을 넣는다 — T2).

**red 대신 측정**: 조립 직후 `notes.json`에서 (1) 매핑·앵커·용어 수가 T25 대조 기준과 맞는지,
(2) 앵커 키가 전부 `^[a-z0-9]+(?:-[a-z0-9]+)*$` fullmatch이고 **유일**한지,
(3) `g.ingame-item-usage.item-standby`의 `synonyms`에 대표명이 실렸는지. 하나라도 어긋나면 멈춘다.

**변경**: `domain_spec_v2.py`를 만든다(백업 spec 복사 후 수정). HOOK에서:
1. 노이즈 목록이 복원됐으면 제거, 아니면 앵커 구성 유지(T25의 미결 항목 참조).
2. 살아남은 앵커마다 `anchor_key`를 심는다 — 규칙은 T19와 같은 심볼 유래.
3. `g.ingame-item-usage.item-standby`에 `synonyms: ["인게임 아이템 사용"]`.
   **좁은 안이다** — 넓은 안 '아이템 사용'은 '출석 아이템 버튼 어디 있어' 같은 혼합 질의
   누수를 만드는데, 좁은 안은 문제였던 질의를 그대로 열면서 그 누수를 피한다.
   맨 '아이템 사용' 질의가 계속 막히는 것은 감수한다.
4. `VERIFIED_AT`을 **실제 검증 시각**으로 준다. 자정 값을 다시 쓰지 않는다.

**검증**: `assemble_notes.py verify.json domain_spec_v2.py -o notes.json
--finalization-out finalization.json` 성공 + 위 측정 3개 통과.

> **미결 (착수 전 결정 필요) — 키 충돌이 kamehameha보다 훨씬 크다.**
> 실측: 같은 매핑 안에서 `(symbol, path)`가 완전히 같아지는 그룹이 **60개, 그 안 앵커 156개,
> 최대 그룹 6개**다(`mapping.ingame-item-usage.item-enum-class-factory-switch`의 `--0`~`--5`가
> 전부 `ItemManager::makeBeforeAndInGameItemObject`). 심볼 유래 키만으로는 **156개가 충돌한다** —
> kamehameha는 수동 지정표 4개로 끝났는데 여기서는 그럴 수 없다.
> 선택지: (a) 충돌 그룹 안에서만 `-1`·`-2` 순번을 뒤에 붙인다(읽을 수 있는 부분은 살리고
> 판별자만 기계로 붙임), (b) quote에서 판별어를 뽑는다(예: `return-superball`),
> (c) 그 60개 그룹은 순번형을 유지한다. **(a)를 권한다** — 기계로 결정되고 유일성이 보장되며,
> `ItemManager::makeBeforeAndInGameItemObject`라는 정보는 남는다.

---

## T28 — item-usage build → baseline → ingest → finalize (색인 재생성)

**레포** bb2 · **선행** T27 · T8

**왜**: D1 완료 단계. finalize가 index rebuild를 첫 명령으로 돌아 T26의 정지 구간을 닫는다.

**red 대신 측정**: build 리포트의 `built` 수가 T25 대조 기준과 맞고 errors가 없다.
그리고 T25의 대조 스크립트를 **다시** 돌려 라이브 대비 '같아야 하는 것/달라야 하는 것'을 확인한다.

**변경**: T20과 같은 순서 —
`build` → `finalize_ingest.sh --capture-baseline`(반드시 삭제 뒤·ingest 앞) →
`ingest --objects-file --preconditions-file`(T8의 quote 게이트가 신규 앵커를 git blob과 대조) →
`finalize_ingest.sh --config finalization.json --baseline …`.
**회상 확인 질문은 `ingest-run2.log`의 원문을 쓴다** — run3에서 게이트 통과형으로 바꿔치기된
문구('액티브 아이템 사용을 실제로 실행하는 곳')를 쓰지 않는다. 원문은
'인게임 아이템 사용 로직은 어디서 실행되나'다. 실패는 세 갈래(**게이트 차단** / **순위 밀림** /
**기대 id 오류**)로 분류해 `ingest-case-log.md`에 적고, **질문을 바꿔 `ok=true`를 만들지 않는다.**

**검증**: ingest `ok: true` + 파일 수가 조립 결과와 일치 + finalize의 `index_rebuild` ok /
`lint` problems `[]` / `eval` 통과 / `graph isolated` 증가 0 / `audit` ok / `raw_chunks` 불변.
고립 판정은 `project-brain graph isolated` 출력만 쓴다 —
`brain/.brain-local/isolated_report.md`는 2026-06-23자라 근거로 쓰면 오판한다.

---

## 되돌리기 · 범위 밖

[리포트 5.4·5.5](../reports/2026-07-27-two-ingest-session-review.md)에 있다.
요점: 엔진은 `git revert`(편집 설치라 즉시 반영), kamehameha는 **백업본만**이 원본
(`/brain` exclude로 git 미추적), item-usage는 `git restore`로 정확히 복구,
색인·stale 캐시는 T17 스냅샷에서 파일로 되돌린다(실모델 rebuild 회피).

---

## T5b — 색인 없는 폴백의 무더기 적재 (결정 대기, 후순위)

**레포** engine · **선행** 없음 · **상태** 경고는 넣었고 자르기는 **결정 대기**

**넣은 것 (2026-07-27)**: 폴백으로 전량 적재했을 때 경고를 남긴다 —
`색인 없이 회상이 꺼져 검수완료 CodeLocator N개를 전량 적재했다`.
상태 계산·provenance를 안 건드려서 위험이 없고, 받는 쪽이 `--db` 누락을 즉시 안다.
테스트: `test_fallback_implementation_section_omits_locator_details`.

**안 넣은 것과 이유**: 목록 자체를 자르는 것. `object_ids`는 곧 `source_ids`이고
`needs_clarification` 판정과 `claim_statuses` 집계의 입력이다. 그냥 자르면
**잘려나간 것 중 `restricted`·`raw-unavailable`이 있었을 때 답변이 실제보다 깨끗한 상태를
주장한다** — 상한을 잘못 넣는 것이 안 넣는 것보다 나쁘다. 그리고 '표시만 자르기'도 반쪽이다:
`source_object_ids`에 전량이 남아 출력이 여전히 크다.

**결정해야 할 것**: 색인 없이 구현위치를 물었을 때 답을 주는 것이 맞는가.
- **(A) 폴백에서 구현위치를 답하지 않는다** — `색인 없이는 구현위치를 좁힐 수 없다`로 fail-closed.
  가장 정직하다. `_implementation_locators` docstring이 이 폴백의 존재 이유를 '색인 없는 tmp store
  **테스트** 보존'이라고 적어 놨고, 실사용(bb2)은 항상 색인이 있다. 영향: 색인 없는 라우터 테스트 일부.
- **(B) 표시 상위 N + `truncated`, 상태·provenance는 전량** — 출력이 여전히 크다(반쪽).
- **(C) 경고만(현 상태)** — T13이 문서에 `--db`를 박으면 실사용 노출은 줄어든다.

**권고**: T13(문서 `--db`)을 먼저 넣어 실사용 노출을 없애고, 그 뒤 **(A)**를 검토한다.
지금 (C)로 두어도 조용한 실패는 없다.
