from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = ROOT / "database" / "user_feedback.db"
DB_PATH = Path(os.environ.get("JOBHUNTER_FEEDBACK_DB", str(_DEFAULT_DB)))

FEEDBACK_VERSION = "1.0"

VERDICTS = ["MATCH", "REVIEW", "NO_MATCH"]
VERDICT_LABELS = {
    "MATCH": "👍 Correspond",
    "REVIEW": "🤔 À revoir",
    "NO_MATCH": "👎 Ne correspond pas",
}
REASONS = [
    "Score trop élevé",
    "Score trop faible",
    "Métier / missions",
    "Langue",
    "Expérience",
    "Diplôme",
    "Seniorité",
    "Localisation",
    "Salaire",
    "Horaires / shifts",
    "Contrat",
    "Description insuffisante",
    "Autre",
]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def ensure_schema() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS job_feedback (
                feedback_key TEXT PRIMARY KEY,
                stable_item_key TEXT,
                canonical_job_id TEXT,
                url TEXT,
                title TEXT,
                company TEXT,
                source TEXT,
                verdict TEXT NOT NULL,
                user_score REAL,
                auto_score_at_rating REAL,
                note TEXT NOT NULL DEFAULT '',
                reasons_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (verdict IN ('MATCH','REVIEW','NO_MATCH')),
                CHECK (user_score IS NULL OR (user_score >= 0 AND user_score <= 100))
            );

            CREATE INDEX IF NOT EXISTS idx_feedback_stable
                ON job_feedback(stable_item_key);
            CREATE INDEX IF NOT EXISTS idx_feedback_url
                ON job_feedback(url);
            CREATE INDEX IF NOT EXISTS idx_feedback_canonical
                ON job_feedback(canonical_job_id);
            CREATE INDEX IF NOT EXISTS idx_feedback_verdict
                ON job_feedback(verdict);
            """
        )


def _identity_candidates(job: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    stable = str(job.get("stable_item_key") or "").strip()
    url = str(job.get("url") or "").strip()
    canonical = str(job.get("canonical_job_id") or "").strip()
    if stable:
        keys.append(f"stable:{stable}")
    if url:
        keys.append(f"url:{url}")
    if canonical:
        keys.append(f"canonical:{canonical}")
    return keys


def _preferred_key(job: dict[str, Any]) -> str:
    keys = _identity_candidates(job)
    if not keys:
        title = str(job.get("title") or "unknown").strip()
        company = str(job.get("company") or "unknown").strip()
        return f"fallback:{company}|{title}"
    return keys[0]


def automatic_score(job: dict[str, Any]) -> float | None:
    candidates = [
        job.get("display_score"),
        job.get("final_score_v12"),
        job.get("final_score"),
        job.get("queue_score"),
        job.get("match_score"),
    ]
    for value in candidates:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    try:
        item["reasons"] = json.loads(item.pop("reasons_json") or "[]")
    except Exception:
        item["reasons"] = []
    auto = item.get("auto_score_at_rating")
    user = item.get("user_score")
    item["score_gap"] = (
        round(float(auto) - float(user), 1)
        if auto is not None and user is not None
        else None
    )
    item["verdict_label"] = VERDICT_LABELS.get(item.get("verdict"), item.get("verdict"))
    return item


def get_feedback(job: dict[str, Any]) -> dict[str, Any] | None:
    ensure_schema()
    keys = _identity_candidates(job)
    stable = str(job.get("stable_item_key") or "").strip()
    url = str(job.get("url") or "").strip()
    canonical = str(job.get("canonical_job_id") or "").strip()

    with connect() as conn:
        if keys:
            placeholders = ",".join("?" for _ in keys)
            row = conn.execute(
                f"""
                SELECT * FROM job_feedback
                WHERE feedback_key IN ({placeholders})
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                tuple(keys),
            ).fetchone()
            if row:
                return _row_to_dict(row)

        clauses, params = [], []
        if stable:
            clauses.append("stable_item_key = ?")
            params.append(stable)
        if url:
            clauses.append("url = ?")
            params.append(url)
        if canonical:
            clauses.append("canonical_job_id = ?")
            params.append(canonical)
        if clauses:
            row = conn.execute(
                f"""
                SELECT * FROM job_feedback
                WHERE {' OR '.join(clauses)}
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
            return _row_to_dict(row)
    return None


def save_feedback(
    job: dict[str, Any],
    verdict: str,
    user_score: float | None = None,
    note: str = "",
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    ensure_schema()
    if verdict not in VERDICTS:
        raise ValueError(f"Verdict invalide: {verdict}")
    if user_score is not None:
        user_score = float(user_score)
        if not 0 <= user_score <= 100:
            raise ValueError("Le score personnel doit être compris entre 0 et 100.")

    existing = get_feedback(job)
    feedback_key = existing["feedback_key"] if existing else _preferred_key(job)
    created_at = existing["created_at"] if existing else _now()
    updated_at = _now()

    stable = str(job.get("stable_item_key") or "").strip() or None
    canonical = str(job.get("canonical_job_id") or "").strip() or None
    url = str(job.get("url") or "").strip() or None
    title = str(job.get("title") or "").strip() or None
    company = str(job.get("company") or "").strip() or None
    source = str(job.get("source") or "").strip() or None
    auto_score = automatic_score(job)
    reasons = [r for r in (reasons or []) if r in REASONS]

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO job_feedback (
                feedback_key, stable_item_key, canonical_job_id, url,
                title, company, source, verdict, user_score,
                auto_score_at_rating, note, reasons_json,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(feedback_key) DO UPDATE SET
                stable_item_key=excluded.stable_item_key,
                canonical_job_id=excluded.canonical_job_id,
                url=excluded.url,
                title=excluded.title,
                company=excluded.company,
                source=excluded.source,
                verdict=excluded.verdict,
                user_score=excluded.user_score,
                auto_score_at_rating=excluded.auto_score_at_rating,
                note=excluded.note,
                reasons_json=excluded.reasons_json,
                updated_at=excluded.updated_at
            """,
            (
                feedback_key, stable, canonical, url, title, company, source,
                verdict, user_score, auto_score, note.strip(),
                json.dumps(reasons, ensure_ascii=False),
                created_at, updated_at,
            ),
        )
    saved = get_feedback(job)
    if saved is None:
        raise RuntimeError("Le feedback n'a pas pu être relu après enregistrement.")
    return saved


