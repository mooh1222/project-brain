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

## Wayfinding operations

`wayfinder`는 하나의 map issue와 그 아래 child issue를 사용한다.

- **Map**: `wayfinder:map` 라벨을 붙인 단일 issue다. 본문에는 Destination, Notes,
  Decisions so far, Not yet specified, Out of scope를 둔다.
- **Child ticket**: map의 GitHub sub-issue로 연결하고 `wayfinder:research`,
  `wayfinder:prototype`, `wayfinder:grilling`, `wayfinder:task` 중 하나를 붙인다.
  sub-issue를 사용할 수 없으면 map의 task list에 연결하고 child 본문 맨 위에
  `Part of #<map>`을 적는다.
- **Blocking**: GitHub native issue dependency를 사용한다. blocker의 database id는
  `gh api repos/<owner>/<repo>/issues/<number> --jq .id`로 구하고, child에
  `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by \
  -F issue_id=<blocker-database-id>`로 연결한다. native dependency를 사용할 수 없을 때만
  child 본문 맨 위의 `Blocked by: #<number>`를 사용한다.
- **Frontier**: map의 열린 child 가운데 미해결 blocker와 assignee가 없는 issue만 남기고,
  map 순서의 첫 issue를 다음 작업으로 고른다.
- **Claim**: 작업 전에 `gh issue edit <number> --add-assignee @me`로 먼저 할당한다.
- **Resolve**: 결정 내용을 resolution comment로 남기고 issue를 닫은 다음, map의
  Decisions so far에 제목·링크·한 줄 결론을 추가한다.
