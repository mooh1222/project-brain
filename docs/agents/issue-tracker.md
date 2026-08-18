# Issue tracker: GitHub

이 저장소의 spec과 작업 issue는 `mooh1222/project-brain` GitHub Issues에 둔다.
모든 조회·생성·댓글·라벨·종료 작업은 저장소 안에서 `gh` CLI로 수행한다.

## Conventions

- spec 게시 요청은 GitHub issue 생성으로 해석한다.
- issue를 읽을 때는 본문·댓글·라벨을 함께 확인한다.
- `to-spec`으로 게시한 spec은 `enhancement`와 `ready-for-agent` 라벨을 사용한다.
- 후속 ticket의 선후관계는 GitHub native issue dependency를 우선한다. 사용할 수 없으면
  issue 본문 맨 위의 `Blocked by: #<number>`로 대체한다.
- GitHub issue와 PR은 번호 공간을 공유하므로 bare `#42`는 PR을 먼저 확인하고 issue로
  fallback한다.

## Pull requests as a triage surface

**PRs as a request surface: no.**

명시적으로 지정된 PR은 확인할 수 있지만, 외부 PR을 자동 triage 대기열로 수집하지 않는다.
