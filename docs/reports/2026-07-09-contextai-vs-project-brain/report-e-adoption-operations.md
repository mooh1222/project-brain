# ContextAI 도입 장벽·운영 형태 분석 — "내일 당장 개인 개발자가 쓰려면"

> **분석 한계 (정직성)**: 이 clone은 식별자 상당수가 스크럽(редactED)되어 있다. `sources`·`token`·`url`·`base_url`·`file`·`text` 같은 흔한 단어가 코드/설정에서 `n`으로 치환돼 있다(예: `source_router = APIRouter(prefix="/sources")`는 `prefix="n"`로, `openai_base_url` 필드는 `n_n`으로 보임). 구조·엔드포인트·의존성 결론은 영향받지 않지만, 일부 정확한 문자열 인용은 불가능해 그 지점은 "추정"으로 표기한다.

---

## 1. 배포 형태 — 사내 k8s 호스팅 서비스 (셀프호스트는 개발용 stack만)

**코드 실증**: 배포는 `workflow_dispatch` 수동 트리거 하나뿐이고, 배포 대상 environment 선택지는 `prod/kks` **단 하나**다 (`.github/workflows/deploy.yaml:8-11`). 배포 동작은 별도 인프라 레포 `Cloud-Native/cn-deploy`를 체크아웃해 `context-ai/deployments/apiserver/overlays/prod/kks/kustomization.yaml`의 이미지 태그를 `kustomize edit set image`로 바꾸고 커밋·푸시하는 방식이다 (`deploy.yaml:88-101`). 이미지는 사내 레지스트리 `vcr-platform.linecorp.com/cloud-native/context-ai/api:<tag>`에서 가져온다 (`deploy.yaml:18-20,37`). 즉 **kustomize 오버레이 기반 k8s 배포**이며, 이건 개인이 손댈 수 없는 사내 GitOps 파이프라인이다.

**문서 주장**: `prod/kks` GitHub Environment는 본인 외 required reviewer 1명이 있어야 배포되고, 롤백은 직전 안정 태그로 워크플로를 재실행한다 (`README.md:37-46`).

**셀프호스트 가능성**: `make local`이 도커 컴포즈로 전체 스택(apiserver + fcp + oauth2-proxy + sandbox, 별도로 postgres)을 띄운다 (`Makefile:75-78`, `hack/docker/docker-compose.yml`의 서비스 목록: `apiserver`, `fcp`(`flava-common-proxy` 사내 이미지), `oauth2-proxy`, `sandbox`). 하지만 이건 "개발자 로컬 개발환경"이지 개인용 배포판이 아니다 — 뒤(2번)의 사내 인프라 의존 때문에 사실상 사내망 + 사내 자격증명이 있어야 뜬다.

---

## 2. 의존 인프라 전수 — 로컬 단독 실행은 mock 말고는 불가

| 인프라 | 역할 | 근거 | 로컬 단독? |
|---|---|---|---|
| **PostgreSQL + pgvector** | 유일한 저장·벡터 검색 DB | `hack/docker/docker-compose.postgres.yml`, `hack/docker/init-extensions.sql`, `providers.py:16,28-58` (asyncpg, `sslmode=require`는 사내 PG 전용). `.env.template:11` DATABASE_URL | 로컬 도커로 가능 |
| **OpenAI (사내 egress 프록시)** | LLM + 임베딩 | `base.yaml` `openai_base_url: https://us.api.openai.com/v1` (LY corp egress), 모델 `gpt-5.5` (`config.py` `n_model`), `langchain_openai` ChatOpenAI/OpenAIEmbeddings (`providers.py:16`), `.env.template:16` OPENAI_API_KEY | 키 필요, 사내 프록시 URL 경유 |
| **Athenz ZTS + Amaterasu** | mTLS로 people/share-target 검색 | `README.md:9-35` (zts-svccert로 30일 cert 발급), `config.py` `amaterasu_n`, `share_target_search.py`(nPeopleClient). 미설정 시 `ConfigError`로 **graceful 비활성**(부팅은 됨) | 사내 SA private key 필요 |
| **FCP (flava-common-proxy)** | 신원 헤더 주입(`X-Unified-ID`/`X-Athenz-Principal`/`X-Employee-ID`/`X-Athenz-Role`) | `CLAUDE.md:86`, `apiserver/auth.py:28-86`, `hack/docker/CLAUDE.md:1-30`, 컴포즈 이미지 `vcr-platform.linecorp.com/flava-common/flava-common-proxy` | 사내 이미지 필요 |
| **oauth2-proxy + CorporateIdP** | 브라우저 OIDC 로그인 | 컴포즈 `oauth2-proxy` 서비스, `.env.template:27` CORPORATEIDP_CLIENT_SECRET, `hack/docker/oauth2-proxy/alpha-config.yaml` | 사내 IdP client secret 필요 |
| **GitHub Enterprise App** | code 소스 인증(레포별 단기 토큰) | `base.yaml` `ghe_instances: git.linecorp.com: app_id "1478"`, `sources/github_app.py` | 사내 GHE App private key 필요 |
| **IMON** | 메트릭 런타임 소스(prod 활성) | `config.py` `imon_auth_n`/`imon_metadata_api_n`/`imon_query_n`(imon.linecorp.com) | 사내망 |
| **KMS / Langfuse / Jira / Context7 / k8s / web_search** | KMS=암호화키, Langfuse=관측, 나머지 소스 | `config.py` `kms_n`, `base.yaml` langfuse_*, `jira_n`. k8s/logs/mcp/context7/web_search는 EA에서 **비활성**(`base.yaml disabled_source_types`) | — |
| **sandboxserver (bash_run)** | 코드 실행 샌드박스 | `sandboxserver/server.py`(별도 컨테이너 `ctxai-sandbox`), `DISABLE_SANDBOX=true`로 **비활성**(`base.yaml`) | 비활성 |

