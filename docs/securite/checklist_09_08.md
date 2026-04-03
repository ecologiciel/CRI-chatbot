# Checklist de Conformité — Loi n° 09-08

> **Plateforme CRI Chatbot Multi-Tenant RAG**
> Appel d'Offres N° 02/2026/CRI RSK — Client initial : CRI Rabat-Salé-Kénitra
> **Date de l'audit** : 2 avril 2026
> **Version** : 1.0
> **Référentiel** : Loi n° 09-08 relative à la protection des personnes physiques à l'égard du traitement des données à caractère personnel

---

## Résumé exécutif

| Indicateur | Valeur |
|------------|--------|
| Articles applicables | 9 |
| ✅ Conformes | 3 |
| ⚠️ Partiellement conformes | 5 |
| ❌ Non conformes | 1 |
| Non applicables | 0 |

**Score global : 3/9 pleinement conformes, 5/9 partiellement conformes (mesures techniques en place, actions complémentaires requises), 1/9 en attente (déclaration CNDP non encore déposée).**

### Synthèse des actions prioritaires

| Priorité | Action | Article | Délai recommandé |
|----------|--------|---------|-------------------|
| 🔴 Critique | Déposer la déclaration préalable CNDP | Art. 12 | Avant mise en production |
| 🟠 Haute | Signer un DPA avec Google (Gemini API) | Art. 15, 24 | Avant mise en production |
| 🟠 Haute | Signer un DPA avec Nindohost | Art. 24 | Avant mise en production |
| 🟡 Moyenne | Implémenter un avis de confidentialité au premier contact WhatsApp | Art. 9 | Sprint suivant |
| 🟡 Moyenne | Ajouter les mots-clés arabes au mécanisme STOP | Art. 9 | Sprint suivant |
| 🟡 Moyenne | Automatiser la purge des conversations (90 jours) | Art. 3 | Avant mise en production |
| 🔵 Basse | Désigner formellement un DPO | Recommandation | 3 mois post-MEP |

---

## Article 3 — Conditions de licéité des traitements

### 3.1 Finalité déterminée, explicite et légitime

- **Statut** : ✅ CONFORME
- **Mesure** : La plateforme sert exclusivement l'accompagnement des investisseurs dans le cadre de la mission légale des CRI (loi 47-18 portant réforme des CRI). Les traitements se limitent à : réponses aux questions sur les procédures, information sur les incitations, suivi des dossiers d'investissement, notifications proactives de changement de statut.
- **Preuve** : Architecture conversationnelle définie dans `backend/app/services/ai/orchestrator.py` — le graphe LangGraph route exclusivement vers les agents FAQ, Incitations, Suivi et Interne. Toute intention hors-périmètre est détectée et rejetée par l'`InputGuardService` (`backend/app/services/guardrails/input_guard.py`).
- **Recommandation** : Aucune.

### 3.2 Pertinence et non-excès des données collectées

- **Statut** : ✅ CONFORME
- **Mesure** : Collecte minimale — seul le numéro de téléphone WhatsApp est collecté automatiquement. Le nom est optionnel (fourni par l'utilisateur). Le CIN n'est collecté que lors de l'authentification OTP pour le suivi de dossier (cas d'usage explicite).
- **Preuve** :
  - Modèle Contact (`backend/app/models/contact.py:33-45`) : `phone` obligatoire, `name` nullable, `cin` nullable.
  - Le CIN est demandé uniquement dans le flux TrackingAgent (`backend/app/services/dossier/otp.py`), pas dans les flux FAQ ou Incitations.
- **Recommandation** : Aucune.

### 3.3 Conservation limitée dans le temps

- **Statut** : ⚠️ PARTIELLEMENT CONFORME
- **Mesure** : Les durées de conservation sont définies dans l'architecture :
  - Messages conversationnels : 90 jours
  - Logs d'audit : 12 mois PostgreSQL + 24 mois MinIO
  - OTP : 5 minutes (TTL Redis, auto-purgé)
  - Sessions dossier : 30 minutes (TTL Redis, auto-purgé)
  - Dossiers d'investissement : durée légale applicable
