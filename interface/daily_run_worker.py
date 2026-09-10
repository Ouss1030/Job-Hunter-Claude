from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def utf8_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--state", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    log_path = Path(args.log)
    state_path = Path(args.state)

    state = {
        "status": "RUNNING",
        "started_at": now_iso(),
        "finished_at": None,
        "worker_pid": os.getpid(),
        "returncode": None,
        "log_path": str(log_path),
        "error": None,
    }
    atomic_write_json(state_path, state)

    command = [
        sys.executable,
        "-X",
        "utf8",
        "-u",
        str(root / "daily_run.py"),
        "--no-handoff",
    ]

    try:
        with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
            log_file.write(f"Worker PID : {os.getpid()}\n")
            log_file.write(f"Python     : {sys.executable}\n")
            log_file.write(f"Commande   : {' '.join(command)}\n")
            log_file.write("Mode       : handoff ChatGPT automatique désactivé (création manuelle via l'interface)\n\n")
            log_file.flush()

            result = subprocess.run(
                command,
                cwd=str(root),
                env=utf8_env(),
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                check=False,
            )

        state["returncode"] = result.returncode
        state["finished_at"] = now_iso()
        state["status"] = "COMPLETED" if result.returncode == 0 else "FAILED"
        if result.returncode != 0:
            state["error"] = f"daily_run.py s'est terminé avec le code {result.returncode}."
        atomic_write_json(state_path, state)
        return result.returncode

    except Exception as exc:
        state["status"] = "FAILED"
        state["finished_at"] = now_iso()
        state["returncode"] = -1
        state["error"] = f"{type(exc).__name__}: {exc}"
        atomic_write_json(state_path, state)
        try:
            with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
                log_file.write("\nJOBHUNTER UI WORKER ERROR\n")
                log_file.write(state["error"] + "\n")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
