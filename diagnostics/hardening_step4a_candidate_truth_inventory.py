"""
HARDENING STEP 4A - CANDIDATE TRUTH INVENTORY

Lecture seule.
Aucun réseau.
Aucune DB.
Aucun Handoff régénéré.

Usage:
    python -m diagnostics.hardening_step4a_candidate_truth_inventory
"""

from __future__ import annotations

import ast
import importlib
import json
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AI_PATH = ROOT / "config" / "ai_generation.py"
HANDOFF_PATH = ROOT / "applications" / "chatgpt_handoff.py"
HANDOFF_EXPORT_DIR = ROOT / "exports" / "chatgpt_handoff"


def clean(value):
    if value is None:
        return None
    return value


def safe_sorted_strings(value):
    if value is None:
        return []
    if isinstance(value, (set, tuple, list)):
        return sorted(str(x) for x in value)
    return [str(value)]


def safe_dict(value):
    return value if isinstance(value, dict) else {}


def import_module(name):
    return importlib.import_module(name)


def source_info(path):
    if not path.exists():
        return {
            "exists": False,
            "path": str(path),
        }

    text = path.read_text(encoding="utf-8", errors="strict")

    info = {
        "exists": True,
        "path": str(path),
        "bytes": len(text.encode("utf-8")),
        "candidate_truth_mentions": text.count("CANDIDATE_TRUTH"),
        "candidate_truth_literal_mentions": text.count('"candidate_truth"')
            + text.count("'candidate_truth'"),
        "application_instructions_literal_mentions":
            text.count('"application_instructions"')
            + text.count("'application_instructions'"),
        "forbidden_terms_mentions":
            text.count("FORBIDDEN_CANDIDATE_CLAIM_TERMS"),
        "hard_truth_rules_mentions":
            text.count("HARD_TRUTH_RULES"),
    }

    try:
        tree = ast.parse(text)
    except Exception as exc:
        info["ast_error"] = str(exc)
        return info

    assignments = []
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            else:
                targets = [node.target]

            for target in targets:
                if isinstance(target, ast.Name):
                    if target.id in {
                        "CANDIDATE_TRUTH",
                        "FORBIDDEN_CANDIDATE_CLAIM_TERMS",
                        "DEFAULT_BASE_CV_NAME",
                        "HARD_TRUTH_RULES",
                    }:
                        assignments.append(target.id)

        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [alias.name for alias in node.names]
            if any(
                name in {
                    "CANDIDATE_TRUTH",
                    "FORBIDDEN_CANDIDATE_CLAIM_TERMS",
                    "DEFAULT_BASE_CV_NAME",
                    "HARD_TRUTH_RULES",
                }
                for name in names
            ):
                imports.append({
                    "from": module,
                    "names": names,
                })

    info["assignments"] = assignments
    info["relevant_imports"] = imports
    return info


def diff_dicts(left, right):
    left = safe_dict(left)
    right = safe_dict(right)

    left_keys = set(left)
    right_keys = set(right)

    result = {
        "left_only_keys": sorted(left_keys - right_keys),
        "right_only_keys": sorted(right_keys - left_keys),
        "shared_keys": sorted(left_keys & right_keys),
        "different_shared_values": {},
    }

    for key in sorted(left_keys & right_keys):
        if left.get(key) != right.get(key):
            result["different_shared_values"][key] = {
                "ai_generation": left.get(key),
                "chatgpt_handoff": right.get(key),
            }

    return result


def find_latest_handoff_zip():
    if not HANDOFF_EXPORT_DIR.exists():
        return None

    candidates = [
        p for p in HANDOFF_EXPORT_DIR.glob("handoff_v1_*_ALL.zip")
        if p.is_file()
    ]
    if not candidates:
        return None

    return max(candidates, key=lambda p: p.stat().st_mtime)


