"""
JOB HUNTER BELGIUM
DATABASE - VERSION 2.1

OBJECTIF
========

Conserver DEUX niveaux de données distincts :

1. RAW LISTING SNAPSHOT
   --------------------
   Ce que la source nous a donné au moment de la collecte,
   AVANT enrichissement.

2. ENRICHED SNAPSHOT
   -----------------
   L'objet après récupération de la page détail,
   extraction des champs, éligibilité, etc.


ARCHITECTURE
============

SOURCE
    ↓
raw listing
    ↓
raw_payload_json
    ↓
DETAIL / ENRICHISSEMENT
    ↓
enriched_payload_json
    +
detail_matching_text


REGLE FONDAMENTALE
==================

Un enrichissement ne doit JAMAIS écraser :

    raw_payload_json

Le snapshot RAW doit rester disponible indépendamment
de la version enrichie.


HISTORIQUE PAR RUN
==================

raw_job_run_items conserve maintenant :

    initial_snapshot_json
        = snapshot au moment de la collecte

    final_snapshot_json
        = snapshot après enrichissement

    snapshot_json
        = dernière version observée dans le run


COMPATIBILITE
=============

DATABASE V2.1 migre automatiquement la base V2 existante.

Aucune table n'est supprimée.

L'ancienne table :

    jobs

reste intacte.


IMPORTANT POUR LE RUN V9 DEJA EFFECTUE
======================================

Le premier run V9 a déjà remplacé certains raw_payload_json
par leurs versions enrichies.

Ce snapshot historique précis ne peut pas être reconstruit.

CEPENDANT :

au prochain :

    python main.py

la collecte initiale rafraîchira correctement raw_payload_json
avec les nouvelles données LISTING,

puis l'enrichissement sera stocké séparément dans :

    enriched_payload_json

À partir de ce moment, le problème sera définitivement corrigé.
"""


import hashlib
import json
import sqlite3
import sys
import uuid

from datetime import (
    date,
    datetime,
)

from pathlib import Path


# ============================================================
# VERSION
# ============================================================

DATABASE_VERSION = "2.1"


# ============================================================
# PATHS
# ============================================================

DATABASE_DIR = (
    Path(__file__)
    .resolve()
    .parent
)


PROJECT_ROOT = (
    DATABASE_DIR
    .parent
)


