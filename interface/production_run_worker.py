from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def utf8_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()

    log_path = Path(args.log)
    state_path = Path(args.state)
    state = read_state(state_path)
    state.update({
        "status": "RUNNING",
        "started_at": state.get("started_at") or now_iso(),
        "finished_at": None,
        "returncode": None,
        "runner": "PRODUCTION_RUNNER_V1",
        "error": None,
    })
    write_state(state_path, state)

    command = [
        sys.executable,
        "-X", "utf8",
        "-u",
        "-m", "diagnostics.production_runner_v1",
    ]

    try:
        with log_path.open("a", encoding="utf-8") as log:
            log.write("COMMAND: " + " ".join(command) + "\n\n")
            log.flush()
            proc = subprocess.Popen(
                command,
                cwd=str(ROOT),
                env=utf8_env(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            state["engine_pid"] = proc.pid
            write_state(state_path, state)
            rc = proc.wait()

        state.update({
            "status": "COMPLETED" if rc == 0 else "FAILED",
            "finished_at": now_iso(),
            "returncode": rc,
        })
        if rc != 0:
            state["error"] = "Production Runner returned a non-zero exit code. DB rollback is handled by Production Runner."
        write_state(state_path, state)
        return rc
    except Exception as exc:
        state.update({
            "status": "FAILED",
            "finished_at": now_iso(),
            "returncode": -1,
            "error": f"{type(exc).__name__}: {exc}",
        })
        write_state(state_path, state)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
