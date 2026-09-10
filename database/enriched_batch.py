"""
JOBHUNTER - SQLITE ENRICHMENT BATCH V1

Objectif
--------
Accélérer uniquement la persistance des offres ENRICHIES.

Le SQL métier existant reste dans database.db._upsert_raw_job().
Ce module ne modifie ni le schéma, ni les tables Lifecycle, ni APPLIED.

Sécurité
--------
- config désactivée par défaut ;
- SAVEPOINT par offre ;
- commit par petits lots ;
- rollback du lot courant si exception fatale ;
- fallback automatique vers upsert_raw_job historique hors batch.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import ContextDecorator
from functools import wraps
from pathlib import Path

from database import db


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "sqlite_enrichment_batch.json"

_STATE = threading.local()


def _read_config():
    try:
        payload = json.loads(
            CONFIG_PATH.read_text(
                encoding="utf-8"
            )
        )
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    return {
        "enabled": False,
        "commit_every": 50,
    }


def is_enabled():
    override = str(
        os.environ.get(
            "JOBHUNTER_SQLITE_ENRICH_BATCH",
            ""
        )
    ).strip().lower()

    if override in {
        "1", "true", "yes", "on"
    }:
        return True

    if override in {
        "0", "false", "no", "off"
    }:
        return False

    return bool(
        _read_config().get(
            "enabled",
            False
        )
    )


def _commit_every():
    try:
        value = int(
            _read_config().get(
                "commit_every",
                50
            )
            or 50
        )
    except Exception:
        value = 50

    return max(
        1,
        min(
            value,
            500
        )
    )


def _active_connection():
    return getattr(
        _STATE,
        "connection",
        None
    )


def _reset_state():
    _STATE.connection = None
    _STATE.pending = 0
    _STATE.total = 0
    _STATE.commits = 0
    _STATE.failures = 0
    _STATE.savepoint_counter = 0


def get_batch_stats():
    return {
        "active": (
            _active_connection()
            is not None
        ),
        "pending": int(
            getattr(
                _STATE,
                "pending",
                0
            )
            or 0
        ),
        "total": int(
            getattr(
                _STATE,
                "total",
                0
            )
            or 0
        ),
        "commits": int(
            getattr(
                _STATE,
                "commits",
                0
            )
            or 0
        ),
        "failures": int(
            getattr(
                _STATE,
                "failures",
                0
            )
            or 0
        ),
    }


class _EnrichedPersistenceBatch(ContextDecorator):

    def __init__(
        self,
        force=None
    ):
        self.force = force
        self.enabled = False
        self.connection = None

    def __enter__(self):
        if self.force is None:
            self.enabled = is_enabled()
        else:
            self.enabled = bool(
                self.force
            )

        if not self.enabled:
            return self

        if _active_connection() is not None:
            raise RuntimeError(
                "Nested SQLite enrichment batch is not supported."
            )

        db.init_db()

        self.connection = (
            db.get_connection()
        )

        _reset_state()
        _STATE.connection = (
            self.connection
        )

        print()
        print(
            "SQLITE ENRICH BATCH | "
            f"enabled=1 | "
            f"commit_every={_commit_every()}"
        )

        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb
    ):
        if not self.enabled:
            return False

        connection = (
            self.connection
        )

        try:
            if exc_type is None:
                if int(
                    getattr(
                        _STATE,
                        "pending",
                        0
                    )
                    or 0
                ) > 0:
                    connection.commit()
                    _STATE.commits = (
                        int(
                            getattr(
                                _STATE,
                                "commits",
                                0
                            )
                            or 0
                        )
                        +
                        1
                    )
                    _STATE.pending = 0
            else:
                connection.rollback()

            stats = get_batch_stats()

            print(
                "SQLITE ENRICH BATCH DONE | "
                f"total={stats['total']} | "
                f"commits={stats['commits']} | "
                f"failures={stats['failures']} | "
                f"status="
                f"{'OK' if exc_type is None else 'ROLLBACK_CURRENT_BATCH'}"
            )

        finally:
            try:
                connection.close()
            except Exception:
                pass

            _reset_state()

        return False


def enriched_persistence_batch(
    function=None,
    *,
    force=None
):
    """
    Utilisable comme décorateur ou context manager.

    @enriched_persistence_batch
    def enrich(...):
        ...
    """
    if function is None:
        return _EnrichedPersistenceBatch(
            force=force
        )

    @wraps(function)
    def wrapper(
        *args,
        **kwargs
    ):
        with _EnrichedPersistenceBatch(
            force=force
        ):
            return function(
                *args,
                **kwargs
            )

    return wrapper


def upsert_enriched_job(
    job,
    run_id=None
):
    """
    Batch-aware wrapper.

    Hors batch actif :
        comportement historique database.db.upsert_raw_job().

    Dans un batch :
        même _upsert_raw_job(), même SQL, même run_id,
        mais connexion réutilisée et commit groupé.
    """
    connection = (
        _active_connection()
    )

    if connection is None:
        return db.upsert_raw_job(
            job,
            run_id=run_id
        )

    counter = int(
        getattr(
            _STATE,
            "savepoint_counter",
            0
        )
        or 0
    ) + 1

    _STATE.savepoint_counter = counter

    savepoint = (
        f"enrich_batch_{counter}"
    )

    connection.execute(
        f"SAVEPOINT {savepoint}"
    )

    try:
        result = db._upsert_raw_job(
            connection,
            job,
            run_id
        )

        connection.execute(
            f"RELEASE SAVEPOINT {savepoint}"
        )

    except Exception:
        _STATE.failures = (
            int(
                getattr(
                    _STATE,
                    "failures",
                    0
                )
                or 0
            )
            +
            1
        )

        try:
            connection.execute(
                f"ROLLBACK TO SAVEPOINT {savepoint}"
            )
            connection.execute(
                f"RELEASE SAVEPOINT {savepoint}"
            )
        except Exception:
            pass

        raise

    _STATE.total = (
        int(
            getattr(
                _STATE,
                "total",
                0
            )
            or 0
        )
        +
        1
    )

    _STATE.pending = (
        int(
            getattr(
                _STATE,
                "pending",
                0
            )
            or 0
        )
        +
        1
    )

    if _STATE.pending >= _commit_every():
        connection.commit()

        _STATE.commits = (
            int(
                getattr(
                    _STATE,
                    "commits",
                    0
                )
                or 0
            )
            +
            1
        )

        _STATE.pending = 0

    return result
