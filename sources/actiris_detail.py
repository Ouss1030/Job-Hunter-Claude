"""
JOB HUNTER BELGIUM
ACTIRIS DETAIL - VERSION 1.1 PRODUCTION

AMÉLIORATIONS V1.1
==================

- requests + BeautifulSoup uniquement
- support DirectOnline / Hrxml / Select
- correction des champs Actiris séparés sur plusieurs lignes :
      Lieu :
      1000 - Bruxelles

- titre récupéré depuis la balise <title>
- nettoyage plus strict du bruit Actiris
- suppression de la partie candidature / contacts
- meilleure extraction :
    titre
    lieu
    régime
    contrat
    famille métier
    expérience
    permis
    employeur
    langues
    description
    profil
    conditions d'accès
    avantages

- cache V2 séparé afin de ne PAS réutiliser
  les anciens caches contenant les champs mal parsés.
"""


import json
import re
import time

from datetime import datetime
from pathlib import Path

import requests

from bs4 import BeautifulSoup


# ============================================================
# VERSION PARSER
# ============================================================

PARSER_VERSION = "1.1"


# ============================================================
# CONFIGURATION
# ============================================================

DETAIL_BASE_URL = (
    "https://www.actiris.brussels/"
    "fr/citoyens/detail-offre-d-emploi/"
)


SEARCH_REFERER = (
    "https://www.actiris.brussels/"
    "fr/citoyens/offres-d-emploi/"
)


REQUEST_TIMEOUT = 30

MAX_RETRIES = 4


RETRY_DELAYS = [
    1,
    2,
    4,
    8,
]


# ============================================================
# DOSSIERS
# ============================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)


# IMPORTANT :
# nouveau dossier pour ne pas charger
# les anciens caches produits par V1.

CACHE_DIR = (
    PROJECT_ROOT
    / "logs"
    / "actiris_detail_cache_v2"
)


CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# SESSION HTTP
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

        "Referer":
            SEARCH_REFERER,
    }
)


# ============================================================
# MARQUEURS
# ============================================================

JOB_START_MARKERS = [
    "OFFRES D'EMPLOI",
    "OFFRES D’EMPLOI",
    "VACATURES",
]


PAGE_END_MARKERS = [
    "LIENS UTILES",
    "NUTTIGE LINKS",
    "NEWSLETTER",
    "SOCIAL MEDIA",
]


APPLICATION_MARKERS = [
    "Comment postuler ?",
    "Comment postuler?",
    "Hoe solliciteren?",
    "How to apply?",
    "APPLICATION",
]


SECTION_MARKERS = [
    "Description de l'entreprise",
    "Description de la fonction",
    "Profil",
    "Conditions d'accès",
    "Diplôme",
    "Compétences linguistiques",
    "Avantages du poste",
    "Informations supplémentaires",
    "Informations pratiques",
    "Comment postuler ?",
    "Comment postuler?",
    "APPLICATION",
]


NOISE_PREFIXES = [
    "Envie d'en apprendre davantage sur ce métier",
    "Cette offre a été rédigée par l'employeur",
    "Attention, un employeur ne peut pas",
    "Si vous avez une remarque sur cette offre",
    "Panorama des métiers",
    "En savoir plus",
    "Retour à la liste",
]


SEPARATOR_VALUES = {
    "",
    "|",
    "-",
    "–",
    "—",
    ":",
    ";",
    ".",
}


# ============================================================
# OUTILS TEXTE
# ============================================================

def clean_text(value):

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


def normalize_label(value):

    value = clean_text(
        value
    ).lower()

    value = (
        value
        .replace("’", "'")
        .replace(" :", ":")
    )

    return value


def is_separator_line(
    value
):

    value = clean_text(
        value
    )

    return (
        value
        in SEPARATOR_VALUES
    )


# ============================================================
# URL
# ============================================================

