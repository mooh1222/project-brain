# project-brain — 로드맵 / 히스토리

검수 상태·근거가 붙은 객체 코퍼스 + 한국어 하이브리드 검색 + 조회/적재 CLI를 갖춘
**범용 프로젝트 브레인 엔진**의 발전 단계와 미뤄둔 작업을 한 곳에서 관리한다.

- 전체 구조·현재 코드 길찾기: [docs/architecture/README.md](docs/architecture/README.md)
- 설계 근거(정체성·철학·아키텍처·미결): [docs/design-canonical.md](docs/design-canonical.md)
- 설치·사용: [README.md](README.md) · 개발 루프 정본: [AGENTS.md](AGENTS.md)
  (`CLAUDE.md`는 `@AGENTS.md` wrapper)
- 단계별 설계/계획 문서: `docs/specs/` · `docs/plans/` · `docs/superpowers/specs/` ·
  `docs/superpowers/plans/` · `docs/skill-drafts/`
- 비교·검증 보고서: [docs/reports/](docs/reports/)
- 데이터·적재 이력은 각 프로젝트 레포(`brain/`)에 있다. 이 로드맵은 **엔진 기능**만 다룬다.
  BB2(첫 데이터) 적재 작업 추적은 vault task `bb2-project-brain-build`에 남아 있다.

> 출처 메모: 이 엔진은 BB2 게임의 내부 도구로 출발해 2026-06-11 범용 엔진으로 분리됐다.
> 설계 문서 파일명의 `bb2-brain-` 접두사는 그 출발을 그대로 보존한 것이다(본문에 BB2
> 사례가 섞여 있어 이름만 바꾸면 오히려 불일치).

---

## 현황 (층별)

