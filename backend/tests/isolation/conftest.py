"""Shared fixtures for multi-tenant isolation tests.

Provides two test tenants (alpha, beta) and a factory function.
"""

import uuid

import pytest

from app.core.tenant import TenantContext

TENANT_ALPHA_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_BETA_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def make_tenant(slug: str, **overrides) -> TenantContext:
    """Factory to create a TenantContext with deterministic defaults."""
    defaults = {
        "id": uuid.uuid5(uuid.NAMESPACE_DNS, slug),
        "slug": slug,
        "name": f"CRI {slug.capitalize()}",
        "status": "active",
        "whatsapp_config": {"phone_number_id": f"phone_{slug}", "access_token": f"tok_{slug}"},
    }
    defaults.update(overrides)
    return TenantContext(**defaults)


@pytest.fixture
def tenant_alpha() -> TenantContext:
    return TenantContext(
        id=TENANT_ALPHA_ID,
        slug="alpha",
        name="CRI Alpha",
        status="active",
        whatsapp_config={"phone_number_id": "111", "access_token": "tok_alpha"},
    )


@pytest.fixture
def tenant_beta() -> TenantContext:
    return TenantContext(
        id=TENANT_BETA_ID,
        slug="beta",
        name="CRI Beta",
        status="active",
        whatsapp_config={"phone_number_id": "222", "access_token": "tok_beta"},
    )
