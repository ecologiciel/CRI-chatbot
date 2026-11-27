"""Centralized configuration via pydantic-settings.

All settings are loaded from environment variables or .env file.
NEVER use os.getenv() directly anywhere in the codebase — always inject Settings via Depends.
"""

from pydantic import Field, field_validator, model_validator
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
    log_level: str = Field(default="INFO", description="DEBUG | INFO | WARNING | ERROR")
    debug: bool = Field(default=False)

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
    gemini_fallback_model: str = Field(default="", description="Optional fallback generation model")
    gemini_max_output_tokens: int = Field(default=2048, description="Max output tokens per request")
    gemini_temperature: float = Field(default=0.3, description="Sampling temperature (0.0-2.0)")
    gemini_timeout: float = Field(
        default=15.0, gt=0, description="Total generation timeout including retries, in seconds"
    )
    embedding_model: str = Field(
        default="gemini-embedding-001",
        description="Google Gemini embedding model",
    )
    embedding_dimension: int = Field(default=768, description="Embedding vector dimension")
    embedding_batch_size: int = Field(default=100, description="Max texts per batch embed call")
    rag_hybrid_search_enabled: bool = Field(
        default=False, description="Combine lexical and semantic retrieval"
    )
    # TODO Phase 2: embedding_fallback_model for local multilingual-e5-large

    # --- WhatsApp ---
    whatsapp_app_secret: str = Field(
        default="", description="Meta App Secret for HMAC webhook validation"
    )
    whatsapp_verify_token: str = Field(default="", description="Webhook verification token")
    whatsapp_durable_inbox_enabled: bool = Field(
        default=False, description="Use transactional WhatsApp webhook intake"
    )
    dossier_notification_outbox_enabled: bool = Field(
        default=False, description="Use the staged transactional dossier notification outbox"
    )
    webhook_proxy_shared_secret: str = Field(
        default="", description="Optional shared secret required from the Cloudflare webhook relay"
    )
    whatsapp_webhook_max_body_bytes: int = Field(
        default=1_048_576,
        ge=1024,
        le=10_485_760,
        description="Maximum inbound WhatsApp webhook body size in bytes",
    )

    # --- JWT Auth ---
    jwt_secret_key: str = Field(
        default="CHANGE-ME-IN-PRODUCTION", description="Required in production"
    )
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=30)
    jwt_refresh_token_expire_days: int = Field(default=7)

    # --- KMS (Key Management Service) ---
    kms_master_key: str = Field(
        default="",
        description="Hex-encoded 32 bytes (64 hex chars) for envelope encryption. "
        'Generate with: python -c "import secrets; print(secrets.token_hex(32))"',
    )

    # --- Monitoring ---
    grafana_user: str = Field(default="admin")
    grafana_password: str = Field(default="admin")

    # --- Knowledge Base ---
    kb_max_file_size_mb: int = Field(default=10, description="Max KB upload file size in MB")

    # Malware scanning is enabled explicitly for deployments with a ClamAV daemon.
    antivirus_enabled: bool = False
    antivirus_host: str = "clamav"
    extraction_service_url: str = ""
    antivirus_port: int = Field(default=3310, ge=1, le=65535)
    antivirus_timeout: float = Field(default=30.0, gt=0, le=120)
    antivirus_max_signature_age_days: int = Field(default=7, ge=1, le=30)

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
        from urllib.parse import quote_plus

        return (
            f"redis://:{quote_plus(self.redis_password)}@" f"{self.redis_host}:{self.redis_port}/0"
        )

    @property
    def kb_max_file_size_bytes(self) -> int:
        """Max file size in bytes for KB uploads."""
        return self.kb_max_file_size_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """Reject unsafe or incomplete settings before serving production traffic."""
        if not self.is_production:
            return self

        if self.debug:
            raise ValueError("debug must be false in production")
        if self.log_level == "DEBUG":
            raise ValueError("log_level must not be DEBUG in production")
        if not self.backoffice_url.startswith("https://"):
            raise ValueError("backoffice_url must use HTTPS in production")

        required_secrets = {
            "postgres_password": self.postgres_password,
            "redis_password": self.redis_password,
            "minio_root_password": self.minio_root_password,
            "gemini_api_key": self.gemini_api_key,
            "whatsapp_app_secret": self.whatsapp_app_secret,
            "whatsapp_verify_token": self.whatsapp_verify_token,
            "jwt_secret_key": self.jwt_secret_key,
            "kms_master_key": self.kms_master_key,
        }
        invalid = [name for name, value in required_secrets.items() if _is_placeholder(value)]
        if invalid:
            msg = f"production requires configured secrets: {', '.join(invalid)}"
            raise ValueError(msg)
        return self

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            msg = f"log_level must be one of {allowed}"
            raise ValueError(msg)
        return v.upper()

    @field_validator("kms_master_key")
    @classmethod
    def validate_kms_master_key(cls, v: str) -> str:
        if not v:
            return v  # Empty allowed in dev
        if len(v) != 64:
            msg = "kms_master_key must be exactly 64 hex characters (32 bytes)"
            raise ValueError(msg)
        try:
            bytes.fromhex(v)
        except ValueError:
            msg = "kms_master_key must be a valid hex string"
            raise ValueError(msg) from None
        return v


def _is_placeholder(value: str) -> bool:
    """Return whether a required secret is missing or an example value."""
    normalized = value.strip().lower()
    return not normalized or normalized in {
        "change_me",
        "change-me",
        "change-me-in-production",
        "example",
        "placeholder",
    }


# Singleton — importable partout
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create the Settings singleton."""
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = Settings()
    return _settings
