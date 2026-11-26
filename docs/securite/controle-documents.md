# Contrôle des documents importés

Sur Hostinger, les nouveaux documents passent par ClamAV avant leur stockage et sont
analysés à nouveau avant extraction et indexation. Un résultat positif refuse le
document. Si le service est inaccessible, ne répond pas ou si ses signatures ont
plus de sept jours, l'import est refusé temporairement. Un document déjà indexé
détecté lors d'une réindexation est retiré de la recherche jusqu'à sa correction.

Le service met ses signatures à jour automatiquement et n'expose aucun port sur
Internet. Ses données de signatures peuvent être téléchargées à nouveau et ne
sont pas incluses dans la sauvegarde métier. Le démarrage initial peut prendre
plusieurs minutes. Les journaux et l'état du service `antivirus` permettent de
diagnostiquer une indisponibilité ; ne pas y inclure de contenu confidentiel.

Les fichiers DOCX sont aussi vérifiés avant extraction : 2 048 entrées au maximum,
10 Mio par entrée, 50 Mio décompressés au total. Les archives imbriquées, objets
incorporés, macros, contenus chiffrés et chemins non sûrs sont refusés. Les PDF
chiffrés non analysables sont refusés par l'antivirus. Ces contrôles ne garantissent
pas l'absence de logiciel malveillant et ne remplacent pas la validation humaine.

Sur Hostinger, le worker transmet le fichier à un service d'extraction distinct,
sans identifiants applicatifs, sans accès aux bases et sans réseau extérieur. Le
service utilise un processus enfant par fichier et des limites de temps, mémoire
et taille ; le conteneur est en lecture seule avec capacités Linux retirées. Si le
service échoue ou est indisponible, l'indexation échoue sans retour silencieux à
l'extraction dans le worker. Ce confinement par conteneur réduit la surface
d'exposition : il ne constitue pas une machine virtuelle ni une garantie absolue
d'isolation ou d'absence de vulnérabilités.
