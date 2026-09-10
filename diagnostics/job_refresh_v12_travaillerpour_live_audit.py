"""
JOB REFRESH V1.2 - TRAVAILLERPOUR LIVE AUDIT

Cherche la dernière Application Preparation et teste le premier item
TRAVAILLERPOUR en live, sans DB write.

Usage:
python -m diagnostics.job_refresh_v12_travaillerpour_live_audit
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from applications.job_refresh_v12 import (
    fetch_live_detail,
    parse_travaillerpour_external_id,
)


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "exports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def latest_file(directory, pattern):
    paths = list(Path(directory).glob(pattern))
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_mtime)


def main():
    prep_path = latest_file(
        LOG_DIR,
        "application_preparation_v1_*.json",
    )
    if prep_path is None:
        raise SystemExit("❌ Aucun Application Preparation JSON trouvé.")

    items = json.loads(prep_path.read_text(encoding="utf-8"))
    tp = [
        item for item in items
        if str(item.get("source") or "").upper() == "TRAVAILLERPOUR"
    ]

    if not tp:
        raise SystemExit(
            "❌ Aucun item TRAVAILLERPOUR dans la dernière préparation."
        )

    item = tp[0]
    external_id = parse_travaillerpour_external_id(item.get("url"))
    detail = fetch_live_detail(item)

    length = int(
        detail.get("matching_text_length")
        or len(detail.get("matching_text") or "")
    )
    success = bool(detail.get("success"))
    from_cache = bool(detail.get("from_cache", False))
    error = detail.get("error")

    print("=" * 88)
    print("JOB REFRESH V1.2 - TRAVAILLERPOUR LIVE AUDIT")
    print("=" * 88)
    print()
    print("Préparation :", prep_path)
    print("Titre       :", item.get("title"))
    print("URL         :", item.get("url"))
    print("External ID :", external_id)
    print("Success     :", success)
    print("From cache  :", from_cache)
    print("Description :", length)
    print("Error       :", error)

    passed = (
        external_id is not None
        and success
        and not from_cache
        and length >= 120
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "version": "1.2",
        "preparation_path": str(prep_path),
        "title": item.get("title"),
        "url": item.get("url"),
        "external_id": external_id,
        "success": success,
        "from_cache": from_cache,
        "matching_text_length": length,
        "error": error,
        "passed": passed,
    }

    json_path = LOG_DIR / (
        f"job_refresh_v12_travaillerpour_live_audit_{stamp}.json"
    )
    txt_path = LOG_DIR / (
        f"job_refresh_v12_travaillerpour_live_audit_{stamp}.txt"
    )

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "JOB REFRESH V1.2 - TRAVAILLERPOUR LIVE AUDIT",
            "=" * 88,
            f"Preparation : {prep_path}",
            f"Title       : {item.get('title')}",
            f"URL         : {item.get('url')}",
            f"External ID : {external_id}",
            f"Success     : {success}",
            f"From cache  : {from_cache}",
            f"Description : {length}",
            f"Error       : {error}",
            f"PASS        : {passed}",
        ]),
        encoding="utf-8",
    )

    print()
    print("TXT  :", txt_path)
    print("JSON :", json_path)

    if not passed:
        raise SystemExit("❌ TRAVAILLERPOUR LIVE AUDIT NON VALIDÉ.")

    print("✅ TRAVAILLERPOUR JOB REFRESH V1.2 VALIDÉ LIVE.")


if __name__ == "__main__":
    main()
