"""
JOBHUNTER - WORKDAY PHARMA ACTIVATION V1

Six confirmed public Workday job boards:
- Air Liquide
- Bristol Myers Squibb
- Galderma
- Amgen
- BeiGene / BeOne
- Elanco

Tracks:
- QC_PHARMA_LAB
- DATA_JUNIOR_BI
- QC_DATA_HYBRID

No authentication, no anti-bot bypass, no browser automation.
"""

from __future__ import annotations

import html as html_lib
import re
import time
from urllib.parse import urljoin

import requests

from sources.api_expansion_common import clean, classify_target_title, make_job
from sources.belgium_locations import classify_belgium_location
from sources.source_metrics import publish_source_metrics

TIMEOUT=35
UA="JobHunter/10.0 personal job search"
SESSION=requests.Session()
SESSION.headers.update({
    "User-Agent":UA,
    "Accept":"application/json, text/plain, */*",
    "Content-Type":"application/json",
    "Accept-Language":"en-BE,en;q=0.9,fr;q=0.8,nl;q=0.5",
})

EMPLOYERS={'AIR_LIQUIDE': {'label': 'Air Liquide Belgium', 'host': 'airliquidehr.wd3.myworkdayjobs.com', 'tenant': 'airliquidehr', 'site': 'AirLiquideExternalCareer', 'company': 'Air Liquide'}, 'BMS': {'label': 'Bristol Myers Squibb Belgium', 'host': 'bristolmyerssquibb.wd5.myworkdayjobs.com', 'tenant': 'bristolmyerssquibb', 'site': 'BMS', 'company': 'Bristol Myers Squibb'}, 'GALDERMA': {'label': 'Galderma Belgium', 'host': 'galderma.wd3.myworkdayjobs.com', 'tenant': 'galderma', 'site': 'External', 'company': 'Galderma'}, 'AMGEN': {'label': 'Amgen Belgium', 'host': 'amgen.wd1.myworkdayjobs.com', 'tenant': 'amgen', 'site': 'Careers', 'company': 'Amgen'}, 'BEIGENE': {'label': 'BeiGene / BeOne Belgium', 'host': 'beigene.wd5.myworkdayjobs.com', 'tenant': 'beigene', 'site': 'BeiGene', 'company': 'BeiGene / BeOne Medicines'}, 'ELANCO': {'label': 'Elanco Belgium', 'host': 'elanco.wd5.myworkdayjobs.com', 'tenant': 'elanco', 'site': 'External_Career', 'company': 'Elanco'}}

SENIOR=re.compile(r"\b(senior|sr\.?|lead|manager|head|director|principal|staff|supervisor|vice president|vp)\b",re.I)
INTERNSHIP=re.compile(r"\b(intern|internship|stage|student|apprentice|trainee)\b",re.I)
DATA_TITLE=re.compile(r"\b(data|business intelligence|bi)\b.*\b(analyst|analytics)\b|\b(analyst|analytics)\b.*\b(data|business intelligence|bi)\b",re.I)
JUNIOR_SIGNAL=re.compile(r"\b(junior|graduate|entry[\s-]?level|starter|first\s+job|0\s*[-–]\s*2\s+years?|1\s*[-–]\s*2\s+years?|less\s+than\s+2\s+years?)\b",re.I)
HYBRID=re.compile(r"\b(lims|data integrity|quality data|digital quality|lab digitali[sz]ation|computerized systems? validation|csv specialist|quality systems? analyst|laboratory systems?)\b",re.I)
QC_EXTRA=re.compile(r"\b(qc|quality control|laboratory|laboratoire|lab technician|laborant|microbiology|microbiologie|analytical technician|quality technician)\b",re.I)
BELGIUM_HINT=re.compile(r"\b(belgium|belgique|belgi[ëe]|brussels|bruxelles|braine|die?gem|antwerp|antwerpen|wavre|rixensart|puurs|beerse|lessines|zaventem|li[èe]ge)\b",re.I)

def _track(title:str,description:str)->str|None:
    title=clean(title)
    blob=clean(f"{title} {description}")
    if not title or SENIOR.search(title) or INTERNSHIP.search(title):
        return None
    base=classify_target_title(title)
    if base:
        return base
    if HYBRID.search(blob):
        return "QC_DATA_HYBRID"
    if DATA_TITLE.search(title):
        exp=re.search(r"\b([3-9]|[1-9]\d)\+?\s+years?\b",blob,re.I)
        if JUNIOR_SIGNAL.search(blob) or not exp:
            return "DATA_JUNIOR_BI"
    if QC_EXTRA.search(title) and re.search(r"\b(qc|quality|laboratory|lab|microbio|analyt)\b",blob,re.I):
        return "QC_PHARMA_LAB"
    return None

