"""
FINAL APPLICATION POOL V1.2 - AUDIT DU BATCH ACTUEL

Lit les derniers :
- application_recheck_v1_*.json
- job_refresh_v1_*.json

Aucun export.
Aucun réseau.
Aucune écriture DB.

Usage:
    python -m diagnostics.final_application_pool_v12_current_batch_audit
"""

from collections import Counter

from applications.final_application_pool_v12 import (
    FINAL_POOL_VERSION,
    build_pool_v12,
    latest_file,
    load_json,
)


EXPECTED = {
    "total": 66,
    "APPLY_NOW": 37,
    "APPLY_NEXT": 4,
    "REVIEW_FIRST": 21,
    "DO_NOT_APPLY": 4,
    "duplicates": 7,
    "possible_duplicates": 1,
    "smartrecruiters": 11,
    "travaillerpour": 1,
}


def check(label, condition, detail=""):
    ok = bool(condition)
    print(
        f"{'✅' if ok else '❌'} {label}"
        + (f" | {detail}" if detail else "")
    )
    return ok


def find(pool, title_fragment, company=None):
    fragment = title_fragment.lower()
    for item in pool:
        if fragment not in str(item.get("title") or "").lower():
            continue
        if company and company.lower() not in str(item.get("company") or "").lower():
            continue
        return item
    return None


