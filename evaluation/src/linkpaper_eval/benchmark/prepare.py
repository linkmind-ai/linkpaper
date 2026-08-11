"""벤치마크 준비: 다운로드 → 변환 → 매니페스트.

`prepare`가 끝나면 `benchmarks/data/<name>/` 아래에 기존 하네스가 바로
읽을 수 있는 파일이 놓인다.

    benchmarks/data/qasper/
    ├── raw/              # 원본 (재다운로드 방지용 캐시)
    ├── corpus.jsonl      # 청크 코퍼스
    ├── retrieval.jsonl   # EvalCase
    ├── generation.jsonl
    └── manifest.json     # 원본 해시, 케이스 수, 근거 매칭률

여기서 만든 데이터셋은 `runner.run_suite`가 기존 스위트와 똑같이 처리한다.
벤치마크를 위해 지표 계산이나 실행 골격을 새로 만들지 않는다는 뜻이며,
그래야 자체 데이터셋과 외부 벤치마크 점수를 같은 축에서 볼 수 있다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from linkpaper_eval.benchmark import registry
from linkpaper_eval.benchmark.converters import (
    CONVERTERS,
    ConversionReport,
    write_manifest,
)
from linkpaper_eval.benchmark.download import ensure_raw_files
from linkpaper_eval.config import EvalConfig, RunOptions
from linkpaper_eval.datasets import file_sha256

DEFAULT_DATA_DIR = "benchmarks/data"


def data_dir_for(evaluation_root: Path) -> Path:
    return evaluation_root / DEFAULT_DATA_DIR


def benchmark_dir(evaluation_root: Path, name: str) -> Path:
    return data_dir_for(evaluation_root) / name


def prepare(
    name: str,
    evaluation_root: Path,
    limit: int | None = None,
    force: bool = False,
) -> ConversionReport:
    """원본을 확보하고 평가 형식으로 변환한다."""
    spec = registry.get(name)
    data_dir = data_dir_for(evaluation_root)
    out_dir = data_dir / name

    if spec.converter == "local":
        # 로컬 픽스처는 내려받을 것이 없다. 다른 변환기와 입력 형태를 맞추려고
        # 저장소 안의 경로를 그대로 채워 준다.
        raw = {
            "corpus": evaluation_root / "fixtures" / "mock_corpus.jsonl",
            **{
                suite: evaluation_root / "datasets" / suite / "sample.jsonl"
                for suite in ("retrieval", "generation", "extraction")
            },
        }
    else:
        raw = ensure_raw_files(spec, data_dir, force=force) if spec.files else {}

    converter = CONVERTERS.get(spec.converter)
    if converter is None:
        raise ValueError(f"변환기를 찾을 수 없습니다: {spec.converter}")

    effective_limit = spec.default_limit if limit is None else limit
    report = converter(raw, out_dir, effective_limit)

    write_manifest(
        out_dir,
        report,
        {
            "spec": spec.model_dump(),
            "limit": effective_limit,
            "raw_sha256": {
                key: file_sha256(path)
                for key, path in sorted(raw.items())
                if path.exists()
            },
            "outputs": sorted(
                path.name for path in out_dir.glob("*.jsonl")
            ),
        },
    )
    return report


def is_prepared(evaluation_root: Path, name: str, suite: str) -> bool:
    return (benchmark_dir(evaluation_root, name) / f"{suite}.jsonl").exists()


def build_config(
    name: str,
    suite: str,
    evaluation_root: Path,
    target: str = "baseline",
    target_options: dict[str, Any] | None = None,
    limit: int | None = None,
    concurrency: int = 4,
) -> EvalConfig:
    """준비된 벤치마크로 실행 설정을 만든다.

    설정 파일을 따로 두지 않고 코드에서 만드는 이유는, 벤치마크마다
    경로만 다르고 나머지는 같기 때문이다. YAML을 벤치마크 수만큼
    복제하면 게이트 기준이 서로 어긋나기 쉽다.
    """
    spec = registry.get(name)
    directory = benchmark_dir(evaluation_root, name)
    dataset = directory / f"{suite}.jsonl"
    if not dataset.exists():
        raise FileNotFoundError(
            f"{name}/{suite} 데이터셋이 없습니다. 먼저 실행하세요: "
            f"linkpaper-eval bench prepare --name {name}"
        )

    relative = f"{DEFAULT_DATA_DIR}/{name}"
    corpus = f"{relative}/corpus.jsonl"

    presets: dict[str, dict[str, Any]] = {
        "baseline": {
            "type": "lexical_baseline",
            "options": {"corpus": corpus, "top_k": 10, "citation_count": 3},
        },
        "http": {
            "type": "http_backend",
            "options": {"base_url": "http://localhost:8000", "api_prefix": "/api/v1"},
        },
        "hybrid": {
            "type": "graphrag_hybrid",
            "options": {"top_k": 10, "citation_count": 3},
        },
        "vector": {
            "type": "graphrag_hybrid",
            "options": {"top_k": 10, "citation_count": 3, "graph_expansion": False},
        },
    }
    if target not in presets:
        raise ValueError(
            f"알 수 없는 타깃: {target} (사용 가능: {', '.join(sorted(presets))})"
        )

    spec_dict = dict(presets[target])
    options = dict(spec_dict["options"])
    options.update(target_options or {})
    spec_dict["options"] = options

    return EvalConfig(
        suite=suite,
        dataset=f"{relative}/{suite}.jsonl",
        target=spec_dict,
        targets=presets,
        judge={"type": "heuristic"},
        k_values=[1, 3, 5, 10],
        gates={},
        run=RunOptions(
            concurrency=concurrency, output_dir="runs", limit=limit
        ),
        baseline=f"baselines/bench-{name}-{suite}.json",
        base_dir=evaluation_root,
    )


def describe(name: str) -> str:
    spec = registry.get(name)
    lines = [
        f"{spec.title} ({spec.name})",
        "",
        spec.description,
        "",
        f"라이선스: {spec.license}",
        f"재배포 가능: {'예' if spec.redistributable else '아니오'}",
        f"스위트: {', '.join(spec.suites)}",
    ]
    if spec.homepage:
        lines.append(f"홈페이지: {spec.homepage}")
    if spec.paper:
        lines.append(f"논문: {spec.paper}")
    if spec.notes:
        lines += ["", spec.notes]
    return "\n".join(lines)
