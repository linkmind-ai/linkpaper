from functools import lru_cache

from linkpaper.adapters.llm import OpenAIClient
from linkpaper.modules.conversations import ConversationService
from linkpaper.modules.documents import DocumentService
from linkpaper.modules.generation import GenerationService
from linkpaper.modules.knowledge_graph import KnowledgeGraphService
from linkpaper.modules.papers import PaperService
from linkpaper.modules.retrieval import RetrievalService
from linkpaper.pipelines.paper_analysis import PaperAnalysisPipeline
from linkpaper.pipelines.question_answering import QuestionAnsweringPipeline


@lru_cache
def get_generation_service() -> GenerationService:
    return GenerationService(client=OpenAIClient())


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
        conversations=ConversationService(),
        retrieval=RetrievalService(),
        knowledge_graph=KnowledgeGraphService(),
        generation=get_generation_service(),
    )
