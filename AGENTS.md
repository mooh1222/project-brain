# AGENTS.md

이 파일은 프로젝트 지침의 canonical(단일 원본)이다.

항상 한국어로 답변한다.

## 프로젝트

프로젝트 도메인 지식 brain 엔진. 검수 상태·근거가 붙은 객체 코퍼스를 적재(ingest/
promote)하고, 한국어 하이브리드 검색(FTS5 BM25 + bge-m3 벡터 + RRF + 그래프 재정렬)
으로 회상한다. 상세는 README.md.

brain 객체의 주 소비자는 사람이 아니라 에이전트다. 사용자는 저장된 객체 파일을 직접
읽지 않고 질문하며, 에이전트가 `search` 결과에서 핵심 객체를 골라 `show`로 본문과 근거를
확인한 뒤 답한다. `query`는 변경 이유·현재·과거·근거 사슬의 결정론 계산만 맡는다.
`graph export`로 객체 관계를 시각화해 사람이 확인할 수는 있지만, 이는 점검·탐색을 위한
보조 수단이며 기본 사용 방식은 아니다.

## 2-레포 모델 — 여기는 엔진만

- **이 레포**: 엔진 코드 + 합성 데이터 테스트만. 실코퍼스(프로젝트 도메인 데이터)는 없다.
- **데이터 레포**: 소비 프로젝트의 루트 `brain/`.
  골든셋(`brain/eval_scenarios.json`)과 실측 가드(`brain/checks/`)는 그쪽 소유다.
- 엔진 설계·로드맵·발전 히스토리는 이 레포에 있다: 히스토리 허브 [ROADMAP.md](ROADMAP.md)
  (완료 단계·현황·미뤄둔 작업) + [docs/design-canonical.md](docs/design-canonical.md) +
  `docs/specs/`·`docs/plans/` + `docs/superpowers/specs/`·`docs/superpowers/plans/`.
  데이터·적재 이력만 데이터 레포(`brain/`)·vault task에 있다.

## 작업 길찾기 — 먼저 전체 지도로

- 전체 구조·데이터 흐름: [docs/architecture/README.md](docs/architecture/README.md)에서 시작해
  [runtime-map](docs/architecture/runtime-map.md)을 본다.
- 적재 객체·필드·관계·JSON 예시: [data-contracts](docs/architecture/data-contracts.md)와
  `src/project_brain/templates/ingest/references/object-templates/`를 본다.
- 검색·라우터 변경: [change-map](docs/architecture/change-map.md)의 검색 행과
  [search-internals](docs/search-internals.md)을 함께 본다.
- mutation·migration 변경: runtime map의 코퍼스 쓰기 경로와 change map의 해당 행을 본다.
- 정체성·의도·안정적인 설계 경계: [design-canonical](docs/design-canonical.md)을 본다.
- 현재 완료 상태와 미뤄둔 일: [ROADMAP](ROADMAP.md)을 본다.
- 과거 이유: 연결된 날짜 spec·plan·report를 보되, 현재 코드·테스트와 반드시 대조한다.

전체 지도는 코드보다 높은 새 정본이 아니다. 현재 동작은 현재 checkout의 코드·테스트·CLI가
기준이며, 지도와 다르면 문서 드리프트와 엔진 설계 이탈을 먼저 구분한다.

## Agent skills

### Issue tracker

이 저장소의 spec과 작업 issue는 `mooh1222/project-brain` GitHub Issues에서 관리한다.
자세한 규칙은 [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md)를 본다.

### Triage labels

issue 분류·상태 전이는 Matt triage 기본 라벨을 사용한다.
역할별 실제 라벨은 [docs/agents/triage-labels.md](docs/agents/triage-labels.md)를 본다.

### Domain docs

이 저장소는 루트 `CONTEXT.md`와 `docs/adr/`를 사용하는 single-context 구조다.
사용 규칙은 [docs/agents/domain.md](docs/agents/domain.md)를 본다.

## 개발 루프

```bash
uv sync --extra mecab
.venv/bin/python -m pytest -q
.venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
```

