"""Fail closed when only half of the runtime database credentials is set."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize("user_flag,password_flag", [("", ""), ("1", "1")])
def test_matching_runtime_database_flags_are_valid(user_flag, password_flag):
    settings = Settings(
        _env_file=None,
        postgres_password="fixture",
        redis_password="fixture",
        minio_root_password="fixture",
        runtime_db_user_present=user_flag,
        runtime_db_password_present=password_flag,
    )
    assert settings.runtime_db_user_present == user_flag


@pytest.mark.parametrize("user_flag,password_flag", [("1", ""), ("", "1")])
def test_partial_runtime_database_credentials_are_rejected(user_flag, password_flag):
    with pytest.raises(ValidationError, match="must be configured together"):
        Settings(
            _env_file=None,
            postgres_password="fixture",
            redis_password="fixture",
            minio_root_password="fixture",
            runtime_db_user_present=user_flag,
            runtime_db_password_present=password_flag,
        )
