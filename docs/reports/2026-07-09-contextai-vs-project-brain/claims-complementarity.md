### CLAIM: ContextAI에는 로컬 파일/디렉토리 소스가 없고, 지식 주입은 텍스트 붙여넣기(건당 5만 자)나 도달 가능한 Git 원격에 push하는 것뿐이라 로컬 작업 디렉토리를 실시간으로 색인할 수 없다(보고서 E: sources/repo.py, text.py, apiserver에 파일 업로드 라우트 없음).
- 판정: CONFIRMED
- 근거: 보고서 E의 세 근거가 모두 코드로 확인됨. (1) 로컬 소스 부재: 소스 카탈로그 src/context_ai/source_registry.py:47-58 + DataSourcesConfig src/context_ai/db/source_configs.py:409-431 = wiki/code/text/jira/log/mcp/context7/k8s/imon/web_search뿐, 로컬 디렉토리 색인 소스 없음. src/·web/ 전체 rg에서 UploadFile/multipart/File(/Form( 0건 → 파일 업로드 라우트 없음(apiserver/routers/binder.py 라우트 목록에도 없음). (2) 텍스트 5만 자: src/context_ai/sources/text.py:53 MAX_CONTENT_LENGTH=50000, add_text가 초과 시 ValueError(text.py:127-128), 내용은 붙여넣기 config content(TextSourceConfig.content, source_configs.py:129). (3) Git 원격 push만: CodeSourceConfig.validate_git_url(source_configs.py:204-236)이 https:// + GHE 허용호스트만 통과, git@/SSH·file://·자격증명·비2세그먼트 경로 전부 거부. clone_repo_for_source(sources/repo.py:336-427)가 원격 URL을 서버측 /data/repos로 clone, 갱신은 pull_source_repo(repo.py:467). code 소스의 로컬 경로 get_source_repo_path(repo.py:309)는 서버측 clone 디렉토리일 뿐 사용자 작업트리 아님. MCP 런타임 소스도 url 기반(source_configs.py:345)이라 로컬 파일시스템 접근 불가. 따라서 로컬 작업 디렉토리 실시간 색인 불가가 확인됨.
- 정정: -
- 왜 중요: 이게 틀려서 ContextAI가 로컬 코드베이스를 실시간 물릴 수 있다면, project-brain의 코딩 루프 내 로컬 회상이라는 핵심 일을 대체할 수 있게 되어 '대체 불가·별개 문제' 결론이 무너진다.

### CLAIM: ContextAI는 결정·인사이트·용어를 증류한 검수 지식 객체 타입이 없고 소스(wiki/code/text/jira)를 연합·회수만 한다. 반면 project-brain은 DecisionRecord/Insight/GlossaryTerm 등 19종 객체를 candidate→reviewed 검수 사다리로 누적한다(보고서 A·D vs G).
- 판정: CONFIRMED
- 근거: ContextAI 쪽(반례 없음): README.md:3-5 + CLAUDE.md:1-8은 "Context Registry / NotebookLM 스타일"로 소스를 Binder로 묶어 답하고 "원문으로 돌아갈 수 있는 citation"을 붙인다고 명시 — 연합+회수 성격. src/context_ai/db/models.py의 모든 테이블(Binder, BinderSource, WikiPageManifest, JiraIssueManifest/Record 등)은 연합·인덱싱 산출물이며 증류/검수 지식 객체가 아님. src/context_ai/tools/knowledge.py:270,375의 knowledge_list/get는 source_type이 {wiki,text,jira}로 한정되고 원문 URL citation만 반환. src/·docs/ 전수 검색에서 DecisionRecord/Insight/GlossaryTerm/distill 히트 0. 유일한 "curated/reviewed" 히트인 config.py:409는 공개 Binder 목록을 reviewed yaml로 관리한다는 카탈로그 큐레이션이지 지식객체 검수 사다리가 아님(반례 아님). "candidate"/"reviewed" 나머지 히트는 Jira 권한 후보·PR AI review 등 무관.

project-brain 쪽(주장 지지): src/project_brain/schema.py:10-36,74에 VALID_KINDS가 정확히 19종(DecisionRecord, Insight, GlossaryTerm, DomainMapping, TemporalFact 등 포함). schema.py:62 OBJECT_STATUS_VALUES={candidate, reviewed, superseded, archived, rejected}. src/project_brain/promote.py:70-90이 candidate→reviewed 승격 + ReviewRecord 발행을 구현.
- 정정: -
- 왜 중요: ContextAI가 실은 증류 객체를 만든다면 데이터 모델 직교성(보완성의 가장 강한 축)이 붕괴하고 두 도구가 같은 문제를 푸는 것이 된다.

### CLAIM: project-brain은 서버/HTTP/멀티유저가 없고 router가 acl/sensitivity를 읽지 않아 사용자별 접근 제어가 실집행되지 않는다. 신뢰는 검수 상태 + 콘텐츠 단위 redaction 라벨(fail-closed)이다(보고서 G, grep 0건).
- 판정: CONFIRMED
- 근거: project-brain 코드로 4개 하위주장 모두 확인. (1) 서버/HTTP 없음: pyproject.toml deps=numpy/sqlite-vec/sentence-transformers/kiwipiepy, 유일 진입점 CLI([project.scripts] project-brain=project_brain.cli:main, argparse); 레포 전체 grep(fastapi|flask|uvicorn|http.server|listen, md/lock 제외)=0건; current_user|principal|permission|authorize|authenticate grep=0건. (2) router가 acl/sensitivity 안 읽음: src/project_brain/router.py에서 'acl' 0건, 'sensitivity' 0건. 엔진 전체에서 acl/sensitivity는 오직 assembly.py:168-169(write 시 기본값 채우기)와 schema.py:11-12(필수 필드명)로만 등장, 접근 판정 read 없음. schema.py:3 주석 "router가 실제로 읽는 필드는 일부지만 적재 무결성 위해 spec 필수 필드 전체 강제". (3) 사용자별 접근제어 미집행: 사용자 신원 개념 자체가 엔진에 없음, acl은 저장만 되고 어떤 주체와도 대조되지 않음. (4) 신뢰=검수상태+콘텐츠단위 redaction(fail-closed): router.py:758-768 _restricted_for가 evidence_refs→manifest의 redaction_status!="approved"(None·키누락 포함)면 restricted 처리(fail-closed, line 767), status.py:10-18 claim_status가 restricted/reviewed/candidate 산출. 이는 EvidenceManifest 콘텐츠 단위이지 사용자별 아님. 검증재료의 context-ai(/private/tmp/.../context-ai)는 apiserver/auth/rate_limiter/db/web/mTLS를 갖춘 서버 앱이나 별개 패키지(pyproject name="context-ai")이며 project_brain을 import하지 않아(grep 0건) project-brain 스코프 주장을 반박하지 못함.
- 정정: -
- 왜 중요: 이게 틀리면 project-brain에도 권한 모델이 있는 셈이 되어 '신뢰 축이 다르다(인식론적 신뢰 vs 접근 신뢰)'는 보완성 구분이 흔들린다.

### CLAIM: ContextAI는 조회자 본인 PAT로 질의 시점에 소스 접근권을 확인해 못 보는 콘텐츠를 LLM에 아예 안 보내는 다중 사용자 권한 필터(fail-closed)를 가진다(보고서 B: access_mode.py, session_access.py).
- 판정: CONFIRMED
- 근거: 핵심 주장(다중 사용자·질의 시점·fail-closed·못 보는 콘텐츠 LLM 미전달)은 코드로 직접 확인됨. 다만 "조회자 본인 PAT"라는 표현은 위키/Jira에만 정확하고 코드는 다른 토큰을 쓴다(아래 nuance).

1) 다중 사용자 권한 필터: src/context_ai/services/access/access_mode.py:29-58 — AccessMode enum이 PRIVATE_OWNER / VIEWER_ENFORCED / SYSTEM_PUBLIC_ONLY로 조회자별 처리를 분기. apiserver/services/session_access.py:250-385의 build_session_context_from_token이 요청마다 조회자 정체성으로 접근 계획을 새로 만든다.

2) 조회자 본인 PAT로 질의 시점 확인: session_access.py:235-240(resolve_confluence_token — 조회자 username으로 PAT 조회), access_mode.py:143("confluence_token은 조회자의 복호화된 PAT"). 실제 페이지 단위 확인은 검색 시점에 조회자 토큰으로 CQL 질의: wiki_query_access.py:131-143(ConfluencePageAccessChecker.check, viewer_token 사용), knowledge_service.py:836-868(search)·1012-1081(get_document)·1161-1209(list_wiki_pages). 세션 시작 시 소스 단위 사전필터도 요청별로 수행(session_access.py:289-385).

