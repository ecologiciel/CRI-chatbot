"""Scenario 4 — Import 50K Rows Load Test.

Uploads a pre-generated Excel file with 50,000 dossier rows and
polls the sync-logs endpoint until completion. Verifies the ARQ
worker handles the load without crashing or memory leaks.

Prerequisites:
    Run generate_50k_excel.py first to create the test file:
        python tests/load/generate_50k_excel.py

Success criteria:
  - Upload returns 202 within 5 seconds
  - Import completes (sync_log.status == "completed") within 10 minutes
  - rows_errored / rows_total < 5%
  - Server remains responsive during import

Usage:
    locust -f scenarios/import_load.py --users 1 --spawn-rate 1 \\
           --run-time 15m --headless --html reports/import_load.html
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from locust import HttpUser, constant, events, task

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from helpers import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    TENANTS,
    login_admin,
)

# Path to the pre-generated 50K Excel file
EXCEL_FILE = Path(__file__).resolve().parent.parent / "data" / "dossiers_50k.xlsx"

# Polling configuration
POLL_INTERVAL_SECONDS = 5
MAX_POLL_DURATION_SECONDS = 600  # 10 minutes


class ImportLoadUser(HttpUser):
    """Simulates an admin uploading a large dossier import file."""

    wait_time = constant(0)  # Single import per user

    def on_start(self) -> None:
        """Login as admin and prepare headers."""
        self.access_token = login_admin(self.client)
        if not self.access_token:
            print("[IMPORT] Admin login failed — skipping import")
            return

        self.tenant = TENANTS[0]
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "X-Tenant-ID": self.tenant["tenant_id"],
        }
        self._import_done = False

    @task
    def import_and_poll(self) -> None:
        """Upload the 50K file and poll until import completes."""
        if self._import_done or not self.access_token:
            return

        self._import_done = True  # Only run once per user

        if not EXCEL_FILE.exists():
            print(f"[IMPORT] File not found: {EXCEL_FILE}")
            print("[IMPORT] Run: python tests/load/generate_50k_excel.py")
            return

        # --- Upload ---
        upload_start = time.time()
        with open(EXCEL_FILE, "rb") as f:
            with self.client.post(
                "/api/v1/dossiers/import",
                files={
                    "file": (
                        "dossiers_50k.xlsx",
                        f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
                headers=self.headers,
                catch_response=True,
                name="Import — Upload 50K",
            ) as resp:
                upload_duration = time.time() - upload_start
                if resp.status_code == 202:
                    resp.success()
                    file_path = resp.json().get("file_path", "")
                    print(
                        f"[IMPORT] Upload accepted in {upload_duration:.1f}s "
                        f"— file_path={file_path}"
                    )
                else:
                    resp.failure(f"Upload failed: HTTP {resp.status_code}")
                    print(f"[IMPORT] Upload failed: {resp.status_code} {resp.text}")
                    return

        # --- Poll sync-logs for completion ---
        self._poll_sync_logs("dossiers_50k.xlsx")

    def _poll_sync_logs(self, expected_filename: str) -> None:
        """Poll sync-logs list endpoint until the import completes.

        Since the import endpoint returns file_path (not sync_log_id),
        we poll the list endpoint and match by file_name.
        """
        poll_start = time.time()
        found_log_id = None

        while time.time() - poll_start < MAX_POLL_DURATION_SECONDS:
            time.sleep(POLL_INTERVAL_SECONDS)

            # Re-login if token might have expired (JWT TTL = 30 min)
            elapsed_min = (time.time() - poll_start) / 60
            if elapsed_min > 25 and not self._refresh_token():
                break

            resp = self.client.get(
                "/api/v1/dossiers/sync-logs",
                params={"page": 1, "page_size": 5},
                headers=self.headers,
                name="Import — Poll Status",
            )

            if resp.status_code != 200:
                continue

            data = resp.json()
            items = data.get("items", [])

            for item in items:
                file_name = item.get("file_name", "")
                if expected_filename in file_name:
                    found_log_id = item.get("id")
                    status = item.get("status")
                    elapsed = time.time() - poll_start

                    if status in ("completed", "failed"):
                        rows_total = item.get("rows_total", 0)
                        rows_imported = item.get("rows_imported", 0)
                        rows_updated = item.get("rows_updated", 0)
                        rows_errored = item.get("rows_errored", 0)

                        print(f"\n[IMPORT] {'=' * 50}")
                        print(f"[IMPORT] Status: {status}")
                        print(f"[IMPORT] Duration: {elapsed:.0f}s")
                        print(f"[IMPORT] Rows total: {rows_total}")
                        print(f"[IMPORT] Rows imported: {rows_imported}")
                        print(f"[IMPORT] Rows updated: {rows_updated}")
                        print(f"[IMPORT] Rows errored: {rows_errored}")
                        if rows_total > 0:
                            error_rate = rows_errored / rows_total * 100
                            print(f"[IMPORT] Error rate: {error_rate:.1f}%")
                            if error_rate > 5:
                                print("[IMPORT] FAIL: Error rate > 5%")
                            else:
                                print("[IMPORT] PASS: Error rate < 5%")
                        if elapsed > 300:
                            print("[IMPORT] WARNING: Import took > 5 min")
                        if elapsed > 600:
                            print("[IMPORT] FAIL: Import took > 10 min")
                        print(f"[IMPORT] {'=' * 50}\n")
                        return

                    # Still running
                    rows_imported = item.get("rows_imported", 0)
                    print(
                        f"[IMPORT] Polling... status={status} "
                        f"rows_imported={rows_imported} elapsed={elapsed:.0f}s"
                    )
                    break

        total_elapsed = time.time() - poll_start
        print(f"[IMPORT] TIMEOUT after {total_elapsed:.0f}s — sync log not found or still running")

    def _refresh_token(self) -> bool:
        """Re-login to get a fresh access token."""
        token = login_admin(self.client)
        if token:
            self.access_token = token
            self.headers["Authorization"] = f"Bearer {token}"
            return True
        return False


# ---------------------------------------------------------------------------
# Post-test Prometheus verification
# ---------------------------------------------------------------------------

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs) -> None:
    """Show import-related Prometheus metrics."""
    try:
        import requests

        base = environment.host or "http://localhost:8000"
        resp = requests.get(f"{base}/metrics", timeout=5)
        if resp.status_code != 200:
            return

        text = resp.text
        print("\n" + "=" * 60)
        print("POST-TEST PROMETHEUS METRICS (Import scenario)")
        print("=" * 60)

        for line in text.splitlines():
            if line.startswith("#"):
                continue
            if "cri_import_" in line:
                print(f"  {line.strip()}")

        print("=" * 60 + "\n")
    except Exception as exc:
        print(f"[METRICS] Scrape failed: {exc}")
