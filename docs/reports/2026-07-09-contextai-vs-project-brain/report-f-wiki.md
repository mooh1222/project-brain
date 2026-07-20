# ContextAI 위키 트리 분석 보고서

**전제(중요):** 아래 내용은 전부 사내 Confluence 위키(space `cloudsg`) 본문에서만 뽑은 것이다. 나는 ContextAI 코드베이스(`git.linecorp.com/Cloud-Native/context-ai`)를 직접 열지 않았다. 따라서 모든 아키텍처·상태 서술은 **위키 문서상 주장**이며, "코드에서 직접 실증한 사실"은 이 보고서에 없다. 저장소 코드 대조는 이 산출물을 받는 다음 단계에서 해야 한다. 계획/논의 중인 것과 "운영 중이라고 문서가 주장하는 것"은 아래에서 명확히 구분했다. 문서 간 상태가 어긋나는 지점(특히 IMON)은 따로 짚었다.

---

## 1. 현재 릴리스 / 사용 가능 상태

핵심은 두 가지 "제품"이 겹쳐 있다는 점이다. 위키를 보면 이 둘의 성숙도가 크게 다르다.

### (A) 독립 사내 서비스로서의 ContextAI — 이미 라이브
`ContextAI: 엔지니어링 컨텍스트 플랫폼`(4288512925) 본문의 "맡는 영역과 현재 상태" 표가 가장 명확한 상태 근거다(문서상 주장):

| 영역 | 문서상 상태 |
| --- | --- |
| 위키·코드·텍스트 묶음 + 웹 챗 | **운영 중 — 2026-05-12 정식 오픈** |
| AI 에이전트 연동(MCP) | **운영 중 — 2026-06-10 출시, 보안 심사 완료** |
| 질의 시점 권한 체크 | 운영 중 |
| 사내 메트릭(IMON) | **보안 심사 진행 중** |
| Kubernetes · 로그 | 보안 심사 후 순차 공개 — 베타 환경 실증 완료 |

- 누가 지금 쓸 수 있나: **사내 인증(CorporateIdP OIDC) 통과한 모든 사용자.** 서비스 URL은 `https://context-ai.workers-hub.com`(Prod)이며, Master/Stage 개발 환경도 따로 있다(`ContextAI - Resources` 4076503934). 라이브 Binder 예시 ID `01KRATN47T9SS25K7F4BH1EST7`가 여러 연동 문서에 데모 링크로 박혀 있다.
- Prod는 FKE 클러스터 `prod-kks`(기타큐슈 리전) 위에서 돈다(Resources 페이지).
- 보안 심사 완료(문서상): App Security Design Review(SIMS-148038), Security Assessment(SIMS-148037), MCP Export ASDR(SIMS-149629). 추가로 생성AI 이용상담 GENAICONTACT-2080, DD 리뷰 CONSULTINGDD-157(`ACL Control (JP)` 4423368192).

**상태 불일치(반드시 검증 필요):** 전략 페이지(4288512925)는 IMON을 "보안 심사 진행 중"이라고 적었는데, `Backend Daily Meeting`(3987332546) 6/22~6/23 기록에는 **"IMON Prod 배포"**(CLOUDNATIVE-3481)가 완료로 나오고 유저가이드·릴리즈노트까지 작성·테스트했다고 되어 있다. 즉 IMON 메트릭은 실제로는 6/23경 Prod에 나간 것으로 보이고, 공개용 전략 페이지(버전 5)가 그 시점보다 뒤처졌을 가능성이 크다. "IMON = 심사 중"으로 단정하면 안 된다.

