"""
JOB HUNTER BELGIUM
EMPLOYEURS QUI RECRUTENT (FOREM / ACTIRIS) -> GRAINES DE DECOUVERTE - VERSION 1.0

    python -m sources.employeurs_actifs_seeds_v1                # ecrit config/discovery_seeds_employeurs_actifs.json
    python -m sources.employeurs_actifs_seeds_v1 --min-offres 3 --decouvrir

L'idee : les 3 547 employeurs qui publient en ce moment sur le Forem et
Actiris sont, par definition, ceux qui recrutent. Leur site carriere porte
souvent des offres qu'ils ne republient pas (ou pas encore) sur les
portails publics. La BCE ne donne leur site que pour 154 d'entre eux :
on le devine (sources/annuaires_seeds_v1.deviner_domaine — www.<nom>.be,
.com, .eu, accepte seulement si la page reprend un mot fort du nom), puis
le moteur de decouverte trouve la page carriere, l'ATS et la voie publique.

Ecartes : « OFFRE D'UNE AUTRE REGION » (Forem via Actiris), les noms trop
courts, les domaines deja passes au moteur ou deja au registre.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests

from sources.annuaires_seeds_v1 import deviner_domaine


EMPLOYEURS_ACTIFS_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SORTIE = PROJECT_ROOT / "config" / "discovery_seeds_employeurs_actifs.json"
DB_PATH = PROJECT_ROOT / "database" / "jobs.db"
_RE_FORMES = re.compile(r"\b(?:sa|nv|sprl|bvba|srl|bv|scrl|cvba|asbl|vzw|sc|se|scs|snc|nv/sa|sa/nv|bvba/sprl)\b", re.I)
_EXCLUS = ("offre d'une autre region", "offre d une autre region")


def _cle(nom: str) -> str:
    n = unicodedata.normalize("NFKD", str(nom or "")).encode("ascii", "ignore").decode().lower()
    n = _RE_FORMES.sub(" ", n)
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def employeurs(min_offres: int = 3, sources=("FOREM", "ACTIRIS")) -> list[tuple[str, int]]:
    """(nom d'affichage, nombre d'offres actives) pour chaque employeur distinct."""
    con = sqlite3.connect(DB_PATH)
    comptes: dict[str, list] = {}
    q = f"select company, count(*) from raw_jobs where is_active=1 and source in ({','.join('?' * len(sources))}) " \
        "and company is not null group by company"
    for nom, n in con.execute(q, sources):
        k = _cle(nom)
        if len(k) < 4 or any(x in k for x in _EXCLUS):
            continue
        if k not in comptes:
            comptes[k] = [str(nom).strip(), 0]
        comptes[k][1] += n
    con.close()
    lignes = [(v[0], v[1]) for v in comptes.values() if v[1] >= min_offres]
    lignes.sort(key=lambda x: -x[1])
    return lignes


def graines(min_offres: int = 3, workers: int = 4, verbose: bool = True, limite: int | None = None) -> list[dict]:
    from sources.bce_seeds_v1 import domaines_deja_vus
    deja = domaines_deja_vus()
    lignes = employeurs(min_offres)[:limite]
    if verbose:
        print(f"  employeurs avec >= {min_offres} offres : {len(lignes)} ; domaines deja vus : {len(deja)}")
    session = requests.Session()

    def un(ligne):
        nom, n = ligne
        try:
            return nom, n, deviner_domaine(nom, session)
        except Exception:
            return nom, n, None

    sortie, vus = [], set()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (nom, n, d) in enumerate(pool.map(un, lignes), 1):
            if verbose:
                print(f"  [{i:>4}/{len(lignes)}] {nom[:38]:<38} {n:>4} offres -> {d or '-'}")
            if not d or d in vus or any(d.endswith(k) for k in deja):
                continue
            vus.add(d)
            sortie.append({"domaine": d, "label": nom[:60], "offres_portails": n, "discovered_by": "employeur-actif"})
    return sortie


def ecrire(candidats: list[dict]) -> Path:
    SORTIE.write_text(json.dumps({
        "schema_version": EMPLOYEURS_ACTIFS_VERSION, "generated_at": datetime.now().isoformat(timespec="seconds"),
        "purpose": "Employeurs qui publient sur le Forem/Actiris, site devine, a passer au moteur de decouverte.",
        "groups": {"employeurs_actifs": [{k: c[k] for k in ("domaine", "label", "offres_portails")} for c in candidats]},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return SORTIE


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--min-offres", type=int, default=3)
    p.add_argument("--limite", type=int, default=None)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--decouvrir", action="store_true")
    p.add_argument("--depuis-fichier", action="store_true",
                   help="reprendre les graines deja devinees (config/discovery_seeds_employeurs_actifs.json) sans redeviner")
    args = p.parse_args()
    print("=" * 76)
    print(f"EMPLOYEURS ACTIFS FOREM/ACTIRIS -> GRAINES V{EMPLOYEURS_ACTIFS_VERSION}")
    print("=" * 76)
    if args.depuis_fichier and SORTIE.exists():
        from sources.bce_seeds_v1 import domaines_deja_vus
        deja = domaines_deja_vus()
        data = json.loads(SORTIE.read_text(encoding="utf-8"))
        candidats = [{**c, "discovered_by": "employeur-actif"} for c in data["groups"]["employeurs_actifs"]
                     if not any(c["domaine"].endswith(k) for k in deja)]
        print(f"  graines reprises du fichier : {len(candidats)} (deja vus ecartes)")
        chemin = SORTIE
    else:
        candidats = graines(args.min_offres, workers=args.workers, limite=args.limite)
        chemin = ecrire(candidats)
    print(f"\n{len(candidats)} graines -> {chemin}")
    if args.decouvrir and candidats:
        from sources.source_discovery_v1 import decouvrir
        decouvrir(candidats, dossier=PROJECT_ROOT / "exports" / "logs" /
                  f"discovery_employeurs_actifs_{datetime.now().strftime('%Y%m%d_%H%M%S')}", deviner=False, workers=args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
