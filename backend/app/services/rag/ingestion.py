"""IngestionService — full document ingestion pipeline.

Pipeline: extract text → chunk → enrich metadata (Gemini) → embed → upsert Qdrant → save DB.

Usage:
    service = get_ingestion_service()
    chunk_count = await service.ingest_document(tenant, doc_id, content, title)
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid

import structlog
from prometheus_client import Counter, Histogram
from qdrant_client.models import PointStruct
from sqlalchemy import delete, select, update

from app.core.exceptions import IngestionError
from app.core.qdrant import get_qdrant
from app.core.tenant import TenantContext
from app.models.enums import KBDocumentStatus
from app.models.kb import KBChunk, KBDocument
from app.schemas.rag import ChunkResult, MetadataEnrichment
from app.services.ai.embeddings import get_embedding_service
from app.services.ai.gemini import get_gemini_service
from app.services.rag.chunker import get_chunking_service

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
INGESTION_DOCS = Counter(
    "cri_ingestion_documents_total",
    "Documents processed by ingestion pipeline",
    ["tenant", "status"],
)
INGESTION_CHUNKS = Counter(
    "cri_ingestion_chunks_total",
    "Chunks created during ingestion",
    ["tenant"],
)
INGESTION_LATENCY = Histogram(
    "cri_ingestion_latency_seconds",
    "Document ingestion pipeline latency",
    ["tenant"],
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

# Metadata enrichment: batch size for Gemini calls
ENRICHMENT_BATCH_SIZE = 5

ENRICHMENT_SYSTEM_PROMPT = """Tu es un classificateur de contenu pour les Centres Régionaux d'Investissement (CRI) du Maroc.
Pour chaque texte fourni, extrais les métadonnées structurées suivantes en JSON :
- related_laws: liste des lois/décrets mentionnés (ex: "Loi 47-18", "Décret 2-19-1086")
- applicable_sectors: secteurs économiques concernés (ex: "industrie", "tourisme", "agriculture", "commerce")
- legal_forms: formes juridiques mentionnées (ex: "SARL", "SA", "SAS", "auto-entrepreneur")
- regions: régions marocaines mentionnées
- language: code langue du texte (fr/ar/en)
- summary: résumé en une phrase (max 50 mots)

