# 2026-07-27 적재 2건 세션 리뷰 — 사실 원장과 실행 계획

> 대상: bb2 데이터레포에 같은 날 들어간 두 적재
> — `petskill-kamehameha`(버디스킬 광선 발사, 456객체, **미커밋**)
> — `ingame-item-usage`(인게임 아이템 사용, 944객체, 커밋 `d1294e7032`)
>
> 사용자가 "총체적 난국"이라 평가한 뒤 스냅샷 2건을 리뷰했다. 검증은 서브에이전트 25명
> (진단 7축 + 반박 4건, 설계 3안 + 판정단·적대공격, 실측 4축 + 적대검증 2회)과
> 메인의 직접 실측을 교차했다. 이 문서는 **확정된 사실만** 담는다.
> 리뷰 중 여러 번 정정이 있었고 그 이력은 남기지 않는다.
>
> **실행 계획은 5장이다.** 5.0~5.6이 확정본이고 5.7~5.10은 뒤집힌 초안(이력)이다.

---

## 1. 한 장 요약

문제는 네 갈래이고, 서로 **원인이 다르다**. 하나로 묶어 고치려는 시도가 이번 혼란의 원인이었다.

| 갈래 | 실체 | 급한가 |
|---|---|---|
| **A. 회상 게이트** | 적재를 깊게 한 도메인이 자기 이름으로 검색되지 않는다. 오늘 3개 컨텍스트가 새로 막혔고 그중 2개는 **무관한 기존 도메인** | **P0** |
| **B. 앵커 표시** | 코드 앵커의 `title`이 코드 원문 조각. 코퍼스 전체 3886개 중 2955개(76%) | P1 — 해법은 라우터 출력(5.0 D3 개정) |
| **C. 적재 무결성** | 원문 대조가 `audit`에서만 돈다. 게이트가 위 결함을 하나도 안 잡는다 | P1 |
| **D. 잘못 굳은 지식** | bb2 메모리 1건이 틀린 메커니즘을 기록하고 골든셋 왜곡을 지시한다 | P0 (싸다) |

**최근 엔진 수정은 원인이 아니다.** 검색 로직(`search.py`)은 2026-07-06 이후 무수정이고,
그때 변경은 게이트를 **여는** 방향이었다. `title = quote[:120]`과 앵커 게이트는 초기 커밋(6/19)부터 있었다.
오늘 드러난 것은 **적재 경로가 바뀌면서 엔진의 원래 동작이 처음 노출된 것**이다.

---

## 2. 사실 원장

### A. 회상 게이트

`search.py:124` `_ANCHOR_DF_MAX = 30`. `search.py:699-702`가 이렇게 판정한다 —
질의가 명부와 매칭되지 않고(`registry_match=False`) 질의 토큰의 **최소 문서빈도(df)가 30을 넘으면
검수 완료 결과 채널을 통째로 닫는다**.

- **2026-07-06 대응은 유효하고 작동 중이다.** 명부(`_registry_surfaces`, `search.py:621`)는
  GlossaryTerm의 `term`+`synonyms`+`aliases` 표면형 **1212개**로 차 있고, DomainContext 168개 중
  **156개가 명부로 통과**한다. `방해버블`(df 813)·`럭키박스`(52)·`고슴도치`(45)도 명부 덕에 열린다.
  2026-07-06에 백필한 7개 컨텍스트는 전부 살아 있다.
- **차단된 것은 5개, df통과 7개.**

| 컨텍스트 | 오늘 df | 오늘 적재 전 df | 판정 |
|---|---|---|---|
| 버디 스킬: 광선 발사 (KAMEHAMEHA) | 57 | **2** | 오늘 막힘 — 자기 적재로 자멸 |
| 오리지널 스테이지 클리어 토큰 | 34 | **30** | 오늘 막힘 — **부수 피해** |
| 버디스킬 망치 발동 모션 개선 (5.5) | 31 | **30** | 오늘 막힘 — **부수 피해** |
| 입장(시작) 팝업 UI 개선 | 32 | 32 | 전부터 막힘 |
| 인게임 아이템 사용 | 209 | 155 | 전부터 막힘 (오늘 만든 컨텍스트) |
| 광고 스킵 상품 (광고 제거) | 24 | 24 | 통과 — **다음 차례** |

`오리지널`은 df 30에 앉아 있다가 문서 4개가 늘어 34로 넘어갔고, `5.5`는 **30 → 31**,
문서 하나 차이로 막혔다. **적재할 때마다 무관한 기존 도메인이 무작위로 사라진다.**

**왜 오늘 두 적재는 명부에 못 들어갔나 — 파이프라인에 칸이 없다.**

설치되는 스킬 문서 `object-model.md:155`는 의무를 적어놨다:
> 대표 용어에는 사용자가 기능이나 도메인을 부르는 고유한 이름을 넣는다.

그런데 추출 스키마 `extract_template.js:9`의 `glossary_term`은 `{term_key, term, definition}`뿐이고,
조립기 `assemble_notes.py:63`은 `{term, definition}`만 넘긴다. **`synonyms`·`aliases`를 조용히 버린다.**
`run_ingest.sh`가 `notes.json`을 mktemp+trap으로 지워 손으로 끼워넣을 지점도 없다.

- GlossaryTerm 1181개 중 `synonyms` 있는 것 32개(2.7%), `aliases` 9개(0.8%) — 전부 손 백필분
- 6/25~7/17 적재들이 살아남은 건 **`term`을 한국어로 썼기 때문**(main-map 69개 중 67개 한국어)
- 오늘 두 적재는 코드 심볼 위주(kamehameha 36개 중 한국어 5개, item-usage 91개 중 6개)라 그 우연이 사라졌다

**추가 함정**: `KAMEHAMEHA (광선 발사)`처럼 괄호 병기한 `term`은 명부 표면형으로 죽는다.
명부 매칭은 표면형이 질의에 **통째로** 포함되어야 하는 부분문자열 방식이라, 표면형 전체인
`kamehameha (광선 발사)`가 질의에 그대로 들어있지 않으면 실패한다. 2026-07-06 설계가 예상하지 못한 형태다.

**상한 30의 출처**: 코퍼스 302문서 시절 캘리브레이션. 현재 df 모집단은 6369행(21배).
절대값이라 코퍼스 성장을 따라가지 않는다. 단 상한 조정은 2026-07-06에 4개 안 전부 기각됐다
(게이트를 느슨히 하면 거짓 양성 재도입). **명부가 정답 경로다.**

### B. 앵커 표시 — `title`과 키

