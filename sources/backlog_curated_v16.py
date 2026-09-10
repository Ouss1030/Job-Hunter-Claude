"""
JOBHUNTER - CURATED RECOVERY V16

Curated second-stage recovery for high-value backlog sources whose old URLs
or generic discovery failed.

Activation rule is stronger than "career page exists":
- listing page must be reachable, AND
- at least one concrete job detail must be structurally validated
  (JSON-LD JobPosting OR plausible detail page with apply signal).

No stealth, no bypass, no IP rotation.
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from sources.backlog_validator_v14 import (
    SESSION, BLOCK_STATUS, CONFIG_PATH, canonical, load_backlog, save_backlog,
    now_iso, _jsonld_jobs, _detect_ats,
)

VERSION="16.0"
TIMEOUT=25

OVERRIDES={
    "SIRRIS":"https://recruitment.sirris.be/",
    "PURATOS":"https://jobs.puratos.com/go/Belgium-%26-HQ_FR/9458001/",
    "COLRUYT":"https://jobs.colruytgroup.com/",
    "DELHAIZE":"https://jobs.delhaize.be/be/fr/search-results",
    "DANONE_BE":"https://careers.danone.com/benelux/en/jobs.html",
    "SCIENSANO_RESEARCH":"https://www.sciensano.be/fr/travailler-faire-un-stage-chez-sciensano/mes-opportunites-demploi",
    "ULB_JOBS":"https://www.ulb.be/fr/travailler-et-collaborer/offres-d-emploi",
    "BPOST":"https://career.bpost.be/en",
    "SNCB_NMBS":"https://jobs.belgiantrain.be/fr/search",
    "ABSOLUTE_JOBS":"https://www.absolutejobs.be/EN/jobs",
    "ACTIEF_INTERIM":"https://www.actief.be/nl/",
    "BRIGHT_PLUS":"https://www.brightplus.be/en/",
    "HAYS_BE":"https://www.hays.be/en/boost-your-career",
    "UNIQUE_BE":"https://www.unique.be/nl/",
    "BARRY_CALLEBAUT":"https://jobs.barry-callebaut.com/",
    "NORMEC":"https://careers.normecgroup.com/vacancies",
    "SAINT_LUC":"https://jobs.saintluc.be/offre-de-emploi/liste-toutes-offres.aspx",
    "SGS":"https://www.sgs.com/en-be/our-company/careers-at-sgs/job-opportunities",
}

COVERED_BY_PARENT={
    "ACTIRIS_STUDENT":"ACTIRIS",
    "ADECCO_STUDENT":"ADECCO",
    "JOBAT_STUDENT":"JOBAT",
    "SYNERGIE_STUDENT":"SYNERGIE_STUDENT",
    "VIVAQUA":"TALENT_BRUSSELS",
}

DETAIL_HINTS={
    "SIRRIS": re.compile(r"(?:vacanc|job|position)",re.I),
    "PURATOS": re.compile(r"/job/|/jobsearch/|/search/",re.I),
    "COLRUYT": re.compile(r"/vacature/|/job/|/jobs?/",re.I),
    "DELHAIZE": re.compile(r"/job/|/jobs/|/vacature/|/offre",re.I),
    "DANONE_BE": re.compile(r"/job/|/jobs/",re.I),
    "SCIENSANO_RESEARCH": re.compile(r"(?:job|emploi|vacature|offre)",re.I),
    "ULB_JOBS": re.compile(r"(?:emploi|job|vacature|recrut)",re.I),
    "BPOST": re.compile(r"/job/|/jobs/|vacanc",re.I),
    "SNCB_NMBS": re.compile(r"/job/|/search/|/jobdetail",re.I),
    "ABSOLUTE_JOBS": re.compile(r"/jobs?[-/]|/vacature|/job/",re.I),
    "ACTIEF_INTERIM": re.compile(r"/vacature|/job/|/jobs/",re.I),
    "BRIGHT_PLUS": re.compile(r"/job/|/jobs/|/vacature",re.I),
    "HAYS_BE": re.compile(r"/job/|/jobs/|/vacature",re.I),
    "UNIQUE_BE": re.compile(r"/vacature|/job/|/jobs/",re.I),
    "BARRY_CALLEBAUT": re.compile(r"/job/|/search/",re.I),
    "NORMEC": re.compile(r"/vacanc|/jobs?/",re.I),
    "SAINT_LUC": re.compile(r"/offre-de-emploi/",re.I),
    "SGS": re.compile(r"/job/|/jobs/|vacanc",re.I),
}

NAV_LABEL=re.compile(
    r"^(home|jobs?|careers?|vacatures?|all jobs|toutes les offres|"
    r"offres d['’]emploi|search|find jobs?|job opportunities)$",
    re.I,
)
APPLY=re.compile(r"\b(apply|postuler|solliciteer|candidater|je postule|apply now)\b",re.I)

def _get(url):
    return SESSION.get(url,timeout=TIMEOUT,allow_redirects=True)

def _detail_links(key,base,soup,limit=80):
    pat=DETAIL_HINTS.get(key,re.compile(r"/job/|/jobs/|/vacature|/offre",re.I))
    out=[];seen=set()
    for a in soup.find_all("a",href=True):
        href=canonical(urljoin(base,a.get("href")))
        label=" ".join(a.get_text(" ",strip=True).split())
        if not href.startswith(("http://","https://")) or href in seen:
            continue
        seen.add(href)
        if NAV_LABEL.fullmatch(label or ""):
            continue
        blob=urlparse(href).path+" "+label
        if pat.search(blob):
            # Avoid the listing page itself.
            if canonical(href)==canonical(base):
                continue
            out.append((href,label))
        if len(out)>=limit: break
    return out

def _validate_detail(url,label=""):
    try:
        r=_get(url)
    except Exception as exc:
        return {"ok":False,"reason":f"{type(exc).__name__}: {exc}","url":url}
    if r.status_code in BLOCK_STATUS:
        return {"ok":False,"blocked":True,"reason":f"HTTP {r.status_code}","url":canonical(r.url)}
    if r.status_code>=400:
        return {"ok":False,"reason":f"HTTP {r.status_code}","url":canonical(r.url)}
    soup=BeautifulSoup(r.text or "","html.parser")
    objs=_jsonld_jobs(soup)
    h=soup.find("h1") or soup.find("h2")
    title=" ".join((h.get_text(" ",strip=True) if h else label or "").split())
    body=" ".join(soup.get_text(" ",strip=True).split())
    if objs:
        return {"ok":True,"reason":"JSONLD_JOBPOSTING","url":canonical(r.url),"title":title}
    if title and len(body)>=500 and APPLY.search(body):
        return {"ok":True,"reason":"DETAIL_APPLY_SIGNAL","url":canonical(r.url),"title":title}
    return {"ok":False,"reason":"NO_DETAIL_CONTRACT","url":canonical(r.url),"title":title}

def validate_curated(existing_keys,progress=None,pause_seconds=0.45):
    rows=load_backlog(include_all=True)
    bykey={str(r.get("key") or "").upper():r for r in rows}
    results=[]

    # Record semantic coverage without creating duplicate source specs.
    for key,parent in COVERED_BY_PARENT.items():
        row=bykey.get(key)
        if row and not row.get("active"):
            row["probe_status"]="COVERED_BY_PARENT"
            row["probe_reason"]=f"V16: student/general coverage already provided by production source {parent}."
            row["covered_by"]=parent
            results.append({"key":key,"status":"COVERED_BY_PARENT","parent":parent})

    items=[(k,u) for k,u in OVERRIDES.items() if k in bykey and not bykey[k].get("active")]
    total=len(items)

    for i,(key,url) in enumerate(items,1):
        if progress: progress(i,total,key,url)
        row=bykey[key]
        attempt={"key":key,"override":url,"status":"PENDING","detail_checks":[]}
        try:
            r=_get(url)
        except Exception as exc:
            row["probe_status"]="PENDING_CURATED_FETCH"
            row["probe_reason"]=f"V16 override fetch failed: {type(exc).__name__}: {exc}"
            attempt["status"]="PENDING_CURATED_FETCH";attempt["reason"]=row["probe_reason"]
            results.append(attempt);continue

        if r.status_code in BLOCK_STATUS:
            row["probe_status"]="SKIPPED_BLOCKED"
            row["probe_reason"]=f"V16 HTTP {r.status_code}; no bypass attempted."
            attempt["status"]="SKIPPED_BLOCKED";attempt["reason"]=row["probe_reason"]
            results.append(attempt);continue
        if r.status_code>=400:
            row["probe_status"]="PENDING_CURATED_HTTP"
            row["probe_reason"]=f"V16 override HTTP {r.status_code}"
            attempt["status"]="PENDING_CURATED_HTTP";attempt["reason"]=row["probe_reason"]
            results.append(attempt);continue

        soup=BeautifulSoup(r.text or "","html.parser")
        embedded=len(_jsonld_jobs(soup))
        links=_detail_links(key,r.url,soup)
        ats=_detect_ats(r.url+"\n"+(r.text or "")[:700000])
        attempt.update({
            "listing_url":canonical(r.url),"embedded_jobs":embedded,
            "detail_links":len(links),"ats":ats,
        })

        valid_detail=None
        for href,label in links[:4]:
            check=_validate_detail(href,label)
            attempt["detail_checks"].append(check)
            if check.get("ok"):
                valid_detail=check;break
            if check.get("blocked"):break
            time.sleep(max(0.0,float(pause_seconds)))

        # Embedded JobPosting itself is already a concrete detail contract.
        structurally_valid = embedded>0 or valid_detail is not None
        if structurally_valid:
            row["active"]=True
            row["status"]="ACTIVE"
            row["health"]="HEALTHY"
            row["collection_mode"]="LIVE"
            row["collector_module"]="sources.backlog_validator_v14"
            row["collector_name"]="collect_backlog_source_jobs"
            row["url"]=url
            row["validated_url"]=canonical(r.url)
            row["probe_status"]="ACTIVATED"
            row["probe_reason"]=(
                f"V16 curated structural validation: embedded={embedded}, "
                f"detail_links={len(links)}, detail={valid_detail.get('reason') if valid_detail else 'EMBEDDED'}, "
                f"ats={ats or 'NONE'}"
            )
            row["v16_validated_at"]=now_iso()
            attempt["status"]="ACTIVATED"
        else:
            row["url"]=url
            row["probe_status"]="PENDING_CURATED_NO_DETAIL"
            row["probe_reason"]=(
                f"V16 official listing reachable but no validated detail page: "
                f"embedded={embedded}, links={len(links)}, ats={ats or 'NONE'}"
            )
            attempt["status"]="PENDING_CURATED_NO_DETAIL"
            attempt["reason"]=row["probe_reason"]

        results.append(attempt)
        time.sleep(max(0.0,float(pause_seconds)))

    save_backlog(rows)
    return rows,results
