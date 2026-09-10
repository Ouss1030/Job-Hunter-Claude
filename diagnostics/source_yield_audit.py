"""
JOB HUNTER BELGIUM
AUDIT DE RENDEMENT DES SOURCES - VERSION 1.0

    python -m diagnostics.source_yield_audit

Pourquoi ce diagnostic
----------------------
Tous les autres audits vérifient qu'un composant fait ce qu'il annonce. Aucun
ne vérifie qu'il rapporte quelque chose. Une source peut être déclarée,
activée, câblée, compiler sans erreur, passer ses tests — et n'avoir jamais
écrit une seule ligne en base.

C'est un angle mort coûteux : le travail de développement se concentre sur les
connecteurs employeurs, et rien ne dit si ce travail produit des offres.

Ce que le diagnostic mesure
---------------------------
Il croise le registre des sources avec le contenu réel de la base :

    source | activée | offres historiques | offres actives | part du total

et signale toute source active n'ayant jamais rien produit.

Ce qu'il ne mesure pas
----------------------
Il constate l'absence, il ne l'explique pas. Savoir si une source muette
échoue en réseau, filtre trop large ou ne trouve simplement aucune cible
demande des compteurs à l'intérieur des collecteurs. C'est l'étape suivante ;
elle n'est pas dans ce fichier.

Lecture seule : la base est ouverte en mode `ro`, aucun fichier n'est écrit.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sources.registry import list_source_status


SOURCE_YIELD_AUDIT_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "database" / "jobs.db"

# En dessous de ce seuil, une source active est signalée comme marginale :
# elle produit, mais si peu que son coût de maintenance mérite un arbitrage.
SEUIL_MARGINAL = 5


# ------------------------------------------------------------------
# Alias entre clé de registre et nom stocké en base
# ------------------------------------------------------------------
# Le registre nomme une source, mais c'est le connecteur qui décide de la
# valeur écrite dans raw_jobs.source. Les deux peuvent diverger, et l'audit
# déclare alors muette une source qui produit.
#
# Cas mesuré le 9 septembre 2026 : WORKDAY_ATS, SUCCESSFACTORS_ATS et
# PHENOM_ATS ont rapporté 194, 119 et 82 offres avec status=OK, toutes
# enregistrées sous WORKDAY, SUCCESSFACTORS et PHENOM. L'audit les comptait
# muettes, et j'ai moi-même conclu à tort qu'elles n'avaient rien produit.
#
# Seuls les cas PROUVÉS figurent ici. KONVERT_STUDENT ressemble à un alias de
# KONVERT mais n'en est pas un : les deux ont tourné séparément dans le même
# run, l'une rendant 0 offre et l'autre 5. Les mapper aurait masqué une
# source réellement muette.
#
# L'alias est affiché dans le rapport : une correspondance invisible serait
# aussi trompeuse que l'absence de correspondance.
ALIAS_SOURCE_EN_BASE = {
    "WORKDAY_ATS": "WORKDAY",
    "SUCCESSFACTORS_ATS": "SUCCESSFACTORS",
    "PHENOM_ATS": "PHENOM",
}


def open_readonly(path: Path) -> sqlite3.Connection:
    """Ouvre la base en lecture seule : un audit ne modifie jamais l'état."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def source_counts(connection: sqlite3.Connection) -> dict[str, dict[str, int]]:
    rows = connection.execute(
        "SELECT source, "
        "       COUNT(*) AS total, "
        "       SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS actives "
        "FROM raw_jobs GROUP BY source"
    ).fetchall()
    return {r[0]: {"total": r[1], "actives": r[2] or 0} for r in rows if r[0]}


