# Job Hunter Belgium — état mesuré et axes d'amélioration

**Mis à jour le 1er septembre 2026.** Toutes les mesures ci-dessous ont été
refaites ce jour, en lecture seule. Chaque constat porte sa commande de
reproduction.

---

## 1. Où en est le projet

```
sources déclarées            84        (22 la veille)
sources actives              84
sources produisant           35        (6 la veille)
sources muettes              49
offres actives            5 939
candidatures envoyées         1
```

Le mouvement est réel : 29 sources de plus produisent effectivement des offres.
Les connecteurs GSK, Pfizer, Novartis, J&J, IBA, Akkodis, Randstad,
Jefferson Wells et Quality Assistance ne sont plus muets.

### Mais la volumétrie reste concentrée

```
ACTIRIS            4 618        JEFFERSON_WELLS     19
FOREM                480        AKKODIS             19
JOBAT                435        RANDSTAD            11
SMARTRECRUITERS      202        QUALITY_ASSISTANCE   5
TRAVAILLERPOUR       102        GSK / PFIZER / NOVARTIS   1 chacune
```

Les cinq sources historiques font **98,3 %** des offres. Les trente nouvelles
en totalisent **99**.

---

## 2. Le chiffre qui change la lecture

Le volume est trompeur. La bonne mesure est la **densité en offres
pertinentes** :

```
sources historiques    5 840 offres    955 pertinentes    16,4 %
nouvelles sources         99 offres     55 pertinentes    55,6 %
```

**Les sources employeurs directes sont 3,4 fois plus denses.**

Jefferson Wells à lui seul apporte une série d'intitulés directement dans la
cible :

```
Laboratory Technician        QC Specialist         Lab Analyst
Technicien de laboratoire    QC Engineer (micro)   QC Equipment Specialist
ELN Business Analyst         technicien QC 2 shifts
```

À comparer au pool final actuel, qui compte 61 offres. Ces 55 offres denses ne
sont pas un détail.

**Conclusion : la stratégie des sources directes fonctionne.** Ce n'est pas le
principe qu'il faut corriger, c'est le tri entre celles qui rapportent et les
49 qui ne rapportent rien.

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

---

## 3. Ce qui a été corrigé ici, avec la preuve

### La géographie : deux familles de faux positifs

Le module de détection belge acceptait comme belges des localisations qui ne
le sont pas. Testé avant correction : **11 cas justes sur 20**.

```
Hoboken, NJ 07030      → belge     (New Jersey)
Charleroi, PA          → belge     (Pennsylvanie)
Ghent, KY              → belge     (Kentucky)
Waterloo, ON           → belge     (Ontario)
Antwerp, NY            → belge     (New York)
Suite 1200, Boston     → belge     (« 1200 » lu comme code postal)
Room 4500, Basel       → belge     (Bâle — siège de Roche et Novartis)
Poste ouvert en 2026   → belge     (un millésime)
```

Neuf villes belges ont un homonyme étranger : Hoboken, Waterloo, Antwerp,
Brussels, Ghent, Charleroi, Bruges, Mons, Hasselt. Quand l'ATS écrit le pays en
toutes lettres, le filtre tient. Quand il écrit `Hoboken, NJ` — le format le
plus courant — la ville belge l'emporte.

**Deux corrections appliquées :**

1. Les subdivisions étrangères (États américains, provinces canadiennes, codes
   pays) sont reconnues. Les codes à deux lettres n'entrent en jeu qu'après une
   virgule et en capitales, sinon `ON`, `IN`, `OR`, `DE`, `LA`, `MA` et `OK`
   matcheraient des mots ordinaires. `BE` et `LU` sont exclus de la liste :
   l'un est la Belgique, l'autre la province de Luxembourg.

2. Un code postal seul ne conclut plus. Tout nombre à quatre chiffres lui
   ressemble.

**Résultat : 26 cas justes sur 26**, et l'audit du module passe de 51 à
**70 tests**, tous verts.

#### La non-régression, mesurée sur les données réelles

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

Le durcissement du code postal semblait risqué : 2 437 offres ont un code postal
sans ville reconnue. Vérification faite, toutes portent « Belgique » et sont
confirmées par le nom du pays. Seules 4 offres reposaient sur le code postal
seul — et aucune n'était belge.

### L'instrument qui manquait

Ajout de `diagnostics/source_yield_audit.py` : il croise le registre des sources
avec le contenu réel de la base et signale toute source active n'ayant jamais
rien produit.

```bash
python -m diagnostics.source_yield_audit
```

Il est en lecture seule et intégré à `run_all` (**35/35**).

