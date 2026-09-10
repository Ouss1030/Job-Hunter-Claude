"""
Job Hunter Belgium — Lifecycle Tracker Core V1.0

Fondations :
- application_entities
- application_events (append-only)
- source_identity_aliases
- application_current_state view

Règles critiques :
- le statut courant est dérivé du dernier événement STATUS ;
- APPLIED ne peut être écrit que par actor_type=USER ;
- les résultats humains (INTERVIEW/OFFER/REJECTED/WITHDRAWN/CLOSED)
  ne peuvent pas être produits par actor_type=SYSTEM ;
- un événement de visibilité (SEEN / REPOSTED) ne modifie jamais le statut.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LIFECYCLE_VERSION = "1.1"
LIFECYCLE_SCHEMA_VERSION = "1.0"

STATUSES = (
    "DISCOVERED",
    "SHORTLISTED",
    "READY",
    "DOCUMENTS_READY",
    "APPLIED",
    "INTERVIEW",
    "OFFER",
    "REJECTED",
    "WITHDRAWN",
    "CLOSED",
)

EVENT_TYPES = (
    "STATUS",
    "SEEN",
    "REPOSTED",
    "NOTE",
    "DOCUMENTS",
)

ACTOR_TYPES = (
    "USER",
    "SYSTEM",
    "MIGRATION",
)

IDENTITY_TYPES = (
    "STABLE_ITEM_KEY",
    "DELTA_IDENTITY_KEY",
    "APPLICATION_GROUP_ID",
    "URL",
    "SOURCE_EXTERNAL_ID",
)

SYSTEM_ALLOWED_STATUSES = {
    "DISCOVERED",
    "SHORTLISTED",
    "READY",
    "DOCUMENTS_READY",
}

MANUAL_ONLY_STATUSES = set(STATUSES) - SYSTEM_ALLOWED_STATUSES


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS application_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lifecycle_id TEXT NOT NULL UNIQUE,
    application_group_id TEXT,
    title TEXT,
    company TEXT,
    location TEXT,
    track TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT,
    next_action_date TEXT,
    contact_name TEXT,
    contact_channel TEXT
);

CREATE INDEX IF NOT EXISTS idx_application_entities_group
ON application_entities(application_group_id);

CREATE INDEX IF NOT EXISTS idx_application_entities_company
ON application_entities(company);


CREATE TABLE IF NOT EXISTS application_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    event_type TEXT NOT NULL
        CHECK(event_type IN ('STATUS','SEEN','REPOSTED','NOTE','DOCUMENTS')),
    status TEXT
        CHECK(status IS NULL OR status IN (
            'DISCOVERED','SHORTLISTED','READY','DOCUMENTS_READY',
            'APPLIED','INTERVIEW','OFFER','REJECTED','WITHDRAWN','CLOSED'
        )),
    actor_type TEXT NOT NULL
        CHECK(actor_type IN ('USER','SYSTEM','MIGRATION')),
    actor TEXT,
    event_at TEXT NOT NULL,
    source TEXT,
    stable_item_key TEXT,
    related_identity_value TEXT,
    note TEXT,
    details_json TEXT,
    FOREIGN KEY(entity_id)
        REFERENCES application_entities(id)
        ON DELETE CASCADE,
    CHECK(
        (event_type = 'STATUS' AND status IS NOT NULL)
        OR
        (event_type <> 'STATUS' AND status IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_application_events_entity_time
ON application_events(entity_id, event_at, id);

CREATE INDEX IF NOT EXISTS idx_application_events_type
ON application_events(event_type);

CREATE INDEX IF NOT EXISTS idx_application_events_status
ON application_events(status);


CREATE TABLE IF NOT EXISTS source_identity_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    identity_type TEXT NOT NULL
        CHECK(identity_type IN (
            'STABLE_ITEM_KEY',
            'DELTA_IDENTITY_KEY',
            'APPLICATION_GROUP_ID',
            'URL',
            'SOURCE_EXTERNAL_ID'
        )),
    identity_value TEXT NOT NULL,
    source TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1
        CHECK(is_current IN (0,1)),
    evidence_json TEXT,
    FOREIGN KEY(entity_id)
        REFERENCES application_entities(id)
        ON DELETE CASCADE,
    UNIQUE(identity_type, identity_value)
);

CREATE INDEX IF NOT EXISTS idx_source_identity_aliases_entity
ON source_identity_aliases(entity_id);

CREATE INDEX IF NOT EXISTS idx_source_identity_aliases_source
ON source_identity_aliases(source);


CREATE VIEW IF NOT EXISTS application_current_state AS
SELECT
    e.id AS entity_id,
    e.lifecycle_id,
    e.application_group_id,
    e.title,
    e.company,
    e.location,
    e.track,
    s.id AS status_event_id,
    s.status AS current_status,
    s.event_at AS status_at,
    s.actor_type AS status_actor_type,
    s.actor AS status_actor
FROM application_entities AS e
LEFT JOIN application_events AS s
    ON s.id = (
        SELECT ev.id
        FROM application_events AS ev
        WHERE
            ev.entity_id = e.id
            AND ev.event_type = 'STATUS'
        ORDER BY ev.event_at DESC, ev.id DESC
        LIMIT 1
    );


CREATE TRIGGER IF NOT EXISTS trg_application_events_no_update
BEFORE UPDATE ON application_events
BEGIN
    SELECT RAISE(
        ABORT,
        'application_events is append-only: UPDATE forbidden'
    );
END;


CREATE TRIGGER IF NOT EXISTS trg_application_events_no_delete
BEFORE DELETE ON application_events
BEGIN
    SELECT RAISE(
        ABORT,
        'application_events is append-only: DELETE forbidden'
    );
END;


CREATE TRIGGER IF NOT EXISTS trg_application_events_applied_user_only
BEFORE INSERT ON application_events
WHEN
    NEW.event_type = 'STATUS'
    AND NEW.status = 'APPLIED'
    AND NEW.actor_type <> 'USER'
BEGIN
    SELECT RAISE(
        ABORT,
        'APPLIED requires explicit USER action'
    );
END;


CREATE TRIGGER IF NOT EXISTS trg_application_events_system_manual_status_block
BEFORE INSERT ON application_events
WHEN
    NEW.event_type = 'STATUS'
    AND NEW.actor_type = 'SYSTEM'
    AND NEW.status IN (
        'APPLIED','INTERVIEW','OFFER',
        'REJECTED','WITHDRAWN','CLOSED'
    )
BEGIN
    SELECT RAISE(
        ABORT,
        'SYSTEM cannot set manual lifecycle outcome status'
    );
END;
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_text(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
    )


def connect_database(
    db_path: str | Path,
) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Colonnes ajoutees apres coup : une base existante ne les a pas.
#
# CREATE TABLE IF NOT EXISTS ne modifie pas une table deja creee. Sans cette
# migration, le suivi de candidature echouerait sur toute base anterieure —
# c'est-a-dire sur la seule qui compte, celle qui porte l'historique.
_COLONNES_AJOUTEES = {
    "application_entities": {
        # Date de relance prevue, au format ISO. C'est elle qui repond a la
        # question « qu'est-ce qui demande mon attention aujourd'hui ».
        "next_action_date": "TEXT",
        "contact_name": "TEXT",
        "contact_channel": "TEXT",
    },
}


def _colonnes_existantes(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        ligne[1]
        for ligne in conn.execute(f"PRAGMA table_info({table})")
    }


def migrer_colonnes(
    conn: sqlite3.Connection,
) -> list[str]:
    """
    Ajoute les colonnes manquantes. Idempotent : relancable sans effet.

    Renvoie la liste de ce qui a ete ajoute, pour que l'appelant puisse le
    journaliser — une migration silencieuse est une migration qu'on ne sait
    pas diagnostiquer.
    """
    ajoutees = []
    for table, colonnes in _COLONNES_AJOUTEES.items():
        presentes = _colonnes_existantes(conn, table)
        if not presentes:
            continue
        for nom, type_sql in colonnes.items():
            if nom in presentes:
                continue
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {nom} {type_sql}"
            )
            ajoutees.append(f"{table}.{nom}")
    if ajoutees:
        conn.commit()
    return ajoutees


def ensure_schema(
    conn: sqlite3.Connection,
) -> None:
    conn.executescript(SCHEMA_SQL)
    migrer_colonnes(conn)


def lifecycle_tables_present(
    conn: sqlite3.Connection,
) -> bool:
    names = {
        row[0]
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            """
        )
    }
    return {
        "application_entities",
        "application_events",
        "source_identity_aliases",
    } <= names


