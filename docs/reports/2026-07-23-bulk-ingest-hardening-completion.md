# 대량 적재 강화 최종 완료 보고서

**완료일:** 2026-07-23
**엔진 브랜치:** `main`
**기능 브랜치 최종 코드:** `182e650`
**merge 후 테스트 호환성 수정:** `f3a7053`
**상태:** Task 1~12 구현·명세 검토·품질 검토 완료

## 1. 결과 요약

대량 적재에서 실제로 발생했던 이중 접두 ID, raw 청크 과소계산, 항목별 반복 색인,
workflow 부분 실패 오인, 코드 흐름 검증 누락, installer 설치본 드리프트를 엔진·runtime·
스킬 문서의 각 책임으로 분리해 막았다.

핵심 결과는 다음과 같다.

- 엔진이 조립 노트의 logical key와 raw 자원 한계를 fail-fast로 검증한다.
- 단건 item ingest와 전체 semantic finalization을 분리했다.
- batch는 부분 성공 상태를 report로 남기고 안전하게 resume할 수 있다.
- workflow는 최상위 상태가 아니라 항목별 exact `ok`와 기대 개수로 완료를 판정한다.
- ingest 스킬은 실행 router가 되고 세부 판단은 reference 단일 원본으로 분리됐다.
- installer는 템플릿에서 사라진 미수정 관리 파일을 설치본과 manifest에서 제거하며,
  중단된 퇴역 작업을 rollback한다.
- Project Brain 범용 템플릿과 BB2 전용 코드 검증 overlay의 소유권을 분리했다.

## 2. 엔진 변경

### logical key 가드

`validate_notes()`는 context, glossary, mapping, decision, code anchor와 상호 연결 key에
완성 객체 ID가 들어오는 것을 거부한다. 조립기는 context와 kind prefix를 직접 붙이므로
입력은 `core-behavior` 같은 상대 logical key여야 한다. anchor의 결정론적 `--N` 접미만
예외로 허용한다.

이 가드는 과거 `g.<context>.g.<context>...` 형태의 이중 접두 객체가 24개 만들어진 뒤
65개 객체를 복구해야 했던 사고를 build 전에 차단한다.

### raw 청크와 실모델 메모리

`approx_tokens()`는 다음 보수적 근사를 쓴다.

- ASCII word: 1
- 한글 음절: 1
- 그 밖의 비공백 기호: 2글자당 1

헤더·줄·문장 분할 뒤에도 한 유닛이 목표 500토큰을 넘으면 문자 경계에서 다시 나눈다.
표 구분자나 한글이 많은 긴 한 줄이 하나의 과대 청크로 남지 않는다. `RealEmbedder`는
batch size 8과 `max_seq_length=2048`을 함께 써서 Metal(MPS)의 거대 어텐션 버퍼를
마지막으로 제한한다.

### batch와 semantic completion

설치되는 ingest runtime의 역할은 다음과 같다.

| 도구 | 책임 |
|---|---|
| `validate_workflow_result.py` | 기대 개수, key 유일성, 각 item의 exact extract/verify `ok` 검증 |
| `run_ingest.sh` | 한 item의 assemble → build → ingest, `--dry`·`--defer-finalize` 지원 |
| `run_ingest_batch.py` | manifest 상대경로, baseline, fingerprint, 성공/실패 report, resume |
| `finalize_ingest.sh` / `.py` | index, lint, eval, graph, corpus tests, 예상 객체+CodeLocator 회수 |

batch item은 `--defer-finalize`로 적재한다. 실패가 하나라도 있으면 finalizer를 호출하지
않고 `finalized=false`를 유지한다. 전체 성공 뒤에도 finalizer의 종료 코드만 보지 않고
정해진 JSON schema와 `ok=true`를 함께 확인한다.

report 경로가 manifest, verify JSON, domain spec 또는 그 심링크 별칭이면 baseline 수집이나
item 실행 전에 거부한다. 입력 파일이 report에 덮이는 실패를 막기 위한 경계다.

## 3. 스킬 구조

ingest `SKILL.md`는 148줄·1,072단어의 실행 router다. Source Intake, single/batch 선택,
history coverage, extract/verify, build/ingest, semantic completion의 순서만 본문에 두고
세부 계약은 reference로 라우팅한다.

