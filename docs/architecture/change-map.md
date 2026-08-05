# Project Brain 변경 지도

이 문서는 “어디를 고치고 어디까지 확인해야 하는가”를 현재 코드 구조에 맞춰 연결한다.
production 파일 하나만 보고 검증 범위를 줄이지 않는다. 먼저 변경이 코퍼스 쓰기, 색인 입력,
회상·게이트, 설치 runtime 중 어디까지 영향을 주는지 분류한 뒤 아래 표를 따른다.

## 검증 층

1. 바꾼 동작과 가장 가까운 표적 테스트를 TDD로 먼저 실패시킨다.
2. 엔진 합성 회귀를 돌린다.
3. 설치 템플릿이나 ingest 흐름을 건드렸다면 설치되는 runtime unittest와 installer 회귀를
   함께 돌린다.
4. schema, 검색 품질, 색인, router, gate, ranking처럼 실제 데이터에 따라 결과가 달라지는
   엔진 변경은 소비 데이터 레포의 `brain/checks`와 `eval`까지 확인한다.
5. 색인에 들어가는 텍스트·청크·토큰·벡터·DB 계약이 바뀐 경우에만 실모델 index를 한 번
   rebuild한다.

P0 coverage·timestamp·receipt·installed runtime 변경은 가장 가까운 **focused** 테스트와 fresh
**full** pytest, 설치 runtime unittest를 함께 돈다. 실제 저장·검색 표면을 바꾸는 변경이면
소비 데이터의 `brain/checks`와 eval까지 확인한다. 문서·template·검증 코드만 바뀌고 index 입력과
실제 corpus가 그대로면 **rebuild 불필요**다.

문서의 과거 통과 수치나 다른 checkout의 bare `project-brain` 실행은 현재 변경의 영수증이 아니다.
검증할 checkout의 `PYTHONPATH`와 `.venv/bin/python`을 같이 고정한다.

## 변경별 검증 표

