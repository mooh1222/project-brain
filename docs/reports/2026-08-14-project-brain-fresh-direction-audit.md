# Project Brain 새 방향 감사와 최종 진행 순서

- 감사일: 2026-08-14 KST
- 엔진 기준: `main` / `c8525b09b301a1bdd6a82ace7776214f4b668362`
- BB2 기준: `docs/bb2-brain-object-model` / `e6601623a6ab742b0e7cb894ece0b8d825e9135e`
- 범위: 엔진 checkout, 설치 템플릿과 테스트, 글로벌 editable 설치, BB2의 설치 스킬·config·corpus·index를 읽기 전용으로 대조
- 비범위: 설치, ingest/promote/migration, index rebuild, stage/commit, BB2 파일 변경

## 결론

새 방향의 순서는 **현재 상태 격리 → 용어와 ADR 승인 → 실행 가능한 통합 spec → 공통 검증·승격 관문 → 어휘 판정 객체와 감사·migration 기반 → 지식 초안 기반 → 설치 스킬 → 복제 BB2 검증 → 승인된 live audit/migration**이 맞다.

지금 바로 live BB2 corpus audit나 migration부터 시작하면 안 된다. 새 `GlossaryClassificationRecord`, 후보 검증 결속, `brain/drafts/`는 아직 production 계약에 없고, 이들을 설명하는 `CONTEXT.md`와 ADR 6개도 모두 untracked 제안이다. 이름만 있는 `docs/specs/bb2-project-brain.md`는 실행 계약이 아니다. 현재 코드는 19종 객체와 기존 `candidate`/`promote` 계약을 그대로 실행한다. 현재 기준은 문서 초안이 아니라 코드·테스트·CLI라는 프로젝트 원칙과도 일치한다([architecture README](../architecture/README.md#L44-L63), [data contracts](../architecture/data-contracts.md#L1-L20)).

또한 엔진 Python과 설치 스킬의 전파 경로는 다르다.

- 글로벌 `project-brain`은 이 checkout의 `src/`를 가리키는 editable 설치라서 **여기서 Python 엔진 코드를 고치면 다음 CLI 프로세스부터 BB2에도 즉시 영향을 준다**([README](../../README.md#L28-L33), [design canonical](../design-canonical.md#L138-L150)).
- `src/project_brain/templates/**`는 install 시 일반 파일로 렌더·복사된다. **템플릿만 고쳐서는 기존 BB2 설치 스킬이 바뀌지 않는다**([README](../../README.md#L40-L69), [installer](../../src/project_brain/installer.py#L228-L248)). 재설치 때도 사용자가 수정한 파일은 manifest 해시가 다르면 `skipped`다([installer](../../src/project_brain/installer.py#L437-L461)).

따라서 새 엔진 작업은 글로벌 editable 설치가 가리키지 않는 별도 worktree와 전용 venv에서 해야 한다. 그동안 live BB2는 현재 설치된 query skill로 조회만 할 수 있다. 다만 엄격한 zero-write 검증은 live가 아니라 복제한 `brain/`과 config에서 해야 한다. 검색 코드가 SQLite를 read-only URI가 아닌 기본 연결로 열고, 연결 helper는 부모 디렉터리까지 만들 수 있기 때문이다([search index](../../src/project_brain/search_index.py#L75-L93), [BM25 query](../../src/project_brain/search_index.py#L517-L556)).

## 서로 섞으면 안 되는 네 상태

| 상태 | 2026-08-14 관찰 | 판정 |
|---|---|---|
| 커밋된 엔진 | HEAD `c8525b09…`; 19 kind, 기존 glossary candidate metadata, mapping-vouched `promote-auto`, generic promote + ReviewRecord | 현재 실행 계약 |
| 엔진 dirty 작업 | query를 읽기 전용으로 바꾸고 pending/backlog 비색인 경로를 추가한 템플릿·runtime·테스트 변경 | 구현 중인 별도 변경. 새 glossary/verification/draft 설계 구현은 아님 |
| untracked 설계 | `CONTEXT.md`, ADR 0001~0006, 2줄짜리 `docs/specs/bb2-project-brain.md` | 아직 승인·통합되지 않은 제안 |
| live BB2 | 설치 스킬 59개가 현재 dirty 템플릿 렌더와 byte/manifest 모두 일치하지만, BB2 worktree 자체가 dirty | 현재 파일 상태일 뿐 배포 완료나 migration 완료 증거가 아님 |

엔진 `ROADMAP`은 현재 확정되어 진행 중인 일이 없다고 적고 있다([ROADMAP](../../ROADMAP.md#L39-L42)). 이번 dirty/untracked 묶음을 이미 승인된 현행 설계로 승격해서 읽으면 그 기록과도 충돌한다.

### 엔진 worktree

감사 시작 시 `main...origin/main [ahead 161]`이었다. tracked 수정은 설치 템플릿·설치 runtime과 관련 테스트 20개 경로에 걸쳐 있었고, 다음이 untracked였다.

- [`CONTEXT.md`](../../CONTEXT.md)
- [`docs/adr/`](../adr/)
- [`docs/specs/bb2-project-brain.md`](../specs/bb2-project-brain.md)
- `decks/project-brain-new/`
- `docs/superpowers/plans/2026-07-27-handoff-consumer.md`
- [`tests/test_agent_skill_contract.py`](../../tests/test_agent_skill_contract.py)

dirty query template는 조회 중 자동 `promote`, projection write, index rebuild를 하지 않고 명시적인 쓰기 요청을 ingest sibling으로 넘기도록 바뀌었다. 새 untracked contract test도 그 경계를 직접 고정한다([agent skill contract](../../tests/test_agent_skill_contract.py#L41-L67)). pending/backlog은 `raw/sources` 밖 비색인 파일로 다루는데, production raw scanner도 실제로 `brain/raw/sources/<context>/*.md`만 읽는다([raw chunks](../../src/project_brain/raw_chunks.py#L132-L150), [agent skill contract](../../tests/test_agent_skill_contract.py#L110-L157)).

이 변경은 안전한 query 기본값과 비색인 대기 파일 계약을 다룬다. 다음 새 설계를 구현하지는 않는다.

- 새 어휘 자격 판정과 모든 ingest 경로의 공통 관문
- `GlossaryClassificationRecord`
- 후보 내용·근거·규칙 버전에 결속된 generic verification
- verification에서 계산되는 promotion readiness
- `brain/drafts/<topic-id>.md`
- glossary 전수 audit와 migration

### untracked 방향 문서

`CONTEXT.md`는 대표 어휘·동의어·별칭, 승격 준비 후보, 어휘 판정 명부, 후보 검증, 지식 초안을 새 공용 언어로 정의한다([CONTEXT](../../CONTEXT.md#L8-L50)). ADR은 다음 목표를 제안한다.

- 모든 ingest 경로가 같은 어휘 규칙을 공유하고, 초안은 어휘를 확정하지 않는다([ADR 0001](../adr/0001-share-glossary-rules-across-ingest-paths.md)).
- token이 아니라 독립 개념과 실제 이름 사용 근거로 glossary를 분류하고, 기존 corpus는 read-only audit 뒤 별도 migration한다([ADR 0002](../adr/0002-classify-glossary-terms-by-concept-not-token.md#L3-L11)).
- 문맥별 제외·기존 어휘 연결을 비색인 `GlossaryClassificationRecord`로 재사용하고, 모든 glossary write gate와 audit가 이를 대조한다([ADR 0003](../adr/0003-reuse-contextual-glossary-exclusions.md#L3-L19)).
- 후보 안에 내용·근거·규칙·실행에 결속된 검증 결과를 두고, 승격 때 ReviewRecord로 요약·결속을 옮긴다([ADR 0004](../adr/0004-keep-verification-on-candidates.md#L3-L11)).
- 사용자의 단순한 “맞다”와 실제 쓰기 승인을 분리한다([ADR 0005](../adr/0005-separate-candidate-confirmation-from-promotion.md)).
- `brain/drafts/<topic-id>.md`는 활성 작업 동안만 쓰는 비정본·비원문·비검색 임시 작업물이며, v1에는 hook이나 완료 archive를 두지 않는다([ADR 0006](../adr/0006-use-temporary-topic-knowledge-drafts.md#L3-L7)).

방향은 서로 연결돼 있지만, 아직 하나의 실행 가능한 spec으로 닫히지 않았다. 특히 지식 초안은 “AI가 유지하는 지식 Markdown 층을 만들지 않는다”는 현 설계 경계와 긴장이 있다([design canonical](../design-canonical.md#L67-L70)). **일시적·비정본·비검색·완료 시 삭제**라는 제한을 spec과 테스트로 강제해야만 양립한다.

### production 코드의 실제 빈틈

1. `schema.py`의 `VALID_KINDS`는 여전히 19종이며 `GlossaryClassificationRecord`가 없다([schema](../../src/project_brain/schema.py#L18-L91)). `BrainStore._KIND_DIR`에도 저장 경로가 없다([store](../../src/project_brain/store.py#L141-L170)).
2. candidate 공통 enum은 있지만 실제 candidate metadata 강제는 `GlossaryTerm`에 집중돼 있다. 현재 glossary 검사는 상태·source와 짧거나 지나치게 일반적인 synonym/alias 정도이며, 제안된 독립 개념·실사용 이름·중복·소유 도메인 verification 결속은 없다([schema](../../src/project_brain/schema.py#L285-L315)). candidate `Insight`는 회상 통로가 없어 아예 거부된다([schema](../../src/project_brain/schema.py#L354-L373)).
3. generic promotion gate는 ReviewRecord 대상 집합, precondition, corpus fingerprint, 현재 candidate→reviewed 전이, 기존 review 충돌을 검사한다. 제안된 verification freshness/readiness를 검사하지 않는다([mutation](../../src/project_brain/mutation.py#L1952-L2021)). `promote()`도 candidate를 제거하고 reviewed와 ReviewRecord를 만드는 현재 계약이다([promote](../../src/project_brain/promote.py#L72-L145)).
4. `promote-auto`는 reviewed DomainMapping이 보증하는 비-conflict GlossaryTerm과 non-legacy evidence를 기준으로 한다. 제안된 어휘 qualification 결과나 generic verification binding을 소비하지 않는다([CLI](../../src/project_brain/cli.py#L1147-L1239), [promotion selection](../../src/project_brain/promote.py#L16-L69)).
5. 현 architecture 문서도 저장 호환 schema와 신규 write gate를 함께 보라고 명시하고, 전용 creator/search가 없는 kind 등 현재 빈틈을 별도로 기록한다([data contracts](../architecture/data-contracts.md#L22-L41), [engine gaps](../architecture/data-contracts.md#L271-L287)). 새 kind 하나만 schema에 추가하는 식으로 끝낼 수 없다.

## live BB2 읽기 전용 관찰

BB2의 `.project-brain.json`은 project `bb2`, `brain_root` `brain`, repo `bb2_client`, default branch `develop`을 지정한다. 설치된 query skill은 일반 파일이며 `.claude/skills/bb2-brain-query`만 그 파일을 가리키는 프로젝트 내부 symlink다. 엔진 template 디렉터리와 직접 연결된 symlink는 아니다.

설치 query skill은 기본 조회를 읽기 전용으로 선언하고 `search`, `query`, `show`만 안내하며, 설치·색인 정비와 candidate/projection 쓰기는 명시적인 요청일 때 sibling ingest로 넘긴다([BB2 installed query](../../../../../Desktop/bb2_client/.agents/skills/bb2-brain-query/SKILL.md#L11-L14), [query commands](../../../../../Desktop/bb2_client/.agents/skills/bb2-brain-query/SKILL.md#L47-L60), [write boundary](../../../../../Desktop/bb2_client/.agents/skills/bb2-brain-query/SKILL.md#L167-L183)).

직접 파일·JSON·SQLite를 읽어 얻은 현재 snapshot은 다음과 같다. 이 수치는 migration 결과가 아니라 **migration 전 대상 규모**다.

| 항목 | 현재 값 |
|---|---:|
| 인식 가능한 고유 객체 | 10,941 |
| 상태 | candidate 580 / reviewed 10,358 / superseded 3 |
| GlossaryTerm | 1,181 = candidate 150 + reviewed 1,031 |
| GlossaryClassificationRecord | 0, kind 자체 없음 |
| `brain/drafts/` | 없음 |
| `brain/pending/insights.md`, `brain/backlog/development.md` | 있음, Git index에서 added |
| SQLite `documents` 행 | 7,881 |
| index glossary 행 | 1,181 |
| 저장/current corpus fingerprint | 모두 `eb9fb8e…`, 현재 fresh |

BB2 worktree는 branch가 origin보다 243 commit 앞서고, 설치된 brain skill·manifest 외에도 agents-doctor/setup-log, `brain/README.md`, real-corpus check, pending/backlog 이동이 dirty다. 따라서 현재 59개 installer-managed 파일이 현재 엔진 dirty template의 렌더·manifest와 전부 일치한다는 해시 대조 결과는 **현재 bytes가 같다**는 뜻만 가진다. 어느 변경이 승인·commit·배포됐다는 뜻은 아니다.

글로벌 uv tool의 `_editable_impl_project_brain.pth`는 `/Users/al03040455/Downloads/codes/project-brain/src`를 가리키고, `direct_url.json`은 `editable:true`다. 실행기 역시 `project_brain.cli`를 import한다. 그러므로 이 main checkout의 Python core 변경과 BB2 query-only 운영은 동시에 안전하게 진행할 수 없다. 의존성이나 `pyproject.toml` 변화만 별도 재설치 대상이고, 순수 Python 변화는 재설치 없이 곧바로 노출된다.

## 최종 의존 순서

### 0. 현재 두 dirty root를 먼저 격리한다

엔진 main과 BB2의 기존 변경은 사용자 작업으로 보존한다. 새 작업을 섞어 commit·install·force하지 않는다. 새 엔진 구현은 별도 engine worktree + 전용 venv + 명시적 `PYTHONPATH`에서 시작하고, installer 검증 대상은 임시 디렉터리만 쓴다. 현재 dirty template/pending/backlog 변경의 소유자가 별도 review로 닫을 때까지 새 방향과 한 커밋으로 묶지 않는다.

### 1. 현재형 architecture map과 이 감사 결과를 기준선으로 삼는다

`docs/architecture/**`는 미래 설계를 미리 써 넣는 곳이 아니라 현재 코드로 가는 지도다([architecture README](../architecture/README.md#L1-L6)). 새 목표는 먼저 research/ADR/spec에서 다루고, architecture map은 production 구현과 테스트가 생기는 변경에서 함께 갱신한다.

이번 대조에서 현재 map의 엔진/데이터 경계, query/search 차이, corpus 쓰기와 cache 쓰기 구분은 production 코드와 맞았다. 구현 전에 발견되는 map drift가 있으면 **현재 동작만 현재형으로** 먼저 바로잡고, 미래 동작은 넣지 않는다. 이 보고서의 gap inventory와 live 규모 측정은 이어지는 통합 spec의 research 입력으로 쓴다.

### 2. 공용어·ADR을 승인하고 하나의 통합 spec을 쓴다

비어 있는 `bb2-project-brain.md`를 채우기 전에 다음을 명시적으로 닫아야 한다.

- glossary 자격, 실제 이름 사용 근거, canonical/synonym/alias/avoid와 모호성 우선순위
- `GlossaryClassificationRecord`의 ID, 필드, 참조, 저장 경로, lifecycle, 검색·그래프·snapshot 노출 경계
- candidate verification envelope, content/evidence/rule/execution fingerprint, invalidation과 readiness 계산
- 직접 reviewed ingest와 기존 candidate의 호환 정책
- 기존 `promote-auto`의 유지·전환·폐기 조건과 단순 확인/명시적 쓰기 승인 구분
- knowledge draft 탐색, 동시 활성 초안, 항목 라우팅, 삭제 조건, snapshot·query·raw 제외
- read-only audit 분류, exact migration plan/apply, reference rewrite, rollback, legacy query 호환
- 새 필드와 새 kind가 없어도 기존 19-kind corpus를 그대로 읽고 조회할 수 있는 backward-compatibility 기간

이 spec은 기존 universal ingest와 mapping-vouched promotion 중 무엇을 대체하는지 조항 단위로 적어야 한다. 설계 정본과 ROADMAP은 승인된 목표와 현재 구현 상태를 혼동하지 않게 갱신한다.

### 3. 후보 검증과 승격 관문을 먼저 구현한다

TDD로 공통 verification binding/readiness를 만든 뒤, 모든 승격 가능한 kind에 적용한다. content·evidence·rule version이 바뀌면 readiness가 낡도록 하고, promotion gate가 이를 거부하게 한다. 승격 시 ReviewRecord에는 검증 요약과 결속을 남긴다. 직접 reviewed ingest와 reviewed 객체의 의미 변경도 같은 검사를 우회하지 않아야 한다.

이 단계가 glossary 규칙보다 먼저인 이유는 `GlossaryTerm`도 결국 공통 candidate→reviewed 상태 기계 위에 올라가야 하기 때문이다. glossary만 별도 승격 길을 만들면 새 공통 계약이 다시 갈라진다.

전환기에는 verification metadata가 없는 기존 candidate를 “검증 통과”로 추정하지 않되, corpus load와 query는 깨뜨리지 않는다. 기존 reviewed 객체도 audit 결과만으로 즉시 읽기 차단하지 않는다. **새 write/promotion에는 새 관문을 적용하고, 옛 corpus read는 유지하는 방식**으로 전환해야 BB2 query-only 운영과 새 엔진 개발을 병행할 수 있다.

### 4. 공통 glossary 규칙과 판정 명부, audit/migration 기반을 구현한다

공통 qualification 함수를 ingest/session/direct-write가 함께 사용하게 한다. 그 뒤 `GlossaryClassificationRecord`를 schema·ID grammar·store·reference registry·lint·snapshot·mutation에 끝까지 연결한다. 일반 search와 기본 graph에서는 제외하되, 전용 조회와 audit에는 보여야 한다.

그 다음에야 기존 corpus를 **바꾸지 않는** audit 분류기와 deterministic migration planner를 만든다. audit 결과는 유지, 적절한 객체로 재분류, 기존 어휘의 alias/synonym으로 병합, 문맥별 분리, 사용자 판단 필요로 나누고, apply는 별도 명령·별도 승인으로 둔다. classification 전용 조회는 추가하되 일반 query/search가 옛 GlossaryTerm을 계속 읽는 backward-compatible 경로를 먼저 보장한다.

### 5. glossary classification/query가 안정된 뒤 지식 초안 기반을 구현한다

지식 초안은 glossary qualification이나 promotion의 선행 조건이 아니다. 통합 spec 뒤 초안 예시와 실패 시나리오를 준비하는 일은 병렬로 할 수 있지만, production 경로 구현은 4단계의 classification/query 경계가 안정된 뒤 한다. 그래야 초안이 탈락 어휘 저장소나 우회 ingest로 굳지 않는다. 다음 경계를 먼저 테스트로 고정한다.

- `brain/drafts/<topic-id>.md`만 사용
- 정식 객체, raw evidence, 일반 query/search, snapshot 입력이 아님
- 초안에서 glossary를 자동 확정하지 않음
- 모든 항목을 객체/backlog/classification/discard로 라우팅한 뒤 파일 삭제
- v1 자동 session hook과 완료 archive 없음

### 6. 엔진 스킬 템플릿은 production surface가 생긴 뒤 바꾼다

ingest와 session-ingest가 같은 glossary reference를 읽게 하고, query는 후보 확인과 promotion 승인을 분리한다. audit skill은 먼저 read-only report를 내고, 명시 요청 전에는 repair/apply로 넘어가지 않는다. 초안 발견·정리 절차도 이때 추가한다.

템플릿을 먼저 쓰면 아직 없는 CLI/kind/검증 필드를 에이전트에게 약속하게 된다. 설치 reference 변경은 installer와 설치 runtime 검증 대상이라는 변경 지도도 따른다([change map](../architecture/change-map.md#L31-L51)).

### 7. 합성·임시 설치 검증을 닫는다

표적 red→green, full engine suite, 설치 runtime unittest를 돌린다. 임시 프로젝트에 두 번 install해 두 번째의 `created/updated/removed/adopted/skipped`가 모두 비어야 한다. 설치기는 현재도 4종 skill, 전체 object template kind 집합, 두 번째 no-op을 테스트한다([installer tests](../../tests/test_installer.py#L202-L223), [idempotence](../../tests/test_installer.py#L278-L292), [object contracts](../../tests/test_installer.py#L343-L400)).

### 8. 복제 BB2에서 audit와 migration을 리허설한다

live `brain/`과 config를 복제하고 격리된 엔진을 명시해 real-corpus checks, lint/audit, 필요한 eval을 실행한다. 먼저 read-only glossary audit를 반복해 같은 분류와 plan hash가 나오는지 확인한다. 모호한 항목은 사용자가 결정하고, 그 뒤 snapshot·exact plan·apply·post-check·rollback을 복제본에서 끝까지 검증한다.

### 9. 두 번 승인받은 뒤 live에 컷오버한다

기존 canonical repair가 사용한 원칙처럼 분류/decision ledger 승인과 byte-exact staging·회귀 승인 두 게이트를 둔다([design canonical](../design-canonical.md#L250-L256)).

1. BB2 쓰기를 잠시 멈추고 두 repo의 dirty 상태를 checkpoint한다.
2. 검증된 stable engine checkout으로 글로벌 editable 링크의 대상을 전환한다. 이 시점부터 Python 변경은 즉시 live다.
3. BB2 skill은 `--force` 없이 install하고 `skipped`·diff를 검토한다. 두 번째 install이 no-op인지 확인하고 새 에이전트 세션에서 discovery를 확인한다.
4. 새 코드로 live **read-only audit**를 다시 실행하고 exact migration plan을 승인받는다.
5. 승인된 apply 후 schema/lint/audit/checks를 실행한다. glossary term·synonym·alias와 실제 corpus가 바뀌므로 후속 search/eval 전 index rebuild가 필요하다([rebuild conditions](../architecture/change-map.md#L53-L69)).
6. query 회귀와 rollback 증거까지 확인한 뒤 종료한다.

## BB2를 query-only로 쓰는 동안의 허용 범위

| 가능 | 금지 또는 별도 승인 필요 |
|---|---|
| 현재 설치 skill로 `query`·`show`, 기존 fresh DB에서 `search` | main checkout의 Python core 수정 후 bare `project-brain`을 live BB2에 실행 |
| 별도 worktree/venv의 문서·spec·합성 구현 | live BB2 `install`, `bootstrap`, `--force` |
| 임시 target의 installer 2회 검증 | live `ingest`, `promote`, projection write, migration apply, snapshot create/restore |
| 복제한 BB2의 audit·migration 리허설 | live index rebuild, 기본 `audit`, `stale-check --write-cache`, `doctor --download` |
| live 파일·DB의 직접 read-only inventory | 새 kind를 먼저 쓰거나 수기 JSON으로 우회 |

현재 index DB가 존재하고 fresh라서 통상 query-only 사용은 가능하다. 그래도 “파일 하나도 생성하지 않는” 감사가 필요하면 복제본을 쓴다. `audit`은 기본 stale cache를 쓰고 `--no-stale-cache-write`만 전체 검사를 하되 cache 게시를 막는다는 현재 명령 경계도 지켜야 한다([README](../../README.md#L71-L98), [runtime map](../architecture/runtime-map.md#L294-L307)).

## 검증 결과와 해석

2026-08-14 현재 checkout을 명시한 Python으로 다음 검증이 완료됐다.

- 전체 엔진 suite: **2,083 passed + 136 subtests passed**, 565.92초
- architecture/installer/skill/raw 표적 집합: **98 passed + 15 subtests passed**
- 설치되는 ingest runtime unittest: **125 passed**

프로젝트가 요구하는 엔진 suite와 설치 runtime의 이중 검증 구조는 README에 명시돼 있다([README](../../README.md#L133-L144)). 이 결과는 **현재 dirty checkout의 테스트 건강성**을 보여 준다. untracked ADR이 승인됐거나 `GlossaryClassificationRecord`, generic verification, knowledge draft, BB2 migration이 구현됐다는 증거는 아니다.

이번 감사에서는 설치·mutation·index rebuild·BB2 변경을 실행하지 않았다. 따라서 최종 판정은 다음과 같다.

> **현재 query-only 경계는 유지할 수 있다. 새 방향은 먼저 격리된 엔진에서 spec과 공통 검증 관문부터 구현한다. live BB2 corpus audit는 read-only shadow 검증이 끝난 뒤, migration은 별도 두 승인과 exact plan을 통과한 뒤에만 한다.**
