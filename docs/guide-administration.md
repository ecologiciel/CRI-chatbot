# Guide d'Administration — Back-Office CRI Chatbot

> Guide destine aux administrateurs des Centres Regionaux d'Investissement.
> Appel d'Offres N° 02/2026/CRI RSK

---

## 1. Connexion et authentification

### 1.1. Se connecter

1. Ouvrir le navigateur et acceder a l'URL du back-office :
   - Developpement : `http://localhost:3000`
   - Production : `https://<domaine-fourni>`
2. Saisir votre adresse email et votre mot de passe
3. Cliquer sur **Se connecter**

La session est valide pendant **30 minutes**. Elle se renouvelle automatiquement tant que vous etes actif.

### 1.2. Se deconnecter

Cliquer sur votre avatar en haut a droite de la barre superieure, puis **Deconnexion**.

### 1.3. Politique de mot de passe

Votre mot de passe doit respecter les regles suivantes :
- **12 caracteres minimum**
- Au moins **1 lettre majuscule**
- Au moins **1 chiffre**
- Au moins **1 caractere special** (ex : `!@#$%`)

### 1.4. Verrouillage de compte

Apres **5 tentatives de connexion echouees** en 15 minutes, votre compte est verrouille pendant **30 minutes**. Contactez votre administrateur si le probleme persiste.

---

## 2. Roles et permissions

La plateforme definit 4 niveaux d'acces :

| Role | Description |
|------|-------------|
| **Super Admin** | Acces complet a tous les tenants. Gestion des CRI. |
| **Admin Tenant** | Acces complet a son propre CRI. |
| **Superviseur** | Consultation + operations quotidiennes (upload KB, modification contacts). |
| **Lecteur** | Consultation uniquement (lecture seule). |

### Matrice des droits

| Action | Super Admin | Admin Tenant | Superviseur | Lecteur |
|--------|:-----------:|:------------:|:-----------:|:-------:|
| Voir le tableau de bord | ✓ | ✓ | ✓ | ✓ |
| Consulter les conversations | ✓ | ✓ | ✓ | ✓ |
| Consulter les feedbacks | ✓ | ✓ | ✓ | ✓ |
| Consulter la base de connaissances | ✓ | ✓ | ✓ | ✓ |
| Ajouter/supprimer des documents KB | ✓ | ✓ | — | — |
| Consulter les contacts | ✓ | ✓ | ✓ | — |
| Modifier les contacts | ✓ | ✓ | — | — |
| Importer/exporter des contacts | ✓ | ✓ | — | — |
| Valider les questions non couvertes | ✓ | ✓ | — | — |
| Creer/gerer les CRI (tenants) | ✓ | — | — | — |

---

## 3. Tableau de bord

Le tableau de bord affiche les indicateurs cles de votre CRI en temps reel :

| Indicateur | Description |
|------------|-------------|
| **Conversations actives** | Nombre de conversations WhatsApp en cours |
| **Messages aujourd'hui** | Total des messages envoyes et recus aujourd'hui |
| **Taux de resolution** | Pourcentage de questions auxquelles le chatbot a pu repondre avec confiance |
| **Score CSAT** | Score de satisfaction (base sur les feedbacks positifs/negatifs) |
| **Contacts** | Nombre total de contacts enregistres |
| **Documents KB indexes** | Nombre de documents dans la base de connaissances avec statut "indexe" |
| **Questions non couvertes** | Nombre de questions en attente de validation |

> **Interpretation :** Un score CSAT inferieur a 70% ou un nombre eleve de questions non couvertes indique qu'il faut enrichir la base de connaissances.

---

## 4. Gestion de la base de connaissances

La base de connaissances (KB) est la source d'information du chatbot. Plus elle est riche et a jour, meilleures seront les reponses.

### 4.1. Importer un document

1. Aller dans **Base de connaissances** via le menu lateral
2. Cliquer sur **Ajouter un document**
3. Remplir les champs :
   - **Titre** : nom descriptif du document (obligatoire)
   - **Categorie** : classification libre (ex : "procedures", "incitations", "juridique")
   - **Langue** : francais, arabe ou anglais
4. Selectionner le fichier a importer
5. Cliquer sur **Importer**

**Formats acceptes :**

