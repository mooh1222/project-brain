# BB2 Brain 검색층(회상 색인) 설계 — 1차 마일스톤

- 상태: **draft** (적대 리뷰 전)
- 작성: 2026-06-10. 근거: 정본 `vault wiki [[bb2-project-brain]]` §6 + 사용자 발언 원장(`vault inbox/dumps/bb2-brain/2026-06-10-user-statement-ledger.md`) + 이 세션 코드·환경 실측
- 선행 결정(인터뷰 Q4·Q5): 구현 순서는 검색 먼저, 1차 마일스톤 = 검색층 + 샐리 카누 회상 통과

## 0. 목적·통과 기준

**목적**: "단어 일치만 되는 건 사전이지 브레인이 아니다"(사용자 06-08)를 해소한다 — 기억이 안 나고 **맥락만 던져도** brain이 의미 기반으로 관련 객체를 찾고, 검수 상태·근거·코드 위치와 함께 답하게 한다.

**통과 기준** (§8 평가 하네스로 측정):
1. 실패했던 실측 시나리오 재실행 통과 — jira 티켓(LGBBTWO-4570급) 텍스트를 주면 관련 코드 위치를 top-5 안에 핀포인트 (06-05 실측은 110개 무더기 반환으로 실패).
2. 용어가 정확히 일치하지 않는 의미 질의("레이스 끝났는데 보상 못 받았대" 류)에서 관련 객체 회상.
3. 기존 라우터 보장 유지 — 검수 상태 표시, 근거 링크, 기록 없으면 없다고 답함, 전 테스트 green.

## 1. 현재 상태 (2026-06-10 실측)

- **매칭**: 정확 부분 문자열뿐 — `term in query` (router.py:347-362 reviewed 용어, :364-377 candidate 용어 term/synonyms/aliases, :379-397 매핑의 용어 표면). 쿼리에 등록된 표면이 글자 그대로 들어있어야만 매칭.
- **의도 분류**: 키워드 규칙 (intent.py:33-50, "왜"/"현재"/"그때"/"어디 구현"/"무슨 뜻"/"근거"). 이 분류 자체는 결정론으로 **유지한다** — 문제는 분류가 아니라 회상(찾기).
- **갭**: 의미 검색 0 / 형태소 처리 0 / 점수 기반 좁히기 0(스코프 못 좁히면 전량 반환) / raw 색인 0.
- **코퍼스**: 객체 571개, 그중 **색인 대상은 302개**(GlossaryTerm 125 + CodeLocator 110 + DomainMapping 64 + DecisionRecord 2 + DomainContext 1 — EvidenceRef 165·ReviewRecord 104는 §2.1 색인 제외). per-file JSON (`scripts/bb2_brain/brain/objects/`). ★표면 분포: GlossaryTerm term의 78%(98/125)가 영문 심볼/약어(targetStages, COOLTIME 등) — 한국어 질의↔영문 term 연결이 이 코퍼스의 핵심 난제(§6·§11)★ (리뷰 실측 2026-06-10).
- **06-05 "110개 무더기"의 정확한 원인**: implementation_location intent가 reviewed CodeLocator **전량(110개)을 스코프 필터 없이** source로 적재(router.py:191-211) — 토크나이저가 아니라 source 적재 구조의 문제이며, §7이 이 적재 로직 자체를 바꿔야 해결된다 (리뷰 정정).
- **환경 실측**: bge-m3 임베딩 모델이 이 머신에 이미 존재(vault-embed-server가 동일 모델 사용 중) / auto_worker venv에 sentence-transformers 5.4.1·sqlite-vec 0.1.9·torch 설치됨 / brew에 mecab·mecab-ko·mecab-ko-dic 설치됨(HwiCortex 사용 경험, 사용자 05-29 직접 설치). **추가 대형 다운로드 없이 hwi_PKM급 스택 구성 가능.**

## 2. 색인 대상

### 2.1 객체 (1차 범위)

kind별 **텍스트 표면 추출 함수**를 둔다 (구현 시 schema.py `KIND_REQUIRED` 기준으로 필드 확정):

