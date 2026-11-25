# Évaluation exploratoire de l'image serveur

Le 26 novembre 2026, l'image backend effectivement utilisée sur Hostinger et une image d'essai construite avec le même Dockerfile, le même code et les mêmes dépendances verrouillées, mais avec `python:3.12-slim-bookworm` au lieu de `python:3.12-slim`, ont été examinées avec Trivy 0.76.0 et la même base de vulnérabilités. Les deux images ont été mises à jour avec les paquets disponibles lors de leur construction. L'image d'essai a été construite séparément et n'a pas été déployée.

| Image | Détections HIGH/CRITICAL par paquet et CVE | CVE distinctes |
| --- | ---: | ---: |
| Image backend en service, Debian trixie | 53 | 13 |
| Image d'essai, Debian bookworm | 102 | 32 |

Trivy n'indiquait aucune version corrigée dans les détections des deux images. Le changement éliminait certaines alertes, dont les deux alertes OpenSSL QUIC, mais en ajoutait d'autres : il ne justifie pas une migration en l'état. Ces détections ne représentent pas chacune une exploitation démontrée ; leur nombre seul ne mesure pas le risque réel et varie avec les versions et la base du scanner. L'image alternative a passé un test d'import de l'application et du tokenizer, pas un test fonctionnel complet.

Le suivi Debian indique notamment que les versions trixie concernées sont vulnérables pour [CVE-2026-78410 (util-linux)](https://security-tracker.debian.org/tracker/CVE-2026-78410) et [CVE-2026-124709 (OpenSSL)](https://security-tracker.debian.org/tracker/CVE-2026-124709). Les capacités Linux du backend ont déjà été réduites et le processus s'exécute sans privilèges, mais ces mesures ne corrigent pas les paquets.

À poursuivre : surveiller les correctifs de la distribution, tester toute autre image de base avec les dépendances et les parcours réels, et examiner la réduction des outils de test actuellement présents dans l'image de production. Aucun seuil de risque institutionnel ou conformité n'a été établi par ce scan.

## Essai Alpine avant migration

Une image complète fondée sur `python:3.12-alpine`, mise à jour par `apk upgrade` et construite avec les mêmes dépendances Python verrouillées, a ensuite été testée séparément sur le VPS. Trivy 0.76.0 n'a détecté aucune alerte HIGH ou CRITICAL dans cette image au moment du scan ; cela ne garantit ni l'absence de vulnérabilités ni de futures alertes.

L'image a réussi l'import de l'application, 60 tests ciblés hors réseau, un test d'ingestion versionnée avec PostgreSQL isolé et Qdrant en mémoire, les migrations depuis une base vide, puis le démarrage en mode production de l'API et d'un worker avec PostgreSQL, Redis, Qdrant et MinIO isolés. Une requête HTTPS sans clé vers l'API publique de découverte Gemini a également réussi depuis le réseau du VPS. Les premiers essais isolés ont nécessité une correction du lancement de commande puis un délai d'attente suffisant pour le worker. Aucun essai n'a utilisé de données de production.

Ces contrôles ne remplacent pas les tests complets et un essai réel après mise en service. Les versions Python tierces et les vulnérabilités doivent continuer à être suivies.
