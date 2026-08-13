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
- `GET /api/v1/papers`
- `POST /api/v1/papers/{paper_id}/analysis`
- `POST /api/v1/conversations/{conversation_id}/messages`

헬스 체크를 제외한 라우트는 아직 구현 전이므로 `501 Not Implemented`를
반환한다.

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
├── ConversationService
├── RetrievalService
├── KnowledgeGraphService
└── GenerationService
```

현재 파이프라인은 의존성만 정의한 골격이며 내부 실행 로직은 구현 예정이다.

### Modules

각 모듈은 자신의 기능과 내부 데이터 모델을 소유한다.

```text
modules/
├── papers/              # 논문 검색과 메타데이터
├── documents/           # 적재된 논문·청크와 준비 상태 조회 골격
├── vector_read/         # Qdrant 선택 논문·글로벌 벡터 조회
├── knowledge_graph/     # Neo4j 논문 그래프 조회와 인용 확장
├── retrieval/           # 벡터·그래프 검색 조율과 결과 결합 골격
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

외부 시스템과 연결되는 구현을 배치한다. 현재는 구현 전인
`OpenAIClient` 골격만 존재한다. Neo4j와 Qdrant 연결은 각각 저장소 스키마를
소유한 `knowledge_graph/`, `vector_read/` 모듈 내부에 둔다.

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

현재 `KnowledgeGraphService`는 파이프라인에 주입되어 있다. `VectorReadService`를
`RetrievalService`에 연결하고 질의 임베딩을 생성하는 작업은 다음 구현 단계다.

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
- 논문 분석 및 GraphRAG 질의응답 파이프라인 골격 생성
- 모듈별 `service.py`, `models.py` 골격 생성
- FastAPI 의존성 팩토리에서 파이프라인 조립
- OpenAI 클라이언트 어댑터 골격 생성
- 공통 설정, 예외, 로깅 골격 생성
- FastAPI, Neo4j, Qdrant, PostgreSQL Docker Compose 구성
- Qdrant payload DTO와 선택 논문·글로벌 범위 read 서비스 구현
- Neo4j `Paper`·`Author`·`Chunk`·`CITES` read DTO와 탐색 서비스 구현
- Qdrant 벡터 차원·거리 함수·임베딩 버전 검증 구현
- Neo4j 스키마 버전 검증 구현
- Neo4j·Qdrant mock 기반 read 연결 테스트 작성
- 헬스 체크 테스트 작성

## 다음 구현 순서

1. Hugging Face Papers 검색 어댑터와 `PaperService` 구현
2. 적재 모델과 동일한 설정을 사용하는 온라인 질의 임베딩 구현
3. `VectorReadService`를 `RetrievalService`에 연결
4. Qdrant 검색 결과의 `chunk_id`를 이용한 Neo4j 그래프 확장과 결과 결합
5. PostgreSQL 대화 저장과 근거 기반 답변 생성 구현
