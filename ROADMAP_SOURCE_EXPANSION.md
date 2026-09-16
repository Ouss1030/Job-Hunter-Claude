# ROADMAP — EXPANSION DES SOURCES

Fondée sur le code constaté (voir `AUDIT_EXPANSION_SOURCES.md`) et sur la campagne de découverte du 15 septembre 2026 (`exports/logs/discovery_seeds_v1/REPORT.txt`). Le principe ne change pas : **collecter le plus largement possible d'abord, filtrer et scorer ensuite.**

## Fait (cette mission)

| Incrément | Résultat mesuré |
|---|---|
| Absorption complète Actiris | 33 208 offres disponibles (au lieu de 4 331 actives), provenance exacte, pages de 200 |
| Absorption complète Forem | 26 198 offres en une requête (au lieu de 345), description via API JSON `DetailOffre` |
| Budget de détail par run | 2 500 nouvelles pages / source / run, cache définitif ; réglable dans `config/absorption_settings.json` |
| ATSDetector | 32 ATS reconnus (URL, redirections, liens, HTML), identifiant extrait, routage vers le connecteur |
| Connecteurs 2e génération | Lever, Ashby, Workable, Personio — API/XML publics, description complète |
| Extracteur universel | sitemap + JSON-LD JobPosting : Teamtailor, Jobtoolz, Talentfinder, sites maison |
| Source Discovery Engine | domaine → page carrière → ATS → validation → registre ; repli universel ; 6 fils |
| Registre employeurs | `config/ats_employers_v2.json`, fusionné dans les 6 connecteurs de 1re génération |
| Campagne graines | 396 domaines en 17 min → **101 sources actives (95 nouvelles)**, +5 après revalidation SuccessFactors ; registre : **109 employeurs** (SuccessFactors 45, Workday 20, JSON-LD 18, Recruitee 9, Phenom 5, Greenhouse 4, Personio 4, SmartRecruiters 2, Ashby 1, Lever 1) ; **843 offres belges validées** sur les seules listes API (les 50 hôtes SuccessFactors/Phenom ne sont comptés qu'au run) ; 35 employeurs sur 12 ATS sans connecteur ; 241 domaines sans voie publique (sites JS sans sitemap ni JSON-LD) |

## Étape 1 (immédiate) — premier run d'absorption, puis mesure

Un `TEST_DAILY_RUN.bat` ordinaire. Ce qu'il fera de nouveau : ~60 000 offres brutes au lieu de 12 000, détail des 2 500 offres pertinentes les plus fraîches par source, le reste au run suivant. Ensuite `python -m diagnostics.source_coverage_matrix` pour lire, source par source, offres uniques et descriptions obtenues — c'est `unique_jobs_from_source`, la mesure qui décide de la suite.

Critère d'acceptation : ACTIRIS ≥ 30 000 actives, FOREM ≥ 24 000, aucune source existante en régression, diagnostics `run_all` verts.

## Étape 2 — connecteurs pour les ATS détectés sans connecteur

**Fait le 16/09/2026 :** Oracle Recruiting Cloud (API REST publique : Telenet 62 offres belges, Euroclear 16, Aperam 9, Carmeuse 3 ; Défense sur domaine vanity non relayé → en attente) et CVWarehouse (pages servies par le serveur, une page de détail par section porte toutes les offres : HOGENT 14, Thomas More 14, AZ Turnhout 33, Provincie Antwerpen 13, Vivalia 51, Greenyard 26 belges sur 66). Registre : 132 employeurs, 14 ATS.


La campagne a détecté des employeurs belges sur des ATS que le projet ne lit pas encore (liste dans `SOURCE_COVERAGE_MATRIX.csv`, lignes `ATS <nom>`). Ordre par nombre d'employeurs détectés : CVWarehouse 7 (provinces d'Anvers et du Brabant flamand, HOGENT, Thomas More, AZ Turnhout, Vivalia, Greenyard), Oracle Cloud 5 (Défense, Aperam, Carmeuse, Euroclear, Telenet), Bullhorn 4 (Manpower, Jefferson Wells, Select HR, Experis), iCIMS 4 (Jan De Nul, PepsiCo, BDO, AXA), Radancy 3 (Sanofi, Cargill, ING), Carerix 2, Cornerstone 2, Avature 2, Eightfold 2, Taleo 1 (UZ Leuven), BrassRing 1, Talentsoft 1. Chaque connecteur écrit sert d'emblée à tous les employeurs déjà détectés, et à ceux que la découverte trouvera ensuite. Ce sont pour la plupart des endpoints JSON internes documentés par l'usage (Taleo `careersection/rest/jobboard/searchjobs`, Cornerstone `services/x/career-site/v1/search`, Oracle Cloud `hcmRestApi/resources/latest/recruitingCEJobRequisitions`, Radancy sitemap + JSON-LD via `JSONLD_SITES`).

## Étape 3 — deuxième réservoir de graines : les employeurs vus dans les offres

Actiris et Forem nomment l'employeur de chaque offre (33 000 + 26 000 offres → plusieurs milliers d'employeurs distincts, avec numéro BCE côté Actiris). Mode `--depuis-base` du moteur : les 300 employeurs les plus présents → devinette d'identifiant d'API + recherche du domaine → découverte. Coût : ~2 000 requêtes, une fois. Gain : leurs offres canoniques avec description complète, sans passer par la page détail.

## Étape 4 — Federgon → graines

Annuaire des membres Federgon (intérim, recrutement, project sourcing) → domaines → moteur. Objectif : les petites agences régionales que personne ne liste.

## Étape 5 — clés API gratuites (action utilisateur)

Adzuna, Careerjet, Jooble : connecteurs écrits, clés absentes. Trois formulaires en ligne, gratuits. Ajoutent des descriptions et de la découverte (URL de candidature externe → ATSDetector).

## Étape 6 — VDAB officiel

Demander un accès à l'API `Vacatures` (ibm-api-key). En attendant, 8 874 offres VDAB/Forem arrivent via Actiris.

## Étape 7 — BCE/KBO

Quand les étapes 2–4 sont stables : open data BCE → noms actifs par NACE → domaine → moteur. La BCE devient un multiplicateur, pas une table inerte.

## Hors périmètre, et pourquoi

LinkedIn, Indeed, StepStone, Jobat en direct : anti-bot ou conditions d'utilisation. Le projet ne contourne rien. StepStone, Jobat et Références republient déjà vers Forem/Actiris : ils sont absorbés par là. Une URL d'offre isolée collée par l'utilisateur passe par `extraire_offre(url)` (JSON-LD) ou par l'ATSDetector, sans scraping de liste.
