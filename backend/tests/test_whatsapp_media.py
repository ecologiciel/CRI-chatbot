"""Tests for WhatsApp media handler.

Covers: download from Meta API (2-step), MinIO storage, Gemini multimodal analysis,
size limits, MIME validation, graceful degradation on analysis failure.

NOTE: httpx.Response methods (.json(), .raise_for_status(), .content) are sync,
so mock responses use MagicMock (not AsyncMock).
"""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Required env vars before any app imports
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("REDIS_PASSWORD", "test-password")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key")

from app.core.tenant import TenantContext
from app.services.whatsapp.media import (
    MAX_SIZE_AUDIO,
    MAX_SIZE_IMAGE,
    WhatsAppMediaHandler,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

TEST_TENANT_ID = uuid.uuid4()
FAKE_IMAGE_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # Fake JPEG header
FAKE_AUDIO_BYTES = b"OggS" + b"\x00" * 100  # Fake OGG header
FAKE_CDN_URL = "https://lookaside.fbsbx.com/whatsapp_business/media/abc123"


def _make_tenant_context(**overrides) -> TenantContext:
    """Factory for test TenantContext (frozen dataclass)."""
    defaults = {
        "id": TEST_TENANT_ID,
        "slug": "rabat",
        "name": "CRI Rabat-Salé-Kénitra",
        "status": "active",
        "whatsapp_config": {
            "phone_number_id": "111222333",
            "access_token": "test_access_token",
            "verify_token": "test_verify_token",
        },
    }
    defaults.update(overrides)
    return TenantContext(**defaults)


def _make_mock_http_client(
    url_response: MagicMock,
    binary_response: MagicMock,
) -> AsyncMock:
    """Create a mock httpx.AsyncClient for 2-step media download.

    First .get() → JSON with url field.
    Second .get() → binary content.
    """
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=[url_response, binary_response])
    return client


