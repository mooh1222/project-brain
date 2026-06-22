# BB2 Brain 범용 적재 인프라 (ingest + promote) Implementation Plan

> ⚠ **[2026-06-04 정정 — 적재 범위 폐기]** 이 plan의 샐리 적재 범위("lifecycle/state spine 용어로 제한" — L18·57·260·269·279·290·364)는 **폐기**됐다. brain은 **도메인 무관 인프라 + 풀 객체 모델**(TemporalFact·EventLedgerRecord·DecisionRecord·GlossaryTerm·DomainMapping·EvidenceManifest/Ref·CodeLocator)이고, 샐리 재추출은 `spec-v8.md` **전반을 기능/규칙 단위로 풀 모델 적재**한다(별도 재추출 plan). "spine 용어만"은 첫 적재 때 예시 몇 개였지 범위가 아니다(사용자 교정). **도구 구현 Task 1~5는 완료·유효** — 이 정정은 적재 범위(Task 6 / §7 AC)에만 적용. 근거: base `ingest-interview` L100 정정.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 도메인 무지(domain-agnostic)한 범용 적재 부품 두 개 — `ingest(objects)`(검증→무결성 lint→쓰기 원자성)와 `promote(ids, scope)`(candidate→reviewed 승격 + ReviewRecord 생성) — 과 공용 헬퍼(`base()`/ReviewRecord 조립)를 만든다. 그다음 **샐리 카누를 폐기 코드 베끼기가 아니라 살아있는 소스(`spec-v8.md` + develop의 `SallyCanoe/` 코드 + git 이력)를 구현 에이전트가 직접 읽어 새로 추출**하고, 그 새 데이터를 generic `ingest`/`promote`로 적재한 뒤, 무결성 거부·멱등·후퇴가드·lint clean·cli 회상까지 **그 새 데이터로** 검증한다.

**이 plan의 전제 (지난 세션 방향 재조정 반영):**
- 브레인은 현재 **엔진 코드만 남고 데이터·테스트 0**이다(이전 테스트 7 + fixture 7 = 14파일 삭제, staged). 이 plan은 **삭제된 이전 테스트·fixture·임시 데이터를 일절 참조·재활용하지 않는다.**
- 도구 검증에 쓰는 데이터는 (a) 도구 단위 테스트는 도메인 이름 없는 **새 중립 합성 데이터**, (b) end-to-end 검증은 **새로 추출한 실데이터(샐리 카누)**. 둘 다 이번에 새로 만든다 — 옛 fixture 부활 아님.
- 폐기 스크립트 코드(`git show`)는 **promote/base 로직을 generic 부품으로 흡수할 때의 출처**로만 본다. 샐리 "데이터"를 테스트로 베끼는 용도가 아니다(그게 지난 세션 거부 지점).

**Architecture:** 이미 있는 범용 부품은 그대로 재사용한다 — `save_object`(객체별 validate + write, `store.py:57-68`), `BrainStore.__init__/load/get/has/by_kind/all`(`store.py:8-33`), `validate_object`(18 kind, `schema.py:109-223`), `lint_store(store, workspace_root=None)`(전수 무결성, `lint.py:79-219`), `QueryRouter.answer`+`cli.py`(질의 전용). 새로 더하는 것은 (1) 신규 모듈 `ingest.py`의 `ingest(brain_root, objects)` — bundle 전체에 validate → merged store lint → save를 원자적으로 묶고, reviewed→candidate 후퇴 가드를 진입점에 둔다. (2) 신규 모듈 `promote.py`의 `promote(objects, ids, scope, ...)` — `build_reviewed_terms`(single_object)와 `bundle_confirmed` 토글+`build_bundle_review`(mapping_bundle)를 흡수한 generic 승격. (3) 공용 헬퍼 모듈(`base()`/ReviewRecord 조립). (4) `cli.py`에 ingest 서브커맨드 배선.

**Tech Stack:** Python 3, `unittest` + `pytest` 실행, per-file JSON store. 게임 런타임과 분리된 `scripts/bb2_brain/` 프로토타입. 폐기 스크립트(4개)와 그 바인딩 테스트(4개)는 **커밋 `1af5b69ef9`에서 삭제됨**(영구) — 흡수 대상 로직은 `git show 1af5b69ef9^:scripts/bb2_brain/<file>`로만 참조. **이전 엔진 테스트 7개(`test_router/lint/schema/store/intent/status/context_projection`) + fixture 7개는 워킹트리에서 staged 삭제(미커밋) → 워킹트리 기준 테스트 0개. 단 HEAD `1af5b69ef9`엔 살아있어 `git restore`로 복원 가능(거취는 위 OPEN DECISION).** 이 plan이 새로 작성하는 모든 테스트는 자기완결(self-contained)이며 삭제된 테스트에 의존하지 않는다.

**Spec:** `docs/superpowers/specs/2026-06-04-bb2-brain-universal-ingest-design.md`

