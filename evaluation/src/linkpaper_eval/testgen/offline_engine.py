"""LLM 없이 동작하는 결정적 평가셋 생성기.

목적은 분명하다. **파이프라인 검증용이지 품질 평가용이 아니다.**

질문 문장을 청크의 특징 단어로 조립하므로, 어휘 기반 검색기(BM25)에
유리하게 기운다. 이 데이터셋에서 나온 Recall을 시스템 성능 근거로 쓰면
안 된다. 대신 다음을 확인할 수 있고, 이것이 이 생성기의 존재 이유다.

- 그래프·벡터 인덱스에서 후보 청크와 간선이 제대로 나오는가
- 생성한 정답 청크 ID가 코퍼스에 실제로 존재하는가
- 만들어진 JSONL을 기존 러너가 그대로 읽는가

API 키와 네트워크 없이 CI에서 매번 돌릴 수 있으므로, 생성 경로가 조용히
깨지는 것을 막는다. 사람이 읽을 만한 질문이 필요하면 `--engine ragas`를
쓴다.

편향을 조금이라도 줄이려고 가장 특징적인 단어 하나는 질문에서 뺀다.
정답 청크에만 있는 희귀어를 그대로 넣으면 검색이 사실상 정답 ID를
받아 보는 것과 같아지기 때문이다.
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from typing import Any

from linkpaper_eval.metrics.generation import tokenize
from linkpaper_eval.stores.records import ChunkRecord
from linkpaper_eval.testgen.graph import ChunkGraph, ChunkLink

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# `metrics.generation.tokenize`의 불용어는 지표 계산용이라 최소한만 담겨
# 있다. 질문 문장을 만들 때는 "cannot", "between" 같은 기능어가 주제어로
# 뽑히면 질문이 무의미해지므로 여기서만 쓰는 목록을 따로 둔다. 지표 쪽
# 토큰화를 바꾸면 기존 점수와 비교가 끊기기 때문에 건드리지 않는다.
_FUNCTION_WORDS = frozenset(
    """
    about above after again against all also although among another any because
    been before being below between both cannot could does doing done during
    each either else even every from further had has have having here how
    however into itself just less like made make many more most much must
    neither never not only other others our over rather same should since
    some such than their them then there these they thing things those though
    through thus under until upon used using very well were what when where
    which while whose will with within without would your
    """.split()
)

_SINGLE_HOP_TEMPLATES = (
    "What does this paper say about {terms}?",
    "In the {section} section, how are {terms} described?",
    "According to this paper, what role do {terms} play?",
)

_MULTI_HOP_TEMPLATES = {
    "cites": (
        "How does the work on {left} relate to {right} in the cited paper?",
        "What does the cited work contribute regarding {right}, "
        "and how does the citing paper build on it for {left}?",
    ),
    "shared_entity": (
        "How do these papers each describe {left} in relation to {right}?",
        "What different perspectives do the papers take on {left} and {right}?",
    ),
    "vector": (
        "How is {left} handled differently across these related papers "
        "compared with {right}?",
        "Comparing the two papers, what is stated about {left} and {right}?",
    ),
}


def _term_scores(
    chunks: list[ChunkRecord],
) -> tuple[dict[str, float], Counter[str], list[list[str]]]:
    """코퍼스 전체 IDF, 문서빈도, 청크별 토큰 목록을 계산한다."""
    token_lists = [tokenize(chunk.text) for chunk in chunks]
    document_frequency: Counter[str] = Counter()
    for tokens in token_lists:
        document_frequency.update(set(tokens))

    total = max(len(chunks), 1)
    idf = {
        term: math.log(1 + total / (freq + 0.5))
        for term, freq in document_frequency.items()
    }
    return idf, document_frequency, token_lists


def _key_terms(
    tokens: list[str],
    idf: dict[str, float],
    document_frequency: Counter[str],
    count: int = 2,
    skip_top: int = 1,
    min_length: int = 5,
) -> list[str]:
    """청크를 대표하는 주제어를 고른다.

    두 가지를 조정한다.

    - 기능어와 짧은 단어를 후보에서 뺀다. TF-IDF만 쓰면 한 청크에만
      등장한 "cannot" 같은 단어가 최고점을 받아 질문이 무의미해진다.
    - 코퍼스에서 두 번 이상 등장한 단어를 먼저 고른다. 한 번만 나온 단어는
      주제어라기보다 우연한 표현인 경우가 많다.

    `skip_top`은 가장 특징적인 단어 하나를 건너뛴다. 정답 청크에만 있는
    희귀어를 질문에 그대로 넣으면 검색이 사실상 정답 ID를 받아 보는 것과
    같아지기 때문이다.
    """

    def rank(candidates: Counter[str]) -> list[str]:
        return [
            term
            for term, _ in sorted(
                candidates.items(),
                key=lambda item: (-(item[1] * idf.get(item[0], 1.0)), item[0]),
            )
        ]

    content = Counter(
        token
        for token in tokens
        if len(token) >= min_length and token not in _FUNCTION_WORDS
    )
    repeated = Counter(
        {
            term: value
            for term, value in content.items()
            if document_frequency.get(term, 0) >= 2
        }
    )

    for candidates in (repeated, content, Counter(tokens)):
        if not candidates:
            continue
        ordered = rank(candidates)
        selected = ordered[skip_top : skip_top + count]
        if len(selected) >= min(count, len(ordered)):
            return selected or ordered[:count]
    return []


def _join(terms: list[str]) -> str:
    if not terms:
        return "this topic"
    if len(terms) == 1:
        return terms[0]
    return f"{', '.join(terms[:-1])} and {terms[-1]}"


def _extractive_answer(chunk: ChunkRecord, sentences: int = 2) -> str:
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(chunk.text) if part.strip()]
    return " ".join(parts[:sentences])


def generate_offline(
    chunk_graph: ChunkGraph,
    size: int = 20,
    single_hop_ratio: float = 0.5,
    seed: int = 20260804,
    include_reference: bool = True,
) -> list[dict[str, Any]]:
    """`ChunkGraph`에서 `EvalCase` 딕셔너리 목록을 만든다."""
    chunks = list(chunk_graph.chunks)
    if not chunks:
        return []

    idf, document_frequency, token_lists = _term_scores(chunks)
    tokens_by_id = {
        chunk.chunk_id: tokens for chunk, tokens in zip(chunks, token_lists)
    }
    lookup = chunk_graph.index()
    rng = random.Random(seed)

    multi_hop_target = int(round(size * (1 - single_hop_ratio)))
    cases: list[dict[str, Any]] = []

    # --- 멀티홉: 실제 그래프/벡터 간선으로 연결된 서로 다른 논문의 청크 쌍
    cross_links: list[ChunkLink] = sorted(
        chunk_graph.cross_paper_links(),
        key=lambda link: (-(link.score or 0.0), link.source, link.target),
    )
    used_pairs: set[tuple[str, str]] = set()
    for link in cross_links:
        if len([c for c in cases if "multi-hop" in c["tags"]]) >= multi_hop_target:
            break
        pair = tuple(sorted((link.source, link.target)))
        if pair in used_pairs:
            continue
        source = lookup.get(link.source)
        target = lookup.get(link.target)
        if source is None or target is None:
            continue
        used_pairs.add(pair)

        left = _key_terms(
            tokens_by_id.get(source.chunk_id, []), idf, document_frequency, count=2
        )
        right = _key_terms(
            tokens_by_id.get(target.chunk_id, []), idf, document_frequency, count=2
        )
        templates = _MULTI_HOP_TEMPLATES.get(
            link.type, _MULTI_HOP_TEMPLATES["vector"]
        )
        question = rng.choice(templates).format(left=_join(left), right=_join(right))

        case: dict[str, Any] = {
            "case_id": f"gen-mh-{len(cases):04d}",
            "question": question,
            "paper_id": source.paper_id,
            "gold_chunk_ids": [source.chunk_id, target.chunk_id],
            "gold_paper_ids": sorted({source.paper_id, target.paper_id}),
            "grades": {source.chunk_id: 3, target.chunk_id: 3},
            "expected_scope": "global",
            "tags": [
                "generated",
                "offline-template",
                "multi-hop",
                "global",
                f"link:{link.type}",
            ],
            "notes": (
                f"{link.type} 간선으로 연결된 청크 쌍에서 생성. "
                "템플릿 기반이므로 어휘 검색에 유리하다."
            ),
        }
        if include_reference:
            case["gold_answer"] = " ".join(
                [_extractive_answer(source, 1), _extractive_answer(target, 1)]
            ).strip()
            case["tags"].append("extractive-reference")
        cases.append(case)

    # --- 싱글홉: 하나의 청크만으로 답할 수 있는 질문
    remaining = size - len(cases)
    if remaining > 0:
        # 논문마다 고르게 뽑는다. 청크가 많은 논문이 데이터셋을 독점하면
        # 태그별 집계가 한 편의 특성만 반영하게 된다.
        by_paper: dict[str, list[ChunkRecord]] = {}
        for chunk in chunks:
            by_paper.setdefault(chunk.paper_id, []).append(chunk)
        for paper_chunks in by_paper.values():
            paper_chunks.sort(key=lambda chunk: chunk.chunk_id)

        ordered: list[ChunkRecord] = []
        position = 0
        while len(ordered) < remaining:
            added = False
            for paper_chunks in by_paper.values():
                if position < len(paper_chunks):
                    ordered.append(paper_chunks[position])
                    added = True
                    if len(ordered) >= remaining:
                        break
            if not added:
                break
            position += 1

        for chunk in ordered:
            terms = _key_terms(
                tokens_by_id.get(chunk.chunk_id, []), idf, document_frequency, count=2
            )
            template = rng.choice(_SINGLE_HOP_TEMPLATES)
            question = template.format(
                terms=_join(terms), section=chunk.section or "main"
            )
            case = {
                "case_id": f"gen-sh-{len(cases):04d}",
                "question": question,
                "paper_id": chunk.paper_id,
                "gold_chunk_ids": [chunk.chunk_id],
                "gold_paper_ids": [chunk.paper_id],
                "grades": {chunk.chunk_id: 3},
                "expected_scope": "selected",
                "tags": ["generated", "offline-template", "single-hop", "local"],
                "notes": "단일 청크에서 생성. 템플릿 기반이므로 품질 평가용이 아니다.",
            }
            if include_reference:
                case["gold_answer"] = _extractive_answer(chunk)
                case["tags"].append("extractive-reference")
            cases.append(case)

    return cases[:size]
