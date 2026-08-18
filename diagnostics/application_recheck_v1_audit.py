"""
Diagnostic APPLICATION POST-REFRESH RECHECK V1

Usage:
    python -m diagnostics.application_recheck_v1_audit
"""

from applications.application_recheck import (
    medical_accreditation_block,
    youth_or_first_job_block,
    mandatory_master_block,
    explicit_student_role,
    mandatory_unknown_skill_block,
    obvious_live_domain_mismatch,
    strong_language_gap,
    evaluate_item,
)


def check(label, cond, detail=""):
    ok = bool(cond)
    print(f"{'✅' if ok else '❌'} {label}" + (f": {detail}" if detail else ""))
    return ok


def live_item(title="Technicien QC", family="chemistry_lab", text="Analyse HPLC GMP"):
    return {
        "stable_item_key": "ITEM_TEST",
        "title": title,
        "company": "Test",
        "location": "Bruxelles, Belgique",
        "url": "https://example.test",
        "queue_rank": 1,
        "queue_score": 120.0,
        "match_score": 90.0,
        "cv_track": "LAB_QC",
        "best_family": family,
        "job_live_status": "LIVE_CONFIRMED",
        "reason": "",
        "live_detail": {
            "matching_text": text,
            "structured": {
                "job_description": text,
                "profile": text,
            },
        },
    }


def main():
    tests = []

    tests.append(check(
        "Agrément médical non négociable détecté",
        medical_accreditation_block(
            "Technologue de laboratoire en chromatographie. "
            "Agrément de technologue de laboratoire en analyses médicales non négociable."
        )
    ))

    tests.append(check(
        "Restriction âge/startbaan détectée",
        youth_or_first_job_block(
            "Vanwege de startbaanovereenkomst kun je niet deelnemen als je 26 jaar wordt."
        )
    ))

    tests.append(check(
        "Master seul détecté",
        mandatory_master_block("Profil : Master diploma. Kennis Python.")
    ))

    tests.append(check(
        "Bachelor ou Master n'est pas bloqué",
        not mandatory_master_block(
            "Master- of bachelordiploma in chemie of wetenschappen."
        )
    ))

    tests.append(check(
        "Job étudiant détecté dans description",
        explicit_student_role("Voor deze functie zoeken we een student Quality Controller.")
    ))

    tests.append(check(
        "Empower must détecté",
        mandatory_unknown_skill_block("Ervaring met Empower is een must.") == "empower"
    ))

    aqua = live_item(
        title="AQUA VITAL - Technicien embouteillage et contrôle qualité microbiologique",
        family="quality",
        text=(
            "Expertise en électromécanique. Conduire la ligne d'embouteillage. "
            "Maintenance et réparations des fontaines."
        ),
    )
    tests.append(check(
        "Faux fit Aqua électromécanique détecté",
        obvious_live_domain_mismatch(aqua, aqua["live_detail"]["matching_text"]) is not None
    ))

    tests.append(check(
        "Néerlandais professionnel -> gap B1",
        bool(strong_language_gap("Je communiceert vlot in Nederlands."))
    ))

    ready = evaluate_item(live_item(text="Analyses HPLC, GC, GMP et traçabilité."))
    tests.append(check(
        "Offre labo propre -> READY_DOCUMENTS",
        ready["status"] == "READY_DOCUMENTS",
        ready["status"],
    ))

    reject_agrement = evaluate_item(live_item(
        title="Laborantin",
        text=(
            "En tant que technologue de laboratoire en chromatographie, "
            "vous êtes titulaire de l'agrément de technologue de laboratoire "
            "en analyses médicales (non négociable)."
        ),
    ))
    tests.append(check(
        "Agrément dans description même si titre Laborantin -> REJECT",
        reject_agrement["status"] == "REJECT",
        reject_agrement["status"],
    ))

    reject_age = evaluate_item(live_item(
        title="Junior data analyst",
        family="data_analytics",
        text=(
            "Ben je minder dan 25 jaar? Vanwege de startbaanovereenkomst "
            "kun je niet deelnemen als je 26 jaar wordt. Master diploma."
        ),
    ))
    tests.append(check(
        "Junior Data restriction âge -> REJECT",
        reject_age["status"] == "REJECT",
        reject_age["status"],
    ))

    verify_student = evaluate_item(live_item(
        title="Laborant",
        text="Voor een bedrijf zoeken we een student Quality Controller.",
    ))
    tests.append(check(
        "Student dans description -> VERIFY",
        verify_student["status"] == "VERIFY",
        verify_student["status"],
    ))

    failed = live_item()
    failed["job_live_status"] = "SOURCE_FETCH_FAILED"
    failed["reason"] = "Parsing Actiris impossible"
    out = evaluate_item(failed)
    tests.append(check(
        "Échec parser -> SOURCE_REVIEW",
        out["status"] == "SOURCE_REVIEW",
        out["status"],
    ))

    closed = live_item()
    closed["job_live_status"] = "SOURCE_FETCH_FAILED"
    closed["reason"] = "404 Client Error: Not Found"
    out = evaluate_item(closed)
    tests.append(check(
        "404 -> CLOSED_OR_REMOVED",
        out["status"] == "CLOSED_OR_REMOVED",
        out["status"],
    ))

    print()
    print(f"Tests synthétiques : {sum(tests)}/{len(tests)}")
    if all(tests):
        print("✅ APPLICATION RECHECK V1 VALIDÉ SUR LE DIAGNOSTIC.")
    else:
        raise SystemExit("❌ APPLICATION RECHECK V1 NON VALIDÉ.")


if __name__ == "__main__":
    main()