- **Preuve** :
  - OTP TTL : `backend/app/services/dossier/otp.py` — `OTP_TTL = 300`, `SESSION_TTL = 1800`
  - Audit rétention : `backend/app/models/audit.py` — commentaire "12 months PostgreSQL, 24 months archived on MinIO"
  - Message dedup TTL : `backend/app/services/whatsapp/handler.py` — `DEDUP_TTL = 86400`
- **Écart** : Les durées de conservation sont définies mais **aucun mécanisme automatisé** (cron job, worker ARQ) ne purge les conversations après 90 jours.
- **Recommandation** : Implémenter un worker de purge automatique des messages et conversations expirés. Ajouter un job cron dans le scheduler ARQ.

### 3.4 Exactitude et mise à jour des données

- **Statut** : ✅ CONFORME
- **Mesure** : Les données dossiers sont mises à jour par import périodique (Excel/CSV). L'historique des modifications est tracé dans `dossier_history` (append-only). Les contacts sont enrichis progressivement (nom, langue, CIN).
- **Preuve** :
  - Import worker : `backend/app/workers/import_worker.py`
  - Historique : `backend/app/models/dossier.py` — classe `DossierHistory` avec `field_changed`, `old_value`, `new_value`
  - Service notification : `backend/app/services/notification/service.py` — notifications de changement de statut (données à jour)
- **Recommandation** : Aucune.

---

## Article 7 — Droit d'accès

- **Statut** : ⚠️ PARTIELLEMENT CONFORME
- **Mesure** : Les personnes concernées peuvent accéder à leurs données via deux canaux :
  1. **Via le chatbot** : Le module TrackingAgent permet la consultation des données de dossier après authentification OTP.
  2. **Via le back-office** : Les administrateurs CRI peuvent consulter et exporter les données d'un contact.
- **Preuve** :
  - TrackingAgent : `backend/app/services/dossier/otp.py` — consultation dossier après vérification OTP
  - Back-office API : endpoints CRUD contacts et dossiers (`backend/app/api/v1/`)
- **Écart** : Pas de commande WhatsApp dédiée type « MES DONNÉES » permettant à l'utilisateur de recevoir un export complet de ses données personnelles (portabilité). L'accès aux données de dossier existe mais pas l'accès à l'ensemble des données personnelles détenues.
- **Recommandation** : Documenter la procédure manuelle d'exercice du droit d'accès via l'accueil CRI. En Phase 4, envisager une commande chatbot « MES DONNÉES » générant un export.

---

## Article 8 — Droit de rectification

- **Statut** : ⚠️ PARTIELLEMENT CONFORME
- **Mesure** : La rectification des données personnelles est possible via :
  1. **Back-office** : Les administrateurs CRI (rôles `admin_tenant` et `supervisor`) peuvent modifier les fiches contact (nom, CIN, tags, opt-in).
  2. **Import** : Les mises à jour de dossiers par import Excel/CSV écrasent les valeurs obsolètes avec traçabilité `DossierHistory`.
- **Preuve** :
  - Service Contact : `backend/app/services/contact/service.py` — `ContactService.update_contact()`
  - RBAC : `backend/app/core/rbac.py` — `require_role()` vérifie les autorisations de modification
  - Historique : `backend/app/models/dossier.py` — `DossierHistory` trace chaque modification
- **Écart** : Pas de mécanisme self-service via WhatsApp pour que l'utilisateur corrige lui-même ses données. La rectification passe par un agent CRI.
- **Recommandation** : Documenter la procédure de rectification dans la politique de confidentialité (contacter le CRI par email/téléphone). Suffisant pour un contexte B2G.

---

## Article 9 — Droit d'opposition et information des personnes

### 9.1 Information au moment de la collecte

- **Statut** : ⚠️ PARTIELLEMENT CONFORME
- **Mesure** : La politique de confidentialité est rédigée (documents 4 et 5 de ce livrable). La commande « STOP » est fonctionnelle et envoie un message de confirmation.
- **Preuve** :
  - STOP keywords : `backend/app/services/contact/segmentation.py:28-37` — 6 mots-clés reconnus
  - Traitement STOP : `backend/app/services/whatsapp/handler.py:142-150` — détection et routage
  - Confirmation multilingue : `backend/app/services/contact/segmentation.py` — `process_stop_command()` envoie une confirmation FR/AR/EN
