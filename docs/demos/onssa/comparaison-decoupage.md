# Comparaison exploratoire du découpage ONSSA

Mesure de référence réalisée le 25 novembre 2026 avec le découpeur du commit `c936efa` et `python -m app.scripts.compare_onssa_chunking --pdf CHEMIN.pdf` depuis `backend`, sur les sept fiches du dépôt et sur la [loi 76-17 diffusée par l’ONSSA](https://www.onssa.gov.ma/wp-content/uploads/2023/01/LOI.76-17.FR_.pdf). Le PDF a été téléchargé séparément pour l’essai ; il n’a pas été importé dans la base de la démonstration. SHA-256 : `63c9d82a879d8b68b2661db81442d5cad7a104d4f1172312592bde18f2f4330d`. Les 19 pages contiennent du texte extrait ; ceci ne vérifie pas que l’extraction est fidèle ou complète.

Les sept fiches courtes produisent 16 passages et 2 091 tokens pour chacune des neuf configurations. Les 45 extraits attendus des questions candidates sont entièrement présents dans au moins un passage. Les cinq questions négatives sont exclues de cette mesure. Ces annotations ne sont pas validées par un expert, et cette présence ne mesure ni la recherche ni la qualité des réponses.

| Cible tokens | Chevauchement | Passages PDF | Tokens dans les passages | Passages associés à une ou plusieurs pages |
| --- | --- | ---: | ---: | ---: |
| 256 | 0 % | 75 | 15 896 | 75 |
| 256 | 10 % | 82 | 17 849 | 82 |
| 256 | 20 % | 98 | 20 716 | 98 |
| 512 | 0 % | 37 | 15 889 | 37 |
| 512 | 10 % | 41 | 17 884 | 41 |
| 512 | 20 % | 47 | 20 520 | 47 |
| 768 | 0 % | 24 | 15 893 | 24 |
| 768 | 10 % | 28 | 17 911 | 28 |
| 768 | 20 % | 32 | 20 604 | 32 |

Tous les passages sont des extraits exacts du texte extrait, sans trou entre passages et dans la limite de tokens testée. La présence d’un numéro de page ne prouve pas qu’une citation soit correcte. Ces résultats comparent la structure et le volume, pas Recall@5, la fidélité des réponses, les tableaux ou la qualité des références de pages. La version officielle du Bulletin officiel reste la référence juridique.

Sur ce PDF, le chevauchement accroît le volume de tokens d’environ 12 à 30 % par rapport à 0 %, selon la cible. Cela ne prouve pas qu’il soit inutile : il faut comparer le rappel et les citations sur des questions annotées et des documents représentatifs, puis mesurer les coûts et les latences en conditions réelles avant de choisir une configuration. Le réglage de production reste inchangé.

## Reconnaissance des articles : essai après correction

Sur le même PDF, 61 titres d’articles isolés ont été repérés ; les 60 intervalles entre titres consécutifs ont servi de mesure exploratoire. Avant correction, avec 10 % de chevauchement, respectivement 18 des 38 articles pouvant tenir dans 256 tokens, 16 des 54 pouvant tenir dans 512 tokens et 17 des 59 pouvant tenir dans 768 tokens étaient coupés. Après reconnaissance des titres d’articles et priorité aux limites de section, aucun de ces articles n’est coupé dans les trois configurations. Les articles trop longs restent découpés sous la limite technique. Le dernier article est exclu de ce comptage car sa fin n’est pas déterminée par un titre suivant ; la mesure ne prouve pas l’exactitude juridique des limites détectées.

Cette reconnaissance s’applique aux titres autonomes « Article N », « Art. N » et « المادة N » et ignore ceux placés dans un bloc de code. La recherche et la qualité des réponses doivent encore être évaluées avant de modifier les réglages de production ou de réindexer les documents existants.

## Essai d'une FAQ étiquetée

Le 26 novembre 2026, un fichier texte fictif comportant trois paires
« Question : / Réponse : » a été importé et validé par API dans une institution
temporaire isolée sur le VPS. Les trois paires étaient chacune réunies dans un
passage indexé. Le chat a répondu à une question sur la deuxième paire avec la
valeur attendue et une source. L'institution temporaire a ensuite été supprimée
par API (204).

Cet essai couvre une FAQ courte et explicitement étiquetée, pas toutes les
présentations possibles ni le parcours d'import dans l'interface. Les réponses
qui dépassent la limite restent découpées, et les documents déjà indexés ne
sont pas retraités automatiquement.

## Contrôle du découpage optimisé sur le VPS

Après optimisation le 26 novembre 2026, le PDF de la loi 76-17 identifié en
tête de ce document a été extrait et découpé en mémoire sur le VPS. L'empreinte
du fichier correspondait à celle déjà relevée. Les 19 pages contenaient du texte
extrait ; le découpeur a produit 68 passages, chacun sous la limite testée de
512 tokens, avec des offsets exacts et sans trou dans le texte extrait. Un
passage contenant le titre de l'article 4 indiquait la page physique 2.

L'extraction a pris environ 2,83 secondes et le découpage 0,15 seconde lors de
cet appel unique. Ces chiffres ne comprennent ni l'antivirus, ni les appels
au fournisseur d'IA, ni la publication ; ils ne sont pas comparables au test
local synthétique avant optimisation. Le fichier n'a pas été importé dans la
base ONSSA lors de ce contrôle, qui ne valide ni la fidélité complète de
l'extraction ni l'exactitude des réponses du chatbot.

## Mesure locale sur une FAQ volumineuse

Un document synthétique de 4 000 paires étiquetées a été découpé sur le poste
de développement avant et après optimisation. Le temps observé est passé de
32,9 à 0,8 seconde ; les deux essais ont produit les mêmes 4 000 plages de
caractères. Ce résultat ponctuel concerne uniquement le découpage, pas l'import
complet : l'indexation de 4 000 passages peut toujours demander du temps et
générer des coûts auprès du fournisseur d'IA. Il ne préjuge pas non plus des
performances de tous les formats ou d'un chargement simultané multi-utilisateur.
