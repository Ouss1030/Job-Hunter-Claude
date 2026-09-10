from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.1"

PROTECTED_DIRS = {
    "applications", "interface", "matching", "database", "config", "sources", "diagnostics",
    "logs", "exports", "backups", ".git", ".venv",
}
PROTECTED_ROOT_FILES = {
    "main.py", "daily_run.py", "jobhunter_ui.py",
    "START_JOBHUNTER.bat", "RESUME_DAILY_RUN.bat", "TEST_DAILY_RUN.bat",
    "README.md", ".gitignore",
}
TRANSIT_DIRS = {
    "_payload", "payload", "_patch_payload", "_step9_1_payload",
    "_jobat_circuit_v1_payload", "_jobat_cookie_once_v1_payload",
    "hardening_files", "hardening_step2_files", "hardening_step4b_files",
    "hardening_step6b_files", "hardening_step7_files",
    "lifecycle_step8f_b_files",
}
ROOT_MIGRATION_PATTERNS = [
    "upgrade_*.py", "install_*.py", "apply_*.py",
    "rollback_*.py", "patch_*.py", "daily_run_v1*_candidate.py",
]
ROOT_STEP_PATTERNS = [
    "lifecycle_step8*.py",
    "main_smartrecruiters_shadow*.py",
    "diagnose_jobat_prov.py",
    "export_full_performance_audit_v1.py",
    "Resume_pour_gemini.py",
    "_wdd.py",
]
KEEP_ROOT_BATS = {
    "START_JOBHUNTER.bat",
    "RESUME_DAILY_RUN.bat",
    "TEST_DAILY_RUN.bat",
}
TEXT_SUFFIXES = {
    ".py", ".bat", ".md", ".txt", ".json", ".toml", ".ini", ".cfg",
    ".yml", ".yaml", ".ps1",
}
MODULE_PREFIXES = (
    "applications", "diagnostics", "interface",
    "matching", "database", "config", "sources",
)
MODULE_STRING_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?P<module>(?:applications|diagnostics|interface|matching|database|config|sources)"
    r"(?:\.[A-Za-z_][A-Za-z0-9_]*)+)"
    r"(?:\:[A-Za-z0-9_.-]+)?"
)
README_VERSION_RE = re.compile(
    r"^(?P<family>README_.+?)_V(?P<version>\d+(?:[_-]\d+)*)\.md$",
    re.IGNORECASE,
)
VERSIONED_APP_RE = re.compile(
    r"^(?P<base>.+?)_v(?P<version>\d+(?:[_-]\d+)*)\.py$",
    re.IGNORECASE,
)

@dataclass
class Candidate:
    lot: int
    path: str
    reason: str
    status: str = "CANDIDATE"
    protected_by: list[str] | None = None

