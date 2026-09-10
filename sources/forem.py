"""
JOB HUNTER BELGIUM
CONNECTEUR FOREM - VERSION 6

Améliorations V6 :
- retries automatiques ;
- délai progressif entre les tentatives ;
- cache local par mot-clé ;
- récupération depuis le cache si l'API devient indisponible ;
- aucune offre déjà récupérée n'est perdue ;
- recherche ciblée titre + métier ;
- localisation complète ;
- déduplication ;
- banque de recherche centralisée FR / EN / NL ;
- couverture élargie Data + Chimie + Labo + QC/QA ;
- conservation des mots-clés ayant trouvé chaque offre.

Objectif :
éviter qu'une panne DNS temporaire d'ODWB fasse disparaître
toutes les offres laboratoire / pharma / quality du classement.
"""

import hashlib
import json
import re
import time

from pathlib import Path

import requests

from database.models import JobOffer

from config.profile import (
    get_collection_search_terms,
)


# ============================================================
# CONFIGURATION API
# ============================================================

API_URL = (
    "https://www.odwb.be/api/explore/v2.1/"
    "catalog/datasets/offres-d-emploi-forem/records"
)

MAX_PAGE_SIZE = 100

REQUEST_TIMEOUT = 30


# ============================================================
# RETRIES
# ============================================================

MAX_RETRIES = 4

RETRY_DELAYS = [
    1,
    2,
    4,
    8,
]

DELAY_BETWEEN_KEYWORDS = 0.20


# ============================================================
# CACHE
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
    / "forem_search_cache"
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
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": (
            "fr-BE,fr;q=0.9,"
            "en;q=0.8,"
            "nl;q=0.7"
        ),
    }
)


# ============================================================
# MOTS-CLÉS
# ============================================================

FOREM_TARGET_SEARCH_TERMS = (
    get_collection_search_terms()
)


# La banque vient de config.profile V5.
#
# Elle contient un représentant FR / EN / NL pour les concepts :
# - Data / BI / reporting / Power BI / SQL / ETL ;
# - technicien chimiste / assistant chimiste / laborantin ;
# - chimie analytique / organique / inorganique / physique ;
# - biochimie / chimie industrielle / chimie fine ;
# - QC / QA / validation / traçabilité / LIMS ;
# - HPLC / GC / UV-Vis / IR / FTIR / RMN-NMR ;
# - chromatographie / titrage / distillation / extraction ;
# - microbiologie / culture cellulaire / PCR / électrophorèse ;
# - environnement / eau / air / sol / déchets chimiques ;
# - pharma / chimie / agroalimentaire / cosmétique ;
# - production / formulation / ISO / GMP / GLP / R&D.
#
# Les acronymes potentiellement ambigus sont représentés avec contexte
# dans config.profile afin de limiter les faux positifs.



# ============================================================
# UTILITAIRE CACHE
# ============================================================

def keyword_cache_path(keyword):
    """
    Génère un fichier cache unique pour chaque recherche.
    """

    normalized = re.sub(
        r"[^a-zA-Z0-9]+",
        "_",
        keyword.lower()
    ).strip("_")

    digest = hashlib.sha1(
        keyword.encode("utf-8")
    ).hexdigest()[:8]

    filename = (
        f"{normalized}_{digest}.json"
    )

    return (
        CACHE_DIR
        / filename
    )


def save_keyword_cache(
    keyword,
    jobs
):
    """
    Sauvegarde les résultats d'un mot-clé.
    """

    path = keyword_cache_path(
        keyword
    )

    data = {
        "keyword": keyword,
        "count": len(jobs),
        "results": jobs,
    }

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
            "    ⚠️ Cache impossible :",
            error
        )

        return False


