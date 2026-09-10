from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "database" / "jobs.db"
LOG_DIR = ROOT / "exports" / "logs"
DAILY_DIR = LOG_DIR / "daily_runs"


def connect(readonly: bool = True) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{DB_PATH.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
    else:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _parse_stamp_from_name(path: Path) -> datetime:
    # Cherche un suffixe YYYYMMDD_HHMMSS dans le nom.
    parts = path.stem.split("_")
    for i in range(len(parts) - 1):
        candidate = f"{parts[i]}_{parts[i + 1]}"
        try:
            return datetime.strptime(candidate, "%Y%m%d_%H%M%S")
        except ValueError:
            continue
    return datetime.fromtimestamp(path.stat().st_mtime)


def _latest_matching(patterns: list[str]) -> Path | None:
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(LOG_DIR.glob(pattern))
    candidates = [p for p in candidates if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=_parse_stamp_from_name)


def load_latest_queue() -> tuple[list[dict[str, Any]], Path | None]:
    # On préfère les vrais artefacts pipeline aux replay diagnostics.
    path = _latest_matching(["application_queue_v1_20*.json"])
    if path is None:
        path = _latest_matching(["application_queue_*.json"])
    if path is None:
        return [], None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data, path
    except Exception:
        pass
    return [], path


def load_latest_final_pool() -> tuple[list[dict[str, Any]], dict[str, Any], Path | None]:
    paths = list(LOG_DIR.glob("final_application_pool_v*.json"))
    if not paths:
        return [], {}, None

    best: tuple[datetime, Path, dict[str, Any]] | None = None
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            generated = payload.get("generated_at")
            stamp = datetime.fromisoformat(generated) if generated else _parse_stamp_from_name(path)
            if best is None or stamp > best[0]:
                best = (stamp, path, payload)
        except Exception:
            continue

    if best is None:
        return [], {}, None
    payload = best[2]
    return payload.get("pool", []) or [], payload, best[1]


def latest_build_id(conn: sqlite3.Connection | None = None) -> str | None:
    own = conn is None
    conn = conn or connect()
    try:
        row = conn.execute(
            """
            SELECT build_id
            FROM canonical_builds
            WHERE status = 'COMPLETED'
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()
        return row["build_id"] if row else None
    finally:
        if own:
            conn.close()


def dashboard_metrics() -> dict[str, Any]:
    queue, _ = load_latest_queue()
    pool, pool_payload, _ = load_latest_final_pool()

    with connect() as conn:
        latest_run = conn.execute(
            """
            SELECT *
            FROM collection_runs
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()

        build_id = latest_build_id(conn)
        canonical_count = 0
        if build_id:
            canonical_count = conn.execute(
                "SELECT COUNT(*) FROM canonical_jobs WHERE build_id = ?",
                (build_id,),
            ).fetchone()[0]

        status_counts = {
            row["current_status"] or "UNKNOWN": row["n"]
            for row in conn.execute(
                """
                SELECT current_status, COUNT(*) AS n
                FROM application_current_state
                GROUP BY current_status
                """
            )
        }

    return {
        "latest_collection": dict(latest_run) if latest_run else None,
        "canonical_count": canonical_count,
        "queue_count": len(queue),
        "pool_count": len(pool),
        "pool_summary": pool_payload.get("summary", {}),
        "status_counts": status_counts,
    }


def source_metrics() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                collection_channel AS source,
                COUNT(*) AS total_historique,
                SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS actives,
                MAX(last_seen) AS derniere_vue
            FROM raw_jobs
            GROUP BY collection_channel
            ORDER BY actives DESC, source
            """
        ).fetchall()
    return [dict(row) for row in rows]


def collection_history(limit: int = 30) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                run_id,
                started_at,
                finished_at,
                status,
                total_collected,
                inserted_count,
                updated_count,
                error_count,
                notes
            FROM collection_runs
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def tracking_maps() -> tuple[dict[str, str], dict[str, str], dict[str, bool], dict[str, bool]]:
    """Statut courant + vérité historique "a déjà postulé", par clé et URL."""
    status_by_key: dict[str, str] = {}
    status_by_url: dict[str, str] = {}
    applied_by_key: dict[str, bool] = {}
    applied_by_url: dict[str, bool] = {}
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT
                s.entity_id,
                s.current_status,
                a.identity_type,
                a.identity_value,
                EXISTS(
                    SELECT 1
                    FROM application_events AS ev
                    WHERE ev.entity_id = s.entity_id
                      AND ev.event_type = 'STATUS'
                      AND ev.status = 'APPLIED'
                ) AS has_applied
            FROM application_current_state AS s
            JOIN source_identity_aliases AS a
              ON a.entity_id = s.entity_id
            WHERE a.is_current = 1
              AND a.identity_type IN ('STABLE_ITEM_KEY', 'URL')
            """
        ).fetchall()
    finally:
        conn.close()

    for row in rows:
        status = row["current_status"] or "NON_SUIVIE"
        applied = bool(row["has_applied"])
        if row["identity_type"] == "STABLE_ITEM_KEY":
            status_by_key[row["identity_value"]] = status
            applied_by_key[row["identity_value"]] = applied
        elif row["identity_type"] == "URL":
            status_by_url[row["identity_value"]] = status
            applied_by_url[row["identity_value"]] = applied
    return status_by_key, status_by_url, applied_by_key, applied_by_url


def current_statuses() -> tuple[dict[str, str], dict[str, str]]:
    status_by_key, status_by_url, _, _ = tracking_maps()
    return status_by_key, status_by_url


def decorate_scored_jobs(items: list[dict[str, Any]], final: bool = False) -> list[dict[str, Any]]:
    by_key, by_url, applied_by_key, applied_by_url = tracking_maps()
    result: list[dict[str, Any]] = []
    for item in items:
        row = dict(item)
        stable = row.get("stable_item_key")
        url = row.get("url")
        row["application_status"] = by_key.get(stable) or by_url.get(url) or "NON_SUIVIE"
        has_applied = (applied_by_key.get(stable) if stable else None)
        if has_applied is None:
            has_applied = applied_by_url.get(url, False)
        row["applied"] = "Oui" if has_applied else "Non"
        if final:
            row["display_score"] = row.get("final_score_v12", row.get("final_score"))
        else:
            row["display_score"] = row.get("queue_score", row.get("match_score"))
        result.append(row)
    return result


def _ajouter_verdict(item: dict[str, Any]) -> None:
    """
    Ajoute le verdict et la piste a une offre affichee.

    Calcule a la lecture plutot que stocke en base : le verdict depend de la
    verite candidat (niveaux de langue, annees d'experience), qui evolue.
    Une colonne figee deviendrait fausse le jour ou le niveau d'anglais
    progresse, sans que rien ne le signale.

    Le cout est negligeable — quelques expressions regulieres sur une page
    de resultats — et l'affichage reste toujours d'accord avec la
    configuration.
    """
    try:
        from matching.piste_accessible import LIBELLES, piste
        from matching.verdict import evaluer
    except Exception:
        return

    texte = item.get("description") or ""
    titre = item.get("title") or ""

    try:
        v = evaluer(texte)
        nom_piste, raison = piste(titre, texte)
    except Exception:
        return

    item["verdict"] = v.verdict
    item["piste"] = nom_piste
    item["piste_libelle"] = LIBELLES.get(nom_piste, nom_piste)
    item["verdict_raison"] = raison
    item["formation_proposee"] = "Oui" if v.formation else ""
    item["barriere"] = v.barrieres[0].message if v.barrieres else ""
    item["barriere_preuve"] = v.barrieres[0].preuve if v.barrieres else ""
    item["alertes"] = " | ".join(a.message for a in v.alertes)
    item["atouts"] = ", ".join(v.atouts[:8])


def query_all_jobs(
    *,
    text: str = "",
    sources: list[str] | None = None,
    active_only: bool = True,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[dict[str, Any]], int, str | None]:
    build_id = latest_build_id()
    if not build_id:
        return [], 0, None

    where = ["cj.build_id = ?"]
    params: list[Any] = [build_id]

    if active_only:
        where.append("rj.is_active = 1")

    if text.strip():
        needle = f"%{text.strip()}%"
        where.append(
            "(COALESCE(cj.title,'') LIKE ? OR COALESCE(cj.company,'') LIKE ? OR COALESCE(cj.location,'') LIKE ?)"
        )
        params.extend([needle, needle, needle])

    if sources:
        placeholders = ",".join("?" for _ in sources)
        where.append(f"UPPER(COALESCE(rj.collection_channel, rj.source, '')) IN ({placeholders})")
        params.extend([s.upper() for s in sources])

    where_sql = " AND ".join(where)

    with connect() as conn:
        total = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM canonical_jobs AS cj
            JOIN raw_jobs AS rj
              ON rj.id = cj.preferred_raw_job_id
            WHERE {where_sql}
            """,
            tuple(params),
        ).fetchone()[0]

        offset = max(0, (page - 1) * page_size)
        rows = conn.execute(
            f"""
            SELECT
                cj.id AS canonical_job_id,
                cj.canonical_key,
                cj.title,
                cj.company,
                cj.location,
                cj.url,
                cj.date_published,
                cj.contract_type,
                cj.language,
                cj.first_seen,
                cj.last_seen,
                cj.member_count,
                cj.source_count,
                rj.collection_channel AS source,
                rj.origin_source,
                rj.source_external_id,
                rj.is_active,
                rj.source_eligibility_status,
                rj.source_eligibility_reason,
                COALESCE(rj.detail_matching_text, cj.description, rj.description, '') AS description
            FROM canonical_jobs AS cj
            JOIN raw_jobs AS rj
              ON rj.id = cj.preferred_raw_job_id
            WHERE {where_sql}
            ORDER BY
                CASE WHEN cj.date_published IS NULL OR cj.date_published = '' THEN 1 ELSE 0 END,
                cj.date_published DESC,
                cj.last_seen DESC,
                cj.id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [page_size, offset]),
        ).fetchall()

    queue, _ = load_latest_queue()
    queue_map = {str(x.get("canonical_job_id")): x for x in queue if x.get("canonical_job_id") is not None}
    pool, _, _ = load_latest_final_pool()
    pool_map = {str(x.get("canonical_job_id")): x for x in pool if x.get("canonical_job_id") is not None}
    by_key, by_url, applied_by_key, applied_by_url = tracking_maps()

    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        q = queue_map.get(str(item["canonical_job_id"]), {})
        p = pool_map.get(str(item["canonical_job_id"]), {})
        stable = p.get("stable_item_key") or q.get("stable_item_key")
        item.update({
            "stable_item_key": stable,
            "application_group_id": p.get("application_group_id") or q.get("application_group_id"),
            "match_score": q.get("match_score"),
            "queue_score": q.get("queue_score"),
            "final_score": p.get("final_score_v12", p.get("final_score")),
            "priority": p.get("priority_v12", p.get("priority")) or q.get("gate_status"),
            "recommended_action": p.get("recommended_action_v12", p.get("recommended_action")) or q.get("queue_status"),
            "cv_track": p.get("cv_track") or q.get("cv_track"),
            "queue_rank": q.get("queue_rank"),
            "pool_rank": p.get("pool_rank_v12", p.get("pool_rank")),
        })
        status = by_key.get(stable) if stable else None
        status = status or by_url.get(item.get("url")) or "NON_SUIVIE"
        item["application_status"] = status
        has_applied = (applied_by_key.get(stable) if stable else None)
        if has_applied is None:
            has_applied = applied_by_url.get(item.get("url"), False)
        item["applied"] = "Oui" if has_applied else "Non"
        _ajouter_verdict(item)
        out.append(item)

    return out, total, build_id


