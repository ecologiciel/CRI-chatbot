# 🚀 PHASE 2 — PLAN D'EXÉCUTION COMPLET
# Plateforme Multi-Tenant RAG Chatbot CRI
# ~30 prompts | 6 semaines | Organisés en 9 Waves (13–21)

---

## 📊 VUE D'ENSEMBLE

| Métrique | Valeur |
|----------|--------|
| Prompts totaux | 30 |
| Waves | 9 (Wave 13 → Wave 21) |
| Points de commit | 11 |
| Durée estimée | 6 semaines |
| Agents parallèles max | 3 |
| Prérequis | Phase 1 complète (v0.1.0-phase1) |

## 🎯 OBJECTIF PHASE 2

Déployer l'Agent 2 (interne CRI), les outils de supervision (escalade, apprentissage supervisé), le module campagnes, le durcissement sécurité, et le back-office complet (analytics, campagnes, gestion utilisateurs, super-admin).

**Livrables :** Agent interne fonctionnel, back-office complet, système d'apprentissage supervisé, module escalade, module campagnes, documentation, rapport de tests.

## 🔑 LÉGENDE

```
✅ DONE        — Déjà exécuté
⏳ EN COURS    — En cours d'exécution
⬜ À FAIRE     — Pas encore commencé
🔒 BLOQUÉ      — Attend une dépendance

🟢 Aucune dépendance
🔵 Dépendance intra-module (séquentiel)
🟡 Dépendance cross-module

🅰🅱🅲 = Agents parallèles dans la même Wave
📌 COMMIT = Point de commit + push obligatoire

[SÉCU] = Mesure de sécurité intégrée (annexe sécurité)
[DESIGN] = Conformité design system Modern Warm (annexe design)
```

---

## 📋 LISTE COMPLÈTE DES PROMPTS

### Module INTERNE (Agent Interne CRI)
| # | Prompt | Status | Wave |
|---|--------|--------|------|
| 1 | INTERNE.1 — Modèle Whitelist + schemas Pydantic + migration | ⬜ | 13 |
| 2 | INTERNE.2 — Service agent interne (whitelist check, lecture dossiers, stats) | ⬜ | 15 |
| 3 | INTERNE.3 — InternalAgent node LangGraph + mise à jour Router/IntentDetector | ⬜ | 15 |
| 4 | INTERNE.4 — API gestion whitelist (CRUD numéros autorisés) | ⬜ | 17 |

### Module ESCALADE (Escalade Agent Humain)
| # | Prompt | Status | Wave |
|---|--------|--------|------|
| 5 | ESCALADE.1 — Modèle Escalation + schemas + migration | ⬜ | 13 |
| 6 | ESCALADE.2 — Service escalade (6 scénarios, détection, assignation, résolution) | ⬜ | 15 |
| 7 | ESCALADE.3 — EscalationHandler node LangGraph + mise à jour Router | ⬜ | 15 |
| 8 | ESCALADE.4 — WebSocket notifications temps réel (FastAPI WS, auth JWT, Redis pub/sub) | ⬜ | 16 |
| 9 | ESCALADE.5 — API escalade (list, assign, respond via WhatsApp, close) | ⬜ | 16 |

### Module APPRENTISSAGE (Apprentissage Supervisé Complet)
| # | Prompt | Status | Wave |
|---|--------|--------|------|
| 10 | APPRENTISSAGE.1 — Service apprentissage supervisé (propositions IA Gemini, workflow validation) | ⬜ | 15 |
| 11 | APPRENTISSAGE.2 — Worker réinjection Qdrant (validation → chunk → embed → index) | ⬜ | 16 |
| 12 | APPRENTISSAGE.3 — API apprentissage (list/review/approve/reject/edit + stats) | ⬜ | 16 |

### Module CAMPAGNE (Publipostage WhatsApp)
| # | Prompt | Status | Wave |
|---|--------|--------|------|
| 13 | CAMPAGNE.1 — Modèle Campaign + CampaignRecipient + schemas + migration | ⬜ | 13 |
| 14 | CAMPAGNE.2 — Service campagne (audience builder, mapping variables, planification) | ⬜ | 16 |
| 15 | CAMPAGNE.3 — Worker envoi campagne (ARQ, gestion débit, quota 100K, stats) | ⬜ | 16 |
| 16 | CAMPAGNE.4 — API campagnes (CRUD, start, pause, stats, export) | ⬜ | 17 |

### Module SECURITE (Durcissement Phase 2) [SÉCU]
| # | Prompt | Status | Wave |
|---|--------|--------|------|
| 17 | SECURITE.1 — Audit trail append-only (INSERT ONLY policy, service logging) | ⬜ | 14 |
| 18 | SECURITE.2 — KMS logiciel (clé AES-256 par tenant, master key env, rotation) | ⬜ | 14 |
| 19 | SECURITE.3 — Gestion sessions avancée (IP check, session unique, alertes) | ⬜ | 14 |
| 20 | SECURITE.4 — Archivage signé MinIO (cron job hebdo, SHA-256, rétention 24 mois) | ⬜ | 14 |

