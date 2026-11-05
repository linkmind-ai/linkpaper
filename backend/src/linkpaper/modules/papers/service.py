"""Hugging Face Papers 응답을 프론트엔드 논문 모델로 변환한다."""

from __future__ import annotations

import re
from typing import Any, Protocol

from linkpaper.modules.papers.models import Paper

_ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}$")
_MAX_DISPLAY_AUTHORS = 3
_MAX_CATEGORIES = 3


class PaperSource(Protocol):
    async def search(self, query: str, limit: int) -> list[dict[str, Any]]: ...

    async def list_daily(self, limit: int) -> list[dict[str, Any]]: ...


class PaperService:
    """논문 검색과 메타데이터 조회를 담당한다."""

    def __init__(self, source: PaperSource, *, default_limit: int = 20) -> None:
        self.source = source
        self.default_limit = default_limit

    async def search(self, query: str) -> list[Paper]:
        """검색어가 비어 있으면 최신 Daily Papers를 기본 목록으로 반환한다."""
        normalized = query.strip()
        if normalized:
            items = await self.source.search(normalized, self.default_limit)
        else:
            items = await self.source.list_daily(self.default_limit)

        papers = (self._to_paper(item) for item in items)
        return [paper for paper in papers if paper is not None]

    @classmethod
    def _to_paper(cls, item: dict[str, Any]) -> Paper | None:
        # 검색과 Daily Papers 모두 실제 논문을 paper 필드로 한 번 감싼다.
        paper = item.get("paper") if isinstance(item.get("paper"), dict) else item
        paper_id = str(paper.get("id") or "").strip()
        if not paper_id:
            return None

        is_arxiv = _ARXIV_ID_RE.fullmatch(paper_id) is not None
        published_at = str(paper.get("publishedAt") or item.get("publishedAt") or "")
        return Paper(
            id=paper_id,
            title=str(paper.get("title") or item.get("title") or "").strip(),
            authors=cls._format_authors(paper.get("authors")),
            year=int(published_at[:4]) if published_at[:4].isdigit() else None,
            categories=[
                str(keyword) for keyword in paper.get("ai_keywords") or []
            ][:_MAX_CATEGORIES],
            summary=str(paper.get("summary") or item.get("summary") or "").strip(),
            pdfUrl=f"https://arxiv.org/pdf/{paper_id}" if is_arxiv else None,
            arxivUrl=f"https://arxiv.org/abs/{paper_id}" if is_arxiv else None,
        )

    @staticmethod
    def _format_authors(authors: Any) -> str:
        names = [
            str(author["name"]).strip()
            for author in authors or []
            if isinstance(author, dict) and author.get("name")
        ]
        if len(names) > _MAX_DISPLAY_AUTHORS:
            return f"{', '.join(names[:_MAX_DISPLAY_AUTHORS])} et al."
        return ", ".join(names)
