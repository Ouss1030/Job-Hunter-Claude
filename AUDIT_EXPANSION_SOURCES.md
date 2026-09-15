# AUDIT — EXPANSION DES SOURCES

Date : 15 septembre 2026. Base de référence : `database/jobs.db`, dernier run complet `RUN_20260910_035747`.
Tout ce qui suit est constaté dans le code et la base, pas supposé.

## 1. Ce qui existe

| Composant | Où | État |
|---|---|---|
| Registre de sources | `sources/registry.py` — `SourceSpec(key, result_key, label, collector, ...)` ; `SOURCE_SPECS` ; activation par `config/source_settings.json` | **Fonctionnel.** 174 specs avant cette mission, exécution en pool de threads, une source en panne n'arrête pas les autres |
| Registre maître partageable | `config/SOURCES_MASTER.json` (168 entrées) via `sources/source_master.py` | Fonctionnel mais **trompeur** : 163 « HEALTHY » signifie « pas de défaut structurel connu », pas « rend des offres » |
| Base | `raw_jobs` (11 905 lignes, 6 800 actives), `canonical_jobs` (13 613), `canonical_job_sources`, `raw_job_run_items`, `source_identity_aliases` | **Fonctionnel.** Tout est sauvé en brut avant tout filtre métier ; couche canonique + observations multi-sources = le modèle *1 job canonique + N observations* demandé existe déjà |
| Déduplication | `database/` canonical_builds, `dedup_review_candidates`, alias d'identité | Fonctionnel, à ne pas toucher |
| Lifecycle | `applications/lifecycle_tracker.py`, `is_active`/`last_run_id` sur `raw_jobs`, delta tracker | Fonctionnel |
| Connecteurs ATS génériques (1re génération) | `sources/greenhouse.py`, `recruitee.py`, `smartrecruiters.py`, `workday_ats_v1.py`, `successfactors_ats_v1.py`, `phenom_ats_v1.py` — chacun piloté par `config/<ats>_sources.py` | **Fonctionnels**, 35 employeurs configurés (Greenhouse 4, Recruitee 8, SmartRecruiters 5, Workday 23 dont 11 actifs, SuccessFactors 5, Phenom 4). Ils collectent *tout* l'employeur puis filtrent la Belgique — conforme au principe |
| Clients ATS bruts | `sources/public_ats_engines_v1.py` : greenhouse, lever, recruitee, ashby, smartrecruiters | Lever et Ashby : client de 4 lignes, **aucun connecteur, aucun employeur** |
| Empreinte ATS | `diagnostics/ats_fingerprint.py` (18 signatures, 5 extracteurs) ; `diagnostics/ats_discovery.py` (sondes par nom Recruitee/Greenhouse/SmartRecruiters) | Outils de diagnostic, pas branchés sur la collecte ; résultats d'août 2026 (77 lignes) |
| Localisation | `sources/location_belgium.py` — `detect_belgium`, `detect_belgium_multi`, `belgian_postal_code` | Fonctionnel, réutilisé partout |
| Détail (description complète) | `forem_detail.py` (API JSON `DetailOffre`), `actiris_detail.py` (HTML), caches disque `logs/*_detail_cache*` | Fonctionnels : Forem 566/953, Actiris 5 826/5 826 tentées |
| Diagnostics | `diagnostics/run_all.py` : 47 audits hors ligne, batterie verte | Fonctionnel |
| BAT | `START_JOBHUNTER.bat`, `LANCER_INTERFACE_WEB.bat`, `TEST_DAILY_RUN.bat` | Fonctionnels |

## 2. Ce qui rend vraiment des offres

168 sources déclarées → **65 ont déjà rendu une offre → 57 vues au dernier run → 9 font 95 % du volume.**

| Source | Actives en base | Vues au dernier run | Description exploitable | Constat |
|---|---|---|---|---|
| ACTIRIS | 4 418 | 4 331 | 5 826 détails | Recherche par **termes** ; catalogue réel : **33 208** |
| JOBAT | 901 | 0 | 51 | HTTP 403 — cache seulement |
| FOREM | 345 | 344 | 566 détails | Recherche par **termes** ; open data réel : **26 198** |
| SMARTRECRUITERS | 258 | 258 | 273 | OK, 5 employeurs |
| WORKDAY | 190 | 190 | 196 | OK, 11 employeurs |
| SUCCESSFACTORS | 118 | 118 | 119 | OK, 5 hôtes |
| RECRUITEE | 105 | 105 | 98 | OK, 8 employeurs |
| TRAVAILLERPOUR | 101 | 101 | 125 | OK |
| PHENOM | 84 | 84 | 84 | OK, 4 hôtes |
| GREENHOUSE | 44 | 44 | 44 | OK, 4 employeurs |
| 55 autres | 1 à 37 | — | — | Sources « employeur direct » à 1–2 offres : le coût de maintenance dépasse la valeur |
| 103 déclarées | 0 | 0 | 0 | Jamais une offre en base |

## 3. Le défaut principal : filtrer à l'entrée

`sources/forem.py` et `sources/actiris.py` interrogent leur API avec `get_collection_search_terms()` — 160 termes tirés du profil du candidat. C'est exactement le schéma interdit par le cahier des charges (SOURCE → FILTRER SELON MON PROFIL → COLLECTER). Mesure :

