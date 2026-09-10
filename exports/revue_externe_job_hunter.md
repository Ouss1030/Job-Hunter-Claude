# Job Hunter Belgium — retour de revue externe #2

Vérification faite sur une copie isolée, à l'état du 19/08/2026 vers 03:50 :
MAIN V10.4.1, Gate V1.3.2, Queue V1.2, Pool V1.2, Delta Tracker V1.1,
Handoff V1.0 (schéma bundle 1.1), Daily Run V1.2.0, Lifecycle V1.0.

Aucune modification n'a été faite sur le dossier d'origine.

---

## D'abord : les correctifs du premier retour sont bien passés

Vérifié un par un sur la copie :

| Point du retour précédent | État |
|---|---|
| Collision de motifs d'artefacts | corrigé, et couvert par `artifact_pattern_collision_audit` |
| Épinglage de version dans les audits | corrigé via `diagnostics/version_support.py` |
| Vérité candidat dupliquée | corrigé — `config/candidate_truth.py` est désormais la source unique |
| Audits remplacés mélangés aux autres | corrigé — `run_all.py` avec 6 catégories |
| `requirements.txt` absent | créé |

Deux choses sont même mieux que ce que je proposais :

- **`run_all.py` refuse de lancer quoi que ce soit si la classification est
  incomplète.** Ma version se contentait d'avertir. Le refus est le bon choix :
  il force la liste à rester à jour. Il a d'ailleurs détecté immédiatement mes
  deux fichiers non classés.
- **`artifact_pattern_collision_audit`** est un audit dédié à la régression que
  j'avais signalée. Meilleur que de laisser la protection implicite.

Et surtout : **`lifecycle` V1.0 existe**. C'est le chantier que j'avais désigné
comme le plus utile. Le CLI fonctionne, le schéma est propre (`application_entities`,
`application_events`, `source_identity_aliases`), le bootstrap a créé 66 entités et
232 événements, et `actor_type=USER` est bien exigé pour toute mutation manuelle.
La règle « aucun `APPLIED` sans action utilisateur » est testée explicitement.

---

## Problème 1 — L'anti-pattern d'épinglage est revenu dans le code neuf

C'est le point important de ce retour. Le correctif a été appliqué là où je l'avais
signalé, mais la règle n'a pas été généralisée : les audits écrits **après** le
retour réintroduisent exactement le même défaut, sous quatre formes.

### 1a. `hardening_step7_final_validation` — 12/15

Cet audit, censé être la validation finale du durcissement, échoue sur trois
assertions qu'il a lui-même figées :

```
[FAIL] Suite active reste a 25 diagnostics        | 26
[FAIL] Daily Run reste 1.1.1                      | 1.2.0
[FAIL] Pipeline Daily Run conserve 7 etapes       | 8 étapes (lifecycle inséré)
```

Il est devenu faux **en moins d'une heure**, à cause de votre propre travail :
`daily_run` est passé de 1.1.1 à 1.2.0 et l'étape `lifecycle` a été insérée.

Le point le plus parlant : `at_least()` avait été écrit une heure plus tôt, et
n'est pas utilisé ici. La ligne 193 compare une version avec `==`.

> Transparence : l'échec « suite active reste à 25 » est en partie de mon fait —
> j'avais ajouté un diagnostic à la suite, ce qui la porte à 26. Mais l'assertion
> aurait cassé de toute façon au premier diagnostic ajouté, ce qui est justement
> le geste que le durcissement encourage.

**Correctifs appliqués côté copie :**

```python
len(run_all.SUITE_ACTIVE) >= 25                          # plancher, pas égalité
at_least(daily_run.DAILY_RUN_VERSION, "1.1.1")           # votre propre helper
# étapes attendues présentes DANS L'ORDRE, insertions autorisées
positions = [installe.index(e) for e in expected_order if e in installe]
len(positions) == len(expected_order) and positions == sorted(positions)
```

Résultat : **15/15**.

### 1b. Trois audits lifecycle épinglent le nombre d'entités

```
lifecycle_step8c_bootstrap_audit.py:289    snap["counts"]["application_entities"] == 66
lifecycle_step8d_manual_cli_audit.py:66    entities == 66
lifecycle_step8e_sync_audit.py:414         prod["entities"] == 66
```

66 est la taille du Final Pool d'aujourd'hui. À la prochaine collecte, ces trois
audits deviendront rouges sans qu'aucun défaut n'existe — et cette fois sur le
composant qui garde la trace de vos candidatures.

**Correctif appliqué côté copie :** `>= 1`, avec un commentaire expliquant que
l'invariant réel est « il existe des entités », pas « il y en a 66 ».

### La règle à retenir

Un audit ne doit épingler que ce qui ne doit **jamais** changer. Ni un numéro de
version, ni un compte de diagnostics, ni une taille de pool, ni une chaîne
d'implémentation, ni un résultat de run. Il doit exprimer une propriété : *au
moins cette version*, *ces étapes dans cet ordre*, *au moins une entité*.

Un test qui casse quand le code s'améliore n'est pas un filet de sécurité, c'est
un frein. Et un diagnostic qui crie au loup sans raison finit par ne plus être lu.

---

