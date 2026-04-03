"""Locust entry point — Mixed workload (default scenario).

Locust automatically discovers HttpUser subclasses in this file.
The MixedWorkloadUser runs the full realistic traffic profile:
  60% FAQ, 20% Incitations, 10% Suivi Dossier, 10% Agent Interne
  across 3 tenants with multi-tenant isolation verification.

Usage:
    # Default mixed workload (CPS deliverable L4)
    locust -f locustfile.py --users 150 --spawn-rate 15 \\
           --run-time 10m --headless --html reports/load_test.html

    # Or run individual scenarios directly:
    locust -f scenarios/faq_load.py --users 100 --spawn-rate 10 --run-time 5m
    locust -f scenarios/otp_load.py --users 50 --spawn-rate 10 --run-time 3m
    locust -f scenarios/import_load.py --users 1 --spawn-rate 1 --run-time 15m
"""

from scenarios.mixed_load import MixedWorkloadUser  # noqa: F401
