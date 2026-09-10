"""
JOB HUNTER BELGIUM
SUITE DE DIAGNOSTICS - RUN ALL

Une seule commande pour savoir si l'installation est saine.

    python -m diagnostics.run_all
    python -m diagnostics.run_all --list
    python -m diagnostics.run_all --include-live

Pourquoi ce fichier
-------------------
Le dossier diagnostics/ contient une trentaine de scripts accumulés au fil
des versions. Trois catégories s'y mélangent :

  - ceux qui valident le code réellement installé ;
  - ceux qui validaient une version remplacée depuis, et qui échouent donc
    normalement — les laisser dans un balayage global fait croire à une
    installation cassée ;
  - ceux qui appellent le réseau, qu'on ne veut pas lancer par réflexe.

Sans cette séparation, « lancer les diagnostics » produit du rouge attendu
au milieu du rouge réel, et plus personne ne lit le résultat.

Règle de maintenance
--------------------
Quand un module passe à une version supérieure et qu'un nouvel audit le
couvre, déplacer l'ancien de CURRENT vers SUPERSEDED en nommant son
remplaçant. Tout diagnostic non classé est signalé en fin de rapport :
la liste ne peut donc pas pourrir en silence.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


DIAG_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DIAG_DIR.parent


# Diagnostics qui valident le code installé. Doivent tous être verts.
CURRENT = [
    "main_v10_4_1_audit",
    "application_gate_v1_audit",
    "application_gate_v13_audit",
    "application_gate_v13_shadow_audit",
    "application_gate_v131_shadow_audit",
    "application_gate_v132_audit",
    "application_gate_v133_audit",
    "application_queue_v12_audit",
    "application_preparation_v11_audit",
    "application_preparation_v11_post_upgrade_audit",
    "job_refresh_v11_audit",
    "job_refresh_v12_audit",
    "job_refresh_v12_post_upgrade_audit",
    "application_recheck_v11_audit",
    "application_recheck_v11_post_upgrade_audit",
    "final_application_pool_v12_audit",
    "final_application_pool_v12_post_upgrade_audit",
    "chatgpt_handoff_v1_audit",
    "daily_run_v101_encoding_audit",
    "daily_run_v102_refresh_status_audit",
    "daily_run_v110_delta_integration_audit",
    "daily_run_v110_current_installation_audit",
    "delta_tracker_v1_audit",
    "delta_tracker_v11_repost_audit",
    "delta_tracker_v11_current_batch_audit",
    # Audits « current batch » : ils valident le dernier lot d'artefacts
    # réellement produit, pas seulement le code. Hors ligne, donc dans la
    # suite — ils échoueront légitimement si la chaîne n'a jamais tourné.
    "daily_run_v1_current_installation_audit",
    "application_recheck_v11_current_batch_audit",
    "final_application_pool_v12_current_batch_audit",
]


# Diagnostics d'une version remplacée. Ils échouent normalement : ce n'est
# pas un défaut de l'installation, c'est leur cible qui n'existe plus.
SUPERSEDED = {
    "application_recheck_v1_audit": "application_recheck_v11_audit",
    "final_application_pool_v1_audit": "final_application_pool_v12_audit",
    "job_refresh_v11_post_upgrade_audit": "job_refresh_v12_post_upgrade_audit",
    # Le pipeline est passé de 6 à 7 étapes (delta inséré) : cet audit
    # valide la structure V1.0, pas celle installée.
    "daily_run_v1_audit": "daily_run_v110_delta_integration_audit",
    # V1.1 introduit le statut REPOSTED, que l'audit V1.0 refuse.
    "delta_tracker_v1_current_batch_audit": "delta_tracker_v11_current_batch_audit",
}


# Appels réseau : jamais lancés par défaut.
LIVE = [
    "job_refresh_v11_smartrecruiters_live_audit",
    "job_refresh_v12_travaillerpour_live_audit",
    "smartrecruiters_v1_audit",
    "smartrecruiters_v11_audit",
]


# Scripts qui produisent un rapport plutôt qu'un verdict : hors suite.
REPORTS = [
    "application_gate_v131_replay",
    "application_gate_v132_db_replay",
    "application_gate_v133_replay",
    "funnel_recall_audit",
    "funnel_recall_v1_audit",
    "recall_rescue_v1",
    "recall_rescue_v1_audit",
    "matcher_v51_audit",
]


# Audits d'une version antérieure encore verts : conservés comme historique,
# hors suite pour ne pas allonger le temps de passage.
LEGACY_GREEN = [
    "ai_document_generator_v1_audit",
    "application_preparation_v1_audit",
    "application_queue_v1_audit",
    "final_application_pool_v11_audit",
    "job_refresh_v1_audit",
    "main_v10_4_audit",
]


SCORE_RE = re.compile(r"(?:Tests|Checks)\s*:\s*(\d+)\s*/\s*(\d+)")


def known_modules():
    return set(CURRENT) | set(SUPERSEDED) | set(LIVE) | set(REPORTS) | set(LEGACY_GREEN)


def discovered_modules():
    found = set()
    for path in DIAG_DIR.glob("*.py"):
        if path.stem in {"__init__", "run_all", "version_support"}:
            continue
        found.add(path.stem)
    return found


def run_one(module, timeout=180):
    proc = subprocess.run(
        [sys.executable, "-m", f"diagnostics.{module}"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env={**__import__("os").environ,
             "PYTHONIOENCODING": "utf-8",
             "PYTHONUTF8": "1"},
    )
    sortie = (proc.stdout or "") + (proc.stderr or "")
    scores = SCORE_RE.findall(sortie)
    score = f"{scores[-1][0]}/{scores[-1][1]}" if scores else ""
    return proc.returncode, score, sortie


def premiere_erreur(sortie):
    for ligne in sortie.splitlines():
        if ligne.strip().startswith("❌"):
            return ligne.strip()[:96]
    for ligne in reversed(sortie.splitlines()):
        if ligne.strip():
            return ligne.strip()[:96]
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true",
                        help="affiche le classement sans rien lancer")
    parser.add_argument("--include-live", action="store_true",
                        help="inclut les diagnostics qui appellent le réseau")
    args = parser.parse_args()

    if args.list:
        for titre, valeurs in (
            ("SUITE (doivent être verts)", CURRENT),
            ("REMPLACÉS (échec attendu)", list(SUPERSEDED)),
            ("RÉSEAU", LIVE),
            ("RAPPORTS", REPORTS),
            ("HISTORIQUE", LEGACY_GREEN),
        ):
            print(f"\n{titre}")
            for nom in valeurs:
                suffixe = ""
                if nom in SUPERSEDED:
                    suffixe = f"   -> remplacé par {SUPERSEDED[nom]}"
                print(f"  {nom}{suffixe}")
        return 0

    a_lancer = list(CURRENT) + (LIVE if args.include_live else [])

    print("=" * 92)
    print("JOB HUNTER - SUITE DE DIAGNOSTICS")
    print("=" * 92)
    print()

    echecs = []
    for module in a_lancer:
        if not (DIAG_DIR / f"{module}.py").exists():
            print(f"  ⚠️  {module:<50} ABSENT")
            echecs.append((module, "fichier absent"))
            continue

        print(f"  ⏳ {module:<50}", end="\r", flush=True)
        try:
            code, score, sortie = run_one(module)
        except subprocess.TimeoutExpired:
            print(f"  ❌ {module:<50} TIMEOUT")
            echecs.append((module, "timeout"))
            continue

        if code == 0:
            print(f"  ✅ {module:<50} {score}")
        else:
            print(f"  ❌ {module:<50} {score}")
            echecs.append((module, premiere_erreur(sortie)))

    print()
    print("-" * 92)
    print(f"Suite : {len(a_lancer) - len(echecs)}/{len(a_lancer)}")

    if SUPERSEDED:
        print()
        print("Non lancés — remplacés par une version plus récente :")
        for ancien, nouveau in SUPERSEDED.items():
            print(f"  {ancien}  ->  {nouveau}")

    inconnus = sorted(discovered_modules() - known_modules())
    if inconnus:
        print()
        print("⚠️  Diagnostics non classés dans run_all.py :")
        for nom in inconnus:
            print(f"  {nom}")
        print("  Ajoute-les à CURRENT, SUPERSEDED, LIVE, REPORTS ou LEGACY_GREEN.")

    print("-" * 92)

    if echecs:
        print()
        for module, detail in echecs:
            print(f"❌ {module}")
            if detail:
                print(f"   {detail}")
        print()
        print("❌ SUITE DE DIAGNOSTICS EN ÉCHEC.")
        return 1

    print()
    print("✅ SUITE DE DIAGNOSTICS VALIDÉE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
