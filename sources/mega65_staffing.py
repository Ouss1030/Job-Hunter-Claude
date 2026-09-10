from __future__ import annotations

import gzip
import io
import json
import re
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.batch4_engine import publish_metrics

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36"
TIMEOUT = 30
MAX_SITEMAPS = 24
MAX_DISCOVERED = 500
MAX_CANDIDATE_DETAILS = 90

# JOBHUNTER_STAFFING_RECALL_REPAIR_V2
MANPOWER_MAX_DISCOVERED = 6500
MANPOWER_MAX_SITEMAPS = 80
LETS_WORK_MAX_LISTING_PAGES = 25

# JOBHUNTER_RAW_CATALOG_PRODUCTION_V2
AGO_MAX_DISCOVERED = 7000
AGILITAS_MAX_DISCOVERED = 3000
AGO_MAX_CANDIDATE_DETAILS = 180
AGILITAS_MAX_CANDIDATE_DETAILS = 60

_LAST_DIAG = {}
_MEGA65_STATE_LOCK = threading.RLock()

TITLE_EXCLUDE = re.compile(
    r"\b(?:senior|sr\.?|principal|staff|director|head|manager|management|"
    r"team\s+leader|leader|supervisor|intern(?:ship)?|stage|trainee|"
    r"apprentice|phd)\b",
    re.I,
)

TRACK_PATTERNS = {
    "DATA_BI": [
        r"\bdata analyst\b", r"\bjunior data analyst\b",
        r"\bbusiness data analyst\b", r"\banalyste de donn[eé]es\b",
        r"\bdata-analist\b", r"\bbi analyst\b",
        r"\bbusiness intelligence analyst\b", r"\bbi developer\b",
        r"\bpower\s*bi\b", r"\breporting analyst\b",
        r"\breporting officer\b", r"\banalytics analyst\b",
        r"\binsights analyst\b", r"\bbusiness analyst\b",
        r"\bjunior business analyst\b", r"\bfunctional analyst\b",
        r"\banalyste fonctionnel\b", r"\bprocess analyst\b",
        r"\boperations analyst\b", r"\bdata quality\b",
        r"\bdata steward\b", r"\bmaster data\b",
        r"\bdata governance\b", r"\bdata coordinator\b",
        r"\bdata management\b",
    ],
    "CHEM_LAB": [
        r"\bqc\b", r"\bquality control\b", r"\bcontr[oô]le qualit[eé]\b",
        r"\bquality assurance\b", r"\bassurance qualit[eé]\b",
        # JOBHUNTER_STAFFING_RECALL_REPAIR_V1 - quality-role recall
        r"\bquality (?:officer|associate|specialist|technician|controller)\b",
        r"\b(?:agent|assistant|collaborateur|technicien(?:ne)?)\s+(?:de\s+)?(?:contr[oô]le\s+)?qualit[eé]\b",
        r"\bcontr[oô]leur(?:euse)?\s+qualit[eé]\b",
        r"\bop[eé]rateur(?:trice)?\s+qualit[eé]\b",
        r"\bqa (?:officer|associate|specialist|technician)\b",
        r"\blaborantin\b", r"\blab(?:oratory)?\s+(?:technician|analyst|assistant)\b",
        r"\btechnicien(?:ne)?\s+(?:de\s+)?laboratoire\b",
        r"\banalyste\s+(?:de\s+)?laboratoire\b",
        r"\btechnicien(?:ne)? chimiste\b",
        r"\banalytical (?:technician|analyst)\b",
        r"\bmicrobiology\b", r"\bmicrobiologie\b",
        r"\bqualification\b", r"\bvalidation\b", r"\bcsv\b",
        r"\bcomputer(?:ized)? system validation\b",
        r"\bhplc\b", r"\buplc\b", r"\blc-ms\b", r"\bgc-ms\b",
        r"\bstability\b", r"\benvironmental monitoring\b",
        r"\bformulation\b", r"\bcell culture\b",
    ],
    "HYBRID": [
        r"\blims analyst\b", r"\blims specialist\b",
        r"\blaboratory informatics\b", r"\blab systems? analyst\b",
        r"\blaboratory data analyst\b", r"\blab data analyst\b",
        r"\bqc data analyst\b", r"\bquality data analyst\b",
        r"\bdata integrity analyst\b", r"\bscientific data\b",
        r"\bdigital qc\b", r"\beln business analyst\b", r"\beln analyst\b",
        r"\bmanufacturing data analyst\b",
    ],
}

