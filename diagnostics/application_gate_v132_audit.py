"""
APPLICATION GATE V1.3.2 - DIAGNOSTIC PRODUCTION

Usage:
    python -m diagnostics.application_gate_v132_audit
"""

from types import SimpleNamespace

from matching.application_gate_v13 import (
    GATE_VERSION,
    detect_required_experience_years_v132,
    evaluate_application_gate,
)


def make_job(title, description, *, location="Bruxelles, Belgique"):
    return SimpleNamespace(
        title=title,
        description=description,
        detail_matching_text=description,
        experience_requirement=None,
        degree_requirement=None,
        language=None,
        contract_type="Full-time",
        restriction=None,
        source="SMARTRECRUITERS",
        source_eligibility_status="ELIGIBLE",
        source_eligibility_reason=None,
        company="TEST",
        location=location,
        url="https://example.test",
        canonical_job_id=1,
    )


def match(score=80, family="chemistry_lab"):
    return {
        "score": float(score),
        "best_family": family,
        "provisional": False,
        "confidence_label": "Élevée",
    }


STATUS_TESTS = [
    (
        "QC LAB APPLY",
        make_job("QC Laborant", "Bachelor in chemistry. GMP and HPLC."),
        match(96),
        "APPLY",
    ),
    (
        "REAL ESTATE REJECT",
        make_job("Real Estate Portfolio Manager", "Manage leases and properties."),
        match(78, "hybrid_data_pharma"),
        "REJECT",
    ),
    (
        "REAL ESTATE DATA ALLOW",
        make_job("Real Estate Data Analyst", "Bachelor accepted. SQL and Power BI."),
        match(82, "data_analytics"),
        "APPLY",
    ),
    (
        "V.I.E REJECT",
        make_job("Performance Analyst - V.I.E Programme", "KPI reporting."),
        match(80, "data_analytics"),
        "REJECT",
    ),
    (
        "FRENCH VIE ALLOW",
        make_job("Quality Coordinator", "Améliorer la qualité de vie au travail."),
        match(78, "quality"),
        "APPLY",
    ),
    (
        "MASTER QUALIFICATION REJECT",
        make_job("Scientist biochimie", "Master avec expérience ou Docteur en biochimie."),
        match(90),
        "REJECT",
    ),
    (
        "BACHELOR OR MASTER ALLOW",
        make_job("Data Analyst", "Bachelor or Master's degree in data."),
        match(85, "data_analytics"),
        "APPLY",
    ),
    (
        "MASTER PLUS ALLOW",
        make_job("QC Analyst", "Bachelor required. A Master's degree is a plus."),
        match(85, "pharma_qc"),
        "APPLY",
    ),
    (
        "MASTER PREFERRED ALLOW",
        make_job("QC Analyst", "Bachelor required. Master's degree preferred."),
        match(85, "pharma_qc"),
        "APPLY",
    ),
    (
        "MASTER REQUIRED REJECT",
        make_job("QC Scientist", "A Master's degree in chemistry is required."),
        match(90),
        "REJECT",
    ),
    (
        "MASTER DATA ALLOW",
        make_job("Master Data Officer", "Bachelor accepted. Master Data governance."),
        match(85, "data_analytics"),
        "APPLY",
    ),
    (
        "MEDICAL GUARD PRESERVED",
        make_job(
            "Technologue de laboratoire médical",
            "Agrément et visa obligatoires pour exercer la fonction.",
        ),
        match(91),
        "REJECT",
    ),
    (
        "DAJOBS 70 YEARS ALLOW",
        make_job(
            "Laborantin junior",
            "Avec plus de 70 ans d'expérience dans le recrutement, "
            "notre agence accompagne les candidats. "
            "Profil junior accepté, une première expérience est un plus.",
        ),
        match(74),
        "APPLY",
    ),
    (
        "REAL QC 5 YEARS REJECT",
        make_job(
            "QC Analyst",
            "Minimum 5 ans d'expérience en laboratoire QC.",
        ),
        match(92, "pharma_qc"),
        "REJECT",
    ),
    (
        "DATA 2 YEARS STRETCH",
        make_job(
            "Data Analyst",
            "2 years of experience in data analytics. SQL and Power BI.",
        ),
        match(84, "data_analytics"),
        "STRETCH",
    ),
]


