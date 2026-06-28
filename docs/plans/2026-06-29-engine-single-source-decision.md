# 엔진 단일원본(스킬 관리) — 다음 세션 결정·착수 문서

> **목적:** 우선순위4("엔진이 스킬의 단일 원본")의 **배포모델 결정**을 다음 세션이 바로
> 논의·착수하도록 정리. 2026-06-29 세션이 우선순위1~3 + stale 운용(audit) + 줄번호 정합을
> 완료했고, **이것이 유일하게 남은 미결 항목**이다(사용자가 "가장 후순위"로 둔 것).
>
> 선행 맥락: [감사 후속 정비 플랜](2026-06-27-brain-audit-remediation.md) 우선순위4 + 재논의 섹션,
> ROADMAP "팀 공개"(§4 동반작업)·"locator 정비"(§5)·"코퍼스 감사 audit" 완료 섹션.

## 결정할 것 — 딱 하나

**"엔진이 스킬을 소비 프로젝트(bb2 등)에 어떻게 전달·관리하나"의 배포모델** — 아래 1·2·3 중 택.
사용자는 방향상 "엔진이 최종 스킬 관리 소스"가 맞다고 했고, **1번(installer 확장)으로 기울어
있다**. 다만 1번이 재설계 수준이라 착수 전 이 선택을 확정해야 안전하다.

## 현재 코드 사실 (2026-06-29 검증)

- **installer는 `SKILL.md`만 주입한다.** `install()`(`src/project_brain/installer.py`)이
  `_TEMPLATES`를 돌며 `.claude/skills/{project}-{suffix}/SKILL.md` 한 파일만 렌더·기록.
  `references/`·`scripts/`는 주입 경로에 없음.
- **bb2 manifest = `{"files": {}}` (빔).** install은 manifest에 없는 기존 파일을 "사용자 소유"로
  보고 skip → bb2에 install을 돌려도 아무것도 안 바뀐다(전파 0).
- **레이아웃 불일치.** installer는 `.claude/skills/`에 쓴다고 가정하지만, bb2는
  `.agents/skills/bb2-brain-*`가 원본이고 `.claude/skills/*`는 그 심볼릭 미러. 엔진은
  `.agents/skills/` 구조를 모른다.
- **미주입 자산 규모(install 밖에 있는 것):** `bb2-brain-ingest` SKILL.md 외 **23 파일**
  (references/scripts), `bb2-brain-session-ingest` **3 파일**. query·audit은 0.
- **엔진 templates 현재 범위:** `query.md / ingest.md / session-ingest.md / audit.md` + `CHANGELOG.md`.
  references/scripts 하위 디렉터리 자체가 없음(= 베이스가 SKILL.md급만 보유).
- **하드코딩(역수입 시 일반화 대상):** bb2 `scripts/`에 리터럴 `bb2_client` 5파일, `develop` 1파일
  (references까지 전수 grep은 착수 시 확정). `bb2`→`{{PROJECT}}`, REPO·기본 브랜치는 변수/재서술 필요.

## 세 방식 + 장단

**1. installer를 디렉토리 통째 주입으로 확장** (사용자가 기운 방향)
`install`이 SKILL.md 하나가 아니라 **스킬 폴더 전체(SKILL.md + references/ + scripts/)**를
렌더·복사하도록 키운다. 엔진이 완본 스킬을 보유하고 install이 프로젝트로 민다.
- 장점: 진짜 단일 원본, 명령 하나로 전파. "엔진이 최종 소스"와 정확히 부합.
- 단점: **재설계 수준.** 디렉토리 walk(`.md`/`.py` 치환 분기, `__pycache__`·`.pyc`·fixtures 제외),
  `.agents/skills/` 레이아웃 반영, bb2 scripts 하드코딩 일반화, manifest 순서(아래 위험).

**2. 별도 scaffold(초기 골격) 배포 도구**
install과 분리된 "처음 한 번 골격만 까는" 도구. 깐 뒤엔 프로젝트가 소유·편집.
- 장점: 단순, clobber 위험 없음(1회성).
- 단점: 진짜 단일 원본은 아님 — 깐 뒤 갈라지면 공통 수정은 여전히 수동.

