from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.batch3_wallonia_engine import clean, dutch_hard, geo_status, title_is_target

NSIDE_VERSION = "1.1"

BOARD_URL = "https://n-side.csod.com/ux/ats/careersite/1/home?c=n-side"
TENANT_HOST = "https://n-side.csod.com"
CAREER_SITE_ID = "1"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/152.0.0.0 Safari/537.36"
)

_CONTEXT_RE = re.compile(r"csod\.context\s*=\s*(\{.*?\});", re.DOTALL)
_CLOUD_HOST_RE = re.compile(r"^[a-z0-9-]+\.api\.csod\.com$", re.I)

EXTRA_TARGETS = (
    re.compile(r"\bclinical supply optimization analyst\b", re.I),
)


def _session():
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept-Language": "en-GB,en;q=0.9,fr-BE;q=0.8",
        }
    )
    return s


def _is_target(title):
    title = clean(title)
    return title_is_target(title) or any(p.search(title) for p in EXTRA_TARGETS)


def _parse_context(html):
    match = _CONTEXT_RE.search(html or "")
    if not match:
        raise RuntimeError("N-SIDE CSOD context not found.")

    ctx = json.loads(match.group(1))

    token = clean(ctx.get("token"))
    culture_id = ctx.get("cultureID")
    culture_name = clean(ctx.get("cultureName") or "en-GB")
    cloud = clean((ctx.get("endpoints") or {}).get("cloud")).rstrip("/")

    if not token:
        raise RuntimeError("N-SIDE CSOD token missing.")
    if culture_id is None:
        raise RuntimeError("N-SIDE CSOD cultureID missing.")

    parsed = urlparse(cloud)
    host = (parsed.hostname or "").lower()

    if parsed.scheme != "https" or not _CLOUD_HOST_RE.fullmatch(host):
        raise RuntimeError(f"Unexpected N-SIDE cloud endpoint: {cloud}")

    return {
        "token": token,
        "culture_id": culture_id,
        "culture_name": culture_name,
        "cloud": cloud,
        "corp": clean(ctx.get("corp") or "n-side"),
    }


def _auth_headers(context, content_type=False):
    headers = {
        "Authorization": f"Bearer {context['token']}",
        "CSOD-Accept-Language": context["culture_name"],
        "Accept": "application/json",
        "Referer": BOARD_URL,
    }

    if content_type:
        headers["Content-Type"] = "application/json"

    return headers


def fetch_nside_board():
    s = _session()

    page = s.get(BOARD_URL, timeout=30, allow_redirects=True)
    page.raise_for_status()

    context = _parse_context(page.text)

    payload = {
        "careerSiteId": CAREER_SITE_ID,
        "careerSitePageId": "1",
        "pageNumber": 1,
        "pageSize": 200,
        "cultureId": context["culture_id"],
        "cultureName": context["culture_name"],
        "searchText": "",
        "states": [],
        "countryCodes": [],
        "cities": [],
        "placeID": "",
        "radius": "",
        "postingsWithinDays": "",
        "customFieldCheckboxKeys": [],
        "customFieldDropdowns": [],
        "customFieldRadios": [],
    }

    endpoint = f"{context['cloud']}/rec-job-search/external/jobs"

    response = s.post(
        endpoint,
        json=payload,
        headers=_auth_headers(context, content_type=True),
        timeout=30,
        allow_redirects=False,
    )
    response.raise_for_status()

    envelope = response.json()
    data = envelope.get("data") if isinstance(envelope, dict) else None

    if not isinstance(data, dict):
        raise RuntimeError("N-SIDE board response missing data object.")

    rows = data.get("requisitions") or []

    if not isinstance(rows, list):
        raise RuntimeError("N-SIDE requisitions is not a list.")

    return {
        "session": s,
        "context": context,
        "requisitions": rows,
        "total": int(data.get("totalCount") or len(rows)),
    }


def _listing_location(req):
    values = []

    for loc in req.get("locations") or []:
        if not isinstance(loc, dict):
            continue

        text = " | ".join(
            x
            for x in [
                clean(loc.get("locationDisplayTitle")),
                clean(loc.get("title")),
                clean(loc.get("city")),
                clean(loc.get("state")),
                clean(loc.get("country")),
            ]
            if x
        )

        if text:
            values.append(text)

    return " ; ".join(dict.fromkeys(values))