- `assembly.py:68`(CodeLocator)·`:75`(EvidenceRef)가 `"title": quote[:120]` **하드코딩**.
  `:77`이 EvidenceRef `"summary": quote[:500]`. 노트가 `title`을 넘길 입구가 없고,
  `_ITEM_REQUIRED["code_anchors"]`(`:320`)에도 없으며 `validate_notes`는 항목의 모르는 필드를 조용히 버린다.
- **규모**: CodeLocator 3886개 중 읽을 수 있는 title 817개(21%), 코드 조각 2955개(76%), 애매 114개.
  title 길이가 정확히 120인 게 691개, **120 초과 0개** — 코퍼스가 이 컷을 벗어난 적이 없다.
- EvidenceRef 4214개 중 title이 summary 앞 120자와 같은 것 3340개(79%).
- **title은 검색 색인에 안 들어간다.** CodeLocator의 색인 표면은 `path`+`symbol`뿐(`surface.py:130-137`).
  실측: 문제의 앵커 색인 행 `surface_text`는 경로 + 심볼 두 줄뿐이다.
- **대신 title은 답변에 실린다.** `search.py:177`이 `linked.code_locators`에
  `{object_id, title, path, symbol}`을 담고, `cli.py:417·443`이 `[kind] id — title`로 출력한다.
- **실제로 색인을 오염시키는 건 `symbol`이다.** title 통로가 없어서 적재하는 쪽이 symbol에
  괄호 한글 주석을 넣고 있다 — 코퍼스 전체 **224개**(kamehameha 63/180). 이건 색인에 들어간다.
  그리고 **이미 거짓이 있다**: `disturb-force-pop--2`/`pop-presentation--5`/`pop-target-filter--4`는
  `verified_quote`가 글자까지 같은데 symbol 라벨이 서로 다르고 3개 중 2개가 그 코드에 대해 거짓이다.
  `code_verify`는 symbol을 보지 않는다고 docstring이 못박았다.

**키 규약은 네 가지가 섞여 있다.**

| 형태 | 개수 | 대표 |
|---|---|---|
| 순번형 `--<숫자>` | 3255 (83.8%) | ingame-item-usage 393, kamehameha 180, ball-select 131 |
| 단일하이픈 의미형 | 549 (14.1%) | ingame-logic·ingame-view 등 |
| 꿀통형 `--<낱말>` | 73 (1.9%) | stage-clear-token 39, petskill-honeyjar 24, enter-popup-ui 10 |
| 점 3단 | 9 (0.2%) | sally-canoe |

- `assembly.py:315` `_ANCHOR_KEY_RE = ^[a-z0-9]+(?:-[a-z0-9]+)*(?:--[0-9]+)?$` —
  이중하이픈 뒤 **숫자만** 허용. **기존 코퍼스의 82개(꿀통형 73 + 점3단 9)를 엔진이 거부한다.**
  즉 그 객체들은 지금 재적재가 불가능하다.
- `--` 없는 의미형 키는 지금도 통과한다. 순번을 그만 쓰는 데 엔진 변경은 필요 없다 —
  고칠 곳은 `assemble_notes.py:52`의 `ak = f"{mk}--{i}"` 한 줄(정본은 **이 레포 템플릿**).
  깨지는 테스트 4곳(`test_assemble_notes.py:30·32·39·180`).
- `lint.py`에 키·id 형식 검증이 **0건**(`re.compile` 0건). 위반 키 82개가 그래서 조용히 살아 있다.

### C. 객체 수 구조

- 앵커 1개 → CodeLocator + EvidenceRef 1쌍(`assembly.py:62-81`). **중복 제거가 없다.**
  같은 코드가 3개 매핑에 걸리면 3쌍이 만들어진다. kamehameha에서 같은 `(path, quote)` 11묶음,
  여분 12개, 포개짐 쌍 20건.
- **1:1은 엔진 요구가 아니다.** `schema.py:251-252`는 reviewed DomainMapping에
  `evidence_refs` **1개 이상**만 요구한다. 실증: reviewed 매핑 20개는 `code_locator_ids`가
  비었는데도 기획서 근거만으로 통과하고, 코퍼스 매핑 1030개 중 227개는 두 필드 개수가 다르다.
  **앵커를 지울 때 짝 evref도 같이 지워도 된다.**
- EvidenceRef 4214개는 **색인 0행**(`surface.py:32` `EXCLUDED_KINDS`), 디스크 16MB.
  단 `schema.py:231`이 죽은 필드가 아니라고 못박는다 — 라우터의 근거 표기(`router.py:360`)와
  원문 접근(`:748`)이 소비한다.
- 구세대 부채: evref가 아무도 안 가리키는 CodeLocator **607개**, `locator`가 dict가 아니라
  경로 문자열인 evref **337개**.
- **입도는 광선발사가 아니라 도메인 형태의 문제다.** kamehameha 앵커 180개가 파일 57개에 걸쳐
  있고 앵커 1개뿐인 파일이 26개(45.6%), `(path, symbol)` 조합 176/180 — 거의 다 다른 함수다.
  item-usage는 393개가 파일 75개, 1개뿐인 파일 30개. 기능이 분산 분기로 구현된 결과다.

### D. 적재 무결성 — 게이트가 아무것도 안 잡았다

- `verified_quote` 원문 대조는 **`audit`에서만** 돈다. `save_object`·`ingest`·`build` 어디에도 없다.
  쓰기가 검증보다 앞서고, 사후 검증 실패는 롤백하지 않는다.
- item-usage 적재의 `--dry` build는 "945객체, 경고 0", lint 0건, 회귀 통과였다.
  그 안에 title 393/393 오염, 순번 키 393개, 자정 타임스탬프 393개가 다 들어 있었다.
- **키 중복은 무신호다.** `build()`는 같은 key 2개를 같은 id 객체 2개로 만들고
  `ingest`가 마지막 것만 남긴다. 오류도 경고도 없다.
- 검증 커버리지 착시: 앵커 3886개 중 `verified_quote`를 가진 것은 **579개뿐**.
  나머지 3307개는 audit이 skipped로 넘어간다. "앵커가 촘촘하니 검증되고 있다"는 감각은 과대평가다.
- `593112e`(7/23) "reject unverifiable finalizer state"가 kamehameha 세션의 `--capture-baseline`을
  막았다. **의도된 fail-closed이고 실제로 결함 1건을 찾아냈다.** 문제는 차단 이유
  (`quote_not_found` + locator id)가 두 층에서 버려져 "고립 baseline 결과가 올바르지 않습니다"만
  남은 것 — 진단 코드는 설치되는 템플릿(`finalize_ingest.py`)에 있다.
