# Revue du STEP 1 — V3.8 PIPELINE RELIABILITY

**31 août 2026.** Revue des deux fichiers livrés, par exécution réelle et non par
lecture. Aucun fichier n'a été modifié ; le diagnostic a été exécuté en lecture
seule (`mode=ro`, aucune écriture dans le code).

À lire **avant** le STEP 2, parce que deux défauts se propageraient à tous les
connecteurs au moment de les brancher.

---

## 1. Ce qui fonctionne, vérifié

### `diagnostics/source_yield_audit.py`

Exécuté. Il reproduit le constat exactement :

```
Sources declarees                 : 22
Sources actives                   : 21
Sources ayant un historique DB    : 6
Sources actives jamais en base    : 15
```

Il est strictement en lecture seule — aucun `write_text`, aucun `json.dump`,
base ouverte en `mode=ro`. Il est honnête sur sa portée, et le dit lui-même :

> ne distingue pas encore réseau / géographie / langue / non-cible

C'est la bonne façon de livrer un instrument.

### `sources/belgium_locations.py`

Testé sur 26 cas. **23 corrects.** Les acquis réels :

```
Wavre, Braine-l'Alleud, Beerse, Anderlecht, Gent, Anvers,
Liège, Charleroi, Hoboken, Puurs, Zaventem, Louvain-la-Neuve   → BELGIUM
Lessines, Wallonia                                             → BELGIUM
Munich Germany / Paris France / Bruges France                  → FOREIGN
""                                                             → UNKNOWN
```

Les pièges annoncés sont tenus : `BE` ne matche pas *Berlin*, *Bruges, France*
est rejeté, *Luxembourg* seul donne UNKNOWN et non BELGIUM.

C'est nettement au-dessus des dix listes dispersées. Les trois défauts ci-dessous
ne remettent pas ça en cause.

---

## 2. DÉFAUT 1 — une abréviation d'État américain n'est pas reconnue comme étrangère

### La preuve

```python
from sources.belgium_locations import classify_belgium_location as C
for t in ["Hoboken, NJ, United States of America",
          "Hoboken, NJ 07030",
          "Charleroi, PA",
          "Ghent, KY",
          "Waterloo, ON",
          "Antwerp, NY"]:
    print(t, C(t).status)
```

Résultat obtenu :

| Localisation | Statut | |
|---|---|---|
| `Hoboken, NJ, United States of America` | FOREIGN | correct |
| `USA-NJ-Hoboken` | FOREIGN | correct |
| `Hoboken, NJ 07030` | **BELGIUM** | **faux positif** |
| `New Brunswick, NJ / Hoboken, NJ` | **BELGIUM** | **faux positif** |
| `Charleroi, PA` | **BELGIUM** | **faux positif** |
| `Ghent, KY` | **BELGIUM** | **faux positif** |
| `Waterloo, ON` | **BELGIUM** | **faux positif** |
| `Antwerp, NY` | **BELGIUM** | **faux positif** |

### Le mécanisme

`FOREIGN_COUNTRY_MARKERS` contient des **pays** :

```
france germany deutschland allemagne netherlands nederland switzerland
suisse schweiz united kingdom uk united states usa canada spain espagne
italy italie ireland irlande austria autriche poland pologne denmark
danemark sweden suede norway norvege
```

Aucune subdivision. Or la règle est « ville belge reconnue → BELGIUM, sauf
marqueur de pays étranger explicite ». Quand Workday écrit `Hoboken, NJ` sans
répéter le pays — ce qui est le format le plus fréquent — la ville belge gagne.

### Pourquoi c'est urgent

**9 des 120 villes/alias déclarés ont un homonyme étranger connu :**

```
hoboken     Hoboken NJ (USA)              waterloo   Waterloo ON (Canada), IA (USA)
antwerp     Antwerp OH et NY (USA)        brussels   Brussels WI (USA)
ghent       Ghent KY et NY (USA)          charleroi  Charleroi PA (USA)
bruges      Bruges (France)               mons       Mons (France)
hasselt     Hasselt (Pays-Bas)
```

Ce n'est pas théorique : `Hoboken, NJ` est précisément la façon dont un tenant
Workday formate les postes du New Jersey — c'est-à-dire le cœur de l'implantation
américaine de Johnson & Johnson, l'un des connecteurs à brancher au STEP 3.

Le STEP 2/3 injecterait donc des offres américaines dans un pipeline belge. C'est
le défaut symétrique de celui qu'on vient de corriger, et il est plus coûteux :
une offre perdue est invisible, une offre étrangère acceptée arrive jusqu'au CV.

### Correctif proposé

Ajouter les subdivisions aux marqueurs étrangers, testées **avant** la
reconnaissance de ville :

- les 50 noms d'États américains en toutes lettres ;
- leurs codes à deux lettres, **uniquement précédés d'une virgule et isolés par
  des frontières lexicales** — sans quoi `ON`, `IN`, `OR`, `DE`, `LA`, `MA`, `ME`
  et `OK` matcheraient des mots ordinaires ;
- les provinces canadiennes.