### Module CONTACTS (CRM Complet — enrichissement Phase 1)
| # | Prompt | Status | Wave |
|---|--------|--------|------|
| 21 | CONTACTS.2 — Service contacts enrichi (segmentation, tags avancés, opt-in/out CNDP, STOP) | ⬜ | 17 |
| 22 | CONTACTS.3 — API contacts complète (search avancée, import/export Excel, dédoublonnage) | ⬜ | 17 |

### Module BACKOFFICE (Pages Front-end Phase 2) [DESIGN]
| # | Prompt | Status | Wave |
|---|--------|--------|------|
| 23 | BO.7 — Page Analytics & Rapports (Recharts, 5 tabs, KPI cards, export PDF/Excel) | ⬜ | 18F |
| 24 | BO.8 — Page Campagnes (wizard 4 étapes, audience builder, preview WhatsApp) | ⬜ | 18F |
| 25 | BO.9 — Page Gestion Utilisateurs + RBAC + Section Whitelist Agent Interne | ⬜ | 18F |
| 26 | BO.10 — Page Escalade (file d'attente temps réel, WebSocket, prise en charge) | ⬜ | 19F |
| 27 | BO.11 — Page Apprentissage supervisé (tab KB enrichi, review/validate/reject) | ⬜ | 19F |
| 28 | BO.12 — Back-office Super-Admin (gestion tenants, monitoring global, wizard création) | ⬜ | 19F |

### Module INTEGRATION + TESTS
| # | Prompt | Status | Wave |
|---|--------|--------|------|
| 29 | INTEGRATION.2 — Graphe LangGraph v2 (InternalAgent + EscalationHandler) + E2E | ⬜ | 20 |
| 30 | TEST.3 — Tests unitaires + intégration Phase 2 (sécurité, escalade, interne, campagnes) | ⬜ | 21 |

---

## 🌊 PLAN D'EXÉCUTION PAR WAVE

---

### ╔══════════════════════════════════════════════════════╗
### ║  WAVE 13 — Modèles de données Phase 2 (3 agents)     ║
### ╚══════════════════════════════════════════════════════╝

| Agent | Prompt | Fichiers | Durée |
|-------|--------|----------|-------|
| 🅰 | INTERNE.1 — Modèle Whitelist + schemas + migration | models/whitelist.py, schemas/whitelist.py | 0.5j |
| 🅱 | ESCALADE.1 — Modèle Escalation + schemas + migration | models/escalation.py, schemas/escalation.py | 0.5j |
| 🅲 | CAMPAGNE.1 — Modèle Campaign + CampaignRecipient + schemas + migration | models/campaign.py, schemas/campaign.py | 0.5j |

**Dépendances :** Phase 1 complète (Wave 12)

#### INTERNE.1 — Modèle Whitelist
**Résumé :** Table `internal_whitelist` dans le schéma tenant : id UUID, phone (E.164, UNIQUE), name, added_by (FK admins), is_active, created_at, updated_at. Schemas Pydantic : WhitelistCreate, WhitelistRead, WhitelistList. Migration Alembic.
**Fichiers :** `backend/app/models/whitelist.py`, `backend/app/schemas/whitelist.py`, `backend/alembic/versions/XXX_create_whitelist.py`

#### ESCALADE.1 — Modèle Escalation
**Résumé :** Table `escalations` dans le schéma tenant : id UUID, conversation_id FK, trigger_type ENUM(explicit_request, rag_failure, sensitive_topic, negative_feedback, otp_timeout, manual), priority ENUM(high, medium, low), assigned_to FK admins nullable, context_summary TEXT (généré Gemini), status ENUM(pending, assigned, in_progress, resolved, closed), resolution_notes TEXT, created_at, assigned_at, resolved_at. Schemas Pydantic complets. Index sur status + priority.
**Fichiers :** `backend/app/models/escalation.py`, `backend/app/schemas/escalation.py`, `backend/alembic/versions/XXX_create_escalations.py`

#### CAMPAGNE.1 — Modèle Campaign + Recipients
**Résumé :** Table `campaigns` : id UUID, name, template_id (WhatsApp template), template_name, audience_filter JSONB (tags, segments), variable_mapping JSONB, status ENUM(draft, scheduled, sending, paused, completed, failed), scheduled_at, started_at, completed_at, stats JSONB (sent, delivered, read, clicked, failed), created_by FK admins, created_at. Table `campaign_recipients` : id, campaign_id FK, contact_id FK, status ENUM(pending, sent, delivered, read, failed), sent_at, error_message. Index sur campaign_id + status.
**Fichiers :** `backend/app/models/campaign.py`, `backend/app/schemas/campaign.py`, `backend/alembic/versions/XXX_create_campaigns.py`

```
📌 COMMIT : git commit -m "feat: Wave 13 — Phase 2 data models (whitelist, escalation, campaign)"
📌 PUSH : git push
```

---

### ╔══════════════════════════════════════════════════════╗
### ║  WAVE 14 — Sécurité durcissement Phase 2 (3 agents)   ║
### ╚══════════════════════════════════════════════════════╝

| Agent | Prompt | Fichiers | Durée |
|-------|--------|----------|-------|
| 🅰 | SECURITE.1 — Audit trail append-only + service logging | models/audit.py, services/audit/ | 1.5j |
| 🅱 | SECURITE.2 — KMS logiciel + clé par tenant | services/crypto/ | 2j |
| 🅲 | SECURITE.3 + SECURITE.4 — Sessions avancées + archivage signé | services/auth/, workers/archive.py | 1.5j |

**Dépendances :** Wave 13 (modèles)

#### SECURITE.1 — Audit trail append-only [SÉCU]
**Résumé :** Table `audit_logs` dans le schéma **public** (pas tenant) : id UUID, tenant_slug, user_id, user_type ENUM(admin, whatsapp_user), action VARCHAR, resource_type VARCHAR, resource_id VARCHAR, ip_address INET, user_agent TEXT, details JSONB, created_at. Politique INSERT ONLY : le rôle applicatif n'a PAS les droits UPDATE/DELETE. Service `AuditService` avec méthode `log_action()` appelable depuis tous les modules. Middleware FastAPI pour logger automatiquement les actions admin. Rétention 12 mois en DB.
**Fichiers :** `backend/app/models/audit.py`, `backend/app/services/audit/service.py`, `backend/app/services/audit/__init__.py`, `backend/alembic/versions/XXX_create_audit_logs.py`

#### SECURITE.2 — KMS logiciel [SÉCU]
**Résumé :** Table `tenant_keys` dans le schéma public : id UUID, tenant_id FK, encrypted_key BYTEA, algorithm VARCHAR (default AES-256-GCM), created_at, rotated_at. Service `KMSService` : generate_tenant_key(), encrypt(data, tenant_slug), decrypt(data, tenant_slug), rotate_key(tenant_slug). Master key depuis variable d'environnement `KMS_MASTER_KEY`. Chiffrement AES-256-GCM avec IV aléatoire. Intégration avec le provisionnement tenant (auto-génération clé).
**Fichiers :** `backend/app/models/tenant_key.py`, `backend/app/services/crypto/kms.py`, `backend/app/services/crypto/__init__.py`, `backend/alembic/versions/XXX_create_tenant_keys.py`

#### SECURITE.3 + SECURITE.4 — Sessions avancées + Archivage [SÉCU]
**Résumé :** Enrichissement du service auth existant : détection changement IP pendant session (clé Redis `{slug}:session:{user_id}:ip`), session unique par compte (nouvelle connexion → invalidation ancienne session), logging complet chaque action admin dans audit trail, alerte email si connexion depuis 2 IP différentes en < 5 min. Worker ARQ `archive_audit_logs` : cron hebdomadaire, export JSON des logs de la semaine sur MinIO bucket `cri-{slug}`, calcul SHA-256 du fichier, stockage du hash dans metadata MinIO. Rétention MinIO 24 mois.
**Fichiers :** `backend/app/services/auth/session_manager.py`, `backend/app/workers/archive.py`, modification `backend/app/services/auth/service.py`

```
📌 COMMIT : git commit -m "feat: Wave 14 — Security hardening (audit trail, KMS, sessions, archival)"
📌 PUSH : git push
```

---

### ╔══════════════════════════════════════════════════════╗
### ║  WAVE 15 — Services métier core Phase 2 (3 agents)    ║
### ╚══════════════════════════════════════════════════════╝

| Agent | Prompt | Fichiers | Durée |
|-------|--------|----------|-------|
| 🅰 | INTERNE.2 + INTERNE.3 — Service + InternalAgent LangGraph | services/internal/, services/orchestrator/ | 1.5j |
| 🅱 | ESCALADE.2 + ESCALADE.3 — Service + EscalationHandler LangGraph | services/escalation/, services/orchestrator/ | 1.5j |
| 🅲 | APPRENTISSAGE.1 — Service apprentissage supervisé complet | services/learning/ | 1j |

**Dépendances :** Wave 14 (audit trail pour logging), Wave 13 (modèles)

#### INTERNE.2 + INTERNE.3 — Agent Interne complet
**Résumé :** `InternalAgentService` : verify_whitelist(phone) → bool, get_dashboard_stats(tenant) → stats simplifiés (dossiers par statut, conversations du jour, questions non couvertes), get_dossier_summary(dossier_id, tenant) → résumé, generate_report(criteria, tenant) → rapport Gemini. Nœud LangGraph `InternalAgent` : reçoit intent "internal" → vérifie whitelist → si autorisé, exécute la requête (FAQ interne, stats, consultation dossier) → sinon, message refus poli. Mise à jour `IntentDetector` pour détecter intent "internal". Mise à jour `Router` pour aiguiller vers InternalAgent. Le nœud utilise agent_type="internal" dans le ConversationState.
**Fichiers :** `backend/app/services/internal/service.py`, `backend/app/services/orchestrator/internal_agent.py`, modification `backend/app/services/orchestrator/intent.py`, modification `backend/app/services/orchestrator/router.py`

#### ESCALADE.2 + ESCALADE.3 — Escalade complète
**Résumé :** `EscalationService` : detect_escalation(state) → EscalationTrigger | None (analyse les 6 scénarios : demande explicite via Gemini, échec RAG 2x consécutifs score < 0.5, sujet sensible classification Gemini, feedback négatif + "parler agent", timeout OTP 5min, déclenchement manuel BO), create_escalation(conversation_id, trigger, priority), assign_escalation(escalation_id, admin_id), respond_via_whatsapp(escalation_id, message, admin_id), close_escalation(escalation_id, resolution_notes), generate_context_summary(conversation_id) → résumé Gemini de l'historique. Nœud LangGraph `EscalationHandler` : reçoit intent "escalade" OU est invoqué par detect_escalation() → crée escalation → envoie message WhatsApp "Un conseiller va prendre le relais" → conversation.status = "escalated". Mise à jour Router. Audit trail pour chaque action.
**Fichiers :** `backend/app/services/escalation/service.py`, `backend/app/services/orchestrator/escalation_handler.py`, modification `backend/app/services/orchestrator/router.py`

#### APPRENTISSAGE.1 — Service apprentissage supervisé
**Résumé :** `SupervisedLearningService` : enrichissement du service feedback existant. get_unanswered_questions(tenant, filters) → liste paginée, generate_ai_proposal(question_id) → proposition IA Gemini basée sur KB existante + contexte, approve_question(question_id, admin_id, final_answer?) → marque "approved" + prépare chunk pour réinjection, reject_question(question_id, admin_id, reason), edit_proposal(question_id, admin_id, edited_answer) → marque "approved" avec réponse éditée, get_learning_stats(tenant) → nb pending/approved/rejected, taux de couverture KB. Corrélation avec le FeedbackService (les 👎 avec raison alimentent la file).
**Fichiers :** `backend/app/services/learning/service.py`, `backend/app/services/learning/__init__.py`

```
📌 COMMIT : git commit -m "feat: Wave 15 — Core services (internal agent, escalation, supervised learning)"
📌 PUSH : git push
```

---

### ╔══════════════════════════════════════════════════════╗
### ║  WAVE 16 — APIs + Workers + WebSocket (3 agents)      ║
### ╚══════════════════════════════════════════════════════╝

| Agent | Prompt | Fichiers | Durée |
|-------|--------|----------|-------|
| 🅰 | ESCALADE.4 + ESCALADE.5 — WebSocket + API escalade | api/v1/escalation.py, api/ws/ | 1.5j |
| 🅱 | CAMPAGNE.2 + CAMPAGNE.3 — Service + Worker campagnes | services/campaign/, workers/campaign.py | 1.5j |
| 🅲 | APPRENTISSAGE.2 + APPRENTISSAGE.3 — Worker réinjection + API | workers/learning.py, api/v1/learning.py | 1j |

**Dépendances :** Wave 15 (services métier)

#### ESCALADE.4 + ESCALADE.5 — WebSocket + API
**Résumé :** Endpoint WebSocket FastAPI `/ws/escalations/{tenant_slug}` : auth JWT via query param, Redis pub/sub channel `{slug}:escalations:updates`, push temps réel des nouvelles escalades et mises à jour de statut. API REST : GET /escalations (list, filtres status/priority/assigned_to, pagination), GET /escalations/{id} (détail + historique conversation + résumé contexte), POST /escalations/{id}/assign (auto-assign au superviseur connecté), POST /escalations/{id}/respond (envoie message via WhatsApp API du tenant, le message apparaît dans la conversation comme venant du même numéro), POST /escalations/{id}/close (résolution + notes + retour mode auto conversation). RBAC : supervisor + admin_tenant uniquement.
**Fichiers :** `backend/app/api/v1/escalation.py`, `backend/app/api/ws/escalation_ws.py`, `backend/app/api/ws/__init__.py`

#### CAMPAGNE.2 + CAMPAGNE.3 — Service + Worker
**Résumé :** `CampaignService` : create_campaign(data, admin_id), build_audience(filter_criteria) → count + preview contacts, map_variables(template, contacts) → preview messages, schedule_campaign(campaign_id, scheduled_at), start_campaign(campaign_id), pause_campaign(campaign_id), get_campaign_stats(campaign_id). Worker ARQ `send_campaign` : récupère les destinataires pending, envoie via WhatsApp API du tenant avec gestion débit (max 80 msg/s conformément aux limites Meta BSP), met à jour le statut de chaque recipient, incrémente le compteur quota tenant (clé Redis `{slug}:whatsapp:quota`), alerte si quota > 80% ou 95%. Stats temps réel : sent, delivered, read, clicked, failed — agrégées dans campaign.stats JSONB.
**Fichiers :** `backend/app/services/campaign/service.py`, `backend/app/workers/campaign.py`, `backend/app/services/campaign/__init__.py`

#### APPRENTISSAGE.2 + APPRENTISSAGE.3 — Worker + API
**Résumé :** Worker ARQ `reinject_approved_question` : prend une question approuvée → génère un chunk formaté (question + réponse validée) → appelle EmbeddingService pour embed → indexe dans Qdrant collection du tenant → met à jour le statut en "reinjected" → log dans audit trail. API REST : GET /learning/questions (list, filtres status/date, pagination), GET /learning/questions/{id} (détail + conversation source + chunks corrélés), POST /learning/questions/{id}/generate (déclenche génération proposition IA), POST /learning/questions/{id}/approve (avec réponse finale optionnelle, déclenche worker réinjection), POST /learning/questions/{id}/reject (avec raison), PUT /learning/questions/{id}/edit (modification de la proposition), GET /learning/stats (métriques apprentissage). RBAC : supervisor + admin_tenant.
**Fichiers :** `backend/app/workers/learning.py`, `backend/app/api/v1/learning.py`

```
📌 COMMIT : git commit -m "feat: Wave 16 — WebSocket, campaign worker, learning API & worker"
📌 PUSH : git push
```

---

### ╔══════════════════════════════════════════════════════╗
### ║  WAVE 17 — Contacts enrichis + APIs restantes (3 ag.) ║
### ╚══════════════════════════════════════════════════════╝

| Agent | Prompt | Fichiers | Durée |
|-------|--------|----------|-------|
| 🅰 | CONTACTS.2 + CONTACTS.3 — Service + API contacts enrichis | services/contacts/, api/v1/contacts.py | 1.5j |
| 🅱 | INTERNE.4 + CAMPAGNE.4 — API whitelist + API campagnes | api/v1/whitelist.py, api/v1/campaigns.py | 1j |
| 🅲 | INTEGRATION.2 — Mise à jour graphe LangGraph v2 complet | services/orchestrator/graph.py | 1j |

**Dépendances :** Wave 16 (WebSocket, workers)

#### CONTACTS.2 + CONTACTS.3 — CRM complet
**Résumé :** Enrichissement du service contacts Phase 1 : segmentation automatique (règles configurables par tenant : "investisseur actif" si dossier en_cours, "inactif > 6 mois" si dernière interaction > 180j), gestion tags avancée (ajout/suppression batch, autocomplete), import Excel amélioré (wizard 3 étapes : upload → mapping colonnes → preview + validation, dédoublonnage sur phone E.164, rapport d'import), export Excel filtré (par segment, tag, statut opt-in, période), conformité CNDP complète (opt-out via "STOP" détecté par orchestrateur, journal de consentement avec dates/sources, exclusion auto des opt-out dans campagnes et notifications). API : GET /contacts (recherche full-text nom+phone+CIN+tags, filtres facettes, pagination), POST /contacts/import (upload Excel + mapping), GET /contacts/export (Excel filtré), PUT /contacts/{id}/tags (batch update), GET /contacts/{id}/history (historique interactions).
**Fichiers :** `backend/app/services/contacts/service.py` (enrichissement), `backend/app/api/v1/contacts.py` (enrichissement)

#### INTERNE.4 + CAMPAGNE.4 — APIs restantes
**Résumé :** API Whitelist : GET /internal/whitelist (list), POST /internal/whitelist (ajouter numéro), DELETE /internal/whitelist/{id} (retirer), PUT /internal/whitelist/{id}/toggle (activer/désactiver). RBAC : admin_tenant uniquement. API Campagnes : GET /campaigns (list + stats), POST /campaigns (create), GET /campaigns/{id} (détail + stats), POST /campaigns/{id}/start, POST /campaigns/{id}/pause, POST /campaigns/{id}/audience-preview (count + échantillon), GET /campaigns/{id}/recipients (list paginée avec statut), GET /campaigns/{id}/export (stats Excel). RBAC : admin_tenant + gestionnaire_campagnes.
**Fichiers :** `backend/app/api/v1/whitelist.py`, `backend/app/api/v1/campaigns.py`

#### INTEGRATION.2 — Graphe LangGraph v2
**Résumé :** Mise à jour du graphe LangGraph assemblé en Wave 8 : ajout des nœuds InternalAgent et EscalationHandler. Nouvelles transitions : Router → InternalAgent (si intent "internal" ET agent_type peut être "internal"), Router → EscalationHandler (si intent "escalade" OU détection automatique via EscalationService.detect_escalation()). L'EscalationHandler peut aussi être invoqué depuis FAQAgent (échec RAG répété) et FeedbackCollector (👎 + "parler agent"). Mise à jour du ConversationState avec champs : `escalation_id`, `is_internal_user`, `consecutive_low_confidence`. Test E2E : message WhatsApp d'un numéro whitelisté → InternalAgent → réponse lecture seule. Message avec demande escalade → EscalationHandler → notification WebSocket.
**Fichiers :** `backend/app/services/orchestrator/graph.py` (modification majeure), `backend/app/services/orchestrator/state.py` (ajout champs)

```
📌 COMMIT : git commit -m "feat: Wave 17 — CRM complete, whitelist/campaign APIs, LangGraph v2"
📌 PUSH : git push
```

---

### ╔══════════════════════════════════════════════════════╗
### ║  WAVE 18 — Back-office pages batch 1 (3 agents)       ║
### ╚══════════════════════════════════════════════════════╝

| Agent | Prompt | Fichiers | Durée |
|-------|--------|----------|-------|
| 🅰 | BO.7 — Page Analytics & Rapports [DESIGN §6.6] | frontend/src/app/(dashboard)/analytics/ | 1.5j |
| 🅱 | BO.8 — Page Campagnes [DESIGN §6.5] | frontend/src/app/(dashboard)/campaigns/ | 1.5j |
| 🅲 | BO.9 — Page Utilisateurs + RBAC + Whitelist [DESIGN §6.8] | frontend/src/app/(dashboard)/users/ | 1j |

**Dépendances :** Wave 17 (APIs backend fonctionnelles), BO.5/BO.6 Phase 1 (API client typé)

#### BO.7 — Analytics & Rapports [DESIGN]
**Résumé :** Page avec 5 tabs (Vue d'ensemble, Conversations, Base de connaissances, WhatsApp, Dossiers). Tab Vue d'ensemble : 4 KPI cards (conversations total, messages total, taux résolution, CSAT moyen) avec sparklines, Line chart Recharts évolution mensuelle multi-séries (terracotta/sable), Bar chart langues, Donut chart types de questions, Table top 10 questions fréquentes. Sélecteur de période (7j, 30j, 90j, custom). Export PDF via react-pdf et Excel via SheetJS. Palette graphiques : terracotta #C4704B, sable #D4A574, olive #7A8B5F, info #5B7A8B. TanStack Query pour fetch données. Design system Modern Warm strict.
**Fichiers :** `frontend/src/app/(dashboard)/analytics/page.tsx`, `frontend/src/components/analytics/`, `frontend/src/lib/api/analytics.ts`

#### BO.8 — Campagnes [DESIGN]
**Résumé :** Table campagnes (TanStack Table) : nom, template, audience, statut badge, envoyés/lus, date, actions dropdown. Wizard création 4 étapes (composant Stepper horizontal, étape active terracotta) : 1) Sélection template WhatsApp (dropdown + preview bulle style WhatsApp), 2) Audience (sélecteur segments/tags avec compteur contacts temps réel), 3) Mapping variables + preview message final, 4) Planification (immédiat ou DatePicker) + confirmation. Détail campagne : cards KPI (envoyés, délivrés, lus, cliqués) + Funnel chart (dégradé terracotta→sable). React Hook Form + Zod validation.
**Fichiers :** `frontend/src/app/(dashboard)/campaigns/page.tsx`, `frontend/src/app/(dashboard)/campaigns/new/page.tsx`, `frontend/src/components/campaigns/`

