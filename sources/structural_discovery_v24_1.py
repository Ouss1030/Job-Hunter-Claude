
from __future__ import annotations
import json,re,time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin,urlparse,quote
import requests
from bs4 import BeautifulSoup

VERSION="24.1"
UA="JobHunter/24.1 personal structural job-source discovery; Belgium"
SESSION=requests.Session()
SESSION.headers.update({
    "User-Agent":UA,
    "Accept-Language":"fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.7,de;q=0.4",
})
TIMEOUT=18

CAREER_TEXT=re.compile(
    r"\b(career|careers|jobs?|vacanc|vacatur|werken bij|werken-bij|work with us|"
    r"join us|recruitment|recrutement|emploi|offres? d['’]emploi|carri[eè]re|"
    r"jobs and careers|job opportunities)\b",re.I)
JOB_URL=re.compile(
    r"(/job/|/jobs/|/vacature|/vacatures/|/vacancy|/vacancies/|/offre|/emploi/|"
    r"/position|jobid=|vacancyid=|requisition|jobdetail|job-details)",re.I)
BELGIUM=re.compile(
    r"\b(Belgium|Belgique|Belgi[ëe]|Brussels|Bruxelles|Brussel|Antwerpen|Antwerp|"
    r"Gent|Ghent|Li[eè]ge|Luik|Charleroi|Namur|Namen|Leuven|Louvain|Mons|Bergen|"
    r"Mechelen|Malines|Hasselt|Kortrijk|Courtrai|Wavre|Zaventem|Vilvoorde|"
    r"Anderlecht|Jette|Ixelles|Elsene|Uccle|Ukkel|Wallonia|Wallonie|Flanders|"
    r"Vlaanderen)\b",re.I)

ATS_PATTERNS={
    "SMARTRECRUITERS":re.compile(r"smartrecruiters\.com",re.I),
    "GREENHOUSE":re.compile(r"greenhouse\.io|boards\.greenhouse",re.I),
    "LEVER":re.compile(r"lever\.co",re.I),
    "RECRUITEE":re.compile(r"recruitee\.com",re.I),
    "TEAMTAILOR":re.compile(r"teamtailor",re.I),
    "WORKDAY":re.compile(r"myworkdayjobs|workdayjobs",re.I),
    "PERSONIO":re.compile(r"personio\.(de|com)|jobs\.personio",re.I),
    "SUCCESSFACTORS":re.compile(r"successfactors|career\d+\.successfactors",re.I),
    "TALENTSOFT":re.compile(r"talent-soft|talentsoft",re.I),
    "TALENTFINDER":re.compile(r"talentfinder",re.I),
    "ASHBY":re.compile(r"ashbyhq",re.I),
    "JOBTOOLZ":re.compile(r"jobtoolz",re.I),
}

ATS_QUERY_PATTERNS=[
    ("SMARTRECRUITERS","careers.smartrecruiters.com/*"),
    ("GREENHOUSE","boards.greenhouse.io/*"),
    ("GREENHOUSE","job-boards.greenhouse.io/*"),
    ("LEVER","jobs.lever.co/*"),
    ("RECRUITEE","*.recruitee.com/*"),
    ("TEAMTAILOR","*.teamtailor.com/*"),
    ("WORKDAY","*.myworkdayjobs.com/*"),
    ("PERSONIO","*.jobs.personio.com/*"),
    ("SUCCESSFACTORS","*.successfactors.com/*"),
    ("ASHBY","jobs.ashbyhq.com/*"),
    ("JOBTOOLZ","*.jobtoolz.com/*"),
]

BELGIUM_TERMS=[
    "Belgium","Belgique","Brussels","Bruxelles","Antwerpen","Ghent","Gent",
    "Liege","Liège","Charleroi","Namur","Leuven","Wavre","Zaventem","Hasselt",
    "Mechelen","Mons","Kortrijk"
]

COMMON_PATHS=[
    "/careers","/jobs","/vacancies","/vacatures","/emploi","/jobs-and-careers",
    "/careers/jobs","/werken-bij","/werkenbij","/fr/jobs","/nl/jobs","/en/jobs",
    "/sitemap.xml","/robots.txt"
]

def domain_of(url):
    try:
        h=(urlparse(url).hostname or "").lower()
        if h.startswith("www."):h=h[4:]
        return h
    except:return ""

def same_domain_or_ats(base,href):
    b=domain_of(base);h=domain_of(href)
    if not h:return False
    if h==b or h.endswith("."+b) or b.endswith("."+h):return True
    return any(p.search(href) for p in ATS_PATTERNS.values())

def ats_from_text(text):
    return sorted(name for name,pat in ATS_PATTERNS.items() if pat.search(text or ""))

def latest_cc():
    try:
        r=SESSION.get("https://index.commoncrawl.org/collinfo.json",timeout=20)
        r.raise_for_status()
        x=r.json()
        return x[0]["id"] if x else None
    except:return None

def cc_query(pattern,index_name=None,limit=100,filter_url=None):
    index_name=index_name or latest_cc()
    if not index_name:return []
    endpoint=f"https://index.commoncrawl.org/{index_name}-index"
    params={"url":pattern,"output":"json","filter":"status:200","collapse":"urlkey","limit":str(limit)}
    try:
        r=SESSION.get(endpoint,params=params,timeout=25)
        if r.status_code!=200:return []
        out=[]
        for line in r.text.splitlines():
            try:u=json.loads(line).get("url","")
            except:continue
            if not u:continue
            if filter_url and not filter_url.search(u):continue
            if u not in out:out.append(u)
        return out
    except:return []

