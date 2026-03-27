# Reference API — Plateforme CRI Chatbot

> Documentation complete des 30 endpoints REST Phase 1.
> Appel d'Offres N° 02/2026/CRI RSK

---

## 1. Informations generales

### 1.1. URL de base

| Environnement | URL |
|---------------|-----|
| Developpement | `http://localhost:8000/api/v1` |
| Production | `https://<domaine>/api/v1` |

**Documentation interactive** (dev uniquement) :
- Swagger UI : `http://localhost:8000/docs`
- ReDoc : `http://localhost:8000/redoc`

### 1.2. Authentification

Les endpoints proteges requierent un token JWT dans le header `Authorization` :

```
Authorization: Bearer <access_token>
```

Pour les endpoints tenant-scoped, le header `X-Tenant-ID` est egalement requis :

```
X-Tenant-ID: <uuid-du-tenant>
```

### 1.3. Format des reponses

**Succes :** corps JSON direct (schema specifique a chaque endpoint).

**Erreur :** format standardise :

```json
{
  "error": "NomDeLException",
  "message": "Description lisible de l'erreur",
  "details": { ... }
}
```

### 1.4. Codes HTTP

| Code | Signification |
|------|--------------|
| 200 | Succes |
| 201 | Ressource creee |
| 202 | Accepte (traitement asynchrone) |
| 204 | Succes sans contenu (suppression, deconnexion) |
| 400 | Requete invalide (header manquant, format incorrect) |
| 401 | Non authentifie (token manquant, expire, invalide) |
| 403 | Acces refuse (role insuffisant, tenant inactif) |
| 404 | Ressource introuvable |
| 409 | Conflit (doublon : slug, telephone, email) |
| 422 | Validation echouee (donnees invalides) |
| 429 | Trop de requetes (rate limiting, verrouillage compte) |
| 502 | Erreur service externe (Gemini, embeddings) |

### 1.5. Pagination

Tous les endpoints de liste utilisent le meme format :

**Parametres de requete :**
- `page` : numero de page (defaut : 1, min : 1)
- `page_size` : elements par page (defaut : 20, min : 1, max : 100)

**Reponse paginee :**

```json
{
  "items": [ ... ],
  "total": 150,
  "page": 1,
  "page_size": 20
}
```

---

## 2. Authentification (`/auth`)

> Pas de resolution tenant — opere sur le schema public.

### POST `/auth/login`

Connexion admin avec email et mot de passe.

**Auth requise :** Non

**Corps de la requete :**

```json
{
  "email": "admin@cri-rsk.ma",
  "password": "MotDePasse123!"
}
```

**Reponse 200 :**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

**Erreurs :**
- `401 AuthenticationError` : identifiants invalides
- `429 AccountLockedError` : compte verrouille apres 5 tentatives echouees (blocage 30 min)

---

### POST `/auth/refresh`

Renouveler le couple access/refresh token. Le refresh token est a usage unique.

**Auth requise :** Non

**Corps de la requete :**

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**Reponse 200 :** meme format que `/auth/login`

**Erreurs :**
- `401 AuthenticationError` : token invalide, expire, ou deja utilise

---

### GET `/auth/me`

Profil de l'administrateur connecte (donnees fraiches depuis la base).

**Auth requise :** Bearer token

