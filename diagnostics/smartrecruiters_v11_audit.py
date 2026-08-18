"""
SMARTRECRUITERS V1.1 - DIAGNOSTIC

Vérifie spécifiquement que le texte corporate n'est plus transmis au Matcher.

Usage :
    python -m diagnostics.smartrecruiters_v11_audit --synthetic-only
    python -m diagnostics.smartrecruiters_v11_audit --limit-per-company 10
    python -m diagnostics.smartrecruiters_v11_audit
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

from config.smartrecruiters_sources import SMARTRECRUITERS_COMPANIES
from sources.smartrecruiters import (
    _extract_job_ad,
    posting_to_job,
    fetch_smartrecruiters_jobs,
)
from matching.basic_matcher import score_job


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = PROJECT_ROOT / "database" / "jobs.db"


def clean(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def norm(value):
    text = clean(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def synthetic_tests():
    tests = []

    def check(label, condition, detail=""):
        ok = bool(condition)
        tests.append(ok)
        print(
            f"{'✅' if ok else '❌'} {label}"
            + (f": {detail}" if detail else "")
        )

    detail = {
        "id": "TEST-1",
        "name": "Real Estate Portfolio Manager",
        "company": {"name": "Fake Pharma Group"},
        "location": {
            "city": "Brussels",
            "country": "be",
        },
        "jobAd": {
            "sections": {
                "companyDescription": {
                    "text": (
                        "<p>Global pharmaceutical laboratory, "
                        "biopharma, diagnostics, Power BI, "
                        "data governance, GMP and quality.</p>"
                    )
                },
                "jobDescription": {
                    "text": (
                        "<p>Manage office leases, landlords, "
                        "property budgets and real-estate projects.</p>"
                    )
                },
                "qualifications": {
                    "text": (
                        "<p>Experience in commercial real estate.</p>"
                    )
                },
            }
        },
    }

    extracted = _extract_job_ad(detail)

    check(
        "companyDescription séparée",
        "pharmaceutical" in extracted["company_description"].lower(),
    )
    check(
        "companyDescription exclue du matching_text",
        "pharmaceutical" not in extracted["matching_text"].lower(),
    )
    check(
        "Texte réel du poste conservé",
        "real estate" in extracted["matching_text"].lower(),
    )

    job = posting_to_job("FakePharma", detail)

    check(
        "JobOffer.description sans corporate",
        "biopharma" not in job.description.lower(),
    )
    check(
        "company_description conservée en attribut",
        "biopharma" in getattr(job, "company_description", "").lower(),
    )
    check(
        "Titre conservé",
        job.title == "Real Estate Portfolio Manager",
    )
    check(
        "External ID stable",
        job.external_id == "FakePharma:TEST-1",
    )

    print()
    print(f"Tests synthétiques : {sum(tests)}/{len(tests)}")

    if not all(tests):
        raise SystemExit(
            "❌ SMARTRECRUITERS V1.1 NON VALIDÉ."
        )

    print(
        "✅ SMARTRECRUITERS V1.1 VALIDÉ "
        "SUR LE DIAGNOSTIC SYNTHÉTIQUE."
    )


def load_existing_index():
    title_company = set()
    title_location = set()

    if not DB_PATH.exists():
        return title_company, title_location

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row

        if not conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='raw_jobs'
            """
        ).fetchone():
            return title_company, title_location

        cols = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(raw_jobs)"
            ).fetchall()
        }

        if not {"title", "company", "location"}.issubset(cols):
            return title_company, title_location

        for row in conn.execute(
            "SELECT title, company, location FROM raw_jobs"
        ):
            t = norm(row["title"])
            c = norm(row["company"])
            l = norm(row["location"])

            if t and c:
                title_company.add((t, c))
            if t and l:
                title_location.add((t, l))

        conn.close()
    except Exception:
        pass

    return title_company, title_location


def likely_existing(job, tc, tl):
    t = norm(job.title)
    c = norm(job.company)
    l = norm(job.location)

    if t and c and (t, c) in tc:
        return True, "exact_title_company"
    if t and l and (t, l) in tl:
        return True, "exact_title_location"

    return False, ""