- **Écart** : **Aucun message de notification de confidentialité n'est envoyé au premier contact WhatsApp.** La loi exige que la personne soit informée de la collecte et de ses droits « au moment de la collecte ».
- **Recommandation** : Créer un template WhatsApp Meta pré-approuvé contenant un résumé de la politique de confidentialité. L'envoyer automatiquement au premier message reçu d'un nouveau contact.

### 9.2 Droit d'opposition (opt-out)

- **Statut** : ⚠️ PARTIELLEMENT CONFORME
- **Mesure** : Le mécanisme STOP est pleinement fonctionnel. L'envoi du mot « STOP » (ou variantes) met à jour `opt_in_status` à `opted_out`, exclut le contact des campagnes et notifications, et génère un audit log.
- **Preuve** :
  - Keywords : `{"stop", "arreter", "arrêter", "desabonner", "désabonner", "unsubscribe"}` — `segmentation.py:28-37`
  - Audit : action `opt_in_change` avec `details={"source": "user_stop"}`
  - Exclusion campagnes : `backend/app/services/campaign/service.py` — filtre `opt_in_status != opted_out`
  - Exclusion notifications : `backend/app/services/notification/service.py` — vérification opt-in avant envoi
- **Écart** : **Aucun mot-clé arabe** dans le frozenset `STOP_KEYWORDS`. Un utilisateur arabophone ne peut pas exercer son droit d'opposition dans sa langue. Mots-clés manquants : « توقف » (tawaquf), « إلغاء » (ilghaa), « الغاء ».
- **Recommandation** : Ajouter les mots-clés arabes au frozenset dans `segmentation.py`. Changement de code minimal (~3 lignes).

---

## Article 12 — Déclaration préalable à la CNDP

- **Statut** : ❌ NON CONFORME (en attente)
- **Mesure** : La loi 09-08 exige une déclaration préalable auprès de la CNDP avant tout traitement de données personnelles. Cette déclaration n'a pas encore été déposée.
- **Action requise** : Le template de déclaration est préparé (Document 3 — `declaration_cndp_template.md`). Le CRI doit le compléter avec ses informations spécifiques (adresse, représentant légal, DPO) et le soumettre à la CNDP **avant la mise en production**.
- **Preuve** : Template pré-rempli disponible dans `docs/securite/declaration_cndp_template.md`
- **Recommandation** : Soumettre la déclaration dès que possible. Délai de traitement CNDP : généralement 2-4 semaines.

---

## Article 15 — Transfert de données vers l'étranger

- **Statut** : ⚠️ PARTIELLEMENT CONFORME
- **Mesure** : La plateforme utilise l'API Google Gemini 2.5 Flash (infrastructure cloud Google, serveurs hors Maroc) pour la génération de réponses et la classification d'intention. Cependant, **aucune donnée personnelle identifiable n'est transmise** à Gemini grâce à un pipeline d'anonymisation systématique.

### Pipeline d'anonymisation pré-Gemini

| Étape | Fichier | Patterns supprimés |
|-------|---------|-------------------|
| 1. Anonymisation des chunks RAG | `backend/app/services/rag/generation.py:259-288` | CIN → `[CIN]`, Phone → `[TELEPHONE]`, Email → `[EMAIL]`, Montants → `[MONTANT]` |
| 2. Masquage PII pré-envoi | `backend/app/services/guardrails/pii_masker.py` | CIN, Phone, Email, IBAN, Montants MAD/DH, N° dossier (6 patterns) |
| 3. Validation post-LLM | `backend/app/services/guardrails/output_guard.py` | Re-vérification PII dans la réponse générée |

