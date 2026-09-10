"""
JOBHUNTER - STATEFUL MEGA ADVANCE V21

Core idea:
- completed work is remembered in config/MEGA_PROGRESS_V21.json
- active sources are never re-probed
- blocked/credential/policy sources are paused, not repeatedly retried
- failed/incomplete runs resume from the last unfinished source
- previous V15 attempted URLs are remembered and not retried
- only NEW URLs / sitemap / robots / ATS evidence are explored

No stealth, CAPTCHA bypass, IP rotation or login.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from sources.backlog_validator_v14 import (
    SESSION, BLOCK_STATUS, load_backlog, save_backlog, canonical,
    _jsonld_jobs, _candidate_links, _detect_ats,
)
try:
    from sources.backlog_curated_v16 import OVERRIDES as V16_OVERRIDES
except Exception:
    V16_OVERRIDES={}
try:
    from sources.backlog_deep_validator_v15 import VERIFIED_OVERRIDES as V15_OVERRIDES
except Exception:
    V15_OVERRIDES={}

ROOT=Path(__file__).resolve().parent.parent
STATE_PATH=ROOT/"config"/"MEGA_PROGRESS_V21.json"
VERSION="21.3"

PAUSE_STATUSES={
    "NEEDS_CREDENTIALS","SKIPPED_POLICY","DUPLICATE_EXISTING",
    "COVERED_BY_PARENT",
}
COMMON_PATHS=(
    "/jobs","/jobs/","/careers","/careers/","/vacatures","/vacatures/",
    "/fr/jobs","/fr/jobs/","/fr/emploi","/fr/emploi/","/fr/carrieres",
    "/fr/carrieres/","/werken-bij","/werken-bij/","/job-opportunities",
    "/viewalljobs/","/search-results","/offres-d-emploi",
)
SITEMAP_JOB=re.compile(
    r"(job|jobs|career|careers|vacature|vacatures|emploi|offre|position|vacancy)",
    re.I,
)

EXTRA_OVERRIDES={
    "STIB_MIVB":"https://jobs.stib-mivb.be/viewalljobs/",
    "VUB_JOBS":"https://jobs.vub.be/go/EN_ALL-JOBS/3775601/",
    "SGS":"https://www.sgs.com/en-be/our-company/careers-at-sgs/job-opportunities",
    "SCIENSANO_RESEARCH":"https://www.sciensano.be/fr/travailler-faire-un-stage-chez-sciensano/mes-opportunites-demploi",
    "SNCB_NMBS":"https://jobs.belgiantrain.be/fr/search",
    "PURATOS":"https://jobs.puratos.com/go/Belgium-%26-HQ_FR/9458001/",
    "BPOST":"https://career.bpost.be/en/job-search",
    "ULB_JOBS":"https://www.ulb.be/fr/offres-d-emploi/offres-demploi-a-lulb-externe",
}

def _now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def _root(url):
    try:
        p=urlsplit(str(url or ""))
        if p.scheme and p.netloc:
            return urlunsplit((p.scheme,p.netloc,"","",""))
    except Exception:
        pass
    return ""

def _load_state():
    if not STATE_PATH.exists():
        return {
            "version":VERSION,
            "created_at":_now(),
            "updated_at":_now(),
            "sources":{},
            "actions":{},
        }
    try:
        obj=json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(obj,dict):
            obj.setdefault("sources",{})
            obj.setdefault("actions",{})
            return obj
    except Exception:
        pass
    return {
        "version":VERSION,"created_at":_now(),"updated_at":_now(),
        "sources":{},"actions":{},
    }

def _save_state(state):
    state["version"]=VERSION
    state["updated_at"]=_now()
    STATE_PATH.parent.mkdir(parents=True,exist_ok=True)
    tmp=STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(STATE_PATH)

def initialize_state():
    state=_load_state()
    rows=load_backlog(include_all=True)
    for row in rows:
        key=str(row.get("key") or "").upper()
        s=state["sources"].setdefault(key,{})
        s.setdefault("attempted_urls",[])
        # Import attempts already made by older versions, so V21 does NOT repeat them.
        for att in row.get("v15_attempts") or []:
            u=canonical(att.get("url") or "")
            if u and u not in s["attempted_urls"]:
                s["attempted_urls"].append(u)

        if row.get("active"):
            s["status"]="DONE_ACTIVE"
            s["reason"]="Already active before V21; skipped."
        elif s.get("status")=="DONE_ACTIVATED" and s.get("validated_url"):
            # A previous V21 run validated/applied this source, then a later
            # unrelated final check triggered rollback. Reuse the validated
            # evidence: do NOT probe the web again.
            s["status"]="READY_TO_ACTIVATE"
            s["recovered_from_rollback"]=True
            s["reason"]="Recovered after rollback; previous V21 validation reused."
        elif row.get("probe_status") in PAUSE_STATUSES:
            s["status"]="PAUSED"
            s["reason"]=str(row.get("probe_reason") or row.get("probe_status"))
        else:
            s.setdefault("status","TODO")
            s.setdefault("reason","")
        s["backlog_status"]=row.get("probe_status")
    _save_state(state)
    return state

def _candidate_urls(row,state_entry):
    seen=set(state_entry.get("attempted_urls") or [])
    out=[]

    def add(u):
        u=canonical(u)
        if u and u.startswith(("http://","https://")) and u not in seen and u not in out:
            out.append(u)

    key=str(row.get("key") or "").upper()
    add(EXTRA_OVERRIDES.get(key))
    add(V16_OVERRIDES.get(key))
    add(V15_OVERRIDES.get(key))
    add(row.get("validated_url"))
    add(row.get("url"))

    root=_root(row.get("url") or row.get("validated_url") or "")
    if root:
        for p in COMMON_PATHS:
            add(root+p)
    return out[:18]

def _probe(url):
    try:
        r=SESSION.get(url,timeout=25,allow_redirects=True)
    except Exception as exc:
        return {"ok":False,"status":"FETCH_ERROR","reason":f"{type(exc).__name__}: {exc}","url":canonical(url)}

    if r.status_code in BLOCK_STATUS:
        return {"ok":False,"status":"BLOCKED","reason":f"HTTP {r.status_code}","url":canonical(r.url)}
    if r.status_code>=400:
        return {"ok":False,"status":"HTTP_ERROR","reason":f"HTTP {r.status_code}","url":canonical(r.url)}

    text=r.text or ""
    soup=BeautifulSoup(text,"html.parser")
    jsonld=len(_jsonld_jobs(soup))
    links=_candidate_links(r.url,soup)
    ats=_detect_ats(r.url+"\n"+text[:700000])
    ok=jsonld>0 or len(links)>=2 or bool(ats)
    return {
        "ok":bool(ok),"status":"VALID" if ok else "NO_EVIDENCE",
        "url":canonical(r.url),"jsonld":jsonld,"job_links":len(links),
        "ats":ats,"reason":f"jsonld={jsonld}, links={len(links)}, ats={ats or 'NONE'}",
    }

def _robots_sitemaps(root):
    urls=[]
    if not root:return urls
    try:
        r=SESSION.get(root+"/robots.txt",timeout=20,allow_redirects=True)
        if r.status_code<400:
            for line in (r.text or "").splitlines():
                if line.lower().startswith("sitemap:"):
                    u=line.split(":",1)[1].strip()
                    if u.startswith(("http://","https://")):
                        urls.append(u)
    except Exception:
        pass
    urls.append(root+"/sitemap.xml")
    # unique
    out=[]
    for u in urls:
        if u not in out:out.append(u)
    return out[:5]

def _sitemap_candidates(root,attempted):
    out=[]
    for sm in _robots_sitemaps(root):
        if sm in attempted:
            continue
        try:
            r=SESSION.get(sm,timeout=25,allow_redirects=True)
            if r.status_code>=400:
                continue
            raw=r.text or ""
            # XML parsing first, regex fallback.
            locs=[]
            try:
                rootxml=ET.fromstring(raw)
                for el in rootxml.iter():
                    if el.tag.lower().endswith("loc") and el.text:
                        locs.append(el.text.strip())
            except Exception:
                locs=re.findall(r"<loc>\s*([^<]+)\s*</loc>",raw,re.I)
            for u in locs[:2000]:
                if SITEMAP_JOB.search(urlparse(u).path) and u not in attempted and u not in out:
                    out.append(canonical(u))
                    if len(out)>=30:return out
        except Exception:
            continue
    return out

def process_unfinished(progress=None):
    state=initialize_state()
    rows=load_backlog(include_all=True)
    bykey={str(r.get("key") or "").upper():r for r in rows}
    todo=[k for k,s in state["sources"].items() if s.get("status")=="TODO" and k in bykey]

    for idx,key in enumerate(todo,1):
        row=bykey[key]
        s=state["sources"][key]
        if progress:progress(idx,len(todo),key,row)

        attempted=s.setdefault("attempted_urls",[])
        attempts=s.setdefault("v21_attempts",[])
        best=None
        blocked=False

        # 1) New direct/common URLs not already tried by older batches.
        candidates=_candidate_urls(row,s)
        # 2) New sitemap discovery.
        root=_root(row.get("url") or row.get("validated_url") or "")
        candidates.extend(_sitemap_candidates(root,set(attempted)))

        unique=[]
        for u in candidates:
            u=canonical(u)
            if u and u not in attempted and u not in unique:
                unique.append(u)

        for u in unique[:24]:
            attempted.append(u)
            res=_probe(u)
            attempts.append(res)
            _save_state(state)  # resume-safe after EVERY URL

            if res.get("status")=="BLOCKED":
                blocked=True
                break
            if res.get("ok"):
                best=res
                break
            time.sleep(0.35)

        if best:
            s["status"]="READY_TO_ACTIVATE"
            s["validated_url"]=best["url"]
            s["reason"]="V21 new evidence: "+best["reason"]
            s["ats"]=best.get("ats","")
        elif blocked:
            s["status"]="PAUSED_BLOCKED"
            s["reason"]="Site blocked access; no bypass attempted."
        else:
            s["status"]="DONE_EXHAUSTED"
            s["reason"]="V21 found no NEW safe evidence after previous attempts + common paths + sitemap."
        s["finished_at"]=_now()
        _save_state(state)

    return state

def apply_ready_to_backlog():
    state=_load_state()
    rows=load_backlog(include_all=True)
    changed=[]
    for row in rows:
        key=str(row.get("key") or "").upper()
        s=state["sources"].get(key,{})
        if s.get("status")!="READY_TO_ACTIVATE":
            continue
        row["active"]=True
        row["status"]="ACTIVE"
        row["health"]="HEALTHY"
        row["collection_mode"]="LIVE"
        row["collector_module"]="sources.backlog_validator_v14"
        row["collector_name"]="collect_backlog_source_jobs"
        row["validated_url"]=s["validated_url"]
        row["probe_status"]="ACTIVATED"
        row["probe_reason"]=s["reason"]
        row["v21_validated_at"]=_now()
        changed.append(key)
        s["status"]="DONE_ACTIVATED"
        s["activation_applied_at"]=_now()
    save_backlog(rows)
    _save_state(state)
    return changed,state

def mark_action(name,status,details=""):
    state=_load_state()
    state["actions"][name]={
        "status":status,"details":details,"updated_at":_now()
    }
    _save_state(state)

def action_done(name):
    return _load_state().get("actions",{}).get(name,{}).get("status")=="DONE"

def summary():
    state=_load_state()
    counts={}
    for s in state.get("sources",{}).values():
        k=s.get("status","UNKNOWN")
        counts[k]=counts.get(k,0)+1
    return {"state_path":str(STATE_PATH),"counts":counts,"actions":state.get("actions",{})}
