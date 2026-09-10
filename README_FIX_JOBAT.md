# JobHunter V2.1.1 — correctif Jobat

Ce patch corrige le cas où Jobat renvoie une page anti-bot avec HTTP 200.

## Installation
1. Fermer JobHunter.
2. Extraire ce ZIP directement dans le dossier JobHunter.
3. Accepter le remplacement des fichiers.
4. Relancer `START_JOBHUNTER.bat`.

Aucune réinstallation de Streamlit n'est nécessaire.

## Changements
- Une page `Sorry, you have been blocked` n'est plus traitée comme une offre.
- Les pages de blocage déjà présentes dans `logs/jobat_detail_cache` sont supprimées automatiquement.
- Le cache valide est utilisé avant le réseau afin de réduire les requêtes quotidiennes vers Jobat.
- `requests` -> validation -> Edge -> validation.
- Si Jobat bloque aussi Edge, l'offre reste avec son résumé de recherche et l'enrichissement est marqué en échec proprement ; aucun faux titre n'est injecté.
- `CLEAN_JOBAT_CACHE.bat` permet de forcer manuellement le nettoyage du cache détail Jobat.

## Test recommandé
Lancer un Daily Run normal et vérifier qu'aucune ligne ne contient désormais :
`Sorry, you have been blocked`

Si Jobat bloque totalement le détail, le journal doit plutôt indiquer des échecs d'enrichissement Jobat, sans corrompre les titres/descriptions.