def make_lifecycle_id(
    seed: str,
) -> str:
    digest = hashlib.sha256(
        seed.encode("utf-8")
    ).hexdigest()[:16]
    return f"LIFE_{digest}"


def create_entity(
    conn: sqlite3.Connection,
    *,
    seed: str,
    application_group_id: str | None = None,
    title: str | None = None,
    company: str | None = None,
    location: str | None = None,
    track: str | None = None,
    metadata: dict | None = None,
    created_at: str | None = None,
) -> int:
    now = created_at or utc_now()
    lifecycle_id = make_lifecycle_id(seed)

    cursor = conn.execute(
        """
        INSERT INTO application_entities (
            lifecycle_id,
            application_group_id,
            title,
            company,
            location,
            track,
            created_at,
            updated_at,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lifecycle_id,
            application_group_id,
            title,
            company,
            location,
            track,
            now,
            now,
            json_text(metadata),
        ),
    )
    return int(cursor.lastrowid)


def get_entity(
    conn: sqlite3.Connection,
    entity_id: int,
) -> dict | None:
    row = conn.execute(
        """
        SELECT *
        FROM application_entities
        WHERE id = ?
        """,
        (entity_id,),
    ).fetchone()
    return dict(row) if row else None


def attach_alias(
    conn: sqlite3.Connection,
    *,
    entity_id: int,
    identity_type: str,
    identity_value: str,
    source: str | None = None,
    seen_at: str | None = None,
    is_current: bool = True,
    evidence: dict | None = None,
) -> int:
    identity_type = identity_type.upper().strip()
    identity_value = identity_value.strip()

    if identity_type not in IDENTITY_TYPES:
        raise ValueError(
            f"Unsupported identity_type: {identity_type}"
        )
    if not identity_value:
        raise ValueError("identity_value is required")

    existing = conn.execute(
        """
        SELECT id, entity_id
        FROM source_identity_aliases
        WHERE
            identity_type = ?
            AND identity_value = ?
        """,
        (identity_type, identity_value),
    ).fetchone()

    if existing:
        if int(existing["entity_id"]) != int(entity_id):
            raise ValueError(
                "Alias already belongs to another lifecycle entity"
            )

        conn.execute(
            """
            UPDATE source_identity_aliases
            SET
                last_seen_at = ?,
                is_current = ?,
                source = COALESCE(?, source),
                evidence_json = COALESCE(?, evidence_json)
            WHERE id = ?
            """,
            (
                seen_at or utc_now(),
                1 if is_current else 0,
                source,
                json_text(evidence),
                int(existing["id"]),
            ),
        )
        return int(existing["id"])

    now = seen_at or utc_now()
    cursor = conn.execute(
        """
        INSERT INTO source_identity_aliases (
            entity_id,
            identity_type,
            identity_value,
            source,
            first_seen_at,
            last_seen_at,
            is_current,
            evidence_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_id,
            identity_type,
            identity_value,
            source,
            now,
            now,
            1 if is_current else 0,
            json_text(evidence),
        ),
    )
    return int(cursor.lastrowid)


