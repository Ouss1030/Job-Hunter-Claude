from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from interface.data_access import ROOT

DAILY_DIR = ROOT / "exports" / "logs" / "daily_runs"

_STEP_TIMING_RE = re.compile(r"^\s*(\d+)/(\d+)\s+(\d{2}:\d{2}:\d{2})\s+\|\s+(.+?)\s*$", re.M)
_SOURCE_RUNTIME_RE = re.compile(
    r"SOURCE_RUNTIME\s*\|\s*(\d+)/(\d+)\s*\|\s*key=([^|]+)\|\s*seconds=([0-9.]+)\s*\|\s*jobs=(\d+)\s*\|\s*status=([^\r\n|]+)",
    re.I,
)
_ENRICH_RUNTIME_RE = re.compile(
    r"ENRICH_RUNTIME\s*\|\s*source=([^|]+)\|\s*jobs=(\d+)\s*\|\s*seconds=([0-9.]+)\s*\|\s*avg=([0-9.]+)\s*\|\s*success=(\d+)\s*\|\s*cache=(\d+)\s*\|\s*failures=(\d+)",
    re.I,
)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _duration(started, finished) -> int | None:
    a = _parse_iso(started)
    b = _parse_iso(finished)
    if not a or not b:
        return None
    return max(0, int((b - a).total_seconds()))


def _hms_seconds(value: str) -> int:
    h, m, s = (int(x) for x in value.split(":"))
    return h * 3600 + m * 60 + s


def _manifest_paths() -> list[Path]:
    if not DAILY_DIR.exists():
        return []
    paths = [p for p in DAILY_DIR.glob("daily_run_v1_*.json") if p.is_file()]
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


def _main_log_path(payload: dict) -> Path | None:
    row = ((payload.get("steps") or {}).get("main") or {})
    for raw in (
        ((row.get("artifacts") or {}).get("main_log")),
        row.get("log"),
    ):
        if raw:
            path = Path(raw)
            if path.exists():
                return path
    return None


def pipeline_run_history(limit: int = 30) -> list[dict]:
    rows = []
    for path in _manifest_paths()[: max(1, int(limit))]:
        data = _read_json(path)
        if not data:
            continue
        steps = data.get("steps") or {}
        delta = ((steps.get("delta") or {}).get("validation") or {})
        counters = delta.get("counters") or {}
        final_validation = ((steps.get("final_pool") or {}).get("validation") or {})
        actions = final_validation.get("actions") or {}
        main_row = steps.get("main") or {}
        rows.append(
            {
                "run_id": data.get("run_id") or path.stem,
                "started_at": data.get("started_at"),
                "finished_at": data.get("finished_at"),
                "status": data.get("status"),
                "duration_seconds": _duration(data.get("started_at"), data.get("finished_at")),
                "main_seconds": _duration(main_row.get("started_at"), main_row.get("finished_at")),
                "final_pool": final_validation.get("count", delta.get("current_total")),
                "apply_now": actions.get("APPLY_NOW", 0),
                "new": counters.get("NEW", 0),
                "reactivated": counters.get("REACTIVATED", 0),
                "reposted": counters.get("REPOSTED", 0),
                "updated": counters.get("UPDATED", 0),
                "unchanged": counters.get("UNCHANGED", 0),
                "disappeared": counters.get("DISAPPEARED", 0),
                "manifest_path": str(path),
            }
        )
    return rows


def latest_main_internal_durations() -> list[dict]:
    paths = _manifest_paths()
    if not paths:
        return []
    data = _read_json(paths[0])
    log_path = _main_log_path(data)
    if not log_path:
        return []
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    rows = []
    for m in _STEP_TIMING_RE.finditer(text):
        rows.append(
            {
                "step": int(m.group(1)),
                "total_steps": int(m.group(2)),
                "duration_seconds": _hms_seconds(m.group(3)),
                "duration": m.group(3),
                "label": m.group(4).strip(),
            }
        )
    # Le bloc final n'apparaît qu'une fois normalement ; dédoublonnage défensif.
    dedup = {}
    for row in rows:
        dedup[row["step"]] = row
    return [dedup[k] for k in sorted(dedup)]


def latest_source_runtimes() -> list[dict]:
    paths = _manifest_paths()
    if not paths:
        return []
    data = _read_json(paths[0])
    log_path = _main_log_path(data)
    if not log_path:
        return []
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    rows = []
    for m in _SOURCE_RUNTIME_RE.finditer(text):
        rows.append(
            {
                "index": int(m.group(1)),
                "total": int(m.group(2)),
                "source": m.group(3).strip(),
                "seconds": round(float(m.group(4)), 2),
                "jobs": int(m.group(5)),
                "status": m.group(6).strip(),
            }
        )
    return sorted(rows, key=lambda x: x["seconds"], reverse=True)


def latest_enrichment_runtimes() -> list[dict]:
    paths = _manifest_paths()
    if not paths:
        return []
    data = _read_json(paths[0])
    log_path = _main_log_path(data)
    if not log_path:
        return []
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    rows = []
    for m in _ENRICH_RUNTIME_RE.finditer(text):
        rows.append(
            {
                "source": m.group(1).strip(),
                "jobs": int(m.group(2)),
                "seconds": round(float(m.group(3)), 2),
                "avg_seconds": round(float(m.group(4)), 3),
                "success": int(m.group(5)),
                "cache": int(m.group(6)),
                "failures": int(m.group(7)),
            }
        )
    return sorted(rows, key=lambda x: x["seconds"], reverse=True)
