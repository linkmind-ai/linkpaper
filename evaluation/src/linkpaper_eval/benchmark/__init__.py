"""외부 벤치마크 데이터셋과 ragas 지표.

- `registry` — 어떤 벤치마크를 쓸 수 있는가
- `download` — 원본 확보 (실패 시 수동 설정 안내)
- `converters` — 외부 형식 → LinkPaper 평가 형식
- `prepare` — 준비 오케스트레이션과 실행 설정 생성
- `seed` — 코퍼스를 Qdrant·Neo4j에 적재
- `ragas_metrics` — 실행 결과 사후 채점
"""

from linkpaper_eval.benchmark import prepare, registry
from linkpaper_eval.benchmark.prepare import build_config, describe
from linkpaper_eval.benchmark.prepare import prepare as prepare_benchmark

# `prepare`는 서브모듈 이름이므로 함수는 `prepare_benchmark`로 노출한다.
# 같은 이름으로 재노출하면 서브모듈 접근이 함수에 덮어써진다.
__all__ = [
    "build_config",
    "describe",
    "prepare",
    "prepare_benchmark",
    "registry",
]
