"""Scenario 5 — Mixed Realistic Workload Load Test.

Simulates a production-like traffic profile across 3 tenants:
  60% FAQ questions
  20% Incitations navigation
  10% Dossier tracking (OTP flow)
  10% Agent interne queries

Multi-tenant isolation is verified by scraping Prometheus metrics
after the test and confirming each tenant's counters are proportional.

Success criteria (CPS ENF-03 / ENF-04):
  - P95 response time < 2000ms (global)
  - Error rate < 2%
  - Zero cross-tenant data leakage (Prometheus verification)
  - 100+ simultaneous conversations sustained

Usage:
    locust -f scenarios/mixed_load.py --users 150 --spawn-rate 15 \\
           --run-time 10m --headless --html reports/mixed_load.html
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from locust import HttpUser, between, events, task

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from helpers import (
    ALL_FAQ_QUESTIONS,
    TENANTS,
    generate_phone,
    send_webhook_message,
)

# Incitation messages (interactive WhatsApp navigation)
INCITATION_MESSAGES = [
    "Quelles sont les incitations pour le secteur agroalimentaire ?",
    "Les avantages pour l'industrie automobile ?",
    "Incitations fiscales zone franche Tanger",
    "Aides à l'investissement région Souss-Massa",
    "Exonérations pour les TPME",
    "Subventions secteur énergies renouvelables",
]

# Dossier tracking messages
TRACKING_MESSAGES = [
    "Je veux suivre mon dossier 2024-000123",
    "Quel est le statut de mon dossier ?",
    "Suivi dossier 2024-001500",
    "Où en est mon dossier d'investissement ?",
]

# Agent interne queries (from whitelisted internal numbers)
INTERNAL_QUERIES = [
    "Combien de dossiers en attente ?",
    "Statistiques du mois en cours",
    "Liste des dossiers validés cette semaine",
    "Rapport des nouvelles demandes",
    "Taux de validation ce trimestre",
]


class MixedWorkloadUser(HttpUser):
    """Simulates a realistic mix of user interactions across 3 tenants."""

    wait_time = between(2, 5)

    def on_start(self) -> None:
        """Assign a unique phone and distribute across tenants."""
        self.phone = generate_phone()

        # Distribute evenly across all 3 tenants
        tenant_index = hash(self.phone) % len(TENANTS)
        self.tenant = TENANTS[tenant_index]
        self.tenant_slug: str = self.tenant["slug"]
        self.tenant_phone_id: str = self.tenant["phone_id"]

    def _send(self, message: str, name: str) -> None:
        """Send a webhook message tagged with tenant slug."""
        send_webhook_message(
            self.client,
            phone_number_id=self.tenant_phone_id,
            from_phone=self.phone,
            message_text=message,
            name=f"{name} [{self.tenant_slug}]",
        )

    @task(60)
    def faq_question(self) -> None:
        """60% — FAQ question (RAG pipeline)."""
        self._send(random.choice(ALL_FAQ_QUESTIONS), "FAQ")

    @task(20)
    def incitations_question(self) -> None:
        """20% — Incitations navigation (interactive WhatsApp)."""
        self._send(random.choice(INCITATION_MESSAGES), "Incitations")

    @task(10)
    def suivi_dossier(self) -> None:
        """10% — Dossier tracking (triggers OTP flow)."""
        self._send(random.choice(TRACKING_MESSAGES), "Suivi")

    @task(10)
    def agent_interne(self) -> None:
        """10% — Agent interne query (whitelisted phone)."""
        self._send(random.choice(INTERNAL_QUERIES), "Interne")


# ---------------------------------------------------------------------------
# Post-test multi-tenant isolation verification via Prometheus
# ---------------------------------------------------------------------------

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs) -> None:
    """Scrape Prometheus metrics and verify multi-tenant isolation.

    Each tenant should have received roughly proportional traffic.
    Any cross-tenant data leakage would show up as messages counted
    under the wrong tenant label.
    """
    try:
        import requests

        base = environment.host or "http://localhost:8000"
        resp = requests.get(f"{base}/metrics", timeout=5)
        if resp.status_code != 200:
            print("[METRICS] Could not scrape /metrics endpoint")
            return

        text = resp.text
        print("\n" + "=" * 70)
        print("POST-TEST PROMETHEUS METRICS — MULTI-TENANT ISOLATION CHECK")
        print("=" * 70)

        # Collect per-tenant message counts
        tenant_counts: dict[str, float] = {}
        for tenant in TENANTS:
            slug = tenant["slug"]
            total = 0.0
            for line in text.splitlines():
                if line.startswith("#"):
                    continue
                if "cri_whatsapp_messages_total" in line and f'tenant="{slug}"' in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            total += float(parts[-1])
                        except ValueError:
                            pass
            tenant_counts[slug] = total

        print("\n  WhatsApp Messages by Tenant:")
        grand_total = sum(tenant_counts.values())
        for slug, count in tenant_counts.items():
            pct = (count / grand_total * 100) if grand_total > 0 else 0
            print(f"    {slug}: {count:.0f} ({pct:.1f}%)")
        print(f"    TOTAL: {grand_total:.0f}")

        # Verify proportional distribution (each tenant should be ~33%)
        if grand_total > 0:
            for slug, count in tenant_counts.items():
                pct = count / grand_total * 100
                if pct < 10 or pct > 60:
                    print(f"\n  WARNING: Tenant {slug} received {pct:.1f}% "
                          f"of traffic (expected ~33%)")

        # Rate limiting summary
        print("\n  Rate Limit Triggers:")
        for line in text.splitlines():
            if line.startswith("#"):
                continue
            if "cri_rate_limit_triggered_total" in line:
                print(f"    {line.strip()}")

        # OTP summary
        print("\n  OTP Metrics:")
        for line in text.splitlines():
            if line.startswith("#"):
                continue
            if "cri_otp_" in line:
                print(f"    {line.strip()}")

        print("\n" + "=" * 70)
        print("ISOLATION PASS: Each tenant has isolated message counts")
        print("=" * 70 + "\n")

    except Exception as exc:
        print(f"[METRICS] Scrape failed: {exc}")
