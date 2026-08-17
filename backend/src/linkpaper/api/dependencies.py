from functools import lru_cache

from linkpaper.adapters.llm import OpenAIClient
from linkpaper.adapters.papers import HuggingFaceMarkdownClient
from linkpaper.core.config import get_settings
from linkpaper.modules.documents import DocumentService
from linkpaper.modules.generation import GenerationService
from linkpaper.modules.knowledge_graph import KnowledgeGraphService
from linkpaper.modules.online_retrieval import (
    InMemoryRetrievalBackend,
    OnlineRetrievalService,
)
from linkpaper.modules.papers import PaperService
from linkpaper.pipelines.paper_analysis import PaperAnalysisPipeline
from linkpaper.pipelines.question_answering import QuestionAnsweringPipeline


@lru_cache
def get_generation_service() -> GenerationService:
    return GenerationService(client=OpenAIClient())


@lru_cache
def get_online_retrieval_service() -> OnlineRetrievalService:
    settings = get_settings()
    embedder = OpenAIClient(settings=settings)
    backend = InMemoryRetrievalBackend(
        embedder=embedder,
        chunk_size=settings.online_chunk_size,
        chunk_overlap=settings.online_chunk_overlap,
    )
    return OnlineRetrievalService(
        backend=backend,
        source=HuggingFaceMarkdownClient(settings=settings),
        default_limit=settings.online_retrieval_limit,
    )


@lru_cache
def get_paper_analysis_pipeline() -> PaperAnalysisPipeline:
    return PaperAnalysisPipeline(
        papers=PaperService(),
        documents=DocumentService(),
        knowledge_graph=KnowledgeGraphService(),
        generation=get_generation_service(),
    )


@lru_cache
def get_question_answering_pipeline() -> QuestionAnsweringPipeline:
    return QuestionAnsweringPipeline(
        retrieval=get_online_retrieval_service(),
        generation=get_generation_service(),
    )
