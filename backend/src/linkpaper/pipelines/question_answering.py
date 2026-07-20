"""GraphRAG 질의응답 파이프라인의 조율 경계.

예상 흐름: 로컬 검색 -> 필요시 그래프 확장 -> 재정렬 -> 답변 생성.
각 파이프라인 단계를 구현하면서 실제 협력 객체를 추가한다.
"""

from linkpaper.modules.conversations import ConversationService
from linkpaper.modules.generation import GenerationService
from linkpaper.modules.knowledge_graph import KnowledgeGraphService
from linkpaper.modules.retrieval import RetrievalService


class QuestionAnsweringPipeline:
    def __init__(
        self,
        conversations: ConversationService,
        retrieval: RetrievalService,
        knowledge_graph: KnowledgeGraphService,
        generation: GenerationService,
    ) -> None:
        self.conversations = conversations
        self.retrieval = retrieval
        self.knowledge_graph = knowledge_graph
        self.generation = generation