**Base (설계 근거 — 세션 대화로 좁히지 말고 항상 여기로 복귀):** `~/Desktop/vault/wiki/bb2-client/bb2-brain-design-hub.md`(권위 순서 #10 universal-ingest), `~/Desktop/vault/wiki/bb2-client/2026-06-02-bb2-brain-redesign-ingest-interview.md`(L92 입력=완성코드+기획서+git+세션, L93 첫 대상=샐리 카누 develop 기준, L95 흐름=candidate→검토→reviewed·파이프라인 반복가능, ~~L99 첫 샐리 범위=lifecycle/state spine~~ → ⚠ L100 정정으로 폐기: 범위가 아니라 예시였고, 적재는 풀 객체 모델로 spec 전반).

---

## ✅ RESOLVED (2026-06-04 사용자 결정) — 엔진 테스트는 삭제 유지, 필요 시 현재 기준 새로

**결정: 삭제한 엔진 테스트 7개는 복원하지 않는다(옵션 a). 검사가 필요하면 그때 현재 코드 기준으로 새로 작성한다.** 근거: 이 plan은 엔진 모듈(intent/status/router/schema/lint/store)을 건드리지 않고 새 모듈만 얹으므로 작업 중 회귀 위험이 없고, "몽땅 삭제 + 새롭게" 방향과 일치한다. 아래 git 사실·성격 분석은 결정 근거로 보존한다.

★정확한 git 사실 (적대 리뷰 + 직접 재확인):★ 이 7개는 **커밋에서 사라진 게 아니다.** 커밋 `1af5b69ef9`는 폐기 스크립트 4 + 그 바인딩 테스트 4(8파일)만 지웠고, 엔진 테스트 7개는 HEAD(`1af5b69ef9`)에 그대로 있다(`git cat-file -e`로 7개 전부 확인). 7개 + fixture 7개의 삭제는 **워킹트리의 staged 미커밋 변경**(git status `D`)이라 `git restore --staged --worktree scripts/bb2_brain/tests/` 한 줄로 즉시 되살릴 수 있다. 즉 "처음부터 재작성"만이 선택지가 아니다.

★성격이 갈린다 (되살릴 때 임시데이터 문제 여부 — `git show HEAD:` grep 직접 확인):★
- `test_intent` · `test_status` — 샐리/스테이지 임시데이터 **전혀 안 씀**(도메인 매치 0, 순수 엔진 로직). 되살려도 사용자가 거부한 임시데이터와 무관.
- `test_router`(도메인 82회) · `test_lint`(50회, `test_router` import) · `test_context_projection`(37회, `test_router` import) — 샐리/스테이지 **임시데이터에 깊이 묶임**. 되살리면 지운 임시데이터가 테스트에 부활.
- `test_schema`(33회) · `test_store`(6회) — 중간.

지난 세션에서 사용자가 "test 코드 몽땅 삭제 + 검증 새롭게"라 했으나, 그 맥락의 거부 대상은 "**새 도구 검증을 옛 샐리-데이터 테스트에 기대는 것**"이었다. 순수 엔진 테스트(`test_intent`/`test_status`)까지 영구히 버리는 게 의도였는지는 base에 없는 **진짜 열린 결정**이다. 새 도구는 이 엔진(`validate_object`/`lint_store`/`BrainStore`/`QueryRouter`)을 그대로 재사용하므로 무회귀 상태는 도구 신뢰성에 직접 영향을 준다.

| 후보 | 내용 | 트레이드오프 |
|---|---|---|
| (a) 삭제 유지·전부 새로 | staged 삭제 그대로 커밋, 검증은 새 도구 테스트 + 실데이터 e2e로만 | 가장 깨끗한 단절. 단 엔진 특화 동작(intent 경계·§9 충돌·§6.2 인과·G11b) 회귀가 한동안 빔 |
| (b) 임시데이터 없는 것만 복원 + 나머지 새로 (**추천**) | `test_intent`/`test_status`는 `git restore`로 복원(임시데이터 무관), 임시데이터 묶인 5개는 삭제 유지 + 새 도구 테스트·실데이터 e2e가 안 닿는 엔진 특화 동작만 새 중립데이터로 보강 | 잃을 필요 없는 회귀는 지키고 임시데이터는 배제. 단 "어디까지 보강"의 경계를 인터뷰에서 정해야 함 |
| (c) 전부 복원 후 임시데이터만 리팩터 | 7개 다 복원 후 샐리/스테이지 데이터를 새 중립데이터로 교체 | 회귀 최대 보존. 단 임시데이터 제거 작업이 큼 |
| (d) 전부 재작성 | 삭제 유지 + 7개를 새 데이터로 다시 작성 | 안전하나 이미 동작하던 커버리지를 처음부터 |

**확정: (a) 채택.** plan 본문(Task 1~7)이 가정한 그대로 — 엔진 테스트 0에서 출발, 새 도구 테스트 + 샐리 재적재 e2e로만 검증한다. Task 8(엔진 보강)은 **제거**한다. 구현 중 특정 엔진 동작 검사가 필요해지면 그때 현재 코드 기준 중립 데이터로 새로 추가한다(별도 사전 task 없음).

---

## 핵심 설계 결정 (정밀화 — spec 설계 변경 아님, gaps 해소)

spec이 "구현 디테일=plan 결정"으로 명시 위임한 항목만 여기서 확정한다. 설계 방향은 spec 그대로.

| 결정 | 내용 | 근거 (spec §) |
|---|---|---|
| **promote 시그니처** | `promote(objects, ids, scope, *, bundle_key=None, reviewer, reviewed_at)`. `objects`=현재 bundle 객체 리스트(또는 id→obj), `ids`=승격 대상 id, `scope ∈ {"single_object","mapping_bundle"}`. `bundle_key`는 `mapping_bundle`일 때만 필수(없으면 ValueError). `reviewer`/`reviewed_at`은 **caller 주입**(generic 헬퍼에 도메인/시점 상수를 박지 않음). 반환=`(promoted_objects, review_records)` 튜플. **review_record의 `created_at`/`updated_at`은 `reviewed_at`을 재사용**(`review_record` 헬퍼는 BASE_REQUIRED상 둘 다 필수 — `schema.py:5-8` — 이고 promote 시그니처에 별도 timestamp 파라미터가 없으므로). | §3.2, §3.3 |
| **ingest 입력/원자성** | `ingest(brain_root, objects)` — bundle 전체에 1) per-object `validate_object` → 2) `BrainStore.load(brain_root).all()` + bundle을 id→obj로 merge(같은 id는 bundle이 기존 덮음)한 `BrainStore`에 `lint_store(store)`(workspace_root 미전달) → 3) 통과 시에만 `save_object` 루프. 어느 게이트든 실패하면 `IngestError` raise하고 **아무것도 안 씀**. | §3.1, §4.2 |
| **후퇴 가드 (유일 신규 로직)** | merge 전, bundle의 각 객체에 대해 on-disk 동일 id가 `status=="reviewed"`인데 incoming이 `status=="candidate"`면 거부. candidate→reviewed(승격)·reviewed→reviewed(멱등)·신규는 허용. ingest 진입점에 위치(`save_object`는 dumb writer 유지). | §4.1 |
| **promote title 문구** | generic promote는 status/`updated_at`/`review_record_id` 갱신 + (single_object 한정) `candidate` 키 통째 pop만. GlossaryTerm 전용 `"Reviewed term: "` 접두사(`source.py:379`)와 mapping `"Candidate mapping: X"→"Mapping: X"`(`mappings.py:110`)는 **흡수하지 않음** — title 문구는 caller가 bundle에 미리 박는다. title 내용은 schema/lint 무검사(존재만 요구, `schema.py:5-8`)라 결과 동등. | §3.2 (마지막 문단 명시) |
| **review_record evidence_refs** | single_object review_record는 승격 객체의 `evidence_refs`를 복사(`source.py:395`). mapping_bundle review_record는 generic은 **빈 리스트로 둔다**(caller가 명시 주입 않는 한 `base()` default `[]`). 폐기 `build_bundle_review`의 도메인 3값 하드코딩(`mappings.py:195`)은 흡수 안 함. schema·lint dangling 검사 무영향(빈 list)이고 회상은 mapping의 `evidence_refs`로 동작. | §3.2 |
| **e2e 재적재 방식** | 구현 에이전트가 살아있는 소스를 읽어 candidate bundle 1개를 추출 → `ingest` 1회 → `promote(single_object, [spine term 1개])` 결과 ingest → `promote(mapping_bundle, mapping ids, bundle_key=...)` 결과 ingest. 단일/묶음 승격 두 경로를 각각 한 번씩 태운다. | §7 AC2 |

