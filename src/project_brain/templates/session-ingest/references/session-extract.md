# (다) 과거 세션 추출 — 코어 절차 + 입력 3모드

## 입력 3모드 (코어는 동일)

| 모드 | 흐름 |
|---|---|
| 세션 직접 지정 | 사용자가 지목한 세션에 코어 절차 |
| 주제·기능 단위 | `project-brain session list --project {{REPO}}`로 후보 발견 → 관련성 판단(요약·grep) → 관련 세션들에 코어 반복 |
| 일괄 백필 | `session list --unprocessed` 순회 → 세션마다 코어. 마킹 덕에 중단·재개 안전 |

## 코어 절차

1. transcript Read — 세션 경로는 `session list` 출력의 path. cwd는 CLI가 payload 기준으로
   판별해 줌(디렉토리명은 정본 아님 — 워크트리 세션 포함).
2. kind별 후보 추출: DecisionRecord·GlossaryTerm·DomainMapping·TemporalFact(값 변경이면
   update-rules.md의 3객체 묶음). 기존 kind로 못 담는 교훈·함정 → `{{BRAIN_ROOT}}/raw/sources/insights/backlog.md`
   누적(버리지 않는다 — P3 실례). 개인 메모리(주어가 사용자·어시스턴트)는 적재 안 함, 표시만.
3. **검토 라운드** (최대 3): 후보를 표로 일괄 제시 → 사용자 자연어 일괄 응답 → 반영.
   중복 의심은 경고 표시만(자동 제외 금지). **3라운드 소진 후 미합의 후보는 적재하지 않고**
   mark-processed `--note`("미합의 N건")로 남긴다 — 사용자가 결정하지 않은 것은 코퍼스에
   넣지 않는다.
4. ingest → 적재 후 4단계(SKILL.md 공통 규칙) → `project-brain session mark-processed <uuid>`.

## 가드

- **과거 진술 주의**: 세션 내용은 "그 시점 사실" — 현재 {{DEFAULT_BRANCH}} 코드와 대조 전에는 reviewed
  금지. 충돌 시 코드 정설 + caveat. 단 코드에 없는 지식(의도·결정)의 사용자 진술 자체는
  reviewer=user-statement로 reviewed 가능(전례: decision.petskill-honeyjar.data-first-processing-order).
- **id 안정성**: 추출물 id는 의미 기반 결정론(`kind.context.slug`) — 같은 대상은 재추출에서도
  같은 id(부분 적재 후 재실행이 ingest 멱등과 결합돼 중복을 안 만든다).
- **EvidenceManifest**: source_type=session, locator=`claude-session:<uuid>#<날짜>`,
  redaction_status=**"approved" 명시**(화이트리스트 게이트 — 다른 값은 답이 restricted 처리됨).
  세션 로그 raw는 brain에 저장하지 않는다(참조만).