**Reponse 200 :**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "admin@cri-rsk.ma",
  "full_name": "Ahmed Benali",
  "role": "admin_tenant",
  "tenant_id": "660e8400-e29b-41d4-a716-446655440001",
  "is_active": true,
  "last_login": "2026-03-27T10:00:00Z",
  "created_at": "2026-01-15T08:30:00Z"
}
```

---

### POST `/auth/logout`

Invalider un refresh token.

**Auth requise :** Bearer token

**Corps de la requete :**

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**Reponse :** `204 No Content`

---

## 3. Tenants (`/tenants`)

> Schema public. Accessible uniquement aux `super_admin` (sauf GET `/{id}` pour `admin_tenant` propre).

### POST `/tenants/`

Creer et provisionner un nouveau tenant. Pipeline atomique : schema PG + collection Qdrant + mappings Redis + bucket MinIO.

**Auth requise :** Bearer token, role `super_admin`

**Corps de la requete :**

```json
{
  "name": "CRI Rabat-Sale-Kenitra",
  "slug": "rabat_sale_kenitra",
  "region": "Rabat-Sale-Kenitra",
  "logo_url": "https://cri-rsk.ma/logo.svg",
  "accent_color": "#C4704B",
  "whatsapp_config": {
    "phone_number_id": "123456789",
    "access_token": "<TOKEN_META>",
    "display_name": "CRI RSK Bot"
  },
  "max_contacts": 50000,
  "max_messages_per_year": 100000,
  "max_admins": 10
}
```

**Reponse 201 :** `TenantAdminResponse` (inclut `whatsapp_config`)

**Erreurs :**
- `409 DuplicateTenantError` : slug deja existant
- `500 TenantProvisioningError` : echec de provisionnement (rollback automatique)

---

### GET `/tenants/`

Lister tous les tenants.

**Auth requise :** Bearer token, role `super_admin`

**Parametres :** `page`, `page_size`, `status` (optionnel : `active`, `inactive`, `provisioning`)

**Reponse 200 :** `TenantList` (paginee)

---

### GET `/tenants/{tenant_id}`

Obtenir les details d'un tenant.

**Auth requise :** Bearer token
- `super_admin` : acces a tout tenant → `TenantAdminResponse` (avec `whatsapp_config`)
- `admin_tenant` : uniquement son propre tenant → `TenantResponse` (sans `whatsapp_config`)

---

### PATCH `/tenants/{tenant_id}`

Modifier un tenant (mise a jour partielle).

**Auth requise :** Bearer token, role `super_admin`

**Corps :** tous les champs sont optionnels (nom, region, logo, couleur accent, quotas, whatsapp_config, status)

**Reponse 200 :** `TenantAdminResponse`

---

### DELETE `/tenants/{tenant_id}`

Deprovisionnement complet d'un tenant. **IRREVERSIBLE** : supprime le schema PostgreSQL, la collection Qdrant, le bucket MinIO, et les mappings Redis.

**Auth requise :** Bearer token, role `super_admin`

**Reponse :** `204 No Content`

---

## 4. Contacts (`/contacts`)

> Tenant-scoped : header `X-Tenant-ID` requis.

### GET `/contacts`

Lister les contacts avec recherche et filtres.

**Auth requise :** Bearer token, roles `super_admin`, `admin_tenant`, `supervisor`

**Parametres de requete :**

| Parametre | Type | Defaut | Description |
|-----------|------|--------|-------------|
| `page` | int | 1 | Numero de page |
| `page_size` | int | 20 | Elements par page (max 100) |
| `search` | string | — | Recherche par nom, telephone ou CIN |
| `opt_in_status` | enum | — | Filtre : `opted_in`, `opted_out`, `pending` |
| `language` | enum | — | Filtre : `fr`, `ar`, `en` |
| `tags` | string | — | Tags separes par virgule |

**Reponse 200 :** `ContactList` (paginee)

---

### POST `/contacts`

Creer un contact manuellement.

**Auth requise :** Bearer token, roles `super_admin`, `admin_tenant`

**Corps de la requete :**

```json
{
  "phone": "+212612345678",
  "name": "Fatima Zahra",
  "language": "fr",
  "cin": "AB12345",
  "tags": ["investisseur", "industrie"],
  "source": "manual"
}
```

**Validations :**
- `phone` : format E.164 obligatoire
- `cin` : format marocain `[A-Z]{1,2}\d{5,6}` (optionnel)

**Reponse 201 :** `ContactResponse`

**Erreurs :** `409 DuplicateResourceError` si le telephone existe deja

---

### GET `/contacts/{contact_id}`

Details d'un contact avec nombre de conversations et derniere interaction.

**Auth requise :** Bearer token, roles `super_admin`, `admin_tenant`, `supervisor`

**Reponse 200 :** `ContactDetailResponse`

```json
{
  "id": "...",
  "phone": "+212612345678",
  "name": "Fatima Zahra",
  "language": "fr",
  "cin": "AB12345",
  "opt_in_status": "opted_in",
  "tags": ["investisseur"],
  "source": "whatsapp",
  "conversation_count": 5,
  "last_interaction": "2026-03-26T14:30:00Z",
  "created_at": "2026-02-01T09:00:00Z"
}
```

---

### PATCH `/contacts/{contact_id}`

Modifier un contact (mise a jour partielle).

**Auth requise :** Bearer token, roles `super_admin`, `admin_tenant`

**Reponse 200 :** `ContactResponse`

---

### DELETE `/contacts/{contact_id}`

Supprimer un contact et ses conversations/messages associes (cascade).

**Auth requise :** Bearer token, roles `super_admin`, `admin_tenant`

**Reponse :** `204 No Content`

---

### POST `/contacts/import`

Importer des contacts depuis un fichier Excel ou CSV.

**Auth requise :** Bearer token, roles `super_admin`, `admin_tenant`

**Corps :** `multipart/form-data` avec fichier (`.csv`, `.xlsx`, `.xls`)

**Reponse 200 :**

```json
{
  "created": 150,
  "skipped": 12,
  "errors": [
    {"row": 45, "error": "Invalid phone format: 06123"},
    {"row": 78, "error": "Duplicate phone: +212612345678"}
  ]
}
```

---

### GET `/contacts/export`

Exporter tous les contacts du tenant en fichier.

**Auth requise :** Bearer token, roles `super_admin`, `admin_tenant`, `supervisor`

**Parametres :** `format` (`csv` ou `xlsx`, defaut : `csv`)

**Reponse :** `StreamingResponse` (fichier telecharge)

---

## 5. Base de connaissances (`/kb`)

> Tenant-scoped : header `X-Tenant-ID` requis.

### POST `/kb/documents`

Uploader un document dans la base de connaissances. Le traitement (chunking, embedding, indexation Qdrant) se fait de maniere asynchrone.

**Auth requise :** Bearer token, roles `super_admin`, `admin_tenant`

**Corps :** `multipart/form-data`

| Champ | Type | Requis | Validation |
|-------|------|--------|------------|
| `file` | fichier | Oui | Extensions : `.pdf`, `.docx`, `.txt`, `.md`, `.csv`. Taille max : 10 Mo |
| `title` | string | Oui | 1 a 500 caracteres |
| `category` | string | Non | Max 100 caracteres |
| `language` | enum | Non | `fr` (defaut), `ar`, `en` |

**Reponse 202 :** `KBDocumentResponse`

```json
{
  "id": "770e8400-e29b-41d4-a716-446655440002",
  "title": "Guide de creation d'entreprise",
  "category": "procedures",
  "language": "fr",
  "status": "pending",
  "chunk_count": 0,
  "created_at": "2026-03-27T11:00:00Z"
}
```

---

### GET `/kb/documents`

Lister les documents de la base de connaissances.

**Auth requise :** Bearer token, tous les roles

**Parametres :** `page`, `page_size`, `status` (`pending`, `indexing`, `indexed`, `error`), `category`

**Reponse 200 :** `KBDocumentList` (paginee)

---

### GET `/kb/documents/{document_id}`

Details d'un document avec ses chunks.

**Auth requise :** Bearer token, tous les roles

**Reponse 200 :** `KBDocumentDetailResponse` (inclut tableau `chunks[]`)

---

### DELETE `/kb/documents/{document_id}`

Supprimer un document, ses chunks (DB + Qdrant) et le fichier MinIO.

**Auth requise :** Bearer token, roles `super_admin`, `admin_tenant`

**Reponse :** `204 No Content`

---

### POST `/kb/documents/{document_id}/reindex`

Relancer l'ingestion complete d'un document. Le statut repasse a `pending`.

**Auth requise :** Bearer token, roles `super_admin`, `admin_tenant`

**Reponse 202 :** `KBDocumentResponse`

**Erreurs :** `422 ValidationError` si le document n'a pas de fichier associe

---

## 6. Feedback (`/feedback`)

> Tenant-scoped : header `X-Tenant-ID` requis.

### POST `/feedback`

Enregistrer un feedback sur un message.

**Auth requise :** Bearer token, roles `super_admin`, `admin_tenant`, `supervisor`

**Corps de la requete :**

```json
{
  "message_id": "880e8400-e29b-41d4-a716-446655440003",
  "rating": "negative",
  "reason": "Reponse incomplete",
  "comment": "Il manque les documents requis"
}
```

**Reponse 201 :** `FeedbackResponse`

---

### GET `/feedback`

Lister les feedbacks avec filtres.

**Auth requise :** Bearer token, tous les roles

**Parametres :** `page`, `page_size`, `rating` (`positive`, `negative`, `question`)

**Reponse 200 :** `FeedbackList` (paginee)

---

### GET `/feedback/stats`

Statistiques aggregees des feedbacks.

**Auth requise :** Bearer token, tous les roles

**Reponse 200 :**

```json
{
  "total": 500,
  "positive": 350,
  "negative": 100,
  "question": 50,
  "satisfaction_rate": 0.70
}
```

---

### GET `/feedback/unanswered`

Questions non couvertes par la base de connaissances (apprentissage supervise).

**Auth requise :** Bearer token, tous les roles

**Parametres :** `page`, `page_size`, `status` (`pending`, `approved`, `modified`, `rejected`, `injected`)

**Reponse 200 :** `UnansweredQuestionList` (paginee)

---

### PATCH `/feedback/unanswered/{question_id}`

Valider, modifier ou rejeter une question non couverte.

**Auth requise :** Bearer token, roles `super_admin`, `admin_tenant`

**Corps de la requete :**

```json
{
  "status": "approved",
  "proposed_answer": "Pour creer une SARL, les documents requis sont ...",
  "review_note": "Verifie avec le service juridique"
}
```

**Validation :** `proposed_answer` obligatoire si `status` = `approved` ou `modified`

**Reponse 200 :** `UnansweredQuestionResponse`

---

## 7. Dashboard (`/dashboard`)

> Tenant-scoped : header `X-Tenant-ID` requis.

### GET `/dashboard/stats`

Indicateurs cles de performance (KPIs) du tenant.

**Auth requise :** Bearer token, tous les roles

**Reponse 200 :**

```json
{
  "active_conversations": 12,
  "messages_today": 87,
  "resolution_rate": 0.85,
  "csat_score": 0.78,
  "total_contacts": 1250,
  "kb_documents_indexed": 45,
  "unanswered_questions": 8
}
```

---

## 8. Webhook WhatsApp (`/webhook`)

> Pas de resolution tenant via header. Le tenant est determine par le `phone_number_id` dans le payload.

### GET `/webhook/whatsapp`

Verification de l'abonnement webhook par Meta.

**Auth requise :** Non (verify token)

**Parametres de requete :**

| Parametre | Alias | Description |
|-----------|-------|-------------|
| `hub.mode` | `hub_mode` | Doit etre `subscribe` |
| `hub.verify_token` | `hub_verify_token` | Doit correspondre a `WHATSAPP_VERIFY_TOKEN` |
| `hub.challenge` | `hub_challenge` | Challenge Meta a renvoyer |

**Reponse 200 :** `PlainTextResponse` avec le challenge

**Erreurs :** `403` si le verify token ne correspond pas

---

### POST `/webhook/whatsapp`

Reception des evenements WhatsApp (messages, statuts de livraison, etc.).

**Auth requise :** Signature HMAC-SHA256 via header `X-Hub-Signature-256`

**Fonctionnement :**
1. Verification de la signature HMAC-SHA256 avec `WHATSAPP_APP_SECRET`
2. Parsing du payload Meta
3. Resolution du tenant via `phone_number_id`
4. Rate limiting : 50 req/min par tenant, 10 msg/min par utilisateur
5. Deduplication via Redis (cle `{slug}:whatsapp:dedup:{wamid}`, TTL 24h)
6. Traitement du message via l'orchestrateur LangGraph
7. Reponse WhatsApp via Meta Cloud API

**Reponse :** `200 OK` (toujours, sauf 403 si signature invalide)

> **Note :** Meta attend toujours un 200. Les erreurs de traitement sont loguees mais n'affectent pas le code de retour.

---

## 9. Health (`/health`)

### GET `/health`

Verification de la sante de tous les services d'infrastructure.

**Auth requise :** Non

**Reponse 200 :**

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "services": {
    "postgresql": { "status": "healthy", "latency_ms": 2.5 },
    "redis": { "status": "healthy", "latency_ms": 0.8 },
    "qdrant": { "status": "healthy", "latency_ms": 3.1 },
    "minio": { "status": "healthy", "latency_ms": 1.2 }
  }
}
```

