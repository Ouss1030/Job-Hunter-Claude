from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(label, condition, detail=""):
    ok = bool(condition)
    print(
        f"[{'OK' if ok else 'FAIL'}] {label}"
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
    print("HARDENING STEP 4C - IMPORT ORDER HOTFIX AUDIT")
    print("=" * 100)

    tests = []

    try:
        import applications.chatgpt_handoff as handoff
        imported = True
        import_error = ""
    except Exception as exc:
        imported = False
        import_error = repr(exc)
        handoff = None

    tests.append(check(
        "chatgpt_handoff importable",
        imported,
        import_error,
    ))

    if imported:
        tests.append(check(
            "HANDOFF_VERSION reste 1.0",
            handoff.HANDOFF_VERSION == "1.0",
            handoff.HANDOFF_VERSION,
        ))
        tests.append(check(
            "Bundle schema reste 1.1",
            getattr(handoff, "HANDOFF_BUNDLE_SCHEMA_VERSION", None) == "1.1",
            str(getattr(handoff, "HANDOFF_BUNDLE_SCHEMA_VERSION", None)),
        ))
        tests.append(check(
            "BASE_CV_PREFERENCE canonique",
            handoff.BASE_CV_PREFERENCE == handoff.DEFAULT_BASE_CV_NAME,
            handoff.BASE_CV_PREFERENCE,
        ))
    else:
        tests.extend([False, False, False])

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "diagnostics.hardening_step4c_handoff_bundle_audit",
        ],
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
        "Audit Step 4C complet exécutable",
        proc.returncode == 0,
        f"code={proc.returncode}",
    ))

    passed = sum(bool(x) for x in tests)
    total = len(tests)

    status = (
        "HARDENING STEP 4C IMPORT HOTFIX VALIDÉ."
        if passed == total
        else "HARDENING STEP 4C IMPORT HOTFIX NON VALIDÉ."
    )

    print()
    print(f"Tests : {passed}/{total}")
    print(status)

    log_dir = ROOT / "exports" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = log_dir / f"hardening_step4c_import_order_audit_{stamp}.json"
    txt_path = log_dir / f"hardening_step4c_import_order_audit_{stamp}.txt"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "import_error": import_error,
        "step4c_returncode": proc.returncode,
        "step4c_output_tail": proc.stdout[-6000:],
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "HARDENING STEP 4C - IMPORT ORDER HOTFIX AUDIT",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status,
            f"Step 4C rc : {proc.returncode}",
        ]),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if passed != total:
        print(proc.stdout[-4000:])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
