# LinkPaper Benchmark & Testset Generation

> 상태: Draft
>
> 범위: 외부 벤치마크 데이터셋 설정, 그래프·벡터 인덱스 기반 평가셋 생성,
> Qdrant·Neo4j 연결, ragas 지표

지표 정의와 백엔드 응답 계약은 [evaluation.md](./evaluation.md)를 따른다.
이 문서는 **평가에 쓸 데이터를 어디서 가져오고 어떻게 만드는가**만 다룬다.

## 1. 왜 따로 필요한가

기존 하네스에는 12건짜리 샘플 데이터셋과 BM25 베이스라인이 있다. 파이프라인을
검증하기에는 충분하지만 두 가지를 할 수 없다.

1. **규모 있는 비교** — 12건으로는 태그별 집계의 표본이 한 자릿수다. 점수가
   움직여도 개선인지 잡음인지 구분되지 않는다.
2. **그래프의 기여 측정** — 우리 데이터셋의 `global`·`follow-up` 케이스는
   손으로 쓴 것이라 수가 적다. 그래프 확장이 실제로 도움이 되는지 보려면
   "여러 문서를 가로질러야 답이 나오는" 질문이 대량으로 필요하다.

그래서 두 가지 경로를 만들었다. **외부 벤치마크를 가져오는 경로**와
**우리 인덱스에서 평가셋을 생성하는 경로**다. 둘 다 최종 산출물이
`EvalCase` JSONL이므로, 기존 러너·지표·게이트·리포트가 그대로 적용된다.
벤치마크를 위해 별도의 실행 골격을 만들지 않았다는 뜻이며, 그래야 자체
데이터셋 점수와 외부 벤치마크 점수를 같은 축에서 볼 수 있다.

## 2. 빠른 시작 (DB·API 키 없이)

```bash
cd evaluation
pip install -e '.[dev]'

# 저장소 픽스처를 벤치마크 형식으로 묶는다
linkpaper-eval bench prepare --name linkpaper-local
linkpaper-eval bench run --name linkpaper-local --suite retrieval

# 벡터 유사도로 평가셋을 생성한다
linkpaper-eval testgen \
  --source jsonl --corpus fixtures/mock_corpus.jsonl \
  --engine offline --size 20 --out datasets/generated/smoke.jsonl
```

여기까지는 네트워크, API 키, 실행 중인 컨테이너가 없어도 동작한다. 배관이
살아 있는지 확인하는 용도이며, 이 숫자를 시스템 품질 근거로 쓰지 않는다.

환경 점검은 `linkpaper-eval bench doctor`가 한다. 어떤 의존성이 빠졌고 어떤
DB에 못 붙는지 한 번에 보여 준다.

## 3. 외부 벤치마크

### 3.1 목록

```bash
linkpaper-eval bench list
linkpaper-eval bench list --name qasper   # 상세
```

