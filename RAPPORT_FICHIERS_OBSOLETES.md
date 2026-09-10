# Rapport — fichiers obsolètes dans le projet original

**2 septembre 2026.** Analyse en lecture seule de `C:\Users\Aharr\Desktop\JobHunter`.
Aucun fichier n'a été modifié ni supprimé.

---

## Méthode

« Obsolète » ne peut pas vouloir dire « ça a l'air vieux ». Quatre critères
vérifiables ont été appliqués, du plus sûr au plus faible :

1. **Déclaré remplacé par ses propres auteurs** — le projet tient lui-même une
   liste `REPLACED` dans `diagnostics/run_all.py`.
2. **Remplacé par une version ultérieure du même composant**, présente sur
   disque.
3. **Non atteignable** depuis les points d'entrée vivants (`main.py`,
   `daily_run.py`, `jobhunter_ui.py`, `run_all.py` et tout script invoqué par
   un `.bat`), via le graphe d'imports réel.
4. **Copie de sauvegarde ou dossier de transit**, identifié comme tel par son
   emplacement.

Un fichier peut être ancien et vivant. Un script lancé à la main par un `.bat`
a été compté comme vivant.

---

## Le chiffre principal

```
backups/            8,1 Go        78 sous-dossiers, 145 fichiers
```

C'est, de loin, le poste le plus lourd — davantage que tout le reste du projet
réuni. Il contient **9 copies complètes de la base de données**, prises au fil
des intégrations du 31 août et du 1er septembre :

```
1 085,6 Mo   backups/post_main_pipeline_pre_20260901_222206/jobs.db
1 044,9 Mo   backups/jobs_pre_vnext14_real_main_20260901_213513/jobs.db
1 001,1 Mo   backups/jobs_pre_mega5_final_main_20260901_191703/jobs.db
  956,3 Mo   backups/jobs_pre_v39_batch3_6_20260901_164906/jobs.db
  913,5 Mo   backups/jobs_pre_v39_batch2_13_20260831_235118/jobs.db
  870,7 Mo   backups/jobs_pre_v39_batch2_10_20260831_231025/jobs.db
  ... 3 autres
```

Sauvegarder avant une migration est une bonne pratique. Le problème n'est pas
le principe, c'est qu'aucune de ces copies n'est jamais supprimée.

### La cause réelle : la base elle-même

La base vivante pèse **1,13 Go pour 5 939 offres actives**. C'est
disproportionné, et l'explication est mesurable :

```
canonical_job_sources     174 932 lignes
canonical_jobs            174 468 lignes
raw_job_run_items         157 846 lignes
dedup_review_candidates    93 516 lignes
raw_jobs                   12 386 lignes   (dont 5 939 actives)
```

`canonical_jobs` contient **34 build_id distincts × 5 131 lignes en moyenne**.
Chaque build réécrit un instantané complet, description comprise, et aucun
ancien build n'est élagué. La table conserve 34 photographies successives du
même catalogue.

**C'est un effet de levier :** chaque build ajoute ~5 000 lignes à la base,
chaque migration copie la base entière. Élaguer les builds anciens réduirait à
la fois la base et toutes les sauvegardes futures.

### Vérifier

```python
import sqlite3
con = sqlite3.connect("file:database/jobs.db?mode=ro", uri=True)
print(con.execute("SELECT COUNT(DISTINCT build_id), COUNT(*) FROM canonical_jobs").fetchone())
```

---

## Niveau 1 — obsolescence déclarée par le projet lui-même

`diagnostics/run_all.py` maintient un dictionnaire `REPLACED` qui associe chaque
diagnostic périmé à son successeur.

```
25 diagnostics explicitement déclarés remplacés
```

C'est la preuve la plus forte disponible : ce ne sont pas des fichiers que je
juge obsolètes, ce sont des fichiers que le projet sait obsolètes et qu'il
continue de conserver.

À quoi s'ajoutent **16 diagnostics** dont le successeur est présent sur disque
et vérifiable par le numéro de version :

