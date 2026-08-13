"""Neo4j read DTO.

snake_case API 모델을 사용하되 Cypher에서는 저장된 camelCase 속성을 명시적으로
매핑한다.
"""

from pydantic import BaseModel, Field


class PaperNode(BaseModel):
    paper_id: str  # Neo4j와 Qdrant가 공유하는 전역 논문 ID
    arxiv_id: str | None = None  # 버전을 제거한 arXiv 원본 ID
    title: str  # 논문 제목
    abstract: str | None = None  # 논문 초록
    published_at: str | None = None  # 논문의 최초 공개일
    source_version: str | None = None  # 본문 확보 방식
    source_url: str | None = None  # Hugging Face 등 메타데이터 원본 주소
    pdf_url: str | None = None  # 원본 PDF 주소
    processing_status: str  # completed 또는 reference_only 등 처리 상태
    content_hash: str | None = None  # 논문 본문 변경 여부를 판단하는 해시
    schema_version: str  # 노드를 생성한 Neo4j 스키마 버전
    in_global_corpus: bool = False  # GlobalPaper 보조 라벨 보유 여부


class AuthorNode(BaseModel):
    author_id: str  # 저자를 구분하는 전역 또는 provisional ID
    name: str  # 원문에 표시된 저자 이름
    normalized_name: str  # 검색과 후보 병합을 위해 정규화한 이름
    author_order: int  # 논문 저자 목록에서의 순서


class ChunkNode(BaseModel):
    chunk_id: str  # Qdrant payload와 연결하는 전역 청크 ID
    paper_id: str  # 청크가 속한 논문의 전역 ID
    chunk_index: int  # 논문 안에서 청크가 등장하는 순서
    text: str  # 그래프 근거 추적에 사용할 청크 원문
    section: str | None = None  # 청크가 속한 섹션 제목
    char_count: int  # 청크 원문의 문자 수
    content_hash: str  # 청크 내용 변경 여부를 판단하는 해시
    in_global_corpus: bool = False  # GlobalChunk 보조 라벨 보유 여부


class CitationEdge(BaseModel):
    source_paper_id: str  # 인용하는 논문 ID
    target_paper_id: str  # 인용된 논문 ID


class KnowledgeGraph(BaseModel):
    paper: PaperNode  # 조회 기준이 된 논문
    authors: list[AuthorNode] = Field(default_factory=list)  # AUTHORED_BY 결과
    chunks: list[ChunkNode] = Field(default_factory=list)  # HAS_CHUNK 결과
    citations: list[CitationEdge] = Field(default_factory=list)  # CITES 결과


class GraphExpansion(BaseModel):
    source_chunk_id: str  # Qdrant 검색에서 그래프 탐색을 시작한 청크 ID
    source_paper_id: str  # 시작 청크가 속한 논문 ID
    relationship_type: str  # 탐색에 사용한 Neo4j 관계 타입
    related_paper: PaperNode  # 관계를 따라 발견한 연관 논문
