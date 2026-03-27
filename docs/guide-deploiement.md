# Guide de Deploiement — Plateforme CRI Chatbot

> Guide d'installation, configuration et exploitation en production.
> Appel d'Offres N° 02/2026/CRI RSK

---

## 1. Pre-requis

### 1.1. Materiel (infrastructure Nindohost)

| Serveur | Specs recommandees | Role |
|---------|-------------------|------|
| VPS Prod 1 | 8 vCPU, 32 Go RAM, 500 Go SSD NVMe | Backend API, Orchestrateur IA, Qdrant |
| VPS Prod 2 | 4 vCPU, 16 Go RAM, 200 Go SSD NVMe | PostgreSQL, Redis, MinIO |
| VPS Prod 3 | 4 vCPU, 8 Go RAM, 100 Go SSD NVMe | Frontend, Traefik, Prometheus, Grafana |
| VPS Pre-Prod | 4 vCPU, 16 Go RAM, 200 Go SSD NVMe | Miroir production (tests) |

> Clarification CPS R5 : serveurs virtualises, pas de GPU. Architecture LLM cloud (Gemini API).

### 1.2. Logiciels

- **Systeme** : Ubuntu 22.04 LTS ou superieur
- **Docker Engine** : 24.0 ou superieur
- **Docker Compose** : v2 (integre a Docker Engine)
- **Git** : pour cloner le depot
- **openssl** : pour generer les secrets

### 1.3. Reseau