def build_report(connection: sqlite3.Connection) -> tuple[list[dict], dict]:
    comptes = source_counts(connection)
    total_actives = sum(c["actives"] for c in comptes.values()) or 1

    lignes = []
    for spec in list_source_status():
        cle = spec["key"]
        # La clé de registre peut différer du nom écrit en base.
        nom_base = ALIAS_SOURCE_EN_BASE.get(cle, cle)
        compte = comptes.get(nom_base, {"total": 0, "actives": 0})

        if not spec["active"]:
            etat = "DESACTIVEE"
        elif compte["total"] == 0:
            etat = "JAMAIS EN BASE"
        elif compte["actives"] == 0:
            etat = "PLUS D'OFFRE ACTIVE"
        elif compte["actives"] < SEUIL_MARGINAL:
            etat = "MARGINALE"
        else:
            etat = "OK"

        lignes.append({
            "key": cle,
            "alias_base": nom_base if nom_base != cle else "",
            "source": spec["source"],
            "active": spec["active"],
            "total": compte["total"],
            "actives": compte["actives"],
            "part": 100.0 * compte["actives"] / total_actives,
            "etat": etat,
        })

    lignes.sort(key=lambda x: (-x["actives"], x["key"]))

    actives = [x for x in lignes if x["active"]]
    resume = {
        "declarees": len(lignes),
        "actives": len(actives),
        "productives": sum(1 for x in actives if x["actives"] > 0),
        "muettes": [x["key"] for x in actives if x["total"] == 0],
        "marginales": [x["key"] for x in actives if x["etat"] == "MARGINALE"],
        "offres_actives": total_actives,
    }
    return lignes, resume


def main() -> None:
    print("=" * 92)
    print(f"AUDIT DE RENDEMENT DES SOURCES V{SOURCE_YIELD_AUDIT_VERSION}")
    print("=" * 92)
    print()

    if not DB_PATH.exists():
        raise SystemExit(f"[FAIL] Base introuvable : {DB_PATH}")

    connection = open_readonly(DB_PATH)
    try:
        lignes, resume = build_report(connection)
    finally:
        connection.close()

    print(f"{'SOURCE':<24}{'ACTIVE':<9}{'HIST.':>8}{'ACTIVES':>9}{'PART':>8}  ÉTAT")
    print("-" * 92)
    for x in lignes:
        etiquette = x["key"]
        if x.get("alias_base"):
            etiquette = f"{x['key']} →{x['alias_base']}"
        print(f"{etiquette:<24}{('oui' if x['active'] else 'non'):<9}"
              f"{x['total']:>8}{x['actives']:>9}{x['part']:>7.1f}%  {x['etat']}")

    print()
    print("RÉSUMÉ")
    print("-" * 92)
    print(f"Sources déclarées                 : {resume['declarees']}")
    print(f"Sources actives                   : {resume['actives']}")
    print(f"Sources actives productives       : {resume['productives']}")
    print(f"Sources actives jamais en base    : {len(resume['muettes'])}")
    print(f"Offres actives en base            : {resume['offres_actives']}")

    # Une poignée de sources porte souvent l'essentiel du volume. Le dire
    # évite de confondre « beaucoup de sources » et « beaucoup d'offres ».
    productives = [x for x in lignes if x["actives"] > 0]
    tete = productives[:5]
    if tete:
        print()
        print(f"Part des 5 premières sources      : "
              f"{sum(x['part'] for x in tete):.1f} %  "
              f"({', '.join(x['key'] for x in tete)})")
        reste = productives[5:]
        if reste:
            print(f"Part des {len(reste):>2} suivantes            : "
                  f"{sum(x['part'] for x in reste):.1f} %")

    if resume["muettes"]:
        print()
        print("ALERTE - SOURCES ACTIVES SANS AUCUNE LIGNE HISTORIQUE")
        for cle in resume["muettes"]:
            print(f"  - {cle}")

    if resume["marginales"]:
        print()
        print(f"SOURCES MARGINALES (moins de {SEUIL_MARGINAL} offres actives)")
        for cle in resume["marginales"]:
            print(f"  - {cle}")

    print()
    print("NOTE")
    print("Ce diagnostic mesure le rendement en base. Il ne distingue pas encore")
    print("réseau / géographie / langue / non-cible : cela demande des compteurs")
    print("à l'intérieur des collecteurs.")


if __name__ == "__main__":
    main()
