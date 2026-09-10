"""
JOBHUNTER - BACKLOG 66 AUTO VALIDATOR / COLLECTOR V14

Safety:
- normal identifiable User-Agent
- no stealth / no CAPTCHA bypass / no IP rotation
- bounded requests and links
- stop/skip on 401/403/429
- only activates sources with concrete public job-listing evidence
- VDAB official API stays NEEDS_CREDENTIALS until credentials/schema are ready
- EURES unofficial JSON endpoint is not auto-activated
- Jobat Student respects existing CACHE_ONLY policy

Tracks:
- regular jobs: QC_PHARMA_LAB, DATA_JUNIOR_BI, QC_DATA_HYBRID
- any genuine student job: STUDENT_ANY
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from sources.api_expansion_common import clean, classify_target_title, make_job
from sources.source_metrics import publish_source_metrics

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "source_backlog_v14.json"
VERSION = "14.2"
TIMEOUT = 25

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "JobHunter/14.0 personal job search; Belgium",
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.6",
})

BLOCK_STATUS = {401, 403, 429}
SPECIAL_SKIP = {
    "EURES": "UNOFFICIAL_ENDPOINT_NOT_AUTO_ACTIVATED",
    "JOBAT_STUDENT": "JOBAT_CACHE_ONLY_POLICY",
}
CREDENTIAL_KEYS = {"VDAB"}

ATS_SIGNATURES = {
    "WORKDAY": ("myworkdayjobs.com", "workday"),
    "SMARTRECRUITERS": ("smartrecruiters.com",),
    "GREENHOUSE": ("greenhouse.io", "boards.greenhouse.io"),
    "LEVER": ("lever.co", "jobs.lever.co"),
    "RECRUITEE": ("recruitee.com",),
    "TEAMTAILOR": ("teamtailor.com",),
    "PERSONIO": ("personio.",),
    "ASHBY": ("ashbyhq.com",),
    "SUCCESSFACTORS": ("successfactors",),
    "TALENTSOFT": ("talentsoft",),
}

JOB_PATH = re.compile(
    r"(?:/job(?:s)?/|/vacature(?:s)?/|/offre(?:s)?/|/emploi(?:s)?/|"
    r"/position(?:s)?/|jobdetail|job-detail|vacancy|vacancies|career-opportunit)",
    re.I,
)
NAV_BAD = re.compile(
    r"\b(login|sign.?in|connexion|inscription|register|privacy|cookie|contact|"
    r"search jobs?|all jobs?|jobs? home|career home|spontaneous|candidature spontan[eé]e)\b",
    re.I,
)
STUDENT = re.compile(
    r"\b(student|étudiant|etudiant|jobstudent|studentenjob|werkstudent|"
    r"job étudiant|job etudiant|student job)\b",
    re.I,
)
SENIOR = re.compile(r"\b(senior|sr\.?|lead|manager|head|director|principal|staff|vp|vice president)\b", re.I)
DATA = re.compile(
    r"\b(data|business intelligence|bi)\b.*\b(analyst|analytics)\b|"
    r"\b(analyst|analytics)\b.*\b(data|business intelligence|bi)\b",
    re.I,
)
HYBRID = re.compile(
    r"\b(lims|data integrity|quality data|digital quality|lab digitali[sz]ation|"
    r"computerized systems? validation|csv specialist|quality systems? analyst|laboratory systems?)\b",
    re.I,
)
QC = re.compile(
    r"\b(qc|quality control|laboratory|laboratoire|lab technician|laborant|"
    r"microbiology|microbiologie|analytical technician|quality technician|chemist|chimiste|hplc|uplc)\b",
    re.I,
)
BELGIUM = re.compile(
    r"\b(belgium|belgique|belgi[ëe]|brussels|bruxelles|wallonia|wallonie|"
    r"flanders|vlaanderen|antwerp|antwerpen|wavre|rixensart|braine|lessines|"
    r"zaventem|mechelen|puurs|beerse|li[èe]ge|namur|charleroi|gent|ghent|"
    r"leuven|louvain|halle|zellik|seneffe|herve|jette|woluwe|machelen)\b",
    re.I,
)
FOREIGN = re.compile(
    r"\b(france|paris|netherlands|nederland|germany|deutschland|luxembourg|"
    r"spain|italy|ireland|united kingdom|uk|switzerland|poland|usa|united states)\b",
    re.I,
)
APPLY = re.compile(r"\b(apply|postuler|solliciteer|candidater|bewerben|apply now)\b", re.I)

GENERIC_NAV_TITLE = re.compile(
    r"^(je cherche un emploi|wie zijn wij|who are we|vacatures|jobs?|alle vacatures|"
    r"toutes les offres|all jobs|careers?|carri[eè]res?|werken bij|offres d['’]emploi)$",
    re.I,
)
NAV_PATH = re.compile(
    r"(?:/jobs?/?$|/careers?/?$|/vacatures?/?$|/alle-vacatures/?$|"
    r"/offres?-d['’]?emploi/?$|/vacatures-per-stad/|/jobs/werken-bij-|"
    r"/jobs/vacatures/?$|/jobs/alle-vacatures/|/go/jobs?[_-]?/\d+/?$)",
    re.I,
)
STUDENT_CONTRACT_CONTEXT = re.compile(
    r"(?:contract|contrat|statuut|type d['’]?emploi|type de contrat|"
    r"arbeidsregime|employment type).{0,100}"
    r"(?:student|étudiant|etudiant|jobstudent|studentenjob|werkstudent)",
    re.I | re.S,
)

def _is_navigation_page(url, title=""):
    path = urlparse(str(url or "")).path
    title = clean(title)
    return bool(
        GENERIC_NAV_TITLE.fullmatch(title)
        or NAV_PATH.search(path)
        or re.search(r"/(?:vacatures|jobs)/(?:vacatures-per-stad|alle-vacatures)(?:/|$)", path, re.I)
    )

def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def canonical(url):
    try:
        p = urlsplit(str(url or ""))
        return urlunsplit((p.scheme, p.netloc, p.path, "", ""))
    except Exception:
        return str(url or "")

def load_backlog(include_all=True):
    if not CONFIG_PATH.exists():
        return []
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    rows = list(payload.get("sources") or [])
    if include_all:
        return rows
    return [r for r in rows if r.get("active") and r.get("validated_url")]

def save_backlog(rows):
    payload = {
        "schema_version": VERSION,
        "purpose": "Backlog V14 automatiquement sondé; seules les sources validées sont actives.",
        "count": len(rows),
        "updated_at": now_iso(),
        "sources": rows,
    }
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)

def _get(url):
    r = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True)
    return r

def _jsonld_jobs(soup):
    out = []
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = node.string or node.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = list(data) if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop()
            if isinstance(obj, dict):
                if obj.get("@type") == "JobPosting":
                    out.append(obj)
                g = obj.get("@graph")
                if isinstance(g, list):
                    stack.extend(g)
    return out

def _detect_ats(text):
    lo = str(text or "").lower()
    for name, needles in ATS_SIGNATURES.items():
        if any(n.lower() in lo for n in needles):
            return name
    return ""

def _candidate_links(base_url, soup, limit=220):
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        label = clean(html_lib.unescape(a.get_text(" ", strip=True)))
        href = canonical(urljoin(base_url, a.get("href")))
        if not href.startswith(("http://", "https://")) or href in seen:
            continue
        seen.add(href)
        blob = f"{label} {urlparse(href).path}"
        if NAV_BAD.search(blob):
            continue
        ats = _detect_ats(href)
        if JOB_PATH.search(urlparse(href).path) or ats:
            links.append((href, label, ats))
        if len(links) >= limit:
            break
    return links

def _safe_probe_row(row, existing_keys):
    key = str(row.get("key") or "").upper()
    url = str(row.get("url") or "").strip()
    result = dict(row)
    result.update({
        "active": False,
        "validated_url": "",
        "validated_at": now_iso(),
        "probe_status": "PENDING",
        "probe_reason": "",
        "probe_job_links": 0,
        "probe_jsonld_jobs": 0,
        "probe_ats": "",
    })

    if key in existing_keys:
        result["probe_status"] = "DUPLICATE_EXISTING"
        result["probe_reason"] = "Source key already present in production registry."
        return result
    if key in CREDENTIAL_KEYS:
        result["probe_status"] = "NEEDS_CREDENTIALS"
        result["health"] = "NEEDS_CREDENTIALS"
        result["probe_reason"] = "Official API requires credentials/schema; not guessed automatically."
        return result
    if key in SPECIAL_SKIP:
        result["probe_status"] = "SKIPPED_POLICY"
        result["probe_reason"] = SPECIAL_SKIP[key]
        return result
    if not url.startswith(("http://", "https://")):
        result["probe_status"] = "SKIPPED_NO_URL"
        result["probe_reason"] = "No usable URL supplied."
        return result

    try:
        r = _get(url)
    except Exception as exc:
        result["probe_status"] = "WARN_FETCH"
        result["probe_reason"] = f"{type(exc).__name__}: {exc}"
        return result

    if r.status_code in BLOCK_STATUS:
        result["probe_status"] = "SKIPPED_BLOCKED"
        result["probe_reason"] = f"HTTP {r.status_code}; no bypass attempted."
        return result
    if r.status_code >= 400:
        result["probe_status"] = "WARN_HTTP"
        result["probe_reason"] = f"HTTP {r.status_code}"
        return result

    result["validated_url"] = canonical(r.url)
    ctype = str(r.headers.get("content-type") or "").lower()
    if "html" not in ctype and "<html" not in r.text[:500].lower():
        result["probe_status"] = "PENDING_NON_HTML"
        result["probe_reason"] = f"Accessible but unsupported content-type: {ctype}"
        return result

    soup = BeautifulSoup(r.text, "html.parser")
    jsonld = _jsonld_jobs(soup)
    links = _candidate_links(r.url, soup)
    ats = _detect_ats(r.url + "\n" + r.text[:500000])
    if not ats:
        for href, _, a in links:
            if a:
                ats = a
                break

    result["probe_jsonld_jobs"] = len(jsonld)
    result["probe_job_links"] = len(links)
    result["probe_ats"] = ats

    # Concrete activation evidence. A single generic "jobs" link is too weak.
    evidence = len(jsonld) > 0 or len(links) >= 2 or bool(ats)
    if not evidence:
        result["probe_status"] = "PENDING_NO_JOB_EVIDENCE"
        result["probe_reason"] = "Page reachable but no robust public job-listing evidence."
        return result

    result["active"] = True
    result["status"] = "ACTIVE"
    result["health"] = "HEALTHY"
    result["collection_mode"] = "LIVE"
    result["collector_module"] = "sources.backlog_validator_v14"
    result["collector_name"] = "collect_backlog_source_jobs"
    result["probe_status"] = "ACTIVATED"
    result["probe_reason"] = (
        f"Validated public page: jsonld={len(jsonld)}, job_links={len(links)}, ats={ats or 'NONE'}"
    )
    return result

def validate_all_backlog(existing_keys, progress=None, pause_seconds=1.0):
    rows = load_backlog(include_all=True)
    out = []
    total = len(rows)
    for i, row in enumerate(rows, 1):
        if progress:
            progress(i, total, row)
        validated = _safe_probe_row(row, set(existing_keys))
        out.append(validated)
        # Respectful pacing; one main request per candidate.
        if i < total:
            time.sleep(max(0.0, float(pause_seconds)))
    save_backlog(out)
    return out

def _track(title, body, student_hint=False):
    title = clean(title)
    body = clean(body)
    blob = clean(f"{title} {body}")

    if student_hint or STUDENT.search(title):
        return "STUDENT_ANY"
    if SENIOR.search(title):
        return None

    base = classify_target_title(title)
    if base:
        return base
    if HYBRID.search(blob):
        return "QC_DATA_HYBRID"
    if DATA.search(title):
        exp = re.search(r"\b([3-9]|[1-9]\d)\+?\s+years?\b", blob, re.I)
        if not exp:
            return "DATA_JUNIOR_BI"
    if QC.search(title):
        return "QC_PHARMA_LAB"
    return None

def _company(obj, default):
    org = obj.get("hiringOrganization") if isinstance(obj, dict) else None
    if isinstance(org, dict):
        v = clean(org.get("name"))
        if v:
            return v
    return default

def _loc(obj):
    if not isinstance(obj, dict):
        return ""
    loc = obj.get("jobLocation")
    items = loc if isinstance(loc, list) else [loc]
    vals = []
    for item in items:
        if not isinstance(item, dict):
            continue
        addr = item.get("address") or {}
        if isinstance(addr, dict):
            vals.extend(str(addr.get(k) or "") for k in (
                "addressLocality", "addressRegion", "postalCode", "addressCountry"
            ))
    return clean(" ".join(vals))

def _hash(*parts):
    raw = "|".join(clean(x).lower() for x in parts)
    return hashlib.sha1(raw.encode("utf-8","ignore")).hexdigest()[:22]

def _valid_detail_page(source_key, row, response, soup, list_label=""):
    body = clean(html_lib.unescape(soup.get_text(" ", strip=True)))
    h = soup.find("h1") or soup.find("h2")
    title = clean(html_lib.unescape(h.get_text(" ", strip=True) if h else "")) or clean(list_label)
    objs = _jsonld_jobs(soup)

    if objs:
        obj = objs[0]
        jt = clean(html_lib.unescape(str(obj.get("title") or "")))
        if jt:
            title = jt
        desc = clean(html_lib.unescape(str(obj.get("description") or "")))
        if len(desc) < 100:
            desc = body
        loc = _loc(obj)
        company = _company(obj, row.get("name") or source_key)
    else:
        obj = {}
        desc = body
        loc = ""
        company = row.get("name") or source_key
        # Avoid converting navigation/category pages.
        if not title or len(body) < 350 or not APPLY.search(body):
            return None

    if _is_navigation_page(response.url, title):
        return None

    student_hint = (
        "STUDENT_ANY" in (row.get("tracks") or [])
        and (
            bool(STUDENT.search(title))
            or bool(STUDENT_CONTRACT_CONTEXT.search(body[:5000]))
        )
    )
    track = _track(title, desc, bool(student_hint))
    if not track:
        return None

    # Student jobs from dedicated student sources may be anywhere in Belgium.
    # Professional tracks need Belgian evidence unless the source itself is a BE-only local portal.
    local_be = any(x in (urlparse(str(row.get("url") or "")).netloc.lower()) for x in (
        ".be", "brussels", "uclouvain", "ulb", "vub", "stib", "vivaqua"
    ))
    geo_blob = clean(f"{loc} {body[:5000]}")
    if track != "STUDENT_ANY":
        if FOREIGN.search(loc) and not BELGIUM.search(loc):
            return None
        if not local_be and not BELGIUM.search(geo_blob):
            return None

    url = canonical(response.url)
    identifier = obj.get("identifier") if isinstance(obj, dict) else None
    if isinstance(identifier, dict):
        identifier = identifier.get("value")
    ext = clean(identifier) or _hash(source_key, url, title)

    job = make_job(
        source=source_key,
        external_id=ext,
        title=title,
        company=company,
        location=loc or ("Belgium" if local_be else ""),
        description=desc,
        url=url,
        date_published=obj.get("datePosted") if isinstance(obj, dict) else None,
        contract_type="Student" if track == "STUDENT_ANY" else None,
    )
    setattr(job, "api_target_track", track)
    if track == "STUDENT_ANY":
        setattr(job, "student_source", True)
    return job

def collect_backlog_source_jobs(key):
    key = str(key or "").upper()
    rows = {str(r.get("key") or "").upper(): r for r in load_backlog(include_all=False)}
    row = rows.get(key)
    if not row:
        return []

    # V17: priority source-specific listing recovery.
    try:
        from sources.yield_recovery_v17 import collect_priority_source_jobs
        recovered = collect_priority_source_jobs(key)
        if recovered is not None:
            return recovered
    except Exception as exc:
        print(key, "V17 RECOVERY FALLBACK |", type(exc).__name__, exc)

    seen = target = errors = detail_failed = 0
    jobs = {}
    try:
        r = _get(row["validated_url"])
        if r.status_code in BLOCK_STATUS or r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}")
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as exc:
        publish_source_metrics(key, {
            "seen":0,"target_title":0,"non_target":0,"detail_ok":0,"detail_failed":1,
            "geography_accepted":0,"geography_rejected":0,"geography_unknown":0,
            "language_rejected":0,"converted":0,"persisted":None,"errors":1,
        })
        print(key, "LIST ERROR |", type(exc).__name__, exc)
        return []

    for obj in _jsonld_jobs(soup):
        seen += 1
        try:
            # Use current listing page as response for embedded JobPosting.
            fake_url = clean(obj.get("url")) or r.url
            class R:
                url = fake_url
            # Build a tiny synthetic soup from JobPosting metadata through regular path.
            title = clean(html_lib.unescape(str(obj.get("title") or "")))
            desc = clean(html_lib.unescape(str(obj.get("description") or "")))
            if _is_navigation_page(fake_url, title):
                continue
            student_hint = (
                "STUDENT_ANY" in (row.get("tracks") or [])
                and (
                    bool(STUDENT.search(title))
                    or bool(STUDENT_CONTRACT_CONTEXT.search(desc[:5000]))
                )
            )
            track = _track(title, desc, bool(student_hint))
            if not track:
                continue
            loc = _loc(obj)
            local_be = ".be" in urlparse(str(row.get("url") or "")).netloc.lower()
            if track != "STUDENT_ANY" and FOREIGN.search(loc) and not BELGIUM.search(loc):
                continue
            ext = obj.get("identifier")
            if isinstance(ext, dict):
                ext = ext.get("value")
            ext = clean(ext) or _hash(key, fake_url, title)
            job = make_job(
                source=key, external_id=ext, title=title,
                company=_company(obj,row.get("name") or key),
                location=loc or ("Belgium" if local_be else ""),
                description=desc, url=canonical(fake_url),
                date_published=obj.get("datePosted"),
                contract_type="Student" if track=="STUDENT_ANY" else None,
            )
            setattr(job,"api_target_track",track)
            if track=="STUDENT_ANY":
                setattr(job,"student_source",True)
            jobs[ext]=job
            target += 1
        except Exception as exc:
            errors += 1
            print(key, "JSONLD ERROR |", type(exc).__name__, exc)

    links = _candidate_links(r.url, soup)
    for href, label, _ats in links[:70]:
        seen += 1
        try:
            dr = _get(href)
            if dr.status_code in BLOCK_STATUS or dr.status_code >= 400:
                continue
            ds = BeautifulSoup(dr.text, "html.parser")
            job = _valid_detail_page(key,row,dr,ds,label)
            if job:
                jobs[job.external_id] = job
                target += 1
            time.sleep(0.12)
        except Exception as exc:
            errors += 1
            detail_failed += 1
            print(key, "DETAIL ERROR |", href, "|", type(exc).__name__, exc)

    publish_source_metrics(key, {
        "seen":seen,
        "target_title":target,
        "non_target":max(0,seen-target),
        "detail_ok":len(jobs),
        "detail_failed":detail_failed,
        "geography_accepted":len(jobs),
        "geography_rejected":0,
        "geography_unknown":0,
        "language_rejected":0,
        "converted":len(jobs),
        "persisted":None,
        "errors":errors,
    })
    print(key, "| V14 | seen=",seen,"| kept=",len(jobs),"| errors=",errors)
    return list(jobs.values())

def make_backlog_collector(key):
    def _collector():
        return collect_backlog_source_jobs(key)
    _collector.__name__ = f"collect_{str(key).lower()}_jobs"
    return _collector
