"""Schemas for the anonymous, tenant-scoped web demonstration channel."""

from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


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
    page_numbers: list[int] = Field(default_factory=list)
    language: str | None = None

    @field_validator("url", mode="before")
    @classmethod
    def safe_public_url(cls, value: object) -> str | None:
        """Do not render active-content links or credentials from stored metadata."""
        if value is None:
            return None
        if (
            not isinstance(value, str)
            or len(value) > 1000
            or "\\" in value
            or any(ord(char) <= 32 or ord(char) == 127 for char in value)
        ):
            return None
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme.lower() not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                return None
            _ = parsed.port  # Invalid ports raise ValueError.
        except ValueError:
            return None
        return value


class PublicChatResponse(BaseModel):
    answer: str
    language: str
    sources: list[PublicSource] = Field(default_factory=list)
    disclaimer: str
