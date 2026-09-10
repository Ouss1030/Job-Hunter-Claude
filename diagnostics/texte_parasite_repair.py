"""
JOB HUNTER BELGIUM
NETTOYAGE DES TEXTES PARASITES - VERSION 1.0

    python -m diagnostics.texte_parasite_repair            (constat seul)
    python -m diagnostics.texte_parasite_repair --appliquer

Pourquoi
--------
matching/texte_parasite.py empeche desormais un bloc « offres similaires »
d'etre enregistre comme description. Il ne defait pas ce qui a deja ete
ecrit : au 9 septembre 2026, 218 offres Jobat actives portaient une liste
d'autres postes a la place de leur propre texte, dans detail_matching_text
ET dans description.

Ce que le nettoyage fait
------------------------
Il efface les deux champs et nomme l'echec dans detail_enrichment_error. Il
n'essaie pas de sauver un morceau de texte : la mesure a montre que 198 des
218 textes commencent par le titre d'une AUTRE offre. Il n'y a pas de debut
sain a conserver.

Une offre nettoyee retombe sur son titre seul. C'est peu — mais un titre
seul se lit comme peu d'information, tandis qu'une liste de metiers etrangers
se lit comme beaucoup d'information fausse, et c'est elle qui faisait scorer
l'offre sur des metiers qu'elle ne propose pas.

Par defaut ce module ne modifie RIEN : il faut --appliquer.
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from matching.texte_parasite import (
    TEXTE_PARASITE_VERSION,
    raison_parasite,
)


REPAIR_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "database" / "jobs.db"
LOG_DIR = PROJECT_ROOT / "exports" / "logs"


def recenser(connection: sqlite3.Connection) -> list[tuple]:
    """Lignes dont le texte enrichi est un bloc de navigation."""
    rows = connection.execute(
        "SELECT id, source, title, detail_matching_text, description "
        "FROM raw_jobs "
        "WHERE detail_matching_text IS NOT NULL "
        "  AND TRIM(detail_matching_text) <> ''"
    ).fetchall()

    touchees = []
    for ident, source, titre, texte, description in rows:
        raison = raison_parasite(texte)
        if raison:
            touchees.append((ident, source, titre, raison,
                             bool(raison_parasite(description))))
    return touchees


def appliquer(connection: sqlite3.Connection, touchees: list[tuple]) -> int:
    """Efface les textes parasites et nomme l'echec."""
    for ident, _source, _titre, raison, description_aussi in touchees:
        if description_aussi:
            connection.execute(
                "UPDATE raw_jobs SET detail_matching_text = NULL, "
                "detail_matching_text_length = 0, "
                "detail_enrichment_success = 0, "
                "detail_enrichment_error = ?, "
                "description = NULL WHERE id = ?",
                (raison, ident))
        else:
            # La description d'origine est saine : on ne touche qu'au texte
            # enrichi. Effacer une description valable serait une perte
            # seche, et rien ici ne l'exige.
            connection.execute(
                "UPDATE raw_jobs SET detail_matching_text = NULL, "
                "detail_matching_text_length = 0, "
                "detail_enrichment_success = 0, "
                "detail_enrichment_error = ? WHERE id = ?",
                (raison, ident))
    connection.commit()
    return len(touchees)


def main() -> None:
    parseur = argparse.ArgumentParser()
    parseur.add_argument("--appliquer", action="store_true",
                         help="ecrit reellement en base")
    args = parseur.parse_args()

    print("=" * 92)
    print(f"NETTOYAGE DES TEXTES PARASITES V{REPAIR_VERSION} "
          f"(detecteur V{TEXTE_PARASITE_VERSION})")
    print("=" * 92)
    print()

    if not DB_PATH.exists():
        raise SystemExit(f"[FAIL] Base introuvable : {DB_PATH}")

    mode = "" if args.appliquer else "?mode=ro"
    connection = sqlite3.connect(f"{DB_PATH.resolve().as_uri()}{mode}",
                                 uri=True)
    try:
        touchees = recenser(connection)

        par_source = Counter(x[1] for x in touchees)
        par_raison = Counter(x[3].split(" :")[0] for x in touchees)
        description_aussi = sum(1 for x in touchees if x[4])

        print(f"Lignes portant un texte parasite : {len(touchees)}")
        print(f"  dont description egalement contaminee : {description_aussi}")
        print()
        print("PAR SOURCE")
        for source, n in par_source.most_common():
            print(f"  {source:<24}{n:>6}")
        print()
        print("PAR MOTIF")
        for raison, n in par_raison.most_common():
            print(f"  {raison:<40}{n:>6}")

        print()
        print("EXEMPLES")
        for ident, source, titre, raison, _ in touchees[:5]:
            print(f"  [{source}] {str(titre)[:52]:<52} {raison}")

        if not args.appliquer:
            print()
            print("CONSTAT SEUL — rien n'a ete modifie.")
            print("Relancer avec --appliquer pour nettoyer.")
            return

        nombre = appliquer(connection, touchees)
        print()
        print(f"NETTOYE : {nombre} lignes")

        restantes = recenser(connection)
        print(f"Restantes apres nettoyage : {len(restantes)}")
        if restantes:
            raise SystemExit("[FAIL] Des textes parasites subsistent.")
    finally:
        connection.close()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"texte_parasite_repair_{stamp}.txt").write_text(
        "\n".join([
            f"NETTOYAGE DES TEXTES PARASITES V{REPAIR_VERSION}",
            "=" * 92,
            f"Lignes nettoyees : {len(touchees)}",
            f"Descriptions contaminees : {description_aussi}",
            "Par source : " + repr(dict(par_source)),
        ]),
        encoding="utf-8")


if __name__ == "__main__":
    main()