def inspect_handoff_zip(path):
    if path is None:
        return {
            "found": False,
        }

    result = {
        "found": True,
        "path": str(path),
        "job_json_count": 0,
        "job_json_with_candidate_truth": 0,
        "job_json_with_application_instructions": 0,
        "job_json_sizes": [],
        "root_json_candidates": [],
        "forbidden_term_hits": {},
    }

    forbidden_probe_terms = [
        "talend",
        "apache hop",
        "pl/sql",
        "empower",
        "tableau",
        "oracle",
    ]

    with zipfile.ZipFile(path, "r") as z:
        for name in z.namelist():
            lower = name.lower()
            if not lower.endswith(".json"):
                continue

            try:
                raw = z.read(name)
                data = json.loads(raw.decode("utf-8-sig"))
            except Exception:
                continue

            if isinstance(data, dict):
                if lower.endswith("job.json"):
                    result["job_json_count"] += 1
                    result["job_json_sizes"].append(len(raw))

                    if "candidate_truth" in data:
                        result["job_json_with_candidate_truth"] += 1
                    if "application_instructions" in data:
                        result["job_json_with_application_instructions"] += 1

                    text = json.dumps(data, ensure_ascii=False).lower()
                    for term in forbidden_probe_terms:
                        if term in text:
                            result["forbidden_term_hits"][term] = (
                                result["forbidden_term_hits"].get(term, 0) + 1
                            )

                else:
                    # Potential bundle/root metadata JSON.
                    if (
                        "candidate_truth" in data
                        or "application_instructions" in data
                    ):
                        result["root_json_candidates"].append({
                            "name": name,
                            "has_candidate_truth": "candidate_truth" in data,
                            "has_application_instructions":
                                "application_instructions" in data,
                            "size": len(raw),
                        })

    sizes = result["job_json_sizes"]
    result["job_json_average_size"] = (
        round(sum(sizes) / len(sizes), 2) if sizes else None
    )
    result["job_json_min_size"] = min(sizes) if sizes else None
    result["job_json_max_size"] = max(sizes) if sizes else None

    return result


