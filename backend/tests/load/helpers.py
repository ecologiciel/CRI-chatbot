"""Shared helpers for CRI load tests.

Provides HMAC signing, webhook payload builders, FAQ question banks,
and utility functions used across all Locust scenarios.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import os
import random
import time
from uuid import uuid4

# ---------------------------------------------------------------------------
# Configuration (environment variables with sensible defaults)
# ---------------------------------------------------------------------------

API_BASE_URL = os.getenv("LOAD_TEST_BASE_URL", "http://localhost:8000")
WHATSAPP_APP_SECRET = os.getenv("LOAD_TEST_APP_SECRET", "test_app_secret")

# Tenant A
TENANT_SLUG_A = os.getenv("LOAD_TEST_TENANT_SLUG_A", "load-tenant-a")
TENANT_PHONE_ID_A = os.getenv("LOAD_TEST_PHONE_ID_A", "load_phone_a")
TENANT_ID_A = os.getenv("LOAD_TEST_TENANT_ID_A", "00000000-0000-0000-0000-00000000000a")

# Tenant B
TENANT_SLUG_B = os.getenv("LOAD_TEST_TENANT_SLUG_B", "load-tenant-b")
TENANT_PHONE_ID_B = os.getenv("LOAD_TEST_PHONE_ID_B", "load_phone_b")
TENANT_ID_B = os.getenv("LOAD_TEST_TENANT_ID_B", "00000000-0000-0000-0000-00000000000b")

# Tenant C
TENANT_SLUG_C = os.getenv("LOAD_TEST_TENANT_SLUG_C", "load-tenant-c")
TENANT_PHONE_ID_C = os.getenv("LOAD_TEST_PHONE_ID_C", "load_phone_c")
TENANT_ID_C = os.getenv("LOAD_TEST_TENANT_ID_C", "00000000-0000-0000-0000-00000000000c")

# Admin credentials for import tests
ADMIN_EMAIL = os.getenv("LOAD_TEST_ADMIN_EMAIL", "admin-load@test.cri.ma")
ADMIN_PASSWORD = os.getenv("LOAD_TEST_ADMIN_PASSWORD", "TestAdmin123!")

# All tenants for distribution
TENANTS = [
    {"slug": TENANT_SLUG_A, "phone_id": TENANT_PHONE_ID_A, "tenant_id": TENANT_ID_A},
    {"slug": TENANT_SLUG_B, "phone_id": TENANT_PHONE_ID_B, "tenant_id": TENANT_ID_B},
    {"slug": TENANT_SLUG_C, "phone_id": TENANT_PHONE_ID_C, "tenant_id": TENANT_ID_C},
]

# ---------------------------------------------------------------------------
# FAQ question banks (FR + AR)
# ---------------------------------------------------------------------------

FAQ_QUESTIONS_FR = [
    "Quels sont les documents nécessaires pour créer une entreprise ?",
    "Combien de temps prend la validation d'un dossier ?",
    "Quelles sont les incitations pour le secteur agroalimentaire ?",
    "Comment obtenir un certificat négatif ?",
    "Quels sont les frais d'enregistrement ?",
    "Comment contacter le CRI de Rabat ?",
    "Quelles sont les étapes de création d'une SARL ?",
    "Y a-t-il des aides pour les jeunes entrepreneurs ?",
    "Comment faire une demande de subvention ?",
    "Quels sont les délais de traitement d'un dossier d'investissement ?",
    "Quels sont les avantages fiscaux pour les zones franches ?",
    "Comment immatriculer une entreprise au registre du commerce ?",
    "Quel est le capital minimum pour créer une SA ?",
    "Quelles sont les pièces justificatives pour un investissement étranger ?",
    "Comment bénéficier de la prime à l'investissement ?",
]

FAQ_QUESTIONS_AR = [
    "ما هي الوثائق المطلوبة لإنشاء شركة؟",
    "كم يستغرق التحقق من الملف؟",
    "ما هي الحوافز لقطاع الصناعة الغذائية؟",
    "كيف أحصل على الشهادة السلبية؟",
    "ما هي رسوم التسجيل؟",
    "ما هي خطوات إنشاء شركة ذات مسؤولية محدودة؟",
]

ALL_FAQ_QUESTIONS = FAQ_QUESTIONS_FR + FAQ_QUESTIONS_AR

# ---------------------------------------------------------------------------
# HMAC signing (matches webhook.py:150-156 exactly)
# ---------------------------------------------------------------------------


def sign_payload(body: bytes, secret: str = WHATSAPP_APP_SECRET) -> str:
    """Compute HMAC-SHA256 signature matching the server's validation.

    The server at webhook.py:150-156 does:
        expected = hmac.new(secret.encode("utf-8"), raw_body, sha256).hexdigest()
        compare_digest(f"sha256={expected}", signature)

    Args:
        body: Raw JSON bytes (must be identical to what the server receives).
        secret: WhatsApp app secret.

    Returns:
        Signature string in format ``sha256={hex}``.
    """
    digest = hmac_mod.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# Phone number generation
# ---------------------------------------------------------------------------


def generate_phone() -> str:
    """Generate a random Moroccan E.164 phone number."""
    prefix = random.choice(["6", "7"])
    number = random.randint(10000000, 99999999)
    return f"+212{prefix}{number}"


# ---------------------------------------------------------------------------
# Webhook payload builder
# ---------------------------------------------------------------------------


def build_webhook_payload(
    phone_number_id: str,
    from_phone: str,
    message_text: str,
    wamid: str | None = None,
) -> dict:
    """Build a valid Meta WhatsApp webhook payload.

    Matches the WhatsAppWebhookPayload Pydantic model expected by the server.

    Args:
        phone_number_id: The tenant's phone number ID for resolution.
        from_phone: Sender phone number (without + prefix).
        message_text: Text message body.
        wamid: Unique message ID. Auto-generated if None.

    Returns:
        Webhook payload dict.
    """
    if wamid is None:
        wamid = f"wamid.load_{uuid4().hex[:16]}"

    # Strip + prefix if present (Meta sends without it)
    from_number = from_phone.lstrip("+")

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456789",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550001234",
                                "phone_number_id": phone_number_id,
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Load Test User"},
                                    "wa_id": from_number,
                                }
                            ],
                            "messages": [
                                {
                                    "from": from_number,
                                    "id": wamid,
                                    "timestamp": str(int(time.time())),
                                    "text": {"body": message_text},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Webhook sender (serialize-once pattern to guarantee HMAC match)
# ---------------------------------------------------------------------------


def send_webhook_message(
    client,
    phone_number_id: str,
    from_phone: str,
    message_text: str,
    name: str = "Webhook",
    secret: str = WHATSAPP_APP_SECRET,
):
    """Build, sign, and POST a webhook message.

    Uses the serialize-once pattern: the payload is serialized to bytes
    ONCE, signed, then sent as raw bytes with explicit Content-Type.
    This guarantees the HMAC matches what the server computes.

    Args:
        client: Locust HttpUser.client instance.
        phone_number_id: Tenant phone number ID.
        from_phone: Sender phone (E.164 with or without +).
        message_text: Message text body.
        name: Locust request name for reporting.
        secret: HMAC secret.

    Returns:
        Locust response object.
    """
    payload = build_webhook_payload(phone_number_id, from_phone, message_text)
    body_bytes = json.dumps(payload).encode("utf-8")
    signature = sign_payload(body_bytes, secret)

    with client.post(
        "/api/v1/webhook/whatsapp",
        data=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
        catch_response=True,
        name=name,
    ) as response:
        if response.status_code == 200:
            response.success()
        elif response.status_code == 403:
            response.failure("HMAC signature rejected")
        elif response.status_code == 429:
            response.failure("Rate limited (HTTP 429)")
        else:
            response.failure(f"HTTP {response.status_code}")
        return response


# ---------------------------------------------------------------------------
# Admin login helper
# ---------------------------------------------------------------------------


def login_admin(
    client,
    email: str = ADMIN_EMAIL,
    password: str = ADMIN_PASSWORD,
) -> str | None:
    """Login as admin and return access token.

    Args:
        client: Locust HttpUser.client instance.
        email: Admin email.
        password: Admin password.

    Returns:
        Access token string, or None on failure.
    """
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        name="Admin Login",
    )
    if resp.status_code == 200:
        return resp.json().get("access_token")
    return None


# ---------------------------------------------------------------------------
# Prometheus metrics scraper
# ---------------------------------------------------------------------------


def scrape_metrics(client) -> str:
    """Fetch raw Prometheus metrics from /metrics endpoint.

    Args:
        client: Locust HttpUser.client or requests session.

    Returns:
        Raw metrics text.
    """
    resp = client.get("/metrics", name="[internal] Metrics Scrape")
    if resp.status_code == 200:
        return resp.text
    return ""


def parse_metric_value(metrics_text: str, metric_name: str, labels: dict | None = None) -> float:
    """Extract a single metric value from Prometheus text format.

    Args:
        metrics_text: Raw /metrics output.
        metric_name: Metric name (e.g., "cri_whatsapp_messages_total").
        labels: Optional label filters (e.g., {"tenant": "load-tenant-a"}).

    Returns:
        Metric value as float, or 0.0 if not found.
    """
    for line in metrics_text.splitlines():
        if line.startswith("#"):
            continue
        if metric_name not in line:
            continue

        # Check label filters
        if labels:
            match = True
            for key, value in labels.items():
                if f'{key}="{value}"' not in line:
                    match = False
                    break
            if not match:
                continue

        # Extract value (last token on the line)
        parts = line.split()
        if len(parts) >= 2:
            try:
                return float(parts[-1])
            except ValueError:
                continue

    return 0.0