| kind | 색인할 텍스트 표면 (예시) |
|---|---|
| GlossaryTerm | term, synonyms, aliases, avoid, definition, boundary |
| DomainMapping | meaning, boundary, canonical_summary + 참조 용어의 term/synonyms (현 라우터의 표면 위임 로직 계승) |
| DecisionRecord | 결정 내용·이유 텍스트 필드 |
| TemporalFact / EventLedgerRecord / CurrentView | subject·predicate·value·summary 류 텍스트 필드 (데이터는 현재 거의 0 — 적재되면 자동 포함) |
| CodeLocator | path + symbol (예: "SallyCanoePopupEnterRaceInfoNode onClickNewRace" — 심볼명 질의 대응) |
| DomainContext | display_name, boundary_summary |
| EvidenceManifest/EvidenceRef/ReviewRecord/ContextProjection | **색인 제외** — 근거·검수 기록은 그래프(§3.5)로 따라가는 대상이지 검색 표면이 아님 |

각 색인 행에 메타 동반: `object_id, kind, status(candidate/reviewed), context_id, content_hash`.

### 2.2 raw — ✅ 적용 완료 (2026-06-11, P4)

기획서 md 원문(`brain/raw/sources/<context>/*.md` — P1 규약)을 헤더 기준 chunk(과대 섹션은 문장 경계 분할 + 15% 겹침, hwi_PKM 청커 채택 — 500토큰 근사·완전 결정론, `raw_chunks.py`)로 같은 색인에 넣는다. 행 메타 `kind=raw_chunk, status=raw, context_id=context.<디렉토리>`, 원문은 `documents.surface_text`(스키마 v3)가 운반(store에 없는 행). 검색 결과에서 raw는 "원문 발췌(미검수)"로 구분 표시 — 지식 객체와 신뢰 등급이 다름(Q1 결정).

구현 시 확정된 설계 3건(2026-06-11, 사용자 결정=cli search 셋째 채널까지·라우터 answer는 객체 전용):
- **별도 레인**: recall은 채널 검색을 3배 과대 적재 후 kind로 갈라 객체 레인(top50/30 — 융합·그래프·재정렬)과 raw 레인(top50/융합 10)을 분리한다 — 한 레인에 섞으면 기획서 청크가 융합 top-30의 객체 자리를 잠식해 그래프 상호지지 재정렬(s1·s2)이 약해지는 회귀가 실재.
- **게이트**: raw 채널은 바닥(candidate 수준)만, ★앵커 미적용★ — 앵커는 단정 답 채널용 보정이고 raw 레인의 존재 이유가 "객체화 안 된 기획서 서술 회수"(객체화 경계 규약)라 객체 코퍼스 앵커로 막으면 본말전도. 앵커 df 계산(`_document_frequency`)은 raw 행 제외 — §7 보정(상한 30)이 객체 분포 기준이라서.
- **채널**: eval_recall/`cli search`에 `raw_excerpts`(top-5, 항목마다 trust_label) 신설. needs_clarification 판정에는 불참(발췌는 단정 답이 아님). 골든셋 s7(기획 배경·의도 질의 → raw 회수, 프리픽스 판정)이 가드 — 7/7 실측.

## 3. 검색 파이프라인

`recall(query, scope?) → RecallResult` 5단계. hwi_PKM·HwiCortex와 같은 하이브리드 골격(BM25+벡터+RRF)을 쓰되, **색인 대상이 검수 상태·근거가 붙은 객체라는 점이 차별**(정본 §6).

