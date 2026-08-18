"""
JOB HUNTER BELGIUM
TRAVAILLERPOUR.BE DETAIL - VERSION 1.1

CORRECTIONS V1.1
================

1. Le contenu des "jobs recommandés" en bas de page
   n'est plus utilisé pour déterminer les restrictions.

   Cela corrige notamment le faux :
       "Réservé aux fonctionnaires"
   détecté sur XFC26104.

2. L'expérience est recherchée prioritairement dans
   la vraie section "Expérience requise" /
   "Vereiste ervaring".

3. Meilleure extraction du barème :
       NA11
       NA21
       B1
       etc.

4. Le salaire annuel brut est conservé lorsqu'il existe.

5. Cache V1.1 séparé.

6. Génération automatique du TXT de test.

IMPORTANT
=========

Ce fichier extrait les données.

La règle métier spécifique au profil utilisateur :

    MASTER REQUIS -> INÉLIGIBLE

sera appliquée dans main.py, et non ici.

Ainsi le connecteur reste réutilisable indépendamment
du profil de candidature.
"""


import hashlib
import json
import re
import sys
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
    / "travaillerpour_detail_cache_v2"
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

        "Accept-Language": (
            "fr-BE,fr;q=0.9,"
            "en;q=0.8,"
            "nl;q=0.7"
        ),

        "Cache-Control":
            "no-cache",

        "Pragma":
            "no-cache",
    }
)


# ============================================================
# LOGGER
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
            "travaillerpour_detail_"
            f"{timestamp}.txt"
        )
    )


    log_file = log_path.open(
        "w",
        encoding="utf-8"
    )


    original_stdout = sys.stdout

    original_stderr = sys.stderr


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

    sys.stdout = logger[
        "stdout"
    ]


    sys.stderr = logger[
        "stderr"
    ]


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


    value = value.replace(
        "\ufeff",
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
            r"[^A-Za-z0-9_-]+",
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
        f"URL_{digest}"
    )


