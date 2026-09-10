# Job Hunter — ce qui est essentiel, ce qui est supprimable

**4 septembre 2026.** Analyse en lecture seule du dossier principal.
**Aucun fichier n'a été modifié, déplacé ni supprimé.**

---

## ⚠️ À lire avant toute suppression

```
git : 4 commits, 5 449 fichiers non commités
```

**Git ne vous protège pas en l'état.** Le dernier commit est ancien et
l'essentiel du travail des dernières semaines n'y est pas. Une suppression
aujourd'hui ne serait pas annulable.

**Faites un commit avant de supprimer quoi que ce soit.** Cela transforme toute
l'opération en action réversible :

```
git add -A
git commit -m "Etat avant nettoyage"
```

Ensuite, supprimez vers la corbeille plutôt qu'en dur, et lancez
`python daily_run.py --check` après chaque lot.

---

## Méthode

Un fichier est déclaré **essentiel** s'il est atteignable depuis les trois
points d'entrée réels — `main.py`, `daily_run.py`, `jobhunter_ui.py` — ou depuis
la suite de diagnostics active déclarée dans `run_all.py`.

**Un piège a été évité en cours de route.** Une analyse d'imports seule aurait
conclu que `applications/application_preparation.py` est mort. C'est faux :
`daily_run.py` lance ses étapes en **sous-processus** :

```python
subprocess.Popen([... "-m", "applications.application_preparation" ...])
```

Ces appels ne sont pas des `import`. L'analyse a donc été étendue aux chaînes
de caractères désignant un module du projet. C'est exactement le genre d'erreur
qui fait supprimer un fichier vital.

**Résultat : 153 modules essentiels sur 572.**

---

# PARTIE 1 — À GARDER

## 1.1 Le noyau exécutable

```
racine/
    main.py                     pipeline de collecte et scoring
    daily_run.py                orchestrateur quotidien
    jobhunter_ui.py             interface Streamlit

applications/                   TOUT le dossier — lancé en sous-processus
    application_preparation.py      job_refresh.py
    application_recheck.py          final_application_pool.py
    delta_tracker.py                lifecycle_tracker.py
    lifecycle_sync.py               lifecycle_daily_sync.py
    chatgpt_handoff.py              ai_document_generator.py

config/
    profile.py                  profil de recherche
    candidate_truth.py          vérité candidat (langues, mobilité, diplômes)
    versioning.py               versions des composants
    smartrecruiters_sources.py
    + les fichiers de configuration des sources actives

database/
    db.py                       accès base
    models.py                   modèle JobOffer
    canonical.py                déduplication
    enriched_batch.py           enrichissement
    backup_retention.py         rétention des sauvegardes

matching/
    application_gate.py         Gate (langue, mobilité, diplôme)
    application_gate_v13.py     overlay actif
    application_queue.py        + application_queue_v12.py
    basic_matcher.py            scoring
    matcher_vnext_overlay.py    overlay Matcher

interface/                      TOUT le dossier — utilisé par l'UI
    data_access.py              pipeline_runner.py
    handoff_service.py          progress_monitor.py
    lifecycle_service.py        run_statistics.py
    source_registry_service.py

sources/
    registry.py                 registre central — indispensable
    belgium_locations.py        détection géographique partagée
    source_metrics.py           instrumentation
    + les connecteurs des sources actives
```

## 1.2 Les lanceurs

Trois `.bat` sur 227 lancent réellement l'application. Ils installent
l'environnement UTF-8 et le venv, donc ils comptent :

```
START_JOBHUNTER.bat        lance l'interface Streamlit
RESUME_DAILY_RUN.bat       reprend le Daily Run
TEST_DAILY_RUN.bat         test du Daily Run
```

## 1.3 Les données — à ne jamais supprimer

```
database/jobs.db       13 737 offres, 126 candidatures, 1 110 événements
```

