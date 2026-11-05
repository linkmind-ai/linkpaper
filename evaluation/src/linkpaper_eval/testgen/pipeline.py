"""Generate validated benchmark bundles and regenerate from verified snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
from contextlib import ExitStack
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pydantic import BaseModel, Field

from linkpaper_eval.stores.config import StoreSettings
from linkpaper_eval.testgen import export, offline_engine, sources
from linkpaper_eval.testgen.graph import ChunkGraph, build_chunk_graph


class TestgenResult(BaseModel):
    engine: str
    output: str
    manifest: str = ""
    case_count: int = 0
    graph_summary: dict[str, Any] = Field(default_factory=dict)
    source_summary: dict[str, Any] = Field(default_factory=dict)
    export_summary: str = ""
    problems: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                               allow_nan=False) + "\n", encoding="utf-8")


def _versions() -> dict[str, str]:
    result = {"python": platform.python_version()}
    for package in ("linkpaper-eval", "ragas", "langchain-openai", "qdrant-client", "neo4j"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            pass
    return result


def _publish(staged: dict[str, Path], destinations: dict[str, Path]) -> None:
    """Publish the completion marker last and roll back ordinary I/O failures."""
    order = [key for key in staged if key != "manifest"] + ["manifest"]
    with ExitStack() as stack:
        candidates, backups = {}, {}
        for key in order:
            destination = destinations[key]
            destination.parent.mkdir(parents=True, exist_ok=True)
            directory = Path(stack.enter_context(TemporaryDirectory(
                prefix=".publish-", dir=destination.parent
            )))
            candidates[key] = directory / "new"
            shutil.copyfile(staged[key], candidates[key])
            if destination.exists():
                backups[key] = directory / "old"
                shutil.copyfile(destination, backups[key])
        # A process crash cannot leave an old manifest advertising mixed contents.
        destinations["manifest"].unlink(missing_ok=True)
        changed: list[str] = []
        try:
            for key in order:
                os.replace(candidates[key], destinations[key])
                changed.append(key)
        except OSError:
            for key in reversed(changed):
                if key in backups:
                    os.replace(backups[key], destinations[key])
                else:
                    destinations[key].unlink(missing_ok=True)
            if "manifest" in backups and "manifest" not in changed:
                os.replace(backups["manifest"], destinations["manifest"])
            raise


def _validate_graph(graph: ChunkGraph) -> None:
    ids: set[str] = set()
    for chunk in graph.chunks:
        if not chunk.chunk_id.strip() or not chunk.paper_id.strip() or not chunk.text.strip():
            raise ValueError("Every source chunk needs a nonempty chunk_id, paper_id and text")
        if chunk.chunk_id in ids:
            raise ValueError(f"Duplicate source chunk_id: {chunk.chunk_id}")
        ids.add(chunk.chunk_id)
    if not ids:
        raise ValueError("No source chunks; check filters and database connection")
    for link in graph.links:
        if link.source not in ids or link.target not in ids:
            raise ValueError(f"Graph link references a missing chunk: {link.source} -> {link.target}")


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
    embedding_model_name: str = "text-embedding-3-small",
    overwrite: bool = False,
    snapshot: ChunkGraph | None = None,
    reuse_knowledge_graph: Path | None = None,
    parent_manifest: Path | None = None,
) -> TestgenResult:
    if engine not in {"offline", "ragas"}:
        raise ValueError(f"Unknown engine: {engine}")
    if source not in {"jsonl", "neo4j", "qdrant"}:
        raise ValueError(f"Unknown source: {source}")
    if size < 1 or (limit is not None and limit < 1):
        raise ValueError("size and limit must be positive")
    if not 0 <= single_hop_ratio <= 1 or not 0 <= expand_hops <= 3:
        raise ValueError("single_hop_ratio must be in [0, 1]; expand_hops in [0, 3]")
    if vector_backend not in {"auto", "local", "qdrant"}:
        raise ValueError(f"Unknown vector backend: {vector_backend}")
    if engine != "ragas" and (knowledge_graph_path or reuse_knowledge_graph):
        raise ValueError("KnowledgeGraph save/reuse requires engine=ragas")

    settings = settings or StoreSettings.from_env()
    output = Path(output).resolve()
    destinations = {
        "cases": output,
        "corpus": output.with_suffix(".corpus.jsonl"),
        "graph": output.with_suffix(".graph.json"),
        "manifest": output.with_suffix(".manifest.json"),
    }
    if engine == "ragas":
        destinations["knowledge_graph"] = (
            Path(knowledge_graph_path).resolve() if knowledge_graph_path
            else output.with_suffix(".kg.json")
        )
    if len(set(destinations.values())) != len(destinations):
        raise ValueError("Output artifact paths must be distinct")
    if not overwrite:
        for path in destinations.values():
            if path.exists():
                raise FileExistsError(f"Artifact already exists: {path}; use --overwrite or a new --out")

    resolved_backend = vector_backend
    if resolved_backend == "auto":
        resolved_backend = "local" if source == "jsonl" else "qdrant"
    # JSONL is self-contained and never implicitly connects to Neo4j.
    db_graph = use_graph and source != "jsonl"
    if snapshot is None:
        chunks = sources.load_chunks(source, settings=settings, corpus=corpus,
                                     limit=limit, paper_ids=paper_ids,
                                     expand_hops=expand_hops)
        if not chunks:
            raise ValueError(f"source={source}: no chunks; check filters and database connection")
        chunk_graph = build_chunk_graph(chunks, settings=settings, use_graph=db_graph,
                                        use_vector=use_vector, vector_backend=resolved_backend)
    else:
        chunk_graph = snapshot.model_copy(deep=True)
    chunk_graph.chunks.sort(key=lambda c: (c.paper_id, c.chunk_index or 0, c.chunk_id))
    chunk_graph.links.sort(key=lambda edge: (edge.source, edge.target, edge.type))
    _validate_graph(chunk_graph)
    chunks = chunk_graph.chunks

    output.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    with TemporaryDirectory(prefix=".testgen-", dir=output.parent) as temporary:
        staging = Path(temporary)
        staged = {key: staging / key for key in destinations}
        if engine == "offline":
            cases = offline_engine.generate_offline(chunk_graph, size=size,
                                                     single_hop_ratio=single_hop_ratio, seed=seed)
            export_summary = f"오프라인 템플릿으로 {len(cases)}건 생성 (품질 평가용 아님)"
            export_report = None
        else:
            from linkpaper_eval.testgen import ragas_engine

            kg = None
            if reuse_knowledge_graph:
                kg = ragas_engine.load_knowledge_graph(reuse_knowledge_graph)
                actual = {
                    node.properties.get("document_metadata", {}).get("chunk_id"):
                    node.properties.get("page_content") for node in kg.nodes
                }
                if actual != {chunk.chunk_id: chunk.text for chunk in chunks}:
                    raise ValueError("Saved KnowledgeGraph does not match the source snapshot")
            testset = ragas_engine.generate(
                chunk_graph, size=size, model=model, embedding_model_name=embedding_model_name,
                knowledge_graph_path=staged["knowledge_graph"], knowledge_graph=kg,
                single_hop_ratio=single_hop_ratio, seed=seed,
            )
            cases, report = export.testset_to_cases(testset, chunks)
            export_summary = report.summary()
            export_report = report.model_dump()

        problems = export.validate_cases(cases, chunks)
        if not cases:
            problems.append("No valid generated cases")
        for case in cases:
            if not str(case.get("gold_answer") or "").strip():
                problems.append(f"{case.get('case_id')}: missing reference answer")
        if problems:
            raise ValueError("Generated dataset validation failed: " + "; ".join(problems[:20]))
        if len(cases) != size:
            warnings.append(f"Requested {size} cases, exported {len(cases)}; inspect export counts")
        export.write_cases(cases, staged["cases"])
        export.write_cases([chunk.to_corpus_row() for chunk in chunks], staged["corpus"])
        _json(staged["graph"], chunk_graph.model_dump(mode="json"))
        parameters = dict(source=source, engine=engine, size=size, limit=limit,
                          paper_ids=paper_ids, expand_hops=expand_hops, use_graph=use_graph,
                          use_vector=use_vector, vector_backend=resolved_backend,
                          single_hop_ratio=single_hop_ratio, model=model,
                          embedding_model_name=embedding_model_name, seed=seed)
        manifest = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "parameters": parameters,
            "versions": _versions(),
            "parent_manifest_sha256": _digest(parent_manifest) if parent_manifest else None,
            "source_mode": "snapshot" if snapshot is not None else "live",
            "source_summary": sources.describe(chunks),
            "graph_summary": chunk_graph.summary(),
            "store_identity": {
                "neo4j_database": settings.neo4j.database,
                "qdrant_collection": settings.qdrant.collection,
                "qdrant_vector_name": settings.qdrant.vector_name,
                "vector_origin": (
                    "disabled" if not use_vector else
                    "indexed" if resolved_backend == "qdrant" else "local"
                ),
                "vector_provenance": "Per-chunk metadata in corpus/graph snapshots",
                "local_embedding": (
                    {"provider": settings.embedding.provider,
                     "model": settings.embedding.model,
                     "dimensions": settings.embedding.dimensions}
                    if use_vector and resolved_backend == "local" else None
                ),
            },
            "case_count": len(cases), "export_report": export_report, "warnings": warnings,
            "reproducibility": "Snapshot and seed fix inputs/sampling, not remote LLM outputs.",
            "artifacts": {
                key: {"path": os.path.relpath(path, output.parent), "sha256": _digest(staged[key])}
                for key, path in destinations.items() if key != "manifest"
            },
        }
        if parent_manifest is not None:
            parent = json.loads(parent_manifest.read_text(encoding="utf-8"))
            manifest["store_identity"] = parent["store_identity"]
        _json(staged["manifest"], manifest)
        _publish(staged, destinations)

    return TestgenResult(engine=engine, output=str(output), manifest=str(destinations["manifest"]),
                         case_count=len(cases), graph_summary=chunk_graph.summary(),
                         source_summary=sources.describe(chunks), export_summary=export_summary,
                         warnings=warnings)


def regenerate(
    manifest_path: Path,
    output: Path,
    *,
    size: int | None = None,
    seed: int | None = None,
    single_hop_ratio: float | None = None,
    model: str | None = None,
    overwrite: bool = False,
) -> TestgenResult:
    """Reuse frozen input and transformed Ragas graph without reading the DB."""
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported generation manifest schema")
    paths = {}
    for key, artifact in manifest["artifacts"].items():
        path = (manifest_path.parent / artifact["path"]).resolve()
        if _digest(path) != artifact["sha256"]:
            raise ValueError(f"Snapshot checksum mismatch: {key}")
        paths[key] = path
    snapshot = ChunkGraph.model_validate_json(paths["graph"].read_text(encoding="utf-8"))
    parameters = dict(manifest["parameters"])
    for key, value in dict(size=size, seed=seed, single_hop_ratio=single_hop_ratio, model=model).items():
        if value is not None:
            parameters[key] = value
    return run(**parameters, output=output, snapshot=snapshot,
               reuse_knowledge_graph=paths.get("knowledge_graph"),
               parent_manifest=manifest_path, overwrite=overwrite)
