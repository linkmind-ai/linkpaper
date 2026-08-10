# 벤치마크 기능 추가 변경 내역

기존 하네스의 실행 골격·지표·게이트·리포트를 그대로 두고 얹는 방향으로
작업했다. 아래는 **기존 파일에 손댄 부분 전부**다. 머지할 때 이 목록만
확인하면 된다.

## 수정한 기존 파일 (6개)

| 파일 | 변경 | 이유 |
|---|---|---|
| `src/linkpaper_eval/cli.py` | 서브파서 등록 훅 + `handler` 디스패치 (약 10줄 추가) | `bench`·`testgen` 명령을 붙인다. `run`/`baseline`/`show` 동작은 그대로다. 등록이 실패해도 기존 명령은 쓸 수 있게 예외를 삼킨다 |
| `src/linkpaper_eval/schemas.py` | `RetrievalSource`에 `qdrant_vector` 추가 | 벡터 저장소를 Qdrant로 정했다. 기존 값은 지우지 않았다 — 과거 산출물과 백엔드 응답이 아직 쓸 수 있다 |
| `src/linkpaper_eval/targets/base.py` | `graphrag_hybrid` 분기 추가 | 파일 주석이 안내하는 확장 방식 그대로다 |
| `pyproject.toml` | optional-dependencies에 `stores`/`bench`/`ragas`/`all` 추가 | 기본 설치에는 새 의존성이 없다. CI는 그대로 돌아간다 |
| `.gitignore` | `benchmarks/data/`, `datasets/generated/` 추가 | 재배포 금지 데이터와 미검토 생성물이 커밋되는 것을 막는다 |
| `README.md` (evaluation) | 벤치마크 섹션과 구조도 갱신 | |

루트에서는 `.env.example`(평가용 변수 추가), `README.md`(문서 링크 한 줄),
`.github/workflows/evaluation.yml`(오프라인 스모크 잡 추가)를 건드렸다.
`docker-compose.yml`은 **건드리지 않았다.** 평가용 DB는
`evaluation/docker-compose.eval.yml`로 분리했다.

## 새로 추가한 것

```text
evaluation/
├── docker-compose.eval.yml          # 평가 전용 Qdrant + Neo4j
├── configs/hybrid.yaml              # DB 직결 타깃 설정
├── benchmarks/README.md
├── datasets/generated/README.md
├── tests/test_benchmark.py          # 30건 추가 (네트워크·API 키 불필요)
└── src/linkpaper_eval/
    ├── ragas_runtime.py             # ragas LLM·임베딩 래퍼 (버전 대응)
    ├── stores/                      # Qdrant·Neo4j 연결, 임베딩
    │   ├── config.py records.py embedding.py
    │   ├── neo4j_store.py qdrant_store.py
    ├── benchmark/                   # 외부 벤치마크
    │   ├── registry.py download.py converters.py
    │   ├── prepare.py seed.py ragas_metrics.py cli.py
    ├── testgen/                     # 그래프·벡터 기반 평가셋 생성
    │   ├── sources.py graph.py
    │   ├── offline_engine.py ragas_engine.py
    │   ├── export.py pipeline.py
    └── targets/graphrag_hybrid.py   # Qdrant + Neo4j 직결 타깃
```

## 파이썬 버전

`requires-python = ">=3.11"`이고 CI도 3.11로 돈다. 로컬이 3.12 이상이면
3.12에서 새로 허용된 문법(f-string 표현식 안의 백슬래시, 같은 따옴표 중첩)이
로컬에서만 통과하고 CI에서 깨진다. 실제로 한 번 겪었고, 전체 테스트를 3.11로
다시 확인했다.

```bash
uv venv --python 3.11 .venv311
.venv311/bin/pip install -e '.[dev,stores]'
.venv311/bin/pytest -q
```

## 설계에서 지킨 것

- **기본 설치에 새 의존성이 없다.** `neo4j`, `qdrant-client`, `datasets`,
  `ragas`는 전부 선택 의존성이고 지연 임포트한다. 설치하지 않아도 패키지
  임포트와 기존 테스트가 그대로 통과한다.
- **생성물이 기존 형식을 따른다.** 벤치마크와 생성기의 출력이 모두
  `EvalCase` JSONL과 `mock_corpus.jsonl` 형식이라, 러너·지표·게이트·리포트를
  새로 만들지 않았다.
- **다운로드와 변환을 분리했다.** 자동 다운로드가 막혀도 원본을 직접 두면
  변환부터 이어서 진행된다.
- **ragas 호출이 실행 경로에 끼어들지 않는다.** LLM 지표는 실행이 끝난 뒤
  사후 채점한다. 오프라인 CI가 깨지지 않는다.

## 확인 방법

```bash
cd evaluation
pip install -e '.[dev]'
pytest -q                                    # 57 passed (기존 27 + 신규 30)

linkpaper-eval run --config configs/retrieval.yaml   # 기존 경로 회귀 확인
linkpaper-eval bench prepare --name linkpaper-local
linkpaper-eval bench run --name linkpaper-local --suite retrieval
linkpaper-eval testgen --source jsonl --corpus fixtures/mock_corpus.jsonl \
  --engine offline --size 20 --out /tmp/gen.jsonl
```
