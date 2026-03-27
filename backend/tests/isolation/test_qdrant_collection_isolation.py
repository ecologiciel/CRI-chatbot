"""Qdrant collection isolation tests.

Verifies that each tenant gets a unique Qdrant collection name
derived from its slug, with no possibility of cross-tenant overlap.
"""

import pytest

from app.core.tenant import TenantContext

from .conftest import make_tenant


class TestQdrantCollectionIsolation:
    """Qdrant collections must be strictly per-tenant."""

    def test_collection_name_format(self, tenant_alpha, tenant_beta):
        """Collection names follow the kb_{slug} pattern."""
        assert tenant_alpha.qdrant_collection == "kb_alpha"
        assert tenant_beta.qdrant_collection == "kb_beta"

    def test_no_collection_overlap_many_tenants(self):
        """10 distinct tenants produce 10 unique collection names."""
        slugs = ["rabat", "tanger", "casa", "marrakech", "fes",
                 "agadir", "oujda", "kenitra", "tetouan", "meknes"]
        collections = {make_tenant(s).qdrant_collection for s in slugs}
        assert len(collections) == 10

    def test_collection_name_consistent(self):
        """Two TenantContext instances with the same slug yield the same collection."""
        t1 = make_tenant("rabat")
        t2 = make_tenant("rabat")
        assert t1.qdrant_collection == t2.qdrant_collection

    def test_collection_rejects_invalid_slug(self):
        """Invalid slugs are rejected before a collection name can be formed."""
        with pytest.raises(ValueError, match="Invalid tenant slug"):
            make_tenant("invalid-slug")