| 변경 축 | 주요 production 파일 | 엔진 표적 테스트 | 설치 runtime·installer | 소비 데이터 회귀 | `eval` | 실모델 rebuild 조건 | 함께 확인할 계약 |
|---|---|---|---|---|---|---|---|
| schema·ID·reference·store | `schema.py`, `id_grammar.py`, `reference_fields.py`, `store.py`, `lint.py` | `test_schema.py`, `test_id_grammar.py`, `test_reference_fields.py`, `test_store.py`, `test_lint.py`, `test_mutation.py` | 설치 JSON·적재 안내가 바뀌면 runtime + `test_installer.py` | `brain/checks` + `lint` + `audit` | 검색·라우팅 표면 영향이 있으면 필요 | required/ID만 바뀌고 indexed surface가 같으면 불필요. surface·fingerprint 입력 또는 실제 corpus가 바뀌면 필요 | 19종 kind 집합, legacy read와 신규 write, graph/lint/rewrite registry |
| assembly·ingest | `assembly.py`, `ingest.py`, `mutation.py`, `templates/ingest/**` | `test_assembly.py`, `test_ingest.py`, `test_mutation.py`, `test_universal_ingest_e2e.py` | 항상 runtime unittest, 템플릿 변경이면 `test_installer.py`와 두 번째 install 무변경 확인 | `brain/checks` + 실제 `lint`/`audit` | 새 객체가 회수돼야 하거나 표면이 바뀌면 필요 | 코드·템플릿만 바뀌고 색인 입력이 같으면 불필요. 실제 ingest action 뒤에는 DB가 무효화되므로 후속 search/eval 전 필요 | build는 corpus를 쓰지 않음, precondition, CodeLocator verifier, semantic finalization |
| coverage·timestamp·receipt | `coverage.py`, `assembly.py`, `write_semantics.py`, `mutation.py`, `transaction_receipt.py`, `cli.py` | `test_coverage.py`, `test_assembly.py`, `test_write_semantics.py`, `test_mutation.py`, `test_transaction_receipt.py`, `test_cli.py` | coverage 전파·finalizer가 바뀌면 runtime unittest + installer 2회 | `brain/checks` + 실제 `audit`; corpus를 썼다면 lint/eval | 저장 객체나 회수 결과가 바뀌면 필요 | 계약·문서·receipt 코드만 바뀌고 실제 corpus/index 입력이 같으면 rebuild 불필요. action이 있으면 후속 search 전 필요 | exact expected planner, MutationService 단일 clock, mutation/no-op receipt, foundation gate |
| P0 foundation gate·handoff | `foundation.py`, `installer.py`, `templates/ingest/scripts/validate_foundation.py` | `test_foundation.py`, `test_installer.py`, `test_snapshot.py`, `test_architecture_docs.py` | 설치 runtime unittest + 첫/두 번째 install report의 target-relative 경로·control file·두 번째 무변이 확인 | 엔진 단계는 합성 repo만 사용. 실제 BB2 baseline·gate·snapshot handoff는 Task 15에서 명시적으로 한 번 실행 | gate 자체는 기존 eval command를 실행하지만 검색 입력을 바꾸지 않음 | finalizer와 index rebuild를 호출하지 않으므로 불필요 | baseline/gate SHA 결속, command 전후 불변식, audit stale 유일 허용 변화, 독립 snapshot verify, 게시 후 artifact 두 번 재확인 |
| mutation·transaction | `mutation.py`, `corpus_io.py`, `transaction_receipt.py`, `ingest.py` | `test_mutation.py`, `test_corpus_io.py`, `test_ingest.py` | ingest 호출·영수증 계약이 바뀌면 runtime | `brain/checks` + `lint`/`audit`; 적용·rollback smoke | 검색 가능한 객체 결과가 바뀌면 필요 | 코드만 바뀌고 index 계약이 같으면 불필요. 실제 action이 있는 mutation은 DB를 무효화하므로 후속 search/eval 전 필요 | plan/apply 결속, lock, rollback, 파생물 무효화, batch receipt |
| 한국어 tokenizer | `tokenize_ko.py` | `test_tokenize_ko.py`, `test_search_index.py`, `test_search.py` | 보통 불필요 | `brain/checks` + `eval` | 필요 | **필요** | index/query tokenizer 대칭, 정규식 fallback 결정론 |
| surface·raw chunk·index schema | `surface.py`, `raw_chunks.py`, `search_index.py` | `test_surface.py`, `test_raw_chunks.py`, `test_search_index.py`, `test_search.py` | 적재 finalizer의 기대 행·결과가 바뀌면 runtime | `brain/checks` + `eval` | 필요 | **필요** | 객체 lane과 raw lane 분리, corpus fingerprint, 원자 DB 교체 |
| embedder | `embedder.py`, `search_index.py` | `test_embedder.py`, `test_search_index.py`, `test_search.py` | 보통 불필요 | `brain/checks` + `eval` | 필요 | 모델·차원·벡터 생성 계약 변경 시 **필요** | index/query 모델 이름·차원 대칭, 테스트는 StubEmbedder |
| router·intent·gate·ranking | `intent.py`, `router.py`, `search.py`, `status.py`, `eval_harness.py` | `test_router.py`, `test_search.py`, `test_status.py`, `test_eval_harness.py` | query/ingest finalization 출력 계약이 바뀌면 해당 runtime | `brain/checks` + `eval` | 필요 | 색인 입력과 저장 DB가 그대로면 불필요 | exact route 우선, query fallback, five channels, 경로별 status/redaction/stale 표시와 미적용 경계 |
| graph·reference 시각화·support | `reference_fields.py`, `graph.py`, `graph_viz.py`, `search.py` | `test_reference_fields.py`, `test_graph.py`, `test_graph_viz.py`, `test_search.py` | 보통 불필요 | 실제 `lint`/`audit`/`graph`; ranking support에 영향이면 checks + eval | search graph support가 바뀌면 필요 | DB 입력이 그대로면 불필요 | graph·lint·reference rewrite의 registry 공유, 외부 식별자 제외, 기본 고립 잎 kind |
| projection | `context_projection.py`, `hash_utils.py`, `lint.py`, `search.py`, `search_index.py` | `test_context_projection.py`, `test_lint.py`, `test_search.py`, `test_search_index.py`, `test_mutation.py` | 설치된 query 흐름이 바뀌면 installer/runtime | `brain/checks` + `eval` | 필요 | indexed payload, source fingerprint, surface 코드가 바뀌면 필요. 실제 projection write/repair 뒤에도 DB가 무효화되므로 후속 search/eval 전 필요 | creator의 source IDs, semantic hash, manual-edit 정책, 별도 `projection_reuse` lane |
| stale·mark-checked·code verify·audit | `stale_check.py`, `code_verify.py`, `symbol_verify.py`, `audit.py`, `quote_access.py`, `cli.py` | `test_stale_check.py`, `test_code_verify.py`, `test_symbol_verify.py`, `test_audit.py`, `test_quote_access.py`, `test_mutation.py`, `test_cli.py` | audit/ingest skill 절차가 바뀌면 installer/runtime | `brain/checks` + 실제 `audit` | 회수 라벨·advisory가 바뀌면 필요 | 코드만 바뀌면 보통 불필요. 실제 `mark-checked` 갱신 뒤 search/eval을 돌리면 무효화된 DB rebuild 필요 | full SHA·quote·symbol, branch ancestry, stale cache, `--no-stale`, ACL 미집행 경계 |
| CLI·config·installer | `cli.py`, `config.py`, `installer.py`, `templates/**` | `test_cli.py`, `test_config.py`, `test_installer.py`, `test_doctor.py`, `test_architecture_docs.py` | 템플릿·실행 스크립트 변경 시 항상 runtime; install 두 번의 두 번째 report가 빈 변경인지 확인 | 소비 프로젝트 설치 smoke. 검색 동작도 바뀌면 checks | CLI가 검색 결과 계약을 바꾸면 필요 | install/bootstrap이 색인을 새로 만드는 경우 외에는 불필요 | `명시 인자 > config > ConfigError`, 사용자 수정 보존, overlay 비관리, 실행 비트·퇴역·rollback |
| session·session-ingest | `session.py`, `cli.py`, `templates/session-ingest/**` | `test_session.py`, session CLI와 skill contract 테스트 | session-ingest template이 바뀌면 installer/runtime | 실제 transcript scan·marker smoke는 필요할 때 별도 | 불필요 | 불필요 | transcript 해석은 스킬, CLI는 scan·marker만; marker는 코퍼스 밖 |
| snapshot·context replace·migration·canonical repair | `snapshot.py`, `context_replace.py`, `migration.py`, `canonical_repair.py`, `canonical_merge.py`, `mutation.py`, `corpus_io.py` | `test_snapshot.py`, `test_context_replace.py`, `test_migration.py`, `test_canonical_repair.py`, `test_canonical_merge.py`, `test_mutation.py`, `test_corpus_io.py` | 보통 불필요 | 실제 적용은 별도 승인 아래 snapshot verify, corpus checks, lint/audit, rollback 증거 | 적용 뒤 사용자 회수 계약을 확인할 때 필요 | 실제 context/migration apply는 DB를 무효화하므로 후속 search/eval 전 필요. snapshot restore는 포함된 DB의 freshness를 다시 확인 | plan/apply hash 결속, snapshot, precondition, reference rewrite, 보존 문제 종료 조건 |
| architecture 문서·계약 예시 | `docs/architecture/**`, `AGENTS.md`, `README.md`, `ROADMAP.md`, 설치되는 object template | `test_architecture_docs.py`, `test_object_contract_templates.py` | 설치 reference를 건드리면 `test_installer.py` + runtime | 불필요 | 불필요 | 불필요 | CLI·kind·operation 집합 드리프트, JSON parse/schema/lint/write-gate 층 구분 |

