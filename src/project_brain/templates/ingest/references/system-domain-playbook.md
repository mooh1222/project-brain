# 시스템 도메인 적재 플레이북 — 운영 절차

개념 단위 도메인을 여러 컨텍스트와 긴 코드 흐름으로 적재할 때 쓰는 **대규모 운영편**이다. 기획서 없는 코드 정본
도메인이 핵심 클래스 수십 개·스프라이트 수백 종·만 줄 넘는 파일·여러 컨텍스트로 클 때 쓴다.
작은 개념 하나(매핑 몇 개)면 이 파일 대신 라우터와 필요한 책임 reference만 읽는다.

이 파일은 절대 규칙·객체 모델·검수 절차를 **대체하지 않는다**. 그 위에 "어떻게 손을 움직이나"만
얹는다. 아래 6개는 이 절차를 처음 즉석 설계할 때 에이전트가 매번 틀리는 지점이다(실측 baseline).

## 개념 단위 렌즈

기획서가 없으면 개발 완료 코드가 canonical이다. 착수 브리핑은 데이터 소스, 구조/표시 패턴, 확장 지점,
규칙/함정, 과거 결정 다섯 요소로 코드와 보조 근거를 훑는다. 이때 확장 지점 종합 매핑 1개를 만들어
새 기능을 넣을 때 만질 경계를 모은다. 여러 기능에 공통인 것은 공통분모만 일반화하고, 기능별 차이는
각 기능의 매핑과 경계에 유지한다.

## 목차

