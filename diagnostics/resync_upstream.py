"""
JOB HUNTER BELGIUM
RESYNCHRONISATION DEPUIS LE PROJET PRINCIPAL - VERSION 1.0

    python -m diagnostics.resync_upstream                 (simulation)
    python -m diagnostics.resync_upstream --appliquer
    python -m diagnostics.resync_upstream --source "C:/autre/chemin"

Pourquoi cet outil
------------------
Le projet principal evolue plusieurs fois par jour : 84 sources le 4
septembre, 160 le 6. Un portage fait en une passe est perime en vingt-quatre
heures.

Cet outil compare les deux dossiers, montre ce qui a change en amont, et
rejoue le delta ici — sans effacer les ajouts locaux ni les correctifs
appliques.

Trois categories
----------------
IDENTIQUE   rien a faire
AMONT       present en amont, absent ou different ici -> a reprendre
LOCAL       present seulement ici -> a conserver

Fichiers proteges
-----------------
Certains fichiers ne doivent JAMAIS etre ecrases par l'amont, soit parce que
la version locale est plus riche, soit parce qu'elle porte un correctif que
l'amont n'a pas. Ils sont listes dans PROTEGES avec la raison.

C'est le coeur de l'outil : une resynchronisation qui ecrase les correctifs
les reintroduirait a chaque fois.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path


RESYNC_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_UPSTREAM = Path(r"C:\Users\Aharr\Desktop\JobHunter")
LOG_DIR = PROJECT_ROOT / "exports" / "logs"

# Dossiers compares. Les donnees (logs, exports, database, backups) sont
# exclues : ce sont des etats locaux, pas du code.
DOSSIERS = ("sources", "config", "matching", "applications",
            "interface", "database")
RACINE = ("main.py", "daily_run.py", "jobhunter_ui.py")

IGNORER = {"__pycache__", ".git", ".venv", "logs", "exports", "backups"}


# ---------------------------------------------------------------------------
# Fichiers proteges : jamais ecrases par l'amont
# ---------------------------------------------------------------------------
PROTEGES: dict[str, str] = {
    "config/profile.py":
        "version locale plus riche (concepts et termes ajoutes)",
    "config/smartrecruiters_sources.py":
        "version locale plus riche (5 employeurs contre 3)",
    "config/candidate_truth.py":
        "verite candidat locale (niveau de neerlandais)",
    "sources/registry.py":
        "porte l'extension locale en fin de fichier (connecteurs ATS + VDAB)",
    "sources/registry_ats_v1.py":
        "extension locale : connecteurs ATS publics et VDAB",
    "sources/vdab.py":
        "connecteur local, absent en amont",
    "sources/workday_ats_v1.py":
        "connecteur ATS local, renomme pour ne pas heurter le moteur amont",
    "sources/successfactors_ats_v1.py":
        "connecteur ATS local, renomme",
    "sources/phenom_ats_v1.py":
        "connecteur ATS local, renomme",
    "sources/location_belgium.py":
        "module de geographie local, distinct de sources/belgium_locations.py",
    "matching/application_gate_v133.py":
        "overlay Gate 1.3.5 local",
    "matching/preselection_rescue.py":
        "seconde porte d'enrichissement locale",
    "matching/verdict.py":
        "moteur de verdict local, absent en amont",
    "matching/piste_accessible.py":
        "classement en pistes local, absent en amont",
    "matching/basic_matcher_v51.py":
        "porte deux correctifs locaux : lecture de detail_matching_text et "
        "normalisation de l'ecriture inclusive",
    "daily_run.py":
        "porte la comparaison de version at_least() que l'amont n'a pas "
        "(l'amont compare par egalite stricte)",
}


def _hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _fichiers(racine: Path) -> dict[str, Path]:
    trouves: dict[str, Path] = {}
    for nom in RACINE:
        p = racine / nom
        if p.is_file():
            trouves[nom] = p
    for dossier in DOSSIERS:
        base = racine / dossier
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if any(x in p.parts for x in IGNORER):
                continue
            trouves[p.relative_to(racine).as_posix()] = p
        for p in base.glob("*.json"):
            trouves[p.relative_to(racine).as_posix()] = p
    return trouves


def comparer(upstream: Path, local: Path) -> dict:
    amont, ici = _fichiers(upstream), _fichiers(local)
    identiques, nouveaux, modifies, locaux, proteges = [], [], [], [], []

    for rel, p_amont in sorted(amont.items()):
        if rel in PROTEGES:
            proteges.append(rel)
            continue
        p_ici = ici.get(rel)
        if p_ici is None:
            nouveaux.append(rel)
        elif _hash(p_amont) != _hash(p_ici):
            modifies.append(rel)
        else:
            identiques.append(rel)

    for rel in sorted(ici):
        if rel not in amont and rel not in PROTEGES:
            locaux.append(rel)

    return {
        "identiques": identiques, "nouveaux": nouveaux,
        "modifies": modifies, "locaux": locaux, "proteges": proteges,
    }


def appliquer(upstream: Path, local: Path, plan: dict) -> dict:
    """Rejoue le delta. Les fichiers remplaces partent en quarantaine."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    quarantaine = local / f"_resync_avant_{stamp}"
    repris, sauvegardes = [], 0

    for rel in plan["nouveaux"] + plan["modifies"]:
        src, dst = upstream / rel, local / rel
        if dst.exists():
            garde = quarantaine / rel
            garde.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, garde)
            sauvegardes += 1
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        repris.append(rel)

    if repris:
        quarantaine.mkdir(parents=True, exist_ok=True)
        (quarantaine / "MANIFESTE.json").write_text(
            json.dumps({"date": datetime.now().isoformat(timespec="seconds"),
                        "amont": str(upstream), "repris": repris},
                       ensure_ascii=False, indent=2), encoding="utf-8")

    return {"repris": len(repris), "sauvegardes": sauvegardes,
            "quarantaine": str(quarantaine) if repris else ""}


