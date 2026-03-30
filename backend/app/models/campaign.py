"""Campaign and CampaignRecipient models — stored in the TENANT schema.

A campaign represents a WhatsApp mass-messaging operation using pre-validated
Meta templates. CampaignRecipient tracks per-contact delivery status.

Quota: 100 000 messages/year/tenant (CPS clarification R13).
Contacts with opt_in_status = opted_out are excluded at the service layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import CampaignStatus, RecipientStatus

if TYPE_CHECKING:
    from app.models.admin import Admin
    from app.models.contact import Contact


class Campaign(UUIDMixin, TimestampMixin, Base):
    """Campagne de publipostage WhatsApp.

    Permet l'envoi en masse de messages WhatsApp via des templates Meta
    prévalidés, avec ciblage par segments/tags de contacts.

    Quota: 100 000 messages/an/tenant (clarification R13 du CPS).
    Les contacts en opt_out sont automatiquement exclus (service layer).

    Cycle de vie: draft → scheduled → sending → completed/failed
                                   ↘ paused ↗
    """

    __tablename__ = "campaigns"
    __table_args__ = (
        Index("ix_campaigns_status", "status"),
        Index(
            "ix_campaigns_scheduled_at",
            "scheduled_at",
            postgresql_where=text("scheduled_at IS NOT NULL"),
        ),
        Index("ix_campaigns_created_by", "created_by"),
    )

    # ── Campaign info ──
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── WhatsApp template ──
    template_id: Mapped[str] = mapped_column(String(255), nullable=False)
    template_name: Mapped[str] = mapped_column(String(255), nullable=False)
    template_language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default="fr",
    )

    # ── Audience ──
    audience_filter: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    audience_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    # ── Variable mapping ──
    variable_mapping: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    # ── Status ──
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus, name="campaignstatus", schema="public"),
        nullable=False,
        default=CampaignStatus.draft,
        server_default=CampaignStatus.draft.value,
    )

    # ── Scheduling & timestamps ──
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Aggregated stats (updated by the send worker) ──
    stats: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text(
            """'{"sent": 0, "delivered": 0, "read": 0, "failed": 0, "total": 0}'::jsonb"""
        ),
    )

    # ── Traceability ──
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.admins.id"),
        nullable=False,
    )

    # ── Relationships ──
    recipients: Mapped[list[CampaignRecipient]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    creator: Mapped[Admin] = relationship(lazy="selectin")

    def __repr__(self) -> str:
        return f"<Campaign id={self.id} name={self.name!r} status={self.status.value}>"


class CampaignRecipient(UUIDMixin, Base):
    """Destinataire individuel d'une campagne de publipostage.

    Chaque ligne représente un contact ciblé par une campagne.
    Le statut est mis à jour par le worker d'envoi et par les
    callbacks de statut WhatsApp (delivered, read).
    """

    __tablename__ = "campaign_recipients"
    __table_args__ = (
        Index("ix_recipients_campaign_status", "campaign_id", "status"),
        Index("ix_recipients_contact_id", "contact_id"),
        Index(
            "ix_recipients_whatsapp_msg_id",
            "whatsapp_message_id",
            postgresql_where=text("whatsapp_message_id IS NOT NULL"),
        ),
    )

    # ── Foreign keys ──
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id"),
        nullable=False,
    )

    # ── Delivery status ──
    status: Mapped[RecipientStatus] = mapped_column(
        Enum(RecipientStatus, name="recipientstatus", schema="public"),
        nullable=False,
        default=RecipientStatus.pending,
        server_default=RecipientStatus.pending.value,
    )

    # ── Delivery details ──
    whatsapp_message_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Timestamp (no updated_at — status changes tracked via dedicated fields) ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ──
    campaign: Mapped[Campaign] = relationship(back_populates="recipients")
    contact: Mapped[Contact] = relationship(lazy="selectin")

    def __repr__(self) -> str:
        return f"<CampaignRecipient id={self.id} status={self.status.value}>"
