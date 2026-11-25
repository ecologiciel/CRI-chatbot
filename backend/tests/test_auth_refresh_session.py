"""Refresh must restore the active session without reviving an older login."""

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthenticationError
from app.services.auth.jwt import JWTManager
from app.services.auth.service import AuthService
from app.services.auth.session_manager import SessionManager


@pytest.mark.asyncio
async def test_bound_refresh_rotates_session_and_rejects_replay_and_old_login():
    test_redis_url = os.getenv("RAG_AUTH_TEST_REDIS_URL")
    if test_redis_url:
        from redis.asyncio import from_url

        redis = from_url(test_redis_url, decode_responses=True)
    else:
        fakeredis = pytest.importorskip("fakeredis.aioredis")
        pytest.importorskip("lupa")
        redis = fakeredis.FakeRedis(decode_responses=True)
    admin = MagicMock(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    admin.role.value = "admin_tenant"
    db = AsyncMock()
    db.__aenter__.return_value = db
    db.execute.return_value = MagicMock(scalar_one_or_none=lambda: admin)
    settings = MagicMock(
        jwt_secret_key="a-test-secret-with-more-than-32-bytes",
        jwt_algorithm="HS256",
        jwt_access_token_expire_minutes=30,
        jwt_refresh_token_expire_days=7,
    )
    manager = SessionManager(redis)
    ip = "192.0.2.1"
    sid = str(uuid.uuid4())
    with (
        patch("app.services.auth.jwt.get_settings", return_value=settings),
        patch("app.services.auth.jwt.get_redis", return_value=redis),
        patch("app.services.auth.service.get_settings", return_value=settings),
        patch("app.services.auth.service.get_redis", return_value=redis),
        patch("app.services.auth.service.get_session_factory", return_value=lambda: db),
        patch("app.services.auth.session_manager.get_settings", return_value=settings),
    ):
        _, original_jti = JWTManager.create_access_token(
            admin.id, admin.role.value, admin.tenant_id
        )
        await manager.register_session(str(admin.id), original_jti, ip, refresh_session_id=sid)
        refresh, _ = await JWTManager.create_refresh_token(admin.id, session_id=sid)
        service = AuthService()

        # Exactly one concurrent use can rotate the same refresh token.
        results = await asyncio.gather(
            service.refresh_token(refresh, ip),
            service.refresh_token(refresh, ip),
            return_exceptions=True,
        )
        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, AuthenticationError)]
        assert len(successes) == len(failures) == 1
        new_jti = JWTManager.verify_token(successes[0].access_token)["jti"]
        assert await manager.validate_session(str(admin.id), new_jti, ip)
        assert not await manager.validate_session(str(admin.id), original_jti, ip)

        # An unexpected IP cannot take over the session.
        with pytest.raises(AuthenticationError):
            await service.refresh_token(successes[0].refresh_token, "192.0.2.2")
        assert await manager.validate_session(str(admin.id), new_jti, ip)

        # A later login supersedes all refresh tokens from the old login.
        await manager.register_session(str(admin.id), "new-login", ip, refresh_session_id="new-sid")
        with pytest.raises(AuthenticationError):
            await service.refresh_token(successes[0].refresh_token, ip)
        assert await manager.validate_session(str(admin.id), "new-login", ip)

        fresh_refresh, _ = await JWTManager.create_refresh_token(admin.id, session_id="new-sid")
        await manager.invalidate_session(str(admin.id))
        with pytest.raises(AuthenticationError):
            await service.refresh_token(fresh_refresh, ip)
    await redis.aclose()
