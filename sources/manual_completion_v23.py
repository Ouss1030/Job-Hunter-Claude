
from __future__ import annotations
import hashlib, html as html_lib, json, re, time
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from sources.api_expansion_common import clean, make_job
from sources.source_metrics import publish_source_metrics

VERSION="23.0"
TIMEOUT=28
SESSION=requests.Session()
SESSION.headers.update({
    "User-Agent":"JobHunter/23.0 personal job search; Belgium",
    "Accept-Language":"fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.7,de;q=0.5",
})

CONFIG={
"ADG_OSTBELGIEN":{
 "urls":["https://adg.be/desktopdefault.aspx/tabid-6166/"],
 "local":True,"mode":"general"},
"SGS":{
 "urls":["https://careers.smartrecruiters.com/SGS?search=wavre",
         "https://careers.smartrecruiters.com/SGS?location=Antwerpen&page=0&search=",
         "https://careers.smartrecruiters.com/SGS/"],
 "local":False,"mode":"general"},
"BUREAU_VERITAS":{
 "urls":["https://jobs.bureauveritas.com/search/?q=&locationsearch=Belgium",
         "https://jobs.bureauveritas.com/"],
 "local":False,"mode":"general"},
"CERTECH":{
 "urls":[],
 "local":True,"mode":"general"},
"SIRRIS":{
 "urls":["https://recruitment.sirris.be/fr","https://recruitment.sirris.be/"],
 "local":True,"mode":"general"},
"ABINBEV":{
 "urls":["https://europecareers.ab-inbev.com/fr","https://europecareers.ab-inbev.com/"],
 "local":False,"mode":"general"},
"COLRUYT":{
 "urls":["https://colruytgroup.recruitee.com/","https://jobs.colruytgroup.com/fr",
         "https://jobs.colruytgroup.com/"],
 "local":True,"mode":"general"},
"DELHAIZE":{
 "urls":["https://jobs.delhaize.be/be/fr/search-results","https://jobs.delhaize.be/be/fr"],
 "local":True,"mode":"general"},
"VANDEMOORTELE":{
 "urls":["https://careers.vandemoortele.com/search/?q=&locationsearch=Belgium",
         "https://careers.vandemoortele.com/"],
 "local":False,"mode":"general"},
"IRIS_HOPITAUX":{
 "urls":["https://www.his-izz.be/fr","https://www.his-izz.be/"],
 "local":True,"mode":"general"},
"UZ_BRUSSEL":{
 "urls":["https://www.uzbrusselwerkt.be/alle-vacatures"],
 "local":True,"mode":"general"},
"CHIREC":{
 "urls":["https://jobs.chirec.be/fr/home.aspx","https://chirec2024.dev.talentfinder.be/"],
 "local":True,"mode":"general"},
"BRUSSELS_AIRPORT":{
 "urls":["https://jobs.brusselsairport.be/search/?q=&locationsearch=",
         "https://jobs.brusselsairport.be/viewalljobs/?locale=fr_FR"],
 "local":True,"mode":"general"},
"SWISSPORT_BE":{
 "urls":["https://careers.swissport.com/jobs",
         "https://www.swissport.com/en/careers/search-jobs"],
 "local":False,"mode":"general"},
"BRUXELLES_PROPRETE":{
 "urls":["https://www.talent.brussels/fr/offres-d-emploi?field_employer=124"],
 "local":True,"mode":"covered"},
"DAOUST":{
 "urls":["https://daoust.be/fr/","https://daoust.be/"],
 "local":True,"mode":"general"},
"WALTERS_PEOPLE":{
 "urls":["https://www.robertwalters.be/nl/jobs.html",
         "https://www.robertwalters.be/fr/jobs.html"],
 "local":True,"mode":"general"},
"SDWORX_STAFFING":{
 "urls":["https://www.sdworx.jobs/fr-be/offres-d-emploi?redirected=true",
         "https://www.sdworx.jobs/en-be/jobs"],
 "local":True,"mode":"general"},
"DAOUST_STUDENT":{
 "urls":["https://daoust.be/fr/","https://daoust.be/"],
 "local":True,"mode":"student"},
"UNIQUE_STUDENT":{
 "urls":["https://www.unique.be/fr/offres-demploi/contrat-etudiant/bruxelles",
         "https://www.unique.be/fr/travailler/etudiants/",
         "https://student.unique.be/"],
 "local":True,"mode":"covered"},
}

