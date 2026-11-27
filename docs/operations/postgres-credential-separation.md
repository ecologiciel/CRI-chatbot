# Séparation des identifiants PostgreSQL

La configuration Hostinger peut fournir `APP_POSTGRES_USER` et `APP_POSTGRES_PASSWORD` ensemble aux services applicatifs. Si aucun n'est défini, elle conserve temporairement le compte PostgreSQL historique. Si un seul est défini, le démarrage de l'application échoue : les deux valeurs doivent être installées ensemble par une procédure sécurisée.

Le service ponctuel `db-migrate`, dans le profil `maintenance`, utilise `POSTGRES_USER` et `POSTGRES_PASSWORD` et non les identifiants applicatifs. Le démarrage ponctuel `demo-bootstrap` utilise également le compte de maintenance. Ces services ne constituent pas une séparation physique : les secrets de maintenance restent présents dans l'environnement de déploiement et doivent être protégés.

Ne pas activer un compte limité avant de vérifier ses droits effectifs, les migrations, les workers, le provisionnement et la récupération, puis de préparer une procédure de retour arrière. Ce mécanisme ne prouve pas l'isolation SQL entre institutions et ne modifie pas automatiquement le rôle PostgreSQL existant.
