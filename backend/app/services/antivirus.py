"""Bounded ClamAV streaming scan before document storage and parsing."""

from __future__ import annotations

import asyncio
import struct
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from app.core.config import get_settings

_CHUNK_SIZE = 64 * 1024
_REPLY_LIMIT = 4096
_SCAN_SLOTS = asyncio.Semaphore(4)


class MalwareDetectedError(Exception):
    """The scanner detected a threat; never include file content in the error."""


class AntivirusUnavailableError(Exception):
    """The scanner failed, timed out, or returned an unexpected response."""


def signature_database_is_fresh(reply: bytes, max_age_days: int) -> bool:
    """Accept only a recognisable, recent ClamAV signature timestamp."""
    try:
        value = reply.rstrip(b"\0").decode("ascii")
        engine, version, timestamp = value.split("/", 2)
        if not engine.startswith("ClamAV ") or not version.isdigit():
            return False
        parsed = parsedate_to_datetime(timestamp)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        age = datetime.now(UTC) - parsed.astimezone(UTC)
        return -timedelta(hours=1) <= age <= timedelta(days=max_age_days)
    except (UnicodeError, ValueError, TypeError, OverflowError):
        return False


async def _check_signature_freshness(settings) -> None:
    reader, writer = await asyncio.open_connection(
        settings.antivirus_host, settings.antivirus_port, limit=_REPLY_LIMIT
    )
    try:
        writer.write(b"zVERSION\0")
        await writer.drain()
        reply = await reader.readuntil(b"\0")
        if not signature_database_is_fresh(reply, settings.antivirus_max_signature_age_days):
            raise AntivirusUnavailableError("Antivirus signatures are unavailable or outdated")
    finally:
        writer.close()
        try:
            async with asyncio.timeout(1):
                await writer.wait_closed()
        except (OSError, TimeoutError):
            pass


async def scan_document(data: bytes) -> None:
    """Scan bytes with clamd INSTREAM; when enabled, anything but OK fails closed."""
    settings = get_settings()
    if not settings.antivirus_enabled:
        return
    writer = None
    try:
        async with asyncio.timeout(settings.antivirus_timeout), _SCAN_SLOTS:
            await _check_signature_freshness(settings)
            reader, writer = await asyncio.open_connection(
                settings.antivirus_host, settings.antivirus_port, limit=_REPLY_LIMIT
            )
            writer.write(b"zINSTREAM\0")
            for offset in range(0, len(data), _CHUNK_SIZE):
                part = data[offset : offset + _CHUNK_SIZE]
                writer.write(struct.pack(">I", len(part)))
                writer.write(part)
                await writer.drain()
            writer.write(struct.pack(">I", 0))
            await writer.drain()
            response = await reader.readuntil(b"\0")
            if response == b"stream: OK\0":
                return
            if response.startswith(b"stream: ") and response.endswith(b" FOUND\0"):
                raise MalwareDetectedError("Document refused by antivirus")
            raise AntivirusUnavailableError("Antivirus scan did not complete")
    except MalwareDetectedError:
        raise
    except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
        raise AntivirusUnavailableError("Antivirus service unavailable") from exc
    finally:
        if writer is not None:
            writer.close()
            try:
                async with asyncio.timeout(1):
                    await writer.wait_closed()
            except (OSError, TimeoutError):
                pass
