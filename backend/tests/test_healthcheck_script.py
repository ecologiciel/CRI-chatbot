"""Container readiness must not mistake degraded dependencies for health."""

from unittest.mock import Mock, patch

import httpx
import pytest

from app.scripts.healthcheck import is_ready


def response(body, status=200):
    request = httpx.Request("GET", "http://localhost:8000/api/v1/health")
    return httpx.Response(status, json=body, request=request)


@pytest.mark.parametrize(
    ("body", "status", "expected"),
    [
        (
            {
                "status": "healthy",
                "services": {
                    s: {"status": "ok"} for s in ("postgresql", "redis", "qdrant", "minio")
                },
            },
            200,
            True,
        ),
        ({"status": "degraded", "services": {}}, 200, False),
        ({"status": "unhealthy", "services": {}}, 200, False),
        ({"status": "healthy", "services": {}}, 200, False),
        ({"status": "healthy", "services": {"postgresql": {"status": "error"}}}, 200, False),
        ({"status": "healthy", "services": None}, 200, False),
        ({"status": "healthy"}, 503, False),
        ([], 200, False),
    ],
)
def test_readiness_uses_status_and_required_services(body, status, expected):
    with patch("app.scripts.healthcheck.httpx.get", return_value=response(body, status)):
        assert is_ready() is expected


def test_readiness_rejects_connection_failure_or_invalid_json():
    with patch("app.scripts.healthcheck.httpx.get", side_effect=httpx.ConnectError("unavailable")):
        assert not is_ready()
    bad = Mock()
    bad.json.side_effect = ValueError("invalid JSON")
    with patch("app.scripts.healthcheck.httpx.get", return_value=bad):
        assert not is_ready()
