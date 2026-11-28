"""Check Compose credential separation using only synthetic values."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render(runtime_user=None, runtime_password=None):
    env = os.environ.copy()
    env.update(
        POSTGRES_USER="fixture_owner",
        POSTGRES_PASSWORD="fixture_owner_password",
        REDIS_PASSWORD="fixture_redis_password",
        MINIO_ROOT_PASSWORD="fixture_minio_password",
        JWT_SECRET_KEY="fixture_jwt_secret",
        KMS_MASTER_KEY="a" * 64,
        BACKOFFICE_URL="https://fixture.invalid",
        DEMO_HOSTNAME="fixture.invalid",
        SEED_ADMIN_EMAIL="fixture@example.invalid",
        SEED_ADMIN_PASSWORD="fixture_admin_password",
    )
    for key, value in (
        ("APP_POSTGRES_USER", runtime_user),
        ("APP_POSTGRES_PASSWORD", runtime_password),
    ):
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "docker-compose.hostinger.yml"),
            "--profile",
            "maintenance",
            "--profile",
            "whatsapp-durable",
            "--profile",
            "agent-replies",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)["services"]


def check():
    legacy = render()
    assert legacy["backend"]["environment"]["POSTGRES_USER"] == "fixture_owner"
    assert (
        legacy["backend"]["environment"]["POSTGRES_PASSWORD"]
        == "fixture_owner_password"
    )
    split = render("fixture_runtime", "fixture_runtime_password")
    for service in (
        "backend",
        "ingestion-worker",
        "learning-worker",
        "purge-worker",
        "whatsapp-inbox-worker",
        "agent-reply-worker",
    ):
        settings = split[service]["environment"]
        assert settings["POSTGRES_USER"] == "fixture_runtime"
        assert settings["POSTGRES_PASSWORD"] == "fixture_runtime_password"
        assert settings["RUNTIME_DB_USER_PRESENT"] == "1"
        assert settings["RUNTIME_DB_PASSWORD_PRESENT"] == "1"
    for service in ("db-migrate", "demo-bootstrap", "postgres"):
        settings = split[service]["environment"]
        assert settings["POSTGRES_USER"] == "fixture_owner"
        assert settings["POSTGRES_PASSWORD"] == "fixture_owner_password"
    for user, password in (
        ("fixture_runtime", None),
        (None, "fixture_runtime_password"),
    ):
        settings = render(user, password)["backend"]["environment"]
        assert bool(settings["RUNTIME_DB_USER_PRESENT"]) != bool(
            settings["RUNTIME_DB_PASSWORD_PRESENT"]
        )
    print("HOSTINGER_DB_CREDENTIAL_SEPARATION_CONFIG_OK")


if __name__ == "__main__":
    check()
