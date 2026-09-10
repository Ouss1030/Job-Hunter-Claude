"""
APPLICATION RECHECK V1.1 - AUDIT OFFLINE

Usage:
    python -m diagnostics.application_recheck_v11_audit
"""

from applications.application_recheck_v11 import (
    RECHECK_VERSION,
    explicit_student_role,
    mandatory_master_block,
    strong_language_gap,
    data_experience_or_degree_stretch,
)


def check(label, condition, detail=""):
    ok = bool(condition)
    print(
        f"{'✅' if ok else '❌'} {label}"
        + (f" | {detail}" if detail else "")
    )
    return ok


def main():
    tests = []

    print("=" * 88)
    print("APPLICATION RECHECK V1.1 - AUDIT OFFLINE")
    print("=" * 88)
    print()

    tests.append(check(
        "Version 1.1",
        RECHECK_VERSION == "1.1",
        RECHECK_VERSION,
    ))

    tests.append(check(
        "Master obligatoire rejeté",
        mandatory_master_block(
            "Qualifications. Diplôme de master en chimie avec une première expérience."
        ) is True,
    ))

    tests.append(check(
        "Bachelor ou Master accepté",
        mandatory_master_block(
            "Bachelor or Master degree in chemistry accepted."
        ) is False,
    ))

    tests.append(check(
        "Bachelor- of masterdiploma accepté",
        mandatory_master_block(
            "Ben je in het bezit van een bachelor- of masterdiploma in IT, logistiek, supply chain?"
        ) is False,
    ))

    tests.append(check(
        "Master is a plus accepté",
        mandatory_master_block(
            "Bachelor in chemistry required. A Master's degree is a plus."
        ) is False,
    ))

    tests.append(check(
        "Vrai job étudiant détecté",
        explicit_student_role(
            "Voor een bedrijf zijn we op zoek naar student Quality Controller."
        ) is True,
    ))

    tests.append(check(
        "Studentenjob comme expérience NON détecté",
        explicit_student_role(
            "Ervaring via een stage, studentenjob of eerdere functie "
            "in een analytisch labo is mooi meegenomen."
        ) is False,
    ))

    nl = strong_language_gap(
        "Je spreekt en schrijft zeer vlot Nederlands."
    )
    tests.append(check(
        "Néerlandais très fluide -> warning",
        any("Néerlandais" in x for x in nl),
        str(nl),
    ))

    nl2 = strong_language_gap(
        "Vlotte communicatievaardigheden in het Nederlands zijn vereist."
    )
    tests.append(check(
        "Communication NL fluide -> warning",
        any("Néerlandais" in x for x in nl2),
        str(nl2),
    ))

    data_item = {"best_family": "data_analytics"}
    warnings = data_experience_or_degree_stretch(
        data_item,
        "Concevoir des tableaux de bord via SAP Business Object.",
    )
    tests.append(check(
        "tableaux de bord != technologie Tableau",
        not any("tableau" in x.lower() for x in warnings),
        str(warnings),
    ))

    warnings2 = data_experience_or_degree_stretch(
        data_item,
        "Dashboards in Tableau, ETL via Talend et bases Oracle.",
    )
    tests.append(check(
        "Technologie Tableau réelle détectée",
        any("Stack spécifique" in x for x in warnings2),
        str(warnings2),
    ))

    warnings3 = data_experience_or_degree_stretch(
        data_item,
        "Bachelor- of masterdiploma in IT, logistiek of supply chain.",
    )
    tests.append(check(
        "Diplôme Data adjacent -> warning",
        any("Diplôme explicitement" in x for x in warnings3),
        str(warnings3),
    ))

    print()
    print(f"Tests : {sum(tests)}/{len(tests)}")

    if not all(tests):
        raise SystemExit("❌ APPLICATION RECHECK V1.1 NON VALIDÉ.")

    print("✅ APPLICATION RECHECK V1.1 VALIDÉ OFFLINE.")


if __name__ == "__main__":
    main()
