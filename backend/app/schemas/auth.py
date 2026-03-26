"""Authentication schemas — login, tokens, and JWT payloads."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    """Credentials for admin login."""

    email: EmailStr
    password: str = Field(..., min_length=1)


class AuthTokenResponse(BaseModel):
    """JWT token pair returned on successful login or refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expires


class RefreshTokenRequest(BaseModel):
    """Request to rotate a refresh token."""

    refresh_token: str


class AdminTokenPayload(BaseModel):
    """Decoded JWT token payload.

    Uses extra="ignore" so jose.jwt.decode extra fields
    don't break validation.
    """

    model_config = ConfigDict(extra="ignore")

    sub: str  # admin UUID
    role: str
    tenant_id: str | None = None
    exp: int
    iat: int
    jti: str
    type: str  # "access" | "refresh"
