# BB2 Brain — 조립 결과 재사용층 (Projection Reuse Lane) 설계

- 작성일: 2026-06-17
- 상태: 설계 (구현 전) — v2: codex(project-brain 엔진) 합성 검증 리뷰 반영(§4.1 작업 지점 정정·promote 불필요·채널 전파·reviewed 전용 채널). v2.1: codex 최종 리뷰 반영 — projection은 promote 후에도 `projection_reuse` 채널 유지(채널 이동 아님), status별 라벨 분리(candidate=미검증/reviewed=검증됨)
- 정본 연결: [[bb2-project-brain]] §3 L3(회상·답변)·L4(적재) / task [[bb2-project-brain-build]]
- 대상 레포: 엔진 = `project-brain`(`~/Downloads/codes/project-brain`) / 데이터·스킬 = 게임 레포 `bb2_client`

## 0. 이 문서의 위상과 근거

이 설계의 모든 결정은 아래 셋에서 나왔다. 추측이 아니라 검증된 입력이다.

- **사용자 결정 2건(2026-06-17 세션)**: (1) 재사용 방향으로 "답변 텍스트 캐시"가 아니라 "projection" 선택, (2) **"projection은 별도 검색층으로 둬야 하지 않을까"** — 별도 레인 방식 채택.
- **codex(project-brain 엔진) 5턴 브레인스토밍**: 답변 캐시 반대, §8 조립 모드 유지, 재사용은 bundle-aware 회수 + 파생 projection으로 좁힘. 별도 레인 실현 시 필요한 엔진 작업 목록과 낡음 처리 위치를 엔진 코드 근거로 제시.
- **엔진 코드 직접 검증(이 세션)**: 아래 §3·§5에 인용한 파일·함수·필드는 전부 현재 코드에서 실재를 확인했다. 정확한 줄 번호는 구현(writing-plans) 시점에 재확인한다(코드가 활발히 바뀌므로 줄은 스냅샷).

## 1. 배경 — 풀려는 문제

`bb2-brain-query` 스킬 §8(개발 착수 조립 모드)은 개발 요구를 받으면 분해 질의 3축 + 도메인 용어 재시도 + 적중 객체 원문 열람 + 5요소 조립으로 착수 브리핑을 만든다. 정확도 규칙으로는 충분하다.

문제는 **같은/비슷한 요구가 다음 세션에 또 오면 그 브리핑을 처음부터 다시 조립한다**는 점이다. 실측:

- 실험 A(샐리 카누 결과 팝업 착수 브리핑): **8질의**(Q1은 "경주"라는 자연어가 도메인 용어 "레이스"와 어긋나 미스 → 재질의). 흩어진 적재 + 어휘 미스가 겹침.
- 방해버블: 4질의(확장 지점이 한 종합 매핑에 모여 있어 짧게 끝남).

여기서 진짜 비싼 것은 로컬 색인 검색(`project-brain search`) 호출이 아니라, **여러 질의로 나눠 회상하고 그 결과를 읽어 종합하는 추론 자체**(토큰·시간)다. 그 종합 결과(브리핑)는 재사용 가치가 크지만, 지금은 어디에도 남지 않아 매번 새로 만든다.

## 2. 목표 · 비목표

### 목표
- 한 기능 안에서 여러 객체를 종합한 착수 브리핑을 **재방문 시 재조립 없이 재사용**한다.
- 재사용 자산은 정본 객체 그래프를 잠식하지 않고, "미검증 후보"로 노출되며, 쓰면서 검수 승격된다(brain 검수 사다리 일관).
- 구성 객체가 바뀌면 자동으로 낡았다고 걸러진다(무효화 비용을 새로 만들지 않고 기존 부품 재사용).

### 비목표 (명시적으로 안 하는 것)
- **답변 텍스트 캐시를 만들지 않는다.** 자유 텍스트 답변을 정본 옆에 또 쌓는 "AI 유지보수 문서 층"은 정본 §2가 금지한다. projection은 답변이 아니라 "구성 객체 id + 산출물 위치 + 낡음 지문"을 담은 메타다.
- **§8 조립 모드를 대체하지 않는다.** projection이 없거나 낡았으면 §8로 새로 조립한다. projection은 그 위의 재사용 단축일 뿐이다.
- **검색 중 자동 저장을 하지 않는다.** 저장은 조건을 만족한 순간 에이전트가 명시적으로 트리거한다(§4.3).
- **mapping_bundle을 회수 부품으로 승격하는 것은 이 spec 범위가 아니다.** 별도 보완 과제로 남긴다(§7).