def inspect_page(url):
    result={"url":url,"final_url":url,"ats":[],"career_urls":[],"job_links":[],"belgium":False,"errors":[]}
    try:
        r=SESSION.get(url,timeout=TIMEOUT,allow_redirects=True)
        result["final_url"]=r.url
        if r.status_code>=400:
            result["errors"].append(f"HTTP {r.status_code}")
            return result
        raw=r.text[:1800000]
        result["ats"]=ats_from_text(raw+" "+r.url)
        result["belgium"]=bool(BELGIUM.search(raw[:500000]+" "+r.url))
        soup=BeautifulSoup(raw,"html.parser")
        seen=set()
        for a in soup.find_all("a",href=True):
            href=urljoin(r.url,a.get("href"))
            if href in seen:continue
            seen.add(href)
            txt=" ".join(a.stripped_strings)
            blob=txt+" "+href
            if CAREER_TEXT.search(blob) and same_domain_or_ats(r.url,href):
                result["career_urls"].append(href)
            if JOB_URL.search(href) and same_domain_or_ats(r.url,href):
                result["job_links"].append(href)
        if re.search(r'["\']JobPosting["\']',raw,re.I):
            result["job_links"].append(r.url+"#jsonld-jobposting")
        result["career_urls"]=list(dict.fromkeys(result["career_urls"]))[:20]
        result["job_links"]=list(dict.fromkeys(result["job_links"]))[:30]
        return result
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        return result

def expand_existing_domain(candidate):
    base=candidate["website"]
    root="https://"+domain_of(base)
    pages=[]
    first=inspect_page(base)
    pages.append(first)
    queue=[]
    for u in first["career_urls"][:5]:
        if u not in queue:queue.append(u)
    if not queue:
        queue=[root+p for p in COMMON_PATHS[:10]]
    for u in queue[:10]:
        if any(p["url"]==u for p in pages):continue
        pages.append(inspect_page(u))
        time.sleep(0.08)

    ats=set()
    careers=[]
    jobs=[]
    belg=False
    errors=[]
    for p in pages:
        ats.update(p["ats"]);careers.extend(p["career_urls"]);jobs.extend(p["job_links"])
        belg=belg or p["belgium"];errors.extend(p["errors"])

    confidence="LOW"
    if ats and (jobs or careers):confidence="HIGH"
    elif len(jobs)>=2:confidence="HIGH"
    elif ats or careers:confidence="MEDIUM"
    return {
        **candidate,
        "strategy":"MASTER_DOMAIN_EXPANSION",
        "ats":sorted(ats),
        "career_urls":list(dict.fromkeys(careers))[:20],
        "job_links":list(dict.fromkeys(jobs))[:20],
        "belgium_evidence":belg,
        "confidence":confidence,
        "errors":errors[:12]
    }

def commoncrawl_existing_domain(domain,index_name=None):
    urls=cc_query(f"{domain}/*",index_name=index_name,limit=120,
                  filter_url=re.compile(r"(career|jobs?|vacanc|vacatur|emploi|werken)",re.I))
    return urls[:30]

def ats_seed_discovery(index_name=None,per_query=80):
    found={}
    for ats_name,pattern in ATS_QUERY_PATTERNS:
        urls=cc_query(pattern,index_name=index_name,limit=per_query)
        for u in urls:
            # Keep URLs that have a Belgium-ish term in URL, if available.
            # Generic board root may still be kept for live Belgium validation.
            d=domain_of(u)
            key=u.split("#",1)[0]
            if key not in found:
                found[key]={"url":u,"ats_hint":ats_name,"domain":d}
    return list(found.values())

def ats_belgium_targeted(index_name=None,per_term=60):
    found={}
    # We cannot full-text-search Common Crawl index, but many ATS URLs include location terms.
    # This is a cheap targeted pass, later live-validated.
    for ats_name,pattern in ATS_QUERY_PATTERNS:
        urls=cc_query(pattern,index_name=index_name,limit=per_term*3)
        for u in urls:
            if any(term.lower() in u.lower() for term in BELGIUM_TERMS):
                found[u]={"url":u,"ats_hint":ats_name,"domain":domain_of(u)}
    return list(found.values())

def verify_ats_candidate(seed):
    p=inspect_page(seed["url"])
    belg=p["belgium"]
    # Some board pages hide location in JS; job URLs may still prove a live board.
    live_jobs=len(p["job_links"])
    ats=sorted(set(p["ats"]+[seed.get("ats_hint","")])-{""})
    confidence="LOW"
    if belg and (ats or live_jobs):confidence="HIGH"
    elif belg:confidence="MEDIUM"
    elif live_jobs>=2 and ats:confidence="MEDIUM"
    return {
        **seed,
        "strategy":"COMMONCRAWL_ATS",
        "ats":ats,
        "career_urls":p["career_urls"],
        "job_links":p["job_links"],
        "belgium_evidence":belg,
        "confidence":confidence,
        "errors":p["errors"]
    }
