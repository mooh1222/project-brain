# project-brain

프로젝트 도메인 지식 brain 엔진 — 검수 상태·근거가 붙은 객체 코퍼스 + 한국어
하이브리드 검색(FTS5 BM25 + bge-m3 벡터 + RRF 융합 + 그래프 상호지지 재정렬) +
조회 CLI.

한 프로젝트의 내부 도구로 개발되다 2026-06에 범용 엔진으로 분리됐다.

색인·임베딩·검색의 코드 기준 동작은 [docs/search-internals.md](docs/search-internals.md),
설계 근거는 [docs/design-canonical.md](docs/design-canonical.md), 발전 단계·히스토리는
[ROADMAP.md](ROADMAP.md)를 본다.

## 2-레포 모델: 엔진 / 데이터

- **엔진(이 레포)**: 스키마·적재(ingest/promote)·lint·색인·검색·라우터·평가 하네스.
  합성 데이터 테스트만 갖는다.
- **데이터(각 프로젝트 레포)**: `brain/` 코퍼스(객체 JSON + raw 원문) +
  골든셋(`eval_scenarios.json`) + 실코퍼스 가드. 프로젝트 git이 추적한다.

엔진은 글로벌 도구로 한 번 설치하고, 프로젝트 쪽은 `.project-brain.json` config가
경로를 해석한다(명시 플래그 > config > 에러).

## 설치