- 첫 테스트는 엔진 합성 회귀, 두 번째는 설치되는 ingest runtime의 unittest다. 둘 다
  통과해야 엔진 변경이 완료다.
- 글로벌 도구는 이 클론의 **편집 설치**다(`uv tool install -e . --with mecab-python3`)
  — 여기서 코드를 고치면 `project-brain` 명령에 즉시 반영된다. 재설치 불필요.
  단 pyproject 의존성이 바뀌면 `uv tool install -e . --with mecab-python3 --force`.
- TDD: red 테스트 먼저, 그다음 구현. 결정론 유지 — 테스트에서 실모델 금지
  (StubEmbedder / `PROJECT_BRAIN_EMBEDDER=stub`), 토큰화는 정규식 폴백 강제 패턴 참고.

## 엔진 수정 후 실코퍼스 회귀 (변경별)

엔진 테스트는 합성 데이터 중심이다. schema·ingest·mutation·migration·projection·검색처럼
실제 데이터에 따라 결과가 달라지는 변경은 [change-map](docs/architecture/change-map.md)의
해당 행을 기준으로 데이터 레포에서 확인한다. `brain/checks`, `lint`·`audit`, `eval`, `graph`,
`index rebuild`를 일괄 실행하지 말고 변경 축과 실제 corpus·index 영향에 맞는 것만 실행한다.
아래는 자주 쓰는 명령 예시다:

```bash
cd <소비 프로젝트 루트>
PYTHONPATH=<engine-root>/src <engine-root>/.venv/bin/python \
  -m unittest discover -s brain/checks -p "test_*.py"
PYTHONPATH=<engine-root>/src <engine-root>/.venv/bin/python \
  -m project_brain.cli index rebuild   # 색인 영향 변경 시에만
PYTHONPATH=<engine-root>/src <engine-root>/.venv/bin/python \
  -m project_brain.cli eval            # 현재 BB2 기준 15/15
```

여러 checkout이 있으면 bare `project-brain`이나 시스템 `python3`가 다른 엔진을 import할 수
있다. 검증할 checkout의 `PYTHONPATH`와 `.venv/bin/python`을 함께 명시한다. 실모델 rebuild는
비용이 크므로 change map의 조건에 해당할 때만 한 번 실행한다. 설치 대상이 아닌 문서만
바뀌면 해당 문서의 표적 검사만 돌리고 소비 데이터 회귀는 하지 않는다. 설치되는 template·
reference와 installer 변경은 installer 회귀, 설치 runtime unittest, 두 번째 설치의 무변경
확인이 기본이다. 설치 결과가 데이터·검색 계약까지 바꿀 때만 change map이 지정한 BB2 검증을
추가한다.

## 주의

- `Date`·경로 하드코딩 금지 — 경로는 config(.project-brain.json) 해석
  (`src/project_brain/config.py`, 명시 인자 > config > ConfigError).
- `context_projection.py`는 context_md와 reuse projection 빌더의 정본이다. source 의미 해시의
  단일 공식은 `hash_utils.py`가 맡고, `lint.py`의 `projection_is_fresh()`가 현재 store 기준
  freshness를 판정한다. `search_index.py`는 이 판정을 fingerprint와 색인 입력에 함께 사용한다.
- 스킬 템플릿이나 installer를 바꾸면 `tests/test_installer.py`로 사용자 수정 파일 skip,
  프로젝트 overlay 비관리, 실행 비트 채택, 퇴역 파일 제거·rollback을 확인한다. 임시
  대상에 두 번 설치해 두 번째 report의 `created/updated/removed/adopted/skipped`가 전부
  빈 배열인지도 확인한다.
- `raw/manifests/`를 손으로 편집·추가한 뒤에는 `project-brain audit`를 돌린다 — redaction_status
  enum 검증이 write 시점(save_object)뿐 아니라 lint_store 전수 재검증에도 있으나, 수기 편집은
  write 층을 건너뛰므로 audit로 태워야 잡힌다. (라우터 `_restricted_for`는 "approved"가 아니면
  fail-closed로 restricted 처리 — 누락 시 조용한 신뢰 오표기는 없으나 enum 위반은 audit로 확인.)
