"""JOB HUNTER BELGIUM - BAXTER BELGIUM V1.0 (Radancy public careers)."""
from __future__ import annotations
import re
import time
from database.models import JobOffer
from sources.radancy import RadancySite, clean_text, fetch_listing, extract_listing_rows, get_job_detail
from sources.randstad import dutch_professional_required
from sources.scienceatwork import detect_language

SITE = RadancySite(key="BAXTER", company="Baxter", base_url="https://jobs.baxter.com", listing_urls=("https://jobs.baxter.com/en/location/belgium-jobs/152/2802361/2",), cache_slug="baxter", location_terms=("wallonia", "lessines", "braine-l'alleud", "braine l'alleud"))
TARGET=(r"\bqc\b",r"\bquality\s+control\b",r"\bquality\s+assurance\b",r"\bqa\s+(?:analyst|associate|technician|specialist)\b",r"\blab(?:oratory)?\s+(?:analyst|technician|associate)\b",r"\bresearch\s+(?:associate|scientist)\b",r"\banalytical\s+(?:analyst|scientist|chemist)\b",r"\bchemist\b",r"\bmicrobiology\b",r"\bdata\s+analyst\b",r"\bbusiness\s+analyst\b",r"\bdata\s+quality\b",r"\bmaster\s+data\b",r"\bpower\s*bi\b")
EXCLUDE=(r"\b(?:senior|sr\.?|principal|lead|manager|director|head|vp|supervisor|team\s+leader)\b",r"\b(?:intern|internship|stage|graduate|trainee|student|apprentice)\b")
def _target(title):
    t=clean_text(title).lower(); return bool(t) and not any(re.search(p,t,re.I) for p in EXCLUDE) and any(re.search(p,t,re.I) for p in TARGET)
def collect_baxter_listing_candidates(use_cache=True):
    print("BAXTER - collecte directe Belgique via Radancy public")
    html,url,fc,errors,announced,scope=fetch_listing(SITE,use_cache); rows=extract_listing_rows(SITE,html,url) if html else []; c=[r for r in rows if _target(r.get("title",""))]
    print(f"BAXTER - BELGIQUE : {len(rows)} offre(s) | {len(c)} candidate(s) métier | annoncé={announced if announced is not None else '?'} | {'CACHE' if fc else 'WEB'}")
    return c,{"belgium_rows":len(rows),"candidates":len(c),"all_belgium_rows":rows,"errors":errors,"announced_total":announced,"scope":scope,"listing_url":url}
def get_baxter_job_detail(url,external_id=None,use_cache=True,fallback=None):
    d=get_job_detail(SITE,url,external_id,use_cache,fallback)
    if d.get("success"):
        text=d.get("matching_text",""); s=d.setdefault("structured",{}); s["language"]=detect_language(text); s["dutch_required"]=dutch_professional_required(text); s["baxter_job_id"]=s.get("radancy_job_id") or s.get("external_id")
    return d
def _to_job(d,f):
    s=d.get("structured") or {}; text=clean_text(d.get("matching_text")); job=JobOffer(source="BAXTER",external_id=clean_text(s.get("external_id") or f.get("external_id")),title=clean_text(s.get("title") or f.get("title")),company="Baxter",location=clean_text(s.get("location") or f.get("location")),description=text,url=clean_text(s.get("url") or f.get("url")),date_published=clean_text(s.get("date_published") or f.get("date_published")) or None,contract_type=clean_text(s.get("contract_type")) or None,language=clean_text(s.get("language")) or None); job.collection_channel="BAXTER"; job.origin_source="BAXTER"; job.detail_enrichment_attempted=True; job.detail_enrichment_success=True; job.detail_matching_text=text; job.detail_matching_text_length=len(text); job.baxter_job_id=clean_text(s.get("baxter_job_id") or job.external_id); job.radancy_requisition_id=clean_text(s.get("requisition_id")); return job
def collect_baxter_jobs():
    c,meta=collect_baxter_listing_candidates(True); jobs=[]
    for i,item in enumerate(c,1):
        d=get_baxter_job_detail(item.get("url",""),item.get("external_id"),True,item); s=d.get("structured") or {}; title=clean_text(s.get("title") or item.get("title"))
        if d.get("closed"): print(f"[{i:02d}/{len(c):02d}] 💤 CLOSED | {title}"); continue
        if not d.get("success"): print(f"[{i:02d}/{len(c):02d}] ⚠️ DETAIL | {title} | {d.get('error')}"); continue
        lang=clean_text(s.get("language")).lower() or "unknown"
        if lang=="nl": print(f"[{i:02d}/{len(c):02d}] ⛔ NL     | {title}"); continue
        if s.get("dutch_required"): print(f"[{i:02d}/{len(c):02d}] ⛔ DUTCH  | {title}"); continue
        job=_to_job(d,item); jobs.append(job); print(f"[{i:02d}/{len(c):02d}] ✅ {lang.upper():<7} | {len(job.description):4d} car. | {job.title} | {job.location}"); time.sleep(.08)
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
