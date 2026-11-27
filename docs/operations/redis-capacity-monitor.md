# Surveillance locale de Redis

La file de travaux et les sessions utilisent le même Redis. La politique `noeviction` empêche son remplacement silencieux de clés quand la limite mémoire est atteinte ; une écriture supplémentaire échoue alors et le service peut devenir indisponible. Elle ne garantit pas à elle seule la durabilité des messages.

`scripts/check_redis_capacity.sh` signale dans sa sortie d'erreur une politique incorrecte, une mémoire utilisée d'au moins 80 % de la limite, des clés évincées depuis le dernier démarrage, un journal AOF indisponible ou un contrôle impossible. Il ne révèle pas les identifiants ni les clés. Le code de sortie vaut zéro uniquement si tous les contrôles passent.

Sur le VPS, la tâche cron installée par l'exploitant écrit les erreurs dans le journal système sous `chatbot-redis-monitor`. Surveiller ce journal depuis un système indépendant ; un journal local ne prévient pas lorsque le VPS est inaccessible. Dimensionner Redis, traiter les files et prévoir la reprise avant saturation. L'AOF ne remplace ni une sauvegarde indépendante ni un test de restauration.
