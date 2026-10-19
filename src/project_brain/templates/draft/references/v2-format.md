# JSON v2 항목과 patch

문서는 version=2, topic_id, title, scope, resume_summary, updated, items, sources다.
scope는 240자, resume_summary는 2000자 이내다. updated는 엔진이 찍는다.
항목·source key는 topic 안에서 유일한 ASCII kebab-case이며 안정적으로 유지한다.

항목은 key, kind, text, source_keys와 선택적인 limits, recall_question을 가진다.
kind는 finding/concept/decision/hypothesis/question이다. 모두 미검수 작업 재료다.
hypothesis/question은 자동 적재 후보가 아니다. recall_question은 회상 검사 질문 후보로,
미결 kind=question과 다르다. 근거가 충돌하면 각 주장/source를 보존하고 finding.limits에 적는다.

source는 key, kind, locator와 선택 quote, context, observation을 가진다.

| kind | locator | 원문 보존 |
|---|---|---|
| code | repo, checkout 상대 path, 선택 symbol | 짧은 verbatim quote. 현재 관찰은 observe:true |
| document | path와 선택 section, 또는 url/uri | 로컬 원문 위치·구분 가능한 절. 외부 자료는 locator만 기록 가능 |
| session | session_id, position, 확보한 경우 occurred_at | 사용자 발화 그대로의 quote와 질문 context. 시각은 timezone 포함 |
| object | object_id | 기존 객체 ID. ID 존재는 검수 완료가 아님 |

현재 코드 source를 추가/재관찰할 때 patch value에 `observe:true`를 넣는다.
엔진은 CLI cwd 또는 --repo-root의 Git toplevel을 쓰며 brain_root로 추정하지 않는다.
repo_root·관찰 시각·full HEAD SHA·path_dirty·실제로 읽은 bytes hash와 quote 존재 상태를 기록한다.
checkout 루트의 .project-brain.json repo와 locator repo의 일치를 확인하며, 확인할 수 없으면
관찰을 unavailable로 남긴다. source에 적힌 저장소 이름만으로 현재 관찰을 확정하지 않는다.
dirty 원문은 HEAD blob을 읽었다는 뜻이 아니다. 관찰할 수 없으면 unavailable과 이유를 남긴다.
이 Git/파일 읽기는 짧은 write lock 밖에서 수행하며 실제 쓰기 직전에 expected SHA를 다시 확인한다.

과거 재료는 `observation:{"status":"historical", ...}`에 확보한 head_sha·observed_at·sha256 등을
보존하거나 `{"status":"unavailable"}`로 둔다. 현재 SHA를 과거 관찰로 대신 넣지 않는다.
current 관찰을 임의로 작성하지 않는다. observe 없는 새 source는 unavailable이며,
요약·다른 항목의 patch는 기존 관찰을 갱신하지 않는다. quote present/absent/multiple은
문자열 존재 상태이며 동작 의미나 최신성 판정이 아니다.

## patch 예시

```json
{
  "resume_summary": "서버 시각 판정 확인. 표시 기준은 다음 구간에서 확인한다.",
  "sources": [
    {"op": "add", "value": {
      "key": "expiry-code", "kind": "code",
      "locator": {"repo": "example", "path": "src/Expiry.cpp", "symbol": "isExpired"},
      "quote": "return now >= expiresAt;", "observe": true
    }}
  ],
  "items": [
    {"op": "add", "value": {
      "key": "expiry-clock", "kind": "finding", "text": "만료는 서버 기준 시각으로 판정한다.",
      "source_keys": ["expiry-code"], "recall_question": "만료 판정은 어떤 시각 기준인가?"
    }}
  ]
}
```

metadata(title/scope/resume_summary)는 명시적 교체다. items/sources는 add(없는 key),
replace(있는 key의 전체 value), delete(`{"op":"delete","key":"..."}`)다.
같은 배열에서 한 key를 두 번 바꾸거나 전제가 맞지 않으면 전체 무변경 거부한다.
source를 삭제할 때 남은 항목에서 그 key를 참조하면 함께 거부한다.
중복 JSON 필드·key, 알 수 없는 필드, 형식별 옵션 혼용도 거부한다.

사용자 발화 보존은 근거 승인이 아니다. 정식 적재에서는 발췌 문장의 문맥·적용 범위·현재 유효성을
확인받고 기존 source_type=session / reviewer=user-statement 경로를 쓴다.
미확인 발췌는 draft에 남긴다. 코드 사실은 사용자 확인만으로 reviewed로 만들지 않는다.
