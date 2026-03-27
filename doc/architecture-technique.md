# Architecture Technique — Plateforme CRI Chatbot

> Document de reference pour les developpeurs et auditeurs techniques.
> Appel d'Offres N° 02/2026/CRI RSK — Phase 1

---

## 1. Vue d'ensemble

La plateforme CRI Chatbot est un systeme SaaS multi-tenant de chatbots conversationnels intelligents (RAG) pour les Centres Regionaux d'Investissement du Maroc. Chaque CRI regional constitue un tenant isole avec sa propre base de connaissances, configuration WhatsApp, et donnees metier.

### Architecture haut niveau

```
                              ┌─────────────────────┐
                              │     Utilisateurs     │
                              │   WhatsApp / Admin   │
                              └──────────┬──────────┘
                                         │
                              ┌──────────▼──────────┐
                              │    Traefik v3        │
                              │  (Reverse Proxy TLS) │
                              │  Ports 80 / 443      │
                              └───┬─────────────┬───┘
                     ┌────────────▼───┐   ┌─────▼──────────┐
                     │  Backend API   │   │   Frontend      │
                     │  FastAPI :8000 │   │   Next.js :3000 │
                     └───┬──┬──┬──┬──┘   └────────────────┘
          ┌──────────────┘  │  │  └──────────────┐
  ┌───────▼───────┐ ┌──────▼──▼──────┐  ┌───────▼───────┐
  │  PostgreSQL   │ │     Qdrant     │  │     Redis     │
  │  :5432        │ │     :6333      │  │     :6379     │
  │  (Schemas)    │ │  (Collections) │  │   (Prefixes)  │
  └───────────────┘ └───────────────┘  └───────────────┘
          │                                      │
  ┌───────▼───────┐              ┌───────────────▼───┐
  │     MinIO     │              │   Prometheus      │
  │  :9000 (S3)   │              │   :9090           │
  │  (Buckets)    │              │   + Grafana :3001 │
  └───────────────┘              └───────────────────┘
```

### Principes directeurs

- **Isolation multi-tenant** : chaque requete est scopee au tenant courant (invariant de securite)
- **Async partout** : Python asyncio, pas de code synchrone bloquant
- **Anonymisation LLM** : aucune donnee personnelle identifiable (PII) n'est envoyee a Gemini
- **Conformite CNDP** : donnees hebergees exclusivement au Maroc (Nindohost)

---

## 2. Stack technique

| Composant | Technologie | Version |
|-----------|-------------|---------|
| LLM | Google Gemini 2.5 Flash | API cloud |
| Backend | Python / FastAPI | Python 3.12+, Pydantic v2, SQLAlchemy 2.0 async |
| Orchestration IA | LangGraph (LangChain) | Graphe d'etat multi-agents |
| Base vectorielle | Qdrant | Collection par tenant, vecteurs 768 dimensions |
| Base relationnelle | PostgreSQL | 16-alpine (schema par tenant + RLS) |
| Cache | Redis | 7-alpine (sessions, OTP, rate limiting) |
| Stockage objet | MinIO | S3-compatible, bucket par tenant |
| Embeddings | text-embedding-004 (Google) | Multilingual FR/AR/EN, 768 dim |
| Front Back-Office | Next.js 15 + TailwindCSS + shadcn/ui | TypeScript strict, App Router |
| WhatsApp | Meta Cloud API v21.0 | Webhook unifie HMAC-SHA256 |
| Conteneurisation | Docker + Docker Compose v2 | Multi-stage builds, non-root |
| Reverse Proxy | Traefik v3.2 | TLS auto Let's Encrypt |
| Monitoring | Prometheus + Grafana | Metriques infra + IA + RAG |

---

## 3. Structure du monorepo

