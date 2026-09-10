"""
HARDENING STEP 2 - DIAGNOSTICS ROBUSTNESS AUDIT

Usage:
    python -m diagnostics.hardening_step2_diagnostics_audit

No network.
No collection.
No DB write.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from diagnostics.version_support import at_least, version_tuple


TARGETS = [
    "diagnostics.daily_run_v101_encoding_audit",
    "diagnostics.daily_run_v102_refresh_status_audit",
    "diagnostics.delta_tracker_v1_audit",
    "diagnostics.delta_tracker_v11_repost_audit",
    "diagnostics.daily_run_v110_delta_integration_audit",
]


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f" | {detail}" if detail else ""))
    return ok



def utf8_subprocess_env():
    """
    Force UTF-8 dans les sous-processus Python.

    Sous Windows, lorsqu'un stdout est redirigé vers PIPE, Python peut
    sélectionner cp1252. Les audits utilisent des symboles Unicode (✅/❌),
    ce qui provoque alors UnicodeEncodeError avant même l'exécution des tests.
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def main():
    print("=" * 100)
    print("HARDENING STEP 2 - DIAGNOSTICS ROBUSTNESS AUDIT")
    print("=" * 100)
    print()

    tests = []

    # Structured version semantics.
    tests.append(check("1.1.1 >= 1.0.1", at_least("1.1.1", "1.0.1")))
    tests.append(check("1.1 >= 1.1", at_least("1.1", "1.1")))
    tests.append(check("1.10.0 > 1.9.9", at_least("1.10.0", "1.9.9")))
    tests.append(check("1.0 < 1.0.1", not at_least("1.0", "1.0.1")))
    tests.append(check("v2.0 parsé", version_tuple("v2.0") == (2, 0)))

    results = {}

    for module in TARGETS:
        proc = subprocess.run(
            [sys.executable, "-m", module],
            env=utf8_subprocess_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        results[module] = {
            "returncode": proc.returncode,
            "output_tail": proc.stdout[-4000:],
        }
        tests.append(check(
            module,
            proc.returncode == 0,
            f"code={proc.returncode}",
        ))

    passed = sum(tests)
    total = len(tests)
    status = (
        "✅ HARDENING STEP 2 VALIDÉ."
        if all(tests)
        else "❌ HARDENING STEP 2 NON VALIDÉ."
    )

    print()
    print(f"Tests : {passed}/{total}")
    print(status)

    log_dir = Path(__file__).resolve().parents[1] / "exports" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = log_dir / f"hardening_step2_diagnostics_audit_{stamp}.json"
    txt_path = log_dir / f"hardening_step2_diagnostics_audit_{stamp}.txt"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "target_results": results,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "HARDENING STEP 2 - DIAGNOSTICS ROBUSTNESS AUDIT",
        "=" * 100,
        f"Tests : {passed}/{total}",
        status,
        "",
    ]
    for module, info in results.items():
        lines.append(f"{module}: code={info['returncode']}")
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