3) 못 보는 콘텐츠 LLM 미전달: LLM 인터페이스인 tools/knowledge.py(120·321·421행에서 __access_context 획득)가 예외 없이 SecureKnowledgeStore를 경유(knowledge_service.py:1261·1352·1478). Store가 행을 반환 전에 필터링하므로 접근 불가 콘텐츠는 도구 결과에 포함되지 않음. 문서 계약도 명시: docs/contracts/binder-permissions.md:82-90("Editor가 인덱싱했더라도 다른 viewer에게 원본 권한 없으면 보여주면 안 됨").

4) fail-closed: wiki_query_access.py:140-143(토큰/URL/id 누락 시 raise 없이 제외), code_viewer_access.py:45-46·66-68, wiki_viewerless.py:8-11·133-144, knowledge_service.py:857·866-868(page_id 없는 행 드롭). 기본 AccessContext는 SYSTEM_PUBLIC_ONLY(knowledge_service.py:1259-1260). 조회자 정체성(unified_id) 없으면 코드 소스 전량 fail-closed 제외(session_access.py:267-270). wiki_viewer_unrestricted_fallback가 켜져도 인덱스시점 공개 행만 서빙하고 deny/unknown은 드롭(fail-closed 유지).

NUANCE(과잉주장 방지): 코드 소스는 조회자 "본인 PAT"가 아니라 공유 GitHub App 설치 토큰 + 조회자 github_login 협업자 권한 조회로 검사한다(code_viewer_access.py:1-11). "본인 PAT"는 위키(Confluence PAT)·Jira(Jira PAT)에만 해당. 또 인덱스시점 공개 스킵(ADR 0017)과 Confluence 검색 인덱스 지연(wiki_query_access.py:6-8)은 문서화된 트레이드오프로, 인덱싱 후 권한이 강화된 공개페이지가 서빙될 수 있음 — 설계상 명시된 한계이지 fail-closed 위반은 아님.
- 정정: -
- 왜 중요: ContextAI 신뢰 모델의 고유 가치(멀티유저 접근 통제)를 규정하는 근거로, 틀리면 '벤치마킹 후보=권한 모델' 및 '보완성' 판단이 바뀐다.

