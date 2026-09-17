"""
JOB HUNTER BELGIUM
BCE / KBO OPEN DATA - GRAINES DE DECOUVERTE - VERSION 1.1

    python -m sources.bce_seeds_v1 chemin/vers/KboOpenData_XXXX_Full.zip
    python -m sources.bce_seeds_v1 chemin/vers/KboOpenData_XXXX_Full.zip --nace 21,20,72,86,71.2 --decouvrir

D'ou vient le fichier
---------------------
La Banque-Carrefour des Entreprises publie un extrait Open Data mensuel
(https://kbopub.economie.fgov.be/kbo-open-data) : un ZIP d'environ 500 Mo
avec toutes les entreprises belges. Il faut creer un compte gratuit sur le
site du SPF Economie, puis telecharger le "Full" du mois. JobHunter ne
peut pas le faire a votre place — c'est une inscription personnelle.

Ce que l'outil en fait
----------------------
Il lit le ZIP sans le decompresser sur disque et croise trois tables :

    enterprise.csv    numero, statut (AC = active), forme juridique
    activity.csv      codes NACE 2008 de l'activite (principale ou non)
    contact.csv       contacts declares : TEL, EMAIL, WEB  <- le site web
    denomination.csv  nom (langue FR/NL)

puis retient les entreprises ACTIVES dont l'activite tombe dans les codes
NACE demandes ET qui ont declare un site web. Chaque site devient une
graine pour sources/source_discovery_v1.py, qui trouve la page carriere,
l'ATS et la voie publique. C'est ainsi que la BCE devient un multiplicateur
de couverture et non une table inerte.

Codes NACE utiles pour ce projet (2008, prefixes) :
    21     industrie pharmaceutique      20     industrie chimique
    72     recherche-developpement       71.2   analyses, essais, laboratoires
    86     activites hospitalieres       62/63  informatique, donnees
    10/11  agroalimentaire               78     agences de placement
    85.4   enseignement superieur        84     administration publique

Volume : la BCE compte ~1,9 million d'entites. Avec 21,20,72,71.2,86 et un
site web declare, on obtient quelques milliers de domaines : la campagne de
decouverte se lance alors par tranches (--limite N, --offset N).

V1.1 (17/09/2026)
    --etablissements   l'activite d'une unite d'etablissement (numero 2.xxx)
                       compte pour son entreprise (establishment.csv) : un
                       groupe dont le siege est « holding » mais l'usine
                       « industrie pharmaceutique » est retenu
    --personnes-morales ecarte les personnes physiques (TypeOfEnterprise 1 :
                       independants, freelances — la moitie des NACE 62/63)
    --sauf-deja-vus    ecarte les domaines deja passes au moteur (toutes les
                       campagnes exports/logs/discovery_*/SOURCE_RESULTS.jsonl)
                       et ceux du registre : une tranche 2 ne refait pas la 1

Tranche 1 (16/09/2026) : NACE 21,20,72,71.2,86 -> 2 390 sites, 1 215 passes,
25 sources actives (2 %). Le goulot est le champ « site web » : sur les
3 547 employeurs qui publient sur le Forem et Actiris, 1 898 sont dans la
BCE mais 154 ont declare un site.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit


BCE_SEEDS_VERSION = "1.1"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SORTIE = PROJECT_ROOT / "config" / "discovery_seeds_bce.json"
NACE_DEFAUT = "21,20,72,71.2,86"


def _ouvrir_csv(zf: zipfile.ZipFile, nom: str):
    """Trouve un CSV dans le ZIP sans se soucier de la casse ni du dossier."""
    for info in zf.infolist():
        if info.filename.lower().rsplit("/", 1)[-1] == nom.lower():
            return io.TextIOWrapper(zf.open(info), encoding="utf-8", errors="replace", newline="")
    raise FileNotFoundError(f"{nom} absent du ZIP")


def _domaine(valeur: str) -> str:
    v = (valeur or "").strip().lower()
    if not v:
        return ""
    if not v.startswith(("http://", "https://")):
        v = "https://" + v
    try:
        h = urlsplit(v).netloc.removeprefix("www.")
    except Exception:
        return ""
    return h if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", h) else ""


def domaines_deja_vus() -> set[str]:
    """Domaines deja passes au moteur (campagnes precedentes) ou deja au registre."""
    vus: set[str] = set()
    for chemin in (PROJECT_ROOT / "exports" / "logs").glob("discovery_*/SOURCE_RESULTS.jsonl"):
        try:
            lignes = chemin.read_text(encoding="utf-8").split("\n")
        except OSError:
            continue
        for ligne in lignes:
            if not ligne.strip():
                continue
            try:
                e = json.loads(ligne).get("entree") or ""
            except ValueError:
                continue
            d = _domaine(e) if not e.startswith("http") else _domaine(urlsplit(e).netloc)
            if d:
                vus.add(d)
    try:
        from sources.ats_employers_v2 import charger
        for e in charger()["employers"]:
            for v in (e.get("career_url"), str(e.get("identifier"))):
                d = _domaine(str(v or "")) if str(v or "").startswith("http") else _domaine(str(v or ""))
                if d:
                    vus.add(d)
    except Exception:
        pass
    return vus


def extraire(chemin_zip: Path, nace: list[str], limite: int | None = None, verbose: bool = True,
             etablissements: bool = False, exclure: set[str] | None = None,
             personnes_morales: bool = False) -> list[dict]:
    nace = [c.replace(".", "") for c in nace]
    exclure = exclure or set()
    with zipfile.ZipFile(chemin_zip) as zf:
        # 1) entites dont l'activite correspond
        cibles: dict[str, str] = {}
        etabs: dict[str, str] = {}
        with _ouvrir_csv(zf, "activity.csv") as f:
            for row in csv.DictReader(f):
                code = str(row.get("NaceCode") or "").replace(".", "")
                if any(code.startswith(c) for c in nace):
                    num = row.get("EntityNumber") or row.get("EnterpriseNumber") or ""
                    # 0xxx.xxx.xxx = entreprise ; 2.xxx.xxx.xxx = unite d'etablissement.
                    if num.startswith("2."):
                        if etablissements:
                            etabs.setdefault(num, code)
                        continue
                    cibles.setdefault(num, code)
        if etabs:
            with _ouvrir_csv(zf, "establishment.csv") as f:
                for row in csv.DictReader(f):
                    code = etabs.get(row.get("EstablishmentNumber") or "")
                    if code:
                        cibles.setdefault(row.get("EnterpriseNumber") or "", code)
        if verbose:
            print(f"  activites NACE {nace} : {len(cibles)} entites" + (f" (dont via {len(etabs)} unites d'etablissement)" if etabs else ""))
        # 2) sites web declares
        sites: dict[str, str] = {}
        with _ouvrir_csv(zf, "contact.csv") as f:
            for row in csv.DictReader(f):
                if str(row.get("ContactType") or "").upper() != "WEB":
                    continue
                ent = row.get("EntityNumber") or ""
                if ent in cibles and ent not in sites:
                    d = _domaine(row.get("Value") or "")
                    if d:
                        sites[ent] = d
        if verbose:
            print(f"  avec site web declare : {len(sites)}")
        # 3) actives seulement
        actives: set[str] = set()
        with _ouvrir_csv(zf, "enterprise.csv") as f:
            for row in csv.DictReader(f):
                if row.get("EnterpriseNumber") in sites and str(row.get("Status") or "").upper() == "AC":
                    # TypeOfEnterprise 1 = personne physique (independant, freelance), 2 = personne morale
                    if personnes_morales and str(row.get("TypeOfEnterprise") or "") == "1":
                        continue
                    actives.add(row["EnterpriseNumber"])
        # 4) noms
        noms: dict[str, str] = {}
        with _ouvrir_csv(zf, "denomination.csv") as f:
            for row in csv.DictReader(f):
                num = row.get("EntityNumber") or ""
                if num in actives and (num not in noms or str(row.get("TypeOfDenomination")) == "001"):
                    noms[num] = row.get("Denomination") or ""
    vus: set[str] = set(exclure)
    sortie = []
    for num in sorted(actives):
        d = sites[num]
        if d in vus:
            continue
        vus.add(d)
        sortie.append({"domaine": d, "label": (noms.get(num) or d.split(".")[0]).title()[:60],
                       "bce": num, "nace": cibles.get(num), "discovered_by": f"bce:{cibles.get(num)}"})
        if limite and len(sortie) >= limite:
            break
    sortie.sort(key=lambda g: (g["nace"] or "", g["domaine"]))
    if verbose:
        print(f"  entreprises actives, NACE cible, site web : {len(sortie)} domaines distincts")
    return sortie


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("zip", help="KboOpenData_..._Full.zip telecharge sur kbopub.economie.fgov.be")
    p.add_argument("--nace", default=NACE_DEFAUT, help=f"prefixes NACE separes par des virgules (defaut {NACE_DEFAUT})")
    p.add_argument("--limite", type=int, default=None, help="au plus N graines")
    p.add_argument("--offset", type=int, default=0, help="sauter les N premieres graines (campagne par tranches)")
    p.add_argument("--decouvrir", action="store_true", help="passer ensuite les graines au moteur de decouverte")
    p.add_argument("--etablissements", action="store_true", help="l'activite d'une unite d'etablissement compte pour son entreprise")
    p.add_argument("--sauf-deja-vus", action="store_true", help="ecarter les domaines deja passes au moteur ou deja au registre")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--personnes-morales", action="store_true", help="ecarter les personnes physiques (independants, freelances)")
    args = p.parse_args()
    chemin = Path(args.zip)
    if not chemin.exists():
        print(f"[FAIL] fichier introuvable : {chemin}")
        return 1
    print("=" * 76)
    print(f"BCE / KBO OPEN DATA -> GRAINES V{BCE_SEEDS_VERSION}")
    print("=" * 76)
    exclure = domaines_deja_vus() if args.sauf_deja_vus else set()
    if exclure:
        print(f"  domaines deja vus (campagnes + registre) : {len(exclure)}")
    graines = extraire(chemin, [c.strip() for c in args.nace.split(",") if c.strip()], verbose=True,
                       etablissements=args.etablissements, exclure=exclure, personnes_morales=args.personnes_morales)
    SORTIE.write_text(json.dumps({
        "schema_version": BCE_SEEDS_VERSION, "source": chemin.name, "nace": args.nace,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "groups": {"bce": [{k: g[k] for k in ("domaine", "label", "bce", "nace")} for g in graines]},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  -> {SORTIE}")
    if args.decouvrir:
        tranche = graines[args.offset: (args.offset + args.limite) if args.limite else None]
        from sources.source_discovery_v1 import decouvrir
        decouvrir(tranche, dossier=PROJECT_ROOT / "exports" / "logs" /
                  f"discovery_bce_{datetime.now().strftime('%Y%m%d_%H%M%S')}", deviner=False, workers=args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
