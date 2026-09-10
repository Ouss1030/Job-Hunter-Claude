"""
JOB REFRESH V1.2 - POST UPGRADE AUDIT

Usage:
python -m diagnostics.job_refresh_v12_post_upgrade_audit
"""

import inspect
import applications.job_refresh as refresh


def main():
    checks = []

    def check(label, condition, detail=""):
        ok = bool(condition)
        checks.append(ok)
        print(
            f"{'✅' if ok else '❌'} {label}"
            + (f" | {detail}" if detail else "")
        )

    print("=" * 80)
    print("JOB REFRESH V1.2 - POST UPGRADE AUDIT")
    print("=" * 80)
    print()

    check("Version 1.2", refresh.REFRESH_VERSION == "1.2", refresh.REFRESH_VERSION)
    check(
        "Parser TP présent",
        callable(getattr(refresh, "parse_travaillerpour_external_id", None)),
    )

    source = inspect.getsource(refresh.fetch_live_detail)
    check("Forem route", 'source == "FOREM"' in source)
    check("Actiris route", 'source == "ACTIRIS"' in source)
    check("SmartRecruiters route", 'source == "SMARTRECRUITERS"' in source)
    check("TravaillerPour route", 'source == "TRAVAILLERPOUR"' in source)

    print()
    print(f"Checks : {sum(checks)}/{len(checks)}")

    if not all(checks):
        raise SystemExit("❌ JOB REFRESH V1.2 MAL INSTALLÉ.")

    print("✅ JOB REFRESH V1.2 INSTALLÉ ET COHÉRENT.")


if __name__ == "__main__":
    main()
