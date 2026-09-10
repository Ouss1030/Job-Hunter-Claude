"""
APPLICATION RECHECK V1.1 - POST UPGRADE AUDIT

Usage:
    python -m diagnostics.application_recheck_v11_post_upgrade_audit
"""

import inspect
import applications.application_recheck as recheck


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
    print("APPLICATION RECHECK V1.1 - POST UPGRADE AUDIT")
    print("=" * 84)
    print()

    check(
        "Version 1.1",
        recheck.RECHECK_VERSION == "1.1",
        recheck.RECHECK_VERSION,
    )
    check(
        "Master Gate V1.3 branché",
        "detect_structured_master_requirement"
        in inspect.getsource(recheck.mandatory_master_block),
    )
    check(
        "Student contextuel",
        "strong_patterns"
        in inspect.getsource(recheck.explicit_student_role),
    )
    check(
        "Tableau contextuel",
        "_stack_term_is_mentioned"
        in inspect.getsource(recheck.data_experience_or_degree_stretch),
    )
    check(
        "Export downstream compatible",
        "application_recheck_v1_"
        in inspect.getsource(recheck.export_results),
    )

    print()
    print(f"Checks : {sum(checks)}/{len(checks)}")

    if not all(checks):
        raise SystemExit("❌ APPLICATION RECHECK V1.1 MAL INSTALLÉ.")

    print("✅ APPLICATION RECHECK V1.1 INSTALLÉ ET COMPATIBLE.")


if __name__ == "__main__":
    main()
