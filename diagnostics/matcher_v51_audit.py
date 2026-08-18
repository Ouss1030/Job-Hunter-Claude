"""
JOB HUNTER BELGIUM
DIAGNOSTIC MATCHER V5.1

But :
- vérifier que les bons métiers Chimie/Labo/Data restent hauts ;
- vérifier que les faux positifs carrière/mine/production générique sortent ;
- vérifier que les plafonds Data senior restent actifs ;
- mesurer rapidement les performances du nouveau matcher ;
- écrire automatiquement le résultat dans exports/logs/.

Lancement depuis la racine du projet :

    python -m diagnostics.matcher_v51_audit
"""

import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from config.profile import COLLECTION_SEARCH_TERMS
from matching.basic_matcher import score_job


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()


def make_job(title, description, location="Bruxelles, Belgique"):
    return SimpleNamespace(
        source="TEST",
        external_id="TEST",
        title=title,
        company="Entreprise test",
        location=location,
        description=description,
        url="",
        date_published=None,
        contract_type="CDI",
        language="Français",
        salary=None,
        detail_enrichment_attempted=True,
        detail_enrichment_success=True,
        detail_matching_text_length=max(800, len(description)),
    )


def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"matcher_v51_audit_{timestamp}.txt"

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    with log_path.open("w", encoding="utf-8") as log_file:
        sys.stdout = Tee(original_stdout, log_file)
        sys.stderr = Tee(original_stderr, log_file)

        try:
            print()
            print("=" * 80)
            print("                 MATCHER V5.1 - AUDIT RAPIDE")
            print("=" * 80)
            print()
            print("Termes de collecte :", len(COLLECTION_SEARCH_TERMS))
            print("Attendu            : 199")
            print()

            tests = [
                {
                    "name": "Technicien chimiste",
                    "job": make_job(
                        "Technicien chimiste",
                        "Laboratoire de chimie analytique. Analyses HPLC, chromatographie, contrôle qualité, LIMS.",
                    ),
                    "check": lambda r: r["core_relevance"] and r["score"] >= 80,
                    "expected": "core=True et score >= 80",
                },
                {
                    "name": "Technisch Laborant",
                    "job": make_job(
                        "Technisch Laborant",
                        "Chemisch laboratorium. HPLC, kwaliteitscontrole en LIMS.",
                    ),
                    "check": lambda r: r["core_relevance"] and r["score"] >= 80,
                    "expected": "core=True et score >= 80",
                },
                {
                    "name": "Laboratory Analyst Physico-Chemistry",
                    "job": make_job(
                        "Laboratory Analyst - Physico-Chemistry",
                        "Analytical chemistry laboratory. HPLC, UPLC, physicochemical analysis, GMP and LIMS.",
                    ),
                    "check": lambda r: r["core_relevance"] and r["score"] >= 80,
                    "expected": "core=True et score >= 80",
                },
                {
                    "name": "Junior Data Analyst",
                    "job": make_job(
                        "Junior Data Analyst",
                        "Python, pandas, SQL, Power BI, reporting, dashboards and statistics. Junior position.",
                    ),
                    "check": lambda r: r["core_relevance"] and r["score"] >= 80,
                    "expected": "core=True et score >= 80",
                },
                {
                    "name": "Senior Data Analyst 5 ans",
                    "job": make_job(
                        "Senior Data Analyst",
                        "SQL, Power BI, Python, pandas, reporting. Minimum 5 years of experience.",
                    ),
                    "check": lambda r: r["score"] <= 55,
                    "expected": "score <= 55",
                },
                {
                    "name": "Aide-mineur / extraction",
                    "job": make_job(
                        "Aide-mineur",
                        "Travail en carrière, mine, forage, extraction de pierre, concassage et production industrielle.",
                    ),
                    "check": lambda r: not r["core_relevance"],
                    "expected": "core=False",
                },
                {
                    "name": "Ouvrier en carrière",
                    "job": make_job(
                        "Ouvrier en Carrière",
                        "Carrière, extraction, concassage, mine, forage et production de chaux.",
                    ),
                    "check": lambda r: not r["core_relevance"],
                    "expected": "core=False",
                },
                {
                    "name": "Technicien production pharma",
                    "job": make_job(
                        "Technicien de production",
                        "Industrie pharmaceutique GMP, salle blanche, formulation, laboratoire QC et LIMS.",
                    ),
                    "check": lambda r: r["core_relevance"] and r["score"] >= 65,
                    "expected": "core=True et score >= 65",
                },
                {
                    "name": "Technicien production construction",
                    "job": make_job(
                        "Technicien de production",
                        "Construction, mécanique, métallurgie, soudure et maintenance industrielle.",
                    ),
                    "check": lambda r: not r["core_relevance"],
                    "expected": "core=False",
                },
                {
                    "name": "Quality métal",
                    "job": make_job(
                        "Medewerker kwaliteitscontrole Metaal",
                        "Kwaliteitscontrole in metaalindustrie, mechanica, lassen en productie.",
                    ),
                    "check": lambda r: r["score"] < 65,
                    "expected": "score < 65",
                },
                {
                    "name": "Research technician générique",
                    "job": make_job(
                        "Research technician",
                        "Research support in mechanical engineering and construction materials.",
                    ),
                    "check": lambda r: not r["core_relevance"],
                    "expected": "core=False",
                },
                {
                    "name": "Research technician laboratoire",
                    "job": make_job(
                        "Research technician",
                        "R&D laboratory, analytical chemistry, HPLC, sample preparation and chromatography.",
                    ),
                    "check": lambda r: r["core_relevance"] and r["score"] >= 65,
                    "expected": "core=True et score >= 65",
                },
            ]

            passed = 0

            for index, test in enumerate(tests, start=1):
                result = score_job(test["job"])
                ok = bool(test["check"](result))
                passed += int(ok)

                print(
                    f"[{index:02d}/{len(tests):02d}] "
                    f"{'✅' if ok else '❌'} "
                    f"{test['name']}"
                )
                print(
                    f"         score={result['score']:.1f} | "
                    f"core={result['core_relevance']} | "
                    f"famille={result['best_family']}"
                )
                print("         attendu :", test["expected"])

            collection_ok = len(COLLECTION_SEARCH_TERMS) == 199

            print()
            print("=" * 80)
            print("BENCHMARK")
            print("=" * 80)

            templates = [test["job"] for test in tests]
            bench_jobs = [templates[i % len(templates)] for i in range(1000)]

            start = time.perf_counter()
            for job in bench_jobs:
                score_job(job)
            elapsed = time.perf_counter() - start

            print(f"1000 scorings : {elapsed:.3f} s")
            print(f"Moyenne       : {(elapsed / 1000) * 1000:.3f} ms/offre")

            print()
            print("=" * 80)
            print("RÉSULTAT")
            print("=" * 80)
            print()
            print(f"Tests métier : {passed}/{len(tests)}")
            print("199 termes   :", "OK" if collection_ok else "ERREUR")

            all_ok = passed == len(tests) and collection_ok

            if all_ok:
                print()
                print("✅ MATCHER V5.1 VALIDÉ SUR LE DIAGNOSTIC.")
                print("Tu peux lancer : python main.py")
            else:
                print()
                print("❌ NE PAS LANCER main.py.")
                print("Envoie ce TXT pour correction.")

            print()
            print("TXT :", log_path)

        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr

    print()
    print("TXT généré automatiquement :")
    print(log_path)


if __name__ == "__main__":
    main()
