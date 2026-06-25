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
| L4 적재 | ✅ 3경로 완성 | 소급 / 개발 중 / 과거 세션 추출 + `build` 조립 자동화 |
| 재사용층(projection) | ✅ 구현·검증·push (2026-06-17) | 착수 브리핑 `projection_reuse` 재회수 + 해시 시각필드 제외·`projection refresh` (2026-06-24) |
| 코드 변경 안전망 | ✅ stale-check / mark-checked (2026-06-15) | 읽기 전용 후보 제시 · 갱신 대상은 commit_sha/verified_at(줄번호는 저장 안 함) |
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

---

## 미뤄둔 작업 (최종 관리)

각 항목은 "왜 미뤘는가 / 착수 트리거"를 함께 적는다. 트리거가 없으면 착수하지 않는다.

1. **top-K 상수·재랭커(cross-encoder) 필요성 재평가**
   - 상태: 보류. 실사용 회상 실패 증거가 벤치마크 1건뿐이라 도입 안 함.
   - 트리거: scope-None 넓은 질의에서 핀포인트 순위 회귀가 반복될 때. 선행 조건 = 골든셋
     s8(scope-None 시나리오) 신설 + red 측정. red 없이 도입 금지.
   - 근거: scoped BM25가 scope 특정 질의는 이미 해결 → 재랭커는 역할 비중첩 영역만.

2. **L5 개인 메모리 층** (미결 7)
   - 상태: 설계상 자리만. 단기(작업 연속성)/장기(개인 교훈·선호) 구조 미설계.
   - 트리거: 1차 목표(팀 공유 가능 코어) 완료 후. 기존 도구(handoff·auto-memory·vault
     task)와의 관계 정리가 설계 입력.

3. **세션 종료 hook 저장 제안 기능** (미결 6)
   - 상태: 후순위. 세션 끝에서 "저장할까요?" 제안하는 형태·시점 미정.

4. **팀 공개 — reviewed 승격 권한 결정** (미결 5)
   - 상태: 혼자 시험 제작 단계라 미정. 각자 promote vs 검수자 지정.
   - 동반 작업: 스킬 범용화(엔진 install이 주입하는 `SKILL.md` 2개 외에 `references/`·
     session-ingest는 미주입 — 범용화는 삭제가 아니라 추상화, 맞춤은 설치 후 실사용으로).
   - 트리거: 사용자가 팀 공개를 결정할 때.

5. **locator 위치 갱신 / 기존 데이터 정비 (Part B)**
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
   - 상태: 설계 확정·보류. 추출(`stale-check`)·해소(`mark-checked`)는 **이미 구현·실코퍼스
     검증**(새 코드 없음). 남은 자동화 = B(에이전트가 diff 읽고 확실-불변 자동 갱신 / 변경은
     supersede 초안) + query 시점 "확인 필요: 코드 변경" 노출(C). 정밀화는 엔진 파서 아니라
     에이전트 몫(줄번호 제거로 엔진은 hunk→symbol 못 이음, bb2 84% 클러스터링 실측).
   - 부수 요건(실코퍼스 발견): stale-check이 "앵커 커밋이 develop 조상 아님(미머지 적재)"을
     삭제/변경과 구분 표시해야 거짓 stale를 안 낸다(bb2는 머지 커밋·직접 푸시 모두 원커밋 해시
     보존=스쿼시/리베이스 아님이라 머지되면 자동 해소, commit_sha 정정 불필요).
   - 트리거: stale 결과 수동 triage가 거슬리거나 query 노출이 필요해질 때.
   - 설계 정본: [stale-automation-bc](docs/plans/2026-06-25-brain-stale-automation-bc.md).

미결 사항 상세는 [docs/design-canonical.md §4](docs/design-canonical.md)를 본다.