def resolve_entity_by_alias(
    conn: sqlite3.Connection,
    *,
    identity_type: str,
    identity_value: str,
) -> dict | None:
    row = conn.execute(
        """
        SELECT e.*
        FROM source_identity_aliases AS a
        JOIN application_entities AS e
          ON e.id = a.entity_id
        WHERE
            a.identity_type = ?
            AND a.identity_value = ?
        """,
        (
            identity_type.upper().strip(),
            identity_value.strip(),
        ),
    ).fetchone()

    return dict(row) if row else None


def record_event(
    conn: sqlite3.Connection,
    *,
    entity_id: int,
    event_type: str,
    actor_type: str,
    status: str | None = None,
    actor: str | None = None,
    event_at: str | None = None,
    source: str | None = None,
    stable_item_key: str | None = None,
    related_identity_value: str | None = None,
    note: str | None = None,
    details: dict | None = None,
) -> int:
    event_type = event_type.upper().strip()
    actor_type = actor_type.upper().strip()
    status = status.upper().strip() if status else None

    if event_type not in EVENT_TYPES:
        raise ValueError(
            f"Unsupported event_type: {event_type}"
        )
    if actor_type not in ACTOR_TYPES:
        raise ValueError(
            f"Unsupported actor_type: {actor_type}"
        )

    if event_type == "STATUS":
        if status not in STATUSES:
            raise ValueError(
                f"Unsupported lifecycle status: {status}"
            )
    elif status is not None:
        raise ValueError(
            "Non-STATUS events cannot carry a status"
        )

    if status == "APPLIED" and actor_type != "USER":
        raise PermissionError(
            "APPLIED requires explicit USER action"
        )

    if (
        event_type == "STATUS"
        and actor_type == "SYSTEM"
        and status in MANUAL_ONLY_STATUSES
    ):
        raise PermissionError(
            f"SYSTEM cannot set manual status {status}"
        )

    cursor = conn.execute(
        """
        INSERT INTO application_events (
            entity_id,
            event_type,
            status,
            actor_type,
            actor,
            event_at,
            source,
            stable_item_key,
            related_identity_value,
            note,
            details_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_id,
            event_type,
            status,
            actor_type,
            actor,
            event_at or utc_now(),
            source,
            stable_item_key,
            related_identity_value,
            note,
            json_text(details),
        ),
    )

    return int(cursor.lastrowid)


def record_system_status(
    conn: sqlite3.Connection,
    *,
    entity_id: int,
    status: str,
    actor: str,
    **kwargs,
) -> int:
    return record_event(
        conn,
        entity_id=entity_id,
        event_type="STATUS",
        actor_type="SYSTEM",
        status=status,
        actor=actor,
        **kwargs,
    )


def record_user_status(
    conn: sqlite3.Connection,
    *,
    entity_id: int,
    status: str,
    actor: str = "USER",
    **kwargs,
) -> int:
    return record_event(
        conn,
        entity_id=entity_id,
        event_type="STATUS",
        actor_type="USER",
        status=status,
        actor=actor,
        **kwargs,
    )


def record_visibility_event(
    conn: sqlite3.Connection,
    *,
    entity_id: int,
    event_type: str,
    actor: str,
    source: str | None = None,
    stable_item_key: str | None = None,
    related_identity_value: str | None = None,
    details: dict | None = None,
    event_at: str | None = None,
) -> int:
    event_type = event_type.upper().strip()
    if event_type not in {"SEEN", "REPOSTED"}:
        raise ValueError(
            "Visibility event must be SEEN or REPOSTED"
        )

    return record_event(
        conn,
        entity_id=entity_id,
        event_type=event_type,
        actor_type="SYSTEM",
        actor=actor,
        source=source,
        stable_item_key=stable_item_key,
        related_identity_value=related_identity_value,
        details=details,
        event_at=event_at,
    )


def current_state(
    conn: sqlite3.Connection,
    entity_id: int,
) -> dict | None:
    row = conn.execute(
        """
        SELECT *
        FROM application_current_state
        WHERE entity_id = ?
        """,
        (entity_id,),
    ).fetchone()

    return dict(row) if row else None


def event_history(
    conn: sqlite3.Connection,
    entity_id: int,
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT *
        FROM application_events
        WHERE entity_id = ?
        ORDER BY event_at, id
        """,
        (entity_id,),
    ).fetchall()

    return [dict(row) for row in rows]
