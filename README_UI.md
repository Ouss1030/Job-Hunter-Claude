# JobHunter UI V2.1 — Registre de sources + Jobat

Cette mise à jour est cumulative avec la V2 actuelle.

## Nouveautés

- Registre central des sources dans `sources/registry.py`.
- Activation/désactivation depuis `📡 Sources` dans l'interface.
- Nouvelle source **JOBAT** activée par défaut.
- Jobat recherche uniquement des termes **FR/EN** ciblés Data/BI + Labo/QC/Pharma.
- Filtrage léger des titres clairement néerlandophones.
- Jobat utilise `requests` d'abord ; si le site bloque l'accès automatisé, il bascule sur Microsoft Edge via Playwright.
- Les pages Jobat sont mises en cache dans `logs/jobat_search_cache` et `logs/jobat_detail_cache`.
- Une source en panne n'arrête plus toute la collecte : le registre journalise l'erreur et continue avec les autres sources.
- Le suivi temps réel reconnaît maintenant les sources même si leur numéro change après activation/désactivation.

## Installation

1. Fermer JobHunter.
2. Extraire **tout le contenu** du ZIP directement dans le dossier racine `JobHunter`.
3. Accepter le remplacement des fichiers.
4. Relancer `START_JOBHUNTER.bat`.

Aucune migration SQLite n'est nécessaire.

## Vérifier la configuration

Dans l'interface :

`📡 Sources`

Tu verras les 6 sources enregistrées et tu pourras choisir lesquelles sont actives. Les changements s'appliquent au prochain Daily Run.

## Tester Jobat seul

Double-cliquer sur :

`TEST_JOBAT.bat`

Le test utilise seulement 4 recherches et **ne modifie pas la base SQLite**. Il indique si Jobat est lu via HTTP ou via Edge.

## Si Playwright manque

Ton archive JobHunter actuelle contient déjà Playwright. Si un jour il manque dans un nouvel environnement :

`.venv\Scripts\python.exe -m pip install -r requirements_jobat.txt`

Il n'est pas nécessaire de télécharger Chromium : le connecteur utilise le Microsoft Edge installé avec Windows 11.

## Fichiers principaux ajoutés

- `sources/registry.py`
- `sources/jobat.py`
- `sources/jobat_detail.py`
- `config/source_settings.json`
- `interface/source_registry_service.py`
- `diagnostics/jobat_v1_live_test.py`
- `TEST_JOBAT.bat`

## Important

Le Daily Run continue à être lancé avec `--no-handoff` depuis l'interface V2. Les chunks ChatGPT restent donc entièrement manuels.
