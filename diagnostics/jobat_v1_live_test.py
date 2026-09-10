"""Test live minimal du connecteur Jobat V1. N'altère pas la base SQLite."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources.jobat import search_targeted_jobat_jobs, convert_jobat_job


def main():
    terms = ["data analyst", "laborantin", "technicien laboratoire", "quality control"]
    print("=" * 76)
    print("JOBAT V1 - TEST LIVE MINIMAL")
    print("=" * 76)
    print("Termes :", ", ".join(terms))
    print("Ce test ne modifie PAS database/jobs.db.")
    print()

    raw = search_targeted_jobat_jobs(search_terms=terms, max_pages_per_term=1)
    jobs = [convert_jobat_job(item) for item in raw]

    print()
    print("Résultat :", len(jobs), "offre(s) unique(s)")
    for job in jobs[:15]:
        print(f"- {job.title} | {job.url}")

    if not jobs:
        raise SystemExit(
            "Aucune offre récupérée. Regarde les lignes HTTP/EDGE ci-dessus et envoie-les moi si nécessaire."
        )

    print()
    print("✅ TEST JOBAT VALIDÉ : le collecteur remonte des offres.")


if __name__ == "__main__":
    main()
