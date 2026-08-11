# FINAL 전체 변경 리뷰 — agents-doctor 글로벌 스킬 미러 검사

리뷰어: Senior Code Reviewer (독립 재검증 — 라이브 파일시스템 읽기 전용 확인 + 돌연변이 테스트)
일시: 2026-07-28
대상 계획: `docs/superpowers/plans/2026-07-28-agents-doctor-global-skill-mirror.md`

## Verdict (판정)

**ACCEPT** — 6개 완료 기준 전부 충족, 네 태스크가 서로 어긋나는 곳 없음, 미룬 minor 중
지금 반드시 고쳐야 하는 것 없음.

계획한 기능이 빠진 곳도, 계획 밖 변경이 몰래 들어간 곳도 없다. 새 검사는 정상적인 사용자
환경에서 doctor를 깨뜨리지 않는다(손으로 망가뜨린 `settings.json` 한 경우만 traceback —
아래 Minor 1번). 미룬 항목 9건은 전부 defer 가능하며, 그중 하나(enabledPlugins 타입 방어)를
다음에 이 파일을 손볼 때 같이 넣기를 권한다.

## Plan Criteria (완료 기준 6개)

1. **`test_doctor.py` 19 passed, 0 failed** — 충족. 직접 실행: `19 passed, 0 failed`,
   종료 코드 0. 기존 17개 전부 PASS + 신규 2개 PASS.
2. **`doctor.py --root ~/.agents` → ✅ exit 0** — 충족. 직접 실행:
   `✅ agents-doctor: /Users/al03040455/.agents 정합성 이상 없음`, `GLOBAL_EXIT=0`.
   "구현 직후 WARN 9건" 선행 증거는 정리가 끝난 지금 재관찰이 불가능하지만, 사후 산술이
   정확히 맞는다(미러 없던 3개 + 실물 사본 6개 = 9). Task 2 리뷰가 독립 재현으로 기록.
3. **허브 스킬 전수 WARN 0** — 실질 충족. 직접 조사: 허브 디렉토리 31개, 그중 최상위
   `SKILL.md` 보유 30개. 30개 = 심링크 미러 23개(기존 15 + 교체 6 + 신규 2) + 플러그인
   면제 7개. `superpowers`만 최상위 `SKILL.md`가 없어 검사 대상 외. WARN 0을 전수 재계산으로
   확인. **다만 계획서의 내역 표기가 하나 틀렸다**: "기존 심링크 미러(14)"인데 실제는 15개다
   (`orchestration` 18:09, `x-bookmarks` 19:05 — 둘 다 계획서 작성 시각 20:12보다 앞선 선행
   작업물). 그래서 합계도 30이 아니라 31개 디렉토리다. 기능 누락이 아니라 계획서 요약의
   산술 오차이고, 검증해야 할 결과(WARN 0)는 그대로 충족.
4. **`~/.claude/skills`에 허브 스킬 실물 사본 0개** — 충족. `find -type d -maxdepth 1`로
   남은 실물 디렉토리는 `_vendor` 하나뿐이고, 이건 허브 스킬 이름이 아니며(허브에 `_vendor`
   없음) 내용물은 5월 22일자 `mattpocock-skills.bak.20260522` 백업이라 최상위 `SKILL.md`도
   없다 — 새 검사의 대상 밖.
5. **`.skill-lock.json` skills = computer-use, orca-cli, orchestration** — 충족.
   `jq -r '.skills | keys'` 결과가 정확히 그 3개. `dismissed.findSkillsPrompt`는 남아 있는데
   이건 스킬 항목이 아니라 설치 도구 자체의 상태라 맞는 처리다.
6. **SKILL.md가 검사 4개 기재** — 충족. `SKILL.md:61-67`에 글로벌 항목 4번으로 추가됨.

## Cross-Task Consistency (태스크 간 일치)

**일치.** 네 층이 서로 어긋나는 곳을 못 찾았다. 구체적으로 맞춰본 지점들:

- 테스트가 검사하는 문구 `"미러"`(test_doctor.py 신규 케이스)가 구현이 내는 메시지
  `"global skill '...' 의 claude 미러 심링크 없음"`(doctor.py:359)과 맞는다.
- Task 1이 fixture에 넣은 demo 미러가 Task 2 검사의 전제와 맞아서 `case_global_root_healthy`가
  계속 초록이다(19개 전부 통과로 확인).
- 문서가 주장하는 세 가지 — "SKILL.md 보유" 필터, 플러그인 면제, codex 미검사 — 가 코드
  `doctor.py:344-360`과 하나씩 대응한다. 문서의 "켜진 Claude 플러그인"도 코드의
  `enabled is not True`(명시적 `false`는 면제 안 줌)와 뜻이 같다.
