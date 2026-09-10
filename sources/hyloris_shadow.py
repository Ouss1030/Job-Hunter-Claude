from bs4 import BeautifulSoup
from urllib.parse import urljoin
from sources.batch3_3_engine import session,clean,geo_status,dutch_hard,title_is_target,metrics,print_result

URL="https://hyloris.com/careers/"

def collect_hyloris_shadow():
    s=session(); r=s.get(URL,timeout=30,allow_redirects=True); r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    rows=[]; seen=set()

    # Vacancies are currently rendered inline on the careers page.
    for heading in soup.find_all(["h4","h5","h3","h2"]):
        title=clean(heading.get_text(" ",strip=True))
        if not title or title.lower() in {"latest vacancies","grow with us","why join us"}:
            continue
        card=heading.find_parent(["article","section","div"]) or heading.parent
        text=clean(card.get_text(" ",strip=True)) if card else title
        if "location:" not in text.lower() and not title_is_target(title):
            continue
        low=text.lower()
        location="Liège, Belgium" if ("liège" in low or "liege" in low) else ("Belgium" if "belgium" in low else "")
        key=(title,location)
        if key in seen: continue
        seen.add(key)
        rows.append({"title":title,"location":location,"geo":geo_status(location or text),
                     "description":text,"hard_dutch":dutch_hard(text),"url":r.url})

    kept,m=metrics(rows)
    print_result("HYLORIS",kept,m)
    return kept,m,rows