Réponds UNIQUEMENT en JSON valide. Format: une liste de N objets JSON (un par texte fourni)."""


class IngestionService:
    """Full document ingestion: chunk → enrich → embed → Qdrant upsert → DB save.

    Orchestrates the complete write path for the RAG pipeline. Each operation
    targets the tenant's isolated resources (DB schema, Qdrant collection).
    """

    def __init__(self) -> None:
        self._chunker = get_chunking_service()
        self._embedder = get_embedding_service()
        self._gemini = get_gemini_service()
        self._qdrant = get_qdrant()
        self._logger = logger.bind(service="ingestion")

    async def ingest_document(
        self,
        tenant: TenantContext,
        document_id: uuid.UUID,
        content: str,
        title: str,
    ) -> int:
        """Ingest a document: chunk, enrich, embed, index.

        Args:
            tenant: Tenant context for scoping all operations.
            document_id: UUID of the existing KBDocument record.
            content: Full document text content.
            title: Document title (included in Qdrant payload).

        Returns:
            Number of chunks created and indexed.

        Raises:
            IngestionError: If any pipeline step fails.
        """
        start_time = time.monotonic()
        log = self._logger.bind(
            tenant=tenant.slug,
            document_id=str(document_id),
            title=title,
        )

        try:
            # 1. Set status → indexing
            await self._update_document_status(
                tenant,
                document_id,
                KBDocumentStatus.indexing,
            )

            # 2. Content hash for dedup
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            # 3. Dedup check
            if await self._is_duplicate(tenant, document_id, content_hash):
                log.info("ingestion_skipped_duplicate", content_hash=content_hash)
                await self._update_document_status(
                    tenant,
                    document_id,
                    KBDocumentStatus.indexed,
                    content_hash=content_hash,
                )
                return 0

            # 4. Chunk the content
            chunk_results = self._chunker.chunk_text(content)
            log.info("chunks_created", count=len(chunk_results))

            # 5. Enrich metadata via Gemini (best-effort)
            metadata_list = await self._enrich_metadata(
                [c.content for c in chunk_results],
                tenant,
            )

            # 6. Generate embeddings for all chunks
            vectors = await self._embedder.embed_batch(
                [c.content for c in chunk_results],
                tenant,
            )

            # 7. Upsert into Qdrant
            point_ids = await self._index_qdrant(
                tenant,
                chunk_results,
                vectors,
                metadata_list,
                document_id,
                title,
            )

            # 8. Save KBChunk records in tenant DB
            await self._save_chunks_db(
                tenant,
                document_id,
                chunk_results,
                metadata_list,
                point_ids,
            )

            # 9. Update document status → indexed
            await self._update_document_status(
                tenant,
                document_id,
                KBDocumentStatus.indexed,
                chunk_count=len(chunk_results),
                content_hash=content_hash,
            )

            # Metrics
            latency = time.monotonic() - start_time
            INGESTION_DOCS.labels(tenant=tenant.slug, status="success").inc()
            INGESTION_CHUNKS.labels(tenant=tenant.slug).inc(len(chunk_results))
            INGESTION_LATENCY.labels(tenant=tenant.slug).observe(latency)

            log.info(
                "document_ingested",
                chunk_count=len(chunk_results),
                latency_s=round(latency, 2),
            )

            return len(chunk_results)

        except IngestionError:
            raise
        except Exception as exc:
            latency = time.monotonic() - start_time
            INGESTION_DOCS.labels(tenant=tenant.slug, status="error").inc()
            INGESTION_LATENCY.labels(tenant=tenant.slug).observe(latency)

            log.error("ingestion_failed", error=str(exc))

            # Set document status to error
            await self._update_document_status(
                tenant,
                document_id,
                KBDocumentStatus.error,
                error_message=str(exc),
            )

            raise IngestionError(
                message=f"Ingestion failed for document {document_id}: {exc}",
                details={"document_id": str(document_id), "tenant": tenant.slug},
            ) from exc

    async def delete_document(
        self,
        tenant: TenantContext,
        document_id: uuid.UUID,
    ) -> None:
        """Remove all chunks from Qdrant and DB for a document.

        Args:
            tenant: Tenant context for scoping.
            document_id: UUID of the document to delete.
        """
        log = self._logger.bind(
            tenant=tenant.slug,
            document_id=str(document_id),
        )

        # 1. Get qdrant_point_ids from DB
        point_ids: list[str] = []
        async with tenant.db_session() as session:
            result = await session.execute(
                select(KBChunk.qdrant_point_id).where(
                    KBChunk.document_id == document_id,
                )
            )
            point_ids = [row[0] for row in result.fetchall() if row[0] is not None]

        # 2. Delete from Qdrant
        if point_ids:
            await self._qdrant.delete(
                collection_name=tenant.qdrant_collection,
                points_selector=point_ids,
            )
            log.info("qdrant_points_deleted", count=len(point_ids))

        # 3. Delete chunks from DB
        async with tenant.db_session() as session:
            await session.execute(delete(KBChunk).where(KBChunk.document_id == document_id))
            await session.commit()

        # 4. Reset document status
        await self._update_document_status(
            tenant,
            document_id,
            KBDocumentStatus.pending,
            chunk_count=0,
        )

        log.info("document_deleted")

    async def reindex_document(
        self,
        tenant: TenantContext,
        document_id: uuid.UUID,
        content: str,
        title: str,
    ) -> int:
        """Delete existing chunks and re-ingest the document.

        Args:
            tenant: Tenant context.
            document_id: UUID of the document to reindex.
            content: Full document text content.
            title: Document title.

        Returns:
            Number of new chunks created.
        """
        await self.delete_document(tenant, document_id)
        return await self.ingest_document(tenant, document_id, content, title)

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    async def _update_document_status(
        self,
        tenant: TenantContext,
        document_id: uuid.UUID,
        status: KBDocumentStatus,
        chunk_count: int | None = None,
        error_message: str | None = None,
        content_hash: str | None = None,
    ) -> None:
        """Update document status and optional fields in tenant DB."""
        values: dict = {"status": status}
        if chunk_count is not None:
            values["chunk_count"] = chunk_count
        if error_message is not None:
            values["error_message"] = error_message
        if content_hash is not None:
            values["content_hash"] = content_hash

        async with tenant.db_session() as session:
            await session.execute(
                update(KBDocument).where(KBDocument.id == document_id).values(**values)
            )
            await session.commit()

    async def _is_duplicate(
        self,
        tenant: TenantContext,
        document_id: uuid.UUID,
        content_hash: str,
    ) -> bool:
        """Check if another document with same content_hash is already indexed."""
        async with tenant.db_session() as session:
            result = await session.execute(
                select(KBDocument.id).where(
                    KBDocument.content_hash == content_hash,
                    KBDocument.status == KBDocumentStatus.indexed,
                    KBDocument.id != document_id,
                )
            )
            return result.first() is not None

    async def _enrich_metadata(
        self,
        chunks_content: list[str],
        tenant: TenantContext,
    ) -> list[dict]:
        """Enrich chunks with structured metadata via Gemini (batched, best-effort).

        Groups chunks in batches of ENRICHMENT_BATCH_SIZE and sends each batch
        to Gemini for metadata extraction. On any failure, returns empty dicts
        for the failed batch — never blocks ingestion.

        Returns:
            List of metadata dicts (one per chunk).
        """
        all_metadata: list[dict] = []

        for i in range(0, len(chunks_content), ENRICHMENT_BATCH_SIZE):
            batch = chunks_content[i : i + ENRICHMENT_BATCH_SIZE]
            batch_metadata = await self._enrich_batch(batch, tenant)
            all_metadata.extend(batch_metadata)

        return all_metadata

    async def _enrich_batch(
        self,
        batch: list[str],
        tenant: TenantContext,
    ) -> list[dict]:
        """Enrich a single batch of chunks via Gemini."""
        try:
            # Build prompt with numbered chunks
            numbered = "\n\n".join(
                f"--- Texte {i + 1} ---\n{text[:2000]}"  # Limit per chunk
                for i, text in enumerate(batch)
            )
            prompt = f"Analyse les {len(batch)} textes suivants et retourne un tableau JSON de {len(batch)} objets:\n\n{numbered}"

            response_text = await self._gemini.generate_simple(
                prompt=prompt,
                tenant=tenant,
                system_prompt=ENRICHMENT_SYSTEM_PROMPT,
            )

            # Parse JSON response
            # Strip markdown code fences if present
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()

            parsed = json.loads(cleaned)

            if isinstance(parsed, list):
                result: list[dict] = []
                for item in parsed:
                    try:
                        enrichment = MetadataEnrichment.model_validate(item)
                        result.append(enrichment.model_dump())
                    except Exception:
                        result.append({})
                # Pad if Gemini returned fewer items than expected
                while len(result) < len(batch):
                    result.append({})
                return result[: len(batch)]
            else:
                # Single object — wrap and pad
                try:
                    enrichment = MetadataEnrichment.model_validate(parsed)
                    result = [enrichment.model_dump()]
                except Exception:
                    result = [{}]
                while len(result) < len(batch):
                    result.append({})
                return result[: len(batch)]

        except Exception as exc:
            self._logger.warning(
                "metadata_enrichment_failed",
                error=str(exc),
                batch_size=len(batch),
                tenant=tenant.slug,
            )
            # Best-effort: return empty metadata for each chunk in the batch
            return [{} for _ in batch]

    async def _index_qdrant(
        self,
        tenant: TenantContext,
        chunks: list[ChunkResult],
        embeddings: list[list[float]],
        metadata_list: list[dict],
        document_id: uuid.UUID,
        title: str,
    ) -> list[str]:
        """Upsert vectors into Qdrant collection.

        Each point has:
        - id: UUID4 string
        - vector: embedding (768 dim)
        - payload: document_id, chunk_index, content, title, + enriched metadata

        Returns:
            List of qdrant point ID strings.
        """
        point_ids: list[str] = []
        points: list[PointStruct] = []

        for i, (chunk, vector) in enumerate(zip(chunks, embeddings, strict=False)):
            point_id = str(uuid.uuid4())
            point_ids.append(point_id)

            metadata = metadata_list[i] if i < len(metadata_list) else {}

            payload = {
                "document_id": str(document_id),
                "chunk_index": chunk.chunk_index,
                "content": chunk.content[:2000],  # Limit payload size
                "title": title,
                "language": metadata.get("language", "fr"),
                "related_laws": metadata.get("related_laws", []),
                "applicable_sectors": metadata.get("applicable_sectors", []),
                "legal_forms": metadata.get("legal_forms", []),
                "regions": metadata.get("regions", []),
                "summary": metadata.get("summary", ""),
            }

            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            )

        # Upsert in batches of 100
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            await self._qdrant.upsert(
                collection_name=tenant.qdrant_collection,
                points=batch,
            )

        self._logger.info(
            "qdrant_points_upserted",
            count=len(points),
            collection=tenant.qdrant_collection,
            tenant=tenant.slug,
        )

        return point_ids

    async def _save_chunks_db(
        self,
        tenant: TenantContext,
        document_id: uuid.UUID,
        chunks: list[ChunkResult],
        metadata_list: list[dict],
        point_ids: list[str],
    ) -> None:
        """Bulk insert KBChunk records into the tenant's DB schema."""
        async with tenant.db_session() as session:
            for i, chunk in enumerate(chunks):
                metadata = metadata_list[i] if i < len(metadata_list) else {}
                db_chunk = KBChunk(
                    document_id=document_id,
                    content=chunk.content,
                    chunk_index=chunk.chunk_index,
                    qdrant_point_id=point_ids[i] if i < len(point_ids) else None,
                    token_count=chunk.token_count,
                    metadata_=metadata,
                )
                session.add(db_chunk)
            await session.commit()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_ingestion_service: IngestionService | None = None


def get_ingestion_service() -> IngestionService:
    """Get or create the IngestionService singleton."""
    global _ingestion_service  # noqa: PLW0603
    if _ingestion_service is None:
        _ingestion_service = IngestionService()
    return _ingestion_service
