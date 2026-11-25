"""Check that pilot relevance labels refer to the actual checked-in corpus."""

import json
from pathlib import Path


def test_pilot_questions_are_traceable_to_source_passages():
    corpus_root = Path(__file__).resolve().parents[2] / "docs" / "demos" / "onssa"
    cases = json.loads((corpus_root / "evaluation-pilote.json").read_text(encoding="utf-8"))[
        "cases"
    ]
    assert len(cases) >= 5
    assert len({case["id"] for case in cases}) == len(cases)
    assert any(not case["answerable"] for case in cases)
    for case in cases:
        if not case["answerable"]:
            assert case["expected_document"] is None
            assert case["expected_passage"] is None
            continue
        content = (corpus_root / "corpus" / case["expected_document"]).read_text(encoding="utf-8")
        assert case["expected_passage"] in content, case["id"]
