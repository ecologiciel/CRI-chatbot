# Essai exploratoire du seuil de recherche ONSSA — 28 novembre 2026

Cet essai mesure uniquement la moyenne des scores de recherche, après le déploiement de validation des embeddings. Il ne mesure pas la correction des réponses, l'adéquation exacte des passages ou la qualité de l'arabe. Les étiquettes de réponse attendue des deux jeux de questions sont candidates et n'ont pas été validées par un expert. Les six documents de démonstration ONSSA étaient indexés. Le repli de langue était actif et chaque question a été traitée individuellement.

L'échantillon comporte huit questions du jeu pilote (sept étiquetées répondables, une non répondable), six questions arabes candidates étiquetées répondables et cinq autres questions candidates étiquetées non répondables. Aucune génération de réponse n'a été demandée lors de cet essai.

| Groupe candidat | Nombre | Score de recherche min.–max. | Score inférieur à 0,7 | Score inférieur à 0,5 |
|---|---:|---:|---:|---:|
| Répondables en français | 7 | 0,6355–0,7227 | 5 | 0 |
| Répondables en arabe | 6 | 0,6107–0,6670 | 6 | 0 |
| Non répondables en français | 5 | 0,6160–0,6555 | 5 | 0 |
| Non répondables en arabe | 1 | 0,5942 | 1 | 0 |

Sur cet échantillon, refuser toute réponse sous 0,7 aurait refusé 11 des 13 questions étiquetées répondables. Le seuil de 0,5 retenu pour bloquer les résultats très faibles n'aurait arrêté aucune des six questions étiquetées non répondables. Ce seuil est une protection limitée alignée sur le déclencheur existant d'escalade, et ne constitue pas un détecteur de vérité ou d'absence d'information. Les cas au-dessus du seuil peuvent eux aussi produire des réponses incorrectes.

Avant une utilisation institutionnelle, les cas et leurs sources doivent être revus par des personnes compétentes ; il faut ensuite évaluer les réponses et leurs affirmations, les citations, les questions négatives, l'arabe et les comportements d'escalade sur un jeu représentatif plus large.
