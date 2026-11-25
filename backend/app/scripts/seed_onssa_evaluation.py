"""Load the reviewed-source ONSSA pilot questions without replacing user cases.

The pilot is exploratory: none of its labels is marked as human-reviewed.
Run inside the backend container with ``python -m app.scripts.seed_onssa_evaluation``;
add ``--run`` to also record an evaluation run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.qdrant import close_qdrant, init_qdrant
from app.core.redis import close_redis, init_redis
from app.core.tenant import TenantContext, TenantResolver
from app.models.enums import KBDocumentStatus
from app.models.kb import KBDocument
from app.models.rag_evaluation import RAGEvaluationCase
from app.services.rag.evaluation import RAGEvaluationService


def _document_title_candidates(root: Path, case: dict) -> set[str]:
    name = case["expected_document"]
    if not name or Path(name).name != name or not name.endswith(".md"):
        raise ValueError("Invalid pilot document name")
    content = (root / "corpus" / name).read_text(encoding="utf-8")
    if not case.get("expected_passage") or case["expected_passage"] not in content:
        raise ValueError(f"Expected passage not found in {name}")
    heading = content.splitlines()[0].removeprefix("# ").strip()
    return {Path(name).stem, heading}


async def seed(tenant: TenantContext, root: Path) -> int:
    pilot = json.loads((root / "evaluation-pilote.json").read_text(encoding="utf-8"))
    async with tenant.db_session() as db:
        docs = (
            (
                await db.execute(
                    select(KBDocument).where(
                        KBDocument.status == KBDocumentStatus.indexed,
                        KBDocument.active_index_version.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        existing = set((await db.execute(select(RAGEvaluationCase.query))).scalars().all())
        prepared = []
        for case in pilot["cases"]:
            if case["question"] in existing:
                continue
            expected_ids = []
            if case["answerable"]:
                candidates = _document_title_candidates(root, case)
                matches = [doc for doc in docs if doc.title in candidates]
                if len(matches) != 1:
                    raise ValueError(f"Expected exactly one indexed document for {case['id']}")
                expected_ids = [str(matches[0].id)]
            prepared.append(
                RAGEvaluationCase(
                    query=case["question"],
                    language="fr",
                    expected_document_ids=expected_ids,
                    expects_abstention=not case["answerable"],
                    is_active=True,
                    human_faithfulness=None,
                )
            )
        db.add_all(prepared)
        return len(prepared)


async def _main(run_evaluation: bool) -> None:
    await init_redis()
    await init_qdrant()
    try:
        tenant = await TenantResolver.from_slug("onssa")
        count = await seed(tenant, Path("/app/onssa-corpus"))
        print(f"Pilot cases added: {count}; human review remains pending.")
        if run_evaluation:
            run = await RAGEvaluationService().run(tenant, None)
            print(f"Evaluation cases: {run.case_count}; metrics: {json.dumps(run.metrics)}")
    finally:
        await close_qdrant()
        await close_redis()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="Also run the pilot evaluation")
    asyncio.run(_main(parser.parse_args().run))