- **Nom de domaine** configure (enregistrements DNS A pointant vers le VPS)
- **Ports 80 et 443** ouverts sur le firewall (pour Traefik / Let's Encrypt)
- **SSH via VPN** pour l'acces administrateur (clarification CPS R7)
- **Firewall** : whitelist IP admin

### 1.4. Comptes externes

| Service | Necessaire pour | Comment l'obtenir |
|---------|----------------|------------------|
| **Google AI Studio** | Cle API Gemini 2.5 Flash | https://aistudio.google.com |
| **Meta Business** | WhatsApp Business API | https://business.facebook.com |
| **Email** | Certificat Let's Encrypt | Adresse email valide |

> Clarification CPS R10 : le CRI ne dispose pas de compte WhatsApp. Il est a creer dans le cadre de la prestation.

---

## 2. Configuration de l'environnement

### 2.1. Cloner le depot

```bash
git clone <url-du-depot> cri-chatbot-platform
cd cri-chatbot-platform
```

### 2.2. Configurer le fichier `.env`

```bash
cp .env.example .env
chmod 600 .env
```

Editer `.env` et remplir les variables obligatoires :

### Variables obligatoires (a generer)

```bash
# Generer des mots de passe forts
openssl rand -base64 32  # Pour POSTGRES_PASSWORD
openssl rand -base64 32  # Pour REDIS_PASSWORD
openssl rand -base64 32  # Pour MINIO_ROOT_PASSWORD
openssl rand -base64 64  # Pour JWT_SECRET_KEY
```

| Variable | Description | Exemple |
|----------|-------------|---------|
| `POSTGRES_PASSWORD` | Mot de passe PostgreSQL | *(genere)* |
| `REDIS_PASSWORD` | Mot de passe Redis | *(genere)* |
| `MINIO_ROOT_PASSWORD` | Mot de passe MinIO | *(genere)* |
| `JWT_SECRET_KEY` | Cle secrete JWT (512 bits) | *(genere)* |
| `GRAFANA_PASSWORD` | Mot de passe Grafana admin | *(mot de passe fort)* |

### Variables API

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Cle API Google AI Studio |
| `WHATSAPP_APP_SECRET` | App secret Meta pour validation HMAC webhook |
| `WHATSAPP_VERIFY_TOKEN` | Token de verification webhook (vous le choisissez) |

### Variables production

```ini
ENVIRONMENT=production
LOG_LEVEL=INFO
ACME_EMAIL=admin@<votre-domaine>.ma
BACKOFFICE_URL=https://<votre-domaine>.ma
```

> **IMPORTANT :** Le fichier `.env` contient des secrets sensibles. Ne jamais le versionner (deja dans `.gitignore`). Permissions recommandees : `chmod 600 .env`.

---

## 3. Deploiement en developpement local

### 3.1. Lancer les services

```bash
docker compose up -d
```

Cela demarre 9 services : PostgreSQL, Qdrant, Redis, MinIO, Traefik, Prometheus, Grafana, Backend, Frontend.

### 3.2. Verifier le demarrage

```bash
# Tous les services doivent etre "healthy"
docker compose ps

# Tester l'endpoint health
curl http://localhost:8000/api/v1/health
```

Reponse attendue :
```json
{"status": "healthy", "version": "0.1.0", "services": {"postgresql": {"status": "healthy"}, ...}}
```

### 3.3. Initialisation de la base de donnees

Le script `scripts/init-db.sh` s'execute automatiquement au premier demarrage de PostgreSQL (extensions `pgcrypto` et `uuid-ossp`).

Appliquer les migrations Alembic :

```bash
docker compose exec backend alembic upgrade head
```

### 3.4. Acces aux services

| Service | URL | Notes |
|---------|-----|-------|
| **Back-office** | http://localhost:3000 | Interface d'administration |
| **API (Swagger)** | http://localhost:8000/docs | Documentation interactive |
| **API (ReDoc)** | http://localhost:8000/redoc | Documentation alternative |
| **Traefik Dashboard** | http://localhost:8080 | Monitoring reverse proxy |
| **Grafana** | http://localhost:3001 | Dashboards (admin/admin) |
| **MinIO Console** | http://localhost:9001 | Gestion des fichiers |
| **Prometheus** | http://localhost:9090 | Metriques brutes |

---

## 4. Deploiement en production

### 4.1. Commande de lancement

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Le fichier `docker-compose.prod.yml` surcharge le fichier de base avec les parametres de production.

### 4.2. Differences production vs developpement

| Aspect | Developpement | Production |
|--------|--------------|------------|
| Ports internes | Exposes sur localhost | Fermes (PostgreSQL, Redis, Qdrant, MinIO, Prometheus, Grafana) |
| Reseau backend | Accessible | `internal: true` (aucun acces Internet) |
| Swagger/ReDoc | Actives | Desactivees |
| Hot reload | Active | Desactive |
| Traefik dashboard | Port 8080 | Desactive |
| Restart policy | Non | `unless-stopped` sur tous les services |

**Limites memoire en production :**

| Service | Memoire max |
|---------|------------|
| PostgreSQL | 8 Go |
| Qdrant | 12 Go |
| MinIO | 4 Go |
| Redis | 2 Go |
| Traefik | 512 Mo |

### 4.3. TLS / Let's Encrypt

Traefik obtient automatiquement les certificats TLS via Let's Encrypt (challenge HTTP).

**Pre-requis :**
- Variable `ACME_EMAIL` renseignee dans `.env`
- Ports 80 et 443 ouverts
- Enregistrement DNS A pointant vers le serveur

**Verification :**
```bash
curl -v https://<votre-domaine>.ma/api/v1/health
```

Les certificats sont stockes dans le volume `traefik_certs` et renouveles automatiquement.

### 4.4. Migrations en production

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend alembic upgrade head
```

### 4.5. Provisionnement du premier tenant

Apres le deploiement, creer le premier super_admin et le premier tenant via l'API :

```bash
# 1. Se connecter avec le super_admin (cree lors du seed initial)
TOKEN=$(curl -s -X POST https://<domaine>/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@cri.ma", "password": "<mot-de-passe>"}' \
  | jq -r '.access_token')

# 2. Creer le premier tenant
curl -X POST https://<domaine>/api/v1/tenants/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "CRI Rabat-Sale-Kenitra",
    "slug": "rabat_sale_kenitra",
    "region": "Rabat-Sale-Kenitra",
    "whatsapp_config": {
      "phone_number_id": "<VOTRE_PHONE_NUMBER_ID>",
      "access_token": "<VOTRE_ACCESS_TOKEN>",
      "display_name": "CRI RSK Bot"
    }
  }'
