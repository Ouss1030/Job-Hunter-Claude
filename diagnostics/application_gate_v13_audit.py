"""
APPLICATION GATE V1.3.1 - DIAGNOSTIC PRODUCTION
"""

from types import SimpleNamespace

from matching.application_gate_v13 import (
    evaluate_application_gate,
    detect_mandatory_master_v131,
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


def match(score=80, family="hybrid_data_pharma"):
    return {
        "score": float(score),
        "best_family": family,
        "provisional": False,
        "confidence_label": "Élevée",
    }


TESTS = [
    (
        "QC LAB APPLY",
        make_job(
            "QC Laborant",
            "Bachelor in chemistry. GMP, HPLC and laboratory quality control.",
        ),
        match(96, "chemistry_lab"),
        "APPLY",
    ),
    (
        "REAL ESTATE REJECT",
        make_job(
            "Real Estate Portfolio Manager",
            "Manage leases, landlords and property portfolio.",
        ),
        match(78, "hybrid_data_pharma"),
        "REJECT",
    ),
    (
        "REAL ESTATE DATA ALLOW",
        make_job(
            "Real Estate Data Analyst",
            "Bachelor accepted. SQL, Power BI and portfolio analytics.",
        ),
        match(82, "data_analytics"),
        "APPLY",
    ),
    (
        "V.I.E REJECT",
        make_job(
            "Performance Analyst - V.I.E Programme",
            "Data analysis and KPI reporting.",
        ),
        match(80, "data_analytics"),
        "REJECT",
    ),
    (
        "FRENCH VIE ALLOW",
        make_job(
            "Quality Coordinator",
            "Améliorer la qualité de vie professionnelle et la conformité.",
        ),
        match(78, "quality"),
        "APPLY",
    ),
    (
        "MASTER QUALIFICATION REJECT",
        make_job(
            "Scientist biochimie",
            "Qualifications: Master avec expérience ou Docteur en biochimie.",
        ),
        match(90, "chemistry_lab"),
        "REJECT",
    ),
    (
        "BACHELOR OR MASTER ALLOW",
        make_job(
            "Data Analyst",
            "Qualifications: Bachelor or Master's degree in data.",
        ),
        match(85, "data_analytics"),
        "APPLY",
    ),
    (
        "MASTER PLUS ALLOW",
        make_job(
            "QC Analyst",
            "Bachelor in chemistry required. A Master's degree is a plus.",
        ),
        match(85, "pharma_qc"),
        "APPLY",
    ),
    (
        "MASTER PREFERRED ALLOW",
        make_job(
            "QC Analyst",
            "Bachelor required. Master's degree preferred.",
        ),
        match(85, "pharma_qc"),
        "APPLY",
    ),
    (
        "MASTER REQUIRED REJECT",
        make_job(
            "QC Scientist",
            "A Master's degree in chemistry is required.",
        ),
        match(90, "chemistry_lab"),
        "REJECT",
    ),
    (
        "MASTER DATA ALLOW",
        make_job(
            "Master Data Officer",
            "Bachelor accepted. Master Data governance, SQL and reporting.",
        ),
        match(85, "data_analytics"),
        "APPLY",
    ),
    (
        "V1.2 MEDICAL GUARD PRESERVED",
        make_job(
            "Technologue de laboratoire médical",
            "Agrément et visa obligatoires pour exercer la fonction.",
        ),
        match(91, "chemistry_lab"),
        "REJECT",
    ),
]


def main():
    passed = 0

    print("=" * 84)
    print("APPLICATION GATE V1.3.1 - DIAGNOSTIC PRODUCTION")
    print("=" * 84)
    print()

    for name, job, result, expected in TESTS:
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
            print("   overlay :", gate.get("v13_overlay"))

    print()
    print(f"Tests : {passed}/{len(TESTS)}")

    if passed != len(TESTS):
        raise SystemExit("❌ APPLICATION GATE V1.3.1 NON VALIDÉ.")

    print("✅ APPLICATION GATE V1.3.1 VALIDÉ.")


if __name__ == "__main__":
    main()
