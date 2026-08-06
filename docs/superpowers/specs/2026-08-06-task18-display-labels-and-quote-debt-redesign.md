# Task 18 표시 제목·인용문 부채 재설계

- **작성일**: 2026-08-06
- **상태**: 사용자 설계 승인 완료 — 구현 계획 검토 대기, binding·실코퍼스 변경 금지
- **선행 작업**: P0 ingest integrity foundation 완료
- **현재 입력**: Task 18 읽기 전용 재측정 receipt

---

## 1. 왜 새 문서가 필요한가

2026-08-04 Task 18 설계와 계획은 P0 이전의 엔진·BB2 HEAD, `origin/develop`, snapshot,
binding을 전제로 썼다. 그 뒤 신규 적재를 coverage·단일 mutation·receipt·foundation gate로
묶는 P0가 들어왔고, 기존 binding도 현재 migration에 쓸 수 없는 상태가 됐다.

따라서 옛 문서를 고쳐서 현재 문서처럼 보이게 하지 않는다. 다음 두 파일은 당시 판단과 시행착오를
보존하는 역사 자료다.

- `docs/superpowers/specs/2026-08-04-task18-display-labels-and-quote-backlog-design.md`
- `docs/superpowers/plans/2026-08-04-task18-display-labels-and-quote-backlog.md`

이 문서는 2026-08-06 재측정 결과와 현재 checkout의 코드 계약을 새 기준으로 삼는다. 옛 문서의
실행 순서, HEAD, snapshot, binding, 예상 지문, 커밋 묶음은 승계하지 않는다.

## 2. 현재 기준

### 2.1 정본 입력

| 항목 | 현재 값 |
|---|---|
| 재측정 receipt | `/Users/al03040455/Desktop/bb2_client/.snapshots/2026-08-06/task18-remeasurement/measurement.json` |
| receipt SHA-256 | `6de6a1d55e135974a0443e67bce323bae0d2183e0f9307cebdfaebc5faf7e589` |
| 측정 시각 | `2026-08-06T11:22:14+09:00` |
| 측정 방식 | `read_only_no_fetch` |
| 측정 당시 engine HEAD | `f054ba9c35039fb936c1ce849df1ddefa293abf6` |
| 측정 당시 BB2 HEAD | `fbcbc861f9a9b43c3ac483e43b8d706c9c4d2b01` |
| `refs/remotes/origin/develop` | `6607c458a635ab96ac31acf04c3474fa4ea7eeff` |
| 원격 `refs/heads/develop` 확인값 | `6607c458a635ab96ac31acf04c3474fa4ea7eeff` |
| P0 handoff SHA-256 | `55df01d2ed40aa8bee93ded3df378c3733bb00be30fbc8a8a9da21138590761b` |
| 옛 Task 18 binding | SHA-256 `a27aa26e238c5e0a1bf76fb48080b9b019873e0f08b93519cc86029cc6e56e5f`, `usable_for_current_migration=false` |

receipt는 canonical JSON이며, 대상 ID 배열의 정렬·유일성·자체 SHA-256을 검증했다. 측정 전후
engine·BB2 Git 상태와 corpus/index 지문도 같았고 `corpus_mutated=false`다.

측정 이후 생기는 설계·계획 커밋 때문에 HEAD는 달라질 수밖에 없다. 따라서 이 receipt는
**현재 상태를 설명하는 입력**이지 나중 migration을 허가하는 binding이 아니다. 실제 적용 직전에는
최종 HEAD와 모든 입력을 다시 묶은 새 binding이 필요하다.

### 2.2 실측 수치