- [연결과 조립](#1-연결은-메인이-조립으로-통제한다--추출-에이전트에게-json-연결을-맡기지-마라)
- [추출·검증과 코드 흐름 게이트](#2-추출--extractverify-파이프라인-코드-대조-적대검증)
- [대량 워크플로우 완료와 재개](#3-대량-워크플로우-완료와-재개)
- [많은 ID 승격](#4-promote에-많은-id-넘기기--셸-단어분리-주의엔진-정상-또는-함수-호출)
- [기존 객체 재사용](#5-기존-컨텍스트용어-재사용-확장-적재일-때)
- [한 묶음 적재와 흔한 실수](#6-한-묶음-원자-ingest-슬라이스-분할-금지)

## 1. 연결은 메인이 조립으로 통제한다 — 추출 에이전트에게 JSON 연결을 맡기지 마라

가장 큰 함정. 추출 에이전트가 완성된 brain 객체 JSON(`id`·`glossary_term_ids`·`code_locator_ids`·
`evidence_refs` 연결까지)을 만들게 하면 **그 연결은 거의 날조다** — 존재하지 않는 id를 가리키거나
엉뚱하게 교차한다(과거 critic이 기능당 11~23건 적발). 라인·심볼은 코드를 읽었으니 맞지만,
객체 사이 연결은 에이전트가 지어낸다.

분리 원칙:
- **추출 에이전트 = 의미 원자 노트만.** 구조화 스키마로 받는다(Workflow `schema` 옵션으로 강제):
  `mapping_key` / `canonical_summary` / `meaning` / `boundary` /
  `code_anchors[{key, path, symbol, quote}]` / `glossary_term_keys`(연결 대상의
  논리 key만, 실제 id 아님) / `uncertainty`(코드로 안 잡히는 의도 — 예외 큐로) / `overlap_with_existing`.
- **메인(부모) = 결정론적 조립 = `project-brain build`.** 추출 노트를 build 노트(JSON: context/
  sources/glossary/code_anchors/mappings/refs/updates/extra_objects)로 정리해 `project-brain build
  --notes notes.json --objects-file out.json`을 돌리면 id 파생·객체 간 연결(노트의 논리 key → 실제
  id)·기존 용어 재사용(refs/updates)·EvidenceManifest 부여·끊긴 참조 검사·diff를 **엔진이** 한다
  (2026-06-16, `ingest-tools.md` "build" 절). **더는 적재마다 손으로 조립 스크립트를 짜지 않는다.**
  build로 표현 못 하는 것(1차 기준: DecisionRecord 조립, session 등 비-code EvidenceRef)만
  `extra_objects[]`(완성 객체 직접)나 소량의 손 코드로 보완한다. 에이전트가 만든 자유 연결은 여전히
  신뢰하지 않는다 — 노트의 연결은 논리 key이고, 실제 id는 build가 만든다.
- **ingest 전 무결성은 build가 본다.** build가 끊긴 참조(dangling)·EvidenceRef→manifest·updates
  union 대상 실존을 2층 검증으로 잡아 `errors`로 돌려준다(ingest의 lint 게이트보다 먼저). build
  errors가 비어야 ingest로 넘어간다 — 조립 스크립트에 손으로 dangling 검사를 짤 필요가 없어졌다.

자유 텍스트 노트보다 **구조화 노트**가 낫다 — 조립 스크립트가 그대로 순회해 객체를 찍어낸다.

## 2. 추출 = extract→verify 파이프라인 (코드 대조 적대검증)

Workflow로 컨텍스트/그룹별 병렬 처리한다(`pipeline`):

코드 흐름을 근거로 쓰기 전에는 프로젝트 `AGENTS.md`와 프로젝트의 코드 검증 규칙을 읽고 따른다.
`references/project-code-verification.md`가 있으면 코드 기반 extract/verify 전에 반드시 읽는다. 호출처
추적 기록을 결과에 남기며, 호출처를 추적할 수 없는 경계에서는 그 이유와 대체 확인 기록을 남긴다.
읽은 프로젝트 검증 계약은 동적 workflow와 하위 작업자의 프롬프트에도 그대로 전달한다. 코드로 확인할 수
있는데 계약에 맞는 확인 기록이 없으면 `needs_user`가 아니라 검증 실패다.

- **extract**: 담당 그룹의 코드를 읽고 위 노트 스키마로 의미 원자를 뽑는다.
- **verify**: 읽기 전용 검증자로 extract 노트를 받아 각 `code_anchor`를 실제
  파일에서 열어 라인·심볼·quote 일치를 확인하고, `meaning`의 과장·근거 초과·중복·경계 침범을
  적발·수정한다. 반환에 `issues[]` + `verdict`(pass/fixed/needs_user)를 담게 한다.
  `needs_user`는 미완료 상태다. workflow top-level completed나 후속 runner가 이를
  성공이나 finalized로 바꾸면 안 된다.

verify가 **적대검증 역할**을 한다(라인 어긋남·과장·날조를 이미 본다). 따라서 **별도 critic 워크플로우는
대개 중복**이다 — verify를 돌렸으면 critic은 생략하고, reviewer를 `extract-verify-workflow`로
정직하게 기록한다. critic은 verify를 못 돌렸거나 "묶음 전체를 가로지르는 중복·일관성"이 꼭 필요할 때만.

리뷰어(verify·critic)는 반드시 읽기 전용으로 둔다. 쓰기 도구를 주면 검증 대상인 실파일을
오염시킬 수 있다. 실행 환경에 맞는 읽기 전용 작업자나 권한 설정을 사용한다.

## 3. 대량 워크플로우 완료와 재개

최상위 `completed`만으로는 조립 단계로 넘어가지 않는다. 결과 JSON을
`scripts/validate_workflow_result.py`에 통과시켜 예상 항목 수, 중복 없는 key, 빈 실패 목록, 모든
extract/verify `ok`, `pass` 또는 `fixed` verdict를 확인한 뒤에만 조립한다.

세션 한도처럼 재개 가능한 실패는 완료나 차단으로 바꾸지 말고 미완료 report로 남긴다. **같은 run ID와
같은 입력**으로 실패 항목을 재개하고, 새 결과 JSON에 validator를 다시 실행해 통과할 때만 다음 단계로
간다.

## 4. promote에 많은 id 넘기기 — 셸 단어분리 주의

`promote --ids`는 `nargs='+'`로 여러 인자를 정상으로 받는다(리터럴 `--ids a b c` → 3개로 인식,
엔진 버그 아님). 함정은 **셸**이다: **zsh는 비따옴표 변수(`--ids $VAR`)를 단어분리하지 않아**(bash와
다름) 전체가 한 id로 들어가 "unknown ids"로 실패한다. id를 리터럴로 나열하거나 zsh 배열을 쓰고,
매핑 묶음 승격 뒤에는 공개 CLI인 `promote-auto`로 보증된 용어를 승격한다.

```bash
project-brain promote \
  --ids mapping.example.one mapping.example.two \
  --scope mapping_bundle \
  --bundle-key bundle.example.domain-mapping \
  --reviewer extract-verify-workflow
project-brain promote-auto --ids g.example.one g.example.two
```

용어 `eligible` 가드(매핑 보증 없음·근거 없음으로 빠지는 것)는 곧 **고아 진단**이다 — unref/no_evidence가
나오면 그 용어는 매핑에 안 엮였다는 뜻이니 조립을 고친다(규칙 7).

## 5. 기존 컨텍스트·용어 재사용 (확장 적재일 때)

대상 도메인에 이미 적재된 컨텍스트/용어가 있으면(예: 방해버블 `disturb-bubble-system`) 새로 만들지
않는다. 기존 객체는 `{{BRAIN_ROOT}}/objects/domain/`(`context.*.json`·`g.*.json`)·`{{BRAIN_ROOT}}/objects/mappings/`(`mapping.*.json`)에서
조회한다. id 컨벤션은 `mapping.<ctx-slug>.<key>` / `g.<ctx-slug>.<term-key>` / `code.<ctx-slug>.<anchor>`이고
조립이 이 형식으로 만든다(`term.*`·`objects/glossary-terms/` 같은 경로·prefix는 없다 — 추측 금지, store 파일로 확인):
- **기존 용어 key는 기존 id로 resolve**(재정의 금지). 조립 스크립트에 `EXISTING_TERM_IDS` 매핑 테이블을
  두고, 추출이 같은 key를 다시 정의했어도 새 GlossaryTerm을 만들지 말고 기존 id를 매핑이 가리키게 한다.
- **기존 컨텍스트는 멱등 갱신.** 기존 DomainContext 객체를 읽어 `glossary_term_ids`에 신규 용어를 더해
  다시 ingest한다(reviewed 유지, ingest는 reviewed→reviewed 멱등).
- **컨텍스트 간 공유 용어**는 주인 1곳에만 GlossaryTerm을 두고(`TERM_OWNER` 결정), 그 용어를 쓰는 다른
  컨텍스트의 매핑이 `glossary_term_ids`로 교차참조해 기능 범위 질의에서도 회수되게 한다.

## 6. 한 묶음 원자 ingest (슬라이스 분할 금지)

`ingest`는 묶음 전체의 연결무결성을 저장 전에 한 번에 검사하고 rollback transaction으로 쓰므로,
**한 파일에 전 객체(컨텍스트·매핑·용어·코드·근거·매니페스트)를 담아 한 번에 넣으면** 객체 생성
순서와 무관하게 검증한다. context→manifest→code→term→evref→mapping 식으로 여러 묶음에 나눠
순차 ingest할 필요가 없다.
나누면 "참조 대상이 먼저 들어와야 한다"는 순서 부담만 생긴다.

## Common Mistakes (baseline 실측)

| 실수 | 바로잡기 |
|---|---|
| 추출 에이전트에게 완성 JSON(연결 포함) 생성 | 노트(구조화 스키마)만. id·연결은 메인이 결정론적 조립으로 (§1) |
| `promote --ids $VAR` (zsh 비따옴표 변수) | zsh는 단어분리 안 함 — 리터럴/`${=VAR}`/배열, id 많으면 함수 호출 (§4) |
| 추출물을 자유 텍스트 초안으로 | Workflow `schema`로 구조화 노트 강제 (§1·§2) |
| critic 워크플로우 무조건 추가 | verify가 코드대조 적대검증이면 critic 중복 — 생략하고 reviewer 정직 기록 (§2) |
| 객체를 7단계 슬라이스로 나눠 순차 ingest | 한 묶음에 다 넣어 저장 전 전체 연결을 검증 (§6) |
| 확장 적재인데 기존 용어를 새로 정의 | 기존 id 재사용·기존 컨텍스트 멱등 갱신 (§5) |
| 리뷰어 에이전트에 쓰기 도구 부여 | 실행 환경의 읽기 전용 작업자나 권한 설정을 사용 (§2) |

완료 게이트는 `completeness-checklist.md`, 실행 명령과 저장 절차는 `ingest-tools.md`가 맡는다.
여기서는 그 계약을 반복하지 않는다.
