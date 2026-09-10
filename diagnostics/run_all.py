"""
Job Hunter Belgium — suite officielle de diagnostics.

Hardening Step 5B.

Usage courant:
    python -m diagnostics.run_all

Autres modes:
    python -m diagnostics.run_all --list
    python -m diagnostics.run_all --check-classification
    python -m diagnostics.run_all --reports
    python -m diagnostics.run_all --replays
    python -m diagnostics.run_all --network

Par défaut:
- lance uniquement SUITE_ACTIVE;
- ne lance aucun audit réseau/live;
- ne lance aucun replay DB;
- ne lance aucun rapport;
- ne lance aucun audit remplacé/historique;
- échoue AVANT exécution si un fichier diagnostics/*.py n'est pas classé.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIAG_DIR = ROOT / "diagnostics"
LOG_DIR = ROOT / "exports" / "logs"


# ---------------------------------------------------------------------------
# 1) SUITE ACTIVE OFFLINE
# ---------------------------------------------------------------------------
# Audits de régression encore utiles sur l'installation courante.
# Aucun audit explicitement live/réseau ou replay DB n'est ici.
SUITE_ACTIVE = [
    "ai_document_generator_v1_audit",
    "application_gate_v13_audit",
    "application_gate_v131_shadow_audit",
    "application_gate_v132_audit",
    "application_gate_v133_audit",
    "application_gate_v13_shadow_audit",
    "application_preparation_v1_audit",
    "application_preparation_v11_audit",
    "application_queue_v12_audit",
    "application_recheck_v11_audit",
    "artifact_pattern_collision_audit",
    "chatgpt_handoff_v1_audit",
    "daily_run_v101_encoding_audit",
    "daily_run_v102_refresh_status_audit",
    "daily_run_v110_delta_integration_audit",
    "delta_tracker_v1_audit",
    "delta_tracker_v11_repost_audit",
    "final_application_pool_v11_audit",
    "final_application_pool_v12_audit",
    "funnel_recall_v1_audit",
    "hardening_step4b_candidate_truth_audit",
    "hardening_step4c_handoff_bundle_audit",
    "job_refresh_v12_audit",
    "jobhunter_ui_v1_audit",
    "location_belgium_v1_audit",
    "main_v10_4_1_audit",
    "matcher_v51_audit",
    "recall_rescue_v1_audit",
    "recruitee_v1_audit",
    "greenhouse_v1_audit",
    "workday_v1_audit",
    "successfactors_v1_audit",
    "preselection_rescue_v1_audit",
    "phenom_v1_audit",
    # Instrument, pas test : il ne peut pas échouer, il rapporte. Il est ici
    # parce qu'une source muette ne se voit nulle part ailleurs — tous les
    # autres audits vérifient qu'un composant fait ce qu'il annonce, aucun ne
    # vérifie qu'il rapporte des offres.
    "source_yield_audit",
    "vdab_v1_audit",
    "verdict_v1_audit",
    "verdict_gate_v1_audit",
    "texte_parasite_v1_audit",
    "reprise_stock_v1_audit",
    "job_titles_v2_audit",
    "piste_accessible_v1_audit",
]


# ---------------------------------------------------------------------------
# 2) REMPLACÉS — jamais lancés par run_all
# ---------------------------------------------------------------------------
REPLACED = {
    "application_gate_v1_audit":
        "application_gate_v132_audit",
    "application_queue_v1_audit":
        "application_queue_v12_audit",
    "application_recheck_v1_audit":
        "application_recheck_v11_audit",
    "daily_run_v1_audit":
        "daily_run_v110_delta_integration_audit",
    "daily_run_v1_current_installation_audit":
        "daily_run_v110_current_installation_audit",
    "delta_tracker_v1_current_batch_audit":
        "delta_tracker_v11_current_batch_audit",
    "final_application_pool_v1_audit":
        "final_application_pool_v12_audit",
    "job_refresh_v1_audit":
        "job_refresh_v12_audit",
    "job_refresh_v11_audit":
        "job_refresh_v12_audit",
    "job_refresh_v11_post_upgrade_audit":
        "job_refresh_v12_post_upgrade_audit",
    "main_v10_4_audit":
        "main_v10_4_1_audit",
    "smartrecruiters_v1_audit":
        "smartrecruiters_v11_audit",
    "hardening_step3_handoff_audit":
        "hardening_step3_v2_audit",
}


# ---------------------------------------------------------------------------
# 3) RÉSEAU / LIVE — seulement avec --network
# ---------------------------------------------------------------------------
# Classification explicite : certains utilisent des fonctions réseau
# indirectement et n'importent pas requests eux-mêmes.
NETWORK = [
    "phenom_v1_live_test",
    "successfactors_v1_live_test",
    "ats_fingerprint",
    "workday_discovery",
    "workday_v1_live_test",
    "ats_discovery",
    "greenhouse_v1_live_test",
    "recruitee_v1_live_test",
    # Test live Jobat : réseau, et surtout repli navigateur sur 403/429.
    # Voir la note du rapport de revue — jamais lancé par défaut.
    "jobat_v1_live_test",
    "job_refresh_v11_smartrecruiters_live_audit",
    "job_refresh_v12_travaillerpour_live_audit",
    "smartrecruiters_v11_audit",
]


# ---------------------------------------------------------------------------
# 4) RAPPORTS — seulement avec --reports
# ---------------------------------------------------------------------------
REPORTS = [
    "application_recheck_v11_current_batch_audit",
    "daily_run_v110_current_installation_audit",
    "delta_tracker_v11_current_batch_audit",
    "final_application_pool_v12_current_batch_audit",
    "funnel_recall_audit",
    "hardening_step4a_candidate_truth_inventory",
    "hardening_step5a_diagnostics_inventory",
    "hardening_step6a_dependency_inventory",
]


# ---------------------------------------------------------------------------
# 5) REPLAYS / ANALYSES LOURDES — seulement avec --replays
# ---------------------------------------------------------------------------
REPLAYS = [
    "application_gate_v131_replay",
    "application_gate_v132_db_replay",
    "application_gate_v133_replay",
]


# ---------------------------------------------------------------------------
# 6) HISTORIQUE / HOTFIX — conservés, jamais lancés par défaut
# ---------------------------------------------------------------------------
HISTORICAL = [
    "application_preparation_v11_post_upgrade_audit",
    "application_recheck_v11_post_upgrade_audit",
    "final_application_pool_v12_post_upgrade_audit",
    "job_refresh_v12_post_upgrade_audit",
    "hardening_step2_diagnostics_audit",
    "hardening_step3_v2_audit",
    "hardening_step4b_bda_label_audit",
    "hardening_step4c_import_order_audit",
]


# ---------------------------------------------------------------------------
# 7) OUTILS / INFRASTRUCTURE — classés mais non lancés par défaut
# ---------------------------------------------------------------------------
TOOLS = [
    "recall_rescue_v1",
    "version_support",
    "run_all",
    "resync_upstream",
    "source_silence_probe",
    "detail_backfill",
    "texte_parasite_repair",
    "purge_historique",
    "purge_artefacts",
    "verdict_vs_score",
    "hardening_step5b_run_all_audit",
    "hardening_step6b_requirements_audit",
    "hardening_step7_final_validation",
]


def child_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def discovered_modules():
    return {
        path.stem
        for path in DIAG_DIR.glob("*.py")
        if path.name != "__init__.py"
    }


def category_map():
    result = {}

    def add(category, values):
        for value in values:
            if value in result:
                raise RuntimeError(
                    f"Diagnostic classé deux fois: {value} "
                    f"({result[value]} + {category})"
                )
            result[value] = category

    add("SUITE_ACTIVE", SUITE_ACTIVE)
    add("REPLACED", REPLACED.keys())
    add("NETWORK", NETWORK)
    add("REPORTS", REPORTS)
    add("REPLAYS", REPLAYS)
    add("HISTORICAL", HISTORICAL)
    add("TOOLS", TOOLS)

    return result


def classification_status():
    discovered = discovered_modules()
    mapping = category_map()
    classified = set(mapping)

    missing_on_disk = sorted(classified - discovered)
    unclassified = sorted(discovered - classified)

    return {
        "ok": not missing_on_disk and not unclassified,
        "discovered_count": len(discovered),
        "classified_count": len(classified),
        "missing_on_disk": missing_on_disk,
        "unclassified": unclassified,
        "mapping": mapping,
    }


def print_classification(status):
    print("Classification diagnostics")
    print("-" * 80)
    print("Fichiers détectés :", status["discovered_count"])
    print("Fichiers classés  :", status["classified_count"])
    print("Non classés       :", len(status["unclassified"]))
    print("Classés mais absents:", len(status["missing_on_disk"]))

    if status["unclassified"]:
        print()
        print("NON CLASSÉS:")
        for item in status["unclassified"]:
            print(" -", item)

    if status["missing_on_disk"]:
        print()
        print("CLASSÉS MAIS ABSENTS:")
        for item in status["missing_on_disk"]:
            print(" -", item)


def print_list():
    print("=" * 100)
    print("JOB HUNTER — DIAGNOSTICS CLASSIFICATION")
    print("=" * 100)

    categories = [
        ("SUITE ACTIVE", SUITE_ACTIVE),
        ("REMPLACÉS", list(REPLACED)),
        ("RÉSEAU / LIVE", NETWORK),
        ("RAPPORTS", REPORTS),
        ("REPLAYS", REPLAYS),
        ("HISTORIQUE", HISTORICAL),
        ("OUTILS", TOOLS),
    ]

    for title, values in categories:
        print()
        print(f"{title} ({len(values)})")
        print("-" * 80)
        for value in values:
            if title == "REMPLACÉS":
                print(f" - {value} -> {REPLACED[value]}")
            else:
                print(" -", value)


def run_module(module):
    proc = subprocess.run(
        [sys.executable, "-m", f"diagnostics.{module}"],
        cwd=ROOT,
        env=child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    return {
        "module": module,
        "returncode": proc.returncode,
        "passed": proc.returncode == 0,
        "output": proc.stdout,
    }


def run_group(group_name, modules):
    print()
    print("=" * 100)
    print(f"{group_name} — {len(modules)} diagnostics")
    print("=" * 100)

    results = []

    for index, module in enumerate(modules, start=1):
        result = run_module(module)
        results.append(result)

        mark = "PASS" if result["passed"] else "FAIL"
        print(
            f"[{mark}] {index:02d}/{len(modules):02d} "
            f"diagnostics.{module}"
        )

        if not result["passed"]:
            tail = result["output"][-2500:]
            print("-" * 80)
            # La console Windows est en cp1252 : imprimer telle quelle la
            # sortie d'un audit contenant une croix ou un tiret cadratin
            # levait UnicodeEncodeError. Le lanceur plantait donc au moment
            # precis ou il devait montrer l'echec — le seul moment ou sa
            # sortie compte vraiment.
            encodage = getattr(sys.stdout, "encoding", None) or "utf-8"
            print(tail.encode(encodage, errors="replace").decode(encodage))
            print("-" * 80)

    return results


def write_report(mode, results, classification):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    passed = sum(1 for row in results if row["passed"])
    total = len(results)

    status = (
        "VALIDATED"
        if total > 0 and passed == total
        else "FAILED"
        if total > 0
        else "NO_TESTS"
    )

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "status": status,
        "checks_passed": passed,
        "checks_total": total,
        "classification": {
            "ok": classification["ok"],
            "discovered_count":
                classification["discovered_count"],
            "classified_count":
                classification["classified_count"],
            "missing_on_disk":
                classification["missing_on_disk"],
            "unclassified":
                classification["unclassified"],
        },
        "results": [
            {
                "module": row["module"],
                "returncode": row["returncode"],
                "passed": row["passed"],
                "output_tail": row["output"][-6000:],
            }
            for row in results
        ],
    }

    json_path = (
        LOG_DIR
        / f"diagnostics_run_all_{mode}_{stamp}.json"
    )
    txt_path = (
        LOG_DIR
        / f"diagnostics_run_all_{mode}_{stamp}.txt"
    )

    json_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        f"JOB HUNTER - DIAGNOSTICS RUN ALL ({mode})",
        "=" * 100,
        f"Classification : {'OK' if classification['ok'] else 'FAIL'}",
        f"Tests          : {passed}/{total}",
        f"Status         : {status}",
        "",
    ]

    for row in results:
        lines.append(
            f"[{'PASS' if row['passed'] else 'FAIL'}] "
            f"diagnostics.{row['module']}"
        )

    txt_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    return json_path, txt_path, payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--list",
        action="store_true",
        help="Afficher la classification sans lancer de diagnostic.",
    )
    parser.add_argument(
        "--check-classification",
        action="store_true",
        help="Vérifier qu'aucun fichier n'est non classé.",
    )
    parser.add_argument(
        "--reports",
        action="store_true",
        help="Lancer uniquement les rapports.",
    )
    parser.add_argument(
        "--replays",
        action="store_true",
        help="Lancer uniquement les replays/analyses lourdes.",
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help="Lancer explicitement les audits live/réseau.",
    )
    args = parser.parse_args()

    classification = classification_status()

    if args.list:
        print_list()
        print()
        print_classification(classification)
        raise SystemExit(
            0 if classification["ok"] else 1
        )

    if args.check_classification:
        print_classification(classification)
        if classification["ok"]:
            print()
            print("[PASS] Tous les diagnostics sont classés.")
            return
        raise SystemExit(1)

    # Garde essentielle: aucun test n'est lancé tant que la classification
    # n'est pas exhaustive.
    if not classification["ok"]:
        print_classification(classification)
        print()
        print(
            "[FAIL] Classification incomplète. "
            "Aucun diagnostic n'a été lancé."
        )
        raise SystemExit(1)

    selected_modes = sum(
        bool(x)
        for x in (
            args.reports,
            args.replays,
            args.network,
        )
    )

    if selected_modes > 1:
        raise SystemExit(
            "Choisir un seul mode parmi --reports, --replays, --network."
        )

    if args.reports:
        mode = "reports"
        modules = REPORTS
        title = "RAPPORTS"
    elif args.replays:
        mode = "replays"
        modules = REPLAYS
        title = "REPLAYS"
    elif args.network:
        mode = "network"
        modules = NETWORK
        title = "RÉSEAU / LIVE"
        print(
            "ATTENTION: mode réseau explicitement demandé."
        )
    else:
        mode = "suite"
        modules = SUITE_ACTIVE
        title = "SUITE ACTIVE OFFLINE"

    results = run_group(title, modules)
    json_path, txt_path, payload = write_report(
        mode,
        results,
        classification,
    )

    print()
    print("=" * 100)
    print(
        f"Résultat : {payload['checks_passed']}/"
        f"{payload['checks_total']}"
    )
    print(
        "[PASS] SUITE VALIDÉE."
        if payload["status"] == "VALIDATED"
        else "[FAIL] SUITE NON VALIDÉE."
    )
    print("JSON :", json_path)
    print("TXT  :", txt_path)

    if payload["status"] != "VALIDATED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
