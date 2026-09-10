"""
HARDENING STEP 3 V2 AUDIT

Usage:
    python -m diagnostics.hardening_step3_v2_audit
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "diagnostics" / "chatgpt_handoff_v1_audit.py"


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" | {detail}" if detail else ""))
    return ok


def child_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def main():
    print("=" * 100)
    print("HARDENING STEP 3 V2 - HANDOFF AUDIT DYNAMIC COUNT")
    print("=" * 100)

    tests = []
    tests.append(check("Audit Handoff present", TARGET.exists(), str(TARGET)))
    if not TARGET.exists():
        raise SystemExit(1)

    text = TARGET.read_text(encoding="utf-8", errors="strict")

    tests.append(check(
        "Ancien libelle 37 APPLY_NOW absent",
        "37 APPLY_NOW" not in text,
    ))
    tests.append(check(
        "Ancienne condition == 37 absente",
        "len(apply_now) == 37" not in text,
    ))
    tests.append(check(
        "Nouveau test dynamique present",
        "Au moins une APPLY_NOW" in text
        and "len(apply_now) > 0" in text,
    ))

    proc = subprocess.run(
        [sys.executable, "-m", "diagnostics.chatgpt_handoff_v1_audit"],
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
        "Audit Handoff existant passe",
        proc.returncode == 0,
        f"code={proc.returncode}",
    ))

    tests.append(check(
        "Sortie Handoff utilise le test dynamique",
        "Au moins une APPLY_NOW" in proc.stdout
        and "37 APPLY_NOW" not in proc.stdout,
    ))

    passed = sum(tests)
    total = len(tests)
    status = (
        "HARDENING STEP 3 V2 VALIDE."
        if all(tests)
        else "HARDENING STEP 3 V2 NON VALIDE."
    )

    print()
    print(f"Tests : {passed}/{total}")
    print(status)

    log_dir = ROOT / "exports" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = log_dir / f"hardening_step3_v2_audit_{stamp}.json"
    txt_path = log_dir / f"hardening_step3_v2_audit_{stamp}.txt"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "handoff_audit_returncode": proc.returncode,
        "handoff_audit_output_tail": proc.stdout[-6000:],
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "HARDENING STEP 3 V2 - HANDOFF AUDIT DYNAMIC COUNT",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status,
            f"Handoff audit return code : {proc.returncode}",
        ]),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        print(proc.stdout[-4000:])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