| 층 | 상태 | 비고 |
|---|---|---|
| L1 저장 엔진 | ✅ 완료 수준 | 19 kind(Insight 포함)·원자성 적재·promote·lint |
| L1 인사이트 그릇 | ✅ `Insight` kind (2026-06-15) | advisories 별도 통로·candidate 적재 거부(1차) |
| L0 raw 보관 | ✅ 있음 | `raw/sources/<context>/` 텍스트 추적·locator brain root 상대·보수적 토큰 근사와 과대 유닛 분할 |
| L2 검색 색인 | ✅ 있음 | FTS5 BM25 + bge-m3 벡터 + RRF + 그래프 재정렬 + scoped BM25 + raw 색인 |
| L3 라우터·회상 | ✅ 회수 전담 (#71 프로그램, 2026-09-04) | bare/explicit `search` 5채널 일반 회수 + `show` 본문·이웃·mapping stale + `query` 네 결정론 조회 축(#61). 다신호 답변 게이트·점수 바닥·`needs_clarification`을 폐지해 채널을 검수 상태·객체 종류로만 가르고(#77, ADR 0008), 그 자리에 회수 사실을 실었다 — `query_tokens`(토큰별 `object_df`·`raw_df`)·적중별 `matched_query_tokens`·`scope`(#73). `search`에 `--context-id`·`--all-contexts`·`--top-k`(#74), 평가 하네스는 `no_answer` 대신 부재 토큰 보고를 단언한다(#76). 답변 판정은 조회 스킬을 따르는 에이전트 몫(#78) |
| L4 적재 | ✅ 공개 경로 운영 | 소급 / 개발 중 / 현재·과거 세션 추출 + `build` 조립 자동화 + 재개 가능한 batch·semantic finalization + coverage·단일 쓰기·receipt. `session complete`는 성공한 batch receipt와 transcript를 결속 |
| 검수·쓰기 정책 확장 | ⏸️ 재판단 중 | #4 capability registry와 #41~#43 evidence plan/preparation은 main의 내부 기반이지만 공개 caller가 없다. #44~#46과 공통 verification 프로그램은 보류 |
| 어휘 기준·지식 초안 | ✅ 대체 범위 완료 | #48 공통 어휘 기준, #49 이름 표면 회수, #50 지식 초안 엔진·CLI·설치 스킬, #51 실제 BB2 로컬 전용 파일럿 완료 |
| 재사용층(projection) | ✅ 구현·검증·push (2026-06-17) | 착수 브리핑 `projection_reuse` 재회수 + 해시 시각필드 제외·`projection refresh` (2026-06-24) |
| 코드 변경 안전망 | ✅ stale-check / mark-checked (2026-06-15) · 미머지 앵커 라벨 + show 노출 | 읽기 전용 후보 제시 · 갱신 대상은 commit_sha/verified_at(줄번호는 저장 안 함) · `--write-cache`→show advisory |
| 그래프 무결성·고립 | ✅ `graph isolated` + build 경고 + `graph export` (2026-06-24) | 인바운드 0 잎 탐지·vis-network 시각화 HTML·엣지 정본 단일 출처 |
| 공유 경계 | ✅ 엔진/데이터 2-레포 분리 (2026-06-11) | brain/ git 추적·색인만 로컬 |

---

## 진행 중

### 현재 기준 재설정과 작은 replacement spec (2026-08-28)

replacement 시작 런타임 기준점은 `aa4101ec8fe62878b9a554b471be66d519cf4bc8`이다. 그 뒤 기준선
문서와 Git ignore 정리를 거쳐 #48이 설치 스킬 계약을 처음 바꿨다. 과거 #1 통합 명세와 열린
하위 그래프는 새 실행 계약으로 사용하지 않는다. #47과 후속 #48~#51이 승인된 새 실행 계약이며,
과거 열린 그래프는 대응표를 남기고 `NOT_PLANNED`로 정리한다. 이미 닫힌 완료 이슈와 구현 기록은
보존한다.

현재 main과 BB2 로컬 전용 파일럿의 분류는 다음과 같다.

- **공개 경로에 연결됨**: #2 query/audit 기본 읽기 전용, #3 receipt-bound `session complete`,
  #5 snapshot v1·v2 19종 동결, #48 공통 어휘 기준과 ingest·session-ingest·audit 조건부 연결,
  #49 대표어·동의어·별칭의 reviewed 어휘·매핑 동등 회수, #50 지식 초안 모듈·CLI와 다섯 번째
  설치 스킬.
- **내부 정책·부분 기반**: #4 `capabilities.py`는 분산 runtime 분기를 대체하지 않는 설명·드리프트
  검사 registry다. #41 `evidence_plan.py`와 #42~#43 `evidence_preparation.py`는 직접 테스트만 있고
  public ingest·promote·CLI·설치 스킬에서 import하거나 호출하지 않는다.
- **실제 BB2 파일럿 완료**: #51 샐리 카누 초안·어휘 감사를 BB2 로컬 커밋으로 완료했다. 기존
  Brain 객체·raw·index는 바꾸지 않았고, 무관한 로컬 이력이 섞인 브랜치는 원격에 push하지 않았다.
- **미구현·범위 밖 유지**: `GlossaryClassificationRecord`, 공통 verification 공개 적용.

replacement spec #47의 활성 결과는 네 개로 제한한다.

1. #48 공통 어휘 기준 reference와 ingest·session-ingest·audit 연결 — 구현 완료
2. #49 대표어·동의어·별칭 회수 통일 — 구현 완료
3. #50 지식 초안 모듈·CLI·`brain-draft` 설치 스킬 — 구현 완료
4. #51 실제 BB2 샐리 카누 초안·어휘 감사 파일럿 — BB2 로컬 전용 완료

공통 candidate verification, `GlossaryClassificationRecord`, #44~#46, 전체 BB2 어휘 migration,
초안 정식화·close·자동 라우팅은 이 범위 밖이다. 구현 중 계약 공백이 발견돼도 새 admission이나
하위 티켓을 자동 생성하지 않고 사용자에게 현재 실패와 필요한 결정만 보고한다.

후속으로 보존하되 현재 범위를 막지 않는 항목은 다음과 같다.

- #40: 현재·과거 세션 여러 개의 미리보기, 동일 세션 중복 방지, 성공한 세션만 완료 처리.
- Project Brain 자체 `brain/` self-hosting과 과거 엔진 세션 백필: BB2 데이터를 엔진 레포로 옮기는
  안이 아니며, #40의 Claude·Codex·Orca 세션 source 범위와 배치 계약을 정한 뒤 별도로 재검토한다.
- #4·#41~#43: 현재 main에 동결한다. 실제 필요나 유지비가 확인될 때 재사용·격리를 별도로 결정한다.

현재 BB2 설치본은 엔진 템플릿과 완전히 같지 않다. #51에서 새 draft 스킬과 공통 어휘 기준을
설치하고, 기존 ingest·session-ingest·audit 프로젝트 overlay에는 관련 pointer만 명시적으로
병합했다. installer는 사용자 수정 파일을 보존했으며, 나머지 overlay 차이는 #47 완료 결과나
엔진 템플릿 관리 범위로 확대하지 않는다.

---

## 완료 단계

### #61 일반 조회 search·show 통일과 query 결정론 조회 축 축소 — 완료 (2026-09-01)

서브커맨드 없는 자유질의와 explicit `search`를 같은 public 회수 경로와 같은 fresh-index 실패
계약으로 통일했다. 설치 조회 스킬은 일반 의미·코드 위치·개발 착수 질문에서 검색 결과의 핵심 객체를
`show`로 열고, candidate를 쓰면 확인 필요 상태를 표시한 뒤 여러 객체를 조합한다.

- explicit `query`는 변경 이유·현재 상태·과거 시점·근거 사슬의 조회 축만 BrainStore에서 결정론적으로
  계산한다. 일반 의미·구현 위치·unknown recall은 객체 종류를 고르지 않고 `search → show`를 안내한다.
- query의 index·embedder·recall·Insight·mapping stale·current-head 배관과 #59의 candidate spillover
  응답 필드를 제거했다. mapping stale은 `show`, Insight advisory는 `search`가 소유한다.
- 충돌·supersedes·current/as-of·인과관계·DecisionRecord·근거 사슬과 CurrentView source fact 유효성,
  #59의 reviewed 대표어·동의어·별칭 matcher는 보존했다. ranking·채널·scope·index surface는 바꾸지 않았다.
- 실코퍼스 쓰기·migration·index rebuild는 수행하지 않는 범위다.

### #51 실제 BB2 샐리 카누 지식 초안·어휘 감사 — 완료 (2026-08-28, BB2 로컬 전용)

BB2 `docs/bb2-brain-object-model`에서 `sally-canoe-glossary-audit` 초안을 spec-v8과 live Event API·
Join API 위키로 만들고, 전체 GlossaryTerm 1,181개를 읽기 전용으로 측정했다. 샐리 카누 125개는
독립 유지 19, 통합·대표어 교정 17, 상위 DomainMapping·CodeLocator 보존 76, 무객체 제거 후보 7,
사용자 판단 필요 6으로 빠짐없이 분류했으며 기존 객체와 색인은 수정하지 않았다.

- 다른 새 세션이 과거 대화 없이 초안을 발견·설명하고 expected SHA로 갱신했다. stale SHA는
  기존 bytes를 바꾸지 않고 실패했고, 사용자는 실제 재개 비용이 줄었다고 확인했다.
- BrainStore·raw·index fingerprint와 bytes·일반 조회·graph·snapshot 대상은 생성·갱신 전후
  같았다. 엔진 회귀와 실제 BB2 검증을 분리해 통과했다.
- BB2 커밋은 `a045328448`, `2e5382c118`, `e66fefd731`이다. 기존 로컬 이력과 dirty 파일을
  보존하기 위해 원격 push는 하지 않았고 GitHub #51은 이 로컬 증거로 `COMPLETED` 처리했다.

### #50 지식 초안 모듈·CLI와 `brain-draft` 설치 스킬 — 완료 (2026-08-28)

config가 해석한 `brain/drafts/<ASCII-kebab-topic-id>.md`만 소유하는 `draft.py`와
`project-brain draft create/list/show/update/lint`를 추가했다. v1 Markdown 구조·UTF-8·실제
경로를 lint하고, show의 SHA와 같은 expected SHA에서만 같은 디렉터리의 임시 파일을 원자
교체한다. stale SHA와 잘못된 본문은 기존 파일을 바꾸지 않는다.

- 목록은 topic ID·제목·범위·갱신 시각만 반환한다. 설치되는 model-invoked `brain-draft`는
  하나의 명확한 초안만 바로 재개하고 여러 후보는 본문을 읽기 전에 사용자 선택을 받는다.
- session-ingest는 현재·과거 세션 재료 추출만 맡고, 미결 내용은 draft로, 확인된 내용은
  ingest로 넘긴다. 공통 어휘 기준은 ingest reference 한 파일을 조건부로 읽는다.
- drafts는 BrainStore·raw·index·일반 조회·graph·snapshot에서 제외되며 엔진은 Git
  stage·commit을 실행하지 않는다. 정식화·close·자동 라우팅·history·receipt·시작 hook은
  범위 밖으로 유지했다.

### #49 대표어·동의어·별칭의 의미 매핑 회수 통일 — 완료 (2026-08-28)

`QueryRouter`의 `glossary_meaning` exact 경로가 reviewed `GlossaryTerm`의 대표어·동의어·별칭을
같은 이름 표면으로 취급하고, 맞은 어휘와 그 어휘를 참조하는 reviewed `DomainMapping`을 함께
회수한다. exact 어휘는 recall top-K 밖으로 밀려도 먼저 포함하며 scope 추론용 기존 매처와
candidate 노출·`avoid` 교정 경로는 바꾸지 않았다.

- `DomainMapping` 색인 표면도 reviewed 참조 어휘의 `term`·`synonyms`·`aliases`를 모두
  이어받는다. candidate 참조 어휘는 기존 `term`·`synonyms`만 유지한다. 추출기 버전은 4로
  올렸고, aliases가 있는 코퍼스는 표면 기반 fingerprint가 달라져 예전 DB를 stale로 거부한다.
- 실제 BB2에서 실모델 색인을 한 번 재구축해 객체 7,881개와 raw chunk 1,583개를 v4 DB에
  적재했다. `KAMEHAMEHA`·`광선 발사`·`광선발사` 세 질의가 모두 같은 reviewed 어휘와
  `mapping.petskill-kamehameha.skill-code-registration`을 회수했다.
- BB2 `brain/checks`는 13개 중 12개 통과·1개 skip, 실모델 eval은 15/15를 통과했다.
  tracked corpus 변경은 없고 `GlossaryClassificationRecord`·공통 candidate verification·
  evidence preparation 공개 연결은 추가하지 않았다.

### Task 18 표시 제목·인용문 부채 — 적용·검증 완료 (2026-08-11)

표시 제목 규칙과 독립 검증·복구 경계를 엔진에 구현하고, BB2 실코퍼스에서 CodeLocator
3,305개와 짝 EvidenceRef 3,186개, 합계 6,491개의 `title`만 갱신했다. create/delete/rename과
보조 파일 변경은 0건이고 짝 불일치도 0/3,202였다.

- attempt-005는 gate·apply·리뷰·완료 문서 commit까지 성공한 뒤 closure-create에서
  descendant ref 계약 결함을 드러냈다. closure-verify는 실행하지 않았고,
  engine `bc2b8de8` 수정·BB2 `c924843e` exact revert commit·canonical v2 restore로
  계약과 corpus를 복구한 뒤 attempt-006 전체 순서를 다시 실행했다.
- 엔진 implementation HEAD `bc2b8de82b0cf31a9b1cea6550cae5981ed4c7b6`, BB2 corpus HEAD
  `7ed3cc687fb3ba09fc0f3ebe274cbfc1cd1bd2d5`
- 인용문 부채 3,307건과 비정본 symbol 289건은 목록화한 상태 그대로 보존했으며 backfill하거나
  고치지 않았다. legacy 인용문은 적재 당시 검토됐지만 현재 저장 정보만으로 기계 재검증할 수 없는
  항목이다. 이를 "검증된 적 없음"으로 보지 않는다.
- 엔진 pytest 2,077개(+ subtest 136개), 설치 runtime 120개, BB2 checks 12개, audit lint 0,
  eval 15/15, graph export를 통과했다. index DB SHA와 기존 사용자 변경은 그대로 보존했고
  index rebuild와 finalizer는 실행하지 않았다.
- engine과 BB2 독립 최종 리뷰는 설계 준수·품질 모두 통과했고 Critical·Important·Minor가
  각각 0건이었다.
- 설계: [Task 18 재설계](docs/superpowers/specs/2026-08-06-task18-display-labels-and-quote-debt-redesign.md) ·
  계획: [Task 18 구현 계획](docs/superpowers/plans/2026-08-06-task18-display-labels-and-quote-debt.md) ·
  결과: [완료 보고서](docs/reports/2026-08-06-task18-display-labels-and-quote-debt-completion.md)

attempt-006 완료 문서 commit 뒤 create-only closure와 독립 verify까지 완료했다. closure
SHA-256 `1a6a17c3f0f5ca13e15c08bb26dbf151dc959971dbccd399ff6f43515ae53495`는 engine
implementation `bc2b8de82b0cf31a9b1cea6550cae5981ed4c7b6`, engine docs
`da044273af6fae011d4ee43ab17a4c79eb434fc5`, BB2 corpus
`7ed3cc687fb3ba09fc0f3ebe274cbfc1cd1bd2d5`를 결속한다. 독립 verify SHA-256은
`32ce0f2d1b07b04173c89157143ccd5397ebbf4dd44e0d4d3cf1dcf3d8a7107c`이고 `ok=true`다.
이후 문서 이력은 이 고정 결속을 넓히거나 무효화하지 않으며 closure를 다시 실행할 이유가
아니다. 현재 인계는 [Task 18 세션 인계](docs/reports/2026-08-11-task18-session-handoff.md)를 본다.

### P0 ingest integrity foundation — 완료 (2026-08-05)

신규 적재를 `CoverageContract → 독립 expected planner → MutationService 단일 clock →
mutation/no-op receipt → foundation gate`로 결속했다. coverage 없는 single/batch 쓰기 차단,
assembled/direct identity 결속, 신규·변경 write semantics, canonical receipt와 복구, 설치
runtime·template 일치, BB2 비변이 gate와 snapshot handoff까지 완료했다.

- 엔진 완료 HEAD: `e84d4ed371a59de158c65beb9c5b05a2e9bef7f1`
- BB2 runtime 완료 HEAD: `fbcbc861f9a9b43c3ac483e43b8d706c9c4d2b01`
- 엔진 전체 회귀: `1808 passed`, subtests `127 passed`; 설치 runtime `120 OK`
- BB2 gate: 정해진 6개 명령 전부 성공, finalizer·index rebuild 없음
- corpus objects/raw/index 불변; 허용된 `brain/.brain-local/stale-set.json`만 갱신
- snapshot: 11,168 files, manifest `0ec3d3874bcb…`; handoff `ok=true`
- 독립 최종 리뷰: Critical·Important·새 Minor 없음

완료 증거와 이후 문서 커밋의 경계는
[P0 적재 무결성 완료 보고서](docs/reports/2026-08-06-ingest-integrity-foundation-completion.md)에
기록했다.

### 1차 마일스톤 — 검색층 + 라우터 통합
한국어 형태소 토크나이저 + BM25(FTS5) + bge-m3 벡터 + RRF 융합 + 그래프 1-hop 상호지지
재정렬 + 다신호 게이트. 라우터에 통합(정확 매칭 보존 + 의미 보강 + "없으면 없다").
통과 기준 = jira 티켓→코드 핀포인트(무더기 반환 아님) + 맥락만으로 의미 회상.

- 설계: [docs/specs/2026-06-10-bb2-brain-search-layer-design.md](docs/specs/2026-06-10-bb2-brain-search-layer-design.md) (권위)
- 라우팅: [docs/specs/2026-05-28-bb2-brain-query-routing-design.md](docs/specs/2026-05-28-bb2-brain-query-routing-design.md)
- 계획: [docs/plans/2026-05-28-bb2-brain-p0-router.md](docs/plans/2026-05-28-bb2-brain-p0-router.md) · [router-mapping-integration](docs/plans/2026-06-02-bb2-brain-router-mapping-integration.md) · g4~g11 게이트 시리즈(`docs/plans/`)

### 저장 기반
객체 모델(18 kind)·저장 레이아웃 확정. git 추적 경계(brain/ 전체·색인만 로컬), raw 규약
(`raw/sources/<context>/`), project_id 닫음(프로젝트 경계 = 레포 경계).

- 설계: [object-model](docs/specs/2026-05-27-bb2-brain-object-model-design.md) · [storage-layout](docs/specs/2026-05-28-bb2-brain-storage-layout-design.md)

### 적재 경로 (L4)
적재 3경로(완성 스펙 소급 / 개발 중 / 과거 세션 추출) + 검수 사다리(candidate→reviewed).
도메인 매핑 수명주기, 용어 승격, scope 자동 라우팅, scoped BM25(정당한 어휘 중첩에 의한
df 흔들림 면역), candidate locator 노출, 시스템 도메인 적재.

- 설계: [universal-ingest](docs/specs/2026-06-04-bb2-brain-universal-ingest-design.md) · [bc-review-model-v2](docs/specs/2026-06-05-bb2-brain-bc-review-model-design-v2.md) · [p2-ops-layer](docs/specs/2026-06-10-bb2-brain-p2-ops-layer-design.md) · [session-ingest](docs/specs/2026-06-11-bb2-brain-session-ingest-design.md) · [system-domain](docs/specs/2026-06-12-bb2-brain-system-domain-design.md) · [domain-mapping-lifecycle](docs/specs/2026-06-02-bb2-brain-domain-mapping-lifecycle-design.md) · [mapping-vouched-term-promotion](docs/specs/2026-06-08-bb2-brain-mapping-vouched-term-promotion-design.md)
- 계획: [scoped-bm25](docs/plans/2026-06-12-bb2-brain-scoped-bm25.md) · [extraction-guide(spec)](docs/specs/2026-06-04-bb2-brain-extraction-guide-design.md)

### Insight kind
여러 객체·구현·결정을 가로지르는 위험/교훈을 담는 신설 kind. advisories 별도 통로로만
노출(일반 답에 비섞임), 객체 레인·게이트 둘 다 Insight 개수에 면역.

- 설계: [insight-kind](docs/specs/2026-06-15-bb2-brain-insight-kind-design.md)

### raw 본문 색인 + 정리
raw 청커(헤더 1차·500토큰 근사·문장 경계·15% 겹침·결정론) + 별도 레인(과대적재 후 kind
분리) + `raw_excerpts` 채널. store 재사용 주입, `cli query` 배선. 2026-07-22부터 토큰 근사는
ASCII 단어 1·한글 음절 1·그 밖의 비공백 기호 2글자당 1로 보수화했고, 표 한 줄처럼 분할
경계가 없는 단일 유닛도 목표 크기 아래로 다시 나눈다.

- 계획·설계: 검색층 스펙 §2.2 (위 1차 마일스톤 링크)

### 재사용층 (projection)
한 기능 안에서 조립한 착수 브리핑을 `ContextProjection`(format=prompt_payload) 별도 검색
레인(`projection_reuse` 채널)으로 저장해 재방문 시 재조립을 줄인다. 답변 텍스트 캐시는
기각(설계 §2 "AI 유지보수 문서층 금지" 충돌). candidate 저장 → 사용 시점 promote, 채널
유지·라벨만 status로 분리.

- 설계: [projection-reuse-layer](docs/specs/2026-06-17-bb2-brain-projection-reuse-layer-design.md)
- 계획: [projection-reuse-layer(plan)](docs/plans/2026-06-17-bb2-brain-projection-reuse-layer.md)

### 적재 조립 자동화 (build) + 2-레포 분리
"구조화 노트→객체 묶음" 조립을 `project-brain build`로 대체(id 파생·연결·끊긴 참조 검사는
엔진, 판정은 노트). 엔진/데이터 2-레포 분리 실행.

- 계획: [project-brain-assembly-build](docs/plans/2026-06-16-project-brain-assembly-build.md)

### 코드 변경 안전망
`stale-check`(읽기 전용 후보 제시) + `mark-checked`(locator closure 검토 완료 시
CodeLocator commit_sha/verified_at 갱신). 목적은 줄번호 갱신이 아니라 "코드 변경 뒤 매핑
의미가 낡았을 후보" 발견.

- 설계: [stale-check](docs/specs/2026-06-14-bb2-brain-stale-check-design.md) · 계획: [stale-check(plan)](docs/plans/2026-06-14-bb2-brain-stale-check.md) · [update-mechanism-followup](docs/plans/2026-06-13-bb2-brain-update-mechanism-followup.md)

### 그래프 고립 탐지 + projection 해시 정합 (2026-06-24)
bb2_client 고립 노드 정비 4세션(2026-06-23)을 회고해 도출·검증한 엔진 보강. 진짜 버그
하나와 빠진 도구 하나가 핵심. 독립 code-review PASS(무조건), 엔진 합성테스트 488 통과,
데이터 레포 eval 10/10 복구.

- **projection 해시 정합(C2+C3, 버그 수정)**: `source_content_hash`가 시각·버전 메타
  (`created_at`/`updated_at`/`verified_at`/`captured_at`/`schema_version`)를 빼고 의미
  내용만 해시한다. `_at` 일괄 변환(KST 표준화)이 의미 불변인데도 projection을 stale로
  오판해 **eval 10→8 회귀**를 냈던 버그를 근원 수정. 생성식 2곳(context_projection)·검증식
  1곳(lint)이 `hash_utils.source_content_hash` 단일 헬퍼를 공유(드리프트 차단).
  `projection refresh [--ids]` CLI로 기존 코퍼스 해시를 전수 재계산(reviewed→reviewed 멱등
  재적재 활용, dangling은 merged lint를 막으므로 빠른 실패).
- **그래프 고립 탐지(C1, 빠진 도구)**: `graph isolated [--kind]` CLI — store 1회 순회
  역인덱스로 "아무도 안 가리킴(인바운드 0)"인 잎 객체를 읽기 전용으로 보고. 무결성 검사가
  그동안 아웃바운드(끊긴 참조=dangling)만 보던 단방향 비대칭을 해소. 인바운드 엣지 필드는
  명시 allowlist(외부 키 `channel_id`·`project_id`·`jira_issue_ids` 제외, `evidence_refs`
  포함), 점검 잎 kind 화이트리스트(CodeLocator·GlossaryTerm·EvidenceRef)로 구조적 인바운드0
  kind(CurrentView·Insight 등) 폭주를 막는다. 발견은 엔진, "어디에 연결할지" 판정은 스킬·사람.
- **build 사후 고립 경고(C8)** + **시점 자동기입 회귀 테스트(C4)** + **회귀 명령 문서 정정(C10)**.
  C8은 C1의 역인덱스 헬퍼(`graph.referenced_ids`)·잎 kind를 공유, build report에 비차단
  `warnings`로 신규 고립 잎을 담는다(차단 아님 — candidate 일시 고립은 정상).
- 계획(작업 순서 단일 출처): [isolated-node-followup](docs/plans/2026-06-23-bb2-brain-isolated-node-followup.md)
  · 상세 분석 근거는 같은 레포 `.snapshots/2026-06-23/`(git 미추적).
- **남은 스킬 Task(C6·C7·C9) ✅ 완료** (2026-06-24, 데이터 레포 `bb2_client` `125cd987de` —
  엔진 밖 스킬·가드 측). C7 — `bb2-brain-ingest/references/ingest-tools.md` "적재 후 확인"
  4→5단계(`graph isolated` 고립 재점검) + `SKILL.md` 절대규칙 7 확장(사후 재점검 + 연결 정책:
  primary 1개 + 진짜 공동 primary만, 약한 secondary는 희석 방지로 제외) +
  `history_coverage=complete` 판정 보강(4종 다 봤는가가 아니라 알려진 변경집합 전부 연결인가).
  session-ingest 적재 후 단계에도 고립 재점검 추가. 연결 정책은 발명 없이 06-23 정비 원전에서 옮김.
  C6 — 실코퍼스 가드 객체행 수를 하드코딩 상수 대신 디스크의 색인 대상 kind `.json` 수(엔진
  `surface.py` `_EXTRACTORS`와 일치)로 자동 대조 + 색인 제외 kind 표(`EXPECTED_RAW_CHUNKS`는
  청커가 정해 상수 유지). C9 — `bb2-brain-query/SKILL.md`에 적중 원소 식별자 키 `object_id`
  (`id` 아님) 노트(`templates/query.md`와 동기화). 검증: unittest 5 OK · `graph isolated` 15(무영향)
  · 적대 검증 3 + 데이터 레포 code-reviewer APPROVE(LOW 2건 반영).

### 그래프 시각화 export (2026-06-24)
코퍼스를 vis-network 단일 HTML로 내보내는 `project-brain graph export <out.html>`.
데이터 레포의 `.brain-local/graph_export.py` 로컬 프로토타입(git 미추적이라 다른 머신·
새 클론에 없어 재현 불가)을 정식 명령으로 승격. 엣지는 `graph isolated`와 같은 정본
정의(`graph.edges`가 `reference_fields` registry의 `iter_object_refs()`를 사용하고 외부 키는
제외)를 써서 "어떤 잎이 왜 고립인지"가
화면에서 그대로 보인다(둘이 어긋나지 않게 단일 출처). 노드 클릭 시 객체 전체·kind 필터·
검색·이웃만 보기 지원. vis-network는 CDN(unpkg)에서 받아 파이썬 의존성 0, 볼 때 인터넷
필요. 읽기 전용(store 불변, 출력 파일만). 다관점 적대 리뷰 8건 중 4건 확정·반영
(edges from 가드·출력 부모 자동생성·payload 1회 생성·라벨 절단/폴백 테스트). 합성 501 통과.

### 코드 근거 정비 — locator 번호표 + 줄번호 제거 + show CLI (2026-06-24)
근거 위치 정보를 원래 설계 의도(정본 §6.2)로 복원. 코드 책갈피(EvidenceRef)의 `locator`에
좌표를 복사하는 대신 짝 코드 위치 장부(CodeLocator)의 id를 **번호표**로 저장
(`{"code_locator_id": <짝 CodeLocator id>}`). 엔진이 읽지도 갱신하지도 않던 줄번호
(`line_start`/`line_end`)는 `build`가 더 이상 만들지 않아 신규 저장에서 빠진다(스키마는
줄번호 optional로 허용만 — 거부 규칙 추가가 아니라 발원지에서 안 만들 뿐). 회상으로 찾은 객체를 펼쳐보는
`project-brain show <id>` 신설(본문 + 1-hop 이웃을 종류·제목과 함께) + `search` 이웃에
제목 동반(맨 id → 제목 표시). 소비자 무영향 확인(eval_harness는 str/dict 모두 수용,
router는 object_id로 재조회). 합성 506 통과, route 적대 리뷰 APPROVE(LOW 1건은 검색 정본과
일관·회귀 아님으로 보류). 엔진 템플릿(ingest·session-ingest·query)·데이터 레포 bb2 스킬에서
줄번호 안내를 함께 정리(심볼+`commit_sha`가 앵커·변경감지 기준임을 명시). 기존 코퍼스 일괄
변경(Part B)은 실익 0 + 짝짓기 구조적 불가 ~45건으로 미룸(미뤄둔 작업 §4).

- 계획(확정본·결정 로그·Part B 보류 근거): [code-evidence-cleanup](docs/plans/2026-06-24-brain-code-evidence-cleanup.md)

### stale 자동화 Step 1·2 — 미머지 앵커 라벨 + query/show 노출 (2026-06-25)
설계(보류했던 자동화, 미뤄둔 작업 §6)의 **엔진 부분만** 구현. Step 3(에이전트 diff 자동
정리)은 실코퍼스 회귀가 필요해 보류 유지.
- **Step 1 — 미머지 앵커 라벨**: `stale-check`이 `git merge-base`로 앵커 `commit_sha`가
  config의 `default_branch` 조상인지 판정해, 조상 아니면(PR 머지 전 작업 브랜치 커밋) candidate에서 빼고
  새 키 `unmerged_anchors`(차단 아니라 라벨)로 분리. bb2 실행에서 본 거짓 'D'(삭제) 신호를
  근원 제거(머지되면 자동 해소). 약식 sha는 `base.startswith(from_commit)` prefix 비교로 처리.
- **Step 2 — query/show 노출**: `stale-check --write-cache`가 stale-set을
  `.brain-local/stale-set.json`(색인과 같은 재생성 파생물)에 떨구고, `query`/`show`가 읽어
  매핑별 `stale_advisory`(코드 변경 감지 + 기준 시점)를 곁들인다. 파일 IO는 CLI, router는
  주입된 dict만 소비(git·파일 모름 — `git_runner` 주입과 같은 패턴). 캐시 없으면 동작 불변.
- 검증: 합성 519 통과(신규 13), 3렌즈 적대 검증 correctness·regression clean. 실코퍼스 회귀는
  데이터 레포에서 별도(아래 주의). 계획: [stale-step1·2 impl](docs/plans/2026-06-25-brain-stale-step12-impl-plan.md).

### 코퍼스 감사 audit — stale 캐시 도는 주체 (2026-06-28)
Step 2가 읽기(`query`/`show`)·쓰기(`stale-check --write-cache`) 양끝을 만들었으나 **캐시를
채울 주체가 없어** stale_advisory 채널이 죽어 있던 갭을 메움. `project-brain audit`이
`lint`(무결성) + `graph isolated`(고아 잎) + `stale-check --write-cache`(코드 드리프트)를 한
패스로 돌려 캐시를 채운다 — 셋은 "코퍼스 건강검진"이라는 같은 결이라 묶음. 관리 스킬
`audit.md`(install 주입 4번째)로 어시스턴트가 config의 `default_branch`를 당긴 뒤·대량 적재 후 돌린다. 후보
처리는 검수 정책 B+C(자동 supersede 없음 — Step 3 여전히 보류, 에이전트가 advisory 보고 판정).
- 검증: 합성 530 통과(신규 audit 1), 적대 검증 OK. 실 bb2 종단(audit→캐시 45건→`show`
  stale_advisory 실회수)로 죽은 채널 부활 입증.
- 데이터레포 backlog의 2026-06-12·13 항목(line drift 무해 + "코드변경→의미갱신 발견" 별개
  니즈)이 이 기능의 설계 입력이었고, 이제 stale-check+audit으로 실현돼 그 항목들은 졸업.

### build_decisions — decisions[] 결정 결정론 조립 (2026-06-26)
`assembly.py`에 `build_decisions(notes, now)`를 신설해 노트의 `decisions[]` 섹션을
`DecisionRecord` + `EvidenceRef`(commit/jira/pr)로 결정론 조립한다. `build()`가 파이프라인에
배선(`build_mappings` 다음·`build_context` 앞)하고, 각 결정의 `affects[]`(매핑 키)를 그 매핑의
`decision_keys`로 역채움 → `build_mappings`가 `decision_record_ids`를 도출해 lint 8c(reviewed
매핑↔결정 양방향 링크)를 자동 충족한다. 모든 객체가 단일 `now` → 재빌드 idempotent(churn 0).

왜: 적재마다 `DecisionRecord`를 손으로 `extra_objects`에 조립하면 타임스탬프가 매번 달라져
재적재 churn이 나고, 매핑↔결정 양방향을 수동으로 맞춰야 해 실수 소지가 있었다. 손조립을 엔진
결정론 조립으로 흡수해 churn 제거 + 양방향 자동화 — 위 "적재 조립 자동화 (build)"에서
`extra_objects` 탈출구로 남겨뒀던 결정 조립을 1급 노트 섹션으로 승격한 것이다.

- **섹션 등록·검증**: `_VALID_SECTIONS`/`_LIST_SECTIONS`/`_ITEM_REQUIRED`에 `"decisions"` 등록,
  `validate_notes`가 `decisions[].evidence[]` 무결성(type/ref/locator)을 1층에서 검증.
- **도메인 무지 유지**: commit locator만 `{repo, sha}` 자동(repo=context), jira/pr locator는
  노트가 제공(인스턴스 URL을 엔진에 박지 않음).
- 검증: assembly 테스트 37(기존 31+신규 6)·엔진 전체 525 통과, 데이터 레포 볼셀렉 실코퍼스
  14결정 회귀 "차이 0건 PASS"(손조립==엔진조립 기능 동치). 커밋 `7c2f87c`·`91a9a6c`·`37d0da9`.
- 계획(2차 이행): [project-brain-assembly-build](docs/plans/2026-06-16-project-brain-assembly-build.md)
  Task 4가 예고한 "decisions 2차". 상세 설계·구현 플랜은 데이터 레포 `bb2_client`
  `docs/superpowers/`(2026-06-26).
- 다음(범위 밖): `bb2-brain-ingest` 스킬/조립기가 `extra_objects` 손조립 대신 `decisions[]`
  노트를 emit하도록 전환.

### GlossaryTerm 동의어 — 도메인·언어 갭 recall 보강 통로 (2026-06-26)
동료 PKM(hwi_PKM)·개인 vault 임베딩 기법을 교차검토(6후보 독립검증 + 적대 리뷰)해 "재랭커
외에 우리가 가져올 것"으로 도출한 **단 하나**. GlossaryTerm의 `synonyms`/`aliases`(특히
한국어↔영문 등가어)를 적재가 채울 수 있게 통로를 연다. 색인 표면(`surface.py`)이 이미 이
필드를 읽으므로 **새 메커니즘이 아니라 빈 필드를 채우는 통로**다.

