"""
JOB HUNTER BELGIUM
CONNECTEUR WORKDAY - AUDIT V1.0 (HORS LIGNE)

    python -m diagnostics.workday_v1_audit

Aucun réseau : travaille sur des réponses réelles figées dans
tests/fixtures/workday_gsk_sample.json (liste + détail).

Le test live est séparé : diagnostics/workday_v1_live_test.py.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sources.workday_ats_v1 import (
    WORKDAY_CONNECTOR_VERSION,
    build_matching_text,
    convert_workday_job,
    html_to_text,
    looks_belgian,
    _base_url,
    _multi_site,
)
from diagnostics.version_support import at_least


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "workday_gsk_sample.json"
LOG_DIR = PROJECT_ROOT / "exports" / "logs"

COMPANY = {"tenant": "gsk", "wd": "wd5", "site": "GSKCareers", "label": "GSK"}


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def main():
    print("=" * 92)
    print(f"CONNECTEUR WORKDAY V{WORKDAY_CONNECTOR_VERSION} - AUDIT HORS LIGNE")
    print("=" * 92)
    print()

    tests = [check("Fixture présente", FIXTURE.exists(), FIXTURE.name)]
    if not FIXTURE.exists():
        raise SystemExit("[FAIL] Fixture manquante.")

    echantillons = json.loads(FIXTURE.read_text(encoding="utf-8"))["samples"]
    tests.append(check("Fixture non vide", len(echantillons) >= 3,
                       f"{len(echantillons)} offres"))

    print()
    print("A. CONSTRUCTION DES URL")
    print("-" * 92)
    base = _base_url(COMPANY)
    tests.append(check(
        "URL construite depuis tenant / wd / site",
        base == "https://gsk.wd5.myworkdayjobs.com/wday/cxs/gsk/GSKCareers",
        base,
    ))

    print()
    print("B. PRÉ-FILTRE SUR LA LISTE")
    print("-" * 92)
    # Le pré-filtre évite de demander le détail de chaque offre : sur GSK,
    # 62 candidates au lieu de 782.
    tests.append(check("Belgium-Wavre reconnu belge",
                       looks_belgian({"locationsText": "Belgium-Wavre"})))
    tests.append(check("Belgium-Rixensart reconnu belge",
                       looks_belgian({"locationsText": "Belgium-Rixensart"})))
    tests.append(check("USA-Philadelphia écarté",
                       not looks_belgian({"locationsText": "USA-Philadelphia"})))
    tests.append(check("Multi-site conservé pour vérification au détail",
                       looks_belgian({"locationsText": "6 Locations"}),
                       "écarter une offre belge serait pire que d'en vérifier une de trop"))
    tests.append(check("Détection du format multi-site",
                       _multi_site("6 Locations") and not _multi_site("Belgium-Wavre")))

    print()
    print("C. CONVERSION")
    print("-" * 92)
    convertis, echecs = [], 0
    for ech in echantillons:
        try:
            offre = convert_workday_job(ech["detail"], ech["posting"], COMPANY)
        except Exception as exc:
            echecs += 1
            print(f"    exception : {exc}")
            continue
        if offre is None:
            echecs += 1
            continue
        convertis.append(offre)

    tests.append(check("Toutes les offres se convertissent", echecs == 0,
                       f"{len(convertis)}/{len(echantillons)}"))
    tests.append(check("Identifiant externe préfixé par le tenant",
                       all(o.external_id.startswith("gsk:") for o in convertis)))
    tests.append(check("Provenance renseignée",
                       all(getattr(o, "collection_channel", "") == "WORKDAY"
                           for o in convertis)))
    tests.append(check("URL publique présente",
                       all(str(o.url).startswith("http") for o in convertis)))

    print()
    print("D. PAYS STRUCTURÉ")
    print("-" * 92)
    # country.descriptor est une donnée, pas du texte : plus fiable que
    # l'analyse de "Belgium-Wavre".
    #
    # La fixture contient volontairement des offres non belges : une
    # recherche "Wavre" remonte aussi des postes multi-sites rattachés au
    # Royaume-Uni ou aux États-Unis. C'est précisément ce que le filtre
    # doit écarter.
    belges = [o for o in convertis
              if getattr(o, "country_descriptor", None) == "Belgium"]
    autres = [o for o in convertis if o not in belges]

    tests.append(check(
        "country.descriptor exploité",
        all(getattr(o, "country_descriptor", None) for o in convertis),
        str(sorted({getattr(o, "country_descriptor", None) for o in convertis})),
    ))
    tests.append(check(
        "La fixture contient bien les deux cas",
        bool(belges) and bool(autres),
        f"{len(belges)} belge(s), {len(autres)} étrangère(s)",
    ))
    tests.append(check(
        "Offres belges marquées BE_CONFIRMED",
        all(getattr(o, "belgium_status", "") == "BE_CONFIRMED" for o in belges),
    ))
    tests.append(check(
        "Offres étrangères non marquées BE_CONFIRMED",
        all(getattr(o, "belgium_status", "") != "BE_CONFIRMED" for o in autres),
        str([getattr(o, "belgium_status", "") for o in autres]),
    ))

    print()
    print("E. TEXTE DE MATCHING")
    print("-" * 92)
    ech = echantillons[0]
    texte = build_matching_text(ech["detail"], ech["posting"])
    tests.append(check("matching_text non vide", len(texte) > 50,
                       f"{len(texte)} caractères"))
    tests.append(check("Aucune balise HTML résiduelle",
                       "<p>" not in texte and "<span>" not in texte))
    tests.append(check("Aucune entité HTML résiduelle",
                       "&nbsp;" not in texte and "&amp;" not in texte))
    tests.append(check("Le titre ouvre le texte",
                       texte.startswith(str(ech["detail"].get("title"))[:15])))

    print()
    print("F. ROBUSTESSE")
    print("-" * 92)
    tests.append(check("Détail vide ignoré",
                       convert_workday_job({}, {}, COMPANY) is None))
    tests.append(check("Détail sans description ignoré",
                       convert_workday_job({"title": ""}, {}, COMPANY) is None))
    tests.append(check("HTML vide donne texte vide", html_to_text(None) == ""))
    tests.append(check("Version au moins 1.0",
                       at_least(WORKDAY_CONNECTOR_VERSION, "1.0"),
                       WORKDAY_CONNECTOR_VERSION))

    passed = sum(1 for x in tests if x)
    total = len(tests)

    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"workday_v1_audit_{stamp}.json").write_text(
        json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                    "connector_version": WORKDAY_CONNECTOR_VERSION,
                    "passed": passed, "total": total},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    if passed != total:
        raise SystemExit("[FAIL] CONNECTEUR WORKDAY NON VALIDÉ.")

    print("[PASS] CONNECTEUR WORKDAY VALIDÉ HORS LIGNE.")


if __name__ == "__main__":
    main()
