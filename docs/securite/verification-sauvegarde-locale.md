# Vérification locale d’une sauvegarde Hostinger réelle

Les anciens scripts génériques `scripts/backup/restore.sh` et
`scripts/backup/test_restore.sh` sont désactivés. Le contrôle isolé décrit ici
ne restaure pas la plateforme en production et ne remplace pas une procédure de
reprise complète, qui reste à établir et à tester.

Le 26 novembre 2026, la copie chiffrée du 25 novembre à 21 h 22 UTC a été restaurée deux fois sur l’ordinateur de l’utilisateur. L’empreinte et le déchiffrement ont été contrôlés ; PostgreSQL, MinIO et Qdrant ont été restaurés dans des volumes Docker temporaires `tmpfs`, avec un Redis neuf. L’API et ses quatre dépendances ont démarré sur un réseau interne sans port publié. La base contenait six documents ONSSA indexés ; un fichier MinIO a été relu et un point Qdrant a été rapproché de son document PostgreSQL. Les conteneurs, volumes, réseau et fichiers temporaires ont ensuite été supprimés.

Ce contrôle porte sur **une archive datée et un échantillon**, pas sur tous les fichiers, toutes les recherches ou une conversation IA. L’archive est antérieure aux derniers changements et aux rotations de certains secrets. Avant toute remise en ligne après une véritable restauration, les secrets exposés doivent être renouvelés. Redis est volontairement recréé vide afin de ne pas rejouer d’anciennes tâches. Les systèmes `tmpfs` peuvent utiliser le swap de l’ordinateur : ils ne garantissent pas l’absence de traces sur disque.

## Refaire le contrôle

Prérequis : Docker local sous Linux/WSL avec un daemon de confiance, GnuPG, Python 3, les images `postgres:16-alpine`, `redis:7-alpine`, `qdrant/qdrant:v1.12.1`, `dappros/minio:RELEASE.2025-09-07T16-13-09Z`, et une image backend locale construite depuis le dépôt. Prévoir suffisamment de place dans `/dev/shm` et en mémoire. Vérifier le nom du daemon local avec `docker info --format '{{.Name}}'` ; le script refuse les contextes Docker distants et les variables `DOCKER_HOST` ou `DOCKER_CONTEXT`.

La commande `scripts/backup/test-local-real-restore.sh` exige les variables `BACKUP_DIR`, `BACKUP_EXPECTED_DAEMON` et `BACKUP_TEST_BACKEND_IMAGE`. La variable facultative `BACKUP_ARCHIVE_NAME` permet de choisir une archive datée dans le même dossier ; son fichier `.sha256` doit porter le nom complet de l’archive suivi de `.sha256`. Par défaut, le script contrôle la première archive `donnees-hostinger.tar.gz.gpg` et son fichier `donnees-hostinger.sha256`. Elle lit la phrase de passe GPG sur son entrée standard. Ne la placer ni dans les arguments d’une commande, ni dans un journal, ni dans une conversation. Le script vérifie l’empreinte, refuse les chemins d’archive dangereux, ne publie aucun port et supprime ses propres ressources à la fin ; vérifier sa sortie et sa réussite. Il faut traiter toute erreur de nettoyage avant un nouvel essai.

Sur cet ordinateur, la phrase de passe est protégée par DPAPI pour le compte Windows actuel. La copie du dossier sans ce compte ou sans une procédure de récupération portable peut être inutilisable ailleurs. Conserver une seconde copie indépendante ainsi qu’un moyen de récupération séparé et testé ; la sauvegarde n’est pas encore planifiée automatiquement.

## Reprise après interruption de la sauvegarde à froid

Avant d'arrêter les services, le script enregistre leur liste dans `.cold-backup-services`, dans le répertoire de sauvegarde. En cas d'arrêt brutal du processus, ce journal reste en place et toute nouvelle sauvegarde est refusée. Après avoir vérifié qu'aucune sauvegarde ni maintenance KMS n'est active et que la configuration Compose n'a pas changé, exécuter sur le VPS :