- **Preuve** :
  - Code d'anonymisation : `generation.py:259-272` — `_anonymize_text()` appliqué à tous les chunks avant construction du prompt
  - Test PII : `backend/tests/test_pii_masker.py` et `backend/tests/unit/test_pii_masker.py` — ~20 tests vérifiant la détection des patterns marocains
  - Test no-PII dans logs : `backend/tests/test_gemini_service.py:211-229` — vérifie qu'aucun PII n'apparaît dans les logs Gemini
  - Suivi de dossier : opère 100% en local (PostgreSQL) sans appel LLM pour l'accès aux données

- **Argument juridique** : Puisque les données sont anonymisées avant transmission, les informations envoyées à Gemini ne constituent pas des « données à caractère personnel » au sens de l'article 1er de la loi 09-08. Par conséquent, l'article 15 ne s'applique pas strictement. Toutefois, par mesure de précaution :
  - Google Gemini API (offre payante) ne réutilise pas les données pour l'entraînement de ses modèles
  - Les prompts ne contiennent que du texte anonymisé + instructions système

- **Recommandation** :
  1. Mentionner l'usage de Gemini dans la déclaration CNDP (transparence)
  2. Signer un Data Processing Agreement (DPA) avec Google
  3. Documenter le pipeline d'anonymisation dans un registre des traitements

---

## Article 21 — Obligation de confidentialité

- **Statut** : ✅ CONFORME
- **Mesure** : Plusieurs couches de confidentialité sont implémentées :

| Mesure | Détail | Preuve |
|--------|--------|--------|
| RBAC strict | 4 rôles (super_admin, admin_tenant, supervisor, viewer) avec whitelist d'actions | `backend/app/core/rbac.py` |
| Authentification forte | bcrypt cost factor 12, JWT 30min, refresh token rotation usage unique | `backend/app/services/auth/service.py` |
| Session unique | Un seul token actif par admin, détection changement IP | `backend/app/services/auth/session_manager.py` |
| Audit trail immuable | Table `audit_logs` INSERT ONLY (politique SQL), archivage signé SHA-256 | `backend/scripts/apply_audit_policy.sql` |
| KMS par tenant | Chiffrement enveloppe AES-256-GCM, clé par tenant, master key en env | `backend/app/services/crypto/kms.py` |
| Politique mots de passe | 12+ caractères, complexité, check 10 000 mots de passe courants | `backend/app/services/auth/service.py` |

- **Recommandation** : Aucune.

---

## Article 23 — Mesures de sécurité

- **Statut** : ✅ CONFORME
- **Mesure** : La plateforme implémente des mesures de sécurité techniques et organisationnelles conformes à l'état de l'art :

### Chiffrement

