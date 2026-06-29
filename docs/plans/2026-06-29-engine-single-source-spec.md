# 엔진 단일 관리 주체 — 구현 설계 spec

> **목적:** [배포모델 결정 문서](2026-06-29-engine-single-source-decision.md)의 후속. 그 문서는
> "1번(installer 디렉토리 통째 주입) vs 2번 vs 3번" 중 사용자가 1번에 기운 데까지였다.
> 이 세션(2026-06-29)에서 **1번 확정 + 실제 코드 전수 조사 + 상세 설계**까지 마쳤고, 이 문서가
> 그 결과다. 다음 세션은 이 문서만 읽고 구현 plan을 짤 수 있다.
>
> **이 문서가 결정 문서를 갱신하는 지점:** 결정 문서는 1번을 "재설계 수준, 도메인 예시 일반화
> 필요"로 봤으나, 조사 결과 그 전제가 틀렸다(아래 §2). 1번은 "범용화"가 아니라 "관리 주체 옮기기"
> 라서 훨씬 가볍다.

## 1. 목표 — "관리 주체 1곳", 범용화 아님

엔진이 brain 스킬의 **단일 관리 주체**가 된다. 모든 편집과 git 히스토리가 엔진 레포에서
일어나고, 소비 프로젝트(bb2)의 `.agents/skills/<project>-brain-*`는 `install`이 찍어내는
**생성물**이 된다. 착수 후 규율: **bb2에서 스킬 직접수정 금지**(엔진에서 고친다).

**범용화(추상화)는 목표가 아니다.** 전파 대상이 bb2 하나뿐이라, 도메인 예시를 일반 예시로
바꾸거나 `{{EXAMPLE_*}}` 변수로 빼는 작업은 하지 않는다. 예시 문구가 bb2색(게임 도메인)이어도
무방하다 — 고칠 일이 생기면 엔진에서 고친다. 변수 치환은 "목표"가 아니라 install이 스킬을
찍어내는 데 필요한 **최소 수단**일 뿐이다.

동기: 지금 엔진 templates와 bb2 `.agents/skills`를 **둘 다 손으로 고치는 이중 편집**이 관리
부담이 됐다. 손편집을 엔진 한 곳으로 모으는 게 핵심이다.

## 2. 조사로 확정된 사실 (2026-06-29, 추측 아님 — 전수 코드/그래프 확인)

bb2 brain 스킬 4종(query·ingest·session-ingest·audit) 전 파일을 읽고 확정했다.

- **scripts 실행 코드 4종은 전부 제네릭.** 게임/도메인 종속이 **0**이다.
  - `assemble_notes.py`: verify 출력(list 또는 `{groups}`) → build 노트 제네릭 조립기.
    bb2 종속은 `spec.get("REPO", "bb2_client")` 기본값 2곳뿐.
  - `run_ingest.sh`: `project-brain` CLI 러너. bb2/게임 종속 0.
  - `extract_template.js`: extract→verify 골격(빈 `GROUPS` 슬롯). bb2/게임 종속 0.
  - `domain_spec.template.py`: 빈 데이터 템플릿. bb2 종속은 `REPO = "bb2_client"` 1곳뿐.
  - `ball-select`·`main-map`은 전부 `# 근거:` 주석(역사 기록)이거나 문서의 예시 언급일 뿐,
    실행 코드가 fixtures를 import/읽지 않는다.
- **게임색(샐리 카누·볼셀렉·버블 등)은 "예시 문구"와 "fixtures 데이터"에만 있다.** 스킬이
  돌아가는 코드에는 없다. 즉 "게임 용어가 있다 ≠ bb2 종속".
- **fixtures는 죽은 산출물.** `scripts/fixtures/ball-select.*`·`main-map.*`는 과거 적재
  (ball-select 2026-06-26, main-map 2026-06-25)에서 나온 verify 표본·파생 domain_spec이다.
  그걸 **근거 삼아** `assemble_notes.py`를 제네릭으로 공통화한 뒤, 지금은 어떤 코드도 참조하지
  않는다(git: 커밋 `7eb7a8477d`).