---

## File Structure

- **Create** `scripts/bb2_brain/objbase.py` — 공용 `base(obj, *, tags, created_at, updated_at, schema_version="0.1", poc_priority="P0")` + `review_record(...)` 헬퍼. 세 폐기 `base()`(`source.py:34-45`, `mappings.py:33-44`, `seed_first_slice.py:38-51`)가 중복하던 setdefault 묶음. **status default 없음**(§3.3). 도메인 상수 0.
- **Create** `scripts/bb2_brain/promote.py` — `promote(objects, ids, scope, *, bundle_key=None, reviewer, reviewed_at)`. single_object/mapping_bundle 2모드. `build_reviewed_terms`(`source.py:370-397`) + `bundle_confirmed` 토글(`mappings.py:124-126`) + `build_bundle_review`(`mappings.py:180-196`) 흡수. 도메인 상수 0.
- **Create** `scripts/bb2_brain/ingest.py` — `ingest(brain_root, objects)` + `IngestError`. validate→merged lint→save 원자성 + 후퇴 가드. 도메인 상수 0.
- **Modify** `scripts/bb2_brain/cli.py` — argparse 서브파서로 `ingest` 서브커맨드 추가. 기존 query 경로는 무변경 호환 유지(AC6).
- **Create** `scripts/bb2_brain/tests/test_objbase.py` — 새 중립 합성 데이터.
- **Create** `scripts/bb2_brain/tests/test_promote.py` — 새 중립 합성 데이터.
- **Create** `scripts/bb2_brain/tests/test_ingest.py` — 새 중립 합성 데이터.
- **Create** `scripts/bb2_brain/tests/test_universal_ingest_e2e.py` — 샐리 카누 **새 추출** 실데이터 end-to-end.
- **임포트 규약:** 신규 모듈(`objbase`/`promote`/`ingest`)은 엔진과 동일하게 `from scripts.bb2_brain.X` **절대 임포트**를 쓴다(상대 임포트 금지). 근거: 엔진 전부와 `store.py:60`(`from scripts.bb2_brain.schema import ...`)가 절대 임포트이고 검증 명령이 레포 루트 `pytest scripts/bb2_brain/tests/`라, 상대 임포트는 ImportError를 낸다.
- **읽기 전용 입력 (Task 6 새 추출의 소스 — 살아있는 것):** `~/Desktop/vault/inbox/dumps/sally-canoe/spec-v8.md`(기획서), `LineBubble2/Classes/main/Event/SallyCanoe/`(develop 코드: `model/SallyCanoeEventModel.{hpp,cpp}`, `presenter/SallyCanoeViewData.{hpp,cpp}`, `model/SallyCanoeEventManager.{hpp,cpp}` 등), git 이력. **설계 참고(베끼기 아님):** `docs/superpowers/specs/2026-06-02-bb2-brain-sally-canoe-real-ingest-design.md`(충실한 샐리 도메인 형태 — 완성도 대조용).

---

## Task 1: objbase.py — 공용 base() + ReviewRecord 헬퍼

**목표:** 세 폐기 스크립트가 중복하던 `base()`(공통 기본 필드 setdefault)를 caller 파라미터화한 단일 헬퍼로 만든다. status default는 빼서(§3.3) generic 부품이 도메인/시점에 무지하게 한다. ReviewRecord 조립도 헬퍼화한다.

**spec_ref:** §3.3

**Files:**
- Create: `scripts/bb2_brain/objbase.py`
- Test: `scripts/bb2_brain/tests/test_objbase.py` (새 중립 합성 데이터 — 인라인 dict)

**빨강 (작성할 실패 테스트):**
- `test_base_fills_defaults_via_setdefault`: `base({"id":"x","kind":"GlossaryTerm"}, tags=["t"], created_at=T, updated_at=T)` 결과에 `schema_version=="0.1"`, `poc_priority=="P0"`, `created_at==T`, `tags==["t"]`, `evidence_refs==[]`가 있음.
- `test_base_does_not_default_status`: `base(...)` 결과에 `"status"` 키가 **없음**(`assertNotIn("status", ...)`) — §3.3 핵심 발산점.
- `test_base_does_not_overwrite_caller_fields`: caller가 `evidence_refs=["a"]`, `status="reviewed"`를 미리 박으면 그대로 보존(setdefault 동작).
- `test_review_record_assembles_required_fields`: `review_record(rid, target_object_id="g.x", reviewer="user-confirmed", reviewed_at=T, verdict="approved", tags=[...], created_at=T, updated_at=T)` 결과가 `validate_object`를 통과(빈 list). `kind=="ReviewRecord"`, `truth_role=="review"`, `status=="reviewed"`.

**빨강 검증 동작:** `validate_object`(schema.py)에 통과시켜 헬퍼 산출물이 스키마 정합임을 단언. status 미주입은 `assertNotIn`으로 확인.