- 타임스탬프: `verified_at`은 `NOW`와 무관하게 spec의 `VERIFIED_AT`이 그대로 들어간다
  (`assemble_notes.py:56`). `NOW`는 `created_at`/`updated_at`만 정한다(`cli.py:678`).
  설치 문서 `ingest-tools.md:39`는 "생략하면 엔진이 `verified_at`까지 자동으로 박는다"고
  **거짓 안내**를 한다. 엔진에 시각 형식·정합성 검증은 없다.

---

## 3. 두 세션 진단 채점

### `petskill-kamehameha` 세션

| 세션이 지목한 원인 | 판정 |
|---|---|
| 앵커 180개 중 77개 노이즈 = 내 프롬프트 탓 | **맞음.** 덤으로 `object-model.md:61-62`에 절제 규칙이 이미 있어 문서 위반이기도 함 |
| title = 스캐폴드가 안 넘겨 엔진이 폴백 | **틀림.** 폴백이 아니라 무조건 덮어씀 |
| 앵커 ID `--8` = 스캐폴드 탓 | **맞음.** 다만 정본이 bb2가 아니라 이 레포 |
| 자정 타임스탬프 = 내 실수, 엔진 정상 | **절반.** `verified_at`은 다른 경로. 설치 문서가 거짓 안내 |
| EvidenceRef 203개 = 순수 부속물 | **절반.** 180개만 코드 1:1, 23개는 commit·pr·jira·spec |
| 회상 3건 실패 | **원인 자체를 놓침** — 앵커 게이트 |
| `assemble_notes.py`는 팀 공유 파일이라 승인 필요 | **틀림.** 엔진 템플릿 설치본. bb2에서 고치면 영구 드리프트 |

세션이 결함으로 올렸지만 **결함이 아닌 것**도 걸러졌다 — 앵커 `status="reviewed"` 하드코딩은
2026-07-23 계획서와 테스트로 못박은 의도된 설계, `line_start` 부재는 2026-07-03 "영구 보류" 확정.

미결: 앵커 정리 180→103은 **아예 실행된 적이 없다**(되돌려진 게 아니다).

### `ingame-item-usage` 세션

**잘한 것**: 5축 역추적 + 적대검증으로 정정 58건, 원자 70→66 병합 심사,
`--dry` build → lint → 회귀 baseline → 적재 → 게이트 → 재적재 루프,
남의 미커밋 적재와 섞이지 않게 자기 것만 골라 커밋. 완전 중복 앵커 23개(6%)뿐 —
kamehameha 노이즈 77개(43%)와 질이 다르고 **앵커 393개는 정당하다**.

**틀린 것**: 회상 실패를 "짧거나 추상적인 질의를 게이트가 의도적으로 거른다",
"여러 컨텍스트에 걸치는 토큰은 점수가 분산돼 게이트를 못 넘는다"로 결론.
실제는 df 상한 초과로 **채널을 통째로 차단**하는 것이다. 그 세션이 "잘 나옴"으로 묶은 3개는
서로 다른 세 이유로 통과했다 — `게이팅`(df 19) 희귀, `액티브`(df 8) 희귀,
`아이템 사용 확인 팝업 조건`은 df 228인데 **명부 매칭**으로. 하나의 규칙으로 뭉갠 결과 예측력이 없다.

**그 오진이 메모리로 굳었다** — `brain_search_gate_drops_abstract_query.md`.
가장 문제는 "How to apply"다:
> `FINALIZATION.recall_checks` 질문도 추상 표현으로 쓰면 통과 못 하니 구체 표현으로 선언한다.

**골든셋을 엔진 결함에 맞춰 왜곡하라는 지시**이고, 그 세션이 실제로 `use-entry` 질의를 교체했다.

또한 `history_coverage=unsearched`인데 `claim_status=reviewed`로 적재해
DecisionRecord 0개·기획서·PR·Jira 근거 0개가 됐다. 한계를 선언했으니 숨긴 건 아니지만
두 값의 조합을 엔진이 막지 않는다.

미결: `item-standby-exit-return-and-freeze-watchdog` 매핑 하나에 앵커 19개 — 세션이 재분할을 권했고 답을 못 받았다.

---

## 4. 소관

| 갈래 | 엔진 코어 | 설치되는 템플릿(이 레포, 수정 후 bb2 재설치 필요) | bb2 데이터 |
|---|---|---|---|
| A 게이트 | — (이미 구현) | `extract_template.js` 스키마, `assemble_notes.py` 배관, `object-model.md` 규칙 | 대표명 백필 |
| B 표시 | `assembly.py` title 결정, `lint.py` 키 검증, `_SET_ALLOWLIST` | `assemble_notes.py:52` 키 생성 | 2952개 백필 |
| C 무결성 | 쓰기 시점 quote 대조, key 중복 오류, 객체 퇴역 | `finalize_ingest.py` 진단 전달, `ingest-tools.md:39` 거짓 안내 | — |
| D 지식 | `ROADMAP.md:294` 조건 누락 | — | 메모리 1건 정정 |

`.claude/skills/bb2-brain-ingest`는 `.agents/skills/...`로 가는 심링크이고,
그 19개 파일 전부가 `.project-brain-manifest.json`에 sha256으로 등록된 **엔진 렌더 사본**이다
(전수 비교 결과 23개 파일 IDENTICAL). 예외는 `references/project-code-verification.md` 하나(bb2 overlay).
bb2 사본을 고치면 installer가 사용자 수정으로 보고 **영구히 skip** 한다 — 되돌아가는 것보다 발견이 어렵다.
그리고 bb2 `brain/install.sh:83-85`가 install을 일부러 빼므로 **엔진 템플릿 수정이 자동 전파되지 않는다**.
`doctor.py`에 설치본 드리프트 점검도 없다(manifest·skill·template 문자열 0건).

---

## 5. 실행 계획 (확정본, 2026-07-27 19:00)

> 아래 5.0~5.6이 **확정본**이다. 그 뒤의 5.7~5.10은 확정 전 초안이며 이미 뒤집힌 판단이
> 들어 있다(특히 5.8 "재적재 불가"와 5.9 "title 통짜 symbol 교체"). **읽지 말고 이력으로만 둔다.**
>
> 확정 경로: 실측 4축(에이전트 4명) → 1차 적대검증 13건 → 통합 계획 24개 → 2차 적대검증 21건.
> 모든 숫자에 파일:줄 또는 실행 명령 증거가 붙어 있다.
>
> **task별 구현 세부(변경 지점·red 테스트·검증 명령·심사 반영)는
> [docs/plans/2026-07-27-ingest-fix-execution-plan.md](../plans/2026-07-27-ingest-fix-execution-plan.md)에 있다.**
> 이 장은 결정·순서·범위만 담는다.

