"""
LIFECYCLE TRACKER — STEP 8A INVENTORY

READ ONLY.

Usage:
    python lifecycle_step8a_inventory.py

Reads:
- database/jobs.db schema and counts
- latest Final Pool V1.2
- latest Delta Tracker V1.x
- exports/applications directory structure

Writes only:
- exports/logs/lifecycle_step8a_inventory_<timestamp>.json
- exports/logs/lifecycle_step8a_inventory_<timestamp>.txt

No network.
No DB writes.
No main.py.
No daily_run.py.
"""

from __future__ import annotations

import fnmatch
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "database" / "jobs.db"
LOG_DIR = ROOT / "exports" / "logs"
APPLICATIONS_DIR = ROOT / "exports" / "applications"


def latest_matching(directory: Path, pattern: str):
    if not directory.exists():
        return None

    items = [
        path
        for path in directory.iterdir()
        if path.is_file() and fnmatch.fnmatch(path.name, pattern)
    ]
    return max(items, key=lambda p: p.stat().st_mtime) if items else None


def load_json(path: Path | None):
    if path is None or not path.exists():
        return None

    return json.loads(
        path.read_text(
            encoding="utf-8-sig",
            errors="strict",
        )
    )


def sqlite_inventory():
    result = {
        "db_exists": DB_PATH.exists(),
        "db_path": str(DB_PATH),
        "db_bytes": DB_PATH.stat().st_size if DB_PATH.exists() else None,
        "tables": {},
        "views": [],
        "triggers": [],
    }

    if not DB_PATH.exists():
        return result

    # Critical: immutable read-only URI. No accidental DB writes.
    uri = DB_PATH.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(
        uri,
        uri=True,
    )

    try:
        objects = conn.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()

        for obj_type, name, table_name, sql in objects:
            if obj_type == "table":
                columns = [
                    {
                        "cid": row[0],
                        "name": row[1],
                        "type": row[2],
                        "notnull": bool(row[3]),
                        "default": row[4],
                        "pk": row[5],
                    }
                    for row in conn.execute(
                        f'PRAGMA table_info("{name}")'
                    ).fetchall()
                ]

                indexes = []
                for row in conn.execute(
                    f'PRAGMA index_list("{name}")'
                ).fetchall():
                    index_name = row[1]
                    index_cols = [
                        x[2]
                        for x in conn.execute(
                            f'PRAGMA index_info("{index_name}")'
                        ).fetchall()
                    ]
                    indexes.append({
                        "name": index_name,
                        "unique": bool(row[2]),
                        "origin": row[3],
                        "partial": bool(row[4]),
                        "columns": index_cols,
                    })

                foreign_keys = [
                    {
                        "id": row[0],
                        "seq": row[1],
                        "table": row[2],
                        "from": row[3],
                        "to": row[4],
                        "on_update": row[5],
                        "on_delete": row[6],
                        "match": row[7],
                    }
                    for row in conn.execute(
                        f'PRAGMA foreign_key_list("{name}")'
                    ).fetchall()
                ]

                try:
                    count = conn.execute(
                        f'SELECT COUNT(*) FROM "{name}"'
                    ).fetchone()[0]
                except Exception:
                    count = None

                result["tables"][name] = {
                    "row_count": count,
                    "columns": columns,
                    "indexes": indexes,
                    "foreign_keys": foreign_keys,
                    "create_sql": sql,
                }

            elif obj_type == "view":
                result["views"].append({
                    "name": name,
                    "sql": sql,
                })

            elif obj_type == "trigger":
                result["triggers"].append({
                    "name": name,
                    "table": table_name,
                    "sql": sql,
                })

    finally:
        conn.close()

    return result


def get_items(payload):
    if payload is None:
        return []

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

    return []


def summarize_items(items):
    if not items:
        return {
            "count": 0,
            "union_keys": [],
            "key_presence": {},
            "sample_identity": {},
        }

    union = set()
    presence = Counter()

    identity_candidates = (
        "stable_item_key",
        "application_group_id",
        "source",
        "origin_source",
        "external_id",
        "url",
        "title",
        "company",
        "location",
        "recommended_action_v12",
        "recommended_action",
        "delta_status",
        "previous_identity_key",
        "identity_key",
        "identity_method",
    )

    for item in items:
        if not isinstance(item, dict):
            continue

        union.update(item.keys())

        for key in identity_candidates:
            if key in item and item.get(key) not in (None, "", [], {}):
                presence[key] += 1

    first = next(
        (x for x in items if isinstance(x, dict)),
        {},
    )

    sample_identity = {
        key: first.get(key)
        for key in identity_candidates
        if key in first
    }

    return {
        "count": len(items),
        "union_keys": sorted(union),
        "key_presence": dict(sorted(presence.items())),
        "sample_identity": sample_identity,
    }


