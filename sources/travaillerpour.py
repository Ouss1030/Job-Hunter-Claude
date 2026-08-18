"""
JOB HUNTER BELGIUM
TRAVAILLERPOUR.BE - VERSION 1

OBJECTIF
========

Collecter toutes les offres actuellement publiées sur :

    https://travaillerpour.be/fr/jobs

Le catalogue est suffisamment petit pour être parcouru
entièrement.

FONCTIONNEMENT
==============

1. requests + BeautifulSoup
2. aucune utilisation de Playwright
3. pagination automatique
4. exclusion de "Jobs favoris"
5. déduplication exacte par identifiant
6. cache HTML par page
7. conversion en JobOffer
8. conservation des métadonnées utiles :
   - langue
   - employeur
   - type de contrat
   - nombre de postes
   - restrictions éventuelles
9. génération automatique d'un fichier TXT de test dans :

       exports/logs/

IMPORTANT
=========

Le détail complet des offres sera traité dans :

    sources/travaillerpour_detail.py

après validation de ce collecteur.
"""


import hashlib
import re
import sys
import time

from datetime import datetime
from pathlib import Path
from urllib.parse import (
    urljoin,
    urlparse,
)

import requests

from bs4 import BeautifulSoup

from database.models import JobOffer


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = (
    "https://travaillerpour.be"
)


LIST_URL = (
    "https://travaillerpour.be/fr/jobs"
)


REQUEST_TIMEOUT = 30


MAX_RETRIES = 4


RETRY_DELAYS = [
    1,
    2,
    4,
    8,
]


DELAY_BETWEEN_PAGES = 0.15


MAX_PAGES = 30


# ============================================================
# DOSSIERS
# ============================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)


CACHE_DIR = (
    PROJECT_ROOT
    / "logs"
    / "travaillerpour_search_cache"
)


CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


LOG_DIR = (
    PROJECT_ROOT
    / "exports"
    / "logs"
)


LOG_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# SESSION
# ============================================================

SESSION = requests.Session()


SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/151.0 Safari/537.36"
        ),

        "Accept": (
            "text/html,"
            "application/xhtml+xml,"
            "application/xml;q=0.9,"
            "*/*;q=0.8"
        ),

        "Accept-Language":
            "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.7",

        "Cache-Control":
            "no-cache",

        "Pragma":
            "no-cache",
    }
)


# ============================================================
# LOGGER TERMINAL + TXT
# ============================================================

class Tee:

    def __init__(
        self,
        *streams
    ):

        self.streams = streams


    def write(
        self,
        data
    ):

        for stream in self.streams:

            try:

                stream.write(
                    data
                )

                stream.flush()

            except Exception:

                pass


    def flush(
        self
    ):

        for stream in self.streams:

            try:

                stream.flush()

            except Exception:

                pass


def start_logging():

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )


    log_path = (
        LOG_DIR
        /
        (
            "travaillerpour_collect_"
            f"{timestamp}.txt"
        )
    )


    log_file = log_path.open(
        "w",
        encoding="utf-8"
    )


    original_stdout = (
        sys.stdout
    )


    original_stderr = (
        sys.stderr
    )


    sys.stdout = Tee(
        original_stdout,
        log_file
    )


    sys.stderr = Tee(
        original_stderr,
        log_file
    )


    return {
        "path":
            log_path,

        "file":
            log_file,

        "stdout":
            original_stdout,

        "stderr":
            original_stderr,
    }


def stop_logging(
    logger
):

    sys.stdout = (
        logger[
            "stdout"
        ]
    )


    sys.stderr = (
        logger[
            "stderr"
        ]
    )


    try:

        logger[
            "file"
        ].close()

    except Exception:

        pass


# ============================================================
# TEXTE
# ============================================================

def clean_text(
    value
):

    if value is None:

        return ""


    value = str(
        value
    )


    value = value.replace(
        "\xa0",
        " "
    )


    value = value.replace(
        "\u200b",
        ""
    )


    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()


    return value


# ============================================================
# URL LISTE
# ============================================================

def build_listing_url(
    page_number
):

    return (
        LIST_URL
        +
        f"?page={page_number}"
        +
        "&sort_bef_combine=publicationdate_DESC"
        +
        "&sort_by=publicationdate"
        +
        "&sort_order=DESC"
    )


