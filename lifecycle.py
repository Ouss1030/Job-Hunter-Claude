"""
Job Hunter Belgium — Lifecycle Manual CLI V1.0

Manual interface for lifecycle state changes.

Examples:
    python lifecycle.py list
    python lifecycle.py list --status READY
    python lifecycle.py search "Michael Page"
    python lifecycle.py show ITEM_7767194ff01c4d2a
    python lifecycle.py history ITEM_7767194ff01c4d2a
    python lifecycle.py set-status ITEM_7767194ff01c4d2a APPLIED
    python lifecycle.py note ITEM_7767194ff01c4d2a "Candidature envoyée via le site"

Every status mutation uses actor_type=USER.
No network. No Main. No Daily Run.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

from applications import lifecycle_tracker as lt


CLI_VERSION = "1.0"

ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = ROOT / "database" / "jobs.db"
LOG_DIR = ROOT / "exports" / "logs"

STATUS_ALIASES = {
    "DECOUVERT": "DISCOVERED",
    "DECOUVERTE": "DISCOVERED",
    "SHORTLISTE": "SHORTLISTED",
    "SELECTIONNE": "SHORTLISTED",
    "SELECTIONNEE": "SHORTLISTED",
    "PRET": "READY",
    "PRETE": "READY",
    "DOCUMENTS_PRETS": "DOCUMENTS_READY",
    "DOCUMENTS_PRETES": "DOCUMENTS_READY",
    "DOCS_PRETS": "DOCUMENTS_READY",
    "POSTULE": "APPLIED",
    "POSTULEE": "APPLIED",
    "ENTRETIEN": "INTERVIEW",
    "OFFRE": "OFFER",
    "REFUSE": "REJECTED",
    "REFUSEE": "REJECTED",
    "REJETEE": "REJECTED",
    "REJETE": "REJECTED",
    "RETIRE": "WITHDRAWN",
    "RETIREE": "WITHDRAWN",
    "ABANDONNE": "WITHDRAWN",
    "ABANDONNEE": "WITHDRAWN",
    "FERME": "CLOSED",
    "FERMEE": "CLOSED",
}


def normalize_status(value: str) -> str:
    raw = unicodedata.normalize("NFKD", value.strip())
    raw = "".join(
        char
        for char in raw
        if not unicodedata.combining(char)
    )
    raw = raw.upper().replace("-", "_").replace(" ", "_")
    raw = STATUS_ALIASES.get(raw, raw)
    if raw not in lt.STATUSES:
        raise ValueError(
            f"Statut invalide: {value}. "
            f"Valeurs: {', '.join(lt.STATUSES)}"
        )
    return raw


def connect(db_path: Path):
    if not db_path.exists():
        raise RuntimeError(f"Database not found: {db_path}")
    conn = lt.connect_database(db_path)
    if not lt.lifecycle_tables_present(conn):
        conn.close()
        raise RuntimeError(
            "Lifecycle schema missing. Install Step 8B first."
        )
    return conn


def entity_with_state(conn, entity_id: int):
    row = conn.execute(
        """
        SELECT *
        FROM application_current_state
        WHERE entity_id = ?
        """,
        (entity_id,),
    ).fetchone()
    return dict(row) if row else None


def current_aliases(conn, entity_id: int):
    rows = conn.execute(
        """
        SELECT
            identity_type,
            identity_value,
            source,
            first_seen_at,
            last_seen_at,
            is_current
        FROM source_identity_aliases
        WHERE entity_id = ?
        ORDER BY identity_type, is_current DESC, last_seen_at DESC, id DESC
        """,
        (entity_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def resolve_entity(conn, token: str):
    token = token.strip()
    if not token:
        raise ValueError("Identifiant vide")

    row = conn.execute(
        """
        SELECT *
        FROM application_entities
        WHERE lifecycle_id = ?
        """,
        (token,),
    ).fetchone()
    if row:
        return dict(row)

    rows = conn.execute(
        """
        SELECT DISTINCT e.*
        FROM source_identity_aliases AS a
        JOIN application_entities AS e
          ON e.id = a.entity_id
        WHERE a.identity_value = ?
        """,
        (token,),
    ).fetchall()

    if len(rows) == 1:
        return dict(rows[0])

    if len(rows) > 1:
        raise RuntimeError(
            "Ambiguous identity value across aliases; use lifecycle_id."
        )

    raise LookupError(
        f"Aucune candidature Lifecycle trouvée pour: {token}"
    )


def latest_stable_key(conn, entity_id: int):
    row = conn.execute(
        """
        SELECT identity_value
        FROM source_identity_aliases
        WHERE
            entity_id = ?
            AND identity_type = 'STABLE_ITEM_KEY'
        ORDER BY is_current DESC, last_seen_at DESC, id DESC
        LIMIT 1
        """,
        (entity_id,),
    ).fetchone()
    return row[0] if row else None


def list_entities(conn, status=None, limit=50):
    params = []
    where = ""
    if status:
        where = "WHERE s.current_status = ?"
        params.append(status)

    params.append(limit)

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
            (
                SELECT a.identity_value
                FROM source_identity_aliases AS a
                WHERE
                    a.entity_id = s.entity_id
                    AND a.identity_type='STABLE_ITEM_KEY'
                ORDER BY
                    a.is_current DESC,
                    a.last_seen_at DESC,
                    a.id DESC
                LIMIT 1
            ) AS stable_item_key
        FROM application_current_state AS s
        {where}
        ORDER BY
            CASE s.current_status
                WHEN 'APPLIED' THEN 1
                WHEN 'INTERVIEW' THEN 2
                WHEN 'OFFER' THEN 3
                WHEN 'READY' THEN 4
                WHEN 'DOCUMENTS_READY' THEN 5
                WHEN 'SHORTLISTED' THEN 6
                WHEN 'DISCOVERED' THEN 7
                WHEN 'REJECTED' THEN 8
                WHEN 'WITHDRAWN' THEN 9
                WHEN 'CLOSED' THEN 10
                ELSE 99
            END,
            s.entity_id
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()

    return [dict(row) for row in rows]


def search_entities(conn, query: str, limit=30):
    needle = f"%{query.strip()}%"
    rows = conn.execute(
        """
        SELECT
            s.entity_id,
            s.lifecycle_id,
            s.title,
            s.company,
            s.location,
            s.track,
            s.current_status,
            (
                SELECT a.identity_value
                FROM source_identity_aliases AS a
                WHERE
                    a.entity_id = s.entity_id
                    AND a.identity_type='STABLE_ITEM_KEY'
                ORDER BY
                    a.is_current DESC,
                    a.last_seen_at DESC,
                    a.id DESC
                LIMIT 1
            ) AS stable_item_key
        FROM application_current_state AS s
        WHERE
            COALESCE(s.title, '') LIKE ?
            OR COALESCE(s.company, '') LIKE ?
            OR COALESCE(s.location, '') LIKE ?
            OR COALESCE(s.lifecycle_id, '') LIKE ?
            OR EXISTS (
                SELECT 1
                FROM source_identity_aliases AS a
                WHERE
                    a.entity_id = s.entity_id
                    AND a.identity_value LIKE ?
            )
        ORDER BY s.entity_id
        LIMIT ?
        """,
        (
            needle,
            needle,
            needle,
            needle,
            needle,
            limit,
        ),
    ).fetchall()
    return [dict(row) for row in rows]


def history(conn, entity_id: int):
    return lt.event_history(conn, entity_id)


def write_action_log(action: dict):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = LOG_DIR / f"lifecycle_manual_action_{stamp}.json"
    path.write_text(
        json.dumps(action, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def set_status(
    conn,
    *,
    entity,
    status,
    note=None,
    actor="USER",
    write_log=True,
):
    status = normalize_status(status)
    current = entity_with_state(conn, entity["id"])
    previous = current["current_status"] if current else None

    if previous == status:
        result = {
            "status": "NO_CHANGE",
            "lifecycle_id": entity["lifecycle_id"],
            "entity_id": entity["id"],
            "previous_status": previous,
            "new_status": status,
            "event_id": None,
        }
        return result

    stable_key = latest_stable_key(conn, entity["id"])

    conn.execute("BEGIN IMMEDIATE")
    try:
        event_id = lt.record_user_status(
            conn,
            entity_id=entity["id"],
            status=status,
            actor=actor,
            stable_item_key=stable_key,
            note=note,
            details={
                "cli_version": CLI_VERSION,
                "manual_command": True,
                "previous_status": previous,
            },
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    result = {
        "status": "UPDATED",
        "lifecycle_id": entity["lifecycle_id"],
        "entity_id": entity["id"],
        "stable_item_key": stable_key,
        "previous_status": previous,
        "new_status": status,
        "event_id": event_id,
        "actor_type": "USER",
        "note": note,
    }

    if write_log:
        result["action_log"] = str(write_action_log(result))

    return result


def add_note(
    conn,
    *,
    entity,
    text,
    actor="USER",
    write_log=True,
):
    stable_key = latest_stable_key(conn, entity["id"])

    conn.execute("BEGIN IMMEDIATE")
    try:
        event_id = lt.record_event(
            conn,
            entity_id=entity["id"],
            event_type="NOTE",
            actor_type="USER",
            actor=actor,
            stable_item_key=stable_key,
            note=text,
            details={
                "cli_version": CLI_VERSION,
                "manual_command": True,
            },
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    result = {
        "status": "NOTE_ADDED",
        "lifecycle_id": entity["lifecycle_id"],
        "entity_id": entity["id"],
        "stable_item_key": stable_key,
        "event_id": event_id,
        "actor_type": "USER",
        "note": text,
    }

    if write_log:
        result["action_log"] = str(write_action_log(result))

    return result


def print_rows(rows):
    if not rows:
        print("Aucun résultat.")
        return

    for row in rows:
        print(
            f"[{row.get('current_status') or '-':15}] "
            f"{row.get('stable_item_key') or row.get('lifecycle_id')} | "
            f"{row.get('company') or '-'} | "
            f"{row.get('title') or '-'} | "
            f"{row.get('location') or '-'}"
        )


def cmd_list(args):
    conn = connect(args.db)
    try:
        status = normalize_status(args.status) if args.status else None
        rows = list_entities(conn, status=status, limit=args.limit)
    finally:
        conn.close()

    print_rows(rows)
    print()
    print(f"Résultats : {len(rows)}")


def cmd_search(args):
    conn = connect(args.db)
    try:
        rows = search_entities(conn, args.query, limit=args.limit)
    finally:
        conn.close()

    print_rows(rows)
    print()
    print(f"Résultats : {len(rows)}")


def cmd_show(args):
    conn = connect(args.db)
    try:
        entity = resolve_entity(conn, args.identity)
        state = entity_with_state(conn, entity["id"])
        aliases = current_aliases(conn, entity["id"])
        payload = {
            "entity": entity,
            "current_state": state,
            "aliases": aliases,
        }
    finally:
        conn.close()

    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_history(args):
    conn = connect(args.db)
    try:
        entity = resolve_entity(conn, args.identity)
        rows = history(conn, entity["id"])
    finally:
        conn.close()

    print(
        f"{entity['lifecycle_id']} | "
        f"{entity.get('company') or '-'} | "
        f"{entity.get('title') or '-'}"
    )
    print("-" * 100)

    for row in rows:
        status = row.get("status") or "-"
        note = row.get("note") or ""
        print(
            f"{row['event_at']} | "
            f"{row['event_type']:10} | "
            f"{status:15} | "
            f"{row['actor_type']:9} | "
            f"{note}"
        )

    print()
    print(f"Événements : {len(rows)}")


def cmd_set_status(args):
    conn = connect(args.db)
    try:
        entity = resolve_entity(conn, args.identity)
        result = set_status(
            conn,
            entity=entity,
            status=args.status,
            note=args.note,
            actor="USER",
            write_log=not args.no_log,
        )
    finally:
        conn.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_note(args):
    conn = connect(args.db)
    try:
        entity = resolve_entity(conn, args.identity)
        result = add_note(
            conn,
            entity=entity,
            text=args.text,
            actor="USER",
            write_log=not args.no_log,
        )
    finally:
        conn.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(
        description="Job Hunter Lifecycle manual interface"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="SQLite DB path (default: database/jobs.db)",
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    p_list = sub.add_parser("list")
    p_list.add_argument("--status")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.set_defaults(func=cmd_list)

    p_search = sub.add_parser("search")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=30)
    p_search.set_defaults(func=cmd_search)

    p_show = sub.add_parser("show")
    p_show.add_argument("identity")
    p_show.set_defaults(func=cmd_show)

    p_history = sub.add_parser("history")
    p_history.add_argument("identity")
    p_history.set_defaults(func=cmd_history)

    p_set = sub.add_parser("set-status")
    p_set.add_argument("identity")
    p_set.add_argument("status")
    p_set.add_argument("--note")
    p_set.add_argument("--no-log", action="store_true")
    p_set.set_defaults(func=cmd_set_status)

    p_note = sub.add_parser("note")
    p_note.add_argument("identity")
    p_note.add_argument("text")
    p_note.add_argument("--no-log", action="store_true")
    p_note.set_defaults(func=cmd_note)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