DB_PATH = (
    DATABASE_DIR
    /
    "jobs.db"
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
            "database_v21_test_"
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
# TIME
# ============================================================

def now_iso():

    return (
        datetime.now()
        .astimezone()
        .isoformat(
            timespec="seconds"
        )
    )


# ============================================================
# TEXT
# ============================================================

def clean_text(
    value
):

    if value is None:

        return None


    value = str(
        value
    ).strip()


    if not value:

        return None


    return value


# ============================================================
# JSON
# ============================================================

def json_default(
    value
):

    if isinstance(
        value,
        (
            datetime,
            date,
        )
    ):

        return value.isoformat()


    if isinstance(
        value,
        Path
    ):

        return str(
            value
        )


    if isinstance(
        value,
        set
    ):

        return sorted(
            value
        )


    return str(
        value
    )


def to_json(
    value
):

    return json.dumps(
        value,
        ensure_ascii=False,
        default=json_default,
        sort_keys=True
    )


# ============================================================
# BOOL
# ============================================================

def bool_to_int(
    value
):

    if value is None:

        return None


    return (
        1
        if bool(
            value
        )
        else 0
    )


# ============================================================
# CONNECTION
# ============================================================

def get_connection():

    connection = sqlite3.connect(
        DB_PATH,
        timeout=30
    )


    connection.row_factory = (
        sqlite3.Row
    )


    connection.execute(
        "PRAGMA foreign_keys = ON"
    )


    connection.execute(
        "PRAGMA busy_timeout = 30000"
    )


    return connection


# ============================================================
# TABLE INFO
# ============================================================

def table_exists(
    connection,
    table_name
):

    row = connection.execute(
        """
        SELECT name

        FROM sqlite_master

        WHERE
            type = 'table'
            AND name = ?
        """,
        (
            table_name,
        )
    ).fetchone()


    return (
        row is not None
    )


def get_existing_columns(
    connection,
    table_name
):

    if not table_exists(
        connection,
        table_name
    ):

        return set()


    rows = connection.execute(
        f"""
        PRAGMA table_info(
            {table_name}
        )
        """
    ).fetchall()


    return {
        row[
            "name"
        ]
        for row
        in rows
    }


def ensure_column(
    connection,
    table_name,
    column_name,
    column_definition
):

    columns = get_existing_columns(
        connection,
        table_name
    )


    if column_name in columns:

        return False


    connection.execute(
        f"""
        ALTER TABLE {table_name}

        ADD COLUMN
        {column_name}
        {column_definition}
        """
    )


    return True


# ============================================================
# DATABASE INIT
# ============================================================

def init_db():

    DATABASE_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    connection = (
        get_connection()
    )


    try:

        connection.execute(
            "PRAGMA journal_mode = WAL"
        )


        # ====================================================
        # COLLECTION RUNS
        # ====================================================

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS collection_runs (

                run_id TEXT PRIMARY KEY,

                database_version TEXT NOT NULL,

                started_at TEXT NOT NULL,

                finished_at TEXT,

                status TEXT NOT NULL,

                total_collected INTEGER DEFAULT 0,

                inserted_count INTEGER DEFAULT 0,

                updated_count INTEGER DEFAULT 0,

                error_count INTEGER DEFAULT 0,

                notes TEXT
            )
            """
        )


        # ====================================================
        # RAW JOBS
        # ====================================================

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_jobs (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                collection_channel TEXT NOT NULL,

                origin_source TEXT,

                source TEXT NOT NULL,

                source_external_id TEXT NOT NULL,

                title TEXT,

                company TEXT,

                location TEXT,

                description TEXT,

                url TEXT,

                date_published TEXT,

                contract_type TEXT,

                language TEXT,

                salary TEXT,

                date_collected TEXT,

                first_seen TEXT NOT NULL,

                last_seen TEXT NOT NULL,

                last_run_id TEXT,

                is_active INTEGER NOT NULL DEFAULT 1,

                detail_enrichment_attempted INTEGER,

                detail_enrichment_success INTEGER,

                detail_matching_text_length INTEGER,

                detail_from_cache INTEGER,

                detail_enrichment_error TEXT,

                detail_matching_text TEXT,

                degree_requirement TEXT,

                experience_requirement TEXT,

                application_deadline TEXT,

                restriction_text TEXT,

                source_eligibility_status TEXT,

                source_eligibility_reason TEXT,

                origin_sources_json TEXT,

                search_terms_json TEXT,

                raw_payload_json TEXT,

                enriched_payload_json TEXT,

                FOREIGN KEY (
                    last_run_id
                )
                REFERENCES collection_runs (
                    run_id
                ),

                UNIQUE (
                    collection_channel,
                    source_external_id
                )
            )
            """
        )


        # ====================================================
        # RUN ITEMS
        # ====================================================

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_job_run_items (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                run_id TEXT NOT NULL,

                raw_job_id INTEGER NOT NULL,

                observed_at TEXT NOT NULL,

                source_eligibility_status TEXT,

                detail_enrichment_success INTEGER,

                initial_snapshot_json TEXT,

                final_snapshot_json TEXT,

                snapshot_json TEXT,

                FOREIGN KEY (
                    run_id
                )
                REFERENCES collection_runs (
                    run_id
                )
                ON DELETE CASCADE,

                FOREIGN KEY (
                    raw_job_id
                )
                REFERENCES raw_jobs (
                    id
                )
                ON DELETE CASCADE,

                UNIQUE (
                    run_id,
                    raw_job_id
                )
            )
            """
        )


        # ====================================================
        # MIGRATION V2 -> V2.1
        # ====================================================

        ensure_column(
            connection,
            "raw_jobs",
            "detail_matching_text",
            "TEXT"
        )


        ensure_column(
            connection,
            "raw_jobs",
            "enriched_payload_json",
            "TEXT"
        )


        ensure_column(
            connection,
            "raw_job_run_items",
            "initial_snapshot_json",
            "TEXT"
        )


        ensure_column(
            connection,
            "raw_job_run_items",
            "final_snapshot_json",
            "TEXT"
        )


        # ====================================================
        # INDEXES
        # ====================================================

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_raw_jobs_source

            ON raw_jobs (
                source
            )
            """
        )


        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_raw_jobs_collection_channel

            ON raw_jobs (
                collection_channel
            )
            """
        )


        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_raw_jobs_origin_source

            ON raw_jobs (
                origin_source
            )
            """
        )


        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_raw_jobs_company

            ON raw_jobs (
                company
            )
            """
        )


        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_raw_jobs_title

            ON raw_jobs (
                title
            )
            """
        )


        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_raw_jobs_active

            ON raw_jobs (
                is_active
            )
            """
        )


        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_raw_jobs_last_seen

            ON raw_jobs (
                last_seen
            )
            """
        )


        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_raw_jobs_eligibility

            ON raw_jobs (
                source_eligibility_status
            )
            """
        )


        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_raw_job_run_items_run

            ON raw_job_run_items (
                run_id
            )
            """
        )


        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_raw_job_run_items_job

            ON raw_job_run_items (
                raw_job_id
            )
            """
        )


        connection.commit()


    finally:

        connection.close()


# ============================================================
# RUN
# ============================================================

def generate_run_id():

    timestamp = (
        datetime.now()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )


    suffix = (
        uuid.uuid4()
        .hex[:8]
    )


    return (
        f"RUN_{timestamp}_{suffix}"
    )


def start_collection_run(
    notes=None,
    connection=None
):

    owns_connection = (
        connection is None
    )


    if owns_connection:

        connection = (
            get_connection()
        )


    run_id = generate_run_id()


    connection.execute(
        """
        INSERT INTO collection_runs (

            run_id,

            database_version,

            started_at,

            status,

            notes

        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            run_id,
            DATABASE_VERSION,
            now_iso(),
            "RUNNING",
            clean_text(
                notes
            ),
        )
    )


    if owns_connection:

        connection.commit()

        connection.close()


    return run_id