| 항목 | 현재 값 |
|---|---:|
| 전체 객체 | 10,941 |
| CodeLocator | 3,809 |
| 표시 제목 변경 대상 | 3,305 |
| `verified_quote`가 없는 legacy CodeLocator | 3,307 |
| `verified_quote`가 있는 CodeLocator | 502 |
| quote 부채 중 stale | 396 |
| quote 부채 중 unmerged 또는 현재 기계 검증 불가 | 34 |
| quote 부채 중 줄 범위 잔존 | 592 |
| quote 부채 중 candidate | 252 |
| 비정본 symbol 전체 | 289 |
| 비정본 symbol 중 표시 제목 대상 | 279 |
| 비정본 symbol 중 quote 부채 | 285 |
| CodeLocator–EvidenceRef 짝 | 3,202 |
| 현재 제목이 같은 짝 | 2,720 |
| locator만 바꿀 때 새로 어긋나는 짝 | 2,704 |
| locator만 바꾼 뒤 어긋나는 짝 전체 | 3,186 |

2026-08-04 수치와 비교하면 핵심 모수 3,305/3,307/289는 같지만, quote 부채 중 stale은
371에서 396으로 늘었다. 예전 stale-set 캐시나 예전 binding 수치를 현재 기준으로 재사용하면 안 된다.

코퍼스 자체는 P0 handoff 뒤 바뀌지 않았다.

- mutation fingerprint: `0e9a2d52c387a8c51b73635bf60de690e20110f59a70135d3865a1e2a5926f7c`
- objects tree: `762117e941ba427333d7929cb06aa87a08d81f49bdeb8a049f5272b306e09372`
- raw tree: `1c5b0cdd2088a0b40d129c6974bf2477e42e7e9a7d3806e9bad25923ec208060`
- live/meta search fingerprint: `b6b3708f963dec1b382ef6cd7d03b8e7a4dfdb7b48b8510d3051e0daffa1734f`
- index DB SHA-256: `b5aa3b3d846752107f651a2393b4169fdf07a0db82c5f1d47ab1b0e535d381a4`

## 3. 목표와 범위

Task 18은 다음 세 가지를 하나의 닫힌 작업으로 끝낸다.

1. legacy CodeLocator의 표시 제목을 현재 파생 규칙에 맞춘다.
2. 짝 EvidenceRef의 표시 제목도 같은 규칙으로 맞춰 신규 ingest 결과와 legacy corpus가 다시
   같은 불변식을 갖게 한다.
3. 채울 수 없는 `verified_quote`를 억지로 만들지 않고, 현재 부채 3,307건을 재현 가능한 목록으로
   고정한다.

표시 제목 변경에 따라 `graph export`에서 같은 symbol을 가진 CodeLocator를 구분하기 어려워지는
문제도 표시층에서 함께 해결한다. 반면 검색·라우팅·색인 의미는 바꾸지 않는다.

## 4. 선택지와 결정안

### 안 1 — 옛 계획대로 CodeLocator만 변경

변경량은 가장 작지만 적용 뒤 3,202쌍 중 3,186쌍의 제목이 어긋난다. 현재 `build_code_evidence()`는
CodeLocator와 EvidenceRef를 같은 symbol 제목으로 만들기 때문에, legacy migration이 신규 ingest
불변식을 깨뜨린 채 끝나는 안이다. 채택하지 않는다.

### 안 2 — CodeLocator와 짝 EvidenceRef를 함께 동기화

CodeLocator 3,305개와 제목이 어긋날 짝 EvidenceRef 3,186개를 함께 변경한다. 총 예상 UPDATE는
6,491개다. 적용 후 측정된 3,202쌍은 모두 같은 canonical locator title을 갖고, 이미 맞는
EvidenceRef 16개는 no-op으로 남는다.

EvidenceRef의 실제 근거 내용은 `summary`에 남아 있다. 이번 변경은 `title`만 맞추며 summary,
manifest 연결, nested locator, 검수 상태, timestamp는 건드리지 않는다.

**이 안을 채택한다.** 2026-08-06 사용자 승인을 받았고, 후속 구현 계획을 별도 승인받기 전에는
Task 18 구현으로 진행하지 않는다.

### 안 3 — corpus는 그대로 두고 graph 표시만 변경