**mockserver의 역할 (유일한 진짜 단독 실행 경로)**: `make mock`은 DB·crypto·LLM·외부 네트워크·인증 레이어 **전부 없이** 메모리 상태 + 실제 contract Pydantic 모델만으로 뜬다 (`mockserver/README.md:3`, `Makefile:83-84`). 인증도 검증하지 않는다 (`mockserver/README.md:42`). 하지만 **canned(미리 박아둔) 응답만** 돌려주고 project-scoped List/Get/Chat 5개 엔드포인트만 흉내 낸다 (`mockserver/README.md:9-17`). 즉 FE 개발용 껍데기이지 실제 지식 회수는 불가능하다. **`MOCK_MODE=true`**면 apiserver 이미지 그대로 이 mock 앱이 뜬다 (`mockserver/README.md:24`).

**결론**: 실제로 답변을 생성하는 로컬 단독 실행은 불가능하다. 최소한 사내 OpenAI egress 키 + CorporateIdP secret + FCP 사내 이미지가 있어야 `make local`이 의미 있게 돌고, code/wiki/people 소스는 각각 GHE App key / Confluence PAT / Athenz cert를 더 요구한다.

---

## 3. 개인 로컬 프로젝트 지식 주입 경로 — 로컬 파일/디렉토리 소스는 없다

**소스 종류 (코드 실증)**: 정적 소스 = `wiki`·`code`·`text`, 런타임 소스 = `logs`·`mcp`·`k8s`·`web_search`·`context7`·`imon` (`README.md:8`, `contracts/apiserver/schemas/binders.py`의 `Literal["wiki","code","text","jira","k8s","imon"]`). prod 활성은 `wiki`·`code`·`text`·`imon`뿐 (`README.md:20`).

- **로컬 파일/디렉토리 업로드 소스: 없음** (코드 실증). apiserver 전체에 `UploadFile`/`multipart`/파일 업로드 라우트가 없다(grep 결과 sandbox의 내부 PUT `/n/{path}`만 나옴). 소스 라우터는 wiki preview/scope, reindex 등만 있다 (`routers/binder.py:977-1020`, `routers/project_binder.py:252-559`).

- **Text 소스 = 임의 지식 주입의 유일한 수기 경로** (코드 실증). "복사-붙여넣기" 콘텐츠를 pgvector에 저장한다 (`sources/text.py:1,45-50`). **용량 제한: 텍스트 1건당 최대 50,000자** (`text.py:53` `MAX_CONTENT_LENGTH = 50000`), 6,000자/500자 오버랩으로 청킹 (`text.py:71`). UI에선 "Text — Paste any content"로 붙여넣기 모달 (`web/index.html:374`). 입력 방식은 UI 붙여넣기 또는 API 호출이며, 파일 경로 지정은 없다.

- **Code 소스 = 서버가 Git URL을 clone** (코드 실증). `clone_repo_for_source`가 GitPython으로 URL을 받아 `/data/repos/{binder_id}`(로컬 dev는 `/tmp/repos`)에 clone한다 (`sources/repo.py:1-4,199,336`). UI 플레이스홀더는 "Git URL (public only)" (`web/index.html:373`), 사내 private 레포는 GHE App 설치 토큰으로 접근 (`sources/github_app.py`). → **로컬에만 있는(커밋 안 된) 작업 디렉토리는 색인 불가.** 도달 가능한 Git URL(공개 레포, 또는 GHE App이 설치된 레포)이어야 한다.

- **Wiki 소스 = Confluence 페이지** (PAT 필요, `.env.template:24`, `preview_service.py`).

**요지**: 개인 로컬 프로젝트 지식을 넣는 방법은 (a) **텍스트 붙여넣기(건당 5만 자, 여러 건 가능)** 또는 (b) **레포를 도달 가능한 Git 원격에 push**뿐이다. "내 로컬 폴더를 가리키면 알아서 색인"하는 경로는 없다.

---

## 4. 소비 표면 — 웹 chat + Query API + Tool API, MCP는 Hub 경유

- **웹 chat** (코드 실증): SSE 스트리밍 + 클릭 가능한 citation (`web/chat.html:80-92,113-122`).

