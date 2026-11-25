"""Reject path-like names and bound reads before touching storage."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ValidationError
from app.core.uploads import validate_upload_filename


@pytest.mark.parametrize("name", ["../doc.pdf", "dir/doc.pdf", r"dir\doc.pdf", "bad\x00.pdf", ""])
def test_upload_filename_rejects_paths_and_controls(name):
    with pytest.raises(ValidationError):
        validate_upload_filename(name)


def test_upload_filename_accepts_regular_international_name():
    assert validate_upload_filename("Réglementation ONSSA.pdf") == "Réglementation ONSSA.pdf"


@pytest.mark.asyncio
async def test_kb_upload_reads_only_limit_plus_one():
    from app.api.v1.kb import upload_document

    file = MagicMock(filename="guide.txt")
    file.read = AsyncMock(return_value=b"x" * 9)
    settings = MagicMock(kb_max_file_size_bytes=8, kb_max_file_size_mb=1)
    with patch("app.api.v1.kb.get_settings", return_value=settings):
        with pytest.raises(ValidationError, match="too large"):
            await upload_document(file=file, title="Guide")
    file.read.assert_awaited_once_with(9)


@pytest.mark.asyncio
async def test_dossier_upload_reads_only_limit_plus_one():
    from app.api.v1.dossiers import import_dossiers

    file = MagicMock(filename="dossiers.csv")
    file.read = AsyncMock(return_value=b"x" * 9)
    tenant = MagicMock(slug="onssa")
    admin = MagicMock(sub="admin")
    with patch("app.api.v1.dossiers.MAX_IMPORT_SIZE", 8):
        with pytest.raises(ValidationError, match="volumineux"):
            await import_dossiers(file=file, tenant=tenant, admin=admin)
    file.read.assert_awaited_once_with(9)
