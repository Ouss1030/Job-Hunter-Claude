from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.batch4_engine import publish_metrics

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36"
TIMEOUT = 30

_LAST_DIAG = {}

TITLE_EXCLUDE = re.compile(
    r"\b(?:senior|sr\.?|principal|staff|director|head|manager|management|"
    r"team\s+leader|leader|supervisor|intern(?:ship)?|stage|trainee|"
    r"apprentice|phd)\b",
    re.I,
)

TRACK_PATTERNS = {
    "DATA_BI": [
        r"\bdata analyst\b",
        r"\bjunior data analyst\b",
        r"\bbusiness data analyst\b",
        r"\bbi analyst\b",
        r"\bbusiness intelligence analyst\b",
        r"\bbi developer\b",
        r"\bpower\s*bi\b",
        r"\breporting analyst\b",
        r"\bbusiness analyst\b",
        r"\bfunctional analyst\b",
        r"\bprocess analyst\b",
        r"\boperations analyst\b",
        r"\bdata quality\b",
        r"\bdata steward\b",
        r"\bmaster data\b",
        r"\bdata governance\b",
        r"\bdata coordinator\b",
        r"\bdata management\b",
    ],
    "CHEM_LAB": [
        r"\bqc\b",
        r"\bquality control\b",
        r"\bquality assurance\b",
        r"\bqa (?:officer|associate|specialist|technician)\b",
        r"\blaborantin\b",
        r"\blab(?:oratory)?\s+(?:technician|analyst|assistant)\b",
        r"\btechnicien(?:ne)?\s+(?:de\s+)?laboratoire\b",
        r"\banalyste\s+(?:de\s+)?laboratoire\b",
        r"\bmicrobiology\b",
        r"\bmicrobiologie\b",
        r"\bqualification\b",
        r"\bvalidation\b",
        r"\bcsv\b",
        r"\bhplc\b",
        r"\buplc\b",
        r"\blims\b",
        r"\bstability\b",
        r"\benvironmental monitoring\b",
    ],
    "HYBRID": [
        r"\blims analyst\b",
        r"\blims specialist\b",
        r"\blaboratory informatics\b",
        r"\blab systems? analyst\b",
        r"\blaboratory data analyst\b",
        r"\bqc data analyst\b",
        r"\bquality data analyst\b",
        r"\bdata integrity analyst\b",
        r"\bscientific data\b",
        r"\bdigital qc\b",
        r"\beln business analyst\b",
        r"\beln analyst\b",
    ],
}

DUTCH_HARD = [
    r"\bcommunicatief\s+vaardig\s+in\s+het\s+nederlands\b",
    r"\bcommunicatief\s+(?:in\s+)?(?:het\s+)?nederlands\b",
    r"\bgoede\s+kennis\s+(?:van\s+het\s+)?nederlands\b",
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
    "minstens", "bij voorkeur", "analytische vaardigheden", "kennis van",
)

FR_WORDS = (
    "nous recherchons", "vous êtes", "votre profil", "expérience", "formation",
    "français", "responsabilités", "compétences", "nous offrons", "postuler",
)

EN_WORDS = (
    "we are looking", "you are", "your profile", "experience", "requirements",
    "responsibilities", "skills", "english", "apply", "we offer",
)

BELGIUM_COUNTRIES = {"be", "bel", "belgium", "belgique", "belgië", "belgie"}
BELGIUM_CITIES = {
    "brussels", "bruxelles", "antwerp", "antwerpen", "ghent", "gent", "leuven",
    "liege", "liège", "charleroi", "namur", "mons", "wavre", "nivelles",
    "seraing", "gosselies", "tournai", "mouscron", "verviers", "arlon",
    "hasselt", "mechelen", "machelen", "zaventem", "puurs", "geel", "lessines",
    "braine-l'alleud", "louvain-la-neuve", "ottignies", "roeselare", "waregem",
    "kortrijk", "brugge", "aalst", "genk", "ardooie", "wingene", "maldegem",
}

