"""
JOBHUNTER - YIELD RECOVERY V17

Purpose:
Read actual job-title links more reliably from high-value sources that were
structurally valid in V16 but returned zero useful jobs.

Supported:
- SAINT_LUC
- SNCB_NMBS
- PURATOS
- BPOST
- DANONE_BE
- NORMEC
- ULB_JOBS

No stealth, no anti-bot bypass, no login.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from sources.api_expansion_common import clean, make_job
from sources.source_metrics import publish_source_metrics

VERSION="18.0"
V19_PATCH="19.1"
V20_PATCH="20.0"

PURATOS_SEARCHES=(
    "https://jobs.puratos.com/search/?q=quality&locationsearch=Belgium",
    "https://jobs.puratos.com/search/?q=qc&locationsearch=Belgium",
    "https://jobs.puratos.com/search/?q=laboratory&locationsearch=Belgium",
    "https://jobs.puratos.com/search/?q=data&locationsearch=Belgium",
    "https://jobs.puratos.com/search/?q=analyst&locationsearch=Belgium",
)
BPOST_STUDENT_URL="https://career.bpost.be/fr/offre-d-emploi/jobs-etudiants"

PURATOS_VIEWALL=(
    "https://jobs.puratos.com/viewalljobs/",
    "https://jobs.puratos.com/viewalljobs/50/",
    "https://jobs.puratos.com/viewalljobs/100/",
    "https://jobs.puratos.com/viewalljobs/150/",
)
PURATOS_RAW_JOB=re.compile(
    r"""["'](?P<u>/job/[^"'<>]+/\d+(?:-[A-Za-z_]+)?/?)(?:["'])""",
    re.I,
)
TIMEOUT=30

SESSION=requests.Session()
SESSION.headers.update({
    "User-Agent":"JobHunter/17.0 personal job search; Belgium",
    "Accept-Language":"fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.6",
})

SOURCES={
    "SAINT_LUC":{
        "url":"https://jobs.saintluc.be/offre-de-emploi/liste-offres.aspx",
        "local":True,
        "detail":re.compile(r"/offre-de-emploi/emploi-[^?#]+_\d+\.aspx",re.I),
    },
    "SNCB_NMBS":{
        "url":"https://jobs.belgiantrain.be/fr/search",
        "local":True,
        "detail":re.compile(r"/job/[^?#]+/\d+/?$",re.I),
    },
    "PURATOS":{
        "url":"https://jobs.puratos.com/go/Belgium-%26-HQ_FR/9458001/",
        "local":True,
        "detail":re.compile(r"/job/[^?#]+/\d+(?:-[^/]+)?/?$",re.I),
    },
    "BPOST":{
        "url":"https://career.bpost.be/en/job-search",
        "local":True,
        "detail":re.compile(r"/(?:en|fr|nl)/vacancy/[^/]+/[^/]+/\d+/?$",re.I),
    },
    "DANONE_BE":{
        "url":"https://careers.danone.com/benelux/en/jobs.html",
        "local":False,
        "detail":re.compile(r"/benelux/en/jobs/[^?#]+\.html$",re.I),
    },
    "NORMEC":{
        "url":"https://careers.normecgroup.com/vacancies",
        "local":False,
        "detail":re.compile(r"/vacancies/[^?#]+/?$",re.I),
    },
    "ULB_JOBS":{
        "url":"https://www.ulb.be/fr/offres-d-emploi/offres-demploi-a-lulb-externe",
        "local":True,
        "detail":re.compile(r"/fr/offres-d-emploi/[^?#]+",re.I),
    },
}

STUDENT=re.compile(r"\b(student|étudiant|etudiant|jobstudent|studentenjob|werkstudent)\b",re.I)
INTERNSHIP=re.compile(r"\b(stage|stagiaire|internship|intern\b|trainee)\b",re.I)
SENIOR=re.compile(r"\b(senior|sr\.?|lead|manager|head|director|principal|responsable)\b",re.I)
QC=re.compile(
    r"\b(qc|quality control|quality engineer|quality specialist|quality analyst|"
    r"quality assurance|qa analyst|qa officer|contrôle de qualité|controle de qualite|"
    r"laboratoire|laboratory|laborant|lab technician|technologue de laboratoire|"
    r"microbiolog|chimiste|chemist|analytical technician|hplc|uplc)\b",re.I
)
DATA=re.compile(
    r"\b(data analyst|analyste de donn[ée]es|business intelligence|bi analyst|"
    r"reporting analyst|data analytics)\b",re.I
)
HYBRID=re.compile(
    r"\b(lims|data integrity|quality data|lab systems?|laboratory systems?|"
    r"computerized systems? validation|csv specialist)\b",re.I
)
BELGIUM=re.compile(
    r"\b(belgium|belgique|belgi[ëe]|brussels|bruxelles|groot-bijgaarden|grand-bigard|"
    r"halle|leuven|louvain|li[èe]ge|antwerp|antwerpen|gent|ghent|namur|charleroi|"
    r"jette|woluwe|sint-lambrechts-woluwe|saint-luc)\b",re.I
)
BAD_TITLE=re.compile(
    r"^(more about|search|search results?|all jobs?|jobs?|careers?|vacancies|"
    r"offres d['’]emploi|emploi|sign up|talentpool|open sollicitatie)$",re.I
)

def _hash(*parts):
    raw="|".join(clean(x).lower() for x in parts)
    return hashlib.sha1(raw.encode("utf-8","ignore")).hexdigest()[:22]

def _get(url):
    r=SESSION.get(url,timeout=TIMEOUT,allow_redirects=True)
    r.raise_for_status()
    return r

def _track(title,body=""):
    title=clean(html_lib.unescape(str(title or "")))
    blob=clean(f"{title} {body}")
    if not title or BAD_TITLE.search(title) or INTERNSHIP.search(title):
        return None
    if STUDENT.search(title):
        return "STUDENT_ANY"
    if SENIOR.search(title):
        return None
    if HYBRID.search(blob):
        return "QC_DATA_HYBRID"
    if DATA.search(title):
        return "DATA_JUNIOR_BI"
    if QC.search(title):
        return "QC_PHARMA_LAB"
    return None

def _title_from_detail(soup,fallback=""):
    h=soup.find("h1")
    if h:
        t=clean(html_lib.unescape(h.get_text(" ",strip=True)))
        if t:return t
    # JobPosting title fallback
    for node in soup.find_all("script",attrs={"type":"application/ld+json"}):
        raw=node.string or node.get_text()
        if not raw:continue
        try:
            import json
            obj=json.loads(raw)
        except Exception:
            continue
        stack=list(obj) if isinstance(obj,list) else [obj]
        while stack:
            x=stack.pop()
            if isinstance(x,dict):
                if x.get("@type")=="JobPosting":
                    t=clean(html_lib.unescape(str(x.get("title") or "")))
                    if t:return t
                if isinstance(x.get("@graph"),list):stack.extend(x["@graph"])
    return clean(html_lib.unescape(str(fallback or "")))

def _ulb_text_jobs(soup):
    text=clean(html_lib.unescape(soup.get_text("\n",strip=True)))
    out=[]
    for line in text.split("\n"):
        line=clean(line)
        if not line or len(line)>220:
            continue
        if re.search(r"\b(Type contrat|Temps de travail|Campus|Date de parution|Date limite|Référence)\b",line,re.I):
            continue
        if re.match(r"^(Un[·e]?|Une|Un|Technicien|Technicienne|Analyste|Gestionnaire|Chargé|Chargée)\b",line,re.I):
            out.append(line)
    return out[:80]


def _listing_links(key,soup,base):
    cfg=SOURCES[key]
    out=[]
    seen=set()
    for a in soup.find_all("a",href=True):
        href=urljoin(base,a.get("href"))
        if href in seen or not cfg["detail"].search(urlparse(href).path):
            continue
        seen.add(href)
        title=clean(html_lib.unescape(a.get_text(" ",strip=True)))
        # Keep even if title is weak: detail page can supply the real title.
        out.append((href,title))
    return out[:140]

def _puratos_v19_links():
    out=[]
    seen=set()
    errors=0
    urls=list(PURATOS_VIEWALL)+list(PURATOS_SEARCHES)
    for url in urls:
        try:
            r=_get(url)
            soup=BeautifulSoup(r.text,"html.parser")
            for a in soup.find_all("a",href=True):
                href=urljoin(r.url,a.get("href"))
                if href in seen or not SOURCES["PURATOS"]["detail"].search(urlparse(href).path):
                    continue
                seen.add(href)
                title=clean(html_lib.unescape(a.get_text(" ",strip=True)))
                out.append((href,title))
            raw=html_lib.unescape(r.text or "")
            for mm in PURATOS_RAW_JOB.finditer(raw):
                href=urljoin(r.url,mm.group("u"))
                if href in seen:
                    continue
                seen.add(href)
                out.append((href,""))
        except Exception:
            errors+=1
        time.sleep(0.10)
    return out[:220],errors

def _bpost_student_job():
    try:
        r=_get(BPOST_STUDENT_URL)
        soup=BeautifulSoup(r.text,"html.parser")
        body=clean(html_lib.unescape(soup.get_text(" ",strip=True)))
        if not re.search(r"\b(job étudiant|jobs étudiants|étudiant|etudiant)\b",body,re.I):
            return None
        job=make_job(
            source="BPOST",
            external_id=_hash("BPOST",BPOST_STUDENT_URL,"student"),
            title="Jobs étudiants bpost",
            company="bpost",
            location="Belgium",
            description=body,
            url=r.url,
            contract_type="Student",
        )
        setattr(job,"api_target_track","STUDENT_ANY")
        setattr(job,"student_source",True)
        return job
    except Exception:
        return None


def collect_priority_source_jobs(key):
    key=str(key or "").upper()
    cfg=SOURCES.get(key)
    if not cfg:
        return None

    seen=target=errors=0
    jobs={}
    try:
        if key=="PURATOS":
            links,pre_errors=_puratos_v19_links()
            errors+=pre_errors
            listing=_get(cfg["url"])
            soup=BeautifulSoup(listing.text,"html.parser")
        else:
            listing=_get(cfg["url"])
            soup=BeautifulSoup(listing.text,"html.parser")
            links=_listing_links(key,soup,listing.url)
        ulb_text_rows=_ulb_text_jobs(soup) if key=="ULB_JOBS" else []
    except Exception as exc:
        publish_source_metrics(key,{
            "seen":0,"target_title":0,"non_target":0,"detail_ok":0,"detail_failed":1,
            "geography_accepted":0,"geography_rejected":0,"geography_unknown":0,
            "language_rejected":0,"converted":0,"persisted":None,"errors":1,
        })
        print(key,"V17 LIST ERROR |",type(exc).__name__,exc)
        return []

    if key=="ULB_JOBS":
        for title in ulb_text_rows:
            seen+=1
            track=_track(title,"")
            if not track:
                continue
            ext=_hash(key,listing.url,title)
            job=make_job(
                source=key,external_id=ext,title=title,
                company="ULB",location="Brussels, Belgium",
                description=title,url=listing.url,
                contract_type="Student" if track=="STUDENT_ANY" else None,
            )
            setattr(job,"api_target_track",track)
            if track=="STUDENT_ANY":setattr(job,"student_source",True)
            jobs[ext]=job;target+=1

    for href,list_title in links:
        seen+=1
        # If listing title is clearly unrelated, skip the expensive detail fetch.
        preliminary=_track(list_title)
        if list_title and len(list_title)>5 and preliminary is None:
            # For Saint-Luc/SNCB titles are reliable; for other sources detail may improve title.
            if key in {"SAINT_LUC","SNCB_NMBS"}:
                continue

        try:
            dr=_get(href)
            ds=BeautifulSoup(dr.text,"html.parser")
            body=clean(html_lib.unescape(ds.get_text(" ",strip=True)))
            title=_title_from_detail(ds,list_title)
            track=_track(title,body)
            if not track:
                continue

            if not cfg["local"] and track!="STUDENT_ANY":
                if not BELGIUM.search(body[:9000]+" "+title):
                    continue

            ext=_hash(key,dr.url,title)
            job=make_job(
                source=key,
                external_id=ext,
                title=title,
                company=key.replace("_"," ").title(),
                location="Belgium",
                description=body,
                url=dr.url,
                contract_type="Student" if track=="STUDENT_ANY" else None,
            )
            setattr(job,"api_target_track",track)
            if track=="STUDENT_ANY":
                setattr(job,"student_source",True)
            jobs[ext]=job
            target+=1
            time.sleep(0.10)
        except Exception as exc:
            errors+=1
            print(key,"V17 DETAIL ERROR |",href,"|",type(exc).__name__,exc)

    if key=="BPOST":
        student=_bpost_student_job()
        if student:
            jobs[getattr(student,"external_id",None) or student.url]=student
            target+=1

    publish_source_metrics(key,{
        "seen":seen,"target_title":target,"non_target":max(0,seen-target),
        "detail_ok":len(jobs),"detail_failed":errors,
        "geography_accepted":len(jobs),"geography_rejected":0,"geography_unknown":0,
        "language_rejected":0,"converted":len(jobs),"persisted":None,"errors":errors,
    })
    print(key,"| V17 | detail_links=",len(links),"| kept=",len(jobs),"| errors=",errors)
    return list(jobs.values())
