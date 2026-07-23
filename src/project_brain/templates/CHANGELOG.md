# project-brain 스킬 템플릿 변경 이력

엔진(`project-brain`)이 install로 주입하는 스킬 템플릿(`templates/<skill>/`, skill∈{ingest,query,
session-ingest,audit} — 각 `SKILL.md` + `references/` + `scripts/`을 디렉토리 통째 walk로 주입
→ 데이터레포 `.agents/skills/<project>-<suffix>/`; SKILL.md 한 장이 아니라 하위 파일 전부)의
구조·도구 주요 변경만 1줄로 남긴다.

★베이스는 엔진 `templates/`다.★ 데이터레포(bb2 등)는 install로 받은 스킬을 실사용하며 개선하고,
그 개선분이 여기로 **역수입돼 누적**된다(스킬은 엔진 소유, 데이터레포는 소비·개선처). 사용법
상세는 각 템플릿(`templates/<skill>/SKILL.md`)·`references/`. 엔진 코어(스키마·검색·
적재 엔진) 변경 이력은 [ROADMAP.md](../../../ROADMAP.md). 적재된 데이터 이력은 각 데이터레포의 `brain/`.

## 2026-07-23 — 대량 적재 최종 안전 보강

kind별 기존 객체 갱신 규칙의 단일 원본을 ingest `references/update-rules.md`로 옮기고
session-ingest는 그 파일을 참조하게 했다. single runner는 semantic finalization 결과의
정확한 구조와 `ok`를 확인하고, batch runner는 baseline·입력 fingerprint·resume report를
검증하며 manifest/verify/domain 입력과 같은 report 경로 또는 심링크 별칭을 실행 전에
거부한다. 내용이 같은 manifest 밖 스크립트를 채택할 때 실행 비트를 템플릿과 맞춘다.

installer는 템플릿에서 사라진 미수정 관리 파일을 설치본과 manifest에서 퇴역시킨다.
manifest 임시 파일을 먼저 완성하고 퇴역 원본을 같은 디렉토리 backup으로 옮긴 뒤 확정하며,
중간 이동이나 manifest 교체 실패 시 역순 복원한다. 사용자 수정 파일·프로젝트 overlay,
심링크·상위 경로 탈출·비일반 파일은 기존 보존/거부 경계를 유지한다.

## 2026-07-22 — 대량 적재 완료 계약 강화

완성 ID를 논리 key로 넣지 못하게 막고, raw 청크의 토큰 수는 보수적으로 추정해 과대 단위를 안전하게 나누며, 개정 기획서의 `spec-v<N>.md`와 대량·이전 자료 보관용 정리된 원본 basename 규칙(충돌 시 SHA-256 접미사)을 분리했다. 여러 항목은 `run_ingest_batch.py`가 처리하고 모두 성공한 뒤 `finalize_ingest.sh`는 한 번만 수행한다. 동적 workflow 결과는 `validate_workflow_result.py`를 통과해야 다음 단계로 간다. 코드 기반 작업은 선택적 `references/project-code-verification.md`를 읽어 그 계약을 동적 workflow와 하위 작업자에게 전달한다. SKILL.md는 실행 경로 중심 148줄로 줄였다.

## 2026-07-01 — 적대검증 진정성 문구 보강 + 안전장치 B 폐기(엔진 변경 없음)

completeness-checklist 8번: 적대검증을 의무로 못 박아도 "완료" 도장으로 퇴화하면 무의미 — 핵심은 단계 존재가 아니라 실제 반박 시도, 코드로 강제 못 하는 행동 완화책임을 한 줄 보강. 안전장치로 검토하던 DecisionRecord.verification_note 하드 게이트(설계 B)는 4렌즈+surface 교차검증 결과 헛도장(빈값 검사는 구문 층이라 "근거 있는데 모순"에 못 닿음)으로 판정해 **폐기 — 엔진 변경 없음**. 결정 근거·후속 위생 티켓은 `docs/plans/2026-06-30-ingest-skill-retro-improvements.md`("P0 후속") + `docs/plans/2026-07-01-decisionrecord-evidence-refs-hygiene.md`.

