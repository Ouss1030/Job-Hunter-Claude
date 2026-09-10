"""
HARDENING STEP 5A - DIAGNOSTICS INVENTORY

Lecture seule.
Aucun réseau.
Aucune collecte.
Aucune DB.
Aucun diagnostic exécuté.

Usage:
    python -m diagnostics.hardening_step5a_diagnostics_inventory
"""

from __future__ import annotations

import ast
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIAG_DIR = ROOT / "diagnostics"


NETWORK_IMPORTS = {
    "requests",
    "urllib3",
    "httpx",
    "aiohttp",
    "selenium",
    "playwright",
}

REPORT_HINTS = (
    "current_batch",
    "current_installation",
    "inventory",
    "report",
)

HISTORICAL_HINTS = (
    "post_upgrade",
    "encoding",
    "hotfix",
)

VERSION_RE = re.compile(r"_v(\d+(?:\d+)*)")


def read_source(path):
    return path.read_text(
        encoding="utf-8",
        errors="replace",
    )


def parse_info(path):
    text = read_source(path)

    info = {
        "filename": path.name,
        "module": f"diagnostics.{path.stem}",
        "bytes": len(text.encode("utf-8")),
        "has_main_guard": 'if __name__ == "__main__"' in text,
        "imports": [],
        "from_imports": [],
        "network_imports": [],
        "subprocess_usage": "subprocess" in text,
        "writes_exports_logs": "exports" in text and "logs" in text,
        "mentions_main_py": "main.py" in text or "import main" in text,
        "mentions_daily_run": "daily_run" in text,
        "name_hints": [],
        "syntax_ok": True,
        "syntax_error": None,
    }

    lower_name = path.stem.lower()

    for hint in REPORT_HINTS:
        if hint in lower_name:
            info["name_hints"].append(f"REPORT:{hint}")

    for hint in HISTORICAL_HINTS:
        if hint in lower_name:
            info["name_hints"].append(f"HISTORY:{hint}")

    if lower_name.endswith("_audit"):
        info["name_hints"].append("AUDIT_SUFFIX")

    try:
        tree = ast.parse(text)
    except Exception as exc:
        info["syntax_ok"] = False
        info["syntax_error"] = repr(exc)
        return info

    imported_roots = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                info["imports"].append(name)
                imported_roots.add(name.split(".", 1)[0])

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [alias.name for alias in node.names]
            info["from_imports"].append({
                "module": module,
                "names": names,
            })
            if module:
                imported_roots.add(module.split(".", 1)[0])

    info["network_imports"] = sorted(
        imported_roots & NETWORK_IMPORTS
    )

    return info


def likely_successor_pairs(files):
    """
    Suggestions uniquement, sans modifier ni classer définitivement.
    Regroupe les diagnostics qui partagent un préfixe fonctionnel.
    """
    stems = sorted(path.stem for path in files)
    groups = {}

    prefixes = [
        "application_recheck",
        "final_application_pool",
        "job_refresh",
        "daily_run",
        "delta_tracker",
        "chatgpt_handoff",
        "application_preparation",
        "application_queue",
        "application_gate",
    ]

    for prefix in prefixes:
        matches = [
            stem for stem in stems
            if stem.startswith(prefix)
        ]
        if len(matches) > 1:
            groups[prefix] = matches

    return groups


def main():
    print("=" * 100)
    print("HARDENING STEP 5A - DIAGNOSTICS INVENTORY")
    print("=" * 100)
    print("Mode : READ_ONLY")
    print()

    files = sorted(
        path for path in DIAG_DIR.glob("*.py")
        if path.name != "__init__.py"
    )

    infos = [parse_info(path) for path in files]

    syntax_bad = [
        row["filename"]
        for row in infos
        if not row["syntax_ok"]
    ]

    network_candidates = [
        row["filename"]
        for row in infos
        if row["network_imports"]
    ]

    report_candidates = [
        row["filename"]
        for row in infos
        if any(
            hint.startswith("REPORT:")
            for hint in row["name_hints"]
        )
    ]

    audit_candidates = [
        row["filename"]
        for row in infos
        if "audit" in row["filename"].lower()
    ]

    helper_candidates = [
        row["filename"]
        for row in infos
        if "audit" not in row["filename"].lower()
        and not row["has_main_guard"]
    ]

    payload = {
        "generated_at": datetime.now().isoformat(
            timespec="seconds"
        ),
        "mode": "READ_ONLY",
        "diagnostics_dir": str(DIAG_DIR),
        "python_file_count": len(files),
        "audit_candidate_count": len(audit_candidates),
        "network_candidate_count": len(network_candidates),
        "report_candidate_count": len(report_candidates),
        "helper_candidate_count": len(helper_candidates),
        "syntax_error_count": len(syntax_bad),
        "syntax_errors": syntax_bad,
        "network_candidates": network_candidates,
        "report_candidates": report_candidates,
        "helper_candidates": helper_candidates,
        "possible_successor_groups":
            likely_successor_pairs(files),
        "files": infos,
    }

    log_dir = ROOT / "exports" / "logs"
    log_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    json_path = (
        log_dir
        / f"hardening_step5a_diagnostics_inventory_{stamp}.json"
    )
    txt_path = (
        log_dir
        / f"hardening_step5a_diagnostics_inventory_{stamp}.txt"
    )

    json_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        "HARDENING STEP 5A - DIAGNOSTICS INVENTORY",
        "=" * 100,
        "Mode : READ_ONLY",
        "",
        f"Python files      : {len(files)}",
        f"Audit candidates  : {len(audit_candidates)}",
        f"Network candidates: {len(network_candidates)}",
        f"Report candidates : {len(report_candidates)}",
        f"Helper candidates : {len(helper_candidates)}",
        f"Syntax errors     : {len(syntax_bad)}",
        "",
        "FILES",
        "-----",
    ]

    for row in infos:
        suffix = []
        if row["network_imports"]:
            suffix.append(
                "NETWORK=" + ",".join(row["network_imports"])
            )
        if row["name_hints"]:
            suffix.extend(row["name_hints"])
        if not row["syntax_ok"]:
            suffix.append("SYNTAX_ERROR")

        extra = (
            " | " + " | ".join(suffix)
            if suffix else ""
        )
        lines.append(
            f"- {row['filename']}{extra}"
        )

    lines.extend([
        "",
        "POSSIBLE SUCCESSOR GROUPS",
        "-------------------------",
    ])

    for key, values in payload[
        "possible_successor_groups"
    ].items():
        lines.append(
            f"{key}: {', '.join(values)}"
        )

    txt_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print(f"Python files       : {len(files)}")
    print(f"Audit candidates   : {len(audit_candidates)}")
    print(f"Network candidates : {len(network_candidates)}")
    print(f"Report candidates  : {len(report_candidates)}")
    print(f"Helper candidates  : {len(helper_candidates)}")
    print(f"Syntax errors      : {len(syntax_bad)}")
    print()
    print("JSON :", json_path)
    print("TXT  :", txt_path)
    print()
    print("Aucun diagnostic n'a été exécuté.")
    print("Aucun fichier métier n'a été modifié.")


if __name__ == "__main__":
    main()
