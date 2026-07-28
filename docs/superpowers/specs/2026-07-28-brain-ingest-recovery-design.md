# 브레인 적재 복구·재발 방지 최종 설계

> 상태: **최종 — 적대적 리뷰와 감독 게이트 반영 완료**
>
> 범위: Project Brain 엔진, 설치되는 ingest/query 스킬 계약, BB2 실코퍼스 복구
>
> 이 문서는 구현 계획이 아니다. 구현 순서와 파일 단위 작업은 이 설계를 입력으로 별도
> 계획에서 작성한다. 설계 완료만으로 엔진이나 BB2 데이터가 수정됐다고 보지 않는다.

## 1. 최종 결정

이번 문제는 하나의 적재 버그가 아니라 세 문제가 겹친 사고다.

1. **쓰기 계약 부재**: build, 직접 객체 입력, promote, mark-checked가 같은 검증·원자성
   경계를 공유하지 않는다.
2. **두 적재의 데이터 결함**: `petskill-kamehameha`와 `ingame-item-usage`에 검색 표면,
   anchor 연결, symbol, 시각 값 문제가 들어갔다.
3. **기존 코퍼스 부채**: 기존 부분 검사에서 잡힌 ID 형식 위반 116건, 전수 grammar
   검사에서 추가로 드러난 ReviewRecord 3건, quote 없는 CodeLocator 3,307개가 이미 있다.

따라서 다음 순서로 해결한다.

1. 별도 엔진 worktree에서 공통 mutation service와 검증 계약을 먼저 구현한다.
2. 전체 저장 단위를 snapshot으로 고정한다.
3. 광선발사를 staging에서 검증하고 journal transaction으로 교체한다.
4. 광선발사 기준점을 새로 만든 뒤 인게임을 같은 방식으로 교체한다.
5. 일반 ingest와 분리된 ID-only migration으로 남은 ID 위반을 없앤다.
6. CodeLocator title은 전 코퍼스에서 결정론적 display label로 정리한다.
7. quote 없는 나머지 legacy anchor는 전면 백필하지 않고 재검증 수요가 생길 때 보강한다.

**전체 코퍼스 재적재는 하지 않는다.** 기존 객체 수와 결과를 새 결과에 억지로 맞추지도
않는다. 모든 차이는 manifest의 create/update/delete/rename으로 설명한다.

## 2. 제품 경계

### 2.1 누가 brain 객체를 소비하는가

brain 객체의 주 소비자는 사람보다 에이전트다. 사용자는 저장된 JSON을 직접 읽는 대신
에이전트에게 query로 질문하고, 에이전트가 회상 결과와 근거를 해석해 답한다.

사람이 `graph export`, `show`, 원본 파일로 상태를 볼 수는 있지만 이는 점검·탐색용 보조
수단이다. 그래프나 객체 파일을 사람이 직접 읽는 흐름을 메인 사용자 경험으로 두지 않는다.

이 경계에서 중요한 것은 다음 두 가지다.

- 에이전트가 의미와 근거 위치를 혼동하지 않는가
- 답변에 쓸 수 없는 근거를 그럴듯한 설명으로 소비하지 않는가

### 2.2 의미와 근거의 소유권

`CodeLocator`는 `truth_role=reference`인 위치 정보다. 도메인 의미를 소유하지 않는다.

- 검수된 의미, 역할, 경계: `DomainMapping.meaning`, `canonical_summary`
- 정확한 코드 위치: `CodeLocator.id`, `repo`, `path`, `symbol`, `commit_sha`
- 저장 시점의 코드 인용: `CodeLocator.verified_quote`
- 원본·공개 상태 연결: 역방향 `EvidenceRef` → `EvidenceManifest`

에이전트는 DomainMapping에서 “무슨 뜻인가”를 얻고, 연결된 CodeLocator에서 “어디서
확인하는가”를 얻는다.

## 3. 검증된 현재 기준선

다음 값은 2026-07-28 읽기 전용 실측 기준선이다. 구현 시작 시 같은 명령으로 다시
측정하고 달라졌으면 새 기준선을 기록해야 한다.

| 항목 | 현재 값 |
|---|---:|
| BB2 저장 객체 | 11,097 |
| CodeLocator | 3,886 |
| EvidenceRef | 4,214 |
| EvidenceManifest | 288 |
| ReviewRecord | 217 |
| ContextProjection | 1 |
| quote 보유 CodeLocator | 579 |
| quote 누락 CodeLocator | 3,307 |
| 기존 부분 grammar의 ID 형식 위반 | 116 |
| 19종 전수 grammar의 ID 형식 위반 후보 | 119 |
| 119개 위반 ID의 객체 참조 | 65파일, 187회 |
| 위반 ID가 든 eval 기대값 | 3 |
| stale-set의 위반 ID | 27 |

추가로 확인된 사실:

