"""
JOB HUNTER BELGIUM
TRAVAILLERPOUR.BE DETAIL - DIAGNOSTIC V1

OBJECTIF
========

Tester l'accès HTTP aux pages détaillées de Travaillerpour.be
AVANT de construire le parseur de production.

Nous testons plusieurs offres réelles :

- Expert scientifique
- Business Analyste
- Gestionnaire de données
- Chercheur en décontamination chimique

Le script vérifie :

1. HTTP 200
2. anti-bot / CAPTCHA
3. taille HTML
4. présence du contenu métier
5. présence de l'employeur
6. présence des sections :
   - contenu de la fonction
   - profil
   - diplôme
   - expérience
   - offre
   - lieu de travail
   - date limite
7. génération automatique d'un TXT

SORTIE
======

exports/logs/
travaillerpour_detail_diagnostic_YYYYMMDD_HHMMSS.txt
"""


import re
import sys

from datetime import datetime
from pathlib import Path

import requests

from bs4 import BeautifulSoup


# ============================================================
# DOSSIERS
# ============================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
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


HTML_DIR = (
    PROJECT_ROOT
    / "logs"
    / "travaillerpour_detail_diagnostic"
)


HTML_DIR.mkdir(
    parents=True,
    exist_ok=True
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
            "travaillerpour_detail_diagnostic_"
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
# CONFIGURATION HTTP
# ============================================================

REQUEST_TIMEOUT = 30


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
# OFFRES TEST
# ============================================================

TEST_OFFERS = [

    {
        "id":
            "CFG26044",

        "label":
            "Expert scientifique",

        "url":
            (
                "https://travaillerpour.be/fr/jobs/"
                "cfg26044-expert-scientifique-mfx"
            ),
    },


    {
        "id":
            "AFG26147",

        "label":
            "Business Analyste",

        "url":
            (
                "https://travaillerpour.be/fr/jobs/"
                "afg26147-business-analyste-mfx"
            ),
    },


    {
        "id":
            "XFC26104",

        "label":
            "Gestionnaire de données",

        "url":
            (
                "https://travaillerpour.be/fr/jobs/"
                "xfc26104-gestionnaire-de-donnees-"
                "maitrisant-le-neerlandais-mfx"
            ),
    },


    {
        "id":
            "CNG26031",

        "label":
            "Onderzoeker chemische decontaminatie",

        "url":
            (
                "https://travaillerpour.be/fr/jobs/"
                "cng26031-onderzoeker-chemische-"
                "decontaminatie-mvx"
            ),
    },
]


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
# ANTI-BOT
# ============================================================

def detect_antibot(
    html
):

    normalized = clean_text(
        html
    ).lower()


    markers = [

        "testing whether you are a human",

        "human visitor",

        "what code is in the image",

        "support id",

        "captcha",

        "access denied",

        "request rejected",

        "bot detection",

        "please enable javascript to view the page content",
    ]


    detected = []


    for marker in markers:

        if marker in normalized:

            detected.append(
                marker
            )


    return detected


# ============================================================
# HTML
# ============================================================

def build_soup(
    html
):

    return BeautifulSoup(
        html,
        "html.parser"
    )


def save_html(
    external_id,
    html
):

    path = (
        HTML_DIR
        /
        f"{external_id}.html"
    )


    try:

        path.write_text(
            html,
            encoding="utf-8"
        )


        return path


    except Exception:

        return None


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

        value = clean_text(
            h1.get_text(
                " ",
                strip=True
            )
        )


        if value:

            return value


    if soup.title:

        return clean_text(
            soup.title.get_text(
                " ",
                strip=True
            )
        )


    return None


# ============================================================
# TEXTE PRINCIPAL
# ============================================================

def extract_main_text(
    soup
):

    root = (
        soup.find(
            "main"
        )
        or
        soup.body
        or
        soup
    )


    return clean_text(
        root.get_text(
            " ",
            strip=True
        )
    )


# ============================================================
# MARQUEURS MÉTIER
# ============================================================

SEARCH_MARKERS = {

    "employeur": [

        "employeur",

        "organisation",

        "organisation qui recrute",
    ],


    "fonction": [

        "contenu de la fonction",

        "description de fonction",

        "fonction",

        "missions",

        "tâches",
    ],


    "profil": [

        "profil",

        "profil recherché",

        "compétences",
    ],


    "diplome": [

        "diplôme",

        "diplomes",

        "niveau d'études",

        "niveau d’etudes",

        "master",

        "bachelier",
    ],


    "experience": [

        "expérience",

        "experience",

        "expérience professionnelle",
    ],


    "lieu": [

        "lieu de travail",

        "localisation",

        "bruxelles",
    ],


    "offre": [

        "offre",

        "nous offrons",

        "avantages",

        "salaire",
    ],


    "deadline": [

        "date limite",

        "postuler jusqu",

        "postulez jusqu",

        "dernier jour",
    ],
}


def find_markers(
    text
):

    normalized = (
        text.lower()
    )


    results = {}


    for category, markers in (
        SEARCH_MARKERS.items()
    ):

        found = []


        for marker in markers:

            if marker in normalized:

                found.append(
                    marker
                )


        results[
            category
        ] = found


    return results


# ============================================================
# ANALYSE STRUCTURE
# ============================================================

def print_structure_stats(
    soup
):

    print()

    print(
        "STRUCTURE HTML"
    )


    print(
        "-" * 76
    )


    selectors = [

        "main",

        "article",

        "section",

        "h1",

        "h2",

        "h3",

        "dl",

        "dt",

        "dd",

        "table",

        "p",

        "li",
    ]


    for selector in selectors:

        print(
            f"{selector:<10} : "
            f"{len(soup.select(selector))}"
        )


# ============================================================
# HEADINGS
# ============================================================

def print_headings(
    soup
):

    print()

    print(
        "TITRES / SECTIONS HTML"
    )


    print(
        "-" * 76
    )


    headings = []


    for element in soup.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
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


        if text in headings:

            continue


        headings.append(
            text
        )


    if not headings:

        print(
            "[aucun heading détecté]"
        )

        return


    for index, heading in enumerate(
        headings,
        start=1
    ):

        print(
            f"{index:>2}. "
            f"{heading}"
        )


# ============================================================
# META
# ============================================================

def print_meta(
    soup
):

    print()

    print(
        "META"
    )


    print(
        "-" * 76
    )


    interesting = [

        "description",

        "og:title",

        "og:description",

        "og:url",
    ]


    for key in interesting:

        element = soup.find(
            "meta",
            attrs={
                "name":
                    key
            }
        )


        if element is None:

            element = soup.find(
                "meta",
                attrs={
                    "property":
                        key
                }
            )


        if element:

            content = clean_text(
                element.get(
                    "content"
                )
            )


            print(
                f"{key:<15} : "
                f"{content[:1000]}"
            )


# ============================================================
# TEST D'UNE OFFRE
# ============================================================

def test_offer(
    offer
):

    print()

    print(
        "=" * 80
    )


    print(
        f"{offer['id']} | "
        f"{offer['label']}"
    )


    print(
        "=" * 80
    )


    print(
        "URL :",
        offer[
            "url"
        ]
    )


    try:

        response = SESSION.get(

            offer[
                "url"
            ],

            timeout=
                REQUEST_TIMEOUT,

            allow_redirects=
                True,
        )


    except Exception as error:

        print()

        print(
            "❌ ERREUR HTTP"
        )


        print(
            type(
                error
            ).__name__,
            ":",
            error
        )


        return {

            "id":
                offer[
                    "id"
                ],

            "success":
                False,

            "antibot":
                False,

            "error":
                str(
                    error
                ),
        }


    print()

    print(
        "HTTP         :",
        response.status_code
    )


    print(
        "URL finale   :",
        response.url
    )


    print(
        "Content-Type :",
        response.headers.get(
            "Content-Type"
        )
    )


    print(
        "Taille HTML  :",
        len(
            response.text
        )
    )


    html_path = save_html(

        offer[
            "id"
        ],

        response.text
    )


    print(
        "HTML sauvegardé :",
        html_path
    )


    # ========================================================
    # ANTI-BOT
    # ========================================================

    antibot = detect_antibot(
        response.text
    )


    print()

    print(
        "ANTI-BOT :",
        (
            "OUI"
            if antibot
            else
            "NON"
        )
    )


    if antibot:

        print(
            "Marqueurs :",
            ", ".join(
                antibot
            )
        )


    # ========================================================
    # SOUP
    # ========================================================

    soup = build_soup(
        response.text
    )


    title = extract_title(
        soup
    )


    main_text = extract_main_text(
        soup
    )


    print()

    print(
        "Titre détecté :",
        title
    )


    print()

    print(
        "Longueur texte principal :",
        len(
            main_text
        )
    )


    print_structure_stats(
        soup
    )


    print_headings(
        soup
    )


    print_meta(
        soup
    )


    # ========================================================
    # MARQUEURS
    # ========================================================

    markers = find_markers(
        main_text
    )


    print()

    print(
        "MARQUEURS MÉTIER"
    )


    print(
        "-" * 76
    )


    for category, found in (
        markers.items()
    ):

        print(
            f"{category:<12} : ",
            end=""
        )


        if found:

            print(
                ", ".join(
                    found
                )
            )


        else:

            print(
                "NON"
            )


    # ========================================================
    # EXTRAIT
    # ========================================================

    print()

    print(
        "EXTRAIT TEXTE PRINCIPAL"
    )


    print(
        "-" * 76
    )


    print(
        main_text[:10000]
    )


    # ========================================================
    # BILAN
    # ========================================================

    success = (

        response.status_code
        ==
        200

        and

        not antibot

        and

        len(
            main_text
        )
        >=
        500
    )


    return {

        "id":
            offer[
                "id"
            ],

        "success":
            success,

        "status":
            response.status_code,

        "antibot":
            bool(
                antibot
            ),

        "html_length":
            len(
                response.text
            ),

        "text_length":
            len(
                main_text
            ),

        "title":
            title,

        "markers":
            markers,

        "error":
            None,
    }


# ============================================================
# BILAN
# ============================================================

def print_summary(
    results
):

    print()

    print(
        "=" * 80
    )


    print(
        "BILAN DETAIL TRAVAILLERPOUR.BE"
    )


    print(
        "=" * 80
    )


    print()


    for result in results:

        print(
            f"{result['id']:<10} | "
            f"succès="
            f"{'OUI' if result['success'] else 'NON':<3} | "
            f"anti-bot="
            f"{'OUI' if result.get('antibot') else 'NON':<3} | "
            f"HTTP="
            f"{result.get('status', '-')}"
        )


    successes = sum(

        1
        for result
        in results

        if result[
            "success"
        ]
    )


    antibot_count = sum(

        1
        for result
        in results

        if result.get(
            "antibot"
        )
    )


    print()

    print(
        "Tests réussis :",
        successes,
        "/",
        len(
            results
        )
    )


    print(
        "Pages anti-bot :",
        antibot_count
    )


    if successes == len(
        results
    ):

        print()

        print(
            "✅ Les pages détail sont "
            "exploitables avec requests."
        )


        print(
            "→ On peut construire "
            "travaillerpour_detail.py."
        )


    elif antibot_count > 0:

        print()

        print(
            "⚠️ Une protection anti-bot "
            "est active sur les détails."
        )


        print(
            "→ Ne pas construire le parseur "
            "requests avant analyse."
        )


    else:

        print()

        print(
            "⚠️ Les pages répondent mais "
            "le contenu attendu n'est pas complet."
        )


# ============================================================
# MAIN
# ============================================================

def main():

    logger = start_logging()


    try:

        print()

        print(
            "=" * 80
        )


        print(
            " TRAVAILLERPOUR.BE DETAIL - DIAGNOSTIC V1"
        )


        print(
            "=" * 80
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


        results = []


        for offer in TEST_OFFERS:

            result = test_offer(
                offer
            )


            results.append(
                result
            )


        print_summary(
            results
        )


        print()

        print(
            "=" * 80
        )


        print(
            "DIAGNOSTIC TERMINÉ"
        )


        print(
            "=" * 80
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