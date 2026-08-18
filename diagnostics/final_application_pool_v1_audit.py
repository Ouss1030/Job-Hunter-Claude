"""
Diagnostic FINAL APPLICATION POOL V1
Aucun accès réseau.

Usage :
    python -m diagnostics.final_application_pool_v1_audit
"""

from applications.final_application_pool import (
    preferred_location,
    classify_track,
    off_domain_title,
    rescue_stretch_allowed,
    enrich_ranking_fields,
    duplicate_score,
)


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f": {detail}" if detail else ""))
    return ok


def main():
    tests = []

    tests.append(check(
        "Anderlecht = zone prioritaire",
        preferred_location("Anderlecht, 1070, Belgique"),
    ))
    tests.append(check(
        "Louvain-la-Neuve = zone prioritaire",
        preferred_location("Louvain-la-Neuve, 1348, Belgique"),
    ))
    tests.append(check(
        "HPLC -> LAB_QC",
        classify_track("Technicien laboratoire HPLC", "LAB_QC") == "LAB_QC",
    ))
    tests.append(check(
        "Production chimie -> PRODUCTION_SCIENCE",
        classify_track("Opérateur de production secteur chimie", "LAB_QC")
        == "PRODUCTION_SCIENCE",
    ))
    tests.append(check(
        "Business Data Analyst -> DATA",
        classify_track("Business Data Analyst", "DATA") == "DATA",
    ))
    tests.append(check(
        "Piping = hors domaine",
        off_domain_title("Quality Controller | Piping"),
    ))

    rescue_ok = {
        "rescue_status": "RESCUED_STRETCH",
        "title": "Technicien qualité ISO",
        "after": {"score": 62.4, "family": "quality"},
    }
    tests.append(check(
        "Rescue quality plausible conservé",
        rescue_stretch_allowed(rescue_ok),
    ))

    rescue_bad = {
        "rescue_status": "RESCUED_STRETCH",
        "title": "Quality Controller | Piping",
        "after": {"score": 64.0, "family": "quality"},
    }
    tests.append(check(
        "Rescue piping exclu",
        not rescue_stretch_allowed(rescue_bad),
    ))

    ranked = enrich_ranking_fields([{
        "title": "Technicien laboratoire HPLC",
        "location": "Anderlecht, 1070, Belgique",
        "cv_track": "LAB_QC",
        "pool_origin": "READY_DOCUMENTS",
        "queue_score": 139.0,
        "match_score": 100.0,
    }])[0]
    tests.append(check(
        "Très bon poste proche -> A+ APPLY_NOW",
        ranked["priority"] == "A+" and ranked["recommended_action"] == "APPLY_NOW",
        f"{ranked['priority']} {ranked['recommended_action']}",
    ))

    a = {
        "title": "Laborantin GQP",
        "location": "Spa, 4900, Belgique",
        "description": "analyse laboratoire qualite echantillon " * 50,
        "application_group_id": "",
        "source": "FOREM",
        "url": "https://a",
    }
    b = {
        "title": "Laborantin GQP H/F/X",
        "location": "Spa, 4900, Belgique",
        "description": "analyse laboratoire qualite echantillon " * 50,
        "application_group_id": "",
        "source": "ACTIRIS",
        "url": "https://b",
    }
    dup, sim, method = duplicate_score(a, b)
    tests.append(check(
        "Descriptions identiques même lieu -> doublon",
        dup,
        f"{sim:.3f} {method}",
    ))

    c = dict(b)
    c["location"] = "Brugge, 8000, Belgique"
    dup, _, _ = duplicate_score(a, c)
    tests.append(check(
        "Même description autre ville -> pas fusion automatique",
        not dup,
    ))

    print()
    print(f"Tests synthétiques : {sum(tests)}/{len(tests)}")
    if all(tests):
        print("✅ FINAL APPLICATION POOL V1 VALIDÉ SUR LE DIAGNOSTIC.")
    else:
        raise SystemExit("❌ FINAL APPLICATION POOL V1 NON VALIDÉ.")


if __name__ == "__main__":
    main()
