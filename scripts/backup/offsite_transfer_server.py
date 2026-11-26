"""Temporary, read-only transfer of one verified encrypted backup.

The reverse proxy must terminate TLS. The bearer token and server lifetime are
mandatory. This process never serves directories, logs requests or writes data.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

NAME = re.compile(r"hostinger-data-[0-9]{8}T[0-9]{6}Z-[0-9]+\.tar\.gz\.gpg")
TOKEN = re.compile(r"[0-9a-f]{64}")
MAX_SIZE = 5 * 1024**3


def checked_file(directory: Path, name: str, maximum: int) -> bytes:
    """Read a small regular file without following links."""
    fd = os.open(directory / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError("unsafe file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return stream.read(maximum + 1)
    finally:
        os.close(fd)


def prepare(directory: Path) -> tuple[int, dict]:
    """Open and checksum the exact last successful encrypted archive."""
    lines = (
        checked_file(directory, "scheduled-backup.status", 1024)
        .decode("ascii")
        .splitlines()
    )
    if (
        len(lines) != 3
        or not re.fullmatch(r"finished_utc=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", lines[0])
        or lines[1] != "status=success"
    ):
        raise ValueError("no successful backup")
    name = lines[2].removeprefix("archive=")
    if lines[2] != "archive=" + name or not NAME.fullmatch(name):
        raise ValueError("invalid archive name")
    manifest = checked_file(directory, name + ".sha256", 512).decode("ascii").strip()
    match = re.fullmatch(r"([0-9a-f]{64})  (.+)", manifest)
    if not match or match.group(2) != name:
        raise ValueError("invalid checksum")
    fd = os.open(directory / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_SIZE:
            raise ValueError("unsafe archive")
        digest = hashlib.sha256()
        with os.fdopen(os.dup(fd), "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if not hmac.compare_digest(digest.hexdigest(), match.group(1)):
            raise ValueError("checksum mismatch")
        os.lseek(fd, 0, os.SEEK_SET)
        return fd, {
            "name": name,
            "sha256": digest.hexdigest(),
            "size": info.st_size,
            "finished_utc": lines[0][13:],
        }
    except BaseException:
        os.close(fd)
        raise


def serve(directory: Path, token: str, ttl: int, port: int = 8080) -> None:
    if not TOKEN.fullmatch(token) or not 10 <= ttl <= 600:
        raise ValueError("invalid token or lifetime")
    fd, metadata = prepare(directory)
    deadline = time.monotonic() + ttl

    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            if not hmac.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + token
            ):
                self.send_error(403)
                return
            if time.monotonic() >= deadline:
                self.send_error(410)
                return
            if self.path == "/_offsite/manifest":
                payload = json.dumps(metadata).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)
            elif self.path == "/_offsite/archive":
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(metadata["size"]))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                os.lseek(fd, 0, os.SEEK_SET)
                while time.monotonic() < deadline:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            else:
                self.send_error(404)

    server = HTTPServer(("0.0.0.0", port), Handler)
    server.timeout = 1
    try:
        while time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
        os.close(fd)


if __name__ == "__main__":
    serve(
        Path(os.environ.get("BACKUP_DIR", "/backups")),
        os.environ["TRANSFER_TOKEN"],
        int(os.environ.get("TRANSFER_TTL", "300")),
    )
