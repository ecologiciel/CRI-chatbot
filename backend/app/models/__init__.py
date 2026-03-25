"""SQLAlchemy models package.

Import all models here so Alembic can detect them for autogenerate.
As new model files are added, import them here.
"""

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.tenant import Tenant
from app.models.enums import (
    AdminRole,
    AgentType,
    CampaignStatus,
    ContactSource,
    ConversationStatus,
    DossierStatut,
    EscalationStatus,
    EscalationTrigger,
    FeedbackRating,
    KBDocumentStatus,
    Language,
    MessageDirection,
    MessageType,
    OptInStatus,
    SyncStatus,
    TenantStatus,
    UnansweredStatus,
)

__all__ = [
    "Base",
    "Tenant",
    "UUIDMixin",
    "TimestampMixin",
    "TenantStatus",
    "AgentType",
    "ConversationStatus",
    "MessageDirection",
    "MessageType",
    "OptInStatus",
    "ContactSource",
    "Language",
    "AdminRole",
    "KBDocumentStatus",
    "UnansweredStatus",
    "FeedbackRating",
    "EscalationTrigger",
    "EscalationStatus",
    "DossierStatut",
    "CampaignStatus",
    "SyncStatus",
]
