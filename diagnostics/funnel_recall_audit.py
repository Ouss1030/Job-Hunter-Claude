"""
JOB HUNTER BELGIUM
FUNNEL RECALL AUDIT - VERSION 1.0

But
===
Expliquer précisément pourquoi des milliers d'offres collectées n'aboutissent
pas à des candidatures.

Le script :
1. retrouve le dernier run RAW dans jobs.db ;
2. relit le snapshot INITIAL du run (donc avant enrichissement) ;
3. rescora chaque offre avec le Matcher ACTUEL ;
4. identifie les titres Lab/QC/Chimie/Production/Data à surveiller ;
5. recroise chaque RAW avec le dernier build canonique ;
6. recroise avec le dernier Gate JSON ;
7. reconstruit la Queue avec le module application_queue ACTUEL ;
8. mesure le backlog READY_APPLY jamais préparé ;
9. exporte TXT + JSON + CSV automatiquement.

IMPORTANT
=========
- AUCUNE collecte web.
- AUCUN appel API.
- AUCUNE modification de la DB.
- AUCUNE modification Matcher / Gate / Queue.
- Pas besoin de relancer main.py.

Usage :
    python -m diagnostics.funnel_recall_audit
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from config.funnel_recall import (
    FUNNEL_RECALL_VERSION,
    WATCH_BUCKETS,
    PRODUCTION_CONTEXT_TERMS,
    HIGH_RECALL_BUCKETS,
    MAX_LOST_ITEMS_IN_TXT,
    MAX_BACKLOG_ITEMS_IN_TXT,
)
from database.db import get_connection
from database.models import JobOffer
from matching.basic_matcher import score_job
from matching.application_queue import build_application_queue_from_gate_payload


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Texte / JSON
# ---------------------------------------------------------------------------

def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize(value: Any) -> str:
    text = clean_text(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'").replace("`", "'")
    text = re.sub(r"[^a-z0-9+#./' -]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def safe_json(value: Any, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def latest_file(pattern: str) -> Path | None:
    paths = list(LOG_DIR.glob(pattern))
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def load_json(path: Path | None, default):
    if not path or not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


# ---------------------------------------------------------------------------
# DB introspection
# ---------------------------------------------------------------------------

def table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def table_columns(conn, name: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({name})").fetchall()]


def latest_collection_run_id(conn) -> str | None:
    if table_exists(conn, "collection_runs"):
        cols = table_columns(conn, "collection_runs")
        row = conn.execute(
            "SELECT * FROM collection_runs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if row is not None:
            data = dict(row)
            for key in ("run_id", "id", "collection_run_id"):
                if key in cols and data.get(key) not in (None, ""):
                    return str(data[key])

    # Fallback robuste.
    row = conn.execute(
        """
        SELECT last_run_id, COUNT(*) AS n
        FROM raw_jobs
        WHERE last_run_id IS NOT NULL AND last_run_id <> ''
        GROUP BY last_run_id
        ORDER BY MAX(rowid) DESC
        LIMIT 1
        """
    ).fetchone()
    return str(row["last_run_id"]) if row else None


def load_latest_raw_rows(conn) -> tuple[str | None, list[dict]]:
    run_id = latest_collection_run_id(conn)
    if not run_id:
        return None, []

    raw_cols = table_columns(conn, "raw_jobs")

    # Snapshot initial exact du run lorsque disponible.
    if table_exists(conn, "raw_job_run_items"):
        item_cols = table_columns(conn, "raw_job_run_items")
        needed = {"raw_job_id", "run_id"}
        if needed.issubset(item_cols):
            snapshot_col = (
                "initial_snapshot_json"
                if "initial_snapshot_json" in item_cols
                else ("snapshot_json" if "snapshot_json" in item_cols else None)
            )
            final_col = (
                "final_snapshot_json"
                if "final_snapshot_json" in item_cols
                else None
            )

            select_extra = []
            if snapshot_col:
                select_extra.append(f"ri.{snapshot_col} AS _initial_snapshot_json")
            if final_col:
                select_extra.append(f"ri.{final_col} AS _final_snapshot_json")

            extra_sql = ", " + ", ".join(select_extra) if select_extra else ""

            sql = f"""
                SELECT rj.* {extra_sql}
                FROM raw_jobs AS rj
                JOIN raw_job_run_items AS ri
                  ON ri.raw_job_id = rj.id
                WHERE CAST(ri.run_id AS TEXT) = ?
                ORDER BY rj.id
            """
            rows = [dict(row) for row in conn.execute(sql, (str(run_id),)).fetchall()]
            if rows:
                # Defensive dedup si une DB future contient plusieurs observations.
                dedup = {}
                for row in rows:
                    dedup[row["id"]] = row
                return run_id, list(dedup.values())

    # Fallback via last_run_id.
    rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM raw_jobs WHERE CAST(last_run_id AS TEXT)=? ORDER BY id",
            (str(run_id),),
        ).fetchall()
    ]
    return run_id, rows


# ---------------------------------------------------------------------------
# Reconstruction JobOffer
# ---------------------------------------------------------------------------

def snapshot_for_row(row: dict) -> dict:
    snap = safe_json(row.get("_initial_snapshot_json"), {}) or {}
    if isinstance(snap, dict):
        return snap
    return {}


def pick(snapshot: dict, row: dict, *names, default=""):
    for name in names:
        if snapshot.get(name) not in (None, ""):
            return snapshot.get(name)
    for name in names:
        if row.get(name) not in (None, ""):
            return row.get(name)
    return default


def row_to_job(row: dict) -> JobOffer:
    snap = snapshot_for_row(row)

    job = JobOffer(
        source=clean_text(pick(snap, row, "source")),
        external_id=clean_text(
            pick(snap, row, "external_id", "source_external_id")
        ),
        title=clean_text(pick(snap, row, "title")),
        company=clean_text(pick(snap, row, "company")),
        location=clean_text(pick(snap, row, "location")),
        description=clean_text(pick(snap, row, "description")),
        url=clean_text(pick(snap, row, "url")),
        date_published=clean_text(pick(snap, row, "date_published")),
        contract_type=clean_text(pick(snap, row, "contract_type")),
        language=clean_text(pick(snap, row, "language")),
        salary=clean_text(pick(snap, row, "salary")),
        date_collected=clean_text(pick(snap, row, "date_collected")),
    )

    dynamic = {
        "collection_channel": pick(snap, row, "collection_channel"),
        "origin_source": pick(snap, row, "origin_source"),
        "source_eligibility_status": pick(
            snap, row, "source_eligibility_status", default="ELIGIBLE"
        ),
        "source_eligibility_reason": pick(
            snap, row, "source_eligibility_reason", default=None
        ),
        "degree_requirement": pick(snap, row, "degree_requirement", default=None),
        "experience_requirement": pick(
            snap, row, "experience_requirement", default=None
        ),
        "application_deadline": pick(
            snap, row, "application_deadline", default=None
        ),
        "restriction_text": pick(snap, row, "restriction_text", default=None),
    }
    for name, value in dynamic.items():
        setattr(job, name, value)

    search_terms = (
        snap.get("_search_terms")
        or snap.get("search_terms")
        or safe_json(row.get("search_terms_json"), [])
        or []
    )
    setattr(job, "_search_terms", search_terms)
    return job


# ---------------------------------------------------------------------------
# Watchlist / concepts
# ---------------------------------------------------------------------------

def watch_text(job: JobOffer) -> str:
    return normalize(
        " ".join([
            job.title or "",
            job.company or "",
            job.description or "",
        ])
    )


def title_text(job: JobOffer) -> str:
    return normalize(job.title)


def matched_buckets(job: JobOffer) -> list[str]:
    title = title_text(job)
    body = watch_text(job)
    buckets = []

    for bucket, terms in WATCH_BUCKETS.items():
        matched = False
        for term in terms:
            nterm = normalize(term)
            # Pour les instruments, le terme peut être dans la description.
            haystack = body if bucket == "ANALYTICAL_INSTRUMENTS" else title
            if nterm and nterm in haystack:
                matched = True
                break
        if matched:
            buckets.append(bucket)

    return buckets


def production_context(job: JobOffer) -> bool:
    body = watch_text(job)
    return any(normalize(term) in body for term in PRODUCTION_CONTEXT_TERMS)


def recall_risk(buckets: list[str], core_relevance: bool, prod_context: bool) -> str:
    if core_relevance:
        return "NONE"
    if any(bucket in HIGH_RECALL_BUCKETS for bucket in buckets):
        return "HIGH"
    if "PRODUCTION_ADJACENT" in buckets and prod_context:
        return "HIGH"
    if buckets:
        return "MEDIUM"
    return "NONE"


# ---------------------------------------------------------------------------
# Canonical / Gate / Queue
# ---------------------------------------------------------------------------

def latest_canonical_mapping(conn) -> tuple[Any, dict[int, int]]:
    if not table_exists(conn, "canonical_job_sources"):
        return None, {}

    cols = table_columns(conn, "canonical_job_sources")
    if not {"raw_job_id", "canonical_job_id"}.issubset(cols):
        return None, {}

    build_id = None
    if "build_id" in cols:
        row = conn.execute(
            """
            SELECT build_id
            FROM canonical_job_sources
            ORDER BY rowid DESC
            LIMIT 1
            """
        ).fetchone()
        if row:
            build_id = row["build_id"]

    if build_id is not None and "build_id" in cols:
        rows = conn.execute(
            """
            SELECT raw_job_id, canonical_job_id
            FROM canonical_job_sources
            WHERE build_id=?
            """,
            (build_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT raw_job_id, canonical_job_id FROM canonical_job_sources"
        ).fetchall()

    return build_id, {
        int(row["raw_job_id"]): int(row["canonical_job_id"])
        for row in rows
        if row["raw_job_id"] is not None and row["canonical_job_id"] is not None
    }


def latest_gate_payload() -> tuple[Path | None, list[dict]]:
    path = latest_file("application_gate_v1_*.json")
    payload = load_json(path, [])
    return path, payload if isinstance(payload, list) else []


def rebuild_current_queue(gate_payload: list[dict]) -> list[dict]:
    if not gate_payload:
        return []
    return build_application_queue_from_gate_payload(gate_payload)


def canonical_index(items: list[dict]) -> dict[int, dict]:
    out = {}
    for item in items:
        cid = item.get("canonical_job_id")
        if cid is None:
            continue
        try:
            out[int(cid)] = item
        except Exception:
            pass
    return out


# ---------------------------------------------------------------------------
# Preparation / Recheck coverage
# ---------------------------------------------------------------------------

def latest_preparation_keys() -> tuple[Path | None, set[str]]:
    path = latest_file("application_preparation_v1_*.json")
    payload = load_json(path, [])
    keys = {
        clean_text(x.get("stable_item_key"))
        for x in payload
        if isinstance(x, dict) and clean_text(x.get("stable_item_key"))
    } if isinstance(payload, list) else set()
    return path, keys


def latest_recheck_statuses() -> tuple[Path | None, dict[str, str]]:
    path = latest_file("application_recheck_v1_*.json")
    payload = load_json(path, [])
    statuses = {}
    if isinstance(payload, list):
        for x in payload:
            if not isinstance(x, dict):
                continue
            key = clean_text(x.get("stable_item_key"))
            if key:
                statuses[key] = clean_text(x.get("status"))
    return path, statuses


# ---------------------------------------------------------------------------
# Stage explanation
# ---------------------------------------------------------------------------

def stage_for_record(
    source: str,
    core_relevance: bool,
    canonical_id: int | None,
    gate_item: dict | None,
    queue_item: dict | None,
) -> str:
    if queue_item:
        return "QUEUE_" + clean_text(queue_item.get("queue_status"))
    if gate_item:
        gate = gate_item.get("gate") or {}
        return "GATE_" + clean_text(gate.get("status"))
    if canonical_id is not None:
        return "CANONICAL_NOT_GATED"
    if source == "TRAVAILLERPOUR":
        return "TP_NOT_IN_GATE"
    if core_relevance:
        return "PRESELECTED_NOT_GATED"
    return "PRESELECT_REJECTED"


def loss_reason(
    result: dict,
    stage: str,
    gate_item: dict | None,
    queue_item: dict | None,
) -> str:
    if queue_item:
        qs = clean_text(queue_item.get("queue_status"))
        if qs == "EXCLUDED":
            gate = queue_item.get("gate") or {}
            reasons = gate.get("hard_reasons") or gate.get("reasons") or []
            if reasons:
                return "Gate: " + " | ".join(clean_text(x) for x in reasons[:3])
        if qs == "HOLD_DUPLICATE":
            return (
                "Doublon candidature probable"
                + (
                    f" de {queue_item.get('duplicate_of')}"
                    if queue_item.get("duplicate_of")
                    else ""
                )
            )
        return "Offre présente dans la Queue"

    if gate_item:
        gate = gate_item.get("gate") or {}
        reasons = gate.get("hard_reasons") or gate.get("reasons") or []
        return " | ".join(clean_text(x) for x in reasons[:3]) or stage

    if stage == "PRESELECT_REJECTED":
        reasons = result.get("reasons") or []
        return " | ".join(clean_text(x) for x in reasons[:3]) or "Aucun signal métier suffisant"

    if stage == "PRESELECTED_NOT_GATED":
        return "Pré-sélection positive mais aucune présence dans le Gate : à auditer"

    if stage == "CANONICAL_NOT_GATED":
        return "Présent dans le build canonique mais absent du Gate/scoring final"

    return stage


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def run_audit() -> dict:
    conn = get_connection()
    # sqlite Row mapping même si get_connection() ne l'active pas.
    try:
        conn.row_factory = sqlite3.Row
    except Exception:
        pass

    run_id, raw_rows = load_latest_raw_rows(conn)
    build_id, raw_to_canonical = latest_canonical_mapping(conn)

    gate_path, gate_payload = latest_gate_payload()
    queue_payload = rebuild_current_queue(gate_payload)
    gate_by_can = canonical_index(gate_payload)
    queue_by_can = canonical_index(queue_payload)

    prep_path, prepared_keys = latest_preparation_keys()
    recheck_path, recheck_statuses = latest_recheck_statuses()

    queue_ready_apply = [
        x for x in queue_payload if x.get("queue_status") == "READY_APPLY"
    ]
    ready_apply_unprepared = [
        x for x in queue_ready_apply
        if clean_text(x.get("stable_item_key")) not in prepared_keys
    ]

    rows = []
    all_score_counts = Counter()
    bucket_stats = defaultdict(Counter)
    source_stats = defaultdict(Counter)

    for index, row in enumerate(raw_rows, start=1):
        job = row_to_job(row)
        try:
            result = score_job(job)
        except Exception as exc:
            result = {
                "score": 0.0,
                "core_relevance": False,
                "best_family": "ERROR",
                "reasons": [f"Erreur score: {type(exc).__name__}: {exc}"],
                "confidence_level": "UNKNOWN",
                "provisional": True,
            }

        source = clean_text(job.source).upper()
        core = bool(result.get("core_relevance"))
        score = float(result.get("score") or 0)
        buckets = matched_buckets(job)
        prod_ctx = production_context(job)
        risk = recall_risk(buckets, core, prod_ctx)

        raw_id = int(row["id"])
        canonical_id = raw_to_canonical.get(raw_id)
        gate_item = gate_by_can.get(canonical_id) if canonical_id is not None else None
        queue_item = queue_by_can.get(canonical_id) if canonical_id is not None else None
        stage = stage_for_record(source, core, canonical_id, gate_item, queue_item)
        why = loss_reason(result, stage, gate_item, queue_item)

        detail_success = bool(row.get("detail_enrichment_success"))
        enriched_text_len = int(row.get("detail_matching_text_length") or 0)

        all_score_counts["raw"] += 1
        if source == "TRAVAILLERPOUR":
            all_score_counts["travaillerpour"] += 1
        else:
            all_score_counts["standard"] += 1
            if core:
                all_score_counts["standard_core_relevant"] += 1
            else:
                all_score_counts["standard_preselect_rejected"] += 1

        if buckets:
            all_score_counts["watchlist"] += 1
            if core:
                all_score_counts["watchlist_core_relevant"] += 1
            if risk == "HIGH":
                all_score_counts["watchlist_high_recall_risk"] += 1

        for bucket in buckets:
            bucket_stats[bucket]["raw"] += 1
            if core:
                bucket_stats[bucket]["core_relevant"] += 1
            else:
                bucket_stats[bucket]["preselect_rejected"] += 1
            if risk == "HIGH":
                bucket_stats[bucket]["high_recall_risk"] += 1
            if queue_item:
                bucket_stats[bucket][
                    "queue_" + clean_text(queue_item.get("queue_status"))
                ] += 1

        source_stats[source]["raw"] += 1
        if buckets:
            source_stats[source]["watchlist"] += 1
        if core:
            source_stats[source]["core_relevant"] += 1
        if risk == "HIGH":
            source_stats[source]["high_recall_risk"] += 1

        rows.append({
            "raw_job_id": raw_id,
            "run_id": str(run_id),
            "source": source,
            "collection_channel": clean_text(
                getattr(job, "collection_channel", "")
            ),
            "origin_source": clean_text(getattr(job, "origin_source", "")),
            "external_id": clean_text(job.external_id),
            "title": clean_text(job.title),
            "company": clean_text(job.company),
            "location": clean_text(job.location),
            "url": clean_text(job.url),
            "watch_buckets": buckets,
            "production_context": prod_ctx,
            "watchlist": bool(buckets),
            "recall_risk": risk,
            "matcher_core_relevance": core,
            "matcher_score": score,
            "matcher_family": clean_text(result.get("best_family")),
            "matcher_confidence": clean_text(result.get("confidence_level")),
            "matcher_provisional": bool(result.get("provisional")),
            "matcher_reasons": result.get("reasons") or [],
            "detail_enrichment_success": detail_success,
            "detail_matching_text_length": enriched_text_len,
            "canonical_job_id": canonical_id,
            "gate_status": clean_text(
                ((gate_item or {}).get("gate") or {}).get("status")
            ),
            "queue_status": clean_text((queue_item or {}).get("queue_status")),
            "stable_item_key": clean_text((queue_item or {}).get("stable_item_key")),
            "stage": stage,
            "stage_reason": why,
            "prepared": (
                clean_text((queue_item or {}).get("stable_item_key"))
                in prepared_keys
                if queue_item else False
            ),
            "latest_recheck_status": (
                recheck_statuses.get(
                    clean_text((queue_item or {}).get("stable_item_key")),
                    "",
                )
                if queue_item else ""
            ),
        })

    # RAW watchlist perdue AVANT détail.
    lost_recall = [
        x for x in rows
        if x["watchlist"]
        and not x["matcher_core_relevance"]
    ]
    lost_recall.sort(
        key=lambda x: (
            0 if x["recall_risk"] == "HIGH" else 1,
            -x["matcher_score"],
            x["title"].lower(),
        )
    )

    high_risk = [x for x in lost_recall if x["recall_risk"] == "HIGH"]

    # Opportunités déjà bonnes mais jamais préparées.
    backlog = []
    for item in sorted(
        ready_apply_unprepared,
        key=lambda x: int(x.get("queue_rank") or 999999),
    ):
        backlog.append({
            "queue_rank": item.get("queue_rank"),
            "queue_score": item.get("queue_score"),
            "match_score": item.get("match_score"),
            "stable_item_key": item.get("stable_item_key"),
            "canonical_job_id": item.get("canonical_job_id"),
            "title": item.get("title"),
            "company": item.get("company"),
            "location": item.get("location"),
            "source": item.get("source"),
            "best_family": item.get("best_family"),
            "cv_track": item.get("cv_track"),
            "preferred_location": bool(item.get("preferred_location")),
            "url": item.get("url"),
        })

    return {
        "audit_version": FUNNEL_RECALL_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "inputs": {
            "latest_run_id": run_id,
            "canonical_build_id": build_id,
            "gate_json": str(gate_path) if gate_path else None,
            "preparation_json": str(prep_path) if prep_path else None,
            "recheck_json": str(recheck_path) if recheck_path else None,
        },
        "global": dict(all_score_counts),
        "queue": {
            "total": len(queue_payload),
            "READY_APPLY": sum(
                1 for x in queue_payload if x.get("queue_status") == "READY_APPLY"
            ),
            "READY_STRETCH": sum(
                1 for x in queue_payload if x.get("queue_status") == "READY_STRETCH"
            ),
            "VERIFY_FIRST": sum(
                1 for x in queue_payload if x.get("queue_status") == "VERIFY_FIRST"
            ),
            "HOLD_DUPLICATE": sum(
                1 for x in queue_payload if x.get("queue_status") == "HOLD_DUPLICATE"
            ),
            "EXCLUDED": sum(
                1 for x in queue_payload if x.get("queue_status") == "EXCLUDED"
            ),
            "ready_apply_prepared": len(queue_ready_apply) - len(ready_apply_unprepared),
            "ready_apply_unprepared": len(ready_apply_unprepared),
        },
        "bucket_stats": {
            bucket: dict(counter)
            for bucket, counter in sorted(bucket_stats.items())
        },
        "source_stats": {
            source: dict(counter)
            for source, counter in sorted(source_stats.items())
        },
        "high_recall_risk_count": len(high_risk),
        "high_recall_risk_items": high_risk,
        "lost_watchlist_items": lost_recall,
        "ready_apply_backlog": backlog,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

CSV_FIELDS = [
    "raw_job_id", "run_id", "source", "origin_source", "external_id",
    "title", "company", "location", "watch_buckets", "recall_risk",
    "matcher_core_relevance", "matcher_score", "matcher_family",
    "detail_enrichment_success", "canonical_job_id",
    "gate_status", "queue_status", "stable_item_key", "stage",
    "stage_reason", "prepared", "latest_recheck_status", "url",
]


def export_audit(audit: dict) -> tuple[Path, Path, Path]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt_path = LOG_DIR / f"funnel_recall_audit_v1_{stamp}.txt"
    json_path = LOG_DIR / f"funnel_recall_audit_v1_{stamp}.json"
    csv_path = LOG_DIR / f"funnel_recall_audit_v1_{stamp}.csv"

    json_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in audit["rows"]:
            exported = dict(row)
            exported["watch_buckets"] = "|".join(row.get("watch_buckets") or [])
            writer.writerow({k: exported.get(k, "") for k in CSV_FIELDS})

    g = audit["global"]
    q = audit["queue"]

    raw = int(g.get("raw", 0))
    std = int(g.get("standard", 0))
    core = int(g.get("standard_core_relevant", 0))
    watch = int(g.get("watchlist", 0))
    watch_core = int(g.get("watchlist_core_relevant", 0))
    risk = int(audit.get("high_recall_risk_count", 0))

    def pct(a, b):
        return (100.0 * a / b) if b else 0.0

    lines = [
        "FUNNEL RECALL AUDIT V1",
        "=" * 88,
        f"Run RAW analysé            : {audit['inputs'].get('latest_run_id')}",
        f"Build canonique            : {audit['inputs'].get('canonical_build_id')}",
        "",
        "1) FUNNEL GLOBAL",
        "-" * 88,
        f"RAW observées              : {raw}",
        f"Standard (hors TP)         : {std}",
        f"Pré-sélection métier       : {core} / {std} ({pct(core, std):.1f}%)",
        f"Écartées avant détail      : {std-core}",
        "",
        f"Watchlist métier           : {watch}",
        f"Watchlist pré-sélectionnée : {watch_core} / {watch} ({pct(watch_core, watch):.1f}%)",
        f"⚠️ Recall HIGH à examiner   : {risk}",
        "",
        "2) QUEUE ACTUELLE RECONSTRUITE AVEC LE MODULE INSTALLÉ",
        "-" * 88,
        f"READY_APPLY                : {q['READY_APPLY']}",
        f"READY_STRETCH              : {q['READY_STRETCH']}",
        f"VERIFY_FIRST               : {q['VERIFY_FIRST']}",
        f"HOLD_DUPLICATE             : {q['HOLD_DUPLICATE']}",
        f"EXCLUDED                   : {q['EXCLUDED']}",
        "",
        f"READY_APPLY déjà préparées : {q['ready_apply_prepared']}",
        f"🔥 READY_APPLY NON PRÉPARÉES: {q['ready_apply_unprepared']}",
        "",
        "3) WATCHLIST PAR FAMILLE",
        "-" * 88,
    ]

    for bucket, stats in audit["bucket_stats"].items():
        lines.append(
            f"{bucket:<24} RAW {stats.get('raw',0):>4} | "
            f"PRESELECT {stats.get('core_relevant',0):>4} | "
            f"DROP {stats.get('preselect_rejected',0):>4} | "
            f"RISK HIGH {stats.get('high_recall_risk',0):>4} | "
            f"READY {stats.get('queue_READY_APPLY',0):>3} | "
            f"STRETCH {stats.get('queue_READY_STRETCH',0):>3}"
        )

    lines.extend([
        "",
        "4) PAR SOURCE",
        "-" * 88,
    ])
    for source, stats in audit["source_stats"].items():
        lines.append(
            f"{source:<20} RAW {stats.get('raw',0):>5} | "
            f"WATCH {stats.get('watchlist',0):>4} | "
            f"CORE {stats.get('core_relevant',0):>4} | "
            f"RISK HIGH {stats.get('high_recall_risk',0):>4}"
        )

    lines.extend([
        "",
        "5) BACKLOG IMMÉDIAT : READY_APPLY JAMAIS PRÉPARÉES",
        "-" * 88,
    ])
    backlog = audit.get("ready_apply_backlog") or []
    if not backlog:
        lines.append("Aucun backlog READY_APPLY.")
    else:
        for item in backlog[:MAX_BACKLOG_ITEMS_IN_TXT]:
            star = "⭐" if item.get("preferred_location") else " "
            lines.extend([
                f"{int(item.get('queue_rank') or 0):>3}. {star} "
                f"Q{float(item.get('queue_score') or 0):>5.1f} | "
                f"M{float(item.get('match_score') or 0):>5.1f} | "
                f"{clean_text(item.get('cv_track')):<7} | "
                f"{clean_text(item.get('title'))}",
                f"     {clean_text(item.get('company'))} | {clean_text(item.get('location'))}",
                f"     {clean_text(item.get('url'))}",
            ])

    lines.extend([
        "",
        "6) ALERTES RECALL : TITRES INTÉRESSANTS ÉCARTÉS AVANT DÉTAIL",
        "-" * 88,
        "Ces lignes sont des CANDIDATS À AUDITER, pas des offres automatiquement bonnes.",
        "",
    ])

    lost = audit.get("lost_watchlist_items") or []
    if not lost:
        lines.append("Aucune watchlist écartée avant détail.")
    else:
        for item in lost[:MAX_LOST_ITEMS_IN_TXT]:
            icon = "🔥" if item.get("recall_risk") == "HIGH" else "⚠️"
            buckets = ",".join(item.get("watch_buckets") or [])
            lines.extend([
                f"{icon} {item.get('recall_risk'):<6} | "
                f"{item.get('source'):<14} | "
                f"S{float(item.get('matcher_score') or 0):>5.1f} | "
                f"{buckets}",
                f"   {item.get('title')}",
                f"   {item.get('company')} | {item.get('location')}",
                f"   Famille matcher : {item.get('matcher_family')}",
                f"   Raison           : {item.get('stage_reason')}",
                f"   {item.get('url')}",
                "",
            ])

    lines.extend([
        "",
        "7) LECTURE DU RAPPORT",
        "-" * 88,
        "A. READY_APPLY NON PRÉPARÉES > 0",
        "   => problème d'exploitation du backlog, PAS du Matcher.",
        "",
        "B. RISK HIGH nombreux dans PRESELECT_REJECTED",
        "   => le Matcher manque probablement des métiers pertinents ;",
        "      on corrige seulement les familles/règles réellement concernées.",
        "",
        "C. Beaucoup de READY_STRETCH proches du profil",
        "   => on peut élargir le batch après revue des raisons Gate.",
        "",
        "D. Les nouvelles sources futures seront comparables avec les mêmes",
        "   colonnes source/origin_source et le même funnel.",
        "",
        f"JSON complet : {json_path}",
        f"CSV complet  : {csv_path}",
    ])

    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return txt_path, json_path, csv_path


def main():
    audit = run_audit()
    txt_path, json_path, csv_path = export_audit(audit)

    print()
    print("=" * 88)
    print("FUNNEL RECALL AUDIT V1")
    print("=" * 88)
    print("RAW                :", audit["global"].get("raw", 0))
    print("Watchlist          :", audit["global"].get("watchlist", 0))
    print("Recall HIGH        :", audit["high_recall_risk_count"])
    print("READY_APPLY        :", audit["queue"]["READY_APPLY"])
    print("READY non préparés :", audit["queue"]["ready_apply_unprepared"])
    print()
    print("TXT  :", txt_path)
    print("JSON :", json_path)
    print("CSV  :", csv_path)


if __name__ == "__main__":
    main()
