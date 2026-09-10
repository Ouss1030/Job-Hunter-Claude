from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.batch4_engine import clean, dutch_hard, title_is_target, publish_metrics

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36"
TIMEOUT = 30
MIN_DESC = 220

_LAST_DIAG = {}

BLOCK_TITLE = re.compile(
    r"\b(?:senior|sr\.?|principal|staff|director|head|manager|management|"
    r"team\s+leader|leader|lead|supervisor|intern(?:ship)?|stage|trainee|"
    r"apprentice|phd)\b",
    re.I,
)

EXTRA_TARGETS = (
    re.compile(r"\bdata analyst\b", re.I),
    re.compile(r"\bbusiness analyst\b", re.I),
    re.compile(r"\bbi engineer\b", re.I),
    re.compile(r"\bpower\s*bi\b", re.I),
    re.compile(r"\bdata governance\b", re.I),
    re.compile(r"\bdata quality\b", re.I),
    re.compile(r"\bdata steward\b", re.I),
    re.compile(r"\bmaster data\b", re.I),
    re.compile(r"\bfunctional analyst\b", re.I),
    re.compile(r"\bquality assurance\b", re.I),
    re.compile(r"\bquality control\b", re.I),
    re.compile(r"\bvalidation\b", re.I),
    re.compile(r"\bqualification\b", re.I),
    re.compile(r"\blaborantin\b", re.I),
    re.compile(r"\blab(?:oratory)?\s+(?:technician|analyst)\b", re.I),
)

BELGIUM_CITIES = (
    "brussels", "bruxelles", "diegem", "machelen", "zaventem", "leuven",
    "herstal", "liège", "liege", "welkenraedt", "huizingen", "antwerp",
    "antwerpen", "wavre", "charleroi", "gosselies", "nivelles",
    "louvain-la-neuve", "ottignies", "grimbergen", "seraing",
)


def _target(title):
    title = clean(title)
    if not title or BLOCK_TITLE.search(title):
        return False
    return title_is_target(title) or any(p.search(title) for p in EXTRA_TARGETS)


def _session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.2",
    })
    return s


def _stable_id(source, url, title=""):
    raw = f"{source}|{clean(url).lower()}|{clean(title).lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _is_be(text):
    low = clean(text).lower()
    return (
        bool(re.search(r"\b(?:belgium|belgique|belgië|\bBE\b)\b", text, re.I))
        or any(city in low for city in BELGIUM_CITIES)
    )


def _job(source, company, external_id, title, location, description, url, date_published=None):
    return JobOffer(
        source=source,
        external_id=clean(external_id) or _stable_id(source, url, title),
        title=clean(title),
        company=company,
        location=clean(location) or "Belgium",
        description=clean(description),
        url=clean(url),
        date_published=clean(date_published) or None,
        contract_type=None,
        language=None,
    )


def _publish(source, seen, candidates, jobs, *,
             rejected_language=0, rejected_geo=0, closed=0,
             detail_errors=0, diag=None):
    metrics = {
        "seen": int(seen),
        "candidates": int(candidates),
        "kept": len(jobs),
        "non_target": max(0, int(seen) - int(candidates)),
        "rejected_language": int(rejected_language),
        "rejected_geo": int(rejected_geo),
        "closed": int(closed),
        "detail_errors": int(detail_errors),
    }

    publish_metrics(source, metrics)
    _LAST_DIAG[source] = dict(diag or {})
    _LAST_DIAG[source]["metrics"] = dict(metrics)

    print()
    print("=" * 92)
    print(source)
    print("=" * 92)
    for k, v in metrics.items():
        print(f"{k:<22}: {v}")
    for item in jobs:
        print("KEEP |", item.title, "|", item.location)

    return jobs


def get_mega512_diag(source):
    return dict(_LAST_DIAG.get(str(source).upper(), {}))


def _h1(soup, fallback=""):
    node = soup.find("h1")
    return clean(node.get_text(" ", strip=True)) if node else clean(fallback)


def _page_text(soup):
    return clean(soup.get_text(" ", strip=True))


# =============================================================================
# AMARIS
# =============================================================================