- CodeLocator 3,886개의 정방향 `evidence_refs`는 모두 비어 있다.
- 3,279개 locator에는 `EvidenceRef.locator.code_locator_id` 역참조가 있고, 607개에는
  없다. 역참조 없는 607개는 모두 quote도 없다.
- quote가 있는 579개에는 각각 한 개의 역방향 EvidenceRef가 있다.
- 기존 부분 검사의 ID 위반은 CodeLocator 82, EvidenceRef 19, DomainMapping 4,
  GlossaryTerm 11이다.
- §5의 19종 grammar를 전수 적용하면 ReviewRecord 3개가 더 검출돼 후보 합계가 119가
  된다. 세 ID는 `review.disturb-hedgehog.cloud-fix`,
  `review.disturb-boostedbomb.depth-config`,
  `review.mapping.stage-clear-token.continue-button-visibility-20260611`이다.
- 기존 116개 때문에 영향받는 ReviewRecord는 9개이고, 그중 single-object review 8개는
  ReviewRecord 자신의 ID도 함께 바뀌어야 한다. 추가 3개도 canonical target/bundle
  identity로 rename해야 하므로 ReviewRecord ID rename 후보는 합계 11개다.
- 119개는 객체 필드에서 187회 참조되고, eval의 3회를 포함한 전체 JSON 참조는
  66파일 190회다.
- 현재 ContextProjection은
  `projection.sally-canoe.result-popup-rank.reuse` 한 개다.
- `petskill-kamehameha`는 456개, `ingame-item-usage`는 945개 객체다.
- 두 백업 입력은 총 573개 anchor에 동일한 자정
  `2026-07-27T00:00:00+09:00`을 넣는다. 실제 검증 시각으로 쓸 수 없다.
- 백업 symbol 중 괄호가 붙은 값은 광선발사 66개, 인게임 3개다. 한글 설명이 섞인 값은
  각각 128개와 4개다. 두 집합은 겹칠 수 있으므로 정규화 대상의 정확한 합집합 수는
  staging report에서 다시 계산한다.
- 현재 CodeLocator 3,886개는 모두 symbol을 갖고 있고, title과 symbol이 다른 객체는
  3,879개다.
- 대표 query의 현재 `anchor_df`는 스테이지 클리어 토큰 34, 망치 31, 광선 발사 57,
  인게임 아이템 사용 209다.
- DB 없는 폴백의 CodeLocator compact JSON은 약 383KB이고, 현재 보유 quote 전체는 약
  75.9KB다.

이 숫자는 완료 목표가 아니라 비교 기준이다. 복구 후 개수가 달라지면 manifest로 이유를
증명한다.

## 4. 정본 객체 계약

### 4.1 CodeLocator title

저장 객체의 `title`은 BASE schema상 필수지만 의미 필드는 아니다.

1. 새 CodeLocator의 title은 엔진이 결정론적으로 만든 display label이다.
2. 기본값은 canonical `symbol`이다.
3. symbol이 없는 legacy locator만 `basename(path):anchor-key` 형식을 쓴다. 새 locator는
   symbol이 없으면 원칙적으로 거부한다.
4. note, LLM, 설치 스킬이 준 CodeLocator title은 무시한다.
5. title을 검색 랭킹, 의미 판정, 답변 주장 근거로 쓰지 않는다.
6. linked 검색 결과의 정본 필드는 `object_id`, `path`, `symbol`이다.
7. `show`와 graph가 title을 표시할 때는 `display_only=true` 계약이다.

같은 path와 symbol을 가리키는 anchor가 여러 개면 object ID와 검증된 quote hash로
구별한다. 이를 해결하려고 CodeLocator에 의미 설명을 넣지 않는다.

전 코퍼스의 기존 title 정리는 코드 재조사가 아니라 별도 결정론적 display migration으로
한다. `title=symbol` 외 필드가 바뀌면 그 항목은 이 migration에서 거부한다.

### 4.2 symbol

새 symbol은 괄호 설명이나 번역을 붙인 표시 문자열이 아니라 실제 코드 식별자다.

- 언어 adapter가 지원되는 파일은 parser가 quote 안의 symbol 선언·참조 경계를 확인한다.
- 단순 substring 일치만으로 symbol 검증을 통과시키지 않는다.
- parser가 지원하지 않거나 하나로 확정하지 못하면 mutation manifest에
  `manual_symbol_verification`을 남긴다. 여기에는 reviewer, repo, commit, path, symbol,
  quote hash, 판정 근거가 필수다.
- 이 기계 검증이나 구조화된 수동 증거가 없으면 새 locator를 저장하지 않는다.
- legacy symbol을 무조건 괄호 앞에서 자르지 않는다. old→new 대응표를 만들고 실제
  blob과 quote를 대조한다.

두 사고 컨텍스트의 괄호 symbol 69개와 한글 혼합 symbol의 합집합은 staging에서 전수
분류한다. overload나 소속 정보가 사라지는 자동 치환은 금지한다.

### 4.3 quote 무결성

새 CodeLocator와 근거 좌표를 바꾸는 CodeLocator는 비어 있지 않은 `verified_quote`가
필수다.

