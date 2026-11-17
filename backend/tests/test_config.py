"""Security-focused tests for application settings."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "debug": False,
        "log_level": "INFO",
        "backoffice_url": "https://admin.example.test",
        "postgres_password": "postgres-secret",
        "redis_password": "redis-secret",
        "minio_root_password": "minio-secret",
        "gemini_api_key": "gemini-secret",
        "whatsapp_app_secret": "whatsapp-app-secret",
        "whatsapp_verify_token": "whatsapp-verify-token",
        "jwt_secret_key": "jwt-secret",
        "kms_master_key": "0" * 64,
    }
    values.update(overrides)
    return Settings(**values)


def test_defaults_are_safe_for_non_production() -> None:
    settings = Settings(
        postgres_password="postgres-secret",
        redis_password="redis-secret",
        minio_root_password="minio-secret",
        log_level="INFO",
    )
    assert settings.debug is False
    assert settings.log_level == "INFO"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("postgres_password", "CHANGE_ME"),
        ("redis_password", ""),
        ("minio_root_password", "placeholder"),
        ("gemini_api_key", ""),
        ("whatsapp_app_secret", ""),
        ("whatsapp_verify_token", ""),
        ("jwt_secret_key", "CHANGE-ME-IN-PRODUCTION"),
        ("kms_master_key", ""),
    ],
)
def test_production_rejects_missing_or_placeholder_secrets(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match=field):
        _production_settings(**{field: value})


def test_production_rejects_debug_mode() -> None:
    with pytest.raises(ValidationError, match="debug must be false"):
        _production_settings(debug=True)


def test_production_rejects_debug_log_level() -> None:
    with pytest.raises(ValidationError, match="log_level must not be DEBUG"):
        _production_settings(log_level="DEBUG")


def test_production_requires_https_backoffice_url() -> None:
    with pytest.raises(ValidationError, match="backoffice_url must use HTTPS"):
        _production_settings(backoffice_url="http://admin.example.test")


def test_production_accepts_complete_secure_configuration() -> None:
    assert _production_settings().is_production is True
