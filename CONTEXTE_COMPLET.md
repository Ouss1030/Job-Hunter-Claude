# Job Hunter Belgium — contexte complet

**État au 22 août 2026.** Ce document résume le projet, ce qui a été fait pendant
les sessions de travail avec Claude, les décisions prises et leurs raisons, et
ce qui reste à faire.

Il est écrit pour être lu par quelqu'un qui reprend le projet à froid — toi dans
trois mois, ou un autre assistant.

---

## 1. Ce qu'est le projet

Un pipeline Python local qui automatise la recherche d'emploi en Belgique pour un
profil précis : **technicien de laboratoire QC pharma**, avec une spécialisation
**Business Data Analysis**.

Il ne postule jamais tout seul. Il collecte, enrichit, score, filtre, priorise, et
prépare des dossiers de candidature qu'un humain valide.

### Le profil ciblé

| | |
|---|---|
| Expérience | ~3 ans pharma / QC (GSK 2022-2023, Prothya 2020-2022) |
| Diplômes | Bachelier Chimie industrielle · Bachelier de spécialisation Business Data Analysis (2026) |
| **Pas** de Master | Master 1 en sciences pharmaceutiques validé — jamais présenter comme un Master obtenu |
| Expérience Data | **0 an professionnel** — compétences issues du diplôme et des projets |
| Langues | Français C2 · Anglais B1 · **Néerlandais A2** (notions, pas de capacité de travail) |
| Compétences | HPLC/UPLC, Endosafe, microbiologie, LIMS, SAP QM/MM, TrackWise, GMP, CAPA, ALCOA+, Python, SQL, Power BI |

### La chaîne

```
11 SOURCES
    ↓
RAW JOBS  (historique jamais supprimé)
    ↓
PRÉ-SÉLECTION  ← deux portes d'entrée depuis le 22/08
    ↓
ENRICHISSEMENT DES DESCRIPTIONS
    ↓
MATCHER V5.1  (score de pertinence métier)
    ↓
CANONICAL V3.1.3  (déduplication conservatrice ; V3.1.3 = même algorithme, description calculée paresseusement, validé 0 écart sur 26 000 paires)
    ↓
APPLICATION GATE  (éligibilité : diplôme, langue, expérience, credentials)
    ↓
APPLICATION QUEUE V1.2  (priorisation, anti-double-candidature)
    ↓
JOB REFRESH V1.2 → APPLICATION RECHECK V1.1  (vérification live)
    ↓
FINAL APPLICATION POOL V1.2
    ↓
CHATGPT HANDOFF  (bundle ZIP à coller dans ChatGPT Plus)
    ↓
LIFECYCLE V1.0  (suivi des candidatures)
```

Le tout s'exécute en une commande : `python daily_run.py`.

---

## 2. Règles absolues du projet

Elles priment sur toute considération technique.

1. **Ne jamais inventer** une compétence, un diplôme, une durée d'expérience.
2. **Aucun Master.** La seule formulation acceptable est « Master 1 en Sciences
   Pharmaceutiques (validé) ».
3. **Zéro année d'expérience Data professionnelle.**
4. **Jamais `APPLIED` sans action explicite de l'utilisateur.**
5. **Les RAW ne sont jamais supprimés**, même pour « nettoyer ».
6. **Déduplication conservatrice** : mieux vaut deux doublons qu'une fusion à tort.
7. **Pas de contournement de protection technique.** Voir §7.
8. **Composants frozen sans défaut prouvé** : Matcher V5.1, Canonical V3.1.3 (V3.1.2 + calcul paresseux, 17/09/2026),
   Database V2.1, et `matching/application_gate.py` V1.2 conservé intact pour
   permettre un rollback.

---

## 3. Les onze sources

| # | Source | Type d'accès | Ce qu'elle apporte |
|---|---|---|---|
| 10 | **Forem** | API open data (ODWB) | Wallonie, recherche ciblée 199 termes |
| 20 | **Actiris** | API | Bruxelles + partenaires — la plus grosse source (4 651 offres) |
| 30 | **Talent.brussels** | API | Région bruxelloise, faible volume |
| 40 | **TravaillerPour** | API | Fonction publique fédérale |
| 50 | **SmartRecruiters** | API publique documentée | SGS, Eurofins, Sopra Steria, Devoteam, Arηs |
| 60 | **Jobat** | ⚠️ voir §7 | — |
| 70 | **Recruitee** | API publique documentée | VITO, NRB, Dataroots, Isabel, Radix, Colruyt |
| 80 | **Greenhouse** | API publique documentée | Collibra, In The Pocket, DataCamp |
| 90 | **Workday** | API du site carrière public | GSK, J&J/Janssen, Abbott, Thermo Fisher, Danaher, Pfizer… |
| 100 | **SuccessFactors** | sitemap + HTML | Umicore, Puratos, Aquafin, Solvay, Syensqo |
| 110 | **Phenom** | sitemap + JSON-LD | UCB, P&G, Proximus |

