# #58 자동 벡터 재사용 구현 검증

계약: [#57](https://github.com/mooh1222/project-brain/issues/57),
구현: [#58](https://github.com/mooh1222/project-brain/issues/58).
시작 기준점은 `bb0f633cde97551494c9044138d86e590e0fd967`이다.

## 구현

기존 `index rebuild` 입력을 유지한다. 마지막 정상 live index를 읽기 전용으로 열어
완전성과 embedder identity를 확인하고 exact `surface_text`의 벡터만 현재 row ID에 복사한다.
miss는 한 번의 `embed_many` 호출로 계산한다. 새 documents·FTS 전체 재조립과 기존
lock·검증·fsync·원자 교체를 유지하며 별도 cache 파일이나 재개 상태는 만들지 않는다.
통계·fallback 사유는 [검색 내부 문서](../search-internals.md#자동-벡터-재사용-5758)에 있다.

실모델 identity는 revision, 최대 길이, 정규화, 차원·dtype, device, 라이브러리 버전과
출력 구현 버전을 포함한다. 모델 artifact revision은
`5617a9f61b028005a4858fdac845db406aefb181`로 고정했다.

## 실측에서 확인한 배치 의존성

첫 post-feature 실측은 이전 실행 방식(모델 batch size 8)으로 8,044개를 234.49초에 계산했다.
그 DB에는 같은 surface인데 벡터가 다른 행 4개가 있어 계약대로 전체 재사용이 거부됐다.
차이는 최대 약 `1.15e-7`이었다. 이를 허용 오차로 덮거나 중복 텍스트 계산을 생략하지 않았다.

별도 소규모 모델 실측에서 같은 텍스트를 mixed/단독 호출로 비교한 결과:

| 모델 내부 batch size | 벡터 바이트 동치 | 최대 차이 |
|---|---|---|
| 8 | 아니오 | `1.27e-7` |
| 1 | 예 | 0 |

따라서 내부 실행 배치를 1로 고정하고 identity의 implementation을 2로 갱신했다.
호출자는 여전히 miss 전체를 한 번에 전달한다. cold 중복 제거는 하지 않는다.
최종 실측 환경은 MPS, float32, numpy 2.5.1, sentence-transformers 5.6.1,
transformers 5.14.1, torch 2.13.0이다. 이 환경의 결과이며 고정 시간 SLA는 아니다.

## 검증

- rebuild 경계에서 unchanged 객체/raw, 한 surface 변경, status/ID 변경, 삭제,
  eligibility·stale projection·빈 surface, FTS-only, 구형/손상/누락/충돌 DB를 검증했다.
- cold/warm documents·FTS·vector bytes·metadata와 BM25/벡터 검색 결과를 비교했다.
- 교체 전 검증·fsync·replace·임베딩 실패/중단 시 기존 live DB bytes 보존을 확인했다.
- CLI에서 총 대상 수 = 재사용 + 새 계산, fallback 사유, 소요 시간 출력을 확인했다.
- 독립 Standards 검수: 차단 지적 0건. Spec 검수에서 필수 metadata 컬럼 누락 검사
  1건을 발견해 red→green으로 수정했으며 재검수 지적 0건이다. 배치 독립성 보완도 재검수했다.
- 저장소에 별도 typechecker 설정은 없다. 변경 Python 모듈 compile 검사를 수행했다.

BB2 최종 rebuild 실측:

| 실행 | 전체 벡터 | 재사용 | 새 계산 | 소요 시간 | fallback |
|---|---:|---:|---:|---:|---|
| cold | 8,044 | 0 | 8,044 | 306.35초 | embedding_identity_mismatch |
| warm | 8,044 | 8,044 | 0 | 28.92초 | 없음 |

약 10.59배 빨라졌고 소요 시간은 약 90.56% 줄었다. cold의 fallback은 앞선 배치 8
진단 색인과 implementation 2가 다르기 때문이다. 최초 기능 도입 실행에서는 legacy_index로
전체 계산했으며, 최종 비교는 배치 독립성 보완 후 같은 코퍼스에서 다시 수행했다.
객체 행 6,023개와 raw 청크 2,021개를 포함한다. corpus fingerprint는
`6cdf0fec672962d1e129a24ae7de0898f27b2072a1cce65611f139820b89fd95`다.

최종 전체 엔진 회귀는 **2,318개 + 155 subtests 통과**(555.56초), 설치 runtime은
**123개 통과**했다. 새 재사용 표적 테스트는 25개, architecture 문서 표적 검사는 16개
통과했으며 `git diff --check`도 통과했다. 최종 명령:

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest -q
PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
git diff --check
```

cold/warm의 documents·FTS·vector bytes·metadata는 테이블 내용을 row ID 순으로 읽어
비교한 SHA-256이 모두 같았다. 전체 DB 파일의 물리 bytes 동치를 요구한 것은 아니다.

| 테이블 | cold/warm 공통 내용 SHA-256 |
|---|---|
| documents | `0e658c0a32a54ba937821b6acd92432c44a7c9d58d4ac3e2b93bfe26f7b0260e` |
| documents_fts | `f7706ad98ef8c6a97b4e14cd24ad6ddb1281bbc5dd487eda2c333409e1e86ade` |
| documents_vec | `9128b1b925df1121a746dcd9696e1cfe042354eb20add26626f697fa214b1dbe` |
| meta | `31531da972e78d0be00f14f947b0e26c7331df07135ca698bd04537445fd0449` |

- 전체 eval: cold/warm 각각 **18/18 통과**. `scenarios[].latency_ms`만 제외하고
  모든 시나리오의 판정·적중·회수 사실 결과가 같았다. 초기 비교 스크립트는 측정 시간까지
  비교해 assertion이 실패했으며, 원본 결과를 보존한 채 해당 시간 필드만 제외해 재확인했다.
- 대표 search: `인게임에서 아이템 사용하면`의 전체 JSON 응답이 같았다.
- 대표 query: `샐리 카누 보상은 왜 바뀌었어?`의 전체 JSON 응답이 같았다.
  이는 기존 결정론 조회 결과의 보존 확인이며 답변 의미 품질의 별도 승인은 아니다.

명령은 소비 프로젝트 루트에서 현재 checkout의 `PYTHONPATH=$ENGINE_ROOT/src`와
`$ENGINE_ROOT/.venv/bin/python -m project_brain.cli`를 함께 고정했다.
BB2 checks의 하위 CLI도 임시 wrapper로 같은 Python·엔진을 사용했다.

## BB2 기존 데이터 가드 불일치

현재 BB2 checks는 16개 중 14개 통과, 1개 skip, 1개 실패다.
실패는 `test_real_corpus.RealCorpusRebuildGuard.test_rebuild_row_counts`의
`EXPECTED_RAW_CHUNKS=2009`와 실제 2021개의 차이다.
작업 시작 전부터 있던 미추적 `brain/raw/sources/disturb-mini-icicle/`가 정확히 12개 청크를
추가한다. 시작 커밋의 엔진 source를 임시 디렉터리에 추출해 같은 BB2 상태와 같은 Python으로
해당 파일의 검사 6개를 실행했고, 같은 `2021 != 2009` 실패를 재현했다.

이 티켓은 소비 데이터·실측 가드를 소유하지 않으므로 그 원문이나 기대값을 변경하지 않았다.
사용자는 이 불일치가 BB2에서 병행 중인 작업에 따른 것이며 이번 기능과 무관하므로
#58을 완료 처리하도록 확인했다. 해당 실패는 기존 데이터 가드 불일치로 기록하고
완료 차단 사유에서 제외한다. BB2 checks 전체 통과로 바꾸어 보고하지는 않는다.

BB2 실행 전에 기존 `transactions/.DS_Store`가 트랜잭션 읽기를 차단했다. Finder metadata를
임시 디렉터리에 보존 이동해 해소했으며 트랜잭션 journal·객체·원문은 수정하지 않았다.
