"""
JOB HUNTER BELGIUM
TALENT.BRUSSELS DETAIL - VERSION 1.1

CORRECTIONS V1.1
================

- requests + BeautifulSoup uniquement
- correction des faux salaires :
    * prime vélo 0,37 €/km ≠ salaire
    * chèques-repas 8 € ≠ salaire

- détection prioritaire de :
    "Aucune expérience n'est requise"

- extraction de l'expérience depuis la vraie section
  "Expérience" plutôt que depuis tout le texte

- support des expériences requises sans durée chiffrée

- extraction de salaire limitée aux vrais contextes :
    * salaire
    * traitement
    * rémunération
    * barème
    * échelle

- extraction des sections avec correspondance exacte
  des titres pour éviter les collisions :
    Profil
    Profil recherché
    Offre
    Qui sommes-nous ?

- meilleure séparation entre :
    profil
    offre
    procédure de candidature
    employeur

- cache V2 séparé afin de ne pas réutiliser
  les résultats mal parsés de V1.
"""


import hashlib
import json
import re
import time

from datetime import datetime
from pathlib import Path

import requests

from bs4 import BeautifulSoup


# ============================================================
# VERSION
# ============================================================

PARSER_VERSION = "1.1"


# ============================================================
# CONFIGURATION
# ============================================================

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


