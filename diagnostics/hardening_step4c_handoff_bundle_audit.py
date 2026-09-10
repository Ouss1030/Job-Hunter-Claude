from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import applications.chatgpt_handoff as handoff
from diagnostics.version_support import at_least

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


def read_zip_json(zf, name):
    return json.loads(zf.read(name).decode("utf-8-sig"))


def inspect_zip(path):
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        job_names = [x for x in names if x.endswith("/job.json")]
        prompt_names = [x for x in names if x.endswith("/PROMPT_CHATGPT.txt")]

        jobs = [read_zip_json(zf, x) for x in job_names]
        candidate = read_zip_json(zf, "candidate_truth.json")
        instructions = read_zip_json(zf, "application_instructions.json")
        manifest = read_zip_json(zf, "manifest.json")

        prompts_ok = True
        for name in prompt_names:
            text = zf.read(name).decode("utf-8-sig")
            if (
                "candidate_truth.json" not in text
                or "application_instructions.json" not in text
            ):
                prompts_ok = False

        new_sizes = []
        old_sizes = []
        for job in jobs:
            new_sizes.append(
                len(json.dumps(job, ensure_ascii=False, indent=2).encode("utf-8"))
            )
            old_job = {
                **job,
                "candidate_truth": handoff.CANDIDATE_TRUTH,
                "application_instructions": handoff.APPLICATION_INSTRUCTIONS,
            }
            old_sizes.append(
                len(json.dumps(old_job, ensure_ascii=False, indent=2).encode("utf-8"))
            )

        return {
            "job_count": len(jobs),
            "candidate": candidate,
            "instructions": instructions,
            "manifest": manifest,
            "job_has_truth": any("candidate_truth" in job for job in jobs),
            "job_has_instructions": any(
                "application_instructions" in job for job in jobs
            ),
            "prompts_ok": prompts_ok,
            "new_sizes": new_sizes,
            "old_sizes": old_sizes,
        }


def main():
    print("=" * 100)
    print("HARDENING STEP 4C - HANDOFF BUNDLE DEDUP AUDIT")
    print("=" * 100)

    tests = []

    tests.append(check(
        "HANDOFF_VERSION reste 1.0",
        handoff.HANDOFF_VERSION == "1.0",
        handoff.HANDOFF_VERSION,
    ))

    tests.append(check(
        "Bundle schema au moins 1.1",
        at_least(str(getattr(handoff, "HANDOFF_BUNDLE_SCHEMA_VERSION", "0")), "1.1"),
        str(getattr(handoff, "HANDOFF_BUNDLE_SCHEMA_VERSION", None)),
    ))

    tests.append(check(
        "CV de base canonique",
        handoff.BASE_CV_PREFERENCE == handoff.DEFAULT_BASE_CV_NAME,
        handoff.BASE_CV_PREFERENCE,
    ))

    source = handoff.latest_file("final_application_pool_v12_*.json")
    tests.append(check("Final Pool disponible", source is not None, str(source)))
    if source is None:
        raise SystemExit(1)

    payload = handoff.load_json(source)
    selected = handoff.select_items(
        payload,
        actions=["APPLY_NOW"],
        start=1,
        limit=2,
    )
    tests.append(check("2 APPLY_NOW pour le test", len(selected) == 2, str(len(selected))))
    if len(selected) != 2:
        raise SystemExit(1)

    compact = [handoff.compact_job(x) for x in selected]
    tests.append(check(
        "compact_job sans candidate_truth",
        all("candidate_truth" not in x for x in compact),
    ))
    tests.append(check(
        "compact_job sans application_instructions",
        all("application_instructions" not in x for x in compact),
    ))

    with tempfile.TemporaryDirectory(prefix="jobhunter_step4c_") as tmp:
        original_export_root = handoff.EXPORT_ROOT
        try:
            handoff.EXPORT_ROOT = Path(tmp)
            result = handoff.export_handoff(
                actions=["APPLY_NOW"],
                start=1,
                limit=2,
                chunk_size=1,
            )
        finally:
            handoff.EXPORT_ROOT = original_export_root

        full = inspect_zip(result["full_zip"])
        chunks = [inspect_zip(x) for x in result["chunk_zips"]]

        tests.append(check(
            "ALL.zip fichiers globaux corrects",
            full["candidate"] == handoff.CANDIDATE_TRUTH
            and full["instructions"] == handoff.APPLICATION_INSTRUCTIONS,
        ))

        tests.append(check(
            "ALL.zip job.json dédupliqués",
            not full["job_has_truth"]
            and not full["job_has_instructions"],
        ))

        tests.append(check(
            "Prompts référencent les fichiers globaux",
            full["prompts_ok"],
        ))

        tests.append(check(
            "Manifest schema au moins 1.1",
            at_least(str(full["manifest"].get("bundle_schema_version") or "0"), "1.1"),
            str(full["manifest"].get("bundle_schema_version")),
        ))

        tests.append(check(
            "Chaque chunk autonome et dédupliqué",
            len(chunks) == 2
            and all(
                info["candidate"] == handoff.CANDIDATE_TRUTH
                and info["instructions"] == handoff.APPLICATION_INSTRUCTIONS
                and not info["job_has_truth"]
                and not info["job_has_instructions"]
                for info in chunks
            ),
        ))

        old_total = sum(full["old_sizes"])
        new_total = sum(full["new_sizes"])
        reduction_pct = round(
            ((old_total - new_total) / old_total * 100) if old_total else 0.0,
            2,
        )

        tests.append(check(
            "Taille job.json réellement réduite",
            new_total < old_total,
            f"{old_total} -> {new_total} bytes ({reduction_pct}% en moins)",
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
        "Ancien audit Handoff reste vert",
        proc.returncode == 0,
        f"code={proc.returncode}",
    ))

    passed = sum(tests)
    total = len(tests)
    status = (
        "HARDENING STEP 4C VALIDÉ."
        if all(tests)
        else "HARDENING STEP 4C NON VALIDÉ."
    )

    print()
    print(f"Tests : {passed}/{total}")
    print(status)

    log_dir = ROOT / "exports" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = log_dir / f"hardening_step4c_handoff_bundle_audit_{stamp}.json"
    txt_path = log_dir / f"hardening_step4c_handoff_bundle_audit_{stamp}.txt"

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "handoff_version": handoff.HANDOFF_VERSION,
        "bundle_schema_version": getattr(
            handoff,
            "HANDOFF_BUNDLE_SCHEMA_VERSION",
            None,
        ),
        "test_job_count": 2,
        "old_serialized_job_bytes": old_total,
        "new_serialized_job_bytes": new_total,
        "reduction_pct": reduction_pct,
        "historical_handoff_audit_returncode": proc.returncode,
        "historical_handoff_audit_output_tail": proc.stdout[-5000:],
    }

    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "HARDENING STEP 4C - HANDOFF BUNDLE DEDUP AUDIT",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status,
            f"Handoff version : {handoff.HANDOFF_VERSION}",
            f"Bundle schema   : {getattr(handoff, 'HANDOFF_BUNDLE_SCHEMA_VERSION', None)}",
            f"job.json bytes  : {old_total} -> {new_total} ({reduction_pct}% en moins)",
            f"Old audit rc    : {proc.returncode}",
        ]),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        print(proc.stdout[-3000:])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
