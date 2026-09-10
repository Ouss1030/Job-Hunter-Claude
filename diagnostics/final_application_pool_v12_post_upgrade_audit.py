"""
FINAL APPLICATION POOL V1.2 - POST UPGRADE AUDIT

Usage:
    python -m diagnostics.final_application_pool_v12_post_upgrade_audit
"""

import inspect

import applications.final_application_pool as pool


def main():
    checks = []

    def check(label, condition, detail=""):
        ok = bool(condition)
        checks.append(ok)
        print(
            f"{'✅' if ok else '❌'} {label}"
            + (f" | {detail}" if detail else "")
        )

    print("=" * 90)
    print("FINAL APPLICATION POOL V1.2 - POST UPGRADE AUDIT")
    print("=" * 90)
    print()

    check(
        "Version 1.2",
        pool.FINAL_POOL_VERSION == "1.2",
        pool.FINAL_POOL_VERSION,
    )

    build_src = inspect.getsource(pool.build_pool_v12)

    check(
        "Construit depuis Recheck",
        'application_recheck_v1_*.json' in build_src,
    )

    check(
        "Construit depuis Job Refresh",
        'job_refresh_v1_*.json' in build_src,
    )

    check(
        "Ne lit plus ancien final_application_pool_v1",
        'final_application_pool_v1_*.json' not in build_src,
    )

    check(
        "Recall Rescue stale exclu",
        "EXCLUDED_UNLESS_REFETCHED_AND_RECHECKED" in build_src,
    )

    check(
        "Export V1.2",
        "final_application_pool_v12_" in inspect.getsource(pool.export_pool),
    )

    print()
    print(f"Checks : {sum(checks)}/{len(checks)}")

    if not all(checks):
        raise SystemExit("❌ FINAL APPLICATION POOL V1.2 MAL INSTALLÉ.")

    print("✅ FINAL APPLICATION POOL V1.2 INSTALLÉ ET COHÉRENT.")


if __name__ == "__main__":
    main()