검증기는 절대 `repo_root`의 Git object database에서 `commit_sha:path` blob을 읽고,
quote의 정확한 UTF-8 substring 일치와 §4.2 symbol 관계를 함께 확인한다. 성공 직후
엔진 시계로 `verified_at`을 만들고 검증 결과와 한 객체로 mutation service에 전달한다.

- notes, domain spec, 외부 JSON의 `verified_at`은 신규·재검증 쓰기에서 무시한다.
- quote 전체나 앞부분을 title로 복사하지 않는다.
- line number는 근거 정체성이 아니다.
- quote 없는 legacy 객체를 읽는 것은 허용하지만, 확인한 것처럼 표시하지 않는다.
- ID와 ID에서 파생된 참조만 바꾸는 ID-only migration은 legacy `verified_at`과 quote
  누락을 그대로 보존할 수 있는 유일한 예외다.

### 4.4 quote 공개

저장 무결성과 사용자별 공개 권한은 다른 문제다.

CodeLocator에서 EvidenceRef는 역방향으로 찾는다.

```text
CodeLocator.id
  <- EvidenceRef.locator.code_locator_id
  -> EvidenceRef.evidence_manifest_id
  -> EvidenceManifest
```

quote 공개 판정은 다음 두 축과 최종 3상태를 사용한다.

| 축 | 상태 |
|---|---|
| redaction | `allow` / `deny` / `indeterminate` |
| principal ACL | `allow` / `deny` / `indeterminate` |
| 최종 quote_access | `allow` / `deny` / `indeterminate` |

- 연결된 모든 manifest가 `redaction_status=approved`이고 principal 기반 ACL도 허용을
  증명했을 때만 최종 `allow`다.
- 명시적 차단이 하나라도 있으면 `deny`다.
- 역참조·manifest·principal·판정기 중 하나라도 없거나 실패하면 `indeterminate`다.
- `allow`가 아니면 어떤 query/search 경로에서도 quote를 빼고 상태만 표시한다.

현재 엔진에는 principal, team membership, ACL evaluator가 없다. 따라서 신원 모델이
별도 설계로 도입되기 전 제품 기본값은 **항상 quote 생략**이다.
`redaction_status=approved`를 사용자 권한 허용으로 해석하지 않는다.

### 4.5 quote와 stale의 차이

quote 없는 기존 anchor도 `commit_sha + path`가 있으면 저장 커밋 이후 해당 파일이
바뀌었는지 검사할 수 있다. 그러나 anchor 원문 자체가 정확했는지, 현재 어느 코드 조각과
대응하는지는 증명할 수 없다.

따라서 audit은 한 성공값으로 뭉개지 않고 다음을 분리한다.

| 항목 | 상태 예 |
|---|---|
| `stale` | unchanged / changed / commit_missing / path_missing / error |
| `code_quote` | verified / mismatch / missing / unverifiable / error |
| `symbol_relation` | verified / manual_verified / mismatch / unsupported |
| `quote_access` | allow / deny / indeterminate |
| `id_format` | valid / invalid / unknown_grammar |
| `references` | intact / dangling |

quote가 없다고 stale 검사를 건너뛰지 않는다. SHA/path 검사는 바뀐 파일을 잡지만 quote
검증을 대신하지 않는다.

## 5. ID 문법

### 5.1 공통 원자

```text
slug       := [a-z0-9]+(?:-[a-z0-9]+)*
anchor-key := slug(?:--[0-9]+)?
decimal    := 0|[1-9][0-9]*
```

`--N`은 동일 논리 이름에서 여러 코드 anchor를 구별하는 정식 규약이다. 오염으로 보지
않는다. Jira의 원형 `LGBBTWO-234`는 locator에 보존하고 내부 key만
`jira-lgbbtwo-234`처럼 소문자로 정규화한다.

### 5.2 19종 parser/formatter registry

현재 `schema.VALID_KINDS`는 20종이 아니라 **19종**이다. 다음 표가 ID parser와 formatter의
단일 정본이다.

| Kind | 정식 형식 |
|---|---|
| EvidenceManifest | `manifest.<ctx>.<key>` |
| EvidenceRef | `evref.<ctx>.<anchor-key>` |
| ReviewRecord | single: `review.<target-object-id>` / bundle: `review.bundle.<ctx>.<key>` |
| EventLedgerRecord | `ledger.<ctx>.<key>` |
| TemporalFact | `fact.<ctx>.<key>` |
| CodeLocator | `code.<ctx>.<anchor-key>` |
| DomainContext | `context.<ctx>` |
| GlossaryTerm | `g.<ctx>.<key>` |
| ContextProjection | context: `projection.<ctx>.context-md` / reuse: `projection.<ctx>.<requirement-key>.reuse` |
| CurrentView | `view.<view-type>.<key>` |
| KnowledgePage | `page.<category>.<key>` |
| IndexRecord | `index.<index-name>.<source-id-digest>` |
| SpecDocument | `spec.<document-key>` |
| SpecRevision | `revision.<document-key>.<revision-key>` |
| SlideRef | `slide.<document-key>.<revision-key>.<decimal>` |
| SlackThread | `slack.<ctx>.<key>` |
| DecisionRecord | `decision.<ctx>.<key>` |
| DomainMapping | `mapping.<ctx>.<key>` |
| Insight | `insight.<ctx>.<key>` |

