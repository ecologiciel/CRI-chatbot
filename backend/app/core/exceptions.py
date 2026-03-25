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


# --- RAG ---
class RAGError(CRIBaseException):
    """Base RAG pipeline error."""


class IngestionError(RAGError):
    """Document ingestion failed."""


# --- Validation ---
class ValidationError(CRIBaseException):
    """Business logic validation error."""


# --- Rate Limiting ---
class RateLimitExceededError(CRIBaseException):
    """Rate limit exceeded."""
