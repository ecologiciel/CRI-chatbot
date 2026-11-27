#!/usr/bin/env python3
"""Offline, crash-recoverable Hostinger KMS master-key rewrap.

Run inside a trusted Docker CLI environment with the deployment directory and
Docker socket mounted at their host paths. No key values are printed. The
operator must ensure no external process writes to the tenant-key table.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REQUIRED_WRITERS = ("backend", "ingestion-worker", "learning-worker", "purge-worker")
OPTIONAL_WRITERS = (
    "whatsapp-inbox-worker",
    "dossier-import-worker",
    "dossier-outbox-worker",
    "agent-reply-worker",
)
WRITERS = REQUIRED_WRITERS + OPTIONAL_WRITERS
STATE_NAME = ".kms-maintenance"


def valid_writer_services(services: object) -> bool:
    """Accept required writers and any ordered, unique optional subset."""
    if not isinstance(services, list) or not all(
        isinstance(item, str) for item in services
    ):
        return False
    required = list(REQUIRED_WRITERS)
    optional = services[len(required) :]
    return services[: len(required)] == required and optional == [
        item for item in OPTIONAL_WRITERS if item in optional
    ]


def command(*args: str, capture: bool = False) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        # Environment contents and container output are never written to logs.
        raise RuntimeError(f"Command failed: {' '.join(args[:3])}")
    return result.stdout.strip() if capture else ""


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_json(path: Path, data: dict) -> None:
    tmp = path.parent / ".manifest.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(data, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    fsync_directory(path.parent)


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_backup(path: Path) -> None:
    """Require a recent, non-symlinked encrypted archive and its exact checksum."""
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("A recent encrypted backup file is required")
    if not path.name.endswith(".tar.gz.gpg") or path.stat().st_size == 0:
        raise ValueError("Invalid encrypted backup")
    age = time.time() - path.stat().st_mtime
    if not 0 <= age <= 24 * 60 * 60:
        raise ValueError("Backup is older than 24 hours or has a future timestamp")
    checksum_file = path.with_name(path.name + ".sha256")
    if checksum_file.is_symlink() or not checksum_file.is_file():
        raise ValueError("Backup checksum file is missing")
    expected = checksum_file.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{64}  " + re.escape(path.name), expected):
        raise ValueError("Invalid backup checksum record")
    if checksum(path) != expected[:64]:
        raise ValueError("Backup checksum does not match")
    # This only verifies the OpenPGP packet structure, not decryptability or a
    # successful restore; those must be checked independently on another host.
    with tempfile.TemporaryDirectory(prefix="kms-backup-packets-") as keydir:
        env = {**os.environ, "GNUPGHOME": keydir}
        result = subprocess.run(
            ["gpg", "--batch", "--no-options", "--list-packets", str(path)],
            capture_output=True,
            timeout=60,
            env=env,
        )
    encrypted_packets = (b":encrypted data packet:", b":aead encrypted packet:")
    if b":pubkey enc packet:" not in result.stdout or not any(
        packet in result.stdout for packet in encrypted_packets
    ):
        raise ValueError("Backup does not contain expected encrypted OpenPGP packets")


class RotationOperator:
    def __init__(self, root: Path, project: str, network: str) -> None:
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise ValueError("Deployment directory must be an absolute, real directory")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,62}", project):
            raise ValueError("Invalid Compose project name")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{1,127}", network):
            raise ValueError("Invalid data network name")
        self.root = root
        self.project = project
        self.network = network
        self.state = root / STATE_NAME
        self.manifest = self.state / "manifest.json"
        self.env = root / ".env.demo"
        self.compose_files = (
            root / "docker-compose.hostinger.yml",
            root / "docker-compose.hostinger.local.yml",
        )
        for path in (self.env, *self.compose_files):
            if path.is_symlink() or not path.is_file():
                raise ValueError("Deployment configuration is missing or unsafe")

    def compose(self, *args: str, capture: bool = False) -> str:
        return command(
            "docker",
            "compose",
            "--project-name",
            self.project,
            "--env-file",
            str(self.env),
            "-f",
            str(self.compose_files[0]),
            "-f",
            str(self.compose_files[1]),
            "--profile",
            "whatsapp-durable",
            "--profile",
            "dossier-import",
            "--profile",
            "dossier-outbox",
            "--profile",
            "agent-replies",
            *args,
            capture=capture,
        )

    def inspect(self, container: str) -> dict:
        return json.loads(command("docker", "inspect", container, capture=True))[0]

    def containers(self, service: str) -> list[str]:
        output = command(
            "docker",
            "ps",
            "-aq",
            "--no-trunc",
            "--filter",
            f"label=com.docker.compose.project={self.project}",
            "--filter",
            f"label=com.docker.compose.service={service}",
            capture=True,
        )
        return output.splitlines() if output else []

    def writer_ids(
        self, require_one: bool = True, services: tuple[str, ...] | None = None
    ) -> list[str]:
        ids = []
        for service in services or WRITERS:
            matches = self.containers(service)
            required = service in REQUIRED_WRITERS or services is not None
            if len(matches) > 1 or (require_one and required and len(matches) != 1):
                raise RuntimeError(f"Expected exactly one {service} container")
            ids.extend(matches)
        return ids

    def verify_writer_images(self, ids: list[str]) -> str:
        """Refuse a stale/mutated tag that Compose would recreate differently."""
        entries = [self.inspect(cid) for cid in ids]
        image = entries[0]["Image"]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
            raise ValueError("Invalid writer image identifier")
        for item in entries:
            if item["Image"] != image:
                raise RuntimeError("Application writers do not share the same image")
            current = command(
                "docker",
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                item["Config"]["Image"],
                capture=True,
            )
            if current != image:
                raise RuntimeError("An application image tag changed after startup")
        return image

    def assert_no_unmanaged_key_writers(self) -> None:
        """Refuse any other container holding a KMS key on the data network."""
        command("docker", "network", "inspect", self.network, capture=True)
        allowed = set(self.writer_ids(require_one=False))
        all_ids = command(
            "docker",
            "ps",
            "-aq",
            "--no-trunc",
            "--filter",
            f"network={self.network}",
            capture=True,
        ).splitlines()
        for cid in all_ids:
            if cid in allowed:
                continue
            item = self.inspect(cid)
            if self.network not in item.get("NetworkSettings", {}).get("Networks", {}):
                continue
            has_key = any(
                value.startswith("KMS_MASTER_KEY=")
                for value in (item["Config"].get("Env") or [])
            )
            if has_key:
                raise RuntimeError(
                    "Another possible KMS writer is connected to the data network"
                )

    def quiesce(self) -> None:
        self.assert_no_unmanaged_key_writers()
        ids = self.writer_ids(require_one=False)
        # Restart policies are persisted by Docker; a host reboot cannot
        # silently revive an old environment during the database switch.
        for cid in ids:
            command("docker", "update", "--restart=no", cid)
        for cid in ids:
            if self.inspect(cid)["State"]["Running"]:
                # Ingestion jobs are allowed up to ten minutes; give workers
                # time to finish rather than killing an active transaction.
                command("docker", "stop", "--time", "780", cid)
        for cid in ids:
            info = self.inspect(cid)
            if (
                info["State"]["Running"]
                or info["HostConfig"]["RestartPolicy"]["Name"] != "no"
            ):
                raise RuntimeError("A KMS writer did not stop safely")

    def coordinator(self, action: str, image: str) -> None:
        command(
            "docker",
            "run",
            "--rm",
            "--user",
            "0",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:noexec,nosuid,nodev,size=32m",
            "--network",
            self.network,
            "--env-file",
            str(self.env),
            "--env",
            "POSTGRES_HOST=postgres",
            "--mount",
            f"type=bind,src={self.root},dst=/deployment",
            "--entrypoint",
            "python",
            image,
            "-m",
            "app.scripts.kms_rotation",
            action,
            "--env-path",
            "/deployment/.env.demo",
            "--journal",
            f"/deployment/{STATE_NAME}/journal",
        )

    def start_writers(self, services: tuple[str, ...]) -> None:
        self.compose(
            "up", "-d", "--no-deps", "--no-build", "--force-recreate", "backend"
        )
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            ids = self.containers("backend")
            if (
                len(ids) == 1
                and self.inspect(ids[0])["State"].get("Health", {}).get("Status")
                == "healthy"
            ):
                break
            time.sleep(2)
        else:
            raise RuntimeError("Backend did not become healthy")
        self.compose(
            "up", "-d", "--no-deps", "--no-build", "--force-recreate", *services[1:]
        )
        for cid in self.writer_ids(services=services):
            if not self.inspect(cid)["State"]["Running"]:
                raise RuntimeError("A writer did not restart")

    def load_manifest(self) -> dict:
        if (
            self.state.is_symlink()
            or not self.state.is_dir()
            or self.manifest.is_symlink()
        ):
            raise ValueError("Unsafe maintenance state")
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        if data.get("project") != self.project or data.get("network") != self.network:
            raise ValueError("Maintenance state belongs to a different deployment")
        if data.get("compose_hashes") != [
            checksum(path) for path in self.compose_files
        ]:
            raise ValueError("Compose configuration changed during maintenance")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", data.get("image", "")):
            raise ValueError("Invalid maintenance image identifier")
        services = data.get("writer_services", list(REQUIRED_WRITERS))
        if not valid_writer_services(services):
            raise ValueError("Invalid maintenance writer services")
        refs = data.get("image_references")
        if not isinstance(refs, list) or len(refs) != len(services):
            raise ValueError("Invalid application image references")
        for ref in refs:
            if not isinstance(ref, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._/@:-]{0,511}", ref
            ):
                raise ValueError("Invalid application image reference")
            current = command(
                "docker", "image", "inspect", "--format", "{{.Id}}", ref, capture=True
            )
            if current != data["image"]:
                raise ValueError("Application image changed during maintenance")
        return data

    def clear_state(self) -> None:
        # Never recursively delete unexpected files or the journal.
        if (self.state / "journal").exists():
            raise RuntimeError("KMS recovery journal still exists")
        for path in self.state.iterdir():
            if (
                path.name not in {"manifest.json", ".manifest.tmp"}
                or path.is_symlink()
                or not path.is_file()
            ):
                raise RuntimeError("Unexpected maintenance state; refusing cleanup")
        for path in self.state.iterdir():
            path.unlink()
        fsync_directory(self.state)
        self.state.rmdir()
        fsync_directory(self.root)

    def recover(self) -> None:
        if self.state.is_dir() and not self.manifest.exists():
            # The manifest is fully synced before any container is touched.
            self.clear_state()
            print("Incomplete maintenance preparation removed.", flush=True)
            return
        data = self.load_manifest()
        self.quiesce()
        journal = self.state / "journal"
        if journal.exists():
            if (journal / "COMMITTED").exists():
                self.coordinator("finalize", data["image"])
            elif (journal / "ROLLED_BACK").exists():
                self.coordinator("finalize-rollback", data["image"])
            elif (journal / "READY").exists():
                self.coordinator("rollback", data["image"])
                self.coordinator("finalize-rollback", data["image"])
            else:
                self.coordinator("abort-incomplete", data["image"])
        self.start_writers(tuple(data.get("writer_services", REQUIRED_WRITERS)))
        self.clear_state()
        print("Maintenance recovered; writers restarted.", flush=True)

    def rotate(self, backup: Path) -> None:
        verify_backup(backup)
        if self.state.exists() or self.state.is_symlink():
            raise RuntimeError("Maintenance state exists; recover it before starting")
        self.assert_no_unmanaged_key_writers()
        ids = self.writer_ids()
        services = REQUIRED_WRITERS + tuple(
            service for service in OPTIONAL_WRITERS if self.containers(service)
        )
        if not all(self.inspect(cid)["State"]["Running"] for cid in ids):
            raise RuntimeError(
                "Every application writer must be running before rotation"
            )
        image = self.verify_writer_images(ids)
        self.state.mkdir(mode=0o700)
        fsync_directory(self.root)
        image_references = [self.inspect(cid)["Config"]["Image"] for cid in ids]
        durable_json(
            self.manifest,
            {
                "project": self.project,
                "network": self.network,
                "image": image,
                "image_references": image_references,
                "writer_services": list(services),
                "compose_hashes": [checksum(path) for path in self.compose_files],
            },
        )
        try:
            self.quiesce()
            self.coordinator("prepare", image)
            self.coordinator("apply", image)
            self.start_writers(services)
            self.coordinator("finalize", image)
            self.clear_state()
        except Exception:
            print(
                "Rotation failed; attempting recovery without exposing keys.",
                file=sys.stderr,
            )
            try:
                self.recover()
            except Exception:
                print(
                    "Recovery incomplete; maintenance state retained.", file=sys.stderr
                )
            raise
        print("KMS master rewrap completed and writers restarted.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("rotate", "recover"))
    parser.add_argument(
        "--deployment-dir", type=Path, default=Path("/opt/chatbot-demo")
    )
    parser.add_argument("--project", default="chatbot-demo")
    parser.add_argument("--network", default="demo-data")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    operator = RotationOperator(args.deployment_dir, args.project, args.network)
    lock_path = operator.root / ".kms-rotation.lock"
    if lock_path.is_symlink():
        raise ValueError("Unsafe rotation lock")
    with lock_path.open("a") as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "rotate":
            if args.backup is None:
                parser.error("--backup is required for rotation")
            operator.rotate(args.backup)
        else:
            operator.recover()


if __name__ == "__main__":
    main()
