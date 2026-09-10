"""
JOB HUNTER BELGIUM
IBA BELGIUM - VERSION 1.0

Direct-employer collector for IBA's public SAP SuccessFactors career site.
Targets Belgian QC/Lab and Data/BI roles close to the user's profiles.
"""
from __future__ import annotations

import html as html_lib
import re
import time
from pathlib import Path

from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.randstad import dutch_professional_required
from sources.scienceatwork import detect_language
from sources.successfactors import (
    SuccessFactorsClient,
    clean_text,
    extract_jobposting_jsonld,
    jsonld_location,
    parse_listing_rows,
    parse_total,
)
from sources.source_metrics import publish_metrics_from_locals

BASE_URL = "https://careers.iba-worldwide.com"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "logs" / "iba_successfactors_cache"
CLIENT = SuccessFactorsClient(
    base_url=BASE_URL,
    all_jobs_path="/go/All-Jobs/9047155/",
    cache_dir=CACHE_DIR,
    page_size=50,
)

PAGE_SIZE = 50
MAX_PAGES = 6
DETAIL_DELAY_SECONDS = 0.12
MIN_DESCRIPTION_LENGTH = 180

TARGET_TITLE_PATTERNS = (
    '\\bquality\\s+control\\b',
    '\\bqc\\b',
    '\\bquality\\s+(?:associate|technician|specialist|officer|coordinator)\\b',
    '\\bquality\\s+assurance\\s+(?:associate|technician|specialist|officer|coordinator)\\b',
    '\\bqa\\s+(?:associate|technician|specialist|officer|coordinator)\\b',
    '\\blab(?:oratory)?\\s+(?:technician|analyst|associate|specialist)\\b',
    '\\btechnicien(?:ne)?\\s+(?:de\\s+)?laboratoire\\b',
    '\\blaborantin(?:e)?\\b',
    '\\banalytical\\s+(?:technician|analyst|scientist)\\b',
    '\\bchemist\\b',
    '\\bmicrobiology\\b',
    '\\bjunior\\s+data\\s+analyst\\b',
    '\\bdata\\s+analyst\\b',
    '\\bbusiness\\s+(?:data\\s+)?analyst\\b',
    '\\bpower\\s*bi\\s+(?:developer|analyst)\\b',
    '\\bbi\\s+(?:developer|analyst)\\b',
    '\\breporting\\s+analyst\\b',
    '\\bdata\\s+quality\\b',
    '\\bdata\\s+integrity\\b',
    '\\bmaster\\s+data\\b',
    '\\bdata\\s+steward\\b',
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
    r"\b(?:senior|sr\.?|principal)\b",
    r"\b(?:lead|leader|manager|director|head|vp|vice president)\b",
    r"\bintern(?:ship)?\b",
    r"\bstage\b",
    r"\bstagiaire\b",
    r"\bstudent\b",
    r"\bgraduate\b",
    r"\btrainee\b",
)

CLOSED_MARKERS = (
    "job is no longer available",
    "position is no longer available",
    "job you are trying to access is no longer available",
    "job you are trying to apply for is no longer available",
    "this job has been filled",
)

PRIVATE_MARKERS = (
    "the page you are trying to access is for employees",
    "please login",
)


def _norm(value) -> str:
    return clean_text(value).lower().replace("’", "'")


def _is_belgium(row: dict) -> bool:
    location = _norm(row.get("location"))
    url = _norm(row.get("url"))
    return bool(location.endswith("be") or ", be" in location or "belgium" in location or "louvain-la-neuve" in url)


def _is_target(row: dict) -> bool:
    title = _norm(row.get("title"))
    seniority = _norm(row.get("seniority"))
    if not title:
        return False
    if "mid-senior" in seniority or "director" in seniority or "executive" in seniority:
        return False
    if any(re.search(p, title, re.I) for p in NON_TARGET_TITLE_PATTERNS):
        return False
    return any(re.search(p, title, re.I) for p in TARGET_TITLE_PATTERNS)


def collect_iba_listing_candidates(use_cache: bool = True) -> tuple[list[dict], list[dict], dict]:
    print("IBA - collecte directe Belgique via SAP SuccessFactors public")
    found: dict[str, dict] = {}
    total = None
    errors = []
    pages = 0

    for page in range(MAX_PAGES):
        offset = page * PAGE_SIZE
        html, from_cache, error = CLIENT.listing_html(offset=offset, use_cache=use_cache)
        if not html:
            errors.append(f"offset {offset}: {error or 'listing inaccessible'}")
            break
        rows = parse_listing_rows(html, BASE_URL)
        if total is None:
            total = parse_total(html)
        added = 0
        belgium_added = 0
        target_added = 0
        for row in rows:
            key = clean_text(row.get("external_id")) or clean_text(row.get("url"))
            if not key or key in found:
                continue
            found[key] = row
            added += 1
            if _is_belgium(row):
                belgium_added += 1
                if _is_target(row):
                    target_added += 1
        pages += 1
        print(
            f"IBA - page {page + 1:2d}: {len(rows):2d} offre(s) | +{added:2d} unique(s) "
            f"| +{belgium_added:2d} Belgique | +{target_added:2d} cible(s) | "
            f"{'CACHE' if from_cache else 'WEB'}"
        )
        if not rows or len(rows) < PAGE_SIZE or (total and (offset + len(rows) >= total)):
            break

    all_rows = list(found.values())
    belgium = [row for row in all_rows if _is_belgium(row)]
    candidates = [row for row in belgium if _is_target(row)]
    return belgium, candidates, {"pages": pages, "total": total, "errors": errors, "all_rows": len(all_rows)}


