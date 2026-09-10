# Job Hunter Belgium — cahier des charges : élargir les sources via les ATS publics

Objectif : augmenter le volume d'offres pertinentes sans scraper aucun site,
en consommant des API publiques et documentées, conçues pour être lues.

---

## 1. Mise au point préalable : ce que sont Greenhouse, Lever et Recruitee

Ce ne sont **pas** des sites d'offres d'emploi. Ce sont des ATS — les logiciels
qui hébergent la page carrière de chaque entreprise.

On n'interroge donc jamais « Greenhouse » pour obtenir les offres belges. On
interroge **l'employeur X hébergé chez Greenhouse**, et on récupère l'ensemble
de ses offres, dans le monde entier. Il y a des offres belges uniquement si cet
employeur recrute en Belgique.

C'est exactement le modèle SmartRecruiters déjà en place : la source n'est pas
« SmartRecruiters », ce sont SGS, Eurofins et Sopra Steria.

**Conséquence directe sur la charge de travail.** Le connecteur est la partie
facile — environ une journée pour les trois. La valeur réelle vient de la
**liste d'employeurs**, qui est un travail de recherche, pas de code. Un
connecteur Greenhouse sans employeurs belges pertinents ne rapporte rien.

---

## 2. Ce qui existe déjà et qu'il faut réutiliser

Le socle est en place, il ne faut rien réinventer :

- `sources/registry.py` — architecture à plugins. Une source = un `SourceSpec`
  (`key`, `result_key`, `label`, `collector`, `languages`, `priority`, `notes`).
- `config/source_settings.json` — activation/désactivation par source.
- `sources/smartrecruiters.py` — le modèle à copier. 220/220 offres converties,
  0 échec. C'est le meilleur patron disponible.
- `config/smartrecruiters_sources.py` — le modèle de configuration d'employeurs
  (`identifier`, `label`, `tracks`, `enabled`).
- `diagnostics/run_all.py` — toute nouvelle source doit avoir son audit classé.

---

## 3. Le point technique critique : détecter la Belgique

C'est **le** risque du chantier, et il mérite d'être traité avant d'écrire une
ligne de connecteur.

SmartRecruiters renvoie un champ structuré :

```json
"location": { "country": "be", "city": "Wavre" }
```

Le filtre actuel est donc fiable : `country == "be"`.

**Greenhouse, Lever et Recruitee renvoient une chaîne de texte libre.** Selon
l'employeur, on trouvera :

```
"Brussels, Belgium"      "Bruxelles"        "Brussel"
"Ghent, BE"              "Wavre"            "Belgium - Remote"
"EMEA"                   "Zaventem, BE"     "Diegem"
```

Filtrer là-dessus, c'est du matching de texte — exactement la famille de défauts
qui a déjà coûté cher au projet : le bug V.I.E, « Evere » qui matchait
« Beveren », « pharmA PLUS » qui neutralisait un Master exigé.

### Règles à respecter

1. **Jamais de sous-chaîne nue.** Réutiliser `phrase_regex()` de
   `matching/application_gate.py` ou `_bounded_phrase_in_text()` de
   `matching/application_queue_v12.py`. Les deux existent et sont validés.
   Le piège concret : le token `"BE"` en sous-chaîne matche *Berlin*,
   *Bern*, *Aberdeen*, *Beverly*.

2. **Trois niveaux de confiance**, pas un booléen :
   - `BE_CONFIRMED` — mention explicite du pays (`Belgium`, `Belgique`,
     `België`, `, BE` en fin de chaîne avec frontière de mot).
   - `BE_LIKELY` — ville belge reconnue sans mention de pays (`Wavre`,
     `Zaventem`, `Diegem`, `Anderlecht`…). Réutiliser `PREFERRED_LOCATIONS`
     de `config/profile.py` comme base, en l'élargissant.
   - `BE_UNKNOWN` — `EMEA`, `Remote`, `Europe`, chaîne vide.

3. **Ne jamais jeter les `BE_UNKNOWN` silencieusement.** Les compter et les
   journaliser. Une offre « Remote – Europe » chez un employeur belge peut être
   parfaitement valable. Le principe du projet est déjà celui-là : mieux vaut
   deux doublons qu'une fusion à tort.

4. **Attention aux villes homonymes.** Il existe un Wavre en Belgique et des
   homonymes ailleurs ; Bruges existe aussi en France. Une ville seule donne
   `BE_LIKELY`, jamais `BE_CONFIRMED`.