### (B) 정식 Flava Product로서의 ContextAI — 초기 준비 단계
`06. Release` 하위 `Readiness Checklist (Dev)`(4321627581)는 (A)와 별개다. 이건 ContextAI를 **Flava 플랫폼의 정식 상품**으로 올리기 위한 Dev 환경 준비 체크리스트다.
- 맨 위 로그: **"7/8 — 프로젝트 킥오프 진행, FE/QA 팀과 일정 논의. 현시점 이슈 없음."** 즉 정식 상품화는 이제 막 킥오프한 상태.
- 체크리스트 대부분이 `YellowTODO`다. HA/Multi-AZ/DR, SLI·SLO, 백업, 감사로그, 온콜, 미터링, 보안 어세스먼트, CI/CD, 유저가이드, Backoffice API 등이 전부 TODO.
- 진행 중(Green IN PROGRESS): User API(Mock API 제공 예정), C-plane Stage 배포.
- 아예 해당 없음으로 적힌 항목이 제품 형태를 드러낸다: **"No CLI", "No D-plane"(사용자별 D-plane 없음), "No User Quota", "No Instance", "No User Data"**. 이는 아키텍처의 "중앙집중 단일 배포, 논리적 멀티테넌시" 방침(아래 2번)과 일치한다.

**요약:** 사내 도구로는 이미 정식 오픈(5/12)했고 MCP까지(6/10) 열렸다. 하지만 "Flava 정식 상품"으로서의 롤아웃은 7/8 킥오프한 초기 단계이고, 운영 성숙도 항목 다수가 미완이다.

---

## 2. 아키텍처 (위키 버전) — 코드 대조용 상세

출처: `02. Architecture`(3854108940) 전문 + ADR들. 아래는 전부 위키 서술이며 코드 검증 대상이다.

**전체 형태**
- 단일 배포(single deployment). Control Plane(바인더/소스/접근 관리)과 Data Plane(질의 처리)로 논리 분리하되 **둘 다 한 배포 안**. 사용자별·바인더별 D-plane 인스턴스 없음("centralized D-Plane").
- 멀티테넌시는 물리적이 아니라 **논리적** — 요청마다 하나의 Binder로 scope.
- 3개 인터페이스: Web Chat(SSE), REST API, MCP.

**에이전트**
- **LangGraph 기반 ReAct 에이전트**(reason→act 루프). "에이전트 코드 ~572줄"이라고 명시(ADR-005).
- 도구는 **바인더의 소스 타입에 따라 동적 필터링**. Wiki+Code만 있는 바인더엔 K8s/Logs/Metrics 도구가 아예 안 붙음 → 환각 도구 호출 방지.
- 서브에이전트 없음(단일 에이전트에 모든 도구). `spawn_agent` 기능은 시도했다가 중단(ADR-006, 5번 참조).

**소스 2분류 (코드 대조 핵심)**
- **Static(색인형):** Wiki, Code, Indexed Web, Text → 셋업 시 크롤/클론·청킹·임베딩해서 pgvector에 저장, 검색으로 조회. status(`indexing`→`ready`/`error`) 있음.
- **Runtime(라이브):** Logs, K8s, IMON, MCP, Web Search, Context7 → 색인 없이 질의 시점에 직접 조회. status 없음.
- **주의:** Code는 static으로 분류되지만 **벡터 색인이 아니라 git clone만** 한다. 실제 코드 탐색은 grep/read/glob 온디맨드(ADR-003). Binder 생성 시퀀스에도 "Code: git clone repo → store on filesystem (no embedding)"이라고 명시.

**저장·검색**
- PostgreSQL + pgvector. 검색은 **하이브리드(BM25 full-text + dense 벡터 유사도)**.
- 임베딩: OpenAI `text-embedding-3-large`(3072차원). LLM은 OpenAI GPT(문서 곳곳에 "GPT-5.4" 명시, ADR-006/007).
- 격리: 벡터 컬렉션은 바인더+소스타입 단위(예 `bnd_mybinder_wiki`), 크로스 바인더 쿼리 없음. 코드 레포는 바인더별 디렉토리 `/data/repos/{binder_id}/`.

**샌드박스**
- 코드 실행용 임시 K8s Pod, 채팅 스레드당 1개. egress 전면 차단, 시크릿 미마운트, 서비스어카운트 없음, 60분 유휴 후 자동 정리. 별도 네임스페이스 `context-ai-sandbox`.

