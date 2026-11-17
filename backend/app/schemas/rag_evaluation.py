"""API schemas for tenant-scoped, non-blocking RAG evaluation."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RAGEvaluationCaseCreate(BaseModel):
    query: str = Field(..., min_length=1, max_length=5000)
    language: str = Field(default="fr", pattern=r"^(fr|ar|en)$")
    expected_document_ids: list[uuid.UUID] = Field(default_factory=list)
    expects_abstention: bool = False


class RAGEvaluationCaseResponse(RAGEvaluationCaseCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool
    human_faithfulness: bool | None
    created_at: datetime
    updated_at: datetime


class RAGEvaluationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_count: int
    metrics: dict
    triggered_by: uuid.UUID | None
    created_at: datetime