def finish_collection_run(
    run_id,
    total_collected,
    inserted_count,
    updated_count,
    error_count,
    status=None,
    connection=None
):

    owns_connection = (
        connection is None
    )


    if owns_connection:

        connection = (
            get_connection()
        )


    if status is None:

        status = (
            "COMPLETED"
            if error_count == 0
            else
            "COMPLETED_WITH_ERRORS"
        )


    connection.execute(
        """
        UPDATE collection_runs

        SET
            finished_at = ?,

            status = ?,

            total_collected = ?,

            inserted_count = ?,

            updated_count = ?,

            error_count = ?

        WHERE run_id = ?
        """,
        (
            now_iso(),
            status,
            int(
                total_collected
            ),
            int(
                inserted_count
            ),
            int(
                updated_count
            ),
            int(
                error_count
            ),
            run_id,
        )
    )


    if owns_connection:

        connection.commit()

        connection.close()


# ============================================================
# EXTERNAL ID
# ============================================================

def ensure_external_id(
    job
):

    external_id = clean_text(
        getattr(
            job,
            "external_id",
            None
        )
    )


    if external_id:

        return external_id


    url = clean_text(
        getattr(
            job,
            "url",
            None
        )
    )


    if url:

        digest = hashlib.sha1(
            url.encode(
                "utf-8"
            )
        ).hexdigest()[:20]


        return (
            f"URL_{digest}"
        )


    raise ValueError(
        (
            "Impossible de sauvegarder l'offre : "
            "external_id et url absents."
        )
    )


# ============================================================
# LIST HELPERS
# ============================================================

def extract_search_terms(
    job
):

    value = getattr(
        job,
        "search_terms",
        None
    )


    if value is None:

        value = getattr(
            job,
            "_search_terms",
            None
        )


    if value is None:

        return []


    if isinstance(
        value,
        str
    ):

        return [
            value
        ]


    if isinstance(
        value,
        (
            list,
            tuple,
            set,
        )
    ):

        return [
            str(
                item
            )
            for item
            in value
            if item is not None
        ]


    return [
        str(
            value
        )
    ]


def extract_origin_sources(
    job
):

    value = getattr(
        job,
        "origin_sources",
        None
    )


    if value is None:

        origin = getattr(
            job,
            "origin_source",
            None
        )


        if origin:

            return [
                str(
                    origin
                )
            ]


        source = getattr(
            job,
            "source",
            None
        )


        if source:

            return [
                str(
                    source
                )
            ]


        return []


    if isinstance(
        value,
        str
    ):

        return [
            value
        ]


    if isinstance(
        value,
        (
            list,
            tuple,
            set,
        )
    ):

        return [
            str(
                item
            )
            for item
            in value
            if item is not None
        ]


    return [
        str(
            value
        )
    ]


# ============================================================
# SNAPSHOT
# ============================================================

def job_to_snapshot(
    job
):

    try:

        data = dict(
            vars(
                job
            )
        )

    except Exception:

        data = {}


    base_fields = [
        "source",
        "external_id",
        "title",
        "company",
        "location",
        "description",
        "url",
        "date_published",
        "contract_type",
        "language",
        "salary",
        "date_collected",
    ]


    for field in base_fields:

        if field not in data:

            data[
                field
            ] = getattr(
                job,
                field,
                None
            )


    return data


# ============================================================
# PHASE
# ============================================================

def is_enriched_job(
    job
):
    """
    Un JobOffer fraîchement converti depuis la liste
    n'a normalement pas encore :

        detail_enrichment_attempted = True

    Une offre enrichie l'a.

    Cette distinction permet de protéger raw_payload_json.
    """

    return (
        getattr(
            job,
            "detail_enrichment_attempted",
            None
        )
        is True
    )


# ============================================================
# DETAIL STATUS
# ============================================================

def get_detail_status(
    job
):

    attempted = getattr(
        job,
        "detail_enrichment_attempted",
        None
    )


    success = getattr(
        job,
        "detail_enrichment_success",
        None
    )


    if attempted is not True:

        return (
            "NOT_ATTEMPTED"
        )


    if success is True:

        return (
            "SUCCESS"
        )


    return (
        "FAILED"
    )


# ============================================================
# INTERNAL UPSERT
# ============================================================

