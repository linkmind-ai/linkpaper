# Pipeline 개발 현황

> 상태: 온라인 단일 논문 RAG MVP 구현
>
> 범위: Chat SSE, 온라인 인메모리 인덱싱·검색, OpenAI 답변 생성

## 1. 목적

현재 파이프라인은 사용자가 선택한 논문 한 편을 요청 시점에 인덱싱하고,
검색한 본문을 근거로 답변하는 온라인 RAG를 제공한다.

사전에 구축한 Qdrant·Neo4j 인덱스를 사용하는 글로벌 GraphRAG는 이 흐름에
섞지 않는다. 관련 모듈인 `vector_read/`, `knowledge_graph/`, `retrieval/`은
보존하며 향후 별도 GraphRAG 파이프라인에서 사용한다.

## 2. 현재 요청 흐름

```text
POST /api/v1/chat/stream
  → QuestionAnsweringPipeline
  → OnlineRetrievalService
      → HuggingFaceMarkdownClient
      → InMemoryRetrievalBackend
          → OpenAI embeddings
  → GenerationService
      → OpenAI Responses API
  → token / done SSE events
```

첫 질문에서는 다음 작업을 수행한다.

1. `paper_id`로 Hugging Face Papers Markdown을 가져온다.
2. Markdown을 겹침이 있는 문자 단위 청크로 나눈다.
3. OpenAI Embeddings API로 모든 청크의 벡터를 생성한다.
4. 청크와 벡터를 백엔드 프로세스 메모리에 보관한다.
5. 질문을 임베딩하고 cosine 유사도로 상위 청크를 찾는다.
6. 검색 청크를 `GenerationRequest.context`에 넣는다.
7. OpenAI Responses API 출력을 SSE token 이벤트로 전달한다.

같은 논문의 다음 질문은 1~4단계를 생략하고 메모리 인덱스를 재사용한다.
다른 `paper_id`가 들어오면 기존 인덱스를 새 논문 인덱스로 교체한다.

## 3. 구현 범위

### 3.1 Chat API

- `POST /api/v1/chat/stream`
- 요청 필드: `paperId`, `message`, `history`
- 응답 형식: `text/event-stream`
- 현재 발생 이벤트: `token`, `done`, `error`
- 요청의 마지막 history가 현재 질문과 같으면 중복 제거

### 3.2 OpenAI 어댑터

`OpenAIClient`가 외부 SDK 형식을 애플리케이션에서 숨긴다.

- `stream_text()`: Responses API의 `response.output_text.delta`만 반환
- `embed_texts()`: 입력 순서를 유지한 임베딩 벡터 반환
- API 키와 모델은 환경변수로 주입
- 테스트에서 SDK client를 fake로 교체 가능

### 3.3 온라인 본문 확보

`HuggingFaceMarkdownClient`가 다음 주소에서 본문을 가져온다.

```text
https://huggingface.co/papers/{paper_id}.md
```

HTML 오류 응답과 너무 짧은 본문은 거부한다. 현재 온라인 경로에는 PDF 변환
fallback이 없다.

### 3.4 인메모리 검색

`InMemoryRetrievalBackend`가 다음 책임을 가진다.

- 본문 청킹
- 청크 임베딩 생성
- 결정적 chunk ID 생성
- 질문과 청크의 cosine 유사도 계산
- 점수 기준 상위 k개 청크 반환
- 현재 인덱스 초기화

기본 설정은 다음과 같다.

| 설정 | 기본값 | 설명 |
|---|---:|---|
| `ONLINE_CHUNK_SIZE` | 2000 | 청크 문자 수 |
| `ONLINE_CHUNK_OVERLAP` | 200 | 인접 청크 중복 문자 수 |
| `ONLINE_RETRIEVAL_LIMIT` | 5 | 답변에 전달할 최대 청크 수 |

`OnlineRetrievalService`는 현재 논문 확인, Markdown 확보, 인덱스 교체와 검색
순서를 조율한다. 단일 인덱스 교체 중 다른 요청이 섞이지 않도록 lock을 쓴다.

### 3.5 교체 가능한 검색 backend

파이프라인은 인메모리 자료구조를 직접 다루지 않는다. 검색 backend는 다음
계약을 따른다.

```python
class RetrievalBackend(Protocol):
    @property
    def paper_id(self) -> str | None: ...

    async def index(self, paper_id: str, content: str) -> None: ...
    async def search(self, paper_id: str, query: str, limit: int): ...
    async def reset(self) -> None: ...
```

현재는 `InMemoryRetrievalBackend`를 주입한다. 이후 MiniRAG나 다른 검색기로
교체할 경우 같은 계약을 구현하고 `api/dependencies.py`의 조립 코드만 바꾼다.

## 4. 코드 위치

```text
backend/src/linkpaper/
├── api/routes/chat.py                         # HTTP·SSE 경계
├── api/dependencies.py                        # 구현체 조립
├── pipelines/question_answering.py            # 검색 → 생성 순서
├── adapters/llm/openai_client.py              # 생성·임베딩 API
├── adapters/papers/huggingface_markdown.py    # 논문 Markdown 조회
├── modules/generation/                        # 프롬프트와 답변 생성
└── modules/online_retrieval/
    ├── backend.py                             # 교체 계약
    ├── models.py                              # 검색 결과 모델
    ├── in_memory.py                           # 현재 검색 구현
    └── service.py                             # 인덱스 생명주기
```

