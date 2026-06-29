# project-brain 스킬 템플릿 변경 이력

엔진(`project-brain`)이 install로 주입하는 스킬 템플릿(`templates/<skill>/`, skill∈{ingest,query,
session-ingest,audit} — 각 `SKILL.md` + `references/` + `scripts/`을 디렉토리 통째 walk로 주입
→ 데이터레포 `.agents/skills/<project>-<suffix>/`; SKILL.md 한 장이 아니라 하위 파일 전부)의
구조·도구 주요 변경만 1줄로 남긴다.

★베이스는 엔진 `templates/`다.★ 데이터레포(bb2 등)는 install로 받은 스킬을 실사용하며 개선하고,
그 개선분이 여기로 **역수입돼 누적**된다(스킬은 엔진 소유, 데이터레포는 소비·개선처). 사용법
상세는 각 템플릿(`templates/<skill>/SKILL.md`)·`references/`. 엔진 코어(스키마·검색·
적재 엔진) 변경 이력은 [ROADMAP.md](../../../ROADMAP.md). 적재된 데이터 이력은 각 데이터레포의 `brain/`.

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