def _upsert_raw_job(
    connection,
    job,
    run_id=None
):

    source = clean_text(
        getattr(
            job,
            "source",
            None
        )
    )


    if not source:

        raise ValueError(
            "JobOffer.source est obligatoire."
        )


    collection_channel = clean_text(
        getattr(
            job,
            "collection_channel",
            None
        )
    )


    if not collection_channel:

        collection_channel = source


    origin_source = clean_text(
        getattr(
            job,
            "origin_source",
            None
        )
    )


    if not origin_source:

        origin_source = source


    source_external_id = (
        ensure_external_id(
            job
        )
    )


    # ========================================================
    # EXISTING ROW
    # ========================================================

    previous = connection.execute(
        """
        SELECT id

        FROM raw_jobs

        WHERE
            collection_channel = ?
            AND
            source_external_id = ?
        """,
        (
            collection_channel,
            source_external_id,
        )
    ).fetchone()


    inserted = (
        previous is None
    )


    enriched = is_enriched_job(
        job
    )


    observed_at = now_iso()


    snapshot = job_to_snapshot(
        job
    )


    snapshot_json = to_json(
        snapshot
    )


    # ========================================================
    # RAW VS ENRICHED PAYLOAD
    # ========================================================

    if enriched:

        # Si une ligne existe déjà :
        # NE PAS toucher au raw_payload_json.
        #
        # Cas exceptionnel :
        # l'objet enrichi arrive avant la collecte RAW.
        # On conserve alors quand même une copie pour éviter
        # une valeur totalement vide.

        if inserted:

            raw_payload_json = (
                snapshot_json
            )

        else:

            raw_payload_json = (
                None
            )


        enriched_payload_json = (
            snapshot_json
        )


    else:

        # Listing brut :
        # il est autorisé à rafraîchir raw_payload_json
        # lors d'un nouveau run.

        raw_payload_json = (
            snapshot_json
        )


        enriched_payload_json = (
            None
        )


    origin_sources_json = to_json(
        extract_origin_sources(
            job
        )
    )


    search_terms_json = to_json(
        extract_search_terms(
            job
        )
    )


    date_collected = clean_text(
        getattr(
            job,
            "date_collected",
            None
        )
    )


    if not date_collected:

        date_collected = (
            observed_at
        )


    detail_matching_text = clean_text(
        getattr(
            job,
            "detail_matching_text",
            None
        )
    )


    # Dans le pipeline actuel le texte détail est
    # principalement intégré à description.
    # Si aucun attribut dédié n'existe, on ne fabrique
    # rien artificiellement.

    params = {

        "collection_channel":
            collection_channel,

        "origin_source":
            origin_source,

        "source":
            source,

        "source_external_id":
            source_external_id,

        "title":
            clean_text(
                getattr(
                    job,
                    "title",
                    None
                )
            ),

        "company":
            clean_text(
                getattr(
                    job,
                    "company",
                    None
                )
            ),

        "location":
            clean_text(
                getattr(
                    job,
                    "location",
                    None
                )
            ),

        "description":
            clean_text(
                getattr(
                    job,
                    "description",
                    None
                )
            ),

        "url":
            clean_text(
                getattr(
                    job,
                    "url",
                    None
                )
            ),

        "date_published":
            clean_text(
                getattr(
                    job,
                    "date_published",
                    None
                )
            ),

        "contract_type":
            clean_text(
                getattr(
                    job,
                    "contract_type",
                    None
                )
            ),

        "language":
            clean_text(
                getattr(
                    job,
                    "language",
                    None
                )
            ),

        "salary":
            clean_text(
                getattr(
                    job,
                    "salary",
                    None
                )
            ),

        "date_collected":
            date_collected,

        "first_seen":
            observed_at,

        "last_seen":
            observed_at,

        "last_run_id":
            run_id,

        "is_active":
            1,

        "detail_enrichment_attempted":
            bool_to_int(
                getattr(
                    job,
                    "detail_enrichment_attempted",
                    None
                )
            ),

        "detail_enrichment_success":
            bool_to_int(
                getattr(
                    job,
                    "detail_enrichment_success",
                    None
                )
            ),

        "detail_matching_text_length":
            getattr(
                job,
                "detail_matching_text_length",
                None
            ),

        "detail_from_cache":
            bool_to_int(
                getattr(
                    job,
                    "detail_from_cache",
                    None
                )
            ),

        "detail_enrichment_error":
            clean_text(
                getattr(
                    job,
                    "detail_enrichment_error",
                    None
                )
            ),

        "detail_matching_text":
            detail_matching_text,

        "degree_requirement":
            clean_text(
                getattr(
                    job,
                    "degree_requirement",
                    None
                )
            ),

        "experience_requirement":
            clean_text(
                getattr(
                    job,
                    "experience_requirement",
                    None
                )
            ),

        "application_deadline":
            clean_text(
                getattr(
                    job,
                    "application_deadline",
                    None
                )
            ),

        "restriction_text":
            clean_text(
                getattr(
                    job,
                    "restriction",
                    None
                )
            ),

        "source_eligibility_status":
            clean_text(
                getattr(
                    job,
                    "source_eligibility_status",
                    None
                )
            ),

        "source_eligibility_reason":
            clean_text(
                getattr(
                    job,
                    "source_eligibility_reason",
                    None
                )
            ),

        "origin_sources_json":
            origin_sources_json,

        "search_terms_json":
            search_terms_json,

        "raw_payload_json":
            raw_payload_json,

        "enriched_payload_json":
            enriched_payload_json,
    }


    # ========================================================
    # RAW JOB UPSERT
    # ========================================================

    connection.execute(
        """
        INSERT INTO raw_jobs (

            collection_channel,
            origin_source,
            source,
            source_external_id,

            title,
            company,
            location,
            description,
            url,

            date_published,
            contract_type,
            language,
            salary,
            date_collected,

            first_seen,
            last_seen,
            last_run_id,
            is_active,

            detail_enrichment_attempted,
            detail_enrichment_success,
            detail_matching_text_length,
            detail_from_cache,
            detail_enrichment_error,
            detail_matching_text,

            degree_requirement,
            experience_requirement,
            application_deadline,
            restriction_text,

            source_eligibility_status,
            source_eligibility_reason,

            origin_sources_json,
            search_terms_json,

            raw_payload_json,
            enriched_payload_json

        )
        VALUES (

            :collection_channel,
            :origin_source,
            :source,
            :source_external_id,

            :title,
            :company,
            :location,
            :description,
            :url,

            :date_published,
            :contract_type,
            :language,
            :salary,
            :date_collected,

            :first_seen,
            :last_seen,
            :last_run_id,
            :is_active,

            :detail_enrichment_attempted,
            :detail_enrichment_success,
            :detail_matching_text_length,
            :detail_from_cache,
            :detail_enrichment_error,
            :detail_matching_text,

            :degree_requirement,
            :experience_requirement,
            :application_deadline,
            :restriction_text,

            :source_eligibility_status,
            :source_eligibility_reason,

            :origin_sources_json,
            :search_terms_json,

            :raw_payload_json,
            :enriched_payload_json
        )

        ON CONFLICT (
            collection_channel,
            source_external_id
        )

        DO UPDATE SET

            origin_source =
                excluded.origin_source,

            source =
                excluded.source,

            title =
                excluded.title,

            company =
                excluded.company,

            location =
                excluded.location,

            description =
                excluded.description,

            url =
                excluded.url,

            date_published =
                excluded.date_published,

            contract_type =
                excluded.contract_type,

            language =
                excluded.language,

            salary =
                excluded.salary,

            date_collected =
                excluded.date_collected,

            last_seen =
                excluded.last_seen,

            last_run_id =
                excluded.last_run_id,

            is_active =
                1,

            -- Les indicateurs d'enrichissement suivent le meme sort que le
            -- texte : ils ne sont ecrases que par une VRAIE tentative.
            --
            -- Sans COALESCE, une simple recollecte les remettait a NULL. Le
            -- texte, lui, etait bien preserve juste en dessous — d'ou une
            -- incoherence silencieuse : l'offre gardait sa description mais
            -- redevenait « jamais tentee ». Consequence mesuree le
            -- 9 septembre : 2 023 lignes enrichies signalees comme vides,
            -- que l'outil de rattrapage aurait retelechargees pour rien, et
            -- une couverture affichee a 69 % au lieu de la valeur reelle.
            detail_enrichment_attempted =
                COALESCE(
                    excluded.detail_enrichment_attempted,
                    raw_jobs.detail_enrichment_attempted
                ),

            detail_enrichment_success =
                COALESCE(
                    excluded.detail_enrichment_success,
                    raw_jobs.detail_enrichment_success
                ),

            detail_matching_text_length =
                COALESCE(
                    excluded.detail_matching_text_length,
                    raw_jobs.detail_matching_text_length
                ),

            detail_from_cache =
                COALESCE(
                    excluded.detail_from_cache,
                    raw_jobs.detail_from_cache
                ),

            -- L'erreur, elle, est bien remplacee : une nouvelle collecte
            -- reussie doit effacer le message d'echec precedent.
            detail_enrichment_error =
                excluded.detail_enrichment_error,

            detail_matching_text =
                COALESCE(
                    excluded.detail_matching_text,
                    raw_jobs.detail_matching_text
                ),

            degree_requirement =
                excluded.degree_requirement,

            experience_requirement =
                excluded.experience_requirement,

            application_deadline =
                excluded.application_deadline,

            restriction_text =
                excluded.restriction_text,

            source_eligibility_status =
                excluded.source_eligibility_status,

            source_eligibility_reason =
                excluded.source_eligibility_reason,

            origin_sources_json =
                excluded.origin_sources_json,

            search_terms_json =
                excluded.search_terms_json,

            raw_payload_json =
                CASE

                    WHEN
                        excluded.raw_payload_json
                        IS NOT NULL

                    THEN
                        excluded.raw_payload_json

                    ELSE
                        raw_jobs.raw_payload_json

                END,

            enriched_payload_json =
                CASE

                    WHEN
                        excluded.enriched_payload_json
                        IS NOT NULL

                    THEN
                        excluded.enriched_payload_json

                    ELSE
                        raw_jobs.enriched_payload_json

                END
        """,
        params
    )


    # ========================================================
    # GET RAW ID
    # ========================================================

    row = connection.execute(
        """
        SELECT id

        FROM raw_jobs

        WHERE
            collection_channel = ?
            AND
            source_external_id = ?
        """,
        (
            collection_channel,
            source_external_id,
        )
    ).fetchone()


    if row is None:

        raise RuntimeError(
            (
                "Impossible de retrouver raw_job "
                "après UPSERT."
            )
        )


    raw_job_id = int(
        row[
            "id"
        ]
    )


    # ========================================================
    # RUN OBSERVATION
    # ========================================================

    if run_id:

        if enriched:

            initial_snapshot_json = (
                None
            )


            final_snapshot_json = (
                snapshot_json
            )


        else:

            initial_snapshot_json = (
                snapshot_json
            )


            final_snapshot_json = (
                None
            )


        connection.execute(
            """
            INSERT INTO raw_job_run_items (

                run_id,
                raw_job_id,
                observed_at,

                source_eligibility_status,

                detail_enrichment_success,

                initial_snapshot_json,

                final_snapshot_json,

                snapshot_json

            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?
            )

            ON CONFLICT (
                run_id,
                raw_job_id
            )

            DO UPDATE SET

                observed_at =
                    excluded.observed_at,

                source_eligibility_status =
                    COALESCE(
                        excluded.source_eligibility_status,
                        raw_job_run_items.source_eligibility_status
                    ),

                detail_enrichment_success =
                    COALESCE(
                        excluded.detail_enrichment_success,
                        raw_job_run_items.detail_enrichment_success
                    ),

                initial_snapshot_json =
                    COALESCE(
                        raw_job_run_items.initial_snapshot_json,
                        excluded.initial_snapshot_json
                    ),

                final_snapshot_json =
                    COALESCE(
                        excluded.final_snapshot_json,
                        raw_job_run_items.final_snapshot_json
                    ),

                snapshot_json =
                    excluded.snapshot_json
            """,
            (
                run_id,

                raw_job_id,

                observed_at,

                clean_text(
                    getattr(
                        job,
                        "source_eligibility_status",
                        None
                    )
                ),

                bool_to_int(
                    getattr(
                        job,
                        "detail_enrichment_success",
                        None
                    )
                ),

                initial_snapshot_json,

                final_snapshot_json,

                snapshot_json,
            )
        )


    return {

        "raw_job_id":
            raw_job_id,

        "inserted":
            inserted,

        "updated":
            not inserted,

        "collection_channel":
            collection_channel,

        "source_external_id":
            source_external_id,

        "detail_status":
            get_detail_status(
                job
            ),

        "phase":
            (
                "ENRICHED"
                if enriched
                else
                "RAW"
            ),
    }