### Répartition géographique mesurée

Sur 5 430 offres actives, par code postal :

```
Flandre     2 624   48,3 %
Bruxelles   1 721   31,7 %
Wallonie      373    6,9 %
sans code     712   13,1 %
```

**Contre-intuitif mais mesuré** : la Flandre domine, via les flux partenaires
d'Actiris. La Wallonie est sous-représentée parce que Forem interroge par
199 termes ciblés là où Actiris ramène un catalogue complet.

---

## 4. Comment ajouter une source ou un employeur

C'est la partie la plus utile au quotidien.

### Étape 1 — identifier l'ATS

```bash
python -m diagnostics.ats_fingerprint --entreprise nomdomaine.com
```

L'outil ouvre la page carrière, suit les redirections, reconnaît 18 signatures
d'ATS et **extrait l'identifiant exploitable**.

### Étape 2 — selon la réponse

| Réponse | Action |
|---|---|
| WORKDAY, GREENHOUSE, RECRUITEE, SMARTRECRUITERS, SUCCESSFACTORS, PHENOM | Une ligne dans le `config/*_sources.py` correspondant |
| Autre ATS | Un connecteur reste à écrire |
| Non identifié | Ouvrir la page carrière à la main et lire l'URL |

### Autres outils de découverte

```bash
python -m diagnostics.ats_discovery --secteur pharma      # teste des noms contre les API
python -m diagnostics.workday_discovery --tenant ucb      # trouve un tenant Workday
```

**Astuce qui a marché pour J&J** : quand la devinette échoue, lire l'URL de l'ATS
directement dans le HTML de la page carrière. Le tenant de Johnson & Johnson est
`jj`, pas `jnj` — aucune sonde par devinette ne l'aurait trouvé.

### Ce que la recherche d'employeurs a donné

**194 entreprises belges testées.** Résultat brut :

- Les employeurs **pharma et labo belges ne sont majoritairement pas** sur
  Greenhouse, Recruitee ou SmartRecruiters. Sur 54 testées, 4 seulement.
- Ils sont sur **Workday** (GSK, J&J, Abbott, Pfizer), **SuccessFactors**
  (Umicore, Puratos, Solvay) ou **Phenom** (UCB).
- La track **DATA** répond bien mieux aux ATS classiques : NRB, Dataroots,
  Isabel Group, Collibra, DataCamp, Devoteam.

---

## 5. Le Gate — historique des correctifs

Le Gate décide de l'éligibilité. Il est construit en couches, chacune conservant
la précédente intacte pour permettre un rollback.

```
application_gate.py        V1.2    ← jamais modifié
application_gate_v13.py    V1.3.2  ← en production dans main.py
application_gate_v133.py   V1.3.5  ← couche Claude, NON branchée
```

### La famille de bugs qui revient

Le Gate V1.2 possède `phrase_regex()`, avec frontières lexicales, documenté par
*« "fabric" ne doit PAS matcher "fabrication" »*. Il l'utilise 9 fois. **Les
couches V1.3.x ne l'utilisaient jamais** — elles testaient leurs marqueurs en
sous-chaîne brute. C'est la cause commune de :

- le bug **V.I.E** historique : le regex lisait le mot français « vie » et a
  rejeté 58 offres à tort, dont 23 en APPLY/STRETCH ;
- **« pharmA PLUS »** : un Master réellement exigé passait pour optionnel ;
- **« Master Data »** : un métier data lu comme un diplôme Master exigé ;
- **« Evere » vs « Beveren »** dans la Queue, corrigé de son côté en V1.2.

### Correctifs de la couche V1.3.5 (non branchée)

| # | Correctif | Impact mesuré |
|---|---|---|
| 1 | Marqueurs testés avec frontières lexicales (2 sites) | 0 offre aujourd'hui |
| 2 | Ancienneté d'agence (« 20 ans d'expérience et 200 collaborateurs ») | 5 offres |
| 3 | `master data` dans la branche obligation | 0 aujourd'hui, mordra sur la track DATA |
| 4 | `\bVIE\b` majuscule retiré | 0 |
| 5 | Mention V.I.E non auto-référentielle | 1 |
| 6 | **Exigence linguistique sans niveau CECR** | **6 offres reclassées** |
| 7 | **Stages et alternances détectés** | `Stage : Data Analyst` passe de APPLY à VERIFY |

