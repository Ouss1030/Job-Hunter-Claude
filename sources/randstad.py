"""
JOB HUNTER BELGIUM
RANDSTAD BELGIUM - VERSION 1.0

Collecte ciblée des offres publiques Randstad Belgique (version FR) utiles aux
profils Data/BI et Lab/QC/Pharma. Les pages catégories/métiers sont parcourues,
les fiches détaillées sont récupérées, puis les annonces clairement NL ou
exigeant explicitement un niveau professionnel de néerlandais sont rejetées.

Aucune technique de contournement anti-bot n'est utilisée.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.scienceatwork import detect_language as detect_body_language
from sources.source_metrics import publish_metrics_from_locals


BASE_URL = "https://www.randstad.be"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAYS = (1, 2, 4)
DETAIL_DELAY_SECONDS = 0.10
MAX_PAGES_PER_ROOT = 6
MIN_DESCRIPTION_LENGTH = 120

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIST_CACHE_DIR = PROJECT_ROOT / "logs" / "randstad_listing_cache"
DETAIL_CACHE_DIR = PROJECT_ROOT / "logs" / "randstad_detail_cache"
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
        "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.3",
        "Cache-Control": "no-cache",
    }
)

# Pages publiques relativement ciblées et de faible volume. Les doublons sont
# fusionnés par UUID Randstad.
SEARCH_ROOTS = (
    (
        "DATA_BUSINESS",
        f"{BASE_URL}/fr/candidats/jobs/s-data-business-analyse/",
    ),
    (
        "QUALITY_CONTROL",
        f"{BASE_URL}/fr/candidats/jobs/s-qualite-controle/",
    ),
    (
        "R_AND_D",
        f"{BASE_URL}/fr/candidats/jobs/s-recherche-developpement/",
    ),
    (
        "LABORANTIN",
        f"{BASE_URL}/fr/candidats/jobs/r-laborantin/",
    ),
    (
        "TECHNICIEN_CHIMISTE",
        f"{BASE_URL}/fr/candidats/jobs/s-recherche-developpement/"
        "s2-chimistes-microbiologistes-technologues-des-procedes/"
        "r-technicien-chimiste/",
    ),
    (
        "TECHNICIEN_LABORATOIRE",
        f"{BASE_URL}/fr/candidats/jobs/s-recherche-developpement/"
        "s2-chimistes-microbiologistes-technologues-des-procedes/"
        "r-technicien-de-laboratoire/",
    ),
)

UUID_RE = re.compile(
    r"_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?(?:[?#].*)?$",
    re.I,
)

RANDSTAD_JOB_PATH_RE = re.compile(
    r"^/fr/candidats/jobs/[^/?#]+_[^/?#]+_"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/?$",
    re.I,
)

DUTCH_REQUIRED_PATTERNS = (
    r"\bbilingue\s+(?:fr|français|francais)\s*[/+&-]\s*(?:nl|néerlandais|neerlandais)\b",
    r"\bbilingue\s+(?:nl|néerlandais|neerlandais)\s*[/+&-]\s*(?:fr|français|francais)\b",
    r"\b(?:néerlandais|neerlandais|dutch)\b.{0,55}\b(?:requis|required|obligatoire|indispensable|fluent|courant|excellent)\b",
    r"\b(?:requis|required|obligatoire|indispensable|fluent|courant|excellent)\b.{0,55}\b(?:néerlandais|neerlandais|dutch)\b",
    r"\b(?:ma[iî]trise|maitrise|bonne connaissance|très bonne connaissance|tres bonne connaissance|excellent niveau)\b.{0,55}\b(?:du\s+)?(?:néerlandais|neerlandais)\b",
    r"\b(?:spreekt|schrijft)\b.{0,35}\b(?:vlot|goed|zeer goed)\b.{0,35}\bnederlands\b",
    r"\bgoede\s+kennis\s+van\s+(?:het\s+)?nederlands\b",
    r"\bnederlands\s+(?:is\s+)?(?:vereist|noodzakelijk)\b",
)

OPTIONAL_DUTCH_PATTERNS = (
    r"\b(?:néerlandais|neerlandais|dutch)\b.{0,35}\b(?:atout|plus|souhaité|souhaite|préféré|prefere|nice to have)\b",
    r"\b(?:atout|plus|souhaité|souhaite|préféré|prefere|nice to have)\b.{0,35}\b(?:néerlandais|neerlandais|dutch)\b",
)


FR_LANGUAGE_WORDS = (
    "vous", "votre", "nous", "notre", "tu", "tes", "profil", "poste",
    "offre", "expérience", "experience", "diplôme", "diplome", "compétences",
    "competences", "responsabilités", "responsabilites", "recherchons", "mission",
)
EN_LANGUAGE_WORDS = (
    "you", "your", "we", "our", "role", "position", "experience", "degree",
    "skills", "responsibilities", "requirements", "candidate", "apply",
)
NL_LANGUAGE_WORDS = (
    "je", "jouw", "wij", "onze", "voor", "functie", "ervaring", "opleiding",
    "vereisten", "verantwoordelijkheden", "solliciteren", "nederlands", "klant",
)

def detect_randstad_language(text: str) -> str:
    primary = detect_body_language(text)
    if primary in {"fr", "en", "nl"}:
        return primary
    low = _normalize(text)
    def score(words):
        return sum(len(re.findall(r"\b" + re.escape(word) + r"\b", low, flags=re.I)) for word in words)
    fr = score(FR_LANGUAGE_WORDS)
    en = score(EN_LANGUAGE_WORDS)
    nl = score(NL_LANGUAGE_WORDS)
    if nl >= 4 and nl >= max(fr, en) + 2:
        return "nl"
    if fr >= 3 and fr >= en:
        return "fr"
    if en >= 3:
        return "en"
    return "unknown"

STOP_MARKERS = (
    "fonction",
    "candidats",
    "nos solutions",
    "contactez-nous",
    "téléchargez l'application",
    "recevoir des jobs similaires",
    "accélérez votre recherche",
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


def _listing_url(root_url: str, page: int) -> str:
    if page <= 1:
        return root_url.rstrip("/") + "/"
    return root_url.rstrip("/") + f"/page-{page}/"


def _listing_cache_path(root_key: str, page: int) -> Path:
    return LIST_CACHE_DIR / f"{root_key.lower()}_page_{page}.html"


def _listing_html(root_key: str, root_url: str, page: int, use_cache: bool = True):
    url = _listing_url(root_url, page)
    text, error = _request_html(url)
    cache = _listing_cache_path(root_key, page)
    if text:
        try:
            cache.write_text(text, encoding="utf-8")
        except Exception:
            pass
        return text, False, None
    if use_cache and cache.exists():
        try:
            return cache.read_text(encoding="utf-8"), True, error
        except Exception:
            pass
    return None, False, error


def _parse_job_links(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, dict] = {}
    for anchor in soup.find_all("a", href=True):
        href = clean_text(anchor.get("href"))
        if not href:
            continue
        parsed_path = urlparse(urljoin(BASE_URL, href)).path
        if not RANDSTAD_JOB_PATH_RE.match(parsed_path):
            continue
        url = urljoin(BASE_URL, href)
        match = UUID_RE.search(url)
        if not match:
            continue
        external_id = match.group(1).lower()
        title = clean_text(anchor.get_text(" ", strip=True))
        if not title or title.lower() in {"voir l'offre d'emploi", "postuler"}:
            title = ""
        row = found.setdefault(
            external_id,
            {"external_id": external_id, "url": url, "title": ""},
        )
        if title and len(title) > len(row.get("title") or ""):
            row["title"] = title
    return list(found.values())


def collect_listing_links(use_cache: bool = True) -> tuple[list[dict], dict]:
    unique: dict[str, dict] = {}
    meta = {"pages": 0, "roots": 0, "errors": []}

    for root_key, root_url in SEARCH_ROOTS:
        root_new = 0
        root_pages = 0
        for page in range(1, MAX_PAGES_PER_ROOT + 1):
            html, from_cache, error = _listing_html(root_key, root_url, page, use_cache=use_cache)
            if not html:
                if page == 1:
                    meta["errors"].append(f"{root_key}: {error or 'listing inaccessible'}")
                break
            links = _parse_job_links(html)
            if not links:
                break

            before = len(unique)
            for item in links:
                row = unique.setdefault(item["external_id"], dict(item))
                if item.get("title") and not row.get("title"):
                    row["title"] = item["title"]
                row.setdefault("search_roots", [])
                if root_key not in row["search_roots"]:
                    row["search_roots"].append(root_key)
            added = len(unique) - before
            root_new += added
            root_pages += 1
            meta["pages"] += 1
            mode = "CACHE" if from_cache else "WEB"
            print(
                f"RANDSTAD - {root_key:<22} page {page}: "
                f"{len(links):2d} lien(s) | +{added:<2d} unique(s) | {mode}"
            )

            # Pas de nouvelle offre sur cette page : pagination épuisée ou chevauchement.
            if added == 0 and page > 1:
                break
            # Randstad affiche actuellement 30 cartes/page ; une page plus courte est la fin.
            if len(links) < 25:
                break

        meta["roots"] += 1
        print(f"RANDSTAD - {root_key:<22} : +{root_new} nouvelle(s) sur {root_pages} page(s)")

    return list(unique.values()), meta


def _detail_cache_path(url: str, external_id: str | None = None) -> Path:
    key = clean_text(external_id) or _hash(url)
    safe = re.sub(r"[^0-9A-Za-z_-]+", "_", key)
    return DETAIL_CACHE_DIR / f"{safe}.html"


def _iter_jsonld_nodes(value):
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_jsonld_nodes(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_jsonld_nodes(item)


def _find_jobposting_jsonld(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        for node in _iter_jsonld_nodes(payload):
            kind = node.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if any(str(x).lower() == "jobposting" for x in kinds if x):
                return node
    return {}


def _organization_name(value) -> str:
    if isinstance(value, dict):
        return clean_text(value.get("name"))
    return clean_text(value)


def _location_text(value) -> str:
    values = value if isinstance(value, list) else [value]
    parts = []
    for item in values:
        if not isinstance(item, dict):
            continue
        address = item.get("address") or {}
        if isinstance(address, str):
            txt = clean_text(address)
        elif isinstance(address, dict):
            txt = ", ".join(
                x for x in [
                    clean_text(address.get("addressLocality")),
                    clean_text(address.get("addressRegion")),
                    clean_text(address.get("addressCountry")),
                ] if x
            )
        else:
            txt = ""
        if txt and txt not in parts:
            parts.append(txt)
    return " | ".join(parts)


def _visible_detail_text(soup: BeautifulSoup) -> str:
    main = soup.find("main") or soup.find("article") or soup.body
    if main is None:
        return ""
    text = clean_text(main.get_text("\n", strip=True))
    low = text.lower()

    starts = [
        low.find("offre d'emploi"),
        low.find("principales responsabilités"),
        low.find("responsabilités"),
    ]
    starts = [x for x in starts if x >= 0]
    if starts:
        text = text[min(starts):]
        low = text.lower()

    cuts = []
    for marker in STOP_MARKERS:
        pos = low.find(marker)
        if pos > 500:
            cuts.append(pos)
    if cuts:
        text = text[: min(cuts)]
    return clean_text(text)


def _strip_html(value) -> str:
    if not value:
        return ""
    return clean_text(BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True))


def _extract_reference(text: str) -> str:
    match = re.search(r"\bJN\s*-\s*\d{6}-\d{5,8}\b", text, flags=re.I)
    return clean_text(match.group(0)) if match else ""


def _extract_contract(text: str) -> str:
    low = _normalize(text)
    candidates = (
        "mission d'intérim en vue de fixe",
        "mission d’intérim en vue de fixe",
        "mission d'intérim",
        "mission d’intérim",
        "cdi",
        "cdd",
        "temporaire",
        "permanent",
    )
    for candidate in candidates:
        if candidate in low:
            return candidate
    return ""


def _dutch_is_optional(text: str) -> bool:
    low = _normalize(text)
    return any(re.search(pattern, low, flags=re.I) for pattern in OPTIONAL_DUTCH_PATTERNS)


def dutch_professional_required(text: str) -> bool:
    low = _normalize(text)
    if not low:
        return False
    # Une mention explicitement facultative ne doit pas déclencher le rejet à elle seule.
    optional = _dutch_is_optional(low)
    required = any(re.search(pattern, low, flags=re.I) for pattern in DUTCH_REQUIRED_PATTERNS)
    return bool(required and not optional)


def parse_randstad_detail(html: str, url: str, external_id: str | None = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    posting = _find_jobposting_jsonld(soup)

    visible = _visible_detail_text(soup)
    title = clean_text(posting.get("title")) if posting else ""
    if not title:
        h1 = soup.find("h1")
        title = clean_text(h1.get_text(" ", strip=True)) if h1 else ""

    description_parts = []
    if posting:
        for key in ("description", "responsibilities", "qualifications", "skills"):
            value = _strip_html(posting.get(key))
            if value and value not in description_parts:
                description_parts.append(value)
    jsonld_text = clean_text(" ".join(description_parts))

    # Le JSON-LD est prioritaire ; fallback visible si trop court.
    matching_text = jsonld_text if len(jsonld_text) >= MIN_DESCRIPTION_LENGTH else visible
    if len(matching_text) < MIN_DESCRIPTION_LENGTH and visible:
        matching_text = clean_text(" ".join([jsonld_text, visible]))

    company = _organization_name(posting.get("hiringOrganization")) if posting else ""
    location = _location_text(posting.get("jobLocation")) if posting else ""
    contract = clean_text(posting.get("employmentType")) if posting else ""
    date_published = clean_text(posting.get("datePosted")) if posting else ""
    valid_through = clean_text(posting.get("validThrough")) if posting else ""

    if not contract:
        contract = _extract_contract(visible)

    # Fallback localisation sur le début du main : Randstad place la ville/province sous le H1.
    if not location and visible:
        location_match = re.search(
            r"résumé\s+(.{2,90}?)\s+(?:cdi|cdd|mission d['’]intérim|temps plein|temps partiel)",
            visible,
            flags=re.I,
        )
        if location_match:
            location = clean_text(location_match.group(1))

    external_id = clean_text(external_id)
    if not external_id:
        match = UUID_RE.search(url)
        external_id = match.group(1).lower() if match else _hash(url)

    language = detect_randstad_language(matching_text)
    dutch_required = dutch_professional_required(matching_text)
    reference = _extract_reference(visible or matching_text)

    structured = {
        "external_id": external_id,
        "url": url,
        "title": title,
        "company": company or "Randstad / client",
        "location": location or "Belgique",
        "contract_type": contract,
        "date_published": date_published,
        "valid_through": valid_through,
        "language": language,
        "dutch_required": dutch_required,
        "randstad_reference": reference,
    }

    success = bool(title and len(matching_text) >= MIN_DESCRIPTION_LENGTH)
    return {
        "success": success,
        "matching_text": matching_text,
        "matching_text_length": len(matching_text),
        "structured": structured,
        "from_cache": False,
        "error": None if success else (
            f"Randstad : fiche incomplète (titre={bool(title)}, description={len(matching_text)} car.)"
        ),
    }


def get_randstad_job_detail(
    url: str,
    external_id: str | None = None,
    use_cache: bool = True,
) -> dict:
    cache = _detail_cache_path(url, external_id)
    if use_cache and cache.exists():
        try:
            result = parse_randstad_detail(cache.read_text(encoding="utf-8"), url, external_id)
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
            "error": f"Randstad : {error or 'lecture HTTP impossible'}",
        }
    try:
        cache.write_text(html, encoding="utf-8")
    except Exception:
        pass
    return parse_randstad_detail(html, url, external_id)


def _job_from_detail(detail: dict, fallback: dict) -> JobOffer:
    structured = detail.get("structured") or {}
    description = clean_text(detail.get("matching_text"))
    job = JobOffer(
        source="RANDSTAD",
        external_id=clean_text(structured.get("external_id") or fallback.get("external_id")),
        title=clean_text(structured.get("title") or fallback.get("title") or "Titre inconnu"),
        company=clean_text(structured.get("company") or "Randstad / client"),
        location=clean_text(structured.get("location") or "Belgique"),
        description=description,
        url=clean_text(structured.get("url") or fallback.get("url")),
        date_published=clean_text(structured.get("date_published")) or None,
        contract_type=clean_text(structured.get("contract_type")) or None,
        language=clean_text(structured.get("language")) or None,
    )
    job.collection_channel = "RANDSTAD"
    job.origin_source = "RANDSTAD"
    job.detail_enrichment_attempted = True
    job.detail_enrichment_success = True
    job.detail_matching_text = description
    job.detail_matching_text_length = len(description)
    job.randstad_reference = structured.get("randstad_reference")
    job.valid_through = structured.get("valid_through")
    job.search_roots = fallback.get("search_roots") or []
    return job



_NOISE_TITLE_PATTERNS = (
    r"\bconseiller(?:e)?\s+en\s+pr[eé]vention\b",
    r"\bhse\b",
    r"\bhealth\s*,?\s*safety\b",
    r"\bsafety\s+(?:manager|officer|advisor)\b",
    r"\bnettoyeur\s+industriel\b",
    r"\bindustrial\s+cleaner\b",
)

def _is_obvious_noise_title(title: str) -> bool:
    value = clean_text(title)
    return bool(value) and any(
        re.search(pattern, value, flags=re.I)
        for pattern in _NOISE_TITLE_PATTERNS
    )

def search_targeted_randstad_jobs() -> list[JobOffer]:
    print("RANDSTAD - collecte ciblée FR Belgique")
    links, meta = collect_listing_links(use_cache=True)
    print(
        f"RANDSTAD - liens uniques détectés : {len(links)} "
        f"sur {meta.get('roots', 0)} racine(s) / {meta.get('pages', 0)} page(s)"
    )
    for error in meta.get("errors") or []:
        print(f"RANDSTAD - avertissement listing : {error}")
    if not links:
        raise RuntimeError("Randstad : aucun lien d'offre ciblée détecté.")

    jobs: list[JobOffer] = []
    errors = 0
    rejected_nl = 0
    rejected_dutch = 0
    languages = {"fr": 0, "en": 0, "unknown": 0}

    for index, item in enumerate(links, start=1):
        detail = get_randstad_job_detail(
            url=item["url"],
            external_id=item["external_id"],
            use_cache=True,
        )
        structured = detail.get("structured") or {}
        title = clean_text(structured.get("title") or item.get("title") or "Titre inconnu")

        if not detail.get("success"):
            errors += 1
            print(
                f"[{index:03d}/{len(links):03d}] ❌ DETAIL | {title} | "
                f"{clean_text(detail.get('error'))}"
            )
            continue

        language = clean_text(structured.get("language") or "unknown").lower()
        if language == "nl":
            rejected_nl += 1
            print(f"[{index:03d}/{len(links):03d}] ⛔ NL     | {title}")
            continue

        if bool(structured.get("dutch_required")):
            rejected_dutch += 1
            print(f"[{index:03d}/{len(links):03d}] ⛔ DUTCH  | {title} | néerlandais professionnel requis")
            continue

        if language not in languages:
            language = "unknown"
        languages[language] += 1
        job = _job_from_detail(detail, item)
        jobs.append(job)
        lang_label = {"fr": "FR", "en": "EN", "unknown": "?"}.get(language, "?")
        print(
            f"[{index:03d}/{len(links):03d}] ✅ {lang_label:<2} | "
            f"{len(job.description):4d} car. | {job.title} | {job.location}"
        )
        time.sleep(DETAIL_DELAY_SECONDS)

    print()
    print("=" * 76)
    print("                    BILAN RANDSTAD V1.0")
    print("=" * 76)
    print(f"Fiches ciblées détectées          : {len(links)}")
    print(f"Conservées FR/EN/ambiguës         : {len(jobs)}")
    print(f"  Français                        : {languages['fr']}")
    print(f"  Anglais                         : {languages['en']}")
    print(f"  Langue ambiguë                  : {languages['unknown']}")
    print(f"Rejetées - fiche clairement NL    : {rejected_nl}")
    print(f"Rejetées - néerlandais requis     : {rejected_dutch}")
    print(f"Échecs détail                     : {errors}")
    # V3.8 STEP 9.7.1 - conservative returned-job noise guard
    _before_noise_guard = len(jobs)
    jobs = [job for job in jobs if not _is_obvious_noise_title(getattr(job, "title", ""))]
    _noise_guard_rejected = _before_noise_guard - len(jobs)
    if _noise_guard_rejected:
        print(f"Source noise guard - rejet évident : {_noise_guard_rejected}")
    publish_metrics_from_locals("RANDSTAD", locals())
    return jobs


def collect_randstad_jobs() -> list[JobOffer]:
    return search_targeted_randstad_jobs()
