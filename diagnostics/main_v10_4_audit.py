"""
MAIN V10.4 - AUDIT OFFLINE

Aucun appel réseau.
Aucune écriture DB.

Usage :
    python -m diagnostics.main_v10_4_audit
"""

from __future__ import annotations

import inspect

import main


def main_audit():
    checks = []

    def check(label, condition, detail=""):
        ok = bool(condition)
        checks.append(ok)
        print(
            f"{'✅' if ok else '❌'} {label}"
            + (f" | {detail}" if detail else "")
        )

    print("=" * 82)
    print("MAIN V10.4 - AUDIT OFFLINE")
    print("=" * 82)
    print()

    module_source = inspect.getsource(main)

    check(
        "Version MAIN V10.4",
        "MAIN - VERSION 10.4" in module_source,
    )
    check(
        "Collecteur SmartRecruiters",
        callable(getattr(main, "collect_smartrecruiters_jobs", None)),
    )
    check(
        "SmartRecruiters dans collect_all_jobs",
        '"smartrecruiters": smartrecruiters'
        in inspect.getsource(main.collect_all_jobs),
    )
    check(
        "SmartRecruiters dans standard_jobs",
        "smartrecruiters"
        in inspect.getsource(main.collect_all_jobs),
    )
    check(
        "Routeur détail SmartRecruiters",
        'source == "SMARTRECRUITERS"'
        in inspect.getsource(main.get_job_detail),
    )
    check(
        "Gate V1.3 branché",
        getattr(main.apply_application_gate, "__module__", "")
        == "matching.application_gate_v13",
        getattr(main.apply_application_gate, "__module__", ""),
    )
    check(
        "8 étapes conservées",
        getattr(main, "TOTAL_MAIN_STEPS", None) == 8,
        str(getattr(main, "TOTAL_MAIN_STEPS", None)),
    )
    check(
        "Main callable",
        callable(getattr(main, "main", None)),
    )

    print()
    print(f"Checks : {sum(checks)}/{len(checks)}")

    if not all(checks):
        raise SystemExit("❌ MAIN V10.4 NON VALIDÉ.")

    print("✅ MAIN V10.4 VALIDÉ STRUCTURELLEMENT.")


if __name__ == "__main__":
    main_audit()
