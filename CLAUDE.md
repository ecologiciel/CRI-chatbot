# CLAUDE.md — Plateforme Multi-Tenant RAG Chatbot CRI

> **Ce fichier est la référence absolue pour Claude Code.** Chaque décision de code doit être vérifiable ici.
> Appel d'Offres N° 02/2026/CRI RSK — Client initial : CRI Rabat-Salé-Kénitra

---

## 1. VISION DU PROJET

Plateforme SaaS multi-tenant de chatbots conversationnels intelligents (RAG) pour les Centres Régionaux d'Investissement (CRI) du Maroc. Chaque CRI régional = un tenant isolé (base de connaissances, base métier, paramètres WhatsApp). Le provisionnement d'un nouveau CRI se fait via back-office super-admin sans redéploiement de code.

**Volumétrie cible par tenant :** ~6 000 dossiers actifs, ~1 000 nouveaux/an, 20 000 contacts, 100 000 messages WhatsApp/an, 10 admins max, 100+ conversations simultanées.

---

## 2. STACK TECHNIQUE (NE PAS DÉVIER)

| Composant | Technologie | Version |
|-----------|-------------|---------|
| LLM | Google Gemini 2.5 Flash | API cloud (⚠️ Gemini 2.0 Flash déprécié, retrait 1er juin 2026) |
| Backend | Python / FastAPI | Python 3.12+, FastAPI async, Pydantic v2 |
| Orchestration IA | LangGraph (LangChain) | Graphe d'état multi-agents |
| Base vectorielle | Qdrant | Collection par tenant |
| Base relationnelle | PostgreSQL | 16 (schéma par tenant + RLS) |
| Cache | Redis | 7 (sessions, OTP, rate limiting) |
| Stockage objet | MinIO | Bucket par tenant |
| Embeddings | text-embedding-004 (Google) ou multilingual-e5-large | Multilingue FR/AR/EN |
| Front Back-Office | Next.js 15 + TailwindCSS + shadcn/ui | TypeScript strict |
| WhatsApp | Meta Cloud API (direct) ou 360dialog | Webhook unifié |
| Conteneurisation | Docker + Docker Compose | Multi-stage builds |
| Reverse Proxy | Traefik v3 | TLS auto Let's Encrypt |
| CI/CD | GitHub Actions | SSH vers Nindohost |
| Monitoring | Prometheus + Grafana | Métriques infra + IA + RAG |
| Hébergement | Nindohost | Datacenter Maroc, ISO 9001:2015 |

---

## 3. STRUCTURE DU MONOREPO

```
cri-chatbot-platform/
├── backend/                  # FastAPI (Python)
│   ├── app/
│   │   ├── core/             # Config, security, multi-tenant middleware
│   │   │   ├── config.py     # pydantic-settings, .env
│   │   │   ├── security.py   # JWT, bcrypt, RBAC
│   │   │   ├── middleware.py  # TenantMiddleware, rate limiting, HMAC
│   │   │   └── tenant.py     # TenantContext, TenantResolver
│   │   ├── api/v1/           # Routes FastAPI
│   │   ├── services/         # Logique métier
│   │   │   ├── rag/          # Pipeline RAG (ingestion, retrieval, generation)
│   │   │   ├── whatsapp/     # Intégration Meta Cloud API
│   │   │   ├── tenant/       # Provisionnement et gestion multi-tenant
│   │   │   ├── dossier/      # Suivi de dossier + OTP
│   │   │   ├── notification/ # Notifications proactives
│   │   │   ├── campaign/     # Publipostage WhatsApp
│   │   │   ├── contact/      # CRM léger, segmentation, opt-in/out
│   │   │   ├── escalation/   # Escalade agent humain (6 scénarios)
│   │   │   ├── feedback/     # Notation et feedback utilisateurs
│   │   │   ├── guardrails/   # Input/Output guardrails, PII masking
│   │   │   └── ai/           # Abstraction Gemini, embeddings, langue
│   │   ├── models/           # SQLAlchemy 2.0 models (async)
│   │   ├── schemas/          # Pydantic v2 schemas
│   │   └── workers/          # Celery/ARQ tasks (ingestion, notifications, sync)
│   ├── alembic/              # Migrations DB
│   ├── tests/
│   └── requirements.txt
├── frontend/                 # Next.js 15 (Back-Office)
│   ├── src/
│   │   ├── app/              # App Router
│   │   ├── components/       # Composants shadcn/ui customisés
│   │   ├── lib/              # API client, auth, utils
│   │   └── types/            # TypeScript types
│   └── package.json
├── docker/                   # Dockerfiles
├── docker-compose.yml        # Dev local
├── docker-compose.prod.yml   # Production Nindohost
├── .github/workflows/        # CI/CD
├── docs/                     # Documentation
├── scripts/                  # Scripts utilitaires
└── CLAUDE.md                 # CE FICHIER
```