```
cri-chatbot-platform/
├── backend/                      # FastAPI (Python 3.12+)
│   ├── app/
│   │   ├── api/v1/               # 8 routers (auth, contacts, dashboard, feedback, health, kb, tenant, webhook)
│   │   ├── core/                 # Config, security, middleware, tenant, database, redis, qdrant, minio
│   │   ├── models/               # SQLAlchemy 2.0 models + enums
│   │   ├── schemas/              # Pydantic v2 schemas (request/response)
│   │   ├── services/             # 13 modules metier (rag, whatsapp, orchestrator, guardrails, etc.)
│   │   └── workers/              # Taches ARQ asynchrones
│   ├── alembic/                  # 3 migrations (tenants, phase1_tables, incitations)
│   ├── tests/                    # 59 fichiers, ~324 tests
│   └── Dockerfile                # Multi-stage, non-root user
├── frontend/                     # Next.js 15 (Back-Office)
│   ├── src/
│   │   ├── app/                  # App Router : login, dashboard, conversations, contacts, kb
│   │   ├── components/           # shadcn/ui custom (sidebar, topbar, tables, modals)
│   │   ├── hooks/                # useAuth, useTenant, custom hooks
│   │   ├── lib/                  # API client, auth utils
│   │   └── types/                # Types TypeScript
│   ├── docker/
│   │   └── frontend.Dockerfile   # Multi-stage, non-root user
│   └── package.json
├── docker/                       # Configuration infrastructure
│   ├── traefik/                  # traefik.yml + dynamic.yml (TLS, headers, rate limiting)
│   └── prometheus/               # prometheus.yml (scrape config)
├── scripts/                      # Scripts utilitaires
│   └── init-db.sh                # Extensions pgcrypto, uuid-ossp
├── docker-compose.yml            # Developpement local (9 services)
├── docker-compose.prod.yml       # Surcharges production (ports fermes, limites memoire)
├── .env.example                  # Variables d'environnement documentees
└── CLAUDE.md                     # Reference technique du projet
```

---

## 4. Isolation multi-tenant

### 4.1. Strategies d'isolation par composant

| Composant | Strategie | Exemple |
|-----------|-----------|---------|
| PostgreSQL | Schema par tenant | `tenant_rabat.contacts`, `tenant_tanger.contacts` |
| Qdrant | Collection par tenant | `kb_rabat`, `kb_tanger` |
| Redis | Prefixe par tenant | `rabat:session:xxx`, `tanger:otp:yyy` |
| MinIO | Bucket par tenant | `cri-rabat/`, `cri-tanger/` |
| WhatsApp | Config par tenant | Chaque tenant = son propre `phone_number_id`, `access_token` |

### 4.2. TenantContext

Le `TenantContext` est un dataclass immutable (`frozen=True`) qui expose les accesseurs scopes :

```python
@dataclass(frozen=True, slots=True)
class TenantContext:
    id: uuid.UUID
    slug: str
    name: str
    status: str
    whatsapp_config: dict | None

    @property
    def db_schema(self) -> str:       # "tenant_{slug}"
    @property
    def qdrant_collection(self) -> str:  # "kb_{slug}"
    @property
    def redis_prefix(self) -> str:    # "{slug}"
    @property
    def minio_bucket(self) -> str:    # "cri-{slug}"
```

La methode `db_session()` fournit une session PostgreSQL scopee au schema du tenant :

```python
async with tenant.db_session() as session:
    # SET search_path TO tenant_{slug}, public
    await session.execute(select(Contact).where(...))
```

### 4.3. TenantResolver

Trois strategies de resolution selon la source de la requete :

| Source | Methode | Cache Redis |
|--------|---------|-------------|
| Header `X-Tenant-ID` | `from_tenant_id_header()` | TTL 5 min |
| WhatsApp `phone_number_id` | `from_phone_number_id()` | TTL 1 heure |
| Slug interne | `from_slug()` | TTL 5 min |

Le slug est valide par regex `^[a-z0-9][a-z0-9_]*$` pour prevenir l'injection SQL dans `SET search_path`.

### 4.4. TenantMiddleware

Le middleware HTTP intercepte chaque requete et injecte le `TenantContext` dans `request.state.tenant`.

**Chemins exclus** (pas de resolution tenant) :

| Type | Chemins |
|------|---------|
| Exactes | `/health`, `/api/v1/health`, `/docs`, `/openapi.json`, `/redoc`, `/favicon.ico`, `/metrics` |
| Prefixes | `/api/v1/webhook/` (tenant resolu via payload), `/api/v1/auth/` (table publique), `/api/v1/tenants` (gestion) |

**Comportement en cas d'erreur :**
- Header `X-Tenant-ID` manquant → HTTP 400
- Tenant introuvable → HTTP 404
- Tenant inactif → HTTP 403
- Erreur interne → HTTP 500

---

## 5. Architecture conversationnelle (LangGraph)

### 5.1. Graphe d'orchestration