- Actiris, recherche vide, `pageSize=200` : **33 208 offres** (1 953 propres, 8 874 republiées VDAB/Forem, 22 380 partenaires — dont Jobat, StepSone, Références qui nous bloquent en direct).
- Forem, `exports/json` : **26 198 offres** en une requête, avec employeur, commune, code postal, NACE, langues, dates ; description via l'API `DetailOffre` (1 484 caractères mesurés).

Le pipeline aval est déjà prêt à absorber : `persist_initial_raw_collection` sauve tout, `select_candidate_jobs` ne demande le détail qu'aux offres pertinentes ou à titre pertinent et description mince.

## 4. Cassé, partiel, absent

| | Constat |
|---|---|
| **Cassé** | Jobat direct (403 vérifié) ; VDAB direct (pages JS, `/api/vindeenjob/` interdit par robots.txt — connecteur désactivé à raison) ; Sciensano DEGRADED |
| **Partiel** | Adzuna, Careerjet, Jooble : connecteurs écrits, **clés API absentes** (gratuites à demander) ; 103 sources déclarées sans jamais une offre |
| **Absent** | Détecteur d'ATS branché sur la collecte ; moteur de découverte ; extracteur universel JSON-LD ; connecteurs Lever, Ashby, Workable, Personio, Teamtailor, Jobtoolz, Talentfinder ; registre des employeurs découverts ; LinkedIn/Indeed/StepStone (anti-bot : pas de voie publique) ; Federgon ; BCE/KBO ; EURES |

## 5. Risques de régression identifiés et traités

- **Volume ×5 en `raw_jobs`** (≈ 60 000 au lieu de 12 000) : SQLite tient ; le détail est borné par run (`config/absorption_settings.json`, 2 500 nouvelles pages par source) pour que le premier run reste de l'ordre de l'heure et non de la nuit ; cache disque = acquis définitif.
- **Fausse disparition** si une API tombe à mi-parcours : instantané `logs/absorption/*_last_ok.json` rendu à la place, jamais zéro.
- **Provenance Actiris** (`ACTIRIS` / `VDAB_FOREM` / `PARTNER`) : `typeOffre` ne la distingue pas → pagination par mode, même coût, provenance exacte (main.py raisonne dessus).
- **Clés FOREM/ACTIRIS inchangées** : routeur de détail, lifecycle, statistiques, interface continuent de fonctionner.
- **Homonymes étrangers** en devinant un slug d'ATS par le nom : un slug deviné n'est enregistré qu'avec ≥ 1 offre belge.
- **Sous-domaines techniques** (`careers-analytics.recruitee.com`) pris pour un employeur : exclus.
- **Écritures concurrentes** du registre d'employeurs : verrou.

## 6. Ce que cette mission a ajouté (tout testé, 39/39 hors ligne + vérifications réseau)

| Fichier | Rôle |
|---|---|
| `sources/absorption_v1.py` | Actiris complet (3 provenances, pages de 200) + Forem export complet ; instantanés ; progression console |
| `sources/registry_absorption_v1.py` | Remplace les collecteurs FOREM/ACTIRIS ; budget de détail par run ; `config/absorption_settings.json` (`{"complete": false}` = retour arrière) |
| `config/ats_signatures.json` | 32 ATS : motifs URL, extraction d'identifiant, connecteur, stratégie, endpoint |
| `sources/ats_detector_v1.py` | `detecter_url()` hors ligne, `detecter_site()` en ligne (chemins usuels, redirections, liens, HTML, suivi de liens « carrière ») |
| `sources/ats_public_v2.py` | Connecteurs **Lever, Ashby, Workable, Personio** (API/XML publics, description complète, filtre Belgique) |
| `sources/jsonld_sitemap_v1.py` | **Extracteur universel** : robots → sitemap index → URL d'offres → JSON-LD JobPosting → JobOffer ; cache par `lastmod` ; `extraire_offre(url)` pour une URL isolée |
| `sources/ats_employers_v2.py` + `config/ats_employers_v2.json` | Registre persistant des employeurs découverts ; fusion dans les 6 configs existantes via `enabled_companies()` |
| `sources/source_discovery_v1.py` + `config/discovery_seeds_v1.json` | Moteur : domaine → page carrière → ATS → validation (liste seule) → registre ; repli universel ; devinette de slug ; 6 fils ; rapports `exports/logs/discovery_*/` |
| `sources/registry_expansion_v1.py` | 5 `SourceSpec` : LEVER, ASHBY, WORKABLE, PERSONIO, JSONLD_SITES (179 specs au total) |
| `diagnostics/expansion_sources_v1_audit.py` | 39 tests hors ligne, inscrit dans `run_all.py` |
| `diagnostics/source_coverage_matrix.py`, `diagnostics/expansion_diag_pack.py` | Matrice CSV et ZIP de diagnostic |
| `EXPANSION_SOURCES.bat` | Menu : audit, découverte (graines ou domaines tapés), matrice + ZIP, état du registre |

Vérifications réseau faites pendant la mission (échantillons, pas de run) : Actiris 600 offres sur 3 pages, Forem 300 lignes export, Forem détail JSON OK, Lever Deliverect 35 offres (3 belges, 6 000 caractères), Personio Intigriti (flux OK, 0 belge ce jour), JSON-LD Teamleader (11 offres) et Delaware (84 offres) avec descriptions complètes, Workday Materialise 21 offres belges, Recruitee Aikido 41 belges.

Résultats de la campagne de découverte sur les graines : voir `ROADMAP_SOURCE_EXPANSION.md` et `exports/logs/discovery_seeds_v1/REPORT.txt`.