def _strip_noise(soup: BeautifulSoup):
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "form", "noscript"]):
        tag.decompose()
    for node in soup.find_all(class_=re.compile(r"cookie|footer|header|navbar|search", re.I)):
        try:
            node.decompose()
        except Exception:
            pass


def _description_container(soup: BeautifulSoup):
    selectors = (
        "[itemprop='description']",
        ".jobdescription",
        ".job-description",
        ".jobDescription",
        ".job",
        "#jobcontent",
        ".jobDisplayShell",
    )
    for selector in selectors:
        node = soup.select_one(selector)
        if node and len(clean_text(node.get_text(" ", strip=True))) >= MIN_DESCRIPTION_LENGTH:
            return node
    return soup.body or soup


def _meta_from_text(text: str, label: str) -> str:
    pattern = rf"{re.escape(label)}\s*:\s*(.+?)(?=\s+(?:Requisition ID|Location|Work regime|Kind of contract|Mission|Challenges we trust you with|What we value|Who you are|$))"
    m = re.search(pattern, text, re.I)
    return clean_text(m.group(1)) if m else ""


def parse_iba_detail(html: str, url: str, external_id: str | None = None, fallback: dict | None = None, from_cache: bool = False) -> dict:
    fallback = fallback or {}
    soup = BeautifulSoup(html or "", "html.parser")
    full_text = clean_text(soup.get_text(" ", strip=True))
    low = _norm(full_text)

    closed = any(marker in low for marker in CLOSED_MARKERS)
    private = any(marker in low for marker in PRIVATE_MARKERS)
    jsonld = extract_jobposting_jsonld(soup)

    title = clean_text(jsonld.get("title"))
    if not title:
        h1 = soup.find("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "")
    title = title or clean_text(fallback.get("title"))

    location = jsonld_location(jsonld) or clean_text(fallback.get("location"))
    contract = clean_text(jsonld.get("employmentType")) or _meta_from_text(full_text, "Kind of contract")
    date_published = clean_text(jsonld.get("datePosted"))

    req = _meta_from_text(full_text, "Requisition ID") or clean_text(external_id) or clean_text(fallback.get("external_id"))
    work_regime = _meta_from_text(full_text, "Work regime")
    if not location:
        location = _meta_from_text(full_text, "Location")

    _strip_noise(soup)
    container = _description_container(soup)
    description = clean_text(container.get_text(" ", strip=True))

    # If a broad container was used, prefer content starting at the mission/challenges section.
    for marker in ("Mission", "Challenges we trust you with", "What we value", "Who you are"):
        pos = description.find(marker)
        if 0 <= pos < 1500:
            description = description[pos:]
            break

    language = detect_language(description or full_text)
    dutch_required = dutch_professional_required(description or full_text)

    structured = {
        "external_id": req,
        "successfactors_job_id": req,
        "title": title,
        "company": "IBA",
        "location": location,
        "contract_type": contract,
        "date_published": date_published,
        "language": language,
        "dutch_required": dutch_required,
        "work_regime": work_regime,
        "url": url,
        "closed": closed,
        "private_page": private,
        "category": clean_text(fallback.get("category")),
        "seniority": clean_text(fallback.get("seniority")),
    }

    if closed:
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": structured,
            "from_cache": from_cache,
            "error": "IBA : offre clôturée / non disponible.",
        }
    if private:
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": structured,
            "from_cache": from_cache,
            "error": "IBA : la fiche publique a renvoyé une page réservée aux employés.",
        }
    if len(description) < MIN_DESCRIPTION_LENGTH:
        return {
            "success": False,
            "matching_text": description,
            "matching_text_length": len(description),
            "structured": structured,
            "from_cache": from_cache,
            "error": f"IBA : description trop courte ({len(description)} caractères).",
        }
    return {
        "success": True,
        "matching_text": description,
        "matching_text_length": len(description),
        "structured": structured,
        "from_cache": from_cache,
        "error": None,
    }


