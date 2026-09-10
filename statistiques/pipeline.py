"""
JOB HUNTER BELGIUM
STATISTIQUES DE PIPELINE - VERSION 1.0

Ou les offres se perdent-elles, et la situation s'ameliore-t-elle ?

Un run isole ne dit rien. « 135 offres pretes » n'est ni bon ni mauvais tant
qu'on ignore si c'etait 111 la veille. Ce module relit les artefacts laisses
par les runs successifs et reconstitue l'entonnoir dans le temps.

L'entonnoir
-----------
    file            offres presentees au tri, apres deduplication canonique
    pretes          READY_APPLY : aucune reserve
    a tension       READY_STRETCH : un ecart a assumer
    a verifier      VERIFY_FIRST : un point a lever soi-meme
    ecartees        EXCLUDED
    pool            ce qui ressort effectivement, prêt a postuler

Pourquoi lire les artefacts et non la base
------------------------------------------
La base ne garde que l'etat courant : elle sait quelles offres sont actives
aujourd'hui, pas ce que le tri en avait fait la semaine derniere. Les
artefacts JSON, eux, sont dates et immuables — chacun est la photographie
d'un run. C'est la seule source d'histoire disponible.

Consequence directe : purger exports/logs supprime cette histoire. Le
nettoyage du 9 septembre 2026 conserve les cinq artefacts les plus recents
par famille, ce qui borne la profondeur des tendances a cinq runs environ.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


PIPELINE_STATS_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPORTS = PROJECT_ROOT / "exports" / "logs"

_HORODATAGE = re.compile(r"(\d{8})_(\d{6})")


def _quand(chemin: Path) -> str:
    """Horodatage lisible tire du nom de fichier, jamais de sa date disque."""
    trouve = _HORODATAGE.search(chemin.name)
    if not trouve:
        return "?"
    jour, heure = trouve.groups()
    return f"{jour[:4]}-{jour[4:6]}-{jour[6:]} {heure[:2]}:{heure[2:4]}"


def _cle_tri(chemin: Path) -> str:
    trouve = _HORODATAGE.search(chemin.name)
    return "".join(trouve.groups()) if trouve else ""


def _charger(chemin: Path):
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except Exception:
        return None


def entonnoir_par_run(dossier: Path | None = None) -> list[dict]:
    """Une ligne par run, du plus ancien au plus recent."""
    racine = dossier or EXPORTS
    if not racine.exists():
        return []

    files = sorted(racine.glob("application_queue_v1_*.json"), key=_cle_tri)
    pools = {_cle_tri(p): p
             for p in racine.glob("final_application_pool_v12_*.json")}
    pools_tries = sorted(pools)

    lignes = []
    for chemin in files:
        elements = _charger(chemin)
        if not isinstance(elements, list):
            continue

        statuts = Counter(x.get("queue_status") for x in elements
                          if isinstance(x, dict))
        verdicts = Counter(x.get("verdict") for x in elements
                           if isinstance(x, dict) and x.get("verdict"))

        # Le pool du meme run porte un horodatage legerement posterieur :
        # on prend le premier pool produit apres cette file.
        cle = _cle_tri(chemin)
        suivants = [k for k in pools_tries if k >= cle]
        pool_total = pool_apply = None
        if suivants:
            contenu = _charger(pools[suivants[0]])
            if isinstance(contenu, dict):
                pool = contenu.get("pool") or []
                pool_total = len(pool)
                pool_apply = sum(
                    1 for x in pool
                    if str(x.get("recommended_action_v12") or "")
                    .startswith("APPLY"))

        lignes.append({
            "quand": _quand(chemin),
            "file": len(elements),
            "pretes": statuts.get("READY_APPLY", 0),
            "a_tension": statuts.get("READY_STRETCH", 0),
            "a_verifier": statuts.get("VERIFY_FIRST", 0),
            "ecartees": statuts.get("EXCLUDED", 0),
            "pool": pool_total,
            "pool_apply": pool_apply,
            "verdicts": dict(verdicts),
        })
    return lignes


def evolution(lignes: list[dict]) -> dict:
    """Ecart entre le premier et le dernier run disponibles."""
    if len(lignes) < 2:
        return {}
    premier, dernier = lignes[0], lignes[-1]
    ecarts = {}
    for champ in ("file", "pretes", "a_tension", "a_verifier", "pool"):
        avant, apres = premier.get(champ), dernier.get(champ)
        if isinstance(avant, int) and isinstance(apres, int):
            ecarts[champ] = {"avant": avant, "apres": apres,
                             "delta": apres - avant}
    return {"depuis": premier["quand"], "jusqu_a": dernier["quand"],
            "runs": len(lignes), "ecarts": ecarts}


def rendement_des_sources(dossier: Path | None = None) -> list[dict]:
    """
    Sources qui produisent des offres PRETES, pas seulement des lignes.

    source_yield_audit compte ce qu'une source depose en base. Ce n'est pas
    la meme question : une source peut rapporter des centaines d'offres dont
    aucune ne franchit le tri, et une autre en rapporter dix dont la moitie
    finit dans le pool. La seconde vaut mieux.
    """
    racine = dossier or EXPORTS
    files = sorted(racine.glob("application_queue_v1_*.json"), key=_cle_tri)
    if not files:
        return []

    elements = _charger(files[-1])
    if not isinstance(elements, list):
        return []

    total = Counter()
    pretes = Counter()
    for item in elements:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "?")
        total[source] += 1
        if item.get("queue_status") == "READY_APPLY":
            pretes[source] += 1

    lignes = [
        {
            "source": source,
            "offres": nombre,
            "pretes": pretes.get(source, 0),
            "rendement": round(100.0 * pretes.get(source, 0) / nombre, 1),
        }
        for source, nombre in total.items()
    ]
    lignes.sort(key=lambda x: (-x["pretes"], -x["rendement"]))
    return lignes
