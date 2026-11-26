"""Tests for health check endpoint."""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_endpoint_returns_200():
    """Health endpoint should return 200 even if some services are down."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "0.3.0-rc.1"
    assert "services" in data
    assert "postgresql" in data["services"]
    assert "redis" in data["services"]
    assert "qdrant" in data["services"]
    assert "minio" in data["services"]


@pytest.mark.asyncio
async def test_public_health_hides_dependency_exception_details():
    secret = "sensitive-test-token"
    getters = ("get_engine", "get_redis", "get_qdrant", "get_minio")
    with (
        patch("app.api.v1.health.get_engine", side_effect=RuntimeError(secret)),
        patch("app.api.v1.health.get_redis", side_effect=RuntimeError(secret)),
        patch("app.api.v1.health.get_qdrant", side_effect=RuntimeError(secret)),
        patch("app.api.v1.health.get_minio", side_effect=RuntimeError(secret)),
        patch("app.api.v1.health.logger") as logger,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/health")

    assert response.json()["status"] == "unhealthy"
    assert secret not in response.text
    assert secret not in str(logger.warning.call_args_list)
    assert all(service["status"] == "error" for service in response.json()["services"].values())
    assert logger.warning.call_count == len(getters)