```
application_gate_v1_audit.py            ->  application_gate_v132_audit.py
application_gate_v13_audit.py           ->  application_gate_v132_audit.py
application_gate_v13_shadow_audit.py    ->  application_gate_v131_shadow_audit.py
application_preparation_v1_audit.py     ->  application_preparation_v11_audit.py
application_queue_v1_audit.py           ->  application_queue_v12_audit.py
application_recheck_v1_audit.py         ->  application_recheck_v11_audit.py
final_application_pool_v1_audit.py      ->  final_application_pool_v12_audit.py
final_application_pool_v11_audit.py     ->  final_application_pool_v12_audit.py
job_refresh_v1_audit.py                 ->  job_refresh_v12_audit.py
job_refresh_v11_audit.py                ->  job_refresh_v12_audit.py
jobat_v213_audit.py                     ->  jobat_v214_audit.py
... et 5 autres
```

Et **15 README** dont une version supérieure existe :

```
README_SCIENSANO_V350.md   V351   V352   V353   V3531   V354      (6 périmés sur 7)
README_TAKEDA_V300.md      V301                                   (2 périmés sur 4)
README_AKKODIS_V250.md     README_GSK_V260.md    README_JOBAT_V213.md
README_SCIENCEATWORK_V220.md
README_HANDOFF_BUNDLE_V2_1_2.md   V2_1_4
```

Plus **5 candidats de `daily_run`** superposés :

```
daily_run_v101_candidate.py   v102   v110   v111   v120
```

---

## Niveau 2 — dossiers de transit et de sauvegarde

```
backups/               145 fichiers    8,1 Go     78 sous-dossiers horodatés
_payload/               72 fichiers    1,1 Mo
_step9_1_payload/        1 fichier       8 Ko
hardening_files/         1 fichier
hardening_step2_files/   6 fichiers
hardening_step4b_files/  1 fichier
hardening_step6b_files/  2 fichiers
hardening_step7_files/   1 fichier
lifecycle_step8f_b_files/1 fichier
```

Ces dossiers contiennent des copies de fichiers déjà installés ailleurs
(`sources/registry.py`, `config/versioning.py`, `sources/belgium_locations.py`…).
Ils servaient au transit d'un lot vers son emplacement définitif ; le transit a
eu lieu.

**Total : 230 fichiers, 8,1 Go.**

---

## Niveau 3 — code non atteignable

Graphe d'imports réel, en comptant comme vivant tout script invoqué par un
`.bat` :

```
modules Python du projet        427
points d'entrée vivants          85
atteignables                    178
NON ATTEIGNABLES                249     (58 %)
```

Répartition :

```
diagnostics/    132
racine/          84
sources/          8
config/           6
interface/        2
matching/         2
autres           15
```

**Nuance importante.** Non atteignable ne veut pas dire inutilisable : un
diagnostic peut toujours être lancé à la main par `python -m diagnostics.foo`.
Ce que le chiffre établit, c'est que **rien dans le projet ne pointe vers ces
249 fichiers** — ni import, ni `.bat`, ni `run_all`.

### Le dossier diagnostics a changé de nature

```
fichiers sur disque              213
cités dans run_all (7 catégories) 65
NON CLASSÉS                      148
```

Composition réelle :

```
audits (*_audit.py)                       69
runners one-shot (batch/mega/step)        88
tests live (*_live_test.py)               16
shadow (*_shadow*.py)                     15
```

**88 des 213 fichiers ne sont pas des diagnostics** : ce sont des scripts
d'intégration à usage unique (`mega_batch5_10_recover4_specific.py`,
`batch4_3_integrate4_resolve4.py`, `run_batch2_9_integrate_az_amgen.py`…),
exécutés une fois puis conservés.

Le dossier destiné à surveiller le projet est devenu son journal de bord.

---

## Niveau 4 — scripts de migration

```
66 scripts upgrade_/install_/apply_/rollback_ à la racine
```

Dont **40 ne sont référencés par aucun autre `.py`**. Les 26 restants ne le sont
que par leur propre script d'exécution — lui-même à usage unique :

