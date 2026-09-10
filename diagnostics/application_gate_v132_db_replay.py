"""
APPLICATION GATE V1.3.2 - DB REPLAY SANS RECOLLECTE

Objectif
========
Le MAIN V10.4 a produit un export Gate V1.3.1.
Le code Gate V1.3.2 a ensuite été validé, sans rerun complet de MAIN.

Ce diagnostic :
- lit le dernier application_gate_v1_*.json ;
- récupère la description canonical correspondante dans jobs.db ;
- reconstruit 575 JobOffer légers ;
- réévalue avec matching.application_gate_v13 (V1.3.2 installé) ;
- reconstruit la Queue avec matching.application_queue_v12 ;
- écrit de NOUVEAUX exports Gate + Queue standards dans exports/logs ;
- NE collecte aucune offre ;
- NE modifie aucune ligne SQLite.

Usage
=====
python -m diagnostics.application_gate_v132_db_replay
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from database.db import get_connection
from matching.application_gate_v13 import (
    GATE_VERSION,
    apply_application_gate,
    export_application_gate,
    gate_summary,
)
from matching.application_queue_v12 import (
    QUEUE_VERSION,
    build_application_queue_from_gate_payload,
    export_application_queue,
    queue_summary,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "exports" / "logs"


def clean_text(value):
    return "" if value is None else str(value).strip()


def latest_file(directory, pattern):
    paths = list(Path(directory).glob(pattern))
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_mtime)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def payload_gate_version(payload):
    versions = {
        clean_text((row.get("gate") or {}).get("gate_version"))
        for row in payload
        if isinstance(row, dict)
    }
    versions.discard("")
    if not versions:
        return "UNKNOWN"
    if len(versions) == 1:
        return next(iter(versions))
    return "MIXED:" + ",".join(sorted(versions))


def canonical_row(connection, canonical_job_id):
    return connection.execute(
        """
        SELECT
            id,
            title,
            company,
            location,
            description,
            url,
            contract_type,
            language
        FROM canonical_jobs
        WHERE id = ?
        """,
        (int(canonical_job_id),),
    ).fetchone()


def row_value(row, key, default=""):
    if row is None:
        return default
    try:
        return row[key]
    except Exception:
        return default


def build_job(old_row, canonical):
    old_gate = old_row.get("gate") or {}

    return SimpleNamespace(
        canonical_job_id=old_row.get("canonical_job_id"),
        title=clean_text(row_value(canonical, "title"))
              or clean_text(old_row.get("title")),
        company=clean_text(row_value(canonical, "company"))
                or clean_text(old_row.get("company")),
        location=clean_text(row_value(canonical, "location"))
                 or clean_text(old_row.get("location")),
        description=clean_text(row_value(canonical, "description")),
        detail_matching_text="",
        url=clean_text(row_value(canonical, "url"))
            or clean_text(old_row.get("url")),
        source=clean_text(old_row.get("source")),
        origin_source=clean_text(old_row.get("origin_source")),
        contract_type=clean_text(row_value(canonical, "contract_type")),
        language=clean_text(row_value(canonical, "language")),
        experience_requirement="",
        degree_requirement="",
        restriction="",
        source_eligibility_status=clean_text(
            old_gate.get("source_eligibility_status")
        ) or "ELIGIBLE",
        source_eligibility_reason=old_gate.get(
            "source_eligibility_reason"
        ),
    )


def build_match(old_row):
    old_gate = old_row.get("gate") or {}
    return {
        "score": float(old_row.get("match_score") or 0),
        "best_family": clean_text(old_row.get("best_family")),
        "confidence_label": clean_text(old_row.get("confidence")),
        "provisional": bool(old_gate.get("provisional", False)),
    }


def main():
    print("=" * 92)
    print("APPLICATION GATE V1.3.2 - DB REPLAY SANS RECOLLECTE")
    print("=" * 92)
    print()
    print("Gate installé  :", GATE_VERSION)
    print("Queue installée:", QUEUE_VERSION)

    if GATE_VERSION != "1.3.2":
        raise SystemExit(
            f"❌ Gate installé inattendu : {GATE_VERSION}. Attendu 1.3.2."
        )

    if QUEUE_VERSION != "1.2":
        raise SystemExit(
            f"❌ Queue installée inattendue : {QUEUE_VERSION}. Attendu 1.2."
        )

    gate_path = latest_file(LOG_DIR, "application_gate_v1_*.json")
    if gate_path is None:
        raise SystemExit("❌ Aucun application_gate_v1_*.json trouvé.")

    old_payload = load_json(gate_path)
    old_version = payload_gate_version(old_payload)

    print("Gate source    :", gate_path)
    print("Version source :", old_version)
    print("Lignes source  :", len(old_payload))
    print()

    # Si le dernier Gate est déjà 1.3.2, le replay est idempotent mais
    # on l'autorise pour reconstruire une Queue V1.2 propre.
    connection = get_connection()

    scored_jobs = []
    missing_canonical = []
    empty_descriptions = []

    try:
        for old_row in old_payload:
            canonical_id = old_row.get("canonical_job_id")
            if canonical_id is None:
                missing_canonical.append(
                    (canonical_id, old_row.get("title"), old_row.get("url"))
                )
                continue

            canonical = canonical_row(connection, canonical_id)
            if canonical is None:
                missing_canonical.append(
                    (canonical_id, old_row.get("title"), old_row.get("url"))
                )
                continue

            description = clean_text(row_value(canonical, "description"))
            if not description:
                empty_descriptions.append(
                    (canonical_id, old_row.get("title"), old_row.get("url"))
                )

            job = build_job(old_row, canonical)
            match_result = build_match(old_row)
            scored_jobs.append((job, match_result))
    finally:
        connection.close()

    print("Canonical trouvés      :", len(scored_jobs))
    print("Canonical manquants    :", len(missing_canonical))
    print("Descriptions vides     :", len(empty_descriptions))

    if missing_canonical:
        print()
        print("❌ Replay bloqué : au moins un canonical_job_id est introuvable.")
        for row in missing_canonical[:10]:
            print(" -", row)
        raise SystemExit(1)

    if len(scored_jobs) != len(old_payload):
        raise SystemExit(
            "❌ Nombre de jobs reconstruits différent de l'export source."
        )

    gated = apply_application_gate(scored_jobs)
    gate_result = export_application_gate(gated, PROJECT_ROOT)
    summary = gate_summary(gated)

    # Retrouve le JSON standard nouvellement exporté.
    new_gate_path = gate_result["json_path"]
    new_payload = load_json(new_gate_path)

    queue_items = build_application_queue_from_gate_payload(new_payload)
    queue_result = export_application_queue(queue_items, PROJECT_ROOT)
    qsummary = queue_summary(queue_items)

    print()
    print("=" * 92)
    print("RÉSULTAT REPLAY")
    print("=" * 92)
    print("Gate :", new_gate_path)
    print("Queue:", queue_result["json_path"])
    print()
    print("Gate APPLY   :", summary["APPLY"])
    print("Gate STRETCH :", summary["STRETCH"])
    print("Gate VERIFY  :", summary["VERIFY"])
    print("Gate REJECT  :", summary["REJECT"])
    print()
    print("READY_APPLY    :", qsummary["READY_APPLY"])
    print("READY_STRETCH  :", qsummary["READY_STRETCH"])
    print("VERIFY_FIRST   :", qsummary["VERIFY_FIRST"])
    print("HOLD_DUPLICATE :", qsummary["HOLD_DUPLICATE"])
    print("EXCLUDED       :", qsummary["EXCLUDED"])
    print("Zone prioritaire APPLY :", qsummary["preferred_ready_apply"])

    # Garde-fous Beveren et version.
    beveren_preferred = [
        item for item in queue_items
        if item.get("preferred_location")
        and "beveren" in clean_text(item.get("location")).lower()
    ]

    replay_gate_versions = {
        clean_text((row.get("gate") or {}).get("gate_version"))
        for row in new_payload
    }

    print()
    print("Gate versions export :", sorted(replay_gate_versions))
    print("Beveren prioritaire  :", len(beveren_preferred))

    # Rapport des changements de statut Gate.
    old_by_url = {
        clean_text(row.get("url")): (row.get("gate") or {}).get("status")
        for row in old_payload
    }
    new_by_url = {
        clean_text(row.get("url")): (row.get("gate") or {}).get("status")
        for row in new_payload
    }

    transitions = Counter()
    changed = []

    for url, old_status in old_by_url.items():
        new_status = new_by_url.get(url)
        transitions[(old_status, new_status)] += 1
        if old_status != new_status:
            changed.append((old_status, new_status, url))

    print()
    print("Transitions Gate changées :", len(changed))
    for (old_status, new_status), count in sorted(transitions.items()):
        if old_status != new_status:
            print(f"  {old_status} -> {new_status} : {count}")

    if replay_gate_versions != {GATE_VERSION}:
        raise SystemExit("❌ Export Gate n'est pas uniformément en V1.3.2.")

    if beveren_preferred:
        raise SystemExit("❌ Beveren est encore marqué prioritaire.")

    print()
    print("✅ REPLAY GATE V1.3.2 + QUEUE V1.2 VALIDÉ.")
    print("✅ Aucune recollecte réseau.")
    print("✅ Aucune modification de la base SQLite.")


if __name__ == "__main__":
    main()