왜: 코퍼스 term의 다수가 영문(코드명·enum·메시지키)이라 한국어 질의가 BM25 토큰을 못 잡는
언어 갭이 실재한다(실코퍼스 437개 GlossaryTerm 중 동의어가 채워진 건 2개뿐이었다). 색인 측
보강이 호출자(어시스턴트)의 질의 다듬기보다 robust한 영역 = 코퍼스에만 있는 내부 코드명·enum.

- **엔진**: `build_glossary_terms`가 노트의 `synonyms`/`aliases`를 객체에 운반(`evidence_refs`와
  같은 `g.get(...,[])` 패턴) + `_UNION_ALLOWLIST["GlossaryTerm"]`에 추가(기존 객체 백필 통로).
  `surface.py`·`EXTRACTOR_VERSION` **미변경**(이미 읽음 — 추출 로직 불변, 데이터만 채움).
- **스킬**: `templates/ingest.md`에 동의어 작성 규칙 — 한↔영 등가어 우선, **흔한 단일어 금지**
  (답변 게이트 표면 앵커 df를 흔들어 거짓양성 가드를 약화시킴), definition 본문 중복 금지.
- **검증(Task 4, bb2 실코퍼스 샘플 5개 실측)**: 골든셋 **10/10 통과 = 동의어 무해**(s5 거짓양성
  가드 유지). recall은 **고유 등가어에서만 뚜렷**("버블 생성기"→BallGenerator 회수 없음→rank5),
  일반 표현은 완만. **vault에서 본 "5.5배"는 우리 코퍼스서 안 나옴** — GlossaryTerm definition이
  이미 도메인 정의문이라 갭이 작다는 교차검토 예측이 실측으로 확인됨.
