"""
JOB HUNTER BELGIUM
CONNECTEUR PHENOM - AUDIT V1.0 (HORS LIGNE)

    python -m diagnostics.phenom_v1_audit

Aucun réseau : travaille sur les blocs JSON-LD réels figés dans
tests/fixtures/phenom_ucb_sample.json — deux offres belges et une
japonaise, pour tester le filtrage dans les deux sens.

Le test live est séparé : diagnostics/phenom_v1_live_test.py.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sources.phenom_ats_v1 import (
    MIN_DESCRIPTION_CHARS,
    PHENOM_CONNECTOR_VERSION,
    convert_phenom_job,
    extract_job_posting,
    html_to_text,
    _location_text,
)
from diagnostics.version_support import at_least


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "phenom_ucb_sample.json"
LOG_DIR = PROJECT_ROOT / "exports" / "logs"

COMPANY = {"host": "careers.ucb.com", "label": "UCB"}


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def _page(sample):
    """Reconstitue une page à partir des blocs JSON-LD conservés."""
    return "".join(
        f'<script type="application/ld+json">{b}</script>'
        for b in sample["blocks"]
    )


def main():
    print("=" * 92)
    print(f"CONNECTEUR PHENOM V{PHENOM_CONNECTOR_VERSION} - AUDIT HORS LIGNE")
    print("=" * 92)
    print()

    tests = [check("Fixture présente", FIXTURE.exists(), FIXTURE.name)]
    if not FIXTURE.exists():
        raise SystemExit("[FAIL] Fixture manquante.")

    echantillons = json.loads(FIXTURE.read_text(encoding="utf-8"))["samples"]
    tests.append(check("Fixture non vide", len(echantillons) >= 3,
                       f"{len(echantillons)} offres"))

    print()
    print("A. EXTRACTION DU JSON-LD")
    print("-" * 92)
    # Une page porte plusieurs blocs (fil d'Ariane, organisation) : seul
    # celui de type JobPosting décrit le poste.
    multi = [s for s in echantillons if len(s["blocks"]) > 1]
    tests.append(check("Des pages portent plusieurs blocs",
                       bool(multi),
                       f"{len(multi)} page(s) — le bon doit être choisi"))

    postings = []
    for s in echantillons:
        p = extract_job_posting(_page(s))
        postings.append((s, p))
        tests.append(check(f"JobPosting trouvé ({s['url'][-28:]})", p is not None))

    tests.append(check(
        "Seul le type JobPosting est retenu",
        all(p.get("@type") == "JobPosting" for _, p in postings if p),
    ))
    tests.append(check(
        "Page sans JSON-LD : rien extrait",
        extract_job_posting("<html><body>rien</body></html>") is None,
    ))
    tests.append(check(
        "JSON-LD invalide : rien extrait, pas d'exception",
        extract_job_posting(
            '<script type="application/ld+json">{cassé</script>') is None,
    ))

    print()
    print("B. CHAMPS STRUCTURÉS")
    print("-" * 92)
    for s, p in postings:
        if not p:
            continue
        tests.append(check(f"Titre présent ({str(p.get('title'))[:32]})",
                           bool(p.get("title"))))
    exemple = next(p for _, p in postings if p)
    tests.append(check("Date de publication exposée",
                       bool(exemple.get("datePosted")),
                       str(exemple.get("datePosted"))))
    tests.append(check("Description substantielle",
                       len(html_to_text(exemple.get("description")))
                       >= MIN_DESCRIPTION_CHARS,
                       f"{len(html_to_text(exemple.get('description')))} car."))

    print()
    print("C. LOCALISATION")
    print("-" * 92)
    # Le pays vient de jobLocation.address : c'est une donnée, pas du texte
    # libre. C'est ce qui rend ce connecteur plus fiable que SuccessFactors.
    belges, etrangeres = [], []
    for s, p in postings:
        if not p:
            continue
        offre = convert_phenom_job(s["url"], p, COMPANY)
        if offre is None:
            continue
        (belges if getattr(offre, "belgium_status", "") in
         ("BE_CONFIRMED", "BE_LIKELY") else etrangeres).append(offre)

    tests.append(check("Offres belges reconnues", len(belges) >= 2,
                       ", ".join(o.location[:22] for o in belges)))
    tests.append(check("Offre étrangère écartée", len(etrangeres) >= 1,
                       ", ".join(o.location[:22] for o in etrangeres)))
    tests.append(check(
        "Localisation reconstruite lisible",
        all("," in o.location for o in belges),
        belges[0].location if belges else "",
    ))
    tests.append(check(
        "jobLocation absent : pas d'exception",
        _location_text({"title": "x"}) == "",
    ))

    print()
    print("D. CONVERSION")
    print("-" * 92)
    offre = belges[0]
    tests.append(check("Provenance renseignée",
                       getattr(offre, "collection_channel", "") == "PHENOM"))
    tests.append(check("Identifiant préfixé par l'hôte",
                       offre.external_id.startswith("careers.ucb.com:")))
    tests.append(check("URL conservée", str(offre.url).startswith("http")))
    tests.append(check("Le titre ouvre la description",
                       offre.description.startswith(offre.title[:15])))
    tests.append(check("Aucune balise HTML résiduelle",
                       "<p>" not in offre.description
                       and "<li>" not in offre.description))
    tests.append(check("Aucune entité HTML résiduelle",
                       "&nbsp;" not in offre.description
                       and "&amp;" not in offre.description))

    print()
    print("E. ROBUSTESSE")
    print("-" * 92)
    tests.append(check("Offre sans titre ignorée",
                       convert_phenom_job("u", {"description": "x" * 500},
                                          COMPANY) is None))
    tests.append(check("Description trop courte ignorée",
                       convert_phenom_job("u", {"title": "T",
                                                "description": "court"},
                                          COMPANY) is None,
                       f"seuil : {MIN_DESCRIPTION_CHARS}"))
    tests.append(check("HTML vide donne texte vide", html_to_text(None) == ""))
    tests.append(check("Version au moins 1.0",
                       at_least(PHENOM_CONNECTOR_VERSION, "1.0"),
                       PHENOM_CONNECTOR_VERSION))

    passed = sum(1 for x in tests if x)
    total = len(tests)

    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"phenom_v1_audit_{stamp}.json").write_text(
        json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                    "connector_version": PHENOM_CONNECTOR_VERSION,
                    "passed": passed, "total": total},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    if passed != total:
        raise SystemExit("[FAIL] CONNECTEUR PHENOM NON VALIDÉ.")

    print("[PASS] CONNECTEUR PHENOM VALIDÉ HORS LIGNE.")


if __name__ == "__main__":
    main()
