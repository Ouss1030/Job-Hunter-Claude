"""
JOBHUNTER - REMOTIVE API V1

Official public Remotive API.
Targets:
- Junior Data Analyst / BI / Business Analyst
- QC/Data hybrid roles
- QC/Lab roles if remote-compatible
Only locations compatible with Belgium are kept:
Belgium / Europe / EU / EMEA / Worldwide / Remote.
"""

from __future__ import annotations

import re
import requests

from sources.api_expansion_common import clean, classify_target_title, make_job
from sources.source_metrics import publish_source_metrics

SOURCE_KEY="REMOTIVE"
API_URL="https://remotive.com/api/remote-jobs"
TIMEOUT=40

SESSION=requests.Session()
SESSION.headers.update({
    "User-Agent":"JobHunter/9.0 personal job search",
    "Accept":"application/json",
})

SENIOR=re.compile(r"\b(senior|sr\.?|lead|manager|head|director|principal|staff|supervisor)\b",re.I)
DATA=re.compile(r"\b(data|business intelligence|bi)\b",re.I)
ANALYST=re.compile(r"\b(analyst|analytics)\b",re.I)
JUNIOR=re.compile(
    r"\b(junior|graduate|entry[\s-]?level|starter|first\s+job|"
    r"0\s*[-–]\s*2\s+years?|1\s*[-–]\s*2\s+years?|less\s+than\s+2\s+years?)\b",
    re.I,
)
HYBRID=re.compile(
    r"\b(lims|data integrity|quality data|digital quality|lab digitali[sz]ation|"
    r"computerized systems? validation|csv specialist|quality systems? analyst)\b",
    re.I,
)
LOCATION_OK=re.compile(
    r"\b(belgium|belgique|belgi[ëe]|brussels|bruxelles|europe|eu\b|emea|worldwide|anywhere)\b",
    re.I,
)

def _track(title:str,description:str)->str|None:
    blob=clean(f"{title} {description}")
    if SENIOR.search(title or ""):
        return None
    base=classify_target_title(title)
    if base:
        return base
    if HYBRID.search(blob):
        return "QC_DATA_HYBRID"
    if DATA.search(title or "") and ANALYST.search(title or ""):
        # Plain Data Analyst is allowed when junior signals exist, or when
        # the description does not ask for >2 years / seniority.
        if JUNIOR.search(blob):
            return "DATA_JUNIOR_BI"
        exp=re.search(r"\b([3-9]|[1-9]\d)\+?\s+years?\b",blob,re.I)
        if not exp:
            return "DATA_JUNIOR_BI"
    return None

def collect_remotive_jobs()->list:
    seen=target=errors=0
    jobs={}
    try:
        r=SESSION.get(API_URL,timeout=TIMEOUT)
        r.raise_for_status()
        rows=(r.json() or {}).get("jobs") or []
    except Exception as exc:
        publish_source_metrics(SOURCE_KEY,{
            "seen":0,"target_title":0,"non_target":0,
            "detail_ok":0,"detail_failed":1,
            "geography_accepted":0,"geography_rejected":0,"geography_unknown":0,
            "language_rejected":0,"converted":0,"persisted":None,"errors":1,
        })
        print("REMOTIVE API ERROR |",type(exc).__name__,exc)
        return []

    for row in rows:
        seen+=1
        title=clean(row.get("title"))
        description=clean(row.get("description"))
        location=clean(row.get("candidate_required_location"))
        if not LOCATION_OK.search(location):
            continue
        track=_track(title,description)
        if not track:
            continue
        target+=1
        ext=str(row.get("id") or "").strip() or clean(row.get("url"))
        try:
            job=make_job(
                source=SOURCE_KEY,
                external_id=ext,
                title=title,
                company=clean(row.get("company_name")) or "Unknown",
                location=location or "Remote Europe",
                description=description,
                url=clean(row.get("url")),
                date_published=row.get("publication_date"),
            )
            setattr(job,"api_target_track",track)
            jobs[ext]=job
        except Exception as exc:
            errors+=1
            print("REMOTIVE CONVERT ERROR |",ext,"|",type(exc).__name__,exc)

    publish_source_metrics(SOURCE_KEY,{
        "seen":seen,
        "target_title":target,
        "non_target":max(0,seen-target),
        "detail_ok":len(jobs),
        "detail_failed":errors,
        "geography_accepted":len(jobs),
        "geography_rejected":0,
        "geography_unknown":0,
        "language_rejected":0,
        "converted":len(jobs),
        "persisted":None,
        "errors":errors,
    })
    print("REMOTIVE | seen=",seen,"| target=",target,"| kept=",len(jobs),"| errors=",errors)
    return list(jobs.values())