def cache_path(
    url,
    external_id=None
):

    return (
        CACHE_DIR
        /
        (
            make_cache_key(
                url,
                external_id
            )
            +
            ".json"
        )
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

            data = json.load(
                file
            )


        if (
            data.get(
                "parser_version"
            )
            !=
            PARSER_VERSION
        ):

            return None


        data[
            "from_cache"
        ] = True


        return data


    except Exception:

        return None


def save_cache(
    url,
    external_id,
    data
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
                data,
                file,
                ensure_ascii=False,
                indent=2
            )


        return True


    except Exception as error:

        print(
            "⚠️ Cache travaillerpour impossible :",
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
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True
            )


            response.raise_for_status()


            if not response.text:

                raise ValueError(
                    "HTML travaillerpour.be vide."
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
                f"      ⚠️ Tentative "
                f"{attempt}/{MAX_RETRIES} échouée"
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
# SOUP
# ============================================================

def build_soup(
    html_content
):

    return BeautifulSoup(
        html_content,
        "html.parser"
    )


# ============================================================
# LIGNES
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


    for raw_line in text.splitlines():

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
# SUPPRESSION DES RECOMMANDATIONS
# ============================================================

PRIMARY_END_MARKERS = [

    "Ces jobs peuvent vous intéresser?",

    "Ces jobs peuvent vous intéresser ?",

    "Deze jobs kunnen je interesseren?",

    "Même domaine",

    "Zelfde domein",

    "Rencontrez nos collègues",

    "Ontmoet onze collega's",

    "Newsletter",
]


def cut_primary_job_lines(
    lines
):
    """
    Tout ce qui se trouve après les recommandations
    d'autres offres doit être exclu.

    Sinon les restrictions des AUTRES jobs peuvent
    contaminer l'offre courante.
    """

    normalized_markers = {
        normalize_text(
            marker
        )
        for marker
        in PRIMARY_END_MARKERS
    }


    for index, line in enumerate(
        lines
    ):

        if (
            normalize_text(
                line
            )
            in
            normalized_markers
        ):

            return lines[
                :index
            ]


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
            r"\s*\|\s*Workingfor\.be.*$",
            "",
            title,
            flags=re.IGNORECASE
        )


        if title:

            return title


    return None


# ============================================================
# INDEX
# ============================================================

def find_exact_index(
    lines,
    labels,
    start=0
):

    normalized_labels = {
        normalize_text(
            label
        )
        for label
        in labels
    }


    for index in range(
        start,
        len(
            lines
        )
    ):

        if (
            normalize_text(
                lines[
                    index
                ]
            )
            in
            normalized_labels
        ):

            return index


    return None


# ============================================================
# MÉTADONNÉE LABEL -> VALEUR
# ============================================================

METADATA_LABELS = [

    "Code de sélection",
    "Selectiecode",

    "Langue",
    "Taal",

    "Diplôme",
    "Diploma",

    "Type de contrat",
    "Contracttype",

    "Niveau de fonction",
    "Functieniveau",

    "Type de recrutement",
    "Wervingstype",

    "Durée",
    "Duur",

    "Lieu de travail",
    "Werkplaats",

    "Temps plein/temps partiel",
    "Voltijds/deeltijds",
]


def get_label_value(
    lines,
    labels,
    max_lookahead=5
):

    index = find_exact_index(
        lines,
        labels
    )


    if index is None:

        return None


    known_labels = {
        normalize_text(
            label
        )
        for label
        in METADATA_LABELS
    }


    for current_index in range(
        index + 1,
        min(
            len(
                lines
            ),
            index + max_lookahead + 1
        )
    ):

        candidate = clean_text(
            lines[
                current_index
            ]
        )


        if not candidate:

            continue


        if (
            normalize_text(
                candidate
            )
            in
            known_labels
        ):

            break


        return candidate


    return None


# ============================================================
# MÉTADONNÉES
# ============================================================

def extract_selection_code(
    lines
):

    return get_label_value(
        lines,
        [
            "Code de sélection",
            "Selectiecode",
        ]
    )


def extract_language(
    lines
):

    return get_label_value(
        lines,
        [
            "Langue",
            "Taal",
        ]
    )


def extract_degree(
    lines
):

    return get_label_value(
        lines,
        [
            "Diplôme",
            "Diploma",
        ]
    )


def extract_contract_type(
    lines
):

    return get_label_value(
        lines,
        [
            "Type de contrat",
            "Contracttype",
        ]
    )


def extract_function_level(
    lines
):

    return get_label_value(
        lines,
        [
            "Niveau de fonction",
            "Functieniveau",
        ]
    )


def extract_recruitment_type(
    lines
):

    return get_label_value(
        lines,
        [
            "Type de recrutement",
            "Wervingstype",
        ]
    )


def extract_duration(
    lines
):

    return get_label_value(
        lines,
        [
            "Durée",
            "Duur",
        ]
    )


def extract_location(
    lines
):

    return get_label_value(
        lines,
        [
            "Lieu de travail",
            "Werkplaats",
        ]
    )


def extract_work_regime(
    lines
):

    return get_label_value(
        lines,
        [
            "Temps plein/temps partiel",
            "Voltijds/deeltijds",
        ]
    )


# ============================================================
# ENTREPRISE
# ============================================================

def extract_company(
    lines,
    title
):

    if not title:

        return None


    normalized_title = normalize_text(
        title
    )


    title_indexes = []


    for index, line in enumerate(
        lines[:50]
    ):

        if (
            normalize_text(
                line
            )
            ==
            normalized_title
        ):

            title_indexes.append(
                index
            )


    if not title_indexes:

        return None


    start_index = (
        title_indexes[-1]
        +
        1
    )


    ignored = {

        "print this job",

        "share this job",

        "love this job",

        "postuler",

        "solliciteren",
    }


    for index in range(
        start_index,
        min(
            len(
                lines
            ),
            start_index + 15
        )
    ):

        candidate = clean_text(
            lines[
                index
            ]
        )


        normalized = normalize_text(
            candidate
        )


        if not candidate:

            continue


        if normalized in ignored:

            continue


        if normalized == normalized_title:

            continue


        if normalized.startswith(
            (
                "postuler jusqu",
                "solliciteren tot",
                "openvacancies",
            )
        ):

            continue


        if re.fullmatch(
            r"\d+\s+poste(?:s)?",
            normalized,
            flags=re.IGNORECASE
        ):

            continue


        if len(
            candidate
        ) <= 180:

            return candidate


    return None


# ============================================================
# SECTION
# ============================================================

def extract_section(
    lines,
    start_labels,
    stop_labels,
    search_start=0
):

    start_index = find_exact_index(
        lines,
        start_labels,
        start=
            search_start
    )


    if start_index is None:

        return ""


    start_index += 1


    normalized_stops = {
        normalize_text(
            label
        )
        for label
        in stop_labels
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


        if (
            normalize_text(
                line
            )
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
# CONTENU MÉTIER
# ============================================================

def extract_job_content(
    lines
):

    return extract_section(

        lines,

        [
            "Contenu de la fonction",
            "Jobinhoud",
        ],

        [
            "Employeur",
            "Werkgever",
        ],
    )


def extract_employer_section(
    lines
):

    return extract_section(

        lines,

        [
            "Employeur",
            "Werkgever",
        ],

        [
            "Conditions de participation",
            "Deelnemingsvoorwaarden",
            "Compétences",
            "Competenties",
            "Procédure",
            "Procedure",
        ],
    )


def extract_participation_section(
    lines
):

    return extract_section(

        lines,

        [
            "Conditions de participation",
            "Deelnemingsvoorwaarden",
            "Compétences",
            "Competenties",
        ],

        [
            "Procédure",
            "Procedure",
            "Offre",
            "Aanbod",
        ],
    )


# ============================================================
# DESCRIPTION COMPLÈTE
# ============================================================

def find_description_complete_index(
    lines
):

    return find_exact_index(
        lines,
        [
            "Description complète",
            "Volledige beschrijving",
        ]
    )


def extract_detailed_profile(
    lines
):

    description_index = (
        find_description_complete_index(
            lines
        )
    )


    if description_index is None:

        return ""


    start_index = find_exact_index(
        lines,
        [
            "Compétences",
            "Competenties",
        ],
        start=
            description_index + 1
    )


    if start_index is None:

        return ""


    stop_labels = {

        normalize_text(
            value
        )

        for value in [

            "Conditions d'affectation",

            "Aanstellingsvoorwaarden",

            "Étape 1 : Vérification du diplôme",

            "Etape 1 : Vérification du diplôme",

            "Stap 1: Screening van diploma",
        ]
    }


    stop_index = None


    for index in range(
        start_index,
        len(
            lines
        )
    ):

        if (
            normalize_text(
                lines[
                    index
                ]
            )
            in
            stop_labels
        ):

            stop_index = index

            break


    if stop_index is None:

        stop_index = min(
            len(
                lines
            ),
            start_index + 250
        )


    return "\n".join(
        lines[
            start_index:
            stop_index
        ]
    ).strip()


# ============================================================
# EXPÉRIENCE REQUISE
# ============================================================

EXPERIENCE_HEADINGS = [

    "Expérience requise",

    "Expérience requise à la date limite d’inscription :",

    "Expérience requise à la date limite d'inscription :",

    "Vereiste ervaring",

    "Vereiste ervaring op de uiterste inschrijvingsdatum:",
]


EXPERIENCE_STOP_HEADINGS = [

    "Conditions d'affectation",

    "Aanstellingsvoorwaarden",

    "Étape 1 : Vérification du diplôme",

    "Etape 1 : Vérification du diplôme",

    "Stap 1: Screening van diploma",

    "Procédure",

    "Procedure",
]


def extract_experience_block(
    lines
):

    description_index = (
        find_description_complete_index(
            lines
        )
    )


    search_start = (
        description_index + 1
        if description_index is not None
        else 0
    )


    return extract_section(

        lines,

        EXPERIENCE_HEADINGS,

        EXPERIENCE_STOP_HEADINGS,

        search_start=
            search_start,
    )


def interpret_experience(
    text
):

    if not text:

        return None


    compact = re.sub(
        r"\s+",
        " ",
        text
    )


    normalized = normalize_text(
        compact
    )


    # ========================================================
    # AUCUNE
    # ========================================================

    no_experience_patterns = [

        r"aucune expérience n['’]?est requise",

        r"aucune expérience professionnelle n['’]?est requise",

        r"pas d['’]expérience requise",

        r"il n['’]?y a pas d['’]?expérience requise",

        r"geen ervaring vereist",

        r"geen werkervaring vereist",

        r"er is geen ervaring vereist",

        r"geen professionele ervaring vereist",

        r"no experience required",
    ]


    for pattern in no_experience_patterns:

        if re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE
        ):

            return (
                "Aucune expérience requise"
            )


    # ========================================================
    # FR
    # ========================================================

    french_patterns = [

        (
            r"(?:minimum|au moins)"
            r"[^.]{0,30}?"
            r"(\d+)\s+ans?"
        ),

        (
            r"(\d+)\s+ans?"
            r"[^.]{0,60}?"
            r"d['’]expérience"
        ),

        (
            r"vous avez"
            r"[^.]{0,80}?"
            r"(\d+)\s+ans?"
            r"[^.]{0,80}?"
            r"d['’]expérience"
        ),
    ]


    for pattern in french_patterns:

        match = re.search(
            pattern,
            compact,
            flags=re.IGNORECASE
        )


        if match:

            return (
                f"Minimum {match.group(1)} "
                "an(s) d'expérience"
            )


    # ========================================================
    # NL
    # ========================================================

    dutch_patterns = [

        (
            r"(?:minimum|minstens)"
            r"[^.]{0,40}?"
            r"(\d+)\s+jaar"
        ),

        (
            r"(\d+)\s+jaar"
            r"[^.]{0,80}?"
            r"(?:ervaring|werkervaring)"
        ),
    ]


    for pattern in dutch_patterns:

        match = re.search(
            pattern,
            compact,
            flags=re.IGNORECASE
        )


        if match:

            return (
                f"Minimum {match.group(1)} "
                "an(s) d'expérience"
            )


    return (
        "Expérience requise "
        "(durée non précisée)"
    )


def extract_experience(
    lines,
    participation_section
):

    # ========================================================
    # PRIORITÉ À LA VRAIE SECTION FORMELLE
    # ========================================================

    block = extract_experience_block(
        lines
    )


    if block:

        return interpret_experience(
            block
        )


    # ========================================================
    # FALLBACK POUR LES OFFRES SIMPLES
    # ========================================================

    if participation_section:

        normalized = normalize_text(
            participation_section
        )


        if any(
            phrase
            in normalized

            for phrase in [

                "aucune expérience n'est requise",

                "aucune expérience n’est requise",

                "geen ervaring vereist",

                "er is geen ervaring vereist",
            ]
        ):

            return (
                "Aucune expérience requise"
            )


        patterns = [

            r"(\d+)\s+ans?"
            r"[^.]{0,80}?"
            r"d['’]expérience",

            r"(\d+)\s+jaar"
            r"[^.]{0,80}?"
            r"(?:ervaring|werkervaring)",
        ]


        for pattern in patterns:

            match = re.search(
                pattern,
                participation_section,
                flags=re.IGNORECASE
            )


            if match:

                return (
                    f"Minimum {match.group(1)} "
                    "an(s) d'expérience"
                )


    return None


# ============================================================
# NOMBRE DE POSTES
# ============================================================

def extract_positions_count(
    text
):

    patterns = [

        r"\b(\d+)\s+poste(?:s)?\b",

        r"\b(\d+)\s+vacature(?:s)?\b",
    ]


    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE
        )


        if match:

            try:

                return int(
                    match.group(
                        1
                    )
                )

            except Exception:

                pass


    return None


# ============================================================
# DEADLINE
# ============================================================

def extract_deadline(
    text
):

    compact = re.sub(
        r"\s+",
        " ",
        text
    )


    patterns = [

        (
            r"Postuler\s+jusqu['’]au\s+"
            r"(\d{1,2}/\d{1,2}/\d{4})"
        ),

        (
            r"Solliciteren\s+tot\s+"
            r"(\d{1,2}/\d{1,2}/\d{4})"
        ),
    ]


    for pattern in patterns:

        match = re.search(
            pattern,
            compact,
            flags=re.IGNORECASE
        )


        if match:

            return match.group(
                1
            )


    return None


# ============================================================
# RESTRICTIONS
# ============================================================

def extract_restriction(
    primary_text
):
    """
    IMPORTANT :
    primary_text ne contient PLUS les jobs recommandés.

    Une restriction trouvée ici concerne donc
    réellement l'offre courante.
    """

    normalized = normalize_text(
        primary_text
    )


    restrictions = []


    checks = [

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
                "moins de 26 ans pendant toute la durée du contrat",
            ],
        ),

        (
            "Convention premier emploi",
            [
                "convention premier emploi",
                "convention de premier emploi",
            ],
        ),
    ]


    for canonical, aliases in checks:

        for alias in aliases:

            if (
                normalize_text(
                    alias
                )
                in
                normalized
            ):

                restrictions.append(
                    canonical
                )

                break


    if not restrictions:

        return None


    return ", ".join(
        dict.fromkeys(
            restrictions
        )
    )


