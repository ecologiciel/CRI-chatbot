# PHASE 1 — Prompts Atomiques pour Claude Code
# Plateforme Multi-Tenant RAG Chatbot CRI

**AO N° 02/2026/CRI RSK | Durée Phase 1 : 8 semaines**
**Objectif :** Socle multi-tenant + Agent Public (FAQ RAG + Incitations) + Back-office v1 + Sécurité P1

---

## 📊 TABLEAU DE BORD PHASE 1

| Module | Nb Prompts | Effort estimé |
|--------|-----------|---------------|
| INFRA | 3 | 2-3 jours |
| TENANT | 5 | 4-5 jours |
| AUTH | 4 | 3-4 jours |
| WHATSAPP | 5 | 5-6 jours |
| RAG | 6 | 7-8 jours |
| ORCHESTRATOR | 3 | 3-4 jours |
| INCITATIONS | 3 | 3-4 jours |
| LANG | 2 | 1-2 jours |
| FEEDBACK | 2 | 2 jours |
| CONTACTS | 2 | 2 jours |
| BACKOFFICE | 7 | 8-10 jours |
| **TOTAL** | **42 prompts** | **~40-52 jours-homme** |

**Avec parallélisation (2-3 agents Claude Code) : ~18-22 jours calendaires**

---

## 🔀 GRAPHE DE PARALLÉLISATION — WAVES D'EXÉCUTION

Le principe : chaque Wave contient des prompts qui peuvent être lancés **simultanément** sur des agents Claude Code distincts. On ne passe à la Wave suivante que quand TOUS les prompts de la Wave courante sont terminés.

```
╔══════════════════════════════════════════════════════════════════════╗
║  WAVE 0 — FONDATION (séquentiel, 1 seul agent)                     ║
║  INFRA.1 → INFRA.2 → INFRA.3                                       ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
╔══════════════════════════════════════════════════════════════════════╗
║  WAVE 1 — MODÈLES DE BASE (1 seul agent)                           ║
║  TENANT.1                                                           ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
╔══════════════════════════════════════════════════════════════════════╗
║  WAVE 2 — CORE MIDDLEWARE (2 agents en parallèle)                   ║
║  🅰 TENANT.2 (middleware multi-tenant)                              ║
║  🅱 AUTH.1 (modèle Admin + JWT)                                     ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
╔══════════════════════════════════════════════════════════════════════╗
║  WAVE 3 — SERVICES CORE (3 agents en parallèle)                    ║
║  🅰 TENANT.3 (provisioning) ← TENANT.2                             ║
║  🅱 AUTH.2 (RBAC middleware) ← AUTH.1                               ║
║  🅲 AUTH.3 (rate limiting Redis) ← AUTH.1                           ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
╔══════════════════════════════════════════════════════════════════════╗
║  WAVE 4 — API + INTÉGRATIONS (4 agents en parallèle)               ║
║  🅰 TENANT.4 (API CRUD tenant) ← TENANT.3, AUTH.2                  ║
║  🅱 WHATSAPP.1 (client Meta Cloud API) ← TENANT.2                  ║
║  🅲 RAG.1 (ingestion: chunking + embeddings) ← TENANT.2            ║
║  🅳 CONTACTS.1 (modèle + service contact) ← TENANT.2               ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
╔══════════════════════════════════════════════════════════════════════╗
║  WAVE 5 — PIPELINE CORE (4 agents en parallèle)                    ║
║  🅰 WHATSAPP.2 (webhook + HMAC) ← WHATSAPP.1                      ║
║  🅱 RAG.2 (retrieval Qdrant) ← RAG.1                               ║
║  🅲 FEEDBACK.1 (modèle + service) ← TENANT.1                       ║
║  🅳 INCITATIONS.1 (modèle données) ← TENANT.1                      ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
╔══════════════════════════════════════════════════════════════════════╗
║  WAVE 6 — GÉNÉRATION + LANGUE (3 agents en parallèle)              ║
║  🅰 RAG.3 (génération Gemini + guardrails) ← RAG.2                 ║
║  🅱 WHATSAPP.3 (router conversationnel) ← WHATSAPP.2               ║
║  🅲 LANG.1 (détection langue + prompts multilingues) ← TENANT.2    ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
╔══════════════════════════════════════════════════════════════════════╗
║  WAVE 7 — ORCHESTRATION (3 agents en parallèle)                    ║
║  🅰 RAG.4 (pipeline RAG orchestré LangGraph) ← RAG.3, LANG.1      ║
║  🅱 WHATSAPP.4 (sessions Redis) ← WHATSAPP.3                       ║
║  🅲 INCITATIONS.2 (IncentivesAgent LangGraph) ← INCITATIONS.1,     ║
║                                                   WHATSAPP.1        ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
╔══════════════════════════════════════════════════════════════════════╗
║  WAVE 8 — ORCHESTRATEUR GLOBAL (2 agents en parallèle)             ║
║  🅰 ORCHESTRATOR.1 (graphe LangGraph complet) ← RAG.4, WHATSAPP.3, ║
║                                     INCITATIONS.2, FEEDBACK.1       ║
║  🅱 RAG.5 (API endpoints KB) ← RAG.4, AUTH.2                       ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
╔══════════════════════════════════════════════════════════════════════╗
║  WAVE 9 — INTÉGRATION E2E (3 agents en parallèle)                  ║
║  🅰 ORCHESTRATOR.2 (intégration WhatsApp ↔ LangGraph) ←            ║
║                                ORCHESTRATOR.1, WHATSAPP.4           ║
║  🅱 CONTACTS.2 (API contacts) ← CONTACTS.1, AUTH.2                 ║
║  🅲 FEEDBACK.2 (API feedback) ← FEEDBACK.1, AUTH.2                 ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
╔══════════════════════════════════════════════════════════════════════╗
║  WAVE 10 — TESTS BACKEND (3 agents en parallèle)                   ║
║  🅰 TENANT.5 (tests multi-tenant isolation) ← TENANT.4             ║
║  🅱 AUTH.4 (tests auth + sécurité) ← AUTH.3                        ║
║  🅲 ORCHESTRATOR.3 (tests E2E pipeline) ← ORCHESTRATOR.2           ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
╔══════════════════════════════════════════════════════════════════════╗
║  WAVE 11 — TESTS SPÉCIALISÉS (3 agents en parallèle)               ║
║  🅰 WHATSAPP.5 (tests webhook) ← WHATSAPP.4                       ║
║  🅱 RAG.6 (tests RAG E2E) ← RAG.5                                  ║
║  🅲 INCITATIONS.3 (tests parcours) ← INCITATIONS.2                 ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
╔══════════════════════════════════════════════════════════════════════╗
║  WAVE 12 — BACK-OFFICE SETUP (1 agent, peut commencer dès Wave 4)  ║
║  🅰 BACKOFFICE.1 (Next.js + design system) ← aucune dép backend    ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
╔══════════════════════════════════════════════════════════════════════╗
║  WAVE 13 — BACK-OFFICE PAGES (3 agents en parallèle)               ║
║  🅰 BACKOFFICE.2 (auth + layout + RTL) ← BACKOFFICE.1, AUTH.2      ║
║  🅱 BACKOFFICE.3 (dashboard) ← BACKOFFICE.1                        ║
║  🅲 BACKOFFICE.4 (supervision conversations) ← BACKOFFICE.1        ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
╔══════════════════════════════════════════════════════════════════════╗
║  WAVE 14 — BACK-OFFICE MODULES (3 agents en parallèle)             ║
║  🅰 BACKOFFICE.5 (gestion KB) ← BACKOFFICE.2, RAG.5                ║
║  🅱 BACKOFFICE.6 (gestion contacts) ← BACKOFFICE.2, CONTACTS.2     ║
║  🅲 BACKOFFICE.7 (gestion tenants super-admin) ← BACKOFFICE.2,     ║
║                                                    TENANT.4         ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
╔══════════════════════════════════════════════════════════════════════╗
║  WAVE 15 — LANG TESTS + FINALISATION (2 agents en parallèle)       ║
║  🅰 LANG.2 (tests trilinguisme) ← LANG.1, ORCHESTRATOR.2          ║
║  🅱 Intégration finale + smoke tests globaux                        ║
╚══════════════════════════════════════════════════════════════════════╝
```

### ⚡ OPTIMISATION : PISTE PARALLÈLE FRONT-END

Le back-office (BACKOFFICE.1) n'a **aucune dépendance backend** pour le setup initial. Un agent dédié au front-end peut démarrer **dès la Wave 4** en parallèle du backend :

```
PISTE BACKEND :  Wave 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11
PISTE FRONTEND : ─────────────────── Wave 12 → 13 → 14 (dès que les API existent)
```

