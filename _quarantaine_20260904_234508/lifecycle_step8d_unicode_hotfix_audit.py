from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import lifecycle

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "exports" / "logs"


def check(label, condition, detail=""):
    ok = bool(condition)
    print(
        f"[{'PASS' if ok else 'FAIL'}] {label}"
        + (f" | {detail}" if detail else "")
    )
    return ok


def child_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def main():
    print("=" * 100)
    print("LIFECYCLE STEP 8D - UNICODE HOTFIX AUDIT")
    print("=" * 100)

    tests = []
    cases = {
        "postulé": "APPLIED",
        "postulée": "APPLIED",
        "refusé": "REJECTED",
        "refusée": "REJECTED",
        "fermé": "CLOSED",
        "fermée": "CLOSED",
        "retiré": "WITHDRAWN",
        "retirée": "WITHDRAWN",
        "prêt": "READY",
        "prête": "READY",
    }

    details = {}
    accent_ok = True

    for raw, expected in cases.items():
        try:
            got = lifecycle.normalize_status(raw)
        except Exception as exc:
            got = f"ERROR:{exc}"
        details[raw] = got
        accent_ok = accent_ok and (got == expected)

    tests.append(check(
        "French accented aliases normalize correctly",
        accent_ok,
        str(details),
    ))
    tests.append(check(
        "Canonical APPLIED still accepted",
        lifecycle.normalize_status("APPLIED") == "APPLIED",
    ))
    tests.append(check(
        "Canonical DOCUMENTS_READY still accepted",
        lifecycle.normalize_status("DOCUMENTS_READY")
        == "DOCUMENTS_READY",
    ))

    proc = subprocess.run(
        [sys.executable, "lifecycle_step8d_manual_cli_audit.py"],
        cwd=ROOT,
        env=child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    tests.append(check(
        "Original Step 8D audit now passes",
        proc.returncode == 0,
        f"code={proc.returncode}",
    ))
    tests.append(check(
        "Original Step 8D reports VALIDE",
        "LIFECYCLE TRACKER STEP 8D VALIDE." in proc.stdout,
    ))

    passed = sum(tests)
    total = len(tests)

    status = (
        "LIFECYCLE STEP 8D UNICODE HOTFIX VALIDE."
        if all(tests)
        else "LIFECYCLE STEP 8D UNICODE HOTFIX NON VALIDE."
    )

    print()
    print(f"Tests : {passed}/{total}")
    print(status)

    if proc.stdout:
        print()
        print("Original Step 8D audit tail:")
        print(proc.stdout[-3000:])

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = (
        LOG_DIR
        / f"lifecycle_step8d_unicode_hotfix_audit_{stamp}.json"
    )
    txt_path = (
        LOG_DIR
        / f"lifecycle_step8d_unicode_hotfix_audit_{stamp}.txt"
    )

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "accent_cases": details,
        "original_step8d_returncode": proc.returncode,
        "original_step8d_output_tail": proc.stdout[-5000:],
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "LIFECYCLE STEP 8D - UNICODE HOTFIX AUDIT",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status,
            f"Original Step8D rc : {proc.returncode}",
        ]),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
