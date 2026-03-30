"""SQLAlchemy models package.

Import all models here so Alembic can detect them for autogenerate.
As new model files are added, import them here.
"""

from app.core.database import Base
from app.models.admin import Admin
from app.models.audit import AuditLog
from app.models.base import TimestampMixin, UUIDMixin
from app.models.campaign import Campaign, CampaignRecipient
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.enums import (
    AdminRole,
    AgentType,
    CampaignStatus,
    ContactSource,
    ConversationStatus,
    DossierStatut,
    EscalationPriority,
    EscalationStatus,
    EscalationTrigger,
    FeedbackRating,
    KBDocumentStatus,
    Language,
    MessageDirection,
    MessageType,
    OptInStatus,
    RecipientStatus,
    SyncStatus,
    TenantStatus,
    UnansweredStatus,
)
from app.models.escalation import Escalation
from app.models.feedback import Feedback, UnansweredQuestion
from app.models.incitation import IncentiveCategory, IncentiveItem
from app.models.kb import KBChunk, KBDocument
from app.models.tenant import Tenant
from app.models.tenant_key import TenantKey
from app.models.whitelist import InternalWhitelist

__all__ = [
    # Base & mixins
    "Base",
    "UUIDMixin",
    "TimestampMixin",
    # Models
    "Admin",
    "AuditLog",
    "Campaign",
    "CampaignRecipient",
    "Contact",
    "Conversation",
    "Escalation",
    "Feedback",
    "IncentiveCategory",
    "IncentiveItem",
    "InternalWhitelist",
    "KBChunk",
    "KBDocument",
    "Message",
    "Tenant",
    "TenantKey",
    "UnansweredQuestion",
    # Enums
    "AdminRole",
    "AgentType",
    "CampaignStatus",
    "ContactSource",
    "ConversationStatus",
    "RecipientStatus",
    "DossierStatut",
    "EscalationPriority",
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
