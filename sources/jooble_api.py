from __future__ import annotations

import json
from pathlib import Path

import requests

from sources.api_credentials import credential_status, get_credential
from sources.api_expansion_common import ALL_SEARCH_TERMS, belgium_location_ok, clean, is_target_title, make_job
from sources.source_metrics import publish_source_metrics

SOURCE_KEY="JOOBLE"
PROJECT_ROOT=Path(__file__).resolve().parent.parent
STATE_PATH=PROJECT_ROOT/"cache"/"jooble_api_rotation.json"
BASE_TEMPLATE="https://be.jooble.org/api/{key}"


def _rotating_terms() -> list[str]:
    STATE_PATH.parent.mkdir(parents=True,exist_ok=True)
    per=int(get_credential("JOOBLE_QUERIES_PER_RUN","2") or 2)
    per=max(1,min(3,per))
    index=0
    if STATE_PATH.exists():
        try:index=int(json.loads(STATE_PATH.read_text(encoding="utf-8")).get("index",0))
        except Exception:index=0
    terms=list(ALL_SEARCH_TERMS)
    chosen=[terms[(index+i)%len(terms)] for i in range(per)]
    STATE_PATH.write_text(json.dumps({"index":(index+per)%len(terms)},indent=2),encoding="utf-8")
    return chosen


def collect_jooble_jobs() -> list:
    cred=credential_status(SOURCE_KEY)
    if not cred["ready"]:
        print("JOOBLE | NEEDS_CREDENTIALS | missing=" + ",".join(cred["missing"]))
        publish_source_metrics(SOURCE_KEY,{
            "seen":0,"target_title":0,"non_target":0,"detail_ok":0,"detail_failed":0,
            "geography_accepted":0,"geography_rejected":0,"geography_unknown":0,
            "language_rejected":0,"converted":0,"persisted":None,"errors":0,
        })
        return []

    key=get_credential("JOOBLE_API_KEY")
    url=BASE_TEMPLATE.format(key=key)
    session=requests.Session()
    session.headers.update({"Accept":"application/json","Content-Type":"application/json","User-Agent":"JobHunter/7.0 personal job search"})

    seen=target=geo_ok=geo_rej=errors=0
    jobs={}
    terms=_rotating_terms()
    print("JOOBLE | quota-aware rotation | queries=",len(terms),"|",terms)
    for term in terms:
        try:
            r=session.post(url,json={
                "keywords":term,"location":"Belgium","radius":"80",
                "page":"1","ResultOnPage":20,"companysearch":False,
            },timeout=30)
            r.raise_for_status()
            data=r.json()
        except Exception as exc:
            errors+=1
            print("JOOBLE ERROR |",term,"|",type(exc).__name__,exc)
            continue
        for row in data.get("jobs") or []:
            seen+=1
            title=clean(row.get("title"))
            if not is_target_title(title):
                continue
            target+=1
            loc=clean(row.get("location"))
            if not belgium_location_ok(loc, trusted=True):
                geo_rej+=1
                continue
            geo_ok+=1
            ext=clean(row.get("id") or row.get("link"))
            link=clean(row.get("link"))
            jobs[ext or link]=make_job(
                source=SOURCE_KEY,external_id=ext or link,title=title,
                company=clean(row.get("company")),location=loc,
                description=clean(row.get("snippet")),url=link,
                date_published=row.get("updated"),contract_type=row.get("type"),
            )

    publish_source_metrics(SOURCE_KEY,{
        "seen":seen,"target_title":target,"non_target":max(0,seen-target),
        "detail_ok":len(jobs),"detail_failed":0,
        "geography_accepted":geo_ok,"geography_rejected":geo_rej,"geography_unknown":0,
        "language_rejected":0,"converted":len(jobs),"persisted":None,"errors":errors,
    })
    print("JOOBLE | kept=",len(jobs),"| seen=",seen,"| errors=",errors)
    return list(jobs.values())