def delete_feedback(job: dict[str, Any]) -> int:
    ensure_schema()
    keys = _identity_candidates(job)
    existing = get_feedback(job)
    if existing and existing.get("feedback_key"):
        keys.append(existing["feedback_key"])
    keys = list(dict.fromkeys(keys))
    if not keys:
        return 0
    placeholders = ",".join("?" for _ in keys)
    with connect() as conn:
        cur = conn.execute(
            f"DELETE FROM job_feedback WHERE feedback_key IN ({placeholders})",
            tuple(keys),
        )
        return int(cur.rowcount or 0)


def decorate_feedback(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM job_feedback ORDER BY updated_at DESC").fetchall()

    by_key: dict[str, dict[str, Any]] = {}
    by_stable: dict[str, dict[str, Any]] = {}
    by_url: dict[str, dict[str, Any]] = {}
    by_canonical: dict[str, dict[str, Any]] = {}

    for raw in rows:
        fb = _row_to_dict(raw)
        if not fb:
            continue
        by_key[fb["feedback_key"]] = fb
        if fb.get("stable_item_key"):
            by_stable.setdefault(str(fb["stable_item_key"]), fb)
        if fb.get("url"):
            by_url.setdefault(str(fb["url"]), fb)
        if fb.get("canonical_job_id"):
            by_canonical.setdefault(str(fb["canonical_job_id"]), fb)

    out: list[dict[str, Any]] = []
    for raw in items:
        job = dict(raw)
        fb = None
        for key in _identity_candidates(job):
            if key in by_key:
                fb = by_key[key]
                break
        if fb is None and job.get("stable_item_key"):
            fb = by_stable.get(str(job["stable_item_key"]))
        if fb is None and job.get("url"):
            fb = by_url.get(str(job["url"]))
        if fb is None and job.get("canonical_job_id") is not None:
            fb = by_canonical.get(str(job["canonical_job_id"]))

        auto = automatic_score(job)
        if fb:
            job["feedback_verdict"] = fb.get("verdict")
            job["feedback_label"] = fb.get("verdict_label")
            job["user_score"] = fb.get("user_score")
            job["feedback_note"] = fb.get("note") or ""
            job["feedback_reasons"] = fb.get("reasons") or []
            job["feedback_updated_at"] = fb.get("updated_at")
            job["score_gap"] = (
                round(auto - float(fb["user_score"]), 1)
                if auto is not None and fb.get("user_score") is not None
                else None
            )
        else:
            job["feedback_verdict"] = None
            job["feedback_label"] = "—"
            job["user_score"] = None
            job["feedback_note"] = ""
            job["feedback_reasons"] = []
            job["feedback_updated_at"] = None
            job["score_gap"] = None
        out.append(job)
    return out


def feedback_rows() -> list[dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM job_feedback ORDER BY updated_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows if r is not None]


def feedback_summary(contested_threshold: float = 15.0) -> dict[str, int]:
    rows = feedback_rows()
    summary = {
        "total": len(rows),
        "match": 0,
        "review": 0,
        "no_match": 0,
        "contested": 0,
    }
    for row in rows:
        verdict = row.get("verdict")
        if verdict == "MATCH":
            summary["match"] += 1
        elif verdict == "REVIEW":
            summary["review"] += 1
        elif verdict == "NO_MATCH":
            summary["no_match"] += 1
        gap = row.get("score_gap")
        if gap is not None and abs(float(gap)) >= contested_threshold:
            summary["contested"] += 1
    return summary


# Create the tiny feedback DB lazily and safely when the module is imported.
ensure_schema()