def build_detail_url(
    reference,
    offer_type=None
):

    reference = clean_text(
        reference
    )

    offer_type = clean_text(
        offer_type
    )


    url = (
        DETAIL_BASE_URL
        +
        f"?reference={reference}"
    )


    if offer_type:

        url += (
            f"&type={offer_type}"
        )


    return url


# ============================================================
# CACHE
# ============================================================

def cache_path(
    reference,
    offer_type=None
):

    safe_reference = re.sub(
        r"[^0-9A-Za-z_-]+",
        "_",
        clean_text(
            reference
        )
    )


    safe_type = re.sub(
        r"[^0-9A-Za-z_-]+",
        "_",
        clean_text(
            offer_type
        )
        or
        "unknown"
    )


    return (
        CACHE_DIR
        /
        f"{safe_reference}_{safe_type}.json"
    )


def load_cache(
    reference,
    offer_type=None
):

    path = cache_path(
        reference,
        offer_type
    )


    if not path.exists():

        return None


    try:

        with path.open(
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(
                file
            )


        if not isinstance(
            data,
            dict
        ):

            return None


        if (
            data.get(
                "parser_version"
            )
            != PARSER_VERSION
        ):

            return None


        data[
            "from_cache"
        ] = True


        return data


    except Exception:

        return None


def save_cache(
    reference,
    offer_type,
    data
):

    path = cache_path(
        reference,
        offer_type
    )


    try:

        with path.open(
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2
            )


        return True


    except Exception as error:

        print(
            "⚠️ Cache Actiris Detail impossible :",
            error
        )

        return False


# ============================================================
# REQUÊTE HTTP
# ============================================================

def request_detail_page(
    reference,
    offer_type=None
):

    url = build_detail_url(
        reference,
        offer_type
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
                    "HTML Actiris vide."
                )


            return response


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
                f"      ⚠️ Actiris Detail "
                f"tentative {attempt}/{MAX_RETRIES} échouée"
            )


            print(
                f"      ↳ nouvelle tentative "
                f"dans {delay}s"
            )


            time.sleep(
                delay
            )


    raise requests.RequestException(
        str(
            last_error
        )
    )


# ============================================================
# BEAUTIFULSOUP
# ============================================================

def build_soup(
    html_content
):

    return BeautifulSoup(
        html_content,
        "html.parser"
    )


# ============================================================
# HTML -> LIGNES
# ============================================================