def _bloc(titre: str, items: list[str], limite: int = 25) -> None:
    print()
    print(f"{titre} : {len(items)}")
    print("-" * 78)
    for rel in items[:limite]:
        print(f"  {rel}")
    if len(items) > limite:
        print(f"  ... et {len(items) - limite} autres")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Resynchronisation depuis le projet principal")
    parser.add_argument("--source", type=Path, default=DEFAULT_UPSTREAM)
    parser.add_argument("--appliquer", action="store_true",
                        help="Rejoue reellement le delta (defaut : simulation)")
    args = parser.parse_args(argv)

    print("=" * 78)
    print(f"RESYNCHRONISATION V{RESYNC_VERSION}"
          f"{'' if args.appliquer else '  (SIMULATION)'}")
    print("=" * 78)
    print(f"  amont : {args.source}")
    print(f"  ici   : {PROJECT_ROOT}")

    if not args.source.is_dir():
        print(f"\n[FAIL] Dossier amont introuvable : {args.source}")
        return 1

    plan = comparer(args.source, PROJECT_ROOT)

    print()
    print(f"  identiques        : {len(plan['identiques'])}")
    print(f"  nouveaux en amont : {len(plan['nouveaux'])}")
    print(f"  modifies en amont : {len(plan['modifies'])}")
    print(f"  locaux conserves  : {len(plan['locaux'])}")
    print(f"  proteges          : {len(plan['proteges'])}")

    _bloc("NOUVEAUX EN AMONT — seront ajoutes", plan["nouveaux"])
    _bloc("MODIFIES EN AMONT — seront remplaces", plan["modifies"])
    _bloc("LOCAUX — conserves, absents en amont", plan["locaux"])

    print()
    print(f"PROTEGES — jamais ecrases : {len(plan['proteges'])}")
    print("-" * 78)
    for rel in plan["proteges"]:
        print(f"  {rel}")
        print(f"      {PROTEGES[rel]}")

    if not args.appliquer:
        print()
        print("Simulation uniquement. Pour appliquer :")
        print("    python -m diagnostics.resync_upstream --appliquer")
        print()
        print("Ensuite, imperativement :")
        print("    python -m diagnostics.run_all")
        print("    python daily_run.py --check")
        return 0

    resultat = appliquer(args.source, PROJECT_ROOT, plan)
    print()
    print(f"  fichiers repris   : {resultat['repris']}")
    print(f"  sauvegardes       : {resultat['sauvegardes']}")
    if resultat["quarantaine"]:
        print(f"  versions d'avant  : {Path(resultat['quarantaine']).name}")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"resync_upstream_{stamp}.json").write_text(
        json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                    "amont": str(args.source), "plan": {
                        k: len(v) for k, v in plan.items()},
                    "resultat": resultat}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    print()
    print("A LANCER MAINTENANT :")
    print("    python -m diagnostics.run_all")
    print("    python daily_run.py --check")
    print()
    print("Si un test casse, les versions d'avant sont dans la quarantaine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
