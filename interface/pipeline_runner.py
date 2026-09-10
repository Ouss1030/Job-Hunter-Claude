from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from interface.data_access import DAILY_DIR, ROOT


LOCK_PATH = DAILY_DIR / ".daily_run.lock"
UI_LOG_DIR = ROOT / "exports" / "logs" / "ui"
STATE_PATH = UI_LOG_DIR / "daily_run_ui_state.json"
WORKER_PATH = Path(__file__).resolve().parent / "production_run_worker.py"
PRODUCTION_RUNNER_PATH = ROOT / "diagnostics" / "production_runner_v1.py"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _utf8_env() -> dict[str, str]:
    """Force UTF-8 for redirected Python stdout/stderr on Windows.

    daily_run.py prints Unicode symbols (✅, ❌, ℹ️...).  When stdout is
    redirected to a file on a non-UTF-8 Windows locale, Python can otherwise
    inherit cp1252 and fail with UnicodeEncodeError before the pipeline starts.
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _read_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_run_state() -> dict:
    return _read_state()


def _pid_exists(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False

    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
            return str(pid) in (result.stdout or "")
        except Exception:
            # Le lock du vrai daily_run reste la source de vérité principale.
            return False

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def is_running() -> bool:
    # Source de vérité du moteur existant.
    if LOCK_PATH.exists():
        return True

    # Couvre la courte fenêtre entre le clic et la création du lock daily_run.
    state = _read_state()
    if state.get("status") in {"STARTING", "RUNNING"}:
        return _pid_exists(state.get("worker_pid"))
    return False


def latest_ui_log() -> Path | None:
    if not UI_LOG_DIR.exists():
        return None
    logs = list(UI_LOG_DIR.glob("daily_run_ui_*.txt"))
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else None


def _run_preflight() -> tuple[bool, str]:
    """Run daily_run.py --check in the exact interpreter used by Streamlit."""
    command = [
        sys.executable,
        "-X",
        "utf8",
        "-u",
        str(ROOT / "daily_run.py"),
        "--check",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=str(ROOT),
            env=_utf8_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )
    except Exception as exc:
        return False, f"Impossible d'exécuter le préflight : {type(exc).__name__}: {exc}"

    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if result.returncode != 0:
        return False, output or f"Préflight terminé avec le code {result.returncode}."
    return True, output


def launch_daily_run() -> Path:
    """Validate the environment, then start the certified Production Runner through a small worker.

    The worker survives Streamlit reruns, forces UTF-8, captures the real return
    code, and persists a state file that the dashboard can display.
    """
    if is_running():
        raise RuntimeError("Un Daily Run est déjà en cours.")

    daily_run = ROOT / "daily_run.py"
    if not daily_run.exists():
        raise FileNotFoundError(f"daily_run.py introuvable : {daily_run}")
    if not PRODUCTION_RUNNER_PATH.exists():
        raise FileNotFoundError(f"Production Runner introuvable : {PRODUCTION_RUNNER_PATH}")
    if not WORKER_PATH.exists():
        raise FileNotFoundError(f"Lanceur UI introuvable : {WORKER_PATH}")

    UI_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = UI_LOG_DIR / f"daily_run_ui_{stamp}.txt"

    ok, preflight_output = _run_preflight()
    if not ok:
        log_path.write_text(
            "JOBHUNTER UI - PREFLIGHT ÉCHOUÉ\n\n" + preflight_output + "\n",
            encoding="utf-8",
        )
        raise RuntimeError(
            "Le préflight du moteur JobHunter a échoué. "
            f"Ouvre le journal {log_path.name} dans le Dashboard pour voir la cause."
        )

    # Garde le préflight au début du journal : utile pour diagnostiquer la machine.
    log_path.write_text(
        "JOBHUNTER UI - PREFLIGHT OK\n"
        + (preflight_output + "\n\n" if preflight_output else "\n")
        + "JOBHUNTER UI - DÉMARRAGE DU PRODUCTION RUNNER\n\n",
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-X",
        "utf8",
        "-u",
        str(WORKER_PATH),
        "--log",
        str(log_path),
        "--state",
        str(STATE_PATH),
    ]

    creationflags = 0
    if os.name == "nt":
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        # Pas de deuxième fenêtre noire : le journal est visible dans Streamlit.
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            env=_utf8_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
    except Exception as exc:
        raise RuntimeError(f"Échec du lancement du worker : {type(exc).__name__}: {exc}") from exc

    # État immédiat pour éviter le trou entre Popen() et l'initialisation du worker.
    state = {
        "status": "STARTING",
        "started_at": _now_iso(),
        "finished_at": None,
        "worker_pid": process.pid,
        "returncode": None,
        "log_path": str(log_path),
        "error": None,
    }
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return log_path
