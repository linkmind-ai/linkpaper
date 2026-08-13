from __future__ import annotations

from data_pipeline.models import PaperChunk, PaperMetadata, ProcessedPaper
from indexing_common.ids import canonicalize_paper, paper_id_for


def test_paper_id_for_distinguishes_arxiv_and_hf_ids() -> None:
    assert paper_id_for("1706.03762") == "arxiv:1706.03762"
    assert paper_id_for("arxiv:1706.03762") == "arxiv:1706.03762"
    assert paper_id_for("community-paper") == "hf:community-paper"


def test_canonicalize_paper_uses_shared_paper_and_chunk_ids() -> None:
    paper = ProcessedPaper(
        metadata=PaperMetadata(
            paper_id="1706.03762",
            arxiv_id="1706.03762",
            title="Attention Is All You Need",
            references=["1607.06450"],
            content_hash="paper-hash",
            source_version="hf-markdown",
        ),
        chunks=[
            PaperChunk(
                chunk_id="1706.03762:chunk:0:12345678",
                paper_id="1706.03762",
                chunk_index=0,
                text="Attention text",
                section="Introduction",
                section_index=0,
                char_count=14,
                content_hash="1234567890abcdef",
            )
        ],
    )

    result = canonicalize_paper(paper)

    assert result.metadata.paper_id == "arxiv:1706.03762"
    assert result.metadata.references == ["arxiv:1607.06450"]
    assert result.chunks[0].paper_id == "arxiv:1706.03762"
    assert result.chunks[0].chunk_id == "arxiv:1706.03762:chunk:0:12345678"