Attention particulière à `DE` (Delaware) et `LA` (Louisiane) : très fréquents en
français et en néerlandais. La contrainte « précédé d'une virgule » est ce qui
rend la règle sûre.

---

## 3. DÉFAUT 2 — tout nombre à quatre chiffres est lu comme un code postal belge

### La preuve

| Localisation | Statut | |
|---|---|---|
| `Suite 1200, Boston` | **BELGIUM** | **faux positif** |
| `Building 2000` | **BELGIUM** | **faux positif** |
| `Room 4500, Basel` | **BELGIUM** | **faux positif** |
| `Poste ouvert en 2026` | **BELGIUM** | **faux positif** |
| `1000` | BELGIUM | discutable |
| `10001 New York` | UNKNOWN | correct |
| `75008 Paris` | UNKNOWN | correct |

Les codes à cinq chiffres sont bien écartés. Mais un numéro de bureau, un numéro
de bâtiment ou un millésime suffisent à conclure « Belgique ».

`Room 4500, Basel` est le cas le plus parlant : Bâle est le siège de Roche et de
Novartis, et `NOVARTIS` fait partie des connecteurs à brancher.

### Le mécanisme

C'est la même erreur de fond que la sous-chaîne sans frontière, transposée aux
nombres : `4500` est traité comme une preuve alors que ce n'est qu'une
coïncidence de format.

### Correctif proposé

Un code postal ne devrait compter comme preuve que s'il est **corroboré** :

- suivi ou précédé d'un nom de commune belge, ou
- accompagné d'un marqueur de pays belge, ou
- isolé en début de chaîne dans un format reconnu (`1000 Bruxelles`).

Et il ne devrait jamais compter s'il est précédé d'un mot comme *suite*, *room*,
*building*, *bureau*, *bât*, *étage*, *box*, ou suivi d'un contexte non
géographique.

En cas de doute, la bonne réponse est **UNKNOWN**, pas BELGIUM. Un code postal
seul est un indice, pas une preuve.

---

## 4. DÉFAUT 3 — le wrapper booléen annule le bénéfice des trois états

### Le constat

Le document V3.8 pose la bonne règle (§6) :

> Le résultat ne doit pas être un simple booléen. Il faut distinguer
> BELGIUM / FOREIGN / UNKNOWN.

Mais le wrapper de compatibilité écrase les trois états en deux :

```python
def is_belgium_location(location, *, trusted_belgium_listing=False,
                        extra_belgium_markers=None) -> bool:
    """Compatibilité simple pour les anciens connecteurs booléens."""
    return classify_belgium_location(...).status == BELGIUM
```

`UNKNOWN` et `FOREIGN` renvoient tous deux `False`.

### Pourquoi c'est un piège

C'est le chemin de migration le plus tentant : remplacer l'ancien
`_is_belgium_location` par celui-ci, une ligne par connecteur, et considérer le
STEP 3 fait. Or le code appelant reste :

```python
if location and not _is_belgium_location(location):
    continue          # toujours aucun compteur
```

On obtient alors une classification correcte suivie du même rejet silencieux
qu'avant, avec les offres à localisation inconnue traitées exactement comme
Munich. La règle §5 — *« aucun `continue` correspondant à une exclusion
importante ne doit rester sans compteur »* — serait violée tout en croyant
l'avoir appliquée.

### Correctif proposé

Ne pas utiliser le wrapper booléen pour la migration. Chaque connecteur devrait
appeler `classify_belgium_location` et brancher les trois cas sur les compteurs
prévus :

```
BELGIUM  → BELGIUM_ACCEPTED
FOREIGN  → GEOGRAPHY_REJECTED
UNKNOWN  → GEOGRAPHY_UNKNOWN   (à vérifier, pas à jeter)
```

Si le wrapper reste, sa docstring devrait dire explicitement qu'il ne convient
pas aux connecteurs instrumentés.

---

## 5. Point mineur — liste de pays étrangers incomplète

Les marqueurs couvrent l'Europe de l'Ouest et l'Amérique du Nord. Manquent
notamment :

```
Japan  China  India  Brazil  Singapore  Australia  Portugal  Czech
Hungary  Romania  Turkey  Mexico  Israel  Greece  Finland
```

Vérifié : `Tokyo, Japan` → UNKNOWN, `Boston, MA` → UNKNOWN.

Ce n'est pas une perte de données — le wrapper rejette UNKNOWN. C'est un problème
de lisibilité du futur diagnostic : des centaines d'offres manifestement
étrangères tomberont dans le compteur `GEOGRAPHY_UNKNOWN`, censé signaler les cas
à vérifier à la main. Le seul compteur qui devait rester lisible deviendrait le
plus bruyant.

Les tenants Workday pharma publient massivement depuis le Japon, Singapour,
l'Inde et le Brésil.

---

## 6. Ordre recommandé avant le STEP 2

1. Corriger les défauts 1 et 2 — ce sont des faux positifs, ils polluent le
   résultat au lieu de le réduire.
2. Compléter la liste des pays étrangers (défaut 5).
3. Migrer Baxter avec `classify_belgium_location` et les trois compteurs, **pas**
   avec le wrapper booléen (défaut 3).