## 3. 설계 결정

### 3.1 정체 · 묶는 단위

- projection은 기존 `ContextProjection` kind를 **확장**해서 쓴다. 새 kind를 만들지 않는다.
  - 근거: `schema.py`에 `ContextProjection`이 이미 정의돼 있고 필드(`context_id`, `format`, `source_object_ids`, `source_content_hash`, `output_locator`, `projection_hash`, `stale_policy`)와 `truth_role="index"`, 포맷 값 집합 `PROJECTION_FORMAT_VALUES = {context_md, prompt_payload}`이 갖춰져 있다. 검색 표면에서 빠지는 종류라 정본과 경쟁하지 않는다.
- **묶는 단위 = 한 context(기능) 안의 "요구 부분집합"**.
  - 근거: `ContextProjection`은 `context_id`가 필수라, 한 projection은 자연히 단일 기능 범위로 한정된다. 전체 컨텍스트 스냅샷(현재 `context_md` 빌더가 만드는 것)도 아니고, 여러 기능을 가로지르는 것도 아니다.
  - 현재 `build_context_projection`은 context의 reviewed 용어·매핑을 **전부** 덤프한다(`context_projection.py`). 이걸 그대로 쓰면 샐리(reviewed 매핑 63개)가 통째로 끌려와 노이즈가 된다 — 우리가 피하려는 문제와 같다. 그래서 **요구 부분집합만 담는 새 빌더 경로**가 필요하다(§5 엔진 작업).
- 산출물 형식 = `format="prompt_payload"`. 사람이 읽는 문서(`context_md`)가 아니라, 다음 착수에 바로 쓰는 조립 브리핑 payload다.
  - 담는 것: §8의 5요소(데이터 출처 / 구조·표시 패턴 / 확장 지점 / 규칙·함정 / 과거 결정)와 그 근거 객체 id.

### 3.2 별도 검색 레인 (사용자 결정의 핵심)

projection을 **세 번째 별도 검색 레인**으로 둔다. 이미 검증된 패턴의 재적용이다.

- 선례: `search.py`의 `_OBJECT_LANE_EXCLUDED = (RAW_KIND, INSIGHT_KIND)` — raw 청크(`raw_excerpts` 채널)와 Insight(`advisories` 채널)가 객체 레인에서 빠져 따로 융합돼 **정본 객체 적중 뒤에** 붙는다.
- projection도 같은 틀: 별도 레인 + **"재사용 후보(미검증)" 채널** + 정본 적중 뒤 노출.
- **검색 점수 계산(document frequency)에서 projection을 제외**한다. 안 그러면 projection 본문이 앵커 df 계산에 섞여 정본 회수 게이트를 흔든다(raw·Insight를 제외하는 것과 같은 이유).
- 회수 흐름: 새 개발 요구가 오면 projection 레인에서 의미검색 → 비슷한 요구의 projection을 후보로 회수 → 에이전트는 그 후보가 맞으면 §8 전체 조립을 건너뛰고 빈 곳만 보강, 안 맞거나 없으면 §8로 새로 조립.
- **status 무관 전용 채널(codex 리뷰 반영)**: candidate든 reviewed든 projection은 `eval_recall`의 정본 `results`/`candidates`가 아니라 `projection_reuse` 채널로만 나온다. `eval_recall`이 reviewed non-Insight를 전부 `results`로 보내므로(search.py:667), projection을 kind로 따로 빼지 않으면 promote 후 정본 답변에 섞인다 — 검색 점수 계산·scope 레인·정본 채널 셋 다에서 제외해야 한다.

### 3.3 생성 시점 · 검수 사다리

세 입장(사용자 "매번 안 하게" / codex "자동 저장은 정당화 안 됨, 저장 경계는 ingest 쪽" / 정본 검수 사다리)이 한 점으로 모인다:

