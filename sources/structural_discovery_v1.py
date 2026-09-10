"""
JOBHUNTER - STRUCTURAL SOURCE DISCOVERY V1

Read-only discovery utilities.
No DB writes. No anti-bot bypass.

1. Discover pharma.be member companies and websites.
2. Detect public ATS fingerprints on employer sites.
3. Discover sitemap / JSON-LD JobPosting hints.
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

UA="JobHunter/9.0 personal job search"
TIMEOUT=25
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":UA,"Accept-Language":"fr-BE,fr;q=0.9,en;q=0.8"})

PHARMA_MEMBERS="https://pharma.be/fr/a-propos-de-nous/membres"

ATS_PATTERNS={
    "WORKDAY":re.compile(r"myworkdayjobs\.com|/wday/cxs/",re.I),
    "GREENHOUSE":re.compile(r"greenhouse\.io|boards\.greenhouse",re.I),
    "LEVER":re.compile(r"lever\.co",re.I),
    "RECRUITEE":re.compile(r"recruitee\.com",re.I),
    "SMARTRECRUITERS":re.compile(r"smartrecruiters\.com",re.I),
    "JOBTOOLZ":re.compile(r"jobtoolz",re.I),
    "TEAMTAILOR":re.compile(r"teamtailor\.com",re.I),
    "PERSONIO":re.compile(r"personio\.(de|com)|jobs\.personio",re.I),
    "ASHBY":re.compile(r"ashbyhq\.com",re.I),
    "SUCCESSFACTORS":re.compile(r"successfactors|career\d*\.successfactors",re.I),
    "TALENTSOFT":re.compile(r"talentsoft",re.I),
}

CAREER_PATHS=("/jobs","/careers","/career","/emploi","/vacatures","/jobs-and-careers","/join-us","/werken-bij")

def _get(url, **kwargs):
    r=SESSION.get(
        url,
        timeout=TIMEOUT,
        allow_redirects=True,
        **kwargs,
    )
    r.raise_for_status()
    return r

def discover_pharma_be_members(max_pages:int=10)->list[dict]:
    """
    Discover pharma.be member companies.

    pharma.be currently exposes member pages with ?page=N pagination.
    We collect company heading + external website + address text, deduplicate,
    and keep Belgian members first while still preserving foreign members in
    the output for transparency.
    """
    out={}
    for page in range(max(1,max_pages)):
        try:
            r=_get(PHARMA_MEMBERS,params={"page":page})
        except Exception as exc:
            print("PHARMA.BE PAGE ERROR |",page,"|",type(exc).__name__,exc)
            continue

        soup=BeautifulSoup(r.text,"html.parser")
        headings=soup.find_all(["h2","h3"])
        page_hits=0

        for heading in headings:
            name=" ".join(heading.stripped_strings).strip()
            if not name or len(name)>180:
                continue

            card=heading
            for _ in range(7):
                parent=getattr(card,"parent",None)
                if not parent:
                    break
                card=parent
                # stop once the block contains both heading text and enough body/link material
                if card.find("a",href=True) and len(" ".join(card.stripped_strings))>len(name)+10:
                    break

            website=None
            body=""
            if card:
                body=" ".join(card.stripped_strings)
                for a in card.find_all("a",href=True):
                    href=urljoin(r.url,a.get("href"))
                    host=urlparse(href).netloc.lower()
                    if href.startswith("http") and host and "pharma.be" not in host:
                        # Ignore social/share/utility hosts.
                        if any(x in host for x in ("facebook.com","linkedin.com","twitter.com","x.com","youtube.com")):
                            continue
                        website=href
                        break

            if not website:
                continue

            country="BELGIUM" if re.search(r"\b(Belgique|België|Belgium)\b",body,re.I) else "OTHER_OR_UNKNOWN"
            key=(name.lower(),urlparse(website).netloc.lower())
            out[key]={
                "company":name,
                "website":website,
                "country_class":country,
                "source":"pharma.be",
                "page":page,
            }
            page_hits+=1

        print("PHARMA.BE PAGE |",page,"| members=",page_hits)
        # Stop after two consecutive effectively empty pages is handled naturally by max_pages.
        time.sleep(0.35)

    rows=sorted(out.values(),key=lambda x:(x["country_class"]!="BELGIUM",x["company"].lower()))
    return rows


def detect_ats_from_html(html:str)->list[str]:
    return [name for name,rx in ATS_PATTERNS.items() if rx.search(html or "")]

def inspect_employer_site(url:str)->dict:
    result={
        "website":url,
        "status":"UNKNOWN",
        "ats":[],
        "career_url":None,
        "jsonld_jobposting":False,
        "tested_paths":[],
    }
    try:
        r=_get(url)
        html=r.text
        result["status"]="HOME_OK"
        result["ats"]=detect_ats_from_html(html+" "+r.url)
        if '"JobPosting"' in html or "'JobPosting'" in html:
            result["jsonld_jobposting"]=True

        soup=BeautifulSoup(html,"html.parser")
        candidates=[]
        for a in soup.find_all("a",href=True):
            label=" ".join(a.stripped_strings).lower()
            href=urljoin(r.url,a.get("href"))
            if any(w in label for w in ("career","careers","jobs","emploi","vacature","werken","join us","join-us")):
                candidates.append(href)

        # Add common paths only after discovered links.
        origin=f"{urlparse(r.url).scheme}://{urlparse(r.url).netloc}"
        for path in CAREER_PATHS:
            candidates.append(urljoin(origin,path))

        candidates=list(dict.fromkeys(candidates))[:10]
        for candidate in candidates:
            result["tested_paths"].append(candidate)
            try:
                cr=_get(candidate)
            except Exception:
                continue

            blob=cr.text+" "+cr.url
            detected=detect_ats_from_html(blob)
            has_jobposting=('"JobPosting"' in cr.text or "'JobPosting'" in cr.text)
            looks_career=bool(
                detected or has_jobposting or
                re.search(r"\b(job|jobs|career|careers|emploi|vacature|werken)\b",
                          " ".join(BeautifulSoup(cr.text,"html.parser").stripped_strings)[:5000],re.I)
            )
            if looks_career:
                result["career_url"]=cr.url
                result["ats"]=sorted(set(result["ats"]+detected))
                result["jsonld_jobposting"]=result["jsonld_jobposting"] or has_jobposting
                result["status"]="CAREER_OK"
                break
    except Exception as exc:
        result["status"]="ERROR"
        result["error"]=f"{type(exc).__name__}: {exc}"
    return result


def fingerprint_members(members:list[dict],limit:int=25)->list[dict]:
    out=[]
    for item in members[:max(0,limit)]:
        row=dict(item)
        row.update(inspect_employer_site(item["website"]))
        out.append(row)
        time.sleep(0.5)
    return out


def rank_discovered_employers(rows:list[dict])->list[dict]:
    """Rank discovered employers for JobHunter integration."""
    priority_names=(
        "gsk","ucb","takeda","baxter","pfizer","janssen","johnson","roche",
        "novartis","sanofi","abbvie","bristol","merck","biogen","argenx",
        "sterop","trenker","air liquide","ceva","boehringer","galderma",
    )
    ranked=[]
    for row in rows:
        x=dict(row)
        score=0
        name=str(x.get("company") or "").lower()
        if x.get("country_class")=="BELGIUM":
            score+=40
        if any(k in name for k in priority_names):
            score+=30
        if x.get("ats"):
            score+=25
        if x.get("jsonld_jobposting"):
            score+=15
        if x.get("career_url"):
            score+=10
        x["discovery_priority_score"]=score
        ranked.append(x)
    return sorted(ranked,key=lambda x:(-x["discovery_priority_score"],x.get("company","").lower()))
