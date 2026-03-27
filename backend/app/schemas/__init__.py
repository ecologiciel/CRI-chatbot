"""Pydantic v2 schemas package."""

from app.schemas.auth import (
    AdminTokenPayload,
    AuthTokenResponse,
    LoginRequest,
    RefreshTokenRequest,
)
from app.schemas.admin import (
    AdminCreate,
    AdminList,
    AdminPasswordChange,
    AdminResponse,
    AdminUpdate,
)
from app.schemas.escalation import (
    EscalationAssign,
    EscalationCreate,
    EscalationList,
    EscalationRead,
    EscalationResolve,
    EscalationRespond,
    EscalationStats,
)
from app.schemas.contact import (
    ContactCreate,
    ContactList,
    ContactResponse,
    ContactUpdate,
)
from app.schemas.conversation import (
    ConversationCreate,
    ConversationList,
    ConversationResponse,
    ConversationUpdate,
    MessageCreate,
    MessageResponse,
)
from app.schemas.feedback import (
    FeedbackCreate,
    FeedbackResponse,
    UnansweredQuestionCreate,
    UnansweredQuestionList,
    UnansweredQuestionResponse,
    UnansweredQuestionUpdate,
)
from app.schemas.kb import (
    KBChunkResponse,
    KBDocumentCreate,
    KBDocumentDetailResponse,
    KBDocumentList,
    KBDocumentResponse,
    KBDocumentUpdate,
)
from app.schemas.tenant import (
    TenantAdminResponse,
    TenantCreate,
    TenantList,
    TenantResponse,
    TenantUpdate,
    WhatsAppConfig,
)
from app.schemas.whitelist import (
    InternalWhitelistCreate,
    InternalWhitelistList,
    InternalWhitelistResponse,
    InternalWhitelistUpdate,
    WhitelistCheckResponse,
)

__all__ = [
    # Auth
    "AdminTokenPayload",
    "AuthTokenResponse",
    "LoginRequest",
    "RefreshTokenRequest",
    # Admin
    "AdminCreate",
    "AdminList",
    "AdminPasswordChange",
    "AdminResponse",
    "AdminUpdate",
    # Escalation
    "EscalationAssign",
    "EscalationCreate",
    "EscalationList",
    "EscalationRead",
    "EscalationResolve",
    "EscalationRespond",
    "EscalationStats",
    # Contact
    "ContactCreate",
    "ContactList",
    "ContactResponse",
    "ContactUpdate",
    # Conversation & Message
    "ConversationCreate",
    "ConversationList",
    "ConversationResponse",
    "ConversationUpdate",
    "MessageCreate",
    "MessageResponse",
    # Feedback
    "FeedbackCreate",
    "FeedbackResponse",
    "UnansweredQuestionCreate",
    "UnansweredQuestionList",
    "UnansweredQuestionResponse",
    "UnansweredQuestionUpdate",
    # Knowledge Base
    "KBChunkResponse",
    "KBDocumentCreate",
    "KBDocumentDetailResponse",
    "KBDocumentList",
    "KBDocumentResponse",
    "KBDocumentUpdate",
    # Tenant
    "TenantAdminResponse",
    "TenantCreate",
    "TenantList",
    "TenantResponse",
    "TenantUpdate",
    "WhatsAppConfig",
    # Whitelist
    "InternalWhitelistCreate",
    "InternalWhitelistList",
    "InternalWhitelistResponse",
    "InternalWhitelistUpdate",
    "WhitelistCheckResponse",
]
