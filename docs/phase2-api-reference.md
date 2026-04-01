# Reference API — Phase 2 (v0.2.0)

> Endpoints ajoutes en Phase 2. Pour les endpoints Phase 1, voir [api-reference.md](api-reference.md).

## Informations generales

### Authentification

Tous les endpoints necessitent :
- Un JWT valide dans le header `Authorization: Bearer <token>`
- Un header `X-Tenant-ID: <slug>` (sauf indication contraire)

### Pagination

Les endpoints listes supportent les parametres :
- `page` (int, defaut 1, min 1)
- `page_size` (int, defaut 20, min 1, max 100 ou 200 selon l'endpoint)

### Format des erreurs

```json
{
  "detail": "Description de l'erreur"
}
```

### Codes HTTP courants

| Code | Signification |
|------|---------------|
| 200  | Succes |
| 201  | Cree avec succes |
| 204  | Supprime avec succes (pas de corps) |
| 400  | Requete invalide (validation, statut incorrect) |
| 401  | Non authentifie |
| 403  | Acces interdit (role insuffisant) |
| 404  | Ressource non trouvee |
| 409  | Conflit (doublon, deja assigne) |
| 429  | Trop de requetes (rate limiting) |

---

## Module Escalade

**Prefixe :** `/api/v1/escalations`
**Roles autorises :** `supervisor`, `admin_tenant`

### GET /api/v1/escalations

Liste paginee des escalades du tenant courant.

**Query params :**
| Parametre | Type | Defaut | Description |
|-----------|------|--------|-------------|
| `page` | int | 1 | Page courante |
| `page_size` | int | 20 | Taille de page (max 100) |
| `status` | EscalationStatus | null | Filtrer par statut (`pending`, `assigned`, `in_progress`, `resolved`, `closed`) |
| `priority` | EscalationPriority | null | Filtrer par priorite (`high`, `medium`, `low`) |
| `assigned_to` | UUID | null | Filtrer par admin assigne |

**Response :** `EscalationList`
```json
{
  "items": [
    {
      "id": "uuid",
      "conversation_id": "uuid",
      "trigger_type": "explicit_request",
      "priority": "high",
      "status": "pending",
      "assigned_to": null,
      "context_summary": "L'utilisateur demande a parler a un agent...",
      "created_at": "2026-03-15T10:30:00Z",
      "resolved_at": null
    }
  ],
  "total": 42,
  "page": 1,
  "page_size": 20
}
```

### GET /api/v1/escalations/stats

Statistiques des escalades du tenant.

**Response :** `EscalationStats`
```json
{
  "total": 120,
  "pending": 5,
  "assigned": 3,
  "in_progress": 2,
  "resolved": 100,
  "closed": 10,
  "avg_resolution_time_minutes": 45.2
}
```

### GET /api/v1/escalations/{escalation_id}

Detail d'une escalade.

**Response :** `EscalationRead` | **404** si non trouvee.

### POST /api/v1/escalations/{escalation_id}/assign

Prendre en charge une escalade (self-assign a l'admin connecte).

**Response :** `EscalationRead` | **404** si non trouvee | **409** si deja assignee.

### POST /api/v1/escalations/{escalation_id}/respond

Envoyer un message a l'utilisateur via WhatsApp.

**Body :** `EscalationRespond`
```json
{
  "message": "Bonjour, je suis un agent CRI. Comment puis-je vous aider ?"
}
```

**Response :** `{ "wamid": "wamid.xxx" }` | **404** | **409** si escalade non assignee.

### POST /api/v1/escalations/{escalation_id}/close

Cloturer une escalade. La conversation revient en mode automatique.

**Body :** `EscalationResolve`
```json
{
  "resolution_notes": "Demande traitee, dossier mis a jour."
}
```

**Response :** `EscalationRead` | **404** | **409** si non assignee.

### GET /api/v1/escalations/{escalation_id}/conversation

Historique des messages de la conversation liee.

**Query params :**
| Parametre | Type | Defaut | Description |
|-----------|------|--------|-------------|
| `limit` | int | 50 | Nombre de messages (max 200) |

**Response :** `list[MessageResponse]` | **404** si escalade non trouvee.

### WebSocket /ws/escalations/{tenant_slug}

Notifications temps reel des escalades.

**URL :** `ws://{host}/ws/escalations/{tenant_slug}?token={jwt}`

**Authentification :** JWT dans le parametre `token` de la query string.
**Roles :** `supervisor`, `admin_tenant`, `super_admin`

**Evenements recus :**
| Evenement | Description |
|-----------|-------------|
| `new` | Nouvelle escalade creee |
| `assigned` | Escalade prise en charge |
| `resolved` | Escalade resolue |

**Format des messages :**
```json
{
  "event": "new",
  "data": {
    "id": "uuid",
    "trigger_type": "explicit_request",
    "priority": "high",
    "context_summary": "..."
  },
  "timestamp": "2026-03-15T10:30:00Z"
}
```

**Keepalive :** Le client envoie `"ping"` → le serveur repond `{"event": "pong", "timestamp": "..."}`.

**Codes de fermeture :**
| Code | Raison |
|------|--------|
| 4001 | Token invalide ou expire |
| 4003 | Role insuffisant |
| 4004 | Tenant invalide ou inactif |

---

## Module Campagnes

**Prefixe :** `/api/v1/campaigns`
**Roles autorises :** `super_admin`, `admin_tenant`

### GET /api/v1/campaigns

Liste des campagnes.

**Query params :**
| Parametre | Type | Defaut | Description |
|-----------|------|--------|-------------|
| `page` | int | 1 | Page courante |
| `page_size` | int | 20 | Taille de page (max 100) |
| `status` | CampaignStatus | null | Filtrer par statut (`draft`, `scheduled`, `sending`, `paused`, `completed`, `failed`) |

**Response :** `CampaignList`

### POST /api/v1/campaigns

Creer une campagne en mode `draft`.

**Body :** `CampaignCreate`
```json
{
  "name": "Rappel delais dossiers",
  "template_id": "template_123",
  "audience_filter": {
    "tags": ["investisseur"],
    "language": "fr",
    "opt_in_status": "opted_in"
  },
  "variable_mapping": {
    "1": "name",
    "2": "numero_dossier"
  }
}
```

**Response :** `CampaignRead` (status 201)

### GET /api/v1/campaigns/quota

Statut du quota WhatsApp du tenant.

**Query params :**
| Parametre | Type | Defaut | Description |
|-----------|------|--------|-------------|
| `count` | int | 0 | Nombre de messages a verifier (pour pre-validation) |

**Response :**
```json
{
  "used": 45000,
  "limit": 100000,
  "remaining": 55000,
  "usage_percent": 45.0
}
```

### GET /api/v1/campaigns/{campaign_id}

Detail d'une campagne avec statistiques.

**Response :** `CampaignRead` | **404** si non trouvee.

### PATCH /api/v1/campaigns/{campaign_id}

Modifier une campagne (statut `draft` uniquement).

**Body :** `CampaignUpdate` (champs optionnels : `name`, `template_id`, `audience_filter`, `variable_mapping`)

**Response :** `CampaignRead` | **400** si statut != draft | **404** si non trouvee.

### POST /api/v1/campaigns/{campaign_id}/schedule

Planifier l'envoi a une date future.

**Body :** `CampaignSchedule`
```json
{
  "scheduled_at": "2026-04-01T09:00:00Z"
}
```

**Response :** `CampaignRead` | **400** si statut incompatible | **404** si non trouvee.

### POST /api/v1/campaigns/{campaign_id}/launch

Lancer l'envoi immediatement. Verifie le quota avant envoi.

**Response :** `CampaignRead` | **400** si quota insuffisant ou statut incompatible | **404** si non trouvee.

### POST /api/v1/campaigns/{campaign_id}/pause

Mettre en pause une campagne en cours d'envoi.

**Response :** `CampaignRead` | **400** si statut != `sending` | **404** si non trouvee.

### POST /api/v1/campaigns/{campaign_id}/resume

Reprendre une campagne en pause.

**Response :** `CampaignRead` | **400** si statut != `paused` | **404** si non trouvee.

### GET /api/v1/campaigns/{campaign_id}/stats

Statistiques de livraison temps reel.

**Response :** `CampaignStats`
```json
{
  "total": 500,
  "sent": 480,
  "delivered": 460,
  "read": 320,
  "failed": 20,
  "delivery_rate": 95.8,
  "read_rate": 69.6
}
```

### GET /api/v1/campaigns/{campaign_id}/recipients

Liste paginee des destinataires.

**Query params :**
| Parametre | Type | Defaut | Description |
|-----------|------|--------|-------------|
| `page` | int | 1 | Page courante |
| `page_size` | int | 50 | Taille de page (max 200) |
| `status` | RecipientStatus | null | Filtrer par statut de livraison |

**Response :** `RecipientList` | **404** si campagne non trouvee.

### POST /api/v1/campaigns/{campaign_id}/preview

Previsualiser l'audience (comptage + echantillon de 5 contacts).

**Response :** `AudiencePreview`
```json
{
  "total_count": 1250,
  "sample_contacts": [
    {"id": "uuid", "phone": "+212600000001", "name": "Ahmed B.", "language": "fr"}
  ]
}
```

---

## Module Apprentissage Supervise

**Prefixe :** `/api/v1/learning`
**Roles :** voir par endpoint

### GET /api/v1/learning/questions

Liste des questions non couvertes.
**Roles :** `super_admin`, `admin_tenant`, `supervisor`

**Query params :**
| Parametre | Type | Defaut | Description |
|-----------|------|--------|-------------|
| `status` | UnansweredStatus | null | Filtrer par statut (`pending`, `proposed`, `approved`, `rejected`, `modified`) |
| `date_from` | datetime | null | Date debut |
| `date_to` | datetime | null | Date fin |
| `page` | int | 1 | Page courante |
| `page_size` | int | 20 | Taille de page (max 100) |

**Response :** `UnansweredQuestionList`

### GET /api/v1/learning/questions/{question_id}

Detail d'une question avec conversation source et chunks correles.
**Roles :** `super_admin`, `admin_tenant`, `supervisor`

**Response :** `UnansweredQuestionResponse` | **404** si non trouvee.

### POST /api/v1/learning/questions/{question_id}/generate

Generer une proposition de reponse IA via Gemini (utilise le pipeline RAG).
**Roles :** `super_admin`, `admin_tenant`, `supervisor`

**Response :** `UnansweredQuestionResponse` (avec `proposed_answer` rempli) | **404** si non trouvee.

### POST /api/v1/learning/questions/{question_id}/approve

Approuver la reponse. Declenche la reinjection dans Qdrant (worker asynchrone).
**Roles :** `super_admin`, `admin_tenant`

**Body :** `ApproveRequest`
```json
{
  "final_answer": "Reponse editee optionnelle. Si null, utilise la proposition existante."
}
```

**Response :** `UnansweredQuestionResponse` | **404** si non trouvee.

### POST /api/v1/learning/questions/{question_id}/reject

Rejeter une question avec raison obligatoire.
**Roles :** `super_admin`, `admin_tenant`

**Body :** `RejectRequest`
```json
{
  "reason": "Question hors perimetre CRI"
}
```

**Response :** `UnansweredQuestionResponse` | **404** si non trouvee.

### POST /api/v1/learning/questions/{question_id}/edit

Modifier la proposition sans approuver.
**Roles :** `super_admin`, `admin_tenant`, `supervisor`

**Body :** `EditRequest`
```json
{
  "edited_answer": "Reponse modifiee..."
}
```

**Response :** `UnansweredQuestionResponse` | **404** si non trouvee.

### GET /api/v1/learning/stats

Statistiques d'apprentissage.
**Roles :** `super_admin`, `admin_tenant`, `supervisor`, `viewer`

**Response :** `LearningStatsResponse`
```json
{
  "total": 85,
  "by_status": {
    "pending": 15,
    "proposed": 8,
    "approved": 50,
    "rejected": 10,
    "modified": 2
  },
  "approval_rate": 78.1,
  "avg_review_time_hours": 12.5,
  "top_pending": [
    {"question": "Comment obtenir un certificat negatif ?", "count": 5}
  ]
}
```

---

## Module Whitelist Agent Interne

**Prefixe :** `/api/v1/whitelist`
**Roles autorises :** `super_admin`, `admin_tenant`

### GET /api/v1/whitelist

Liste des numeros autorises pour l'agent interne.

**Query params :**
| Parametre | Type | Defaut | Description |
|-----------|------|--------|-------------|
| `page` | int | 1 | Page courante |
| `page_size` | int | 20 | Taille de page (max 100) |
| `search` | string | null | Recherche par telephone ou label |
| `is_active` | bool | null | Filtrer par statut actif/inactif |

**Response :** `InternalWhitelistList`

### GET /api/v1/whitelist/check

Verifier si un numero est dans la whitelist et actif.

**Query params :**
| Parametre | Type | Requis | Description |
|-----------|------|--------|-------------|
| `phone` | string | oui | Numero au format E.164 (ex: `+212600000001`) |

**Response :** `WhitelistCheckResponse`
```json
{
  "is_whitelisted": true,
  "is_active": true,
  "entry_id": "uuid"
}
```

### POST /api/v1/whitelist

Ajouter un numero a la whitelist.

**Body :** `InternalWhitelistCreate`
```json
{
  "phone": "+212600000001",
  "label": "Ahmed Benali",
  "note": "Responsable Service Investissement"
}
```

**Response :** `InternalWhitelistResponse` (status 201) | **409** si numero deja present.

### PATCH /api/v1/whitelist/{entry_id}

Modifier le label, la note ou le statut actif/inactif.

**Body :** `InternalWhitelistUpdate`
```json
{
  "label": "Nouveau nom",
  "note": "Mise a jour",
  "is_active": false
}
```

**Response :** `InternalWhitelistResponse` | **404** si non trouvee.

### DELETE /api/v1/whitelist/{entry_id}

Supprimer definitivement une entree.

**Response :** 204 (pas de corps) | **404** si non trouvee.

---

## Module Contacts (enrichissements Phase 2)

**Prefixe :** `/api/v1/contacts`
**Roles :** voir par endpoint

> Les endpoints de base (CRUD) sont documentes dans [api-reference.md](api-reference.md).
> Ci-dessous : les endpoints ajoutes en Phase 2 (Wave 17).

### POST /api/v1/contacts/import

Import de contacts depuis un fichier Excel/CSV.
**Roles :** `super_admin`, `admin_tenant`

**Body :** `multipart/form-data` avec fichier (`file`).
Formats acceptes : `.csv`, `.xlsx`. Maximum 50 000 lignes.
Deduplication automatique par numero de telephone.

**Response :** `ImportResultResponse`
```json
{
  "total_rows": 500,
  "imported": 480,
  "duplicates": 15,
  "errors": 5,
  "error_details": [
    {"row": 42, "error": "Numero de telephone invalide"}
  ]
}
```

### GET /api/v1/contacts/export

Export des contacts au format CSV ou XLSX.
**Roles :** `super_admin`, `admin_tenant`, `supervisor`

**Query params :**
| Parametre | Type | Defaut | Description |
|-----------|------|--------|-------------|
| `format` | string | `csv` | Format de sortie (`csv` ou `xlsx`) |
| `search` | string | null | Recherche full-text |
| `opt_in_status` | OptInStatus | null | Filtrer par consentement |
| `language` | Language | null | Filtrer par langue |
| `tags` | string | null | Filtrer par tags (separes par virgule) |
| `source` | ContactSource | null | Filtrer par source |
| `created_after` | datetime | null | Crees apres cette date |
| `created_before` | datetime | null | Crees avant cette date |

**Response :** `StreamingResponse` (fichier telecharge).

### GET /api/v1/contacts/segments

Liste des segments predefinis avec comptage en temps reel.
**Roles :** `super_admin`, `admin_tenant`, `supervisor`

**Response :** `list[SegmentInfo]`
```json
[
  {"key": "active_30d", "label": "Actifs 30 jours", "count": 245},
  {"key": "opted_out", "label": "Opt-out CNDP", "count": 18},
  {"key": "no_interaction", "label": "Sans interaction", "count": 502}
]
```

### GET /api/v1/contacts/segments/{segment_key}

Contacts dans un segment donne (pagine).
**Roles :** `super_admin`, `admin_tenant`, `supervisor`

**Response :** `ContactList`

### GET /api/v1/contacts/{contact_id}/history

Historique complet des interactions (conversations + participations campagnes).
**Roles :** `super_admin`, `admin_tenant`, `supervisor`

**Response :** `ContactHistory` | **404** si contact non trouve.

### POST /api/v1/contacts/tags/batch

Mise a jour de tags en lot sur plusieurs contacts.
**Roles :** `super_admin`, `admin_tenant`

**Body :** `TagsBatchUpdate`
```json
{
  "contact_ids": ["uuid1", "uuid2", "uuid3"],
  "add_tags": ["investisseur", "region-rsk"],
  "remove_tags": ["prospect"]
}
```

**Response :** `TagsBatchResult`
```json
{
  "updated": 3,
  "not_found": 0
}
```

### POST /api/v1/contacts/{contact_id}/opt-in

Changer le statut de consentement (conformite CNDP). Journalise dans l'audit trail.
**Roles :** `super_admin`, `admin_tenant`

**Body :** `OptInChangeRequest`
```json
{
  "new_status": "opted_out",
  "reason": "Demande explicite du contact"
}
```

**Response :** `OptInChangeLog` | **404** si contact non trouve.
