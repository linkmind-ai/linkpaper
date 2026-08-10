"""벤치마크·저장소·평가셋 생성 경로 테스트.

전부 오프라인에서 돌아야 한다. 네트워크, API 키, 실행 중인 데이터베이스가
없는 CI에서도 이 경로가 살아 있는지 확인하는 것이 목적이다. DB가 필요한
부분은 어댑터가 지연 임포트를 하는지까지만 본다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from linkpaper_eval.benchmark import registry
from linkpaper_eval.benchmark.converters import (
    EvidenceMatcher,
    convert_local,
    split_text,
)
from linkpaper_eval.benchmark.download import manual_instructions
from linkpaper_eval.benchmark.prepare import build_config, prepare
from linkpaper_eval.stores.embedding import HashEmbedder, build_embedder
from linkpaper_eval.stores.records import ChunkRecord, make_chunk_id, normalize_paper_id
from linkpaper_eval.targets import build_target
from linkpaper_eval.testgen import export, sources
from linkpaper_eval.testgen.graph import build_chunk_graph, vector_links_local
from linkpaper_eval.testgen.offline_engine import generate_offline

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "fixtures" / "mock_corpus.jsonl"


# ----------------------------------------------------------------------
# 레지스트리
# ----------------------------------------------------------------------


def test_registry_contains_expected_benchmarks() -> None:
    names = registry.names()
    assert {"qasper", "multihop-rag", "graphrag-bench", "linkpaper-local"} <= set(names)
    for name in names:
        spec = registry.get(name)
        assert spec.converter, f"{name}: 변환기가 지정되지 않았다"
        assert spec.suites, f"{name}: 스위트가 비어 있다"


def test_non_redistributable_benchmarks_are_flagged() -> None:
    """재배포 금지 데이터셋은 반드시 표시되어야 한다.

    이 플래그가 문서와 gitignore 정책의 근거다.
    """
    assert registry.get("graphrag-bench").redistributable is False
    assert registry.get("qasper").redistributable is True


def test_unknown_benchmark_raises_with_available_names() -> None:
    with pytest.raises(KeyError) as excinfo:
        registry.get("nope")
    assert "qasper" in str(excinfo.value)


# ----------------------------------------------------------------------
# 레코드와 식별자
# ----------------------------------------------------------------------


def test_chunk_id_follows_schema_format() -> None:
    chunk_id = make_chunk_id("arxiv:1706.03762", 12, "hello world")
    prefix, _, suffix = chunk_id.rpartition(":")
    assert prefix == "arxiv:1706.03762:chunk:12"
    assert len(suffix) == 8


def test_chunk_id_is_deterministic_and_content_sensitive() -> None:
    first = make_chunk_id("arxiv:1", 0, "same text")
    assert first == make_chunk_id("arxiv:1", 0, "same text")
    assert first != make_chunk_id("arxiv:1", 0, "other text")


def test_normalize_paper_id_preserves_existing_prefix() -> None:
    assert normalize_paper_id("1706.03762") == "arxiv:1706.03762"
    assert normalize_paper_id("arxiv:1706.03762") == "arxiv:1706.03762"
    assert normalize_paper_id("hf:abc") == "hf:abc"


def test_chunk_record_reads_camel_case_payload() -> None:
    """적재 주체가 camelCase를 써도 평가가 깨지지 않아야 한다."""
    record = ChunkRecord.from_payload(
        {"chunkId": "c1", "paperId": "arxiv:1", "text": "hi", "chunkIndex": 3}
    )
    assert (record.chunk_id, record.paper_id, record.chunk_index) == ("c1", "arxiv:1", 3)


# ----------------------------------------------------------------------
# 임베딩
# ----------------------------------------------------------------------


def test_hash_embedder_is_deterministic_and_normalized() -> None:
    embedder = HashEmbedder(dimensions=64)
    first = embedder.embed(["retrieval augmented generation"])[0]
    second = embedder.embed(["retrieval augmented generation"])[0]
    assert first == second
    assert abs(sum(value * value for value in first) - 1.0) < 1e-9


def test_hash_embedder_scores_related_text_higher() -> None:
    embedder = HashEmbedder(dimensions=256)
    vectors = embedder.embed(
        [
            "the transformer uses multi-head self-attention",
            "multi-head attention lets the transformer attend jointly",
            "sourdough bread needs a long fermentation",
        ]
    )

    def cosine(left, right):
        return sum(a * b for a, b in zip(left, right))

    assert cosine(vectors[0], vectors[1]) > cosine(vectors[0], vectors[2])


def test_build_embedder_defaults_to_offline_provider() -> None:
    assert build_embedder().name == "hash"


# ----------------------------------------------------------------------
# 변환
# ----------------------------------------------------------------------


def test_split_text_respects_max_chars() -> None:
    text = "\n\n".join(["단락 " + "가" * 300 for _ in range(6)])
    chunks = split_text(text, max_chars=500)
    assert chunks
    assert all(len(chunk) <= 500 for chunk in chunks)


def test_evidence_matcher_prefers_exact_over_fuzzy() -> None:
    chunks = [
        ChunkRecord(chunk_id="c1", paper_id="p1", text="The Transformer uses attention."),
        ChunkRecord(chunk_id="c2", paper_id="p1", text="BERT pretrains bidirectionally."),
    ]
    matcher = EvidenceMatcher(chunks)
    assert matcher.match("The Transformer uses attention.") == "c1"
    assert matcher.match("the transformer uses attention") == "c1"
    assert matcher.match("완전히 무관한 문장입니다") is None


def test_evidence_matcher_ignores_float_evidence() -> None:
    """QASPER의 그림·표 근거는 본문 청크로 매칭할 수 없다."""
    chunks = [ChunkRecord(chunk_id="c1", paper_id="p1", text="body text here")]
    matcher = EvidenceMatcher(chunks)
    assert matcher.match("FLOAT SELECTED: Table 1 shows results") is None


def test_convert_local_produces_usable_dataset(tmp_path: Path) -> None:
    out_dir = tmp_path / "benchmarks" / "data" / "linkpaper-local"
    raw = {
        "corpus": CORPUS,
        **{
            suite: ROOT / "datasets" / suite / "sample.jsonl"
            for suite in ("retrieval", "generation", "extraction")
        },
    }
    report = convert_local(raw, out_dir, limit=None)

    assert report.chunk_count > 0
    assert (out_dir / "corpus.jsonl").exists()
    assert (out_dir / "retrieval.jsonl").exists()

    corpus_ids = {
        json.loads(line)["chunk_id"]
        for line in (out_dir / "corpus.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    for line in (out_dir / "retrieval.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        for chunk_id in case.get("gold_chunk_ids", []):
            assert chunk_id in corpus_ids, f"{case['case_id']}: 코퍼스에 없는 청크"


def test_manual_instructions_name_the_target_path() -> None:
    """자동 다운로드 실패 메시지는 그 자체로 설정 안내여야 한다."""
    spec = registry.get("qasper")
    target = Path("/tmp/benchmarks/data/qasper/raw/qasper.jsonl")
    message = manual_instructions(spec, spec.files[0], target)
    assert str(target) in message
    assert spec.homepage in message


# ----------------------------------------------------------------------
# 실행 설정
# ----------------------------------------------------------------------


def test_prepare_and_build_config_round_trip(tmp_path: Path) -> None:
    """`prepare` 산출물을 `build_config`가 그대로 읽어야 한다."""
    root = tmp_path / "evaluation"
    (root / "fixtures").mkdir(parents=True)
    (root / "configs").mkdir()
    (root / "fixtures" / "mock_corpus.jsonl").write_text(
        CORPUS.read_text(encoding="utf-8"), encoding="utf-8"
    )
    for suite in ("retrieval", "generation", "extraction"):
        source = ROOT / "datasets" / suite / "sample.jsonl"
        target = root / "datasets" / suite
        target.mkdir(parents=True)
        (target / "sample.jsonl").write_text(
            source.read_text(encoding="utf-8"), encoding="utf-8"
        )

    report = prepare("linkpaper-local", root)
    assert report.case_counts["retrieval"] > 0

    config = build_config("linkpaper-local", "retrieval", root, target="baseline")
    assert config.suite == "retrieval"
    assert config.resolve(config.dataset).exists()
    assert config.resolve(config.target["options"]["corpus"]).exists()


def test_build_config_rejects_unknown_target(tmp_path: Path) -> None:
    root = tmp_path
    directory = root / "benchmarks" / "data" / "demo"
    directory.mkdir(parents=True)
    (directory / "retrieval.jsonl").write_text("", encoding="utf-8")
    registry.REGISTRY["demo"] = registry.BenchmarkSpec(
        name="demo", title="demo", description="", converter="local"
    )
    try:
        with pytest.raises(ValueError):
            build_config("demo", "retrieval", root, target="telepathy")
    finally:
        registry.REGISTRY.pop("demo", None)


def test_hybrid_target_builds_without_touching_databases() -> None:
    """타깃 생성만으로 DB에 붙으면 안 된다.

    연결이 생성자에서 일어나면 설정 실수를 케이스 실행이 아니라 프로세스
    시작 시점에 알게 되고, 오프라인 CI에서 타깃 등록조차 확인할 수 없다.
    """
    target = build_target({"type": "graphrag_hybrid", "options": {"top_k": 3}})
    try:
        assert target.name == "graphrag_hybrid"
        assert target.top_k == 3
    finally:
        target.close()


def test_unknown_target_still_raises() -> None:
    with pytest.raises(ValueError, match="Unknown target type"):
        build_target({"type": "telepathy"})


# ----------------------------------------------------------------------
# 평가셋 생성
# ----------------------------------------------------------------------


def test_vector_links_connect_different_papers() -> None:
    chunks = sources.from_jsonl(CORPUS)
    links = vector_links_local(chunks, top_k=3)
    assert links, "벡터 간선이 하나도 만들어지지 않았다"
    lookup = {chunk.chunk_id: chunk for chunk in chunks}
    assert all(
        lookup[link.source].paper_id != lookup[link.target].paper_id for link in links
    )


def test_offline_generation_yields_valid_cases() -> None:
    chunks = sources.from_jsonl(CORPUS)
    graph = build_chunk_graph(chunks, use_graph=False, use_vector=True)
    cases = generate_offline(graph, size=10)

    assert len(cases) == 10
    assert not export.validate_cases(cases, chunks)

    multi_hop = [case for case in cases if "multi-hop" in case["tags"]]
    assert multi_hop, "멀티홉 케이스가 생성되지 않았다"
    for case in multi_hop:
        assert case["expected_scope"] == "global"
        assert len(case["gold_paper_ids"]) == 2


def test_offline_generation_is_deterministic() -> None:
    chunks = sources.from_jsonl(CORPUS)
    graph = build_chunk_graph(chunks, use_graph=False, use_vector=True)
    first = generate_offline(graph, size=8, seed=7)
    second = generate_offline(graph, size=8, seed=7)
    assert [case["question"] for case in first] == [
        case["question"] for case in second
    ]


def test_generated_questions_avoid_function_words() -> None:
    """주제어 대신 기능어가 뽑히면 질문이 무의미해진다."""
    chunks = sources.from_jsonl(CORPUS)
    graph = build_chunk_graph(chunks, use_graph=False, use_vector=True)
    questions = " ".join(case["question"] for case in generate_offline(graph, size=10))
    for word in ("cannot", "between", "which", "however"):
        assert f" {word} " not in questions


def test_validate_cases_catches_unknown_gold_chunk() -> None:
    chunks = sources.from_jsonl(CORPUS)
    problems = export.validate_cases(
        [
            {
                "case_id": "bad-1",
                "question": "q",
                "gold_chunk_ids": ["arxiv:0000.0000:chunk:0:deadbeef"],
            }
        ],
        chunks,
    )
    assert problems and "코퍼스에 없는" in problems[0]


def test_validate_cases_catches_duplicate_ids() -> None:
    chunks = sources.from_jsonl(CORPUS)
    case = {"case_id": "dup", "question": "q", "gold_chunk_ids": []}
    problems = export.validate_cases([case, dict(case)], chunks)
    assert any("중복" in problem for problem in problems)


# ----------------------------------------------------------------------
# 선택 의존성
# ----------------------------------------------------------------------


def test_optional_modules_import_without_drivers() -> None:
    """드라이버와 ragas가 없어도 임포트만으로 실패하면 안 된다."""
    import linkpaper_eval.benchmark.ragas_metrics  # noqa: F401
    import linkpaper_eval.stores  # noqa: F401
    import linkpaper_eval.stores.neo4j_store  # noqa: F401
    import linkpaper_eval.stores.qdrant_store  # noqa: F401
    import linkpaper_eval.testgen.ragas_engine  # noqa: F401


def test_ragas_runtime_reports_missing_install() -> None:
    from linkpaper_eval import ragas_runtime

    if ragas_runtime.ragas_version() is not None:
        pytest.skip("ragas가 설치되어 있다")
    with pytest.raises(RuntimeError, match="ragas"):
        ragas_runtime.require_ragas()


# ----------------------------------------------------------------------
# Qdrant 통합 (임베디드 모드, 서버 불필요)
# ----------------------------------------------------------------------


def _qdrant_available() -> bool:
    try:
        import qdrant_client  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(not _qdrant_available(), reason="qdrant-client 미설치")
def test_qdrant_roundtrip_in_embedded_mode() -> None:
    """적재부터 검색까지 실제 Qdrant API로 확인한다.

    `:memory:` 모드는 서버 모드와 API가 같으므로, 여기서 통과하면 어댑터가
    클라이언트 버전과 맞는다는 뜻이다. `search`가 `query_points`로 바뀐
    것 같은 변경을 놓치지 않기 위한 테스트다.
    """
    from linkpaper_eval.stores.config import QdrantSettings
    from linkpaper_eval.stores.qdrant_store import QdrantStore

    chunks = sources.from_jsonl(CORPUS)
    embedder = HashEmbedder(dimensions=128)
    vectors = embedder.embed([chunk.text for chunk in chunks])

    settings = QdrantSettings(url=":memory:", collection="test_chunks")
    with QdrantStore(settings) as store:
        store.ensure_collection(len(vectors[0]))
        written = store.upsert_chunks(chunks, vectors)
        assert written == len(chunks)
        assert store.count() == len(chunks)

        # 적재한 청크를 자기 자신으로 검색하면 1위로 나와야 한다.
        target = chunks[0]
        hits = store.search(vectors[0], top_k=3)
        assert hits and hits[0].chunk.chunk_id == target.chunk_id
        assert hits[0].chunk.paper_id == target.paper_id

        # paper_id 필터가 범위를 실제로 좁히는지
        other = next(c for c in chunks if c.paper_id != target.paper_id)
        filtered = store.search(vectors[0], top_k=5, paper_ids=[other.paper_id])
        assert filtered
        assert all(hit.chunk.paper_id == other.paper_id for hit in filtered)

        assert len(list(store.iter_chunks())) == len(chunks)


@pytest.mark.skipif(not _qdrant_available(), reason="qdrant-client 미설치")
def test_qdrant_upsert_is_idempotent() -> None:
    """같은 코퍼스를 두 번 넣어도 point 수가 늘면 안 된다."""
    from linkpaper_eval.stores.config import QdrantSettings
    from linkpaper_eval.stores.qdrant_store import QdrantStore

    chunks = sources.from_jsonl(CORPUS)
    vectors = HashEmbedder(dimensions=64).embed([chunk.text for chunk in chunks])

    with QdrantStore(QdrantSettings(url=":memory:", collection="idem")) as store:
        store.ensure_collection(64)
        store.upsert_chunks(chunks, vectors)
        store.upsert_chunks(chunks, vectors)
        assert store.count() == len(chunks)


@pytest.mark.skipif(not _qdrant_available(), reason="qdrant-client 미설치")
def test_hybrid_target_retrieves_from_vector_index(tmp_path: Path) -> None:
    """하이브리드 타깃이 실제 벡터 인덱스에서 정답을 찾아오는지 확인한다.

    Neo4j 없이 벡터 경로만 본다. 그래프 확장은 DB가 필요하므로 끈다.
    """
    from linkpaper_eval.schemas import EvalCase
    from linkpaper_eval.stores.config import QdrantSettings
    from linkpaper_eval.stores.qdrant_store import QdrantStore

    url = f"file://{tmp_path / 'qdrant'}"
    chunks = sources.from_jsonl(CORPUS)
    vectors = HashEmbedder(dimensions=128).embed([chunk.text for chunk in chunks])

    with QdrantStore(QdrantSettings(url=url, collection="hybrid")) as store:
        store.ensure_collection(128)
        store.upsert_chunks(chunks, vectors)

    target = build_target(
        {
            "type": "graphrag_hybrid",
            "options": {
                "top_k": 5,
                "graph_expansion": False,
                "qdrant": {"url": url, "collection": "hybrid"},
                "embedding": {"provider": "hash", "dimensions": 128},
            },
        }
    )
    try:
        case = EvalCase(
            case_id="t1",
            question="What attention mechanism does the Transformer use?",
            paper_id="arxiv:1706.03762",
        )
        response = target.run(case)
    finally:
        target.close()

    assert response.error is None
    assert response.retrieved, "검색 결과가 비어 있다"
    assert response.scope in {"selected", "global"}
    assert response.citations
    # 인용은 반드시 검색 결과 안에 있어야 한다. citation_validity의 전제다.
    retrieved_ids = {item.chunk_id for item in response.retrieved}
    assert set(response.citations) <= retrieved_ids
    assert all(item.retrieval_source == "qdrant_vector" for item in response.retrieved)