GENERIC_PRODUCTION = re.compile(
    r"\b(?:production operator|production technician|manufacturing technician|"
    r"process technician|op[eé]rateur(?:trice)? de production|"
    r"technicien(?:ne)? de production)\b",
    re.I,
)

SCIENCE_CONTEXT = re.compile(
    r"\b(?:pharma|pharmaceutical|biotech|life sciences?|laboratory|laboratoire|"
    r"chemistry|chimie|chemical|gmp|bpf|qc|quality control|microbiology|"
    r"analytical|hplc|uplc|lims|clean ?room|salle blanche)\b",
    re.I,
)

DUTCH_HARD = [
    r"\bcommunicatief\s+vaardig\s+in\s+het\s+nederlands\b",
    r"\bcommunicatief\s+(?:in\s+)?(?:het\s+)?nederlands\b",
    r"\b(?:zeer\s+)?goede\s+kennis\s+(?:van\s+het\s+)?nederlands\b",
    r"\buitstekende\s+kennis\s+(?:van\s+het\s+)?nederlands\b",
    r"\bvlotte?\s+kennis\s+(?:van\s+het\s+)?nederlands\b",
    r"\bvloeiend\s+(?:in\s+)?(?:het\s+)?nederlands\b",
    r"\b(?:je|jij|u)\s+spreekt\s+(?:zeer\s+)?goed\s+nederlands\b",
    r"\bnederlands\s+op\s+professioneel\s+niveau\b",
    r"\bnederlands\s+(?:is\s+)?vereist\b",
    r"\bfluent\s+(?:in\s+)?dutch\b",
    r"\bprofessional\s+(?:level\s+)?dutch\b",
    r"\bdutch\s+(?:is\s+)?(?:required|mandatory)\b",
    r"\btweetalig\b",
    r"\bn[eé]erlandais\s+(?:est\s+)?(?:exig[eé]|requis|obligatoire)\b",
]

NL_WORDS = (
    "voor onze", "wij zijn", "jouw", "je bent", "ervaring", "opleiding",
    "nederlands", "werkervaring", "functie", "verantwoordelijkheden",
    "vaardigheden", "wat zoeken we", "wat bieden we", "solliciteer",
    "minstens", "bij voorkeur", "kennis van",
)
FR_WORDS = (
    "nous recherchons", "vous êtes", "votre profil", "expérience",
    "formation", "français", "responsabilités", "compétences",
    "nous offrons", "postuler",
)
EN_WORDS = (
    "we are looking", "you are", "your profile", "experience",
    "requirements", "responsibilities", "skills", "english", "apply",
    "we offer",
)

BELGIUM_COUNTRIES = {"be", "bel", "belgium", "belgique", "belgië", "belgie"}
BELGIUM_CITIES = {
    "brussels", "bruxelles", "antwerp", "antwerpen", "ghent", "gent",
    "leuven", "liege", "liège", "charleroi", "namur", "mons", "wavre",
    "nivelles", "seraing", "gosselies", "tournai", "mouscron", "verviers",
    "arlon", "hasselt", "mechelen", "machelen", "zaventem", "puurs",
    "geel", "lessines", "braine-l'alleud", "louvain-la-neuve", "ottignies",
    "roeselare", "waregem", "kortrijk", "brugge", "aalst", "genk",
    "ardooie", "wingene", "maldegem", "dilbeek", "grimbergen",
}
FOREIGN_COUNTRIES = {
    "france", "germany", "netherlands", "luxembourg", "united kingdom",
    "united states", "usa", "canada", "india", "singapore", "qatar",
    "papua new guinea", "switzerland", "italy", "spain", "poland",
    "ireland", "sweden",
}

