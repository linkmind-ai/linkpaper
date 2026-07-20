"""논문 분석 파이프라인의 조율 경계.

예상 흐름: 다운로드 -> 파싱 -> 청킹 -> 그래프 추출 -> 요약 -> 인덱싱.
각 파이프라인 단계를 구현하면서 실제 협력 객체를 추가한다.
"""

from linkpaper.modules.documents import DocumentService
from linkpaper.modules.generation import GenerationService
from linkpaper.modules.knowledge_graph import KnowledgeGraphService
from linkpaper.modules.papers import PaperService


class PaperAnalysisPipeline:
    def __init__(
        self,
        papers: PaperService,
        documents: DocumentService,
        knowledge_graph: KnowledgeGraphService,
        generation: GenerationService,
    ) -> None:
        self.papers = papers
        self.documents = documents
        self.knowledge_graph = knowledge_graph
        self.generation = generation
