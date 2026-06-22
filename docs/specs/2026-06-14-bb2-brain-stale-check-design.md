# BB2 Brain — 코드 변경 → 의미 갱신 대상 발견 (stale-check) 설계

- 작성: 2026-06-14. 근거: 이 세션 brainstorming + 정본 `vault wiki [[bb2-project-brain]]` §7 미결·§6 + 후속 계획서 `docs/superpowers/plans/2026-06-13-bb2-brain-update-mechanism-followup.md`(Task 4·5) + 이 세션 객체 구조 실측 + **codex(gpt-5.5) 적대 리뷰 2026-06-14**(§9 반영 기록).
- 레포: spec = 게임 레포(`bb2_client`), 구현 = 엔진 레포(`project-brain`, CLI 명령 추가).
- 위상: 팀 공유를 기준으로 (1)(2)(3)을 "트리거 대기"에서 "능동 작업"으로 전환한 첫 작업. (1) 의미 갱신 대상 발견.

---

## 0. 배경 — 왜 지금 만드나

기존 우선순위("실사용 막힘 트리거 대기")는 **혼자 쓰는 전제**의 것이었다. 혼자면 "내가 고쳤으니 안다 / 내가 불편할 때 고친다"가 성립한다. 그러나 brain의 최종 목적은 **팀 공유**(정본 §1)이고, 팀이면 **남이 develop 코드를 고친다.** 그 결과 brain 매핑의 의미가 낡는데 **알아챌 장치가 없다.** "추후 수정"과 "기능 부재"는 다른 문제이고, 공유한 뒤 없는 기능으로 문제가 되면 신뢰가 깨진다 — 그래서 공유 전에 갖춘다.

Task 4 실측이 이 작업의 경계를 정해줬다: **줄 번호(line) 어긋남은 회상에 무해**(엔진이 line을 검색·회상 어디서도 안 읽음, path+symbol만). 따라서 "위치(line) 갱신"은 불필요하고, 이 spec이 다루는 건 **"의미가 낡았는지" 발견**이다 — line과 독립인 별개 문제.

정본 골자(이어서 22 설계 입력): `git diff`로 바뀐 파일을 뽑아 영향받는 brain 객체를 **후보로 제시**, 판정은 사람. "코드 자동 비교 금지" 철학(멀쩡한 사실을 기계가 잘못 닫지 않게) 유지 — 기계는 "어느 파일이 바뀌어 어느 매핑이 영향권인가"를 **찾기**까지, "그 변경이 의미를 바꿨나"는 사람이 **판정**.

## 1. 목적

남(다른 팀원·개발자)이 develop 코드를 고쳐서, 그 코드를 설명하는 brain **매핑의 의미가 낡았을 수 있는 곳**을 찾아 "재검토 후보"로 제시한다. 판정·수정은 사람이 한다. (한 번이라도 brain에 적재돼 CodeLocator가 있는 코드에 한해 잡는 안전망 — 미적재 코드는 "새 적재" 대상이지 이 기능 범위가 아니다.)

## 2. 명령 두 개

| 명령 | 성격 | 하는 일 |
|---|---|---|
| `stale-check` | 읽기 전용 | 바뀐 파일 → 영향받는 매핑을 재검토 후보로 제시 + coverage 리포트 + locator_group |
| `mark-checked --mappings <id...> --checked-head <sha>` | 갱신 | 입력 매핑이 어떤 locator의 영향 매핑 전체(closure)를 덮으면 그 CodeLocator의 `commit_sha`/`verified_at`/`updated_at`를 갱신 |

(명령 이름은 잠정 — 구현 시 기존 CLI 네이밍에 맞춰 확정.)

## 3. `stale-check` 동작

