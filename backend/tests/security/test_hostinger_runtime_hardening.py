"""Hostinger's internet-facing app and workers should not gain Linux privileges."""

from pathlib import Path

import yaml


def test_hostinger_application_containers_drop_capabilities_and_escalation():
    root = Path(__file__).resolve().parents[3]
    compose = yaml.safe_load((root / "docker-compose.hostinger.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    for name in (
        "backend",
        "ingestion-worker",
        "learning-worker",
        "purge-worker",
        "demo-bootstrap",
        "frontend-demo",
        "frontend-admin",
    ):
        assert "ALL" in services[name]["cap_drop"], name
        assert "no-new-privileges:true" in services[name]["security_opt"], name
