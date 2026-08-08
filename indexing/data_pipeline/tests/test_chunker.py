"""Chunker 테스트.

가장 조용히 깨지는 지점은 제목 인식이다. HF Markdown은 상위 섹션을 setext
형식으로 쓰기 때문에 `^#`만 보면 참고문헌 섹션을 통째로 놓치고, 그러면
`references`가 아무 오류 없이 빈 목록이 된다.
"""

from __future__ import annotations

from data_pipeline.chunker import Chunker, is_references_heading, split_sections

PAPER_ID = "2401.00001"


def test_setext_and_atx_headings_are_both_detected(paper_markdown: str) -> None:
    titles = [section.title for section in split_sections(paper_markdown)]

    # setext (`----` 밑줄) 상위 섹션
    assert "1 Introduction" in titles
    assert "2 Method" in titles
    assert "References" in titles
    # ATX 하위 섹션
    assert "2.1 Setup" in titles
    assert "Abstract" in titles
    # 첫 제목 앞의 저자 블록
    assert titles[0] == "Front Matter"


def test_heading_without_body_is_dropped() -> None:
    """본문 없이 하위 섹션만 여는 제목은 청크를 만들지 않으므로 섹션에서 뺀다.

    남겨두면 어떤 청크도 가리키지 않는 빈 섹션이 `section_index`만 밀어낸다.
    """
    sections = split_sections("## Method\n\n### 2.1 Setup\n\nbody text")

    assert [section.title for section in sections] == ["2.1 Setup"]
    assert sections[0].index == 0


def test_code_fence_underline_is_not_a_heading(paper_markdown: str) -> None:
    titles = [section.title for section in split_sections(paper_markdown)]
    assert 'value = "not a heading"' not in titles


def test_references_heading_variants() -> None:
    assert is_references_heading("References")
    assert is_references_heading("7 References")
    assert is_references_heading("A.1 References")
    assert is_references_heading("Bibliography")
    assert is_references_heading("References and Notes")
    assert is_references_heading("참고문헌")

    # 'preference'가 'reference'로 잡히면 본문 섹션이 참고문헌이 된다.
    assert not is_references_heading("3 Preference Learning")
    assert not is_references_heading("Related Work")
    assert not is_references_heading("")


def test_reference_section_can_span_multiple_chunks(
    settings, paper_markdown: str
) -> None:
    result = Chunker(settings).chunk(PAPER_ID, paper_markdown)

    reference_chunks = [chunk for chunk in result.chunks if chunk.is_references]
    assert len(reference_chunks) > 1, "참고문헌이 한 청크뿐이면 이 테스트는 의미가 없다"
    assert {chunk.section for chunk in reference_chunks} == {"References"}

    # 본문 섹션이 참고문헌으로 잘못 분류되지 않았는지 확인한다.
    assert all(
        not chunk.is_references
        for chunk in result.chunks
        if chunk.section == "3 Preference Learning"
    )


def test_references_text_keeps_raw_links(settings, paper_markdown: str) -> None:
    """참고문헌 원문은 정리 전 상태여야 arXiv 링크가 살아남는다."""
    result = Chunker(settings).chunk(PAPER_ID, paper_markdown)

    assert "https://arxiv.org/abs/1610.02357" in result.references_text
    assert "arXiv:1607.06450" in result.references_text


def test_chunk_text_is_cleaned(settings, paper_markdown: str) -> None:
    result = Chunker(settings).chunk(PAPER_ID, paper_markdown)
    intro = " ".join(
        chunk.text for chunk in result.chunks if chunk.section == "1 Introduction"
    )

    # 인용 앵커는 표시 문자열만 남고 URL은 사라진다.
    assert "[13]" in intro
    assert "bib.bib13" not in intro
    # 이미지 줄은 통째로 제거된다.
    assert "figures/f1.png" not in intro


def test_chunk_ids_follow_schema_and_are_unique(settings, paper_markdown: str) -> None:
    chunks = Chunker(settings).chunk(PAPER_ID, paper_markdown).chunks

    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    for index, chunk in enumerate(chunks):
        # neo4j-schema.md 7.2: <paperId>:chunk:<chunkIndex>:<contentHash-prefix>
        assert chunk.chunk_id == f"{PAPER_ID}:chunk:{index}:{chunk.content_hash[:8]}"
        assert chunk.chunk_index == index


def test_every_chunk_identifies_paper_and_section(settings, paper_markdown: str) -> None:
    chunks = Chunker(settings).chunk(PAPER_ID, paper_markdown).chunks

    assert chunks
    for chunk in chunks:
        assert chunk.paper_id == PAPER_ID
        assert chunk.section
        assert chunk.section_index >= 0
        assert chunk.text.strip()
        assert chunk.char_count == len(chunk.text)


