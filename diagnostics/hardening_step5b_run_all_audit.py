"""
Hardening Step 5B — audit structurel de diagnostics.run_all.

N'exécute PAS la suite complète.
N'exécute PAS le réseau.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from diagnostics import run_all


ROOT = Path(__file__).resolve().parents[1]


def check(label, condition, detail=""):
    ok = bool(condition)
    print(
        f"[{'PASS' if ok else 'FAIL'}] {label}"
        + (f" | {detail}" if detail else "")
    )
    return ok


def main():
    print("=" * 100)
    print("HARDENING STEP 5B - RUN_ALL STRUCTURAL AUDIT")
    print("=" * 100)

    tests = []

    status = run_all.classification_status()

    tests.append(check(
        "Classification exhaustive",
        status["ok"],
        (
            f"unclassified={status['unclassified']} "
            f"missing={status['missing_on_disk']}"
        ),
    ))

    tests.append(check(
        "Suite active non vide",
        len(run_all.SUITE_ACTIVE) > 0,
        str(len(run_all.SUITE_ACTIVE)),
    ))

    tests.append(check(
        "Réseau exclu de la suite active",
        set(run_all.NETWORK).isdisjoint(
            run_all.SUITE_ACTIVE
        ),
    ))

    tests.append(check(
        "Replays exclus de la suite active",
        set(run_all.REPLAYS).isdisjoint(
            run_all.SUITE_ACTIVE
        ),
    ))

    tests.append(check(
        "Rapports exclus de la suite active",
        set(run_all.REPORTS).isdisjoint(
            run_all.SUITE_ACTIVE
        ),
    ))

    tests.append(check(
        "Remplacés exclus de la suite active",
        set(run_all.REPLACED).isdisjoint(
            run_all.SUITE_ACTIVE
        ),
    ))

    tests.append(check(
        "Historique exclu de la suite active",
        set(run_all.HISTORICAL).isdisjoint(
            run_all.SUITE_ACTIVE
        ),
    ))

    required_replaced = {
        "application_recheck_v1_audit":
            "application_recheck_v11_audit",
        "final_application_pool_v1_audit":
            "final_application_pool_v12_audit",
        "daily_run_v1_audit":
            "daily_run_v110_delta_integration_audit",
        "delta_tracker_v1_current_batch_audit":
            "delta_tracker_v11_current_batch_audit",
    }
    tests.append(check(
        "Remplacements critiques documentés",
        all(
            run_all.REPLACED.get(old) == new
            for old, new in required_replaced.items()
        ),
    ))

    required_network = {
        "job_refresh_v11_smartrecruiters_live_audit",
        "job_refresh_v12_travaillerpour_live_audit",
        "smartrecruiters_v11_audit",
    }
    tests.append(check(
        "Audits live explicitement réseau",
        required_network <= set(run_all.NETWORK),
    ))

    tests.append(check(
        "run_all lui-même classé",
        "run_all" in run_all.TOOLS,
    ))

    passed = sum(tests)
    total = len(tests)
    status_text = (
        "HARDENING STEP 5B VALIDÉ."
        if all(tests)
        else "HARDENING STEP 5B NON VALIDÉ."
    )

    print()
    print(f"Tests : {passed}/{total}")
    print(status_text)

    log_dir = ROOT / "exports" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = (
        log_dir
        / f"hardening_step5b_run_all_audit_{stamp}.json"
    )
    txt_path = (
        log_dir
        / f"hardening_step5b_run_all_audit_{stamp}.txt"
    )

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checks_passed": passed,
        "checks_total": total,
        "status": status_text,
        "classification": {
            "ok": status["ok"],
            "discovered_count":
                status["discovered_count"],
            "classified_count":
                status["classified_count"],
            "unclassified":
                status["unclassified"],
            "missing_on_disk":
                status["missing_on_disk"],
        },
        "counts": {
            "suite_active":
                len(run_all.SUITE_ACTIVE),
            "replaced":
                len(run_all.REPLACED),
            "network":
                len(run_all.NETWORK),
            "reports":
                len(run_all.REPORTS),
            "replays":
                len(run_all.REPLAYS),
            "historical":
                len(run_all.HISTORICAL),
            "tools":
                len(run_all.TOOLS),
        },
    }

    json_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "HARDENING STEP 5B - RUN_ALL STRUCTURAL AUDIT",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status_text,
            (
                "Classification : "
                f"{status['classified_count']}/"
                f"{status['discovered_count']}"
            ),
            (
                "Suite active   : "
                f"{len(run_all.SUITE_ACTIVE)}"
            ),
        ]),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