- `object-model.md`: 필드·연결·logical key
- `scope.md`: source intake·history coverage
- `ingest-tools.md`: 단건/batch CLI·raw 보관
- `system-domain-playbook.md`: workflow 분할·resume·프로젝트 검증 전달
- `completeness-checklist.md`: semantic completion
- `update-rules.md`: kind별 기존 객체 갱신·대체 단일 원본

과거 session-ingest가 갖고 있던 `references/update-rules.md`는 퇴역했다. session-ingest는
ingest의 update-rules를 참조해 같은 객체 변경 규칙을 공유한다.

코드 기반 extract/verify는 프로젝트에
`references/project-code-verification.md`가 있을 때만 이를 읽는다. 이 overlay는 프로젝트
소유이며 Project Brain installer manifest에 포함되지 않는다. BB2 overlay는
`bb2-code-search-routing`, clangd callers, 매크로·notification/callback의 `rg` 추적과
동적 작업자 프롬프트 전달 규칙을 연결한다.

## 4. installer 퇴역 파일 안전 모델

installer는 현재 템플릿의 desired 집합과 기존 manifest를 비교한다.

1. 제어 파일·관리 경로·부모·leaf가 안전한 일반 파일 경로인지 preflight한다.
2. 사용자 수정된 retired 파일이나 적용 불가능한 migration 목적지가 있으면 쓰기 전에
   중단한다.
3. desired 파일을 같은 디렉토리의 완성된 임시 파일로 준비·교체한다.
4. 최종 manifest 임시 파일을 먼저 완성하고 fsync한다.
5. retired 원본을 unlink하지 않고 같은 parent의 고유 backup으로 원자 이동한다.
6. manifest를 원자 교체한 뒤에만 backup을 제거하고 `removed`를 확정한다.

N번째 retired 이동이나 manifest 교체가 실패하면 앞서 옮긴 원본을 역순으로 복원한다.
복원 자체가 실패하면 원래 오류와 복구 오류를 함께 표면화하며 남은 backup을 지우지 않는다.
실패 주입 회귀는 바이트 동일성, 구 manifest 보존, 임시 파일 부재, 재시도 성공,
2회차 완전 no-op을 확인한다.

matching untracked 파일은 내용이 템플릿과 같을 때 `adopted`로 편입하고, 스크립트의 실행
비트도 템플릿과 맞춘다. 내용이 다른 manifest 밖 파일과 프로젝트 overlay는 `--force`에서도
사용자 소유로 보존한다.

## 5. Task 9 행동 증거

다섯 중립 fixture에는 예상 출력·예상 파일명·예상 해시를 미리 넣지 않았다. 실제 실행 뒤
관찰한 결과만 [Task 9 행동 보고서](2026-07-22-bulk-ingest-task9-behavior-evidence.md)에
기록했다.

| 시나리오 | 관찰 결과 |
|---|---|
| 현재 코드 단건 | `Source Intake`, `route=single`, `history_coverage=unsearched`; build/ingest 성공 후 finalize 보류 |
| 부분 실패 workflow | 두 번째 item의 `verify_status != ok`를 거부하고 객체·report를 만들지 않음 |
| C++ 코드 흐름 | clangd callers로 `transform ← dispatch ← run`을 확인하고 CodeLocator와 함께 적재 |
| full-ID logical key | `mapping.sample-a.core-behavior` 입력을 build 전에 거부하고 파일을 만들지 않음 |
| raw 이름 분기 | 개정본 `spec-v1/v2`, 옛 문서 basename, 충돌 SHA 접미, 비ASCII fallback; 22/22 바이트 보존 |

raw 보관 replay는 기존 파일·디렉토리·심링크를 덮지 않고, 충돌 접미사를 source bundle
root 아래 canonical relative path의 SHA-256 앞 12글자부터 결정론적으로 확장한다.

## 6. BB2 설치본 전파

BB2 작업은 `/Users/al03040455/Desktop/bb2_client`의
`docs/bb2-brain-object-model` 브랜치에서 수행했다.