**인증·인가**
- 3경로: (1) Browser/CLI = oauth2-proxy → OIDC(CorporateIdP/Dex), `X-Forwarded-Email`로 사용자 식별. (2) System API = 고정 Bearer 토큰, 사용자 신원 없음, public 바인더 non-streaming만. (3) MCP = **인증 없음, public 바인더만**(FCP 이관 시 Athenz 인증 추가 예정).
- 5개 역할: Creator / Shared User / Public User / Admin(`ADMIN_USERS` env, 사용자 임퍼소네이션 가능) / System.
- 자격증명(Confluence PAT, GitHub PAT) **AES-256-GCM-SIV** 암호화, API 응답에선 write-only. K8s 시크릿은 에이전트 출력에서 항상 `[REDACTED]`(비활성화 불가).
- Rate limit 10 req/min/user, 바인더 status guard(ready 아니면 거부).

**질의 시점 권한 체크 (보안 핵심)**
- shared/public 바인더에서 **크리에이터가 아니라 조회자 본인 토큰**으로 소스 시스템 권한을 질의 시점에 확인. 접근 불가 콘텐츠는 답변에서 제외 + **LLM에 아예 전송 안 함**.
- `ACL Control (JP)`(4423368192)에 구현 디테일이 있다: 후보 page_id를 **CQL 배치**로 확인(page별 REST 호출 아님), **permission cache TTL allow/deny 각 60초**, 확인 실패 시 해당 chunk는 OpenAI에 안 보내고 경로에 따라 request failure 처리.
- 소스 타입별 soft-block: K8s/IMON은 public 확장 시 `?confirmed=true` 없으면 차단, Wiki는 실시간 재확인.

**배포/스택**
- 단일 Pod에 컨테이너 2개: `oauth2-proxy`(OIDC 사이드카; `/health`,`/mcp/*`,`/api/v1/*`는 auth 예외) + `context-ai`(FastAPI+Uvicorn). init 컨테이너가 Alembic 마이그레이션.
- 환경: `context-ai`(prod), `context-ai-dev`(dev), 같은 클러스터. Ingress는 FabricLB+TLS.
- CLI는 Go+Cobra(`ctxai`). 인프라 K8s+Kustomize. 관측성 Langfuse.

**MCP 이중 역할**
- **MCP 서버**(바인더 노출): public+ready 바인더만, stateless, K8s/IMON/Sandbox(bash_run)/MCP소스/Web검색 도구는 제외 노출.
- **MCP 클라이언트**(외부 서버 소비): 바인더별 설정, optional bearer, runtime 소스. 외부 MCP 서버는 다시 MCP 서버로 재노출 안 함(자격증명 유출 방지).

**통합 지점(위키 표 기준):** PostgreSQL+pgvector, OpenAI, CorporateIdP(Dex), Confluence(per-user PAT), GitHub Enterprise(per-user PAT), Loki(LogQL), OpenSearch, Kubernetes API(SA token), IMON Flash(PromQL, Basic auth), Tavily(웹검색), Context7(라이브러리 문서), 외부 MCP(SSE), Langfuse.

---

## 3. 제품 전략 (01 중점)

출처: `Positioning`(4296489543), `엔지니어링 컨텍스트 플랫폼`(4288512925), `Adoption Kickoff with LY DevRel`(4216274551), 메인(3621526112).

**한 줄 포지셔닝:** "서비스 하나의 업무 문맥을 **Binder**라는 단위로 한 번 묶으면, 사람과 AI 에이전트가 그대로 재사용한다." 검색 제품도, AI 챗봇도, 소스 커넥터 모음도 아니고 **묶음(bundling) 자체가 핵심**이라고 못박는다.