# ============================================================
# CACHE
# ============================================================

def cache_path(
    page_number
):

    return (
        CACHE_DIR
        /
        f"page_{page_number:03d}.html"
    )


def save_page_cache(
    page_number,
    html_content
):

    path = cache_path(
        page_number
    )


    try:

        path.write_text(
            html_content,
            encoding="utf-8"
        )


        return True


    except Exception:

        return False


def load_page_cache(
    page_number
):

    path = cache_path(
        page_number
    )


    if not path.exists():

        return None


    try:

        return path.read_text(
            encoding="utf-8"
        )


    except Exception:

        return None


# ============================================================
# HTTP
# ============================================================

def request_listing_page(
    page_number
):

    url = build_listing_url(
        page_number
    )


    last_error = None


    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            response = SESSION.get(
                url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True
            )


            response.raise_for_status()


            html_content = (
                response.text
            )


            if not html_content:

                raise ValueError(
                    "Page Travaillerpour.be vide."
                )


            save_page_cache(
                page_number,
                html_content
            )


            return {
                "success":
                    True,

                "html":
                    html_content,

                "url":
                    response.url,

                "from_cache":
                    False,

                "error":
                    None,
            }


        except (
            requests.RequestException,
            ValueError,
        ) as error:

            last_error = error


            if attempt >= MAX_RETRIES:

                break


            delay = RETRY_DELAYS[
                min(
                    attempt - 1,
                    len(
                        RETRY_DELAYS
                    ) - 1
                )
            ]


            print(
                f"    ⚠️ Page {page_number} : "
                f"tentative "
                f"{attempt}/{MAX_RETRIES} échouée"
            )


            print(
                f"    ↳ nouvelle tentative "
                f"dans {delay}s"
            )


            time.sleep(
                delay
            )


    # ========================================================
    # FALLBACK CACHE
    # ========================================================

    cached = load_page_cache(
        page_number
    )


    if cached:

        return {
            "success":
                True,

            "html":
                cached,

            "url":
                url,

            "from_cache":
                True,

            "error":
                None,
        }


    return {
        "success":
            False,

        "html":
            "",

        "url":
            url,

        "from_cache":
            False,

        "error":
            str(
                last_error
            ),
    }


# ============================================================
# URL OFFRE
# ============================================================

def is_job_detail_url(
    url
):

    if not url:

        return False


    try:

        parsed = urlparse(
            url
        )


        path = (
            parsed.path
            .rstrip("/")
        )


    except Exception:

        return False


    if not path.startswith(
        "/fr/jobs/"
    ):

        return False


    # ========================================================
    # FAUX POSITIFS
    # ========================================================

    excluded_paths = {

        "/fr/jobs/favorites",
    }


    if path in excluded_paths:

        return False


    parts = [
        part
        for part
        in path.split("/")
        if part
    ]


    # fr / jobs / slug
    if len(
        parts
    ) != 3:

        return False


    slug = parts[-1]


    if slug.lower() in {
        "favorites",
        "favourites",
    }:

        return False


    return True


# ============================================================
# IDENTIFIANT
# ============================================================

def extract_external_id(
    url
):

    parsed = urlparse(
        url
    )


    slug = (
        parsed.path
        .rstrip("/")
        .split("/")[-1]
    )


    # Exemples :
    #
    # cfg26044-expert-scientifique-mfx
    # afg26147-business-analyste-mfx
    # ang26236-kwaliteitsbeheerder-mvx
    # xfc26104-gestionnaire...
    #
    # Identifiant :
    # cfg26044
    # afg26147
    # ...

    match = re.match(
        r"^([a-z]{2,4}\d{5})-",
        slug,
        flags=re.IGNORECASE
    )


    if match:

        return (
            match.group(
                1
            )
            .upper()
        )


    digest = hashlib.sha1(
        url.encode(
            "utf-8"
        )
    ).hexdigest()[:16]


    return (
        f"URL_{digest}"
    )


# ============================================================
# LIGNES D'UNE CARTE
# ============================================================