#### BO.9 — Utilisateurs + Whitelist [DESIGN]
**Résumé :** Table utilisateurs (TanStack Table) : nom, email, rôle badge, statut, dernière connexion, actions. Modal création : email + dropdown rôle (Super-Admin Tenant, Gestionnaire KB, Superviseur, Analyste, Gestionnaire Campagnes) + message invitation. Max 10 admins par tenant (compteur visible). Section séparée "Whitelist Agent Interne" : table numéros (téléphone, nom, date ajout, toggle actif/inactif, supprimer). Bouton "+Ajouter numéro" → modal avec input téléphone (validation E.164) + nom.
**Fichiers :** `frontend/src/app/(dashboard)/users/page.tsx`, `frontend/src/components/users/`

```
📌 COMMIT : git commit -m "feat: Wave 18 — Backoffice analytics, campaigns, users pages"
📌 PUSH : git push
```

---

### ╔══════════════════════════════════════════════════════╗
### ║  WAVE 19 — Back-office pages batch 2 (3 agents)       ║
### ╚══════════════════════════════════════════════════════╝

| Agent | Prompt | Fichiers | Durée |
|-------|--------|----------|-------|
| 🅰 | BO.10 — Page Escalade temps réel [DESIGN §6.2 enrichi] | frontend/src/app/(dashboard)/escalations/ | 1.5j |
| 🅱 | BO.11 — Page Apprentissage supervisé [DESIGN §6.3 enrichi] | frontend/src/app/(dashboard)/knowledge/ | 1j |
| 🅲 | BO.12 — Back-office Super-Admin [DESIGN §6.11] | frontend/src/app/(super-admin)/ | 1.5j |