1. **쿼리 정규화**: 기존 avoid_map canonical 보정(intent.py 경로 유지) → 형태소 토큰화(§6).
2. **BM25**: SQLite FTS5. 한국어는 **사전 형태소 분리 후 공백 결합 텍스트를 색인**(pre-tokenized column + unicode61) — 색인과 쿼리가 같은 토크나이저를 쓰면 FTS5 커스텀 토크나이저 없이 동작. top 50. ★scope가 단일 특정되면(infer_scope 또는 명시) 객체 레인은 FTS5 전역 점수 대신 **scoped BM25**(후보 집합 context_id=scope·raw 제외 안에서 df·avgdl 재계산, `search_bm25_scoped`)로 바뀐다 — 전역 df 오염 면역(2026-06-12 s1 회귀 해법. raw 레인은 전역 유지).★ ★infer_scope 자체의 단일 특정 판정은 "구체 표면 우선"(2026-06-12 이어서 23): 매칭 표면이 다른 매칭의 진부분집합이면 제거하고 maximal만 세어 판정 — 시스템/기능 표면 중첩("방해버블"⊂"고슴도치 방해버블") 시 다중매칭 scope 상실 방지. 상세 시스템도메인 설계 §3.★
3. **벡터**: bge-m3(1024차원, L2 정규화) + sqlite-vec vec0 KNN. scope 필터는 over-fetch(top×4, 최소 200) 후 후처리 — vec0가 WHERE를 못 받는 제약(hwi_PKM과 동일 처리). top 50.
4. **RRF 융합**: `score = Σ 1/(60 + rank)`, k=60(업계 표준, hwi_PKM·HwiCortex·hindsight 동일). 동점은 object_id 정렬로 결정론 tie-break. top 30.
5. **그래프 확장(1-hop)**: 적중 객체에서 참조 필드를 따라 **코드 위치·근거·연결 객체를 결과에 동반**시킨다. jira→코드 핀포인트가 이 단계에서 완성된다(매핑 적중 → code_locator 동반 반환 — 실측: 매핑 64개 중 58개가 code_locator_ids 보유).
   - **엣지 필드(전부 optional — 없으면 건너뜀)**: `glossary_term_ids`(65건) / `code_locator_ids`(64건) / `decision_record_ids`(64건, 단 값은 빈 배열 많음) / `affected_glossary_term_ids`(2건) / `affected_mapping_ids`(**현재 0건** — router.py:131이 읽는 필드라 엣지로 유지하되 데이터 부재 명시). 필드명은 전부 실코퍼스 대조 완료(2026-06-10 리뷰). 핀포인트 품질이 참조 데이터 완비도에 좌우됨을 §8 측정이 드러내게 한다.
   - **`evidence_refs`는 표시 전용**: 전 객체(571/571)가 가진 보편 필드라, 동반 표시(`linked.evidence_ref_ids`)에만 쓰고 **랭킹·가산 입력에서는 제외** (안 그러면 EvidenceRef 165건이 랭킹을 오염).
   - **가산점은 점수 합산이 아니라 분리 신호**: RRF 점수(스케일 ~0.016-0.033)에 임의 상수를 더하지 않는다. 그래프 도달은 `graph_reached: true` 표식 + 도달 횟수로 분리해 두고, 재정렬에 쓸지·계수는 §8 캘리브레이션 대상. 결정론(§5)을 지키기 위해 재정렬 규칙도 동점 시 object_id 정렬 유지.

**결과 계약** (라우터·어시스턴트가 소비):
```
RecallResult = [{
  object_id, kind, status,            # 검수 상태가 항상 동반 — candidate면 후보 표시
  score, matched_via,                 # bm25 | vector | both (+graph)
  surface,                            # 매칭된 텍스트 표면
  linked: { code_locators: [...], evidence_ref_ids: [...], related_object_ids: [...] }
}]
```

**(P1, 비범위) 재랭커**: bge-reranker-v2-m3 cross-encoder는 1차에서 넣지 않는다 — §8 측정에서 정밀도가 부족할 때만 추가(모델 2.1GB 추가 다운로드·지연 비용 대비 효과를 실측으로 판단).

## 4. 저장·재생성