---

## 4. ISOLATION MULTI-TENANT (INVARIANT CRITIQUE)

**Chaque ligne de code DOIT respecter l'isolation multi-tenant. C'est un invariant de sécurité.**

### 4.1. Stratégies d'isolation par composant

| Composant | Stratégie | Exemple |
|-----------|-----------|---------|
| PostgreSQL | Schéma par tenant | `tenant_rabat.dossiers`, `tenant_tanger.dossiers` + RLS en filet |
| Qdrant | Collection par tenant | `kb_rabat`, `kb_tanger` — JAMAIS de requête cross-collection |
| Redis | Préfixe par tenant | `rabat:session:xxx`, `tanger:otp:yyy` — TOUJOURS préfixer |
| MinIO | Bucket par tenant | `cri-rabat/`, `cri-tanger/` — politique IAM par bucket |
| WhatsApp | Numéro et config par tenant | Chaque tenant = son propre `phone_number_id`, `access_token`, templates |

### 4.2. Pattern obligatoire dans chaque service

```python
from app.core.tenant import TenantContext, get_current_tenant

async def any_service_function(
    data: SomeSchema,
    tenant: TenantContext = Depends(get_current_tenant)
):
    """Toute fonction métier DOIT recevoir le tenant via Depends."""
    async with tenant.db_session() as session:
        # Opère automatiquement dans le schéma du tenant
        result = await session.execute(
            select(Model).where(Model.id == data.id)
        )
    # Qdrant : toujours la collection du tenant
    qdrant.search(collection_name=f"kb_{tenant.slug}", ...)
    # Redis : toujours le préfixe tenant
    redis.get(f"{tenant.slug}:session:{session_id}")
    # MinIO : toujours le bucket tenant
    minio.get_object(f"cri-{tenant.slug}", file_path)
```

### 4.3. Middleware TenantResolver

Le middleware résout le tenant selon la source :
- **Webhook WhatsApp** : `phone_number_id` du payload → lookup Redis `phone_mapping:{phone_number_id}` → `tenant_id`
- **Back-office API** : header `X-Tenant-ID` + validation JWT du rôle admin
- **Super-admin** : header `X-Tenant-ID` optionnel + rôle `super_admin`

Le `TenantContext` est injecté dans `request.state.tenant` et contient : slug, db_schema, qdrant_collection, redis_prefix, minio_bucket, whatsapp_config.

---

## 5. ARCHITECTURE CONVERSATIONNELLE (LANGGRAPH)

L'orchestration utilise LangGraph avec un graphe d'état par conversation :

```
[IntentDetector] → [Router] → [FAQAgent | IncentivesAgent | TrackingAgent | InternalAgent | EscalationHandler]
                                    ↓
                            [ResponseValidator] → [FeedbackCollector] → Réponse WhatsApp
```

### 5.1. Nœuds du graphe

| Nœud | Rôle | Phase |
|------|------|-------|
| IntentDetector | Classification d'intention via Gemini (FAQ, suivi, incitations, interne, escalade, hors-périmètre) + Input Guardrails | P1 |
| Router | Aiguillage conditionnel selon intention + contexte | P1 |
| FAQAgent | Pipeline RAG complet (retrieval Qdrant + generation Gemini) | P1 |
| IncentivesAgent | Arborescence interactive WhatsApp (boutons/listes) | P1 |
| TrackingAgent | Auth OTP + consultation dossier (sous-graphe : non_auth → otp_sent → authenticated) | P3 |
| InternalAgent | Lecture seule dossiers, dashboards, rapports (whitelist numéros) | P2 |
| EscalationHandler | 6 scénarios d'escalade + transfert avec contexte | P2 |
| ResponseValidator | Output Guardrails : PII masking, ton institutionnel, anti-hallucination | P1 |
| FeedbackCollector | Collecte feedback post-réponse (👍/👎/❓) | P1 |

