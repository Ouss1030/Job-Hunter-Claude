"""
JOB HUNTER BELGIUM
CONNECTEUR ACTIRIS - VERSION 3.2 - ADAPTIVE + INTERNAL PARALLEL V1

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
import concurrent.futures
import threading
import html
import json
import os
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


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ACTIRIS_SCHEDULER_CONFIG_PATH = (
    PROJECT_ROOT
    /
    "config"
    /
    "actiris_scheduler.json"
)
ACTIRIS_SCHEDULER_STATE_PATH = (
    PROJECT_ROOT
    /
    "logs"
    /
    "actiris_scheduler_state.json"
)

ACTIRIS_PERFORMANCE_CONFIG_PATH = (
    PROJECT_ROOT
    /
    "config"
    /
    "actiris_performance.json"
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
# ADAPTIVE SCHEDULER V1
# ============================================================

def _scheduler_read_json(
    path,
    default
):

    try:

        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(
            payload,
            dict
        ):

            return payload

    except Exception:

        pass


    return default


def _scheduler_write_json(
    path,
    payload
):

    try:

        path.parent.mkdir(
            parents=True,
            exist_ok=True
        )


        temp_path = (
            path.with_suffix(
                path.suffix
                +
                ".tmp"
            )
        )


        temp_path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2
            )
            +
            "\n",
            encoding="utf-8"
        )


        temp_path.replace(
            path
        )


        return True


    except Exception as error:

        print(
            "⚠️ ACTIRIS SCHEDULER - "
            "state write failed :",
            error
        )


        return False


def _scheduler_config():

    return (
        _scheduler_read_json(
            ACTIRIS_SCHEDULER_CONFIG_PATH,
            {}
        )
    )


def _scheduler_state():

    return (
        _scheduler_read_json(
            ACTIRIS_SCHEDULER_STATE_PATH,
            {
                "version": 1,
                "rotation_cursor": 0,
                "last_full_sweep_epoch": 0.0,
            }
        )
    )


def _scheduler_env_profile():

    return str(
        os.environ.get(
            "JOBHUNTER_ACTIRIS_PROFILE",
            ""
        )
    ).strip().lower()


def _scheduler_full_due(
    config,
    state,
    now_epoch
):

    try:

        interval_days = float(
            config.get(
                "full_sweep_interval_days",
                7
            )
            or
            7
        )

    except Exception:

        interval_days = 7.0


    try:

        last_full = float(
            state.get(
                "last_full_sweep_epoch",
                0.0
            )
            or
            0.0
        )

    except Exception:

        last_full = 0.0


    interval_seconds = (
        max(
            1.0,
            interval_days
        )
        *
        86400.0
    )


    return (
        last_full <= 0.0
        or
        (
            now_epoch
            -
            last_full
        )
        >=
        interval_seconds
    )


def get_actiris_scheduler_plan(
    now_epoch=None,
    profile_override=None
):

    config = (
        _scheduler_config()
    )


    state = (
        _scheduler_state()
    )


    if now_epoch is None:

        now_epoch = (
            time.time()
        )


    now_epoch = float(
        now_epoch
    )


    override = str(
        profile_override
        or
        _scheduler_env_profile()
    ).strip().lower()


    enabled = bool(
        config.get(
            "enabled",
            False
        )
    )


    valid_profiles = {
        "legacy",
        "full",
        "core",
        "adaptive",
    }


    if override in valid_profiles:

        requested = override


    elif not enabled:

        requested = "legacy"


    else:

        requested = str(
            config.get(
                "mode",
                "adaptive"
            )
            or
            "adaptive"
        ).strip().lower()


        if requested not in valid_profiles:

            requested = "adaptive"


    core_terms = [
        str(
            term
        ).strip()
        for term
        in (
            config.get(
                "core_terms"
            )
            or
            []
        )
        if str(
            term
        ).strip()
    ]


    secondary_terms = [
        str(
            term
        ).strip()
        for term
        in (
            config.get(
                "secondary_terms"
            )
            or
            []
        )
        if str(
            term
        ).strip()
    ]


    # Malformed config => historical full coverage.
    if (
        len(
            core_terms
        )
        <
        90
        or
        len(
            set(
                core_terms
                +
                secondary_terms
            )
        )
        <
        190
    ):

        requested = "legacy"


    regular_provenances = (
        config.get(
            "regular_provenances"
        )
        or
        [
            "ACTIRIS",
            "VDAB_FOREM",
            "PARTNER",
        ]
    )


    full_provenances = (
        config.get(
            "full_provenances"
        )
        or
        DEFAULT_PROVENANCE_MODES
    )


    regular_provenances = [
        str(
            value
        ).strip()
        for value
        in regular_provenances
        if str(
            value
        ).strip()
    ]


    full_provenances = [
        str(
            value
        ).strip()
        for value
        in full_provenances
        if str(
            value
        ).strip()
    ]


    try:

        rotation_buckets = max(
            1,
            int(
                config.get(
                    "rotation_buckets",
                    4
                )
                or
                4
            )
        )

    except Exception:

        rotation_buckets = 4


    try:

        rotation_cursor = int(
            state.get(
                "rotation_cursor",
                0
            )
            or
            0
        )

    except Exception:

        rotation_cursor = 0


    rotation_bucket = (
        rotation_cursor
        %
        rotation_buckets
    )


    full_due = (
        _scheduler_full_due(
            config,
            state,
            now_epoch
        )
    )


    if requested == "legacy":

        profile = "LEGACY"

        terms = list(
            ACTIRIS_TARGET_SEARCH_TERMS
        )

        provenances = list(
            DEFAULT_PROVENANCE_MODES
        )

        secondary_selected = []


    elif (
        requested == "full"
        or
        (
            requested == "adaptive"
            and
            full_due
        )
    ):

        profile = "FULL"

        terms = list(
            ACTIRIS_TARGET_SEARCH_TERMS
        )

        provenances = list(
            full_provenances
        )

        secondary_selected = list(
            secondary_terms
        )


    elif requested == "core":

        profile = "CORE"

        terms = list(
            core_terms
        )

        provenances = list(
            regular_provenances
        )

        secondary_selected = []


    else:

        profile = "ADAPTIVE"

        secondary_selected = [
            term
            for index, term
            in enumerate(
                secondary_terms
            )
            if (
                index
                %
                rotation_buckets
            )
            ==
            rotation_bucket
        ]


        terms = list(
            dict.fromkeys(
                core_terms
                +
                secondary_selected
            )
        )


        provenances = list(
            regular_provenances
        )


    return {
        "version": 1,
        "enabled": enabled,
        "requested": requested.upper(),
        "profile": profile,
        "terms": terms,
        "provenances": provenances,
        "core_count": len(
            core_terms
        ),
        "secondary_total": len(
            secondary_terms
        ),
        "secondary_selected": (
            secondary_selected
        ),
        "secondary_selected_count": len(
            secondary_selected
        ),
        "rotation_buckets": (
            rotation_buckets
        ),
        "rotation_bucket": (
            rotation_bucket
        ),
        "rotation_cursor": (
            rotation_cursor
        ),
        "full_due": bool(
            full_due
        ),
        "full_sweep_interval_days": float(
            config.get(
                "full_sweep_interval_days",
                7
            )
            or
            7
        ),
    }


def _commit_actiris_scheduler_plan(
    plan
):

    profile = str(
        (
            plan
            or
            {}
        ).get(
            "profile",
            ""
        )
    ).upper()


    if profile not in {
        "ADAPTIVE",
        "FULL",
    }:

        return


    state = (
        _scheduler_state()
    )


    state[
        "version"
    ] = 1


    state[
        "last_success_epoch"
    ] = time.time()


    state[
        "last_success_profile"
    ] = profile


    if profile == "ADAPTIVE":

        try:

            cursor = int(
                state.get(
                    "rotation_cursor",
                    0
                )
                or
                0
            )

        except Exception:

            cursor = 0


        state[
            "rotation_cursor"
        ] = (
            cursor
            +
            1
        )


        state[
            "last_rotation_bucket"
        ] = int(
            (
                plan
                or
                {}
            ).get(
                "rotation_bucket",
                0
            )
            or
            0
        )


    elif profile == "FULL":

        state[
            "last_full_sweep_epoch"
        ] = time.time()


    _scheduler_write_json(
        ACTIRIS_SCHEDULER_STATE_PATH,
        state
    )


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

def _new_actiris_session():

    session = requests.Session()

    session.headers.update(
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

    return session


SESSION = _new_actiris_session()
_ACTIRIS_THREAD_LOCAL = threading.local()


def _actiris_session():

    session = getattr(
        _ACTIRIS_THREAD_LOCAL,
        "session",
        None
    )

    if session is None:

        session = _new_actiris_session()

        _ACTIRIS_THREAD_LOCAL.session = session

    return session


def _actiris_internal_worker_count(
    override=None
):

    if override is not None:

        try:

            return max(
                1,
                min(
                    3,
                    int(
                        override
                    )
                )
            )

        except Exception:

            return 1

    env_value = str(
        os.environ.get(
            "JOBHUNTER_ACTIRIS_INTERNAL_WORKERS",
            ""
        )
        or
        ""
    ).strip()

    if env_value:

        try:

            return max(
                1,
                min(
                    3,
                    int(
                        env_value
                    )
                )
            )

        except Exception:

            pass

    config = _scheduler_read_json(
        ACTIRIS_PERFORMANCE_CONFIG_PATH,
        {}
    )

    try:

        return max(
            1,
            min(
                3,
                int(
                    config.get(
                        "internal_workers",
                        1
                    )
                    or
                    1
                )
            )
        )

    except Exception:

        return 1


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

            response = _actiris_session().post(
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

def _search_actiris_keyword_bundle(
    keyword,
    max_per_keyword,
    provenance_modes
):

    results = []

    for provenance_mode in (
        provenance_modes
    ):

        jobs = search_actiris_keyword(
            keyword=keyword,
            max_jobs=max_per_keyword,
            provenance_mode=provenance_mode,
        )

        results.append(
            (
                provenance_mode,
                jobs,
            )
        )

        time.sleep(
            DELAY_BETWEEN_ORIGINS
        )

    time.sleep(
        DELAY_BETWEEN_KEYWORDS
    )

    return (
        keyword,
        results,
    )


def search_targeted_actiris_jobs(
    search_terms=None,
    max_per_keyword=DEFAULT_MAX_PER_KEYWORD,
    provenance_modes=None,
    internal_workers=None
):

    scheduler_plan = None


    if (
        search_terms is None
        and
        provenance_modes is None
    ):

        scheduler_plan = (
            get_actiris_scheduler_plan()
        )


        search_terms = (
            scheduler_plan[
                "terms"
            ]
        )


        provenance_modes = (
            scheduler_plan[
                "provenances"
            ]
        )


        print()

        print(
            "ACTIRIS SCHEDULER | "
            f"profile={scheduler_plan['profile']} | "
            f"terms={len(search_terms)} | "
            f"core={scheduler_plan['core_count']} | "
            f"secondary="
            f"{scheduler_plan['secondary_selected_count']}/"
            f"{scheduler_plan['secondary_total']} | "
            f"bucket="
            f"{scheduler_plan['rotation_bucket'] + 1}/"
            f"{scheduler_plan['rotation_buckets']} | "
            f"full_due={int(scheduler_plan['full_due'])}"
        )


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


    internal_workers = (
        _actiris_internal_worker_count(
            internal_workers
        )
    )

    print(
        "ACTIRIS INTERNAL PARALLEL | "
        f"workers={internal_workers} | "
        f"terms={total_terms}"
    )

    if internal_workers <= 1:

        keyword_bundles = []

        for fetch_index, keyword in enumerate(
            search_terms,
            start=1
        ):

            keyword_bundles.append(
                _search_actiris_keyword_bundle(
                    keyword,
                    max_per_keyword,
                    provenance_modes,
                )
            )

            print(
                "ACTIRIS FETCH PROGRESS | "
                f"{fetch_index}/{total_terms} | "
                f"workers={internal_workers}"
            )

    else:

        keyword_bundles = [
            None
            for _ in search_terms
        ]

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=internal_workers,
            thread_name_prefix="actiris-term",
        ) as executor:

            future_to_index = {
                executor.submit(
                    _search_actiris_keyword_bundle,
                    keyword,
                    max_per_keyword,
                    provenance_modes,
                ): index
                for index, keyword in enumerate(
                    search_terms
                )
            }

            completed = 0

            for future in concurrent.futures.as_completed(
                future_to_index
            ):

                index = future_to_index[
                    future
                ]

                keyword_bundles[
                    index
                ] = future.result()

                completed += 1

                print(
                    "ACTIRIS FETCH PROGRESS | "
                    f"{completed}/{total_terms} | "
                    f"workers={internal_workers}"
                )

    for keyword_index, bundle in enumerate(
        keyword_bundles,
        start=1
    ):

        keyword, provenance_results = bundle

        print(
            f"[{keyword_index}/{total_terms}] "
            f"{keyword}"
        )

        keyword_new_count = 0

        for provenance_mode, jobs in (
            provenance_results
        ):

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

        print(
            f"    Nouvelles ce mot-clé : "
            f"{keyword_new_count}"
        )

        print(
            f"    Total unique Actiris : "
            f"{len(unique_jobs)}"
        )

        print()


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


    if scheduler_plan is not None:

        _commit_actiris_scheduler_plan(
            scheduler_plan
        )


        print()

        print(
            "ACTIRIS SCHEDULER DONE | "
            f"profile={scheduler_plan['profile']} | "
            f"rotation_bucket="
            f"{scheduler_plan['rotation_bucket'] + 1}/"
            f"{scheduler_plan['rotation_buckets']} | "
            f"jobs={len(jobs)}"
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



# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1
from sources.unified_discovery import get_master_search_terms
ACTIRIS_TARGET_SEARCH_TERMS = get_master_search_terms()



# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1_1_CV_POOL
from sources.unified_discovery import get_source_query_terms as _ud11_query_terms
from sources.unified_discovery import get_master_search_terms as _ud11_master_terms

_ud11_original_get_actiris_scheduler_plan = get_actiris_scheduler_plan

def get_actiris_scheduler_plan(*args, **kwargs):
    plan = dict(_ud11_original_get_actiris_scheduler_plan(*args, **kwargs))
    legacy_live = list(plan.get("terms") or [])
    active = _ud11_query_terms(
        "ACTIRIS",
        legacy_live,
        rotation_buckets=4,
    )
    plan["terms"] = active
    plan["master_term_count"] = len(_ud11_master_terms())
    plan["master_active_count"] = len(active)
    plan["master_pool_enabled"] = True
    return plan

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