# ============================================================
# PUBLIC SINGLE UPSERT
# ============================================================

def upsert_raw_job(
    job,
    run_id=None
):

    init_db()


    connection = (
        get_connection()
    )


    try:

        result = _upsert_raw_job(
            connection,
            job,
            run_id
        )


        connection.commit()


        return result


    except Exception:

        connection.rollback()

        raise


    finally:

        connection.close()


# ============================================================
# FULL COLLECTION SAVE
# ============================================================

def save_raw_jobs(
    jobs,
    notes=None
):

    init_db()


    jobs = list(
        jobs
    )


    connection = (
        get_connection()
    )


    run_id = None


    inserted_count = 0

    updated_count = 0

    error_count = 0

    errors = []


    try:

        run_id = start_collection_run(
            notes=
                notes,
            connection=
                connection
        )


        connection.commit()


        for index, job in enumerate(
            jobs,
            start=1
        ):

            savepoint = (
                f"job_{index}"
            )


            connection.execute(
                f"SAVEPOINT {savepoint}"
            )


            try:

                result = _upsert_raw_job(
                    connection,
                    job,
                    run_id
                )


                if result[
                    "inserted"
                ]:

                    inserted_count += 1


                else:

                    updated_count += 1


                connection.execute(
                    f"RELEASE SAVEPOINT {savepoint}"
                )


            except Exception as error:

                error_count += 1


                try:

                    connection.execute(
                        (
                            f"ROLLBACK TO SAVEPOINT "
                            f"{savepoint}"
                        )
                    )


                    connection.execute(
                        f"RELEASE SAVEPOINT {savepoint}"
                    )


                except Exception:

                    pass


                errors.append(
                    {
                        "index":
                            index,

                        "source":
                            clean_text(
                                getattr(
                                    job,
                                    "source",
                                    None
                                )
                            ),

                        "external_id":
                            clean_text(
                                getattr(
                                    job,
                                    "external_id",
                                    None
                                )
                            ),

                        "title":
                            clean_text(
                                getattr(
                                    job,
                                    "title",
                                    None
                                )
                            ),

                        "error":
                            str(
                                error
                            ),
                    }
                )


        finish_collection_run(
            run_id=
                run_id,

            total_collected=
                len(
                    jobs
                ),

            inserted_count=
                inserted_count,

            updated_count=
                updated_count,

            error_count=
                error_count,

            connection=
                connection
        )


        connection.commit()


    except Exception:

        connection.rollback()


        if run_id:

            try:

                connection.execute(
                    """
                    UPDATE collection_runs

                    SET
                        finished_at = ?,
                        status = ?

                    WHERE run_id = ?
                    """,
                    (
                        now_iso(),
                        "FAILED",
                        run_id,
                    )
                )


                connection.commit()


            except Exception:

                pass


        raise


    finally:

        connection.close()


    return {
        "run_id":
            run_id,

        "total":
            len(
                jobs
            ),

        "inserted":
            inserted_count,

        "updated":
            updated_count,

        "errors":
            error_count,

        "error_details":
            errors,
    }


