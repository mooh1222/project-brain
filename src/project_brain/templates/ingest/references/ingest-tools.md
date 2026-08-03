# 적재 도구 — ingest / promote 호출법

엔진(project-brain — 글로벌 도구)은 도메인을 모른다.
받은 객체 묶음을 검증·저장만 한다. 이 파일은 그 도구를 어떻게 부르는지, 무엇을 검증하는지,
어떤 가드가 있는지 정리한다. 코드 계약이 어긋나 보이면 엔진 레포의
`src/project_brain/ingest.py`·`promote.py`·`cli.py`·`store.py`를 직접 읽어 확인하라.

## 목차

- [build](#build--구조화-노트--객체-묶음-조립-자동화-2026-06-16)
- [ingest와 promote](#ingest--cli로-부르기)
- [저장 레이아웃과 raw 원문](#기획서-원문-보관-2026-06-10-확정)
- [단건·대량 실행](#조립적재-스크립트-scripts)
- [적재 후 확인](#적재-후-확인--lint--색인--골든셋--회상--고립-재점검)

## 큰 그림 (B+C 검수, design-hub §8)

```
검증된 근거 + 적대검증 통과 + lint clean ──ingest(status:reviewed)──▶ store 저장                          ← B (자동, 사람 0)
근거 약함/충돌/검증 실패 ──ingest(status:candidate)──▶ store 저장 ──질의 시 "확인 필요" 노출──▶ project-brain promote(사용 시점) ──▶ reviewed   ← C
```

- `ingest`: 묶음을 받아 **per-object 스키마 검증 → 병합 store 연결무결성 lint → mutation
  transaction** 순서로 처리한다. 저장 전 게이트가 실패하면 파일 쓰기를 시작하지 않고, 쓰기 중
  실패는 transaction journal로 rollback한다. status는 호출자가 박는다 — 검증 통과 매핑을
  `reviewed`로 넣으면 그대로 검수됨(B), 후퇴(reviewed→candidate)만 거부한다. §6.4로 reviewed `DomainMapping`·
  `GlossaryTerm`은 `evidence_refs` non-empty여야 통과한다(코드앵커는 비강제).
- `promote`: candidate 객체를 reviewed로 승격하고 (승격 객체 + ReviewRecord)를 돌려주는 **함수**. 저장은 안 하니
  결과를 다시 `ingest`에 넣는다 — 적재 슬라이스 **묶음 승격**에 쓴다. **사용 시점 단건 확정**은 아래 `project-brain promote`가
  저장까지 한 번에 한다(C 루프).

## build — 구조화 노트 → 객체 묶음 (조립 자동화, 2026-06-16)

손으로 조립 스크립트를 짜는 대신 **노트(JSON)**를 작성하고 `build`가 brain 객체 묶음으로
변환한다. build는 **저장하지 않는다** — 묶음과 diff만 만들고, 저장은 ingest가 한다.

```bash
# 1) 노트(JSON) 작성: context / sources / glossary / code_anchors / mappings / decisions / refs / updates / extra_objects
#    context는 key·commit 필수. now는 선택 — 생략하면 엔진이 현재 KST(+09:00)를
#    created_at/updated_at/verified_at에 자동으로 박는다(적으면 그 값으로 override = 소급·테스트용).
#    (decisions[]는 build_decisions가 DecisionRecord + commit/jira/pr EvidenceRef로 조립하고
#     affects 역채움까지 한다. 노트 입력은 scripts/domain_spec.template.py와
#     project-brain build --help에서 확인한다.)
# 2) build — 묶음(out.json) 생성. 리포트(diff·resolved_refs·preconditions)는 stdout → 파일로 저장
project-brain build --notes notes.json --objects-file out.json > report.json
# 3) report.json의 diff 확인 (특히 updates의 기존 객체 before/after 값)
# 4) ingest — build 리포트를 --preconditions-file로 넘겨 저장 직전 낙관적 잠금 재검사 후 저장
project-brain ingest --objects-file out.json --preconditions-file report.json
# 5) 색인·골든셋·회상
project-brain index rebuild && project-brain eval && project-brain search "..."
```

- **build가 하는 것**: id 파생(`g.<ctx>.<key>`·`mapping.<ctx>.<key>`·`code.<ctx>.<key>`·`evref.<ctx>.<key>`)·
  객체 간 연결(노트의 논리 key → 실제 id)·근거 묶기·끊긴 참조 검사(dangling·EvidenceRef→manifest·
  updates union 대상 실존)·diff.
- **build가 안 하는 것**: supersede·강등·충돌 해소·이력 판정 — 이건 노트에 명시한다(에이전트 판단). build는 기계적 변환만.
- **updates**(기존 객체 갱신)는 `set`(scalar 교체)·`union`(list 합치기) 2종만, **객체 kind별 allowlist** 안에서만.
  의미(claim) 필드(meaning·boundary 등) 수정은 `evidence_unchanged: true`나 evidence 변경을 동반해야 한다.
  `expected_updated_at`로 낙관적 잠금(build 시점·ingest 저장 직전 두 번 검사 — 그 사이 store가 바뀌면 거부).
- **DecisionRecord**는 `decisions[]` 노트 키로 조립한다(build_decisions — DecisionRecord + commit/jira/pr EvidenceRef + affects 역채움).
  decision 근거의 evref id는 `evref.<ctx>.<type>-<ref>`(예: `evref.sally-canoe.commit-abc1234567`)로 파생되고 같은 id는 중복 제거된다.
  commit은 locator={repo,sha}를 자동으로 채우고, jira/pr은 노트 evidence의 `locator`(인스턴스 URL)를 그대로 쓴다.
  **노트로 못 담는 완성 객체**(session 등 비-code EvidenceRef)는 `extra_objects[]`에 직접 넣는다 —
  build가 검증·끊긴 참조 검사에 함께 태운다.

## ingest — CLI로 부르기

`cli.py`에 `ingest` 서브커맨드가 있다(query 경로는 그대로 유지). 묶음을 JSON 배열 파일로 만들어 넘긴다:

```bash
project-brain ingest \
  --objects-file <묶음.json> \
  [--preconditions-file <build리포트.json>] \
  --repo-root <absolute-project-root> \
  --expected-repo-id <repo-id> \
  --expected-revision-ref <git-ref> \
  --engine-sha <exact-engine-sha>
```

- `--objects-file`: 객체 dict들의 **JSON 배열** 한 파일.
- `--preconditions-file`: build 리포트 JSON(선택). 저장 직전 `expected_updated_at`를 다시 확인해
  build 이후 store가 바뀌었으면 거부한다(검사–저장 시점차 방지, build의 updates를 쓸 때만 의미 있음).
- 성공 JSON은 `transaction_id`, `operation=ingest`, `committed`, `manifest_sha256`,
  `before_fingerprint`, `after_fingerprint`, `ingested_ids`, `ingested_count`를 정확히 담는다.
  `committed=true`와 lowercase SHA-256 형식의 `manifest_sha256`이 없으면 성공 증거가 아니다.
  실패 시 `{"ok": false, ...}`와 종료코드 1이다.
- 레포 안 어느 디렉토리에서든 실행 가능 — 루트 `.project-brain.json` config가 brain root를
  해석한다(`--brain-root`로 덮어쓸 수 있음).

## ingest가 거는 3개 게이트 (ingest.py)

1. **per-object 스키마 검증.** 묶음 전체에 `validate_object`. 하나라도 위반이면 전체 중단(아무것도 안 씀).
2. **병합 store 연결무결성 lint.** on-disk 기존 객체 + 묶음을 합쳐 `lint_store` 실행. 없는 id를
   가리키는 링크(dangling)가 있으면 전체 중단. 가리키는 객체는 같은 묶음 안이나 이미 store에 있어야 한다.
   (이때 `workspace_root` 미전달 = 참조 무결성만, 생성파일 projection 검사는 안 함.)
3. **저장.** 1·2 통과 후에만 kind별 디렉토리에 `<id>.json`으로 쓴다.

## ingest 가드 — 멱등 / 후퇴 금지

- **멱등 갱신 허용.** 같은 id를 다시 ingest하면 덮어쓴다(`save_object`가 `write_text`로 overwrite).
  끊어 적재하거나 같은 의미 객체에 연결을 추가할 때 이 동작에 기댄다.
- **reviewed→candidate 후퇴 거부.** on-disk가 `reviewed`인데 같은 id를 `candidate`로 덮으려 하면
  `IngestError`. 이건 ingest 진입점의 유일한 신규 로직이다. 승격된 걸 실수로 후퇴시키지 마라.

## promote — 묶음 승격(함수) / 사용 시점 단건 확정(`project-brain promote`)

**묶음 승격**(적재 슬라이스 전체를 한 검토 기록으로)은 `promote` 함수로 한다. 작은 파이썬
한 토막(엔진이 깔린 도구 venv python으로 실행 —
경로는 `$(head -1 "$(which project-brain)" | sed 's/^#!//')` 로 얻는다):

```python
from project_brain.promote import promote
from project_brain.ingest import ingest
from pathlib import Path

# objects = 적재된 candidate 매핑들(또는 그 dict 목록)
promoted, reviews = promote(
    objects, ids=[...승격할 mapping id들...], scope="mapping_bundle",
    bundle_key="bundle.<도메인>.domain-mapping",
    reviewer="user-confirmed", reviewed_at="2026-06-04T00:00:00Z",
)
ingest(Path("<brain 디렉토리>"), promoted + reviews)  # 승격 결과를 다시 검증·저장
```

**사용 시점 단건 확정**(C 루프 — 답하다 사람이 "맞다")은 `project-brain promote`가 한다. 승격 객체 + 검토 기록을 둘 다 저장하고,
쓰기 전 일괄 schema 검증(근거 없는 후보면 §6.4로 거부)·사후 lint까지 한 번에 처리한다:

```bash
project-brain promote \
  --ids <승격할 id...> --reviewer user-confirmed [--reviewed-at <ISO8601>] \
  [--scope mapping_bundle --bundle-key bundle.<도메인>.domain-mapping]
```

- `--scope`는 기본 `single_object`(단건), 여러 매핑을 한 번에면 `mapping_bundle` + `--bundle-key`.
- 성공 시 `{"ok": true, "promoted": [...], "reviews": [...]}`, 근거 부재·dangling 등은 `{"ok": false, ...}` + 종료코드 1.

`promote(objects, ids, scope, *, bundle_key=None, reviewer, reviewed_at)` — `reviewer`/`reviewed_at`는
keyword-only 필수다.

### scope 두 가지 (promote.py)

- **`single_object`**: 각 id를 독립 승격. `candidate` 키 통째 제거, `status="reviewed"`,
  `review_record_id="review."+id`, 객체별 ReviewRecord(`target_object_id` 단수, evidence_refs 복사).
  `bundle_key` 불필요.
- **`mapping_bundle`**: ids 전체를 한 review 묶음으로 승격. 각 매핑 `status="reviewed"` + 공유
  `review_record_id="review."+bundle_key` + `review_state`({meaning/evidence/projection}_reviewed=true).
  단일 bundle ReviewRecord(`target_object_ids` 복수, `review_scope="mapping_bundle"`, `bundle_key`/
  `confirmation_key`). `bundle_key` 필수(없으면 ValueError).
  - `confirmation_key`는 **개별 매핑이 아니라 리뷰 작업을 명명**한다. 예: `bundle.sally-canoe.domain-mapping`.
  - `implementation_reviewed`는 코드 앵커를 따로 재검증했을 때만 켠다 — promote는 기본으로 안 켠다.
  - `status="reviewed"` 승격은 `current_ingest_done`을 만들 수 있지만 변경 이력 완료를 자동 의미하지 않는다.
    `history_coverage=complete`는 너가 Jira/Slack/PR/commit 이력을 확인한 뒤 `caveats`에 남겨야 한다.

- `reviewer`는 caller(너)가 넘긴다. `reviewed_at`은 함수 `promote()`엔 keyword-only 필수 인자지만, CLI `promote`/`promote-auto`는 생략 시 엔진이 현재 KST(+09:00)를 박는다(시점 상수는 코드에 없다 — 자동값은 항상 "지금").

## 저장 레이아웃 (store.py `_KIND_DIR`)

`save_object`가 kind에 따라 brain-root 아래 이 디렉토리에 `<id>.json`을 쓴다:

| kind | 디렉토리 |
|---|---|
| EvidenceManifest | raw/manifests |
| EvidenceRef | objects/evidence_refs |
| ReviewRecord | objects/reviews |
| EventLedgerRecord | objects/ledger |
| TemporalFact | objects/facts |
| CodeLocator | objects/code |
| DomainContext / GlossaryTerm | objects/domain |
| DomainMapping | objects/mappings |
| DecisionRecord | objects/decisions |
| Insight | objects/insights |
| SpecDocument / SpecRevision / SlideRef | objects/specs |
| SlackThread | objects/comms |
| ContextProjection | indexes/context_projections |
| IndexRecord | indexes/records |
| KnowledgePage | views/knowledge |
| CurrentView | views/current |

## 기획서 원문 보관 (2026-06-10 확정)

기획서 마크다운 원문은 `{{BRAIN_ROOT}}/raw/sources/<context-slug>/`에 보관한다. 파일 이름은 자료의
성격에 따라 둘 중 하나를 쓴다.

- 한 기능의 개정 기획서는 `spec-v<N>.md`를 쓴다. 번호는 `analyze-spec-ppt` 규약을 따르고 이전
  버전을 덮어쓰지 않는다.
- 서로 다른 옛 문서를 대량 보관하거나 내부 버전을 알 수 없으면
  `<sanitized-original-basename>.md`를 쓴다. 원본 이름을 안전하게 정리한 basename이므로 서로 다른
  원본이 충돌하지 않게 확인한다. 확장자를 뺀 이름은 소문자 ASCII 영숫자와 하이픈만 남기며, `[^a-z0-9]+`는
  하이픈 하나로 바꾸고 양끝 하이픈은 제거한다. 결과가 비면 fallback `document`를 쓴다. 예: `Legacy Plan 01.md` → `legacy-plan-01.md`, `Collision Notes.md` → `collision-notes.md`.
  같은 basename이 이미 있으면 원본 source locator/path의 SHA-256 앞
  12글자를 붙인 `<sanitized-original-basename>-<sha256-12>.md`를 쓴다. 쓰기 전에 최종 후보 경로의
  해시는 Source Intake에서 선언한 source bundle root를 기준으로 한다. 입력은 그 root 아래 상대경로여야 하며,
  절대경로와 `..` 탈출은 거부한다. `.` component는 제거하고 각 component는 Unicode NFC로 정규화하며 경로 구분자는 `/`를
  쓴다. 대소문자는 바꾸지 않고 이 canonical relative path 문자열의 UTF-8 바이트를 SHA-256 입력으로 쓴다. 파일 내용의 SHA-256이 아니다.
  최종 후보가 충돌하면 suffix를 늘리고 매번 유일성을 확인한다. suffix는 12글자부터 64 hex 글자까지
  늘리며, 그 범위를 모두 써도 충돌하면 오류로 끝낸다. source bundle root 자체와 그 아래 경로의 심볼릭 링크는 거부한다.
  재생 드라이버는 raw target이 비어 있지 않으면 fail-closed로 중단한다. 기존 raw 파일은 절대 덮어쓰지 않는다.

파일 기반 manifest에는 `build_manifests()`가 보존하는 필드에만 다음 출처 정보를 기록한다.

| EvidenceManifest 필드 | 기록값 |
|---|---|
| `title` | 원본 파일명 그대로 |
| `captured_by` | 변환 도구 이름/버전 |
| `captured_at` | 캡처 시각 |
| `locator` | brain root 기준 최종 raw 상대 경로 |

새 엔진 필드는 만들지 않는다. 텍스트만 Git으로 추적하고 바이너리(PPT·이미지)는 계속 미추적으로 로컬 보관한다. 규약 정본은
`{{BRAIN_ROOT}}/README.md`이며 서버 위키·세션은 링크만(`EvidenceManifest.locator`) 남긴다.

## promote-auto — 매핑 보증 용어 일괄 승격

reviewed 매핑이 참조하는 candidate **용어**는, 배치 커버리지 검증(정의가 매핑 검증 의미
안에 드는지 판정) pass 후 일괄 승격할 수 있다. reviewer는 `auto:mapping-vouched`로
자동 기록되고, 빈 근거는 짝 매핑의 EvidenceRef로 채워진다(backfill — 빈/legacy-only는
부적격 제외). 쓰기 전 일괄 검증으로 부분 쓰기를 막는다:

```bash
project-brain promote-auto --ids <pass 판정 용어 id...> [--reviewed-at <ISO8601>]
```

★돌리기 전 **커밋 먼저** — 많은 객체를 한 번에 바꾸는 파괴적 작업이므로 되돌릴 기준
커밋을 만든 뒤 실행한다(2026-06-09 부분 쓰기 사고 교훈, {{BRAIN_ROOT}}/README.md 규약)★.

## 조립·적재 스크립트 (scripts/)

손으로 조립 스크립트를 새로 짜지 않는다. 적재마다:
1. `scripts/domain_spec.template.py`를 복사해 의미 데이터와 `FINALIZATION`을 채운다. 조립 로직은 넣지 않는다.
   `FINALIZATION.recall_checks[]`마다 중복 없는 `key`, 실제 도메인 `query`, 비어 있지 않은
   `expected_object_ids`, `require_code_locators`를 선언한다. 새 고립 중 근거를 남긴 의도적 종착점만
   `intentional_terminal_ids`에 넣는다. 고정 샘플 질의나 결과 개수만으로 완료를 판정하지 않는다.
2. 추출은 `scripts/extract_template.js`(채워넣기)로 group별 extract→verify → verify.json.
3. 단건 기본 실행은 FINALIZATION schema를 먼저 검사하고 build 뒤 ingest 전에 `isolation_baseline`을
   수집한다. ingest가 성공하면 같은 baseline과 config로 semantic finalizer를 실행한다. config가
   없거나 틀리면 build·ingest 전에 실패한다. 중간 비파괴 검증은 `--dry`를 쓴다.

   ```bash
   scripts/run_ingest.sh \
     --repo-root <absolute-project-root> \
     --brain-root <absolute-brain-root> \
     --expected-repo-id <repo-id> \
     --expected-revision-ref <git-ref> \
     --engine-sha <exact-engine-sha> \
     verify.json domain_spec.py
   ```

4. 대량은 아래처럼 실행한다. `batch.json`은 item 목록과 top-level `finalization` 계약을 함께 둔다.
   각 item은 build→ingest만 하고 색인을 만들지 않는다. 모든 item이 성공한
   뒤에만 batch runner가 finalization을 한 번 실행한다. 실패가 있으면 finalization을 호출하지 않는다.

   ```json
   {
     "repo_root": "/absolute/project/root",
     "expected_repo_id": "repo-id",
     "expected_revision_ref": "origin/main",
     "engine_sha": "40-or-64-lowercase-git-sha",
     "items": [{"key": "a", "verify_json": "a.json", "domain_spec_py": "a.py"}],
     "finalization": {
       "recall_checks": [{
         "key": "a", "query": "A의 핵심 동작은?",
         "expected_object_ids": ["mapping.a.core"],
         "require_code_locators": true
       }],
       "intentional_terminal_ids": []
     }
   }
   ```

   ```bash
   scripts/run_ingest_batch.py batch.json --report batch-report.json
   scripts/run_ingest_batch.py batch.json --report batch-report.json --resume batch-report.json
   ```

   `repo_root`는 symbolic link가 없는 absolute canonical path이자 실제 Git toplevel이어야 한다.
   각 item 입력은 manifest 아래 상대경로만 허용하며 absolute path, `..` 탈출, symbolic link는
   거부한다. runner는 시작 때 no-follow FD로 읽은 verify/spec 바이트를 run 전용 read-only
   `immutable staged` 파일로 고정한다. child에는 이 staged 경로만 넘기며 원본과 staged 파일의
   type/device/inode/size/hash를 item 전후와 finalization 직전에 다시 확인한다.

   첫 실행은 어떤 item보다 먼저 `isolation_baseline`을 report에 저장한다. report에는
   absolute `repo_root`, target config가 해석한 canonical `brain_root`와
   `brain_root_device`/`brain_root_inode`, `expected_repo_id`, `expected_revision_ref`, resolved
   `target_revision_sha`, actual `engine_root`와 `engine_sha`, 양쪽 root의 device/inode, batch 파일
   자체의 `manifest_sha256`, resolved 입력의 `manifest_fingerprint`, authoritative
   `item_records`가 기록된다. 각 record는 full binding, `pending|failed|committed` status, failure,
   exact transaction을 한 객체에 묶는다. `transactions`는 `item_records`에서 파생되는 호환
   출력이며 독립 resume/finalization 근거가 아니다.

   재개는 같은 report의 최초 baseline을 재사용하되 실제 Git toplevel/repo identity, ref가 가리키는
   exact `target_revision_sha`, 실제 engine Git root/HEAD, repo/brain root inode, manifest와 입력 hash 가운데
   하나라도 다르면 `resume_contract_mismatch`로 종료한다. 각 item 전과 finalization 직전에도 같은
   resolved state를 재검증한다. malformed prior report도 fail-closed 처리한다.

   item ingest는 binding을 mutation manifest와 durable batch intent/journal에 함께 기록한다.
   process가 COMMITTED 뒤 report 갱신 전에 끊겨도 재개는 root-anchored journal에서 exact
   `durable receipt`를 복구한다. 이때 canonical manifest SHA, operation, engine SHA, action object
   IDs, before/after fingerprint, 현재 corpus fingerprint, item/input identity를 모두 확인한다.
   receipt가 없는 suffix만 재실행하며 첫 failed/pending record에서 tail 실행을 멈춘다.
   `needs_user`, 누락·불일치 transaction, `committed=false`, durable receipt 불일치는 성공이나
   `finalized`로 승격하지 않는다. 완료 증거는 `finalized=true` 하나가 아니라 모든 `item_records`의
   exact durable 계약과 `finalization.ok=true`, `finalization.isolation.unexpected_new_ids=[]`,
   각 recall check의 누락 목록이 빈 상태까지 포함한다.
   완료 검사는 post head == baseline head와 post unmerged == baseline union expected를 함께
   확인한다. legacy baseline은 당시 허용한 제한만 적용하며, 사용할 수 없는 감사 상태를 만들어 내지 않는다.
   semantic commands가 끝난 뒤 finalizer는 durable receipt chain과 current object corpus tail을
   `post_gate_object_tail` mode로 다시 확인한다. commit 직후와 semantic commands 전 검증은
   derived 파일이 없어야 하는 `strict_commit` mode를 유지한다. post-gate mode는
   intent/journal, canonical manifest와 receipt, full object corpus fingerprint, object action
   entry를 그대로 검증하면서 index/audit derived 출력만 허용한다. batch runner도 finalizer return 뒤 resolved
   repo/ref/engine/brain root state, 원본·staged 입력, receipt chain을 `post-finalizer`로 다시
   확인한 직후에만 `finalized=true`를 쓴다. index/audit 같은 derived 파일 변화는 허용하지만 object
   corpus tail이나 ref/engine/brain root가 바뀌면 commands가 성공했어도 완료로 승격하지 않는다.
   config JSON이 object가 아니거나 config loader가 일반 예외를 내더라도 traceback을 노출하지
   않고 finalizer는 `ok=false`, batch는 `finalized=false`인 JSON 실패를 기록한다.

   finalizer JSON의 `unmerged` 블록은 이 Git 범위 검사의 실제 결과다. `ok`가 false면 완료가 아니다.
   `baseline_ids`는 baseline에 있던 미머지 locator, `expected_ids`는 이번 계약이 허용한 locator,
   `current_ids`는 사후 audit이 읽은 locator다. 비교 기준은 `baseline_ids ∪ expected_ids`다.

   | `unmerged` 필드 | 뜻 |
   |---|---|
   | `current_state_available` | 사후 audit에서 Git 상태를 읽었는지 |
   | `new_ids` / `resolved_ids` | baseline 뒤 새로 생긴 locator / baseline에서 사라진 locator |
   | `missing_expected_ids` / `unexpected_new_ids` | 계약상 있어야 하지만 없는 locator / union 밖 새 locator |
   | `baseline_target_head` / `current_target_head` | baseline과 사후 audit의 기본 브랜치 HEAD |

   audit/stale 오류로 사후 상태를 읽지 못하면 `current_state_available=false`이고 `current_ids`,
   `new_ids`, `resolved_ids`, `missing_expected_ids`, `unexpected_new_ids`, `current_target_head`는 `null`이다.
   이때 `errors`의 audit/stale 오류를 확인해 Git 문제를 고친 뒤 같은 baseline으로 다시 실행한다.

5. verify 출력의 변칙(빈 corrected_atoms 등)은 domain_spec.CORRECTIONS(선언적)로, 진짜 novel만 HOOK으로. HOOK 쓰면 `references/ingest-case-log.md`에 1줄 기록.

채운 예(형태): 14결정·{groups} 래핑형 / 0결정·list형(CORRECTIONS 사용). 변칙 누적은 `references/ingest-case-log.md` 참고.

## 적재 후 확인 — semantic finalization

`scripts/finalize_ingest.py`는 authoritative `item_records`의 binding과 exact transaction을
root-anchored durable intent/journal의 `COMMITTED` receipt chain으로 다시 검증한다. record가 모두
`committed=true`이고 canonical manifest SHA, before/after fingerprint, operation, engine SHA,
action object IDs, 현재 corpus fingerprint가 일치할 때만 아래 게이트를 실행하고 `transactions`, `commands`,
`isolation`, `unmerged`, `recall_checks`, `errors`를
가진 JSON 한 개를 낸다. runner는 종료 코드만 보지 않고 이 schema와 `ok`를 함께 확인한다.
모든 command와 recall check 뒤에도 같은 durable receipt/current object tail을
`post_gate_object_tail` mode로 다시 검증한다. 정상 index/audit derived 출력은 허용하지만
action object 변경이나 알 수 없는 object 추가는 fingerprint 불일치로 거부하며, 이 두 번째
검증 실패도 `ok=false`다.

1. **lint clean** — ingest가 성공했으면 연결무결성은 통과한 것. 별도 일괄 작업을 했다면
   `lint_store` 문제 0건 재확인.
2. **색인 재생성** — store가 바뀌었으면 검색 색인을 다시 만든다(전체 재구축 방식.
   실모델 배치 임베딩이라 수십 초 걸리는 게 정상):
   ```bash
   project-brain index rebuild
   ```
   index rebuild는 잠금으로 동시 실행을 막고, 임시 파일에 완성본을 만든 뒤 유효성을 검사하고
   원자적으로 교체한다. 교체 뒤 내구성 확인까지 끝나야 완료다. 교체 뒤 내구성 실패는 새 색인이
   보이더라도 성공으로 숨기지 말고 `committed` 상태와 함께 보고한다.
3. **골든셋 회귀 + 실코퍼스 가드** — 새 적재가 기존 회상을 깨뜨리지 않았는지(기능마다
   골든셋 시나리오를 늘려가는 게 P2 방침). 객체 색인 행은 가드가 디스크의 색인 대상 kind
   `.json` 수를 세서 `indexed - raw_chunks`와 자동 대조하니 손으로 갱신하지 않는다
   (`test_real_corpus.py`의 `INDEXED_OBJECT_DIRS`, 색인 제외 kind는 아래 표). raw 청크 수
   (`EXPECTED_RAW_CHUNKS`)만 기획서 원문·청커가 바뀔 때 의식적으로 갱신:
   ```bash
   project-brain eval
   python3 -m unittest discover -s {{BRAIN_ROOT}}/checks -p "test_*.py"  # 표준 unittest — pytest 불필요
   ```
4. **계약 회상** — `recall_checks`의 각 query가 모든 `expected_object_ids`를 회수하고,
   `require_code_locators=true`면 각 기대 객체의 `linked.code_locators`가 비어 있지 않은지 확인한다.
   ```bash
   project-brain search "<도메인 관련 질문>"
   ```
5. **고립 잎 재점검** — 적재 전후 `project-brain graph isolated` 차이로 신규 고립 객체(아무도 안
   가리키는 잎)를 나열하고, 각각 (a) 의미 있는 관계가 있으면 연결 (b) 의도적 종착점으로 분류
   (c) rejected·제거 중 하나로 처리한다. 의도적 종착점은 적재 결과 기록에 객체 ID, 분류, 근거를
   남긴 경우에만 허용한다. 0개로 만들려고 의미 없는 연결을 추가하지 않는다 — 검수 정책 B+C:
   명백한 건 에이전트가 자동으로, 애매한 것만 사용자 확인(코드는 나열만, 어느 매핑에 union할지
   판정은 에이전트 몫, 애매하면 사용자). EvidenceRef는 `evidence_refs`로만, GlossaryTerm은
   `glossary_term_ids`로만 가리켜지므로 그 연결 누락이 여기 잡힌다 — "고립 정비가 새 매핑 적재로
   번질 수 있음" 교훈의 사후 가드. 연결할 때의 정책(primary/공동primary 기준·
   `history_coverage=complete` 판정)은 SKILL.md "절대 규칙" 7번이 정본:
   ```bash
   project-brain graph isolated
   ```

**색인 제외 kind** — 아래 kind는 검색 색인에 안 들어가 객체 행(`indexed - raw_chunks`)에
기여하지 않는다(엔진 `surface.py`의 `EXCLUDED_KINDS` + 추출기 없는 kind). 3번 가드가 객체 행을
디스크에서 셀 때도 이들 디렉토리는 뺀다:

| 색인 제외 kind | 이유 |
|---|---|
| EvidenceManifest · EvidenceRef · ReviewRecord | `EXCLUDED_KINDS`로 명시 차단 |
| SpecDocument · SpecRevision · SlideRef | 추출기(`_EXTRACTORS`) 없음 |
| SlackThread · IndexRecord · KnowledgePage | 추출기 없음 |
| ContextProjection | `format=prompt_payload`이고 fresh일 때만 색인(아니면 제외) |

조회 쪽 계약(결과 해석·채널 라벨·사용 시점 promote)은 `{{PROJECT}}-brain-query` 스킬이 정본이다.

## 설치 범위

엔진 `templates/`가 생성 스킬의 단일 원본이다. 소비 프로젝트에서는 먼저 `project-brain install`을
`--force` 없이 실행하고, 같은 입력으로 두 번째 실행했을 때 변경이 없음을 확인한다. 이 문서는 특정
소비 프로젝트에서 설치·재생성·감사를 이미 했다고 주장하지 않는다. session-snapshot filtering은 Project Brain install 범위 밖이며,
별도 도구의 책임으로 남긴다.
