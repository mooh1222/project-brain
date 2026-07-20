조사를 마쳤다. 아래가 보고서 본문이다.

---

# ContextAI 설계 결정·제품 전략 규명 보고서

조사 대상: 로컬 clone `/private/tmp/.../scratchpad/context-ai` (기본 브랜치 `main`, HEAD `0a88d586`). 근거는 파일경로:줄번호로 표기하고, 코드에서 직접 확인한 사실과 문서상 계획을 구분했다.

---

## 0. 한 줄 정체성

ContextAI는 사내 운영 지식을 다루는 **NotebookLM 스타일 AI 어시스턴트**이자, 스스로를 "**프로젝트 스코프 인프라 제품**"으로 규정한 물건이다. 1급 리소스명은 `Binder`이고, 내장 chat UI는 그 인프라의 "첫 번째 레퍼런스 소비처"로 본다 (`docs/adrs/0012-*.md:89`, `CLAUDE.md:3`, `README.md:3`).

---

## 1. ADR — 각 결정 한 줄 (docs/adrs/, 전 17건)

`docs/adrs/`의 각 파일 `## Decision` 절을 근거로 한다.

| ADR | 상태 | 결정 (한 줄) |
|---|---|---|
| 0001 | Accepted | 복잡한 agentic workflow 대신 **단일 ReAct 에이전트 + 평탄한 tool 목록** 유지 (`0001-*.md:15`). |
| 0002 | Accepted | 코드 분석을 Claude Agent SDK에 위임하지 않고 **Read/Grep/Glob 도구를 직접 구현** (`0002-*.md:16`). |
| 0003 | Accepted | 코드 검색은 **벡터 인덱싱이 아니라 on-demand 탐색(Read/Grep/Glob)** — Claude Code가 둘 다 해보고 agentic search를 택한 선례 인용 (`0003-*.md:16,32`). |
| 0004 | Accepted | 코드 분석을 **별도 sub-agent로 분리하지 않고** 메인 에이전트 tool로 유지 (`0004-*.md:22`). |
| 0005 | Accepted | orchestration 계층은 **Claude Agent SDK가 아니라 LangGraph 유지**, sub-agent·skill·context 압축은 middleware로 확장 (`0005-*.md:24`). |
| 0006 | Accepted | `spawn_agent`(sub-agent) 기능 **비활성화 + 구현 코드 영구 삭제**(2026-03-28 갱신) — 실측 trace에서 context 미전달·오판단이 프롬프트로 안 고쳐짐 (`0006-*.md:35,38`). |
| 0007 | Accepted | `todos_write` 도구 **제거**, 가벼운 system prompt 가이드로 대체 — turn 오버헤드 22% 낭비 (`0007-*.md:22`). |
| 0008 | Accepted | Project Binder 접근제어에 **D-plane role 안 씀**, C-plane role(`ctxai_admin`/`ctxai_readonly`)로 판단 (`0008-*.md:11`). |
| 0009 | Accepted | 개인 Binder와 Project Binder는 **별도 공간**, 초기엔 cross-space 이동·가시성·공유 없음 (`0009-*.md:10`). |
| 0010 | Accepted | 긴 대화 관리는 EA에선 **trimming만**, LLM 기반 compaction은 뒤로 미룸 (`0010-*.md:27`). |
| 0011 | Accepted | 1차 LLM은 **GPT 5.4 유지** (Claude Opus 4.6 비교 후), provider 추상화는 revert (`0011-*.md:59`). |
| 0012 | Accepted | ContextAI를 **프로젝트 스코프 인프라 제품**으로 규정 → Flava 표준대로 Dev/Prod 양쪽 독립 인스턴스 배포 (`0012-*.md:89,91`). |
| 0013 | Accepted | **Indexed Web(BFS 크롤러) 소스 제거**, Web Search+Web Fetch만 유지 — 외부 웹 BFS는 의도대로 경계가 안 잡히고 공격면 과다 (`0013-*.md:127`). |
| 0014 | **Rejected** (2026-04-23) | EA용 운영자 PAT 서비스 fallback 제안 → 보안팀이 account sharing으로 **거부**, EA는 개인 PAT 강제 유지 (`0014-*.md:148,178`). |
| 0015 | Accepted | **Sandbox(코드 실행) 본진 유지·활성화** — Logs/K8s/IMON raw 분석의 인지 보조로 필수, Agent Runner 위임은 분류 오류로 기각 (`0015-*.md:205`). |
| 0016 | Accepted | viewer측 Wiki 권한 체크를 **Confluence CQL batch로 통일** (page별 content API burst 제거, 기본 500 id·동시성 3) (`0016-*.md:237,241`). |
| 0017 | Accepted | index-time `viewerless_access=="allow"`로 판정된 **public wiki page는 CQL 체크 자체를 생략** (`0017-*.md:273`). |

