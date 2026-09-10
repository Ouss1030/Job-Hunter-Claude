"""
MAIN V10.4.1 - AUDIT OFFLINE

Usage:
    python -m diagnostics.main_v10_4_1_audit
"""

import inspect

import main
import matching.application_gate_v13 as gate_overlay
import matching.application_queue_v12 as queue_overlay

import re

from diagnostics.version_support import at_least


def run():
    checks = []

    def check(label, condition, detail=""):
        ok = bool(condition)
        checks.append(ok)
        print(
            f"{'✅' if ok else '❌'} {label}"
            + (f" | {detail}" if detail else "")
        )

    print("=" * 84)
    print("MAIN V10.4.1 - AUDIT OFFLINE")
    print("=" * 84)
    print()

    src = inspect.getsource(main)

    # Version minimale, pas exacte : main.py est passé en 10.5 sans que
    # cet audit change, ce qui faisait échouer une installation saine.
    _v = re.search(r"MAIN - VERSION\s+([0-9.]+)", src)
    check(
        "Version MAIN au moins 10.4.1",
        bool(_v) and at_least(_v.group(1), "10.4.1"),
        _v.group(1) if _v else "introuvable",
    )
    check("Gate overlay branché", main.apply_application_gate.__module__ == "matching.application_gate_v13")
    check("Gate version 1.3.2", gate_overlay.GATE_VERSION == "1.3.2", gate_overlay.GATE_VERSION)
    check("Queue overlay branchée", main.build_application_queue.__module__ == "matching.application_queue_v12")
    check("Queue version 1.2", queue_overlay.QUEUE_VERSION == "1.2", queue_overlay.QUEUE_VERSION)
    check("8 étapes conservées", getattr(main, "TOTAL_MAIN_STEPS", None) == 8)
    check("SmartRecruiters conservé", "collect_smartrecruiters_jobs" in src)
    check("Ancien label RÉSULTATS V10.3 retiré", "RÉSULTATS V10.3" not in src)

    print()
    print(f"Checks : {sum(checks)}/{len(checks)}")

    if not all(checks):
        raise SystemExit("❌ MAIN V10.4.1 NON VALIDÉ.")

    print("✅ MAIN V10.4.1 VALIDÉ STRUCTURELLEMENT.")


if __name__ == "__main__":
    run()
