"""SQLAlchemy models package.

Import all models here so Alembic can detect them for autogenerate.
As new model files are added, import them here.
"""

from app.core.database import Base
from app.models.admin import Admin
from app.models.base import TimestampMixin, UUIDMixin
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
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
from app.models.feedback import Feedback, UnansweredQuestion
from app.models.incitation import IncentiveCategory, IncentiveItem
from app.models.kb import KBChunk, KBDocument
from app.models.tenant import Tenant

__all__ = [
    # Base & mixins
    "Base",
    "UUIDMixin",
    "TimestampMixin",
    # Models
    "Admin",
    "Contact",
    "Conversation",
    "Feedback",
    "IncentiveCategory",
    "IncentiveItem",
    "KBChunk",
    "KBDocument",
    "Message",
    "Tenant",
    "UnansweredQuestion",
    # Enums
    "AdminRole",
    "AgentType",
    "CampaignStatus",
    "ContactSource",
    "ConversationStatus",
    "DossierStatut",
    "EscalationStatus",
    "EscalationTrigger",
    "FeedbackRating",
    "KBDocumentStatus",
    "Language",
    "MessageDirection",
    "MessageType",
    "OptInStatus",
    "SyncStatus",
    "TenantStatus",
    "UnansweredStatus",
]
