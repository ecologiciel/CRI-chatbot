# Tests de Charge — CRI Chatbot Platform

> **Livrable CPS L4** — Rapport de tests de charge (HTML Locust)

Tests de charge Locust validant les exigences non-fonctionnelles ENF-03 (temps de réponse < 2s, 95e percentile) et ENF-04 (100+ conversations simultanées).

## Prérequis

1. **Infrastructure Docker** en cours d'exécution :
   ```bash
   docker compose up -d
   ```

2. **Tenants de test** provisionnés avec :
   - 3 tenants (`load-tenant-a`, `load-tenant-b`, `load-tenant-c`)
   - Chaque tenant avec un `phone_number_id` configuré dans `whatsapp_config`
   - Un admin avec rôle `admin_tenant` ou `super_admin`
   - Base de connaissances peuplée (pour les réponses FAQ)

3. **Dépendances Locust** :
   ```bash
   pip install -r tests/load/requirements.txt
   ```

## Variables d'environnement

| Variable | Défaut | Description |
|----------|--------|-------------|
| `LOAD_TEST_BASE_URL` | `http://localhost:8000` | URL de l'API |
| `LOAD_TEST_APP_SECRET` | `test_app_secret` | Secret HMAC WhatsApp |
| `LOAD_TEST_TENANT_SLUG_A` | `load-tenant-a` | Slug du tenant A |
| `LOAD_TEST_PHONE_ID_A` | `load_phone_a` | Phone number ID tenant A |
| `LOAD_TEST_TENANT_ID_A` | `00000000-...000a` | UUID du tenant A |
| `LOAD_TEST_TENANT_SLUG_B` | `load-tenant-b` | Slug du tenant B |
| `LOAD_TEST_PHONE_ID_B` | `load_phone_b` | Phone number ID tenant B |
| `LOAD_TEST_TENANT_ID_B` | `00000000-...000b` | UUID du tenant B |
| `LOAD_TEST_TENANT_SLUG_C` | `load-tenant-c` | Slug du tenant C |
| `LOAD_TEST_PHONE_ID_C` | `load_phone_c` | Phone number ID tenant C |
| `LOAD_TEST_TENANT_ID_C` | `00000000-...000c` | UUID du tenant C |
| `LOAD_TEST_ADMIN_EMAIL` | `admin-load@test.cri.ma` | Email admin pour import |
| `LOAD_TEST_ADMIN_PASSWORD` | `TestAdmin123!` | Mot de passe admin |

## Générer les données de test

```bash
cd backend
python tests/load/generate_50k_excel.py
# Génère : tests/load/data/dossiers_50k.xlsx (50 000 lignes)
```

## Exécution des scénarios

### Scénario 1 — FAQ RAG (100 users, 5 min)

```bash
cd backend/tests/load
locust -f scenarios/faq_load.py \
    --host http://localhost:8000 \
    --users 100 --spawn-rate 10 \
    --run-time 5m --headless \
    --html reports/faq_load.html
```

### Scénario 3 — OTP Burst (50 users, 3 min)

```bash
locust -f scenarios/otp_load.py \
    --host http://localhost:8000 \
    --users 50 --spawn-rate 10 \
    --run-time 3m --headless \
    --html reports/otp_load.html
```

### Scénario 4 — Import 50K lignes (1 user, 15 min max)

```bash
locust -f scenarios/import_load.py \
    --host http://localhost:8000 \
    --users 1 --spawn-rate 1 \
    --run-time 15m --headless \
    --html reports/import_load.html
```

### Scénario 5 — Mixed Workload (150 users, 10 min) — **Livrable CPS L4**

```bash
locust -f locustfile.py \
    --host http://localhost:8000 \
    --users 150 --spawn-rate 15 \
    --run-time 10m --headless \
    --html reports/mixed_load.html
```

### Mode Web UI (interactif)

```bash
locust -f locustfile.py --host http://localhost:8000
# Ouvrir http://localhost:8089 dans le navigateur
```

## Critères de succès

| Scénario | P95 Latence | Taux d'erreur | Critère spécifique |
|----------|-------------|---------------|---------------------|
| FAQ RAG | < 2000ms | < 1% | 0 timeout (> 10s) |
| OTP Burst | < 3000ms | N/A | Rate limiter actif (Prometheus) |
| Import 50K | < 5s upload | < 5% erreurs lignes | Complété en < 10 min |
| Mixed | < 2000ms | < 2% | Isolation multi-tenant (Prometheus) |

## Vérification Prometheus

Après chaque test, les métriques sont automatiquement scrapées et affichées.
Vérification manuelle :

```bash
# Messages WhatsApp par tenant
curl -s http://localhost:8000/metrics | grep cri_whatsapp_messages_total

# Rate limiting
curl -s http://localhost:8000/metrics | grep cri_rate_limit_triggered_total

# OTP
curl -s http://localhost:8000/metrics | grep cri_otp_

# Import
curl -s http://localhost:8000/metrics | grep cri_import_
```

## Dépannage

### Erreur HMAC 403

Les payloads webhook sont signés avec HMAC-SHA256. Vérifier que `LOAD_TEST_APP_SECRET` correspond à la valeur de `WHATSAPP_APP_SECRET` dans le `.env` du backend.

### Rate limiting entre les runs

Les clés Redis de rate limiting persistent entre les exécutions :
- Webhook : 60s TTL (`whatsapp:webhook_rate_limit:{slug}`)
- OTP : 900s TTL (`{slug}:dossier_otp_attempts:{phone}`)

Si les tests échouent immédiatement avec du rate limiting, attendre l'expiration des TTL ou flusher Redis.

### Import file not found

```bash
python tests/load/generate_50k_excel.py
```

### Token expiré pendant l'import

Le scénario import re-login automatiquement si le token JWT approche de son expiration (TTL 30 min).
