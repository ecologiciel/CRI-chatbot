# Guide — Gestion des Escalades

> Module Phase 2 — Transfert de conversations WhatsApp vers un agent humain CRI.

## Qu'est-ce qu'une escalade ?

Une escalade est le transfert d'une conversation WhatsApp du chatbot IA vers un agent humain du CRI. Le chatbot met la conversation en pause et un superviseur prend le relais pour repondre directement a l'utilisateur.

## Les 6 scenarios de declenchement

| Scenario | Declencheur | Priorite |
|----------|-------------|----------|
| **Demande explicite** | L'utilisateur demande a parler a un agent humain | Haute |
| **Echec RAG repete** | Le chatbot n'a pas su repondre (score confiance < seuil) apres plusieurs tentatives | Haute |
| **Sujet sensible** | Le chatbot detecte un sujet necessitant une intervention humaine (reclamation, litige) | Haute |
| **Feedback negatif** | L'utilisateur donne un feedback negatif et demande a parler a un agent | Moyenne |
| **Timeout OTP** | Echec repete de verification OTP (suivi de dossier) | Basse |
| **Intervention manuelle** | Un administrateur declenche l'escalade depuis le back-office | Variable |

## Acceder aux escalades

Depuis le back-office : **menu lateral** → **Escalades**.

La page affiche :
- Le compteur d'escalades en attente
- La file d'attente triee par priorite (haute en premier) puis anciennete
- Les statistiques globales (temps moyen de resolution, taux de traitement)

## Notifications temps reel

Les nouvelles escalades apparaissent automatiquement grace a la connexion WebSocket. Vous recevez une notification sonore et visuelle des qu'une nouvelle escalade est creee.

Evenements en temps reel :
- **Nouvelle escalade** — apparait dans la file d'attente
- **Escalade assignee** — un collegue a pris en charge
- **Escalade resolue** — une escalade a ete cloturee

## Prendre en charge une escalade

1. Cliquer sur une escalade dans la file d'attente
2. Lire le **resume IA** : un resume automatique du contexte de la conversation
3. Consulter l'**historique de conversation** : tous les messages echanges entre l'utilisateur et le chatbot
4. Cliquer **"Prendre en charge"** pour s'assigner l'escalade
5. Rediger votre reponse dans le champ de texte
6. Cliquer **"Envoyer"** — le message est envoye directement sur WhatsApp a l'utilisateur
7. Vous pouvez envoyer plusieurs messages si necessaire
8. Une fois la demande resolue, cliquer **"Cloturer"** avec une note de resolution obligatoire

## Apres la cloture

Lorsqu'une escalade est cloturee :
- La conversation WhatsApp revient en **mode automatique** (le chatbot reprend)
- La note de resolution est archivee dans l'audit trail
- L'escalade apparait dans les statistiques

## Indicateurs de priorite

- 🔴 **Haute** : demande explicite d'agent, echec RAG repete, sujet sensible
- 🟡 **Moyenne** : feedback negatif avec demande d'agent
- 🔵 **Basse** : timeout OTP, autres situations

## Cycle de vie d'une escalade

```
[pending] → [assigned] → [in_progress] → [resolved/closed]
```

| Statut | Description |
|--------|-------------|
| `pending` | En attente dans la file, aucun agent assigne |
| `assigned` | Un agent a pris en charge |
| `in_progress` | L'agent a commence a repondre |
| `resolved` | L'escalade est cloturee avec une note de resolution |

## Bonnes pratiques

- Traitez les escalades **haute priorite** en premier
- Consultez toujours le **resume IA** et l'historique avant de repondre
- Redigez une **note de resolution** detaillee pour le suivi
- Si la question est recurrente, pensez a enrichir la base de connaissances via le module **Apprentissage supervise**