관찰: ADR은 대부분 "**단순함을 위해 무언가를 안 만들거나 되돌린다**"는 방향이다(0001·0002·0004·0005·0006·0007·0010·0013). 오버빌드 억제가 이 팀의 일관된 설계 철학이다.

---

## 2. 아키텍처 핵심 설계 (designs / specs / contracts)

### 2-1. 검색(Search) 모델

- **알고리즘은 계약이 아니라 "결과 경계"만 고정한다.** `knowledge_search`는 dense vector·lexical·metadata match·rank fusion·rerank를 자유 조합할 수 있고, 계약은 "큰 Binder에서도 작은 후보 집합만 반환한다(전체 목록을 LLM에 읽히지 않는다)"만 강제한다 (`docs/contracts/knowledge-tools.md:25-30`). 검색 대상에 본문뿐 아니라 title·source URL·section heading·page id 같은 식별 단서도 포함해야 한다 (`knowledge-tools.md:22`).
- 3개 도구 역할 분리: `knowledge_search`(후보 찾기) / `knowledge_list`(catalog 확인, citation 근거 아님) / `knowledge_get`(고른 문서 읽기) (`knowledge-tools.md:11-15,40`).
- **[코드 실증] `knowledge_search`에 LLM 기반 결과 필터가 붙어 있다.** 기본 모델·effort를 재사용하되 `OPENAI_FILTER_MODEL`로 분리 가능, "필터가 관련 문서를 잘못 지우면 회복 불가라 recall/품질 우선" (`docs/specs/agent.md:13`).

### 2-2. 인덱싱 모델

두 갈래로 뚜렷하게 갈린다.

- **코드는 인덱싱하지 않는다.** git clone 후 grep/glob/read로 on-demand 탐색 (ADR-003; `docs/specs/source-code.md:5`). 새 코드 소스 추가는 "git clone"뿐, 파싱·임베딩·sync job 없음.
- **Wiki/Text는 벡터 인덱싱한다.** Wiki 인덱싱 설계가 가장 정교하다 (`docs/contracts/wiki-source.md`):
  - scope는 root page + depth + exclude/include override로 정하고, **인덱싱 대상 목록의 최종 근거는 Confluence REST tree traversal**. CQL은 search index 기반이라 stale할 수 있어 "이미 아는 page id 집합의 권한 대량 확인"에만 쓴다 (`wiki-source.md:10-12,216-223`).
  - 2단계 수치 게이트: `wiki_scope_prepare_cap`(기본 10000, review 목록 생성 한도)과 `wiki_page_budget`(기본 2000, binder 전체 고유 page 수 제한) (`wiki-source.md:157-160`).
  - **청킹은 heading 단위** — `body.storage`(작성 원문)에서 내용을, `body.view`(렌더 HTML)에서 heading anchor id만 읽는다. 이유가 보안적: `include`/`excerpt` 매크로가 렌더 본문에 끌어온 제한 콘텐츠가 공개 chunk로 새는 것을 막기 위함 (`wiki-source.md:242,325,349-350`).
  - 증분 재인덱싱은 page manifest(content hash 등)로 변경 page만 재임베딩 (`docs/contracts/source-lifecycle.md:94-106`).
- Jira는 **벡터가 아닌 별도 read model(`jira_issue_records`)** 로 저장 — 의미검색은 `knowledge_search`, 목록·exact filter는 `jira_search_issues`/`jira_field_values` catalog 도구로 나눔 (`docs/designs/source-jira-design.md:76-80,158-164`).
- IMON은 아예 인덱싱 안 하는 runtime source — cardinality 높고 빨리 낡아서 질문 시점에 Flash에서 조회, `query_range`는 raw 시계열 대신 summary 우선 반환 (`docs/designs/source-imon-design.md:7,13`).

### 2-3. Binder 모델

