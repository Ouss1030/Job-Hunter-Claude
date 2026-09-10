"""
APPLICATION GATE V1.3.3 - DIAGNOSTIC

  BLOC A  non-régression : les 21 cas du diagnostic V1.3.2, importés tels
          quels depuis diagnostics/application_gate_v132_audit.py
  BLOC B  correctifs V1.3.3

Usage :
    python -m diagnostics.application_gate_v133_audit
"""

from matching.application_gate_v133 import (
    GATE_VERSION,
    detect_required_experience_years_v133,
    evaluate_application_gate,
)

from diagnostics.application_gate_v132_audit import (
    DETECTOR_TESTS as DETECTOR_TESTS_V132,
    STATUS_TESTS as STATUS_TESTS_V132,
    make_job,
    match,
)


# ============================================================
# BLOC B - CORRECTIFS V1.3.3
# ============================================================

BOILERPLATE_FORUM = (
    "Forum Jobs c'est 48 agences et deux valeurs clés : passion et "
    "expérience. Après plus de 20 ans d'expérience et plus de 200 "
    "collaborateurs, nous avons pu devenir leader sur le marché du "
    "travail. Vous effectuez le contrôle qualité des produits en "
    "laboratoire. Un bachelier est demandé."
)

VIE_MENTION_RH = (
    "You will support the HR team. Other duties include the review of "
    "internship agreements and V.I.E (Volontariat International en "
    "Entreprise) programme applications, and collaborating with "
    "universities. Bachelor in chemistry, laboratory quality control."
)


STATUS_TESTS_V133 = [
    # --- correctif 1 site A : marqueur diplôme en sous-chaîne ---
    (
        "MASTER PHARMA PLUS REJECT",
        make_job(
            "QC Scientist",
            "Master's degree in Pharma plus GMP knowledge is required.",
        ),
        match(90, "pharma_qc"),
        "REJECT",
    ),
    (
        "MASTER DATA PLUS REJECT",
        make_job(
            "Lab Analyst",
            "A Master degree in data plus 3 years of experience is required.",
        ),
        match(90, "chemistry_lab"),
        "REJECT",
    ),

    # --- correctif 2 : auto-présentation d'agence ---
    (
        "AGENCE 20 ANS ALLOW",
        make_job("kwaliteitscontrole (H/F/X)", BOILERPLATE_FORUM),
        match(80, "quality"),
        "APPLY",
    ),

    # --- correctif 3 : Master Data métier ---
    (
        "MASTER DATA REQUIRED ALLOW",
        make_job(
            "Data Steward",
            "Bachelor accepted. Master Data governance experience is "
            "required, SQL and Power BI.",
        ),
        match(85, "data_analytics"),
        "APPLY",
    ),

    # --- correctif 4 : VIE en capitales ---
    (
        "VIE MAJUSCULE ALLOW",
        make_job(
            "LABORANTIN - SCIENCES DE LA VIE",
            "Bachelier en chimie. Analyses de contrôle qualité.",
        ),
        match(90, "chemistry_lab"),
        "APPLY",
    ),

    # --- correctif 6 : exigence linguistique sans niveau CECR ---
    (
        "NL GOEDE KENNIS REJECT",
        make_job("Laborant",
                 "Bachelor chemie. Je hebt een goede kennis Nederlands. Labo analyses."),
        match(90, "chemistry_lab"),
        "REJECT",
    ),
    (
        "NL MAITRISE EXIGEE REJECT",
        make_job("Laborantin",
                 "Laborantin QC. Maîtrise du néerlandais exigée. Analyses HPLC."),
        match(90, "chemistry_lab"),
        "REJECT",
    ),
    (
        "NL TWEETALIG REJECT",
        make_job("Laborant",
                 "Laborant. Tweetalig NL/FR vereist voor deze functie. Labo."),
        match(90, "chemistry_lab"),
        "REJECT",
    ),
    (
        "NL ATOUT ALLOW",
        make_job("Laborantin",
                 "Laborantin QC. La maîtrise du néerlandais constitue un atout. HPLC."),
        match(90, "chemistry_lab"),
        "APPLY",
    ),
    (
        "EN GOOD KNOWLEDGE ALLOW",
        make_job("Lab technician",
                 "Lab technician. Good knowledge of English required. HPLC analyses."),
        match(90, "chemistry_lab"),
        "APPLY",
    ),

    # --- correctif 7 : stages et alternances ---
    (
        "STAGE FR VERIFY",
        make_job("Stage : Data Analyst - Optimisation",
                 "Bachelier en cours. Analyses de données, Power BI."),
        match(95, "data_analytics"),
        # VERIFY et non REJECT : le Gate signale le statut étudiant sans
        # exclure, conformément au principe « ne jamais écarter sur un doute ».
        "VERIFY",
    ),
    (
        "INTERNSHIP EN VERIFY",
        make_job("Internship: Global Supply Chain Planning",
                 "Bachelor student. Supply chain analysis."),
        match(90, "data_analytics"),
        "VERIFY",
    ),
    (
        "ALTERNANCE VERIFY",
        make_job("Stage en alternance : Business Analyst",
                 "Étudiant. Analyse de données et reporting."),
        match(90, "data_analytics"),
        "VERIFY",
    ),
    (
        "STAGE PILOTE ALLOW",
        make_job("Analyste de stage-pilote",
                 "Bachelier en chimie. Suivi des analyses du pilote de production."),
        match(90, "chemistry_lab"),
        "APPLY",
    ),
    (
        "POSTE FIXE ALLOW",
        make_job("Technicien(ne) QA (Contrat de remplacement)",
                 "Bachelier en chimie. Contrôle qualité, GMP, analyses HPLC."),
        match(90, "pharma_qc"),
        "APPLY",
    ),

    # --- correctif 5 : mention V.I.E non auto-référentielle ---
    (
        "VIE MENTION RH ALLOW",
        make_job("Lab Quality Officer", VIE_MENTION_RH),
        match(85, "quality"),
        "APPLY",
    ),
]