**Dépendances :** Wave 18 (pages de base), Wave 16 (WebSocket endpoint)

#### BO.10 — Escalade temps réel [DESIGN]
**Résumé :** File d'attente des escalades : tableau temps réel (connexion WebSocket `ws/escalations/{slug}`) trié par priorité + ancienneté. Chaque ligne : contact, déclencheur badge, priorité badge coloré (rouge/orange/bleu), temps d'attente, statut, bouton "Prendre en charge". Vue conversationnelle (master-detail §6.2) : panneau gauche = liste escalades, panneau droit = historique complet conversation (bulles style WhatsApp), résumé contextuel IA en bannière, input réponse en bas avec suggestions IA (chips cliquables Gemini), bouton envoyer → appel API respond_via_whatsapp. Indicateur clignotant rouge pour nouvelles escalades. Notifications sonores optionnelles. Stats : temps moyen prise en charge, taux résolution, volume par scénario.
**Fichiers :** `frontend/src/app/(dashboard)/escalations/page.tsx`, `frontend/src/components/escalations/`, `frontend/src/lib/hooks/useEscalationWebSocket.ts`

#### BO.11 — Apprentissage supervisé [DESIGN]
**Résumé :** Nouveau tab "Questions non couvertes" dans la page KB existante (BO.3). Table : question originale, fréquence (nb occurrences), proposition IA, statut badge (pending/approved/rejected), date, actions. Vue détail (Sheet latéral) : question complète, conversation source, chunks RAG corrélés (si disponibles), proposition IA générée (éditable dans un textarea), boutons d'action : Valider (vert ✅, approuve + déclenche réinjection Qdrant), Rejeter (rouge ❌, avec input raison obligatoire), Éditer (terracotta ✏️, ouvre l'éditeur puis valide). Bouton "Générer proposition IA" pour les questions sans proposition. Compteurs KPI en haut : pending, approved cette semaine, rejected, taux de couverture KB.
**Fichiers :** Modification `frontend/src/app/(dashboard)/knowledge/page.tsx`, `frontend/src/components/knowledge/learning-tab.tsx`, `frontend/src/components/knowledge/question-detail.tsx`