## 5. 테스트 방법

### 5.1 단위 테스트

Python 3.11 이상 환경에서 실행한다.

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

pytest -q \
  tests/test_openai_client.py \
  tests/test_generation.py \
  tests/test_online_retrieval.py \
  tests/test_chat_stream.py
```

단위 테스트는 실제 OpenAI나 Hugging Face를 호출하지 않는다.

- OpenAI streaming event 변환
- 임베딩 요청과 응답 순서
- 생성 프롬프트에 history와 context 포함
- cosine 검색 결과 순위
- 같은 논문의 인덱스 재사용
- Chat SSE `token → done` 계약

### 5.2 Docker smoke test

루트 `.env`에 실제 키를 설정한다. 키는 저장소에 커밋하지 않는다.

```dotenv
OPENAI_API_KEY="sk-..."
OPENAI_CHAT_MODEL="gpt-5.6-luna"
```

백엔드를 다시 빌드한다.

```bash
sudo docker compose up -d --build --force-recreate backend
sudo docker compose ps
curl http://localhost:8000/api/v1/health
```

첫 질문으로 온라인 인덱싱과 검색·생성을 함께 확인한다.

```bash
curl -N http://localhost:8000/api/v1/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{
    "paperId": "1706.03762",
    "message": "Transformer의 핵심 기여는?",
    "history": []
  }'
```

정상 응답은 여러 `token` 이벤트 뒤 `done`으로 끝난다.

```text
data: {"text":"...","type":"token"}

data: {"type":"done"}
```

같은 요청을 한 번 더 실행해 논문 다운로드와 청크 임베딩을 반복하지 않고
메모리 인덱스를 재사용하는지 로그와 응답시간으로 확인한다.

```bash
sudo docker compose logs backend --tail=200
```

## 6. 현재 제약

- 백엔드 프로세스가 재시작되면 인메모리 인덱스가 사라진다.
- 서비스 전체에서 현재 논문 한 편의 인덱스만 유지한다.
- 여러 Uvicorn worker를 사용하면 worker마다 별도 인덱스를 가진다.
- 다른 논문 요청이 들어오면 기존 인덱스를 교체한다.
- 첫 질문은 Markdown 다운로드와 전체 청크 임베딩으로 지연시간과 비용이 크다.
- Markdown 청킹은 섹션·토큰이 아닌 단순 문자 길이 기준이다.
- HF Markdown이 없는 논문의 PDF fallback은 아직 없다.
- 검색 점수 threshold와 빈 검색 결과 정책이 아직 없다.
- 현재 SSE 응답에는 실제 검색 청크 citation을 노출하지 않는다.

## 7. 향후 TODO

### P0 — 현재 MVP 검증

- [ ] Docker 이미지 재빌드 후 신규 온라인 검색 경로 smoke test
- [ ] 첫 질문과 동일 논문 두 번째 질문의 지연시간 비교
- [ ] OpenAI embedding 요청량과 비용 확인
- [ ] 전체 backend pytest 실행
- [ ] HF Markdown 오류가 SSE `error`로 변환되는지 확인

### P1 — 온라인 단일 논문 RAG 보강

- [ ] 섹션 또는 토큰 기반 chunker로 교체
- [ ] 임베딩 batch 크기와 timeout 설정
- [ ] 검색 score threshold와 빈 결과 fallback 정의
- [ ] 검색 청크 ID·점수를 citation 이벤트로 반환
- [ ] 명시적인 index/reset/status API 검토
- [ ] PDF → Markdown fallback 검토
- [ ] 애플리케이션 종료 시 HTTP·OpenAI client 정리
- [ ] 인덱싱 중 진행 상태와 오류 모델 정의

### P2 — 검색 backend 교체 가능성 검증

- [ ] `RetrievalBackend` 계약으로 MiniRAG adapter PoC
- [ ] 인메모리 backend와 MiniRAG 품질·비용·지연 비교
- [ ] 다중 사용자 또는 다중 worker가 필요할 때 영속 backend 도입

### P3 — 별도 GraphRAG 파이프라인

- [ ] `GraphQuestionAnsweringPipeline` 추가
- [ ] 질의 임베딩과 `VectorReadService` 연결
- [ ] Qdrant 선택·글로벌 범위 검색 구현
- [ ] Qdrant `chunk_id`를 이용한 `KnowledgeGraphService` 확장
- [ ] 벡터·그래프 결과 융합 및 재정렬
- [ ] 온라인 단일 논문 RAG와 GraphRAG 사이의 라우팅 정책
- [ ] 근거 citation과 research flow 이벤트 구현

GraphRAG 단계에서도 기존 모듈을 재사용한다.

```text
GraphQuestionAnsweringPipeline
└── RetrievalService
    ├── VectorReadService       # Qdrant read
    └── KnowledgeGraphService   # Neo4j read
```

### P4 — 대화와 운영

- [ ] PostgreSQL conversation/message 저장
- [ ] 요청 취소와 timeout 전파
- [ ] 인덱싱·검색·생성 단계별 latency와 token usage 로깅
- [ ] retrieval/generation 평가 하네스 연결
- [ ] API key와 사용자별 rate limit 정책