- 색인 DB: `scripts/bb2_brain/.brain-local/index.db` (**gitignore — 구현 시 .gitignore 신설**). 검수 데이터(brain/)=공유 후보, 색인=로컬 파생물이라는 Q3 경계와 정합. 정본 미결 3(공유/로컬 분리 규약)의 첫 실물이 **된다** — 현재는 brain/ 전체가 미추적이라 경계 자체가 아직 실재하지 않음(리뷰 정정).
- 테이블: `documents(object_id PK, kind, status, context_id, content_hash, tokenized_text)` + `documents_fts`(FTS5) + `documents_vec`(vec0 FLOAT[1024]) + `meta(schema_version, embed_model, tokenizer, extractor_version)`. (2026-06-10 슬라이스 2 리뷰 정정: 초안 DDL이 §2.1 행 메타의 context_id를 빠뜨린 내부 모순 — §2.1 쪽으로 정합. 슬라이스 3+의 scope 후처리가 store 재로드 없이 행만으로 거르는 데 필요.)
- **재생성 가능 = 1급 불변조건**: `cli index rebuild`가 brain/ 객체에서 전체 재구축. DB 삭제는 데이터 손실이 아니다(v0부터의 원칙 — 색인은 SoR 아님).
- **content_hash 정의(리뷰 반영 — 객체 모델에는 이 필드가 없으므로 신설 개념임을 명시)**: 객체 JSON이 아니라 **추출된 텍스트 표면(§2.1) + status**의 SHA-256. **색인 DB의 documents 행에만 저장**, brain/ 객체는 불변(스키마 변경 없음). 이렇게 하면 updated_at만 바뀌는 멱등 재저장은 재색인을 유발하지 않고, 추출 함수가 바뀌면 `extractor_version`(meta) 불일치로 전체 rebuild가 트리거된다.
- **증분**: content_hash 비교로 변경분만 재색인. `cli ingest`/`promote`의 save 이후에 **신규 후처리 단계로** 증분 갱신 훅 추가(현재 두 파일에 후처리 자리 없음 — 구현 시 신설. 실패는 경고만: 진실은 brain/, 색인은 따라가는 캐시).
- 임베딩 모델·토크나이저·추출기 버전을 meta에 기록 — 불일치 감지 시 rebuild 안내.

## 5. 임베딩 실행 형태

- **모델: bge-m3 로컬** (sentence-transformers 직접 lazy 로드). 근거: (a) 이 머신에 모델 캐시 실존(`~/.cache/huggingface/hub/models--BAAI--bge-m3`, 리뷰 실측 — 추가 다운로드 0), (b) hwi_PKM 동일 모델로 한국어 포함 실증, (c) API 키·네트워크 의존 0 → 재현성. vault-embed-server 재사용은 **비채택** — vault 생명주기에 brain이 묶이는 결합을 피한다(모델 캐시는 공유되므로 비용 중복 없음).
- **실행 인터프리터(리뷰 반영 — "0추가" 주장의 정정)**: 패키지(sentence-transformers·sqlite-vec·torch)는 **auto_worker venv(py3.11)에만** 있고, 워크스페이스 기본 python3(3.14)에는 없다. brain 검색층의 실행·테스트 인터프리터는 **auto_worker venv를 기본**으로 한다(전역 Python 규칙과 정합). 모델 캐시(HF)는 인터프리터와 무관하게 공유되므로 "대형 다운로드 0"은 유지되나, 인터프리터 전제는 §11 실검증 항목.
- **테스트 결정론**: env 플래그로 stub embedder(텍스트 SHA-256 시드 가짜 벡터) — 모델 없이 테스트가 결정론적으로 돈다(hwi_PKM 패턴 차용). **stub는 회귀 가드 전용이며 의미 회상 품질은 원리적으로 검증 못 한다** — 품질 검증은 §8 실모델 측정(슬라이스 3 직후 1차 게이트, §10).
- **실모델 결정론 한계(리뷰 반영)**: 임베딩 부동소수점은 환경(스레드·BLAS)에 따라 하위 비트가 흔들릴 수 있다 — 거리값을 고정 소수자리(예: 1e-6)로 반올림한 뒤 동점 tie-break(object_id)에 들어오게 해 top-K 경계 흔들림을 줄인다. torch 스레드 수 고정을 평가 하네스에 명시.

## 6. 한국어 형태소 토크나이저

