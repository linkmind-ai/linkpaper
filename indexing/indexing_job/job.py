"""전처리와 두 저장소 적재 순서를 조율한다."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Self

from data_pipeline import DataPipeline, PipelineRun, ProcessedPaper
from graph_builder import GraphBuildResult, Neo4jGraphBuilder
from vector_builder import QdrantVectorBuilder, VectorBuildResult

logger = logging.getLogger(__name__)

IndexingMode = Literal["paper", "daily", "base"]


@dataclass(frozen=True)
class IndexingOutcome:
    paper_id: str
    graph: GraphBuildResult | None = None
    vector: VectorBuildResult | None = None
    stage: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.graph is not None and self.vector is not None


@dataclass(frozen=True)
class IndexingRun:
    mode: IndexingMode
    window: str
    in_global_corpus: bool
    outcomes: list[IndexingOutcome] = field(default_factory=list)

    @property
    def successes(self) -> list[IndexingOutcome]:
        return [outcome for outcome in self.outcomes if outcome.ok]

    @property
    def failures(self) -> list[IndexingOutcome]:
        return [outcome for outcome in self.outcomes if not outcome.ok]


class IndexingJob:
    """paper/daily/base를 동일한 논문 단위 적재 경로로 실행한다."""

    def __init__(
        self,
        pipeline: DataPipeline | None = None,
        graph_builder: Neo4jGraphBuilder | None = None,
        vector_builder: QdrantVectorBuilder | None = None,
    ) -> None:
        self.pipeline = pipeline or DataPipeline()
        self.graph_builder = graph_builder or Neo4jGraphBuilder()
        self.vector_builder = vector_builder or QdrantVectorBuilder()

    def paper(self, paper_id: str, *, in_global_corpus: bool = False) -> IndexingRun:
        """논문 한 편을 전처리하고 두 저장소에 적재한다."""
        self.graph_builder.ensure_schema()
        # 논문 한 편도 batch처럼 실패 결과로 격리해야 하므로 경계에서 모두 잡는다.
        try:
            paper = self.pipeline.process_paper_id(paper_id)
        except Exception as exc:  # noqa: BLE001
            outcome = self._failure(paper_id, "preprocess", exc)
        else:
            outcome = self._index_paper(paper, in_global_corpus)
        return IndexingRun(
            mode="paper",
            window=paper_id,
            in_global_corpus=in_global_corpus,
            outcomes=[outcome],
        )

    def daily(
        self,
        day: date | None = None,
        *,
        limit: int | None = None,
        in_global_corpus: bool = False,
    ) -> IndexingRun:
        run = self.pipeline.run_daily_papers(day, limit=limit)
        return self._index_pipeline_run(run, in_global_corpus=in_global_corpus)

    def base(
        self,
        year: int | None = None,
        month: int | None = None,
        *,
        limit: int | None = None,
    ) -> IndexingRun:
        run = self.pipeline.run_base_corpus(year, month, limit=limit)
        # base는 전체 검색의 기준 코퍼스이므로 별도 옵션 없이 글로벌로 적재한다.
        return self._index_pipeline_run(run, in_global_corpus=True)

    def _index_pipeline_run(
        self, run: PipelineRun, *, in_global_corpus: bool
    ) -> IndexingRun:
        self.graph_builder.ensure_schema()
        outcomes: list[IndexingOutcome] = []
        for pipeline_outcome in run.outcomes:
            if pipeline_outcome.paper is None:
                outcomes.append(
                    IndexingOutcome(
                        paper_id=pipeline_outcome.paper_id,
                        stage=pipeline_outcome.stage or "preprocess",
                        error=pipeline_outcome.error,
                    )
                )
                continue
            outcomes.append(self._index_paper(pipeline_outcome.paper, in_global_corpus))
        return IndexingRun(
            mode=run.mode,
            window=run.window,
            in_global_corpus=in_global_corpus,
            outcomes=outcomes,
        )

    def _index_paper(
        self, paper: ProcessedPaper, in_global_corpus: bool
    ) -> IndexingOutcome:
        raw_paper_id = paper.metadata.paper_id
        try:
            graph_result = self.graph_builder.upsert(
                paper, in_global_corpus=in_global_corpus
            )
        except Exception as exc:  # noqa: BLE001 - 저장소 실패를 논문 단위로 격리
            # Neo4j가 실패하면 Qdrant를 호출하지 않아 dangling chunk를 방지한다.
            return self._failure(raw_paper_id, "graph", exc)

        try:
            # Qdrant point의 chunk_id가 이미 Neo4j에 존재한 뒤에만 벡터를 쓴다.
            vector_result = self.vector_builder.upsert(
                paper, in_global_corpus=in_global_corpus
            )
        except Exception as exc:
            logger.exception("Qdrant 적재 실패 paper_id=%s", raw_paper_id)
            return IndexingOutcome(
                paper_id=graph_result.paper_id,
                graph=graph_result,
                stage="vector",
                error=f"{type(exc).__name__}: {exc}",
            )

        return IndexingOutcome(
            paper_id=graph_result.paper_id,
            graph=graph_result,
            vector=vector_result,
        )

    @staticmethod
    def _failure(paper_id: str, stage: str, exc: Exception) -> IndexingOutcome:
        logger.exception("인덱싱 실패 paper_id=%s stage=%s", paper_id, stage)
        return IndexingOutcome(
            paper_id=paper_id,
            stage=stage,
            error=f"{type(exc).__name__}: {exc}",
        )

    def close(self) -> None:
        # 생성 순서의 역순으로 외부 연결을 닫는다.
        self.vector_builder.close()
        self.graph_builder.close()
        self.pipeline.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
