"""
JOB HUNTER BELGIUM
INTRA-SOURCE DEDUP AUDIT - VERSION 1.0

OBJECTIF
========

Rechercher les doublons potentiels À L'INTÉRIEUR
d'un même collection_channel :

- ACTIRIS vs ACTIRIS
- FOREM vs FOREM
- etc.

IMPORTANT
=========

CE SCRIPT NE MODIFIE RIEN.

Il :
- ne supprime aucune ligne RAW ;
- ne modifie aucun canonical_job ;
- ne fusionne aucune offre.

Il produit uniquement un audit.


POURQUOI
========

Deux annonces peuvent avoir :

    même titre
    même employeur
    même ville

sans être nécessairement la même offre.

Exemple :
plusieurs offres SMALS peuvent avoir exactement
le même intitulé mais correspondre à plusieurs
recrutements différents.

La description détaillée doit donc servir de
preuve supplémentaire.


NIVEAUX
=======

VERY_STRONG
    candidat potentiellement fusionnable plus tard

STRONG
    doublon probable, mais contrôle nécessaire

REVIEW
    ressemblance notable uniquement


LANCEMENT
=========

python -m database.intrasource_audit


LOG
===

exports/logs/
intrasource_audit_YYYYMMDD_HHMMSS.txt
"""


import hashlib
import re
import sys
import unicodedata

from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path


from database.db import (
    DB_PATH,
    get_raw_jobs_for_dedup,
)


# ============================================================
# CONFIG
# ============================================================

MIN_DESCRIPTION_LENGTH = 250

MAX_DESCRIPTION_LENGTH = 8000

MAX_PRINT = 100


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)


LOG_DIR = (
    PROJECT_ROOT
    /
    "exports"
    /
    "logs"
)


