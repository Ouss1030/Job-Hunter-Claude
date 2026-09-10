from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import applications.chatgpt_handoff as handoff
import daily_run
from diagnostics import run_all

from diagnostics.version_support import at_least

ROOT = Path(__file__).resolve().parents[1]
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


def run_module(module, *args):
    proc = subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=ROOT,
        env=child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "module": module,
        "args": list(args),
        "returncode": proc.returncode,
        "output": proc.stdout,
    }


def latest_digit_artifact(pattern):
    candidates = []
    for path in LOG_DIR.glob("*"):
        if path.is_file() and fnmatch.fnmatch(path.name, pattern):
            candidates.append(path)
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def inspect_full_handoff_zip(path):
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        job_names = sorted(name for name in names if name.endswith("/job.json"))
        prompt_names = sorted(name for name in names if name.endswith("/PROMPT_CHATGPT.txt"))

        jobs = [
            json.loads(zf.read(name).decode("utf-8-sig"))
            for name in job_names
        ]

        manifest = json.loads(
            zf.read("manifest.json").decode("utf-8-sig")
        )
        candidate_truth = json.loads(
            zf.read("candidate_truth.json").decode("utf-8-sig")
        )
        application_instructions = json.loads(
            zf.read("application_instructions.json").decode("utf-8-sig")
        )

        prompts_ok = True
        for name in prompt_names:
            text = zf.read(name).decode("utf-8-sig")
            if (
                "candidate_truth.json" not in text
                or "application_instructions.json" not in text
            ):
                prompts_ok = False

        return {
            "names": names,
            "jobs": jobs,
            "manifest": manifest,
            "candidate_truth": candidate_truth,
            "application_instructions": application_instructions,
            "prompts_ok": prompts_ok,
        }


