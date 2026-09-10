from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from interface.data_access import ROOT
from interface.pipeline_runner import get_run_state

DAILY_DIR = ROOT / "exports" / "logs" / "daily_runs"
STEP_ORDER = ["main", "preparation", "refresh", "recheck", "final_pool", "delta", "lifecycle", "handoff"]
STEP_LABELS = {
    "main": "Collecte + scoring principal",
    "preparation": "Préparation des candidatures",
    "refresh": "Vérification des offres",
    "recheck": "Réévaluation",
    "final_pool": "Final Application Pool",
    "delta": "Delta / nouveautés",
    "lifecycle": "Lifecycle candidatures",
    "handoff": "Handoff ChatGPT",
}
STATUS_LABELS = {
    "PENDING": "⏳ En attente", "RUNNING": "🔄 En cours", "COMMAND_OK": "🔎 Validation",
    "DONE": "✅ Terminé", "SKIPPED": "⏭️ Ignoré", "FAILED": "❌ Échec",
}

MAIN_STAGE_RE = re.compile(r"AVANCEMENT GLOBAL\s*-\s*ÉTAPE\s+(\d+)\s*/\s*(\d+)", re.I)
MAIN_STAGE_LABEL_RE = re.compile(r"^Étape\s*:\s*(.+?)\s*$", re.I | re.M)
SOURCE_PROGRESS_RE = re.compile(r"SOURCE_PROGRESS\s*\|\s*(\d+)\s*/\s*(\d+)\s*\|\s*key=([^|]+)\|\s*label=([^|]+)\|\s*START", re.I)
SOURCE_HEADER_RE = re.compile(r"SOURCE\s+(\d+)\s*-\s*([^\r\n=]+)", re.I)
PRESCORE_RE = re.compile(r"Pré-score standard\s*:\s*(\d+)\s*/\s*(\d+).*?\|\s*écoulé", re.I)
ENRICH_RE = re.compile(r"^\[\s*(\d+)\s*/\s*(\d+)\]\s+([^|\r\n]+?)\s*\|.*?\|\s*(.+?)\s*$", re.M)
GENERIC_PROGRESS_RE = re.compile(r"^\[\s*(\d+)\s*/\s*(\d+)\]\s*(.+?)\s*$", re.M)


def _parse_iso(value: str | None) -> datetime | None:
    if not value: return None
    try: return datetime.fromisoformat(value)
    except Exception: return None


def _read_json(path: Path) -> dict:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return {}


def latest_daily_manifest() -> tuple[Path | None, dict]:
    if not DAILY_DIR.exists(): return None, {}
    candidates = []
    for path in DAILY_DIR.glob("daily_run_v1_*.json"):
        data = _read_json(path)
        if data: candidates.append((path, data))
    if not candidates: return None, {}
    ui_state = get_run_state()
    ui_started = _parse_iso(ui_state.get("started_at"))
    if ui_started:
        relevant = []
        for path, data in candidates:
            started = _parse_iso(data.get("started_at"))
            if started and started >= ui_started.replace(microsecond=0): relevant.append((path, data))
        if relevant: candidates = relevant
    path, data = max(candidates, key=lambda pair: (_parse_iso(pair[1].get("started_at")) or datetime.min, pair[0].stat().st_mtime))
    return path, data


def current_step(manifest: dict) -> str | None:
    steps = manifest.get("steps") or {}
    for step in STEP_ORDER:
        if (steps.get(step) or {}).get("status") in {"RUNNING", "COMMAND_OK"}: return step
    for step in STEP_ORDER:
        if (steps.get(step) or {}).get("status") not in {"DONE", "SKIPPED"}: return step
    return None


def completed_steps(manifest: dict) -> int:
    steps = manifest.get("steps") or {}
    return sum(1 for step in STEP_ORDER if (steps.get(step) or {}).get("status") in {"DONE", "SKIPPED"})


def step_rows(manifest: dict) -> list[dict]:
    steps = manifest.get("steps") or {}
    rows = []
    for idx, step in enumerate(STEP_ORDER, start=1):
        row = steps.get(step) or {}; status = row.get("status") or "PENDING"
        rows.append({"#": idx, "Étape": STEP_LABELS.get(step, step), "État": STATUS_LABELS.get(status, status), "Début": row.get("started_at") or "—", "Fin": row.get("finished_at") or "—"})
    return rows


def _tail_text(path: Path, max_bytes: int = 850_000) -> str:
    if not path.exists(): return ""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes: fh.seek(-max_bytes, 2)
            raw = fh.read()
        return raw.decode("utf-8", errors="replace")
    except Exception: return ""