def soup_to_lines(
    soup
):

    # ========================================================
    # SUPPRESSION BRUIT
    # ========================================================

    for element in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "template",
        ]
    ):

        element.decompose()


    for selector in [
        "header",
        "nav",
        "footer",
    ]:

        for element in soup.select(
            selector
        ):

            element.decompose()


    # ========================================================
    # RACINE
    # ========================================================

    root = (
        soup.find(
            "main"
        )
        or
        soup.body
        or
        soup
    )


    raw_text = root.get_text(
        "\n"
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
# TROUVER UNE LIGNE
# ============================================================

def find_line_index(
    lines,
    markers,
    start=0
):

    normalized_markers = [
        normalize_label(
            marker
        )
        for marker
        in markers
    ]


    for index in range(
        start,
        len(
            lines
        )
    ):

        current = normalize_label(
            lines[
                index
            ]
        )


        for marker in (
            normalized_markers
        ):

            if (
                current == marker
                or
                current.startswith(
                    marker
                )
            ):

                return index


    return None


# ============================================================
# CONTENU OFFRE
# ============================================================

def extract_job_lines(
    all_lines
):

    start_index = find_line_index(
        all_lines,
        JOB_START_MARKERS
    )


    # ========================================================
    # FALLBACK PAR RÉFÉRENCE
    # ========================================================

    if start_index is None:

        for index, line in enumerate(
            all_lines
        ):

            if re.search(
                r"\bRéférence\s+\d+",
                line,
                flags=re.IGNORECASE
            ):

                start_index = max(
                    0,
                    index - 5
                )

                break


    if start_index is None:

        return []


    end_index = find_line_index(
        all_lines,
        PAGE_END_MARKERS,
        start=start_index + 1
    )


    if end_index is None:

        end_index = len(
            all_lines
        )


    # Si on a trouvé le vrai titre
    # "OFFRES D'EMPLOI", on le retire.
    if normalize_label(
        all_lines[
            start_index
        ]
    ) in {
        normalize_label(
            marker
        )
        for marker
        in JOB_START_MARKERS
    }:

        start_index += 1


    return all_lines[
        start_index:
        end_index
    ]


# ============================================================
# TITRE DEPUIS <TITLE>
# ============================================================

def extract_title_from_html(
    soup
):

    if not soup.title:

        return None


    page_title = clean_text(
        soup.title.get_text(
            " ",
            strip=True
        )
    )


    if not page_title:

        return None


    # Exemple :
    #
    # Data-Engineer /X) H/F/X - Ref. 5924678 | Actiris

    page_title = re.sub(
        r"\s*-\s*Ref\.?\s*\d+.*$",
        "",
        page_title,
        flags=re.IGNORECASE
    )


    page_title = re.sub(
        r"\s*\|\s*Actiris.*$",
        "",
        page_title,
        flags=re.IGNORECASE
    )


    page_title = clean_text(
        page_title
    )


    return (
        page_title
        or
        None
    )


# ============================================================
# RÉFÉRENCE
# ============================================================

def extract_reference_line(
    lines
):

    for line in lines:

        if re.search(
            r"\bRéférence\s+\d+",
            line,
            flags=re.IGNORECASE
        ):

            return line


    return None


# ============================================================
# VALEUR APRÈS UN LABEL
# ============================================================

def get_label_value(
    lines,
    labels
):
    """
    Gère les deux formes :

    Lieu : 1000 - Bruxelles

    et

    Lieu :
    1000 - Bruxelles
    """

    normalized_labels = [
        normalize_label(
            label
        ).rstrip(
            ":"
        )
        for label
        in labels
    ]


    for index, line in enumerate(
        lines
    ):

        normalized_line = (
            normalize_label(
                line
            )
        )


        normalized_line_without_colon = (
            normalized_line.rstrip(
                ":"
            )
        )


        for label in normalized_labels:

            # =================================================
            # LABEL EXACT
            # =================================================

            if (
                normalized_line_without_colon
                ==
                label
            ):

                for next_index in range(
                    index + 1,
                    min(
                        index + 5,
                        len(
                            lines
                        )
                    )
                ):

                    candidate = clean_text(
                        lines[
                            next_index
                        ]
                    )


                    if is_separator_line(
                        candidate
                    ):

                        continue


                    candidate_normalized = (
                        normalize_label(
                            candidate
                        )
                    )


                    # Évite de récupérer un autre label.
                    if any(
                        candidate_normalized.rstrip(
                            ":"
                        )
                        ==
                        other_label
                        for other_label
                        in normalized_labels
                    ):

                        break


                    return candidate


            # =================================================
            # LABEL + VALEUR MÊME LIGNE
            # =================================================

            if normalized_line.startswith(
                label + ":"
            ):

                if ":" in line:

                    value = clean_text(
                        line.split(
                            ":",
                            1
                        )[1]
                    )


                    if value:

                        return value


    return None


# ============================================================
# EXTRACTION SECTION
# ============================================================

def extract_section(
    lines,
    section_title
):

    target = normalize_label(
        section_title
    )


    start_index = None


    for index, line in enumerate(
        lines
    ):

        if normalize_label(
            line
        ) == target:

            start_index = (
                index + 1
            )

            break


    if start_index is None:

        return ""


    stop_markers = {
        normalize_label(
            marker
        )
        for marker
        in (
            SECTION_MARKERS
            +
            PAGE_END_MARKERS
            +
            APPLICATION_MARKERS
        )
    }


    output = []


    for index in range(
        start_index,
        len(
            lines
        )
    ):

        line = clean_text(
            lines[
                index
            ]
        )


        normalized = normalize_label(
            line
        )


        if normalized in stop_markers:

            break


        # Bruit Actiris = fin de section utile.
        if any(
            normalized.startswith(
                normalize_label(
                    prefix
                )
            )
            for prefix
            in NOISE_PREFIXES
        ):

            break


        if is_separator_line(
            line
        ):

            continue


        output.append(
            line
        )


    return "\n".join(
        output
    ).strip()


# ============================================================
# EMPLOYEUR
# ============================================================

def extract_employer(
    lines
):

    marker = normalize_label(
        "Nom de l'employeur"
    )


    for index, line in enumerate(
        lines
    ):

        if normalize_label(
            line
        ) != marker:

            continue


        for next_index in range(
            index + 1,
            min(
                index + 5,
                len(
                    lines
                )
            )
        ):

            candidate = clean_text(
                lines[
                    next_index
                ]
            )


            if is_separator_line(
                candidate
            ):

                continue


            return candidate


    return None


# ============================================================
# LANGUES
# ============================================================

def extract_languages(
    lines
):

    language_text = extract_section(
        lines,
        "Compétences linguistiques"
    )


    if not language_text:

        return []


    known_languages = [
        (
            "Français",
            [
                "français",
                "francais",
                "french",
            ],
        ),

        (
            "Néerlandais",
            [
                "néerlandais",
                "neerlandais",
                "néérlandais",
                "nederlands",
                "dutch",
            ],
        ),

        (
            "Anglais",
            [
                "anglais",
                "english",
            ],
        ),

        (
            "Allemand",
            [
                "allemand",
                "german",
                "deutsch",
            ],
        ),
    ]


    normalized_text = (
        normalize_label(
            language_text
        )
    )


    found = []


    for canonical, aliases in (
        known_languages
    ):

        for alias in aliases:

            if re.search(
                rf"\b{re.escape(normalize_label(alias))}\b",
                normalized_text
            ):

                found.append(
                    canonical
                )

                break


    return found


# ============================================================
# EXPÉRIENCE
# ============================================================

def extract_experience(
    lines,
    profile_text=""
):

    metadata_value = get_label_value(
        lines,
        [
            "Nombre d'années d'expérience",
            "Nombre d’années d’expérience",
        ]
    )


    if metadata_value:

        return metadata_value


    # ========================================================
    # FALLBACK DANS LE PROFIL
    # ========================================================

    text = clean_text(
        profile_text
    )


    patterns = [

        (
            r"(minimum\s+\d+\s*(?:à|a|-|et)\s*\d+\s+ans"
            r"(?:\s+d['’ ]expérience)?)"
        ),

        (
            r"(minimum\s+\d+\s+ans"
            r"(?:\s+d['’ ]expérience)?)"
        ),

        (
            r"(\d+\s*(?:à|a|-)\s*\d+\s+ans"
            r"(?:\s+d['’ ]expérience)?)"
        ),

        (
            r"(\d+\s+ans\s+d['’ ]expérience)"
        ),

        (
            r"(\d+\s+years?\s+of\s+experience)"
        ),
    ]


    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE
        )


        if match:

            return clean_text(
                match.group(1)
            )


    return None