표의 `<ctx>`, `<key>`, `<requirement-key>`, `<view-type>`, `<category>`, `<index-name>`,
`<document-key>`, `<revision-key>`는 `slug`다. enum 필드에 underscore가 있으면 formatter는
ID에서 hyphen으로 바꾸고 parser가 원래 enum과의 합치 여부를 검사한다.
`source-id-digest`는 canonical `source_object_id`의 SHA-256 앞 16자리 소문자 hex다.

추가 불변조건:

- single ReviewRecord는 `review.` 뒤 전체를 registry로 다시 parse하고
  `target_object_id`와 정확히 같아야 한다.
- bundle ReviewRecord는 `bundle_key=bundle.<ctx>.<key>` 및 대상 bundle과 일치해야 한다.
- ContextProjection variant는 `format`과 ID suffix가 일치해야 한다.
- SpecRevision과 SlideRef의 ID 조각은 참조 대상의 parsed key와 일치해야 한다.
- IndexRecord의 index-name과 digest는 객체 필드에서 다시 계산한 값과 일치해야 한다.
- 단순 점 조각 수나 첫 prefix만으로 유효성을 판정하지 않는다.

시작 시 `VALID_KINDS == ID_GRAMMARS.keys()`를 강제한다. kind를 추가하면서 grammar를
등록하지 않거나 알 수 없는 prefix가 들어오면 schema, audit, 모든 write가 warning이
아니라 error로 실패한다.

설치 스킬의 `code_evref_keys`는 일반 logical key가 아니라 `anchor-key`를 받는다고
object-model 한 곳에서 명확히 선언한다.

## 6. 공통 mutation service

### 6.1 유일한 제품 쓰기 경계

`BrainStore.save_object()`를 제품 코드가 직접 호출하지 않는다. 상위에 하나의
`MutationService`를 두고 다음 네 경로를 모두 통과시킨다.

- ingest
- promote
- promote-auto
- mark-checked

projection 생성, ID migration, context replace 같은 이후 쓰기 기능도 같은 service의 명시적
operation으로만 추가한다.

### 6.2 경로 입력

모든 코드 근거 mutation은 다음 값을 명시적으로 받는다.

```text
brain_root: absolute path
repo_root: absolute Git worktree path
expected_repo_id: configured canonical repository identity
expected_revision_ref: verification target ref
engine_sha: exact Project Brain engine commit
```

cwd, staging 디렉터리, `.git` symlink로 repo를 추론하지 않는다. 가장 깊은 quote/write
gate까지 `repo_root`를 전달한다.

다음 오류는 서로 구분하고 모두 쓰기 전에 실패한다.

```text
not_git_repo
repo_identity_mismatch
commit_missing
shallow_or_unfetched
commit_not_reachable
path_missing_at_commit
blob_read_failed
quote_not_found
symbol_mismatch
symbol_verification_missing
```

### 6.3 검증 순서

원본 입력 sequence를 보존한 채 다음 순서로 fail-closed한다.

1. sequence에서 완성 object ID 중복 검사
2. 입력 logical key와 source ID 중복 검사
3. schema와 enum
4. §5 ID parse와 필드 합치
5. 허용된 상태 전이
6. repo identity, commit, reachability, blob
7. quote와 symbol 관계
8. 기존 객체 precondition과 before hash
9. 입력과 기존 store를 합친 상태의 모든 참조
10. merged lint
11. transaction prepare
12. atomic commit
13. post-commit fingerprint와 기대 결과

dict로 접기 전에 1번을 수행한다. 같은 ID의 마지막 객체가 앞 객체를 조용히 덮는 동작은
허용하지 않는다.

`--no-quote-verify`, `--allow-unverifiable` 같은 일반 우회 플래그는 만들지 않는다.
legacy 예외는 §7의 ID-only migration으로만 표현한다.

### 6.4 journaled transaction

brain root에 single-writer lock을 잡은 뒤 하나의 transaction ID로 다음을 수행한다.

1. 고정 manifest에 create/update/delete/rename, before/after hash, 참조 rewrite,
   expected corpus/index fingerprint를 기록한다.
2. 모든 새 파일을 대상과 같은 filesystem의 transaction 임시 영역에 쓰고 file fsync한다.
3. before image와 journal을 저장하고 directory fsync 후 상태를 `prepared`로 바꾼다.
4. 상태를 `committing`으로 바꾸고, 기존 파일은 before 영역으로 atomic rename한 뒤 새
   파일을 atomic replace한다. 각 적용 항목을 journal에 기록하고 fsync한다.