- **정적/런타임 2분류.** 정적(`wiki`,`code`,`text`)은 인덱싱, 런타임(`logs`,`mcp`,`k8s`,`web_search`,`context7`,`imon`)은 실행 시점 조회 (`CLAUDE.md:8`).
- **선언형 status(declarative).** Binder status는 직접 쓰지 않고 projection 하나가 계산하는 "availability cache" — 입력(lifecycle condition, 삭제요청, active reindex run, source row status, Wiki scope, published view 유무)만으로 재계산. 상시 watcher/controller 없이 기존 요청·background job 흐름에서 projection 호출 (`docs/designs/declarative-binder-design.md:16-21`, `docs/contracts/binder-lifecycle.md:105-134`).
- **핵심 불변식: published search view.** 이미 준비된 검색 view가 있으면 source 재작업 중에도 chat/read를 막지 않는다. 작업 중 새 chunk는 publish 전까지 검색에 안 섞임. 실패해도 기존 view 전체를 잃지 않음 (`binder-lifecycle.md:11,70-80`). 단 Wiki scope review는 hard block (`binder-lifecycle.md:12,139`).
- **상태별 허용동작 표**가 계약으로 고정 (`binder-lifecycle.md:45-52`): `updating`에선 chat·scalar수정·공유는 O, source변경·reindex는 X. 차단 응답은 409.
- **권한: owner + 공유 role.** visibility는 `private`/`shared`/`public`. `creator`는 감사 필드일 뿐 권한 판단에 안 씀. Admin role은 운영 관찰 API 전용, 접근권한 우회 못함 (`docs/contracts/binder-permissions.md:7-12`). **source-level viewer 경계**는 binder 접근권과 별개 — editor가 인덱싱했어도 viewer에게 원본 권한 없으면 그 content 안 보여줌 (`binder-permissions.md:84-85`).
- **source lifecycle 격리 원칙:** source 작업은 자기 source row가 소유한 산출물만 갱신, 다른 source를 건드리면 안 됨. 소유권 없는 legacy 산출물은 먼저 복구 (`source-lifecycle.md:11-18`).
- **Project Binder + Service Account 설계**(`docs/designs/project-binder-service-account-design.md`): 개인 Binder(`/binders/*`)와 Project Binder(`/projects/{project}/binders/*`)를 URL부터 분리. Service Account v1은 **query-only**, source filtering은 Wiki=`viewerless_access=="allow"` row만, GitHub=repo visibility가 public/internal만(장애 시 fail-closed) (`project-binder-*.md:85-90,193-206`). 접근제어는 FCP(Flava Common Proxy)가 C-plane role로 판단하고 apiserver는 무결성만 검증 (`:159-172`).

### 2-4. 에이전트 실행 설계

- 같은 `thread_id` 동시 실행 금지: **PostgreSQL advisory lock** 획득, 이미 잡혀 있으면 HTTP 423. lock 잡은 요청은 agent를 background `asyncio.Task`로 넘겨 SSE 끊겨도 끝까지 실행, checkpoint가 최종 응답 SoT (`docs/designs/chat-agent-execution-design.md:21-28`).
- **언어 drift 방지**: 외부 language detection 의존성 없이 Unicode script로 ko/ja/en 감지(한글>가나>한자>영어), middleware가 LLM 직전 지시에 반영, CLR(Correct Language Rate)만 Langfuse에 기록 (`docs/designs/multilingual-language-control-design.md:19-25`, `docs/specs/agent.md:45-52`).
- **[코드 실증 드리프트] 모델 버전 불일치**: ADR-011은 "GPT 5.4 유지"인데 `specs/agent.md:11`의 기본값은 이미 `gpt-5.5`로 갱신됨. ADR이 spec을 따라오지 못한 상태로 추정.

### 2-5. 인증/audit

- 인증 경계가 **oauth2-proxy → FCP → apiserver**로 이동. apiserver는 FCP가 주입한 `X-Unified-ID`/`X-Athenz-Principal`/`X-Athenz-Role`만 신뢰, `X-Forwarded-*` 금지 (`docs/designs/fcp-migration-design.md:19-21`, `CLAUDE.md:86`).
- **application audit** 별도: FCP audit는 HTTP 진입점만 보므로, agent가 내부 tool로 어떤 source에 접근했는지는 `source.access` event로 따로 기록(본문·credential은 기록 안 함), `run_id`로 상관 (`docs/designs/audit-logging-design.md:20-26`).

---

## 3. 제품 전략 (docs/strategy/)

### 3-1. 타겟 사용자

