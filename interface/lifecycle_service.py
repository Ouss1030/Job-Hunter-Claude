from __future__ import annotations

from typing import Any

from applications import lifecycle_tracker as lt
from interface.data_access import DB_PATH


USER_STATUSES = list(lt.STATUSES)


def _resolve(conn, job: dict[str, Any]):
    stable = (job.get("stable_item_key") or "").strip()
    url = (job.get("url") or "").strip()

    if stable:
        entity = lt.resolve_entity_by_alias(
            conn,
            identity_type="STABLE_ITEM_KEY",
            identity_value=stable,
        )
        if entity:
            return entity

    if url:
        entity = lt.resolve_entity_by_alias(
            conn,
            identity_type="URL",
            identity_value=url,
        )
        if entity:
            return entity

    return None


def ensure_entity(conn, job: dict[str, Any]) -> dict[str, Any]:
    entity = _resolve(conn, job)
    if entity:
        return entity

    stable = (job.get("stable_item_key") or "").strip()
    url = (job.get("url") or "").strip()
    canonical = str(job.get("canonical_job_id") or "").strip()
    seed = stable or url or f"CANONICAL:{canonical}:{job.get('title','')}:{job.get('company','')}"

    entity_id = lt.create_entity(
        conn,
        seed=seed,
        application_group_id=job.get("application_group_id"),
        title=job.get("title"),
        company=job.get("company"),
        location=job.get("location"),
        track=job.get("cv_track"),
        metadata={
            "created_by": "JOBHUNTER_UI_V1",
            "canonical_job_id": job.get("canonical_job_id"),
        },
    )

    if stable:
        lt.attach_alias(
            conn,
            entity_id=entity_id,
            identity_type="STABLE_ITEM_KEY",
            identity_value=stable,
            source=job.get("source"),
        )

    if url:
        lt.attach_alias(
            conn,
            entity_id=entity_id,
            identity_type="URL",
            identity_value=url,
            source=job.get("source"),
        )

    group = (job.get("application_group_id") or "").strip()
    if group:
        lt.attach_alias(
            conn,
            entity_id=entity_id,
            identity_type="APPLICATION_GROUP_ID",
            identity_value=group,
            source=job.get("source"),
        )

    entity = lt.get_entity(conn, entity_id)
    assert entity is not None
    return entity


def set_status(job: dict[str, Any], status: str, note: str | None = None) -> str:
    status = status.upper().strip()
    if status not in USER_STATUSES:
        raise ValueError(f"Statut inconnu: {status}")

    conn = lt.connect_database(DB_PATH)
    try:
        lt.ensure_schema(conn)
        entity = ensure_entity(conn, job)
        current = lt.current_state(conn, entity["id"])
        previous = current.get("current_status") if current else None

        if previous == status:
            return status

        # Une nouvelle offre reçoit d'abord une trace DISCOVERED, puis l'action utilisateur.
        if previous is None and status != "DISCOVERED":
            lt.record_system_status(
                conn,
                entity_id=entity["id"],
                status="DISCOVERED",
                actor="JOBHUNTER_UI_V1",
                source=job.get("source"),
                stable_item_key=job.get("stable_item_key"),
            )

        lt.record_user_status(
            conn,
            entity_id=entity["id"],
            status=status,
            actor="OUSSAMA_UI",
            source=job.get("source"),
            stable_item_key=job.get("stable_item_key"),
            note=note.strip() if note else None,
            details={"origin": "JobHunter UI"},
        )
        conn.commit()
        return status
    finally:
        conn.close()


def add_note(job: dict[str, Any], note: str) -> None:
    note = note.strip()
    if not note:
        return

    conn = lt.connect_database(DB_PATH)
    try:
        lt.ensure_schema(conn)
        entity = ensure_entity(conn, job)
        lt.record_event(
            conn,
            entity_id=entity["id"],
            event_type="NOTE",
            actor_type="USER",
            actor="OUSSAMA_UI",
            source=job.get("source"),
            stable_item_key=job.get("stable_item_key"),
            note=note,
            details={"origin": "JobHunter UI"},
        )
        conn.commit()
    finally:
        conn.close()
