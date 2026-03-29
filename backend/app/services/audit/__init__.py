"""Audit service — append-only audit trail for security compliance."""

from app.services.audit.service import AuditService, get_audit_service

__all__ = ["AuditService", "get_audit_service"]
