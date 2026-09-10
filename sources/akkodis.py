"""
JOB HUNTER BELGIUM
AKKODIS BELGIUM - VERSION 1.1

Collecte publique ciblée Akkodis Belgique via le portail carrière TalentSoft officiel.

Stratégie :
- parcourt la vue publique TalentSoft filtrée sur le pays Belgique ;
- pré-filtre les cartes par titre/extrait (Data/BI + Lab/QC/Life Sciences) ;
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
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.scienceatwork import detect_language as detect_body_language
from sources.randstad import dutch_professional_required
from sources.source_metrics import publish_metrics_from_locals


BASE_URL = "https://akka-cand.talent-soft.com"
# Le facet 40 correspond au pays Belgium sur le portail carrière public Akkodis.
LISTING_ROOT = (
    BASE_URL
    + "/job/list-of-jobs.aspx?changefacet=1&facet_JobCountry=40&LCID=2057"
)
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAYS = (1, 2, 4)
DETAIL_DELAY_SECONDS = 0.08
MAX_LISTING_PAGES = 20
MIN_DESCRIPTION_LENGTH = 180

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIST_CACHE_DIR = PROJECT_ROOT / "logs" / "akkodis_listing_cache"
DETAIL_CACHE_DIR = PROJECT_ROOT / "logs" / "akkodis_detail_cache"
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

# TalentSoft utilise plusieurs routes selon la langue / version du portail.
DETAIL_ID_RE = re.compile(r"(?:_|/)(\d{4,8})\.aspx$", re.I)
REF_RE = re.compile(r"\b(20\d{2}-\d{4,6})\b")

TARGET_PATTERNS = (
    '\\bjunior\\s+data\\s+analyst\\b',
    '\\bdata\\s+analyst\\b',
    '\\bdata\\s+engineer\\b',
    '\\bbusiness\\s+(?:data\\s+)?analyst\\b',
    '\\bbi\\s+(?:functional\\s+)?analyst\\b',
    '\\bfunctional\\s+analyst\\b',
    '\\bdata\\s+quality\\b',
    '\\bdata\\s+integrity\\b',
    '\\bdata\\s+steward\\b',
    '\\bmaster\\s+data\\b',
    '\\breporting\\b',
    '\\bpower\\s*bi\\b',
    '\\bqlik\\b',
    '\\bbusiness\\s+intelligence\\b',
    '\\bqc\\s+analyst\\b',
    '\\banalyst\\s+qc\\b',
    '\\bqc\\s+(?:specialist|officer|technician)\\b',
    '\\bquality\\s+control\\s+(?:specialist|analyst|technician|officer)\\b',
    '\\bqa\\s+for\\s+qc\\b',
    '\\bquality\\s+assurance\\s+(?:specialist|officer|associate|coordinator)\\b',
    '\\bqa\\s+(?:specialist|officer|operational|opérationnel|csv|validation)\\b',
    '\\blab(?:oratory)?\\s+(?:analyst|technician)\\b',
    '\\bdevelopment\\s+analyst\\b',
    '\\bbioanalytical\\s+scientist\\b',
    '\\banalytical\\s+scientist\\b',
    '\\braw\\s+material\\s+scientist\\b',
    '\\bformulation\\s+scientist\\b',
    '\\bgmp\\s+compliance\\b',
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

NON_TARGET_TITLE_PATTERNS = (
    r"\b(?:senior|lead|manager|director|head|supervisor)\b",
    r"\bconstruction\b", r"\belectrical\b", r"\bhvac\b",
    r"\bcapex\b", r"\butilities\b", r"\bbuilding\b",
    r"\bautomation\b", r"\bcommissioning\b", r"\bqualification\b",
    r"\bproject\s+engineer\b", r"\bprocess\s+engineer\b",
    r"\bpackaging\s+engineer\b", r"\bmanufacturing\b",
    r"\bproduction\s+engineer\b", r"\bmaintenance\s+engineer\b",
    r"\bsustainability\b", r"\bsupply\s+chain\b",
    r"\bproject\s+manager\b", r"\bprogram\s+manager\b",
    r"\bscheduler\b", r"\bequipment\b", r"\bregulatory\b",
    r"\bclinical\s+trial\b", r"\bmedical\s+device\b",
    r"\bsafety\b", r"\bc&q\b", r"\bcqv\b", r"\burs\b", r"\bpmo\b",
)

STOP_MARKERS = (
    "send this job opening to a friend",
    "envoyer cette offre à un ami",
    "submit spontaneous application",
    "candidature spontanée",
    "save criteria",
    "searches, alerts",
    "akkodis site",
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
    sep = "&" if "?" in LISTING_ROOT else "?"
    return LISTING_ROOT if page <= 1 else f"{LISTING_ROOT}{sep}page={page}"


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


def _detail_external_id(url: str) -> str:
    parsed = urlparse(clean_text(url))
    match = DETAIL_ID_RE.search(parsed.path)
    if match:
        return match.group(1)
    query = parse_qs(parsed.query)
    for key in ("id", "jobid", "offerid"):
        value = clean_text((query.get(key) or [""])[0])
        if value.isdigit():
            return value
    return ""


def _is_detail_url(url: str) -> bool:
    parsed = urlparse(clean_text(url))
    path = parsed.path.lower()
    if not path.endswith(".aspx"):
        return False
    if any(token in path for token in ("liste-offres", "list-of-jobs", "liste-toutes-offres")):
        return False
    return bool(_detail_external_id(url))


def _nearest_card_text(anchor, external_id: str) -> str:
    node = anchor
    best = ""
    for _ in range(9):
        node = getattr(node, "parent", None)
        if node is None or not hasattr(node, "find_all"):
            break
        ids = []
        for a in node.find_all("a", href=True):
            absolute = urljoin(BASE_URL, clean_text(a.get("href")))
            if _is_detail_url(absolute):
                eid = _detail_external_id(absolute)
                if eid:
                    ids.append(eid)
        distinct = set(ids)
        if distinct == {external_id}:
            text = clean_text(node.get_text(" ", strip=True))
            if text and (not best or len(text) < len(best)):
                best = text
        elif len(distinct) > 1:
            break
    return best


def _extract_ref(text: str) -> str:
    match = REF_RE.search(clean_text(text))
    return match.group(1) if match else ""


def _extract_date(text: str) -> str:
    # TalentSoft affiche typiquement la date sous forme 27/01/2026.
    m = re.search(r"\b(\d{2}/\d{2}/20\d{2})\b", clean_text(text))
    return m.group(1) if m else ""


def _extract_contract(text: str) -> str:
    low = _normalize(text)
    candidates = (
        "permanent contract",
        "fixed term contract",
        "temporary contract",
        "cdi",
        "cdd",
        "v.i.e",
        "vie",
    )
    for candidate in candidates:
        if candidate in low:
            return candidate
    return ""


def _extract_location_from_card(text: str) -> str:
    # Les cartes TalentSoft n'ont pas toujours de label : on préfère laisser
    # le détail officiel renseigner le lieu. Cette fonction capture seulement
    # les formes les plus sûres autour de Belgique/Belgium/Bruxelles.
    value = clean_text(text)
    patterns = (
        r"\b(Avenue Jules Bordet[^|]{0,60}Bruxelles)\b",
        r"\b(Noordkustlaan[^|]{0,60}Dilbeek)\b",
        r"\b(Bruxelles|Brussels|Belgium|Belgique|Wavre|Braine[- ]l['’]?Alleud|Liège|Liege)\b",
    )
    for pattern in patterns:
        m = re.search(pattern, value, flags=re.I)
        if m:
            return clean_text(m.group(1))
    return ""


def _is_target_candidate(title: str, card_text: str) -> bool:
    # V1.1 : le préfiltre se base d'abord sur le titre. Le V1.0 utilisait
    # aussi les mentions génériques "Life Sciences" / "pharma" de la carte,
    # ce qui faisait entrer de nombreux postes Engineering/Construction.
    title_norm = _normalize(title)
    if not title_norm:
        return False
    if not any(re.search(pattern, title_norm, flags=re.I) for pattern in TARGET_PATTERNS):
        return False

    qa_specialist = bool(
        re.search(r"\bquality\s+assurance\s+specialist\b", title_norm, flags=re.I)
        or re.search(r"\bqa\s+(?:csv|validation|opérationnel|operational)\b", title_norm, flags=re.I)
    )
    for pattern in NON_TARGET_TITLE_PATTERNS:
        if re.search(pattern, title_norm, flags=re.I):
            if qa_specialist and not re.search(r"\b(?:engineer|manager|lead|supervisor)\b", title_norm, flags=re.I):
                continue
            return False
    return True


def _parse_listing_jobs(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, dict] = {}
    for anchor in soup.find_all("a", href=True):
        href = clean_text(anchor.get("href"))
        if not href:
            continue
        absolute = urljoin(BASE_URL, href)
        if not _is_detail_url(absolute):
            continue
        external_id = _detail_external_id(absolute)
        if not external_id:
            continue
        title = clean_text(anchor.get_text(" ", strip=True))
        # Évite les libellés de boutons / icônes TalentSoft.
        if not title or title.lower() in {
            "add this job opening to selection",
            "send this job opening to a friend",
            "ajouter cette offre à ma sélection",
        }:
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
                "contract_type": "",
                "location": "",
                "akkodis_reference": "",
            },
        )
        if title and len(title) > len(row.get("title") or ""):
            row["title"] = title
        if card_text and len(card_text) > len(row.get("card_text") or ""):
            row["card_text"] = card_text
            row["date_published"] = _extract_date(card_text)
            row["contract_type"] = _extract_contract(card_text)
            row["location"] = _extract_location_from_card(card_text)
            row["akkodis_reference"] = _extract_ref(card_text)
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
        for row in rows:
            all_jobs.setdefault(row["external_id"], row)
            if _is_target_candidate(row.get("title", ""), row.get("card_text", "")):
                candidates.setdefault(row["external_id"], row)

        added_all = len(all_jobs) - before_all
        added_candidates = len(candidates) - before_candidates
        meta["pages"] += 1
        mode = "CACHE" if from_cache else "WEB"
        print(
            f"AKKODIS - page {page:2d}: {len(rows):2d} offre(s) | "
            f"+{added_all:<2d} unique(s) | +{added_candidates:<2d} cible(s) | {mode}"
        )
        if added_all == 0:
            break

    meta["all_links"] = len(all_jobs)
    meta["candidate_links"] = len(candidates)
    return list(candidates.values()), meta


def _detail_cache_path(url: str, external_id: str | None = None) -> Path:
    key = clean_text(external_id) or _hash(url)
    return DETAIL_CACHE_DIR / f"{re.sub(r'[^0-9A-Za-z_-]+', '_', key)}.html"


def _visible_detail_text(soup: BeautifulSoup, title: str) -> str:
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
        if pos > 500:
            cuts.append(pos)
    if cuts:
        text = text[: min(cuts)]
    return clean_text(text)


def _label_value(text: str, labels: tuple[str, ...], max_len: int = 140) -> str:
    source = clean_text(text)
    for label in labels:
        pattern = re.compile(
            rf"\b{re.escape(label)}\b\s*:?[ ]*(.{{1,{max_len}}}?)(?=\s+(?:Date de parution|Publication date|Description du poste|Position description|Métier|Category|Intitulé du poste|Job title|Contrat|Contract|Secteur Industriel|Business Industry|Profil|Profile|Localisation du poste|Position location|Lieu|Location|Candidate criteria|Critères candidat)|$)",
            flags=re.I,
        )
        m = pattern.search(source)
        if m:
            return clean_text(m.group(1))
    return ""




def _extract_labeled_contract(text: str) -> str:
    m = re.search(
        r"\b(?:Contract|Contrat)\b\s*:?[ ]*(Permanent contract|Fixed term contract|Temporary contract|CDI|CDD|V\.?I\.?E|VIE)\b",
        clean_text(text),
        flags=re.I,
    )
    return clean_text(m.group(1)) if m else ""


def _extract_labeled_publication_date(text: str) -> str:
    m = re.search(
        r"\b(?:Publication date|Date de parution)\b\s*:?[ ]*(\d{2}/\d{2}/20\d{2})\b",
        clean_text(text),
        flags=re.I,
    )
    return m.group(1) if m else ""


def _extract_detail_location(text: str) -> str:
    value = clean_text(text)
    # TalentSoft imprime typiquement :
    # Position location Job location Europe, Belgium Location Belgium Candidate criteria
    # ou en FR : Localisation du poste Localisation du poste Europe, Belgique Lieu ...
    patterns = (
        r"\bPosition location\b\s+(?:Job location\s+)?(.{1,160}?)\s+\bLocation\b\s+(.{1,160}?)(?=\s+Candidate criteria|\s+General information|$)",
        r"\bLocalisation du poste\b\s+(?:Localisation du poste\s+)?(.{1,160}?)\s+\bLieu\b\s+(.{1,160}?)(?=\s+Critères candidat|\s+Criteres candidat|\s+Informations générales|\s+Informations generales|$)",
    )
    for pattern in patterns:
        m = re.search(pattern, value, flags=re.I)
        if m:
            specific = clean_text(m.group(2))
            generic = clean_text(m.group(1))
            return specific or generic
    # Fallback prudent : ne capture que la valeur immédiatement avant la prochaine section.
    for label in ("Lieu", "Location"):
        matches = list(re.finditer(rf"\b{label}\b\s*:?[ ]*([^|]{{2,120}}?)(?=\s+(?:Candidate criteria|Critères candidat|Criteres candidat|General information|Informations générales|Informations generales|Publication date|Date de parution)|$)", value, flags=re.I))
        if matches:
            candidate = clean_text(matches[-1].group(1))
            if candidate and candidate.lower() not in {"job", "position"}:
                return candidate
    return ""

def _akkodis_dutch_professional_required(text: str) -> bool:
    low = _normalize(text)
    # "Dutch or French" signifie que le français suffit : ne pas pénaliser ce cas.
    masked = re.sub(r"\bdutch\s+or\s+french\b", "french", low, flags=re.I)
    masked = re.sub(r"\bfrench\s+or\s+dutch\b", "french", masked, flags=re.I)
    masked = re.sub(r"\bnederlands\s+of\s+frans\b", "frans", masked, flags=re.I)
    masked = re.sub(r"\bfrans\s+of\s+nederlands\b", "frans", masked, flags=re.I)
    if dutch_professional_required(masked):
        return True
    low = masked
    extra_patterns = (
        r"\b(?:strong|excellent|good|professional|fluent)\b.{0,70}\b(?:dutch|nederlands)\b.{0,30}\b(?:and|&)\b.{0,30}\benglish\b",
        r"\b(?:dutch|nederlands)\b.{0,30}\b(?:and|&)\b.{0,30}\benglish\b.{0,70}\b(?:required|fluent|proficiency|strong|excellent|good)\b",
        r"\bproficien(?:t|cy)\b.{0,55}\b(?:in\s+)?(?:dutch|nederlands)\b",
        r"\bcommunication skills\b.{0,75}\b(?:both\s+)?(?:dutch|nederlands)\b",
        r"\b(?:oral|written)\b.{0,75}\b(?:dutch|nederlands)\b.{0,45}\benglish\b",
    )
    return any(re.search(pattern, low, flags=re.I) for pattern in extra_patterns)


def _detect_language(text: str) -> str:
    lang = clean_text(detect_body_language(text)).lower()
    return lang if lang in {"fr", "en", "nl"} else "unknown"


def parse_akkodis_detail(
    html: str,
    url: str,
    external_id: str | None = None,
    fallback: dict | None = None,
) -> dict:
    fallback = fallback or {}
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = clean_text(h1.get_text(" ", strip=True)) if h1 else clean_text(fallback.get("title"))
    text = _visible_detail_text(soup, title)

    external_id = clean_text(external_id) or _detail_external_id(url) or _hash(url)
    ref = _extract_ref(text) or clean_text(fallback.get("akkodis_reference"))
    # Si la référence 2026-34885 n'est pas imprimée dans le détail TalentSoft,
    # le numéro final de l'URL reste l'identifiant stable.
    if not ref and external_id:
        ref = external_id

    contract = (
        _extract_labeled_contract(text)
        or clean_text(fallback.get("contract_type"))
        or _extract_contract(text)
    )
    date_published = (
        _extract_labeled_publication_date(text)
        or clean_text(fallback.get("date_published"))
        or _extract_date(text)
    )
    location = (
        _extract_detail_location(text)
        or clean_text(fallback.get("location"))
        or "Belgium"
    )
    industry = _label_value(text, ("Business Industry", "Secteur Industriel"), 100)
    category = _label_value(text, ("Category", "Métier"), 100)
    experience = _label_value(text, ("Level of experience", "Niveau d'expérience"), 100)

    language = _detect_language(text)
    dutch_required = _akkodis_dutch_professional_required(text)

    structured = {
        "external_id": external_id,
        "url": url,
        "title": title,
        "company": "Akkodis / client",
        "location": location,
        "contract_type": contract,
        "date_published": date_published,
        "language": language,
        "dutch_required": dutch_required,
        "akkodis_reference": ref,
        "industry": industry,
        "category": category,
        "experience": experience,
    }

    success = bool(title and len(text) >= MIN_DESCRIPTION_LENGTH)
    return {
        "success": success,
        "matching_text": text,
        "matching_text_length": len(text),
        "structured": structured,
        "from_cache": False,
        "error": None if success else (
            f"Akkodis : fiche incomplète (titre={bool(title)}, description={len(text)} car.)"
        ),
    }


def get_akkodis_job_detail(
    url: str,
    external_id: str | None = None,
    use_cache: bool = True,
    fallback: dict | None = None,
) -> dict:
    cache = _detail_cache_path(url, external_id)
    if use_cache and cache.exists():
        try:
            result = parse_akkodis_detail(
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
            "error": f"Akkodis : {error or 'lecture HTTP impossible'}",
        }
    try:
        cache.write_text(html, encoding="utf-8")
    except Exception:
        pass
    return parse_akkodis_detail(html, url, external_id, fallback=fallback)


def _job_from_detail(detail: dict, fallback: dict) -> JobOffer:
    structured = detail.get("structured") or {}
    job = JobOffer(
        source="AKKODIS",
        external_id=clean_text(structured.get("external_id") or fallback.get("external_id")),
        title=clean_text(structured.get("title") or fallback.get("title") or "Titre inconnu"),
        company=clean_text(structured.get("company") or "Akkodis / client"),
        location=clean_text(structured.get("location") or fallback.get("location") or "Belgium"),
        description=clean_text(detail.get("matching_text")),
        url=clean_text(structured.get("url") or fallback.get("url")),
        date_published=clean_text(structured.get("date_published") or fallback.get("date_published")) or None,
        contract_type=clean_text(structured.get("contract_type") or fallback.get("contract_type")) or None,
        language=clean_text(structured.get("language")) or None,
    )
    job.collection_channel = "AKKODIS"
    job.origin_source = "AKKODIS"
    job.akkodis_reference = clean_text(structured.get("akkodis_reference"))
    job.job_category = clean_text(structured.get("category"))
    job.industry = clean_text(structured.get("industry"))
    job.experience_requirement = clean_text(structured.get("experience"))
    return job


def search_targeted_akkodis_jobs() -> list[JobOffer]:
    print("AKKODIS - collecte ciblée Belgique via portail TalentSoft officiel")
    candidates, meta = collect_listing_candidates(use_cache=True)
    print(
        "AKKODIS - préfiltre : "
        f"{meta.get('all_links', 0)} offre(s) vues sur {meta.get('pages', 0)} page(s), "
        f"{len(candidates)} candidate(s) métier"
    )
    for error in meta.get("errors") or []:
        print(f"AKKODIS - avertissement listing : {error}")
    if not candidates:
        raise RuntimeError("Akkodis : aucun candidat métier détecté.")

    jobs: list[JobOffer] = []
    errors = 0
    rejected_nl = 0
    rejected_dutch = 0
    languages = {"fr": 0, "en": 0, "unknown": 0}

    for index, item in enumerate(candidates, start=1):
        detail = get_akkodis_job_detail(
            item.get("url", ""),
            item.get("external_id"),
            use_cache=True,
            fallback=item,
        )
        title = clean_text((detail.get("structured") or {}).get("title") or item.get("title"))
        if not detail.get("success"):
            errors += 1
            print(f"[{index:03d}/{len(candidates):03d}] ⚠️ DETAIL | {title} | {detail.get('error')}")
            continue

        structured = detail.get("structured") or {}
        language = clean_text(structured.get("language")).lower() or "unknown"
        if language == "nl":
            rejected_nl += 1
            print(f"[{index:03d}/{len(candidates):03d}] ⛔ NL     | {title}")
            continue
        if structured.get("dutch_required"):
            rejected_dutch += 1
            print(
                f"[{index:03d}/{len(candidates):03d}] ⛔ DUTCH  | {title} | "
                "néerlandais professionnel requis"
            )
            continue

        languages[language if language in languages else "unknown"] += 1
        job = _job_from_detail(detail, item)
        jobs.append(job)
        print(
            f"[{index:03d}/{len(candidates):03d}] ✅ {language.upper():<7} | "
            f"{len(job.description):4d} car. | {job.title} | {job.location}"
        )
        time.sleep(DETAIL_DELAY_SECONDS)

    print()
    print("=" * 76)
    print("                    BILAN AKKODIS V1.1")
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
    publish_metrics_from_locals("AKKODIS", locals())
    return jobs


def collect_akkodis_jobs() -> list[JobOffer]:
    return search_targeted_akkodis_jobs()


# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1
from sources.unified_discovery import matches_master_title
_ud_original__is_target_candidate = _is_target_candidate

def _is_target_candidate(title, card_text):
    if _ud_original__is_target_candidate(title, card_text):
        return True
    return matches_master_title(title)
