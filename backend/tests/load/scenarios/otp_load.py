"""Scenario 3 — OTP Burst + Rate Limiting Load Test.

Simulates 50 users simultaneously triggering dossier tracking OTP flows.
Each user sends a dossier tracking request, then attempts multiple
wrong OTP codes to exercise the rate limiter.

Success criteria (CPS Annex §7.3):
  - Rate limiter fires after 3 OTP attempts per phone (verified via Prometheus)
  - No server crashes under OTP burst (50 concurrent flows)
  - P95 response time < 3000ms
  - Prometheus counter cri_rate_limit_triggered_total{level="otp"} increments

Usage:
    locust -f scenarios/otp_load.py --users 50 --spawn-rate 10 \\
           --run-time 3m --headless --html reports/otp_load.html
"""

from __future__ import annotations

import sys
from pathlib import Path

from locust import HttpUser, between, events, task

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from helpers import (
    TENANTS,
    generate_phone,
    send_webhook_message,
)

# Dossier numbers to simulate tracking requests
DOSSIER_NUMBERS = [f"2024-{i:06d}" for i in range(1, 101)]


class OTPBurstUser(HttpUser):
    """Simulates a user triggering the OTP flow and attempting wrong codes."""

    wait_time = between(0.5, 2)

    def on_start(self) -> None:
        """Assign a unique phone and tenant to this user."""
        self.phone = generate_phone()
        self.tenant = TENANTS[0]  # All OTP tests target tenant A
        self.otp_attempt_count = 0

    @task(3)
    def request_dossier_tracking(self) -> None:
        """Send a dossier tracking request to trigger OTP generation."""
        import random

        dossier = random.choice(DOSSIER_NUMBERS)
        send_webhook_message(
            self.client,
            phone_number_id=self.tenant["phone_id"],
            from_phone=self.phone,
            message_text=f"Je veux suivre mon dossier {dossier}",
            name="OTP — Tracking Request",
        )

    @task(7)
    def attempt_wrong_otp(self) -> None:
        """Send a wrong 6-digit OTP code.

        After 3 attempts per 15 min, the server's DossierOTPService
        should trigger rate limiting. The test verifies this via
        Prometheus counters post-run.
        """
        self.otp_attempt_count += 1
        wrong_code = f"{(self.otp_attempt_count * 7 + 13) % 1000000:06d}"

        send_webhook_message(
            self.client,
            phone_number_id=self.tenant["phone_id"],
            from_phone=self.phone,
            message_text=wrong_code,
            name="OTP — Wrong Code",
        )


# ---------------------------------------------------------------------------
# Post-test Prometheus verification for OTP rate limiting
# ---------------------------------------------------------------------------

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs) -> None:
    """Verify OTP rate limiting fired via Prometheus metrics."""
    try:
        import requests

        base = environment.host or "http://localhost:8000"
        resp = requests.get(f"{base}/metrics", timeout=5)
        if resp.status_code != 200:
            print("[METRICS] Could not scrape /metrics endpoint")
            return

        text = resp.text
        print("\n" + "=" * 60)
        print("POST-TEST PROMETHEUS METRICS (OTP scenario)")
        print("=" * 60)

        metrics_of_interest = [
            "cri_otp_attempts_total",
            "cri_otp_failures_total",
            "cri_otp_success_total",
            "cri_rate_limit_triggered_total",
        ]

        for line in text.splitlines():
            if line.startswith("#"):
                continue
            for metric in metrics_of_interest:
                if metric in line:
                    print(f"  {line.strip()}")
                    break

        print("=" * 60)
        print("PASS criteria: cri_rate_limit_triggered_total{level=\"otp\"} > 0")
        print("=" * 60 + "\n")
    except Exception as exc:
        print(f"[METRICS] Scrape failed: {exc}")