def _geo_ok(location:str)->bool:
    raw=clean(location)
    if BELGIUM_HINT.search(raw):
        return True
    try:
        decision=classify_belgium_location(raw)
        status=str(getattr(decision.status,"value",decision.status)).upper()
        return status.endswith("BELGIUM")
    except Exception:
        return False

def _post_jobs(cfg:dict,offset:int,limit:int=20)->dict:
    url=f"https://{cfg['host']}/wday/cxs/{cfg['tenant']}/{cfg['site']}/jobs"
    payload={
        "appliedFacets":{},
        "limit":limit,
        "offset":offset,
        "searchText":"",
    }
    r=SESSION.post(url,json=payload,timeout=TIMEOUT)
    r.raise_for_status()
    return r.json() or {}

def _detail(cfg:dict,external_path:str)->dict:
    path=str(external_path or "")
    if not path.startswith("/"):
        path="/"+path
    url=f"https://{cfg['host']}/wday/cxs/{cfg['tenant']}/{cfg['site']}{path}"
    r=SESSION.get(url,timeout=TIMEOUT)
    r.raise_for_status()
    return r.json() or {}

def collect_workday_employer(key:str, source_override:str|None=None)->list:
    cfg=EMPLOYERS[key]
    source=source_override or key
    seen=target=errors=detail_failed=geo_rejected=0
    jobs={}
    offset=0
    limit=20

    for _page in range(12):
        try:
            payload=_post_jobs(cfg,offset,limit)
        except Exception as exc:
            errors+=1
            print(source,"LIST ERROR |",type(exc).__name__,exc)
            break

        rows=payload.get("jobPostings") or []
        if not rows:
            break

        for row in rows:
            seen+=1
            list_title=clean(row.get("title"))
            list_location=clean(row.get("locationsText"))
            external_path=clean(row.get("externalPath"))
            if not external_path:
                continue

            # Belgium-first: don't fetch details of obviously foreign rows.
            if list_location and not _geo_ok(list_location):
                geo_rejected+=1
                continue

            rough_track=_track(list_title,"")
            if not rough_track and not (
                DATA_TITLE.search(list_title or "") or
                HYBRID.search(list_title or "") or
                QC_EXTRA.search(list_title or "")
            ):
                continue

            try:
                detail=_detail(cfg,external_path)
                info=detail.get("jobPostingInfo") or {}
                title=clean(info.get("title")) or list_title
                location=clean(info.get("location")) or list_location
                description=clean(html_lib.unescape(str(info.get("jobDescription") or "")))
                track=_track(title,description)
                if not track:
                    continue
                target+=1
                if not _geo_ok(location):
                    geo_rejected+=1
                    continue

                ext=clean(info.get("jobReqId")) or clean(row.get("bulletFields",[""])[0]) or external_path
                external_url=clean(info.get("externalUrl"))
                if not external_url:
                    external_url=f"https://{cfg['host']}/en-US/{cfg['site']}{external_path}"

                job=make_job(
                    source=source,
                    external_id=ext,
                    title=title,
                    company=cfg["company"],
                    location=location or "Belgium",
                    description=description,
                    url=external_url,
                    date_published=info.get("startDate"),
                )
                setattr(job,"api_target_track",track)
                jobs[ext]=job
                time.sleep(0.12)
            except Exception as exc:
                errors+=1
                detail_failed+=1
                print(source,"DETAIL ERROR |",external_path,"|",type(exc).__name__,exc)

        total=int(payload.get("total") or 0)
        offset+=limit
        if offset>=total:
            break
        time.sleep(0.25)

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
    print(source,"| seen=",seen,"| target=",target,"| kept=",len(jobs),"| geo_rejected=",geo_rejected,"| errors=",errors)
    return list(jobs.values())

def collect_air_liquide_jobs(): return collect_workday_employer("AIR_LIQUIDE")
def collect_bms_jobs(): return collect_workday_employer("BMS")
def collect_galderma_jobs(): return collect_workday_employer("GALDERMA")
def collect_amgen_jobs(): return collect_workday_employer("AMGEN", source_override="AMGEN_WORKDAY")
def collect_beigene_jobs(): return collect_workday_employer("BEIGENE")
def collect_elanco_jobs(): return collect_workday_employer("ELANCO")
