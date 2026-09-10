"""
JOBHUNTER - SOURCES MASTER V1

Canonical shareable source registry.

The file config/SOURCES_MASTER.json is created once, then updated IN PLACE.
It intentionally contains no API keys, tokens or private credentials.

Future source-expansion migrations should call:
    update_source_master(reason="...")

Do not generate timestamped copies of SOURCES_MASTER.json.
"""

from __future__ import annotations

from datetime import datetime, timezone
import importlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT=Path(__file__).resolve().parent.parent
MASTER_PATH=ROOT/"config"/"SOURCES_MASTER.json"
SCHEMA_VERSION="1.0"

PRO_TRACKS=("QC_PHARMA_LAB","DATA_JUNIOR_BI","QC_DATA_HYBRID")
ALL_TRACKS=PRO_TRACKS+("STUDENT_ANY",)

STUDENT_KEYS={"STUDENT_BE","STUDENTJOB_BE","RANDSTAD_STUDENT","START_PEOPLE_STUDENT","SYNERGIE_STUDENT","VDAB_STUDENT_WEB"}
BROAD_KEYS={
    "FOREM","ADZUNA","CAREERJET","JOOBLE","ACTIRIS","TALENT_BRUSSELS",
    "TRAVAILLERPOUR","SMARTRECRUITERS","JOBAT","RANDSTAD","JEFFERSON_WELLS",
    "AKKODIS","EXPERIS","SYNERGIE","ADECCO","MANPOWER","VIVALDIS","SELECT_HR",
    "AGILITAS","AGO","LETS_WORK","OXFORD_GLOBAL","BRUNEL","AUSTIN_BRIGHT",
    "PROGRESSIVE","START_PEOPLE","TEMPO_TEAM","QJOBS","MICHAEL_PAGE","ROBERT_HALF",
    "REFERENCES","ARBEITNOW","REMOTIVE",
}

DATA_KEYS={
    "ICTJOB","KEYRUS","NRB","SOPRA_STERIA","CAPGEMINI_ENG","ODOO","AMARIS",
}

def _now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def _sanitize_url(value):
    value=str(value or "").strip()
    if not value.startswith(("http://","https://")):
        return ""
    try:
        p=urlsplit(value)
        # Remove query/fragment so no credential-like parameters can leak.
        return urlunsplit((p.scheme,p.netloc,p.path,"",""))
    except Exception:
        return ""

def _load_existing():
    if not MASTER_PATH.exists():
        return {}
    try:
        obj=json.loads(MASTER_PATH.read_text(encoding="utf-8"))
        return obj if isinstance(obj,dict) else {}
    except Exception:
        return {}

def _target_function(spec,registry_module):
    collector=spec.collector
    names=getattr(getattr(collector,"__code__",None),"co_names",()) or ()
    for name in names:
        obj=getattr(registry_module,name,None)
        if callable(obj) and getattr(obj,"__module__","")!="sources.registry":
            return obj
    return collector

def _resolve_url(spec,registry_module):
    key=spec.key

    try:
        from sources.backlog_validator_v14 import load_backlog as load_v14_backlog
        for row in load_v14_backlog(include_all=True):
            if str(row.get("key") or "").upper()==key:
                return _sanitize_url(row.get("validated_url") or row.get("url"))
    except Exception:
        pass

    try:
        from sources.student_sources_v1 import PAGES
        if key in PAGES:
            return _sanitize_url(PAGES[key])
    except Exception:
        pass

    try:
        from sources.agency_student_network_v1 import PAGES as NETWORK_PAGES
        if key in NETWORK_PAGES:
            return _sanitize_url(NETWORK_PAGES[key])
    except Exception:
        pass

    try:
        from sources.workday_pharma_v1 import EMPLOYERS
        wk="AMGEN" if key=="AMGEN_WORKDAY" else key
        if wk in EMPLOYERS:
            x=EMPLOYERS[wk]
            return _sanitize_url(f"https://{x['host']}/en-US/{x['site']}")
    except Exception:
        pass

    try:
        from sources.direct_career_v1 import load_employer_configs
        for row in load_employer_configs(include_disabled=True):
            if str(row.get("key") or "").upper()==key:
                return _sanitize_url(row.get("career_url") or row.get("website"))
    except Exception:
        pass

    try:
        from sources.mega8_high_value import (
            EUROPHARMA_URL,ICTJOB_PAGES,REFERENCES_URL,SWDE_URL,ARBEITNOW_API
        )
        mapping={
            "EUROPHARMAJOBS":EUROPHARMA_URL,
            "ICTJOB":ICTJOB_PAGES[0],
            "REFERENCES":REFERENCES_URL,
            "SWDE":SWDE_URL,
            "ARBEITNOW":ARBEITNOW_API,
        }
        if key in mapping:
            return _sanitize_url(mapping[key])
    except Exception:
        pass

    try:
        from sources.remotive import API_URL
        if key=="REMOTIVE":
            return _sanitize_url(API_URL)
    except Exception:
        pass

    target=_target_function(spec,registry_module)
    module_name=getattr(target,"__module__","")
    if module_name:
        try:
            mod=importlib.import_module(module_name)
            preferred=[]
            for name,value in vars(mod).items():
                if not isinstance(value,str) or not value.startswith(("http://","https://")):
                    continue
                if re.search(r"(?:^|_)(?:API_?URL|BASE_?URL|SEARCH_?URL|CAREER.*URL|URL)$",name,re.I):
                    preferred.append(value)
            if preferred:
                return _sanitize_url(preferred[0])
        except Exception:
            pass
    return ""