# ============================================================
# BARÈME
# ============================================================

def extract_grade_scale(
    primary_text
):

    compact = re.sub(
        r"\s+",
        " ",
        primary_text
    )


    patterns = [

        (
            r"(?:échelle de traitement correspondante|"
            r"echelle de traitement correspondante|"
            r"barème de traitement correspondant|"
            r"bareme de traitement correspondant|"
            r"weddeschaal)"
            r"[^A-Z0-9]{0,30}"
            r"\(?([A-Z]{1,3}\d{1,3})\)?"
        ),

        (
            r"(?:échelle de traitement|"
            r"echelle de traitement)"
            r"[^A-Z0-9]{0,20}"
            r"\(?([A-Z]{1,3}\d{1,3})\)?"
        ),
    ]


    for pattern in patterns:

        match = re.search(
            pattern,
            compact,
            flags=re.IGNORECASE
        )


        if match:

            return (
                match.group(
                    1
                )
                .upper()
            )


    return None


# ============================================================
# SALAIRE
# ============================================================

def extract_salary(
    lines,
    primary_text
):

    salary_section = extract_section(

        lines,

        [
            "Rémunération",
            "Loon",
        ],

        [
            "Avantages",
            "Voordelen",
            "Qui contacter?",
            "Wie contacteren?",
        ],
    )


    compact = re.sub(
        r"\s+",
        " ",
        salary_section
    )


    patterns = [

        (
            r"(?:Traitement de départ minimum|"
            r"Traitement minimum de départ)"
            r"\s*:\s*"
            r"€?\s*"
            r"([\d\s\.,]+)"
        ),

        (
            r"Minimum aanvangswedde"
            r"\s*:\s*"
            r"€?\s*"
            r"([\d\s\.,]+)"
        ),
    ]


    for pattern in patterns:

        match = re.search(
            pattern,
            compact,
            flags=re.IGNORECASE
        )


        if match:

            amount = clean_text(
                match.group(
                    1
                )
            )


            return (
                f"{amount} € brut/an"
            )


    scale = extract_grade_scale(
        primary_text
    )


    if scale:

        return (
            f"Barème {scale}"
        )


    return None


