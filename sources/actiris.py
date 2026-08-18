"""
JOB HUNTER BELGIUM
CONNECTEUR ACTIRIS - VERSION 3

OBJECTIF
========

Collecter les offres disponibles via le moteur public Actiris
TOUT EN CONSERVANT LEUR PROVENANCE RÉELLE.

Le moteur Actiris contient plusieurs catégories distinctes :

- ACTIRIS
- VDAB_FOREM
- PARTNER
- HANDICAP

IMPORTANT
=========

"ACTIRIS" reste le CANAL DE COLLECTE.

La provenance réelle est conservée séparément :

    job.source = "ACTIRIS"
    job.collection_channel = "ACTIRIS"
    job.origin_source = "ACTIRIS"
                       ou "VDAB_FOREM"
                       ou "PARTNER"
                       ou "HANDICAP"

Cela permettra plus tard de construire correctement :

raw_jobs
    ↓
déduplication multisource
    ↓
canonical_jobs

sans perdre l'origine réelle d'une annonce.

VERSION 3
=========
- banque de recherche centralisée FR / EN / NL ;
- couverture Data / BI élargie ;
- couverture Chimie / Labo / QC / QA fortement élargie ;
- mêmes concepts de recherche que Forem.
"""


import hashlib
import html
import json
import re
import time

from collections import Counter
from pathlib import Path

import requests

from database.models import JobOffer

from config.profile import (
    get_collection_search_terms,
)


# ============================================================
# API
# ============================================================

API_URL = (
    "https://www.actiris.brussels/"
    "Umbraco/api/OffersApi/GetAllOffers"
)


DETAIL_BASE_URL = (
    "https://www.actiris.brussels/"
    "fr/citoyens/detail-offre-d-emploi/"
)


SEARCH_REFERER = (
    "https://www.actiris.brussels/"
    "fr/citoyens/offres-d-emploi/"
)


REQUEST_TIMEOUT = 30


# ============================================================
# PAGINATION
# ============================================================

DEFAULT_PAGE_SIZE = 50

FALLBACK_PAGE_SIZE = 10

DEFAULT_MAX_PER_KEYWORD = 300


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


DELAY_BETWEEN_PAGES = 0.10

DELAY_BETWEEN_KEYWORDS = 0.20

DELAY_BETWEEN_ORIGINS = 0.05


# ============================================================
# PROVENANCES ACTIRIS
# ============================================================

PROVENANCE_MODES = {

    "ALL": {
        "isOffreActiris":
            False,

        "isOffreVdabForem":
            False,

        "isOfferPartner":
            False,

        "isOffreHandicap":
            False,
    },


    "ACTIRIS": {
        "isOffreActiris":
            True,

        "isOffreVdabForem":
            False,

        "isOfferPartner":
            False,

        "isOffreHandicap":
            False,
    },


    "VDAB_FOREM": {
        "isOffreActiris":
            False,

        "isOffreVdabForem":
            True,

        "isOfferPartner":
            False,

        "isOffreHandicap":
            False,
    },


    "PARTNER": {
        "isOffreActiris":
            False,

        "isOffreVdabForem":
            False,

        "isOfferPartner":
            True,

        "isOffreHandicap":
            False,
    },


    "HANDICAP": {
        "isOffreActiris":
            False,

        "isOffreVdabForem":
            False,

        "isOfferPartner":
            False,

        "isOffreHandicap":
            True,
    },
}


# On collecte séparément les quatre catégories.
# Cela évite qu'un énorme flux PARTNER masque
# les petites catégories ACTIRIS / VDAB_FOREM.

DEFAULT_PROVENANCE_MODES = [
    "ACTIRIS",
    "VDAB_FOREM",
    "PARTNER",
    "HANDICAP",
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


# Nouveau cache pour ne pas mélanger
# avec les anciens résultats Actiris V1.

CACHE_DIR = (
    PROJECT_ROOT
    / "logs"
    / "actiris_search_cache_v2"
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
            "application/json, "
            "text/plain, "
            "*/*"
        ),

        "Accept-Language": (
            "fr-BE,fr;q=0.9,"
            "en;q=0.8,"
            "nl;q=0.7"
        ),

        "Content-Type":
            "application/json",

        "Referer":
            SEARCH_REFERER,
    }
)


# ============================================================
# MOTS-CLÉS
# ============================================================

ACTIRIS_TARGET_SEARCH_TERMS = (
    get_collection_search_terms()
)