def collect_amaris_jobs():
    source = "AMARIS"
    company = "Amaris Consulting"
    s = _session()

    links = {}
    pages_ok = 0

    for page in range(1, 6):
        url = "https://jobs.amaris.com/" if page == 1 else f"https://jobs.amaris.com/?page={page}"
        try:
            r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                break
        except Exception:
            break

        pages_ok += 1
        soup = BeautifulSoup(r.text, "html.parser")
        before = len(links)

        for a in soup.find_all("a", href=True):
            u = urljoin(r.url, a["href"]).split("#", 1)[0]
            m = re.search(r"https?://jobs\.amaris\.com/jobs/(\d+)$", u, re.I)
            if m:
                links[m.group(1)] = u

        for m in re.finditer(r'https?://jobs\.amaris\.com/jobs/(\d+)', r.text, re.I):
            links.setdefault(m.group(1), m.group(0))

        if page > 1 and len(links) == before:
            break

    seen = len(links)
    jobs = []
    candidates = 0
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    detail_ok = 0
    geo_truth = 0

    for jid, url in sorted(links.items()):
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
        text = _page_text(soup)
        title = _h1(soup)

        # Amaris detail pages put city close to the title; full text is a reliable
        # fallback because each /jobs/<id> page represents exactly one vacancy.
        header_blob = text[:2200]
        is_be = _is_be(header_blob)
        if is_be:
            geo_truth += 1

        if not _target(title):
            continue
        candidates += 1

        if not is_be:
            rejected_geo += 1
            continue

        if dutch_hard(text):
            rejected_language += 1
            continue

        if len(text) < MIN_DESC:
            errors += 1
            continue

        location = next(
            (city.title() for city in BELGIUM_CITIES if city in header_blob.lower()),
            "Belgium",
        )

        jobs.append(_job(
            source, company, jid, title, location, text, r.url
        ))

    return _publish(
        source, seen, candidates, jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={
            "pages_ok": pages_ok,
            "listing_links": seen,
            "detail_probe_ok": detail_ok,
            "geo_truth_count": geo_truth,
            "engine": "jobs.amaris.com direct HTML",
        },
    )


# =============================================================================
# KEYES / ex-NRB - Recruitee custom domain
# =============================================================================