Le correctif 6 est le plus important : le Gate ne détectait une exigence de
langue que si le texte citait un niveau CECR ou un mot de fluidité. Ces
formulations passaient au travers :

```
"Je hebt een goede kennis Nederlands"     → ignoré
"maîtrise du néerlandais exigée"          → ignoré
"tweetalig NL/FR"                         → ignoré
```

Une offre Eurofins à **98,8 de score était en READY_APPLY** alors qu'elle exige
le néerlandais.

**Audit : 42/42**, dont 21/21 de non-régression sur les tests V1.3.2.

> **À décider** : cette couche n'est pas branchée dans `main.py`, qui reste sur
> V1.3.2. Le replay sur 575 offres donnait 0 changement au moment du test — mais
> les correctifs 6 et 7 ont été ajoutés depuis et changent, eux, de vraies
> offres. La brancher demande de remplacer une ligne d'import dans `main.py:75`.

---

## 6. Les trois chantiers du 22 août

### 6.1 Sauvetage de pré-sélection — le plus rentable

**Le problème.** Mesure sur la base :

```
offres actives                     5 430
description < 300 caractères       4 711   (86,8 %)
enrichissement réussi                591   (11 %)
```

`select_candidate_jobs()` décidait qui serait enrichi à partir de
`core_relevance`, calculé **avant** l'enrichissement — donc sur 160 à 280
caractères de métadonnées Actiris sans une ligne d'annonce.

Cercle vicieux : une offre mal décrite n'obtenait jamais sa description, donc ne
pouvait jamais être scorée correctement.

**La preuve.** 14 offres écartées, enrichies à la main puis re-scorées :

```
0.0 → 64.4   Technicien Qualité & Production Béton
0.0 → 61.8   Technicien(ne) de laboratoire
0.0 → 61.8   Assistant laboratoire en alimentaire
0.0 → 59.8   Technicien Qualité & Production Béton
0.0 → 50.0   Support Laboratoire Polyvalent
```

**6 sur 12 passent de 0 à ≥50.**

**La correction.** `matching/preselection_rescue.py` ajoute une seconde porte
d'entrée : un intitulé métier suffit, même si le pré-score rejette.

```
retenues par le pré-score : 580
sauvées par l'intitulé    : 244
```

Coût : ~9 minutes au premier run, ~30 secondes ensuite (cache). Audit **33/33**,
dont un bloc entier sur les faux positifs — « Élaboration de projets » ne doit
pas matcher *labo*, « Consultant Qatar » ne doit pas matcher *QA*.

### 6.2 Vocabulaire néerlandais

Correction d'une affirmation fausse faite en cours de route : **le Matcher
contenait déjà 151 termes néerlandais**, et 61 des 72 offres néerlandaises à
intitulé métier scoraient déjà ≥50.

Il manquait quatre concepts, ajoutés à `config/profile.py` :
`process_technician`, `sampling`, `quality_controller`, `researcher` — avec les
formes **belges** : `technieker` (les Pays-Bas disent *technicus*),
`procestechnieker`, `staalnemer`, `kwaliteitscontroleur`.

Résultat : 13 offres améliorées, 1 franchit le seuil, **zéro régression**.

### 6.3 Connecteur Phenom — le plus solide du projet

Il lit le **JSON-LD `schema.org/JobPosting`**, pas du HTML. Titre, date, pays et
description arrivent structurés : un changement de design du site ne le casse pas.

Test réel sur UCB : **0 % d'échec**, 15 offres belges sur 45 visitées, dont 5 ≥50.
Toutes à **Braine-l'Alleud et Anderlecht** — sites francophones, contrairement à
J&J Beerse.

Extrapolé : ~118 offres belges sur les 357 du sitemap. Audit **28/28**.

---

## 7. La question de l'accès — ce qui est fait et ce qui ne l'est pas

Le projet distingue trois niveaux, et cette distinction a été appliquée
systématiquement.

### Ce qui est fait

| Niveau | Sources | Pourquoi c'est légitime |
|---|---|---|
| API publique documentée | SmartRecruiters, Greenhouse, Recruitee | Conçues pour être consommées |
| API du site carrière public | Workday, Phenom | Servies ouvertement, sans authentification ni blocage |
| Sitemap + page publique | SuccessFactors, Phenom | `robots.txt` autorise les chemins `/job/`, un sitemap existe pour les machines |

