# Conservation des copies d'import de dossiers

Le traitement est désactivé par défaut (`DOSSIER_IMPORT_RETENTION_DAYS=0`). Une
durée de 1 à 3650 jours ne doit être configurée qu'après validation d'une
politique applicable à toutes les institutions de cette installation. Le mode
d'import durable doit aussi être activé et le worker de purge redémarré.

Le traitement concerne uniquement les instantanés générés par la plateforme
pour les demandes terminées ou échouées et dont la date de dernière mise à jour
précède la durée configurée. Les demandes en attente, actives ou incertaines
restent conservées. Les noms de fichiers et le contenu ne sont pas inscrits
dans les journaux. Une intention de suppression est auditée avant l'appel au
stockage et un second événement est enregistré après son succès. Si le
stockage ou la confirmation d'audit échoue, la demande reste en cours de purge
et une exécution ultérieure réessaie la suppression, qui doit être idempotente.

Cette opération ne supprime pas les fichiers d'origine des dossiers surveillés,
les instantanés orphelins, les informations du registre, les versions d'objets
S3, ni les sauvegardes ou journaux de base de données. Leur conservation exige
une politique et des procédures complémentaires. Une suppression réussie par
l'API S3 ne prouve pas l'effacement physique de toutes les copies. Il faut
surveiller les erreurs `import_source_retention_failed` et vérifier la version
et la configuration du stockage avant toute activation.