TARGET_SLUG_TOKENS = (
    "data", "analyst", "business-analyst", "functional-analyst", "bi-",
    "power-bi", "report", "quality", "qc-", "qa-", "labor", "lab-",
    "validation", "qualification", "microbi", "lims", "stability",
    "hplc", "uplc", "formulation",
)


@dataclass(frozen=True)
class Feed:
    key: str
    company: str
    base: str
    url_pattern: str | None = None
    global_geo: bool = False


FEEDS = {
    "ADECCO": Feed(
        "ADECCO",
        "Adecco Belgium",
        "https://www.adecco.com/fr-be/offres-emploi",
        r"/fr-be/offres-emploi/[^/?#]+/\d+-\d+-\d+/?$",
    ),
    "MANPOWER": Feed(
        "MANPOWER",
        "Manpower Belgium",
        "https://www.manpower.be/fr/emplois",
        r"/(?:fr/emploi|job)/[^/?#]+-\d+/?$",
    ),
    "VIVALDIS": Feed("VIVALDIS", "Vivaldis",
        "https://www.vivaldisinterim.be/fr/jobs",
        r"/fr/jobs/.+-a0t[A-Za-z0-9]+"),
    "MICHAEL_PAGE": Feed("MICHAEL_PAGE", "Michael Page BeLux",
        "https://www.michaelpage.be/fr/jobs/belgique",
        r"/job-detail/.+/ref/(?:jn-|[a-z0-9-]+)"),
    "SELECT_HR": Feed("SELECT_HR", "Select HR",
        "https://www.selecthr.be/fr/accueil/"),
    "AGILITAS": Feed("AGILITAS", "Proman / ex-Agilitas",
        "https://www.proman.be/fr/emplois/",
        r"/(?:fr/emplois|vacatures)/[^/?#]+/?$"),
    "AGO": Feed("AGO", "AGO Jobs & HR",
        "https://www.ago.jobs/fr",
        r"/(?:fr|nl|en)/jobs/[^/?#]+"),
    "LETS_WORK": Feed("LETS_WORK", "Let's Work",
        "https://www.letswork.be/fr/emplois/",
        r"/fr/emplois/[^/?#]+-(?:PO-)?[A-Za-z0-9]+/?$"),
    "QJOBS": Feed("QJOBS", "Q Jobs",
        "https://www.qjobs.be/fr"),
    "OXFORD_GLOBAL": Feed("OXFORD_GLOBAL", "Oxford Global Resources",
        "https://www.oxfordcorp.com/all-jobs/",
        r"/jobs/[A-Za-z0-9]+/?$", True),
    "BRUNEL": Feed("BRUNEL", "Brunel Belgium",
        "https://www.brunel.net/nl-be/jobs",
        r"/(?:nl-be|en)/jobs/.+-(?:pr|cr|vc)-\d+", True),
    "AUSTIN_BRIGHT": Feed("AUSTIN_BRIGHT", "Austin Bright",
        "https://austinbright.com/"),
    "PROGRESSIVE": Feed("PROGRESSIVE", "Progressive Recruitment",
        "https://www.progressiverecruitment.com/en-be/", None, True),
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()



# JOBHUNTER_STAFFING_RECALL_REPAIR_V1
def url_title_hint(url):
    """Recover a title-like string from a staffing vacancy URL."""
    parts = [
        unquote(x)
        for x in urlparse(clean(url)).path.strip("/").split("/")
        if clean(x)
    ]
    if not parts:
        return ""

    segment = parts[-1]

    # Adecco: title is penultimate segment, final segment is numeric reference.
    if re.fullmatch(r"\d+-\d+-\d+", segment) and len(parts) >= 2:
        segment = parts[-2]

    # Manpower / Let's Work commonly append a vacancy reference.
    segment = re.sub(r"-PO-[A-Z0-9]{3,}$", "", segment, flags=re.I)
    segment = re.sub(r"-(?=[A-Z0-9]*\d)[A-Z0-9]{5,}$", "", segment, flags=re.I)
    segment = re.sub(r"-\d{2,}$", "", segment)

    return clean(re.sub(r"[-_]+", " ", segment))


def url_target_hint(feed, url):
    """High-signal URL prefilter: semantic slug first, legacy tokens second."""
    hint = url_title_hint(url)

    if track_hits(hint):
        return True

    if GENERIC_PRODUCTION.search(hint) and SCIENCE_CONTEXT.search(hint):
        return True

    low = unquote(clean(url)).lower()
    return any(token in low for token in TARGET_SLUG_TOKENS)


def session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.2",
    })
    return s


