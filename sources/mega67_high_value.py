from __future__ import annotations

import html
import json
import re
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.batch4_engine import publish_metrics

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36"
TIMEOUT = 30
MAX_TEMPO_PAGES = 18
MAX_QJOBS_PAGES = 12

_LAST_DIAG = {}

TITLE_EXCLUDE = re.compile(
    r"\b(?:senior|sr\.?|principal|staff|director|head|manager|management|"
    r"team\s+leader|leader|supervisor|intern(?:ship)?|stage|trainee|"
    r"apprentice|phd)\b",
    re.I,
)

DATA_PATTERNS = (
    r"\bdata analyst\b",
    r"\bjunior data analyst\b",
    r"\bbusiness data analyst\b",
    r"\banalyste de donn[eé]es\b",
    r"\bdata-analist\b",
    r"\bbi analyst\b",
    r"\bbusiness intelligence analyst\b",
    r"\bbi developer\b",
    r"\bpower\s*bi\b",
    r"\breporting analyst\b",
    r"\breporting officer\b",
    r"\banalytics analyst\b",
    r"\binsights analyst\b",
    r"\bdata automation analyst\b",
    r"\bbusiness analyst\b",
    r"\bjunior business analyst\b",
    r"\bfunctional analyst\b",
    r"\banalyste fonctionnel\b",
    r"\bprocess analyst\b",
    r"\boperations analyst\b",
    r"\bdata quality\b",
    r"\bdata steward\b",
    r"\bmaster data\b",
    r"\bdata governance\b",
    r"\bdata coordinator\b",
    r"\bdata management\b",
)

LAB_PATTERNS = (
    r"\bqc\b",
    r"\bquality control\b",
    r"\bcontr[oô]le qualit[eé]\b",
    r"\bquality assurance\b",
    r"\bassurance qualit[eé]\b",
    # JOBHUNTER_STAFFING_RECALL_REPAIR_V1 - quality-role recall
    r"\bquality (?:officer|associate|specialist|technician|controller)\b",
    r"\b(?:agent|assistant|collaborateur|technicien(?:ne)?)\s+(?:de\s+)?(?:contr[oô]le\s+)?qualit[eé]\b",
    r"\bcontr[oô]leur(?:euse)?\s+qualit[eé]\b",
    r"\bop[eé]rateur(?:trice)?\s+qualit[eé]\b",
    r"\bqa (?:officer|associate|specialist|technician)\b",
    r"\blaborantin\b",
    r"\bassistant laborantin\b",
    r"\blab(?:oratory)?\s+(?:technician|analyst|assistant)\b",
    r"\btechnicien(?:ne)?\s+(?:de\s+)?laboratoire\b",
    r"\banalyste\s+(?:de\s+)?laboratoire\b",
    r"\btechnicien(?:ne)? chimiste\b",
    r"\bchimiste\b",
    r"\bchemical technician\b",
    r"\banalytical (?:technician|analyst)\b",
    r"\bmicrobiology\b",
    r"\bmicrobiologie\b",
    r"\bqualification\b",
    r"\bvalidation\b",
    r"\bcsv\b",
    r"\bcomputer(?:ized)? system validation\b",
    r"\bhplc\b",
    r"\buplc\b",
    r"\blc-ms\b",
    r"\bgc-ms\b",
    r"\bstability\b",
    r"\benvironmental monitoring\b",
    r"\bformulation\b",
    r"\bcell culture\b",
)

HYBRID_PATTERNS = (
    r"\blims analyst\b",
    r"\blims specialist\b",
    r"\blaboratory informatics\b",
    r"\blab systems? analyst\b",
    r"\blaboratory data analyst\b",
    r"\blab data analyst\b",
    r"\bqc data analyst\b",
    r"\bquality data analyst\b",
    r"\bdata integrity analyst\b",
    r"\bscientific data\b",
    r"\bdigital qc\b",
    r"\beln business analyst\b",
    r"\beln analyst\b",
    r"\bmanufacturing data analyst\b",
)