> **§8 조립이 "한 기능으로 수렴 + 5요소가 다 참 + 구성 객체(source_object_ids) 확정"을 만족한 순간에만, 에이전트가 명시적으로 candidate(미검증) projection을 저장한다. 부분 조립이나 되묻는(clarifying) 단계에선 만들지 않는다.**

- **명시 저장**: 검색 경로(query path)가 검색 도중 저절로 저장하지 않는다. 조립을 끝낸 에이전트가 "이 브리핑은 재사용 가치가 있다"고 판단해 저장 단계를 호출한다. brain의 저장 경계(판단은 사람·에이전트, 도구는 기록만)와 일관.
- **candidate로 시작 → 사용 시점 승격(promote)**: 처음엔 미검증 후보로 노출되고, 다음 재방문에서 실제로 맞으면 reviewed로 승격한다. brain의 B+C 검수 모델(후보 노출 → 쓰면서 정확해짐) 그대로다.
  - 근거: `ContextProjection`은 status에 특별한 제약이 없어 candidate가 허용된다(`schema.py`의 ContextProjection 검증은 format·stale_policy만 본다). candidate를 막는 건 Insight 하나뿐이다(`schema.py`: "candidate Insight not supported — no recall channel"). 단 현재 빌더는 `status="reviewed"`로 박으므로, candidate 생성 경로를 빌더에 추가해야 한다.

### 3.4 낡음 · 재생성

- **1차 방어선은 재생성(rebuild) 시점**이다. 회수 시점이 아니다.
  - 이유: 회수 시점에만 거르면 낡은 projection이 이미 BM25·벡터·RRF·앵커 df에 영향을 준 뒤라 늦다(codex). rebuild에서 빼야 색인 자체에 안 들어간다.
- 메커니즘: rebuild가 색인을 만들 때, projection의 `source_content_hash`를 **현재 store로 재계산**해 일치하는지 본다. 안 맞으면(구성 객체가 supersede·변경됨) 그 projection을 **색인에서 제외 + 코퍼스 지문 계산에서도 제외**한다.
  - 재사용 부품: `lint.py`에 이미 `_compute_source_content_hash(store, source_object_ids)`가 있고, projection의 `source_content_hash` 불일치를 stale 신호로 검사한다(`manual_edit_detected` + hash mismatch). 이 판정을 rebuild 경로에서 호출하면 된다 — 무효화 로직을 새로 만들 필요가 없다.
- 회수 시점 재확인은 **보조 방어막**으로만 둔다(1차 방어선이 막은 뒤의 안전망).
- **reviewed projection은 같은 id로 재생성하지 않는다(정책 A: 재검증 강제, 2026-06-17 codex 합의)**. reuse projection의 reviewed는 "이 요구에 이 브리핑이 맞다"는 사용 시점 promote 판단의 산물이라, 구성 객체가 바뀌면 그 판단이 무효다. 새 브리핑은 candidate부터 다시 검수받는다 — reviewed를 둔 채 본문만 덮는 것(reviewed 유지 갱신)을 막는다.
  - 메커니즘: `build_reuse_projection`은 항상 `status="candidate"`를 만들고, `ingest` 후퇴 가드가 reviewed→candidate 강등을 거부한다(`ingest.py`). 그래서 기존이 reviewed면 `--replace`로도 같은 id 재생성이 막힌다. `cli.py` `_run_projection`은 그 후퇴 가드의 불친절한 메시지 전에 "재검증 강제·§8 재조립" 안내를 준다.
  - context_md 빌더(`build_context_projection`)가 `status="reviewed"` 고정이라 자유롭게 재생성되는 것과 다르게 취급한다 — context_md는 사람 판단이 안 들어가는 기계적 전량 덤프라 reviewed가 항상 정당하지만, reuse는 LLM이 추린 부분집합 + 서술이라 사용 시점 판단이 들어간다.
  - 안전성: 낡은 reviewed projection은 위 stale 거르기로 색인에서 이미 빠지므로 잘못 재사용될 위험은 없다(store에 죽은 채 남아 자리만 차지). 갱신이 실제로 필요해질 때의 메커니즘은 §7 후속 과제.

### 3.5 기각된 대안과 사유