**Cette base n'est pas dans git** (`.gitignore:39  database/*.db`). Si elle est
perdue, rien ne la restaure. Elle contient votre candidature envoyée et vos
43 dossiers prêts.

```
logs/          6 680 fichiers de cache (Actiris, détails d'offres)
exports/logs/  1 439 rapports de run
backups/       3 copies de base, gérées par backup_retention.py
```

Les caches sont **reconstructibles mais coûteux** : les supprimer force une
recollecte complète. Les rapports de run sont votre seul historique de mesure.
`backups/` est déjà sous contrôle : leur outil garde 3 copies (`DEFAULT_KEEP=3`)
et son dernier rapport est `STATUS=GREEN`.

## 1.4 La suite de diagnostics active

25 audits sur 316 sont déclarés dans `SUITE_ACTIVE` de `run_all.py`. Ce sont
les seuls lancés automatiquement — à garder, avec `run_all.py` :

```
ai_document_generator_v1_audit          application_gate_v131_shadow_audit
application_gate_v132_audit             application_gate_v13_audit
application_gate_v13_shadow_audit       application_preparation_v11_audit
application_preparation_v1_audit        application_queue_v12_audit
application_recheck_v11_audit           artifact_pattern_collision_audit
chatgpt_handoff_v1_audit                daily_run_v101_encoding_audit
daily_run_v102_refresh_status_audit     daily_run_v110_delta_integration_audit
delta_tracker_v11_repost_audit          delta_tracker_v1_audit
final_application_pool_v11_audit        final_application_pool_v12_audit
funnel_recall_v1_audit                  hardening_step4b_candidate_truth_audit
hardening_step4c_handoff_bundle_audit   job_refresh_v12_audit
main_v10_4_1_audit                      matcher_v51_audit
recall_rescue_v1_audit
```

---

# PARTIE 2 — SUPPRIMABLE

Classé du plus sûr au plus délicat.

## 2.1 Dossiers de transit — certitude totale

**117 fichiers.** Ce sont des zones de préparation : leur contenu a déjà été
installé à son emplacement définitif.

```
_payload/                        97 fichiers
payload/                          5
_patch_payload/                   2
_step9_1_payload/                 1
_jobat_circuit_v1_payload/        1
_jobat_cookie_once_v1_payload/    1
hardening_files/                  1
hardening_step2_files/            6
hardening_step4b_files/           1
hardening_step6b_files/           2
hardening_step7_files/            1
lifecycle_step8f_b_files/         1
```

Ils contiennent des copies de `registry.py`, `versioning.py`,
`belgium_locations.py`, `candidate_truth.py` — tous présents et à jour ailleurs.

## 2.2 Doublons versionnés dans `applications/` — certitude totale

**7 fichiers.** Leur contenu a été fusionné dans le fichier de base. Vérifié :
le fichier de base porte déjà la version que `daily_run.py` exige.

| À supprimer | Fichier de base | Version portée |
|---|---|---|
| `application_preparation_v11.py` | `application_preparation.py` | **1.1** |
| `application_recheck_v11.py` | `application_recheck.py` | **1.1** |
| `delta_tracker_v11.py` | `delta_tracker.py` | **1.1** |
| `final_application_pool_v12.py` | `final_application_pool.py` | **1.2** |
| `job_refresh_v11.py` | `job_refresh.py` | **1.2** |
| `job_refresh_v12.py` | `job_refresh.py` | **1.2** |

## 2.3 Scripts de migration à la racine — certitude élevée

**70 fichiers** `upgrade_*`, `install_*`, `apply_*`, `rollback_*`, `patch_*`.

Ce sont des scripts à usage unique, déjà exécutés. Leur effet est dans le code.
Ils forment des lots avec leur `.bat` et leur `README`, qui partent avec eux.

**Plus 5 candidats superposés :**

```
daily_run_v101_candidate.py   v102   v110   v111   v120
```

## 2.4 Scripts d'étape à la racine — certitude élevée

**16 fichiers.** Audits et inventaires ponctuels, déjà passés :

