"""
JOB HUNTER BELGIUM
SMARTRECRUITERS V1 - AUDIT

1. Tests synthétiques du parseur.
2. Test LIVE de l'API SmartRecruiters.
3. Scoring avec le Matcher installé.
4. Audit best-effort du chevauchement avec raw_jobs.
5. Exports automatiques TXT + JSON.

Usage :
    python -m diagnostics.smartrecruiters_v1_audit --synthetic-only
    python -m diagnostics.smartrecruiters_v1_audit
    python -m diagnostics.smartrecruiters_v1_audit --limit-per-company 10
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

from config.smartrecruiters_sources import (
    SMARTRECRUITERS_COMPANIES,
    SMARTRECRUITERS_TOP_N,
)
from sources.smartrecruiters import (
    _belgium_location,
    _sections_text,
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
    text = "".join(
        c for c in text
        if not unicodedata.combining(c)
    )
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def synthetic_tests():
    results = []

    def check(label, condition):
        ok = bool(condition)
        print(f"{'✅' if ok else '❌'} {label}")
        results.append(ok)

    detail = {
        "id": "123",
        "uuid": "abc",
        "name": "QC Laboratory Analyst",
        "company": {
            "identifier": "TestLab",
            "name": "Test Laboratory Belgium",
        },
        "releasedDate": "2026-08-18T10:00:00.000Z",
        "location": {
            "city": "Wavre",
            "region": "Walloon Brabant",
            "country": "be",
            "remote": False,
        },
        "department": {"label": "Quality Control"},
        "function": {"label": "Science"},
        "typeOfEmployment": {"label": "Full-time"},
        "experienceLevel": {"label": "Associate"},
        "applyUrl": "https://jobs.smartrecruiters.com/TestLab/123",
        "jobAd": {
            "sections": {
                "jobDescription": {
                    "title": "Job Description",
                    "text": "<p>Perform HPLC and UPLC analyses under GMP.</p>",
                },
                "qualifications": {
                    "title": "Qualifications",
                    "text": "<p>Bachelor in Chemistry.</p>",
                },
            }
        },
    }

    check(
        "Belgique détectée",
        _belgium_location(detail["location"]),
    )
    check(
        "France refusée",
        not _belgium_location({"country": "fr"}),
    )

    text, sections = _sections_text(detail)
    check("HTML nettoyé", "<p>" not in text)
    check("HPLC conservé", "HPLC" in text)
    check("Qualifications conservées", "Bachelor in Chemistry" in text)

    job = posting_to_job("TestLab", detail)
    check("Source SMARTRECRUITERS", job.source == "SMARTRECRUITERS")
    check("External ID stable", job.external_id == "TestLab:123")
    check("Entreprise réelle", job.company == "Test Laboratory Belgium")
    check("Ville Wavre", "Wavre" in job.location)
    check("Description complète", "UPLC" in job.description)
    check(
        "Origin source",
        getattr(job, "origin_source", "") == "TestLab",
    )
    check(
        "Direct employer",
        getattr(job, "direct_employer", False) is True,
    )

    print()
    print(
        f"Tests synthétiques : "
        f"{sum(results)}/{len(results)}"
    )
    if not all(results):
        raise SystemExit(
            "❌ SMARTRECRUITERS V1 NON VALIDÉ."
        )
    print(
        "✅ SMARTRECRUITERS V1 VALIDÉ "
        "SUR LE DIAGNOSTIC SYNTHÉTIQUE."
    )
    return len(results)


def load_existing_index():
    """
    Best effort seulement.
    Ne modifie jamais jobs.db.
    """
    exact_title_company = set()
    exact_title_location = set()

    if not DB_PATH.exists():
        return exact_title_company, exact_title_location

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row

        exists = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type='table' AND name='raw_jobs'
            """
        ).fetchone()
        if not exists:
            return exact_title_company, exact_title_location

        cols = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(raw_jobs)"
            ).fetchall()
        }
        needed = {"title", "company", "location"}
        if not needed.issubset(cols):
            return exact_title_company, exact_title_location

        for row in conn.execute(
            """
            SELECT title, company, location
            FROM raw_jobs
            WHERE title IS NOT NULL
            """
        ):
            t = norm(row["title"])
            c = norm(row["company"])
            l = norm(row["location"])
            if t and c:
                exact_title_company.add((t, c))
            if t and l:
                exact_title_location.add((t, l))

        conn.close()
    except Exception:
        pass

    return exact_title_company, exact_title_location


def likely_existing(job, idx_tc, idx_tl):
    t = norm(job.title)
    c = norm(job.company)
    l = norm(job.location)

    if t and c and (t, c) in idx_tc:
        return True, "exact_title_company"
    if t and l and (t, l) in idx_tl:
        return True, "exact_title_location"
    return False, ""


