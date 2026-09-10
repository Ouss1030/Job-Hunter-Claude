"""JOB HUNTER BELGIUM - SANOFI BELGIUM V1.0 (Radancy public careers)."""
from __future__ import annotations
import re
import time
from database.models import JobOffer
from sources.radancy import RadancySite, clean_text, fetch_listing, extract_listing_rows, get_job_detail
from sources.randstad import dutch_professional_required
from sources.scienceatwork import detect_language

SITE = RadancySite(
    key="SANOFI", company="Sanofi", base_url="https://jobs.sanofi.com",
    listing_urls=(
        "https://jobs.sanofi.com/en/location/belgium-jobs/34155/2802361/2",
        "https://jobs.sanofi.com/en/location/belgique-jobs/2649/2802361/2",
        "https://jobs.sanofi.com/en/search_jobs/Belgique/2649/2/2802361/50x75/4x5/50/2",
    ),
    cache_slug="sanofi",
)

TARGET = (
    r"\bqc\s+(?:analyst|technician|associate|specialist)\b", r"\bquality\s+control\b",
    r"\blab(?:oratory)?\s+(?:analyst|technician|associate)\b", r"\banalytical\s+(?:analyst|technician|scientist|expert)\b",
    r"\bmicrobiology\b", r"\benvironmental\s+monitoring\b", r"\bdata\s+analyst\b", r"\bbusiness\s+analyst\b",
    r"\bdata\s+quality\b", r"\bdata\s+integrity\b", r"\bmaster\s+data\b", r"\bpower\s*bi\b", r"\bbi\s+(?:analyst|developer)\b",
)
EXCLUDE = (
    r"\b(?:senior|sr\.?|principal|lead|manager|director|head|vp|supervisor|team\s+leader)\b",
    r"\b(?:intern|internship|stage|graduate|trainee|student|vie\s+contract|apprentice)\b",
)

def _target(title: str) -> bool:
    t = clean_text(title).lower()
    return bool(t) and not any(re.search(p, t, re.I) for p in EXCLUDE) and any(re.search(p, t, re.I) for p in TARGET)

def collect_sanofi_listing_candidates(use_cache: bool = True):
    print("SANOFI - collecte directe Belgique via Radancy public")
    html, listing_url, from_cache, errors, announced, scope = fetch_listing(SITE, use_cache=use_cache)
    rows = extract_listing_rows(SITE, html, listing_url) if html else []
    candidates = [r for r in rows if _target(r.get("title", ""))]
    print(f"SANOFI - BELGIQUE : {len(rows)} offre(s) | {len(candidates)} candidate(s) métier | annoncé={announced if announced is not None else '?'} | {'CACHE' if from_cache else 'WEB'}")
    return candidates, {"belgium_rows":len(rows),"candidates":len(candidates),"all_belgium_rows":rows,"errors":errors,"announced_total":announced,"scope":scope,"listing_url":listing_url}

def get_sanofi_job_detail(url: str, external_id: str | None = None, use_cache: bool = True, fallback: dict | None = None):
    detail = get_job_detail(SITE, url, external_id=external_id, use_cache=use_cache, fallback=fallback)
    if detail.get("success"):
        text = detail.get("matching_text", "")
        s = detail.setdefault("structured", {})
        s["language"] = detect_language(text)
        s["dutch_required"] = dutch_professional_required(text)
        s["sanofi_job_id"] = s.get("radancy_job_id") or s.get("external_id")
    return detail

def _to_job(detail, fallback):
    s = detail.get("structured") or {}; text=clean_text(detail.get("matching_text"))
    job=JobOffer(source="SANOFI", external_id=clean_text(s.get("external_id") or fallback.get("external_id")), title=clean_text(s.get("title") or fallback.get("title")), company="Sanofi", location=clean_text(s.get("location") or fallback.get("location")), description=text, url=clean_text(s.get("url") or fallback.get("url")), date_published=clean_text(s.get("date_published") or fallback.get("date_published")) or None, contract_type=clean_text(s.get("contract_type")) or None, language=clean_text(s.get("language")) or None)
    job.collection_channel="SANOFI"; job.origin_source="SANOFI"; job.detail_enrichment_attempted=True; job.detail_enrichment_success=True; job.detail_matching_text=text; job.detail_matching_text_length=len(text); job.sanofi_job_id=clean_text(s.get("sanofi_job_id") or job.external_id); job.radancy_requisition_id=clean_text(s.get("requisition_id"))
    return job

def collect_sanofi_jobs():
    candidates, meta=collect_sanofi_listing_candidates(use_cache=True); jobs=[]
    for i,item in enumerate(candidates,1):
        d=get_sanofi_job_detail(item.get("url",""), item.get("external_id"), True, item); s=d.get("structured") or {}; title=clean_text(s.get("title") or item.get("title"))
        if d.get("closed"): print(f"[{i:02d}/{len(candidates):02d}] 💤 CLOSED | {title}"); continue
        if not d.get("success"): print(f"[{i:02d}/{len(candidates):02d}] ⚠️ DETAIL | {title} | {d.get('error')}"); continue
        lang=clean_text(s.get("language")).lower() or "unknown"
        if lang=="nl": print(f"[{i:02d}/{len(candidates):02d}] ⛔ NL     | {title}"); continue
        if s.get("dutch_required"): print(f"[{i:02d}/{len(candidates):02d}] ⛔ DUTCH  | {title}"); continue
        job=_to_job(d,item); jobs.append(job); print(f"[{i:02d}/{len(candidates):02d}] ✅ {lang.upper():<7} | {len(job.description):4d} car. | {job.title} | {job.location}"); time.sleep(.08)
    return jobs


# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1
from sources.unified_discovery import matches_master_title

_ud_original__target = _target

def _target(*args, **kwargs):
    if _ud_original__target(*args, **kwargs):
        return True
    try:
        title = args[0] if args else kwargs.get('title', '')
    except Exception:
        return False
    return matches_master_title(title)