5. 파생 index와 stale-set action을 적용하고 post-commit gate를 실행한다.
6. 모두 맞으면 `committed`로 종료한다.

프로세스가 `prepared` 또는 `committing`에서 죽으면 다음 실행은 새 쓰기를 받지 않고
before image로 자동 rollback한다. 자동 roll-forward는 하지 않는다. rollback 뒤 이전
fingerprint가 맞아야 lock을 해제한다. 복구가 끝나지 않으면 수동 개입이 필요한
`recovery_required` 상태로 남긴다.

단일 객체 쓰기도 같은 transaction의 크기 1인 경우다.

### 6.5 mark-checked

mark-checked는 시각과 commit만 바꾸는 편의 명령이 아니다.

1. 대상 commit의 blob에서 기존 quote를 다시 검증한다.
2. symbol 관계도 다시 검증한다.
3. 성공한 locator만 `commit_sha`와 엔진이 찍은 `verified_at`을 함께 갱신한다.
4. quote 없는 legacy locator는 `refused_unverifiable`로 거부한다.
5. 일부만 성공한 bundle은 저장하지 않는다.

quote 없는 legacy anchor는 stale 변화는 탐지할 수 있지만 mark-checked로 “확인됨” 상태를
만들 수 없다. 다시 확인하려면 quote를 보강해야 한다.

## 7. ID-only migration

ID 형식 위반 후보 119건은 일반 ingest나 context replace와 분리한다. 이전 보고서의
116건은 ReviewRecord 문법을 검사하지 않은 부분 집계였으므로 최종 migration 입력으로
그대로 고정하지 않는다.

migration manifest의 각 행은 다음을 갖는다.

```text
old_id
new_id
kind
canonical_payload_hash
reference_rewrites[]
dependent_artifacts[]
snapshot_id
```

`canonical_payload_hash`는 ID를 제거하고, registry가 선언한 참조 필드의 old ID를 canonical
token으로 치환한 JSON을 안정적으로 직렬화해 계산한다. old/new 객체가 ID와 그 ID에서
파생된 참조 외에는 완전히 같을 때만 통과한다.

이 operation의 규칙:

- one-to-one rename만 허용한다. merge, split, 의미 수정은 거부한다.
- quote, path, symbol, commit, verified_at, status를 바꾸지 않는다.
- quote 없는 CodeLocator 82개도 위 조건을 만족하면 rename할 수 있다.
- `(repo,path,commit_sha)`는 anchor 고유 키가 아니므로 동일성 증거로 쓰지 않는다.
- 119개 old→new 후보와 객체 참조 187회를 전수 manifest에 고정한다.
- 기존 위반 target 때문에 파생되는 single-object ReviewRecord 8개와, 전수 grammar에서
  추가로 잡힌 ReviewRecord 3개를 합쳐 ReviewRecord ID rename 후보 11개를 함께 다룬다.
- 영향받는 ReviewRecord, eval 기대 ID 3개, Insight 등 모든 source/reference 필드를
  dry-run report에 포함한다. eval까지 포함한 기대 참조 기준선은 66파일 190회다.
- stale-set의 27개 ID와 index document ID는 문자열 치환하지 않는다. migration 뒤
  invalidation하고 재생성한다.
- ContextProjection과 기타 파생물은 source ID가 바뀌면 stale로 만들고 재생성한다.

광선발사 replace로 대문자 Jira 3건이 사라지면 manifest에
`resolved_by_context_replace`로 남긴다. 이 경우 현재 기준 예상 잔여 후보는 116건이지만,
live migration 입력은 context replace 뒤 19종 grammar로 다시 측정한 값만 사용한다.
최종 audit의 ID 위반은 0이어야 한다.

## 8. snapshot과 staging

### 8.1 snapshot 단위

대량 작업 전 하나의 snapshot ID로 다음을 함께 고정한다.

- `BrainStore._KIND_DIR`가 가리키는 모든 저장 디렉터리
- `raw/manifests`
- mutation 대상이 아닌 `raw/sources`의 read-only 파일 hash inventory
- `.brain-local/index.db`와 존재하는 SQLite sidecar
- `.brain-local/stale-set.json`
- `eval_scenarios.json`
- project config
- 파일별 SHA-256 manifest
- kind별 수, 전체 object ID, corpus fingerprint, index fingerprint
- BB2 repo SHA, engine SHA, 설치 managed-file hash

snapshot 중 writer가 생기거나 시작 전 fingerprint가 바뀌면 중단한다.

rollback은 snapshot 묶음을 먼저 복원하고 corpus, search, stale fingerprint를 비교한다.
일치하지 않을 때만 index를 rebuild한다. 임의 rebuild가 snapshot의 정상 index를 덮지
않게 한다.

### 8.2 staging

staging brain은 임시 Git repo가 아니라 실제 brain의 검증용 복제본이다. quote 검증은
항상 별도로 받은 실제 BB2 `repo_root`에서 수행한다.