**초록 (구현):**
`objbase.py`에 두 함수.
```python
def base(obj, *, tags, created_at, updated_at, schema_version="0.1", poc_priority="P0"):
    defaults = {"schema_version": schema_version, "poc_priority": poc_priority,
                "created_at": created_at, "updated_at": updated_at,
                "tags": tags, "evidence_refs": []}
    for k, v in defaults.items():
        obj.setdefault(k, v)
    return obj
```
근거: 세 폐기 base()의 defaults 교집합(`source.py:35-43`/`mappings.py:34-42`/`seed_first_slice.py:39-50` git show 확인). `tags`·timestamp는 caller 파라미터(발산점), `status`는 default 안 함(`seed_first_slice.py:42`만 가졌던 `status="reviewed"`를 generic에서 제거).
`review_record(rid, *, target_object_id=None, target_object_ids=None, reviewer, reviewed_at, verdict, tags, created_at, updated_at, title="검수 기록", truth_role="review", **extra)`: `base()`로 공통 채우고 `kind="ReviewRecord"`, `status="reviewed"`, `verdict`/`reviewer`/`reviewed_at` 박고 `extra`(review_scope/bundle_key/confirmation_key/review_type 등) merge. 근거: `source.py:385-396` + `mappings.py:180-196` inline literal 두 개를 한 헬퍼로.

**검증:** `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_objbase.py -q` → PASS (4 tests).

---

## Task 2: promote.py — single_object 모드 (build_reviewed_terms 흡수)

**목표:** candidate 객체를 reviewed로 승격하는 generic `promote`의 single_object 모드. `build_reviewed_terms`(`source.py:370-397`)의 정확한 변환을 흡수하되 GlossaryTerm 전용 title 문구는 제외(§3.2).

**spec_ref:** §3.2 (Mode single_object)

**Files:**
- Create: `scripts/bb2_brain/promote.py`
- Test: `scripts/bb2_brain/tests/test_promote.py` (새 중립 합성 데이터)

**빨강 (작성할 실패 테스트):**
- `test_single_object_promotes_candidate_glossary`: candidate GlossaryTerm(`status="candidate"`, `candidate={candidate_state:"ready_for_review", candidate_source:"spec", promotion_criteria:[...]}`) 1개를 `promote(objs, [id], "single_object", reviewer="user-confirmed", reviewed_at=T)`. 반환 promoted: `status=="reviewed"`, `"candidate" not in obj`, `updated_at==T`, `review_record_id=="review."+id`. 반환 review_records: 1개, `target_object_id==id`(단수), `verdict=="approved"`, `reviewer=="user-confirmed"`, `reviewed_at==T`, `evidence_refs`가 승격 객체 것 복사.
- `test_single_object_promoted_passes_schema`: promoted + review_record 둘 다 `validate_object`==[] (candidate 키 pop 덕에 reviewed GlossaryTerm 거부 안 됨, `schema.py:173-177`).
- `test_single_object_drops_conflict_candidate`: `candidate_state=="conflict"` + `conflicts_with` 가진 candidate 승격하면 pop 덕에 `validate_object`==[].
- `test_single_object_does_not_rewrite_title`: caller가 안 바꾸면 title 원본 유지(generic이 `"Reviewed term: "` 안 박음).
- `test_single_object_unknown_id_raises`: bundle에 없는 id를 주면 KeyError/ValueError.

**초록 (구현):**
`promote(objects, ids, scope, *, bundle_key=None, reviewer, reviewed_at)`에서 `scope=="single_object"` 분기. id→obj 인덱스 만들고 각 id에 대해:
```python
reviewed = dict(obj); reviewed["status"]="reviewed"; reviewed["updated_at"]=reviewed_at
reviewed.pop("candidate", None)
review_id = "review." + reviewed["id"]; reviewed["review_record_id"]=review_id
rr = review_record(review_id, target_object_id=reviewed["id"], reviewer=reviewer,
                   reviewed_at=reviewed_at, verdict="approved",
                   tags=reviewed.get("tags", []), created_at=reviewed_at, updated_at=reviewed_at,
                   evidence_refs=reviewed.get("evidence_refs", []))
```
근거: `source.py:374-396` 한 줄씩 흡수. `title` 줄(`:379`)은 흡수 안 함(§3.2). `review_scope` 미설정 → schema가 single_object로 취급하고 `target_object_id` 요구(`schema.py:221-222`).

**검증:** `... -m pytest scripts/bb2_brain/tests/test_promote.py -q` → PASS.

---

## Task 3: promote.py — mapping_bundle 모드 (bundle 토글 + build_bundle_review 흡수)

**목표:** mapping 묶음을 한 review bundle로 승격하는 mapping_bundle 모드. `bundle_confirmed=True` 토글(`mappings.py:124-126`)과 `build_bundle_review`(`mappings.py:180-196`)를 흡수.

**spec_ref:** §3.2 (Mode mapping_bundle)

**Files:**
- Modify: `scripts/bb2_brain/promote.py`
- Modify: `scripts/bb2_brain/tests/test_promote.py` (새 중립 합성 데이터)

**빨강 (작성할 실패 테스트):**
- `test_mapping_bundle_promotes_all_members`: candidate DomainMapping 2개를 `promote(objs, [m1,m2], "mapping_bundle", bundle_key="bundle.x", reviewer="user-confirmed", reviewed_at=T)`. 각 promoted: `status=="reviewed"`, `review_record_id=="review.bundle.x"`(공유), `review_state=={"meaning_reviewed":True,"evidence_reviewed":True,"projection_reviewed":True}`(implementation_reviewed **키 부재**), `"candidate" not in obj`.
- `test_mapping_bundle_builds_single_review_record`: 반환 review_records 1개. `review_scope=="mapping_bundle"`, `review_type=="meaning_review"`, `target_object_ids==[m1,m2]`(복수), `bundle_key=="bundle.x"`, `confirmation_key=="bundle.x"`, `id=="review.bundle.x"`.
- `test_mapping_bundle_passes_schema`: promoted mapping들 + bundle review record 모두 `validate_object`==[] (`schema.py:216-220` target_object_ids+confirmation_key 충족, review_state 부분키 허용 `schema.py:198-208`).
- `test_mapping_bundle_requires_bundle_key`: `bundle_key=None`으로 호출 시 ValueError.