**3. 자동화 없이 문서화**
엔진에 "스킬 손조립법"을 문서로. 엔진 = 참고 문서, 전파 도구 아님.
- 장점: 새 코드 0, 위험 0.
- 단점: 완전 수동(현행과 같되 문서만 갖춤).

## 착수 위험 — 순서 엄수 (1번 택할 때)

**역수입(bb2 → 엔진) 먼저 → 엔진 머지 → 그 다음에만 manifest 채우기/install.**
순서를 어기면 엔진의 (짧은) 베이스 템플릿이 bb2의 (풍부한) 스킬을 덮어 발전분이 소실된다.
manifest가 비어 전부 skip이고 `--force`가 없는 현재 상태가, 역수입 전 잘못 install해도
덮지 않게 막아주는 안전판이기도 하다(채우는 순간 사라짐 — 그래서 채우기가 맨 마지막).

내부 절대순서(1번):
1. installer를 디렉토리 walk로 확장(제외 필터 + `.md`/`.py` 치환 분기). templates/에 references/·scripts/ 신설.
2. bb2 정합본 역수입: `bb2`→`{{PROJECT}}`, REPO·`develop` 일반화, 도메인 예시 일반화, fixtures 제외.
3. 엔진 머지(이미 정합된 베이스 항목 제외 — 이번 세션이 advisories·UTC Z→KST·graph isolated B+C·줄번호·audit까지 맞춰둠).
4. **역수입 완료 확인 후에만** manifest 채우기/install.
5. 이후 규율: "bb2 직접수정 금지"(단일원본의 대가).

## 맥락 — 지금 깨진 건 없다

이번 세션 변경(advisories 채널, stale docstring B+C, session-ingest 정합, audit 신설, bb2 스킬
드리프트·줄번호 정정)은 **엔진 템플릿과 bb2 미러를 손으로 나란히 맞춰** 일관된다. 안 끝난 건
*자동 전파 메커니즘*이지 현재 내용 정합성이 아니다. bb2가 엔진보다 앞선 divergence는 원래
정상(메모리 `evidenceref-locator-unread-and-cleanup-decision` 기록: "bb2가 앞서 있고 divergence
정상, 엔진 템플릿은 거기서 distill"). 즉 **이 작업은 정확성이 아니라 편의·아키텍처 개선**이고,
착수 트리거는 "수동 dual-edit이 실제로 아플 때"다.

## 권장

급하지 않다(드리프트 없음). 방향상 1번이 사용자 의사와 맞으나 재설계+clobber 위험이 있으니,
**착수하면 위 절대순서를 반드시 지킨다.** 당장 안 해도 손해 없고, 수동 동기화가 번거로워지는
시점(스킬을 자주 고치게 될 때)이 자연스러운 착수 신호.

## 참고 — 이번 세션(2026-06-29) 산출

- **엔진 커밋**(브랜치 `fix/audit-remediation-p1`): advisories 복구, stale docstring B+C,
  session-ingest 정합, audit 서브커맨드+템플릿+installer 4종, checkup→audit rename, ROADMAP.
- **bb2 커밋**(브랜치 `docs/bb2-brain-object-model`, 전부 path-limited): Insight 승격, backlog 정비,
  스킬 드리프트 정합, 줄번호 제거, bb2-brain-audit 스킬, 06-12·13 졸업.
- **메모리:** `stale-automation-step12-implemented`(audit이 stale 캐시 도는 주체),
  `evidenceref-locator-unread-and-cleanup-decision`(줄번호 문서 정합 완료·데이터 마이그레이션만 보류).
- **관련 코드:** `installer.py`(install/`_TEMPLATES`), `cli.py`(`_run_audit`),
  `templates/audit.md`, bb2 `.agents/skills/bb2-brain-*`(원본)·`.claude/skills`(심볼릭).