# ============================================================
# COMPATIBILITY
# ============================================================

def save_job(
    job
):

    return upsert_raw_job(
        job
    )


def insert_job(
    job
):

    return upsert_raw_job(
        job
    )


def save_jobs(
    jobs
):

    return save_raw_jobs(
        jobs,
        notes=(
            "save_jobs compatibility call"
        )
    )


# ============================================================
# COUNT
# ============================================================

def count_raw_jobs(
    source=None
):

    init_db()


    connection = (
        get_connection()
    )


    try:

        if source:

            row = connection.execute(
                """
                SELECT COUNT(*) AS count

                FROM raw_jobs

                WHERE source = ?
                """,
                (
                    source,
                )
            ).fetchone()


        else:

            row = connection.execute(
                """
                SELECT COUNT(*) AS count

                FROM raw_jobs
                """
            ).fetchone()


        return int(
            row[
                "count"
            ]
        )


    finally:

        connection.close()


# ============================================================
# GET RAW JOBS
# ============================================================

def get_raw_jobs_for_dedup(
    active_only=True
):

    init_db()


    connection = (
        get_connection()
    )


    try:

        if active_only:

            rows = connection.execute(
                """
                SELECT *

                FROM raw_jobs

                WHERE is_active = 1

                ORDER BY id ASC
                """
            ).fetchall()


        else:

            rows = connection.execute(
                """
                SELECT *

                FROM raw_jobs

                ORDER BY id ASC
                """
            ).fetchall()


        return [
            dict(
                row
            )
            for row
            in rows
        ]


    finally:

        connection.close()


