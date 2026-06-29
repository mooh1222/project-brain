# 시스템 도메인 적재 플레이북 — 운영 절차

"개념 단위 도메인 적재" 분기(SKILL.md)의 **대규모 운영편**이다. 기획서 없는 코드 정본
도메인이 핵심 클래스 수십 개·스프라이트 수백 종·만 줄 넘는 파일·여러 컨텍스트로 클 때 쓴다.
작은 개념 하나(매핑 몇 개)면 불필요 — SKILL.md 분기만으로 충분하다.

이 파일은 절대 규칙·객체 모델·검수 절차를 **대체하지 않는다**. 그 위에 "어떻게 손을 움직이나"만
얹는다. 아래 5개는 이 절차를 처음 즉석 설계할 때 에이전트가 매번 틀리는 지점이다(실측 baseline).

## 1. 연결은 메인이 조립으로 통제한다 — 추출 에이전트에게 JSON 연결을 맡기지 마라

가장 큰 함정. 추출 에이전트가 완성된 brain 객체 JSON(`id`·`glossary_term_ids`·`code_locator_ids`·
`evidence_refs` 연결까지)을 만들게 하면 **그 연결은 거의 날조다** — 존재하지 않는 id를 가리키거나
엉뚱하게 교차한다(과거 critic이 기능당 11~23건 적발). 라인·심볼은 코드를 읽었으니 맞지만,
객체 사이 연결은 에이전트가 지어낸다.