### Livrable attendu en premier

Avant les connecteurs : un module `sources/location_belgium.py` avec

```python
def detect_belgium(location_text: str) -> str:   # BE_CONFIRMED | BE_LIKELY | BE_UNKNOWN
```

et son diagnostic `diagnostics/location_belgium_v1_audit.py` contenant au
minimum les cas pièges ci-dessus : `"Berlin"` ne doit pas être belge,
`"Aberdeen"` non plus, `"Ghent, BE"` doit être `BE_CONFIRMED`, `"Wavre"` doit
être `BE_LIKELY`, `"EMEA"` doit être `BE_UNKNOWN`.

Ce module servira aux trois connecteurs. L'écrire une fois, bien, évite de
répéter trois fois la même erreur.

---

## 4. Spécification par source

> Les endpoints ci-dessous correspondent aux API publiques telles que
> documentées à ma connaissance. **À revalider en premier** : une requête
> manuelle sur un employeur connu, avant d'écrire le connecteur. Si un endpoint
> a changé, corriger la spec plutôt que de contourner.

### 4.1 Greenhouse — `sources/greenhouse.py`

```
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
```

- Public, sans authentification.
- `board_token` = identifiant du board de l'employeur.
- `content=true` renvoie le descriptif complet — évite un second appel par offre.
- Champs utiles : `id`, `title`, `location.name`, `absolute_url`,
  `updated_at`, `content` (HTML échappé).
- Le `content` est du HTML : le déséchapper puis le nettoyer avec BeautifulSoup,
  comme le fait déjà `forem_detail.py`.

### 4.2 Lever — `sources/lever.py`

```
GET https://api.lever.co/v0/postings/{company}?mode=json
```

- Public, sans authentification.
- Champs utiles : `id`, `text` (le titre), `categories.location`,
  `categories.team`, `categories.commitment`, `hostedUrl`,
  `descriptionPlain`, `createdAt`.
- `descriptionPlain` est déjà en texte brut : pas de nettoyage HTML nécessaire.
- Un paramètre `location` existe mais les valeurs dépendent de l'employeur :
  ne pas s'y fier, filtrer côté client avec `detect_belgium()`.

### 4.3 Recruitee — `sources/recruitee.py`

```
GET https://{company}.recruitee.com/api/offers/
```

- Public, sans authentification.
- Réponse : `{ "offers": [...] }`.
- Champs utiles : `id`, `title`, `location`, `city`, `country_code`,
  `careers_url`, `description`, `requirements`.
- **Avantage** : `country_code` est structuré. Quand il vaut `BE`, on obtient un
  `BE_CONFIRMED` fiable sans passer par le texte. Bonne source pour commencer.

---

## 5. Conventions à respecter, identiques à SmartRecruiters

Pour chaque connecteur :

1. **Configuration séparée du code** — `config/greenhouse_sources.py` sur le
   modèle de `config/smartrecruiters_sources.py` : liste d'employeurs avec
   `identifier`, `label`, `tracks`, `enabled`. Ajouter un employeur ne doit
   jamais demander de toucher au connecteur.

2. **Politesse réseau** — `User-Agent` explicite, `timeout`, retries avec
   backoff, `time.sleep` entre les appels. Le patron existe dans
   `sources/forem.py` lignes 96-114 et 259-338.

3. **Cache local** — sur le modèle de `logs/actiris_detail_cache_v2/`, pour
   pouvoir rejouer sans rappeler l'API.

4. **`matching_text` propre** — la leçon SmartRecruiters V1.1 : ne jamais
   inclure la description corporate de l'entreprise dans le texte envoyé au
   Matcher. Elle produisait des faux positifs Real Estate, HR, KYC. Garder le
   texte corporate à part, hors scoring.

5. **Provenance** — `collection_channel = "GREENHOUSE"`,
   `origin_source = <identifiant employeur>`, comme SmartRecruiters expose
   `SGS` / `EUROFINS` / `SOPRASTERIA1`.

6. **Un audit par source**, classé dans `run_all.py` :
   - un audit hors ligne sur des données figées (dans `SUITE_ACTIVE`) ;
   - un audit live séparé (dans `NETWORK`, jamais lancé par défaut).

7. **Pas de version épinglée dans les audits.** Utiliser
   `diagnostics/version_support.at_least()`. Ce point a déjà coûté plusieurs
   faux rouges, dont un blocage complet du Daily Run.

---

## 6. Trouver les employeurs — le vrai travail