그림은 나아지지만 저장된 객체가 현재 ingest 불변식과 계속 어긋난다. query 외 소비자나 이후
migration이 legacy 예외를 계속 떠안아야 하므로 채택하지 않는다.

## 5. 표시 제목 migration 계약

### 5.1 canonical title

CodeLocator 제목은 현재 엔진의 `_canonical_locator_title()`과 같다.

- symbol이 비어 있지 않으면 `title = symbol`
- symbol이 비어 있으면 `basename(path):anchor_key`

현재 BB2에는 symbol이 빈 CodeLocator가 없지만 엔진의 합성 테스트는 폴백도 고정한다.

짝 EvidenceRef는 다음 조건을 만족하는 객체만 대상으로 삼는다.

- `kind == "EvidenceRef"`
- `ref_type == "code_locator"`
- `locator.code_locator_id`가 존재하는 CodeLocator를 정확히 가리킴

그 제목은 가리키는 CodeLocator의 canonical title과 같아야 한다. unpaired EvidenceRef와 다른
ref type은 건드리지 않는다.

### 5.2 planner와 MutationService의 책임

planner는 현재 store 전체를 읽어 다음 closure를 한 번에 만든다.

- canonical title과 다른 CodeLocator 전부
- 짝 CodeLocator의 canonical title과 다른 EvidenceRef 전부

MutationService는 `DISPLAY_MIGRATION`에 대해 다음을 fail-closed로 강제한다.

- 기존 CodeLocator/EvidenceRef의 UPDATE만 허용
- create/delete/rename/reference rewrite/auxiliary update 금지
- 각 객체에서 `title` 이외의 payload 변경 금지
- EvidenceRef의 새 title은 실제 짝 CodeLocator의 canonical title과 정확히 같아야 함
- planner가 대상 closure를 빠뜨리거나 불필요한 객체를 넣으면 거부
- 모든 precondition과 before corpus fingerprint 일치
- `created_at`, `updated_at`, `verified_at` 등 기존 시각 보존

현재 `DISPLAY_MIGRATION`의 PRESERVE timestamp 정책은 유지한다. 좌표나 quote를 바꾸지 않으므로
`commit_sha`, `symbol`, `verified_quote`를 새 값처럼 재검증하는 경로를 타지 않는다.

현재 migration API/CLI는 trusted snapshot만 받고 Task 18 final binding을 입력으로 받지 않는다.
후속 구현은 이 우회로를 닫아야 한다.

- `plan_display_migration`과 `apply_display_migration` 공개 seam 모두 exact final binding 절대경로와
  호출자가 기대한 binding SHA-256을 필수 인자로 받음
- CLI의 display plan/apply도 두 값을 필수 옵션으로 받고, 빠뜨리면 명령 실행 전 실패
- 두 seam 모두 독립 binding verifier가 현재 HEAD·status/content·remote·corpus/index/stale·snapshot을
  다시 계산해 `task18_allowed=true`를 확인한 뒤에만 snapshot 검증과 plan/apply로 진행
- plan manifest에 binding path/SHA를 넣고, apply가 받은 값과 manifest의 값이 다르면 실패
- snapshot만 넘기는 기존 호출 방식으로 Task 18 display migration을 실행하는 호환 우회 금지

즉 final binding은 운영 절차 문서가 아니라 plan과 apply 양쪽의 기계적 필수 입력이다.

### 5.3 예상 결과

현재 measurement가 그대로 최종 binding까지 유지된다는 전제의 예상값이다. 값이 달라지면
자동으로 맞춰 진행하지 않고 새 측정·설계 delta를 먼저 기록한다.

| 결과 | 기대 |
|---|---:|
| CodeLocator title UPDATE | 3,305 |
| EvidenceRef title UPDATE | 3,186 |
| 전체 UPDATE | 6,491 |
| create/delete/rename/auxiliary update | 0 |
| 전체 객체 수 | 10,941 |
| 적용 뒤 짝 제목 불일치 | 0 / 3,202 |
| title 외 변경 | 0 |