```
lifecycle_step8a_inventory.py            lifecycle_step8b_audit.py
lifecycle_step8c_bootstrap.py            lifecycle_step8c_bootstrap_audit.py
lifecycle_step8d_manual_cli_audit.py     lifecycle_step8d_unicode_hotfix_audit.py
lifecycle_step8e_sync_audit.py           lifecycle_step8f_a_daily_run_inventory.py
lifecycle_step8f_b_daily_run_integration_audit.py
lifecycle_step8g_final_offline_validation.py
lifecycle.py                             main_smartrecruiters_shadow.py
main_smartrecruiters_shadow_v2.py        diagnose_jobat_prov.py
export_full_performance_audit_v1.py      Resume_pour_gemini.py
```

Après ces trois lots, la racine passe de **94 scripts à 3**.

## 2.5 Diagnostics hors suite — à trier

**288 fichiers sur 316** ne sont pas dans `SUITE_ACTIVE`.

Trois familles, à traiter différemment :

**a) Runners d'intégration à usage unique — supprimables.** Environ 90 fichiers
`mega_batch*`, `batch*_integrate*`, `run_batch*`, `install_*`, `upgrade_*`,
`validate_*`, `rollback_*`. Ce ne sont pas des diagnostics : ce sont des scripts
de migration rangés dans le mauvais dossier.

**b) Audits déclarés remplacés — À NE PAS SUPPRIMER SEULS.** `run_all.py` tient
un dictionnaire `REPLACED` associant chaque audit périmé à son successeur. Il
est tentant de les supprimer, mais **c'est un piège, vérifié en conditions
réelles** : le retrait des 13 audits `REPLACED` du dossier de travail a cassé
la suite immédiatement —

```
[FAIL] Classification incomplète. Aucun diagnostic n'a été lancé.
```

`run_all` exige que chaque nom cité dans ses listes de classification existe sur
disque. La déclaration « remplacé » **crée une dépendance** : l'audit est
obsolète pour l'exécution, mais son fichier reste requis par l'inventaire.

Soit on les laisse (ils ne coûtent presque rien), soit on les supprime **et**
on retire leurs entrées du dictionnaire dans le même geste.

**c) Audits et tests live encore utiles — à garder.** Les `*_live_test.py` et
les audits par connecteur servent au diagnostic manuel. Ils ne coûtent rien et
peuvent servir.

**Recommandation :** supprimer (a) et (b), garder (c). Cela ramène `diagnostics/`
d'environ 316 à 120 fichiers, et lui rend sa fonction.

## 2.6 Fichiers `.bat` — certitude élevée

**224 sur 227.** Seuls `START_JOBHUNTER.bat`, `RESUME_DAILY_RUN.bat` et
`TEST_DAILY_RUN.bat` lancent l'application. Les 224 autres sont des
`RUN_*`, `INSTALL_*`, `TEST_*`, `VERIFY_*` d'étapes déjà passées.

## 2.7 Fichiers `.md` — certitude élevée

**97 sur 197** portent un numéro de version (`README_*_V*.md`) et documentent
une étape révolue. Beaucoup se succèdent sur le même composant :

```
README_SCIENSANO_V350  V351  V352  V353  V3531  V354      7 fichiers
README_TAKEDA_V300     V301                               4 fichiers
```

**Garder** : `README.md`, le document de contexte courant, et le journal de
suivi en cours. **Un fichier par composant avec un historique interne**, pas un
fichier par version.

## 2.8 Orphelins dans les dossiers du noyau — à vérifier au cas par cas

Peu nombreux, mais ils sont dans des dossiers essentiels — donc à traiter
individuellement, pas en lot :

```
config/funnel_recall.py                  config/source_scout_targets.py
config/source_scout_targets_batch2.py    config/source_scout_targets_batch3.py
database/activity.py                     database/intrasource_audit.py
matching/application_gate_v13_overlay.py
sources/  8 modules (actiris_provenance, *_shadow, *_diagnostic, batch3_3_engine)
```

