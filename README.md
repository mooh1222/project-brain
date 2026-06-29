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

`install`은 `.agents/skills/<이름>-brain-{query,ingest,session-ingest,audit}/` 4종을 템플릿에서
렌더해 심는다 — SKILL.md 한 장이 아니라 `templates/<skill>/` 디렉토리 통째(SKILL.md +
references/ + scripts/ 포함)를 주입한다. 설치 직후 어시스턴트(Claude 등)가 코퍼스를 보고 description 트리거
어휘를 프로젝트 어휘로 맞춤 제안하는 단계까지가 온보딩이다 — 맞춤된 스킬 파일은
사용자 소유가 되고, 이후 `install` 재실행은 그 파일을 덮지 않는다(manifest 해시
불일치 → skip 보고).

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

**점검·진단 4종**(모두 읽기 전용 이상 감지): `lint`(끊긴 참조=아웃바운드) · `graph isolated`(고립=인바운드) · `stale-check`(코드 변경→갱신 후보) · `doctor`(환경). `mark-checked`가 stale 해소(쓰기)다. `stale-check`은 미머지 앵커(작업 브랜치 커밋이 develop 조상 아님)를 변경과 별개로 `unmerged_anchors`에 라벨해 거짓 신호를 거른다. `--write-cache`로 떨군 캐시는 `query`/`show`가 읽어 매핑별 `stale_advisory`(코드 변경 감지)를 곁들인다. stale 자동화 설계는 [docs/plans/2026-06-25-brain-stale-automation-bc.md](docs/plans/2026-06-25-brain-stale-automation-bc.md), Step 1·2 구현 계획은 [docs/plans/2026-06-25-brain-stale-step12-impl-plan.md](docs/plans/2026-06-25-brain-stale-step12-impl-plan.md).

전체 명령 목록은 `project-brain --help`, 각 명령 상세는 `project-brain <명령> --help`로 본다.

## 개발

```bash
uv sync --extra mecab
.venv/bin/python -m pytest tests/ -q     # 합성 데이터만 — 실코퍼스 불필요
```
