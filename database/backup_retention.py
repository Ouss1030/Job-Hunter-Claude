from __future__ import annotations

import argparse
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

BACKUP_RETENTION_VERSION = "1.0"
DEFAULT_KEEP = 3
SQLITE_HEADER = b"SQLite format 3\x00"
_TIMESTAMP_RE = re.compile(r"(?<!\d)(20\d{6})[_-]?(\d{6})(?!\d)")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_ROOT = PROJECT_ROOT / "backups"
DEFAULT_LOG_DIR = PROJECT_ROOT / "exports" / "logs" / "diagnostics"


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _is_sqlite_file(path: Path) -> bool:
    try:
        if path.is_symlink() or not path.is_file():
            return False
        with path.open("rb") as handle:
            return handle.read(len(SQLITE_HEADER)) == SQLITE_HEADER
    except OSError:
        return False


def _timestamp_key(path: Path) -> tuple[float, int, str]:
    text = str(path)
    matches = list(_TIMESTAMP_RE.finditer(text))
    parsed = None
    if matches:
        date, clock = matches[-1].groups()
        try:
            parsed = datetime.strptime(date + clock, "%Y%m%d%H%M%S").timestamp()
        except ValueError:
            parsed = None
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    if parsed is None:
        parsed = mtime_ns / 1_000_000_000
    return (parsed, mtime_ns, str(path).lower())


def discover_backup_databases(backup_root: Path) -> tuple[list[Path], list[Path]]:
    backup_root = Path(backup_root)
    valid: list[Path] = []
    ignored_non_sqlite: list[Path] = []
    if not backup_root.exists():
        return valid, ignored_non_sqlite

    for path in backup_root.rglob("*.db"):
        if path.is_symlink():
            ignored_non_sqlite.append(path)
            continue
        if _is_sqlite_file(path):
            valid.append(path)
        else:
            ignored_non_sqlite.append(path)

    valid.sort(key=_timestamp_key, reverse=True)
    ignored_non_sqlite.sort(key=lambda p: str(p).lower())
    return valid, ignored_non_sqlite


def build_retention_plan(backup_root: Path, keep: int = DEFAULT_KEEP) -> dict:
    keep = max(1, int(keep))
    backup_root = Path(backup_root)
    databases, ignored = discover_backup_databases(backup_root)
    kept = databases[:keep]
    remove = databases[keep:]
    return {
        "backup_root": str(backup_root.resolve()),
        "keep_count": keep,
        "database_count": len(databases),
        "kept": kept,
        "remove": remove,
        "ignored_non_sqlite": ignored,
        "remove_bytes": sum(p.stat().st_size for p in remove if p.exists()),
    }


def _render_report(plan: dict, *, applied: bool, deleted: list[Path], errors: list[str]) -> str:
    lines = [
        "=" * 112,
        f"JOBHUNTER - BACKUP RETENTION V{BACKUP_RETENTION_VERSION}",
        "=" * 112,
        f"MODE={'APPLY' if applied else 'DRY_RUN'}",
        f"BACKUP_ROOT={plan['backup_root']}",
        f"KEEP_COUNT={plan['keep_count']}",
        f"SQLITE_BACKUP_COUNT={plan['database_count']}",
    ]

    for path in plan["kept"]:
        size = path.stat().st_size if path.exists() else 0
        lines.append(f" KEEP_DB | {_human_size(size):>10} | {path}")
    for path in plan["remove"]:
        size = path.stat().st_size if path.exists() else 0
        lines.append(f" REMOVE_DB_CANDIDATE | {_human_size(size):>10} | {path}")

    lines.append(f"REMOVE_CANDIDATE_COUNT={len(plan['remove'])}")
    lines.append(f"REMOVE_CANDIDATE_SPACE={_human_size(plan['remove_bytes'])}")
    lines.append(f"IGNORED_NON_SQLITE_DB_FILES={len(plan['ignored_non_sqlite'])}")
    for path in plan["ignored_non_sqlite"]:
        lines.append(f" IGNORED_NON_SQLITE | {path}")

    if applied:
        lines.append(f"DELETED_COUNT={len(deleted)}")
        lines.append(f"DELETE_ERRORS={len(errors)}")
        for error in errors:
            lines.append(f" ERROR | {error}")
    else:
        lines.append("DELETED_COUNT=0")
        lines.append("DELETE_ERRORS=0")

    status = "GREEN" if not errors else "WARNING"
    lines.append(f"STATUS={status}")
    return "\n".join(lines) + "\n"


def enforce_backup_retention(
    *,
    backup_root: Path | None = None,
    keep: int = DEFAULT_KEEP,
    apply: bool = False,
    write_report: bool = True,
    log_dir: Path | None = None,
    verbose: bool = True,
) -> dict:
    backup_root = Path(backup_root or DEFAULT_BACKUP_ROOT)
    plan = build_retention_plan(backup_root, keep=keep)
    deleted: list[Path] = []
    errors: list[str] = []

    if apply:
        root_resolved = backup_root.resolve()
        for path in list(plan["remove"]):
            try:
                resolved = path.resolve()
                if not _is_within(resolved, root_resolved):
                    raise RuntimeError("path outside backups root")
                if path.is_symlink():
                    raise RuntimeError("refusing symlink")
                if not _is_sqlite_file(path):
                    raise RuntimeError("not a valid SQLite database")
                path.unlink()
                deleted.append(path)
            except Exception as exc:
                errors.append(f"{path}: {type(exc).__name__}: {exc}")

    text = _render_report(plan, applied=apply, deleted=deleted, errors=errors)
    report_path = None
    if write_report:
        log_dir = Path(log_dir or DEFAULT_LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        report_path = log_dir / f"BACKUP_RETENTION_V1_{_stamp()}.txt"
        report_path.write_text(text, encoding="utf-8")

    if verbose:
        print(text, end="")
        if report_path is not None:
            print(f"TXT={report_path}")

    return {
        **plan,
        "applied": apply,
        "deleted": deleted,
        "errors": errors,
        "status": "GREEN" if not errors else "WARNING",
        "report_path": report_path,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JobHunter backup retention V1")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Delete backups beyond retention count.")
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    args = parser.parse_args(list(argv) if argv is not None else None)

    result = enforce_backup_retention(
        backup_root=args.backup_root,
        keep=args.keep,
        apply=bool(args.apply),
        write_report=True,
        verbose=True,
    )
    return 0 if not result["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
