"""
JOB HUNTER BELGIUM
JEFFERSON WELLS BELGIUM - VERSION 1.0

Collecte publique ciblée Jefferson Wells Belgique.

Stratégie :
- parcourt les pages publiques /fr/rechercher-un-emploi/ ;
- pré-filtre les cartes par titre/extrait (Data/BI + Lab/QC/Pharma) ;
- ne télécharge en détail que les candidats métier ;
- rejette les fiches clairement NL ;
- rejette les fiches qui exigent explicitement un niveau professionnel de néerlandais ;
- conserve FR/EN pour le matcher JobHunter.

Aucun contournement anti-bot n'est utilisé.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.scienceatwork import detect_language as detect_body_language
from sources.randstad import dutch_professional_required
from sources.source_metrics import publish_metrics_from_locals


BASE_URL = "https://jeffersonwells.be"
LISTING_ROOT = f"{BASE_URL}/fr/rechercher-un-emploi/"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAYS = (1, 2, 4)
DETAIL_DELAY_SECONDS = 0.08
MAX_LISTING_PAGES = 30
MAX_LISTING_AGE_DAYS = 120
MIN_DESCRIPTION_LENGTH = 180

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIST_CACHE_DIR = PROJECT_ROOT / "logs" / "jeffersonwells_listing_cache"
DETAIL_CACHE_DIR = PROJECT_ROOT / "logs" / "jeffersonwells_detail_cache"
LIST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
DETAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0 Safari/537.36 Edg/151.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.2",
        "Cache-Control": "no-cache",
    }
)

JOB_PATH_RE = re.compile(r"^/(?:fr/)?vacancies/(\d+)-[^/?#]+/?$", re.I)

# Préfiltre volontairement assez large : le matcher JobHunter tranche ensuite.
TARGET_PATTERNS = (
    '\\bjunior\\s+(?:business\\s+)?data\\s+analyst\\b',
    '\\bdata\\s+analyst\\b',
    '\\bbusiness\\s+(?:data\\s+)?analyst\\b',
    '\\bfunctional\\s+analyst\\b',
    '\\bdata\\s+quality\\b',
    '\\bdata\\s+steward\\b',
    '\\bmaster\\s+data\\b',
    '\\breporting\\b',
    '\\bpower\\s*bi\\b',
    '\\bbusiness\\s+intelligence\\b',
    '\\bbi\\s+analyst\\b',
    '\\blab(?:oratory)?\\s+analyst\\b',
    '\\blab(?:oratory)?\\s+(?:operations\\s+)?technician\\b',
    '\\blab\\s+technician\\b',
    '\\bqc\\b',
    '\\bquality\\s+control\\b',
    '\\bquality\\s+engineer\\b',
    '\\bquality\\s+project\\b',
    '\\blaunch\\s+excellence\\s+technician\\b',
    '\\banalytical\\s+scientist\\b',
    '\\banalytical\\s+(?:chemist|chemistry)\\b',
    '\\bchemist\\b',
    '\\bchemistry\\b',
    '\\bmicrobiolog(?:y|ical|ist)\\b',
    '\\bpharma(?:ceutical)?\\b',
    '\\bgmp\\b',
    '\\blims\\b',
    '\\bhplc\\b',
    '\\btechnicien(?:ne)?\\s+(?:de\\s+)?laboratoire\\b',
    '\\bcontr[oô]le\\s+qualit[eé]\\b',
    '\\bassurance\\s+qualit[eé]\\b',
    '\\banalyste\\s+(?:de\\s+)?laboratoire\\b',
    '\\banalyste\\s+(?:qc|qualit[eé])\\b',
    '\\btechnicien(?:ne)?\\s+chimiste\\b',
    '\\banalyste\\s+(?:de\\s+)?donn[eé]es\\b',
    '\\banalyste\\s+fonctionnel(?:le)?\\b',
    '\\banalyste\\s+bi\\b',
    '\\bd[eé]veloppeur\\s+power\\s*bi\\b',
)

STOP_MARKERS = (
    "apply now",
    "solutions",
    "numéros de certification",
    "numeros de certification",
    "nous suivre",
    "dernières publications",
    "dernieres publications",
)


def clean_text(value) -> str:
    if value is None:
        return ""
    value = html_lib.unescape(str(value)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def _normalize(value) -> str:
    return clean_text(value).lower().replace("’", "'")


def _hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:24]


def _request_html(url: str) -> tuple[str | None, str | None]:
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            text = response.text or ""
            if len(text) < 500:
                raise ValueError(f"HTML trop court ({len(text)} caractères)")
            return text, None
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAYS[attempt])
    return None, last_error


def _listing_url(page: int) -> str:
    if page <= 1:
        return LISTING_ROOT
    return f"{LISTING_ROOT}page/{page}/"


def _listing_cache_path(page: int) -> Path:
    return LIST_CACHE_DIR / f"page_{page}.html"


def _listing_html(page: int, use_cache: bool = True):
    url = _listing_url(page)
    html, error = _request_html(url)
    cache = _listing_cache_path(page)
    if html:
        try:
            cache.write_text(html, encoding="utf-8")
        except Exception:
            pass
        return html, False, None
    if use_cache and cache.exists():
        try:
            return cache.read_text(encoding="utf-8"), True, error
        except Exception:
            pass
    return None, False, error


def _nearest_card_text(anchor, external_id: str) -> str:
    """Retourne le plus petit ancêtre qui ressemble à UNE carte emploi."""
    node = anchor
    best = ""
    for _ in range(8):
        node = getattr(node, "parent", None)
        if node is None or not hasattr(node, "find_all"):
            break
        links = []
        for a in node.find_all("a", href=True):
            path = urlparse(urljoin(BASE_URL, clean_text(a.get("href")))).path
            m = JOB_PATH_RE.match(path)
            if m:
                links.append(m.group(1))
        distinct = set(links)
        if distinct == {external_id}:
            text = clean_text(node.get_text(" ", strip=True))
            if text and (not best or len(text) < len(best)):
                best = text
        elif len(distinct) > 1:
            break
    return best


def _extract_date(card_text: str) -> str:
    m = re.search(r"\bDate\s*:?\s*(.{3,35}?)(?=\s+Bullhorn\s+Job\s+Id|$)", card_text, flags=re.I)
    return clean_text(m.group(1)) if m else ""


_MONTHS = {
    "janvier": 1, "january": 1, "januari": 1,
    "fevrier": 2, "february": 2, "februari": 2,
    "mars": 3, "march": 3, "maart": 3,
    "avril": 4, "april": 4,
    "mai": 5, "may": 5, "mei": 5,
    "juin": 6, "june": 6, "juni": 6,
    "juillet": 7, "july": 7, "juli": 7,
    "aout": 8, "august": 8, "augustus": 8,
    "septembre": 9, "september": 9,
    "octobre": 10, "october": 10,
    "novembre": 11, "november": 11,
    "decembre": 12, "december": 12,
}


def _ascii_lower(value: str) -> str:
    value = unicodedata.normalize("NFKD", clean_text(value))
    return "".join(ch for ch in value if not unicodedata.combining(ch)).lower()


def _parse_listing_date(value: str):
    text = _ascii_lower(value).replace(",", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    # 17 août 2026
    m = re.match(r"^(\d{1,2})\s+([a-z]+)\s+(\d{4})$", text)
    if m and m.group(2) in _MONTHS:
        try:
            return datetime(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
        except ValueError:
            return None
    # novembre 5 2025
    m = re.match(r"^([a-z]+)\s+(\d{1,2})\s+(\d{4})$", text)
    if m and m.group(1) in _MONTHS:
        try:
            return datetime(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2)))
        except ValueError:
            return None
    return None


def _extract_location(card_text: str) -> str:
    m = re.search(r"\bLocation\s*:?\s*(.{2,80}?)(?=\s+Date\b|\s+Bullhorn\s+Job\s+Id|$)", card_text, flags=re.I)
    return clean_text(m.group(1)) if m else ""


def _is_target_candidate(title: str, card_text: str) -> bool:
    haystack = _normalize(" ".join([title, card_text]))
    return any(re.search(pattern, haystack, flags=re.I) for pattern in TARGET_PATTERNS)


def _parse_listing_jobs(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, dict] = {}
    for anchor in soup.find_all("a", href=True):
        href = clean_text(anchor.get("href"))
        if not href:
            continue
        absolute = urljoin(BASE_URL, href)
        path = urlparse(absolute).path
        match = JOB_PATH_RE.match(path)
        if not match:
            continue
        external_id = match.group(1)
        title = clean_text(anchor.get_text(" ", strip=True))
        if not title or title.lower() in {"apply now", "postuler"}:
            title = ""
        card_text = _nearest_card_text(anchor, external_id)
        row = found.setdefault(
            external_id,
            {
                "external_id": external_id,
                "url": absolute,
                "title": "",
                "card_text": "",
                "date_published": "",
                "location": "",
            },
        )
        if title and len(title) > len(row.get("title") or ""):
            row["title"] = title
        if card_text and len(card_text) > len(row.get("card_text") or ""):
            row["card_text"] = card_text
            row["date_published"] = _extract_date(card_text)
            row["location"] = _extract_location(card_text)
    return list(found.values())


def collect_listing_candidates(use_cache: bool = True) -> tuple[list[dict], dict]:
    all_jobs: dict[str, dict] = {}
    candidates: dict[str, dict] = {}
    meta = {"pages": 0, "all_links": 0, "candidate_links": 0, "errors": []}

    for page in range(1, MAX_LISTING_PAGES + 1):
        html, from_cache, error = _listing_html(page, use_cache=use_cache)
        if not html:
            if page == 1:
                meta["errors"].append(error or "listing inaccessible")
            break

        rows = _parse_listing_jobs(html)
        if not rows:
            break

        before_all = len(all_jobs)
        before_candidates = len(candidates)
        parsed_dates = []
        for row in rows:
            all_jobs.setdefault(row["external_id"], row)
            parsed_date = _parse_listing_date(row.get("date_published", ""))
            if parsed_date:
                parsed_dates.append(parsed_date)
            is_recent = (
                parsed_date is None
                or parsed_date >= datetime.now() - timedelta(days=MAX_LISTING_AGE_DAYS)
            )
            if is_recent and _is_target_candidate(row.get("title", ""), row.get("card_text", "")):
                candidates.setdefault(row["external_id"], row)

        added_all = len(all_jobs) - before_all
        added_candidates = len(candidates) - before_candidates
        meta["pages"] += 1
        mode = "CACHE" if from_cache else "WEB"
        print(
            f"JEFFERSON WELLS - page {page:2d}: {len(rows):2d} offre(s) | "
            f"+{added_all:<2d} unique(s) | +{added_candidates:<2d} cible(s) | {mode}"
        )

        # Les annonces sont ordonnées de la plus récente à la plus ancienne.
        # Si toute la page a une date lisible et est plus vieille que la fenêtre,
        # les pages suivantes n'apporteraient que de l'historique.
        if parsed_dates and len(parsed_dates) == len(rows):
            if max(parsed_dates) < datetime.now() - timedelta(days=MAX_LISTING_AGE_DAYS):
                print(
                    f"JEFFERSON WELLS - arrêt pagination : page {page} entièrement "
                    f"plus ancienne que {MAX_LISTING_AGE_DAYS} jours."
                )
                break

        # Une page sans nouvel ID indique la fin ou un cycle de pagination.
        if added_all == 0:
            break

    meta["all_links"] = len(all_jobs)
    meta["candidate_links"] = len(candidates)
    return list(candidates.values()), meta


def _detail_cache_path(url: str, external_id: str | None = None) -> Path:
    key = clean_text(external_id) or _hash(url)
    return DETAIL_CACHE_DIR / f"{re.sub(r'[^0-9A-Za-z_-]+', '_', key)}.html"


def _extract_detail_text(soup: BeautifulSoup, title: str) -> str:
    main = soup.find("main") or soup.find("article") or soup.body
    if main is None:
        return ""
    text = clean_text(main.get_text("\n", strip=True))
    low = text.lower()

    if title:
        pos = low.find(title.lower())
        if pos >= 0:
            text = text[pos:]
            low = text.lower()

    cuts = []
    for marker in STOP_MARKERS:
        pos = low.find(marker)
        if pos > 250:
            cuts.append(pos)
    if cuts:
        text = text[: min(cuts)]
    return clean_text(text)


def _extract_contract(text: str) -> str:
    low = _normalize(text)
    candidates = (
        "contracting",
        "vast contract",
        "permanent contract",
        "freelance",
        "cdi",
        "cdd",
        "temporary",
        "temporaire",
    )
    for candidate in candidates:
        if candidate in low:
            return candidate
    return ""


def _detect_language(text: str) -> str:
    lang = clean_text(detect_body_language(text)).lower()
    return lang if lang in {"fr", "en", "nl"} else "unknown"


def parse_jeffersonwells_detail(
    html: str,
    url: str,
    external_id: str | None = None,
    fallback: dict | None = None,
) -> dict:
    fallback = fallback or {}
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = clean_text(h1.get_text(" ", strip=True)) if h1 else clean_text(fallback.get("title"))
    text = _extract_detail_text(soup, title)

    id_match = JOB_PATH_RE.match(urlparse(url).path)
    external_id = clean_text(external_id) or (id_match.group(1) if id_match else "") or _hash(url)

    location = clean_text(fallback.get("location"))
    m_loc = re.search(r"\bLocation\s*:\s*(.{2,100}?)(?=\s+Job\s*#|\s+[A-Z][A-Za-z]+\s*[–-]|$)", text, flags=re.I)
    if m_loc:
        location = clean_text(m_loc.group(1))

    # Certaines fiches commencent par "Locatie – Puurs" ou "Contracting – Brabant Wallon".
    if not location:
        m_loc2 = re.search(r"\b(?:Locatie|Lieu)\s*[–:-]\s*([^|]{2,80})", text, flags=re.I)
        if m_loc2:
            location = clean_text(m_loc2.group(1))

    language = _detect_language(text)
    dutch_required = dutch_professional_required(text)
    contract = _extract_contract(text)

    structured = {
        "external_id": external_id,
        "url": url,
        "title": title,
        "company": "Jefferson Wells / client",
        "location": location or "Belgique",
        "contract_type": contract,
        "date_published": clean_text(fallback.get("date_published")),
        "language": language,
        "dutch_required": dutch_required,
        "bullhorn_job_id": external_id,
    }

    success = bool(title and len(text) >= MIN_DESCRIPTION_LENGTH)
    return {
        "success": success,
        "matching_text": text,
        "matching_text_length": len(text),
        "structured": structured,
        "from_cache": False,
        "error": None if success else (
            f"Jefferson Wells : fiche incomplète (titre={bool(title)}, description={len(text)} car.)"
        ),
    }


def get_jeffersonwells_job_detail(
    url: str,
    external_id: str | None = None,
    use_cache: bool = True,
    fallback: dict | None = None,
) -> dict:
    cache = _detail_cache_path(url, external_id)
    if use_cache and cache.exists():
        try:
            result = parse_jeffersonwells_detail(
                cache.read_text(encoding="utf-8"), url, external_id, fallback=fallback
            )
            if result.get("success"):
                result["from_cache"] = True
                return result
        except Exception:
            pass

    html, error = _request_html(url)
    if not html:
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": {"external_id": external_id, "url": url},
            "from_cache": False,
            "error": f"Jefferson Wells : {error or 'lecture HTTP impossible'}",
        }
    try:
        cache.write_text(html, encoding="utf-8")
    except Exception:
        pass
    return parse_jeffersonwells_detail(html, url, external_id, fallback=fallback)


def _job_from_detail(detail: dict, fallback: dict) -> JobOffer:
    structured = detail.get("structured") or {}
    job = JobOffer(
        source="JEFFERSON_WELLS",
        external_id=clean_text(structured.get("external_id") or fallback.get("external_id")),
        title=clean_text(structured.get("title") or fallback.get("title") or "Titre inconnu"),
        company=clean_text(structured.get("company") or "Jefferson Wells / client"),
        location=clean_text(structured.get("location") or fallback.get("location") or "Belgique"),
        description=clean_text(detail.get("matching_text")),
        url=clean_text(structured.get("url") or fallback.get("url")),
        date_published=clean_text(structured.get("date_published") or fallback.get("date_published")) or None,
        contract_type=clean_text(structured.get("contract_type")) or None,
        language=clean_text(structured.get("language")) or None,
    )
    job.collection_channel = "JEFFERSON_WELLS"
    job.origin_source = "JEFFERSON_WELLS"
    job.bullhorn_job_id = clean_text(structured.get("bullhorn_job_id"))
    return job


def search_targeted_jeffersonwells_jobs() -> list[JobOffer]:
    print("JEFFERSON WELLS - collecte ciblée Belgique")
    candidates, meta = collect_listing_candidates(use_cache=True)
    print(
        "JEFFERSON WELLS - préfiltre : "
        f"{meta.get('all_links', 0)} offre(s) vues sur {meta.get('pages', 0)} page(s), "
        f"{len(candidates)} candidate(s) métier"
    )
    for error in meta.get("errors") or []:
        print(f"JEFFERSON WELLS - avertissement listing : {error}")
    if not candidates:
        raise RuntimeError("Jefferson Wells : aucun candidat métier détecté.")

    jobs: list[JobOffer] = []
    errors = 0
    rejected_nl = 0
    rejected_dutch = 0
    languages = {"fr": 0, "en": 0, "unknown": 0}

    for index, item in enumerate(candidates, start=1):
        detail = get_jeffersonwells_job_detail(
            item["url"], item["external_id"], use_cache=True, fallback=item
        )
        structured = detail.get("structured") or {}
        title = clean_text(structured.get("title") or item.get("title") or "Titre inconnu")

        if not detail.get("success"):
            errors += 1
            print(
                f"[{index:03d}/{len(candidates):03d}] ❌ DETAIL | {title} | "
                f"{clean_text(detail.get('error'))}"
            )
            continue

        language = clean_text(structured.get("language") or "unknown").lower()
        if language == "nl":
            rejected_nl += 1
            print(f"[{index:03d}/{len(candidates):03d}] ⛔ NL     | {title}")
            continue

        if bool(structured.get("dutch_required")):
            rejected_dutch += 1
            print(f"[{index:03d}/{len(candidates):03d}] ⛔ DUTCH  | {title} | néerlandais professionnel requis")
            continue

        if language not in languages:
            language = "unknown"
        languages[language] += 1
        job = _job_from_detail(detail, item)
        jobs.append(job)
        print(
            f"[{index:03d}/{len(candidates):03d}] ✅ {language.upper():<7} | "
            f"{len(job.description):4d} car. | {job.title} | {job.location}"
        )
        time.sleep(DETAIL_DELAY_SECONDS)

    print()
    print("=" * 76)
    print("              BILAN JEFFERSON WELLS V1.0")
    print("=" * 76)
    print(f"Offres vues dans les listings       : {meta.get('all_links', 0)}")
    print(f"Candidates métier préfiltrées       : {len(candidates)}")
    print(f"Conservées FR/EN/ambiguës           : {len(jobs)}")
    print(f"  Français                          : {languages['fr']}")
    print(f"  Anglais                           : {languages['en']}")
    print(f"  Langue ambiguë                    : {languages['unknown']}")
    print(f"Rejetées - fiche clairement NL      : {rejected_nl}")
    print(f"Rejetées - néerlandais requis       : {rejected_dutch}")
    print(f"Échecs détail                       : {errors}")
    publish_metrics_from_locals("JEFFERSON_WELLS", locals())
    return jobs


def collect_jeffersonwells_jobs() -> list[JobOffer]:
    return search_targeted_jeffersonwells_jobs()


# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1
from sources.unified_discovery import matches_master_title
_ud_original__is_target_candidate = _is_target_candidate

def _is_target_candidate(title, card_text):
    if _ud_original__is_target_candidate(title, card_text):
        return True
    return matches_master_title(title)
