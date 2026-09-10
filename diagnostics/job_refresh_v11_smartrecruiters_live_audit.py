"""
JOB REFRESH V1.1 - SMARTRECRUITERS LIVE AUDIT

- utilise le dernier Application Queue JSON disponible ;
- choisit jusqu'à 3 SMARTRECRUITERS READY_APPLY ;
- appelle le Posting API LIVE avec use_cache=False ;
- n'écrit pas dans la DB ;
- ne crée pas de dossier de candidature.

Usage:
    python -m diagnostics.job_refresh_v11_smartrecruiters_live_audit
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from applications.job_refresh_v11 import (
    fetch_live_detail,
    parse_smartrecruiters_identity,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def candidate_queue_files():
    patterns = [
        "application_queue_v12_replay_*.json",
        "application_queue_v1_*.json",
        "application_queue_v131_replay_*.json",
    ]
    found = []
    for pattern in patterns:
        found.extend(LOG_DIR.glob(pattern))
    return sorted(
        set(found),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def load_latest_queue():
    files = candidate_queue_files()
    if not files:
        raise SystemExit("❌ Aucun Application Queue JSON trouvé.")

    path = files[0]
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, list):
        raise SystemExit("❌ Queue JSON invalide.")

    return path, payload


def main():
    queue_path, items = load_latest_queue()

    sr = [
        item
        for item in items
        if str(item.get("source") or "").upper() == "SMARTRECRUITERS"
        and item.get("queue_status") == "READY_APPLY"
    ]

    if not sr:
        raise SystemExit(
            "❌ Aucun SMARTRECRUITERS READY_APPLY trouvé dans la dernière Queue."
        )

    selected = sr[:3]
    results = []
    success_count = 0

    print("=" * 92)
    print("JOB REFRESH V1.1 - SMARTRECRUITERS LIVE AUDIT")
    print("=" * 92)
    print("Queue :", queue_path)
    print("Tests :", len(selected))
    print()

    for index, item in enumerate(selected, start=1):
        company, posting = parse_smartrecruiters_identity(item)

        print(
            f"[{index}/{len(selected)}] "
            f"{item.get('company')} | {item.get('title')}"
        )
        print(f"    Identity : {company}:{posting}")

        detail = fetch_live_detail(item)
        success = bool(detail.get("success"))
        length = int(
            detail.get("matching_text_length")
            or len(detail.get("matching_text") or "")
        )
        error = str(detail.get("error") or "")

        if success:
            success_count += 1
            status = "LIVE_OK"
        elif "404" in error:
            status = "CLOSED_404_HANDLED"
        else:
            status = "FETCH_FAILED"

        print(
            f"    {status} | "
            f"description={length} | cache={detail.get('from_cache')}"
        )
        if error:
            print("    Error    :", error)

        structured = detail.get("structured") or {}

        results.append({
            "title": item.get("title"),
            "company": item.get("company"),
            "url": item.get("url"),
            "company_identifier": company,
            "posting_id": posting,
            "status": status,
            "success": success,
            "from_cache": bool(detail.get("from_cache", False)),
            "matching_text_length": length,
            "structured_title": structured.get("title"),
            "structured_company": structured.get("company"),
            "structured_location": structured.get("location"),
            "error": error or None,
        })

    passed = (
        success_count >= 1
        and all(
            r["status"] in {"LIVE_OK", "CLOSED_404_HANDLED"}
            for r in results
        )
        and all(
            (not r["success"]) or (
                not r["from_cache"]
                and r["matching_text_length"] >= 120
            )
            for r in results
        )
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = LOG_DIR / f"job_refresh_v11_smartrecruiters_live_audit_{stamp}.json"
    txt_path = LOG_DIR / f"job_refresh_v11_smartrecruiters_live_audit_{stamp}.txt"

    payload = {
        "version": "1.1",
        "queue_path": str(queue_path),
        "tested": len(results),
        "live_success": success_count,
        "passed": passed,
        "results": results,
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "JOB REFRESH V1.1 - SMARTRECRUITERS LIVE AUDIT",
        "=" * 92,
        f"Queue        : {queue_path}",
        f"Testées      : {len(results)}",
        f"Live success : {success_count}",
        f"PASS         : {passed}",
        "",
    ]
    for r in results:
        lines.extend([
            f"{r['status']} | {r['company']} | {r['title']}",
            f"  Identity    : {r['company_identifier']}:{r['posting_id']}",
            f"  Description : {r['matching_text_length']}",
            f"  Cache       : {r['from_cache']}",
            f"  Error       : {r['error']}",
            "",
        ])

    txt_path.write_text("\n".join(lines), encoding="utf-8")

    print()
    print("Live success :", success_count, "/", len(results))
    print("TXT          :", txt_path)
    print("JSON         :", json_path)

    if not passed:
        raise SystemExit("❌ SMARTRECRUITERS LIVE AUDIT NON VALIDÉ.")

    print("✅ SMARTRECRUITERS JOB REFRESH V1.1 VALIDÉ LIVE.")


if __name__ == "__main__":
    main()
