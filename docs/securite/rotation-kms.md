# Rotation hors ligne de la clé maîtresse KMS

Cette procédure réemballe les clés de données actives et historiques avec une
nouvelle clé maîtresse. Elle ne renouvelle pas les clés de données elles-mêmes,
ne révoque pas une copie déjà compromise et ne chiffre pas les champs métier
stockés en clair. Ne pas présenter cette opération comme une mise en conformité.

## Conditions préalables

- Prévoir une interruption : l'API et les trois workers sont arrêtés pendant
  l'opération. Aucun opérateur ni processus externe ne doit écrire dans la table
  `public.tenant_keys` ou modifier `.env.demo` et les fichiers Compose.
- Disposer d'une sauvegarde chiffrée récente, copiée hors du VPS, déchiffrée et
  restaurée sur un environnement isolé. Le contrôle automatique vérifie son âge,
  son empreinte et son format OpenPGP ; il **ne prouve pas** qu'elle soit
  déchiffrable ou restaurable.
- Exécuter l'outil depuis un environnement Linux de confiance avec Python 3,
  GnuPG, Docker Compose et le socket Docker. Le répertoire de déploiement et
  celui de la sauvegarde doivent être accessibles aux mêmes chemins absolus par
  l'outil et par le daemon Docker. Seul le compte administrateur doit y accéder.
- Vérifier que les quatre services `backend`, `ingestion-worker`,
  `learning-worker`, `purge-worker` sont présents, démarrés et utilisent la
  même image. Tout autre conteneur détecté avec une clé KMS sur le réseau de
  données bloque l'opération. Cette détection ne remplace pas le contrôle des
  accès directs à PostgreSQL ou des opérateurs extérieurs.

## Exécution et reprise

`scripts/kms_rotation_operator.py rotate --backup CHEMIN_ABSOLU` vérifie la
sauvegarde, prend un verrou exclusif commun avec la sauvegarde, désactive la
politique de redémarrage des écrivains, puis les arrête avant de changer la
base et la configuration. Après contrôle, il recrée les services et vérifie le
backend. Aucun contenu de clé n'est affiché. Le fichier `.sha256` associé doit
se trouver à côté de l'archive, sous le nom complet de l'archive suivi de
`.sha256`.

Le répertoire privé `.kms-maintenance/` contient temporairement un journal
sensible. Il ne doit être ni partagé, ni supprimé manuellement. En cas d'arrêt
brutal, les anciens conteneurs restent arrêtés avec redémarrage désactivé ;
selon le moment de l'arrêt, certains nouveaux conteneurs peuvent déjà tourner
avec la nouvelle configuration. Relancer
`scripts/kms_rotation_operator.py recover` dans le même environnement après
avoir arrêté toute intervention concurrente. L'outil vérifie les fichiers Compose
et l'image, arrête les écrivains restants, rétablit l'ancien état si nécessaire
ou termine une finalisation déjà engagée, puis redémarre les services. Si la
reprise échoue, conserver le journal et traiter l'erreur : ne pas forcer la
suppression de fichiers ni modifier manuellement les clés.

Une interruption avant que la nouvelle configuration soit complète peut laisser
la plateforme indisponible jusqu'à l'exécution de la reprise. Ce n'est pas une
reprise automatique après redémarrage. Vérifier ensuite la santé des services,
l'accès des institutions et un test du chatbot, sans exposer les secrets.