- **벤치마크 두 시스템의 선택이 갈림(기록)**: **HwiCortex = mecab-ko**(qmd fork, brew 본체+사전 필요) / **hwi_PKM = Kiwi(kiwipiepy)**(`korean` extra, 순수 pip wheel — 시스템 의존성 없음). 같은 개발자가 후속작에서 Kiwi로 간 것은 설치 용이성 때문으로 추정(미확인).
- **우리는 mecab-ko 1순위 채택**: brew로 본체+사전이 이미 설치돼 있고(리뷰 실측: `/opt/homebrew/bin/mecab`, ko-dic 0.9.2), 사용자가 직접 설치·해결 경험(05-29 "install-mecab-ko-dic 사용하면 해결됐어"). python 바인딩(mecab-python3 또는 python-mecab-ko)은 구현 시 사전 경로 연결이 되는 쪽으로 확정.
- **2순위 폴백 = kiwipiepy**: mecab 바인딩 연결이 실패하면 정규식으로 떨어지기 전에 kiwipiepy를 시도한다 — pip 설치만으로 동작(시스템 의존 0)하고 hwi_PKM이 실증한 선택이라, 품질 손실 없는 대체가 가능. 어느 쪽이든 색인 meta에 기록(§4).
- **영문 심볼 토큰화 = 한국어와 동등한 1급 항목(리뷰 반영)**: 색인 표면의 78%가 영문 심볼이므로(§1) 심볼 분리 규칙을 명문화한다 — camelCase(`onClickNewRace`→`on click new race`+원형) / snake_case·대문자(`SALLY_CANOE_RACE_STATUS`→토큰 분리+원형) / `::` 구분자 분리. **색인과 쿼리가 같은 토큰화 함수 하나를 공유**(대칭 보장 — 쿼리 쪽만 다른 분리를 하면 매칭 깨짐).
- **FTS5 질의는 phrase/prefix를 쓰지 않고 토큰 OR 매칭만** 사용한다(hwi_PKM 멀티워드와 동일) — 형태소+심볼 토큰이 한 컬럼에 섞여도 phrase 경계 문제가 생기지 않게 하는 의도적 단순화. 정밀도는 RRF·(P1)재랭커 몫. (2026-06-10 슬라이스 2 리뷰 자구 보강: 구분자를 품은 복합 원형 토큰(`a/b/c.cpp`, `x::y`)은 개별 인용해도 unicode61이 재분리해 사실상 phrase로 해석된다 — 같은 tokenize()가 조각 토큰을 항상 OR로 동반시키고 색인측도 동일 전개라 재현율 손실·비대칭 없음을 실측 확인. 이 문장의 의도("phrase 경계로 인한 매칭 실패 방지")는 그대로 성립.)
- **폴백**: 바인딩 로드 실패 시 정규식 분리(한글 연속/영숫자 연속)로 동작하되 경고. **색인·쿼리 비대칭 발동이 진짜 위험**(배치 색인과 쿼리가 다른 환경에서 돌 때) — 토큰화는 단일 모듈 함수로만 제공하고, 색인 meta의 tokenizer 기록과 쿼리 시점 토크나이저가 다르면 결과에 경고를 박는다(§4 meta 활용).

## 7. 라우터 통합

- **의도 분류는 유지** (결정론, intent.py). 바뀌는 건 회상 경로:
  - `_matched_glossary_terms / _matched_candidate_terms / _matched_mappings`의 정확 부분 문자열 매칭은 **1순위 경로로 보존**(정확 일치가 있으면 가장 신뢰), `recall()`이 그 뒤를 **의미 확장**으로 보강.
  - **전량 적재 → top-K 전이 규칙(리뷰 반영)**: 무더기 반환의 원인은 intent별 source 적재가 reviewed 전량을 무조건 싣는 구조(implementation_location: CodeLocator 110개 전량 router.py:191-211 / glossary_meaning: DomainContext+GlossaryTerm 전량 router.py:229-232). 이 적재를 **recall 점수 top-K(기본 5)**로 교체한다. 이는 **의도된 행동 변경**이며 "기존 테스트 보존"의 예외 — 실측상 전량 적재를 고정하는 기존 테스트는 0건(리뷰 확인)이라 충돌 없고, needs_clarification이 `(not source_ids)`에 의존하는 부분은 아래 게이트 식으로 대체한다.
