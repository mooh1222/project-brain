# 적재별 데이터 한 장(코드 아님 — 의미 데이터만). assemble_notes.py가 읽는다.
# 조립 로직은 절대 여기 넣지 않는다(그건 assemble_notes.py). 채우는 건 데이터뿐.
CTX = ""                       # 컨텍스트 키 (예: "ball-select")
COMMIT = ""                    # {{DEFAULT_BRANCH}} 이력에서 도달 가능한 앵커 커밋 (git rev-parse --short=10)
REPO = "{{REPO}}"
MANIFESTS = {                  # sources[]가 될 매니페스트. 키=종류, 값=manifest id
    "code": "manifest.<ctx>.code",
    # "commit": "manifest.<ctx>.commit", "jira": "manifest.<ctx>.jira", "pr": "manifest.<ctx>.pr",
}
DISPLAY_NAME = ""
BOUNDARY_SUMMARY = """"""      # 다줄 한국어 경계 설명
IN_SCOPE = []
OUT_OF_SCOPE = []
GROUP_ORDER = []              # 의미 경계(사람 판정). verify 그룹명 순서
EXCLUDE_TERMS = set()        # 독립 회상 가치 없는 용어(사람 판정)
HISTORY_COVERAGE = "unsearched"   # unsearched | partial | complete
NOW = ""                      # 고정 ISO 시각 (예: "2026-06-26T00:00:00+09:00") — churn 0
# claim 기본 상태. candidate GlossaryTerm은 각 항목에 아래 기존 계약을 반드시 함께 둔다:
# {"candidate": {"candidate_state": "ready_for_review", "candidate_source": "code"}}
# candidate_state/source의 허용값은 schema.py를 따른다. 후보 메타데이터가 비면 조립이 거부된다.
CLAIM_STATUS = "reviewed"
# 근거 출처는 기본값이 없다. 빈 값은 assembly가 거부한다.
SOURCE_ACL: list[str] = []
CAPTURED_AT = ""
# CodeLocator의 원문 인용은 공백·줄바꿈을 바꾸지 않고 저장한다. 빈 값은 assembly가 거부한다.
VERIFIED_AT = ""
# Task 5 finalizer가 사용할 선언값. 이 조립기에서는 아직 해석하지 않는다.
EXPECT_UNMERGED_ANCHORS = False
CORRECTIONS = {}             # 선언적 보정 {mapping_key: {"meaning": "...", "drop_terms": [...]}}
DECISIONS = []               # decisions[] 노트 그대로(엔진 build_decisions가 조립).
                              # 각: {"key","decision_type","title","summary","decision",
                              #      "spec_reflected"?, "affects":[mapping_key...],
                              #      "evidence":[{"type":"commit|jira|pr","ref","summary"?,"locator"?}]}
                              #   (commit: locator={repo,sha} 자동. jira/pr: locator=인스턴스 URL을 직접 적는다.)
FINALIZATION = {             # 고정 샘플 질의 금지: 이 적재가 실제로 회수해야 할 ID를 선언
    "recall_checks": [{
        "key": "",          # 이 적재 안에서 중복 없는 검사 key
        "query": "",        # 새 도메인을 실제로 묻는 질문
        "expected_object_ids": [],
        "require_code_locators": True,
    }],
    "intentional_terminal_ids": [],  # 새 고립 중 근거를 남긴 의도적 종착점만
}
# HOOK = lambda atoms: atoms  # (선택) 선언적으로 안 되는 그 적재 한정 변칙. 쓰면 ingest-case-log.md에 기록.