BAD_TITLE=re.compile(
 r"^(home|accueil|jobs?|careers?|carri[eè]res?|vacancies|vacatures|"
 r"offres? d['’]emploi|emploi|search|zoeken|rechercher|all jobs?|view all jobs?|"
 r"toutes? les offres|apply|postuler|solliciteer|login|profile|read more|"
 r"en savoir plus|meer informatie|candidature spontan[ée]e?)$",re.I)
JOB_URL=re.compile(
 r"(/job/|/jobs/|/vacature|/vacatures/|/vacancy|/vacancies/|/offre|"
 r"/emploi/|/position|/viewjob/|talentfinder|jobid=|vacancyid=|reference=\d+)",re.I)
DISCOVERY_TEXT=re.compile(
 r"\b(job|jobs|vacature|vacatures|offre|offres|emploi|career|careers|"
 r"carri[eè]re|recruitment|recrutement|werken|travailler)\b",re.I)
ATS=re.compile(r"(smartrecruiters|recruitee|teamtailor|successfactors|talentfinder|workday)",re.I)
BELGIUM=re.compile(
 r"\b(Belgium|Belgique|Belgi[ëe]|Brussels|Bruxelles|Wavre|Antwerpen|Antwerp|"
 r"Leuven|Louvain|Halle|Gent|Ghent|Zaventem|Anderlecht|Jette|Ixelles|Elsene|"
 r"Forest|Vorst|Etterbeek|Li[eè]ge|Namur|Charleroi|Mons|Ostbelgien|Eupen)\b",re.I)
STUDENT=re.compile(r"\b(student|étudiant|etudiant|jobstudent|studentenjob|werkstudent)\b",re.I)
INTERNSHIP=re.compile(r"\b(stage|stagiaire|internship|intern\b|trainee|master thesis|tfe)\b",re.I)
SENIOR=re.compile(r"\b(senior|sr\.?|lead|manager|head|director|principal|chef de service)\b",re.I)
QC=re.compile(
 r"\b(qc|quality control|quality analyst|quality specialist|quality engineer|"
 r"quality assurance|qa analyst|qa officer|laboratoire|laboratory|laborant|"
 r"lab technician|laboratoriumtechnoloog|medisch laboratoriumtechnoloog|"
 r"laboratoriumtechnicus|technologue de laboratoire|microbiolog|chimiste|chemist|"
 r"analytical technician|hplc|uplc|st[eé]rilisation)\b",re.I)
DATA=re.compile(
 r"\b(data analyst|data-analist|analyste de donn[ée]es|business intelligence|"
 r"bi analyst|reporting analyst|data analytics|junior data|data reporting)\b",re.I)
HYBRID=re.compile(
 r"\b(lims|data integrity|quality data|lab systems?|laboratory systems?|"
 r"computerized systems? validation|csv specialist)\b",re.I)

def _hash(*parts):
    return hashlib.sha1("|".join(clean(x).lower() for x in parts).encode("utf-8","ignore")).hexdigest()[:22]

def _track(title,context="",mode="general"):
    title=clean(html_lib.unescape(str(title or "")))
    blob=clean(f"{title} {context}")
    if not title or BAD_TITLE.search(title) or INTERNSHIP.search(title):
        return None
    if STUDENT.search(title) or (mode=="student" and STUDENT.search(blob)):
        return "STUDENT_ANY"
    if SENIOR.search(title):
        return None
    if HYBRID.search(blob):
        return "QC_DATA_HYBRID"
    if DATA.search(title):
        return "DATA_JUNIOR_BI"
    if QC.search(title):
        return "QC_PHARMA_LAB"
    return None

def _get(url):
    r=SESSION.get(url,timeout=TIMEOUT,allow_redirects=True)
    r.raise_for_status()
    return r

def _same_or_career_host(base,href):
    try:
        b=(urlparse(base).hostname or "").lower()
        h=(urlparse(href).hostname or "").lower()
        if not h:return False
        if h==b or h.endswith("."+b) or b.endswith("."+h):
            return True
        # Allow known career platform jumps, never arbitrary external browsing.
        return any(x in h for x in (
            "smartrecruiters.com","recruitee.com","teamtailor.com",
            "talentfinder.be","successfactors","swissport.com",
            "robertwalters.be","talent.brussels"
        ))
    except Exception:
        return False

