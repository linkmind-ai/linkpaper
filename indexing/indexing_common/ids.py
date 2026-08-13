"""Neo4j와 Qdrant가 공유하는 결정적 식별자를 만든다."""

from __future__ import annotations

import re

from data_pipeline.models import PaperChunk, ProcessedPaper

_CANONICAL_PREFIXES = ("arxiv:", "hf:", "ref:")
_ARXIV_ID_RE = re.compile(
    r"^(?:\d{4}\.\d{4,5}|[a-z][a-z.-]+(?:/[a-z.-]+)?/\d{7})$",
    re.IGNORECASE,
)


def paper_id_for(raw_id: str, arxiv_id: str | None = None) -> str:
    """원천 ID를 저장소 공통 Paper ID로 바꾼다."""
    value = raw_id.strip()
    if value.startswith(_CANONICAL_PREFIXES):
        return value

    candidate = (arxiv_id or value).strip()
    if _ARXIV_ID_RE.fullmatch(candidate):
        return f"arxiv:{candidate}"
    return f"hf:{value}"


def chunk_id_for(chunk: PaperChunk, canonical_paper_id: str) -> str:
    """본문과 청킹 결과가 같으면 항상 같은 Chunk ID를 만든다."""
    # 원천 chunk_id의 접두사만 치환하지 않고 계약에 따라 다시 조립한다.
    # 이렇게 해야 두 builder가 입력 표기와 무관하게 완전히 같은 키를 사용한다.
    return f"{canonical_paper_id}:chunk:{chunk.chunk_index}:{chunk.content_hash[:8]}"


def canonicalize_paper(paper: ProcessedPaper) -> ProcessedPaper:
    """전처리 결과를 저장소 공통 ID 체계로 복사한다."""
    metadata = paper.metadata
    canonical_paper_id = paper_id_for(metadata.paper_id, metadata.arxiv_id)

    normalized_metadata = metadata.model_copy(
        update={
            "paper_id": canonical_paper_id,
            # CITES 목적지도 Paper와 같은 canonical ID 정책을 사용한다.
            "references": [
                paper_id_for(reference, reference) for reference in metadata.references
            ],
        }
    )
    normalized_chunks = [
        chunk.model_copy(
            update={
                "paper_id": canonical_paper_id,
                "chunk_id": chunk_id_for(chunk, canonical_paper_id),
            }
        )
        for chunk in paper.chunks
    ]
    return ProcessedPaper(metadata=normalized_metadata, chunks=normalized_chunks)
