"""답변 품질 심판.

CI 기본값은 결정적 심판이다. LLM 심판은 점수에 분산이 있고 비용이 들며
API 키가 필요하므로, 기본 실행을 막지 않도록 명시적으로 선택할 때만 쓴다.
LLM 심판 점수는 `judge.` 접두사로 분리해서 결정적 지표와 섞이지 않게 한다.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod

from linkpaper_eval.metrics.generation import lexical_groundedness, tokenize
from linkpaper_eval.schemas import EvalCase, TargetResponse

_SYSTEM_PROMPT = (
    "You grade answers from a research-paper QA system. "
    "Score strictly and return JSON only."
)

_USER_TEMPLATE = """질문:
{question}

근거 컨텍스트:
{evidence}

시스템 답변:
{answer}

다음 세 항목을 0.0~1.0 사이 실수로 채점하고 JSON만 출력하세요.
- faithfulness: 답변의 모든 주장이 근거 컨텍스트로 뒷받침되는가
- relevance: 답변이 질문에 실제로 답하는가
- completeness: 질문에 답하는 데 필요한 핵심 요소를 빠짐없이 담았는가

출력 형식: {{"faithfulness": 0.0, "relevance": 0.0, "completeness": 0.0}}
"""


class Judge(ABC):
    name: str = "judge"

    @abstractmethod
    def score(self, case: EvalCase, response: TargetResponse) -> dict[str, float]:
        """`judge.` 접두사가 붙은 지표를 반환한다."""


class HeuristicJudge(Judge):
    """LLM 없이 동작하는 결정적 심판.

    근거 겹침과 질문-답변 어휘 겹침만 본다. 정밀하지는 않지만 재현 가능하고
    비용이 0이라 CI 회귀 감지에 적합하다.
    """

    name = "heuristic"

    def score(self, case: EvalCase, response: TargetResponse) -> dict[str, float]:
        if not response.answer:
            return {
                "judge.faithfulness": 0.0,
                "judge.relevance": 0.0,
            }

        faithfulness = lexical_groundedness(
            response.answer, response.evidence_text()
        )
        question_tokens = set(tokenize(case.question))
        answer_tokens = set(tokenize(response.answer))
        if question_tokens:
            relevance = len(question_tokens & answer_tokens) / len(question_tokens)
        else:
            relevance = float("nan")

        return {
            "judge.faithfulness": faithfulness,
            "judge.relevance": min(relevance * 1.5, 1.0),
        }


class OpenAIJudge(Judge):
    """OpenAI 호환 엔드포인트를 사용하는 LLM 심판."""

    name = "openai"

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        api_key_env: str = "OPENAI_API_KEY",
        temperature: float = 0.0,
        timeout_s: float = 60.0,
        max_evidence_chars: int = 6000,
    ) -> None:
        import httpx

        api_key = os.environ.get(api_key_env, "")
        if not api_key:
            raise RuntimeError(
                f"{api_key_env} is not set. "
                "Use `judge.type: heuristic` for offline runs."
            )
        self.model = model
        self.temperature = temperature
        self.max_evidence_chars = max_evidence_chars
        self.client = httpx.Client(
            base_url=base_url,
            timeout=timeout_s,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def score(self, case: EvalCase, response: TargetResponse) -> dict[str, float]:
        if not response.answer:
            return {"judge.faithfulness": 0.0, "judge.relevance": 0.0}

        prompt = _USER_TEMPLATE.format(
            question=case.question,
            evidence=response.evidence_text()[: self.max_evidence_chars],
            answer=response.answer,
        )
        try:
            api_response = self.client.post(
                "/chat/completions",
                json={
                    "model": self.model,
                    "temperature": self.temperature,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            api_response.raise_for_status()
            content = api_response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except Exception:  # noqa: BLE001 - 심판 실패가 실행 전체를 막으면 안 된다
            return {
                "judge.faithfulness": float("nan"),
                "judge.relevance": float("nan"),
                "judge.error": 1.0,
            }

        return {
            f"judge.{key}": float(value)
            for key, value in parsed.items()
            if isinstance(value, (int, float))
        }

    def close(self) -> None:
        self.client.close()


def build_judge(spec: dict) -> Judge:
    judge_type = (spec or {}).get("type", "heuristic")
    options = {
        key: value for key, value in (spec or {}).items() if key != "type"
    }

    if judge_type in {"heuristic", "none", "offline"}:
        return HeuristicJudge()
    if judge_type in {"openai", "llm"}:
        return OpenAIJudge(**options)
    raise ValueError(f"Unknown judge type: {judge_type}")