| 커밋 | 내용 |
|---|---|
| `1d1faa77` | 네 brain 스킬 구조·ingest runtime·update-rules 소유권 동기화 |
| `e3e4cd30` | 보수적 청커에 맞춰 real corpus raw chunk guard를 1,577로 갱신 |
| `6022287c` | report 입력 충돌 차단 runtime과 manifest hash 최종 동기화 |

installer를 force 없이 다시 실행했을 때 `created/updated/removed/adopted/skipped`가 모두
빈 배열이었다. BB2 전용 overlay 해시는 유지됐고 manifest에는 들어가지 않았다.
`bb2-brain-session-ingest/references/update-rules.md`는 제거됐으며
`bb2-brain-ingest/references/update-rules.md`가 존재한다.

BB2 커밋의 원격 push는 데이터 저장소 소유자가 별도로 수행한다.

## 7. 실제 코퍼스 검증

첫 stub 측정에서 bare 글로벌 CLI가 당시 기본 checkout의 옛 청커를 import해 raw chunk
1,062를 출력한 실행은 무효 처리했다. 이후 모든 유효 검증은 기능 worktree의
`PYTHONPATH`와 `.venv/bin/python -m project_brain.cli`를 함께 명시했다.

올바른 엔진으로 확인한 최종 DB는 다음과 같다.

| 항목 | 결과 |
|---|---:|
| documents | 7,092 |
| raw_chunk | 1,577 |
| vector rowids | 7,092 |
| schema | 4 |
| embed model | `BAAI/bge-m3` |
| tokenizer | `mecab-ko` |
| extractor version | 3 |
| corpus fingerprint | `3afb552862238abbfeb6853b9fc688e12e285981281f2094be2a227e48a602f3` |
| SQLite quick check | `ok` |

저장된 fingerprint와 현재 코퍼스에서 다시 계산한 fingerprint가 일치했다.

- lint: 문제 0
- eval: 15/15
- graph isolated: 기존 15개(EvidenceRef 14, GlossaryTerm 1)
- corpus guard: 5/5
- `"설치형 콤보폭탄이 뭐야"`: reviewed
  `mapping.disturb-combo-bomb.core-behavior`와 CodeLocator 4개 회수
- `"현재 슈팅된 버블 조회"`: reviewed
  `mapping.ingame-logic.current-ball-option`과 CodeLocator 3개를 첫 결과로 회수

## 8. 최종 엔진 검증과 리뷰

최종 코드 기준 결과:

```text
.venv/bin/python -m pytest -q
611 passed, 26 subtests passed

.venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
Ran 59 tests
OK
```

merge 후 main의 Homebrew Python 3.14가 빈 unittest discovery를 exit 5로 처리하면서
wrapper 테스트 두 subcase가 실패했다. 기능 worktree의 macOS Python 3.9는 같은 빈 suite를
exit 0으로 처리해 드러나지 않았던 fixture 결함이었다. 임시 corpus checks에 실제 통과
unittest를 하나 만들어 두 인터프리터에서 동일하게 검증했고 `f3a7053`으로 커밋했다.
제품 runtime은 바뀌지 않았다.

Task 9~12는 태스크별 구현·명세 검토·품질 검토를 거쳤다. installer 퇴역 rollback,
report 입력 충돌, 실행 비트 채택과 Python 버전 독립 fixture까지 후속 품질 재검토에서
최종 승인됐다.

## 9. 운영 주의

- 이 저장소의 글로벌 CLI는 `uv tool install -e` 편집 설치다. 현재
  `/Users/al03040455/.local/bin/project-brain`은 이 저장소의 `src/project_brain`을 import한다.
- 여러 checkout이 있으면 bare CLI나 시스템 Python이 다른 엔진을 잡을 수 있다. 중요한
  검증은 대상 checkout의 `PYTHONPATH`와 `.venv/bin/python`을 명시한다.
- Hugging Face `BAAI/bge-m3` 캐시는 기존 파일을 재사용했다. 캐시는 삭제·이동하지 않았다.
  올바른 feature 엔진의 실모델 rebuild는 한 번 수행했고, 최종 문서·installer 검증에서는
  index를 다시 만들지 않고 기존 DB와 캐시를 읽었다.
- 기능 브랜치와 worktree는 복구·감사를 위해 보존했다.