CACHE_DIR = (
    PROJECT_ROOT
    / "logs"
    / "talent_brussels_detail_cache_v2"
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
# MARQUEURS
# ============================================================

PROFILE_MARKERS = [
    "Votre profil",
    "Profil recherché",
    "Profil",
    "Jouw profiel",
    "Functieprofiel",
]


OFFER_MARKERS = [
    "Notre offre",
    "Nous offrons",
    "Offre",
    "Ons aanbod",
    "Avantages",
]


EMPLOYER_MARKERS = [
    "Qui sommes-nous ?",
    "Qui sommes-nous?",
    "Wie zijn wij?",
]


EXPERIENCE_MARKERS = [
    "Expérience",
    "Expérience professionnelle",
    "Ervaring",
    "Werkervaring",
]


DEGREE_MARKERS = [
    "Diplôme",
    "Diplôme*",
    "Diploma",
    "Formation",
]


KNOWLEDGE_MARKERS = [
    "Connaissances",
    "Compétences",
    "Compétences techniques",
    "Compétences comportementales",
    "Atouts",
    "Kennis",
    "Competenties",
]


PROCEDURE_MARKERS = [
    "Étapes de la procédure",
    "Etapes de la procédure",
    "Procédure de candidature",
    "Stappen van de procedure",
    "Comment postuler ?",
    "Comment postuler?",
    "Hoe solliciteren?",
]


FOOTER_MARKERS = [
    "Information entreprise",
    "Informations sur l'entreprise",
    "Informatie over het bedrijf",
    "Contact",
    "Suivez-nous sur",
    "Volg ons op",
]


SECTION_MARKERS = (
    PROFILE_MARKERS
    +
    OFFER_MARKERS
    +
    EMPLOYER_MARKERS
    +
    EXPERIENCE_MARKERS
    +
    DEGREE_MARKERS
    +
    KNOWLEDGE_MARKERS
    +
    PROCEDURE_MARKERS
    +
    FOOTER_MARKERS
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


def normalize_text(
    value
):

    return (
        clean_text(
            value
        )
        .lower()
        .replace(
            "’",
            "'"
        )
    )


# ============================================================
# CACHE
# ============================================================

def make_cache_key(
    url,
    external_id=None
):

    if external_id:

        safe_id = re.sub(
            r"[^0-9A-Za-z_-]+",
            "_",
            clean_text(
                external_id
            )
        )


        if safe_id:

            return safe_id


    digest = hashlib.sha1(
        url.encode(
            "utf-8"
        )
    ).hexdigest()[:20]


    return (
        f"url_{digest}"
    )


def cache_path(
    url,
    external_id=None
):

    key = make_cache_key(
        url,
        external_id
    )


    return (
        CACHE_DIR
        /
        f"{key}.json"
    )


def load_cache(
    url,
    external_id=None
):

    path = cache_path(
        url,
        external_id
    )


    if not path.exists():

        return None


    try:

        with path.open(
            "r",
            encoding="utf-8"
        ) as file:

            result = json.load(
                file
            )


        if not isinstance(
            result,
            dict
        ):

            return None


        if (
            result.get(
                "parser_version"
            )
            !=
            PARSER_VERSION
        ):

            return None


        result[
            "from_cache"
        ] = True


        return result


    except Exception:

        return None


def save_cache(
    url,
    external_id,
    result
):

    path = cache_path(
        url,
        external_id
    )


    try:

        with path.open(
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                result,
                file,
                ensure_ascii=False,
                indent=2
            )


        return True


    except Exception as error:

        print(
            "⚠️ Cache talent.brussels impossible :",
            error
        )

        return False


# ============================================================
# HTTP
# ============================================================

def request_detail_page(
    url
):

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
                    "HTML talent.brussels vide."
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
                f"      ⚠️ talent.brussels "
                f"tentative {attempt}/{MAX_RETRIES}"
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


    root = (
        soup.find(
            "main"
        )
        or
        soup.body
        or
        soup
    )


    text = root.get_text(
        "\n"
    )


    lines = []


    previous = None


    for raw_line in (
        text.splitlines()
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
# TITRE
# ============================================================

def extract_title(
    soup
):

    h1 = soup.find(
        "h1"
    )


    if h1:

        title = clean_text(
            h1.get_text(
                " ",
                strip=True
            )
        )


        if title:

            return title


    if soup.title:

        title = clean_text(
            soup.title.get_text(
                " ",
                strip=True
            )
        )


        title = re.sub(
            r"\s*\|\s*talent\.brussels.*$",
            "",
            title,
            flags=re.IGNORECASE
        )


        if title:

            return title


    return None


# ============================================================
# MARQUEURS
# ============================================================

def find_exact_marker_index(
    lines,
    markers,
    start=0
):
    """
    Correspondance EXACTE.

    Cela évite par exemple que :
        "Profil"
    capture prématurément :
        "Profil recherché"
    """

    normalized_markers = {
        normalize_text(
            marker
        )
        for marker
        in markers
    }


    for index in range(
        start,
        len(
            lines
        )
    ):

        current = normalize_text(
            lines[
                index
            ]
        )


        if current in normalized_markers:

            return index


    return None


def find_loose_marker_index(
    lines,
    markers,
    start=0
):

    normalized_markers = [
        normalize_text(
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

        current = normalize_text(
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
# BLOC PRINCIPAL
# ============================================================

def extract_job_lines(
    lines,
    title=None
):

    start_index = 0


    if title:

        normalized_title = (
            normalize_text(
                title
            )
        )


        for index, line in enumerate(
            lines
        ):

            if normalize_text(
                line
            ) == normalized_title:

                start_index = index

                break


    end_index = (
        find_loose_marker_index(
            lines,
            FOOTER_MARKERS,
            start=
                start_index + 1
        )
    )


    if end_index is None:

        end_index = len(
            lines
        )


    return lines[
        start_index:
        end_index
    ]


# ============================================================
# SECTION GÉNÉRIQUE
# ============================================================

def extract_section(
    lines,
    possible_titles,
    extra_stop_markers=None
):

    start_index = (
        find_exact_marker_index(
            lines,
            possible_titles
        )
    )


    if start_index is None:

        return ""


    start_index += 1


    stop_markers = list(
        SECTION_MARKERS
    )


    if extra_stop_markers:

        stop_markers.extend(
            extra_stop_markers
        )


    normalized_stops = {
        normalize_text(
            marker
        )
        for marker
        in stop_markers
    }


    normalized_own_titles = {
        normalize_text(
            marker
        )
        for marker
        in possible_titles
    }


    output = []


    for index in range(
        start_index,
        len(
            lines
        )
    ):

        line = lines[
            index
        ]


        normalized = normalize_text(
            line
        )


        if (
            normalized
            in
            normalized_stops
        ):

            # Si c'est simplement une variante
            # de notre propre titre, on l'ignore.
            if normalized in normalized_own_titles:

                continue


            break


        output.append(
            line
        )


    return "\n".join(
        output
    ).strip()


# ============================================================
# BLOC APRÈS UN TITRE
# ============================================================

def extract_block_after_heading(
    lines,
    headings,
    stop_headings=None,
    max_lines=30
):

    index = find_exact_marker_index(
        lines,
        headings
    )


    if index is None:

        return ""


    normalized_stops = set()


    if stop_headings:

        normalized_stops = {
            normalize_text(
                value
            )
            for value
            in stop_headings
        }


    output = []


    for current_index in range(
        index + 1,
        min(
            len(
                lines
            ),
            index
            +
            max_lines
            +
            1
        )
    ):

        line = lines[
            current_index
        ]


        normalized = normalize_text(
            line
        )


        if (
            normalized_stops
            and
            normalized
            in
            normalized_stops
        ):

            break


        output.append(
            line
        )


    return "\n".join(
        output
    ).strip()


# ============================================================
# MATCHING TEXT
# ============================================================

def extract_matching_lines(
    job_lines
):

    end_index = len(
        job_lines
    )


    for marker in PROCEDURE_MARKERS:

        index = (
            find_exact_marker_index(
                job_lines,
                [
                    marker
                ]
            )
        )


        if index is not None:

            end_index = min(
                end_index,
                index
            )


    output = []


    ignored_exact = {
        "description",
        "beschrijving",
        "employeur",
        "werkgever",
        "postuler",
        "solliciteren",
    }


    for line in (
        job_lines[
            :end_index
        ]
    ):

        normalized = (
            normalize_text(
                line
            )
        )


        if normalized in (
            ignored_exact
        ):

            continue


        output.append(
            line
        )


    return output


# ============================================================
# DEADLINE
# ============================================================

def extract_deadline(
    text
):

    normalized_text = re.sub(
        r"\s+",
        " ",
        text
    )


    patterns = [

        (
            r"(?:postulez|postuler)"
            r"\s+(?:au\s+plus\s+tard\s+)?"
            r"(?:jusqu['’]au\s+)?"
            r"(\d{1,2}/\d{1,2}/\d{4})"
        ),

        (
            r"solliciteren\s+tot\s+"
            r"(\d{1,2}/\d{1,2}/\d{4})"
        ),

        (
            r"uiterlijk\s+"
            r"(\d{1,2}/\d{1,2}/\d{4})"
        ),

        (
            r"jusqu['’]au\s+"
            r"(\d{1,2}/\d{1,2}/\d{4})"
        ),
    ]


    for pattern in patterns:

        match = re.search(
            pattern,
            normalized_text,
            flags=re.IGNORECASE
        )


        if match:

            return match.group(
                1
            )


    return None


# ============================================================
# EXPÉRIENCE
# ============================================================

def extract_experience(
    job_lines,
    full_text
):
    """
    Règle importante :

    On cherche D'ABORD la vraie section "Expérience".

    Cela évite de considérer une condition particulière
    d'équivalence de diplôme comme expérience générale
    exigée pour le poste.
    """

    experience_block = (
        extract_block_after_heading(

            lines=
                job_lines,

            headings=
                EXPERIENCE_MARKERS,

            stop_headings=(
                DEGREE_MARKERS
                +
                KNOWLEDGE_MARKERS
                +
                OFFER_MARKERS
                +
                PROCEDURE_MARKERS
            ),

            max_lines=
                20,
        )
    )


    search_text = (
        experience_block
        or
        full_text
    )


    compact = re.sub(
        r"\s+",
        " ",
        search_text
    )


    normalized = normalize_text(
        compact
    )


    # ========================================================
    # AUCUNE EXPÉRIENCE
    # ========================================================

    no_experience_patterns = [

        r"aucune expérience n['’]?est requise",

        r"aucune expérience professionnelle n['’]?est requise",

        r"pas d['’]expérience requise",

        r"geen ervaring vereist",

        r"geen werkervaring vereist",

        r"no experience required",
    ]


    for pattern in (
        no_experience_patterns
    ):

        if re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE
        ):

            return (
                "Aucune expérience requise"
            )


    # ========================================================
    # DURÉE CHIFFRÉE
    # ========================================================

    patterns = [

        (
            r"(minimum\s+\d+\s+ans"
            r"(?:\s+d['’ ]expérience)?)"
        ),

        (
            r"(au\s+moins\s+\d+\s+ans"
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
            r"(minstens\s+\d+\s+jaar"
            r"(?:\s+relevante\s+werkervaring)?)"
        ),

        (
            r"(\d+\s+years?\s+of\s+experience)"
        ),
    ]


    for pattern in patterns:

        match = re.search(
            pattern,
            compact,
            flags=re.IGNORECASE
        )


        if match:

            return clean_text(
                match.group(
                    1
                )
            )


    # ========================================================
    # EXPÉRIENCE REQUISE MAIS DURÉE NON PRÉCISÉE
    # ========================================================

    generic_required_patterns = [

        r"une expérience professionnelle pertinente",

        r"expérience professionnelle pertinente",

        r"expérience pertinente",

        r"ervaring in",

        r"relevante ervaring",

        r"relevant professional experience",
    ]


    for pattern in (
        generic_required_patterns
    ):

        if re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE
        ):

            return (
                "Expérience pertinente requise "
                "(durée non précisée)"
            )


    return None


# ============================================================
# MONTANT
# ============================================================

def parse_euro_amount(
    value
):

    value = clean_text(
        value
    )


    value = value.replace(
        "€",
        ""
    )


    value = value.replace(
        " ",
        ""
    )


    # Format belge :
    # 3.700,00
    value = value.replace(
        ".",
        ""
    )


    value = value.replace(
        ",",
        "."
    )


    try:

        return float(
            value
        )


    except Exception:

        return None


# ============================================================
# SALAIRE
# ============================================================

def extract_salary(
    lines,
    full_text
):
    """
    N'accepte plus n'importe quel montant en euros.

    0,37 €/km = prime vélo
    8 €        = chèques-repas

    ne sont PAS des salaires.
    """

    compact = re.sub(
        r"\s+",
        " ",
        full_text
    )


    # ========================================================
    # 1. BARÈME / ÉCHELLE
    # ========================================================

    scale_patterns = [

        (
            r"(?:bar[eè]me(?:s)?|"
            r"échelle(?:s)?(?:\s+de\s+traitement)?)"
            r"\s*[:\-]?\s*"
            r"([A-Z]{1,3}\s*\d{1,4})"
        ),

        (
            r"(?:weddeschaal|schaal)"
            r"\s*[:\-]?\s*"
            r"([A-Z]{1,3}\s*\d{1,4})"
        ),
    ]


    for pattern in (
        scale_patterns
    ):

        match = re.search(
            pattern,
            compact,
            flags=re.IGNORECASE
        )


        if match:

            scale = clean_text(
                match.group(
                    1
                )
            )


            return (
                f"Barème {scale}"
            )


    # ========================================================
    # 2. FOURCHETTE SALARIALE EXPLICITE
    # ========================================================

    range_patterns = [

        (
            r"(?:salaire|rémunération|traitement)"
            r"[^€\n]{0,100}?"
            r"(\d[\d\s\.,]*)\s*€"
            r"[^€\n]{0,40}?"
            r"(?:à|a|-|et)\s*"
            r"(\d[\d\s\.,]*)\s*€"
        ),

        (
            r"(\d[\d\s\.,]*)\s*€"
            r"\s*(?:à|a|-)\s*"
            r"(\d[\d\s\.,]*)\s*€"
            r"[^.\n]{0,80}"
            r"(?:brut|bruto|par mois|maand)"
        ),
    ]


    for pattern in (
        range_patterns
    ):

        match = re.search(
            pattern,
            compact,
            flags=re.IGNORECASE
        )


        if not match:

            continue


        first = parse_euro_amount(
            match.group(
                1
            )
        )


        second = parse_euro_amount(
            match.group(
                2
            )
        )


        if (
            first is not None
            and
            second is not None
            and
            first >= 1000
            and
            second >= 1000
        ):

            return (
                f"{match.group(1).strip()} € - "
                f"{match.group(2).strip()} €"
            )


    # ========================================================
    # 3. SALAIRE SIMPLE EXPLICITE
    # ========================================================

    context_patterns = [

        r"salaire",

        r"rémunération",

        r"traitement",

        r"brut par mois",

        r"brut/mois",

        r"bruto per maand",
    ]


    for index, line in enumerate(
        lines
    ):

        normalized_line = (
            normalize_text(
                line
            )
        )


        if not any(
            re.search(
                pattern,
                normalized_line,
                flags=re.IGNORECASE
            )
            for pattern
            in context_patterns
        ):

            continue


        context_lines = lines[
            index:
            min(
                index + 5,
                len(
                    lines
                )
            )
        ]


        context = " ".join(
            context_lines
        )


        for amount_match in re.finditer(
            r"(\d[\d\s\.,]*)\s*€",
            context
        ):

            raw_amount = (
                amount_match.group(
                    1
                )
            )


            amount = parse_euro_amount(
                raw_amount
            )


            # Un salaire mensuel brut belge
            # ne sera normalement pas 8 € ou 0,37 €.
            #
            # Le seuil protège surtout contre
            # chèques repas / indemnités / primes km.
            if (
                amount is not None
                and
                amount >= 1000
            ):

                return (
                    f"{clean_text(raw_amount)} €"
                )


    return None


# ============================================================
# LANGUES
# ============================================================

def extract_languages(
    text
):

    normalized = (
        normalize_text(
            text
        )
    )


    languages = []


    language_aliases = {

        "Français": [
            "français",
            "francais",
            "french",
        ],

        "Néerlandais": [
            "néerlandais",
            "neerlandais",
            "nederlands",
            "dutch",
        ],

        "Anglais": [
            "anglais",
            "english",
            "engels",
        ],

        "Allemand": [
            "allemand",
            "german",
            "duits",
            "deutsch",
        ],
    }


    for canonical, aliases in (
        language_aliases.items()
    ):

        for alias in aliases:

            if re.search(
                rf"\b{re.escape(alias)}\b",
                normalized
            ):

                languages.append(
                    canonical
                )

                break


    return languages


# ============================================================
# CONTRAT
# ============================================================

def extract_contract(
    lines
):

    contract_terms = [

        "Statutaire",

        "Contractuel",

        "Contractuelle",

        "CDD",

        "CDI",

        "Divers",

        "Mobilité intrarégionale",

        "Statutair",

        "Contractueel",

        "Contract van bepaalde duur",

        "Contract van onbepaalde duur",
    ]


    for line in lines[:50]:

        normalized_line = (
            normalize_text(
                line
            )
        )


        for term in contract_terms:

            normalized_term = (
                normalize_text(
                    term
                )
            )


            if (
                normalized_line
                ==
                normalized_term
            ):

                return clean_text(
                    line
                )


    # ========================================================
    # FALLBACK DANS TOUT LE TEXTE
    # ========================================================

    full_text = " ".join(
        lines
    )


    normalized_full = (
        normalize_text(
            full_text
        )
    )


    phrases = [

        (
            "Durée indéterminée",
            [
                "contrat à durée indéterminée",
                "contrat a durée indéterminée",
            ],
        ),

        (
            "Durée déterminée",
            [
                "contrat à durée déterminée",
                "contrat a durée déterminée",
            ],
        ),
    ]


    for canonical, aliases in phrases:

        for alias in aliases:

            if (
                normalize_text(
                    alias
                )
                in
                normalized_full
            ):

                return canonical


    return None


# ============================================================
# DIPLÔME
# ============================================================

def extract_degree(
    job_lines,
    text
):

    degree_block = (
        extract_block_after_heading(

            lines=
                job_lines,

            headings=
                DEGREE_MARKERS,

            stop_headings=(
                EXPERIENCE_MARKERS
                +
                KNOWLEDGE_MARKERS
                +
                OFFER_MARKERS
                +
                PROCEDURE_MARKERS
            ),

            max_lines=
                15,
        )
    )


    search_text = (
        degree_block
        or
        text
    )


    patterns = [

        r"(master[^.\n]{0,100})",

        r"(bachelier[^.\n]{0,100})",

        r"(bachelor[^.\n]{0,100})",

        r"(graduat[^.\n]{0,100})",

        r"(enseignement secondaire supérieur[^.\n]{0,100})",

        r"(hoger onderwijs[^.\n]{0,100})",

        r"(universitair[^.\n]{0,100})",
    ]


    for pattern in patterns:

        match = re.search(
            pattern,
            search_text,
            flags=re.IGNORECASE
        )


        if match:

            return clean_text(
                match.group(
                    1
                )
            )


    return None


# ============================================================
# STRUCTURE
# ============================================================

def extract_structured_info(
    soup,
    job_lines,
    matching_text
):

    full_text = "\n".join(
        job_lines
    )


    return {

        "title":
            extract_title(
                soup
            ),

        "deadline":
            extract_deadline(
                full_text
            ),

        "contract_type":
            extract_contract(
                job_lines
            ),

        "experience":
            extract_experience(
                job_lines,
                matching_text
            ),

        "salary":
            extract_salary(
                job_lines,
                matching_text
            ),

        "degree":
            extract_degree(
                job_lines,
                matching_text
            ),

        "languages":
            extract_languages(
                matching_text
            ),

        "profile":
            extract_section(
                job_lines,
                PROFILE_MARKERS
            ),

        "offer":
            extract_section(
                job_lines,
                OFFER_MARKERS,
                extra_stop_markers=
                    PROCEDURE_MARKERS
            ),

        "employer_section":
            extract_section(
                job_lines,
                EMPLOYER_MARKERS
            ),
    }


# ============================================================
# PARSING COMPLET
# ============================================================

def parse_talent_brussels_detail_html(
    html_content
):

    soup = build_soup(
        html_content
    )


    title = extract_title(
        soup
    )


    all_lines = soup_to_lines(
        soup
    )


    job_lines = extract_job_lines(
        all_lines,
        title
    )


    if not job_lines:

        raise ValueError(
            "Contenu de l'offre introuvable."
        )


    matching_lines = (
        extract_matching_lines(
            job_lines
        )
    )


    if title:

        if not any(
            normalize_text(
                line
            )
            ==
            normalize_text(
                title
            )
            for line
            in matching_lines[:5]
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


    structured = (
        extract_structured_info(
            soup,
            job_lines,
            matching_text
        )
    )


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

def get_talent_brussels_job_detail(
    url,
    external_id=None,
    use_cache=True
):

    url = clean_text(
        url
    )


    external_id = clean_text(
        external_id
    )


    # ========================================================
    # CACHE
    # ========================================================

    if use_cache:

        cached = load_cache(
            url,
            external_id
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
            url
        )


    except Exception as error:

        return {

            "success":
                False,

            "external_id":
                external_id,

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
            parse_talent_brussels_detail_html(
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
                "Contenu métier trop court."
            )


    except Exception as error:

        return {

            "success":
                False,

            "external_id":
                external_id,

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
                    "Parsing talent.brussels impossible : "
                    f"{error}"
                ),
        }


    # ========================================================
    # RÉSULTAT
    # ========================================================

    result = {

        "success":
            True,

        "external_id":
            external_id,

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
        url,
        external_id,
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
        "ID        :",
        result[
            "external_id"
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


    print(
        "URL       :",
        result[
            "url"
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
        ][:6000]
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    TEST_OFFERS = [

        {
            "external_id":
                "url_3743c07310ee3779",

            "url":
                (
                    "https://www.talent.brussels/"
                    "fr/offres-d-emploi/"
                    "service-public-regional-de-bruxelles-sprb/"
                    "a1-fr-juriste-elections-communales-mfx"
                ),
        },

        {
            "external_id":
                "614399",

            "url":
                (
                    "https://www.talent.brussels/"
                    "fr/offres-d-emploi/"
                    "bruxelles-environnement/"
                    "inspecteur-securite-gaz-reference-2025-a13-hfx-614399"
                ),
        },
    ]


    print()

    print(
        "=" * 80
    )

    print(
        "     TALENT.BRUSSELS DETAIL - PRODUCTION TEST V1.1"
    )

    print(
        "=" * 80
    )


    for offer in TEST_OFFERS:

        result = (
            get_talent_brussels_job_detail(

                url=
                    offer[
                        "url"
                    ],

                external_id=
                    offer[
                        "external_id"
                    ],

                use_cache=
                    False,
            )
        )


        print_test_result(
            result
        )