### 5.2. Guardrails (module `services/guardrails/`)

**Input Guardrails (IntentDetector) :**
- Classification d'intention via Gemini (~50 tokens/classification)
- Détection de patterns regex (injection prompt, role-play, instruction override)
- Sandboxing contexte : balises XML séparant instructions système, chunks RAG, message utilisateur
- Refus gracieux avec message institutionnel prédéfini + audit log

**Output Guardrails (ResponseValidator) :**
- Masquage PII pré-LLM : anonymisation CIN, téléphone, montants AVANT envoi à Gemini
- Masquage PII post-LLM : regex patterns marocains (CIN: `[A-Z]{1,2}\d{5,6}`, tél: `+212/06/07 + 8 chiffres`)
- Score de confiance RAG : si < seuil (défaut 0.7) → disclaimer ou escalade
- Vérification citation : éléments factuels présents dans les chunks récupérés
- Ton institutionnel : scoring registre formel

### 5.3. Sécurité des données en transit vers Gemini

**CRITIQUE :** Aucune donnée personnelle identifiable (CIN, n° dossier réel, montant, nom) n'est envoyée dans les prompts Gemini. Seuls les chunks RAG anonymisés et le texte filtré transitent. Le suivi de dossier opère 100% local (PostgreSQL, pas d'appel LLM pour l'accès aux données).

---

## 6. PIPELINE RAG (`services/rag/`)

### 6.1. Ingestion

1. Crawl automatisé des sites web CRI (détection de mise à jour)
2. Import documents (PDF, Word, Excel) via back-office
3. Chunking : 512-1024 tokens, chevauchement 128 tokens
4. Enrichissement métadonnées (Structured RAG) via Gemini : `related_laws`, `applicable_sectors`, `legal_forms`, régions, chunks prérequis
5. Embeddings multilingues (text-embedding-004 ou multilingual-e5-large)
6. Stockage dans collection Qdrant du tenant

### 6.2. Retrieval

1. Détection langue (FR/AR/EN)
2. Embedding de la question
3. Recherche hybride Qdrant : cosinus + filtrage métadonnées JSON (Structured RAG)
4. Top-K chunks (K configurable, défaut 5)
5. Re-ranking optionnel via Gemini

### 6.3. Generation

1. Prompt = instructions système + chunks anonymisés + historique (3-5 derniers échanges) + question
2. Gemini 2.5 Flash → réponse dans la langue détectée
3. Post-traitement : ResponseValidator (guardrails)
4. Envoi WhatsApp (texte, boutons, listes) + boutons feedback (👍/👎/❓)
5. Stockage chunk_ids dans métadonnées message pour corrélation feedback/RAG

### 6.4. Apprentissage supervisé

- Questions non couvertes (score confiance < seuil) → file de révision
- Propositions IA générées par Gemini
- Validation humaine back-office : approuver / modifier / rejeter
- Réinjection automatique dans Qdrant après validation

---

## 7. MODULES FONCTIONNELS

### 7.1. Suivi de dossier (Phase 3)

- Auth OTP 6 chiffres : `secrets.randbelow()`, hash SHA-256 dans Redis (TTL 5min)
- Anti-bruteforce : max 3 tentatives / 15 min par téléphone
- Anti-replay : OTP invalidé après usage
- Scope : accès uniquement aux dossiers associés au téléphone vérifié (anti-BOLA)
- Import Excel/CSV : openpyxl data_only, validation schéma, sanitisation HTML/SQL injection, max 10MB, worker ARQ isolé

**Intégration SI 3 niveaux :**
- Niveau 1 (Phase 3) : Import Excel/CSV (watched folder MinIO, job ARQ + cron, hash SHA-256, mapping configurable par tenant)
- Niveau 2 (Maintenance) : Connecteur API REST (sync incrémentale 15-30 min, SyncProvider par tenant)
- Niveau 3 (Post-marché) : DB-Link/CDC (FDW PostgreSQL ou Debezium)

