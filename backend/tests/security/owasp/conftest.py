"""Shared fixtures for OWASP penetration tests.

Provides a dual-mode HTTP client (ASGI in-process or real HTTP against staging),
authenticated client fixtures for each role, and helper utilities.

Environment variables (all optional, with defaults for ASGI/CI mode):
    TEST_API_URL            — Staging base URL. Empty = ASGI mode (default).
    TEST_ADMIN_A_EMAIL      — Tenant A admin_tenant email.
    TEST_ADMIN_A_PASSWORD   — Tenant A admin_tenant password.
    TEST_TENANT_A_SLUG      — Tenant A slug identifier.
    TEST_TENANT_A_ID        — Tenant A UUID for X-Tenant-ID header.
    TEST_ADMIN_B_EMAIL      — Tenant B admin_tenant email.
    TEST_ADMIN_B_PASSWORD   — Tenant B admin_tenant password.
    TEST_TENANT_B_SLUG      — Tenant B slug identifier.
    TEST_TENANT_B_ID        — Tenant B UUID for X-Tenant-ID header.
    TEST_VIEWER_EMAIL       — Viewer role email (tenant A).
    TEST_VIEWER_PASSWORD    — Viewer role password.
    TEST_SUPER_ADMIN_EMAIL  — Super-admin email.
    TEST_SUPER_ADMIN_PASSWORD — Super-admin password.
"""

import os
import uuid

# Env vars must be set BEFORE importing app (triggers Settings())
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("REDIS_PASSWORD", "test-password")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-owasp")

import httpx
import pytest
from httpx import ASGITransport

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STAGING_URL: str = os.environ.get("TEST_API_URL", "")

TENANT_A_SLUG = os.environ.get("TEST_TENANT_A_SLUG", "test-tenant-a")
TENANT_A_ID = os.environ.get("TEST_TENANT_A_ID", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B_SLUG = os.environ.get("TEST_TENANT_B_SLUG", "test-tenant-b")
TENANT_B_ID = os.environ.get("TEST_TENANT_B_ID", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

ADMIN_A_EMAIL = os.environ.get("TEST_ADMIN_A_EMAIL", "admin-a@test.cri.ma")
ADMIN_A_PASSWORD = os.environ.get("TEST_ADMIN_A_PASSWORD", "TestAdmin123!")
ADMIN_B_EMAIL = os.environ.get("TEST_ADMIN_B_EMAIL", "admin-b@test.cri.ma")
ADMIN_B_PASSWORD = os.environ.get("TEST_ADMIN_B_PASSWORD", "TestAdmin123!")
VIEWER_EMAIL = os.environ.get("TEST_VIEWER_EMAIL", "viewer@test.cri.ma")
VIEWER_PASSWORD = os.environ.get("TEST_VIEWER_PASSWORD", "ViewerPass123!")
SUPER_ADMIN_EMAIL = os.environ.get("TEST_SUPER_ADMIN_EMAIL", "superadmin@test.cri.ma")
SUPER_ADMIN_PASSWORD = os.environ.get("TEST_SUPER_ADMIN_PASSWORD", "SuperAdmin123!")


def is_asgi_mode() -> bool:
    """Return True when tests run in-process (no staging URL configured)."""
    return not STAGING_URL


def requires_staging(reason: str = "Requires live infrastructure (Redis/PostgreSQL)"):
    """Marker to skip tests that need a real staging server."""
    return pytest.mark.skipif(is_asgi_mode(), reason=reason)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def auth_headers(token: str, tenant_id: str | None = None) -> dict[str, str]:
    """Build Authorization + optional X-Tenant-ID headers."""
    headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    return headers


async def _login(client: httpx.AsyncClient, email: str, password: str) -> dict:
    """Perform login and return the full token response dict.

    Returns an empty dict on failure so fixtures can handle gracefully.
    """
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    if resp.status_code == 200:
        return resp.json()
    return {}


# ---------------------------------------------------------------------------
# Core client fixture — dual-mode
# ---------------------------------------------------------------------------


@pytest.fixture
async def api_client():
    """Unauthenticated async HTTP client (ASGI or staging)."""
    if is_asgi_mode():
        from app.main import app

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            timeout=30.0,
        ) as client:
            yield client
    else:
        async with httpx.AsyncClient(
            base_url=STAGING_URL,
            timeout=30.0,
        ) as client:
            yield client


# ---------------------------------------------------------------------------
# Authenticated client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def admin_token_a(api_client: httpx.AsyncClient) -> str:
    """Access token for tenant A admin_tenant."""
    data = await _login(api_client, ADMIN_A_EMAIL, ADMIN_A_PASSWORD)
    token = data.get("access_token", "")
    if not token:
        pytest.skip("Tenant A admin login failed — seed data missing?")
    return token


@pytest.fixture
async def admin_token_b(api_client: httpx.AsyncClient) -> str:
    """Access token for tenant B admin_tenant."""
    data = await _login(api_client, ADMIN_B_EMAIL, ADMIN_B_PASSWORD)
    token = data.get("access_token", "")
    if not token:
        pytest.skip("Tenant B admin login failed — seed data missing?")
    return token


@pytest.fixture
async def viewer_token(api_client: httpx.AsyncClient) -> str:
    """Access token for viewer role (tenant A)."""
    data = await _login(api_client, VIEWER_EMAIL, VIEWER_PASSWORD)
    token = data.get("access_token", "")
    if not token:
        pytest.skip("Viewer login failed — seed data missing?")
    return token


@pytest.fixture
async def super_admin_token(api_client: httpx.AsyncClient) -> str:
    """Access token for super_admin role."""
    data = await _login(api_client, SUPER_ADMIN_EMAIL, SUPER_ADMIN_PASSWORD)
    token = data.get("access_token", "")
    if not token:
        pytest.skip("Super-admin login failed — seed data missing?")
    return token


@pytest.fixture
async def admin_client_a(api_client: httpx.AsyncClient, admin_token_a: str):
    """Authenticated client with tenant A admin_tenant headers pre-set."""
    api_client.headers.update(auth_headers(admin_token_a, TENANT_A_ID))
    yield api_client


@pytest.fixture
async def admin_client_b(api_client: httpx.AsyncClient, admin_token_b: str):
    """Authenticated client with tenant B admin_tenant headers pre-set."""
    api_client.headers.update(auth_headers(admin_token_b, TENANT_B_ID))
    yield api_client


@pytest.fixture
async def viewer_client(api_client: httpx.AsyncClient, viewer_token: str):
    """Authenticated client with viewer role (tenant A)."""
    api_client.headers.update(auth_headers(viewer_token, TENANT_A_ID))
    yield api_client


@pytest.fixture
async def super_admin_client(api_client: httpx.AsyncClient, super_admin_token: str):
    """Authenticated client with super_admin role (no tenant header)."""
    api_client.headers.update(auth_headers(super_admin_token))
    yield api_client


# ---------------------------------------------------------------------------
# Utility fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def random_uuid() -> str:
    """A fresh random UUID string for idempotent tests."""
    return str(uuid.uuid4())