직군별 유스케이스 카탈로그(`docs/strategy/use-cases.md`)가 8개 직군을 명시: 개발자, SRE/운영, QA/SET, PM/기획, 보안팀, DevRel/지원, 리더/팀장, **AI 도구 사용자**(`use-cases.md:9-18`). 반복 강조되는 경계선: "**내 저장소 탐색은 Claude Code/Codex가 낫고, ContextAI는 내가 관리하지 않는 다른 팀 서비스·타 서비스 맥락에 쓴다**"(`use-cases.md:22,175`).

### 3-2. 포지셔닝 — 특히 사내 전사검색과의 관계 인식

플랫폼 포지셔닝 문서(`docs/strategy/platform-positioning.md`)가 핵심이다.

- **자기 정의**: "또 하나의 AI 모델·챗봇·검색 제품이 아니다. 특정 서비스의 업무 문맥을 팀과 AI 에이전트가 재사용하게 만드는 **서비스 문맥 패키지**"(`:12-14`).
- **경쟁이 아니라 계층 분리로 프레이밍**한다. 도구별 담당 계층 표(`:56-64`)에서 각 사내 도구와 명시적으로 선을 긋는다:
  - **Gemini(전사 AI front door)**: 충돌 아님. "Gemini는 AI 실행 계층, Binder는 그 실행에 필요한 서비스 문맥 계층." Gemini가 강해질수록 입력 문맥 품질이 더 중요해진다는 논리 (`:97-99,115`).
  - **Universal Search(전사검색)**: "넓은 범위에서 후보를 찾지만, **특정 서비스의 공식 source set을 고정하고 재사용하는 단위는 아니다**"로 규정 (`:62`). 즉 전사검색을 competitor가 아니라 "커버리지는 넓지만 재사용 단위가 없는 계층"으로 인식하고, Binder는 "누군가 정의한 공식 문맥을 팀·에이전트가 재사용하는 단위"라는 빈자리를 차지한다고 주장 (`:66-70`).
  - **NotebookLM**: "정적 source엔 맞지만 runtime source·agent 재사용엔 안 맞음"으로 차별화 (`:63`).
  - **MCP/AGENT.md**: 커넥터·규칙을 연결하지만 "이 서비스에서 무엇을 공식 문맥으로 볼지"는 정하지 않음 → 그 정의를 Binder가 개인설정이 아닌 팀 재사용 단위로 승격 (`:58-60,68-70`).
- **성공 판단 기준을 "chat UI 사용량"이 아니라 "Binder가 전사 AI 플랫폼의 재사용 문맥 단위가 되는가"로 명시**(`:136-138`) — 문맥 재사용, source coverage(runtime까지), 권한·출처 유지, agent 연동, 운영 가치 (`:141-146`).

### 3-3. 로드맵 (전략 문서 + 공개 roadmap + 발표 스크립트 교차)

세 출처가 일관된다.

- 발표 스크립트(`docs/presentations/pj-air-20260528/script.md:4-6`): 현재 공개 = Wiki/Code/Text, 확장 = K8s/Logs/Metrics/MCP/Web Search는 보안 검토 이후.
- 공개 roadmap(`web/roadmap.html`, 2026-06-22 업데이트) "Coming soon" 구조:
  - **In progress**: Latency improvements(메트릭으로 느린 단계 식별)
  - **Pending approval**: YJ Partner GitHub host 지원
  - **Planned**: HTTP API 지원, Flava IAM Service Account 지원, Wiki OAuth 인증, Logs, K8s, Web Search, External MCP servers, Context7, Flava UI 통합
- 포지셔닝 문서 제품상태 표(`platform-positioning.md:121-126`): Wiki/Code/Text=공개, Logs/K8s/Metrics=베타·보안검수 대상, Binder MCP export=검토 대상, Agent/Slack bot/AIOps 연동=확장 시나리오.

---

## 4. "구현 완료" vs "계획" — 기능 목록 (코드 교차 검증)

**[코드 실증]** `src/context_ai/source_registry.py:47-58`의 `ea_enabled` 플래그와 `src/context_ai/sources/`·`tools/` 파일 존재, git log를 교차했다.

### 구현 완료 + 현재 릴리즈 활성 (`ea_enabled=True`)
`wiki`, `code`, `text`, `imon` (`source_registry.py:48-50,56`; `CLAUDE.md:20`).