각 context staging은 다음을 고정한다.

- 입력 백업과 hash
- 기존 대상 object ID와 외부 역참조
- old/new symbol 대응표
- create/update/delete/rename과 before/after hash
- 기존 15개 eval의 시나리오별 기준선
- 대상 query와 무관 회귀 query의 exact expected result
- expected repo, target commit, engine SHA

staging에서 통과한 manifest byte hash와 live에 적용하는 manifest byte hash가 같아야 한다.

### 8.3 공통 staging gate

- build, ingest, finalize 성공
- 새·재검증 CodeLocator quote 전수 통과
- symbol parser 또는 manual verification 전수 통과
- 신규 ID 위반 0, unknown grammar 0
- 끊긴 참조 0
- transaction failure injection에서 원상복구
- 예상 객체 전수 회수
- 기존 15개 eval 시나리오별 기준선 유지
- 대상 신규 query 통과
- 두 무관 회귀 query가 기준선보다 나빠지지 않음
- gate 차단, 순위 밀림, 결과 없음이 서로 다른 진단으로 남음
- 두 번째 finalize가 아무 변경도 만들지 않음

## 9. 두 사고 컨텍스트 복구

### 9.1 순서

두 context를 한 transaction에 넣지 않는다.

1. `petskill-kamehameha`
2. 광선발사 live 검증과 새 snapshot
3. `ingame-item-usage`
4. 인게임 live 검증과 새 snapshot

앞 단계 live gate를 통과하기 전에는 다음 단계로 가지 않는다.

### 9.2 광선발사

보존된 verify 결과와 domain spec을 재사용하되 현재 엔진 계약으로 다시 조립·검증한다.
의미를 처음부터 재조사하지는 않지만, quote·symbol·연결이 확정되지 않는 항목만 실제
코드를 다시 연다.

exact expected delta:

- DROP 77
- MOVE `shot-bubble-sprite--6 → shoot-action` 1
- Jira 내부 logical key 3개 소문자화, locator 원형 유지
- `광선 발사`와 `KAMEHAMEHA`를 독립된 term/synonym/alias 표면으로 연결
- 자정 verified_at 폐기, 엔진 검증 성공 시각 사용
- old→new symbol 대응표 전수 확정

`--N` anchor ID를 유지한다. 의미형 anchor ID 103개를 새로 손 작명하지 않는다.
대표 query는 올바른 DomainMapping과 `object_id/path/symbol` 근거를 반환해야 한다.

### 9.3 인게임

먼저 보존 입력의 재조립 결과와 기존 945개를 비교한다.

- 계약 변경으로 설명되는 차이와 예상하지 못한 차이를 분리한다.
- 예상하지 못한 의미·연결 차이가 하나라도 있으면 live 교체를 중단한다.
- 393개 CodeLocator quote와 symbol 관계를 다시 확인한다.
- `인게임 아이템 사용`과 근거 있는 실제 사용자 표현을 term/synonyms/aliases로 연결한다.
- 정당한 분산 code anchor를 수를 줄이기 위해 삭제하지 않는다.
- mapping 분할은 실제 의미 경계가 둘 이상임을 DomainMapping으로 검수할 때만 한다.
- 자정 verified_at을 재사용하지 않는다.

### 9.4 무관 회귀

다음 두 query를 staging과 live 모두의 exact regression으로 추가한다.

- `오리지널 스테이지 클리어 토큰`
- `버디스킬 망치 발동 모션 개선 5.5`

복구 전 expected object IDs, `needs_clarification`, top-k를 저장하고 더 나빠지면 교체하지
않는다. 이 회귀를 고치기 위해 synonyms를 자동 추가하지 않는다. 어휘 변경이 필요하면
실패 원인과 도메인 근거를 가진 별도 승인 변경으로 다룬다.

## 10. legacy 정리

### 10.1 CodeLocator display migration

두 context 복구와 ID migration이 끝난 뒤 새 기준선에서 대상 수를 다시 잰다.

- 기존 symbol이 canonical로 판정된 locator: `title=symbol`
- symbol이 비어 있는 legacy locator: path 기반 결정론 label
- symbol 자체가 비정상인 locator: title만 덮어 문제를 숨기지 않고 별도 symbol 정규화
  대상으로 남김

이 migration은 의미나 근거를 바꾸지 않는다. title 외 payload가 달라지면 거부하고,
검색 index를 재생성한다.

### 10.2 quote 없는 3,307개

전면 백필하지 않는다. 전수 백필은 각 historical commit의 blob을 열고 정확한 symbol
관계를 확인해야 하므로 단순 복사 작업이 아니다.

우선순위:

1. 이번에 복구하는 두 context
2. stale로 판정돼 mark-checked가 필요한 context
3. 자주 조회되는 핵심 context
4. quote 보유율이 낮고 코드 의존성이 높은 context

