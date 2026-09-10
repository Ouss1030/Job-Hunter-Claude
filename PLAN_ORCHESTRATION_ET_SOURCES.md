# Job Hunter Belgium — orchestration et élargissement des sources

**Document destiné à l'équipe de développement. 3 septembre 2026.**

Deux sujets, dans cet ordre : **rendre l'orchestration fiable**, puis **ajouter
un maximum de sources**. L'ordre n'est pas négociable — ajouter des sources à un
pipeline non instrumenté multiplie le bruit sans qu'on puisse le mesurer.

Toutes les affirmations sur les sources externes ont été **vérifiées en direct**
(robots.txt, sitemaps, documentation d'API) et sont datées. Les résultats sont
cités verbatim.

---

## Sommaire

- [Partie A — Orchestration](#partie-a--orchestration)
- [Partie B — Sources disponibles, vérifiées](#partie-b--sources-disponibles-vérifiées)
- [Partie C — Sources fermées, et pourquoi](#partie-c--sources-fermées-et-pourquoi)
- [Partie D — La déduplication devient critique](#partie-d--la-déduplication-devient-critique)
- [Partie E — Plan d'exécution](#partie-e--plan-dexécution)

---

# Partie A — Orchestration

## A.1 Le constat qui commande tout le reste

```
sources déclarées        84
sources actives          84
sources produisant       36
sources muettes          48
```

48 sources activées ne rapportent rien, et **rien dans le système ne dit
pourquoi**. Réseau ? Filtre trop strict ? Aucune cible réelle ? Ce sont trois
problèmes différents, avec trois correctifs différents.

Tant que cette question reste sans réponse, ajouter des sources revient à
augmenter le nombre de cas qu'on ne sait pas diagnostiquer.

## A.2 Ce qui existe déjà — et c'est une bonne base

L'infrastructure d'instrumentation est en place :

```
sources/source_metrics.py       store de métriques
sources/source_yield.py         rendement
publish_metrics()               publication par source
publish_metrics_from_locals()   publication automatique
```

**35 modules sur 82** émettent des métriques. Le principe est bon, il est déjà
codé, il ne demande qu'à être généralisé.

## A.3 Le défaut structurel de `publish_metrics_from_locals`

Ce mécanisme publie les variables locales existantes. C'est élégant, et c'est
précisément ce qui le rend trompeur : **il ne peut rapporter que les compteurs
que quelqu'un a pensé à créer.**

Dans `sources/gsk.py` :

```python
rejected_nl = 0
...
if location and not _is_belgium_location(location):
    continue                     # aucune variable, donc aucun compteur

if language == "nl":
    rejected_nl += 1             # compté, publié, visible
...
publish_metrics_from_locals("GSK", locals())
```

Le module est « instrumenté ». Le rejet linguistique est visible. **Le rejet
géographique est invisible** — il n'existe aucune variable à publier.

C'est le pire cas de figure : un tableau de bord qui affiche des colonnes, dont
certaines resteront vides sans que personne ne s'en aperçoive.

### Correctif : un contrat de compteurs explicite

Ne pas se reposer sur `locals()`. Définir un jeu de compteurs obligatoire,
initialisé à zéro en début de collecte, pour que **l'absence de compteur devienne
une erreur visible** plutôt qu'un silence :

```python
COMPTEURS = (
    "seen", "target_title", "non_target",
    "detail_ok", "detail_failed",
    "geography_accepted", "geography_rejected", "geography_unknown",
    "language_rejected",
    "converted", "persisted", "errors",
)

def nouveaux_compteurs() -> dict[str, int]:
    return {nom: 0 for nom in COMPTEURS}
```

Et une vérification au moment de publier :

```python
def publish_metrics(source, metrics):
    manquants = [c for c in COMPTEURS if c not in metrics]
    if manquants:
        print(f"  ⚠️  {source} : compteurs manquants — {', '.join(manquants)}")
    ...
```

**Règle : aucun `continue` correspondant à une exclusion ne doit rester sans
compteur.** Cette règle figure déjà dans la documentation du projet ; il manque
le mécanisme qui la rend impossible à oublier.

## A.4 Corriger la géographie avant de brancher quoi que ce soit

`sources/belgium_locations.py` v1.1 est désormais câblé sur `gsk`, `jnj`,
`pfizer`, `lonza`, `roche` et quatre moteurs. Testé aujourd'hui : **3 cas justes
sur 13.**

```
Hoboken, NJ 07030    → BELGIUM        Room 4500, Basel      → BELGIUM
Charleroi, PA        → BELGIUM        Building 2000         → BELGIUM
Ghent, KY            → BELGIUM        Poste ouvert en 2026  → BELGIUM
Waterloo, ON         → BELGIUM        Suite 1200, Boston    → BELGIUM
Antwerp, NY          → BELGIUM
```

Le côté belge est solide (10/10) ; c'est le côté étranger qui cède.

**Pourquoi c'est urgent maintenant.** Tant que ces connecteurs ne produisaient
rien, le défaut était latent. Ils produisent. `Hoboken, NJ` est exactement le
format Workday pour le New Jersey — c'est-à-dire le cœur américain de Johnson &
Johnson, et `jnj.py` utilise ce classifieur. Une offre étrangère acceptée va
jusqu'au CV ; une offre belge perdue reste invisible. Le second défaut coûte du
temps, le premier coûte de la crédibilité.

### Les deux correctifs, mesurés

**1. Reconnaître les subdivisions étrangères**, testées avant la reconnaissance
de ville : noms d'États américains et de provinces canadiennes en toutes lettres,
plus les codes à deux lettres — **uniquement après une virgule et en capitales**,
sinon `ON`, `IN`, `OR`, `DE`, `LA`, `MA`, `ME` et `OK` matchent des mots
ordinaires. Exclure `BE` (la Belgique) et `LU` (la province de Luxembourg).

**2. Un code postal seul ne conclut plus.** Il reste extrait — il donne la
province — mais ne décide plus seul.

**Résultat après correction : 26 cas justes sur 26.**

**Non-régression vérifiée sur 5 430 localisations réelles :**

```
statut            avant    après    delta
BE_CONFIRMED       5 423    5 423       +0
BE_LIKELY              4        0       -4
BE_UNKNOWN             0        1       +1
BE_EXCLUDED            3        6       +3

offres belges perdues : 0
```

Les 4 reclassées sont `9999, PL` (×3) et `9999, FR` — des codes bidons
étrangers, donc 4 faux positifs corrigés au passage.

Le durcissement du code postal paraissait risqué : 2 437 offres ont un code
postal sans ville reconnue. Vérification faite, **toutes portent « Belgique »**
et passent par le nom du pays. Seules 4 reposaient sur le code seul, et aucune
n'était belge.

## A.5 Ne pas ré-emballer les trois états en booléen

Le classifieur renvoie `BELGIUM / FOREIGN / UNKNOWN`. Les connecteurs migrés
l'importent correctement… puis l'écrasent :

```python
from sources.belgium_locations import classify_belgium_location   # 3 états

def _is_belgium_location(location):                               # → booléen
    decision = classify_belgium_location(location)
    return decision.status == BELGIUM
...
if location and not _is_belgium_location(location):
    continue                                                      # sans compteur
```

`UNKNOWN` et `FOREIGN` deviennent tous deux `False`, et une offre sans
localisation exploitable subit le même sort qu'une offre à Munich.

### Le motif d'appel correct

```python
decision = classify_belgium_location(location, trusted_belgium_listing=trust)

if decision.status == FOREIGN:
    compteurs["geography_rejected"] += 1
    continue
if decision.status == UNKNOWN:
    compteurs["geography_unknown"] += 1
    continue          # écarté, mais compté séparément et donc révisable
compteurs["geography_accepted"] += 1
```

Trois lignes de plus, et la question « où passent les offres ? » devient
répondable.

## A.6 Un contrat de source unique

Aujourd'hui chaque connecteur a sa forme. C'est ce qui rend l'ajout d'une source
coûteux et son diagnostic impossible.

Un contrat minimal :

```python
@dataclass
class ResultatCollecte:
    source: str
    offres: list[JobOffer]
    compteurs: dict[str, int]      # les 12 compteurs obligatoires
    erreurs: list[str]
    mode: str                      # "api" | "sitemap" | "jsonld" | "html"
    duree_s: float
```

Toute source renvoie cet objet. Le registre n'a plus qu'à agréger. Le diagnostic
de rendement lit les compteurs sans rien parser.

**Point important** : l'audit de couverture actuel
(`source_keyword_coverage_v1_audit.py`) reconstruit ces chiffres en **parsant du
texte** (`parse_metric`, `parse_runtime`). Cela fonctionne, mais c'est fragile —
un changement de format d'affichage casse la mesure. Avec un contrat, la donnée
est structurée à la source.

## A.7 Configuration plutôt que code

62 modules de sources ont été ajoutés récemment. Beaucoup partagent le même
moteur et ne diffèrent que par leurs paramètres.

Une source qui utilise un moteur existant ne devrait pas être un module Python
mais une entrée de configuration :

```python
{
    "key": "LONZA",
    "label": "Lonza",
    "engine": "workday",
    "tenant": "lonza",
    "site": "External",
    "search_terms": ["QC", "quality control", "laboratory technician"],
    "belgium_sites": ["Braine-l'Alleud", "Verviers"],
    "enabled": True,
}
```

Bénéfice direct : ajouter dix sources devient dix entrées, pas dix fichiers avec
dix copies du même bug potentiel.

**Ne pas jeter la connaissance métier** au passage — `TARGET_TITLE_PATTERNS`,
`NON_TARGET_TITLE_PATTERNS` et `SEARCH_TERMS` sont du travail utile, à déplacer
dans la configuration, pas à supprimer.

## A.8 Le pipeline, vu de haut

```
REGISTRE (config)
   ↓  contrat unique
COLLECTE  →  compteurs obligatoires par source
   ↓
GÉOGRAPHIE  →  BELGIUM / FOREIGN / UNKNOWN, chacun compté
   ↓
DÉDUPLICATION  →  clé canonique inter-sources        ← Partie D
   ↓
PRÉ-SCORE  →  + seconde porte pour descriptions maigres
   ↓
ENRICHISSEMENT
   ↓
GATE (langue, mobilité, diplôme)
   ↓
POOL FINAL  →  rendement mesuré par source
   ↓
CANDIDATURES  →  retour réel réinjecté dans le scoring
```

Deux maillons manquent aujourd'hui : la **déduplication inter-sources** (elle
existe mais accumule au lieu de trancher) et le **retour réel** (1 candidature
envoyée sur 43 prêtes).

---

# Partie B — Sources disponibles, vérifiées

Toutes les vérifications ci-dessous ont été faites le 3 septembre 2026.

## B.1 VDAB — la plus grosse source belge manquante

**C'est la recommandation numéro un.** La Flandre représente 43 % des offres
déjà collectées, et le service public flamand de l'emploi n'est pas intégré.

### Ce qui a été vérifié

`https://www.vdab.be/robots.txt` déclare des sitemaps dédiés aux offres :

```
Sitemap: https://www.vdab.be/sitemap/vindeenjob/vacatures/index.xml
Sitemap: https://www.vdab.be/sitemap/vindeenjob/index.xml
```

`/vac/` et `/vindeenjob/prive/` sont interdits. **`/vindeenjob/jobs/` ne l'est
pas.**

L'index de sitemap résout et contient **228 sitemaps enfants**, nommés par année
et semaine :

```
https://www.vdab.be/sitemap/vindeenjob/vacatures/index-2024-25-1.xml
https://www.vdab.be/sitemap/vindeenjob/vacatures/index-2024-26-1.xml
...
```

Un sitemap hebdomadaire récent contient **environ 1 000 à 1 200 URL d'offres** :

```
https://www.vdab.be/vindeenjob/vacatures/60152620/account-manager-verzekeringen
https://www.vdab.be/vindeenjob/vacatures/62374869/dossierbeheerder-verzekeringen-b2c
```

avec un `lastmod` par offre.

### Pourquoi c'est idéal

- **Partitionnement hebdomadaire** : la collecte incrémentale est native. On ne
  lit que les semaines récentes, pas les 228 sitemaps.
- **`lastmod` par offre** : le rafraîchissement devient trivial.
- **Sitemap publié pour les machines** : rien à contourner, c'est l'usage prévu.
- **Le projet sait déjà faire** : c'est exactement le motif des connecteurs
  sitemap + JSON-LD déjà en place.

### À vérifier avant de coder

Une seule chose : est-ce que les pages d'offres portent un bloc JSON-LD
`schema.org/JobPosting` ? Si oui, le connecteur est un quasi-copier-coller du
connecteur sitemap existant. Sinon, il faut lire le HTML.

**Le test coûte une requête.** À faire avant d'estimer la charge de travail.

## B.2 EURES — le portail européen officiel

EURES est le réseau officiel Commission européenne / Autorité européenne du
travail, agrégeant les services publics de l'emploi de l'UE, Islande,
Liechtenstein, Norvège et Suisse — donc **incluant Actiris, Forem et VDAB**.

Une API publique est documentée à `https://europa.eu/eures/api`, avec notamment :

```
POST /jv-searchengine/public/jv-search/search      recherche filtrée
GET  /jv-searchengine/public/jv/id/{id}            détail d'une offre
GET  ...                                           statistiques par pays/secteur
```

**Réserve honnête** : la documentation la plus complète trouvée est
**communautaire, non officielle**, et n'est pas endossée par la Commission. Les
endpoints doivent être validés directement avant tout développement, et le
statut d'usage confirmé.

**Intérêt** : source publique, filtrable par pays, gratuite. **Attention au
recouvrement** : EURES republie les offres d'Actiris, du Forem et du VDAB.
Utile surtout pour les employeurs qui publient *uniquement* via EURES.

## B.3 Jooble — API publique sur demande

Jooble expose une API REST documentée à `https://jooble.org/api/about` :

> « Our REST API allows you to take search queries from Jooble and post the
> results on your website in your own design. »

La clé s'obtient par un formulaire (nom, fonction, e-mail, site, téléphone). Des
exemples de code sont fournis en PHP, JavaScript, Ruby, C#, Python 2.7 et 3.5.

**Non confirmé sur la page** : gratuité, quotas, format exact des requêtes. À
valider à l'obtention de la clé.

**C'est le seul grand agrégateur généraliste avec une voie d'accès officielle
et simple.** À privilégier sur tous les autres agrégateurs.

## B.4 Adzuna — API publique multi-pays

Endpoint documenté, cité verbatim :

```
http://api.adzuna.com/v1/api/jobs/{country_code}/search/{page}?app_id={ID}&app_key={KEY}
```

Paramètres : `what`, `where`, `results_per_page`, `page`, plus `what_exclude`,
`salary_min`, `full_time`, `permanent`, `sort_by`.

**À vérifier en une requête** : la documentation consultée illustre `gb` et ne
confirme pas la présence de `be`. La liste complète des pays est dans la
référence interactive (`/activedocs`). **Tester `be` avant d'investir.**

Le paramètre `what_exclude` est intéressant pour ce profil : il permet d'écarter
« senior », « manager », « PhD » côté serveur.

## B.5 Google for Jobs — il n'y a pas d'API, mais il y a mieux

**Google ne propose aucune API publique de recherche d'emploi.** Google for Jobs
est une fonctionnalité de recherche, pas un service interrogeable. Les
intermédiaires qui prétendent l'exposer scrapent les pages de résultats Google,
ce que les conditions de Google interdisent.

**Mais le mécanisme sous-jacent est déjà exploité par le projet.** Google for
Jobs se nourrit du balisage `schema.org/JobPosting` en JSON-LD que les
employeurs publient sur leurs propres pages. Autrement dit :

> Tout ce qui apparaît dans Google for Jobs publie du JSON-LD lisible
> directement à la source.

Le projet possède déjà les connecteurs sitemap + JSON-LD. **La bonne stratégie
n'est pas de chercher une API Google, c'est de généraliser ce motif** : pour
chaque employeur cible, lire `robots.txt`, trouver le sitemap, extraire les
pages d'offres, lire le JSON-LD.

C'est plus fiable qu'un agrégateur — la donnée est de première main, complète, et
sans intermédiaire susceptible de fermer son accès.

## B.6 Autres pistes à évaluer

À vérifier selon la même méthode (robots.txt → sitemap → API documentée) :

| Source | Intérêt | Point à vérifier |
|---|---|---|
| **Le Forem** | déjà intégré via l'open data | relever le plafond de 100/mot-clé |
| **Actiris** | déjà intégré | — |
| **ADG** | communauté germanophone | volume probablement faible |
| **Talent.brussels** | déjà intégré, 3 offres | rendement à vérifier |
| **essenscia** | fédération chimie/pharma | job board sectoriel, très ciblé |
| **BioWin** | déjà intégré, 5 offres | pôle de compétitivité wallon |
| **flanders.bio** | équivalent flamand | à évaluer |
| **Careerjet** | API affiliée documentée | conditions à lire |
| **Arbeitnow** | API publique gratuite, Europe | couverture Belgique à mesurer |
| **The Muse** | API publique | orientation US, à mesurer |

**Méthode** : ne pas coder avant d'avoir mesuré le volume belge pertinent. Une
source qui rapporte 3 offres coûte autant à maintenir qu'une source qui en
rapporte 300.

---

# Partie C — Sources fermées, et pourquoi

Ces vérifications évitent de perdre du temps, et surtout de construire quelque
chose que la documentation du projet interdit.

## C.1 Indeed — fermé par robots.txt

`https://be.indeed.com/robots.txt`, bloc `User-agent: *` :

```
Disallow: /job/
Disallow: /Job/
```

**Les pages de détail d'offre sont interdites à tous les robots.** Ce sont
précisément les pages dont le projet aurait besoin.

Second point, plus net encore : le fichier contient un bloc dédié aux agents
d'IA — `GPTBot`, `CCBot`, `anthropic-ai` et d'autres — qui interdit en plus
`/jobs`, `/viewjob`, `/q-` et `/l-`. Indeed exprime explicitement son refus de
ce type de collecte.

**Recommandation : ne pas intégrer Indeed.** Ni en direct, ni via un
intermédiaire qui le scrape. Cela vaut aussi pour tout service tiers qui
revendrait des données Indeed obtenues de cette façon.

## C.2 StepStone — largement fermé

`https://www.stepstone.be/robots.txt` :

```
Disallow: /?*
Disallow: /*?*
Disallow: /jobs/full-time/*
Disallow: /emplois/plein-temps/*
```

Les chaînes de requête sont bloquées de façon quasi générale — donc la recherche
paramétrée est exclue. Quelques exceptions étroites existent
(`Allow: /vacatures/*?q=*`, temps partiel), mais elles ne couvrent pas le
besoin. **Aucune ligne `Sitemap:`.**

**Recommandation : ne pas intégrer StepStone** par crawl. Si la source est jugée
indispensable, la seule voie propre est un accord de licence de données.

## C.3 Jobat — la décision qui n'a pas été prise

`sources/jobat.py` bascule toujours sur un navigateur Edge piloté par Playwright
quand le site renvoie **403, 429 ou 503**, et le code imprime lui-même :

```python
print("    ⚠️ Jobat Edge : page anti-bot détectée")
```

La documentation du projet l'exclut explicitement — *« Ne pas contourner le 403 /
anti-bot […] PAS de scraper anti-bot Jobat »*. Or la source est active et produit
**435 offres**.

Point à porter au crédit du travail récent : le gestionnaire de consentement
clique **« Tout refuser » / « Alles weigeren »**, ce qui est le bon choix. Mais
cela ne change pas la question de fond.

**Recommandation : trancher explicitement et l'écrire.** Soit la règle du projet
évolue en connaissance de cause et c'est documenté, soit le connecteur est
retiré. Le statu quo — faire tourner en production ce que la documentation
interdit — est la seule option à exclure.

## C.4 Le critère à appliquer aux futures sources

Avant d'intégrer quoi que ce soit, dans cet ordre :

1. **Une API documentée existe-t-elle ?** → voie royale.
2. **Sinon, `robots.txt` autorise-t-il le chemin visé ?** → à lire, pas à
   supposer.
3. **Un `Sitemap:` est-il publié ?** → c'est une invitation explicite.
4. **Les pages portent-elles du JSON-LD `JobPosting` ?** → données structurées,
   pas d'analyse de mise en page.
5. **Le site renvoie-t-il 403 / une page anti-bot ?** → **arrêt**. Pas de
   contournement.

Ce test tient en trois requêtes et évite des jours de développement.

---

# Partie D — La déduplication devient critique

C'est le point que l'ajout d'agrégateurs rend incontournable.

## D.1 Le problème arrive avec les agrégateurs

Un agrégateur republie les offres d'autres sources. Une même offre Eurofins peut
arriver par le VDAB, par EURES, par Jooble, par Adzuna et par le site carrière
d'Eurofins — **cinq fois la même annonce**.

Sans déduplication solide, ajouter cinq agrégateurs ne multiplie pas la
couverture, il multiplie le bruit. Et le pool final devient inexploitable.

## D.2 L'état actuel

L'infrastructure existe, mais elle accumule au lieu de trancher :

```
canonical_job_sources     174 932 lignes
canonical_jobs            174 468 lignes     34 build_id × ~5 131 lignes
dedup_review_candidates    93 516 lignes
raw_jobs                   12 386 lignes     dont 5 939 actives
```

`canonical_jobs` conserve **34 instantanés successifs** du même catalogue, jamais
élagués. C'est ce qui porte la base à 1,13 Go — et chaque sauvegarde de migration
copie ce volume, d'où **8,1 Go dans `backups/`**.

**À faire avant d'ajouter des agrégateurs** : élaguer les anciens builds (ne
garder que les 2 ou 3 derniers) et mettre une rétention sur les sauvegardes.
Sinon chaque nouvelle source aggrave un problème déjà présent.

## D.3 Une clé canonique robuste

La déduplication inter-agrégateurs demande une clé qui résiste aux variations de
formulation :

```
employeur normalisé  +  intitulé normalisé  +  localisation normalisée
```

Avec, pour chaque composant :

- **employeur** : minuscules, accents retirés, suffixes juridiques supprimés
  (`SA`, `NV`, `BV`, `SPRL`, `BVBA`), espaces réduits ;
- **intitulé** : suffixes de genre retirés (`(H/F/X)`, `M/V/X`, `(m/w/d)`),
  numéros de référence retirés ;
- **localisation** : ramenée à la commune via le module géographique — c'est
  aussi ce qui rend la correction de la Partie A rentable une seconde fois.

**Piège à éviter** : ne pas dédupliquer sur l'URL. Chaque agrégateur a la sienne
pour la même offre.

**Règle de préférence** : quand un doublon est détecté, **garder la version de la
source la plus directe**. Le site carrière de l'employeur l'emporte sur
l'agrégateur — description complète, pas de troncature, lien de candidature
direct.

## D.4 Le rôle réel des agrégateurs

Une mesure change la façon de les envisager :

```
sources historiques (5 généralistes)   5 840 offres    955 pertinentes    16,4 %
sources employeurs directes               99 offres     55 pertinentes    55,6 %
```

**Les sources directes sont 3,4 fois plus denses en offres pertinentes.**

Conclusion pratique : un agrégateur ne devrait pas servir de source de collecte
principale, mais de **couche de découverte**.

```
AGRÉGATEUR  →  identifie un employeur belge qui recrute dans la cible
                            ↓
            détection de son ATS (Workday, SmartRecruiters, Phenom…)
                            ↓
CONNECTEUR DIRECT  →  collecte propre, complète, sans intermédiaire
```

Le projet possède déjà `diagnostics/ats_fingerprint`-like et des moteurs par ATS.
Brancher la découverte dessus transforme chaque agrégateur en générateur de
sources directes — c'est-à-dire en générateur de densité, pas de volume.

---

# Partie E — Plan d'exécution

## Étape 0 — Débloquer, sans risque (une demi-journée)

1. **Élaguer `canonical_jobs` / `canonical_job_sources`** : garder les 2 ou 3
   derniers `build_id`.
2. **`backups/`** : garder la sauvegarde la plus récente, supprimer les 78
   autres — **≈ 7 Go récupérés**, aucun impact sur le code.
3. **Ajouter une rétention** : 3 sauvegardes maximum.

## Étape 1 — Corriger avant d'étendre (un jour)

4. **Géographie** : subdivisions étrangères + code postal corroboré.
   Jeu de cas de contrôle en annexe. Objectif : 26/26.
5. **Compteurs obligatoires** : contrat explicite, avertissement si un compteur
   manque.
6. **Motif d'appel à trois états** dans les connecteurs déjà migrés — `gsk`,
   `jnj`, `pfizer`, `lonza`, `roche`.

À l'issue de cette étape, la question « où passent les offres ? » a une réponse
chiffrée pour chaque source.

## Étape 2 — Diagnostiquer les 48 muettes (un jour)

7. Lancer une collecte instrumentée et lire les compteurs. Trois familles
   apparaîtront : problème réseau, filtre trop strict, aucune cible réelle.
8. **Ne corriger que celles dont les compteurs montrent un vrai défaut.** Une
   source fiable sans cible actuelle est valide — elle doit être suivie dans le
   temps, pas réparée.

## Étape 3 — VDAB (un à deux jours)

9. Vérifier la présence de JSON-LD sur une page d'offre — **une requête**.
10. Connecteur sitemap hebdomadaire, en ne lisant que les semaines récentes.
11. Mesurer le rendement et la densité avant d'aller plus loin.

**C'est la source au meilleur rapport valeur/effort du projet** : service public,
sitemaps publiés pour les machines, partitionnement hebdomadaire natif, et elle
couvre les 43 % de marché flamand.

## Étape 4 — Déduplication (un jour)

12. Clé canonique employeur + intitulé + commune.
13. Règle de préférence : source directe > agrégateur.
14. Mesurer le taux de doublons **avant** d'ajouter d'autres agrégateurs.

## Étape 5 — Agrégateurs, un par un (un jour chacun)

15. **Jooble** — demander la clé, mesurer le volume belge pertinent.
16. **Adzuna** — vérifier `be` en une requête, puis mesurer.
17. **EURES** — valider les endpoints, mesurer le recouvrement avec Actiris,
    Forem et VDAB.

**Après chaque intégration** : rendement, densité, taux de doublons. Une source
qui n'améliore pas la densité du pool final ne doit pas être conservée.

## Étape 6 — Découverte plutôt que collecte

18. Extraire des agrégateurs la **liste des employeurs belges** qui recrutent
    dans la cible.
19. Détecter leur ATS.
20. Générer les connecteurs directs par configuration, pas par code.

## En parallèle, sans attendre

21. **Envoyer trois candidatures** parmi les 43 prêtes. Aucun seuil du Matcher
    n'a jamais été confronté à un retour réel : personne ne sait si une offre à
    139/100 obtient plus de réponses qu'une à 90.

C'est la seule action qui transforme le pipeline en système qui apprend.

---

# Annexe — Jeu de cas géographiques

À figer dans un audit, exécuté à chaque livraison. `py_compile` valide la
syntaxe, jamais le comportement : les faux positifs ci-dessous sont dans du code
qui compile parfaitement.

```python
# doivent être écartés — homonymes étrangers
"Hoboken, NJ"          "Hoboken, NJ 07030"     "Hoboken, New Jersey"
"Charleroi, PA"        "Ghent, KY"             "Waterloo, ON"
"Antwerp, NY"          "Brussels, Wisconsin"   "Boston, MA"
"Tokyo, Japan"         "9999, PL"

# doivent être écartés — faux codes postaux
"Suite 1200, Boston"   "Building 2000"
"Room 4500, Basel"     "Poste ouvert en 2026"

# doivent rester belges — non-régression
"Wavre"                "Braine-l'Alleud"       "Anderlecht"
"Lessines, Wallonia"   "1000 Bruxelles"        "Brussels, Belgium"
"Gent, BE"             "3560, Belgique"        "Jemeppe-sur-Sambre, 5190, Belgique"

# doivent rester belges — villes homonymes sans qualificatif étranger
"Hoboken"              "Charleroi"             "Waterloo"
"Gent"                 "Bruges"
```

Les quatre derniers sont les plus importants : le correctif ne doit pas rendre le
classifieur timide au point de perdre les vraies villes belges homonymes.

---

# Annexe — Résumé des vérifications externes

Toutes datées du 3 septembre 2026.

| Source | Vérification | Résultat |
|---|---|---|
| **VDAB** | robots.txt + sitemaps | **228 sitemaps hebdomadaires, ~1 000 offres/semaine, `/vindeenjob/jobs/` autorisé** |
| **EURES** | documentation API | API publique documentée, doc communautaire — **à valider** |
| **Jooble** | page API officielle | API REST, clé sur formulaire, exemples Python |
| **Adzuna** | documentation endpoint | endpoint confirmé, **couverture `be` à tester** |
| **Google for Jobs** | — | **aucune API publique** ; passer par le JSON-LD des employeurs |
| **Indeed** | robots.txt | **`Disallow: /job/` + bloc dédié aux agents IA** → ne pas intégrer |
| **StepStone** | robots.txt | **requêtes bloquées, aucun sitemap** → ne pas intégrer |

---

# Le principe qui résume tout

**Mesurer avant de construire, compter avant de filtrer.**

Le projet a ajouté 62 modules de sources en deux jours pour 99 offres, dont 48
sources qui ne rapportent rien — sans qu'aucun instrument ne puisse dire
pourquoi. Dans le même temps, une source publique majeure qui publie ses offres
en sitemap hebdomadaire, couvrant 43 % du marché belge, n'est pas intégrée.

L'écart entre ces deux faits n'est pas un manque de travail. C'est un manque de
mesure.