Son premier verdict porte sur le travail fait ici : les cinq connecteurs ATS
construits dans ce dossier — Recruitee, Greenhouse, Workday, SuccessFactors,
Phenom — **n'ont jamais produit une seule offre**. C'est exactement le reproche
adressé ailleurs. L'instrument vaut d'abord contre soi.

---

## 4. Axes d'amélioration

### Axe 1 — Trier les 49 sources muettes, ne pas les corriger en bloc

**Constat.** 49 sources actives ne produisent rien. Corriger 49 connecteurs est
un chantier ; savoir lesquels méritent l'effort est une mesure.

**Ce qu'il faut faire.** Instrumenter les collecteurs avec des compteurs de
motifs, pour que le diagnostic de rendement puisse répondre *pourquoi* :

```
SEEN  TARGET_TITLE  DETAIL_OK  DETAIL_FAILED
BELGIUM_ACCEPTED  GEOGRAPHY_REJECTED  GEOGRAPHY_UNKNOWN
LANGUAGE_REJECTED  NON_TARGET  CONVERTED  PERSISTED  ERROR
```

Une source qui voit 0 annonce a un problème réseau. Une source qui en voit 200
et n'en garde aucune a un problème de filtre. Ce sont deux chantiers différents,
et rien aujourd'hui ne permet de les distinguer.

**Règle** : aucun `continue` correspondant à une exclusion importante ne doit
rester sans compteur.

### Axe 2 — Le risque a changé de sens

**Constat.** Tant que les connecteurs employeurs ne produisaient rien, un défaut
géographique ne coûtait que des offres perdues — invisible mais sans dommage.
Maintenant qu'ils produisent, un faux positif va jusqu'au CV.

Les tenants Workday pharma publient massivement depuis les États-Unis, le Japon,
Singapour, l'Inde et le Brésil. `Hoboken, NJ` est le format standard pour le
New Jersey, cœur de l'implantation américaine de Johnson & Johnson.

**Ce qu'il faut faire.** Faire passer les dix connecteurs employeurs par une
détection géographique unique, et vérifier qu'elle traite les subdivisions et
les faux codes postaux. Le jeu de cas de la section 3 sert de contrôle.

### Axe 3 — Ne pas confondre « source valide » et « source rentable »

**Constat.** GSK, Pfizer et Novartis produisent **une offre chacune**. Ces
connecteurs sont probablement corrects : ces employeurs n'ont simplement pas
beaucoup de postes belges ouverts dans la cible à un instant donné.

C'est une distinction que le projet énonce déjà (« une source fiable avec zéro
cible actuelle peut être valide ») mais que rien ne mesure.

**Ce qu'il faut faire.** Suivre le rendement dans le temps, pas à un instant.
Une source à 1 offre sur trois mois n'est pas une source à 1 offre aujourd'hui.
Le seuil « marginal » du diagnostic de rendement est un premier signal ; il
demande un historique pour devenir une décision.

### Axe 4 — 84 % des offres ne sont toujours pas enrichies

**Constat.** Inchangé et toujours mesurable :

```
5 810 offres actives, 4 895 avec une description < 300 caractères  (84,3 %)
dont 336 avec un intitulé métier pertinent
```

Le pré-score décide de l'enrichissement sur ces 164 caractères. Douze offres
écartées de ce type, enrichies puis re-scorées : **six passent de 0 à ≥ 50**.

**Ce qu'il faut faire.** Une seconde porte d'entrée : un intitulé métier suffit
quand la description est trop maigre. Deux garde-fous — ne l'appliquer qu'aux
descriptions effectivement courtes, et tester les termes avec frontières
lexicales, faute de quoi « Élaboration » matchera *labo* et « Qatar » matchera
*QA*.

Ordre de grandeur : **150 offres récupérables**, contre 61 dans le pool actuel.

### Axe 5 — Les exigences de néerlandais

**Constat.** Le niveau réel est **A2**. Le Gate ne déduit une exigence que d'un
niveau CECR explicite ou d'un mot de fluidité. Ces formulations passent au
travers :

```
"Je hebt een goede kennis Nederlands"    "maîtrise du néerlandais exigée"
"tweetalig NL/FR vereist"                "bilingue FR/NL indispensable"
```

Sur un run de 575 offres, six mal classées, dont une à **98,8 en READY_APPLY**
exigeant le néerlandais.

**Ce qu'il faut faire.** Étendre l'inférence, avec trois précautions : ne
l'appliquer qu'aux langues non maîtrisées (A1/A2), respecter les formulations
optionnelles (« est un atout »), et traiter « bilingue » et « tweetalig » comme
une exigence de néerlandais. Tester la non-régression sur FR et EN.

