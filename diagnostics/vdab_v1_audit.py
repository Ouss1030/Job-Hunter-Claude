"""
JOB HUNTER BELGIUM
CONNECTEUR VDAB - AUDIT V1.0 (HORS LIGNE)

    python -m diagnostics.vdab_v1_audit

Aucun réseau. Le connecteur VDAB lit du HTML et non du JSON-LD : il dépend
donc de la mise en page. C'est exactement le type de code qu'il faut figer
par des cas attendus, parce qu'un redesign le casse sans rien changer à la
syntaxe — et `py_compile` ne verra rien.

Les fragments ci-dessous reproduisent la structure réelle observée le
6 septembre 2026 : <h1> pour l'intitulé, sections <h3> néerlandaises pour
l'annonce, "Plaats tewerkstelling" pour le lieu.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from diagnostics.version_support import at_least
from sources.vdab import (
    COMPTEURS,
    MIN_DESCRIPTION_CHARS,
    VDAB_CONNECTOR_VERSION,
    _week_key,
    convert_vdab_job,
    html_to_text,
    job_id_from_url,
    nouveaux_compteurs,
    parse_job_page,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "exports" / "logs"

URL = "https://www.vdab.be/vindeenjob/vacatures/60152620/laborant-kwaliteitscontrole"

PAGE = """
<html><head><title>VDAB</title>
<script>var x = "Functieomschrijving piege dans du script";</script>
</head><body>
<nav>Vind een job | Vind een opleiding</nav>
<h1>Laborant kwaliteitscontrole</h1>
<section>
  <h3>Functieomschrijving</h3>
  <p>Als laborant voer je fysico-chemische analyses uit op grondstoffen en
  afgewerkte producten. Je werkt volgens GMP en rapporteert afwijkingen in
  het LIMS. Je staat mee in voor de kalibratie van de toestellen.</p>
  <h3>Profiel</h3>
  <ul><li>Bachelor chemie of gelijkwaardig door ervaring</li>
  <li>Kennis van HPLC is een pluspunt</li></ul>
  <h3>Aanbod</h3>
  <p>Een voltijds contract van onbepaalde duur, maaltijdcheques en
  hospitalisatieverzekering. Opleiding wordt voorzien.</p>
  <h3>Plaats tewerkstelling</h3>
  <p>Regio Gent</p>
