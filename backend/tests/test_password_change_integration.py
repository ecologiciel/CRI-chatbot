"""Password changes serialize with logins and revoke sessions on real services."""

import asyncio
import os
import uuid
from unittest.mock import MagicMock, patch

import pytest
from redis.asyncio import from_url
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import AuthenticationError, ValidationError
from app.models.admin import Admin
from app.models.enums import AdminRole
from app.models.tenant import Tenant  # noqa: F401 — registers the referenced table
from app.services.auth.jwt import JWTManager
from app.services.auth.service import AuthService
from app.services.auth.session_manager import SessionManager


@pytest.mark.asyncio
async def test_password_change_revokes_sessions_and_serializes_with_login():
    dsn = os.getenv("AUTH_PASSWORD_TEST_DSN")
    redis_url = os.getenv("RAG_AUTH_TEST_REDIS_URL")
    if not dsn:
        pytest.skip("Requires an isolated auth_password_test PostgreSQL database")
    engine = create_async_engine(dsn)
    if redis_url:
        redis = from_url(redis_url, decode_responses=True)
    else:
        fakeredis = pytest.importorskip("fakeredis.aioredis")
        pytest.importorskip("lupa")
        redis = fakeredis.FakeRedis(decode_responses=True)
    manager = SessionManager(redis)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    admin_id = uuid.uuid4()
    email = f"auth-test-{admin_id.hex}@example.com"
    old_password, new_password = "Old-Only-Test1!", "New-Only-Test2!"
    settings = MagicMock(
        jwt_secret_key="isolated-test-key-with-at-least-32-bytes",
        jwt_algorithm="HS256",
        jwt_access_token_expire_minutes=30,
        jwt_refresh_token_expire_days=7,
    )
    known_jtis = []
    safe_database = False
    admin_created = False
    try:
        async with engine.begin() as connection:
            assert (
                await connection.execute(text("SELECT current_database()"))
            ).scalar_one() == "auth_password_test"
            safe_database = True
            # Only the referenced tenant primary key is needed by this isolated
            # authentication test; no tenant records or provisioning occur.
            await connection.execute(
                text("CREATE TABLE IF NOT EXISTS public.tenants (id uuid PRIMARY KEY)")
            )
            await connection.run_sync(lambda conn: Admin.__table__.create(conn, checkfirst=True))
        async with factory() as session:
            session.add(
                Admin(
                    id=admin_id,
                    email=email,
                    full_name="Test",
                    role=AdminRole.super_admin,
                    password_hash=AuthService.hash_password(old_password),
                )
            )
            await session.commit()
            admin_created = True

        with (
            patch("app.services.auth.service.get_session_factory", return_value=factory),
            patch("app.services.auth.service.get_redis", return_value=redis),
            patch("app.services.auth.jwt.get_redis", return_value=redis),
            patch("app.services.auth.service.get_settings", return_value=settings),
            patch("app.services.auth.jwt.get_settings", return_value=settings),
            patch("app.services.auth.session_manager.get_settings", return_value=settings),
            patch("app.services.auth.session_manager.get_session_manager", return_value=manager),
        ):
            service = AuthService()
            ip = "192.0.2.9"
            initial = await service.login(email, old_password, ip)
            known_jtis.extend(
                [
                    JWTManager.verify_token(initial.access_token)["jti"],
                    JWTManager.verify_token(initial.refresh_token)["jti"],
                ]
            )
            with pytest.raises(ValidationError):
                await service.change_password(admin_id, "incorrect", new_password)
            with pytest.raises(ValidationError):
                await service.change_password(admin_id, old_password, old_password)
            await service.verify_access_token(initial.access_token, ip)

            # Hold a login inside registration while it owns the DB row lock.
            # The change must wait, then invalidate that just-created session.
            entered, release = asyncio.Event(), asyncio.Event()
            original_register = manager.register_session

            async def delayed_register(*args, **kwargs):
                entered.set()
                await release.wait()
                return await original_register(*args, **kwargs)

            with patch.object(manager, "register_session", side_effect=delayed_register):
                login_task = asyncio.create_task(service.login(email, old_password, ip))
                await asyncio.wait_for(entered.wait(), timeout=10)
                change_task = asyncio.create_task(
                    service.change_password(admin_id, old_password, new_password)
                )
                await asyncio.sleep(0.2)
                assert not change_task.done()
                release.set()
                concurrent_login, _ = await asyncio.wait_for(
                    asyncio.gather(login_task, change_task), timeout=15
                )
            known_jtis.extend(
                [
                    JWTManager.verify_token(concurrent_login.access_token)["jti"],
                    JWTManager.verify_token(concurrent_login.refresh_token)["jti"],
                ]
            )
            with pytest.raises(AuthenticationError):
                await service.verify_access_token(concurrent_login.access_token, ip)
            with pytest.raises(AuthenticationError):
                await service.refresh_token(concurrent_login.refresh_token, ip)
            with pytest.raises(AuthenticationError):
                await service.login(email, old_password, ip)
            fresh = await service.login(email, new_password, ip)
            known_jtis.extend(
                [
                    JWTManager.verify_token(fresh.access_token)["jti"],
                    JWTManager.verify_token(fresh.refresh_token)["jti"],
                ]
            )
            await service.verify_access_token(fresh.access_token, ip)

            # Failure to revoke in Redis must leave the stored password intact.
            with patch.object(
                manager, "invalidate_session", side_effect=ConnectionError("redis unavailable")
            ):
                with pytest.raises(ConnectionError):
                    await service.change_password(admin_id, new_password, "Another-Test3!")
            async with factory() as session:
                stored_hash = (
                    await session.execute(select(Admin.password_hash).where(Admin.id == admin_id))
                ).scalar_one()
            assert AuthService.verify_password(new_password, stored_hash)

            # Conversely, a login started while the change owns the lock
            # cannot authenticate using the soon-to-be-obsolete password.
            entered, release = asyncio.Event(), asyncio.Event()
            original_invalidate = manager.invalidate_session

            async def delayed_invalidate(*args, **kwargs):
                entered.set()
                await release.wait()
                return await original_invalidate(*args, **kwargs)

            with patch.object(manager, "invalidate_session", side_effect=delayed_invalidate):
                change_task = asyncio.create_task(
                    service.change_password(admin_id, new_password, "Another-Test3!")
                )
                await asyncio.wait_for(entered.wait(), timeout=10)
                login_task = asyncio.create_task(service.login(email, new_password, ip))
                await asyncio.sleep(0.2)
                assert not login_task.done()
                release.set()
                await asyncio.wait_for(change_task, timeout=15)
                with pytest.raises(AuthenticationError):
                    await asyncio.wait_for(login_task, timeout=15)
    finally:
        if safe_database and admin_created:
            async with factory() as session:
                await session.execute(delete(Admin).where(Admin.id == admin_id))
                await session.commit()
        keys = [
            f"auth:session:{admin_id}:{suffix}"
            for suffix in ("active", "ip", "last_login", "refresh_session", "refresh_ip")
        ]
        keys += [f"auth:login_attempts:{email}", f"auth:lockout:{email}"]
        keys += [
            key
            for jti in known_jtis
            for key in (f"auth:refresh_token:{jti}", f"auth:revoked:{jti}")
        ]
        await redis.delete(*keys)
        await redis.aclose()
        await engine.dispose()
