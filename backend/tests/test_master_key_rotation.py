"""Rewrapping preserves data keys and fails closed on any damaged envelope."""

import asyncio
import os
import secrets
import sys
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.services.crypto.master_key_rotation import rewrap_key_blobs


def _wrap(master: bytes, data_key: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(master).encrypt(nonce, data_key, None)


def _unwrap(master: bytes, blob: bytes) -> bytes:
    return AESGCM(master).decrypt(blob[:12], blob[12:], None)


def test_rewrap_preserves_each_data_key_and_changes_envelopes():
    old, new = secrets.token_bytes(32), secrets.token_bytes(32)
    data_keys = [secrets.token_bytes(32), secrets.token_bytes(32)]
    originals = [_wrap(old, key) for key in data_keys]
    result = rewrap_key_blobs(originals, old, new)
    assert [_unwrap(new, blob) for blob in result] == data_keys
    assert all(a != b for a, b in zip(originals, result, strict=True))
    assert [_unwrap(old, blob) for blob in originals] == data_keys


@pytest.mark.parametrize("reason", ["invalid_key", "same_key", "empty", "wrong_key", "damaged"])
def test_rewrap_rejects_invalid_inputs(reason):
    old, new = secrets.token_bytes(32), secrets.token_bytes(32)
    blobs = [_wrap(old, secrets.token_bytes(32)), _wrap(old, secrets.token_bytes(32))]
    if reason == "invalid_key":
        new = b"short"
    elif reason == "same_key":
        new = old
    elif reason == "empty":
        blobs = []
    elif reason == "wrong_key":
        old = secrets.token_bytes(32)
    else:
        blobs[1] = blobs[1][:-1] + bytes([blobs[1][-1] ^ 1])
    with pytest.raises(ValueError):
        rewrap_key_blobs(blobs, old, new)


@pytest.mark.asyncio
async def test_postgres_transaction_rewraps_all_versions_and_rolls_back_on_damage(tmp_path):
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.models  # noqa: F401 — register relationships for ORM configuration
    from app.models.tenant import Tenant
    from app.models.tenant_key import TenantKey
    from app.services.crypto.master_key_coordinator import (
        _env_key,
        _journal_key,
        apply_rotation,
        finalize_rollback,
        finalize_rotation,
        prepare_rotation,
        rollback_rotation,
    )
    from app.services.crypto.master_key_rotation import rewrap_tenant_keys
    from app.services.crypto.startup_guard import assert_master_key_consistent

    dsn = os.getenv("KMS_ROTATION_TEST_DSN")
    if not dsn:
        pytest.skip("Requires a fresh disposable kms_rotation_test PostgreSQL database")
    engine = create_async_engine(dsn)
    created = False
    try:
        async with engine.begin() as conn:
            assert (
                await conn.execute(text("SELECT current_database()"))
            ).scalar_one() == "kms_rotation_test"
            assert (
                await conn.execute(text("SELECT to_regclass('public.tenants') IS NULL"))
            ).scalar_one()
            assert (
                await conn.execute(text("SELECT to_regclass('public.tenant_keys') IS NULL"))
            ).scalar_one()
            await conn.run_sync(Tenant.__table__.create)
            await conn.run_sync(TenantKey.__table__.create)
        created = True
        factory = async_sessionmaker(engine, expire_on_commit=False)
        old, new = secrets.token_bytes(32), secrets.token_bytes(32)
        active, historical = secrets.token_bytes(32), secrets.token_bytes(32)
        tenant_id = uuid.uuid4()
        async with factory.begin() as session:
            session.add(Tenant(id=tenant_id, slug="testrotation", name="Test", region="Test"))
            await session.flush()
            session.add_all(
                [
                    TenantKey(
                        tenant_id=tenant_id,
                        encrypted_key=_wrap(old, active),
                        key_version=2,
                        is_active=True,
                    ),
                    TenantKey(
                        tenant_id=tenant_id,
                        encrypted_key=_wrap(old, historical),
                        key_version=1,
                        is_active=False,
                    ),
                ]
            )
        await assert_master_key_consistent(factory, old)
        assert await rewrap_tenant_keys(factory, old, new) == 2
        with pytest.raises(RuntimeError, match="Tenant key validation failed"):
            await assert_master_key_consistent(factory, old)
        await assert_master_key_consistent(factory, new)
        async with factory() as session:
            rows = list(
                (await session.execute(select(TenantKey).order_by(TenantKey.key_version))).scalars()
            )
            assert [_unwrap(new, row.encrypted_key) for row in rows] == [historical, active]
            before = [bytes(row.encrypted_key) for row in rows]
        with pytest.raises(ValueError):
            await rewrap_tenant_keys(factory, old, secrets.token_bytes(32))
        async with factory() as session:
            rows = list(
                (await session.execute(select(TenantKey).order_by(TenantKey.key_version))).scalars()
            )
            assert [bytes(row.encrypted_key) for row in rows] == before

        env_path = tmp_path / ".env.demo"
        env_path.write_bytes(b"OTHER=unchanged\nKMS_MASTER_KEY=" + new.hex().encode() + b"\n")
        journal = tmp_path / "rotation-active"

        # Interrupted after the durable journal, before the database transaction.
        prepare_rotation(env_path, journal)
        await rollback_rotation(factory, env_path, journal)
        await finalize_rollback(factory, env_path, journal)
        assert _env_key(env_path) == new and not journal.exists()

        async def crash_after(code: str, expected: int) -> None:
            # Exit without Python cleanup to emulate a process disappearing after
            # a durable boundary. Only the disposable database and tmp_path are used.
            child_env = dict(os.environ)
            child_env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                code,
                str(env_path),
                str(journal),
                env=child_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, errors = await asyncio.wait_for(process.communicate(), timeout=30)
            assert process.returncode == expected, errors.decode(errors="replace")

        # Process disappears after committing the DB but before changing the file.
        prepare_rotation(env_path, journal)
        await crash_after(
            "import asyncio,os,sys; from pathlib import Path; import app.models; "
            "from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker; "
            "from app.services.crypto.master_key_coordinator import _journal_key; "
            "from app.services.crypto.master_key_rotation import rewrap_tenant_keys; "
            "j=Path(sys.argv[2]); f=async_sessionmaker(create_async_engine(os.environ['KMS_ROTATION_TEST_DSN'])); "
            "asyncio.run(rewrap_tenant_keys(f,_journal_key(j,'old.key'),_journal_key(j,'new.key'))); os._exit(71)",
            71,
        )
        with pytest.raises(RuntimeError, match="Tenant key validation failed"):
            await assert_master_key_consistent(factory, new)
        # A process can also disappear after writing the next environment
        # file but before its atomic rename. Recovery owns this exact path.
        (journal / "env.next").write_bytes(b"incomplete temporary configuration")
        await rollback_rotation(factory, env_path, journal)
        await finalize_rollback(factory, env_path, journal)
        assert _env_key(env_path) == new and not journal.exists()
        await assert_master_key_consistent(factory, new)

        # Process disappears after the file switch; rollback remains idempotent.
        prepare_rotation(env_path, journal)
        await crash_after(
            "import asyncio,os,sys; from pathlib import Path; import app.models; "
            "from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker; "
            "from app.services.crypto.master_key_coordinator import apply_rotation; "
            "f=async_sessionmaker(create_async_engine(os.environ['KMS_ROTATION_TEST_DSN'])); "
            "asyncio.run(apply_rotation(f,Path(sys.argv[1]),Path(sys.argv[2]))); os._exit(72)",
            72,
        )
        await rollback_rotation(factory, env_path, journal)
        await rollback_rotation(factory, env_path, journal)
        await finalize_rollback(factory, env_path, journal)
        assert _env_key(env_path) == new and not journal.exists()

        # Successful switch followed by interrupted journal cleanup.
        prepare_rotation(env_path, journal)
        candidate = _journal_key(journal, "new.key")
        assert await apply_rotation(factory, env_path, journal) == 2
        (journal / "COMMITTED").write_text("1\n", encoding="ascii")
        (journal / "old.key").unlink()
        await finalize_rotation(factory, env_path, journal)
        assert _env_key(env_path) == candidate and not journal.exists()
        assert env_path.read_bytes().startswith(b"OTHER=unchanged\n")
        new = candidate
        async with factory() as session:
            rows = list(
                (await session.execute(select(TenantKey).order_by(TenantKey.key_version))).scalars()
            )
            assert [_unwrap(new, row.encrypted_key) for row in rows] == [historical, active]
            before = [bytes(row.encrypted_key) for row in rows]
        async with factory.begin() as session:
            rows = list(
                (await session.execute(select(TenantKey).order_by(TenantKey.key_version))).scalars()
            )
            rows[1].encrypted_key = before[1][:-1] + bytes([before[1][-1] ^ 1])
        with pytest.raises(ValueError, match="could not be authenticated"):
            await rewrap_tenant_keys(factory, new, secrets.token_bytes(32))
        async with factory() as session:
            rows = list(
                (await session.execute(select(TenantKey).order_by(TenantKey.key_version))).scalars()
            )
            assert bytes(rows[0].encrypted_key) == before[0]
    finally:
        if created:
            async with engine.begin() as conn:
                await conn.run_sync(TenantKey.__table__.drop)
                await conn.run_sync(Tenant.__table__.drop)
        await engine.dispose()


def test_startup_guard_authenticates_all_envelopes_without_revealing_them():
    from app.services.crypto.startup_guard import validate_envelopes

    master = secrets.token_bytes(32)
    valid = _wrap(master, secrets.token_bytes(32))
    validate_envelopes(master, [])
    validate_envelopes(master, [(valid, "AES-256-GCM")])
    for key, rows in [
        (secrets.token_bytes(32), [(valid, "AES-256-GCM")]),
        (master, [(valid[:-1], "AES-256-GCM")]),
        (master, [(valid, "unsupported")]),
    ]:
        with pytest.raises(RuntimeError, match="Tenant key validation failed") as error:
            validate_envelopes(key, rows)
        assert valid.hex() not in str(error.value)
    with pytest.raises(RuntimeError, match="Invalid KMS"):
        validate_envelopes(b"short", [])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "worker",
    ["archive", "campaign", "import_dossier", "ingestion", "learning", "notification", "purge"],
)
async def test_workers_stop_before_connecting_when_kms_check_fails(monkeypatch, worker):
    import importlib
    from unittest.mock import AsyncMock, Mock

    import app.core.database
    import app.core.logging
    import app.core.redis
    import app.services.crypto.startup_guard

    monkeypatch.setattr(app.core.database, "get_engine", Mock())
    monkeypatch.setattr(app.core.logging, "setup_logging", Mock())
    redis = AsyncMock()
    monkeypatch.setattr(app.core.redis, "init_redis", redis)
    monkeypatch.setattr(
        app.services.crypto.startup_guard,
        "verify_kms_on_startup",
        AsyncMock(side_effect=RuntimeError("invalid KMS")),
    )
    with pytest.raises(RuntimeError, match="invalid KMS"):
        await importlib.import_module(f"app.workers.{worker}").startup({})
    redis.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_does_not_start_if_kms_check_fails(monkeypatch):
    from unittest.mock import AsyncMock, Mock

    import app.main
    import app.services.crypto.startup_guard

    monkeypatch.setattr(app.main, "get_engine", Mock())
    monkeypatch.setattr(app.main, "setup_logging", Mock())
    redis = AsyncMock()
    monkeypatch.setattr(app.main, "init_redis", redis)
    monkeypatch.setattr(
        app.services.crypto.startup_guard,
        "verify_kms_on_startup",
        AsyncMock(side_effect=RuntimeError("invalid KMS")),
    )
    with pytest.raises(RuntimeError, match="invalid KMS"):
        async with app.main.lifespan(app.main.app):
            pytest.fail("the API must not start")
    redis.assert_not_awaited()
