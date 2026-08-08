"""Data Pipeline 조립.

    Hugging Face Papers Client ─ metadata ─┐
                    │                       ↓
                    └ paper ─ Preprocessor ─ markdown ─ Chunker ─ chunks
                                                          │
                                                    references
                                                          ↓
                                                   Metadata Curator
                                                          ↓
                                        ProcessedPaper(metadata, chunks)

논문 한 편이 처리 단위다. 베이스 구축(이번 달 전체)과 Daily Papers 최신화는
조회 범위만 다를 뿐 `process_paper`를 그대로 재사용한다.

스케줄러는 이 모듈에 두지 않는다. 외부 Job이 `run_base_corpus` /
`run_daily_papers`를 호출하는 형태다.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from datetime import date, datetime, timezone
from typing import Literal

from data_pipeline.chunker import Chunker
from data_pipeline.config import IndexingSettings, settings as default_settings
from data_pipeline.exceptions import PaperFetchError, PreprocessingError
from data_pipeline.hf_client import HuggingFacePapersClient
from data_pipeline.metadata_curator import MetadataCurator
from data_pipeline.models import (
    PaperMetadata,
    PaperOutcome,
    PipelineRun,
    ProcessedPaper,
)
from data_pipeline.preprocessor import Preprocessor

logger = logging.getLogger(__name__)

RunMode = Literal["base", "daily"]

_STAGE_BY_ERROR: tuple[tuple[type[Exception], str], ...] = (
    (PaperFetchError, "fetch"),
    (PreprocessingError, "preprocess"),
)


class DataPipeline:
    """논문 수집·전처리 파이프라인.

    각 컴포넌트를 주입할 수 있어 외부 호출 없이 전체 흐름을 테스트할 수 있다.
    """

    def __init__(
        self,
        settings: IndexingSettings | None = None,
        client: HuggingFacePapersClient | None = None,
        preprocessor: Preprocessor | None = None,
        chunker: Chunker | None = None,
        curator: MetadataCurator | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self.client = client or HuggingFacePapersClient(self.settings)
        self.preprocessor = preprocessor or Preprocessor(self.settings)
        self.chunker = chunker or Chunker(self.settings)
        self.curator = curator or MetadataCurator()

    # ------------------------------------------------------------------
    # 논문 한 편
    # ------------------------------------------------------------------
    def process_paper(self, metadata: PaperMetadata) -> ProcessedPaper:
        """논문 한 편을 처리해 최종 메타데이터와 청크를 돌려준다.

        실패하면 예외를 던진다. 배치에서 실패를 격리하려면 `process`를 쓴다.
        """
        markdown = self.preprocessor.to_markdown(metadata)
        chunked = self.chunker.chunk(metadata.paper_id, markdown.text)
        curated = self.curator.curate(metadata, chunked.references_text, markdown)

        logger.info(
            "논문 처리 완료 paper_id=%s source=%s chunks=%d references=%d",
            curated.paper_id,
            markdown.source,
            len(chunked.chunks),
            len(curated.references),
        )
        return ProcessedPaper(metadata=curated, chunks=chunked.chunks)

    def process_paper_id(self, paper_id: str) -> ProcessedPaper:
        """메타데이터 조회부터 시작하는 단건 처리."""
        return self.process_paper(self.client.get_paper(paper_id))

    # ------------------------------------------------------------------
    # 배치
    # ------------------------------------------------------------------
    def process(self, papers: Iterable[PaperMetadata]) -> Iterator[PaperOutcome]:
        """여러 편을 처리하며 실패를 논문 단위로 격리한다.

        결과를 하나씩 내보내므로 호출하는 Job이 전체를 메모리에 쌓지 않고
        바로 Graph Builder에 넘길 수 있다.
        """
        for metadata in papers:
            yield self._process_safely(metadata)

    def run_base_corpus(
        self,
        year: int | None = None,
        month: int | None = None,
        limit: int | None = None,
    ) -> PipelineRun:
        """베이스 지식그래프용 배치. 기본값은 이번 달 전체다."""
        today = date.today()
        year = year or today.year
        month = month or today.month
        papers = self.client.list_papers_in_month(year, month)
        return self._run("base", f"{year:04d}-{month:02d}", papers, limit)

    def run_daily_papers(
        self, day: date | None = None, limit: int | None = None
    ) -> PipelineRun:
        """Daily Papers 최신화 배치. 기본값은 오늘이다."""
        day = day or date.today()
        papers = self.client.list_daily_papers(day)
        return self._run("daily", day.isoformat(), papers, limit)

    def close(self) -> None:
        self.client.close()
        self.preprocessor.close()

    def __enter__(self) -> DataPipeline:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------
    def _run(
        self,
        mode: RunMode,
        window: str,
        papers: list[PaperMetadata],
        limit: int | None,
    ) -> PipelineRun:
        if limit is not None:
            papers = papers[:limit]

        started_at = datetime.now(timezone.utc)
        logger.info("배치 시작 mode=%s window=%s papers=%d", mode, window, len(papers))

        outcomes = list(self.process(papers))

        finished_at = datetime.now(timezone.utc)
        failures = [outcome for outcome in outcomes if not outcome.ok]
        logger.info(
            "배치 종료 mode=%s window=%s 성공=%d 실패=%d 소요=%.1fs",
            mode,
            window,
            len(outcomes) - len(failures),
            len(failures),
            (finished_at - started_at).total_seconds(),
        )
        for failure in failures:
            logger.warning(
                "실패 논문 paper_id=%s stage=%s error=%s",
                failure.paper_id,
                failure.stage,
                failure.error,
            )

        return PipelineRun(
            mode=mode,
            window=window,
            started_at=started_at,
            finished_at=finished_at,
            outcomes=outcomes,
        )

    def _process_safely(self, metadata: PaperMetadata) -> PaperOutcome:
        try:
            paper = self.process_paper(metadata)
        except Exception as exc:
            stage = next(
                (name for error, name in _STAGE_BY_ERROR if isinstance(exc, error)),
                "process",
            )
            logger.warning(
                "논문 처리 실패 paper_id=%s stage=%s error=%s: %s",
                metadata.paper_id,
                stage,
                type(exc).__name__,
                exc,
                exc_info=stage == "process",
            )
            return PaperOutcome(
                paper_id=metadata.paper_id,
                stage=stage,
                error=f"{type(exc).__name__}: {exc}",
            )
        return PaperOutcome(paper_id=metadata.paper_id, paper=paper)
