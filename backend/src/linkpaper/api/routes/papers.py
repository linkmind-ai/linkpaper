import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from linkpaper.api.dependencies import (
    get_paper_analysis_pipeline,
    get_paper_service,
)
from linkpaper.modules.papers import Paper, PaperService
from linkpaper.pipelines.paper_analysis import PaperAnalysisPipeline

router = APIRouter()
logger = logging.getLogger(__name__)

PaperAnalysisDependency = Annotated[
    PaperAnalysisPipeline,
    Depends(get_paper_analysis_pipeline),
]
PaperServiceDependency = Annotated[PaperService, Depends(get_paper_service)]


@router.get("/search")
async def search_papers(
    papers: PaperServiceDependency,
    q: str = "",
) -> list[Paper]:
    try:
        return await papers.search(q)
    except (httpx.HTTPError, ValueError) as exc:
        logger.exception("Hugging Face Papers 검색 실패")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="논문 검색 서비스에 연결하지 못했습니다.",
        ) from exc


@router.post("/{paper_id}/analysis", status_code=status.HTTP_202_ACCEPTED)
async def analyze_paper(
    paper_id: str,
    _pipeline: PaperAnalysisDependency,
) -> dict[str, str]:
    # 작업 저장소를 구현한 뒤 논문 분석 파이프라인을 작업 큐에 등록한다.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Paper analysis is not implemented yet: {paper_id}",
    )
