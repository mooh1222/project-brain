# 브랜치 기반 Brain 적재·감사 안전 보강 완료 보고서

**완료일:** 2026-07-23  
**Project Brain 최종 SHA:** `6bed11457b4213964fb0ba8399177887f79effc5`  
**BB2 설치본 최종 SHA:** `4894337958f394585ae7a09c0d6a180144e9e556`  
**상태:** 구현·설계 검토·품질 검토·merge·push 완료

## 1. 시작 계기

BB2 인게임 확장 프로토를 개발 브랜치에서 Brain에 적재하는 과정에서
`머지 뒤 develop SHA로 고쳐야 한다`는 안내가 나왔다. 원인은 session-ingest 문서의
`머지 정정 때 기본 브랜치 SHA로 교체`라는 무조건형 문장이었다.

커밋 SHA 자체는 머지로 바뀌지 않는다. fast-forward와 일반 merge에서는 작업 브랜치
커밋이 기본 브랜치 이력에 그대로 들어가므로, 기존 SHA가 기본 브랜치에서 도달 가능하고
앵커 대상 코드가 같으면 그대로 유지하는 것이 맞다. squash·rebase·cherry-pick이나
충돌 해결로 SHA 또는 코드가 달라진 경우에만 코드를 확인한 뒤 앵커를 갱신한다.

## 2. 합의한 경계

- `reviewed`는 근거와 해석을 검토했다는 뜻이며, 기본 브랜치 도달 여부와 분리한다.
- 검증된 개발 브랜치 프로토는 미머지라는 이유만으로 `candidate`로 내리지 않는다.
- 미머지 상태는 오류가 아닌 `unmerged_anchors` 안내 정보로 노출한다.
- Git 실행 실패, 존재하지 않는 커밋·경로, blob이 아닌 대상, 정확 인용문 불일치는
  검증 불가 상태로 보고 audit와 ingest finalization을 실패시킨다.
- Project Brain 템플릿과 runtime을 먼저 고치고, BB2 설치본은 엔진 installer로만 받는다.
- 기존 BB2 인게임 확장 객체 101개의 재생성·재적재는 이 작업 범위에서 제외한다.

이 경계는 구현 주체·아키텍트 서브에이전트·크리틱 서브에이전트의 3자 검토로 확정했다.

## 3. Project Brain 변경 결과

### 브랜치 도달성과 코드 근거

- `.project-brain.json`의 `default_branch`를 Git 도달성 판정의 기준으로 사용한다.
- `stale-check`, query/show 경고, audit가 미머지와 검증 불가를 서로 다른 상태로 보존한다.
- `CodeLocator.verified_quote`가 있으면 `git show <sha>:<path>`의 blob 바이트에서 정확히
  일치하는지 확인한다. 공백 정규화나 느슨한 문자열 비교는 하지 않는다.

### 적재 finalization

개발 브랜치 적재는 시작 시점의 기본 브랜치 HEAD와 미머지 locator 집합을 baseline으로
기록한다. 완료 때 기본 브랜치 HEAD가 그대로이며, 사후 미머지 집합이
`baseline ∪ 이번 적재 예상 locator`와 같은지 확인한다. audit 상태를 얻지 못했거나
검증할 수 없으면 성공으로 간주하지 않는다.

### 색인 내구성

색인 재구축은 같은 디렉토리의 임시 DB와 별도 잠금을 사용한다. SQLite 무결성·문서 수를
확인하고 디스크 동기화한 뒤 `os.replace`로 교체한다. 생성·검사·교체 뒤 내구성 보장 중
어느 단계에서 실패해도 주된 오류를 잃지 않고 기존 DB를 보존한다.

## 4. BB2 설치 이력

대상은 `/Users/al03040455/Desktop/bb2_client`의
`docs/bb2-brain-object-model` 브랜치였다.

| 커밋 | 내용 |
|---|---|
| `5e3d5c4a6f` | 엔진 installer로 branch-aware Brain 스킬과 runtime 설치 |
| `8a7d56323a` | 설치 manifest 기록 |
| `4894337958` | finalizer의 audit-state 차단 규칙 최종 동기화 |

`--force` 없이 설치했으며, 같은 엔진 SHA로 다시 설치했을 때 변경 배열은 모두 비었다.
설치된 23개 관리 파일은 엔진 템플릿과 hash·크기·실행 비트가 일치했고
`agents-doctor`도 통과했다. 기존 로컬 `Podfile.lock` 수정은 건드리지 않았다.

## 5. 최종 검증과 통합

Project Brain `feat/brain-ingest-branch-audit-hardening`은 `6bed114`까지 25개 커밋으로
구현했다. 최종 통합 검토는 Critical·Important·Minor 지적 없이 `Ready: Yes`였다.

```text
.venv/bin/python -m pytest -q
674 passed, 32 subtests passed

.venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
Ran 75 tests
OK
```

ingest shell script 문법 검사와 `git diff --check`, 임시 대상 installer 2회 실행도
통과했다. 기능 브랜치는 `main`에 fast-forward merge해
`origin/main`으로 push했고, merge된 로컬 feature 브랜치와 worktree는 정리했다.
BB2 `docs/bb2-brain-object-model`도 `4894337958`까지 원격으로 push했다.

## 6. 의도적으로 실행하지 않은 작업

이번 작업에서는 다음 고비용 데이터 작업을 실행하지 않았다.

- 기존 101개 BB2 인게임 확장 객체 재생성·재적재
- BB2 Brain 전체 audit·eval·corpus·recall·finalization
- 검토에서 식별한 locator 30개, EvidenceRef 3개, manifest 2개의 데이터 보정
- 인게임 기능 브랜치가 기본 브랜치에 합쳐진 뒤 locator 30개 실데이터 재대조

따라서 엔진과 설치본 안전 보강은 완료됐지만, 위 항목은 다음에 실제 적재를 별도로
승인할 때만 수행한다. 일반 merge라면 기존 도달 가능한 SHA를 유지하고 미머지 집합에서
빠졌는지만 확인한다. squash·rebase·cherry-pick 또는 의미 있는 충돌 해결이 있었다면
영향받은 코드를 먼저 확인한 뒤 필요한 locator만 다시 앵커링한다.
