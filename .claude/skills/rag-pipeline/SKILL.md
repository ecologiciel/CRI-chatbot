---
name: rag-pipeline
description: |
  Use this skill when writing any code related to the RAG (Retrieval-Augmented Generation) pipeline
  for the CRI chatbot platform. Triggers: any mention of 'RAG', 'ingestion', 'retrieval',
  'chunking', 'embedding', 'vector search', 'Qdrant', 'knowledge base', 'KB', 'base de connaissances',
  'document indexing', 'semantic search', 'reranking', 'apprentissage supervisé', 'unanswered questions',
  'confidence score', 'hallucination', 'guardrails', 'prompt template', 'context window',
  'structured RAG', 'metadata enrichment', or any work in services/rag/ directory.
  Do NOT use for general LLM questions unrelated to the RAG pipeline.
---

# RAG Pipeline — CRI Chatbot Platform

## Architecture Overview

The RAG pipeline has 3 stages, all tenant-scoped:

```
INGESTION:  Documents → Chunking → Metadata Enrichment → Embedding → Qdrant (kb_{slug})
RETRIEVAL:  User Query → Lang Detection → Embedding → Hybrid Search Qdrant → Re-ranking
GENERATION: System Prompt + Anonymized Chunks + History → Gemini 2.5 Flash → Guardrails → Response
```

**Security invariant**: No PII (CIN, phone, real dossier numbers, names) is ever sent to Gemini.
All chunks are anonymized before prompt construction. Dossier tracking operates 100% locally.

## 1. Ingestion Pipeline (`services/rag/ingestion.py`)

### 1.1 Document Sources

| Source | Method | Trigger |
|---|---|---|
| Web crawl | Scrapy/httpx + BeautifulSoup | Scheduled cron (configurable per tenant) |
| PDF/Word/Excel upload | Back-office file upload | Manual via admin UI |
| Manual text entry | Back-office KB editor | Admin creates/edits content |

### 1.2 Chunking Strategy

```python
from app.schemas.rag import ChunkCreate

async def chunk_document(
    content: str,
    doc_id: str,
    metadata: dict,
) -> list[ChunkCreate]:
    """Split document into overlapping chunks.

    Parameters:
        chunk_size: 512-1024 tokens (configurable per tenant)
        overlap: 128 tokens
        strategy: sentence-boundary aware (never split mid-sentence)
    """
    chunks = []
    sentences = split_into_sentences(content)  # Use spaCy or regex
    current_chunk = []
    current_tokens = 0

    for sentence in sentences:
        sentence_tokens = count_tokens(sentence)
        if current_tokens + sentence_tokens > chunk_size:
            chunk_text = " ".join(current_chunk)
            chunks.append(ChunkCreate(
                doc_id=doc_id,
                content=chunk_text,
                metadata={
                    **metadata,
                    "chunk_index": len(chunks),
                    "token_count": current_tokens,
                },
            ))
            # Overlap: keep last N tokens worth of sentences
            overlap_sentences = get_overlap_sentences(current_chunk, overlap_tokens=128)
            current_chunk = overlap_sentences
            current_tokens = sum(count_tokens(s) for s in overlap_sentences)

        current_chunk.append(sentence)
        current_tokens += sentence_tokens

    # Don't forget the last chunk
    if current_chunk:
        chunks.append(ChunkCreate(
            doc_id=doc_id,
            content=" ".join(current_chunk),
            metadata={**metadata, "chunk_index": len(chunks), "token_count": current_tokens},
        ))

    return chunks
```

### 1.3 Structured RAG — Metadata Enrichment via Gemini

Each chunk is enriched with structured metadata for precise filtering:

```python
async def enrich_chunk_metadata(
    chunk_text: str,
    doc_metadata: dict,
    tenant: TenantContext,
) -> dict:
    """Use Gemini to extract structured metadata from a chunk.

    Extracted fields (all optional, multi-value):
    - related_laws: list[str]         e.g. ["Loi 47-18", "Décret 2-19-1088"]
    - applicable_sectors: list[str]   e.g. ["industrie", "tourisme", "agriculture"]
    - legal_forms: list[str]          e.g. ["SARL", "SA", "auto-entrepreneur"]
    - regions: list[str]              e.g. ["Rabat-Salé-Kénitra", "Tanger-Tétouan"]
    - procedure_type: str             e.g. "création_entreprise", "investissement"
    - target_audience: str            e.g. "investisseur", "porteur_projet", "interne"
    - prerequisite_chunks: list[str]  IDs of chunks that should be read first
    """
    prompt = f"""Analyse ce texte issu d'un document du Centre Régional d'Investissement.
Extrais les métadonnées structurées suivantes au format JSON.
Ne réponds QU'avec le JSON, sans commentaire.

Texte : {chunk_text}

Format attendu :
{{
  "related_laws": [],
  "applicable_sectors": [],
  "legal_forms": [],
  "regions": [],
  "procedure_type": "",
  "target_audience": ""
}}"""

    response = await gemini_client.generate(
        prompt=prompt,
        model="gemini-2.5-flash",
        temperature=0.1,  # Low temp for structured extraction
        max_tokens=500,
    )
    return parse_json_response(response.text)
```

