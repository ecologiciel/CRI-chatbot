# Renouvellement de la clé maîtresse : état de préparation

La clé maîtresse `KMS_MASTER_KEY` protège les clés de données enregistrées dans
`public.tenant_keys`. Le module `master_key_rotation.py` permet de réemballer
toutes les clés actives et historiques dans une transaction PostgreSQL : il
authentifie chaque enveloppe avant toute modification, verrouille la table et
annule la transaction en cas d'erreur. Les tests incluent une base PostgreSQL
isolée et une enveloppe corrompue.

Le coordinateur `master_key_coordinator.py` ajoute un journal privé persistant,
un remplacement atomique du fichier de configuration et un retour arrière qui
identifie la clé utilisée par la base. Des tests ont arrêté réellement un
processus après la transaction et après le remplacement du fichier, puis vérifié
le retour arrière sur une base isolée. Une préparation interrompue avant son
marqueur READY peut également être abandonnée après vérification que la clé
de configuration authentifie toujours toutes les enveloppes en base ; les
fichiers inconnus empêchent le nettoyage. Le module `app.scripts.kms_rotation`
expose ces opérations unitaires, mais ne coordonne pas les services.

Un contrôle au démarrage en production authentifie les enveloppes actives et
historiques avant de démarrer l’API ou les workers. Une incohérence empêche
leur démarrage. Il ne surveille pas les processus déjà lancés : tous les
écrivains doivent être arrêtés pendant la rotation.

**Ces modules ne constituent pas encore une procédure de rotation
opérationnelle.** Ils n'arrêtent pas les services et ne vérifient pas que tous
les utilisateurs de clés sont à l'arrêt. Ils ne garantissent pas encore le
maintien en sécurité du démarrage automatique des services après une panne du
VPS. Ne pas les exécuter seuls sur une installation réelle. Une orchestration et un essai de reprise complet restent nécessaires.

Le réemballage conserve les mêmes clés de données : il ne révoque donc pas une
clé de données déjà compromise et ne rechiffre pas les données existantes.
Une rotation effective de ces clés nécessite d'identifier les données
concernées, de gérer les versions et de rechiffrer les données sans perte.

Enfin, l'existence du service KMS ne signifie pas que tous les champs métier
sont chiffrés. Les modèles actuels de contacts et de dossiers contiennent des
champs texte classiques ; leur protection au repos et leur migration doivent
être traitées séparément avant d'utiliser des données institutionnelles
sensibles. Les sauvegardes chiffrées restent soumises à leur propre procédure
de conservation et de restauration.
