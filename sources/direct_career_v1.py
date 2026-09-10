"""
JOBHUNTER - DIRECT CAREER GENERIC ENGINE V1

One reusable engine for many employer career pages.
No authentication, no bypass, no browser camouflage.

Extraction order:
1. JSON-LD JobPosting present on page
2. job-like links on career page
3. detail page JSON-LD / text fallback

Target tracks:
- QC_PHARMA_LAB
- DATA_JUNIOR_BI
- QC_DATA_HYBRID
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from sources.api_expansion_common import clean, classify_target_title, make_job
from sources.source_metrics import publish_source_metrics

ROOT=Path(__file__).resolve().parent.parent
CONFIG_PATH=ROOT/"config"/"direct_career_employers_v11.json"

TIMEOUT=30
SESSION=requests.Session()
SESSION.headers.update({
    "User-Agent":"JobHunter/11.0 personal job search",
    "Accept-Language":"fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.5",
})

SENIOR=re.compile(r"\b(senior|sr\.?|lead|manager|head|director|principal|staff|supervisor|vice president|vp)\b",re.I)
DATA_TITLE=re.compile(r"\b(data|business intelligence|bi)\b.*\b(analyst|analytics)\b|\b(analyst|analytics)\b.*\b(data|business intelligence|bi)\b",re.I)
HYBRID=re.compile(r"\b(lims|data integrity|quality data|digital quality|lab digitali[sz]ation|computerized systems? validation|csv specialist|quality systems? analyst|laboratory systems?)\b",re.I)
QC_EXTRA=re.compile(r"\b(qc|quality control|laboratory|laboratoire|lab technician|laborant|microbiology|microbiologie|analytical technician|quality technician|chemist|chimiste)\b",re.I)
BELGIUM=re.compile(r"\b(belgium|belgique|belgi[ëe]|brussels|bruxelles|wallonia|wallonie|flanders|vlaanderen|antwerp|antwerpen|wavre|rixensart|braine|lessines|zaventem|mechelen|puurs|beerse|li[èe]ge|namur|charleroi|gent|ghent|leuven|louvain)\b",re.I)
JOB_PATH=re.compile(r"(job|jobs|career|careers|vacature|vacatures|emploi|offre|position|opening|opportunit)",re.I)

def load_employer_configs(include_disabled=False):
    if not CONFIG_PATH.exists():
        return []
    payload=json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    rows=list(payload.get("static_ready") or [])+list(payload.get("auto_candidates") or [])
    if include_disabled:
        return rows
    return [r for r in rows if r.get("enabled") and r.get("career_url")]

def _hash(*parts):
    raw="|".join(clean(x).lower() for x in parts)
    return hashlib.sha1(raw.encode("utf-8","ignore")).hexdigest()[:22]

def _get(url):
    r=SESSION.get(url,timeout=TIMEOUT,allow_redirects=True)
    r.raise_for_status()
    return r

def _track(title,description=""):
    title=clean(title)
    blob=clean(f"{title} {description}")
    if not title or SENIOR.search(title):
        return None
    base=classify_target_title(title)
    if base:
        return base
    if HYBRID.search(blob):
        return "QC_DATA_HYBRID"
    if DATA_TITLE.search(title):
        exp=re.search(r"\b([3-9]|[1-9]\d)\+?\s+years?\b",blob,re.I)
        if not exp:
            return "DATA_JUNIOR_BI"
    if QC_EXTRA.search(title):
        return "QC_PHARMA_LAB"
    return None

def _jsonld_objects(soup):
    out=[]
    for node in soup.find_all("script",attrs={"type":"application/ld+json"}):
        raw=node.string or node.get_text()
        if not raw:
            continue
        try:
            data=json.loads(raw)
        except Exception:
            continue
        stack=list(data) if isinstance(data,list) else [data]
        while stack:
            obj=stack.pop()
            if isinstance(obj,dict):
                if obj.get("@type")=="JobPosting":
                    out.append(obj)
                graph=obj.get("@graph")
                if isinstance(graph,list):
                    stack.extend(graph)
    return out

def _location_from_jsonld(obj):
    loc=obj.get("jobLocation")
    items=loc if isinstance(loc,list) else [loc]
    chunks=[]
    for item in items:
        if not isinstance(item,dict):
            continue
        addr=item.get("address") or {}
        if isinstance(addr,dict):
            chunks.extend(str(addr.get(k) or "") for k in ("addressLocality","addressRegion","postalCode","addressCountry"))
        elif addr:
            chunks.append(str(addr))
    return clean(" ".join(chunks))

def _company_from_jsonld(obj,default):
    org=obj.get("hiringOrganization") or {}
    if isinstance(org,dict):
        return clean(org.get("name")) or default
    return default

def _job_from_jsonld(source,cfg,obj,page_url):
    title=clean(obj.get("title"))
    desc=clean(obj.get("description"))
    track=_track(title,desc)
    if not track:
        return None
    location=_location_from_jsonld(obj)
    if location and not BELGIUM.search(location):
        return None
    url=clean(obj.get("url")) or page_url
    ext=clean(obj.get("identifier"))
    if isinstance(obj.get("identifier"),dict):
        ext=clean(obj["identifier"].get("value"))
    ext=ext or _hash(url,title,cfg["company"])
    job=make_job(
        source=source,external_id=ext,title=title,
        company=_company_from_jsonld(obj,cfg["company"]),
        location=location or "Belgium",
        description=desc,url=url,date_published=obj.get("datePosted"),
    )
    setattr(job,"api_target_track",track)
    return job

def collect_direct_career_jobs(key):
    cfgs={r["key"]:r for r in load_employer_configs()}
    cfg=cfgs.get(key)
    if not cfg:
        return []

    source=key
    seen=target=errors=detail_failed=geo_rejected=0
    jobs={}

    try:
        r=_get(cfg["career_url"])
        soup=BeautifulSoup(r.text,"html.parser")
    except Exception as exc:
        publish_source_metrics(source,{
            "seen":0,"target_title":0,"non_target":0,"detail_ok":0,"detail_failed":1,
            "geography_accepted":0,"geography_rejected":0,"geography_unknown":0,
            "language_rejected":0,"converted":0,"persisted":None,"errors":1,
        })
        print(source,"CAREER ERROR |",type(exc).__name__,exc)
        return []

    for obj in _jsonld_objects(soup):
        seen+=1
        try:
            job=_job_from_jsonld(source,cfg,obj,r.url)
            if job:
                target+=1;jobs[job.external_id]=job
        except Exception as exc:
            errors+=1
            print(source,"JSONLD ERROR |",type(exc).__name__,exc)

    links={}
    for a in soup.find_all("a",href=True):
        href=urljoin(r.url,a.get("href"))
        title=clean(a.get_text(" ",strip=True))
        if not href.startswith("http"):
            continue
        if href==r.url:
            continue
        if not JOB_PATH.search(urlparse(href).path+" "+title):
            continue
        if len(title)<3 or len(title)>180:
            continue
        links[href]=title

    for url,list_title in list(links.items())[:80]:
        seen+=1
        if not (_track(list_title) or DATA_TITLE.search(list_title) or HYBRID.search(list_title) or QC_EXTRA.search(list_title)):
            continue
        try:
            dr=_get(url)
            ds=BeautifulSoup(dr.text,"html.parser")
            objs=_jsonld_objects(ds)
            made=False
            for obj in objs:
                job=_job_from_jsonld(source,cfg,obj,dr.url)
                if job:
                    target+=1;jobs[job.external_id]=job;made=True
            if made:
                continue

            body=clean(ds.get_text(" ",strip=True))
            h=ds.find(["h1","h2"])
            title=clean(h.get_text(" ",strip=True) if h else "") or list_title
            track=_track(title,body)
            if not track:
                continue
            if not BELGIUM.search(body+" "+title):
                geo_rejected+=1
                continue
            target+=1
            ext=_hash(dr.url,title,cfg["company"])
            job=make_job(
                source=source,external_id=ext,title=title,company=cfg["company"],
                location="Belgium",description=body,url=dr.url,
            )
            setattr(job,"api_target_track",track)
            jobs[ext]=job
            time.sleep(0.15)
        except Exception as exc:
            errors+=1;detail_failed+=1
            print(source,"DETAIL ERROR |",url,"|",type(exc).__name__,exc)

    publish_source_metrics(source,{
        "seen":seen,
        "target_title":target,
        "non_target":max(0,seen-target),
        "detail_ok":len(jobs),
        "detail_failed":detail_failed,
        "geography_accepted":len(jobs),
        "geography_rejected":geo_rejected,
        "geography_unknown":0,
        "language_rejected":0,
        "converted":len(jobs),
        "persisted":None,
        "errors":errors,
    })
    print(source,"| seen=",seen,"| target=",target,"| kept=",len(jobs),"| errors=",errors)
    return list(jobs.values())