### 1.4 Embedding Generation

```python
async def generate_embeddings(
    texts: list[str],
    model: str = "text-embedding-004",  # or "multilingual-e5-large"
) -> list[list[float]]:
    """Generate embeddings for a batch of texts.

    - text-embedding-004: 768 dimensions, Google API
    - multilingual-e5-large: 1024 dimensions, local model (Sentence-Transformers)

    For multilingual-e5-large, prefix queries with "query: " and documents with "passage: "
    """
    if model == "text-embedding-004":
        response = await google_embedding_client.embed_content(
            model=f"models/{model}",
            content=texts,
            task_type="RETRIEVAL_DOCUMENT",
        )
        return [e.values for e in response.embeddings]
    else:
        # Local model via sentence-transformers
        return local_embedding_model.encode(
            [f"passage: {t}" for t in texts],
            normalize_embeddings=True,
        ).tolist()
```

### 1.5 Qdrant Indexation (Tenant-Scoped)

```python
async def index_chunks(
    chunks: list[ChunkCreate],
    embeddings: list[list[float]],
    tenant: TenantContext,
) -> None:
    """Index chunks into the tenant's Qdrant collection."""
    points = [
        PointStruct(
            id=str(uuid4()),
            vector=embedding,
            payload={
                "doc_id": chunk.doc_id,
                "content": chunk.content,
                "chunk_index": chunk.metadata["chunk_index"],
                # Structured RAG metadata for filtering
                "related_laws": chunk.metadata.get("related_laws", []),
                "applicable_sectors": chunk.metadata.get("applicable_sectors", []),
                "legal_forms": chunk.metadata.get("legal_forms", []),
                "regions": chunk.metadata.get("regions", []),
                "procedure_type": chunk.metadata.get("procedure_type", ""),
                "target_audience": chunk.metadata.get("target_audience", ""),
                "language": chunk.metadata.get("language", "fr"),
                "source_url": chunk.metadata.get("source_url", ""),
            },
        )
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]

    await qdrant_client.upsert(
        collection_name=tenant.qdrant_collection,  # "kb_{slug}"
        points=points,
    )
```

### 1.6 Full Ingestion Pipeline (Background Worker)

```python
@arq_worker.task
async def ingest_document(tenant_slug: str, document_id: str) -> None:
    """Full ingestion pipeline. Runs as background ARQ task."""
    tenant = await load_tenant_context(tenant_slug)

    async with tenant.db_session() as session:
        doc = await session.get(KBDocument, document_id)
        doc.status = "processing"
        await session.commit()

    try:
        # 1. Extract text
        content = await extract_text(doc.source_url or doc.file_path, tenant)

        # 2. Chunk
        chunks = await chunk_document(content, doc.id, doc.metadata_dict)

        # 3. Enrich metadata (batch, with rate limiting for Gemini)
        for chunk in chunks:
            chunk.metadata.update(
                await enrich_chunk_metadata(chunk.content, doc.metadata_dict, tenant)
            )

        # 4. Generate embeddings (batch of 100)
        all_embeddings = []
        for batch in batched(chunks, 100):
            embeddings = await generate_embeddings([c.content for c in batch])
            all_embeddings.extend(embeddings)

        # 5. Index in Qdrant
        await index_chunks(chunks, all_embeddings, tenant)

        # 6. Store chunk references in PostgreSQL
        async with tenant.db_session() as session:
            for chunk, point_id in zip(chunks, point_ids, strict=True):
                session.add(KBChunk(
                    doc_id=doc.id,
                    content=chunk.content,
                    qdrant_id=str(point_id),
                    metadata=chunk.metadata,
                ))
            doc.status = "indexed"
            await session.commit()

        logger.info("document_ingested", tenant=tenant.slug, doc_id=document_id,
                     chunks=len(chunks))

    except Exception as e:
        async with tenant.db_session() as session:
            doc.status = "error"
            await session.commit()
        logger.error("ingestion_failed", tenant=tenant.slug, doc_id=document_id, error=str(e))
        raise
```

