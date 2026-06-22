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
| 재사용층(projection) | ✅ 구현·검증·push (2026-06-17) | 착수 브리핑을 `projection_reuse` 채널로 재회수 |
| 코드 변경 안전망 | ✅ stale-check / mark-checked (2026-06-15) | 읽기 전용 후보 제시·줄번호 갱신 아님 |
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

5. **locator 위치 갱신**
   - 순수 줄번호 재백필: **영구 보류**. 엔진이 line_start/end를 검색·회상 어디서도 읽지
     않아 line drift가 회상에 무해함을 실측으로 확인(object-model 철학 검증 완료).
   - "코드 변경→매핑 의미 갱신 대상 발견"은 별개 니즈 — stale-check/mark-checked로 일부
     해소됨. 자동 코드 의미 비교·자동 supersede·hook은 하지 않는다.

6. **스킬·슬래시 커맨드 라인업 결정**
   - 상태: 후순위 작업 전부 완료한 뒤로 명시 보류. 현재 자동 진입점은 스킬 description뿐.
   - 입력: pkm 비교(스킬 3 + install/init 슬래시) 참고.

미결 사항 상세는 [docs/design-canonical.md §4](docs/design-canonical.md)를 본다.
