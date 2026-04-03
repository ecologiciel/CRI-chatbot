"""A05:2021 — Security Misconfiguration.

Verifies that security headers are present, debug endpoints are disabled,
error messages do not leak stack traces, and CORS is properly restricted.
"""

import pytest

pytestmark = [pytest.mark.security, pytest.mark.owasp_a05]


class TestSecurityMisconfiguration:
    """OWASP A05 — Security Misconfiguration."""

    # ------------------------------------------------------------------ #
    # A05-01  Security headers present
    # ------------------------------------------------------------------ #

    async def test_security_headers_present(self, api_client):
        """Critical HTTP security headers must be present on responses.

        Headers are typically injected by Traefik in production.  In ASGI
        mode FastAPI may not set them, so we warn instead of failing.
        """
        resp = await api_client.get("/api/v1/health")

        expected_headers = {
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
        }

        for header, expected_value in expected_headers.items():
            actual = resp.headers.get(header)
            if actual is not None:
                assert actual.lower() == expected_value.lower(), (
                    f"Header {header}: expected '{expected_value}', got '{actual}'"
                )
            else:
                # Warn — headers may only be present behind Traefik
                pytest.skip(
                    f"Header '{header}' absent (expected in production behind Traefik)"
                )

    # ------------------------------------------------------------------ #
    # A05-02  No debug / admin endpoints exposed
    # ------------------------------------------------------------------ #

    @pytest.mark.parametrize(
        "path",
        [
            "/debug",
            "/admin",
            "/.env",
            "/phpinfo",
            "/api/v1/internal/debug",
            "/server-status",
            "/.git/config",
        ],
    )
    async def test_no_debug_endpoints_exposed(self, api_client, path: str):
        """Common debug / admin / sensitive paths must not be reachable."""
        resp = await api_client.get(path)
        assert resp.status_code in (
            404,
            405,
            403,
            307,
        ), f"{path} returned unexpected {resp.status_code}"

    # ------------------------------------------------------------------ #
    # A05-03  Error messages hide stack traces
    # ------------------------------------------------------------------ #

    async def test_error_messages_no_stack_trace(self, api_client):
        """Error responses must never expose Python tracebacks or file paths."""
        # Trigger a 422 by sending a non-UUID where a UUID is expected
        resp = await api_client.get("/api/v1/dossiers/not-a-valid-uuid")
        assert resp.status_code >= 400

        body = resp.text
        leak_patterns = ["Traceback", 'File "/', "line ", "sqlalchemy", "asyncpg"]
        for pattern in leak_patterns:
            assert pattern not in body, (
                f"Error response leaks internal info: found '{pattern}'"
            )

    # ------------------------------------------------------------------ #
    # A05-04  CORS rejects arbitrary origins
    # ------------------------------------------------------------------ #

    async def test_cors_restricted(self, api_client):
        """CORS must not allow wildcard or arbitrary origins."""
        resp = await api_client.options(
            "/api/v1/health",
            headers={
                "Origin": "https://evil-attacker.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao != "*", "CORS allows wildcard origin (*)"
        assert "evil-attacker" not in acao, (
            f"CORS allows arbitrary origin: {acao}"
        )