def application_dir_inventory():
    result = {
        "exists": APPLICATIONS_DIR.exists(),
        "path": str(APPLICATIONS_DIR),
        "folder_count": 0,
        "files_by_name": {},
        "folders": [],
    }

    if not APPLICATIONS_DIR.exists():
        return result

    folders = [
        p for p in APPLICATIONS_DIR.iterdir()
        if p.is_dir()
    ]
    result["folder_count"] = len(folders)

    file_name_counts = Counter()

    for folder in sorted(folders):
        files = sorted(
            p.name
            for p in folder.iterdir()
            if p.is_file()
        )
        file_name_counts.update(files)

        lifecycle_like = [
            name
            for name in files
            if any(
                token in name.casefold()
                for token in (
                    "status",
                    "lifecycle",
                    "applied",
                    "event",
                    "history",
                )
            )
        ]

        result["folders"].append({
            "folder_name": folder.name,
            "file_count": len(files),
            "files": files,
            "lifecycle_like_files": lifecycle_like,
        })

    result["files_by_name"] = dict(
        sorted(file_name_counts.items())
    )

    return result


def main():
    print("=" * 100)
    print("LIFECYCLE TRACKER - STEP 8A INVENTORY")
    print("=" * 100)
    print("Mode : READ_ONLY")
    print()

    final_pool_path = latest_matching(
        LOG_DIR,
        "final_application_pool_v12_[0-9]*.json",
    )
    delta_path = latest_matching(
        LOG_DIR,
        "delta_tracker_v1_[0-9]*.json",
    )

    final_pool = load_json(final_pool_path)
    delta = load_json(delta_path)

    final_items = get_items(final_pool)
    delta_items = get_items(delta)

    db = sqlite_inventory()
    applications = application_dir_inventory()

    lifecycle_table_hints = [
        name
        for name in db["tables"]
        if any(
            token in name.casefold()
            for token in (
                "application",
                "lifecycle",
                "event",
                "status",
                "alias",
            )
        )
    ]

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "READ_ONLY",
        "database": db,
        "existing_lifecycle_table_hints": lifecycle_table_hints,
        "final_pool": {
            "path": str(final_pool_path) if final_pool_path else None,
            **summarize_items(final_items),
        },
        "delta": {
            "path": str(delta_path) if delta_path else None,
            **summarize_items(delta_items),
        },
        "applications_directory": applications,
        "design_questions": {
            "existing_application_or_event_tables":
                lifecycle_table_hints,
            "stable_item_key_available_in_final_pool":
                sum(
                    1 for x in final_items
                    if isinstance(x, dict)
                    and x.get("stable_item_key")
                ),
            "application_group_id_available_in_final_pool":
                sum(
                    1 for x in final_items
                    if isinstance(x, dict)
                    and x.get("application_group_id")
                ),
            "delta_identity_key_available":
                sum(
                    1 for x in delta_items
                    if isinstance(x, dict)
                    and x.get("identity_key")
                ),
            "delta_reposted_count":
                sum(
                    1 for x in delta_items
                    if isinstance(x, dict)
                    and x.get("delta_status") == "REPOSTED"
                ),
        },
    }

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = (
        LOG_DIR
        / f"lifecycle_step8a_inventory_{stamp}.json"
    )
    txt_path = (
        LOG_DIR
        / f"lifecycle_step8a_inventory_{stamp}.txt"
    )

    json_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        "LIFECYCLE TRACKER - STEP 8A INVENTORY",
        "=" * 100,
        "Mode : READ_ONLY",
        "",
        f"DB exists              : {db['db_exists']}",
        f"DB tables              : {len(db['tables'])}",
        f"Lifecycle table hints  : {lifecycle_table_hints}",
        f"Final Pool             : {final_pool_path}",
        f"Final Pool items       : {len(final_items)}",
        (
            "Final stable_item_key  : "
            f"{payload['design_questions']['stable_item_key_available_in_final_pool']}"
        ),
        (
            "Final app_group_id     : "
            f"{payload['design_questions']['application_group_id_available_in_final_pool']}"
        ),
        f"Delta                  : {delta_path}",
        f"Delta items            : {len(delta_items)}",
        (
            "Delta identity_key     : "
            f"{payload['design_questions']['delta_identity_key_available']}"
        ),
        (
            "Delta REPOSTED         : "
            f"{payload['design_questions']['delta_reposted_count']}"
        ),
        f"Application folders    : {applications['folder_count']}",
        "",
        "DB TABLES",
        "---------",
    ]

    for name, info in db["tables"].items():
        columns = ", ".join(
            x["name"]
            for x in info["columns"]
        )
        lines.append(
            f"- {name}: rows={info['row_count']} | {columns}"
        )

    lines.extend([
        "",
        "FINAL POOL KEY PRESENCE",
        "-----------------------",
    ])

    for key, count in payload["final_pool"]["key_presence"].items():
        lines.append(f"- {key}: {count}")

    lines.extend([
        "",
        "DELTA KEY PRESENCE",
        "------------------",
    ])

    for key, count in payload["delta"]["key_presence"].items():
        lines.append(f"- {key}: {count}")

    txt_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print(f"DB tables            : {len(db['tables'])}")
    print(f"Lifecycle table hints: {lifecycle_table_hints}")
    print(f"Final Pool items     : {len(final_items)}")
    print(f"Delta items          : {len(delta_items)}")
    print(f"Application folders  : {applications['folder_count']}")
    print()
    print("JSON :", json_path)
    print("TXT  :", txt_path)
    print()
    print("Aucune ecriture DB. Aucun reseau.")


if __name__ == "__main__":
    main()
