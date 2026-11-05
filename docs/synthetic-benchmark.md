# 지식 베이스 합성 벤치마크와 vector RAG 평가

[이슈 #9](https://github.com/linkmind-ai/linkpaper/issues/9)의 DB 연결·그래프/벡터 인덱스 기반 평가셋 생성을 구현한다. 기존 인덱스를 읽어 질문·정답·근거 청크를 생성하고, 입력 스냅샷에서 재생성하거나 최신 DB에서 다시 생성한다. 기준 시스템은 **Qdrant vector retrieval + LLM 답변 생성**이며 아래 네 Ragas 지표를 기본으로 모두 계산한다.

| 출력 키 | 측정 내용 | 입력 |
|---|---|---|
| `ragas.faithfulness` | 답변의 주장 중 검색 근거가 지지하는 비율 | 질문·실제 답변·검색 근거 |
| `ragas.answer_relevancy` | 답변에서 역생성한 질문과 원 질문의 임베딩 유사도, 답변 회피 반영 | 질문·실제 답변 |
| `ragas.context_precision` | 정답에 유용한 검색 근거가 상위에 오는 정도(AP) | 질문·정답·순위가 보존된 검색 근거 |
| `ragas.context_recall` | 정답의 주장 중 검색 근거로 뒷받침되는 비율 | 정답·검색 근거 |

Ragas의 `Faithfulness`, `ResponseRelevancy`, `LLMContextPrecisionWithReference`, `LLMContextRecall`를 직접 사용한다. 지표 이름은 보고서에서 위 이름으로 고정한다. 어휘 중첩 점수를 이 네 지표로 대체 표기하지 않는다.

## 설치와 연결

```bash
cd evaluation
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,stores,ragas]'
```

실행 셸에서 `OPENAI_API_KEY`, `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`, `QDRANT_URL`, `QDRANT_COLLECTION`을 설정한다. `.env` 파일은 CLI가 자동 로드하지 않는다. `.env.example`의 컬렉션명·모델명은 운영 인덱스 설정에 맞춰 사용한다. 비밀번호/API 키는 매니페스트에 기록하지 않는다.

- 검색 임베딩: `LINKPAPER_EMBEDDING_PROVIDER=openai`, `LINKPAPER_EMBEDDING_MODEL`, `LINKPAPER_EMBEDDING_DIMENSIONS`. 인덱서를 실행할 때 사용한 모델·차원과 일치해야 한다.
- 답변 모델: `LINKPAPER_ANSWER_MODEL` (기본 `gpt-4o-mini`). `configs/vector.yaml`의 `generation`에서 토큰 상한·온도·시간 제한을 설정한다.
- 생성/심판 모델: 각각 CLI의 `--model`. 생성 변환용 임베딩은 `--embedding-model`로 선택하며 검색 임베딩과 역할이 다르다.
- OpenAI 호환 주소: `OPENAI_BASE_URL`. 서버가 chat JSON 응답과 embeddings API를 지원해야 한다.
- Qdrant named vector를 쓰면 `QDRANT_VECTOR_NAME`을 설정한다.
- 전체 DB 점검은 `linkpaper-eval bench doctor`. Qdrant만 사용하는 경로는 Neo4j가 없어도 실행할 수 있다.

검증한 버전은 **Ragas 0.3.9**이며 의존성을 고정했다. 해당 버전의 testset generator와 지표가 요구하는 `BaseRagasLLM`/`BaseRagasEmbeddings` 프로토콜에 맞는 LangChain 래퍼를 사용한다. Ragas를 올릴 때는 생성기·네 지표 계약 테스트를 함께 실행한다.

## 생성 → 기준 시스템 실행 → 네 지표 평가

이미 서비스 인덱서가 적재한 DB를 사용한다. 아래 생성·평가 명령은 DB에 쓰지 않는다.

```bash
# Neo4j의 실제 인용/청크 순서 관계 + Qdrant에 저장된 벡터를 활용한다.
linkpaper-eval testgen \
  --source neo4j --engine ragas --size 50 --limit 500 \
  --paper-ids arxiv:1706.03762,arxiv:1810.04805 --expand-hops 1 \
  --single-hop-ratio 0.5 --seed 1019 \
  --out datasets/generated/linkpaper.jsonl

# vector RAG: 전체 설정 컬렉션에서 top-k 검색 후 독립적으로 답변한다.
linkpaper-eval run --config configs/vector.yaml --run-id vector-1019

# 기본값으로 반드시 네 지표 모두 실행한다.
linkpaper-eval bench score --run-id vector-1019
```

`configs/vector.yaml`은 `suite: full`로 기존 검색/생성 지표도 저장한다. Ragas 심판은 `bench score` 단계에서 별도로 실행하므로 같은 답변에 심판 모델만 바꿔 재평가할 수 있다. `--metrics`를 생략해야 네 필수 지표가 모두 실행된다. 명시한다면 `faithfulness,answer_relevancy,context_precision,context_recall`을 사용한다.

Qdrant만 있을 때는 다음 경로를 사용한다.

```bash
linkpaper-eval testgen \
  --source qdrant --no-graph --engine ragas --size 50 --limit 500 \
  --out datasets/generated/vector-source.jsonl
linkpaper-eval run --config configs/vector.yaml \
  --dataset datasets/generated/vector-source.jsonl --run-id vector-source-1019
linkpaper-eval bench score --run-id vector-source-1019
```

멀티홉 생성에 쓸 간선이 없으면 실패한다. 단일 문서/청크만 평가하려면 `--single-hop-ratio 1`을 지정한다. Ragas 생성 후보 수는 요청값을 따르지만 검증에서 근거 누락·중복 질문이 제거되면 최종 건수가 줄 수 있다. 내보낸 건수와 제외 사유를 확인한다. 유효한 케이스가 0건이거나 스키마 검증이 실패하면 파일을 게시하지 않는다.

`--source jsonl --corpus ...`는 파일에서 생성하며 자동으로 DB에 연결하지 않는다. `--vector-backend auto`는 JSONL이면 설정한 임베더의 로컬 유사도(기본 hash), DB 소스면 Qdrant 저장 벡터를 사용한다. JSONL의 로컬 해시 연결은 배관 테스트용이다. DB 연결 실패를 로컬 처리로 숨기지 않는다.

## 재생성과 산출물

`linkpaper.jsonl` 옆에 다음 파일을 저장한다.

| 파일 | 내용 |
|---|---|
| `linkpaper.jsonl` | 질문, 정답, 근거 청크/논문 ID, 태그, Ragas 생성 근거 및 출처 |
| `linkpaper.corpus.jsonl` | 실제 입력 청크 본문과 온톨로지/인덱싱 메타데이터 |
| `linkpaper.graph.json` | 생성에 사용한 청크와 유형·방향·출처가 있는 간선 |
| `linkpaper.kg.json` | Ragas transform이 끝난 그래프 (`ragas` 엔진) |
| `linkpaper.manifest.json` | 입력 범위·옵션·버전·부모 매니페스트 해시·파일별 SHA-256·제외 통계 |

```bash
# DB를 읽거나 변환을 재실행하지 않고 저장한 그래프에서 다른 질문을 만든다.
linkpaper-eval testgen-regenerate \
  --manifest datasets/generated/linkpaper.manifest.json \
  --out datasets/generated/linkpaper-v2.jsonl \
  --size 100 --seed 1020 --single-hop-ratio 0.3
```

입력 산출물의 해시와 KG의 청크 ID/본문을 검증하고 이전 출처 정보를 이어받는다. 최신 지식 베이스를 반영하려면 처음의 `testgen --source neo4j` 또는 `qdrant` 명령을 새 출력 경로로 다시 실행한다. 기존 산출물을 바꾸려면 `--overwrite`를 명시한다. 검증 후 매니페스트를 마지막에 게시하고, 일반 파일 쓰기 실패는 이전 파일로 되돌린다. 프로세스 강제 종료 시 완료 매니페스트가 없으면 해당 묶음을 완료된 실행으로 취급하지 않는다. 동일 경로에 여러 생성 프로세스를 동시에 실행하지 않는다.

seed는 시나리오 선택을 제어한다. 원격 LLM 응답의 동일성을 보장하지 않으므로 실제 비교에는 확정된 생성 데이터셋과 해시를 고정한다.

평가 실행의 `cases.jsonl`에는 실제 검색 순서·전체 근거 본문·기준 답변을 저장한다. DB가 바뀌어도 해당 실행의 근거로 재채점한다. 과거 실행에 본문/정답이 없으면 `bench score --corpus ... --dataset ...` 또는 외부 벤치마크의 `--name`으로 복원한다. 누락된 근거 일부만 사용해 채점하지 않는다.

`ragas.json`에는 지표별 평균·유효 표본 수·케이스별 점수/실패 사유를 기록한다. 누락·예외·NaN/Inf는 평균에서 제외하며 보고서 상태가 `partial`/`failed`이면 CLI가 실패 코드를 반환한다. 정상적으로 검색 결과가 0개인 경우 precision/recall은 0점이다. 심판 호출이 실패한 것을 0점으로 치환하지 않는다. 정상 완료는 종료 코드 0, 불완전한 채점은 1, 잘못된 설정/실행 실패는 2다.

## 실제 온톨로지와 평가 범위

현재 `indexing/graph_builder`는 `Paper`, `Author`, `Chunk`와 `HAS_CHUNK`, `NEXT_CHUNK`, `AUTHORED_BY`, `CITES`를 적재한다. `Entity`/`MENTIONS`는 문서의 확장 계약이며 기본 인덱서가 만들지 않는다. 읽기 어댑터는 실제 존재하는 `MENTIONS`만 활용할 수 있다. 존재하지 않는 엔티티·의미 관계를 만들어 넣지 않는다.

- `chunkId/paperId`와 Qdrant의 `chunk_id/paper_id`를 동일한 원본 ID로 정규화한다. `sectionPath`, `contentHash`, `sourceVersion`, schema/global 상태, 임베딩 메타데이터를 보존한다.
- `CITES`는 두 논문의 청크를 짝짓는 근거다. 인용만으로 성능 개선·인과관계·후속 연구의 성공을 추론하지 않도록 생성 프롬프트에 제한한다. 답변 근거는 원문이다.
- Qdrant 연결은 저장된 벡터를 재사용하고 표본 내 후보로 제한한다. 모델을 추측해 다시 임베딩하지 않는다.
- 참고문헌 청크는 Neo4j에는 있으나 기본 인덱싱 설정상 Qdrant에는 없을 수 있다. 실제 vector baseline에서 답할 수 있는 코퍼스만 생성에 쓰려면 `--source qdrant`를 선택한다. Neo4j 소스는 벡터 검색의 이 누락도 평가에 드러낼 수 있다.
- `--limit`/`--paper-ids`는 **질문 생성 입력 표본**을 제한한다. vector RAG는 설정한 Qdrant 컬렉션 전체에서 검색하며 정답·정답 논문 ID를 검색/생성 입력으로 받지 않는다. 작은 표본만 적재한 평가 컬렉션의 점수는 전체 KB 점수가 아니다.
- `baseline`은 기존 BM25 테스트 타깃 이름으로 유지한다. 이번 기능의 품질 비교 기준은 `vector`/`vector_rag` 또는 `configs/vector.yaml`이다. 기존 `hybrid`는 추출식 답변을 사용하므로 생성 점수 차이를 그래프만의 효과로 해석하지 않는다. 기존 검색 확장 대조군은 `configs/hybrid.yaml`의 `vector_retrieval`이다.

외부 벤치마크를 적재할 때는 서비스 DB와 분리한 평가 저장소를 사용한다. Qdrant 쓰기/삭제 CLI는 대상을 `--collection`으로 명시해야 한다. 예: `bench seed --name qasper --collection linkpaper_eval_qasper`. 이후 평가할 때도 같은 `QDRANT_COLLECTION`을 설정한다. 합성 생성에는 이 적재 단계가 필요하지 않다.

## 전체 브랜치 검토 (2026-10-19)

`git fetch origin --prune` 이후 원격 브랜치 9개의 트리·차이·인덱싱/평가 계약을 확인했다. `1019`는 최신 `main`에서 분기해 별도 PR #20의 변경을 포함하지 않는다.

| 브랜치 | 확인한 HEAD | 판단 |
|---|---|---|
| `main` | `f487ac4` | 최신 데이터 파이프라인/인덱서가 통합된 기준 |
| `1016` | `1800d44` | 미병합 평가 지표·회귀 게이트 개선, PR #20에서 별도 관리 |
| `benchmark` | `1666aa0` | 기존 testgen/DB 어댑터 골격, main에 병합됨 |
| `data-pipeline` | `3bb34ae` | 일별 수집·section_path, main에 병합됨 |
| `evaluation` | `74e0bea` | 초기 평가 하네스, main에 병합됨 |
| `feat/pipline` | `de2a3a3` | 미병합 메모리 기반 온라인 RAG; 저장소의 정규 청크 ID와 다름 |
| `frontend` | `dba8acd` | 프런트 UI, main에 병합됨 |
| `graph_vector_builder` | `8b49540` | 실제 Qdrant/Neo4j 인덱싱·공유 ID 규칙, main에 병합됨 |
| `neo4j-schema-dev` | `083b0d0` | 벡터 책임을 Qdrant로 분리한 스키마, main에 병합됨 |

이전 Neo4j 벡터 인덱스/페이지 좌표 중심 문서보다 현재 builder의 `charCount`, `sourceVersion`, `sectionPath`와 Qdrant payload 계약을 우선한다.

## 검증과 참고자료

```bash
pytest -q
# Docker의 독립 임시 Neo4j에서 실제 인덱서 → 생성 소스 계약 검증
pip install 'pydantic-settings>=2.9,<3' 'langchain-text-splitters>=0.3,<0.4'
LINKPAPER_TEST_DOCKER_NEO4J=1 pytest -q tests/test_ontology_integration.py
```

CI는 기본 테스트, 실제 Ragas 생성/네 지표 알고리즘을 scripted provider로 실행하는 계약 테스트, in-memory Qdrant vector RAG, 스냅샷 재생성, 격리 Neo4j 통합 테스트를 실행한다. API 키 없이 구현 경로를 검증하며 실제 LLM 생성 품질이나 운영 KB 점수를 대신하지 않는다. 합성 질문·정답은 사람이 표본 검토한 후 평가용으로 확정한다.

Ragas를 우선 검토해 기존 하네스와 testset/지표 API를 함께 사용할 수 있어 채택했다. DeepEval도 후보로 검토했으나 이번 구현에 두 평가 프레임워크를 함께 넣을 필요는 없었다.

- [Ragas 공식 합성 데이터 생성](https://docs.ragas.io/en/stable/getstarted/rag_testset_generation/), [v0.3.9 소스](https://github.com/vibrantlabsai/ragas/tree/v0.3.9)
- [Faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/), [Answer/Response Relevancy](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/answer_relevance/), [Context Precision](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_precision/), [Context Recall](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_recall/)
- 사용자 참고자료: [DeepEval](https://github.com/confident-ai/deepeval), [Ragas 저장소](https://github.com/vibrantlabsai/ragas), [위키독스 합성 테스트셋](https://wikidocs.net/259204), [RAGAS 평가 블로그](https://velog.io/@judy_choi/우아한-스터디-RAGAS-RAG-파이프라인-평가-프레임워크)