def _make_url_response(url: str = FAKE_CDN_URL) -> MagicMock:
    """Mock response for Step 1: resolve media URL."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"url": url}
    resp.raise_for_status = MagicMock()
    return resp


def _make_binary_response(content: bytes = FAKE_IMAGE_BYTES) -> MagicMock:
    """Mock response for Step 2: download binary content."""
    resp = MagicMock()
    resp.status_code = 200
    resp.content = content
    resp.headers = {"content-length": str(len(content))}
    resp.raise_for_status = MagicMock()
    return resp


def _make_mock_minio() -> MagicMock:
    """Create a mock MinIO client with async put_object."""
    minio = MagicMock()
    minio.put_object = AsyncMock()
    return minio


def _make_mock_settings() -> MagicMock:
    """Create a mock Settings object with Gemini + MinIO config."""
    settings = MagicMock()
    settings.gemini_api_key = "test-gemini-key"
    settings.gemini_model = "gemini-2.5-flash"
    return settings


def _make_mock_gemini_response(text: str = "Image description text") -> MagicMock:
    """Create a mock Gemini multimodal response."""
    resp = MagicMock()
    resp.text = text
    usage = MagicMock()
    usage.prompt_token_count = 50
    usage.candidates_token_count = 30
    resp.usage_metadata = usage
    return resp


def _patch_all(
    mock_http_client: AsyncMock,
    mock_minio: MagicMock,
    mock_settings: MagicMock,
    mock_gemini_response: MagicMock | None = None,
):
    """Context manager stack patching httpx, minio, settings, and genai."""
    mock_genai_client = MagicMock()
    if mock_gemini_response is not None:
        mock_genai_client.aio.models.generate_content = AsyncMock(
            return_value=mock_gemini_response,
        )
    else:
        mock_genai_client.aio.models.generate_content = AsyncMock(
            return_value=_make_mock_gemini_response(),
        )

    return (
        patch("app.services.whatsapp.media.httpx.AsyncClient", return_value=mock_http_client),
        patch("app.services.whatsapp.media.get_minio", return_value=mock_minio),
        patch("app.services.whatsapp.media.get_settings", return_value=mock_settings),
        patch("app.services.whatsapp.media.genai.Client", return_value=mock_genai_client),
    ), mock_genai_client


# ---------------------------------------------------------------------------
# Tests: Full pipeline
# ---------------------------------------------------------------------------


class TestProcessImageSuccess:
    @pytest.mark.asyncio
    async def test_process_image_success(self):
        """Full happy path: image download → MinIO store → Gemini analysis."""
        tenant = _make_tenant_context()
        handler = WhatsAppMediaHandler()

        url_resp = _make_url_response()
        bin_resp = _make_binary_response(FAKE_IMAGE_BYTES)
        mock_client = _make_mock_http_client(url_resp, bin_resp)
        mock_minio = _make_mock_minio()
        mock_settings = _make_mock_settings()
        gemini_resp = _make_mock_gemini_response("Document officiel CRI")

        patches, _ = _patch_all(mock_client, mock_minio, mock_settings, gemini_resp)
        with patches[0], patches[1], patches[2], patches[3]:
            result = await handler.process_media(tenant, "media_img_123", "image/jpeg")

        assert result.success is True
        assert result.media_type == "image"
        assert result.extracted_text == "Document officiel CRI"
        assert result.analysis == "success"
        assert "cri-rabat/media/" in result.minio_path
        assert result.minio_path.endswith(".jpg")

        # Verify MinIO was called with correct bucket
        mock_minio.put_object.assert_awaited_once()
        call_kwargs = mock_minio.put_object.call_args.kwargs
        assert call_kwargs["bucket_name"] == "cri-rabat"
        assert call_kwargs["content_type"] == "image/jpeg"


class TestProcessAudioSuccess:
    @pytest.mark.asyncio
    async def test_process_audio_success(self):
        """Full happy path: audio download → store → transcription."""
        tenant = _make_tenant_context()
        handler = WhatsAppMediaHandler()

        url_resp = _make_url_response()
        bin_resp = _make_binary_response(FAKE_AUDIO_BYTES)
        mock_client = _make_mock_http_client(url_resp, bin_resp)
        mock_minio = _make_mock_minio()
        mock_settings = _make_mock_settings()
        gemini_resp = _make_mock_gemini_response("Bonjour, je veux créer une SARL.")

        patches, _ = _patch_all(mock_client, mock_minio, mock_settings, gemini_resp)
        with patches[0], patches[1], patches[2], patches[3]:
            result = await handler.process_media(tenant, "media_audio_456", "audio/ogg")

        assert result.success is True
        assert result.media_type == "audio"
        assert result.extracted_text == "Bonjour, je veux créer une SARL."
        assert result.minio_path.endswith(".ogg")


class TestUnsupportedMimeType:
    @pytest.mark.asyncio
    async def test_unsupported_mime_type(self):
        """application/pdf → unsupported, success=False, no download attempted."""
        tenant = _make_tenant_context()
        handler = WhatsAppMediaHandler()

        result = await handler.process_media(tenant, "media_pdf_789", "application/pdf")

        assert result.success is False
        assert result.media_type == "unsupported"
        assert "non supporté" in result.analysis


class TestFileTooLarge:
    @pytest.mark.asyncio
    async def test_file_too_large_image(self):
        """Image > 16 MB → success=False, no MinIO upload."""
        tenant = _make_tenant_context()
        handler = WhatsAppMediaHandler()

        oversized = b"\x00" * (MAX_SIZE_IMAGE + 1)
        url_resp = _make_url_response()
        bin_resp = _make_binary_response(oversized)
        mock_client = _make_mock_http_client(url_resp, bin_resp)
        mock_minio = _make_mock_minio()
        mock_settings = _make_mock_settings()

        patches, _ = _patch_all(mock_client, mock_minio, mock_settings)
        with patches[0], patches[1], patches[2], patches[3]:
            result = await handler.process_media(tenant, "big_img", "image/jpeg")

        assert result.success is False
        assert "trop volumineux" in result.analysis
        mock_minio.put_object.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_file_too_large_audio(self):
        """Audio > 25 MB → success=False."""
        tenant = _make_tenant_context()
        handler = WhatsAppMediaHandler()

        oversized = b"\x00" * (MAX_SIZE_AUDIO + 1)
        url_resp = _make_url_response()
        bin_resp = _make_binary_response(oversized)
        mock_client = _make_mock_http_client(url_resp, bin_resp)
        mock_minio = _make_mock_minio()
        mock_settings = _make_mock_settings()

        patches, _ = _patch_all(mock_client, mock_minio, mock_settings)
        with patches[0], patches[1], patches[2], patches[3]:
            result = await handler.process_media(tenant, "big_audio", "audio/ogg")

        assert result.success is False
        assert "trop volumineux" in result.analysis


class TestDownloadMetaApi:
    @pytest.mark.asyncio
    async def test_download_meta_api_two_step(self):
        """Verifies 2 GET calls: resolve URL, then download binary."""
        tenant = _make_tenant_context()
        handler = WhatsAppMediaHandler()

        url_resp = _make_url_response(FAKE_CDN_URL)
        bin_resp = _make_binary_response(FAKE_IMAGE_BYTES)
        mock_client = _make_mock_http_client(url_resp, bin_resp)
        mock_minio = _make_mock_minio()
        mock_settings = _make_mock_settings()

        patches, _ = _patch_all(mock_client, mock_minio, mock_settings)
        with patches[0], patches[1], patches[2], patches[3]:
            await handler.process_media(tenant, "media_123", "image/png")

        # Exactly 2 GET calls
        assert mock_client.get.call_count == 2

        # First call: Meta Graph API
        first_call = mock_client.get.call_args_list[0]
        assert "graph.facebook.com" in first_call.args[0]
        assert "media_123" in first_call.args[0]

        # Second call: CDN URL
        second_call = mock_client.get.call_args_list[1]
        assert second_call.args[0] == FAKE_CDN_URL


class TestUploadToMinio:
    @pytest.mark.asyncio
    async def test_upload_to_minio_correct_path(self):
        """MinIO path: cri-{slug}/media/{YYYY-MM}/{id}.{ext}."""
        tenant = _make_tenant_context()
        handler = WhatsAppMediaHandler()

        url_resp = _make_url_response()
        bin_resp = _make_binary_response(FAKE_IMAGE_BYTES)
        mock_client = _make_mock_http_client(url_resp, bin_resp)
        mock_minio = _make_mock_minio()
        mock_settings = _make_mock_settings()

        patches, _ = _patch_all(mock_client, mock_minio, mock_settings)
        with patches[0], patches[1], patches[2], patches[3]:
            result = await handler.process_media(tenant, "img_abc", "image/jpeg")

        assert result.minio_path.startswith("cri-rabat/media/")
        assert "/img_abc.jpg" in result.minio_path

        # Verify put_object args
        call_kwargs = mock_minio.put_object.call_args.kwargs
        assert call_kwargs["bucket_name"] == "cri-rabat"
        assert call_kwargs["length"] == len(FAKE_IMAGE_BYTES)
        assert call_kwargs["content_type"] == "image/jpeg"


class TestClassifyMedia:
    def test_classify_media_types(self):
        """jpeg→image, ogg→audio, exe→unsupported."""
        handler = WhatsAppMediaHandler()

        assert handler._classify_media("image/jpeg") == "image"
        assert handler._classify_media("image/png") == "image"
        assert handler._classify_media("image/webp") == "image"
        assert handler._classify_media("audio/ogg") == "audio"
        assert handler._classify_media("audio/mpeg") == "audio"
        assert handler._classify_media("audio/amr") == "audio"
        assert handler._classify_media("audio/aac") == "audio"
        assert handler._classify_media("audio/mp4") == "audio"
        assert handler._classify_media("application/pdf") == "unsupported"
        assert handler._classify_media("application/octet-stream") == "unsupported"
        assert handler._classify_media("video/mp4") == "unsupported"


class TestGeminiPrompts:
    @pytest.mark.asyncio
    async def test_gemini_image_prompt(self):
        """Image analysis prompt contains 'Décris cette image'."""
        tenant = _make_tenant_context()
        handler = WhatsAppMediaHandler()

        url_resp = _make_url_response()
        bin_resp = _make_binary_response(FAKE_IMAGE_BYTES)
        mock_client = _make_mock_http_client(url_resp, bin_resp)
        mock_minio = _make_mock_minio()
        mock_settings = _make_mock_settings()

        patches, mock_genai_client = _patch_all(mock_client, mock_minio, mock_settings)
        with patches[0], patches[1], patches[2], patches[3]:
            await handler.process_media(tenant, "img_prompt", "image/jpeg")

        # Inspect the prompt sent to Gemini
        call_args = mock_genai_client.aio.models.generate_content.call_args
        contents = call_args.kwargs["contents"]
        text_part = contents[0].parts[0].text
        assert "Décris cette image" in text_part

    @pytest.mark.asyncio
    async def test_gemini_audio_prompt(self):
        """Audio analysis prompt contains 'Transcris'."""
        tenant = _make_tenant_context()
        handler = WhatsAppMediaHandler()

        url_resp = _make_url_response()
        bin_resp = _make_binary_response(FAKE_AUDIO_BYTES)
        mock_client = _make_mock_http_client(url_resp, bin_resp)
        mock_minio = _make_mock_minio()
        mock_settings = _make_mock_settings()

        patches, mock_genai_client = _patch_all(mock_client, mock_minio, mock_settings)
        with patches[0], patches[1], patches[2], patches[3]:
            await handler.process_media(tenant, "aud_prompt", "audio/ogg")

        call_args = mock_genai_client.aio.models.generate_content.call_args
        contents = call_args.kwargs["contents"]
        text_part = contents[0].parts[0].text
        assert "Transcris" in text_part


class TestGeminiFailureGraceful:
    @pytest.mark.asyncio
    async def test_gemini_failure_graceful(self):
        """Gemini exception → media still stored, success=True, extracted_text=''."""
        tenant = _make_tenant_context()
        handler = WhatsAppMediaHandler()

        url_resp = _make_url_response()
        bin_resp = _make_binary_response(FAKE_IMAGE_BYTES)
        mock_client = _make_mock_http_client(url_resp, bin_resp)
        mock_minio = _make_mock_minio()
        mock_settings = _make_mock_settings()

        # Genai raises on analysis
        mock_genai_client = MagicMock()
        mock_genai_client.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("Gemini API unavailable"),
        )

        with (
            patch("app.services.whatsapp.media.httpx.AsyncClient", return_value=mock_client),
            patch("app.services.whatsapp.media.get_minio", return_value=mock_minio),
            patch("app.services.whatsapp.media.get_settings", return_value=mock_settings),
            patch("app.services.whatsapp.media.genai.Client", return_value=mock_genai_client),
        ):
            result = await handler.process_media(tenant, "img_fail", "image/jpeg")

        # Media stored OK, but no text extracted
        assert result.success is True
        assert result.extracted_text == ""
        assert result.minio_path != ""
        assert result.analysis == "success"

        # MinIO was still called
        mock_minio.put_object.assert_awaited_once()


class TestMissingAccessToken:
    @pytest.mark.asyncio
    async def test_missing_access_token(self):
        """No whatsapp_config → success=False."""
        tenant = _make_tenant_context(whatsapp_config=None)
        handler = WhatsAppMediaHandler()

        result = await handler.process_media(tenant, "media_no_token", "image/jpeg")

        assert result.success is False
        assert "Erreur" in result.analysis


class TestMetaApiError:
    @pytest.mark.asyncio
    async def test_meta_api_error(self):
        """Meta API HTTP error → success=False."""
        tenant = _make_tenant_context()
        handler = WhatsAppMediaHandler()

        # First GET raises HTTPStatusError
        error_response = MagicMock()
        error_response.status_code = 401
        error_response.json.return_value = {"error": {"message": "Invalid token"}}
        error_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "401 Unauthorized",
                request=MagicMock(),
                response=error_response,
            ),
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=error_response)

        mock_minio = _make_mock_minio()
        mock_settings = _make_mock_settings()

        with (
            patch("app.services.whatsapp.media.httpx.AsyncClient", return_value=mock_client),
            patch("app.services.whatsapp.media.get_minio", return_value=mock_minio),
            patch("app.services.whatsapp.media.get_settings", return_value=mock_settings),
        ):
            result = await handler.process_media(tenant, "media_err", "image/jpeg")

        assert result.success is False
        assert "Erreur" in result.analysis
        mock_minio.put_object.assert_not_awaited()