```
                          ┌─────────────────────┐
                          │   intent_detector    │
                          │ (Langue + Guardrails │
                          │  + Classification)   │
                          └──────────┬──────────┘
                                     │ Router.route()
                 ┌───────────────────┼───────────────────┐
                 │                   │                   │
         ┌───────▼───────┐  ┌───────▼───────┐  ┌───────▼───────────┐
         │   faq_agent   │  │  incentives   │  │  greeting_response│
         │   (RAG)       │  │    _agent     │  │  out_of_scope     │
         └───────┬───────┘  └───────┬───────┘  │  blocked_response │
                 │                   │          │  tracking*        │
                 └─────────┬─────────┘          │  escalation*     │
                           │                    │  internal*       │
                 ┌─────────▼─────────┐          └────────┬────────┘
                 │ response_validator│                    │
                 └─────────┬─────────┘                   │
                 ┌─────────▼─────────┐                   │
                 │ feedback_collector │                   │
                 └─────────┬─────────┘                   │
                           └─────────────┬───────────────┘
                                         ▼
                                        END

* = placeholders Phase 2/3
```

### 5.2. ConversationState

Le state partage entre tous les noeuds LangGraph :

```python
ConversationState = TypedDict:
    tenant_slug: str              # Identifiant du tenant
    tenant_context: dict          # TenantContext serialise
    phone: str                    # Telephone E.164 de l'utilisateur
    language: str                 # "fr", "ar", "en"
    intent: str                   # Intention detectee
    messages: list[dict]          # Historique conversation
    query: str                    # Message utilisateur
    retrieved_chunks: list[dict]  # Chunks RAG recuperes
    response: str                 # Reponse generee
    chunk_ids: list[str]          # IDs des chunks utilises
    confidence: float             # Score de confiance RAG
    is_safe: bool                 # Resultat guardrails input
    guard_message: str | None     # Message de blocage si unsafe
    incentive_state: dict         # Navigation arborescence incitations
    error: str | None             # Erreur eventuelle
```

### 5.3. Noeuds Phase 1

| Noeud | Role | Entree | Sortie |
|-------|------|--------|--------|
| **IntentDetector** | Detection langue + input guardrails + classification intention Gemini (~50 tokens) | query | language, intent, is_safe |
| **Router** | Aiguillage conditionnel selon intent | intent, is_safe | Nom du noeud suivant |
| **FAQAgent** | Pipeline RAG complet (retrieval Qdrant + generation Gemini) | query, language | response, chunk_ids, confidence |
| **IncentivesAgent** | Navigation arborescence interactive (boutons/listes WhatsApp) | query, incentive_state | response, incentive_state |
| **ResponseValidator** | Verification qualite, flagging questions non couvertes | response, confidence | response validee |
| **FeedbackCollector** | Ajout boutons feedback (👍/👎/❓) | response | response avec boutons |
| **GreetingNode** | Reponse de bienvenue multilingue | language | response |
| **OutOfScopeNode** | Reponse hors-perimetre institutionnelle | language | response |
| **BlockedResponseNode** | Reponse blocage (input guardrails) | guard_message | response |

### 5.4. Intentions reconnues

`faq`, `incitations`, `greeting` (salutation), `out_of_scope` (hors-perimetre), `blocked` (guardrails), `tracking` (suivi dossier, Phase 3), `escalation` (escalade, Phase 2), `internal` (agent interne, Phase 2).

---

## 6. Pipeline RAG

### 6.1. Ingestion (chemin d'ecriture)

```
Document (PDF/DOCX/TXT/MD/CSV)
  → Upload MinIO (bucket tenant)
  → Extraction texte (pdfplumber, python-docx)
  → Chunking recursif (512-1024 tokens, chevauchement 128)
  → Enrichissement metadonnees via Gemini (batch de 5 chunks)
      ├─ related_laws, applicable_sectors, legal_forms, regions
  → Embedding (text-embedding-004, 768 dimensions)
  → Upsert dans collection Qdrant du tenant (kb_{slug})
  → Sauvegarde KBDocument + KBChunk en base
  → Mise a jour statut : pending → indexing → indexed (ou error)
```

**Contraintes :**
- Formats acceptes : `.pdf`, `.docx`, `.txt`, `.md`, `.csv`
- Taille maximale : 10 Mo (configurable via `KB_MAX_FILE_SIZE_MB`)
- Hash SHA-256 du contenu pour deduplication
- Traitement asynchrone via worker ARQ

