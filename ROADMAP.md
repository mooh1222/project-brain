# project-brain — 로드맵 / 히스토리

검수 상태·근거가 붙은 객체 코퍼스 + 한국어 하이브리드 검색 + 조회/적재 CLI를 갖춘
**범용 프로젝트 브레인 엔진**의 발전 단계와 미뤄둔 작업을 한 곳에서 관리한다.

- 설계 근거(정체성·철학·아키텍처·미결): [docs/design-canonical.md](docs/design-canonical.md)
- 설치·사용: [README.md](README.md) · 개발 루프: [CLAUDE.md](CLAUDE.md)
- 단계별 설계/계획 문서: `docs/specs/`(18) · `docs/plans/`(28) · `docs/skill-drafts/`(3)
- 데이터·적재 이력은 각 프로젝트 레포(`brain/`)에 있다. 이 로드맵은 **엔진 기능**만 다룬다.
  BB2(첫 데이터) 적재 작업 추적은 vault task `bb2-project-brain-build`에 남아 있다.

> 출처 메모: 이 엔진은 BB2 게임의 내부 도구로 출발해 2026-06-11 범용 엔진으로 분리됐다.
> 설계 문서 파일명의 `bb2-brain-` 접두사는 그 출발을 그대로 보존한 것이다(본문에 BB2
> 사례가 섞여 있어 이름만 바꾸면 오히려 불일치).

---

## 현황 (층별)

| 층 | 상태 | 비고 |
|---|---|---|
| L1 저장 엔진 | ✅ 완료 수준 | 18 kind + Insight·원자성 적재·promote·lint |
| L1 인사이트 그릇 | ✅ `Insight` kind (2026-06-15) | advisories 별도 통로·candidate 적재 거부(1차) |
| L0 raw 보관 | ✅ 있음 | `raw/sources/<context>/` 텍스트 추적·locator brain root 상대 |
| L2 검색 색인 | ✅ 있음 | FTS5 BM25 + bge-m3 벡터 + RRF + 그래프 재정렬 + scoped BM25 + raw 색인 |
| L3 라우터·회상 | ✅ 통합 | 정확 매칭 1순위 + 의미 보강 + unknown 일반 회상 + `cli search` |
| L4 적재 | ✅ 3경로 완성 | 소급 / 개발 중 / 과거 세션 추출 + `build` 조립 자동화(decisions[] 결정 조립 2026-06-26) + GlossaryTerm 동의어 통로(신규 적재분, 2026-06-26) |
| 재사용층(projection) | ✅ 구현·검증·push (2026-06-17) | 착수 브리핑 `projection_reuse` 재회수 + 해시 시각필드 제외·`projection refresh` (2026-06-24) |
| 코드 변경 안전망 | ✅ stale-check / mark-checked (2026-06-15) · 미머지 앵커 라벨 + query/show 노출 (2026-06-25) | 읽기 전용 후보 제시 · 갱신 대상은 commit_sha/verified_at(줄번호는 저장 안 함) · `--write-cache`→query advisory |
| 그래프 무결성·고립 | ✅ `graph isolated` + build 경고 + `graph export` (2026-06-24) | 인바운드 0 잎 탐지·vis-network 시각화 HTML·엣지 정본 단일 출처 |
| 공유 경계 | ✅ 엔진/데이터 2-레포 분리 (2026-06-11) | brain/ git 추적·색인만 로컬 |
| L5 개인 메모리 | ⬜ 없음 | 설계상 자리만 (미뤄둠) |

---

## 완료 단계

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
분리) + `raw_excerpts` 채널. store 재사용 주입, `cli query` 배선.

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
정의(`graph.edges` = INBOUND_REF_FIELDS, 외부 키 제외)를 써서 "어떤 잎이 왜 고립인지"가
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
변경(Part B)은 실익 0 + 짝짓기 구조적 불가 ~45건으로 미룸(미뤄둔 작업 §5).

