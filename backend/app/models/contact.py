"""Contact model — stored in the TENANT schema.

Every WhatsApp interaction creates or updates a contact.
Key: phone in E.164 format. CIN added via suivi de dossier auth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Enum, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import ContactSource, Language, OptInStatus

if TYPE_CHECKING:
    from app.models.conversation import Conversation


class Contact(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        Index("ix_contacts_phone", "phone", unique=True),
        Index("ix_contacts_cin", "cin"),
        Index("ix_contacts_tags", "tags", postgresql_using="gin"),
        Index("ix_contacts_created_at", "created_at"),
    )

    # Identity
    phone: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="E.164 format, e.g. +212612345678"
    )
    name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Contact display name"
    )
    language: Mapped[Language] = mapped_column(
        Enum(Language, name="language", schema="public"),
        nullable=False,
        default=Language.fr,
        server_default=Language.fr.value,
    )
    cin: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="CIN marocain")

    # Consent & source
    opt_in_status: Mapped[OptInStatus] = mapped_column(
        Enum(OptInStatus, name="optinstatus", schema="public"),
        nullable=False,
        default=OptInStatus.pending,
        server_default=OptInStatus.pending.value,
    )
    tags: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    source: Mapped[ContactSource] = mapped_column(
        Enum(ContactSource, name="contactsource", schema="public"),
        nullable=False,
        default=ContactSource.whatsapp,
        server_default=ContactSource.whatsapp.value,
    )

    # Extensible metadata
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=None,
    )

    # Relationships
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="contact",
    )

    def __repr__(self) -> str:
        return f"<Contact phone={self.phone!r} language={self.language.value}>"
