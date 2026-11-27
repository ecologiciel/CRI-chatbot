"""Transactional consent updates for canonical international phone aliases."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.enums import ContactSource, OptInStatus
from app.services.contact.phone_identity import phone_variants


async def lock_and_opt_out(session: AsyncSession, phone: str) -> uuid.UUID:
    """Update or insert a contact, holding its row until the caller commits.

    Requires the canonical phone unique index. A concurrent insertion is
    resolved after its commit; pre-existing aliases raise rather than guessing.
    The caller must write the consent audit in the same transaction.
    """
    variants = phone_variants(phone)
    if len(variants) != 2:
        raise ValueError("Invalid international WhatsApp identifier")
    query = select(Contact).where(Contact.phone.in_(variants)).with_for_update()
    contact = (await session.execute(query)).scalar_one_or_none()
    if contact is None:
        statement = (
            insert(Contact)
            .values(phone=phone, source=ContactSource.whatsapp, opt_in_status=OptInStatus.opted_out)
            .on_conflict_do_nothing()
            .returning(Contact.id)
        )
        inserted = (await session.execute(statement)).scalar_one_or_none()
        if inserted is not None:
            return inserted
        # The conflicting insert may have used the alternate representation.
        contact = (await session.execute(query)).scalar_one()
    contact.opt_in_status = OptInStatus.opted_out
    contact.updated_at = func.now()
    return contact.id
