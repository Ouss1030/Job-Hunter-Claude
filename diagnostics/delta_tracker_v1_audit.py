"""
DELTA TRACKER V1.0 - AUDIT OFFLINE

Usage:
    python -m diagnostics.delta_tracker_v1_audit

Aucun réseau.
Aucune DB.
"""

from datetime import datetime
from pathlib import Path

from diagnostics.version_support import at_least

from applications.delta_tracker import (
    DELTA_TRACKER_VERSION,
    build_current_record,
    build_disappeared_record,
    content_payload,
    decision_payload,
    fingerprint,
    identity_key,
    summarize,
    validate_comparison,
)


def decorate(item):
    row = dict(item)
    key, method = identity_key(row)
    row["_delta_identity_key"] = key
    row["_delta_identity_method"] = method
    row["_delta_content_payload"] = content_payload(row)
    row["_delta_decision_payload"] = decision_payload(row)
    row["_delta_content_fingerprint"] = fingerprint(
        row["_delta_content_payload"]
    )
    row["_delta_decision_fingerprint"] = fingerprint(
        row["_delta_decision_payload"]
    )
    return row


def base(key, title="Laborantin", action="APPLY_NOW", description="Analyse QC"):
    return decorate({
        "stable_item_key": key,
        "title": title,
        "company": "Example Lab",
        "location": "Bruxelles, Belgique",
        "url": f"https://example.test/{key}",
        "description": description,
        "recommended_action_v12": action,
        "priority_v12": "A",
        "track": "LAB_QC",
        "guard_level": "PASS",
        "guard_flags": [],
        "warnings": [],
        "recheck_status": "READY_DOCUMENTS",
        "preferred_location": True,
        "pool_rank_v12": 1,
        "final_score_v12": 150.0,
    })


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f" | {detail}" if detail else ""))
    return ok


def main():
    tests = []

    print("=" * 100)
    print("DELTA TRACKER V1.0 - AUDIT OFFLINE")
    print("=" * 100)
    print()

    tests.append(check(
        "Version >= 1.0",
        at_least(DELTA_TRACKER_VERSION, "1.0"),
        DELTA_TRACKER_VERSION,
    ))

    same_old = base("ITEM_same")
    same_new = base("ITEM_same")

    unchanged = build_current_record(
        "UNCHANGED",
        same_new,
        previous_item=same_old,
    )
    tests.append(check(
        "UNCHANGED sans faux changement",
        not unchanged["content_changed"]
        and not unchanged["decision_changed"],
        str(unchanged),
    ))

    content_old = base("ITEM_content", description="Analyse QC")
    content_new = base("ITEM_content", description="Analyse QC + HPLC")

    updated_content = build_current_record(
        "UPDATED",
        content_new,
        previous_item=content_old,
    )
    tests.append(check(
        "Modification description détectée",
        updated_content["content_changed"]
        and not updated_content["decision_changed"],
        str(updated_content["content_changes"]),
    ))

    action_old = base("ITEM_action", action="APPLY_NEXT")
    action_new = base("ITEM_action", action="APPLY_NOW")

    updated_decision = build_current_record(
        "UPDATED",
        action_new,
        previous_item=action_old,
    )
    tests.append(check(
        "Modification décision détectée",
        updated_decision["decision_changed"],
        str(updated_decision["decision_changes"]),
    ))

    tests.append(check(
        "Transition d'action explicite",
        updated_decision["action_transition"]
        == "APPLY_NEXT -> APPLY_NOW",
        str(updated_decision["action_transition"]),
    ))

    new_item = base("ITEM_new")
    new_record = build_current_record(
        "NEW",
        new_item,
        history_seen=False,
    )
    tests.append(check(
        "NEW",
        new_record["delta_status"] == "NEW"
        and not new_record["history_seen_before_previous"],
    ))

    reactivated_record = build_current_record(
        "REACTIVATED",
        new_item,
        history_seen=True,
    )
    tests.append(check(
        "REACTIVATED",
        reactivated_record["delta_status"] == "REACTIVATED"
        and reactivated_record["history_seen_before_previous"],
    ))

    disappeared = build_disappeared_record(base("ITEM_gone"))
    tests.append(check(
        "DISAPPEARED limité au Final Pool",
        disappeared["disappearance_scope"] == "FINAL_POOL_ONLY",
    ))

    tests.append(check(
        "Rank seul exclu du fingerprint contenu",
        "pool_rank_v12" not in content_payload(base("ITEM_rank")),
    ))

    tests.append(check(
        "Score seul exclu du fingerprint décision",
        "final_score_v12" not in decision_payload(base("ITEM_score")),
    ))

    records = [
        new_record,
        updated_decision,
        unchanged,
        disappeared,
    ]
    summary = summarize(
        records,
        current_count=3,
        previous_count=3,
    )

    tests.append(check(
        "Résumé current cohérent",
        summary["current_total"] == 3
        and summary["NEW"] == 1
        and summary["UPDATED"] == 1
        and summary["UNCHANGED"] == 1,
        str(summary),
    ))

    tests.append(check(
        "Résumé previous cohérent",
        summary["previous_total"] == 3
        and summary["DISAPPEARED"] == 1,
        str(summary),
    ))

    try:
        validate_comparison(records, summary)
        invariant_ok = True
    except Exception as exc:
        invariant_ok = False
        invariant_detail = str(exc)
    else:
        invariant_detail = ""

    tests.append(check(
        "Invariants valides",
        invariant_ok,
        invariant_detail,
    ))

    stable_key, method = identity_key(base("ITEM_stable"))
    tests.append(check(
        "stable_item_key prioritaire",
        stable_key == "ITEM_stable"
        and method == "STABLE_ITEM_KEY",
        f"{stable_key} / {method}",
    ))

    fallback_key, fallback_method = identity_key({
        "url": "https://example.test/job/1?utm_source=x",
        "title": "Test",
        "company": "Example",
        "location": "Bruxelles",
        "source": "TEST",
    })
    tests.append(check(
        "Fallback URL disponible",
        fallback_key.startswith("URL_")
        and fallback_method == "URL_FALLBACK",
        f"{fallback_key} / {fallback_method}",
    ))

    passed = sum(tests)
    total = len(tests)
    status = (
        "✅ DELTA TRACKER V1.0 VALIDÉ OFFLINE."
        if all(tests)
        else "❌ DELTA TRACKER V1.0 NON VALIDÉ."
    )

    print()
    print(f"Tests : {passed}/{total}")
    print(status)

    log_dir = Path(__file__).resolve().parents[1] / "exports" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = log_dir / f"delta_tracker_v1_audit_{stamp}.txt"
    out.write_text(
        "\n".join([
            "DELTA TRACKER V1.0 - AUDIT OFFLINE",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status,
        ]),
        encoding="utf-8",
    )
    print("TXT audit :", out)

    if not all(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
