class LinkPaperError(Exception):
    """예상 가능한 LinkPaper 애플리케이션 오류의 기본 예외."""


class PaperNotFoundError(LinkPaperError):
    def __init__(self, paper_id: str) -> None:
        super().__init__(f"Paper not found: {paper_id}")
        self.paper_id = paper_id