# ============================================================
# MATCHING TEXT
# ============================================================

def extract_matching_lines(
    job_lines
):

    end_index = len(
        job_lines
    )


    # ========================================================
    # COUPE CANDIDATURE
    # ========================================================

    for marker in APPLICATION_MARKERS:

        marker_index = find_line_index(
            job_lines,
            [
                marker
            ]
        )


        if (
            marker_index
            is not None
        ):

            end_index = min(
                end_index,
                marker_index
            )


    useful_lines = (
        job_lines[
            :end_index
        ]
    )


    filtered = []


    for line in useful_lines:

        line = clean_text(
            line
        )


        if is_separator_line(
            line
        ):

            continue


        normalized = normalize_label(
            line
        )


        if any(
            normalized.startswith(
                normalize_label(
                    prefix
                )
            )
            for prefix
            in NOISE_PREFIXES
        ):

            continue


        filtered.append(
            line
        )


    return filtered


# ============================================================
# STRUCTURE
# ============================================================

def extract_structured_info(
    soup,
    job_lines
):

    title = extract_title_from_html(
        soup
    )


    company_description = (
        extract_section(
            job_lines,
            "Description de l'entreprise"
        )
    )


    job_description = (
        extract_section(
            job_lines,
            "Description de la fonction"
        )
    )


    profile = (
        extract_section(
            job_lines,
            "Profil"
        )
    )


    access_conditions = (
        extract_section(
            job_lines,
            "Conditions d'accès"
        )
    )


    language_section = (
        extract_section(
            job_lines,
            "Compétences linguistiques"
        )
    )


    benefits = (
        extract_section(
            job_lines,
            "Avantages du poste"
        )
    )


    practical_information = (
        extract_section(
            job_lines,
            "Informations pratiques"
        )
    )


    return {

        "title":
            title,

        "reference_line":
            extract_reference_line(
                job_lines
            ),

        "location":
            get_label_value(
                job_lines,
                [
                    "Lieu",
                    "Lieu de travail",
                ]
            ),

        "work_regime":
            get_label_value(
                job_lines,
                [
                    "Temps de travail",
                    "Régime de travail",
                ]
            ),

        "contract_type":
            get_label_value(
                job_lines,
                [
                    "Type de contrat",
                ]
            ),

        "job_family":
            get_label_value(
                job_lines,
                [
                    "Famille de métiers",
                ]
            ),

        "experience":
            extract_experience(
                job_lines,
                profile
            ),

        "driving_license":
            get_label_value(
                job_lines,
                [
                    "Permis de conduire",
                ]
            ),

        "company":
            extract_employer(
                job_lines
            ),

        "languages":
            extract_languages(
                job_lines
            ),

        "company_description":
            company_description,

        "job_description":
            job_description,

        "profile":
            profile,

        "access_conditions":
            access_conditions,

        "language_section":
            language_section,

        "benefits":
            benefits,

        "practical_information":
            practical_information,
    }


