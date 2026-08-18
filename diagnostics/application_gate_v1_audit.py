"""Diagnostic rapide Application Gate V1.2."""

from types import SimpleNamespace

from matching.application_gate import evaluate_application_gate


def make_job(title, description, *, source="FOREM", status="ELIGIBLE", reason=None, language=None):
    job = SimpleNamespace(
        title=title,
        description=description,
        detail_matching_text=description,
        experience_requirement=None,
        degree_requirement=None,
        language=language,
        contract_type="CDI",
        restriction=None,
        source=source,
        source_eligibility_status=status,
        source_eligibility_reason=reason,
        company="TEST",
        location="Bruxelles, Belgique",
        url="https://example.test/job",
        canonical_job_id=1,
    )
    return job


def match(score, family, provisional=False):
    return {
        "score": float(score),
        "best_family": family,
        "provisional": provisional,
        "confidence_label": "Élevée",
    }


TESTS = [
    (
        "QC LAB APPLY",
        make_job(
            "Technicien de laboratoire QC",
            "Bachelier en chimie. HPLC, GMP et LIMS. 2 ans d'expérience en laboratoire.",
        ),
        match(96, "chemistry_lab"),
        "APPLY",
    ),
    (
        "TECHNOLOGUE AGREMENT REJECT",
        make_job(
            "Technologue de laboratoire médical",
            "Agrément et visa obligatoires pour exercer la fonction.",
        ),
        match(91, "chemistry_lab"),
        "REJECT",
    ),
    (
        "MASTER OBLIGATOIRE REJECT",
        make_job(
            "Data Analyst",
            "Un diplôme de Master est obligatoire pour cette fonction.",
        ),
        match(94, "data_analytics"),
        "REJECT",
    ),
    (
        "BACHELOR OU MASTER APPLY",
        make_job(
            "Data Analyst Junior",
            "Bachelor ou Master en data, statistiques ou domaine similaire. SQL et Power BI.",
        ),
        match(90, "data_analytics"),
        "APPLY",
    ),
    (
        "SENIOR DATA REJECT",
        make_job(
            "Senior Data Analyst",
            "Minimum 5 years of experience in data analytics.",
        ),
        match(55, "data_analytics"),
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
    (
        "QC 4 YEARS STRETCH",
        make_job(
            "QC Analyst",
            "4 ans d'expérience en contrôle qualité sont demandés. HPLC et GMP.",
        ),
        match(88, "pharma_qc"),
        "STRETCH",
    ),
    (
        "QC 5 YEARS REJECT",
        make_job(
            "QC Analyst",
            "Minimum 5 ans d'expérience en laboratoire QC.",
        ),
        match(92, "pharma_qc"),
        "REJECT",
    ),
    (
        "NEDERLANDS C1 REJECT",
        make_job(
            "Laboratory Analyst",
            "Nederlands C1 is verplicht. HPLC en GMP.",
        ),
        match(90, "chemistry_lab"),
        "REJECT",
    ),
    (
        "AZURE REQUIRED STRETCH",
        make_job(
            "Junior Data Engineer",
            "Azure is required. Python and SQL are required.",
        ),
        match(82, "data_engineering"),
        "STRETCH",
    ),
    (
        "AZURE DATABRICKS REQUIRED REJECT",
        make_job(
            "Data Engineer",
            "Azure and Databricks are mandatory. Python and SQL are required.",
        ),
        match(88, "data_engineering"),
        "REJECT",
    ),
    (
        "SOURCE INELIGIBLE REJECT",
        make_job(
            "Data Analyst",
            "SQL et Power BI.",
            source="TRAVAILLERPOUR",
            status="INELIGIBLE",
            reason="Diplôme Master ou supérieur obligatoire",
        ),
        match(95, "data_analytics"),
        "REJECT",
    ),
    (
        "PROVISIONAL VERIFY",
        make_job(
            "Technicien de laboratoire",
            "Description indisponible.",
        ),
        match(72, "chemistry_lab", provisional=True),
        "VERIFY",
    ),
    (
        "LOW FIT REJECT",
        make_job(
            "Inspecteur trains",
            "Inspection ferroviaire.",
        ),
        match(18, "quality"),
        "REJECT",
    ),
    (
        "LANGUAGE ATTRIBUTION ONLY NL",
        make_job(
            "Laboratory Analyst",
            "English B1. Nederlands C1 is verplicht. HPLC en GMP.",
        ),
        match(90, "chemistry_lab"),
        "REJECT",
    ),
    (
        "LANGUAGE C1 NON MANDATORY STRETCH",
        make_job(
            "Laboratory Analyst",
            "English C1. HPLC and GMP.",
        ),
        match(90, "chemistry_lab"),
        "STRETCH",
    ),
    (
        "DATA ENGINEER 100 NON JUNIOR STRETCH",
        make_job(
            "Cloud Big Data Engineer",
            "Python, SQL, cloud data pipelines and Power BI.",
        ),
        match(100, "data_engineering"),
        "STRETCH",
    ),
    (
        "JUNIOR DATA ENGINEER APPLY",
        make_job(
            "Junior Data Engineer",
            "Python, SQL and ETL. Bachelor accepted.",
        ),
        match(88, "data_engineering"),
        "APPLY",
    ),
    (
        "LOW FIT CERTIFICATE REJECT",
        make_job(
            "Inspecteur trains",
            "Un certificat est obligatoire pour la fonction.",
        ),
        match(28, "quality"),
        "REJECT",
    ),

    (
        "FABRICATION NOT FABRIC APPLY",
        make_job(
            "Technicien Chimiste Laboratoire",
            "Fabrication obligatoire selon GMP et HPLC.",
        ),
        match(95, "chemistry_lab"),
        "APPLY",
    ),
    (
        "REAL FABRIC REQUIRED STRETCH",
        make_job(
            "Junior Data Engineer",
            "Microsoft Fabric is required. Python and SQL.",
        ),
        match(90, "data_engineering"),
        "STRETCH",
    ),
    (
        "STUDENT LAB VERIFY",
        make_job(
            "Student laborant (bachelor/master)",
            "Laboratoire QC.",
        ),
        match(85, "chemistry_lab"),
        "VERIFY",
    ),
    (
        "CANADA REJECT",
        make_job(
            "Technicien contrôle qualité",
            "Contrôle qualité laboratoire.",
        ),
        match(90, "quality"),
        "REJECT",
        # Location modifiée juste après création dans le runner.
    ),
    (
        "GENERIC ISO CERTIFICATION APPLY",
        make_job(
            "Quality Coordinator",
            "Responsable du maintien de la certification ISO 9001 obligatoire pour le site.",
        ),
        match(90, "quality"),
        "APPLY",
    ),
    (
        "PERSONAL PERMIT VERIFY",
        make_job(
            "Technicien de laboratoire",
            "Permis B obligatoire pour les déplacements.",
        ),
        match(90, "chemistry_lab"),
        "VERIFY",
    ),
    (
        "FILM LAB REJECT",
        make_job(
            "Technicien de laboratoire film",
            "Traitement et développement de films cinéma.",
        ),
        match(90, "chemistry_lab"),
        "REJECT",
    ),
    (
        "MASTER DATA NOT MASTER DEGREE",
        make_job(
            "Master Data Officer",
            "Bachelor accepté. Master Data governance, SQL et reporting.",
        ),
        match(85, "data_analytics"),
        "APPLY",
    ),
    (
        "AGENCY 20 YEARS NOT REQUIREMENT",
        make_job(
            "Kwaliteitscontrole",
            "Notre agence de recrutement possède 20 ans d'expérience dans le recrutement. Contrôle qualité.",
        ),
        match(60, "quality"),
        "STRETCH",
    ),

]


def main():
    print("=" * 76)
    print("APPLICATION GATE V1.2 - DIAGNOSTIC")
    print("=" * 76)
    print()

    passed = 0

    for name, job, result, expected in TESTS:
        if name == "CANADA REJECT":
            job.location = "Québec, Canada"
        gate = evaluate_application_gate(job, result)
        ok = gate["status"] == expected
        passed += int(ok)
        marker = "✅" if ok else "❌"
        print(
            f"{marker} {name:<35} "
            f"attendu={expected:<7} obtenu={gate['status']:<7} "
            f"gate={gate['priority_score']:>5.1f}"
        )
        if not ok:
            print("   hard    :", gate["hard_reasons"])
            print("   warnings:", gate["warnings"])
            print("   reasons :", gate["reasons"])

    print()
    print(f"Tests : {passed}/{len(TESTS)}")

    if passed == len(TESTS):
        print("✅ APPLICATION GATE V1.2 VALIDÉ SUR LE DIAGNOSTIC.")
        return 0

    print("❌ APPLICATION GATE V1.2 NON VALIDÉ.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