**Attention** : `config/source_scout_targets*.py` contient probablement des
listes d'employeurs cibles — de la connaissance métier, pas du code mort.
**Lire avant de supprimer, et reporter le contenu si nécessaire.**

---

# PARTIE 3 — Récapitulatif

| Catégorie | Fichiers | Certitude |
|---|---|---|
| Dossiers de transit et payload | 117 | **totale** |
| Doublons versionnés `applications/` | 7 | **totale** |
| Migrations racine | 70 | élevée |
| Candidats `daily_run` | 5 | élevée |
| Scripts d'étape racine | 16 | élevée |
| Runners one-shot dans `diagnostics/` | ~90 | élevée |
| Audits déclarés `REPLACED` | ~25 | **déclarée par le projet** |
| Fichiers `.bat` | 224 | élevée |
| README versionnés | 97 | élevée |
| Orphelins dans dossiers du noyau | ~15 | **à vérifier un par un** |

**Total supprimable : environ 650 à 670 fichiers.**

Après nettoyage :

```
                    avant    après
racine .py             94        3
racine .bat           227        3
racine .md            197     ~10
diagnostics/          316     ~120
modules Python        572     ~200
```

Le poids disque gagné est faible — ces fichiers sont petits. **Le gain est la
lisibilité** : aujourd'hui, savoir lequel des 94 scripts racine est vivant
demande une analyse. Demain, il y en aura trois.

---

# PARTIE 4 — Ordre d'exécution

**Étape 0.** Commit de l'état actuel. Sans cela, rien n'est réversible.

**Étape 1.** Les 12 dossiers de transit et les 7 doublons `applications/`.
Certitude totale, aucun risque.

**Étape 2.** `python daily_run.py --check` — doit rester vert.

**Étape 3.** Les 70 migrations et 5 candidats, **avec** leurs `.bat` et
`README` associés, par lots complets.

**Étape 4.** `python -m diagnostics.run_all` — doit rester vert.

**Étape 5.** Les 16 scripts d'étape racine, les runners one-shot de
`diagnostics/`, les audits `REPLACED`.

**Étape 6.** Les `.bat` et README versionnés.

**Étape 7.** Les orphelins des dossiers du noyau, **un par un**, en lisant
chacun avant.

## La vérification à faire avant chaque suppression

```bash
grep -rl "nom_du_module" --include=*.py . | grep -v __pycache__
```

Si le résultat ne contient que le fichier lui-même, il n'est référencé nulle
part. **Trois précautions** que l'analyse a rendues nécessaires :

1. Chercher aussi le nom **en chaîne de caractères** — les étapes du Daily Run
   sont lancées par `subprocess` avec `-m applications.xxx`, pas par `import`.
2. Chercher dans les `.bat`, pas seulement dans les `.py`.
3. Vérifier qu'aucun audit de `SUITE_ACTIVE` ne le teste. `ai_document_generator.py`
   n'est appelé par aucun module du runtime, mais `ai_document_generator_v1_audit`
   le teste — il doit rester.

---

# Ce que ce nettoyage ne règle pas

Supprimer des fichiers ne change ni le volume disque — dominé par la base à
1,08 Go et ses trois sauvegardes — ni le fonctionnement.

Le vrai gain d'espace est ailleurs : `canonical_jobs` conserve 34 instantanés
successifs du catalogue, jamais élagués. Élaguer les anciens builds réduirait la
base **et** les sauvegardes d'un coup.

Et la vraie cause du désordre n'est pas le passé mais la cadence : chaque étape
de développement produit encore aujourd'hui son script, son `.bat` et son
`README`. Sans changer cette habitude, la racine sera revenue à 90 fichiers dans
quinze jours.

**La règle qui l'évite** : un fichier de documentation par composant avec un
historique interne, et les scripts à usage unique hors du dossier qui sert à
surveiller le projet.
