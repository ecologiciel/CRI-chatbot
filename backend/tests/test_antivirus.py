"""Fail-closed ClamAV framing and upload behavior."""

from __future__ import annotations

import asyncio
import struct
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.antivirus import (
    AntivirusUnavailableError,
    MalwareDetectedError,
    scan_document,
    signature_database_is_fresh,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (b"stream: OK\0", None),
        (b"stream: Eicar-Test-Signature FOUND\0", MalwareDetectedError),
        (b"stream: limit exceeded ERROR\0", AntivirusUnavailableError),
        (b"not-a-scan\0", AntivirusUnavailableError),
        (b"stream: OK", AntivirusUnavailableError),
    ],
)
async def test_clamd_stream_framing_and_fail_closed(reply, expected):
    received = bytearray()

    async def handler(reader, writer):
        command = await reader.readuntil(b"\0")
        if command == b"zVERSION\0":
            stamp = datetime.now(UTC).strftime("%a %b %d %H:%M:%S %Y")
            writer.write(f"ClamAV 1.4.7/28191/{stamp}\0".encode("ascii"))
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return
        assert command == b"zINSTREAM\0"
        while True:
            size = struct.unpack(">I", await reader.readexactly(4))[0]
            if not size:
                break
            assert size <= 65536
            received.extend(await reader.readexactly(size))
        writer.write(reply)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    settings = SimpleNamespace(
        antivirus_enabled=True,
        antivirus_host="127.0.0.1",
        antivirus_port=port,
        antivirus_timeout=2,
        antivirus_max_signature_age_days=7,
    )
    document = b"a" * 70000 + b"confidential"
    try:
        with patch("app.services.antivirus.get_settings", return_value=settings):
            if expected:
                with pytest.raises(expected) as error:
                    await scan_document(document)
                assert "confidential" not in str(error.value)
            else:
                await scan_document(document)
        assert received == document
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_unavailable_scanner_blocks_and_disabled_scanner_skips():
    settings = SimpleNamespace(
        antivirus_enabled=True, antivirus_host="127.0.0.1", antivirus_port=1, antivirus_timeout=1
    )
    with patch("app.services.antivirus.get_settings", return_value=settings):
        with pytest.raises(AntivirusUnavailableError):
            await scan_document(b"data")
    settings.antivirus_enabled = False
    with (
        patch("app.services.antivirus.get_settings", return_value=settings),
        patch("asyncio.open_connection") as connect,
    ):
        await scan_document(b"data")
        connect.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "status"), [(MalwareDetectedError("x"), 422), (AntivirusUnavailableError("x"), 503)]
)
async def test_upload_refuses_before_storage(failure, status):
    from app.api.v1.kb import upload_document

    file = MagicMock(filename="guide.txt")
    file.read = AsyncMock(return_value=b"contaminated")
    settings = MagicMock(kb_max_file_size_bytes=100, kb_max_file_size_mb=1)
    tenant = MagicMock()
    with (
        patch("app.api.v1.kb.get_settings", return_value=settings),
        patch("app.api.v1.kb.scan_document", new_callable=AsyncMock, side_effect=failure),
        patch("app.api.v1.kb.get_minio") as minio,
        pytest.raises(HTTPException) as error,
    ):
        await upload_document(request=MagicMock(), file=file, title="Guide", tenant=tenant)
    assert error.value.status_code == status
    tenant.db_session.assert_not_called()
    minio.assert_not_called()


def test_signature_timestamp_must_be_current_and_parseable():
    def version(when):
        return ("ClamAV 1.4.7/28191/" + when.strftime("%a %b %d %H:%M:%S %Y")).encode() + b"\0"

    now = datetime.now(UTC)
    assert signature_database_is_fresh(version(now - timedelta(days=2)), 7)
    assert not signature_database_is_fresh(version(now - timedelta(days=8)), 7)
    assert not signature_database_is_fresh(version(now + timedelta(days=1)), 7)
    assert not signature_database_is_fresh(b"unknown\0", 7)


@pytest.mark.asyncio
async def test_stale_signatures_block_scanning():
    commands = []

    async def handler(reader, writer):
        commands.append(await reader.readuntil(b"\0"))
        old = (datetime.now(UTC) - timedelta(days=8)).strftime("%a %b %d %H:%M:%S %Y")
        writer.write(f"ClamAV 1.4.7/28191/{old}\0".encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    settings = SimpleNamespace(
        antivirus_enabled=True,
        antivirus_host="127.0.0.1",
        antivirus_port=server.sockets[0].getsockname()[1],
        antivirus_timeout=2,
        antivirus_max_signature_age_days=7,
    )
    try:
        with patch("app.services.antivirus.get_settings", return_value=settings):
            with pytest.raises(AntivirusUnavailableError):
                await scan_document(b"document")
        assert commands == [b"zVERSION\0"]
    finally:
        server.close()
        await server.wait_closed()
