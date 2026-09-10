"""
JOBHUNTER - SOURCE HEALTH POLICY V1

Separates:
- enabled/disabled by user
- collection mode (LIVE / CACHE_ONLY)
- operational health (HEALTHY / DEGRADED / CACHE_ONLY / BROKEN / DISABLED)
"""

from __future__ import annotations

VALID_HEALTH = {"HEALTHY", "DEGRADED", "CACHE_ONLY", "BROKEN", "DISABLED", "NEEDS_CREDENTIALS"}
VALID_COLLECTION_MODES = {"LIVE", "CACHE_ONLY", "DISABLED", "API"}

_POLICY = {
    "JOBAT": {
        "health": "CACHE_ONLY",
        "collection_mode": "CACHE_ONLY",
        "reason": (
            "Live Jobat is temporarily unreliable because anti-bot pages/403 "
            "were observed. Keep connector and bounded cache, but do not use "
            "Jobat as a fresh LIVE source in production."
        ),
    },
    "SCIENSANO": {
        "health": "DEGRADED",
        "collection_mode": "LIVE",
        "reason": "Official portal has historically shown instability/timeouts.",
    },
}



_API_SOURCES = {"ADZUNA", "CAREERJET", "JOOBLE", "VDAB"}


def _api_credential_health(key: str):
    if key not in _API_SOURCES:
        return None
    try:
        from sources.api_credentials import credential_status
        status = credential_status(key)
    except Exception as exc:
        return {
            "key": key,
            "health": "DEGRADED",
            "collection_mode": "API",
            "reason": f"Credential status error: {type(exc).__name__}: {exc}",
        }

    if not status["ready"]:
        return {
            "key": key,
            "health": "NEEDS_CREDENTIALS",
            "collection_mode": "API",
            "reason": "Missing private API credentials: " + ", ".join(status["missing"]),
        }

    if key == "VDAB":
        return {
            "key": key,
            "health": "DEGRADED",
            "collection_mode": "API",
            "reason": "Credentials ready; Vacature 4.2.0 schema validation still required before activation.",
        }

    return {
        "key": key,
        "health": "HEALTHY",
        "collection_mode": "API",
        "reason": "Official API credentials configured.",
    }

def get_source_health(key: str, enabled: bool = True) -> dict:
    key = str(key or "").strip().upper()

    if not enabled:
        return {
            "key": key,
            "health": "DISABLED",
            "collection_mode": "DISABLED",
            "reason": "Source disabled by current source settings.",
        }

    api_health = _api_credential_health(key)
    if api_health is not None:
        return api_health

    row = dict(_POLICY.get(key) or {})
    health = str(row.get("health") or "HEALTHY").upper()
    mode = str(row.get("collection_mode") or "LIVE").upper()

    if health not in VALID_HEALTH:
        health = "DEGRADED"
    if mode not in VALID_COLLECTION_MODES:
        mode = "LIVE"

    return {
        "key": key,
        "health": health,
        "collection_mode": mode,
        "reason": str(row.get("reason") or "No known structural health issue."),
    }


def runtime_source_health(
    key: str,
    *,
    enabled: bool = True,
    error: str | None = None,
    metrics: dict | None = None,
) -> dict:
    base = get_source_health(key, enabled=enabled)

    if not enabled:
        return base

    if error:
        return {
            **base,
            "health": "BROKEN",
            "reason": f"Runtime collector error: {error}",
        }

    metrics = metrics or {}
    runtime_state = str(metrics.get("health_state") or "").upper()

    if base["health"] in {"CACHE_ONLY", "NEEDS_CREDENTIALS"}:
        return {
            **base,
            "runtime_state": runtime_state or None,
        }

    if "DEGRADED" in runtime_state or "UNAVAILABLE" in runtime_state:
        return {
            **base,
            "health": "DEGRADED",
            "runtime_state": runtime_state,
            "reason": f"Runtime state reported by source: {runtime_state}",
        }

    return {
        **base,
        "runtime_state": runtime_state or None,
    }


def all_policy_overrides() -> dict:
    return {key: dict(value) for key, value in _POLICY.items()}