## 6. quote 부채 계약

### 6.1 의미

`verified_quote`가 없는 3,307개 legacy 객체는 **ingest 당시 검토됐지만 현재 저장 정보만으로
기계 재검증할 수 없는 객체**다. 이를 신규 객체 schema failure나 “검증된 적 없음”으로 바꾸지 않는다.
P0 이후 신규·좌표 변경 객체의 quote 필수 계약을 과거 객체에 소급해 거짓 상태를 만들지도 않는다.

Task 18에서는 quote를 채우지 않는다. 정확한 ID와 당시 맥락을 부채 목록으로 남겨 이후 사람이
근거를 다시 찾을 수 있게 한다.

### 6.2 산출물

부채 목록은 migration 전에 현재 store에서 결정론적으로 만든다. 최소한 다음을 담는다.

- 측정 receipt 경로와 SHA-256
- engine/BB2/target revision SHA
- 전체 quote 부채 ID 3,307개와 ID 목록 SHA-256
- locator id, context, path, symbol, status, locator source
- migration 전 CodeLocator title
- 짝 EvidenceRef가 있으면 그 id와 migration 전 title
- stale, unmerged 또는 검증 불가, line-range 잔존, candidate 축
- 비정본 symbol 여부와 사유
- 생성 입력의 corpus/index/stale 지문

stale 396, unmerged 또는 검증 불가 34, candidate 252는 우선순위 축이지 자동 quote 복원 규칙이
아니다. 비정본 symbol 289개도 별도 부채다. title migration과 동시에 symbol·commit·quote를
고치지 않는다.

생성기는 합성 fixture로 결정론과 부분집합 관계를 검증하고, BB2는 생성된 canonical JSON과
실코퍼스 check를 소유한다. canonical 부채 목록은 최종 binding보다 먼저 별도 path-limited
커밋한다. 그래야 migration 전 제목을 보존하면서도 최종 BB2 HEAD에 결속할 수 있다.

## 7. graph 표시 계약

저장된 title을 canonical symbol로 맞추면 같은 symbol을 공유하는 CodeLocator가 graph에서
구분되지 않을 수 있다. corpus title을 다시 설명문으로 쓰지 않고 표시층에서 해결한다.

- CodeLocator node label: `anchor_key · symbol의 끝마디`
- symbol이 없으면 `basename(path):anchor_key`
- CodeLocator tooltip: symbol과 path를 모두 표시
- EvidenceRef와 다른 kind: 기존 title 우선 규칙 유지
- details와 edge 정본: 변경 없음

같은 symbol·다른 anchor key인 두 CodeLocator의 label이 달라야 한다. 이 변경은 graph export의
표시만 바꾸며 객체 JSON이나 검색 색인을 건드리지 않는다.

## 8. 검색·색인 영향

색인은 다시 만들지 않는다.

- CodeLocator 검색 표면은 `path + symbol`이고 title을 쓰지 않는다.
- EvidenceRef는 검색 색인 대상에서 제외된다.
- linked CodeLocator 응답도 title을 싣지 않는다.

따라서 migration 전후 live search fingerprint가 meta fingerprint와 같아야 한다. 다르면 자동으로
rebuild하지 말고 예상 밖 입력 변경으로 실패한다. 이번 작업에 임베딩 계약이나 색인 입력 변경은 없다.

## 9. 실행 허가 사슬

실코퍼스 변경은 아래 순서를 모두 통과한 뒤에만 가능하다.

