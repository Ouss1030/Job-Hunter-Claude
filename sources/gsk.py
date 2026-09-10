"""
JOB HUNTER BELGIUM
GSK BELGIUM - VERSION 1.1

Direct-employer collector using GSK's public Workday careers endpoints.
Targets Belgium roles close to the user's QC/Lab and Junior Data/BI profiles.

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
CACHE_DIR = PROJECT_ROOT / "logs" / "gsk_workday_cache"

CLIENT = WorkdayClient(
    host="https://gsk.wd5.myworkdayjobs.com",
    tenant="gsk",
    site="GSKCareers",
    public_locale="en-US",
    cache_dir=CACHE_DIR,
)

MAX_PAGES = 30
PAGE_SIZE = 20
DETAIL_DELAY_SECONDS = 0.08

BELGIUM_TERMS = (
    "belgium",
    "belgique",
    "wavre",
    "rixensart",
    "brussels",
    "bruxelles",
    "walloon brabant",
    "brabant wallon",
)

TARGET_TITLE_PATTERNS = (
    '\\bqc\\b',
    '\\bquality\\s+control\\b',
    '\\bquality\\s+(?:analyst|technician|specialist|associate|coordinator|officer)\\b',
    '\\bqa\\s+(?:technician|specialist|associate|coordinator|officer)\\b',
    '\\blab(?:oratory)?\\s+(?:technician|analyst|associate)\\b',
    '\\btechnicien(?:ne)?\\s+(?:de\\s+)?laboratoire\\b',
    '\\btechnicien(?:ne)?\\s+(?:qa|qc|qualit[eé])\\b',
    '\\blaborantin\\b',
    '\\banalytical\\s+(?:technician|analyst)\\b',
    '\\bmicrobiology\\s+(?:technician|analyst)\\b',
    '\\bchemist\\s+(?:technician|analyst)\\b',
    '\\blab(?:oratory)?\\s+(?:operations?|equipment|systems?|support)\\b',
    '\\b(?:lab|laboratory)\\s+(?:specialist|coordinator|operator|scientist)\\b',
    '\\bqc\\s+(?:operations?|testing|specialist|coordinator|operator)\\b',
    '\\bquality\\s+(?:operations?|testing)\\b',
    '\\b(?:sample|stability)\\s+(?:management|coordinator|technician|analyst)\\b',
    '\\benvironmental\\s+monitoring\\b',
    '\\bmedia\\s+(?:preparation|prep)\\b',
    '\\bprep\\s+mil\\b',
    '\\btesting\\s+operations?\\b',
    '\\banalytical\\s+scientist\\b',
    '\\bmicrobiology\\s+scientist\\b',
    '\\bjunior\\s+data\\s+analyst\\b',
    '\\bdata\\s+analyst\\b',
    '\\bbusiness\\s+data\\s+analyst\\b',
    '\\bbusiness\\s+analyst\\b',
    '\\bdata\\s+quality\\b',
    '\\bdata\\s+integrity\\b',
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

# These are normally too senior or outside the profile. Matcher still handles borderline roles,
# but blocking them before detail saves network requests and noise.
NON_TARGET_TITLE_PATTERNS = (
    r"\b(?:director|head|vice president|vp)\b",
    r"\b(?:senior|sr\.?|lead|principal)\b",
    r"\bmanager\b",
    r"\bintern(?:ship)?\b",
    r"\bstage\b",
    r"\bgraduate\s+programme\b",
    r"\bregister\s+your\s+interest\b",
    r"\bapprentice(?:ship)?\b",
    r"\btrainee\b",
)

SEARCH_TERMS = (
    'QC',
    'quality control',
    'laboratory technician',
    'lab technician',
    'laboratory analyst',
    'data analyst',
    'Power BI',
    'business data analyst',
    'contrôle qualité',
    'assurance qualité',
    'technicien de laboratoire',
    'analyste de laboratoire',
    'laborantin',
    'technicien qualité',
    'analyste qualité',
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


def _merge_rows(target: dict[str, dict], rows: list[dict], source_label: str, trust_belgium: bool = False) -> tuple[int, int]:
    added = 0
    target_added = 0
    for row in rows:
        candidate = _row_to_candidate(row)
        path = clean_text(candidate.get("external_path"))
        key = path or clean_text(candidate.get("external_id"))
        if not key:
            continue
        location = clean_text(candidate.get("location"))
        # Workday occasionally omits list location. Keep targeted titles for the detail stage;
        # otherwise require a Belgian signal here.
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
            f"GSK - {label:<18} page {page:2d}: {len(rows):2d} offre(s) "
            f"| total annoncé {total or '?'} | {'CACHE' if from_cache else 'WEB'}"
        )
        if not rows:
            break
        rows_all.extend(rows)
        offset += len(rows)
        if len(rows) < PAGE_SIZE or (total and offset >= total):
            break
    return rows_all, errors


def collect_gsk_listing_candidates() -> tuple[list[dict], dict]:
    print("GSK - collecte directe Belgique via Workday public")
    found: dict[str, dict] = {}
    errors: list[str] = []
    strategy = []

    # 1) Discover a Belgium/location facet dynamically from Workday.
    seed, _, seed_error = CLIENT.search(search_text="Belgium", offset=0, limit=PAGE_SIZE, use_cache=False)
    if seed:
        facet_matches = discover_facet_values(seed, BELGIUM_TERMS)
        # Pick the facet returning the largest group of matching location ids.
        if facet_matches:
            facet_parameter, ids = max(facet_matches.items(), key=lambda item: len(item[1]))
            rows, errs = _paginate(
                search_text="",
                applied_facets={facet_parameter: ids},
                label="BELGIUM FACET",
            )
            _merge_rows(found, rows, "BELGIUM FACET", trust_belgium=True)
            errors.extend(errs)
            strategy.append(f"facet:{facet_parameter}")
        else:
            # Even without a facet, the seed query itself can expose Belgian rows.
            _merge_rows(found, posting_rows(seed), "BELGIUM SEARCH")
            strategy.append("search:Belgium")
    elif seed_error:
        errors.append(f"seed Belgium: {seed_error}")

    # 2) Location queries are a fallback if the facet does not expose all Belgian sites.
    for location_query in ("Wavre", "Rixensart"):
        payload, _, error = CLIENT.search(search_text=location_query, offset=0, limit=PAGE_SIZE, use_cache=False)
        if payload:
            _merge_rows(found, posting_rows(payload), location_query)
            strategy.append(f"search:{location_query}")
        elif error:
            errors.append(f"{location_query}: {error}")

    # 3) Targeted role searches guarantee coverage if Workday does not index location text.
    for term in SEARCH_TERMS:
        payload, _, error = CLIENT.search(search_text=term, offset=0, limit=PAGE_SIZE, use_cache=False)
        if not payload:
            if error:
                errors.append(f"{term}: {error}")
            continue
        rows = posting_rows(payload)
        before = len(found)
        _merge_rows(found, rows, term)
        after = len(found)
        print(f"GSK - mot-clé {term:<24}: {len(rows):2d} résultat(s) | +{after-before} Belgique")

    all_belgium = list(found.values())
    candidates = [row for row in all_belgium if _is_target_title(row.get("title", ""))]
    candidates.sort(key=lambda row: (_normalize(row.get("title")), clean_text(row.get("external_id"))))
    return candidates, {
        "belgium_rows": len(all_belgium),
        "candidates": len(candidates),
        "errors": errors,
        "strategy": strategy,
        # Used only by diagnostics when there is no current target role. Keeping the raw
        # Belgian listing candidates lets the verifier probe one public detail endpoint
        # and distinguish "0 compatible jobs today" from a broken Workday connector.
        "all_belgium_rows": all_belgium,
    }


def get_gsk_job_detail(
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
    if not path:
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": fallback,
            "from_cache": False,
            "error": "GSK : externalPath Workday introuvable.",
        }

    payload, from_cache, error = CLIENT.detail(path, use_cache=use_cache)
    if not payload:
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": fallback,
            "from_cache": from_cache,
            "error": f"GSK Workday : {error or 'lecture détail impossible'}",
        }

    detail = parse_workday_detail(payload, fallback=fallback)
    structured = detail.setdefault("structured", {})
    structured["external_path"] = clean_text(structured.get("external_path") or path)
    structured["url"] = CLIENT.public_url(structured["external_path"])
    structured["company"] = "GSK"
    text = clean_text(detail.get("matching_text"))
    structured["language"] = detect_language(text)
    structured["dutch_required"] = dutch_professional_required(text)
    detail["from_cache"] = from_cache
    return detail


def _job_from_detail(detail: dict, fallback: dict) -> JobOffer:
    structured = detail.get("structured") or {}
    description = clean_text(detail.get("matching_text"))
    job = JobOffer(
        source="GSK",
        external_id=clean_text(structured.get("external_id") or fallback.get("external_id")),
        title=clean_text(structured.get("title") or fallback.get("title") or "Titre inconnu"),
        company="GSK",
        location=clean_text(structured.get("location") or fallback.get("location") or "Belgium"),
        description=description,
        url=clean_text(structured.get("url") or fallback.get("url")),
        date_published=clean_text(structured.get("date_published") or fallback.get("date_published")) or None,
        contract_type=clean_text(structured.get("contract_type")) or None,
        language=clean_text(structured.get("language")) or None,
    )
    job.collection_channel = "GSK"
    job.origin_source = "GSK"
    job.detail_enrichment_attempted = True
    job.detail_enrichment_success = True
    job.detail_matching_text = description
    job.detail_matching_text_length = len(description)
    job.workday_external_path = clean_text(structured.get("external_path") or fallback.get("external_path"))
    job.gsk_requisition_id = clean_text(structured.get("job_requisition_id") or structured.get("external_id"))
    return job


def collect_gsk_jobs() -> list[JobOffer]:
    _reset_geo_runtime_counters()
    candidates, meta = collect_gsk_listing_candidates()
    print(
        "GSK - préfiltre : "
        f"{meta.get('belgium_rows', 0)} offre(s) Belgique détectée(s), "
        f"{len(candidates)} candidate(s) métier"
    )
    for error in meta.get("errors") or []:
        print(f"GSK - avertissement : {error}")

    jobs: list[JobOffer] = []
    rejected_nl = 0
    rejected_dutch = 0
    errors = 0
    detail_ok = 0
    languages = {"fr": 0, "en": 0, "unknown": 0}

    for index, item in enumerate(candidates, start=1):
        detail = get_gsk_job_detail(
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
            # Target keyword searches can return global roles; reject after authoritative detail.
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
    print("                       BILAN GSK V1.1")
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
    publish_metrics_from_locals("GSK", locals())
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
