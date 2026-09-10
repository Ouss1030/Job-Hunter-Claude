from bs4 import BeautifulSoup
from urllib.parse import urljoin
from sources.batch3_3_engine import session,clean,page,metrics,print_result

URL="https://www.eyedpharma.com/careers/"

def collect_eyed_shadow():
    s=session(); r=s.get(URL,timeout=30,allow_redirects=True); r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser"); links={}
    for a in soup.find_all("a",href=True):
        href=clean(a.get("href")); text=clean(a.get_text(" ",strip=True))
        u=urljoin(r.url,href).split("#",1)[0]
        if u.startswith("mailto:"): continue
        if "career" in u.lower() or "manager" in u.lower() or "/rd-" in u.lower() or "/qa-" in u.lower():
            if u.rstrip("/")!=URL.rstrip("/"): links[u]=text
    # Known current direct offer is also discoverable from page text.
    if "R&D QA Manager" in clean(soup.get_text(" ",strip=True)):
        links.setdefault(urljoin(r.url,"/rd-qa-manager/"),"R&D QA Manager")

    rows=[]
    for u,title in links.items():
        try: d=page(s,u)
        except Exception: continue
        if not d["title"]: d["title"]=title
        if not d["location"]: d["location"]="Seraing, Belgium"; d["geo"]="BELGIUM"
        rows.append(d)

    kept,m=metrics(rows)
    print_result("EYED_PHARMA",kept,m)
    return kept,m,rows
