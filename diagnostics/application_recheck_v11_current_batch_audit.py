"""
APPLICATION RECHECK V1.1 - CURRENT BATCH AUDIT

Lit le dernier job_refresh_v1_*.json et exécute V1.1 sans écrire de résultat.

Usage:
    python -m diagnostics.application_recheck_v11_current_batch_audit
"""

from pathlib import Path

from applications.application_recheck_v11 import (
    LOG_DIR,
    latest_file,
    load_json,
    recheck_batch,
    summary,
)


def by_fragment(results, fragment):
    f = fragment.lower()
    for row in results:
        if f in str(row.get("title") or "").lower():
            return row
    return None


def check(label, condition, detail=""):
    ok = bool(condition)
    print(
        f"{'✅' if ok else '❌'} {label}"
        + (f" | {detail}" if detail else "")
    )
    return ok


def main():
    input_path = latest_file(LOG_DIR, "job_refresh_v1_*.json")
    if not input_path:
        raise SystemExit("❌ Aucun job_refresh_v1_*.json trouvé.")

    items = load_json(input_path)
    results = recheck_batch(items)
    s = summary(results)

    print("=" * 92)
    print("APPLICATION RECHECK V1.1 - CURRENT BATCH AUDIT")
    print("=" * 92)
    print("Source :", input_path)
    print("Total  :", len(items))
    print()

    tests = []

    accent = by_fragment(results, "Laborantin (H/F/X)")
    # Plusieurs titres identiques existent ; contrôle plus précis ci-dessous.
    accent = next(
        (r for r in results if r.get("company") == "Accent"),
        None,
    )
    tests.append(check(
        "Accent agrément médical -> REJECT",
        accent and accent["status"] == "REJECT",
        str(accent and accent["status"]),
    ))

    talentus = next(
        (
            r for r in results
            if r.get("company") == "TALENTUS"
            and "collaborateur qualité" in str(r.get("title") or "").lower()
        ),
        None,
    )
    tests.append(check(
        "Talentus Master -> REJECT",
        talentus and talentus["status"] == "REJECT",
        str(talentus and talentus["status"]),
    ))

    diox = by_fragment(results, "dioxines")
    tests.append(check(
        "SGS dioxines n'est PAS un job étudiant",
        diox and diox["status"] != "VERIFY",
        str(diox and diox["status"]),
    ))

    oud = by_fragment(results, "Data Analist | Oudenaarde")
    tests.append(check(
        "Oudenaarde Bachelor/Master n'est PAS REJECT Master",
        oud and oud["status"] != "REJECT",
        str(oud and oud["status"]),
    ))

    business_data = by_fragment(results, "Business Data Analyst")
    fake_tableau = (
        business_data
        and any(
            "tableau" in str(w).lower()
            for w in business_data.get("warnings", [])
        )
    )
    tests.append(check(
        "Business Data Analyst : pas de faux Tableau",
        business_data and not fake_tableau,
        str(business_data and business_data.get("warnings")),
    ))

    qc_level2 = by_fragment(results, "QC Lab Analyst level 2")
    tests.append(check(
        "QC Level 2 NL très fluide -> STRETCH_REVIEW",
        qc_level2 and qc_level2["status"] == "STRETCH_REVIEW",
        str(qc_level2 and qc_level2["status"]),
    ))

    qc_eurofins = next(
        (
            r for r in results
            if r.get("company") == "Eurofins"
            and r.get("title") == "QC Laborant"
        ),
        None,
    )
    tests.append(check(
        "Eurofins QC Laborant NL fluide -> STRETCH_REVIEW",
        qc_eurofins and qc_eurofins["status"] == "STRETCH_REVIEW",
        str(qc_eurofins and qc_eurofins["status"]),
    ))

    print()
    for key, value in s.items():
        print(f"{key:18s}: {value}")

    print()
    print(f"Checks : {sum(tests)}/{len(tests)}")

    if not all(tests):
        raise SystemExit("❌ CURRENT BATCH RECHECK V1.1 NON VALIDÉ.")

    print("✅ CURRENT BATCH RECHECK V1.1 VALIDÉ.")


if __name__ == "__main__":
    main()