GENERIC_SCIENCE_PRODUCTION = re.compile(
    r"\b(?:production operator|production technician|manufacturing technician|"
    r"process technician|op[eé]rateur(?:trice)? de production|"
    r"technicien(?:ne)? de production|op[eé]rateur.*(?:filling|pr[eé]l[eè]vement))\b",
    re.I,
)

SCIENCE_CONTEXT = re.compile(
    r"\b(?:pharma|pharmaceutical|biotech|life sciences?|laboratory|laboratoire|"
    r"chemistry|chimie|chemical|gmp|bpf|qc|quality control|microbiology|"
    r"analytical|hplc|uplc|lims|aseptic|aseptique|clean ?room|salle blanche)\b",
    re.I,
)

DUTCH_HARD = (
    r"\bcommunicatief\s+vaardig\s+in\s+het\s+nederlands\b",
    r"\bcommunicatief\s+(?:in\s+)?(?:het\s+)?nederlands\b",
    r"\bgoede\s+kennis\s+(?:van\s+het\s+)?nederlands\b",
    r"\bnederlands\s+(?:is\s+)?vereist\b",
    r"\bfluent\b[^.!?;]{0,100}\bdutch\b",
    r"\bprofessional\s+(?:level\s+)?dutch\b",
    r"\bdutch\s+(?:is\s+)?(?:required|mandatory)\b",
    r"\b(?:french|fran[cç]ais)\b[^.!?;]{0,80}\bdutch\b[^.!?;]{0,80}\benglish\b",
    r"\bdutch\b[^.!?;]{0,80}\benglish\b",
    r"\btweetalig\b",
    r"\bn[eé]erlandais\s+(?:est\s+)?(?:exig[eé]|requis|obligatoire)\b",
)

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
BELGIUM_CITY_HINTS = (
    "brussels", "bruxelles", "antwerp", "antwerpen", "ghent", "gent",
    "leuven", "liege", "liège", "charleroi", "namur", "mons", "wavre",
    "nivelles", "seraing", "gosselies", "tournai", "mouscron", "verviers",
    "arlon", "hasselt", "mechelen", "machelen", "zaventem", "puurs",
    "geel", "lessines", "braine-l'alleud", "louvain-la-neuve", "ottignies",
    "roeselare", "waregem", "kortrijk", "brugge", "aalst", "genk",
    "ardooie", "wingene", "maldegem", "dilbeek", "grimbergen", "spa",
    "virton", "messancy", "oreye", "andenne", "neder-over-heembeek",
)

FOREIGN_COUNTRIES = {
    "france", "germany", "netherlands", "luxembourg country",
    "united kingdom", "united states", "usa", "canada", "india",
    "singapore", "qatar", "papua new guinea", "switzerland",
    "italy", "spain", "poland", "ireland", "sweden",
}


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.2",
    })
    return s


def tracks(title, description=""):
    title = clean(title)
    out = []
    if any(re.search(p, title, re.I) for p in DATA_PATTERNS):
        out.append("DATA_BI")
    if any(re.search(p, title, re.I) for p in LAB_PATTERNS):
        out.append("CHEM_LAB")
    if any(re.search(p, title, re.I) for p in HYBRID_PATTERNS):
        out.append("HYBRID")
    if (
        not out
        and GENERIC_SCIENCE_PRODUCTION.search(title)
        and SCIENCE_CONTEXT.search(title + " " + clean(description)[:5000])
    ):
        out.append("CHEM_LAB")
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
    low = clean(text).lower()
    if any(re.search(p, low, re.I) for p in DUTCH_HARD):
        return True
    return language_hint(low) == "NL"


TITLE_DUTCH_MANDATORY = (
    # JOBHUNTER_STAFFING_RECALL_REPAIR_V2
    # Accept FR/NL, FR-NL, "FR NL" and compact slug/H1 forms such as FRNL.
    r"\bfr\s*[/\-]?\s*nl(?:\s*[/\-]?\s*en)?\b",
    r"\bnl\s*[/\-]?\s*fr(?:\s*[/\-]?\s*en)?\b",
    r"\bfrench\s*[/\-]\s*dutch(?:\s*[/\-]\s*english)?\b",
    r"\bdutch\s*[/\-]\s*french(?:\s*[/\-]\s*english)?\b",
)