- **결정**: 기존 437개 **전수 백필 안 함**(ROI 낮음). 동의어는 **신규 적재분에만**(통로는
  머지로 활성, 추가작업 0). 검증 샘플 5개는 git 원복(기존 동의어 0 유지).
- 검증: 엔진 합성 528 통과. 커밋 `dbb57ac`·`d8bf86c`·`4987f86`.
- 계획: [glossary-synonyms-domain-gap](docs/plans/2026-06-26-glossary-synonyms-domain-gap.md)
  · 교차검토 근거: 메모리 `hwi-pkm-technique-crosscheck`(엔진 밖, 6후보 판정 + 적대 리뷰).

### 엔진 단일 관리 주체 — installer 디렉토리 walk + 채택 + footgun (2026-06-29)
스킬을 고치는 곳이 둘(엔진 templates/ + 데이터 레포 손수정)이라 갈라지던 것을 엔진 한 곳으로
모음. install이 `SKILL.md` 한 장만 주입하던 것을 `templates/<skill>/` 디렉토리 통째 walk로
바꿔 `references/`·`scripts/`까지 함께 주입한다(`__pycache__`·`fixtures`·`*.pyc`·`test_*.py`는
주입 제외 — 개발 자산·테스트 픽스처·생성물). 목표는 범용화/추상화가 아니라 "관리 주체 1곳"이며,
소비처가 bb2 하나뿐이라 도메인 예시는 bb2색 리터럴로 두고 변수 치환은 최소 수단만 쓴다.