def get_card_lines(
    article
):

    raw_text = article.get_text(
        "\n",
        strip=True
    )


    lines = []


    previous = None


    for raw_line in (
        raw_text.splitlines()
    ):

        line = clean_text(
            raw_line
        )


        if not line:

            continue


        if line == previous:

            continue


        previous = line


        lines.append(
            line
        )


    return lines


# ============================================================
# LANGUE
# ============================================================

def extract_language(
    card_text
):

    normalized = (
        card_text.lower()
    )


    patterns = {

        "fr":
            "Français",

        "nl":
            "Néerlandais",

        "de":
            "Allemand",
    }


    for code, canonical in (
        patterns.items()
    ):

        if re.search(
            rf"\blangue\s+{code}\b",
            normalized,
            flags=re.IGNORECASE
        ):

            return canonical


    return None


# ============================================================
# NOMBRE DE POSTES
# ============================================================

def extract_positions_count(
    card_text
):

    match = re.search(
        r"\b(\d+)\s+poste(?:s)?\b",
        card_text,
        flags=re.IGNORECASE
    )


    if not match:

        return None


    try:

        return int(
            match.group(
                1
            )
        )


    except Exception:

        return None


# ============================================================
# TYPE DE CONTRAT
# ============================================================

def extract_contract_type(
    card_text
):

    contract_terms = [

        "Mission temporaire",

        "Contractuel",

        "Statutaire",

        "Pas applicable",
    ]


    normalized = (
        card_text.lower()
    )


    for term in contract_terms:

        if term.lower() in normalized:

            return term


    return None


# ============================================================
# RESTRICTION
# ============================================================

def extract_restriction(
    card_text
):

    restrictions = []


    normalized = (
        card_text.lower()
    )


    patterns = [

        (
            "Réservé aux fonctionnaires",
            [
                "réservé aux fonctionnaires",
                "reserve aux fonctionnaires",
            ],
        ),

        (
            "Uniquement pour -26 ans",
            [
                "uniquement pour -26 ans",
                "uniquement pour les -26 ans",
            ],
        ),
    ]


    for canonical, aliases in patterns:

        for alias in aliases:

            if alias in normalized:

                restrictions.append(
                    canonical
                )

                break


    if not restrictions:

        return None


    return ", ".join(
        restrictions
    )


# ============================================================
# STATUT LISTE
# ============================================================

def extract_listing_status(
    card_text
):

    normalized = (
        card_text.lower()
    )


    statuses = []


    if "nouveau" in normalized:

        statuses.append(
            "Nouveau"
        )


    if "dernière chance" in normalized:

        statuses.append(
            "Dernière chance"
        )


    if "derniere chance" in normalized:

        if (
            "Dernière chance"
            not in statuses
        ):

            statuses.append(
                "Dernière chance"
            )


    if not statuses:

        return None


    return ", ".join(
        statuses
    )


# ============================================================
# EMPLOYEUR
# ============================================================

def extract_company(
    lines,
    title
):

    # ========================================================
    # APPROCHE PRINCIPALE
    #
    # La structure observée est généralement :
    #
    # Titre
    # 1 poste
    # EMPLOYEUR
    # Statutaire / Contractuel
    # ========================================================

    position_index = None


    for index, line in enumerate(
        lines
    ):

        if re.fullmatch(
            r"\d+\s+poste(?:s)?",
            line,
            flags=re.IGNORECASE
        ):

            position_index = index

            break


    if position_index is not None:

        for index in range(
            position_index + 1,
            min(
                len(
                    lines
                ),
                position_index + 6
            )
        ):

            candidate = clean_text(
                lines[
                    index
                ]
            )


            if not candidate:

                continue


            normalized = (
                candidate.lower()
            )


            # =================================================
            # BRUIT / MÉTADONNÉES
            # =================================================

            if normalized in {
                "statutaire",
                "contractuel",
                "mission temporaire",
                "love this job",
                "nouveau",
                "dernière chance",
                "derniere chance",
            }:

                continue


            if normalized.startswith(
                "réservé aux"
            ):

                continue


            if normalized.startswith(
                "reserve aux"
            ):

                continue


            if normalized.startswith(
                "uniquement pour"
            ):

                continue


            if normalized.startswith(
                "langue "
            ):

                continue


            if candidate == title:

                continue


            return candidate


    return (
        "Employeur non précisé"
    )


