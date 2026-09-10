from __future__ import annotations

import json
import os
import time
from pathlib import Path

from sources.forem import (
    FOREM_TARGET_SEARCH_TERMS,
    keyword_cache_path,
    load_keyword_cache,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "forem_scheduler.json"
STATE_PATH = PROJECT_ROOT / "logs" / "forem_scheduler_state.json"

DEFAULT_CACHE_CARRY_DAYS = 8


def _read_json(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def _write_json(path: Path, payload: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)
        return True
    except Exception as exc:
        print("⚠️ FOREM SCHEDULER state write failed:", exc)
        return False


def _config():
    return _read_json(CONFIG_PATH, {})


def _state():
    return _read_json(
        STATE_PATH,
        {
            "version": 1,
            "rotation_cursor": 0,
            "last_full_sweep_epoch": 0.0,
        },
    )


def get_forem_scheduler_plan(now_epoch=None, profile_override=None):
    config = _config()
    state = _state()
    all_terms = list(FOREM_TARGET_SEARCH_TERMS)

    now_epoch = float(now_epoch if now_epoch is not None else time.time())

    override = str(
        profile_override
        or os.environ.get("JOBHUNTER_FOREM_PROFILE", "")
    ).strip().lower()

    enabled = bool(config.get("enabled", False))
    requested = override if override in {"legacy", "full", "core", "adaptive"} else None

    if requested is None:
        requested = (
            str(config.get("mode", "adaptive") or "adaptive").strip().lower()
            if enabled
            else "legacy"
        )

    core = [str(x).strip() for x in (config.get("core_terms") or []) if str(x).strip()]
    secondary = [
        str(x).strip()
        for x in (config.get("secondary_terms") or [])
        if str(x).strip()
    ]

    # Fail closed to historical behavior if config does not cover the whole bank.
    if set(core + secondary) != set(all_terms):
        requested = "legacy"
        core = list(all_terms)
        secondary = []

    try:
        buckets = max(1, int(config.get("rotation_buckets", 4) or 4))
    except Exception:
        buckets = 4

    try:
        cursor = int(state.get("rotation_cursor", 0) or 0)
    except Exception:
        cursor = 0

    try:
        interval_days = max(1.0, float(config.get("full_sweep_interval_days", 7) or 7))
    except Exception:
        interval_days = 7.0

    try:
        last_full = float(state.get("last_full_sweep_epoch", 0.0) or 0.0)
    except Exception:
        last_full = 0.0

    full_due = (
        last_full <= 0.0
        or now_epoch - last_full >= interval_days * 86400.0
    )

    bucket = cursor % buckets

    if requested in {"legacy", "full"}:
        profile = "LEGACY" if requested == "legacy" else "FULL"
        live_terms = list(all_terms)
        cache_only = []
    elif requested == "core":
        profile = "CORE"
        live_terms = list(core)
        cache_only = [t for t in all_terms if t not in set(live_terms)]
    elif full_due:
        profile = "FULL"
        live_terms = list(all_terms)
        cache_only = []
    else:
        selected_secondary = [
            term
            for index, term in enumerate(secondary)
            if index % buckets == bucket
        ]
        live_terms = list(dict.fromkeys(core + selected_secondary))
        live_set = set(live_terms)
        cache_only = [term for term in all_terms if term not in live_set]
        profile = "ADAPTIVE"

    return {
        "version": 1,
        "profile": profile,
        "requested": requested,
        "live_terms": live_terms,
        "cache_only_terms": cache_only,
        "core_count": len(core),
        "secondary_count": len(secondary),
        "rotation_buckets": buckets,
        "rotation_bucket": bucket,
        "bucket_label": f"{bucket + 1}/{buckets}",
        "full_due": bool(full_due),
        "now_epoch": now_epoch,
    }


def _cache_is_recent(keyword: str, max_age_days: float) -> bool:
    path = keyword_cache_path(keyword)
    if not path.exists():
        return False
    try:
        age = time.time() - path.stat().st_mtime
        return age <= max(1.0, float(max_age_days)) * 86400.0
    except Exception:
        return False


def merge_cached_forem_results(
    live_jobs,
    cache_only_terms,
    max_age_days=DEFAULT_CACHE_CARRY_DAYS,
):
    unique = {}

    def merge_row(row, term=None):
        if not isinstance(row, dict):
            return
        external_id = str(row.get("numerooffreforem") or "").strip()
        if not external_id:
            return

        annotated = dict(row)
        terms = set(annotated.get("_search_terms") or [])
        if term:
            terms.add(term)
        annotated["_search_terms"] = sorted(terms)

        if external_id not in unique:
            unique[external_id] = annotated
        else:
            existing = unique[external_id]
            existing_terms = set(existing.get("_search_terms") or [])
            existing_terms.update(annotated.get("_search_terms") or [])
            existing["_search_terms"] = sorted(existing_terms)

    for row in list(live_jobs or []):
        merge_row(row)

    cache_terms_loaded = 0
    cache_rows_loaded = 0

    for term in list(cache_only_terms or []):
        if not _cache_is_recent(term, max_age_days):
            continue

        rows = load_keyword_cache(term)
        if rows is None:
            continue

        cache_terms_loaded += 1
        cache_rows_loaded += len(rows)

        for row in rows:
            merge_row(row, term=term)

    jobs = list(unique.values())
    jobs.sort(
        key=lambda row: row.get("datedebutdiffusion") or "",
        reverse=True,
    )

    return jobs, {
        "cache_terms_loaded": cache_terms_loaded,
        "cache_rows_loaded": cache_rows_loaded,
        "unique_total": len(jobs),
    }


def mark_forem_scheduler_success(plan: dict) -> bool:
    state = _state()
    now_epoch = float(plan.get("now_epoch") or time.time())

    if plan.get("profile") == "FULL":
        state["last_full_sweep_epoch"] = now_epoch

    if plan.get("profile") == "ADAPTIVE":
        state["rotation_cursor"] = int(state.get("rotation_cursor", 0) or 0) + 1

    state["version"] = 1
    state["last_success_epoch"] = now_epoch
    state["last_success_profile"] = str(plan.get("profile") or "")
    state["last_rotation_bucket"] = int(plan.get("rotation_bucket") or 0)

    return _write_json(STATE_PATH, state)


# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1_1_CV_POOL
from sources.unified_discovery import get_source_query_terms as _ud11_query_terms
from sources.unified_discovery import get_master_search_terms as _ud11_master_terms

_ud11_original_get_forem_scheduler_plan = get_forem_scheduler_plan

def get_forem_scheduler_plan(*args, **kwargs):
    plan = dict(_ud11_original_get_forem_scheduler_plan(*args, **kwargs))
    legacy_live = list(plan.get("live_terms") or [])
    active = _ud11_query_terms(
        "FOREM",
        legacy_live,
        rotation_buckets=4,
    )
    master = list(_ud11_master_terms())
    active_keys = {" ".join(str(x).casefold().split()) for x in active}
    plan["live_terms"] = active
    plan["cache_only_terms"] = [
        term
        for term in master
        if " ".join(str(term).casefold().split()) not in active_keys
    ]
    plan["master_term_count"] = len(master)
    plan["master_active_count"] = len(active)
    plan["master_pool_enabled"] = True
    return plan