def title_requires_dutch(title):
    t = clean(title).lower()
    return any(re.search(p, t, re.I) for p in TITLE_DUTCH_MANDATORY)


def years_required(text):
    vals = []
    for pat in (
        r"\b(?:minimum|min\.?|at least|minstens)\s+(\d+)\+?\s+(?:years?|jaar|ans?)\b",
        r"\b(\d+)\s*[-–]\s*(\d+)\s+(?:years?|jaar|ans?)\b",
        r"\b(\d+)\+?\s+years?\s+(?:of\s+)?experience\b",
        r"\b(\d+)\+?\s+ans?\s+d['’ ]exp[eé]rience\b",
        r"\b(\d+)\+?\s+jaar\s+ervaring\b",
    ):
        for m in re.finditer(pat, clean(text), re.I):
            for g in m.groups():
                if g:
                    try:
                        v = int(g)
                    except Exception:
                        continue
                    if 0 <= v <= 15:
                        vals.append(v)
    return max(vals) if vals else None


def jsonld_jobs(soup):
    found = []
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
                found.append(obj)
    return found


def structured_location(obj):
    countries, cities, parts = [], [], []

    def norm_country(v):
        if isinstance(v, dict):
            v = v.get("name") or v.get("@id") or v.get("value") or ""
        return clean(v).lower()

    def walk(v):
        if isinstance(v, dict):
            addr = v.get("address")
            if isinstance(addr, dict):
                country = norm_country(addr.get("addressCountry"))
                city = clean(addr.get("addressLocality"))
                region = clean(addr.get("addressRegion"))
                if country:
                    countries.append(country)
                if city:
                    cities.append(city.lower())
                for x in (city, region, country):
                    if x:
                        parts.append(clean(x))
            country = norm_country(v.get("addressCountry"))
            city = clean(v.get("addressLocality"))
            if country:
                countries.append(country)
            if city:
                cities.append(city.lower())
            for k in ("jobLocation", "applicantLocationRequirements"):
                if k in v:
                    walk(v[k])
        elif isinstance(v, list):
            for item in v:
                walk(item)

    walk(obj.get("jobLocation") or obj.get("applicantLocationRequirements"))
    return list(dict.fromkeys(countries)), list(dict.fromkeys(cities)), " | ".join(dict.fromkeys(parts))


def geo_from_obj_or_text(obj, text, fallback_location=""):
    countries, cities, location = structured_location(obj)
    if fallback_location and not location:
        location = clean(fallback_location)

    if countries:
        if any(c in BELGIUM_COUNTRIES for c in countries):
            return "BE", location
        return "FOREIGN", location

    blob = (clean(location) + " " + clean(text[:2600])).lower()
    for city in BELGIUM_CITY_HINTS:
        if re.search(rf"(?<![a-z]){re.escape(city)}(?![a-z])", blob):
            return "BE", location or city.title()

    for country in FOREIGN_COUNTRIES:
        if re.search(rf"(?<![a-z]){re.escape(country)}(?![a-z])", blob):
            return "FOREIGN", location

    return "UNKNOWN", location


def classify(title, description, geo):
    title = clean(title)
    description = clean(description)
    tr = tracks(title, description)

    if not tr:
        return "NOT_TARGET", tr
    if TITLE_EXCLUDE.search(title):
        return "REJECT_SENIORITY", tr
    if geo != "BE":
        return "REJECT_GEO", tr
    if title_requires_dutch(title) or hard_dutch(description):
        return "REJECT_DUTCH", tr

    yrs = years_required(description)
    if yrs is not None and yrs >= 4:
        return "REJECT_EXPERIENCE", tr
    if yrs == 3:
        return "STRETCH", tr
    return "GOOD", tr


