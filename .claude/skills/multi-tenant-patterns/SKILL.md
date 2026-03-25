---
name: multi-tenant-patterns
description: |
  Use this skill PROACTIVELY whenever writing any backend code for the CRI chatbot platform.
  Triggers: any mention of 'tenant', 'multi-tenant', 'isolation', 'schema', 'middleware',
  database queries, Qdrant operations, Redis operations, MinIO operations, WhatsApp config,
  or ANY service/endpoint/model creation. This skill enforces tenant isolation as a
  security invariant — every line of code MUST be scoped to the current tenant.
  Do NOT skip this skill for "simple" code — even a single unscoped query is a data breach.
---

# Multi-Tenant Isolation Patterns — CRI Chatbot Platform

## CRITICAL INVARIANT

**Every database query, cache operation, vector search, object storage access, and WhatsApp API call MUST be scoped to the current tenant.** There are ZERO exceptions. An unscoped operation is a cross-tenant data leak and a security breach.

## Architecture Overview

Each CRI (Centre Régional d'Investissement) is an isolated tenant:
- **PostgreSQL**: Schema per tenant (`tenant_{slug}.table_name`) + Row Level Security as safety net
- **Qdrant**: Collection per tenant (`kb_{slug}`)
- **Redis**: Key prefix per tenant (`{slug}:resource:id`)
- **MinIO**: Bucket per tenant (`cri-{slug}/`)
- **WhatsApp**: Separate `phone_number_id`, `access_token`, and templates per tenant

## 1. TenantContext — The Core Dependency

Every service function receives tenant context via FastAPI's `Depends()`:

```python
# app/core/tenant.py

from dataclasses import dataclass
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Request, HTTPException

@dataclass(frozen=True)
class TenantContext:
    """Immutable tenant context injected into every request."""
    id: str
    slug: str
    name: str
    db_schema: str           # "tenant_{slug}"
    qdrant_collection: str   # "kb_{slug}"
    redis_prefix: str        # "{slug}"
    minio_bucket: str        # "cri-{slug}"
    whatsapp_config: dict    # phone_number_id, access_token, verify_token, templates

    async def db_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Yield an async session scoped to this tenant's schema."""
        # Implementation sets search_path to self.db_schema
        ...

async def get_current_tenant(request: Request) -> TenantContext:
    """Extract tenant from request.state (set by TenantMiddleware)."""
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise HTTPException(status_code=500, detail="Tenant context not resolved")
    return tenant
```

## 2. TenantMiddleware — Resolution Logic

The middleware resolves tenant identity before any route handler executes:

```python
# app/core/middleware.py

class TenantMiddleware(BaseHTTPMiddleware):
    """Resolve tenant from request source."""

    async def dispatch(self, request: Request, call_next):
        # Source 1: WhatsApp webhook — resolve from phone_number_id
        if request.url.path.startswith("/api/v1/webhook/whatsapp"):
            body = await request.body()
            phone_number_id = extract_phone_number_id(body)
            tenant = await resolve_tenant_by_phone(phone_number_id)  # Redis lookup

        # Source 2: Back-office API — resolve from X-Tenant-ID header + JWT
        elif request.url.path.startswith("/api/v1/"):
            tenant_id = request.headers.get("X-Tenant-ID")
            jwt_payload = verify_jwt(request)  # Validates role has access to tenant
            tenant = await resolve_tenant_by_id(tenant_id)

        # Source 3: Super-admin — optional X-Tenant-ID
        # (super_admin role can access any tenant or operate cross-tenant)

        request.state.tenant = tenant
        response = await call_next(request)
        return response
```

**Redis mapping for WhatsApp resolution:**
```
phone_mapping:{phone_number_id} → tenant_id
```
This mapping is set during tenant provisioning and cached with no TTL (invalidated on config change).

## 3. MANDATORY Patterns — Use These Everywhere

### 3.1 Service Functions

```python
# ✅ CORRECT — Every service function receives TenantContext
async def get_dossier(
    dossier_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
) -> DossierResponse:
    """Fetch a dossier within the current tenant's schema."""
    async with tenant.db_session() as session:
        result = await session.execute(
            select(Dossier).where(Dossier.id == dossier_id)
        )
        dossier = result.scalar_one_or_none()
        if not dossier:
            raise DossierNotFoundError(dossier_id)
        return DossierResponse.model_validate(dossier)

# ❌ FORBIDDEN — No tenant context, no schema isolation
async def get_dossier(dossier_id: str):
    async with get_session() as session:  # Which schema? BREACH!
        ...
```

### 3.2 Database Queries (PostgreSQL)

```python
# ✅ CORRECT — Session is scoped to tenant schema
async with tenant.db_session() as session:
    # This automatically operates in tenant_{slug} schema
    stmt = select(Contact).where(Contact.phone == phone_number)
    result = await session.execute(stmt)

# ❌ FORBIDDEN patterns:
# - Raw SQL without schema prefix
# - Using a shared session pool without schema switching
# - Cross-schema joins (SELECT * FROM tenant_rabat.x JOIN tenant_tanger.y)
# - Using the 'public' schema for tenant data
```

**Schema switching implementation:**
```python
async def _set_tenant_schema(session: AsyncSession, schema: str) -> None:
    """Set the search_path for this session to the tenant's schema."""
    await session.execute(text(f"SET search_path TO {schema}, public"))
```

### 3.3 Vector Search (Qdrant)

```python
# ✅ CORRECT — Always use tenant's collection
async def search_knowledge_base(
    query_embedding: list[float],
    tenant: TenantContext,
    top_k: int = 5,
    filters: dict | None = None,
) -> list[QdrantSearchResult]:
    results = await qdrant_client.search(
        collection_name=tenant.qdrant_collection,  # "kb_{slug}"
        query_vector=query_embedding,
        limit=top_k,
        query_filter=build_qdrant_filter(filters) if filters else None,
    )
    return [QdrantSearchResult.from_scored_point(r) for r in results]

# ❌ FORBIDDEN — Hardcoded or missing collection name
results = await qdrant_client.search(collection_name="knowledge_base", ...)
```

### 3.4 Cache Operations (Redis)

```python
# ✅ CORRECT — Always prefix with tenant slug
async def get_session_data(session_id: str, tenant: TenantContext) -> dict | None:
    key = f"{tenant.redis_prefix}:session:{session_id}"
    data = await redis.get(key)
    return json.loads(data) if data else None

async def set_otp(phone: str, otp_hash: str, tenant: TenantContext) -> None:
    key = f"{tenant.redis_prefix}:otp:{phone}"
    await redis.setex(key, 300, otp_hash)  # TTL 5 minutes

# Rate limiting keys
f"{tenant.redis_prefix}:rl:user:{phone}"      # Per-user rate limit
f"{tenant.redis_prefix}:rl:webhook"            # Per-tenant webhook limit
f"{tenant.redis_prefix}:rl:otp:{phone}"        # OTP anti-bruteforce

# ❌ FORBIDDEN — No tenant prefix
await redis.get(f"session:{session_id}")  # Which tenant? BREACH!
```

### 3.5 Object Storage (MinIO)

```python
# ✅ CORRECT — Always use tenant's bucket
async def upload_document(
    file: UploadFile,
    tenant: TenantContext,
) -> str:
    object_name = f"documents/{uuid4()}/{file.filename}"
    await minio_client.put_object(
        bucket_name=tenant.minio_bucket,  # "cri-{slug}"
        object_name=object_name,
        data=file.file,
        length=file.size,
        content_type=file.content_type,
    )
    return object_name

# ❌ FORBIDDEN — Hardcoded bucket
await minio_client.put_object(bucket_name="documents", ...)
```

### 3.6 WhatsApp API Calls

```python
# ✅ CORRECT — Use tenant's WhatsApp config
async def send_whatsapp_message(
    to: str,
    content: MessageContent,
    tenant: TenantContext,
) -> WhatsAppResponse:
    wa_config = tenant.whatsapp_config
    response = await httpx_client.post(
        f"https://graph.facebook.com/v21.0/{wa_config['phone_number_id']}/messages",
        headers={"Authorization": f"Bearer {wa_config['access_token']}"},
        json={"messaging_product": "whatsapp", "to": to, **content.to_api_dict()},
    )
    return WhatsAppResponse.model_validate(response.json())

# ❌ FORBIDDEN — Shared/hardcoded WhatsApp credentials
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")  # Which tenant?!
```

## 4. Tenant Provisioning Checklist

When creating a new tenant, ALL of these must be provisioned:

```python
async def provision_tenant(data: TenantCreate) -> TenantContext:
    """Provision all resources for a new tenant. Atomic — rollback on failure."""
    slug = data.slug  # e.g., "rabat", "tanger"

    # 1. PostgreSQL: Create schema + tables
    await create_tenant_schema(f"tenant_{slug}")
    await run_alembic_migrations(schema=f"tenant_{slug}")
    await setup_rls_policies(schema=f"tenant_{slug}")

    # 2. Qdrant: Create collection with HNSW index
    await qdrant_client.create_collection(
        collection_name=f"kb_{slug}",
        vectors_config=VectorParams(size=768, distance=Distance.COSINE),
    )

    # 3. Redis: Set phone_number_id → tenant_id mapping
    await redis.set(
        f"phone_mapping:{data.whatsapp_phone_number_id}",
        str(tenant_id),
    )

    # 4. MinIO: Create bucket with IAM policy
    await minio_client.make_bucket(f"cri-{slug}")
    await set_bucket_policy(f"cri-{slug}", tenant_id)

    # 5. Store tenant record in public schema
    tenant = Tenant(slug=slug, name=data.name, ...)
    await db.add(tenant)
    await db.commit()
```

## 5. Anti-Patterns — NEVER Do These

| Anti-Pattern | Risk | Correct Pattern |
|---|---|---|
| `session.execute(text("SELECT * FROM dossiers"))` without schema | Queries wrong/default schema | Use `tenant.db_session()` which sets `search_path` |
| `qdrant.search(collection_name="knowledge_base")` | Searches all tenants' data | `qdrant.search(collection_name=tenant.qdrant_collection)` |
| `redis.get(f"session:{id}")` | Reads another tenant's session | `redis.get(f"{tenant.redis_prefix}:session:{id}")` |
| `os.getenv("WHATSAPP_TOKEN")` for API calls | Uses wrong tenant's token | `tenant.whatsapp_config['access_token']` |
| Cross-tenant JOIN in SQL | Data leak between tenants | NEVER — each tenant is a separate schema |
| Caching query results without tenant key | Cache poisoning across tenants | Always include tenant slug in cache key |
| Background task without tenant context | Loses tenant scope | Pass `tenant_slug` to worker, reconstruct `TenantContext` |

## 6. Background Workers / Async Tasks

Workers (Celery/ARQ) run outside the request lifecycle. They MUST reconstruct tenant context:

```python
# ✅ CORRECT — Worker reconstructs tenant context
@arq_worker.task
async def process_document_ingestion(tenant_slug: str, document_id: str):
    tenant = await load_tenant_context(tenant_slug)  # From DB
    async with tenant.db_session() as session:
        doc = await session.get(KBDocument, document_id)
        chunks = chunk_document(doc.content)
        embeddings = await generate_embeddings(chunks)
        await qdrant_client.upsert(
            collection_name=tenant.qdrant_collection,
            points=[...],
        )

# ❌ FORBIDDEN — Worker without tenant context
@arq_worker.task
async def process_document_ingestion(document_id: str):
    # No tenant context — which schema? which collection? BREACH!
```

## 7. Testing Multi-Tenant Isolation

Every test suite MUST include tenant isolation verification:

```python
@pytest.mark.asyncio
async def test_tenant_isolation():
    """Verify that tenant A cannot access tenant B's data."""
    # Create data in tenant_rabat
    async with tenant_rabat.db_session() as session:
        await session.execute(insert(Contact).values(phone="+212600000001"))
        await session.commit()

    # Verify tenant_tanger cannot see it
    async with tenant_tanger.db_session() as session:
        result = await session.execute(
            select(Contact).where(Contact.phone == "+212600000001")
        )
        assert result.scalar_one_or_none() is None  # Must be None!

@pytest.mark.asyncio
async def test_qdrant_collection_isolation():
    """Verify Qdrant searches are scoped to tenant collection."""
    # Insert vector in kb_rabat
    await qdrant.upsert(collection_name="kb_rabat", points=[test_point])

    # Search in kb_tanger — must NOT find it
    results = await qdrant.search(collection_name="kb_tanger", query_vector=test_vector)
    assert len(results) == 0
```

## 8. Structured Logging with Tenant Context

Always include tenant slug in log entries:

```python
import structlog

logger = structlog.get_logger()

async def handle_message(message: IncomingMessage, tenant: TenantContext):
    logger.info(
        "processing_whatsapp_message",
        tenant=tenant.slug,
        phone=mask_phone(message.from_),  # Mask PII in logs
        message_type=message.type,
    )
```

## Quick Reference

| Resource | Tenant Scope Pattern | Example |
|---|---|---|
| PostgreSQL session | `tenant.db_session()` | Auto sets `search_path` to `tenant_{slug}` |
| Qdrant collection | `tenant.qdrant_collection` | `"kb_rabat"` |
| Redis key | `f"{tenant.redis_prefix}:{resource}:{id}"` | `"rabat:session:abc123"` |
| MinIO bucket | `tenant.minio_bucket` | `"cri-rabat"` |
| WhatsApp token | `tenant.whatsapp_config['access_token']` | Per-tenant token |
| Background task | Pass `tenant_slug`, reconstruct context | `load_tenant_context(slug)` |
| Log entry | `logger.info(..., tenant=tenant.slug)` | Always include tenant |
| Cache key | `f"{tenant.slug}:{cache_namespace}:{key}"` | `"rabat:faq_cache:hash"` |
