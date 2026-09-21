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


def test_reference_word_inside_a_body_heading_is_not_a_references_section() -> None:
    """낱말이 제목 중간에 나오면 참고문헌 제목이 아니다.

    참고문헌으로 잘못 잡히면 그 섹션이 임베딩 대상에서 통째로 빠지고, 본문에
    언급된 arXiv ID가 인용 관계로 둔갑한다.
    """
    assert not is_references_heading("Comparison with reference implementations")
    assert not is_references_heading("5 Ablations on bibliography extraction")


def test_reference_section_is_marked_and_isolated(settings, paper_markdown: str) -> None:
    result = Chunker(settings).chunk(PAPER_ID, paper_markdown)

    reference_chunks = [chunk for chunk in result.chunks if chunk.is_references]
    assert reference_chunks
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


def test_section_path_carries_the_parent_headings(settings, paper_markdown: str) -> None:
    """하위 섹션 청크는 어느 상위 섹션에 속하는지 알 수 있어야 한다.

    `section`만으로는 '2.1 Setup'이 '2 Method'의 하위라는 걸 알 수 없다.
    """
    chunks = Chunker(settings).chunk(PAPER_ID, paper_markdown).chunks
    by_section = {chunk.section: chunk.section_path for chunk in chunks}

    assert by_section["2.1 Setup"] == "2 Method > 2.1 Setup"
    assert by_section["2.2 Chunking"] == "2 Method > 2.2 Chunking"
    # 최상위 섹션은 경로가 자기 자신뿐이다.
    assert by_section["1 Introduction"] == "1 Introduction"
    # 첫 제목 앞의 본문은 상위 제목이 없다.
    assert by_section["Front Matter"] == "Front Matter"


def test_every_chunk_has_a_section_path(settings, paper_markdown: str) -> None:
    chunks = Chunker(settings).chunk(PAPER_ID, paper_markdown).chunks

    assert chunks
    for chunk in chunks:
        assert chunk.section_path
        # 경로의 마지막 항목이 곧 그 청크의 섹션이다.
        assert chunk.section_path.split(" > ")[-1] == chunk.section


def test_subsections_under_references_are_marked_as_references(settings) -> None:
    """참고문헌의 하위 섹션도 참고문헌이다. 아니면 임베딩 대상에 섞여 들어간다."""
    markdown = (
        "# References\n\n"
        "[1] Jimmy Lei Ba. Layer normalization. arXiv:1607.06450, 2016.\n\n"
        "## Additional citations\n\n"
        "[2] Dzmitry Bahdanau. Neural machine translation. arXiv:1409.0473, 2014.\n"
    )

    result = Chunker(settings).chunk(PAPER_ID, markdown)

    assert all(chunk.is_references for chunk in result.chunks)
    assert "1409.0473" in result.references_text


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


def test_explicit_appendix_heading_is_dropped(settings) -> None:
    markdown = (
        "# 1 Introduction\n\nBody text.\n\n"
        "# References\n\n[1] arXiv:2401.00001\n\n"
        "# Appendix\n\nAppendix intro.\n\n"
        "## A Training Details\n\nWe used a batch size of 32.\n"
    )
    chunks = Chunker(settings).chunk("2401.00001", markdown).chunks
    sections = {chunk.section for chunk in chunks}

    assert "Appendix" not in sections
    assert "A Training Details" not in sections
    assert "1 Introduction" in sections


def test_lettered_sections_after_references_are_dropped(settings) -> None:
    """`Appendix` 표기 없이 참고문헌 뒤에서 바로 A.1로 넘어가는 논문."""
    markdown = (
        "# III Method\n\nMethod body.\n\n"
        "## A Overview\n\nBody subsection A, before references.\n\n"
        "# References\n\n[1] arXiv:2401.00002\n\n"
        "# A.1 Network Architecture\n\nAppendix content here.\n\n"
        "# B Evaluation Protocol\n\nMore appendix content.\n"
    )
    chunks = Chunker(settings).chunk("2401.00001", markdown).chunks
    sections = {chunk.section for chunk in chunks}

    # 참고문헌 앞의 'A Overview'는 본문이므로 남는다.
    assert "A Overview" in sections
    assert "A.1 Network Architecture" not in sections
    assert "B Evaluation Protocol" not in sections


