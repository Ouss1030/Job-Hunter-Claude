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

**iCIMS (16/09/2026)** : liste paginée `in_iframe=1` + JSON-LD JobPosting par page, via `collect_pages` de l'extracteur universel. BDO Belgium (40 listées, 135 au total), Jan De Nul (98). AXA et PepsiCo : portails iCIMS détectés mais listes vides sur l'hôte trouvé → à reprendre. **Bullhorn** : Manpower, Experis, Select HR sont des vitrines maison (Rails, WordPress, Webflow) sans API publique ni JSON-LD JobPosting — pas de connecteur générique possible ; Jefferson Wells reste couvert par son connecteur dédié.


La campagne a détecté des employeurs belges sur des ATS que le projet ne lit pas encore (liste dans `SOURCE_COVERAGE_MATRIX.csv`, lignes `ATS <nom>`). Ordre par nombre d'employeurs détectés : CVWarehouse 7 (provinces d'Anvers et du Brabant flamand, HOGENT, Thomas More, AZ Turnhout, Vivalia, Greenyard), Oracle Cloud 5 (Défense, Aperam, Carmeuse, Euroclear, Telenet), Bullhorn 4 (Manpower, Jefferson Wells, Select HR, Experis), iCIMS 4 (Jan De Nul, PepsiCo, BDO, AXA), Radancy 3 (Sanofi, Cargill, ING), Carerix 2, Cornerstone 2, Avature 2, Eightfold 2, Taleo 1 (UZ Leuven), BrassRing 1, Talentsoft 1. Chaque connecteur écrit sert d'emblée à tous les employeurs déjà détectés, et à ceux que la découverte trouvera ensuite. Ce sont pour la plupart des endpoints JSON internes documentés par l'usage (Taleo `careersection/rest/jobboard/searchjobs`, Cornerstone `services/x/career-site/v1/search`, Oracle Cloud `hcmRestApi/resources/latest/recruitingCEJobRequisitions`, Radancy sitemap + JSON-LD via `JSONLD_SITES`).

## Étape 3 — deuxième réservoir de graines : les employeurs vus dans les offres

Actiris et Forem nomment l'employeur de chaque offre (33 000 + 26 000 offres → plusieurs milliers d'employeurs distincts, avec numéro BCE côté Actiris). Mode `--depuis-base` du moteur : les 300 employeurs les plus présents → devinette d'identifiant d'API + recherche du domaine → découverte. Coût : ~2 000 requêtes, une fois. Gain : leurs offres canoniques avec description complète, sans passer par la page détail.

## Étape 4 — Federgon → graines

**Fait le 16/09/2026 :** `sources/federgon_seeds_v1.py` lit la page « Les membres » (478 domaines de prestataires RH) et les passe au moteur (`--decouvrir`). Campagne lancée le jour même.

## Étape 5 — clés API gratuites (action utilisateur)

Adzuna, Careerjet, Jooble : connecteurs écrits, clés absentes. Trois formulaires en ligne, gratuits. Ajoutent des descriptions et de la découverte (URL de candidature externe → ATSDetector).

## Étape 6 — VDAB officiel

Demander un accès à l'API `Vacatures` (ibm-api-key). En attendant, 8 874 offres VDAB/Forem arrivent via Actiris.

## Étape 7 — BCE/KBO

**Outil prêt le 16/09/2026 :** `sources/bce_seeds_v1.py` lit le ZIP Open Data de la BCE (compte gratuit sur kbopub.economie.fgov.be, ~500 Mo), croise activité NACE × statut actif × site web déclaré, et produit les graines (`config/discovery_seeds_bce.json`), puis lance la découverte par tranches. Il manque le fichier : l'inscription est personnelle.

**Première campagne le 16/09/2026** (fichier 0484) : 113 553 entreprises dans les NACE cibles, 2 390 actives avec site web, 1 215 passées au moteur (cabinets médicaux écartés) → 25 sources actives (24 nouvelles), 70 offres belges validées ; 1 166 sans voie publique (PME sans portail carrière). Rendement : 2 %, soit un employeur par 50 domaines — la BCE trouve ce que rien d'autre ne trouve (Allnex, Kronos, Stepan, Covestro, Stora Enso, Intertek, Laborelec, SAS, SDL), mais le gros de l'emploi PME reste sur le Forem. Prochaine tranche possible : NACE 62/63 (informatique, données) et unités d'établissement.

## Étape 8 — le dernier repli : portails maison (HTML)

**Fait le 16–17/09/2026 :** `sources/html_generique_v1.py` (V1.1) lit un portail carrière sans API, sans flux et sans JSON-LD : liens d'offre depuis la page carrière (ou depuis un hub, un cran plus loin), contenu principal de chaque page, lieu par code postal suivi d'un nom ou par commune connue, preuve d'offre par vocabulaire (au moins trois familles parmi postuler / profil / missions / contrat / compétences / dates / ce qu'on offre — calibré sur 190 pages de huit portails). Idée reprise du projet principal (`job_quality_guard`), durcie : leur version prenait toute la page et n'exigeait rien.

Recampagne sur les 46 graines francophones sans voie : 10 enregistrées (Letec → SuccessFactors, Province d'Anvers → CVWarehouse, 8 portails HTML). Après calibrage : **UNamur 8/8, GHdC 10/11, Prayon 14/14, Brabant wallon 5/16, HELHa 24/64 (bourse de stages étudiants), Eurobrussels 21/22 (job board affaires européennes, `lien_regex` = `/job_display/\d+`)** — 82 offres, descriptions de 2 500 à 10 000 caractères. Namur (namur.be : pages d'information) et CHU Liège (résultats rendus en JavaScript) désactivés avec motif. Restent hors de portée : Chirec (TalentFinder), CHU Charleroi, CHwapi, Citadelle, Cliniques de l'Europe, Solidaris, Mithra, Eurogentec, FN Herstal, Spadel, CMI — CMS sans URL d'offre lisible ou liste en JavaScript ; ceux-là passent par le Forem/Actiris quand ils y publient.

## Hors périmètre, et pourquoi

LinkedIn, Indeed, StepStone, Jobat en direct : anti-bot ou conditions d'utilisation. Le projet ne contourne rien. StepStone, Jobat et Références republient déjà vers Forem/Actiris : ils sont absorbés par là. Une URL d'offre isolée collée par l'utilisateur passe par `extraire_offre(url)` (JSON-LD) ou par l'ATSDetector, sans scraping de liste.
