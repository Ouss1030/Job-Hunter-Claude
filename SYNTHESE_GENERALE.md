# Job Hunter Belgium — synthèse générale

**Document unique de référence. Mis à jour le 2 septembre 2026.**

Il rassemble l'ensemble des mesures, défauts prouvés, corrections appliquées et
axes d'amélioration établis sur le projet. Toutes les mesures ont été refaites en
lecture seule sur le dossier de travail principal, sans jamais le modifier.

Chaque affirmation porte le chiffre qui la fonde et la commande qui la reproduit.

---

## Sommaire

- [Résumé exécutif](#résumé-exécutif)
- [Partie I — État mesuré du projet](#partie-i--état-mesuré-du-projet)
- [Partie II — Défauts prouvés et corrections appliquées](#partie-ii--défauts-prouvés-et-corrections-appliquées)
- [Partie III — Les dix axes d'amélioration](#partie-iii--les-dix-axes-damélioration)
- [Partie IV — Fichiers obsolètes et volume disque](#partie-iv--fichiers-obsolètes-et-volume-disque)
- [Partie V — Revue du lot « pipeline reliability »](#partie-v--revue-du-lot--pipeline-reliability-)
- [Partie VI — Plan d'action consolidé](#partie-vi--plan-daction-consolidé)
- [Partie VII — Principes de méthode](#partie-vii--principes-de-méthode)
- [Annexes](#annexes)

---

# Résumé exécutif

Huit chiffres suffisent à décrire la situation.

| Mesure | Valeur | Ce qu'elle signifie |
|---|---|---|
| Sources déclarées / productives | **84 / 35** | 49 sources activées ne rapportent rien |
| Part des 5 sources historiques | **98,3 %** | le volume vient d'ailleurs que du travail récent |
| Densité des sources directes | **55,6 % contre 16,4 %** | mais leur qualité est 3,4× supérieure |
| Descriptions trop courtes | **84,3 %** | le pré-score décide sur 164 caractères |
| Modules Python atteignables | **178 / 427** | 58 % du code n'est relié à rien |
| Diagnostics classés | **65 / 213** | dont 88 qui ne sont pas des diagnostics |
| Poids des sauvegardes | **8,1 Go** | 9 copies complètes de la base |
| Candidatures envoyées | **1** | pour 43 dossiers prêts |

**La lecture en une phrase.** Le moteur collecte beaucoup, trie mal, garde tout,
et n'envoie presque rien — mais la piste ouverte récemment (les employeurs
directs) est la plus prometteuse du projet et mérite d'être poursuivie, avec un
instrument pour distinguer ce qui marche de ce qui ne marche pas.

---

# Partie I — État mesuré du projet

## I.1 Volumétrie du code

```
modules sources            82
diagnostics               213
scripts .py à la racine    88
fichiers README           144
fichiers .bat             135
modules Python (total)    427
lignes de Python      105 102
```

## I.2 Sources et rendement

```
sources déclarées          84        (22 la veille)
sources actives            84
sources produisant         35        (6 la veille)
sources muettes            49
offres actives          5 939
```

Le mouvement est réel : 29 sources supplémentaires produisent effectivement des
offres. Les connecteurs GSK, Pfizer, Novartis, J&J, IBA, Akkodis, Randstad,
Jefferson Wells et Quality Assistance sont sortis du silence.

### Répartition réelle

```
ACTIRIS            4 618        JEFFERSON_WELLS     19
FOREM                480        AKKODIS             19
JOBAT                435        RANDSTAD            11
SMARTRECRUITERS      202        QUALITY_ASSISTANCE   5
TRAVAILLERPOUR       102        JNJ                  2
TALENT_BRUSSELS        3        GSK / PFIZER / NOVARTIS / IBA   1 chacune
```

Les cinq sources historiques font **98,3 %** des offres. Les trente nouvelles en
totalisent **99**.

## I.3 Le chiffre qui inverse la lecture

Le volume est trompeur. La bonne mesure est la **densité en offres pertinentes** :

```
sources historiques    5 840 offres    955 pertinentes    16,4 %
nouvelles sources         99 offres     55 pertinentes    55,6 %
```

**Les sources employeurs directes sont 3,4 fois plus denses.**

Jefferson Wells seul apporte une série d'intitulés directement dans la cible :

```
Laboratory Technician        QC Specialist         Lab Analyst
Technicien de laboratoire    QC Engineer (micro)   QC Equipment Specialist
ELN Business Analyst         technicien QC 2 shifts
```

À comparer au pool final actuel, qui compte 61 offres. Ces 55 offres denses ne
sont pas un détail.

**Conclusion : la stratégie des sources directes fonctionne.** Ce n'est pas le
principe qu'il faut corriger, c'est le tri entre les 35 qui rapportent et les 49
qui ne rapportent rien.

### Reproduire

```python
import sqlite3, re
HIST = {"ACTIRIS","FOREM","JOBAT","SMARTRECRUITERS","TRAVAILLERPOUR","TALENT_BRUSSELS"}
con = sqlite3.connect("file:database/jobs.db?mode=ro", uri=True)
rows = con.execute("SELECT source, title FROM raw_jobs WHERE is_active=1").fetchall()
M = re.compile(r"(?<![a-z])(laborant|laboratoire|qc|analyst|technicien|data)(?![a-z])", re.I)
for nom, sel in (("historiques", lambda s: s in HIST), ("nouvelles", lambda s: s not in HIST)):
    g = [r for r in rows if sel(r[0])]
    p = [r for r in g if M.search(r[1] or "")]
    print(nom, len(g), len(p), f"{100*len(p)/max(len(g),1):.1f} %")
```

## I.4 Couverture géographique

```
Flandre      2 496    43,0 %
Bruxelles    1 794    30,9 %
Wallonie       368     6,3 %
sans code    1 152    19,8 %
```

Ce n'est pas une source manquante, c'est une méthode d'interrogation différente :
Actiris collecte un catalogue large, Forem fait une recherche ciblée sur
199 termes. Tout ce que ces termes ne couvrent pas en Wallonie reste invisible.

Or GSK Wavre, UCB Braine-l'Alleud, Baxter Lessines et IBA Louvain-la-Neuve sont
wallons — ce sont précisément les employeurs concernés par les connecteurs
récents.

## I.5 Candidatures

```
77 candidatures suivies
71 SHORTLISTED
43 READY
 1 APPLIED
```

43 dossiers prêts, un seul parti.

---

# Partie II — Défauts prouvés et corrections appliquées

## II.1 Géographie : deux familles de faux positifs

### Le constat

Le module de détection belge acceptait comme belges des localisations qui ne le
sont pas. Testé avant correction : **11 cas justes sur 20**.

```
Hoboken, NJ 07030      → belge     (New Jersey)
Hoboken, New Jersey    → belge
Charleroi, PA          → belge     (Pennsylvanie)
Ghent, KY              → belge     (Kentucky)
Waterloo, ON           → belge     (Ontario)
Antwerp, NY            → belge     (New York)
Brussels, Wisconsin    → belge
Suite 1200, Boston     → belge     (« 1200 » lu comme code postal)
Building 2000          → belge
Room 4500, Basel       → belge     (Bâle, siège de Roche et Novartis)
Poste ouvert en 2026   → belge     (un millésime)
```

### Le mécanisme

Neuf villes belges ont un homonyme étranger :

```
hoboken     Hoboken NJ (USA)         waterloo   Waterloo ON (Canada), IA (USA)
antwerp     Antwerp OH et NY (USA)   brussels   Brussels WI (USA)
ghent       Ghent KY et NY (USA)     charleroi  Charleroi PA (USA)
bruges      Bruges (France)          mons       Mons (France)
hasselt     Hasselt (Pays-Bas)
```

Quand l'ATS écrit le pays en toutes lettres, le filtre tient. Quand il écrit
`Hoboken, NJ` — le format le plus courant — la ville belge l'emporte, parce
qu'aucune subdivision n'est reconnue comme étrangère.

Le second défaut est de même nature, transposé aux nombres : tout entier à
quatre chiffres était traité comme un code postal belge.

### Les corrections appliquées

**1. Subdivisions étrangères reconnues.** États américains et provinces
canadiennes en toutes lettres, plus les codes à deux lettres. Ces derniers
n'entrent en jeu qu'**après une virgule et en capitales**, sinon `ON`, `IN`,
`OR`, `DE`, `LA`, `MA`, `ME` et `OK` matcheraient des mots ordinaires. `BE` et
`LU` sont volontairement exclus : l'un est la Belgique, l'autre la province de
Luxembourg.

**2. Un code postal seul ne conclut plus.** Il reste extrait — il donne la
province, utile à l'appelant — mais il ne décide plus à lui seul.

### Le résultat

```
avant   11 / 20
après   26 / 26
```

L'audit du module passe de **51 à 70 tests**, tous verts.

### La non-régression, mesurée sur les données réelles

Le risque d'un durcissement est de perdre de vraies offres. Vérifié sur les
5 430 localisations de la base :

```
statut            avant    après    delta
BE_CONFIRMED       5 423    5 423       +0
BE_LIKELY              4        0       -4
BE_UNKNOWN             0        1       +1
BE_EXCLUDED            3        6       +3

offres belges perdues : 0
```

Les 4 seules reclassées sont `9999, PL` (×3) et `9999, FR` — des codes bidons
étrangers. **Aucune offre belge perdue, 4 faux positifs corrigés.**

Le durcissement paraissait risqué : 2 437 offres ont un code postal sans ville
reconnue. Vérification faite, **toutes portent « Belgique »** et sont confirmées
par le nom du pays. Seules 4 offres reposaient sur le code postal seul, et aucune
n'était belge.

C'est le type de vérification qui distingue une correction d'un pari.

## II.2 L'instrument qui manquait

Ajout de `diagnostics/source_yield_audit.py` : il croise le registre des sources
avec le contenu réel de la base et signale toute source active n'ayant jamais
rien produit.

```bash
python -m diagnostics.source_yield_audit
```

Lecture seule, intégré à la suite (**35/35**).

**Son premier verdict porte sur le travail fait ici.** Les cinq connecteurs ATS
construits dans ce dossier — Recruitee, Greenhouse, Workday, SuccessFactors,
Phenom — n'ont jamais produit une seule offre :

```
Sources déclarées              11
Sources actives productives     5
Sources jamais en base          6
Part des 5 premières       100,0 %
```

C'est exactement le reproche adressé ailleurs. Un instrument qui ne se retourne
pas contre celui qui l'écrit ne sert à rien.

## II.3 Fichiers modifiés

| Fichier | Nature |
|---|---|
| `sources/location_belgium.py` | subdivisions étrangères + code postal corroboré, v1.0 → v1.1 |
| `diagnostics/location_belgium_v1_audit.py` | 51 → 70 tests, section « homonymes étrangers » |
| `diagnostics/source_yield_audit.py` | nouveau — rendement par source |
| `diagnostics/run_all.py` | enregistrement du nouvel instrument |

---

# Partie III — Les dix axes d'amélioration

## Axe 1 — Trier les 49 sources muettes, ne pas les corriger en bloc

**Gravité : majeure.**

**Constat.** 49 sources actives ne produisent rien. Corriger 49 connecteurs est
un chantier ; savoir lesquels méritent l'effort est une mesure.

**Ce qu'il faut faire.** Instrumenter les collecteurs avec des compteurs de
motifs, pour que le diagnostic de rendement puisse répondre *pourquoi* :

```
SEEN  TARGET_TITLE  DETAIL_OK  DETAIL_FAILED
BELGIUM_ACCEPTED  GEOGRAPHY_REJECTED  GEOGRAPHY_UNKNOWN
LANGUAGE_REJECTED  NON_TARGET  CONVERTED  PERSISTED  ERROR
```

Une source qui voit 0 annonce a un problème réseau. Une source qui en voit 200 et
n'en garde aucune a un problème de filtre. Ce sont deux chantiers différents, et
rien aujourd'hui ne permet de les distinguer.

**Règle.** Aucun `continue` correspondant à une exclusion importante ne doit
rester sans compteur.

## Axe 2 — Le risque géographique a changé de sens

**Gravité : majeure.**

**Constat.** Tant que les connecteurs employeurs ne produisaient rien, un défaut
géographique ne coûtait que des offres perdues — invisible mais sans dommage.
Maintenant qu'ils produisent, **un faux positif va jusqu'au CV**.

Les tenants Workday pharma publient massivement depuis les États-Unis, le Japon,
Singapour, l'Inde et le Brésil. `Hoboken, NJ` est le format standard pour le New
Jersey, cœur de l'implantation américaine de Johnson & Johnson.

**Ce qu'il faut faire.** Faire passer les dix connecteurs employeurs par une
détection géographique unique, traitant subdivisions et faux codes postaux. Le
jeu de cas de la partie II sert de contrôle.

## Axe 3 — Ne pas confondre « source valide » et « source rentable »

**Gravité : moyenne.**

**Constat.** GSK, Pfizer, Novartis et IBA produisent **une offre chacune**. Ces
connecteurs sont probablement corrects : ces employeurs n'ont simplement pas
beaucoup de postes belges ouverts dans la cible à un instant donné.

C'est une distinction que le projet énonce déjà — « une source fiable avec zéro
cible actuelle peut être valide » — mais que rien ne mesure.

**Ce qu'il faut faire.** Suivre le rendement dans le temps, pas à un instant. Une
source à 1 offre sur trois mois n'est pas une source à 1 offre aujourd'hui. Le
seuil « marginal » du diagnostic de rendement est un premier signal ; il demande
un historique pour devenir une décision.

## Axe 4 — 84 % des offres ne sont jamais enrichies

**Gravité : majeure.**

**Constat.**

```
5 810 offres actives
4 895 avec une description < 300 caractères   (84,3 %)
  336 dont l'intitulé est pertinent
```

Exemples réels, avec la taille de leur description :

```
164 car.  Collaborateur.trice qualite (H/F/X)
239 car.  Technicien QA (H/F/X)
280 car.  Contrôleur qualité FR-UK (H/F/X)
234 car.  Controleur qualité tridimensionnel (H/F/X)
```

164 caractères, c'est un bloc de métadonnées sans une ligne d'annonce.

**Le cercle vicieux.**

```python
def select_candidate_jobs(pre_scored_jobs):
    return [
        (job, result)
        for job, result in pre_scored_jobs
        if result["core_relevance"]
    ]
```

`core_relevance` est calculé **avant** l'enrichissement, donc sur ces
164 caractères. Une offre mal décrite n'obtient jamais sa description, donc ne
peut jamais être scorée correctement, donc reste écartée. Le pré-score décide sur
une information qu'il a lui-même refusé d'aller chercher.

**La preuve que le potentiel est réel.** Douze offres écartées de ce type,
enrichies puis re-scorées :

```
0.0 → 64.4   Technicien Qualité & Production Béton
0.0 → 61.8   Technicien(ne) de laboratoire
0.0 → 61.8   Assistant laboratoire en alimentaire
0.0 → 59.8   Technicien Qualité & Production Béton
0.0 → 58.6   Technicien Qualité & Production Béton
0.0 → 50.0   Support Laboratoire Polyvalent
```

**Une sur deux.** Sur 336 offres concernées, l'ordre de grandeur est de
**150 offres récupérables**, contre 61 dans le pool actuel.

**Ce qu'il faut faire.** Une seconde porte d'entrée vers l'enrichissement : un
intitulé métier suffit quand la description est trop maigre. Deux garde-fous —
ne l'appliquer qu'aux descriptions effectivement courtes, et tester les termes
avec frontières lexicales, faute de quoi « Élaboration » matchera *labo* et
« Qatar » matchera *QA*.

Coût mesuré : environ 9 minutes au premier run, 30 secondes ensuite grâce au
cache.

## Axe 5 — Les exigences de néerlandais ne sont pas toutes détectées

**Gravité : majeure.**

**Constat.** Le niveau réel est **A2** — notions, sans capacité de travail. Le
Gate ne déduit une exigence que d'un niveau CECR explicite ou d'un mot de
fluidité. Ces formulations, les plus courantes en Belgique, passent au travers :

```
"Je hebt een goede kennis Nederlands"    "maîtrise du néerlandais exigée"
"tweetalig NL/FR vereist"                "bilingue FR/NL indispensable"
"bonne connaissance du néerlandais requise"
```

Sur un run de 575 offres, six mal classées, dont :

```
98.8   Laborant Biopharma Product Testing   (Eurofins)
92.8   Laborant M/V/X
```

La première était en `READY_APPLY` : un dossier complet aurait été préparé pour
une offre inaccessible.

**Ce qu'il faut faire.** Étendre l'inférence, avec trois précautions :

1. Ne l'appliquer qu'aux langues réellement non maîtrisées (A1/A2), sinon
   « good knowledge of English required » ferait basculer en STRETCH des offres
   accessibles.
2. Respecter les formulations optionnelles : « est un atout », « is een
   pluspunt », « preferred » ne doivent pas bloquer.
3. Traiter « bilingue » et « tweetalig » comme une exigence de néerlandais — en
   Belgique, bilingue signifie FR/NL.

Les formulations alternatives (« français OU néerlandais ») restent acceptables.
Tester la non-régression sur le français et l'anglais.

## Axe 6 — Les audits épinglent des valeurs qui bougent

**Gravité : moyenne.**

**Constat.** 22 occurrences dans les diagnostics :

```
8 × _VERSION == "1.2"      6 × _VERSION == "1.1"
5 × _VERSION == "1.0"      3 × _VERSION == "1.3.2"
```

S'y ajoutent des résultats de run figés — `check("37 APPLY_NOW", len(...) == 37)`.

**Trois cas observés :**

| Événement | Effet |
|---|---|
| `daily_run` 1.0.2 → 1.1.0 | 3 audits sains passent au rouge |
| `main.py` 10.4.1 → 10.5 | **le préflight bloque tout le Daily Run** |
| `hardening_step7` | devenu faux en moins d'une heure, par ses propres auteurs |

Le vrai risque n'est pas le test : c'est qu'un diagnostic qui crie au loup sans
raison finit par ne plus être lu. Le jour où il signale un vrai problème — les
49 sources muettes, par exemple — personne ne le voit.

**Ce qu'il faut faire.** Comparer des structures, pas des chaînes.

```python
def at_least(courant, minimum):
    a = tuple(int(x) for x in courant.split("."))
    b = tuple(int(x) for x in minimum.split("."))
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) >= b + (0,) * (n - len(b))
```

Piège intermédiaire : `startswith("1.0")` semble régler le problème mais casse
dès `1.1.0` et accepterait `1.05`. C'est la même erreur de fond que le matching
par sous-chaîne — comparer du texte là où il faut comparer une structure.

**Règle.** Un audit ne doit épingler que ce qui ne doit *jamais* changer. Ni un
numéro de version, ni un compte de diagnostics, ni une taille de pool. Il doit
exprimer une propriété : *au moins cette version*, *ce motif attrape ceci et pas
cela*, *au moins une offre*.

## Axe 7 — Duplication entre connecteurs Workday

**Gravité : moyenne.**

**Constat.** Similarité du code seul, docstrings et commentaires retirés :

```
gsk.py    vs jnj.py       81 %   |  260 lignes identiques
gsk.py    vs pfizer.py    85 %   |  265 lignes identiques
jnj.py    vs pfizer.py    86 %   |  274 lignes identiques
```

Volume : **1 252 lignes** pour trois employeurs partageant le même ATS, dont le
client `WorkdayClient` est *déjà* factorisé.

**Nuance importante.** La factorisation existe déjà en partie — c'est à porter au
crédit du projet. Ce qui reste dupliqué, c'est la couche au-dessus du client :
pagination, filtrage, conversion. C'est aussi précisément la couche où vit le
défaut géographique, ce qui explique qu'il soit corrigé dans certains modules et
pas dans les autres.

Et cette duplication n'est **pas générale** :

```
ucb    vs takeda              21 %
ucb    vs randstad            26 %
takeda vs randstad            16 %
takeda vs quality_assistance  33 %
```

**Une seule autre paire mérite la fusion** : `ucb.py` vs `thermofisher.py`, à
**89 %** et 406 lignes identiques. Fusionner de force les autres produirait un
module à conditions imbriquées, plus difficile à maintenir que cinq modules
clairs. La duplication réelle est d'environ 1 300 lignes, pas de plusieurs
milliers.

**Ce qu'il faut faire.** Déplacer la logique commune dans le client partagé, et
réduire chaque employeur à sa configuration : tenant, site, sites belges, termes
de recherche. **Ne pas jeter la connaissance métier** — `TARGET_TITLE_PATTERNS`,
`NON_TARGET_TITLE_PATTERNS` et `SEARCH_TERMS` sont du travail utile, à reporter.

## Axe 8 — Couverture wallonne

**Gravité : moyenne.**

**Constat.** La Wallonie représente 6,3 % des offres.

**Nuance mesurée.** Élargir Forem n'est pas la bonne réponse. Le dataset public
contient 25 313 offres actives, mais l'union des 199 termes du profil plafonne
autour de **800**, dont 490 sont déjà collectées. Une collecte élargie à des
racines génériques (« technicien », « production ») a été testée : **2,7 % des
résultats seulement** dépassent 50 de score. Élargir dilue.

**Ce qu'il faut faire.** Le gain réel est plus modeste et plus sûr : trois termes
seulement sont tronqués par le plafond de 100 résultats par mot-clé —
« opérateur de production » (360 disponibles), « quality control » (170),
« contrôle qualité » (165). Relever ce plafond récupère des offres directement
pertinentes, sans bruit.

## Axe 9 — Le point de décision sur Jobat

**Gravité : à trancher.**

**Constat.** Le connecteur bascule sur un navigateur Edge piloté par Playwright
lorsque le site renvoie **403, 429 ou 503** :

```python
if response.status_code not in (403, 429, 503):
    ...
class _EdgeFetcher:
    ...
    print("    Jobat Edge : page anti-bot détectée")
```

Le code identifie lui-même la page comme une protection anti-bot.

**Pourquoi il faut trancher.** La documentation du projet l'exclut explicitement
— « Ne pas contourner le 403 / anti-bot […] PAS de scraper anti-bot Jobat » — et
les conditions de Mediahuis vont dans le même sens. Or `JOBAT` est actif et la
source a produit **435 offres** : elle n'est pas dormante, elle est en production.

**Ce qu'il faut faire.** Une décision explicite, dans un sens ou dans l'autre.
Soit la règle du projet change en connaissance de cause, soit le connecteur est
retiré. Le laisser actif sans trancher, c'est faire tourner en production ce que
la documentation interdit.

À noter : les sites carrière lus via sitemap public sont dans une situation
**différente**. Leur `robots.txt` autorise explicitement les chemins `/job/`, et
ils publient un sitemap destiné aux machines. Il n'y a rien à contourner.

## Axe 10 — Une seule candidature envoyée

**Gravité : majeure.**

**Constat.**

```
77 candidatures suivies    71 SHORTLISTED    43 READY    1 APPLIED
```

**Pourquoi c'est le point le plus important.** Aucune donnée réelle ne valide le
Matcher. Personne ne sait si une offre à 139/100 obtient plus de réponses qu'une
à 90. Tous les seuils — scoring, Gate, priorisation — reposent sur des valeurs
devinées, jamais confrontées.

C'est aussi ce qui rend les autres axes difficiles à hiérarchiser : sans retour
réel, on optimise à l'aveugle. Et c'est ce qui explique qu'un défaut comme les
sources muettes ait pu passer inaperçu — quand rien ne part, rien ne manque
visiblement.

**Ce qu'il faut faire.** Envoyer trois candidatures parmi les 43 prêtes et
enregistrer leur statut. À 15–20 candidatures suivies, des questions aujourd'hui
sans réponse deviennent mesurables :

```
source    track    score    statut Gate    CV utilisé
date candidature   réponse   entretien   rejet   délai
```

C'est la seule chose qui transformera le pipeline en système qui apprend, plutôt
qu'en système qui collecte.

---

# Partie IV — Fichiers obsolètes et volume disque

## IV.1 Méthode

« Obsolète » ne peut pas vouloir dire « ça a l'air vieux ». Quatre critères
vérifiables ont été appliqués, du plus sûr au plus faible :

1. **Déclaré remplacé par le projet lui-même** — liste `REPLACED` dans
   `run_all.py`.
2. **Remplacé par une version ultérieure** présente sur disque.
3. **Non atteignable** depuis les points d'entrée vivants, via le graphe
   d'imports réel, en comptant comme vivant tout script invoqué par un `.bat`.
4. **Copie de sauvegarde ou dossier de transit**, identifié par son emplacement.

Un fichier peut être ancien et vivant. Un script lancé à la main par un `.bat` a
été compté comme vivant.

## IV.2 Le poste dominant : 8,1 Go de sauvegardes

```
backups/            8,1 Go        79 sous-dossiers, 145 fichiers
```

Davantage que tout le reste du projet réuni. La répartition par type est sans
ambiguïté :

```
db       9 fichiers     8,02 Go      <- 99 % du poids
py     117 fichiers        ~0
json    17 fichiers        ~0
txt      2 fichiers        ~0
```

**Neuf fichiers portent la totalité du problème.** Les 136 autres — copies de
`registry.py`, de `belgium_locations.py`, de configurations — ne pèsent rien et
ne se suppriment que pour la lisibilité.

Ces 9 copies de la base ont été prises au fil des intégrations :

```
1 085,6 Mo   backups/post_main_pipeline_pre_20260901_222206/jobs.db
1 044,9 Mo   backups/jobs_pre_vnext14_real_main_20260901_213513/jobs.db
1 001,1 Mo   backups/jobs_pre_mega5_final_main_20260901_191703/jobs.db
  956,3 Mo   backups/jobs_pre_v39_batch3_6_20260901_164906/jobs.db
  913,5 Mo   backups/jobs_pre_v39_batch2_13_20260831_235118/jobs.db
  870,7 Mo   backups/jobs_pre_v39_batch2_10_20260831_231025/jobs.db
  ... 3 autres
```

Sauvegarder avant une migration est une bonne pratique. Le problème n'est pas le
principe, c'est qu'aucune copie n'est jamais supprimée.

## IV.3 La cause réelle : la base elle-même

La base vivante pèse **1,13 Go pour 5 939 offres actives**. L'explication est
mesurable :

```
canonical_job_sources     174 932 lignes
canonical_jobs            174 468 lignes
raw_job_run_items         157 846 lignes
dedup_review_candidates    93 516 lignes
raw_jobs                   12 386 lignes   (dont 5 939 actives)
```

`canonical_jobs` contient **34 `build_id` distincts × 5 131 lignes en moyenne**.
Chaque build réécrit un instantané complet, description comprise, et aucun ancien
n'est élagué. La table conserve 34 photographies successives du même catalogue.

**C'est un effet de levier.** Chaque build ajoute ~5 000 lignes à la base, chaque
migration copie la base entière. Élaguer les builds anciens réduirait à la fois
la base et toutes les sauvegardes futures.

```python
import sqlite3
con = sqlite3.connect("file:database/jobs.db?mode=ro", uri=True)
print(con.execute("SELECT COUNT(DISTINCT build_id), COUNT(*) FROM canonical_jobs").fetchone())
```

## IV.4 Obsolescence déclarée par le projet

`run_all.py` maintient un dictionnaire `REPLACED` associant chaque diagnostic
périmé à son successeur.

```
25 diagnostics explicitement déclarés remplacés
```

C'est la preuve la plus forte disponible : ce ne sont pas des fichiers jugés
obsolètes de l'extérieur, ce sont des fichiers que le projet **sait** obsolètes
et conserve.

S'y ajoutent **16 diagnostics** dont le successeur est vérifiable par sa version :

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

**15 README** dont une version supérieure existe :

```
README_SCIENSANO_V350  V351  V352  V353  V3531  V354     (6 périmés sur 7)
README_TAKEDA_V300     V301                              (2 périmés sur 4)
README_AKKODIS_V250    README_GSK_V260    README_JOBAT_V213
README_SCIENCEATWORK_V220
README_HANDOFF_BUNDLE_V2_1_2   V2_1_4
```

**5 candidats `daily_run`** superposés :

```
daily_run_v101_candidate.py   v102   v110   v111   v120
```

## IV.5 Dossiers de transit

```
backups/                 145 fichiers    8,1 Go
_payload/                 72 fichiers    1,1 Mo
_step9_1_payload/          1 fichier       8 Ko
hardening_files/           1 fichier
hardening_step2_files/     6 fichiers
hardening_step4b_files/    1 fichier
hardening_step6b_files/    2 fichiers
hardening_step7_files/     1 fichier
lifecycle_step8f_b_files/  1 fichier
```

Ils contiennent des copies de fichiers déjà installés ailleurs
(`sources/registry.py`, `config/versioning.py`, `sources/belgium_locations.py`…).
Ils servaient au transit d'un lot vers son emplacement définitif ; le transit a
eu lieu.

**Total : 230 fichiers, 8,1 Go.**

## IV.6 Code non atteignable

```
modules Python du projet        427
points d'entrée vivants          85
atteignables                    178
NON ATTEIGNABLES                249     (58 %)
```

Répartition :

```
diagnostics/    132        sources/    8        interface/   2
racine/          84        config/     6        matching/    2
autres           15
```

**Nuance importante.** Non atteignable ne veut pas dire inutilisable : un
diagnostic reste lançable par `python -m diagnostics.foo`. Ce que le chiffre
établit, c'est que **rien dans le projet ne pointe vers ces 249 fichiers** — ni
import, ni `.bat`, ni `run_all`.

## IV.7 Le dossier diagnostics a changé de nature

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
d'intégration à usage unique — `mega_batch5_10_recover4_specific.py`,
`batch4_3_integrate4_resolve4.py`, `run_batch2_9_integrate_az_amgen.py`…

Le dossier destiné à surveiller le projet est devenu son journal de bord.

## IV.8 Scripts de migration

```
66 scripts upgrade_/install_/apply_/rollback_ à la racine
```

Dont **40 ne sont référencés par aucun autre `.py`**. Les 26 restants ne le sont
que par leur propre script d'exécution, lui-même à usage unique :

```
upgrade_v39_mega5_10.py          <-  mega_batch5_10_recover4_specific.py
upgrade_v39_batch4_3_direct4.py  <-  batch4_3_integrate4_resolve4.py
upgrade_v39_batch2_4_registry.py <-  run_batch2_4_registry_integration_4.py
```

**L'obsolescence se propage** : une migration référencée uniquement par son
lanceur reste morte. Les 66 forment des lots complets avec leur `.bat` et leur
`README`.

À l'échelle de la racine :

```
144 README_*.md      135 .bat      88 scripts .py
```

Chaque étape produit son triplet script + `.bat` + `README`. La racine est
devenue l'historique du projet plutôt que son contenu.

## IV.9 Synthèse chiffrée

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
**Avec les migrations et runners : environ 450 fichiers.**

---

# Partie V — Revue du lot « pipeline reliability »

Deux fichiers ont été livrés dans le projet principal en réponse à l'audit
initial. Ils ont été évalués par exécution réelle, pas par lecture.

## V.1 Ce qui fonctionne

**Le diagnostic de rendement.** Exécuté, il reproduit le constat exactement. Il
est strictement en lecture seule — aucune écriture, base ouverte en `mode=ro` —
et honnête sur sa portée : « ne distingue pas encore réseau / géographie / langue
/ non-cible ». C'est la bonne façon de livrer un instrument.

**Le classifieur géographique.** Testé sur 26 cas, **23 corrects** en v1.0. Les
pièges annoncés sont tenus : `BE` ne matche pas *Berlin*, *Bruges, France* est
rejeté, *Luxembourg* seul donne UNKNOWN. C'est nettement au-dessus des dix listes
dispersées qu'il remplace.

## V.2 Les trois défauts identifiés

**Défaut 1 — les abréviations d'États ne sont pas reconnues comme étrangères.**
6 faux positifs sur 8 formats Workday réels. Quand le pays est écrit en toutes
lettres, ça passe ; sinon la ville belge gagne.

**Défaut 2 — tout nombre à quatre chiffres est lu comme un code postal belge.**
4 faux positifs, dont `Room 4500, Basel` — Bâle étant le siège de Roche et
Novartis.

**Défaut 3 — le wrapper booléen annule le bénéfice des trois états.** Le document
de conception pose la bonne règle (« le résultat ne doit pas être un simple
booléen »), mais le wrapper de compatibilité écrase `UNKNOWN` et `FOREIGN` en
`False`. C'est le chemin de migration le plus tentant, une ligne par connecteur,
et il reconduit le rejet silencieux que le lot visait à supprimer.

## V.3 Re-test après mise à jour v1.1

```
côté belge     10 / 10   inchangé, solide
côté étranger   0 / 10   les deux familles subsistent
```

Le seul changement observé est l'ajout du Japon aux pays étrangers. La liste de
villes a par ailleurs été réduite (120 alias → ~24), ce qui réduit la surface du
problème sans le traiter.

## V.4 Point de méthode

La validation annoncée était `py_compile`. Elle valide la syntaxe, jamais le
comportement : les trois défauts sont dans du code qui compile parfaitement.

Les six critères de validation prévus passaient tous — aucun ne contenait
d'abréviation d'État ni de numéro de bureau. C'est précisément pourquoi ces
défauts ne se seraient pas vus.

Un fichier de cas attendus, exécuté à chaque livraison, les montre en une
seconde.

---

# Partie VI — Plan d'action consolidé

## VI.1 Priorités

### Immédiat — le volume, sans risque

1. **`backups/`** : conserver la sauvegarde la plus récente, envoyer les
   78 autres sous-dossiers à la corbeille. **Gain ≈ 7 Go**, aucun impact sur le
   code.
2. **Élaguer `canonical_jobs` et `canonical_job_sources`** : ne garder que les 2
   ou 3 derniers `build_id`. La base retombe à une taille normale, et chaque
   sauvegarde future avec elle.
3. **Ajouter une rétention** aux sauvegardes : garder les 3 dernières.

### Court terme — ce qui décide

4. **Instrumenter les collecteurs** (axe 1). Sans compteurs de motifs, les
   49 sources muettes se corrigent à l'aveugle, et le succès de Jefferson Wells
   ne se distingue pas de l'échec des autres.
5. **Unifier la détection géographique** (axe 2), en traitant subdivisions et
   faux codes postaux. Le risque a changé de sens : un faux positif va désormais
   jusqu'au CV.

### Moyen terme — ce qui rapporte

6. **Seconde porte d'enrichissement** (axe 4) : ~150 offres récupérables, contre
   61 dans le pool actuel.
7. **Exigences de néerlandais** (axe 5) : évite de préparer des dossiers pour des
   offres inaccessibles.

Ces deux axes gagnent des offres **sans ajouter une seule source**.

### Ensuite — ce qui protège

8. **Dépingler les audits** (axe 6).
9. **Ranger** : les lots déclarés obsolètes, puis les migrations par lots
   complets (partie IV).
10. **Factoriser** les connecteurs Workday et la paire UCB/Thermo Fisher
    (axe 7).

### En parallèle, sans attendre

11. **Envoyer trois candidatures** (axe 10). Elles apporteront plus
    d'information sur la qualité réelle du pipeline que n'importe quel autre
    axe.

## VI.2 Ordre de suppression recommandé

1. `backups/` sauf la plus récente — 7 Go, sans risque.
2. Élagage des builds `canonical_*` — traite la cause.
3. `_payload/`, `_step9_1_payload/`, les six `*_files/`.
4. Les 25 diagnostics `REPLACED`, les 16 à successeur vérifié, les 15 README
   périmés, les 5 candidats `daily_run`.
5. Les 66 migrations avec leur `.bat` et leur `README` — récupérables depuis git.
6. Le reste, **après vérification des dépendances** :

```bash
grep -rl "nom_du_module" --include=*.py . | grep -v __pycache__
```

## VI.3 Règles pour que le désordre ne revienne pas

- Un fichier de documentation **par composant**, avec un historique interne,
  plutôt qu'un fichier par version.
- Une **rétention** sur les sauvegardes et un **élagage** des builds.
- Les scripts one-shot **hors** du dossier qui sert à surveiller le projet.
- Aucun `continue` d'exclusion importante **sans compteur**.
- Aucun audit épinglant une valeur qui bouge.

---

# Partie VII — Principes de méthode

Ces trois principes se dégagent des mesures ci-dessus et valent au-delà de ce
projet.

## Un rejet silencieux est une perte invisible

Le filtre géographique jetait des offres sans compteur ni log, alors que le
filtre linguistique, trois lignes plus bas, les comptait et les journalisait :

```python
if location and not _is_belgium_location(location):
    continue                              # aucun compteur, aucune trace

if language == "nl":
    rejected_nl += 1                      # compté
    print(f"[...] NL | {title}")          # journalisé
```

C'est ce qui a permis à des connecteurs de rester muets sans que rien ne
l'indique. Toute décision d'exclusion doit laisser une trace chiffrée, sinon
personne ne saura jamais ce qu'elle coûte.

## Un diagnostic vert ne prouve pas un impact

Une suite entièrement au vert coexistait avec 49 sources muettes et ~150 offres
pertinentes écartées. Les audits vérifient qu'un composant fait ce qu'il
annonce ; aucun ne vérifiait qu'il rapporte quelque chose.

C'est la raison d'être du diagnostic de rendement — et son premier verdict a
porté sur le travail de celui qui l'a écrit.

Avant de coder un correctif, mesurer combien d'offres il change sur le dernier
run. Si c'est zéro, le documenter et passer à autre chose.

## Le matching de texte doit toujours avoir des frontières

C'est la cause commune du bug V.I.E historique, d'« Evere » qui matchait
« Beveren », des listes de villes qui se rataient entre elles, de `Room 4500`
lu comme un code postal, et de `startswith("1.0")` qui casse en 1.1.0.

Le projet possède déjà l'outil : `phrase_regex()`, documenté par *« "fabric" ne
doit PAS matcher "fabrication" »*. Il est utilisé neuf fois dans son fichier
d'origine, et presque nulle part ailleurs.

**Corollaire** : compiler n'est pas tester. Les deux familles de faux positifs
géographiques étaient dans du code qui compilait parfaitement.

---

# Annexes

## A. Documents produits

| Fichier | Lignes | Contenu |
|---|---|---|
| `SYNTHESE_GENERALE.md` | — | ce document, point d'entrée unique |
| `AXES_AMELIORATION.md` | 352 | les dix axes, détaillés avec preuves |
| `RAPPORT_FICHIERS_OBSOLETES.md` | 325 | analyse d'obsolescence, 4 critères |
| `REVUE_V380_STEP1.md` | 381 | revue du lot livré, à transmettre |
| `CONTEXTE_COMPLET.md` | 508 | contexte fonctionnel du projet |

## B. Code modifié dans ce dossier

| Fichier | Nature |
|---|---|
| `sources/location_belgium.py` | v1.0 → v1.1 : subdivisions étrangères, code postal corroboré |
| `diagnostics/location_belgium_v1_audit.py` | 51 → 70 tests |
| `diagnostics/source_yield_audit.py` | nouveau : rendement par source |
| `diagnostics/run_all.py` | enregistrement du nouvel instrument |

État de la suite : **35/35**.

## C. Commandes de vérification

```bash
python -m diagnostics.run_all
```

```bash
python -m diagnostics.source_yield_audit
```

```bash
python -m diagnostics.location_belgium_v1_audit
```

## D. Mesures reproductibles

**Densité en offres pertinentes par famille de sources** — partie I.3.

**Rendement par source :**

```python
import sys, sqlite3; sys.path.insert(0, ".")
from sources.registry import list_source_status
actifs = {r["key"] for r in list_source_status() if r["active"]}
con = sqlite3.connect("file:database/jobs.db?mode=ro", uri=True)
produites = {s for (s,) in con.execute("SELECT DISTINCT source FROM raw_jobs")}
print(sorted(actifs - produites))
```

**Descriptions trop courtes :**

```python
import sqlite3
con = sqlite3.connect("file:database/jobs.db?mode=ro", uri=True)
rows = con.execute("SELECT title, COALESCE(detail_matching_text, description) d "
                   "FROM raw_jobs WHERE is_active=1").fetchall()
print(sum(1 for r in rows if len(r[1] or "") < 300), "/", len(rows))
```

**Accumulation des builds :**

```python
import sqlite3
con = sqlite3.connect("file:database/jobs.db?mode=ro", uri=True)
print(con.execute("SELECT COUNT(DISTINCT build_id), COUNT(*) FROM canonical_jobs").fetchone())
```

**Similarité entre connecteurs :**

```python
import pathlib, difflib, re
def norm(nom):
    s = pathlib.Path(f"sources/{nom}.py").read_text(encoding="utf-8")
    s = re.sub(r'""".*?"""', " ", s, flags=re.S)
    s = re.sub(r"#.*", " ", s)
    return [l.strip() for l in s.splitlines() if l.strip()]
print(difflib.SequenceMatcher(None, norm("gsk"), norm("jnj")).ratio())
```

**Jeu de cas géographiques** — à figer dans un audit :

```python
# doivent être écartés
"Hoboken, NJ 07030"   "Charleroi, PA"   "Ghent, KY"   "Waterloo, ON"
"Antwerp, NY"   "Brussels, Wisconsin"   "Boston, MA"   "Tokyo, Japan"
"Suite 1200, Boston"   "Building 2000"   "Room 4500, Basel"   "9999, PL"

# doivent rester belges
"Wavre"   "Braine-l'Alleud"   "Lessines, Wallonia"   "1000 Bruxelles"
"Brussels, Belgium"   "Gent, BE"   "Hoboken"   "Charleroi"   "Bruges"
```

Les trois derniers sont importants : le correctif ne doit pas rendre le
classifieur timide au point de perdre les vraies villes belges homonymes.