- **답변 텍스트 캐시**(사용자 최초 아이디어): 정본 §2 "AI 유지보수 문서 층 금지" 충돌 + 무효화 추적을 새로 만들어야 함(어떤 객체가 답변에 들어갔는지 역추적) + 질문→캐시답변 검색이 기존 질문→객체 검색과 이중화. 3자(사용자·codex·정본) 합의로 기각.
- **새 briefing kind를 정본으로**: 객체 그래프 옆에 "답변 그래프"를 또 운영하게 됨(codex). 기각.
- **Insight에 브리핑 얹기**: Insight는 candidate 금지 + advisories(경고) 성격이라 일반 착수 브리핑 그릇이 아님(`schema.py`). 기각.
- **CurrentView 사용**: `source_fact_ids`/`source_event_ids` 중심이라 DomainMapping·GlossaryTerm·DecisionRecord를 엮는 착수 브리핑과 구조가 안 맞음(`schema.py`). 기각.
- **mapping_bundle 회수만으로 해결**: bundle 입도에 의존 — 방해버블(기능별 분리 bundle)엔 듣지만, 정작 아픈 샐리는 단일 bundle에 매핑 63개가 뭉쳐 있어 통째로 끌려와 무용. 사용자 통점을 직접 풀지 못함. 별도 보완 과제로 분리(§7).

## 4. 작업 범위

### 4.1 엔진 (project-brain 레포 — codex 협업)

> codex 합성 검증 리뷰(2026-06-17) 반영 — 정확한 작업 지점·함수명을 박았다.

1. **projection 검색 본문을 객체 필드(`reuse_payload`)에 싣기**: raw의 surface_text 운반은 store 없는 raw 전용 예외 경로이므로, store 객체인 projection은 객체 필드 → `extract_surface` → rebuild가 `documents.surface_text`를 파생 생성하는 흐름을 쓴다(codex 확인 — 두 번째 운반 경로 안 만듦).
2. **`extract_surface(ContextProjection)` 추출기 추가**(surface.py `_EXTRACTORS`): prompt_payload projection의 `title`+`reuse_payload`를 표면으로. context_md 덤프는 표면 없음(None).
3. **색인 정책 전환**: `surface.py`의 `EXCLUDED_KINDS`에서 ContextProjection 제거, `search.py`의 `_OBJECT_LANE_EXCLUDED`에 PROJECTION_KIND 추가(색인되되 객체 레인 제외).
4. **`recall()` 별도 융합 블록**: raw·Insight 융합과 동형으로 projection 레인을 따로 융합해 객체·raw 적중 뒤에 붙인다.
5. **df 계산·scope 레인에서 projection 제외**: 앵커 df는 `_OBJECT_LANE_EXCLUDED`가 아니라 **`_document_frequency`의 SQL**(현재 RAW·Insight 제외)에 projection 추가. scope 질의 누수는 **`search_bm25_scoped`**(현재 RAW만 제외)에 projection 추가 — 안 하면 scope 질의에서 projection이 객체 레인으로 샌다.
6. **요구 부분집합 candidate 빌더**(`build_reuse_projection`): context 전체 덤프가 아니라 "주어진 객체 부분집합 + 5요소 payload"를 `format="prompt_payload"`·`status="candidate"`로. **필수 필드 `projection_hash`(reuse_payload의 sha256)와 `source_content_hash`를 반드시 채운다** — 빠지면 `validate_object` 실패(codex 합성 검증 확인).
7. **`eval_recall` projection_reuse 채널 + CLI/하네스 전파**: `eval_recall`의 `results`/`candidates`에서 projection을 **status 무관 제외**하고 `projection_reuse` 채널 신설. `cli.py` `_run_search` 출력에 채널 추가(trust_label "재사용 후보(미검증)"), `eval_harness.py`가 raw/advisories처럼 채널을 인지.
8. **rebuild 낡음 거르기**: `search_index.py`의 `rebuild()`와 `compute_corpus_fingerprint()`에서 `source_content_hash`가 현재 store와 안 맞는 projection을 색인·지문에서 제외(`lint.py`의 `_compute_source_content_hash` 재사용).
9. 관련 테스트 갱신.

