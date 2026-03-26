"""Centralized configuration via pydantic-settings.

All settings are loaded from environment variables or .env file.
NEVER use os.getenv() directly anywhere in the codebase — always inject Settings via Depends.
"""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Environment ---
    environment: str = Field(
        default="development", description="development | staging | production"
    )
    log_level: str = Field(default="DEBUG", description="DEBUG | INFO | WARNING | ERROR")
    debug: bool = Field(default=True)

    # --- PostgreSQL ---
    postgres_host: str = Field(default="postgres")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="cri_platform")
    postgres_user: str = Field(default="cri_admin")
    postgres_password: str = Field(
        ..., description="Required — generate with: openssl rand -base64 32"
    )

    # --- Redis ---
    redis_host: str = Field(default="redis")
    redis_port: int = Field(default=6379)
    redis_password: str = Field(..., description="Required")

    # --- Qdrant ---
    qdrant_host: str = Field(default="qdrant")
    qdrant_http_port: int = Field(default=6333)
    qdrant_grpc_port: int = Field(default=6334)

    # --- MinIO ---
    minio_endpoint: str = Field(default="minio:9000")
    minio_root_user: str = Field(default="cri_minio")
    minio_root_password: str = Field(..., description="Required")
    minio_use_ssl: bool = Field(default=False)

    # --- Gemini API ---
    gemini_api_key: str = Field(default="", description="Google AI Studio API key")

    # --- AI / LLM ---
    gemini_model: str = Field(
        default="gemini-2.5-flash", description="Gemini model ID for generation"
    )
    gemini_max_output_tokens: int = Field(
        default=2048, description="Max output tokens per request"
    )
    gemini_temperature: float = Field(
        default=0.3, description="Sampling temperature (0.0-2.0)"
    )
    gemini_timeout: float = Field(
        default=30.0, description="Request timeout in seconds"
    )
    embedding_model: str = Field(
        default="text-embedding-004", description="Google embedding model"
    )
    embedding_dimension: int = Field(
        default=768, description="Embedding vector dimension"
    )
    embedding_batch_size: int = Field(
        default=100, description="Max texts per batch embed call"
    )
    # TODO Phase 2: embedding_fallback_model for local multilingual-e5-large

    # --- WhatsApp ---
    whatsapp_app_secret: str = Field(
        default="", description="Meta App Secret for HMAC webhook validation"
    )
    whatsapp_verify_token: str = Field(
        default="", description="Webhook verification token"
    )

    # --- JWT Auth ---
    jwt_secret_key: str = Field(
        default="CHANGE-ME-IN-PRODUCTION", description="Required in production"
    )
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=30)
    jwt_refresh_token_expire_days: int = Field(default=7)

    # --- Monitoring ---
    grafana_user: str = Field(default="admin")
    grafana_password: str = Field(default="admin")

    # --- Knowledge Base ---
    kb_max_file_size_mb: int = Field(
        default=10, description="Max KB upload file size in MB"
    )

    # --- CORS ---
    backoffice_url: str = Field(default="http://localhost:3000")

    # --- Computed properties ---
    @property
    def database_url(self) -> str:
        """Async PostgreSQL connection string."""
        from urllib.parse import quote_plus
        return (
            f"postgresql+asyncpg://{quote_plus(self.postgres_user)}:{quote_plus(self.postgres_password)}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        """Sync PostgreSQL URL for Alembic migrations."""
        from urllib.parse import quote_plus
        return (
            f"postgresql://{quote_plus(self.postgres_user)}:{quote_plus(self.postgres_password)}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        """Redis connection string."""
        return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"

    @property
    def kb_max_file_size_bytes(self) -> int:
        """Max file size in bytes for KB uploads."""
        return self.kb_max_file_size_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            msg = f"log_level must be one of {allowed}"
            raise ValueError(msg)
        return v.upper()


# Singleton — importable partout
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create the Settings singleton."""
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = Settings()
    return _settings
