"""
Diagnostic FINAL APPLICATION POOL V1.1

Usage :
    python -m diagnostics.final_application_pool_v11_audit
"""

from applications.final_application_pool import (
    final_guard,
    duplicate_decision,
    recompute_item,
)


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f": {detail}" if detail else ""))
    return ok


def make_item(title, description, location="Bruxelles", origin="READY_DOCUMENTS"):
    return {
        "title": title,
        "description": description,
        "location": location,
        "pool_origin": origin,
        "track": "LAB_QC",
        "cv_track": "LAB_QC",
        "final_score": 120.0,
        "queue_score": 110.0,
        "match_score": 90.0,
        "company": "Test",
        "url": "https://example.test/" + title.replace(" ", "_"),
        "application_group_id": "",
    }


def main():
    tests = []

    forklift = make_item(
        "Opérateur de production secteur chimie",
        "Vous possédez le brevet cariste frontal. Brevet obligatoire.",
        "Louvain-la-Neuve, 1348",
    )
    g = final_guard(forklift)
    tests.append(check(
        "Brevet cariste obligatoire -> VERIFY",
        g["guard_level"] == "VERIFY",
        str(g),
    ))

    dutch = make_item(
        "Laborant",
        "Compétences linguistiques Néérlandais C1. Zeer goed Nederlands.",
        "Zonhoven, 3520",
    )
    g = final_guard(dutch)
    tests.append(check(
        "NL C1 avec candidat B1 -> REVIEW",
        g["guard_level"] == "REVIEW",
        str(g),
    ))

    mechanical = make_item(
        "Collaborateur contrôle qualité",
        "Aéronautique et défense. Contrôle tridimensionnel MMT, GD&T, "
        "micromètres, rugosimètres et lecture de plans complexes.",
        "Verviers",
    )
    g = final_guard(mechanical)
    tests.append(check(
        "Métrologie mécanique -> BLOCK",
        g["guard_level"] == "BLOCK",
        str(g),
    ))

    cell = make_item(
        "Laboratory Technician - Cell Culture",
        "Performing cell passages to support bioassays.",
        "Thuin",
    )
    g = final_guard(cell)
    tests.append(check(
        "Cell culture non démontré -> REVIEW",
        g["guard_level"] == "REVIEW",
        str(g),
    ))

    hospital = make_item(
        "Coordinateur Qualité",
        "Institution hospitalière. Politique qualité et sécurité des soins. "
        "Gestion des événements indésirables associés aux soins et patients.",
        "Watermael-Boitsfort",
    )
    g = final_guard(hospital)
    tests.append(check(
        "Qualité hospitalière -> REVIEW",
        g["guard_level"] == "REVIEW",
        str(g),
    ))

    electrical = make_item(
        "Assistant Technique Assurance Qualité",
        "Bachelier en Électricité, Électromécanique ou Instrumentation. "
        "Suivi des équipements électriques et pièces de réserve.",
        "La Louvière",
    )
    g = final_guard(electrical)
    tests.append(check(
        "QA électricité hors diplôme -> BLOCK",
        g["guard_level"] == "BLOCK",
        str(g),
    ))

    a = make_item(
        "Laborantin CESS",
        ("Technicien chimiste en laboratoire R&D. Tests stabilité formulation. "
         "Traçabilité Excel. Formation CESS chimie. ") * 15,
        "Spa, 4900",
    )
    b = make_item(
        "Laborantin CESS H/F/X",
        ("Technicien chimiste en laboratoire R&D. Tests stabilité formulation. "
         "Traçabilité Excel. Formation CESS chimie. ") * 15,
        "SPA",
    )
    decision, sim, method = duplicate_decision(a, b)
    tests.append(check(
        "Même mission Spa cross-source -> HOLD",
        decision == "HOLD",
        f"{decision} {sim} {method}",
    ))

    c = make_item(
        "Laborantin",
        "Analyse microbiologique produits alimentaires et prélèvements." * 10,
        "Brugge",
    )
    decision, _, _ = duplicate_decision(a, c)
    tests.append(check(
        "Missions distinctes -> pas HOLD",
        decision != "HOLD",
        decision,
    ))

    direct = recompute_item(dutch)
    tests.append(check(
        "REVIEW ne reste pas APPLY_NOW",
        direct["recommended_action_v11"] == "REVIEW_FIRST",
        direct["recommended_action_v11"],
    ))

    prod_hard = make_item(
        "Opérateur de synthèse",
        "Expérience probante en tant qu'opérateur de synthèse indispensable. "
        "Vous justifiez d'une expérience de 3 à 5 ans dans un environnement de production.",
        "Lessines",
    )
    prod_hard["track"] = "PRODUCTION_SCIENCE"
    g = final_guard(prod_hard)
    tests.append(check(
        "Production 3-5 ans indispensable -> BLOCK",
        g["guard_level"] == "BLOCK",
        str(g),
    ))

    prod_review = make_item(
        "Opérateur technique de production",
        "Profil : expérience en environnement de production industrielle pharmaceutique ou chimie.",
        "Brabant Wallon",
    )
    prod_review["track"] = "PRODUCTION_SCIENCE"
    g = final_guard(prod_review)
    tests.append(check(
        "Expérience production demandée sans durée -> REVIEW",
        g["guard_level"] == "REVIEW",
        str(g),
    ))

    clean = make_item(
        "Technicien laboratoire HPLC",
        "Analyses HPLC UPLC. GMP. Bachelier chimie. Deux ans QC pharma.",
        "Anderlecht, 1070",
    )
    x = recompute_item(clean)
    tests.append(check(
        "Bon HPLC sans blocage reste candidatable",
        x["guard_level"] == "PASS",
        str(x),
    ))

    print()
    print(f"Tests synthétiques : {sum(tests)}/{len(tests)}")
    if all(tests):
        print("✅ FINAL APPLICATION POOL V1.1 VALIDÉ SUR LE DIAGNOSTIC.")
    else:
        raise SystemExit("❌ FINAL APPLICATION POOL V1.1 NON VALIDÉ.")


if __name__ == "__main__":
    main()
