"""All enums used across the CRI platform.

Defined as Python str enums for compatibility with SQLAlchemy and Pydantic v2.
Each enum maps to a PostgreSQL ENUM type created via Alembic migrations.
"""

from enum import Enum


class TenantStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    provisioning = "provisioning"


class AgentType(str, Enum):
    public = "public"
    internal = "internal"


class ConversationStatus(str, Enum):
    active = "active"
    ended = "ended"
    escalated = "escalated"
    human_handled = "human_handled"


class MessageDirection(str, Enum):
    inbound = "inbound"
    outbound = "outbound"


class MessageType(str, Enum):
    text = "text"
    image = "image"
    audio = "audio"
    document = "document"
    interactive = "interactive"
    system = "system"


class OptInStatus(str, Enum):
    opted_in = "opted_in"
    opted_out = "opted_out"
    pending = "pending"


class ContactSource(str, Enum):
    whatsapp = "whatsapp"
    import_csv = "import_csv"
    manual = "manual"


class Language(str, Enum):
    fr = "fr"
    ar = "ar"
    en = "en"


class AdminRole(str, Enum):
    super_admin = "super_admin"
    admin_tenant = "admin_tenant"
    supervisor = "supervisor"
    viewer = "viewer"


class KBDocumentStatus(str, Enum):
    pending = "pending"
    indexing = "indexing"
    indexed = "indexed"
    error = "error"


class UnansweredStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    modified = "modified"
    rejected = "rejected"
    injected = "injected"


class FeedbackRating(str, Enum):
    positive = "positive"
    negative = "negative"
    question = "question"


class EscalationTrigger(str, Enum):
    explicit_request = "explicit_request"
    rag_failure = "rag_failure"
    sensitive_topic = "sensitive_topic"
    negative_feedback = "negative_feedback"
    otp_timeout = "otp_timeout"
    manual = "manual"


class EscalationStatus(str, Enum):
    pending = "pending"
    assigned = "assigned"
    resolved = "resolved"
    expired = "expired"


class DossierStatut(str, Enum):
    en_cours = "en_cours"
    valide = "valide"
    rejete = "rejete"
    en_attente = "en_attente"
    complement = "complement"


class CampaignStatus(str, Enum):
    draft = "draft"
    scheduled = "scheduled"
    sending = "sending"
    completed = "completed"
    cancelled = "cancelled"


class SyncStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
