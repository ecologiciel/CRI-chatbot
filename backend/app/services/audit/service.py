"""AuditService — append-only audit trail for security compliance (SECURITE.1).

All writes are fire-and-forget: if the log fails, the error is logged
via structlog but never blocks the calling request.

Uses public-schema sessions (get_session_factory), NOT tenant.db_session(),
because audit_logs lives in the public schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from sqlalchemy import func, select, text

from app.core.database import get_session_factory
from app.models.audit import AuditLog
from app.schemas.audit import AuditLogCreate, AuditLogFilter

logger = structlog.get_logger()


class AuditService:
    """Centralized service for writing and reading audit logs.

    Writing (log_action) is fire-and-forget — exceptions are swallowed.
    Reading (get_logs) is used by the super-admin back-office.
    """

    def __init__(self) -> None:
        self._logger = logger.bind(service="audit_service")

    async def log_action(self, data: AuditLogCreate) -> None:
        """Record an action in the audit trail.

        Fire-and-forget: errors are logged but never re-raised.
        The session operates in the public schema (not tenant-scoped).

        Args:
            data: Audit log entry to persist.
        """
        try:
            factory = get_session_factory()
            async with factory() as session:
                await session.execute(text("SET search_path TO public"))
                audit_log = AuditLog(
                    tenant_slug=data.tenant_slug,
                    user_id=data.user_id,
                    user_type=data.user_type,
                    action=data.action,
                    resource_type=data.resource_type,
                    resource_id=data.resource_id,
                    ip_address=data.ip_address,
                    user_agent=data.user_agent,
                    details=data.details,
                )
                session.add(audit_log)
                await session.commit()

            self._logger.debug(
                "audit_logged",
                action=data.action,
                resource_type=data.resource_type,
                tenant=data.tenant_slug,
            )
        except Exception as exc:
            self._logger.error(
                "audit_log_failed",
                error=str(exc),
                action=data.action,
                resource_type=data.resource_type,
                tenant=data.tenant_slug,
                exc_info=True,
            )

    async def get_logs(
        self,
        *,
        filters: AuditLogFilter,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AuditLog], int]:
        """Retrieve audit logs with filters and pagination.

        Used by the super-admin to consult the audit trail.

        Args:
            filters: Optional filter criteria (tenant, user, action, dates).
            page: Page number (1-indexed).
            page_size: Number of items per page.

        Returns:
            Tuple of (items, total_count).
        """
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SET search_path TO public"))

            base = select(AuditLog)

            # --- Dynamic filters ---
            if filters.tenant_slug is not None:
                base = base.where(AuditLog.tenant_slug == filters.tenant_slug)
            if filters.user_id is not None:
                base = base.where(AuditLog.user_id == filters.user_id)
            if filters.action is not None:
                base = base.where(AuditLog.action == filters.action)
            if filters.resource_type is not None:
                base = base.where(AuditLog.resource_type == filters.resource_type)
            if filters.date_from is not None:
                base = base.where(AuditLog.created_at >= filters.date_from)
            if filters.date_to is not None:
                base = base.where(AuditLog.created_at <= filters.date_to)

            # --- Count ---
            count_result = await session.execute(
                select(func.count()).select_from(base.subquery()),
            )
            total = count_result.scalar_one()

            # --- Paginated data (most recent first) ---
            offset = (page - 1) * page_size
            data_result = await session.execute(
                base.order_by(AuditLog.created_at.desc())
                .offset(offset)
                .limit(page_size),
            )
            items = list(data_result.scalars().all())

        return items, total


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_audit_service: AuditService | None = None


def get_audit_service() -> AuditService:
    """Get or create the AuditService singleton."""
    global _audit_service  # noqa: PLW0603
    if _audit_service is None:
        _audit_service = AuditService()
    return _audit_service
