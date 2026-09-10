"""
JOBHUNTER - STUDENT NETWORK V1

Dedicated public Belgian student-job feeds:
- Start People student jobs
- Synergie student jobs
- VDAB public student jobs web search

No authentication, no anti-bot bypass, bounded requests.
Every converted job is explicitly STUDENT_ANY.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import time
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from sources.api_expansion_common import clean, make_job
from sources.source_metrics import publish_source_metrics

VERSION="1.1"
TIMEOUT=30
SESSION=requests.Session()
SESSION.headers.update({
    "User-Agent":"JobHunter/13.0 personal job search",
    "Accept-Language":"fr-BE,fr;q=0.9,nl;q=0.8,en;q=0.7",
})

PAGES={
    "START_PEOPLE_STUDENT":"https://www.startpeople.be/fr/joblist/offres-d-emploi-etudiant",
    "SYNERGIE_STUDENT":"https://www.synergiejobs.be/fr/jobs/?contractTypes=contract-type-student",
    "VDAB_STUDENT_WEB":"https://www.vdab.be/vindeenjob/jobs/studentenjob",
}

DETAIL_PATTERNS={
    "START_PEOPLE_STUDENT":re.compile(r"^/fr/job/[^/]+-\d+/?$",re.I),
    "SYNERGIE_STUDENT":re.compile(r"^/fr/jobs/[0-9a-f]{24}/[^/]+/?$",re.I),
    "VDAB_STUDENT_WEB":re.compile(r"^/vindeenjob/vacatures/\d+/[^/]+/?$",re.I),
}

STUDENT_SIGNAL=re.compile(
    r"\b(job étudiant|job etudiant|contrat étudiant|contrat etudiant|"
    r"statut étudiant|statut etudiant|studentenjob|studentenjobs|jobstudent|"
    r"étudiant\b|etudiant\b|student job|student worker|student contract)\b",
    re.I,
)
INTERNSHIP=re.compile(r"\b(stage|stagiaire|internship|trainee|apprentice)\b",re.I)
LOW_VALUE=re.compile(r"\b(survey|sondage|jeux? en ligne|online games?)\b",re.I)

def _hash(*parts):
    raw="|".join(clean(x).lower() for x in parts)
    return hashlib.sha1(raw.encode("utf-8","ignore")).hexdigest()[:22]

def _canonical_url(url):
    try:
        p=urlsplit(str(url or ""))
        return urlunsplit((p.scheme,p.netloc,p.path,"",""))
    except Exception:
        return str(url or "")

def _get(url,params=None):
    r=SESSION.get(url,params=params,timeout=TIMEOUT,allow_redirects=True)
    r.raise_for_status()
    return r

def _is_detail(source,url):
    try:path=urlparse(url).path
    except Exception:return False
    return bool(DETAIL_PATTERNS[source].match(path))

def _jsonld_jobs(soup):
    out=[]
    for node in soup.find_all("script",attrs={"type":"application/ld+json"}):
        raw=node.string or node.get_text()
        if not raw:continue
        try:data=json.loads(raw)
        except Exception:continue
        stack=list(data) if isinstance(data,list) else [data]
        while stack:
            obj=stack.pop()
            if isinstance(obj,dict):
                if obj.get("@type")=="JobPosting":
                    out.append(obj)
                if isinstance(obj.get("@graph"),list):
                    stack.extend(obj["@graph"])
    return out

def _location(obj):
    loc=obj.get("jobLocation")
    items=loc if isinstance(loc,list) else [loc]
    vals=[]
    for item in items:
        if not isinstance(item,dict):continue
        a=item.get("address") or {}
        if isinstance(a,dict):
            vals.extend(str(a.get(k) or "") for k in (
                "addressLocality","addressRegion","postalCode","addressCountry"
            ))
    return clean(" ".join(vals))

def _company(obj,default):
    org=obj.get("hiringOrganization") or {}
    if isinstance(org,dict):
        v=clean(org.get("name"))
        if v:return v
    return default

def _eligible(source,title,body,url):
    if not _is_detail(source,url):
        return False
    blob=clean(f"{title} {body}")
    if not title or LOW_VALUE.search(blob) or INTERNSHIP.search(title):
        return False

    if source=="START_PEOPLE_STUDENT":
        return bool(
            re.search(r"\bcontrat étudiant\b",body,re.I)
            or re.search(r"\bEtudiant\s*\(réduction ONSS\)",body,re.I)
            or STUDENT_SIGNAL.search(title)
        )
    if source=="SYNERGIE_STUDENT":
        return bool(
            re.search(r"Type de contrat\s+job étudiant",body,re.I)
            or STUDENT_SIGNAL.search(title)
        )
    if source=="VDAB_STUDENT_WEB":
        return bool(
            re.search(r"\bStudentenjobs?\b",body,re.I)
            or re.search(r"\bVDAB-vacaturenummer\b",body,re.I) and STUDENT_SIGNAL.search(title+" "+body)
        )
    return False

def _make(source,dr,ds):
    body=clean(html_lib.unescape(ds.get_text(" ",strip=True)))
    h=ds.find("h1") or ds.find("h2")
    title=clean(html_lib.unescape(h.get_text(" ",strip=True) if h else ""))
    if not _eligible(source,title,body,dr.url):
        return None

    objs=_jsonld_jobs(ds)
    obj=objs[0] if objs else {}
    jt=clean(html_lib.unescape(str(obj.get("title") or ""))) if obj else ""
    if jt and len(jt)<=180:title=jt
    desc=clean(html_lib.unescape(str(obj.get("description") or ""))) if obj else ""
    if len(desc)<120:desc=body
    identifier=obj.get("identifier") if obj else None
    if isinstance(identifier,dict):identifier=identifier.get("value")
    ext=clean(identifier) or _hash(dr.url,title)
    default_company={
        "START_PEOPLE_STUDENT":"Start People",
        "SYNERGIE_STUDENT":"Synergie",
        "VDAB_STUDENT_WEB":"VDAB listing",
    }[source]

    job=make_job(
        source=source,
        external_id=ext,
        title=title,
        company=_company(obj,default_company) if obj else default_company,
        location=_location(obj) if obj else "Belgium",
        description=desc,
        url=_canonical_url(dr.url),
        date_published=obj.get("datePosted") if obj else None,
        contract_type="Student",
    )
    setattr(job,"api_target_track","STUDENT_ANY")
    setattr(job,"student_source",True)
    return job

def _listing_pages(source):
    base=PAGES[source]
    if source=="START_PEOPLE_STUDENT":
        return [(base,None),(base,{"page":2})]
    if source=="SYNERGIE_STUDENT":
        return [(base,None),(base,{"page":2})]
    # VDAB: bounded first three result pages despite >1000 available.
    return [(base,None),(base,{"page":2}),(base,{"page":3})]

def collect_student_network(source):
    seen=target=errors=detail_failed=0
    urls=[]
    urlset=set()

    for page_url,params in _listing_pages(source):
        try:
            r=_get(page_url,params=params)
            soup=BeautifulSoup(r.text,"html.parser")
        except Exception as exc:
            errors+=1
            print(source,"LIST ERROR |",params,"|",type(exc).__name__,exc)
            continue
        for a in soup.find_all("a",href=True):
            href=_canonical_url(urljoin(r.url,a.get("href")))
            if href in urlset or not _is_detail(source,href):
                continue
            urlset.add(href);urls.append(href)
        time.sleep(0.25)

    cap={
        "START_PEOPLE_STUDENT":60,
        "SYNERGIE_STUDENT":60,
        "VDAB_STUDENT_WEB":80,
    }[source]

    jobs={}
    for detail_url in urls[:cap]:
        seen+=1
        try:
            dr=_get(detail_url)
            ds=BeautifulSoup(dr.text,"html.parser")
            job=_make(source,dr,ds)
            if not job:continue
            target+=1
            jobs[job.external_id]=job
            time.sleep(0.10)
        except Exception as exc:
            errors+=1;detail_failed+=1
            print(source,"DETAIL ERROR |",detail_url,"|",type(exc).__name__,exc)

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
    print(source,"| candidate_urls=",len(urls),"| seen=",seen,"| kept=",len(jobs),"| errors=",errors)
    return list(jobs.values())

def collect_start_people_student_jobs():
    return collect_student_network("START_PEOPLE_STUDENT")

def collect_synergie_student_jobs():
    return collect_student_network("SYNERGIE_STUDENT")

def collect_vdab_student_web_jobs():
    return collect_student_network("VDAB_STUDENT_WEB")