def test_references_after_appendix_are_still_collected(settings) -> None:
    """부록 뒤에 참고문헌이 오는 논문에서도 인용 추출이 유지돼야 한다."""
    markdown = (
        "# 1 Introduction\n\nBody text.\n\n"
        "# Appendix A\n\nAppendix body.\n\n"
        "# References\n\n[1] arXiv:2401.00002\n"
    )
    result = Chunker(settings).chunk("2401.00001", markdown)
    sections = {chunk.section for chunk in result.chunks}

    assert "Appendix A" not in sections
    assert "2401.00002" in result.references_text


def test_appendix_can_be_kept_by_setting(settings) -> None:
    markdown = (
        "# 1 Introduction\n\nBody text.\n\n"
        "# Appendix\n\nAppendix body that should survive.\n"
    )
    kept = settings.model_copy(update={"include_appendix": True})
    sections = {chunk.section for chunk in Chunker(kept).chunk("x", markdown).chunks}

    assert "Appendix" in sections


def test_a_section_becomes_one_chunk(settings) -> None:
    """길이로 자르지 않는다. 섹션 하나가 청크 하나다."""
    body = "This paragraph is part of the method section. " * 60  # 약 2,700자
    markdown = f"# 3 Method\n\n{body}\n"

    chunks = Chunker(settings).chunk(PAPER_ID, markdown).chunks

    assert len(chunks) == 1
    assert chunks[0].char_count > 2000
    assert chunks[0].section == "3 Method"


def test_section_over_the_safety_cap_is_split(settings) -> None:
    """임베딩 토큰 한도를 넘기지 않도록 상한에서만 나눈다."""
    capped = settings.model_copy(update={"max_chunk_chars": 500})
    body = "Sentence about the method. " * 80  # 약 2,160자
    markdown = f"# 3 Method\n\n{body}\n"

    chunks = Chunker(capped).chunk(PAPER_ID, markdown).chunks

    assert len(chunks) > 1
    assert all(chunk.char_count <= 500 for chunk in chunks)
    # 나뉘어도 어느 섹션에서 나왔는지는 유지된다.
    assert {chunk.section for chunk in chunks} == {"3 Method"}


def test_heading_markup_is_stripped(settings) -> None:
    markdown = (
        "# _B. SULAND_ _<u>v1</u> Dataset Organization_\n\n"
        "The audit identified missing annotations.\n"
    )
    chunks = Chunker(settings).chunk(PAPER_ID, markdown).chunks

    assert chunks[0].section == "B. SULAND v1 Dataset Organization"


def test_picture_text_block_is_removed(settings) -> None:
    """그림 OCR 텍스트는 검색에 쓸모가 없어 본문에서 제외한다."""
    markdown = (
        "# 4 Experiments\n\n"
        "Table 3 reports quantitative ablations.\n\n"
        "<!-- Start of picture text -->\n"
        "Ref Video<br>Pairs<br>Edge Only<br>Full Model<br>\n"
        "<!-- End of picture text -->\n\n"
        "Replacing cross-category pairs reduces the score.\n"
    )
    text = Chunker(settings).chunk(PAPER_ID, markdown).chunks[0].text

    assert "picture text" not in text
    assert "Ref Video" not in text
    assert "Table 3 reports" in text
    assert "Replacing cross-category pairs" in text


def test_sentence_fragment_is_not_treated_as_a_heading(settings) -> None:
    """굵은 강조 문장이 줄바꿈으로 잘려 뒷조각만 제목이 되는 경우."""
    markdown = (
        "# Introduction\n\n"
        "Our goal is to build a harness that adapts to different scenarios, model\n\n"
        "#### **families, and evaluation objectives.**\n\n"
        "However, applying a general-purpose agent leaves a systems challenge.\n"
    )
    chunks = Chunker(settings).chunk(PAPER_ID, markdown).chunks
    sections = {chunk.section for chunk in chunks}

    assert sections == {"Introduction"}
    joined = " ".join(chunk.text for chunk in chunks)
    assert "families, and evaluation objectives." in joined