def run_live(limit_per_company=None):
    jobs, metas = fetch_smartrecruiters_jobs(
        companies=SMARTRECRUITERS_COMPANIES,
        detail_limit_per_company=limit_per_company,
    )

    tc, tl = load_existing_index()

    records = []

    for job in jobs:
        try:
            match = score_job(job)
        except Exception as exc:
            match = {
                "score": 0.0,
                "core_relevance": False,
                "best_family": "ERROR",
                "reasons": [
                    f"{type(exc).__name__}: {exc}"
                ],
            }

        existing, overlap_method = likely_existing(job, tc, tl)

        records.append(
            {
                "origin_source": getattr(job, "origin_source", ""),
                "external_id": job.external_id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "date_published": job.date_published,
                "url": job.url,
                "description_length": len(job.description or ""),
                "company_description_length": len(
                    getattr(job, "company_description", "") or ""
                ),
                "match_score": float(match.get("score") or 0),
                "core_relevance": bool(match.get("core_relevance")),
                "best_family": clean(match.get("best_family")),
                "match_reasons": list(match.get("reasons") or []),
                "already_seen_likely": existing,
                "overlap_method": overlap_method,
            }
        )

    records.sort(
        key=lambda x: (
            not x["core_relevance"],
            -x["match_score"],
            x["origin_source"],
            x["title"].lower(),
        )
    )

    summary = Counter()
    summary["total_jobs"] = len(records)

    for row in records:
        if row["core_relevance"]:
            summary["core_relevant"] += 1
            if not row["already_seen_likely"]:
                summary["likely_new_relevant"] += 1
        if row["already_seen_likely"]:
            summary["likely_existing"] += 1

    for meta in metas:
        identifier = clean(meta.get("company_identifier"))
        summary[f"{identifier}_belgium"] = int(
            meta.get("listings_belgium") or 0
        )
        summary[f"{identifier}_converted"] = int(
            meta.get("jobs_converted") or 0
        )
        summary[f"{identifier}_failures"] = len(
            meta.get("failures") or []
        )
        if meta.get("fatal_error"):
            summary[f"{identifier}_fatal"] += 1

    return {
        "version": "1.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "limit_per_company": limit_per_company,
        "company_results": metas,
        "summary": dict(summary),
        "records": records,
    }


def export(payload):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt_path = LOG_DIR / f"smartrecruiters_v11_audit_{stamp}.txt"
    json_path = LOG_DIR / f"smartrecruiters_v11_audit_{stamp}.json"

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    s = payload["summary"]

    lines = [
        "SMARTRECRUITERS V1.1 - LIVE AUDIT",
        "=" * 96,
        f"Total Belgique converti     : {s.get('total_jobs', 0)}",
        f"Matcher core relevant       : {s.get('core_relevant', 0)}",
        f"Probablement déjà vu DB     : {s.get('likely_existing', 0)}",
        f"🔥 Probablement NEW + relevant: {s.get('likely_new_relevant', 0)}",
        "",
        "PAR EMPLOYEUR",
        "-" * 96,
    ]

    for meta in payload["company_results"]:
        lines.extend(
            [
                f"{meta.get('label')} ({meta.get('company_identifier')})",
                f"  offres BE liste : {meta.get('listings_belgium', 0)}",
                f"  détails tentés  : {meta.get('details_attempted', 0)}",
                f"  converties      : {meta.get('jobs_converted', 0)}",
                f"  échecs détail   : {len(meta.get('failures') or [])}",
            ]
        )
        if meta.get("fatal_error"):
            lines.append(
                f"  ❌ FATAL         : {meta.get('fatal_error')}"
            )
        lines.append("")

    lines.extend(
        [
            "",
            "OFFRES CORE RELEVANT APRÈS NETTOYAGE CORPORATE",
            "-" * 96,
        ]
    )

    relevant = [
        x for x in payload["records"]
        if x["core_relevance"]
    ]

    if not relevant:
        lines.append("Aucune offre core_relevant.")

    for i, row in enumerate(relevant, 1):
        badge = "DÉJÀ_VU?" if row["already_seen_likely"] else "🔥 NEW?"
        lines.extend(
            [
                f"{i:>3}. {badge:<9} | "
                f"{row['origin_source']:<14} | "
                f"S{row['match_score']:>5.1f} | "
                f"{row['best_family']}",
                f"     {row['title']}",
                f"     {row['company']} | {row['location']}",
                f"     job_text={row['description_length']} | "
                f"corporate_saved={row['company_description_length']}",
                f"     {row['url']}",
                "",
            ]
        )

    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return txt_path, json_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--limit-per-company", type=int, default=None)
    args = parser.parse_args()

    synthetic_tests()

    if args.synthetic_only:
        return

    print()
    print("Connexion live SmartRecruiters V1.1...")

    payload = run_live(
        limit_per_company=args.limit_per_company
    )
    txt_path, json_path = export(payload)

    s = payload["summary"]

    print()
    print("=" * 96)
    print("SMARTRECRUITERS V1.1 - LIVE")
    print("=" * 96)
    print("Total BE       :", s.get("total_jobs", 0))
    print("Core relevant  :", s.get("core_relevant", 0))
    print("New relevant ? :", s.get("likely_new_relevant", 0))
    print("TXT  :", txt_path)
    print("JSON :", json_path)


if __name__ == "__main__":
    main()