- **실제 bb2 종속 리터럴 인벤토리** (변수화 대상):
  - `develop` (DEFAULT_BRANCH): ingest SKILL 15 · audit 4 · session 4 · dev-ingest 2 · session-extract 2
  - `bb2_client` (REPO): assemble_notes 2 · domain_spec.template 1 · test_assemble_notes 2
  - `BB2`/`bb2`/`LineBubble2` (PROJECT): 다수 — 이미 일부는 `{{PROJECT}}`로 치환돼 있음
- **엔진 베이스가 bb2보다 뒤처진 곳** (역수입 시 발전분 흡수):
  - `ingest`: 엔진 164줄 vs bb2 363줄 + references 7개(엔진에 없음).
  - `session-ingest`: bb2가 references 3개로 분산 + Insight kind(2026-06-15 신설) + 가드 정교화.
  - `query`·`audit`: 거의 동일(audit은 52줄 완전 일치, 변수치환만).

## 3. 설계

### 3.1 installer를 디렉토리 walk로 확장

현재 `install()`(`src/project_brain/installer.py`)은 스킬당 `SKILL.md` **한 파일만** 렌더·기록한다.
이를 **스킬 디렉토리 전체**(SKILL.md + references/ + scripts/)를 walk하며 렌더·복사하도록 키운다.

- **확장자별 치환 분기:** `.md`/`.py`/`.js`/`.sh`/`.json` 파일에서 `{{VAR}}` 치환. 그 외는 바이트 복사.
  render는 맹목 `str.replace`(installer.py:36)다 — 부분문자열 충돌을 막으려면 **긴 리터럴부터**
  치환한다(`{{REPO}}`(bb2_client) → `{{PROJECT}}`(bb2) 순). `bb2`가 `bb2_client`의 부분문자열이라
  순서를 어기면 `bb2_client`가 `{{PROJECT}}_client`로 깨진다. 안전은 순서로 보장하지, 렌더러가
  보장하지 않는다 — "문법 안전"은 단언하지 않는다(§7 날선 모서리).
- **제외 필터 — install 미주입.** 원칙: **스킬 런타임에 참조되지 않는 개발용 자산은 프로젝트에 안 보낸다.**
  - `test_*.py` — 개발 테스트. 참조 grep으로 확인: `test_assemble_notes.py`는 SKILL.md·references·
    다른 scripts 어디서도 안 가리키는 **유일한 고아**(나머지 references·scripts 실행코드는 전부
    런타임 참조됨). 엔진 레포엔 보관해 검증하되, install walk는 건너뛴다(§3.5).
  - `fixtures/` — 죽은 산출물(§4에서 bb2에서도 삭제).
  - `__pycache__/`·`*.pyc` — 생성물.
- **manifest 키:** 현재처럼 target 기준 상대 경로. 디렉토리 walk라 키가 파일별로 여러 개가 된다.

### 3.2 변수 인벤토리

| 변수 | 치환값(bb2) | 상태 |
|------|-----------|------|
| `{{PROJECT}}` | `bb2` | 기존 |
| `{{BRAIN_ROOT}}` | `brain` | 기존 |
| `{{DEFAULT_BRANCH}}` | `develop` | **신규(필수)** |
| `{{REPO}}` | `bb2_client` | **신규(필수)** |

- `{{DEFAULT_BRANCH}}`·`{{REPO}}`는 config(`.project-brain.json`)에 새 키로 추가하고, install이 읽어 치환한다.
- **변수화하지 않는 것:** 도메인 예시 문구(샐리 카누 등) — 그대로 둠(§1).
- **치환하지 않고 리터럴로 두는 것:** `BB2`(대문자, 주입 SKILL.md에 ~6곳)·`LineBubble2`(~2곳) —
  프로젝트 표시명(도메인 문자열)이라 §1 "범용화 안 함"에 해당, 예시 문구와 같은 부류로 그대로 둔다.
  소문자 `bb2`만 `{{PROJECT}}`로 치환되고 대소문자·부분문자열이 달라 `BB2`·`LineBubble2`는 치환
  규칙에 자동으로 안 걸린다. (잘못 통합하면 디스크는 `LineBubble2`인데 렌더는 `bb2`가 돼 §6.3 diff가
  즉시 잡는다.) 미래 프로젝트 #2의 표시명 변수화는 §7.
