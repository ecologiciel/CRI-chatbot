# 📘 GUIDE DE DÉVELOPPEMENT — RÉFÉRENCE PERMANENTE
# Plateforme Multi-Tenant RAG Chatbot CRI
## AO N° 02/2026/CRI RSK

> **Ce document est LA référence à consulter avant de générer des prompts pour n'importe quelle phase.**
> Il contient toutes les conventions, méthodologies, et règles validées pour le projet.
> Dernière mise à jour : Mars 2026

---

# TABLE DES MATIÈRES

1. [Workflow de développement](#1-workflow-de-développement)
2. [Système de Waves (parallélisation)](#2-système-de-waves)
3. [Format des prompts atomiques](#3-format-des-prompts-atomiques)
4. [Règles de découpage](#4-règles-de-découpage)
5. [Conventions de nommage MODULE.COUCHE](#5-conventions-de-nommage)
6. [Stack technique (invariants)](#6-stack-technique)
7. [Isolation multi-tenant (invariants)](#7-isolation-multi-tenant)
8. [Conventions de code](#8-conventions-de-code)
9. [Design system back-office](#9-design-system-back-office)
10. [Sécurité par phase](#10-sécurité-par-phase)
11. [Modèle de données](#11-modèle-de-données)
12. [Architecture conversationnelle LangGraph](#12-architecture-conversationnelle)
13. [Phasage du projet](#13-phasage-du-projet)
14. [Templates réutilisables](#14-templates-réutilisables)
15. [Checklist de génération de prompts](#15-checklist-de-génération)
16. [Anti-patterns à éviter](#16-anti-patterns)

---

# 1. WORKFLOW DE DÉVELOPPEMENT

## 1.1. Chaîne de production

```
┌─────────────────┐         ┌──────────────────┐         ┌──────────────┐
│  Claude AI      │ génère  │  Prompt atomique  │ copié   │  Claude Code │
│  (ce projet)    │───────→ │  (markdown)       │───────→ │  (CLI)       │
│  = Architecte   │         │  = Spécification  │         │  = Exécutant │
└─────────────────┘         └──────────────────┘         └──────────────┘
      │                                                        │
      │ analyse docs archi,                                    │ mode Plan
      │ CPS, annexes sécu/design                               │ → code
      │ découpe en micro-tâches                                │ → tests
      └───────────────────────────────────────────────────────-┘
                        boucle de feedback
                (erreur Claude Code → prompt correctif)
```

## 1.2. Rôles stricts

| Rôle | Qui | Fait | Ne fait PAS |
|------|-----|------|-------------|
| **Architecte** | Claude AI (ce projet) | Découpe, spécifie, génère les prompts | N'écrit pas de code directement dans le repo |
| **Exécutant** | Claude Code (CLI) | Code, teste, commit | Ne prend pas de décisions d'architecture |
| **Validateur** | Toi (développeur) | Valide les plans, lance les agents, vérifie | Ne code pas ce qui peut être automatisé |

## 1.3. Cycle de vie d'un prompt

```
1. TOI → "Découpe-moi le module X de la Phase Y"
2. CLAUDE AI → Liste numérotée des prompts avec résumés
3. TOI → "Valide" ou "Ajuste X, Y, Z"
4. CLAUDE AI → Génère le prompt complet en markdown
5. TOI → Copie dans Claude Code (mode Plan d'abord)
6. CLAUDE CODE → Plan d'exécution → TOI valide → Code + Tests
7. Si erreur → TOI colle l'erreur ici → CLAUDE AI génère un prompt correctif
8. Si OK → Prompt suivant (ou agent parallèle)
```

---

# 2. SYSTÈME DE WAVES (PARALLÉLISATION)

## 2.1. Concept

Une **Wave** est un groupe de prompts qui peuvent être exécutés **simultanément** sur des agents Claude Code distincts. On ne passe à la Wave suivante que quand TOUS les prompts de la Wave courante sont terminés.

## 2.2. Règles de parallélisation

| Règle | Explication |
|-------|-------------|
| **Même couche, modules différents** | Deux services indépendants au même niveau peuvent être parallélisés |
| **Backend // Frontend** | Le front-end (setup + mocks) peut démarrer en parallèle du backend dès que le design system est posé |
| **Tests groupés** | Regrouper les tests de plusieurs modules dans une même Wave pour paralléliser |
| **Jamais même fichier** | Deux agents ne doivent JAMAIS modifier le même fichier en parallèle |
| **Max 4 agents** | Au-delà de 4 agents parallèles, le risque de conflits de merge augmente |

## 2.3. Notation des dépendances

```
🟢 Aucune dépendance       → Peut démarrer immédiatement
🔵 Dépendance intra-module → Séquentiel dans le même module
🟡 Dépendance cross-module → Attend un prompt d'un autre module
```

## 2.4. Template de Wave

```
╔══════════════════════════════════════════════════════╗
║  WAVE N — Titre descriptif (X agents en parallèle)  ║
║  🅰 MODULE.X (description) ← dépendances            ║
║  🅱 MODULE.Y (description) ← dépendances            ║
║  🅲 MODULE.Z (description) ← dépendances            ║
╚══════════════════════════════════════════════════════╝
```

## 2.5. Stratégie des 2 pistes parallèles

Pour chaque phase, identifier si le frontend peut avancer en parallèle du backend :

```
PISTE BACKEND :  Wave 0 → 1 → 2 → ... → N (modèles → services → API → tests)
PISTE FRONTEND : ────────────── Wave F0 → F1 → ... → FN (design system → pages → intégration API)
                                 ↑
                      Démarre dès que le design system est posé
                      (aucune dépendance backend pour le setup)
```

Le frontend utilise des **données mockées** jusqu'à ce que les API backend soient prêtes, puis bascule sur les vraies API dans les dernières Waves.

---

# 3. FORMAT DES PROMPTS ATOMIQUES

## 3.1. Structure obligatoire

Chaque prompt pour Claude Code DOIT suivre cette structure exacte :

```markdown
## CONTEXTE
[Rappel ultra-concis : phase, module, où on en est, ce que ce prompt fait]

## OBJECTIF
[UNE seule tâche claire — UN prompt = UNE fonctionnalité/composant]

## SPÉCIFICATIONS TECHNIQUES
- Stack : [technologies exactes + versions]
- Fichiers à créer/modifier : [chemins exacts dans le monorepo]
- Dépendances à installer : [packages exacts]

## FICHIERS EXISTANTS (ne pas modifier, interfaces à respecter)
[Code des classes/types/interfaces dont ce prompt dépend — COPIÉ, pas référencé]
```python
# Exemple : backend/app/core/tenant.py expose :
class TenantContext:
    slug: str
    db_schema: str
    async def db_session() -> AsyncSession
```

## CONTRAINTES OBLIGATOIRES
- [ ] Multi-tenant : [contrainte spécifique à ce prompt]
- [ ] Sécurité : [mesure de sécurité intégrée, si applicable]
- [ ] Performance : [contrainte perf, si applicable]
- [ ] Design : [specs design, si prompt frontend]

## DÉTAIL DE L'IMPLÉMENTATION
[Description pas-à-pas avec noms exacts : classes, fonctions, types, colonnes]
1. [Étape 1 avec détails précis]
2. [Étape 2...]
3. ...

## SCHÉMA DE DONNÉES (si applicable)
[Tables, colonnes, types, index, relations]

## API ENDPOINTS (si applicable)
[Méthode, route, request body, response body, codes d'erreur]

## TESTS ATTENDUS
[Scénarios de test minimum — Claude Code doit les implémenter]

## VÉRIFICATION FINALE
[Commandes exactes que Claude Code doit exécuter pour confirmer que c'est "DONE"]
```bash
pytest tests/test_xxx.py -v
curl http://localhost:8000/api/v1/xxx
```

## DÉPENDANCES AVEC AUTRES PROMPTS
- Dépend de : [liste des prompts déjà faits]
- Prompts suivants qui en dépendent : [liste]
```

## 3.2. Règles de taille

| Métrique | Valeur cible | Pourquoi |
|----------|-------------|----------|
| Mots | 800-1500 | Trop court → Claude Code invente. Trop long → il oublie. |
| Fichiers créés | 1-4 | Au-delà, découper en sous-prompts |
| Lignes de code attendues | 100-400 | Au-delà, le risque d'erreur augmente |
| Durée d'exécution | 15-45 min | Un prompt ne devrait pas prendre plus d'1h |

## 3.3. Ce que le prompt DOIT contenir

- Les **imports exacts** (pas "importer ce qu'il faut")
- Les **noms de classes, fonctions, variables** (pas "créer un service")
- Les **types Pydantic complets** (champs, types, validators)
- Les **interfaces des dépendances** (code copié, pas juste un nom de fichier)
- Un **smoke test exécutable** (commande shell que Claude Code lance)

## 3.4. Ce que le prompt NE DOIT PAS contenir

- Des phrases vagues ("gérer les erreurs correctement")
- Des références à des fichiers que Claude Code n'a pas vus ("comme on a fait dans le module X")
- Des choix d'architecture ouverts ("choisis entre A ou B")
- Du code partiel ("je te montre l'idée, adapte")

---

# 4. RÈGLES DE DÉCOUPAGE

## 4.1. Principe : Bottom-up par couche

Pour chaque module fonctionnel, TOUJOURS découper dans cet ordre :

```
COUCHE 1 — Infrastructure / Config    (Docker, env, settings)
COUCHE 2 — Modèles de données         (SQLAlchemy + Pydantic + Alembic)
COUCHE 3 — Services métier             (logique pure, pas de HTTP)
COUCHE 4 — API / Routes                (endpoints FastAPI)
COUCHE 5 — Intégrations externes       (WhatsApp, Gemini, etc.)
COUCHE 6 — Frontend                    (pages, composants)
COUCHE 7 — Tests d'intégration         (E2E, isolation, charge)
```

## 4.2. Principe d'atomicité

| Bon découpage | Mauvais découpage |
|---------------|-------------------|
| 1 prompt = modèle SQLAlchemy + schéma Pydantic + migration | 1 prompt = modèle + service + API + tests |
| 1 prompt = service métier seul | 1 prompt = "fais tout le module WhatsApp" |
| 1 prompt = endpoint API + appel au service | 1 prompt = 10 endpoints d'un coup |
| 1 prompt = page frontend + composants associés | 1 prompt = tout le back-office |

## 4.3. Règle du commit

**Chaque prompt = un commit potentiel.** Après chaque prompt, le repo doit être dans un état fonctionnel. `docker compose up` ne doit pas casser.

## 4.4. Quand fusionner deux tâches en un seul prompt

Fusionner UNIQUEMENT si :
- Les deux tâches touchent les mêmes fichiers (ex: modèle + schéma Pydantic)
- L'une n'a aucun sens sans l'autre (ex: migration Alembic sans le modèle)
- Le total reste sous les 1500 mots

## 4.5. Quand splitter un prompt en deux

Splitter si :
- Le prompt dépasse 2000 mots
- Il crée plus de 4 fichiers
- Il couvre 2 couches différentes (ex: service + API)
- Il a des sous-tâches testables indépendamment

---

# 5. CONVENTIONS DE NOMMAGE MODULE.COUCHE

## 5.1. Format

```
MODULE.NUMÉRO — Description courte
```

Le numéro est séquentiel DANS le module et reflète l'ordre d'exécution.

## 5.2. Modules définis pour le projet CRI

| Module | Scope | Exemples de prompts |
|--------|-------|---------------------|
| INFRA | Docker, Traefik, config FastAPI, health checks | INFRA.1, INFRA.2, INFRA.3 |
| TENANT | Modèle tenant, middleware, provisioning, CRUD | TENANT.1 à TENANT.5 |
| AUTH | Admin, JWT, RBAC, rate limiting | AUTH.1 à AUTH.4 |
| WHATSAPP | Client Meta API, webhook, sessions, router | WHATSAPP.1 à WHATSAPP.5 |
| RAG | Ingestion, retrieval, génération, pipeline, API KB | RAG.1 à RAG.6 |
| ORCHESTRATOR | LangGraph, IntentDetector, Router, intégration | ORCHESTRATOR.1 à ORCHESTRATOR.3 |
| INCITATIONS | Modèle incitations, agent LangGraph, arborescence | INCITATIONS.1 à INCITATIONS.3 |
| LANG | Détection langue, prompts multilingues | LANG.1 à LANG.2 |
| FEEDBACK | Modèle feedback, service, API | FEEDBACK.1 à FEEDBACK.2 |
| CONTACTS | Modèle contact, service, API, CRM | CONTACTS.1 à CONTACTS.2 |
| BACKOFFICE | Setup Next.js, design system, pages | BACKOFFICE.1 à BACKOFFICE.7 |
| DOSSIER | Suivi dossier, OTP, import (Phase 3) | DOSSIER.1 à DOSSIER.X |
| ESCALADE | Agent humain, WebSocket, BO (Phase 2) | ESCALADE.1 à ESCALADE.X |
| INTERNE | Agent interne, whitelist (Phase 2) | INTERNE.1 à INTERNE.X |
| NOTIF | Notifications proactives (Phase 3) | NOTIF.1 à NOTIF.X |
| CAMPAGNE | Publipostage WhatsApp (Phase 2) | CAMPAGNE.1 à CAMPAGNE.X |
| MONITORING | Prometheus, Grafana, alertes (Phase 3) | MONITORING.1 à MONITORING.X |
| SECURITE | Audit trail, KMS, tests pentesting | SECURITE.1 à SECURITE.X |
| DEPLOY | CI/CD, Docker prod, Nindohost (Phase 3) | DEPLOY.1 à DEPLOY.X |

## 5.3. Ajout de nouveaux modules

Quand un nouveau besoin apparaît, créer un nouveau module plutôt que surcharger un module existant. Un module ne devrait pas dépasser 8-10 prompts.

---

# 6. STACK TECHNIQUE (INVARIANTS)

**NE JAMAIS DÉVIER sans discussion explicite.**

| Composant | Technologie | Version | Notes |
|-----------|-------------|---------|-------|
| LLM | Google Gemini 2.5 Flash | API cloud | ⚠️ Gemini 2.0 Flash DÉPRÉCIÉ (retrait 1er juin 2026) |
| Backend | Python / FastAPI | Python 3.12+, Pydantic v2 | async/await PARTOUT |
| Orchestration IA | LangGraph (LangChain) | Graphe d'état | Pas LangChain seul, pas CrewAI |
| Base vectorielle | Qdrant | Collection par tenant | Pas ChromaDB, pas Pinecone |
| Base relationnelle | PostgreSQL | 16 + schéma par tenant + RLS | Pas MySQL, pas MongoDB |
| Cache | Redis | 7 | Sessions, OTP, rate limiting, mapping |
| Stockage objet | MinIO | Bucket par tenant | S3-compatible |
| Embeddings | text-embedding-004 (Google) ou multilingual-e5-large | Dimension 768 | Multilingue FR/AR/EN |
| Front Back-Office | Next.js 15 + TailwindCSS + shadcn/ui | TypeScript strict | Pas React seul, pas Vue |
| WhatsApp | Meta Cloud API direct | v21.0+ | Pas Twilio, pas MessageBird |
| Conteneurisation | Docker + Docker Compose | Multi-stage builds | Non-root user |
| Reverse Proxy | Traefik v3 | TLS auto Let's Encrypt | Pas Nginx |
| CI/CD | GitHub Actions | SSH vers Nindohost | — |
| Monitoring | Prometheus + Grafana | — | Pas Datadog, pas ELK |
| Hébergement | Nindohost | Datacenter Maroc ISO 9001 | Données sensibles = Maroc UNIQUEMENT |

---

# 7. ISOLATION MULTI-TENANT (INVARIANTS)

## 7.1. Règle absolue

**Chaque ligne de code, chaque requête DB, chaque appel API, chaque opération cache DOIT être scopé au tenant courant. C'est un invariant de sécurité.**

## 7.2. Stratégies par composant

| Composant | Stratégie | Pattern |
|-----------|-----------|---------|
| PostgreSQL | Schéma par tenant | `tenant_{slug}.table_name` — SET search_path dans session |
| Qdrant | Collection par tenant | `kb_{slug}` — JAMAIS de requête cross-collection |
| Redis | Préfixe par tenant | `{slug}:type:id` — TOUJOURS préfixer |
| MinIO | Bucket par tenant | `cri-{slug}/` — politique IAM par bucket |
| WhatsApp | Config par tenant | Chaque tenant = son phone_number_id, access_token, templates |

## 7.3. Pattern obligatoire dans chaque service

```python
from app.core.tenant import TenantContext, get_current_tenant
from fastapi import Depends

async def any_service_function(
    data: SomeSchema,
    tenant: TenantContext = Depends(get_current_tenant)
):
    """Toute fonction métier DOIT recevoir le tenant via Depends."""
    async with tenant.db_session() as session:
        # Opère automatiquement dans le schéma du tenant
        result = await session.execute(select(Model).where(Model.id == data.id))
    # Qdrant : toujours la collection du tenant
    qdrant.search(collection_name=f"kb_{tenant.slug}", ...)
    # Redis : toujours le préfixe tenant
    redis.get(f"{tenant.slug}:session:{session_id}")
    # MinIO : toujours le bucket tenant
    minio.get_object(f"cri-{tenant.slug}", file_path)
```

## 7.4. Middleware TenantResolver

| Source | Mécanisme de résolution |
|--------|------------------------|
| Webhook WhatsApp | `phone_number_id` payload → lookup Redis `phone_mapping:{phone_number_id}` → tenant_id |
| Back-office API | Header `X-Tenant-ID` + validation JWT rôle admin |
| Super-admin | Header `X-Tenant-ID` optionnel + rôle `super_admin` |

Le `TenantContext` contient : slug, db_schema, qdrant_collection, redis_prefix, minio_bucket, whatsapp_config.

## 7.5. Ce que CHAQUE prompt doit vérifier

Inclure dans chaque prompt backend cette contrainte :

```
## CONTRAINTES OBLIGATOIRES
- [ ] Toute requête DB utilise `tenant.db_session()` (schéma automatique)
- [ ] Toute requête Qdrant cible `kb_{tenant.slug}`
- [ ] Toute clé Redis est préfixée par `{tenant.slug}:`
- [ ] Tout accès MinIO cible le bucket `cri-{tenant.slug}`
- [ ] Aucune donnée cross-tenant n'est accessible
```

---

# 8. CONVENTIONS DE CODE

## 8.1. Python (Backend)

| Convention | Règle | Exemple |
|------------|-------|---------|
| Python | 3.12+ | — |
| Async | async/await PARTOUT | Jamais de code synchrone bloquant |
| Types | Typage strict (mypy compatible) | `def foo(x: str) -> int:` |
| Schemas | Pydantic v2 | Pas de dict bruts |
| ORM | SQLAlchemy 2.0 async | `mapped_column()`, pas `Column()` |
| Nommage fonctions | snake_case | `get_dossier()` |
| Nommage classes | PascalCase | `TenantService` |
| Docstrings | Google-style | Sur toute fonction publique |
| Logging | structlog JSON | JAMAIS `print()` |
| Config | pydantic-settings | Classe `Settings` chargeant `.env` |
| Exceptions | Custom héritant `CRIBaseException` | `TenantNotFoundError`, `AuthenticationError` |
| Tests | pytest + pytest-asyncio | Avec chaque module |

## 8.2. TypeScript (Frontend)

| Convention | Règle |
|------------|-------|
| TypeScript | strict (no `any`) |
| Framework | Next.js 15 App Router, Server Components par défaut |
| Styling | TailwindCSS (pas de CSS custom sauf exception) |
| Composants UI | shadcn/ui exclusivement |
| API client | Client typé centralisé `lib/api-client.ts` |
| Formulaires | React Hook Form + Zod |
| État serveur | TanStack Query (React Query) |
| Icônes | Lucide React, 20px, stroke-width 1.75 |
| Charts | Recharts (palette: terracotta, sable, olive, info) |
| Tables | TanStack Table v8 + shadcn |

## 8.3. Docker

| Convention | Règle |
|------------|-------|
| Dockerfile | Un par service, multi-stage (builder + runner) |
| Utilisateur | Non-root dans TOUS les conteneurs |
| Health checks | Dans chaque service |
| Réseaux | `frontend` (Traefik+API) / `backend` (API+DB+Cache) |

## 8.4. Git

| Convention | Règle |
|------------|-------|
| Branches | `main` (prod), `develop` (staging), `feature/*`, `fix/*` |
| Commits | Conventionnels : `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:` |
| Merge | PR obligatoire pour develop/main |

## 8.5. Langue

| Contexte | Langue |
|----------|--------|
| Code (variables, fonctions, commentaires techniques) | Anglais |
| Conversation avec Claude AI | Français |
| Documentation utilisateur | Français |
| Prompts pour Claude Code | Français (explications), anglais (code) |
| Prompts Gemini | Système en français, réponses adaptées à la langue détectée |

---

# 9. DESIGN SYSTEM BACK-OFFICE

## 9.1. Direction : "Modern Warm" (Terracotta & Sable)

**AUCUN dark mode. AUCUN gradient agressif.**

## 9.2. Header à inclure dans CHAQUE prompt frontend

```
## DESIGN SYSTEM (NE PAS DÉVIER)
Direction : Modern Warm (Terracotta & Sable)
Palette primaire : Terracotta #C4704B, Sable #D4A574, Crème #FAF7F2
Sémantiques : Success #5F8B5F, Warning #C4944B, Error #B5544B, Info #5B7A8B, Olive #7A8B5F
Typo titres : Plus Jakarta Sans (bold/semibold)
Typo body : Inter Variable (regular/medium)
Typo arabe : Noto Sans Arabic
Composants : shadcn/ui (thème custom CSS variables)
Icônes : Lucide React 20px
Charts : Recharts (palette : terracotta, sable, olive, info)
Layout : Sidebar dark brown #3D2B1F (240px/64px) + contenu fond crème #FAF7F2
Topbar : 56px sticky (breadcrumb, search Cmd+K, langue, notifs, avatar)
RTL : Natif via logical properties (dir="rtl" quand arabe)
Radius : 8px par défaut
Ombres : shadow-card 0 1px 3px rgba(61,43,31,0.08), shadow-elevated 0 4px 12px rgba(61,43,31,0.12)
INTERDIT : dark mode, gradients, polices autres que PJSans/Inter/Noto Sans Arabic
```

## 9.3. CSS Variables

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

## 9.4. Composants clés

| Composant | Specs |
|-----------|-------|
| KPI Card | Icône 20px dans cercle 40px terracotta + titre 13px muted uppercase + valeur 28px bold + sparkline + tendance ▲▼ |
| Data Table | TanStack Table v8, header gris muted uppercase, hover crème, pagination 10/20/50, actions dropdown |
| Badges statut | Couleurs sémantiques avec classes : success/warning/error/info |
| Sidebar item actif | Background rgba(196,112,75,0.2) + bordure gauche 3px terracotta |
| Formulaires | React Hook Form + Zod, labels above, validation inline |
| Empty state | Illustration SVG line-art + titre + description + CTA |
| Toast | Bas-droite (bas-gauche RTL), 4s auto-dismiss, max 3 empilés |

## 9.5. RTL (Arabe)

| Aspect | Implémentation |
|--------|---------------|
| Direction | `dir="rtl"` sur `<html>` |
| Sidebar | Bascule à droite |
| Marges | `ms-*` / `me-*` (pas `ml-*` / `mr-*`) |
| Texte | `text-start` / `text-end` |
| Icônes directionnelles | `rtl:rotate-180` |
| Charts Recharts | Axe Y à droite |
| Toasts | Bas-gauche |

## 9.6. Multi-tenant theming (minimal)

Personnalisation par tenant : logo (SVG/PNG max 200x60), couleur accent (`--tenant-accent`), nom, favicon. La couleur accent NE REMPLACE JAMAIS la palette terracotta.

## 9.7. Responsive

| Breakpoint | Largeur | Sidebar | Grille |
|------------|---------|---------|--------|
| Mobile | < 768px | Sheet overlay | 1 colonne |
| Tablet | 768-1024px | Repliée 64px | 2 colonnes |
| Desktop | 1024-1440px | Dépliée 240px | 3-4 colonnes |
| Wide | > 1440px | Dépliée, contenu max-width 1400px | 4 colonnes |

---

# 10. SÉCURITÉ PAR PHASE

## 10.1. Principe d'intégration

La sécurité n'est PAS un module séparé. Chaque mesure est **embarquée dans le prompt du composant qu'elle protège**. Le tag `[SÉCU]` dans un prompt signale une mesure de sécurité intégrée.

## 10.2. Phase 1 — Socle sécurité (~12.5 jours-homme)

| Mesure | Intégrée dans quel prompt | Effort |
|--------|---------------------------|--------|
| HMAC-SHA256 webhook WhatsApp | WHATSAPP.2 | 0.5j |
| Rate limiting 4 niveaux (Redis) | AUTH.3 | 1j |
| Input Guardrails (injection, hors-périmètre) | RAG.3 (IntentDetector) | 2j |
| Output Guardrails (PII, ton, hallucination) | RAG.3 (ResponseValidator) | 2j |
| Anonymisation prompts Gemini | RAG.3 | 1j |
| Anti-BOLA middleware | TENANT.2 | 1j |
| TLS 1.3 Traefik + Let's Encrypt | INFRA.1 | 0.5j |
| Headers sécurité (CORS, CSP, HSTS) | INFRA.1 | 0.5j |
| Docker network isolation | INFRA.1 | 0.5j |
| Secret management (.env + .gitignore) | INFRA.1 | 0.5j |
| Auth back-office (bcrypt + JWT + RBAC) | AUTH.1 + AUTH.2 | 2j |
| Logging structuré structlog | INFRA.2 | 1j |

## 10.3. Phase 2 — Durcissement (~9.5 jours-homme)

| Mesure | Module | Effort |
|--------|--------|--------|
| Audit trail append-only (INSERT ONLY, archivage signé SHA-256) | SECURITE.1 | 2j |
| KMS logiciel + clé AES-256 par tenant (master key en env) | SECURITE.2 | 3j |
| Gestion sessions avancée (IP check, session unique, alertes) | SECURITE.3 | 1.5j |
| Sanitisation imports Excel/CSV (openpyxl data_only, injection SQL, HTML) | DOSSIER.X | 2j |
| Archivage signé MinIO (cron hebdo SHA-256) | SECURITE.4 | 1j |

## 10.4. Phase 3 — Audit et production (~10 jours-homme)

| Mesure | Module | Effort |
|--------|--------|--------|
| Anomaly detection Prometheus AlertManager | MONITORING.1 | 2j |
| Dashboard Grafana "Sécurité" | MONITORING.2 | 1j |
| Tests de pénétration OWASP Top 10 | SECURITE.5 | 3j |
| Audit conformité CNDP | SECURITE.6 | 2j |
| Tests de charge + volet sécurité | SECURITE.7 | 2j |

## 10.5. Risques couverts (matrice)

| Risque | Phase | Mesure clé |
|--------|-------|------------|
| R01 Injection prompt | P1 | Guardrails input + sandboxing |
| R02 Hallucination | P1 | Score confiance + disclaimer |
| R03 Fuite PII | P1 | Masquage pré/post LLM |
| R05 Cross-tenant | P1 | 5 niveaux isolation |
| R07 BOLA/IDOR | P1+P3 | Middleware anti-BOLA + OTP |
| R08 Webhook forgé | P1 | HMAC-SHA256 |
| R09 DDoS | P1 | Rate limiting 4 niveaux |
| R10 Données au repos | P1+P2 | pgcrypto + KMS |
| R11 Violation CNDP | P1+P2 | Hébergement Maroc + anonymisation |
| R12 Import malveillant | P2 | Sanitisation + sandboxing |
| R13 Compromission admin | P1+P2 | bcrypt + JWT + RBAC + sessions |
| R15 Suppression traces | P2 | Audit trail append-only |

---

# 11. MODÈLE DE DONNÉES

## 11.1. Schéma public (partagé)

```sql
tenants (id UUID, name, slug UNIQUE, region, logo_url, whatsapp_config JSONB, status ENUM, created_at, updated_at)
tenant_keys (id, tenant_id FK, encrypted_key, algorithm, created_at, rotated_at)  -- Phase 2
audit_logs (id, tenant_slug, user_id, user_type, action, resource_type, resource_id, ip_address, user_agent, details JSONB, created_at)  -- INSERT ONLY, Phase 2
```

## 11.2. Schéma tenant_{slug}

```sql
contacts (id UUID, phone UNIQUE, name, language ENUM, cin, opt_in_status ENUM, tags JSONB, source ENUM, created_at, updated_at)
  -- Index: phone (unique), cin, tags (GIN)

conversations (id UUID, contact_id FK, agent_type ENUM, status ENUM, started_at, ended_at)

messages (id UUID, conversation_id FK, direction ENUM, type ENUM, content, media_url, chunk_ids JSONB, whatsapp_message_id, timestamp)

kb_documents (id UUID, title, source_url, category, language, content_hash, status ENUM, created_at)

kb_chunks (id UUID, doc_id FK, content, qdrant_id, metadata JSONB)

unanswered_questions (id UUID, question, proposed_answer, status ENUM, reviewed_by FK, review_note, created_at)

feedback (id UUID, message_id FK, rating INT, comment, chunk_ids JSONB, created_at)

incentive_categories (id UUID, name, parent_id FK nullable, order INT, is_leaf BOOL, created_at)

incentive_items (id UUID, category_id FK, title, description, conditions, legal_reference, eligibility_criteria JSONB, documents_required JSONB, language, created_at)

admins (id UUID, email UNIQUE, password_hash, role ENUM, is_active, last_login, created_at)

-- Phase 2
escalations (id UUID, conversation_id FK, trigger_type ENUM, priority ENUM, assigned_to FK, context_summary, status ENUM, created_at, resolved_at)
campaigns (id UUID, name, template_id, audience JSONB, status ENUM, stats JSONB, scheduled_at, created_at)

-- Phase 3
dossiers (id UUID, numero, contact_id FK, statut ENUM, type_projet, dates JSONB, observations, created_at, updated_at)
dossier_history (id UUID, dossier_id FK, field_changed, old_value, new_value, changed_at, sync_log_id FK)
sync_logs (id UUID, source_type, file_name, rows_imported, rows_errored, status ENUM, started_at, completed_at)
sync_configs (id UUID, provider_type, config_json JSONB, mapping_json JSONB, schedule_cron, is_active)
```

## 11.3. Enums utilisés

```python
class TenantStatus(str, Enum): active, inactive, provisioning
class AgentType(str, Enum): public, internal
class ConversationStatus(str, Enum): active, ended, escalated, human_handled
class MessageDirection(str, Enum): inbound, outbound
class MessageType(str, Enum): text, image, audio, document, interactive, system
class OptInStatus(str, Enum): opted_in, opted_out, pending
class ContactSource(str, Enum): whatsapp, import_csv, manual
class Language(str, Enum): fr, ar, en
class AdminRole(str, Enum): super_admin, admin_tenant, supervisor, viewer
class KBDocumentStatus(str, Enum): pending, indexing, indexed, error
class UnansweredStatus(str, Enum): pending, approved, rejected
class EscalationTrigger(str, Enum): explicit_request, rag_failure, sensitive_topic, negative_feedback, otp_timeout, manual
class DossierStatut(str, Enum): en_cours, valide, rejete, en_attente, complet
```

---

# 12. ARCHITECTURE CONVERSATIONNELLE

## 12.1. Graphe LangGraph

```
[IntentDetector] → [Router] → [FAQAgent | IncentivesAgent | TrackingAgent* | InternalAgent* | EscalationHandler*]
                                    ↓
                            [ResponseValidator] → [FeedbackCollector] → Réponse WhatsApp

* = Phase 2 ou 3
```

## 12.2. Nœuds par phase

| Nœud | Phase | Rôle |
|------|-------|------|
| IntentDetector | P1 | Classification intent (Gemini ~50 tokens) + Input Guardrails |
| Router | P1 | Aiguillage conditionnel |
| FAQAgent | P1 | Pipeline RAG (retrieval + generation) |
| IncentivesAgent | P1 | Arborescence interactive WhatsApp |
| ResponseValidator | P1 | Output Guardrails (PII, ton, confiance) |
| FeedbackCollector | P1 | Boutons feedback (👍/👎/❓) |
| TrackingAgent | P3 | Auth OTP + consultation dossier |
| InternalAgent | P2 | Lecture seule (whitelist) |
| EscalationHandler | P2 | 6 scénarios d'escalade |

## 12.3. Intents classifiés

| Intent | Agent cible | Phase |
|--------|-------------|-------|
| `faq` | FAQAgent | P1 |
| `incitations` | IncentivesAgent | P1 |
| `suivi_dossier` | TrackingAgent | P3 |
| `agent_interne` | InternalAgent | P2 |
| `escalade` | EscalationHandler | P2 |
| `hors_perimetre` | Refus gracieux | P1 |

---

# 13. PHASAGE DU PROJET

## 13.1. Vue d'ensemble

| Phase | Durée | Objectif | Nb prompts estimés |
|-------|-------|----------|-------------------|
| Phase 1 | 8 semaines | Socle + Agent Public (FAQ + Incitations) + BO v1 | ~42 |
| Phase 2 | 6 semaines | Agent Interne + Escalade + Supervision + Sécurité durcissement | ~25-30 |
| Phase 3 | 6 semaines | Suivi Dossier + OTP + Notifications + Tests charge + Production | ~25-30 |

## 13.2. Contenu par phase

### Phase 1 (EN COURS)
1. Infrastructure Docker Compose
2. Middleware multi-tenant + provisionnement
3. WhatsApp Business API (webhook, envoi/réception)
4. Pipeline RAG complet (ingestion, retrieval, génération Gemini)
5. Module incitations (arborescence interactive)
6. Multilinguisme FR/AR/EN
7. Guardrails (input + output + PII)
8. Back-office v1 (KB, conversations, contacts, feedback)
9. Sécurité P1 (HMAC, rate limiting, TLS, JWT+RBAC, Docker networks)
10. Tests pré-production

### Phase 2
11. Agent interne CRI (lecture seule, whitelist)
12. Apprentissage supervisé complet
13. Escalade agent humain (6 scénarios, WebSocket, interface BO)
14. Audit trail append-only + archivage signé
15. KMS logiciel + clé par tenant
16. Gestion sessions avancée
17. Back-office complet (analytics, campagnes, gestion utilisateurs, super-admin)

### Phase 3
18. Suivi de dossier (OTP, base dédiée, import Excel/CSV)
19. Sanitisation imports Excel/CSV
20. Notifications proactives
21. Tests de charge (100+ conversations, < 2s)
22. Détection d'anomalies Prometheus + Grafana Sécurité
23. Tests de pénétration OWASP Top 10
24. Audit conformité CNDP
25. Déploiement production Nindohost
26. Formation utilisateurs CRI (à distance)

## 13.3. Pour générer les prompts d'une nouvelle phase

Suivre cette procédure :

```
1. Relire la section du CLAUDE.md correspondante (§13 Phasage)
2. Relire les sections concernées du document d'architecture
3. Relire l'annexe sécurité pour les mesures de cette phase
4. Relire l'annexe design pour les pages back-office de cette phase
5. Identifier tous les modules impactés
6. Découper en prompts atomiques (MODULE.COUCHE)
7. Organiser en Waves avec parallélisation
8. Générer le planning optimisé
9. Valider avec le développeur
10. Générer chaque prompt au format §3.1
```

---

# 14. TEMPLATES RÉUTILISABLES

## 14.1. Template — Prompt de modèle de données

```markdown
## CONTEXTE
Phase X du projet CRI. On crée le modèle de données pour [MODULE].

## OBJECTIF
Créer le modèle SQLAlchemy, les schémas Pydantic, et la migration Alembic pour [TABLE(S)].

## SPÉCIFICATIONS TECHNIQUES
- Stack : SQLAlchemy 2.0 (mapped_column, async), Pydantic v2, Alembic
- Fichiers : `backend/app/models/[module].py`, `backend/app/schemas/[module].py`, `backend/alembic/versions/XXX_create_[table].py`

## FICHIERS EXISTANTS
[interfaces des modèles/services dont on dépend]

## CONTRAINTES OBLIGATOIRES
- [ ] Tables dans le schéma `tenant_{slug}` (pas public, sauf si partagé)
- [ ] UUID comme primary key
- [ ] created_at/updated_at automatiques
- [ ] Index sur les champs de recherche fréquents

## DÉTAIL
[Tables, colonnes, types, FK, index, enums]

## TESTS
- Import du modèle sans erreur
- Migration up/down sans erreur

## VÉRIFICATION
```bash
cd backend && alembic upgrade head
python -c "from app.models.[module] import [Model]; print('OK')"
```
```

## 14.2. Template — Prompt de service métier

```markdown
## CONTEXTE
Phase X, module [MODULE]. Les modèles existent (prompt MODULE.Y). On crée la logique métier.

## OBJECTIF
Créer le service [ServiceName] dans `backend/app/services/[module]/service.py`.

## FICHIERS EXISTANTS
[Modèles, schémas Pydantic, TenantContext — CODE COPIÉ]

## CONTRAINTES OBLIGATOIRES
- [ ] Toutes les méthodes reçoivent `tenant: TenantContext`
- [ ] async/await partout
- [ ] Logging structuré structlog
- [ ] Exceptions custom

## DÉTAIL
[Méthodes avec signatures, logique, gestion d'erreurs]

## TESTS
[Scénarios unitaires à implémenter]

## VÉRIFICATION
```bash
pytest tests/test_[module]_service.py -v
```
```

## 14.3. Template — Prompt d'API endpoint

```markdown
## CONTEXTE
Phase X, module [MODULE]. Le service existe (prompt MODULE.Y). On crée l'API REST.

## OBJECTIF
Créer les endpoints dans `backend/app/api/v1/[module].py`.

## FICHIERS EXISTANTS
[Service, schémas, auth dependencies — CODE COPIÉ]

## CONTRAINTES OBLIGATOIRES
- [ ] Protection RBAC : `require_role([rôles autorisés])`
- [ ] Tenant injecté via `get_current_tenant`
- [ ] Pagination offset/limit sur les listes
- [ ] Codes d'erreur documentés

## ENDPOINTS
| Méthode | Route | Body | Response | Auth |
|---------|-------|------|----------|------|
| ... | ... | ... | ... | ... |

## TESTS
[Scénarios API avec httpx.AsyncClient]

## VÉRIFICATION
```bash
pytest tests/test_api_[module].py -v
```
```

## 14.4. Template — Prompt de page back-office

```markdown
## CONTEXTE
Phase X. Le back-office Next.js est initialisé (BACKOFFICE.1). L'API [MODULE] est prête.

## OBJECTIF
Créer la page [PAGE] du back-office.

## DESIGN SYSTEM (NE PAS DÉVIER)
[Copier le header design du §9.2]

## FICHIERS EXISTANTS
[Layout, API client, types — CODE COPIÉ]

## DÉTAIL
[Layout de la page, composants, données, interactions]

## RESPONSIVE
[Comportement mobile/tablette/desktop]

## RTL
[Adaptations spécifiques pour l'arabe]

## VÉRIFICATION
```bash
cd frontend && npm run build && npm run dev
```
[Vérifier visuellement la page]
```

---

# 15. CHECKLIST DE GÉNÉRATION DE PROMPTS

Avant de soumettre un prompt à Claude Code, vérifier :

## 15.1. Structure

- [ ] Le prompt suit le format du §3.1
- [ ] Il fait entre 800 et 1500 mots
- [ ] Il crée 1 à 4 fichiers maximum
- [ ] Il a une section VÉRIFICATION FINALE avec commandes exécutables

## 15.2. Contexte

- [ ] Les interfaces des dépendances sont COPIÉES (pas référencées)
- [ ] Les imports exacts sont spécifiés
- [ ] Les noms de classes/fonctions/variables sont explicites
- [ ] Les versions des packages sont précisées si critique

## 15.3. Multi-tenant

- [ ] Le prompt mentionne explicitement le pattern tenant
- [ ] Le schéma DB est dans `tenant_{slug}` (sauf tables partagées)
- [ ] Les clés Redis sont préfixées
- [ ] Les collections Qdrant sont scopées au tenant

## 15.4. Sécurité

- [ ] Les mesures de sécurité de la phase sont intégrées (cf §10)
- [ ] Tag [SÉCU] si une mesure de l'annexe sécurité est embarquée
- [ ] Pas de secrets en dur dans le code

## 15.5. Design (front-end)

- [ ] Le header design est inclus (cf §9.2)
- [ ] Les specs shadcn/ui sont respectées
- [ ] Le RTL est prévu
- [ ] Le responsive est décrit

## 15.6. Parallélisation

- [ ] Le prompt indique sa Wave
- [ ] Les prompts parallélisables sont identifiés
- [ ] Aucun conflit de fichier avec les prompts parallèles
- [ ] Les dépendances sont clairement listées (🟢🔵🟡)

---

# 16. ANTI-PATTERNS À ÉVITER

## 16.1. Anti-patterns de découpage

| Anti-pattern | Pourquoi c'est un problème | Solution |
|--------------|---------------------------|----------|
| "Prompt monolithe" (>2500 mots) | Claude Code oublie les détails au milieu | Découper en 2-3 sous-prompts |
| "Prompt vague" (<500 mots) | Claude Code invente et prend des libertés | Ajouter les noms exacts, types, imports |
| "Multi-couche en un prompt" | Trop de responsabilités, difficile à tester | Un prompt = une couche |
| "Pas de smoke test" | Claude Code dit "Done" mais rien ne marche | Toujours terminer par une commande de vérification |

## 16.2. Anti-patterns de code

| Anti-pattern | Solution |
|--------------|----------|
| `print()` pour debug | structlog |
| `dict` brut pour les données | Pydantic v2 schema |
| Code synchrone dans FastAPI | async/await partout |
| `Column()` SQLAlchemy | `mapped_column()` (SQLAlchemy 2.0) |
| `validator` Pydantic | `model_validator` (Pydantic v2) |
| CSS custom dans le front | TailwindCSS classes |
| `any` TypeScript | Type strict |
| Requête DB sans tenant scope | `tenant.db_session()` |
| Clé Redis sans préfixe tenant | `{slug}:type:id` |
| Gemini 2.0 Flash | Gemini 2.5 Flash (2.0 déprécié) |

## 16.3. Anti-patterns de parallélisation

| Anti-pattern | Solution |
|--------------|----------|
| 2 agents modifient le même fichier | Toujours vérifier les chemins de fichiers |
| Lancer la Wave N+1 sans finir la Wave N | Attendre la complétion de TOUS les prompts |
| Ignorer un test en échec pour avancer | Corriger le test AVANT de passer au prompt suivant |
| Plus de 4 agents en parallèle | Max 4, au-delà risque de conflits |

## 16.4. Anti-patterns de correction d'erreur

| Anti-pattern | Solution |
|--------------|----------|
| "Patch partiel" (corriger 1 ligne) | Générer un prompt correctif complet au même format |
| Réexpliquer tout le contexte | Inclure JUSTE l'erreur + le fichier concerné + le fix |
| Ignorer l'erreur multi-tenant | Toujours vérifier l'isolation en premier |
| Ne pas ajouter de test de non-régression | Chaque fix = un test qui vérifie le fix |

---

# 17. CLARIFICATIONS CPS À RETENIR

Ces clarifications impactent les décisions techniques dans CHAQUE phase :

| Ref | Clarification | Impact |
|-----|---------------|--------|
| R5 | Serveurs virtualisés sans GPU. LLM cloud acceptable. | Gemini API cloud, pas de modèle local |
| R6 | CRI a un datacenter on-premise. | Nindohost, pas AWS/GCP |
| R7 | Accès distant via VPN et SSH. | Déploiement CI/CD via SSH |
| R8 | Données suivi exportées Excel/CSV. | Import Excel/CSV dans PostgreSQL |
| R9 | ~6 000 dossiers actifs, ~1 000 nouveaux/an. | Dimensionnement DB |
| R10 | CRI ne dispose PAS de compte WhatsApp. | Création compte dans la prestation |
| R11 | Agent interne en lecture seule. | Pas de modification via Agent 2 |
| R12 | Auth classique email/mdp suffisante. | Pas de SSO/LDAP |
| R13 | 100 000 messages = durée du marché (1 an). | Compteur quota par tenant |
| R14 | Formation à distance autorisée. | Documentation + vidéos |

---

# 18. RAPPELS CRITIQUES PERMANENTS

1. **Gemini 2.0 Flash est DÉPRÉCIÉ.** Utiliser **Gemini 2.5 Flash** partout.
2. **TOUJOURS penser multi-tenant.** Chaque requête = scopée au tenant.
3. **JAMAIS exposer** clés API, tokens WhatsApp, données d'un tenant à un autre.
4. **Données sensibles** (dossiers, contacts, CIN) = serveurs Maroc UNIQUEMENT.
5. **Anonymiser** systématiquement les prompts envoyés à Gemini (pas de PII).
6. **async/await** partout côté backend.
7. **Pydantic v2** pour tous les schemas.
8. **structlog** pour le logging.
9. **Le CPS est le document contractuel de référence.**
10. **Tests unitaires** avec chaque module.
11. **Chaque prompt laisse le repo fonctionnel** (docker compose up ne casse pas).
12. **Le front utilise des mocks** jusqu'à ce que l'API soit prête.

---

# 19. COMMENT UTILISER CE GUIDE

## Pour générer les prompts d'une nouvelle phase :

```
"Claude AI, en suivant le guide de développement (sections 3, 4, 5, 10 pour la sécurité
de la Phase [X], et 9 pour le design des pages BO), découpe-moi les modules de la Phase [X]
en prompts atomiques avec Waves de parallélisation."
```

## Pour générer un prompt spécifique :

```
"Claude AI, génère le prompt [MODULE].[N] pour Claude Code, en suivant le format
du §3.1 du guide et en intégrant les contraintes multi-tenant du §7."
```

## Pour corriger une erreur Claude Code :

```
"Claude AI, voici l'erreur retournée par Claude Code sur le prompt [MODULE].[N] :
[coller l'erreur]
Génère un prompt correctif au même format §3.1."
```

## Pour ajouter un nouveau module non prévu :

```
"Claude AI, j'ai besoin d'un module [NOM] pour [besoin].
Propose une liste de prompts MODULE.COUCHE selon le §4 et §5 du guide,
avec intégration dans les Waves existantes (§2)."
```
