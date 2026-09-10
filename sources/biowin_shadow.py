from bs4 import BeautifulSoup
from urllib.parse import urljoin
from sources.batch3_3_engine import session,clean,page,metrics,print_result

URL="https://www.biowin.org/jobs/"

def _listing_title(anchor):
    # BioWin detail links can render only "Learn more". Recover title from card.
    card=anchor.find_parent(["article","li","div"])
    if card:
        for node in card.find_all(["h2","h3","h4","h5","strong"],limit=10):
            t=clean(node.get_text(" ",strip=True))
            if t and t.lower() not in {"learn more","read more"}:
                return t
    t=clean(anchor.get_text(" ",strip=True))
    return "" if t.lower() in {"learn more","read more"} else t

def collect_biowin_shadow():
    s=session(); r=s.get(URL,timeout=30,allow_redirects=True); r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser"); links={}
    for a in soup.find_all("a",href=True):
        href=clean(a.get("href"))
        if "/jobs/" not in href: continue
        u=urljoin(r.url,href).split("#",1)[0]
        if u.rstrip("/")==URL.rstrip("/"): continue
        title=_listing_title(a)
        if title: links[u]=title
    rows=[]
    for u,title in links.items():
        try: d=page(s,u)
        except Exception: continue
        # Never let generic H1 "Learn more" overwrite the listing title.
        detail_title=clean(d["title"])
        if not detail_title or detail_title.lower() in {"learn more","read more"}:
            detail_title=title
        rows.append({**d,"title":detail_title})
    kept,m=metrics(rows)
    print_result("BIOWIN",kept,m)
    return kept,m,rows