1. `git fetch origin develop` → 최신 develop HEAD sha 확보(`target_head`). brain 브랜치는 develop보다 구버전이라 워킹트리로는 비교 불가.
2. 모든 CodeLocator를 순회하며 `(path, commit_sha)`를 모은다. **구현 키는 `path`가 아니라 `(path, commit_sha)` 쌍** — 같은 path를 commit_sha 다른 locator가 가리키면 각각 판정해야 한다.
3. 각 `(path, commit_sha)`에 대해 `git diff --name-status <commit_sha>..<target_head> -- <path>` → 그 `commit_sha` 이후 바뀐 파일을 가리키는 CodeLocator를 식별한다. (`--name-status`로 변경 종류 M/A/D/R도 같이 — rename·delete를 사람이 알아야 판정 가능.)
4. 바뀐 파일을 가리키는 CodeLocator의 `id`를 `code_locator_ids`에 가진 **매핑**을 후보로 올린다.
5. 출력(JSON, **brain 데이터는 안 건드림 — 읽기 전용**):
   - **매핑 단위 후보**: 각 후보 = `매핑 id` + 연결된 CodeLocator(들) + 바뀐 `path` + 변경 종류.
   - **`locator_group`**: 각 stale locator마다 `{locator_id, path, from_commit, target_head, blocking_affected_mapping_ids, nonblocking_affected_mapping_ids}`. `blocking`은 `status==reviewed`인 매핑(검수 완료 = 현재 진실), `nonblocking`은 candidate/superseded/archived/rejected. `mark-checked`의 closure 판정 근거이자, 사람이 "이 locator를 공유하는 매핑이 무엇무엇인지" 보게 한다.
   - **coverage 리포트**: `covered_mappings`(code_locator_ids로 역추적 가능) / `uncovered_mappings`(code_locator_ids 빈/없는 21개 — 그중 2개는 code EvidenceRef만 가짐) / `skipped_reason=no_code_locator_ids`. 팀 공유용이면 이 숫자 없이는 "사각이 없다"는 착각을 준다.
   - `target_head`(현재 origin/develop sha) — `mark-checked` 경합 가드의 기준.

## 4. 검토 루프 — locator closure mark (A′)

`stale-check`가 매핑 후보 + `locator_group`을 뱉으면 사람이 판정한다:

- **의미 그대로** → `mark-checked --mappings <검토한 매핑 id...> --checked-head <target_head>`.
  - CLI가 **현재 store 기준으로 각 stale locator의 closure를 다시 계산**한다. **closure(blocking) = 그 locator를 `code_locator_ids`로 가리키는 매핑 중 `status==reviewed`인 것만.** `superseded`는 현재 사실이 아니므로 closure에서 빼고(mark를 막지 않음), `candidate`는 "확인 필요" 채널이라 mark를 막지 않되 warning으로 노출한다.
  - 어떤 locator의 blocking closure가 **전부 입력 `--mappings` 안에 있으면** 그때만 그 CodeLocator를 갱신한다: **`commit_sha` = `checked_head`(sha) / `verified_at`·`updated_at` = mark 실행 시각(ISO8601)**. `line_start`/`line_end`는 불변(Task 4). (verified_at은 object model상 ISODateTime이라 sha가 아니라 시각이다.)
  - **하나라도 빠지면** 그 locator는 갱신하지 않고 `blocked: {locator_id, missing_mapping_ids}`를 JSON으로 반환한다. (공유 locator에서 안 본 reviewed 매핑이 조용히 빠지는 사각 방지.)
  - `--checked-head`가 현재 origin/develop과 다르면 실패시킨다 — 사람이 head A를 보고 검토했는데 그새 head가 B로 움직였으면, A 검토를 B까지 확인한 것처럼 올리면 안 된다.
  - (가드 한계, 최종 리뷰 반영) 이 비교는 stateless라 "검토 시점에 본 head"가 아니라 "현재 origin/develop과 일치"를 본다. develop이 A→B→A로 되돌려지는 드문 경우 옛 `checked_head=A`가 현재 head A와 일치해 통과할 수 있다 — 부분 검토 미저장 설계의 연장으로 수용한다(현실 위험 낮음).
  - **부분 검토 상태는 저장하지 않는다.** 매핑별 "검토됨" 필드를 새로 만들면 스키마 변경 + head 이동·supersede·재실행 시 정리 규칙이 생겨 P0치고 과하다. 그래서 closure 미충족 locator는 다음 `stale-check`에 다시 뜨는 게 정상이다.
- **의미 바뀜** → 기존 supersede 워크플로우(ingest)로 옛 매핑을 `superseded` 처리하고 새 매핑으로 잇는다.

> 왜 매핑별 검토 상태를 저장하지 않나: 한 CodeLocator를 여러 매핑이 공유하는데(실측 57개) `commit_sha`는 locator에 **하나뿐**이다. 매핑 하나만 보고 commit_sha를 올리면 같은 locator를 쓰는 다른 미검토 매핑이 다음 점검에서 빠진다. closure 전체 검토를 갱신 조건으로 걸면 새 저장 없이 사각이 사라진다(공유 locator의 reviewed 매핑 참조는 최대 7개라 매번 재계산해도 감당).