| 이름 | 무엇 | 라이선스 | 왜 골랐나 |
|---|---|---|---|
| `qasper` | NLP 논문 1,585편에 대한 질문 5,049개 + 문단 단위 근거 | CC BY 4.0 | **LinkPaper와 가장 가깝다.** arXiv 논문 본문을 섹션·문단으로 제공하고 정답 근거가 문단 단위라, 우리 청크 구조에 그대로 대응된다 |
| `multihop-rag` | 문서 2~4편에 근거가 흩어진 멀티홉 질의 2,556개 | ODC-BY | 도메인은 뉴스지만 "여러 문서를 가로지르는 질문"이라는 성격이 우리 `global` 질의와 같다. 그래프 확장 효과를 보는 용도 |
| `graphrag-bench` | GraphRAG 전용 벤치마크 (난이도 계층) | 연구 목적 한정, **재배포 금지** | 남두현님이 공유한 [arXiv:2506.02404](https://arxiv.org/abs/2506.02404)의 데이터셋 |
| `linkpaper-local` | 저장소 픽스처 | MIT | 오프라인 배관 검증 |

두 가지를 짚어 둔다.

- **QASPER는 전부 `expected_scope: selected`다.** 단일 논문 안에서 답이
  나오는 데이터셋이라 라우팅의 `global` 쪽을 검증하지 못한다. 선택 논문
  내부 검색 성능을 재는 데 쓰고, 확장이 필요한 질문은 `multihop-rag`와
  자체 생성 데이터셋으로 보완한다.
- **GraphRAG-Bench는 재배포가 금지되어 있다.** 원본을 저장소에 커밋하지
  말 것. `benchmarks/data/`가 gitignore 대상인 이유다. 코퍼스 파일 경로가
  릴리스마다 달라 자동 다운로드가 실패할 수 있고, 그때는 질문 파일만으로
  생성 스위트를 만든다.

### 3.2 자동 다운로드

```bash
pip install -e '.[bench]'      # datasets, huggingface-hub
linkpaper-eval bench prepare --name qasper --limit 300
```

`prepare`는 세 단계를 한 번에 한다.

1. **다운로드** — `datasets.load_dataset` → `hf_hub_download` → 직접 HTTP
   순서로 시도한다. 받은 원본은 `raw/` 아래에 캐시되므로 다시 실행해도
   재다운로드하지 않는다 (`--force`로 갱신).
2. **변환** — 외부 형식을 청크 코퍼스와 `EvalCase`로 옮긴다.
3. **매니페스트** — 원본 해시, 케이스 수, 근거 매칭률을 기록한다.

```text
evaluation/benchmarks/data/qasper/
├── raw/qasper.jsonl     # 원본 캐시
├── corpus.jsonl         # 청크 코퍼스 (fixtures/mock_corpus.jsonl과 같은 형식)
├── retrieval.jsonl      # EvalCase
├── generation.jsonl
└── manifest.json
```

**근거 매칭률을 반드시 확인한다.** 외부 벤치마크는 정답 근거를 "문단
텍스트"로 주는데 우리 지표는 "청크 ID"를 비교한다. 그 사이를 텍스트 매칭으로
잇기 때문에, 매칭에 실패한 근거는 정답에서 빠진다. 이걸 모르면 Recall이
낮게 나왔을 때 검색기 탓으로 오해한다. 80% 미만이면 `prepare`가 경고한다.

### 3.3 자동 다운로드가 실패하면

접근 정책이 바뀌거나 파일 경로가 이동하면 다운로드가 막힌다. 이때 실패
메시지 자체가 설정 안내다. 다운로드와 변환이 분리되어 있으므로, 원본을
직접 넣으면 변환부터 이어서 진행된다.

```text
'qasper' 원본을 자동으로 받지 못했습니다.

수동 설정 방법:
  1. https://huggingface.co/datasets/allenai/qasper 에서 원본을 받습니다.
     안내: validation split을 JSONL로 내보내 raw/qasper.jsonl 로 저장
  2. JSON 배열 또는 JSONL로 다음 경로에 저장합니다:
     evaluation/benchmarks/data/qasper/raw/qasper.jsonl
  3. 같은 prepare 명령을 다시 실행하면 다운로드를 건너뛰고 변환합니다.
```

데이터셋별 원본 파일과 저장 경로는 다음과 같다.

| 벤치마크 | 원본 | 저장 경로 (`evaluation/benchmarks/data/` 기준) |
|---|---|---|
| `qasper` | `allenai/qasper` validation split | `qasper/raw/qasper.jsonl` |
| `multihop-rag` | `yixuantt/MultiHopRAG` → `MultiHopRAG.json` | `multihop-rag/raw/queries.jsonl` |
| | `yixuantt/MultiHopRAG` → `corpus.json` | `multihop-rag/raw/corpus.jsonl` |
| `graphrag-bench` | `GraphRAG-Bench/GraphRAG-Bench` → `Datasets/Questions/*.json` | `graphrag-bench/raw/questions.jsonl` |
| | 같은 저장소의 코퍼스 파일 (경로는 Files 탭에서 확인) | `graphrag-bench/raw/corpus.jsonl` |

JSON 배열과 JSONL을 모두 읽으므로, 받은 `.json`을 그대로 `.jsonl` 이름으로
저장해도 된다.

`datasets` 없이 HuggingFace CLI만으로 받으려면:

```bash
huggingface-cli download allenai/qasper --repo-type dataset --local-dir /tmp/qasper
```

내려받은 parquet/json을 위 경로에 JSONL로 옮긴다.

### 3.4 새 벤치마크 추가

`evaluation/src/linkpaper_eval/benchmark/registry.py`에 `BenchmarkSpec`을
하나 더하고, `converters.py`에 변환 함수를 쓴 뒤 `CONVERTERS`에 등록한다.
변환 함수는 `(raw, out_dir, limit) -> ConversionReport` 하나만 지키면 된다.

검토해 볼 만한 후보: HotpotQA, 2WikiMultihopQA, MuSiQue (멀티홉),
SciFact (과학 문헌 검색). 저장소 ID와 config 이름은 추가 전에 확인할 것.

[naver/bergen](https://github.com/naver/bergen)은 데이터셋이 아니라 RAG
벤치마킹 **라이브러리**다. 자체 러너와 설정 체계를 갖고 있어서 의존성으로
넣지 않았다. 우리 하네스는 이미 실행 골격·게이트·리포트를 갖고 있고, 여기에
bergen을 얹으면 두 개의 실행 체계를 동시에 유지해야 한다. 대신 bergen이
정리해 둔 데이터셋 목록과 실험 설계를 레지스트리 확장의 참고 자료로 쓴다.

## 4. 평가셋 생성 (그래프 & 벡터 인덱스 기반)

생성·스냅샷 재생성·실제 온톨로지·필수 네 지표의 전체 실행은
[합성 벤치마크 가이드](synthetic-benchmark.md)를 기준으로 한다.

[ragas testset generation](https://docs.ragas.io/en/stable/getstarted/rag_testset_generation/)의
2단계 구조를 우리 지식그래프 위에서 돌린다.

```text
청크 확보          그래프/벡터 간선 구성        질문 생성          검증·저장
(neo4j|qdrant|      Neo4j: CITES,              ragas 또는       EvalCase JSONL
 jsonl)             NEXT_CHUNK, MENTIONS       offline 템플릿
                    Qdrant: 최근접 이웃
```

### 4.1 무엇이 LinkPaper 고유한가

현재 Neo4j의 CITES/NEXT_CHUNK, 실제 존재하는 MENTIONS와 Qdrant 저장 벡터를
후보 연결로 사용한다. Ragas용 커스텀 시나리오 생성기가 관계 종류와 방향을
유지한다. 인용만으로 개선·인과를 추론하지 않으며 정답은 원문으로 뒷받침한다.

### 4.2 실행

```bash
# 1) 오프라인 — LLM 없이 배관 확인
linkpaper-eval testgen --source jsonl --corpus fixtures/mock_corpus.jsonl \
  --engine offline --size 20

# 2) ragas — 실제로 쓸 데이터셋
pip install -e '.[ragas,stores]'
export OPENAI_API_KEY=...
linkpaper-eval testgen \
  --source neo4j --engine ragas --size 50 \
  --paper-ids arxiv:1706.03762,arxiv:1810.04805 --expand-hops 1 \
  --save-kg runs/kg.json \
  --out datasets/generated/graph-multihop.jsonl
```

주요 옵션:

| 옵션 | 뜻 |
|---|---|
| `--source` | `neo4j` \| `qdrant` \| `jsonl` |
| `--engine` | `ragas` (실사용) \| `offline` (배관 검증) |
| `--paper-ids` + `--expand-hops` | 관심 논문에서 인용 관계로 몇 홉까지 넓힐지 |
| `--no-graph` / `--no-vector` | 간선 출처를 끈다. 각각의 기여를 분리해 볼 때 |
| `--vector-backend` | `auto` (JSONL이면 local, DB 소스면 Qdrant; 연결 실패 시 중단) \| `qdrant` \| `local` |
| `--save-kg` | ragas KnowledgeGraph 저장. 가장 비싼 단계라 재사용 가치가 크다 |

**비용 주의.** 코퍼스 전체를 LLM에 통과시키면 요금이 빠르게 커진다.
`--paper-ids`로 관심 논문에서 시작해 그래프로 넓히는 것이 기본 사용법이다.
`--save-kg`로 지식그래프를 저장해 두면 질문 분포만 바꿔 다시 생성할 때
추출 단계를 건너뛴다.

### 4.3 오프라인 엔진의 한계 (반드시 읽을 것)

오프라인 엔진은 질문 문장을 청크의 특징 단어로 조립한다. 따라서 **어휘 기반
검색기(BM25)에 유리하게 기운다.** 이 데이터셋에서 나온 Recall을 시스템 성능
근거로 쓰면 안 된다.

편향을 줄이려고 가장 특징적인 단어 하나는 질문에서 빼고, 기능어와 한 번만
등장한 단어를 주제어 후보에서 제외한다. 그래도 사람이 쓴 질문과는 다르다.

존재 이유는 다른 데 있다. API 키 없이 CI에서 매번 돌릴 수 있으므로
**생성 경로가 조용히 깨지는 것을 막는다.** 그래프에서 후보와 간선이 제대로
나오는지, 생성한 정답 청크 ID가 코퍼스에 실제로 존재하는지, 만들어진 JSONL을
기존 러너가 읽는지를 확인한다.

### 4.4 생성 결과 검증

내보내기 전에 자동으로 확인한다.

- `EvalCase` 스키마 준수
- `case_id` 중복
- **정답 청크 ID가 코퍼스에 실재하는지** — 오타 하나로 Recall이 조용히 0이
  되는 사고를 막는다. 기존 테스트가 손으로 만든 데이터셋에 하던 검증을
  생성 경로에도 적용한 것이다.

스키마 검증 실패나 유효 케이스 0건이면 산출물을 게시하지 않고 종료 코드 2를 반환한다.
부분 근거·빈 정답·중복 질문의 제외 건수는 매니페스트에 기록한다.

생성한 데이터셋은 `datasets/generated/` 아래에 놓이고 gitignore 대상이다.
검토해서 쓰기로 한 것만 `datasets/<suite>/`로 옮겨 커밋한다. 생성물을 전부
커밋하면 어떤 게 검증된 데이터인지 구분되지 않는다.

## 5. DB 연결

### 5.1 설정

접속 정보는 환경변수를 기본 경로로 한다 (우선순위: 인자 > 환경변수 > 기본값).

| 환경변수 | 기본값 |
|---|---|
| `QDRANT_URL` | `http://localhost:6333` |
| `QDRANT_API_KEY` | (없음) |
| `QDRANT_COLLECTION` | `linkpaper_chunks_v1` (기존 운영 컬렉션명으로 설정) |
| `NEO4J_URI` | `bolt://localhost:7687` |
| `NEO4J_USERNAME` / `NEO4J_PASSWORD` | `neo4j` / `linkpaper-password` |
| `NEO4J_DATABASE` | `neo4j` |
| `LINKPAPER_EMBEDDING_PROVIDER` | `hash` |

기본 호스트가 `localhost`인 것은 의도적이다. 평가는 대부분 호스트에서 CLI로
돌린다. 컨테이너 안에서 실행할 때만 서비스 이름으로 덮어쓰면 된다.

### 5.2 평가 전용 DB 띄우기

루트 `docker-compose.yml`을 건드리지 않으려고 파일을 분리했다. 포트와 볼륨이
달라서 서비스 스택과 동시에 띄울 수 있다.

```bash
cd evaluation
docker compose -f docker-compose.eval.yml up -d

export QDRANT_URL=http://localhost:6343
export NEO4J_URI=bolt://localhost:7688
linkpaper-eval bench doctor
```

**벤치마크 코퍼스를 서비스 DB에 섞지 않는다.** 뉴스 기사나 교과서 문단이
논문 그래프에 들어가면 서비스 검색 결과가 오염된다.

### 5.3 적재

```bash
pip install -e '.[stores]'
linkpaper-eval bench seed --name qasper --collection linkpaper_eval_qasper              # Qdrant + Neo4j
linkpaper-eval bench seed --name qasper --collection linkpaper_eval_qasper --no-neo4j   # 벡터만
linkpaper-eval bench clean --qdrant --collection linkpaper_eval_qasper --neo4j          # 되돌리기
```

적재는 멱등이다. `chunk_id`가 같으면 point와 노드를 덮어쓴다.

- **Qdrant** — point ID는 `chunk_id`의 UUIDv5다 (Qdrant가 문자열 ID를
  받지 않는다). payload에 `chunk_id`, `paper_id`, `text`, `section`을 넣는다.
  `chunk_id`가 없으면 검색 결과를 정답과 대조할 수 없다.
- **Neo4j** — 라벨과 관계는 [neo4j-schema.md](./data-architecture/neo4j-schema.md)를
  따른다 (`:Paper`, `:Chunk:GlobalChunk`, `HAS_CHUNK`, `NEXT_CHUNK`, `CITES`).
  벤치마크로 넣은 논문에는 `processingStatus = 'benchmark'`가 붙어서
  `bench clean`으로 되돌릴 수 있다. 서비스 데이터에는 이 값이 없으므로
  실수로 지워지지 않는다.

### 5.4 임베딩 모델을 맞출 것

인덱스를 만든 모델과 검색에 쓰는 모델이 달라야 할 이유는 없다. 차원이
어긋나면 Qdrant가 거부하고, 차원이 같아도 의미 공간이 다르면 점수가
무의미해진다. 모델을 바꾸면 `--recreate`로 컬렉션을 다시 만든다.

`provider: hash`는 네트워크 없이 도는 결정적 임베더다. 어휘 겹침만
반영하므로 의미 검색 품질을 대표하지 않는다. 배관 검증용이다.

> 임베더마다 코사인 유사도의 분포가 다르다. 학습된 임베딩은 관련 문서가
> 0.3~0.9에 분포하지만 해시 임베더는 같은 관계가 0.1~0.3에 나온다. 그래서
> "관련 있음" 임계값을 상수로 두지 않고 임베더가 직접 들고 있게 했다.

## 6. DB에 직접 붙는 타깃

`vector`는 Qdrant 검색과 LLM 답변 생성 기준 시스템이다. `hybrid`는 기존
Qdrant+Neo4j 검색과 추출식 답변 타깃이다. 생성기가 다르므로 두 답변 점수의
차이를 그래프 효과로 해석하지 않는다. 검색 확장의 대조군은
`configs/hybrid.yaml`의 `vector_retrieval`이다.

```bash
linkpaper-eval run --config configs/vector.yaml --run-id vector-1019
linkpaper-eval bench score --run-id vector-1019
linkpaper-eval run --config configs/hybrid.yaml --target vector_retrieval
```

## 7. ragas 지표

기존 지표는 결정적이고 비용이 0이지만 어휘 기반이라 한계가 있다.
`groundedness_lexical`이 1.0이어도 답변이 질문에 답하지 못할 수 있다.
ragas 지표는 LLM 심판으로 그 간극을 메운다.

```bash
pip install -e '.[ragas]'
export OPENAI_API_KEY=...

linkpaper-eval bench run --name qasper --suite generation --run-id r1
linkpaper-eval bench score --run-id r1 --name qasper --suite generation \
  --metrics faithfulness,answer_relevancy,context_precision,context_recall
```

**실행 중이 아니라 실행이 끝난 뒤에 채점한다.** 이유는 두 가지다.

1. 러너는 실제 답변·검색 본문·정답을 기록하고 LLM 심판은 별도 단계에서 호출한다.
2. 같은 실행 결과를 여러 번 다시 채점할 수 있다. 지표나 심판 모델을 바꿔
   볼 때 파이프라인을 다시 돌릴 필요가 없다.

점수는 `runs/<run_id>/ragas.json`에 저장하고 `ragas.` 접두사가 붙어 결정적
지표와 섞이지 않는다. **LLM 심판은 점수에 분산이 있으므로 CI 게이트 기준으로
쓰지 않는다.**

새 실행은 실제 검색 본문과 정답을 저장하므로 외부 코퍼스 없이 재채점할 수 있다.
과거 실행은 `--name` 또는 `--corpus`/`--dataset`으로 복원한다. 누락·예외·NaN은
지표별 실패로 기록하고 불완전한 채점은 종료 코드 1을 반환한다.

## 8. 알려진 한계

- **근거 매칭이 완벽하지 않다.** 외부 벤치마크의 문단 텍스트를 청크 ID로
  옮기는 과정에서 일부가 유실된다. 매칭률을 매니페스트에 남기므로 낮으면
  변환기를 손봐야 한다.
- **벤치마크 코퍼스는 overlap 0으로 청킹한다.** 청크가 겹치면 같은 근거
  문장이 여러 청크에 들어가 정답이 하나로 정해지지 않는다. 서비스
  인덱싱(overlap 150)과 다른 선택이며, 목적이 다르기 때문이다. 절대 점수를
  서비스 성능으로 읽지 말 것.
- **오프라인 생성 엔진은 어휘 검색에 유리하다.** 4.3 참고.
- **Ragas 합성 정답은 표본 검토가 필요하다.** 스키마·원문 ID·간선·근거 매칭을
  자동 검증해도 질문의 자연스러움과 정답의 의미적 정확성을 보장하지 않는다.
- **QASPER는 `global` 라우팅을 검증하지 못한다.** 3.1 참고.

## 9. 다음 단계

1. QASPER로 `--target baseline` / `vector` / `hybrid` 실측 후 베이스라인 확정
2. `hybrid` vs `vector_retrieval` 검색 지표 차이로 그래프 기여도 정량화
3. 인용 그래프가 실제로 적재된 뒤 `--engine ragas`로 `link:cites` 기반
   멀티홉 데이터셋 생성, 사람이 검토해 `datasets/`로 승격
4. 실제 분포 확인 후 `configs/hybrid.yaml`의 게이트 채우기
5. 한국어 질의 데이터셋 확보 방안 결정 (현재 모든 벤치마크가 영어)
