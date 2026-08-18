# Job Hunter Belgium

Pipeline Python personnel de collecte, enrichissement, déduplication et priorisation d'offres d'emploi en Belgique.

## Objectif

Centraliser plusieurs sources d'offres, conserver l'historique brut, enrichir les descriptions, mesurer la pertinence par rapport à un profil candidat, éliminer les doublons de manière conservatrice et produire une file de candidatures priorisée.

## Architecture

```text
Sources
  ↓
RAW jobs
  ↓
Pré-sélection métier
  ↓
Enrichissement des descriptions
  ↓
Matcher
  ↓
Canonical / Dedup
  ↓
Application Gate
  ↓
Application Queue
  ↓
Job Refresh
  ↓
Application Recheck
  ↓
Final Application Pool
```

## Sources actuellement travaillées

- Forem
- Actiris
- Talent.brussels
- TravaillerPour
- SmartRecruiters / employeurs directs

## Principes

- historique RAW conservé ;
- déduplication volontairement conservatrice ;
- aucune candidature marquée comme envoyée sans confirmation ;
- contrôle des exigences de diplôme, langue et credentials ;
- séparation entre collecte, scoring, éligibilité et préparation des candidatures.

## Lancement

Créer un environnement Python, installer les dépendances du projet puis :

```powershell
python main.py
```

Les diagnostics peuvent être lancés sous forme de modules, par exemple :

```powershell
python -m diagnostics.smartrecruiters_v11_audit
```

## Données privées

Les CV, lettres, bases locales, logs, fichiers de candidatures, secrets et profil personnel ne sont pas versionnés dans ce dépôt.

Voir `.gitignore`.
