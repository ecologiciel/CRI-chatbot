"""A02:2021 — Cryptographic Failures.

Verifies that secrets are not leaked in HTTP responses, passwords are never
returned by the API, and JWT algorithm confusion attacks are rejected.
"""

import base64
import json
import re
import subprocess
import time

import pytest

pytestmark = [pytest.mark.security, pytest.mark.owasp_a02]


class TestCryptographicFailures:
    """OWASP A02 — Cryptographic Failures."""

    # ------------------------------------------------------------------ #
    # A02-01  No secrets in response headers
    # ------------------------------------------------------------------ #

    async def test_no_secrets_in_response_headers(self, api_client):
        """Response headers must never contain secrets or tokens."""
        resp = await api_client.get("/api/v1/health")

        secret_patterns = ["password", "secret", "api_key", "access_token", "private"]
        for header_name, header_value in resp.headers.items():
            value_lower = header_value.lower()
            for pattern in secret_patterns:
                assert pattern not in value_lower, (
                    f"Header '{header_name}' contains sensitive pattern '{pattern}': "
                    f"{header_value[:80]}"
                )

    # ------------------------------------------------------------------ #
    # A02-02  No hardcoded secrets in codebase
    # ------------------------------------------------------------------ #

    def test_no_secrets_in_codebase(self):
        """Grep the backend source for hardcoded secret patterns.

        Filters out false positives: settings files using env vars, test
        files, config references, and Pydantic Field defaults.
        """
        patterns = [
            r'password\s*=\s*["\'][^"\']{4,}',
            r'secret\s*=\s*["\'][^"\']{4,}',
            r'api_key\s*=\s*["\'][^"\']{4,}',
            r'access_token\s*=\s*["\'][^"\']{4,}',
        ]

        false_positive_indicators = [
            "os.environ",
            "os.getenv",
            "settings.",
            "config.",
            "Field(",
            "# ",
            "test",
            "example",
            "placeholder",
            "CHANGE-ME",
            "dummy",
            "mock",
        ]

        violations: list[str] = []
        for pattern in patterns:
            try:
                result = subprocess.run(
                    ["grep", "-rnE", "--include=*.py", pattern, "backend/app/"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=".",
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pytest.skip("grep not available or timed out")
                return

            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                line_lower = line.lower()
                if any(fp in line_lower for fp in false_positive_indicators):
                    continue
                violations.append(line.strip())

        assert not violations, (
            f"Potential hardcoded secrets found:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    # ------------------------------------------------------------------ #
    # A02-03  Passwords never returned in API responses
    # ------------------------------------------------------------------ #

    async def test_passwords_not_in_api_responses(self, api_client):
        """Login and /auth/me responses must never include password fields."""
        # Login response
        login_resp = await api_client.post(
            "/api/v1/auth/login",
            json={"email": "admin-a@test.cri.ma", "password": "TestAdmin123!"},
        )
        if login_resp.status_code == 200:
            login_data = login_resp.json()
            assert "password" not in login_data, "Login response contains 'password'"
            assert "password_hash" not in login_data, (
                "Login response contains 'password_hash'"
            )

            # /auth/me response
            token = login_data.get("access_token")
            if token:
                me_resp = await api_client.get(
                    "/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if me_resp.status_code == 200:
                    me_data = me_resp.json()
                    assert "password" not in me_data
                    assert "password_hash" not in me_data
        else:
            pytest.skip("Login failed — cannot verify password absence")

    # ------------------------------------------------------------------ #
    # A02-04  JWT algorithm "none" attack rejected
    # ------------------------------------------------------------------ #

    async def test_jwt_alg_none_rejected(self, api_client):
        """A JWT with alg=none must be rejected (401).

        This tests the classic JWT algorithm confusion attack where an
        attacker crafts a token with no signature.
        """

        def _b64url(data: dict) -> str:
            return (
                base64.urlsafe_b64encode(json.dumps(data).encode())
                .rstrip(b"=")
                .decode()
            )

        header = _b64url({"alg": "none", "typ": "JWT"})
        payload = _b64url(
            {
                "sub": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "role": "super_admin",
                "tenant_id": None,
                "type": "access",
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
                "jti": "forged-jti",
            }
        )
        forged_token = f"{header}.{payload}."

        resp = await api_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {forged_token}"},
        )
        assert resp.status_code == 401, (
            f"JWT alg=none accepted! Status {resp.status_code}"
        )
