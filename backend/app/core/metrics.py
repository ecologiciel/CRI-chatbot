"""Centralized Prometheus metrics for security, WhatsApp, OTP, auth, and import.

Domain-specific RAG/AI metrics remain co-located in their service files.
This module centralizes cross-cutting security metrics that span multiple
services to avoid circular imports and provide a single import source.
"""

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# WhatsApp
# ---------------------------------------------------------------------------
WHATSAPP_MESSAGES = Counter(
    "cri_whatsapp_messages_total",
    "Total WhatsApp messages processed",
    ["tenant", "direction", "type"],
)

# ---------------------------------------------------------------------------
# OTP
# ---------------------------------------------------------------------------
OTP_ATTEMPTS = Counter(
    "cri_otp_attempts_total",
    "Total OTP generation and verification attempts",
    ["tenant"],
)
OTP_FAILURES = Counter(
    "cri_otp_failures_total",
    "Total OTP verification failures",
    ["tenant"],
)
OTP_SUCCESS = Counter(
    "cri_otp_success_total",
    "Total successful OTP verifications",
    ["tenant"],
)

# ---------------------------------------------------------------------------
# Security — BOLA, injection, rate limiting
# ---------------------------------------------------------------------------
BOLA_ATTEMPTS = Counter(
    "cri_bola_attempts_total",
    "Total BOLA (broken object level authorization) violation attempts",
    ["tenant"],
)
INJECTION_DETECTED = Counter(
    "cri_injection_detected_total",
    "Total prompt/SQL injection attempts detected",
    ["tenant", "type"],
)
RATE_LIMIT_TRIGGERED = Counter(
    "cri_rate_limit_triggered_total",
    "Total rate limit triggers by level",
    ["tenant", "level"],
)

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
LOGIN_ATTEMPTS = Counter(
    "cri_login_attempts_total",
    "Total back-office login attempts",
    ["tenant", "status"],
)
ACTIVE_SESSIONS = Gauge(
    "cri_active_sessions",
    "Number of active admin sessions",
    ["tenant"],
)

# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------
IMPORT_ROWS = Counter(
    "cri_import_rows_total",
    "Total rows processed during dossier imports",
    ["tenant", "status"],
)
IMPORT_DURATION = Histogram(
    "cri_import_duration_seconds",
    "Dossier import pipeline duration in seconds",
    ["tenant"],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600],
)
