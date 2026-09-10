"""
JOB REFRESH V1.1 - POST UPGRADE AUDIT

Usage:
    python -m diagnostics.job_refresh_v11_post_upgrade_audit
"""

import applications.job_refresh as refresh


def main():
    checks = [
        ("Version V1.1", refresh.REFRESH_VERSION == "1.1"),
        (
            "Parser SmartRecruiters",
            callable(getattr(refresh, "parse_smartrecruiters_identity", None)),
        ),
        (
            "Fetch SmartRecruiters",
            callable(getattr(refresh, "fetch_smartrecruiters_live_detail", None)),
        ),
        (
            "Routeur live",
            'source == "SMARTRECRUITERS"'
            in __import__("inspect").getsource(refresh.fetch_live_detail),
        ),
        (
            "Export compatible job_refresh_v1",
            "job_refresh_v1_"
            in __import__("inspect").getsource(refresh.export_results),
        ),
    ]

    print("=" * 80)
    print("JOB REFRESH V1.1 - POST UPGRADE AUDIT")
    print("=" * 80)
    print()

    passed = 0
    for label, ok in checks:
        passed += int(bool(ok))
        print(f"{'✅' if ok else '❌'} {label}")

    print()
    print(f"Checks : {passed}/{len(checks)}")

    if passed != len(checks):
        raise SystemExit("❌ JOB REFRESH V1.1 NON INSTALLÉ CORRECTEMENT.")

    print("✅ JOB REFRESH V1.1 INSTALLÉ ET COMPATIBLE.")


if __name__ == "__main__":
    main()
