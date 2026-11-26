# Recherche ONSSA — essai exploratoire du 26 novembre 2026

Cet essai porte sur les 50 questions candidates de `evaluation-candidats.json`,
qui ne sont pas validées par un expert. Il évalue la recherche de passages,
pas l'exactitude des réponses générées, des citations ni des traductions.
L'index de démonstration contenait six documents et utilisait
`gemini-embedding-001` avec un maximum de cinq résultats par recherche. Les
questions ont été traitées individuellement, sans filtre strict de langue
quand aucun passage n'existe dans la langue demandée.

| Questions avec source candidate | Source attendue dans les trois premiers passages | Extrait candidat exact dans les cinq premiers |
|---|---:|---:|
| Français | 38 / 39 | 38 / 39 |
| Arabe | 6 / 6 | 6 / 6 |
| Total | 44 / 45 | 44 / 45 |

Les 50 recherches, dont cinq questions négatives non comprises dans ce tableau,
ont abouti sans erreur. La latence médiane de recherche mesurée dans le
processus du serveur était de 252 ms ; elle ne comprend pas la génération de
réponse ni le temps de chargement de l'interface.

Le cas `candidate-08` n'a retrouvé ni la source ni l'extrait proposés parmi les
cinq premiers passages, malgré un score de recherche considéré comme confiant.
Sa formulation parle de « cette fiche » sans identifier la fiche ; d'autres
documents peuvent justifier une réponse de portée différente. Un essai manuel
du chat a répondu que la fiche ne remplace pas les instructions officielles et
a cité trois autres pages. Il faut faire examiner ce cas et ses sources avant
de conclure à une erreur de recherche ou à une réponse correcte.

Le rapprochement est fondé sur l'URL exacte de la source candidate et sur la
présence textuelle de l'extrait proposé après normalisation des espaces et des
caractères Unicode. Il ne tient pas compte de toutes les sources alternatives
possibles. Les résultats négatifs ne mesurent pas l'abstention du modèle. Les
résultats peuvent changer avec les documents, le fournisseur de modèles et la
configuration. Une validation humaine de la formulation, des références et
des réponses reste nécessaire avant d'utiliser ces chiffres comme indicateurs
institutionnels.
