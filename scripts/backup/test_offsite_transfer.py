"""Tests for the temporary encrypted backup transfer server."""

import hashlib
import importlib.util
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "offsite_transfer", Path(__file__).with_name("offsite_transfer_server.py")
)
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)


@pytest.fixture
def backup(tmp_path, monkeypatch):
    # Windows lacks these flags; actual symlink rejection is verified on Linux.
    monkeypatch.setattr(os, "O_NOFOLLOW", getattr(os, "O_NOFOLLOW", 0), raising=False)
    monkeypatch.setattr(os, "O_NONBLOCK", getattr(os, "O_NONBLOCK", 0), raising=False)
    name = "hostinger-data-20261126T041450Z-48.tar.gz.gpg"
    content = b"synthetic encrypted backup"
    (tmp_path / name).write_bytes(content)
    (tmp_path / (name + ".sha256")).write_text(
        hashlib.sha256(content).hexdigest() + "  " + name + "\n"
    )
    (tmp_path / "scheduled-backup.status").write_text(
        "finished_utc=2026-11-26T04:15:21Z\nstatus=success\narchive=" + name + "\n"
    )
    return tmp_path, name, content


def test_prepare_rejects_mismatched_checksum(backup):
    directory, name, _ = backup
    (directory / name).write_bytes(b"modified")
    with pytest.raises(ValueError, match="checksum mismatch"):
        server_module.prepare(directory)


def test_rejects_unsafe_name(backup):
    directory, _, _ = backup
    (directory / "scheduled-backup.status").write_text(
        "finished_utc=2026-11-26T04:15:21Z\nstatus=success\narchive=../private\n"
    )
    with pytest.raises(ValueError, match="invalid archive name"):
        server_module.prepare(directory)


def test_authenticated_transfer_and_no_other_paths(backup):
    directory, name, content = backup
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    token = "a" * 64
    thread = threading.Thread(
        target=server_module.serve, args=(directory, token, 10, port), daemon=True
    )
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(40):
        try:
            urllib.request.urlopen(base + "/_offsite/manifest", timeout=1)
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
            break
        except OSError:
            time.sleep(0.05)
    else:
        pytest.fail("server did not start")
    headers = {"Authorization": "Bearer " + token}
    request = lambda path: urllib.request.Request(base + path, headers=headers)  # noqa: E731
    with urllib.request.urlopen(request("/_offsite/manifest")) as response:
        metadata = json.load(response)
    assert metadata["name"] == name
    assert metadata["sha256"] == hashlib.sha256(content).hexdigest()
    with urllib.request.urlopen(request("/_offsite/archive")) as response:
        assert response.read() == content
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request("/scheduled-backup.status"))
    assert exc.value.code == 404
