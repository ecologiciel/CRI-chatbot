# Créer une démonstration pour une institution

Ce guide décrit le parcours web de la plateforme de démonstration déployée sur
Hostinger. Il s'adresse au titulaire d'un compte **super-administrateur**.
Les espaces créés sont des démonstrations non officielles ; vérifiez les
sources et les réponses avant de les présenter à un prospect.

## Créer l'espace

1. Ouvrez [l'administration](https://2-25-21-84.sslip.io/admin/) et connectez-vous.
2. Dans l'espace super-administrateur, ouvrez **Tenants**, puis **Créer une démonstration**.
3. Indiquez le nom de l'institution, son code et la zone couverte. Le code
   contient 2 à 50 lettres minuscules ou chiffres, commence par une lettre et
   figure dans le lien public. Vérifiez-le avant la création.
4. Cliquez sur **Créer la démonstration**. La page **Institutions** liste les
   espaces et leur état. Le chat web est activé pour ce nouvel espace ; sa
   durée de conservation des conversations est configurée à sept jours.

La purge est quotidienne : une conversation terminée est éligible après le
délai configuré ; une conversation de démo non terminée devient éligible après
ce délai sans message récent. La suppression n'est donc pas instantanée au
bout de sept jours. N'utilisez pas ce délai comme engagement contractuel sans
avoir défini la politique de conservation avec l'institution.

## Importer et valider des documents

1. Sur la ligne de l'institution active, cliquez sur **Gérer les documents**.
   Vérifiez le nom de l'institution affiché en haut de l'administration avant
   de poursuivre. Pour changer d'espace, utilisez **Choisir une institution**.
2. Dans **Base de connaissances**, cliquez sur **Ajouter un document** et
   choisissez un fichier PDF, DOCX, TXT, Markdown ou CSV. L'interface indique
   une limite de 50 Mo ; pour un CSV, la première ligne est considérée comme
   les intitulés des colonnes.
3. Renseignez l'organisme émetteur, la référence et la version de la source,
   puis le titre, la catégorie et la langue. Ajoutez un lien officiel si vous
   en disposez. La date de publication est facultative si elle est inconnue :
   ne la remplacez pas par la date de téléchargement.
4. Importez le fichier. Dans la liste, ouvrez le menu **…** du document
   **À valider**, choisissez **Valider et indexer**, puis confirmez après avoir
   contrôlé sa source et son contenu. L'indexation démarre après validation.
5. Actualisez la liste et attendez **Indexé** avant de tester. **En attente**
   ou **En cours** indique que le traitement n'est pas terminé ; **Erreur**
   signifie que le document ne doit pas être considéré comme disponible.
   Le menu **…** permet de demander une réindexation si nécessaire.

Importez uniquement des documents que vous êtes autorisé à utiliser. Les
fichiers scannés, tableaux complexes et sources anciennes demandent un contrôle
particulier : la présence de passages indexés ne garantit pas une extraction
fidèle ni des réponses exactes.

## Tester et partager la démo

Dans **Institutions**, cliquez sur **Ouvrir le chatbot** pour l'espace voulu.
Posez plusieurs questions dont vous connaissez les réponses, y compris une
question absente des documents. Vérifiez la réponse et les **documents
consultés**. Les pages affichées sont les pages des passages consultés ; elles
ne prouvent pas que chaque affirmation est justifiée par chaque page.

La démonstration est publique et accessible sans connexion : évitez d'y mettre
des documents confidentiels ou des données réelles. Le chat
demande aux visiteurs de ne pas transmettre de données personnelles. Certains
motifs reconnus sont masqués, mais cela ne constitue pas une anonymisation
complète. Une vérification humaine des réponses en français et en arabe reste
nécessaire avant une présentation institutionnelle.

## Limites d'exploitation

- WhatsApp demande une configuration et des essais distincts ; créer une
  démonstration web ne configure pas ce canal.
- Un état de santé vert ne garantit pas que le fournisseur d'IA répond ni que
  les réponses sont correctes. Voir [Surveillance depuis Windows](securite/surveillance-windows.md).
- La sauvegarde chiffrée et les limites de récupération sont décrites dans
  [Vérification locale d'une sauvegarde](securite/verification-sauvegarde-locale.md).
- Ne partagez pas de mot de passe ou de clé API dans une conversation. Une
  clé précédemment exposée doit être remplacée auprès de son fournisseur.
