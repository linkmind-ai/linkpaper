"""Data Pipeline 통합 테스트.

Client와 Preprocessor를 대역으로 바꿔 외부 호출 없이 전체 흐름을 돌린다.
"""

from __future__ import annotations

from datetime import date

import pytest

from data_pipeline.chunker import Chunker
from data_pipeline.exceptions import PreprocessingError
from data_pipeline.metadata_curator import MetadataCurator
from data_pipeline.models import PaperMarkdown, PaperMetadata
from data_pipeline.pipeline import DataPipeline


class StubClient:
    def __init__(self, papers: list[PaperMetadata]) -> None:
        self.papers = papers
        self.calls: list[str] = []

    def get_paper(self, paper_id: str) -> PaperMetadata:
        self.calls.append(f"get:{paper_id}")
        return next(paper for paper in self.papers if paper.paper_id == paper_id)

    def list_daily_papers(self, day: date | None = None) -> list[PaperMetadata]:
        self.calls.append(f"daily:{day}")
        return list(self.papers)

    def list_papers_in_month(self, year=None, month=None) -> list[PaperMetadata]:
        self.calls.append(f"month:{year}-{month}")
        return list(self.papers)

    def close(self) -> None:
        self.calls.append("close")


class StubPreprocessor:
    def __init__(self, markdown: str, failing_ids: set[str] | None = None) -> None:
        self.markdown = markdown
        self.failing_ids = failing_ids or set()

    def to_markdown(self, metadata: PaperMetadata) -> PaperMarkdown:
        if metadata.paper_id in self.failing_ids:
            raise PreprocessingError(f"{metadata.paper_id}: 본문을 확보하지 못했습니다")
        return PaperMarkdown(
            paper_id=metadata.paper_id, text=self.markdown, source="hf-markdown"
        )

    def close(self) -> None:
        return None


@pytest.fixture
def build_pipeline(settings, paper_markdown):
    def _build(papers: list[PaperMetadata], failing_ids: set[str] | None = None):
        return DataPipeline(
            settings=settings,
            client=StubClient(papers),
            preprocessor=StubPreprocessor(paper_markdown, failing_ids),
            chunker=Chunker(settings),
            curator=MetadataCurator(),
        )

    return _build


def other(paper_id: str) -> PaperMetadata:
    return PaperMetadata(
        paper_id=paper_id,
        arxiv_id=paper_id,
        title=f"Paper {paper_id}",
        source_url=f"https://huggingface.co/papers/{paper_id}",
        pdf_url=f"https://arxiv.org/pdf/{paper_id}",
    )


def test_process_paper_returns_metadata_and_chunks(build_pipeline, metadata) -> None:
    result = build_pipeline([metadata]).process_paper(metadata)

    # 최종 메타데이터: 초기 값 + 참고문헌에서 뽑은 references
    assert result.metadata.paper_id == "2401.00001"
    assert result.metadata.title == "Section-aware Chunking"
    assert "1607.06450" in result.metadata.references
    assert "1610.02357" in result.metadata.references
    assert result.metadata.source_version == "hf-markdown"
    assert result.metadata.content_hash

    # 청크: 논문과 섹션을 항상 식별할 수 있다
    assert result.chunks
    assert {chunk.paper_id for chunk in result.chunks} == {"2401.00001"}
    assert all(chunk.section for chunk in result.chunks)
    assert any(chunk.is_references for chunk in result.chunks)


def test_process_paper_id_goes_through_the_client(build_pipeline, metadata) -> None:
    pipeline = build_pipeline([metadata])

    pipeline.process_paper_id("2401.00001")

    assert pipeline.client.calls == ["get:2401.00001"]


def test_one_failing_paper_does_not_stop_the_batch(build_pipeline, metadata) -> None:
    papers = [metadata, other("2401.00002"), other("2401.00003")]
    pipeline = build_pipeline(papers, failing_ids={"2401.00002"})

    run = pipeline.run_daily_papers(date(2026, 8, 8))

    assert len(run.outcomes) == 3
    assert [paper.metadata.paper_id for paper in run.papers] == [
        "2401.00001",
        "2401.00003",
    ]
    assert len(run.failures) == 1
    failure = run.failures[0]
    assert failure.paper_id == "2401.00002"
    assert failure.stage == "preprocess"
    assert "PreprocessingError" in (failure.error or "")


def test_daily_and_base_runs_share_the_same_paper_processing(
    build_pipeline, metadata
) -> None:
    papers = [metadata, other("2401.00002")]

    daily = build_pipeline(papers).run_daily_papers(date(2026, 8, 8))
    base = build_pipeline(papers).run_base_corpus(2026, 8)

    assert daily.mode == "daily" and daily.window == "2026-08-08"
    assert base.mode == "base" and base.window == "2026-08"
    assert [paper.metadata.paper_id for paper in daily.papers] == [
        paper.metadata.paper_id for paper in base.papers
    ]
    assert [len(paper.chunks) for paper in daily.papers] == [
        len(paper.chunks) for paper in base.papers
    ]


def test_limit_caps_the_batch(build_pipeline, metadata) -> None:
    papers = [metadata, other("2401.00002"), other("2401.00003")]

    run = build_pipeline(papers).run_base_corpus(2026, 8, limit=2)

    assert len(run.outcomes) == 2


def test_process_streams_outcomes_without_collecting(build_pipeline, metadata) -> None:
    """Job이 결과를 하나씩 받아 Graph Builder로 넘길 수 있어야 한다."""
    papers = [metadata, other("2401.00002")]
    pipeline = build_pipeline(papers, failing_ids={"2401.00002"})

    outcomes = pipeline.process(papers)

    first = next(outcomes)
    assert first.ok and first.paper is not None
    second = next(outcomes)
    assert not second.ok and second.paper is None


def test_close_releases_components(build_pipeline, metadata) -> None:
    pipeline = build_pipeline([metadata])

    with pipeline:
        pass

    assert "close" in pipeline.client.calls