### 5.0 확정된 결정

| 번호 | 결정 | 출처 |
|---|---|---|
| D1 | `ingame-item-usage`(944객체, 커밋됨)도 **삭제 후 재적재** — 19:20 재결정 | 사용자 |
| D2 | `petskill-kamehameha`(456객체, 미커밋)는 **삭제 후 재적재**, 앵커 키는 **의미형** | 사용자 |
| D3 | `title`에 **사람이 새로 쓴 문장을 넣지 않는다** | 검증 |
| D4 | **코드 재순회·재검증 안 한다** — 백업 `verify.json`으로 재조립하면 기존 `notes.json`과 바이트 동일함이 실측됨 | 검증 |
| D5 | 앵커 df 상한 조정 · `line_start` 복원 · 앵커 `status`→`candidate` **안 한다** | 종결된 건 |

**D1 개정 근거 (2026-07-27 19:20)** — 처음 D1을 "백필만"으로 잡은 근거는 "이미 커밋돼 손대기
어렵다"였는데, 실측으로 **거꾸로**였다. 두 적재의 오염 종류는 똑같고, 커밋됐다는 건 되돌리기가
더 쉽다는 뜻이다.

| | `ingame-item-usage` | `petskill-kamehameha` |
|---|---|---|
| 앵커 수 | 393 | 180 |
| **순번형 키** | **393 / 393 (100%)** | 180 / 180 |
| 코드조각 title | 347 | 137 |
| **`verified_at` 자정** | **393개 전부 `2026-07-27T00:00`** | 180개 전부 |
| `verified_quote` 보유 | 393 (전부) | 180 (전부) |
| git 추적 | **393개 전부 추적** → `git restore` 가능 | **0개 (미추적)** → 백업본 하나에 의존 |

**백필로는 순번 키 393개와 자정 시각 393개를 절대 못 고친다** — id는 파일명이자 다른 객체가
가리키는 참조 대상이고, `verified_at`은 `updates` allowlist 밖이다. 그리고 재조립 입력이
백업에 다 있다(`item-usage-session/ingest/`의 `verify.json`·`domain_spec.py`·축별 원자 6개) —
kamehameha와 똑같이 **코드 재순회 없이** 재조립이 가능하다.

**D3 개정 — "title 폴백을 symbol로" 통짜 적용은 기각됐다.** 근거 셋.

1. **라벨이 오히려 뭉개진다.** 같은 매핑 안에서 `(symbol, path)`가 완전히 같아지는 앵커가
   **1356개 / 460 매핑**이다. `mapping.ingame-item-usage.item-enum-class-factory-switch`는
   `--0`~`--5` 여섯 개가 전부 `ItemManager::makeBeforeAndInGameItemObject`로 수렴한다.
   지금은 title이 코드 조각이라 최소한 어느 분기인지는 갈린다.
2. **읽을 수 있는 title 932개를 지운다.** title에 한글이 있고 symbol에는 없는 앵커가 932개다.
3. **불만의 실제 발생지는 `router.py:265`다** — 검수완료 구현위치 섹션이 bare id만 낸다.
   바로 위 `:257-262`의 후보 목록은 이미 `{id, path, symbol}`을 낸다. 같은 함수 안의 비대칭이다.

**D2 실행방식** — 조립기 기본 키는 **순번형 그대로 두고**, 의미형은 `domain_spec` HOOK으로만 심는다.
라벨 문제는 `router.py:265`에서 푼다. 의미형을 기본 규약으로 올리면 모든 적재가 판별어 손
큐레이션 단계를 지나야 하고(심볼이 유일 판별자가 아니다), 그 절차가 어디에도 없다.

### 5.1 순서 — 네 구간, 경계를 넘을 때 재설치가 따라온다

```
구간 1  엔진 코어   T1~T9    편집 설치라 저장 즉시 반영 → 병렬 세션 주의 (5.4 참조)
구간 2  템플릿·문서 T10~T14  파일 사본이라 install 없이는 bb2에 안 닿는다
구간 3  경계        T15~T17  엔진 검증·커밋 → bb2 재설치 → 스냅샷
구간 4  데이터      T18~T28  kamehameha 재적재 → item-usage 재적재 → 백필 → 골든셋 → 지식 정정
```

**T18(kamehameha 삭제)을 title 백필보다 먼저 끝낸다.** 1차 검증에서 재현된 좀비 부활 때문이다 —
`ingest.py:33`이 precondition 대상 객체가 **사라진 경우를 조용히 건너뛴다**. build로 사전조건을
뜬 뒤 kamehameha를 지우고 백필을 적재하면 지운 앵커가 옛 순번 키로 되살아난다
(스크래치에서 3건 재현, 전량이면 최대 180건, 오류·경고 0, lint·audit 통과).

### 5.2 task 24개

**구간 1 — 엔진 코어** (전부 red 테스트 먼저. 실측: 이 9개를 다 넣고 pytest `674 passed` 유지)

| id | 무엇 | 핵심 |
|---|---|---|
| T1 | `ingest` 사전조건 대상이 사라졌으면 **오류로 승격** | 좀비 부활의 유일한 기계 차단선. `ingest.py:33` |
| T2 | `title` 폴백을 `symbol`로 | `assembly.py:68·75`. `summary=quote[:500]`은 그대로 |
| T3 | 노트 5개 키 섹션의 key/id **중복을 오류로** | 지금은 마지막 것만 남고 무신호. glossary·mappings·sources도 같은 구멍 |
| T4 | `_SET_ALLOWLIST`에 `CodeLocator.title` | 백필의 유일한 안전 통로. `extra_objects`는 사전조건이 비어 무신호 덮어쓰기 |
| T5 | 라우터 검수완료 섹션에 `path`·`symbol` 동반 | **D3 개정의 핵심.** 이걸 안 하면 B갈래가 사용자에게 안 닿는다 |
| T6 | lint 키·id 형식 검사를 `ok`와 분리된 **warning**으로 | 유산 82개가 있어 차단하면 멱등 재적재조차 죽는다 |
| T7 | `extra_objects`·`--objects-file` 신규 id **하드 게이트** | warning이 못 막는 입구 |
| T8 | `ingest` 앞단 quote 원문 대조 게이트 | 지금은 audit에서만 — 쓰기가 검증보다 앞선다. blob 캐시로 180앵커 1.53초 |
| T9 | `mark-checked`: `verified_quote` 없는 앵커의 검증 주장 갱신 거부 | 지금 워킹트리 드리프트 20개 중 19개가 이 경로 |

