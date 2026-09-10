"""
JOB HUNTER BELGIUM
CONNECTEUR GREENHOUSE - AUDIT V1.0 (HORS LIGNE)

    python -m diagnostics.greenhouse_v1_audit

Aucun réseau : travaille sur une réponse réelle figée dans
tests/fixtures/greenhouse_collibra_sample.json.

Le test live est séparé : diagnostics/greenhouse_v1_live_test.py.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sources.greenhouse import (
    GREENHOUSE_CONNECTOR_VERSION,
    build_matching_text,
    convert_greenhouse_job,
    html_to_text,
    _location_text,
)
from sources.location_belgium import detect_belgium_multi
from diagnostics.version_support import at_least


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "greenhouse_collibra_sample.json"
LOG_DIR = PROJECT_ROOT / "exports" / "logs"

COMPANY = {"identifier": "collibra", "label": "Collibra", "tracks": ["DATA"]}


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def main():
    print("=" * 92)
    print(f"CONNECTEUR GREENHOUSE V{GREENHOUSE_CONNECTOR_VERSION} - AUDIT HORS LIGNE")
    print("=" * 92)
    print()

    tests = [check("Fixture présente", FIXTURE.exists(), FIXTURE.name)]
    if not FIXTURE.exists():
        raise SystemExit("[FAIL] Fixture manquante.")

    jobs = json.loads(FIXTURE.read_text(encoding="utf-8"))["jobs"]
    tests.append(check("Fixture non vide", len(jobs) >= 5, f"{len(jobs)} offres"))

    print()
    print("A. DOUBLE ÉCHAPPEMENT HTML")
    print("-" * 92)
    # L'API renvoie "&lt;p&gt;" : une seule passe de unescape laisserait
    # des balises visibles dans le texte envoyé au Matcher.
    brut = jobs[0].get("content") or ""
    texte = html_to_text(brut)
    tests.append(check("Le contenu source est bien doublement échappé",
                       "&lt;" in brut, "sinon ce test ne prouve rien"))
    tests.append(check("Aucune balise résiduelle après nettoyage",
                       "<p>" not in texte and "<li>" not in texte))
    tests.append(check("Aucune entité résiduelle après nettoyage",
                       "&lt;" not in texte and "&amp;" not in texte))
    tests.append(check("Le texte nettoyé n'est pas vide", len(texte) > 50,
                       f"{len(texte)} caractères"))

    print()
    print("B. LOCALISATION")
    print("-" * 92)
    belges = [j for j in jobs
              if "belgium" in str((j.get("location") or {}).get("name", "")).lower()]
    etrangeres = [j for j in jobs if j not in belges]

    tests.append(check(
        "Les offres belges sont reconnues",
        all(detect_belgium_multi(_location_text(j)) == "BE_CONFIRMED"
            for j in belges),
        f"{len(belges)} offres",
    ))
    tests.append(check(
        "Aucune offre étrangère marquée BE_CONFIRMED",
        all(detect_belgium_multi(_location_text(j)) != "BE_CONFIRMED"
            for j in etrangeres),
        f"{len(etrangeres)} offres",
    ))
    # Multi-site : une offre ouverte à plusieurs endroits dont un belge
    # concerne la Belgique.
    tests.append(check(
        "Multi-site avec un site belge -> BE_CONFIRMED",
        detect_belgium_multi("New York, USA; Brussels, Belgium") == "BE_CONFIRMED",
    ))
    tests.append(check(
        "Multi-site sans site belge -> pas BE_CONFIRMED",
        detect_belgium_multi("New York, USA; Raleigh, USA") != "BE_CONFIRMED",
    ))

    print()
    print("C. CONVERSION")
    print("-" * 92)
    convertis, echecs = [], 0
    for j in jobs:
        try:
            offer = convert_greenhouse_job(j, COMPANY)
        except Exception as exc:
            echecs += 1
            print(f"    exception sur {j.get('id')} : {exc}")
            continue
        if offer is None:
            echecs += 1
            continue
        convertis.append(offer)

    tests.append(check("Toutes les offres se convertissent", echecs == 0,
                       f"{len(convertis)}/{len(jobs)}"))
    tests.append(check("Identifiant externe préfixé par le board",
                       all(o.external_id.startswith("collibra:") for o in convertis)))
    tests.append(check("Provenance renseignée",
                       all(getattr(o, "collection_channel", "") == "GREENHOUSE"
                           for o in convertis)))
    tests.append(check("URL publique présente",
                       all(str(o.url).startswith("http") for o in convertis)))
    tests.append(check("Statut Belgique exposé sur chaque offre",
                       all(getattr(o, "belgium_status", None) for o in convertis)))

    print()
    print("D. TEXTE DE MATCHING")
    print("-" * 92)
    ad = build_matching_text(jobs[0])
    tests.append(check("matching_text non vide", bool(ad["matching_text"])))
    tests.append(check("Le titre ouvre le texte de matching",
                       ad["matching_text"].startswith(
                           str(jobs[0].get("title") or "")[:20])))
    tests.append(check("Langue de publication exposée",
                       any(getattr(o, "posting_language", None) for o in convertis),
                       "sert à repérer les annonces néerlandophones"))

    print()
    print("E. ROBUSTESSE")
    print("-" * 92)
    tests.append(check("Offre sans id ignorée",
                       convert_greenhouse_job({"title": "x"}, COMPANY) is None))
    tests.append(check("Offre sans contenu ignorée",
                       convert_greenhouse_job({"id": 1}, COMPANY) is None))
    tests.append(check("HTML vide donne texte vide", html_to_text(None) == ""))
    tests.append(check("Version au moins 1.0",
                       at_least(GREENHOUSE_CONNECTOR_VERSION, "1.0"),
                       GREENHOUSE_CONNECTOR_VERSION))

    passed = sum(1 for x in tests if x)
    total = len(tests)

    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"greenhouse_v1_audit_{stamp}.json").write_text(
        json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                    "connector_version": GREENHOUSE_CONNECTOR_VERSION,
                    "passed": passed, "total": total},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    if passed != total:
        raise SystemExit("[FAIL] CONNECTEUR GREENHOUSE NON VALIDÉ.")

    print("[PASS] CONNECTEUR GREENHOUSE VALIDÉ HORS LIGNE.")


if __name__ == "__main__":
    main()