전제는 [uv](https://docs.astral.sh/uv/) 하나다.

```bash
git clone <this-repo> project-brain
uv tool install -e ./project-brain
```

편집 설치(-e)라 엔진 수정이 모든 프로젝트에 즉시 반영된다.

- 임베딩 모델(bge-m3)은 첫 색인 때 자동 다운로드된다. 미리 받으려면
  `project-brain doctor --download`.
- 한국어 형태소: kiwipiepy가 기본 동봉. mecab-ko를 쓰려면 시스템 설치
  (`brew install mecab-ko mecab-ko-dic`) 후 `uv tool install -e <클론> --with mecab-python3`.

## 프로젝트에 붙이기

```bash
cd <프로젝트 루트>
project-brain install --project <이름>   # config + 스킬 4종(조회/적재/세션/audit) 주입(manifest 추적)
project-brain install --project <이름> --default-branch develop --repo myorg/myrepo  # 스킬의 {{DEFAULT_BRANCH}}·{{REPO}} 값 채움
project-brain install --project <이름> --force  # manifest에 기록된 사용자 수정 파일도 덮어 갱신
project-brain doctor                      # 환경·프로젝트 상태 진단
project-brain bootstrap                   # install → 색인 재구축 → doctor 한번에
```

`install`은 `.agents/skills/<이름>-brain-{query,ingest,session-ingest,audit}/` 4종을 엔진 `templates/`에서
렌더해 심는다 — SKILL.md 한 장이 아니라 `templates/<skill>/` 디렉토리 통째(SKILL.md +
references/ + scripts/ 포함)를 주입한다. 설치 직후 어시스턴트(Claude 등)가 코퍼스를 보고 description 트리거
어휘를 프로젝트 어휘로 맞춤 제안하는 단계까지가 온보딩이다 — 맞춤된 스킬 파일은
사용자 소유가 되고, 이후 `install` 재실행은 그 파일을 덮지 않는다(manifest 해시
불일치 → skip 보고).

installer의 파일 소유권 기준은 `.project-brain-manifest.json`이다.

- manifest 해시와 디스크가 일치하는 관리 파일만 자동 갱신한다. 내용이 현재 템플릿과
  같은 manifest 밖 파일은 채택(`adopted`)하고 실행 비트를 템플릿과 맞춘다.
- 템플릿에서 사라진 관리 파일은 사용자가 수정하지 않았을 때만 설치본과 manifest에서
  퇴역시킨다. 사용자 수정 파일은 충돌로 중단하고 보존한다.
- 퇴역 원본은 곧바로 지우지 않고 같은 디렉토리의 backup으로 옮긴다. 여러 파일 처리나
  manifest 확정이 실패하면 역순으로 원위치에 복원한다.
- manifest 밖의 프로젝트 전용 overlay는 `--force`에서도 덮거나 삭제하지 않는다.
  `skipped`가 있으면 먼저 diff를 확인하고, 원인을 모른 채 `--force`를 쓰지 않는다.
- 제어 파일·관리 경로의 심링크, 상위 경로 탈출, 일반 파일이 아닌 목적지는 쓰기 전에
  거부한다. 성공한 설치를 한 번 더 실행했을 때 변경 배열이 모두 비어야 한다.

## 주요 명령

```bash
project-brain search "<질문>"            # 의미 회상 (reviewed/candidate/raw 채널)
project-brain index rebuild              # 코퍼스에서 색인 전체 재구축 (파생물)
project-brain ingest --objects-file f    # 객체 묶음 적재 (스키마+lint 원자적)
project-brain promote --ids ...          # candidate → reviewed 승격 (검토 기록 동반)
project-brain eval                       # 골든셋 회귀 (실모델)
project-brain eval --check-ids           # 골든셋 기대 id 실존 가드 (모델 불필요)
project-brain show <id>                  # 객체 본문 + 1-hop 이웃(종류·제목) 펼쳐보기
project-brain doctor [--download]         # 진단
project-brain graph isolated             # 고립(아무도 안 가리킴) 잎 객체 탐지 (읽기 전용)
project-brain graph export out.html      # 코퍼스를 vis-network 인터랙티브 HTML로 시각화
project-brain lint                       # 무결성: 끊긴 참조(가리키는 대상 없음) 탐지 (읽기 전용)
project-brain stale-check                # 코드 변경 → 갱신 필요 매핑 추출 (읽기 전용). --write-cache로 query/show 노출용 캐시 떨굼
project-brain mark-checked --mappings .. # stale 해소: 의미 그대로인 매핑의 commit_sha 갱신
```

**점검·진단 4종**(모두 읽기 전용 이상 감지): `lint`(끊긴 참조=아웃바운드) · `graph isolated`(고립=인바운드) · `stale-check`(코드 변경→갱신 후보) · `doctor`(환경). `mark-checked`가 stale 해소(쓰기)다. `stale-check`은 미머지 앵커(작업 브랜치 커밋이 config의 `default_branch` 조상이 아님)를 변경과 별개로 `unmerged_anchors`에 라벨해 거짓 신호를 거른다. `--write-cache`로 떨군 캐시는 `query`/`show`가 읽어 매핑별 `stale_advisory`(코드 변경 감지)를 곁들인다. stale 자동화 설계는 [docs/plans/2026-06-25-brain-stale-automation-bc.md](docs/plans/2026-06-25-brain-stale-automation-bc.md), Step 1·2 구현 계획은 [docs/plans/2026-06-25-brain-stale-step12-impl-plan.md](docs/plans/2026-06-25-brain-stale-step12-impl-plan.md).

**코드 앵커 SHA 원칙:** 한번 만들어진 커밋 SHA는 머지해도 바뀌지 않는다. fast-forward와
일반 merge에서는 작업 브랜치 커밋이 기본 브랜치 이력에 그대로 포함되므로 기존
`commit_sha`를 유지한다. 머지 뒤 `git merge-base --is-ancestor <commit_sha> <default-branch-ref>`와
앵커 대상 코드를 대조하고, squash·rebase·cherry-pick 또는 충돌 해결로 기존 SHA가 기본
브랜치 이력에 없거나 코드가 달라진 경우에만 다시 확인한 SHA로 갱신한다.

전체 명령 목록은 `project-brain --help`, 각 명령 상세는 `project-brain <명령> --help`로 본다.

## 적재 실행 경로

installer가 주입한 `<이름>-brain-ingest` 스킬은 단건과 묶음 실행을 분리한다.

- **단건**: `scripts/run_ingest.sh <verify.json> <domain_spec.py>`가
  assemble → build → ingest → semantic finalization을 수행한다. `--dry`는 쓰지 않고
  조립·검증만 하며, `--defer-finalize`는 item ingest 뒤 멈춰 batch가 마지막 검증을
  한 번만 수행하게 한다.
- **묶음**: 먼저 `scripts/validate_workflow_result.py`로 workflow 결과를 검사하고,
  `scripts/run_ingest_batch.py <manifest> --report <report>`를 실행한다. 중단 뒤에는 같은
  report를 `--resume`으로 주면 성공한 item만 건너뛴다.
- workflow의 최상위 `completed`만으로는 성공이 아니다. `expected`와 item 수가 같고,
  각 item의 `extract_status`와 `verify_status`가 정확히 `ok`여야 한다.
- batch는 item마다 `--defer-finalize`로 적재하고, 실패가 하나라도 있으면 finalization을
  호출하지 않는다. 완료 기준은 `failed=[]`, 전체 key가 `succeeded`에 있으며
  `finalized=true`인 report다.
- manifest·verify JSON·domain spec과 같거나 심링크로 같은 위치를 가리키는 report 경로는
  입력을 덮기 전에 거부한다.

`context.key`, mapping·decision·glossary key와 연결 key는 조립 전 **logical key**만
받는다. `mapping.<context>.<key>` 같은 완성 객체 ID를 넣으면 `build` 전에 실패한다.
raw 보관은 개정본의 `spec-v<N>.md`와 이전 자료의 정리된 원본 basename을 구분하며,
파일명 충돌은 원본 묶음 기준 상대경로의 SHA-256 접미사로 해결하고 기존 바이트를 덮지 않는다.
설계와 최종 검증값은 [대량 적재 강화 완료 보고서](docs/reports/2026-07-23-bulk-ingest-hardening-completion.md)에 있다.

## 개발

```bash
uv sync --extra mecab
.venv/bin/python -m pytest -q
.venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
```

첫 명령은 엔진 합성 회귀, 두 번째는 installer가 배포하는 ingest 런타임의 독립 unittest다.
검색·청킹·색인 계약을 바꿨다면 소비 프로젝트의 `brain/checks/`, lint, eval, graph와
필요한 경우 실모델 rebuild까지 별도로 검증한다.