**구간 2 — 템플릿·문서**

| id | 무엇 | 핵심 |
|---|---|---|
| T10 | 조립기 배관 — 앵커 key 선택 입력 + glossary `synonyms`/`aliases` 통과 | 명부가 안 채워진 파이프라인 구멍의 실체. 엔진 build는 이미 읽는다 |
| T11 | `extract_template.js` 스키마·작명 규약 | 한국어 term 비율이 6%~97%로 튄 원인. 골격이 심볼을 방치한다 |
| T12 | finalize·batch 러너가 버리는 **진단 4종** 전달 | 오진의 직접 원인. `needs_clarification`을 버려서 게이트 차단과 순위 밀림이 같은 리포트로 나온다 |
| T13 | 설치되는 문서층 일괄 정정 (G 갈래 전체) | 회상 게이트 설명이 설치 문서 전체에 **0건**이다 |
| T14 | 문서-코드 **기계 대조** 계약 테스트 7종 | 지금 계약 테스트는 문서를 문서와만 비교해 거짓 문장을 오히려 보호한다 |

**구간 3 — 경계**

| id | 무엇 | 완료 조건 |
|---|---|---|
| T15 | 엔진 검증 → 커밋 → 워킹트리 청결 | pytest 674+ / templates unittest OK / `git status --porcelain` 빈 출력 |
| T16 | bb2 `project-brain install` | 리포트의 `skipped`가 **빈 배열**. 두 번째 install이 전부 빈 배열(멱등) |
| T17 | brain 스냅샷 | `.snapshots/2026-07-27/pre-cleanup/`. git으로 못 돌아오는 범위 180개 고정 |

**구간 4 — 데이터**

| id | 무엇 | 핵심 |
|---|---|---|
| T18 | kamehameha 456객체 삭제 | 7개 glob. **`raw/sources/…/spec-v1.1.md`는 안 지운다** — 가드의 `EXPECTED_RAW_CHUNKS`에 +9가 들어있다 |
| T19 | 재조립 — 노이즈 77 제거 · MOVE 1 · meaning 2 · 의미형 키 103 · synonyms · 실시각 | `patch_sources.py`를 빼먹으면 EvidenceManifest 5개가 조용히 달라진다 |
| T20 | build → baseline → ingest → finalize (색인 재생성 1회) | 24개 대조 검사. **회상 실패는 3갈래로 분류**하고 질문을 바꿔 통과시키지 않는다 |
| **T25** | **item-usage 재조립 대조 dry-run** — 백업 `verify.json`으로 재조립해 기존 944객체와 비교 | **아직 안 돌린 유일한 미확인 항목.** kamehameha는 바이트 동일 실증됨, item-usage는 미검증. 어긋나면 왜 어긋나는지부터 본다 |
| **T26** | **item-usage 944객체 삭제** | git 추적이라 `git restore`로 되돌아온다(kamehameha보다 안전). `raw/sources`는 남긴다 |
| **T27** | **item-usage 재조립** — 노이즈 제거 · 의미형 키 · 실시각 · synonyms | 노이즈 목록의 출처를 먼저 확정해야 한다 (아래 주의) |
| **T28** | **item-usage build → baseline → ingest → finalize (색인 재생성)** | T20과 같은 24개 대조 검사. 회상 질문은 run2의 **원문**을 쓴다(바꿔치기된 run3 문구 아님) |
| T21 | 대표명 백필 — 차단 **2개** + 경계선 1개 (`union`) → 색인 재생성 | synonyms는 색인 표면이라 rebuild **필수**. 안 하면 전 세션이 stale로 죽는다 |
| T22 | title 백필 — 잘린 인용임이 증명되는 집합만 | 지문 불변이라 **rebuild 불필요**(실측: `faa1b03e…027a` 동일) |
| T23 | 골든셋 s18~s21 + 실코퍼스 가드 개수 15→19 | `test_real_corpus.py:110`이 개수를 하드 단정한다 |
| T24 | 지식층 정정 — bb2 메모리 · ROADMAP 조건 · 사례 로그 | 메모리의 "점수가 분산돼" 설명이 틀렸다. 점수는 reviewed 바닥의 6배였고 막은 건 앵커뿐 |

**D1 재결정의 파급 (계획 여러 곳이 줄어든다)**

- **T22(title 백필)가 크게 줄어든다.** 대상 507건 중 `ingame-item-usage` 224 + `kamehameha` 97 =
  **321건이 재적재로 처리된다**(엔진 폴백이 build 시점에 `title=symbol`을 넣는다). 남는 건 **186건**.
  5.3의 범위 확대를 적용해도 백필 규모가 절반 아래로 떨어진다.
- **T21(대표명 백필)에서 item-usage가 빠진다** — 재조립 때 `synonyms`를 직접 심는다.
  남는 대상은 `stage-clear-token`·`petskill-hammer-motion` 2개 + 경계선 `ad-skip-product` 1개.
- **자정 `verified_at` 573개(393+180)가 실시각으로 정상화된다.** 백필로는 손댈 수 없던 것이다.
- **색인 재생성이 1회 늘어난다** — kamehameha finalize · item-usage finalize · 대표명 백필로 3회.
  T22는 지문 불변이라 여전히 불필요하다.

> **T27 착수 전에 확정할 것 — item-usage 노이즈 앵커 목록의 출처.**
> kamehameha는 심사 결과가 `drop_anchors.json`·`prune.json`으로 백업에 남아 있는데,
> item-usage 백업에는 그에 해당하는 파일이 없다. "노이즈 23개"는 그 세션 스냅샷 본문에서
> 읽은 숫자다. 목록을 스냅샷에서 복원할 수 있는지 먼저 확인하고, 없으면
> **앵커 구성은 그대로 두고 키·시각만 정상화한다**(D4 정신: 순회한 데이터 자체는 참이다).
> 앵커 심사를 처음부터 다시 하는 것은 이번 범위가 아니다.

### 5.3 2차 적대검증 반영 — blocker 3건은 반드시 고쳐서 착수한다

**BL1. T7·T6의 id 형식 판정 규칙이 엔진 자기 산출물을 거부한다** (실측 498건 중 382건, 77%)