def lifecycle_rows(status: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if status and status != "TOUS":
        where = "WHERE s.current_status = ?"
        params.append(status)
    params.append(limit)

    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                s.entity_id,
                s.lifecycle_id,
                s.application_group_id,
                s.title,
                s.company,
                s.location,
                s.track,
                s.current_status,
                s.status_at,
                EXISTS(
                    SELECT 1
                    FROM application_events AS ev
                    WHERE ev.entity_id = s.entity_id
                      AND ev.event_type = 'STATUS'
                      AND ev.status = 'APPLIED'
                ) AS has_applied,
                (
                    SELECT a.identity_value
                    FROM source_identity_aliases AS a
                    WHERE a.entity_id = s.entity_id
                      AND a.identity_type = 'URL'
                    ORDER BY a.is_current DESC, a.last_seen_at DESC, a.id DESC
                    LIMIT 1
                ) AS url,
                (
                    SELECT a.identity_value
                    FROM source_identity_aliases AS a
                    WHERE a.entity_id = s.entity_id
                      AND a.identity_type = 'STABLE_ITEM_KEY'
                    ORDER BY a.is_current DESC, a.last_seen_at DESC, a.id DESC
                    LIMIT 1
                ) AS stable_item_key
            FROM application_current_state AS s
            {where}
            ORDER BY s.status_at DESC, s.entity_id DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def entity_history(entity_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, event_type, status, actor_type, actor, event_at, note, source
            FROM application_events
            WHERE entity_id = ?
            ORDER BY event_at DESC, id DESC
            """,
            (entity_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def load_latest_delta() -> tuple[dict[str, Any], Path | None]:
    """Charge le dernier artefact Delta Tracker de production."""
    path = _latest_matching(["delta_tracker_v1_20*.json"])
    if path is None:
        path = _latest_matching(["delta_tracker_v1_*.json"])
    if path is None:
        return {}, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload, path
    except Exception:
        pass
    return {}, path
