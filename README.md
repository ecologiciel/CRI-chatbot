# Plateforme CRI Chatbot — Multi-Tenant RAG

> Plateforme SaaS de chatbots conversationnels intelligents pour les Centres Regionaux d'Investissement du Maroc.
> Appel d'Offres N° 02/2026/CRI RSK — Client initial : CRI Rabat-Sale-Kenitra

## Presentation

Chatbot WhatsApp propulse par l'IA (RAG + Gemini 2.5 Flash) pour repondre aux questions des investisseurs sur les procedures, incitations et services des CRI. Chaque CRI regional est un tenant isole avec sa propre base de connaissances, configuration WhatsApp et donnees metier. Le provisionnement d'un nouveau CRI se fait via le back-office sans redeploiement.

**Phase actuelle :** Phase 1 — Socle + Agent Public FAQ/Incitations

## Fonctionnalites Phase 1

- Agent conversationnel WhatsApp (FAQ + Incitations interactives)
- Pipeline RAG multilingue (francais, arabe, anglais)
- Base de connaissances avec ingestion de documents (PDF, DOCX, TXT, MD, CSV)
- Guardrails : anti-injection prompt, masquage PII, anonymisation LLM
- Back-office d'administration (gestion KB, contacts, conversations, feedback)
- Architecture multi-tenant isolee (schema PG, collection Qdrant, prefixe Redis, bucket MinIO)

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| Backend | Python 3.12+ / FastAPI (async) |
| Frontend | Next.js 15 / TailwindCSS / shadcn/ui |
| LLM | Google Gemini 2.5 Flash |
| Base vectorielle | Qdrant |
| Base relationnelle | PostgreSQL 16 |
| Cache | Redis 7 |
| Stockage objet | MinIO (S3-compatible) |
| Orchestration IA | LangGraph (LangChain) |
| Reverse Proxy | Traefik v3 (TLS Let's Encrypt) |
| Conteneurisation | Docker + Docker Compose |

## Demarrage rapide

### Pre-requis

- Docker Desktop (ou Docker Engine 24+ avec Compose v2)
- Node.js 20+ (si developpement frontend hors Docker)
- Python 3.12+ (si developpement backend hors Docker)

### Lancement

```bash
# 1. Cloner le depot
git clone <url-du-depot> cri-chatbot-platform
cd cri-chatbot-platform

# 2. Configurer l'environnement
cp .env.example .env
# Editer .env — generer les mots de passe :
# openssl rand -base64 32 (pour POSTGRES_PASSWORD, REDIS_PASSWORD, MINIO_ROOT_PASSWORD)
# openssl rand -base64 64 (pour JWT_SECRET_KEY)
# Renseigner GEMINI_API_KEY

# 3. Lancer tous les services
docker compose up -d

# 4. Appliquer les migrations
docker compose exec backend alembic upgrade head

# 5. Acceder au back-office
# http://localhost:3000
```

### Acces aux services

| Service | URL |
|---------|-----|
| Back-office | http://localhost:3000 |
| API (Swagger) | http://localhost:8000/docs |
| API (ReDoc) | http://localhost:8000/redoc |
| Grafana | http://localhost:3001 |
| Traefik Dashboard | http://localhost:8080 |
| MinIO Console | http://localhost:9001 |

## Architecture

```
         Utilisateurs (WhatsApp / Admin)
                      |
              Traefik (TLS, 80/443)
              /                 \
    Backend FastAPI          Frontend Next.js
    (API + Orchestrateur)    (Back-Office)
     /    |     |     \
  PostgreSQL Qdrant Redis MinIO
  (schemas)  (vect) (cache)(fichiers)
```

Voir [Architecture technique](docs/architecture-technique.md) pour le detail complet.

## Structure du projet

```
cri-chatbot-platform/
├── backend/              # FastAPI — API REST + services IA + orchestrateur
├── frontend/             # Next.js 15 — Back-office d'administration
├── docker/               # Traefik, Prometheus configurations
├── scripts/              # Scripts d'initialisation
├── docs/                 # Documentation technique
├── docker-compose.yml    # Services Docker (developpement)
├── docker-compose.prod.yml  # Surcharges production
├── .env.example          # Variables d'environnement (template)
└── CLAUDE.md             # Reference technique du projet
```

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture technique](docs/architecture-technique.md) | Stack, multi-tenant, RAG, LangGraph, securite |
| [Reference API](docs/api-reference.md) | 30 endpoints REST, schemas, authentification |
| [Guide d'administration](docs/guide-administration.md) | Utilisation du back-office (pour admins CRI) |
| [Guide de deploiement](docs/guide-deploiement.md) | Installation, production Nindohost, monitoring |

## Services Docker

| Service | Port (dev) | Role |
|---------|-----------|------|
| `postgres` | 5432 | Base relationnelle (schema par tenant) |
| `qdrant` | 6333/6334 | Base vectorielle (collection par tenant) |
| `redis` | 6379 | Cache, sessions, rate limiting |
| `minio` | 9000/9001 | Stockage fichiers S3-compatible |
| `traefik` | 80/443/8080 | Reverse proxy TLS |
| `prometheus` | 9090 | Collecte metriques |
| `grafana` | 3001 | Dashboards monitoring |
| `backend` | 8000 | API FastAPI |
| `frontend` | 3000 | Back-office Next.js |

## Developpement

### Commandes utiles

```bash
# Tests backend
docker compose exec backend pytest -x -q

# Logs temps reel
docker compose logs -f backend

# Frontend en mode dev (hors Docker)
cd frontend && npm run dev

# Verifier la sante des services
curl http://localhost:8000/api/v1/health
```

### Conventions

- **Commits** : conventionnels (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`)
- **Branches** : `main` (prod), `develop` (staging), `feature/*`, `fix/*`
- **Backend** : Python 3.12 async, Pydantic v2, structlog, pytest
- **Frontend** : TypeScript strict, App Router, shadcn/ui, TanStack Query
- **Code** : anglais — **Documentation** : francais

## Tests

- **324 tests** dans 59 fichiers
- Categories : isolation multi-tenant, securite, API endpoints, services metier, E2E

```bash
docker compose exec backend pytest -x -q
```

## Licence

Proprietary — CRI Rabat-Sale-Kenitra / Developpe par [Prestataire]