</section>
<footer>VDAB &copy; 2026</footer>
</body></html>
"""

PAGE_SANS_TITRE = "<html><body><section><h3>Profiel</h3><p>x</p></section></body></html>"
PAGE_MAIGRE = """
<html><body><h1>Jobstudent</h1>
<section><h3>Functieomschrijving</h3><p>Korte tekst.</p></section></body></html>
"""


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def main():
    print("=" * 92)
    print(f"CONNECTEUR VDAB V{VDAB_CONNECTOR_VERSION} - AUDIT HORS LIGNE")
    print("=" * 92)
    print()

    tests = []

    print("A. TRI DES SITEMAPS HEBDOMADAIRES")
    print("-" * 92)
    # L'index liste 228 sitemaps : lire les plus récents suppose un tri sûr.
    urls = [
        "https://www.vdab.be/sitemap/vindeenjob/vacatures/index-2024-25-1.xml",
        "https://www.vdab.be/sitemap/vindeenjob/vacatures/index-2026-9-1.xml",
        "https://www.vdab.be/sitemap/vindeenjob/vacatures/index-2026-35-1.xml",
        "https://www.vdab.be/sitemap/vindeenjob/vacatures/index-2026-35-2.xml",
    ]
    tri = sorted(urls, key=_week_key, reverse=True)
    tests.append(check(
        "Le plus récent vient en tête",
        tri[0].endswith("index-2026-35-2.xml"), tri[0].rsplit("/", 1)[-1]))
    tests.append(check(
        "Semaine 9 classée avant semaine 35, pas après (tri numérique)",
        _week_key(urls[1]) < _week_key(urls[2]),
        f"{_week_key(urls[1])} < {_week_key(urls[2])}"))
    tests.append(check(
        "Un nom non conforme ne fait pas planter le tri",
        _week_key("https://x/sitemap.xml") == (0, 0, 0)))

    print()
    print("B. ANALYSE D'UNE PAGE D'OFFRE")
    print("-" * 92)
    fiche = parse_job_page(PAGE, URL)
    tests.append(check("Page analysée", fiche is not None))
    tests.append(check("Intitulé extrait", fiche["title"] == "Laborant kwaliteitscontrole",
                       fiche["title"]))
    tests.append(check("Lieu extrait", fiche["location"] == "Regio Gent", fiche["location"]))
    tests.append(check("Description substantielle",
                       len(fiche["description"]) >= MIN_DESCRIPTION_CHARS,
                       f"{len(fiche['description'])} car."))
    for section in ("Functieomschrijving", "Profiel", "Aanbod"):
        tests.append(check(f"Section présente : {section}", section in fiche["description"]))
    tests.append(check("Contenu métier conservé", "GMP" in fiche["description"]))

    print()
    print("C. BRUIT ÉCARTÉ")
    print("-" * 92)
    # Un <script> contenant le mot d'un titre de section ne doit pas être
    # aspiré dans l'annonce : c'est le piège classique du parsing HTML.
    tests.append(check("Le <script> n'entre pas dans la description",
                       "var x" not in fiche["description"]))
    tests.append(check("La navigation n'entre pas dans la description",
                       "Vind een opleiding" not in fiche["description"]))
    tests.append(check("Le pied de page n'entre pas dans la description",
                       "VDAB ©" not in fiche["description"]))
    tests.append(check("Aucune balise HTML résiduelle",
                       "<p>" not in fiche["description"]
                       and "<li>" not in fiche["description"]))

    print()
    print("D. ROBUSTESSE")
    print("-" * 92)
    tests.append(check("Page sans <h1> : rien extrait",
                       parse_job_page(PAGE_SANS_TITRE, URL) is None))
    tests.append(check("Page vide : rien extrait, pas d'exception",
                       parse_job_page("", URL) is None))
    maigre = parse_job_page(PAGE_MAIGRE, URL)
    tests.append(check("Description trop courte : offre écartée",
                       convert_vdab_job(maigre) is None,
                       f"seuil {MIN_DESCRIPTION_CHARS}"))
    tests.append(check("HTML vide donne texte vide", html_to_text(None) == ""))
    tests.append(check("Entités HTML doublement échappées résolues",
                       "<" not in html_to_text("&amp;lt;p&amp;gt;")))

    print()
    print("E. CONVERSION")
    print("-" * 92)
    offre = convert_vdab_job(fiche)
    tests.append(check("Offre construite", offre is not None))
    tests.append(check("Identifiant tiré de l'URL",
                       offre.external_id == "vdab:60152620", offre.external_id))
    tests.append(check("Identifiant stable si l'URL change de slug",
                       job_id_from_url("https://www.vdab.be/vindeenjob/vacatures/60152620/autre")
                       == "60152620"))
    tests.append(check("Le titre ouvre la description",
                       offre.description.startswith(offre.title[:15])))
    tests.append(check("Langue déclarée nl", offre.language == "nl"))
    tests.append(check("Provenance renseignée",
                       getattr(offre, "collection_channel", "") == "VDAB"))
    # Le VDAB est le service public flamand : "Regio Gent" ne répète pas
    # "Belgique", et le listing est déclaré de confiance.
    tests.append(check("Localisation flamande acceptée comme belge",
                       getattr(offre, "belgium_status", "") != "FOREIGN",
                       getattr(offre, "belgium_status", "")))

    print()
    print("F. CONTRAT DE COMPTEURS")
    print("-" * 92)
    c = nouveaux_compteurs()
    tests.append(check("Tous les compteurs existent et valent zéro",
                       set(c) == set(COMPTEURS) and set(c.values()) == {0},
                       f"{len(c)} compteurs"))
    for oblige in ("geography_accepted", "geography_rejected", "geography_unknown"):
        tests.append(check(f"Compteur géographique présent : {oblige}", oblige in c))
    tests.append(check("Les rejets de détail sont comptés", "detail_failed" in c))
    tests.append(check("Version au moins 1.0",
                       at_least(VDAB_CONNECTOR_VERSION, "1.0"), VDAB_CONNECTOR_VERSION))

    passed = sum(1 for x in tests if x)
    total = len(tests)
    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"vdab_v1_audit_{stamp}.json").write_text(
        json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                    "connector_version": VDAB_CONNECTOR_VERSION,
                    "passed": passed, "total": total},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    if passed != total:
        raise SystemExit("[FAIL] CONNECTEUR VDAB NON VALIDÉ.")
    print("[PASS] CONNECTEUR VDAB VALIDÉ HORS LIGNE.")


if __name__ == "__main__":
    main()
