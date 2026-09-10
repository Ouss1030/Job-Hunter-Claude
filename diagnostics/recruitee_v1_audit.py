"""
JOB HUNTER BELGIUM
CONNECTEUR RECRUITEE - AUDIT V1.0 (HORS LIGNE)

    python -m diagnostics.recruitee_v1_audit

Aucun réseau : l'audit travaille sur une réponse réelle figée dans
tests/fixtures/recruitee_vito_sample.json, à laquelle a été ajoutée une
offre allemande fabriquée pour vérifier le filtre géographique.

Le test live est séparé : diagnostics/recruitee_v1_live_test.py.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sources.recruitee import (
    RECRUITEE_CONNECTOR_VERSION,
    build_matching_text,
    convert_recruitee_offer,
    _belgium_status,
    _html_to_text,
)
from diagnostics.version_support import at_least


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "recruitee_vito_sample.json"
LOG_DIR = PROJECT_ROOT / "exports" / "logs"

COMPANY = {"identifier": "vito", "label": "VITO", "tracks": ["LAB_QC"]}


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def main():
    print("=" * 92)
    print(f"CONNECTEUR RECRUITEE V{RECRUITEE_CONNECTOR_VERSION} - AUDIT HORS LIGNE")
    print("=" * 92)
    print()

    tests = []

    tests.append(check("Fixture présente", FIXTURE.exists(), str(FIXTURE.name)))
    if not FIXTURE.exists():
        raise SystemExit("[FAIL] Fixture manquante.")

    offers = json.loads(FIXTURE.read_text(encoding="utf-8"))["offers"]
    tests.append(check("Fixture non vide", len(offers) >= 5, f"{len(offers)} offres"))

    belges = [o for o in offers if (o.get("country_code") or "").upper() == "BE"]
    etrangeres = [o for o in offers if (o.get("country_code") or "").upper() != "BE"]

    print()
    print("A. CONVERSION")
    print("-" * 92)
    convertis = []
    echecs = 0
    for offer in offers:
        try:
            job = convert_recruitee_offer(offer, COMPANY)
        except Exception as exc:
            echecs += 1
            print(f"    exception sur {offer.get('id')} : {exc}")
            continue
        if job is None:
            echecs += 1
            continue
        convertis.append(job)

    tests.append(check("Toutes les offres se convertissent", echecs == 0,
                       f"{len(convertis)}/{len(offers)}"))
    tests.append(check("Identifiant externe préfixé par l'employeur",
                       all(j.external_id.startswith("vito:") for j in convertis)))
    tests.append(check("Provenance renseignée",
                       all(getattr(j, "collection_channel", "") == "RECRUITEE"
                           and getattr(j, "origin_source", "") == "vito"
                           for j in convertis)))
    tests.append(check("URL publique présente",
                       all(str(j.url).startswith("http") for j in convertis)))

    print()
    print("B. FILTRE GÉOGRAPHIQUE")
    print("-" * 92)
    tests.append(check(
        "country_code BE donne BE_CONFIRMED",
        all(_belgium_status(o) == "BE_CONFIRMED" for o in belges),
        f"{len(belges)} offres belges",
    ))
    tests.append(check(
        "Une offre allemande n'est pas belge",
        all(_belgium_status(o) != "BE_CONFIRMED" for o in etrangeres),
        f"{len(etrangeres)} offre(s) étrangère(s)",
    ))
    retenues = [j for j in convertis
                if getattr(j, "belgium_status", "") in ("BE_CONFIRMED", "BE_LIKELY")]
    tests.append(check(
        "L'offre étrangère est écartée du lot retenu",
        len(retenues) == len(belges),
        f"retenues={len(retenues)} attendues={len(belges)}",
    ))

    print()
    print("C. TEXTE DE MATCHING")
    print("-" * 92)
    # Leçon SmartRecruiters V1.1 : le corporate ne doit pas piloter le score.
    exemple = belges[0]
    ad = build_matching_text(exemple)
    tests.append(check("matching_text non vide", bool(ad["matching_text"])))
    tests.append(check(
        "sharing_description conservé hors matching",
        bool(ad["company_description"])
        and ad["company_description"] not in ad["matching_text"].split("\n\n")[:1],
        f"{len(ad['company_description'])} caractères mis de côté",
    ))
    tests.append(check(
        "requirements placé avant description",
        ad["requirements"] and ad["matching_text"].index(ad["requirements"][:40])
        < ad["matching_text"].index(ad["description"][:40]),
        "le champ spécifique au poste passe en premier",
    ))
    tests.append(check(
        "Le HTML est nettoyé",
        "<p>" not in ad["matching_text"] and "<li>" not in ad["matching_text"],
    ))
    tests.append(check(
        "Les entités HTML sont décodées",
        "&amp;" not in ad["matching_text"] and "&nbsp;" not in ad["matching_text"],
    ))

    print()
    print("D. DONNÉES STRUCTURÉES")
    print("-" * 92)
    avec_diplome = [j for j in convertis if getattr(j, "degree_requirement", None)]
    tests.append(check(
        "education_code exposé comme degree_requirement",
        len(avec_diplome) >= 1,
        f"{len(avec_diplome)}/{len(convertis)} offres",
    ))
    tests.append(check(
        "Corporate accessible séparément",
        all(hasattr(j, "company_description") for j in convertis),
    ))
    tests.append(check(
        "Département exposé",
        any(getattr(j, "department", "") for j in convertis),
    ))

    print()
    print("E. ROBUSTESSE")
    print("-" * 92)
    tests.append(check("Une offre sans titre ni texte est ignorée",
                       convert_recruitee_offer({"id": 1}, COMPANY) is None))
    tests.append(check("Une offre sans id est ignorée",
                       convert_recruitee_offer({"title": "x"}, COMPANY) is None))
    tests.append(check("HTML vide donne texte vide", _html_to_text(None) == ""))
    tests.append(check("Version du connecteur au moins 1.0",
                       at_least(RECRUITEE_CONNECTOR_VERSION, "1.0"),
                       RECRUITEE_CONNECTOR_VERSION))

    passed = sum(1 for x in tests if x)
    total = len(tests)

    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"recruitee_v1_audit_{stamp}.json").write_text(
        json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                    "connector_version": RECRUITEE_CONNECTOR_VERSION,
                    "passed": passed, "total": total},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")

    if passed != total:
        raise SystemExit("[FAIL] CONNECTEUR RECRUITEE NON VALIDÉ.")

    print("[PASS] CONNECTEUR RECRUITEE VALIDÉ HORS LIGNE.")


if __name__ == "__main__":
    main()
