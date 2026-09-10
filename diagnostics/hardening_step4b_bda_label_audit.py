from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config.candidate_truth import (
    CANDIDATE_TRUTH,
    build_handoff_candidate_truth,
)

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
    print("HARDENING STEP 4B - BDA LABEL COMPATIBILITY AUDIT")
    print("=" * 100)

    tests = []

    canonical_bda = next(
        x
        for x in CANDIDATE_TRUTH["education"]
        if "Business Data Analysis" in x["degree"]
    )
    handoff = build_handoff_candidate_truth()
    handoff_bda = next(
        x
        for x in handoff["degrees"]
        if "Business Data Analysis" in x["label"]
    )

    tests.append(check(
        "Vérité canonique conserve 'en'",
        canonical_bda["degree"]
        == "Bachelier de spécialisation en Business Data Analysis",
        canonical_bda["degree"],
    ))

    tests.append(check(
        "Adaptateur Handoff expose ancien libellé compatible",
        handoff_bda["label"]
        == "Bachelier de spécialisation Business Data Analysis",
        handoff_bda["label"],
    ))

    tests.append(check(
        "BDA reste completed dans Handoff",
        handoff_bda.get("status") == "completed",
        str(handoff_bda.get("status")),
    ))

    proc4b = subprocess.run(
        [
            sys.executable,
            "-m",
            "diagnostics.hardening_step4b_candidate_truth_audit",
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
        "Audit Step 4B complet passe",
        proc4b.returncode == 0,
        f"code={proc4b.returncode}",
    ))

    passed = sum(tests)
    total = len(tests)
    status = (
        "HARDENING STEP 4B BDA HOTFIX VALIDÉ."
        if all(tests)
        else "HARDENING STEP 4B BDA HOTFIX NON VALIDÉ."
    )

    print()
    print(f"Tests : {passed}/{total}")
    print(status)

    log_dir = ROOT / "exports" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = log_dir / f"hardening_step4b_bda_label_audit_{stamp}.json"
    txt_path = log_dir / f"hardening_step4b_bda_label_audit_{stamp}.txt"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "canonical_bda_label": canonical_bda["degree"],
        "handoff_bda_label": handoff_bda["label"],
        "step4b_returncode": proc4b.returncode,
        "step4b_output_tail": proc4b.stdout[-5000:],
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "HARDENING STEP 4B - BDA LABEL COMPATIBILITY AUDIT",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status,
            f"Canonical : {canonical_bda['degree']}",
            f"Handoff   : {handoff_bda['label']}",
            f"Step 4B rc: {proc4b.returncode}",
        ]),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        print(proc4b.stdout[-3000:])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