def get_iba_job_detail(url: str, external_id: str | None = None, use_cache: bool = True, fallback: dict | None = None) -> dict:
    html, from_cache, error = CLIENT.detail_html(url, external_id=external_id, use_cache=use_cache)
    if not html:
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": {"external_id": external_id, "url": url},
            "from_cache": bool(from_cache),
            "error": f"IBA : {error or 'lecture HTTP impossible'}",
        }
    return parse_iba_detail(html, url, external_id, fallback=fallback, from_cache=bool(from_cache))


def _job_from_detail(detail: dict, fallback: dict) -> JobOffer:
    st = detail.get("structured") or {}
    job = JobOffer(
        source="IBA",
        external_id=clean_text(st.get("external_id") or fallback.get("external_id")),
        title=clean_text(st.get("title") or fallback.get("title") or "Titre inconnu"),
        company="IBA",
        location=clean_text(st.get("location") or fallback.get("location") or "Belgium"),
        description=clean_text(detail.get("matching_text")),
        url=clean_text(st.get("url") or fallback.get("url")),
        date_published=clean_text(st.get("date_published")) or None,
        contract_type=clean_text(st.get("contract_type")) or None,
        language=clean_text(st.get("language")) or None,
    )
    job.collection_channel = "IBA"
    job.origin_source = "IBA"
    job.successfactors_job_id = clean_text(st.get("successfactors_job_id") or job.external_id)
    job.job_category = clean_text(st.get("category"))
    job.seniority_level = clean_text(st.get("seniority"))
    job.work_regime = clean_text(st.get("work_regime"))
    return job


def search_targeted_iba_jobs() -> list[JobOffer]:
    belgium, candidates, meta = collect_iba_listing_candidates(use_cache=True)
    print()
    print("=" * 88)
    print("IBA - PREFILTRE LIVE")
    print("=" * 88)
    print(f"Offres Belgique détectées     : {len(belgium)}")
    print(f"Candidates métier             : {len(candidates)}")
    print(f"Pages parcourues              : {meta.get('pages')}")
    for error in meta.get("errors") or []:
        print(f"IBA - avertissement : {error}")

    jobs = []
    rejected_nl = rejected_dutch = closed = errors = 0
    languages = {"fr": 0, "en": 0, "unknown": 0}
    for idx, item in enumerate(candidates, start=1):
        detail = get_iba_job_detail(item.get("url", ""), item.get("external_id"), use_cache=True, fallback=item)
        st = detail.get("structured") or {}
        title = clean_text(st.get("title") or item.get("title"))
        if st.get("closed"):
            closed += 1
            print(f"[{idx:03d}/{len(candidates):03d}] 💤 CLOSED | {title}")
            continue
        if not detail.get("success"):
            errors += 1
            print(f"[{idx:03d}/{len(candidates):03d}] ❌ DETAIL | {title} | {clean_text(detail.get('error'))}")
            continue
        lang = clean_text(st.get("language") or "unknown").lower()
        if lang == "nl":
            rejected_nl += 1
            print(f"[{idx:03d}/{len(candidates):03d}] ⛔ NL     | {title}")
            continue
        if st.get("dutch_required"):
            rejected_dutch += 1
            print(f"[{idx:03d}/{len(candidates):03d}] ⛔ DUTCH  | {title} | néerlandais professionnel requis")
            continue
        if lang not in languages:
            lang = "unknown"
        languages[lang] += 1
        job = _job_from_detail(detail, item)
        jobs.append(job)
        print(f"[{idx:03d}/{len(candidates):03d}] ✅ {lang.upper():<7} | {len(job.description):4d} car. | {job.title} | {job.location}")
        time.sleep(DETAIL_DELAY_SECONDS)

    print()
    print("=" * 76)
    print("                       BILAN IBA V1.0")
    print("=" * 76)
    print(f"Offres Belgique détectées           : {len(belgium)}")
    print(f"Candidates métier préfiltrées       : {len(candidates)}")
    print(f"Conservées FR/EN/ambiguës           : {len(jobs)}")
    print(f"  Français                          : {languages['fr']}")
    print(f"  Anglais                           : {languages['en']}")
    print(f"  Langue ambiguë                    : {languages['unknown']}")
    print(f"Rejetées - fiche clairement NL      : {rejected_nl}")
    print(f"Rejetées - néerlandais requis       : {rejected_dutch}")
    print(f"Clôturées                           : {closed}")
    print(f"Échecs détail                       : {errors}")
    publish_metrics_from_locals("IBA", locals())
    return jobs


def collect_iba_jobs() -> list[JobOffer]:
    return search_targeted_iba_jobs()


# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1
from sources.unified_discovery import matches_master_title
_ud_original__is_target = _is_target

def _is_target(row):
    if _ud_original__is_target(row):
        return True
    try:
        title = row.get("title") if isinstance(row, dict) else ""
    except Exception:
        title = ""
    return matches_master_title(title)
