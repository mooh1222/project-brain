# ContextAI 품질 측정 체계·프로젝트 성숙도 분석

조사 대상: `/private/tmp/claude-501/.../scratchpad/context-ai` (사내 Cloud-Native/context-ai clone, main HEAD `0a88d586`)

주의: 이 저장소는 CLAUDE.md 컨텍스트에 있는 `project-brain`(FTS5+bge-m3+RRF+그래프 하이브리드 엔진)과 **다른 프로젝트**다. ContextAI는 pgvector 임베딩 검색 + LLM 관련성 필터 + LangGraph ReAct 에이전트 기반의 NotebookLM형 어시스턴트다(`src/context_ai/providers.py:351-355` OpenAI `text-embedding-3-large`, README.md:1-5). 아래 판단은 전부 이 저장소 기준이다.

---

## 1. evals/ — 평가 방법론

### 현재 트리 (실측)
`evals/`에는 파일이 **딱 2개**뿐이다 (`ls evals/`): `auto_review.py`(29,502바이트), `triage_ui.html`(18,271바이트).

**방법론 = 골든셋이 아니라 "실사용 트레이스 LLM 심사관"**이다 (`evals/auto_review.py:1-14`, docstring "Langfuse Auto-Review Scorer"):
- 대상: 운영 Langfuse에 쌓인 **실제 유저 트레이스**를 날짜 범위로 가져와 평가 (`auto_review.py:484-515`). 테스트 유저(`woohhan`, `api-test`, `test-api`)는 제외 (`:38`).
- 2축 이진 판정 (`:44-135`): **answer_quality**("유저가 이 답변으로 다음 행동을 취할 수 있는가") + **tool_efficiency**("도구 호출이 최적 경로에 가까웠는가"). 각 축 verdict는 1 또는 0.
- 지표: 축별 pass 개수/비율(%)을 stdout에 집계 출력 (`:682-691`). 실패 유형 분류 택소노미도 기록 — answer는 `empty_response/off_topic/repetitive_failure/hallucination` 등, tool은 `wrong_order/skill_not_used/fragmented_queries/redundant_calls` 등 (`:130-135`).
- 심사관 모델: `us.anthropic.claude-sonnet-4-6` (Bedrock 게이트웨이 경유, `:37`).
- 비용 최적화 2단계: Stage1은 tool **출력 없이** 판정하고 "uncertain"이면 Stage2(출력 포함)로 승격 (`:137-180`, `:550-608`). 취소된 트레이스(빈 응답+cancel 에러)는 LLM 호출 없이 자동 pass (`:539-546`).
- 실패 케이스는 한국어로 번역해 Langfuse score metadata에 저장 → `triage_ui.html`로 검수 (`:622-666`, `:8`).
- **시나리오 수: 고정 시나리오 개념이 없다.** `--limit`(기본 50)만큼 최근 트레이스를 즉석 수집한다 (`:417`, `:484`).

**커밋된 실측 수치: 현재 트리에는 없다.** 점수는 Langfuse에 write될 뿐(`:651-666`) 저장소에 커밋되지 않는다. `find`로 `evals/regression/`·result 파일 없음 확인.

