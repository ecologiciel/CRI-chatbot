# Répétition de séparation des rôles PostgreSQL

L'installation observée utilise le même compte PostgreSQL pour l'API et pour
l'administration de la base. Ce compte est superutilisateur et propriétaire
de `public.audit_logs`. Il peut modifier, supprimer ou tronquer ce journal :
les droits actuels ne garantissent donc pas son immutabilité.

`scripts/prepare-runtime-db-role.sql` est une expérience réservée à une base
jetable. Elle crée un groupe sans connexion et sans attributs de superutilisateur,
accorde les opérations applicatives et réserve l'audit à la lecture et à l'ajout.
Elle refuse une table d'audit dont les droits publics permettraient une mutation.
Elle n'installe aucun mot de passe et n'octroie le groupe à aucun utilisateur.

La répétition minimale vérifie l'ajout au journal, le refus de modifier, supprimer
ou tronquer le journal et de changer la version Alembic, la lecture et l'écriture
d'un schéma d'institution existant, ainsi que la création et la suppression d'un
nouveau schéma. Elle ne prouve pas l'isolation entre institutions au niveau des
droits SQL : le groupe expérimental possède l'accès aux schémas existants.

Une seconde répétition sur le VPS a restauré uniquement la structure de la base
de production dans PostgreSQL 16 isolé. Avec un identifiant synthétique membre
du groupe, le vrai service de provisionnement a créé puis supprimé un schéma
d'institution synthétique ; l'ajout à l'audit a réussi et les mutations de
l'audit et de la version Alembic ont été refusées. La suppression de la copie
du schéma ONSSA existant a aussi été refusée. La base réelle et ses données
n'ont pas été modifiées. Cette répétition ne valide ni l'ensemble des services
ni les privilèges originaux, exclus de la copie de structure.

La suppression d'un schéma existant échoue car il appartient encore au rôle
de migration. Une fonction expérimentale `rehearsal_drop_tenant_schema` est
préparée dans `scripts/rehearse-tenant-schema-drop.sql` pour une base jetable :
elle refuse les institutions actives et les identifiants invalides, vérifie la
ligne de l'institution sous verrou et écrit un audit dans la transaction de
suppression. Son appel par l'application est désactivé par défaut. Cette
fonction s'exécute avec les droits de son propriétaire : il faut contrôler son
installation, son propriétaire et les droits `EXECUTE` avant toute utilisation.
Un rôle applicatif compromis peut encore modifier les institutions auxquelles il
a accès ; cette fonction ne constitue pas une isolation SQL entre institutions.

Les droits sur les objets créés par les migrations suivantes ne
sont pas attribués automatiquement. Avant toute activation il reste notamment
à vérifier la fonction sur une copie du schéma réel, séparer les identifiants de migration,
bootstrap, sauvegarde et application, vérifier tous les workers, protéger les
secrets et préparer le retour arrière. Ne pas appliquer ce script en production
comme procédure de déploiement.