def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def rel(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")

def dotted_module(root: Path, path: Path) -> str | None:
    try:
        rp = path.resolve().relative_to(root.resolve())
    except Exception:
        return None
    if rp.suffix.lower() != ".py":
        return None
    parts = list(rp.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None

def safe_read(path: Path) -> str:
    try:
        if path.stat().st_size > 3_000_000:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""

def parse_imports(path: Path) -> set[str]:
    text = safe_read(path)
    if not text:
        return set()
    try:
        tree = ast.parse(text)
    except Exception:
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out

def literal_classified_modules(run_all_path: Path) -> dict[str, set[str]]:
    text = safe_read(run_all_path)
    if not text:
        raise RuntimeError(f"Impossible de lire {run_all_path}")
    tree = ast.parse(text)
    names = {
        "SUITE_ACTIVE", "REPLACED", "NETWORK", "REPORTS",
        "REPLAYS", "HISTORICAL", "TOOLS",
    }
    found: dict[str, set[str]] = {}
    for node in tree.body:
        target_name = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target_name = node.targets[0].id
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value = node.value
        if target_name not in names or value is None:
            continue
        try:
            literal = ast.literal_eval(value)
        except Exception:
            continue
        if isinstance(literal, dict):
            vals = set(str(k) for k in literal.keys())
        elif isinstance(literal, (set, list, tuple)):
            vals = set(str(x) for x in literal)
        else:
            continue
        found[target_name] = vals
    missing = names - set(found)
    if missing:
        raise RuntimeError(
            "Impossible de lire toutes les catégories de diagnostics dans run_all.py: "
            + ", ".join(sorted(missing))
        )
    return found

def classified_set(root: Path) -> set[str]:
    cats = literal_classified_modules(root / "diagnostics" / "run_all.py")
    out = set()
    for values in cats.values():
        out.update(values)
    return out

def classified_import_closure(root: Path, classified: set[str]) -> set[str]:
    protected = set(classified)
    frontier = {
        root / "diagnostics" / f"{name}.py"
        for name in classified
        if (root / "diagnostics" / f"{name}.py").exists()
    }
    seen_files: set[Path] = set()
    while frontier:
        src = frontier.pop()
        if src in seen_files:
            continue
        seen_files.add(src)
        for mod in parse_imports(src):
            parts = mod.split(".")
            for n in range(len(parts), 0, -1):
                p = root.joinpath(*parts[:n]).with_suffix(".py")
                if p.exists():
                    dm = dotted_module(root, p)
                    if dm:
                        protected.add(dm)
                    if p not in seen_files:
                        frontier.add(p)
                    break
    return protected

def is_protected_path(root: Path, path: Path, classified: set[str], classified_closure: set[str]) -> tuple[bool, str | None]:
    rp = Path(rel(root, path))
    if not rp.parts:
        return True, "root"
    if len(rp.parts) == 1:
        if rp.name in PROTECTED_ROOT_FILES or rp.name.lower().startswith("requirements"):
            return True, "protected root file"
    top = rp.parts[0]
    if top == "diagnostics":
        stem = path.stem
        if stem == "run_all" or stem in classified:
            return True, "classified diagnostic"
    if top in PROTECTED_DIRS and top != "diagnostics":
        # Files in protected code/data dirs are protected except lot 7 explicit duplicates,
        # which are handled separately and must pass version checks.
        return True, f"protected directory: {top}"
    dm = dotted_module(root, path)
    if dm and dm in classified_closure:
        return True, "imported by classified diagnostic"
    return False, None

def build_reference_index(root: Path) -> dict[str, list[str]]:
    """Index references from imports, literal dotted-module strings and BAT mentions."""
    refs: dict[str, list[str]] = {}

    def add(target: str, source: Path, kind: str):
        refs.setdefault(target, []).append(f"{kind}:{rel(root, source)}")

    for src in root.rglob("*"):
        if not src.is_file():
            continue
        try:
            rp = src.resolve().relative_to(root.resolve())
        except Exception:
            continue
        if any(part in {".git", ".venv", "backups", "_quarantine"} or part.startswith("_quarantaine_") for part in rp.parts):
            continue
        if src.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = safe_read(src)
        if not text:
            continue

        if src.suffix.lower() == ".py":
            for mod in parse_imports(src):
                add(mod, src, "import")

        for m in MODULE_STRING_RE.finditer(text):
            add(m.group("module"), src, "string")

        if src.suffix.lower() == ".bat":
            low = text.lower().replace("\\", "/")
            for prefix in MODULE_PREFIXES:
                # Common -m package.module form and filesystem path mentions.
                for m in re.finditer(
                    rf"(?<![a-z0-9_])({prefix}(?:[./][a-z0-9_]+)+)",
                    low,
                    flags=re.IGNORECASE,
                ):
                    mod = m.group(1).replace("/", ".").replace("\\", ".")
                    if mod.lower().endswith(".py"):
                        mod = mod[:-3]
                    add(mod, src, "bat")
    return refs

def external_references(root: Path, path: Path, refs: dict[str, list[str]]) -> list[str]:
    dm = dotted_module(root, path)
    if not dm:
        # For root .bat/.md companions, reference safety is handled via matching base .py.
        return []
    hits: list[str] = []
    for target, sources in refs.items():
        if target == dm or target.startswith(dm + ".") or dm.startswith(target + "."):
            for item in sources:
                src_rel = item.split(":", 1)[1]
                if src_rel != rel(root, path):
                    hits.append(item)
    return sorted(set(hits))

def normalize_version(value: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", str(value))
    return tuple(int(x) for x in nums) if nums else ()

def module_declared_version(path: Path) -> tuple[int, ...]:
    text = safe_read(path)
    if not text:
        return ()
    patterns = [
        r'(?m)^\s*(?:[A-Z_]*VERSION|VERSION)\s*=\s*["\']([^"\']+)["\']',
        r'(?m)^\s*__version__\s*=\s*["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return normalize_version(m.group(1))
    return ()

class WorkspaceCleaner:
    def __init__(self, root: Path, classified_override: set[str] | None = None):
        self.root = root.resolve()
        self.run_all = self.root / "diagnostics" / "run_all.py"
        self.classified = classified_override if classified_override is not None else classified_set(self.root)
        self.classified_closure = (
            set(self.classified)
            if classified_override is not None
            else classified_import_closure(self.root, self.classified)
        )
        self.refs = build_reference_index(self.root)

    def _candidate(self, lot: int, path: Path, reason: str, allow_protected_dir: bool = False) -> Candidate:
        protected, why = is_protected_path(
            self.root, path, self.classified, self.classified_closure
        )
        if allow_protected_dir and why and why.startswith("protected directory:"):
            protected = False
            why = None
        if protected:
            return Candidate(lot, rel(self.root, path), reason, "SKIP_PROTECTED", [why] if why else [])
        refs = external_references(self.root, path, self.refs)
        if refs:
            return Candidate(lot, rel(self.root, path), reason, "SKIP_REFERENCED", refs)
        return Candidate(lot, rel(self.root, path), reason)

    def lot1(self) -> list[Candidate]:
        out = []
        for dirname in sorted(TRANSIT_DIRS):
            d = self.root / dirname
            if not d.exists():
                continue
            for p in sorted(d.rglob("*")):
                if p.is_file():
                    out.append(self._candidate(1, p, f"transit payload: {dirname}"))
        return out

    def lot2(self) -> list[Candidate]:
        diagnostics = self.root / "diagnostics"
        on_disk = {p.stem for p in diagnostics.glob("*.py") if p.name != "__init__.py"}
        unclassified = sorted(on_disk - self.classified)
        out = []
        for stem in unclassified:
            p = diagnostics / f"{stem}.py"
            out.append(self._candidate(2, p, "diagnostic non classé", allow_protected_dir=True))
        return out

    def lot3(self) -> list[Candidate]:
        py_candidates: set[Path] = set()
        for pattern in ROOT_MIGRATION_PATTERNS:
            py_candidates.update(self.root.glob(pattern))
        out: list[Candidate] = []
        for p in sorted(py_candidates):
            c = self._candidate(3, p, "migration/install/rollback racine")
            out.append(c)
            if c.status == "CANDIDATE":
                for ext in (".bat", ".md", ".txt"):
                    companion = self.root / f"{p.stem}{ext}"
                    if companion.exists():
                        out.append(Candidate(3, rel(self.root, companion), f"compagnon de {p.name}"))
        return out

    def lot4(self) -> list[Candidate]:
        paths: set[Path] = set()
        for pattern in ROOT_STEP_PATTERNS:
            paths.update(self.root.glob(pattern))
        paths.discard(self.root / "lifecycle.py")
        return [self._candidate(4, p, "script d'étape racine") for p in sorted(paths)]

    def lot5(self) -> list[Candidate]:
        out = []
        for p in sorted(self.root.glob("*.bat")):
            if p.name in KEEP_ROOT_BATS:
                out.append(Candidate(5, rel(self.root, p), "lanceur racine protégé", "SKIP_PROTECTED", ["protected launcher"]))
            else:
                out.append(self._candidate(5, p, "BAT racine non protégé"))
        return out

    def lot6(self) -> list[Candidate]:
        groups: dict[str, list[tuple[tuple[int, ...], Path]]] = {}
        for p in self.root.glob("README*_V*.md"):
            m = README_VERSION_RE.match(p.name)
            if not m:
                continue
            groups.setdefault(m.group("family").lower(), []).append(
                (normalize_version(m.group("version")), p)
            )
        out = []
        for family, members in sorted(groups.items()):
            members.sort(key=lambda x: x[0])
            if len(members) < 2:
                continue
            keep_ver, keep_path = members[-1]
            out.append(Candidate(
                6, rel(self.root, keep_path),
                f"README le plus récent de {family}: V{'.'.join(map(str, keep_ver))}",
                "SKIP_KEEP_LATEST", []
            ))
            for ver, p in members[:-1]:
                out.append(self._candidate(
                    6, p,
                    f"README versionné ancien; latest={keep_path.name}"
                ))
        return out

    def lot7(self) -> list[Candidate]:
        apps = self.root / "applications"
        out = []
        for p in sorted(apps.glob("*_v*.py")):
            m = VERSIONED_APP_RE.match(p.name)
            if not m:
                continue
            base = apps / f"{m.group('base')}.py"
            if not base.exists():
                out.append(Candidate(
                    7, rel(self.root, p),
                    "doublon versionné sans fichier de base",
                    "SKIP_MANUAL_VERIFY", ["base file missing"]
                ))
                continue
            duplicate_name_ver = normalize_version(m.group("version"))
            base_declared = module_declared_version(base)
            dup_declared = module_declared_version(p)
            effective_dup = dup_declared or duplicate_name_ver
            if not base_declared or not effective_dup:
                out.append(Candidate(
                    7, rel(self.root, p),
                    f"doublon versionné; base={base.name}",
                    "SKIP_MANUAL_VERIFY",
                    [f"base_version={base_declared}", f"duplicate_version={effective_dup}"]
                ))
                continue
            if base_declared >= effective_dup:
                c = self._candidate(
                    7, p,
                    f"doublon versionné; base {base.name} version {base_declared} >= {effective_dup}",
                    allow_protected_dir=True,
                )
                out.append(c)
            else:
                out.append(Candidate(
                    7, rel(self.root, p),
                    f"doublon plus récent que base {base.name}",
                    "SKIP_MANUAL_VERIFY",
                    [f"base_version={base_declared}", f"duplicate_version={effective_dup}"]
                ))
        return out

    def candidates_for_lot(self, lot: int) -> list[Candidate]:
        fn = getattr(self, f"lot{lot}", None)
        if fn is None:
            raise ValueError(f"Lot invalide: {lot}")
        return fn()

    def all_lots(self) -> dict[int, list[Candidate]]:
        return {n: self.candidates_for_lot(n) for n in range(1, 8)}

def quarantine_apply(root: Path, candidates: Iterable[Candidate], lot: int) -> Path:
    selected = [c for c in candidates if c.status == "CANDIDATE"]
    qdir = root / f"_quarantaine_{stamp()}_lot{lot}"
    qdir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "version": VERSION,
        "lot": lot,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "files": [],
    }
    for c in selected:
        src = root / c.path
        if not src.exists() or not src.is_file():
            raise RuntimeError(f"Fichier candidat absent au moment du déplacement: {src}")
        dst = qdir / c.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "original": c.path,
            "quarantine": rel(qdir, dst),
            "sha256": sha256(src),
            "size": src.stat().st_size,
            "reason": c.reason,
        }
        shutil.move(str(src), str(dst))
        manifest["files"].append(record)
    (qdir / "MANIFESTE.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return qdir

def restore_quarantine(root: Path, qdir: Path) -> None:
    manifest_path = qdir / "MANIFESTE.json"
    if not manifest_path.exists():
        raise RuntimeError("MANIFESTE.json introuvable.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for rec in manifest.get("files", []):
        src = qdir / rec["quarantine"]
        dst = root / rec["original"]
        if dst.exists():
            raise RuntimeError(f"Restauration refusée, destination existe déjà: {dst}")
        if not src.exists():
            raise RuntimeError(f"Fichier de quarantaine absent: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        if sha256(dst) != rec["sha256"]:
            raise RuntimeError(f"SHA256 différent après restauration: {dst}")

def patch_tools_classification(root: Path, module_name: str = "cleanup_workspace_audit") -> dict:
    run_all = root / "diagnostics" / "run_all.py"
    audit_file = root / "diagnostics" / f"{module_name}.py"
    if not run_all.exists() or not audit_file.exists():
        raise RuntimeError("run_all.py ou cleanup_workspace_audit.py introuvable.")

    text = run_all.read_text(encoding="utf-8")
    cats = literal_classified_modules(run_all)
    if module_name in set().union(*cats.values()):
        return {"status": "ALREADY_CLASSIFIED", "category": next(k for k,v in cats.items() if module_name in v)}

    tree = ast.parse(text)
    target = None
    value = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "TOOLS":
            target = node
            value = node.value
            break
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "TOOLS":
            target = node
            value = node.value
            break
    if target is None or value is None:
        raise RuntimeError("Affectation TOOLS introuvable dans run_all.py.")

    literal = ast.literal_eval(value)
    if not isinstance(literal, (set, list, tuple)):
        raise RuntimeError(f"Type TOOLS non supporté pour patch sûr: {type(literal).__name__}")

    items = [str(x) for x in literal]
    items.append(module_name)
    items = sorted(set(items))

    if isinstance(literal, set):
        replacement = "{\n" + "".join(f'    "{x}",\n' for x in items) + "}"
    elif isinstance(literal, list):
        replacement = "[\n" + "".join(f'    "{x}",\n' for x in items) + "]"
    else:
        replacement = "(\n" + "".join(f'    "{x}",\n' for x in items) + ")"

    lines = text.splitlines(keepends=True)
    start_line = value.lineno - 1
    end_line = value.end_lineno - 1
    start_col = value.col_offset
    end_col = value.end_col_offset
    prefix = lines[start_line][:start_col]
    suffix = lines[end_line][end_col:]
    new_lines = lines[:start_line] + [prefix + replacement + suffix] + lines[end_line + 1:]
    new_text = "".join(new_lines)

    backup = root / "backups" / f"CLEANUP_WORKSPACE_CLASSIFICATION_{stamp()}" / "diagnostics" / "run_all.py"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(run_all, backup)
    run_all.write_text(new_text, encoding="utf-8")

    try:
        compile(new_text, str(run_all), "exec")
        cats2 = literal_classified_modules(run_all)
        if module_name not in cats2["TOOLS"]:
            raise RuntimeError("Le nouvel audit n'est pas présent dans TOOLS après patch.")
    except Exception:
        shutil.copy2(backup, run_all)
        raise

    report = {
        "status": "GREEN",
        "module": module_name,
        "category": "TOOLS",
        "backup": str(backup),
    }
    out = root / "exports" / "logs" / "diagnostics"
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"CLEANUP_WORKSPACE_CLASSIFICATION_{stamp()}.json"
    p.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report

def git_state(root: Path) -> dict:
    git = root / ".git"
    if not git.exists():
        return {"available": False}
    try:
        cp = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=20,
        )
        return {
            "available": cp.returncode == 0,
            "dirty": bool(cp.stdout.strip()) if cp.returncode == 0 else None,
            "lines": len(cp.stdout.splitlines()) if cp.returncode == 0 else None,
        }
    except Exception as exc:
        return {"available": False, "error": repr(exc)}

def write_dry_run(root: Path, lots: dict[int, list[Candidate]]) -> Path:
    outdir = root / "exports" / "logs" / "diagnostics"
    outdir.mkdir(parents=True, exist_ok=True)
    ts = stamp()
    base = outdir / f"CLEANUP_WORKSPACE_DRY_RUN_V1_{ts}"
    base.mkdir(parents=True, exist_ok=True)

    report = {
        "status": "GREEN_DRY_RUN",
        "version": VERSION,
        "root": str(root),
        "timestamp": ts,
        "git": git_state(root),
        "apply_performed": False,
        "lots": {},
    }
    txt = [
        "JOBHUNTER - CLEANUP WORKSPACE V1 - DRY RUN",
        "=" * 72,
        "STATUS=GREEN_DRY_RUN",
        "APPLY_PERFORMED=FALSE",
        "",
    ]
    for lot, items in lots.items():
        counts: dict[str, int] = {}
        for c in items:
            counts[c.status] = counts.get(c.status, 0) + 1
        report["lots"][str(lot)] = {
            "counts": counts,
            "items": [asdict(c) for c in items],
        }
        txt.append(f"LOT {lot}")
        txt.append("-" * 72)
        txt.append(" | ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "EMPTY")
        for c in items:
            guard = ""
            if c.protected_by:
                guard = " | " + "; ".join(c.protected_by[:5])
            txt.append(f"{c.status:18s} | {c.path} | {c.reason}{guard}")
        txt.append("")

    if report["git"].get("available") and report["git"].get("dirty"):
        txt.append("IMPORTANT: git working tree is dirty.")
        txt.append("Before any --apply: create the requested pre-cleanup commit.")
    txt.append("")
    txt.append("NO FILE WAS MOVED OR DELETED.")

    (base / "00_DRY_RUN_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (base / "00_DRY_RUN_REPORT.txt").write_text("\n".join(txt), encoding="utf-8")

    # Include latest audit/classification reports for one handoff ZIP.
    diagdir = root / "exports" / "logs" / "diagnostics"
    for pattern in (
        "CLEANUP_WORKSPACE_AUDIT_V1_*.json",
        "CLEANUP_WORKSPACE_AUDIT_V1_*.txt",
        "CLEANUP_WORKSPACE_CLASSIFICATION_*.json",
    ):
        matches = list(diagdir.glob(pattern))
        if matches:
            latest = max(matches, key=lambda p: p.stat().st_mtime_ns)
            shutil.copy2(latest, base / latest.name)

    zpath = outdir / f"CLEANUP_WORKSPACE_DRY_RUN_V1_RESULTS_{ts}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in base.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(base))
    return zpath

def main():
    parser = argparse.ArgumentParser(description="JobHunter reversible workspace cleanup")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Default: list only")
    mode.add_argument("--apply", action="store_true", help="Move candidates to quarantine")
    parser.add_argument("--lot", type=int, choices=range(1, 8))
    parser.add_argument("--all-lots", action="store_true")
    parser.add_argument("--restore", type=str)
    parser.add_argument("--classify-audit", action="store_true")
    parser.add_argument("--export-results", action="store_true")
    args = parser.parse_args()

    if args.classify_audit:
        result = patch_tools_classification(ROOT)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.restore:
        restore_quarantine(ROOT, Path(args.restore).resolve())
        print("RESTORE=GREEN")
        return 0

    if not args.lot and not args.all_lots:
        parser.error("Choisir --lot N ou --all-lots.")

    cleaner = WorkspaceCleaner(ROOT)
    lots = cleaner.all_lots() if args.all_lots else {args.lot: cleaner.candidates_for_lot(args.lot)}

    if args.apply:
        # Safety protocol: require a clean git worktree if git exists.
        gs = git_state(ROOT)
        if gs.get("available") and gs.get("dirty"):
            raise RuntimeError(
                "APPLY refusé: git worktree non propre. "
                "Fais d'abord le commit 'Etat avant nettoyage'."
            )
        if len(lots) != 1:
            raise RuntimeError("--apply exige exactement un --lot N à la fois.")
        lot = next(iter(lots))
        qdir = quarantine_apply(ROOT, lots[lot], lot)
        print(f"QUARANTINE={qdir}")
        print("APPLY=GREEN")
        return 0

    # Dry-run default.
    for lot, items in lots.items():
        print(f"LOT {lot}")
        counts: dict[str, int] = {}
        for c in items:
            counts[c.status] = counts.get(c.status, 0) + 1
        print(json.dumps(counts, ensure_ascii=False, sort_keys=True))
    if args.export_results:
        zpath = write_dry_run(ROOT, lots)
        print(f"RESULT_ZIP={zpath}")
    print("STATUS=GREEN_DRY_RUN")
    print("APPLY_PERFORMED=FALSE")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("STATUS=ERROR")
        print(f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1)