### 역사적 맥락 (git 실측 — 방법론이 한 번 바뀌었음)
과거엔 **커밋되는 골든셋 회귀 평가**가 있었으나 제거됐다:
- `evals/regression/`에 `run_experiment.py`(547줄), `create_dataset.py`(347줄), `GUIDE.md`, `TEST_CASES_TEMPLATE.md`(603줄), HTML 리포트들이 있었음. 방법론은 **2축**: trajectory(기대 tool 호출 여부, deterministic) + correctness(**OpenAI Evals A~E 분류** LLM judge, A=subset=FAIL / B=superset=PASS / C=동일=PASS / D=사실불일치=FAIL / E=무관차이=PASS) — `git show 098bc1bd~1:evals/regression/GUIDE.md`.
- 실측 리포트가 실제로 **git에 커밋된 적 있음**: 커밋 `7eeb5632`("chore: eval 리포트를 git에 포함", 2026-03-11) — HTML 6개("시간별 추이 추적 및 PR 리뷰에서 결과 확인" 목적).
- 이 골든셋 인프라는 **2026-05-15 커밋 `098bc1bd`("Remove legacy query API")에서 통째 삭제**됨(리포트 6개 + 스크립트 2개 + `tests/unit/test_regression_eval_judge.py` 동반 삭제). 즉 골든셋 평가가 테스트하던 legacy query API가 사라지면서 함께 폐기된 것으로 **추정**된다(같은 커밋에 묶여 삭제).
- 데이터 기반 개선 루프의 실제 사례도 커밋 이력에 남아 있다(현재 트리엔 없는 `long-running/report-agent-quality-improvement.md`, `git show ace3cfad`): **100건 유저 트레이스 분석(PR #209)** → 실패 빈도 `redundant_calls 18/100, wrong_order 1/100, hallucination 1/100` 측정 → 근거로 프롬프트·도구 설명 수정 PR #210/#211 제출. 재현 트레이스 ID와 diff까지 문서화돼 있었음.

정리: **평가 방식이 "커밋되는 골든셋 A~E judge"에서 "실트래픽 2축 LLM judge(비커밋)"로 이동**했다.

---

## 2. tests/ — 규모와 커버리지

### 규모 (실측)
- 테스트 파일 **248개**(`find tests -name "*.py" | wc -l`), 테스트 함수 **2,276개**(`grep -rh "def test_\|async def test_" | wc -l`).
- 레벨별 파일 수: unit 85, integration 49, invariants 21(+ viewer_permission 11), api_rc 20, contracts/apiserver 17, api 11, architecture 7, contracts/wiki 7, contracts/db 4, contracts/agent 2, regression 2(사실상 비어 있음 — `__init__.py`+`conftest.py`+README), helpers 2.
- 커버리지 계측 없음: `make test`는 `uv run pytest tests/ -v --ignore=tests/api/ --ignore=tests/api_rc/`(Makefile:17-19)이며 pyproject·Makefile에 coverage/cov 설정이 **하나도 없다**(`grep -niE "cov" 결과 0건).

### 무엇을 커버하나 (실측)
레벨 택소노미가 문서로 명시돼 있음(`tests/CLAUDE.md`): invariants=출시 게이트(보안·데이터 격리·fail-closed), architecture=드리프트 가드, contracts=계약(코드>테스트>자연어 우선), regression=`strict xfail` known-gap 추적기.
- **권한·격리에 매우 두껍다**: `tests/invariants/viewer_permission/`(11파일), `test_chat_isolation.py`, `test_metrics_endpoint_guard.py`, `test_binder_refresh_source_isolation.py`, `test_wiki_source_lifecycle_isolation.py` 등.
- **소스 수명주기·인덱싱 배관**: wiki/code/text/jira/imon lifecycle, `test_chunk_by_headings`, `test_wiki_prepare_chunks`, `test_wiki_index_timeout`, reindex/scheduled_reindex.
- **정적 드리프트 가드**(architecture): `test_metric_enum_drift`, `test_source_registry`, `test_tool_descriptions`, `test_no_blocking_in_async`.
- **강한 회귀**(api_rc): 로컬 서버 상대 릴리스후보 회귀. `test_chat_grounding.py`는 실LLM 마커(`pytestmark = [pytest.mark.rc_llm, pytest.mark.slow]`)로 근거 사용을 검증.

### 무엇을 안 하나 (실측 — 품질 관점 핵심 공백)
- **검색 관련성/랭킹 정확도를 검증하는 결정론적 테스트가 없다.** 검색 관련 파일(`test_chunk_by_headings`, `test_wiki_prepare_chunks`, `test_wiki_index_*`, `test_share_target_search`)은 전부 청킹·인덱싱·스코프·타임아웃 **배관**이지 "질의에 올바른 문서가 상위로 오는가"가 아니다.
- 관련성 테스트는 `test_knowledge_filter_fallback.py` 하나인데, 이건 LLM 관련성 필터가 **실패했을 때의 fallback 동작**(retry→drop)만 본다(`src/context_ai/tools/knowledge.py:147-173`, git `c9d6ec7e`). 관련성 판정 자체의 정확도는 검증하지 않는다.
- **답변 품질을 단위 테스트로 못 박지 않는다.** 답변 품질은 (1) 사후 Langfuse judge와 (2) `rc_llm/slow` 마커가 붙은 실LLM api_rc 테스트로만 확인된다 — 결정론적 게이트(`make test`) 밖.

---

## 3. TODO.md / TODO.later.md — 검색 품질·실사용성 관련 자인 부채

### TODO.md (현재 릴리즈, `## Product Quality`)
- `[agent]` `agent_recursion_limit` 기본값(150)을 histogram 1개월 수집 후 재조정(:19).
- `[observability]` prompt cache hit ratio 그래프 추가, 저트래픽 오탐 guard(:20).
- `[frontend]` 사용된 소스 하이라이트를 개별 source 카드까지 세분화(:21).

### TODO.later.md (뒤로 미룬 것)
- `[eval] Langfuse trace feedback loop` — **트레이스 결과를 eval/개발 에이전트가 다시 읽어 품질 개선 루프에 쓰는 방식을 "검토"**(:29). 즉 2번의 사후 judge를 자동 개선 루프로 닫는 일은 아직 착수 전.
- `[wiki/text] Citation 정밀도` — 청킹 전략 + spatial anchor 메타 + NotebookLM 인용 UX, **재인덱싱 필요**(:23). 인용 정밀도를 인지하고 있으나 미뤄둠.
- `[search] 멀티바인더 검색`(:33), `[source-wiki] Wiki source identity 정규화`(중복 소스 발생, :34), `[tool-result/citable] citation 가능 여부 단일 SoT 정리`(현재 hardcoded set·프롬프트 관습·출력 텍스트에 분산, post-GA 정리, :53).

요지: 팀이 인지한 검색·품질 부채는 대체로 **인용 정밀도, 소스 식별 중복, 품질 개선 자동 루프**이며 전부 later로 분류돼 있다.

---

## 4. git 활동

### 기여자 (실측, 이메일 기준 정규화)
동일인이 이름 표기 여러 개로 나타남. 이메일로 묶으면 **실제 사람은 3명**:
| 사람 | 이메일 | 커밋 수 | 비중 |
|---|---|---|---|
| Woo Hyung Han (woohhan) | woohhan@gmail.com + woohhan@linecorp.com | 754+456+263 = **1,473** | **~92%** |
| Hong Seong Pyo (홍성표) | seongpio.hong@linecorp.com | 79+33 = 112 | ~7% |
| Kim Taeuk (김태욱) | iam.taeuk.kim@linecorp.com | 12+12 = 24 | ~1.5% |

총 1,609커밋. **사실상 1인 주도**(bus factor 위험).

### 기간·PR (실측)
- 초기 커밋 2026-01-15(WooHyung Han "init") → 최신 2026-07-08. **약 6개월**.
- merge 커밋 기준 병합 PR **약 497개**, 최신 PR 번호 **#570**.
- 월별 커밋: Jan 141 / Feb 116 / Mar 290 / Apr 386 / **May 451(정점)** / Jun 221 / Jul 4(부분). 5월 정점 후 감소세.

### 최근 2주(2026-06-24 이후, 실측)
- 31커밋, 작성자 woohhan 29 + Kim Taeuk 2.
- 변경 집중 영역(파일 터치 수): `src/context_ai/apiserver/services`(38), `tests/unit`(34), `tests/invariants`(17), `tests/integration`(17), `src/context_ai/services`(17), `docs/contracts`(15), `db`(12), `apiserver/routers`(12), `agent`(10), `tools`(9).
- 최근 병합 PR 테마: **`quality/*` 브랜치 다수** — `quality/knowledge-no-result-guidance`(#565), `quality/imon-error-coverage`(#564), `quality/error-trace-stability`(#566), `quality/code-tool-search-guidance`(#563). 그 외 mockserver 프로젝트 스코프(#570), wiki 인덱싱 타임아웃 연장(#569), jira 소스(#561).
- 해석: 최근 초점 = **에이전트 품질 가이던스(프롬프트·도구 설명)·에러 커버리지 + 계약/목서버 정비 + wiki 인덱싱 견고화**. 검색 알고리즘 자체보다 에이전트 행동·계약 안정화 쪽.

---

## 5. CLAUDE.md — 개발 규율에서 드러나는 운영 방식

(`CLAUDE.md`, `tests/CLAUDE.md`, `tests/api_rc/CLAUDE.md` 실측)
- **계약 우선, 우선순위 명시**: "코드 > 테스트 > 자연어 계약". `docs/specs/`는 "점점 얇아져 결국 삭제되는 옛 영역"이라 새 진술을 안 받음(CLAUDE.md:17, 26-27).
- **테스트는 코드가 아니라 스펙·위험모델에서 도출**. invariant가 깨지면 구현을 고치지, invariant를 약화하지 않는다(필요시 유저 확인). 버그는 실패하는 회귀 테스트 먼저(`tests/CLAUDE.md`).
- **regression = strict xfail 강제장치**: known-gap을 xfail로 두고, 구현이 들어오면 자동 pass→strict가 실행을 flag해 invariants 승격을 강제(`tests/regression/README.md`).
- **"TODO는 기본값이 아니다"**: 통계적으로 TODO는 잊힌다 → 발견한 결함·정리는 이번 PR에 포함, 미루려면 비용·치명도·확률과 함께 유저에게 먼저 물음, LLM이 단독으로 "후속 PR 이관" 결정 금지(CLAUDE.md:30).
- **pre-push AI 리뷰(advisory)**: `.githooks/ai-review.py`(17,737바이트) + `reviewers/`. push를 막지 않고 `CONCERN`/`NIT` 코멘트만 출력, `make lint`/`make test` 실패만 push 차단. 기본 리뷰어 codex, `CTXAI_AI_REVIEWER=claude`로 전환(CLAUDE.md:72-79). 변경 단위당 1회 원칙.
- **결정 기록 문화**: `docs/adrs/`에 ADR 17건(0001~0017) — 에이전트 아키텍처(simple ReAct 채택, sub-agent 보류), LLM 선정(0011 GPT-5.4 유지), 소스 제거(0013 indexed_web) 등을 근거와 함께 남김.
- **관측성 계측**: `src/context_ai/utils/metrics.py`에 LLM 관련성 필터 결과(kept/dropped/error_dropped, retry recovered/exhausted, `:385-410`), chat 완료 결과별 카운트, recursion histogram, cached-token 비율 등 Prometheus 지표가 촘촘함.

---

## 종합 평가 — 이 팀은 품질을 얼마나 실측 기반으로 관리하는가

**에이전트 행동·제품 계약 축은 강하게 실측 기반이지만, 검색 관련성 품질 축은 결정론적 측정 밖에 있고 재현 가능한 커밋 베이스라인을 스스로 버렸다.** 강점은 분명하다 — 실트래픽 LLM 심사관(비용 최적화 2단계 + 트리아지 UI), 데이터 기반 개선 루프의 실증 사례(100트레이스 분석에서 `redundant_calls 18/100` 등 실패 빈도를 측정해 PR #210/#211로 프롬프트·도구를 고침), 2,276개 테스트의 규율 있는 레벨 택소노미와 strict-xfail 강제장치, 계약 우선·invariant 불약화·"TODO 기본값 아님" 같은 반(反)표류 규칙, 촘촘한 Prometheus 지표, ADR 17건. 이 정도면 사내 도구로선 상당히 성숙한 엔지니어링 규율이다. 그러나 약점도 뚜렷하다: (1) 과거 커밋되던 골든셋 A~E 평가·HTML 리포트가 2026-05-15에 통째 삭제돼(`098bc1bd`) **지금 저장소 안에는 버전 관리되는 품질 베이스라인 수치가 0건**이고, 품질 점수는 Langfuse에만 있어 PR에서 추이를 못 본다. (2) 남은 유일한 평가가 실트래픽 LLM judge라 팀 스스로 문서화한 심사관 변동성("run마다 grade가 흔들린다")에 노출된다. (3) **검색 관련성/랭킹 정확도를 못 박는 결정론적 테스트가 없어**, RAG 시스템의 핵심인 "올바른 문서를 상위로 올리는가"가 사실상 유일하게 계측이 약한 차원으로 남아 있다(런타임 LLM 필터로만 방어). (4) 커버리지 게이트 없음, 그리고 커밋의 ~92%가 1인이라는 지속성 위험. 결론적으로 **"에이전트가 잘 행동하는가"는 실측으로, "검색이 정확한가"는 주로 정성·사후·LLM 의존으로** 관리하는 팀이며, 재현 가능한 검색 품질 회귀 수치를 저장소에 다시 세우는 것이 성숙도상 가장 큰 미결 지점이다.