## Problème 2 — La suite exclut 8 audits verts, soit 56 contrôles

`SUITE_ACTIVE` contient 26 diagnostics. Huit autres, tous **verts**, sont classés
en `RAPPORTS` ou `HISTORIQUE` et ne sont donc jamais lancés par `run_all` :

```
daily_run_v110_current_installation_audit         6/6
delta_tracker_v11_current_batch_audit             2/2
application_recheck_v11_current_batch_audit       7/7
final_application_pool_v12_current_batch_audit   19/19
job_refresh_v12_post_upgrade_audit                6/6
application_preparation_v11_post_upgrade_audit    5/5
final_application_pool_v12_post_upgrade_audit     6/6
application_recheck_v11_post_upgrade_audit        5/5
```

Le classement se défend pour les `current_batch` (ils dépendent des artefacts du
dernier run). Il se défend beaucoup moins pour les quatre `post_upgrade`, dont
c'est précisément le rôle de vérifier qu'une montée de version a bien pris : les
mettre en « historique » revient à ne plus jamais le vérifier.

Cas particulier : `daily_run_v110_current_installation_audit` est l'audit qui
avait révélé la collision de motifs. Le classer en `RAPPORTS` retire ce garde-fou
de la suite. Le nouvel `artifact_pattern_collision_audit` couvre bien le cas, donc
la protection existe — mais elle repose désormais sur un seul audit.

**Suggestion :** une catégorie `SUITE_DATA`, lancée quand les artefacts existent
et ignorée sinon, plutôt qu'une exclusion pure.

---

## Problème 3 — Import dupliqué dans `chatgpt_handoff.py`

```python
ligne 43 : from config.candidate_truth import DEFAULT_BASE_CV_NAME as CANONICAL_DEFAULT_BASE_CV_NAME
ligne 58 : from config.candidate_truth import (
               DEFAULT_BASE_CV_NAME,
               FORBIDDEN_CANDIDATE_CLAIM_TERMS,
               HARD_TRUTH_RULES,
               build_handoff_candidate_truth,
           )
```

`DEFAULT_BASE_CV_NAME` est importé deux fois, dont une sous alias, et le second
import est au milieu du corps du module, après des affectations. C'est le résidu
visible du hotfix d'ordre d'import (`chatgpt_handoff_before_step4c_import_hotfix`).

Ça fonctionne, rien n'est cassé. Mais deux noms pour la même constante dans un
module dont le rôle est justement de garantir une source unique de vérité, c'est
le genre de détail qui redevient un vrai problème six mois plus tard.

**Non corrigé côté copie** : purement cosmétique, et je préfère ne pas toucher à
un fichier que vous venez de patcher deux fois.

---

## Détail mineur — `requirements.txt` épingle des versions exactes

```
beautifulsoup4==4.15.0
requests==2.34.2
urllib3==2.7.0
```

Choix défendable pour la reproductibilité. Deux conséquences à connaître : aucun
correctif de sécurité ne sera pris sans édition manuelle, et `openai` +
`python-docx` sont désormais dans les dépendances principales alors qu'ils étaient
optionnels (`requirements_ai.txt`). Une installation minimale tire maintenant tout.

Si l'intention était de garder l'IA optionnelle, `requirements.txt` devrait se
limiter à `requests`, `beautifulsoup4`, `urllib3`.

---

## Récapitulatif des correctifs appliqués côté copie

| Fichier | Correctif |
|---|---|
| `diagnostics/hardening_step7_final_validation.py` | 3 assertions figées → plancher, `at_least()`, ordre des étapes |
| `lifecycle_step8c_bootstrap_audit.py` | compte d'entités dépinglé |
| `lifecycle_step8d_manual_cli_audit.py` | compte d'entités dépinglé |
| `lifecycle_step8e_sync_audit.py` | compte d'entités dépinglé |
| `diagnostics/run_all.py` | classement des 2 diagnostics Gate V1.3.3 |
| `database/jobs.db` | schéma lifecycle installé + bootstrap (66 entités) |

État final de la copie : **suite 26/26**, plus 15 audits hors suite tous verts,
`hardening_step7` à 15/15, les 6 audits lifecycle à 17/17, 14/14, 15/15, 15/15,
12/12 et 19/19.

---

## Ce qui reste, et qui compte plus que tout le reste

Le pipeline est désormais complet de bout en bout, avec traçabilité. Il reste un
seul chiffre qui n'a pas bougé depuis le premier retour :

```
entités lifecycle en base : 66
statut APPLIED            : 0
CV générés                : 0
candidatures envoyées     : 0
```

Le `lifecycle` est prêt à enregistrer une candidature — `python lifecycle.py
set-status ITEM_xxx APPLIED` fonctionne, je l'ai vérifié. Personne ne l'a encore
utilisé.

Tant qu'aucune candidature n'est partie, rien ne valide le Matcher : on ne sait
toujours pas si une offre à 139/100 obtient plus de réponses qu'une à 90. Le
`lifecycle` est exactement l'outil qui répondra à cette question — mais seulement
une fois qu'il contiendra de vraies données.

La prochaine chose qui apporterait de la valeur n'est plus du code. C'est une
première candidature réellement envoyée, et son statut enregistré.