**Metriques Prometheus :** `cri_ingestion_documents_total`, `cri_ingestion_chunks_total`, `cri_ingestion_latency_seconds`

### 6.2. Retrieval (chemin de lecture)

```
Question utilisateur
  → Detection langue (FR/AR/EN)
  → Embedding de la question (meme modele)
  → Recherche vectorielle Qdrant (collection kb_{slug})
      ├─ top_k = 5 (configurable)
      ├─ Seuil de confiance = 0.7
      ├─ Filtrage optionnel metadonnees (sectors, legal_forms, regions)
  → Score de confiance (moyenne top-3 similarites)
  → Retour RetrievalResult avec flag is_confident
```

### 6.3. Generation

```
Prompt = Instructions systeme (FR)
       + Chunks anonymises (PII masques)
       + Historique conversation (3-5 derniers echanges)
       + Question utilisateur

  → Gemini 2.5 Flash → Reponse dans la langue detectee
  → Post-traitement : ResponseValidator (guardrails output)
  → Envoi WhatsApp (texte + boutons feedback 👍/👎/❓)
  → Stockage chunk_ids dans metadonnees message
```

**Metriques Prometheus :** `cri_generation_requests_total`, `cri_generation_latency_seconds`, `cri_generation_confidence`

---

## 7. Guardrails

### 7.1. Input guardrails (IntentDetector)

Trois couches de verification (du moins au plus couteux) :

1. **Verification longueur** : MAX_INPUT_LENGTH = 2000 caracteres
2. **Patterns regex** : injection prompt, role-play, instruction override, DAN/jailbreak
3. **Classification Gemini** : sujet off-topic, sujet sensible (~20 tokens)

**Resultat :**
```python
InputGuardResult:
    is_safe: bool       # True si le message est autorise
    action: str         # "allow", "block", "warn"
    reason: str         # Raison lisible
    category: str       # "safe", "injection", "off_topic", "too_long"
```

### 7.2. Output guardrails (ResponseValidator)

- **Masquage PII pre-LLM** : anonymisation CIN, telephone, montants AVANT envoi a Gemini
- **Masquage PII post-LLM** : patterns regex marocains
  - CIN : `[A-Z]{1,2}\d{5,6}`
  - Telephone : `(?:\+212|0)[567]...`
  - Email : regex standard
  - Montants : `\d{1,3}[\s.,]\d{3}*\s*(MAD|DH|dirhams)`
- **Score de confiance** : si < 0.7 → disclaimer ajoute a la reponse
- **Absence de reponse** : message institutionnel predefini

---

## 8. Modele de donnees

### 8.1. Schema public (partage)

| Table | Colonnes principales | Notes |
|-------|---------------------|-------|
| `tenants` | id (UUID), name, slug (unique), region, logo_url, whatsapp_config (JSONB), status, max_contacts, max_messages_per_year | Properties derivees : db_schema, qdrant_collection, redis_prefix, minio_bucket |
| `admins` | id (UUID), email (unique), password_hash, full_name, role (AdminRole), tenant_id (FK nullable), is_active, last_login | tenant_id = NULL pour super_admin |

### 8.2. Schema par tenant (`tenant_{slug}`)

| Table | Colonnes principales | Relations |
|-------|---------------------|-----------|
| `contacts` | id, phone (unique E.164), name, language, cin, opt_in_status, tags (JSONB), source | Index : phone, cin, tags (GIN) |
| `conversations` | id, contact_id (FK), agent_type, status, started_at, ended_at | Timeout auto 30 min |
| `messages` | id, conversation_id (FK), direction, type, content, media_url, chunk_ids (JSONB), whatsapp_message_id, timestamp | Types : text, image, audio, document, interactive, system |
| `kb_documents` | id, title, source_url, category, language, content_hash (SHA-256), file_path, chunk_count, status | Statuts : pending, indexing, indexed, error |
| `kb_chunks` | id, document_id (FK), content, chunk_index, token_count, qdrant_point_id, metadata (JSONB) | Chaque chunk = 1 point Qdrant |
| `feedback` | id, message_id (FK), rating, reason, comment, chunk_ids (JSONB) | Ratings : positive, negative, question |
| `unanswered_questions` | id, question, proposed_answer, status, review_note, reviewed_by | Statuts : pending, approved, modified, rejected, injected |
| `incentive_categories` | id, parent_id (FK self), name_fr, name_ar, name_en, description_fr/ar/en, icon, order_index, is_leaf, is_active | Arborescence hierarchique |
| `incentive_items` | id, category_id (FK), title_fr/ar/en, content_fr/ar/en, eligibility_criteria (JSONB), documents_required (JSONB) | Feuilles de l'arborescence |

