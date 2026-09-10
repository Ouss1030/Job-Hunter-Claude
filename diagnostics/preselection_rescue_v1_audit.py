"""
JOB HUNTER BELGIUM
SAUVETAGE DE PRÉ-SÉLECTION - AUDIT V1.0

    python -m diagnostics.preselection_rescue_v1_audit

Aucun réseau. Aucune base.

Ce module élargit ce qui entre dans l'enrichissement. Le risque n'est donc
pas de rater une offre, mais d'en faire entrer trop : chaque faux positif
coûte une requête et du bruit. L'audit teste surtout cela.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from matching.preselection_rescue import (
    CORE_TITLE_TERMS,
    RESCUE_VERSION,
    THIN_DESCRIPTION_CHARS,
    description_is_thin,
    has_core_title,
    partition_rescued,
    should_rescue,
)
from diagnostics.version_support import at_least


LOG_DIR = Path(__file__).resolve().parent.parent / "exports" / "logs"


# Intitulés réels de la base, à sauver.
A_SAUVER = [
    "Technicien(ne) de laboratoire H/F/X",
    "Assistant laboratoire en alimentaire (H/F/X)",
    "Kwaliteitscontroleur | Veurne (H/F/X)",
    "kwaliteitsoperator | vaste nacht | vleteren (H/F/X)",
    "staalnemer water M/V/X",
    "Technicien QC (H/F/X)",
    "Technicien QA (H/F/X)",
    "Support Laboratoire Polyvalent M/V/X",
    "Laborantin.e chimiste (H/F/X)",
    "Data Analyst",
    "procestechnieker waterzuivering",
]

# Intitulés qui ne doivent PAS déclencher le sauvetage : chaque faux
# positif coûte une requête d'enrichissement inutile.
A_IGNORER = [
    "Comptable",
    "Chauffeur poids lourd",
    "Vendeur en magasin",
    "Élaboration de projets immobiliers",   # "labo" dans "élaboration"
    "Consultant Qatar",                     # "qa" dans "qatar"
    "Employé administratif",
    "Aide-ménagère",
    "Conseiller clientèle",
    "Chef de rang",
    "Éducateur spécialisé",
]


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def _job(titre, description=""):
    return SimpleNamespace(title=titre, description=description,
                           detail_matching_text=description)


def main():
    print("=" * 92)
    print(f"SAUVETAGE DE PRÉ-SÉLECTION V{RESCUE_VERSION} - AUDIT")
    print("=" * 92)
    print()

    tests = []

    print("A. VOCABULAIRE")
    print("-" * 92)
    tests.append(check("Termes chargés depuis config/profile.py",
                       len(CORE_TITLE_TERMS) > 100,
                       f"{len(CORE_TITLE_TERMS)} termes"))
    tests.append(check("Termes belges présents",
                       all(t in CORE_TITLE_TERMS
                           for t in ("technieker", "kwaliteitscontroleur",
                                     "staalnemer", "procestechnieker")),
                       "formes belges absentes des concepts d'origine"))

    print()
    print("B. INTITULÉS À SAUVER")
    print("-" * 92)
    for titre in A_SAUVER:
        tests.append(check(f"{titre[:56]:<58}", has_core_title(titre)))

    print()
    print("C. FAUX POSITIFS À ÉVITER")
    print("-" * 92)
    # Le point sensible : sans frontières lexicales, "labo" matcherait
    # "élaboration" et "qa" matcherait "qatar".
    for titre in A_IGNORER:
        tests.append(check(f"{titre[:56]:<58} ignoré", not has_core_title(titre)))

    print()
    print("D. CONDITION DE DESCRIPTION MAIGRE")
    print("-" * 92)
    tests.append(check("Description courte détectée",
                       description_is_thin(_job("x", "a" * 150))))
    tests.append(check("Description complète non concernée",
                       not description_is_thin(_job("x", "a" * 900)),
                       f"seuil : {THIN_DESCRIPTION_CHARS} caractères"))

    print()
    print("E. RÈGLE DE SAUVETAGE")
    print("-" * 92)
    court, long = "a" * 150, "a" * 900
    tests.append(check(
        "Offre déjà retenue par le pré-score : pas de sauvetage",
        not should_rescue(_job("Technicien de laboratoire", court),
                          {"core_relevance": True}),
        "évite un doublon",
    ))
    tests.append(check(
        "Offre bien décrite : pas de sauvetage",
        not should_rescue(_job("Technicien de laboratoire", long),
                          {"core_relevance": False}),
        "le pré-score a jugé sur un vrai texte, on respecte sa décision",
    ))
    tests.append(check(
        "Intitulé hors profil : pas de sauvetage",
        not should_rescue(_job("Comptable", court), {"core_relevance": False}),
    ))
    tests.append(check(
        "Intitulé métier + description maigre : sauvetage",
        should_rescue(_job("Technicien de laboratoire", court),
                      {"core_relevance": False}),
    ))

    print()
    print("F. PARTITION")
    print("-" * 92)
    lot = [
        (_job("QC Analyst", long), {"core_relevance": True}),
        (_job("Technicien de laboratoire", court), {"core_relevance": False}),
        (_job("Comptable", court), {"core_relevance": False}),
        (_job("Laborantin", court), {"core_relevance": False}),
    ]
    retenues, sauvees = partition_rescued(lot)
    tests.append(check("Retenues correctes", len(retenues) == 1, str(len(retenues))))
    tests.append(check("Sauvées correctes", len(sauvees) == 2, str(len(sauvees))))
    tests.append(check("Aucun doublon entre les deux listes",
                       not ({id(j) for j, _ in retenues}
                            & {id(j) for j, _ in sauvees})))
    tests.append(check("Version au moins 1.0",
                       at_least(RESCUE_VERSION, "1.0"), RESCUE_VERSION))

    passed = sum(1 for x in tests if x)
    total = len(tests)

    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"preselection_rescue_v1_audit_{stamp}.json").write_text(
        json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                    "rescue_version": RESCUE_VERSION,
                    "terms": len(CORE_TITLE_TERMS),
                    "passed": passed, "total": total},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    if passed != total:
        raise SystemExit("[FAIL] SAUVETAGE DE PRÉ-SÉLECTION NON VALIDÉ.")

    print("[PASS] SAUVETAGE DE PRÉ-SÉLECTION VALIDÉ.")


if __name__ == "__main__":
    main()
