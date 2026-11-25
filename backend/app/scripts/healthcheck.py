"""Check API readiness, including its required infrastructure services."""

from __future__ import annotations

import sys

import httpx

REQUIRED_SERVICES = frozenset({"postgresql", "redis", "qdrant", "minio"})


def is_ready(url: str = "http://localhost:8000/api/v1/health") -> bool:
    """Fail closed for failed requests, malformed responses, or degraded services."""
    try:
        response = httpx.get(url, timeout=4.0)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("status") != "healthy":
            return False
        services = body.get("services")
        return isinstance(services, dict) and all(
            isinstance(services.get(name), dict) and services[name].get("status") == "ok"
            for name in REQUIRED_SERVICES
        )
    except (httpx.HTTPError, ValueError, TypeError):
        return False


def main() -> None:
    sys.exit(0 if is_ready() else 1)


if __name__ == "__main__":
    main()