계획의 규칙("id를 `.`으로 나눠 3조각이 아니면 위반")은 엔진이 스스로 만드는 정상 모양을 위반으로 센다 —
`context.<key>`(2조각), `review.<대상 전체 id>`(4~5조각), `projection.<ctx>.<req>.reuse`(4조각),
jira 근거(`assembly.py:133`이 대문자 Jira 키를 그대로 붙인다). **그대로 착수하면 T20의 kamehameha
재적재가 통째로 거부되고**(신규 4개가 걸린다), 앞으로 새 컨텍스트를 만드는 모든 적재가 막힌다.

→ **kind별 id 문법을 따로 선언**하고, T7의 하드 게이트는 **CodeLocator와 짝 EvidenceRef의 앵커 키에만** 건다.
→ T6의 warning도 앵커 키로 좁혀 첫날부터 82건에서 시작한다. T12가 finalize 최상위로 올리는 것은
   **이번 적재가 새로 만든 위반만**(store에 이미 있던 id 제외) — 안 그러면 매 적재 498줄이 영구히 붙는다.
→ T7 red 테스트에 **정상 케이스**(새 DomainContext 1개 + jira evref 1개가 통과)를 반드시 넣는다.

**BL2. T5가 사용자가 실제로 쓰는 경로에서 답을 더 못 읽게 만든다**

`query/SKILL.md:25`가 지시하는 그대로 `--db` 없이 돌리면 지금도 출력이 **417KB**다 — 색인이 없으면
라우터가 reviewed CodeLocator 전량 폴백(`router.py:503-504`)으로 가서 3634개를 붓는다.
T5는 거기에 항목마다 `path`·`symbol`을 더해 **1.1MB**로 만든다. 더 나쁜 건 T5의 verify가 `--db`를
붙여 돌리게 돼 있어 **이 폭발을 원리상 관측하지 못한다**(`--db`를 주면 게이트가 닫혀 0개다).

→ T5는 `recalled is not None`일 때만 `locators`를 붙인다. 폴백 경로는 지금처럼 id만.
→ 폴백 자체에 상한 + `truncated: 3634` 표시를 둔다. 3634개 bare id 덤프는 T5 이전에도 답이 아니다.
→ **T5의 `depends_on`에 T13(문서 `--db` 안내)을 넣는다.** verify는 `--db` 없이/있이 두 번 돌려 바이트 수를 기록.

**BL3. T13이 자기 계획으로 거짓이 되는 문장을 문서에 새로 새긴다**

T13은 `object-model.md`에 "`updates`는 세 kind만 받는다"는 표를 넣는데, 같은 릴리스의 T4가
`CodeLocator.title`을 allowlist에 추가하고 T22가 그 경로로 백필한다. **이번에 고치려던
거짓 안내와 정확히 같은 종류의 결함이다.**

→ T13의 `depends_on`에 T4를 넣고 표에 `CodeLocator | title | (없음)` 행을 추가한다.
   "앵커의 `path`·`symbol`·`quote`는 여전히 `updates`로 못 고친다 — `amend`를 쓴다"를 함께 적는다.
→ T14에 **7번째 기계 대조**를 추가한다 — 문서의 allowlist 표를 파싱해 `_SET_ALLOWLIST`·
   `_UNION_ALLOWLIST`와 kind·필드 단위 집합 비교.

**나머지 반영 (serious 5 + minor 3)**

| 지적 | 반영 |
|---|---|
| **엔진 편집 = 병렬 세션에 무통보 배포** | 편집 설치라 `T1~T9`를 **저장하는 순간** 다른 세션의 build/ingest/audit·bb2 가드까지 새 코드로 돈다. 오늘 실제로 두 세션이 병렬로 돌았다. → 별도 워크트리에서 편집하고 검증은 `PYTHONPATH=<워크트리>/src`로만. 최소한 T1 앞에 **"엔진 편집 구간 동안 bb2 적재 금지" 합의 단계**를 task로 세운다 |
| **T22 범위가 83%를 남긴다** | 계획대로면 코드조각 title 2950개 중 **2441개(83%)가 그대로 남는다**. 사유 분포는 잘린 증거 없음 2170 / 중복 226 / 괄호 45인데 `out_of_scope`에 2170이 이름으로 안 나온다. → 범위를 **"코드처럼 보이는 title"**(`;`·`{`·`->`·`::`·`if(`·`return ` 중 하나를 품고 한글 없음)로 넓히되 **중복 226과 괄호 45는 계속 제외**한다. 표본 200개로 오판율을 재고 넘어간다 |
| **EvidenceRef title 2919개는 고칠 길이 없다** | T4가 넣는 건 CodeLocator뿐. 그런데 `show` 이웃 목록(`cli.py:442-443`)과 graph 라벨(`graph_viz.py:29`)은 EvidenceRef title을 읽는다 — T22가 개선한다는 바로 그 화면이다. → T4에 `"EvidenceRef": {"title"}`을 함께 넣는다 |
| **T17 스냅샷이 되돌리기를 비싸게 만든다** | `index.db`·`stale-set.json`이 빠져 복구가 파일 복사에서 **실모델 rebuild**로 승격되고, 그 동안 bb2 검색이 정지한다. → 둘을 스냅샷에 넣고 rollback을 "파일 3개 되돌리기 → `search`로 stale 없음 확인 → 어긋나면 그때만 rebuild"로 바꾼다 |
| **T11이 D2 결정과 충돌한다** | `extract_template.js`에 `anchor_key` 칸을 만들면 추출 작업자가 그 칸을 채운다(term 칸이 빈 문자열이라 코드 심볼이 들어찬 것과 같은 기제). 그러면 다음 적재부터 손으로 붙인 의미형 키가 들어오는데 유일성 검사는 kamehameha spec 안에만 있다. → **`anchor_key`를 추출 스키마에 넣지 않는다.** T10의 조립기 선택 입력만 열고 `domain_spec` HOOK 경로로 한정 |
| **T2의 노트 title 입구가 죽은 칸이 된다** | 값을 넣을 경로가 스캐폴드 어디에도 안 생긴다(T11·T10·T13 전부 앵커 title 없음). → **입구를 열지 않는다.** 폴백을 `a["symbol"]` 단일로 두면 title 타입 검사도 필요 없어진다 |
| **T22 verify가 숫자 동치라 조용히 맞춰질 수 있다** | 규칙을 다시 구현하면 대상 수가 달라지는데(계획 본문 507/97/98은 재현값 **509/99/94**), 그때 규칙을 고칠지 숫자를 고칠지 안 정해뒀다. → 백필 직전에 **대상 id 목록을 파일로 떨어뜨리고**, verify를 "그 파일의 모든 id가 `title==symbol`이고 파일 밖 CodeLocator는 title 불변"으로 바꾼다 |
| **T21·T22 verify에 실코퍼스 가드가 없다** | 색인 행 수 대조(ContextProjection stale 감지 포함)가 T23까지 안 돈다. stub 임베더로 도니 실모델 비용 0이다. → 두 task의 verify에 `brain/checks` unittest를 넣고, T22에 "대상이 어떤 projection의 `source_object_ids`에 있는지 확인 → 있으면 `projection refresh`" 한 줄 추가 |
| **엔진 해석 경로가 계획 안에 두 개** | T18·T21·T22는 `PYTHONPATH=<engine>/src`, T20은 finalize를 통해 bare `project-brain`(`finalize_ingest.py:189-201`)을 쓴다. 지금은 같은 클론을 가리키지만 다른 checkout이 가로채면 게이트가 조용히 달라진다. → 하나로 통일하는 결정을 T15에서 못 박는다 |
| **질문 바꿔치기를 막는 장치가 여전히 없다** | 이번 사고의 원인 중 하나인데 `finalize_ingest.py:286`의 config에 질문 잠금이 없다. → 최소한 **"리포트에 이전 질문을 함께 남긴다"**를 T12에서 기계로 넣는다 |
| **`session-ingest/SKILL.md` 검수 규칙 완화** | 이번 사고와 무관한 경로다. → 문구 정정은 확정된 검수 정책과 맞으므로 유지하되, **무관한 변경임을 커밋 메시지에 적고** 확인 수단이 없다는 사실을 기록한다 |

