"""A01:2021 — Broken Access Control.

Verifies RBAC enforcement, cross-tenant isolation, IDOR protection,
and anti-BOLA controls across the API surface.
"""

import uuid

import pytest

from .conftest import TENANT_A_ID, TENANT_B_ID, auth_headers

pytestmark = [pytest.mark.security, pytest.mark.owasp_a01]


class TestBrokenAccessControl:
    """OWASP A01 — Broken Access Control."""

    # ------------------------------------------------------------------ #
    # A01-01  Vertical privilege escalation: viewer → admin
    # ------------------------------------------------------------------ #

    async def test_privilege_escalation_viewer_to_admin(
        self, api_client, viewer_token
    ):
        """A viewer must NOT access admin-only endpoints (import, tenant mgmt)."""
        headers = auth_headers(viewer_token, TENANT_A_ID)

        # POST /dossiers/import requires admin_tenant or super_admin
        resp = await api_client.post(
            "/api/v1/dossiers/import",
            headers=headers,
            files={"file": ("test.csv", b"col1,col2\na,b", "text/csv")},
        )
        assert resp.status_code == 403, (
            f"Viewer accessed admin endpoint: {resp.status_code}"
        )

    # ------------------------------------------------------------------ #
    # A01-02  Vertical privilege escalation: admin_tenant → super_admin
    # ------------------------------------------------------------------ #

    async def test_privilege_escalation_admin_to_superadmin(
        self, api_client, admin_token_a
    ):
        """An admin_tenant must NOT access super_admin-only endpoints."""
        headers = auth_headers(admin_token_a, TENANT_A_ID)

        # GET /tenants is super_admin only
        resp = await api_client.get("/api/v1/tenants/", headers=headers)
        assert resp.status_code == 403, (
            f"admin_tenant accessed super_admin endpoint: {resp.status_code}"
        )

    # ------------------------------------------------------------------ #
    # A01-03  Cross-tenant data access (horizontal isolation)
    # ------------------------------------------------------------------ #

    async def test_cross_tenant_data_access(self, api_client, admin_token_a):
        """Tenant A admin must NOT access tenant B data by swapping
        the X-Tenant-ID header.
        """
        # Use tenant A's token but tenant B's X-Tenant-ID
        headers = auth_headers(admin_token_a, TENANT_B_ID)

        resp = await api_client.get("/api/v1/dossiers", headers=headers)
        # Middleware should reject the mismatch (403) or tenant B won't resolve (404)
        assert resp.status_code in (400, 403, 404), (
            f"Cross-tenant access not blocked: {resp.status_code}"
        )

    # ------------------------------------------------------------------ #
    # A01-04  IDOR — unauthenticated direct object reference
    # ------------------------------------------------------------------ #

    async def test_idor_unauthenticated_dossier(self, api_client, random_uuid):
        """Direct access to a dossier by ID without auth must return 401."""
        resp = await api_client.get(f"/api/v1/dossiers/{random_uuid}")
        # Missing auth → 401, or missing X-Tenant-ID → 400
        assert resp.status_code in (400, 401), (
            f"Unauthenticated IDOR not blocked: {resp.status_code}"
        )

    # ------------------------------------------------------------------ #
    # A01-05  BOLA — dossier ID enumeration returns 404, not 500
    # ------------------------------------------------------------------ #

    async def test_bola_dossier_id_enumeration(
        self, api_client, admin_token_a
    ):
        """Requesting a non-existent dossier ID must return 404 (not 500 or
        data from another tenant).
        """
        headers = auth_headers(admin_token_a, TENANT_A_ID)
        fabricated_id = str(uuid.uuid4())

        resp = await api_client.get(
            f"/api/v1/dossiers/{fabricated_id}", headers=headers
        )
        assert resp.status_code in (404, 422), (
            f"Dossier enumeration returned unexpected {resp.status_code}"
        )
        # Ensure no data leak
        if resp.status_code == 200:
            pytest.fail("Non-existent dossier returned 200 — possible BOLA")

    # ------------------------------------------------------------------ #
    # A01-06  Horizontal escalation — admin cannot see other tenant config
    # ------------------------------------------------------------------ #

    async def test_no_horizontal_privilege_escalation(
        self, api_client, admin_token_a
    ):
        """admin_tenant A listing dossiers must only return tenant A data.

        We verify the response does not reference tenant B identifiers.
        """
        headers = auth_headers(admin_token_a, TENANT_A_ID)

        resp = await api_client.get("/api/v1/dossiers", headers=headers)
        if resp.status_code == 200:
            body = resp.text
            # Ensure tenant B slug or ID doesn't appear in the response
            assert TENANT_B_ID not in body, (
                "Tenant B ID found in tenant A's dossier listing"
            )