## index rebuild 판단

다음 중 하나라도 바뀌면 소비 데이터의 기존 DB를 그대로 두고 `eval`하지 말고 실모델로
`index rebuild`를 먼저 한다.

- `surface.py`가 만드는 색인 텍스트나 대상 kind
- `raw_chunks.py`의 청크 경계·본문·메타데이터
- `tokenize_ko.py`의 색인/질의 토큰 계약
- embedder 모델, 차원, 정규화, 저장 벡터 계약
- `search_index.py`의 DB schema, extractor/tokenizer/model version, corpus fingerprint 입력
- 실제 action이 있는 corpus mutation이 실행된 경우. 현재 transaction은 index DB를 무효화하므로
  후속 `search`·일반 `eval` 전에 rebuild가 필요하다.
- `ContextProjection`의 indexed payload나 source fingerprint가 바뀐 경우

반대로 router, intent 분류, 답변 gate, 결과 채널 배치, RRF 이후 ranking만 바뀌고 색인 입력과
기존 DB가 같다면 rebuild는 생략할 수 있다. 이 경우에도 `brain/checks`와 `eval`은 생략하지 않는다.

## 기본 명령

엔진 checkout에서:

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest -q
PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
git diff --check
```

검색 품질·색인·라우터에 영향을 주는 엔진 변경은 소비 프로젝트 루트에서 검증할 checkout을
명시한다.

```bash
PYTHONPATH=<engine-root>/src <engine-root>/.venv/bin/python \
  -m unittest discover -s brain/checks -p 'test_*.py'
PYTHONPATH=<engine-root>/src <engine-root>/.venv/bin/python \
  -m project_brain.cli index rebuild   # 위 조건에 해당할 때만
PYTHONPATH=<engine-root>/src <engine-root>/.venv/bin/python \
  -m project_brain.cli eval
```

문서만 바꿨다면 architecture 표적 테스트와 엔진 suite로 드리프트를 확인한다. 설치 템플릿이나
reference를 바꾼 경우에는 문서-only로 줄이지 말고 installer와 설치 runtime까지 확인한다.