### 7.2. Notifications proactives

- Templates WhatsApp prévalidés Meta
- Déclencheurs : changement statut dossier, demande complément, décision finale, rappels délais
- Langue préférée du contact

### 7.3. Agent interne (Phase 2)

- Whitelist numéros de téléphone
- Lecture seule (confirmé R11)
- Consultation dossiers, dashboards simplifiés, rapports/stats à la demande

### 7.4. Escalade agent humain (Phase 2)

6 scénarios : demande explicite, échec RAG répété, sujet sensible, feedback négatif + "parler à un agent", timeout OTP, intervention manuelle back-office.

Flux : conversation.status → "escalated" → table `escalations` → WebSocket notification → prise en charge → réponse via API WhatsApp (même numéro) → clôture → retour mode auto.

### 7.5. Contacts / CRM léger

- Création auto : tout nouveau numéro WhatsApp → fiche contact
- Enrichissement progressif (CIN via suivi, nom, langue, secteur via incitations)
- Import/export Excel, dédoublonnage (clé : téléphone E.164)
- Tags, segments, opt-in/out CNDP, commande "STOP"
- Index PostgreSQL : `phone`, `cin`, `tags` (GIN) pour 20 000+ enregistrements

### 7.6. Campagnes / Publipostage

- Templates Meta, import destinataires Excel, mapping variables
- Planification, gestion débit, quota 100 000 msg/an/tenant
- Stats : envoi, réception, lecture, interaction

### 7.7. Feedback et notation

- Après chaque réponse FAQ : boutons 👍/👎/❓
- 👎 → raison via liste WhatsApp → routage auto vers apprentissage supervisé
- Corrélation chunk_ids pour identifier chunks sous-performants
- Seuil d'alerte CSAT configurable

---

## 8. MODÈLE DE DONNÉES (par tenant)

```sql
-- Schéma public (partagé)
tenants (id, name, slug, region, logo_url, whatsapp_config JSONB, status, created_at)
tenant_keys (id, tenant_id, encrypted_key, algorithm, created_at, rotated_at)
audit_logs (id, tenant_slug, user_id, user_type, action, resource_type, resource_id, ip_address, user_agent, details JSONB, created_at)  -- INSERT ONLY

-- Schéma tenant_{slug}
contacts (id, phone, name, language, cin, opt_in_status, tags JSONB, created_at)
  -- Index: phone (unique), cin, tags (GIN)
conversations (id, contact_id, agent_type, status, started_at, ended_at)
messages (id, conversation_id, direction, type, content, media_url, chunk_ids JSONB, timestamp)
dossiers (id, numero, contact_id, statut, type_projet, dates JSONB, observations, created_at, updated_at)
kb_documents (id, title, source_url, category, language, content_hash, status, created_at)
kb_chunks (id, doc_id, content, qdrant_id, metadata JSONB)
unanswered_questions (id, question, proposed_answer, status, reviewed_by, created_at)
feedback (id, message_id, rating, comment, chunk_ids JSONB, created_at)
escalations (id, conversation_id, trigger_type, priority, assigned_to, context_summary, status, created_at, resolved_at)
campaigns (id, name, template_id, audience JSONB, status, stats JSONB, scheduled_at, created_at)
sync_logs (id, source_type, file_name, rows_imported, rows_errored, status, started_at, completed_at)
sync_configs (id, provider_type, config_json JSONB, mapping_json JSONB, schedule_cron, is_active)
dossier_history (id, dossier_id, field_changed, old_value, new_value, changed_at, sync_log_id)
admins (id, email, password_hash, role, is_active, last_login, created_at)
```

---

## 9. SÉCURITÉ

### 9.1. Authentification back-office

- Email/mot de passe (R12)
- bcrypt cost factor 12+
- JWT TTL 30 min, refresh token rotation (usage unique)
- RBAC whitelist : `super_admin`, `admin_tenant`, `supervisor`, `viewer`
- Politique mdp : 12+ chars, 1 maj, 1 chiffre, 1 spécial, check liste 10 000 mdp courants
- Verrouillage : 5 échecs / 15 min → blocage 30 min + notification email
- Phase 2 : détection changement IP, session unique, alertes connexion simultanée

