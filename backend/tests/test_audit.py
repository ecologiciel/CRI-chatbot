"""Tests for the audit trail system (SECURITE.1).

Covers: model, schemas, service, middleware, and SQL policy script.
No database required — uses mocks where needed.
"""

from __future__ import annotations

import uuid

import pytest

# ---------------------------------------------------------------------------
# 1. Model imports and structure
# ---------------------------------------------------------------------------


class TestAuditLogModel:
    """Verify AuditLog model structure and schema placement."""

    def test_audit_model_import(self):
        from app.models.audit import AuditLog

        assert AuditLog.__tablename__ == "audit_logs"

    def test_audit_model_in_public_schema(self):
        from app.models.audit import AuditLog

        # __table_args__ is a tuple where last element is a dict
        table_args = AuditLog.__table_args__
        # Find the dict in the tuple
        schema_dict = next((arg for arg in table_args if isinstance(arg, dict)), {})
        assert schema_dict.get("schema") == "public"

    def test_audit_model_no_updated_at(self):
        """AuditLog is immutable — no updated_at column."""
        from app.models.audit import AuditLog

        columns = {c.name for c in AuditLog.__table__.columns}
        assert "updated_at" not in columns
        assert "created_at" in columns

    def test_audit_model_has_uuid_mixin(self):
        from app.models.audit import AuditLog

        columns = {c.name for c in AuditLog.__table__.columns}
        assert "id" in columns

    def test_audit_model_columns_complete(self):
        """All required columns are present."""
        from app.models.audit import AuditLog

        expected = {
            "id",
            "tenant_slug",
            "user_id",
            "user_type",
            "action",
            "resource_type",
            "resource_id",
            "ip_address",
            "user_agent",
            "details",
            "created_at",
        }
        actual = {c.name for c in AuditLog.__table__.columns}
        assert expected == actual

    def test_audit_model_registered_in_init(self):
        """AuditLog is importable from the models package."""
        from app.models import AuditLog

        assert AuditLog.__tablename__ == "audit_logs"


# ---------------------------------------------------------------------------
# 2. Schema imports and validation
# ---------------------------------------------------------------------------


class TestAuditSchemas:
    """Verify Pydantic v2 schemas for audit logs."""

    def test_audit_schemas_import(self):
        from app.schemas.audit import (
            AuditLogCreate,
            AuditLogFilter,
            AuditLogList,
            AuditLogRead,
        )

        assert AuditLogCreate is not None
        assert AuditLogRead is not None
        assert AuditLogFilter is not None
        assert AuditLogList is not None

    def test_audit_create_schema_valid(self):
        from app.schemas.audit import AuditLogCreate

        log = AuditLogCreate(
            tenant_slug="rabat",
            user_id=None,
            user_type="system",
            action="create",
            resource_type="campaign",
        )
        assert log.tenant_slug == "rabat"
        assert log.user_type == "system"
        assert log.action == "create"
        assert log.resource_type == "campaign"
        assert log.resource_id is None
        assert log.details is None

    def test_audit_create_schema_all_fields(self):
        from app.schemas.audit import AuditLogCreate

        uid = uuid.uuid4()
        log = AuditLogCreate(
            tenant_slug="tanger",
            user_id=uid,
            user_type="admin",
            action="delete",
            resource_type="contact",
            resource_id=str(uuid.uuid4()),
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            details={"reason": "cleanup"},
        )
        assert log.user_id == uid
        assert log.user_type == "admin"
        assert log.ip_address == "192.168.1.1"
        assert log.details == {"reason": "cleanup"}

    def test_audit_create_schema_required_fields(self):
        """Missing required fields should raise ValidationError."""
        from pydantic import ValidationError

        from app.schemas.audit import AuditLogCreate

        with pytest.raises(ValidationError):
            AuditLogCreate()  # type: ignore[call-arg]

    def test_audit_filter_all_optional(self):
        from app.schemas.audit import AuditLogFilter

        # All fields are optional — empty filter is valid
        f = AuditLogFilter()
        assert f.tenant_slug is None
        assert f.user_id is None
        assert f.action is None
        assert f.date_from is None
        assert f.date_to is None

    def test_audit_list_structure(self):
        from app.schemas.audit import AuditLogList

        lst = AuditLogList(items=[], total=0, page=1, page_size=50)
        assert lst.items == []
        assert lst.total == 0
        assert lst.page == 1
        assert lst.page_size == 50


