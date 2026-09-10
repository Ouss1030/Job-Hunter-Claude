"""
DAILY RUN V1.0 - AUDIT OFFLINE / STRUCTUREL

Usage:
    python -m diagnostics.daily_run_v1_audit

Aucun réseau.
Aucune collecte.
Aucune écriture DB.
"""

from pathlib import Path
from datetime import datetime
import inspect

import daily_run


def check(label, condition, detail=""):
    ok = bool(condition)
    print(
        f"{'✅' if ok else '❌'} {label}"
        + (f" | {detail}" if detail else "")
    )
    return ok


def main():
    tests = []

    print("=" * 100)
    print("DAILY RUN V1.0 - AUDIT STRUCTUREL")
    print("=" * 100)
    print()

    tests.append(check(
        "Version 1.0",
        daily_run.DAILY_RUN_VERSION == "1.0",
        daily_run.DAILY_RUN_VERSION,
    ))

    tests.append(check(
        "6 étapes dans le bon ordre",
        daily_run.STEP_ORDER == [
            "main",
            "preparation",
            "refresh",
            "recheck",
            "final_pool",
            "handoff",
        ],
        str(daily_run.STEP_ORDER),
    ))

    tests.append(check(
        "Preparation limite 80",
        daily_run.DEFAULT_PREPARATION_LIMIT == 80,
        str(daily_run.DEFAULT_PREPARATION_LIMIT),
    ))

    tests.append(check(
        "Handoff chunk 10",
        daily_run.DEFAULT_HANDOFF_CHUNK_SIZE == 10,
        str(daily_run.DEFAULT_HANDOFF_CHUNK_SIZE),
    ))

    expected = {
        "matching.application_gate_v13:GATE_VERSION": "1.3.2",
        "matching.application_queue_v12:QUEUE_VERSION": "1.2",
        "applications.application_preparation:PREPARATION_VERSION": "1.1",
        "applications.job_refresh:REFRESH_VERSION": "1.2",
        "applications.application_recheck:RECHECK_VERSION": "1.1",
        "applications.final_application_pool:FINAL_POOL_VERSION": "1.2",
        "applications.chatgpt_handoff:HANDOFF_VERSION": "1.0",
    }
    tests.append(check(
        "Versions attendues exactes",
        daily_run.EXPECTED_VERSIONS == expected,
        str(daily_run.EXPECTED_VERSIONS),
    ))

    refresh_src = inspect.getsource(daily_run.step_refresh)
    tests.append(check(
        "Refresh reçoit le Preparation exact via --input",
        '"--input"' in refresh_src and "prep_path" in refresh_src,
    ))

    recheck_src = inspect.getsource(daily_run.step_recheck)
    tests.append(check(
        "Recheck protège le Refresh exact",
        "require_latest_exact" in recheck_src,
    ))

    final_src = inspect.getsource(daily_run.step_final_pool)
    tests.append(check(
        "Final Pool protège Refresh + Recheck",
        final_src.count("require_latest_exact") >= 2,
    ))

    handoff_src = inspect.getsource(daily_run.step_handoff)
    tests.append(check(
        "Handoff protège le Final Pool exact",
        "require_latest_exact" in handoff_src,
    ))

    tests.append(check(
        "Manifest atomique",
        "atomic_json_write" in inspect.getsource(daily_run.save_manifest),
    ))

    tests.append(check(
        "Subprocess utilise sys.executable",
        "sys.executable" in inspect.getsource(daily_run.step_main),
    ))

    tests.append(check(
        "Aucun statut APPLIED dans l'orchestrateur",
        "APPLIED" not in Path(daily_run.__file__).read_text(
            encoding="utf-8",
            errors="replace",
        ).replace(
            "aucun statut APPLIED n'est modifié",
            ""
        ),
    ))

    tests.append(check(
        "Resume présent",
        callable(daily_run.normalize_manifest_for_resume),
    ))

    tests.append(check(
        "Lock présent",
        daily_run.LOCK_PATH.name == ".daily_run.lock",
        str(daily_run.LOCK_PATH),
    ))

    passed = sum(tests)
    total = len(tests)

    print()
    print(f"Tests : {passed}/{total}")

    log_dir = daily_run.LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = log_dir / f"daily_run_v1_audit_{stamp}.txt"

    status = (
        "✅ DAILY RUN V1.0 VALIDÉ STRUCTURELLEMENT."
        if all(tests)
        else "❌ DAILY RUN V1.0 NON VALIDÉ."
    )

    out.write_text(
        "\n".join([
            "DAILY RUN V1.0 - AUDIT STRUCTUREL",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status,
        ]),
        encoding="utf-8",
    )

    print(status)
    print("TXT audit :", out)

    if not all(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