def get_raw_job(
    raw_job_id
):

    init_db()


    connection = (
        get_connection()
    )


    try:

        row = connection.execute(
            """
            SELECT *

            FROM raw_jobs

            WHERE id = ?
            """,
            (
                raw_job_id,
            )
        ).fetchone()


        if row is None:

            return None


        return dict(
            row
        )


    finally:

        connection.close()


# ============================================================
# LATEST RUN
# ============================================================

def get_latest_collection_run():

    init_db()


    connection = (
        get_connection()
    )


    try:

        row = connection.execute(
            """
            SELECT *

            FROM collection_runs

            ORDER BY started_at DESC

            LIMIT 1
            """
        ).fetchone()


        if row is None:

            return None


        return dict(
            row
        )


    finally:

        connection.close()


# ============================================================
# TABLE COLUMNS
# ============================================================

def get_table_columns(
    table_name
):

    init_db()


    connection = (
        get_connection()
    )


    try:

        if not table_exists(
            connection,
            table_name
        ):

            return []


        rows = connection.execute(
            f"""
            PRAGMA table_info(
                {table_name}
            )
            """
        ).fetchall()


        return [
            dict(
                row
            )
            for row
            in rows
        ]


    finally:

        connection.close()


# ============================================================
# PAYLOAD STATS
# ============================================================

def get_payload_stats(
    connection
):

    row = connection.execute(
        """
        SELECT

            COUNT(*) AS total,

            SUM(
                CASE

                    WHEN raw_payload_json
                         IS NOT NULL

                    THEN 1

                    ELSE 0

                END
            ) AS raw_payload_count,

            SUM(
                CASE

                    WHEN enriched_payload_json
                         IS NOT NULL

                    THEN 1

                    ELSE 0

                END
            ) AS enriched_payload_count,

            SUM(
                CASE

                    WHEN detail_enrichment_attempted = 1

                    THEN 1

                    ELSE 0

                END
            ) AS enrichment_attempted_count,

            SUM(
                CASE

                    WHEN detail_enrichment_success = 1

                    THEN 1

                    ELSE 0

                END
            ) AS enrichment_success_count

        FROM raw_jobs
        """
    ).fetchone()


    return {
        "total":
            int(
                row[
                    "total"
                ]
                or 0
            ),

        "raw_payload_count":
            int(
                row[
                    "raw_payload_count"
                ]
                or 0
            ),

        "enriched_payload_count":
            int(
                row[
                    "enriched_payload_count"
                ]
                or 0
            ),

        "enrichment_attempted_count":
            int(
                row[
                    "enrichment_attempted_count"
                ]
                or 0
            ),

        "enrichment_success_count":
            int(
                row[
                    "enrichment_success_count"
                ]
                or 0
            ),
    }


# ============================================================
# DATABASE SUMMARY
# ============================================================

def get_database_summary():

    init_db()


    connection = (
        get_connection()
    )


    try:

        tables = {}


        for table_name in [
            "jobs",
            "collection_runs",
            "raw_jobs",
            "raw_job_run_items",
        ]:

            exists = table_exists(
                connection,
                table_name
            )


            if not exists:

                tables[
                    table_name
                ] = {
                    "exists": False,
                    "rows": None,
                }

                continue


            row = connection.execute(
                f"""
                SELECT COUNT(*) AS count

                FROM {table_name}
                """
            ).fetchone()


            tables[
                table_name
            ] = {
                "exists":
                    True,

                "rows":
                    int(
                        row[
                            "count"
                        ]
                    ),
            }


        source_counts = []


        if table_exists(
            connection,
            "raw_jobs"
        ):

            rows = connection.execute(
                """
                SELECT
                    source,
                    COUNT(*) AS count

                FROM raw_jobs

                GROUP BY source

                ORDER BY
                    count DESC,
                    source ASC
                """
            ).fetchall()


            source_counts = [
                {
                    "source":
                        row[
                            "source"
                        ],

                    "count":
                        int(
                            row[
                                "count"
                            ]
                        ),
                }
                for row
                in rows
            ]


        latest_run = connection.execute(
            """
            SELECT *

            FROM collection_runs

            ORDER BY started_at DESC

            LIMIT 1
            """
        ).fetchone()


        payload_stats = (
            get_payload_stats(
                connection
            )
        )


        return {
            "database_path":
                str(
                    DB_PATH
                ),

            "database_version":
                DATABASE_VERSION,

            "tables":
                tables,

            "source_counts":
                source_counts,

            "payload_stats":
                payload_stats,

            "latest_run":
                (
                    dict(
                        latest_run
                    )
                    if latest_run
                    else None
                ),
        }


    finally:

        connection.close()


# ============================================================
# RUN SNAPSHOT STATS
# ============================================================

def get_run_snapshot_stats(
    connection
):

    row = connection.execute(
        """
        SELECT

            COUNT(*) AS total,

            SUM(
                CASE

                    WHEN initial_snapshot_json
                         IS NOT NULL

                    THEN 1

                    ELSE 0

                END
            ) AS initial_count,

            SUM(
                CASE

                    WHEN final_snapshot_json
                         IS NOT NULL

                    THEN 1

                    ELSE 0

                END
            ) AS final_count

        FROM raw_job_run_items
        """
    ).fetchone()


    return {
        "total":
            int(
                row[
                    "total"
                ]
                or 0
            ),

        "initial_count":
            int(
                row[
                    "initial_count"
                ]
                or 0
            ),

        "final_count":
            int(
                row[
                    "final_count"
                ]
                or 0
            ),
    }