- **Query API (비스트리밍 프로그래매틱)** (코드 실증): `POST /projects/{project}/binders/{binder_id}/query` — JSON 답변 1건 + 재사용 가능한 `thread_id` 반환 (`routers/query.py:1-6,334-347`). 인증은 FCP 주입 신원 헤더(`require_authenticated_user`) + `require_project_binder_tool_access` (`query.py:344-348`).

- **Tool API (에이전트용)** (코드 실증): `/binders/{binder_id}/tools/*`와 `/projects/{project}/binders/{binder_id}/tools/*`에 `knowledge_search` 등 (`routers/tool.py:82-83,450-451`).

- **API 토큰**: `FIXED_API_TOKEN`이라는 **Query API(`/api/v1/...`) 전용 좁은 경로**가 문서상 존재한다 (`.claude/skills/ctxai-api-scenario/SKILL.md:54,61`, `tests/api_rc/CLAUDE.md`, `tests/api_rc/conftest.py`). 다만 정의부는 redaction으로 clone에서 확인 못 했다 — **추정**: Query API용 정적 bearer 토큰. 즉 로컬 자동화 기본 경로는 아니고(스킬이 "기본 경로 아님"이라 명시), OAuth/FCP 헤더가 기본이다.

- **MCP Export** (문서 주장): apiserver가 `/mcp/*`를 직접 제공하지 **않고** Flava MCP Hub 경로로 제공한다 (`README.md:20`). 웹의 "MCP Export" 버튼이 MCP Hub 커넥터 설정을 복사해준다 (`base.yaml` `mcp_export_endpoint`/`mcp_project_export_endpoint`). 향후 계획으로 표기 (`README.md:3`).

- **CLI: 소비용 CLI 없음** (코드 실증). `.claude/skills/`의 4개(create-pr, release, postgres-ops, api-scenario)는 전부 **개발 워크플로 스킬**이지 최종 사용자용 질의 CLI가 아니다.

---

## 5. web/ 프론트엔드 UX — 프레임워크 없는 정적 멀티페이지

**코드 실증**: React/Vue/Svelte 없음(grep 무결과). 순수 HTML + Tailwind 클래스 + 바닐라 JS, 마크다운은 `web/vendor/marked.min.js`, citation 렌더는 `web/citations.js`.

- **`index.html`**: Binder 목록 — My/Shared/Public 탭, "New Binder" 버튼, 소스 타입 선택 카드(wiki/code/text/context7/loki/opensearch/mcp/k8s/imon/web_search 아이콘 정의) (`index.html:206-242,372-381`).
- **`chat.html`**: 3분할 — 좌측 sources 패널 / 중앙 chat / 우측 chat 목록, SSE 토큰 스트리밍, citation을 클릭하면 원문(텍스트 citation은 role=button)으로 (`chat.html:80-92,113-122`).
- **`binder-overview.html`**: 소스/상태 개요 + 상태 폴링 (`binder-overview.html`).
- **문서 페이지**: `guide.html`(다국어 ko/ja/en), `catalog.html`(use cases), `roadmap.html`, `admin.html`(내부 read-only 관측).
- **UI 언어 정책** (문서): 앱 화면은 영어 단일, 장문 문서만 다국어 (`README.md/CLAUDE.md:12-13`).

---

## 최종 평가 — 개인 일상 코딩 루프에 끼워넣을 수 있는가

**결론: 개인이 "내일 당장" 셀프서비스로 쓰기엔 부적합하다. 이건 사내 인프라에 깊게 묶인 팀·서비스 단위 호스팅 제품이다.** 실행 관점에선 개인이 셀프호스트하는 게 아니라 사내 `prod/kks` 인스턴스를 소비하는 형태이고(1번), 그러려면 CorporateIdP 로그인·FCP 신원·Athenz·사내 PostgreSQL·사내 OpenAI egress·GHE App까지 corp onboarding이 전제된다(2번). 지식 주입 관점이 특히 걸림돌인데, **로컬 작업 디렉토리를 가리키는 소스가 아예 없어서**(3번) 내 로컬 프로젝트 지식을 넣으려면 텍스트를 건당 5만 자씩 손으로 붙여넣거나 레포를 도달 가능한 Git 원격(공개 또는 GHE App)에 올려야 한다. 즉 이 도구의 자연스러운 결은 "Confluence 위키 + GHE 레포에 이미 있는 팀 지식을 binder로 묶어 chat/Query API로 회수"하는 루프이지, "내 로컬 코드베이스를 실시간으로 물려 코딩 중에 질의"하는 개인 루프가 아니다. 프로그래매틱 통합 자체는 가능하다 — Query API(`/projects/.../query`)나 MCP Hub export로 에이전트에서 미리 채워둔 binder를 질의하는 식(4번) — 하지만 이는 "미리 구축된 binder + 사내 신원"을 전제하므로, 개인의 턴키 로컬 도구가 아니라 사내 팀 지식 재사용 채널로 보는 게 맞다.