### Ce qui n'a pas été fait : Jobat

Le connecteur `sources/jobat.py`, ajouté par une autre session, bascule sur un
navigateur Edge piloté par Playwright lorsque le site renvoie **403, 429 ou 503**.
Le code journalise lui-même « page anti-bot détectée ».

C'est un contournement de protection technique. La documentation du projet
l'exclut explicitement, et les conditions de Mediahuis vont dans le même sens.

**Claude n'a pas travaillé sur ce connecteur** et ne l'a pas amélioré. Les
fichiers ont été conservés pour que la copie reste fidèle et fonctionnelle.

> **Décision à prendre.** Soit la règle du projet change en connaissance de cause,
> soit le connecteur est retiré. `JOBAT` est actuellement à `true` dans
> `config/source_settings.json`.

---

## 8. Les outils créés

### Diagnostics

```bash
python -m diagnostics.run_all              # suite complète — 34/34
python -m diagnostics.run_all --list       # classement des ~84 diagnostics
python -m diagnostics.run_all --network    # inclut les appels réseau
```

`run_all.py` classe chaque diagnostic en six catégories et **refuse de rien
lancer si un diagnostic n'est pas classé** — la liste ne peut donc pas pourrir.

### Découverte de sources

| Outil | Rôle |
|---|---|
| `ats_fingerprint` | Identifie l'ATS d'une entreprise et extrait son identifiant |
| `ats_discovery` | Teste des noms contre les API Recruitee / Greenhouse / SmartRecruiters |
| `workday_discovery` | Trouve un tenant Workday par la méthode 404 / 422 |

**La méthode 404/422** : tester un tenant avec un nom de site absurde. Un `404`
signifie que le couple tenant + wd existe et que seul le site est faux ; un `422`
que le couple n'existe pas. Cela transforme une recherche multiplicative en
recherche additive.

### Brique commune

`sources/location_belgium.py` — détection de localisation belge, **51/51**.

Quatre statuts : `BE_CONFIRMED`, `BE_LIKELY`, `BE_UNKNOWN`, `BE_EXCLUDED`.
Le quatrième a été ajouté parce que « Berlin, Germany » et « EMEA » ne demandent
pas le même traitement.

Pièges traités : `BE` ne doit pas matcher *Berlin*, *Bern*, *Aberdeen* ;
*Luxembourg* est à la fois un pays et une province belge ; *Bruges* existe en
France ; les codes postaux belges donnent la province ; les localisations
multiples (`"New York, USA; Brussels, Belgium"`) retiennent le meilleur statut.

---

## 9. Le chiffre qui n'a pas bougé

```
offres collectées          5 430
entités lifecycle             66
statut APPLIED                 0
CV générés                     0
candidatures envoyées          0
```

Le pipeline produit 37 offres `APPLY_NOW`. Aucune n'a donné lieu à une
candidature.

**Conséquence technique** : rien ne valide le Matcher. Personne ne sait si une
offre à 139/100 obtient plus de réponses qu'une à 90. Tous les seuils de scoring,
de Gate et de priorisation reposent sur des valeurs qu'aucune donnée réelle n'a
confirmées.

Le `lifecycle` est prêt à enregistrer :

```bash
python -m applications.chatgpt_handoff --limit 3   # génère le bundle
python lifecycle.py set-status ITEM_xxx APPLIED    # enregistre l'envoi
```

À partir de 15-20 candidatures enregistrées, il deviendra possible de savoir quel
track répond, quel score corrèle avec une réponse, quelle source convertit.

---

## 10. Ce qui reste ouvert

### Décisions qui reviennent à l'utilisateur

1. **Jobat** — garder le contournement anti-bot, ou retirer le connecteur.
2. **Gate V1.3.5** — brancher la couche Claude dans `main.py` (une ligne).
3. **CV** — le niveau néerlandais est corrigé en A2 dans la config, donc dans les
   bundles ChatGPT. Vérifier que le document `.docx` dit la même chose.

### Chantiers techniques identifiés

| Priorité | Chantier | Pourquoi |
|---|---|---|
| Haute | **Première candidature envoyée** | Débloque la validation du Matcher |
| Haute | Lancer un run complet avec les 11 sources | Mesurer l'effet du sauvetage de pré-sélection |
| Moyenne | Élargir Forem au-delà des 199 termes | La Wallonie est à 6,9 % de la collecte |
| Moyenne | Plus d'employeurs Phenom et Workday | Meilleur rendement mesuré |
| Basse | Connecteurs Oracle Cloud, Avature | 3 employeurs à eux deux |

