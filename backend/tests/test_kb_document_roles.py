"""Document roles must not grant each other's write permissions."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute

from app.api.v1.kb import router
from app.core.exceptions import AuthorizationError
from app.models.enums import AdminRole
from app.schemas.admin import AdminCreate


def role_dependency(path: str, method: str):
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == f"/kb{path}" and method in route.methods
    )
    return next(dep.call for dep in route.dependant.dependencies if dep.name == "admin")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "method", "role", "allowed"),
    [
        ("/documents", "POST", AdminRole.document_importer, True),
        ("/documents", "POST", AdminRole.document_validator, False),
        ("/documents/{document_id}/validate", "POST", AdminRole.document_importer, False),
        ("/documents/{document_id}/validate", "POST", AdminRole.document_validator, True),
        ("/documents", "GET", AdminRole.document_importer, True),
        ("/documents", "GET", AdminRole.document_validator, True),
        ("/documents/{document_id}", "DELETE", AdminRole.document_importer, False),
        ("/documents/{document_id}", "DELETE", AdminRole.document_validator, False),
        ("/documents", "POST", AdminRole.admin_tenant, True),
        ("/documents/{document_id}/validate", "POST", AdminRole.admin_tenant, True),
    ],
)
async def test_document_role_matrix(path, method, role, allowed):
    dependency = role_dependency(path, method)
    payload = SimpleNamespace(role=role.value)
    if allowed:
        assert await dependency(admin=payload) is payload
    else:
        with pytest.raises(AuthorizationError):
            await dependency(admin=payload)


@pytest.mark.parametrize("role", [AdminRole.document_importer, AdminRole.document_validator])
def test_document_account_requires_tenant(role):
    data = {
        "email": "test@example.org",
        "password": "StrongPassword1!",
        "full_name": "Document account",
        "role": role,
    }
    with pytest.raises(ValueError):
        AdminCreate(**data)
    tenant_id = uuid.uuid4()
    assert AdminCreate(**data, tenant_id=tenant_id).tenant_id == tenant_id