def _source_type(spec,health,registry_module):
    key=spec.key
    try:
        from sources.backlog_validator_v14 import load_backlog as load_v14_backlog
        for row in load_v14_backlog(include_all=True):
            if str(row.get("key") or "").upper()==key and row.get("active"):
                return str(row.get("source_type") or "AUTO_VALIDATED")
    except Exception:
        pass
    mode=str(health.get("collection_mode") or "").upper()
    if key in STUDENT_KEYS:
        return "STUDENT_BOARD"
    if "WORKDAY" in key:
        return "WORKDAY"
    target=_target_function(spec,registry_module)
    module_name=str(getattr(target,"__module__","")).lower()
    if "workday" in module_name:
        return "WORKDAY"
    if "direct_career" in module_name:
        return "DIRECT_CAREER"
    if mode=="API":
        return "API"
    if mode=="CACHE_ONLY":
        return "CACHE_ONLY"
    if "smartrecruiters" in module_name:
        return "PUBLIC_ATS_API"
    return "LIVE_COLLECTOR"

def _tracks_for(key):
    try:
        from sources.backlog_validator_v14 import load_backlog as load_v14_backlog
        for row in load_v14_backlog(include_all=True):
            if str(row.get("key") or "").upper()==key and row.get("active"):
                tracks=[str(x) for x in (row.get("tracks") or []) if str(x) in ALL_TRACKS]
                # OPERATIONAL_ANY is intentionally not a JobHunter matching track.
                return tracks or list(PRO_TRACKS)
    except Exception:
        pass
    if key in STUDENT_KEYS:
        return ["STUDENT_ANY"]
    if key in BROAD_KEYS:
        return list(ALL_TRACKS)
    if key in DATA_KEYS:
        return ["DATA_JUNIOR_BI","QC_DATA_HYBRID","STUDENT_ANY"]
    return list(PRO_TRACKS)

def update_source_master(reason="manual_update"):
    from sources import registry as registry_module
    from sources.registry import SOURCE_SPECS,load_source_settings,list_source_status

    existing=_load_existing()
    old_rows={
        str(row.get("key") or "").upper():row
        for row in (existing.get("sources") or [])
        if isinstance(row,dict)
    }

    settings=load_source_settings()
    health_rows={row["key"]:row for row in list_source_status()}
    now=_now()
    rows=[]

    for spec in sorted(SOURCE_SPECS,key=lambda x:(x.priority,x.key)):
        old=old_rows.get(spec.key,{})
        h=health_rows.get(spec.key,{})
        target=_target_function(spec,registry_module)
        row={
            "key":spec.key,
            "name":spec.label,
            "url":_resolve_url(spec,registry_module),
            "source_type":_source_type(spec,h,registry_module),
            "collector_module":getattr(target,"__module__",""),
            "collector_name":getattr(target,"__name__",getattr(spec.collector,"__name__","")),
            "active":bool(settings.get(spec.key,spec.enabled_default)),
            "status":"ACTIVE" if bool(settings.get(spec.key,spec.enabled_default)) else "INACTIVE",
            "health":h.get("health","UNKNOWN"),
            "collection_mode":h.get("collection_mode","UNKNOWN"),
            "health_reason":h.get("health_reason") or h.get("reason") or "",
            "pipeline_group":spec.pipeline_group,
            "priority":spec.priority,
            "languages":list(spec.languages),
            "tracks":_tracks_for(spec.key),
            "date_added":old.get("date_added") or now[:10],
            "last_validation":now,
            "notes":spec.notes,
        }
        if old.get("manual_notes"):
            row["manual_notes"]=old["manual_notes"]
        rows.append(row)

    health_summary={}
    for row in rows:
        health_summary[row["health"]]=health_summary.get(row["health"],0)+1

    tracks_summary={}
    for row in rows:
        for track in row["tracks"]:
            tracks_summary[track]=tracks_summary.get(track,0)+1

    payload={
        "schema_version":SCHEMA_VERSION,
        "purpose":"Fichier maître partageable de toutes les sources JobHunter",
        "created_at":existing.get("created_at") or now,
        "updated_at":now,
        "update_reason":str(reason),
        "total_sources":len(rows),
        "active_sources":sum(1 for r in rows if r["active"]),
        "health_summary":health_summary,
        "tracks_summary":tracks_summary,
        "contains_private_credentials":False,
        "sources":rows,
    }

    MASTER_PATH.parent.mkdir(parents=True,exist_ok=True)
    tmp=MASTER_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(MASTER_PATH)
    return MASTER_PATH

def audit_source_master():
    from sources.registry import SOURCE_SPECS

    if not MASTER_PATH.exists():
        return {"ok":False,"reason":"MISSING_MASTER"}

    payload=json.loads(MASTER_PATH.read_text(encoding="utf-8"))
    rows=payload.get("sources") or []
    master_keys=[str(r.get("key") or "").upper() for r in rows]
    registry_keys=[s.key for s in SOURCE_SPECS]

    duplicates=sorted({k for k in master_keys if master_keys.count(k)>1})
    missing=sorted(set(registry_keys)-set(master_keys))
    extra=sorted(set(master_keys)-set(registry_keys))

    raw=MASTER_PATH.read_text(encoding="utf-8")
    secret_patterns=[
        r'"app_key"\s*:',r'"api_key"\s*:',r'"client_secret"\s*:',
        r'"password"\s*:',r'"token"\s*:\s*"[^"]+"',
    ]
    secret_hits=[p for p in secret_patterns if re.search(p,raw,re.I)]

    return {
        "ok":not duplicates and not missing and not extra and not secret_hits,
        "total_master":len(master_keys),
        "total_registry":len(registry_keys),
        "duplicates":duplicates,
        "missing":missing,
        "extra":extra,
        "secret_hits":secret_hits,
    }