### 8.3. Enumerations

| Enum | Valeurs |
|------|---------|
| `TenantStatus` | active, inactive, provisioning |
| `AdminRole` | super_admin, admin_tenant, supervisor, viewer |
| `ConversationStatus` | active, ended, escalated, human_handled |
| `MessageDirection` | inbound, outbound |
| `MessageType` | text, image, audio, document, interactive, system |
| `OptInStatus` | opted_in, opted_out, pending |
| `ContactSource` | whatsapp, import_csv, manual |
| `Language` | fr, ar, en |
| `KBDocumentStatus` | pending, indexing, indexed, error |
| `FeedbackRating` | positive, negative, question |
| `UnansweredStatus` | pending, approved, modified, rejected, injected |
| `AgentType` | public, internal |
| `EscalationTrigger` | explicit_request, rag_failure, sensitive_topic, negative_feedback, otp_timeout, manual |

### 8.4. Migrations Alembic

| Migration | Contenu |
|-----------|---------|
| `0001_create_tenants_table` | Schema public : tenants, admins, tous les types ENUM |
| `0002_create_phase1_tables` | Schema tenant : contacts, conversations, messages, kb_documents, kb_chunks, feedback, unanswered_questions |
| `0003_create_incitation_tables` | Schema tenant : incentive_categories, incentive_items |

---

## 9. Securite

### 9.1. Authentification back-office

- **Algorithme** : JWT HS256 avec cle secrete 512 bits
- **Access token** : TTL 30 minutes
- **Refresh token** : TTL 7 jours, rotation a usage unique
- **Hashage mdp** : bcrypt cost factor 12 (passlib)
- **Politique mdp** : 12+ caracteres, 1 majuscule, 1 chiffre, 1 special
- **Verrouillage** : 5 echecs / 15 min → blocage 30 min

### 9.2. RBAC (Role-Based Access Control)

| Role | Tenants | KB | Contacts | Conversations | Feedback | Dashboard |
|------|---------|----|---------|----|----------|-----------|
| `super_admin` | CRUD tous | CRUD | CRUD | Lecture | CRUD | Lecture |
| `admin_tenant` | Lecture (propre) | CRUD | CRUD | Lecture | CRUD | Lecture |
| `supervisor` | — | Upload/Lecture | Lecture/Modif | Lecture | Lecture | Lecture |
| `viewer` | — | Lecture | — | Lecture | Lecture | Lecture |

### 9.3. Webhook WhatsApp

- Signature HMAC-SHA256 via header `X-Hub-Signature-256` avec `app_secret`
- Validation Pydantic v2 strict du payload
- Rejet HTTP 403 si signature invalide ou absente
- Deduplication via Redis (cle `{slug}:whatsapp:dedup:{wamid}`, TTL 24h)

### 9.4. Rate limiting (Redis TTL)

| Niveau | Limite | Cle Redis | Action |
|--------|--------|-----------|--------|
| Traefik global | 100 req/min, burst 50 | Middleware rate-limit | HTTP 429 |
| Tenant webhook | 50 req/min | `{slug}:rl:webhook` | HTTP 429 |
| Utilisateur WhatsApp | 10 msg/min | `{slug}:rl:user:{phone}` | Message "Veuillez patienter" |
| OTP anti-bruteforce | 3 tentatives / 15 min | `auth:login_attempts:{email}` | Blocage 30 min |

### 9.5. Reseaux Docker

| Reseau | Mode | Services | Role |
|--------|------|----------|------|
| `cri-frontend` | bridge | Traefik, Backend, Frontend, Prometheus | Point d'entree public |
| `cri-backend` | bridge (dev) / internal (prod) | PostgreSQL, Qdrant, Redis, MinIO, Prometheus, Grafana, Backend | Donnees (aucun acces externe en prod) |

Le Backend est le seul service present dans les deux reseaux (bridge entre public et prive).

### 9.6. Headers de securite (Traefik)

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

CORS : uniquement `BACKOFFICE_URL` (methodes : GET, POST, PUT, PATCH, DELETE, OPTIONS ; headers : Content-Type, Authorization, X-Tenant-ID).

---