```bash
cd /opt/chatbot-demo
bash scripts/backup/hostinger-cold-backup.sh --recover
```

La reprise utilise les mêmes verrous que la sauvegarde, refuse un journal KMS inachevé, redémarre les services enregistrés et conserve le journal si le démarrage ou le contrôle de disponibilité échoue. Vérifier ensuite l'état de la plateforme. Le script `hostinger-backup-recovery-guard.sh` peut être appelé régulièrement par le planificateur de l'hôte ; il ne tente rien tant que le verrou de sauvegarde est occupé. La planification doit être installée et surveillée séparément. Elle ne garantit pas la reprise après une coupure électrique au moment de l'écriture du journal. Les tâches Redis en attente ne sont pas incluses dans l'archive.

## Sauvegarde planifiée sur le VPS

`scripts/backup/hostinger-scheduled-backup.sh` utilise une clé publique `recipient-public.asc` dans le répertoire de sauvegarde et lance la sauvegarde à froid. La plateforme peut être indisponible pendant l'opération. Les workers actifs ont un délai de terminaison, mais une tâche bloquée ou dépassant son délai peut encore être interrompue. Le script refuse de démarrer s'il reste moins de 10 Gio libres ou si 120 archives existent déjà ; il ne supprime aucune archive. Ces seuils ne garantissent pas qu'une archive volumineuse tiendra sur le disque.

Le fichier `scheduled-backup.status` indique le dernier résultat et la date ; le journal de l'exécution doit également être surveillé. Un résultat `success` signifie que l'archive chiffrée et sa somme de contrôle existent et concordent, et que les services ont redémarré ; il ne prouve ni le déchiffrement, ni une restauration complète, ni l'existence d'une copie hors du VPS. Un processus tué brutalement peut laisser un état ancien : vérifier aussi son âge. Le contrôle des sauvegardes ne transmet pas d'alerte externe. Maintenir une copie indépendante, tester régulièrement la restauration et gérer la rétention avant d'atteindre la limite.

Le contrôle `scripts/backup/check-hostinger-backup.sh` retourne un code non nul si le dernier succès date de plus de 30 heures, si l'archive ou son fichier de somme manque, si le témoin du surveillant date de plus de cinq minutes ou si un journal de reprise est présent sans sauvegarde active. Il vérifie l'existence des fichiers, sans recalculer le SHA-256 ni tester la restauration. Il peut être exécuté périodiquement et ses erreurs enregistrées dans le journal système ; un journal local ne prévient personne si le serveur est inaccessible, et une surveillance externe reste nécessaire.

Les sauvegardes créées avec la version qui inclut l'antivirus conservent sa
configuration sous `metadata/runtime/docker/clamav/clamd.conf` dans l'archive
chiffrée. Pour restaurer la configuration Compose, recopier ce fichier vers
`docker/clamav/clamd.conf` dans le répertoire de déploiement avant de démarrer
les services. Les signatures antivirus ne sont pas sauvegardées : leur
téléchargement et leur fraîcheur doivent être vérifiés après restauration. Les
archives plus anciennes ne contiennent pas ce fichier et nécessitent la
configuration correspondant à leur version du dépôt.

## Copie actualisée

La capture du 25 novembre à 23 h 54 UTC a également été transférée, contrôlée et restaurée en local le 26 novembre. Les services restaurés sont sains, les six documents ONSSA indexés sont présents, et un objet MinIO et son point Qdrant ont été vérifiés sur un échantillon. L’archive s’appelle `donnees-hostinger-20261125T235444Z.tar.gz.gpg` ; choisir ce nom avec `BACKUP_ARCHIVE_NAME` pour la contrôler. Les deux archives restent sur le même ordinateur et partagent le même trousseau : une copie indépendante et une récupération portable restent nécessaires.
