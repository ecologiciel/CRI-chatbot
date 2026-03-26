"""WhatsApp media handler — download, store, and analyze media with Gemini multimodal.

Downloads media from Meta Cloud API, stores in tenant's MinIO bucket,
and analyzes with Gemini 2.5 Flash (image description/OCR, audio transcription).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO

import httpx
import structlog
from google import genai
from google.genai import types

from app.core.config import get_settings
from app.core.exceptions import WhatsAppMediaError
from app.core.minio import get_minio
from app.core.tenant import TenantContext

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# WhatsApp protocol constants (not deployment config)
# ---------------------------------------------------------------------------
META_GRAPH_URL = "https://graph.facebook.com/v21.0"
DOWNLOAD_TIMEOUT = 60.0

ALLOWED_IMAGE_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})
ALLOWED_AUDIO_MIMES = frozenset({
    "audio/ogg", "audio/mpeg", "audio/amr", "audio/aac", "audio/mp4",
})
ALL_ALLOWED_MIMES = ALLOWED_IMAGE_MIMES | ALLOWED_AUDIO_MIMES

MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/amr": "amr",
    "audio/aac": "aac",
    "audio/mp4": "m4a",
}

MAX_SIZE_IMAGE = 16 * 1024 * 1024   # 16 MB
MAX_SIZE_AUDIO = 25 * 1024 * 1024   # 25 MB

# ---------------------------------------------------------------------------
# Gemini prompts (no PII, CRI institutional tone)
# ---------------------------------------------------------------------------
IMAGE_PROMPT = (
    "Tu es l'assistant du Centre Régional d'Investissement. "
    "Décris cette image en détail. Si elle contient du texte ou un document, "
    "transcris intégralement le texte visible. Réponds en français."
)
AUDIO_PROMPT = (
    "Transcris cet audio en texte. Indique la langue détectée (FR/AR/EN). "
    "Si l'audio est inaudible, indique-le."
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MediaResult:
    """Outcome of media processing — always returned, never raises."""

    extracted_text: str  # Text from Gemini analysis (empty on failure)
    minio_path: str      # "cri-{slug}/media/2026-03/{id}.jpg" (empty on failure)
    media_type: str      # "image" | "audio" | "unsupported"
    analysis: str        # "success" | error description
    success: bool


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------
class WhatsAppMediaHandler:
    """Download WhatsApp media, store in MinIO, analyze with Gemini multimodal."""

    def __init__(self) -> None:
        self.logger = logger.bind(service="media_handler")

    # -- Public entry point ------------------------------------------------

    async def process_media(
        self,
        tenant: TenantContext,
        media_id: str,
        mime_type: str,
    ) -> MediaResult:
        """Full media processing pipeline.

        Steps:
            1. Classify and validate mime_type
            2. Download from Meta Cloud API (2-step: resolve URL, then GET binary)
            3. Validate file size
            4. Upload to MinIO tenant bucket
            5. Analyze with Gemini 2.5 Flash multimodal
            6. Return MediaResult (never raises)

        Args:
            tenant: Current tenant context.
            media_id: WhatsApp media ID from the webhook payload.
            mime_type: MIME type reported by WhatsApp.

        Returns:
            MediaResult with extracted_text, minio_path, and success status.
        """
        # 1. Classify
        clean_mime = mime_type.split(";")[0].strip()
        media_type = self._classify_media(clean_mime)

        if media_type == "unsupported":
            return MediaResult(
                extracted_text="",
                minio_path="",
                media_type="unsupported",
                analysis=f"Format non supporté: {clean_mime}",
                success=False,
            )

        try:
            # 2. Download
            media_bytes = await self._download_media(tenant, media_id)

            # 3. Size check
            max_size = MAX_SIZE_IMAGE if media_type == "image" else MAX_SIZE_AUDIO
            if len(media_bytes) > max_size:
                return MediaResult(
                    extracted_text="",
                    minio_path="",
                    media_type=media_type,
                    analysis=f"Fichier trop volumineux: {len(media_bytes)} octets (max {max_size})",
                    success=False,
                )

            # 4. Store in MinIO
            minio_path = await self._upload_to_minio(
                tenant, media_id, media_bytes, clean_mime,
            )

            # 5. Analyze with Gemini (graceful — failure does not block storage)
            extracted_text = await self._analyze_with_gemini(
                media_bytes, clean_mime, media_type,
            )

            self.logger.info(
                "whatsapp_media_processed",
                tenant_slug=tenant.slug,
                media_id=media_id,
                media_type=media_type,
                size_bytes=len(media_bytes),
                text_length=len(extracted_text),
            )

            return MediaResult(
                extracted_text=extracted_text,
                minio_path=minio_path,
                media_type=media_type,
                analysis="success",
                success=True,
            )

        except Exception as exc:
            self.logger.error(
                "whatsapp_media_failed",
                tenant_slug=tenant.slug,
                media_id=media_id,
                error=str(exc)[:200],
            )
            return MediaResult(
                extracted_text="",
                minio_path="",
                media_type=media_type,
                analysis=f"Erreur: {str(exc)[:100]}",
                success=False,
            )

    # -- Private helpers ---------------------------------------------------

    @staticmethod
    def _get_access_token(tenant: TenantContext) -> str:
        """Extract WhatsApp access_token from tenant config.

        Raises:
            WhatsAppMediaError: If config or token is missing.
        """
        config = tenant.whatsapp_config
        if not config:
            raise WhatsAppMediaError(
                "Missing WhatsApp config",
                details={"tenant_slug": tenant.slug},
            )
        token = config.get("access_token", "")
        if not token:
            raise WhatsAppMediaError(
                "Missing access_token in WhatsApp config",
                details={"tenant_slug": tenant.slug},
            )
        return token

    async def _download_media(self, tenant: TenantContext, media_id: str) -> bytes:
        """Download media binary from Meta Cloud API (2-step).

        Step 1: GET /{media_id} → JSON with "url" field (CDN link).
        Step 2: GET {url} → binary content.

        Args:
            tenant: Tenant context (for access_token).
            media_id: WhatsApp media ID.

        Returns:
            Raw media bytes.

        Raises:
            WhatsAppMediaError: On download failure.
        """
        access_token = self._get_access_token(tenant)
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT) as client:
                # Step 1: Resolve CDN URL
                resp = await client.get(
                    f"{META_GRAPH_URL}/{media_id}",
                    headers=headers,
                )
                resp.raise_for_status()
                media_url = resp.json().get("url")

                if not media_url:
                    raise WhatsAppMediaError(
                        f"No URL in Meta response for media {media_id}",
                    )

                # Step 2: Download binary
                resp = await client.get(media_url, headers=headers)
                resp.raise_for_status()
                return resp.content

        except httpx.HTTPStatusError as exc:
            raise WhatsAppMediaError(
                f"Meta API error {exc.response.status_code}",
                details={"media_id": media_id},
            ) from exc
        except httpx.TimeoutException as exc:
            raise WhatsAppMediaError(
                "Media download timeout",
                details={"media_id": media_id},
            ) from exc

    async def _upload_to_minio(
        self,
        tenant: TenantContext,
        media_id: str,
        content: bytes,
        mime_type: str,
    ) -> str:
        """Upload media to tenant's MinIO bucket.

        Path format: media/{YYYY-MM}/{media_id}.{ext}

        Returns:
            Full MinIO path: "{bucket}/media/{YYYY-MM}/{media_id}.{ext}"
        """
        object_name = self._build_minio_path(media_id, mime_type)
        minio_client = get_minio()

        await minio_client.put_object(
            bucket_name=tenant.minio_bucket,
            object_name=object_name,
            data=BytesIO(content),
            length=len(content),
            content_type=mime_type,
        )

        full_path = f"{tenant.minio_bucket}/{object_name}"
        self.logger.debug(
            "whatsapp_media_stored",
            tenant_slug=tenant.slug,
            minio_path=full_path,
        )
        return full_path

    async def _analyze_with_gemini(
        self,
        content: bytes,
        mime_type: str,
        media_type: str,
    ) -> str:
        """Analyze media with Gemini 2.5 Flash multimodal.

        Image → description + OCR.
        Audio → transcription + language detection.

        On failure, logs a warning and returns empty string (graceful degradation).
        """
        prompt = IMAGE_PROMPT if media_type == "image" else AUDIO_PROMPT

        try:
            settings = get_settings()
            client = genai.Client(api_key=settings.gemini_api_key)

            response = await client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(text=prompt),
                            types.Part(
                                inline_data=types.Blob(
                                    mime_type=mime_type,
                                    data=content,
                                ),
                            ),
                        ],
                    ),
                ],
            )

            return response.text or ""

        except Exception as exc:
            self.logger.warning(
                "whatsapp_media_analysis_failed",
                error=str(exc)[:200],
                media_type=media_type,
            )
            return ""

    @staticmethod
    def _classify_media(mime_type: str) -> str:
        """Classify MIME type into image, audio, or unsupported."""
        if mime_type in ALLOWED_IMAGE_MIMES:
            return "image"
        if mime_type in ALLOWED_AUDIO_MIMES:
            return "audio"
        return "unsupported"

    @staticmethod
    def _build_minio_path(media_id: str, mime_type: str) -> str:
        """Generate date-partitioned MinIO object path.

        Returns:
            "media/{YYYY-MM}/{media_id}.{ext}"
        """
        ext = MIME_TO_EXT.get(mime_type, "bin")
        month = datetime.now(UTC).strftime("%Y-%m")
        return f"media/{month}/{media_id}.{ext}"
