# LinkPaper 백엔드

LinkPaper 백엔드는 FastAPI 기반의 가벼운 모듈러 모놀리스 애플리케이션이다.
하나의 프로세스와 Docker 이미지로 실행·배포하되, 내부 코드는 책임별 모듈과
파이프라인으로 구분하고 모듈의 공개 인터페이스를 통해 연결한다.

## 현재 구조

```text
backend/
├── src/linkpaper/
│   ├── api/                 # HTTP 라우터와 FastAPI 의존성
│   ├── pipelines/           # 여러 모듈을 조합하는 처리 흐름
│   ├── modules/             # 기능과 내부 모델
│   ├── adapters/            # OpenAI 등 외부 시스템 연동
│   ├── core/                # 설정, 예외, 로깅
│   └── main.py              # FastAPI 애플리케이션 진입점
├── tests/
├── Dockerfile
└── pyproject.toml
```

### API

외부에 공개하는 HTTP 경계다. 내부 처리 단계를 각각 API로 만들지 않고 사용자
행동에 해당하는 요청만 노출한다.

현재 생성된 라우트는 다음과 같다.

- `GET /api/v1/health`
- `POST /api/v1/chat/stream`
- `GET /api/v1/papers`
- `POST /api/v1/papers/{paper_id}/analysis`
- `POST /api/v1/conversations/{conversation_id}/messages`

`chat/stream`은 온라인 단일 논문 RAG와 OpenAI SSE 생성을 제공한다. 개발 범위,
테스트 방법과 향후 GraphRAG 계획은
[`docs/pipeline-development.md`](../docs/pipeline-development.md)를 참고한다.
논문 검색·분석과 conversation 라우트는 아직 `501 Not Implemented`를 반환한다.

### Pipelines

파이프라인은 여러 모듈 서비스를 주입받아 실행 순서를 조율하는 애플리케이션
서비스다. 세부 파싱, 검색, 생성 로직은 파이프라인에 직접 작성하지 않는다.

```text
PaperAnalysisPipeline
├── PaperService
├── DocumentService
├── KnowledgeGraphService
└── GenerationService

QuestionAnsweringPipeline
├── OnlineRetrievalService
└── GenerationService
```

현재 질의응답 파이프라인은 선택 논문을 온라인으로 인덱싱하고 검색 근거를
생성 모델에 전달한다. `PaperAnalysisPipeline`은 아직 골격이다.

### Modules

각 모듈은 자신의 기능과 내부 데이터 모델을 소유한다.

```text
modules/
├── papers/              # 논문 검색과 메타데이터
├── documents/           # 적재된 논문·청크와 준비 상태 조회 골격
├── vector_read/         # Qdrant 선택 논문·글로벌 벡터 조회
├── knowledge_graph/     # Neo4j 논문 그래프 조회와 인용 확장
├── retrieval/           # 벡터·그래프 검색 조율과 결과 결합 골격
├── online_retrieval/    # 단일 논문 온라인 인메모리 인덱싱·검색
├── generation/          # 요약과 근거 기반 답변 생성
└── conversations/       # 대화와 메시지 이력
```

`vector_read/`는 Qdrant의 완성된 인덱스만 읽는다. 선택 논문 검색에서는
`paper_id`, 글로벌 검색에서는 `in_global_corpus=true` payload filter를
사용한다. 검색 결과의 `chunk_id`는 Neo4j 그래프 확장의 join key다.

`knowledge_graph/`는 Neo4j의 `Paper`, `Author`, `Chunk` 노드와
`AUTHORED_BY`, `HAS_CHUNK`, `CITES` 관계를 조회한다. `GlobalPaper`와
`GlobalChunk` 보조 라벨로 글로벌 탐색 범위를 제한한다.

두 모듈은 온라인 read 전용이며 create·update·delete나 인덱스 구축 메서드를
노출하지 않는다. 전처리, 임베딩 생성, Neo4j·Qdrant 적재는 저장소 루트의
`indexing/`이 담당한다.

각 모듈의 `__init__.py`는 외부에 공개할 `Service`와 `Model`을
명시한다. 다른 코드에서는 가능한 한 모듈의 내부 파일이 아닌 공개 경로를
사용한다.

```python
from linkpaper.modules.documents import DocumentService
```

### Adapters