def _strip_html(value):
    return clean(
        BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)
    )


def fetch_nside_detail_v2(s, context, requisition_id):
    endpoint = (
        f"{TENANT_HOST}/services/x/job-requisition/v2/"
        f"requisitions/{requisition_id}/jobDetails"
        f"?cultureId={context['culture_id']}"
    )

    response = s.get(
        endpoint,
        headers=_auth_headers(context),
        timeout=30,
        allow_redirects=False,
    )

    response.raise_for_status()
    envelope = response.json()
    data = envelope.get("data") if isinstance(envelope, dict) else None

    if not isinstance(data, dict):
        data = {}

    return {
        "endpoint": endpoint,
        "http": response.status_code,
        "data": data,
        "description": _strip_html(data.get("externalDescription")),
    }


def fetch_nside_job_ad(s, context, requisition_id):
    # Exact endpoint used by the public CSOD career-site JS:
    # Services/API/ATS/CareerSite/<site>/JobRequisitions/<id>
    endpoint = (
        f"{TENANT_HOST}/Services/API/ATS/CareerSite/"
        f"{CAREER_SITE_ID}/JobRequisitions/{requisition_id}"
        f"?useMobileAd=false&cultureId={context['culture_id']}"
    )

    response = s.get(
        endpoint,
        headers=_auth_headers(context),
        timeout=30,
        allow_redirects=False,
    )

    if response.status_code in {404, 410}:
        return {
            "closed": True,
            "endpoint": endpoint,
            "http": response.status_code,
        }

    response.raise_for_status()
    payload = response.json()

    # JS contract: data[0].items[0].fields.ad
    root = payload.get("data") if isinstance(payload, dict) else payload

    ad = ""
    title = ""
    location = ""
    reference = ""

    if isinstance(root, list) and root:
        first = root[0] if isinstance(root[0], dict) else {}
        items = first.get("items") or []

        if isinstance(items, list) and items:
            item = items[0] if isinstance(items[0], dict) else {}
            fields = item.get("fields") or {}

            if isinstance(fields, dict):
                ad = fields.get("ad") or ""
                title = clean(
                    fields.get("displayJobTitle")
                    or fields.get("title")
                    or ""
                )
                location = clean(
                    fields.get("location")
                    or fields.get("primaryLocation")
                    or ""
                )
                reference = clean(
                    fields.get("ref")
                    or fields.get("reference")
                    or ""
                )

    description = _strip_html(ad)

    return {
        "closed": False,
        "endpoint": endpoint,
        "http": response.status_code,
        "description": description,
        "title": title,
        "location": location,
        "reference": reference,
        "payload_shape": type(root).__name__,
    }


def fetch_nside_detail(s, context, requisition_id, listing_title="", listing_location=""):
    v2 = fetch_nside_detail_v2(s, context, requisition_id)
    ad = fetch_nside_job_ad(s, context, requisition_id)

    if ad.get("closed"):
        return ad

    v2_data = v2.get("data") or {}

    description = clean(ad.get("description"))

    if len(description) < 250:
        # Keep V2 only as fallback if it genuinely contains a full description.
        candidate = clean(v2.get("description"))
        if len(candidate) > len(description):
            description = candidate

    primary = v2_data.get("primaryLocation") or {}
    location_parts = []

    if isinstance(primary, dict):
        text = " | ".join(
            x
            for x in [
                clean(primary.get("locationDisplayTitle")),
                clean(primary.get("title")),
                clean(primary.get("city")),
                clean(primary.get("state")),
                clean(primary.get("country")),
            ]
            if x
        )
        if text:
            location_parts.append(text)

    for loc in v2_data.get("additionalLocations") or []:
        if not isinstance(loc, dict):
            continue

        text = " | ".join(
            x
            for x in [
                clean(loc.get("locationDisplayTitle")),
                clean(loc.get("title")),
                clean(loc.get("city")),
                clean(loc.get("state")),
                clean(loc.get("country")),
            ]
            if x
        )

        if text:
            location_parts.append(text)

    location = (
        " ; ".join(dict.fromkeys(location_parts))
        or clean(ad.get("location"))
        or listing_location
    )

    title = (
        clean(v2_data.get("displayTitle"))
        or clean(ad.get("title"))
        or listing_title
    )

    return {
        "closed": False,
        "title": title,
        "location": location,
        "description": description,
        "v2_description_length": len(clean(v2.get("description"))),
        "job_ad_description_length": len(clean(ad.get("description"))),
        "v2_endpoint": v2.get("endpoint"),
        "job_ad_endpoint": ad.get("endpoint"),
        "reference": clean(v2_data.get("ref")) or clean(ad.get("reference")),
    }