첫 문자열 일치나 LLM 추측으로 quote를 채우지 않는다. quote가 없는 동안 stale 검사는
계속하되 `code_quote=missing`, `mark-checked=refused_unverifiable`로 정직하게 남긴다.

## 11. query와 fallback

정상 recall 결과에서도 CodeLocator details는 연결된 top-N에만 붙인다.

```text
object_id, path, symbol, quote_access
```

신원 모델이 생긴 뒤 `quote_access=allow`일 때만 quote를 추가할 수 있다. title은
display-only이고 의미 근거로 전달하지 않는다.

DB가 없거나 stale한 폴백은 전체 CodeLocator details를 내보내지 않는다. object kind별
집계와 최소 object ID만 반환하고 `details_omitted_reason=no_db|stale_db`를 표시한다.
폴백이 접근 제한이나 top-N 제한을 우회할 수 없다.

GlossaryTerm의 `term`, `synonyms`, `aliases`는 실제 사용자 표현을 registry gate에
연결한다. 세 글자 미만, 단독 일반명사, 근거 없는 표현은 넣지 않는다. 검색 DF 상한을
이번 복구에 맞춰 임의로 올리지 않는다.

## 12. 엔진·스킬·설치 경계

### 12.1 엔진 개발

- 현재 전역 편집 설치와 분리된 Project Brain worktree에서 구현한다.
- 명령은 그 worktree의 `.venv/bin/python`과 `PYTHONPATH=<worktree>/src`를 명시한다.
- BB2 live 교체 창에는 한 engine SHA와 한 writer만 허용한다.
- 전역 편집 설치 갱신은 엔진 테스트를 통과한 뒤 별도 배포 단계에서만 한다.

### 12.2 설치 스킬

원본은 이 repo의 `src/project_brain/templates/ingest/`와 query template이다. BB2의
`.agents/skills` 또는 `.claude/skills` 사본을 직접 수정하지 않는다.

스킬 계약에는 다음을 반영한다.

- `code_evref_keys`는 `anchor-key`
- CodeLocator title은 입력하지 않음
- quote와 symbol의 구조화 검증 결과
- 외부 verified_at 무시
- `needs_user`를 완료로 덮지 않음
- engine SHA, repo root, expected repo를 batch report에 기록
- 일반 quote 우회 플래그 금지

BB2 `brain/install.sh`는 의도적으로 `project-brain install`을 호출하지 않으므로 수동
설치 단계가 필요하다.

1. 첫 설치 report에서 `skipped=[]`
2. 관리 파일과 렌더 template hash 일치
3. 두 번째 설치에서 `created/updated/removed/adopted/skipped` 전부 빈 배열
4. 프로젝트 고유 overlay 무변경

## 13. 완료 게이트

### 13.1 엔진

- 새 계약의 RED 테스트를 먼저 작성
- 전체 pytest와 ingest template unittest 통과
- 19종 ID registry coverage와 unknown grammar fail-closed
- ReviewRecord 두 variant와 ContextProjection 두 variant
- dict fold 전 duplicate full ID 거부
- 네 제품 write 경로가 공통 mutation service를 지남
- repo/commit/shallow/path/blob/quote/symbol 오류 분리
- verified_at 엔진 stamping
- mark-checked no-quote 거부
- transaction 중간 실패 주입과 자동 rollback
- no-DB/stale-DB fallback details·quote 미노출
- quote access 3상태 테스트

### 13.2 ID migration

- context replace 전 후보 119개 old/new 전수 대응
- 객체 필드 65파일 187회와 eval 포함 66파일 190회 참조 대응
- 기존 영향 ReviewRecord 9개와 ReviewRecord identity rename 후보 11개 대응
- eval 3개 대응
- stale-set 27개 invalidation
- canonical payload hash 동치
- dry-run과 live manifest hash 일치
- 완료 후 ID 위반 0, dangling 0

### 13.3 BB2 실코퍼스

- `brain/checks` 통과
- 기존 eval 15/15를 시나리오별로 유지
- 두 무관 회귀와 두 대상 신규 query 통과
- 광선발사 DROP 77, exact MOVE 1
- 두 context quote·symbol 전수 검증
- verified_at이 실제 엔진 검증 사건에서 생성됨
- expected delta와 실제 create/update/delete/rename 일치
- snapshot hash와 rollback 후 corpus/index/stale fingerprint 동치
- context별 두 번째 finalize 무변경
- installer 1회 report와 2회 완전 멱등 report

전체 명령 exit code 0만으로 완료하지 않는다. 구조화된 대상 목록, 시나리오별 결과,
fingerprint가 모두 맞아야 한다.

## 14. 적대적 리뷰와 감독 게이트 종합

### 14.1 실행한 게이트

Orca orchestration으로 다음 의존 순서를 실행했다.

1. Claude Opus 5 xhigh 적대적 리뷰
   - task `task_ce1ab901256d`, dispatch `ctx_d933d161fd60`
   - 판정: `CHANGES_REQUIRED — Blocker 5, Major 10, Minor 4`
