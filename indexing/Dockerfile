FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY data_pipeline ./data_pipeline
COPY graph_builder ./graph_builder
COPY indexing_common ./indexing_common
COPY indexing_job ./indexing_job
COPY vector_builder ./vector_builder
RUN pip install --no-cache-dir .

# 배치 작업이라 로그가 버퍼에 갇히면 실행 중 진행 상황을 볼 수 없다.
ENV PYTHONUNBUFFERED=1

# 외부에서 받은 PDF를 네이티브 파서(PyMuPDF)로 여는 컨테이너라 root로 돌리지 않는다.
# 임시 PDF는 /tmp에만 쓰므로 별도 쓰기 권한이 필요하지 않다.
RUN useradd --create-home --uid 1000 indexing
USER indexing

# 서버가 아니라 실행하고 끝나는 Job이다. Neo4j 적재 후 Qdrant를 적재한다.
#   docker run --rm linkpaper-indexing paper 1706.03762
#   docker run --rm linkpaper-indexing daily --date 2026-08-08
#   docker run --rm linkpaper-indexing base --month 2026-08 --limit 10
ENTRYPOINT ["python", "-m", "indexing_job"]
CMD ["daily"]
