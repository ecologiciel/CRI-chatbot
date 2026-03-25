"""Pydantic v2 schemas package."""

from app.schemas.admin import (
    AdminCreate,
    AdminList,
    AdminPasswordChange,
    AdminResponse,
    AdminUpdate,
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

__all__ = [
    # Admin
    "AdminCreate",
    "AdminList",
    "AdminPasswordChange",
    "AdminResponse",
    "AdminUpdate",
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
]