#### BO.12 — Super-Admin [DESIGN]
**Résumé :** Layout distinct du back-office tenant : sidebar avec logo plateforme (pas tenant), navigation Tenants | Monitoring | Configuration | Logs d'audit. Badge "Super-Admin" dans topbar. Page Tenants : table (nom CRI, slug, statut badge, messages utilisés/quota, contacts, date création, actions). Wizard création tenant 3 étapes : 1) Infos (nom, slug, région), 2) Config WhatsApp (phone_number_id, access_token masqué), 3) Personnalisation (logo upload, couleur accent) + Review → POST /tenants/provision. Page Monitoring : santé de chaque tenant (cards avec indicateurs vert/rouge), consommation ressources. Page Logs d'audit : table read-only des audit_logs avec filtres (tenant, user, action, date). Accessible uniquement aux super_admin (guard de route).
**Fichiers :** `frontend/src/app/(super-admin)/layout.tsx`, `frontend/src/app/(super-admin)/tenants/page.tsx`, `frontend/src/app/(super-admin)/monitoring/page.tsx`, `frontend/src/app/(super-admin)/audit/page.tsx`, `frontend/src/components/super-admin/`

```
📌 COMMIT : git commit -m "feat: Wave 19 — Escalation UI, learning UI, super-admin backoffice"
📌 PUSH : git push
```

