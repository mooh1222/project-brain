# 적재별 데이터 한 장(코드 아님 — 의미 데이터만). assemble_notes.py가 읽는다.
# 조립 로직은 절대 여기 넣지 않는다(그건 assemble_notes.py). 채우는 건 데이터뿐.
CTX = ""                       # 컨텍스트 키 (예: "ball-select")
COMMIT = ""                    # {{DEFAULT_BRANCH}} 앵커 커밋 (git rev-parse --short=10)
REPO = "{{REPO}}"
MANIFESTS = {                  # sources[]가 될 매니페스트. 키=종류, 값=manifest id
    "code": "manifest.<ctx>.code",
    # "commit": "manifest.<ctx>.commit", "jira": "manifest.<ctx>.jira",
}
DISPLAY_NAME = ""
BOUNDARY_SUMMARY = """"""      # 다줄 한국어 경계 설명
IN_SCOPE = []
OUT_OF_SCOPE = []
GROUP_ORDER = []              # 의미 경계(사람 판정). verify 그룹명 순서
EXCLUDE_TERMS = set()        # 독립 회상 가치 없는 용어(사람 판정)
HISTORY_COVERAGE = "unsearched"   # unsearched | partial | complete
NOW = ""                      # 고정 ISO 시각 (예: "2026-06-26T00:00:00+09:00") — churn 0
CORRECTIONS = {}             # 선언적 보정 {mapping_key: {"meaning": "...", "drop_terms": [...]}}
DECISIONS = []               # decisions[] 노트 그대로(엔진 build_decisions가 조립).
                              # 각: {"key","decision_type","title","summary","decision",
                              #      "spec_reflected"?, "affects":[mapping_key...],
                              #      "evidence":[{"type":"commit|jira|pr","ref","summary"?,"locator"?}]}
# HOOK = lambda atoms: atoms  # (선택) 선언적으로 안 되는 그 적재 한정 변칙. 쓰면 ingest-case-log.md에 기록.