def _last_nonempty_lines(text: str, count: int = 10) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()][-count:]


def _last_main_stage(text: str) -> tuple[int | None, int | None, str | None, int]:
    matches = list(MAIN_STAGE_RE.finditer(text))
    if not matches: return None, None, None, -1
    m = matches[-1]; segment = text[m.end():]
    lm = MAIN_STAGE_LABEL_RE.search(segment)
    return int(m.group(1)), int(m.group(2)), (lm.group(1).strip() if lm else None), m.start()


def active_step_activity(manifest: dict) -> dict:
    step = current_step(manifest)
    if not step: return {}
    row = ((manifest.get("steps") or {}).get(step) or {})
    log_raw = row.get("log"); log_path = Path(log_raw) if log_raw else None
    text = _tail_text(log_path) if log_path else ""
    result = {
        "step": step, "step_label": STEP_LABELS.get(step, step), "status": row.get("status") or "PENDING",
        "log_path": str(log_path) if log_path else None, "tail_lines": _last_nonempty_lines(text, 12),
        "log_age_seconds": None, "source": None, "source_index": None, "source_total": None,
        "main_stage_current": None, "main_stage_total": None, "main_stage_label": None,
        "item_current": None, "item_total": None, "item_label": None, "activity_kind": None,
        # compatibilité UI précédente
        "keyword_current": None, "keyword_total": None, "keyword": None,
    }
    if log_path and log_path.exists():
        try: result["log_age_seconds"] = max(0, int(datetime.now().timestamp() - log_path.stat().st_mtime))
        except Exception: pass

    if step != "main" or not text: return result

    stage_cur, stage_tot, stage_label, stage_pos = _last_main_stage(text)
    result.update(main_stage_current=stage_cur, main_stage_total=stage_tot, main_stage_label=stage_label)
    segment = text[stage_pos:] if stage_pos >= 0 else text

    if stage_cur == 1:
        sp = list(SOURCE_PROGRESS_RE.finditer(segment))
        if sp:
            m = sp[-1]
            result.update(source_index=int(m.group(1)), source_total=int(m.group(2)), source=m.group(4).strip())
            source_segment = segment[m.start():]
        else:
            sh = list(SOURCE_HEADER_RE.finditer(segment))
            if sh:
                m = sh[-1]; result.update(source_index=int(m.group(1)), source=m.group(2).strip()); source_segment = segment[m.start():]
            else: source_segment = segment
        gm = list(GENERIC_PROGRESS_RE.finditer(source_segment))
        if gm:
            m = gm[-1]
            result.update(item_current=int(m.group(1)), item_total=int(m.group(2)), item_label=m.group(3).strip()[:120], activity_kind="Progression source")
    elif stage_cur == 3:
        pm = list(PRESCORE_RE.finditer(segment))
        if pm:
            m = pm[-1]; result.update(item_current=int(m.group(1)), item_total=int(m.group(2)), activity_kind="Pré-score")
    elif stage_cur == 4:
        gm = list(GENERIC_PROGRESS_RE.finditer(segment))
        if gm:
            m = gm[-1]; result.update(item_current=int(m.group(1)), item_total=int(m.group(2)), item_label=m.group(3).strip()[:120], activity_kind="Travaillerpour")
    elif stage_cur == 5:
        em = list(ENRICH_RE.finditer(segment))
        if em:
            m = em[-1]
            result.update(item_current=int(m.group(1)), item_total=int(m.group(2)), source=m.group(3).strip(), item_label=m.group(4).strip()[:120], activity_kind="Enrichissement")

    # Compatibilité avec l'ancien rendu de mots-clés.
    result["keyword_current"] = result["item_current"]
    result["keyword_total"] = result["item_total"]
    result["keyword"] = result["item_label"]
    return result


def run_elapsed_seconds(manifest: dict, ui_state: dict | None = None) -> int | None:
    started = _parse_iso(manifest.get("started_at"))
    if not started and ui_state: started = _parse_iso(ui_state.get("started_at"))
    if not started: return None
    finished = _parse_iso(manifest.get("finished_at"))
    if not finished and ui_state: finished = _parse_iso(ui_state.get("finished_at"))
    end = finished or datetime.now()
    return max(0, int((end - started).total_seconds()))


def format_duration(seconds: int | None) -> str:
    if seconds is None: return "—"
    minutes, sec = divmod(int(seconds), 60); hours, minutes = divmod(minutes, 60)
    if hours: return f"{hours} h {minutes:02d} min {sec:02d} s"
    return f"{minutes} min {sec:02d} s"