- **변수 불필요:** `project-brain` 명령명은 글로벌 도구라 프로젝트 무관 고정.

### 3.3 레이아웃 — `.agents/skills/`에 쓴다

현재 installer는 `.claude/skills/`에 직접 쓴다. 그러나 bb2는 `.agents/skills/<project>-brain-*`가
**원본**이고 `.claude/skills/*`는 그 심볼릭 미러다. install이 `.agents/skills/`에 쓰도록 바꾼다.
`.claude/skills` 심볼릭은 bb2가 이미 갖고 있어 install이 만들 필요 없다(없으면 생성하는 보강은
구현 시 판단). **범용 레이아웃 추상화는 하지 않는다** — bb2 실제 구조에 맞춘다.

### 3.4 덮어쓰기·채택 — `cli install`에 `--force` 추가

엔진이 소스이므로, install이 manifest 추적 파일을 **강제 갱신**할 수 있어야 한다(현재는 해시
불일치=사용자수정으로 보고 무조건 skip). `--force`는 **manifest에 기록된 파일만** 덮는다.
manifest 밖 파일(사용자 소유)은 `--force`여도 보존한다 — 안전판 유지.

**최초 채택(adopt) 문제 — 이게 "manifest 채우기"의 정체:** bb2의 기존 `.agents/skills/bb2-brain-*`는
빈 manifest 밖이라, 현재 로직으론 `--force`를 줘도 "사용자 소유"로 영원히 skip된다 — 엔진이
덮을 길이 없다. 해결: 역수입(§5 step3)을 정확히 하면 **bb2 디스크 내용 == 엔진 렌더 결과**가
되므로, install이 '디스크 해시 == 렌더 해시'인 파일을 manifest에 **채택**(도구 소유로 등록)하게
한다. 그 뒤부터 엔진 수정분은 `--force`로 갱신한다. 즉 "manifest 채우기"는 수동 작업이 아니라
**정확한 역수입의 자동 결과**다. 내용이 다른 파일은 채택하지 않는다 — 역수입 누락 신호이므로
멈춰서 확인한다. (이는 결정 문서 §"착수 위험"의 "채우는 순간 안전판이 사라진다 → 그래서 역수입
완료 후에만 채운다"와 정확히 일치한다.)

### 3.5 가져오는 자산 (역수입 대상)

원칙: **스킬 런타임에 참조되는 자산만 install 주입.** 참조 grep으로 확정(고아 = `test_*.py`뿐).

**엔진 보관 + install 주입** (런타임 참조 자산):
- SKILL.md 4종
- `ingest/references/` 8개: scope·object-model·ingest-tools·worked-example·system-domain-playbook·
  completeness-checklist·judgment·**ingest-case-log**(다음 적재가 읽는 살아있는 교훈, §4)
- `session-ingest/references/` 3개: dev-ingest·session-extract·update-rules
- `ingest/scripts/` 실행 4종: assemble_notes.py·run_ingest.sh·extract_template.js·domain_spec.template.py

**엔진 보관 + install 미주입** (개발 자산 — §3.1 제외 필터):
- `ingest/scripts/test_assemble_notes.py` — `assemble_notes.py` 검증용. 엔진 레포에서 돌리되 bb2엔
  안 보낸다. fixtures를 안 읽고 인라인 데이터로 테스트하므로 fixtures 삭제와 무관.

**삭제** (죽은 산출물): `fixtures/`·생성물 (§4).

엔진 `templates/`에 `<skill>/references/`·`<skill>/scripts/` 하위 디렉토리를 신설한다(현재 없음).

## 4. 죽은 산출물 삭제 + orphan 정리 (bb2 레포)

데이터(fixtures)는 삭제, 교훈(case-log)은 보존.

**삭제:**
- `scripts/fixtures/ball-select.domain_spec.py` · `ball-select.verify.json`
- `scripts/fixtures/main-map.domain_spec.py` · `main-map.verify.json`
- `scripts/__pycache__/` · `scripts/fixtures/__pycache__/`
- → 비게 되는 `scripts/fixtures/` 디렉토리

**삭제가 깨뜨리는 것 → 같이 정리(orphan 참조):**
- `references/ingest-tools.md:189` — fixtures 파일을 **경로로 직접 가리키는 유일한 줄**
  (`채운 예: scripts/fixtures/ball-select.domain_spec.py(14결정·{groups}형), main-map...`).
  삭제하면 죽은 링크가 되므로 경로 없는 설명(형태 예시)으로 정리.

**삭제 아님(살아있음 → §3.5로 가져감):**
- `references/ingest-case-log.md` — fixtures 데이터(죽음)와 달리 "그 적재에서 무슨 변칙을 봤고
  어떻게 처리했나"의 교훈. fixtures 경로를 안 가리키고 "다음 적재는 여기를 읽고 일반화"한다.
- `references/worked-example.md` — 사용법 예시.
- `assemble_notes.py`·`extract_template.js`의 `# 근거: ball-select·main-map` 주석 — 역사 근거.

## 5. 착수 절대순서 (엄수)

순서를 어기면 엔진의 (짧은) 베이스가 bb2의 (풍부한) 발전분을 덮어 소실시킨다.

1. **installer를 디렉토리 walk로 확장** (§3.1·3.3·3.4). `templates/`에 references/·scripts/ 신설.
   `--force` 추가. config에 `default_branch`·`repo` 키 추가. → verify: 합성 테스트(아래 §6).
2. **bb2 죽은 산출물 삭제 + orphan 정리** (§4). → verify: bb2 스킬에서 fixtures 참조 grep 0건.
3. **bb2 정합본 역수입** — bb2 스킬 전체(제외분 빼고)를 엔진 `templates/`로 옮기며 §3.2 변수화.
   **긴 리터럴부터 치환**(bb2_client→{{REPO}} 먼저, 그다음 bb2→{{PROJECT}}; §3.1). 도메인 예시
   문구는 그대로. → verify: `bb2_client`/`develop` 리터럴 0건이면서 **동시에 `{{REPO}}`·
   `{{DEFAULT_BRANCH}}`가 실제로 등장**해야 한다(리터럴 0건만 보면 잘못 치환돼도 통과 — §6.1).
   추가로 §6.2 파일 집합 동등성.
4. **엔진 머지 — "bb2가 길다 ≠ 이번 세션 편집의 상위집합".** step3이 엔진 templates를 bb2 내용으로
   덮으므로 발전분 후퇴 위험이 있다. **기계적 백스톱(주 안전판):** step3 직전 엔진 `templates/`를
   백업하고 직후와 diff해 **"엔진에만 있던 줄(삭제분)"을 전수 검토**한다 — 나열 리스트에 없는
   스킬문서 변경까지 잡는다(리스트가 불완전해도 안전). **체크리스트(병행):** 이번 세션 정합 항목 중
   templates 텍스트에 영향 있는 것(줄번호 제거·audit 신설 등)이 bb2 디스크에 이미 반영됐는지 대조
   (UTC Z→KST·graph isolated B+C·advisories 채널은 주로 `src/` 코드라 templates를 안 건드림 → 후퇴
   위험 없음). 후퇴분은 되돌려 보강. (메모리: 줄번호 제거는 bb2가 2026-06-28 재정정.)
5. **역수입 완료 확인 후에만** `install` 실행 — 디스크 내용이 엔진 렌더와 일치하는 파일을 manifest에
   자동 채택(§3.4). 불일치 파일이 나오면 역수입 누락이니 멈춰서 확인. 채택 후 엔진 수정분은
   `--force`로 갱신. → verify: §6 bb2 회귀.
6. 이후 규율: **bb2 직접수정 금지**.

## 6. 성공 기준 (verify)

critic 지적 반영: **diff-0 단독은 검증이 못 된다.** 템플릿은 디스크를 거꾸로 치환해 만든 것이라
어떤 치환을 해도 render하면 바이트가 디스크로 되돌아온다(왕복 항등성) — 잘못된 치환·파일 누락도
diff 0을 통과한다. 그래서 세 게이트를 **함께** 본다.

### 6.1 치환 정확성 — 합성값 렌더 스모크 (엔진 합성 테스트)
`tests/test_installer.py`에서 `PROJECT=zzz`·`REPO=qqq`·`DEFAULT_BRANCH=ttt` 같은 **합성값**으로
렌더해 배선을 확인한다. 왕복 항등성을 깨는 진짜 검증이다 — `{{REPO}}`가 실제로 배선됐다면 결과에
`qqq`가 나타나야 하고, 잘못해서 `bb2_client`가 `{{PROJECT}}_client`로 깨졌다면 `zzz_client`가 나와
잡힌다. diff-0(6.3)만으론 이 오류가 안 잡힌다.

### 6.2 파일 집합 동등성 (역수입 완전성)
`{엔진 템플릿을 타깃 경로로 렌더한 파일 집합} == {bb2 스킬 파일 − 제외분(test_*.py·fixtures·생성물)}`.
역수입이 파일을 통째 빠뜨리면 install이 그 파일을 안 건드려 diff 0이지만, 그 파일은 manifest 미등록
("사용자 소유")이라 엔진이 영영 못 고쳐 **이중편집 드리프트가 부활**한다(critic 2번). 집합 비교로 막는다.

### 6.3 내용 후퇴 없음 — diff (보조)
`install`로 bb2 재생성(채택/`--force`) 후 **역수입 직전 bb2 원본과 diff**. 6.1·6.2를 통과한 상태에서
diff 0이면 "치환이 원래 값으로 정확히 복원 + 내용 후퇴 없음"을 뜻한다. **diff 0을 단독 합격 기준으로
쓰지 않는다** — 6.1·6.2의 보조다.

### 6.4 합성·실측 회귀
- 엔진: `tests/test_installer.py` — walk 주입·제외 필터(test_*.py·fixtures·pyc)·`--force`(manifest
  파일만)·멱등·채택. red→green. `.venv/bin/python -m pytest tests/ -q` 통과.
- bb2: `python3 -m unittest discover -s brain/checks -p "test_*.py"` 통과. 색인·라우터 무영향이라
  eval/index rebuild 불요(스킬 문서만 바뀜).

## 7. 미결 / 미래 (이번 범위 아님)

- **맹목 `str.replace`의 날선 모서리** — render(installer.py:36)는 부분문자열을 가리지 않는다. 지금은
  §3.1의 "긴 것부터 치환" 규칙 + bb2 값들이 안 부딪혀서 안전하지만, **프로젝트 #2**에서 치환값이
  다른 키워드의 부분문자열이면 맹목치환 지뢰가 된다. 그때 토큰 경계 치환·명시적 플레이스홀더 형식으로
  강화한다. "문법 안전"을 무조건 단언하지 않고 알려진 한계로 남긴다.
- **도메인 예시 범용화** — 두 번째 소비 프로젝트가 생길 때. 그때 예시를 일반 예시/플레이스홀더로.
  지금은 YAGNI(목표가 "관리 1곳"이지 "범용 배포물"이 아님).
- **`.claude/skills` 심볼릭 자동 생성** — bb2는 이미 가짐. 새 프로젝트에 깔 때 필요해지면 그때.

## 8. 참고 — 이번 세션 산출 위치

- 코드 사실 검증: `installer.py`(`install`/`_TEMPLATES`/`render_template`), `cli.py`(`_run_install`
  537~·`--force` 없음 확인), `tests/test_installer.py`(117줄·5테스트), bb2
  `.agents/skills/bb2-brain-*`(원본)·`.claude/skills`(심볼릭).
- 조사 워크플로: bb2 스킬 4종 전수 분류(공통/변수화/자유서술/제외) + 하드코딩 인벤토리.
