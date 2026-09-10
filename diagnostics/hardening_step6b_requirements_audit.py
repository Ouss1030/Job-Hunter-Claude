from __future__ import annotations

import re

import ast
import importlib.metadata
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from diagnostics import run_all

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "requirements.txt"

# Les dépendances optionnelles vivent dans des fichiers séparés : ne pas les
# lire faisait signaler streamlit, pandas et playwright comme non déclarés.
REQ_AUXILIAIRES = [
    ROOT / "requirements_ui.txt",
    ROOT / "requirements_ai.txt",
    ROOT / "requirements_jobat.txt",
]

# Packages locaux du projet : ce ne sont pas des dépendances tierces.
PACKAGES_LOCAUX = {
    "interface", "applications", "config", "database",
    "diagnostics", "matching", "sources",
}

PROJECT_DIRS = ["applications", "config", "database", "diagnostics", "matching", "sources"]
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "backups", "exports"}
STDLIB = set(getattr(sys, "stdlib_module_names", set()))

IMPORT_TO_DIST = {
    "bs4": "beautifulsoup4",
    "docx": "python-docx",
    "openai": "openai",
    "requests": "requests",
    "urllib3": "urllib3",
    # Dépendances optionnelles, déclarées dans les requirements auxiliaires.
    "streamlit": "streamlit",
    "pandas": "pandas",
    "playwright": "playwright",
}

EXPECTED = {
    "beautifulsoup4": "4.15.0",
    "openai": "3.2.0",
    "python-docx": "1.2.0",
    "requests": "2.34.2",
    "urllib3": "2.7.0",
}


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" | {detail}" if detail else ""))
    return ok


def project_names():
    names = {p.stem for p in ROOT.glob("*.py")}
    for d in PROJECT_DIRS:
        if (ROOT / d).is_dir():
            names.add(d)
    return names


def iter_py():
    files = [p for p in ROOT.glob("*.py") if p.is_file()]
    for d in PROJECT_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            files.append(p)
    return sorted(set(files))


def direct_third_party_imports():
    locals_ = project_names()
    found = set()

    for path in iter_py():
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            roots = []
            if isinstance(node, ast.Import):
                roots = [a.name.split(".", 1)[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = [node.module.split(".", 1)[0]]

            for name in roots:
                if name == "__future__" or name in STDLIB or name in locals_:
                    continue
                found.add(name)

    return found


def parse_requirements_auxiliaires():
    """Noms de paquets déclarés dans les fichiers de dépendances optionnels."""
    noms = set()
    for chemin in REQ_AUXILIAIRES:
        if not chemin.exists():
            continue
        for ligne in chemin.read_text(encoding="utf-8").splitlines():
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#"):
                continue
            noms.add(re.split(r"[<>=!\[]", ligne)[0].strip().lower())
    return noms


def parse_requirements():
    parsed = {}
    duplicates = []

    for raw in REQ.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            raise ValueError(f"Ligne non pinnee: {line}")

        package, version = [x.strip() for x in line.split("==", 1)]
        key = package.casefold()
        if key in parsed:
            duplicates.append(package)
        parsed[key] = version

    return parsed, duplicates


def child_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def main():
    print("=" * 100)
    print("HARDENING STEP 6B - REQUIREMENTS AUDIT")
    print("=" * 100)

    tests = []

    tests.append(check("requirements.txt present", REQ.exists(), str(REQ)))
    if not REQ.exists():
        raise SystemExit(1)

    parsed, duplicates = parse_requirements()
    expected = {k.casefold(): v for k, v in EXPECTED.items()}

    tests.append(check("5 dependances directes", len(parsed) == 5, str(sorted(parsed))))
    tests.append(check("Aucun doublon", not duplicates, str(duplicates)))
    tests.append(check("Pins exacts attendus", parsed == expected, str(parsed)))

    imports = direct_third_party_imports() - PACKAGES_LOCAUX
    unknown = sorted(
        x for x in imports
        if x not in IMPORT_TO_DIST and x not in PACKAGES_LOCAUX
    )

    tests.append(check("Tous les imports tiers connus", not unknown, str(unknown)))

    needed = {IMPORT_TO_DIST[x].casefold() for x in imports}
    # La couverture doit tenir compte des fichiers auxiliaires : le noyau
    # n'a pas à déclarer streamlit, pandas ou playwright, qui sont optionnels.
    declare = set(parsed) | parse_requirements_auxiliaires()
    manquants = sorted(needed - declare)
    tests.append(check(
        "requirements couvre tous les imports tiers",
        not manquants,
        f"manquants={manquants}" if manquants
        else f"noyau={sorted(parsed)} auxiliaires={sorted(parse_requirements_auxiliaires())}",
    ))

    mismatches = {}
    for package, expected_version in EXPECTED.items():
        try:
            installed = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        if installed != expected_version:
            mismatches[package] = {"expected": expected_version, "installed": installed}

    tests.append(check("Environnement courant correspond aux pins", not mismatches, str(mismatches)))

    classification = run_all.classification_status()
    tests.append(check(
        "run_all classification exhaustive",
        classification["ok"],
        f"{classification['classified_count']}/{classification['discovered_count']}",
    ))
    tests.append(check(
        "Step 6A classe REPORTS",
        "hardening_step6a_dependency_inventory" in run_all.REPORTS,
    ))
    tests.append(check(
        "Step 6B audit classe TOOLS",
        "hardening_step6b_requirements_audit" in run_all.TOOLS,
    ))

    proc = subprocess.run(
        [sys.executable, "-m", "diagnostics.hardening_step5b_run_all_audit"],
        cwd=ROOT,
        env=child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    tests.append(check("Audit structurel Step 5B reste vert", proc.returncode == 0, f"code={proc.returncode}"))

    passed = sum(tests)
    total = len(tests)
    status = "HARDENING STEP 6B VALIDE." if all(tests) else "HARDENING STEP 6B NON VALIDE."

    print()
    print(f"Tests : {passed}/{total}")
    print(status)

    log_dir = ROOT / "exports" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = log_dir / f"hardening_step6b_requirements_audit_{stamp}.json"
    txt_path = log_dir / f"hardening_step6b_requirements_audit_{stamp}.txt"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "requirements": [f"{k}=={v}" for k, v in EXPECTED.items()],
        "direct_third_party_imports": sorted(imports),
        "classification": {
            "ok": classification["ok"],
            "discovered_count": classification["discovered_count"],
            "classified_count": classification["classified_count"],
            "unclassified": classification["unclassified"],
            "missing_on_disk": classification["missing_on_disk"],
        },
        "step5b_returncode": proc.returncode,
        "step5b_output_tail": proc.stdout[-5000:],
    }

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_path.write_text(
        "\n".join([
            "HARDENING STEP 6B - REQUIREMENTS AUDIT",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status,
            f"Classification : {classification['classified_count']}/{classification['discovered_count']}",
            f"Step 5B rc : {proc.returncode}",
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