4. Alors seulement, propager aux autres connecteurs.

Le STEP 2 tel qu'il est prévu — Baxter d'abord, avec ses critères
`Lessines / Braine-l'Alleud → ACCEPT`, `Munich / Paris → REJECT`, `"" → UNKNOWN`
— passe déjà aujourd'hui. C'est justement pourquoi les défauts ci-dessus ne
seraient pas vus : aucun de ces six cas ne contient d'abréviation d'État ni de
numéro de bureau.

---

## 7. Jeu de tests à ajouter

Ces cas sont ceux qui échouent aujourd'hui. Les figer évite la régression :

```python
# doivent donner FOREIGN
"Hoboken, NJ 07030"
"New Brunswick, NJ / Hoboken, NJ"
"Charleroi, PA"
"Ghent, KY"
"Waterloo, ON"
"Antwerp, NY"
"Tokyo, Japan"
"Boston, MA"

# doivent donner UNKNOWN
"Suite 1200, Boston"
"Building 2000"
"Room 4500, Basel"
"Poste ouvert en 2026"

# doivent rester BELGIUM (non-régression)
"Wavre"
"Braine-l'Alleud"
"Lessines, Wallonia"
"1000 Bruxelles"
"Brussels, Belgium"
"Hoboken"          # sans qualificatif étranger
"Charleroi"
```

Les trois derniers sont importants : le correctif ne doit pas rendre le
classifieur timide au point de perdre les vraies villes belges homonymes.

---

## 8. En résumé

| | Vérifié |
|---|---|
| `source_yield_audit.py` | fonctionne, lecture seule, honnête sur sa portée |
| `belgium_locations.py` | 23/26 sur les cas annoncés — la base est saine |
| Défaut 1 — abréviations d'États | 6 faux positifs sur 8 formats Workday réels |
| Défaut 2 — codes postaux | 4 faux positifs, dont `Room 4500, Basel` |
| Défaut 3 — wrapper booléen | reconduit le rejet silencieux si utilisé pour migrer |
| Point 5 — pays manquants | bruit futur dans `GEOGRAPHY_UNKNOWN` |

La direction est la bonne, et le diagnostic de rendement est exactement
l'instrument qui manquait. Les deux familles de faux positifs sont à traiter
avant de brancher le premier connecteur, pas après — une fois quinze connecteurs
migrés, distinguer un vrai gain d'un faux positif demandera de tout re-mesurer.

Une remarque de méthode : `py_compile` valide la syntaxe, jamais le comportement.
Les trois défauts ci-dessus sont dans du code qui compile parfaitement. Un fichier
de cas attendus, exécuté à chaque livraison, les aurait tous montrés en une
seconde.

---

## 9. Mise à jour — classifieur v1.1 re-testé le 1er septembre

`sources/belgium_locations.py` est passé en `_VERSION = "1.1"`. Re-testé sur les
mêmes cas :

```
cote belge     10 / 10   inchange, solide
cote etranger   0 / 10   les deux familles subsistent
```

Le seul changement observé est l'ajout du Japon aux pays étrangers
(`Tokyo, Japan` → FOREIGN). `Hoboken, NJ 07030`, `Charleroi, PA`, `Ghent, KY`,
`Waterloo, ON`, `Antwerp, NY` restent BELGIUM ; `Building 2000` et
`Room 4500, Basel` restent BELGIUM.

La liste de villes a par ailleurs ete reduite (120 alias -> ~24), ce qui reduit
la surface du probleme sans le traiter.

### Correctif applique et mesure

Les deux familles ont ete corrigees dans le module equivalent de ce dossier.
La demarche est reproductible telle quelle :

1. Reconnaitre les subdivisions etrangeres. Les codes a deux lettres ne
   comptent qu'apres une virgule et en capitales, sinon `ON`, `IN`, `OR`, `DE`,
   `LA`, `MA` et `OK` matchent des mots ordinaires. `BE` et `LU` sont exclus.

2. Un code postal seul ne conclut plus.

Resultat : 26 cas justes sur 26.

### La non-regression, mesuree sur 5 430 localisations reelles

```
statut            avant    apres    delta
BE_CONFIRMED       5 423    5 423       +0
BE_LIKELY              4        0       -4
BE_UNKNOWN             0        1       +1
BE_EXCLUDED            3        6       +3
```

Aucune offre belge perdue. Les 4 reclassees sont `9999, PL` (x3) et `9999, FR`.

Le durcissement du code postal paraissait risque : 2 437 offres ont un code
postal sans ville reconnue. Verification faite, toutes portent « Belgique » et
sont confirmees par le nom du pays. Seules 4 reposaient sur le code postal seul,
et aucune n'etait belge.

### Le point le plus urgent a change

Tant que les connecteurs employeurs ne produisaient rien, un faux positif
geographique etait sans consequence. Ils produisent maintenant : GSK, Pfizer,
Novartis, J&J, IBA, Akkodis, Randstad, Jefferson Wells et Quality Assistance
sont sortis du silence. Un faux positif va desormais jusqu'au CV.
