from __future__ import annotations

import requests

from sources.api_credentials import credential_status, get_credential
from sources.api_expansion_common import ALL_SEARCH_TERMS, belgium_location_ok, clean, is_target_title, make_job
from sources.source_metrics import publish_source_metrics

SOURCE_KEY = "ADZUNA"
BASE = "https://api.adzuna.com/v1/api/jobs/be/search/1"


def collect_adzuna_jobs() -> list:
    cred = credential_status(SOURCE_KEY)
    if not cred["ready"]:
        print("ADZUNA | NEEDS_CREDENTIALS | missing=" + ",".join(cred["missing"]))
        publish_source_metrics(SOURCE_KEY, {
            "seen":0,"target_title":0,"non_target":0,"detail_ok":0,"detail_failed":0,
            "geography_accepted":0,"geography_rejected":0,"geography_unknown":0,
            "language_rejected":0,"converted":0,"persisted":None,"errors":0,
        })
        return []

    app_id=get_credential("ADZUNA_APP_ID")
    app_key=get_credential("ADZUNA_APP_KEY")
    per_query=int(get_credential("ADZUNA_RESULTS_PER_QUERY","50") or 50)
    per_query=max(10,min(50,per_query))

    session=requests.Session()
    session.headers.update({"Accept":"application/json","User-Agent":"JobHunter/7.0 personal job search"})

    seen=target=geo_ok=geo_rej=errors=0
    jobs={}
    for term in ALL_SEARCH_TERMS:
        try:
            r=session.get(BASE,params={
                "app_id":app_id,"app_key":app_key,"results_per_page":per_query,
                "what":term,"where":"Belgium","sort_by":"date",
                "content-type":"application/json",
            },timeout=30)
            r.raise_for_status()
            data=r.json()
        except Exception as exc:
            errors+=1
            print("ADZUNA ERROR |",term,"|",type(exc).__name__,exc)
            continue

        for row in data.get("results") or []:
            seen+=1
            title=clean(row.get("title"))
            if not is_target_title(title):
                continue
            target+=1
            loc=clean((row.get("location") or {}).get("display_name"))
            if not belgium_location_ok(loc, trusted=True):
                geo_rej+=1
                continue
            geo_ok+=1
            company=clean((row.get("company") or {}).get("display_name"))
            ext=clean(row.get("id") or row.get("redirect_url"))
            url=clean(row.get("redirect_url"))
            jobs[ext or url]=make_job(
                source=SOURCE_KEY,external_id=ext or url,title=title,company=company,
                location=loc,description=clean(row.get("description")),url=url,
                date_published=row.get("created"),
                contract_type=row.get("contract_time") or row.get("contract_type"),
            )

    metrics={
        "seen":seen,"target_title":target,"non_target":max(0,seen-target),
        "detail_ok":len(jobs),"detail_failed":0,
        "geography_accepted":geo_ok,"geography_rejected":geo_rej,"geography_unknown":0,
        "language_rejected":0,"converted":len(jobs),"persisted":None,"errors":errors,
    }
    publish_source_metrics(SOURCE_KEY,metrics)
    print("ADZUNA | kept=",len(jobs),"| seen=",seen,"| errors=",errors)
    return list(jobs.values())
