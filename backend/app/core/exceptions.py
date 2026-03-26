"""Custom exception hierarchy for the CRI platform.

All exceptions inherit from CRIBaseException.
Each module defines its own exceptions (e.g., TenantNotFoundError in services/tenant/).
"""

from typing import Any


class CRIBaseException(Exception):
    """Base exception for all CRI platform errors."""

    def __init__(self, message: str = "", details: dict[str, Any] | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


# --- Authentication / Authorization ---
class AuthenticationError(CRIBaseException):
    """Invalid credentials or token."""


class AuthorizationError(CRIBaseException):
    """User lacks required permissions."""


# --- Tenant ---
class TenantNotFoundError(CRIBaseException):
    """Tenant could not be resolved."""


class TenantProvisioningError(CRIBaseException):
    """Error during tenant provisioning."""


class TenantInactiveError(CRIBaseException):
    """Tenant exists but is not active (inactive/suspended/provisioning)."""


class TenantResolutionError(CRIBaseException):
    """Cannot determine tenant from the request context."""


# --- Resource ---
class ResourceNotFoundError(CRIBaseException):
    """Requested resource does not exist."""


class DuplicateResourceError(CRIBaseException):
    """Resource already exists (unique constraint violation)."""


# --- WhatsApp ---
class WhatsAppError(CRIBaseException):
    """Base WhatsApp error."""


class WhatsAppSendError(WhatsAppError):
    """Failed to send message."""


class WhatsAppSignatureError(WhatsAppError):
    """Invalid HMAC signature on webhook."""


class WhatsAppQuotaExhaustedError(WhatsAppError):
    """WhatsApp message quota exhausted for this tenant."""


# --- RAG ---
class RAGError(CRIBaseException):
    """Base RAG pipeline error."""


class IngestionError(RAGError):
    """Document ingestion failed."""


class RetrievalError(RAGError):
    """RAG retrieval/search failed."""


class ChunkingError(RAGError):
    """Document chunking failed."""


# --- Validation ---
class ValidationError(CRIBaseException):
    """Business logic validation error."""


# --- Rate Limiting ---
class RateLimitExceededError(CRIBaseException):
    """Rate limit exceeded."""


# --- Account Lockout ---
class AccountLockedError(CRIBaseException):
    """Account temporarily locked due to excessive failed login attempts."""

    def __init__(self, remaining_seconds: int = 0) -> None:
        self.remaining_seconds = remaining_seconds
        super().__init__(
            message=f"Account locked. Try again in {remaining_seconds}s",
            details={"remaining_seconds": remaining_seconds},
        )


# --- Tenant Provisioning ---
class DuplicateTenantError(CRIBaseException):
    """Tenant with this slug already exists."""

    def __init__(self, slug: str) -> None:
        super().__init__(
            message=f"Tenant already exists: {slug}",
            details={"slug": slug},
        )


# --- AI / LLM ---
class GeminiError(CRIBaseException):
    """Gemini API call failed."""


class EmbeddingError(CRIBaseException):
    """Embedding generation failed."""