def test_heading_inside_a_picture_text_block_is_removed(settings) -> None:
    """표를 OCR한 줄이 블록 안에서 제목 형태로 나오는 경우(2607.27201)."""
    markdown = (
        "# 7 Results\n\n"
        "Table 5 reports oracle interventions.\n\n"
        "<!-- Start of picture text -->\n"
        "# Configuration F1 vs. S6<br>O1 gold state 93.5<br>"
        "<!-- End of picture text -->\n\n"
        "Figure 8 shows the scenario study.\n"
    )
    chunks = Chunker(settings).chunk(PAPER_ID, markdown).chunks
    sections = {chunk.section for chunk in chunks}

    assert sections == {"7 Results"}
    joined = " ".join(chunk.text for chunk in chunks)
    assert "Configuration F1" not in joined
    assert "picture text" not in joined
    assert "Figure 8 shows" in joined


def test_author_line_is_not_a_section(settings) -> None:
    """표지의 저자 줄이 제목으로 승격되는 경우(2607.29679)."""
    markdown = (
        "# SCALING PROPERTIES OF TEXT CONDITIONING\n\n"
        "#### **Zilong Chen, Chaorui Deng, Kunchang Li, Hongyi Yuan** ByteDance Seed\n\n"
        "Figure 1 caption text lives here.\n\n"
        "### ABSTRACT\n\nWe study text conditioning.\n"
    )
    chunks = Chunker(settings).chunk(PAPER_ID, markdown).chunks
    sections = {chunk.section for chunk in chunks}

    assert sections == {"SCALING PROPERTIES OF TEXT CONDITIONING", "ABSTRACT"}
    # 강등된 줄은 버리지 않고 앞 섹션 본문으로 남는다.
    assert any("Zilong Chen" in chunk.text for chunk in chunks)


def test_body_heading_with_commas_is_kept(settings) -> None:
    """초록을 지난 뒤의 쉼표 많은 제목은 저자 줄이 아니다."""
    markdown = (
        "# A Paper\n\n"
        "### Abstract\n\nSummary.\n\n"
        "### 4 Datasets, Metrics, and Baselines\n\nWe evaluate on three datasets.\n"
    )
    sections = {
        chunk.section for chunk in Chunker(settings).chunk(PAPER_ID, markdown).chunks
    }

    assert "4 Datasets, Metrics, and Baselines" in sections


def test_paper_title_with_commas_is_kept(settings) -> None:
    """첫 제목은 논문 제목이라 쉼표가 많아도 건드리지 않는다."""
    markdown = (
        "# Fast, Cheap, and Out of Control: A Study\n\n"
        "Author affiliation line.\n\n"
        "### Abstract\n\nSummary text.\n"
    )
    sections = {
        chunk.section for chunk in Chunker(settings).chunk(PAPER_ID, markdown).chunks
    }

    assert "Fast, Cheap, and Out of Control: A Study" in sections


def test_author_line_ending_with_a_comma_is_demoted(settings) -> None:
    """윗첨자 소속 번호가 붙어 쉼표로 끝나는 저자 줄(2608.01735)."""
    markdown = (
        "# DAPD: Dual-Anchored Policy Distillation\n\n"
        "## **Jianyu Wu**<sup>1,2</sup> **, Yizhou Wang**<sup>2,3</sup> "
        "**, Shixiang Tang**<sup>2,3,</sup>\n\n"
        "1Shanghai Jiao Tong University 2Shanghai AI Laboratory\n\n"
        "#### Abstract\n\nWe propose DAPD.\n"
    )
    chunks = Chunker(settings).chunk(PAPER_ID, markdown).chunks
    sections = {chunk.section for chunk in chunks}

    assert not any("Jianyu" in section for section in sections)
    assert sections == {"DAPD: Dual-Anchored Policy Distillation", "Abstract"}
    assert any("Jianyu Wu" in chunk.text for chunk in chunks)