# ============================================================
# PARSING COMPLET
# ============================================================

def parse_actiris_detail_html(
    html_content
):

    soup = build_soup(
        html_content
    )


    all_lines = soup_to_lines(
        soup
    )


    job_lines = extract_job_lines(
        all_lines
    )


    if not job_lines:

        raise ValueError(
            "Bloc principal de l'offre introuvable."
        )


    structured = (
        extract_structured_info(
            soup,
            job_lines
        )
    )


    matching_lines = (
        extract_matching_lines(
            job_lines
        )
    )


    # ========================================================
    # AJOUT DU TITRE AU MATCHING
    # ========================================================

    title = clean_text(
        structured.get(
            "title"
        )
    )


    if title:

        if not any(
            clean_text(
                line
            ).lower()
            ==
            title.lower()
            for line in matching_lines[:10]
        ):

            matching_lines.insert(
                0,
                title
            )


    raw_text = "\n".join(
        job_lines
    ).strip()


    matching_text = "\n".join(
        matching_lines
    ).strip()


    return {

        "raw_text":
            raw_text,

        "matching_text":
            matching_text,

        "matching_text_length":
            len(
                matching_text
            ),

        "structured":
            structured,
    }


# ============================================================
# API PUBLIQUE
# ============================================================

def get_actiris_job_detail(
    reference,
    offer_type=None,
    use_cache=True
):

    reference = clean_text(
        reference
    )


    offer_type = clean_text(
        offer_type
    )


    url = build_detail_url(
        reference,
        offer_type
    )


    # ========================================================
    # CACHE
    # ========================================================

    if use_cache:

        cached = load_cache(
            reference,
            offer_type
        )


        if cached is not None:

            cached[
                "success"
            ] = True


            cached[
                "error"
            ] = None


            return cached


    # ========================================================
    # HTTP
    # ========================================================

    try:

        response = request_detail_page(
            reference,
            offer_type
        )


    except Exception as error:

        return {

            "success":
                False,

            "reference":
                reference,

            "offer_type":
                offer_type,

            "url":
                url,

            "raw_text":
                "",

            "matching_text":
                "",

            "matching_text_length":
                0,

            "structured":
                {},

            "from_cache":
                False,

            "parser_version":
                PARSER_VERSION,

            "error":
                str(
                    error
                ),
        }


    # ========================================================
    # PARSING
    # ========================================================

    try:

        parsed = (
            parse_actiris_detail_html(
                response.text
            )
        )


        if (
            parsed[
                "matching_text_length"
            ]
            < 100
        ):

            raise ValueError(
                (
                    "Contenu Actiris trop court "
                    "pour être exploitable."
                )
            )


    except Exception as error:

        return {

            "success":
                False,

            "reference":
                reference,

            "offer_type":
                offer_type,

            "url":
                response.url,

            "raw_text":
                "",

            "matching_text":
                "",

            "matching_text_length":
                0,

            "structured":
                {},

            "from_cache":
                False,

            "parser_version":
                PARSER_VERSION,

            "error":
                (
                    "Parsing Actiris impossible : "
                    f"{error}"
                ),
        }


    # ========================================================
    # RÉSULTAT
    # ========================================================

    result = {

        "success":
            True,

        "reference":
            reference,

        "offer_type":
            offer_type,

        "url":
            response.url,

        "raw_text":
            parsed[
                "raw_text"
            ],

        "matching_text":
            parsed[
                "matching_text"
            ],

        "matching_text_length":
            parsed[
                "matching_text_length"
            ],

        "structured":
            parsed[
                "structured"
            ],

        "from_cache":
            False,

        "parser_version":
            PARSER_VERSION,

        "fetched_at":
            datetime.now().isoformat(
                timespec="seconds"
            ),

        "error":
            None,
    }


    save_cache(
        reference,
        offer_type,
        result
    )


    return result