## 2. Retrieval Pipeline (`services/rag/retrieval.py`)

### 2.1 Language Detection

```python
async def detect_language(text: str) -> Literal["fr", "ar", "en"]:
    """Detect user message language. Priority: Arabic > French > English.

    Uses heuristics first (fast), falls back to Gemini if ambiguous.
    """
    # Fast heuristic: check for Arabic Unicode range
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    if arabic_chars / max(len(text), 1) > 0.3:
        return "ar"

    # For FR/EN disambiguation, use Gemini with minimal prompt
    response = await gemini_client.generate(
        prompt=f"What language is this? Reply ONLY 'fr' or 'en': {text[:100]}",
        model="gemini-2.5-flash",
        max_tokens=5,
        temperature=0.0,
    )
    detected = response.text.strip().lower()
    return detected if detected in ("fr", "en") else "fr"  # Default to French
```

### 2.2 Hybrid Search (Semantic + Metadata Filtering)

```python
async def search_knowledge_base(
    query: str,
    tenant: TenantContext,
    language: str = "fr",
    top_k: int = 5,
    metadata_filters: dict | None = None,
) -> list[RetrievedChunk]:
    """Hybrid search: semantic similarity + structured metadata filters.

    metadata_filters example:
    {
        "applicable_sectors": ["industrie"],
        "legal_forms": ["SARL"],
        "procedure_type": "création_entreprise",
    }
    """
    # 1. Embed query
    query_prefix = "query: " if using_e5_model else ""
    query_embedding = (await generate_embeddings(
        [f"{query_prefix}{query}"],
        task_type="RETRIEVAL_QUERY",
    ))[0]

    # 2. Build Qdrant filter from metadata
    qdrant_filter = None
    if metadata_filters:
        conditions = []
        for key, value in metadata_filters.items():
            if isinstance(value, list):
                conditions.append(
                    FieldCondition(key=key, match=MatchAny(any=value))
                )
            else:
                conditions.append(
                    FieldCondition(key=key, match=MatchValue(value=value))
                )
        qdrant_filter = Filter(must=conditions)

    # 3. Search tenant's collection
    results = await qdrant_client.search(
        collection_name=tenant.qdrant_collection,  # "kb_{slug}"
        query_vector=query_embedding,
        query_filter=qdrant_filter,
        limit=top_k,
        score_threshold=0.5,  # Minimum similarity threshold
    )

    return [
        RetrievedChunk(
            content=r.payload["content"],
            score=r.score,
            doc_id=r.payload["doc_id"],
            chunk_id=str(r.id),
            metadata={k: v for k, v in r.payload.items() if k != "content"},
        )
        for r in results
    ]
```

### 2.3 Re-ranking (Optional, via Gemini)

```python
async def rerank_chunks(
    query: str,
    chunks: list[RetrievedChunk],
    top_k: int = 3,
) -> list[RetrievedChunk]:
    """Re-rank retrieved chunks using Gemini for relevance scoring.

    Only use when initial retrieval returns many borderline results.
    Cost: ~100 tokens per chunk.
    """
    if len(chunks) <= top_k:
        return chunks

    prompt = f"""Score la pertinence de chaque passage par rapport à la question.
Réponds UNIQUEMENT avec un JSON: [{{"index": 0, "score": 0.95}}, ...]

Question: {query}

Passages:
{chr(10).join(f'[{i}] {c.content[:300]}' for i, c in enumerate(chunks))}"""

    response = await gemini_client.generate(
        prompt=prompt,
        model="gemini-2.5-flash",
        temperature=0.0,
        max_tokens=200,
    )
    scores = parse_json_response(response.text)
    scored = sorted(
        [(chunks[s["index"]], s["score"]) for s in scores],
        key=lambda x: x[1],
        reverse=True,
    )
    return [chunk for chunk, _ in scored[:top_k]]
```

## 3. Generation Pipeline (`services/rag/generation.py`)

### 3.1 Prompt Construction

**CRITICAL**: Anonymize all PII before sending to Gemini.