| Format | Extension | Notes |
|--------|-----------|-------|
| PDF | `.pdf` | Documents officiels, guides |
| Word | `.docx` | Documents editables |
| Texte | `.txt` | Texte brut |
| Markdown | `.md` | Documentation formatee |
| CSV | `.csv` | Donnees tabulaires (FAQ) |

**Taille maximale :** 10 Mo par document

### 4.2. Processus d'indexation

Apres l'import, le document passe par plusieurs etapes :

| Statut | Description | Action requise |
|--------|-------------|---------------|
| **En attente** (`pending`) | Le document est enregistre, traitement en file | Patienter |
| **Indexation** (`indexing`) | Decoupage, analyse et indexation en cours | Patienter |
| **Indexe** (`indexed`) | Le document est pret — le chatbot peut l'utiliser | Aucune |
| **Erreur** (`error`) | Echec du traitement | Verifier le fichier, tenter une reindexation |

### 4.3. Consulter les documents

La liste affiche tous les documents avec :
- Titre, categorie, langue
- Statut d'indexation
- Nombre de fragments (chunks) generes
- Date de creation

Utilisez les filtres pour affiner par **statut** ou **categorie**.

### 4.4. Reindexer un document

Si un document est en erreur ou si le pipeline a ete mis a jour :
1. Cliquer sur le document dans la liste
2. Cliquer sur **Reindexer**
3. Le statut repasse a "En attente" et le traitement recommence

### 4.5. Supprimer un document

1. Cliquer sur le document dans la liste
2. Cliquer sur **Supprimer**
3. Confirmer la suppression

> **Attention :** La suppression est **irreversible**. Le fichier, tous les fragments et les vecteurs associes sont detruits.

---

## 5. Gestion des contacts

Les contacts sont les utilisateurs WhatsApp qui interagissent avec le chatbot. Un contact est cree automatiquement lors du premier message.

### 5.1. Consulter la liste

La liste des contacts affiche :
- Nom, telephone, CIN (si renseigne)
- Langue preferee
- Statut opt-in (inscrit / desinscrit / en attente)
- Tags

**Recherche :** tapez dans la barre de recherche pour filtrer par nom, telephone ou CIN.

**Filtres disponibles :**
- Statut opt-in
- Langue
- Tags

### 5.2. Creer un contact

1. Cliquer sur **Nouveau contact**
2. Remplir les champs :
   - **Telephone** (obligatoire) : format international, ex : `+212612345678`
   - **Nom** (optionnel)
   - **Langue** : francais, arabe ou anglais
   - **CIN** (optionnel) : format marocain (1-2 lettres + 5-6 chiffres, ex : `AB12345`)
   - **Tags** : mots-cles libres
3. Cliquer sur **Enregistrer**

> Le telephone doit etre unique. Un doublon sera refuse.

### 5.3. Modifier un contact

Cliquer sur un contact dans la liste pour ouvrir le detail. Vous pouvez modifier :
- Nom
- Langue
- CIN
- Tags
- Statut opt-in

### 5.4. Supprimer un contact

Cliquer sur **Supprimer** dans la fiche du contact.

> **Attention :** La suppression entraine egalement la suppression de toutes les conversations et messages associes.

### 5.5. Importer des contacts

1. Cliquer sur **Importer**
2. Selectionner un fichier `.csv` ou `.xlsx`
3. Le systeme affiche un resume avant import :
   - Nombre de contacts a creer
   - Doublons detectes (ignores automatiquement, cle : telephone)
   - Erreurs de format
4. Confirmer l'import

### 5.6. Exporter les contacts

1. Cliquer sur **Exporter**
2. Choisir le format : **CSV** ou **Excel**
3. Le fichier se telecharge automatiquement

---

## 6. Supervision des conversations

### 6.1. Liste des conversations

La page **Conversations** affiche l'ensemble des echanges WhatsApp avec filtres :

| Statut | Description |
|--------|-------------|
| **Active** | Conversation en cours |
| **Terminee** | Conversation cloturee (timeout 30 min ou cloture explicite) |
| **Escaladee** | Transferee a un agent humain (Phase 2) |

### 6.2. Detail d'une conversation

En cliquant sur une conversation, vous voyez :
- Le contact associe (nom, telephone)
- La liste chronologique des messages
- Pour chaque message : direction (entrant/sortant), type (texte, image, audio, bouton), horodatage
- L'intention detectee par le chatbot
- Le score de confiance RAG

