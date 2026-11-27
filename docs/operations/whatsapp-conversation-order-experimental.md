# Ordre des conversations WhatsApp — expérimental

La réception durable reste désactivée en production. La migration 0022 et le
worker ordonné ne doivent pas être activés avant la fin des essais, une
sauvegarde vérifiée et une procédure de retour arrière.

Les nouveaux événements sont groupés par institution, canal et identifiant
fournisseur de l'expéditeur à l'aide d'une empreinte HMAC. Celle-ci ne contient
pas le numéro en clair, mais reste une donnée pseudonymisée. Elle dépend de la
version 1 de la clé de données de l'institution : les rotations doivent
conserver cette version. Si elle manque, la réception échoue au lieu de créer
une nouvelle identité pour la même conversation.

Un verrou transactionnel commun à la réception et à la prise en charge permet
de traiter les événements d'une conversation dans leur ordre d'acceptation
par la base ; des conversations distinctes peuvent progresser en parallèle.
L'ordre d'envoi original par le citoyen n'est pas garanti si le fournisseur
livre les événements dans un autre ordre. Une issue incertaine ou en suivi
bloque les messages suivants de cette conversation jusqu'à la décision d'un
opérateur, sans déclencher de renvoi automatique.

Les événements antérieurs à la migration n'ont pas d'empreinte : ceux qui ne
sont pas terminés bloquent les nouvelles réclamations de leur institution
jusqu'à une réconciliation explicite. La migration ne fait pas de conversion
automatique. Une restauration doit conserver les clés historiques, les
empreintes et l'ordre ; ne pas rétrograder ou supprimer ces données sans
procédure vérifiée. Les données fournisseur réelles, les changements de canal,
les performances et les interruptions restent à valider avant activation.

Un message STOP reconnu en texte met le contact en opposition dans la même
transaction que son entrée en file, avant l'accusé de réception. Sa prise en
charge est prioritaire devant les événements en attente ou incertains, mais
attend une opération déjà en cours sur la conversation ; un envoi fournisseur
déjà commencé ne peut pas être annulé. Les interactions avec tous les canaux
et les pannes doivent encore être éprouvées avant activation. Le planificateur
prend actuellement au plus un message par appel toutes les dix secondes ; le
débit doit être mesuré et amélioré.

À expiration de la conservation, l'empreinte d'un événement terminé ou résolu
est supprimée. Celle d'un événement non résolu est conservée pour empêcher
une réponse hors ordre, puis supprimée lors de sa résolution après expiration.