**Statuts possibles :**
- `healthy` : tous les services operationnels
- `degraded` : au moins un service en erreur
- `unhealthy` : tous les services en erreur

---

## 10. Metriques (`/metrics`)

### GET `/metrics`

Endpoint Prometheus pour le scraping des metriques.

**Auth requise :** Non

**Format :** texte Prometheus standard

**Metriques incluses :**
- Latence et compteur de requetes HTTP (par route, methode, code)
- Metriques custom RAG : ingestion, retrieval, generation, guardrails
- Exclu du grouping : `/health`, `/metrics`

---

## Annexe A : Matrice des roles par endpoint

| Endpoint | super_admin | admin_tenant | supervisor | viewer |
|----------|:-----------:|:------------:|:----------:|:------:|
| POST /auth/login | — | — | — | — |
| POST /auth/refresh | — | — | — | — |
| GET /auth/me | ✓ | ✓ | ✓ | ✓ |
| POST /auth/logout | ✓ | ✓ | ✓ | ✓ |
| POST /tenants/ | ✓ | — | — | — |
| GET /tenants/ | ✓ | — | — | — |
| GET /tenants/{id} | ✓ | ✓ (propre) | — | — |
| PATCH /tenants/{id} | ✓ | — | — | — |
| DELETE /tenants/{id} | ✓ | — | — | — |
| GET /contacts | ✓ | ✓ | ✓ | — |
| POST /contacts | ✓ | ✓ | — | — |
| GET /contacts/{id} | ✓ | ✓ | ✓ | — |
| PATCH /contacts/{id} | ✓ | ✓ | — | — |
| DELETE /contacts/{id} | ✓ | ✓ | — | — |
| POST /contacts/import | ✓ | ✓ | — | — |
| GET /contacts/export | ✓ | ✓ | ✓ | — |
| POST /kb/documents | ✓ | ✓ | — | — |
| GET /kb/documents | ✓ | ✓ | ✓ | ✓ |
| GET /kb/documents/{id} | ✓ | ✓ | ✓ | ✓ |
| DELETE /kb/documents/{id} | ✓ | ✓ | — | — |
| POST /kb/.../reindex | ✓ | ✓ | — | — |
| POST /feedback | ✓ | ✓ | ✓ | — |
| GET /feedback | ✓ | ✓ | ✓ | ✓ |
| GET /feedback/stats | ✓ | ✓ | ✓ | ✓ |
| GET /feedback/unanswered | ✓ | ✓ | ✓ | ✓ |
| PATCH /feedback/unanswered/{id} | ✓ | ✓ | — | — |
| GET /dashboard/stats | ✓ | ✓ | ✓ | ✓ |
| GET/POST /webhook/whatsapp | HMAC | HMAC | HMAC | HMAC |
| GET /health | Public | Public | Public | Public |
| GET /metrics | Public | Public | Public | Public |

---

## Voir aussi

- [Architecture technique](architecture-technique.md) — Multi-tenant, securite, graphe LangGraph
- [Guide d'administration](guide-administration.md) — Utilisation du back-office
- [Guide de deploiement](guide-deploiement.md) — Installation et configuration
