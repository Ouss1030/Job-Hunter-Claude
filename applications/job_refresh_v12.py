"""
JOB HUNTER BELGIUM
JOB REFRESH - VERSION 1.2

Objectif
========
Prendre le dernier application_preparation_v1_*.json, relire LIVE les offres
FOREM / ACTIRIS / SMARTRECRUITERS / TRAVAILLERPOUR avec les connecteurs déjà validés du projet,
puis produire un payload prêt pour la génération de documents.

Ajouts
======
V1.1 :
- support natif SmartRecruiters ;
- récupération via Posting API avec use_cache=False ;
- extraction robuste companyIdentifier + postingId depuis metadata / URL ;
- conversion au même contrat live_detail que Forem / Actiris ;
- un HTTP 404 reste un échec source explicite afin que Application Recheck
  puisse le classer CLOSED_OR_REMOVED.

V1.2 :
- support natif TravaillerPour ;
- extraction du code d'offre (ex. CFG26046) depuis l'URL ;
- lecture live via sources.travaillerpour_detail avec use_cache=False ;
- aucun changement de logique pour Forem / Actiris / SmartRecruiters.

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
from urllib.parse import urlparse, parse_qs, unquote

from sources.forem_detail import get_forem_job_detail
from sources.actiris_detail import get_actiris_job_detail
from sources.smartrecruiters import get_posting_detail, posting_to_job
from sources.travaillerpour_detail import get_travaillerpour_job_detail

REFRESH_VERSION = "1.2"

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





def parse_travaillerpour_external_id(url):
    """
    Extrait le code d'une offre TravaillerPour depuis l'URL.

    Exemples :
    - CFG26046
    - AFG26147
    - XFC26104
    - CNG26031
    """
    text = clean_text(url)
    if not text:
        return None

    try:
        parsed = urlparse(text)
        path = unquote(parsed.path or "")
    except Exception:
        path = text

    match = re.search(r"(?:^|/)([A-Za-z]{3}\d{5})(?:-|/|$)", path)
    if match:
        return match.group(1).upper()

    match = re.search(r"\b([A-Za-z]{3}\d{5})\b", text)
    if match:
        return match.group(1).upper()

    return None

def parse_smartrecruiters_identity(item):
    """
    Retourne (company_identifier, posting_id).

    Priorité :
    1. métadonnées explicites si présentes ;
    2. external_id au format "CompanyIdentifier:PostingId" ;
    3. URL jobs.smartrecruiters.com ;
    4. URL API api.smartrecruiters.com/v1/companies/.../postings/...

    La fonction ne dépend pas du titre de l'offre.
    """
    item = item or {}

    source = clean_text(item.get("source")).upper()
    if source != "SMARTRECRUITERS":
        return None, None

    company_identifier = clean_text(
        item.get("source_company_identifier")
        or item.get("smartrecruiters_company_identifier")
    )
    posting_id = clean_text(
        item.get("smartrecruiters_posting_id")
        or item.get("posting_id")
    )

    external_id = clean_text(item.get("external_id"))
    if external_id and ":" in external_id:
        ext_company, ext_posting = external_id.split(":", 1)
        if not company_identifier:
            company_identifier = clean_text(ext_company)
        if not posting_id:
            posting_id = clean_text(ext_posting)

    origin = clean_text(item.get("origin_source"))
    if (
        not company_identifier
        and origin
        and origin.upper() != "SMARTRECRUITERS"
    ):
        company_identifier = origin

    url = clean_text(item.get("url"))
    if url:
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            parts = [
                unquote(part)
                for part in parsed.path.split("/")
                if clean_text(part)
            ]

            if host == "jobs.smartrecruiters.com" and len(parts) >= 2:
                if not company_identifier:
                    company_identifier = clean_text(parts[0])

                slug = clean_text(parts[1])
                if not posting_id:
                    numeric = re.match(r"^(\d+)", slug)
                    uuid = re.match(
                        r"^([0-9a-fA-F]{8}-"
                        r"[0-9a-fA-F]{4}-"
                        r"[0-9a-fA-F]{4}-"
                        r"[0-9a-fA-F]{4}-"
                        r"[0-9a-fA-F]{12})",
                        slug,
                    )
                    if numeric:
                        posting_id = numeric.group(1)
                    elif uuid:
                        posting_id = uuid.group(1)
                    elif "-" not in slug:
                        posting_id = slug

            elif host == "api.smartrecruiters.com":
                # /v1/companies/{company}/postings/{posting}
                lowered = [p.lower() for p in parts]
                if "companies" in lowered and "postings" in lowered:
                    cidx = lowered.index("companies")
                    pidx = lowered.index("postings")
                    if cidx + 1 < len(parts) and not company_identifier:
                        company_identifier = clean_text(parts[cidx + 1])
                    if pidx + 1 < len(parts) and not posting_id:
                        posting_id = clean_text(parts[pidx + 1])
        except Exception:
            pass

    return company_identifier or None, posting_id or None


def smartrecruiters_detail_to_refresh_payload(
    company_identifier,
    posting_id,
    detail,
):
    """
    Convertit le Posting API SmartRecruiters vers le contrat déjà utilisé
    par Job Refresh / Application Recheck.

    Important :
    posting_to_job() V1.1 exclut déjà companyDescription du matching_text.
    """
    job = posting_to_job(company_identifier, detail)

    matching_text = clean_text(getattr(job, "description", ""))
    sections = getattr(job, "job_sections", {}) or {}

    structured = {
        "company_identifier": company_identifier,
        "posting_id": str(posting_id),
        "title": clean_text(getattr(job, "title", "")),
        "company": clean_text(getattr(job, "company", "")),
        "location": clean_text(getattr(job, "location", "")),
        "contract_type": clean_text(getattr(job, "contract_type", "")),
        "language": clean_text(getattr(job, "language", "")),
        "department": clean_text(getattr(job, "department", "")),
        "job_function": clean_text(getattr(job, "job_function", "")),
        "experience_level": clean_text(
            getattr(job, "experience_level", "")
        ),
        "apply_url": clean_text(getattr(job, "apply_url", "")),
        "job_description": clean_text(
            sections.get("jobDescription")
        ),
        "profile": clean_text(
            sections.get("qualifications")
        ),
        "additional_information": clean_text(
            sections.get("additionalInformation")
        ),
        "company_description": clean_text(
            getattr(job, "company_description", "")
        ),
        "sections": sections,
    }

    return {
        "success": bool(matching_text),
        "from_cache": False,
        "matching_text": matching_text,
        "matching_text_length": len(matching_text),
        "structured": structured,
        "error": None if matching_text else (
            "SmartRecruiters : détail récupéré mais description exploitable vide."
        ),
    }


def _http_status_from_exception(exc):
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    try:
        return int(status) if status is not None else None
    except Exception:
        return None


def fetch_smartrecruiters_live_detail(item):
    company_identifier, posting_id = parse_smartrecruiters_identity(item)

    if not company_identifier or not posting_id:
        return {
            "success": False,
            "from_cache": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": {},
            "error": (
                "Impossible d'extraire companyIdentifier/postingId "
                "de l'offre SMARTRECRUITERS."
            ),
        }

    try:
        detail = get_posting_detail(
            company_identifier,
            posting_id,
            use_cache=False,
        )
    except Exception as exc:
        status = _http_status_from_exception(exc)

        if status == 404:
            error = (
                "SmartRecruiters HTTP 404 : offre probablement retirée/fermée "
                f"({company_identifier}:{posting_id})."
            )
        elif status:
            error = (
                f"SmartRecruiters HTTP {status} : "
                f"{type(exc).__name__}: {exc}"
            )
        else:
            error = (
                f"SmartRecruiters : {type(exc).__name__}: {exc}"
            )

        return {
            "success": False,
            "from_cache": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": {
                "company_identifier": company_identifier,
                "posting_id": str(posting_id),
            },
            "error": error,
        }

    return smartrecruiters_detail_to_refresh_payload(
        company_identifier,
        posting_id,
        detail,
    )


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

    if source == "TRAVAILLERPOUR":
        external_id = parse_travaillerpour_external_id(url)
        if not external_id:
            return {
                "success": False,
                "from_cache": False,
                "matching_text": "",
                "matching_text_length": 0,
                "structured": {},
                "error": (
                    "Impossible d'extraire le code TRAVAILLERPOUR de l'URL."
                ),
            }

        try:
            return get_travaillerpour_job_detail(
                url=url,
                external_id=external_id,
                use_cache=False,
            )
        except Exception as exc:
            return {
                "success": False,
                "from_cache": False,
                "matching_text": "",
                "matching_text_length": 0,
                "structured": {
                    "external_id": external_id,
                },
                "error": (
                    f"TravaillerPour : {type(exc).__name__}: {exc}"
                ),
            }

    if source == "SMARTRECRUITERS":
        return fetch_smartrecruiters_live_detail(item)

    return {
        "success": False,
        "from_cache": False,
        "matching_text": "",
        "matching_text_length": 0,
        "structured": {},
        "error": f"Source non prise en charge par Job Refresh V1.2 : {source}",
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
        "JOB REFRESH V1.2 - SNAPSHOT OFFRE",
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
    print("JOB REFRESH V1.2 - LECTURE LIVE")
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
        "JOB REFRESH V1.2",
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
    print("BILAN JOB REFRESH V1.2")
    print("=" * 78)
    print(f"READY_FOR_DOCUMENTS : {s['ready_for_documents']}/{s['total']}")
    print(f"À vérifier          : {s['waiting_source_review']}")
    print(f"Échecs live         : {s['fetch_failed']}")
    print(f"TXT                  : {txt_path}")
    print(f"JSON                 : {json_path}")


if __name__ == "__main__":
    main()