def _extract_links(base_url,html):
    soup=BeautifulSoup(html,"html.parser")
    detail=[];discovery=[];seen=set()
    for a in soup.find_all("a",href=True):
        href=urljoin(base_url,a.get("href"))
        if href in seen or not _same_or_career_host(base_url,href):
            continue
        seen.add(href)
        title=clean(html_lib.unescape(a.get_text(" ",strip=True)))
        context=""
        try:
            parent=a.find_parent(["li","article","tr","div"])
            if parent:
                context=clean(html_lib.unescape(parent.get_text(" ",strip=True)))[:1500]
        except Exception:
            pass
        if title and not BAD_TITLE.search(title) and JOB_URL.search(href):
            detail.append((href,title,context))
        elif title and DISCOVERY_TEXT.search(title):
            discovery.append(href)
    return detail,discovery[:8],soup

def crawl_source(key,extra_urls=None,max_pages=12):
    key=str(key or "").upper()
    cfg=CONFIG.get(key)
    if not cfg:return None
    if cfg.get("mode")=="covered":
        return {"key":key,"ok":False,"covered":True,"reason":"covered_by_parent"}

    queue=[]
    for u in (extra_urls or [])+list(cfg.get("urls") or []):
        if u and u not in queue:queue.append(u)
    visited=[];details={};errors=[];ats=set()
    while queue and len(visited)<max_pages:
        url=queue.pop(0)
        if url in visited:continue
        visited.append(url)
        try:
            r=_get(url)
            raw=r.text or ""
            ats.update(x.lower() for x in ATS.findall(raw[:800000]))
            d,disc,_=_extract_links(r.url,raw)
            for href,title,context in d:
                details[href]=(href,title,context)
            for u in disc:
                if u not in visited and u not in queue and len(queue)<20:
                    queue.append(u)
        except Exception as exc:
            errors.append(f"{url} | {type(exc).__name__}: {exc}")
        time.sleep(0.12)

    mode=cfg.get("mode","general")
    targets=[]
    for href,title,context in details.values():
        tr=_track(title,context,mode)
        if tr:
            targets.append((href,title,context,tr))

    ok=len(details)>=2 or (len(details)>=1 and bool(ats)) or len(targets)>=1
    return {
        "key":key,"ok":ok,"detail_links":len(details),"target_titles":len(targets),
        "ats":sorted(ats),"visited":visited,"errors":errors,
        "validated_url":visited[0] if visited else (cfg.get("urls") or [""])[0],
        "samples":[{"title":t,"url":u,"track":tr} for u,t,c,tr in targets[:10]],
    }

def collect_v23_source(key):
    key=str(key or "").upper()
    cfg=CONFIG.get(key)
    if not cfg:return None
    if cfg.get("mode")=="covered":
        return []
    res=crawl_source(key,max_pages=12)
    if not res or not res.get("ok"):
        publish_source_metrics(key,{"seen":0,"target_title":0,"non_target":0,"detail_ok":0,"detail_failed":1,
            "geography_accepted":0,"geography_rejected":0,"geography_unknown":0,
            "language_rejected":0,"converted":0,"persisted":None,"errors":1})
        return []

    jobs={};seen=0;errors=0
    # Re-crawl visited pages to construct actual target jobs deterministically.
    for url in res.get("visited") or []:
        try:
            r=_get(url);d,_,_=_extract_links(r.url,r.text or "")
        except Exception:
            errors+=1;continue
        for href,title,context in d:
            seen+=1
            tr=_track(title,context,cfg.get("mode","general"))
            if not tr:continue
            if not cfg.get("local") and tr!="STUDENT_ANY":
                if not BELGIUM.search(f"{title} {context} {url}"):
                    continue
            ext=_hash(key,href,title)
            job=make_job(source=key,external_id=ext,title=title,
                company=key.replace("_"," ").title(),location="Belgium",
                description=context or title,url=href,
                contract_type="Student" if tr=="STUDENT_ANY" else None)
            setattr(job,"api_target_track",tr)
            if tr=="STUDENT_ANY":setattr(job,"student_source",True)
            jobs[ext]=job

    publish_source_metrics(key,{"seen":seen,"target_title":len(jobs),
        "non_target":max(0,seen-len(jobs)),"detail_ok":len(jobs),"detail_failed":errors,
        "geography_accepted":len(jobs),"geography_rejected":0,"geography_unknown":0,
        "language_rejected":0,"converted":len(jobs),"persisted":None,"errors":errors})
    print(key,"| V23 | seen=",seen,"| kept=",len(jobs),"| errors=",errors)
    return list(jobs.values())
