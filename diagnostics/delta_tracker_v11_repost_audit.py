"""
DELTA TRACKER V1.1 - REPOST AUDIT

Usage:
    python -m diagnostics.delta_tracker_v11_repost_audit

Aucun réseau. Aucune DB.
"""

from datetime import datetime
from pathlib import Path

from diagnostics.version_support import at_least

from applications.delta_tracker import (
    DELTA_TRACKER_VERSION,
    content_payload,
    decision_payload,
    detect_exact_reposts,
    fingerprint,
    identity_key,
    build_reposted_record,
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


def offer(key, url, description="Description identique", company="ADECCO"):
    return decorate({
        "stable_item_key": key,
        "title": "Business / Financial Data Analyst (/X) | CDI (H/F/X)",
        "company": company,
        "location": "SOUMAGNE, Belgique",
        "url": url,
        "source": "FOREM",
        "description": description,
        "recommended_action_v12": "REVIEW_FIRST",
        "priority_v12": "B",
        "track": "DATA",
        "guard_level": "REVIEW",
        "guard_flags": [],
        "warnings": [],
        "recheck_status": "READY_DOCUMENTS",
    })


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f" | {detail}" if detail else ""))
    return ok


def main():
    tests = []

    print("=" * 100)
    print("DELTA TRACKER V1.1 - REPOST AUDIT")
    print("=" * 100)
    print()

    tests.append(check(
        "Version >= 1.1",
        at_least(DELTA_TRACKER_VERSION, "1.1"),
        DELTA_TRACKER_VERSION,
    ))

    old = offer(
        "ITEM_old",
        "https://www.leforem.be/recherche-offres/offre-detail/1990215",
    )
    new = offer(
        "ITEM_new",
        "https://www.leforem.be/recherche-offres/offre-detail/2022367",
    )

    matches = detect_exact_reposts([new], [old])

    tests.append(check(
        "Republication exacte détectée",
        matches.get("ITEM_new") is old,
        str(matches.keys()),
    ))

    record = build_reposted_record(new, old)

    tests.append(check(
        "Statut REPOSTED",
        record["delta_status"] == "REPOSTED",
        record["delta_status"],
    ))
    tests.append(check(
        "Ancienne identité conservée",
        record["reposted_from_identity_key"] == "ITEM_old",
        record["reposted_from_identity_key"],
    ))
    tests.append(check(
        "Confiance exacte",
        record["repost_confidence"] == "EXACT_CONTENT_MATCH",
        record["repost_confidence"],
    ))
    tests.append(check(
        "URL différente ne devient pas content_changed",
        record["content_changed"] is False,
        str(record["content_changes"]),
    ))

    changed_description = offer(
        "ITEM_new2",
        "https://www.leforem.be/recherche-offres/offre-detail/2029999",
        description="Description différente",
    )
    no_match = detect_exact_reposts([changed_description], [old])

    tests.append(check(
        "Description différente non fusionnée",
        "ITEM_new2" not in no_match,
        str(no_match.keys()),
    ))

    different_company = offer(
        "ITEM_new3",
        "https://www.leforem.be/recherche-offres/offre-detail/2030000",
        company="AUTRE ENTREPRISE",
    )
    no_match_company = detect_exact_reposts([different_company], [old])

    tests.append(check(
        "Entreprise différente non fusionnée",
        "ITEM_new3" not in no_match_company,
        str(no_match_company.keys()),
    ))

    # Ambiguïté 2-à-1 : aucun auto-match.
    duplicate = offer(
        "ITEM_new4",
        "https://www.leforem.be/recherche-offres/offre-detail/2030001",
    )
    ambiguous = detect_exact_reposts([new, duplicate], [old])

    tests.append(check(
        "Ambiguïté non fusionnée",
        not ambiguous,
        str(ambiguous),
    ))

    passed = sum(tests)
    total = len(tests)
    status = (
        "✅ REPOST FEATURE (>= DELTA V1.1) VALIDÉE."
        if all(tests)
        else "❌ DELTA TRACKER V1.1 NON VALIDÉ."
    )

    print()
    print(f"Tests : {passed}/{total}")
    print(status)

    log_dir = Path(__file__).resolve().parents[1] / "exports" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = log_dir / f"delta_tracker_v11_repost_audit_{stamp}.txt"
    out.write_text(
        "\n".join([
            "DELTA TRACKER V1.1 - REPOST AUDIT",
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