## 5. 경계 — 설계상 안 하는 것

- **line(줄 위치)을 안 건드린다** — Task 4 "줄 어긋남은 회상에 무해". 감지에도 갱신에도 line을 쓰지 않는다(파일 단위 변경만).
- **EvidenceRef는 stale 판정 대상이 아니다** — `path`를 갖지만(197개) "그때 이게 근거였다"는 **과거 시점 기록**이라 코드가 나중에 바뀌어도 과거 근거는 유효하다. (단 code_locator_ids 없이 code EvidenceRef만 가진 매핑은 coverage gap으로 노출 — §3.)
- **코드의 의미를 자동 판정·자동 supersede 하지 않는다** — 바뀐 파일 추출·closure 계산까지만 기계, "의미가 진짜 낡았나"는 사람.
- **mark-checked는 staleness를 재확인하지 않는다(최종 리뷰 반영)** — 사람이 검토 선언한 매핑의 blocking closure 충족이 유일한 갱신 조건이다(`mark_checked`는 git을 받지 않는다). 안 바뀐 locator라도 그 reviewed closure가 입력 `--mappings`에 전부 들어오면 `commit_sha`가 `checked_head`(origin/develop ancestor)로 갱신된다 — 사람이 그 매핑을 검토했다고 선언한 것이라 무해하다. stale 여부 판정은 stale-check의 몫이고, §4의 "closure 충족이 갱신 조건"의 따름 정리다.
- **트리거(수동/git hook/정기)는 코어에 넣지 않는다** — `stale-check`는 명령일 뿐, 위에 나중에 자유롭게 연결.
- **매핑 외 kind(용어 등)는 1차 범위 밖** — 목적이 "의미=매핑". 필요해지면 후속.
- **AST 비교·심볼 본문 diff는 안 한다** — 파일 단위 변경 신호로 충분(과하면 "코드 자동 비교 금지" 철학 위반).

## 6. 데이터 사실 (이 세션 + codex 리뷰 실측)

- `path`를 직접 가진 kind는 **CodeLocator(363) · EvidenceRef(197)** 둘뿐. 매핑·용어·결정·ledger·review는 `path` 없음.
- **매핑 229개 중 `code_locator_ids`가 있는 건 208개, 비었거나 없는 게 21개**(그중 2개는 code EvidenceRef만 가짐) — 이 21개는 CodeLocator로 역추적이 안 돼 stale-check 사각(coverage gap으로 노출). (★초안의 "전부 역추적 가능"은 `grep -l`로 필드 존재만 세서 틀렸던 것 — codex가 `length>0`로 정정.)
- **매핑 status 분포: reviewed 222 / candidate 5 / superseded 2.** closure의 blocking 대상은 reviewed만 — superseded는 옛 매핑이라 제외, candidate는 미검수라 mark를 안 막고 warning.
- **2개 이상 매핑이 공유하는 CodeLocator가 57개**, 공유 locator의 reviewed 매핑 참조 최대 7개. (candidate 매핑 참조 locator 8개·superseded 참조 3개 — closure status 필터의 근거.)
- CodeLocator `commit_sha` 분포: `edde40210c` 347(2026-06-12 백필) · `dadce49d35` 11 · `b8f9a5b1b6` 4 · `45c1f12aed` 1. 363개 전부 commit_sha 보유. **4개 sha 전부 origin/develop의 조상**이라 `git diff` 기준점으로 안전(codex가 `merge-base --is-ancestor`로 확인).
- schema의 CodeLocator 필수 필드 = `(repo, path, locator_source, verified_at)`. **DomainMapping 필수 필드에 `code_locator_ids`는 없다**(schema.py:33) — 테스트도 "reviewed mapping with evidence but no code locator passes"를 명시(test_schema.py:63). 그래서 "모든 매핑에 code_locator_ids가 있다"는 계약이 아니다.

## 7. 테스트 (TDD로 구현)

엔진 레포의 합성 코퍼스 + 합성 git 환경으로:

