from __future__ import annotations

import json

from indexing_common.input import load_processed_papers


def test_load_processed_papers_accepts_single_object_and_array(tmp_path) -> None:
    payload = {
        "metadata": {
            "paper_id": "1706.03762",
            "title": "Attention Is All You Need",
            "content_hash": "paper-hash",
            "source_version": "hf-markdown",
        },
        "chunks": [],
    }
    single = tmp_path / "paper.json"
    batch = tmp_path / "base.json"
    single.write_text(json.dumps(payload), encoding="utf-8")
    batch.write_text(json.dumps([payload]), encoding="utf-8")

    assert len(load_processed_papers(single)) == 1
    assert len(load_processed_papers(batch)) == 1