```
upgrade_v39_mega5_10.py       <-  mega_batch5_10_recover4_specific.py
upgrade_v39_batch4_3_direct4.py <- batch4_3_integrate4_resolve4.py
upgrade_v39_batch2_4_registry.py <- run_batch2_4_registry_integration_4.py
```

L'obsolescence se propage : une migration référencée uniquement par son
lanceur reste morte. Les 66 forment des lots complets avec leur `.bat` et leur
`README`.

À l'échelle de la racine :

```
144 README_*.md
132 .bat RUN_/INSTALL_/TEST_/VERIFY_
 88 scripts .py
```

Chaque étape produit son triplet script + `.bat` + `README`. La racine est
devenue l'historique du projet plutôt que son contenu.

---

## Synthèse chiffrée

| Catégorie | Fichiers | Poids | Certitude |
|---|---|---|---|
| `backups/` | 145 | **8,1 Go** | certaine |
| `_payload/` + `_step9_1_payload/` | 73 | 1,1 Mo | certaine |
| Dossiers `*_files/` | 12 | — | certaine |
| Diagnostics déclarés `REPLACED` | 25 | — | **déclarée par le projet** |
| Diagnostics avec successeur sur disque | 16 | — | certaine |
| README avec version supérieure | 15 | — | certaine |
| Candidats `daily_run` | 5 | — | certaine |
| Scripts de migration racine | 66 | — | élevée |
| Runners one-shot dans `diagnostics/` | 88 | — | élevée |
| Code non atteignable (hors ci-dessus) | ~150 | — | à vérifier |

**Noyau incontestable : environ 290 fichiers et 8,1 Go.**
**Avec les migrations et runners one-shot : environ 450 fichiers.**

Pour mémoire, le projet compte 427 modules Python, dont **178 atteignables**.

---

## Ordre de suppression recommandé

### 1. Le volume, sans risque (8,1 Go)

`backups/` d'abord : conserver la sauvegarde la plus récente, envoyer les
77 autres sous-dossiers à la corbeille. Gain immédiat ≈ 7 Go, aucun impact sur
le code.

### 2. La cause, pour que ça ne revienne pas

Élaguer `canonical_jobs` et `canonical_job_sources` : ne garder que les 2 ou
3 derniers `build_id`. La base retombe à une taille normale, et chaque
sauvegarde future avec elle.

Ajouter une rétention aux sauvegardes : garder les 3 dernières, supprimer
au-delà.

### 3. Les lots morts

Les dossiers `_payload/`, `_step9_1_payload/` et les six `*_files/`.

### 4. Ce que le projet déclare lui-même périmé

Les 25 diagnostics de la liste `REPLACED`, les 16 à successeur vérifié, les
15 README périmés, les 5 candidats `daily_run`.

### 5. Les migrations, par lots complets

Les 66 scripts avec leur `.bat` et leur `README`. Ils restent récupérables
depuis git.

### 6. Le reste, après vérification

Avant toute suppression de la dernière catégorie, vérifier les dépendances —
plusieurs fichiers d'apparence obsolète sont référencés par des diagnostics :

```bash
grep -rl "nom_du_module" --include=*.py . | grep -v __pycache__
```

---

## Ce que ce rapport dit vraiment

Le volume de fichiers n'est pas un problème d'esthétique. Il a trois
conséquences mesurables.

**Il coûte 8 Go**, parce qu'une base non élaguée est copiée intégralement à
chaque migration.

**Il rend le projet illisible** : 178 modules vivants sur 427, 65 diagnostics
classés sur 213. Quelqu'un qui reprend le projet — ou vous dans trois mois —
doit deviner lequel des 88 scripts racine est vivant.

**Il masque les vrais signaux.** Le dossier `diagnostics/` contient 88 scripts
d'intégration à usage unique pour 69 audits réels. Quand un audit signale un
problème authentique, il est noyé.

La correction durable n'est pas un nettoyage, c'est une règle : un fichier de
documentation par composant avec un historique interne, une rétention sur les
sauvegardes, un élagage des builds, et les scripts one-shot hors du dossier
qui sert à surveiller le projet.
