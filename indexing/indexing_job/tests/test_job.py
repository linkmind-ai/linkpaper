from __future__ import annotations

from datetime import UTC, datetime

from data_pipeline.models import (
    PaperChunk,
    PaperMetadata,
    PaperOutcome,
    PipelineRun,
    ProcessedPaper,
)
from graph_builder import GraphBuildResult
from indexing_job import IndexingJob
from vector_builder import VectorBuildResult


def sample_paper(paper_id: str = "1706.03762") -> ProcessedPaper:
    return ProcessedPaper(
        metadata=PaperMetadata(
            paper_id=paper_id,
            arxiv_id=paper_id,
            title="Paper",
            content_hash="paper-hash",
            source_version="hf-markdown",
        ),
        chunks=[
            PaperChunk(
                chunk_id=f"{paper_id}:chunk:0:aaaaaaaa",
                paper_id=paper_id,
                chunk_index=0,
                text="chunk",
                section="Intro",
                section_index=0,
                char_count=5,
                content_hash="a" * 64,
            )
        ],
    )


class FakePipeline:
    def __init__(self, paper: ProcessedPaper) -> None:
        self.paper_value = paper

    def process_paper_id(self, paper_id: str) -> ProcessedPaper:
        return self.paper_value

    def run_daily_papers(self, day=None, limit=None) -> PipelineRun:
        now = datetime.now(UTC)
        return PipelineRun(
            mode="daily",
            window="2026-08-12",
            started_at=now,
            finished_at=now,
            outcomes=[
                PaperOutcome(
                    paper_id=self.paper_value.metadata.paper_id, paper=self.paper_value
                )
            ],
        )

    def run_base_corpus(self, year=None, month=None, limit=None) -> PipelineRun:
        now = datetime.now(UTC)
        return PipelineRun(
            mode="base",
            window="2026-07",
            started_at=now,
            finished_at=now,
            outcomes=[
                PaperOutcome(
                    paper_id=self.paper_value.metadata.paper_id, paper=self.paper_value
                )
            ],
        )

    def close(self) -> None:
        return None


class FakeGraphBuilder:
    def __init__(self, events: list[str], fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    def ensure_schema(self) -> None:
        self.events.append("schema")

    def upsert(self, paper, *, in_global_corpus=False) -> GraphBuildResult:
        self.events.append(f"graph:{in_global_corpus}")
        if self.fail:
            raise RuntimeError("neo4j unavailable")
        return GraphBuildResult("arxiv:1706.03762", 1, 0, 0)

    def close(self) -> None:
        return None


class FakeVectorBuilder:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def upsert(self, paper, *, in_global_corpus=False) -> VectorBuildResult:
        self.events.append(f"vector:{in_global_corpus}")
        return VectorBuildResult("arxiv:1706.03762", 1, 0)

    def close(self) -> None:
        return None


def build_job(events: list[str], *, graph_fails: bool = False) -> IndexingJob:
    return IndexingJob(
        pipeline=FakePipeline(sample_paper()),
        graph_builder=FakeGraphBuilder(events, fail=graph_fails),
        vector_builder=FakeVectorBuilder(events),
    )


def test_paper_indexes_neo4j_before_qdrant() -> None:
    events: list[str] = []

    run = build_job(events).paper("1706.03762")

    assert not run.failures
    assert events == ["schema", "graph:False", "vector:False"]


def test_graph_failure_does_not_write_qdrant() -> None:
    events: list[str] = []

    run = build_job(events, graph_fails=True).paper("1706.03762")

    assert run.failures[0].stage == "graph"
    assert events == ["schema", "graph:False"]


def test_base_is_automatically_global() -> None:
    events: list[str] = []

    run = build_job(events).base(2026, 7)

    assert run.in_global_corpus is True
    assert events == ["schema", "graph:True", "vector:True"]