- **답변 게이트 = 단일 임계가 아니라 다신호(리뷰 반영)**: 의미 점수 하나로 "있다/없다"를 가르면 시나리오 3(적중)과 5(거짓 양성 가드)를 동시에 만족 못 한다. 게이트 신호 3개 — (i) RRF 절대 점수 (ii) 1등-2등 점수 차(margin) (iii) **정확/근접 표면 매칭 유무(BM25 토큰 일치)**. "존재하지 않는 엔티티" 질의는 (iii)=0이 우선 신호로 needs_clarification을 켠다. 계수는 §8 캘리브레이션 대상. (2026-06-10 슬라이스 5 캘리브레이션 결과: (iii)은 "표면 앵커" — 질의의 코퍼스 존재 내용 토큰 중 가장 희소한 것의 문서 빈도(anchor_df)로 정밀화, 상한 30(견고 구간 18~51의 중앙, s1~s4 anchor_df 1·17·6·5 vs s5 52). (ii) margin은 boolean 게이트에서 **제외하고 진단·보고 전용** — 실측에서 s5의 margin(0.0119)이 5개 시나리오 중 최대(외로운 허위 적중이 1등일수록 margin이 커짐)라 "margin 크면 확신"이 역작동. (i)는 채널별 바닥(reviewed 0.005/candidate 0.001)으로 degenerate 약한 적중 방어만 담당.)
  - **unknown 일반 회상 경로의 needs_clarification 산출식 명시**: `needs_clarification = (게이트 통과 결과 0건)`. recall이 항상 top-K를 반환하더라도 게이트를 못 넘으면 source에 싣지 않는다 — "no evidence → 없다" 규약이 이렇게 보존된다.
  - **candidate/reviewed는 게이트를 분리**: candidate는 source가 아니라 별도 후보 채널(기존 C 정책의 promotable_candidate_ids·"확인 필요" 라벨)로 노출하므로, reviewed보다 관대한 임계를 써도 "확신 답변" 오염이 없다 — "후보 노출이 안 되면 승격 기회가 영영 없음"(06-05)과 거짓 양성 가드를 채널 분리로 동시 충족.
- **일반 회상 신설**: intent가 `unknown`(맥락만 던진 질의)일 때 recall 결과로 답하는 경로 추가 — "bb2-brain은 너가 사용해서 나에게 알려주는거야"(06-09)의 핵심 사용 모델. 결과는 검수 상태별로 구분 표시(reviewed=확신 / candidate=후보 — 기존 C 정책 계승).
- CLI: `cli search "<query>"` (어시스턴트가 직접 쓰는 회상 명령), `cli index rebuild`. **명명 주의**: 기존 테스트 `test_e2e_cli_recall`(test_universal_ingest_e2e.py:548)은 옛 키워드 라우터의 회귀 테스트 — 새 API를 `recall()`로 두되 기존 테스트 이름과 역할 혼동이 없도록 구현 시 주석/이름 정리.

## 8. 평가 하네스

시나리오 파일(질의 → 기대 object_id/코드 경로) 기반 `cli eval`(또는 pytest 마커). **실 코퍼스 + 실 모델**로 측정.