```

Le provisionnement cree automatiquement :
- Schema PostgreSQL `tenant_rabat_sale_kenitra`
- Collection Qdrant `kb_rabat_sale_kenitra`
- Bucket MinIO `cri-rabat_sale_kenitra`
- Mapping Redis `phone_mapping:<phone_number_id>`

---

## 5. Configuration WhatsApp

### 5.1. Creer l'application Meta Business

1. Aller sur https://developers.facebook.com
2. Creer une application de type **Business**
3. Ajouter le produit **WhatsApp**
4. Recuperer :
   - `phone_number_id` (dans WhatsApp > Getting Started)
   - `access_token` (token permanent via System User)
   - `app_secret` (dans Settings > Basic)

### 5.2. Configurer le webhook

1. Dans l'application Meta, aller a **WhatsApp > Configuration**
2. Cliquer sur **Edit** dans la section Webhook
3. Renseigner :
   - **Callback URL** : `https://<votre-domaine>.ma/api/v1/webhook/whatsapp`
   - **Verify Token** : la valeur de `WHATSAPP_VERIFY_TOKEN` dans votre `.env`
4. S'abonner aux champs : `messages`, `message_deliveries`, `message_reads`

### 5.3. Tester

Envoyer un message WhatsApp au numero associe. Verifier dans les logs :

```bash
docker compose logs -f backend | grep webhook
```

---

## 6. Volumes et persistance

Les donnees sont stockees dans des volumes Docker nommes :

| Volume | Contenu | Critique |
|--------|---------|----------|
| `postgres_data` | Base de donnees relationnelle | **Oui** — sauvegarder quotidiennement |
| `qdrant_data` | Index vectoriels | **Oui** — sauvegarder hebdomadairement |
| `redis_data` | Cache et sessions (AOF) | Moyen — recreable |
| `minio_data` | Documents uploades | **Oui** — sauvegarder hebdomadairement |
| `traefik_certs` | Certificats Let's Encrypt | Moyen — regenerable |
| `prometheus_data` | Metriques (30 jours) | Faible |
| `grafana_data` | Configuration Grafana | Faible — recreable |

> **ATTENTION :** Ne jamais supprimer les volumes sans sauvegarde prealable. Emplacement par defaut : `/var/lib/docker/volumes/`

---

## 7. Healthchecks

Chaque service dispose d'un healthcheck Docker :

| Service | Commande | Intervalle | Retries |
|---------|----------|-----------|---------|
| PostgreSQL | `pg_isready` | 10s | 5 |
| Qdrant | `wget http://localhost:6333/readyz` | 10s | 5 |
| Redis | `redis-cli ping` | 10s | 5 |
| MinIO | `curl http://localhost:9000/minio/health/live` | 10s | 5 |
| Traefik | `traefik healthcheck` | 10s | 3 |
| Prometheus | `wget http://localhost:9090/-/healthy` | 15s | 3 |
| Grafana | `wget http://localhost:3000/api/health` | 15s | 3 |
| Backend | `httpx GET http://localhost:8000/api/v1/health` | 15s | 3 |
| Frontend | `wget http://localhost:3000/` | 15s | 3 |

L'endpoint `/api/v1/health` du backend verifie la connectivite a PostgreSQL, Redis, Qdrant et MinIO. Statuts possibles : `healthy`, `degraded` (au moins un service en erreur), `unhealthy`.

---

## 8. Sauvegarde et restauration (PRA)

### 8.1. PostgreSQL

```bash
# Sauvegarde quotidienne
docker compose exec postgres pg_dump -U cri_admin cri_platform > backup_$(date +%Y%m%d).sql

# Restauration
docker compose exec -T postgres psql -U cri_admin cri_platform < backup_20260327.sql
```

### 8.2. Qdrant

```bash
# Snapshot d'une collection
curl -X POST http://localhost:6333/collections/kb_rabat_sale_kenitra/snapshots

# Lister les snapshots
curl http://localhost:6333/collections/kb_rabat_sale_kenitra/snapshots
```

