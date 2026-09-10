"""
Job Hunter Belgium — Lifecycle Sync V1.0

Synchronise un Final Pool V1.2 + Delta Tracker V1.x vers le Lifecycle
sans écraser les décisions humaines.

Règles :
- aucune création automatique de APPLIED ;
- aucune fermeture automatique sur DISAPPEARED ;
- aucun downgrade automatique de statut ;
- DOCUMENTS_READY et tous les statuts humains sont préservés ;
- REPOSTED réutilise la même lifecycle entity ;
- conflits d'identité => refus de synchroniser, jamais de fusion au hasard ;
- idempotent sur le même artifact Delta.
"""

from __future__ import annotations

import fnmatch
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from applications import lifecycle_tracker as lt


LIFECYCLE_SYNC_VERSION = "1.0"
SYNC_ACTOR = "LIFECYCLE_SYNC_V1"

AUTO_STATUS_RANK = {
    "DISCOVERED": 1,
    "SHORTLISTED": 2,
    "READY": 3,
}

PROTECTED_STATUSES = {
    "DOCUMENTS_READY",
    "APPLIED",
    "INTERVIEW",
    "OFFER",
    "REJECTED",
    "WITHDRAWN",
    "CLOSED",
}

ACTION_TARGET_STATUS = {
    "APPLY_NOW": "READY",
    "APPLY_NEXT": "SHORTLISTED",
    "REVIEW_FIRST": "SHORTLISTED",
    "DO_NOT_APPLY": "DISCOVERED",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def latest_matching(
    directory: str | Path,
    pattern: str,
) -> Path | None:
    directory = Path(directory)
    if not directory.exists():
        return None

    paths = [
        path
        for path in directory.iterdir()
        if path.is_file()
        and fnmatch.fnmatch(path.name, pattern)
    ]
    return (
        max(paths, key=lambda p: p.stat().st_mtime)
        if paths
        else None
    )


def load_json(path: str | Path) -> Any:
    return json.loads(
        Path(path).read_text(
            encoding="utf-8-sig",
            errors="strict",
        )
    )


def get_items(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [
            item
            for item in payload
            if isinstance(item, dict)
        ]

    if isinstance(payload, dict):
        for key in (
            "items",
            "applications",
            "pool",
            "jobs",
            "results",
            "records",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                return [
                    item
                    for item in value
                    if isinstance(item, dict)
                ]

    raise ValueError(
        "Cannot locate item list in payload"
    )


def nonempty(value: Any) -> bool:
    return (
        value is not None
        and str(value).strip() != ""
    )


def current_action(item: dict) -> str:
    return (
        item.get("recommended_action_v12")
        or item.get("recommended_action")
        or ""
    ).strip().upper()


def target_status_for_item(
    item: dict,
) -> tuple[str, str | None]:
    action = current_action(item)

    if action in ACTION_TARGET_STATUS:
        return ACTION_TARGET_STATUS[action], None

    return (
        "DISCOVERED",
        f"Unknown recommended_action={action!r}; "
        "conservative target DISCOVERED used",
    )


def delta_map(
    delta_items: list[dict],
) -> tuple[dict[str, dict], list[dict]]:
    by_identity = {}
    disappeared = []

    for record in delta_items:
        identity = record.get("identity_key")
        status = (
            record.get("delta_status")
            or ""
        ).upper()

        if status == "DISAPPEARED":
            disappeared.append(record)
            continue

        if nonempty(identity):
            if identity in by_identity:
                raise ValueError(
                    f"Duplicate Delta identity_key: {identity}"
                )
            by_identity[identity] = record

    return by_identity, disappeared


def aliases_for_value(
    conn,
    *,
    identity_type: str,
    identity_value: str | None,
) -> list[dict]:
    if not nonempty(identity_value):
        return []

    rows = conn.execute(
        """
        SELECT
            a.entity_id,
            a.identity_type,
            a.identity_value,
            a.is_current,
            e.lifecycle_id
        FROM source_identity_aliases AS a
        JOIN application_entities AS e
          ON e.id = a.entity_id
        WHERE
            a.identity_type = ?
            AND a.identity_value = ?
        """,
        (
            identity_type,
            str(identity_value).strip(),
        ),
    ).fetchall()

    return [dict(row) for row in rows]


def candidate_entity_ids(
    conn,
    item: dict,
    delta_record: dict | None,
) -> dict[str, int]:
    candidates = {}

    probes = [
        (
            "CURRENT_STABLE",
            "STABLE_ITEM_KEY",
            item.get("stable_item_key"),
        ),
        (
            "APPLICATION_GROUP",
            "APPLICATION_GROUP_ID",
            item.get("application_group_id"),
        ),
        (
            "CURRENT_URL",
            "URL",
            item.get("url"),
        ),
    ]

    if delta_record and (
        delta_record.get("delta_status")
        == "REPOSTED"
    ):
        probes.insert(
            1,
            (
                "REPOST_OLD_STABLE",
                "STABLE_ITEM_KEY",
                delta_record.get(
                    "reposted_from_identity_key"
                ),
            ),
        )
        probes.append(
            (
                "REPOST_OLD_URL",
                "URL",
                delta_record.get("previous_url"),
            )
        )

    for label, identity_type, value in probes:
        rows = aliases_for_value(
            conn,
            identity_type=identity_type,
            identity_value=value,
        )

        if len(rows) > 1:
            raise RuntimeError(
                f"Alias uniqueness violation for "
                f"{identity_type}={value}"
            )

        if rows:
            candidates[label] = int(
                rows[0]["entity_id"]
            )

    return candidates


def resolve_existing_entity(
    conn,
    item: dict,
    delta_record: dict | None,
) -> tuple[dict | None, str | None]:
    candidates = candidate_entity_ids(
        conn,
        item,
        delta_record,
    )

    entity_ids = set(
        candidates.values()
    )

    if len(entity_ids) > 1:
        raise RuntimeError(
            "Identity conflict: aliases point to "
            f"different lifecycle entities: {candidates}"
        )

    if not entity_ids:
        return None, None

    entity_id = next(iter(entity_ids))
    entity = lt.get_entity(
        conn,
        entity_id,
    )

    if entity is None:
        raise RuntimeError(
            f"Resolved entity {entity_id} missing"
        )

    # Prefer strongest resolution label for reporting.
    for label in (
        "CURRENT_STABLE",
        "REPOST_OLD_STABLE",
        "APPLICATION_GROUP",
        "CURRENT_URL",
        "REPOST_OLD_URL",
    ):
        if candidates.get(label) == entity_id:
            return entity, label

    return entity, "ALIAS"


def ensure_current_aliases(
    conn,
    *,
    entity_id: int,
    item: dict,
    delta_record: dict | None,
    seen_at: str,
    sync_token: str,
) -> dict:
    added_or_touched = Counter()

    current_aliases = [
        (
            "STABLE_ITEM_KEY",
            item.get("stable_item_key"),
            item.get("source"),
        ),
        (
            "APPLICATION_GROUP_ID",
            item.get("application_group_id"),
            item.get("source"),
        ),
        (
            "URL",
            item.get("url"),
            item.get("source"),
        ),
    ]

    if (
        delta_record
        and nonempty(
            delta_record.get("identity_key")
        )
    ):
        current_aliases.append(
            (
                "DELTA_IDENTITY_KEY",
                delta_record.get("identity_key"),
                delta_record.get("source"),
            )
        )

    for identity_type, value, source in current_aliases:
        if not nonempty(value):
            continue

        lt.attach_alias(
            conn,
            entity_id=entity_id,
            identity_type=identity_type,
            identity_value=str(value),
            source=source,
            seen_at=seen_at,
            is_current=True,
            evidence={
                "sync_version":
                    LIFECYCLE_SYNC_VERSION,
                "sync_token":
                    sync_token,
            },
        )
        added_or_touched[
            identity_type
        ] += 1

    return dict(
        added_or_touched
    )


def ensure_repost_lineage(
    conn,
    *,
    entity_id: int,
    item: dict,
    delta_record: dict,
    seen_at: str,
    sync_token: str,
) -> bool:
    if (
        delta_record.get("delta_status")
        != "REPOSTED"
    ):
        return False

    old_key = delta_record.get(
        "reposted_from_identity_key"
    )
    if not nonempty(old_key):
        raise RuntimeError(
            "REPOSTED record missing "
            "reposted_from_identity_key"
        )

    current_key = item.get(
        "stable_item_key"
    )

    lt.attach_alias(
        conn,
        entity_id=entity_id,
        identity_type="STABLE_ITEM_KEY",
        identity_value=str(old_key),
        source=delta_record.get("source"),
        seen_at=seen_at,
        is_current=False,
        evidence={
            "sync_version":
                LIFECYCLE_SYNC_VERSION,
            "sync_token":
                sync_token,
            "repost_confidence":
                delta_record.get(
                    "repost_confidence"
                ),
        },
    )

    previous_url = delta_record.get(
        "previous_url"
    )
    if (
        nonempty(previous_url)
        and previous_url
        != item.get("url")
    ):
        lt.attach_alias(
            conn,
            entity_id=entity_id,
            identity_type="URL",
            identity_value=str(
                previous_url
            ),
            source=delta_record.get(
                "source"
            ),
            seen_at=seen_at,
            is_current=False,
            evidence={
                "sync_version":
                    LIFECYCLE_SYNC_VERSION,
                "sync_token":
                    sync_token,
            },
        )

    existing = conn.execute(
        """
        SELECT id
        FROM application_events
        WHERE
            entity_id = ?
            AND event_type = 'REPOSTED'
            AND stable_item_key = ?
            AND related_identity_value = ?
        LIMIT 1
        """,
        (
            entity_id,
            current_key,
            old_key,
        ),
    ).fetchone()

    if existing:
        return False

    lt.record_visibility_event(
        conn,
        entity_id=entity_id,
        event_type="REPOSTED",
        actor=SYNC_ACTOR,
        source=delta_record.get("source"),
        stable_item_key=current_key,
        related_identity_value=str(
            old_key
        ),
        details={
            "sync_version":
                LIFECYCLE_SYNC_VERSION,
            "sync_token":
                sync_token,
            "repost_confidence":
                delta_record.get(
                    "repost_confidence"
                ),
            "repost_reason":
                delta_record.get(
                    "repost_reason"
                ),
            "previous_url":
                previous_url,
            "current_url":
                delta_record.get(
                    "current_url"
                )
                or item.get("url"),
        },
        event_at=seen_at,
    )

    return True


def seen_event_exists(
    conn,
    *,
    entity_id: int,
    stable_item_key: str,
    sync_token: str,
) -> bool:
    row = conn.execute(
        """
        SELECT id
        FROM application_events
        WHERE
            entity_id = ?
            AND event_type = 'SEEN'
            AND stable_item_key = ?
            AND related_identity_value = ?
        LIMIT 1
        """,
        (
            entity_id,
            stable_item_key,
            sync_token,
        ),
    ).fetchone()
    return row is not None


def ensure_seen_event(
    conn,
    *,
    entity_id: int,
    item: dict,
    delta_record: dict | None,
    seen_at: str,
    sync_token: str,
) -> bool:
    stable_key = item.get(
        "stable_item_key"
    )

    if seen_event_exists(
        conn,
        entity_id=entity_id,
        stable_item_key=stable_key,
        sync_token=sync_token,
    ):
        return False

    lt.record_visibility_event(
        conn,
        entity_id=entity_id,
        event_type="SEEN",
        actor=SYNC_ACTOR,
        source=item.get("source"),
        stable_item_key=stable_key,
        related_identity_value=sync_token,
        details={
            "sync_version":
                LIFECYCLE_SYNC_VERSION,
            "delta_status":
                (
                    delta_record.get(
                        "delta_status"
                    )
                    if delta_record
                    else None
                ),
            "recommended_action":
                current_action(item),
        },
        event_at=seen_at,
    )
    return True


def update_entity_snapshot(
    conn,
    *,
    entity_id: int,
    item: dict,
    seen_at: str,
) -> None:
    conn.execute(
        """
        UPDATE application_entities
        SET
            application_group_id =
                COALESCE(?, application_group_id),
            title =
                COALESCE(NULLIF(?, ''), title),
            company =
                COALESCE(NULLIF(?, ''), company),
            location =
                COALESCE(NULLIF(?, ''), location),
            track =
                COALESCE(NULLIF(?, ''), track),
            updated_at = ?
        WHERE id = ?
        """,
        (
            item.get(
                "application_group_id"
            ),
            item.get("title") or "",
            item.get("company") or "",
            item.get("location") or "",
            item.get("track") or "",
            seen_at,
            entity_id,
        ),
    )


def status_event_exists(
    conn,
    *,
    entity_id: int,
    status: str,
    sync_token: str,
) -> bool:
    row = conn.execute(
        """
        SELECT id
        FROM application_events
        WHERE
            entity_id = ?
            AND event_type = 'STATUS'
            AND status = ?
            AND actor = ?
            AND related_identity_value = ?
        LIMIT 1
        """,
        (
            entity_id,
            status,
            SYNC_ACTOR,
            sync_token,
        ),
    ).fetchone()
    return row is not None


def advance_auto_status(
    conn,
    *,
    entity_id: int,
    item: dict,
    seen_at: str,
    sync_token: str,
) -> list[str]:
    state = lt.current_state(
        conn,
        entity_id,
    )
    current = (
        state.get("current_status")
        if state
        else None
    )

    target, _warning = (
        target_status_for_item(item)
    )

    if current in PROTECTED_STATUSES:
        return []

    current_rank = (
        AUTO_STATUS_RANK.get(
            current,
            0,
        )
        if current
        else 0
    )
    target_rank = AUTO_STATUS_RANK[
        target
    ]

    if current_rank >= target_rank:
        # Never downgrade.
        return []

    path = [
        status
        for status, rank
        in AUTO_STATUS_RANK.items()
        if (
            rank > current_rank
            and rank <= target_rank
        )
    ]
    path.sort(
        key=lambda status:
            AUTO_STATUS_RANK[status]
    )

    created = []

    for status in path:
        if status_event_exists(
            conn,
            entity_id=entity_id,
            status=status,
            sync_token=sync_token,
        ):
            continue

        lt.record_event(
            conn,
            entity_id=entity_id,
            event_type="STATUS",
            status=status,
            actor_type="SYSTEM",
            actor=SYNC_ACTOR,
            event_at=seen_at,
            source=item.get("source"),
            stable_item_key=item.get(
                "stable_item_key"
            ),
            related_identity_value=
                sync_token,
            details={
                "sync_version":
                    LIFECYCLE_SYNC_VERSION,
                "recommended_action":
                    current_action(item),
                "auto_advance_only":
                    True,
            },
        )
        created.append(status)

    return created


def create_new_entity(
    conn,
    *,
    item: dict,
    delta_record: dict | None,
    seen_at: str,
) -> dict:
    seed = (
        (
            delta_record.get(
                "reposted_from_identity_key"
            )
            if (
                delta_record
                and delta_record.get(
                    "delta_status"
                ) == "REPOSTED"
            )
            else None
        )
        or item.get(
            "application_group_id"
        )
        or item.get(
            "stable_item_key"
        )
    )

    if not nonempty(seed):
        raise RuntimeError(
            "Cannot create lifecycle entity "
            "without stable/group identity"
        )

    entity_id = lt.create_entity(
        conn,
        seed=str(seed),
        application_group_id=
            item.get(
                "application_group_id"
            ),
        title=item.get("title"),
        company=item.get("company"),
        location=item.get("location"),
        track=item.get("track"),
        metadata={
            "created_by":
                SYNC_ACTOR,
            "sync_version":
                LIFECYCLE_SYNC_VERSION,
        },
        created_at=seen_at,
    )

    entity = lt.get_entity(
        conn,
        entity_id,
    )
    if entity is None:
        raise RuntimeError(
            "New lifecycle entity missing"
        )

    return entity


def validate_current_item(
    item: dict,
) -> None:
    required = (
        "stable_item_key",
        "application_group_id",
        "url",
    )

    missing = [
        key
        for key in required
        if not nonempty(
            item.get(key)
        )
    ]

    if missing:
        raise ValueError(
            f"Final Pool item missing "
            f"required identities: {missing}"
        )


def analyze_sync(
    conn,
    *,
    final_items: list[dict],
    delta_items: list[dict],
) -> dict:
    by_identity, disappeared = (
        delta_map(delta_items)
    )

    counts = Counter()
    warnings = []
    resolutions = Counter()

    for item in final_items:
        validate_current_item(item)

        stable_key = item[
            "stable_item_key"
        ]
        delta_record = by_identity.get(
            stable_key
        )

        if delta_record is None:
            warnings.append(
                f"No Delta current record "
                f"for {stable_key}"
            )

        entity, method = (
            resolve_existing_entity(
                conn,
                item,
                delta_record,
            )
        )

        if entity is None:
            counts["new_entities"] += 1
        else:
            counts[
                "existing_entities"
            ] += 1
            resolutions[
                method or "UNKNOWN"
            ] += 1

            state = lt.current_state(
                conn,
                entity["id"],
            )
            current = (
                state.get(
                    "current_status"
                )
                if state
                else None
            )
            target, warning = (
                target_status_for_item(
                    item
                )
            )

            if warning:
                warnings.append(
                    f"{stable_key}: {warning}"
                )

            if (
                current
                in PROTECTED_STATUSES
            ):
                counts[
                    "protected_statuses"
                ] += 1
            else:
                current_rank = (
                    AUTO_STATUS_RANK.get(
                        current,
                        0,
                    )
                    if current
                    else 0
                )
                target_rank = (
                    AUTO_STATUS_RANK[
                        target
                    ]
                )

                if (
                    target_rank
                    > current_rank
                ):
                    counts[
                        "status_advances"
                    ] += 1
                elif (
                    target_rank
                    < current_rank
                ):
                    counts[
                        "prevented_downgrades"
                    ] += 1
                else:
                    counts[
                        "status_unchanged"
                    ] += 1

        if (
            delta_record
            and delta_record.get(
                "delta_status"
            ) == "REPOSTED"
        ):
            counts["reposted"] += 1

    counts["disappeared_records"] = (
        len(disappeared)
    )

    return {
        "sync_version":
            LIFECYCLE_SYNC_VERSION,
        "current_items":
            len(final_items),
        "delta_items":
            len(delta_items),
        "counts":
            dict(counts),
        "resolution_methods":
            dict(resolutions),
        "warnings":
            warnings,
        "rule_disappeared":
            "NO_STATUS_CHANGE",
    }


def sync_lifecycle(
    conn,
    *,
    final_items: list[dict],
    delta_items: list[dict],
    sync_token: str,
    event_at: str | None = None,
) -> dict:
    event_at = event_at or utc_now()

    by_identity, disappeared = (
        delta_map(delta_items)
    )

    result = Counter()
    status_created = Counter()
    resolutions = Counter()
    warnings = []

    # Pre-resolve every current item before starting writes.
    plans = []

    for item in final_items:
        validate_current_item(item)

        stable_key = item[
            "stable_item_key"
        ]
        delta_record = by_identity.get(
            stable_key
        )

        entity, method = (
            resolve_existing_entity(
                conn,
                item,
                delta_record,
            )
        )

        plans.append(
            (
                item,
                delta_record,
                entity,
                method,
            )
        )

    conn.execute(
        "BEGIN IMMEDIATE"
    )
    try:
        for (
            item,
            delta_record,
            entity,
            method,
        ) in plans:
            if entity is None:
                entity = create_new_entity(
                    conn,
                    item=item,
                    delta_record=
                        delta_record,
                    seen_at=event_at,
                )
                result[
                    "entities_created"
                ] += 1
                method = "NEW_ENTITY"
            else:
                result[
                    "entities_existing"
                ] += 1

            resolutions[
                method or "UNKNOWN"
            ] += 1

            entity_id = int(
                entity["id"]
            )

            update_entity_snapshot(
                conn,
                entity_id=entity_id,
                item=item,
                seen_at=event_at,
            )

            ensure_current_aliases(
                conn,
                entity_id=entity_id,
                item=item,
                delta_record=
                    delta_record,
                seen_at=event_at,
                sync_token=sync_token,
            )

            if (
                delta_record
                and delta_record.get(
                    "delta_status"
                ) == "REPOSTED"
            ):
                created = (
                    ensure_repost_lineage(
                        conn,
                        entity_id=
                            entity_id,
                        item=item,
                        delta_record=
                            delta_record,
                        seen_at=
                            event_at,
                        sync_token=
                            sync_token,
                    )
                )
                if created:
                    result[
                        "reposted_events_created"
                    ] += 1

            if ensure_seen_event(
                conn,
                entity_id=entity_id,
                item=item,
                delta_record=
                    delta_record,
                seen_at=event_at,
                sync_token=sync_token,
            ):
                result[
                    "seen_events_created"
                ] += 1

            state_before = (
                lt.current_state(
                    conn,
                    entity_id,
                )
            )
            current_before = (
                state_before.get(
                    "current_status"
                )
                if state_before
                else None
            )

            created_statuses = (
                advance_auto_status(
                    conn,
                    entity_id=
                        entity_id,
                    item=item,
                    seen_at=event_at,
                    sync_token=
                        sync_token,
                )
            )

            for status in (
                created_statuses
            ):
                status_created[
                    status
                ] += 1

            if created_statuses:
                result[
                    "entities_auto_advanced"
                ] += 1
            else:
                target, warning = (
                    target_status_for_item(
                        item
                    )
                )
                if warning:
                    warnings.append(
                        f"{item['stable_item_key']}: "
                        f"{warning}"
                    )

                if (
                    current_before
                    in PROTECTED_STATUSES
                ):
                    result[
                        "protected_statuses_preserved"
                    ] += 1
                else:
                    current_rank = (
                        AUTO_STATUS_RANK.get(
                            current_before,
                            0,
                        )
                        if current_before
                        else 0
                    )
                    target_rank = (
                        AUTO_STATUS_RANK[
                            target
                        ]
                    )
                    if (
                        current_rank
                        > target_rank
                    ):
                        result[
                            "downgrades_prevented"
                        ] += 1
                    else:
                        result[
                            "status_unchanged"
                        ] += 1

        # DISAPPEARED is intentionally visibility-only/no status mutation.
        result[
            "disappeared_records_ignored_for_status"
        ] = len(disappeared)

        # Critical invariants.
        auto_applied = conn.execute(
            """
            SELECT COUNT(*)
            FROM application_events
            WHERE
                event_type='STATUS'
                AND status='APPLIED'
                AND actor_type <> 'USER'
            """
        ).fetchone()[0]

        if auto_applied:
            raise RuntimeError(
                f"Lifecycle sync invariant violated: "
                f"{auto_applied} non-user APPLIED"
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    return {
        "sync_version":
            LIFECYCLE_SYNC_VERSION,
        "sync_token":
            sync_token,
        "current_items":
            len(final_items),
        "delta_items":
            len(delta_items),
        "counts":
            dict(result),
        "status_events_created":
            dict(status_created),
        "resolution_methods":
            dict(resolutions),
        "warnings":
            warnings,
        "disappeared_policy":
            "NO_STATUS_CHANGE",
        "applied_policy":
            "USER_ONLY",
    }


def sync_from_paths(
    conn,
    *,
    final_pool_path: str | Path,
    delta_path: str | Path,
    event_at: str | None = None,
) -> dict:
    final_pool_path = Path(
        final_pool_path
    )
    delta_path = Path(
        delta_path
    )

    final_items = get_items(
        load_json(
            final_pool_path
        )
    )
    delta_items = get_items(
        load_json(
            delta_path
        )
    )

    sync_token = (
        f"DELTA_ARTIFACT:"
        f"{delta_path.name}"
    )

    return sync_lifecycle(
        conn,
        final_items=final_items,
        delta_items=delta_items,
        sync_token=sync_token,
        event_at=event_at,
    )