def _keyes_api_offers(s):
    endpoints = [
        "https://keyescareers.eu/api/offers/",
        "https://keyes.recruitee.com/api/offers/",
        "https://nrb.recruitee.com/api/offers/",
    ]

    for endpoint in endpoints:
        try:
            r = s.get(endpoint, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            data = r.json()
            if isinstance(data, dict):
                rows = data.get("offers") or data.get("jobs") or data.get("results")
            else:
                rows = data
            if isinstance(rows, list) and rows:
                return rows, endpoint
        except Exception:
            continue

    return [], ""


def collect_nrb_jobs():
    source = "NRB"
    company = "KEYES (ex-NRB)"
    s = _session()

    api_rows, api_endpoint = _keyes_api_offers(s)
    links = {}
    api_meta = {}

    if api_rows:
        for row in api_rows:
            if not isinstance(row, dict):
                continue
            slug = clean(row.get("slug") or row.get("id"))
            title = clean(row.get("title") or row.get("name"))
            url = clean(row.get("careers_url") or row.get("url"))
            if not url and slug:
                url = f"https://keyescareers.eu/o/{slug}"
            if url:
                key = clean(row.get("id") or slug or _stable_id(source, url, title))
                links[key] = (url, title)
                api_meta[key] = row

    pages_ok = 0

    if not links:
        for page in range(1, 7):
            url = "https://keyescareers.eu/find-my-job"
            if page > 1:
                url += f"?page={page}"

            try:
                r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
                if r.status_code != 200:
                    break
            except Exception:
                break

            pages_ok += 1
            soup = BeautifulSoup(r.text, "html.parser")
            before = len(links)

            for a in soup.find_all("a", href=True):
                u = urljoin(r.url, a["href"]).split("#", 1)[0]
                m = re.search(r"https?://keyescareers\.eu/o/([^/?#]+)$", u, re.I)
                if m:
                    links[m.group(1)] = (u, clean(a.get_text(" ", strip=True)))

            if page > 1 and len(links) == before:
                break

    seen = len(links)
    jobs = []
    candidates = 0
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    detail_ok = 0
    geo_truth = 0

    for jid, (url, listing_title) in sorted(links.items()):
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
        text = _page_text(soup)
        title = _h1(soup, listing_title)

        location = ""
        for node in soup.find_all(string=re.compile(r"Belgium|Belgique|Brussels|Herstal|Li[eè]ge", re.I)):
            candidate = clean(node.parent.get_text(" ", strip=True) if getattr(node, "parent", None) else node)
            if 2 < len(candidate) < 400:
                location = candidate
                break

        is_be = _is_be(location or text[:1800])
        if is_be:
            geo_truth += 1

        if not _target(title):
            continue
        candidates += 1

        if not is_be:
            rejected_geo += 1
            continue

        if dutch_hard(text):
            rejected_language += 1
            continue

        if len(text) < MIN_DESC:
            errors += 1
            continue

        jobs.append(_job(
            source, company, jid, title, location or "Belgium", text, r.url
        ))

    return _publish(
        source, seen, candidates, jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={
            "api_endpoint": api_endpoint,
            "api_rows": len(api_rows),
            "pages_ok": pages_ok,
            "listing_links": seen,
            "detail_probe_ok": detail_ok,
            "geo_truth_count": geo_truth,
            "engine": "Recruitee custom domain / official KEYES careers",
        },
    )


# =============================================================================
# IQVIA - Workday
# =============================================================================

def collect_iqvia_jobs():
    source = "IQVIA"
    company = "IQVIA Belgium"

    host = "https://iqvia.wd1.myworkdayjobs.com"
    tenant = "iqvia"
    site = "IQVIA"
    board_url = f"{host}/en-US/{site}"
    endpoint = f"{host}/wday/cxs/{tenant}/{site}/jobs"

    s = _session()

    try:
        board = s.get(board_url, timeout=TIMEOUT, allow_redirects=True)
        board.raise_for_status()
    except Exception as exc:
        return _publish(
            source, 0, 0, [],
            detail_errors=1,
            diag={"transport_error": f"BOARD {type(exc).__name__}: {exc}", "geo_truth_count": 0},
        )

    payload = {
        "appliedFacets": {},
        "limit": 20,
        "offset": 0,
        "searchText": "Belgium",
    }

    try:
        r = s.post(
            endpoint,
            json=payload,
            headers={"Content-Type": "application/json", "Referer": board.url},
            timeout=TIMEOUT,
        )
    except Exception as exc:
        return _publish(
            source, 0, 0, [],
            detail_errors=1,
            diag={"transport_error": f"CXS {type(exc).__name__}: {exc}", "geo_truth_count": 0},
        )

    if r.status_code != 200:
        return _publish(
            source, 0, 0, [],
            detail_errors=1,
            diag={
                "board_http": board.status_code,
                "cxs_http": r.status_code,
                "response_preview": clean(r.text)[:500],
                "geo_truth_count": 0,
            },
        )

    data = r.json()
    rows = data.get("jobPostings") or []

    be_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        blob = clean(row.get("locationsText")) + " " + json.dumps(row, ensure_ascii=False)
        if _is_be(blob):
            be_rows.append(row)

    candidates = [row for row in be_rows if _target(row.get("title"))]

    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    detail_ok = 0

    probe_rows = candidates if candidates else be_rows[:1]

    detail_cache = {}
    for row in probe_rows:
        path = clean(row.get("externalPath"))
        if not path:
            errors += 1
            continue
        detail_url = f"{host}/wday/cxs/{tenant}/{site}{path}"
        try:
            rr = s.get(detail_url, headers={"Referer": board.url}, timeout=TIMEOUT)
            if rr.status_code in {404, 410}:
                detail_cache[path] = {"closed": True}
                continue
            rr.raise_for_status()
            detail_cache[path] = {"closed": False, "payload": rr.json()}
            detail_ok += 1
        except Exception:
            errors += 1
            detail_cache[path] = {"error": True}

    for row in candidates:
        path = clean(row.get("externalPath"))
        if not path:
            continue

        cached = detail_cache.get(path)
        if cached is None:
            try:
                rr = s.get(
                    f"{host}/wday/cxs/{tenant}/{site}{path}",
                    headers={"Referer": board.url},
                    timeout=TIMEOUT,
                )
                if rr.status_code in {404, 410}:
                    closed += 1
                    continue
                rr.raise_for_status()
                cached = {"closed": False, "payload": rr.json()}
                detail_ok += 1
            except Exception:
                errors += 1
                continue

        if cached.get("error"):
            continue
        if cached.get("closed"):
            closed += 1
            continue

        info = (cached.get("payload") or {}).get("jobPostingInfo") or cached.get("payload") or {}
        title = clean(info.get("title") or row.get("title"))
        location = clean(info.get("location") or info.get("locationText") or row.get("locationsText"))
        desc_html = (
            info.get("jobDescription")
            or info.get("description")
            or info.get("externalJobDescription")
            or ""
        )
        description = clean(BeautifulSoup(str(desc_html), "html.parser").get_text(" ", strip=True))
        if len(description) < MIN_DESC:
            description = clean(json.dumps(info, ensure_ascii=False))

        if len(description) < MIN_DESC:
            errors += 1
            continue

        if not _is_be(location + " " + json.dumps(info, ensure_ascii=False)):
            rejected_geo += 1
            continue

        if dutch_hard(description):
            rejected_language += 1
            continue

        ext_id = clean(
            info.get("jobReqId")
            or info.get("jobRequisitionId")
            or path.rsplit("/", 1)[-1]
        )

        jobs.append(_job(
            source, company, ext_id, title, location or "Belgium",
            description,
            f"{host}/en-US/{site}{path}",
            info.get("postedOn") or info.get("startDate"),
        ))

    return _publish(
        source, len(be_rows), len(candidates), jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={
            "board_http": board.status_code,
            "cxs_http": r.status_code,
            "announced_total": data.get("total"),
            "returned_rows": len(rows),
            "belgium_rows": len(be_rows),
            "geo_truth_count": len(be_rows),
            "detail_probe_ok": detail_ok,
            "engine": "Workday CXS limit=20",
        },
    )


# =============================================================================
# CAPGEMINI BELGIUM - public SuccessFactors HTML
# =============================================================================

def collect_capgemini_eng_jobs():
    source = "CAPGEMINI_ENG"
    company = "Capgemini Belgium"

    s = _session()
    links = {}
    pages_ok = 0

    for startrow in (0, 25, 50, 75, 100):
        url = "https://careers.capgemini.com/search/?q=&locationsearch=Belgium"
        if startrow:
            url += f"&startrow={startrow}"

        try:
            r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                break
        except Exception:
            break

        pages_ok += 1
        soup = BeautifulSoup(r.text, "html.parser")
        before = len(links)

        for a in soup.find_all("a", href=True):
            u = urljoin(r.url, a["href"]).split("#", 1)[0]
            m = re.search(r"/job/[^?#]+/(\d+)/?$", u, re.I)
            if m:
                links[m.group(1)] = (u, clean(a.get_text(" ", strip=True)))

        if startrow and len(links) == before:
            break

    seen = len(links)
    jobs = []
    candidates = 0
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    detail_ok = 0
    geo_truth = 0

    for jid, (url, listing_title) in sorted(links.items()):
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
        text = _page_text(soup)
        title = _h1(soup, listing_title)

        mloc = re.search(
            r"\bLocation:\s*([A-Za-zÀ-ÿ0-9 ,.'’()\-]+?(?:BE|Belgium))\b",
            text,
            re.I,
        )
        location = clean(mloc.group(1)) if mloc else ""

        is_be = _is_be(location)
        if is_be:
            geo_truth += 1

        if not _target(title):
            continue
        candidates += 1

        if not is_be:
            rejected_geo += 1
            continue

        if dutch_hard(text):
            rejected_language += 1
            continue

        if len(text) < MIN_DESC:
            errors += 1
            continue

        mdate = re.search(r"\bPosted on:\s*([0-9]{1,2}\s+[A-Za-z]+\s+20\d{2})", text, re.I)
        posted = clean(mdate.group(1)) if mdate else ""

        jobs.append(_job(
            source, company, jid, title, location or "Belgium",
            text, r.url, posted,
        ))

    return _publish(
        source, seen, candidates, jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={
            "pages_ok": pages_ok,
            "listing_links": seen,
            "detail_probe_ok": detail_ok,
            "geo_truth_count": geo_truth,
            "engine": "careers.capgemini.com public SuccessFactors HTML",
        },
    )