**초록 (구현):**
`scope=="mapping_bundle"` 분기. `bundle_key` 없으면 `raise ValueError`. 각 mapping:
```python
m = dict(obj); m["status"]="reviewed"; m["updated_at"]=reviewed_at
m["review_record_id"]="review."+bundle_key
m["review_state"]={"meaning_reviewed":True,"evidence_reviewed":True,"projection_reviewed":True}
```
근거: `mappings.py:124-126`. `implementation_reviewed`는 dict에서 통째 생략. title은 caller가 박은 값 유지. 단일 bundle review는 `review_record("review."+bundle_key, target_object_ids=list(ids), reviewer=reviewer, reviewed_at=reviewed_at, verdict="approved", created_at=reviewed_at, updated_at=reviewed_at, review_type="meaning_review", review_scope="mapping_bundle", bundle_key=bundle_key, confirmation_key=bundle_key, tags=...)`. `evidence_refs`는 안 넘겨 `base()` default `[]`. 근거: `mappings.py:180-196`.

**검증:** `... -m pytest scripts/bb2_brain/tests/test_promote.py -q` → PASS(전체 promote).

---

## Task 4: ingest.py — validate→merged lint→save 원자성 + 멱등 + 후퇴 가드

**목표:** bundle을 받아 per-object validate → merged store lint → save를 원자적으로 묶는 단일 진입점. 멱등 갱신 허용 + reviewed→candidate 후퇴 가드(유일 신규 로직)를 진입점에 둔다.

**spec_ref:** §3.1, §4.1, §4.2

**Files:**
- Create: `scripts/bb2_brain/ingest.py`
- Test: `scripts/bb2_brain/tests/test_ingest.py` (새 중립 합성 데이터 — tempfile brain root + 인라인 객체 dict 번들. 삭제된 `test_store.py`를 참조하지 않고 자기완결로 작성)

**빨강 (작성할 실패 테스트):**
- `test_ingest_writes_valid_bundle`: 자기완결 bundle(EvidenceManifest 1 + EvidenceRef 1 + candidate GlossaryTerm 1, 참조가 모두 bundle 내)을 `ingest(root, bundle)`. 성공 후 `BrainStore.load(root)`로 각 객체 회수.
- `test_ingest_rejects_schema_violation_writes_nothing`: base 필드 빠진 객체 섞으면 `IngestError` + `root`에 아무 파일도 안 생김(원자성 §4.2).
- `test_ingest_rejects_dangling_link_writes_nothing` (AC3): mapping이 store에도 bundle에도 없는 `glossary_term_id`를 가리키면 `IngestError` + 무쓰기 (`lint.py:146-158`).
- `test_ingest_idempotent_overwrite` (AC4): 같은 candidate 객체 두 번 ingest → 둘째도 성공(write_text 덮어쓰기, `store.py:67`).
- `test_ingest_allows_candidate_to_reviewed` (AC4): candidate로 ingest 후 같은 id를 reviewed로 ingest → 성공(승격은 후퇴 아님). reviewed로 넣을 때 가리키는 review_record_id도 같은 bundle에 포함해 lint 통과.
- `test_ingest_rejects_reviewed_to_candidate_demotion` (AC4 가드): reviewed로 ingest(자기완결) 후 같은 id를 candidate로 ingest → `IngestError` + 기존 reviewed 보존.
- `test_ingest_reviewed_to_reviewed_ok`: reviewed 객체를 다시 reviewed로 ingest(멱등) → 성공.
- `test_ingest_merges_existing_store_for_lint`: 기존 store에 glossary term, 새 bundle의 mapping이 그 기존 term을 가리킴 → merge 후 lint 통과(§3.1 step2 merge 검증).

**빨강 검증 동작:** 무쓰기는 `IngestError` 후 `BrainStore.load(root).all()`이 비었거나 기존값 그대로임을 단언. 후퇴 가드는 reviewed→candidate에서만 raise, 다른 3분기(신규/candidate→reviewed/reviewed→reviewed) 성공을 매트릭스로 단언.

**초록 (구현):**
```python
class IngestError(RuntimeError): ...

def ingest(brain_root, objects):
    # 1) per-object schema validation (bundle 전체 선검사)
    errors = []
    for obj in objects:
        errors.extend(validate_object(obj))
    if errors: raise IngestError("; ".join(errors))
    # 후퇴 가드 (유일 신규 로직): on-disk reviewed를 candidate로 덮으려 하면 거부
    existing = BrainStore.load(brain_root)  # 빈 디렉토리면 빈 store
    for obj in objects:
        if existing.has(obj["id"]):
            prev = existing.get(obj["id"])
            if prev.get("status") == "reviewed" and obj.get("status") == "candidate":
                raise IngestError(f"{obj['id']}: refuse reviewed→candidate demotion")
    # 2) merged store lint (workspace_root 미전달 = 참조 무결성만)
    merged = {o["id"]: o for o in existing.all()}
    for obj in objects: merged[obj["id"]] = obj   # bundle이 기존 덮음(멱등)
    problems = lint_store(BrainStore(merged))
    if problems: raise IngestError("; ".join(problems))
    # 3) 통과 후에만 쓰기
    for obj in objects:
        BrainStore.save_object(brain_root, obj)
```
근거: §3.1 순서, `BrainStore.load/all/has/get`(`store.py:14-33`), `BrainStore(merged)` ctor(`store.py:8`), `lint_store(store)` workspace_root 미전달(`lint.py:79,138-139`), `save_object`(`store.py:57`). 후퇴 가드는 현존 안 하는 신규 로직(§4.1). load는 한 번만(가드+merge 같은 `existing` 재사용).
**주의 (의도적 중복 — 제거 금지):** step1의 per-object `validate_object`는 step2 `lint_store` 내부 validate(`lint.py:84-85`)와 중복 실행된다. 기능 버그가 아니라 의도된 선검사 — 신규 객체 스키마 에러를 merge·후퇴가드 전에 선제 격리해 (a) 에러 메시지 품질을 높이고 (b) 후퇴 가드가 "validate 통과한 객체"에만 도는 전제를 보장한다. "lint가 어차피 잡으니 step1 제거"로 오판하지 말 것.

