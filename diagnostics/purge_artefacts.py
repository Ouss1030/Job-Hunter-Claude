"""
JOB HUNTER BELGIUM
PURGE DES RAPPORTS D'AUDIT ACCUMULES - VERSION 1.0

    python -m diagnostics.purge_artefacts               (constat seul)
    python -m diagnostics.purge_artefacts --appliquer --garder 5

Le probleme
-----------
Chaque passage de run_all ecrit un rapport horodate par diagnostic. Au
10 septembre 2026, exports/logs contenait 2 163 fichiers pour 187 Mo, dont
152 exemplaires du meme rapport d'audit. Ces fichiers ne sont jamais relus :
ce sont des traces, et seule la plus recente sert encore a quelque chose.

La distinction qui compte
-------------------------
Deux familles de fichiers coexistent dans exports/logs, et les confondre
casserait le pipeline :

    ARTEFACTS   application_queue_v1_20260909_163259.json
                relus par latest_file() a l'etape suivante — INTOUCHABLES

    RAPPORTS    application_queue_v12_audit_20260909_163259.json
                ecrits, jamais relus — purgeables

Les deux partagent leur prefixe et leur horodatage. Seul le marqueur
« _audit_ », « _suite_ », « _replay_ » ou « _probe_ » les separe — c'est
exactement la distinction que delta_pattern_ok() teste deja ailleurs dans
les diagnostics, et pour la meme raison.

Par prudence, les familles d'artefacts du pipeline sont aussi listees
nommement : deux barrieres valent mieux qu'une quand se tromper coute un run.
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


PURGE_ARTEFACTS_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPORTS = PROJECT_ROOT / "exports" / "logs"

GARDER_PAR_FAMILLE = 5

# Marqueurs d'un rapport : ecrit pour etre lu par un humain, jamais par le
# pipeline.
_RAPPORT = re.compile(r"_(?:audit|suite|replay|probe|shadow|inventory)_",
                      re.I)

# Familles relues par latest_file() dans daily_run. Aucune ne doit etre
# touchee, meme si son nom contenait par accident un marqueur de rapport.
_ARTEFACTS_PROTEGES = (
    "job_hunter_main_v10_4_",
    "application_gate_v1_",
    "application_queue_v1_",
    "application_preparation_v1_",
    "job_refresh_v1_",
    "application_recheck_v1_",
    "final_application_pool_",
    "delta_tracker_v1_2",
    "chatgpt_handoff_",
    "lifecycle_",
    "daily_run_manifest",
    "daily_run_console",
)

_HORODATAGE = re.compile(r"_?\d{8}_\d{6}")


def famille(nom: str) -> str:
    """Nom de fichier prive de son horodatage et de son extension."""
    return _HORODATAGE.sub("", Path(nom).stem)


def est_purgeable(chemin: Path) -> bool:
    nom = chemin.name
    if any(nom.startswith(p) for p in _ARTEFACTS_PROTEGES):
        return False
    return bool(_RAPPORT.search(nom))


def recenser(garder: int) -> tuple[list[Path], dict]:
    if not EXPORTS.exists():
        return [], {}

    par_famille = defaultdict(list)
    for chemin in EXPORTS.iterdir():
        if chemin.is_file() and est_purgeable(chemin):
            par_famille[famille(chemin.name)].append(chemin)

    a_supprimer = []
    detail = {}
    for nom, fichiers in par_famille.items():
        # Le nom porte l'horodatage : trier dessus est plus fiable que la
        # date du fichier, qu'une copie ou une synchro peut avoir refaite.
        fichiers.sort(key=lambda p: p.name, reverse=True)
        surplus = fichiers[garder:]
        if surplus:
            a_supprimer.extend(surplus)
            detail[nom] = (len(fichiers), len(surplus),
                           sum(p.stat().st_size for p in surplus))
    return a_supprimer, detail


def main() -> None:
    parseur = argparse.ArgumentParser()
    parseur.add_argument("--appliquer", action="store_true")
    parseur.add_argument("--garder", type=int, default=GARDER_PAR_FAMILLE)
    args = parseur.parse_args()

    print("=" * 92)
    print(f"PURGE DES RAPPORTS D'AUDIT V{PURGE_ARTEFACTS_VERSION}")
    print("=" * 92)
    print()

    total_avant = sum(p.stat().st_size for p in EXPORTS.iterdir()
                      if p.is_file())
    nombre_avant = sum(1 for p in EXPORTS.iterdir() if p.is_file())
    print(f"exports/logs : {nombre_avant} fichiers, "
          f"{total_avant/1048576:.0f} Mo")
    print(f"Conserve les {args.garder} plus recents de chaque famille.")
    print()

    a_supprimer, detail = recenser(args.garder)
    poids = sum(taille for _, _, taille in detail.values())

    print(f"A SUPPRIMER : {len(a_supprimer)} fichiers, "
          f"{poids/1048576:.0f} Mo")
    print()
    print(f"{'FAMILLE':<52}{'TOTAL':>7}{'SUPPR.':>8}{'Mo':>7}")
    for nom, (total, surplus, taille) in sorted(
            detail.items(), key=lambda x: -x[1][2])[:15]:
        print(f"  {nom[:50]:<50}{total:>7}{surplus:>8}"
              f"{taille/1048576:>7.1f}")

    proteges = [p.name for p in EXPORTS.iterdir()
                if p.is_file() and not est_purgeable(p)]
    print()
    print(f"INTOUCHES : {len(proteges)} fichiers "
          f"(artefacts du pipeline et rapports recents)")

    if not args.appliquer:
        print()
        print("CONSTAT SEUL — rien n'a ete supprime.")
        print("Relancer avec --appliquer pour nettoyer.")
        return

    for chemin in a_supprimer:
        chemin.unlink(missing_ok=True)

    total_apres = sum(p.stat().st_size for p in EXPORTS.iterdir()
                      if p.is_file())
    nombre_apres = sum(1 for p in EXPORTS.iterdir() if p.is_file())
    print()
    print(f"AVANT : {nombre_avant:>5} fichiers  {total_avant/1048576:>7.0f} Mo")
    print(f"APRES : {nombre_apres:>5} fichiers  {total_apres/1048576:>7.0f} Mo")
    print(f"LIBERE: {(total_avant-total_apres)/1048576:>21.0f} Mo")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (EXPORTS / f"purge_artefacts_{stamp}.txt").write_text(
        "\n".join([f"PURGE DES RAPPORTS V{PURGE_ARTEFACTS_VERSION}",
                   "=" * 92,
                   f"Supprimes : {len(a_supprimer)} fichiers",
                   f"Libere : {(total_avant-total_apres)/1048576:.0f} Mo"]),
        encoding="utf-8")


if __name__ == "__main__":
    main()
