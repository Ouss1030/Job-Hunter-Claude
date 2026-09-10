"""
JOBHUNTER - STUDENT SOURCES V2

Strict Belgian student-job collectors:
- Student.be
- StudentJob.be
- Randstad Student

Quality rule:
Only actual detail pages are converted.
Navigation, login, category/search/result pages are never jobs.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from sources.api_expansion_common import clean, make_job
from sources.source_metrics import publish_source_metrics

VERSION="2.0"
TIMEOUT=30
SESSION=requests.Session()
SESSION.headers.update({
    "User-Agent":"JobHunter/12.0 personal job search",
    "Accept-Language":"fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.6",
})

PAGES={
    "STUDENT_BE":"https://www.student.be/en/be/student-jobs/",
    "STUDENTJOB_BE":"https://fr.studentjob.be/job-etudiant/bruxelles",
    "RANDSTAD_STUDENT":"https://www.randstad.be/fr/candidats/jobs/jt-etudiant/",
}

LOW_VALUE=re.compile(
    r"\b(sondage|sondages|enqu[eê]te|enquêtes|survey|surveys|"
    r"paid games?|jeux en ligne|online games?|jeux mobiles|mobile games?)\b",
    re.I,
)
INTERNSHIP=re.compile(
    r"\b(stage|stagiaire|internship|intern\b|trainee\b|apprentice)\b",
    re.I,
)
STUDENT_SIGNAL=re.compile(
    r"\b(job étudiant|job etudiant|student job|studentenjob|jobstudent|"
    r"job étudiant[e]?|étudiant[e]?|etudiant[e]?|werkstudent|student worker|"
    r"student contract|contrat étudiant|contrat etudiant|jobs liés aux études)\b",
    re.I,
)

DETAIL_PATTERNS={
    "STUDENT_BE": re.compile(r"^/(?:en|fr|nl)/student-jobs/[^/]+/?$",re.I),
    "STUDENTJOB_BE": re.compile(r"^/offre/\d+-[^/]+/?$",re.I),
    "RANDSTAD_STUDENT": re.compile(
        r"^/fr/candidats/jobs/[^/]+_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/?$",
        re.I,
    ),
}

def _hash(*parts):
    raw="|".join(clean(x).lower() for x in parts)
    return hashlib.sha1(raw.encode("utf-8","ignore")).hexdigest()[:22]

def _get(url):
    r=SESSION.get(url,timeout=TIMEOUT,allow_redirects=True)
    r.raise_for_status()
    return r

def _is_detail_url(source,url):
    try:
        path=urlparse(url).path
    except Exception:
        return False
    return bool(DETAIL_PATTERNS[source].match(path))

def _jsonld_jobs(soup):
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

def _loc(obj):
    item=obj.get("jobLocation")
    items=item if isinstance(item,list) else [item]
    vals=[]
    for x in items:
        if not isinstance(x,dict):
            continue
        a=x.get("address") or {}
        if isinstance(a,dict):
            vals.extend(str(a.get(k) or "") for k in (
                "addressLocality","addressRegion","postalCode","addressCountry"
            ))
    return clean(" ".join(vals))

def _company(obj,default):
    h=obj.get("hiringOrganization") or {}
    if isinstance(h,dict):
        v=clean(h.get("name"))
        if v:
            return v
    return default

def _eligible_detail(source,title,body,url):
    if not _is_detail_url(source,url):
        return False
    blob=clean(f"{title} {body}")
    if not title or LOW_VALUE.search(blob) or INTERNSHIP.search(title):
        return False

    if source=="STUDENT_BE":
        # Student.be detail pages explicitly identify the posting as "Student job".
        return bool(
            re.search(r"\bStudent job\b",body,re.I)
            or STUDENT_SIGNAL.search(title)
        )

    if source=="STUDENTJOB_BE":
        # Real offer pages use /offre/<numeric-id>-<slug> and expose the contract.
        return bool(
            re.search(r"Type de Contrat\s+Job étudiant",body,re.I)
            or re.search(r"Type de Contrat.{0,120}Job étudiant",body,re.I|re.S)
            or STUDENT_SIGNAL.search(title)
        )

    if source=="RANDSTAD_STUDENT":
        # Real Randstad pages use a UUID detail URL and include student contract text.
        return bool(
            re.search(r"\b(?:mission d'intérim,\s*)?étudiant\b",body,re.I)
            or re.search(r"\bjobs liés aux études\b",body,re.I)
            or STUDENT_SIGNAL.search(title)
        )

    return False

def _make_from_page(source,dr,ds):
    body=clean(ds.get_text(" ",strip=True))
    h=ds.find("h1") or ds.find("h2")
    title=clean(h.get_text(" ",strip=True) if h else "")
    if not _eligible_detail(source,title,body,dr.url):
        return None

    objs=_jsonld_jobs(ds)
    chosen=objs[0] if objs else {}
    json_title=clean(chosen.get("title")) if chosen else ""
    if json_title and len(json_title)<=180:
        title=json_title

    company=_company(chosen,source.replace("_"," ").title()) if chosen else source.replace("_"," ").title()
    location=_loc(chosen) if chosen else ""
    description=clean(chosen.get("description")) if chosen else ""
    if len(description)<120:
        description=body

    identifier=chosen.get("identifier") if chosen else None
    if isinstance(identifier,dict):
        identifier=identifier.get("value")
    ext=clean(identifier) or _hash(dr.url,title)

    job=make_job(
        source=source,
        external_id=ext,
        title=title,
        company=company,
        location=location or "Belgium",
        description=description,
        url=dr.url,
        date_published=chosen.get("datePosted") if chosen else None,
        contract_type="Student",
    )
    setattr(job,"api_target_track","STUDENT_ANY")
    setattr(job,"student_source",True)
    return job

def collect_student_source(source):
    url=PAGES[source]
    seen=target=errors=detail_failed=0
    jobs={}

    try:
        r=_get(url)
        soup=BeautifulSoup(r.text,"html.parser")
    except Exception as exc:
        publish_source_metrics(source,{
            "seen":0,"target_title":0,"non_target":0,
            "detail_ok":0,"detail_failed":1,
            "geography_accepted":0,"geography_rejected":0,"geography_unknown":0,
            "language_rejected":0,"converted":0,"persisted":None,"errors":1,
        })
        print(source,"LIST ERROR |",type(exc).__name__,exc)
        return []

    links=[]
    seen_urls=set()
    for a in soup.find_all("a",href=True):
        href=urljoin(r.url,a.get("href"))
        if href in seen_urls or not _is_detail_url(source,href):
            continue
        seen_urls.add(href)
        links.append(href)

    cap={"STUDENT_BE":120,"STUDENTJOB_BE":80,"RANDSTAD_STUDENT":50}[source]

    for detail_url in links[:cap]:
        seen+=1
        try:
            dr=_get(detail_url)
            ds=BeautifulSoup(dr.text,"html.parser")
            job=_make_from_page(source,dr,ds)
            if not job:
                continue
            target+=1
            jobs[job.external_id]=job
            time.sleep(0.12)
        except Exception as exc:
            errors+=1
            detail_failed+=1
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
    print(source,"| v2 | detail_links=",len(links),"| seen=",seen,"| kept=",len(jobs),"| errors=",errors)
    return list(jobs.values())

def collect_student_be_jobs(): return collect_student_source("STUDENT_BE")
def collect_studentjob_be_jobs(): return collect_student_source("STUDENTJOB_BE")
def collect_randstad_student_jobs(): return collect_student_source("RANDSTAD_STUDENT")