# ============================================================
# MATCHING TEXT
# ============================================================

def build_matching_text(
    title,
    company,
    structured,
    job_content,
    employer_section,
    participation_section,
    detailed_profile
):

    blocks = []


    if title:

        blocks.append(
            title
        )


    if company:

        blocks.append(
            f"Employeur : {company}"
        )


    metadata = []


    for label, value in [

        (
            "Diplôme",
            structured.get(
                "degree"
            )
        ),

        (
            "Langue",
            structured.get(
                "language"
            )
        ),

        (
            "Contrat",
            structured.get(
                "contract_type"
            )
        ),

        (
            "Niveau",
            structured.get(
                "function_level"
            )
        ),

        (
            "Lieu",
            structured.get(
                "location"
            )
        ),

        (
            "Expérience",
            structured.get(
                "experience"
            )
        ),
    ]:

        if value:

            metadata.append(
                f"{label} : {value}"
            )


    if metadata:

        blocks.append(
            "\n".join(
                metadata
            )
        )


    for section in [

        job_content,

        employer_section,

        participation_section,

        detailed_profile,
    ]:

        section = clean_text(
            section
        )


        if section:

            blocks.append(
                section
            )


    unique_blocks = []

    seen = set()


    for block in blocks:

        normalized = normalize_text(
            block
        )


        if not normalized:

            continue


        if normalized in seen:

            continue


        seen.add(
            normalized
        )


        unique_blocks.append(
            block
        )


    return "\n\n".join(
        unique_blocks
    ).strip()


