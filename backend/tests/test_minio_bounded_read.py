"""The import reader must bound memory and close responses on every outcome."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.minio import get_object_bytes


@pytest.mark.asyncio()
@pytest.mark.parametrize("oversized", [False, True])
async def test_bounded_storage_read_closes_response(oversized):
    response = MagicMock()
    response.content.readexactly = AsyncMock(
        return_value=b"12345" if oversized else None,
        side_effect=None if oversized else asyncio.IncompleteReadError(b"123", 5),
    )
    client = MagicMock()
    client.get_object = AsyncMock(return_value=response)
    session = AsyncMock()
    session.__aenter__.return_value = session
    with (
        patch("app.core.minio.get_minio", return_value=client),
        patch("app.core.minio.aiohttp.ClientSession", return_value=session),
    ):
        if oversized:
            with pytest.raises(ValueError, match="maximum"):
                await get_object_bytes("bucket", "file", max_bytes=4)
        else:
            assert await get_object_bytes("bucket", "file", max_bytes=4) == b"123"
    response.content.readexactly.assert_awaited_once_with(5)
    response.release.assert_called_once()
