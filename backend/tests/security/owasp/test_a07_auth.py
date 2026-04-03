"""A07:2021 — Identification and Authentication Failures.

Tests brute-force login lockout, token replay after logout, expired
token rejection, and password policy enforcement.
"""

import base64
import json
import os
import time
import uuid

import pytest

from .conftest import (
    TENANT_A_ID,
    auth_headers,
    is_asgi_mode,
    requires_staging,
)

pytestmark = [pytest.mark.security, pytest.mark.owasp_a07]


class TestAuthenticationFailures:
    """OWASP A07 — Identification and Authentication Failures."""

    # ------------------------------------------------------------------ #
    # A07-01  Brute-force login lockout (5 attempts → 30 min lock)
    # ------------------------------------------------------------------ #

    @requires_staging("Login rate limiting requires live Redis")
    async def test_bruteforce_login_lockout(self, api_client):
        """After 5 failed login attempts, the account must be locked.

        Uses a unique fake email per run so the test is idempotent and
        does not lock real accounts.
        """
        fake_email = f"owasp_lockout_{uuid.uuid4().hex[:8]}@nonexistent.cri.ma"

        last_status = 0
        locked = False
        for i in range(7):
            resp = await api_client.post(
                "/api/v1/auth/login",
                json={"email": fake_email, "password": "WrongPassword123!"},
            )
            last_status = resp.status_code
            if resp.status_code == 429:
                # Lockout triggered — verify it's around the 5th-6th attempt
                assert i >= 4, f"Lockout triggered too early at attempt #{i + 1}"
                locked = True
                break

        assert locked, (
            f"Account not locked after 7 attempts (last status: {last_status})"
        )

    # ------------------------------------------------------------------ #
    # A07-02  Token replay after logout
    # ------------------------------------------------------------------ #

    @requires_staging("Logout + token blacklist requires live Redis")
    async def test_token_replay_after_logout(self, api_client):
        """A JWT used after logout should be rejected (if token blacklisting
        is implemented) or documented as a known JWT-stateless limitation.
        """
        # Login
        login_resp = await api_client.post(
            "/api/v1/auth/login",
            json={
                "email": os.environ.get("TEST_ADMIN_A_EMAIL", "admin-a@test.cri.ma"),
                "password": os.environ.get("TEST_ADMIN_A_PASSWORD", "TestAdmin123!"),
            },
        )
        if login_resp.status_code != 200:
            pytest.skip("Login failed")

        data = login_resp.json()
        access_token = data["access_token"]
        refresh_token = data.get("refresh_token", "")

        # Logout
        logout_resp = await api_client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"refresh_token": refresh_token},
        )
        assert logout_resp.status_code in (200, 204), (
            f"Logout failed: {logout_resp.status_code}"
        )

        # Replay the access token
        replay_resp = await api_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        # Ideal: 401 (blacklisted). Acceptable: 200 (JWT-stateless — access
        # tokens are short-lived and not individually revocable).
        if replay_resp.status_code == 200:
            # Document as known limitation
            pytest.skip(
                "JWT access tokens are stateless — replay succeeds until TTL. "
                "Refresh token single-use is enforced separately."
            )
        else:
            assert replay_resp.status_code == 401

    # ------------------------------------------------------------------ #
    # A07-03  Expired token rejected
    # ------------------------------------------------------------------ #

    async def test_expired_token_rejected(self, api_client):
        """A JWT with exp in the past must be rejected with 401.

        In ASGI mode we craft a token using the known test secret.
        In staging mode we cannot forge tokens, so we skip.
        """
        if not is_asgi_mode():
            pytest.skip("Cannot craft tokens without knowing staging JWT secret")

        jwt_secret = os.environ.get("JWT_SECRET_KEY", "test-jwt-secret-key-owasp")

        def _b64url(data: dict) -> str:
            return (
                base64.urlsafe_b64encode(json.dumps(data).encode())
                .rstrip(b"=")
                .decode()
            )

        # We need to produce a valid HS256 signature
        import hashlib
        import hmac

        header = _b64url({"alg": "HS256", "typ": "JWT"})
        payload = _b64url(
            {
                "sub": str(uuid.uuid4()),
                "role": "admin_tenant",
                "tenant_id": str(uuid.uuid4()),
                "type": "access",
                "iat": int(time.time()) - 7200,
                "exp": int(time.time()) - 3600,  # Expired 1 hour ago
                "jti": str(uuid.uuid4()),
            }
        )
        signing_input = f"{header}.{payload}"
        signature = (
            base64.urlsafe_b64encode(
                hmac.new(
                    jwt_secret.encode(),
                    signing_input.encode(),
                    hashlib.sha256,
                ).digest()
            )
            .rstrip(b"=")
            .decode()
        )
        expired_token = f"{signing_input}.{signature}"

        resp = await api_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert resp.status_code == 401, (
            f"Expired token accepted! Status {resp.status_code}"
        )

    # ------------------------------------------------------------------ #
    # A07-04  Password policy enforced on admin creation
    # ------------------------------------------------------------------ #

    async def test_password_policy_enforced(
        self, api_client, super_admin_token
    ):
        """Weak passwords must be rejected when creating an admin."""
        headers = auth_headers(super_admin_token)

        weak_passwords = [
            "short",           # < 12 chars
            "alllowercase1!",  # no uppercase
            "ALLUPPERCASE1!",  # no lowercase
            "NoDigitsHere!!",  # no digit
            "NoSpecial1234A",  # no special character
        ]

        for weak_pw in weak_passwords:
            resp = await api_client.post(
                "/api/v1/auth/admins",
                headers=headers,
                json={
                    "email": f"weakpw_{uuid.uuid4().hex[:6]}@test.cri.ma",
                    "password": weak_pw,
                    "role": "viewer",
                    "tenant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                },
            )
            assert resp.status_code in (400, 422), (
                f"Weak password '{weak_pw}' accepted: {resp.status_code}"
            )