## 10. Monitoring et observabilite

### 10.1. Prometheus

**Configuration scrape** (`docker/prometheus/prometheus.yml`) :

| Job | Cible | Intervalle |
|-----|-------|-----------|
| `prometheus` | localhost:9090 | 15s |
| `traefik` | traefik:8080/metrics | 15s |
| `fastapi` | backend:8000/metrics | 10s |

**Retention** : 30 jours (`--storage.tsdb.retention.time=30d`)

### 10.2. Metriques custom

| Service | Metriques |
|---------|-----------|
| RAG Ingestion | `cri_ingestion_documents_total`, `cri_ingestion_chunks_total`, `cri_ingestion_latency_seconds` |
| RAG Retrieval | `cri_retrieval_requests_total`, `cri_retrieval_latency_seconds`, `cri_retrieval_confidence` |
| RAG Generation | `cri_generation_requests_total`, `cri_generation_latency_seconds`, `cri_generation_confidence` |
| Guardrails | `cri_guardrail_input_checks_total` (par resultat) |
| FastAPI | Instrumentees automatiquement via `prometheus_fastapi_instrumentator` |

### 10.3. Grafana

- Acces dev : http://localhost:3001 (credentials configurables via `GRAFANA_USER`/`GRAFANA_PASSWORD`)
- Datasource : Prometheus `http://prometheus:9090`
- Dashboards recommandes : Infrastructure, API (latence, erreurs), WhatsApp, RAG (confiance, ingestion)

### 10.4. Logging structure

Toutes les couches utilisent **structlog** avec contexte lie :

```python
logger = structlog.get_logger()
log = logger.bind(service="faq_agent", tenant=tenant.slug)
log.info("faq_request_processed", query_length=len(query), confidence=confidence)
```

---

## 11. Infrastructure cible (Nindohost)

### 11.1. Serveurs

| Serveur | Specs | Role |
|---------|-------|------|
| VPS Prod 1 | 8 vCPU, 32 Go RAM, 500 Go SSD NVMe | Backend API, Orchestrateur, Qdrant |
| VPS Prod 2 | 4 vCPU, 16 Go RAM, 200 Go SSD NVMe | PostgreSQL, Redis, MinIO |
| VPS Prod 3 | 4 vCPU, 8 Go RAM, 100 Go SSD NVMe | Frontend, Traefik, Monitoring |
| VPS Pre-Prod | 4 vCPU, 16 Go RAM, 200 Go SSD NVMe | Miroir production |

Acces : SSH/VPN (clarification CPS R7). Pas de GPU (R5). Firewall whitelist IP admin.

### 11.2. Plan de Reprise d'Activite (PRA)

| Composant | Frequence | Methode |
|-----------|-----------|---------|
| PostgreSQL | Quotidien | `pg_dump` incremental |
| Qdrant | Hebdomadaire | Snapshot via API REST |
| MinIO | Hebdomadaire | `mc mirror` vers stockage secondaire |

**Retention** : 30 jours glissants + mensuels 12 mois. **RTO** < 4h, **RPO** < 24h.

---

## 12. Conventions de code

### Python (Backend)

- **Python 3.12+**, async/await partout
- **Pydantic v2** pour tous les schemas (pas de dict bruts)
- **SQLAlchemy 2.0** async sessions
- **structlog** pour le logging (pas de `print()`)
- **pydantic-settings** pour la configuration
- Nommage : `snake_case` fonctions/variables, `PascalCase` classes
- Exceptions : custom heritant de `CRIBaseException`
- Tests : **pytest** + **pytest-asyncio**

### TypeScript (Frontend)

- **TypeScript strict** (pas de `any`)
- **Next.js 15** App Router, Server Components par defaut
- **TailwindCSS** avec design system "Modern Warm" (terracotta & sable)
- **shadcn/ui** pour tous les composants
- **TanStack Query** pour l'etat serveur
- **React Hook Form + Zod** pour les formulaires

### Git

- Branches : `main` (prod), `develop` (staging), `feature/*`, `fix/*`
- Commits conventionnels : `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
- PR obligatoire pour merge dans develop/main
- Code en anglais, documentation utilisateur en francais

---

## Voir aussi

- [Reference API](api-reference.md) — 30 endpoints REST Phase 1
- [Guide de deploiement](guide-deploiement.md) — Installation et production
- [Guide d'administration](guide-administration.md) — Utilisation du back-office
