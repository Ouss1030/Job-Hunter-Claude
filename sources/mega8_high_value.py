"""
JOBHUNTER - HIGH VALUE EXPANSION V8

New keyless sources:
- EUROPHARMAJOBS : pharma/science Europe, Belgium filter
- ICTJOB         : Belgium IT/Data
- REFERENCES     : Belgian francophone job board
- SWDE           : official Walloon water employer
- ARBEITNOW      : free public European jobs API

Targeting:
- QC / Pharma / Laboratory
- Junior Data Analyst / BI junior
- QC/Data hybrid
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from sources.api_expansion_common import clean, classify_target_title, make_job
from sources.source_metrics import publish_source_metrics

UA="JobHunter/8.0 personal job search"
TIMEOUT=30

SESSION=requests.Session()
SESSION.headers.update({
    "User-Agent": UA,
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.4",
})

SENIOR=re.compile(r"\b(senior|sr\.?|lead|manager|head|director|principal|staff|supervisor)\b",re.I)
DATA_PLAIN=re.compile(r"\bdata\s+analyst\b",re.I)
DATA_JUNIOR_SIGNAL=re.compile(
    r"\b(junior|first\s+job|starter|graduate|entry[\s-]?level|0\s*[-–]\s*2\s+years?|"
    r"1\s*[-–]\s*2\s+years?|(?:less\s+than|<)\s*2\s+years?|"
    r"6\s+months?\s*[-–]\s*2\s+years?)\b",
    re.I,
)
LAB_EXTRA=re.compile(
    r"\b(pr[ée]leveur(?:se)?\s+(?:de\s+)?laboratoire|laboratory\s+sampler|"
    r"technicien(?:ne)?\s+qualit[ée]|quality\s+technician|lab\s+assistant)\b",
    re.I,
)

def _get(url, **kwargs):
    r=SESSION.get(url,timeout=TIMEOUT,allow_redirects=True,**kwargs)
    r.raise_for_status()
    return r

def _hash_id(*parts):
    blob="|".join(clean(x).lower() for x in parts)
    return hashlib.sha1(blob.encode("utf-8","ignore")).hexdigest()[:20]

def _target(title, detail=""):
    track=classify_target_title(title)
    if track:
        return track
    if SENIOR.search(title or ""):
        return None
    if LAB_EXTRA.search(title or ""):
        return "QC_PHARMA_LAB"
    if DATA_PLAIN.search(title or "") and DATA_JUNIOR_SIGNAL.search((title or "")+" "+(detail or "")):
        return "DATA_JUNIOR_BI"
    return None

def _publish(source,seen,target,jobs,errors,detail_failed=0):
    publish_source_metrics(source,{
        "seen":seen,
        "target_title":target,
        "non_target":max(0,seen-target),
        "detail_ok":len(jobs),
        "detail_failed":detail_failed,
        "geography_accepted":len(jobs),
        "geography_rejected":0,
        "geography_unknown":0,
        "language_rejected":0,
        "converted":len(jobs),
        "persisted":None,
        "errors":errors,
    })

def _detail_text(url):
    r=_get(url)
    soup=BeautifulSoup(r.text,"html.parser")
    return clean(soup.get_text(" ",strip=True)), soup, r.url

# ------------------------------------------------------------------
# EuroPharmaJobs
# ------------------------------------------------------------------
EUROPHARMA_URL="https://www.europharmajobs.com/jobs/belgium"

def collect_europharmajobs_jobs():
    source="EUROPHARMAJOBS"
    seen=target=errors=detail_failed=0
    jobs={}
    try:
        r=_get(EUROPHARMA_URL)
        soup=BeautifulSoup(r.text,"html.parser")
    except Exception as exc:
        _publish(source,0,0,{},1,1)
        print("EUROPHARMAJOBS LIST ERROR |",type(exc).__name__,exc)
        return []

    candidates={}
    for a in soup.find_all("a",href=True):
        title=clean(a.get_text(" ",strip=True))
        href=urljoin(r.url,a.get("href"))
        if not title or href==r.url:
            continue
        # Skip navigation/category links.
        if len(title)<4 or any(x in href.lower() for x in ("/job_search/category/","/job_search/location/","#")):
            continue
        if urlparse(href).netloc and "europharmajobs.com" not in urlparse(href).netloc:
            continue
        if "/job" not in urlparse(href).path.lower():
            continue
        seen+=1
        if not (_target(title) or DATA_PLAIN.search(title) or LAB_EXTRA.search(title)):
            continue
        target+=1
        candidates[href]=title

    for url,list_title in list(candidates.items())[:40]:
        try:
            text,soup,final=_detail_text(url)
            h=soup.find(["h1","h2"])
            parsed=clean(h.get_text(" ",strip=True) if h else "")
            title=parsed if _target(parsed,text) else list_title
            track=_target(title,text)
            if not track:
                continue
            location="Belgium"
            company="EuroPharmaJobs listing"
            jobs[url]=make_job(
                source=source,external_id=_hash_id(url,title),
                title=title,company=company,location=location,
                description=text,url=final,
            )
            setattr(jobs[url],"api_target_track",track)
            time.sleep(0.35)
        except Exception as exc:
            errors+=1;detail_failed+=1
            print("EUROPHARMAJOBS DETAIL ERROR |",url,"|",type(exc).__name__,exc)

    _publish(source,seen,target,jobs,errors,detail_failed)
    print(source,"| kept=",len(jobs),"| seen=",seen,"| target=",target,"| errors=",errors)
    return list(jobs.values())

# ------------------------------------------------------------------
# ICTjob
# ------------------------------------------------------------------
ICTJOB_PAGES=(
    "https://www.ictjob.be/en/search-it-jobs/data-analyst-belgium",
    "https://www.ictjob.be/en/search-it-jobs/business-intelligence-belgium",
)

def collect_ictjob_jobs():
    source="ICTJOB"
    seen=target=errors=detail_failed=0
    links={}
    for page in ICTJOB_PAGES:
        try:
            r=_get(page)
            soup=BeautifulSoup(r.text,"html.parser")
        except Exception as exc:
            errors+=1
            print("ICTJOB LIST ERROR |",page,"|",type(exc).__name__,exc)
            continue
        for a in soup.find_all("a",href=True):
            href=urljoin(r.url,a.get("href"))
            title=clean(a.get_text(" ",strip=True))
            path=urlparse(href).path.lower()
            if not title or not any(tok in path for tok in ("/job/","/emploi/","/vacature/")):
                continue
            seen+=1
            if SENIOR.search(title):
                continue
            if not (_target(title) or DATA_PLAIN.search(title)):
                continue
            target+=1
            links[href]=title

    jobs={}
    for url,list_title in list(links.items())[:40]:
        try:
            text,soup,final=_detail_text(url)
            h=soup.find(["h1","h2"])
            parsed=clean(h.get_text(" ",strip=True) if h else "")
            title=parsed if (_target(parsed,text) or DATA_PLAIN.search(parsed)) else list_title
            track=_target(title,text)
            if not track:
                continue
            jobs[url]=make_job(
                source=source,external_id=_hash_id(final,title),
                title=title,company="ictjob.be listing",
                location="Belgium",description=text,url=final,
            )
            setattr(jobs[url],"api_target_track",track)
            time.sleep(0.35)
        except Exception as exc:
            errors+=1;detail_failed+=1
            print("ICTJOB DETAIL ERROR |",url,"|",type(exc).__name__,exc)

    _publish(source,seen,target,jobs,errors,detail_failed)
    print(source,"| kept=",len(jobs),"| seen=",seen,"| target=",target,"| errors=",errors)
    return list(jobs.values())

# ------------------------------------------------------------------
# References.be
# ------------------------------------------------------------------
REFERENCES_URL="https://www.references.be/Jobs"

def collect_references_jobs():
    source="REFERENCES"
    seen=target=errors=detail_failed=0
    try:
        r=_get(REFERENCES_URL)
        soup=BeautifulSoup(r.text,"html.parser")
    except Exception as exc:
        _publish(source,0,0,{},1,1)
        print("REFERENCES LIST ERROR |",type(exc).__name__,exc)
        return []

    links={}
    for a in soup.find_all("a",href=True):
        title=clean(a.get_text(" ",strip=True))
        href=urljoin(r.url,a.get("href"))
        path=urlparse(href).path.lower()
        if not title or "/jobs/" not in path:
            continue
        # numeric job pages are a useful discriminator
        if not re.search(r"/jobs/\d+",path):
            continue
        seen+=1
        if not (_target(title) or DATA_PLAIN.search(title) or LAB_EXTRA.search(title)):
            continue
        if SENIOR.search(title):
            continue
        target+=1
        links[href]=title

    jobs={}
    for url,list_title in list(links.items())[:40]:
        try:
            text,soup,final=_detail_text(url)
            h=soup.find(["h1","h2"])
            parsed=clean(h.get_text(" ",strip=True) if h else "")
            title=parsed if (_target(parsed,text) or DATA_PLAIN.search(parsed) or LAB_EXTRA.search(parsed)) else list_title
            track=_target(title,text)
            if not track:
                continue
            jobs[url]=make_job(
                source=source,external_id=_hash_id(final,title),
                title=title,company="Références.be listing",
                location="Belgium",description=text,url=final,
            )
            setattr(jobs[url],"api_target_track",track)
            time.sleep(0.35)
        except Exception as exc:
            errors+=1;detail_failed+=1
            print("REFERENCES DETAIL ERROR |",url,"|",type(exc).__name__,exc)

    _publish(source,seen,target,jobs,errors,detail_failed)
    print(source,"| kept=",len(jobs),"| seen=",seen,"| target=",target,"| errors=",errors)
    return list(jobs.values())

# ------------------------------------------------------------------
# SWDE
# ------------------------------------------------------------------
SWDE_URL="https://www.swde.be/fr/jobs/offres-emploi"

def collect_swde_jobs():
    source="SWDE"
    seen=target=errors=detail_failed=0
    try:
        r=_get(SWDE_URL)
        soup=BeautifulSoup(r.text,"html.parser")
    except Exception as exc:
        _publish(source,0,0,{},1,1)
        print("SWDE LIST ERROR |",type(exc).__name__,exc)
        return []

    links={}
    for a in soup.find_all("a",href=True):
        title=clean(a.get_text(" ",strip=True))
        href=urljoin(r.url,a.get("href"))
        if not title:
            continue
        if "job" not in urlparse(href).path.lower():
            continue
        seen+=1
        blob=title
        if not (_target(blob) or LAB_EXTRA.search(blob) or DATA_PLAIN.search(blob)):
            continue
        if SENIOR.search(blob):
            continue
        target+=1
        links[href]=title

    jobs={}
    for url,list_title in list(links.items())[:30]:
        try:
            text,soup,final=_detail_text(url)
            h=soup.find(["h1","h2"])
            parsed=clean(h.get_text(" ",strip=True) if h else "")
            title=parsed if (_target(parsed,text) or LAB_EXTRA.search(parsed) or DATA_PLAIN.search(parsed)) else list_title
            track=_target(title,text)
            if not track:
                continue
            jobs[url]=make_job(
                source=source,external_id=_hash_id(final,title),
                title=title,company="SWDE",location="Wallonia, Belgium",
                description=text,url=final,
            )
            setattr(jobs[url],"api_target_track",track)
            time.sleep(0.35)
        except Exception as exc:
            errors+=1;detail_failed+=1
            print("SWDE DETAIL ERROR |",url,"|",type(exc).__name__,exc)

    _publish(source,seen,target,jobs,errors,detail_failed)
    print(source,"| kept=",len(jobs),"| seen=",seen,"| target=",target,"| errors=",errors)
    return list(jobs.values())

# ------------------------------------------------------------------
# Arbeitnow public API
# ------------------------------------------------------------------
ARBEITNOW_API="https://www.arbeitnow.com/api/job-board-api"
BELGIUM_MARKER=re.compile(r"\b(belgium|belgique|belgi[ëe]|brussels|bruxelles|wallonia|wallonie)\b",re.I)

def collect_arbeitnow_jobs():
    source="ARBEITNOW"
    seen=target=errors=0
    jobs={}
    for page in range(1,4):
        try:
            r=_get(ARBEITNOW_API,params={"page":page})
            payload=r.json()
            rows=payload.get("data") or []
        except Exception as exc:
            errors+=1
            print("ARBEITNOW API ERROR | page=",page,"|",type(exc).__name__,exc)
            continue
        if not rows:
            break
        for row in rows:
            seen+=1
            title=clean(row.get("title"))
            location=clean(row.get("location"))
            description=clean(row.get("description"))
            if not BELGIUM_MARKER.search(location+" "+description):
                continue
            track=_target(title,description)
            if not track:
                continue
            target+=1
            url=clean(row.get("url"))
            ext=clean(row.get("slug")) or _hash_id(url,title)
            job=make_job(
                source=source,external_id=ext,title=title,
                company=clean(row.get("company_name")) or "Unknown",
                location=location or "Belgium",
                description=html_lib.unescape(description),
                url=url,date_published=row.get("created_at"),
            )
            setattr(job,"api_target_track",track)
            jobs[ext]=job
        time.sleep(0.6)

    _publish(source,seen,target,jobs,errors,errors)
    print(source,"| kept=",len(jobs),"| seen=",seen,"| target=",target,"| errors=",errors)
    return list(jobs.values())