**promote는 별도 작업 불필요(codex 합성 실행 확인)**: `promote()`는 single_object에서 kind를 안 가리는 범용 승격기라 candidate ContextProjection이 그대로 reviewed로 승격되고 `validate_object`를 통과한다. stale candidate 승격 거부도 CLI의 merged-store lint 단계가 이미 막는다.

### 4.2 스킬 (게임 레포 `bb2-brain-query` / `bb2-brain-ingest`)
1. `bb2-brain-query` §8에 단계 추가: 회수 시 projection 레인의 "재사용 후보(미검증)"를 먼저 확인 → 맞으면 그걸 토대로 빈 곳만 보강, 없거나 낡았으면 기존 §8 조립.
2. 저장 단계: §8 조립이 "한 기능 수렴 + 5요소 참 + 구성 객체 확정"을 만족하면 candidate projection 저장(명시 호출). 부분 조립·되묻는 중엔 금지.
3. 사용 시점 promote: 회수한 candidate projection이 실제로 맞았으면 reviewed로 승격.
4. 채널 라벨: status별 분리 — candidate="재사용 후보(미검증)", reviewed="재사용 브리핑(검증됨)". 채널은 두 status 공통 `projection_reuse`로 두고 라벨만 가른다(raw_excerpts "원문 발췌(미검수)" 선례와 같은 자리).

### 4.3 정책 (생성 조건)
- 생성 트리거: 한 context로 수렴 + 5요소 충족 + source_object_ids 확정. 그 외엔 생성 안 함.
- 검수: candidate로 시작, 사용 시점 promote.

## 5. 검증 기준

- **골든셋 신규 시나리오**: 동일/유사 개발 요구를 두 번 던졌을 때, 1회차는 §8 전체 조립, 2회차는 projection 레인에서 후보 회수 → 질의 수가 유의하게 줄어드는지(예: 샐리 결과 팝업 류 요구가 2회차에 1~2질의로 수렴). 후보는 "미검증" 라벨로 노출되는지.
- **정본 비잠식**: projection 레인 도입 후에도 기존 골든셋(현재 eval 8/8)이 회귀하지 않는지 — 특히 정본 객체 핀포인트 회수가 projection 때문에 밀리지 않는지(df 제외가 작동하는지).
- **낡음 거르기**: projection의 구성 객체를 supersede한 뒤 rebuild → 그 projection이 색인·지문에서 빠지고 회수되지 않는지.
- **candidate→promote**: projection은 candidate든 reviewed든 항상 `projection_reuse` 채널로만 노출되고(**채널 이동 없음**), 라벨만 candidate="재사용 후보(미검증)" → promote 후 reviewed="재사용 브리핑(검증됨)"으로 바뀌는지. reviewed projection이 정본 `results`에 절대 안 섞이는지(승격해도 채널은 그대로).
- 엔진 전체 테스트 통과 + 실코퍼스 가드(`brain/checks`) 통과.

## 6. 데이터 흐름 (요약)

```
[1회차 — 개발 요구 도착]
  §8 조립 (분해 질의 → 원문 열람 → 5요소)
    └ 조건 충족(수렴+5요소+source 확정) → candidate projection 저장
        (source_object_ids + prompt_payload 산출물 + source_content_hash)

[색인 rebuild]
  projection 본문 → extract_surface → 별도 레인 색인 (df 제외)
    └ source_content_hash가 현재 store와 안 맞으면 색인·지문에서 제외(낡음)

[2회차 — 유사 요구 도착]
  projection 레인 의미검색 → "재사용 후보(미검증)" 회수 (정본 적중 뒤)
    ├ 맞음 → 빈 곳만 보강 + 사용 시점 promote(status만 reviewed, 채널 그대로·라벨 "검증됨")
    └ 없음/낡음/안 맞음 → §8로 새로 조립
```

## 7. 미결 · 후속 과제

