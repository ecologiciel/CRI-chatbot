"""Version lifecycle against disposable PostgreSQL and an in-memory Qdrant."""

import asyncio
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.tenant import TenantContext
from app.models.enums import KBDocumentStatus
from app.models.kb import KBChunk, KBDocument
from app.services.rag.ingestion import IngestionService
from app.services.rag.retrieval import RetrievalService


@pytest.mark.asyncio
async def test_reindex_failure_preserves_published_search():
    dsn = os.environ.get("RAG_PIPELINE_TEST_DSN")
    if not dsn:
        pytest.skip("Set RAG_PIPELINE_TEST_DSN to a fresh disposable PostgreSQL database")
    engine = create_async_engine(dsn)
    qdrant = AsyncQdrantClient(":memory:")
    try:
        async with engine.begin() as conn:
            assert (await conn.execute(text("SELECT current_database()"))).scalar_one() in {
                "rag_pipeline_test",
                "rag_pipeline_test_2",
                "rag_pipeline_test_3",
                "rag_pipeline_test_4",
                "rag_pipeline_test_5",
            }
            assert (
                await conn.execute(text("SELECT to_regnamespace('tenant_onssa') IS NULL"))
            ).scalar_one()
            await conn.execute(text("CREATE SCHEMA tenant_onssa"))
            await conn.execute(text("SET search_path TO tenant_onssa, public"))
            await conn.run_sync(lambda c: KBDocument.__table__.create(c, checkfirst=True))
            await conn.run_sync(lambda c: KBChunk.__table__.create(c, checkfirst=True))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        tenant = TenantContext(
            id=uuid.uuid4(), slug="onssa", name="ONSSA", status="active", whatsapp_config=None
        )
        document_id = uuid.uuid4()
        with patch("app.core.tenant.get_session_factory", return_value=factory):
            async with tenant.db_session() as session:
                session.add(
                    KBDocument(
                        id=document_id,
                        title="Guide",
                        language="fr",
                        status=KBDocumentStatus.pending,
                        source_authority="ONSSA",
                        source_reference="Guide",
                        source_version="v1",
                        published_at=date.today(),
                        validated_at=datetime.now(UTC),
                        validated_by=uuid.uuid4(),
                    )
                )
            await qdrant.create_collection(
                "kb_onssa",
                vectors_config=models.VectorParams(size=768, distance=models.Distance.COSINE),
            )
            embedding = AsyncMock()
            embedding.embed_batch.return_value = [[0.1] * 768]
            embedding.embed_single.return_value = [0.1] * 768
            with (
                patch("app.services.rag.ingestion.get_qdrant", return_value=qdrant),
                patch("app.services.rag.ingestion.get_embedding_service", return_value=embedding),
                patch("app.services.rag.ingestion.get_gemini_service", return_value=AsyncMock()),
                patch("app.services.rag.retrieval.get_qdrant", return_value=qdrant),
                patch("app.services.rag.retrieval.get_embedding_service", return_value=embedding),
            ):
                service = IngestionService()
                service._enrich_metadata = AsyncMock(return_value=[{}])
                await service.ingest_document(
                    tenant, document_id, "Première version du guide sanitaire.", "Guide"
                )
                result = await RetrievalService().retrieve(tenant, "guide")
                assert len(result.chunks) == 1
                assert "Première version" in result.chunks[0].content
                # Index payloads are not the authoritative source of text,
                # document identity or provenance.
                await qdrant.set_payload(
                    collection_name="kb_onssa",
                    payload={"content": "tronqué", "title": "faux", "document_id": "faux"},
                    points=[result.chunks[0].chunk_id],
                )
                restored = await RetrievalService().retrieve(tenant, "guide")
                assert "Première version" in restored.chunks[0].content
                assert restored.chunks[0].metadata["title"] == "Guide"
                assert restored.chunks[0].document_id == str(document_id)
                hybrid = RetrievalService()
                hybrid._hybrid_enabled = True
                assert await hybrid._lexical_point_ids(tenant, "Première version", "fr", 5) == [
                    restored.chunks[0].chunk_id
                ]
                hybrid_result = await hybrid.retrieve(tenant, "Première version", language="fr")
                assert hybrid_result.chunks[0].document_id == str(document_id)
                await service.reindex_document(
                    tenant, document_id, "Deuxième version du guide sanitaire.", "Guide"
                )
                result = await RetrievalService().retrieve(tenant, "guide")
                assert len(result.chunks) == 1
                assert "Deuxième version" in result.chunks[0].content
                embedding.embed_batch.side_effect = RuntimeError("provider unavailable")
                with pytest.raises(Exception, match="provider unavailable"):
                    await service.reindex_document(
                        tenant, document_id, "Nouvelle version.", "Guide"
                    )
                result = await RetrievalService().retrieve(tenant, "guide")
                assert len(result.chunks) == 1
                assert "Deuxième version" in result.chunks[0].content
                async with tenant.db_session() as session:
                    document = (
                        await session.execute(
                            select(KBDocument).where(KBDocument.id == document_id)
                        )
                    ).scalar_one()
                    assert document.active_index_version == 2
                embedding.embed_batch.side_effect = None
                await asyncio.gather(
                    service.reindex_document(
                        tenant, document_id, "Version concurrente A.", "Guide"
                    ),
                    service.reindex_document(
                        tenant, document_id, "Version concurrente B.", "Guide"
                    ),
                )
                async with tenant.db_session() as session:
                    document = (
                        await session.execute(
                            select(KBDocument).where(KBDocument.id == document_id)
                        )
                    ).scalar_one()
                    assert document.active_index_version == 4
                result = await RetrievalService().retrieve(tenant, "guide")
                assert len(result.chunks) == 1
                published_content = result.chunks[0].content
                assert published_content in {"Version concurrente A.", "Version concurrente B."}

                original_upsert = qdrant.upsert

                async def fail_after_write(*args, **kwargs):
                    await original_upsert(*args, **kwargs)
                    raise RuntimeError("interrupted after vector write")

                with patch.object(qdrant, "upsert", side_effect=fail_after_write):
                    with pytest.raises(Exception, match="interrupted after vector write"):
                        await service.reindex_document(
                            tenant, document_id, "Version interrompue.", "Guide"
                        )
                result = await RetrievalService().retrieve(tenant, "guide")
                assert len(result.chunks) == 1
                assert result.chunks[0].content == published_content
                async with tenant.db_session() as session:
                    document = (
                        await session.execute(
                            select(KBDocument).where(KBDocument.id == document_id)
                        )
                    ).scalar_one()
                    document.expires_at = date.today() - timedelta(days=1)
                assert (await RetrievalService().retrieve(tenant, "guide")).chunks == []
                assert await hybrid._lexical_point_ids(tenant, "guide", "fr", 5) == []
                async with tenant.db_session() as session:
                    document = (
                        await session.execute(
                            select(KBDocument).where(KBDocument.id == document_id)
                        )
                    ).scalar_one()
                    document.expires_at = None
                    document.status = KBDocumentStatus.rejected
                assert (await RetrievalService().retrieve(tenant, "guide")).chunks == []
                assert await hybrid._lexical_point_ids(tenant, "guide", "fr", 5) == []
                with pytest.raises(Exception, match="non autorisé"):
                    await service.reindex_document(tenant, document_id, "Document rejeté.", "Guide")
                async with tenant.db_session() as session:
                    document = (
                        await session.execute(
                            select(KBDocument).where(KBDocument.id == document_id)
                        )
                    ).scalar_one()
                    assert document.status == KBDocumentStatus.rejected
                    assert document.active_index_version == 4
                from app.workers.ingestion import _recover_tenant_documents

                now = datetime.now(UTC)
                old = now - timedelta(hours=2)
                approved_id, unapproved_id, recent_id, expired_id = (uuid.uuid4() for _ in range(4))
                async with tenant.db_session() as session:
                    for doc_id, approved, updated_at, expires_at in [
                        (approved_id, True, old, None),
                        (unapproved_id, False, old, None),
                        (recent_id, True, now, None),
                        (expired_id, True, old, date.today() - timedelta(days=1)),
                    ]:
                        session.add(
                            KBDocument(
                                id=doc_id,
                                title="Recovery",
                                language="fr",
                                status=KBDocumentStatus.pending,
                                file_path=f"kb/{doc_id}/source.md",
                                updated_at=updated_at,
                                validated_at=old if approved else None,
                                validated_by=uuid.uuid4() if approved else None,
                                expires_at=expires_at,
                            )
                        )
                queue = AsyncMock()
                queue.enqueue_job.return_value = object()
                assert (
                    await _recover_tenant_documents(
                        {"redis": queue}, tenant, now - timedelta(minutes=30)
                    )
                    == 1
                )
                assert queue.enqueue_job.await_args.args[2] == str(approved_id)

                # Exact legal references must be recoverable even when their
                # vector similarity ranks below the semantic top-k.
                point_ids = [str(uuid.uuid4()) for _ in range(3)]
                doc_ids = [uuid.uuid4() for _ in range(3)]
                contents = [
                    "Document générique sur les procédures sanitaires.",
                    "Autre document générique sur les contrôles.",
                    "La loi 47-18 précise la référence réglementaire recherchée.",
                ]
                async with tenant.db_session() as session:
                    for doc_id, point_id, content in zip(doc_ids, point_ids, contents, strict=True):
                        session.add(
                            KBDocument(
                                id=doc_id,
                                title="Test lexical",
                                language="fr",
                                status=KBDocumentStatus.indexed,
                                active_index_version=1,
                            )
                        )
                        await session.flush()
                        session.add(
                            KBChunk(
                                document_id=doc_id,
                                content=content,
                                chunk_index=0,
                                index_version=1,
                                qdrant_point_id=point_id,
                                token_count=10,
                            )
                        )
                await qdrant.upsert(
                    collection_name="kb_onssa",
                    points=[
                        models.PointStruct(
                            id=point_id,
                            vector=([0.1] * 768 if index < 2 else [1.0] + [0.0] * 767),
                            payload={"document_id": str(doc_ids[index]), "language": "fr"},
                        )
                        for index, point_id in enumerate(point_ids)
                    ],
                )
                plain = RetrievalService()
                plain._hybrid_enabled = False
                baseline = await plain.retrieve(tenant, '"47-18"', top_k=2, language="fr")
                assert str(doc_ids[2]) not in {chunk.document_id for chunk in baseline.chunks}
                hybrid = RetrievalService()
                hybrid._hybrid_enabled = True
                fused = await hybrid.retrieve(tenant, '"47-18"', top_k=2, language="fr")
                assert str(doc_ids[2]) in {chunk.document_id for chunk in fused.chunks}
    finally:
        await qdrant.close()
        await engine.dispose()