1. **현재 재측정 receipt** — 완료. 상태 설명만 하며 적용 권한은 없음.
2. **이 설계의 사용자 승인** — 2026-08-06 완료.
3. **새 구현 계획 커밋** — Task별 TDD·독립 리뷰·path-limited commit을 정확한 파일과 명령으로 고정.
4. **엔진 준비 구현** — paired display planner/service, graph 표시, 부채 생성·검증 경계. 실코퍼스 쓰기 금지.
5. **엔진 합성·runtime 전체 검증과 독립 리뷰** — 실패 0.
6. **부채 목록 생성·검증·BB2 커밋** — corpus 객체는 아직 변경하지 않음.
7. **`audit --no-fetch`와 BB2 실코퍼스 회귀** — 현재 remote SHA와 present quote 502개의 실제
   blob 검증을 포함. quote 없는 legacy 3,307개 전체를 검증했다고 확대 해석하지 않음.
8. **새 pre-mutation snapshot 생성·독립 검증** — 모든 engine/BB2 코드·문서·부채 커밋 뒤 생성.
9. **최종 Task 18 binding 생성·독립 검증** — 아래 §10의 현재 상태를 create-only로 결속.
10. **plan → 독립 manifest 검증 → apply** — binding 이후 HEAD·corpus·bound dirt가 바뀌면 중단.
11. **적용 후 검증과 최종 snapshot** — exact changed set, title-only, audit/eval/check/graph/index 신선도 확인.

최종 binding 전까지는 얼마든지 고쳐 커밋할 수 있다. **최종 binding 뒤에는 plan/apply가 쓰는
Git 상태 비영향 control artifact 외에 커밋이나 corpus write를 끼우지 않는다.** drift가 생기면
기존 binding을 고치지 않고 새 snapshot과 새 binding을 만든다.

## 10. 최종 binding 계약

binding은 기존 파일을 덮어쓰지 않는 canonical JSON이다. 생성기와 검증기는 독립 구현으로 두고,
검증기가 다음 항목을 현재 값과 다시 계산해 모두 같을 때만 `task18_allowed=true`로 판정한다.

- exact engine HEAD와 BB2 HEAD
- engine·BB2 `git status --porcelain=v1 -z` 바이트와 상태 SHA-256
- 모든 dirty path의 종류·내용·실행 비트·symlink 정보를 포함한 content manifest/hash
- BB2 cached path가 비어 있음
- 로컬 `refs/remotes/origin/develop`과 원격 `refs/heads/develop`의 exact SHA
- objects/raw/index/stale 파일 지문과 corpus mutation fingerprint
- P0 handoff path/SHA
- 2026-08-06 measurement path/SHA
- 승인된 설계와 구현 계획의 commit SHA·파일 SHA
- quote 부채 목록 path/SHA
- pre-mutation snapshot path·manifest SHA·검증 결과
- 예상 migration 대상 ID 목록과 before non-title hash
- binding 생성 시각, schema version, 목적, `task18_allowed`

검증기는 binding 파일 자체의 SHA-256이 호출자가 전달한 기대값과 같은지도 먼저 확인한다.
plan과 apply는 이 검증기를 각각 호출하며, 한쪽의 과거 PASS 결과나 plan manifest의 boolean을
다른 쪽이 신뢰해 재검증을 생략하지 않는다.

측정 당시 engine에는 사용자 추적 수정 2개와 미추적 파일 13개, BB2에는 기존 dirty 12개가 있었다.
이 파일들은 삭제·원복·묶음 커밋하지 않는다. 최종 binding 시점의 실제 목록과 내용으로 다시 묶고,
Task 18 소유 경로 외 staged entry가 하나라도 있으면 실패한다. 허용된 사용자 dirt라도 내용이 바뀌면
재결속 없이는 적용할 수 없다.

measurement·plan·manifest·binding 같은 control artifact는 corpus와 분리된 snapshot artifact
root에 만들고, 생성 때문에 bound Git 상태가 바뀌지 않게 한다. 부채 목록처럼 데이터 레포의 지속
기록으로 남길 파일은 **binding 전에** 커밋한다.

## 11. 적용과 복구

