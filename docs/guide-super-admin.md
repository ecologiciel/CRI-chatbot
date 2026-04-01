# Guide — Back-Office Super-Admin

> Module Phase 2 — Administration cross-tenant de la plateforme CRI Chatbot.

## Role du super-admin

Le super-admin a un acces global a la plateforme. Il peut :
- **Creer et gerer les tenants** (CRI regionaux)
- **Superviser** l'activite de tous les tenants
- **Gerer les administrateurs** de chaque tenant
- **Consulter les logs d'audit** centralises
- **Acceder a tous les modules** sans restriction de tenant

## Acces

Le super-admin accede au back-office avec ses identifiants. L'espace super-admin offre une navigation distincte avec des pages dediees :
- **Tenants** — Gestion des CRI regionaux
- **Administrateurs** — Gestion des comptes admin par tenant
- **Monitoring** — Vue d'ensemble de la sante de la plateforme
- **Logs d'audit** — Consultation centralisee de toutes les actions

## Creer un nouveau tenant CRI

1. **Tenants** → bouton **"Creer un tenant"**
2. Renseigner les informations :
   - **Nom du CRI** (ex : "CRI Rabat-Sale-Kenitra")
   - **Slug** (auto-genere a partir du nom, ex : `rabat`)
   - **Region** (ex : "Rabat-Sale-Kenitra")
3. Configurer WhatsApp :
   - **Phone Number ID** (identifiant du numero dans Meta Business)
   - **Access Token** (token d'acces API WhatsApp)
   - **App Secret** (secret pour la validation HMAC des webhooks)
4. Personnaliser (optionnel) :
   - **Logo** (SVG ou PNG, max 200x60px)
   - **Couleur accent** (pour la page de login du tenant)
5. Confirmer la creation

### Provisionnement automatique

A la creation d'un tenant, la plateforme provisionne automatiquement :
- **Schema PostgreSQL** : `tenant_{slug}` avec toutes les tables metier
- **Collection Qdrant** : `kb_{slug}` pour la base de connaissances vectorielle
- **Bucket MinIO** : `cri-{slug}` pour le stockage de fichiers
- **Prefixe Redis** : `{slug}:*` pour le cache et les sessions
- **Cle de chiffrement KMS** : cle AES-256 dediee au tenant (envelope encryption)

## Gerer les administrateurs

Chaque tenant peut avoir jusqu'a **10 administrateurs** avec des roles differents :

| Role | Droits |
|------|--------|
| `admin_tenant` | Acces complet au tenant (KB, contacts, campagnes, escalades, configuration) |
| `supervisor` | Gestion des escalades, apprentissage supervise, consultation contacts |
| `viewer` | Consultation seule (dashboards, statistiques) |

### Operations :
- **Creer un admin** : renseigner email, mot de passe initial, role
- **Modifier un admin** : changer le role, reactiver/desactiver
- **Desactiver un admin** : l'admin ne peut plus se connecter mais son historique est conserve

## Monitoring multi-tenant

La page Monitoring affiche en temps reel pour chaque tenant :
- **Statut** : actif / inactif
- **Messages du jour** : nombre de messages WhatsApp echanges
- **Contacts** : nombre total de contacts
- **Derniere activite** : horodatage du dernier message
- **Sante des services** : etat des connexions DB, Qdrant, Redis, MinIO

## Logs d'audit

La table `audit_logs` est en mode **INSERT ONLY** (aucune suppression ni modification possible par l'application). Chaque action significative est enregistree :

| Champ | Description |
|-------|-------------|
| `tenant_slug` | Tenant concerne |
| `user_id` | Administrateur ayant effectue l'action |
| `user_type` | Type d'utilisateur (admin, super_admin, system) |
| `action` | Action effectuee (create, update, delete, login, etc.) |
| `resource_type` | Type de ressource (contact, escalation, campaign, etc.) |
| `resource_id` | Identifiant de la ressource |
| `ip_address` | Adresse IP de l'utilisateur |
| `details` | Details supplementaires (JSON) |
| `created_at` | Horodatage |

### Filtres disponibles :
- Par **tenant**
- Par **utilisateur**
- Par **action**
- Par **periode** (date debut / date fin)

### Archivage
Les logs sont archives automatiquement chaque semaine :
- Signature SHA-256 du lot archive
- Stockage sur MinIO (bucket dedie)
- Retention : 12 mois PostgreSQL, 24 mois MinIO

## Securite

### KMS (Key Management Service)

Chaque tenant dispose de sa propre cle de chiffrement AES-256-GCM. L'architecture utilise l'**envelope encryption** :
- La **master key** (variable d'environnement `KMS_MASTER_KEY`) protege les cles de tenant
- Chaque **tenant key** chiffre les donnees sensibles du tenant
- Rotation planifiable des cles de tenant

### Gestion des sessions

- Detection de **changement d'adresse IP** en cours de session
- **Session unique** : une seule session active par administrateur
- Alertes en cas de connexion simultanee depuis des IP differentes