def main():
    print("=" * 100)
    print("HARDENING STEP 4A - CANDIDATE TRUTH INVENTORY")
    print("=" * 100)
    print()

    checks = []

    def check(label, condition, detail=""):
        ok = bool(condition)
        checks.append(ok)
        print(
            f"[{'OK' if ok else 'FAIL'}] {label}"
            + (f" | {detail}" if detail else "")
        )
        return ok

    check("config/ai_generation.py present", AI_PATH.exists(), str(AI_PATH))
    check("applications/chatgpt_handoff.py present", HANDOFF_PATH.exists(), str(HANDOFF_PATH))

    if not AI_PATH.exists() or not HANDOFF_PATH.exists():
        raise SystemExit(1)

    ai_module = import_module("config.ai_generation")
    handoff_module = import_module("applications.chatgpt_handoff")

    ai_truth = getattr(ai_module, "CANDIDATE_TRUTH", None)
    handoff_truth = getattr(handoff_module, "CANDIDATE_TRUTH", None)

    check("AI CANDIDATE_TRUTH dict", isinstance(ai_truth, dict))
    check("Handoff CANDIDATE_TRUTH dict", isinstance(handoff_truth, dict))

    ai_forbidden = getattr(
        ai_module,
        "FORBIDDEN_CANDIDATE_CLAIM_TERMS",
        None,
    )
    handoff_forbidden = getattr(
        handoff_module,
        "FORBIDDEN_CANDIDATE_CLAIM_TERMS",
        None,
    )

    ai_default_cv = getattr(
        ai_module,
        "DEFAULT_BASE_CV_NAME",
        None,
    )
    handoff_default_cv = getattr(
        handoff_module,
        "DEFAULT_BASE_CV_NAME",
        None,
    )

    hard_truth_rules = getattr(
        handoff_module,
        "HARD_TRUTH_RULES",
        None,
    )

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "READ_ONLY",
        "checks_passed": sum(checks),
        "checks_total": len(checks),
        "source_files": {
            "ai_generation": source_info(AI_PATH),
            "chatgpt_handoff": source_info(HANDOFF_PATH),
        },
        "runtime": {
            "ai_generation": {
                "candidate_truth": ai_truth,
                "candidate_truth_keys":
                    sorted(ai_truth.keys()) if isinstance(ai_truth, dict) else [],
                "forbidden_candidate_claim_terms":
                    safe_sorted_strings(ai_forbidden),
                "default_base_cv_name": ai_default_cv,
            },
            "chatgpt_handoff": {
                "candidate_truth": handoff_truth,
                "candidate_truth_keys":
                    sorted(handoff_truth.keys()) if isinstance(handoff_truth, dict) else [],
                "forbidden_candidate_claim_terms":
                    safe_sorted_strings(handoff_forbidden),
                "default_base_cv_name": handoff_default_cv,
                "hard_truth_rules": hard_truth_rules,
            },
        },
        "candidate_truth_diff": diff_dicts(ai_truth, handoff_truth),
        "latest_handoff_zip": inspect_handoff_zip(
            find_latest_handoff_zip()
        ),
    }

    # Additional semantic probes.
    ai_truth_dict = safe_dict(ai_truth)
    handoff_truth_dict = safe_dict(handoff_truth)

    payload["semantic_probes"] = {
        "ai_unsupported_or_not_proven":
            ai_truth_dict.get("unsupported_or_not_proven"),
        "handoff_unsupported_or_not_proven":
            handoff_truth_dict.get("unsupported_or_not_proven"),
        "handoff_not_demonstrated":
            handoff_truth_dict.get("not_demonstrated"),
        "ai_forbidden_count": len(safe_sorted_strings(ai_forbidden)),
        "handoff_forbidden_count": len(safe_sorted_strings(handoff_forbidden)),
        "hard_truth_rules_present":
            hard_truth_rules is not None,
    }

    log_dir = ROOT / "exports" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = log_dir / f"hardening_step4a_candidate_truth_inventory_{stamp}.json"
    txt_path = log_dir / f"hardening_step4a_candidate_truth_inventory_{stamp}.txt"

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    diff = payload["candidate_truth_diff"]
    zip_info = payload["latest_handoff_zip"]

    lines = [
        "HARDENING STEP 4A - CANDIDATE TRUTH INVENTORY",
        "=" * 100,
        "Mode : READ_ONLY",
        "",
        f"AI truth keys      : {len(payload['runtime']['ai_generation']['candidate_truth_keys'])}",
        f"Handoff truth keys : {len(payload['runtime']['chatgpt_handoff']['candidate_truth_keys'])}",
        f"AI forbidden terms : {payload['semantic_probes']['ai_forbidden_count']}",
        f"Handoff forbidden  : {payload['semantic_probes']['handoff_forbidden_count']}",
        "",
        f"AI-only keys       : {diff['left_only_keys']}",
        f"Handoff-only keys  : {diff['right_only_keys']}",
        f"Different shared   : {sorted(diff['different_shared_values'])}",
        "",
        f"Handoff ZIP found  : {zip_info.get('found')}",
        f"Job JSON count     : {zip_info.get('job_json_count')}",
        f"Job JSON + truth   : {zip_info.get('job_json_with_candidate_truth')}",
        f"Job JSON + instr.  : {zip_info.get('job_json_with_application_instructions')}",
        f"Avg job.json bytes : {zip_info.get('job_json_average_size')}",
        "",
        f"JSON inventory     : {json_path}",
    ]

    txt_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print()
    print("Inventaire écrit :")
    print("JSON :", json_path)
    print("TXT  :", txt_path)
    print()
    print("Aucun fichier métier n'a été modifié.")


if __name__ == "__main__":
    main()
