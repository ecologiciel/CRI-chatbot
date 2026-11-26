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

## Essai des cinq questions sans réponse précise attendue

Les cinq questions candidates négatives ont ensuite été envoyées au chatbot
public, chacune dans une nouvelle session. Les réponses observées le
26 novembre 2026 sont résumées ci-dessous ; cet essai ponctuel ne garantit pas
que les réponses seront identiques lors d'un prochain appel.

| Cas | Observation | Durée approximative |
|---|---|---:|
| 46 — frais en 2027 | N'a pas donné de tarif ; renvoie aux services compétents. | 18 s |
| 47 — délai garanti | N'a pas donné de délai garanti ; renvoie à l'ONSSA. | 11 s |
| 48 — envoi de tomates | N'a pas validé l'envoi ; indique que la certification n'est pas automatique. | 27 s |
| 49 — sanction individuelle | N'a pas donné de sanction pour une entreprise particulière. | 13 s |
| 50 — frais en arabe | N'a pas inventé de montant, mais a qualifié la question de hors périmètre alors qu'elle concerne la certification. | 11 s |

Le dernier cas illustre une orientation trompeuse à corriger ou à évaluer plus
largement ; il ne suffit pas qu'aucun montant ne soit inventé. Les réponses ont
été lentes pour une démonstration interactive. Sur ces appels, les journaux
montrent des recherches documentaires d'environ 0,25 à 0,30 seconde et des
étapes de génération variables, dépassant parfois dix secondes ; le reste du
temps inclut d'autres étapes et les échanges réseau. Cet échantillon ne suffit
pas à établir un percentile ni à attribuer tout le délai à un seul composant.
Les formulations et affirmations accessoires doivent également être examinées
par une personne compétente avant usage institutionnel.

## Essai d'un PDF ONSSA de 19 pages

Le 26 novembre 2026, une institution temporaire isolée a été créée sur le VPS
pour importer la [loi 76-17 diffusée par l'ONSSA](https://www.onssa.gov.ma/wp-content/uploads/2023/01/LOI.76-17.FR_.pdf).
Son empreinte SHA-256 correspondait à celle indiquée dans
`comparaison-decoupage.md`. Après validation, le document a été indexé en
68 passages. L'institution temporaire a ensuite été supprimée par l'API (204) ;
le corpus de la démonstration ONSSA n'a pas été modifié.

À la question « Selon l'article 4, quel type de veille l'autorité compétente
assure-t-elle sur le territoire national ? », le chatbot a répondu qu'elle
assure une veille phytosanitaire permanente, ce qui correspond au texte de la
page physique 2 du PDF. Les pages retournées pour le document étaient 2, 3, 7,
8, 10 et 14 : elles représentent les pages des passages consultés, pas une
attribution vérifiée de chaque affirmation à une page précise.

Cet essai porte sur une seule question et ne démontre pas la fidélité de toutes
les réponses ni la qualité de l'extraction des tableaux ou des autres PDF. Le
texte officiel applicable et l'interprétation juridique restent à vérifier
auprès des sources compétentes avant tout usage institutionnel.