# ============================================================
# AFFICHAGE TEST
# ============================================================

def print_test_result(
    result
):

    print()

    print(
        "=" * 80
    )


    print(
        "Référence :",
        result[
            "reference"
        ]
    )


    print(
        "Type      :",
        result[
            "offer_type"
        ]
    )


    print(
        "Succès    :",
        result[
            "success"
        ]
    )


    print(
        "Cache     :",
        result[
            "from_cache"
        ]
    )


    print(
        "Longueur  :",
        result[
            "matching_text_length"
        ]
    )


    if result[
        "error"
    ]:

        print(
            "Erreur    :",
            result[
                "error"
            ]
        )

        return


    print()

    print(
        "STRUCTURE :"
    )


    print(
        json.dumps(
            result[
                "structured"
            ],
            ensure_ascii=False,
            indent=2
        )
    )


    print()

    print(
        "MATCHING TEXT :"
    )

    print(
        "-" * 80
    )


    print(
        result[
            "matching_text"
        ][:5000]
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    TEST_OFFERS = [

        {
            "reference":
                "5925099",

            "type":
                "DirectOnline",
        },

        {
            "reference":
                "5924678",

            "type":
                "Hrxml",
        },

        {
            "reference":
                "5905799",

            "type":
                "Select",
        },
    ]


    print()

    print(
        "=" * 80
    )

    print(
        "        ACTIRIS DETAIL - PRODUCTION TEST V1.1"
    )

    print(
        "=" * 80
    )


    for offer in TEST_OFFERS:

        result = (
            get_actiris_job_detail(

                reference=
                    offer[
                        "reference"
                    ],

                offer_type=
                    offer[
                        "type"
                    ],

                use_cache=False
            )
        )


        print_test_result(
            result
        )