**검증:** `... -m pytest scripts/bb2_brain/tests/test_ingest.py -q` → PASS.

---

## Task 5: cli.py ingest 서브커맨드 (query 경로 무변경 보존)

**목표:** ingest를 CLI 서브커맨드로 노출. 기존 query 경로(`cli.py --brain-root <q>`)는 깨지 않는다(AC6 회상이 이 경로로 검증되므로).

**spec_ref:** §3.1 (CLI subcommand)

**Files:**
- Modify: `scripts/bb2_brain/cli.py`
- Test: `scripts/bb2_brain/tests/test_ingest.py` (CLI smoke 추가) 또는 신규 `test_cli.py`. **삭제된 fixture(`tests/fixtures/stage_clear_token_brain/`)를 쓰지 않고 tempfile에 새 객체를 적재해 검증.**

**빨강 (작성할 실패 테스트):**
- `test_cli_query_path_unchanged`: tempfile store에 새 객체 몇 개 적재 후 query 인자로 `main` 호출(또는 subprocess) → answer JSON이 나옴. argparse 서브파서 전환이 query 호환을 안 깼는지 단언.
- `test_cli_ingest_subcommand_writes`: `ingest` 서브커맨드로 bundle JSON을 넘기면 `ingest()`가 호출되고 store에 적재됨.

**초록 (구현):**
argparse를 `add_subparsers`로 전환하되 **기존 query 호환 유지**(서브커맨드 없는 위치인자 query를 default 동작으로, 또는 `query` 서브커맨드 + 무서브커맨드 fallback). 입력 형식은 §3.1이 plan 위임 → **`--objects-file <path>`(JSON 배열) + `--brain-root`**로 단순화. ingest 분기는 `objects=json.loads(path)` 후 `ingest(brain_root, objects)` 호출, 결과/에러를 JSON으로 출력.
근거: 현재 `cli.py:9-23`은 query 전용. AC6은 query 경로 무변경 요구.

**검증:** `... -m pytest scripts/bb2_brain/tests/test_ingest.py -q`(+ test_cli) → PASS.

---

## Task 6: 샐리 카누 **새 추출** end-to-end 적재 (AC2 — 실데이터 authoring + generic 부품)

**목표:** 폐기 도메인 스크립트 없이 generic `ingest`/`promote`만으로 샐리 카누를 적재한다. 이 task는 코드가 아니라 **살아있는 소스를 읽어 객체를 새로 추출 + 부품 조합**이다.

**★이 task의 핵심 원칙 (지난 세션 거부 지점 회피):**
- 구현 에이전트가 **`spec-v8.md` + develop `SallyCanoe/` 코드 + git 이력을 직접 읽어** candidate bundle을 추출한다. 코드를 닻으로 기획서·이력을 종합한다(base ingest-interview L95).
- **폐기 스크립트(`git show`)나 원본 real-ingest spec의 객체 덤프를 베껴오지 않는다.** 폐기 스크립트는 promote/base **로직** 흡수의 출처일 뿐, 샐리 **데이터** 출처가 아니다.
- 객체 종류·대략 개수는 아래 인벤토리를 **목표 형태**로 참고하되, 실제 필드 값(term/synonyms/avoid, 코드 path·symbol·line, 의미 경계, decision)은 소스를 읽어 채운다. **추측 금지 — 소스에 있는 것만 적는다. 휘발/부재 소스는 비워 표시(base L95).**
- ⚠ **[폐기 — 상단 정정 참조]** ~~도메인 범위는 lifecycle/state spine으로 제한~~. 실제 적재 범위 = `spec-v8.md` 전반을 **기능/규칙 단위로 풀 객체 모델**(도메인 무관 인프라). UI 컴포넌트·팝업 세부·QA 이슈명을 evidence/code locator에 두는 원칙 자체는 유효하나, 그게 "용어를 spine으로 제한"한다는 뜻은 아니다.

**spec_ref:** §7 AC1, AC2

**Files:**
- Create: `scripts/bb2_brain/tests/test_universal_ingest_e2e.py`

**소스 (읽기 전용):** `~/Desktop/vault/inbox/dumps/sally-canoe/spec-v8.md`, `LineBubble2/Classes/main/Event/SallyCanoe/model/SallyCanoeEventModel.{hpp,cpp}` · `presenter/SallyCanoeViewData.{hpp,cpp}` · `model/SallyCanoeEventManager.{hpp,cpp}`, git 이력. 완성도 대조 참고(베끼기 아님): `docs/superpowers/specs/2026-06-02-bb2-brain-sally-canoe-real-ingest-design.md`.

**적재 객체 인벤토리 (목표 형태 — lifecycle/state spine):**

*단계 1 — candidate bundle 1회 ingest:*
| kind | 대략 개수 | 내용 (소스에서 추출) |
|---|---|---|
| EvidenceManifest | 2 | 기획서(spec-v8) manifest, 코드 manifest |
| EvidenceRef (spec) | 여러 | spec-v8.md의 lifecycle/state 관련 라인 인용 (basic info, dummy NPC, race state, cooldown 등 — 실제 라인은 읽어서 확정) |
| CodeLocator | 여러 | develop 코드 앵커 (EventModel parse, ViewData state/racers, EventManager 등 — path + symbol + line_start/line_end, locator_source="rg") |
| EvidenceRef (code) | 여러 | 각 CodeLocator를 가리키는 code evidence ref |
| DomainContext | 1 | `context.sally-canoe` (status=reviewed, glossary_term_ids=candidate 전부, review_record_id 없음 정상 — `lint.py:102-104`/`108-111`) |
| GlossaryTerm (candidate) | spine 용어 수 | 레이스 단계/상태·더미 NPC·선착순·쿨타임·반복참여 등. candidate 메타(candidate_state/candidate_source/promotion_criteria). 의미 충돌 발견 시 candidate_state="conflict"+conflicts_with로 표시(승격 안 함) |
| DecisionRecord | 여러 | naming/race-status/participant/cooldown 등 결정 (status=reviewed, spec_reflected, affected_mapping_ids) |
| DomainMapping (candidate) | 여러 | 용어↔기획의미↔결정↔코드앵커 묶음 (status=candidate, glossary_term_ids/decision_record_ids/code_locator_ids/evidence_refs는 단계1 객체 가리킴) |

