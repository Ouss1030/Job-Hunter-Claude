from __future__ import annotations

import re
import time
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from sources.api_expansion_common import clean, is_target_title, make_job
from sources.source_metrics import publish_source_metrics

SOURCE_KEY="PROTHYA"
VERSION="2.0"
BASE="https://careers-be.prothya.com/"
DEPARTMENTS=(
    "department-vacancies/quality-control/",
    "department-vacancies/business-automation-it/",
)


def _detail(session,url):
    r=session.get(url,timeout=30)
    r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    h=soup.find(["h1","h2"])
    title=clean(h.get_text(" ",strip=True) if h else "")
    text=clean(soup.get_text(" ",strip=True))
    return title,text


def collect_prothya_jobs() -> list:
    session=requests.Session()
    session.headers.update({"User-Agent":"JobHunter/7.0 personal job search","Accept-Language":"fr-BE,fr;q=0.9,en;q=0.8"})
    seen=target=errors=0
    links={}
    for dep in DEPARTMENTS:
        try:
            r=session.get(urljoin(BASE,dep),timeout=30)
            r.raise_for_status()
            soup=BeautifulSoup(r.text,"html.parser")
        except Exception as exc:
            errors+=1
            print("PROTHYA LIST ERROR |",dep,"|",type(exc).__name__,exc)
            continue
        for a in soup.find_all("a",href=True):
            href=urljoin(r.url,a.get("href"))
            if "vacancy/" not in href or "jobCode=" not in href:
                continue
            seen+=1
            title=clean(a.get_text(" ",strip=True))
            if not is_target_title(title):
                continue
            target+=1
            links[href]=title

    jobs={}
    for url,list_title in links.items():
        try:
            title,description=_detail(session,url)
            parsed_title=title
            if not is_target_title(parsed_title) and is_target_title(list_title):
                title=list_title
            else:
                title=parsed_title or list_title
            if not is_target_title(title):
                errors+=1
                print("PROTHYA TITLE MISMATCH |",url,"| parsed=",repr(parsed_title),"| list=",repr(list_title))
                continue
            code=(parse_qs(urlparse(url).query).get("jobCode") or [url])[-1]
            jobs[code]=make_job(
                source=SOURCE_KEY,external_id=code,title=title,
                company="Prothya Biosolutions",location="Brussels, Belgium",
                description=description,url=url,
            )
            time.sleep(0.4)
        except Exception as exc:
            errors+=1
            print("PROTHYA DETAIL ERROR |",url,"|",type(exc).__name__,exc)

    publish_source_metrics(SOURCE_KEY,{
        "seen":seen,"target_title":target,"non_target":max(0,seen-target),
        "detail_ok":len(jobs),"detail_failed":errors,
        "geography_accepted":len(jobs),"geography_rejected":0,"geography_unknown":0,
        "language_rejected":0,"converted":len(jobs),"persisted":None,"errors":errors,
    })
    print("PROTHYA | kept=",len(jobs),"| seen=",seen,"| errors=",errors)
    return list(jobs.values())
