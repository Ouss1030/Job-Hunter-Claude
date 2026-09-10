"""
JOBHUNTER - BACKLOG DEEP VALIDATOR V15

Second-pass validation for the 55 non-activated V14 candidates.
It tries:
- verified URL corrections for selected high-value sources
- root + common job/career paths
- redirects to public ATS/listing pages
- JSON-LD JobPosting / >=2 job-like links / ATS evidence

No stealth, no CAPTCHA bypass, no IP rotation.
403/429 are not bypassed.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from sources.backlog_validator_v14 import (
    CONFIG_PATH, SESSION, BLOCK_STATUS, _jsonld_jobs, _candidate_links,
    _detect_ats, canonical, load_backlog, save_backlog, now_iso,
)

VERSION="15.0"
TIMEOUT=25

VERIFIED_OVERRIDES={
    "STIB_MIVB":"https://jobs.stib-mivb.be/viewalljobs/",
    "SGS":"https://www.sgs.com/en-be/our-company/careers-at-sgs/job-opportunities",
    "SCIENSANO_RESEARCH":"https://www.sciensano.be/fr/travailler-faire-un-stage-chez-sciensano/mes-opportunites-demploi",
    "VUB_JOBS":"https://jobs.vub.be/go/EN_ALL-JOBS/3775601/",
}

COMMON_PATHS=(
    "/jobs",
    "/jobs/",
    "/careers",
    "/careers/",
    "/vacatures",
    "/vacatures/",
    "/fr/jobs",
    "/fr/jobs/",
    "/fr/emploi",
    "/fr/emploi/",
    "/fr/carrieres",
    "/fr/carrieres/",
    "/werken-bij",
    "/werken-bij/",
    "/job-opportunities",
    "/viewalljobs/",
)

RETRY_STATUSES={
    "PENDING_NO_JOB_EVIDENCE","WARN_HTTP","WARN_FETCH","SKIPPED_NO_URL",
}
DO_NOT_RETRY={
    "NEEDS_CREDENTIALS","SKIPPED_POLICY","SKIPPED_BLOCKED",
    "DUPLICATE_EXISTING",
}

LISTING_MARKER=re.compile(
    r"(results?\s+\d+\s*[-–]\s*\d+|résultats?\s+\d+|resultaten\s+\d+|"
    r"open jobs?|openstaande vacatures|postes? disponibles|vacatures?\s+\(\d+\)|"
    r"job opportunities|offres d['’]emploi)",
    re.I,
)

def _root(url):
    try:
        p=urlsplit(str(url or ""))
        if not p.scheme or not p.netloc:
            return ""
        return urlunsplit((p.scheme,p.netloc,"","",""))
    except Exception:
        return ""

def candidate_urls(row):
    key=str(row.get("key") or "").upper()
    seen=set()
    out=[]

    def add(u):
        u=canonical(u)
        if u and u.startswith(("http://","https://")) and u not in seen:
            seen.add(u);out.append(u)

    if key in VERIFIED_OVERRIDES:
        add(VERIFIED_OVERRIDES[key])

    add(row.get("url") or "")
    root=_root(row.get("url") or "")
    if root:
        for path in COMMON_PATHS:
            add(root+path)

    # Limit breadth while keeping verified override first.
    return out[:12]

def probe_url(url):
    try:
        r=SESSION.get(url,timeout=TIMEOUT,allow_redirects=True)
    except Exception as exc:
        return {"ok":False,"status":"WARN_FETCH","reason":f"{type(exc).__name__}: {exc}"}

    if r.status_code in BLOCK_STATUS:
        return {"ok":False,"status":"SKIPPED_BLOCKED","reason":f"HTTP {r.status_code}"}
    if r.status_code>=400:
        return {"ok":False,"status":"WARN_HTTP","reason":f"HTTP {r.status_code}"}

    text=r.text or ""
    ctype=str(r.headers.get("content-type") or "").lower()
    if "html" not in ctype and "<html" not in text[:600].lower():
        return {"ok":False,"status":"PENDING_NON_HTML","reason":ctype}

    soup=BeautifulSoup(text,"html.parser")
    jsonld=len(_jsonld_jobs(soup))
    links=_candidate_links(r.url,soup)
    ats=_detect_ats(r.url+"\n"+text[:700000])
    marker=bool(LISTING_MARKER.search(soup.get_text(" ",strip=True)[:120000]))

    # Stronger than V14: verified listing marker alone is insufficient unless
    # it comes from a known override; otherwise require concrete links/ATS/JSON-LD.
    evidence=jsonld>0 or len(links)>=2 or bool(ats)

    return {
        "ok":bool(evidence),
        "status":"ACTIVATED" if evidence else "PENDING_NO_JOB_EVIDENCE",
        "reason":f"jsonld={jsonld}, job_links={len(links)}, ats={ats or 'NONE'}, listing_marker={marker}",
        "url":canonical(r.url),
        "jsonld":jsonld,
        "links":len(links),
        "ats":ats,
        "marker":marker,
    }

def deep_validate_remaining(progress=None,pause_seconds=0.55):
    rows=load_backlog(include_all=True)
    out=[]
    total=sum(1 for r in rows if not r.get("active") and r.get("probe_status") in RETRY_STATUSES)
    idx=0

    for row in rows:
        if row.get("active") or row.get("probe_status") in DO_NOT_RETRY:
            out.append(row);continue
        if row.get("probe_status") not in RETRY_STATUSES:
            out.append(row);continue

        idx+=1
        if progress:progress(idx,total,row)

        best=None
        attempts=[]
        for url in candidate_urls(row):
            res=probe_url(url)
            attempts.append({"url":url,**res})
            if res.get("ok"):
                best=res
                break
            if res.get("status")=="SKIPPED_BLOCKED":
                # Do not keep probing a domain that explicitly blocks us.
                break
            time.sleep(max(0.0,float(pause_seconds)))

        new=dict(row)
        new["v15_attempts"]=attempts
        new["v15_validated_at"]=now_iso()

        if best:
            new["active"]=True
            new["status"]="ACTIVE"
            new["health"]="HEALTHY"
            new["collection_mode"]="LIVE"
            new["collector_module"]="sources.backlog_validator_v14"
            new["collector_name"]="collect_backlog_source_jobs"
            new["validated_url"]=best["url"]
            new["probe_status"]="ACTIVATED"
            new["probe_reason"]="V15 deep validation: "+best["reason"]
            new["probe_job_links"]=best["links"]
            new["probe_jsonld_jobs"]=best["jsonld"]
            new["probe_ats"]=best["ats"]
        else:
            statuses=[a.get("status") for a in attempts]
            if "SKIPPED_BLOCKED" in statuses:
                new["probe_status"]="SKIPPED_BLOCKED"
                new["probe_reason"]="V15: HTTP block encountered; no bypass attempted."
            elif attempts:
                last=attempts[-1]
                new["probe_status"]="PENDING_DEEP_NO_EVIDENCE"
                new["probe_reason"]="V15 exhausted alternate public paths; "+str(last.get("reason") or "")
            else:
                new["probe_status"]="PENDING_DEEP_NO_URL"
                new["probe_reason"]="V15 found no safe candidate URL."

        out.append(new)

    save_backlog(out)
    return out
