"""Fail-safe orchestration tests; real KMS transactions have separate PG tests."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Requires Linux file locking")


@pytest.fixture
def operator_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "kms_rotation_operator.py"
    spec = importlib.util.spec_from_file_location("kms_rotation_operator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def deployment(tmp_path):
    for name in (".env.demo", "docker-compose.hostinger.yml", "docker-compose.hostinger.local.yml"):
        (tmp_path / name).write_text("fixture", encoding="utf-8")
    backup = tmp_path / "backup.tar.gz.gpg"
    backup.write_bytes(b"encrypted fixture")
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    backup.with_name(backup.name + ".sha256").write_text(f"{digest}  {backup.name}\n")
    return tmp_path, backup


def test_backup_rejects_missing_bad_stale_or_symlink(operator_module, deployment, tmp_path):
    _, backup = deployment
    operator_module.verify_backup(backup)
    backup.write_bytes(b"tampered")
    with pytest.raises(ValueError):
        operator_module.verify_backup(backup)
    backup.unlink()
    with pytest.raises(ValueError):
        operator_module.verify_backup(backup)
    target = tmp_path / "other"
    target.write_bytes(b"encrypted fixture")
    backup.symlink_to(target)
    with pytest.raises(ValueError):
        operator_module.verify_backup(backup)
    backup.unlink()
    backup.write_bytes(b"encrypted fixture")
    os.utime(backup, (1, 1))
    with pytest.raises(ValueError):
        operator_module.verify_backup(backup)


def test_incomplete_manifest_cleanup_cannot_remove_unexpected_files(operator_module, deployment):
    root, _ = deployment
    op = operator_module.RotationOperator(root, "testproject", "testnetwork")
    op.state.mkdir()
    (op.state / ".manifest.tmp").write_text("partial")
    op.recover()
    assert not op.state.exists()
    op.state.mkdir()
    (op.state / "unknown").write_text("preserve")
    with pytest.raises(RuntimeError):
        op.recover()
    assert (op.state / "unknown").exists()


def test_failed_apply_rolls_back_before_restart(operator_module, deployment, monkeypatch):
    root, backup = deployment
    op = operator_module.RotationOperator(root, "testproject", "testnetwork")
    events = []
    monkeypatch.setattr(op, "assert_no_unmanaged_key_writers", lambda: None)
    monkeypatch.setattr(op, "writer_ids", lambda: ["a", "b", "c", "d"])
    monkeypatch.setattr(op, "verify_writer_images", lambda _: "sha256:" + "a" * 64)
    monkeypatch.setattr(
        op,
        "inspect",
        lambda _: {
            "State": {"Running": True},
            "Image": "sha256:" + "a" * 64,
            "Config": {"Image": "fixture:tag"},
        },
    )
    monkeypatch.setattr(operator_module, "command", lambda *args, **kwargs: "sha256:" + "a" * 64)
    monkeypatch.setattr(op, "quiesce", lambda: events.append("stopped"))
    monkeypatch.setattr(op, "start_writers", lambda: events.append("started"))

    def coordinator(action, image):
        events.append(action)
        journal = op.state / "journal"
        if action == "prepare":
            journal.mkdir()
            (journal / "READY").write_text("1")
        elif action == "apply":
            raise RuntimeError("simulated database/configuration interruption")
        elif action == "finalize-rollback":
            (journal / "READY").unlink()
            journal.rmdir()

    monkeypatch.setattr(op, "coordinator", coordinator)
    with pytest.raises(RuntimeError, match="simulated"):
        op.rotate(backup)
    assert events == [
        "stopped",
        "prepare",
        "apply",
        "stopped",
        "rollback",
        "finalize-rollback",
        "started",
    ]
    assert not op.state.exists()


def test_changed_compose_blocks_recovery_before_stopping(operator_module, deployment, monkeypatch):
    root, _ = deployment
    op = operator_module.RotationOperator(root, "testproject", "testnetwork")
    op.state.mkdir()
    operator_module.durable_json(
        op.manifest,
        {
            "project": op.project,
            "network": op.network,
            "image": "sha256:" + "a" * 64,
            "compose_hashes": [operator_module.checksum(path) for path in op.compose_files],
        },
    )
    op.compose_files[0].write_text("changed")
    monkeypatch.setattr(op, "quiesce", lambda: pytest.fail("writers should remain untouched"))
    with pytest.raises(ValueError, match="Compose configuration changed"):
        op.recover()
    assert op.manifest.exists()