# ---------------------------------------------------------------------------
# 3. Service imports and singleton
# ---------------------------------------------------------------------------


class TestAuditService:
    """Verify AuditService structure and singleton pattern."""

    def test_audit_service_import(self):
        from app.services.audit.service import AuditService

        assert AuditService is not None

    def test_audit_service_init(self):
        from app.services.audit.service import AuditService

        svc = AuditService()
        assert svc._logger is not None

    def test_singleton_factory(self):
        """get_audit_service() returns the same instance on repeated calls."""
        # Reset singleton for clean test
        import app.services.audit.service as mod
        from app.services.audit.service import get_audit_service

        mod._audit_service = None

        svc1 = get_audit_service()
        svc2 = get_audit_service()
        assert svc1 is svc2

        # Cleanup
        mod._audit_service = None

    def test_audit_service_from_package(self):
        """Service is re-exported from the package __init__."""
        from app.services.audit import AuditService, get_audit_service

        assert AuditService is not None
        assert callable(get_audit_service)


# ---------------------------------------------------------------------------
# 4. Middleware imports and logic
# ---------------------------------------------------------------------------


class TestAuditMiddleware:
    """Verify AuditMiddleware structure and helper functions."""

    def test_audit_middleware_import(self):
        from app.core.audit_middleware import AuditMiddleware

        assert AuditMiddleware is not None

    def test_excluded_prefixes_contain_required_paths(self):
        from app.core.audit_middleware import AUDIT_EXCLUDED_PREFIXES

        prefixes = AUDIT_EXCLUDED_PREFIXES
        assert any("/webhook/" in p for p in prefixes), "Webhooks should be excluded"
        assert any("/health" in p for p in prefixes), "Health checks should be excluded"
        assert any("/docs" in p for p in prefixes), "Docs should be excluded"
        assert any("/metrics" in p for p in prefixes), "Metrics should be excluded"

    def test_audited_methods(self):
        from app.core.audit_middleware import AUDITED_METHODS

        assert "POST" in AUDITED_METHODS
        assert "PUT" in AUDITED_METHODS
        assert "PATCH" in AUDITED_METHODS
        assert "DELETE" in AUDITED_METHODS
        assert "GET" not in AUDITED_METHODS

    def test_extract_resource_type(self):
        from app.core.audit_middleware import _extract_resource_type

        assert _extract_resource_type("/api/v1/contacts/abc-123") == "contacts"
        assert _extract_resource_type("/api/v1/kb/documents") == "kb"
        assert _extract_resource_type("/api/v1/campaigns") == "campaigns"
        assert _extract_resource_type("/api/v1/auth/login") == "auth"

    def test_extract_resource_id_with_uuid(self):
        from app.core.audit_middleware import _extract_resource_id

        test_uuid = "550e8400-e29b-41d4-a716-446655440000"
        path = f"/api/v1/contacts/{test_uuid}"
        assert _extract_resource_id(path) == test_uuid

    def test_extract_resource_id_without_uuid(self):
        from app.core.audit_middleware import _extract_resource_id

        assert _extract_resource_id("/api/v1/contacts") is None

    def test_method_action_map(self):
        from app.core.audit_middleware import _METHOD_ACTION_MAP

        assert _METHOD_ACTION_MAP["POST"] == "create"
        assert _METHOD_ACTION_MAP["PUT"] == "update"
        assert _METHOD_ACTION_MAP["PATCH"] == "update"
        assert _METHOD_ACTION_MAP["DELETE"] == "delete"


# ---------------------------------------------------------------------------
# 5. SQL policy script existence
# ---------------------------------------------------------------------------


class TestAuditPolicy:
    """Verify the INSERT ONLY SQL script exists."""

    def test_sql_script_exists(self):
        import os

        script_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "scripts",
            "apply_audit_policy.sql",
        )
        assert os.path.isfile(script_path), f"SQL policy script not found at {script_path}"

    def test_sql_script_contains_revoke(self):
        import os

        script_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "scripts",
            "apply_audit_policy.sql",
        )
        with open(script_path) as f:
            content = f.read()
        assert "REVOKE" in content
        assert "GRANT INSERT" in content
        assert "GRANT SELECT" in content
        assert "audit_logs" in content
