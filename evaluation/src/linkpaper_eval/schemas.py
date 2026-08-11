"""평가 하네스가 사용하는 공통 데이터 계약.

이 모듈의 스키마는 평가 팀과 백엔드/GraphRAG 팀 사이의 인터페이스다.
백엔드 응답 형식이 바뀌면 `targets/` 어댑터에서 흡수하고, 이 스키마는
평가 지표가 의존하는 안정적인 형태로 유지한다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Scope = Literal["selected", "global", "unknown"]
RetrievalSource = Literal[
    "qdrant_vector",
    "neo4j_graph",
    "lexical_baseline",
    "unknown",
]


class Triple(BaseModel):
    """지식그래프 추출 결과 트리플."""

    model_config = ConfigDict(extra="ignore")

    subject: str
    predicate: str
    object: str
    chunk_id: str | None = None
    confidence: float | None = None

    def key(self) -> tuple[str, str, str]:
        """대소문자·공백을 정규화한 비교용 키."""
        return (
            _normalize(self.subject),
            _normalize(self.predicate),
            _normalize(self.object),
        )


class EvalCase(BaseModel):
    """평가 데이터셋의 한 건. JSONL 한 줄이 하나의 케이스다."""

    model_config = ConfigDict(extra="ignore")

    case_id: str
    question: str
    paper_id: str | None = None

    # 검색 정답
    gold_chunk_ids: list[str] = Field(default_factory=list)
    gold_paper_ids: list[str] = Field(default_factory=list)
    grades: dict[str, int] = Field(default_factory=dict)

    # 라우팅 정답 (선택 논문만으로 답변 가능한가)
    expected_scope: Scope = "unknown"

    # 생성 정답
    gold_answer: str | None = None
    must_include: list[str] = Field(default_factory=list)

    # 추출 정답
    gold_triples: list[Triple] = Field(default_factory=list)

    tags: list[str] = Field(default_factory=list)
    notes: str | None = None

    def grade_of(self, chunk_id: str) -> int:
        """등급이 명시되지 않은 정답 청크는 이진 관련도 1로 간주한다."""
        if chunk_id in self.grades:
            return self.grades[chunk_id]
        return 1 if chunk_id in self.gold_chunk_ids else 0

    def graded_ids(self) -> list[str]:
        ids = set(self.gold_chunk_ids)
        ids.update(k for k, v in self.grades.items() if v > 0)
        return sorted(ids)


class RetrievedItem(BaseModel):
    """검색기가 반환한 후보 하나.

    data-retrieval-architecture.md 8장의 통합 후보 계약과 필드를 맞춘다.
    """

    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    paper_id: str | None = None
    text: str = ""
    scope: Scope = "unknown"
    retrieval_source: RetrievalSource = "unknown"
    rank: int | None = None
    score: float | None = None
    section: str | None = None
    matched_entity_ids: list[str] = Field(default_factory=list)


class Usage(BaseModel):
    """토큰 및 비용 회계."""

    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class TargetResponse(BaseModel):
    """평가 대상 시스템(SUT)의 응답.

    백엔드가 이 형태로 응답하면 어댑터 없이 바로 평가할 수 있다.
    """

    model_config = ConfigDict(extra="ignore")

    answer: str = ""
    citations: list[str] = Field(default_factory=list)
    retrieved: list[RetrievedItem] = Field(default_factory=list)
    scope: Scope = "unknown"
    triples: list[Triple] = Field(default_factory=list)

    latency_ms: float = 0.0
    usage: Usage = Field(default_factory=Usage)
    error: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    def ranked_chunk_ids(self) -> list[str]:
        """rank 필드가 있으면 그 순서를, 없으면 배열 순서를 신뢰한다."""
        items = list(self.retrieved)
        if all(item.rank is not None for item in items) and items:
            items.sort(key=lambda item: item.rank or 0)
        seen: set[str] = set()
        ordered: list[str] = []
        for item in items:
            if item.chunk_id not in seen:
                seen.add(item.chunk_id)
                ordered.append(item.chunk_id)
        return ordered

    def evidence_text(self) -> str:
        return "\n".join(item.text for item in self.retrieved if item.text)


class CaseResult(BaseModel):
    """케이스 하나의 실행 결과와 지표."""

    model_config = ConfigDict(extra="ignore")

    case_id: str
    question: str
    expected_scope: Scope = "unknown"
    actual_scope: Scope = "unknown"
    metrics: dict[str, float] = Field(default_factory=dict)
    latency_ms: float = 0.0
    error: str | None = None
    answer: str = ""
    citations: list[str] = Field(default_factory=list)
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class RunManifest(BaseModel):
    """실행 재현에 필요한 메타데이터."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    suite: str
    target: str
    dataset: str
    dataset_sha256: str
    config_sha256: str
    git_sha: str | None = None
    started_at: str
    finished_at: str | None = None
    case_count: int = 0
    judge: str | None = None
    notes: str | None = None


class RunResult(BaseModel):
    """실행 전체 결과. `metrics.json`으로 직렬화된다."""

    model_config = ConfigDict(extra="ignore")

    manifest: RunManifest
    aggregate: dict[str, float] = Field(default_factory=dict)
    by_tag: dict[str, dict[str, float]] = Field(default_factory=dict)
    cases: list[CaseResult] = Field(default_factory=list)


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").split())