def main():
    print("=" * 100)
    print("FINAL APPLICATION POOL V1.2 - AUDIT BATCH ACTUEL")
    print("=" * 100)
    print()

    recheck_path = latest_file("application_recheck_v1_*.json")
    refresh_path = latest_file("job_refresh_v1_*.json")

    if not recheck_path or not refresh_path:
        raise SystemExit("❌ Recheck/Refresh actuel introuvable.")

    recheck = load_json(recheck_path)
    refresh = load_json(refresh_path)

    eligible = [
        x for x in recheck
        if x.get("status") in {"READY_DOCUMENTS", "STRETCH_REVIEW"}
    ]

    payload = build_pool_v12()
    pool = payload["pool"]
    summary = payload["summary"]

    tests = []

    tests.append(check(
        "Version 1.2",
        FINAL_POOL_VERSION == "1.2",
        FINAL_POOL_VERSION,
    ))

    tests.append(check(
        "73 éléments live avant dédup",
        len(eligible) == 73,
        str(len(eligible)),
    ))

    tests.append(check(
        "Total unique 66",
        summary.get("total") == EXPECTED["total"],
        str(summary.get("total")),
    ))

    tests.append(check(
        "37 APPLY_NOW",
        summary.get("APPLY_NOW") == EXPECTED["APPLY_NOW"],
        str(summary.get("APPLY_NOW")),
    ))

    tests.append(check(
        "4 APPLY_NEXT",
        summary.get("APPLY_NEXT") == EXPECTED["APPLY_NEXT"],
        str(summary.get("APPLY_NEXT")),
    ))

    tests.append(check(
        "21 REVIEW_FIRST",
        summary.get("REVIEW_FIRST") == EXPECTED["REVIEW_FIRST"],
        str(summary.get("REVIEW_FIRST")),
    ))

    tests.append(check(
        "4 DO_NOT_APPLY",
        summary.get("DO_NOT_APPLY") == EXPECTED["DO_NOT_APPLY"],
        str(summary.get("DO_NOT_APPLY")),
    ))

    tests.append(check(
        "7 doublons retirés",
        payload.get("duplicates_removed_count") == EXPECTED["duplicates"],
        str(payload.get("duplicates_removed_count")),
    ))

    tests.append(check(
        "1 doublon possible non auto-fusionné",
        payload.get("possible_duplicates_count")
        == EXPECTED["possible_duplicates"],
        str(payload.get("possible_duplicates_count")),
    ))

    sources = Counter(
        str(item.get("source") or "").upper()
        for item in pool
    )

    tests.append(check(
        "11 SmartRecruiters présents",
        sources.get("SMARTRECRUITERS") == EXPECTED["smartrecruiters"],
        str(sources.get("SMARTRECRUITERS")),
    ))

    tests.append(check(
        "1 TravaillerPour présent",
        sources.get("TRAVAILLERPOUR") == EXPECTED["travaillerpour"],
        str(sources.get("TRAVAILLERPOUR")),
    ))

    beveren_bad = [
        item for item in pool
        if "beveren" in str(item.get("location") or "").lower()
        and item.get("preferred_location")
    ]
    tests.append(check(
        "Beveren non prioritaire",
        not beveren_bad,
        str(len(beveren_bad)),
    ))

    chemistry = find(pool, "Analyste - Chemistry Mono", "SGS")
    tests.append(check(
        "SGS Chemistry Mono présent",
        chemistry is not None
        and chemistry.get("source") == "SMARTRECRUITERS"
        and chemistry.get("recommended_action_v12") == "APPLY_NOW",
        str(chemistry and chemistry.get("recommended_action_v12")),
    ))

    sopra = find(pool, "Computer System Validation Engineer", "Sopra Steria")
    tests.append(check(
        "Sopra CSV -> REVIEW_FIRST",
        sopra is not None
        and sopra.get("recommended_action_v12") == "REVIEW_FIRST",
        str(sopra and sopra.get("recommended_action_v12")),
    ))

    gc = find(pool, "Laborant Milieuonderzoek GC", "Eurofins")
    tests.append(check(
        "Eurofins GC NL -> REVIEW_FIRST",
        gc is not None
        and gc.get("recommended_action_v12") == "REVIEW_FIRST",
        str(gc and gc.get("recommended_action_v12")),
    ))

    junior_rd = find(pool, "JUNIOR R&D LABORANT", "KONVERT")
    tests.append(check(
        "Junior R&D bilingue -> REVIEW_FIRST",
        junior_rd is not None
        and junior_rd.get("recommended_action_v12") == "REVIEW_FIRST",
        str(junior_rd and junior_rd.get("recommended_action_v12")),
    ))

    synthese = find(pool, "Opérateur(trice) de synthèse", "VIVALDIS")
    tests.append(check(
        "Synthèse 3-5 ans indispensable -> DO_NOT_APPLY",
        synthese is not None
        and synthese.get("recommended_action_v12") == "DO_NOT_APPLY",
        str(synthese and synthese.get("recommended_action_v12")),
    ))

    forbidden_companies = {
        "Accent",
        "EXPERIS BELGIUM",
        "BETUNED - BETUNED",
        "SPF ECONOMIE",
    }
    forbidden = [
        item for item in pool
        if item.get("company") in forbidden_companies
    ]
    tests.append(check(
        "Rejets Recheck ne réapparaissent pas",
        not forbidden,
        str([x.get("company") for x in forbidden]),
    ))

    stale_source = payload.get("inputs", {}).get("recall_rescue_policy")
    tests.append(check(
        "Recall Rescue stale exclu",
        stale_source == "EXCLUDED_UNLESS_REFETCHED_AND_RECHECKED",
        str(stale_source),
    ))

    print()
    print("RÉSUMÉ")
    print("-" * 100)
    print("Recheck :", recheck_path)
    print("Refresh :", refresh_path)
    print("Unique  :", summary.get("total"))
    print("APPLY_NOW       :", summary.get("APPLY_NOW"))
    print("APPLY_NEXT      :", summary.get("APPLY_NEXT"))
    print("REVIEW_FIRST    :", summary.get("REVIEW_FIRST"))
    print("DO_NOT_APPLY    :", summary.get("DO_NOT_APPLY"))
    print("SmartRecruiters :", sources.get("SMARTRECRUITERS"))
    print("TravaillerPour  :", sources.get("TRAVAILLERPOUR"))
    print()

    print(f"Checks : {sum(tests)}/{len(tests)}")

    if not all(tests):
        raise SystemExit("❌ FINAL POOL V1.2 BATCH ACTUEL NON VALIDÉ.")

    print("✅ FINAL POOL V1.2 VALIDÉ SUR LE BATCH LIVE ACTUEL.")


if __name__ == "__main__":
    main()