적용은 하나의 recoverable corpus transaction으로 처리한다. 6,491개를 루프에서 개별 저장하거나
부분 커밋하지 않는다.

적용 직전에는 살아 있는 store에서 plan을 다시 계산하고, 승인된 manifest bytes·precondition·
before fingerprint와 같아야 한다. 적용 도중 실패하면 transaction recovery가 before image로
복구하고, 실패 receipt를 남긴다. 성공 뒤에는 다음을 독립 검증한다.

- manifest의 대상 ID와 실제 Git 변경 ID가 정확히 같음
- 각 변경 객체에서 title을 뺀 canonical bytes/hash가 적용 전과 같음
- expected after corpus fingerprint 일치
- 객체 수·reference graph·lint 불변
- paired title mismatch 0
- quote backlog ID와 quote 유무 불변
- noncanonical symbol ID 불변
- live/meta search fingerprint 일치, index DB bytes 불변
- 사용자 dirty content hash 불변

검증이 끝난 뒤 BB2 corpus 변경과 지속 보고서만 정확한 pathspec으로 커밋한다. `git add -A`,
`git add .`, `git commit -a`는 쓰지 않는다.

## 12. TDD와 리뷰 수준

TDD는 핵심 경계에만 쓴다. 구현 세부 한 줄마다 테스트를 늘리지 않는다.

- RED가 필요한 경계: paired EvidenceRef 누락, 잘못된 짝 title, title 외 변경, closure 누락,
  timestamp 변동, stale binding, 같은 symbol graph label 충돌, 부채 목록 결정론
- GREEN 뒤 최소 범위 리팩터링
- Task별 구현자가 자기 diff와 focused test를 확인
- 다른 에이전트가 고정 candidate SHA를 대상으로 spec review와 code-quality review
- 리뷰 수정 뒤 같은 테스트와 전체 게이트 재실행
- 커밋은 Task 소유 path만 포함

문서나 단순 배선까지 억지 RED를 만들지는 않는다. 대신 결정론적 검증 명령과 실제 출력으로
완료를 증명한다.

## 13. 완료 조건

다음이 모두 참일 때만 Task 18을 완료로 옮긴다.

- 사용자가 이 설계와 후속 구현 계획을 각각 승인함
- 새 final binding의 독립 검증이 PASS이고 `task18_allowed=true`
- 예상 6,491 UPDATE와 실제 변경 집합이 일치함. 수치가 바뀌었다면 승인된 delta 문서가 있음
- 3,202 paired title mismatch가 0
- title 외 payload와 lifecycle timestamp 변경이 0
- quote 부채 3,307개와 비정본 symbol 289개가 정확한 목록으로 남고 corpus 값은 바뀌지 않음
- index rebuild 없이 live/meta fingerprint가 일치하고 index DB bytes가 같음
- 엔진 pytest·설치 runtime unittest, BB2 checks·eval·audit가 모두 통과함
- 사용자 기존 dirty가 내용까지 보존됨
- final snapshot verify가 PASS함
- engine과 BB2 커밋이 모두 path-limited이며 unrelated staged path가 0

## 14. 이번에 하지 않는 것

- quote 3,307개 백필
- 비정본 symbol 289개 교정
- commit SHA·path·symbol·locator 좌표 변경
- unmerged/unverifiable 34개를 임의로 stale 또는 invalid로 재분류
- 검색 랭킹·라우터·임베딩·색인 schema 변경
- 옛 Task 18 문서나 binding 덮어쓰기
- 옛 계획의 Task 19 뒷정리·검색 회귀 항목을 검증 없이 끌어오기
- 사용자 기존 dirty 삭제·원복·포괄 stage

---

이 설계는 2026-08-06 승인됐다. 다음 gate는
[새 구현 계획](../plans/2026-08-06-task18-display-labels-and-quote-debt.md)의 사용자 승인이다.
그 전에는 Task 18 엔진 구현, final binding, 실코퍼스 migration을 시작하지 않는다.