def test_chunks_do_not_cross_section_boundaries(settings) -> None:
    markdown = "\n".join(
        [
            "# Alpha",
            "alpha body sentence.",
            "",
            "# Beta",
            "beta body sentence.",
        ]
    )
    chunks = Chunker(settings).chunk(PAPER_ID, markdown).chunks

    by_section = {chunk.section: chunk.text for chunk in chunks}
    assert "beta" not in by_section["Alpha"]
    assert "alpha" not in by_section["Beta"]


def test_pymupdf_bold_headings_are_normalized(settings) -> None:
    """pymupdf4llm은 제목을 `## **1 Introduction**` 처럼 굵게 감싸서 낸다.

    그대로 두면 같은 논문이라도 본문을 어느 경로로 받았는지에 따라 섹션 이름이
    달라진다.
    """
    markdown = "## **1 Introduction**\n\nbody text\n\n## **References**\n\n[1] arXiv:1607.06450"

    result = Chunker(settings).chunk(PAPER_ID, markdown)
    sections = [chunk.section for chunk in result.chunks]

    assert "1 Introduction" in sections
    assert "References" in sections
    assert any(chunk.is_references for chunk in result.chunks)


def test_inline_references_marker_is_promoted_to_a_section(settings) -> None:
    """단이 나뉜 PDF에서는 참고문헌 제목이 본문 중간에 남는다.

    실제 pymupdf4llm 출력에서 관찰된 형태다. 이 경우를 놓치면 references가
    오류 없이 빈 목록이 된다.
    """
    markdown = (
        "## **7 Conclusion**\n\n"
        "We presented the Transformer.\n\n"
        "**Acknowledgements** We are grateful to our colleagues. "
        "**References** [1] Jimmy Lei Ba. Layer normalization. arXiv preprint arXiv:1607.06450, 2016.\n\n"
        "- [2] Dzmitry Bahdanau. Neural machine translation. arXiv:1409.0473, 2014.\n"
    )

    result = Chunker(settings).chunk(PAPER_ID, markdown)

    assert "arXiv:1607.06450" in result.references_text
    assert "1409.0473" in result.references_text
    reference_chunks = [chunk for chunk in result.chunks if chunk.is_references]
    assert reference_chunks
    assert reference_chunks[0].section == "References"
    # 승격 지점 앞의 본문은 참고문헌으로 넘어가지 않는다.
    assert "We presented the Transformer" not in result.references_text


def test_inline_promotion_requires_a_numbered_citation(settings) -> None:
    """본문에서 참고문헌을 단순히 언급한 문장까지 잘라내면 안 된다."""
    markdown = "# Method\n\nWe follow the References section of prior work for notation."

    result = Chunker(settings).chunk(PAPER_ID, markdown)

    assert result.references_text == ""
    assert all(not chunk.is_references for chunk in result.chunks)


def test_bare_references_line_without_any_heading_is_detected(settings) -> None:
    """제목 표기가 하나도 없는 논문에서도 참고문헌은 찾아야 한다.

    저자-연도 인용을 쓰면 `[1]` 형태가 없으므로 줄 단위 표기로 인식한다.
    """
    body = "We study safety inference scaling in detail. " * 40
    markdown = f"Saffron-1: Safety Inference Scaling\n\n{body}\n\nReferences\n\nAndriushchenko et al. [2025] arXiv:2404.02151\n"

    result = Chunker(settings).chunk(PAPER_ID, markdown)

    assert "2404.02151" in result.references_text
    assert any(chunk.is_references for chunk in result.chunks)


def test_table_of_contents_entry_is_not_promoted(settings) -> None:
    """앞쪽 목차의 'References' 줄을 잡으면 논문 대부분이 참고문헌이 된다.

    그러면 본문에 언급된 arXiv ID가 인용 관계로 둔갑한다.
    """
    body = "The proposed method cites arXiv:1234.56789 as motivation. " * 40
    markdown = f"Contents\n\n1 Introduction\n\nReferences\n\n{body}"

    result = Chunker(settings).chunk(PAPER_ID, markdown)

    assert result.references_text == ""
    assert all(not chunk.is_references for chunk in result.chunks)


def test_paper_without_references_returns_empty_reference_text(settings) -> None:
    result = Chunker(settings).chunk(PAPER_ID, "# Introduction\n\nno bibliography here.")

    assert result.references_text == ""
    assert result.chunks
    assert all(not chunk.is_references for chunk in result.chunks)