def track_hits(title):
    title = clean(title)
    out = []
    for track, pats in TRACK_PATTERNS.items():
        if any(re.search(p, title, re.I) for p in pats):
            out.append(track)
    return out


def language_hint(text):
    low = clean(text).lower()
    scores = {
        "NL": sum(low.count(x) for x in NL_WORDS),
        "FR": sum(low.count(x) for x in FR_WORDS),
        "EN": sum(low.count(x) for x in EN_WORDS),
    }
    best = max(scores, key=scores.get)
    others = [v for k, v in scores.items() if k != best]
    if scores[best] >= 4 and scores[best] >= max(others) + 2:
        return best
    return "UNKNOWN"


def hard_dutch(text):
    """Reject only an explicit professional-Dutch requirement.

    Page language alone is not a hard requirement. A Dutch-language vacancy
    may still be relevant and must reach the downstream matcher/gate unless
    the text explicitly requires Dutch at a professional level.
    """
    low = clean(text).lower()
    return any(re.search(p, low, re.I) for p in DUTCH_HARD)


def years_required(text):
    vals = []
    for pat in (
        r"\b(?:minimum|min\.?|at least|minstens)\s+(\d+)\+?\s+(?:years?|jaar)\b",
        r"\b(\d+)\s*[-–]\s*(\d+)\s+(?:years?|jaar)\b",
        r"\b(\d+)\+?\s+years?\s+(?:of\s+)?experience\b",
        r"\b(\d+)\+?\s+ans?\s+d['’ ]exp[eé]rience\b",
        r"\b(\d+)\+?\s+jaar\s+ervaring\b",
    ):
        for m in re.finditer(pat, clean(text), re.I):
            for g in m.groups():
                if g is None:
                    continue
                try:
                    value = int(g)
                except Exception:
                    continue
                if 0 <= value <= 15:
                    vals.append(value)
    return max(vals) if vals else None


def parse_jsonld(soup):
    jobs = []
    for script in soup.find_all("script", type=lambda x: x and "ld+json" in x.lower()):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop()
            if isinstance(obj, list):
                stack.extend(obj)
                continue
            if not isinstance(obj, dict):
                continue
            if isinstance(obj.get("@graph"), list):
                stack.extend(obj["@graph"])
            typ = obj.get("@type")
            types = typ if isinstance(typ, list) else [typ]
            if any(str(t).lower() == "jobposting" for t in types if t):
                jobs.append(obj)
    return jobs


def normalize_country(value):
    if isinstance(value, dict):
        value = value.get("name") or value.get("@id") or value.get("value") or ""
    return clean(value).lower()


def structured_location(obj):
    countries = []
    cities = []
    parts = []

    def walk(v):
        if isinstance(v, dict):
            addr = v.get("address")
            if isinstance(addr, dict):
                country = normalize_country(addr.get("addressCountry"))
                city = clean(addr.get("addressLocality"))
                region = clean(addr.get("addressRegion"))
                if country:
                    countries.append(country)
                if city:
                    cities.append(city.lower())
                for x in (city, region, country):
                    if x:
                        parts.append(clean(x))
            country = normalize_country(v.get("addressCountry"))
            city = clean(v.get("addressLocality"))
            if country:
                countries.append(country)
            if city:
                cities.append(city.lower())
            for key in ("jobLocation", "applicantLocationRequirements"):
                if key in v:
                    walk(v[key])
        elif isinstance(v, list):
            for item in v:
                walk(item)

    walk(obj.get("jobLocation") or obj.get("applicantLocationRequirements"))
    return list(dict.fromkeys(countries)), list(dict.fromkeys(cities)), " | ".join(dict.fromkeys(parts))