def dedupe_jobs(jobs):
    out, seen = [], set()
    for job in jobs:
        key = (
            clean(getattr(job, "title", "")).lower(),
            clean(getattr(job, "location", "")).lower(),
            clean(getattr(job, "description", "")).lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(job)
    return out


def make_job(source, company, ext_id, title, location, description, url):
    return JobOffer(
        source=source,
        external_id=clean(ext_id),
        title=clean(title),
        company=company,
        location=clean(location) or "Belgium",
        description=clean(description),
        url=clean(url),
        date_published=None,
        contract_type=None,
        language=None,
    )


def publish(source, seen, candidates, jobs, *, lang=0, geo=0, closed=0, errors=0, diag=None):
    jobs = dedupe_jobs(jobs)
    metrics = {
        "seen": int(seen),
        "candidates": int(candidates),
        "kept": len(jobs),
        "non_target": max(0, int(seen) - int(candidates)),
        "rejected_language": int(lang),
        "rejected_geo": int(geo),
        "closed": int(closed),
        "detail_errors": int(errors),
    }
    publish_metrics(source, metrics)
    _LAST_DIAG[source] = dict(diag or {})
    _LAST_DIAG[source]["metrics"] = dict(metrics)

    print()
    print("=" * 96)
    print(source)
    print("=" * 96)
    for k, v in metrics.items():
        print(f"{k:<22}: {v}")
    for j in jobs:
        print("KEEP |", j.title, "|", j.location)
    return jobs


def get_mega67_diag(source):
    return dict(_LAST_DIAG.get(str(source).upper(), {}))


# ---------------------------------------------------------------------------
# START PEOPLE
# ---------------------------------------------------------------------------

def collect_start_people_jobs():
    source = "START_PEOPLE"
    company = "Start People Belgium"
    s = session()

    pages = [
        "https://www.startpeople.be/fr/joblist/offres-d-emploi-laborantin",
        "https://www.startpeople.be/fr/joblist/offres-d-emploi-quality-control",
        "https://www.startpeople.be/fr/joblist/offres-d-emploi-data-analyst",
        "https://www.startpeople.be/fr/joblist/offres-d-emploi-business-analyst",
    ]

    links = {}
    for page in pages:
        try:
            r = s.get(page, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                u = urljoin(r.url, a["href"]).split("#", 1)[0]
                m = re.search(r"/fr/job/([^/?#]+)-(\d+)", u, re.I)
                if m:
                    links[m.group(2)] = (u, clean(a.get_text(" ", strip=True)))
        except Exception:
            continue

    seen = len(links)
    jobs, candidates = [], 0
    rej_lang = rej_geo = closed = errors = detail_ok = 0

    for ext_id, (url, listing_title) in sorted(links.items()):
        try:
            r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code in {404, 410}:
                closed += 1
                continue
            r.raise_for_status()
        except Exception:
            errors += 1
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        objs = jsonld_jobs(soup)
        if not objs:
            errors += 1
            continue

        detail_ok += 1
        obj = objs[0]
        page_text = clean(soup.get_text(" ", strip=True))
        title = clean(obj.get("title") or obj.get("name") or listing_title)
        desc = clean(BeautifulSoup(str(obj.get("description") or ""), "html.parser").get_text(" ", strip=True))
        if len(desc) < 200:
            desc = page_text

        geo, location = geo_from_obj_or_text(obj, page_text)
        fit, tr = classify(title, desc, geo)

        if not tr:
            continue
        candidates += 1

        if fit == "REJECT_GEO":
            rej_geo += 1
            continue
        if fit == "REJECT_DUTCH":
            rej_lang += 1
            continue
        if fit not in {"GOOD", "STRETCH"}:
            continue

        jobs.append(make_job(source, company, ext_id, title, location, desc, r.url))

    return publish(
        source, seen, candidates, jobs,
        lang=rej_lang, geo=rej_geo, closed=closed, errors=errors,
        diag={"detail_probe_ok": detail_ok, "listing_pages": len(pages)},
    )



# JOBHUNTER_STAFFING_RECALL_REPAIR_V1
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.I,
)


def title_hint_from_url(url):
    """Recover a human title hint from staffing job-detail URL slugs."""
    parts = [
        unquote(x)
        for x in urlparse(clean(url)).path.strip("/").split("/")
        if clean(x)
    ]
    if not parts:
        return ""

    segment = parts[-1]

    # Tempo-Team: <title>_<city>_<uuid>
    if _UUID_RE.search(segment):
        segment = _UUID_RE.sub("", segment).rstrip("_-")
        if "_" in segment:
            segment = segment.rsplit("_", 1)[0]

    # Q Jobs / generic staffing references.
    segment = re.sub(r"-PO-[A-Z0-9]{3,}$", "", segment, flags=re.I)
    segment = re.sub(r"-(?=[A-Z0-9]*\d)[A-Z0-9]{5,}$", "", segment, flags=re.I)
    segment = re.sub(r"-\d{3,}$", "", segment)

    return clean(re.sub(r"[-_]+", " ", segment))


def effective_title_hint(listing_title, url):
    """Prefer a useful listing title, otherwise use the URL slug title."""
    listing_title = clean(listing_title)
    if tracks(listing_title):
        return listing_title

    slug_title = title_hint_from_url(url)
    if tracks(slug_title):
        return slug_title

    return listing_title or slug_title


# ---------------------------------------------------------------------------
# TEMPO TEAM - true UUID individual job URLs
# ---------------------------------------------------------------------------

TEMPO_JOB_RE = re.compile(
    r"/fr/candidats/nos-offres/[^/?#]+_[^/?#]+_"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/?$",
    re.I,
)


def tempo_location_from_page(soup):
    lines = [clean(x) for x in soup.get_text("\n", strip=True).splitlines() if clean(x)]
    try:
        idx = next(i for i, x in enumerate(lines) if x.lower() == "résumé")
    except StopIteration:
        idx = -1
    if idx >= 0:
        for value in lines[idx+1:idx+7]:
            low = value.lower()
            if (
                2 < len(value) < 120
                and "," in value
                and not any(x in low for x in ("mission", "cdi", "temps plein", "€", "publi"))
            ):
                return value
    return ""


def collect_tempo_team_jobs():
    source = "TEMPO_TEAM"
    company = "Tempo-Team Belgium"
    s = session()

    links = {}
    for page in range(1, MAX_TEMPO_PAGES + 1):
        url = "https://www.tempo-team.be/fr/candidats/nos-offres/"
        if page > 1:
            url += f"page-{page}/"
        try:
            r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                break
        except Exception:
            break

        before = len(links)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            u = urljoin(r.url, a["href"]).split("#", 1)[0]
            if TEMPO_JOB_RE.search(urlparse(u).path):
                title = clean(a.get_text(" ", strip=True))
                links[u] = title
        if page > 1 and len(links) == before:
            break

    seen = len(links)
    jobs, candidates = [], 0
    rej_lang = rej_geo = closed = errors = detail_ok = 0

    # Use anchor text when useful, otherwise recover title from the UUID URL slug.
    selected = []
    for u, t in links.items():
        effective = effective_title_hint(t, u)
        if tracks(effective):
            selected.append((u, t, effective))

    if not selected and links:
        u, t = next(iter(links.items()))
        selected = [(u, t, effective_title_hint(t, u))]

    for url, listing_title, effective_title in selected:
        try:
            r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code in {404, 410}:
                closed += 1
                continue
            r.raise_for_status()
        except Exception:
            errors += 1
            continue

        detail_ok += 1
        soup = BeautifulSoup(r.text, "html.parser")
        page_text = clean(soup.get_text(" ", strip=True))
        h1 = soup.find("h1")
        title = clean(h1.get_text(" ", strip=True)) if h1 else effective_title
        if not tracks(title) and tracks(effective_title):
            title = effective_title
        location = tempo_location_from_page(soup)
        geo = "BE" if location else "UNKNOWN"

        desc = page_text
        fit, tr = classify(title, desc, geo)
        if not tr:
            continue
        candidates += 1

        if fit == "REJECT_GEO":
            rej_geo += 1
            continue
        if fit == "REJECT_DUTCH":
            rej_lang += 1
            continue
        if fit not in {"GOOD", "STRETCH"}:
            continue

        m = re.search(
            r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
            r.url, re.I,
        )
        ext_id = m.group(1) if m else re.sub(r"\W+", "-", r.url)[-80:]
        jobs.append(make_job(source, company, ext_id, title, location, desc, r.url))

    return publish(
        source, seen, candidates, jobs,
        lang=rej_lang, geo=rej_geo, closed=closed, errors=errors,
        diag={
            "detail_probe_ok": detail_ok,
            "true_individual_urls": seen,
            "category_pages_excluded": True,
        },
    )


# ---------------------------------------------------------------------------
# ROBERT HALF
# ---------------------------------------------------------------------------

ROBERT_JOB_RE = re.compile(
    r"/be/fr/(?:vacature|emploi)/[^/?#]+/[^/?#]+/\d+-[a-z]+$",
    re.I,
)


def collect_robert_half_jobs():
    source = "ROBERT_HALF"
    company = "Robert Half Belgium"
    s = session()

    pages = [
        "https://www.roberthalf.com/be/fr/emplois/belgium/data-analyst-business-analyst",
        "https://www.roberthalf.com/be/fr/emplois",
    ]

    links = {}
    for page in pages:
        try:
            r = s.get(page, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                u = urljoin(r.url, a["href"]).split("#", 1)[0]
                if ROBERT_JOB_RE.search(urlparse(u).path):
                    links[u] = clean(a.get_text(" ", strip=True))
        except Exception:
            continue

    seen = len(links)
    jobs, candidates = [], 0
    rej_lang = rej_geo = closed = errors = detail_ok = 0

    for url, listing_title in links.items():
        # Avoid detail calls for clearly irrelevant listing titles.
        if not tracks(listing_title):
            continue
        try:
            r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code in {404, 410}:
                closed += 1
                continue
            r.raise_for_status()
        except Exception:
            errors += 1
            continue

        detail_ok += 1
        soup = BeautifulSoup(r.text, "html.parser")
        text = clean(soup.get_text(" ", strip=True))
        h1 = soup.find("h1")
        title = clean(h1.get_text(" ", strip=True)) if h1 else listing_title
        desc = text

        # Every accepted URL is under /be/ and contains the Belgian city/province.
        path_parts = [clean(x) for x in urlparse(r.url).path.split("/") if clean(x)]
        location = ""
        try:
            marker = next(i for i, x in enumerate(path_parts) if x in {"vacature", "emploi"})
            location = " | ".join(path_parts[marker+1:marker+3])
        except Exception:
            pass

        geo = "BE" if location else "UNKNOWN"
        fit, tr = classify(title, desc, geo)
        if not tr:
            continue
        candidates += 1

        if fit == "REJECT_GEO":
            rej_geo += 1
            continue
        if fit == "REJECT_DUTCH":
            rej_lang += 1
            continue
        if fit not in {"GOOD", "STRETCH"}:
            continue

        m = re.search(r"/(\d+)-[a-z]+$", urlparse(r.url).path, re.I)
        ext_id = m.group(1) if m else re.sub(r"\W+", "-", r.url)[-80:]
        jobs.append(make_job(source, company, ext_id, title, location, desc, r.url))

    return publish(
        source, seen, candidates, jobs,
        lang=rej_lang, geo=rej_geo, closed=closed, errors=errors,
        diag={"detail_probe_ok": detail_ok, "belgium_path_scope": True},
    )


# ---------------------------------------------------------------------------
# Q JOBS
# ---------------------------------------------------------------------------

QJOB_RE = re.compile(r"/fr/offres-d-emploi/(\d+)/[^/?#]+/?$", re.I)


def collect_qjobs_jobs():
    source = "QJOBS"
    company = "Q Jobs Belgium"
    s = session()

    links = {}
    for page in range(1, MAX_QJOBS_PAGES + 1):
        url = "https://www.qjobs.be/fr/offres-d-emploi"
        if page > 1:
            url += f"?page={page}"
        try:
            r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                break
        except Exception:
            break

        before = len(links)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            u = urljoin(r.url, a["href"]).split("#", 1)[0]
            m = QJOB_RE.search(urlparse(u).path)
            if m:
                links[m.group(1)] = (u, clean(a.get_text(" ", strip=True)))
        if page > 1 and len(links) == before:
            break

    seen = len(links)
    jobs, candidates = [], 0
    rej_lang = rej_geo = closed = errors = detail_ok = 0

    selected = []
    for eid, (u, t) in links.items():
        effective = effective_title_hint(t, u)
        if tracks(effective):
            selected.append((eid, u, t, effective))

    if not selected and links:
        eid, (u, t) = next(iter(links.items()))
        selected = [(eid, u, t, effective_title_hint(t, u))]

    for ext_id, url, listing_title, effective_title in selected:
        try:
            r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code in {404, 410}:
                closed += 1
                continue
            r.raise_for_status()
        except Exception:
            errors += 1
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        objs = jsonld_jobs(soup)
        if not objs:
            errors += 1
            continue

        detail_ok += 1
        obj = objs[0]
        text = clean(soup.get_text(" ", strip=True))
        title = clean(obj.get("title") or obj.get("name") or effective_title or listing_title)
        if not tracks(title) and tracks(effective_title):
            title = effective_title
        desc = clean(BeautifulSoup(str(obj.get("description") or ""), "html.parser").get_text(" ", strip=True))
        if len(desc) < 200:
            desc = text
        geo, location = geo_from_obj_or_text(obj, text)
        fit, tr = classify(title, desc, geo)

        if not tr:
            continue
        candidates += 1
        if fit == "REJECT_GEO":
            rej_geo += 1
            continue
        if fit == "REJECT_DUTCH":
            rej_lang += 1
            continue
        if fit not in {"GOOD", "STRETCH"}:
            continue

        jobs.append(make_job(source, company, ext_id, title, location, desc, r.url))

    return publish(
        source, seen, candidates, jobs,
        lang=rej_lang, geo=rej_geo, closed=closed, errors=errors,
        diag={"detail_probe_ok": detail_ok},
    )


# ---------------------------------------------------------------------------
# MICHAEL PAGE - listing anchor title is authoritative fallback
# ---------------------------------------------------------------------------

MP_JOB_RE = re.compile(r"/job-detail/[^?#]+/ref/(jn-[a-z0-9-]+)", re.I)
GENERIC_MP_TITLE = re.compile(r"^(?:consultez l['’]offre|view job|bekijk vacature)$", re.I)


def collect_michael_page_jobs():
    source = "MICHAEL_PAGE"
    company = "Michael Page BeLux"
    s = session()

    pages = [
        "https://www.michaelpage.be/jobs/analyst",
        "https://www.michaelpage.be/jobs/business-analyst",
        "https://www.michaelpage.be/fr/jobs/analyst",
        "https://www.michaelpage.be/fr/jobs/business-analyst",
        "https://www.michaelpage.be/fr/jobs/data-analyst",
    ]

    links = {}
    for page in pages:
        try:
            r = s.get(page, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                u = urljoin(r.url, a["href"]).split("#", 1)[0]
                m = MP_JOB_RE.search(u)
                if not m:
                    continue
                title = clean(a.get_text(" ", strip=True))
                context = ""
                parent = a.find_parent(["article", "li", "div"])
                if parent:
                    context = clean(parent.get_text(" | ", strip=True))
                current = links.get(m.group(1))
                # Prefer the richest listing anchor/context.
                if current is None or len(title) + len(context) > len(current[1]) + len(current[2]):
                    links[m.group(1)] = (u, title, context)
        except Exception:
            continue

    seen = len(links)
    jobs, candidates = [], 0
    rej_lang = rej_geo = closed = errors = detail_ok = 0

    # Only details with target-like listing titles or slugs.
    selected = []
    for ext_id, (url, listing_title, context) in links.items():
        slug_title = clean(urlparse(url).path.split("/job-detail/", 1)[-1].split("/ref/", 1)[0].replace("-", " "))
        effective = listing_title if tracks(listing_title) else slug_title
        if tracks(effective):
            selected.append((ext_id, url, listing_title, context, effective))

    if not selected and links:
        ext_id, (url, listing_title, context) = next(iter(links.items()))
        selected = [(ext_id, url, listing_title, context, listing_title)]

    for ext_id, url, listing_title, context, effective_title in selected:
        try:
            r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code in {404, 410}:
                closed += 1
                continue
            r.raise_for_status()
        except Exception:
            errors += 1
            continue

        detail_ok += 1
        soup = BeautifulSoup(r.text, "html.parser")
        text = clean(soup.get_text(" ", strip=True))
        h1 = soup.find("h1")
        h1_title = clean(h1.get_text(" ", strip=True)) if h1 else ""

        if not h1_title or GENERIC_MP_TITLE.match(h1_title):
            title = clean(listing_title)
            if not title or GENERIC_MP_TITLE.match(title):
                title = effective_title
        else:
            title = h1_title

        # Listing context normally contains Brussels City / region.
        geo, location = geo_from_obj_or_text({}, context + " " + text[:1800])
        if not location:
            for city in BELGIUM_CITY_HINTS:
                if re.search(rf"(?<![a-z]){re.escape(city)}(?![a-z])", (context + " " + text[:2200]).lower()):
                    location = city.title()
                    geo = "BE"
                    break

        desc = text
        fit, tr = classify(title, desc, geo)
        if not tr:
            continue
        candidates += 1

        if fit == "REJECT_GEO":
            rej_geo += 1
            continue
        if fit == "REJECT_DUTCH":
            rej_lang += 1
            continue
        if fit not in {"GOOD", "STRETCH"}:
            continue

        jobs.append(make_job(source, company, ext_id, title, location, desc, r.url))

    return publish(
        source, seen, candidates, jobs,
        lang=rej_lang, geo=rej_geo, closed=closed, errors=errors,
        diag={
            "detail_probe_ok": detail_ok,
            "listing_title_fallback": True,
            "generic_detail_title_fixed": True,
        },
    )


def regression_checks():
    checks = {
        "technicien_chimiste_is_lab": "CHEM_LAB" in tracks("Technicien chimiste"),
        "quality_controller_is_lab": "CHEM_LAB" in tracks("Contrôleur qualité"),
        "quality_operator_is_lab": "CHEM_LAB" in tracks("Opérateur qualité FR/NL"),
        "quality_officer_is_lab": "CHEM_LAB" in tracks("Quality Officer"),
        "qjobs_slug_recovers_title": "CHEM_LAB" in tracks(
            title_hint_from_url("https://www.qjobs.be/fr/offres-d-emploi/12345/controleur-qualite")
        ),
        "tempo_slug_recovers_title": "CHEM_LAB" in tracks(
            title_hint_from_url(
                "https://www.tempo-team.be/fr/candidats/nos-offres/"
                "operateur-qualite_neder-over-heembeek_"
                "12345678-1234-1234-1234-123456789abc/"
            )
        ),
        "business_analyst_is_data": "DATA_BI" in tracks("Business Analyst"),
        "lims_is_hybrid": "HYBRID" in tracks("LIMS Analyst"),
        "aml_analyst_not_target": not tracks("AML Analyst"),
        "tempo_category_not_individual": not TEMPO_JOB_RE.search(
            "/fr/candidats/nos-offres/r-operateur-de-controle-qualite/"
        ),
        "tempo_uuid_is_individual": bool(TEMPO_JOB_RE.search(
            "/fr/candidats/nos-offres/technicien-de-laboratoire_virton_"
            "12345678-1234-1234-1234-123456789abc/"
        )),
        "michael_page_generic_title_detected": bool(
            GENERIC_MP_TITLE.match("Consultez l'offre")
        ),
        "dutch_requirement_rejected": hard_dutch(
            "Goede kennis van het Nederlands is vereist voor deze functie."
        ),
        "fluent_fr_dutch_en_rejected": hard_dutch(
            "The successful applicant is fluent in French, Dutch, English."
        ),
        "fr_nl_en_title_rejected": title_requires_dutch(
            "Business Analyst BeNeLux - Automotive - FR/NL/EN"
        ),
        "compact_frnl_title_rejected": title_requires_dutch(
            "operateurtrice qualite frnl"
        ),
        "robert_half_current_url_matches": bool(ROBERT_JOB_RE.search(
            "/be/fr/vacature/kall%C3%B8-east-flanders/business-analyst/000515478-benl"
        )),
    }
    return checks


# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1
from sources.unified_discovery import master_track_hits
_ud_original_tracks = tracks

def tracks(title, description=""):
    out = list(_ud_original_tracks(title, description) or [])
    for hit in master_track_hits(title):
        if hit not in out:
            out.append(hit)
    return out
