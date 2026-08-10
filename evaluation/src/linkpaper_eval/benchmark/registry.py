"""외부 벤치마크 데이터셋 레지스트리.

각 항목은 "어디서 받아서, 어떤 변환기로, 어떤 스위트에 쓸 수 있는가"를
선언한다. 다운로드와 변환을 분리했기 때문에, 자동 다운로드가 막혀도
사용자가 원본 파일을 `raw/` 아래에 직접 넣으면 변환부터 이어서 진행된다.
데이터셋 배포처가 접근 정책을 바꿔도 파이프라인 전체가 멈추지 않는다.

라이선스는 데이터셋마다 다르다. GraphRAG-Bench처럼 재배포가 금지된
데이터는 저장소에 커밋하지 않고 실행 시점에만 내려받는다. 그래서
`benchmarks/data/`는 gitignore 대상이다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FileSpec(BaseModel):
    """원본 파일 하나를 어떻게 확보하는가."""

    model_config = ConfigDict(extra="forbid")

    key: str
    """`raw/<key>.jsonl`로 저장되는 이름. 변환기가 이 이름으로 찾는다."""

    hf_config: str | None = None
    """`datasets.load_dataset(repo, config)`에 쓰는 config 이름."""

    hf_split: str = "train"

    hf_filename: str | None = None
    """`huggingface_hub.hf_hub_download`로 직접 받을 때의 저장소 내 경로."""

    url: str | None = None
    """HTTP로 직접 받을 때의 주소."""

    required: bool = True

    manual_hint: str = ""
    """자동 다운로드가 실패했을 때 사용자에게 보여 줄 안내."""


class BenchmarkSpec(BaseModel):
    """벤치마크 데이터셋 하나."""

    model_config = ConfigDict(extra="forbid")

    name: str
    title: str
    description: str
    homepage: str = ""
    paper: str = ""
    license: str = "unknown"
    redistributable: bool = False
    hf_repo: str | None = None
    files: list[FileSpec] = Field(default_factory=list)
    converter: str = ""
    suites: list[str] = Field(default_factory=lambda: ["retrieval", "generation"])
    default_limit: int | None = 200
    notes: str = ""

    def file(self, key: str) -> FileSpec | None:
        for spec in self.files:
            if spec.key == key:
                return spec
        return None


REGISTRY: dict[str, BenchmarkSpec] = {
    # ------------------------------------------------------------------
    "qasper": BenchmarkSpec(
        name="qasper",
        title="QASPER (Question Answering over Scientific Papers)",
        description=(
            "NLP 논문 1,585편에 대한 정보 탐색형 질문 5,049개. 질문마다 "
            "정답 문단(evidence)이 라벨링되어 있어 검색 지표를 그대로 잴 수 "
            "있다. arXiv 논문 본문을 섹션·문단 단위로 제공하므로 LinkPaper의 "
            "청크 구조와 가장 가깝다."
        ),
        homepage="https://huggingface.co/datasets/allenai/qasper",
        paper="https://arxiv.org/abs/2105.03011",
        license="cc-by-4.0",
        redistributable=True,
        hf_repo="allenai/qasper",
        files=[
            FileSpec(
                key="qasper",
                hf_config="qasper",
                hf_split="validation",
                manual_hint=(
                    "https://huggingface.co/datasets/allenai/qasper 에서 "
                    "validation split을 JSONL로 내보내 raw/qasper.jsonl 로 저장"
                ),
            )
        ],
        converter="qasper",
        suites=["retrieval", "generation"],
        default_limit=300,
        notes=(
            "단일 논문 안에서 답이 나오므로 expected_scope는 전부 selected다. "
            "선택 논문 내부 검색 성능을 재는 데 쓰고, 그래프 확장이 필요한 "
            "global 질문은 multihop-rag나 자체 생성 데이터셋으로 보완한다."
        ),
    ),
    # ------------------------------------------------------------------
    "multihop-rag": BenchmarkSpec(
        name="multihop-rag",
        title="MultiHop-RAG",
        description=(
            "문서 2~4개에 근거가 흩어진 멀티홉 질의 2,556개와 뉴스 문서 "
            "코퍼스 609편. 여러 문서를 이어 붙여야 답이 나오는 질문이라 "
            "그래프 확장의 효과를 재기에 적합하다."
        ),
        homepage="https://huggingface.co/datasets/yixuantt/MultiHopRAG",
        paper="https://arxiv.org/abs/2401.15391",
        license="odc-by",
        redistributable=True,
        hf_repo="yixuantt/MultiHopRAG",
        files=[
            FileSpec(
                key="queries",
                hf_config="MultiHopRAG",
                hf_split="train",
                hf_filename="MultiHopRAG.json",
                manual_hint="MultiHopRAG.json을 raw/queries.jsonl 로 변환해 저장",
            ),
            FileSpec(
                key="corpus",
                hf_config="corpus",
                hf_split="train",
                hf_filename="corpus.json",
                manual_hint="corpus.json을 raw/corpus.jsonl 로 변환해 저장",
            ),
        ],
        converter="multihop_rag",
        suites=["retrieval", "generation"],
        default_limit=300,
        notes=(
            "논문이 아니라 뉴스 코퍼스다. 도메인은 다르지만 '여러 문서를 "
            "가로지르는 질문'이라는 성격이 LinkPaper의 global 질의와 같아서, "
            "라우팅과 그래프 확장의 회귀를 감지하는 용도로 쓴다. "
            "question_type이 null_query인 항목은 근거가 없는 질문이므로 "
            "unanswerable 태그가 붙는다."
        ),
    ),
    # ------------------------------------------------------------------
    "graphrag-bench": BenchmarkSpec(
        name="graphrag-bench",
        title="GraphRAG-Bench",
        description=(
            "GraphRAG 전용 벤치마크. 사실 검색부터 복합 추론까지 난이도가 "
            "올라가는 문항으로 구성되며, 그래프 구축·검색·생성 전 구간을 "
            "평가하도록 설계되었다."
        ),
        homepage="https://huggingface.co/datasets/GraphRAG-Bench/GraphRAG-Bench",
        paper="https://arxiv.org/abs/2506.02404",
        license="research-only (재배포 금지)",
        redistributable=False,
        hf_repo="GraphRAG-Bench/GraphRAG-Bench",
        files=[
            FileSpec(
                key="questions",
                hf_config="medical",
                hf_split="train",
                hf_filename="Datasets/Questions/medical_questions.json",
                manual_hint=(
                    "데이터셋 페이지의 Files 탭에서 Datasets/Questions/ 아래 "
                    "질문 JSON을 받아 raw/questions.jsonl 로 저장"
                ),
            ),
            FileSpec(
                key="corpus",
                hf_filename="Datasets/Corpus/medical.json",
                required=False,
                manual_hint=(
                    "코퍼스 파일 경로는 릴리스마다 다르다. Files 탭에서 확인한 "
                    "뒤 raw/corpus.jsonl 로 저장한다. 없으면 생성 스위트만 "
                    "만들어진다."
                ),
            ),
        ],
        converter="graphrag_bench",
        suites=["generation"],
        default_limit=200,
        notes=(
            "라이선스가 학술 연구 목적으로 제한되고 재배포가 금지되어 있다. "
            "원본 파일을 저장소에 커밋하지 말 것. 코퍼스 파일 경로가 릴리스마다 "
            "달라서 자동 다운로드가 실패할 수 있으며, 그때는 질문 파일만으로 "
            "생성 스위트를 만든다."
        ),
    ),
    # ------------------------------------------------------------------
    "linkpaper-local": BenchmarkSpec(
        name="linkpaper-local",
        title="LinkPaper 로컬 픽스처",
        description=(
            "저장소에 포함된 mock 코퍼스와 샘플 데이터셋을 벤치마크 형식으로 "
            "묶는다. 네트워크와 API 키 없이 전체 경로를 확인할 때 쓴다."
        ),
        license="MIT (저장소와 동일)",
        redistributable=True,
        converter="local",
        suites=["retrieval", "generation", "extraction"],
        default_limit=None,
        notes=(
            "실제 벤치마크가 아니라 배관 검증용이다. 이 데이터로 나온 점수를 "
            "시스템 품질 근거로 쓰지 않는다."
        ),
    ),
}


def get(name: str) -> BenchmarkSpec:
    if name not in REGISTRY:
        available = ", ".join(sorted(REGISTRY))
        raise KeyError(f"알 수 없는 벤치마크: {name} (사용 가능: {available})")
    return REGISTRY[name]


def names() -> list[str]:
    return sorted(REGISTRY)