### Axe 6 — Les audits épinglent des valeurs qui bougent

**Constat.** 22 occurrences du type `_VERSION == "1.2"`, plus des résultats de
run figés. Trois cas observés : trois audits au rouge après une montée de
version, le préflight bloquant tout le Daily Run, et un audit devenu faux en
moins d'une heure.

**Ce qu'il faut faire.** Comparer des structures, pas des chaînes.

```python
def at_least(courant, minimum):
    a = tuple(int(x) for x in courant.split("."))
    b = tuple(int(x) for x in minimum.split("."))
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) >= b + (0,) * (n - len(b))
```

Piège intermédiaire : `startswith("1.0")` casse dès `1.1.0` et accepte `1.05`.

Un audit ne doit épingler que ce qui ne doit jamais changer.

### Axe 7 — Le volume de fichiers

**Constat.** 41 README, 30 `.bat`, 47 scripts à la racine, et la production du
jour ajoute un README et un `.bat` par étape. Sept README pour le seul
Sciensano, qui est par ailleurs désactivé.

**Ce qu'il faut faire.** Un fichier de documentation par composant, avec un
historique interne, plutôt qu'un fichier par version. Vérifier les dépendances
avant toute suppression :

```bash
grep -rl "nom_du_module" --include=*.py . | grep -v __pycache__
```

### Axe 8 — Une candidature envoyée

**Constat.**

```
77 candidatures suivies    71 SHORTLISTED    43 READY    1 APPLIED
```

43 dossiers prêts, un seul parti.

**Pourquoi c'est le point le plus important.** Aucune donnée réelle ne valide le
Matcher. Personne ne sait si une offre à 139/100 obtient plus de réponses qu'une
à 90. Tous les seuils reposent sur des valeurs devinées.

C'est aussi ce qui rend les autres axes difficiles à hiérarchiser : sans retour
réel, on optimise à l'aveugle.

**Ce qu'il faut faire.** Envoyer trois candidatures parmi les 43 prêtes et
enregistrer leur statut. À 15–20 candidatures suivies, des questions
aujourd'hui sans réponse deviennent mesurables : quel track répond, quel score
corrèle avec un retour, quelle source convertit.

---

## 5. Synthèse

| # | Axe | Gravité | Preuve |
|---|---|---|---|
| 1 | 49 sources muettes à trier | **majeur** | 84 actives, 35 produisent |
| 2 | Faux positifs géographiques | **majeur** | corrigé ici : 11/20 → 26/26, 0 offre perdue |
| 3 | Rendement à suivre dans le temps | moyen | GSK, Pfizer, Novartis à 1 offre |
| 4 | 84 % des offres non enrichies | **majeur** | 4 895/5 810 ; 6 sur 12 passent de 0 à ≥50 |
| 5 | Exigences de néerlandais | **majeur** | offre à 98,8 en READY_APPLY |
| 6 | Audits épinglant des versions | moyen | 22 occurrences ; préflight bloqué |
| 7 | Volume de fichiers | moyen | 41 README, 30 .bat, 47 scripts |
| 8 | 1 candidature envoyée | **majeur** | 43 prêtes, 1 partie |

### Ordre recommandé

**D'abord ce qui décide.** Axe 1 — instrumenter les collecteurs. Sans cela, les
49 sources muettes se corrigent à l'aveugle, et le succès de Jefferson Wells
(55,6 % de densité) ne se distingue pas de l'échec des autres.

**Ensuite ce qui rapporte.** Axe 4 (seconde porte d'enrichissement, ~150 offres)
et axe 5 (néerlandais). Ces deux-là gagnent des offres sans ajouter une source.

**En parallèle et sans attendre.** Axe 8. Trois candidatures apporteront plus
d'information sur la qualité réelle du pipeline que n'importe quel autre axe.

---

## 6. Trois principes de méthode

**Un rejet silencieux est une perte invisible.** Le filtre géographique jetait
des offres sans compteur, alors que le filtre linguistique juste en dessous les
comptait. Toute exclusion doit laisser une trace chiffrée.

**Un diagnostic vert ne prouve pas un impact.** Une suite entièrement au vert
coexistait avec 49 sources muettes et 150 offres pertinentes écartées. Les
audits vérifient qu'un composant fait ce qu'il annonce ; le diagnostic de
rendement vérifie qu'il rapporte quelque chose. Les deux sont nécessaires.

**Compiler n'est pas tester.** `py_compile` valide la syntaxe. Les deux familles
de faux positifs corrigées ici étaient dans du code qui compilait parfaitement :
`Room 4500, Basel` passait pour belge. Un fichier de cas attendus les montre en
une seconde.