---

### ╔══════════════════════════════════════════════════════╗
### ║  WAVE 20 — Intégration E2E Phase 2 (1 agent)          ║
### ╚══════════════════════════════════════════════════════╝

| Agent | Prompt | Fichiers | Durée |
|-------|--------|----------|-------|
| 🅰 | INTEGRATION.2 — Tests E2E Phase 2 complets | backend/tests/test_e2e_phase2.py | 1.5j |

**Dépendances :** Wave 19 (toutes fonctionnalités Phase 2)

#### INTEGRATION.2 — Flux E2E Phase 2
**Résumé :** Scénarios de test end-to-end :
1. **Agent interne** : Message WhatsApp d'un numéro whitelisté → IntentDetector détecte "internal" → InternalAgent → réponse stats/dossier. Message d'un numéro NON whitelisté avec intent interne → refus poli.
2. **Escalade automatique** : 3 questions FAQ consécutives avec score confiance < 0.5 → EscalationHandler déclenché → escalation créée → WebSocket notification → assign → respond via WhatsApp → close → retour mode auto.
3. **Escalade manuelle** : Utilisateur écrit "je veux parler à un agent" → détection intent escalade → même flux.
4. **Apprentissage supervisé** : Question FAQ → score < seuil → UnansweredQuestion créée → API generate proposal → API approve → Worker réinjection → vérification chunk dans Qdrant.
5. **Campagne** : Création campagne → audience preview → start → Worker envoie → stats mises à jour → vérification quota.
6. **Sécurité** : Vérification audit trail (actions loggées), KMS (encrypt/decrypt round-trip), sessions (changement IP → déconnexion).
**Fichiers :** `backend/tests/test_e2e_phase2.py`, `backend/tests/conftest_phase2.py`