DETECTOR_TESTS_V133 = [
    # correctif 1 site B : "pharmA PLUS" ne doit pas rendre l'exigence optionnelle
    (
        "5 ANS PHARMA PLUS OBLIGATOIRES",
        "Minimum 5 ans d'expérience en pharma plus GMP requise.",
        5,
        None,
    ),
    (
        "5 ANS DATA PLUS OBLIGATOIRES",
        "5 years of experience in data plus SQL is required.",
        5,
        None,
    ),
    # correctif 2 : auto-présentation d'agence ignorée
    (
        "AGENCE 20 ANS + COLLABORATEURS",
        "Après plus de 20 ans d'expérience et plus de 200 collaborateurs, "
        "nous avons pu devenir leader.",
        None,
        None,
    ),
    (
        "AGENCE 48 AGENCES",
        "Forum Jobs c'est 48 agences et 15 ans d'expérience.",
        None,
        None,
    ),
    # non-régression : un vrai optionnel reste optionnel
    (
        "3 ANS UN PLUS RESTE OPTIONNEL",
        "3 ans d'expérience en laboratoire est un plus.",
        None,
        3,
    ),
]


def run_status(titre, tests):
    passed = 0
    print(titre)
    print("-" * 84)
    for name, job, result, expected in tests:
        gate = evaluate_application_gate(job, result)
        obtained = gate["status"]
        ok = obtained == expected
        passed += int(ok)
        print(f"{'✅' if ok else '❌'} {name:<38} "
              f"attendu={expected:<7} obtenu={obtained:<7}")
        if not ok:
            print("   hard :", gate.get("hard_reasons"))
    print()
    return passed


def run_detector(titre, tests):
    passed = 0
    print(titre)
    print("-" * 84)
    for name, text, exp_m, exp_o in tests:
        r = detect_required_experience_years_v133(text)
        ok = r["mandatory"] == exp_m and r["optional"] == exp_o
        passed += int(ok)
        print(f"{'✅' if ok else '❌'} {name:<38} "
              f"mandatory={str(r['mandatory']):<6} optional={str(r['optional']):<6}")
        if not ok:
            print(f"   attendu mandatory={exp_m} optional={exp_o}")
    print()
    return passed


def main():
    print("=" * 84)
    print(f"APPLICATION GATE V{GATE_VERSION} - DIAGNOSTIC")
    print("=" * 84)
    print()

    a1 = run_status("BLOC A1 - NON-RÉGRESSION statuts (V1.3.2)", STATUS_TESTS_V132)
    a2 = run_detector("BLOC A2 - NON-RÉGRESSION détecteur (V1.3.2)", DETECTOR_TESTS_V132)
    b1 = run_status("BLOC B1 - CORRECTIFS V1.3.3 statuts", STATUS_TESTS_V133)
    b2 = run_detector("BLOC B2 - CORRECTIFS V1.3.3 détecteur", DETECTOR_TESTS_V133)

    na = len(STATUS_TESTS_V132) + len(DETECTOR_TESTS_V132)
    nb = len(STATUS_TESTS_V133) + len(DETECTOR_TESTS_V133)
    oka, okb = a1 + a2, b1 + b2

    print("=" * 84)
    print(f"Non-régression V1.3.2 : {oka}/{na}")
    print(f"Correctifs V1.3.3     : {okb}/{nb}")
    print(f"Tests                 : {oka + okb}/{na + nb}")
    print("=" * 84)

    if oka != na:
        raise SystemExit("❌ RÉGRESSION SUR LE V1.3.2 - V1.3.3 REFUSÉ.")
    if okb != nb:
        raise SystemExit("❌ APPLICATION GATE V1.3.3 NON VALIDÉ.")

    print("✅ APPLICATION GATE V1.3.3 VALIDÉ.")


if __name__ == "__main__":
    main()