| Couche | Technologie | Preuve |
|--------|-------------|--------|
| En transit | TLS 1.3 via Traefik (Let's Encrypt) | `docker/traefik/traefik.yml` |
| Au repos (DB) | pgcrypto pour champs sensibles | Configuration PostgreSQL |
| Au repos (fichiers) | SSE-S3 MinIO | Configuration MinIO |
| Par tenant | AES-256-GCM, clé par tenant, rotation planifiable | `backend/app/services/crypto/kms.py` |

### Contrôle d'accès

| Mesure | Configuration | Preuve |
|--------|--------------|--------|
| Rate limiting webhook | 50 req/min/tenant | `backend/app/services/whatsapp/webhook.py` |
| Rate limiting utilisateur | 10 msg/min/user | `backend/app/services/whatsapp/handler.py` |
| Anti-bruteforce OTP | 3 tentatives/15 min | `backend/app/services/dossier/otp.py` |
| Anti-bruteforce login | 5 échecs/15 min → blocage 30 min | `backend/app/services/auth/service.py` |
| HMAC webhook | Signature SHA-256 sur tous les webhooks WhatsApp | `backend/app/services/whatsapp/webhook.py` |

### Isolation réseau

| Réseau Docker | Services | Accès |
|--------------|----------|-------|
| `cri-frontend` | Traefik, Frontend | Ports 80/443 uniquement |
| `cri-backend` | PostgreSQL, Redis, Qdrant, MinIO, Backend | `internal: true` (aucun accès Internet direct en production) |

- **Preuve réseau** : `docker-compose.prod.yml` — réseau `cri-backend` avec `internal: true`

### Isolation multi-tenant (5 niveaux)

| Composant | Isolation | Pattern |
|-----------|-----------|---------|
| PostgreSQL | Schéma par tenant | `tenant_{slug}` |
| Qdrant | Collection par tenant | `kb_{slug}` |
| Redis | Préfixe par tenant | `{slug}:` |
| MinIO | Bucket par tenant | `cri-{slug}` |
| WhatsApp | Config par tenant | `whatsapp_config` JSONB par tenant |

- **Preuve isolation** : `backend/app/core/tenant.py` — `TenantContext` dataclass immutable avec scoping automatique
- **Tests isolation** : 5 fichiers dans `backend/tests/isolation/` (~23 tests)

### Monitoring sécurité

| Alerte Prometheus | Seuil | Sévérité |
|-------------------|-------|----------|
| Flood WhatsApp | >50 msg/h/tenant | Warning |
| Bruteforce OTP coordonné | >20% échecs ET >5 tentatives/h | Critical |
| Anomalie coût Gemini | >2x moyenne 24h | Warning |

- **Preuve alertes** : `docker/prometheus/alert_rules.yml`

### Couverture de tests sécurité

- ~213 tests dédiés à la sécurité sur 15 fichiers de tests
- Répertoires : `backend/tests/security/` (5 fichiers), `backend/tests/isolation/` (5 fichiers), tests unitaires OTP/PII/KMS/Auth

- **Recommandation** : Aucune.

---

## Article 24 — Sous-traitance

- **Statut** : ⚠️ PARTIELLEMENT CONFORME
- **Mesure** : La plateforme fait appel à deux sous-traitants pour le traitement de données :

| Sous-traitant | Rôle | Données exposées | Garanties actuelles |
|---------------|------|-----------------|---------------------|
| **Nindohost** | Hébergeur (datacenter Maroc, ISO 9001:2015) | Toutes les données (hébergement physique) | Datacenter certifié, Maroc |
| **Google** (Gemini API) | Génération IA | Prompts anonymisés uniquement (aucun PII) | API payante, no-training policy |

- **Preuve** :
  - Nindohost : `docker-compose.prod.yml` — déploiement sur VPS Nindohost
  - Gemini anonymisation : `backend/app/services/rag/generation.py:259-288`
- **Écart** : Aucun Data Processing Agreement (DPA) formalisé avec Nindohost ou Google au moment de l'audit.
- **Recommandation** :
  1. Signer un DPA avec Nindohost couvrant : accès limité aux données, notification de brèche, mesures de sécurité, suppression en fin de contrat
  2. Signer un DPA avec Google pour l'usage de l'API Gemini (Google propose des DPA standard pour ses services cloud)
  3. Exiger de Nindohost un engagement contractuel de non-accès aux données hébergées

---

## Annexe — Tableau récapitulatif

| Article | Objet | Statut | Actions requises |
|---------|-------|--------|-----------------|
| Art. 3 | Licéité des traitements | ✅ Conforme | Automatiser la purge 90j |
| Art. 7 | Droit d'accès | ⚠️ Partiel | Documenter procédure manuelle |
| Art. 8 | Droit de rectification | ⚠️ Partiel | Documenter procédure manuelle |
| Art. 9 | Droit d'opposition / Information | ⚠️ Partiel | Avis premier contact + keywords AR |
| Art. 12 | Déclaration préalable | ❌ Non conforme | Soumettre déclaration CNDP |
| Art. 15 | Transfert étranger | ⚠️ Partiel | DPA Google + mention déclaration |
| Art. 21 | Confidentialité | ✅ Conforme | — |
| Art. 23 | Sécurité | ✅ Conforme | — |
| Art. 24 | Sous-traitance | ⚠️ Partiel | DPA Nindohost + Google |

---

*Document généré dans le cadre de l'audit de conformité CNDP — Livrable CPS L6*
*Plateforme CRI Chatbot v0.3.0 — Appel d'Offres N° 02/2026/CRI RSK*
