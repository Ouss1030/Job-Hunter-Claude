from __future__ import annotations
import re, requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36"

TARGET=[
 r"\bdata analyst\b",r"\bbusiness analyst\b",r"\bbusiness intelligence\b",r"\bpower\s*bi\b",
 r"\bdata quality\b",r"\bquality control\b",r"\bquality assurance\b",r"\bqc\b",r"\bqa\b",
 r"\bqc specialist\b",r"\bquality specialist\b",r"\blaboratory technician\b",r"\blab technician\b",
 r"\blaboratory analyst\b",r"\blab engineer\b",r"\btechnologue de laboratoire\b",
 r"\btechnicien(?:ne)? de laboratoire\b",r"\banalytical chemistry\b",r"\banalytical scientist\b",
 r"\banalytical analyst\b",r"\banalytical project\b",r"\bchemist\b",r"\bchimiste\b",
 r"\bmicrobiology\b",r"\bvalidation technician\b",r"\bmsat\b",r"\bproduction gmp\b",
]
EXCLUDE=[r"\bsenior\b",r"\bprincipal\b",r"\bdirector\b",r"\bhead\b",r"\bmanager\b",
         r"\bsupervisor\b",r"\bintern(?:ship)?\b",r"\bstage\b",r"\btrainee\b",r"\bapprentice\b"]
DUTCH=[
 r"\bfluent\s+dutch\b",r"\bprofessional\s+dutch\b",r"\bdutch\s+(?:is\s+)?required\b",
 r"\bgoede\s+kennis\s+(?:van\s+het\s+)?nederlands\b",r"\bnederlands\s+(?:is\s+)?vereist\b",
 r"\bvloeiend\s+nederlands\b",r"\btweetalig\b",r"\bma[iî]trise\s+du\s+n[eé]erlandais\b",
 r"\bn[eé]erlandais\s+(?:est\s+)?(?:exig[eé]|requis|obligatoire)\b",
]
OPTIONAL=["asset","plus","preferred","nice to have","atout","pluspunt","souhaité","souhaite"]
WALLONIA=["donstiennes","thuin","charleroi","gosselies","liège","liege","seraing","ougrée","ougree",
          "nivelles","louvain-la-neuve","wavre","braine-l'alleud","brussels","bruxelles","wallonia","wallonie"]

def clean(x): return re.sub(r"\s+"," ",str(x or "")).strip()

def session():
    s=requests.Session()
    s.headers.update({"User-Agent":UA,"Accept-Language":"fr-BE,fr;q=0.9,en;q=0.8"})
    return s

def title_is_target(title):
    t=clean(title)
    return bool(t) and not any(re.search(p,t,re.I) for p in EXCLUDE) and any(re.search(p,t,re.I) for p in TARGET)

def dutch_hard(text):
    for chunk in re.split(r"(?<=[.!?;:])\s+|[\r\n•●▪◦]+",str(text or "")):
        low=clean(chunk).lower()
        if not low: continue
        if any(re.search(p,low,re.I) for p in DUTCH):
            if any(x in low for x in OPTIONAL): continue
            return True
    return False

def geo_status(text):
    value=clean(text)
    try:
        from sources.belgium_locations import classify_belgium_location
        d=classify_belgium_location(value)
        st=getattr(d,"status",getattr(d,"state","UNKNOWN"))
        if st in {"BELGIUM","FOREIGN"}: return st
    except Exception:
        pass
    low=value.lower()
    if "belgium" in low or "belgique" in low or "belgië" in low or any(x in low for x in WALLONIA):
        return "BELGIUM"
    return "UNKNOWN"

def page(s,url):
    r=s.get(url,timeout=30,allow_redirects=True); r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    text=clean(soup.get_text(" ",strip=True))
    h1=soup.find("h1")
    title=clean(h1.get_text(" ",strip=True)) if h1 else ""
    location=""
    low=text.lower()
    for hint in WALLONIA:
        if hint in low:
            location=hint
            break
    return {"title":title,"location":location,"geo":geo_status(location or text[:3000]),
            "description":text,"hard_dutch":dutch_hard(text),"url":r.url,"http":r.status_code}

def metrics(rows):
    candidates=[r for r in rows if title_is_target(r["title"])]
    kept=[r for r in candidates if r["geo"]=="BELGIUM" and not r["hard_dutch"]]
    m={"seen":len(rows),"candidates":len(candidates),"kept":len(kept),
       "non_target":max(0,len(rows)-len(candidates)),
       "rejected_language":sum(1 for r in candidates if r["hard_dutch"]),
       "rejected_geo":sum(1 for r in candidates if r["geo"]!="BELGIUM"),
       "closed":0,"detail_errors":0}
    return kept,m

def print_result(key,kept,m):
    print("\n"+"="*82); print(key); print("="*82)
    for k,v in m.items(): print(f"{k:<20}: {v}")
    for r in kept: print("KEEP |",r["title"],"|",r["location"],"|",r["url"])


# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1
from sources.unified_discovery import matches_master_title

_ud_original_title_is_target = title_is_target

def title_is_target(*args, **kwargs):
    if _ud_original_title_is_target(*args, **kwargs):
        return True
    try:
        title = args[0] if args else kwargs.get('title', '')
    except Exception:
        return False
    return matches_master_title(title)