## 2026-06-30 — 적재 회고 반영: 적대검증 의무화 + 머지 전 앵커 경계 + PR/evref 문서 보강

completeness-checklist 8번: 고위험 객체(DecisionRecord·supersede·code anchor·history_coverage=complete) 재구성 감사를 "선택"→"필수"로, 메모리 서사를 결정에 옮길 땐 코드/원문 대조 적대검증 의무를 명시(메모리 기반 허위 DecisionRecord 방지 — 럭키박스 세션 실측). scope.md: 기본은 머지 후 앵커 / 머지 전 PR HEAD SHA는 그 PR이 merge-commit으로 머지될 게 확실할 때만(머지 방식은 레포 속성 아닌 per-PR 선택, 죽은 SHA는 lint dangling에 안 걸려 조용히 깨짐) 경계 추가. domain_spec.template.py·ingest-tools.md: PR manifest 예시 + commit(locator={repo,sha} auto)/jira·pr(locator 수동) 형식·evref `<ctx>.<type>-<ref>` id 형식 명시. run_ingest.sh: EXPECTED_RAW_CHUNKS 드리프트 ≠ 적재 실패 주석. 근거: `docs/plans/2026-06-30-ingest-skill-retro-improvements.md`.

## 2026-06-29 — 디렉토리 통째 주입 + bb2 정합본 역수입 + 변수화

주입 단위를 SKILL.md 한 장 → `templates/<skill>/` 디렉토리 통째 walk로 확장(`references/`·`scripts/` 포함, `__pycache__`·`fixtures`·`*.pyc`·`test_*.py` 제외). bb2 실사용 개선분을 엔진 templates로 역수입하며 `{{PROJECT}}`/`{{BRAIN_ROOT}}`/`{{DEFAULT_BRANCH}}`/`{{REPO}}` 변수화 동반. glossary 세션이 덮어쓴 ingest 동의어 섹션도 복원. 엔진 커밋 `6d6a936`(walk)·`5ca5405`(역수입)·`6722d65`(synonyms 복원).

## 2026-06-26 — ingest 스킬에 GlossaryTerm 동의어 작성 규칙

`ingest.md`에 용어 동의어(`synonyms`/`aliases`) 작성 규칙 섹션 추가 — **한국어↔영문 등가어 우선**
(코퍼스 term 다수가 영문 코드명·enum이라 한국어 질의 갭이 큼), **흔한 단일어 금지**(답변 게이트의
표면 앵커 df를 흔들어 거짓양성 가드 약화), definition 본문 중복 금지. 엔진 통로(`build_glossary_terms`
의 synonyms/aliases 운반 + `_UNION_ALLOWLIST` 백필)와 한 묶음. bb2 실측: 무해(골든셋 10/10), recall은
고유 등가어에서만 뚜렷. 엔진 커밋 `4987f86`.

## 2026-06-26 — 적재 조립 시스템화 (손조립 → 재사용 스캐폴드)  [bb2 실사용 개선분 — 역수입 완료]

적재마다 손으로 짜던 조립 스크립트를 재사용 스캐폴드로 대체. `scripts/assemble_notes.py`(verify출력+domain_spec→notes 제네릭 조립기) + `domain_spec`(적재별 데이터) + `run_ingest.sh`(assemble→build→…→graph 러너, `--dry` 비파괴) + `extract_template.js`(추출 골격) + `references/ingest-case-log.md`(변칙 누적). **왜:** DecisionRecord 손조립이 타임스탬프 churn·양방향 링크 수동맞춤 실수를 냈다 → `decisions[]` 노트 패스스루로 전환(엔진 `build_decisions`가 DecisionRecord+EvidenceRef 조립·`affects`→`decision_keys` 역채움으로 lint 8c 양방향 자동). 실코퍼스 회귀로 ball-select(368객체·14결정)·main-map(341객체) 코퍼스 동치 확인. bb2 커밋 `2444e6d226`..`5a59a0b273`. (scripts/references 본체 역수입 완료 — `templates/ingest/scripts`·`references`에 본체 존재, 변수화 동반: 엔진 커밋 `5ca5405`.)
