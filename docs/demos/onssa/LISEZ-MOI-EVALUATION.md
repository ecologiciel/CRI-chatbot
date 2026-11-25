# Questions candidates pour évaluer la démo ONSSA

Le fichier `evaluation-candidats.json` contient 50 questions proposées : 45 avec
un passage attendu dans le corpus de démonstration et 5 pour lesquelles une
absence de réponse est à vérifier. Il inclut des questions en français et en
arabe. Toutes portent le marqueur `human_reviewed: false` : elles ne constituent
pas un jeu de référence validé et ne sont pas importées automatiquement.

Pour chaque question avec réponse attendue, le fichier indique le document,
un extrait littéral de la fiche locale et l'URL officielle associée. Les fiches
sont des extraits ou synthèses de démonstration datés de novembre 2026, et ne
remplacent pas les textes officiels. L'extrait indiqué n'est pas nécessairement
la seule source correcte.

Avant d'ajouter une question à l'évaluation opérationnelle :

1. Vérifier le contenu et son actualité sur le site officiel, ainsi que les
   autres documents de l'institution qui peuvent répondre à la question.
2. Confirmer que le passage proposé suffit à répondre, ou que la réponse est
   effectivement absente du corpus pour les cinq cas négatifs.
3. Vérifier la formulation et la traduction, puis ajouter la question et le
   document attendu dans **Base de connaissances → Évaluation RAG**.
4. Examiner la réponse générée et les passages cités séparément : retrouver un
   document parmi les cinq premiers ne prouve pas qu'une réponse est correcte.

Les documents ONSSA indexés pour cette démo sont en français. Pour le chat et
l'évaluation, une recherche sans filtre de langue est tentée si aucun passage
n'existe dans la langue demandée. La langue des documents consultés apparaît
dans les sources. Six questions arabes candidates ont retrouvé leur passage
attendu dans un essai exploratoire ; les traductions et les réponses générées
doivent encore être évaluées par des personnes compétentes avant de servir
d'indicateur de performance. Les tableaux, les PDF longs et les pages précises
nécessitent également un corpus représentatif supplémentaire.