def strict_geo(obj, page_text, global_geo):
    countries, cities, location = structured_location(obj)

    if countries:
        if any(c in BELGIUM_COUNTRIES for c in countries):
            return "BE", location
        return "FOREIGN", location

    if any(c in BELGIUM_CITIES for c in cities):
        return "BE", location

    low = clean(page_text[:2600]).lower()

    # Never infer Belgium from tiny tokens such as "be".
    for city in BELGIUM_CITIES:
        if re.search(rf"(?<![a-z]){re.escape(city)}(?![a-z])", low):
            return "BE", location or city.title()

    for country in FOREIGN_COUNTRIES:
        if re.search(rf"(?<![a-z]){re.escape(country)}(?![a-z])", low):
            return "FOREIGN", location

    # Local Belgian portals can still be healthy with unknown geo, but no job is kept.
    return "UNKNOWN", location


def xml_locs(text):
    try:
        root = ET.fromstring(text)
    except Exception:
        return []
    return [
        clean(elem.text)
        for elem in root.iter()
        if elem.tag.lower().endswith("loc") and elem.text
    ]


def fetch_text(s, url):
    r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
    if r.status_code != 200:
        return r, ""
    content = r.content
    ctype = (r.headers.get("content-type") or "").lower()
    if url.lower().endswith(".gz") or "gzip" in ctype:
        try:
            content = gzip.GzipFile(fileobj=io.BytesIO(content)).read()
        except Exception:
            pass
    try:
        text = content.decode(r.encoding or "utf-8", errors="replace")
    except Exception:
        text = content.decode("utf-8", errors="replace")
    return r, text


