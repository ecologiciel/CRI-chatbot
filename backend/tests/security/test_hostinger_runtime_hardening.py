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
        "dossier-import-worker",
        "dossier-outbox-worker",
        "learning-worker",
        "purge-worker",
        "demo-bootstrap",
        "frontend-demo",
        "frontend-admin",
    ):
        assert "ALL" in services[name]["cap_drop"], name
        assert "no-new-privileges:true" in services[name]["security_opt"], name


def test_dossier_workers_are_staged_and_outbox_defaults_off():
    root = Path(__file__).resolve().parents[3]
    compose = yaml.safe_load((root / "docker-compose.hostinger.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert services["dossier-import-worker"]["profiles"] == ["dossier-import"]
    assert services["dossier-outbox-worker"]["profiles"] == ["dossier-outbox"]
    for name in ("backend", "dossier-import-worker", "dossier-outbox-worker"):
        assert (
            services[name]["environment"]["DOSSIER_NOTIFICATION_OUTBOX_ENABLED"]
            == "${DOSSIER_NOTIFICATION_OUTBOX_ENABLED:-false}"
        )
        assert (
            services[name]["environment"]["DOSSIER_IMPORT_WORKER_ENABLED"]
            == "${DOSSIER_IMPORT_WORKER_ENABLED:-false}"
        )
        assert (
            services[name]["environment"]["DOSSIER_DURABLE_IMPORTS_ENABLED"]
            == "${DOSSIER_DURABLE_IMPORTS_ENABLED:-false}"
        )
