"""
JOB HUNTER BELGIUM
JOHNSON & JOHNSON / JANSSEN BELGIUM - VERSION 1.0

Direct-employer collector using Johnson & Johnson's public Workday careers endpoints.
Targets Belgian roles close to the user's QC/Lab/Chemistry and Junior Data/BI profiles.

No authentication bypass or anti-bot circumvention is used.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from database.models import JobOffer
from sources.randstad import dutch_professional_required
from sources.scienceatwork import detect_language
from sources.workday import (
    WorkdayClient,
    clean_text,
    discover_facet_values,
    parse_workday_detail,
    posting_date,
    posting_external_path,
    posting_id,
    posting_location,
    posting_rows,
    posting_title,
    posting_total,
)
from sources.belgium_locations import classify_belgium_location
from sources.source_metrics import publish_metrics_from_locals


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "logs" / "jnj_workday_cache"

CLIENT = WorkdayClient(
    host="https://jj.wd5.myworkdayjobs.com",
    tenant="jj",
    site="JJ",
    public_locale="en-US",
    cache_dir=CACHE_DIR,
)

MAX_PAGES = 20
PAGE_SIZE = 20
DETAIL_DELAY_SECONDS = 0.08

BELGIUM_TERMS = (
    "belgium",
    "belgique",
    "beerse",
    "geel",
    "gent",
    "ghent",
    "diegem",
    "courcelles",
    "olen",
    "brussels",
    "bruxelles",
    "antwerp",
    "anvers",
)

TARGET_TITLE_PATTERNS = (
    '\\bqc\\b.*\\b(?:analyst|technician|associate|specialist|coordinator|officer|investigation)\\b',
    '\\bquality\\s+control\\b.*\\b(?:analyst|technician|associate|specialist|coordinator|officer)\\b',
    '\\bqa\\b.*\\b(?:analyst|technician|associate|specialist|coordinator|officer|release)\\b',
    '\\bquality\\s+assurance\\b.*\\b(?:analyst|technician|associate|specialist|coordinator|officer)\\b',
    '\\b(?:analyst|technician|associate|specialist|coordinator|officer)\\s+quality\\s+assurance\\b',
    '\\bquality\\s+(?:analyst|technician|associate|specialist|coordinator|officer)\\b',
    '\\blab(?:oratory)?\\s+(?:technician|analyst|associate|specialist|coordinator)\\b',
    '\\btechnicien(?:ne)?\\s+(?:de\\s+)?laboratoire\\b',
    '\\btechnicien(?:ne)?\\s+(?:qa|qc|qualit[eé])\\b',
    '\\blaborantin(?:e)?\\b',
    '\\banalytical\\s+(?:technician|analyst|scientist|associate)\\b',
    '\\bmicro(?:biology)?\\s+(?:technician|analyst|scientist|associate)\\b',
    '\\bmicrobiology\\s+(?:technician|analyst|scientist|associate)\\b',
    '\\bchemist\\s+(?:technician|analyst|associate)\\b',
    '\\bchemical\\s+(?:operator|technician|analyst)\\b',
    '\\bproduction\\s+technician\\b',
    '\\bmanufacturing\\s+technician\\b',
    '\\bprocess\\s+technician\\b',
    '\\benvironmental\\s+monitoring\\b',
    '\\bdata\\s+integrity\\b',
    '\\b(?:sample|stability)\\s+(?:management|coordinator|technician|analyst)\\b',
    '\\bjunior\\s+data\\s+analyst\\b',
    '\\bdata\\s+analyst\\b',
    '\\bbusiness\\s+data\\s+analyst\\b',
    '\\bbusiness\\s+analyst\\b',
    '\\bdata\\s+quality\\b',
    '\\bdata\\s+steward\\b',
    '\\bdata\\s+officer\\b',
    '\\bmaster\\s+data\\b',
    '\\breporting\\s+analyst\\b',
    '\\bpower\\s*bi\\b',
    '\\bbi\\s+(?:analyst|developer)\\b',
    '\\bbusiness\\s+intelligence\\b',
    '\\bcontr[oô]le\\s+qualit[eé]\\b',
    '\\bassurance\\s+qualit[eé]\\b',
    '\\banalyste\\s+(?:de\\s+)?laboratoire\\b',
    '\\banalyste\\s+(?:qc|qualit[eé])\\b',
    '\\btechnicien(?:ne)?\\s+chimiste\\b',
    '\\banalyste\\s+(?:de\\s+)?donn[eé]es\\b',
    '\\banalyste\\s+fonctionnel(?:le)?\\b',
    '\\banalyste\\s+bi\\b',
    '\\bd[eé]veloppeur\\s+power\\s*bi\\b',
)

NON_TARGET_TITLE_PATTERNS = (
    r"\b(?:director|head|vice president|vp)\b",
    r"\b(?:senior|sr\.?|lead|principal)\b",
    r"\b(?:manager|mgr)\b",
    r"\bsupervisor\b",
    r"\bteam\s+leader\b",
    r"\bintern(?:ship)?\b",
    r"\bstage\b",
    r"\bstagiair\b",
    r"\bbachelorstage\b",
    r"\bmasterproef\b",
    r"\bthesis\b",
    r"\bgraduate\b",
    r"\bapprentice(?:ship)?\b",
    r"\btrainee\b",
    r"\bstudent\b",
)

SEARCH_TERMS = (
    'QC',
    'quality assurance',
    'laboratory',
    'chemical operator',
    'microbiology',
    'data analyst',
    'business analyst',
    'master data',
    'Power BI',
    'contrôle qualité',
    'assurance qualité',
    'technicien de laboratoire',
    'analyste de laboratoire',
    'laborantin',
    'technicien qualité',
    'analyste qualité',
    'technicien chimiste',
    'analyste de données',
    'analyste fonctionnel',
    'développeur Power BI',
)


def _normalize(value) -> str:
    return clean_text(value).lower().replace("’", "'")


_GEO_RUNTIME_COUNTS = {
    "BELGIUM": 0,
    "FOREIGN": 0,
    "UNKNOWN": 0,
}


def _geo_status_key(decision):
    status = getattr(decision, "status", "UNKNOWN")
    status = getattr(status, "value", status)
    key = str(status or "UNKNOWN").upper()
    if "." in key:
        key = key.rsplit(".", 1)[-1]
    if key not in _GEO_RUNTIME_COUNTS:
        key = "UNKNOWN"
    return key


def _reset_geo_runtime_counters():
    for key in _GEO_RUNTIME_COUNTS:
        _GEO_RUNTIME_COUNTS[key] = 0


def _geo_runtime_counters():
    return dict(_GEO_RUNTIME_COUNTS)


def _is_belgium_location(location):
    decision = classify_belgium_location(location)
    key = _geo_status_key(decision)
    _GEO_RUNTIME_COUNTS[key] += 1
    return key == "BELGIUM"



def _is_target_title(title: str) -> bool:
    low = _normalize(title)
    if not low:
        return False
    if any(re.search(pattern, low, flags=re.I) for pattern in NON_TARGET_TITLE_PATTERNS):
        return False
    return any(re.search(pattern, low, flags=re.I) for pattern in TARGET_TITLE_PATTERNS)


def _row_to_candidate(row: dict) -> dict:
    path = posting_external_path(row)
    return {
        "external_id": posting_id(row),
        "external_path": path,
        "title": posting_title(row),
        "location": posting_location(row),
        "date_published": posting_date(row),
        "url": CLIENT.public_url(path) if path else "",
    }


def _merge_rows(target: dict[str, dict], rows: list[dict], trust_belgium: bool = False) -> tuple[int, int]:
    added = 0
    target_added = 0
    for row in rows:
        candidate = _row_to_candidate(row)
        path = clean_text(candidate.get("external_path"))
        key = path or clean_text(candidate.get("external_id"))
        if not key:
            continue
        location = clean_text(candidate.get("location"))
        if not trust_belgium and location and not _is_belgium_location(location):
            continue
        if key not in target:
            target[key] = candidate
            added += 1
            if _is_target_title(candidate.get("title", "")):
                target_added += 1
        else:
            existing = target[key]
            for field in ("external_id", "external_path", "title", "location", "date_published", "url"):
                if not clean_text(existing.get(field)) and clean_text(candidate.get(field)):
                    existing[field] = candidate[field]
    return added, target_added


def _paginate(search_text: str = "", applied_facets: dict | None = None, label: str = "SEARCH"):
    rows_all = []
    errors = []
    offset = 0
    total = None
    page = 0
    while page < MAX_PAGES:
        payload, from_cache, error = CLIENT.search(
            search_text=search_text,
            applied_facets=applied_facets,
            offset=offset,
            limit=PAGE_SIZE,
            use_cache=False,
        )
        if not payload:
            errors.append(error or "réponse vide")
            break
        rows = posting_rows(payload)
        if total is None:
            total = posting_total(payload)
        page += 1
        print(
            f"J&J - {label:<18} page {page:2d}: {len(rows):2d} offre(s) "
            f"| total annoncé {total or '?'} | {'CACHE' if from_cache else 'WEB'}"
        )
        if not rows:
            break
        rows_all.extend(rows)
        offset += len(rows)
        if len(rows) < PAGE_SIZE or (total and offset >= total):
            break
    return rows_all, errors


def collect_jnj_listing_candidates() -> tuple[list[dict], dict]:
    print("J&J - collecte directe Belgique via Workday public")
    found: dict[str, dict] = {}
    errors: list[str] = []
    strategy = []

    # 1) Discover the Belgium facet dynamically from the public Workday payload.
    seed, _, seed_error = CLIENT.search(search_text="Belgium", offset=0, limit=PAGE_SIZE, use_cache=False)
    if seed:
        facet_matches = discover_facet_values(seed, BELGIUM_TERMS)
        if facet_matches:
            facet_parameter, ids = max(facet_matches.items(), key=lambda item: len(item[1]))
            rows, errs = _paginate(
                search_text="",
                applied_facets={facet_parameter: ids},
                label="BELGIUM FACET",
            )
            _merge_rows(found, rows, trust_belgium=True)
            errors.extend(errs)
            strategy.append(f"facet:{facet_parameter}")
        else:
            _merge_rows(found, posting_rows(seed))
            strategy.append("search:Belgium")
    elif seed_error:
        errors.append(f"seed Belgium: {seed_error}")

    # 2) Belgian site fallbacks.
    for location_query in ("Beerse", "Geel", "Gent", "Diegem"):
        payload, _, error = CLIENT.search(search_text=location_query, offset=0, limit=PAGE_SIZE, use_cache=False)
        if payload:
            _merge_rows(found, posting_rows(payload))
            strategy.append(f"search:{location_query}")
        elif error:
            errors.append(f"{location_query}: {error}")

    # 3) Targeted role searches catch rows when location text is omitted in cards.
    for term in SEARCH_TERMS:
        payload, _, error = CLIENT.search(search_text=term, offset=0, limit=PAGE_SIZE, use_cache=False)
        if not payload:
            if error:
                errors.append(f"{term}: {error}")
            continue
        rows = posting_rows(payload)
        before = len(found)
        _merge_rows(found, rows)
        after = len(found)
        print(f"J&J - mot-clé {term:<22}: {len(rows):2d} résultat(s) | +{after-before} Belgique")

    all_belgium = list(found.values())
    candidates = [row for row in all_belgium if _is_target_title(row.get("title", ""))]
    candidates.sort(key=lambda row: (_normalize(row.get("title")), clean_text(row.get("external_id"))))
    return candidates, {
        "belgium_rows": len(all_belgium),
        "candidates": len(candidates),
        "errors": errors,
        "strategy": strategy,
        "all_belgium_rows": all_belgium,
    }


def get_jnj_job_detail(
    url: str = "",
    external_id: str | None = None,
    external_path: str | None = None,
    use_cache: bool = True,
    fallback: dict | None = None,
) -> dict:
    fallback = dict(fallback or {})
    if external_id:
        fallback.setdefault("external_id", external_id)
    path = clean_text(external_path or fallback.get("external_path"))
    if not path and url:
        marker = f"/{CLIENT.site}"
        if marker in url:
            path = url.split(marker, 1)[1]
    if not path and external_id:
        # J&J's public CXS detail endpoint also accepts /job/R-xxxx requisitions.
        path = f"/job/{clean_text(external_id)}"
    if not path:
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": fallback,
            "from_cache": False,
            "error": "J&J : externalPath Workday introuvable.",
        }

    payload, from_cache, error = CLIENT.detail(path, use_cache=use_cache)
    if not payload:
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": fallback,
            "from_cache": from_cache,
            "error": f"J&J Workday : {error or 'lecture détail impossible'}",
        }

    detail = parse_workday_detail(payload, fallback=fallback)
    structured = detail.setdefault("structured", {})
    structured["external_path"] = clean_text(structured.get("external_path") or path)
    structured["url"] = CLIENT.public_url(structured["external_path"])
    structured["company"] = "Johnson & Johnson / Janssen"
    text = clean_text(detail.get("matching_text"))
    structured["language"] = detect_language(text)
    structured["dutch_required"] = dutch_professional_required(text)
    detail["from_cache"] = from_cache
    return detail


def _job_from_detail(detail: dict, fallback: dict) -> JobOffer:
    structured = detail.get("structured") or {}
    description = clean_text(detail.get("matching_text"))
    job = JobOffer(
        source="JNJ",
        external_id=clean_text(structured.get("external_id") or fallback.get("external_id")),
        title=clean_text(structured.get("title") or fallback.get("title") or "Titre inconnu"),
        company="Johnson & Johnson / Janssen",
        location=clean_text(structured.get("location") or fallback.get("location") or "Belgium"),
        description=description,
        url=clean_text(structured.get("url") or fallback.get("url")),
        date_published=clean_text(structured.get("date_published") or fallback.get("date_published")) or None,
        contract_type=clean_text(structured.get("contract_type")) or None,
        language=clean_text(structured.get("language")) or None,
    )
    job.collection_channel = "JNJ"
    job.origin_source = "JNJ"
    job.detail_enrichment_attempted = True
    job.detail_enrichment_success = True
    job.detail_matching_text = description
    job.detail_matching_text_length = len(description)
    job.workday_external_path = clean_text(structured.get("external_path") or fallback.get("external_path"))
    job.jnj_requisition_id = clean_text(structured.get("job_requisition_id") or structured.get("external_id"))
    return job


def collect_jnj_jobs() -> list[JobOffer]:
    _reset_geo_runtime_counters()
    candidates, meta = collect_jnj_listing_candidates()
    print(
        "J&J - préfiltre : "
        f"{meta.get('belgium_rows', 0)} offre(s) Belgique détectée(s), "
        f"{len(candidates)} candidate(s) métier"
    )
    for error in meta.get("errors") or []:
        print(f"J&J - avertissement : {error}")

    jobs: list[JobOffer] = []
    rejected_nl = 0
    rejected_dutch = 0
    errors = 0
    detail_ok = 0
    languages = {"fr": 0, "en": 0, "unknown": 0}

    for index, item in enumerate(candidates, start=1):
        detail = get_jnj_job_detail(
            url=item.get("url", ""),
            external_id=item.get("external_id"),
            external_path=item.get("external_path"),
            use_cache=True,
            fallback=item,
        )
        title = clean_text((detail.get("structured") or {}).get("title") or item.get("title"))
        if not detail.get("success"):
            errors += 1
            print(f"[{index:03d}/{len(candidates):03d}] ⚠️ DETAIL | {title} | {detail.get('error')}")
            continue
        detail_ok += 1
        structured = detail.get("structured") or {}
        location = clean_text(structured.get("location") or item.get("location"))
        if location and not _is_belgium_location(location):
            continue
        language = clean_text(structured.get("language")).lower() or "unknown"
        if language == "nl":
            rejected_nl += 1
            print(f"[{index:03d}/{len(candidates):03d}] ⛔ NL     | {title}")
            continue
        if structured.get("dutch_required"):
            rejected_dutch += 1
            print(f"[{index:03d}/{len(candidates):03d}] ⛔ DUTCH  | {title} | néerlandais professionnel requis")
            continue
        languages[language if language in languages else "unknown"] += 1
        job = _job_from_detail(detail, item)
        jobs.append(job)
        print(
            f"[{index:03d}/{len(candidates):03d}] ✅ {language.upper():<7} | "
            f"{len(job.description):4d} car. | {job.title} | {job.location}"
        )
        time.sleep(DETAIL_DELAY_SECONDS)

    print()
    print("=" * 76)
    print("                       BILAN J&J V1.0")
    print("=" * 76)
    print(f"Offres Belgique détectées           : {meta.get('belgium_rows', 0)}")
    print(f"Candidates métier préfiltrées       : {len(candidates)}")
    print(f"Conservées FR/EN/ambiguës           : {len(jobs)}")
    print(f"  Français                          : {languages['fr']}")
    print(f"  Anglais                           : {languages['en']}")
    print(f"  Langue ambiguë                    : {languages['unknown']}")
    print(f"Rejetées - fiche clairement NL      : {rejected_nl}")
    print(f"Rejetées - néerlandais requis       : {rejected_dutch}")
    _geo = _geo_runtime_counters()
    print("Rejetées - géographie étrangère      :", _geo["FOREIGN"])
    print("Géographie inconnue hors facet (non retenue) :", _geo["UNKNOWN"])
    print(f"Échecs détail                       : {errors}")
    publish_metrics_from_locals("JNJ", locals())
    return jobs


# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1
from sources.unified_discovery import matches_master_title

_ud_original__is_target_title = _is_target_title

def _is_target_title(*args, **kwargs):
    if _ud_original__is_target_title(*args, **kwargs):
        return True
    try:
        title = args[0] if args else kwargs.get('title', '')
    except Exception:
        return False
    return matches_master_title(title)
