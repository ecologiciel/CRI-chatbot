"""Crash-recoverable coordination of a master rewrap and an environment file.

All application writers must be stopped externally before every operation.
The journal contains sensitive master keys and must live on a persistent,
access-restricted filesystem. Do not expose it in logs or backups unencrypted.
"""

from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.tenant_key import TenantKey
from app.services.crypto.master_key_rotation import rewrap_tenant_keys

_PREFIX = b"KMS_MASTER_KEY="
_KEY = re.compile(rb"^[0-9a-fA-F]{64}$")


def _sync_dir(path: Path) -> None:
    if os.name == "nt":  # Windows cannot open directories with os.open.
        return
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_dir(path.parent)


def _env_key(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("The environment path must be a regular file")
    matches = [
        line[len(_PREFIX) :] for line in path.read_bytes().splitlines() if line.startswith(_PREFIX)
    ]
    if len(matches) != 1 or not _KEY.fullmatch(matches[0]):
        raise ValueError("The environment must contain exactly one valid KMS master key")
    return bytes.fromhex(matches[0].decode("ascii"))


def _replace_env_key(
    path: Path, journal: Path, expected: tuple[bytes, ...], new_key: bytes
) -> None:
    if _env_key(path) not in expected:
        raise ValueError("The environment key does not match the rotation journal")
    lines = path.read_bytes().splitlines(keepends=True)
    output = []
    for line in lines:
        if line.startswith(_PREFIX):
            ending = b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b""
            line = _PREFIX + new_key.hex().encode("ascii") + ending
        output.append(line)
    temp = journal / "env.next"
    try:
        # This exact journal-owned name can remain after a hard process stop.
        # It is always removed before retry and during journal cleanup.
        temp.unlink(missing_ok=True)
        _write_private(temp, b"".join(output))
        os.replace(temp, path)
        _sync_dir(path.parent)
        _sync_dir(journal)
    finally:
        temp.unlink(missing_ok=True)


def prepare_rotation(env_path: Path, journal: Path) -> None:
    """Create a durable journal before changing the database or environment."""
    old = _env_key(env_path)
    if os.stat(env_path.parent).st_dev != os.stat(journal.parent).st_dev:
        raise ValueError("Journal and environment must be on the same filesystem")
    new = secrets.token_bytes(32)
    journal.mkdir(mode=0o700, exist_ok=False)
    _sync_dir(journal.parent)
    _write_private(journal / "old.key", old.hex().encode("ascii"))
    _write_private(journal / "new.key", new.hex().encode("ascii"))
    _write_private(journal / "READY", b"1\n")


def _journal_key(journal: Path, name: str) -> bytes:
    value = (journal / name).read_bytes().strip()
    if not _KEY.fullmatch(value):
        raise ValueError("Invalid rotation journal")
    return bytes.fromhex(value.decode("ascii"))


async def _database_uses_key(factory: async_sessionmaker[AsyncSession], key: bytes) -> bool:
    async with factory() as session, session.begin():
        await session.execute(text("LOCK TABLE public.tenant_keys IN ACCESS EXCLUSIVE MODE"))
        rows = list((await session.execute(select(TenantKey))).scalars())
        if not rows or any(row.algorithm != "AES-256-GCM" for row in rows):
            raise ValueError("No supported tenant keys found")
        cipher = AESGCM(key)
        for row in rows:
            blob = bytes(row.encrypted_key)
            if len(blob) != 60:
                raise ValueError("Invalid tenant key envelope")
            try:
                data_key = cipher.decrypt(blob[:12], blob[12:], None)
            except InvalidTag:
                return False
            if len(data_key) != 32:
                raise ValueError("Invalid tenant data key")
        return True


async def apply_rotation(
    factory: async_sessionmaker[AsyncSession], env_path: Path, journal: Path
) -> int:
    """Rewrap and switch configuration; leave journal until external verification."""
    if not (journal / "READY").is_file() or (journal / "COMMITTED").exists():
        raise ValueError("Rotation journal is not ready")
    old, new = _journal_key(journal, "old.key"), _journal_key(journal, "new.key")
    if _env_key(env_path) != old:
        raise ValueError("Environment key changed before rotation")
    count = await rewrap_tenant_keys(factory, old, new)
    _replace_env_key(env_path, journal, (old,), new)
    if not await _database_uses_key(factory, new):
        raise ValueError("New key verification failed")
    return count


async def rollback_rotation(
    factory: async_sessionmaker[AsyncSession], env_path: Path, journal: Path
) -> None:
    """Idempotently restore the old master after a partially completed switch."""
    if (
        not (journal / "READY").is_file()
        or (journal / "COMMITTED").exists()
        or (journal / "ROLLED_BACK").exists()
    ):
        raise ValueError("Rotation journal cannot be rolled back automatically")
    old, new = _journal_key(journal, "old.key"), _journal_key(journal, "new.key")
    if _env_key(env_path) not in (old, new):
        raise ValueError("Environment key does not match journal")
    if await _database_uses_key(factory, new):
        await rewrap_tenant_keys(factory, new, old)
    elif not await _database_uses_key(factory, old):
        raise ValueError("Database keys match neither master; journal preserved")
    _replace_env_key(env_path, journal, (old, new), old)
    if not await _database_uses_key(factory, old):
        raise ValueError("Old key verification failed; journal preserved")


async def finalize_rotation(
    factory: async_sessionmaker[AsyncSession], env_path: Path, journal: Path
) -> None:
    """Delete the journal only after external validation of the restarted stack."""
    if (journal / "ROLLED_BACK").exists():
        raise ValueError("Journal is being finalized as a rollback")
    key = _env_key(env_path)
    new_path = journal / "new.key"
    if new_path.exists() and key != _journal_key(journal, "new.key"):
        raise ValueError("Environment does not contain the new master key")
    if not await _database_uses_key(factory, key):
        raise ValueError("Database does not match environment; journal preserved")
    marker = journal / "COMMITTED"
    if not marker.exists():
        if not (journal / "READY").is_file() or not new_path.is_file():
            raise ValueError("Incomplete rotation journal")
        _write_private(marker, b"1\n")
    _remove_journal(journal, marker)


async def finalize_rollback(
    factory: async_sessionmaker[AsyncSession], env_path: Path, journal: Path
) -> None:
    """Delete recovery material only when the old state is verified."""
    if (journal / "COMMITTED").exists():
        raise ValueError("Journal is committed and cannot be rolled back")
    key = _env_key(env_path)
    old_path = journal / "old.key"
    marker = journal / "ROLLED_BACK"
    if old_path.exists() and key != _journal_key(journal, "old.key"):
        raise ValueError("Environment does not contain the old master key")
    if not marker.exists() and (not old_path.is_file() or not (journal / "READY").is_file()):
        raise ValueError("Incomplete rotation journal")
    if not await _database_uses_key(factory, key):
        raise ValueError("Database does not match environment; journal preserved")
    if not marker.exists():
        _write_private(marker, b"1\n")
    _remove_journal(journal, marker)


def _remove_journal(journal: Path, marker: Path) -> None:
    allowed = {"old.key", "new.key", "READY", "env.next", marker.name}
    if any(child.name not in allowed for child in journal.iterdir()):
        raise ValueError("Unexpected journal files; refusing cleanup")
    for name in ("old.key", "new.key", "READY", "env.next"):
        (journal / name).unlink(missing_ok=True)
    _sync_dir(journal)
    marker.unlink()
    _sync_dir(journal)
    journal.rmdir()
    _sync_dir(journal.parent)
