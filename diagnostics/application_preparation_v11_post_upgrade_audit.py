"""
APPLICATION PREPARATION V1.1 - POST UPGRADE AUDIT

Usage:
python -m diagnostics.application_preparation_v11_post_upgrade_audit
"""

import inspect
import applications.application_preparation as prep
from diagnostics.version_support import at_least


def main():
    checks = []

    def check(label, condition, detail=""):
        ok = bool(condition)
        checks.append(ok)
        print(
            f"{'✅' if ok else '❌'} {label}"
            + (f" | {detail}" if detail else "")
        )

    print("=" * 84)
    print("APPLICATION PREPARATION V1.1 - POST UPGRADE AUDIT")
    print("=" * 84)
    print()

    check("Version Prep au moins 1.1",
          at_least(prep.PREPARATION_VERSION, "1.1"), prep.PREPARATION_VERSION)
    check("Queue 1.2 branchée", prep.QUEUE_VERSION == "1.2", prep.QUEUE_VERSION)
    check("Gate 1.3.2 attendu", prep.GATE_VERSION == "1.3.2", prep.GATE_VERSION)

    src = inspect.getsource(prep.load_current_queue)
    check(
        "Garde-fou Gate stale présent",
        "_assert_current_gate_version" in src,
    )
    check(
        "Rebuild Queue courant présent",
        "build_application_queue_from_gate_payload" in src,
    )

    print()
    print(f"Checks : {sum(checks)}/{len(checks)}")

    if not all(checks):
        raise SystemExit("❌ APPLICATION PREPARATION V1.1 MAL INSTALLÉE.")

    print("✅ APPLICATION PREPARATION V1.1 INSTALLÉE ET COHÉRENTE.")


if __name__ == "__main__":
    main()
