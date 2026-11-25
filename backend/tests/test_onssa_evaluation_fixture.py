"""Check that pilot relevance labels refer to the actual checked-in corpus."""

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


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


def test_candidate_questions_are_traceable_and_not_marked_as_reviewed():
    root = Path(__file__).resolve().parents[2] / "docs" / "demos" / "onssa"
    cases = json.loads((root / "evaluation-candidats.json").read_text(encoding="utf-8"))["cases"]
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    urls = {source["slug"]: source["url"] for source in manifest["sources"]}
    assert len(cases) == 50
    assert len({case["id"] for case in cases}) == len(cases)
    assert len({case["question"] for case in cases}) == len(cases)
    assert {case["language"] for case in cases} == {"fr", "ar"}
    assert sum(not case["answerable"] for case in cases) == 5
    assert all(case["human_reviewed"] is False for case in cases)
    for case in cases:
        if not case["answerable"]:
            assert case["expected_document"] is None
            assert case["expected_passage"] is None
            assert case["source_url"] is None
            continue
        name = case["expected_document"]
        assert Path(name).name == name
        assert case["expected_passage"] in (root / "corpus" / name).read_text(encoding="utf-8")
        assert case["source_url"] == urls[Path(name).stem]


@pytest.mark.asyncio
async def test_seed_adds_only_missing_case_and_keeps_human_review_unset():
    from app.scripts.seed_onssa_evaluation import seed

    root = Path(__file__).resolve().parents[2] / "docs" / "demos" / "onssa"
    cases = json.loads((root / "evaluation-pilote.json").read_text(encoding="utf-8"))["cases"]
    new_case = next(case for case in cases if case["id"] == "phyto-loi-76-17")
    document = MagicMock(id=uuid.uuid4(), title="ONSSA — Contrôle phytosanitaire")
    docs_result = MagicMock()
    docs_result.scalars.return_value.all.return_value = [document]
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = [
        case["question"] for case in cases if case is not new_case
    ]
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.side_effect = [docs_result, existing_result]
    session.add_all = MagicMock()
    tenant = MagicMock()
    tenant.db_session.return_value = session

    assert await seed(tenant, root) == 1
    added = session.add_all.call_args.args[0]
    assert len(added) == 1
    assert added[0].expected_document_ids == [str(document.id)]
    assert added[0].human_faithfulness is None
