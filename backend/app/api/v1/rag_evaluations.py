"""Admin APIs for non-blocking, tenant-scoped RAG evaluation monitoring."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.core.rbac import require_role
from app.core.tenant import TenantContext, get_current_tenant
from app.models.enums import AdminRole
from app.models.rag_evaluation import RAGEvaluationCase, RAGEvaluationRun
from app.schemas.auth import AdminTokenPayload
from app.schemas.rag_evaluation import (
    RAGEvaluationCaseCreate,
    RAGEvaluationCaseResponse,
    RAGEvaluationRunResponse,
)
from app.services.rag.evaluation import get_rag_evaluation_service

router = APIRouter(prefix="/kb/evaluations", tags=["rag-evaluations"])


@router.post("/cases", response_model=RAGEvaluationCaseResponse, status_code=201)
async def create_case(
    data: RAGEvaluationCaseCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> RAGEvaluationCase:
    async with tenant.db_session() as session:
        case = RAGEvaluationCase(
            query=data.query,
            language=data.language,
            expected_document_ids=[str(value) for value in data.expected_document_ids],
            expects_abstention=data.expects_abstention,
        )
        session.add(case)
        await session.flush()
        await session.refresh(case)
        return case


@router.get("/cases", response_model=list[RAGEvaluationCaseResponse])
async def list_cases(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> list[RAGEvaluationCase]:
    async with tenant.db_session() as session:
        result = await session.execute(select(RAGEvaluationCase).order_by(RAGEvaluationCase.created_at.desc()))
        return list(result.scalars())


@router.post("/runs", response_model=RAGEvaluationRunResponse, status_code=201)
async def run_evaluation(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> RAGEvaluationRun:
    return await get_rag_evaluation_service().run(tenant, uuid.UUID(admin.sub))


@router.get("/runs", response_model=list[RAGEvaluationRunResponse])
async def list_runs(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> list[RAGEvaluationRun]:
    async with tenant.db_session() as session:
        result = await session.execute(select(RAGEvaluationRun).order_by(RAGEvaluationRun.created_at.desc()).limit(50))
        return list(result.scalars())