# ============================================================
# TOTAL ANNONCÉ
# ============================================================

def extract_advertised_total(
    soup
):

    main = (
        soup.find(
            "main"
        )
        or
        soup
    )


    text = clean_text(
        main.get_text(
            " ",
            strip=True
        )
    )


    match = re.search(
        r"\b(\d+)\s+offres?\s+d['’]emploi\b",
        text,
        flags=re.IGNORECASE
    )


    if not match:

        return None


    try:

        return int(
            match.group(
                1
            )
        )


    except Exception:

        return None


# ============================================================
# PARSING D'UNE CARTE
# ============================================================

def parse_job_article(
    article
):

    job_link = None


    for link in article.select(
        "a[href]"
    ):

        href = clean_text(
            link.get(
                "href"
            )
        )


        if not href:

            continue


        absolute_url = urljoin(
            BASE_URL,
            href
        )


        if is_job_detail_url(
            absolute_url
        ):

            job_link = link

            break


    if job_link is None:

        return None


    href = clean_text(
        job_link.get(
            "href"
        )
    )


    url = urljoin(
        BASE_URL,
        href
    )


    title = clean_text(
        job_link.get_text(
            " ",
            strip=True
        )
    )


    if not title:

        return None


    external_id = (
        extract_external_id(
            url
        )
    )


    lines = get_card_lines(
        article
    )


    card_text = " ".join(
        lines
    )


    company = (
        extract_company(
            lines,
            title
        )
    )


    language = (
        extract_language(
            card_text
        )
    )


    positions_count = (
        extract_positions_count(
            card_text
        )
    )


    contract_type = (
        extract_contract_type(
            card_text
        )
    )


    restriction = (
        extract_restriction(
            card_text
        )
    )


    listing_status = (
        extract_listing_status(
            card_text
        )
    )


    return {

        "external_id":
            external_id,

        "title":
            title,

        "company":
            company,

        "location":
            "Belgique",

        "description":
            card_text,

        "url":
            url,

        "language":
            language,

        "positions_count":
            positions_count,

        "contract_type":
            contract_type,

        "restriction":
            restriction,

        "listing_status":
            listing_status,

        "collection_channel":
            "TRAVAILLERPOUR",

        "origin_source":
            "TRAVAILLERPOUR",
    }


# ============================================================
# PARSING PAGE
# ============================================================

def parse_listing_page(
    html_content
):

    soup = BeautifulSoup(
        html_content,
        "html.parser"
    )


    advertised_total = (
        extract_advertised_total(
            soup
        )
    )


    jobs = {}


    # ========================================================
    # LE SITE UTILISE <article> POUR LES CARTES
    # ========================================================

    for article in soup.select(
        "article"
    ):

        raw_job = parse_job_article(
            article
        )


        if raw_job is None:

            continue


        external_id = (
            raw_job[
                "external_id"
            ]
        )


        jobs[
            external_id
        ] = raw_job


    return {

        "advertised_total":
            advertised_total,

        "jobs":
            list(
                jobs.values()
            ),
    }


# ============================================================
# COLLECTE COMPLÈTE
# ============================================================