def run_live(limit_per_company=None):
    jobs, metas = fetch_smartrecruiters_jobs(
        companies=SMARTRECRUITERS_COMPANIES,
        detail_limit_per_company=limit_per_company,
    )

    idx_tc, idx_tl = load_existing_index()

    records = []
    for job in jobs:
        try:
            match = score_job(job)
        except Exception as exc:
            match = {
                "score": 0.0,
                "core_relevance": False,
                "best_family": "ERROR",
                "confidence_level": "UNKNOWN",
                "provisional": True,
                "reasons": [
                    f"Matcher error: "
                    f"{type(exc).__name__}: {exc}"
                ],
            }

        existing, overlap_method = likely_existing(
            job, idx_tc, idx_tl
        )

        records.append(
            {
                "source": job.source,
                "origin_source": getattr(
                    job, "origin_source", ""
                ),
                "external_id": job.external_id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "date_published": job.date_published,
                "contract_type": job.contract_type,
                "url": job.url,
                "description_length": len(
                    clean(job.description)
                ),
                "match_score": float(
                    match.get("score") or 0
                ),
                "core_relevance": bool(
                    match.get("core_relevance")
                ),
                "best_family": clean(
                    match.get("best_family")
                ),
                "confidence": clean(
                    match.get("confidence_level")
                ),
                "provisional": bool(
                    match.get("provisional")
                ),
                "match_reasons": list(
                    match.get("reasons") or []
                ),
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
        if row["already_seen_likely"]:
            summary["likely_existing"] += 1
        elif row["core_relevance"]:
            summary["likely_new_relevant"] += 1

    for meta in metas:
        key = clean(
            meta.get("company_identifier")
        )
        summary[
            f"{key}_belgium"
        ] = int(meta.get("listings_belgium") or 0)
        summary[
            f"{key}_converted"
        ] = int(meta.get("jobs_converted") or 0)
        summary[
            f"{key}_failures"
        ] = len(meta.get("failures") or [])
        if meta.get("fatal_error"):
            summary[
                f"{key}_fatal"
            ] += 1

    return {
        "version": "1.0",
        "generated_at": datetime.now().isoformat(
            timespec="seconds"
        ),
        "limit_per_company": limit_per_company,
        "companies": SMARTRECRUITERS_COMPANIES,
        "company_results": metas,
        "summary": dict(summary),
        "records": records,
    }


def export(payload):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt = (
        LOG_DIR /
        f"smartrecruiters_v1_audit_{stamp}.txt"
    )
    js = (
        LOG_DIR /
        f"smartrecruiters_v1_audit_{stamp}.json"
    )

    js.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    s = payload["summary"]
    lines = [
        "SMARTRECRUITERS V1 - LIVE AUDIT",
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
                f"{meta.get('label')} "
                f"({meta.get('company_identifier')})",
                f"  offres BE liste : "
                f"{meta.get('listings_belgium', 0)}",
                f"  détails tentés  : "
                f"{meta.get('details_attempted', 0)}",
                f"  converties      : "
                f"{meta.get('jobs_converted', 0)}",
                f"  échecs détail   : "
                f"{len(meta.get('failures') or [])}",
            ]
        )
        if meta.get("fatal_error"):
            lines.append(
                f"  ❌ FATAL         : "
                f"{meta.get('fatal_error')}"
            )
        lines.append("")

    lines.extend(
        [
            "",
            "OFFRES PERTINENTES",
            "-" * 96,
        ]
    )

    relevant = [
        x for x in payload["records"]
        if x["core_relevance"]
    ]

    if not relevant:
        lines.append(
            "Aucune offre core_relevant "
            "dans ce test."
        )

    for i, row in enumerate(
        relevant[:SMARTRECRUITERS_TOP_N],
        1,
    ):
        badge = (
            "DÉJÀ_VU?"
            if row["already_seen_likely"]
            else "🔥 NEW?"
        )
        lines.extend(
            [
                f"{i:>3}. {badge:<9} | "
                f"{row['origin_source']:<14} | "
                f"S{row['match_score']:>5.1f} | "
                f"{row['best_family']}",
                f"     {row['title']}",
                f"     {row['company']} | "
                f"{row['location']}",
                f"     {row['url']}",
                "",
            ]
        )

    lines.extend(
        [
            "",
            "NOTE",
            "-" * 96,
            "NEW?/DÉJÀ_VU? est un audit best-effort basé sur "
            "titre+entreprise ou titre+lieu exacts normalisés.",
            "La déduplication canonique officielle reste celle du pipeline.",
            "",
            f"JSON : {js}",
        ]
    )

    txt.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )
    return txt, js


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--synthetic-only",
        action="store_true",
    )
    parser.add_argument(
        "--limit-per-company",
        type=int,
        default=None,
    )
    args = parser.parse_args()

    synthetic_tests()

    if args.synthetic_only:
        return

    print()
    print("Connexion live SmartRecruiters...")
    payload = run_live(
        limit_per_company=args.limit_per_company
    )
    txt, js = export(payload)

    s = payload["summary"]
    print()
    print("=" * 96)
    print("SMARTRECRUITERS V1 - LIVE")
    print("=" * 96)
    print(
        "Total BE       :",
        s.get("total_jobs", 0),
    )
    print(
        "Core relevant  :",
        s.get("core_relevant", 0),
    )
    print(
        "New relevant ? :",
        s.get("likely_new_relevant", 0),
    )
    print("TXT  :", txt)
    print("JSON :", js)


if __name__ == "__main__":
    main()
