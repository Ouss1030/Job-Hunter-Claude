"""
FINAL APPLICATION POOL V1.2 - AUDIT OFFLINE

Usage:
    python -m diagnostics.final_application_pool_v12_audit
"""

from diagnostics.version_support import at_least
from applications.final_application_pool_v12 import (
    FINAL_POOL_VERSION,
    classify_track,
    final_guard,
    preferred_location,
    _high_language_requirement,
)


def check(label, condition, detail=""):
    ok = bool(condition)
    print(
        f"{'✅' if ok else '❌'} {label}"
        + (f" | {detail}" if detail else "")
    )
    return ok


def guard_item(title, description, track="LAB_QC"):
    return final_guard({
        "title": title,
        "description": description,
        "track": track,
    })


def main():
    tests = []

    print("=" * 92)
    print("FINAL APPLICATION POOL V1.2 - AUDIT OFFLINE")
    print("=" * 92)
    print()

    tests.append(check(
        "Version au moins 1.2",
        at_least(FINAL_POOL_VERSION, "1.2"),
        FINAL_POOL_VERSION,
    ))

    tests.append(check(
        "Evere prioritaire",
        preferred_location("Evere, 1140, Belgique") is True,
    ))

    tests.append(check(
        "Beveren != Evere",
        preferred_location(
            "Beveren-Kruibeke-Zwijndrecht, Vlaanderen, Belgique"
        ) is False,
    ))

    tests.append(check(
        "Opérateur(trice) synthèse -> PRODUCTION",
        classify_track(
            "Opérateur(trice) de synthèse (H/F/X)",
            "LAB_QC",
        ) == "PRODUCTION_SCIENCE",
    ))

    tests.append(check(
        "NL C1 comme atout n'est pas obligatoire",
        _high_language_requirement(
            "Compétences linguistiques Néérlandais (atout) "
            "Comprendre : Expérimenté - C1.",
            "nl",
        ) is False,
    ))

    tests.append(check(
        "Tweetalig NL/FR détecté",
        _high_language_requirement(
            "Je bent tweetalig (NL/FR).",
            "nl",
        ) is True,
    ))

    tests.append(check(
        "Excellent Dutch détecté",
        _high_language_requirement(
            "Excellent written and oral communication skills in Dutch "
            "and English.",
            "nl",
        ) is True,
    ))

    tests.append(check(
        "Excellent English détecté",
        _high_language_requirement(
            "Excellent written and oral communication skills in Dutch "
            "and English.",
            "en",
        ) is True,
    ))

    g = guard_item(
        "Opérateur(trice) de synthèse (H/F/X)",
        "Vous disposez déjà d'une expérience probante en tant "
        "qu'opérateur de synthèse en chimie (indispensable). "
        "Vous justifiez d'une expérience de 3 à 5 ans dans un "
        "environnement de production.",
        "PRODUCTION_SCIENCE",
    )
    tests.append(check(
        "Synthèse expérience indispensable -> BLOCK",
        g["guard_level"] == "BLOCK",
        str(g),
    ))

    g = guard_item(
        "Laboratory Technician - Cell Culture",
        "Performing cell passages is a core responsibility.",
        "LAB_QC",
    )
    tests.append(check(
        "Cell culture core -> REVIEW",
        g["guard_level"] == "REVIEW",
        str(g),
    ))

    g = guard_item(
        "Laborantin GQP",
        "Connaissance pratique de la méthode HACCP en milieu industriel.",
        "LAB_QC",
    )
    tests.append(check(
        "HACCP pratique -> REVIEW",
        g["guard_level"] == "REVIEW",
        str(g),
    ))

    g = guard_item(
        "Opérateur de production secteur chimie",
        "Vous possédez le brevet cariste frontal. Brevet obligatoire.",
        "PRODUCTION_SCIENCE",
    )
    tests.append(check(
        "Cariste obligatoire -> VERIFY",
        g["guard_level"] == "VERIFY",
        str(g),
    ))

    g = guard_item(
        "Business / Financial Data Analyst",
        "Rôle au sein des équipes finance et comptabilité. "
        "Valorisation des inventaires, concepts comptables, "
        "SAP Business Object.",
        "DATA",
    )
    tests.append(check(
        "Data finance -> REVIEW",
        g["guard_level"] == "REVIEW",
        str(g),
    ))

    print()
    print(f"Tests : {sum(tests)}/{len(tests)}")

    if not all(tests):
        raise SystemExit("❌ FINAL POOL V1.2 NON VALIDÉ OFFLINE.")

    print("✅ FINAL APPLICATION POOL V1.2 VALIDÉ OFFLINE.")


if __name__ == "__main__":
    main()
