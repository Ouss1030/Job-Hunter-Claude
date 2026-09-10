from __future__ import annotations

import base64
import requests

from sources.api_credentials import credential_status, get_credential
from sources.api_expansion_common import ALL_SEARCH_TERMS, belgium_location_ok, clean, is_target_title, make_job
from sources.source_metrics import publish_source_metrics

SOURCE_KEY="CAREERJET"
BASE="https://search.api.careerjet.net/v4/query"


def collect_careerjet_jobs() -> list:
    cred=credential_status(SOURCE_KEY)
    if not cred["ready"]:
        print("CAREERJET | NEEDS_CREDENTIALS | missing=" + ",".join(cred["missing"]))
        publish_source_metrics(SOURCE_KEY,{
            "seen":0,"target_title":0,"non_target":0,"detail_ok":0,"detail_failed":0,
            "geography_accepted":0,"geography_rejected":0,"geography_unknown":0,
            "language_rejected":0,"converted":0,"persisted":None,"errors":0,
        })
        return []

    api_key=get_credential("CAREERJET_API_KEY")
    user_ip=get_credential("CAREERJET_USER_IP")
    locale=get_credential("CAREERJET_LOCALE_CODE","fr_BE") or "fr_BE"
    ua=get_credential("CAREERJET_USER_AGENT","JobHunter/7.0 personal job search") or "JobHunter/7.0 personal job search"
    token=base64.b64encode((api_key+":").encode("utf-8")).decode("ascii")

    session=requests.Session()
    session.headers.update({"Accept":"application/json","Authorization":"Basic "+token})

    seen=target=geo_ok=geo_rej=errors=0
    jobs={}
    # Fewer, broader terms: Careerjet requires end-user context on every call.
    terms=("QC Analyst","Laborantin","LIMS Data Integrity","Junior Data Analyst","Power BI Analyst","Data Quality Analyst")
    for term in terms:
        try:
            r=session.get(BASE,params={
                "locale_code":locale,"keywords":term,"location":"Belgium",
                "sort":"date","page_size":50,"page":1,
                "user_ip":user_ip,"user_agent":ua,
            },timeout=30)
            r.raise_for_status()
            data=r.json()
        except Exception as exc:
            errors+=1
            print("CAREERJET ERROR |",term,"|",type(exc).__name__,exc)
            continue

        for row in data.get("jobs") or []:
            seen+=1
            title=clean(row.get("title"))
            if not is_target_title(title):
                continue
            target+=1
            loc=clean(row.get("locations") or row.get("location"))
            if not belgium_location_ok(loc, trusted=True):
                geo_rej+=1
                continue
            geo_ok+=1
            url=clean(row.get("url"))
            ext=url
            jobs[ext]=make_job(
                source=SOURCE_KEY,external_id=ext,title=title,
                company=clean(row.get("company")),location=loc,
                description=clean(row.get("description")),url=url,
                date_published=row.get("date"),
                contract_type=row.get("contract_type"),
            )

    publish_source_metrics(SOURCE_KEY,{
        "seen":seen,"target_title":target,"non_target":max(0,seen-target),
        "detail_ok":len(jobs),"detail_failed":0,
        "geography_accepted":geo_ok,"geography_rejected":geo_rej,"geography_unknown":0,
        "language_rejected":0,"converted":len(jobs),"persisted":None,"errors":errors,
    })
    print("CAREERJET | kept=",len(jobs),"| seen=",seen,"| errors=",errors)
    return list(jobs.values())