### 5.4 되돌리기

| 구간 | 되돌리는 법 |
|---|---|
| 엔진 코어·템플릿 | `git revert`. 편집 설치라 되돌린 즉시 반영된다 |
| bb2 재설치 | `project-brain install`을 이전 엔진 커밋에서 다시 돌린다 |
| kamehameha 삭제·재적재 | 백업본에서 456개 복사 → `lint` 0 확인 → **스냅샷 `index.db`·`stale-set.json` 되돌리기** → `search`로 stale 없음 확인. git으로는 못 돌아온다(`/brain` exclude로 전량 미추적) |
| item-usage 삭제·재적재 | `git restore brain/objects/` — 944개 전부 추적이라 커밋 `d1294e7032` 상태로 정확히 돌아온다. 그 뒤 스냅샷 `index.db`·`stale-set.json` 되돌리기 |
| 대표명 백필 | 스냅샷 `objects/domain/` 되돌리기 + rebuild(synonyms는 색인 표면이라 필수) |
| title 백필 | 대상 목록 파일 기준으로 스냅샷에서 되돌리기. rebuild 불필요 |

### 5.5 범위 밖 (기록하고 방아쇠를 적어둔다)

- 엔진 **객체 퇴역 명령** — 지금은 파일 rm. 방아쇠: 재적재가 또 필요할 때
- **EvidenceRef 1:1 감축** — 앵커마다 evref를 하나씩 만드는 구조 자체
- **`symbol` 괄호 한글 주석 94개 정화** — `PopupOriginalStageContinue::showBuySuccessPopup (분기 콜백 … 라인 2158)`
  처럼 폐기한 줄번호를 품고 있다. 정화 전에 title로 옮기면 좌표가 답변 라벨로 승격된다
- **`/brain` exclude 처리** — `.git/info/exclude:18`. kamehameha 457개가 `git clean -x`에 취약
- **`disturb-bubble-system` 미커밋 드리프트 20개** — `mark-checked` 결과, 19개가 `verified_quote` 없이 commit만 최신
- **한글 title 932개** — symbol보다 정보량이 크므로 손대지 않는다
- **잘린 증거 없는 코드조각 title 2170개** — 5.3의 범위 확대를 적용하면 대부분 들어온다. 남는 것은 숫자로 남긴다

### 5.6 이전 초안 (이력. 뒤집힌 판단이 들어 있다)

### 5.7 먼저 할 것 — A와 D (싸고 효과가 크다)

1. `extract_template.js`의 `glossary_term` 스키마에 `synonyms` 추가
2. `assemble_notes.py`가 그 값을 버리지 않고 넘기게 + `test_assemble_notes.py` 회귀
3. `object-model.md`에 규칙 추가 — "괄호 병기한 `term`은 명부 표면형으로 매칭되지 않는다.
   순수 대표명을 `synonyms`에 따로 넣는다"
4. `ROADMAP.md:294`의 "빈도 무관이라 코퍼스 성장에 안 무너진다"에 조건 명시 —
   **명부에 등록된 엔티티에 대해서만** 참
5. bb2: 차단된 5개 + 경계선 1개 대표명 백필 → 색인 rebuild → eval
6. bb2: `brain_search_gate_drops_abstract_query.md` 정정 (메커니즘 + "골든셋은 실제 질문으로 쓴다")

효과: 오늘 무너진 3개 즉시 복구, 앞으로 적재마다 무너지는 것 중단.
엔진 코어 수정 0. `search.py` 무수정.

### 5.8 B는 계획을 바꿔야 한다 — 재적재가 지금 불가능하다

적대검증이 세 설계안 공통 **blocker**를 찾았다.

> `ingest`는 쓰기만 하고 지우지 않으며 CLI 전체에 삭제·prune 서브커맨드가 없다(`_run_*` 20개 전수 확인).
> 재적재를 시뮬레이션하면 옛 CodeLocator 180 + 옛 evref 180이 그대로 남아
> **isolated 15→375, lint 문제 0(무신호)**, audit의 `ok` 식은 isolated를 아예 보지 않는다.
> `index rebuild`는 store 전량을 색인하므로 옛 앵커가 색인에 남아 **앵커 df가 오히려 늘고**,
> `verify_code_quotes` 대상이 579→759로 늘어 audit이 31% 느려진다.

**선행 조건 3개** — 이걸 먼저 만들지 않으면 어떤 키·title 변경도 코퍼스를 악화시킨다.

1. **객체 퇴역 절차** (엔진) — 컨텍스트 재적재 시 옛 객체를 지우거나 퇴역 표기
2. **`code_anchors` 내 key 중복을 오류로** (엔진) — 지금은 마지막 것만 남고 무신호
3. **`lint.py`에 키·id 형식 검증** (엔진) — 지금 0건이라 위반 키 82개가 조용히 살아 있음

그리고 앵커 id는 골든셋(`eval_scenarios.json`)·stale-set 캐시(271개)·매핑·용어 참조에
흩어져 있어 키를 바꾸면 네 곳을 같은 커밋에서 갈아야 한다.

