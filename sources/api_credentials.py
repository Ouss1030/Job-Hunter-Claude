"""
JOBHUNTER - PRIVATE API CREDENTIALS V1

Secrets are read from:
1) process environment variables
2) config/private/api_keys.env

config/private/ is excluded locally from Git by the V7 installer.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_DIR = PROJECT_ROOT / "config" / "private"
PRIVATE_FILE = PRIVATE_DIR / "api_keys.env"

REQUIREMENTS = {
    "ADZUNA": ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"),
    "CAREERJET": ("CAREERJET_API_KEY", "CAREERJET_USER_IP"),
    "JOOBLE": ("JOOBLE_API_KEY",),
    "VDAB": ("VDAB_API_KEY", "VDAB_CLIENT_ID"),
}


def _parse_file() -> dict[str, str]:
    out = {}
    if not PRIVATE_FILE.exists():
        return out
    for raw in PRIVATE_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def load_api_credentials() -> dict[str, str]:
    values = _parse_file()
    for keys in REQUIREMENTS.values():
        for key in keys:
            if os.environ.get(key):
                values[key] = os.environ[key].strip()
    # Optional configuration.
    for key in (
        "CAREERJET_LOCALE_CODE",
        "CAREERJET_USER_AGENT",
        "JOOBLE_QUERIES_PER_RUN",
        "ADZUNA_RESULTS_PER_QUERY",
    ):
        if os.environ.get(key):
            values[key] = os.environ[key].strip()
    return values


def credential_status(source_key: str) -> dict:
    key = str(source_key or "").strip().upper()
    required = REQUIREMENTS.get(key, ())
    values = load_api_credentials()
    missing = [name for name in required if not values.get(name)]
    return {
        "source": key,
        "required": list(required),
        "missing": missing,
        "ready": bool(required) and not missing,
        "private_file": str(PRIVATE_FILE),
    }


def get_credential(name: str, default: str | None = None) -> str | None:
    return load_api_credentials().get(name, default)
