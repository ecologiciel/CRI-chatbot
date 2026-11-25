"""Read-only tenant-scoped conversation supervision."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, or_, select

from app.core.rbac import require_role
from app.core.tenant import TenantContext, get_current_tenant
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.enums import AdminRole, ContactSource
from app.schemas.auth import AdminTokenPayload
from app.schemas.conversation import (
    ConversationMessagePage,
    ConversationSummary,
    ConversationSummaryList,
    MessageResponse,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])
_supervision = require_role(AdminRole.super_admin, AdminRole.admin_tenant, AdminRole.supervisor)


def _summary_query():
    last_message = (
        select(Message.content)
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.timestamp.desc(), Message.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    last_time = (
        select(Message.timestamp)
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.timestamp.desc(), Message.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    return select(
        Conversation,
        Contact,
        last_message,
        func.coalesce(last_time, Conversation.started_at).label("last_activity"),
    ).join(Contact, Contact.id == Conversation.contact_id)


def _summary(row) -> ConversationSummary:
    conversation, contact, last_message, last_time = row
    return ConversationSummary(
        id=conversation.id,
        contact_name=contact.name,
        contact_phone=None if contact.source == ContactSource.web else contact.phone,
        channel=contact.source.value,
        agent_type=conversation.agent_type,
        status=conversation.status,
        last_message=last_message,
        last_message_at=last_time,
    )


@router.get("", response_model=ConversationSummaryList)
async def list_conversations(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(_supervision),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=100),
) -> ConversationSummaryList:
    async with tenant.db_session() as session:
        query = _summary_query()
        count_query = select(func.count(Conversation.id)).join(Contact)
        if search and search.strip():
            term = f"%{search.strip()}%"
            predicate = or_(Contact.name.ilike(term), Contact.phone.ilike(term))
            query = query.where(predicate)
            count_query = count_query.where(predicate)
        total = (await session.execute(count_query)).scalar_one()
        rows = (
            await session.execute(
                query.order_by(desc("last_activity"), Conversation.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return ConversationSummaryList(
            items=[_summary(row) for row in rows], total=total, page=page, page_size=page_size
        )


@router.get("/{conversation_id}", response_model=ConversationSummary)
async def get_conversation(
    conversation_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(_supervision),
) -> ConversationSummary:
    async with tenant.db_session() as session:
        row = (
            await session.execute(_summary_query().where(Conversation.id == conversation_id))
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Conversation introuvable")
        return _summary(row)


@router.get("/{conversation_id}/messages", response_model=ConversationMessagePage)
async def list_messages(
    conversation_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(_supervision),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
) -> ConversationMessagePage:
    async with tenant.db_session() as session:
        exists = await session.scalar(
            select(Conversation.id).where(Conversation.id == conversation_id)
        )
        if exists is None:
            raise HTTPException(status_code=404, detail="Conversation introuvable")
        total = await session.scalar(
            select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
        )
        messages = (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.timestamp.asc(), Message.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return ConversationMessagePage(
            items=[MessageResponse.model_validate(message) for message in messages],
            total=total or 0,
            page=page,
            page_size=page_size,
        )