- **변수 치환**: `{{PROJECT}}`·`{{BRAIN_ROOT}}`·`{{DEFAULT_BRANCH}}`·`{{REPO}}` 4개만(머신·레포
  종속값). 그 외 도메인 예시는 리터럴 보존.
- **manifest 파일단위 추적·보존·채택(adopt)**: `.project-brain-manifest.json`이 파일별로 무엇을
  주입했는지 기록(hwi_PKM 멱등 패턴). 디스크 내용이 렌더 결과와 같으면 채택(adopt) 처리하고,
  사용자가 수정했거나 manifest 밖 파일은 보존한다. `--force`는 manifest에 기록된 사용자 수정만
  덮고, manifest 밖 파일은 force여도 보존.
- **config 누락 키 backfill(footgun 차단)**: config가 없으면 생성, 있으면 보존하되 누락 키 중
  값이 있는 것만 채워 넣는다(기존 키·빈 값은 안 건드림). 빈 값을 기록해버리던 footgun을 막음.
- **2026-07-23 안전 보강**: 템플릿에서 사라진 manifest 관리 파일은 미수정 상태일 때만
  퇴역시킨다. manifest와 새 파일을 먼저 준비하고, 퇴역 원본은 같은 디렉토리의 backup으로
  원자 이동한 뒤 manifest를 확정한다. 중간 이동·manifest 교체가 실패하면 역순 복원한다.
  제어 파일·부모·leaf 심링크/비일반 파일/상위 경로 탈출은 쓰기 전에 거부하고, 내용이 같은
  manifest 밖 스크립트를 채택할 때 실행 비트도 템플릿과 맞춘다. 프로젝트 overlay는 계속
  manifest 밖 소유다.
- 검증: 머지+origin 푸시(`edc2f88..c9eda64`), 합성 537 통과, bb2 채택 19파일 diff 0.
- 계획: [engine-single-source(spec)](docs/plans/2026-06-29-engine-single-source-spec.md) ·
  [engine-single-source(plan)](docs/plans/2026-06-29-engine-single-source-plan.md) ·
  [engine-single-source(decision)](docs/plans/2026-06-29-engine-single-source-decision.md)

### redaction 게이트 정합 + evidence_refs 비대칭 정리 (2026-07-02)
적재 회고 후속 점검에서 두 건 처리. 발단은 "reviewed 결정에 근거가 없다"는 오해였는데, 그 점검이
훨씬 큰 신뢰 라벨 버그를 드러냈다.

- **redaction "none" 함정 (발견·수정).** EvidenceManifest의 `redaction_status`는 라우터
  `_restricted_for`(router.py:758) 화이트리스트에서 `(None,"approved")`만 통과하는데, assembly 기본값이
  spec enum(`raw_local|staged|approved|rejected`)에 없는 문자열 `"none"`이라, bb2 초기 컨텍스트
  manifest 10개를 인용한 객체 **409개**(reviewed 404+candidate 5)가 최고 심각도 `restricted`로
  **오라벨**됐다. 콘텐츠 억제가 아니라 신뢰 라벨만 틀려 골든셋 eval은 통과해와 여태 안 들켰다.
  처리: bb2 데이터 10개 `approved` 교정(엔진 함수로 409→0 실측) + assembly 기본값 **폐지**(미지정=키
  생략→적재가 시끄럽게 거부) + schema에 `REDACTION_STATUS_VALUES` enum 검증(“none”·오타 적재 거부) +
  object-model 게이트 안내. 후속으로 `assemble_notes.py`가 redaction을 안 방출해 기본값 폐지 후 domain
  적재가 전부 거부되던 회귀를 잡아 수정(source마다 `approved` 명시). B2(기본값 approved)·게이트 제거·
  lint 가드는 기각(근거는 plan 참조).
- **evidence_refs 비대칭 정리.** DecisionRecord·Insight의 정본 근거 필드는 `source_object_ids`이고
  `evidence_refs`는 보조 사본이라 빈 값이 정상이다(schema non-empty 강제는 GlossaryTerm·DomainMapping만).
  "근거 없는 reviewed"라는 오판을 막게 문서 3곳(schema.py 주석·object-model DecisionRecord 절·
  completeness-checklist §5)에 못박음. 스키마 규칙 추가·bb2 backfill은 안 함(빈값 게이트는 헛도장).
- 검증: 합성 540 + 템플릿 테스트 11 + installer 14 통과, bb2 실측 가드 5 통과, bb2 전파(install) 완료 —
  모두 메인 에이전트가 직접 재실행. surface(review)가 옵션 실행을 맡았고 메인이 전수 재검증하며 회귀 1건 포착.
- 계획: [decisionrecord-evidence-refs-hygiene](docs/plans/2026-07-01-decisionrecord-evidence-refs-hygiene.md) ·
  [broad-review-findings](docs/plans/2026-07-02-broad-review-findings.md)

