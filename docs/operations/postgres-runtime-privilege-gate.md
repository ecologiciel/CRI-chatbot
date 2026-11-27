# Vérification d'un rôle PostgreSQL applicatif

Le contrôle en lecture seule `scripts/check_runtime_db_privileges.py` examine un rôle candidat indiqué par `DB_RUNTIME_ROLE`. Il vérifie les droits sur le journal d'audit et la table de version des migrations, les rôles accessibles par appartenance, les attributs élevés et la création d'objets dans `public`. Une fonction `SECURITY DEFINER` accessible et détenue par un rôle capable de modifier l'audit entraîne un refus conservateur : elle doit être examinée avant toute bascule.

Le contrôle retourne 0 si ces vérifications passent, 1 si elles échouent et 2 s'il ne peut pas vérifier. Il ne modifie aucun privilège. Il doit être exécuté avec un compte de lecture disposant des informations de catalogue nécessaires, sans afficher de mot de passe.

Un résultat positif **ne prouve pas** l'isolation SQL entre institutions, le bon fonctionnement des workers ou du provisionnement, ni la protection des sauvegardes. Avant de changer le compte de production, tester séparément les migrations, le cycle de vie des institutions, tous les workers et le retour arrière sur une copie isolée. Les scripts de répétition actuels restent limités aux bases jetables `ragtest_`.
