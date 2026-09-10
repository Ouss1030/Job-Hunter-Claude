"""
JOB HUNTER BELGIUM
DELTA TRACKER - VERSION 1.1

Compare deux Final Application Pool V1.2.

Statuts
-------
NEW
    Présent dans le pool actuel, absent du précédent et jamais vu dans un
    ancien Final Pool V1.2 disponible.

REACTIVATED
    Présent dans le pool actuel, absent du précédent, mais déjà vu dans un
    Final Pool V1.2 plus ancien.

UPDATED
    Présent dans les deux pools avec le même stable_item_key, mais le contenu
    utile de l'offre et/ou la décision finale a changé.

UNCHANGED
    Présent dans les deux pools sans modification utile.

DISAPPEARED
    Présent dans le pool précédent, absent du pool actuel.

IMPORTANT
---------
DISAPPEARED signifie uniquement "sorti du Final Pool".
Cela ne prouve PAS que l'annonce a été retirée d'Internet.

Le tracker ne modifie :
- ni la DB ;
- ni les statuts de candidature ;
- ni Gate / Queue / Recheck / Final Pool ;
- ni APPLIED.

Usage
-----
python -m applications.delta_tracker

Options :
python -m applications.delta_tracker --current PATH --previous PATH
python -m applications.delta_tracker --dry-run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from diagnostics.version_support import at_least


DELTA_TRACKER_VERSION = "1.1"

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "exports" / "logs"

POOL_PATTERN = "final_application_pool_v12_*.json"

CURRENT_STATUSES = {"NEW", "REACTIVATED", "REPOSTED", "UPDATED", "UNCHANGED"}
ALL_STATUSES = CURRENT_STATUSES | {"DISAPPEARED"}

CONTENT_FIELDS = (
    "title",
    "company",
    "location",
    "url",
    "description",
)

DECISION_FIELDS = (
    "recommended_action_v12",
    "priority_v12",
    "track",
    "guard_level",
    "recheck_status",
    "preferred_location",
    "off_domain_title",
)

LIST_DECISION_FIELDS = (
    "guard_flags",
    "warnings",
)


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_text(value):
    text = unicodedata.normalize("NFKD", clean_text(value))
    text = "".join(
        ch for ch in text
        if not unicodedata.combining(ch)
    )
    return text.lower()


def normalized_url(value):
    """
    Conserve l'URL métier, retire uniquement les paramètres de tracking
    manifestement non identitaires.
    """
    raw = clean_text(value)
    if not raw:
        return ""

    try:
        parts = urlsplit(raw)
        drop = {
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "gclid",
            "fbclid",
        }
        query = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in drop
        ]
        return urlunsplit((
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            urlencode(query, doseq=True),
            "",
        ))
    except Exception:
        return raw


def sha256_text(value):
    return hashlib.sha256(
        str(value).encode("utf-8")
    ).hexdigest()


def canonical_scalar(value):
    if isinstance(value, bool):
        return bool(value)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    return normalize_text(value)


def canonical_list(value):
    if not value:
        return []
    if not isinstance(value, list):
        value = [value]
    return sorted(
        {
            normalize_text(v)
            for v in value
            if clean_text(v)
        }
    )


def identity_key(item):
    """
    Priorité absolue au stable_item_key produit par la Queue.

    Fallback conservateur :
    - URL exacte normalisée ;
    - sinon title + company + location.

    Le fallback ne fusionne jamais deux sources différentes si l'URL manque.
    """
    stable = clean_text(item.get("stable_item_key"))
    if stable:
        return stable, "STABLE_ITEM_KEY"

    url = normalized_url(item.get("url"))
    if url:
        return "URL_" + sha256_text(url)[:24], "URL_FALLBACK"

    payload = "|".join([
        normalize_text(item.get("source")),
        normalize_text(item.get("title")),
        normalize_text(item.get("company")),
        normalize_text(item.get("location")),
    ])
    return "FALLBACK_" + sha256_text(payload)[:24], "TEXT_FALLBACK"


def content_payload(item):
    payload = {}
    for field in CONTENT_FIELDS:
        if field == "url":
            payload[field] = normalized_url(item.get(field))
        else:
            payload[field] = normalize_text(item.get(field))
    return payload


def decision_payload(item):
    payload = {
        field: canonical_scalar(item.get(field))
        for field in DECISION_FIELDS
    }
    for field in LIST_DECISION_FIELDS:
        payload[field] = canonical_list(item.get(field))
    return payload


def fingerprint(payload):
    return sha256_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def pool_timestamp(payload, path):
    generated = clean_text(payload.get("generated_at"))
    if generated:
        try:
            return datetime.fromisoformat(generated)
        except ValueError:
            pass

    match = re.search(r"(\d{8}_\d{6})", Path(path).name)
    if match:
        return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")

    return datetime.fromtimestamp(Path(path).stat().st_mtime)


def load_pool(path):
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise RuntimeError(f"{path}: Final Pool JSON doit être un objet.")

    if not at_least(str(payload.get("pool_version")), "1.2"):
        raise RuntimeError(
            f"{path}: pool_version={payload.get('pool_version')!r}, attendu au moins 1.2."
        )

    pool = payload.get("pool")
    if not isinstance(pool, list):
        raise RuntimeError(f"{path}: champ pool invalide.")

    prepared = []
    seen_keys = set()

    for item in pool:
        if not isinstance(item, dict):
            raise RuntimeError(f"{path}: item non objet dans pool.")

        key, identity_method = identity_key(item)

        if key in seen_keys:
            raise RuntimeError(
                f"{path}: identité dupliquée dans le même pool: {key}"
            )
        seen_keys.add(key)

        row = dict(item)
        row["_delta_identity_key"] = key
        row["_delta_identity_method"] = identity_method
        row["_delta_content_payload"] = content_payload(item)
        row["_delta_decision_payload"] = decision_payload(item)
        row["_delta_content_fingerprint"] = fingerprint(
            row["_delta_content_payload"]
        )
        row["_delta_decision_fingerprint"] = fingerprint(
            row["_delta_decision_payload"]
        )
        prepared.append(row)

    return {
        "path": str(path.resolve()),
        "payload": payload,
        "pool": prepared,
        "timestamp": pool_timestamp(payload, path),
    }


def discover_pool_files():
    candidates = []

    for path in LOG_DIR.glob(POOL_PATTERN):
        if not path.is_file():
            continue
        try:
            loaded = load_pool(path)
            candidates.append((loaded["timestamp"], path))
        except Exception:
            # Un ancien fichier cassé ne doit pas empêcher la découverte
            # des Final Pools valides.
            continue

    candidates.sort(key=lambda x: (x[0], x[1].name))
    return [path for _, path in candidates]


def resolve_inputs(current=None, previous=None):
    if current and previous:
        current_path = Path(current)
        previous_path = Path(previous)
    else:
        files = discover_pool_files()
        if len(files) < 2:
            raise RuntimeError(
                "Au moins deux final_application_pool_v12_*.json valides "
                "sont nécessaires."
            )

        current_path = Path(current) if current else files[-1]

        if previous:
            previous_path = Path(previous)
        else:
            earlier = [
                p for p in files
                if p.resolve() != current_path.resolve()
            ]
            if not earlier:
                raise RuntimeError("Aucun Final Pool précédent disponible.")
            previous_path = earlier[-1]

    if current_path.resolve() == previous_path.resolve():
        raise RuntimeError("Current et previous pointent vers le même fichier.")

    return current_path, previous_path


def historical_seen_keys(previous_path, current_path):
    """
    Cherche les clés vues avant le pool précédent afin de distinguer
    NEW de REACTIVATED.
    """
    previous = load_pool(previous_path)
    cutoff = previous["timestamp"]
    current_resolved = Path(current_path).resolve()
    previous_resolved = Path(previous_path).resolve()

    seen = set()
    used_files = []

    for path in discover_pool_files():
        resolved = path.resolve()
        if resolved in {current_resolved, previous_resolved}:
            continue

        try:
            loaded = load_pool(path)
        except Exception:
            continue

        if loaded["timestamp"] >= cutoff:
            continue

        used_files.append(str(path.resolve()))
        seen.update(
            item["_delta_identity_key"]
            for item in loaded["pool"]
        )

    return seen, used_files


def compare_fields(previous_item, current_item, fields):
    changes = []

    for field in fields:
        old = previous_item.get(field)
        new = current_item.get(field)

        if field == "url":
            old_cmp = normalized_url(old)
            new_cmp = normalized_url(new)
        elif field in LIST_DECISION_FIELDS:
            old_cmp = canonical_list(old)
            new_cmp = canonical_list(new)
        else:
            old_cmp = canonical_scalar(old)
            new_cmp = canonical_scalar(new)

        if old_cmp != new_cmp:
            changes.append({
                "field": field,
                "previous": old,
                "current": new,
            })

    return changes



def repost_signature(item):
    """
    Signature STRICTE pour une republication automatique.

    On exige :
    - même source ;
    - même titre normalisé ;
    - même entreprise normalisée ;
    - même lieu normalisé ;
    - description live NON VIDE et strictement identique après normalisation.

    L'URL et le stable_item_key sont volontairement exclus : ce sont justement
    les éléments susceptibles de changer lors d'une republication.
    """
    description = normalize_text(item.get("description"))
    if not description:
        return None

    return (
        normalize_text(item.get("source")),
        normalize_text(item.get("title")),
        normalize_text(item.get("company")),
        normalize_text(item.get("location")),
        description,
    )


def detect_exact_reposts(current_pool, previous_pool):
    """
    Retourne current_key -> previous_item pour des republications exactes.

    Le matching est 1-à-1 uniquement. Si plusieurs annonces partagent la même
    signature stricte dans un pool, on NE fusionne RIEN automatiquement.
    """
    current_by_sig = defaultdict(list)
    previous_by_sig = defaultdict(list)

    for item in current_pool:
        sig = repost_signature(item)
        if sig:
            current_by_sig[sig].append(item)

    for item in previous_pool:
        sig = repost_signature(item)
        if sig:
            previous_by_sig[sig].append(item)

    matches = {}

    for sig, current_items in current_by_sig.items():
        previous_items = previous_by_sig.get(sig, [])

        if len(current_items) != 1 or len(previous_items) != 1:
            continue

        current_item = current_items[0]
        previous_item = previous_items[0]

        current_key = current_item["_delta_identity_key"]
        previous_key = previous_item["_delta_identity_key"]

        # Une même identité stable n'est pas une republication.
        if current_key == previous_key:
            continue

        matches[current_key] = previous_item

    return matches


def build_reposted_record(item, previous_item):
    """
    Republication exacte : même contenu métier, nouvelle identité source.
    """
    record = build_current_record(
        "REPOSTED",
        item,
        previous_item=previous_item,
    )

    record["reposted_from_identity_key"] = (
        previous_item["_delta_identity_key"]
    )
    record["repost_confidence"] = "EXACT_CONTENT_MATCH"
    record["repost_reason"] = (
        "Même source, titre, entreprise, lieu et description live ; "
        "stable_item_key/URL différents."
    )

    # Une nouvelle URL n'est pas considérée comme une modification du contenu
    # métier de l'offre. On conserve toutefois le changement explicitement.
    record["source_identity_changed"] = True
    record["previous_url"] = previous_item.get("url")
    record["current_url"] = item.get("url")

    semantic_content_fields = tuple(
        field for field in CONTENT_FIELDS
        if field != "url"
    )
    semantic_changes = compare_fields(
        previous_item,
        item,
        semantic_content_fields,
    )
    record["content_changes"] = semantic_changes
    record["content_changed"] = bool(semantic_changes)

    return record


def action_of(item):
    return clean_text(
        item.get("recommended_action_v12")
        or item.get("recommended_action")
        or "UNKNOWN"
    )


def public_item(item):
    """
    Retire les champs techniques ajoutés par Delta Tracker.
    """
    return {
        k: v
        for k, v in item.items()
        if not k.startswith("_delta_")
    }


def build_current_record(status, item, previous_item=None, history_seen=False):
    record = {
        "delta_status": status,
        "identity_key": item["_delta_identity_key"],
        "identity_method": item["_delta_identity_method"],
        "history_seen_before_previous": bool(history_seen),
        "title": item.get("title"),
        "company": item.get("company"),
        "location": item.get("location"),
        "url": item.get("url"),
        "source": item.get("source"),
        "origin_source": item.get("origin_source"),
        "recommended_action": action_of(item),
        "priority": item.get("priority_v12"),
        "track": item.get("track"),
        "guard_level": item.get("guard_level"),
        "recheck_status": item.get("recheck_status"),
        "pool_rank_current": item.get("pool_rank_v12"),
        "pool_rank_previous": (
            previous_item.get("pool_rank_v12")
            if previous_item else None
        ),
        "final_score_current": item.get("final_score_v12"),
        "final_score_previous": (
            previous_item.get("final_score_v12")
            if previous_item else None
        ),
        "content_changed": False,
        "decision_changed": False,
        "content_changes": [],
        "decision_changes": [],
        "action_transition": None,
        "current_item": public_item(item),
        "previous_item": (
            public_item(previous_item)
            if previous_item else None
        ),
    }

    if previous_item:
        record["content_changed"] = (
            previous_item["_delta_content_fingerprint"]
            != item["_delta_content_fingerprint"]
        )
        record["decision_changed"] = (
            previous_item["_delta_decision_fingerprint"]
            != item["_delta_decision_fingerprint"]
        )

        if record["content_changed"]:
            record["content_changes"] = compare_fields(
                previous_item,
                item,
                CONTENT_FIELDS,
            )

        if record["decision_changed"]:
            record["decision_changes"] = (
                compare_fields(
                    previous_item,
                    item,
                    DECISION_FIELDS,
                )
                + compare_fields(
                    previous_item,
                    item,
                    LIST_DECISION_FIELDS,
                )
            )

        old_action = action_of(previous_item)
        new_action = action_of(item)
        if old_action != new_action:
            record["action_transition"] = f"{old_action} -> {new_action}"

    return record


def build_disappeared_record(item):
    return {
        "delta_status": "DISAPPEARED",
        "disappearance_scope": "FINAL_POOL_ONLY",
        "identity_key": item["_delta_identity_key"],
        "identity_method": item["_delta_identity_method"],
        "title": item.get("title"),
        "company": item.get("company"),
        "location": item.get("location"),
        "url": item.get("url"),
        "source": item.get("source"),
        "origin_source": item.get("origin_source"),
        "recommended_action_previous": action_of(item),
        "priority_previous": item.get("priority_v12"),
        "track_previous": item.get("track"),
        "guard_level_previous": item.get("guard_level"),
        "recheck_status_previous": item.get("recheck_status"),
        "pool_rank_previous": item.get("pool_rank_v12"),
        "final_score_previous": item.get("final_score_v12"),
        "previous_item": public_item(item),
    }


def summarize(records, current_count, previous_count):
    statuses = Counter(
        r["delta_status"]
        for r in records
    )

    current_records = [
        r for r in records
        if r["delta_status"] in CURRENT_STATUSES
    ]

    new_like = [
        r for r in current_records
        if r["delta_status"] in {"NEW", "REACTIVATED"}
    ]

    reposted = [
        r for r in current_records
        if r["delta_status"] == "REPOSTED"
    ]

    current_actions = Counter(
        r.get("recommended_action") or "UNKNOWN"
        for r in current_records
    )

    new_actions = Counter(
        r.get("recommended_action") or "UNKNOWN"
        for r in new_like
    )

    updated_actions = Counter(
        r.get("recommended_action") or "UNKNOWN"
        for r in current_records
        if r["delta_status"] == "UPDATED"
    )

    reposted_actions = Counter(
        r.get("recommended_action") or "UNKNOWN"
        for r in reposted
    )

    transitions = Counter(
        r["action_transition"]
        for r in current_records
        if r.get("action_transition")
    )

    return {
        "previous_total": previous_count,
        "current_total": current_count,
        "NEW": statuses.get("NEW", 0),
        "REACTIVATED": statuses.get("REACTIVATED", 0),
        "REPOSTED": statuses.get("REPOSTED", 0),
        "UPDATED": statuses.get("UPDATED", 0),
        "UNCHANGED": statuses.get("UNCHANGED", 0),
        "DISAPPEARED": statuses.get("DISAPPEARED", 0),
        "current_actions": dict(current_actions),
        "new_or_reactivated_actions": dict(new_actions),
        "reposted_actions": dict(reposted_actions),
        "updated_actions": dict(updated_actions),
        "action_transitions": dict(transitions),
        "new_apply_now": new_actions.get("APPLY_NOW", 0),
        "reposted_apply_now": reposted_actions.get("APPLY_NOW", 0),
        "updated_apply_now": updated_actions.get("APPLY_NOW", 0),
    }


def compare_pools(current_path, previous_path):
    current = load_pool(current_path)
    previous = load_pool(previous_path)

    if current["timestamp"] <= previous["timestamp"]:
        raise RuntimeError(
            "Le pool current doit être postérieur au pool previous.\n"
            f"Current : {current['timestamp']} {current['path']}\n"
            f"Previous: {previous['timestamp']} {previous['path']}"
        )

    history_seen, history_files = historical_seen_keys(
        previous_path=previous_path,
        current_path=current_path,
    )

    current_map = {
        item["_delta_identity_key"]: item
        for item in current["pool"]
    }
    previous_map = {
        item["_delta_identity_key"]: item
        for item in previous["pool"]
    }

    exact_reposts = detect_exact_reposts(
        current["pool"],
        previous["pool"],
    )
    consumed_previous_repost_keys = {
        item["_delta_identity_key"]
        for item in exact_reposts.values()
    }

    records = []

    # Ordre du pool actuel pour NEW / REPOSTED / UPDATED / UNCHANGED.
    for item in current["pool"]:
        key = item["_delta_identity_key"]
        old = previous_map.get(key)

        if old is None:
            reposted_from = exact_reposts.get(key)
            if reposted_from is not None:
                records.append(
                    build_reposted_record(
                        item,
                        previous_item=reposted_from,
                    )
                )
                continue

            status = (
                "REACTIVATED"
                if key in history_seen
                else "NEW"
            )
            records.append(
                build_current_record(
                    status,
                    item,
                    previous_item=None,
                    history_seen=key in history_seen,
                )
            )
            continue

        content_changed = (
            old["_delta_content_fingerprint"]
            != item["_delta_content_fingerprint"]
        )
        decision_changed = (
            old["_delta_decision_fingerprint"]
            != item["_delta_decision_fingerprint"]
        )

        status = (
            "UPDATED"
            if content_changed or decision_changed
            else "UNCHANGED"
        )

        records.append(
            build_current_record(
                status,
                item,
                previous_item=old,
            )
        )

    # Les sorties du Final Pool sont ajoutées à la fin.
    for item in previous["pool"]:
        key = item["_delta_identity_key"]
        if (
            key not in current_map
            and key not in consumed_previous_repost_keys
        ):
            records.append(build_disappeared_record(item))

    summary = summarize(
        records,
        current_count=len(current["pool"]),
        previous_count=len(previous["pool"]),
    )

    validate_comparison(
        records,
        summary,
        current_map=current_map,
        previous_map=previous_map,
    )

    return {
        "delta_tracker_version": DELTA_TRACKER_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scope": "FINAL_APPLICATION_POOL_V1.2",
        "disappeared_semantics": (
            "Absent du Final Pool actuel. "
            "Ne prouve pas que l'annonce a été retirée d'Internet."
        ),
        "inputs": {
            "previous_pool": previous["path"],
            "previous_generated_at": previous["payload"].get("generated_at"),
            "current_pool": current["path"],
            "current_generated_at": current["payload"].get("generated_at"),
            "historical_pools_used_for_reactivation": history_files,
        },
        "summary": summary,
        "records": records,
    }


def validate_comparison(
    records,
    summary,
    current_map=None,
    previous_map=None,
):
    current_records = [
        r for r in records
        if r["delta_status"] in CURRENT_STATUSES
    ]
    disappeared = [
        r for r in records
        if r["delta_status"] == "DISAPPEARED"
    ]

    if len(current_records) != summary["current_total"]:
        raise RuntimeError(
            "Invariant Delta cassé : current statuses != current_total."
        )

    current_status_total = sum(
        summary[name]
        for name in ("NEW", "REACTIVATED", "REPOSTED", "UPDATED", "UNCHANGED")
    )
    if current_status_total != summary["current_total"]:
        raise RuntimeError(
            "Invariant Delta cassé : somme des statuts actuels incorrecte."
        )

    shared = (
        summary["REPOSTED"]
        + summary["UPDATED"]
        + summary["UNCHANGED"]
    )
    expected_previous = shared + summary["DISAPPEARED"]
    if expected_previous != summary["previous_total"]:
        raise RuntimeError(
            "Invariant Delta cassé : reconstruction previous_total incorrecte."
        )

    if len(disappeared) != summary["DISAPPEARED"]:
        raise RuntimeError(
            "Invariant Delta cassé : nombre DISAPPEARED incorrect."
        )

    current_keys = [
        r["identity_key"]
        for r in current_records
    ]
    if len(current_keys) != len(set(current_keys)):
        raise RuntimeError(
            "Invariant Delta cassé : identité actuelle dupliquée."
        )

    disappeared_keys = {
        r["identity_key"]
        for r in disappeared
    }
    if disappeared_keys.intersection(current_keys):
        raise RuntimeError(
            "Invariant Delta cassé : un item est à la fois actuel et disparu."
        )

    if current_map is not None and set(current_keys) != set(current_map):
        raise RuntimeError(
            "Invariant Delta cassé : clés actuelles incomplètes."
        )

    if previous_map is not None:
        reconstructed_previous = set()
        for r in records:
            if r["delta_status"] == "REPOSTED":
                reconstructed_previous.add(
                    r["reposted_from_identity_key"]
                )
            elif r["delta_status"] in {"UPDATED", "UNCHANGED", "DISAPPEARED"}:
                reconstructed_previous.add(
                    r["identity_key"]
                )

        if reconstructed_previous != set(previous_map):
            raise RuntimeError(
                "Invariant Delta cassé : clés previous incomplètes."
            )


def output_sort_key(record):
    order = {
        "NEW": 0,
        "REACTIVATED": 1,
        "REPOSTED": 2,
        "UPDATED": 3,
        "DISAPPEARED": 4,
        "UNCHANGED": 5,
    }
    return (
        order.get(record["delta_status"], 99),
        record.get("pool_rank_current")
        if record.get("pool_rank_current") is not None
        else 999999,
        record.get("pool_rank_previous")
        if record.get("pool_rank_previous") is not None
        else 999999,
    )


def export_delta(result):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = LOG_DIR / f"delta_tracker_v1_{stamp}.json"
    txt_path = LOG_DIR / f"delta_tracker_v1_{stamp}.txt"
    csv_path = LOG_DIR / f"delta_tracker_v1_{stamp}.csv"

    json_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = result["summary"]
    lines = [
        "DELTA TRACKER V1.1",
        "=" * 100,
        f"Previous : {result['inputs']['previous_pool']}",
        f"Current  : {result['inputs']['current_pool']}",
        "",
        f"Previous total : {summary['previous_total']}",
        f"Current total  : {summary['current_total']}",
        "",
        f"NEW            : {summary['NEW']}",
        f"REACTIVATED    : {summary['REACTIVATED']}",
        f"REPOSTED       : {summary['REPOSTED']}",
        f"UPDATED        : {summary['UPDATED']}",
        f"UNCHANGED      : {summary['UNCHANGED']}",
        f"DISAPPEARED    : {summary['DISAPPEARED']}  [FINAL POOL ONLY]",
        "",
        f"New APPLY_NOW  : {summary['new_apply_now']}",
        f"Reposted APPLY_NOW : {summary['reposted_apply_now']}",
        f"Updated APPLY_NOW : {summary['updated_apply_now']}",
        "",
    ]

    for status in ("NEW", "REACTIVATED", "REPOSTED", "UPDATED", "DISAPPEARED"):
        rows = [
            r for r in result["records"]
            if r["delta_status"] == status
        ]
        if not rows:
            continue

        lines.append("=" * 100)
        lines.append(status)
        lines.append("=" * 100)

        for row in sorted(rows, key=output_sort_key):
            action = (
                row.get("recommended_action")
                or row.get("recommended_action_previous")
                or "UNKNOWN"
            )
            lines.append(
                f"[{action}] {row.get('title')} | "
                f"{row.get('company')} | {row.get('location')}"
            )
            lines.append(f"  Key : {row.get('identity_key')}")
            if row.get("action_transition"):
                lines.append(
                    f"  Action : {row['action_transition']}"
                )
            if status == "UPDATED":
                change_types = []
                if row.get("content_changed"):
                    change_types.append("CONTENT")
                if row.get("decision_changed"):
                    change_types.append("DECISION")
                lines.append(
                    "  Changes : " + ", ".join(change_types)
                )
                for change in (
                    row.get("content_changes", [])
                    + row.get("decision_changes", [])
                ):
                    lines.append(
                        f"    - {change['field']}: "
                        f"{change['previous']!r} -> {change['current']!r}"
                    )
            if row.get("url"):
                lines.append(f"  {row['url']}")
            lines.append("")

    txt_path.write_text("\n".join(lines), encoding="utf-8")

    csv_fields = [
        "delta_status",
        "identity_key",
        "identity_method",
        "title",
        "company",
        "location",
        "source",
        "recommended_action",
        "recommended_action_previous",
        "priority",
        "priority_previous",
        "track",
        "track_previous",
        "pool_rank_current",
        "pool_rank_previous",
        "final_score_current",
        "final_score_previous",
        "content_changed",
        "decision_changed",
        "action_transition",
        "disappearance_scope",
        "url",
    ]

    with csv_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=csv_fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in sorted(
            result["records"],
            key=output_sort_key,
        ):
            writer.writerow(row)

    return {
        "json": json_path,
        "txt": txt_path,
        "csv": csv_path,
    }


def print_summary(result, paths=None):
    s = result["summary"]

    print("=" * 100)
    print("DELTA TRACKER V1.1")
    print("=" * 100)
    print("Previous :", result["inputs"]["previous_pool"])
    print("Current  :", result["inputs"]["current_pool"])
    print()
    print("Previous total :", s["previous_total"])
    print("Current total  :", s["current_total"])
    print()
    print("NEW            :", s["NEW"])
    print("REACTIVATED    :", s["REACTIVATED"])
    print("REPOSTED       :", s["REPOSTED"])
    print("UPDATED        :", s["UPDATED"])
    print("UNCHANGED      :", s["UNCHANGED"])
    print("DISAPPEARED    :", s["DISAPPEARED"], "[FINAL POOL ONLY]")
    print()
    print("NEW APPLY_NOW  :", s["new_apply_now"])
    print("REPOSTED APPLY_NOW :", s["reposted_apply_now"])
    print("UPDATED APPLY_NOW :", s["updated_apply_now"])

    if paths:
        print()
        print("JSON :", paths["json"])
        print("TXT  :", paths["txt"])
        print("CSV  :", paths["csv"])

    print()
    print("✅ DELTA TRACKER V1.1 TERMINÉ.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", default=None)
    parser.add_argument("--previous", default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compare sans exporter.",
    )
    args = parser.parse_args()

    current, previous = resolve_inputs(
        current=args.current,
        previous=args.previous,
    )

    result = compare_pools(
        current_path=current,
        previous_path=previous,
    )

    paths = None
    if not args.dry_run:
        paths = export_delta(result)

    print_summary(result, paths=paths)


if __name__ == "__main__":
    main()
