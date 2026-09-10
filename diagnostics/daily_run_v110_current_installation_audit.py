"""
DAILY RUN V1.1.0 - CURRENT INSTALLATION AUDIT

Usage:
    python -m diagnostics.daily_run_v110_current_installation_audit

Aucune collecte.
"""

from datetime import datetime
import json
from pathlib import Path

import daily_run


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f" | {detail}" if detail else ""))
    return ok


def main():
    tests = []

    print("=" * 100)
    print("DAILY RUN V1.1.0 - CURRENT INSTALLATION AUDIT")
    print("=" * 100)
    print()

    preflight = daily_run.run_preflight()
    daily_run.print_preflight(preflight)

    tests.append(check(
        "Preflight global",
        preflight["ok"],
        " | ".join(preflight.get("errors") or []),
    ))

    tests.append(check(
        "Delta Tracker installé en 1.1",
        preflight["installed_versions"].get(
            "applications.delta_tracker:DELTA_TRACKER_VERSION"
        ) == "1.1",
        str(preflight["installed_versions"].get(
            "applications.delta_tracker:DELTA_TRACKER_VERSION"
        )),
    ))

    latest_pool = daily_run.latest_path(
        daily_run.LOG_DIR,
        daily_run.ARTIFACT_PATTERNS["final_pool_json"],
    )
    tests.append(check(
        "Dernier Final Pool trouvé",
        latest_pool is not None,
        str(latest_pool),
    ))

    if latest_pool is not None:
        pool_validation = daily_run.validate_final_pool_json(latest_pool)
        tests.append(check(
            "Dernier Final Pool V1.2 valide",
            pool_validation["count"] > 0,
            str(pool_validation["count"]),
        ))

    latest_delta = daily_run.latest_path(
        daily_run.LOG_DIR,
        daily_run.ARTIFACT_PATTERNS["delta_json"],
    )
    tests.append(check(
        "Dernier Delta trouvé",
        latest_delta is not None,
        str(latest_delta),
    ))

    if latest_delta is not None and latest_pool is not None:
        delta_validation = daily_run.validate_delta_json(
            latest_delta,
            expected_current_pool=latest_pool,
            expected_current_count=pool_validation["count"],
        )
        tests.append(check(
            "Dernier Delta V1.1 ancré sur le dernier Final Pool",
            delta_validation["version"] == "1.1",
            str(delta_validation),
        ))

    passed = sum(tests)
    total = len(tests)
    status = (
        "✅ DAILY RUN V1.1.0 COMPATIBLE AVEC L'INSTALLATION ACTUELLE."
        if all(tests)
        else "❌ INSTALLATION V1.1.0 NON VALIDÉE."
    )

    print()
    print(f"Checks : {passed}/{total}")
    print(status)

    log_dir = Path(__file__).resolve().parents[1] / "exports" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = log_dir / f"daily_run_v110_current_installation_audit_{stamp}.json"
    txt_path = log_dir / f"daily_run_v110_current_installation_audit_{stamp}.txt"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "preflight": preflight,
        "latest_final_pool": str(latest_pool) if latest_pool else None,
        "latest_delta": str(latest_delta) if latest_delta else None,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "DAILY RUN V1.1.0 - CURRENT INSTALLATION AUDIT",
            "=" * 100,
            f"Checks : {passed}/{total}",
            status,
            f"Latest Final Pool : {latest_pool}",
            f"Latest Delta      : {latest_delta}",
        ]),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
