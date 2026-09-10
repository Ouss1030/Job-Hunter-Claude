"""
JOB HUNTER BELGIUM
CONNECTEUR JOBAT - VERSION 1.6.0 - PRODUCTION CACHE_ONLY V1

Stratégie :
- recherche ciblée uniquement sur des termes FR/EN utiles au profil ;
- lecture des pages publiques Jobat ;
- cache HTML frais réutilisé en priorité selon la profondeur de page ;
- page 1 rafraîchie fréquemment pour préserver la découverte des nouvelles offres ;
- requests avec circuit de panne par run, puis fallback Edge existant ;
- cache HTML par mot-clé/page, sans rafraîchir artificiellement l'âge d'un cache relu ;
- déduplication par job_<id> ;
- filtrage renforcé des titres clairement néerlandophones ;
- extraction enrichie des cartes (JSON-LD / JSON embarqué / DOM visible) ;
- le détail complet n'est PAS chargé ici : il sera enrichi seulement pour les candidats métier.

Ce choix évite de lancer des centaines de pages détaillées inutiles sur un PC 8 Go.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from sources.jobat_browser_consent import handle_jobat_cookie_consent, valid_storage_state_path

from database.models import JobOffer


BASE_URL = "https://www.jobat.be"
SEARCH_PREFIX = f"{BASE_URL}/fr/emplois/titres"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 2
MAX_PAGES_PER_TERM = 3
DELAY_BETWEEN_PAGES = 0.75

# Performance V1.
#
# - Page 1 reste très fraîche : un cache de moins de 4 h peut être réutilisé
#   lors de runs rapprochés, sinon elle est rafraîchie en direct.
# - Pages 2/3 changent moins vite et peuvent réutiliser un cache de 30 h.
# - Après 5 URL Jobat consécutives sans succès via requests, on cesse de
#   répéter le même échec pour le reste du run. Le fallback Edge historique
#   reste inchangé.
PAGE1_CACHE_TTL_SECONDS = 4 * 3600
DEEP_PAGE_CACHE_TTL_SECONDS = 30 * 3600
# Stale fallback remains useful during temporary Jobat blocking, but must not
# silently become arbitrarily old. 72h balances recall with freshness.
MAX_STALE_SEARCH_CACHE_SECONDS = 72 * 3600
DEFAULT_COLLECTION_MODE = "CACHE_ONLY"
HTTP_CIRCUIT_FAILURE_THRESHOLD = 5

_HTTP_CIRCUIT_OPEN = False
_HTTP_CONSECUTIVE_FAILURES = 0
_HTTP_SKIPPED_CALLS = 0
_LAST_PERF_METRICS: dict[str, object] = {}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "logs" / "jobat_search_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

PARSED_SEARCH_CACHE_SCHEMA = 1

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0 Safari/537.36 Edg/151.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8",
    }
)

# Volontairement FR/EN seulement. Le matcher continuera à décider de la pertinence.
JOBAT_TARGET_SEARCH_TERMS = [
    # Data / BI
    "data analyst",
    "junior data analyst",
    "business data analyst",
    "business intelligence",
    "BI analyst",
    "reporting analyst",
    "data quality analyst",
    "data officer",
    "Power BI",
    "SQL analyst",
    "ETL",
    "junior business analyst",
    # Laboratoire / chimie / pharma / quality
    "laborantin",
    "technicien laboratoire",
    "laboratory technician",
    "lab technician",
    "technicien chimiste",
    "analyste laboratoire",
    "QC technician",
    "quality control analyst",
    "quality control",
    "contrôle qualité",
    "analyste QC",
    "quality assurance",
    "assurance qualité",
    "HPLC",
    "microbiologie",
    "microbiology",
    "GMP",
    "LIMS",
    "pharmaceutique",
    "pharmaceutical",
]

# Filtre de langue V2.1.4, calibré sur le vrai Daily Run du 19/08/2026.
#
# Principe :
# - on garde FR/EN ;
# - on rejette les marqueurs NL très fiables même si le titre contient aussi
#   un mot international comme "Business Analyst" ou "Quality Control" ;
# - "Laborant" seul reste volontairement ambigu et n'est PAS rejeté ;
# - "Laborant" + contexte NL (nacht, ploegen, fysisch, staal..., etc.) est rejeté.
#
# Cela évite les faux positifs observés dans V2.1.3 :
# "Business Analyst - verzekeringen", "Laborant vaste nacht",
# "Quality Control Medewerker", "Scientist organische chemie", etc.
DUTCH_HARD_PATTERNS = (
    r"\banalist\b",                 # analyst = EN, analist = NL
    r"\bprocesanalist\w*\b",
    r"\bdatabeheerder\w*\b",
    r"\bartikelbestand\w*\b",
    r"\bfarmaceutisch\w*\b",
    r"\bkwaliteits\w*\b",
    r"\btechnisch(?:e)?\b",
    r"\bproductie\w*\b",
    r"\bprocesoperator\w*\b",
    r"\blogistiek\w*\b",
    r"\bprocessen\b",
    r"\bbedrijfswagen\b",
    r"\bverzekeringen\b",
    r"\bintegratie\b",
    r"\boperationeel\w*\b",
    r"\bverantwoordelijk\w*\b",
    r"\bmedewerker\b",
    r"\bschoonmaak\b",
    r"\bzoekt\b",
    r"\bnacht\b",
    r"\bploegen?\b",
    r"\bvoedingsindustrie\b",
    r"\bvoedingsproductie\b",
    r"\borganische\s+chemie\b",
    r"\bco[oö]rdinator\b",        # orthographe NL avec tréma
    r"\bmonsternemer\w*\b",
    r"\bstaalvoorbereiding\w*\b",
    r"\bgaschromatografie\w*\b",
)

DUTCH_CONTEXT_PATTERNS = (
    r"\bvaste\s+nacht\b",
    r"\bnacht\b",
    r"\btwee\s+ploegen\b",
    r"\b2\s*[- ]?ploegen\b",
    r"\b3\s*[- ]?ploegen\b",
    r"\bploegen?\b",
    r"\bfysisch\w*\b",
    r"\bchemische\s+analyses?\b",
    r"\bvoorbereiding\w*\b",
    r"\bextrusie\w*\b",
    r"\bbeton\b",
    r"\brecyclage\b",
    r"\bserologie\b",
    r"\bvoeding\b",
    r"\bdag\b",
    r"\btijdelijk\w*\b",
    r"\bkans\s+op\b",
    r"\bhaven\s+van\b",
    r"\bregio\b",
    r"\bte\s+[A-ZÀ-ÖØ-Þa-zà-öø-ÿ-]+\b",
)

# Marqueurs FR/EN explicites. Ils servent seulement à éviter de rejeter un
# titre ambigu ; ils ne neutralisent PAS un DUTCH_HARD_PATTERN.
FR_EN_STRONG_PATTERNS = (
    r"\banalyst\b",
    r"\banalyste\b",
    r"\btechnician\b",
    r"\btechnicien(?:ne)?\b",
    r"\blaboratory\b",
    r"\blaboratoire\b",
    r"\blaborantin(?:e)?\b",
    r"\bquality\b",
    r"\bqualit[eé]\b",
    r"\bchemist\b",
    r"\bchimiste\b",
    r"\bmicrobiology\b",
    r"\bmicrobiologie\b",
    r"\bassurance qualit[eé]\b",
    r"\bcontr[oô]le qualit[eé]\b",
    r"\bdata analyst\b",
    r"\bbusiness analyst\b",
    r"\bpower bi\b",
)

JOB_URL_RE = re.compile(r"/(?:fr/emplois|en/jobs|nl/jobs)/[^?#]+/job_(\d+)(?:[/?#]|$)", re.I)

BLOCK_PAGE_MARKERS = (
    "sorry, you have been blocked",
    "you have been blocked",
    "cloudflare ray id",
    "cf-error-details",
)


def _is_block_page(html: str) -> bool:
    low = (html or "").lower()
    return bool(low) and any(marker in low for marker in BLOCK_PAGE_MARKERS)


def clean_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", clean_text(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


def _cache_path(keyword: str, page_number: int) -> Path:
    digest = hashlib.sha1(keyword.encode("utf-8")).hexdigest()[:8]
    return CACHE_DIR / f"{slugify(keyword)[:45]}_{digest}_p{page_number:02d}.html"


def _parsed_cache_path(keyword: str, page_number: int) -> Path:
    return _cache_path(keyword, page_number).with_suffix(".parsed.json")


def _load_parsed_search_cache(
    keyword: str,
    page_number: int,
) -> list[dict] | None:
    html_path = _cache_path(keyword, page_number)
    parsed_path = _parsed_cache_path(keyword, page_number)
    if not html_path.exists() or not parsed_path.exists():
        return None
    try:
        stat = html_path.stat()
        payload = json.loads(parsed_path.read_text(encoding="utf-8"))
        if int(payload.get("schema") or 0) != PARSED_SEARCH_CACHE_SCHEMA:
            return None
        if int(payload.get("html_mtime_ns") or 0) != int(stat.st_mtime_ns):
            return None
        if int(payload.get("html_size") or -1) != int(stat.st_size):
            return None
        rows = payload.get("records")
        return rows if isinstance(rows, list) else None
    except Exception:
        return None


def _save_parsed_search_cache(
    keyword: str,
    page_number: int,
    rows: list[dict],
) -> bool:
    html_path = _cache_path(keyword, page_number)
    parsed_path = _parsed_cache_path(keyword, page_number)
    if not html_path.exists():
        return False
    try:
        stat = html_path.stat()
        payload = {
            "schema": PARSED_SEARCH_CACHE_SCHEMA,
            "keyword": keyword,
            "page_number": int(page_number),
            "html_mtime_ns": int(stat.st_mtime_ns),
            "html_size": int(stat.st_size),
            "records": list(rows or []),
        }
        temp = parsed_path.with_suffix(parsed_path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp.replace(parsed_path)
        return True
    except Exception:
        return False


def _load_cache(keyword: str, page_number: int) -> str | None:
    path = _cache_path(keyword, page_number)
    if not path.exists():
        return None
    try:
        html = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    if _is_block_page(html):
        try:
            path.unlink(missing_ok=True)
            print(f"    🧹 Cache recherche Jobat bloqué supprimé : {path.name}")
        except Exception:
            pass
        return None
    return html


def _cache_age_seconds(keyword: str, page_number: int) -> float | None:
    path = _cache_path(keyword, page_number)
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except Exception:
        return None


def _load_fresh_cache(
    keyword: str,
    page_number: int,
    *,
    ttl_seconds: float,
) -> str | None:
    age = _cache_age_seconds(keyword, page_number)
    if age is None or age > ttl_seconds:
        return None
    return _load_cache(keyword, page_number)


def _force_live_page1() -> bool:
    return str(os.environ.get("JOBHUNTER_JOBAT_FORCE_LIVE_PAGE1", "")).strip().lower() in {
        "1", "true", "yes", "on"
    }


def _reset_http_circuit() -> None:
    global _HTTP_CIRCUIT_OPEN, _HTTP_CONSECUTIVE_FAILURES, _HTTP_SKIPPED_CALLS
    _HTTP_CIRCUIT_OPEN = False
    _HTTP_CONSECUTIVE_FAILURES = 0
    _HTTP_SKIPPED_CALLS = 0


def get_jobat_perf_metrics() -> dict:
    return dict(_LAST_PERF_METRICS)


def _save_cache(keyword: str, page_number: int, html: str) -> None:
    if _is_block_page(html):
        return
    try:
        _cache_path(keyword, page_number).write_text(html, encoding="utf-8")
    except Exception:
        pass


def _requests_html(url: str) -> str | None:
    global _HTTP_CIRCUIT_OPEN, _HTTP_CONSECUTIVE_FAILURES, _HTTP_SKIPPED_CALLS

    if _HTTP_CIRCUIT_OPEN:
        _HTTP_SKIPPED_CALLS += 1
        return None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if response.status_code == 200 and "job_" in response.text and not _is_block_page(response.text):
                _HTTP_CONSECUTIVE_FAILURES = 0
                return response.text
            if response.status_code not in (403, 429, 503):
                print(f"    ⚠️ Jobat HTTP {response.status_code} : {url}")
        except Exception as error:
            if attempt == MAX_RETRIES:
                print("    ⚠️ Jobat requests :", error)
        time.sleep(0.5 * attempt)

    _HTTP_CONSECUTIVE_FAILURES += 1
    if _HTTP_CONSECUTIVE_FAILURES >= HTTP_CIRCUIT_FAILURE_THRESHOLD:
        _HTTP_CIRCUIT_OPEN = True
        print(
            "    ⚡ Jobat HTTP circuit ouvert pour ce run après "
            f"{_HTTP_CONSECUTIVE_FAILURES} URL(s) consécutives sans succès"
        )
    return None


class _EdgeFetcher:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.error = None

    def start(self) -> bool:
        if self.page is not None:
            return True
        if self.error:
            return False
        try:
            from playwright.sync_api import sync_playwright

            self.playwright = sync_playwright().start()
            # Standard browser fallback only: no stealth / anti-detection flags.
            self.browser = self.playwright.chromium.launch(
                channel="msedge",
                headless=True,
            )
            self.context = self.browser.new_context(
                storage_state=valid_storage_state_path(),
                locale="fr-BE",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/151.0 Safari/537.36 Edg/151.0"
                ),
            )
            self.page = self.context.new_page()
            self.page.set_default_timeout(30000)
            return True
        except Exception as error:
            self.error = str(error)
            self.close()
            return False

    def fetch(self, url: str) -> str | None:
        if not self.start():
            return None
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
            handle_jobat_cookie_consent(self.page, self.context, verbose=True)
            try:
                self.page.wait_for_selector('a[href*="/job_"]', timeout=8000)
            except Exception:
                pass
            self.page.wait_for_timeout(500)
            html = self.page.content()
            if _is_block_page(html):
                print("    ⚠️ Jobat Edge : page anti-bot détectée")
                return None
            return html
        except Exception as error:
            print("    ⚠️ Jobat Edge :", error)
            return None

    def close(self) -> None:
        try:
            if self.browser is not None:
                self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright is not None:
                self.playwright.stop()
        except Exception:
            pass
        self.playwright = self.browser = self.context = self.page = None


def _looks_obviously_dutch(title: str) -> bool:
    """Rejette les intitulés Jobat clairement NL, sans sur-filtrer FR/EN.

    Règles V2.1.4 :
    - un marqueur NL "dur" suffit (ex. verzekeringen, medewerker, productie) ;
    - "Laborant" seul reste accepté ;
    - "Laborant" + contexte NL est rejeté ;
    - les titres anglais/français purs restent acceptés.
    """
    raw = clean_text(title)
    text = raw.lower()
    if not text:
        return False

    # 1) Marqueurs néerlandais très fiables : rejet direct.
    if any(re.search(pattern, text, re.I) for pattern in DUTCH_HARD_PATTERNS):
        return True

    # 2) Cas "Laborant" : le mot seul est ambigu en Belgique.
    #    On le rejette uniquement lorsqu'un contexte NL est également présent.
    if re.search(r"\blaborant(?:e)?\b", text):
        context_hits = sum(bool(re.search(pattern, raw, re.I)) for pattern in DUTCH_CONTEXT_PATTERNS)
        if context_hits >= 1:
            return True

    # 3) Titres sans "Laborant" : deux marqueurs contextuels NL sont suffisants.
    context_hits = sum(bool(re.search(pattern, raw, re.I)) for pattern in DUTCH_CONTEXT_PATTERNS)
    fr_en_hits = sum(bool(re.search(pattern, text, re.I)) for pattern in FR_EN_STRONG_PATTERNS)
    if context_hits >= 2 and fr_en_hits == 0:
        return True

    return False


def _nearest_card_text(anchor) -> str:
    node = anchor
    best = ""
    for _ in range(6):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = clean_text(node.get_text(" ", strip=True))
        if 20 <= len(text) <= 700:
            best = text
        if getattr(node, "name", None) in {"article", "li"} and text:
            return text
    return best


def _candidate_title(anchor) -> str:
    title = clean_text(anchor.get_text(" ", strip=True)) or clean_text(anchor.get("title"))
    generic = {"voir", "voir l'offre", "plus d'infos", "postuler", "job", "vacature"}
    if title.lower() not in generic and 3 <= len(title) <= 220:
        return title

    node = anchor
    for _ in range(5):
        node = getattr(node, "parent", None)
        if node is None:
            break
        heading = node.find(["h2", "h3", "h4"]) if hasattr(node, "find") else None
        if heading:
            value = clean_text(heading.get_text(" ", strip=True))
            if 3 <= len(value) <= 220:
                return value
    return ""



def _walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _strip_html_text(value) -> str:
    if value is None:
        return ""
    text = str(value)
    if "<" in text and ">" in text:
        try:
            text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
        except Exception:
            pass
    return clean_text(text)


def _payload_job_id(item: dict) -> str | None:
    # URL/@id sont les signaux les plus fiables.
    for key in ("url", "@id", "jobUrl", "jobURL", "link", "href"):
        value = item.get(key)
        if isinstance(value, str):
            match = re.search(r"job_(\d+)", value, re.I)
            if match:
                return match.group(1)

    # Certains états JS stockent directement jobId/id sous forme numérique.
    for key in ("jobId", "jobID", "vacancyId", "vacancyID"):
        value = item.get(key)
        if isinstance(value, (str, int)) and str(value).isdigit():
            return str(value)
    return None


def _nested_name(value) -> str:
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, dict):
        for key in ("name", "title", "label", "value"):
            result = clean_text(value.get(key))
            if result:
                return result
    return ""


def _payload_company(item: dict) -> str:
    for key in ("companyName", "employerName", "organisationName", "organizationName"):
        value = clean_text(item.get(key))
        if value:
            return value
    for key in ("hiringOrganization", "company", "employer", "organisation", "organization"):
        value = _nested_name(item.get(key))
        if value:
            return value
    return ""


def _payload_location(item: dict) -> str:
    for key in ("locationName", "city", "municipality", "place"):
        value = clean_text(item.get(key))
        if value:
            return value

    location = item.get("jobLocation") or item.get("location")
    locations = location if isinstance(location, list) else [location]
    values = []
    for loc in locations:
        if isinstance(loc, str):
            value = clean_text(loc)
        elif isinstance(loc, dict):
            address = loc.get("address", loc)
            if isinstance(address, str):
                value = clean_text(address)
            elif isinstance(address, dict):
                parts = [
                    address.get("postalCode"),
                    address.get("addressLocality"),
                    address.get("addressRegion"),
                    address.get("addressCountry"),
                ]
                value = clean_text(", ".join(clean_text(part) for part in parts if clean_text(part)))
            else:
                value = ""
        else:
            value = ""
        if value and value not in values:
            values.append(value)
    return " | ".join(values)


def _payload_description(item: dict) -> str:
    candidates = []
    for key in (
        "description", "jobDescription", "shortDescription", "summary", "teaser",
        "intro", "introduction", "snippet", "preview", "body", "content",
    ):
        value = item.get(key)
        if isinstance(value, (str, int, float)):
            text = _strip_html_text(value)
            if 20 <= len(text) <= 12000:
                candidates.append(text)
    return max(candidates, key=len, default="")


def _payload_title(item: dict) -> str:
    for key in ("title", "jobTitle", "name"):
        value = clean_text(item.get(key))
        if 3 <= len(value) <= 240:
            return value
    return ""


def _extract_embedded_job_records(soup: BeautifulSoup) -> dict[str, dict]:
    """Extrait les données Jobat déjà embarquées dans la page de résultats.

    On ne fait aucun nouvel appel réseau. Cela permet de récupérer, lorsqu'ils
    existent dans JSON-LD/état JSON, entreprise, lieu et un résumé plus long.
    """
    records: dict[str, dict] = {}

    scripts = []
    scripts.extend(soup.find_all("script", attrs={"type": "application/ld+json"}))
    scripts.extend(soup.find_all("script", attrs={"type": "application/json"}))
    next_data = soup.find("script", id="__NEXT_DATA__")
    if next_data is not None:
        scripts.append(next_data)

    seen_nodes = set()
    for script in scripts:
        node_id = id(script)
        if node_id in seen_nodes:
            continue
        seen_nodes.add(node_id)
        raw = script.string or script.get_text(" ", strip=True)
        if not raw or len(raw) > 8_000_000:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue

        for item in _walk_json(payload):
            external_id = _payload_job_id(item)
            if not external_id:
                continue

            candidate = {
                "external_id": external_id,
                "title": _payload_title(item),
                "summary": _payload_description(item),
                "company": _payload_company(item),
                "location": _payload_location(item),
                "contract_type": clean_text(item.get("employmentType") or item.get("contractType")),
                "language": clean_text(item.get("inLanguage") or item.get("language")),
                "date_published": clean_text(item.get("datePosted") or item.get("publicationDate")),
            }

            existing = records.setdefault(external_id, {"external_id": external_id})
            for key, value in candidate.items():
                if key == "external_id" or not value:
                    continue
                previous = clean_text(existing.get(key))
                # Pour le résumé, on conserve la version la plus riche.
                if key == "summary":
                    if len(value) > len(previous):
                        existing[key] = value
                elif not previous:
                    existing[key] = value

    return records


def _merge_record(base: dict, extra: dict) -> dict:
    for key in ("title", "company", "location", "contract_type", "language", "date_published"):
        value = clean_text(extra.get(key))
        if value and not clean_text(base.get(key)):
            base[key] = value
    summary = clean_text(extra.get("summary"))
    if len(summary) > len(clean_text(base.get("summary"))):
        base["summary"] = summary
    return base

def parse_jobat_search_html(html: str, keyword: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: dict[str, dict] = {}
    embedded = _extract_embedded_job_records(soup)

    for anchor in soup.find_all("a", href=True):
        href = clean_text(anchor.get("href"))
        match = JOB_URL_RE.search(href)
        if not match:
            continue

        external_id = match.group(1)
        title = _candidate_title(anchor) or clean_text(embedded.get(external_id, {}).get("title"))
        if not title:
            continue
        if _looks_obviously_dutch(title):
            continue

        url = urljoin(BASE_URL, href.split("#", 1)[0])
        summary = _nearest_card_text(anchor)
        record = {
            "external_id": external_id,
            "title": title,
            "url": url,
            "summary": summary,
            "company": "",
            "location": "",
            "contract_type": "",
            "language": "",
            "date_published": "",
            "search_keywords": [keyword],
        }
        _merge_record(record, embedded.get(external_id, {}))

        if external_id not in found:
            found[external_id] = record
        else:
            existing = found[external_id]
            keywords = existing.setdefault("search_keywords", [])
            if keyword not in keywords:
                keywords.append(keyword)
            if len(title) > len(existing.get("title") or ""):
                existing["title"] = title
            _merge_record(existing, record)

    # Certains états JSON peuvent contenir une offre qui n'a pas été retrouvée
    # par l'ancre (rendu JS). On ne l'ajoute que si une URL Jobat exploitable est
    # présente/reconstructible et si le titre passe le filtre de langue.
    for external_id, extra in embedded.items():
        if external_id in found:
            continue
        title = clean_text(extra.get("title"))
        if not title or _looks_obviously_dutch(title):
            continue
        # Sans ancre nous ne connaissons pas le slug : on n'invente pas l'URL.
        # Le record sera ignoré plutôt que d'introduire un lien faux.

    return list(found.values())

def _parse_jobat_page_with_cache(
    html: str,
    keyword: str,
    page_number: int,
    mode: str,
) -> tuple[list[dict], bool]:
    if mode in {"CACHE_FRESH", "CACHE_STALE"}:
        cached = _load_parsed_search_cache(keyword, page_number)
        if cached is not None:
            return cached, True
    parsed = parse_jobat_search_html(html, keyword)
    _save_parsed_search_cache(keyword, page_number, parsed)
    return parsed, False


def prebuild_jobat_parsed_search_cache(
    search_terms: list[str] | None = None,
    max_pages_per_term: int = MAX_PAGES_PER_TERM,
) -> dict:
    terms = list(dict.fromkeys(search_terms or JOBAT_TARGET_SEARCH_TERMS))
    built = hits = missing = errors = records = 0
    for keyword in terms:
        for page_number in range(1, max_pages_per_term + 1):
            html = _load_cache(keyword, page_number)
            if not html:
                missing += 1
                continue
            cached = _load_parsed_search_cache(keyword, page_number)
            if cached is not None:
                hits += 1
                records += len(cached)
                continue
            try:
                parsed = parse_jobat_search_html(html, keyword)
                if _save_parsed_search_cache(keyword, page_number, parsed):
                    built += 1
                    records += len(parsed)
                else:
                    errors += 1
            except Exception:
                errors += 1
    return {
        "terms": len(terms),
        "built": built,
        "hits": hits,
        "missing": missing,
        "errors": errors,
        "records": records,
    }


def _search_url(keyword: str, page_number: int) -> str:
    base = f"{SEARCH_PREFIX}/{slugify(keyword)}"
    return base if page_number <= 1 else f"{base}?page={page_number}"



def _resolve_collection_mode(collection_mode: str | None = None) -> str:
    raw = (
        collection_mode
        or os.environ.get("JOBHUNTER_JOBAT_MODE")
        or DEFAULT_COLLECTION_MODE
    )
    mode = str(raw or "").strip().upper()
    return "LIVE" if mode == "LIVE" else "CACHE_ONLY"


def search_targeted_jobat_jobs(
    search_terms: list[str] | None = None,
    max_pages_per_term: int = MAX_PAGES_PER_TERM,
    collection_mode: str | None = None,
) -> list[dict]:
    global _LAST_PERF_METRICS

    effective_mode = _resolve_collection_mode(collection_mode)
    terms = list(dict.fromkeys(search_terms or JOBAT_TARGET_SEARCH_TERMS))
    jobs_by_id: dict[str, dict] = {}
    edge = _EdgeFetcher()
    _reset_http_circuit()

    perf = {
        "page1_fresh_cache_hits": 0,
        "deep_fresh_cache_hits": 0,
        "stale_cache_fallback_hits": 0,
        "stale_cache_rejected_too_old": 0,
        "stale_cache_max_age_h": 0.0,
        "http_success_pages": 0,
        "edge_success_pages": 0,
        "cache_saves": 0,
        "parsed_pages": 0,
        "parsed_cache_hits": 0,
        "parsed_cache_builds": 0,
        "force_live_page1": bool(_force_live_page1() and effective_mode == "LIVE"),
        "collection_mode": effective_mode,
    }

    print(f"JOBAT - {len(terms)} termes ciblés FR/EN")
    print(f"JOBAT - maximum {max_pages_per_term} page(s) par terme")
    print(
        "JOBAT PERF | page1_cache_ttl_h=4 | deep_cache_ttl_h=30 | "
        "max_stale_h=72 | "
        f"mode={effective_mode} | "
        f"force_live_page1={int(bool(perf['force_live_page1']))}"
    )

    try:
        for term_index, keyword in enumerate(terms, start=1):
            keyword_new = 0
            previous_signature = None

            for page_number in range(1, max_pages_per_term + 1):
                url = _search_url(keyword, page_number)
                html = None
                mode = ""

                # Cache-first prudent:
                # - page 1 seulement si très récente (<4h) ;
                # - pages 2/3 jusqu'à 30h.
                if page_number == 1:
                    if not perf["force_live_page1"]:
                        html = _load_fresh_cache(
                            keyword,
                            page_number,
                            ttl_seconds=PAGE1_CACHE_TTL_SECONDS,
                        )
                        if html:
                            mode = "CACHE_FRESH"
                            perf["page1_fresh_cache_hits"] += 1
                else:
                    html = _load_fresh_cache(
                        keyword,
                        page_number,
                        ttl_seconds=DEEP_PAGE_CACHE_TTL_SECONDS,
                    )
                    if html:
                        mode = "CACHE_FRESH"
                        perf["deep_fresh_cache_hits"] += 1

                if not html and effective_mode == "LIVE":
                    html = _requests_html(url)
                    mode = "HTTP"
                    if html:
                        perf["http_success_pages"] += 1

                if not html and effective_mode == "LIVE":
                    html = edge.fetch(url)
                    mode = "EDGE"
                    if html:
                        perf["edge_success_pages"] += 1

                if not html:
                    # Dernier filet de sécurité : cache ancien mais borné à 72 h.
                    age = _cache_age_seconds(keyword, page_number)
                    if age is not None and age <= MAX_STALE_SEARCH_CACHE_SECONDS:
                        html = _load_cache(keyword, page_number)
                        mode = "CACHE_STALE"
                        if html:
                            perf["stale_cache_fallback_hits"] += 1
                            perf["stale_cache_max_age_h"] = max(
                                float(perf["stale_cache_max_age_h"]),
                                round(age / 3600.0, 2),
                            )
                    elif age is not None:
                        perf["stale_cache_rejected_too_old"] += 1

                if not html:
                    if page_number == 1:
                        print(f"[{term_index:02d}/{len(terms)}] {keyword:<28} indisponible")
                    break

                # Ne jamais réécrire un cache simplement parce qu'on l'a relu :
                # son mtime reste ainsi un vrai indicateur de fraîcheur.
                if mode in {"HTTP", "EDGE"}:
                    _save_cache(keyword, page_number, html)
                    perf["cache_saves"] += 1

                parsed, parsed_cache_hit = _parse_jobat_page_with_cache(
                    html,
                    keyword,
                    page_number,
                    mode,
                )
                perf["parsed_pages"] += 1
                if parsed_cache_hit:
                    perf["parsed_cache_hits"] += 1
                else:
                    perf["parsed_cache_builds"] += 1
                signature = tuple(sorted(item["external_id"] for item in parsed))

                if not signature or signature == previous_signature:
                    break
                previous_signature = signature

                page_new = 0
                for item in parsed:
                    external_id = item["external_id"]
                    if external_id not in jobs_by_id:
                        jobs_by_id[external_id] = item
                        page_new += 1
                        keyword_new += 1
                    else:
                        existing = jobs_by_id[external_id]
                        for found_keyword in item.get("search_keywords", []):
                            if found_keyword not in existing.setdefault("search_keywords", []):
                                existing["search_keywords"].append(found_keyword)

                if page_number == 1:
                    print(
                        f"[{term_index:02d}/{len(terms)}] {keyword:<28} "
                        f"{len(parsed):>3} trouvée(s) | +{page_new:<3} | {mode}"
                    )

                if page_number > 1 and page_new == 0:
                    break
                time.sleep(DELAY_BETWEEN_PAGES)

            if keyword_new:
                print(f"    nouvelles uniques ce terme : {keyword_new} | total Jobat : {len(jobs_by_id)}")
    finally:
        edge.close()

    live_pages = int(perf["http_success_pages"]) + int(perf["edge_success_pages"])
    fresh_cache_pages = int(perf["page1_fresh_cache_hits"]) + int(perf["deep_fresh_cache_hits"])
    if effective_mode == "CACHE_ONLY":
        if int(perf["stale_cache_fallback_hits"]) > 0:
            health_state = "CACHE_ONLY_STALE"
        elif fresh_cache_pages > 0:
            health_state = "CACHE_ONLY_FRESH"
        else:
            health_state = "CACHE_ONLY_EMPTY"
    elif live_pages > 0:
        health_state = "HEALTHY_LIVE"
    elif int(perf["stale_cache_fallback_hits"]) > 0:
        health_state = "DEGRADED_CACHE_FALLBACK"
    elif fresh_cache_pages > 0:
        health_state = "HEALTHY_FRESH_CACHE"
    else:
        health_state = "UNAVAILABLE"

    perf.update(
        {
            "http_circuit_open": bool(_HTTP_CIRCUIT_OPEN),
            "http_consecutive_failures": int(_HTTP_CONSECUTIVE_FAILURES),
            "http_skipped_calls": int(_HTTP_SKIPPED_CALLS),
            "jobs_returned": len(jobs_by_id),
            "health_state": health_state,
        }
    )
    _LAST_PERF_METRICS = dict(perf)

    print(
        "JOBAT PERF SUMMARY | "
        f"p1_cache={perf['page1_fresh_cache_hits']} | "
        f"deep_cache={perf['deep_fresh_cache_hits']} | "
        f"http_ok={perf['http_success_pages']} | "
        f"edge_ok={perf['edge_success_pages']} | "
        f"stale_cache={perf['stale_cache_fallback_hits']} | "
        f"stale_max_age_h={perf['stale_cache_max_age_h']} | "
        f"stale_too_old={perf['stale_cache_rejected_too_old']} | "
        f"health={perf['health_state']} | "
        f"http_skipped={perf['http_skipped_calls']} | "
        f"http_circuit={int(perf['http_circuit_open'])} | "
        f"parsed_hit={perf['parsed_cache_hits']} | "
        f"parsed_build={perf['parsed_cache_builds']}"
    )
    print("JOBAT - total unique avant matcher :", len(jobs_by_id))
    return list(jobs_by_id.values())



def get_jobat_search_cache_inventory() -> dict:
    """Offline inventory of Jobat search cache freshness."""
    now = time.time()
    ages = []
    files = 0
    blocked = 0
    for path in CACHE_DIR.glob("*.html"):
        files += 1
        try:
            age_h = max(0.0, now - path.stat().st_mtime) / 3600.0
            ages.append(age_h)
            html = path.read_text(encoding="utf-8", errors="ignore")
            if _is_block_page(html):
                blocked += 1
        except Exception:
            continue
    ages.sort()
    return {
        "html_files": files,
        "blocked_cache_files": blocked,
        "fresh_4h": sum(1 for x in ages if x <= 4),
        "fresh_30h": sum(1 for x in ages if x <= 30),
        "usable_stale_72h": sum(1 for x in ages if x <= 72),
        "older_than_72h": sum(1 for x in ages if x > 72),
        "oldest_age_h": round(max(ages), 2) if ages else None,
        "newest_age_h": round(min(ages), 2) if ages else None,
    }

def convert_jobat_job(raw_job: dict) -> JobOffer:
    title = clean_text(raw_job.get("title")) or "Titre inconnu"
    summary = clean_text(raw_job.get("summary"))
    job = JobOffer(
        source="JOBAT",
        external_id=clean_text(raw_job.get("external_id")),
        title=title,
        company=clean_text(raw_job.get("company")) or "Employeur non précisé",
        location=clean_text(raw_job.get("location")) or "Belgique",
        description=summary,
        url=clean_text(raw_job.get("url")),
        date_published=clean_text(raw_job.get("date_published")) or None,
        contract_type=clean_text(raw_job.get("contract_type")) or None,
        language=clean_text(raw_job.get("language")) or None,
    )
    job.collection_channel = "JOBAT"
    job.origin_source = "JOBAT"
    job.search_keywords = list(raw_job.get("search_keywords") or [])
    job.jobat_card_length = len(summary)
    return job


# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1
from sources.unified_discovery import get_source_query_terms
_UD_JOBAT_CORE_TERMS = list(JOBAT_TARGET_SEARCH_TERMS)
JOBAT_TARGET_SEARCH_TERMS = get_source_query_terms(
    "JOBAT",
    _UD_JOBAT_CORE_TERMS,
    rotation_buckets=4,
)
