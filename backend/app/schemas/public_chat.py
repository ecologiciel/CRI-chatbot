"""Schemas for the anonymous, tenant-scoped web demonstration channel."""

from pydantic import BaseModel, Field


class PublicSessionResponse(BaseModel):
    tenant_slug: str
    tenant_name: str
    expires_in_seconds: int


class PublicChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    language: str | None = Field(default=None, pattern=r"^(fr|ar|en)$")


class PublicSource(BaseModel):
    title: str | None = None
    url: str | None = None
    published_at: str | None = None
    section_path: list[str] = Field(default_factory=list)


class PublicChatResponse(BaseModel):
    answer: str
    language: str
    sources: list[PublicSource] = Field(default_factory=list)
    disclaimer: str
