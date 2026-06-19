# project-brain

프로젝트 도메인 지식 brain 엔진 — 검수 상태·근거가 붙은 객체 코퍼스 + 한국어
하이브리드 검색(FTS5 BM25 + bge-m3 벡터 + RRF 융합 + 그래프 상호지지 재정렬) +
회상 CLI.

한 프로젝트의 내부 도구로 개발되다 2026-06에 범용 엔진으로 분리됐다.

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
project-brain install --project <이름>   # config + 회상/적재 스킬 주입(manifest 추적)
project-brain doctor                      # 환경·프로젝트 상태 진단
project-brain bootstrap                   # install → 색인 재구축 → doctor 한번에
```

`install`은 `.claude/skills/<이름>-brain-recall|ingest/SKILL.md`를 범용 템플릿에서
렌더해 심는다. 설치 직후 어시스턴트(Claude 등)가 코퍼스를 보고 description 트리거
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
project-brain doctor [--download]        # 진단
```

## 개발

```bash
uv sync --extra mecab
.venv/bin/python -m pytest tests/ -q     # 합성 데이터만 — 실코퍼스 불필요
```