- 계획(확정본·결정 로그·Part B 보류 근거): [code-evidence-cleanup](docs/plans/2026-06-24-brain-code-evidence-cleanup.md)

### stale 자동화 Step 1·2 — 미머지 앵커 라벨 + query/show 노출 (2026-06-25)
설계(보류했던 자동화, 미뤄둔 작업 §7)의 **엔진 부분만** 구현. Step 3(에이전트 diff 자동
정리)은 실코퍼스 회귀가 필요해 보류 유지.
- **Step 1 — 미머지 앵커 라벨**: `stale-check`이 `git merge-base`로 앵커 `commit_sha`가
  origin/develop 조상인지 판정해, 조상 아니면(PR 머지 전 작업 브랜치 커밋) candidate에서 빼고
  새 키 `unmerged_anchors`(차단 아니라 라벨)로 분리. bb2 실행에서 본 거짓 'D'(삭제) 신호를
  근원 제거(머지되면 자동 해소). 약식 sha는 `base.startswith(from_commit)` prefix 비교로 처리.
- **Step 2 — query/show 노출**: `stale-check --write-cache`가 stale-set을
  `.brain-local/stale-set.json`(색인과 같은 재생성 파생물)에 떨구고, `query`/`show`가 읽어
  매핑별 `stale_advisory`(코드 변경 감지 + 기준 시점)를 곁들인다. 파일 IO는 CLI, router는
  주입된 dict만 소비(git·파일 모름 — `git_runner` 주입과 같은 패턴). 캐시 없으면 동작 불변.
- 검증: 합성 519 통과(신규 13), 3렌즈 적대 검증 correctness·regression clean. 실코퍼스 회귀는
  데이터 레포에서 별도(아래 주의). 계획: [stale-step1·2 impl](docs/plans/2026-06-25-brain-stale-step12-impl-plan.md).

### 코퍼스 건강검진 checkup — stale 캐시 도는 주체 (2026-06-28)
Step 2가 읽기(`query`/`show`)·쓰기(`stale-check --write-cache`) 양끝을 만들었으나 **캐시를
채울 주체가 없어** stale_advisory 채널이 죽어 있던 갭을 메움. `project-brain checkup`이
`lint`(무결성) + `graph isolated`(고아 잎) + `stale-check --write-cache`(코드 드리프트)를 한
패스로 돌려 캐시를 채운다 — 셋은 "코퍼스 건강검진"이라는 같은 결이라 묶음. 관리 스킬
`checkup.md`(install 주입 4번째)로 어시스턴트가 develop 당긴 뒤·대량 적재 후 돌린다. 후보
처리는 검수 정책 B+C(자동 supersede 없음 — Step 3 여전히 보류, 에이전트가 advisory 보고 판정).
- 검증: 합성 530 통과(신규 checkup 1), 적대 검증 OK. 실 bb2 종단(checkup→캐시 45건→`show`
  stale_advisory 실회수)로 죽은 채널 부활 입증.
- 데이터레포 backlog의 2026-06-12·13 항목(line drift 무해 + "코드변경→의미갱신 발견" 별개
  니즈)이 이 기능의 설계 입력이었고, 이제 stale-check+checkup으로 실현돼 그 항목들은 졸업.

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

---

## 미뤄둔 작업 (최종 관리)

각 항목은 "왜 미뤘는가 / 착수 트리거"를 함께 적는다. 트리거가 없으면 착수하지 않는다.

1. **top-K 상수·재랭커(cross-encoder) 필요성 재평가**
   - 상태: 보류. 실사용 회상 실패 증거가 벤치마크 1건뿐이라 도입 안 함.
   - 트리거: scope-None 넓은 질의에서 핀포인트 순위 회귀가 반복될 때. 선행 조건 = 골든셋
     s8(scope-None 시나리오) 신설 + red 측정. red 없이 도입 금지.
   - 근거: scoped BM25가 scope 특정 질의는 이미 해결 → 재랭커는 역할 비중첩 영역만.
   - 2026-06-26 실측: 도메인·언어 갭의 색인 측 보강은 **GlossaryTerm 동의어**가 일부 흡수(완료
     단계 참고) — 단 효과가 고유 등가어에 한정·무해 확인. 재랭커는 여전히 "후보엔 들어왔으나
     순서가 나쁜" 비중첩 영역만 남으며, 그 영역 측정용 s8 골든셋이 선행이라는 결론 불변.