→ merge 후 한 번에 lint라 한 bundle·1회 ingest로 충분(적재 순서 무관). **정확한 개수보다 lint clean(관계 정합)이 게이트.**

**★코드 닻 주의 (적대 리뷰가 develop 코드 직접 확인 — 추출 시 반영):**
- **레이스 상태 enum이 둘 공존**한다: 서버 파싱용 `SALLY_CANOE_RACE_STATUS{IDLE,RACING,RACE_END,COOLTIME,FINISHED}`(`model/SallyCanoeEventModel.hpp:14-32`)와 표시용 `SallyCanoeViewData::State{READY,RACING,COOLDOWN,ENDED}`(`presenter/SallyCanoeViewData.hpp:38`). `presenter/SallyCanoeViewData.cpp:24-40`에서 IDLE→READY, COOLTIME→COOLDOWN, **RACE_END·FINISHED 둘 다 →ENDED**로 접힌다(5→4). 추출 시 두 enum을 GlossaryTerm spine에 둘 다 두고, 이 접힘(특히 RACE_END/FINISHED→ENDED)을 DomainMapping/DecisionRecord 추출 대상으로 잡는다 — plan이 의도한 `candidate_state="conflict"` 시연의 좋은 실증 후보다.
- **쿨타임 표면어 철자**: 코드가 `COOLTIME`(EventModel)·`COOLDOWN`(ViewData) 두 철자, 기획서는 '쿨타임'. 해당 GlossaryTerm `synonyms`에 셋(`COOLTIME`/`COOLDOWN`/`쿨타임`) 다 넣어야 Task 7 회상 전제2(표면어 substring 매칭)가 안 깨진다.
- **8c drift 주의**: reviewed DomainMapping이 `affected_mapping_ids`를 가진 decision을 자기 `decision_record_ids`에 안 실으면 `lint.py` 8c(drift)가 발화해 AC5(lint clean)가 깨진다 — candidate 단계부터 mapping↔decision을 정합하게 묶을 것.

*단계 2 — single_object 승격 (+1 ReviewRecord):* spine term 1개를 `promote(bundle, [term_id], "single_object", reviewer="user-confirmed", reviewed_at=T)` → reviewed + `review.<term_id>`. 둘을 ingest. **어느 term을 올릴지는 도구와 무관한 경로 시연 — 실제 운영에선 검토자가 결정. e2e는 단일 승격 경로를 한 번 태우는 게 목적.**

*단계 3 — mapping_bundle 승격 (+1 ReviewRecord):* mapping ids를 `promote(bundle, [mapping ids], "mapping_bundle", bundle_key="bundle.sally-canoe.domain-mapping", reviewer="user-confirmed", reviewed_at=T)` → mapping들 reviewed + `review.bundle.sally-canoe.domain-mapping`. ingest.

**빨강 (작성할 검증):**
- `test_e2e_candidate_ingest` (AC2 단계1): bundle ingest 성공. load 후 mapping들 `status=="candidate"`, glossary들 `status=="candidate"`.
- `test_e2e_promote_glossary` (AC2 단계2): single_object 승격 후 ingest. 대상 term `status=="reviewed"` + `review.<term_id>` 존재.
- `test_e2e_promote_mapping_bundle` (AC2 단계3): mapping_bundle 승격 후 ingest. mapping들 `status=="reviewed"`, 모두 `review_record_id=="review.bundle.sally-canoe.domain-mapping"`. bundle ReviewRecord 1개 존재.
- `test_e2e_no_domain_constants` (AC1): `ingest.py`/`promote.py`/`objbase.py` 소스 텍스트에 `"sally"`·`"canoe"`·`"bundle.sally"` 등 도메인 id가 **없음**을 단언(범용부품 도메인 상수 0).

**빨강 검증 동작:** 각 단계 후 `BrainStore.load(tempfile root)`로 status·id·review_record_id 단언. AC1은 모듈 소스 파일을 열어 도메인 문자열 부재 단언.

**초록 (구현):** 신규 도구 코드 없음 — Task 1~5 부품 조합 + **소스를 읽어 bundle dict authoring**. bundle은 테스트 파일 안에 인라인 dict로 조립(헬퍼 `objbase.base`/`review_record` 사용 가능, 도메인 값은 소스에서 읽어 채움).

**검증:** `... -m pytest scripts/bb2_brain/tests/test_universal_ingest_e2e.py -q` → PASS.

> **범위 명확화:** spec §5 "two deprecation shapes" 중 direct-reviewed seed form(stage-clear-token 58객체)은 §7 AC에 재적재 항목이 없다. "promote 없이 ingest 단독으로 reviewed bundle 통과" 경로는 Task 4 `test_ingest_reviewed_to_reviewed_ok` + 단계1의 reviewed DomainContext/Decision이 이미 커버한다. 별도 58객체 seed 재적재 task는 만들지 않는다(AC 밖).

---

## Task 7: regression + lint clean + cli 회상 (AC1/3/4/5/6 최종 검증 — 새 데이터로)

**목표:** 전체 테스트 회귀 통과 + 새로 적재한 샐리 store lint clean + cli query로 샐리 도메인 회상까지 묶어 모든 AC를 종단 검증. **삭제된 `test_router.py` 등 이전 테스트에 일절 의존하지 않고**, Task 6에서 새로 적재한 store만으로 회상을 검증한다.

**spec_ref:** §7 AC1, AC3, AC4, AC5, AC6

**Files:**
- Modify: `scripts/bb2_brain/tests/test_universal_ingest_e2e.py` (lint clean + cli 회상 추가)

