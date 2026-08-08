"""Metadata Curator 테스트."""

from __future__ import annotations

from data_pipeline.metadata_curator import MetadataCurator, extract_arxiv_ids
from data_pipeline.models import PaperMarkdown


def test_extracts_common_arxiv_notations() -> None:
    text = """
    [1] Ba et al. Layer normalization. arXiv preprint arXiv:1607.06450, 2016.
    [2] Chollet. Xception. https://arxiv.org/abs/1610.02357, 2016.
    [3] Kim et al. Structured attention. arXiv: 1702.00887, 2017.
    [4] Someone. A paper. https://arxiv.org/pdf/2401.12345v3, 2024.
    [5] Old style. arXiv:hep-th/9901001, 1999.
    """

    assert extract_arxiv_ids(text) == [
        "1607.06450",
        "1610.02357",
        "1702.00887",
        "2401.12345",
        "hep-th/9901001",
    ]


def test_version_suffix_is_stripped_and_duplicates_merged() -> None:
    text = "arXiv:2401.12345v1 and arXiv:2401.12345v2 and https://arxiv.org/abs/2401.12345"

    assert extract_arxiv_ids(text) == ["2401.12345"]


def test_self_reference_is_excluded() -> None:
    text = "arXiv:2401.00001 arXiv:1607.06450"

    assert extract_arxiv_ids(text, exclude=("2401.00001", None)) == ["1607.06450"]


def test_non_arxiv_citations_are_ignored() -> None:
    text = "[7] Dyer et al. Recurrent neural network grammars. In Proc. of NAACL, 2016."

    assert extract_arxiv_ids(text) == []


def test_empty_reference_text_returns_empty_list() -> None:
    assert extract_arxiv_ids("") == []


def test_curate_merges_initial_metadata_with_references(metadata) -> None:
    markdown = PaperMarkdown(
        paper_id=metadata.paper_id, text="# Body\n\ncontent", source="hf-markdown"
    )

    curated = MetadataCurator().curate(
        metadata,
        references_text="see arXiv:1706.03762 and arXiv:1810.04805",
        markdown=markdown,
    )

    # 초기 메타데이터는 그대로 유지된다.
    assert curated.paper_id == metadata.paper_id
    assert curated.title == metadata.title
    assert curated.authors == metadata.authors
    # 큐레이션 결과가 더해진다.
    assert curated.references == ["1706.03762", "1810.04805"]
    assert curated.source_version == "hf-markdown"
    assert curated.content_hash == markdown.content_hash

    # 원본은 변경되지 않는다.
    assert metadata.references == []
    assert metadata.content_hash is None