- **변경 감지**: `commit_sha` 이후 그 파일이 바뀐 CodeLocator + 연결 매핑 → 후보. 안 바뀐 파일 → 후보 안 됨.
- **closure 갱신**: 공유 locator에서 일부 매핑만 `--mappings`로 주면 → `blocked: missing_mapping_ids`, commit_sha 불변. 영향 매핑 전부 주면 → `commit_sha`/`verified_at`/`updated_at` 갱신, `line_*` 불변.
- **checked_head 가드**: `--checked-head`가 현재 origin/develop과 다르면 실패.
- **coverage**: code_locator_ids 빈 매핑은 `uncovered_mappings`에 들어가고 후보 판정에서 빠진다.
- git 호출(`fetch`/`diff`)은 주입 가능하게 분리해 합성 입력으로 대체(네트워크·실레포 의존 없이).

## 8. 못 잡는 것 · 미결 (구현 plan에서 확정)

- **백필 이전에 이미 낡은 매핑은 못 잡는다** — `commit_sha`가 대부분 백필 sha(`edde40210c`, 6-12)이고, 백필은 줄/위치 **재검증**이지 "매핑 의미를 그 코드 기준으로 재검토함"이 아니다. 이 기능은 그 commit_sha **이후** 변경만 잡는다. 백필 이전에 이미 의미가 어긋난 매핑은 **별도 초기 감사**가 있어야 하며, 그건 이 P0 범위 밖이다.
- **code_locator_ids 없는 매핑 21개(그중 2개는 code EvidenceRef만)는 사각** — coverage 리포트로 "안 보고 있다"를 가시화만 한다(자동 처리 안 함).
- **첫 실행 후보 수**: 백필(6-12) 이후 변경을 다 잡아 후보가 많을 수 있다. 정상이며, 한 번 훑어 closure mark/supersede 하면 이후엔 "지난번 이후 변경"만 떠서 줄어든다.
- **`git fetch` 실패**(오프라인 등) 시 동작(에러 vs 마지막 알려진 develop)은 plan에서.
- **출력 정렬·그룹핑** 디테일은 plan에서.
- **CLI 위치**: 엔진 `cli.py`에 서브커맨드로 추가(기존 `list`·`mark-processed` 등과 같은 구조).

## 9. codex 리뷰 반영 기록 (2026-06-14)

codex(gpt-5.5) 적대 리뷰 7개 지적을 검증(핵심 수치 21·57·verified_at 직접 재확인) 후 전부 반영:

| 지적 | 반영 |
|---|---|
| Blocker 1: "전부 역추적 가능" false (빈 매핑 21개) | §3 "CodeLocator 연결 매핑만 범위" + coverage 리포트, §6 정정 |
| Blocker 2: locator 단위 mark가 공유 매핑 사각(57개) | §4 locator closure mark(A′) — 영향 매핑 전체 검토 시만 갱신 |
| 백필 SHA를 "의미 검토 기준점"으로 쓰는 표현 과함 | §0·§8 "위치 재검증 ≠ 의미 재검토, 백필 이전 낡음은 초기 감사" |
| mark-checked가 develop 이동 경합 못 막음 | §3 `target_head` 출력 + §4 `--checked-head` 가드 |
| commit_sha만 갱신하면 verified_at 의미 깨짐 | §4 `commit_sha`+`verified_at`+`updated_at` 동반 갱신(line 불변) |
| "path별로 묶어" vs "commit_sha 다르면 각각" 모호 | §3 구현 키 = `(path, commit_sha)` 명시 |
| EvidenceRef 제외 시 code 근거만 가진 매핑 2개 사각 | §3·§6 coverage gap으로 노출 |

**2차 재리뷰(2026-06-14) 추가 반영:**

| 지적 | 반영 |
|---|---|
| closure status 필터 미정 — superseded가 mark를 막고, candidate가 조용히 누락 | §4 closure = `reviewed`만 blocking, `superseded` 제외, `candidate`는 warning |
| verified_at을 sha로 갱신하는 표현(실제 ISODateTime) | §4 `commit_sha`=sha / `verified_at`·`updated_at`=mark 실행 시각 ISO8601 |
| coverage "21 + 2"가 23으로 읽힘(2는 21의 부분집합) | §3·§6·§8 "21개 중 2개는 code EvidenceRef만"으로 정정 |

YAGNI 판정(codex 동의): **안 함** = AST 비교·심볼 본문 diff·line 갱신·자동 supersede·hook/정기 실행. **최소치** = coverage 리포트·closure 처리·checked_head 가드·verified_at/updated_at 갱신·`--name-status`(rename/delete) 출력.