2. **L5 개인 메모리 층** (미결 7)
   - 상태: 설계상 자리만. 단기(작업 연속성)/장기(개인 교훈·선호) 구조 미설계.
   - 트리거: 1차 목표(팀 공유 가능 코어) 완료 후. 기존 도구(handoff·auto-memory·vault
     task)와의 관계 정리가 설계 입력.

3. **세션 종료 hook 저장 제안 기능** (미결 6)
   - 상태: 후순위. 세션 끝에서 "저장할까요?" 제안하는 형태·시점 미정.

4. **팀 공개 — reviewed 승격 권한 결정** (미결 5)
   - 상태: 혼자 시험 제작 단계라 미정. 각자 promote vs 검수자 지정.
   - 동반 작업: 스킬 범용화(엔진 install이 주입하는 `SKILL.md` 4개(query/ingest/session-ingest/checkup)
     외에 `references/`·`scripts/`는 미주입 — 범용화는 삭제가 아니라 추상화, 맞춤은 설치 후 실사용으로).
   - 트리거: 사용자가 팀 공개를 결정할 때.

5. **locator 위치 갱신 / 기존 데이터 정비 (Part B)**
   - ⚠️ `commit_sha`와 줄번호는 **별개 필드**다(혼동 주의). `commit_sha`(변경 감지 기준점,
     stale-check/checkup이 `(path, commit_sha)`로 판정)는 **필수**라 백필 완료(bb2 842/842).
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
     이미 됨(§7로 분리). **완전 자동(사람·적대검증 무개입) supersede·hook은 안 하되**, B+C
     게이트(확실 자동 / 모호 query 확인)로 잇는 설계는 §7 참고.

6. **스킬·슬래시 커맨드 라인업 결정**
   - 상태: 후순위 작업 전부 완료한 뒤로 명시 보류. 현재 자동 진입점은 스킬 description뿐.
   - 입력: pkm 비교(스킬 3 + install/init 슬래시) 참고.

7. **stale 자동화 — B+C 검수 모델에 코드변경 트리거 잇기**
   - 상태: 설계 확정. 추출(`stale-check`)·해소(`mark-checked`)는 이미 구현·실코퍼스 검증.
     **Step 1·2(엔진) ✅ 구현(2026-06-25, 완료 단계 참고)** — 미머지 앵커 라벨 + query/show
     "코드 변경" 노출(C). **남은 것 = Step 3(B)**: 에이전트가 diff 읽고 확실-불변 자동 갱신 /
     변경은 supersede 초안. 정밀화는 엔진 파서 아니라 에이전트 몫(줄번호 제거로 엔진은
     hunk→symbol 못 이음, bb2 84% 클러스터링 실측) — 실코퍼스 회귀 필요라 보류.
   - 부수 요건(실코퍼스 발견) ✅ 해결(Step 1): stale-check이 "앵커 커밋이 develop 조상 아님
     (미머지 적재)"을 삭제/변경과 별개 `unmerged_anchors`로 구분 표시해 거짓 stale를 안 낸다
     (bb2는 머지 커밋·직접 푸시 모두 원커밋 해시 보존=스쿼시/리베이스 아님이라 머지되면 자동 해소).
   - Step 3 착수 트리거: stale 수동 triage가 실제로 거슬릴 때.
   - 설계 정본: [stale-automation-bc](docs/plans/2026-06-25-brain-stale-automation-bc.md) ·
     Step 1·2 계획: [stale-step1·2 impl](docs/plans/2026-06-25-brain-stale-step12-impl-plan.md).

미결 사항 상세는 [docs/design-canonical.md §4](docs/design-canonical.md)를 본다.
