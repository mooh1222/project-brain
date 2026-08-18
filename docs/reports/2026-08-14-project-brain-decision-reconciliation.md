---
role: "to-spec 전 research 입력"
status: "현재 상태와 결정 대조 완료; spec·인계문·구현 계획 아님"
current_as_of: "2026-08-14 KST; engine HEAD c8525b09b301a1bdd6a82ace7776214f4b668362; 조사 시작 시 dirty worktree"
decision_update: "2026-08-14 KST; 후속 grill 4건 사용자 승인 반영"
superseded_by: null
---

# Project Brain 현재 상태·결정 대조

## 목적과 판정

이 문서는 긴 설계 세션에서 나온 내용을 바로 사양으로 옮기기 전에, **현재 커밋의 구현 사실,
커밋되지 않은 WIP, 사용자가 합의했지만 아직 통합·구현하지 않은 설계, 폐기안, 미결정**으로
다시 나눈 연구 입력이다. 새 정본, 아키텍처 지도, 인계문, 실행 spec이 아니다. 승인된 통합
spec이 생기면 머리말의 `superseded_by`를 그 문서로 갱신할 대상이다.

결론은 세 가지다.

1. 현재 production 계약은 **19종 객체 + 설치 스킬 4종**이다. `GlossaryClassificationRecord`,
   공통 `candidate.verification`, `brain/drafts/<topic-id>.md`는 아직 없다.
2. 어휘 기준·후보 검증·지식 초안은 단순 아이디어가 아니다. 사용자가 방향을 명시적으로 고른
   **합의·미통합·미구현 설계**다. 다만 실행 가능한 필드·상태 전이·호환 계약은 아직 닫히지 않았다.
3. 이미 합의한 내용을 다시 처음부터 인터뷰하면 안 된다. 아래 미결정만 짧게 닫은 뒤
   `to-spec → 사용자 승인 → to-tickets`로 가야 한다.

## 근거 판독 규칙

이 보고서는 다음 1차 자료만 사용했다.

- 현재 커밋 사실: `git show c8525b09b301a1bdd6a82ace7776214f4b668362:<path>`와 현재
  production 코드·테스트. 작업 트리에서 수정된 스킬 파일은 반드시 `git show`로 HEAD와 분리했다.
- dirty WIP: `git status --short --branch`, `git diff --numstat`, `git diff -- <path>`.
- 사용자 결정: [원 세션 스냅샷](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt).
  같은 주제에서 내용이 바뀌면 뒤쪽의 사용자 정정과 최종 선택을 우선했다.
- 현재 설계 초안: [CONTEXT.md](../../CONTEXT.md)와 [ADR 6개](../adr/). 이 파일들은 사용자
  합의를 정리한 보조 근거지만 untracked이고, 코드나 승인된 통합 spec보다 높은 현재 정본이 아니다.
- 시점 감사: [새 방향 감사](2026-08-14-project-brain-fresh-direction-audit.md). 현재 구조를 찾는
  데는 쓰되, 그 문서의 과거 실행 수치를 이번 실행 결과로 바꾸어 말하지 않는다.

조사 시작 시 Git은 `main...origin/main [ahead 161]`, tracked 수정 20개
(`+524/-280`), staged 0개였다. 이 보고서 작성 전부터 존재한 미추적 사용자 파일과 설계 파일은
그대로 보존했다.

## 1. 현재 커밋 구현 사실