DETECTOR_TESTS = [
    (
        "70 ANS AGENCE IGNORÉS",
        "Avec plus de 70 ans d'expérience dans le recrutement, DaJobs accompagne les candidats.",
        None,
        None,
    ),
    (
        "20 ANS RECRUTEMENT IGNORÉS",
        "Our company has 20 years of experience in recruitment.",
        None,
        None,
    ),
    (
        "2 ANS CANDIDAT",
        "You have 2 years of experience in data analytics.",
        2,
        None,
    ),
    (
        "5 ANS QC",
        "Minimum 5 ans d'expérience en laboratoire QC.",
        5,
        None,
    ),
    (
        "3 ANS OPTIONNELS",
        "3 years of experience is a plus.",
        None,
        3,
    ),

    # ------------------------------------------------------------------
    # Un age minimum n'est pas une experience
    # ------------------------------------------------------------------
    # Mesure du 10 septembre 2026 sur la file reelle : douze offres
    # portaient une exigence d'experience invraisemblable, et le gate les
    # ecartait ou les envoyait en verification. Aucune n'exigeait ce que le
    # gate y lisait.
    #
    # Les motifs « minimum N ans » et « minstens N jaar » n'exigent pas le
    # mot experience : l'age d'acces d'un job etudiant passait pour dix-huit
    # annees de metier.
    (
        "AGE ETUDIANT FR",
        "Etudiant Caisse. Vous devez avoir minimum 18 ans pour ce poste.",
        None,
        None,
    ),
    (
        "AGE ETUDIANT NL",
        "Jobstudent logistics. Minstens 18 jaar oud.",
        None,
        None,
    ),
    (
        "AGE 18+ DANS LE TITRE",
        "Jobstudent Exterioo logistics 18+. Minimum 18 ans requis.",
        None,
        None,
    ),
    # Le plafond etait a 40, ce qui laissait passer exactement 40. Ce cas
    # ecartait un Laboratory Technician - Cell Culture note 93.
    (
        "40 ANS = REMPLISSAGE",
        "Notre laboratoire dispose de 40 ans d'experience en culture "
        "cellulaire.",
        None,
        None,
    ),
    (
        "20 ANS = REMPLISSAGE",
        "Une equipe forte de 20 ans d'experience vous accueille.",
        None,
        None,
    ),

    # ------------------------------------------------------------------
    # Ce qui doit continuer de passer
    # ------------------------------------------------------------------
    # Un garde-fou qui avale les vraies exigences serait pire que le defaut
    # qu'il corrige : ces cas verifient qu'il ne mord pas trop large.
    (
        "AGE + EXPERIENCE REELLE",
        "Vous devez avoir minimum 4 ans d'experience en QC.",
        4,
        None,
    ),
    (
        "EXIGENCE SANS LE MOT EXPERIENCE",
        "Minimum 3 ans dans un poste similaire en laboratoire.",
        3,
        None,
    ),
    (
        "15 ANS RESTE PLAUSIBLE",
        "Ingenieur : minimum 15 ans d'experience exigee.",
        15,
        None,
    ),
    (
        "15 ANS SENIOR RÉELS",
        "Minimum 15 years of experience in IT programme management.",
        15,
        None,
    ),
]


def main():
    print("=" * 88)
    print("APPLICATION GATE V1.3.2 - DIAGNOSTIC PRODUCTION")
    print("=" * 88)
    print("Version :", GATE_VERSION)
    print()

    passed = 0
    total = 0

    for name, job, result, expected in STATUS_TESTS:
        total += 1
        gate = evaluate_application_gate(job, result)
        obtained = gate["status"]
        ok = obtained == expected
        passed += int(ok)
        print(
            f"{'✅' if ok else '❌'} "
            f"{name:<34} attendu={expected:<7} obtenu={obtained:<7}"
        )
        if not ok:
            print("   hard    :", gate.get("hard_reasons"))
            print("   warnings:", gate.get("warnings"))

    print()
    print("EXTRACTEUR D'EXPÉRIENCE")
    print("-" * 88)

    for name, text, expected_mandatory, expected_optional in DETECTOR_TESTS:
        total += 1
        result = detect_required_experience_years_v132(text)
        ok = (
            result["mandatory"] == expected_mandatory
            and result["optional"] == expected_optional
        )
        passed += int(ok)
        print(
            f"{'✅' if ok else '❌'} {name:<34} "
            f"mandatory={result['mandatory']} optional={result['optional']}"
        )

    print()
    print(f"Tests : {passed}/{total}")

    if passed != total:
        raise SystemExit("❌ APPLICATION GATE V1.3.2 NON VALIDÉ.")

    print("✅ APPLICATION GATE V1.3.2 VALIDÉ.")


if __name__ == "__main__":
    main()
