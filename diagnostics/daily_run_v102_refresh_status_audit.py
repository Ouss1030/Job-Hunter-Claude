"""
DAILY RUN V1.0.2 - REFRESH STATUS AUDIT

Usage:
    python -m diagnostics.daily_run_v102_refresh_status_audit

Aucune collecte, aucun réseau.
"""

import inspect
import daily_run
from diagnostics.version_support import at_least


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f" | {detail}" if detail else ""))
    return ok


def main():
    tests = []

    print("=" * 100)
    print("DAILY RUN V1.0.2 - REFRESH STATUS AUDIT")
    print("=" * 100)
    print()

    tests.append(check(
        "Version >= 1.0.2",
        at_least(daily_run.DAILY_RUN_VERSION, "1.0.2"),
        daily_run.DAILY_RUN_VERSION,
    ))

    src = inspect.getsource(daily_run.validate_refresh_json)

    tests.append(check(
        "job_live_status utilisé",
        'row.get("job_live_status")' in src,
    ))

    tests.append(check(
        "status générique non utilisé comme priorité",
        'row.get("status")' not in src,
    ))

    latest = daily_run.latest_path(
        daily_run.LOG_DIR,
        daily_run.ARTIFACT_PATTERNS["refresh_json"],
    )
    tests.append(check(
        "Dernier Refresh trouvé",
        latest is not None,
        str(latest),
    ))

    if latest is not None:
        result = daily_run.validate_refresh_json(latest)

        tests.append(check(
            "Refresh non vide",
            result["count"] > 0,
            str(result["count"]),
        ))

        tests.append(check(
            "Aucun UNKNOWN",
            result["statuses"].get("UNKNOWN", 0) == 0,
            str(result["statuses"]),
        ))

        tests.append(check(
            "LIVE_CONFIRMED détecté",
            result["statuses"].get("LIVE_CONFIRMED", 0) > 0,
            str(result["statuses"]),
        ))

        print()
        print("Statuts détectés :", result["statuses"])

    print()
    print(f"Tests : {sum(tests)}/{len(tests)}")

    if not all(tests):
        raise SystemExit("❌ REFRESH STATUS NON VALIDÉ.")

    print("✅ REFRESH STATUS (>= V1.0.2) VALIDÉ.")


if __name__ == "__main__":
    main()