- Task 3 실환경이 Task 2 검사를 실제로 통과한다(직접 실행 exit 0). 교체된 미러 6개의
  `readlink -f`가 모두 허브를 가리키고, `settings.json`은 손대지 않았다(mtime 18:31 <
  Task 3 작업 시각 20:31).
- Task 3의 "미러+on" 의도가 실제 설정과 맞는다: `skillOverrides`에 `slides-grab` 계열 5개만
  `off`이고 `pkm-vault`·`computer-use`·`diagnosing-bugs`는 목록에 없어서 켜진 상태다.
  `diagnosing-bugs`는 frontmatter `disable-model-invocation: true`가 실제로 확인돼서 "모델
  목록 비용 0"이라는 판정 근거도 맞다.

## Deferred Minors Triage (미룬 항목 판정)

Task 1

1. **면제 가드가 Task 2 전까지 무신호** — **OK TO DEFER.** 이제 신호가 있음을 직접 확인했다.
   돌연변이 A(면제 로직을 `provided = set()`으로 무력화)를 넣으면
   `case_global_plugin_provided_skill_exempt`가 실패한다 — 헛도는 테스트가 아니다.
2. **꺼진 플러그인(false) 면제 거부 테스트 없음** — **OK TO DEFER.** 돌연변이 B로 확인한 결과
   `enabled is not True` 줄을 없애도 19개가 다 통과한다(정말 미커버). 다만 실환경에서 꺼진
   플러그인 4개(clangd-lsp, claude-code-setup, document-skills, serena)의 캐시 스킬 이름이
   허브 스킬 이름과 하나도 겹치지 않아서, 이 분기는 지금 동작에 영향이 없다. 틀리는 방향도
   "면제를 잘못 줘서 WARN을 놓침"이라 위험이 낮다.
3. **가드가 부정 assert 단독 의존** — **OK TO DEFER.** 같은 fixture로 도는 빨간 케이스가
   상쇄 역할을 하고, 1번의 돌연변이 검증으로 실효성이 확인됐다.

Task 2

4. **`enabledPlugins`가 dict 아닌 타입이면 traceback** — **OK TO DEFER**(단, 다음 수정 때 같이
   넣기를 권함). 실측: 값이 list/str/int면 `AttributeError: ... has no attribute 'items'`로
   죽는다. 하지만 실제 `~/.claude/settings.json`의 `enabledPlugins`는 Claude Code가 쓰는
   객체(항목 10개)라서 손으로 망가뜨려야 닿는 경로이고, 같은 스타일의 무방비 `.get`이
   기존 코드에도 이미 있다(`doctor.py:246` `payload.get("ok")`). `null`·최상위 list·파일 없음·
   깨진 JSON은 모두 정상 처리됨을 확인했다.
5. **면제가 캐시 전 버전 이름의 합집합** — **OK TO DEFER.** 실측으로 무해함이 확인됐다:
   superpowers 캐시에 6.1.1과 6.2.0 두 버전이 있는데 스킬 이름 집합이 완전히 동일해서
   (6.1.1에만 있는 이름 0개) 합집합이 만드는 차이가 오늘 데이터에는 없다. 계획서가 YAGNI로
   명시 기록한 절충이기도 하다.
6. **꺼진 플러그인 분기·SKILL.md 스킵 미테스트** — **OK TO DEFER.** 돌연변이 C로
   `SKILL.md` 필터를 제거해도 19개가 통과한다(미커버 확인). 하지만 이 필터가 깨지면 결과는
   `superpowers` 디렉토리 링크에 대한 WARN 1건 — 소음이고, doctor를 한 번 돌리면 바로 드러난다.

Task 3

7. **pkm-vault는 사본이 아니라 "절대경로 심링크를 담은 실물 디렉토리"였음** — **OK TO DEFER.**
   교체 정당성에 영향 없고(어느 쪽이든 미러 심링크가 아니라 WARN 대상), 데이터 손실도 없음을
   확인했다 — 백업 6개 전부 `diff -r` 결과 현재 심링크 대상과 내용 동일.
8. **lock 파일 끝 개행 추가 / 무수정 증거가 mtime뿐 / 패키지 9개 표기 중 orchestration은 선행
   산출물** — **OK TO DEFER.** 개행은 jq 부수효과로 무해(`jq empty` 통과, 키 3개 확인). 선행
   산출물 표기는 완료 기준 3번의 산술 오차와 같은 뿌리이고 위에서 정정했다.

Task 4

