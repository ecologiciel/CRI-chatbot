# Déclaration Préalable de Traitement de Données à Caractère Personnel

> **Commission Nationale de Contrôle de la Protection des Données à Caractère Personnel (CNDP)**
> Formulaire conforme à l'article 12 de la loi n° 09-08
> **Date de préparation** : 2 avril 2026
> **Version** : 1.0

---

> **Note** : Ce document est un template pré-rempli. Les champs entre crochets `[...]` doivent être complétés par le CRI avant soumission à la CNDP. Les sections pré-remplies reflètent les traitements effectifs de la plateforme CRI Chatbot v0.3.0.

---

## I. Identité du responsable du traitement

| Champ | Valeur |
|-------|--------|
| **Dénomination** | Centre Régional d'Investissement de la Région [Nom de la Région] |
| **Sigle** | CRI [Sigle Région] |
| **Forme juridique** | Établissement public doté de la personnalité morale et de l'autonomie financière (Loi 47-18) |
| **Adresse du siège** | [Adresse complète du CRI] |
| **Ville** | [Ville] |
| **Code postal** | [Code postal] |
| **Téléphone** | [Numéro de téléphone] |
| **Email** | [Email officiel du CRI] |
| **Site web** | [URL du site web CRI] |
| **Représentant légal** | [Nom et prénom du Directeur Général du CRI] |
| **Fonction** | Directeur Général |

### Personne de contact pour les questions de protection des données

| Champ | Valeur |
|-------|--------|
| **Nom et prénom** | [Nom du responsable désigné] |
| **Fonction** | [Fonction] |
| **Email** | [Email dédié protection des données] |
| **Téléphone** | [Numéro direct] |

---

## II. Finalité(s) du traitement

### Finalité principale

Accompagnement des porteurs de projets d'investissement via un agent conversationnel intelligent (chatbot WhatsApp) dans le cadre de la mission légale du CRI définie par la loi n° 47-18 portant réforme des Centres Régionaux d'Investissement et création des Commissions Régionales Unifiées d'Investissement.

### Finalités détaillées

| # | Finalité | Description |
|---|----------|-------------|
| F1 | Information des investisseurs | Répondre aux questions sur les procédures administratives, délais, documents requis et conditions d'éligibilité |
| F2 | Incitations à l'investissement | Fournir des informations interactives sur les incitations fiscales, subventions et aides régionales/nationales |
| F3 | Suivi de dossier | Permettre aux investisseurs de consulter l'état d'avancement de leur dossier d'investissement via authentification OTP |
| F4 | Notifications proactives | Informer les investisseurs des changements de statut de leur dossier, demandes de compléments, et décisions finales |
| F5 | Agent interne | Permettre aux collaborateurs CRI (whitelist) de consulter les données dossiers et statistiques via WhatsApp (lecture seule) |
| F6 | Administration | Gestion de la base de connaissances, supervision des conversations, gestion des contacts et campagnes via back-office web |

---

## III. Catégories de données collectées

### Données des investisseurs (contacts WhatsApp)