### 5.9 B의 title은 `symbol`로 간다 — 사람 문장으로 바꾸지 않는다

설계 3안은 전부 title을 **사람이 쓴 문장**으로 바꾸자고 했고, 판정단은 C안(대표 앵커 정책)을
골랐다. **그 방향을 채택하지 않는다.** 적대검증이 찾은 이유가 결정적이다.

> 지금 title은 못 읽지만 **항상 참**이다. 세 안 모두 그걸 사람 문장으로 바꾸는데,
> `verified_quote`는 어느 답 경로에도 실리지 않는다 — 즉 답을 받는 쪽이 라벨을 코드와
> 대조할 방법이 사라지고, 틀린 라벨이 검수 도장을 달고 나간다. **이미 같은 quote에
> 서로 다른 라벨 3개(2개는 거짓) 실물이 있다**(symbol 경로).

같은 교훈이 이 레포에 이미 있다 — 의미적 거짓은 schema·lint로 막을 수 없다(엔진 `2de5beb`).

**대안: `title` 폴백을 `quote[:120]`에서 `symbol`로 바꾼다.**

- `BubbleObjectDisturbPrickleVineChild::_doDisturbOnPop` — 사용자 불만("구분이 안 된다")을 해소한다
- `symbol`은 이미 존재하고 코드에서 파생됐다. **새 거짓을 만들지 않는다**
- **백필이 기계적으로 가능하다** — 2952개를 스크립트로. 사람 판단 0
- 노트 `title` passthrough는 넣되 **선택**으로, 값이 있으면 쓰고 없으면 `symbol` 폴백
- 색인 표면은 안 바뀌고 `content_hash`도 안 바뀐다 → **실모델 재색인 불필요**(실측 확인됨)

단 `_SET_ALLOWLIST`에 CodeLocator가 없어(`assembly.py:236-240`) `updates` 레인으로는 못 고친다.
백필 경로를 열거나 데이터 직접 수정이 필요하다.

**앵커 키는 이번에 바꾸지 않는다.** 재적재 선행 조건이 안 갖춰졌고, 심볼 파생 키는
kamehameha 180개에서 49%가 충돌하며(코퍼스 전체 1897/3886), title이 `symbol`이 되면
사용자 불만은 이미 해소된다. 키는 후속으로 남긴다.

### 5.10 설계 워크플로에서 건질 것

전제가 어긋난 부분(사람 라벨 전환, 재적재 가정)은 버리고 다음만 쓴다.

- **"안 넣기 게이트" 4유형** — 부모 기본값 오버라이드 / 비교 대상인 다른 기능 코드 /
  실제로 안 타는 경로·공용 유틸 / 주석·선언만. kamehameha 노이즈 77개가 여기 걸린다.
  이건 **적재 전 규칙**이라 재적재가 필요 없다
- **기계 선별 2단계** — G1: 기능 식별자가 quote·path에 등장(실측 87/168),
  G2: 심볼 마지막 식별자가 G1 통과 앵커 quote에 등장(28개). 나머지 53개만 사람이 본다
- **부재 근거를 매핑당 1개까지 앵커로 허용** — 부재는 코드가 바뀌면 조용히 거짓이 되므로
  산문보다 바이트 대조를 받는 쪽이 낫다
- **경고**: 매핑 `meaning`은 `_SET_ALLOWLIST`에 있어 `evidence_unchanged: true` 한 줄로
  근거 없이 고칠 수 있다. 앵커를 산문으로 흡수하는 설계는 근거를 검증 채널에서
  무검증 채널로 옮기는 것이다

---

## 6. 하지 않을 것

- **앵커 df 상한 조정·비례화** — 2026-07-06에 4개 안 전부 기각(거짓 양성 재도입 실측).
  상한 30이 302문서 시절 값이고 지금 모집단이 6369행이라는 사실은 기록해두되, 경로는 명부다
- **앵커 개수 줄이기로 게이트 열기** — 광선발사 앵커를 전량 지워도 df 53으로 여전히 막힌다
- **`line_start` 복원** — 2026-07-03 영구 보류 확정
- **앵커 `status`를 `candidate`로** — 2026-07-23 계획서·테스트로 못박은 의도된 설계
- **bb2 사본 직접 수정** — installer가 영구 skip 한다. 정본은 이 레포 템플릿

---

## 7. 열린 질문

1. ~~**왜 오늘 두 적재가 용어를 코드 심볼 위주로 만들었나.**~~ **답 나왔다.**
   골격이 심볼을 강제하는 게 아니라 **방치한다** — `extract_template.js`의 SCHEMAS에서 실제
   예시값이 채워진 곳은 `code_anchor` 하나뿐이고 전부 코드 모양이며, `term`은 빈 문자열이고
   `extractPrompt`는 TODO다. 그래서 같은 골격·같은 파이프라인인데 한국어 term 비율이
   **6%(item-usage) ~ 97%(main-map)**로 튄다. → T11이 이걸 닫는다
2. **`ingame-item-usage`의 근거가 코드 100%인 것이 의도인가.** `history_coverage=unsearched`
   선언은 됐지만 기획서·PR·Jira 근거 0개, DecisionRecord 0개다
3. **`item-standby-exit-return-and-freeze-watchdog` 앵커 19개** 재분할 여부
4. ~~**kamehameha 457개 미커밋분을 어떻게 할지**~~ **결정됐다(D2)** — 삭제 후 의미형 키로 재적재.
   백업은 `.snapshots/2026-07-27/ingest-backup/`(486파일, 6.1MB)
5. **T22의 범위를 어디까지 넓힐지** — 5.3의 "코드처럼 보이는 title" 정규식을 쓰면 대상이
   410건에서 2000건대로 늘어난다. 표본 200개 오판율을 재고 결정한다

---

## 부록: 현재 bb2 상태 (2026-07-27 리뷰 시점)

- 미커밋 485개 (그중 `petskill-kamehameha` 457개). `ingame-item-usage`는 `d1294e7032`로 커밋됨
- 색인 `documents` 7963행. 두 적재 모두 반영됨
- DomainContext 168개, CodeLocator 3886개, EvidenceRef 4214개, GlossaryTerm 1181개
- kamehameha 세션이 손으로 고친 `code.ingame-area-expansion.admin-row-adjustment--4.json`은
  `verified_quote`·`title` 둘 다 교체됐고 남은 차이는 맨 앞 탭 1글자 오프셋이다
  (`title`↔`quote` 일관성 검사는 엔진에 없다 — `lint.py`가 title을 읽지 않는다)
