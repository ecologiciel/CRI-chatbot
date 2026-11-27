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

La suppression d'un schéma existant échoue car il appartient encore au rôle
de migration. Les droits sur les objets créés par les migrations suivantes ne
sont pas attribués automatiquement. Avant toute activation il reste notamment
à concevoir et tester ces opérations, séparer les identifiants de migration,
bootstrap, sauvegarde et application, vérifier tous les workers, protéger les
secrets et préparer le retour arrière. Ne pas appliquer ce script en production
comme procédure de déploiement.
