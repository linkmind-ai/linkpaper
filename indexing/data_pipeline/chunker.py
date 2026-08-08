"""논문 Markdown을 섹션 단위로 나눈 뒤 청킹한다.

Markdown의 제목 표기는 한 가지가 아니다. Hugging Face의 `.md` 응답은 상위
섹션을 setext 형식으로 쓴다.

    References
    ----------

반면 하위 섹션은 ATX 형식(`### 3.1 Attention`)이고, pymupdf4llm 변환 결과는
전부 ATX다. `^#`만 찾으면 HF 경로에서는 상위 섹션과 참고문헌을 통째로 놓치므로
두 형식을 모두 인식한다.

청킹은 섹션 경계를 넘지 않는다. 한 청크가 두 섹션에 걸치면 그 청크의 `section`
값이 거짓이 되고, 근거 표시도 틀리게 된다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from data_pipeline.config import IndexingSettings, settings as default_settings
from data_pipeline.models import ChunkedPaper, PaperChunk, content_hash

logger = logging.getLogger(__name__)

# 첫 제목 앞의 본문(저자, 소속 등)에 붙일 이름.
FRONT_MATTER = "Front Matter"

_ATX_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_SETEXT_UNDERLINE_RE = re.compile(r"^\s*(=+|-+)\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
# setext 밑줄로 오인하기 쉬운 목록·인용·표 줄을 제외한다.
_NON_TITLE_PREFIX = ("*", "-", "+", ">", "|", "#")

# 'preference'가 'reference'로 잡히지 않도록 단어 경계를 쓴다.
_REFERENCE_HEADING_RE = re.compile(
    r"\b(references?|bibliography|works\s+cited|literature\s+cited)\b|참고문헌",
    re.IGNORECASE,
)

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

# pymupdf4llm은 제목을 `## **1 Introduction**` 처럼 굵게 감싸서 낸다. 같은 논문을
# HF Markdown으로 받았을 때와 섹션 이름이 달라지지 않도록 강조 표시를 지운다.
_EMPHASIS_RE = re.compile(r"[*`]")

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
# 앞쪽 목차의 'References' 줄을 실제 목록으로 오인하면 본문 대부분이 참고문헌으로
# 분류되고, 본문에 나온 arXiv ID가 인용 관계로 둔갑한다.
_MIN_REFERENCES_POSITION = 0.4


@dataclass
class Section:
    """Markdown 제목 하나가 여는 구간."""

    title: str
    level: int
    index: int
    text: str
    is_references: bool


class Chunker:
    """논문 Markdown → 섹션 인식 청크 목록.

    참고문헌 섹션의 원문도 함께 돌려준다. Metadata Curator가 그 원문에서
    arXiv ID를 뽑아 `references`를 만든다.
    """

    def __init__(self, settings: IndexingSettings | None = None) -> None:
        self.settings = settings or default_settings
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
            keep_separator=True,
        )

    def chunk(self, paper_id: str, markdown: str) -> ChunkedPaper:
        sections = split_sections(markdown)
        if not any(section.is_references for section in sections):
            promoted = promote_inline_references_heading(markdown)
            if promoted is not None:
                logger.debug("본문 중간의 참고문헌 표시를 제목으로 승격 paper_id=%s", paper_id)
                sections = split_sections(promoted)

        chunks: list[PaperChunk] = []
        # 참고문헌은 정리 전 원문을 넘긴다. 링크 정리를 거치면
        # `[제목](https://arxiv.org/abs/...)` 형태의 arXiv ID가 사라진다.
        reference_texts: list[str] = []

        for section in sections:
            if section.is_references:
                reference_texts.append(section.text)

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
                        is_references=section.is_references,
                        char_count=len(piece),
                        content_hash=digest,
                    )
                )

        if not reference_texts:
            logger.info("참고문헌 섹션을 찾지 못했습니다 paper_id=%s", paper_id)
        logger.debug(
            "청킹 완료 paper_id=%s sections=%d chunks=%d",
            paper_id,
            len(sections),
            len(chunks),
        )
        return ChunkedPaper(
            chunks=chunks, references_text="\n\n".join(reference_texts).strip()
        )


def split_sections(markdown: str) -> list[Section]:
    """제목을 기준으로 본문을 섹션으로 나눈다."""
    sections: list[Section] = []
    title = FRONT_MATTER
    level = 0
    buffer: list[str] = []
    in_fence = False

    def flush() -> None:
        text = "\n".join(buffer).strip()
        if text:
            sections.append(
                Section(
                    title=title,
                    level=level,
                    index=len(sections),
                    text=text,
                    is_references=is_references_heading(title),
                )
            )

    for line in _normalize_setext_headings(markdown):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            buffer.append(line)
            continue

        heading = None if in_fence else _ATX_RE.match(line)
        if heading is None:
            buffer.append(line)
            continue

        flush()
        title = _clean_heading(heading.group(2)) or FRONT_MATTER
        level = len(heading.group(1))
        buffer = []

    flush()
    return sections


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
    return " ".join(_EMPHASIS_RE.sub("", title).split())


def is_references_heading(title: str) -> bool:
    """`References`, `7 References`, `Bibliography`, `참고문헌` 등을 식별한다."""
    stripped = title.strip()
    if not stripped:
        return False
    # 'Comparison with reference implementations' 같은 본문 제목은 제외한다.
    if len(stripped.split()) > 4:
        return False
    return bool(_REFERENCE_HEADING_RE.search(stripped))


def clean_markdown(text: str) -> str:
    """청킹 전 본문 정리.

    이미지를 지우고 링크는 표시 문자열만 남긴다. 논문 Markdown은 인용 표시마다
    긴 앵커 URL이 붙어 있어서, 그대로 두면 청크의 상당 부분이 URL로 채워진다.
    """
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
