"""
APPLICATION GATE V1.3 SHADOW - DIAGNOSTIC

Usage :
    python -m diagnostics.application_gate_v13_shadow_audit
"""

from types import SimpleNamespace

from matching.application_gate_v13_overlay import (
    apply_overlay_to_gate,
    detect_real_estate_domain_mismatch,
    detect_structured_master_requirement,
    detect_vie_ineligibility,
)


def make_job(title, description):
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
        location="Brussels, Belgique",
        url="https://example.test",
        canonical_job_id=1,
    )


def base_gate(status="APPLY"):
    return {
        "gate_version": "1.2",
        "status": status,
        "status_label": status,
        "priority_score": 90,
        "match_score": 75,
        "family": "hybrid_data_pharma",
        "reasons": (
            ["Aucun blocage fort détecté et correspondance métier suffisante"]
            if status == "APPLY"
            else []
        ),
        "warnings": [],
        "hard_reasons": [],
        "mandatory_master_detected": False,
    }


def match(score=75, family="hybrid_data_pharma"):
    return {
        "score": float(score),
        "best_family": family,
        "provisional": False,
    }


TESTS = [
    (
        "REAL ESTATE REJECT",
        make_job(
            "Real Estate Portfolio Manager",
            "Manage leases, landlords and property portfolio."
        ),
        "REJECT",
    ),
    (
        "REAL ESTATE DATA ALLOW",
        make_job(
            "Real Estate Data Analyst",
            "SQL, Power BI and portfolio analytics."
        ),
        "APPLY",
    ),
    (
        "VIE REJECT",
        make_job(
            "Performance Analyst - V.I.E Programme",
            "Data analysis, KPI reporting and Power BI."
        ),
        "REJECT",
    ),
    (
        "MASTER QUALIFICATIONS REJECT",
        make_job(
            "Scientist",
            "Qualifications: Master's degree in chemistry or pharmaceutical sciences."
        ),
        "REJECT",
    ),
    (
        "MASTER WITH EXPERIENCE REJECT",
        make_job(
            "Scientist biochimie",
            "Qualifications: Master avec expérience ou Docteur en biochimie."
        ),
        "REJECT",
    ),
    (
        "BACHELOR OR MASTER ALLOW",
        make_job(
            "Data Analyst",
            "Qualifications: Bachelor or Master's degree in data or statistics."
        ),
        "APPLY",
    ),
    (
        "MASTER PLUS ALLOW",
        make_job(
            "QC Analyst",
            "Bachelor in chemistry required. A Master's degree is a plus."
        ),
        "APPLY",
    ),
    (
        "MASTER DATA ALLOW",
        make_job(
            "Master Data Officer",
            "Bachelor accepted. Master Data governance, SQL and reporting."
        ),
        "APPLY",
    ),
]


def main():
    passed = 0

    print("=" * 80)
    print("APPLICATION GATE V1.3 SHADOW - DIAGNOSTIC")
    print("=" * 80)
    print()

    for name, job, expected in TESTS:
        result = apply_overlay_to_gate(
            job,
            match(),
            base_gate("APPLY"),
        )
        obtained = result["status"]
        ok = obtained == expected
        passed += int(ok)

        print(
            f"{'✅' if ok else '❌'} "
            f"{name:<34} attendu={expected:<7} obtenu={obtained:<7}"
        )

        if not ok:
            print("   hard:", result["hard_reasons"])
            print("   overlay:", result["v13_overlay"])

    print()
    print(f"Tests : {passed}/{len(TESTS)}")

    if passed != len(TESTS):
        raise SystemExit("❌ GATE V1.3 SHADOW NON VALIDÉ.")

    print("✅ GATE V1.3 SHADOW VALIDÉ SUR LE DIAGNOSTIC.")


if __name__ == "__main__":
    main()
