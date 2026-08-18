"""
JOB HUNTER BELGIUM
TALENT.BRUSSELS - VERSION 1

OBJECTIF
========

Collecter toutes les offres actuellement publiées sur
le portail officiel talent.brussels.

Contrairement à Forem / Actiris :

- le volume est relativement limité ;
- le site possède une pagination HTML côté serveur ;
- nous récupérons donc TOUTES les offres ;
- le Matcher V4.1 décidera ensuite lesquelles
  correspondent au profil.

Cette version :

1. utilise requests + BeautifulSoup ;
2. n'utilise PAS Playwright ;
3. parcourt automatiquement les pages ;
4. récupère les liens d'offres ;
5. déduplique par URL / identifiant ;
6. crée des JobOffer ;
7. conserve le canal et l'origine ;
8. utilise un cache HTML par page.

Le détail complet des offres sera ajouté
dans l'étape suivante.
"""


import hashlib
import re
import time

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
    "https://www.talent.brussels"
)


LIST_URL = (
    "https://www.talent.brussels/"
    "fr/offres-d-emploi"
)


REQUEST_TIMEOUT = 30

MAX_RETRIES = 4


RETRY_DELAYS = [
    1,
    2,
    4,
    8,
]


MAX_PAGES = 50

DELAY_BETWEEN_PAGES = 0.15


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
    / "talent_brussels_search_cache"
)


CACHE_DIR.mkdir(
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
    }
)


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


    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()


    return value


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
# URL DE PAGE
# ============================================================

