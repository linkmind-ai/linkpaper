from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from linkpaper.api.dependencies import get_paper_analysis_pipeline
from linkpaper.pipelines.paper_analysis import PaperAnalysisPipeline

router = APIRouter()

PaperAnalysisDependency = Annotated[
    PaperAnalysisPipeline,
    Depends(get_paper_analysis_pipeline),
]


@router.get("")
async def search_papers(query: str) -> list[dict[str, str]]:
    # 추후 파이프라인을 통해 Hugging Face Papers 어댑터와 연결한다.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Paper search is not implemented yet: {query}",
    )


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