### Tenants Workday non résolus

`msd` (wd5), `organon` (wd5), `roche` (wd3), `elanco` (wd5) répondent mais leur
nom de site reste introuvable. Janssen, Takeda, Solvay et Umicore n'ont répondu à
aucun numéro wd — ils sont sur un autre ATS.

---

## 11. Travail en parallèle — point de vigilance

Une autre session d'assistant (probablement ChatGPT) a travaillé sur
`C:\Users\Aharr\Desktop\JobHunter` **pendant** les sessions Claude, parfois dans
la même heure. Le dossier `JobHunter - Copie` a donc divergé plusieurs fois.

Conséquences observées :

- Une analyse Claude a été faite sur une copie périmée et a produit des
  conclusions fausses, corrigées ensuite.
- Deux modules `chatgpt_handoff.py` concurrents ont existé, fusionnés depuis.
- Un correctif Claude (`startswith("1.0")`) a cassé quand l'autre session est
  passée en 1.1.0.

**Règle retenue** : toujours comparer les deux dossiers avant d'analyser ou de
patcher.

```bash
diff -rq --exclude=".venv" --exclude="__pycache__" --exclude="exports" \
     "JobHunter" "JobHunter - Copie"
```

---

## 12. Leçons transversales

Trois principes se sont dégagés du travail, et ils valent au-delà de ce projet.

**Mesurer avant de coder.** Un correctif du Gate validé 32/32 en diagnostic
changeait **0 offre sur 575** en replay réel. Un diagnostic vert ne dit rien de
l'impact. La règle : avant de coder un correctif, mesurer combien d'offres il
change sur le dernier run. Si c'est zéro, le documenter et passer à autre chose.

**Un audit ne doit pas épingler ce qui va bouger.** Ni un numéro de version, ni
une chaîne d'implémentation, ni un résultat de run. Il doit exprimer une
propriété : *au moins cette version*, *ce motif attrape ceci et pas cela*, *au
moins une offre*. Un test qui casse quand le code s'améliore n'est pas un filet
de sécurité, c'est un frein — et un diagnostic qui crie au loup finit par ne plus
être lu.

**Le matching de texte doit toujours avoir des frontières.** C'est la cause
unique du bug V.I.E, de « pharmA PLUS », de « Evere/Beveren », de « Élaboration »
qui matcherait *labo*. Le projet possède déjà l'outil : `phrase_regex()` dans
`application_gate.py`. Il faut l'utiliser partout.

---

## 13. État final vérifié

```
Suite de diagnostics       34/34
Préflight Daily Run        validé
main.py                    importable, V10.5
Sources au registre        11, toutes actives
Fichiers Python            ~77 900 lignes
```

### Versions installées

| Composant | Version |
|---|---|
| MAIN | 10.5 |
| Daily Run | 1.2.0 |
| Matcher | 5.1 (frozen) |
| Canonical | 3.1.3 (frozen ; V3.1.2 + calcul paresseux validé le 17/09/2026) |
| Application Gate | 1.3.2 en production · 1.3.5 disponible |
| Application Queue | 1.2 |
| Job Refresh | 1.2 |
| Application Recheck | 1.1 |
| Final Application Pool | 1.2 |
| Delta Tracker | 1.1 |
| ChatGPT Handoff | 1.0 |
| Lifecycle | 1.0 |
| Détection localisation belge | 1.0 |
| Sauvetage de pré-sélection | 1.0 |

### Nettoyage du 22 août

**39 éléments envoyés à la corbeille** — donc récupérables :

- 25 scripts `upgrade_*.py` de migration déjà appliqués
- 5 versions candidates `daily_run_v1XX_candidate.py`
- 2 runners shadow SmartRecruiters (rôle terminé)
- 1 module `sources/forem_broad.py` mesuré inutile (2,7 % de pertinence)
- 6 dossiers de staging `*_files`

Conservés malgré les apparences, parce que **référencés par la suite de
diagnostics** : `job_refresh_v11.py`, `job_refresh_v12.py`,
`application_recheck_v11.py`, `application_preparation_v11.py`,
`final_application_pool_v12.py`, `delta_tracker_v11.py`,
`matching/application_gate_v13_overlay.py`.

La suite a été relancée après suppression : **34/34**, rien n'est cassé.
