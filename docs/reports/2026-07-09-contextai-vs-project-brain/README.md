# ContextAI vs project-brain 분석 보고서 (2026-07-09)

Claude Code 세션에서 만든 ContextAI와 project-brain 비교 분석의 상세 보고서를
엔진 문서로 보존한 디렉터리다.

- 원 세션: `f61d4690-5ece-442c-a11e-80d3fa87e36f`
- 제목 세션: `923a726f-84f4-40cf-9abd-186f9c92447f`
- 원 스크래치패드:
  `/private/tmp/claude-501/-Users-al03040455-Downloads-codes-project-brain/f61d4690-5ece-442c-a11e-80d3fa87e36f/scratchpad/wf-out/`
- ContextAI 조사 clone: 보고서 본문 기준 `/private/tmp/.../scratchpad/context-ai`

## 결론 요약

ContextAI는 project-brain을 대체하는 물건이 아니라 역할이 다르다. ContextAI는 회사
위키·원격 코드·텍스트를 binder로 묶어 답하는 서버형 맥락 검색 도구이고,
project-brain은 로컬 프로젝트 안에서 결정·인사이트·용어·근거를 구조화해 누적하는
검수형 기억 엔진이다.

채택 후보는 세 가지다.

- B2: raw 청크에 heading breadcrumb 접두
- B3: query 스킬의 다중 쿼리 변형
- B4: query 스킬의 grounding 규율 강화

B1 증분 재색인은 보류했다. LLM 관련성 필터, 멀티유저 권한, Prometheus 관측성은 현재
project-brain 단계와 맞지 않아 기각했다.

## 상세 보고서

- [report-a-search-pipeline.md](report-a-search-pipeline.md): ContextAI 인덱싱·검색 파이프라인
- [report-b-agent-mcp-surface.md](report-b-agent-mcp-surface.md): 에이전트 구조와 MCP 표면
- [report-c-evaluation-quality.md](report-c-evaluation-quality.md): 평가·품질 체계
- [report-d-design-strategy.md](report-d-design-strategy.md): 설계 문서와 전략 문서
- [report-e-adoption-operations.md](report-e-adoption-operations.md): 도입 장벽과 운영 조건
- [report-f-wiki.md](report-f-wiki.md): ContextAI 위키 조사
- [report-g-projectbrain-inventory.md](report-g-projectbrain-inventory.md): project-brain 현재 구현 인벤토리

## 교차 검토

- [lens-replaceability.md](lens-replaceability.md): 대체 가능성 관점 검토
- [lens-benchmarking.md](lens-benchmarking.md): 벤치마킹 관점 검토
- [lens-complementarity.md](lens-complementarity.md): 보완 관계 관점 검토

## 주장 검증

- [claims-replaceability.md](claims-replaceability.md): 대체 가능성 관련 핵심 주장 검증
- [claims-benchmarking.md](claims-benchmarking.md): 벤치마킹 관련 핵심 주장 검증
- [claims-complementarity.md](claims-complementarity.md): 보완 관계 관련 핵심 주장 검증

## 읽는 법

보고서의 `파일:줄` 근거는 조사 당시 ContextAI clone과 이 레포의 파일 상태를 기준으로 한다.
ContextAI가 이후 바뀌었을 수 있으므로, 새 의사결정에 재사용할 때는 현재 ContextAI 저장소와
project-brain 코드를 다시 확인한다.