def discover(feed):
    s = session()
    parsed = urlparse(feed.base)
    root = f"{parsed.scheme}://{parsed.netloc}/"

    queue = [urljoin(root, "sitemap.xml")]
    seen_maps = set()
    urls = set()

    max_discovered = {
        "MANPOWER": MANPOWER_MAX_DISCOVERED,
        "AGO": AGO_MAX_DISCOVERED,
        "AGILITAS": AGILITAS_MAX_DISCOVERED,
    }.get(feed.key, MAX_DISCOVERED)
    max_sitemaps = MANPOWER_MAX_SITEMAPS if feed.key == "MANPOWER" else MAX_SITEMAPS

    while queue and len(seen_maps) < max_sitemaps and len(urls) < max_discovered:
        sm = queue.pop(0)
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        try:
            r, text = fetch_text(s, sm)
        except Exception:
            continue
        if r.status_code != 200 or not text:
            continue

        for loc in xml_locs(text):
            low = loc.lower()
            if low.endswith((".xml", ".xml.gz")) and len(queue) < MAX_SITEMAPS * 3:
                queue.append(loc)
                continue
            if feed.url_pattern:
                # A source-specific vacancy regex is authoritative. Do not fall
                # through to generic category/blog URLs when it does not match.
                if re.search(feed.url_pattern, loc, re.I):
                    urls.add(loc)
            elif any(x in low for x in (
                "/job/", "/jobs/", "/emploi/", "/emplois/", "/vacature/",
                "/vacancies/", "/job-detail/", "/offre",
            )):
                urls.add(loc)
            if len(urls) >= max_discovered:
                break

    # Also inspect the official listing page.
    try:
        r = s.get(feed.base, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                u = urljoin(r.url, a["href"]).split("#", 1)[0]
                if feed.url_pattern:
                    if re.search(feed.url_pattern, u, re.I):
                        urls.add(u)
                elif any(x in u.lower() for x in (
                    "/job/", "/jobs/", "/emploi/", "/emplois/", "/vacature/",
                    "/vacancies/", "/job-detail/", "/offre",
                )):
                    urls.add(u)
    except Exception:
        pass


    # JOBHUNTER_STAFFING_RECALL_REPAIR_V2
    # Let's Work exposes the full French catalogue through normal ?page=N pagination.
    # The previous generic collector only saw the first page (~25 jobs).
    if feed.key == "LETS_WORK":
        stagnant_pages = 0
        for page in range(1, LETS_WORK_MAX_LISTING_PAGES + 1):
            page_url = feed.base
            separator = "&" if "?" in page_url else "?"
            page_url = f"{page_url}{separator}orderby=alphabetically&page={page}"
            before = len(urls)
            try:
                rr = s.get(page_url, timeout=TIMEOUT, allow_redirects=True)
                if rr.status_code != 200:
                    break
                page_soup = BeautifulSoup(rr.text, "html.parser")
                page_job_links = 0
                for a in page_soup.find_all("a", href=True):
                    u = urljoin(rr.url, a["href"]).split("#", 1)[0]
                    if feed.url_pattern and re.search(feed.url_pattern, u, re.I):
                        urls.add(u)
                        page_job_links += 1
                if page_job_links == 0:
                    break
            except Exception:
                break

            if len(urls) == before:
                stagnant_pages += 1
            else:
                stagnant_pages = 0

            if stagnant_pages >= 2:
                break

    return sorted(urls), len(seen_maps)


def real_job_evidence(feed, url, soup, obj, text):
    if obj:
        return True
    if feed.url_pattern and re.search(feed.url_pattern, url, re.I):
        return True

    h1 = soup.find("h1")
    h1t = clean(h1.get_text(" ", strip=True)) if h1 else ""
    has_apply = bool(re.search(r"\b(?:apply|postuler|solliciteer)\b", text[:5000], re.I))
    has_ref = bool(re.search(
        r"\b(?:job|vacancy|reference|référence|ref\.?)\s*(?:id|nr|number|no)?[:# ]+[A-Z0-9-]{5,}\b",
        text[:5000],
        re.I,
    ))
    return bool(h1t and len(h1t) < 200 and has_apply and has_ref)


def external_id(feed, obj, url):
    identifier = obj.get("identifier") if obj else None
    if isinstance(identifier, dict):
        identifier = identifier.get("value") or identifier.get("name")
    identifier = clean(identifier)
    if identifier:
        return identifier

    for pattern in (
        r"/ref/(jn-[a-z0-9-]+)",
        r"-a0t([A-Za-z0-9]+)",
        r"/jobs/([A-Za-z0-9]+)/?$",
        r"/(\d{5,})/?$",
    ):
        m = re.search(pattern, url, re.I)
        if m:
            return m.group(1)

    return re.sub(r"[^A-Za-z0-9]+", "-", url)[-100:]


def evaluate(feed, url):
    s = session()
    r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
    if r.status_code in {404, 410}:
        return {"closed": True}
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    page_text = clean(soup.get_text(" ", strip=True))
    objs = parse_jsonld(soup)
    obj = objs[0] if objs else {}

    if not real_job_evidence(feed, r.url, soup, obj, page_text):
        return {"not_real": True}

    title = clean(obj.get("title") or obj.get("name"))
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = clean(h1.get_text(" ", strip=True))
    if len(title) > 220:
        title = ""

    desc = clean(
        BeautifulSoup(str(obj.get("description") or ""), "html.parser").get_text(" ", strip=True)
    )
    if len(desc) < 200:
        desc = page_text

    tracks = track_hits(title)
    if not tracks and GENERIC_PRODUCTION.search(title):
        if SCIENCE_CONTEXT.search(title + " " + desc[:4000]):
            tracks = ["CHEM_LAB"]

    geo, location = strict_geo(obj, page_text, feed.global_geo)
    yrs = years_required(desc)

    if not tracks:
        fit = "NOT_TARGET"
    elif TITLE_EXCLUDE.search(title):
        fit = "REJECT_SENIORITY"
    elif geo != "BE":
        fit = "REJECT_GEO"
    elif hard_dutch(desc):
        fit = "REJECT_DUTCH"
    elif yrs is not None and yrs >= 4:
        fit = "REJECT_EXPERIENCE"
    elif yrs == 3:
        fit = "STRETCH"
    else:
        fit = "GOOD"

    return {
        "closed": False,
        "not_real": False,
        "title": title,
        "description": desc,
        "tracks": tracks,
        "geo": geo,
        "location": location,
        "years": yrs,
        "fit": fit,
        "url": r.url,
        "obj": obj,
    }


def make_job(feed, row):
    return JobOffer(
        source=feed.key,
        external_id=external_id(feed, row["obj"], row["url"]),
        title=clean(row["title"]),
        company=feed.company,
        location=clean(row["location"]) or "Belgium",
        description=clean(row["description"]),
        url=clean(row["url"]),
        date_published=None,
        contract_type=None,
        language=None,
    )


def dedupe_exact_jobs(jobs):
    """Remove only exact-content duplicates; preserve genuinely distinct vacancies."""
    out = []
    seen = set()
    for job in jobs:
        title = clean(getattr(job, "title", "")).lower()
        location = clean(getattr(job, "location", "")).lower()
        description = clean(getattr(job, "description", "")).lower()
        # Exact-content key: title + location + normalized description.
        # URL/external id are intentionally excluded because duplicate agency pages
        # can expose the same vacancy under several identifiers.
        key = (title, location, description)
        if key in seen:
            continue
        seen.add(key)
        out.append(job)
    return out


def collect_generic(key):
    feed = FEEDS[key]
    urls, sitemap_count = discover(feed)

    target_urls = [
        u for u in urls
        if url_target_hint(feed, u)
    ]

    # Candidate URLs first; source-specific caps prevent large multilingual
    # catalogues from silently truncating relevant candidates.
    max_candidate_details = {
        "AGO": AGO_MAX_CANDIDATE_DETAILS,
        "AGILITAS": AGILITAS_MAX_CANDIDATE_DETAILS,
    }.get(feed.key, MAX_CANDIDATE_DETAILS)
    probe_urls = target_urls[:max_candidate_details]
    if not probe_urls:
        probe_urls = urls[:3]

    jobs = []
    candidates = 0
    rejected_language = 0
    rejected_geo = 0
    rejected_experience = 0
    rejected_seniority = 0
    closed = 0
    errors = 0
    detail_ok = 0
    not_real = 0
    non_target_detail = 0

    for url in probe_urls:
        try:
            row = evaluate(feed, url)
        except Exception:
            errors += 1
            continue

        if row.get("closed"):
            closed += 1
            continue
        if row.get("not_real"):
            not_real += 1
            continue

        detail_ok += 1

        if not row["tracks"]:
            non_target_detail += 1
            continue

        candidates += 1

        if row["fit"] == "REJECT_GEO":
            rejected_geo += 1
            continue
        if row["fit"] == "REJECT_DUTCH":
            rejected_language += 1
            continue
        if row["fit"] == "REJECT_EXPERIENCE":
            rejected_experience += 1
            continue
        if row["fit"] == "REJECT_SENIORITY":
            rejected_seniority += 1
            continue
        if row["fit"] == "NOT_TARGET":
            continue
        if row["fit"] not in {"GOOD", "STRETCH"}:
            continue

        jobs.append(make_job(feed, row))

    jobs_before_dedupe = len(jobs)
    jobs = dedupe_exact_jobs(jobs)
    duplicates_removed = jobs_before_dedupe - len(jobs)

    metrics = {
        "seen": len(urls),
        "candidates": candidates,
        "kept": len(jobs),
        # Only evaluated pages may be called NON_TARGET.
        "non_target": non_target_detail,
        "unprobed": max(0, len(urls) - len(probe_urls)),
        "detail_probed": len(probe_urls),
        "target_url_hints": len(target_urls),
        "rejected_language": rejected_language,
        "rejected_geo": rejected_geo,
        "rejected_seniority": rejected_seniority,  # JOBHUNTER_BRUNEL_COUNTERS_V1
        "rejected_experience": rejected_experience,
        "closed": closed,
        "detail_errors": errors,
    }

    # PERFORMANCE BIG GAINS V1
    # Network sessions are local. Only shared diagnostics/metrics publication
    # is serialized, keeping the expensive HTTP work fully concurrent.
    with _MEGA65_STATE_LOCK:
        publish_metrics(feed.key, metrics)

        _LAST_DIAG[feed.key] = {
            "metrics": dict(metrics),
            "sitemaps_checked": sitemap_count,
            "discovered_urls": len(urls),
            "target_urls": len(target_urls),
            "detail_probe_ok": detail_ok,
            "non_target_detail": non_target_detail,
            "unprobed": max(0, len(urls) - len(probe_urls)),
            "not_real": not_real,
            "rejected_experience": rejected_experience,
            "rejected_seniority": rejected_seniority,
            "duplicates_removed": duplicates_removed,
            "strict_geo": True,
            "strict_language": True,
        }

    print()
    print("=" * 94)
    print(feed.key)
    print("=" * 94)
    for k, v in metrics.items():
        print(f"{k:<22}: {v}")
    for job in jobs:
        print("KEEP |", job.title, "|", job.location)

    return jobs


def get_mega65_diag(key):
    with _MEGA65_STATE_LOCK:
        return dict(_LAST_DIAG.get(str(key).upper(), {}))


def collect_adecco_jobs(): return collect_generic("ADECCO")
def collect_manpower_jobs(): return collect_generic("MANPOWER")
def collect_vivaldis_jobs(): return collect_generic("VIVALDIS")
def collect_michael_page_jobs(): return collect_generic("MICHAEL_PAGE")
def collect_select_hr_jobs(): return collect_generic("SELECT_HR")
def collect_agilitas_jobs(): return collect_generic("AGILITAS")
def collect_ago_jobs(): return collect_generic("AGO")
def collect_lets_work_jobs(): return collect_generic("LETS_WORK")
def collect_qjobs_jobs(): return collect_generic("QJOBS")
def collect_oxford_global_jobs(): return collect_generic("OXFORD_GLOBAL")
def collect_brunel_jobs(): return collect_generic("BRUNEL")
def collect_austin_bright_jobs(): return collect_generic("AUSTIN_BRIGHT")
def collect_progressive_jobs(): return collect_generic("PROGRESSIVE")


def regression_checks():
    fake_fr = {"jobLocation": {"address": {
        "addressLocality": "Puteaux", "addressCountry": "France"}}}
    fake_png = {"jobLocation": {"address": {
        "addressLocality": "Port Moresby", "addressCountry": "Papua New Guinea"}}}
    fake_be = {"jobLocation": {"address": {
        "addressLocality": "Liège", "addressCountry": "Belgium"}}}

    return {
        "puteaux_france_not_be": strict_geo(fake_fr, "", True)[0] == "FOREIGN",
        "papua_new_guinea_not_be": strict_geo(fake_png, "", True)[0] == "FOREIGN",
        "liege_belgium_is_be": strict_geo(fake_be, "", False)[0] == "BE",
        "dutch_sentence_rejected": hard_dutch(
            "Voor onze klant zoeken we een Data Analyst. Goede kennis van het Nederlands is vereist."
        ),
        "business_analyst_is_data_track": "DATA_BI" in track_hits("Business Analyst"),
        "qc_analyst_is_lab_track": "CHEM_LAB" in track_hits("QC Analyst"),
        "quality_controller_is_lab_track": "CHEM_LAB" in track_hits("Contrôleur qualité"),
        "quality_officer_is_lab_track": "CHEM_LAB" in track_hits("Quality Officer"),
        "adecco_url_title_hint": "CHEM_LAB" in track_hits(url_title_hint(
            "https://www.adecco.com/fr-be/offres-emploi/technicien-de-laboratoire-seneffe-hainaut/730-1069-2"
        )),
        "manpower_url_title_hint": "CHEM_LAB" in track_hits(url_title_hint(
            "https://www.manpower.be/fr/emploi/junior-lab-analyst-275596"
        )),
        "lets_work_url_title_hint": "CHEM_LAB" in track_hits(url_title_hint(
            "https://www.letswork.be/fr/emplois/agent-de-controle-qualite-24614/"
        )),
        "manpower_catalog_cap_is_large": MANPOWER_MAX_DISCOVERED >= 5000,
        "letswork_pagination_enabled": LETS_WORK_MAX_LISTING_PAGES >= 15,
        "lims_analyst_is_hybrid": "HYBRID" in track_hits("LIMS Analyst"),
    }


# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1
from sources.unified_discovery import master_track_hits
_ud_original_track_hits = track_hits

def track_hits(title):
    out = list(_ud_original_track_hits(title) or [])
    for hit in master_track_hits(title):
        if hit not in out:
            out.append(hit)
    return out
