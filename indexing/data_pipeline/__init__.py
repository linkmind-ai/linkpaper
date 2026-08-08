"""LinkPaper Data Pipeline.

Hugging Face Papers에서 논문을 가져와 전처리하고, Graph Builder가 쓸
최종 메타데이터와 청크를 만든다.

    from data_pipeline import DataPipeline

    with DataPipeline() as pipeline:
        result = pipeline.process_paper_id("2406.04093")
        print(result.metadata.references, len(result.chunks))
"""

from data_pipeline.chunker import Chunker
from data_pipeline.exceptions import (
    DataPipelineError,
    PaperFetchError,
    PreprocessingError,
)
from data_pipeline.hf_client import HuggingFacePapersClient
from data_pipeline.metadata_curator import MetadataCurator
from data_pipeline.models import (
    ChunkedPaper,
    PaperChunk,
    PaperMarkdown,
    PaperMetadata,
    PaperOutcome,
    PipelineRun,
    ProcessedPaper,
)
from data_pipeline.pipeline import DataPipeline
from data_pipeline.preprocessor import Preprocessor

__all__ = [
    "ChunkedPaper",
    "Chunker",
    "DataPipeline",
    "DataPipelineError",
    "HuggingFacePapersClient",
    "MetadataCurator",
    "PaperChunk",
    "PaperFetchError",
    "PaperMarkdown",
    "PaperMetadata",
    "PaperOutcome",
    "PipelineRun",
    "Preprocessor",
    "PreprocessingError",
    "ProcessedPaper",
]