def collect_travaillerpour_jobs():

    print()

    print(
        "=" * 76
    )

    print(
        "          RECHERCHE TRAVAILLERPOUR.BE V1"
    )

    print(
        "=" * 76
    )

    print()


    unique_jobs = {}


    advertised_total = None


    pages_processed = 0


    for page_number in range(
        0,
        MAX_PAGES
    ):

        result = request_listing_page(
            page_number
        )


        if not result[
            "success"
        ]:

            print(
                f"[page {page_number:>2}] "
                f"❌ erreur : "
                f"{result['error']}"
            )

            break


        parsed = parse_listing_page(
            result[
                "html"
            ]
        )


        if (
            advertised_total
            is None
            and
            parsed[
                "advertised_total"
            ]
            is not None
        ):

            advertised_total = (
                parsed[
                    "advertised_total"
                ]
            )


        page_jobs = (
            parsed[
                "jobs"
            ]
        )


        # ====================================================
        # FIN DU CATALOGUE
        # ====================================================

        if not page_jobs:

            print(
                f"[page {page_number:>2}] "
                "aucune offre → fin"
            )

            break


        new_count = 0


        for raw_job in page_jobs:

            external_id = (
                raw_job[
                    "external_id"
                ]
            )


            if (
                external_id
                in
                unique_jobs
            ):

                continue


            unique_jobs[
                external_id
            ] = raw_job


            new_count += 1


        pages_processed += 1


        source_label = (
            "CACHE"
            if result[
                "from_cache"
            ]
            else
            "WEB"
        )


        print(
            f"[page {page_number:>2}] "
            f"{source_label:<5} | "
            f"{len(page_jobs):>3} offre(s) | "
            f"{new_count:>3} nouvelle(s) | "
            f"total {len(unique_jobs)}"
        )


        # ====================================================
        # SI LA PAGE EST IDENTIQUE À UNE PAGE PRÉCÉDENTE
        # ====================================================

        if new_count == 0:

            print(
                "    ↳ aucune nouvelle référence "
                "→ fin de pagination"
            )

            break


        # ====================================================
        # SI LE TOTAL OFFICIEL EST ATTEINT
        # ====================================================

        if (
            advertised_total is not None
            and
            len(
                unique_jobs
            )
            >=
            advertised_total
        ):

            print()

            print(
                "Total annoncé atteint :",
                advertised_total
            )

            break


        time.sleep(
            DELAY_BETWEEN_PAGES
        )


    jobs = list(
        unique_jobs.values()
    )


    print()

    print(
        "=" * 76
    )

    print(
        "             BILAN TRAVAILLERPOUR.BE V1"
    )

    print(
        "=" * 76
    )


    print(
        "Pages parcourues :",
        pages_processed
    )


    print(
        "Total annoncé    :",
        advertised_total
    )


    print(
        "Offres uniques   :",
        len(
            jobs
        )
    )


    # ========================================================
    # LANGUES
    # ========================================================

    language_counts = {}


    for job in jobs:

        language = (
            job.get(
                "language"
            )
            or
            "Non précisé"
        )


        language_counts[
            language
        ] = (
            language_counts.get(
                language,
                0
            )
            +
            1
        )


    print()

    print(
        "Répartition par langue :"
    )


    for language, count in sorted(
        language_counts.items(),
        key=lambda item: (
            -item[1],
            item[0]
        )
    ):

        print(
            f"  {language:<15} "
            f"{count}"
        )


    # ========================================================
    # CONTRATS
    # ========================================================

    contract_counts = {}


    for job in jobs:

        contract = (
            job.get(
                "contract_type"
            )
            or
            "Non précisé"
        )


        contract_counts[
            contract
        ] = (
            contract_counts.get(
                contract,
                0
            )
            +
            1
        )


    print()

    print(
        "Répartition par contrat :"
    )


    for contract, count in sorted(
        contract_counts.items(),
        key=lambda item: (
            -item[1],
            item[0]
        )
    ):

        print(
            f"  {contract:<25} "
            f"{count}"
        )


    return jobs


# ============================================================
# ALIAS POUR MAIN.PY
# ============================================================

def search_targeted_travaillerpour_jobs():

    # Le catalogue est assez petit :
    # on récupère volontairement toutes les offres.
    return collect_travaillerpour_jobs()


# ============================================================
# CONVERSION JOBOFFER
# ============================================================

