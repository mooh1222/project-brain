# CLAUDE.md

항상 한국어로 답변한다.

## 프로젝트

프로젝트 도메인 지식 brain 엔진. 검수 상태·근거가 붙은 객체 코퍼스를 적재(ingest/
promote)하고, 한국어 하이브리드 검색(FTS5 BM25 + bge-m3 벡터 + RRF + 그래프 재정렬)
으로 회상한다. 상세는 README.md.

## 2-레포 모델 — 여기는 엔진만

- **이 레포**: 엔진 코드 + 합성 데이터 테스트만. 실코퍼스(프로젝트 도메인 데이터)는 없다.
- **데이터 레포**: 소비 프로젝트의 루트 `brain/`.
  골든셋(`brain/eval_scenarios.json`)과 실측 가드(`brain/checks/`)는 그쪽 소유다.
- 엔진 설계·로드맵·발전 히스토리는 이 레포에 있다: 히스토리 허브 [ROADMAP.md](ROADMAP.md)
  (완료 단계·현황·미뤄둔 작업) + [docs/design-canonical.md](docs/design-canonical.md) +
  `docs/specs/`·`docs/plans/`. 데이터·적재 이력만 데이터 레포(`brain/`)·vault task에 있다.

## 개발 루프

```bash
uv sync --extra mecab                  # 개발 venv (최초 1회)
.venv/bin/python -m pytest tests/ -q   # 합성 테스트 (실코퍼스 불필요)
```

- 글로벌 도구는 이 클론의 **편집 설치**다(`uv tool install -e . --with mecab-python3`)
  — 여기서 코드를 고치면 `project-brain` 명령에 즉시 반영된다. 재설치 불필요.
  단 pyproject 의존성이 바뀌면 `uv tool install -e . --with mecab-python3 --force`.
- TDD: red 테스트 먼저, 그다음 구현. 결정론 유지 — 테스트에서 실모델 금지
  (StubEmbedder / `PROJECT_BRAIN_EMBEDDER=stub`), 토큰화는 정규식 폴백 강제 패턴 참고.

## 엔진 수정 후 실코퍼스 회귀 (필수)

엔진 테스트는 합성뿐이라, 검색 품질·색인·라우터를 건드렸으면 데이터 레포에서 회귀를
돌려야 완료다:

```bash
cd <소비 프로젝트 루트>
python3 -m unittest discover -s brain/checks -p "test_*.py"   # 실측 가드 (CLI 호출 — 빠름)
project-brain index rebuild      # 색인 영향 변경 시 (실모델, 수십 초)
project-brain eval               # 골든셋 7종 (실모델)
```

## 주의

- `Date`·경로 하드코딩 금지 — 경로는 config(.project-brain.json) 해석
  (`src/project_brain/config.py`, 명시 인자 > config > ConfigError).
- `context_projection.py`는 context_md 빌더와 `build_reuse_projection`(재사용 projection 빌더)를 모두 담는 정본이다. projection 재사용층(별도 검색 레인)이 소비하며, cli `projection` 서브커맨드·`rebuild`·`lint`도 이 파일을 참조한다. "동결·소비자 없음"이 아님.
- 스킬 템플릿(`src/project_brain/templates/`)을 바꾸면 install의 manifest 보존
  동작(사용자 수정 파일 skip)을 깨지 않는지 `tests/test_installer.py`로 확인.
