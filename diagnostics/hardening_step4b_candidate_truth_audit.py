"""
HARDENING STEP 4B — SINGLE CANDIDATE TRUTH AUDIT

Usage:
    python -m diagnostics.hardening_step4b_candidate_truth_audit

Aucun réseau.
Aucune collecte.
Aucune régénération Handoff.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import candidate_truth as canonical
import config.ai_generation as ai_generation
import applications.chatgpt_handoff as chatgpt_handoff


ROOT = Path(__file__).resolve().parents[1]
AI_PATH = ROOT / "config" / "ai_generation.py"
HANDOFF_PATH = ROOT / "applications" / "chatgpt_handoff.py"


def check(label, condition, detail=""):
    ok = bool(condition)
    print(
        f"[{'OK' if ok else 'FAIL'}] {label}"
        + (f" | {detail}" if detail else "")
    )
    return ok


def local_dict_assignment(path, name):
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)

    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue

        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                return isinstance(
                    getattr(node, "value", None),
                    (ast.Dict, ast.List, ast.Tuple, ast.Set),
                )

    return False


def child_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def main():
    print("=" * 100)
    print("HARDENING STEP 4B - SINGLE CANDIDATE TRUTH AUDIT")
    print("=" * 100)

    tests = []

    tests.append(check(
        "Canonical version 1.0",
        canonical.CANDIDATE_TRUTH_VERSION == "1.0",
        canonical.CANDIDATE_TRUTH_VERSION,
    ))

    tests.append(check(
        "AI utilise exactement la vérité canonique",
        ai_generation.CANDIDATE_TRUTH is canonical.CANDIDATE_TRUTH,
    ))

    tests.append(check(
        "AI default CV canonique",
        ai_generation.DEFAULT_BASE_CV_NAME
        == canonical.DEFAULT_BASE_CV_NAME,
        ai_generation.DEFAULT_BASE_CV_NAME,
    ))

    tests.append(check(
        "AI forbidden terms canoniques",
        ai_generation.FORBIDDEN_CANDIDATE_CLAIM_TERMS
        is canonical.FORBIDDEN_CANDIDATE_CLAIM_TERMS,
    ))

    tests.append(check(
        "AI ne redéfinit plus un dict CANDIDATE_TRUTH local",
        not local_dict_assignment(AI_PATH, "CANDIDATE_TRUTH"),
    ))

    tests.append(check(
        "Handoff ne redéfinit plus un dict CANDIDATE_TRUTH local",
        not local_dict_assignment(HANDOFF_PATH, "CANDIDATE_TRUTH"),
    ))

    expected_handoff = canonical.build_handoff_candidate_truth()

    tests.append(check(
        "Handoff = adaptateur canonique",
        chatgpt_handoff.CANDIDATE_TRUTH == expected_handoff,
    ))

    tests.append(check(
        "Unsupported canonique propagé au Handoff",
        chatgpt_handoff.CANDIDATE_TRUTH.get("not_demonstrated")
        == canonical.CANDIDATE_TRUTH.get("unsupported_or_not_proven"),
    ))

    expected_forbidden = sorted(
        canonical.FORBIDDEN_CANDIDATE_CLAIM_TERMS.values()
    )
    tests.append(check(
        "Forbidden terms propagés au Handoff",
        chatgpt_handoff.CANDIDATE_TRUTH.get("forbidden_claim_terms")
        == expected_forbidden,
        str(expected_forbidden),
    ))

    tests.append(check(
        "Hard truth rules propagées",
        chatgpt_handoff.CANDIDATE_TRUTH.get("hard_truth_rules")
        == canonical.HARD_TRUTH_RULES,
    ))

    unsupported = {
        value.casefold()
        for value in canonical.CANDIDATE_TRUTH["unsupported_or_not_proven"]
    }

    required_unsupported = {
        "gc comme compétence pratiquée",
        "empower",
        "talend",
        "apache hop",
        "tableau",
        "oracle",
        "pl/sql",
        "diplôme de master",
        "expérience professionnelle data/bi",
        "culture cellulaire",
        "métrologie mécanique / gd&t / cmm",
        "allemand professionnel",
        "brevet cariste",
    }

    tests.append(check(
        "Unsupported consolidé",
        required_unsupported <= unsupported,
        str(sorted(required_unsupported - unsupported)),
    ))

    education_text = json.dumps(
        canonical.CANDIDATE_TRUTH["education"],
        ensure_ascii=False,
    ).casefold()

    tests.append(check(
        "BDA terminé",
        "diplôme obtenu en 2026" in education_text,
    ))

    tests.append(check(
        "Master non obtenu explicite",
        "aucun diplôme de master obtenu" in education_text,
    ))

    # L'ancien audit Handoff doit rester vert après migration.
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "diagnostics.chatgpt_handoff_v1_audit",
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
        "Audit Handoff V1 existant reste vert",
        proc.returncode == 0,
        f"code={proc.returncode}",
    ))

    passed = sum(tests)
    total = len(tests)
    status = (
        "HARDENING STEP 4B VALIDE."
        if all(tests)
        else "HARDENING STEP 4B NON VALIDE."
    )

    print()
    print(f"Tests : {passed}/{total}")
    print(status)

    log_dir = ROOT / "exports" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = log_dir / f"hardening_step4b_candidate_truth_audit_{stamp}.json"
    txt_path = log_dir / f"hardening_step4b_candidate_truth_audit_{stamp}.txt"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "canonical_version": canonical.CANDIDATE_TRUTH_VERSION,
        "default_base_cv": canonical.DEFAULT_BASE_CV_NAME,
        "forbidden_terms": expected_forbidden,
        "unsupported_count": len(
            canonical.CANDIDATE_TRUTH["unsupported_or_not_proven"]
        ),
        "supported_count": len(
            canonical.CANDIDATE_TRUTH["supported_skills"]
        ),
        "handoff_audit_returncode": proc.returncode,
        "handoff_audit_output_tail": proc.stdout[-6000:],
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "HARDENING STEP 4B - SINGLE CANDIDATE TRUTH AUDIT",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status,
            f"Canonical version : {canonical.CANDIDATE_TRUTH_VERSION}",
            f"Unsupported count : {payload['unsupported_count']}",
            f"Forbidden terms   : {expected_forbidden}",
            f"Handoff audit rc  : {proc.returncode}",
        ]),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        print()
        print(proc.stdout[-4000:])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