**3계층 논리(Positioning 문서):**
- 위(소비): 사람 + AI 에이전트(Claude·Codex·Gemini)·챗 → 교체 가능한 상품.
- 가운데(묶기): ContextAI = Binder → **여기가 가치의 핵심.**
- 아래(소스): wiki·code·k8s·metrics·logs → MCP만 있으면 누구나 연결 가능한 범용재.
- 논지: 위(AI)와 아래(소스)는 둘 다 commodity화된다. MCP가 퍼질수록 "닿는 것(access)"은 moat가 아니고, "이 서비스가 무엇을 봐야 하는가를 정하는 curation(가운데)"의 가치가 **오히려 오른다.** 두 번째 moat는 "닿은 데이터를 실제로 쓸 수 있게 만드는 엔지니어링" — 질의 시점 권한 해석, RAG, 온디맨드 grep.

**전사검색·다른 AI 도구와의 관계 (명시적 구분):**
- **전사검색(enterprise-wide search)과 경쟁 아님, 보완.** 검색은 회사 전체에서 찾아주고, ContextAI는 서비스 하나의 문맥을 조립해 재사용 단위로 만든다. "커넥터는 파이프, Binder는 큐레이션."
- **문서 Q&A 도구와도 영역 다름** — 정적 문서만이 아니라 코드+운영 데이터까지 포함.
- **AGENTS.md와 대비:** AGENTS.md는 "이거 봐라"라고 가리키기만 하고, 권한 해석·헤딩 단위 청킹·온디맨드 grep을 못 한다. Binder는 소스를 가로지르고, 여러 사람·여러 에이전트가 여러 표면에서 재사용.
- Binder는 표준(MCP)으로 노출되므로 웹 챗뿐 아니라 코딩 에이전트, **Gemini Enterprise** 같은 커스텀 MCP 연결 도구에서도 그대로 사용 가능.

**Flava 내부에 있다는 것이 차별점:** ContextAI는 Flava 안에 사는 플랫폼이라 **큐레이션 자동화** 방향으로 간다 — App Runner 서비스를 등록하면 매칭되는 네임스페이스·로그·메트릭 scope를 알아서 묶는다(진행 중인 방향).

**타깃 사용 시나리오(메인 페이지, Wiki/Code/Text로 지금 됨):** 개발자(타 팀 API·코드 근거 답변), QA/SET(스펙·코드·테스트 묶어 회귀 위험·미커버 경로), 보안 리뷰(개발자 없이 코드로 auth 확인), PM/기획(구현 vs 스펙 대조, 과거 결정 추적), 온보딩, Support/DevRel. Logs/K8s/Metrics가 열리면 장애 대응(AIOps)으로 확장.

**어답션 신호(LY DevRel 킥오프):**
- PJ AIR / CTO Office에 소개하고 피드백 받음. **핵심 피드백: LY·글로벌 롤아웃 지원, 사용자 교육·가이드, 제품 사용 지표(usage metrics)가 필요.**
- 첫 TECH UP 세션 준비 중(소개 + 유스케이스 데모 + 로드맵).
- 실제 업무 시나리오 발굴 중: Flava 릴리스 사이클 중 프로젝트 문맥 공유, 보안 어세스먼트 때 서비스 Binder 제공, 기획-QA-개발 간 반복 질문 줄이기.
- 데모 자료: `pjair-presentation-20260513.html` 슬라이드, 유스케이스 포털 `portal.workers-hub.com/news/6149`.

---

## 4. Integrations — 현재 상태 vs 계획 (04 중점)

MCP·코딩 에이전트 연동을 중심으로, 각 페이지 근거와 함께 정리한다.

**이미 라이브(문서상):**
- **MCP Export(서버):** 외부 AI 도구(Cursor, Claude Code 등)가 `/mcp/{binder_id}/`로 붙어 바인더 도구를 씀. Streamable HTTP, stateless, public+ready 바인더만. 6/10 출시·ASDR 완료(SIMS-149629). **현재 인증 없음** — FCP 이관 시 Athenz 기반 인증 추가 예정(아키텍처 페이지 + `Flava MCP Hub for MCP Export` 4100025922는 본문 비어 열람 실패).
- **MCP Client:** 외부 MCP 서버를 runtime 소스로 소비, 바인더별 optional bearer.
- **Confluence(Wiki), GitHub Enterprise(Code), Text.** 다만 GitHub 연동엔 Prod 이슈가 있다(아래 5번).
- **IMON 메트릭:** 위 1번의 불일치 참조 — 전략 페이지는 "심사 중"이나 메일리 로그상 6/23 Prod 배포.