```
📌 COMMIT : git commit -m "test: Wave 20 — End-to-end integration tests Phase 2"
📌 PUSH : git push
```

---

### ╔══════════════════════════════════════════════════════╗
### ║  WAVE 21 — Tests + Documentation (2 agents)           ║
### ╚══════════════════════════════════════════════════════╝

| Agent | Prompt | Fichiers | Durée |
|-------|--------|----------|-------|
| 🅰 | TEST.3 — Tests unitaires complets Phase 2 | backend/tests/ | 1.5j |
| 🅱 | DOCS.1 — Documentation Phase 2 + mise à jour CI/CD | docs/, .github/workflows/ | 1j |

**Dépendances :** Wave 20

#### TEST.3 — Tests unitaires Phase 2
**Résumé :** Tests par module :
- **Interne** : whitelist CRUD, vérification accès autorisé/refusé, InternalAgent node en isolation
- **Escalade** : détection des 6 scénarios, création/assignation/résolution, WebSocket message format, EscalationHandler node
- **Apprentissage** : génération proposition IA, workflow approve/reject/edit, réinjection Qdrant (mock)
- **Campagne** : audience builder, variable mapping, quota check, worker envoi (mock WhatsApp)
- **Sécurité** : audit trail INSERT ONLY (tentative UPDATE/DELETE → erreur), KMS encrypt/decrypt round-trip, session IP change detection, archivage SHA-256 vérification
- **Contacts** : segmentation, import Excel dédoublonnage, opt-out STOP, export filtré
- **Isolation multi-tenant** : escalade tenant A invisible pour tenant B, campagne scopée au tenant
**Fichiers :** `backend/tests/test_internal.py`, `backend/tests/test_escalation.py`, `backend/tests/test_learning.py`, `backend/tests/test_campaign.py`, `backend/tests/test_security_p2.py`, `backend/tests/test_contacts_p2.py`

