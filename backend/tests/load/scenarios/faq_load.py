"""Scenario 1 — FAQ RAG Concurrent Load Test.

Simulates 100 users sending FAQ questions via WhatsApp webhook.
Each user sends a random question from the FR/AR question bank,
distributed evenly across two tenants.

Success criteria (CPS ENF-03 / ENF-04):
  - P95 response time < 2000ms
  - Error rate < 1%
  - 0 timeouts (> 10s)
  - Multi-tenant isolation maintained (verified via Prometheus)

Usage:
    locust -f scenarios/faq_load.py --users 100 --spawn-rate 10 \\
           --run-time 5m --headless --html reports/faq_load.html
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from locust import HttpUser, between, events, task

# Ensure helpers is importable when running this file directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from helpers import (
    ALL_FAQ_QUESTIONS,
    TENANTS,
    generate_phone,
    scrape_metrics,
    send_webhook_message,
)


class FAQLoadUser(HttpUser):
    """Simulates a WhatsApp user asking FAQ questions."""

    wait_time = between(1, 3)

    def on_start(self) -> None:
        """Assign a unique phone and tenant to this user."""
        self.phone = generate_phone()
        # Distribute users across tenants
        tenant = random.choice(TENANTS[:2])  # Use tenants A and B
        self.tenant_phone_id: str = tenant["phone_id"]
        self.tenant_slug: str = tenant["slug"]

    @task
    def send_faq_question(self) -> None:
        """Send a random FAQ question via webhook."""
        question = random.choice(ALL_FAQ_QUESTIONS)
        send_webhook_message(
            self.client,
            phone_number_id=self.tenant_phone_id,
            from_phone=self.phone,
            message_text=question,
            name=f"FAQ [{self.tenant_slug}]",
        )


# ---------------------------------------------------------------------------
# Post-test Prometheus verification
# ---------------------------------------------------------------------------

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs) -> None:
    """Scrape Prometheus metrics after the test to verify isolation."""
    if environment.runner is None:
        return

    try:
        import requests

        base = environment.host or "http://localhost:8000"
        resp = requests.get(f"{base}/metrics", timeout=5)
        if resp.status_code != 200:
            print("[METRICS] Could not scrape /metrics endpoint")
            return

        text = resp.text
        print("\n" + "=" * 60)
        print("POST-TEST PROMETHEUS METRICS (FAQ scenario)")
        print("=" * 60)

        for tenant in TENANTS[:2]:
            slug = tenant["slug"]
            for line in text.splitlines():
                if "cri_whatsapp_messages_total" in line and slug in line:
                    print(f"  {line.strip()}")

        # Rate limit triggers
        for line in text.splitlines():
            if "cri_rate_limit_triggered_total" in line and "webhook" in line:
                print(f"  {line.strip()}")

        print("=" * 60 + "\n")
    except Exception as exc:
        print(f"[METRICS] Scrape failed: {exc}")
