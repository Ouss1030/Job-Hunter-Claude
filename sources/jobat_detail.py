"""
JOB HUNTER BELGIUM
JOBAT DETAIL - VERSION 1.2.0

Correctif Anti-Bot Stealth & SPA Validation + Mode Debug :
- Injection d'un script furtif pour masquer navigator.webdriver à Cloudflare ;
- Simulation de mouvements de souris pour valider le défi Turnstile ;
- Validation assouplie (skeletons Next.js) ;
- Mode Debug : Sauvegarde du code HTML si le contenu n'est pas reconnu pour inspection.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from sources.jobat_browser_consent import handle_jobat_cookie_consent, valid_storage_state_path
from matching.texte_parasite import est_texte_parasite


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "logs" / "jobat_detail_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

REQUEST_TIMEOUT = 30
BASE_URL = "https://www.jobat.be"

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
)

BLOCK_STRONG_MARKERS = (
    "sorry, you have been blocked",
    "you have been blocked",
    "why have i been blocked",
    "cloudflare ray id",
    "ray id:",
    "cf-error-details",
    "access denied",
    "attention required",
    "just a moment",
    "checking your browser",
    "verifying you are human",
    "enable cookies",
    "please enable cookies",
)

BLOCK_GENERIC_MARKERS = (
    "security service to protect itself from online attacks",
    "the action you just performed triggered the security solution",
    "cloudflare",
)

DUTCH_BODY_MARKERS = (
    "wij zoeken", "jouw profiel", "jouw functie", "wat bieden wij",
    "wat verwachten we", "vereisten", "werkervaring", "opleiding",
    "voltijds", "deeltijds",
)
FR_BODY_MARKERS = (
    "votre profil", "description de fonction", "nous recherchons",
    "vos responsabilités", "ce que nous offrons", "expérience",
    "formation", "temps plein",
)
EN_BODY_MARKERS = (
    "your profile", "job description", "we are looking",
    "responsibilities", "what we offer", "experience",
    "requirements", "full time",
)

_CACHE_PURGED_ONCE = False

# ============================================================
# PARSED DETAIL CACHE V1
# ============================================================
# Sidecar JSON local uniquement. Une fiche HTML déjà validée peut ensuite
# être relue sans reparsing BeautifulSoup à chaque Daily Run.
PARSED_CACHE_SCHEMA_VERSION = 1
_PARSED_CACHE_STATS = {
    "sidecar_hits": 0,
    "sidecar_misses": 0,
    "sidecar_builds": 0,
    "sidecar_invalidations": 0,
    "html_fallbacks": 0,
}


def _reset_parsed_cache_stats() -> None:
    for key in list(_PARSED_CACHE_STATS):
        _PARSED_CACHE_STATS[key] = 0


def get_jobat_parsed_cache_stats() -> dict:
    return dict(_PARSED_CACHE_STATS)

# ============================================================
# BULK ENRICHMENT CIRCUIT BREAKER V1
# ============================================================
# Cache valide toujours prioritaire. Le circuit est uniquement en mémoire et
# se réinitialise au prochain processus / Daily Run.
_CIRCUIT_OPEN = False
_CIRCUIT_REASON = None
_CIRCUIT_CONSECUTIVE_FAILURES = 0
_CIRCUIT_TIMEOUT_FAILURES = 0
_CIRCUIT_LIVE_ATTEMPTS = 0
_CIRCUIT_LIVE_SUCCESSES = 0
_CIRCUIT_SKIPPED = 0

CIRCUIT_TIMEOUT_THRESHOLD = 3
CIRCUIT_GENERIC_FAILURE_THRESHOLD = 5


def _reset_jobat_detail_circuit_for_tests() -> None:
    global _CIRCUIT_OPEN, _CIRCUIT_REASON
    global _CIRCUIT_CONSECUTIVE_FAILURES, _CIRCUIT_TIMEOUT_FAILURES
    global _CIRCUIT_LIVE_ATTEMPTS, _CIRCUIT_LIVE_SUCCESSES, _CIRCUIT_SKIPPED
    _CIRCUIT_OPEN = False
    _CIRCUIT_REASON = None
    _CIRCUIT_CONSECUTIVE_FAILURES = 0
    _CIRCUIT_TIMEOUT_FAILURES = 0
    _CIRCUIT_LIVE_ATTEMPTS = 0
    _CIRCUIT_LIVE_SUCCESSES = 0
    _CIRCUIT_SKIPPED = 0


def get_jobat_detail_circuit_status() -> dict:
    return {
        "open": bool(_CIRCUIT_OPEN),
        "reason": _CIRCUIT_REASON,
        "consecutive_failures": int(_CIRCUIT_CONSECUTIVE_FAILURES),
        "timeout_failures": int(_CIRCUIT_TIMEOUT_FAILURES),
        "live_attempts": int(_CIRCUIT_LIVE_ATTEMPTS),
        "live_successes": int(_CIRCUIT_LIVE_SUCCESSES),
        "skipped": int(_CIRCUIT_SKIPPED),
        "timeout_threshold": CIRCUIT_TIMEOUT_THRESHOLD,
        "generic_failure_threshold": CIRCUIT_GENERIC_FAILURE_THRESHOLD,
    }


def _open_jobat_detail_circuit(reason: str) -> None:
    global _CIRCUIT_OPEN, _CIRCUIT_REASON
    if _CIRCUIT_OPEN:
        return
    _CIRCUIT_OPEN = True
    _CIRCUIT_REASON = reason
    print(
        "JOBAT DETAIL - CIRCUIT OPEN | "
        f"reason={reason} | live_attempts={_CIRCUIT_LIVE_ATTEMPTS} | "
        "caches valides conserves; appels live suivants ignores pour ce run"
    )


def _record_jobat_live_success() -> None:
    global _CIRCUIT_CONSECUTIVE_FAILURES, _CIRCUIT_TIMEOUT_FAILURES
    global _CIRCUIT_LIVE_SUCCESSES
    _CIRCUIT_LIVE_SUCCESSES += 1
    _CIRCUIT_CONSECUTIVE_FAILURES = 0
    _CIRCUIT_TIMEOUT_FAILURES = 0


def _record_jobat_live_failure(diagnostics) -> None:
    global _CIRCUIT_CONSECUTIVE_FAILURES, _CIRCUIT_TIMEOUT_FAILURES
    text = " | ".join(str(x) for x in (diagnostics or [])).lower()
    _CIRCUIT_CONSECUTIVE_FAILURES += 1

    if "anti-bot" in text or "you have been blocked" in text:
        _open_jobat_detail_circuit("ANTI_BOT")
        return

    timeout_markers = ("timeout", "timed out", "read timed out", "connect timeout")
    if any(marker in text for marker in timeout_markers):
        _CIRCUIT_TIMEOUT_FAILURES += 1
        if _CIRCUIT_TIMEOUT_FAILURES >= CIRCUIT_TIMEOUT_THRESHOLD:
            _open_jobat_detail_circuit("TIMEOUTS")
            return
    else:
        _CIRCUIT_TIMEOUT_FAILURES = 0

    if _CIRCUIT_CONSECUTIVE_FAILURES >= CIRCUIT_GENERIC_FAILURE_THRESHOLD:
        _open_jobat_detail_circuit("CONSECUTIVE_FAILURES")



def clean_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def _html_to_text(value) -> str:
    if not value:
        return ""
    return clean_text(BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True))


def _html_probe_text(html: str, max_chars: int = 30000) -> str:
    if not html:
        return ""
    raw = str(html)[:max_chars]
    try:
        soup = BeautifulSoup(raw, "html.parser")
        title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
        h1 = soup.find("h1")
        h1_text = clean_text(h1.get_text(" ", strip=True) if h1 else "")
        body = clean_text(soup.get_text(" ", strip=True))[:12000]
        return f"{title} {h1_text} {body}".lower()
    except Exception:
        return clean_text(raw).lower()


def is_jobat_block_page(html: str) -> bool:
    if not html:
        return False
    low_html = str(html).lower()
    probe = _html_probe_text(html)

    if any(marker in low_html or marker in probe for marker in BLOCK_STRONG_MARKERS):
        return True

    generic_hits = sum(marker in low_html or marker in probe for marker in BLOCK_GENERIC_MARKERS)
    return generic_hits >= 2


def _walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _jobposting_json(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        for item in _walk_json(payload):
            item_type = item.get("@type")
            if item_type == "JobPosting" or (isinstance(item_type, list) and "JobPosting" in item_type):
                return item
    return {}


def _extract_description(soup: BeautifulSoup, posting: dict) -> str:
    desc = _html_to_text(posting.get("description"))
    if len(desc) >= 100:
        return desc

    next_script = soup.find("script", id="__NEXT_DATA__")
    if next_script and next_script.string:
        try:
            payload = json.loads(next_script.string)
            candidates = []
            for item in _walk_json(payload):
                for k in ("description", "jobDescription", "content", "body", "text", "vacancyDescription"):
                    val = item.get(k)
                    if isinstance(val, str) and len(val) > 80:
                        candidates.append(_html_to_text(val))
            if candidates:
                desc = max(candidates, key=len)
                if len(desc) >= 100:
                    return desc
        except Exception:
            pass

    for selector in [
        "div[class*='description']", "div[class*='vacancy']",
        "div[class*='detail']", "div[class*='content']", "main", "article"
    ]:
        for node in soup.select(selector):
            text = clean_text(node.get_text(" ", strip=True))
            if len(text) >= 150 and not est_texte_parasite(text):
                return text

    # Dernier recours : la page entiere.
    #
    # Cette fonction ne pouvait pas echouer. Elle finissait toujours par
    # rendre soup.get_text() sur tout le document, si bien qu'une extraction
    # ratee ne se distinguait pas d'une reussite — elle rendait le fil
    # d'Ariane et le bloc « offres similaires », qui partaient en base comme
    # description. 253 offres ont ete enregistrees ainsi.
    #
    # Elle peut desormais rendre une chaine vide. Une absence de texte se
    # voit et se corrige ; un faux texte se propage.
    #
    # Mesure du 9 septembre 2026 : les pages de detail Jobat repondent
    # HTTP 403 (anti-bot) a un client HTTP simple. Ce n'est donc pas
    # l'extraction qui a produit ces 253 textes, mais le chemin navigateur,
    # qui atterrissait sur une page de liste. Le blocage Jobat est reel.
    entier = clean_text(soup.get_text(" ", strip=True))
    return "" if est_texte_parasite(entier) else entier


def is_valid_jobat_detail_html(html: str) -> bool:
    if not html or len(html) < 400:
        return False
    if is_jobat_block_page(html):
        return False

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return False

    # 1. Validation via JSON-LD
    posting = _jobposting_json(soup)
    if posting and clean_text(posting.get("title")):
        return True

    # 2. Validation via state React (SPA Skeleton)
    next_script = soup.find("script", id="__NEXT_DATA__")
    if next_script and next_script.string and ("jobDescription" in next_script.string or "vacancyId" in next_script.string):
        return True

    # 3. Validation via DOM classique
    h1 = soup.find("h1")
    title = clean_text(h1.get_text(" ", strip=True) if h1 else "")
    if title:
        return True

    return False


def _cache_path(url: str, external_id: str | None = None) -> Path:
    key = clean_text(external_id) or hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"jobat_{key}.html"


def _parsed_cache_path(html_path: Path) -> Path:
    return html_path.with_suffix(".parsed.json")


def _html_identity(path: Path) -> dict | None:
    try:
        stat = path.stat()
    except Exception:
        return None
    return {
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _load_parsed_sidecar(html_path: Path) -> dict | None:
    sidecar = _parsed_cache_path(html_path)
    if not sidecar.exists():
        _PARSED_CACHE_STATS["sidecar_misses"] += 1
        return None

    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        _PARSED_CACHE_STATS["sidecar_invalidations"] += 1
        try:
            sidecar.unlink(missing_ok=True)
        except Exception:
            pass
        return None

    identity = _html_identity(html_path)
    expected = payload.get("html_identity") if isinstance(payload, dict) else None

    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != PARSED_CACHE_SCHEMA_VERSION
        or not isinstance(expected, dict)
        or identity != expected
        or not isinstance(payload.get("structured"), dict)
    ):
        _PARSED_CACHE_STATS["sidecar_invalidations"] += 1
        try:
            sidecar.unlink(missing_ok=True)
        except Exception:
            pass
        return None

    structured = payload.get("structured") or {}
    if not clean_text(structured.get("description")):
        _PARSED_CACHE_STATS["sidecar_invalidations"] += 1
        try:
            sidecar.unlink(missing_ok=True)
        except Exception:
            pass
        return None

    _PARSED_CACHE_STATS["sidecar_hits"] += 1
    return structured


def _save_parsed_sidecar(html_path: Path, structured: dict) -> None:
    identity = _html_identity(html_path)
    if identity is None or not clean_text((structured or {}).get("description")):
        return

    payload = {
        "schema_version": PARSED_CACHE_SCHEMA_VERSION,
        "html_identity": identity,
        "generated_at_epoch": time.time(),
        "structured": structured,
    }
    try:
        _parsed_cache_path(html_path).write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        _PARSED_CACHE_STATS["sidecar_builds"] += 1
    except Exception:
        pass


def _delete_parsed_sidecar(html_path: Path) -> None:
    try:
        _parsed_cache_path(html_path).unlink(missing_ok=True)
    except Exception:
        pass


def _delete_bad_cache(path: Path, reason: str) -> None:
    _delete_parsed_sidecar(path)
    try:
        path.unlink(missing_ok=True)
        print(f"    🧹 Cache Jobat supprimé ({reason}) : {path.name}")
    except Exception:
        pass


def purge_invalid_jobat_detail_cache() -> dict[str, int]:
    checked = 0
    removed = 0
    sidecar_fast = 0
    sidecar_built = 0

    for path in CACHE_DIR.glob("jobat_*.html"):
        checked += 1

        # Sidecar valide + identité HTML identique = fiche déjà validée lors
        # d'un run précédent. Inutile de relire/reparser 400+ Ko d'HTML.
        structured = _load_parsed_sidecar(path)
        if structured:
            sidecar_fast += 1
            continue

        try:
            html = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            _delete_bad_cache(path, "illisible")
            removed += 1
            continue

        if is_jobat_block_page(html) or not is_valid_jobat_detail_html(html):
            _delete_bad_cache(path, "page invalide/bloquée/skeleton")
            removed += 1
            continue

        structured = parse_jobat_detail_html(html)
        if clean_text(structured.get("description")):
            _save_parsed_sidecar(path, structured)
            sidecar_built += 1

    return {
        "checked": checked,
        "removed": removed,
        "sidecar_fast": sidecar_fast,
        "sidecar_built": sidecar_built,
    }


def _ensure_cache_purged_once() -> None:
    global _CACHE_PURGED_ONCE
    if _CACHE_PURGED_ONCE:
        return
    _CACHE_PURGED_ONCE = True
    summary = purge_invalid_jobat_detail_cache()
    if summary["checked"]:
        print(
            f"JOBAT DETAIL - cache vérifié : {summary['checked']} fichier(s), "
            f"{summary['removed']} supprimé(s), "
            f"{summary.get('sidecar_fast', 0)} sidecar(s) rapides, "
            f"{summary.get('sidecar_built', 0)} sidecar(s) créé(s)."
        )


def _load_cache(url: str, external_id: str | None) -> str | None:
    path = _cache_path(url, external_id)
    if not path.exists():
        return None
    try:
        html = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        _delete_bad_cache(path, "lecture impossible")
        return None

    if not is_valid_jobat_detail_html(html):
        _delete_bad_cache(path, "page invalide/bloquée")
        return None
    return html


def _load_cached_structured(url: str, external_id: str | None) -> dict | None:
    path = _cache_path(url, external_id)
    if not path.exists():
        return None

    structured = _load_parsed_sidecar(path)
    if structured:
        return structured

    _PARSED_CACHE_STATS["html_fallbacks"] += 1
    html = _load_cache(url, external_id)
    if not html:
        return None

    structured = parse_jobat_detail_html(html)
    if not clean_text(structured.get("description")):
        return None

    _save_parsed_sidecar(path, structured)
    return structured


def _save_cache(url: str, external_id: str | None, html: str) -> None:
    if not is_valid_jobat_detail_html(html):
        return
    path = _cache_path(url, external_id)
    try:
        path.write_text(html, encoding="utf-8")
        # Le contenu HTML vient de changer : tout sidecar précédent est obsolète.
        _delete_parsed_sidecar(path)
    except Exception:
        pass


def _requests_html(url: str) -> tuple[str | None, str | None]:
    try:
        response = SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    except Exception as error:
        return None, f"HTTP exception: {error}"

    html = response.text or ""
    if is_jobat_block_page(html):
        return None, f"HTTP {response.status_code}: page anti-bot détectée"
    if response.status_code != 200:
        return None, f"HTTP {response.status_code}"
    if not is_valid_jobat_detail_html(html):
        return None, "HTTP 200 mais contenu non reconnu comme fiche Jobat"
    return html, None


class _EdgeDetailFetcher:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.failed = False

    def start(self) -> bool:
        if self.page is not None:
            return True
        if self.failed:
            return False
        try:
            from playwright.sync_api import sync_playwright

            self.playwright = sync_playwright().start()
            # Standard browser fallback only: no stealth / anti-detection flags.
            self.browser = self.playwright.chromium.launch(
                channel="msedge",
                headless=False,
            )
            self.context = self.browser.new_context(
                storage_state=valid_storage_state_path(),
                locale="fr-BE",
                viewport={'width': 1920, 'height': 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
                ),
            )
            self.page = self.context.new_page()
            self.page.set_default_timeout(45000)
            return True
        except Exception as error:
            print("⚠️ Jobat détail : Edge/Playwright indisponible :", error)
            self.failed = True
            self.close()
            return False

    def fetch(self, url: str) -> tuple[str | None, str | None]:
        if not self.start():
            return None, "Edge/Playwright indisponible"
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
            handle_jobat_cookie_consent(self.page, self.context, verbose=True)

            self.page.wait_for_timeout(3000)
            
            try:
                self.page.wait_for_selector("main, article, div[class*='description'], script[id='__NEXT_DATA__']", timeout=10000)
            except Exception:
                pass
                
            self.page.wait_for_timeout(1000)
            html = self.page.content()
            
            if is_jobat_block_page(html):
                return None, "Edge: page anti-bot détectée"
            
            if not is_valid_jobat_detail_html(html):
                job_id = url.split('/')[-1]
                debug_path = CACHE_DIR / f"debug_{job_id}.html"
                try:
                    debug_path.write_text(html, encoding="utf-8")
                except Exception:
                    pass
                return None, f"Edge: contenu non reconnu (sauvegardé dans {debug_path.name})"
                
            return html, None
        except Exception as error:
            return None, f"Edge exception: {error}"

    def close(self) -> None:
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
        self.playwright = self.browser = self.context = self.page = None

_EDGE = _EdgeDetailFetcher()
atexit.register(_EDGE.close)

def _location_from_json(jobposting: dict) -> str:
    locations = jobposting.get("jobLocation") or []
    if isinstance(locations, dict):
        locations = [locations]
    values = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        address = location.get("address") or {}
        if isinstance(address, str):
            text = clean_text(address)
        else:
            parts = [
                address.get("streetAddress"),
                address.get("postalCode"),
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry"),
            ]
            text = clean_text(", ".join(clean_text(part) for part in parts if clean_text(part)))
        if text and text not in values:
            values.append(text)
    return " | ".join(values)

def _detect_language(text: str) -> str | None:
    low = clean_text(text).lower()
    nl = sum(marker in low for marker in DUTCH_BODY_MARKERS)
    fr = sum(marker in low for marker in FR_BODY_MARKERS)
    en = sum(marker in low for marker in EN_BODY_MARKERS)
    if nl >= 2 and nl > fr and nl > en:
        return "NL"
    if fr >= 2 and fr >= en:
        return "FR"
    if en >= 2:
        return "EN"
    return None

def parse_jobat_detail_html(html: str) -> dict:
    if is_jobat_block_page(html):
        return {
            "title": "", "company": "", "location": "", "contract_type": "",
            "date_published": "", "language": None, "description": "",
        }

    soup = BeautifulSoup(html or "", "html.parser")
    posting = _jobposting_json(soup)

    title = clean_text(posting.get("title"))
    organization = posting.get("hiringOrganization") or {}
    company = clean_text(organization.get("name")) if isinstance(organization, dict) else ""
    location = _location_from_json(posting)
    
    contract = posting.get("employmentType")
    if isinstance(contract, list):
        contract = ", ".join(clean_text(value) for value in contract if clean_text(value))
    contract = clean_text(contract)
    
    date_published = clean_text(posting.get("datePosted"))
    description = _extract_description(soup, posting)

    if not title:
        h1 = soup.find("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "")

    language = clean_text(posting.get("inLanguage")) or _detect_language(description)

    return {
        "title": title,
        "company": company,
        "location": location,
        "contract_type": contract,
        "date_published": date_published,
        "language": language,
        "description": description,
    }

def get_jobat_job_detail(url: str, external_id: str | None = None, use_cache: bool = True, cache_only: bool | None = None) -> dict:
    if not url:
        return {
            "success": False, "matching_text": "", "matching_text_length": 0,
            "structured": {}, "from_cache": False, "error": "URL Jobat vide.",
        }

    _ensure_cache_purged_once()

    if cache_only is None:
        cache_only = (
            str(os.environ.get("JOBHUNTER_JOBAT_MODE") or "CACHE_ONLY")
            .strip()
            .upper()
            != "LIVE"
        )

    if use_cache:
        structured = _load_cached_structured(url, external_id)
        if structured:
            matching_text = clean_text(structured.get("description"))
            if matching_text:
                return {
                    "success": True, "matching_text": matching_text,
                    "matching_text_length": len(matching_text),
                    "structured": structured, "from_cache": True, "error": None,
                }

    if cache_only:
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": {},
            "from_cache": False,
            "cache_only": True,
            "skipped_live": True,
            "error": "Jobat CACHE_ONLY: aucune description locale validée pour cette offre.",
        }

    # Cache miss: if Jobat is already known unavailable in this run,
    # do not repeat HTTP + Edge waits for every remaining offer.
    global _CIRCUIT_LIVE_ATTEMPTS, _CIRCUIT_SKIPPED
    if _CIRCUIT_OPEN:
        _CIRCUIT_SKIPPED += 1
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": {},
            "from_cache": False,
            "circuit_open": True,
            "skipped_live": True,
            "error": f"Jobat live detail circuit open: {_CIRCUIT_REASON}",
        }

    _CIRCUIT_LIVE_ATTEMPTS += 1
    diagnostics = []

    html, http_error = _requests_html(url)
    if http_error:
        diagnostics.append(http_error)

    if not html:
        html, edge_error = _EDGE.fetch(url)
        if edge_error:
            diagnostics.append(edge_error)

    if not html:
        _record_jobat_live_failure(diagnostics)
        return {
            "success": False, "matching_text": "", "matching_text_length": 0,
            "structured": {}, "from_cache": False,
            "blocked": any("anti-bot" in item.lower() for item in diagnostics),
            "error": "Jobat détail inaccessible : " + " | ".join(diagnostics),
        }

    _record_jobat_live_success()
    _save_cache(url, external_id, html)
    structured = parse_jobat_detail_html(html)
    matching_text = clean_text(structured.get("description"))
    if matching_text:
        _save_parsed_sidecar(_cache_path(url, external_id), structured)

    if not matching_text:
        return {
            "success": False, "matching_text": "", "matching_text_length": 0,
            "structured": {}, "from_cache": False,
            "error": "Description Jobat vide après validation de la fiche.",
        }

    return {
        "success": True, "matching_text": matching_text,
        "matching_text_length": len(matching_text),
        "structured": structured, "from_cache": False, "error": None,
    }