# ============================================================
# TEST
# ============================================================

def print_database_test():

    print()

    print(
        "=" * 80
    )


    print(
        "       JOB HUNTER - DATABASE V2.1 TEST"
    )


    print(
        "=" * 80
    )


    print()

    print(
        "Version :",
        DATABASE_VERSION
    )


    print(
        "DB      :",
        DB_PATH
    )


    print()

    print(
        "Migration / initialisation..."
    )


    init_db()


    print(
        "✅ init_db() terminé"
    )


    summary = (
        get_database_summary()
    )


    # ========================================================
    # TABLES
    # ========================================================

    print()

    print(
        "=" * 80
    )


    print(
        "TABLES"
    )


    print(
        "=" * 80
    )


    for table_name, info in (
        summary[
            "tables"
        ].items()
    ):

        print()

        print(
            f"{table_name:<25} "
            f"| existe="
            f"{'OUI' if info['exists'] else 'NON':<3} "
            f"| lignes={info['rows']}"
        )


    # ========================================================
    # REQUIRED COLUMNS
    # ========================================================

    raw_columns = {
        item[
            "name"
        ]
        for item
        in get_table_columns(
            "raw_jobs"
        )
    }


    run_columns = {
        item[
            "name"
        ]
        for item
        in get_table_columns(
            "raw_job_run_items"
        )
    }


    print()

    print(
        "=" * 80
    )


    print(
        "MIGRATION V2.1"
    )


    print(
        "=" * 80
    )


    required_raw_columns = [
        "raw_payload_json",
        "enriched_payload_json",
        "detail_matching_text",
    ]


    required_run_columns = [
        "initial_snapshot_json",
        "final_snapshot_json",
        "snapshot_json",
    ]


    print()


    for column in required_raw_columns:

        print(
            f"raw_jobs.{column:<30} : "
            f"{'OK' if column in raw_columns else 'MANQUANT'}"
        )


    for column in required_run_columns:

        print(
            f"run_items.{column:<29} : "
            f"{'OK' if column in run_columns else 'MANQUANT'}"
        )


    # ========================================================
    # CURRENT PAYLOADS
    # ========================================================

    payload = summary[
        "payload_stats"
    ]


    print()

    print(
        "=" * 80
    )


    print(
        "PAYLOADS ACTUELS"
    )


    print(
        "=" * 80
    )


    print()

    print(
        "raw_jobs total              :",
        payload[
            "total"
        ]
    )


    print(
        "raw_payload_json présent    :",
        payload[
            "raw_payload_count"
        ]
    )


    print(
        "enriched_payload_json       :",
        payload[
            "enriched_payload_count"
        ]
    )


    print(
        "enrichissement tenté        :",
        payload[
            "enrichment_attempted_count"
        ]
    )


    print(
        "enrichissement réussi       :",
        payload[
            "enrichment_success_count"
        ]
    )


    # ========================================================
    # RUN SNAPSHOT STATS
    # ========================================================

    connection = (
        get_connection()
    )


    try:

        run_stats = (
            get_run_snapshot_stats(
                connection
            )
        )


    finally:

        connection.close()


    print()

    print(
        "Snapshots par run :"
    )


    print(
        "  observations totales      :",
        run_stats[
            "total"
        ]
    )


    print(
        "  initial_snapshot_json      :",
        run_stats[
            "initial_count"
        ]
    )


    print(
        "  final_snapshot_json        :",
        run_stats[
            "final_count"
        ]
    )


    # ========================================================
    # SOURCES
    # ========================================================

    print()

    print(
        "=" * 80
    )


    print(
        "RAW JOBS PAR SOURCE"
    )


    print(
        "=" * 80
    )


    print()


    for item in (
        summary[
            "source_counts"
        ]
    ):

        print(
            f"{item['source']:<20} "
            f"{item['count']}"
        )


    # ========================================================
    # VALIDATION
    # ========================================================

    missing_raw = [
        column

        for column
        in required_raw_columns

        if column not in raw_columns
    ]


    missing_run = [
        column

        for column
        in required_run_columns

        if column not in run_columns
    ]


    print()

    print(
        "=" * 80
    )


    print(
        "VALIDATION"
    )


    print(
        "=" * 80
    )


    print()


    if (
        missing_raw
        or
        missing_run
    ):

        print(
            "❌ Migration DATABASE V2.1 incomplète."
        )


    else:

        print(
            "✅ DATABASE V2.1 correctement installée."
        )


        print()

        print(
            "IMPORTANT :"
        )


        print(
            "Le prochain python main.py rafraîchira "
            "raw_payload_json depuis les listings bruts."
        )


        print(
            "Les enrichissements suivants seront stockés "
            "séparément dans enriched_payload_json."
        )


        print()

        print(
            "Après ce run, nous pourrons créer "
            "canonical_jobs sans perdre les données RAW."
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


        print_database_test()


        print()

        print(
            "=" * 80
        )


        print(
            "TEST DATABASE V2.1 TERMINÉ"
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
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()