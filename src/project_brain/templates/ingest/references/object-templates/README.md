# 객체 계약 JSON

이 디렉터리는 적재 작업에서 입력 모양을 추측하지 않도록, 현재 엔진이 직접 검증하는 JSON
예시를 한곳에 모은다. 설명만 보고 새 payload를 만들기보다 목적에 맞는 파일을 복사한 뒤
`build → ingest` 또는 해당 전용 쓰기 경로로 확인한다.

## 어떤 파일을 써야 하나

| 목적 | 파일 | 보장 범위 |
|---|---|---|
| build 노트 작성 | `build-notes.complete.template.json` | 9개 section을 모두 사용하며 `validate_notes()`와 `build()`를 통과한다 |
| 연결된 저장 객체 확인 | `object-graph.complete.template.json` | 6개 reviewed 객체가 하나의 연결 요소를 이루며 schema·ID·lint를 통과한다 |
| kind 하나의 키 모양 확인 | `kinds/<Kind>.template.json` | 19종 각각의 공통·kind 필수 키와 정식 ID 문법을 통과한다 |
| 실패가 잡히는 층 확인 | `invalid/manifest.json` | notes·schema·lint·mutation 네 층의 의도적 실패 10건을 재생한다 |

`kinds/` 파일은 **저장 객체의 모양 참고용**이다. 참조 대상이 같은 store에 없을 수 있고,
전용 쓰기 검증이나 생성기 계산값까지 혼자 충족한다고 보장하지 않는다. 여러 객체를 실제로
적재할 때는 `object-graph.complete.template.json`처럼 모든 등록 참조를 닫아야 한다.

## 복사한 뒤 바꿀 값

JSON에는 설치기가 알지 못하는 임의 placeholder가 없다. 따라서 고정 합성값을 그대로 실제
데이터로 쓰지 말고, 다음 값을 근거에 맞게 바꾼다.

- 의미와 출처: `title`, 의미 필드, `locator`, `captured_at`, `acl`, `redaction_status`
- 생명주기: `status`, candidate metadata, review metadata
- 시간과 ID: `created_at`, `updated_at`, 객체 ID와 연결 ID
- 코드 좌표: `repo`, `path`, `commit_sha`, `symbol`, `verified_quote`

ID만 따로 바꾸면 안 된다. `DomainContext.context_key`, `GlossaryTerm.context_id`,
`DomainMapping.context_id`·`mapping_key`, `CurrentView.view_type`, `KnowledgePage.category`,
`IndexRecord.index_name`·`source_object_id`, `SpecRevision.spec_document_id`·`revision_label`,
`SlideRef.spec_revision_id`·`slide_no`, `ContextProjection.context_id`·`format`처럼 ID와 결속된
필드도 함께 바꿔야 한다. 참조 ID를 바꾸면 같은 묶음의 대상과 역방향 연결도 함께 고친다.

## build 입력과 저장 객체는 다른 층이다

`build-notes.complete.template.json`의 일반 section은 의미 중심 입력이다. build가 정식 ID,
`truth_role`, 공통 metadata를 만들고 다음 객체 관계를 조립한다.

- `sources[]` → `EvidenceManifest`
- `code_anchors[]` → `CodeLocator` + `EvidenceRef`
- `glossary[]` → `GlossaryTerm`
- `mappings[]` → `DomainMapping`
- `decisions[]` → `DecisionRecord` + 결정 근거 `EvidenceRef`
- `decisions[].affects` → 해당 `DomainMapping.decision_record_ids` 역채움

반면 `extra_objects[]`는 탈출구다. ID, 상태, 역할, timestamp, 근거와 참조까지 완성된 **저장 객체
전체**를 받는다. build가 빠진 metadata를 추측해 채우지 않는다. `refs`는 기존 객체 ID와 기대
kind/status를 확인하고, `updates`는 `expected_updated_at`과 허용된 `set`/`union`만 사용한다.

## schema 통과와 신규 쓰기 통과는 다르다

검증은 한 단계가 아니다.

1. `validate_notes()`가 build 입력 구조를 검사한다.
2. `validate_object()`와 ID grammar가 객체 모양·enum·ID 결속을 검사한다.
3. lint가 합쳐진 store의 dangling·생명주기·관계 문제를 검사한다.
4. `MutationService`가 상태 전환, 코드 검증, transaction 전제까지 검사한다.

특히 `CodeLocator.template.json`은 shape 참고용이라 `verified_at`가 있지만 `commit_sha`와
`verified_quote`가 없다. 새 locator, 좌표가 바뀐 locator, `mark-checked`는 repo context와 full
commit SHA, 실제 symbol·quote가 필요하다. verifier가 성공한 뒤 `verified_at`와 표준 `title`을
확정한다. 좌표가 그대로인 과거 객체의 quote 누락을 읽고 보존할 수 있다는 사실을 신규 쓰기
허용으로 일반화하면 안 된다.

`ContextProjection.template.json`의 hash는 고정 합성 source로 생성한 값이다. source나 payload를
바꾸면 공식 projection builder로 다시 계산한다. `ReviewRecord`는 보통 `promote()`가 대상 객체의
`review_record_id`와 함께 만든다.

## 현재 확인된 빈틈

- 공통 reference registry는 대부분 참조 대상의 **존재**를 검사하지만 target kind까지 일반적으로
  강제하지 않는다. 정상 그래프는 테스트가 의도 kind를 별도로 확인한다.
- `SpecRevision.slide_refs`와 `SlackThread.message_refs`는 현재 registry 밖이다. 빈 배열 예시는
  요소 구조나 dangling 검증이 완성됐다는 뜻이 아니다.
- `KnowledgePage.stale_policy`와 `IndexRecord.content_hash`의 제품 수준 의미는 schema가 확정하지
  않는다. 예시 값은 현재 shape·ID 검증을 통과하는 합성값이다.
- `KnowledgePage`, `IndexRecord`, `SpecDocument`, `SpecRevision`, `SlideRef`, `SlackThread`는 현재
  전용 creator와 검색 표면이 없고 direct `extra_objects[]`/저장·graph 중심이다.
- `ContextProjection.source_object_ids`는 schema상 빈 배열도 가능하지만 공식 생성기는 실제 source를
  전제로 한다.

이 빈틈은 예시 JSON으로 덮어쓰지 않는다. 엔진 동작을 바꿀 일은 별도 설계와 회귀가 필요하다.

## 실패 예시 읽는 법

`invalid/manifest.json`의 각 case에는 첫 실패 층, validator, 필요한 base fixture, 기대 error
code 또는 메시지 조각이 들어 있다. 단일 JSON만 보고 결과를 추측하지 말고 manifest의 setup까지
같이 실행한다. 예를 들어 좌표 변경 CodeLocator 반례는 기존 locator와 임시 git repo가 있어야
`quote_required`까지 도달한다.

엔진 checkout의 전체 19종 계약과 소비처는 `docs/architecture/data-contracts.md`가 정리한다.