Cela réduit le chemin critique de ~3-4 jours.

---

## 📋 DÉTAIL DE CHAQUE PROMPT

---

### INFRA.1 — Docker Compose + Traefik + Réseau sécurisé

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 0 (séquentiel) |
| **Parallélisable avec** | Rien (premier prompt) |
| **Dépendances** | 🟢 Aucune |
| **Effort** | 0.5-1 jour |
| **Sécurité intégrée** | [SÉCU] TLS 1.3 Let's Encrypt, headers sécurité, Docker network isolation |
| **Fichiers créés** | `docker-compose.yml`, `docker-compose.prod.yml`, `docker/traefik/traefik.yml`, `docker/traefik/dynamic.yml`, `.env.example` |

**Résumé :** Créer le Docker Compose de développement local avec PostgreSQL 16, Qdrant, Redis 7, MinIO, Traefik v3. Configurer deux réseaux Docker isolés (`frontend` : Traefik + FastAPI ; `backend` : FastAPI + PG + Qdrant + Redis + MinIO). Traefik gère TLS auto (Let's Encrypt) et injecte les headers de sécurité (HSTS, X-Content-Type-Options, X-Frame-Options, CSP, Referrer-Policy, CORS). Le `.env.example` documente toutes les variables attendues.

**Smoke test :** `docker compose up -d && docker compose ps` — tous les services healthy.

---

### INFRA.2 — Configuration FastAPI + pydantic-settings + structlog

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 0 (séquentiel, après INFRA.1) |
| **Parallélisable avec** | Rien |
| **Dépendances** | 🔵 INFRA.1 |
| **Effort** | 0.5-1 jour |
| **Sécurité intégrée** | [SÉCU] Logging structuré structlog, secret management .env |
| **Fichiers créés** | `backend/app/__init__.py`, `backend/app/main.py`, `backend/app/core/__init__.py`, `backend/app/core/config.py`, `backend/app/core/logging.py`, `backend/app/core/exceptions.py`, `backend/requirements.txt`, `docker/backend.Dockerfile` |

**Résumé :** Initialiser l'application FastAPI avec pydantic-settings (classe `Settings` chargeant le `.env`), structlog configuré en JSON, exception handler global avec classes custom (`CRIBaseException`, `TenantNotFoundError`, `AuthenticationError`, etc.), et le Dockerfile backend multi-stage (builder + runner, non-root user). Inclure les dépendances de base : fastapi, uvicorn, pydantic-settings, structlog, sqlalchemy[asyncio], asyncpg, redis, httpx.

**Smoke test :** `docker compose up backend` → `curl http://localhost:8000/docs` retourne le Swagger UI.

---

### INFRA.3 — Health checks + startup/shutdown events

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 0 (séquentiel, après INFRA.2) |
| **Parallélisable avec** | Rien |
| **Dépendances** | 🔵 INFRA.2 |
| **Effort** | 0.5 jour |
| **Fichiers créés** | `backend/app/api/__init__.py`, `backend/app/api/v1/__init__.py`, `backend/app/api/v1/health.py`, `backend/app/core/lifespan.py` |

**Résumé :** Créer le lifespan manager FastAPI (startup : connexion pools PG, Redis, Qdrant, MinIO ; shutdown : fermeture gracieuse). Endpoint `/health` vérifiant la connectivité de chaque service (PG, Redis, Qdrant, MinIO) avec timeout 2s. Endpoint `/health/ready` pour readiness probe. Ajouter les health checks dans le `docker-compose.yml` pour chaque service.

**Smoke test :** `curl http://localhost:8000/health` → `{"status": "healthy", "services": {"postgres": "ok", ...}}`.

---

### TENANT.1 — Modèle SQLAlchemy Tenant + migration Alembic

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 1 |
| **Parallélisable avec** | Rien (fondation données) |
| **Dépendances** | 🟡 INFRA.2 |
| **Effort** | 1 jour |
| **Fichiers créés** | `backend/app/models/__init__.py`, `backend/app/models/base.py`, `backend/app/models/tenant.py`, `backend/app/schemas/tenant.py`, `backend/app/core/database.py`, `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/001_create_tenants.py` |

**Résumé :** Créer la base SQLAlchemy 2.0 async (engine + sessionmaker async), le modèle `Tenant` dans le schéma `public` (id UUID, name, slug unique, region, logo_url, whatsapp_config JSONB, status enum [active/inactive/provisioning], created_at, updated_at), les schémas Pydantic v2 (TenantCreate, TenantUpdate, TenantResponse, TenantInDB), et la première migration Alembic. Configurer Alembic pour async avec `asyncpg`.

**Smoke test :** `cd backend && alembic upgrade head && python -c "from app.models.tenant import Tenant; print('OK')"`.

---

### TENANT.2 — TenantMiddleware + TenantContext + anti-BOLA

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 2 🅰 |
| **Parallélisable avec** | AUTH.1 (Wave 2 🅱) |
| **Dépendances** | 🔵 TENANT.1 |
| **Effort** | 1-1.5 jours |
| **Sécurité intégrée** | [SÉCU] Anti-BOLA middleware (vérification que chaque ressource appartient au tenant courant) |
| **Fichiers créés** | `backend/app/core/tenant.py`, `backend/app/core/middleware.py` |

**Résumé :** Créer la classe `TenantContext` (slug, db_schema, qdrant_collection, redis_prefix, minio_bucket, whatsapp_config) avec méthode `db_session()` qui set le `search_path` PostgreSQL au schéma du tenant. Créer le middleware `TenantMiddleware` qui résout le tenant selon la source : (1) webhook WhatsApp → lookup Redis `phone_mapping:{phone_number_id}` → tenant_id, (2) back-office → header `X-Tenant-ID` + validation JWT, (3) super-admin → `X-Tenant-ID` optionnel. Le contexte est injecté dans `request.state.tenant`. Dependency `get_current_tenant` pour injection dans les routes. Le middleware anti-BOLA vérifie que chaque ressource accédée appartient au tenant courant.

**Smoke test :** `pytest tests/test_tenant_middleware.py -v` — test avec mock Redis pour résolution tenant.

---

### AUTH.1 — Modèle Admin + bcrypt + JWT (access + refresh)

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 2 🅱 |
| **Parallélisable avec** | TENANT.2 (Wave 2 🅰) |
| **Dépendances** | 🟡 TENANT.1 |
| **Effort** | 1-1.5 jours |
| **Sécurité intégrée** | [SÉCU] bcrypt cost 12+, JWT TTL 30min, refresh rotation usage unique, politique mdp 12+ chars, verrouillage 5 échecs/15min |
| **Fichiers créés** | `backend/app/models/admin.py`, `backend/app/schemas/auth.py`, `backend/app/core/security.py`, `backend/app/services/auth/__init__.py`, `backend/app/services/auth/service.py`, `backend/alembic/versions/002_create_admins.py` |

**Résumé :** Créer le modèle `Admin` (table `admins` dans schéma tenant : id UUID, email unique, password_hash, role enum [super_admin/admin_tenant/supervisor/viewer], is_active, last_login, created_at). Service `AuthService` avec : hash bcrypt (cost 12+), vérification mot de passe, génération JWT (access TTL 30min + refresh TTL 7j rotation usage unique), validation politique mdp (12+ chars, 1 maj, 1 chiffre, 1 spécial, check liste 10k mdp courants), verrouillage compte (5 échecs / 15 min → blocage 30 min, compteur Redis `{slug}:lockout:{email}`). Schémas Pydantic : LoginRequest, LoginResponse (access_token, refresh_token, admin info), TokenPayload, AdminCreate, AdminResponse.

**Smoke test :** `python -c "from app.core.security import hash_password, verify_password; h = hash_password('Test1234!@#$'); assert verify_password('Test1234!@#$', h); print('OK')"`.

---

### TENANT.3 — Service TenantProvisioning

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 3 🅰 |
| **Parallélisable avec** | AUTH.2 (Wave 3 🅱), AUTH.3 (Wave 3 🅲) |
| **Dépendances** | 🔵 TENANT.2 |
| **Effort** | 1-1.5 jours |
| **Fichiers créés** | `backend/app/services/tenant/__init__.py`, `backend/app/services/tenant/provisioning.py` |

**Résumé :** Créer le service `TenantProvisioningService` avec les méthodes : `create_tenant()` (insertion dans table `tenants`), `provision_database()` (CREATE SCHEMA + exécution de toutes les migrations tenant via SQL dynamique), `provision_qdrant_collection()` (création collection `kb_{slug}` avec config HNSW, dimension 768), `provision_minio_bucket()` (création bucket `cri-{slug}` avec politique IAM), `provision_redis_namespace()` (test de connectivité + enregistrement mapping), `provision_full()` (orchestration atomique des 4 étapes avec rollback en cas d'échec). Transaction rollback : si une étape échoue, les étapes précédentes sont nettoyées.

**Smoke test :** Test d'intégration qui provisionne un tenant de test puis vérifie que le schéma PG, la collection Qdrant, le bucket MinIO existent.

---

### AUTH.2 — RBAC middleware + décorateurs de rôles

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 3 🅱 |
| **Parallélisable avec** | TENANT.3 (Wave 3 🅰), AUTH.3 (Wave 3 🅲) |
| **Dépendances** | 🔵 AUTH.1 |
| **Effort** | 0.5-1 jour |
| **Fichiers créés** | `backend/app/core/permissions.py`, `backend/app/api/v1/auth.py` |

**Résumé :** Créer la dependency `get_current_admin` (extraction + validation JWT depuis header `Authorization: Bearer`), le système RBAC avec matrice de permissions par rôle (super_admin: tout, admin_tenant: gestion KB + contacts + conversations + campagnes, supervisor: lecture conversations + feedback, viewer: lecture seule). Décorateur/dependency `require_role(roles: list[str])` pour protéger les endpoints. Endpoints auth : `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`.

**Smoke test :** `pytest tests/test_auth_rbac.py -v` — test login, accès protégé par rôle, rejet si rôle insuffisant.

---

### AUTH.3 — Rate limiting multi-niveau (Redis)

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 3 🅲 |
| **Parallélisable avec** | TENANT.3 (Wave 3 🅰), AUTH.2 (Wave 3 🅱) |
| **Dépendances** | 🔵 AUTH.1, INFRA.2 |
| **Effort** | 0.5-1 jour |
| **Sécurité intégrée** | [SÉCU] Rate limiting 4 niveaux (annexe sécurité Phase 1) |
| **Fichiers créés** | `backend/app/core/rate_limiter.py` |

**Résumé :** Implémenter le rate limiting 4 niveaux avec compteurs Redis (TTL sliding window) : (1) Global IP : 100 req/min → clé `rl:ip:{ip}` → HTTP 429 + header Retry-After, (2) Tenant webhook : 50 req/min → clé `{slug}:rl:webhook` → HTTP 429 + alerte admin, (3) Utilisateur WhatsApp : 10 msg/min → clé `{slug}:rl:user:{phone}` → message WhatsApp "Veuillez patienter", (4) OTP anti-bruteforce : 3 tentatives / 15 min → clé `{slug}:rl:otp:{phone}` → blocage temporaire + alerte. Implémenté comme middleware FastAPI avec décorateur configurable par endpoint.

**Smoke test :** Test unitaire simulant 101 requêtes depuis la même IP en 1 minute → 429 à la 101e.

---

### AUTH.4 — Tests auth + sécurité

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 10 🅱 |
| **Parallélisable avec** | TENANT.5 (Wave 10 🅰), ORCHESTRATOR.3 (Wave 10 🅲) |
| **Dépendances** | 🔵 AUTH.3 |
| **Effort** | 0.5-1 jour |
| **Fichiers créés** | `backend/tests/test_auth_service.py`, `backend/tests/test_rate_limiter.py`, `backend/tests/test_rbac.py` |

**Résumé :** Suite de tests complète : (1) Test login/logout/refresh, (2) Test politique mdp (rejet mdp faibles), (3) Test verrouillage compte après 5 échecs, (4) Test RBAC (chaque rôle accède uniquement à ses ressources), (5) Test rate limiting 4 niveaux, (6) Test JWT expiré/invalide/absent. Utiliser pytest-asyncio + httpx.AsyncClient + factories.

**Smoke test :** `pytest tests/test_auth_*.py tests/test_rate_limiter.py tests/test_rbac.py -v --tb=short`.

---

### TENANT.4 — API CRUD Tenant (super-admin)

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 4 🅰 |
| **Parallélisable avec** | WHATSAPP.1 (Wave 4 🅱), RAG.1 (Wave 4 🅲), CONTACTS.1 (Wave 4 🅳) |
| **Dépendances** | 🔵 TENANT.3, AUTH.2 |
| **Effort** | 0.5-1 jour |
| **Fichiers créés** | `backend/app/api/v1/tenants.py`, `backend/app/services/tenant/service.py` |

**Résumé :** Endpoints CRUD tenant protégés par rôle `super_admin` : `POST /api/v1/tenants` (création + provisionnement auto), `GET /api/v1/tenants` (liste paginée), `GET /api/v1/tenants/{slug}` (détail + stats), `PATCH /api/v1/tenants/{slug}` (mise à jour config), `POST /api/v1/tenants/{slug}/activate` / `deactivate`. Le service orchestre le provisioning complet. Réponses avec pagination offset/limit.

**Smoke test :** `pytest tests/test_api_tenants.py -v` — CRUD complet + vérification provisioning.

---

### TENANT.5 — Tests multi-tenant isolation

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 10 🅰 |
| **Parallélisable avec** | AUTH.4 (Wave 10 🅱), ORCHESTRATOR.3 (Wave 10 🅲) |
| **Dépendances** | 🔵 TENANT.4 |
| **Effort** | 0.5-1 jour |
| **Fichiers créés** | `backend/tests/test_tenant_isolation.py`, `backend/tests/conftest.py` (fixtures multi-tenant) |

**Résumé :** Tests critiques d'isolation : (1) Créer 2 tenants, insérer des données dans chacun, vérifier qu'un tenant ne voit pas les données de l'autre (PG schéma, Qdrant collection, Redis préfixe, MinIO bucket), (2) Vérifier que le middleware refuse les requêtes sans tenant résolu, (3) Vérifier que l'anti-BOLA rejette l'accès à une ressource d'un autre tenant, (4) Fixtures pytest réutilisables pour les tests suivants.

**Smoke test :** `pytest tests/test_tenant_isolation.py -v --tb=short` — tous les tests passent.

---

### WHATSAPP.1 — Client Meta Cloud API (envoi/réception)

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 4 🅱 |
| **Parallélisable avec** | TENANT.4 (Wave 4 🅰), RAG.1 (Wave 4 🅲), CONTACTS.1 (Wave 4 🅳) |
| **Dépendances** | 🟡 TENANT.2 |
| **Effort** | 1-1.5 jours |
| **Fichiers créés** | `backend/app/services/whatsapp/__init__.py`, `backend/app/services/whatsapp/client.py`, `backend/app/services/whatsapp/schemas.py` |

**Résumé :** Client httpx async pour Meta Cloud API v21.0. Méthodes : `send_text_message()`, `send_interactive_buttons()` (max 3 boutons), `send_interactive_list()` (max 10 items), `send_template_message()`, `mark_as_read()`, `download_media()` (images, audio, documents). Gestion du token par tenant (depuis `tenant.whatsapp_config`). Retry avec backoff exponentiel (3 tentatives). Schémas Pydantic pour tous les payloads Meta (IncomingMessage, OutgoingMessage, MessageStatus, MediaInfo). Métriques Prometheus : compteur messages envoyés/reçus par tenant, latence API Meta.

**Smoke test :** Test unitaire avec mock httpx vérifiant la construction des payloads Meta pour chaque type de message.

---

### WHATSAPP.2 — Webhook handler + validation HMAC-SHA256

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 5 🅰 |
| **Parallélisable avec** | RAG.2 (Wave 5 🅱), FEEDBACK.1 (Wave 5 🅲), INCITATIONS.1 (Wave 5 🅳) |
| **Dépendances** | 🔵 WHATSAPP.1 |
| **Effort** | 1 jour |
| **Sécurité intégrée** | [SÉCU] Signature HMAC-SHA256 webhook (header X-Hub-Signature-256 + app_secret), validation payload Pydantic v2 strict |
| **Fichiers créés** | `backend/app/api/v1/webhooks.py`, `backend/app/services/whatsapp/webhook_handler.py` |

**Résumé :** Deux endpoints webhook : `GET /api/v1/webhooks/whatsapp` (vérification Meta challenge), `POST /api/v1/webhooks/whatsapp` (réception messages). Le handler POST : (1) Valide la signature HMAC-SHA256 du header `X-Hub-Signature-256` avec le `app_secret` → 403 si invalide, (2) Parse le payload avec Pydantic strict (rejette les champs inconnus), (3) Extrait le `phone_number_id` → résolution tenant via middleware, (4) Dispatche le message au router conversationnel (background task pour ne pas bloquer le webhook → réponse 200 immédiate à Meta). Gestion des types : text, interactive (button_reply, list_reply), image, audio, document, location. Idempotence via message_id en Redis (TTL 24h).

**Smoke test :** Test avec un payload Meta simulé + signature HMAC valide → 200. Payload sans signature → 403.

---

### WHATSAPP.3 — Router conversationnel (dispatch intent)

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 6 🅱 |
| **Parallélisable avec** | RAG.3 (Wave 6 🅰), LANG.1 (Wave 6 🅲) |
| **Dépendances** | 🔵 WHATSAPP.2 |
| **Effort** | 1 jour |
| **Fichiers créés** | `backend/app/services/whatsapp/router.py`, `backend/app/services/whatsapp/conversation_manager.py` |

**Résumé :** Le `ConversationManager` orchestre le flux : (1) Récupère ou crée la conversation dans PG, (2) Récupère ou crée le contact (création auto avec téléphone + langue détectée), (3) Charge l'historique récent (3-5 derniers messages) depuis PG, (4) Transmet au graphe LangGraph (Wave 7-8) ou, en attendant, à un dispatcher simple basé sur keywords. (5) Sauvegarde le message entrant + la réponse sortante dans PG, (6) Envoie la réponse via WHATSAPP.1. Le `ConversationRouter` sera remplacé par l'orchestrateur LangGraph (ORCHESTRATOR.1) mais fournit dès maintenant le squelette de routage.

**Smoke test :** Test unitaire : message texte → création conversation + contact + réponse envoyée.

---

### WHATSAPP.4 — Gestion de session Redis

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 7 🅱 |
| **Parallélisable avec** | RAG.4 (Wave 7 🅰), INCITATIONS.2 (Wave 7 🅲) |
| **Dépendances** | 🔵 WHATSAPP.3 |
| **Effort** | 0.5-1 jour |
| **Fichiers créés** | `backend/app/services/whatsapp/session.py` |

**Résumé :** Service `SessionManager` gérant l'état conversationnel dans Redis. Clé : `{slug}:session:{phone}`. Données : `ConversationState` (conversation_id, current_intent, current_node, context JSONB, last_activity timestamp, language). TTL : 30 minutes d'inactivité (configurable par tenant). Méthodes : `get_or_create_session()`, `update_session()`, `clear_session()`, `extend_ttl()`. Le state permet de reprendre une arborescence d'incitations ou un flow OTP en cours sans perdre le contexte. Sérialisation JSON compacte.

**Smoke test :** Test : créer session → lire → mettre à jour → vérifier TTL → attendre expiration → vérifier absence.

---

### WHATSAPP.5 — Tests webhook + intégration WhatsApp

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 11 🅰 |
| **Parallélisable avec** | RAG.6 (Wave 11 🅱), INCITATIONS.3 (Wave 11 🅲) |
| **Dépendances** | 🔵 WHATSAPP.4 |
| **Effort** | 0.5-1 jour |
| **Fichiers créés** | `backend/tests/test_webhook.py`, `backend/tests/test_whatsapp_client.py`, `backend/tests/test_session.py`, `backend/tests/fixtures/meta_payloads.py` |

**Résumé :** (1) Test HMAC : signature valide → 200, invalide → 403, absente → 403, (2) Test challenge GET → retourne hub.challenge, (3) Test payload text → conversation créée + réponse envoyée, (4) Test payload interactive (button_reply, list_reply), (5) Test idempotence (même message_id deux fois), (6) Test rate limiting utilisateur (11e message en 1 min → message "patientez"), (7) Test session Redis (cycle de vie complet), (8) Fixtures avec payloads Meta réalistes.

**Smoke test :** `pytest tests/test_webhook.py tests/test_whatsapp_client.py tests/test_session.py -v`.

---

### RAG.1 — Service d'ingestion (chunking + embeddings)

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 4 🅲 |
| **Parallélisable avec** | TENANT.4 (Wave 4 🅰), WHATSAPP.1 (Wave 4 🅱), CONTACTS.1 (Wave 4 🅳) |
| **Dépendances** | 🟡 TENANT.2 |
| **Effort** | 1.5-2 jours |
| **Fichiers créés** | `backend/app/services/rag/__init__.py`, `backend/app/services/rag/ingestion.py`, `backend/app/services/rag/chunker.py`, `backend/app/services/rag/embeddings.py` |

**Résumé :** Module d'ingestion de documents pour le RAG. (1) `DocumentChunker` : découpage en segments de 512-1024 tokens avec chevauchement de 128 tokens, support PDF (PyPDF2/pdfplumber), Word (python-docx), Excel (openpyxl), texte brut. (2) `EmbeddingService` : abstraction pour text-embedding-004 (Google API) ou multilingual-e5-large, génération batch d'embeddings, dimension 768. (3) `IngestionService` : orchestration complète — réception fichier (MinIO) → extraction texte → chunking → enrichissement métadonnées basique (titre, source, catégorie, langue, hash SHA-256 du contenu) → embeddings → stockage dans Qdrant (collection `kb_{slug}`) + PG (tables `kb_documents` + `kb_chunks`). (4) Détection de doublons via content_hash.

**Smoke test :** Test : ingérer un fichier texte de 3 pages → vérifier chunks dans Qdrant + métadonnées dans PG.

---

### RAG.2 — Service de retrieval Qdrant

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 5 🅱 |
| **Parallélisable avec** | WHATSAPP.2 (Wave 5 🅰), FEEDBACK.1 (Wave 5 🅲), INCITATIONS.1 (Wave 5 🅳) |
| **Dépendances** | 🔵 RAG.1 |
| **Effort** | 1 jour |
| **Fichiers créés** | `backend/app/services/rag/retrieval.py` |

**Résumé :** Service `RetrievalService` : (1) Génère l'embedding de la question utilisateur via `EmbeddingService`, (2) Recherche hybride dans Qdrant : similarité cosinus + filtrage par métadonnées JSON (Structured RAG — filtres optionnels sur `category`, `language`, `applicable_sectors`, `legal_forms`), (3) Récupère les Top-K chunks (K configurable, défaut 5), (4) Re-ranking optionnel via Gemini (scoring de pertinence des chunks par rapport à la question), (5) Retourne les chunks ordonnés par score avec métadonnées. Métriques Prometheus : temps de retrieval, score confiance moyen, nombre de résultats.

**Smoke test :** Test : ingérer 10 chunks, rechercher une question → vérifier que le chunk le plus pertinent est en premier.

---

### RAG.3 — Service de génération Gemini + guardrails

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 6 🅰 |
| **Parallélisable avec** | WHATSAPP.3 (Wave 6 🅱), LANG.1 (Wave 6 🅲) |
| **Dépendances** | 🔵 RAG.2 |
| **Effort** | 1.5-2 jours |
| **Sécurité intégrée** | [SÉCU] Input guardrails (injection, hors-périmètre), Output guardrails (PII masking, ton, hallucination), anonymisation prompts Gemini |
| **Fichiers créés** | `backend/app/services/ai/__init__.py`, `backend/app/services/ai/gemini_client.py`, `backend/app/services/guardrails/__init__.py`, `backend/app/services/guardrails/input_guard.py`, `backend/app/services/guardrails/output_guard.py`, `backend/app/services/guardrails/pii_masker.py`, `backend/app/services/rag/generation.py` |

**Résumé :** (1) `GeminiClient` : abstraction httpx async pour Gemini 2.5 Flash API (texte, image, audio), configuration par tenant, métriques Prometheus (latence TTFT, tokens input/output, coût estimé, taux erreur). (2) `InputGuard` : détection injection prompt (regex patterns : "ignore instructions", "role-play", "you are now"), détection hors-périmètre via classification Gemini (~50 tokens), refus gracieux avec message institutionnel prédéfini. (3) `PIIMasker` : anonymisation CIN (`[A-Z]{1,2}\d{5,6}`), téléphone (`+212/06/07 + 8 chiffres`), montants, noms propres — AVANT envoi à Gemini. (4) `OutputGuard` : score de confiance RAG (si < seuil 0.7 → disclaimer), vérification de citation (faits présents dans chunks), scoring ton institutionnel. (5) `GenerationService` : construction du prompt (instructions système + chunks anonymisés + historique 3-5 messages + question), appel Gemini, post-traitement guardrails.

**Smoke test :** Test : question FAQ avec chunks → réponse générée. Question avec PII → PII masqué. Prompt injection → refus gracieux.

---

### RAG.4 — Pipeline RAG orchestré (LangGraph FAQAgent)

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 7 🅰 |
| **Parallélisable avec** | WHATSAPP.4 (Wave 7 🅱), INCITATIONS.2 (Wave 7 🅲) |
| **Dépendances** | 🔵 RAG.3, LANG.1 |
| **Effort** | 1-1.5 jours |
| **Fichiers créés** | `backend/app/services/rag/pipeline.py`, `backend/app/services/rag/faq_agent.py` |

**Résumé :** Orchestration complète du pipeline RAG en un nœud LangGraph `FAQAgent` : (1) Réception question + contexte (langue, historique), (2) Input guardrails, (3) Détection langue → adaptation prompt, (4) Retrieval (RAG.2), (5) Génération (RAG.3), (6) Output guardrails, (7) Si score confiance < seuil → flag pour apprentissage supervisé (unanswered_questions), (8) Retour de la réponse formatée + chunk_ids (pour corrélation feedback). Le `FAQAgent` est un nœud réutilisable dans le graphe LangGraph global (ORCHESTRATOR.1). Stockage trace LLM dans PG (prompt, réponse, tokens, latence, intention, chunks utilisés, rétention 90j).

**Smoke test :** Test E2E : question → retrieval → génération → réponse avec chunk_ids + trace stockée.

---

### RAG.5 — API endpoints KB (upload, search, manage)

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 8 🅱 |
| **Parallélisable avec** | ORCHESTRATOR.1 (Wave 8 🅰) |
| **Dépendances** | 🔵 RAG.4, AUTH.2 |
| **Effort** | 1 jour |
| **Fichiers créés** | `backend/app/api/v1/knowledge_base.py`, `backend/app/api/v1/unanswered.py` |

**Résumé :** Endpoints back-office protégés par RBAC (admin_tenant+) : (1) `POST /api/v1/kb/documents` : upload fichier (PDF, Word, Excel, max 10MB) → MinIO → ingestion async (worker ARQ), (2) `GET /api/v1/kb/documents` : liste paginée avec filtres (catégorie, statut, langue), (3) `GET /api/v1/kb/documents/{id}` : détail + chunks associés, (4) `DELETE /api/v1/kb/documents/{id}` : suppression document + chunks Qdrant, (5) `GET /api/v1/kb/search` : recherche sémantique dans la KB (test depuis le back-office), (6) `GET /api/v1/kb/unanswered` : liste des questions non couvertes avec réponse IA proposée, (7) `PATCH /api/v1/kb/unanswered/{id}` : valider/rejeter/éditer une proposition → réinjection dans Qdrant si validée. Pagination offset/limit sur toutes les listes.

**Smoke test :** Test : upload PDF → vérifier statut "indexing" → vérifier chunks créés → recherche sémantique → résultat trouvé.

---

### RAG.6 — Tests RAG end-to-end

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 11 🅱 |
| **Parallélisable avec** | WHATSAPP.5 (Wave 11 🅰), INCITATIONS.3 (Wave 11 🅲) |
| **Dépendances** | 🔵 RAG.5 |
| **Effort** | 0.5-1 jour |
| **Fichiers créés** | `backend/tests/test_rag_ingestion.py`, `backend/tests/test_rag_retrieval.py`, `backend/tests/test_rag_generation.py`, `backend/tests/test_rag_pipeline.py`, `backend/tests/test_api_kb.py` |

**Résumé :** (1) Test ingestion : fichier PDF → chunks corrects (taille, overlap, métadonnées), (2) Test retrieval : question FR → chunks pertinents, question AR → même qualité, (3) Test génération : réponse dans la langue de la question, PII masqué, ton formel, (4) Test pipeline E2E : question → réponse complète avec chunk_ids et trace, (5) Test guardrails : injection prompt → refus, contenu hors-périmètre → refus, (6) Test apprentissage supervisé : question non couverte → validation → réinjection dans Qdrant, (7) Test API KB : CRUD documents + recherche.

**Smoke test :** `pytest tests/test_rag_*.py tests/test_api_kb.py -v --tb=short`.

---

### ORCHESTRATOR.1 — Graphe LangGraph complet (IntentDetector + Router)

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 8 🅰 |
| **Parallélisable avec** | RAG.5 (Wave 8 🅱) |
| **Dépendances** | 🟡 RAG.4, WHATSAPP.3, INCITATIONS.2, FEEDBACK.1 |
| **Effort** | 1.5-2 jours |
| **Fichiers créés** | `backend/app/services/orchestrator/__init__.py`, `backend/app/services/orchestrator/graph.py`, `backend/app/services/orchestrator/intent_detector.py`, `backend/app/services/orchestrator/router.py`, `backend/app/services/orchestrator/state.py` |

**Résumé :** Construction du graphe LangGraph Phase 1 : (1) `ConversationState` : dataclass typée (messages, current_intent, language, tenant_slug, contact_id, session_data, response). (2) `IntentDetector` : nœud qui classifie l'intention via Gemini (~50 tokens) parmi : FAQ, incitations, hors_perimetre + input guardrails intégrés. (Phase 2 ajoutera : suivi_dossier, agent_interne, escalade). (3) `Router` : nœud conditionnel qui aiguille vers FAQAgent, IncentivesAgent, ou message de refus gracieux (hors-périmètre). (4) `ResponseValidator` : nœud guardrails post-génération (PII, ton, confiance). (5) `FeedbackCollector` : nœud qui ajoute les boutons feedback (👍/👎/❓) à la réponse. Assemblage du graphe : IntentDetector → Router → [FAQAgent | IncentivesAgent | refus] → ResponseValidator → FeedbackCollector → fin.

**Smoke test :** Test : message FAQ → route vers FAQAgent → réponse. Message incitations → route vers IncentivesAgent. Message hors-périmètre → refus poli.

---

### ORCHESTRATOR.2 — Intégration WhatsApp ↔ LangGraph

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 9 🅰 |
| **Parallélisable avec** | CONTACTS.2 (Wave 9 🅱), FEEDBACK.2 (Wave 9 🅲) |
| **Dépendances** | 🔵 ORCHESTRATOR.1, WHATSAPP.4 |
| **Effort** | 1 jour |
| **Fichiers créés** | `backend/app/services/orchestrator/whatsapp_integration.py` — modification de `backend/app/services/whatsapp/router.py` |

**Résumé :** Connecter le flux WhatsApp complet au graphe LangGraph : (1) Message WhatsApp reçu → webhook → ConversationManager charge session Redis + historique PG, (2) Construction du `ConversationState` depuis le contexte, (3) Exécution du graphe LangGraph (IntentDetector → Router → Agent → ResponseValidator → FeedbackCollector), (4) Formatage de la réponse pour WhatsApp (texte, boutons interactifs, listes), (5) Envoi via WhatsApp client, (6) Sauvegarde message + réponse dans PG, (7) Mise à jour session Redis. Ce prompt remplace le dispatcher simple de WHATSAPP.3 par l'orchestrateur LangGraph.

**Smoke test :** Test E2E : payload Meta simulé → webhook → LangGraph → réponse WhatsApp envoyée (mock httpx).

---

### ORCHESTRATOR.3 — Tests E2E pipeline complet

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 10 🅲 |
| **Parallélisable avec** | TENANT.5 (Wave 10 🅰), AUTH.4 (Wave 10 🅱) |
| **Dépendances** | 🔵 ORCHESTRATOR.2 |
| **Effort** | 0.5-1 jour |
| **Fichiers créés** | `backend/tests/test_orchestrator.py`, `backend/tests/test_e2e_flow.py` |

**Résumé :** Tests du flux complet : (1) Message FAQ WhatsApp → intent FAQ → RAG → réponse avec chunks + feedback buttons, (2) Message incitations → intent incitations → arborescence interactive, (3) Message hors-périmètre → refus poli, (4) Conversation multi-tours (historique préservé), (5) Vérification isolation multi-tenant (tenant A ne reçoit pas les données tenant B), (6) Vérification métriques Prometheus incrémentées, (7) Vérification traces LLM stockées dans PG.

**Smoke test :** `pytest tests/test_orchestrator.py tests/test_e2e_flow.py -v`.

---

### INCITATIONS.1 — Modèle de données incitations

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 5 🅳 |
| **Parallélisable avec** | WHATSAPP.2 (Wave 5 🅰), RAG.2 (Wave 5 🅱), FEEDBACK.1 (Wave 5 🅲) |
| **Dépendances** | 🟡 TENANT.1 |
| **Effort** | 0.5-1 jour |
| **Fichiers créés** | `backend/app/models/incentive.py`, `backend/app/schemas/incentive.py`, `backend/alembic/versions/003_create_incentives.py`, `backend/app/services/incentives/__init__.py`, `backend/app/services/incentives/data.py` |

**Résumé :** Tables d'incitations dans le schéma tenant : `incentive_categories` (id, name, parent_id nullable, order, is_leaf, created_at) pour l'arborescence hiérarchique (secteur → statut juridique → localisation → nature), `incentive_items` (id, category_id, title, description, conditions, legal_reference, eligibility_criteria JSONB, documents_required JSONB, language, created_at). Schémas Pydantic : IncentiveCategoryTree, IncentiveItem, IncentiveResponse. Service `IncentiveDataService` : `get_tree()` (arborescence complète), `get_children(parent_id)`, `get_items(category_id)`, `search_incentives(criteria)`. Seed data initial pour CRI-RSK.

**Smoke test :** Test : charger l'arborescence → vérifier hiérarchie 4 niveaux → récupérer items pour une feuille.

---

### INCITATIONS.2 — IncentivesAgent LangGraph (arborescence WhatsApp)

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 7 🅲 |
| **Parallélisable avec** | RAG.4 (Wave 7 🅰), WHATSAPP.4 (Wave 7 🅱) |
| **Dépendances** | 🔵 INCITATIONS.1, WHATSAPP.1 |
| **Effort** | 1-1.5 jours |
| **Fichiers créés** | `backend/app/services/orchestrator/incentives_agent.py` |

**Résumé :** Nœud LangGraph `IncentivesAgent` : parcours interactif de l'arborescence d'incitations via boutons/listes WhatsApp. (1) État de session : `current_category_id` dans Redis (via SessionManager), (2) À chaque message : affiche les enfants de la catégorie courante sous forme de boutons WhatsApp (≤3 options) ou liste WhatsApp (>3 options), (3) L'utilisateur clique → descente d'un niveau, (4) À une feuille : affiche les fiches d'incitation (titre, description, conditions, documents requis), (5) Boutons "Retour" et "Recommencer" à chaque étape, (6) Si l'utilisateur tape du texte libre au lieu de cliquer → recherche sémantique dans les incitations via Gemini, (7) Timeout session 10 min → retour au début. Format WhatsApp : utilise `send_interactive_buttons()` et `send_interactive_list()` de WHATSAPP.1.

**Smoke test :** Test : simuler un parcours complet (4 niveaux) → vérifier les messages interactifs envoyés à chaque étape.

---

### INCITATIONS.3 — Tests parcours incitations

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 11 🅲 |
| **Parallélisable avec** | WHATSAPP.5 (Wave 11 🅰), RAG.6 (Wave 11 🅱) |
| **Dépendances** | 🔵 INCITATIONS.2 |
| **Effort** | 0.5 jour |
| **Fichiers créés** | `backend/tests/test_incentives.py` |

**Résumé :** (1) Test arborescence complète (4 niveaux de navigation), (2) Test bouton "Retour" (remonte d'un niveau), (3) Test bouton "Recommencer" (retour racine), (4) Test recherche texte libre dans les incitations, (5) Test timeout session (10 min → reset), (6) Test multi-tenant (incitations tenant A ≠ tenant B), (7) Test format WhatsApp (boutons si ≤3 options, liste si >3).

**Smoke test :** `pytest tests/test_incentives.py -v`.

---

### LANG.1 — Détection de langue + prompts multilingues

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 6 🅲 |
| **Parallélisable avec** | RAG.3 (Wave 6 🅰), WHATSAPP.3 (Wave 6 🅱) |
| **Dépendances** | 🟡 TENANT.2 |
| **Effort** | 0.5-1 jour |
| **Fichiers créés** | `backend/app/services/ai/language.py`, `backend/app/services/ai/prompts.py` |

**Résumé :** (1) `LanguageDetector` : détection automatique FR/AR/EN. Heuristique rapide (regex Unicode ranges pour arabe, mots-clés fréquents FR/EN) + fallback Gemini pour les cas ambigus (~20 tokens). Retourne un enum `Language(fr, ar, en)`. (2) `PromptManager` : templates de prompts système multilingues. Prompt système principal en français avec instruction de répondre dans la langue détectée. Messages d'erreur, de refus, de feedback traduits dans les 3 langues. Messages WhatsApp système (bienvenue, patientez, hors-périmètre) en 3 langues. Configuration par tenant (possibilité de personnaliser les messages). Stockage de la langue préférée dans le profil contact (mise à jour après chaque détection).

**Smoke test :** Test : texte FR → `Language.fr`, texte AR → `Language.ar`, texte EN → `Language.en`, texte mixte → détection correcte.

---

### LANG.2 — Tests trilinguisme

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 15 🅰 |
| **Parallélisable avec** | Intégration finale (Wave 15 🅱) |
| **Dépendances** | 🔵 LANG.1, ORCHESTRATOR.2 |
| **Effort** | 0.5 jour |
| **Fichiers créés** | `backend/tests/test_language.py`, `backend/tests/test_multilingual.py` |

**Résumé :** (1) Test détection : 10+ exemples par langue (phrases courtes, longues, formelles, informelles, Darija vs arabe classique), (2) Test pipeline complet FR : question FR → réponse FR, (3) Test pipeline complet AR : question AR → réponse AR, (4) Test pipeline complet EN : question EN → réponse EN, (5) Test switch de langue en cours de conversation, (6) Test messages système dans les 3 langues, (7) Test mise à jour langue préférée du contact.

**Smoke test :** `pytest tests/test_language.py tests/test_multilingual.py -v`.

---

### FEEDBACK.1 — Modèle feedback + service collecte

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 5 🅲 |
| **Parallélisable avec** | WHATSAPP.2 (Wave 5 🅰), RAG.2 (Wave 5 🅱), INCITATIONS.1 (Wave 5 🅳) |
| **Dépendances** | 🟡 TENANT.1 |
| **Effort** | 0.5-1 jour |
| **Fichiers créés** | `backend/app/models/feedback.py`, `backend/app/schemas/feedback.py`, `backend/app/services/feedback/__init__.py`, `backend/app/services/feedback/service.py` |

**Résumé :** Table `feedback` déjà définie dans TENANT.1 (id, message_id FK, rating int 1-5, comment nullable, chunk_ids JSONB, created_at). Table `unanswered_questions` (id, question, proposed_answer, status enum [pending/approved/rejected], reviewed_by FK, review_note, created_at). `FeedbackService` : `record_feedback()` (stocke le feedback + si rating=1 → crée une `unanswered_question` automatiquement), `get_feedback_stats()` (taux CSAT, top chunks sous-performants), `check_csat_alert()` (si CSAT < seuil configurable sur 7j → flag alerte). Le nœud LangGraph `FeedbackCollector` appelle ce service quand l'utilisateur clique sur un bouton feedback.

**Smoke test :** Test : enregistrer feedback positif + négatif → vérifier stats → vérifier unanswered_question créée pour négatif.

---

### FEEDBACK.2 — API feedback + tests

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 9 🅲 |
| **Parallélisable avec** | ORCHESTRATOR.2 (Wave 9 🅰), CONTACTS.2 (Wave 9 🅱) |
| **Dépendances** | 🔵 FEEDBACK.1, AUTH.2 |
| **Effort** | 0.5 jour |
| **Fichiers créés** | `backend/app/api/v1/feedback.py`, `backend/tests/test_feedback.py` |

**Résumé :** Endpoints back-office protégés RBAC : `GET /api/v1/feedback` (liste paginée + filtres rating, date), `GET /api/v1/feedback/stats` (CSAT global, par période, par catégorie, top 10 chunks sous-performants), `GET /api/v1/feedback/alerts` (alertes CSAT actives). Tests : (1) Collecte feedback via WhatsApp (👍→rating 5, 👎→rating 1 + raison), (2) Corrélation chunk_ids, (3) Stats CSAT correctes, (4) Alerte quand seuil dépassé.

**Smoke test :** `pytest tests/test_feedback.py -v`.

---

### CONTACTS.1 — Modèle Contact + création auto + service

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 4 🅳 |
| **Parallélisable avec** | TENANT.4 (Wave 4 🅰), WHATSAPP.1 (Wave 4 🅱), RAG.1 (Wave 4 🅲) |
| **Dépendances** | 🟡 TENANT.2 |
| **Effort** | 1 jour |
| **Fichiers créés** | `backend/app/models/contact.py`, `backend/app/models/conversation.py`, `backend/app/models/message.py`, `backend/app/schemas/contact.py`, `backend/app/services/contact/__init__.py`, `backend/app/services/contact/service.py`, `backend/alembic/versions/004_create_contacts_conversations.py` |

**Résumé :** Modèles SQLAlchemy : `Contact` (id UUID, phone unique E.164, name nullable, language enum, cin nullable, opt_in_status enum [opted_in/opted_out/pending], tags JSONB, source enum [whatsapp/import/manual], created_at, updated_at — index sur phone, cin, tags GIN), `Conversation` (id UUID, contact_id FK, agent_type enum [public/internal], status enum [active/ended/escalated/human_handled], started_at, ended_at), `Message` (id UUID, conversation_id FK, direction enum [inbound/outbound], type enum [text/image/audio/document/interactive/system], content, media_url nullable, chunk_ids JSONB nullable, whatsapp_message_id nullable, timestamp). `ContactService` : `get_or_create_by_phone()` (création auto lors du premier message WhatsApp), `update_contact()`, `search_contacts()` (recherche full-text sur nom/phone/CIN), `handle_opt_out()` (commande "STOP" → opt_out_status). Pagination + recherche optimisée pour 20 000+ contacts.

**Smoke test :** Test : `get_or_create_by_phone("+212600000000")` → crée le contact → 2e appel → retourne le même.

---

### CONTACTS.2 — API contacts + tests

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 9 🅱 |
| **Parallélisable avec** | ORCHESTRATOR.2 (Wave 9 🅰), FEEDBACK.2 (Wave 9 🅲) |
| **Dépendances** | 🔵 CONTACTS.1, AUTH.2 |
| **Effort** | 0.5-1 jour |
| **Fichiers créés** | `backend/app/api/v1/contacts.py`, `backend/tests/test_contacts.py` |

**Résumé :** Endpoints RBAC (admin_tenant+) : `GET /api/v1/contacts` (liste paginée, recherche, filtres par tags/opt_in/langue), `GET /api/v1/contacts/{id}` (détail + historique conversations), `PATCH /api/v1/contacts/{id}` (mise à jour tags, nom, langue), `POST /api/v1/contacts/import` (import Excel/CSV avec dédoublonnage sur phone E.164), `GET /api/v1/contacts/export` (export Excel filtré). Tests : (1) CRUD contacts, (2) Recherche par nom/phone/CIN/tag, (3) Import Excel avec doublons → dédoublonnés, (4) Opt-out STOP → exclu des campagnes.

**Smoke test :** `pytest tests/test_contacts.py -v`.

---

### BACKOFFICE.1 — Setup Next.js + design system complet

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 12 (peut démarrer en parallèle dès Wave 4) |
| **Parallélisable avec** | Tout le backend à partir de Wave 4 |
| **Dépendances** | 🟢 Aucune dépendance backend |
| **Effort** | 1.5-2 jours |
| **Design intégré** | [DESIGN] Palette Modern Warm complète, typographie, composants shadcn/ui, layout, RTL |
| **Fichiers créés** | `frontend/package.json`, `frontend/tsconfig.json`, `frontend/tailwind.config.ts`, `frontend/src/app/layout.tsx`, `frontend/src/app/globals.css`, `frontend/src/lib/utils.ts`, `frontend/src/components/ui/` (shadcn init), `docker/frontend.Dockerfile` |

**Résumé :** Initialisation Next.js 15 (App Router, TypeScript strict) + TailwindCSS + shadcn/ui. Configuration du design system "Modern Warm" complet : (1) CSS variables dans `globals.css` (palette terracotta #C4704B, sable #D4A574, crème #FAF7F2, sidebar dark brown #3D2B1F, sémantiques success/warning/error/info/olive), (2) Tailwind config (fonts: Plus Jakarta Sans, Inter Variable, Noto Sans Arabic, JetBrains Mono), (3) Initialisation shadcn/ui avec thème custom, (4) Support RTL natif (`dir="rtl"` conditionnel, logical properties), (5) Composants de base shadcn : Button, Input, Card, Badge, Table, Dialog, Sheet, Dropdown, Toast, Skeleton. (6) Dockerfile frontend multi-stage, non-root. **AUCUN dark mode. AUCUN gradient agressif.**

**Smoke test :** `cd frontend && npm run build && npm run dev` → page blanche avec bonne palette.

---

### BACKOFFICE.2 — Auth pages (login) + layout sidebar/topbar + RTL

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 13 🅰 |
| **Parallélisable avec** | BACKOFFICE.3 (Wave 13 🅱), BACKOFFICE.4 (Wave 13 🅲) |
| **Dépendances** | 🔵 BACKOFFICE.1, 🟡 AUTH.2 |
| **Effort** | 1.5-2 jours |
| **Design intégré** | [DESIGN] Layout sidebar 240px/64px + topbar 56px, responsive, RTL |
| **Fichiers créés** | `frontend/src/app/(auth)/login/page.tsx`, `frontend/src/app/(dashboard)/layout.tsx`, `frontend/src/components/layout/sidebar.tsx`, `frontend/src/components/layout/topbar.tsx`, `frontend/src/lib/api-client.ts`, `frontend/src/lib/auth.ts`, `frontend/src/types/auth.ts`, `frontend/src/middleware.ts` |

**Résumé :** (1) Page login : formulaire email/mdp (React Hook Form + Zod), logo tenant, palette terracotta, gestion erreurs (mdp invalide, compte verrouillé). (2) Layout dashboard : sidebar dark brown (240px dépliée / 64px repliée, navigation : Dashboard, Conversations, Base de connaissances, Contacts, Campagnes, Analytics, Paramètres, icônes Lucide 20px, item actif avec bordure gauche terracotta, collapse persisté), topbar 56px (breadcrumb, recherche Cmd+K, sélecteur langue FR/AR/EN, notifications, avatar). (3) API client typé (`lib/api-client.ts`) : fetch wrapper avec JWT auto-refresh, gestion erreurs, baseURL configurable. (4) Middleware Next.js : redirection vers login si pas de JWT. (5) RTL complet : sidebar bascule à droite, logical properties, icônes mirrorées. (6) Responsive : sidebar Sheet overlay sur mobile <768px, repliée sur tablette.

**Smoke test :** `npm run dev` → page login → login → layout dashboard avec sidebar + topbar.

---

### BACKOFFICE.3 — Dashboard principal (KPIs, graphiques)

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 13 🅱 |
| **Parallélisable avec** | BACKOFFICE.2 (Wave 13 🅰), BACKOFFICE.4 (Wave 13 🅲) |
| **Dépendances** | 🔵 BACKOFFICE.1 |
| **Effort** | 1-1.5 jours |
| **Design intégré** | [DESIGN] KPI cards, Recharts (terracotta/sable/olive), sparklines |
| **Fichiers créés** | `frontend/src/app/(dashboard)/page.tsx`, `frontend/src/components/dashboard/kpi-card.tsx`, `frontend/src/components/dashboard/conversations-chart.tsx`, `frontend/src/components/dashboard/top-questions.tsx`, `frontend/src/components/dashboard/language-donut.tsx`, `frontend/src/components/dashboard/recent-escalations.tsx` |

**Résumé :** Page dashboard avec : Row 1 : 4 KPI Cards (Conversations actives / Messages aujourd'hui / Taux résolution / Temps réponse moyen — chacun avec sparkline 7j, tendance ▲▼, icône Lucide dans cercle terracotta). Row 2 : graphique évolution conversations (Recharts LineChart 30j, palette terracotta/sable/olive) + Top 5 questions fréquentes. Row 3 : répartition par langue (Recharts Donut 3 segments FR/AR/EN) + dernières escalades en attente (mini-table). Row 4 : questions non couvertes récentes (file d'apprentissage). Sélecteur de période (7j/30j/90j/custom). TanStack Query pour le data fetching. Données mockées en attendant les API. Responsive : grille 4→2→1 colonnes.

**Smoke test :** `npm run dev` → dashboard avec KPIs, graphiques, données mockées.

---

### BACKOFFICE.4 — Supervision conversations (master-detail)

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 13 🅲 |
| **Parallélisable avec** | BACKOFFICE.2 (Wave 13 🅰), BACKOFFICE.3 (Wave 13 🅱) |
| **Dépendances** | 🔵 BACKOFFICE.1 |
| **Effort** | 1.5-2 jours |
| **Design intégré** | [DESIGN] Master-detail layout, bulles style WhatsApp, badges statut |
| **Fichiers créés** | `frontend/src/app/(dashboard)/conversations/page.tsx`, `frontend/src/components/conversations/conversation-list.tsx`, `frontend/src/components/conversations/conversation-detail.tsx`, `frontend/src/components/conversations/message-bubble.tsx`, `frontend/src/components/conversations/context-panel.tsx` |

**Résumé :** Interface master-detail : (1) Liste conversations (350px) : search + filtres (statut, agent_type, langue, date), card par conversation (avatar initiales, nom contact, dernier message tronqué, badge statut, timestamp relatif), badge rouge clignotant pour escalades. (2) Détail conversation : header (contact + statut + langue), messages scroll avec bulles style WhatsApp (droite = utilisateur en primary-bg, gauche = bot en bg-card, système = centré muted), boutons feedback inline (👍/👎). (3) Panel contextuel (droite) : infos contact, tags, historique, chunks utilisés. Données mockées. Responsive : sur mobile la liste remplace le détail (navigation push).

**Smoke test :** `npm run dev` → page conversations → cliquer sur une conversation → voir les messages.

---

### BACKOFFICE.5 — Gestion base de connaissances

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 14 🅰 |
| **Parallélisable avec** | BACKOFFICE.6 (Wave 14 🅱), BACKOFFICE.7 (Wave 14 🅲) |
| **Dépendances** | 🔵 BACKOFFICE.2, 🟡 RAG.5 |
| **Effort** | 1.5-2 jours |
| **Design intégré** | [DESIGN] Tabs, upload drag&drop, progress bar terracotta, apprentissage supervisé cards |
| **Fichiers créés** | `frontend/src/app/(dashboard)/knowledge-base/page.tsx`, `frontend/src/components/kb/document-table.tsx`, `frontend/src/components/kb/upload-modal.tsx`, `frontend/src/components/kb/chunk-viewer.tsx`, `frontend/src/components/kb/unanswered-queue.tsx` |

**Résumé :** Page avec tabs : [Documents] [Catégories] [Questions non couvertes]. (1) Tab Documents : TanStack Table (titre, catégorie, chunks, statut badge, date, actions dropdown), filtres + search, bouton "+ Ajouter un document" → modal drag&drop (upload vers API, progress bar terracotta, sélection catégorie, preview parsing). (2) Viewer de chunks : panneau latéral avec texte découpé, métadonnées surlignées, bouton éditer. (3) Tab Questions non couvertes : cards avec question + réponse IA proposée, boutons Valider (vert) / Rejeter (rouge) / Éditer (terracotta), appels API pour valider/rejeter/éditer → réinjection. Connecté aux API RAG.5.

**Smoke test :** `npm run dev` → page KB → upload document → voir progression → voir chunks → valider une question.

---

### BACKOFFICE.6 — Gestion contacts (CRM léger)

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 14 🅱 |
| **Parallélisable avec** | BACKOFFICE.5 (Wave 14 🅰), BACKOFFICE.7 (Wave 14 🅲) |
| **Dépendances** | 🔵 BACKOFFICE.2, 🟡 CONTACTS.2 |
| **Effort** | 1-1.5 jours |
| **Design intégré** | [DESIGN] TanStack Table, badges tags, import Excel |
| **Fichiers créés** | `frontend/src/app/(dashboard)/contacts/page.tsx`, `frontend/src/components/contacts/contact-table.tsx`, `frontend/src/components/contacts/contact-detail.tsx`, `frontend/src/components/contacts/import-modal.tsx` |

**Résumé :** (1) Table contacts TanStack Table (nom, téléphone, langue, CIN, opt-in badge, tags badges colorés, dernière interaction, actions), search full-text, filtres (langue, opt-in, tags), pagination 10/20/50. (2) Détail contact (panneau latéral ou page) : infos, historique conversations, dossiers liés, tags éditable. (3) Import Excel : modal upload + mapping colonnes + preview + confirmation + rapport d'import (importés/doublons/erreurs). (4) Export Excel filtré. Connecté aux API CONTACTS.2.

**Smoke test :** `npm run dev` → page contacts → rechercher → détail → importer Excel.

---

### BACKOFFICE.7 — Gestion tenants super-admin

| Propriété | Valeur |
|-----------|--------|
| **Wave** | 14 🅲 |
| **Parallélisable avec** | BACKOFFICE.5 (Wave 14 🅰), BACKOFFICE.6 (Wave 14 🅱) |
| **Dépendances** | 🔵 BACKOFFICE.2, 🟡 TENANT.4 |
| **Effort** | 1 jour |
| **Design intégré** | [DESIGN] Cards tenant, formulaire provisionnement, badges statut |
| **Fichiers créés** | `frontend/src/app/(dashboard)/admin/tenants/page.tsx`, `frontend/src/components/admin/tenant-card.tsx`, `frontend/src/components/admin/tenant-form.tsx`, `frontend/src/components/admin/provisioning-progress.tsx` |

**Résumé :** Page accessible uniquement au rôle `super_admin` : (1) Grille de cards tenant (logo, nom, région, statut badge [active/inactive/provisioning], stats: nb conversations, nb contacts, quota messages). (2) Bouton "+ Nouveau CRI" → formulaire multi-étapes (infos générales → config WhatsApp → première alimentation KB → création admins). (3) Progress de provisionnement (étapes 1-7 avec indicateur de progression). (4) Détail tenant : config, quotas, statistiques, boutons activer/désactiver. Connecté aux API TENANT.4.

**Smoke test :** `npm run dev` → login super_admin → page tenants → voir les tenants → créer un nouveau.

---

## 📅 PLANNING OPTIMISÉ AVEC PARALLÉLISATION (2-3 agents)

```
SEMAINE 1 : Wave 0-1-2 (fondation)
  Agent 1 : INFRA.1 → INFRA.2 → INFRA.3 → TENANT.1
  Agent 2 : — (attend la fondation)
  Fin S1  : TENANT.1 terminé, lancement Wave 2

SEMAINE 2 : Wave 2-3-4 (core + services)
  Agent 1 : TENANT.2 → TENANT.3 → TENANT.4
  Agent 2 : AUTH.1 → AUTH.2 → AUTH.3
  Agent 3 : — (préparer BACKOFFICE.1 dès que possible)
  Fin S2  : Middleware + Auth + Provisioning prêts

SEMAINE 3 : Wave 4-5 (intégrations)
  Agent 1 : WHATSAPP.1 → WHATSAPP.2
  Agent 2 : RAG.1 → RAG.2
  Agent 3 : CONTACTS.1 + FEEDBACK.1 + INCITATIONS.1
  Fin S3  : Tous les services de base existent

SEMAINE 4 : Wave 6-7 (pipeline IA)
  Agent 1 : RAG.3 → RAG.4
  Agent 2 : WHATSAPP.3 → WHATSAPP.4
  Agent 3 : LANG.1 + INCITATIONS.2
  Fin S4  : Pipeline RAG + WhatsApp + Incitations fonctionnels

SEMAINE 5 : Wave 8-9 (orchestration + APIs)
  Agent 1 : ORCHESTRATOR.1 → ORCHESTRATOR.2
  Agent 2 : RAG.5 + CONTACTS.2 + FEEDBACK.2
  Agent 3 : BACKOFFICE.1 (début front-end)
  Fin S5  : Backend complet, front-end démarré

SEMAINE 6 : Wave 10-11-12 (tests backend + front-end)
  Agent 1 : TENANT.5 + AUTH.4 + ORCHESTRATOR.3
  Agent 2 : WHATSAPP.5 + RAG.6 + INCITATIONS.3
  Agent 3 : BACKOFFICE.2 + BACKOFFICE.3 + BACKOFFICE.4
  Fin S6  : Backend testé, front-end layout + dashboard + conversations

SEMAINE 7 : Wave 13-14 (front-end modules)
  Agent 1 : BACKOFFICE.5 (KB)
  Agent 2 : BACKOFFICE.6 (contacts)
  Agent 3 : BACKOFFICE.7 (tenants super-admin)
  Fin S7  : Front-end complet

SEMAINE 8 : Wave 15 + Intégration finale
  Agent 1 : LANG.2 (tests trilinguisme)
  Agent 2 : Tests d'intégration front-back
  Agent 3 : Smoke tests globaux + documentation
  Fin S8  : Phase 1 prête pour recette
```

---

## 🚦 CHECKLIST DE VALIDATION PHASE 1

À la fin de la Phase 1, les éléments suivants doivent être vérifiés :

- [ ] Docker Compose up → tous les services healthy
- [ ] Provisionnement d'un tenant → schéma PG + collection Qdrant + bucket MinIO créés
- [ ] Isolation multi-tenant → tenant A ne voit pas les données de tenant B
- [ ] Webhook WhatsApp → message reçu → réponse envoyée
- [ ] FAQ RAG → question → chunks pertinents → réponse Gemini → réponse WhatsApp
- [ ] Incitations → parcours interactif 4 niveaux → fiches d'incitation
- [ ] Trilinguisme → question FR/AR/EN → réponse dans la même langue
- [ ] Guardrails → injection prompt refusée, PII masqué, hors-périmètre refusé
- [ ] Feedback → 👍/👎 → stats CSAT → question non couverte si 👎
- [ ] Back-office → login → dashboard → conversations → KB → contacts → tenants
- [ ] Rate limiting → 101e requête → 429
- [ ] HMAC webhook → signature invalide → 403
- [ ] JWT → token expiré → 401
- [ ] RBAC → viewer accède à /conversations mais pas /tenants
- [ ] Métriques Prometheus → latence, tokens, taux erreur exposés
- [ ] Traces LLM → prompt + réponse + tokens stockés dans PG