Sans liste d'employeurs, les connecteurs ne servent à rien. Méthode proposée :

1. Partir des secteurs cibles : pharma, biotech, laboratoires d'analyse,
   chimie, agroalimentaire, dispositifs médicaux, ESN orientées Life Sciences.
2. Pour chaque entreprise ayant un site belge, ouvrir sa page carrière et
   regarder l'URL. Elle révèle l'ATS :
   - `boards.greenhouse.io/<token>` ou `job-boards.greenhouse.io/<token>`
   - `jobs.lever.co/<company>`
   - `<company>.recruitee.com`
   - `careers.smartrecruiters.com/<Company>` → déjà couvert
3. Noter l'identifiant et l'ajouter au fichier de config correspondant.
4. Commencer petit : **3 employeurs par ATS**, exactement comme le premier test
   SmartRecruiters. Valider, puis élargir.

Pistes à explorer côté belge : sous-traitants et laboratoires d'analyse,
groupes pharma présents en Wallonie et au Brabant, CRO, sociétés de contrôle
qualité, biotech de la région de Gand et de Louvain.

---

## 7. Critères de validation, par source

Reprendre le protocole qui a validé SmartRecruiters :

1. **Diagnostic hors ligne** sur un échantillon figé : conversion, détection
   Belgique, `matching_text` sans texte corporate, provenance correcte.
2. **Test live** sur les 3 employeurs, en comptant : offres totales, offres
   belges `CONFIRMED` / `LIKELY` / `UNKNOWN`, échecs de conversion. Objectif :
   **0 échec**, comme les 220/220 de SmartRecruiters.
3. **Replay Gate + Queue sans recollecte**, pour vérifier qu'aucune offre hors
   cible ne remonte en `READY_APPLY`.
4. **Contrôle de pureté** : aucune offre non belge dans le pool final, aucun
   `matching_text` contenant du texte corporate.

Une source n'est intégrée dans `main.py` qu'après ces quatre étapes — cycle
diagnostic → shadow → comparaison → intégration, comme pour tout le reste.

---

## 8. Ordre de travail proposé

| Étape | Contenu | Pourquoi en premier |
|---|---|---|
| 1 | `sources/location_belgium.py` + audit | Brique commune aux trois, et principal risque |
| 2 | Recruitee | `country_code` structuré : la plus simple, valide le patron |
| 3 | Greenhouse | Volume potentiel le plus important |
| 4 | Lever | Même patron, description déjà en texte brut |
| 5 | Élargissement des employeurs | Là où se trouve la vraie valeur |

---

## 9. Deux points à trancher avant de commencer

### 9.1 L'état actuel de `config/source_settings.json`

```json
"FOREM": false, "ACTIRIS": false, "TALENT_BRUSSELS": false,
"TRAVAILLERPOUR": false, "SMARTRECRUITERS": false, "JOBAT": true
```

Toutes les sources historiques sont désactivées et seul Jobat est actif. Au
prochain run, la collecte ne ramènerait que Jobat. C'est probablement un reste
de test, mais il faut le corriger avant toute nouvelle collecte, sinon les
mesures de la nouvelle source seront comparées à un run vide.

### 9.2 Jobat

Le connecteur actuel bascule sur un navigateur Edge piloté par Playwright
lorsque le site renvoie 403, 429 ou 503 — le code journalise lui-même
« page anti-bot détectée ». C'est un contournement de protection technique.

La documentation du projet l'exclut explicitement (§10 : *« Ne pas contourner
le 403 / anti-bot […] PAS de scraper anti-bot Jobat »*, et §39 point 7). Les
conditions de Jobat / Mediahuis vont dans le même sens.

Le sujet mérite une décision explicite plutôt qu'un silence : soit la règle du
projet change en connaissance de cause, soit le connecteur est retiré. Les ATS
publics décrits ici apportent du volume sans poser cette question.

---

## 10. Ce que ce chantier n'est pas

- Ce n'est pas du scraping : ce sont des API publiques, documentées, prévues
  pour être consommées, sans authentification ni contournement.
- Ce n'est pas un nouveau moteur : le Matcher, le Gate, la Queue, le Pool et le
  Lifecycle ne bougent pas. On ajoute des sources en amont, c'est tout.
- Ce n'est pas urgent au point de sauter la validation. Le pipeline produit déjà
  37 offres `APPLY_NOW` dont aucune n'a encore donné lieu à une candidature.
  Plus de sources sans candidature envoyée, c'est plus de volume sans plus de
  résultat.