### 8.3. MinIO

```bash
# Installer mc (MinIO Client)
# Configurer l'alias
mc alias set cri http://localhost:9000 cri_minio <MOT_DE_PASSE>

# Miroir vers un stockage secondaire
mc mirror cri/ /chemin/backup/minio/
```

### 8.4. Frequence et retention

| Composant | Frequence | Retention |
|-----------|-----------|-----------|
| PostgreSQL | Quotidien (incremental) | 30 jours glissants + mensuels 12 mois |
| Qdrant | Hebdomadaire | 30 jours glissants |
| MinIO | Hebdomadaire | 30 jours glissants |

**Objectifs :** RTO < 4 heures, RPO < 24 heures.

---

## 9. Monitoring

### 9.1. Prometheus

Configuration dans `docker/prometheus/prometheus.yml` :

| Job | Cible | Intervalle |
|-----|-------|-----------|
| `prometheus` | localhost:9090 | 15s |
| `traefik` | traefik:8080/metrics | 15s |
| `fastapi` | backend:8000/metrics | 10s |

Retention : 30 jours.

### 9.2. Grafana

- **Dev** : http://localhost:3001 (admin / mot de passe configure)
- **Prod** : accessible via Traefik (configurer un router supplementaire si necessaire)
- **Datasource** : ajouter Prometheus avec URL `http://prometheus:9090`

### 9.3. Logs

Les logs du backend sont structures en JSON (structlog) :

```bash
# Logs temps reel
docker compose logs -f backend

# Filtrer par service
docker compose logs -f backend | grep "faq_agent"

# Logs d'un service specifique
docker compose logs -f postgres
```

---

## 10. Mise a jour

### 10.1. Procedure standard

```bash
# 1. Recuperer les changements
git pull

# 2. Reconstruire les images
docker compose -f docker-compose.yml -f docker-compose.prod.yml build

# 3. Appliquer les migrations (si nouvelles)
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend alembic upgrade head

# 4. Redemarrer les services
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 10.2. Rollback

```bash
# Rollback migration (si necessaire)
docker compose exec backend alembic downgrade -1

# Restauration complete depuis sauvegarde
# 1. Arreter les services
docker compose down

# 2. Restaurer les donnees (voir section 8)
# 3. Redemarrer
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

---

## 11. Depannage

### Le backend ne demarre pas

1. Verifier les variables `.env` obligatoires :
   ```bash
   grep -c "=\s*$" .env  # Pas de variables vides
   ```
2. Verifier la connectivite aux services :
   ```bash
   docker compose ps  # Tous les services de donnees "healthy" ?
   docker compose logs backend | tail -50
   ```

### Erreur de migration Alembic

1. Verifier que PostgreSQL est accessible :
   ```bash
   docker compose exec postgres pg_isready
   ```
2. Consulter le message d'erreur :
   ```bash
   docker compose exec backend alembic upgrade head 2>&1
   ```
3. En cas de migration partielle, utiliser `alembic stamp` pour synchroniser l'etat.

### Le webhook WhatsApp ne fonctionne pas

1. Verifier que `WHATSAPP_VERIFY_TOKEN` et `WHATSAPP_APP_SECRET` sont renseignes dans `.env`
2. Verifier que l'URL est accessible publiquement :
   ```bash
   curl https://<domaine>/api/v1/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=<TOKEN>&hub.challenge=test
   ```
3. Consulter les logs webhook :
   ```bash
   docker compose logs backend | grep "webhook\|hmac\|signature"
   ```

### L'ingestion KB reste en "pending"

1. Verifier le worker ARQ :
   ```bash
   docker compose logs backend | grep "arq\|ingest"
   ```
2. Relancer manuellement via l'API :
   ```bash
   curl -X POST https://<domaine>/api/v1/kb/documents/<ID>/reindex \
     -H "Authorization: Bearer <TOKEN>" \
     -H "X-Tenant-ID: <TENANT_ID>"
   ```