**연동 설계 확정, 구현 대기:**
- **FKE(Flava Kubernetes Engine)** `FKE`(4216277705, v131): 2026-06-04 싱크로 설계 확정. `ai-utility` addon이 읽기전용 SA `ai-read`(ClusterRole `fke-user:read`) 배포 → 소스 등록은 프로젝트·클러스터 선택 + addon 활성화 한 단계. Cluster Proxy는 ContextAI Athenz SA로 인증하고 **엔드유저 토큰은 클러스터 접근 게이트로만** 전달(임퍼소네이션 아님), 실제 읽기는 `ai-read` 권한(Secrets 제외, pod logs 포함). **단, 데일리 로그상 "FKE Cluster Proxy 개발 대기(7월 이후)"** — 구현은 아직.
- **Athenz/CopperArgos** `Athenz`(4275686060) + `Flava Product`(4420518744): Flava Product 소스를 "호출자 신원 그대로" 닿게 하는 문제. Human은 CIDP 토큰이라 STS 교환으로 해결됨. **Workload/SA는 CopperArgos가 Athenz로 발급한 토큰이라 STS 교환 불가** → `Flava Product` 문서에서 **방안 4 "유저 SA 등록(Source)"을 채택**(유저 Flava IAM SA로 유저용 API 호출). 방안 4의 자동 key pair 생성은 IAM팀 논의 필요. 이건 Project Binder 전용.
- **Flava OpenSearch(런타임 로그)** `Flava Opensearch`(4301837780): ContextAI 전용 Proxy 별도 검토 중. 미해결 논의 2개(Proxy 호출 자격, cluster/index 단위 접근 판별 — 특히 SA일 때). 데일리 로그상 PoC 클러스터 설정 대기.
- **Flava Monitoring Log(LaaS, 런타임 로그)** `Flava Monitoring Log Integration`(4241150971): Search Proxy로 제공 예정(일정 LaaS팀 내 논의), 인증은 프로젝트별 SA 사용 필요로 합의됨. 스키마 조회용 integration API는 아직 없음(UI용 API 사용은 가능).

**논의·초기 단계:**
- **Jira Source** `Jira Source`(4359905576): 정적 색인 방향, QA 업무(Test Case·Testflo·버그 티켓) 스코핑을 QA와 논의 중. 데일리 로그상 "Jira SA 문서 작성" 진행.
- **Slack App**(CLOUDNATIVE-3693): 유저 시나리오 검토, WFPF 신청.
- **Flava App Runner**(CLOUDNATIVE-3692): OIDC client 변경·토큰 발급 시나리오, PoC.
- **Confluence OAuth** `Confluence OAuth`(4082413862): 현재 PAT 방식의 한계(온보딩 마찰, 과도·장수명 권한) 해소 위해 **읽기 전용 OAuth 2.0 클라이언트로 전환 추진**. 전략 페이지상 4월부터 Confluence 담당 부서(DX Promotion Division)와 협의 중.
- **GHEC(GitHub Enterprise Cloud)** SA 연동: 데일리 로그에 SA 문서 작성·신청 반복 등장(CLOUDNATIVE-3683). 전용 페이지(4360554240)는 본문 비어 열람 실패.

---

## 5. 회의록(03)·Records(05)에서 드러난 고민 / 품질 이슈 / 사용자 피드백

