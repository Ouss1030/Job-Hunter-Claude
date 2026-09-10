# Prompt à transmettre — élargissement de la couverture

À envoyer avec `PLAN_ORCHESTRATION_ET_SOURCES.md` en pièce jointe.

---

## Le prompt

```
CONTEXTE

Job Hunter Belgium collecte des offres d'emploi belges pour un profil
pharma/QC/laboratoire et data/BI junior. État mesuré au 3 septembre 2026 :

    84 sources déclarées, 84 actives, 36 produisant, 48 muettes
    5 917 offres actives
    5 sources historiques = 98,3 % du volume
    30 sources employeurs récentes = 99 offres

Objectif : élargir la couverture réelle. Pas le nombre de sources — le nombre
d'offres belges pertinentes qui arrivent jusqu'au pool final.

Un audit externe joint (PLAN_ORCHESTRATION_ET_SOURCES.md) contient les
vérifications faites en direct sur les sources candidates. Lis-le avant de
commencer.


ORDRE NON NÉGOCIABLE

Ne commence pas par ajouter des sources. Trois choses doivent être corrigées
d'abord, sinon chaque source ajoutée aggrave un problème existant.

ÉTAPE 0 — Libérer et assainir (rapide, sans risque)

  a) canonical_jobs contient 34 build_id × ~5 131 lignes, jamais élaguées.
     C'est ce qui porte la base à 1,13 Go. Ne garder que les 2 ou 3 derniers
     builds.
  b) backups/ pèse 8,1 Go, dont 8,02 Go en 9 copies complètes de la base.
     Garder la plus récente, supprimer les autres.
  c) Ajouter une rétention : 3 sauvegardes maximum.

  Vérifie avec :
      SELECT COUNT(DISTINCT build_id), COUNT(*) FROM canonical_jobs;

ÉTAPE 1 — Corriger la géographie AVANT de brancher de nouvelles sources

  sources/belgium_locations.py v1.1 est câblé sur gsk, jnj, pfizer, lonza,
  roche et quatre moteurs. Testé, il donne 3 réponses justes sur 13 :

      Hoboken, NJ 07030    -> BELGIUM   (New Jersey)
      Charleroi, PA        -> BELGIUM   (Pennsylvanie)
      Ghent, KY            -> BELGIUM   (Kentucky)
      Waterloo, ON         -> BELGIUM   (Ontario)
      Antwerp, NY          -> BELGIUM   (New York)
      Room 4500, Basel     -> BELGIUM   (Bâle)
      Building 2000        -> BELGIUM
      Suite 1200, Boston   -> BELGIUM
      Poste ouvert en 2026 -> BELGIUM

  Le côté belge est correct (10/10) ; c'est le côté étranger qui cède.
  jnj.py utilise ce classifieur, et "Hoboken, NJ" est le format Workday du
  New Jersey — cœur américain de Johnson & Johnson. Des offres américaines
  entrent donc dans un pipeline belge.

  Deux correctifs :

  1. Reconnaître les subdivisions étrangères AVANT la reconnaissance de ville.
     Noms d'États américains et de provinces canadiennes en toutes lettres,
     plus les codes à deux lettres — mais uniquement après une virgule et en
     capitales, sinon ON, IN, OR, DE, LA, MA, ME et OK matchent des mots
     ordinaires. Exclure BE (la Belgique) et LU (province de Luxembourg).

  2. Un code postal seul ne conclut plus. Tout nombre à quatre chiffres lui
     ressemble. Le garder comme donnée (il fournit la province), pas comme
     décision.

  Ce durcissement ne coûte rien : mesuré sur les 5 430 localisations réelles
  de la base, il ne dégrade AUCUNE offre belge. Les 2 437 offres à code postal
  sans ville portent toutes "Belgique". Les 4 seules reposant sur le code seul
  étaient "9999, PL" et "9999, FR", donc étrangères.

  Objectif : 26/26 sur le jeu de cas fourni en annexe du document joint.
  Fige ce jeu de cas dans un audit exécuté à chaque livraison.

ÉTAPE 2 — Rendre les rejets visibles

  Dans gsk.py, deux rejets consécutifs sont traités différemment :

      if location and not _is_belgium_location(location):
          continue                  # aucun compteur, aucune trace

      if language == "nl":
          rejected_nl += 1          # compté
          print(...)                # journalisé

  publish_metrics_from_locals() publie les variables locales : il ne peut donc
  rapporter que les compteurs que quelqu'un a pensé à créer. Aucun n'existe
  pour la géographie, donc le rejet géographique est invisible alors même que
  le module est "instrumenté".

  Définis un contrat de compteurs obligatoires, initialisés à zéro, avec un
  avertissement si l'un manque au moment de publier :

      seen, target_title, non_target,
      detail_ok, detail_failed,
      geography_accepted, geography_rejected, geography_unknown,
      language_rejected, converted, persisted, errors

  Et utilise les trois états au lieu de les écraser en booléen :

      decision = classify_belgium_location(location, trusted_belgium_listing=trust)
      if decision.status == FOREIGN:
          compteurs["geography_rejected"] += 1; continue
      if decision.status == UNKNOWN:
          compteurs["geography_unknown"] += 1; continue
      compteurs["geography_accepted"] += 1

  Applique-le d'abord aux connecteurs déjà migrés : gsk, jnj, pfizer, lonza,
  roche.

  Résultat attendu : pour chacune des 48 sources muettes, on doit pouvoir dire
  si elle échoue en réseau, si elle filtre trop, ou si elle n'a simplement
  aucune cible. Ne corrige que celles dont les compteurs montrent un vrai
  défaut — une source fiable sans cible actuelle est valide.


ÉTAPE 3 — VDAB, la source prioritaire

C'est le meilleur rapport valeur/effort du projet. La Flandre représente 43 %
des offres déjà collectées, et le service public flamand de l'emploi n'est pas
intégré.

Vérifié en direct le 3 septembre 2026 :

  - robots.txt publie des sitemaps dédiés aux offres :
        https://www.vdab.be/sitemap/vindeenjob/vacatures/index.xml
        https://www.vdab.be/sitemap/vindeenjob/index.xml
  - /vac/ et /vindeenjob/prive/ sont interdits ; /vindeenjob/jobs/ ne l'est pas
  - l'index résout et liste 228 sitemaps enfants, nommés par année-semaine :
        .../vacatures/index-2026-35-1.xml
  - un sitemap hebdomadaire contient ~1 000 à 1 200 URL d'offres, avec lastmod :
        https://www.vdab.be/vindeenjob/vacatures/60152620/account-manager-verzekeringen

Le partitionnement hebdomadaire rend la collecte incrémentale native : ne lis
que les semaines récentes, jamais les 228 sitemaps.

AVANT DE CODER : une seule requête sur une page d'offre pour vérifier si elle
porte un bloc JSON-LD schema.org/JobPosting. Si oui, le connecteur est un
quasi-copier-coller des connecteurs sitemap + JSON-LD existants. Sinon, il faut
lire le HTML. Cette requête décide de la charge de travail — fais-la avant
d'estimer.

Puis mesure : nombre d'offres belges retenues, densité en intitulés pertinents,
taux de doublons avec l'existant. Ne passe à la suite qu'après cette mesure.


ÉTAPE 4 — Déduplication, avant tout agrégateur

Un agrégateur republie les offres d'autres sources. Une même offre peut arriver
par le VDAB, EURES, Jooble, Adzuna et le site carrière de l'employeur. Sans
déduplication solide, ajouter des agrégateurs multiplie le bruit, pas la
couverture.

Clé canonique : employeur normalisé + intitulé normalisé + commune.

  - employeur : minuscules, accents retirés, suffixes juridiques supprimés
    (SA, NV, BV, SPRL, BVBA)
  - intitulé : suffixes de genre retirés ((H/F/X), M/V/X, (m/w/d)), références
    numériques retirées
  - commune : obtenue via le module géographique corrigé à l'étape 1

Ne déduplique jamais sur l'URL : chaque agrégateur a la sienne.

Règle de préférence : en cas de doublon, garder la version de la source la plus
directe. Le site carrière de l'employeur l'emporte sur l'agrégateur —
description complète, pas de troncature, lien de candidature direct.


ÉTAPE 5 — Agrégateurs, un par un, avec mesure entre chaque

  Jooble  — API REST, clé sur formulaire (jooble.org/api/about).
            Le seul grand agrégateur généraliste avec un accès officiel simple.

  Adzuna  — endpoint confirmé :
            http://api.adzuna.com/v1/api/jobs/{country}/search/{page}?app_id=..&app_key=..
            La couverture 'be' n'est PAS confirmée dans la doc consultée.
            Teste-la en une requête avant d'investir.
            Le paramètre what_exclude permet d'écarter senior/manager/PhD côté
            serveur.

  EURES   — API publique documentée à https://europa.eu/eures/api
            Réserve : la documentation la plus complète trouvée est
            communautaire, non endossée par la Commission. Valide les endpoints
            avant de développer.
            Attention au recouvrement : EURES republie Actiris, Forem et VDAB.

Après CHAQUE intégration : rendement, densité, taux de doublons. Une source qui
n'améliore pas la densité du pool final ne doit pas être conservée.


CE QU'IL NE FAUT PAS FAIRE

  Indeed — be.indeed.com/robots.txt contient "Disallow: /job/" pour tous les
  robots : ce sont exactement les pages de détail nécessaires. Un bloc dédié
  aux agents d'IA (GPTBot, CCBot, anthropic-ai) interdit en plus /jobs,
  /viewjob, /q- et /l-. Ne pas intégrer, ni directement, ni via un
  intermédiaire qui le scrape.

  StepStone — stepstone.be/robots.txt contient "Disallow: /*?*", qui bloque les
  chaînes de requête de façon quasi générale, et aucune ligne Sitemap. Ne pas
  intégrer par crawl.

  Google for Jobs — il n'existe aucune API publique. C'est une fonctionnalité
  de recherche. Ce qui l'alimente est le balisage schema.org/JobPosting que les
  employeurs publient eux-mêmes — c'est ce qu'il faut lire, directement à la
  source.

  Jobat — sources/jobat.py bascule toujours sur un navigateur Edge piloté par
  Playwright sur 403/429/503, et imprime lui-même "page anti-bot détectée",
  alors que la documentation du projet l'interdit. Tranche explicitement et
  écris la décision : soit la règle change en connaissance de cause, soit le
  connecteur est retiré. Ne développe aucun mécanisme de contournement
  supplémentaire.

  Ne crée pas un module Python par source. Une source qui utilise un moteur
  existant doit être une entrée de configuration : key, label, engine, tenant,
  search_terms, belgium_sites, enabled. Dix sources = dix entrées, pas dix
  fichiers.

  Ne crée pas un README et un .bat par étape. Un fichier de documentation par
  composant, avec un historique interne.


CRITÈRE POUR TOUTE SOURCE FUTURE

Dans cet ordre, avant d'écrire une ligne de code :

  1. Une API documentée existe-t-elle ?          -> voie royale
  2. Sinon, robots.txt autorise-t-il le chemin ? -> le lire, pas le supposer
  3. Un Sitemap: est-il publié ?                 -> invitation explicite
  4. Les pages portent-elles du JSON-LD ?        -> données structurées
  5. Le site renvoie-t-il 403 / anti-bot ?       -> ARRÊT, pas de contournement

Trois requêtes suffisent, et cela évite des jours de développement inutile.


DÉFINITION DE « TERMINÉ »

Pour chaque étape, livre :

  - le code ;
  - un audit qui fige les cas limites et échoue si le comportement régresse ;
  - la mesure AVANT / APRÈS sur les données réelles : offres retenues, densité
    en intitulés pertinents, taux de doublons, offres belges perdues.

py_compile valide la syntaxe, jamais le comportement. Les faux positifs
géographiques ci-dessus sont dans du code qui compile parfaitement. Un fichier
de cas attendus les montre en une seconde.

Si une correction ne change aucune offre sur le dernier run, dis-le et passe à
autre chose.


PRINCIPE GÉNÉRAL

Mesurer avant de construire, compter avant de filtrer.

62 modules de sources ont été ajoutés en deux jours pour 99 offres, dont 48
sources qui ne rapportent rien sans qu'aucun instrument ne puisse dire pourquoi.
Pendant ce temps, une source publique majeure qui publie ses offres en sitemap
hebdomadaire, couvrant 43 % du marché belge, n'est pas intégrée.

L'écart n'est pas un manque de travail. C'est un manque de mesure.
```

---

## Comment l'utiliser

**Envoie le prompt et le document `PLAN_ORCHESTRATION_ET_SOURCES.md` ensemble.**
Le prompt donne la marche à suivre, le document porte les preuves et le détail.

**Ne demande pas les six étapes d'un coup.** L'expérience du projet montre que
les livraisons larges produisent beaucoup de fichiers et peu de mesures. Le
prompt est écrit pour être donné en entier — il pose l'ordre — mais réclame la
livraison **étape par étape**, avec la mesure avant/après à chaque fois.

**Le point de contrôle le plus utile** est à la fin de l'étape 2 : à ce moment,
pour chacune des 48 sources muettes, on doit pouvoir dire si elle échoue en
réseau, si elle filtre trop, ou si elle n'a aucune cible. Tant que cette
question n'a pas de réponse chiffrée, l'ajout de sources est prématuré.

**Si tu veux aller plus vite**, la seule étape qu'on peut avancer en parallèle
est la vérification JSON-LD du VDAB (étape 3) : elle coûte une requête et décide
de la charge de travail du connecteur.
