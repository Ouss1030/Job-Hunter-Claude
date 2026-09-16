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
# Chaque domaine Jooble (pays) exige sa propre cle : une cle demandee sur
# fr.jooble.org ne repond que sur fr.jooble.org (verifie le 16/09/2026).
# JOOBLE_HOST dans config/private/api_keys.env permet de suivre la cle.
BASE_TEMPLATE="https://{host}/api/{key}"
HOTE_DEFAUT="be.jooble.org"
# La cle gratuite est limitee a 500 requetes A VIE (documentation Jooble).
# On garde une reserve : au-dela de QUOTA_VIE, le connecteur se tait.
QUOTA_VIE=480


def _etat() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _compter_requete(nb: int = 1) -> int:
    etat=_etat()
    etat["requetes_vie"]=int(etat.get("requetes_vie",0))+nb
    STATE_PATH.parent.mkdir(parents=True,exist_ok=True)
    STATE_PATH.write_text(json.dumps(etat,indent=2),encoding="utf-8")
    return etat["requetes_vie"]


def _rotating_terms() -> list[str]:
    STATE_PATH.parent.mkdir(parents=True,exist_ok=True)
    per=int(get_credential("JOOBLE_QUERIES_PER_RUN","2") or 2)
    per=max(1,min(3,per))
    etat=_etat()
    index=int(etat.get("index",0) or 0)
    terms=list(ALL_SEARCH_TERMS)
    chosen=[terms[(index+i)%len(terms)] for i in range(per)]
    etat["index"]=(index+per)%len(terms)
    STATE_PATH.write_text(json.dumps(etat,indent=2),encoding="utf-8")
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
    hote=(get_credential("JOOBLE_HOST") or HOTE_DEFAUT).strip().removeprefix("https://").strip("/")
    url=BASE_TEMPLATE.format(host=hote,key=key)
    deja=int(_etat().get("requetes_vie",0))
    if deja>=QUOTA_VIE:
        print(f"JOOBLE | QUOTA_VIE atteint ({deja}/{QUOTA_VIE} requetes) : demander une nouvelle cle sur {hote}/api/about")
        return []
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
            if r.status_code==200:
                total_vie=_compter_requete()
                print(f"JOOBLE | {term} | requetes a vie : {total_vie}/500")
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
