"""ragas 기반 평가셋 생성.

https://docs.ragas.io/en/stable/getstarted/rag_testset_generation/ 의
2단계 구조를 그대로 따른다.

1. **KnowledgeGraph 생성** — 청크를 노드로 넣고 transform으로 요약·테마·
   엔티티·임베딩을 붙인다.
2. **Testset 생성** — 시나리오를 만들고 질문·정답을 합성한다.

LinkPaper가 여기에 더하는 것은 관계다. ragas의 기본 관계는 코사인 유사도와
엔티티 겹침으로만 만들어지는데, 우리에게는 이미 Neo4j에 명시적인 인용
관계가 있다. 인용으로 연결된 청크 쌍을 KnowledgeGraph에 함께 넣으면
멀티홉 질문이 "우연히 비슷한 두 문단"이 아니라 "실제로 이어진 연구 흐름"
위에서 만들어진다. 이것이 LinkPaper의 문제의식과 직결되는 부분이다.

주의: 관계 속성 이름(`entities_overlap_score` 등)은 ragas 내부 시나리오
생성기가 참조하는 값이라 버전에 따라 달라질 수 있다. 인식되지 않아도
ragas 자체 관계로 생성은 계속되므로, 실패가 아니라 품질 저하로 나타난다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from linkpaper_eval.ragas_runtime import build_embeddings, build_llm, require_ragas
from linkpaper_eval.testgen.graph import ChunkGraph

logger = logging.getLogger(__name__)

# 청크가 이미 잘려 있으므로 분할 transform은 쓰지 않는다. 추출기만 적용한다.
_TRANSFORM_SPECS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("SummaryExtractor", ("llm",)),
    ("EmbeddingExtractor", ("embedding_model",)),
    ("ThemesExtractor", ("llm",)),
    ("NERExtractor", ("llm",)),
)

# 우리 간선을 ragas 관계 속성으로 옮길 때 쓰는 이름.
_LINK_PROPERTY = {
    "cites": "entities_overlap_score",
    "shared_entity": "entities_overlap_score",
    "next": "entities_overlap_score",
    "vector": "summary_similarity",
}


def _construct(cls: Any, candidates: dict[str, Any]) -> Any | None:
    """생성자 시그니처를 모르는 상태에서 안전하게 인스턴스를 만든다."""
    for kwargs in (candidates, {}):
        try:
            return cls(**kwargs)
        except TypeError:
            continue
        except Exception as exc:  # noqa: BLE001 - 이 transform만 건너뛴다
            logger.warning("transform %s 생성 실패: %s", cls.__name__, exc)
            return None
    return None


def chunk_transforms(llm: Any, embedding_model: Any) -> list[Any]:
    """미리 청킹된 데이터에 맞는 transform 목록."""
    import ragas.testset.transforms as transforms

    available: dict[str, Any] = {"llm": llm, "embedding_model": embedding_model}
    built: list[Any] = []
    for name, needs in _TRANSFORM_SPECS:
        cls = getattr(transforms, name, None)
        if cls is None:
            logger.info("설치된 ragas에 %s가 없어 건너뜁니다", name)
            continue
        instance = _construct(cls, {key: available[key] for key in needs})
        if instance is not None:
            built.append(instance)
    return built


def build_knowledge_graph(
    chunk_graph: ChunkGraph,
    llm: Any,
    embedding_model: Any,
    apply_transforms: bool = True,
    inject_links: bool = True,
) -> Any:
    """`ChunkGraph`를 ragas `KnowledgeGraph`로 옮긴다."""
    require_ragas()
    from ragas.testset.graph import KnowledgeGraph, Node, NodeType, Relationship

    kg = KnowledgeGraph()
    node_by_chunk: dict[str, Any] = {}

    for chunk in chunk_graph.chunks:
        node = Node(
            type=NodeType.CHUNK,
            properties={
                "page_content": chunk.text,
                "document_metadata": {
                    # chunk_id를 메타데이터에 실어야 생성 결과를 정답 청크
                    # ID로 되돌릴 수 있다. 이 값이 없으면 검색 지표를 만들 수
                    # 없고 생성 스위트로만 쓸 수 있다.
                    "chunk_id": chunk.chunk_id,
                    "paper_id": chunk.paper_id,
                    "section": chunk.section,
                    "title": chunk.title,
                },
            },
        )
        kg.nodes.append(node)
        node_by_chunk[chunk.chunk_id] = node

    if apply_transforms:
        from ragas.testset.transforms import apply_transforms as run_transforms

        transforms = chunk_transforms(llm, embedding_model)
        if transforms:
            run_transforms(kg, transforms)

    if inject_links:
        injected = 0
        for link in chunk_graph.links:
            source = node_by_chunk.get(link.source)
            target = node_by_chunk.get(link.target)
            if source is None or target is None:
                continue
            property_name = _LINK_PROPERTY.get(link.type, "summary_similarity")
            score = link.score if link.score is not None else 0.9
            try:
                kg.relationships.append(
                    Relationship(
                        source=source,
                        target=target,
                        type=f"linkpaper_{link.type}",
                        bidirectional=True,
                        properties={
                            property_name: float(score),
                            "linkpaper_link_type": link.type,
                        },
                    )
                )
                injected += 1
            except Exception as exc:  # noqa: BLE001 - 관계 하나가 실패해도 계속
                logger.warning("관계 주입 실패 (%s): %s", link.type, exc)
        logger.info("LinkPaper 그래프 관계 %d개를 주입했습니다", injected)

    return kg


def generate(
    chunk_graph: ChunkGraph,
    size: int = 20,
    model: str = "gpt-4o-mini",
    embedding_model_name: str = "text-embedding-3-small",
    knowledge_graph_path: Path | None = None,
    apply_transforms: bool = True,
    inject_links: bool = True,
) -> Any:
    """ragas Testset을 만든다. 반환값은 ragas의 `Testset` 객체다."""
    require_ragas()
    from ragas.testset import TestsetGenerator
    from ragas.testset.synthesizers import default_query_distribution

    llm = build_llm(model)
    embeddings = build_embeddings(embedding_model_name)

    kg = build_knowledge_graph(
        chunk_graph,
        llm,
        embeddings,
        apply_transforms=apply_transforms,
        inject_links=inject_links,
    )

    if knowledge_graph_path is not None:
        # 지식그래프 구축은 이 파이프라인에서 가장 비싼 단계다. 저장해 두면
        # 질문 분포만 바꿔 다시 생성할 때 재사용할 수 있다.
        knowledge_graph_path.parent.mkdir(parents=True, exist_ok=True)
        kg.save(str(knowledge_graph_path))

    generator = TestsetGenerator(
        llm=llm, embedding_model=embeddings, knowledge_graph=kg
    )
    return generator.generate(
        testset_size=size, query_distribution=default_query_distribution(llm)
    )


def load_knowledge_graph(path: Path) -> Any:
    require_ragas()
    from ragas.testset.graph import KnowledgeGraph

    return KnowledgeGraph.load(str(path))