9. **SKILL.md "결과 읽기"의 INFO 설명이 프로젝트 모드 전용임 미표기 / 면제가 플러그인 캐시
   실물 존재에 의존한다는 뉘앙스 미기재** — **OK TO DEFER.** INFO 문구는 이번 변경이 만든 게
   아닌 기존 서술이고, 경로를 `~` 없이 `.claude/skills`로 써서 이미 프로젝트 기준으로 읽힌다.
   캐시 의존은 틀리는 방향이 "면제를 못 줘서 WARN이 뜬다"는 눈에 보이는 실패라 조용히 넘어가지
   않는다.

## New Findings (새로 찾은 것)

Critical: 없음.

Important: 없음.

Minor

1. **`plugin_skill_names`의 타입 방어가 반만 되어 있다** (`doctor.py:327-333`).
   바깥 `settings`는 `isinstance(..., dict)`로 막았는데 안쪽 `enabledPlugins`는 안 막았다.
   임시 홈으로 실측한 결과 `{"enabledPlugins": ["a@b"]}` 같은 값이면 진단 메시지 없이
   `AttributeError`로 죽는다. 설정 검사 도구가 망가진 설정을 만나 보고 대신 죽는 건 방향이
   반대라, 다음에 이 파일을 열 때 한 줄 고치기를 권한다:
   `plugins = settings.get("enabledPlugins"); if not isinstance(plugins, dict): return set()`.
   지금 당장 막을 이유는 아니다 — 실제 파일은 Claude Code가 쓰는 객체다.
2. **글로벌 모드가 `~/.claude/settings.json`을 이제 파싱하면서 새 부수 신호가 생겼다.**
   그 파일의 JSON이 깨져 있으면 글로벌 doctor가 `❌ JSON 파싱 실패`를 낸다(실측). 미러 검사와는
   다른 주제의 ERROR지만, 그 상태면 Claude Code 자체가 설정을 못 읽으므로 알려주는 게 맞다고
   본다. 문서화까지 할 필요는 없어 보이고, 기록만 남긴다.
3. **면제 규칙이 "허브와 플러그인 본문이 갈라진 상태"를 조용히 승인한다.** 면제된 허브 스킬
   7개 전부 플러그인 6.2.0 본문과 다르다(`brainstorming` 25줄, `subagent-driven-development`
   532줄 차이 등 — `diff` 실측). 허브 쪽은 `~/.codex/superpowers/skills/...`로 가는 심링크라
   Codex는 벤더된 옛 본문을, Claude는 플러그인 최신 본문을 본다. 미러 문제로는 면제가 옳은
   판단이지만(미러를 만들면 Claude에 같은 이름이 둘), doctor의 ✅는 "미러 불필요"라는 뜻일
   뿐 "두 도구가 같은 걸 본다"는 뜻이 아니다. 이번 계획 범위가 아니고 기각 이유도 아니지만,
   면제가 남기는 잔여 위험으로 기록해 둔다.
4. **Codex 쪽에 같은 종류의 중복 사본이 하나 남아 있다.** `~/.codex/skills/pkm-vault`가 심링크가
   아닌 실물 디렉토리이고 허브 원본과 내용이 같다(`diff -r` 무출력). Codex가 허브를 네이티브
   스캔하므로 이건 이번에 Claude 쪽에서 정리한 것과 똑같은 "언젠가 갈라질 사본"이다. 계획이
   codex 미러 검사를 의도적으로 제외했으니 지금 손댈 일은 아니고, 후속 정리 후보로 남긴다.

## 검증 재현 로그 (리뷰어가 직접 돌린 것)

- `python3 ~/.agents/skills/agents-doctor/scripts/test_doctor.py` → 19 passed, 0 failed
- `doctor.py --root ~/.agents` → ✅, EXIT=0
- `doctor.py --root <project-brain>` → ✅ (프로젝트 모드 무변화)
- 허브 전수 재계산(파이썬으로 `plugin_skill_names`·`symlink_targets` 직접 호출):
  미러 23 / 면제 7(7개 모두 `plugin-exempt=True`) / `superpowers` 스킵
- 돌연변이 3종: A(면제 무력화)→exempt 케이스 FAIL / B(`enabled is not True` 제거)→19 통과 /
  C(SKILL.md 필터 제거)→19 통과
- 망가진 설정 10종 주입(list/str/int/null/최상위 list/깨진 JSON/파일 없음/캐시 없음/false/`@` 없음)
  → traceback은 list·str·int 3종에서만
- 백업 대비 `diff -r` 6건 전부 동일 / `~/.claude/skills`·`~/.codex/skills`·`~/.agents/skills`에
  깨진 심링크 0 / `find-skills` 잔여 참조 0
