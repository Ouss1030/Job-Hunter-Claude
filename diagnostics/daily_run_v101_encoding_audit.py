"""
DAILY RUN V1.0.1 - ENCODING HOTFIX AUDIT

Usage:
    python -m diagnostics.daily_run_v101_encoding_audit

Aucun réseau.
Aucune collecte.
Aucune écriture DB.
"""

import inspect
import os
import subprocess
import sys

import daily_run
from diagnostics.version_support import at_least


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f" | {detail}" if detail else ""))
    return ok


def main():
    tests = []

    print("=" * 100)
    print("DAILY RUN V1.0.1 - ENCODING HOTFIX AUDIT")
    print("=" * 100)
    print()

    tests.append(check(
        "Version >= 1.0.1",
        at_least(daily_run.DAILY_RUN_VERSION, "1.0.1"),
        daily_run.DAILY_RUN_VERSION,
    ))

    source = inspect.getsource(daily_run.run_command)

    tests.append(check(
        "PYTHONIOENCODING=utf-8 forcé",
        'child_env["PYTHONIOENCODING"] = "utf-8"' in source,
    ))

    tests.append(check(
        "PYTHONUTF8=1 forcé",
        'child_env["PYTHONUTF8"] = "1"' in source,
    ))

    tests.append(check(
        "Sous-processus reçoit env UTF-8",
        "env=child_env" in source,
    ))

    tests.append(check(
        "Décodage stdout UTF-8",
        'encoding="utf-8"' in source,
    ))

    tests.append(check(
        "Logs écrits avant affichage console",
        source.find("log.write(line)") < source.find('print(line, end="")'),
    ))

    tests.append(check(
        "Fallback console UnicodeEncodeError",
        "except UnicodeEncodeError" in source,
    ))

    # Propriété durable : un ancien manifest V1.0 doit pouvoir être
    # repris par la version courante de Daily Run sans perdre les étapes
    # déjà DONE. On teste le comportement réel plutôt qu'une chaîne
    # de versions figée dans le code source.
    old_step_names = [
        step
        for step in (
            "main",
            "preparation",
            "refresh",
            "recheck",
            "final_pool",
            "handoff",
        )
        if step in daily_run.STEP_ORDER
    ]

    def _step(status="PENDING"):
        return {
            "status": status,
            "started_at": None,
            "finished_at": None,
            "command": None,
            "log": None,
            "artifacts": {},
            "validation": {},
            "error": None,
        }

    legacy_manifest = {
        "daily_run_version": "1.0",
        "run_id": "ENCODING_AUDIT_V1_RESUME",
        "status": "FAILED",
        "finished_at": None,
        "last_error": "synthetic",
        "resume_count": 0,
        "steps": {
            name: _step("DONE" if name == "main" else "PENDING")
            for name in old_step_names
        },
    }

    original_save_manifest = daily_run.save_manifest
    daily_run.save_manifest = lambda manifest: None
    try:
        migrated = daily_run.normalize_manifest_for_resume(
            legacy_manifest
        )
    except Exception:
        migrated = None
    finally:
        daily_run.save_manifest = original_save_manifest

    resume_ok = bool(
        migrated
        and migrated.get("daily_run_version")
        == daily_run.DAILY_RUN_VERSION
        and migrated.get("steps", {}).get("main", {}).get("status")
        == "DONE"
        and migrated.get("resume_count") == 1
        and all(
            step in migrated.get("steps", {})
            for step in daily_run.STEP_ORDER
        )
    )

    tests.append(check(
        "Manifest V1.0 repris par la version courante",
        resume_ok,
        (
            migrated.get("daily_run_version")
            if migrated
            else "migration failed"
        ),
    ))

    # Test local sans réseau : un enfant Python doit pouvoir émettre l'emoji
    # qui faisait planter Application Preparation sous Windows.
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    proc = subprocess.run(
        [sys.executable, "-c", 'print("⚠️ UTF-8 OK — éàç")'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="strict",
        env=env,
        check=False,
    )

    tests.append(check(
        "Sous-processus Unicode retourne code 0",
        proc.returncode == 0,
        f"code={proc.returncode}",
    ))

    tests.append(check(
        "Emoji et accents préservés",
        "⚠️ UTF-8 OK — éàç" in proc.stdout,
        proc.stdout.strip(),
    ))

    print()
    print(f"Tests : {sum(tests)}/{len(tests)}")

    if not all(tests):
        raise SystemExit("❌ ENCODING HOTFIX NON VALIDÉ.")

    print("✅ ENCODING HOTFIX (>= V1.0.1) VALIDÉ.")


if __name__ == "__main__":
    main()