- **mapping_bundle 회수 부품 승격**: 첫 적중 매핑의 `review_record_id` → ReviewRecord(`review_scope=="mapping_bundle"`)의 `target_object_ids`로 형제 매핑을 끌어오면 1회차 조립도 짧아진다. 단 bundle 입도가 좁아야 효과(샐리는 63개 단일 bundle이라 그대로는 무용). bundle을 착수 단위로 좁게 끊는 적재 규약 또는 회수 시 부분 확장 규칙이 선행 조건. 이 spec과 독립된 보완 과제.
- **projection 본문 저장 위치**: 검색용 본문을 객체 JSON 안에 둘지, 별도 산출물 파일(`output_locator`)을 surface가 읽게 할지 — 구현 시 결정(raw 청크가 `surface_text`로 본문을 운반하는 방식 참고).
- **유사도 임계**: projection 레인 회수에서 "충분히 비슷한" 후보만 노출할 컷오프 — 골든셋으로 캘리브레이션.
- **promote 권한**: 팀 공개 시 누가 projection을 reviewed로 올리는지(정본 §7 미결 5와 동일 트랙).
- **reviewed reuse projection 갱신 메커니즘**: §3.4 정책상 reviewed의 같은 id 재생성은 막혀 있다. 실사용에서 reviewed 브리핑의 구성 객체가 바뀌어 갱신이 실제로 필요해지면, "삭제 후 재생성"이 아니라 **"기존 reviewed를 superseded/archived로 남기고 새 revision id를 만드는 정책"**으로 설계한다(codex 제안). 삭제가 단순하지 않은 이유: `BrainStore`에 삭제 API가 없고(`store.py`는 save_object만), reviewed projection을 지우면 그 `ReviewRecord`가 dangling이 되어 lint 8e가 잡으며(`lint.py`), supersede/EventLedger 정책까지 함께 정해야 한다. 또한 promote(`_run_promote`)에는 ContextProjection을 막는 kind 화이트리스트가 없어, stale/미검증 candidate projection을 성급히 reviewed로 굳히면 위 갇힘 상태로 직행한다(stale은 merged-store lint가 막지만, fresh-but-premature 승격은 절차로만 방지). **트리거 = 실제 stale reviewed reuse projection 갱신 요구 발생**(현재 reviewed reuse projection 0개라 미발생).
- **정책 A의 적용 범위와 본문 무결성 한계 (적대검증 2026-06-17 식별)**: §3.4 정책 A의 reviewed 재생성 차단은 `build-reuse` CLI 경로(`_run_projection`)에만 강제된다. 범용 `cli ingest`(`_run_ingest`)는 brain의 도메인 무지 저장 모델(멱등 갱신 + 신뢰된 적재 에이전트)을 따르므로, 손수 만든 JSON에 [같은 id + status=reviewed + 바뀐 reuse_payload + 재계산 projection_hash + 동일 source_content_hash]를 넣으면 schema·lint·후퇴 가드를 전부 통과해 reviewed 브리핑 본문이 검수 없이 교체된다. 이는 (a) 정책 A 추가 전후 동일하고 reuse projection만이 아니라 **모든 kind 공통**이며, (b) "실수 방지"가 아니라 "권한 주체의 의도적 검수 우회"라 brain 범위 밖이다(ingest 경계 보존은 §4.1·Q2 결정과 일관 — codex 동의). 단 **reviewed ContextProjection의 본문 무결성(reuse_payload ↔ 검수 산출물 일치)을 lint·schema 어디서도 검증하지 않는다**는 점은 기록해 둔다(reuse_payload는 source에서 파생 안 되는 자유 텍스트라 source_content_hash 신선도·dangling 검사로 안 잡힘, `review_record_id`도 schema 필수 아님). 강제가 필요해지면 reviewed ContextProjection의 `review_record_id` 필수화 + projection_hash↔검수 시점 기록 대조를 별도 후속으로. **트리거 = 팀 공개 등으로 "신뢰된 적재 에이전트" 가정이 약해질 때**.

## 8. 출처

- 사용자 발언(2026-06-17): "projection은 별도 검색층으로 둬야 하지 않을까" 외 방향 결정. (발언 원장에 추가 대상)
- codex(project-brain) 5턴 브레인스토밍 로그(이 세션).
- 엔진 코드 직접 검증: `schema.py`, `surface.py`, `search.py`, `search_index.py`, `context_projection.py`, `lint.py`, `promote.py` (project-brain 레포, 이 세션).
- 정본 [[bb2-project-brain]] §2(철학)·§3(층 구조)·§7(미결).
