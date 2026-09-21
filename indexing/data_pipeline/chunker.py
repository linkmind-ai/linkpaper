"""논문 Markdown을 섹션 단위로 나눈 뒤 청킹한다.

Markdown의 제목 표기는 한 가지가 아니다. Hugging Face의 `.md` 응답은 상위
섹션을 setext 형식으로 쓴다.

    References
    ----------

반면 하위 섹션은 ATX 형식(`### 3.1 Attention`)이고, pymupdf4llm 변환 결과는
전부 ATX다. `^#`만 찾으면 HF 경로에서는 상위 섹션과 참고문헌을 통째로 놓치므로
두 형식을 모두 인식한다.

섹션 분할 자체는 `MarkdownHeaderTextSplitter`에 맡기되, 그 앞에
`_normalize_setext_headings`를 반드시 둔다. 이 splitter는 ATX만 인식해서
정규화를 건너뛰면 HF 경로의 상위 섹션과 참고문헌을 통째로 놓친다. 대신 상위
제목 경로를 metadata로 돌려주므로 `2.1 Setup`이 `2 Method`의 하위라는 정보를
얻는다.

청킹은 섹션 경계를 넘지 않는다. 한 청크가 두 섹션에 걸치면 그 청크의 `section`
값이 거짓이 되고, 근거 표시도 틀리게 된다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from data_pipeline.config import IndexingSettings, settings as default_settings
from data_pipeline.models import ChunkedPaper, PaperChunk, content_hash

logger = logging.getLogger(__name__)

# 첫 제목 앞의 본문(저자, 소속 등)에 붙일 이름.
FRONT_MATTER = "Front Matter"

_ATX_HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*$")
_SETEXT_UNDERLINE_RE = re.compile(r"^\s*(=+|-+)\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
# setext 밑줄로 오인하기 쉬운 목록·인용·표 줄을 제외한다.
_NON_TITLE_PREFIX = ("*", "-", "+", ">", "|", "#")

# 제목 앞 번호. '7 References', 'A.1 References', 'IV. Introduction' 등.
_LEADING_NUMBER_RE = re.compile(
    r"^(?:\d+|[IVXLC]+|[A-Z])(?:\.[0-9A-Z]+)*[.):]?\s+", re.IGNORECASE
)

# 'preference'가 'reference'로 잡히지 않도록 단어 경계를 쓴다.
_REFERENCE_HEADING_RE = re.compile(
    r"\b(references?|bibliography|works\s+cited|literature\s+cited)\b|참고문헌",
    re.IGNORECASE,
)

# 제목 깊이를 이름에 담아, metadata를 h1..h6 순서로 정렬할 수 있게 한다.
_HEADER_SPLITTER = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#" * depth, f"h{depth}") for depth in range(1, 7)]
)

# pymupdf4llm은 그림 안의 글자를 OCR해서 주석 블록으로 넣는다. 범례와 축
# 이름이 `Ref Video<br>Pairs<br>...` 처럼 이어 붙어 나오는데, 검색에는 도움이
# 되지 않으면서 청크를 채운다. 블록을 통째로 지운다.
_PICTURE_TEXT_RE = re.compile(
    r"<!--\s*Start of picture text\s*-->.*?<!--\s*End of picture text\s*-->",
    re.DOTALL | re.IGNORECASE,
)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_LINE_BREAK_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

# pymupdf4llm은 제목을 `## **1 Introduction**` 처럼 굵게 감싸서 낸다. 강조 표시를
# 지워야 근거 표시에 그대로 노출되지 않는다.
_EMPHASIS_RE = re.compile(r"[*`]")

# 제목에 `<u>v1</u>` 같은 태그가 섞여 나오는 논문이 있다.
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")

# 이탤릭 마커로 쓰인 `_`만 지운다. 단어 사이의 `_`(task_name)는 식별자의
# 일부라 남긴다. 단어 경계에 붙은 것만 마커로 본다.
_UNDERSCORE_MARKER_RE = re.compile(r"(?<![0-9A-Za-z])_+|_+(?![0-9A-Za-z])")

# 제목 표기가 아예 없는 논문도 있다. 두 가지 형태를 보완적으로 인식한다.
#   1) 단 나누기가 있는 PDF: `... **References** [1] Jimmy Lei Ba. ...`
#   2) 제목이 하나도 없는 평문: 'References'만 있는 줄
# (패턴, 위치 제한 필요 여부). 두 패턴은 정밀도가 다르므로 제한도 다르게 건다.
_FALLBACK_REFERENCES_RES = (
    # 번호 인용이 바로 뒤따르는 형태. 그 자체로 충분히 좁아서 위치 제한이 필요 없다.
    (
        re.compile(
            r"(?:^|\s)\*{0,2}(?:References?|Bibliography)\*{0,2}[ \t]*(?=\[\s*\d+\s*\])",
            re.IGNORECASE,
        ),
        False,
    ),
    # 줄 하나가 통째로 'References'인 형태. 목차 항목과 구분되지 않으므로 위치로 거른다.
    (
        re.compile(
            r"^[ \t]*\*{0,2}(?:References?|Bibliography)\*{0,2}[ \t]*$",
            re.IGNORECASE | re.MULTILINE,
        ),
        True,
    ),
)
# 부록 제목. 'Appendix', 'Appendix A', 'Supplementary Material', '부록'.
_APPENDIX_HEADING_RE = re.compile(
    r"^(?:appendix|appendices|supplement(?:ary|al)?(?:\s+material)?)\b|^부록",
    re.IGNORECASE,
)

# 참고문헌 뒤에 나오는 'A', 'A.1', 'B. Setup', 'D.5.1' 형태의 부록 라벨.
# 본문에도 'A. Overview' 같은 하위 섹션이 있으므로 위치와 함께 판단한다.
_APPENDIX_LABEL_RE = re.compile(r"^[A-Z](?:\.\d+)*\.?(?:\s|$)")

# 앞쪽 목차의 'References' 줄을 실제 목록으로 오인하면 본문 대부분이 참고문헌으로
# 분류되고, 본문에 나온 arXiv ID가 인용 관계로 둔갑한다.
_MIN_REFERENCES_POSITION = 0.4


# pymupdf4llm은 글꼴 크기로 제목을 판단해서, 굵게 강조된 문장이 줄바꿈으로
# 잘리면 뒷조각만 제목이 되는 일이 있다. 실제 사례(2607.29241):
#
#     ...adapt to different recommendation scenarios, model**
#     #### **families, and evaluation objectives.**
#
# 논문 섹션 제목은 소문자로 시작하지도, 마침표로 끝나지도 않는다. 둘을 모두
# 만족하는 제목만 강등하므로 `Ablation studies`나 `A.1 Design axes`는 걸리지
# 않는다. 번호 뒤의 마침표(`3.1.`)는 마지막 글자가 숫자라 대상이 아니다.
_SENTENCE_FRAGMENT_RE = re.compile(r"^[a-z].*[a-z)\]]\.$", re.DOTALL)


def _demote_sentence_fragment_headings(lines: list[str]) -> list[str]:
    """제목처럼 보이지 않는 줄을 일반 문단으로 되돌린다."""
    demoted: list[str] = []
    for line in lines:
        match = _ATX_HEADING_RE.match(line)
        if match and _SENTENCE_FRAGMENT_RE.match(_clean_heading(match.group(1))):
            logger.debug("문장 조각을 제목에서 강등: %s", line.strip()[:60])
            demoted.append(match.group(1))
            continue
        demoted.append(line)
    return demoted


# 초록이나 번호 붙은 섹션이 나오면 표지 구간이 끝난 것으로 본다. 로마숫자는
# 대문자만 인정한다. 소문자까지 받으면 'civil'처럼 I·V·X·L·C로만 된 단어가
# 섹션 번호로 오인된다.
_FRONT_MATTER_END_RE = re.compile(
    r"^(?i:abstract|contents|keywords|index\s+terms)\b|^(?:\d+|[IVXLC]+)[.\s]"
)

# 쉼표가 둘 이상인 제목. 표지의 저자 목록이 이 모양이다. 조각이 비는 것을
# 허용해야 `Shixiang Tang2,3,`처럼 쉼표로 끝나는 저자 줄도 잡힌다.
_AUTHOR_LIST_RE = re.compile(r"^[^,]*(?:,[^,]*){2,}$")


def _demote_author_headings(lines: list[str]) -> list[str]:
    """표지의 저자·소속 줄을 제목에서 내린다.

    pymupdf4llm이 글꼴 크기로 제목을 판단해서, 표지의 크고 굵은 저자 줄이
    제목이 된다(2607.29679의 `#### **Zilong Chen, ... ** ByteDance Seed`).
    그러면 초록 앞 내용이 저자 이름을 제목으로 단 섹션에 들어간다.

    오탐을 줄이려고 세 조건을 모두 건다. 첫 제목은 논문 제목이므로 건드리지
    않고, 초록이나 번호 붙은 섹션이 나오기 전까지만 보며, 쉼표로 나뉜 항목이
    셋 이상인 제목만 내린다.
    """
    demoted: list[str] = []
    seen_title = False
    in_front_matter = True

    for line in lines:
        match = _ATX_HEADING_RE.match(line)
        if not match:
            demoted.append(line)
            continue

        title = _clean_heading(match.group(1))
        if not seen_title:
            # 첫 제목은 논문 제목이다. 쉼표가 많아도 남긴다.
            seen_title = True
            demoted.append(line)
            continue

        if in_front_matter and _FRONT_MATTER_END_RE.match(title):
            in_front_matter = False

        if in_front_matter and _AUTHOR_LIST_RE.match(title):
            logger.debug("표지의 저자 줄을 제목에서 강등: %s", title[:60])
            demoted.append(match.group(1))
            continue

        demoted.append(line)
    return demoted


@dataclass
class Section:
    """Markdown 제목 하나가 여는 구간."""

    title: str
    index: int
    text: str
    is_references: bool
    is_appendix: bool
    # 최상위 제목부터 이 섹션의 제목까지. ("2 Method", "2.1 Setup")
    path: tuple[str, ...]


class Chunker:
    """논문 Markdown → 섹션 인식 청크 목록.

    참고문헌 섹션의 원문도 함께 돌려준다. Metadata Curator가 그 원문에서
    arXiv ID를 뽑아 `references`를 만든다.
    """

    def __init__(self, settings: IndexingSettings | None = None) -> None:
        self.settings = settings or default_settings
        # 섹션 하나가 청크 하나다. 이 splitter는 안전 상한을 넘긴 섹션에만
        # 관여하므로 대부분의 섹션은 통째로 지나간다.
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.settings.max_chunk_chars,
            chunk_overlap=0,
            separators=["\n\n", "\n", ". ", " ", ""],
            keep_separator=True,
        )

    def chunk(self, paper_id: str, markdown: str) -> ChunkedPaper:
        sections = split_sections(markdown)
        if not any(section.is_references for section in sections):
            promoted = promote_inline_references_heading(markdown)
            if promoted is not None:
                logger.debug(
                    "본문 중간의 참고문헌 표시를 제목으로 승격 paper_id=%s", paper_id
                )
                sections = split_sections(promoted)

        chunks: list[PaperChunk] = []
        # 참고문헌은 정리 전 원문을 넘긴다. 링크 정리를 거치면
        # `[제목](https://arxiv.org/abs/...)` 형태의 arXiv ID가 사라진다.
        reference_texts: list[str] = []

        dropped = 0
        for section in sections:
            if section.is_references:
                reference_texts.append(section.text)

            # 참고문헌 원문을 모은 뒤에 버린다. 부록 뒤에 참고문헌이 오는
            # 논문에서도 인용 추출이 영향을 받지 않는다.
            if section.is_appendix and not self.settings.include_appendix:
                dropped += 1
                continue

            body = clean_markdown(section.text)
            if not body:
                continue

            for piece in self.splitter.split_text(body):
                piece = piece.strip()
                if not piece:
                    continue
                digest = content_hash(piece)
                index = len(chunks)
                chunks.append(
                    PaperChunk(
                        # neo4j-schema.md 7.2의 Chunk ID 형식
                        chunk_id=f"{paper_id}:chunk:{index}:{digest[:8]}",
                        paper_id=paper_id,
                        chunk_index=index,
                        text=piece,
                        section=section.title,
                        section_index=section.index,
                        section_path=" > ".join(section.path) or FRONT_MATTER,
                        is_references=section.is_references,
                        char_count=len(piece),
                        content_hash=digest,
                    )
                )

        if not reference_texts:
            logger.info("참고문헌 섹션을 찾지 못했습니다 paper_id=%s", paper_id)
        logger.debug(
            "청킹 완료 paper_id=%s sections=%d chunks=%d appendix_sections_dropped=%d",
            paper_id,
            len(sections),
            len(chunks),
            dropped,
        )
        return ChunkedPaper(
            chunks=chunks, references_text="\n\n".join(reference_texts).strip()
        )


def split_sections(markdown: str) -> list[Section]:
    """제목을 기준으로 본문을 섹션으로 나눈다.

    setext 제목을 ATX로 통일한 뒤 `MarkdownHeaderTextSplitter`에 넘긴다. 그
    결과에는 상위 제목 경로가 metadata로 붙어 오므로, 하위 섹션이 어느 상위
    섹션에 속하는지 알 수 있다.
    """
    # picture text 블록을 가장 먼저 걷어낸다. 블록 안에 `# Configuration F1 ...`
    # 처럼 표를 OCR한 줄이 제목 형태로 들어 있는 경우가 있어서, 분할 뒤에
    # 지우면 그 줄이 이미 섹션 제목이 된 뒤다(2607.27201).
    markdown = _PICTURE_TEXT_RE.sub("", markdown)
    normalized = "\n".join(
        _demote_author_headings(
            _demote_sentence_fragment_headings(_normalize_setext_headings(markdown))
        )
    )

    sections: list[Section] = []
    seen_references = False
    # 부록은 한 번 시작하면 논문 끝까지 이어진다. 본문으로 되돌아가지 않으므로
    # 걸쇠로 다룬다. 부록 하위 섹션마다 라벨을 다시 판정하지 않아도 된다.
    in_appendix = False

    for document in _HEADER_SPLITTER.split_text(normalized):
        text = document.page_content.strip()
        # 본문 없이 하위 섹션만 여는 제목은 어떤 청크도 만들지 않는다. 남겨두면
        # 아무 청크도 가리키지 않는 빈 섹션이 `section_index`만 밀어낸다.
        if not text:
            continue

        path = _heading_path(document.metadata)
        # 상위 제목이 참고문헌이면 그 하위 섹션도 참고문헌이다.
        is_references = any(is_references_heading(name) for name in path)
        if is_references:
            seen_references = True
        elif not in_appendix and is_appendix_heading(
            path, after_references=seen_references
        ):
            in_appendix = True

        sections.append(
            Section(
                title=path[-1] if path else FRONT_MATTER,
                index=len(sections),
                text=text,
                is_references=is_references,
                # 부록 뒤에 참고문헌이 오는 논문이 있다. 인용 추출에 필요하므로
                # 참고문헌은 부록으로 묶지 않는다.
                is_appendix=in_appendix and not is_references,
                path=path,
            )
        )
    return sections


def is_appendix_heading(path: tuple[str, ...], *, after_references: bool) -> bool:
    """부록이 시작되는 제목인지 판정한다.

    `Appendix`처럼 명시적으로 표기하는 논문이 많지만, 참고문헌 뒤에서 곧바로
    `A. Network and Memory Architecture`로 넘어가는 논문도 있다. 후자의 라벨은
    본문 하위 섹션(`A. Overview`)과 모양이 같아서 제목만으로는 구분되지 않는다.
    그래서 참고문헌을 지났는지를 함께 본다.
    """
    if any(_APPENDIX_HEADING_RE.match(name) for name in path):
        return True
    return bool(after_references and path and _APPENDIX_LABEL_RE.match(path[-1]))


def _heading_path(metadata: dict[str, str]) -> tuple[str, ...]:
    """splitter의 metadata를 제목 깊이 순 경로로 편다.

    metadata는 `{"h2": "2 Method", "h3": "2.1 Setup"}` 형태의 dict라 순서를
    믿을 수 없으므로 키에 담긴 깊이로 정렬한다.
    """
    ordered = sorted(metadata.items(), key=lambda item: int(item[0][1:]))
    return tuple(cleaned for _, raw in ordered if (cleaned := _clean_heading(raw)))


def promote_inline_references_heading(markdown: str) -> str | None:
    """제목으로 표기되지 않은 참고문헌 표시를 제목으로 바꾼다.

    이 보정이 없으면 `references`가 아무 오류 없이 빈 목록이 된다. 실제
    Hugging Face Markdown과 pymupdf4llm 출력 양쪽에서 관찰된 형태를 다룬다.

    문서 후반부의 마지막 표시만 승격시킨다. 앞쪽에서 언급된 'References'는
    목차이거나 본문 중의 단순 언급일 가능성이 높다.

    승격할 곳이 없으면 `None`을 돌려준다.
    """
    if not markdown:
        return None

    threshold = len(markdown) * _MIN_REFERENCES_POSITION
    candidates = [
        match
        for pattern, needs_position_guard in _FALLBACK_REFERENCES_RES
        for match in pattern.finditer(markdown)
        if not needs_position_guard or match.start() >= threshold
    ]
    if not candidates:
        return None

    match = max(candidates, key=lambda found: found.start())
    return f"{markdown[: match.start()]}\n\n## References\n\n{markdown[match.end() :]}"


def _clean_heading(title: str) -> str:
    """제목에 섞여 온 마크업을 걷어낸다.

    `_B. SULAND_ _<u>v1</u> Dataset Organization_` 같은 제목이 실제로 나온다.
    이 값이 근거 표시에 그대로 보이므로 태그와 강조 표시를 모두 지운다.
    """
    cleaned = _HTML_TAG_RE.sub("", title)
    cleaned = _EMPHASIS_RE.sub("", cleaned)
    cleaned = _UNDERSCORE_MARKER_RE.sub("", cleaned)
    return " ".join(cleaned.split())


def is_references_heading(title: str) -> bool:
    """`References`, `7 References`, `Bibliography`, `참고문헌` 등을 식별한다."""
    stripped = _LEADING_NUMBER_RE.sub("", title.strip(), count=1)
    if not stripped:
        return False
    # 번호를 뗀 제목의 맨 앞에서만 찾는다. 'Comparison with reference
    # implementations'처럼 낱말이 문장 중간에 나오는 것은 참고문헌 제목이
    # 아니다. 낱말 수로 거르면 이 예시(4단어)가 그대로 통과한다.
    return bool(_REFERENCE_HEADING_RE.match(stripped))


def clean_markdown(text: str) -> str:
    """청킹 전 본문 정리.

    이미지를 지우고 링크는 표시 문자열만 남긴다. 논문 Markdown은 인용 표시마다
    긴 앵커 URL이 붙어 있어서, 그대로 두면 청크의 상당 부분이 URL로 채워진다.
    """
    # picture text 블록은 섹션 분할 전에 이미 제거됐다. 남은 주석은 변환기가
    # 남긴 표시라 본문이 아니다.
    text = _HTML_COMMENT_RE.sub("", text)
    text = _LINE_BREAK_TAG_RE.sub(" ", text)
    text = _IMAGE_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def _normalize_setext_headings(markdown: str) -> list[str]:
    """setext 제목을 ATX로 바꿔 이후 처리를 한 형식으로 통일한다.

    References          ->  ## References
    ----------
    """
    lines = markdown.splitlines()
    normalized: list[str] = []
    in_fence = False
    index = 0

    while index < len(lines):
        line = lines[index]
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            normalized.append(line)
            index += 1
            continue

        underline = lines[index + 1] if index + 1 < len(lines) else None
        if (
            not in_fence
            and underline is not None
            and line.strip()
            and not line.strip().startswith(_NON_TITLE_PREFIX)
            and _SETEXT_UNDERLINE_RE.match(underline)
        ):
            level = 1 if underline.strip().startswith("=") else 2
            normalized.append(f"{'#' * level} {line.strip()}")
            index += 2
            continue

        normalized.append(line)
        index += 1

    return normalized
