"""Pytest configuration — set required env vars before test collection.

Settings requires POSTGRES_PASSWORD, REDIS_PASSWORD, MINIO_ROOT_PASSWORD.
These must be set before any module imports app.main (which triggers Settings()).
"""

import os
import sys
import types


def pytest_configure(config):
    """Set required environment variables for test settings."""
    os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
    os.environ.setdefault("REDIS_PASSWORD", "test-password")
    os.environ.setdefault("MINIO_ROOT_PASSWORD", "test-password")
    os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key")

    # langchain-core>=1.0 tries to read langchain.debug but the full
    # langchain package may not be installed. Provide a stub to avoid
    # AttributeError during LangGraph graph.ainvoke().
    if "langchain" not in sys.modules:
        _stub = types.ModuleType("langchain")
        _stub.debug = False  # type: ignore[attr-defined]
        sys.modules["langchain"] = _stub