def _publish_metrics(metrics):
    try:
        from sources import source_metrics
        store = getattr(source_metrics, "_STORE", None)
        if isinstance(store, dict):
            store["NSIDE"] = dict(metrics)
    except Exception:
        pass


def probe_nside():
    board = fetch_nside_board()

    rows = []

    for req in board["requisitions"]:
        if not isinstance(req, dict):
            continue

        rid = req.get("requisitionId")
        title = clean(req.get("displayJobTitle"))
        location = _listing_location(req)

        rows.append(
            {
                "id": str(rid) if rid is not None else "",
                "title": title,
                "location": location,
                "geo": geo_status(location),
                "target": _is_target(title),
            }
        )

    belgium = [row for row in rows if row["geo"] == "BELGIUM"]
    target_belgium = [row for row in belgium if row["target"]]

    sample_source = target_belgium[:1] or belgium[:1]
    sample_detail = None

    if sample_source:
        row = sample_source[0]
        sample_detail = fetch_nside_detail(
            board["session"],
            board["context"],
            row["id"],
            row["title"],
            row["location"],
        )

    return {
        "total": board["total"],
        "returned": len(rows),
        "belgium_rows": len(belgium),
        "target_belgium_rows": len(target_belgium),
        "rows": rows,
        "sample_detail": sample_detail,
        "sample_detail_ok": bool(
            sample_detail
            and not sample_detail.get("closed")
            and len(clean(sample_detail.get("description"))) >= 250
        ),
        "sample_detail_length": (
            len(clean(sample_detail.get("description")))
            if sample_detail
            else 0
        ),
    }


def collect_nside_jobs():
    board = fetch_nside_board()

    seen = 0
    candidates = 0
    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    detail_errors = 0

    for req in board["requisitions"]:
        if not isinstance(req, dict):
            continue

        seen += 1

        rid = req.get("requisitionId")
        title = clean(req.get("displayJobTitle"))
        listing_location = _listing_location(req)

        if geo_status(listing_location) != "BELGIUM":
            continue

        if not _is_target(title):
            continue

        candidates += 1

        if rid is None:
            detail_errors += 1
            continue

        try:
            detail = fetch_nside_detail(
                board["session"],
                board["context"],
                str(rid),
                title,
                listing_location,
            )
        except Exception:
            detail_errors += 1
            continue

        if detail.get("closed"):
            closed += 1
            continue

        description = clean(detail.get("description"))
        location = clean(detail.get("location")) or listing_location
        final_title = clean(detail.get("title")) or title

        if geo_status(location) != "BELGIUM":
            rejected_geo += 1
            continue

        if len(description) < 250:
            detail_errors += 1
            continue

        if dutch_hard(description):
            rejected_language += 1
            continue

        url = (
            f"https://n-side.csod.com/ux/ats/careersite/"
            f"{CAREER_SITE_ID}/home/requisition/{rid}?c=n-side"
        )

        jobs.append(
            JobOffer(
                source="NSIDE",
                external_id=str(rid),
                title=final_title,
                company="N-SIDE",
                location=location,
                description=description,
                url=url,
                date_published=None,
                contract_type=None,
                language=None,
            )
        )

    metrics = {
        "seen": seen,
        "candidates": candidates,
        "kept": len(jobs),
        "non_target": max(0, seen - candidates),
        "rejected_language": rejected_language,
        "rejected_geo": rejected_geo,
        "closed": closed,
        "detail_errors": detail_errors,
    }

    _publish_metrics(metrics)

    print()
    print("=" * 88)
    print("N-SIDE - CSOD V1.1")
    print("=" * 88)

    for key, value in metrics.items():
        print(f"{key:<20}: {value}")

    for job in jobs:
        print("KEEP |", job.title, "|", job.location)

    return jobs