def convert_travaillerpour_job(
    raw_job
):

    external_id = clean_text(
        raw_job.get(
            "external_id"
        )
    )


    title = (
        clean_text(
            raw_job.get(
                "title"
            )
        )
        or
        "Titre inconnu"
    )


    company = (
        clean_text(
            raw_job.get(
                "company"
            )
        )
        or
        "Employeur non précisé"
    )


    location = (
        clean_text(
            raw_job.get(
                "location"
            )
        )
        or
        "Belgique"
    )


    language = (
        clean_text(
            raw_job.get(
                "language"
            )
        )
        or
        None
    )


    contract_type = (
        clean_text(
            raw_job.get(
                "contract_type"
            )
        )
        or
        None
    )


    restriction = (
        clean_text(
            raw_job.get(
                "restriction"
            )
        )
        or
        None
    )


    listing_status = (
        clean_text(
            raw_job.get(
                "listing_status"
            )
        )
        or
        None
    )


    positions_count = (
        raw_job.get(
            "positions_count"
        )
    )


    url = clean_text(
        raw_job.get(
            "url"
        )
    )


    raw_description = (
        clean_text(
            raw_job.get(
                "description"
            )
        )
    )


    description_parts = [

        "Canal de collecte : Travaillerpour.be",

        "Origine : Travaillerpour.be",
    ]


    if language:

        description_parts.append(
            f"Langue : {language}"
        )


    if contract_type:

        description_parts.append(
            f"Type de contrat : {contract_type}"
        )


    if positions_count is not None:

        description_parts.append(
            f"Nombre de postes : {positions_count}"
        )


    if restriction:

        description_parts.append(
            f"Restriction : {restriction}"
        )


    if listing_status:

        description_parts.append(
            f"Statut : {listing_status}"
        )


    if raw_description:

        description_parts.append(
            raw_description
        )


    description = "\n".join(
        description_parts
    )


    job = JobOffer(

        source=
            "TRAVAILLERPOUR",

        external_id=
            external_id,

        title=
            title,

        company=
            company,

        location=
            location,

        description=
            description,

        url=
            url,

        date_published=
            None,

        contract_type=
            contract_type,

        language=
            language,

        salary=
            None,
    )


    # ========================================================
    # MÉTADONNÉES DYNAMIQUES
    # ========================================================

    job.collection_channel = (
        "TRAVAILLERPOUR"
    )


    job.origin_source = (
        "TRAVAILLERPOUR"
    )


    job.origin_sources = [
        "TRAVAILLERPOUR"
    ]


    job.positions_count = (
        positions_count
    )


    job.restriction = (
        restriction
    )


    job.listing_status = (
        listing_status
    )


    return job


# ============================================================
# AFFICHAGE TEST
# ============================================================

def print_test_jobs(
    raw_jobs
):

    print()

    print(
        "=" * 76
    )

    print(
        "       OFFRES TRAVAILLERPOUR.BE TROUVÉES"
    )

    print(
        "=" * 76
    )


    for index, raw_job in enumerate(
        raw_jobs,
        start=1
    ):

        job = convert_travaillerpour_job(
            raw_job
        )


        print()

        print(
            "-" * 76
        )


        print(
            "N°          :",
            index
        )


        print(
            "ID          :",
            job.external_id
        )


        print(
            "Titre       :",
            job.title
        )


        print(
            "Entreprise  :",
            job.company
        )


        print(
            "Langue      :",
            job.language
        )


        print(
            "Contrat     :",
            job.contract_type
        )


        print(
            "Nb postes   :",
            getattr(
                job,
                "positions_count",
                None
            )
        )


        print(
            "Restriction :",
            getattr(
                job,
                "restriction",
                None
            )
        )


        print(
            "Statut      :",
            getattr(
                job,
                "listing_status",
                None
            )
        )


        print(
            "URL         :",
            job.url
        )


# ============================================================
# MAIN TEST
# ============================================================

def main():

    logger = start_logging()


    try:

        print()

        print(
            "=" * 76
        )

        print(
            "       TRAVAILLERPOUR.BE - PRODUCTION TEST V1"
        )

        print(
            "=" * 76
        )


        print()

        print(
            "Début :",
            datetime.now().isoformat(
                timespec="seconds"
            )
        )


        print()

        print(
            "TXT automatique :"
        )


        print(
            logger[
                "path"
            ]
        )


        raw_jobs = (
            collect_travaillerpour_jobs()
        )


        print_test_jobs(
            raw_jobs
        )


        print()

        print(
            "=" * 76
        )

        print(
            "TEST TERMINÉ"
        )

        print(
            "=" * 76
        )


        print()

        print(
            "Fichier résultat :"
        )


        print(
            logger[
                "path"
            ]
        )


    finally:

        path = (
            logger[
                "path"
            ]
        )


        stop_logging(
            logger
        )


        print()

        print(
            "TXT généré automatiquement :"
        )


        print(
            path
        )


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":

    main()