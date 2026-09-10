"""
LIFECYCLE TRACKER — STEP 8C BOOTSTRAP V1.0

Bootstraps the current Final Pool + Delta into the Lifecycle Tracker.

Conservative mapping:
- every Final Pool item -> DISCOVERED
- every item except DO_NOT_APPLY -> SHORTLISTED
- APPLY_NOW -> READY
- never creates DOCUMENTS_READY
- never creates APPLIED / INTERVIEW / OFFER / REJECTED / WITHDRAWN / CLOSED
- every current item -> SEEN visibility event
- REPOSTED Delta item -> REPOSTED event + previous identity aliases

No network.
No main.py.
No daily_run.py.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from applications import lifecycle_tracker as lt


BOOTSTRAP_VERSION = "1.0"

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "database" / "jobs.db"
LOG_DIR = ROOT / "exports" / "logs"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def latest_matching(pattern):
    if not LOG_DIR.exists():
        return None
    paths = [
        p for p in LOG_DIR.iterdir()
        if p.is_file() and fnmatch.fnmatch(p.name, pattern)
    ]
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def load_json(path):
    return json.loads(
        path.read_text(
            encoding="utf-8-sig",
            errors="strict",
        )
    )


def get_items(payload):
    if isinstance(payload, list):
        return payload

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
                return value

    raise ValueError("Cannot locate item list in payload")


def nonempty(value):
    return value is not None and value != ""


def duplicates(values):
    counter = Counter(x for x in values if nonempty(x))
    return sorted(k for k, v in counter.items() if v > 1)


def lifecycle_counts(conn):
    result = {}
    for name in (
        "application_entities",
        "application_events",
        "source_identity_aliases",
    ):
        result[name] = conn.execute(
            f'SELECT COUNT(*) FROM "{name}"'
        ).fetchone()[0]
    return result


def preflight(final_items, delta_items):
    errors = []

    if not final_items:
        errors.append("Final Pool is empty")

    stable_keys = [
        item.get("stable_item_key")
        for item in final_items
        if isinstance(item, dict)
    ]
    groups = [
        item.get("application_group_id")
        for item in final_items
        if isinstance(item, dict)
    ]
    urls = [
        item.get("url")
        for item in final_items
        if isinstance(item, dict)
    ]

    if len(stable_keys) != len(final_items):
        errors.append("Non-dict Final Pool item detected")

    missing_stable = [
        i for i, value in enumerate(stable_keys, start=1)
        if not nonempty(value)
    ]
    missing_group = [
        i for i, value in enumerate(groups, start=1)
        if not nonempty(value)
    ]
    missing_url = [
        i for i, value in enumerate(urls, start=1)
        if not nonempty(value)
    ]

    if missing_stable:
        errors.append(
            f"Missing stable_item_key at rows {missing_stable[:10]}"
        )
    if missing_group:
        errors.append(
            f"Missing application_group_id at rows {missing_group[:10]}"
        )
    if missing_url:
        errors.append(
            f"Missing URL at rows {missing_url[:10]}"
        )

    for label, values in (
        ("stable_item_key", stable_keys),
        ("application_group_id", groups),
        ("url", urls),
    ):
        dup = duplicates(values)
        if dup:
            errors.append(
                f"Duplicate {label}: {dup[:10]}"
            )

    delta_by_identity = {}
    reposts = []

    for record in delta_items:
        if not isinstance(record, dict):
            continue

        identity = record.get("identity_key")
        if nonempty(identity):
            if identity in delta_by_identity:
                errors.append(
                    f"Duplicate Delta identity_key: {identity}"
                )
            delta_by_identity[identity] = record

        if record.get("delta_status") == "REPOSTED":
            reposts.append(record)

    final_key_set = set(stable_keys)
    missing_delta = sorted(
        key for key in final_key_set
        if key not in delta_by_identity
    )
    if missing_delta:
        errors.append(
            f"Final Pool identities missing in Delta: {missing_delta[:10]}"
        )

    # Every REPOSTED must identify its previous stable identity.
    for record in reposts:
        previous = (
            record.get("reposted_from_identity_key")
            or record.get("previous_identity_key")
        )
        if not nonempty(previous):
            errors.append(
                "REPOSTED Delta record without previous identity key"
            )

    return {
        "ok": not errors,
        "errors": errors,
        "delta_by_identity": delta_by_identity,
        "reposts": reposts,
        "counts": {
            "final_items": len(final_items),
            "delta_items": len(delta_items),
            "reposted": len(reposts),
        },
    }


def bootstrap_complete(conn, final_items):
    counts = lifecycle_counts(conn)

    if counts["application_entities"] == 0:
        return False

    if counts["application_entities"] != len(final_items):
        return False

    for item in final_items:
        key = item["stable_item_key"]
        resolved = lt.resolve_entity_by_alias(
            conn,
            identity_type="STABLE_ITEM_KEY",
            identity_value=key,
        )
        if not resolved:
            return False

    return True


def create_status_chain(
    conn,
    *,
    entity_id,
    item,
    event_at,
    artifact_name,
):
    action = (
        item.get("recommended_action_v12")
        or item.get("recommended_action")
        or ""
    ).upper()

    common = {
        "entity_id": entity_id,
        "actor_type": "MIGRATION",
        "actor": "LIFECYCLE_STEP8C_BOOTSTRAP",
        "event_at": event_at,
        "source": item.get("source"),
        "stable_item_key": item.get("stable_item_key"),
        "details": {
            "bootstrap_version": BOOTSTRAP_VERSION,
            "source_artifact": artifact_name,
            "recommended_action": action,
        },
    }

    lt.record_event(
        conn,
        event_type="STATUS",
        status="DISCOVERED",
        **common,
    )

    if action != "DO_NOT_APPLY":
        lt.record_event(
            conn,
            event_type="STATUS",
            status="SHORTLISTED",
            **common,
        )

    if action == "APPLY_NOW":
        lt.record_event(
            conn,
            event_type="STATUS",
            status="READY",
            **common,
        )


def apply_bootstrap(
    *,
    db_path=DB_PATH,
    final_pool_path=None,
    delta_path=None,
    write_logs=True,
):
    final_pool_path = (
        Path(final_pool_path)
        if final_pool_path
        else latest_matching("final_application_pool_v12_[0-9]*.json")
    )
    delta_path = (
        Path(delta_path)
        if delta_path
        else latest_matching("delta_tracker_v1_[0-9]*.json")
    )

    if final_pool_path is None:
        raise RuntimeError("Current Final Pool not found")
    if delta_path is None:
        raise RuntimeError("Current Delta not found")
    if not Path(db_path).exists():
        raise RuntimeError(f"Database not found: {db_path}")

    final_payload = load_json(final_pool_path)
    delta_payload = load_json(delta_path)
    final_items = get_items(final_payload)
    delta_items = get_items(delta_payload)

    pf = preflight(final_items, delta_items)
    if not pf["ok"]:
        raise RuntimeError(
            "Bootstrap preflight failed: "
            + " | ".join(pf["errors"])
        )

    conn = lt.connect_database(db_path)

    try:
        lt.ensure_schema(conn)
        before = lifecycle_counts(conn)

        if bootstrap_complete(conn, final_items):
            return {
                "status": "ALREADY_BOOTSTRAPPED",
                "bootstrap_version": BOOTSTRAP_VERSION,
                "final_pool": str(final_pool_path),
                "delta": str(delta_path),
                "before_counts": before,
                "after_counts": before,
                "reposted_count": pf["counts"]["reposted"],
                "created_status_counts": {},
                "created_event_type_counts": {},
            }

        if any(before.values()):
            raise RuntimeError(
                "Lifecycle tables are partially/non-empty but bootstrap is "
                "not complete. Refusing to guess or duplicate events. "
                f"Counts={before}"
            )

        event_at = utc_now()
        status_counts = Counter()
        event_type_counts = Counter()

        conn.execute("BEGIN IMMEDIATE")
        try:
            entity_by_current_key = {}

            for item in final_items:
                current_key = item["stable_item_key"]
                delta_record = pf["delta_by_identity"][current_key]

                previous_key = (
                    delta_record.get("reposted_from_identity_key")
                    if delta_record.get("delta_status") == "REPOSTED"
                    else None
                )

                # Use old identity as lifecycle seed for known repost lineage.
                seed = previous_key or item["application_group_id"] or current_key

                entity_id = lt.create_entity(
                    conn,
                    seed=seed,
                    application_group_id=item.get("application_group_id"),
                    title=item.get("title"),
                    company=item.get("company"),
                    location=item.get("location"),
                    track=item.get("track"),
                    metadata={
                        "bootstrap_version": BOOTSTRAP_VERSION,
                        "final_pool_source": final_pool_path.name,
                        "delta_source": delta_path.name,
                        "current_stable_item_key": current_key,
                    },
                    created_at=event_at,
                )
                entity_by_current_key[current_key] = entity_id

                # Durable aliases for current identity.
                lt.attach_alias(
                    conn,
                    entity_id=entity_id,
                    identity_type="STABLE_ITEM_KEY",
                    identity_value=current_key,
                    source=item.get("source"),
                    seen_at=event_at,
                    evidence={"origin": "FINAL_POOL_STEP8C"},
                )
                lt.attach_alias(
                    conn,
                    entity_id=entity_id,
                    identity_type="APPLICATION_GROUP_ID",
                    identity_value=item["application_group_id"],
                    source=item.get("source"),
                    seen_at=event_at,
                    evidence={"origin": "FINAL_POOL_STEP8C"},
                )
                lt.attach_alias(
                    conn,
                    entity_id=entity_id,
                    identity_type="URL",
                    identity_value=item["url"],
                    source=item.get("source"),
                    seen_at=event_at,
                    evidence={"origin": "FINAL_POOL_STEP8C"},
                )
                lt.attach_alias(
                    conn,
                    entity_id=entity_id,
                    identity_type="DELTA_IDENTITY_KEY",
                    identity_value=delta_record["identity_key"],
                    source=delta_record.get("source"),
                    seen_at=event_at,
                    evidence={
                        "identity_method": delta_record.get("identity_method"),
                        "origin": "DELTA_STEP8C",
                    },
                )

                create_status_chain(
                    conn,
                    entity_id=entity_id,
                    item=item,
                    event_at=event_at,
                    artifact_name=final_pool_path.name,
                )

                action = (
                    item.get("recommended_action_v12")
                    or item.get("recommended_action")
                    or ""
                ).upper()
                status_counts["DISCOVERED"] += 1
                event_type_counts["STATUS"] += 1

                if action != "DO_NOT_APPLY":
                    status_counts["SHORTLISTED"] += 1
                    event_type_counts["STATUS"] += 1

                if action == "APPLY_NOW":
                    status_counts["READY"] += 1
                    event_type_counts["STATUS"] += 1

                lt.record_visibility_event(
                    conn,
                    entity_id=entity_id,
                    event_type="SEEN",
                    actor="LIFECYCLE_STEP8C_BOOTSTRAP",
                    source=item.get("source"),
                    stable_item_key=current_key,
                    details={
                        "bootstrap_version": BOOTSTRAP_VERSION,
                        "delta_status": delta_record.get("delta_status"),
                        "source_artifact": delta_path.name,
                    },
                    event_at=event_at,
                )
                event_type_counts["SEEN"] += 1

                # Repost lineage stays on exactly the same lifecycle entity.
                if delta_record.get("delta_status") == "REPOSTED":
                    old_key = delta_record.get("reposted_from_identity_key")
                    if not old_key:
                        raise RuntimeError(
                            f"REPOSTED record {current_key} lacks old identity"
                        )

                    lt.attach_alias(
                        conn,
                        entity_id=entity_id,
                        identity_type="STABLE_ITEM_KEY",
                        identity_value=old_key,
                        source=delta_record.get("source"),
                        seen_at=event_at,
                        is_current=False,
                        evidence={
                            "origin": "DELTA_REPOST_STEP8C",
                            "repost_confidence":
                                delta_record.get("repost_confidence"),
                        },
                    )

                    previous_url = delta_record.get("previous_url")
                    if nonempty(previous_url) and previous_url != item["url"]:
                        lt.attach_alias(
                            conn,
                            entity_id=entity_id,
                            identity_type="URL",
                            identity_value=previous_url,
                            source=delta_record.get("source"),
                            seen_at=event_at,
                            is_current=False,
                            evidence={
                                "origin": "DELTA_REPOST_STEP8C",
                            },
                        )

                    lt.record_visibility_event(
                        conn,
                        entity_id=entity_id,
                        event_type="REPOSTED",
                        actor="LIFECYCLE_STEP8C_BOOTSTRAP",
                        source=delta_record.get("source"),
                        stable_item_key=current_key,
                        related_identity_value=old_key,
                        details={
                            "bootstrap_version": BOOTSTRAP_VERSION,
                            "repost_confidence":
                                delta_record.get("repost_confidence"),
                            "repost_reason":
                                delta_record.get("repost_reason"),
                            "previous_url":
                                delta_record.get("previous_url"),
                            "current_url":
                                delta_record.get("current_url")
                                or delta_record.get("url"),
                        },
                        event_at=event_at,
                    )
                    event_type_counts["REPOSTED"] += 1

            # Safety invariants before commit.
            after = lifecycle_counts(conn)

            if after["application_entities"] != len(final_items):
                raise RuntimeError(
                    "Entity count mismatch before commit: "
                    f"{after['application_entities']} != {len(final_items)}"
                )

            applied = conn.execute(
                """
                SELECT COUNT(*)
                FROM application_events
                WHERE event_type='STATUS' AND status='APPLIED'
                """
            ).fetchone()[0]
            if applied != 0:
                raise RuntimeError(
                    f"Bootstrap must create 0 APPLIED events, got {applied}"
                )

            closed = conn.execute(
                """
                SELECT COUNT(*)
                FROM application_events
                WHERE event_type='STATUS' AND status='CLOSED'
                """
            ).fetchone()[0]
            if closed != 0:
                raise RuntimeError(
                    f"Bootstrap must create 0 CLOSED events, got {closed}"
                )

            # Every current stable key must resolve.
            for key, expected_entity_id in entity_by_current_key.items():
                resolved = lt.resolve_entity_by_alias(
                    conn,
                    identity_type="STABLE_ITEM_KEY",
                    identity_value=key,
                )
                if not resolved or resolved["id"] != expected_entity_id:
                    raise RuntimeError(
                        f"Alias resolution mismatch for {key}"
                    )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        after = lifecycle_counts(conn)

        result = {
            "status": "BOOTSTRAPPED",
            "bootstrap_version": BOOTSTRAP_VERSION,
            "final_pool": str(final_pool_path),
            "delta": str(delta_path),
            "before_counts": before,
            "after_counts": after,
            "final_item_count": len(final_items),
            "delta_item_count": len(delta_items),
            "reposted_count": pf["counts"]["reposted"],
            "created_status_counts": dict(status_counts),
            "created_event_type_counts": dict(event_type_counts),
        }

    finally:
        conn.close()

    if write_logs:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = (
            LOG_DIR
            / f"lifecycle_step8c_bootstrap_{stamp}.json"
        )
        txt_path = (
            LOG_DIR
            / f"lifecycle_step8c_bootstrap_{stamp}.txt"
        )

        json_path.write_text(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        txt_path.write_text(
            "\n".join([
                "LIFECYCLE TRACKER STEP 8C - BOOTSTRAP",
                "=" * 100,
                f"Status      : {result['status']}",
                f"Final items : {result.get('final_item_count')}",
                f"Reposted    : {result['reposted_count']}",
                f"Before      : {result['before_counts']}",
                f"After       : {result['after_counts']}",
                f"Statuses    : {result['created_status_counts']}",
                f"Events      : {result['created_event_type_counts']}",
                "APPLIED created: 0",
                "CLOSED created : 0",
            ]),
            encoding="utf-8",
        )

        result["json_log"] = str(json_path)
        result["txt_log"] = str(txt_path)

    return result


def check_bootstrap():
    final_pool_path = latest_matching(
        "final_application_pool_v12_[0-9]*.json"
    )
    delta_path = latest_matching(
        "delta_tracker_v1_[0-9]*.json"
    )

    if final_pool_path is None or delta_path is None:
        raise SystemExit(
            "Final Pool or Delta artifact missing"
        )

    final_items = get_items(load_json(final_pool_path))
    delta_items = get_items(load_json(delta_path))
    pf = preflight(final_items, delta_items)

    conn = lt.connect_database(DB_PATH)
    try:
        lt.ensure_schema(conn)
        counts = lifecycle_counts(conn)
    finally:
        conn.close()

    print("Final Pool :", final_pool_path)
    print("Delta      :", delta_path)
    print("Final items:", len(final_items))
    print("Delta items:", len(delta_items))
    print("REPOSTED   :", pf["counts"]["reposted"])
    print("Preflight  :", "OK" if pf["ok"] else "FAIL")
    print("Lifecycle  :", counts)

    if not pf["ok"]:
        for error in pf["errors"]:
            print(" -", error)
        raise SystemExit(1)

    if any(counts.values()):
        print(
            "Lifecycle tables are not empty. --apply will only no-op "
            "if the bootstrap is already complete; otherwise it will refuse."
        )

    print("CHECK OK.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.apply:
        result = apply_bootstrap()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        check_bootstrap()


if __name__ == "__main__":
    main()