FOREIGN_COUNTRIES = {
    "france", "germany", "netherlands", "luxembourg", "united kingdom",
    "united states", "usa", "canada", "india", "singapore", "qatar",
    "papua new guinea", "switzerland", "italy", "spain", "poland", "ireland",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


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


def years_required(text):
    vals = []
    for pat in (
        r"\b(?:minimum|min\.?|at least|minstens)\s+(\d+)\+?\s+(?:years?|jaar)\b",
        r"\b(\d+)\s*[-–]\s*(\d+)\s+jaar\s+ervaring\b",
        r"\b(\d+)\+?\s+years?\s+(?:of\s+)?experience\b",
        r"\b(\d+)\+?\s+ans?\s+d['’ ]exp[eé]rience\b",
        r"\b(\d+)\+?\s+jaar\s+ervaring\b",
    ):
        for m in re.finditer(pat, clean(text), re.I):
            try:
                values = [int(x) for x in m.groups() if x is not None]
                values = [x for x in values if 0 <= x <= 15]
                vals.extend(values)
            except Exception:
                pass
    return max(vals) if vals else None


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


def normalize_country(value):
    if isinstance(value, dict):
        value = value.get("name") or value.get("@id") or value.get("value") or ""
    return clean(value).lower()


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
            for k in ("jobLocation", "applicantLocationRequirements"):
                if k in v:
                    walk(v[k])
        elif isinstance(v, list):
            for item in v:
                walk(item)

    walk(obj.get("jobLocation") or obj.get("applicantLocationRequirements"))
    return list(dict.fromkeys(countries)), list(dict.fromkeys(cities)), " | ".join(dict.fromkeys(parts))


def strict_geo(obj, fallback_text=""):
    countries, cities, location = structured_location(obj)

    if countries:
        if any(c in BELGIUM_COUNTRIES for c in countries):
            return "BE", location
        if any(c in FOREIGN_COUNTRIES or c not in BELGIUM_COUNTRIES for c in countries):
            return "FOREIGN", location

    if any(c in BELGIUM_CITIES for c in cities):
        return "BE", location

    low = clean(fallback_text).lower()
    for city in BELGIUM_CITIES:
        if re.search(rf"(?<![a-z]){re.escape(city)}(?![a-z])", low):
            return "BE", location or city.title()

    for country in FOREIGN_COUNTRIES:
        if re.search(rf"(?<![a-z]){re.escape(country)}(?![a-z])", low):
            return "FOREIGN", location

    return "UNKNOWN", location


def make_job(source, company, external_id, title, location, description, url):
    return JobOffer(
        source=source,
        external_id=clean(external_id),
        title=clean(title),
        company=company,
        location=clean(location) or "Belgium",
        description=clean(description),
        url=clean(url),
        date_published=None,
        contract_type=None,
        language=None,
    )


def _publish(source, metrics, jobs, diag):
    publish_metrics(source, metrics)
    _LAST_DIAG[source] = dict(diag)
    _LAST_DIAG[source]["metrics"] = dict(metrics)

    print()
    print("=" * 96)
    print(source)
    print("=" * 96)
    for k, v in metrics.items():
        print(f"{k:<22}: {v}")
    for job in jobs:
        print("KEEP |", job.title, "|", job.location)

    return jobs


def _job_id(obj, url):
    value = obj.get("identifier")
    if isinstance(value, dict):
        value = value.get("value") or value.get("name")
    value = clean(value)
    if value:
        return value

    for pat in (
        r"/vacancies/(\d+)-",
        r"/jobs/([a-f0-9]{16,})/",
    ):
        m = re.search(pat, url, re.I)
        if m:
            return m.group(1)
    return re.sub(r"[^A-Za-z0-9]+", "-", url)[-80:]


def _evaluate(obj, page_text, page_url):
    title = clean(obj.get("title") or obj.get("name"))
    description = clean(
        BeautifulSoup(str(obj.get("description") or ""), "html.parser").get_text(" ", strip=True)
    )
    if len(description) < 150:
        description = page_text

    tracks = track_hits(title)
    geo, location = strict_geo(obj, page_text[:2500])
    lang = language_hint(description)
    dutch = hard_dutch(description)
    yrs = years_required(description)

    if not tracks:
        fit = "NOT_TARGET"
    elif TITLE_EXCLUDE.search(title):
        fit = "REJECT_SENIORITY"
    elif geo != "BE":
        fit = "REJECT_GEO"
    elif dutch:
        fit = "REJECT_DUTCH"
    elif yrs is not None and yrs >= 4:
        fit = "REJECT_EXPERIENCE"
    elif yrs == 3:
        fit = "STRETCH"
    else:
        fit = "GOOD"

    return {
        "title": title,
        "description": description,
        "tracks": tracks,
        "geo": geo,
        "location": location,
        "language": lang,
        "hard_dutch": dutch,
        "years_required": yrs,
        "fit": fit,
        "url": page_url,
    }


def collect_experis_jobs():
    source = "EXPERIS"
    company = "Experis Belgium"
    s = session()

    listing = "https://experis.be/search-jobs/"
    r = s.get(listing, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    links = {}

    for a in soup.find_all("a", href=True):
        url = urljoin(r.url, a["href"]).split("#", 1)[0]
        m = re.search(r"https?://experis\.be/vacancies/(\d+)-[^/?#]+/?$", url, re.I)
        if m:
            links[m.group(1)] = url

    seen = len(links)
    jobs = []
    candidates = 0
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    rejected_experience = 0
    detail_ok = 0

    for ext_id, url in sorted(links.items()):
        try:
            rr = s.get(url, timeout=TIMEOUT, allow_redirects=True)
            if rr.status_code in {404, 410}:
                closed += 1
                continue
            rr.raise_for_status()
        except Exception:
            errors += 1
            continue

        detail_ok += 1
        soup = BeautifulSoup(rr.text, "html.parser")
        objs = parse_jsonld(soup)
        if not objs:
            errors += 1
            continue

        page_text = clean(soup.get_text(" ", strip=True))
        ev = _evaluate(objs[0], page_text, rr.url)

        if not ev["tracks"]:
            continue
        candidates += 1

        if ev["fit"] == "REJECT_GEO":
            rejected_geo += 1
            continue
        if ev["fit"] == "REJECT_DUTCH":
            rejected_language += 1
            continue
        if ev["fit"] == "REJECT_EXPERIENCE":
            rejected_experience += 1
            continue
        if ev["fit"] == "REJECT_SENIORITY":
            continue
        if ev["fit"] not in {"GOOD", "STRETCH"}:
            continue

        jobs.append(make_job(
            source, company, ext_id, ev["title"], ev["location"],
            ev["description"], rr.url,
        ))

    metrics = {
        "seen": seen,
        "candidates": candidates,
        "kept": len(jobs),
        "non_target": max(0, seen - candidates),
        "rejected_language": rejected_language,
        "rejected_geo": rejected_geo,
        "closed": closed,
        "detail_errors": errors,
    }

    return _publish(source, metrics, jobs, {
        "detail_probe_ok": detail_ok,
        "rejected_experience": rejected_experience,
        "strict_geo": True,
        "strict_language": True,
        "known_false_positive_should_reject": "27778 Data Analyst",
    })


def collect_synergie_jobs():
    source = "SYNERGIE"
    company = "Synergie Belgium"
    s = session()

    sitemap = "https://www.synergiejobs.be/sitemap.xml"
    r = s.get(sitemap, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()

    detail_urls = set(re.findall(
        r"https?://www\.synergiejobs\.be/(?:fr|nl|en)/jobs/[a-f0-9]{16,}/[^<\s]+/?",
        r.text,
        re.I,
    ))

    # Fallback to FR/NL listing pages if sitemap format changes.
    if not detail_urls:
        for page in (
            "https://www.synergiejobs.be/fr/jobs/",
            "https://www.synergiejobs.be/nl/jobs/",
        ):
            rr = s.get(page, timeout=TIMEOUT, allow_redirects=True)
            if rr.status_code != 200:
                continue
            soup = BeautifulSoup(rr.text, "html.parser")
            for a in soup.find_all("a", href=True):
                url = urljoin(rr.url, a["href"]).split("#", 1)[0]
                if re.search(r"/(?:fr|nl|en)/jobs/[a-f0-9]{16,}/[^/?#]+/?$", url, re.I):
                    detail_urls.add(url)

    seen = len(detail_urls)
    jobs = []
    candidates = 0
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    rejected_experience = 0
    detail_ok = 0

    # JOBHUNTER_RAW_CATALOG_PRODUCTION_V1_MEGA64
    # Apply FULL Master400 to the raw URL slug BEFORE detail retrieval.
    # Preserve the legacy tokens as an additive safety net.
    from sources.unified_discovery import matches_catalog_master_title

    target_tokens = (
        "data", "analyst", "business-analyst", "bi-", "power-bi", "report",
        "quality", "qc-", "qa-", "labor", "lab-", "validation", "qualification",
        "microbi", "lims",
    )

    def _raw_catalog_slug_title(url):
        try:
            path = urlparse(url).path.rstrip("/")
            slug = path.split("/")[-1]
            slug = re.sub(r"[-_]+", " ", slug)
            return clean(slug)
        except Exception:
            return ""

    candidate_urls = [
        u for u in detail_urls
        if (
            any(tok in u.lower() for tok in target_tokens)
            or matches_catalog_master_title(_raw_catalog_slug_title(u))
        )
    ]

    # One health probe if there are no candidate URLs.
    probe_urls = candidate_urls[:80]
    if not probe_urls and detail_urls:
        probe_urls = [sorted(detail_urls)[0]]

    for url in probe_urls:
        try:
            rr = s.get(url, timeout=TIMEOUT, allow_redirects=True)
            if rr.status_code in {404, 410}:
                closed += 1
                continue
            rr.raise_for_status()
        except Exception:
            errors += 1
            continue

        detail_ok += 1
        soup = BeautifulSoup(rr.text, "html.parser")
        objs = parse_jsonld(soup)

        if objs:
            obj = objs[0]
        else:
            h1 = soup.find("h1")
            title = clean(h1.get_text(" ", strip=True)) if h1 else ""
            obj = {
                "@type": "JobPosting",
                "title": title,
                "description": clean(soup.get_text(" ", strip=True)),
            }

        page_text = clean(soup.get_text(" ", strip=True))
        ev = _evaluate(obj, page_text, rr.url)

        if not ev["tracks"]:
            continue
        candidates += 1

        if ev["fit"] == "REJECT_GEO":
            rejected_geo += 1
            continue
        if ev["fit"] == "REJECT_DUTCH":
            rejected_language += 1
            continue
        if ev["fit"] == "REJECT_EXPERIENCE":
            rejected_experience += 1
            continue
        if ev["fit"] == "REJECT_SENIORITY":
            continue
        if ev["fit"] not in {"GOOD", "STRETCH"}:
            continue

        jobs.append(make_job(
            source, company, _job_id(obj, rr.url), ev["title"], ev["location"],
            ev["description"], rr.url,
        ))

    metrics = {
        "seen": seen,
        "candidates": candidates,
        "kept": len(jobs),
        "non_target": max(0, seen - candidates),
        "rejected_language": rejected_language,
        "rejected_geo": rejected_geo,
        "closed": closed,
        "detail_errors": errors,
    }

    return _publish(source, metrics, jobs, {
        "detail_probe_ok": detail_ok,
        "candidate_urls": len(candidate_urls),
        "rejected_experience": rejected_experience,
        "strict_geo": True,
        "strict_language": True,
        "known_false_positive_should_reject": "HR Data Analyst Wingene",
    })


def get_mega64_diag(source):
    return dict(_LAST_DIAG.get(str(source).upper(), {}))


def regression_checks():
    checks = {}

    fake_fr = {
        "@type": "JobPosting",
        "jobLocation": {
            "address": {
                "addressLocality": "Puteaux",
                "addressCountry": "France",
            }
        },
    }
    fake_png = {
        "@type": "JobPosting",
        "jobLocation": {
            "address": {
                "addressLocality": "Port Moresby",
                "addressCountry": "Papua New Guinea",
            }
        },
    }
    fake_be = {
        "@type": "JobPosting",
        "jobLocation": {
            "address": {
                "addressLocality": "Ardooie",
                "addressCountry": "Belgium",
            }
        },
    }

    checks["puteaux_france_not_be"] = strict_geo(fake_fr)[0] == "FOREIGN"
    checks["papua_new_guinea_not_be"] = strict_geo(fake_png)[0] == "FOREIGN"
    checks["ardooie_belgium_is_be"] = strict_geo(fake_be)[0] == "BE"

    nl1 = (
        "Voor onze partner zoeken we een Data Analyst. "
        "Je bent analytisch sterk. Jouw verantwoordelijkheden zijn data analyseren. "
        "Communicatief vaardig in het Nederlands en Engels."
    )
    checks["experis_like_dutch_rejected"] = hard_dutch(nl1)

    nl2 = (
        "Wat zal je job inhouden? Wat zoeken we? Minstens 3 jaar heb je ervaring. "
        "Je hebt sterke analytische vaardigheden. Solliciteer voor deze job."
    )
    checks["synergie_like_dutch_rejected"] = hard_dutch(nl2)

    return checks


# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1
from sources.unified_discovery import master_track_hits
_ud_original_track_hits = track_hits

def track_hits(title):
    out = list(_ud_original_track_hits(title) or [])
    for hit in master_track_hits(title):
        if hit not in out:
            out.append(hit)
    return out