| 항목 | 현재 커밋에서 확인한 사실 | 1차 근거 | 정본 목적지 | 다음에 필요한 검증 |
|---|---|---|---|---|
| 엔진·데이터 경계 | 이 레포는 엔진과 합성 테스트를 소유하고, 실코퍼스는 소비 프로젝트 `brain/`이 소유한다. 현재 동작의 권위는 코드·테스트·CLI다. | [AGENTS.md](../../AGENTS.md), [아키텍처 진입점](../architecture/README.md#L33-L63) | `AGENTS.md`, `docs/architecture/README.md` | 아키텍처 진입점만 읽은 독립 에이전트가 2-레포 경계를 같은 말로 설명하는지 확인 |
| 객체 집합 | `VALID_KINDS`는 아래 19종뿐이다. 모든 객체의 공통 상태 값은 `candidate`, `reviewed`, `superseded`, `archived`, `rejected`다. | [schema.py](../../src/project_brain/schema.py#L18-L91) | `schema.py`, `data-contracts.md` | `VALID_KINDS`, ID grammar, template kind 집합, store 경로를 기계적으로 대조 |
| 저장·참조 | kind마다 `BrainStore._KIND_DIR`가 정본 경로를 정한다. 공통 참조 registry는 scalar, list, 중첩 locator를 순회하지만 대부분 대상 kind까지 강제하지 않는다. | [store.py](../../src/project_brain/store.py#L141-L170), [reference_fields.py](../../src/project_brain/reference_fields.py#L14-L47), [현재 엔진 빈틈](../architecture/data-contracts.md#L271-L287) | `store.py`, `reference_fields.py`, `data-contracts.md` | kind별 대상 kind 제약과 registry 밖 목록을 별도 테스트로 고정할지 spec에서 결정 |
| 검색 표면 | 검색 표면을 갖는 kind는 10종이며, `ContextProjection`은 `prompt_payload`만 별도 재사용 레인에 들어간다. 나머지 kind는 저장·관계·정확 query 보조에 남을 수 있으나 일반 검색 표면은 없다. | [surface.py](../../src/project_brain/surface.py#L29-L34), [extractor dispatch](../../src/project_brain/surface.py#L173-L204) | `surface.py`, `data-contracts.md` | 문서의 색인/비색인 표시와 `_EXTRACTORS` 집합을 자동 대조 |
| candidate 계약 | 공통 candidate 상태 enum은 있지만 candidate metadata의 실질 강제는 `GlossaryTerm`에 집중돼 있다. `Insight` candidate는 회상 통로가 없어 거부된다. | [schema.py](../../src/project_brain/schema.py#L75-L83), [GlossaryTerm 검사](../../src/project_brain/schema.py#L285-L315), [Insight 검사](../../src/project_brain/schema.py#L354-L373) | `schema.py`, 향후 통합 spec | 기존 19종의 candidate 허용·금지 표를 만든 뒤 종류별 fixture로 검증 |
| 수동 승격 | single promote는 대상의 `candidate` 영역을 제거하고 `reviewed`로 바꾼 뒤 `ReviewRecord`를 만든다. mutation 관문은 대상 집합·precondition·corpus fingerprint·candidate→reviewed 전이를 확인하지만 검증 신선도나 종류별 자격은 확인하지 않는다. | [promote.py](../../src/project_brain/promote.py#L72-L145), [mutation.py](../../src/project_brain/mutation.py#L1952-L2021) | `promote.py`, `mutation.py`, 향후 통합 spec | 기존 승격 호환 fixture와 새 verification 없는 후보의 읽기/쓰기 비대칭 테스트 |
| 자동 승격 | `promote-auto`의 현재 선별은 reviewed `DomainMapping`이 참조하는 non-conflict candidate `GlossaryTerm`과 근거를 중심으로 한다. 공통 verification readiness를 소비하지 않는다. | [promote.py](../../src/project_brain/promote.py#L16-L69), [새 방향 감사](2026-08-14-project-brain-fresh-direction-audit.md#L68-L74) | `promote.py`, CLI, 향후 통합 spec | 유지·전환·폐기 중 하나를 정한 뒤 기존 mapping-vouched 회귀를 보존 |
| 동의어·별칭 | `GlossaryTerm` 자체 검색 표면과 candidate exact match는 aliases를 쓰지만, reviewed glossary exact match는 대표어만, DomainMapping exact/surface 경로는 대표어+synonyms만 쓴다. 따라서 “동의어와 별칭은 같은 지식에 도달”은 아직 현재 동작이 아니다. | [surface.py](../../src/project_brain/surface.py#L58-L88), [router.py](../../src/project_brain/router.py#L645-L695) | `surface.py`, `router.py`, 향후 어휘 계약 | 대표어·동의어·별칭별 exact/scoped/BM25/graph 회귀와 모호성 순위 검사 |
| 지식 초안 | `KnowledgePage`와 `ContextProjection`은 기존 객체지만 이번에 논의한 지식 초안이 아니다. production source와 installer에는 `brain/drafts/<topic-id>.md` 계약이 없다. | [19종 계약표](../architecture/data-contracts.md#L145-L170), `rg -n "brain/drafts|지식 초안" src tests` 결과 없음 | 향후 통합 spec과 구현 뒤 `workflow-map` | raw·객체·색인·snapshot에서 제외되는지 자동 검사 |
| architecture 계약 | 현재 living architecture는 `README`, `runtime-map`, `data-contracts`, `change-map` 네 문서다. 테스트는 문서 존재, CLI·subcommand·mutation 집합, 등록 경로와 일부 문구를 대조하지만 kind·store·surface·skill topology는 대조하지 않는다. | [test_architecture_docs.py](../../tests/test_architecture_docs.py#L13-L18), [계약 검사](../../tests/test_architecture_docs.py#L94-L127) | `docs/architecture/**`, `tests/test_architecture_docs.py` | 19종·저장 경로·검색 표면·4스킬 목록의 구조화 계약 추가 |
| 현재 진행 상태 | committed `ROADMAP.md`는 확정되어 진행 중인 작업이 없다고 적는다. dirty WIP와 untracked 설계안을 완료·활성 production으로 읽으면 이 기록과 충돌한다. | [ROADMAP.md](../../ROADMAP.md#L22-L42) | `ROADMAP.md` | WIP와 spec 승인 상태가 닫힌 뒤에만 상태 갱신 |

### 현재 19종 객체 topology

아래 표는 [schema](../../src/project_brain/schema.py#L23-L74),
[store](../../src/project_brain/store.py#L141-L162),
[참조 registry](../../src/project_brain/reference_fields.py#L14-L47),
[검색 extractor](../../src/project_brain/surface.py#L173-L204),
[19종 데이터 계약](../architecture/data-contracts.md#L145-L170)을 함께 대조한 결과다.

| kind | `truth_role` | 저장 경로 | 핵심 연결 | 현재 검색·질의 노출 |
|---|---|---|---|---|
| `EvidenceManifest` | `source` | `raw/manifests` | `EvidenceRef.evidence_manifest_id`의 원출처 | 일반 검색 제외, 일부 query의 provenance·restricted 판정 |
| `EvidenceRef` | `reference` | `objects/evidence_refs` | manifest 1개, 선택적으로 중첩 `CodeLocator` | 일반 검색 제외, 근거·raw·restricted·graph 보조 |
| `ReviewRecord` | `review` | `objects/reviews` | 단일 target 또는 mapping bundle targets | 일반 검색 제외, promote·audit·graph 증거 |
| `EventLedgerRecord` | `event` | `objects/ledger` | `related_objects`; `TemporalFact`의 원인 | `summary` 검색 표면, 변경 이유·이력 query |
| `TemporalFact` | `fact` | `objects/facts` | 원인 event, 선택적 이전 fact `supersedes` | subject·predicate·value·summary 표면, current/as-of query |
| `CodeLocator` | `reference` | `objects/code` | EvidenceRef 중첩 locator 및 여러 객체의 `code_locator_ids` | path·symbol 표면, 구현 위치와 stale/quote 검사 |
| `DomainContext` | `domain` | `objects/domain` | 소유 glossary 목록과 evidence | display/boundary 표면, scope 추론·projection source |
| `GlossaryTerm` | `domain` | `objects/domain` | context, evidence, 선택적 review·supersedes | term·definition·synonyms·aliases·avoid 표면, 정확 의미·정규화 |
| `ContextProjection` | `index` | `indexes/context_projections` | context와 source objects | `prompt_payload`만 `projection_reuse`; `context_md`는 검색 제외 |
| `CurrentView` | `synthesis` | `views/current` | source facts와 events | summary 표면, current-status query와 stale 비교 |
| `KnowledgePage` | `synthesis` | `views/knowledge` | source objects | 전용 creator·검색 표면 없음; storage·generic graph 중심 |
| `IndexRecord` | `index` | `indexes/records` | source object 1개 | 검색 표면 없음; 실제 index rebuild가 이 kind를 만들지 않음 |
| `SpecDocument` | `reference` | `objects/specs` | `SpecRevision`의 parent | 전용 creator·검색 표면 없음 |
| `SpecRevision` | `reference` | `objects/specs` | `SpecDocument`, 의도상 `SlideRef` 목록 | 전용 creator·검색 표면 없음; `slide_refs`는 공통 registry 밖 |
| `SlideRef` | `reference` | `objects/specs` | `SpecRevision` 1개 | 전용 creator·검색 표면 없음 |
| `SlackThread` | `source` | `objects/comms` | message refs와 evidence | 전용 creator·검색 표면 없음; `message_refs`는 공통 registry 밖 |
| `DecisionRecord` | `event` | `objects/decisions` | source objects, contexts, 선택적 mappings·glossary | summary·decision 표면, why-changed query |
| `DomainMapping` | `domain` | `objects/mappings` | context, glossary, decisions, 선택적 code·review·superseded mappings | 핵심 query·검색·graph rerank·projection·term promotion |
| `Insight` | `synthesis` | `objects/insights` | source objects, 선택적 code locators | reviewed 전용 advisories와 body·scope 표면; candidate 금지 |

이 topology에 `GlossaryClassificationRecord`는 없다. 새 kind를 넣으려면 schema만이 아니라 ID,
저장 경로, 참조, mutation, lint, snapshot, audit, 검색/그래프 제외 정책과 19종 template 집합을
함께 바꿔야 한다.

### 현재 설치 스킬 4종 topology

installer의 실제 흐름은
`templates/<key> → 렌더 → .agents/skills/<project>-brain-<suffix> → manifest SHA 추적`이다.
설치본은 엔진 템플릿과 실시간 연결되지 않은 일반 파일이다. 근거는
[installer.py](../../src/project_brain/installer.py#L1-L12),
[_SKILLS](../../src/project_brain/installer.py#L26-L35),
[installer tests](../../tests/test_installer.py#L202-L223)다.

| template key → 설치 이름 | HEAD의 주 책임 | HEAD의 실제 쓰기 경계 | 현재 dirty WIP가 바꾸려는 경계 | 필요한 검증 |
|---|---|---|---|---|
| `query` → `<project>-brain-query` | Brain 먼저 조회하고 근거·채널을 나눠 답하며 개발 착수 컨텍스트를 조립 | 본문이 read 쪽이라고 말하지만 사용자 확인 뒤 `promote`, reuse projection `--write`, `index rebuild`를 직접 안내 | 기본 조회를 완전한 read-only로 두고 현재 checkout 대조, 백로그 의도 조회, 명시 쓰기는 ingest/session-ingest로 넘김 | 설치본에 금지된 write 명령이 없는지와 query 결과·현재 코드 분리 확인 |
| `ingest` → `<project>-brain-ingest` | 완료된 기능·확정 도메인의 소급 적재; 객체 shape·판정·update·완료 게이트의 sibling 정본 | coverage→build→ingest, promote-auto, finalization 등 코퍼스 쓰기를 소유 | 현재 코드·ROADMAP 우선, 좁은 Git stage, fail-closed 검증 결과, no-op finalization 보강 | full engine + 설치 runtime + 임시 target 2회 install + 해당 변경 축의 소비 corpus 회귀 |
| `session-ingest` → `<project>-brain-session-ingest` | 진행 중 개발 적재와 과거 세션 추출; 객체 모양·갱신·최종화는 ingest에 위임 | candidate/직접 reviewed 적재, raw 보관, session mark-processed를 수행 | 사용자 진술과 코드 사실 분리, pending/backlog 비색인 대기 경계, finalization 성공 뒤에만 processed | session 계약, raw scanner 제외, 실패 시 unprocessed, 설치 reference 연결 검사 |
| `audit` → `<project>-brain-audit` | lint·고립·stale·quote 건강검진과 수정 후보 분류 | 기본 `audit`은 원격 fetch 가능성과 stale cache 쓰기가 있고, 문서는 mark-checked·수정 흐름까지 안내 | `--no-fetch --no-stale-cache-write` 진단을 기본으로 하고 수정은 명시 요청 뒤 ingest에 위임 | read-only 기본 명령의 파일/Git 불변과 checked·skipped·failures 보고 분리 |

HEAD 스킬 책임은 각 수정 파일의 현재 내용이 아니라
`git show c8525b0:src/project_brain/templates/{query,ingest,session-ingest,audit}/SKILL.md`로 확인했다.

## 2. dirty WIP

이 묶음은 코드·문서·테스트가 실제로 바뀌어 있지만 아직 커밋·최종 채택되지 않았다. 새 어휘,
공통 verification, 지식 초안 구현과 섞지 않는다.

| WIP 묶음 | 현재 작업 트리에서 구현된 변화 | 1차 근거 | 정본 목적지 | 닫기 위해 필요한 검증 |
|---|---|---|---|---|
| query 안전 경계 | query를 Brain 조회→현재 checkout 대조→재검색→실패 유형 분류로 바꾸고 자동 promote·projection write·rebuild를 제거했다. 백로그 의도에서만 `pending/insights.md`, `backlog/development.md`를 읽는다. | [dirty query](../../src/project_brain/templates/query/SKILL.md#L11-L45), [쓰기 경계](../../src/project_brain/templates/query/SKILL.md#L167-L172), [untracked contract test](../../tests/test_agent_skill_contract.py#L41-L67) | query template·contract test; 승인 뒤 template changelog | 설치본 렌더, read-only 파일 불변, 일반 질문에서 대기 파일 미노출 |
| audit 보고 우선 | 기본 진단을 `audit --no-fetch --no-stale-cache-write`로 바꾸고 자동 연결·제거 대신 결과를 먼저 보고한다. | [dirty audit](../../src/project_brain/templates/audit/SKILL.md#L10-L40), [수정 경계](../../src/project_brain/templates/audit/SKILL.md#L89-L99), [contract test](../../tests/test_agent_skill_contract.py#L69-L86) | audit template·contract test | 기본 실행 전후 Git·cache 불변, 최신 원격/캐시 요청의 별도 쓰기 경로 |
| ingest/session 안전 규칙 | 현재 코드·ROADMAP을 과거 plan보다 우선하고 broad stage/commit과 자동 stash를 금지했다. 코드 사실은 현재 checkout 대조 없이 사용자 진술만으로 reviewed로 올리지 않는다. | `git diff -- src/project_brain/templates/{ingest,session-ingest}/SKILL.md`, [session rules](../../src/project_brain/templates/session-ingest/SKILL.md#L25-L42) | 두 skill template과 관련 reference | 기존 사용자 변경 보존 fixture, source-intake와 finalization 회귀 |
| pending/backlog 분리 | 실제 원문만 `raw/sources`에 두고 미검증 합성 분석과 개발 제안을 두 비색인 파일로 분리했다. 현재 raw scanner도 `raw/sources/<context>/*.md`만 읽는다. | [session boundary](../../src/project_brain/templates/session-ingest/SKILL.md#L44-L60), [raw scanner](../../src/project_brain/raw_chunks.py#L132-L150), [raw test](../../tests/test_raw_chunks.py#L127-L145) | session/query skill, template changelog, 소비 데이터 README | 일반 search/index/snapshot 제외와 백로그 의도 회수; 실제 데이터 파일 상태는 별도 소비 레포에서 확인 |
| verify fail-closed | assembler가 `pass|fixed`와 `corrected_atoms`를 요구한다. 누락·`needs_user`를 extract atoms로 대체하던 폴백을 제거하고, `pass`면 extract와 exact 일치를 요구한다. | [assemble_notes.py](../../src/project_brain/templates/ingest/scripts/assemble_notes.py#L64-L102), [runtime tests](../../src/project_brain/templates/ingest/scripts/test_assemble_notes.py#L196-L265) | 설치 ingest runtime과 reference | 설치 runtime 전체 unittest, 과거 main-map 변칙의 명시적 fixture |
| no-op finalization | 모든 receipt가 `no_changes`면 실제 index rebuild만 생략하고 lint·eval·graph·audit·소비 checks·recall은 유지한다. | [finalize_ingest.py](../../src/project_brain/templates/ingest/scripts/finalize_ingest.py#L528-L565), [runtime test](../../src/project_brain/templates/ingest/scripts/test_finalize_ingest.py#L204-L244) | 설치 ingest runtime·완료 체크리스트 | mixed/no-op/changed receipt 전체 행렬과 설치 runtime unittest |
| 앵커·처리 완료 보강 | 신규/변경 코드 앵커에 full SHA·symbol·exact quote를 요구하고, session은 exact receipt·실패 0·`finalization.ok=true` 뒤에만 processed로 표시하도록 문서를 맞췄다. | `git diff -- src/project_brain/templates/{ingest,session-ingest}/references src/project_brain/templates/ingest/scripts/domain_spec.template.py`, [contract assertions](../../tests/test_agent_skill_contract.py#L160-L213) | 설치 reference와 template contract | 현재 code verifier 계약과 설치본 문구 일치, 실패 시 processed 불변 |

tracked 수정 20개는 위 일곱 묶음으로 모두 설명된다. `CONTEXT.md`, `docs/adr/`, fresh audit,
빈 spec은 구현 WIP가 아니라 다음 절의 설계 입력이다. `decks/project-brain-new/`와
`docs/superpowers/plans/2026-07-27-handoff-consumer.md`는 기존 사용자 파일이며 이 작업의 정리
대상으로 흡수하지 않는다.

현재 세션에서 root가 다음 표적 검사를 다시 실행해 **55 passed in 1.03s**를 확인했다.

```bash
.venv/bin/python -m pytest -q \
  tests/test_architecture_docs.py \
  tests/test_agent_skill_contract.py \
  tests/test_ingest_skill_contract.py \
  tests/test_raw_chunks.py
```

이 결과는 현재 architecture/skill/raw 표적 계약의 건강성만 뜻한다. full engine suite, 설치되는
runtime 전체, 실코퍼스, 새 어휘 기준, 공통 verification, 지식 초안 구현 증거가 아니다.

## 3. 사용자 합의·미통합·미구현 설계

아래 항목은 “미승인 제안”으로 한데 묶으면 안 된다. 사용자 답변이나 정정으로 방향이 정해졌지만,
untracked 공용어·ADR에만 일부 반영됐고 production 계약에는 아직 없다.

| 합의한 방향 | 정확한 범위 | 1차 근거 | 정본 목적지 | 구현 뒤 필요한 검증 |
|---|---|---|---|---|
| 어휘 규칙의 독립 소유 | 어휘 판정은 지식 초안 하위 기능이 아니라 ingest, session-ingest, 초안 정식화가 함께 쓰는 공통 적재 계약이다. | [사용자 정정과 수용](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L2578-L2628), [ADR 0001](../adr/0001-share-glossary-rules-across-ingest-paths.md) | 통합 spec의 독립 “어휘 적재 계약” 장; 후속 공용 reference | 세 적재 입구가 같은 qualification 함수를 호출하고 우회 경로가 없는지 확인 |
| 어휘 자격·이름 | 독립적으로 질문·설명할 가치가 있는 실제 프로젝트 개념만 어휘다. 함수·필드·enum·클래스는 기본 제외하고, 코드 밖에서도 실제 이름으로 쓴 근거가 있을 때만 대표어/alias가 될 수 있다. | [Q2~Q7 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L2636-L2735), [ADR 0002](../adr/0002-classify-glossary-terms-by-concept-not-token.md#L3-L7) | 통합 spec, 공용 glossary reference | positive/negative/adversarial fixture와 기존 어휘 중복·소유 context 검사 |
| synonym·alias·교정 표현 | synonym과 alias는 이름의 성격만 다르고 신뢰도·검색 권한은 같으며 같은 지식에 도달한다. 대표어는 답변 표시 기본값이지 검색 우선순위가 아니다. 겹치는 표면은 도메인·범위·근거로 해소하고 남은 모호성은 드러낸다. `GlossaryTerm.avoid`는 검색 진입어가 아닌 대표어 교정 전용이다. | [Q3 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L2646-L2685), [Q33 원결정](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4032-L4070), 2026-08-14 후속 grill 2번 사용자 승인 | 통합 spec, router/surface/search | exact·scope·BM25·mapping·graph 각 경로의 동등 도달, ambiguous surface, avoid-only correction 확인 |
| candidate/reviewed 어휘 기준 | candidate도 실제 어휘 문턱은 통과해야 하며 발견 문자열 임시 보관함이 아니다. reviewed는 사실성뿐 아니라 kind·크기·정의·범위·대표 이름·소유 domain까지 검증된 상태다. | [Q5 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L2671-L2691), [Q8 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L2768-L2786), [후속 확정](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L2870-L2906) | 통합 spec, schema/mutation의 종류별 검사 | 어휘가 아닌 정확한 코드 사실을 reviewed GlossaryTerm으로 쓰려 할 때 거부 |
| 사람 검수 예외 | 1차 근거·중복·소유·대표명·경계·적대 검증이 모두 닫히면 에이전트가 reviewed로 적재할 수 있다. 끝내 풀 수 없는 팀 사용·의미 충돌·병합/분리·대표명만 사용자에게 묻는다. | [Q8](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L2768-L2786) | 통합 spec의 검증 주체/예외 절 | 독립 실행 입력과 결과 결속, 대량 검증 한 실행의 후보별 결과 분리 |
| 어휘 판정 명부 | 공통 규칙만으로 충분한 코드 토큰은 개별 기록하지 않는다. 같은 문맥에서 반복 오분류될 제외·기존 어휘 연결만 정식 비색인 `GlossaryClassificationRecord`로 남긴다. 반대 근거가 생기면 영구 차단하지 않고 재판정한다. | [Q9~Q10](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L2908-L2958), [Q28 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L3865-L3917), [ADR 0003](../adr/0003-reuse-contextual-glossary-exclusions.md#L1-L17) | 통합 spec의 새 kind 계약; 구현 뒤 data contracts | 동일 문맥 유일성, 다른 문맥 독립성, 일반 search/graph 제외, audit/snapshot 포함 |
| 이중 어휘 관문 | 스킬이 추출 전에 명부와 자격을 확인하고, 모든 glossary 쓰기가 모이는 엔진 관문이 저장 직전에 다시 막는다. 수기 JSON 우회는 audit가 잡는다. | [Q11 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L2998-L3027) | 통합 spec, 공용 reference, MutationService, audit | ingest/direct-reviewed/update/migration/수기 우회 행렬 |
| 기존 어휘 정리 | 기존 reviewed 상태를 정답으로 보지 않고 전체 GlossaryTerm을 읽기 전용으로 재감사한다. 자동 수정하지 않고 유지·재분류·병합·분리·사용자 판단으로 나눈 뒤 승인된 migration으로만 반영한다. | [Q13 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L3073-L3113), [ADR 0002](../adr/0002-classify-glossary-terms-by-concept-not-token.md#L9-L11) | 통합 spec의 audit/migration 절, 이후 BB2 migration ticket | 반복 실행 결정론, exact plan, ref rewrite, snapshot, rollback, query/eval |
| alias 연결·오적재 제거 | `alias_to`면 classification만 쓰지 않고 실제 대상 `GlossaryTerm.aliases`와 변경 검수를 같은 mutation에서 갱신한다. 잘못된 GlossaryTerm은 rejected로 남기지 않고 알맞은 객체에 의미를 보존한 뒤 migration으로 제거하며 원문·EvidenceRef는 보존한다. | [Q30~Q31 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L3932-L3965), [ADR 0003](../adr/0003-reuse-contextual-glossary-exclusions.md#L7-L19) | 통합 spec의 원자 변경·migration 절 | alias 검색 도달, 참조 rewrite, 삭제 전후 근거 보존, rollback |
| 공통 후보 검증·승격 경계 | 모든 승격 가능한 candidate가 공통 검사와 kind별 검사를 자기 `candidate.verification`에 보존한다. 별도 `ObjectVerificationRecord`와 `GlossaryQualificationRecord`는 만들지 않고 승격 시 기존 `ReviewRecord`에 요약·결속을 남긴다. 수동 승격·즉시 승격·`promote-auto`는 모두 최신 verification을 요구하며 mapping 연결만으로 승격하지 않는다. 직접 reviewed 적재와 reviewed 의미·근거 변경도 동등한 검증을 우회하지 않는다. | [범용화 정정](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4092-L4228), [단순화 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4316-L4369), 2026-08-14 후속 grill 1번 사용자 승인, [ADR 0004](../adr/0004-keep-verification-on-candidates.md) | 통합 spec의 공통 상태 기계 | 내용·근거·규칙·실행 변경 시 readiness 무효화; 기존 후보 read 호환; 모든 쓰기 경로 우회 방지 |
| 질의 확인과 쓰기 승인 분리 | query는 답변이 의미 후보에 의존하고 사람 판단이 필요할 때만 확인을 요청한다. 기술 근거·코드 위치·파생 객체는 적재·전용 갱신 경로에서 검증한다. `맞아`는 답의 모호성을 푸는 근거일 뿐 쓰기 승인이 아니며, `바로 승격해줘`와 `승격 준비 목록에 넣어둬`만 각각 재검증 후 승격과 verification 보존을 요청한다. | [Q36 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4250-L4289), 2026-08-14 후속 grill 1번 사용자 승인, [ADR 0005](../adr/0005-separate-candidate-confirmation-from-promotion.md) | 통합 spec, query/ingest workflow | kind capability, 자연어 권한 분기, no-write 확인, readiness stale, 명시 승인 receipt |
| 지식 초안의 목적·입력 | 지식 초안은 agent-team이나 세션이 소유하지 않고 기능·도메인 주제가 소유하는 지속형 적재 전 작업공간이다. 문서/raw가 있으면 거기서, 없으면 사용자 대화와 현재 코드에서 시작하고 개발 중 계속 갱신한다. | [사용자 원요구](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L1791-L1833), [생성·갱신·인터뷰](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L1925-L2018), [범위 복원](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L2385-L2558) | 통합 spec의 지식 초안 장 | 입력별 생성 fixture, 개발 중 변경/폐기/충돌 이력, current-code 재확인 |
| 지식 초안의 최소 경계 | 기능·주제 단위로 여러 작업 구간에서 갱신하고, 초안 단계에서 `GlossaryTerm` 여부나 최종 kind를 확정하지 않는다. 정식 Brain 객체나 일반 query의 확정 근거가 아닌 적재 전 작업공간이라는 방향까지 합의됐다. 실제 표현·확인 사실·가설·충돌·질문·근거·행선지 같은 정확한 섹션과 인터뷰 절차는 대화에서 제안됐지만 필드 계약으로 따로 승인되지는 않았다. | [사용자 문제 제기와 초안 방향](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L1925-L2018), [Q1 범위 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L2531-L2558), [최종 누락 목록](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L5198-L5225) | 통합 spec과 후속 workflow reference | 잘못된 자동 kind 확정과 raw/index/query 혼입을 막는 테스트; 정확한 섹션·인터뷰 규칙은 spec 전체 승인으로 확정 |
| 지식 초안 발견·종료 | v1 세션 훅 없이 관련 작업 시작이나 “이어서” 요청에서 활성 초안을 찾는다. 항목은 정식 객체·backlog·classification·discard 또는 출처 backlink와 routing receipt를 가진 `pending/insights.md`로 보낼 수 있고, 모두 처리된 뒤 파일을 삭제해 Git 이력만 남긴다. `brain/drafts/<topic-id>.md`는 Q37에 포함된 제안 위치이므로 정확한 topic ID·파일 형식과 함께 spec에서 확정해야 한다. | [Q37 제안과 훅 결정](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4421-L4483), [Q38 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4485-L4502), 2026-08-14 후속 grill 3번 사용자 승인, [ADR 0006](../adr/0006-use-temporary-topic-knowledge-drafts.md) | 통합 spec, 구현 뒤 workflow map·스킬 | 관련 0/1/복수 초안 발견, pending 이동·중복 회수, 미처리 삭제 거부, 완료 삭제, archive/hook 부재 |
| spec·ticket 게시 위치 | Matt `to-spec`과 후속 `to-tickets`의 tracker는 `mooh1222/project-brain` GitHub Issues를 사용한다. 실제 게시 전에 1회용 repo 설정을 기록하고, 승인된 spec만 후속 ticket 입력으로 사용한다. | 2026-08-14 후속 grill 4번 사용자 승인, 현재 `origin`·GitHub repository read-only preflight | `docs/agents/issue-tracker.md`, GitHub Issues | tracker 설정, 대상 저장소, 게시된 issue URL·label 확인 |
| 지식 초안 검증 범위 | 이번 구현은 파일 형식·생성/갱신/삭제·비색인/비정본·ingest 연결과 기본 자동 테스트까지만 한다. 수동 임시 소비 프로젝트·다중 세션 사용성 검증과 BB2 설치는 첫 실사용 파일럿으로 미루며, 초안은 어휘·후보·BB2 migration의 blocker가 아니다. installer 2회 무변경 자동 회귀는 유지한다. | [사용자 범위 조정](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L5174-L5194) | 통합 spec의 범위/비범위·후속 파일럿 조건 | 자동 계약만 이번 티켓에서; 실사용 평가는 별도 승인된 기능에서 |

## 4. 폐기되거나 뒤에서 대체된 안

| 폐기안 | 최종 판정 | 1차 근거 | 정본 목적지 | 재유입 방지 검증 |
|---|---|---|---|---|
| agent-team 전용 전달물 | 지식 초안은 agent-team을 거쳐야 생기는 bridge가 아니라 어떤 개발 흐름에서도 쓰는 주제 소유 작업공간이다. | [사용자 정정](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L1791-L1797) | 통합 spec의 비종속성 조항 | agent-team 없는 생성·재개 fixture |
| 모호한 candidate 예외에만 초안 사용 | 지나치게 좁은 안으로 폐기했다. candidate 가능 여부는 생성 조건이 아니라 정식화 준비 판단이다. | [축소안](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L2380-L2386), [복원](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L2388-L2558) | 통합 spec의 목적·생성 조건 | spec 금지 문구와 진행 중 일반 주제 예시 |
| 어휘 규칙을 초안 아래에 둠 | 폐기. 공통 어휘 적재 계약이 독립 소유하고 초안은 입력만 제공한다. | [사용자 정정](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L2578-L2584) | 통합 spec의 장 구조 | ingest/session/direct formalize가 같은 규칙 사용 |
| 별도 governance 파일·manifest·관리 초기화 | `GlossaryClassificationRecord`를 정식 비색인 객체로 채택하면서 별도 명부 파일, 필수 manifest, 어휘 전용 초기화는 폐기됐다. “현재 판정 1개와 Git 이력”의 의미만 남는다. | [중간 파일안](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L3117-L3188), [대체 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L3833-L3917) | 통합 spec의 새 kind 저장 계약 | 금지된 `brain/governance/glossary/manifest.json` 경로가 spec·코드에 없는지 확인 |
| `GlossaryQualificationRecord` | 별도 kind를 폐기하고 어휘 종류별 검사를 `candidate.verification`에 넣는다. | [중간안](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L3659-L3692), [단순화 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4316-L4369) | 통합 spec의 명시적 non-goal | schema/template kind 집합에 이름이 들어가지 않는지 검사 |
| `ObjectVerificationRecord` | 별도 kind를 폐기하고 공통 검사를 같은 candidate envelope에 넣는다. | [중간안](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4230-L4238), [단순화 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4316-L4369) | 통합 spec의 명시적 non-goal | schema/template kind 집합과 migration에 이름이 없는지 검사 |
| 별도 승격 준비 명부 객체 | 폐기. 현재 candidate verification에서 계산해 보여주며 독립 저장 목록을 두지 않는다. | [계산 목록 제안](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4072-L4090), [최종 구조](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4348-L4357) | 통합 spec의 readiness 계산 절 | 후보 변경 뒤 목록이 자동으로 사라지는지 확인 |
| 단순 “맞다” 즉시 promote | 폐기. 확인과 쓰기 승인을 분리한다. 이 안은 HEAD query에 있고 dirty WIP의 ingest reference에도 남은 반면 dirty query는 반대로 바뀌어, 현재 WIP 내부에서도 권한 의미가 충돌한다. | [Q36 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4250-L4289), [ADR 0005](../adr/0005-separate-candidate-confirmation-from-promotion.md), [dirty query 경계](../../src/project_brain/templates/query/SKILL.md#L167-L172), [dirty ingest 모순](../../src/project_brain/templates/ingest/references/ingest-tools.md#L146-L156) | WIP query/ingest 정리와 통합 spec | 자연어 확인 뒤 corpus·index 불변 |
| v1 세션 시작 hook | 폐기. 관련 작업 시작/이어가기에서 발견하고, 실제 누락이 반복될 때만 가벼운 신호를 다시 검토한다. | [hook 정정과 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4434-L4483) | 통합 spec의 non-goal | 설치 산출물에 session hook이 없는지 확인 |
| 완료 초안 archive | 폐기. 모든 항목이 처리되면 파일을 삭제하고 Git 이력만 남긴다. | [Q38 승인](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4485-L4502) | 통합 spec의 수명주기 | 완료 archive 디렉터리가 생성되지 않는지 확인 |
| live BB2부터 감사·migration | 폐기. 엔진·스킬 관문과 복제 rehearsal이 먼저고 live는 별도 승인 뒤다. | [최종 순서](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4980-L5051) | 통합 spec의 전환/비범위 | live 경로는 두 승인과 exact plan 없이는 실행 불가 |

## 5. 미결정

아래는 구현자가 임의로 채우면 제품 동작이나 호환 범위가 달라지는 항목이다. 전부를 사용자에게
긴 인터뷰로 돌릴 필요는 없다. `결정 주체`가 “spec 제안”인 것은 1차 자료를 바탕으로 한 안을
spec에 제시하고 사용자가 전체 spec에서 승인하면 된다.

| 미결정 | 아직 닫히지 않은 질문 | 1차 근거 | 결정 주체 | 정본 목적지 | 필요한 검증 |
|---|---|---|---|---|---|
| 19종 kind capability 표 | 사용자는 query가 답변에 필요한 의미 후보만 확인하고 기술·근거·파생 객체는 전용 경로에서 검증한다는 정책을 승인했다. 이를 현재 19종 각각의 candidate 허용·질의 확인·직접 승격·전용 갱신 능력으로 옮기는 정확한 표는 아직 없다. | [Q35 원질문](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4240-L4248), 2026-08-14 후속 grill 1번 사용자 승인 | spec 제안 후 사용자 승인 | 통합 spec의 kind capability 표 | 19종 각각의 허용·금지 fixture |
| `GlossaryClassificationRecord` 상세 계약 | ID, required/optional 필드, truth role, 저장 디렉터리, context/surface/target uniqueness, 상태 전이, reference kind, 전용 조회, 일반 graph 제외 방식이 없다. | [fresh audit 미결정 목록](2026-08-14-project-brain-fresh-direction-audit.md#L112-L125), [ADR 0003](../adr/0003-reuse-contextual-glossary-exclusions.md) | spec 제안 후 사용자 승인 | 통합 spec의 kind 표·ID·storage·surface·lifecycle | schema/ID/store/ref/lint/audit/snapshot/mutation/template 종단 회귀 |
| `candidate.verification` 상세 계약 | content/evidence/rule/execution 결속 형식, 규칙 버전, 실행 신원, 종류별 검사표, readiness 계산과 무효화가 없다. | [ADR 0004](../adr/0004-keep-verification-on-candidates.md#L3-L11), [fresh audit](2026-08-14-project-brain-fresh-direction-audit.md#L116-L123) | spec 제안 후 사용자 승인 | 통합 spec의 공통 verification envelope | 각 결속 축 변경 시 stale, 기존 후보 read 호환, 승격 거부 |
| 직접 reviewed·reviewed 수정 결속 | 동등한 검증을 우회하지 않는 정책은 승인됐다. 후보를 만들지 않는 경로에서 exact receipt·ReviewRecord·transaction에 무엇을 어떻게 결속할지와 legacy read 호환은 spec 실행 설계로 남는다. | [ADR 0004](../adr/0004-keep-verification-on-candidates.md#L9-L11), 2026-08-14 후속 grill 1번 사용자 승인 | spec 제안 후 사용자 승인 | 통합 spec의 쓰기 경로별 호환 표 | ingest/promote/update/migration 각각 새 write와 legacy read fixture |
| `promote-auto` 전환 세부 | 명령 유지, verification-ready only, mapping-vouch 불충분 정책은 승인됐다. 기존 verification 없는 후보와 현재 mapping-vouched fixture를 어떤 기간·보고 방식으로 전환할지는 남았다. | [현재 동작](../../src/project_brain/promote.py#L16-L69), 2026-08-14 후속 grill 1번 사용자 승인 | spec 제안 후 사용자 승인 | 통합 spec의 하위 호환·CLI 절 | 기존 mapping-vouched fixture, verification 없는 기존 candidate의 보수적 처리 |
| 지식 초안 파일·인터뷰 계약 | 문서 섹션, topic ID, source locator, 항목 ID/상태, 갱신 충돌, 여러 활성 초안 선택, 관련성 판정, backlog/classification/discard receipt가 없다. 실제 표현·확인 사실·가설·충돌·열린 질문·근거·행선지 구분과 “문서·코드로 풀 수 없는 의도만 질문”도 유력한 설계 입력이지만 정확한 강제 형식으로는 아직 확정되지 않았다. | [초안 내용·인터뷰 제안](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L1966-L2018), [최종 누락 목록](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L5198-L5227), [review 미결정](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.review.md#L205-L234) | spec 제안 후 사용자 승인 | 통합 spec의 draft schema·workflow | 0/1/복수 발견, 동시 수정, 부분 정식화, 완료 삭제, 복구·과잉 인터뷰 방지 테스트 |
| 지식 Markdown 금지와의 기계 경계 | 초안이 임시·비정본·비검색·완료 시 삭제라는 합의는 있지만, existing “AI-maintained knowledge Markdown 금지”를 어떤 loader/index/snapshot 검사로 강제할지 없다. | [design canonical](../design-canonical.md#L67-L70), [ADR 0006](../adr/0006-use-temporary-topic-knowledge-drafts.md) | spec 제안 후 사용자 승인 | 통합 spec의 불변 규칙, 구현 뒤 design canonical 설명 | raw scanner, object loader, search index, snapshot 입력에서 draft 제외 |
| 기존 어휘 migration 세부 | 읽기 전용 분류 결과의 exact schema, reference rewrite, classification+alias+remove 원자성, legacy query 기간, rollback과 두 승인 artifact가 없다. | [Q13](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L3073-L3113), [fresh audit](2026-08-14-project-brain-fresh-direction-audit.md#L121-L125) | spec 제안 후 사용자 승인; live apply는 별도 승인 | 통합 spec의 audit/migration/cutover | 복제 BB2 결정론 audit→plan→apply→rebuild/eval→rollback |
| living architecture 완성 형태 | 현재 docs를 보강한다는 목표는 분명하지만 `workflow-map.md` 추가 여부, 19종 전체 관계 표현, Task 18 특수 흐름의 위치, 현재/합의·미구현/과거 상태 표기 방식과 테스트 block 형식은 확정 문서가 없다. | [아키텍처 요구와 분석](../../.snapshots/2026-08-14/019fee5e-4dff-7820-ab54-02c6981f68b5.txt#L4506-L4654), [현재 테스트 범위](../../tests/test_architecture_docs.py#L94-L181) | spec 제안 후 사용자 승인 | architecture entry/data/runtime/change, 필요 시 workflow map | 새 세션 독립 설명 + kind/store/surface/skill 자동 대조 |
| dirty WIP의 종료 단위 | query/audit/ingest/runtime/pending-backlog 변경을 한 변경으로 닫을지 더 나눌지, untracked contract test와 changelog를 어떤 commit 범위로 묶을지 정하지 않았다. | `git status`, `git diff --numstat`, [fresh audit](2026-08-14-project-brain-fresh-direction-audit.md#L33-L53) | 현재 WIP 검수에서 결정 | 기존 WIP 전용 review/commit; 새 spec과 분리 | full engine, 설치 runtime, installer 2회, 범위별 review |
| 문서 상태 원장 완성 | 후속 grill 뒤 ADR 0001~0006에는 accepted·미구현·통합 spec 대기 상태를 넣었지만, 빈 spec·ROADMAP·architecture entry가 이 상태와 구현 근거·대체 관계를 아직 연결하지 않는다. | [CONTEXT.md](../../CONTEXT.md), [ADR 0001~0006](../adr/), [빈 spec](../specs/bb2-project-brain.md) | spec 제안 후 사용자 승인 | 통합 spec, ADR index, ROADMAP, architecture entry | 현재 구현·합의 미구현·어시스턴트 제안·폐기·과거 문서의 discovery 검사 |

## `to-spec`에 넘길 최소 입력

다음 단계는 이 보고서의 미결정을 숨긴 채 spec을 채우는 일이 아니다.

1. 후속 grill에서 승인된 질의 확인·승격, 이름 표면·교정, draft→pending, GitHub tracker 결정을 반영한다.
2. 남은 실행 계약은 현재 코드와 위 합의를 바탕으로 spec 작성자가 한 안을 제시한다.
3. 통합 spec은 적어도 다음 장을 독립적으로 가져야 한다.
   - 현행 19종과 하위 호환
   - 공통 후보 verification과 승격 상태 기계
   - 공통 어휘 적재 기준
   - `GlossaryClassificationRecord`
   - query 확인과 쓰기 승인
   - 지식 초안 생성·재개·정식화·삭제
   - read-only glossary audit와 migration/rollback
   - 4스킬·installer·living architecture 동기화
4. 사용자 승인을 받은 spec만 `to-tickets` 입력으로 쓴다. dirty WIP 안정화, 엔진 구현,
   스킬/installer, 복제 BB2, live 승인 단계는 같은 티켓으로 뭉치지 않는다.

최초 research 작성에서는 이 보고서 하나만 새로 만들었다. 후속 grill 승인 뒤에는 CONTEXT와
ADR 0001~0006, 이 보고서의 결정 상태만 갱신했다. 엔진·스킬·아키텍처·BB2·설치·GitHub 외부
상태는 바꾸지 않았다.
