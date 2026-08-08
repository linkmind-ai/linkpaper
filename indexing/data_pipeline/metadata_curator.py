"""초기 메타데이터와 참고문헌을 합쳐 최종 메타데이터를 만든다.

Hugging Face Papers API는 인용 목록을 주지 않는다. 그래서 참고문헌 섹션 원문
에서 식별 가능한 arXiv ID만 뽑아 `references`에 채운다. arXiv ID가 없는 인용
(학회 논문, 도서 등)은 이 단계에서 다루지 않는다. 문자열 매칭으로 논문을
추정하면 인용 그래프에 잘못된 간선이 생기기 때문이다.

추출한 ID는 `paper_id`와 같은 형식(버전 접미사 없는 arXiv base ID)으로
정규화한다. Graph Builder가 `references`의 값을 그대로 `paper_id`와 맞춰
인용 관계를 만들 수 있게 하기 위해서다.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from data_pipeline.models import PaperMarkdown, PaperMetadata

logger = logging.getLogger(__name__)

# 2007년 이후 형식: 2401.12345 / 2401.12345v2
_NEW_ID = r"\d{4}\.\d{4,5}"
# 구형식: hep-th/9901001, cs.CL/0012345
_OLD_ID = r"[a-z-]+(?:\.[A-Za-z]{2})?/\d{7}"

_PATTERNS = (
    # arXiv:2401.12345 / arXiv: 2401.12345 / "arXiv preprint arXiv:2401.12345"
    re.compile(rf"arxiv\s*:\s*({_NEW_ID}|{_OLD_ID})", re.IGNORECASE),
    # https://arxiv.org/abs/2401.12345, /pdf/, /html/
    re.compile(
        rf"arxiv\.org/(?:abs|pdf|html)/({_NEW_ID}|{_OLD_ID})",
        re.IGNORECASE,
    ),
)
_VERSION_SUFFIX_RE = re.compile(r"v\d+$", re.IGNORECASE)


class MetadataCurator:
    """Client의 초기 메타데이터 + Chunker의 참고문헌 원문 → 최종 메타데이터."""

    def curate(
        self,
        metadata: PaperMetadata,
        references_text: str,
        markdown: PaperMarkdown,
    ) -> PaperMetadata:
        references = extract_arxiv_ids(
            references_text,
            exclude=(metadata.paper_id, metadata.arxiv_id),
        )
        logger.debug(
            "메타데이터 큐레이션 paper_id=%s references=%d",
            metadata.paper_id,
            len(references),
        )
        return metadata.model_copy(
            update={
                "references": references,
                "content_hash": markdown.content_hash,
                "source_version": markdown.source,
            }
        )


def extract_arxiv_ids(
    text: str, exclude: Iterable[str | None] = ()
) -> list[str]:
    """참고문헌 원문에서 arXiv ID를 뽑는다.

    같은 인용이 본문 표기와 링크로 두 번 나오는 일이 흔하므로 중복을 제거하고,
    재실행 결과가 흔들리지 않도록 정렬해서 돌려준다.
    """
    if not text:
        return []

    excluded = {_normalize(value) for value in exclude if value}
    found: set[str] = set()
    for pattern in _PATTERNS:
        for match in pattern.finditer(text):
            arxiv_id = _normalize(match.group(1))
            if arxiv_id and arxiv_id not in excluded:
                found.add(arxiv_id)
    return sorted(found)


def _normalize(arxiv_id: str) -> str:
    """버전 접미사를 떼고 소문자로 통일한다. 2401.12345v2 -> 2401.12345"""
    return _VERSION_SUFFIX_RE.sub("", arxiv_id.strip().lower())
