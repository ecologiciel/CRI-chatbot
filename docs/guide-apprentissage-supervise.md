# Guide — Apprentissage Supervise

> Module Phase 2 — Amelioration continue de la base de connaissances par validation humaine.

## Principe

Quand le chatbot ne sait pas repondre a une question (score de confiance RAG inferieur au seuil), celle-ci est automatiquement collectee dans une file de revision. Un superviseur CRI peut alors :

1. **Consulter** les questions non couvertes
2. **Generer** une proposition de reponse IA (via Gemini)
3. **Valider**, **modifier** ou **rejeter** la proposition
4. Les reponses validees sont **automatiquement reinjectees** dans la base de connaissances (Qdrant)

Ce cycle d'amelioration continue permet au chatbot de devenir plus performant au fil du temps.

## Acceder aux questions non couvertes

Menu lateral → **Base de connaissances** → onglet **Questions non couvertes**

La page affiche :
- La liste des questions triees par frequence (les plus posees en premier)
- Le statut de chaque question
- Les statistiques globales (taux de validation, temps moyen de traitement)

## Statuts des questions

| Statut | Description |
|--------|-------------|
| `pending` | Nouvelle question, en attente de traitement |
| `proposed` | Proposition IA generee, en attente de validation |
| `approved` | Validee, reinjection dans Qdrant en cours ou terminee |
| `modified` | Proposition editee par un superviseur |
| `rejected` | Rejetee (hors perimetre, non pertinente) |

## Workflow de traitement

### 1. Consulter une question

Cliquer sur une question pour voir :
- Le **texte exact** pose par l'utilisateur
- La **conversation source** (contexte du message)
- Les **chunks recuperes** par le RAG (si disponibles)
- Le **score de confiance** obtenu

### 2. Generer une proposition IA

Cliquer **"Generer proposition IA"**. Le systeme utilise Gemini et le pipeline RAG pour produire une reponse structuree. La proposition est affichee dans un champ editable.

### 3. Valider, modifier ou rejeter

- **Valider** (bouton ✅) : la reponse est acceptee telle quelle. Un worker asynchrone l'injecte dans Qdrant (creation d'un chunk avec embeddings).
- **Modifier** : editez le texte dans le champ, puis validez. La reponse modifiee est celle qui sera reinjectee.
- **Rejeter** (bouton ❌) : indiquez une raison obligatoire (ex : "Question hors perimetre CRI"). La question est archivee sans reinjection.

### 4. Reinjection automatique

Apres validation, un worker asynchrone :
1. Genere les **embeddings** de la reponse validee
2. Cree un nouveau **chunk** dans la collection Qdrant du tenant
3. Met a jour les **metadonnees** (source : apprentissage supervise, date, valideur)

La prochaine fois qu'un utilisateur posera une question similaire, le chatbot trouvera cette reponse dans sa base de connaissances.

## Statistiques

La page affiche les metriques suivantes :

| Metrique | Description |
|----------|-------------|
| **Total** | Nombre total de questions collectees |
| **En attente** | Questions non encore traitees |
| **Taux de validation** | % de questions approuvees vs total traitees |
| **Temps moyen de traitement** | Duree moyenne entre collecte et validation/rejet |
| **Top questions** | Les questions en attente les plus frequentes |

## Bonnes pratiques

- Traitez les questions les plus **frequentes** en priorite (plus d'impact)
- Verifiez toujours la proposition IA avant de valider — le chatbot peut halluciner
- Redigez des reponses dans un **ton institutionnel** (registre formel)
- Si une question revient souvent, envisagez d'ajouter un **document complet** dans la base de connaissances plutot qu'une seule reponse
- Rejetez les questions clairement **hors perimetre** (questions personnelles, spam, etc.)
