"""Cross-tenant resource name isolation tests.

Verifies that TenantContext generates completely separate resource names
for different tenants, with no collisions possible.
"""

import uuid

import pytest

from app.core.tenant import TenantContext

from .conftest import make_tenant


class TestTenantResourceIsolation:
    """Two tenants must never share resource names."""

    def test_two_tenants_different_db_schemas(self, tenant_alpha, tenant_beta):
        """Different tenants get different PostgreSQL schemas."""
        assert tenant_alpha.db_schema == "tenant_alpha"
        assert tenant_beta.db_schema == "tenant_beta"
        assert tenant_alpha.db_schema != tenant_beta.db_schema

    def test_two_tenants_different_qdrant_collections(self, tenant_alpha, tenant_beta):
        """Different tenants get different Qdrant collections."""
        assert tenant_alpha.qdrant_collection == "kb_alpha"
        assert tenant_beta.qdrant_collection == "kb_beta"
        assert tenant_alpha.qdrant_collection != tenant_beta.qdrant_collection

    def test_two_tenants_different_redis_prefixes(self, tenant_alpha, tenant_beta):
        """Different tenants get different Redis key prefixes."""
        assert tenant_alpha.redis_prefix == "alpha"
        assert tenant_beta.redis_prefix == "beta"
        assert tenant_alpha.redis_prefix != tenant_beta.redis_prefix

    def test_two_tenants_different_minio_buckets(self, tenant_alpha, tenant_beta):
        """Different tenants get different MinIO buckets."""
        assert tenant_alpha.minio_bucket == "cri-alpha"
        assert tenant_beta.minio_bucket == "cri-beta"
        assert tenant_alpha.minio_bucket != tenant_beta.minio_bucket

    def test_resource_names_deterministic_by_slug(self):
        """Same slug with different UUIDs produces identical resource names."""
        t1 = make_tenant("rabat", id=uuid.uuid4())
        t2 = make_tenant("rabat", id=uuid.uuid4())

        assert t1.id != t2.id
        assert t1.db_schema == t2.db_schema == "tenant_rabat"
        assert t1.qdrant_collection == t2.qdrant_collection == "kb_rabat"
        assert t1.redis_prefix == t2.redis_prefix == "rabat"
        assert t1.minio_bucket == t2.minio_bucket == "cri-rabat"