### 구현 완료 but 게이트로 비활성 (`ea_enabled=False`, 코드는 존재)
- **jira**: `sources/jira.py`·`tools/jira.py`·`jira_client.py` 존재, git log에 `Add Jira source integration`~`Gate Jira source by user and binder`(PR #561)까지 병합됨. 즉 **구현됐고 rollout만 유저·binder 단위로 막힌 상태** (`source_registry.py:51`; git `2f61c4a4`, `80f78a5e`).
- **k8s, logs(log), mcp, context7, web_search**: 각 `sources/`·`tools/` 파일 존재하나 `ea_enabled=False` (`source_registry.py:52-57`). 발표·roadmap상 "보안 검토 이후" 확장 대상.
- **bash_run 샌드박스**: 구현돼 있으나 `DISABLE_SANDBOX=true`로 비활성 (`CLAUDE.md:20`; ADR-015가 활성화 방향 확정).

### 제거/폐기됨 (구현했다가 뺌)
- Indexed Web 크롤러·임베딩 파이프라인 (ADR-013, from-scratch 재작성 필요).
- `spawn_agent` sub-agent — 코드·테스트 영구 삭제 (ADR-006).
- `todos_write` (ADR-007).
- Claude Agent SDK provider 추상화 프로토타입 — revert (ADR-011:72).

### 계획/미구현 (문서만 존재)
- **DB 레벨 optimistic concurrency** (모든 write API): "스펙 확정, 구현만 남음" (`TODO.md:26`).
- **MCP Export** (Flava MCP Hub 경유 thin shim) (`TODO.later.md:16`; `CLAUDE.md:20`은 apiserver가 직접 `/mcp/*` 제공 안 함 명시).
- **Project Binder + Service Account**: 설계 완성, "현재 구현은 API+임시 UI만 열어둔 상태, FCP project authorization·IM role 미연결"로 **부분 구현/gated** (`project-binder-*.md:309-322`).
- **HTTP Query API, Wiki OAuth, Flava UI 통합**: roadmap Planned.
- **Web Fetch Service egress 아키텍처**: 문서 자체가 "미구현 보안 검토안"으로 명시 (`docs/designs/web-fetch-egress-architecture.md:3`).
- Tool API 계약 분리, 멀티바인더 검색, source별 reindex endpoint, durable background job 등 (`TODO.md:30-33`, `TODO.later.md:28-37`).

주의: `CLAUDE.md:30`이 "TODO·후속 PR을 LLM이 단독 결정 말라"고 강제하고 TODO.md는 완료 항목을 삭제하는 규칙이라(`TODO.md:5`), "TODO에 없음 = 구현됨 or 폐기됨" 판단은 git history로 확인해야 정확하다.

---

## 5. 개발 방법론 (spec-driven-development.md, contract-rule.md)

### 5-1. Spec-Driven Development — "자율 엔지니어링 파이프라인"

목표: 사람이 로컬에서 스펙을 작성·merge하고 작업 할당하면, **원격 러너의 에이전트가 스펙→코드→테스트→PR까지 사람 개입 없이 수행**. 사람 역할을 코딩에서 스펙작성·방향설정·PR승인으로 전환 (`docs/spec-driven-development.md:5,17,21`).

- **핵심 개념 "황금 원칙(Golden Rules)"**: 문서화(soft, CLAUDE.md 지시)와 테스트/린터 인코딩(hard, 위반 시 CI 실패)을 대체가 아닌 **레이어**로 봄. "에이전트가 스펙을 안 읽었어도 위반 코드는 merge 불가"가 핵심 (`:34,43`).
- 에이전트 5종: 스펙작성/개발/doc-gardening(스펙↔코드 drift)/리팩터링/리뷰(코멘트만, merge 권한 없음) (`:97-103`).
- CI 5종 게이트: 불변조건 테스트(K8s+public 금지, secret redaction 등), 아키텍처 린터(import 방향: routers→services→db, sources는 routers import 금지), 구조검증, 문서검증, 기존 테스트 (`:109-152`). 보호: CLAUDE.md(soft) + CODEOWNERS(hard, `tests/`·`docs/specs/`) (`:154-156`).
- 3단계 도입(Phase 1~3) (`:166-170`). 참고로 OpenAI "Harness Engineering" 인용 (`:174`).

### 5-2. Contract Rule — 계약 매체 정책

- **계약 정의**: "누가 구현하든 같아야 하는 시스템 동작." 계약 코드는 '인간이 합의한 확실한 것', 나머지는 'LLM이 생성해 확실하지 않을 수 있는 코드'로 구분 (`docs/contract-rule.md:5-7`).
- **3매체 + 우선순위**: 코드 계약(`src/context_ai/contracts/`) > 테스트 계약(`tests/contracts/`) > 자연어 계약(`docs/contracts/`). 강제력 순서(런타임>CI>리뷰)가 근거 (`:11-13,29-33`).
- **한 결정 한 매체**(중복 금지), 실행 가능한 규칙은 코드/테스트로, 자연어는 이유·tradeoff·리뷰 진입점에만 (`:15-17`).
- 라우트를 코드 계약에 두려면 **thin handler**여야 하고(service 위임+단순 매핑까지만), 내부 동작 계약은 자유 prose가 아니라 `(group,title,cases[id+summary])` **dict 카탈로그**로 표현 → verifier test가 case id를 fixture에 매핑 (`:21-27`).
- 계약 편입 판별 3단계: ①비즈니스 영향(외부에서 보이는 동작 차이) ②깨지면 그 자리서 이상해지나 vs 겉으론 정상(보안누출·권한우회·격리위반) ③어느 매체가 사람이 읽기 분명한가 (`:37-57`).
- **`docs/specs/`는 "임시/소멸 영역"** — 새 진술 안 받고 점점 얇아져 삭제, 계약으로 흡수 (`:59-62`; `CLAUDE.md:17,27`). `tests/invariants/`·`tests/architecture/`도 옛 영역 (`:61`).

관찰: 5-1(황금 원칙)과 5-2(계약 우선순위)는 같은 철학의 두 얼굴이다 — "LLM 에이전트가 자율 개발하는 세계에서 신뢰의 앵커를 문서가 아니라 기계가 강제하는 코드/테스트에 둔다."

---

## 6. 종합 — 이 팀이 어디로 가려 하는가

1. **제품 방향**: chat UI 회사가 아니라 "**재사용 가능한 서비스 문맥(Binder) 인프라**" 회사가 되려 한다. chat은 첫 소비처일 뿐, 진짜 목표는 Binder를 **Gemini·Codex·Slack bot·AIOps·MCP 등 여러 AI 실행 계층이 공유하는 컨텍스트 레이어**로 만드는 것 (`platform-positioning.md:150`, `use-cases.md:426`). 성공 지표를 사용량이 아닌 "재사용 단위 채택"으로 잡은 게 이 의도를 뒷받침한다.

2. **전사검색·Gemini와의 관계**: 정면 경쟁을 피하고 "실행 계층 vs 문맥 준비 계층"으로 계층 분리를 택했다. 전사검색은 "넓지만 고정된 재사용 단위가 없는 것"으로, 그 빈자리를 Binder가 메운다는 서사다.

3. **기술 로드맵의 다음 관문**: (a) runtime source(Logs/K8s/Web/MCP) 보안검수 통과 후 활성화 — 여기에 **sandbox 활성화가 전제**(ADR-015), (b) **인간 전용에서 프로그램 소비로 확장** — Project Binder + Service Account + HTTP Query API + MCP Hub export, (c) **Flava UI 통합**으로 정식 제품 표면 진입, (d) Wiki OAuth로 PAT 강제 해소(ADR-014 거부의 정식 해결 경로).

4. **엔지니어링 방향**: "**스펙만 사람이 쓰고 코드는 에이전트가**" 파이프라인을 지향하며, 그 신뢰 기반을 계약(코드>테스트>자연어)과 CI 황금 원칙에 둔다. `docs/specs/`를 의도적으로 소멸시키고 계약으로 흡수 중이라, 문서 구조 자체가 이 전환의 진행 상태를 보여준다.

5. **일관된 설계 성향**: ADR 다수가 "안 만든다/되돌린다"이고 CLAUDE.md가 오버빌드·후속PR 이관을 명시적으로 억제한다 — **단순함과 surgical change를 강하게 강제하는 팀**으로 판단된다.

---

**보고서 신뢰도 메모**: 1·4·5장은 파일 직접 인용 + 코드(`source_registry.py`)·git log로 실증했다. 3장 로드맵/포지셔닝은 문서상 주장(계획)이다. 2-4의 "gpt-5.5 vs ADR의 GPT 5.4" 및 4장의 "jira=구현됐으나 gated"는 코드/커밋으로 확인한 사실이다. 미독파 contract(automatic-reindex, declarative-status, conversation-share, observability-events, agent-source-catalog, agent-instructions, web-ui, source-imon/jira 계약)와 대부분의 specs는 상위 계약·CLAUDE.md 참조로 역할만 파악했고 전문은 안 읽었다.