| # | 시나리오 | 통과 기준 |
|---|---|---|
| 1 | LGBBTWO-4570 티켓 원문(2026-06-10 jira 실확인: "2단계 오픈 팝업과 실제 플레이 스테이지 개수가 다른 문제" — 팝업 5개 vs 이벤트 페이지 7개) | **매핑 `mapping.sally-canoe.alert-popups-start-alert`(한국어 표면 보유, reviewed)가 top-5에 적중하고, 그래프 동반으로 용어(`g.sally-canoe.alert-popups-start-alert-target-stages`, term=targetStages)·CodeLocator가 따라옴**. 무더기 반환 없음. ★주의: 용어 term이 영문이고 synonyms가 비어 있어 용어 직접 적중은 벡터 단독 의존(미검증 가설) — 매핑 경유가 1차 경로, 직접 적중은 측정 항목(§11 분기)★. DecisionRecord 동반은 기대하지 않음(해당 매핑 decision_record_ids=[] 실측) |
| 2 | "샐리 카누 레이스 레인 a에 이슈" | 매핑 `racing-main-page-race-area-lanes`(reviewed, 실존 확인)+그래프 동반 코드 위치 top-5 ("lane-index"라는 용어는 코퍼스에 없음 — 리뷰 정정. 기대 object_id는 슬라이스 1에서 실코퍼스로 확정) |
| 3 | 표면 불일치 의미 질의 (예: "레이스 끝났는데 보상 못 받았대") | finish-reward/error-code류 객체 top-5. ★해당 에러코드 용어들(NO_REWARD 15207 등)은 **candidate**(위키-only 근거) — candidate 채널(관대한 임계)로 노출되는 것이 통과이며, reviewed source 채널 기준이 아님(§7 채널 분리)★ |
| 4 | 코드 심볼 질의 ("onClickNewRace 왜 바뀌었어") | 기존 why_changed 동작 보존 + recall 병행 |
| 5 | 기록에 없는 것 ("크리스마스 이벤트 보상") | "없다" 답변 유지. ★코퍼스에 '보상' 객체가 다수 실존하므로 의미 유사도만으로는 못 거름 — §7 다신호 게이트(표면 매칭 0 + margin)가 작동해야 통과★ |

측정값: top-5 적중률, 반환 개수 상한 준수, (참고) 쿼리 지연. 시나리오는 측정 가능해야 하므로 구현 첫 슬라이스에서 하네스부터 만든다(목표 주도, 기존 작업 원칙).

게이트 계수(§7 다신호: 절대 점수·margin·표면 매칭)와 그래프 재정렬 계수(§3.5)는 사전에 정하지 않고 **시나리오 5(거짓 양성 가드)와 1~3(적중) 사이에서 캘리브레이션**한다 — 단일 스칼라 임계가 아니라 다신호라서 이 동시 만족이 가능해진다(리뷰 반영: '보상'처럼 표면을 공유하는 거짓 양성은 점수가 아니라 표면 매칭 신호로 갈라야 함). 결과는 스펙이 아니라 코드 상수+테스트로 고정.

## 9. 비범위 (이 스펙에서 안 하는 것)

- 재랭커(P1 — ★정책 확정 2026-06-12★: **scope 미특정 넓은 질의 전용(조건부)**. scope 특정 질의는 scoped BM25(§3.2)가 df 면역을 결정론으로 보장하므로 재랭커를 겹쳐 돌리지 않는다 — hwi_PKM의 "항상 ON"은 scoped 레인이 없는 구조의 선택. 위치는 RRF top30 뒤(재랭커 점수 1순위 + graph_support 동점 키 — 결합 계수는 도입 시 캘리브레이션). **선행 조건: 골든셋에 scope-None 넓은 질의 시나리오(s8) 추가** — 측정 수단 없는 도입 금지(§8 원칙). 트리거: s8 FAIL 또는 scope-None 질의 품질 저하 실측. 리스크: bge-reranker-v2-m3 2.1GB + Metal 4GB 제약(embedder 배치 사망 실측 2026-06-11 전례) — 도입 시 메모리·지연 실측 필수), ~~raw 본문 색인 적용~~(✅ 2026-06-11 §2.2 적용 완료), 그래프 멀티홉/그래프 DB, `IndexRecord` kind 활용(이 색인은 brain 객체로 저장하지 않음 — kind 자체의 존폐는 후속 재검토), 적재 자동화, 개인 메모리 층, vault 검색과의 통합.

## 10. 구현 슬라이스 (TDD 순서)