### CLAIM: 두 시스템을 같은 질의로 비교한 벤치마크가 이 보고서들에 없고, ContextAI는 커밋된 골든셋 베이스라인을 삭제해 결정론적 검색 관련성 테스트가 없다(보고서 C).
- 판정: CONFIRMED
- 근거: 동일 질의 상호 벤치마크 부재: `git grep -niE "project-brain"` (context-ai) 0건, project-brain에서 "context-ai" 0건 — 양쪽 코드/문서 어디에도 상호 비교 하네스 없음. 골든셋 삭제: 커밋 098bc1bd "Remove legacy query API" (2026-05-15, main·HEAD 조상)이 evals/regression/ 전체 삭제 — TEST_CASES_TEMPLATE.md(098bc1bd^ 기준 603줄, A1~C2 실제 골든 케이스 input/required_tools/must_contain), create_dataset.py(347줄), run_experiment.py(547줄), GUIDE.md, eval-20260311-*.html 베이스라인 리포트 6개, tests/unit/test_regression_eval_judge.py. 현재 evals/regression ABSENT. 현 상태: 남은 건 evals/auto_review.py(JUDGE_MODEL="us.anthropic.claude-sonnet-4-6"로 Langfuse 운영 트레이스 LLM-판정, 비결정론) + evals/triage_ui.html뿐, 2026-05-15 이후 골든셋 재추가 없음. 테스트의 relevance 히트(tests/unit/test_knowledge_filter_fallback.py:3)는 LLM relevance filter 컴포넌트 테스트로 검색 관련성 골든셋 아님. 캐비앗: 삭제된 스위트는 결정론 trajectory + LLM-판정 correctness의 e2e 에이전트 회귀 스위트였고 기대답변 데이터셋은 Langfuse(외부)에 있었음 — "순수 결정론적 검색 관련성 테스트"라는 표현은 약간 부정확하나, 주장이 단언하는 세 사실(커밋 골든셋 삭제됨/현재 결정론적 검색 관련성 테스트 없음/상호 벤치마크 없음)은 모두 성립.
- 정정: -
- 왜 중요: 사용자 전제 '품질이 밀리지 않으면'을 보고서로 실증할 수 없음을 뜻하므로, 결정 근거를 품질 비교가 아니라 문제-적합성으로 옮겨야 한다는 재프레이밍의 토대가 된다.
