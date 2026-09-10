from __future__ import annotations

from datetime import date, datetime
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


# ------------------------------------------------------------------
# Suivi : relance, contact, canal
# ------------------------------------------------------------------
# Le pipeline sait dire qu'une offre est prete. Il ne sait rien de ce qui
# se passe ensuite : a qui on a ecrit, par quel canal, et quand il faudra
# relancer. Ces trois informations n'existent que dans la tete du candidat,
# et c'est precisement pour cela qu'elles doivent etre ecrites quelque part.
#
# La date de relance porte tout le poids : c'est elle qui repond a la seule
# question qui compte un matin — qu'est-ce qui demande mon attention
# aujourd'hui.

_CHAMPS_SUIVI = ("next_action_date", "contact_name", "contact_channel")


def _valider_date(valeur: str | None) -> str | None:
    """
    Date ISO, ou rien.

    Une date mal formee vaut moins que pas de date : elle ne declenchera
    jamais de rappel, et personne ne s'en apercevra. On refuse donc plutot
    que d'enregistrer une valeur qui ne sera jamais lue.
    """
    texte = str(valeur or "").strip()
    if not texte:
        return None
    try:
        date.fromisoformat(texte)
    except ValueError as erreur:
        raise ValueError(
            f"Date de relance invalide : {texte!r} (format attendu AAAA-MM-JJ)"
        ) from erreur
    return texte


def get_suivi(job: dict[str, Any]) -> dict[str, Any]:
    """Champs de suivi de l'offre, vides si elle n'est pas encore suivie."""
    conn = lt.connect_database(DB_PATH)
    try:
        lt.ensure_schema(conn)
        entity = _resolve(conn, job)
        if not entity:
            return {champ: None for champ in _CHAMPS_SUIVI}
        ligne = conn.execute(
            f"SELECT {', '.join(_CHAMPS_SUIVI)} "
            f"FROM application_entities WHERE id = ?",
            (entity["id"],),
        ).fetchone()
        if not ligne:
            return {champ: None for champ in _CHAMPS_SUIVI}
        return dict(zip(_CHAMPS_SUIVI, ligne))
    finally:
        conn.close()


def save_suivi(job: dict[str, Any],
               next_action_date: str | None = None,
               contact_name: str | None = None,
               contact_channel: str | None = None,
               note: str | None = None) -> dict[str, Any]:
    """
    Enregistre le suivi et journalise la modification.

    L'ecriture passe par application_events autant que par les colonnes :
    savoir qu'une relance est prevue au 20 septembre est utile, savoir
    QUAND on l'a decidee l'est aussi.
    """
    valeurs = {
        "next_action_date": _valider_date(next_action_date),
        "contact_name": (str(contact_name).strip() or None
                         if contact_name is not None else None),
        "contact_channel": (str(contact_channel).strip() or None
                            if contact_channel is not None else None),
    }

    conn = lt.connect_database(DB_PATH)
    try:
        lt.ensure_schema(conn)
        entity = ensure_entity(conn, job)
        conn.execute(
            "UPDATE application_entities SET "
            "next_action_date = ?, contact_name = ?, contact_channel = ?, "
            "updated_at = ? WHERE id = ?",
            (valeurs["next_action_date"], valeurs["contact_name"],
             valeurs["contact_channel"],
             datetime.now().isoformat(timespec="seconds"), entity["id"]),
        )

        resume = ", ".join(f"{cle}={val}" for cle, val in valeurs.items() if val)
        lt.record_event(
            conn,
            entity_id=entity["id"],
            # NOTE, et non un type dedie : EVENT_TYPES est un vocabulaire
            # partage par le tracker et ses audits. Y ajouter une valeur
            # pour un besoin d'interface ferait porter le risque au mauvais
            # endroit. Les valeurs structurees voyagent dans details_json.
            event_type="NOTE",
            actor_type="USER",
            actor="OUSSAMA_UI",
            source=job.get("source"),
            stable_item_key=job.get("stable_item_key"),
            note=(note or "").strip() or f"Suivi mis à jour : {resume or 'vidé'}",
            details={"origin": "JobHunter Web", **{k: v for k, v in valeurs.items() if v}},
        )

        conn.commit()
        return valeurs
    finally:
        conn.close()


def relances_dues(jusqu_a: str | None = None) -> list[dict[str, Any]]:
    """
    Candidatures dont la relance est arrivee a echeance.

    Les dates passees comptent aussi : une relance oubliee la semaine
    derniere reste a faire. Les masquer serait le meilleur moyen de ne
    jamais la voir.
    """
    limite = jusqu_a or date.today().isoformat()
    conn = lt.connect_database(DB_PATH)
    try:
        lt.ensure_schema(conn)
        lignes = conn.execute(
            "SELECT id, title, company, track, next_action_date, "
            "       contact_name, contact_channel "
            "FROM application_entities "
            "WHERE next_action_date IS NOT NULL "
            "  AND TRIM(next_action_date) <> '' "
            "  AND next_action_date <= ? "
            "ORDER BY next_action_date",
            (limite,),
        ).fetchall()
        colonnes = ("id", "title", "company", "track", "next_action_date",
                    "contact_name", "contact_channel")
        return [dict(zip(colonnes, ligne)) for ligne in lignes]
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
