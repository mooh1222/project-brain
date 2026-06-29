# (가) 진행 중 개발 적재 — 시간차 흐름 4단계

발동: 기획서 기반 기능 개발 착수, 또는 개발 중 "이거 저장해두자".

1. **후보 선점** (개발 시작): 기획서 분석에서 저장 후보(용어·매핑·결정)를 candidate로 바로
   적재. 코드 앵커 없이 가능(candidate는 evidence 강제 없음). EvidenceRef는 기획서
   (raw/sources/<context>/ 보관 — 규약 {{BRAIN_ROOT}}/README.md). DomainContext도 이때 신설.
2. **코드 연결** (개발 중): 코드가 생기면 CodeLocator 추가 + 매핑 연결. locator는 경로+심볼
   힌트(라인=조사 당시 스냅샷, verified_at이 시점) — 작업 브랜치 기준으로 달고, {{DEFAULT_BRANCH}} 머지
   시 스냅샷 갱신(제자리)으로 정정한다. `commit_sha`는 여기서도 기입 의무(라인을 확인한
   그 브랜치 커밋 — 머지 정정 때 {{DEFAULT_BRANCH}} sha로 교체). 비우면 변경 감지 기준점이 없다.
3. **갱신** (이미 있는 걸 고칠 때 — 가장 흔한 흐름): **추출(뭐가 바뀜) → `search`로 기존 객체 있는지 찾기 → references/update-rules.md 분기표로 처리 판정**. ingest는 '저장'만 한다 — '찾기'와 '판정'은 에이전트 몫. '찾기'는 자동 전수조사가 아니라 **자기 수정 범위를 알고 그 단어로 search**하는 것(개발자는 자기가 뭘 고쳤는지 안다). 기존 객체가 없으면(search 0건) 그냥 신설. 점검·개선 수정이면 원인이 있으니 DecisionRecord(decision_type=`improvement`) 연결.
4. **완료 마무리** (기능 완료): reviewed 승격 검토 + history 보강 — 완료 소급({{PROJECT}}-brain-ingest)
   수준으로 닫는다. {{DEFAULT_BRANCH}} 기준으로 locator 수렴. 중복·병합 판정은 에이전트.

**폐기 경로**: 기능 폐기·기획 취소 시 그 context의 후보 선점 candidate를 일괄
status=`rejected`로 전환(사유 노트). 코드 앵커 없는 candidate가 잔존하면 회상 후보 채널에
실재하지 않는 기능이 계속 떠 오답을 유도한다.
