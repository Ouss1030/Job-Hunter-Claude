"""
JOB HUNTER BELGIUM
TRAVAILLERPOUR.BE - DIAGNOSTIC V1

OBJECTIF
========

Déterminer si travaillerpour.be est directement exploitable
avec requests + BeautifulSoup.

Le script teste :

1. la page principale des offres ;
2. plusieurs variantes de pagination ;
3. la présence de cartes/liens d'offres ;
4. une éventuelle protection anti-bot ;
5. la structure des URLs d'offres ;
6. quelques informations visibles dans la liste.

IMPORTANT
=========

Le script génère AUTOMATIQUEMENT un log TXT complet dans :

    exports/logs/

Exemple :

    exports/logs/
    travaillerpour_diagnostic_20260813_212500.txt

Plus besoin de copier manuellement le terminal.
"""


import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

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


# ============================================================
# LOGGER TERMINAL + TXT
# ============================================================

class Tee:
    """
    Tout ce qui est affiché dans le terminal
    est également écrit dans le fichier TXT.
    """

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
            "travaillerpour_diagnostic_"
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
# CONFIGURATION
# ============================================================

BASE_URL = (
    "https://travaillerpour.be"
)


LIST_URL = (
    "https://travaillerpour.be/fr/jobs"
)


REQUEST_TIMEOUT = 30


TEST_URLS = [

    (
        "PAGE PRINCIPALE",
        LIST_URL
    ),

    (
        "PAGE 0",
        (
            LIST_URL
            +
            "?page=0"
        )
    ),

    (
        "PAGE 1",
        (
            LIST_URL
            +
            "?page=1"
        )
    ),

    (
        "TRI DATE",
        (
            LIST_URL
            +
            "?sort_bef_combine="
            "publicationdate_DESC"
            "&sort_by=publicationdate"
            "&sort_order=DESC"
        )
    ),
]


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

        "Cache-Control":
            "no-cache",

        "Pragma":
            "no-cache",
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
# DÉTECTION ANTI-BOT
# ============================================================

def detect_antibot(
    html
):

    normalized = clean_text(
        html
    ).lower()


    markers = [

        "please enable javascript",

        "support id",

        "testing whether you are a human",

        "what code is in the image",

        "captcha",

        "access denied",

        "request rejected",

        "bot detection",

        "human visitor",
    ]


    detected = []


    for marker in markers:

        if marker in normalized:

            detected.append(
                marker
            )


    return detected


# ============================================================
# URL OFFRE
# ============================================================

def is_job_url(
    url
):

    if not url:

        return False


    try:

        parsed = urlparse(
            url
        )

    except Exception:

        return False


    path = (
        parsed.path
        .rstrip("/")
    )


    # Exemple attendu :
    #
    # /fr/jobs/abc123-data-analyst-mfx

    if not path.startswith(
        "/fr/jobs/"
    ):

        return False


    if path == "/fr/jobs":

        return False


    parts = [
        part
        for part
        in path.split("/")
        if part
    ]


    if len(
        parts
    ) < 3:

        return False


    return True


# ============================================================
# EXTRACTION LIENS
# ============================================================

def extract_job_links(
    soup
):

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


        if not is_job_url(
            absolute_url
        ):

            continue


        title = clean_text(
            link.get_text(
                " ",
                strip=True
            )
        )


        if not title:

            title = (
                absolute_url
                .rstrip("/")
                .split("/")[-1]
            )


        jobs[
            absolute_url
        ] = {
            "title":
                title,

            "url":
                absolute_url,
        }


    return list(
        jobs.values()
    )


# ============================================================
# STATISTIQUES HTML
# ============================================================

def print_html_diagnostics(
    soup,
    html
):

    print()

    print(
        "STATISTIQUES HTML"
    )

    print(
        "-" * 76
    )


    print(
        "Taille HTML             :",
        len(
            html
        )
    )


    print(
        "Nombre de <a>           :",
        len(
            soup.select(
                "a"
            )
        )
    )


    print(
        "Nombre de <article>     :",
        len(
            soup.select(
                "article"
            )
        )
    )


    print(
        "Nombre de <main>        :",
        len(
            soup.select(
                "main"
            )
        )
    )


    print(
        "Nombre de <form>        :",
        len(
            soup.select(
                "form"
            )
        )
    )


    print(
        "Nombre de <input>       :",
        len(
            soup.select(
                "input"
            )
        )
    )


# ============================================================
# REQUÊTE
# ============================================================