### 미결 일괄 결정 + 앵커 근본 방향 + 신뢰 게이트 fail-closed (2026-07-03)
미뤄둔 목록·발견3·럭키박스 앵커를 "미루지 말고 결정" 지시로 일괄 종결(워크플로우 분석 + brain critic 2라운드
검수 [OKAY], critic가 bb2 실코퍼스로 서브에이전트 허위 수치 2건·브리핑 오류 1건 실측 포착).
- **결함 2건 수정(엔진 합성 545 통과):** router `_restricted_for` fail-open→fail-closed(`!= "approved"` —
  수기 manifest 키 누락 시 미승인 근거의 신뢰 오표기 차단) + 발견3(결정 근거 어휘에 slack/spec/wiki 추가 —
  스키마 REF_TYPE_VALUES는 이미 지원, `validate_notes` 하드코딩 튜플도 `_DECISION_REF_TYPE` 참조로).
- **앵커: 근본 방향 "엔티티 명부 기반" 확정** — 빈도 조정 4안 전부 s5 거짓양성 재도입 실측 기각. bb2 골든셋 보강 선행.
- **4건 확정 종결(결함 아님):** 재랭커·Part B·슬래시·stale Step3. **2건 추후 논의 항목:** 팀승격·세션hook. **개인 메모리(L5)는 안 만듦**(handoff·auto-memory·vault 대체).
- 계획·근거·미해결 설계질문: [deferred-items-and-anchor-decisions](docs/plans/2026-07-03-deferred-items-and-anchor-decisions.md)

### 명부 인식 앵커 게이트 — 럭키박스 거짓음성 근본 수정 (2026-07-06)
2026-07-03에 확정한 "엔티티 명부 기반" 방향을 구현. 앵커 게이트가 토큰 빈도(anchor_df)만 보던 것을,
질의가 명부(GlossaryTerm 표면형)의 엔티티와 통째 매칭되면 통과시키는 OR 보강으로 바꿨다. "럭키"·"박스"가
흔한 토큰이라 거짓 차단되던 잘 적재된 엔티티 질의가 열리고, 미적재 엔티티(크리스마스 등)는 명부에 없어
여전히 차단(거짓양성 가드 유지). 빈도 무관이라 코퍼스 성장에 안 무너진다(빈도 조정 4안이 전부 실패한 근본 원인 제거).
- **엔진**: `_gate_pass`에 `registry_match` OR 보강(게이트 = 명부 D1 매칭 OR `anchor_df≤30`, 단조 완화라
  기존 통과 질의 회귀 0) + `compute_query_signals`·`_registry_surfaces`(GlossaryTerm term+synonyms+aliases
  표면형, 길이 3+) + `eval_recall` store 배관. synonyms가 "검색 리콜 보조"에서 **"게이트 통과권"으로 승격**되어
  schema lint(최소 3글자·단독 일반명사 blocklist)와 적재 스킬 규칙에 "누가 '이벤트'를 넣으면 D1이 뚫림" 제약을 박음.
- **검증**: 엔진 합성 556 통과. bb2 실모델 eval **15/15** — 럭키박스 진양성(s16·s17) red→green, 미적재
  no_answer(s5·s13~s15) 차단 유지, 기존 s1~s12 회귀 0. bb2 manifest 전량 approved라 결함 A(fail-closed)의
  restricted 0→0도 실측 확인.
- **백필은 실측 타겟팅**: 27개 컨텍스트 중 이름이 흔한-토큰으로만 이뤄져 핵심 질의가 게이트에 막히던 6개
  (볼셀렉·방해버블·고슴도치·인게임로직·인게임뷰·메인맵)+럭키박스만 백필. 나머지는 자연어 질의로 이미 도달해
  제외(플랜의 "수십 개" 대량 백필 가정을 실측이 축소 — 저가치 churn·거짓열림 표면 증가 회피).
- 반영: 엔진 머지 `ffc84fc`(origin/main) + bb2 `docs/bb2-brain-object-model` 푸시(골든셋·백필 + `bb2-brain-ingest`
  스킬 재install 전파).
- 계획: [registry-aware-anchor-gate](docs/plans/2026-07-06-registry-aware-anchor-gate.md) ·
  [bb2-anchor-golden-set-backfill](docs/plans/2026-07-06-bb2-anchor-golden-set-backfill.md) ·
  방향·근거: [deferred-items-and-anchor-decisions §2](docs/plans/2026-07-03-deferred-items-and-anchor-decisions.md)

### 대량 적재 완료 계약 강화 (2026-07-22~23)

136개 규모 적재와 MPS 메모리 사고에서 드러난 엔진·스킬·installer 경계를 한 번에
보강했다. 판단은 스킬과 사람이 맡되, 재시작·완료·파일 소유권처럼 조용히 틀리면 안 되는
경계는 엔진과 runtime이 fail-closed로 막는다.

- **입력·자원 가드**: 조립 노트의 context/mapping/decision/glossary와 연결 key는 완성
  객체 ID가 아닌 logical key만 허용한다. raw 토큰 근사는 한글과 마크다운 기호를
  보수적으로 세고 과대 단일 유닛을 다시 분할한다. `RealEmbedder`는 배치 8에 더해
  `max_seq_length=2048`을 최종 MPS 메모리 방어선으로 둔다.
- **실행·완료 가드**: `run_ingest.sh --defer-finalize`가 item 적재까지만 수행하고,
  `run_ingest_batch.py`가 manifest 상대경로·fingerprint·baseline·성공/실패 report와
  `--resume`을 관리한다. 모든 item이 성공한 뒤 `finalize_ingest.sh`가 index rebuild,
  lint, eval, graph, corpus tests와 예상 객체 회수를 한 번만 검증한다. workflow는
  최상위 `completed`가 아니라 기대 개수와 각 item의 정확한 `extract_status=ok`,
  `verify_status=ok`를 검사한다.
- **스킬 구조**: ingest `SKILL.md`를 148줄 실행 router로 줄이고 상세 판단은 reference로
  라우팅했다. kind별 갱신 규칙은 ingest의 `references/update-rules.md`가 단일 원본이고,
  session-ingest는 그 파일을 참조한다. 프로젝트 코드 검증은 installer가 소유하지 않는
  선택적 `project-code-verification.md` overlay로 분리했다.
- **installer·batch 안전**: 퇴역 파일 정리와 rollback, 안전 경로 preflight, 실행 비트
  채택, report와 manifest/verify/domain 입력의 동일 경로·심링크 별칭 거부를 회귀로
  고정했다. 새 설치 뒤 2회차는 모든 변경 배열이 비는 멱등 상태다.
- **행동·실코퍼스 검증**: 단건, 부분 실패 workflow, C++ callers 흐름, full-ID logical key
  거부, raw 개정/대량 이름 분기를 재실행 가능한 중립 fixture와 보고서로 남겼다. BB2에서
  문서 7,092·raw chunk 1,577·vector rowid 7,092, lint 0, eval 15/15, 기존 고립 15,
  코퍼스 guard 5/5를 확인했다. 엔진은 pytest 611 + subtests 26, 템플릿 unittest 59를
  통과했다.

- 설계: [bulk-ingest-hardening design](docs/specs/2026-07-21-bulk-ingest-hardening-design.md)
- 계획: [bulk-ingest-hardening plan](docs/plans/2026-07-21-bulk-ingest-hardening.md)
- 행동 증거: [Task 9 report](docs/reports/2026-07-22-bulk-ingest-task9-behavior-evidence.md)
- 최종 결과: [completion report](docs/reports/2026-07-23-bulk-ingest-hardening-completion.md)

### 코드 앵커 SHA 머지 안전 계약 (2026-07-23)

- **원인**: session-ingest에 `머지 정정 때 기본 브랜치 SHA로 교체`라는 무조건형 문장이
  남아 있어, 일반 merge 뒤에도 작업 브랜치 SHA를 버리는 것으로 해석됐다. 이는 이미
  [stale 자동화 계획](docs/plans/2026-06-25-brain-stale-automation-bc.md)에 기록된
  “원커밋 해시를 보존하는 머지는 정정 불필요” 결론과 충돌했다.
- **현재 규칙**: 커밋 SHA 자체는 바뀌지 않는다. fast-forward와 일반 merge 뒤 기존 SHA가
  기본 브랜치의 조상이고 앵커 대상 코드가 같으면 그대로 쓴다. squash·rebase·cherry-pick
  또는 충돌 해결로 SHA 도달 가능성이나 코드가 달라진 경우에만 갱신한다.
- **안전 보강**: config의 기본 브랜치를 판정 기준으로 고정하고, `reviewed`와 미머지
  도달성을 분리했다. Git·정확 인용문 검증 불가 상태는 audit/finalization에서 닫힌 쪽으로
  실패시키며, 색인 재구축은 잠금·검사·원자 교체로 기존 DB를 보존한다.
- **완료 이력**: Project Brain `6bed114`를 `main`에 fast-forward merge·push했다. BB2는
  엔진 installer만 사용해 `4894337958`까지
  `docs/bb2-brain-object-model`에 설치·push했으며, 기존 Brain 객체 재생성·재적재·audit·eval은
  실행하지 않았다.
- 계획: [branch-aware audit hardening plan](docs/superpowers/plans/2026-07-23-brain-ingest-branch-audit-hardening.md)
- 최종 결과: [completion report](docs/reports/2026-07-23-brain-ingest-branch-audit-hardening-completion.md)