# Une occurrence représentative FR / EN / NL par concept.
# Les variantes supplémentaires sont gérées par le matcher V5.
#
# Actiris reste interrogé séparément par provenance :
# ACTIRIS / VDAB_FOREM / PARTNER / HANDICAP.



# ============================================================
# TEXTE
# ============================================================

def clean_text(value):

    if value is None:
        return ""

    value = html.unescape(
        str(
            value
        )
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

def keyword_cache_path(
    keyword,
    provenance_mode
):

    normalized = re.sub(
        r"[^a-zA-Z0-9]+",
        "_",
        keyword.lower()
    ).strip("_")


    provenance_slug = re.sub(
        r"[^a-zA-Z0-9]+",
        "_",
        provenance_mode.lower()
    ).strip("_")


    digest_source = (
        f"{provenance_mode}|{keyword}"
    )


    digest = hashlib.sha1(
        digest_source.encode(
            "utf-8"
        )
    ).hexdigest()[:8]


    filename = (
        f"{provenance_slug}__"
        f"{normalized}__"
        f"{digest}.json"
    )


    return (
        CACHE_DIR
        /
        filename
    )


def save_keyword_cache(
    keyword,
    provenance_mode,
    jobs,
    total
):

    path = keyword_cache_path(
        keyword,
        provenance_mode
    )


    payload = {

        "keyword":
            keyword,

        "provenance_mode":
            provenance_mode,

        "total_reported":
            total,

        "count_saved":
            len(
                jobs
            ),

        "results":
            jobs,
    }


    try:

        with path.open(
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                payload,
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


def load_keyword_cache(
    keyword,
    provenance_mode
):

    path = keyword_cache_path(
        keyword,
        provenance_mode
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


        return {

            "total":
                data.get(
                    "total_reported",
                    0
                ),

            "results":
                data.get(
                    "results",
                    []
                ),
        }


    except Exception:

        return None


# ============================================================
# PAYLOAD
# ============================================================

def build_search_payload(
    keyword,
    page,
    page_size,
    provenance_mode="ALL"
):

    if (
        provenance_mode
        not in PROVENANCE_MODES
    ):

        raise ValueError(
            (
                "Provenance Actiris inconnue : "
                f"{provenance_mode}"
            )
        )


    from_index = (
        (page - 1)
        *
        page_size
    )


    payload = {

        "pageOption": {

            "page":
                page,

            "from":
                from_index,

            "pageSize":
                page_size,
        },


        "offreFilter": {

            "texte":
                keyword,

            "regimesTravail":
                None,

            "dateDerniereModification":
                None,

            "langue":
                None,

            "codesPostal":
                [],

            "codesContrat":
                [],

            "domainesImt":
                [],

            "secteursPanorama":
                [],

            "references":
                None,

            "localisation":
                "Tout",

            "keywordSearchType":
                "Partout",

            "isOffreActiris":
                False,

            "isOffreVdabForem":
                False,

            "isOfferPartner":
                False,

            "isOffreHandicap":
                False,

            "employerFilter":
                [],
        },
    }


    provenance_config = (
        PROVENANCE_MODES[
            provenance_mode
        ]
    )


    for key, value in (
        provenance_config.items()
    ):

        payload[
            "offreFilter"
        ][
            key
        ] = value


    return payload


# ============================================================
# API
# ============================================================

def request_actiris_api(
    payload
):

    last_error = None


    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            response = SESSION.post(
                API_URL,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )


            response.raise_for_status()


            data = response.json()


            if not isinstance(
                data,
                dict
            ):

                raise ValueError(
                    "Réponse Actiris inattendue."
                )


            if (
                "total"
                not in data
                or
                "items"
                not in data
            ):

                raise ValueError(
                    "Champs total/items absents."
                )


            return data


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
# PAGE SIZE
# ============================================================

def get_working_page_size(
    keyword,
    provenance_mode
):

    payload = build_search_payload(
        keyword=
            keyword,

        page=
            1,

        page_size=
            DEFAULT_PAGE_SIZE,

        provenance_mode=
            provenance_mode,
    )


    try:

        data = request_actiris_api(
            payload
        )


        return (
            DEFAULT_PAGE_SIZE,
            data
        )


    except requests.RequestException:

        print(
            "    ⚠️ pageSize=50 refusé."
        )

        print(
            "    ↳ fallback pageSize=10"
        )


    payload = build_search_payload(
        keyword=
            keyword,

        page=
            1,

        page_size=
            FALLBACK_PAGE_SIZE,

        provenance_mode=
            provenance_mode,
    )


    data = request_actiris_api(
        payload
    )


    return (
        FALLBACK_PAGE_SIZE,
        data
    )


# ============================================================
# RECHERCHE MOT-CLÉ + PROVENANCE
# ============================================================

def search_actiris_keyword(
    keyword,
    max_jobs=DEFAULT_MAX_PER_KEYWORD,
    provenance_mode="ALL"
):

    all_jobs = []


    try:

        page_size, first_data = (
            get_working_page_size(
                keyword,
                provenance_mode
            )
        )


    except requests.RequestException as error:

        print(
            "      ❌ API Actiris inaccessible :",
            error
        )


        cached = load_keyword_cache(
            keyword,
            provenance_mode
        )


        if cached is not None:

            cached_jobs = (
                cached[
                    "results"
                ]
            )


            print(
                f"      ♻️ Cache utilisé : "
                f"{len(cached_jobs)} offre(s)"
            )


            return (
                cached_jobs[
                    :max_jobs
                ]
            )


        print(
            "      ⚠️ Aucun cache disponible."
        )


        return []


    total = int(
        first_data.get(
            "total",
            0
        )
        or 0
    )


    first_items = (
        first_data.get(
            "items",
            []
        )
        or []
    )


    all_jobs.extend(
        first_items
    )


    target_count = min(
        total,
        max_jobs
    )


    if len(
        all_jobs
    ) >= target_count:

        result = (
            all_jobs[
                :target_count
            ]
        )


        save_keyword_cache(
            keyword,
            provenance_mode,
            result,
            total
        )


        return result


    page = 2


    while len(
        all_jobs
    ) < target_count:

        payload = build_search_payload(
            keyword=
                keyword,

            page=
                page,

            page_size=
                page_size,

            provenance_mode=
                provenance_mode,
        )


        try:

            data = request_actiris_api(
                payload
            )


        except requests.RequestException as error:

            print(
                "      ⚠️ Pagination interrompue :",
                error
            )

            break


        items = (
            data.get(
                "items",
                []
            )
            or []
        )


        if not items:

            break


        all_jobs.extend(
            items
        )


        if len(
            items
        ) < page_size:

            break


        page += 1


        time.sleep(
            DELAY_BETWEEN_PAGES
        )


    result = (
        all_jobs[
            :target_count
        ]
    )


    save_keyword_cache(
        keyword,
        provenance_mode,
        result,
        total
    )


    return result


# ============================================================
# ENRICHISSEMENT MÉTADONNÉES DE COLLECTE
# ============================================================

def annotate_raw_job(
    raw_job,
    provenance_mode,
    keyword
):

    annotated = dict(
        raw_job
    )


    annotated[
        "_collection_channel"
    ] = "ACTIRIS"


    annotated[
        "_origin_source"
    ] = provenance_mode


    annotated[
        "_search_terms"
    ] = [
        keyword
    ]


    return annotated


# ============================================================
# FUSION DES HITS D'UNE MÊME RÉFÉRENCE
# ============================================================

def merge_raw_job_metadata(
    existing_job,
    new_job
):

    # ========================================================
    # MOTS-CLÉS AYANT TROUVÉ L'OFFRE
    # ========================================================

    existing_terms = set(
        existing_job.get(
            "_search_terms",
            []
        )
        or []
    )


    new_terms = set(
        new_job.get(
            "_search_terms",
            []
        )
        or []
    )


    existing_job[
        "_search_terms"
    ] = sorted(
        existing_terms
        |
        new_terms
    )


    # ========================================================
    # PROVENANCES
    # ========================================================

    existing_origins = set(
        existing_job.get(
            "_origin_sources",
            []
        )
        or []
    )


    existing_single_origin = (
        existing_job.get(
            "_origin_source"
        )
    )


    if existing_single_origin:

        existing_origins.add(
            existing_single_origin
        )


    new_origin = (
        new_job.get(
            "_origin_source"
        )
    )


    if new_origin:

        existing_origins.add(
            new_origin
        )


    existing_job[
        "_origin_sources"
    ] = sorted(
        existing_origins
    )


    if len(
        existing_origins
    ) == 1:

        existing_job[
            "_origin_source"
        ] = next(
            iter(
                existing_origins
            )
        )


    elif len(
        existing_origins
    ) > 1:

        existing_job[
            "_origin_source"
        ] = "MULTI"


    return existing_job


# ============================================================
# RECHERCHE CIBLÉE COMPLÈTE
# ============================================================

def search_targeted_actiris_jobs(
    search_terms=None,
    max_per_keyword=DEFAULT_MAX_PER_KEYWORD,
    provenance_modes=None
):

    if search_terms is None:

        search_terms = (
            ACTIRIS_TARGET_SEARCH_TERMS
        )


    if provenance_modes is None:

        provenance_modes = (
            DEFAULT_PROVENANCE_MODES
        )


    unique_jobs = {}


    source_hit_counter = Counter()


    print()

    print(
        "=" * 76
    )

    print(
        "      RECHERCHE ACTIRIS CIBLÉE V3 - PROVENANCE"
    )

    print(
        "=" * 76
    )

    print()


    total_terms = len(
        search_terms
    )


    for keyword_index, keyword in enumerate(
        search_terms,
        start=1
    ):

        print(
            f"[{keyword_index}/{total_terms}] "
            f"{keyword}"
        )


        keyword_new_count = 0


        for provenance_mode in (
            provenance_modes
        ):

            jobs = search_actiris_keyword(

                keyword=
                    keyword,

                max_jobs=
                    max_per_keyword,

                provenance_mode=
                    provenance_mode,
            )


            origin_new_count = 0


            for raw_job in jobs:

                reference = clean_text(
                    raw_job.get(
                        "reference"
                    )
                )


                if not reference:

                    continue


                annotated = (
                    annotate_raw_job(
                        raw_job,
                        provenance_mode,
                        keyword
                    )
                )


                source_hit_counter[
                    provenance_mode
                ] += 1


                # ============================================
                # NOUVELLE RÉFÉRENCE
                # ============================================

                if (
                    reference
                    not in unique_jobs
                ):

                    annotated[
                        "_origin_sources"
                    ] = [
                        provenance_mode
                    ]


                    unique_jobs[
                        reference
                    ] = annotated


                    origin_new_count += 1

                    keyword_new_count += 1


                # ============================================
                # DÉJÀ TROUVÉE VIA UN AUTRE MOT-CLÉ
                # ============================================

                else:

                    unique_jobs[
                        reference
                    ] = (
                        merge_raw_job_metadata(
                            unique_jobs[
                                reference
                            ],
                            annotated
                        )
                    )


            print(
                f"    {provenance_mode:<12} : "
                f"{len(jobs):>4} récupérée(s) | "
                f"{origin_new_count:>4} nouvelle(s)"
            )


            time.sleep(
                DELAY_BETWEEN_ORIGINS
            )


        print(
            f"    Nouvelles ce mot-clé : "
            f"{keyword_new_count}"
        )


        print(
            f"    Total unique Actiris : "
            f"{len(unique_jobs)}"
        )


        print()


        time.sleep(
            DELAY_BETWEEN_KEYWORDS
        )


    jobs = list(
        unique_jobs.values()
    )


    jobs.sort(
        key=lambda job: (
            job.get(
                "dateModification"
            )
            or
            job.get(
                "dateCreation"
            )
            or
            ""
        ),
        reverse=True
    )


    # ========================================================
    # RÉPARTITION FINALE
    # ========================================================

    origin_counts = Counter(
        job.get(
            "_origin_source",
            "UNKNOWN"
        )
        for job
        in jobs
    )


    print()

    print(
        "=" * 76
    )

    print(
        "                 BILAN ACTIRIS V3"
    )

    print(
        "=" * 76
    )


    print(
        "Mots-clés testés :",
        total_terms
    )


    print(
        "Offres uniques   :",
        len(
            jobs
        )
    )


    print()

    print(
        "Répartition par provenance :"
    )


    for provenance, count in (
        origin_counts.most_common()
    ):

        print(
            f"  {provenance:<15} "
            f"{count}"
        )


    return jobs


# ============================================================
# URL DÉTAIL
# ============================================================

def build_detail_url(
    raw_job
):

    reference = clean_text(
        raw_job.get(
            "reference"
        )
    )


    offer_type = clean_text(
        raw_job.get(
            "typeOffre"
        )
    )


    if not reference:

        return ""


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
# CONVERSION JOBOFFER
# ============================================================

def convert_actiris_job(
    raw_job
):

    reference = clean_text(
        raw_job.get(
            "reference"
        )
    )


    # ========================================================
    # TITRE
    # ========================================================

    title = (
        clean_text(
            raw_job.get(
                "titreFr"
            )
        )
        or
        clean_text(
            raw_job.get(
                "titreNl"
            )
        )
        or
        "Titre inconnu"
    )


    # ========================================================
    # EMPLOYEUR
    # ========================================================

    employer_data = (
        raw_job.get(
            "employeur"
        )
        or {}
    )


    company = (
        clean_text(
            employer_data.get(
                "nomFr"
            )
        )
        or
        clean_text(
            employer_data.get(
                "nomNl"
            )
        )
        or
        "Employeur non précisé"
    )


    # ========================================================
    # LOCALISATION
    # ========================================================

    municipality = (
        clean_text(
            raw_job.get(
                "communeFr"
            )
        )
        or
        clean_text(
            raw_job.get(
                "communeNl"
            )
        )
    )


    postal_code = clean_text(
        raw_job.get(
            "codePostal"
        )
    )


    country_code = clean_text(
        raw_job.get(
            "codePays"
        )
    )


    location_parts = []


    if municipality:

        location_parts.append(
            municipality
        )


    if postal_code:

        location_parts.append(
            postal_code
        )


    if country_code == "BE":

        location_parts.append(
            "Belgique"
        )


    elif country_code:

        location_parts.append(
            country_code
        )


    location_parts = list(
        dict.fromkeys(
            location_parts
        )
    )


    location = (
        ", ".join(
            location_parts
        )
        if location_parts
        else
        "Lieu non précisé"
    )


    # ========================================================
    # CONTRAT
    # ========================================================

    contract_type = (
        clean_text(
            raw_job.get(
                "typeContratLibelle"
            )
        )
        or
        clean_text(
            raw_job.get(
                "dureeContratLibelle"
            )
        )
        or
        clean_text(
            raw_job.get(
                "typeContrat"
            )
        )
        or
        None
    )


    # ========================================================
    # PROVENANCE
    # ========================================================

    origin_source = clean_text(
        raw_job.get(
            "_origin_source"
        )
    ) or "UNKNOWN"


    origin_sources = (
        raw_job.get(
            "_origin_sources"
        )
        or [
            origin_source
        ]
    )


    search_terms = (
        raw_job.get(
            "_search_terms"
        )
        or []
    )


    # ========================================================
    # DESCRIPTION DE BASE
    # ========================================================

    description_parts = [

        "Canal de collecte : Actiris",

        (
            "Origine catalogue Actiris : "
            f"{origin_source}"
        ),

        (
            "Référence Actiris : "
            f"{reference}"
        ),

        (
            "Domaine IMT : "
            f"{clean_text(raw_job.get('codeDomaineImt')) or 'Non précisé'}"
        ),

        (
            "Type offre : "
            f"{clean_text(raw_job.get('typeOffre')) or 'Non précisé'}"
        ),

        (
            "Régime : "
            f"{clean_text(raw_job.get('regimeTravail')) or 'Non précisé'}"
        ),

        (
            "Contrat : "
            f"{contract_type or 'Non précisé'}"
        ),
    ]


    description = "\n".join(
        description_parts
    )


    # ========================================================
    # DATE
    # ========================================================

    date_published = (
        clean_text(
            raw_job.get(
                "dateCreation"
            )
        )
        or
        None
    )


    # ========================================================
    # URL
    # ========================================================

    url = build_detail_url(
        raw_job
    )


    # ========================================================
    # OBJET
    # ========================================================

    job = JobOffer(

        source=
            "ACTIRIS",

        external_id=
            reference,

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
            date_published,

        contract_type=
            contract_type,

        language=
            None,

        salary=
            None,
    )


    # ========================================================
    # MÉTADONNÉES DYNAMIQUES
    # ========================================================

    job.collection_channel = (
        "ACTIRIS"
    )


    job.origin_source = (
        origin_source
    )


    job.origin_sources = list(
        origin_sources
    )


    job.search_terms = list(
        search_terms
    )


    job.actiris_offer_type = clean_text(
        raw_job.get(
            "typeOffre"
        )
    )


    job.actiris_raw_reference = (
        reference
    )


    return job


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    TEST_TERMS = [

        "data analyst",

        "laborantin",

        "technicien de laboratoire",

        "contrôle qualité",

        "quality assurance",

        "pharma",
    ]


    raw_jobs = (
        search_targeted_actiris_jobs(

            search_terms=
                TEST_TERMS,

            max_per_keyword=
                100,
        )
    )


    print()

    print(
        "=" * 76
    )

    print(
        "          30 OFFRES ACTIRIS V3 RÉCENTES"
    )

    print(
        "=" * 76
    )


    for raw_job in (
        raw_jobs[:30]
    ):

        job = convert_actiris_job(
            raw_job
        )


        print()

        print(
            "-" * 76
        )


        print(
            "ID         :",
            job.external_id
        )


        print(
            "Origine    :",
            job.origin_source
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
            "Contrat    :",
            job.contract_type
        )


        print(
            "Date       :",
            job.date_published
        )


        print(
            "URL        :",
            job.url
        )