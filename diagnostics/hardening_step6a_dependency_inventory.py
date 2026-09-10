"""
HARDENING STEP 6A - PROJECT DEPENDENCY INVENTORY

Lecture seule.
N'installe rien.
Ne lance aucun module métier.
Ne fait aucun appel réseau.

Usage:
    python -m diagnostics.hardening_step6a_dependency_inventory
"""

from __future__ import annotations

import ast
import importlib.metadata
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "exports" / "logs"


SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "backups",
    "exports",
    "database",
}

# Répertoires projet à scanner s'ils existent.
PROJECT_DIRS = [
    "applications",
    "config",
    "database",
    "diagnostics",
    "matching",
    "sources",
]

# Modules top-level connus comme stdlib Python 3.11.
STDLIB = set(getattr(sys, "stdlib_module_names", set()))

# Mapping import -> nom de package pip quand différent.
PIP_NAME_OVERRIDES = {
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
}


def project_top_level_names():
    names = set()

    for path in ROOT.glob("*.py"):
        names.add(path.stem)

    for dirname in PROJECT_DIRS:
        path = ROOT / dirname
        if path.exists() and path.is_dir():
            names.add(dirname)

    return names


def iter_python_files():
    files = []

    # Fichiers Python racine.
    files.extend(
        path
        for path in ROOT.glob("*.py")
        if path.is_file()
    )

    # Sous-répertoires métier.
    for dirname in PROJECT_DIRS:
        base = ROOT / dirname
        if not base.exists():
            continue

        for path in base.rglob("*.py"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            files.append(path)

    return sorted(set(files))


def imports_from_file(path):
    text = path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    try:
        tree = ast.parse(text)
    except Exception as exc:
        return {
            "syntax_ok": False,
            "syntax_error": repr(exc),
            "imports": [],
        }

    roots = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.add(node.module.split(".", 1)[0])

    return {
        "syntax_ok": True,
        "syntax_error": None,
        "imports": sorted(roots),
    }


def installed_version_for_import(import_name):
    candidates = []

    pip_name = PIP_NAME_OVERRIDES.get(
        import_name,
        import_name,
    )
    candidates.append(pip_name)

    # importlib.metadata n'utilise pas toujours le nom d'import.
    package_map = importlib.metadata.packages_distributions()
    for dist in package_map.get(import_name, []):
        candidates.append(dist)

    seen = set()

    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)

        try:
            return {
                "distribution": candidate,
                "version": importlib.metadata.version(candidate),
            }
        except importlib.metadata.PackageNotFoundError:
            pass

    return None


def main():
    print("=" * 100)
    print("HARDENING STEP 6A - PROJECT DEPENDENCY INVENTORY")
    print("=" * 100)
    print("Mode : READ_ONLY")
    print()

    project_names = project_top_level_names()
    files = iter_python_files()

    import_usage = {}
    syntax_errors = []

    for path in files:
        info = imports_from_file(path)

        rel = str(path.relative_to(ROOT))

        if not info["syntax_ok"]:
            syntax_errors.append({
                "file": rel,
                "error": info["syntax_error"],
            })
            continue

        for name in info["imports"]:
            import_usage.setdefault(
                name,
                [],
            ).append(rel)

    stdlib = []
    local = []
    third_party = []
    unresolved = []

    for name in sorted(import_usage):
        if name in STDLIB or name == "__future__":
            stdlib.append(name)
            continue

        if name in project_names:
            local.append(name)
            continue

        installed = installed_version_for_import(name)

        record = {
            "import_name": name,
            "files": import_usage[name],
            "pip_name": PIP_NAME_OVERRIDES.get(name, name),
            "installed": installed,
        }

        if installed:
            third_party.append(record)
        else:
            unresolved.append(record)

    payload = {
        "generated_at": datetime.now().isoformat(
            timespec="seconds"
        ),
        "mode": "READ_ONLY",
        "python_file_count": len(files),
        "syntax_error_count": len(syntax_errors),
        "syntax_errors": syntax_errors,
        "project_top_level_names": sorted(project_names),
        "stdlib_imports": stdlib,
        "local_imports": local,
        "third_party_imports": third_party,
        "unresolved_imports": unresolved,
        "candidate_requirements": [
            {
                "package": row["installed"]["distribution"],
                "installed_version": row["installed"]["version"],
                "import_name": row["import_name"],
                "used_by_count": len(row["files"]),
            }
            for row in third_party
        ],
    }

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    json_path = (
        LOG_DIR
        / f"hardening_step6a_dependency_inventory_{stamp}.json"
    )
    txt_path = (
        LOG_DIR
        / f"hardening_step6a_dependency_inventory_{stamp}.txt"
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
        "HARDENING STEP 6A - PROJECT DEPENDENCY INVENTORY",
        "=" * 100,
        "Mode : READ_ONLY",
        "",
        f"Python files       : {len(files)}",
        f"Syntax errors      : {len(syntax_errors)}",
        f"Stdlib imports     : {len(stdlib)}",
        f"Local imports      : {len(local)}",
        f"Third-party imports: {len(third_party)}",
        f"Unresolved imports : {len(unresolved)}",
        "",
        "THIRD-PARTY",
        "-----------",
    ]

    for row in third_party:
        installed = row["installed"]
        lines.append(
            f"- {row['import_name']} -> "
            f"{installed['distribution']}=={installed['version']} "
            f"| files={len(row['files'])}"
        )

    lines.extend([
        "",
        "UNRESOLVED",
        "----------",
    ])

    for row in unresolved:
        lines.append(
            f"- {row['import_name']} | files={len(row['files'])}"
        )

    txt_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print(f"Python files        : {len(files)}")
    print(f"Syntax errors       : {len(syntax_errors)}")
    print(f"Third-party imports : {len(third_party)}")
    print(f"Unresolved imports  : {len(unresolved)}")
    print()
    print("JSON :", json_path)
    print("TXT  :", txt_path)
    print()
    print("Aucun package n'a été installé ou modifié.")


if __name__ == "__main__":
    main()