**빨강 (작성할 검증):**
- `test_e2e_lint_clean_after_full_reingest` (AC5): 새로 적재 완료한 store에 `lint_store(BrainStore.load(root))`==[] 단언.
- `test_e2e_cli_recall` (AC6): **Task 6에서 새로 적재한 tempfile store**에 대해 cli query 경로(또는 `QueryRouter(store).answer(...)`)로 샐리 표면어 질의 → reviewed mapping이 `source_object_ids`에 뜸.
  - **회상 전제 1 (intent 분류):** `glossary_meaning` 의도는 query에 `"무슨 뜻"` 또는 `"용어"`가 들어있을 때만 분류된다(`intent.py:47-48`; `"의미"` 단독은 트리거 아님). 질의 예는 추출한 term의 표면어를 넣어 `"<표면어>가 무슨 뜻이야?"` 형태로.
  - **회상 전제 2 (표면어 매칭):** 질의어는 reviewed mapping이 가리키는 glossary term의 `term`/`synonyms` 표면을 문자 그대로 포함해야 매칭(`router.py`의 `_matched_mappings`, substring 비교는 `:314` `surface in query`). 실제 표면어는 Task 6에서 추출한 값으로 확정(쿨타임은 위 코드 닻 주의대로 `COOLTIME`/`COOLDOWN`/`쿨타임` 셋 다 synonyms에).
  - **회상 전제 3 (승격 순서):** mapping이 회상되려면 단계3 mapping_bundle 승격까지 끝난 store여야 한다(이때 mapping reviewed).
  - **단언:** reviewed mapping id가 `source_object_ids`에 포함 + `needs_clarification==False`. 보조로 `answer(q)["intents"]`에 `"glossary_meaning"` 포함 확인(실패 시 intent 분류인지 표면어 매칭인지 가름).
- AC3/AC4는 Task 4에서 이미 단위 검증(재참조만, 중복 작성 불필요).

**빨강 검증 동작:** lint==[]로 무결성, answer dict의 `source_object_ids`에 reviewed mapping 포함으로 회상. 이전 세션과 달리 **삭제된 test_router의 회상에 기대지 않고, 새로 적재한 store가 스스로 회상함을 증명**한다.

**초록 (구현):** 신규 코드 없음. Task 6 store에 lint/router 적용.

**검증 (최종):**
```
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/ -q
```
Expected: 전부 PASS. **워킹트리 기준 현재 0 tests(엔진 7개 staged 삭제 반영) → 신규 ≈ objbase 4 + promote ~9 + ingest ~8 + cli 2 + e2e ~7 = ~30.** baseline·회귀 기준: 사용자 결정 (a) 채택 — 엔진 테스트 복원 없이 **신규 ~30만**. (RESOLVED 참조.)

---

## Task 8: 제거됨 (사용자 결정 — 엔진 테스트 복원 안 함)

2026-06-04 사용자 결정으로 엔진 테스트는 삭제 유지하고 별도 복원/재작성 task를 두지 않는다(위 RESOLVED 참조). 구현 중 특정 엔진 동작 검사가 정말 필요해지면 해당 Task 안에서 현재 코드 기준 중립 데이터로 새로 추가한다.

---

## Self-Review

**1. 지난 세션 거부 지점 해소 확인:**
- 삭제된 이전 테스트/fixture 참조 제거: Task 1~5 테스트는 새 중립 합성 데이터, Task 5는 삭제된 fixture 대신 tempfile, Task 7은 삭제된 test_router 회상 대신 새 적재 store 회상. ✓
- Task 6 git-show 베끼기 제거: 살아있는 소스(spec-v8.md+develop 코드) 새 추출로 교체. ✓
- baseline 정정: 엔진 테스트는 커밋이 아니라 **staged 삭제**(워킹트리 0, HEAD엔 살아있어 복원 가능)임을 OPEN DECISION·Tech Stack에 정확히 반영. 신규 ~30, 복원 여부는 OPEN DECISION. ✓
- 엔진 회귀(삭제 부수효과): 정확한 git 사실 확인 후 사용자 결정 (a) 채택 — 복원 안 함, 필요 시 현재 기준 새로. RESOLVED + Task 8 제거로 반영. ✓

**2. Spec coverage** (§ 대비):
- §3.1 ingest → Task 4 + Task 5 ✓ / §3.2 promote single/bundle → Task 2 + Task 3 ✓ / §3.3 base()+ReviewRecord → Task 1 ✓ / §4.1 멱등+후퇴가드 → Task 4 ✓ / §4.2 strict integrity → Task 4 ✓ / §4.3 initial+승격만 → amend/supersede 없음 ✓ / §7 AC1~6 → Task 6/7 ✓

**3. 의존 순서:** Task1(헬퍼) → Task2/3(promote) → Task4(ingest) → Task5(cli) → Task6(새 추출+조합) → Task7(검증) → Task8(OPEN 후).

**4. 흡수 정확성 (git show 직접 확인):** single_object=`source.py:374-396`(title 379 제외), mapping_bundle 토글=`mappings.py:124-126`, bundle review=`mappings.py:180-196`, base 교집합=세 스크립트 base() defaults. 멱등=`save_object` write_text(`store.py:67`). 후퇴 가드=현존 안 함(신규, §4.1).

**알려진 제약/주의:**
- ingest 후퇴 가드는 동일 kind 동일 id 갱신만 다룬다(spec §4.1 범위).
- Task 6 객체 수는 "목표"이고, 관계 정합(lint clean)이 개수보다 우선 — Task7 lint==[]가 최종 게이트.
- Task 6 단일 승격 대상(spine term 1개)은 도구와 무관한 경로 시연 — 어느 term이든 무방(사용자 결정 사안 아님).
- Task 6 추출의 충실성(코드 앵커가 실제 develop 코드를 정확히 가리키는지)은 적대 검증/구현 시 직접 코드 대조로 확인한다(추측 금지).
- **spec §5 동기화 필요 (follow-up, 사용자 승인 후)**: spec §5 Resolved 블록은 "133 tests / live coverage stays"로 **커밋 `1af5b69ef9` 시점** 기준이라, 엔진 테스트 7개 staged 삭제(워킹트리 0)를 반영하는 보정이 필요하다. spec은 설계 문서라 수정 시 사용자 승인을 받는다 — 이 plan에선 안 고친다.