---

## Annexe A : Variables d'environnement completes

| Variable | Obligatoire | Defaut | Description |
|----------|:-----------:|--------|-------------|
| `POSTGRES_DB` | Non | `cri_platform` | Nom de la base |
| `POSTGRES_USER` | Non | `cri_admin` | Utilisateur PostgreSQL |
| `POSTGRES_PASSWORD` | **Oui** | — | Mot de passe PostgreSQL |
| `POSTGRES_HOST` | Non | `postgres` | Hote PostgreSQL |
| `POSTGRES_PORT` | Non | `5432` | Port PostgreSQL |
| `REDIS_PASSWORD` | **Oui** | — | Mot de passe Redis |
| `REDIS_HOST` | Non | `redis` | Hote Redis |
| `REDIS_PORT` | Non | `6379` | Port Redis |
| `QDRANT_HOST` | Non | `qdrant` | Hote Qdrant |
| `QDRANT_HTTP_PORT` | Non | `6333` | Port HTTP Qdrant |
| `QDRANT_GRPC_PORT` | Non | `6334` | Port gRPC Qdrant |
| `MINIO_ROOT_USER` | Non | `cri_minio` | Utilisateur MinIO |
| `MINIO_ROOT_PASSWORD` | **Oui** | — | Mot de passe MinIO |
| `MINIO_ENDPOINT` | Non | `minio:9000` | Endpoint MinIO |
| `MINIO_USE_SSL` | Non | `false` | SSL pour MinIO |
| `ACME_EMAIL` | Prod | — | Email pour Let's Encrypt |
| `BACKOFFICE_URL` | Non | `http://localhost:3000` | URL du back-office (CORS) |
| `GEMINI_API_KEY` | **Oui** | — | Cle API Google AI Studio |
| `WHATSAPP_APP_SECRET` | **Oui** | — | App secret Meta (HMAC) |
| `WHATSAPP_VERIFY_TOKEN` | **Oui** | — | Token verification webhook |
| `JWT_SECRET_KEY` | **Oui** | — | Cle secrete JWT (512 bits) |
| `JWT_ALGORITHM` | Non | `HS256` | Algorithme JWT |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Non | `30` | Duree access token |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | Non | `7` | Duree refresh token |
| `GRAFANA_USER` | Non | `admin` | Utilisateur Grafana |
| `GRAFANA_PASSWORD` | **Oui** | — | Mot de passe Grafana |
| `ENVIRONMENT` | Non | `development` | `development`, `staging`, `production` |
| `LOG_LEVEL` | Non | `DEBUG` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## Annexe B : Ports par service

| Service | Port interne | Port expose (dev) | Port expose (prod) |
|---------|:------------:|:-----------------:|:------------------:|
| PostgreSQL | 5432 | 127.0.0.1:5432 | Ferme |
| Qdrant (HTTP) | 6333 | 127.0.0.1:6333 | Ferme |
| Qdrant (gRPC) | 6334 | 127.0.0.1:6334 | Ferme |
| Redis | 6379 | 127.0.0.1:6379 | Ferme |
| MinIO (API) | 9000 | 127.0.0.1:9000 | Ferme |
| MinIO (Console) | 9001 | 127.0.0.1:9001 | Ferme |
| Traefik (HTTP) | 80 | 80 | 80 |
| Traefik (HTTPS) | 443 | 443 | 443 |
| Traefik (Dashboard) | 8080 | 127.0.0.1:8080 | Ferme |
| Prometheus | 9090 | 127.0.0.1:9090 | Ferme |
| Grafana | 3000 | 127.0.0.1:3001 | Ferme |
| Backend | 8000 | 127.0.0.1:8000 | Via Traefik |
| Frontend | 3000 | 127.0.0.1:3000 | Via Traefik |

---

## Voir aussi

- [Architecture technique](architecture-technique.md) — Stack, reseaux Docker, securite
- [Reference API](api-reference.md) — Endpoints REST et schemas
- [Guide d'administration](guide-administration.md) — Utilisation du back-office
