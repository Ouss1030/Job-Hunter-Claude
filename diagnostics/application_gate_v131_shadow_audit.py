"""
APPLICATION GATE V1.3.1 SHADOW - DIAGNOSTIC

Usage :
    python -m diagnostics.application_gate_v131_shadow_audit
"""

from types import SimpleNamespace

from matching.application_gate_v13_overlay import (
    apply_overlay_to_gate,
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
    # V.I.E réels
    (
        "V.I.E POINTS REJECT",
        make_job(
            "Performance Analyst - V.I.E Programme",
            "Data analysis and KPI reporting.",
        ),
        "REJECT",
    ),
    (
        "VIE UPPERCASE REJECT",
        make_job(
            "Business Analyst - VIE Programme",
            "Data analysis.",
        ),
        "REJECT",
    ),
    (
        "OFFICIAL VIE BODY REJECT",
        make_job(
            "Performance Analyst",
            "Contrat de volontariat international en entreprise.",
        ),
        "REJECT",
    ),

    # Faux positifs qui ont réellement cassé le shadow V1.3
    (
        "VIE PROFESSIONNELLE ALLOW",
        make_job(
            "Quality Coordinator",
            "Améliorer la qualité de vie professionnelle et la conformité.",
        ),
        "APPLY",
    ),
    (
        "VIE QUOTIDIENNE ALLOW",
        make_job(
            "Technicien de laboratoire",
            "La sécurité fait partie de la vie quotidienne du laboratoire.",
        ),
        "APPLY",
    ),
    (
        "LIFE SCIENCES ALLOW",
        make_job(
            "Life Sciences Computer System Validation Engineer",
            "Validation de systèmes informatisés GxP.",
        ),
        "APPLY",
    ),

    # Règles V1.3 conservées
    (
        "REAL ESTATE REJECT",
        make_job(
            "Real Estate Portfolio Manager",
            "Manage leases and property portfolio.",
        ),
        "REJECT",
    ),
    (
        "MASTER QUALIFICATION REJECT",
        make_job(
            "Scientist",
            "Qualifications: Holds master's degree in pharmaceutical sciences.",
        ),
        "REJECT",
    ),
    (
        "BACHELOR OR MASTER ALLOW",
        make_job(
            "Data Analyst",
            "Qualifications: Bachelor or Master's degree in data.",
        ),
        "APPLY",
    ),
    (
        "MASTER PLUS ALLOW",
        make_job(
            "QC Analyst",
            "Bachelor in chemistry required. A Master's degree is a plus.",
        ),
        "APPLY",
    ),
]


def main():
    passed = 0

    print("=" * 84)
    print("APPLICATION GATE V1.3.1 SHADOW - DIAGNOSTIC")
    print("=" * 84)
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
            print("   overlay:", result.get("v13_overlay"))

    print()
    print(f"Tests : {passed}/{len(TESTS)}")

    if passed != len(TESTS):
        raise SystemExit("❌ GATE V1.3.1 SHADOW NON VALIDÉ.")

    print("✅ GATE V1.3.1 SHADOW VALIDÉ SUR LE DIAGNOSTIC.")


if __name__ == "__main__":
    main()