LOG_DIR.mkdir(
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

    timestamp = (
        datetime.now()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )


    path = (
        LOG_DIR
        /
        (
            "intrasource_audit_"
            f"{timestamp}.txt"
        )
    )


    file = path.open(
        "w",
        encoding="utf-8"
    )


    stdout = sys.stdout

    stderr = sys.stderr


    sys.stdout = Tee(
        stdout,
        file
    )


    sys.stderr = Tee(
        stderr,
        file
    )


    return {
        "path": path,
        "file": file,
        "stdout": stdout,
        "stderr": stderr,
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
# TEXT
# ============================================================

def clean_text(
    value
):

    if value is None:

        return ""


    return re.sub(
        r"\s+",
        " ",
        str(
            value
        )
    ).strip()


def remove_accents(
    value
):

    value = unicodedata.normalize(
        "NFKD",
        clean_text(
            value
        )
    )


    return "".join(
        character
        for character
        in value
        if not unicodedata.combining(
            character
        )
    )


def normalize_basic(
    value
):

    value = (
        remove_accents(
            value
        )
        .lower()
        .replace(
            "’",
            "'"
        )
    )


    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value
    )


    return re.sub(
        r"\s+",
        " ",
        value
    ).strip()


# ============================================================
# TITLE
# ============================================================

def normalize_title(
    value
):

    value = normalize_basic(
        value
    )


    noise = [
        r"\bh f x\b",
        r"\bm f x\b",
        r"\bm v x\b",
        r"\bhfx\b",
        r"\bmfx\b",
        r"\bmvx\b",
    ]


    for pattern in noise:

        value = re.sub(
            pattern,
            " ",
            value
        )


    return re.sub(
        r"\s+",
        " ",
        value
    ).strip()


# ============================================================
# COMPANY
# ============================================================

COMPANY_NOISE = {
    "sa",
    "nv",
    "bv",
    "sprl",
    "srl",
    "asbl",
    "vzw",
    "belgium",
    "belgie",
    "belgique",
}


def normalize_company(
    value
):

    tokens = (
        normalize_basic(
            value
        )
        .split()
    )


    return " ".join(
        token
        for token
        in tokens
        if token not in COMPANY_NOISE
    )


# ============================================================
# LOCATION
# ============================================================

LOCATION_NOISE = {
    "belgique",
    "belgium",
    "belgie",
    "region",
    "regionale",
    "wallonne",
    "wallon",
    "wallonie",
    "flamande",
    "flamand",
    "vlaanderen",
    "province",
    "du",
    "de",
    "la",
    "le",
}


def location_tokens(
    value
):

    tokens = (
        normalize_basic(
            value
        )
        .split()
    )


    return {
        token
        for token
        in tokens
        if (
            token not in LOCATION_NOISE
            and
            not token.isdigit()
            and
            len(
                token
            ) >= 3
        )
    }


def extract_postal_code(
    value
):

    match = re.search(
        r"\b(\d{4})\b",
        clean_text(
            value
        )
    )


    if match:

        return match.group(
            1
        )


    return ""


# ============================================================
# DESCRIPTION
# ============================================================

def normalized_description(
    job
):

    # Préférence au texte détail explicite.
    detail = clean_text(
        job.get(
            "detail_matching_text"
        )
    )


    if detail:

        text = detail

    else:

        text = clean_text(
            job.get(
                "description"
            )
        )


    return normalize_basic(
        text
    )[
        :MAX_DESCRIPTION_LENGTH
    ]


# ============================================================
# SIMILARITY
# ============================================================

def sequence_similarity(
    value_a,
    value_b
):

    if (
        not value_a
        or
        not value_b
    ):

        return 0.0


    return SequenceMatcher(
        None,
        value_a,
        value_b
    ).ratio()


def token_jaccard(
    value_a,
    value_b
):

    tokens_a = set(
        value_a.split()
    )


    tokens_b = set(
        value_b.split()
    )


    if (
        not tokens_a
        or
        not tokens_b
    ):

        return 0.0


    return (
        len(
            tokens_a
            &
            tokens_b
        )
        /
        len(
            tokens_a
            |
            tokens_b
        )
    )


def description_similarity(
    value_a,
    value_b
):

    if (
        len(
            value_a
        )
        <
        MIN_DESCRIPTION_LENGTH

        or

        len(
            value_b
        )
        <
        MIN_DESCRIPTION_LENGTH
    ):

        return 0.0


    sequence = sequence_similarity(
        value_a,
        value_b
    )


    jaccard = token_jaccard(
        value_a,
        value_b
    )


    return max(
        sequence,
        (
            sequence
            *
            0.60
            +
            jaccard
            *
            0.40
        ),
    )


# ============================================================
# EXACT CONTENT HASH
# ============================================================

def description_hash(
    value
):

    if (
        not value
        or
        len(
            value
        )
        <
        MIN_DESCRIPTION_LENGTH
    ):

        return None


    return hashlib.sha256(
        value.encode(
            "utf-8"
        )
    ).hexdigest()


# ============================================================
# PREPARE
# ============================================================

def prepare_jobs():

    raw_jobs = (
        get_raw_jobs_for_dedup(
            active_only=True
        )
    )


    output = []


    for raw in raw_jobs:

        job = dict(
            raw
        )


        job[
            "_channel"
        ] = clean_text(
            job.get(
                "collection_channel"
            )
        ).upper()


        job[
            "_title"
        ] = normalize_title(
            job.get(
                "title"
            )
        )


        job[
            "_company"
        ] = normalize_company(
            job.get(
                "company"
            )
        )


        job[
            "_location_tokens"
        ] = location_tokens(
            job.get(
                "location"
            )
        )


        job[
            "_postal"
        ] = extract_postal_code(
            job.get(
                "location"
            )
        )


        job[
            "_description"
        ] = normalized_description(
            job
        )


        job[
            "_description_hash"
        ] = description_hash(
            job[
                "_description"
            ]
        )


        output.append(
            job
        )


    return output


# ============================================================
# LOCATION COMPATIBILITY
# ============================================================

def location_similarity(
    job_a,
    job_b
):

    postal_a = job_a[
        "_postal"
    ]


    postal_b = job_b[
        "_postal"
    ]


    if (
        postal_a
        and
        postal_b
    ):

        return (
            1.0
            if postal_a == postal_b
            else 0.0
        )


    tokens_a = job_a[
        "_location_tokens"
    ]


    tokens_b = job_b[
        "_location_tokens"
    ]


    if (
        not tokens_a
        or
        not tokens_b
    ):

        return 0.40


    if not (
        tokens_a
        &
        tokens_b
    ):

        return 0.0


    if (
        tokens_a <= tokens_b
        or
        tokens_b <= tokens_a
    ):

        return 0.98


    return (
        len(
            tokens_a
            &
            tokens_b
        )
        /
        len(
            tokens_a
            |
            tokens_b
        )
    )


# ============================================================
# CANDIDATE BUCKETS
# ============================================================

def build_candidate_pairs(
    jobs
):

    buckets = defaultdict(
        list
    )


    for index, job in enumerate(
        jobs
    ):

        title = job[
            "_title"
        ]


        if len(
            title
        ) < 5:

            continue


        key = (
            job[
                "_channel"
            ],
            title,
        )


        buckets[
            key
        ].append(
            index
        )


    pairs = []


    for (
        channel,
        title
    ), indexes in buckets.items():

        if len(
            indexes
        ) < 2:

            continue


        for position_a in range(
            len(
                indexes
            )
        ):

            for position_b in range(
                position_a + 1,
                len(
                    indexes
                )
            ):

                pairs.append(
                    (
                        indexes[
                            position_a
                        ],
                        indexes[
                            position_b
                        ],
                    )
                )


    return pairs


# ============================================================
# CLASSIFY PAIR
# ============================================================

def classify_pair(
    job_a,
    job_b
):

    title_score = sequence_similarity(
        job_a[
            "_title"
        ],
        job_b[
            "_title"
        ]
    )


    company_score = sequence_similarity(
        job_a[
            "_company"
        ],
        job_b[
            "_company"
        ]
    )


    location_score = location_similarity(
        job_a,
        job_b
    )


    description_score = (
        description_similarity(
            job_a[
                "_description"
            ],
            job_b[
                "_description"
            ]
        )
    )


    exact_description = (
        job_a[
            "_description_hash"
        ]
        is not None

        and

        job_a[
            "_description_hash"
        ]
        ==
        job_b[
            "_description_hash"
        ]
    )


    same_publication_date = (
        clean_text(
            job_a.get(
                "date_published"
            )
        )
        and
        clean_text(
            job_a.get(
                "date_published"
            )
        )
        ==
        clean_text(
            job_b.get(
                "date_published"
            )
        )
    )


    level = None


    # ========================================================
    # VERY STRONG
    #
    # Nous exigeons le contenu comme preuve.
    # ========================================================

    if (
        title_score >= 0.995
        and
        company_score >= 0.97
        and
        location_score >= 0.95
        and
        (
            exact_description
            or
            description_score >= 0.985
        )
    ):

        level = (
            "VERY_STRONG"
        )


    # ========================================================
    # STRONG
    # ========================================================

    elif (
        title_score >= 0.995
        and
        company_score >= 0.95
        and
        location_score >= 0.90
        and
        description_score >= 0.88
    ):

        level = (
            "STRONG"
        )


    # ========================================================
    # REVIEW
    # ========================================================

    elif (
        title_score >= 0.995
        and
        company_score >= 0.90
        and
        location_score >= 0.80
    ):

        level = (
            "REVIEW"
        )


    if level is None:

        return None


    return {
        "level":
            level,

        "job_a":
            job_a,

        "job_b":
            job_b,

        "title_score":
            title_score,

        "company_score":
            company_score,

        "location_score":
            location_score,

        "description_score":
            description_score,

        "exact_description":
            exact_description,

        "same_publication_date":
            bool(
                same_publication_date
            ),
    }


# ============================================================
# AUDIT
# ============================================================

def audit():

    jobs = prepare_jobs()


    pairs = build_candidate_pairs(
        jobs
    )


    results = []


    for index_a, index_b in pairs:

        result = classify_pair(
            jobs[
                index_a
            ],
            jobs[
                index_b
            ]
        )


        if result:

            results.append(
                result
            )


    priority = {
        "VERY_STRONG": 3,
        "STRONG": 2,
        "REVIEW": 1,
    }


    results.sort(
        key=lambda result: (
            priority[
                result[
                    "level"
                ]
            ],
            result[
                "description_score"
            ],
            result[
                "company_score"
            ],
            result[
                "location_score"
            ],
        ),
        reverse=True
    )


    return {
        "jobs":
            jobs,

        "candidate_pairs":
            len(
                pairs
            ),

        "results":
            results,
    }


# ============================================================
# PRINT
# ============================================================

def print_audit(
    audit_result
):

    results = audit_result[
        "results"
    ]


    levels = defaultdict(
        int
    )


    for result in results:

        levels[
            result[
                "level"
            ]
        ] += 1


    print()

    print(
        "=" * 80
    )


    print(
        "     JOB HUNTER - INTRA-SOURCE DEDUP AUDIT V1"
    )


    print(
        "=" * 80
    )


    print()

    print(
        "SQLite              :",
        DB_PATH
    )


    print(
        "RAW actifs          :",
        len(
            audit_result[
                "jobs"
            ]
        )
    )


    print(
        "Paires testées      :",
        audit_result[
            "candidate_pairs"
        ]
    )


    print()

    print(
        "VERY_STRONG         :",
        levels[
            "VERY_STRONG"
        ]
    )


    print(
        "STRONG              :",
        levels[
            "STRONG"
        ]
    )


    print(
        "REVIEW              :",
        levels[
            "REVIEW"
        ]
    )


    print()

    print(
        "=" * 80
    )


    print(
        "CANDIDATS"
    )


    print(
        "=" * 80
    )


    for position, result in enumerate(
        results[
            :MAX_PRINT
        ],
        start=1
    ):

        job_a = result[
            "job_a"
        ]


        job_b = result[
            "job_b"
        ]


        print()

        print(
            f"[{position}] "
            f"{result['level']}"
        )


        print(
            "    CHANNEL :",
            job_a[
                "_channel"
            ]
        )


        print(
            "    SCORES  : "
            f"T={result['title_score']:.3f} | "
            f"C={result['company_score']:.3f} | "
            f"L={result['location_score']:.3f} | "
            f"D={result['description_score']:.3f}"
        )


        print(
            "    DESC EXACTE :",
            (
                "OUI"
                if result[
                    "exact_description"
                ]
                else
                "NON"
            )
        )


        print(
            "    DATE IDENTIQUE:",
            (
                "OUI"
                if result[
                    "same_publication_date"
                ]
                else
                "NON"
            )
        )


        print()

        print(
            "    A :",
            job_a.get(
                "source_external_id"
            ),
            "|",
            job_a.get(
                "title"
            )
        )


        print(
            "       ",
            job_a.get(
                "company"
            ),
            "|",
            job_a.get(
                "location"
            )
        )


        print()

        print(
            "    B :",
            job_b.get(
                "source_external_id"
            ),
            "|",
            job_b.get(
                "title"
            )
        )


        print(
            "       ",
            job_b.get(
                "company"
            ),
            "|",
            job_b.get(
                "location"
            )
        )


    print()

    print(
        "=" * 80
    )


    print(
        "INTERPRETATION"
    )


    print(
        "=" * 80
    )


    print()

    print(
        "VERY_STRONG = seuls candidats que nous "
        "envisagerons pour une future fusion automatique."
    )


    print(
        "STRONG      = probable doublon, mais aucune "
        "fusion automatique pour l'instant."
    )


    print(
        "REVIEW      = même intitulé / entreprise / lieu "
        "sans preuve de contenu suffisante."
    )


    print()

    print(
        "✅ Ce script n'a modifié ni raw_jobs "
        "ni canonical_jobs."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    logger = start_logging()


    try:

        print()

        print(
            "TXT automatique :"
        )


        print(
            logger[
                "path"
            ]
        )


        result = audit()


        print_audit(
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