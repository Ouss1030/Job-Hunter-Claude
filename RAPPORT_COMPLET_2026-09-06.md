# Job Hunter Belgium — rapport complet

**6 septembre 2026.** Analyse en lecture seule du projet.
**Aucun fichier n'a été modifié.**

Ce document contient tout : l'état mesuré, ce qui va bien, ce qui ne va pas,
l'inventaire de ce qui est essentiel et de ce qui peut partir, et **deux prompts
prêts à copier** en fin de document — un pour le nettoyage, un pour les
améliorations.

---

## Sommaire

- [1. L'urgence : la suite de diagnostics est bloquée](#1-lurgence--la-suite-de-diagnostics-est-bloquée)
- [2. Ce qui va bien](#2-ce-qui-va-bien)
- [3. Ce qui ne va pas](#3-ce-qui-ne-va-pas)
- [4. Inventaire : essentiel et supprimable](#4-inventaire--essentiel-et-supprimable)
- [5. PROMPT DE NETTOYAGE](#5-prompt-de-nettoyage)
- [6. PROMPT D'AMÉLIORATION](#6-prompt-damélioration)

---

# 1. L'urgence : la suite de diagnostics est bloquée

C'est le constat le plus important du rapport, et il n'était pas visible jusqu'ici.

`diagnostics/run_all.py` impose une garde avant de lancer le moindre test :

```python
def discovered_modules():
    return {path.stem for path in DIAG_DIR.glob("*.py")
            if path.name != "__init__.py"}

def classification_status():
    ...
    return {"ok": not missing_on_disk and not unclassified, ...}
```

**Chaque fichier `.py` présent dans `diagnostics/` doit être classé** dans l'une
des sept catégories (`SUITE_ACTIVE`, `REPLACED`, `NETWORK`, `REPORTS`,
`REPLAYS`, `HISTORICAL`, `TOOLS`). Sinon :

```python
if not classification["ok"]:
    print("[FAIL] Classification incomplète. Aucun diagnostic n'a été lancé.")
```

### L'état réel, obtenu en appelant leur propre fonction

```
sur disque      : 342
classés         :  65
NON classés     : 277
classés absents :   0
suite lançable  : False        ←
```

**Aucun des 342 diagnostics ne peut être lancé aujourd'hui.** Pas un seul.

### Pourquoi c'est arrivé

La garde est saine — elle force à ranger. Mais chaque script d'intégration à
usage unique déposé dans `diagnostics/` la fait échouer un peu plus. Le dossier
est passé de 213 à 342 fichiers en cinq jours, et les nouveaux ne sont pas
classés.

Résultat : le mécanisme censé garantir la qualité est désactivé par le volume,
au moment précis où le projet change le plus vite.

### Ce qui rend le constat décisif

**Le nettoyage n'est plus une question d'esthétique : c'est ce qui remet la
suite en marche.** Supprimer ou classer les 277 fichiers non classés est la
seule façon de récupérer les tests.

---

# 2. Ce qui va bien

Le travail des derniers jours a produit des résultats réels, mesurés.

## 2.1 Les candidatures ont décollé

```
              4 sept.    6 sept.
APPLIED           1        12
READY            43       119
SHORTLISTED      71       156
REJECTED          0         1
```

C'est le point que je signalais comme le plus important. **Douze candidatures
envoyées et un premier retour.** Le pipeline commence à produire de
l'information réelle plutôt que des scores devinés.

## 2.2 Les sources muettes reculent

```
              4 sept.    6 sept.
déclarées        84        84
produisant       36        44
muettes          48        40
offres        5 917     6 222
```

Huit sources de plus rapportent effectivement des offres.

## 2.3 La densité des sources directes se confirme

```
sources historiques   6 035 offres   1 021 pertinentes   16,9 %
sources directes        187 offres      95 pertinentes   50,8 %
```

**Trois fois plus denses.** La mesure tient sur un échantillon deux fois plus
grand qu'il y a deux jours. La stratégie des employeurs directs est validée.

## 2.4 Le problème d'enrichissement s'améliore

```
descriptions < 300 caractères :  78,8 %   (84,3 % il y a deux jours)
```

## 2.5 La base a été élaguée

```
canonical_jobs :  14 builds / 83 800 lignes   (34 builds / 174 468 avant)
backups        :   3 copies                   (9 avant)
```

L'outil `database/backup_retention.py` fonctionne et tourne.

## 2.6 Le garde néerlandais est correct

Testé sur les neuf cas qui comptent : **9/9**. Les formulations bloquantes
(`goede kennis Nederlands`, `tweetalig NL/FR vereist`, `maîtrise du néerlandais
exigée`) sont détectées, et les formulations optionnelles (`is een pluspunt`,
`est un atout`) comme les alternatives (`Frans of Nederlands`) ne bloquent pas.
La non-régression sur l'anglais tient.

## 2.7 Un système de rotation de mots-clés a été construit

```
UNIFIED MASTER TERMS | mode=CORE80+ROTATION80 | active=160 | master=400
```

400 termes maîtres, 160 actifs par run avec rotation. C'est une bonne réponse au
plafond de résultats par mot-clé.

---

# 3. Ce qui ne va pas

## 3.1 Le défaut géographique est toujours là — et il fuit maintenant

Le classifieur `sources/belgium_locations.py` v1.1 est inchangé : **3 réponses
justes sur 13**.

```
Hoboken, NJ 07030    → BELGIUM   (New Jersey)
Charleroi, PA        → BELGIUM   (Pennsylvanie)
Ghent, KY            → BELGIUM   (Kentucky)
Waterloo, ON         → BELGIUM   (Ontario)
Antwerp, NY          → BELGIUM   (New York)
Room 4500, Basel     → BELGIUM   (Bâle)
Building 2000        → BELGIUM
Suite 1200, Boston   → BELGIUM
Poste ouvert en 2026 → BELGIUM   (un millésime)
```

Le côté belge reste correct — `Wavre`, `Lessines, Wallonia`, `1000 Bruxelles`
passent. C'est le côté étranger qui cède.

### Ce n'est plus théorique

Recherche dans la base des localisations manifestement étrangères :

```
offres actives                        6 222
localisation manifestement étrangère      3

FOREM    Québec, Canada, Centre du Canada    A7 Intégration - Technicien
FOREM    Québec, Canada, Centre du Canada    Cabico - Responsable assurance
GSK      UK – London – New Oxford Street     SPQS Data Steward
```

Trois seulement, donc le volume reste faible. Mais **une offre GSK à Londres est
entrée en base**, et le nombre de connecteurs employeurs productifs augmente.
Le défaut ne se manifestait pas ; il commence à se manifester.

### Le rejet géographique n'est toujours pas compté

Dans `sources/gsk.py`, inchangé :

```python
if location and not _is_belgium_location(location):
    continue                     # aucun compteur, aucune trace

if language == "nl":
    rejected_nl += 1             # compté
    print(...)                   # journalisé
```

Le rejet linguistique est mesuré, le rejet géographique ne l'est pas. Impossible
de savoir combien d'offres belges sont perdues, ni combien d'étrangères passent.

## 3.2 La prolifération s'accélère

```
                4 sept.   6 sept.
diagnostics/      316       342
racine .bat       227       252
racine .md        197       197
racine .py         94        94
modules Python    572       604
```

En deux jours : **26 diagnostics et 25 fichiers `.bat` de plus**. C'est
exactement ce qui a bloqué la suite (§1).

## 3.3 Le disque

```
database/jobs.db   1 376 Mo
backups/           3,68 Go   (3 copies, 122 sous-dossiers, 325 fichiers)
```

La base a grossi de 1 079 à 1 376 Mo en deux jours malgré l'élagage. Les
14 builds restants de `canonical_jobs` représentent encore 83 800 lignes pour
6 222 offres actives.

## 3.4 Jobat : la décision n'est toujours pas prise

Le repli sur navigateur Playwright après 403/429/503 est inchangé, et le code
imprime toujours « page anti-bot détectée », alors que la documentation du
projet l'interdit. Ce n'est pas un défaut technique — c'est une décision qui
n'est ni prise ni écrite.

---

# 4. Inventaire : essentiel et supprimable

## 4.1 Méthode

Un fichier est **essentiel** s'il est atteignable depuis `main.py`,
`daily_run.py`, `jobhunter_ui.py` ou depuis les 25 audits de `SUITE_ACTIVE`.

**Piège évité.** `daily_run.py` lance ses étapes en **sous-processus** :

```python
subprocess.Popen([... "-m", "applications.application_preparation" ...])
```

Ce ne sont pas des `import`. Une analyse d'imports seule conclurait que
`applications/application_preparation.py` est mort — c'est le cœur du pipeline.
L'analyse a donc été étendue aux chaînes de caractères désignant un module.

**Résultat : 154 modules essentiels sur 604.**

## 4.2 À GARDER

```
racine/
    main.py    daily_run.py    jobhunter_ui.py

applications/     TOUT — lancé en sous-processus
config/           profile, candidate_truth, versioning, sources actives
database/         db, models, canonical, enriched_batch, backup_retention
matching/         application_gate, application_gate_v13, application_queue,
                  basic_matcher, matcher_vnext_overlay
interface/        TOUT — utilisé par l'UI Streamlit
sources/          registry, belgium_locations, source_metrics + connecteurs actifs

diagnostics/      run_all.py + les 65 modules CLASSÉS dans ses 7 catégories
```

### Les données — jamais supprimées

```
database/jobs.db    1 376 Mo   16 491 lignes, 167 candidatures suivies
                               PAS dans git (.gitignore) — irremplaçable
logs/                          caches Actiris — reconstructibles mais coûteux
exports/logs/                  seul historique de mesure
backups/                       3 copies, gérées par backup_retention.py
```

### Les lanceurs

```
START_JOBHUNTER.bat     RESUME_DAILY_RUN.bat     TEST_DAILY_RUN.bat
```

## 4.3 À SUPPRIMER

| # | Catégorie | Fichiers | Certitude |
|---|---|---|---|
| 1 | Dossiers de transit / payload (12 dossiers) | ~120 | **totale** |
| 2 | Diagnostics NON classés | **277** | **élevée — débloque la suite** |
| 3 | Migrations racine `upgrade_/install_/apply_/rollback_` | 70 | élevée |
| 4 | Candidats `daily_run_v1*_candidate.py` | 5 | élevée |
| 5 | Scripts d'étape racine `lifecycle_step8*` etc. | 16 | élevée |
| 6 | Fichiers `.bat` hors les 3 lanceurs | 249 | élevée |
| 7 | README portant un numéro de version | ~97 | élevée |
| 8 | Doublons versionnés dans `applications/` | ~7 | **à vérifier un par un** |

**Total : environ 840 fichiers.**

## 4.4 Le piège à ne pas répéter

**Ne jamais supprimer un diagnostic CLASSÉ**, même ceux listés dans `REPLACED`.

Testé en conditions réelles sur le dossier de travail : retirer les 13 audits
déclarés `REPLACED` a cassé la suite instantanément —

```
[FAIL] Classification incomplète. Aucun diagnostic n'a été lancé.
```

`run_all` vérifie aussi que chaque nom **classé** existe sur disque
(`missing_on_disk`). La déclaration « remplacé » crée donc une dépendance : le
fichier est obsolète pour l'exécution, mais requis par l'inventaire.

**La règle :** supprimer uniquement les **non classés**, ou bien supprimer un
classé **et** retirer son entrée du dictionnaire dans le même geste.

---

# 5. PROMPT DE NETTOYAGE

À copier tel quel.

```
CONTEXTE — URGENT

La suite de diagnostics du projet JobHunter est actuellement BLOQUÉE. Vérifié
en appelant votre propre fonction :

    from diagnostics.run_all import classification_status
    s = classification_status()
    # sur disque : 342   classés : 65   NON classés : 277   ok : False

run_all.py impose que CHAQUE fichier .py de diagnostics/ soit classé dans l'une
des sept catégories (SUITE_ACTIVE, REPLACED, NETWORK, REPORTS, REPLAYS,
HISTORICAL, TOOLS). 277 ne le sont pas, donc :

    [FAIL] Classification incomplète. Aucun diagnostic n'a été lancé.

Aucun test ne tourne. Le nettoyage n'est donc pas cosmétique : c'est ce qui
remet les tests en marche.

OBJECTIF

Écris un script Python unique, database/cleanup_workspace.py, qui met en
quarantaine les fichiers inutiles par lots, de façon entièrement réversible, et
qui restaure la capacité de run_all à s'exécuter.


CONTRAINTE DE SÉCURITÉ 1 — LE PIÈGE DES SOUS-PROCESSUS

N'écris PAS un script qui décide par analyse d'imports seule.

daily_run.py lance ses étapes ainsi :

    subprocess.Popen([... "-m", "applications.application_preparation" ...])

Ce ne sont pas des `import`. Une analyse d'imports conclurait que
applications/application_preparation.py est mort. C'est le cœur du pipeline.

Cherche les références sous TROIS formes :
    1. imports (ast)
    2. chaînes de caractères "applications.xxx", "diagnostics.yyy", y compris
       avec un suffixe ":VERSION"
    3. mentions dans les fichiers .bat

Un fichier n'est candidat que s'il n'apparaît sous AUCUNE des trois.


CONTRAINTE DE SÉCURITÉ 2 — NE JAMAIS TOUCHER UN DIAGNOSTIC CLASSÉ

Vérifié en conditions réelles : retirer des diagnostics classés REPLACED casse
run_all immédiatement, car il contrôle aussi que chaque nom classé existe sur
disque (missing_on_disk).

Donc :
    - les 65 modules classés dans les 7 catégories → INTOUCHABLES
    - les 277 NON classés → candidats
    - si tu veux supprimer un classé, retire son entrée de la catégorie DANS LE
      MÊME GESTE, puis relance run_all pour confirmer.


CONTRAINTE DE SÉCURITÉ 3 — LISTE PROTÉGÉE EN DUR, TESTÉE EN PREMIER

Dossiers   : applications/ interface/ matching/ database/ config/ sources/
             logs/ exports/ backups/ .git/ .venv/
Fichiers   : main.py daily_run.py jobhunter_ui.py
             START_JOBHUNTER.bat RESUME_DAILY_RUN.bat TEST_DAILY_RUN.bat
             README.md .gitignore requirements*.txt
Diagnostics: run_all.py + les 65 noms classés, lus DYNAMIQUEMENT depuis
             run_all.py (ne pas les recopier en dur) + tout module importé par
             l'un d'eux
Données    : database/jobs.db (pas dans git, irremplaçable)
             logs/ et exports/logs/


MÉCANISME — QUARANTAINE, PAS SUPPRESSION

Déplace vers un dossier daté en conservant l'arborescence :

    _quarantaine_20260906_HHMMSS/
        diagnostics/install_streamlit_v2_3.py
        upgrade_v39_batch2_4_registry.py
        MANIFESTE.json      ← chemin d'origine de chaque fichier

Trois modes :
    python database/cleanup_workspace.py --lot N --dry-run    (défaut)
    python database/cleanup_workspace.py --lot N --apply
    python database/cleanup_workspace.py --restaurer _quarantaine_20260906_HHMMSS


LES LOTS

LOT 1 — dossiers de transit (~120 fichiers), certitude totale
    _payload/  payload/  _patch_payload/  _step9_1_payload/
    _jobat_circuit_v1_payload/  _jobat_cookie_once_v1_payload/
    hardening_files/  hardening_step2_files/  hardening_step4b_files/
    hardening_step6b_files/  hardening_step7_files/  lifecycle_step8f_b_files/

LOT 2 — LE LOT QUI DÉBLOQUE LA SUITE : les 277 diagnostics NON classés
    Obtiens-les dynamiquement :
        classification_status()["unclassified"]
    Ce sont très majoritairement des scripts d'intégration à usage unique
    (mega_batch*, batch*_integrate*, run_batch*, install_*, upgrade_*,
    validate_*, rollback_*) rangés dans le mauvais dossier.

    Après ce lot, run_all doit redevenir exécutable. C'est le critère de succès.

    Si certains méritent d'être gardés (tests live utiles), ne les déplace pas :
    ajoute-les à la catégorie TOOLS ou HISTORICAL de run_all. Garder OU classer,
    mais ne pas laisser non classé.

LOT 3 — migrations racine (75 fichiers)
    upgrade_*.py install_*.py apply_*.py rollback_*.py patch_*.py
    daily_run_v1*_candidate.py
    Déplace aussi le .bat et le README du même nom de base : ils forment un lot.

LOT 4 — scripts d'étape racine (16 fichiers)
    lifecycle_step8*.py  main_smartrecruiters_shadow*.py
    diagnose_jobat_prov.py  export_full_performance_audit_v1.py
    Resume_pour_gemini.py  _wdd.py
    ATTENTION : lifecycle.py est UTILISÉ par daily_run.py — ne pas y toucher.

LOT 5 — fichiers .bat (249 sur 252)
    Tous sauf les trois lanceurs protégés.

LOT 6 — README versionnés (~97 sur 197)
    Motif README_*_V<numéro>.md quand une version supérieure du même composant
    existe. Garde toujours la plus récente de chaque famille.
    Exemple : README_SCIENSANO_V350/351/352/353/3531/354 → garder V354.

LOT 7 — doublons versionnés dans applications/ — UN PAR UN
    Vérifie que le fichier de base porte déjà une version >= celle du doublon
    AVANT de déplacer. Ne déplace pas si la vérification échoue.


PROTOCOLE

    0. git add -A && git commit -m "Etat avant nettoyage"
       (le dépôt a 4 commits et des milliers de fichiers non commités :
        sans ce commit, rien n'est réversible par git)

    1. --lot 1 --dry-run  puis  --apply
    2. python daily_run.py --check              doit rester vert
    3. lot suivant
    4. après le LOT 2 : python -m diagnostics.run_all   DOIT ENFIN SE LANCER

Si une vérification échoue : restaurer le dernier lot et s'arrêter.


LIVRAISON ATTENDUE

    1. database/cleanup_workspace.py
    2. diagnostics/cleanup_workspace_audit.py — sur fichiers factices en dossier
       temporaire, il doit vérifier :
         - qu'un fichier protégé n'est jamais candidat
         - qu'un module référencé UNIQUEMENT par une chaîne "applications.xxx"
           n'est PAS candidat   ← le test le plus important
         - qu'un module cité seulement dans un .bat n'est PAS candidat
         - qu'un diagnostic CLASSÉ n'est jamais candidat
         - que la restauration remet chaque fichier à son chemin d'origine
       N'oublie pas de classer ce nouvel audit dans run_all, sinon tu recrées
       le problème que tu viens de résoudre.
    3. Le dry-run complet des 7 lots, sans rien appliquer.

Ne lance aucun --apply toi-même. Je veux voir le dry-run d'abord.


RÈGLE GÉNÉRALE

Compiler n'est pas tester. Un script de suppression qui compile parfaitement
peut effacer le cœur du pipeline. Le garde-fou qui compte est l'audit du
point 2.
```

---

# 6. PROMPT D'AMÉLIORATION

À copier tel quel, **après** le nettoyage.

```
CONTEXTE

Le pipeline JobHunter progresse : 44 sources produisent (contre 36 il y a deux
jours), 6 222 offres actives, et surtout 12 candidatures envoyées contre 1.
Les sources employeurs directes sont 3 fois plus denses en offres pertinentes
que les sources généralistes (50,8 % contre 16,9 %).

Trois défauts mesurés freinent cette progression. Ils sont classés par gravité.


AMÉLIORATION 1 — LA GÉOGRAPHIE LAISSE PASSER DES OFFRES ÉTRANGÈRES

sources/belgium_locations.py v1.1 donne 3 réponses justes sur 13 :

    Hoboken, NJ 07030    -> BELGIUM   (New Jersey)
    Charleroi, PA        -> BELGIUM   (Pennsylvanie)
    Ghent, KY            -> BELGIUM   (Kentucky)
    Waterloo, ON         -> BELGIUM   (Ontario)
    Antwerp, NY          -> BELGIUM   (New York)
    Boston, MA           -> UNKNOWN
    Room 4500, Basel     -> BELGIUM   (Bâle)
    Building 2000        -> BELGIUM
    Suite 1200, Boston   -> BELGIUM
    Poste ouvert en 2026 -> BELGIUM   (un millésime)

Le côté belge est correct (Wavre, Lessines Wallonia, 1000 Bruxelles passent).
C'est le côté étranger qui cède.

CE N'EST PLUS THÉORIQUE. Trois offres étrangères sont déjà en base, dont :

    GSK   "UK – London – New Oxford Street"   SPQS Data Steward

Deux correctifs :

1. Reconnaître les subdivisions étrangères AVANT la reconnaissance de ville :
   noms d'États américains et de provinces canadiennes en toutes lettres, plus
   les codes à deux lettres — mais UNIQUEMENT après une virgule et en
   capitales, sinon ON, IN, OR, DE, LA, MA, ME et OK matchent des mots
   ordinaires. Exclure BE (la Belgique) et LU (province de Luxembourg).

2. Un code postal seul ne conclut plus. Tout nombre à quatre chiffres lui
   ressemble. Le garder comme donnée (il fournit la province), pas comme
   décision.

Ce durcissement a été testé sur 5 430 localisations réelles d'un jeu de données
équivalent : il ne dégrade AUCUNE offre belge. Les offres à code postal sans
ville portent toutes « Belgique » et passent par le nom du pays. Les seules
reclassées étaient « 9999, PL » et « 9999, FR », donc étrangères.

Objectif : 26/26 sur le jeu de cas donné en fin de prompt. Fige-le dans un
audit, et CLASSE cet audit dans run_all.


AMÉLIORATION 2 — LE REJET GÉOGRAPHIQUE EST INVISIBLE

Dans sources/gsk.py, deux rejets consécutifs sont traités différemment :

    if location and not _is_belgium_location(location):
        continue                  # aucun compteur, aucune trace

    if language == "nl":
        rejected_nl += 1          # compté
        print(...)                # journalisé

publish_metrics_from_locals() publie les variables locales : il ne peut donc
rapporter que les compteurs que quelqu'un a pensé à créer. Aucun n'existe pour
la géographie. Le module est « instrumenté » et pourtant aveugle sur ce rejet.

Conséquence directe : impossible de savoir combien d'offres belges sont perdues,
ni combien d'étrangères passent. C'est aussi ce qui empêche de diagnostiquer les
40 sources encore muettes.

Correctif — un contrat de compteurs obligatoires, initialisés à zéro :

    COMPTEURS = ("seen", "target_title", "non_target",
                 "detail_ok", "detail_failed",
                 "geography_accepted", "geography_rejected", "geography_unknown",
                 "language_rejected", "converted", "persisted", "errors")

avec un avertissement au moment de publier si l'un manque.

Et utiliser les trois états au lieu de les écraser en booléen :

    decision = classify_belgium_location(location, trusted_belgium_listing=trust)
    if decision.status == FOREIGN:
        compteurs["geography_rejected"] += 1; continue
    if decision.status == UNKNOWN:
        compteurs["geography_unknown"] += 1; continue
    compteurs["geography_accepted"] += 1

Applique-le d'abord aux connecteurs déjà migrés : gsk, jnj, pfizer, lonza, roche.

Résultat attendu : pour chacune des 40 sources muettes, pouvoir dire si elle
échoue en réseau, si elle filtre trop, ou si elle n'a aucune cible. Ne corrige
ensuite QUE celles dont les compteurs montrent un vrai défaut — une source
fiable sans cible actuelle est valide.


AMÉLIORATION 3 — 78,8 % DES OFFRES NE SONT JAMAIS ENRICHIES

4 902 offres actives sur 6 222 ont une description de moins de 300 caractères.
C'est en progrès (84,3 % il y a deux jours), mais le mécanisme de fond demeure :

    def select_candidate_jobs(pre_scored_jobs):
        return [(job, result) for job, result in pre_scored_jobs
                if result["core_relevance"]]

core_relevance est calculé AVANT l'enrichissement, donc sur ~160 caractères de
métadonnées. Une offre mal décrite n'obtient jamais sa description, donc ne peut
jamais être scorée correctement, donc reste écartée. Le pré-score décide sur une
information qu'il a lui-même refusé d'aller chercher.

Mesuré : sur douze offres écartées de ce type puis enrichies manuellement, SIX
passent d'un score nul à un score exploitable (50 à 64).

Correctif — une seconde porte d'entrée : un intitulé métier suffit quand la
description est trop maigre. Deux garde-fous indispensables :
  - ne l'appliquer QU'AUX descriptions effectivement courtes, sinon on contourne
    une décision légitime du pré-score ;
  - tester les termes avec frontières lexicales, sinon « Élaboration » matchera
    "labo" et « Qatar » matchera "QA".


AMÉLIORATION 4 — TRANCHER SUR JOBAT

sources/jobat.py bascule toujours sur un navigateur Edge/Playwright après
403/429/503, et imprime lui-même « page anti-bot détectée », alors que la
documentation du projet l'interdit explicitement.

Ce n'est pas un défaut technique, c'est une décision non prise. Tranche
explicitement et écris-la : soit la règle du projet change en connaissance de
cause, soit le connecteur est retiré. Ne développe aucun mécanisme de
contournement supplémentaire.

À noter au crédit du travail fait : le gestionnaire de consentement clique
« Tout refuser » / « Alles weigeren ». C'est le bon choix.


AMÉLIORATION 5 — ARRÊTER LA PROLIFÉRATION

En deux jours : +26 diagnostics, +25 fichiers .bat. C'est ce qui a bloqué la
suite de tests.

Deux règles à adopter :
  - les scripts d'intégration à usage unique NE VONT PAS dans diagnostics/.
    Crée un dossier migrations/ hors du périmètre de run_all, ou classe-les
    immédiatement dans TOOLS.
  - un fichier de documentation PAR COMPOSANT avec un historique interne, pas
    un README par version.

Sans cela, run_all sera de nouveau bloqué dans une semaine.


DÉFINITION DE « TERMINÉ »

Pour chaque amélioration, livre :
  - le code ;
  - un audit qui fige les cas limites, CLASSÉ dans run_all ;
  - la mesure AVANT / APRÈS sur les données réelles : offres retenues, offres
    belges perdues, offres étrangères écartées, densité du pool final.

py_compile valide la syntaxe, jamais le comportement. Les faux positifs
géographiques ci-dessus sont dans du code qui compile parfaitement.

Si une correction ne change aucune offre sur le dernier run, dis-le et passe à
autre chose.


JEU DE CAS GÉOGRAPHIQUES À FIGER

    # doivent être écartés — homonymes étrangers
    "Hoboken, NJ"        "Hoboken, NJ 07030"     "Hoboken, New Jersey"
    "Charleroi, PA"      "Ghent, KY"             "Waterloo, ON"
    "Antwerp, NY"        "Brussels, Wisconsin"   "Boston, MA"
    "Tokyo, Japan"       "9999, PL"

    # doivent être écartés — faux codes postaux
    "Suite 1200, Boston"    "Building 2000"
    "Room 4500, Basel"      "Poste ouvert en 2026"

    # doivent rester belges — non-régression
    "Wavre"              "Braine-l'Alleud"    "Anderlecht"
    "Lessines, Wallonia" "1000 Bruxelles"     "Brussels, Belgium"
    "Gent, BE"           "3560, Belgique"

    # doivent rester belges — villes homonymes sans qualificatif étranger
    "Hoboken"   "Charleroi"   "Waterloo"   "Gent"   "Bruges"

Les cinq derniers sont les plus importants : le correctif ne doit pas rendre le
classifieur timide au point de perdre les vraies villes belges homonymes.
```

---

# Le principe qui résume le rapport

**Mesurer avant de construire, compter avant de filtrer.**

Le projet a produit 26 diagnostics de plus en deux jours — et aucun ne peut être
lancé, parce que leur nombre a désactivé la garde qui les protège. Dans le même
temps, un défaut géographique signalé il y a cinq jours a laissé entrer sa
première offre étrangère.

Ce ne sont pas deux problèmes distincts. C'est le même : produire plus vite que
l'on ne mesure.

Le nettoyage remet les tests en marche. Les compteurs rendent les 40 sources
muettes diagnosticables. Le reste suit.