```python
async def build_rag_prompt(
    user_message: str,
    chunks: list[RetrievedChunk],
    conversation_history: list[Message],
    language: str,
    tenant: TenantContext,
) -> str:
    """Build the complete RAG prompt for Gemini.

    Structure:
    1. System instructions (role, tone, language, guardrails)
    2. Retrieved chunks (anonymized, in XML tags)
    3. Conversation history (last 3-5 exchanges)
    4. User question
    """
    # Anonymize chunks (remove any PII that slipped through)
    anonymized_chunks = [anonymize_text(c.content) for c in chunks]

    system_prompt = f"""Tu es l'assistant virtuel du Centre Régional d'Investissement ({tenant.name}).
Tu réponds UNIQUEMENT aux questions liées à l'investissement, la création d'entreprise,
et les services du CRI. Tu réponds dans la langue de l'utilisateur ({language}).

RÈGLES STRICTES :
- Réponds UNIQUEMENT à partir des informations fournies dans <context>.
- Si l'information n'est pas dans le contexte, dis-le clairement et propose de contacter le CRI.
- Ne fabrique JAMAIS d'informations (pas d'hallucination).
- Adopte un ton professionnel et institutionnel.
- Ne communique JAMAIS de données personnelles (CIN, numéro de téléphone, noms).
- Si la question est hors périmètre CRI, refuse poliment.
- Cite les sources (lois, décrets) quand elles sont disponibles dans le contexte.

<context>
{chr(10).join(f'<chunk id="{c.chunk_id}">{text}</chunk>' for c, text in zip(chunks, anonymized_chunks))}
</context>"""

    # Build conversation history (max 5 exchanges)
    history_text = ""
    for msg in conversation_history[-10:]:  # Last 5 exchanges = 10 messages
        role = "Utilisateur" if msg.direction == "incoming" else "Assistant"
        history_text += f"\n{role}: {anonymize_text(msg.content)}"

    full_prompt = f"""{system_prompt}

<historique>{history_text}
</historique>

Utilisateur: {anonymize_text(user_message)}

Réponds en {{"fr": "français", "ar": "arabe", "en": "anglais"}.get(language, "français")}:"""

    return full_prompt
```

### 3.2 PII Anonymization (Pre-LLM)

```python
import re

# Moroccan PII patterns
PII_PATTERNS = {
    "cin": re.compile(r'\b[A-Z]{1,2}\d{5,6}\b'),                    # CIN: A12345, BE123456
    "phone_212": re.compile(r'\+212[5-7]\d{8}'),                     # +212612345678
    "phone_06_07": re.compile(r'\b0[67]\d{8}\b'),                    # 0612345678
    "email": re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.-]+\b'),
    "dossier_number": re.compile(r'\b(?:RC|IF|TP|ICE)-?\d{4,}\b'),   # RC-2024-001
    "amount_mad": re.compile(r'\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?\s*(?:MAD|DH|dh|dirhams?)\b', re.IGNORECASE),
}

def anonymize_text(text: str) -> str:
    """Remove PII from text before sending to Gemini."""
    for pii_type, pattern in PII_PATTERNS.items():
        text = pattern.sub(f"[{pii_type.upper()}_MASQUÉ]", text)
    return text
```

### 3.3 Gemini Generation Call

```python
async def generate_response(
    prompt: str,
    model: str = "gemini-2.5-flash",
) -> GenerationResult:
    """Call Gemini 2.5 Flash for RAG response generation.

    Returns structured result with response text, token counts, and latency.
    """
    start_time = time.monotonic()

    response = await gemini_client.generate_content_async(
        model=f"models/{model}",
        contents=prompt,
        generation_config={
            "temperature": 0.3,      # Low for factual RAG
            "top_p": 0.9,
            "max_output_tokens": 1024,
        },
        safety_settings=[...],  # Permissive for institutional content
    )

    latency = time.monotonic() - start_time

    return GenerationResult(
        text=response.text,
        input_tokens=response.usage_metadata.prompt_token_count,
        output_tokens=response.usage_metadata.candidates_token_count,
        latency_ms=int(latency * 1000),
        model=model,
    )
```

### 3.4 Confidence Scoring

```python
async def compute_confidence_score(
    chunks: list[RetrievedChunk],
    response_text: str,
) -> float:
    """Compute RAG confidence score based on retrieval quality.

    Factors:
    - Top chunk similarity score (40% weight)
    - Number of relevant chunks (20% weight)
    - Score variance (lower is better, 20% weight)
    - Response length vs chunk coverage (20% weight)

    Returns: 0.0 to 1.0
    Threshold: < 0.7 → add disclaimer or escalate
    """
    if not chunks:
        return 0.0

    top_score = chunks[0].score
    relevant_count = sum(1 for c in chunks if c.score > 0.6) / len(chunks)
    scores = [c.score for c in chunks]
    variance = max(scores) - min(scores) if len(scores) > 1 else 0
    stability = 1.0 - min(variance, 1.0)

    confidence = (
        top_score * 0.4
        + relevant_count * 0.2
        + stability * 0.2
        + min(len(chunks) / 5, 1.0) * 0.2
    )
    return round(min(confidence, 1.0), 3)
```

