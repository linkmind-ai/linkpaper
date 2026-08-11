"""평가셋 생성 파이프라인.

    청크 확보 → 그래프/벡터 간선 구성 → 질문 생성 → 검증 → JSONL 저장

엔진은 두 가지다. `ragas`는 실제 사용할 데이터셋을 만들고, `offline`은
LLM 없이 같은 경로를 끝까지 돌려 배관을 확인한다. 두 엔진이 같은
`ChunkGraph`를 입력으로 받고 같은 형식을 출력하므로, 오프라인에서 통과한
파이프라인은 ragas로 바꿔도 그대로 동작한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from linkpaper_eval.stores.config import StoreSettings
from linkpaper_eval.testgen import export, offline_engine, sources
from linkpaper_eval.testgen.graph import build_chunk_graph


class TestgenResult(BaseModel):
    engine: str
    output: str
    case_count: int = 0
    graph_summary: dict[str, Any] = Field(default_factory=dict)
    source_summary: dict[str, Any] = Field(default_factory=dict)
    export_summary: str = ""
    problems: list[str] = Field(default_factory=list)


def run(
    source: str,
    output: Path,
    engine: str = "offline",
    corpus: str | Path | None = None,
    settings: StoreSettings | None = None,
    size: int = 20,
    limit: int | None = None,
    paper_ids: list[str] | None = None,
    expand_hops: int = 1,
    use_graph: bool = True,
    use_vector: bool = True,
    vector_backend: str = "auto",
    single_hop_ratio: float = 0.5,
    model: str = "gpt-4o-mini",
    knowledge_graph_path: Path | None = None,
    seed: int = 20260804,
) -> TestgenResult:
    settings = settings or StoreSettings.from_env()

    chunks = sources.load_chunks(
        source,
        settings=settings,
        corpus=corpus,
        limit=limit,
        paper_ids=paper_ids,
        expand_hops=expand_hops,
    )
    if not chunks:
        raise ValueError(
            f"source={source} 에서 청크를 하나도 읽지 못했습니다. "
            "적재 상태와 접속 설정을 확인하세요 (linkpaper-eval bench doctor)."
        )

    chunk_graph = build_chunk_graph(
        chunks,
        settings=settings,
        use_graph=use_graph,
        use_vector=use_vector,
        vector_backend=vector_backend,
    )

    if engine == "offline":
        cases = offline_engine.generate_offline(
            chunk_graph,
            size=size,
            single_hop_ratio=single_hop_ratio,
            seed=seed,
        )
        export_summary = f"오프라인 템플릿으로 {len(cases)}건 생성"
    elif engine == "ragas":
        from linkpaper_eval.testgen import ragas_engine

        testset = ragas_engine.generate(
            chunk_graph,
            size=size,
            model=model,
            knowledge_graph_path=knowledge_graph_path,
        )
        cases, report = export.testset_to_cases(testset, chunks)
        export_summary = report.summary()
    else:
        raise ValueError(f"알 수 없는 엔진: {engine} (사용 가능: offline, ragas)")

    problems = export.validate_cases(cases, chunks)
    export.write_cases(cases, output)

    return TestgenResult(
        engine=engine,
        output=str(output),
        case_count=len(cases),
        graph_summary=chunk_graph.summary(),
        source_summary=sources.describe(chunks),
        export_summary=export_summary,
        problems=problems,
    )
