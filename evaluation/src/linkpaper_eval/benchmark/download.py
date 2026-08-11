"""벤치마크 원본 데이터 확보.

세 가지 경로를 순서대로 시도하고, 어느 하나라도 성공하면 원본을
`raw/<key>.jsonl`로 정규화해 저장한다.

1. `datasets.load_dataset` — config/split이 정의된 데이터셋
2. `huggingface_hub.hf_hub_download` — 저장소 안 특정 파일
3. 일반 HTTP GET — 허브 밖에 있는 파일

모두 실패하면 예외에 "어떤 파일을 어디에 두면 되는지"를 담아서 던진다.
자동 다운로드 실패가 파이프라인의 끝이 되어서는 안 되기 때문이다. 원본을
직접 넣어 두면 `prepare`는 다운로드를 건너뛰고 변환부터 이어서 한다.

이미 받아 둔 파일이 있으면 다시 받지 않는다. 강제로 다시 받으려면
`force=True`를 쓴다.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from linkpaper_eval.benchmark.registry import BenchmarkSpec, FileSpec


class BenchmarkDownloadError(RuntimeError):
    """원본 확보 실패. 메시지에 수동 설정 방법을 담는다."""


def raw_dir(data_dir: Path, name: str) -> Path:
    return data_dir / name / "raw"


def raw_path(data_dir: Path, name: str, key: str) -> Path:
    return raw_dir(data_dir, name) / f"{key}.jsonl"


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            count += 1
    return count


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _rows_from_json_file(path: Path) -> list[dict[str, Any]]:
    """JSON 배열 파일과 JSONL 파일을 모두 리스트로 읽는다.

    허브에서 받은 파일은 `.json`이지만 내용이 JSON 배열인 경우가 많고,
    프로젝트에 따라 JSONL인 경우도 있어서 둘 다 처리한다.
    """
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text[0] == "[":
        payload = json.loads(text)
        return [row for row in payload if isinstance(row, dict)]
    if text[0] == "{":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            # {"data": [...]} 형태를 흔히 쓴다.
            for key in ("data", "rows", "questions", "examples"):
                if isinstance(payload.get(key), list):
                    return [row for row in payload[key] if isinstance(row, dict)]
            return [payload]

    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
    return rows


def _try_datasets(spec: BenchmarkSpec, file_spec: FileSpec) -> list[dict[str, Any]]:
    if not spec.hf_repo or not file_spec.hf_config:
        return []
    try:
        from datasets import load_dataset
    except ImportError:
        return []

    dataset = load_dataset(
        spec.hf_repo, file_spec.hf_config, split=file_spec.hf_split
    )
    return [dict(row) for row in dataset]


def _try_hub_file(spec: BenchmarkSpec, file_spec: FileSpec) -> list[dict[str, Any]]:
    if not spec.hf_repo or not file_spec.hf_filename:
        return []
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        return []

    local = hf_hub_download(
        repo_id=spec.hf_repo,
        filename=file_spec.hf_filename,
        repo_type="dataset",
    )
    return _rows_from_json_file(Path(local))


def _try_url(file_spec: FileSpec) -> list[dict[str, Any]]:
    if not file_spec.url:
        return []
    import httpx

    response = httpx.get(file_spec.url, timeout=120.0, follow_redirects=True)
    response.raise_for_status()

    target = Path(file_spec.url).name
    suffix = Path(target).suffix.lower()
    if suffix in {".json", ".jsonl"}:
        temp = Path(target)
        temp.write_text(response.text, encoding="utf-8")
        try:
            return _rows_from_json_file(temp)
        finally:
            temp.unlink(missing_ok=True)
    raise BenchmarkDownloadError(f"지원하지 않는 파일 형식입니다: {file_spec.url}")


def manual_instructions(spec: BenchmarkSpec, file_spec: FileSpec, target: Path) -> str:
    lines = [
        f"'{spec.name}' 원본을 자동으로 받지 못했습니다.",
        "",
        "수동 설정 방법:",
        f"  1. {spec.homepage or spec.hf_repo or '데이터셋 배포처'} 에서 원본을 받습니다.",
    ]
    if file_spec.hf_filename:
        lines.append(f"     저장소 내 경로: {file_spec.hf_filename}")
    if file_spec.manual_hint:
        lines.append(f"     안내: {file_spec.manual_hint}")
    lines += [
        f"  2. JSON 배열 또는 JSONL로 다음 경로에 저장합니다: {target}",
        "  3. 같은 prepare 명령을 다시 실행하면 다운로드를 건너뛰고 변환합니다.",
        "",
        "자동 다운로드에는 추가 의존성이 필요합니다: pip install -e '.[bench]'",
    ]
    return "\n".join(lines)


def ensure_raw_files(
    spec: BenchmarkSpec,
    data_dir: Path,
    force: bool = False,
) -> dict[str, Path]:
    """원본 파일을 확보하고 `{key: 경로}`를 돌려준다."""
    resolved: dict[str, Path] = {}

    for file_spec in spec.files:
        target = raw_path(data_dir, spec.name, file_spec.key)

        if target.exists() and not force:
            resolved[file_spec.key] = target
            continue

        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        for attempt in (_try_datasets, _try_hub_file):
            try:
                rows = attempt(spec, file_spec)
            except Exception as exc:  # noqa: BLE001 - 다음 경로를 시도한다
                errors.append(f"{attempt.__name__}: {type(exc).__name__}: {exc}")
                rows = []
            if rows:
                break

        if not rows and file_spec.url:
            try:
                rows = _try_url(file_spec)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"_try_url: {type(exc).__name__}: {exc}")

        if not rows:
            if not file_spec.required:
                continue
            message = manual_instructions(spec, file_spec, target)
            if errors:
                message += "\n\n시도 기록:\n  - " + "\n  - ".join(errors)
            raise BenchmarkDownloadError(message)

        write_jsonl(target, rows)
        resolved[file_spec.key] = target

    return resolved