#### DOCS.1 — Documentation Phase 2
**Résumé :** Mise à jour `docs/` : API reference Phase 2 (OpenAPI auto-gen), guide utilisateur escalade, guide utilisateur campagnes, guide super-admin. Mise à jour CI/CD GitHub Actions pour inclure les tests Phase 2. Mise à jour docker-compose.yml si nouveaux services (WebSocket). README.md mis à jour avec les fonctionnalités Phase 2.
**Fichiers :** `docs/phase2-api.md`, `docs/guide-escalade.md`, `docs/guide-campagnes.md`, `docs/guide-super-admin.md`, mise à jour `.github/workflows/ci.yml`

```
📌 COMMIT : git commit -m "test: Wave 21 — Unit tests Phase 2, documentation, CI/CD update"
📌 PUSH : git push
📌 TAG : git tag v0.2.0-phase2
```

---

## 📅 PLANNING SEMAINE PAR SEMAINE

| Semaine | Waves | Prompts | Focus |
|---------|-------|---------|-------|
| S9 | 13, 14 | Modèles P2, Sécurité durcissement | Fondations + sécurité |
| S10 | 15 | Services interne, escalade, apprentissage | Services métier core |
| S11 | 16 | WebSocket, workers, APIs | Communication temps réel + workers |
| S12 | 17 | Contacts enrichis, APIs restantes, LangGraph v2 | Assemblage backend complet |
| S13 | 18, 19 | Back-office pages (6 pages) | Frontend complet |
| S14 | 20, 21 | Tests E2E, tests unitaires, docs | Stabilisation + livraison |

---

## 🔗 DÉPENDANCES INTER-WAVES

```
Wave 13 (modèles) ──┬── Wave 14 (sécurité)
                     │
                     └── Wave 15 (services) ── Wave 16 (APIs/workers) ── Wave 17 (contacts/graphe)
                                                                              │
                                                                              └── Wave 18 (BO batch 1) ── Wave 19 (BO batch 2)
                                                                                                              │
                                                                                                              └── Wave 20 (E2E) ── Wave 21 (tests/docs)
```

**Note :** Les Waves 14 et 15 peuvent se chevaucher partiellement si Wave 13 est terminée rapidement (les services Wave 15 n'ont besoin de l'audit trail Wave 14 que pour le logging, pas pour leur logique core).

---

## ⚡ RÈGLES D'EXÉCUTION (identiques Phase 1)

1. **Toujours `git commit` entre chaque Wave** — c'est ton filet de sécurité
2. **Ne JAMAIS passer à la Wave N+1 si la Wave N a des tests qui échouent**
3. **Max 3 agents parallèles** — au-delà, risque de conflits de merge
4. **Si un prompt échoue** → coller l'erreur dans Claude AI → recevoir un prompt correctif
5. **Docker doit tourner** (hérité de Phase 1)
6. **Le front (BO.*) peut avancer indépendamment** du backend tant qu'il utilise des mocks
7. **[SÉCU]** = inclure les mesures de l'annexe sécurité dans le prompt
8. **[DESIGN]** = inclure le wireframe + CSS variables de l'annexe design dans le prompt

---

## 🔄 COMMENT UTILISER CE DOCUMENT

1. **Trouve la prochaine Wave** à exécuter (la première avec status ⬜)
2. **Pour chaque prompt de la Wave** : demande-moi "Génère le prompt ESCALADE.2" (ou autre)
3. **Je te génère le prompt complet** avec tout le contexte embarqué
4. **Tu le copies dans Claude Code** (terminal yolo + /plan)
5. **Claude Code exécute**, tu vérifies le smoke test
6. **Tu commit + push** selon les points 📌 indiqués
7. **Wave suivante !**

Ou tu peux me demander : "Génère tous les prompts de la Wave 15" et je te les produis d'un coup.

---

## 📊 RÉCAPITULATIF DES MESURES SÉCURITÉ PHASE 2

| Mesure | Prompt | Effort estimé |
|--------|--------|---------------|
| Audit trail append-only (INSERT ONLY, archivage signé SHA-256) | SECURITE.1 | 2j |
| KMS logiciel + clé AES-256 par tenant (master key en env) | SECURITE.2 | 3j |
| Gestion sessions avancée (IP check, session unique, alertes) | SECURITE.3 | 1.5j |
| Archivage signé MinIO (cron hebdo SHA-256) | SECURITE.4 | 1j |
| **Total effort sécurité Phase 2** | | **~9.5 jours-homme** |

---

## 📐 NŒUDS LANGGRAPH AJOUTÉS EN PHASE 2

| Nœud | Intent | Rôle | Déclenchement |
|------|--------|------|---------------|
| InternalAgent | `internal` | Lecture seule dossiers, stats, rapports (whitelist) | IntentDetector détecte intent + numéro whitelisté |
| EscalationHandler | `escalade` | 6 scénarios d'escalade + transfert humain | Intent explicite OU détection auto (échec RAG, sujet sensible, etc.) |

**Graphe LangGraph v2 :**
```
[IntentDetector] → [Router] → [FAQAgent | IncentivesAgent | InternalAgent | EscalationHandler]
                                    ↓
                            [ResponseValidator] → [FeedbackCollector] → Réponse WhatsApp
                                                        ↓ (si 👎 + "parler agent")
                                                  [EscalationHandler]
```
