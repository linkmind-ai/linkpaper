"""벤치마크와 평가셋 생성 명령.

기존 `cli.py`의 서브파서에 명령을 얹는다. `run`, `baseline`, `show`의
동작은 건드리지 않는다. 등록에 실패하더라도 기존 명령은 그대로 쓸 수
있도록, 등록 지점에서 예외를 삼킨다.

    linkpaper-eval bench list
    linkpaper-eval bench prepare --name qasper
    linkpaper-eval bench seed --name qasper
    linkpaper-eval bench run --name qasper --suite retrieval --target hybrid
    linkpaper-eval bench score --run-id <id> --name qasper --suite generation
    linkpaper-eval bench doctor
    linkpaper-eval testgen --source neo4j --engine ragas --size 50
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from linkpaper_eval.benchmark import prepare as prepare_module
from linkpaper_eval.benchmark import registry
from linkpaper_eval.benchmark.download import BenchmarkDownloadError
from linkpaper_eval.gates import load_baseline, save_baseline
from linkpaper_eval.report import render, write
from linkpaper_eval.runner import run_suite, save_run
from linkpaper_eval.stores.config import StoreSettings


def evaluation_root() -> Path:
    """`evaluation/` 루트를 찾는다.

    설치된 패키지에서 실행할 수도 있으므로 현재 작업 디렉터리를 먼저
    본다. `configs/`와 `fixtures/`가 함께 있는 디렉터리가 기준이다.
    """
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "configs").is_dir() and (candidate / "fixtures").is_dir():
            return candidate
    return cwd


def register(subparsers: argparse._SubParsersAction) -> None:
    """`cli.build_parser`가 호출한다."""
    bench = subparsers.add_parser("bench", help="외부 벤치마크 데이터셋 다루기")
    bench_sub = bench.add_subparsers(dest="bench_command", required=True)

    listing = bench_sub.add_parser("list", help="사용 가능한 벤치마크 목록")
    listing.add_argument("--name", help="특정 벤치마크 상세 정보")
    listing.set_defaults(handler=_cmd_list)

    prepare_parser = bench_sub.add_parser(
        "prepare", help="원본을 받아 평가 형식으로 변환한다"
    )
    prepare_parser.add_argument("--name", required=True)
    prepare_parser.add_argument("--limit", type=int, help="케이스 수 상한")
    prepare_parser.add_argument(
        "--force", action="store_true", help="캐시를 무시하고 다시 받는다"
    )
    prepare_parser.set_defaults(handler=_cmd_prepare)

    seed_parser = bench_sub.add_parser(
        "seed", help="벤치마크 코퍼스를 Qdrant/Neo4j에 적재한다"
    )
    seed_parser.add_argument("--name", required=True)
    seed_parser.add_argument("--no-qdrant", action="store_true")
    seed_parser.add_argument("--no-neo4j", action="store_true")
    seed_parser.add_argument(
        "--recreate", action="store_true", help="Qdrant 컬렉션을 다시 만든다"
    )
    seed_parser.set_defaults(handler=_cmd_seed)

    run_parser = bench_sub.add_parser("run", help="준비된 벤치마크로 평가를 실행한다")
    run_parser.add_argument("--name", required=True)
    run_parser.add_argument("--suite", default="retrieval")
    run_parser.add_argument(
        "--target",
        default="baseline",
        help="baseline | http | hybrid | vector",
    )
    run_parser.add_argument("--limit", type=int)
    run_parser.add_argument("--run-id")
    run_parser.add_argument("--quiet", action="store_true")
    run_parser.add_argument(
        "--save-baseline",
        action="store_true",
        help="이번 결과를 이 벤치마크의 베이스라인으로 저장한다",
    )
    run_parser.set_defaults(handler=_cmd_run)

    score_parser = bench_sub.add_parser(
        "score", help="실행 결과를 ragas 지표로 사후 채점한다"
    )
    score_parser.add_argument("--run-id", required=True)
    score_parser.add_argument("--name", help="코퍼스와 정답을 가져올 벤치마크")
    score_parser.add_argument("--suite", default="generation")
    score_parser.add_argument(
        "--metrics",
        default="faithfulness,answer_relevancy,context_recall",
        help="쉼표로 구분한 ragas 지표 이름",
    )
    score_parser.add_argument("--model", default="gpt-4o-mini")
    score_parser.add_argument("--limit", type=int)
    score_parser.set_defaults(handler=_cmd_score)

    doctor = bench_sub.add_parser("doctor", help="의존성과 DB 연결을 점검한다")
    doctor.set_defaults(handler=_cmd_doctor)

    clean = bench_sub.add_parser("clean", help="적재한 벤치마크 데이터를 지운다")
    clean.add_argument("--qdrant", action="store_true", help="컬렉션 삭제")
    clean.add_argument("--neo4j", action="store_true", help="벤치마크 노드 삭제")
    clean.set_defaults(handler=_cmd_clean)

    testgen = subparsers.add_parser(
        "testgen", help="그래프·벡터 인덱스에서 평가셋을 생성한다"
    )
    testgen.add_argument(
        "--source", default="jsonl", help="jsonl | neo4j | qdrant"
    )
    testgen.add_argument("--corpus", help="source=jsonl 일 때의 코퍼스 경로")
    testgen.add_argument(
        "--engine", default="offline", help="offline | ragas"
    )
    testgen.add_argument("--size", type=int, default=20)
    testgen.add_argument("--limit", type=int, help="입력 청크 수 상한")
    testgen.add_argument("--paper-ids", help="쉼표로 구분한 논문 ID")
    testgen.add_argument("--expand-hops", type=int, default=1)
    testgen.add_argument("--single-hop-ratio", type=float, default=0.5)
    testgen.add_argument("--no-graph", action="store_true", help="그래프 간선 사용 안 함")
    testgen.add_argument("--no-vector", action="store_true", help="벡터 간선 사용 안 함")
    testgen.add_argument(
        "--vector-backend", default="auto", help="auto | qdrant | local"
    )
    testgen.add_argument("--model", default="gpt-4o-mini")
    testgen.add_argument("--out", help="출력 JSONL 경로")
    testgen.add_argument(
        "--save-kg", help="ragas KnowledgeGraph를 저장할 경로"
    )
    testgen.add_argument("--seed", type=int, default=20260804)
    testgen.set_defaults(handler=_cmd_testgen)


# ----------------------------------------------------------------------


def _cmd_list(args: argparse.Namespace) -> int:
    if args.name:
        print(prepare_module.describe(args.name))
        return 0

    root = evaluation_root()
    print(f"{'이름':<18}{'라이선스':<24}{'스위트':<28}준비됨")
    print("-" * 82)
    for name in registry.names():
        spec = registry.get(name)
        ready = any(
            prepare_module.is_prepared(root, name, suite) for suite in spec.suites
        )
        print(
            f"{spec.name:<18}{spec.license:<24}"
            f"{', '.join(spec.suites):<28}{'예' if ready else '아니오'}"
        )
    print("\n상세: linkpaper-eval bench list --name <이름>")
    return 0


def _cmd_prepare(args: argparse.Namespace) -> int:
    root = evaluation_root()
    try:
        report = prepare_module.prepare(
            args.name, root, limit=args.limit, force=args.force
        )
    except BenchmarkDownloadError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(report.summary())
    for warning in report.warnings:
        print(f"  경고: {warning}", file=sys.stderr)
    print(f"\n산출물: {prepare_module.benchmark_dir(root, args.name)}")
    return 0


def _cmd_seed(args: argparse.Namespace) -> int:
    from linkpaper_eval.benchmark.seed import seed

    root = evaluation_root()
    corpus = prepare_module.benchmark_dir(root, args.name) / "corpus.jsonl"
    if not corpus.exists():
        print(
            f"코퍼스가 없습니다: {corpus}\n"
            f"먼저 실행하세요: linkpaper-eval bench prepare --name {args.name}",
            file=sys.stderr,
        )
        return 2

    report = seed(
        corpus,
        to_qdrant=not args.no_qdrant,
        to_neo4j=not args.no_neo4j,
        recreate=args.recreate,
    )
    print(
        f"청크 {report.chunks}개 / Qdrant {report.qdrant_points}점 / "
        f"Neo4j {report.neo4j_nodes}노드 (임베딩: {report.embedding or '사용 안 함'})"
    )
    for note in report.notes:
        print(f"  {note}", file=sys.stderr)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    root = evaluation_root()
    config = prepare_module.build_config(
        args.name,
        args.suite,
        root,
        target=args.target,
        limit=args.limit,
    )

    result = run_suite(config, run_id=args.run_id)
    run_dir = save_run(result, config.resolve(config.run.output_dir))
    baseline_values = load_baseline(
        config.resolve(config.baseline) if config.baseline else None
    )

    report_text = render(result, None, baseline_values)
    write(report_text, run_dir / "report.md")
    if not args.quiet:
        print(report_text)
    print(f"\n산출물: {run_dir}", file=sys.stderr)

    if args.save_baseline and config.baseline:
        path = save_baseline(result, config.resolve(config.baseline))
        print(f"베이스라인 저장: {path}", file=sys.stderr)
    return 0


def _cmd_score(args: argparse.Namespace) -> int:
    from linkpaper_eval.benchmark.ragas_metrics import score_run

    root = evaluation_root()
    run_dir = root / "runs" / args.run_id
    corpus = dataset = None
    if args.name:
        directory = prepare_module.benchmark_dir(root, args.name)
        corpus = directory / "corpus.jsonl"
        dataset = directory / f"{args.suite}.jsonl"

    try:
        report = score_run(
            run_dir,
            corpus_path=corpus,
            dataset_path=dataset,
            metrics=tuple(m.strip() for m in args.metrics.split(",") if m.strip()),
            model=args.model,
            limit=args.limit,
        )
    except Exception as exc:  # noqa: BLE001 - 원인을 그대로 보여 준다
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report.aggregate, indent=2, ensure_ascii=False))
    for warning in report.warnings:
        print(f"  경고: {warning}", file=sys.stderr)
    print(f"\n샘플 {report.sample_count}건 / 제외 {report.skipped}건", file=sys.stderr)
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    from linkpaper_eval.ragas_runtime import ragas_version

    settings = StoreSettings.from_env()
    print("의존성")
    # 모듈 이름만 확인하면 안 된다. `evaluation/datasets/` 디렉터리가
    # 네임스페이스 패키지로 잡혀서 `datasets`가 설치된 것처럼 보인다.
    # 실제로 쓰는 심볼까지 확인해야 판정이 맞는다.
    for module, symbol, extra in (
        ("neo4j", "GraphDatabase", "stores"),
        ("qdrant_client", "QdrantClient", "stores"),
        ("datasets", "load_dataset", "bench"),
        ("huggingface_hub", "hf_hub_download", "bench"),
    ):
        try:
            imported = __import__(module, fromlist=[symbol])
            getattr(imported, symbol)
            print(f"  [OK]   {module}")
        except (ImportError, AttributeError):
            print(f"  [없음] {module}  →  pip install -e '.[{extra}]'")
    version = ragas_version()
    print(f"  {'[OK]  ' if version else '[없음]'} ragas {version or ''}")

    print("\n연결")
    ok = True
    try:
        from linkpaper_eval.stores.qdrant_store import QdrantStore

        with QdrantStore(settings.qdrant) as store:
            if store.ping():
                print(f"  [OK]   Qdrant {settings.qdrant.redacted()} / {store.count()}점")
            else:
                ok = False
                print(f"  [실패] Qdrant {settings.qdrant.redacted()}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"  [실패] Qdrant: {type(exc).__name__}: {exc}")

    try:
        from linkpaper_eval.stores.neo4j_store import Neo4jStore

        with Neo4jStore(settings.neo4j) as store:
            if store.ping():
                print(
                    f"  [OK]   Neo4j {settings.neo4j.redacted()} / "
                    f"{store.count_chunks()}청크"
                )
            else:
                ok = False
                print(f"  [실패] Neo4j {settings.neo4j.redacted()}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"  [실패] Neo4j: {type(exc).__name__}: {exc}")

    print(f"\n임베딩 provider: {settings.embedding.provider}")
    print(
        "\nDB가 없어도 `--source jsonl`, `--target baseline`, "
        "`bench prepare --name linkpaper-local`은 동작합니다."
    )
    return 0 if ok else 1


def _cmd_clean(args: argparse.Namespace) -> int:
    if not args.qdrant and not args.neo4j:
        print("--qdrant 또는 --neo4j 중 하나를 지정하세요.", file=sys.stderr)
        return 2

    settings = StoreSettings.from_env()
    if args.qdrant:
        from linkpaper_eval.stores.qdrant_store import QdrantStore

        with QdrantStore(settings.qdrant) as store:
            store.delete_collection()
        print(f"Qdrant 컬렉션 삭제: {settings.qdrant.collection}")
    if args.neo4j:
        from linkpaper_eval.stores.neo4j_store import Neo4jStore

        with Neo4jStore(settings.neo4j) as store:
            removed = store.delete_benchmark_data()
        print(f"Neo4j 벤치마크 노드 삭제: {removed}개")
    return 0


def _cmd_testgen(args: argparse.Namespace) -> int:
    from linkpaper_eval.testgen import pipeline

    root = evaluation_root()
    output = Path(args.out) if args.out else (
        root / "datasets" / "generated" / f"{args.engine}-{args.source}.jsonl"
    )
    paper_ids = (
        [value.strip() for value in args.paper_ids.split(",") if value.strip()]
        if args.paper_ids
        else None
    )

    try:
        result = pipeline.run(
            source=args.source,
            output=output,
            engine=args.engine,
            corpus=args.corpus,
            size=args.size,
            limit=args.limit,
            paper_ids=paper_ids,
            expand_hops=args.expand_hops,
            use_graph=not args.no_graph,
            use_vector=not args.no_vector,
            vector_backend=args.vector_backend,
            single_hop_ratio=args.single_hop_ratio,
            model=args.model,
            knowledge_graph_path=Path(args.save_kg) if args.save_kg else None,
            seed=args.seed,
        )
    except Exception as exc:  # noqa: BLE001 - 원인을 그대로 보여 준다
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"입력: {json.dumps(result.source_summary, ensure_ascii=False)}")
    print(f"그래프: {json.dumps(result.graph_summary, ensure_ascii=False)}")
    print(f"{result.export_summary}")
    print(f"\n케이스 {result.case_count}건 → {result.output}")
    if result.problems:
        print("\n검증 문제:", file=sys.stderr)
        for problem in result.problems[:20]:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    return 0
