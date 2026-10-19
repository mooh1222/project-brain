# (가) 개발 중 기록과 명시적 정식 적재

발동: 기획서 기반 기능 개발 착수, 또는 개발 중 "이거 저장해두자".

개발 착수와 진행 중 새 이해·가설·결정은 기본적으로 `{{PROJECT}}-brain-draft`에 기록한다.
공통 발견 reference로 관련 topic을 찾고 원문 locator와 작은 항목·재개 요약을 넘긴다.
개발 개선 제안/backlog와 미검증 교차 분석/pending은 기존 위치를 유지하며 자동 이동하지 않는다.
순수 조회는 기록 트리거가 아니다.

사용자가 **즉시 정식 적재를 명시적으로 요청한 경우에만** 아래 기존 경로를 쓴다.

1. **명시적 후보 적재**: 기획서 분석에서 저장 후보(용어·매핑·결정)를 candidate로
   적재. 코드 앵커 없이 가능(candidate는 evidence 강제 없음). EvidenceRef는 기획서
   (raw/sources/<context>/ 보관 — 규약 {{BRAIN_ROOT}}/README.md). DomainContext도 이때 신설.
   direct면 exact `(id, kind)`, 조립이면 notes section과 `expected_objects`를 `COVERAGE`에 먼저 선언하고
   `--coverage-out`에서 build·ingest의 `--coverage-file`까지 같은 binding을 전달한다.
2. **코드 연결** (개발 중): 코드가 생기면 CodeLocator 추가 + 매핑 연결. locator는 경로+심볼
   힌트(라인=조사 당시 스냅샷, verified_at이 시점)를 작업 브랜치 기준으로 달고, `commit_sha`에는
   그 코드를 확인한 작업 브랜치 커밋을 기록한다. 머지 자체는 기존 커밋 SHA를 바꾸지 않는다.
   머지 뒤 기존 SHA가 {{DEFAULT_BRANCH}} 이력에서 도달 가능하고 앵커 대상 코드가 같으면 그대로 둔다.
   일반 merge나 fast-forward만으로 앵커를 다시 잡지 않는다. squash·rebase·cherry-pick 또는 충돌 해결이나 실질 코드 변경으로 기존 SHA가 {{DEFAULT_BRANCH}} 이력에 없거나 코드가 달라진
   경우에만 {{DEFAULT_BRANCH}}에서 다시 확인한 SHA와 스냅샷으로 제자리 갱신한다. `commit_sha`를 비우면
   변경 감지 기준점이 없으므로 여기서도 기입은 의무다.
3. **갱신**: 바뀐 범위의 단어로 기존 객체를 search하고, 있으면 `{{PROJECT}}-brain-ingest/references/update-rules.md`의 kind별 흐름을 따른다. 없으면 신설한다.
4. **완료 마무리**: reviewed 승격과 history를 보강한 뒤 `{{PROJECT}}-brain-ingest/references/completeness-checklist.md`로 닫는다.

coverage 없는 single/batch는 쓰기 전에 실패해야 한다. terminal 결과는 canonical receipt의
`expected_objects == verified_objects`와 `committed|no_changes`를 확인한 뒤에만 finalize한다.

**폐기 경로**: 기능 폐기·기획 취소 시 그 context의 후보 선점 candidate를 일괄
status=`rejected`로 전환(사유 노트). 코드 앵커 없는 candidate가 잔존하면 회상 후보 채널에
실재하지 않는 기능이 계속 떠 오답을 유도한다.
