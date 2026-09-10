from __future__ import annotations

from copy import deepcopy
import threading


class _ThreadSafeStore(dict):
    """dict-compatible store protected for concurrent source collection."""

    def __init__(self):
        super().__init__()
        self._lock = threading.RLock()

    def __setitem__(self, key, value):
        with self._lock:
            return super().__setitem__(key, value)

    def __getitem__(self, key):
        with self._lock:
            return super().__getitem__(key)

    def get(self, key, default=None):
        with self._lock:
            return super().get(key, default)

    def pop(self, key, default=None):
        with self._lock:
            return super().pop(key, default)

    def clear(self):
        with self._lock:
            return super().clear()

    def update(self, *args, **kwargs):
        with self._lock:
            return super().update(*args, **kwargs)


_STORE: dict[str, dict] = _ThreadSafeStore()


def _safe_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _safe_len(value):
    if value is None:
        return None
    try:
        return len(value)
    except Exception:
        return None


def _sum_present(*values):
    nums = [_safe_int(v) for v in values]
    nums = [v for v in nums if v is not None]
    return sum(nums) if nums else None


def _meta(local_vars):
    value = local_vars.get("meta")
    return value if isinstance(value, dict) else {}


def _pick_seen(source_key: str, local_vars: dict):
    meta = _meta(local_vars)

    if source_key in {"JEFFERSON_WELLS", "AKKODIS"}:
        return _safe_int(meta.get("all_links"))

    if source_key in {"GSK", "PFIZER", "JNJ", "TAKEDA"}:
        return _safe_int(meta.get("belgium_rows"))

    if source_key == "QUALITY_ASSISTANCE":
        return _safe_int(meta.get("jobs_seen"))

    if source_key in {"UCB", "THERMO_FISHER"}:
        return _safe_len(local_vars.get("all_belgium"))

    if source_key == "IBA":
        return _safe_len(local_vars.get("belgium"))

    if source_key in {"SCIENCEATWORK", "RANDSTAD"}:
        return _safe_len(local_vars.get("links"))

    return None


def _pick_candidates(source_key: str, local_vars: dict):
    if source_key in {"SCIENCEATWORK", "RANDSTAD"}:
        return None

    candidates = local_vars.get("candidates")
    if candidates is not None:
        return _safe_len(candidates)

    meta = _meta(local_vars)
    return _safe_int(meta.get("candidates"))


def _pick_kept(local_vars: dict):
    return _safe_len(local_vars.get("jobs"))


def _pick_language_rejected(source_key: str, local_vars: dict):
    if source_key == "SCIENCEATWORK":
        return _sum_present(
            local_vars.get("rejected_nl"),
            local_vars.get("rejected_dutch_requirement"),
        )

    return _sum_present(
        local_vars.get("rejected_nl"),
        local_vars.get("rejected_dutch"),
    )


def _pick_closed(local_vars: dict):
    return _safe_int(local_vars.get("closed"))


def _pick_detail_errors(source_key: str, local_vars: dict):
    if source_key == "QUALITY_ASSISTANCE":
        return _safe_int(local_vars.get("detail_errors"))

    errors = local_vars.get("errors")
    if isinstance(errors, int):
        return int(errors)

    return None


def _pick_non_target(seen, candidates):
    if seen is None or candidates is None:
        return None
    value = int(seen) - int(candidates)
    return value if value >= 0 else None


STANDARD_METRIC_KEYS = (
    "seen",
    "target_title",
    "non_target",
    "detail_ok",
    "detail_failed",
    "geography_accepted",
    "geography_rejected",
    "geography_unknown",
    "language_rejected",
    "converted",
    "persisted",
    "errors",
)


def _first_present(mapping: dict, *keys):
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return None


def publish_source_metrics(source_key: str, payload: dict | None = None) -> dict:
    """Publish normalized source metrics while preserving legacy aliases."""
    key = str(source_key or "").upper()
    src = dict(payload or {})

    seen = _safe_int(_first_present(src, "seen"))
    target_title = _safe_int(_first_present(src, "target_title", "candidates"))
    non_target = _safe_int(_first_present(src, "non_target"))
    if non_target is None:
        non_target = _pick_non_target(seen, target_title)

    detail_ok = _safe_int(_first_present(src, "detail_ok"))
    detail_failed = _safe_int(_first_present(src, "detail_failed", "detail_errors"))
    geography_accepted = _safe_int(_first_present(src, "geography_accepted"))
    geography_rejected = _safe_int(_first_present(src, "geography_rejected", "rejected_geo"))
    geography_unknown = _safe_int(_first_present(src, "geography_unknown"))
    language_rejected = _safe_int(_first_present(src, "language_rejected", "rejected_language"))
    converted = _safe_int(_first_present(src, "converted", "kept"))
    persisted = _safe_int(_first_present(src, "persisted"))
    errors = _safe_int(_first_present(src, "errors"))

    normalized = {
        "seen": seen,
        "target_title": target_title,
        "non_target": non_target,
        "detail_ok": detail_ok,
        "detail_failed": detail_failed,
        "geography_accepted": geography_accepted,
        "geography_rejected": geography_rejected,
        "geography_unknown": geography_unknown,
        "language_rejected": language_rejected,
        "converted": converted,
        "persisted": persisted,
        "errors": errors,

        # Legacy aliases kept for existing consumers.
        "candidates": target_title,
        "kept": converted,
        "rejected_language": language_rejected,
        "rejected_geo": geography_rejected,
        "closed": _safe_int(_first_present(src, "closed")),
        "detail_errors": detail_failed,
    }

    _STORE[key] = normalized
    return deepcopy(normalized)


def publish_metrics_from_locals(source_key: str, local_vars: dict) -> dict:
    key = str(source_key or "").upper()

    seen = _pick_seen(key, local_vars)
    candidates = _pick_candidates(key, local_vars)
    kept = _pick_kept(local_vars)
    rejected_language = _pick_language_rejected(key, local_vars)
    closed = _pick_closed(local_vars)
    detail_errors = _pick_detail_errors(key, local_vars)

    geo = local_vars.get("_geo")
    if not isinstance(geo, dict):
        geo = {}

    geography_rejected = _safe_int(geo.get("FOREIGN"))
    geography_unknown = _safe_int(geo.get("UNKNOWN"))

    # For Workday collectors, 'seen' is the deduplicated Belgium listing pool.
    geography_accepted = seen

    detail_ok = _safe_int(local_vars.get("detail_ok"))
    if detail_ok is None and candidates is not None and detail_errors is not None:
        detail_ok = max(0, int(candidates) - int(detail_errors))

    meta_errors = _meta(local_vars).get("errors")
    technical_errors = len(meta_errors) if isinstance(meta_errors, list) else None

    payload = {
        "seen": seen,
        "target_title": candidates,
        "non_target": _pick_non_target(seen, candidates),
        "detail_ok": detail_ok,
        "detail_failed": detail_errors,
        "geography_accepted": geography_accepted,
        "geography_rejected": geography_rejected,
        "geography_unknown": geography_unknown,
        "language_rejected": rejected_language,
        "converted": kept,
        "persisted": None,
        "errors": technical_errors,
        "closed": closed,
    }
    return publish_source_metrics(key, payload)


def clear_source_metrics(source_key: str | None = None):
    if source_key is None:
        _STORE.clear()
    else:
        _STORE.pop(str(source_key).upper(), None)


def get_source_metrics(source_key: str):
    value = _STORE.get(str(source_key or "").upper())
    return deepcopy(value) if value is not None else None