def canonical_json_list(items):
    return sorted(
        json.dumps(
            item,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for item in items
    )


def main():
    print("=" * 100)
    print("HARDENING STEP 7 - FINAL OFFLINE / REPLAY VALIDATION")
    print("=" * 100)
    print("Aucun réseau. Aucun main.py. Aucun daily_run.py.")
    print()

    tests = []
    subprocess_reports = []

    # ------------------------------------------------------------------
    # A. Classification
    # ------------------------------------------------------------------
    classification = run_all.classification_status()
    tests.append(check(
        "Classification diagnostics exhaustive",
        classification["ok"],
        (
            f"{classification['classified_count']}/"
            f"{classification['discovered_count']} "
            f"unclassified={classification['unclassified']} "
            f"missing={classification['missing_on_disk']}"
        ),
    ))

    # ------------------------------------------------------------------
    # B. Suite active officielle
    # ------------------------------------------------------------------
    suite = run_module("diagnostics.run_all")
    subprocess_reports.append(suite)
    tests.append(check(
        "Suite active run_all passe",
        suite["returncode"] == 0,
        f"code={suite['returncode']}",
    ))
    # La suite ne doit pas RÉTRÉCIR. Épingler le compte exact fait échouer
    # l'audit à chaque diagnostic ajouté, ce qui est l'inverse du but.
    tests.append(check(
        "Suite active d'au moins 25 diagnostics",
        len(run_all.SUITE_ACTIVE) >= 25,
        str(len(run_all.SUITE_ACTIVE)),
    ))

    # ------------------------------------------------------------------
    # C. Hardening audits non inclus / structure finale
    # ------------------------------------------------------------------
    extra_modules = [
        "diagnostics.hardening_step2_diagnostics_audit",
        "diagnostics.hardening_step3_v2_audit",
        "diagnostics.hardening_step5b_run_all_audit",
        "diagnostics.hardening_step6b_requirements_audit",
    ]

    extras_ok = True
    for module in extra_modules:
        report = run_module(module)
        subprocess_reports.append(report)
        if report["returncode"] != 0:
            extras_ok = False

    tests.append(check(
        "Audits hardening complementaires passent",
        extras_ok,
        ", ".join(
            f"{r['module']}={r['returncode']}"
            for r in subprocess_reports[1:]
        ),
    ))

    # ------------------------------------------------------------------
    # D. Daily Run structure only — no execution.
    # ------------------------------------------------------------------
    tests.append(check(
        "Daily Run au moins 1.1.1",
        at_least(getattr(daily_run, "DAILY_RUN_VERSION", "0"), "1.1.1"),
        str(getattr(daily_run, "DAILY_RUN_VERSION", None)),
    ))

    expected_order = [
        "main",
        "preparation",
        "refresh",
        "recheck",
        "final_pool",
        "delta",
        "handoff",
    ]
    # Ce qui doit être garanti, c'est que les étapes attendues sont présentes
    # DANS CET ORDRE — pas qu'aucune étape ne soit jamais ajoutée. L'étape
    # "lifecycle" a été insérée après coup entre delta et handoff.
    installe = list(getattr(daily_run, "STEP_ORDER", []))
    positions = [installe.index(e) for e in expected_order if e in installe]
    tests.append(check(
        "Pipeline Daily Run conserve les étapes attendues dans l'ordre",
        len(positions) == len(expected_order)
        and positions == sorted(positions),
        str(installe),
    ))

    # ------------------------------------------------------------------
    # E. Saved artifact chain — read-only.
    # ------------------------------------------------------------------
    patterns = {
        "main_log": "job_hunter_main_v10_4_[0-9]*.txt",
        "gate_json": "application_gate_v1_[0-9]*.json",
        "queue_json": "application_queue_v1_[0-9]*.json",
        "preparation_json": "application_preparation_v1_[0-9]*.json",
        "refresh_json": "job_refresh_v1_[0-9]*.json",
        "recheck_json": "application_recheck_v1_[0-9]*.json",
        "final_pool_json": "final_application_pool_v12_[0-9]*.json",
        "delta_json": "delta_tracker_v1_[0-9]*.json",
    }

    artifacts = {
        key: latest_digit_artifact(pattern)
        for key, pattern in patterns.items()
    }

    tests.append(check(
        "Chaine d'artefacts sauvegardee complete",
        all(artifacts.values()),
        str({
            k: (v.name if v else None)
            for k, v in artifacts.items()
        }),
    ))

    final_pool_path = artifacts["final_pool_json"]
    delta_path = artifacts["delta_json"]

    # Robust lineage property: latest Delta must explicitly refer to the
    # exact latest current Final Pool basename somewhere in its JSON payload.
    lineage_ok = False
    if final_pool_path and delta_path:
        delta_payload = load_json(delta_path)
        delta_serialized = json.dumps(
            delta_payload,
            ensure_ascii=False,
        )
        lineage_ok = final_pool_path.name in delta_serialized

    tests.append(check(
        "Delta reference le Final Pool courant",
        lineage_ok,
        (
            f"final_pool={final_pool_path.name if final_pool_path else None} "
            f"delta={delta_path.name if delta_path else None}"
        ),
    ))

    # ------------------------------------------------------------------
    # F. Full temporary Handoff replay from current Final Pool.
    # ------------------------------------------------------------------
    pool_path = handoff.latest_file("final_application_pool_v12_[0-9]*.json")
    if pool_path is None:
        # Compatibility fallback if helper uses pathlib.glob semantics.
        pool_path = final_pool_path

    pool_payload = handoff.load_json(pool_path)
    expected_items = handoff.select_items(
        pool_payload,
        actions=["APPLY_NOW"],
        start=1,
        limit=10000,
    )
    expected_jobs = [
        handoff.compact_job(item)
        for item in expected_items
    ]

    tests.append(check(
        "Final Pool contient au moins un APPLY_NOW",
        len(expected_items) > 0,
        str(len(expected_items)),
    ))

    with tempfile.TemporaryDirectory(prefix="jobhunter_step7_") as tmp:
        original_export_root = handoff.EXPORT_ROOT
        try:
            handoff.EXPORT_ROOT = Path(tmp)
            result = handoff.export_handoff(
                actions=["APPLY_NOW"],
                start=1,
                limit=10000,
                chunk_size=10,
            )
        finally:
            handoff.EXPORT_ROOT = original_export_root

        full = inspect_full_handoff_zip(result["full_zip"])

        tests.append(check(
            "Handoff temporaire contient toutes les APPLY_NOW",
            len(full["jobs"]) == len(expected_jobs),
            f"{len(full['jobs'])}/{len(expected_jobs)}",
        ))

        tests.append(check(
            "Handoff temporaire preserve exactement compact_job",
            canonical_json_list(full["jobs"])
            == canonical_json_list(expected_jobs),
        ))

        tests.append(check(
            "Handoff schema 1.1 et fichiers globaux corrects",
            (
                full["manifest"].get("bundle_schema_version") == "1.1"
                and full["candidate_truth"] == handoff.CANDIDATE_TRUTH
                and full["application_instructions"]
                == handoff.APPLICATION_INSTRUCTIONS
            ),
            str(full["manifest"].get("bundle_schema_version")),
        ))

        no_dup = all(
            "candidate_truth" not in job
            and "application_instructions" not in job
            for job in full["jobs"]
        )
        tests.append(check(
            "Aucun job.json ne duplique les blocs globaux",
            no_dup,
        ))

        tests.append(check(
            "Tous les prompts referencent les fichiers globaux",
            full["prompts_ok"],
        ))

        new_total = sum(
            len(
                json.dumps(
                    job,
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8")
            )
            for job in full["jobs"]
        )
        old_total = 0
        for job in full["jobs"]:
            old_job = {
                **job,
                "candidate_truth": handoff.CANDIDATE_TRUTH,
                "application_instructions":
                    handoff.APPLICATION_INSTRUCTIONS,
            }
            old_total += len(
                json.dumps(
                    old_job,
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8")
            )

        reduction_pct = round(
            (
                (old_total - new_total)
                / old_total
                * 100
            )
            if old_total
            else 0.0,
            2,
        )

        tests.append(check(
            "Deduplication reduit le poids total des job.json",
            new_total < old_total,
            f"{old_total} -> {new_total} bytes ({reduction_pct}% en moins)",
        ))

    # ------------------------------------------------------------------
    # G. Final report
    # ------------------------------------------------------------------
    passed = sum(tests)
    total = len(tests)
    status = (
        "HARDENING STEP 7 VALIDE."
        if all(tests)
        else "HARDENING STEP 7 NON VALIDE."
    )

    print()
    print("=" * 100)
    print(f"Tests : {passed}/{total}")
    print(status)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = LOG_DIR / f"hardening_step7_final_validation_{stamp}.json"
    txt_path = LOG_DIR / f"hardening_step7_final_validation_{stamp}.txt"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "OFFLINE_REPLAY",
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "classification": {
            "ok": classification["ok"],
            "discovered_count": classification["discovered_count"],
            "classified_count": classification["classified_count"],
            "unclassified": classification["unclassified"],
            "missing_on_disk": classification["missing_on_disk"],
        },
        "suite_active_count": len(run_all.SUITE_ACTIVE),
        "saved_artifacts": {
            key: str(path) if path else None
            for key, path in artifacts.items()
        },
        "current_final_pool": str(pool_path),
        "temporary_handoff_apply_now_count": len(expected_items),
        "temporary_handoff_old_job_bytes": old_total,
        "temporary_handoff_new_job_bytes": new_total,
        "temporary_handoff_reduction_pct": reduction_pct,
        "subprocesses": [
            {
                "module": row["module"],
                "args": row["args"],
                "returncode": row["returncode"],
                "output_tail": row["output"][-6000:],
            }
            for row in subprocess_reports
        ],
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "HARDENING STEP 7 - FINAL OFFLINE / REPLAY VALIDATION",
        "=" * 100,
        f"Tests : {passed}/{total}",
        status,
        f"Classification : {classification['classified_count']}/{classification['discovered_count']}",
        f"Suite active    : {len(run_all.SUITE_ACTIVE)}",
        f"APPLY_NOW replay: {len(expected_items)}",
        f"job.json bytes  : {old_total} -> {new_total} ({reduction_pct}% en moins)",
        "",
        "Subprocesses:",
    ]
    for row in subprocess_reports:
        lines.append(
            f"- {row['module']} : rc={row['returncode']}"
        )

    txt_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        print()
        print("ECHECS / SORTIES UTILES")
        print("-" * 100)
        for row in subprocess_reports:
            if row["returncode"] != 0:
                print(row["module"])
                print(row["output"][-4000:])
                print("-" * 100)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