## 4. Apprentissage Supervisé (`services/rag/learning.py`)

### 4.1 Capture Unanswered Questions

```python
async def flag_unanswered(
    question: str,
    confidence: float,
    chunks: list[RetrievedChunk],
    tenant: TenantContext,
) -> None:
    """Flag low-confidence questions for human review."""
    if confidence >= 0.7:  # Configurable threshold
        return

    # Generate AI-proposed answer
    proposed = await gemini_client.generate(
        prompt=f"""En tant qu'expert CRI, propose une réponse à cette question.
Si tu ne peux pas répondre avec certitude, écris "INCERTAIN".

Question: {question}""",
        model="gemini-2.5-flash",
        temperature=0.5,
        max_tokens=500,
    )

    async with tenant.db_session() as session:
        session.add(UnansweredQuestion(
            question=question,
            proposed_answer=proposed.text,
            confidence_score=confidence,
            top_chunks=[c.chunk_id for c in chunks[:3]],
            status="pending",  # pending → approved/modified/rejected
        ))
        await session.commit()
```

### 4.2 Validation & Reinjection Flow

```
Back-office Review Queue:
  [pending] → Admin reviews → [approved] → Auto-inject into KB
                             → [modified] → Admin edits → Auto-inject into KB
                             → [rejected] → Archived (no injection)

Auto-injection:
  1. Create KBDocument from validated Q&A
  2. Chunk (usually single chunk for Q&A)
  3. Generate embedding
  4. Index in tenant's Qdrant collection
  5. Mark UnansweredQuestion as "injected"
```

## 5. Feedback Correlation (`services/rag/feedback.py`)

```python
async def process_negative_feedback(
    message_id: str,
    reason: str,
    tenant: TenantContext,
) -> None:
    """Track negative feedback and correlate with chunks for quality improvement.

    Chunks with high negative feedback rate are flagged for review.
    """
    async with tenant.db_session() as session:
        message = await session.get(Message, message_id)
        chunk_ids = message.chunk_ids or []  # Stored during generation

        session.add(Feedback(
            message_id=message_id,
            rating="negative",
            comment=reason,
            chunk_ids=chunk_ids,
        ))
        await session.commit()

    # Check if any chunk has accumulated too many negative feedbacks
    for chunk_id in chunk_ids:
        neg_count = await count_negative_feedbacks_for_chunk(chunk_id, tenant)
        if neg_count >= 5:  # Threshold configurable
            logger.warning("chunk_underperforming", chunk_id=chunk_id,
                          tenant=tenant.slug, neg_count=neg_count)
```

## 6. Performance Targets

| Metric | Target | How |
|---|---|---|
| Retrieval latency (Qdrant) | < 100ms | HNSW index, in-memory segments |
| Embedding generation | < 200ms | Batch processing, API caching |
| Gemini TTFT | < 1s | Gemini 2.5 Flash, streaming |
| Total RAG response | < 2s (P95) | All above + Redis cache for frequent queries |
| Confidence accuracy | > 85% | Tuned thresholds per tenant |

## 7. Caching Strategy

```python
async def get_cached_response(
    query_hash: str,
    tenant: TenantContext,
) -> str | None:
    """Check Redis cache for identical recent queries."""
    key = f"{tenant.redis_prefix}:rag_cache:{query_hash}"
    return await redis.get(key)

async def cache_response(
    query_hash: str,
    response: str,
    tenant: TenantContext,
    ttl: int = 3600,  # 1 hour default
) -> None:
    key = f"{tenant.redis_prefix}:rag_cache:{query_hash}"
    await redis.setex(key, ttl, response)
```

## Quick Reference — File Locations

| Component | Path |
|---|---|
| Ingestion service | `backend/app/services/rag/ingestion.py` |
| Retrieval service | `backend/app/services/rag/retrieval.py` |
| Generation service | `backend/app/services/rag/generation.py` |
| Learning service | `backend/app/services/rag/learning.py` |
| Feedback service | `backend/app/services/rag/feedback.py` |
| PII anonymizer | `backend/app/services/guardrails/anonymizer.py` |
| Qdrant client | `backend/app/core/qdrant.py` |
| Embedding client | `backend/app/services/ai/embeddings.py` |
| Gemini client | `backend/app/services/ai/gemini.py` |
| Pydantic schemas | `backend/app/schemas/rag.py` |
| SQLAlchemy models | `backend/app/models/kb.py` |
| ARQ worker tasks | `backend/app/workers/ingestion.py` |