> **Note Phase 1 :** La supervision est en **lecture seule**. L'intervention humaine dans les conversations sera disponible en Phase 2 (escalade agent humain).

---

## 7. Feedback et apprentissage supervise

### 7.1. Consulter les feedbacks

Apres chaque reponse FAQ, l'utilisateur WhatsApp peut donner son avis via des boutons :
- 👍 **Positif** : la reponse etait utile
- 👎 **Negatif** : la reponse n'etait pas satisfaisante
- ❓ **Pas clair** : la reponse n'est pas comprise

La page **Feedback** permet de :
- Voir la liste de tous les feedbacks
- Filtrer par type (positif / negatif / pas clair)
- Consulter les statistiques globales

### 7.2. Questions non couvertes

Quand le chatbot ne peut pas repondre avec confiance (score < 70%), la question est automatiquement ajoutee a la file des **questions non couvertes**.

Le systeme propose une reponse generee par l'IA que vous pouvez valider.

### 7.3. Workflow de validation

Pour chaque question non couverte :

| Action | Effet |
|--------|-------|
| **Approuver** | La reponse proposee est validee telle quelle et sera reinjectee dans la base de connaissances |
| **Modifier** | Vous ajustez la reponse avant validation |
| **Rejeter** | La question est archivee (pas d'ajout a la KB) |

Les questions validees (approuvees ou modifiees) enrichissent automatiquement la base de connaissances, ameliorant progressivement les reponses du chatbot.

**Statuts possibles :**

| Statut | Description |
|--------|-------------|
| En attente (`pending`) | Nouvelle question, non traitee |
| Approuvee (`approved`) | Reponse validee, prete pour injection |
| Modifiee (`modified`) | Reponse ajustee et validee |
| Rejetee (`rejected`) | Question archivee |
| Injectee (`injected`) | Reponse ajoutee a la KB |

---

## 8. Gestion multi-tenant (Super Admin uniquement)

Cette section est reservee aux utilisateurs avec le role **Super Admin**.

### 8.1. Creer un nouveau CRI

1. Aller dans **Gestion des CRI**
2. Cliquer sur **Nouveau CRI**
3. Remplir les champs :
   - **Nom** : nom complet du CRI (ex : "CRI Fes-Meknes")
   - **Slug** : identifiant technique unique (ex : `fes_meknes`) — lettres minuscules, chiffres et underscores
   - **Region** : region administrative
   - **Logo** (optionnel) : URL de l'image
   - **Configuration WhatsApp** (optionnel) : `phone_number_id` et `access_token` Meta
4. Cliquer sur **Creer**

Le systeme cree automatiquement toute l'infrastructure necessaire :
- Schema PostgreSQL dedie
- Collection Qdrant pour les vecteurs
- Bucket MinIO pour les fichiers
- Mappings Redis

### 8.2. Lister les CRI

La liste affiche tous les tenants avec leur statut :
- **Actif** : operationnel
- **Inactif** : desactive (toutes les API retournent 403)
- **En provisionnement** : creation en cours

### 8.3. Modifier un CRI

Vous pouvez modifier : nom, region, logo, couleur accent, quotas (contacts max, messages annuels max, admins max), configuration WhatsApp.

### 8.4. Desactiver / Supprimer un CRI

- **Desactiver** : passe le statut a "Inactif". Le chatbot et le back-office ne fonctionnent plus pour ce CRI, mais les donnees sont conservees.
- **Supprimer** : **IRREVERSIBLE**. Toutes les donnees sont detruites (base de donnees, vecteurs, fichiers, cache).

---

## Annexe A : Codes d'erreur courants

| Code | Signification | Que faire |
|------|--------------|-----------|
| **401** | Session expiree | Se reconnecter |
| **403** | Permissions insuffisantes | Contacter votre administrateur pour verifier votre role |
| **404** | Ressource introuvable | Verifier que vous etes sur le bon tenant |
| **409** | Doublon detecte | Le telephone, email ou slug existe deja |
| **422** | Donnees invalides | Verifier les formats (telephone, CIN, taille fichier) |
| **429** | Trop de tentatives | Patienter quelques minutes avant de reessayer |

---

## Voir aussi

- [Reference API](api-reference.md) — Documentation technique des endpoints
- [Architecture technique](architecture-technique.md) — Fonctionnement interne du systeme
- [Guide de deploiement](guide-deploiement.md) — Installation et configuration