| # | Catégorie | Donnée | Caractère obligatoire | Mode de collecte |
|---|-----------|--------|----------------------|------------------|
| 1 | Identité | Numéro de téléphone WhatsApp (E.164) | Obligatoire (automatique) | Collecte automatique au premier message WhatsApp |
| 2 | Identité | Nom et prénom | Facultatif | Fourni volontairement par le contact |
| 3 | Identité | CIN (Carte d'Identité Nationale) | Conditionnel | Collecté uniquement lors du suivi de dossier (vérification OTP) |
| 4 | Préférence | Langue préférée (FR/AR/EN) | Automatique | Détection automatique de la langue du message |
| 5 | Communication | Contenu des messages WhatsApp | Automatique | Messages envoyés par l'investisseur au chatbot |
| 6 | Consentement | Statut d'opt-in/opt-out | Automatique | Enregistrement du consentement et de l'opposition |

### Données des dossiers d'investissement

| # | Catégorie | Donnée | Mode de collecte |
|---|-----------|--------|------------------|
| 7 | Identification | Numéro de dossier | Import depuis le SI du CRI (Excel/CSV) |
| 8 | Identification | Raison sociale | Import depuis le SI du CRI |
| 9 | Financière | Montant d'investissement | Import depuis le SI du CRI |
| 10 | Métier | Statut du dossier et historique | Import et mises à jour périodiques |

### Données d'administration

| # | Catégorie | Donnée | Mode de collecte |
|---|-----------|--------|------------------|
| 11 | Identité admin | Email professionnel | Saisie lors de la création du compte admin |
| 12 | Identité admin | Nom complet | Saisie lors de la création du compte admin |
| 13 | Technique | Adresse IP de connexion | Collecte automatique lors de l'authentification back-office |

---

## IV. Catégories de personnes concernées

| # | Catégorie | Estimation volumétrique |
|---|-----------|------------------------|
| 1 | Porteurs de projets d'investissement (investisseurs) — personnes physiques et morales | ~20 000 contacts par CRI |
| 2 | Collaborateurs CRI utilisant l'agent interne WhatsApp | ≤ 50 par CRI |
| 3 | Administrateurs du back-office | ≤ 10 par CRI |

---

## V. Destinataires des données

### Destinataires internes

| # | Destinataire | Données accessibles | Base d'accès |
|---|-------------|---------------------|-------------|
| 1 | Agents CRI habilités (admin_tenant, supervisor) | Contacts, conversations, dossiers du tenant | RBAC — rôle vérifié par JWT |
| 2 | Agents CRI (viewer) | Contacts, conversations, dossiers — lecture seule | RBAC — rôle vérifié par JWT |
| 3 | Super-administrateur (prestataire technique) | Données cross-tenant pour maintenance | RBAC — rôle super_admin, audit trail |

### Destinataires externes

| # | Destinataire | Données transmises | Garanties |
|---|-------------|-------------------|-----------|
| 1 | **Google** (API Gemini 2.5 Flash) | Prompts textuels **anonymisés uniquement** — aucune donnée personnelle identifiable | Anonymisation systématique avant envoi ; API payante avec politique de non-utilisation pour l'entraînement |
| 2 | **Meta** (WhatsApp Business API) | Messages WhatsApp (contenu et numéro de téléphone) | Chiffrement de bout en bout WhatsApp ; Meta agit en tant que sous-traitant technique du canal de communication |
| 3 | **Nindohost** (hébergeur) | Accès physique aux serveurs hébergeant toutes les données | Datacenter Maroc, ISO 9001:2015 ; accès logique restreint (SSH/VPN) |

---

## VI. Transferts de données hors du territoire marocain

### 6.1 Transfert vers Google (API Gemini)

| Champ | Détail |
|-------|--------|
| **Destinataire** | Google LLC — API Gemini 2.5 Flash |
| **Pays** | Infrastructure Google Cloud (serveurs hors Maroc) |
| **Données transférées** | Prompts textuels anonymisés uniquement |
| **Données NON transférées** | CIN, numéros de téléphone, noms, adresses, montants financiers, numéros de dossier |
| **Mesure de protection** | Anonymisation systématique avant envoi : CIN → `[CIN]`, Téléphone → `[TELEPHONE]`, Email → `[EMAIL]`, Montants → `[MONTANT]` |
| **Base légale** | Les données anonymisées ne constituent pas des données à caractère personnel au sens de l'article 1er de la loi 09-08. L'anonymisation rend le transfert non soumis à l'article 15. |
| **Garanties supplémentaires** | API payante — données non utilisées pour l'entraînement des modèles Google ; traitement éphémère (pas de stockage côté Google) |

### 6.2 Transfert vers Meta (WhatsApp)

| Champ | Détail |
|-------|--------|
| **Destinataire** | Meta Platforms, Inc. — WhatsApp Business API |
| **Données transférées** | Messages WhatsApp (contenu + numéro de téléphone) |
| **Mesure de protection** | Chiffrement de bout en bout WhatsApp ; Meta agit comme sous-traitant technique |
| **Base légale** | Nécessité pour l'exécution du service de communication demandé par la personne concernée |

---

## VII. Durée de conservation

| Catégorie de données | Durée de conservation | Justification |
|---------------------|----------------------|---------------|
| Messages conversationnels | 90 jours | Nécessité d'historique court pour la qualité des réponses |
| Données de contact (téléphone, nom) | Jusqu'à demande de suppression (STOP) | Maintien du service tant que le contact est actif |
| CIN | Durée du suivi de dossier actif | Nécessaire pour la liaison dossier uniquement |
| Données de dossier | Durée légale applicable au dossier d'investissement | Obligation légale de conservation des actes administratifs |
| Logs d'audit | 12 mois en base + 24 mois en archive | Traçabilité et conformité sécuritaire |
| OTP (code de vérification) | 5 minutes | Durée de validité technique du code |
| Sessions de consultation | 30 minutes | Durée de la session utilisateur |
| Données d'administration (comptes) | Durée de l'emploi au CRI | Nécessité d'accès au back-office |

**Mécanisme de suppression** : Purge automatique programmée pour les données temporaires (OTP, sessions). Purge planifiée pour les conversations (90 jours). Suppression manuelle sur demande pour les contacts.

---

## VIII. Mesures de sécurité (Article 23)

### 8.1 Chiffrement

| Couche | Technologie |
|--------|-------------|
| En transit | TLS 1.3 (certificats Let's Encrypt, renouvellement automatique) |
| Au repos (base de données) | pgcrypto pour les champs sensibles |
| Au repos (fichiers) | SSE-S3 (MinIO Server-Side Encryption) |
| Par tenant | AES-256-GCM — clé unique par CRI, rotation planifiable |

### 8.2 Contrôle d'accès

| Mesure | Détail |
|--------|--------|
| Authentification | Email/mot de passe, bcrypt (facteur de coût 12), politique de complexité (12+ caractères) |
| Autorisation | RBAC à 4 rôles : super_admin, admin_tenant, supervisor, viewer |
| Tokens | JWT (HS256), durée 30 minutes, refresh token à usage unique |
| Anti-bruteforce | 5 échecs → blocage 30 minutes + notification |
| Session | Session unique par administrateur, détection de changement d'IP |

### 8.3 Isolation des données

| Composant | Stratégie d'isolation |
|-----------|----------------------|
| Base de données | Schéma PostgreSQL dédié par CRI (`tenant_{slug}`) |
| Base vectorielle | Collection Qdrant dédiée par CRI (`kb_{slug}`) |
| Cache | Préfixe Redis dédié par CRI (`{slug}:`) |
| Stockage fichiers | Bucket MinIO dédié par CRI (`cri-{slug}`) |
| Réseau | Réseau Docker backend isolé (aucun accès Internet direct en production) |

### 8.4 Traçabilité

| Mesure | Détail |
|--------|--------|
| Journal d'audit | Table immuable (INSERT uniquement, pas de UPDATE/DELETE) |
| Couverture | Toutes les actions admin, OTP, opt-in/opt-out, escalades |
| Archivage | Hebdomadaire, signé SHA-256, stocké sur MinIO |
| Rétention | 12 mois base de données + 24 mois archives |

### 8.5 Protection contre les abus

| Niveau | Limite |
|--------|--------|
| Webhook WhatsApp | 50 requêtes/minute par CRI |
| Messages utilisateur | 10 messages/minute par utilisateur |
| Vérification OTP | 3 tentatives par 15 minutes par numéro |
| Login administrateur | 5 tentatives par 15 minutes par email |

### 8.6 Monitoring

Surveillance en temps réel via Prometheus et Grafana avec alertes automatiques pour les comportements anormaux (flood, bruteforce, anomalies de coût IA).

---

## IX. Droits des personnes concernées

### 9.1 Droit d'accès (Article 7)

| Canal | Modalité |
|-------|----------|
| Chatbot WhatsApp | Consultation des données de dossier via authentification OTP |
| Contact CRI | Demande par email à [Email DPO] ou par téléphone au [Numéro CRI] |
| Back-office | Export des données par un administrateur CRI habilité |

### 9.2 Droit de rectification (Article 8)

| Canal | Modalité |
|-------|----------|
| Contact CRI | Demande par email ou téléphone ; rectification effectuée par un administrateur CRI |
| Import de données | Mise à jour automatique lors des imports Excel/CSV du SI |

### 9.3 Droit d'opposition (Article 9)

| Canal | Modalité |
|-------|----------|
| Chatbot WhatsApp | Envoi du mot « STOP » (ou variantes : arrêter, désabonner, unsubscribe) |
| Contact CRI | Demande par email ou téléphone |
| Effet | Cessation immédiate des messages, exclusion des campagnes et notifications |

---

## X. Interconnexions avec d'autres traitements

| Traitement connecté | Nature de la connexion | Finalité |
|---------------------|----------------------|----------|
| Système d'information CRI (SI interne) | Import unidirectionnel Excel/CSV | Synchronisation des données de dossier |
| WhatsApp Business API (Meta) | Bidirectionnel (webhook + envoi) | Canal de communication |
| Google Gemini API | Unidirectionnel (envoi de prompts anonymisés) | Génération de réponses IA |

---

## XI. Date de mise en œuvre prévue

| Étape | Date |
|-------|------|
| Préparation de la déclaration | 2 avril 2026 |
| Soumission à la CNDP | [Date de soumission — à compléter] |
| Mise en production prévue | [Date MEP — à compléter] |

---

## XII. Engagement du responsable du traitement

Je soussigné(e), [Nom et prénom du Directeur Général], en qualité de Directeur Général du Centre Régional d'Investissement de la Région [Nom de la Région], déclare :

1. Que le traitement décrit ci-dessus sera mis en œuvre conformément aux dispositions de la loi n° 09-08 relative à la protection des personnes physiques à l'égard du traitement des données à caractère personnel ;
2. Que les mesures de sécurité décrites en section VIII sont effectivement implémentées dans la plateforme ;
3. Que les droits des personnes concernées seront respectés conformément aux modalités décrites en section IX ;
4. Que toute modification substantielle du traitement fera l'objet d'une déclaration modificative auprès de la CNDP.

| Champ | Valeur |
|-------|--------|
| **Fait à** | [Ville] |
| **Le** | [Date] |
| **Nom et prénom** | [Nom du Directeur Général] |
| **Qualité** | Directeur Général du CRI [Région] |
| **Signature** | _________________________________ |
| **Cachet** | [Cachet officiel du CRI] |

---

## Pièces jointes

1. Checklist de conformité loi 09-08 (`checklist_09_08.md`)
2. Rapport d'audit technique CNDP (`audit_cndp.md`)
3. Politique de confidentialité — version française (`politique_confidentialite_fr.md`)
4. Politique de confidentialité — version arabe (`politique_confidentialite_ar.md`)

---

*Template préparé dans le cadre de l'audit de conformité CNDP — Livrable CPS L6*
*Plateforme CRI Chatbot v0.3.0 — Appel d'Offres N° 02/2026/CRI RSK*
