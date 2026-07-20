### CLAIM: ContextAI에는 로컬 파일·디렉토리 소스가 없어, 로컬 지식 주입은 텍스트 붙여넣기(건당 5만 자) 또는 도달 가능한 Git 원격 push뿐이며 커밋 안 된 로컬 작업 디렉토리는 색인 불가다(보고서 E §3, 코드 실증).
- 판정: CONFIRMED
- 근거: 주장의 네 요소 모두 ContextAI 코드·스펙에서 직접 확인, 반례 없음.

1) 로컬 파일/디렉토리 소스 부재: src/context_ai/source_registry.py:47-57 의 DEFINITIONS가 소스 타입 전체(wiki, code, text, jira, log, mcp, context7, k8s, imon, web_search)를 담는 단일 원본인데 로컬 파일/디렉토리 타입이 없음. web/*.html 에서 type="file"/FileReader/dropzone 검색 결과 0건 — 텍스트 입력은 textarea 붙여넣기뿐.

2) 텍스트 붙여넣기 건당 5만 자: src/context_ai/sources/text.py:52 MAX_CONTENT_LENGTH = 50000, add_text 에서 초과 시 ValueError. web/index.html TEXT_MAX_LENGTH: n, textarea maxlength=n. docs/specs/source-text.md "최대 50,000자 ... 바인더에 text 소스 여러 개 등록 가능"(=건당 상한 정확).

3) 도달 가능한 Git 원격 push: src/context_ai/db/source_configs.py:204-236 validate_git_url 이 git@(SSH) 거부, https:// 아니면 거부, host를 config.get_ghe_allowed_hosts() 화이트리스트로 검증, https://<host>/<owner>/<repo> 포맷 강제 → 로컬 경로·file:// 불가. src/context_ai/sources/repo.py clone_repo_for_source 는 is_host_allowed 후 Repo.clone_from/fetch로 원격 클론. ADR docs/adrs/0003-...md "Adding a new code source is just a git clone."

4) 커밋 안 된 로컬 작업 디렉토리 색인 불가: 코드 적재는 도달 가능한 화이트리스트 HTTPS 원격 클론만이 경로라 로컬 미커밋 내용은 어느 원격에도 없어 클론·색인 불가. 반례 후보였던 code_read "local filesystem"(src/context_ai/tools/code.py:233)은 _get_all_repo_paths→get_source_repo_path 즉 서버측 클론본을 읽는 것이고, 샌드박스 /upload(src/context_ai/sandboxserver/server.py:113)는 코드실행 /workspace/ 용이라 둘 다 지식 적재 경로가 아님.
- 정정: -
- 왜 중요: 이게 거짓이라면(로컬 소스가 존재하거나 로드맵에 있다면) '내 로컬 코딩 루프' 구멍이 사라져 대체 불가 논리의 핵심 기둥이 무너진다.

### CLAIM: ContextAI는 기존 소스 위 RAG/검색 제품으로 검수 사다리·DecisionRecord·Insight 같은 누적 큐레이션 지식 객체 모델이 없고, 설계상 '검색 알고리즘은 계약도 아니고 결과 경계만 고정'한다(보고서 A, D §0/§2-1). 반면 project-brain은 검수 상태·근거가 붙은 구조화 객체 코퍼스다(보고서 G §1).
- 판정: CONFIRMED
- 근거: ContextAI = RAG/검색 over 기존 소스: README.md:3-5 (NotebookLM 스타일, binder가 소스 묶고 citation), 검색은 dense+lexical+RRF+rerank (sources/wiki_index_store.py:1399, sources/text.py:327, docs/contracts/knowledge-tools.md:26). DB 모델(src/context_ai/db/models.py)은 전부 Binder/Source/WikiPageManifest/WikiScopeSession/Chat — 큐레이션 지식 객체 없음. 큐레이션 객체 모델 부재: rg 'DecisionRecord|Insight|GlossaryTerm|evidence_ref|knowledge object' ContextAI 전체 0건; 유일한 review 객체 WikiScopeSessionRow(models.py:227-228)는 '인덱싱 대상 페이지 범위 확정' 워크플로일 뿐 검수 사다리 지식객체 아님; crud.py:1678 promote는 binder status 승격이지 지식 검수 아님. '검색 알고리즘은 계약 아니고 결과 경계만 고정': docs/contracts/knowledge-tools.md:26-27 '계약은 특정 알고리즘이 아니라 결과 경계다', knowledge-tools-review.html:387-388, docs/contract-rule.md:19. project-brain 구조화 객체 코퍼스: src/project_brain/schema.py — kinds GlossaryTerm/DecisionRecord/DomainMapping/Insight/ReviewRecord, 공통 필수필드 status+evidence_refs(:6-7), candidate→reviewed→rejected 검수 사다리(:184-273).
- 정정: 주장의 네 하위 진술 모두 코드·문서에서 직접 확인됨. 단 한 가지 뉘앙스: ContextAI 자체 포지셔닝 문서(docs/strategy/platform-positioning.md:12)는 'Binder는 또 하나의 검색 제품이 아니다'라며 '검색 제품' 라벨을 명시적으로 거부하고 재사용 가능한 서비스 문맥 계층으로 자기규정한다. 따라서 보고서의 'RAG/검색 제품'이라는 표현은 ContextAI가 프레이밍상 이의를 제기할 단순화다. 그러나 이는 아키텍처 반증이 아니라 마케팅 프레이밍 차이일 뿐이고(실제 회수 메커니즘은 기존 소스 인덱싱 위 검색), 핵심 구별점인 '검수 사다리/DecisionRecord/Insight 같은 누적 큐레이션 객체 모델 부재'는 그대로 성립하므로 판정을 뒤집지 않는다.
- 왜 중요: 이게 거짓이라면(ContextAI가 누적 큐레이션 모델을 갖췄다면) '다른 종류의 일'이라는 논지가 약해져 대체 가능 쪽으로 기운다.

### CLAIM: ContextAI 자기 전략 문서가 '내 레포 탐색은 Claude Code/Codex가 낫고, ContextAI는 내가 관리 안 하는 남의 팀 서비스 문맥에 쓴다'고 스스로 경계를 긋는다(보고서 D §3-1 use-cases.md:22,175, F §3).
- 판정: CONFIRMED
- 근거: ContextAI 전략 문서가 경계를 명시적으로 긋는다. context-ai/docs/strategy/use-cases.md:22 "개발자가 이미 담당하는 저장소 안에서 파일을 찾고 수정 방향을 잡는 일은 Claude Code나 Codex 같은 코딩 도구가 더 적합하다. ContextAI의 개발자 유즈케이스는 로컬 개발환경 바깥의 서비스 맥락, 다른 팀 코드... 장면에 둔다." 재확인: 같은 파일 :37 "내 저장소 탐색을 대체하는 것이 아니라, 내가 직접 관리하지 않는 서비스의 실제 동작을 확인하는 데 쓴다", :381 "로컬 저장소 탐색은 코딩 도구에 맡기고, 바인더는 그 도구가 모르는 사내 문서·운영 규칙·타 서비스 맥락을 공급한다", 그리고 docs/presentations/pj-air-20260528/script.md:59 "자기 서비스 코드라면 로컬에서 Codex나 Claude Code를 바로 쓰면 됩니다. ContextAI가 더 유용한 경우는 다른 팀 서비스나 외부 호출 대상의 코드 레벨 맥락까지 확인해야 할 때입니다." 반례 탐색(자기 레포 탐색 대체 주장) 결과 상충 문구 없음.
- 정정: 주장 자체(경계 긋기)는 참이나 인용 좌표 하나가 어긋난다. use-cases.md:175는 경계와 무관한 PM 릴리즈 영향 질문("QA, 운영, 지원팀이 각각 알아야 할 내용은?")이다. 경계를 실제로 뒷받침하는 줄은 22(핵심)와 37·381이다. 즉 :22는 정확, :175는 오인용. 보고서 F §3는 제공 재료에 없어 그 인용은 검증 불가(주장 실질은 1차 문서로 CONFIRMED).
- 왜 중요: 벤더 본인이 project-brain 영역(내 프로젝트 로컬 루프)을 대체 대상에서 제외한다는 직접 증거다. 거짓이면 '역할 분담' 결론의 가장 강한 근거가 사라진다.

### CLAIM: ContextAI는 형태소 분석기도 BM25 전문검색도 없고(rg 전수 0건), 어휘 매칭은 본문이 아닌 제목·경로·id 메타데이터에만 LIKE로 걸려 본문에만 나오는 희귀 한국어 용어는 dense recall에만 의존한다(보고서 A §4/§5). 위키의 '하이브리드 BM25' 주장(F §2)은 코드와 어긋난다.
- 판정: CONFIRMED
- 근거: context-ai/src/context_ai/providers.py:1055,1071,1131-1138; context-ai/src/context_ai/sources/wiki_index_store.py:1374-1388,1443,1538,1556-1563; context-ai/src/context_ai/sources/confluence_client.py:183-184; 레포 전체 rg(bm25/fts5/tsvector/to_tsquery) 0건; Confluence wiki pageId 3854108940 (ContextAI - 02. Architecture) Tech Stack + Integration Points 표
- 정정: 주장 본문은 사실로 확정. 단 하나 정정: 보고서가 "F §2"로 인용한 '하이브리드 BM25' 문구의 실제 출처는 '06 Release'(=F로 추정)가 아니라 '02. Architecture' 위키 페이지(pageId 3854108940)의 Tech Stack/Integration Points 표다. 즉 위키가 그 주장을 한다는 사실은 맞지만, 인용 라벨(F)-페이지 매핑은 실측상 02(Architecture)로 확인됨. 또 어휘 매칭 대상 메타데이터는 "제목·경로·id" 3종이 아니라 정확히 title(8)/heading_path(6)/heading_anchor(5)/page_id(6)/source(4) 5종 — 모두 메타데이터이고 본문 아님이라는 취지는 동일.
- 왜 중요: 한국어 검색 비교의 근거. 거짓이라면(실제 본문 BM25가 있다면) project-brain의 한국어 어휘 recall 우위 주장이 약해진다.

### CLAIM: ContextAI MCP Export는 저장소 자체엔 서버가 없고 외부 Flava MCP Hub 경유이며(보고서 B §0), 위키상 라이브라 해도 현재 public+ready 바인더만·인증 없음(FCP 이관 후 Athenz 인증 예정)이다(보고서 F §2/§4).
- 판정: CONFIRMED
- 근거: 파트1(코드, 보고서 B): 저장소에 서버 없이 외부 Flava MCP Hub 경유 — CLAUDE.md:20 "MCP Export는 apiserver가 직접 /mcp/*로 제공하지 않고 Flava MCP Hub 경로로 제공한다"; src/context_ai/config.py:395-401 "MCP Export (Flava MCP Hub)" (mcp_export_endpoint/mcp_project_export_endpoint); web/chat.html:5225 "expose a binder as an MCP server via the Flava MCP Hub" + connector @linecorp/flava-mcp-connector; docs/designs/project-binder-service-account-design.md:245,265 "Apiserver가 직접 /mcp/*를 제공하지 않는다는 원칙은 유지". 전수 grep 결과 저장소에 서버측 /mcp/{binder_id}/ 라우트·StreamableHTTP MCP 서버 없음(tools/mcp.py·sources/mcp_client.py는 외부 서버를 소비하는 MCP '클라이언트'일 뿐). 파트2(위키, 보고서 F): 위키 페이지 02 Architecture(id 3854108940) MCP Server 섹션에 "Only public + ready binders are exposed", "Currently no authentication (FCP migration will add it)", Auth 표 "MCP | None (public binders only) | Anonymous" 및 "FCP migration will add Athenz-based auth"로 3개 사실 모두 그대로 확인됨.
- 정정: 주장 자체는 두 근거(코드·위키) 모두에 정확히 부합해 CONFIRMED이지만, 반박 시도 중 실질적 불일치 하나를 확인함: 위키 페이지 02는 여전히 ContextAI 자신을 /mcp/{binder_id}/를 직접 서빙하는 MCP 서버로 기술하고 oauth2-proxy가 /mcp/*를 인증 예외로 둔다고 적혀 있어, 코드(외부 Flava MCP Hub 경유, apiserver는 /mcp/* 미제공)와 어긋난다. 즉 위키가 코드보다 오래된 자체호스팅 모델을 담고 있다. 주장은 파트1을 코드(보고서 B)에, 파트2를 위키(보고서 F)에 각각 귀속시키고 "위키상 …라 해도"로 이 간극을 명시하므로 반박되지 않는다.
- 왜 중요: '코딩 중 Claude Code가 사내 민감 프로젝트 지식에 MCP로 붙는다'는 지금-시점 대체 논리의 실용성을 좌우한다. 거짓이면(인증·private 지원이 이미 되면) 지금 대체 가능성이 올라간다.
