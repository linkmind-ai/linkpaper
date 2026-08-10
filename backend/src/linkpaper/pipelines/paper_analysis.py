"""사용자용 논문 분석 파이프라인의 온라인 조율 경계.

예상 흐름: 논문 선택 -> 인덱스 준비 상태 확인 -> 저장소 조회 -> 요약.
주기적인 파싱·청킹·그래프 추출·임베딩·적재는 ``indexing/`` 오프라인
엔진에서 수행하며 이 파이프라인에서는 실행하지 않는다.
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