### 품질 이슈 (ADR 실측 기반 — 위키에 트레이스 근거 명시)
- **ADR-006: `spawn_agent` 서브에이전트 중단.** 프로덕션 트레이스(trace-723f473a, "6시간 메트릭으로 장애 징후 확인" 쿼리)에서 복합 실패: 메인이 발견한 네임스페이스 필터(`verda-.*`)를 서브에이전트에 안 넘김 → 서브가 처음부터 재탐색(중복 explore 32회) → 틀린 필터로 빈 결과 → end 파라미터만 바꾸며 13회 헛질의 → step 50 재귀 한도 크래시 → 에러가 조용히 삼켜짐 → 메인이 전부 재실행. 총 267초·66 LLM콜·160 툴콜(서브 없이라면 ~120초). **"LLM이 명시적 지시를 무시하는 판단 실패는 프롬프트로 못 고친다"**가 결론. 코드는 남기고 툴 목록에서만 제거.
- **ADR-007: `todos_write` 툴 제거.** Langfuse 트레이스(210초·26턴)에서 6개 턴이 체크박스만 토글(전체 22%·47초 낭비, 최악은 마지막 태스크 완료 표시에 20.6초·1192 추론토큰). GPT-5.4 medium이 내부 추론으로 이미 계획하니 외부 계획툴은 중복. 제거로 응답시간 15~20% 단축, 대신 프론트의 구조화 체크리스트 UI는 사라짐. 복잡 태스크 스킵율은 트레이스로 모니터링하겠다는 단서.
- 위 둘 다 **"LLM 판단은 프롬프트로 신뢰성 있게 통제 안 되니 툴 자체를 뺀다"**는 같은 철학. (참고로 이건 이 project-brain 레포의 메모리에 있는 "의미 검증은 schema/lint로 못 막는다"류 교훈과 결이 같다.)

### 운영·인프라 고민 (Backend Daily Meeting 3987332546, 최근순)
- **OIDC/CIDP 클라이언트 이관:** oauth2-proxy를 `flava-console` CIDP 클라이언트로 교체(6/25 이슈로 명시). Flava Product 연동의 STS 토큰 교환에 필요. Personal/Project Binder 인증·인가 시나리오(CLOUDNATIVE-3735)가 최근 주요 작업. 6/30~7/9 계속 등장.
- **코드 레포 스토리지 볼륨 마이그레이션(신뢰성 이슈):** code repo가 쓰는 `filestorage-hdd` StorageClass가 볼륨 스냅샷을 지원 안 해 **백업 생성 불가**. HDD→SSD PVC로 rsync live migration 후 하루 1회 스냅샷 cronjob 배포 계획(6/22 이슈). 랜섬웨어 대비 조사도 병행.
- **GHEC Prod 접근 제약:** Flava Prod에서 GHEC API outbound 프록시가 Tool 세그먼트에만 열려 있어, Prod 세그먼트에서 GHEC API 쓸 방법을 별도 문의·프록시 필요(6/19, 6/22).
- **SIMS XSS 취약점**(ticket 156068): 답변 완료·대기 중으로 6/17~7/9 내내 "공유 사항"에 남아 있음.
- **Audit Log를 SplunkPF로 전송**(CLOUDNATIVE-3711): 우선순위 논의 필요로 이슈 등록.
- **Partner.git 대기**(CLOUDNATIVE-3449): 장기 대기 항목.
- **Athenz Quota 증량, Solution Template/IAM Catalog PR**: Flava Product화 배관 작업이 6월 하순~7월 초 집중(Solution Template 배포 7/13 예정).
- **Mock 서버**(CLOUDNATIVE-3740): Flava 연동용 목 서버 개발·배포(7/2~7/9).

### 사용자 피드백 / 실사용 신호
- **PJ AIR / CTO Office 피드백**(LY DevRel 페이지): LY·글로벌 롤아웃 지원, 사용자 교육·가이드, **사용 지표(usage metrics)** 필요. → 지금 제품이 "사용량을 못 보고 있다"는 신호.
- **QA에서 온 실제 질문 예시**(Jira Source 페이지, Slack 공유): "쿠폰 특정 기능의 과거 버그 리스트", "과거 버그로 개발 리스크 파악", "업데이트된 기획서+기존 Test Case로 신규 Test Case 생성". → QA가 실제로 원하는 워크로드가 구체적으로 잡혀 있음.
- 실 업무 도입 후보로 Flava 릴리스 문맥 공유, 보안 어세스먼트용 서비스 Binder, 기획-QA-개발 반복질문 감소를 스스로 꼽음.