def test_url(
    label,
    url
):

    print()

    print(
        "=" * 80
    )

    print(
        label
    )

    print(
        "=" * 80
    )


    print(
        "URL demandée :",
        url
    )


    try:

        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )


    except Exception as error:

        print()

        print(
            "❌ ERREUR REQUESTS"
        )


        print(
            type(
                error
            ).__name__,
            ":",
            error
        )


        return None


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
        "Taille       :",
        len(
            response.text
        )
    )


    antibot = detect_antibot(
        response.text
    )


    print()

    print(
        "ANTI-BOT     :",
        (
            "OUI"
            if antibot
            else
            "NON"
        )
    )


    if antibot:

        print(
            "Marqueurs    :",
            ", ".join(
                antibot
            )
        )


    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )


    print_html_diagnostics(
        soup,
        response.text
    )


    jobs = extract_job_links(
        soup
    )


    print()

    print(
        "LIENS D'OFFRES TROUVÉS"
    )

    print(
        "-" * 76
    )


    print(
        "Nombre :",
        len(
            jobs
        )
    )


    for index, job in enumerate(
        jobs[:30],
        start=1
    ):

        print()

        print(
            f"{index:>2}. "
            f"{job['title']}"
        )


        print(
            "    ",
            job[
                "url"
            ]
        )


    # ========================================================
    # EXTRAIT TEXTE
    # ========================================================

    main = (
        soup.find(
            "main"
        )
        or
        soup.body
        or
        soup
    )


    page_text = clean_text(
        main.get_text(
            " ",
            strip=True
        )
    )


    print()

    print(
        "EXTRAIT DU TEXTE"
    )

    print(
        "-" * 76
    )


    print(
        page_text[:5000]
    )


    return {
        "label":
            label,

        "status":
            response.status_code,

        "url":
            response.url,

        "html_length":
            len(
                response.text
            ),

        "antibot":
            antibot,

        "jobs":
            jobs,
    }


# ============================================================
# COMPARAISON DES PAGES
# ============================================================

def compare_results(
    results
):

    print()

    print(
        "=" * 80
    )

    print(
        "BILAN DIAGNOSTIC TRAVAILLERPOUR.BE"
    )

    print(
        "=" * 80
    )


    valid_results = [
        result
        for result
        in results
        if result
    ]


    print()

    print(
        "Pages testées :",
        len(
            valid_results
        )
    )


    print()


    for result in valid_results:

        print(
            f"{result['label']:<20} | "
            f"HTTP {result['status']:<3} | "
            f"anti-bot="
            f"{'OUI' if result['antibot'] else 'NON':<3} | "
            f"offres={len(result['jobs'])}"
        )


    # ========================================================
    # UNION DES OFFRES
    # ========================================================

    unique_jobs = {}


    for result in valid_results:

        for job in result[
            "jobs"
        ]:

            unique_jobs[
                job[
                    "url"
                ]
            ] = job


    print()

    print(
        "Offres uniques détectées :",
        len(
            unique_jobs
        )
    )


    # ========================================================
    # DIFFÉRENCE PAGE 0 / PAGE 1
    # ========================================================

    page_0 = next(
        (
            result
            for result
            in valid_results
            if result[
                "label"
            ]
            ==
            "PAGE 0"
        ),
        None
    )


    page_1 = next(
        (
            result
            for result
            in valid_results
            if result[
                "label"
            ]
            ==
            "PAGE 1"
        ),
        None
    )


    if (
        page_0
        and
        page_1
    ):

        urls_0 = {
            job[
                "url"
            ]
            for job
            in page_0[
                "jobs"
            ]
        }


        urls_1 = {
            job[
                "url"
            ]
            for job
            in page_1[
                "jobs"
            ]
        }


        print()

        print(
            "Pagination :"
        )


        print(
            "  Page 0 seulement :",
            len(
                urls_0
                -
                urls_1
            )
        )


        print(
            "  Page 1 seulement :",
            len(
                urls_1
                -
                urls_0
            )
        )


        print(
            "  Communes          :",
            len(
                urls_0
                &
                urls_1
            )
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
            "   JOB HUNTER - TRAVAILLERPOUR.BE DIAGNOSTIC V1"
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
            "Le résultat complet sera sauvegardé dans :"
        )


        print(
            logger[
                "path"
            ]
        )


        results = []


        for label, url in (
            TEST_URLS
        ):

            result = test_url(
                label,
                url
            )


            results.append(
                result
            )


        compare_results(
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


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":

    main()