def load_keyword_cache(keyword):
    """
    Recharge les derniers résultats connus
    pour un mot-clé.
    """

    path = keyword_cache_path(
        keyword
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

        return (
            data.get(
                "results",
                []
            )
        )

    except Exception:

        return None


# ============================================================
# REQUÊTE API AVEC RETRIES
# ============================================================

def request_forem_api(
    params
):
    """
    Effectue une requête vers ODWB.

    En cas de :
    - DNS temporairement indisponible ;
    - connexion réinitialisée ;
    - timeout ;
    - erreur serveur ;

    plusieurs tentatives sont effectuées.
    """

    last_error = None

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            response = SESSION.get(
                API_URL,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()

            return response.json()


        except (
            requests.ConnectionError,
            requests.Timeout,
            requests.HTTPError,
            requests.RequestException,
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
                f"      Nouvelle tentative "
                f"dans {delay}s..."
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
# DERNIÈRES OFFRES
# ============================================================

def get_forem_jobs(
    max_jobs=250
):
    """
    Récupère les dernières offres Forem.
    """

    all_jobs = []

    offset = 0


    while len(all_jobs) < max_jobs:

        remaining = (
            max_jobs
            -
            len(all_jobs)
        )

        page_size = min(
            MAX_PAGE_SIZE,
            remaining
        )


        params = {
            "limit":
                page_size,

            "offset":
                offset,

            "order_by":
                "datedebutdiffusion desc",
        }


        try:

            data = request_forem_api(
                params
            )

        except requests.RequestException as error:

            print(
                "❌ Impossible de récupérer "
                "les offres Forem :",
                error
            )

            break


        jobs = data.get(
            "results",
            []
        )


        if not jobs:
            break


        all_jobs.extend(
            jobs
        )


        print(
            f"Forem : "
            f"{len(all_jobs)} / "
            f"{max_jobs} offres récupérées"
        )


        offset += len(
            jobs
        )


        if len(jobs) < page_size:
            break


    return all_jobs


# ============================================================
# RECHERCHE PAR MOT-CLÉ
# ============================================================

def search_forem_keyword(
    keyword,
    max_jobs=100
):
    """
    Recherche dans :
    - titreoffre
    - metier

    En cas d'échec complet de l'API,
    utilise automatiquement le cache local.
    """

    all_jobs = []

    offset = 0


    safe_keyword = (
        keyword.replace(
            '"',
            '\\"'
        )
    )


    where_clause = (
        f'search('
        f'titreoffre, '
        f'metier, '
        f'"{safe_keyword}"'
        f')'
    )


    api_failed = False


    while len(all_jobs) < max_jobs:

        remaining = (
            max_jobs
            -
            len(all_jobs)
        )

        page_size = min(
            MAX_PAGE_SIZE,
            remaining
        )


        params = {
            "where":
                where_clause,

            "limit":
                page_size,

            "offset":
                offset,

            "order_by":
                "datedebutdiffusion desc",
        }


        try:

            data = request_forem_api(
                params
            )


        except requests.RequestException as error:

            api_failed = True

            print(
                "    ❌ API inaccessible après retries"
            )

            print(
                "       ",
                error
            )

            break


        jobs = data.get(
            "results",
            []
        )


        if not jobs:
            break


        all_jobs.extend(
            jobs
        )


        offset += len(
            jobs
        )


        if len(jobs) < page_size:
            break


    # ========================================================
    # API RÉUSSIE
    # ========================================================

    if not api_failed:

        save_keyword_cache(
            keyword,
            all_jobs
        )

        return all_jobs


    # ========================================================
    # FALLBACK CACHE
    # ========================================================

    cached_jobs = (
        load_keyword_cache(
            keyword
        )
    )


    if cached_jobs is not None:

        print(
            f"    ♻️ Utilisation du cache : "
            f"{len(cached_jobs)} résultat(s)"
        )

        return (
            cached_jobs[
                :max_jobs
            ]
        )


    print(
        "    ⚠️ Aucun cache disponible."
    )

    return []


# ============================================================
# RECHERCHE GLOBALE
# ============================================================

def search_targeted_forem_jobs(
    search_terms=None,
    max_per_keyword=100
):
    """
    Lance toutes les recherches ciblées
    puis déduplique les offres.
    """

    if search_terms is None:

        search_terms = (
            FOREM_TARGET_SEARCH_TERMS
        )


    unique_jobs = {}


    print()
    print(
        "========================================"
    )
    print(
        "   RECHERCHE FOREM CIBLÉE V6"
    )
    print(
        "========================================"
    )
    print()


    total_terms = len(
        search_terms
    )


    successful_terms = 0

    cache_terms = 0

    empty_terms = 0


    for index, keyword in enumerate(
        search_terms,
        start=1
    ):

        print(
            f"[{index}/{total_terms}] "
            f"{keyword}"
        )


        jobs = search_forem_keyword(
            keyword=keyword,
            max_jobs=max_per_keyword
        )


        if jobs:
            successful_terms += 1

        else:
            empty_terms += 1


        new_count = 0


        for job in jobs:

            external_id = str(
                job.get(
                    "numerooffreforem",
                    ""
                )
            )


            if not external_id:
                continue


            if (
                external_id
                not in
                unique_jobs
            ):

                annotated_job = dict(
                    job
                )


                annotated_job[
                    "_search_terms"
                ] = [
                    keyword
                ]


                unique_jobs[
                    external_id
                ] = annotated_job

                new_count += 1


            else:

                existing_terms = set(
                    unique_jobs[
                        external_id
                    ].get(
                        "_search_terms",
                        []
                    )
                    or []
                )


                existing_terms.add(
                    keyword
                )


                unique_jobs[
                    external_id
                ][
                    "_search_terms"
                ] = sorted(
                    existing_terms
                )


        print(
            f"    Résultats       : "
            f"{len(jobs)}"
        )

        print(
            f"    Nouvelles       : "
            f"{new_count}"
        )

        print(
            f"    Total unique    : "
            f"{len(unique_jobs)}"
        )

        print()


        time.sleep(
            DELAY_BETWEEN_KEYWORDS
        )


    # ========================================================
    # LISTE FINALE
    # ========================================================

    jobs = list(
        unique_jobs.values()
    )


    jobs.sort(
        key=lambda job: (
            job.get(
                "datedebutdiffusion"
            )
            or ""
        ),
        reverse=True
    )


    print()
    print(
        "========================================"
    )
    print(
        "        BILAN COLLECTE FOREM"
    )
    print(
        "========================================"
    )

    print(
        "Mots-clés testés :",
        total_terms
    )

    print(
        "Mots-clés avec résultats :",
        successful_terms
    )

    print(
        "Mots-clés sans résultat :",
        empty_terms
    )

    print(
        "Offres uniques :",
        len(jobs)
    )


    return jobs


# ============================================================
# CONVERSION FOREM -> JOBOFFER
# ============================================================

def convert_forem_job(
    raw_job
):
    """
    Convertit une offre Open Data Forem
    en objet JobOffer.
    """

    locations = (
        raw_job.get(
            "lieuxtravaillocalite"
        )
        or []
    )

    regions = (
        raw_job.get(
            "lieuxtravailregion"
        )
        or []
    )

    languages = (
        raw_job.get(
            "langues"
        )
        or []
    )

    sectors = (
        raw_job.get(
            "secteurs"
        )
        or []
    )

    studies = (
        raw_job.get(
            "niveauxetudes"
        )
        or []
    )


    # ========================================================
    # LOCALISATION
    # ========================================================

    location_parts = []


    if locations:

        location_parts.extend(
            locations
        )


    if regions:

        location_parts.extend(
            regions
        )


    location_parts = list(
        dict.fromkeys(
            location_parts
        )
    )


    if location_parts:

        location = ", ".join(
            location_parts
        )

    else:

        location = (
            "Lieu non précisé"
        )


    # ========================================================
    # LANGUES
    # ========================================================

    if languages:

        language = ", ".join(
            languages
        )

    else:

        language = None


    # ========================================================
    # DESCRIPTION OPEN DATA
    # ========================================================

    description_parts = [

        (
            "Métier : "
            f"{raw_job.get('metier') or 'Non précisé'}"
        ),

        (
            "Secteur : "
            f"{', '.join(sectors) or 'Non précisé'}"
        ),

        (
            "Études : "
            f"{', '.join(studies) or 'Non précisées'}"
        ),

        (
            "Expérience : "
            f"{raw_job.get('experiencerequise') or 'Non précisée'}"
        ),

        (
            "Régime : "
            f"{raw_job.get('regimetravail') or 'Non précisé'}"
        ),

        (
            "Source originale : "
            f"{raw_job.get('source') or 'Forem'}"
        ),
    ]


    description = "\n".join(
        description_parts
    )


    # ========================================================
    # JOBOFFER
    # ========================================================

    job = JobOffer(

        source="FOREM",

        external_id=str(
            raw_job.get(
                "numerooffreforem",
                ""
            )
        ),

        title=(
            raw_job.get(
                "titreoffre"
            )
            or
            "Titre inconnu"
        ),

        company=(
            raw_job.get(
                "nomemployeur"
            )
            or
            "Employeur non précisé"
        ),

        location=location,

        description=description,

        url=(
            raw_job.get(
                "url"
            )
            or
            ""
        ),

        date_published=(
            raw_job.get(
                "datedebutdiffusion"
            )
        ),

        contract_type=(
            raw_job.get(
                "typecontrat"
            )
        ),

        language=language,

        salary=None,
    )


    job.collection_channel = (
        "FOREM"
    )


    job.origin_source = (
        "FOREM"
    )


    job.search_terms = list(
        raw_job.get(
            "_search_terms",
            []
        )
        or []
    )


    return job


# ============================================================
# TEST
# ============================================================



# JOBHUNTER_MASTER400_V2_CORE_ROTATION
from sources.unified_discovery import get_source_query_terms
FOREM_TARGET_SEARCH_TERMS = get_source_query_terms(
    "FOREM",
    legacy_core_terms=[],
    rotation_buckets=4,
)

if __name__ == "__main__":

    raw_jobs = (
        search_targeted_forem_jobs(
            max_per_keyword=100
        )
    )


    print()
    print(
        "Nombre final :",
        len(raw_jobs)
    )


    print()
    print(
        "20 offres les plus récentes :"
    )


    for raw_job in (
        raw_jobs[:20]
    ):

        job = (
            convert_forem_job(
                raw_job
            )
        )

        print()
        print(
            "-" * 72
        )

        print(
            "Date       :",
            job.date_published
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
            "URL        :",
            job.url
        )