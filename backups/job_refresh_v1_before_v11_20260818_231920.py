"""
JOB HUNTER BELGIUM
JOB REFRESH - VERSION 1.0

Objectif
========
Prendre le dernier application_preparation_v1_*.json, relire LIVE les offres
FOREM / ACTIRIS avec les enrichisseurs déjà validés du projet, puis produire
un payload prêt pour la génération de documents.

Cette couche :
- ne modifie ni Matcher, ni Gate, ni Queue, ni Canonical, ni RAW ;
- force use_cache=False pour vérifier la source actuelle ;
- sauvegarde un snapshot TXT de l'offre dans le dossier de candidature ;
- ne passe READY_FOR_DOCUMENTS que si :
  * le CV de base existe,
  * la lecture live réussit,
  * une description exploitable est récupérée.

Usage
=====
    python -m applications.job_refresh

Optionnel :
    python -m applications.job_refresh --input exports/logs/application_preparation_v1_....json
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from sources.forem_detail import get_forem_job_detail
from sources.actiris_detail import get_actiris_job_detail

REFRESH_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
APPLICATION_DIR = PROJECT_ROOT / "exports" / "applications"

MIN_DESCRIPTION_LENGTH = 120


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


def parse_forem_external_id(url):
    match = re.search(r"/offre-detail/(\d+)", clean_text(url))
    return match.group(1) if match else None


def parse_actiris_reference_and_type(url):
    parsed = urlparse(clean_text(url))
    qs = parse_qs(parsed.query)
    reference = (qs.get("reference") or [None])[0]
    offer_type = (qs.get("type") or [None])[0]
    return reference, offer_type


def fetch_live_detail(item):
    source = clean_text(item.get("source")).upper()
    url = clean_text(item.get("url"))

    if source == "FOREM":
        external_id = parse_forem_external_id(url)
        if not external_id:
            return {
                "success": False,
                "from_cache": False,
                "matching_text": "",
                "matching_text_length": 0,
                "structured": {},
                "error": "Impossible d'extraire l'external_id FOREM de l'URL.",
            }
        return get_forem_job_detail(external_id, use_cache=False)

    if source == "ACTIRIS":
        reference, offer_type = parse_actiris_reference_and_type(url)
        if not reference:
            return {
                "success": False,
                "from_cache": False,
                "matching_text": "",
                "matching_text_length": 0,
                "structured": {},
                "error": "Impossible d'extraire la référence ACTIRIS de l'URL.",
            }
        return get_actiris_job_detail(
            reference=reference,
            offer_type=offer_type,
            use_cache=False,
        )

    return {
        "success": False,
        "from_cache": False,
        "matching_text": "",
        "matching_text_length": 0,
        "structured": {},
        "error": f"Source non prise en charge par Job Refresh V1 : {source}",
    }


def assess_detail(item, detail):
    success = bool(detail.get("success"))
    from_cache = bool(detail.get("from_cache", False))
    text = clean_text(detail.get("matching_text"))
    length = len(text)

    if not success:
        return {
            "job_live_status": "SOURCE_FETCH_FAILED",
            "job_description_status": "UNAVAILABLE",
            "document_generation_status": "WAITING_SOURCE_REVIEW",
            "safe_to_generate_documents": False,
            "reason": clean_text(detail.get("error")) or "Lecture live échouée.",
        }

    if from_cache:
        return {
            "job_live_status": "CACHE_ONLY",
            "job_description_status": "STALE_OR_UNCONFIRMED",
            "document_generation_status": "WAITING_SOURCE_REVIEW",
            "safe_to_generate_documents": False,
            "reason": "La source a répondu via cache malgré la demande de lecture live.",
        }

    if length < MIN_DESCRIPTION_LENGTH:
        return {
            "job_live_status": "LIVE_FETCH_OK",
            "job_description_status": "TOO_SHORT",
            "document_generation_status": "WAITING_SOURCE_REVIEW",
            "safe_to_generate_documents": False,
            "reason": f"Description live trop courte ({length} caractères).",
        }

    if not item.get("base_cv_found"):
        return {
            "job_live_status": "LIVE_FETCH_OK",
            "job_description_status": "LIVE_COMPLETE",
            "document_generation_status": "WAITING_BASE_CV",
            "safe_to_generate_documents": False,
            "reason": "Description live disponible mais CV de base introuvable.",
        }

    return {
        "job_live_status": "LIVE_CONFIRMED",
        "job_description_status": "LIVE_COMPLETE",
        "document_generation_status": "READY_FOR_DOCUMENTS",
        "safe_to_generate_documents": True,
        "reason": "Lecture live réussie, description exploitable et CV de base disponible.",
    }


def snapshot_text(item, detail, assessment):
    structured = detail.get("structured") or {}
    description = detail.get("matching_text") or ""

    lines = [
        "JOB REFRESH V1 - SNAPSHOT OFFRE",
        "=" * 78,
        f"Date refresh      : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
        f"Stable item key   : {item.get('stable_item_key')}",
        f"Poste             : {item.get('title')}",
        f"Entreprise        : {item.get('company')}",
        f"Lieu              : {item.get('location')}",
        f"Source            : {item.get('source')}",
        f"URL               : {item.get('url')}",
        f"Live status       : {assessment['job_live_status']}",
        f"Description status: {assessment['job_description_status']}",
        f"Documents         : {assessment['document_generation_status']}",
        f"Raison            : {assessment['reason']}",
        "",
        "DONNÉES STRUCTURÉES",
        "-" * 78,
        json.dumps(structured, ensure_ascii=False, indent=2, default=str),
        "",
        "DESCRIPTION / MATCHING TEXT",
        "-" * 78,
        str(description),
        "",
    ]
    return "\n".join(lines)


def refresh_item(item):
    refreshed = dict(item)
    detail = fetch_live_detail(item)
    assessment = assess_detail(item, detail)

    refreshed.update({
        "refresh_version": REFRESH_VERSION,
        "refreshed_at": datetime.now().isoformat(timespec="seconds"),
        **assessment,
        "live_detail": {
            "success": bool(detail.get("success")),
            "from_cache": bool(detail.get("from_cache", False)),
            "matching_text_length": int(
                detail.get("matching_text_length")
                or len(detail.get("matching_text") or "")
            ),
            "matching_text": detail.get("matching_text") or "",
            "structured": detail.get("structured") or {},
            "error": detail.get("error"),
        },
    })

    app_folder = PROJECT_ROOT / Path(item["application_folder"])
    app_folder.mkdir(parents=True, exist_ok=True)

    snapshot_name = (item.get("output_files") or {}).get(
        "job_snapshot_txt",
        f"{item.get('stable_item_key','offre')}_Offre.txt",
    )
    snapshot_path = app_folder / snapshot_name
    snapshot_path.write_text(
        snapshot_text(item, detail, assessment),
        encoding="utf-8",
    )
    refreshed["job_snapshot_path"] = str(snapshot_path)

    return refreshed


def refresh_batch(items):
    results = []
    total = len(items)

    print("\n" + "=" * 78)
    print("JOB REFRESH V1 - LECTURE LIVE")
    print("=" * 78)

    for index, item in enumerate(items, start=1):
        title = clean_text(item.get("title"))
        print(f"[{index}/{total}] {title[:70]}")

        try:
            refreshed = refresh_item(item)
        except Exception as exc:
            refreshed = dict(item)
            refreshed.update({
                "refresh_version": REFRESH_VERSION,
                "refreshed_at": datetime.now().isoformat(timespec="seconds"),
                "job_live_status": "REFRESH_EXCEPTION",
                "job_description_status": "UNAVAILABLE",
                "document_generation_status": "WAITING_SOURCE_REVIEW",
                "safe_to_generate_documents": False,
                "refresh_exception": f"{type(exc).__name__}: {exc}",
                "live_detail": {
                    "success": False,
                    "from_cache": False,
                    "matching_text_length": 0,
                    "matching_text": "",
                    "structured": {},
                    "error": f"{type(exc).__name__}: {exc}",
                },
            })

        results.append(refreshed)

        print(
            f"    {refreshed.get('job_live_status')} | "
            f"{refreshed.get('document_generation_status')}"
        )

    return results


def summary(items):
    return {
        "total": len(items),
        "live_confirmed": sum(1 for x in items if x.get("job_live_status") == "LIVE_CONFIRMED"),
        "ready_for_documents": sum(
            1 for x in items if x.get("document_generation_status") == "READY_FOR_DOCUMENTS"
        ),
        "waiting_source_review": sum(
            1 for x in items if x.get("document_generation_status") == "WAITING_SOURCE_REVIEW"
        ),
        "waiting_base_cv": sum(
            1 for x in items if x.get("document_generation_status") == "WAITING_BASE_CV"
        ),
        "fetch_failed": sum(
            1 for x in items
            if x.get("job_live_status") in {"SOURCE_FETCH_FAILED", "REFRESH_EXCEPTION"}
        ),
        "cache_only": sum(1 for x in items if x.get("job_live_status") == "CACHE_ONLY"),
        "too_short": sum(1 for x in items if x.get("job_description_status") == "TOO_SHORT"),
    }


def export_results(items):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = LOG_DIR / f"job_refresh_v1_{stamp}.json"
    txt_path = LOG_DIR / f"job_refresh_v1_{stamp}.txt"

    json_path.write_text(
        json.dumps(items, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    s = summary(items)
    lines = [
        "JOB REFRESH V1",
        "=" * 78,
        f"Total                 : {s['total']}",
        f"LIVE_CONFIRMED        : {s['live_confirmed']}",
        f"READY_FOR_DOCUMENTS   : {s['ready_for_documents']}",
        f"WAITING_SOURCE_REVIEW : {s['waiting_source_review']}",
        f"WAITING_BASE_CV       : {s['waiting_base_cv']}",
        f"FETCH_FAILED          : {s['fetch_failed']}",
        f"CACHE_ONLY            : {s['cache_only']}",
        f"DESCRIPTION_TOO_SHORT : {s['too_short']}",
        "",
    ]

    for index, item in enumerate(items, start=1):
        lines.extend([
            f"{index:2d}. {item.get('job_live_status')} | "
            f"{item.get('document_generation_status')}",
            f"    {item.get('title')}",
            f"    {item.get('company')} | {item.get('location')}",
            f"    Description : "
            f"{(item.get('live_detail') or {}).get('matching_text_length', 0)} caractères",
            f"    {item.get('url')}",
            "",
        ])

    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return txt_path, json_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", dest="input_path", default=None)
    args = parser.parse_args()

    input_path = Path(args.input_path) if args.input_path else latest_file(
        LOG_DIR,
        "application_preparation_v1_*.json",
    )

    if not input_path or not input_path.exists():
        raise SystemExit(
            "Aucun application_preparation_v1_*.json trouvé dans exports/logs."
        )

    items = load_json(input_path)
    if not isinstance(items, list) or not items:
        raise SystemExit("Le fichier de préparation est vide ou invalide.")

    print(f"Préparation source : {input_path}")
    print(f"Offres à rafraîchir : {len(items)}")
    print("Mode              : LIVE (use_cache=False)")

    refreshed = refresh_batch(items)
    txt_path, json_path = export_results(refreshed)

    s = summary(refreshed)
    print("\n" + "=" * 78)
    print("BILAN JOB REFRESH V1")
    print("=" * 78)
    print(f"READY_FOR_DOCUMENTS : {s['ready_for_documents']}/{s['total']}")
    print(f"À vérifier          : {s['waiting_source_review']}")
    print(f"Échecs live         : {s['fetch_failed']}")
    print(f"TXT                  : {txt_path}")
    print(f"JSON                 : {json_path}")


if __name__ == "__main__":
    main()
