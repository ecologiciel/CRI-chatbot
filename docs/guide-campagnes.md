# Guide — Campagnes de Publipostage WhatsApp

> Module Phase 2 — Envoi de messages WhatsApp en masse a partir de templates Meta prevalides.

## Presentation

Le module Campagnes permet d'envoyer des messages WhatsApp personnalises a un ensemble de contacts cibles. Les messages utilisent des **templates prevalides par Meta** et peuvent etre planifies ou envoyes immediatement.

## Pre-requis

- Disposer de **templates WhatsApp valides** (prevalides par Meta dans le Business Manager)
- Les contacts doivent etre en statut **opt-in** (les contacts ayant envoye "STOP" sont automatiquement exclus)
- Le **quota annuel** (100 000 messages/an/tenant) ne doit pas etre depasse

## Creer une campagne

1. Menu lateral → **Campagnes** → bouton **"+ Nouvelle campagne"**
2. Renseigner le **nom** de la campagne
3. Selectionner un **template WhatsApp** prevalide
4. Definir l'**audience** :
   - Par tags (ex : `investisseur`, `region-rsk`)
   - Par langue (francais, arabe, anglais)
   - Par statut opt-in
5. **Mapper les variables** du template (ex : `{{1}}` = nom du contact, `{{2}}` = numero de dossier)
6. **Previsualiser l'audience** : verifier le nombre de destinataires et l'echantillon
7. Choisir : **lancer immediatement** ou **planifier** a une date future

## Cycle de vie d'une campagne

```
[draft] → [scheduled] → [sending] → [completed]
                            ↓
                        [paused] → [sending]
```

| Statut | Description |
|--------|-------------|
| `draft` | Brouillon, modifiable |
| `scheduled` | Planifiee, envoi a la date prevue |
| `sending` | Envoi en cours |
| `paused` | Mise en pause (peut etre reprise) |
| `completed` | Tous les messages ont ete envoyes |
| `failed` | Erreur critique (quota depasse, template invalide) |

## Quota WhatsApp

Chaque tenant CRI dispose de **100 000 messages WhatsApp par an** (duree du marche).

Le compteur de quota est visible :
- Dans la page **Campagnes** (barre de progression)
- Via l'endpoint `GET /api/v1/campaigns/quota`

**Alertes automatiques :**
- A **80%** d'utilisation : notification d'avertissement
- A **95%** d'utilisation : notification critique

## Suivi des statistiques

Pour chaque campagne, les statistiques suivantes sont disponibles en temps reel :

| Metrique | Description |
|----------|-------------|
| **Envoyes** | Messages transmis a l'API WhatsApp |
| **Delivres** | Messages arrives sur le telephone du destinataire |
| **Lus** | Messages ouverts et lus par le destinataire |
| **Echoues** | Messages en erreur (numero invalide, blocage, etc.) |
| **Taux de livraison** | % delivres / envoyes |
| **Taux de lecture** | % lus / delivres |

## Contacts exclus

Les contacts suivants sont **automatiquement exclus** de toute campagne :
- Contacts en statut **opt-out** (ont envoye "STOP")
- Contacts sans numero de telephone valide
- Contacts marques comme inactifs

Cette exclusion est conforme a la reglementation CNDP (loi 09-08).

## Bonnes pratiques

- Testez votre campagne avec un **petit groupe** avant un envoi massif
- Utilisez la **previsualisation d'audience** pour verifier les filtres
- **Planifiez** les envois aux heures ouvrables (9h-18h)
- Surveillez le **taux d'echec** : un taux eleve peut indiquer des numeros obsoletes
- Mettez a jour regulierement votre base de contacts pour maintenir la qualite