### 9.2. Webhooks WhatsApp

- Signature HMAC-SHA256 via header `X-Hub-Signature-256` avec `app_secret`
- Validation payload Pydantic v2 strict
- Rejet HTTP 403 si signature invalide/absente

### 9.3. Rate limiting (4 niveaux, Redis TTL)

| Niveau | Limite | Clé Redis | Action |
|--------|--------|-----------|--------|
| Global IP | 100 req/min | `rl:ip:{ip}` | HTTP 429 + Retry-After |
| Tenant webhook | 50 req/min | `{slug}:rl:webhook` | HTTP 429 + alerte admin |
| Utilisateur WhatsApp | 10 msg/min | `{slug}:rl:user:{phone}` | Message "Veuillez patienter" |
| OTP anti-bruteforce | 3 tentatives / 15 min | `{slug}:rl:otp:{phone}` | Blocage temporaire + alerte |

### 9.4. Chiffrement

- **Au repos** : pgcrypto (champs sensibles), SSE-S3 MinIO, Qdrant encryption at-rest
- **En transit** : TLS 1.3 via Traefik (Let's Encrypt), HTTPS natif Gemini/Meta
- **Par tenant (Phase 2)** : KMS logiciel, clé AES-256 par tenant, master key en env var, rotation planifiable

### 9.5. Réseau Docker

- Réseau `frontend` : Traefik + FastAPI (seul point d'entrée 80/443)
- Réseau `backend` : FastAPI + PostgreSQL + Qdrant + Redis + MinIO (aucun service exposé publiquement)
- FastAPI = bridge entre les deux réseaux
- Inter-VPS : TLS ou tunnel SSH

### 9.6. Headers de sécurité (Traefik)

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'
Referrer-Policy: strict-origin-when-cross-origin
CORS: uniquement le domaine du back-office
```

### 9.7. Audit trail (Phase 2)

- Table `audit_logs` INSERT ONLY (pas de UPDATE/DELETE pour le rôle applicatif)
- Colonnes : tenant_slug, user_id, user_type, action, resource_type, resource_id, ip, user_agent, details JSONB, created_at
- Archivage hebdo signé (SHA-256) sur MinIO
- Rétention : 12 mois PostgreSQL, 24 mois MinIO

### 9.8. Gestion des secrets

- Variables d'environnement : clés API Gemini, tokens WhatsApp, credentials DB/Redis/MinIO/Qdrant, master key KMS
- `.env` non versionné (.gitignore), permissions 600
- Rotation : tokens WhatsApp 90j, credentials DB 180j

### 9.9. Conformité CNDP (loi 09-08)

- Données personnelles uniquement sur Nindohost (Maroc)
- Prompts Gemini = anonymisés systématiquement (aucun PII)
- Data use policy Gemini : non-utilisation pour entraînement
- Rétention : conversations 90j, logs 12 mois, dossiers selon durée légale
- Opt-out via "STOP", exclusion auto campagnes/notifications
- Déclaration CNDP avant mise en production

---

## 10. INFRASTRUCTURE NINDOHOST

| Serveur | Specs | Rôle |
|---------|-------|------|
| VPS Prod 1 | 8 vCPU, 32 Go RAM, 500 Go SSD NVMe | Backend API, Orchestrateur, Qdrant |
| VPS Prod 2 | 4 vCPU, 16 Go RAM, 200 Go SSD NVMe | PostgreSQL, Redis, MinIO |
| VPS Prod 3 | 4 vCPU, 8 Go RAM, 100 Go SSD NVMe | Front Back-Office, Traefik, Monitoring |
| VPS Pré-Prod | 4 vCPU, 16 Go RAM, 200 Go SSD NVMe | Miroir production |

Accès : SSH/VPN (R7). Pas de GPU (R5). Firewall whitelist IP admin. Réseau privé inter-VPS.

**PRA :** pg_dump quotidien, Qdrant snapshot hebdo, MinIO réplication. Rétention 30j glissants + 12 mois mensuels. RTO < 4h, RPO < 24h.

---

## 11. BACK-OFFICE — DESIGN SYSTEM "MODERN WARM"

### 11.1. Direction artistique

**Palette terracotta & sable** inspirée du Maroc. Aucun dark mode. Aucun gradient agressif.

### 11.2. Couleurs

```css
:root {
  --primary: 16 55% 53%;        /* Terracotta #C4704B */
  --primary-foreground: 0 0% 100%;
  --secondary: 28 50% 64%;       /* Sable #D4A574 */
  --background: 30 33% 97%;      /* Crème #FAF7F2 */
  --card: 0 0% 100%;
  --foreground: 0 0% 10%;
  --muted: 30 10% 93%;
  --muted-foreground: 20 12% 37%;
  --border: 30 12% 90%;
  --ring: 16 55% 53%;
  --radius: 0.5rem;
  --sidebar-bg: 24 33% 12%;      /* Dark Brown #3D2B1F */
  --sidebar-fg: 30 20% 90%;
}
```

**Sémantiques :** Success #5F8B5F, Warning #C4944B, Error #B5544B, Info #5B7A8B, Olive #7A8B5F

### 11.3. Typographie

| Élément | Font | Weight | Size |
|---------|------|--------|------|
| Display/H1 | Plus Jakarta Sans | 700 | 28-32px |
| H2 | Plus Jakarta Sans | 600 | 22-24px |
| H3 | Plus Jakarta Sans | 600 | 18-20px |
| Body | Inter Variable | 400 | 14-15px |
| Body emphasis | Inter Variable | 500 | 14-15px |
| Small/Caption | Inter Variable | 400 | 12-13px |
| Monospace | JetBrains Mono | 400 | 13px |
| Arabe | Noto Sans Arabic | 400-700 | Même échelle |

**INTERDIT :** Space Grotesk, Outfit, ou toute autre police "créative". TOUJOURS Plus Jakarta Sans + Inter Variable.

### 11.4. Layout

- Sidebar dark brown (240px / 64px collapsed) + contenu fond crème
- Topbar 56px sticky (breadcrumb, search Cmd+K, langue FR/AR/EN, notifications, avatar)
- Radius par défaut : 8px (rounded-lg)
- Ombres : `shadow-card: 0 1px 3px rgba(61,43,31,0.08)`, `shadow-elevated: 0 4px 12px rgba(61,43,31,0.12)`

### 11.5. Composants

- **Framework UI :** shadcn/ui exclusivement (pas de composants custom sauf nécessité absolue)
- **Icônes :** Lucide React, 20px, stroke-width 1.75
- **Charts :** Recharts, palette : terracotta, sable, olive, info (JAMAIS bleu vif, violet, vert néon)
- **Tables :** TanStack Table v8 + shadcn
- **Formulaires :** React Hook Form + Zod
- **État serveur :** TanStack Query (React Query)

### 11.6. RTL natif (arabe)

- `dir="rtl"` sur `<html>` quand langue = arabe
- Logical properties CSS partout (`ms-*`, `me-*`, `text-start`, `text-end`)
- Sidebar bascule à droite
- Icônes directionnelles : `rtl:rotate-180`
- Recharts axe Y à droite
- Toasts : bas-gauche en RTL

### 11.7. Multi-tenant theming

Personnalisation minimale par tenant : logo (SVG/PNG max 200x60), couleur accent (`--tenant-accent`), nom, favicon. La couleur accent ne remplace JAMAIS la palette terracotta — utilisée UNIQUEMENT pour les éléments de marque tenant (page login, logo area).

### 11.8. Accessibilité

- WCAG 2.1 AA minimum
- Contraste 4.5:1 texte normal, 3:1 texte large
- ⚠️ Terracotta sur blanc = 4.1:1 → utiliser uniquement en bold/large
- Focus ring : 3px var(--ring) offset 2px
- `prefers-reduced-motion: reduce` → pas d'animation
- Keyboard navigation complète

---

## 12. CONVENTIONS DE CODE

### 12.1. Python (Backend)

```python
# Typage strict partout (mypy compatible)
async def create_contact(
    data: ContactCreate,
    tenant: TenantContext = Depends(get_current_tenant),
) -> ContactResponse:
    """Create a new contact for the current tenant.

    Args:
        data: Contact creation payload.
        tenant: Injected tenant context.

    Returns:
        Created contact response.

    Raises:
        DuplicateContactError: If phone number already exists.
    """
    ...
```

- **Python 3.12+**, async/await partout, pas de code synchrone bloquant
- **Pydantic v2** pour tous les schemas (pas de dict bruts)
- **SQLAlchemy 2.0** async sessions
- Nommage : `snake_case` fonctions/variables, `PascalCase` classes
- Docstrings Google-style
- Logging structuré : **structlog** (pas de `print()`)
- Variables d'env : **pydantic-settings**
- Exceptions : custom héritant de `CRIBaseException`
- Tests : **pytest** + **pytest-asyncio**

### 12.2. TypeScript (Frontend)

- **TypeScript strict** (no `any`)
- **Next.js 15** App Router, Server Components par défaut
- **TailwindCSS** (pas de CSS custom sauf cas exceptionnel)
- API calls : client typé centralisé (`lib/api-client.ts`)
- Formulaires : React Hook Form + Zod
- État serveur : TanStack Query

### 12.3. Docker

- Un Dockerfile par service (multi-stage build)
- Non-root user dans tous les conteneurs
- Health checks dans chaque service

### 12.4. Git

- Branches : `main` (prod), `develop` (staging), `feature/*`, `fix/*`
- Commits conventionnels : `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
- PR obligatoire pour merge dans develop/main

### 12.5. Langue

- **Code** : anglais (variables, fonctions, commentaires techniques)
- **Documentation utilisateur** : français
- **Prompts Gemini** : système en français, réponses adaptées à la langue détectée

---

## 13. PHASAGE DU DÉVELOPPEMENT

### Phase 1 — Socle + Agent Public FAQ/Incitations (8 semaines) ← **EN COURS**

1. Infrastructure Docker Compose (PostgreSQL, Qdrant, Redis, MinIO, Traefik)
2. Middleware multi-tenant + provisionnement tenant
3. Intégration WhatsApp Business API (webhook, envoi/réception)
4. Pipeline RAG complet (ingestion, retrieval, génération Gemini)
5. Module incitations (arborescence interactive WhatsApp)
6. Multilinguisme FR/AR/EN
7. Guardrails (input + output + PII masking)
8. Back-office v1 (gestion KB, supervision conversations, contacts, feedback)
9. Sécurité Phase 1 : HMAC webhook, rate limiting, TLS, headers, bcrypt+JWT+RBAC, Docker networks
10. Tests pré-production

### Phase 2 — Agent Interne + Supervision (6 semaines)

11. Agent interne CRI (lecture seule, whitelist)
12. Système d'apprentissage supervisé complet
13. Module d'escalade agent humain (6 scénarios, WebSocket, interface BO)
14. Audit trail append-only + archivage signé
15. KMS logiciel + clé par tenant
16. Gestion sessions avancée (IP check, session unique)
17. Back-office complet (analytics, campagnes, gestion utilisateurs, super-admin)

### Phase 3 — Suivi Dossier + Production (6 semaines)

18. Module suivi de dossier (OTP, base dédiée, import Excel/CSV)
19. Sanitisation imports Excel/CSV
20. Notifications proactives
21. Tests de charge (100+ conversations, < 2s)
22. Détection d'anomalies Prometheus + Dashboard Grafana Sécurité
23. Tests de pénétration OWASP Top 10
24. Audit conformité CNDP
25. Déploiement production Nindohost
26. Formation utilisateurs CRI (à distance, R14)

---

## 14. EXIGENCES NON-FONCTIONNELLES

| Exigence | Valeur cible | Comment l'atteindre |
|----------|--------------|---------------------|
| Temps de réponse | < 2s (95th percentile) | Cache Redis, Gemini Flash TTFT < 1s, Qdrant HNSW, async partout |
| Conversations simultanées | 100+ | FastAPI async, connection pooling, workers ARQ |
| Disponibilité | 99,5% SLA | Health checks, graceful shutdown, retry logic, PRA |
| Trilinguisme | FR / Arabe classique / EN | Détection auto langue, prompts multilingues, Noto Sans Arabic |
| Multimodal | Texte + Image + Audio | Gemini 2.5 Flash multimodal natif |
| Données sensibles | Hébergement Maroc | Nindohost, anonymisation Gemini, chiffrement |

---

## 15. MONITORING ET OBSERVABILITÉ

### Métriques Prometheus

**Infrastructure :** CPU, RAM, disque, latence réseau par VPS
**API :** taux d'erreur, latence P95, requêtes par tenant
**WhatsApp :** taux envoi/lecture, erreurs API Meta
**Gemini :** latence TTFT, tokens consommés (input/output), coût estimé par tenant, taux d'erreur
**RAG :** score confiance moyen, taux fallback, temps retrieval Qdrant

### Traces LLM (PostgreSQL)

Prompt complet, réponse, tokens, latence, intention, chunks utilisés. Rétention 90 jours.

### Alertes Phase 3

- Utilisateur WhatsApp > 50 msg/h → aspiration de base
- Taux échec OTP > 20% / 1h → bruteforce coordonné
- Coût Gemini tenant > 2x moyenne 24h → anomalie usage

---

## 16. CLARIFICATIONS CPS À RETENIR

| Ref | Clarification |
|-----|---------------|
| R5 | Serveurs virtualisés sans GPU. Architecture LLM cloud acceptable. |
| R6 | CRI a un datacenter on-premise. |
| R7 | Accès distant via VPN et SSH. |
| R8 | Données suivi exportées Excel/CSV puis importées dans PostgreSQL. |
| R9 | ~6 000 dossiers actifs, ~1 000 nouveaux/an. |
| R10 | CRI ne dispose PAS de compte WhatsApp (à créer dans la prestation). |
| R11 | Agent interne en lecture seule uniquement. |
| R12 | Auth classique (email/mot de passe) suffisante pour back-office. |
| R13 | 100 000 messages = durée du marché (1 an). |
| R14 | Formation à distance autorisée. |

---

## 17. HEADER DESIGN POUR PROMPTS UI

Inclure ce bloc dans chaque prompt de création d'interface :

```
## DESIGN SYSTEM (NE PAS DÉVIER)
Direction : Modern Warm (Terracotta & Sable)
Palette primaire : Terracotta #C4704B, Sable #D4A574, Crème #FAF7F2
Typo titres : Plus Jakarta Sans (bold/semibold)
Typo body : Inter Variable (regular/medium)
Composants : shadcn/ui (thème custom CSS variables)
Icônes : Lucide React 20px
Charts : Recharts (palette : terracotta, sable, olive, info)
Layout : Sidebar dark brown #3D2B1F + contenu fond crème #FAF7F2
RTL : Natif via logical properties
Radius : 8px par défaut
INTERDIT : dark mode, gradients, polices autres que PJSans/Inter/Noto Sans Arabic
```

---

## 18. RAPPELS CRITIQUES

1. **Gemini 2.0 Flash est déprécié.** Utiliser **Gemini 2.5 Flash** partout.
2. **TOUJOURS penser multi-tenant.** Chaque requête DB, appel API, opération cache = scopé au tenant courant.
3. **JAMAIS exposer** clés API, tokens WhatsApp, données d'un tenant à un autre.
4. **Données sensibles** (dossiers, contacts, CIN) = serveurs Maroc (Nindohost) uniquement.
5. **Anonymiser** systématiquement les prompts envoyés à Gemini (pas de PII).
6. **async/await** partout côté backend. Pas de code synchrone bloquant.
7. **Pydantic v2** pour tous les schemas. Pas de dict bruts.
8. **structlog** pour le logging. Pas de `print()`.
9. **Le CPS est le document contractuel de référence.** Toute décision technique doit être justifiable.
10. **Tests unitaires** avec chaque module. pytest + pytest-asyncio.
## 19. AUTONOMIE CLAUDE CODE

- Claude Code a les droits COMPLETS sur tous les fichiers du repo
- Créer et modifier `.env` directement (générer les mots de passe avec `openssl rand -base64 32`)
- Exécuter `docker compose up/down` sans demander
- Lancer les tests automatiquement après chaque implémentation
- Faire les commits git avec le format conventionnel
- Ne PAS demander confirmation pour les opérations courantes
