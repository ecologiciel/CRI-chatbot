# Renouvellement de la clé maîtresse : état de préparation

La clé maîtresse `KMS_MASTER_KEY` protège les clés de données enregistrées dans
`public.tenant_keys`. Le module `master_key_rotation.py` permet de réemballer
toutes les clés actives et historiques dans une transaction PostgreSQL : il
authentifie chaque enveloppe avant toute modification, verrouille la table et
annule la transaction en cas d'erreur. Les tests incluent une base PostgreSQL
isolée et une enveloppe corrompue.

**Ce module ne constitue pas une procédure de rotation opérationnelle.** Il ne
met pas à jour le fichier de configuration, ne coupe pas les services, ne
coordonne pas le basculement entre la base et le fichier, et ne gère pas une
interruption du processus pendant ce basculement. Ne pas l'exécuter seul sur
une installation réelle. Une procédure avec journal de récupération, arrêt des
écritures, retour arrière et tests d'interruption reste à mettre en place.

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