분리 원칙:
- **추출 에이전트 = 의미 원자 노트만.** 구조화 스키마로 받는다(Workflow `schema` 옵션으로 강제):
  `mapping_key` / `canonical_summary` / `meaning` / `boundary` /
  `code_anchors[{path, symbol, quote}]` / `glossary_term_keys`(연결 대상의
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

- **extract** (`model: 'opus'`): 담당 그룹의 코드를 읽고 위 노트 스키마로 의미 원자를 뽑는다.
- **verify** (`agentType: 'Explore'` + `model: 'opus'`): extract 노트를 받아 각 `code_anchor`를 실제
  파일에서 열어 라인·심볼·quote 일치를 확인하고, `meaning`의 과장·근거 초과·중복·경계 침범을
  적발·수정한다. 반환에 `issues[]` + `verdict`(pass/fixed/needs_user)를 담게 한다.

verify가 **적대검증 역할**을 한다(라인 어긋남·과장·날조를 이미 본다). 따라서 **별도 critic 워크플로우는
대개 중복**이다 — verify를 돌렸으면 critic은 생략하고, reviewer를 `claude-extract-verify-workflow`로
정직하게 기록한다. critic은 verify를 못 돌렸거나 "묶음 전체를 가로지르는 중복·일관성"이 꼭 필요할 때만.

리뷰어(verify·critic)는 반드시 읽기 전용(`agentType: 'Explore'`)으로 — 쓰기 도구를 주면 실파일을
오염시킨다(반복 사고). Explore는 모델이 Haiku로 떨어지니 `model: 'opus'`를 같이 박는다.

## 3. promote에 많은 id 넘기기 — 셸 단어분리 주의(엔진 정상), 또는 함수 호출

`promote --ids`는 `nargs='+'`로 여러 인자를 정상으로 받는다(리터럴 `--ids a b c` → 3개로 인식,
엔진 버그 아님). 함정은 **셸**이다: **zsh는 비따옴표 변수(`--ids $VAR`)를 단어분리하지 않아**(bash와
다름) 전체가 한 id로 들어가 "unknown ids"로 실패한다. 해결은 셋 중 하나 — id를 리터럴로 나열,
zsh면 `${=VAR}`나 배열로 분리, 또는 **id가 많고 매핑 묶음 승격→용어 자동승격을 한 흐름으로 돌려야
하면 promote 함수를 직접 부른다**(reviewer·scope·backfill을 한 토막에 묶을 수 있어 편하다). 도구
venv python으로:

```python
# 도구 venv: $(head -1 "$(which project-brain)" | sed 's/^#!//')  (보통 ~/.local/share/uv/tools/project-brain/bin/python3)
import json
from pathlib import Path
from project_brain.promote import promote, select_vouched_candidates, backfill_evidence
from project_brain.ingest import ingest

BR = Path("<repo>/brain")
objs = json.load(open("<조립한 객체파일>.json"))

# 매핑: 컨텍스트별 mapping_bundle 승격
for ctx, bkey in [("context.x", "bundle.x.domain-mapping"), ...]:
    ids = [o["id"] for o in objs if o["kind"] == "DomainMapping" and o["context_id"] == ctx]
    subset = [o for o in objs if o["id"] in ids]
    promoted, reviews = promote(subset, ids, "mapping_bundle", bundle_key=bkey,
                                reviewer="claude-extract-verify-workflow", reviewed_at="<ISO8601>")
    ingest(BR, promoted + reviews)          # 함수 ingest는 저장까지 함

# 용어: 매핑이 reviewed 된 뒤 promote-auto 로직 재현 (cli.py _run_promote_auto와 동일)
store = BrainStore.load(BR)                  # 매핑 reviewed 반영된 새 store
sel = select_vouched_candidates(store)       # {term_id: [보증 매핑 id]}
eligible = [t for t in term_ids
            if t in sel and backfill_evidence(store.get(t), store).get("evidence_refs")]
objects = [backfill_evidence(store.get(t), store) for t in eligible]
review_extra = {t: {"vouched_by_mapping_ids": sel[t]} for t in eligible}
promoted, records = promote(objects, eligible, "single_object",
                            reviewer="auto:mapping-vouched", reviewed_at="<ISO8601>",
                            review_extra_by_id=review_extra)
ingest(BR, promoted + records)
```

용어 `eligible` 가드(매핑 보증 없음·근거 없음으로 빠지는 것)는 곧 **고아 진단**이다 — unref/no_evidence가
나오면 그 용어는 매핑에 안 엮였다는 뜻이니 조립을 고친다(규칙 7).

## 4. 기존 컨텍스트·용어 재사용 (확장 적재일 때)

대상 도메인에 이미 적재된 컨텍스트/용어가 있으면(예: 방해버블 `disturb-bubble-system`) 새로 만들지
않는다. 기존 객체는 `{{BRAIN_ROOT}}/objects/domain/`(`context.*.json`·`g.*.json`)·`{{BRAIN_ROOT}}/objects/mappings/`(`mapping.*.json`)에서
조회한다. id 컨벤션은 `mapping.<ctx-slug>.<key>` / `g.<ctx-slug>.<term-key>` / `code.<ctx-slug>.<anchor>`이고
조립이 이 형식으로 만든다(`term.*`·`objects/glossary-terms/` 같은 경로·prefix는 없다 — 추측 금지, store 파일로 확인):
- **기존 용어 key는 기존 id로 resolve**(재정의 금지). 조립 스크립트에 `EXISTING_TERM_IDS` 매핑 테이블을
  두고, 추출이 같은 key를 다시 정의했어도 새 GlossaryTerm을 만들지 말고 기존 id를 매핑이 가리키게 한다.
- **기존 컨텍스트는 멱등 갱신.** 기존 DomainContext 객체를 읽어 `glossary_term_ids`에 신규 용어를 더해
  다시 ingest한다(reviewed 유지, ingest는 reviewed→reviewed 멱등).
- **컨텍스트 간 공유 용어**는 주인 1곳에만 GlossaryTerm을 두고(`TERM_OWNER` 결정), 그 용어를 쓰는 다른
  컨텍스트의 매핑이 `glossary_term_ids`로 교차참조한다(SKILL.md §11.4 — 이주 용어 scope 필터 누락 방지).

## 5. 한 묶음 원자 ingest (슬라이스 분할 금지)

`ingest`는 묶음 전체의 연결무결성을 한 번에 검사하므로, **한 파일에 전 객체(컨텍스트·매핑·용어·코드·
근거·매니페스트)를 담아 한 번에 넣으면** 객체 생성 순서와 무관하게 통과한다(실패 시 아무것도 안 씀 —
원자적). context→manifest→code→term→evref→mapping 식으로 여러 묶음에 나눠 순차 ingest할 필요가 없다.
나누면 "참조 대상이 먼저 들어와야 한다"는 순서 부담만 생긴다.

## Common Mistakes (baseline 실측)

| 실수 | 바로잡기 |
|---|---|
| 추출 에이전트에게 완성 JSON(연결 포함) 생성 | 노트(구조화 스키마)만. id·연결은 메인이 결정론적 조립으로 (§1) |
| `promote --ids $VAR` (zsh 비따옴표 변수) | zsh는 단어분리 안 함 — 리터럴/`${=VAR}`/배열, id 많으면 함수 호출 (§3) |
| 추출물을 자유 텍스트 초안으로 | Workflow `schema`로 구조화 노트 강제 (§1·§2) |
| critic 워크플로우 무조건 추가 | verify가 코드대조 적대검증이면 critic 중복 — 생략하고 reviewer 정직 기록 (§2) |
| 객체를 7단계 슬라이스로 나눠 순차 ingest | 한 묶음에 다 넣으면 순서 무관·원자적 (§5) |
| 확장 적재인데 기존 용어를 새로 정의 | 기존 id 재사용·기존 컨텍스트 멱등 갱신 (§4) |
| 리뷰어 에이전트에 쓰기 도구 부여 | `agentType: 'Explore'`(읽기전용) + `model: 'opus'` (§2) |

검증·가드 갱신·골든셋 추가·promote-auto 전 커밋은 SKILL.md와 `ingest-tools.md`가 이미 다룬다 —
여기서 반복하지 않는다.