# ============================================================
# PARSING COMPLET
# ============================================================

def parse_travaillerpour_detail_html(
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


    if not all_lines:

        raise ValueError(
            "Aucun contenu principal."
        )


    # ========================================================
    # IMPORTANT : COUPE DES AUTRES JOBS
    # ========================================================

    lines = cut_primary_job_lines(
        all_lines
    )


    primary_text = "\n".join(
        lines
    )


    company = extract_company(
        lines,
        title
    )


    job_content = extract_job_content(
        lines
    )


    employer_section = (
        extract_employer_section(
            lines
        )
    )


    participation_section = (
        extract_participation_section(
            lines
        )
    )


    detailed_profile = (
        extract_detailed_profile(
            lines
        )
    )


    experience = extract_experience(
        lines,
        participation_section
    )


    grade_scale = extract_grade_scale(
        primary_text
    )


    structured = {

        "title":
            title,

        "company":
            company,

        "selection_code":
            extract_selection_code(
                lines
            ),

        "language":
            extract_language(
                lines
            ),

        "degree":
            extract_degree(
                lines
            ),

        "contract_type":
            extract_contract_type(
                lines
            ),

        "function_level":
            extract_function_level(
                lines
            ),

        "recruitment_type":
            extract_recruitment_type(
                lines
            ),

        "duration":
            extract_duration(
                lines
            ),

        "location":
            extract_location(
                lines
            ),

        "work_regime":
            extract_work_regime(
                lines
            ),

        "positions_count":
            extract_positions_count(
                primary_text
            ),

        "deadline":
            extract_deadline(
                primary_text
            ),

        "restriction":
            extract_restriction(
                primary_text
            ),

        "experience":
            experience,

        "salary":
            extract_salary(
                lines,
                primary_text
            ),

        "grade_scale":
            grade_scale,

        "job_content":
            job_content,

        "employer_section":
            employer_section,

        "participation_section":
            participation_section,

        "detailed_profile":
            detailed_profile,
    }


    matching_text = build_matching_text(

        title,
        company,
        structured,
        job_content,
        employer_section,
        participation_section,
        detailed_profile,
    )


    return {

        "raw_text":
            primary_text,

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

def get_travaillerpour_job_detail(
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


    try:

        parsed = (
            parse_travaillerpour_detail_html(
                response.text
            )
        )


        if (
            parsed[
                "matching_text_length"
            ]
            <
            300
        ):

            raise ValueError(
                (
                    "Matching text trop court : "
                    f"{parsed['matching_text_length']}"
                )
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
                    "Parsing travaillerpour impossible : "
                    f"{error}"
                ),
        }


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
# TEST
# ============================================================

TEST_OFFERS = [

    (
        "CFG26044",
        (
            "https://travaillerpour.be/fr/jobs/"
            "cfg26044-expert-scientifique-mfx"
        )
    ),

    (
        "AFG26147",
        (
            "https://travaillerpour.be/fr/jobs/"
            "afg26147-business-analyste-mfx"
        )
    ),

    (
        "XFC26104",
        (
            "https://travaillerpour.be/fr/jobs/"
            "xfc26104-gestionnaire-de-donnees-"
            "maitrisant-le-neerlandais-mfx"
        )
    ),

    (
        "CNG26031",
        (
            "https://travaillerpour.be/fr/jobs/"
            "cng26031-onderzoeker-chemische-"
            "decontaminatie-mvx"
        )
    ),
]


def print_test_result(
    result
):

    print()

    print(
        "=" * 80
    )


    print(
        "ID         :",
        result.get(
            "external_id"
        )
    )


    print(
        "Succès     :",
        result.get(
            "success"
        )
    )


    print(
        "Cache      :",
        result.get(
            "from_cache"
        )
    )


    print(
        "Longueur   :",
        result.get(
            "matching_text_length"
        )
    )


    if not result.get(
        "success"
    ):

        print(
            "Erreur     :",
            result.get(
                "error"
            )
        )

        return


    structured = (
        result.get(
            "structured",
            {}
        )
        or {}
    )


    print()

    print(
        "STRUCTURE"
    )


    print(
        "-" * 80
    )


    for field in [

        "title",

        "company",

        "selection_code",

        "language",

        "degree",

        "contract_type",

        "function_level",

        "recruitment_type",

        "duration",

        "location",

        "work_regime",

        "positions_count",

        "deadline",

        "restriction",

        "experience",

        "salary",

        "grade_scale",
    ]:

        print(
            f"{field:<22} : "
            f"{structured.get(field)}"
        )


def main():

    logger = start_logging()


    try:

        print()

        print(
            "=" * 80
        )


        print(
            " TRAVAILLERPOUR DETAIL - TEST V1.1"
        )


        print(
            "=" * 80
        )


        for external_id, url in TEST_OFFERS:

            result = (
                get_travaillerpour_job_detail(

                    url=
                        url,

                    external_id=
                        external_id,

                    use_cache=
                        False,
                )
            )


            print_test_result(
                result
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

        path = logger[
            "path"
        ]


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


if __name__ == "__main__":

    main()