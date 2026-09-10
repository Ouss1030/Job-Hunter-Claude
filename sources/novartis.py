"""JOB HUNTER BELGIUM - NOVARTIS BELGIUM V1.0.
Public novartis.com career-search collector. No authentication/bypass.
"""
from __future__ import annotations
import hashlib, html as html_lib, json, re, time
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from database.models import JobOffer
from sources.randstad import dutch_professional_required
from sources.scienceatwork import detect_language

BASE_URL="https://www.novartis.com"
LIST_URL="https://www.novartis.com/careers/career-search/tag/LOC_BE"
PROJECT_ROOT=Path(__file__).resolve().parent.parent
CACHE_DIR=PROJECT_ROOT/"logs"/"novartis_public_cache"
HEADERS={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151.0 Safari/537.36","Accept-Language":"en,fr-BE;q=0.9,fr;q=0.8"}
TARGET=(r"\bdata\s+analyst\b",r"\bbusiness\s+analyst\b",r"\bdata\s+quality\b",r"\bdata\s+integrity\b",r"\bmaster\s+data\b",r"\bdata\s+steward\b",r"\breporting\s+analyst\b",r"\bpower\s*bi\b",r"\bbi\s+(?:analyst|developer)\b",r"\bbusiness\s+intelligence\b",r"\bqc\s+(?:analyst|technician|associate|specialist)\b",r"\bquality\s+control\b",r"\bqa\s+(?:analyst|associate|technician|specialist)\b",r"\bquality\s+assurance\b",r"\blab(?:oratory)?\s+(?:analyst|technician|associate)\b",r"\banalytical\s+(?:analyst|scientist|chemist)\b",r"\bmicrobiology\b")
EXCLUDE=(r"\b(?:senior|sr\.?|principal|lead|manager|director|head|vp|supervisor|team\s+leader)\b",r"\b(?:intern|internship|stage|graduate|trainee|student|apprentice)\b")
CLOSED=("job is no longer available","position has been filled","page not found","404 not found")
def clean_text(v):
    if v is None:return ""
    return re.sub(r"\s+"," ",html_lib.unescape(str(v)).replace("\xa0"," ")).strip()
def _target(t):
    s=clean_text(t).lower(); return bool(s) and not any(re.search(p,s,re.I) for p in EXCLUDE) and any(re.search(p,s,re.I) for p in TARGET)
def _cache(url,prefix):
    CACHE_DIR.mkdir(parents=True,exist_ok=True); return CACHE_DIR/f"{prefix}_{hashlib.sha1(url.encode()).hexdigest()[:18]}.html"
def _get(url,use_cache=True,prefix="detail"):
    p=_cache(url,prefix)
    if use_cache and p.exists():
        return p.read_text(encoding="utf-8",errors="ignore"),True,None,200
    try:
        r=requests.get(url,headers=HEADERS,timeout=25,allow_redirects=True); st=r.status_code
        if st==404:return "",False,"HTTP 404",st
        r.raise_for_status(); text=r.text or ""
        if text:p.write_text(text,encoding="utf-8")
        return text,False,None,st
    except requests.HTTPError as e:return "",False,f"HTTPError: {e}",getattr(getattr(e,"response",None),"status_code",None)
    except Exception as e:return "",False,f"{type(e).__name__}: {e}",None
def _job_id(url):
    m=re.search(r"/job/details/(req-\d+)(?:-|/|$)",urlparse(url).path,re.I); return (m.group(1).upper() if m else "")
def _extract_rows(html):
    soup=BeautifulSoup(html or "","html.parser"); out={}
    for a in soup.find_all("a",href=True):
        href=clean_text(a.get("href")); absu=urljoin(BASE_URL,href)
        jid=_job_id(absu)
        if not jid:continue
        title=clean_text(a.get_text(" ",strip=True))
        if not title:continue
        tr=a.find_parent("tr"); cells=[]
        if tr:
            cells=[clean_text(c.get_text(" ",strip=True)) for c in tr.find_all(["td","th"])]
        # Expected table: title, site, location, division, business, functional area, date.
        site=cells[1] if len(cells)>1 else ""; country=cells[2] if len(cells)>2 else ""; division=cells[3] if len(cells)>3 else ""; business=cells[4] if len(cells)>4 else ""; functional=cells[5] if len(cells)>5 else ""; date=cells[6] if len(cells)>6 else ""
        if country and "belgium" not in country.lower():continue
        out[jid]={"external_id":jid,"title":title,"location":clean_text(f"{site}, Belgium" if site else country or "Belgium"),"site":site,"country":country or "Belgium","division":division,"business":business,"functional_area":functional,"date_published":date,"url":absu}
    return list(out.values())
def collect_novartis_listing_candidates(use_cache=True):
    print("NOVARTIS - collecte directe Belgique via career-search public")
    html,fc,err,st=_get(LIST_URL,use_cache,"listing"); rows=_extract_rows(html) if html else []; c=[r for r in rows if _target(r.get("title",""))]
    print(f"NOVARTIS - BELGIQUE : {len(rows)} offre(s) | {len(c)} candidate(s) métier | {'CACHE' if fc else 'WEB'}")
    return c,{"belgium_rows":len(rows),"candidates":len(c),"all_belgium_rows":rows,"errors":[err] if err else [],"listing_url":LIST_URL}
def _jsonld(soup):
    for sc in soup.find_all("script",attrs={"type":"application/ld+json"}):
        raw=sc.string or sc.get_text(" ",strip=True)
        try:data=json.loads(raw)
        except Exception:continue
        stack=data if isinstance(data,list) else [data]
        while stack:
            x=stack.pop(0)
            if isinstance(x,list):stack.extend(x);continue
            if not isinstance(x,dict):continue
            typ=x.get("@type")
            if typ=="JobPosting" or (isinstance(typ,list) and "JobPosting" in typ):return x
            if isinstance(x.get("@graph"),list):stack.extend(x["@graph"])
    return {}
def _loc(j):
    loc=j.get("jobLocation")
    if isinstance(loc,list):loc=loc[0] if loc else None
    if not isinstance(loc,dict):return ""
    a=loc.get("address")
    if isinstance(a,dict):return clean_text(", ".join(clean_text(a.get(k)) for k in ("addressLocality","addressRegion","addressCountry") if clean_text(a.get(k))))
    return clean_text(loc.get("name"))
def _desc(soup,title):
    j=_jsonld(soup); d=clean_text(BeautifulSoup(str(j.get("description") or ""),"html.parser").get_text(" ",strip=True))
    if len(d)>=220:return d,j
    lines=[clean_text(x) for x in soup.get_text("\n",strip=True).splitlines() if clean_text(x)]; txt="\n".join(lines)
    m=re.search(r"(?:^|\n)(?:About the Role|Summary)(?:\n|$)",txt,re.I); body=txt[m.start():] if m else txt
    stop=re.search(r"\n(?:Why Novartis|Commitment to Diversity|Accessibility and accommodation|Novartis is committed)\b",body,re.I)
    if stop:body=body[:stop.start()]
    return clean_text(body),j
def parse_novartis_detail(html,url,fallback=None,from_cache=False):
    f=dict(fallback or {}); soup=BeautifulSoup(html or "","html.parser"); full=clean_text(soup.get_text(" ",strip=True)); low=full.lower(); desc,j=_desc(soup,clean_text(f.get("title")))
    title=clean_text(j.get("title")) or clean_text((soup.find("h1") or {}).get_text(" ",strip=True) if soup.find("h1") else "") or clean_text(f.get("title")); jid=_job_id(url) or clean_text(f.get("external_id")); location=_loc(j) or clean_text(f.get("location")); date=clean_text(j.get("datePosted")) or clean_text(f.get("date_published")); emp=j.get("employmentType"); contract=clean_text(", ".join(emp) if isinstance(emp,list) else emp)
    if not location:
        m=re.search(r"\bLocation\s*:?\s*([^#]+?)(?=\s+#?LI-|\s+Internal job title|\s+This role|$)",full,re.I); location=clean_text(m.group(1)) if m else ""
    closed=any(x in low for x in CLOSED)
    s={**f,"external_id":jid,"novartis_job_id":jid,"title":title,"company":"Novartis","location":location,"contract_type":contract,"date_published":date,"url":url,"closed":closed}
    if closed:return {"success":False,"closed":True,"matching_text":"","matching_text_length":0,"structured":s,"from_cache":from_cache,"error":"Novartis : offre clôturée."}
    if len(desc)<220:return {"success":False,"closed":False,"matching_text":desc,"matching_text_length":len(desc),"structured":s,"from_cache":from_cache,"error":f"Novartis : description trop courte ({len(desc)} caractères)."}
    s["language"]=detect_language(desc); s["dutch_required"]=dutch_professional_required(desc)
    return {"success":True,"closed":False,"matching_text":desc,"matching_text_length":len(desc),"structured":s,"from_cache":from_cache,"error":None}
def get_novartis_job_detail(url,external_id=None,use_cache=True,fallback=None):
    f=dict(fallback or {}); f.setdefault("external_id",external_id or ""); html,fc,err,st=_get(url,use_cache,"detail")
    if not html:return {"success":False,"closed":st==404,"matching_text":"","matching_text_length":0,"structured":{**f,"external_id":external_id or f.get("external_id"),"url":url,"closed":st==404},"from_cache":fc,"error":"Novartis : offre clôturée / HTTP 404" if st==404 else f"Novartis : {err}"}
    return parse_novartis_detail(html,url,f,fc)
def _to_job(d,f):
    s=d.get("structured") or {}; text=clean_text(d.get("matching_text")); job=JobOffer(source="NOVARTIS",external_id=clean_text(s.get("external_id") or f.get("external_id")),title=clean_text(s.get("title") or f.get("title")),company="Novartis",location=clean_text(s.get("location") or f.get("location")),description=text,url=clean_text(s.get("url") or f.get("url")),date_published=clean_text(s.get("date_published") or f.get("date_published")) or None,contract_type=clean_text(s.get("contract_type")) or None,language=clean_text(s.get("language")) or None); job.collection_channel="NOVARTIS"; job.origin_source="NOVARTIS"; job.detail_enrichment_attempted=True; job.detail_enrichment_success=True; job.detail_matching_text=text; job.detail_matching_text_length=len(text); job.novartis_job_id=clean_text(s.get("novartis_job_id") or job.external_id); job.job_category=clean_text(f.get("functional_area")); return job
def collect_novartis_jobs():
    c,meta=collect_novartis_listing_candidates(True); jobs=[]
    for i,item in enumerate(c,1):
        d=get_novartis_job_detail(item.get("url",""),item.get("external_id"),True,item); s=d.get("structured") or {}; title=clean_text(s.get("title") or item.get("title"))
        if d.get("closed"):print(f"[{i:02d}/{len(c):02d}] 💤 CLOSED | {title}");continue
        if not d.get("success"):print(f"[{i:02d}/{len(c):02d}] ⚠️ DETAIL | {title} | {d.get('error')}");continue
        lang=clean_text(s.get("language")).lower() or "unknown"
        if lang=="nl":print(f"[{i:02d}/{len(c):02d}] ⛔ NL     | {title}");continue
        if s.get("dutch_required"):print(f"[{i:02d}/{len(c):02d}] ⛔ DUTCH  | {title}");continue
        job=_to_job(d,item); jobs.append(job); print(f"[{i:02d}/{len(c):02d}] ✅ {lang.upper():<7} | {len(job.description):4d} car. | {job.title} | {job.location}");time.sleep(.08)
    return jobs


# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1
from sources.unified_discovery import matches_master_title

_ud_original__target = _target

def _target(*args, **kwargs):
    if _ud_original__target(*args, **kwargs):
        return True
    try:
        title = args[0] if args else kwargs.get('title', '')
    except Exception:
        return False
    return matches_master_title(title)