외부 시스템과 연결되는 구현을 배치한다. `OpenAIClient`는 Responses API 기반
스트리밍 생성과 Embeddings API 호출을 제공하고,
`HuggingFaceMarkdownClient`는 선택 논문의 Markdown 본문을 가져온다. Neo4j와
Qdrant 연결은 각각 저장소 스키마를 소유한 `knowledge_graph/`, `vector_read/`
모듈 내부에 둔다.

### 의존성 조립

`api/dependencies.py`에서 모듈 서비스를 생성하고 파이프라인에 주입한다.
별도의 DI 프레임워크나 컨테이너는 사용하지 않으며, `lru_cache`로
파이프라인 인스턴스를 재사용한다.

```text
Router
  → api/dependencies.py
  → Pipeline
  → Module Service
  → Adapter 또는 Neo4j·Qdrant
```

현재 Chat 파이프라인에는 `OnlineRetrievalService`와 `GenerationService`만
주입한다. `KnowledgeGraphService`와 `VectorReadService`는 향후 별도 GraphRAG
파이프라인에서 `RetrievalService`를 통해 조합한다.

## 로컬 실행

저장소 루트에서 환경변수 파일을 준비한다.

```bash
cp .env.example .env
docker compose up --build
```

Docker Compose는 현재 다음 서비스를 실행한다.

- FastAPI 백엔드: <http://localhost:8000>
- Swagger UI: <http://localhost:8000/docs>
- Neo4j Browser: <http://localhost:7474>
- Qdrant HTTP API: <http://localhost:6333>
- PostgreSQL: `localhost:5432`

PostgreSQL, Neo4j, Qdrant 데이터는 Docker named volume에 저장된다.
`indexing` 서비스는 `jobs` profile의 일회성 오프라인 작업이므로 일반
`docker compose up`에는 포함되지 않는다.

Docker Compose는 백엔드의 저장소 조회 설정을 루트 `.env`에서 읽는다.

온라인 질의 임베딩은 Qdrant 적재에 사용한 provider, model, dimension,
version과 모두 같아야 한다. Docker Compose 실행 시 Neo4j와 Qdrant 주소는
컨테이너 내부 주소로 자동 덮어쓴다.

## 직접 실행

Python 3.11 이상이 필요하다.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
set -a
source ../.env
set +a
uvicorn linkpaper.main:app --reload
```

직접 실행할 때는 위와 같이 루트 `.env`를 현재 셸에 내보내야 한다. 또는 같은
설정을 `backend/.env`에 두면 `Settings`가 자동으로 읽는다.

테스트는 다음 명령으로 실행한다.

```bash
pytest
```

## 현재까지 완료된 작업

- FastAPI 애플리케이션 팩토리와 API 라우터 구성
- 가벼운 모듈러 모놀리스 패키지 경계 구성
- Chat SSE API와 OpenAI Responses API 스트리밍 구현
- OpenAI 임베딩과 Hugging Face Papers Markdown 조회 구현
- 선택 논문 단일 인메모리 온라인 인덱싱·검색 구현
- 검색 근거를 답변 생성에 전달하는 질의응답 파이프라인 구현
- 교체 가능한 `RetrievalBackend` 계약 정의
- 논문 분석 및 별도 GraphRAG 파이프라인 골격 생성
- 모듈별 `service.py`, `models.py` 골격 생성
- FastAPI 의존성 팩토리에서 파이프라인 조립
- 공통 설정, 예외, 로깅 골격 생성
- FastAPI, Neo4j, Qdrant, PostgreSQL Docker Compose 구성
- Qdrant payload DTO와 선택 논문·글로벌 범위 read 서비스 구현
- Neo4j `Paper`·`Author`·`Chunk`·`CITES` read DTO와 탐색 서비스 구현
- Qdrant 벡터 차원·거리 함수·임베딩 버전 검증 구현
- Neo4j 스키마 버전 검증 구현
- Neo4j·Qdrant mock 기반 read 연결 테스트 작성
- 헬스 체크 테스트 작성

## 다음 구현 순서

1. Docker에서 온라인 인덱싱·검색·생성 smoke test 완료
2. 청킹, 검색 threshold, citation 등 단일 논문 RAG 보강
3. `RetrievalBackend` 기반 MiniRAG adapter의 필요성과 효과 검증
4. `VectorReadService`와 `KnowledgeGraphService`를 사용하는 별도 GraphRAG 구현
5. PostgreSQL 대화 저장과 운영 관측성 구현

세부 테스트 절차와 우선순위별 TODO는
[`docs/pipeline-development.md`](../docs/pipeline-development.md)를 참고한다.