1. **평가 하네스 골격 + 시나리오 파일** (실패하는 기준 먼저. 기대 object_id는 실코퍼스로 확정)
2. 토크나이저(mecab+폴백+심볼 분리, 단일 공유 함수) + 객체 텍스트 표면 추출 + FTS 색인 빌드 + `cli index rebuild` — 첫 작업: sqlite FTS5·확장 로드·mecab 바인딩을 실행 인터프리터(auto_worker venv)에서 실검증(§11)
3. 벡터 색인(stub embedder 테스트) + RRF 융합 + `recall()` 결과 계약
3.5. **1차 실모델 측정 게이트(리뷰 반영)**: 슬라이스 3 직후 §8 골든셋을 실모델로 1회 측정 — 의미 회상(스펙의 존재 이유)은 stub로 원리적으로 검증 불가하므로, 라우터 통합 전에 cross-lingual 가설(§11)을 먼저 판정해 fallback 분기를 조기에 태운다
4. 그래프 1-hop 동반 반환
5. 라우터 통합(보강 경로 + unknown 일반 회상 + 다신호 게이트 + top-K 좁히기) — 기존 89 tests green 유지(전량 적재 의존 테스트는 실측 0건. 벡터 의존이 없는 환경에서도 기존 테스트는 조건부 import로 무영향이어야 함)
6. 실 모델로 §8 전체 측정 → 통과 판정 (미달 항목은 재랭커 등 P1 검토 입력)

## 11. 리스크·미결 연결

- **★cross-lingual 회상 가설(리뷰 critical 반영)★**: 한국어 질의 ↔ 영문 term(코퍼스의 78%)의 직접 연결은 벡터 단독 의존 = **미검증 가설**. 1차 경로는 한국어 표면을 가진 매핑 적중 → 그래프 동반(§8 시나리오 1)이고, 슬라이스 3.5 측정에서 직접 적중이 부족하면 분기: (a) **용어 synonyms에 한국어 표면 보강**(소량 데이터 보강 — 적재 가이드와 연결, 1차 범위 내 허용) (b) 재랭커 조기 투입(P1 앞당김). 이건 리스크가 아니라 계획된 분기.
- **sqlite 환경 전제 실검증 필요(슬라이스 2 첫 작업)**: **실행 인터프리터 = auto_worker venv(py3.11)** 기준으로 — (a) sqlite3 FTS5 포함 여부 (b) 확장 로드(`enable_load_extension` — sqlite-vec 필수) (c) mecab 바인딩 설치·사전 연결. 긍정 신호: 같은 머신의 vault sqlite-vec 파이프라인이 동작 중(단 vault는 py3.14 별도 환경 — 인터프리터별 재확인 필수, 리뷰 정정). §2.1 kind별 필드명도 이때 schema.py로 실확정.
- mecab python 바인딩·사전 경로 연결이 환경 의존 — 슬라이스 2에서 가장 먼저 실검증, 안 되면 폴백으로 진행하고 품질 영향을 §8에서 측정.
- **코퍼스 성장 재방문 트리거(리뷰 반영)**: top50/30/5 상수는 571객체(색인 302) 기준 — 2차(5.5 전부 적재)로 코퍼스가 커지면 고정 top-K의 회수율이 떨어지고 무가중 RRF의 한계가 드러남. **2차 적재 시작 시 top-K 상수·재랭커 필요성을 재평가**한다(설계 부채로 명시). → ★1차 재방문 완료(2026-06-12)★: s1 핀포인트 회귀(normal-honor 적재의 정당한 어휘 중첩 — 두 번째 회귀 신호)로 트리거 도달 → **scoped BM25 도입으로 해소**(§3.2). 그래프 동점 처리 보강 후보는 **안 함** 결정 — scoped BM25가 동점 입력(RRF 순위)을 scope 질의에서 안정화하고, scope-None 동점은 재랭커 도입 시 재랭커 점수가 1순위 키가 되며 자연 해소. top-K 상수는 유지(7/7 복구 시 추가 변경 불요). 재랭커는 §9 확정 정책(조건부+s8 선행)대로 보류.
- bge-m3 로드 시간(초회 수 초~수십 초) — 색인 빌드는 배치라 무관, 쿼리 경로는 lazy 로드 후 상주(어시스턴트 사용 패턴상 세션 내 반복 질의).
- candidate 노출 정책(C)과 의미 검색의 상호작용 — 의미 확장으로 candidate가 더 자주 보이게 됨. 이는 의도된 방향("후보도 노출돼야 승격 기회", 06-05)이나 노이즈가 심하면 임계로 조절.
- 정본 미결 2(raw 영역)·미결 3(공유 경계)은 이 스펙의 §2.2·§4가 첫 입력이 됨.