def build_listing_url(
    page_number
):

    return (
        f"{LIST_URL}"
        f"?page={page_number}"
    )


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
                timeout=REQUEST_TIMEOUT
            )


            response.raise_for_status()


            if not response.text:

                raise ValueError(
                    "Page talent.brussels vide."
                )


            save_page_cache(
                page_number,
                response.text
            )


            return {
                "success":
                    True,

                "html":
                    response.text,

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
                f"tentative {attempt}/{MAX_RETRIES} échouée"
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
# DÉTECTION URL OFFRE
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


    prefix = (
        "/fr/offres-d-emploi/"
    )


    if not path.startswith(
        prefix
    ):

        return False


    # Exclut la racine.
    if path in {
        "/fr/offres-d-emploi",
        "/fr/offres-d-emploi/",
    }:

        return False


    parts = [
        part
        for part
        in path.split("/")
        if part
    ]


    # Exemple :
    #
    # fr
    # offres-d-emploi
    # vivaqua
    # analyste-en-chimie-614318

    if len(
        parts
    ) < 4:

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


    path = (
        parsed.path
        .rstrip("/")
    )


    last_part = (
        path.split("/")[-1]
    )


    # La plupart des URLs talent.brussels
    # terminent par l'identifiant Drupal :
    #
    # ...-614318

    match = re.search(
        r"-(\d{4,})$",
        last_part
    )


    if match:

        return match.group(
            1
        )


    # Fallback robuste.
    digest = hashlib.sha1(
        url.encode(
            "utf-8"
        )
    ).hexdigest()[:16]


    return (
        f"url_{digest}"
    )


# ============================================================
# CONTENEUR DE CARTE
# ============================================================

def find_card_container(
    link
):
    """
    Essaie de trouver le bloc HTML entourant
    l'offre afin de récupérer employeur / deadline.
    """

    current = link


    for _ in range(
        7
    ):

        current = (
            current.parent
            if current
            else None
        )


        if current is None:

            break


        text = clean_text(
            current.get_text(
                " ",
                strip=True
            )
        )


        if (
            30
            <=
            len(
                text
            )
            <=
            1500
        ):

            if clean_text(
                link.get_text(
                    " ",
                    strip=True
                )
            ) in text:

                return current


    return link.parent


# ============================================================
# DEADLINE
# ============================================================

def extract_deadline(
    card_text
):

    if not card_text:

        return None


    patterns = [

        r"Postulez\s+jusqu['’]au\s+([^|]+)",

        r"Postuler\s+jusqu['’]au\s+([^|]+)",

        r"jusqu['’]au\s+"
        r"(\d{1,2}/\d{1,2}/\d{4})",
    ]


    for pattern in patterns:

        match = re.search(
            pattern,
            card_text,
            flags=re.IGNORECASE
        )


        if match:

            value = clean_text(
                match.group(
                    1
                )
            )


            # Évite qu'un bloc HTML trop large
            # avale le texte de l'offre suivante.
            date_match = re.search(
                r"\d{1,2}/\d{1,2}/\d{4}",
                value
            )


            if date_match:

                return date_match.group(
                    0
                )


    return None


# ============================================================
# EMPLOYEUR
# ============================================================

def extract_company_from_card(
    card,
    title
):

    if card is None:

        return None


    # ========================================================
    # IMAGE ALT
    # ========================================================

    for image in card.select(
        "img[alt]"
    ):

        alt = clean_text(
            image.get(
                "alt"
            )
        )


        if (
            alt
            and
            alt.lower()
            not in {
                "image",
                "logo",
            }
            and
            alt.lower()
            not in title.lower()
        ):

            return alt


    # ========================================================
    # TEXTES COURTS
    # ========================================================

    candidates = []


    for element in card.find_all(
        [
            "span",
            "div",
            "p",
        ]
    ):

        text = clean_text(
            element.get_text(
                " ",
                strip=True
            )
        )


        if not text:

            continue


        if text == title:

            continue


        if (
            len(
                text
            )
            >
            100
        ):

            continue


        if re.search(
            r"\d{1,2}/\d{1,2}/\d{4}",
            text
        ):

            continue


        if text.lower().startswith(
            (
                "postulez",
                "postuler",
            )
        ):

            continue


        candidates.append(
            text
        )


    # Ne devine pas agressivement.
    # On préfère None plutôt qu'un faux employeur.

    if candidates:

        # Une valeur répétée dans plusieurs
        # sous-éléments est souvent l'employeur.
        counts = {}


        for value in candidates:

            counts[
                value
            ] = (
                counts.get(
                    value,
                    0
                )
                +
                1
            )


        ranked = sorted(
            counts.items(),
            key=lambda item: (
                item[1],
                -len(
                    item[0]
                )
            ),
            reverse=True
        )


        if ranked:

            best_value = (
                ranked[0][0]
            )


            if (
                2
                <=
                len(
                    best_value
                )
                <=
                80
            ):

                return best_value


    return None


# ============================================================
# PARSING PAGE LISTE
# ============================================================

def parse_listing_page(
    html_content,
    page_number
):

    soup = BeautifulSoup(
        html_content,
        "html.parser"
    )


    jobs = {}


    for link in soup.select(
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


        if not is_job_detail_url(
            absolute_url
        ):

            continue


        title = clean_text(
            link.get_text(
                " ",
                strip=True
            )
        )


        if (
            not title
            or
            len(
                title
            )
            < 3
        ):

            continue


        external_id = (
            extract_external_id(
                absolute_url
            )
        )


        card = (
            find_card_container(
                link
            )
        )


        card_text = (
            clean_text(
                card.get_text(
                    " ",
                    strip=True
                )
            )
            if card
            else
            title
        )


        company = (
            extract_company_from_card(
                card,
                title
            )
        )


        deadline = (
            extract_deadline(
                card_text
            )
        )


        raw_job = {

            "external_id":
                external_id,

            "title":
                title,

            "company":
                company,

            "location":
                "Bruxelles, Belgique",

            "description":
                card_text,

            "url":
                absolute_url,

            "deadline":
                deadline,

            "listing_page":
                page_number,

            "collection_channel":
                "TALENT_BRUSSELS",

            "origin_source":
                "TALENT_BRUSSELS",
        }


        # ====================================================
        # DÉDUP EXACT PAR ID
        # ====================================================

        if (
            external_id
            not in jobs
        ):

            jobs[
                external_id
            ] = raw_job


    return list(
        jobs.values()
    )


# ============================================================
# COLLECTE COMPLÈTE
# ============================================================

def collect_talent_brussels_jobs():

    print()

    print(
        "=" * 76
    )

    print(
        "       RECHERCHE TALENT.BRUSSELS V1"
    )

    print(
        "=" * 76
    )

    print()


    unique_jobs = {}


    consecutive_pages_without_new = (
        0
    )


    for page_number in range(
        0,
        MAX_PAGES
    ):

        result = (
            request_listing_page(
                page_number
            )
        )


        if not result[
            "success"
        ]:

            print(
                f"[page {page_number}] "
                f"❌ erreur : "
                f"{result['error']}"
            )

            break


        page_jobs = (
            parse_listing_page(
                result[
                    "html"
                ],
                page_number
            )
        )


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


        cache_label = (
            "CACHE"
            if result[
                "from_cache"
            ]
            else
            "WEB"
        )


        print(
            f"[page {page_number:>2}] "
            f"{cache_label:<5} | "
            f"{len(page_jobs):>3} offre(s) | "
            f"{new_count:>3} nouvelle(s) | "
            f"total {len(unique_jobs)}"
        )


        # ====================================================
        # FIN PAGINATION
        # ====================================================

        if new_count == 0:

            consecutive_pages_without_new += (
                1
            )


        else:

            consecutive_pages_without_new = (
                0
            )


        # Deux pages consécutives sans rien de nouveau
        # => fin du catalogue.
        if (
            consecutive_pages_without_new
            >= 2
        ):

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
        "          BILAN TALENT.BRUSSELS V1"
    )

    print(
        "=" * 76
    )


    print(
        "Offres uniques :",
        len(
            jobs
        )
    )


    return jobs


# ============================================================
# ALIAS POUR FUTUR MAIN.PY
# ============================================================

def search_targeted_talent_brussels_jobs():

    # talent.brussels possède un catalogue limité.
    # Nous collectons volontairement tout.
    return collect_talent_brussels_jobs()


# ============================================================
# CONVERSION EN JOBOFFER
# ============================================================

def convert_talent_brussels_job(
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
        "Bruxelles, Belgique"
    )


    description = (
        clean_text(
            raw_job.get(
                "description"
            )
        )
    )


    url = clean_text(
        raw_job.get(
            "url"
        )
    )


    deadline = clean_text(
        raw_job.get(
            "deadline"
        )
    )


    # ========================================================
    # DESCRIPTION TECHNIQUE
    # ========================================================

    description_parts = [

        "Canal de collecte : talent.brussels",

        "Origine : talent.brussels",
    ]


    if deadline:

        description_parts.append(
            (
                "Date limite de candidature : "
                f"{deadline}"
            )
        )


    if description:

        description_parts.append(
            description
        )


    final_description = (
        "\n".join(
            description_parts
        )
    )


    # ========================================================
    # JOBOFFER
    # ========================================================

    job = JobOffer(

        source=
            "TALENT_BRUSSELS",

        external_id=
            external_id,

        title=
            title,

        company=
            company,

        location=
            location,

        description=
            final_description,

        url=
            url,

        date_published=
            None,

        contract_type=
            None,

        language=
            None,

        salary=
            None,
    )


    # ========================================================
    # MÉTADONNÉES DYNAMIQUES
    # ========================================================

    job.collection_channel = (
        "TALENT_BRUSSELS"
    )


    job.origin_source = (
        "TALENT_BRUSSELS"
    )


    job.origin_sources = [
        "TALENT_BRUSSELS"
    ]


    job.application_deadline = (
        deadline
        or
        None
    )


    return job


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    raw_jobs = (
        collect_talent_brussels_jobs()
    )


    print()

    print(
        "=" * 76
    )

    print(
        "        OFFRES TALENT.BRUSSELS TROUVÉES"
    )

    print(
        "=" * 76
    )


    for index, raw_job in enumerate(
        raw_jobs,
        start=1
    ):

        job = (
            convert_talent_brussels_job(
                raw_job
            )
        )


        print()

        print(
            "-" * 76
        )


        print(
            "N°         :",
            index
        )


        print(
            "ID         :",
            job.external_id
        )


        print(
            "Titre      :",
            job.title
        )


        print(
            "Entreprise :",
            job.company
        )


        print(
            "Lieu       :",
            job.location
        )


        print(
            "Deadline   :",
            getattr(
                job,
                "application_deadline",
                None
            )
        )


        print(
            "URL        :",
            job.url
        )