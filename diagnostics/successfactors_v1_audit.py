"""
JOB HUNTER BELGIUM
CONNECTEUR SUCCESSFACTORS - AUDIT V1.0 (HORS LIGNE)

    python -m diagnostics.successfactors_v1_audit

Aucun réseau : travaille sur deux pages réelles figées dans
tests/fixtures/successfactors_sample.json.

Ces deux pages ne sont pas redondantes : Umicore et Aquafin utilisent des
gabarits différents. Umicore expose le microdata schema.org, Aquafin non.
C'est précisément ce que l'audit doit protéger — un connecteur HTML se
casse par un changement de gabarit, pas par une erreur de logique.

Le test live est séparé : diagnostics/successfactors_v1_live_test.py.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sources.successfactors_ats_v1 import (
    MIN_DESCRIPTION_CHARS,
    SUCCESSFACTORS_CONNECTOR_VERSION,
    convert_successfactors_job,
    html_to_text,
    looks_belgian_url,
    parse_job_page,
    slug_from_url,
)
from diagnostics.version_support import at_least


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "successfactors_sample.json"
LOG_DIR = PROJECT_ROOT / "exports" / "logs"


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def main():
    print("=" * 92)
    print(f"CONNECTEUR SUCCESSFACTORS V{SUCCESSFACTORS_CONNECTOR_VERSION} "
          f"- AUDIT HORS LIGNE")
    print("=" * 92)
    print()

    tests = [check("Fixture présente", FIXTURE.exists(), FIXTURE.name)]
    if not FIXTURE.exists():
        raise SystemExit("[FAIL] Fixture manquante.")

    echantillons = json.loads(FIXTURE.read_text(encoding="utf-8"))["samples"]
    hotes = {e["host"] for e in echantillons}
    tests.append(check("Fixture couvre plusieurs employeurs", len(hotes) >= 2,
                       ", ".join(sorted(hotes))))

    print()
    print("A. LECTURE DES URL DE SITEMAP")
    print("-" * 92)
    tests.append(check(
        "Slug extrait de l'URL",
        slug_from_url("https://x/job/Hoboken-Buyer-IT/1404786033/")
        == "Hoboken Buyer IT",
    ))
    tests.append(check(
        "Slug désencodé",
        "Belgium Brussels" in slug_from_url(
            "https://x/job/Belgium-Brussels-Consolidation-%28FMX%29/12/"),
    ))
    tests.append(check(
        "Ville belge reconnue dans le slug",
        looks_belgian_url("https://x/job/Hoboken-Buyer-IT/1/"),
    ))
    tests.append(check(
        "Ville étrangère écartée",
        not looks_belgian_url("https://x/job/Quapaw-Process-Engineer-OK/1/"),
        "évite de télécharger les offres non belges",
    ))
    tests.append(check(
        "Ville allemande écartée",
        not looks_belgian_url("https://x/job/Hanau-Schuelerpraktikum-IT/1/"),
    ))

    print()
    print("B. DEUX GABARITS DIFFÉRENTS")
    print("-" * 92)
    # Le point sensible d'un connecteur HTML : chaque employeur peut
    # structurer sa page autrement.
    for ech in echantillons:
        donnees = parse_job_page(ech["html"])
        tests.append(check(
            f"Titre extrait ({ech['host']})",
            bool(donnees["title"]),
            donnees["title"][:44],
        ))
        tests.append(check(
            f"Description extraite ({ech['host']})",
            len(donnees["description"]) >= MIN_DESCRIPTION_CHARS,
            f"{len(donnees['description'])} caractères",
        ))

    print()
    print("C. QUALITÉ DU TEXTE")
    print("-" * 92)
    donnees = parse_job_page(echantillons[0]["html"])
    texte = donnees["description"]
    tests.append(check("Aucune balise résiduelle",
                       "<div" not in texte and "<p>" not in texte))
    tests.append(check("Aucune entité résiduelle",
                       "&nbsp;" not in texte and "&amp;" not in texte))
    tests.append(check("Aucun script résiduel",
                       "function(" not in texte and "var " not in texte))
    tests.append(check("HTML vide donne texte vide", html_to_text(None) == ""))

    print()
    print("D. CONVERSION")
    print("-" * 92)
    company = {"host": "careers.umicore.com", "label": "Umicore"}
    ech = [e for e in echantillons if "umicore" in e["host"]][0]
    offre = convert_successfactors_job(ech["url"], parse_job_page(ech["html"]),
                                       company)
    tests.append(check("Offre convertie", offre is not None))
    if offre is not None:
        tests.append(check("Provenance renseignée",
                           getattr(offre, "collection_channel", "") == "SUCCESSFACTORS"))
        tests.append(check("Identifiant externe préfixé par l'hôte",
                           offre.external_id.startswith("careers.umicore.com:")))
        tests.append(check("URL conservée",
                           str(offre.url).startswith("http")))
        tests.append(check("Le titre ouvre la description",
                           offre.description.startswith(offre.title[:15])))
        tests.append(check("Statut Belgique exposé",
                           bool(getattr(offre, "belgium_status", None)),
                           getattr(offre, "belgium_status", "")))

    print()
    print("E. GARDE-FOU CONTRE UN CHANGEMENT DE GABARIT")
    print("-" * 92)
    # Une page vide ne doit jamais produire une offre : c'est ainsi qu'on
    # détecte un changement de mise en page au lieu de polluer la base.
    tests.append(check(
        "Page vide rejetée",
        convert_successfactors_job("https://x/job/A-B/1/",
                                   {"title": "A", "description": ""},
                                   company) is None,
    ))
    tests.append(check(
        "Description trop courte rejetée",
        convert_successfactors_job("https://x/job/A-B/1/",
                                   {"title": "A", "description": "court"},
                                   company) is None,
        f"seuil : {MIN_DESCRIPTION_CHARS} caractères",
    ))
    tests.append(check(
        "Page sans aucune ancre connue donne une extraction vide",
        parse_job_page("<html><body><p>rien</p></body></html>")["description"]
        == "",
    ))
    tests.append(check("Version au moins 1.0",
                       at_least(SUCCESSFACTORS_CONNECTOR_VERSION, "1.0"),
                       SUCCESSFACTORS_CONNECTOR_VERSION))

    passed = sum(1 for x in tests if x)
    total = len(tests)

    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"successfactors_v1_audit_{stamp}.json").write_text(
        json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                    "connector_version": SUCCESSFACTORS_CONNECTOR_VERSION,
                    "passed": passed, "total": total},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    if passed != total:
        raise SystemExit("[FAIL] CONNECTEUR SUCCESSFACTORS NON VALIDÉ.")

    print("[PASS] CONNECTEUR SUCCESSFACTORS VALIDÉ HORS LIGNE.")


if __name__ == "__main__":
    main()