### Task 17 canonical ID 복구 — 실코퍼스 적용 완료 (2026-07-31~2026-08-04)

strict ID grammar를 유지한 채 ID-only migration과 제한된 canonical repair를 분리하고,
decision ledger·classification·snapshot·engine·corpus receipt를 서로 묶는 엔진 지원을
구현한 뒤, BB2 실코퍼스에 적용해 **잘못된 객체 이름 158개를 0으로 만들었다.**

- **엔진**: `canonical_repair.py` 신설, `mutation.py`에 `CANONICAL_REPAIR`와 exact diff
  guard. 승인된 collision source를 기존 canonical target에 합치는
  `collision_merge_into_existing`은 source 삭제, survivor/referrer 갱신, 보수적 근거 병합,
  참조 축약 receipt, intermediate 검증, 전체 before/after 복구까지 갖췄다. Task 6 독립
  리뷰의 Major 4건을 세 차례 fix round로 수정하고 최종 재리뷰 Blocker/Major/Minor 0으로
  통과했다.
- **적용**: 두 단계로 나눴다 — canonical repair(이름 5개 변경 + 2개 삭제 + 참조 12곳
  재작성) 다음 ID-only migration(148개 + 참조 71개). 두 경로로 독립 유도한 rename map이
  정확히 일치할 때만 썼다. 예행 2회가 같은 지문을 내고 라이브가 그것을 바이트 단위로
  재현했다. BB2 commit `e28ff4ee7d`(153 renames + 2 deletes + 93 modifications).
- **폐기한 경로**: 맞춤 러너 `run_task17_live.py`(974행)는 회상·eval 점검이 상수를
  돌려주는 가짜 영수증이었고 잠금 교착까지 있어 버렸다. 엔진 공개 API만 조합한
  569행 `run_migration.py` + 테스트 15개로 대체했다. 그 안의 안전장치 네 가지와
  엔진 흡수 조건은 아래 미뤄둔 작업 7번에 있다.
- **마무리(2026-08-04)**: audit을 막고 있던 symbol 불일치 5건을 4 대 1로 갈라 해결했다.
  4건은 라벨이 정확한데도 실패한 거짓 경보라 엔진에 몸통 규칙을 넣었고(`ab27a9c`),
  1건은 인용문이 라벨과 다른 함수 안에 있던 진짜 데이터 오류라 라벨을 고쳤다.
  이 과정에서 드러난 읽기/쓰기 비대칭은 미뤄둔 작업 8번에 기록했다.
- **최종 상태**: `audit ok=true`(lint 0, 참조 3809 intact, symbol mismatch 0),
  엔진 pytest 1522 + ingest runtime 99, 실코퍼스 checks 10(건너뜀 0), eval 15/15,
  색인 7,884개(mecab-ko + bge-m3). 최종 스냅샷 `ad657ec5…`(11,132 파일) 검증 통과,
  Task 18 연결점 `135ce054…` 고정. engine `148c9e7d`.
- **미충족 1건**: recovery bundle을 BB2 commit에 넣는 항목은 사용자가 brain 공유 방식을
  바꾸기로 해 보류했다. 파일은 `bb2 brain/recovery/`에 있고 그 폴더 README와 아래 7번에
  경위를 적었다.
- 설계: [Task 17 설계](docs/superpowers/specs/2026-07-31-task17-canonical-id-recovery-design.md) ·
  [collision merge 설계](docs/superpowers/specs/2026-08-02-task17-collision-merge-design.md)
- 마무리 계획: [몸통 규칙 + Task 13](docs/plans/2026-08-04-symbol-verify-body-scope-and-task13.md)

---

## 미뤄둔 작업 (최종 관리)

각 항목은 "왜 미뤘는가 / 착수 트리거"를 함께 적는다. 트리거가 없으면 착수하지 않는다.

> 아래 재랭커·Part B·슬래시·stale Step3는 2026-07-03에 "결함 아님"으로 확정 종결됐고(열린 대기가
> 아니라 근거 댄 종결), 팀승격·세션hook은 추후 논의 항목으로 남긴다. 개인 메모리(L5)는 안 만들기로
> 확정(2026-07-06, 외부 도구 대체 — 상세 [design-canonical §4](docs/design-canonical.md)). 프레임·근거: [2026-07-03 결정문](docs/plans/2026-07-03-deferred-items-and-anchor-decisions.md).

1. **top-K 상수·재랭커(cross-encoder) 필요성 재평가**
   - 상태: 보류. 실사용 회상 실패 증거가 벤치마크 1건뿐이라 도입 안 함.
   - 트리거: scope-None 넓은 질의에서 핀포인트 순위 회귀가 반복될 때. 선행 조건 = 골든셋
     s8(scope-None 시나리오) 신설 + red 측정. red 없이 도입 금지.
   - 근거: scoped BM25가 scope 특정 질의는 이미 해결 → 재랭커는 역할 비중첩 영역만.
   - 2026-06-26 실측: 도메인·언어 갭의 색인 측 보강은 **GlossaryTerm 동의어**가 일부 흡수(완료
     단계 참고) — 단 효과가 고유 등가어에 한정·무해 확인. 재랭커는 여전히 "후보엔 들어왔으나
     순서가 나쁜" 비중첩 영역만 남으며, 그 영역 측정용 s8 골든셋이 선행이라는 결론 불변.

2. **세션 종료 hook 저장 제안 기능** (미결 6)
   - 상태: 추후 논의 항목. 세션 끝에서 "저장할까요?" 제안하는 형태·시점 미정.

3. **팀 공개 — reviewed 승격 권한 결정** (미결 5)
   - 상태: 추후 논의 항목 — 혼자 시험 제작 단계라 미정. 각자 promote vs 검수자 지정.
   - 동반 작업: install 측 인프라는 단일원본 작업(2026-06-29, 완료 단계 참고)으로 **이미 완료**.
     install이 `templates/<skill>/` 디렉토리를 통째 walk해 `SKILL.md`·`references/`·`scripts/`를
     다 주입하고 manifest로 보존·채택한다(과거 "SKILL.md만 주입·references/scripts 미주입"은 옛 상태).
     목표는 범용화/추상화가 아니라 "관리 주체 1곳"이며, 소비처가 bb2뿐이라 도메인 예시는 리터럴로
     둔다. 팀 공개 시 남는 건 승격 권한 정책 결정이지 미주입 인프라가 아니다.
   - 트리거: 사용자가 팀 공개를 결정할 때.

4. **locator 위치 갱신 / 기존 데이터 정비 (Part B)**
   - ⚠️ `commit_sha`와 줄번호는 **별개 필드**다(혼동 주의). `commit_sha`(변경 감지 기준점,
     stale-check/audit이 `(path, commit_sha)`로 판정)는 **필수**라 백필 완료(bb2 842/842).
     아래 "재백필/삭제 보류"는 오직 `line_start`/`line_end`(엔진이 안 읽는 칸) 얘기다.
   - 순수 줄번호 재백필: **영구 보류**. 엔진이 line_start/end를 검색·회상 어디서도 읽지
     않아 line drift가 회상에 무해함을 실측으로 확인(object-model 철학 검증 완료).
   - **신규 데이터는 완료(2026-06-24)**: `build`가 책갈피(EvidenceRef) locator를 짝
     CodeLocator의 번호표(`code_locator_id`)로 **저장**하고, 줄번호(line_start/end)는 더
     이상 안 넣음 — 신규 코드 근거의 drift를 발원지에서 차단(완료 단계 참고).
   - **남은 Part B = 기존 코퍼스 일괄 변경(미룸)**: 옛(레거시) 데이터의 좌표 복사
     locator(문자열·객체)를 번호표(`code_locator_id`)로 통일하고, 거기 남은 줄번호는 함께
     제거하는 마이그레이션(신규 데이터는 이미 번호표라 줄번호 없음). **실익 0**(그 칸은 색인·회상·랭킹·
     답변 어디서도 안 읽힘)이고 Part A가 신규 drift를 이미 막아 미룸. route 판정 BLOCK —
     532건 중 단일 번호표로 구조적 불가 ~45건(멀티좌표 자유텍스트 ~39 + orphan 6)이라 전수
     유일 짝짓기 가정이 깨짐(복수참조 `code_locator_ids` 모델 결정이 선행). 상세·짝짓기 실측은
     계획 Part B에 보존.
     - **착수 방아쇠: locator 좌표를 실제로 읽는 기능(답변에 `파일:줄` 표시·점프 등)이
       엔진에 생길 때.** 그 전엔 착수하지 않는다.
   - "코드 변경→매핑 의미 갱신 대상 발견"은 별개 니즈 — 추출(stale-check)·해소(mark-checked)는
     이미 됨(§6로 분리). **완전 자동(사람·적대검증 무개입) supersede·hook은 안 하되**, B+C
     게이트(확실 자동 / 모호 query 확인)로 잇는 설계는 §6 참고.

5. **스킬·슬래시 커맨드 라인업 결정**
   - 상태: 후순위 작업 전부 완료한 뒤로 명시 보류. 현재 자동 진입점은 스킬 description뿐.
   - 입력: pkm 비교(스킬 3 + install/init 슬래시) 참고.

