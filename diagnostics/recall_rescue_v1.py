"""
JOB HUNTER BELGIUM
RECALL RESCUE - VERSION 1.0

Objectif
========
Tester les faux négatifs potentiels détectés par Funnel Recall Audit V1 sans
modifier le Matcher, le Gate, la Queue, Canonical ni la base.

Le module :
1. charge le dernier funnel_recall_audit_v1_*.json ;
2. prend uniquement high_recall_risk_items ;
3. enrichit ces offres via les enrichisseurs déjà validés du projet ;
4. rescrore avec le Matcher actuel ;
5. applique Application Gate V1.2 si l'offre devient core_relevant ;
6. exporte TXT + JSON.

Aucune écriture DB.

Usage :
    python -m diagnostics.recall_rescue_v1

Optionnel :
    python -m diagnostics.recall_rescue_v1 --limit 10
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from database.models import JobOffer
from matching.basic_matcher import score_job
from matching.application_gate import evaluate_application_gate

from main import (
    get_job_detail,
    apply_structured_data,
    apply_detail_description,
)


RESCUE_VERSION = "1.0"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def latest_file(directory, pattern):
    paths = list(Path(directory).glob(pattern))
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_mtime)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def audit_item_to_job(item):
    job = JobOffer(
        source=clean_text(item.get("source")),
        external_id=clean_text(item.get("external_id")),
        title=clean_text(item.get("title")),
        company=clean_text(item.get("company")),
        location=clean_text(item.get("location")),
        description="",
        url=clean_text(item.get("url")),
        date_published="",
        contract_type="",
        language="",
        salary="",
        date_collected="",
    )

    job.collection_channel = clean_text(item.get("collection_channel")) or job.source
    job.origin_source = clean_text(item.get("origin_source")) or job.source
    job.source_eligibility_status = "ELIGIBLE"
    job.source_eligibility_reason = None
    return job


def unique_high_risk_items(audit):
    items = audit.get("high_recall_risk_items") or []
    seen = set()
    out = []

    for item in items:
        key = (
            clean_text(item.get("source")).upper(),
            clean_text(item.get("external_id")),
        )
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        out.append(item)

    return out


def rescue_one(item):
    job = audit_item_to_job(item)

    before = {
        "core_relevance": bool(item.get("matcher_core_relevance")),
        "score": float(item.get("matcher_score") or 0),
        "family": clean_text(item.get("matcher_family")),
        "reasons": item.get("matcher_reasons") or [],
    }

    try:
        detail = get_job_detail(job)
    except Exception as exc:
        detail = {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": {},
            "from_cache": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    result = {
        "rescue_version": RESCUE_VERSION,
        "raw_job_id": item.get("raw_job_id"),
        "source": job.source,
        "origin_source": getattr(job, "origin_source", job.source),
        "external_id": job.external_id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "watch_buckets": item.get("watch_buckets") or [],
        "before": before,
        "detail_success": bool(detail.get("success")),
        "detail_from_cache": bool(detail.get("from_cache", False)),
        "detail_length": int(
            detail.get("matching_text_length")
            or len(detail.get("matching_text") or "")
        ),
        "detail_error": detail.get("error"),
        "after": None,
        "gate": None,
        "rescue_status": None,
    }

    if not detail.get("success"):
        result["rescue_status"] = "FETCH_FAILED"
        return result

    apply_structured_data(job, detail)
    apply_detail_description(job, detail)

    # Important : aucune persistance DB dans ce diagnostic.
    try:
        after = score_job(job)
    except Exception as exc:
        result["rescue_status"] = "SCORE_FAILED"
        result["detail_error"] = f"{type(exc).__name__}: {exc}"
        return result

    result["title"] = clean_text(job.title)
    result["company"] = clean_text(job.company)
    result["location"] = clean_text(job.location)
    result["after"] = {
        "core_relevance": bool(after.get("core_relevance")),
        "score": float(after.get("score") or 0),
        "family": clean_text(after.get("best_family")),
        "confidence": clean_text(after.get("confidence_label")),
        "provisional": bool(after.get("provisional")),
        "reasons": after.get("reasons") or [],
    }

    if not after.get("core_relevance"):
        result["rescue_status"] = "STILL_OUT"
        return result

    try:
        gate = evaluate_application_gate(job, after)
    except Exception as exc:
        result["rescue_status"] = "GATE_FAILED"
        result["detail_error"] = f"{type(exc).__name__}: {exc}"
        return result

    result["gate"] = gate
    status = clean_text(gate.get("status"))

    if status == "APPLY":
        result["rescue_status"] = "RESCUED_APPLY"
    elif status == "STRETCH":
        result["rescue_status"] = "RESCUED_STRETCH"
    elif status == "VERIFY":
        result["rescue_status"] = "RESCUED_VERIFY"
    else:
        result["rescue_status"] = "RESCUED_REJECT"

    return result


def rescue_batch(items):
    results = []
    total = len(items)

    print("=" * 84)
    print("RECALL RESCUE V1")
    print("=" * 84)
    print("Candidats HIGH à enrichir :", total)
    print()

    for index, item in enumerate(items, start=1):
        print(f"[{index:>2}/{total}] {clean_text(item.get('title'))[:68]}")
        result = rescue_one(item)
        results.append(result)

        after = result.get("after") or {}
        gate = result.get("gate") or {}
        print(
            "    ->",
            result.get("rescue_status"),
            f"| score {after.get('score', 0):.1f}" if after else "",
            f"| gate {gate.get('status')}" if gate else "",
        )

    return results


def summary(results):
    counts = Counter(x.get("rescue_status") for x in results)
    return {
        "total": len(results),
        "detail_success": sum(1 for x in results if x.get("detail_success")),
        "RESCUED_APPLY": counts.get("RESCUED_APPLY", 0),
        "RESCUED_STRETCH": counts.get("RESCUED_STRETCH", 0),
        "RESCUED_VERIFY": counts.get("RESCUED_VERIFY", 0),
        "RESCUED_REJECT": counts.get("RESCUED_REJECT", 0),
        "STILL_OUT": counts.get("STILL_OUT", 0),
        "FETCH_FAILED": counts.get("FETCH_FAILED", 0),
        "SCORE_FAILED": counts.get("SCORE_FAILED", 0),
        "GATE_FAILED": counts.get("GATE_FAILED", 0),
    }


def export_results(results, audit_path):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt_path = LOG_DIR / f"recall_rescue_v1_{stamp}.txt"
    json_path = LOG_DIR / f"recall_rescue_v1_{stamp}.json"

    payload = {
        "rescue_version": RESCUE_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "funnel_audit_source": str(audit_path),
        "summary": summary(results),
        "results": results,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    s = payload["summary"]
    lines = [
        "RECALL RESCUE V1",
        "=" * 84,
        f"Audit source      : {audit_path}",
        f"Total HIGH        : {s['total']}",
        f"Détails récupérés : {s['detail_success']}",
        "",
        f"RESCUED_APPLY     : {s['RESCUED_APPLY']}",
        f"RESCUED_STRETCH   : {s['RESCUED_STRETCH']}",
        f"RESCUED_VERIFY    : {s['RESCUED_VERIFY']}",
        f"RESCUED_REJECT    : {s['RESCUED_REJECT']}",
        f"STILL_OUT         : {s['STILL_OUT']}",
        f"FETCH_FAILED      : {s['FETCH_FAILED']}",
        "",
        "OFFRES RÉCUPÉRÉES POUR CANDIDATURE",
        "-" * 84,
    ]

    actionable = [
        x for x in results
        if x.get("rescue_status") in {
            "RESCUED_APPLY", "RESCUED_STRETCH", "RESCUED_VERIFY"
        }
    ]
    actionable.sort(
        key=lambda x: (
            {"RESCUED_APPLY": 3, "RESCUED_STRETCH": 2, "RESCUED_VERIFY": 1}.get(
                x.get("rescue_status"), 0
            ),
            float((x.get("after") or {}).get("score") or 0),
        ),
        reverse=True,
    )

    if not actionable:
        lines.append("Aucune offre récupérée en APPLY/STRETCH/VERIFY.")
    else:
        for idx, item in enumerate(actionable, start=1):
            after = item.get("after") or {}
            gate = item.get("gate") or {}
            lines.extend([
                f"{idx:>2}. {item.get('rescue_status')} | "
                f"M{float(after.get('score') or 0):.1f} | "
                f"GATE {gate.get('status')}",
                f"    {item.get('title')}",
                f"    {item.get('company')} | {item.get('location')}",
                f"    Famille : {after.get('family')}",
                f"    {item.get('url')}",
                "",
            ])

    lines.extend([
        "REJETS / TOUJOURS HORS CIBLE",
        "-" * 84,
    ])
    for item in results:
        if item.get("rescue_status") not in {
            "RESCUED_REJECT", "STILL_OUT", "FETCH_FAILED"
        }:
            continue
        after = item.get("after") or {}
        gate = item.get("gate") or {}
        reason = ""
        if gate:
            reasons = gate.get("hard_reasons") or gate.get("reasons") or []
            reason = " | ".join(clean_text(x) for x in reasons[:2])
        elif after:
            reason = " | ".join(clean_text(x) for x in (after.get("reasons") or [])[:2])
        else:
            reason = clean_text(item.get("detail_error"))

        lines.extend([
            f"- {item.get('rescue_status')} | {item.get('title')}",
            f"  {item.get('company')} | {item.get('location')}",
            f"  {reason}",
        ])

    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return txt_path, json_path


def main():
    parser = argparse.ArgumentParser(description="Recall Rescue V1")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    audit_path = latest_file(LOG_DIR, "funnel_recall_audit_v1_*.json")
    if not audit_path:
        raise SystemExit("Aucun funnel_recall_audit_v1_*.json trouvé dans exports/logs.")

    audit = load_json(audit_path)
    items = unique_high_risk_items(audit)
    if args.limit is not None:
        items = items[: max(0, int(args.limit))]

    if not items:
        raise SystemExit("Aucune alerte HIGH à tester.")

    results = rescue_batch(items)
    txt_path, json_path = export_results(results, audit_path)
    s = summary(results)

    print()
    print("=" * 84)
    print("BILAN RECALL RESCUE V1")
    print("=" * 84)
    print("RESCUED_APPLY   :", s["RESCUED_APPLY"])
    print("RESCUED_STRETCH :", s["RESCUED_STRETCH"])
    print("RESCUED_VERIFY  :", s["RESCUED_VERIFY"])
    print("RESCUED_REJECT  :", s["RESCUED_REJECT"])
    print("STILL_OUT       :", s["STILL_OUT"])
    print("FETCH_FAILED    :", s["FETCH_FAILED"])
    print("TXT             :", txt_path)
    print("JSON            :", json_path)


if __name__ == "__main__":
    main()