### Records(05)에서
- `Resources`(4076503934): Master/Stage/Prod API·문서 URL, Grafana C-Plane 메트릭·Loki 로그 대시보드, FKE 클러스터/VPC/LB/DNS/Redis/PostgreSQL/Object Storage 링크, OpenAI 프로젝트(`ly2043_LP contextai`(dev/stage), `ly2080_LP contextai`(prod)). → 운영 리소스 인벤토리는 갖춰져 있음.
- `CorporateIdP Tokens`(4021123726), `How to Create Encrypted DEK`(4000766792)는 운영 절차 문서(본문 미열람).

---

## 부록: 읽은 페이지 전체 목록

**본문 전문 확보(내용 인용에 사용):**
- 3621526112 — ContextAI: Bridging the Gap Between AI and Your Systems (메인)
- 3854108940 — 02. Architecture
- 4296489543 — ContextAI - Positioning
- 4216274551 — ContextAI Adoption Kickoff with LY DevRel
- 4288512925 — ContextAI: 엔지니어링 컨텍스트 플랫폼
- 4321627581 — ContextAI - Readiness Checklist (Dev)
- 3987332546 — ContextAI - Backend Daily Meeting (v254, 파일로 추출; 7/9~6/15 구간 판독)
- 4275686060 — ContextAI Integration - Athenz
- 4359905576 — ContextAI Integration - Jira Source
- 4420518744 — ContextAI Integration - Flava Product
- 4082413862 — ContextAI Integration - Confluence OAuth
- 4423368192 — ContextAI Confluence Integration and ACL Control (JP)
- 4216277705 — ContextAI Integration - FKE
- 4301837780 — ContextAI Integration - Flava Opensearch
- 4241150971 — ContextAI: Flava Monitoring Log Integration
- 4076503934 — ContextAI - Resources
- 3884473566 — ADR-006: Suspend spawn_agent Sub-Agent Feature
- 3892400678 — ADR-007: Remove todos_write Tool
- 3967544343 — ADR-009: Separate Personal and Project Binder Spaces

**열거만 되고 본문 비어 열람 실패(컨테이너/매크로 페이지로 추정, 메타데이터만 반환):**
- 4284676806 — 01. Product & Strategy (부모)
- 3854120569 — 04. Integrations (부모)
- 3987332537 — 03. Meeting Logs (부모)
- 4321627542 — 06. Release (부모)
- 4000774429 — 05. Records (부모)
- 3854108985 — ADR 인덱스 (부모)
- 4061274951 — AI Generated Meeting Logs (부모)
- 4100025922 — Integration - Flava MCP Hub for MCP Export
- 4360554240 — Integration - GHEC

**존재 확인했으나 우선순위·예산상 미열람(제목만):**
- 01: 4288516955(Engineering Context Platform JP — 4288512925 한국어판의 일본어 중복 추정)
- 02: 3861728037(Designs), 3854116359 ADR-001, 3854119251 ADR-002, 3854119281 ADR-003, 3854119320 ADR-004, 3884452132 ADR-005, 3967544317 ADR-008 (핵심 논지는 Architecture 본문 표에 요약돼 있어 생략)
- 03: 4026322632(2026-04-21 Meeting Minute), 4099358977(2026-05-06 Meeting Minute) — 오래된 회의록이라 후순위
- 04: 4328533341(Flava App Runner), 4174414627(IMON Metrics), 4168693535(IMON Loki Integration)
- 05: 4021123726(CorporateIdP Tokens), 4000766792(How to Create Encrypted DEK)