6. **stale 자동화 — B+C 검수 모델에 코드변경 트리거 잇기**
   - 상태: 설계 확정. 추출(`stale-check`)·해소(`mark-checked`)는 이미 구현·실코퍼스 검증.
     **Step 1·2(엔진) ✅ 구현(2026-06-25, 완료 단계 참고)** — 미머지 앵커 라벨 + query/show
     "코드 변경" 노출(C). **남은 것 = Step 3(B)**: 에이전트가 diff 읽고 확실-불변 자동 갱신 /
     변경은 supersede 초안. 정밀화는 엔진 파서 아니라 에이전트 몫(줄번호 제거로 엔진은
     hunk→symbol 못 이음, bb2 84% 클러스터링 실측) — 실코퍼스 회귀 필요라 보류.
   - 부수 요건(실코퍼스 발견) ✅ 해결(Step 1): stale-check이 "앵커 커밋이 config의 `default_branch` 조상 아님
     (미머지 적재)"을 삭제/변경과 별개 `unmerged_anchors`로 구분 표시해 거짓 stale를 안 낸다
     (bb2는 머지 커밋·직접 푸시 모두 원커밋 해시 보존=스쿼시/리베이스 아님이라 머지되면 자동 해소).
   - Step 3 착수 트리거: stale 수동 triage가 실제로 거슬릴 때.
   - 설계 정본: [stale-automation-bc](docs/plans/2026-06-25-brain-stale-automation-bc.md) ·
     Step 1·2 계획: [stale-step1·2 impl](docs/plans/2026-06-25-brain-stale-step12-impl-plan.md).

7. **Task 17 복구 번들 — 어디에 두고 무엇을 엔진으로 흡수할지** (2026-08-04 판정)

   BB2 이름표 158개 정비에 쓴 도구·근거 12개 파일을 어디에 둘지 정한 기록이다.
   전부 `bb2_client/brain/recovery/` 아래에 **파일로만** 있다.

   - **왜 BB2에 두는가 (8개)** — BB2 객체가 코드·데이터에 직접 박혀 있어 다른
     프로젝트에서 의미가 없다. `scan_task17.py:50-52`에 `evref.petskill-kamehameha.
     jira-LGBBTWO-234` 같은 BB2 객체 이름이 하드코딩돼 있고, Phase A 측정·분류·판정
     3개와 결정 대장 156건, 정본수리 manifest·예행보고는 전부 BB2 객체 158개에 대한
     구체적 값이다. 2-레포 모델이 정한 "데이터·적재 이력은 데이터 레포" 그대로다.

   - **왜 엔진으로 안 옮기는가 (2개)** — `2026-08-03/task17-migration/run_migration.py`
     (569행)와 그 테스트 15개는 성격이 다르다. **BB2라는 문자열이 하나도 없고**
     경로·해시를 전부 설정으로 받으며 엔진 공개 API만 조합한다. 즉 엔진 자산 성격이
     맞다. 그런데도 지금 옮기지 않는 이유는, 일회성 실행 스크립트를 그대로 복사하면
     엔진에 아무도 안 쓰는 코드가 쌓이기 때문이다. 진짜 자산은 파일이 아니라 그 안의
     **안전장치 네 가지**다.

     1. 잠금은 하나만 잡고, 하위 프로세스를 부르는 점검은 잠금 **밖**에 둔다.
        폐기한 러너가 정확히 여기서 교착에 걸렸다(잠금을 쥔 채 자식이 같은 잠금 대기).
     2. 아직 아무것도 안 썼으면 되돌리지 않는다. 되돌리기는 첫 쓰기 이후 정확히 한 번.
     3. 색인을 무효화하는 점검은 되돌리기 범위 **밖**에 둔다. TDD가 이 결함을 잡았다 —
        안 그랬으면 성공한 마이그레이션을 실패로 보고 되돌릴 뻔했다.
     4. 바꿀 이름 목록을 서로 다른 두 경로(코퍼스 구조 / 승인된 대장)로 각각 유도해
        정확히 일치할 때만 쓴다.

     이 네 가지는 복사가 아니라 엔진 기능(CLI 명령이나 모듈)으로 흡수해야 살아난다.

   - **왜 폐기한 것을 남겨뒀는가 (2개)** — `run_task17_live.py`(974행)와 그 테스트는
     2026-08-03에 버린 경로다. 회상·eval 점검이 상수를 돌려주는 가짜 영수증이었다.
     데이터 레포에 정식으로 남기면 다음 사람이 "이게 그 도구구나" 하고 잘못 쓸 수
     있어 보존 대상에서 뺐지만, 파일 자체는 지우지 않고 그대로 둔다. 왜 버렸는지가
     이 문단과 `run_migration.py` 첫 주석에 남아 있다.

   - **왜 git에 안 넣었는가** — BB2의 `.git/info/exclude`에 `/brain`이 통째로 있어
     이 파일들은 `git status`에도 안 뜬다. 넣으려면 `-f`가 필요하다. 2026-08-04에
     사용자가 **brain 공유 방식을 바꿀 예정이라 지금은 커밋하지 않기로** 결정했다.
     ⚠️ 그래서 이 12개는 지금 git 밖에 있다 — 폴더를 지우거나 머신을 옮기면 사라진다.
     공유 방식이 정해지면 그 방식으로 보존한다.

   - **착수 방아쇠**: 다른 데이터 레포에서 대량 이름표 정비가 또 필요해질 때. 그때
     `run_migration.py`를 복사하지 말고 위 안전장치 네 가지를 엔진 기능으로 흡수한다.
     그 전엔 착수하지 않는다.

8. **재검증이 필요한 옛 앵커 수정의 읽기/쓰기 비대칭** (2026-08-04 실측)

   `--3` 하나를 고치려다 드러난 사실이다. 읽기 쪽은 옛 데이터를 받아주지만,
   `repo`·`path`·`commit_sha` 좌표나 `symbol`·`verified_quote`를 바꾸거나 `mark-checked`를
   실행하면 쓰기 쪽의 현재 검증 계약을 통과해야 한다. **모든 옛 객체 수정이 막히는 것은
   아니다.** 이 필드가 그대로인 변경은 legacy 축약 SHA·quote를 보존할 수 있다. Task 18은
   이 경계를 우회한 일반 수정이 아니라, 다른 필드를 그대로 보존하는 title-only 전용
   `DISPLAY_MIGRATION` 경로였다.

   - **벽 1 — 축약 commit_sha**: 재검증 경로의 쓰기 층은 40자(또는 64자) 전체 SHA를 요구한다
     (`mutation.py` 좌표 검증). 2026-08-04 최초 측정에서 BB2 앵커 3,809개 중
     **3,294개(86%)가 10자 축약형**, 40자는 515개였다. 2026-08-11 현재는 10자 3,293개,
     40자 516개이며 현재 일괄 정규화 대상은 3,293개다. 즉 이 옛 앵커가 재검증 대상이 되면
     `commit_missing: locator commit_sha is not an exact hexadecimal SHA`로 거부된다.
     읽기 쪽(audit·stale-check)은 축약형을 그대로 해석해 잘 돈다.

   - **벽 2 — 미머지 커밋 도달 가능성**: `code_verify.py:142`가
     `git merge-base --is-ancestor <앵커 커밋> <기준 ref>`로 검사해, 기본 브랜치에서
     도달할 수 없으면 `commit_not_reachable`로 거부한다. 읽기 쪽은 정반대다 —
     audit이 이런 앵커를 `stale.unmerged_anchors`(`reason: not_ancestor`, 현재 40건)로
     **표시만 하고 실패로 치지 않는다.** 같은 상황을 읽기는 정상으로, 쓰기는 오류로
     본다.

   - **지금 쓸 수 있는 우회**: `--expected-revision-ref <그 커밋이 있는 브랜치>`를
     주면 기준이 바뀌어 통과한다. 실제로 `--3`은
     `--expected-revision-ref side/ingame-resolution`으로 고쳤다. 다만 이건 고치는
     사람이 "이 앵커가 어느 브랜치 것인지" 미리 알아야 쓸 수 있다 — 카드에는 그
     정보가 없고 `git branch --contains`로 직접 찾아야 한다.

   - **왜 지금 안 고치는가**: 벽 1을 없애려면 현재 3,293개를 일괄 변환해야 하는데, 같은
     커밋의 다른 표기로 바꾸는 것이라 의미 변화는 없지만 코퍼스 대부분을 건드린다.
     벽 2는 "미머지 앵커를 쓰기에서 어떻게 다룰지"라는 정책 결정이 먼저다 —
     읽기처럼 표시만 하고 통과시킬지, 브랜치를 카드에 적게 할지, 지금처럼 호출자가
     ref를 대게 할지. 실익 대비 범위가 커서 미룬다.

   - **착수 방아쇠**: 좌표·symbol·quote 재검증이나 `mark-checked`가 반복해서 이 벽에
     걸릴 때. 특히 미머지 브랜치 앵커를 정기적으로 손봐야 하면 벽 2부터 정한다. 그 전엔
     좌표가 그대로인 변경은 legacy 값을 보존하고, 재검증이 필요한 건 위 우회로 개별 처리해
     어느 브랜치를 기준으로 썼는지 기록에 남긴다.

미결 사항 상세는 [docs/design-canonical.md §4](docs/design-canonical.md)를 본다.
