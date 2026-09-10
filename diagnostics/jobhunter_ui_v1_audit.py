"""
JOB HUNTER BELGIUM
JOBHUNTER UI V1 - AUDIT OFFLINE

L'interface Streamlit (jobhunter_ui.py + interface/) représente ~2100 lignes
sans diagnostic, alors que tous les autres composants du projet en ont un.
Cet audit comble ce manque.

Il ne lance PAS Streamlit : il valide la couche métier et les garanties de
sécurité qui, elles, doivent tenir sans interface.

    python -m diagnostics.jobhunter_ui_v1_audit

Aucun réseau. Aucune écriture DB. Streamlit n'a pas besoin d'être installé.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import re
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "exports" / "logs"

MODULES_INTERFACE = [
    "data_access",
    "handoff_service",
    "lifecycle_service",
    "pipeline_runner",
    "progress_monitor",
    "daily_run_worker",
]


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def main():
    tests = []

    print("=" * 92)
    print("JOBHUNTER UI V1 - AUDIT OFFLINE")
    print("=" * 92)
    print()

    # ------------------------------------------------------------------
    # A. Séparation logique / interface
    # ------------------------------------------------------------------
    # Le point de conception qui rend l'UI testable : aucun module de
    # interface/ ne doit dépendre de Streamlit.
    for nom in MODULES_INTERFACE:
        chemin = PROJECT_ROOT / "interface" / f"{nom}.py"
        if not chemin.exists():
            tests.append(check(f"interface/{nom}.py présent", False))
            continue

        source = chemin.read_text(encoding="utf-8")
        importe_streamlit = re.search(r"^\s*(import|from)\s+streamlit\b",
                                      source, re.MULTILINE) is not None
        tests.append(check(
            f"interface/{nom} indépendant de Streamlit",
            not importe_streamlit,
        ))

    for nom in MODULES_INTERFACE:
        try:
            importlib.import_module(f"interface.{nom}")
            tests.append(check(f"interface/{nom} importable hors UI", True))
        except Exception as exc:
            tests.append(check(f"interface/{nom} importable hors UI", False,
                               f"{type(exc).__name__}: {exc}"))

    print()

    # ------------------------------------------------------------------
    # B. Garantie APPLIED — la règle métier la plus importante du projet
    # ------------------------------------------------------------------
    from interface import lifecycle_service as ls

    source_ls = (PROJECT_ROOT / "interface" / "lifecycle_service.py").read_text(
        encoding="utf-8")

    # record_system_status ne doit servir qu'à poser la trace DISCOVERED
    # initiale. Tout statut demandé par l'utilisateur passe par
    # record_user_status, sinon une candidature pourrait être marquée
    # APPLIED sans action humaine.
    arbre = ast.parse(source_ls)
    appels_systeme = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        cible = getattr(noeud.func, "attr", None)
        if cible != "record_system_status":
            continue
        statuts = [
            kw.value.value
            for kw in noeud.keywords
            if kw.arg == "status" and isinstance(kw.value, ast.Constant)
        ]
        appels_systeme.extend(statuts)

    tests.append(check(
        "record_system_status limité à DISCOVERED",
        appels_systeme and set(appels_systeme) == {"DISCOVERED"},
        str(appels_systeme),
    ))

    tests.append(check(
        "set_status passe par record_user_status",
        "record_user_status" in inspect.getsource(ls.set_status),
    ))

    tests.append(check(
        "set_status refuse un statut inconnu",
        _refuse_statut_inconnu(ls),
    ))

    print()

    # ------------------------------------------------------------------
    # C. Contrats de retour des services
    # ------------------------------------------------------------------
    # Ces fonctions renvoient des tuples (données, ..., chemin). Un
    # changement de forme casserait l'UI silencieusement.
    from interface import data_access as da, handoff_service as hs

    try:
        resultat = da.load_latest_final_pool()
        tests.append(check(
            "load_latest_final_pool renvoie (liste, résumé, chemin)",
            isinstance(resultat, tuple) and len(resultat) == 3
            and isinstance(resultat[0], list) and isinstance(resultat[1], dict),
            f"{type(resultat).__name__} de {len(resultat)}"
            if isinstance(resultat, tuple) else type(resultat).__name__,
        ))
    except Exception as exc:
        tests.append(check("load_latest_final_pool renvoie (liste, résumé, chemin)",
                           False, f"{type(exc).__name__}: {exc}"))

    try:
        candidats, chemin = hs.load_candidates()
        tests.append(check(
            "load_candidates renvoie (liste, chemin)",
            isinstance(candidats, list) and candidats
            and isinstance(candidats[0], dict),
            f"{len(candidats)} candidat(s)",
        ))
    except Exception as exc:
        tests.append(check("load_candidates renvoie (liste, chemin)", False,
                           f"{type(exc).__name__}: {exc}"))

    try:
        metriques = da.dashboard_metrics()
        attendues = {"canonical_count", "queue_count", "pool_count"}
        tests.append(check(
            "dashboard_metrics expose les compteurs attendus",
            attendues.issubset(metriques.keys()),
            str(sorted(attendues & set(metriques))),
        ))
    except Exception as exc:
        tests.append(check("dashboard_metrics expose les compteurs attendus",
                           False, f"{type(exc).__name__}: {exc}"))

    print()

    # ------------------------------------------------------------------
    # D. Exposition réseau
    # ------------------------------------------------------------------
    # L'UI affiche le CV, le profil et les candidatures. Elle ne doit être
    # servie que sur la boucle locale.
    lanceur = PROJECT_ROOT / "START_JOBHUNTER.bat"
    if lanceur.exists():
        contenu = lanceur.read_text(encoding="utf-8", errors="replace")
        tests.append(check(
            "Streamlit lié à 127.0.0.1",
            "--server.address 127.0.0.1" in contenu,
        ))
        tests.append(check(
            "Aucune écoute sur 0.0.0.0",
            "0.0.0.0" not in contenu,
        ))
    else:
        tests.append(check("START_JOBHUNTER.bat présent", False))

    fichier_ui = PROJECT_ROOT / "requirements_ui.txt"
    tests.append(check(
        "requirements_ui.txt déclare streamlit",
        fichier_ui.exists() and "streamlit" in fichier_ui.read_text(
            encoding="utf-8").lower(),
    ))

    print()

    # ------------------------------------------------------------------
    # E. Protection contre les exécutions concurrentes
    # ------------------------------------------------------------------
    from interface import pipeline_runner as pr

    tests.append(check(
        "pipeline_runner expose un verrou",
        hasattr(pr, "LOCK_PATH") and hasattr(pr, "is_running"),
    ))
    tests.append(check(
        "Le lancement vérifie is_running()",
        "is_running()" in (PROJECT_ROOT / "interface" / "pipeline_runner.py")
        .read_text(encoding="utf-8"),
    ))

    print()

    # ------------------------------------------------------------------
    # F. Syntaxe de l'interface
    # ------------------------------------------------------------------
    fichier_app = PROJECT_ROOT / "jobhunter_ui.py"
    try:
        ast.parse(fichier_app.read_text(encoding="utf-8"))
        tests.append(check("jobhunter_ui.py compile", True))
    except SyntaxError as exc:
        tests.append(check("jobhunter_ui.py compile", False,
                           f"ligne {exc.lineno}"))

    passed = sum(1 for x in tests if x)
    total = len(tests)

    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"jobhunter_ui_v1_audit_{stamp}.json").write_text(
        json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                    "passed": passed, "total": total},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if passed != total:
        raise SystemExit("[FAIL] JOBHUNTER UI V1 NON VALIDÉ.")

    print("[PASS] JOBHUNTER UI V1 VALIDÉ.")


def _refuse_statut_inconnu(ls) -> bool:
    """set_status doit rejeter un statut hors liste avant tout accès DB."""
    try:
        ls.set_status({"stable_item_key": "TEST", "url": ""}, "STATUT_BIDON")
    except ValueError:
        return True
    except Exception:
        # Une autre erreur signifie que la validation n'a pas eu lieu en premier.
        return False
    return False


if __name__ == "__main__":
    main()