2. Codex GPT-5.6 Sol xhigh 감독 리뷰
   - task `task_fb076ac5f594`, dispatch `ctx_6847c6f68e77`
   - Claude finding 판정: CONFIRM 17, PARTIAL 2, REJECT 0
   - 감독 판정: `CHANGES_REQUIRED — Blocker 7, Major 11`

두 판정은 리뷰 당시 초안에 대한 것이다. 이 최종 문서는 그 blocker와 major를 반영한
조정자 최종안이며, 감독이 초안에 PASS를 줬다고 기록하지 않는다.
두 reviewer는 엔진과 BB2 데이터를 읽기 전용으로 검토했고 repo 파일을 수정하지 않았다.

### 14.2 수용한 핵심

- 재발 방지 / 두 사고 복구 / legacy 부채의 3축 분리
- 전체 코퍼스 재적재 금지
- quote, stale, access 상태 분리
- semantic CodeLocator title 폐기와 DomainMapping 의미 소유권
- principal 모델 전 quote 기본 생략
- 모든 제품 쓰기의 공통 mutation service
- journal, single-writer lock, crash recovery
- 일반 ingest와 ID-only migration 분리
- full-ID 중복을 dict 변환 전에 거부
- verified_at 엔진 stamping
- mark-checked의 quote 재검증과 no-quote 거부
- 절대 repo root와 Git 오류 세분화
- snapshot에 objects/manifests/index/stale-set를 한 단위로 포함
- fallback details·quote 미노출
- 무관 query 두 개의 회귀 게이트
- old→new symbol 대응표와 parser/수동 증거
- 별도 engine worktree와 수동 installer 검증
- 일반 우회 플래그 폐기
- exact MOVE `shot-bubble-sprite--6 → shoot-action`

### 14.3 그대로 수용하지 않은 제안

| 제안 | 최종 판정 |
|---|---|
| `(repo,path,commit_sha)`로 ID migration 동일성 판단 | anchor 고유성이 없어 기각. canonical payload hash와 명시적 rewrite manifest 사용 |
| ContextProjection 0개 | 현재 1개이므로 정정 |
| `VALID_KINDS` 20종 | 현재 `schema.py`는 19종이므로 정정. 19종 registry 전수 일치 강제 |
| 최종 ID 위반도 116건 | 116은 ReviewRecord를 뺀 부분 검사. 전수 grammar에서 3건을 더 찾아 migration 후보 119건으로 정정 |
| unknown ID grammar는 warning | 조용한 누락을 만들므로 error |
| caller timestamp 범위로 verified_at 검사 | 호출자 위조 여지가 있어 기각. 엔진이 검증 성공 직후 생성 |
| 모든 경로에 quote 동반 | 권한 주체 부재와 fallback 폭증 때문에 기각 |
| 의미 title을 위해 전 anchor 코드 재조사 | 의미 소유권 자체를 DomainMapping으로 옮겨 불필요 |
| no-DB 폴백이 현재 수 MB | 실측은 약 383KB + quote 75.9KB로 정정. 크기보다 전량 노출과 우회가 본질 |
| 무관 회귀에 synonyms 자동 추가 | 복구와 어휘 변경을 섞으므로 기각 |
| 정확한 파일 delete만으로 replace | crash consistency가 없어 기각. journal transaction 사용 |
| 괄호를 일괄 제거해 symbol 정규화 | overload·소속 손실 위험 때문에 기각. parser와 old→new 판정표 사용 |

### 14.4 기존 사용자 선택을 뒤집은 이유

초기 논의에서는 CodeLocator title에 짧은 의미 설명을 두는 안을 선택했다. 최종안은 이를
뒤집어 `title=symbol` display label을 채택한다.

이유는 취향이 아니라 실제 소비 경계다. title은 search, show, graph를 통해 에이전트에게
사실 라벨처럼 노출되지만 CodeLocator는 의미 검수 객체가 아니다. quote가 정확해도 역할
설명이 정확하다는 보증은 생기지 않는다. 이미 reviewed 의미를 소유하는 DomainMapping이
있으므로 의미를 그곳에 하나만 두는 편이 더 안전하다.

## 15. 범위 밖과 다음 단계

이번 설계에서 하지 않는 일:

- 구현 코드 작성
- BB2 코퍼스 수정
- 현재 미커밋 구현의 승인
- 전체 quote 백필
- 검색 DF 상한 조정
- principal/팀 ACL 모델 설계
- 사람이 JSON을 직접 읽는 UI를 메인 제품으로 승격

현재 worktree의 title=symbol, precondition, duplicate 검사는 구현 증거일 뿐이다. 이 최종
설계와 항목별로 다시 대조하고, 맞는 변경만 별도 구현 계획에서 사용한다.

다음 단계는 이 문서를 입력으로 `writing-plans`를 사용해 엔진 코어, template/install,
광선발사 복구, 인게임 복구, ID migration, display migration을 서로 다른 검증 경계로
나눈 실행 계획을 작성하는 것이다.
