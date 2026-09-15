"""
JOB HUNTER BELGIUM
DAILY RUN - VERSION 1.0

Orchestrateur conservateur du pipeline validé.

Pipeline par défaut
-------------------
1. main.py
2. Application Preparation V1.1
3. Job Refresh V1.2
4. Application Recheck V1.1
5. Final Application Pool V1.2
6. Delta Tracker V1.1
7. Lifecycle Sync V1.0
8. ChatGPT Handoff V1.0

Principes
---------
- aucune logique métier n'est réimplémentée ici ;
- arrêt immédiat si une commande retourne un code != 0 ;
- chaque étape doit produire un NOUVEL artefact ;
- les versions installées sont contrôlées avant le run ;
- les artefacts exacts du run sont mémorisés dans un manifest ;
- une étape qui ne supporte pas --input n'est lancée que si l'artefact
  attendu est encore le plus récent ;
- reprise possible via --resume-latest sans relancer main.py si MAIN est
  déjà terminé ;
- aucun statut APPLIED n'est créé automatiquement ;
- aucune API OpenAI n'est utilisée ici.

Commandes
---------
Préflight uniquement :
    python daily_run.py --check

Run quotidien complet :
    python daily_run.py

Run sans handoff (Lifecycle inclus) :
    python daily_run.py --no-handoff

Reprendre le dernier run interrompu :
    python daily_run.py --resume-latest

Arrêter volontairement après une étape :
    python daily_run.py --stop-after refresh

Supprimer un lock abandonné :
    python daily_run.py --clear-lock
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from config.versioning import version_at_least, version_set_at_least as _version_set_at_least
from diagnostics.version_support import at_least

# Windows-safe UTF-8 output for audits/log capture.
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


DAILY_RUN_VERSION = "1.2.2"

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
DAILY_DIR = LOG_DIR / "daily_runs"
LOCK_PATH = DAILY_DIR / ".daily_run.lock"

# Plafond du nombre d'offres preparees a chaque run.
#
# A 80, ce plafond etait le vrai facteur limitant du pool final : le run du
# 9 septembre a produit 110 offres en READY_APPLY et n'en a prepare que 80.
# Le pool n'etait donc pas borne par la qualite des offres mais par cette
# valeur, ce qui ne se voyait nulle part dans les rapports.
DEFAULT_PREPARATION_LIMIT = 150
DEFAULT_HANDOFF_CHUNK_SIZE = 10

STEP_ORDER = [
    "main",
    # L'enrichissement vient juste apres la collecte et avant tout le reste.
    #
    # Sans lui, chaque run degradait la couverture des descriptions : les
    # offres fraiches arrivent avec un bloc de metadonnees de 300 caracteres,
    # et le pre-score decide de leur sort sur ce seul texte. Mesure le
    # 9 septembre : la couverture est passee de 86 % a 69 % en un seul run.
    #
    # Le rattrapage manuel ne pouvait pas suivre ; c'est une etape du
    # pipeline, pas un outil d'appoint.
    "enrichissement",
    "preparation",
    "refresh",
    "recheck",
    "final_pool",
    "delta",
    "lifecycle",
    "handoff",
]

EXPECTED_VERSIONS = {
    "matching.application_gate_v13:GATE_VERSION": "1.3.2",
    "matching.application_queue_v12:QUEUE_VERSION": "1.2",
    "applications.application_preparation:PREPARATION_VERSION": "1.2",
    "applications.job_refresh:REFRESH_VERSION": "1.3",
    "applications.application_recheck:RECHECK_VERSION": "1.1",
    "applications.final_application_pool:FINAL_POOL_VERSION": "1.3",
    "applications.delta_tracker:DELTA_TRACKER_VERSION": "1.1",
    "applications.lifecycle_tracker:LIFECYCLE_VERSION": "1.0",
    "applications.lifecycle_sync:LIFECYCLE_SYNC_VERSION": "1.0",
    "applications.lifecycle_daily_sync:LIFECYCLE_DAILY_SYNC_VERSION": "1.0",
    "applications.chatgpt_handoff:HANDOFF_VERSION": "1.0",
}

ARTIFACT_PATTERNS = {
    "main_log": "job_hunter_main_v10_4_[0-9]*.txt",
    "gate_json": "application_gate_v1_[0-9]*.json",
    "queue_json": "application_queue_v1_[0-9]*.json",
    "preparation_json": "application_preparation_v1_[0-9]*.json",
    "preparation_txt": "application_preparation_v1_[0-9]*.txt",
    "refresh_json": "job_refresh_v1_[0-9]*.json",
    "refresh_txt": "job_refresh_v1_[0-9]*.txt",
    "recheck_json": "application_recheck_v1_[0-9]*.json",
    "recheck_txt": "application_recheck_v1_[0-9]*.txt",
    "final_pool_json": "final_application_pool_v12_[0-9]*.json",
    "final_pool_txt": "final_application_pool_v12_[0-9]*.txt",
    "final_pool_csv": "final_application_pool_v12_[0-9]*.csv",
    "delta_json": "delta_tracker_v1_[0-9]*.json",
    "delta_txt": "delta_tracker_v1_[0-9]*.txt",
    "delta_csv": "delta_tracker_v1_[0-9]*.csv",
    "lifecycle_json": "lifecycle_daily_sync_v1_[0-9]*.json",
    "lifecycle_txt": "lifecycle_daily_sync_v1_[0-9]*.txt",
}


# ---------------------------------------------------------------------------
# BASIC HELPERS
# ---------------------------------------------------------------------------

def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def safe_json_load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_json_write(path, payload, max_attempts=30):
    """
    Écriture JSON atomique robuste sous Windows.

    L'interface Streamlit lit régulièrement le manifest pendant le Daily Run.
    Sous Windows, une lecture très brève peut empêcher os.replace() de
    remplacer le fichier et provoquer WinError 5 (Access denied).

    V1.2.1 :
    - fichier temporaire unique par processus/écriture ;
    - retry automatique sur PermissionError / sharing violation ;
    - backoff court plafonné à 0,5 s ;
    - nettoyage du .tmp si l'écriture finit par échouer.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = json.dumps(payload, ensure_ascii=False, indent=2)
    temp = path.with_name(
        f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    temp.write_text(data, encoding="utf-8")

    last_error = None
    for attempt in range(1, int(max_attempts) + 1):
        try:
            os.replace(temp, path)
            return
        except PermissionError as error:
            last_error = error
            # Windows peut verrouiller momentanément la destination pendant
            # que l'UI la lit. On attend puis on retente sans casser le run.
            time.sleep(min(0.05 * attempt, 0.50))
        except OSError as error:
            # Certaines sharing violations Windows remontent comme OSError
            # générique avec winerror 5 ou 32.
            if getattr(error, "winerror", None) in {5, 32}:
                last_error = error
                time.sleep(min(0.05 * attempt, 0.50))
                continue
            raise

    try:
        if temp.exists():
            temp.unlink()
    except Exception:
        pass

    raise PermissionError(
        f"Impossible d'écrire le manifest après {max_attempts} tentatives : "
        f"{path} | dernière erreur: {last_error}"
    ) from last_error


def latest_path(directory, pattern):
    paths = list(Path(directory).glob(pattern))
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_mtime_ns)


def path_identity(path):
    if path is None:
        return None
    try:
        return str(Path(path).resolve())
    except Exception:
        return str(path)


def same_path(a, b):
    if not a or not b:
        return False
    try:
        return Path(a).resolve() == Path(b).resolve()
    except Exception:
        return str(a) == str(b)


def snapshot_glob(directory, pattern):
    return {
        path_identity(path): path.stat().st_mtime_ns
        for path in Path(directory).glob(pattern)
        if path.is_file()
    }


def newly_created_or_modified(directory, pattern, before):
    candidates = []
    for path in Path(directory).glob(pattern):
        if not path.is_file():
            continue
        ident = path_identity(path)
        mtime = path.stat().st_mtime_ns
        old = before.get(ident)
        if old is None or mtime > old:
            candidates.append(path)

    if not candidates:
        return None

    return max(candidates, key=lambda p: p.stat().st_mtime_ns)


def file_exists(path):
    return bool(path and Path(path).exists())


# ---------------------------------------------------------------------------
# VERSION PREFLIGHT
# ---------------------------------------------------------------------------

def read_module_attr(module_name, attr_name):
    module = importlib.import_module(module_name)
    if not hasattr(module, attr_name):
        raise RuntimeError(
            f"{module_name}.{attr_name} introuvable."
        )
    return str(getattr(module, attr_name))


def inspect_main_version():
    main_path = PROJECT_ROOT / "main.py"
    if not main_path.exists():
        raise RuntimeError("main.py introuvable à la racine du projet.")

    text = main_path.read_text(encoding="utf-8", errors="replace")

    version_ok = bool(
        re.search(r"(?:MAIN\s*[-:]?\s*VERSION|MAIN)\s*V?\s*10\.4(?:\.\d+)?", text, re.I)
        or re.search(r"VERSION\s*10\.4(?:\.\d+)?", text, re.I)
    )

    gate_branch_ok = "application_gate_v13" in text
    queue_branch_ok = "application_queue_v12" in text
    sr_ok = "smartrecruiters" in text.lower()

    return {
        "path": str(main_path),
        "version_10_4_family": version_ok,
        "gate_v13_branch": gate_branch_ok,
        "queue_v12_branch": queue_branch_ok,
        "smartrecruiters_present": sr_ok,
    }


def run_preflight():
    errors = []
    installed = {}

    required_paths = [
        PROJECT_ROOT / "main.py",
        PROJECT_ROOT / "applications" / "application_preparation.py",
        PROJECT_ROOT / "applications" / "job_refresh.py",
        PROJECT_ROOT / "applications" / "application_recheck.py",
        PROJECT_ROOT / "applications" / "final_application_pool.py",
        PROJECT_ROOT / "applications" / "delta_tracker.py",
        PROJECT_ROOT / "applications" / "lifecycle_tracker.py",
        PROJECT_ROOT / "applications" / "lifecycle_sync.py",
        PROJECT_ROOT / "applications" / "lifecycle_daily_sync.py",
        PROJECT_ROOT / "applications" / "chatgpt_handoff.py",
        PROJECT_ROOT / "matching" / "application_gate_v13.py",
        PROJECT_ROOT / "matching" / "application_queue_v12.py",
    ]

    missing = [str(p) for p in required_paths if not p.exists()]
    if missing:
        errors.append("Fichiers requis manquants : " + " | ".join(missing))

    for spec, expected in EXPECTED_VERSIONS.items():
        module_name, attr = spec.split(":", 1)
        try:
            actual = read_module_attr(module_name, attr)
            installed[spec] = actual
            # Comparaison de structure, pas d'égalité de chaîne.
            #
            # EXPECTED_VERSIONS exprime un MINIMUM. Une égalité stricte
            # transforme chaque montée de version légitime en panne du
            # préflight, et oblige à éditer cette table à chaque livraison.
            if not at_least(actual, expected):
                errors.append(
                    f"Version trop ancienne {spec}: "
                    f"installé={actual}, minimum={expected}"
                )
        except Exception as exc:
            installed[spec] = f"ERROR: {type(exc).__name__}: {exc}"
            errors.append(
                f"Import/version impossible {spec}: "
                f"{type(exc).__name__}: {exc}"
            )

    try:
        main_info = inspect_main_version()
        if not main_info["version_10_4_family"]:
            errors.append("main.py n'est pas reconnu comme famille V10.4.")
        if not main_info["gate_v13_branch"]:
            errors.append("main.py ne branche pas application_gate_v13.")
        if not main_info["queue_v12_branch"]:
            errors.append("main.py ne branche pas application_queue_v12.")
        if not main_info["smartrecruiters_present"]:
            errors.append("main.py ne semble pas intégrer SmartRecruiters.")
    except Exception as exc:
        main_info = {"error": f"{type(exc).__name__}: {exc}"}
        errors.append(main_info["error"])

    return {
        "ok": not errors,
        "daily_run_version": DAILY_RUN_VERSION,
        "python": sys.executable,
        "python_version": sys.version.split()[0],
        "project_root": str(PROJECT_ROOT),
        "main": main_info,
        "installed_versions": installed,
        "expected_versions": EXPECTED_VERSIONS,
        "errors": errors,
    }


def print_preflight(result):
    print("=" * 100)
    print("JOB HUNTER DAILY RUN V1.2 - PREFLIGHT")
    print("=" * 100)
    print()
    print("Python :", result["python"])
    print("Version:", result["python_version"])
    print("Root   :", result["project_root"])
    print()

    for spec, expected in result["expected_versions"].items():
        actual = result["installed_versions"].get(spec)
        # Meme regle que la validation (ligne ~350) : un minimum, pas une
        # egalite. Sinon lifecycle 1.1 s'affichait en rouge alors qu'il passe.
        icon = "✅" if actual and at_least(actual, expected) else "❌"
        print(f"{icon} {spec:<62} {actual}")

    print()
    main_info = result.get("main") or {}
    for key in (
        "version_10_4_family",
        "gate_v13_branch",
        "queue_v12_branch",
        "smartrecruiters_present",
    ):
        value = main_info.get(key)
        icon = "✅" if value else "❌"
        print(f"{icon} MAIN {key:<34}: {value}")

    print()
    if result["ok"]:
        print("✅ PREFLIGHT DAILY RUN V1.2 VALIDÉ.")
    else:
        print("❌ PREFLIGHT BLOQUÉ.")
        for error in result["errors"]:
            print(" -", error)


# ---------------------------------------------------------------------------
# PAYLOAD VALIDATION
# ---------------------------------------------------------------------------

def unique_nonempty(values):
    return {clean_text(v) for v in values if clean_text(v)}


def validate_gate_json(path):
    payload = safe_json_load(path)
    if not isinstance(payload, list):
        raise RuntimeError("Gate JSON doit être une liste.")

    versions = unique_nonempty(
        (row.get("gate") or {}).get("gate_version")
        for row in payload
        if isinstance(row, dict)
    )

    if not _version_set_at_least(versions, "1.3.2", require_single=True):
        raise RuntimeError(
            f"Gate export incompatible: versions={sorted(versions)}"
        )

    return {
        "count": len(payload),
        "gate_versions": sorted(versions),
    }


def validate_queue_json(path):
    payload = safe_json_load(path)
    if not isinstance(payload, list):
        raise RuntimeError("Queue JSON doit être une liste.")

    queue_versions = unique_nonempty(
        row.get("queue_version")
        for row in payload
        if isinstance(row, dict)
    )
    gate_versions = unique_nonempty(
        (row.get("gate") or {}).get("gate_version")
        for row in payload
        if isinstance(row, dict)
    )

    if not _version_set_at_least(queue_versions, "1.2", require_single=True):
        raise RuntimeError(
            f"Queue export incompatible: versions={sorted(queue_versions)}"
        )

    if not _version_set_at_least(gate_versions, "1.3.2", require_single=True):
        raise RuntimeError(
            f"Queue embarque un Gate incompatible: {sorted(gate_versions)}"
        )

    return {
        "count": len(payload),
        "queue_versions": sorted(queue_versions),
        "gate_versions": sorted(gate_versions),
    }


def validate_preparation_json(path, limit):
    payload = safe_json_load(path)
    if not isinstance(payload, list):
        raise RuntimeError("Application Preparation JSON doit être une liste.")

    if not payload:
        raise RuntimeError("Application Preparation vide.")

    if len(payload) > int(limit):
        raise RuntimeError(
            f"Preparation contient {len(payload)} lignes > limit={limit}."
        )

    gate_versions = unique_nonempty(
        (row.get("gate") or {}).get("gate_version")
        for row in payload
        if isinstance(row, dict)
    )
    queue_versions = unique_nonempty(
        row.get("queue_version")
        for row in payload
        if isinstance(row, dict)
    )

    # Certains exports propagent gate_version directement plutôt que dans gate.
    direct_gate = unique_nonempty(
        row.get("gate_version")
        for row in payload
        if isinstance(row, dict)
    )
    if direct_gate:
        gate_versions |= direct_gate

    if gate_versions and not _version_set_at_least(gate_versions, "1.3.2", require_single=True):
        raise RuntimeError(
            f"Preparation Gate incompatible: {sorted(gate_versions)}"
        )
    if queue_versions and not _version_set_at_least(queue_versions, "1.2", require_single=True):
        raise RuntimeError(
            f"Preparation Queue incompatible: {sorted(queue_versions)}"
        )

    return {
        "count": len(payload),
        "gate_versions": sorted(gate_versions),
        "queue_versions": sorted(queue_versions),
    }


def validate_refresh_json(path, expected_count=None):
    payload = safe_json_load(path)
    if not isinstance(payload, list):
        raise RuntimeError("Job Refresh JSON doit être une liste.")

    if expected_count is not None and len(payload) != int(expected_count):
        raise RuntimeError(
            f"Refresh count={len(payload)} != preparation={expected_count}."
        )

    versions = unique_nonempty(
        row.get("refresh_version")
        for row in payload
        if isinstance(row, dict)
    )
    if versions and not _version_set_at_least(versions, "1.2", require_single=True):
        raise RuntimeError(
            f"Refresh versions incompatibles: {sorted(versions)}"
        )

    # Job Refresh V1.2 expose son état live sous `job_live_status`.
    # `status` appartient à d'autres étages du pipeline (Gate/Recheck)
    # et ne doit pas être utilisé ici comme source principale.
    statuses = {}
    for row in payload:
        status = clean_text(
            row.get("job_live_status")
            or row.get("refresh_status")
            or "UNKNOWN"
        )
        statuses[status] = statuses.get(status, 0) + 1

    return {
        "count": len(payload),
        "refresh_versions": sorted(versions),
        "statuses": statuses,
    }


def validate_recheck_json(path, expected_count=None):
    payload = safe_json_load(path)
    if not isinstance(payload, list):
        raise RuntimeError("Application Recheck JSON doit être une liste.")

    if expected_count is not None and len(payload) != int(expected_count):
        raise RuntimeError(
            f"Recheck count={len(payload)} != refresh={expected_count}."
        )

    versions = unique_nonempty(
        row.get("recheck_version")
        for row in payload
        if isinstance(row, dict)
    )
    if versions and not _version_set_at_least(versions, "1.1", require_single=True):
        raise RuntimeError(
            f"Recheck versions incompatibles: {sorted(versions)}"
        )

    statuses = {}
    for row in payload:
        status = clean_text(row.get("status") or "UNKNOWN")
        statuses[status] = statuses.get(status, 0) + 1

    return {
        "count": len(payload),
        "recheck_versions": sorted(versions),
        "statuses": statuses,
    }


def validate_final_pool_json(path):
    payload = safe_json_load(path)
    if not isinstance(payload, dict):
        raise RuntimeError("Final Pool JSON doit être un objet.")

    # Comparaison par >=, jamais par egalite : un Final Pool en 1.3
    # reste lisible par une chaine qui en attend 1.2, et epingler la
    # version exacte faisait echouer un run entier sur une montee de
    # version parfaitement compatible.
    if not at_least(str(payload.get("pool_version")), "1.2"):
        raise RuntimeError(
            f"Final Pool version={payload.get('pool_version')!r}, attendu au moins 1.2."
        )

    pool = payload.get("pool")
    if not isinstance(pool, list):
        raise RuntimeError("Final Pool: champ pool invalide.")

    summary = payload.get("summary") or {}

    actions = {}
    for row in pool:
        action = clean_text(
            row.get("recommended_action_v12")
            or row.get("recommended_action")
            or "UNKNOWN"
        )
        actions[action] = actions.get(action, 0) + 1

    return {
        "count": len(pool),
        "summary": summary,
        "actions": actions,
        "duplicates_removed_count": payload.get("duplicates_removed_count"),
        "possible_duplicates_count": payload.get("possible_duplicates_count"),
    }



def validate_delta_json(
    path,
    expected_current_pool=None,
    expected_current_count=None,
):
    payload = safe_json_load(path)

    if not isinstance(payload, dict):
        raise RuntimeError("Delta Tracker JSON doit être un objet.")

    version = str(payload.get("delta_tracker_version"))
    if not version_at_least(version, "1.1"):
        raise RuntimeError(
            f"Delta Tracker version={version!r}, attendu 1.1."
        )

    if payload.get("scope") != "FINAL_APPLICATION_POOL_V1.2":
        raise RuntimeError(
            f"Delta scope incompatible: {payload.get('scope')!r}"
        )

    inputs = payload.get("inputs") or {}
    current_pool = inputs.get("current_pool")
    previous_pool = inputs.get("previous_pool")

    if expected_current_pool:
        if not current_pool or not same_path(
            current_pool,
            expected_current_pool,
        ):
            raise RuntimeError(
                "Delta Tracker a comparé un Final Pool différent du run.\n"
                f"Attendu : {expected_current_pool}\n"
                f"Delta   : {current_pool}"
            )

    if not previous_pool:
        raise RuntimeError("Delta Tracker: previous_pool absent.")

    if current_pool and same_path(current_pool, previous_pool):
        raise RuntimeError(
            "Delta Tracker: current_pool et previous_pool sont identiques."
        )

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise RuntimeError("Delta Tracker: summary invalide.")

    def as_int(name):
        try:
            return int(summary.get(name, 0))
        except Exception as exc:
            raise RuntimeError(
                f"Delta Tracker: compteur {name} invalide."
            ) from exc

    current_total = as_int("current_total")
    previous_total = as_int("previous_total")

    if (
        expected_current_count is not None
        and current_total != int(expected_current_count)
    ):
        raise RuntimeError(
            f"Delta current_total={current_total} "
            f"!= Final Pool={expected_current_count}."
        )

    counters = {
        name: as_int(name)
        for name in (
            "NEW",
            "REACTIVATED",
            "REPOSTED",
            "UPDATED",
            "UNCHANGED",
            "DISAPPEARED",
        )
    }

    reconstructed_current = sum(
        counters[name]
        for name in (
            "NEW",
            "REACTIVATED",
            "REPOSTED",
            "UPDATED",
            "UNCHANGED",
        )
    )
    if reconstructed_current != current_total:
        raise RuntimeError(
            "Delta invariant cassé : somme des statuts actuels "
            f"{reconstructed_current} != current_total {current_total}."
        )

    reconstructed_previous = (
        counters["REPOSTED"]
        + counters["UPDATED"]
        + counters["UNCHANGED"]
        + counters["DISAPPEARED"]
    )
    if reconstructed_previous != previous_total:
        raise RuntimeError(
            "Delta invariant cassé : reconstruction previous "
            f"{reconstructed_previous} != previous_total {previous_total}."
        )

    records = payload.get("records")
    if not isinstance(records, list):
        raise RuntimeError("Delta Tracker: records invalide.")

    allowed = {
        "NEW",
        "REACTIVATED",
        "REPOSTED",
        "UPDATED",
        "UNCHANGED",
        "DISAPPEARED",
    }
    bad = sorted({
        clean_text(row.get("delta_status"))
        for row in records
        if isinstance(row, dict)
        and clean_text(row.get("delta_status")) not in allowed
    })
    if bad:
        raise RuntimeError(
            f"Delta Tracker: statuts inconnus {bad}."
        )

    return {
        "version": version,
        "current_total": current_total,
        "previous_total": previous_total,
        "counters": counters,
        "current_pool": current_pool,
        "previous_pool": previous_pool,
        "new_apply_now": as_int("new_apply_now"),
        "reposted_apply_now": as_int("reposted_apply_now"),
        "updated_apply_now": as_int("updated_apply_now"),
    }


def validate_lifecycle_sync_json(
    path,
    expected_final_pool=None,
    expected_delta=None,
    expected_current_count=None,
):
    payload = safe_json_load(path)

    if not isinstance(payload, dict):
        raise RuntimeError("Lifecycle Sync JSON doit être un objet.")

    wrapper_version = str(
        payload.get("lifecycle_daily_sync_version")
    )
    if not version_at_least(wrapper_version, "1.0"):
        raise RuntimeError(
            f"Lifecycle Daily Sync version={wrapper_version!r}, attendu 1.0."
        )

    sync_version = str(
        payload.get("lifecycle_sync_version")
    )
    if not version_at_least(sync_version, "1.0"):
        raise RuntimeError(
            f"Lifecycle Sync version={sync_version!r}, attendu 1.0."
        )

    inputs = payload.get("inputs") or {}
    final_pool = inputs.get("final_pool")
    delta = inputs.get("delta")

    if expected_final_pool:
        if not final_pool or not same_path(
            final_pool,
            expected_final_pool,
        ):
            raise RuntimeError(
                "Lifecycle Sync a utilisé un Final Pool différent du run.\n"
                f"Attendu : {expected_final_pool}\n"
                f"Lifecycle: {final_pool}"
            )

    if expected_delta:
        if not delta or not same_path(
            delta,
            expected_delta,
        ):
            raise RuntimeError(
                "Lifecycle Sync a utilisé un Delta différent du run.\n"
                f"Attendu : {expected_delta}\n"
                f"Lifecycle: {delta}"
            )

    result = payload.get("result") or {}
    try:
        current_items = int(result.get("current_items"))
    except Exception as exc:
        raise RuntimeError(
            "Lifecycle Sync: current_items invalide."
        ) from exc

    if (
        expected_current_count is not None
        and current_items != int(expected_current_count)
    ):
        raise RuntimeError(
            f"Lifecycle current_items={current_items} "
            f"!= Final Pool={expected_current_count}."
        )

    if result.get("applied_policy") != "USER_ONLY":
        raise RuntimeError(
            "Lifecycle Sync: politique APPLIED incompatible."
        )

    if result.get("disappeared_policy") != "NO_STATUS_CHANGE":
        raise RuntimeError(
            "Lifecycle Sync: politique DISAPPEARED incompatible."
        )

    post_sync = payload.get("post_sync") or {}

    try:
        non_user_applied = int(
            post_sync.get("non_user_applied", -1)
        )
    except Exception as exc:
        raise RuntimeError(
            "Lifecycle Sync: non_user_applied invalide."
        ) from exc

    if non_user_applied != 0:
        raise RuntimeError(
            f"Lifecycle invariant cassé : {non_user_applied} "
            "APPLIED non-USER détecté(s)."
        )

    return {
        "wrapper_version": wrapper_version,
        "sync_version": sync_version,
        "current_items": current_items,
        "final_pool": final_pool,
        "delta": delta,
        "counts": result.get("counts") or {},
        "status_events_created": (
            result.get("status_events_created") or {}
        ),
        "applied_policy": result.get("applied_policy"),
        "disappeared_policy": result.get("disappeared_policy"),
        "post_sync": post_sync,
    }


# ---------------------------------------------------------------------------
# MANIFEST + LOCK
# ---------------------------------------------------------------------------

def manifest_paths(run_id):
    return {
        "json": DAILY_DIR / f"daily_run_v1_{run_id}.json",
        "txt": DAILY_DIR / f"daily_run_v1_{run_id}.txt",
        "step_dir": DAILY_DIR / f"daily_run_v1_{run_id}",
    }


def new_manifest(args):
    run_id = stamp()
    paths = manifest_paths(run_id)

    manifest = {
        "daily_run_version": DAILY_RUN_VERSION,
        "run_id": run_id,
        "started_at": now_iso(),
        "finished_at": None,
        "status": "RUNNING",
        "project_root": str(PROJECT_ROOT),
        "python": sys.executable,
        "settings": {
            "preparation_limit": int(args.limit),
            "handoff_chunk_size": int(args.chunk_size),
            "handoff_enabled": not bool(args.no_handoff),
            "stop_after": args.stop_after,
        },
        "preflight": None,
        "steps": {
            step: {
                "status": "PENDING",
                "started_at": None,
                "finished_at": None,
                "command": None,
                "log": None,
                "artifacts": {},
                "validation": {},
                "error": None,
            }
            for step in STEP_ORDER
        },
        "resume_count": 0,
        "last_error": None,
    }

    paths["step_dir"].mkdir(parents=True, exist_ok=True)
    save_manifest(manifest)
    return manifest


def save_manifest(manifest):
    paths = manifest_paths(manifest["run_id"])
    atomic_json_write(paths["json"], manifest)
    write_manifest_txt(paths["txt"], manifest)


def write_manifest_txt(path, manifest):
    lines = []
    lines.append("JOB HUNTER DAILY RUN V1.2")
    lines.append("=" * 100)
    lines.append(f"Run ID       : {manifest.get('run_id')}")
    lines.append(f"Started      : {manifest.get('started_at')}")
    lines.append(f"Finished     : {manifest.get('finished_at')}")
    lines.append(f"Status       : {manifest.get('status')}")
    lines.append(f"Project root : {manifest.get('project_root')}")
    lines.append("")

    for step in STEP_ORDER:
        row = (manifest.get("steps") or {}).get(step) or {}
        lines.append(
            f"{step:<14} | {row.get('status'):<10} | "
            f"{row.get('started_at') or '-'} -> {row.get('finished_at') or '-'}"
        )
        if row.get("command"):
            lines.append("  CMD : " + " ".join(map(str, row["command"])))
        if row.get("log"):
            lines.append("  LOG : " + str(row["log"]))
        for name, value in (row.get("artifacts") or {}).items():
            lines.append(f"  {name:<18}: {value}")
        if row.get("validation"):
            lines.append(
                "  VALIDATION : "
                + json.dumps(row["validation"], ensure_ascii=False)
            )
        if row.get("error"):
            lines.append("  ERROR : " + str(row["error"]))
        lines.append("")

    if manifest.get("last_error"):
        lines.append("LAST ERROR")
        lines.append("-" * 100)
        lines.append(str(manifest["last_error"]))

    Path(path).write_text("\n".join(lines), encoding="utf-8")


def latest_manifest_path():
    return latest_path(DAILY_DIR, "daily_run_v1_*.json")


def load_latest_manifest():
    path = latest_manifest_path()
    if path is None:
        raise RuntimeError("Aucun daily_run_v1_*.json à reprendre.")
    payload = safe_json_load(path)
    return payload


def acquire_lock(run_id, clear=False):
    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    if clear and LOCK_PATH.exists():
        LOCK_PATH.unlink()

    if LOCK_PATH.exists():
        content = LOCK_PATH.read_text(encoding="utf-8", errors="replace")
        raise RuntimeError(
            "Un Daily Run semble déjà actif, ou un lock a été abandonné.\n"
            f"Lock : {LOCK_PATH}\n"
            f"Contenu : {content}\n"
            "Si aucun run n'est actif : python daily_run.py --clear-lock"
        )

    LOCK_PATH.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "pid": os.getpid(),
                "started_at": now_iso(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def release_lock():
    try:
        if LOCK_PATH.exists():
            LOCK_PATH.unlink()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# SUBPROCESS EXECUTION
# ---------------------------------------------------------------------------

def run_command(step, command, manifest):
    paths = manifest_paths(manifest["run_id"])
    log_path = paths["step_dir"] / f"{step}.log"

    row = manifest["steps"][step]
    row["status"] = "RUNNING"
    row["started_at"] = now_iso()
    row["finished_at"] = None
    row["command"] = [str(x) for x in command]
    row["log"] = str(log_path)
    row["error"] = None
    save_manifest(manifest)

    print()
    print("=" * 100)
    print(f"DAILY RUN — {step.upper()}")
    print("=" * 100)
    print("Commande :", " ".join(map(str, command)))
    print("Log      :", log_path)
    print()

    # Windows peut donner cp1252 aux processus Python enfants quand leur
    # stdout est redirigé vers PIPE. Des caractères comme ⚠️ provoquent alors
    # UnicodeEncodeError dans le module enfant, même si sa logique métier a
    # terminé correctement. On force donc UTF-8 pour TOUS les sous-processus.
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"

    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(x) for x in command],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=child_env,
        )

        assert process.stdout is not None
        for line in process.stdout:
            # Toujours préserver le log UTF-8 exact en premier.
            log.write(line)
            log.flush()

            # Le terminal parent peut lui-même avoir un encodage Windows
            # limité. Dans ce cas on dégrade seulement l'AFFICHAGE console,
            # jamais le fichier log ni les données.
            try:
                print(line, end="")
            except UnicodeEncodeError:
                console_encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
                safe_line = line.encode(
                    console_encoding,
                    errors="replace",
                ).decode(
                    console_encoding,
                    errors="replace",
                )
                print(safe_line, end="")

        return_code = process.wait()

    row["finished_at"] = now_iso()

    if return_code != 0:
        row["status"] = "FAILED"
        row["error"] = f"Exit code {return_code}"
        save_manifest(manifest)
        raise RuntimeError(
            f"Étape {step} échouée avec exit code {return_code}. "
            f"Voir {log_path}"
        )

    # La commande a réussi, mais l'étape n'est DONE qu'après
    # validation des artefacts par step_*.
    row["status"] = "COMMAND_OK"
    save_manifest(manifest)
    return log_path


# ---------------------------------------------------------------------------
# ANCHOR / STALE-PROTECTION HELPERS
# ---------------------------------------------------------------------------

def require_latest_exact(pattern, expected_path, label):
    latest = latest_path(LOG_DIR, pattern)
    if latest is None:
        raise RuntimeError(f"{label}: aucun fichier {pattern}.")
    if not same_path(latest, expected_path):
        raise RuntimeError(
            f"{label}: protection anti-mélange déclenchée.\n"
            f"Attendu : {expected_path}\n"
            f"Plus récent actuellement : {latest}\n"
            "Le Daily Run refuse de mélanger deux cycles."
        )
    return latest


def get_step_artifact(manifest, step, name):
    return (
        ((manifest.get("steps") or {}).get(step) or {})
        .get("artifacts", {})
        .get(name)
    )


def require_completed(manifest, step):
    status = manifest["steps"][step]["status"]
    if status != "DONE":
        raise RuntimeError(
            f"Impossible de continuer : étape {step}={status}, attendu DONE."
        )


# ---------------------------------------------------------------------------
# STEP IMPLEMENTATIONS
# ---------------------------------------------------------------------------

def step_main(manifest):
    before = {
        name: snapshot_glob(LOG_DIR, pattern)
        for name, pattern in (
            ("main_log", ARTIFACT_PATTERNS["main_log"]),
            ("gate_json", ARTIFACT_PATTERNS["gate_json"]),
            ("queue_json", ARTIFACT_PATTERNS["queue_json"]),
        )
    }

    run_command(
        "main",
        [sys.executable, str(PROJECT_ROOT / "main.py")],
        manifest,
    )

    artifacts = {}
    for name in ("main_log", "gate_json", "queue_json"):
        path = newly_created_or_modified(
            LOG_DIR,
            ARTIFACT_PATTERNS[name],
            before[name],
        )
        if path is None:
            raise RuntimeError(
                f"MAIN terminé mais aucun nouvel artefact {name} "
                f"({ARTIFACT_PATTERNS[name]}) n'a été produit."
            )
        artifacts[name] = str(path.resolve())

    gate_validation = validate_gate_json(artifacts["gate_json"])
    queue_validation = validate_queue_json(artifacts["queue_json"])

    manifest["steps"]["main"]["artifacts"] = artifacts
    manifest["steps"]["main"]["validation"] = {
        "gate": gate_validation,
        "queue": queue_validation,
    }
    manifest["steps"]["main"]["status"] = "DONE"
    save_manifest(manifest)


def step_enrichissement(manifest):
    """
    Recupere la description complete des offres qui n'en ont pas.

    Le pre-score decide de l'interet d'une offre sur son texte. Une offre
    livree avec 300 caracteres de metadonnees est donc jugee sur presque
    rien, et une offre mal decrite n'obtient jamais sa description : elle
    est ecartee avant qu'on aille la chercher.

    Cette etape casse ce cercle en allant chercher le texte AVANT que la
    chaine ne se prononce.

    Elle ne peut pas faire echouer le run : une description manquante degrade
    la qualite du tri, elle ne casse rien. Un echec reseau ici ne doit pas
    empecher le pipeline de traiter les offres deja completes.
    """
    require_completed(manifest, "main")

    try:
        run_command(
            "enrichissement",
            [sys.executable, "-m", "diagnostics.detail_backfill", "--toutes"],
            manifest,
        )
    except Exception as error:
        print()
        print("⚠️ ENRICHISSEMENT INCOMPLET —", error)
        print("   Le run continue : les offres deja completes restent")
        print("   exploitables, et le rattrapage reprendra au prochain run.")

    return {}


def step_preparation(manifest):
    require_completed(manifest, "main")

    gate_path = get_step_artifact(manifest, "main", "gate_json")
    queue_path = get_step_artifact(manifest, "main", "queue_json")

    if not file_exists(gate_path) or not file_exists(queue_path):
        raise RuntimeError("Artefacts MAIN mémorisés introuvables.")

    # Application Preparation V1.1 lit le dernier Gate :
    # on vérifie donc qu'il s'agit encore exactement de celui de ce run.
    require_latest_exact(
        ARTIFACT_PATTERNS["gate_json"],
        gate_path,
        "Application Preparation / Gate",
    )

    validate_gate_json(gate_path)
    validate_queue_json(queue_path)

    before_json = snapshot_glob(
        LOG_DIR,
        ARTIFACT_PATTERNS["preparation_json"],
    )
    before_txt = snapshot_glob(
        LOG_DIR,
        ARTIFACT_PATTERNS["preparation_txt"],
    )

    limit = int(manifest["settings"]["preparation_limit"])

    run_command(
        "preparation",
        [
            sys.executable,
            "-m",
            "applications.application_preparation",
            "--limit",
            str(limit),
        ],
        manifest,
    )

    json_path = newly_created_or_modified(
        LOG_DIR,
        ARTIFACT_PATTERNS["preparation_json"],
        before_json,
    )
    txt_path = newly_created_or_modified(
        LOG_DIR,
        ARTIFACT_PATTERNS["preparation_txt"],
        before_txt,
    )

    if json_path is None:
        raise RuntimeError("Preparation terminée sans nouveau JSON.")
    if txt_path is None:
        raise RuntimeError("Preparation terminée sans nouveau TXT.")

    validation = validate_preparation_json(json_path, limit)

    manifest["steps"]["preparation"]["artifacts"] = {
        "preparation_json": str(json_path.resolve()),
        "preparation_txt": str(txt_path.resolve()),
    }
    manifest["steps"]["preparation"]["validation"] = validation
    manifest["steps"]["preparation"]["status"] = "DONE"
    save_manifest(manifest)


def step_refresh(manifest):
    require_completed(manifest, "preparation")

    prep_path = get_step_artifact(
        manifest,
        "preparation",
        "preparation_json",
    )
    if not file_exists(prep_path):
        raise RuntimeError("Preparation JSON mémorisé introuvable.")

    prep_validation = validate_preparation_json(
        prep_path,
        manifest["settings"]["preparation_limit"],
    )

    before_json = snapshot_glob(
        LOG_DIR,
        ARTIFACT_PATTERNS["refresh_json"],
    )
    before_txt = snapshot_glob(
        LOG_DIR,
        ARTIFACT_PATTERNS["refresh_txt"],
    )

    run_command(
        "refresh",
        [
            sys.executable,
            "-m",
            "applications.job_refresh",
            "--input",
            str(Path(prep_path).resolve()),
        ],
        manifest,
    )

    json_path = newly_created_or_modified(
        LOG_DIR,
        ARTIFACT_PATTERNS["refresh_json"],
        before_json,
    )
    txt_path = newly_created_or_modified(
        LOG_DIR,
        ARTIFACT_PATTERNS["refresh_txt"],
        before_txt,
    )

    if json_path is None:
        raise RuntimeError("Job Refresh terminé sans nouveau JSON.")
    if txt_path is None:
        raise RuntimeError("Job Refresh terminé sans nouveau TXT.")

    validation = validate_refresh_json(
        json_path,
        expected_count=prep_validation["count"],
    )

    manifest["steps"]["refresh"]["artifacts"] = {
        "refresh_json": str(json_path.resolve()),
        "refresh_txt": str(txt_path.resolve()),
    }
    manifest["steps"]["refresh"]["validation"] = validation
    manifest["steps"]["refresh"]["status"] = "DONE"
    save_manifest(manifest)


def step_recheck(manifest):
    require_completed(manifest, "refresh")

    refresh_path = get_step_artifact(
        manifest,
        "refresh",
        "refresh_json",
    )
    if not file_exists(refresh_path):
        raise RuntimeError("Refresh JSON mémorisé introuvable.")

    # Recheck V1.1 lit automatiquement le dernier Refresh.
    require_latest_exact(
        ARTIFACT_PATTERNS["refresh_json"],
        refresh_path,
        "Application Recheck / Refresh",
    )

    refresh_validation = validate_refresh_json(refresh_path)

    before_json = snapshot_glob(
        LOG_DIR,
        ARTIFACT_PATTERNS["recheck_json"],
    )
    before_txt = snapshot_glob(
        LOG_DIR,
        ARTIFACT_PATTERNS["recheck_txt"],
    )

    run_command(
        "recheck",
        [
            sys.executable,
            "-m",
            "applications.application_recheck",
        ],
        manifest,
    )

    json_path = newly_created_or_modified(
        LOG_DIR,
        ARTIFACT_PATTERNS["recheck_json"],
        before_json,
    )
    txt_path = newly_created_or_modified(
        LOG_DIR,
        ARTIFACT_PATTERNS["recheck_txt"],
        before_txt,
    )

    if json_path is None:
        raise RuntimeError("Recheck terminé sans nouveau JSON.")
    if txt_path is None:
        raise RuntimeError("Recheck terminé sans nouveau TXT.")

    validation = validate_recheck_json(
        json_path,
        expected_count=refresh_validation["count"],
    )

    manifest["steps"]["recheck"]["artifacts"] = {
        "recheck_json": str(json_path.resolve()),
        "recheck_txt": str(txt_path.resolve()),
    }
    manifest["steps"]["recheck"]["validation"] = validation
    manifest["steps"]["recheck"]["status"] = "DONE"
    save_manifest(manifest)


def step_final_pool(manifest):
    require_completed(manifest, "refresh")
    require_completed(manifest, "recheck")

    refresh_path = get_step_artifact(
        manifest,
        "refresh",
        "refresh_json",
    )
    recheck_path = get_step_artifact(
        manifest,
        "recheck",
        "recheck_json",
    )

    if not file_exists(refresh_path) or not file_exists(recheck_path):
        raise RuntimeError("Refresh/Recheck mémorisés introuvables.")

    # Final Pool V1.2 lit automatiquement les derniers Refresh + Recheck.
    require_latest_exact(
        ARTIFACT_PATTERNS["refresh_json"],
        refresh_path,
        "Final Pool / Refresh",
    )
    require_latest_exact(
        ARTIFACT_PATTERNS["recheck_json"],
        recheck_path,
        "Final Pool / Recheck",
    )

    before_json = snapshot_glob(
        LOG_DIR,
        ARTIFACT_PATTERNS["final_pool_json"],
    )
    before_txt = snapshot_glob(
        LOG_DIR,
        ARTIFACT_PATTERNS["final_pool_txt"],
    )
    before_csv = snapshot_glob(
        LOG_DIR,
        ARTIFACT_PATTERNS["final_pool_csv"],
    )

    run_command(
        "final_pool",
        [
            sys.executable,
            "-m",
            "applications.final_application_pool",
        ],
        manifest,
    )

    json_path = newly_created_or_modified(
        LOG_DIR,
        ARTIFACT_PATTERNS["final_pool_json"],
        before_json,
    )
    txt_path = newly_created_or_modified(
        LOG_DIR,
        ARTIFACT_PATTERNS["final_pool_txt"],
        before_txt,
    )
    csv_path = newly_created_or_modified(
        LOG_DIR,
        ARTIFACT_PATTERNS["final_pool_csv"],
        before_csv,
    )

    if json_path is None:
        raise RuntimeError("Final Pool terminé sans nouveau JSON.")
    if txt_path is None:
        raise RuntimeError("Final Pool terminé sans nouveau TXT.")
    if csv_path is None:
        raise RuntimeError("Final Pool terminé sans nouveau CSV.")

    validation = validate_final_pool_json(json_path)

    # Vérifie les inputs embarqués par V1.2.
    payload = safe_json_load(json_path)
    inputs = payload.get("inputs") or {}
    embedded_refresh = inputs.get("refresh_json")
    embedded_recheck = inputs.get("recheck_json")

    if embedded_refresh and not same_path(embedded_refresh, refresh_path):
        raise RuntimeError(
            "Final Pool a embarqué un Refresh différent du Daily Run.\n"
            f"Attendu : {refresh_path}\n"
            f"Embarqué: {embedded_refresh}"
        )

    if embedded_recheck and not same_path(embedded_recheck, recheck_path):
        raise RuntimeError(
            "Final Pool a embarqué un Recheck différent du Daily Run.\n"
            f"Attendu : {recheck_path}\n"
            f"Embarqué: {embedded_recheck}"
        )

    validation["embedded_inputs_checked"] = True

    manifest["steps"]["final_pool"]["artifacts"] = {
        "final_pool_json": str(json_path.resolve()),
        "final_pool_txt": str(txt_path.resolve()),
        "final_pool_csv": str(csv_path.resolve()),
    }
    manifest["steps"]["final_pool"]["validation"] = validation
    manifest["steps"]["final_pool"]["status"] = "DONE"
    save_manifest(manifest)




def step_delta(manifest):
    require_completed(manifest, "final_pool")

    final_pool_path = get_step_artifact(
        manifest,
        "final_pool",
        "final_pool_json",
    )
    if not file_exists(final_pool_path):
        raise RuntimeError("Final Pool JSON mémorisé introuvable.")

    # Delta Tracker choisit automatiquement les deux derniers Final Pools.
    # On verrouille donc le CURRENT sur le Final Pool exact de ce run.
    require_latest_exact(
        ARTIFACT_PATTERNS["final_pool_json"],
        final_pool_path,
        "Delta Tracker / Final Pool actuel",
    )

    pool_validation = validate_final_pool_json(final_pool_path)

    # Il faut au moins un Final Pool historique distinct.
    valid_pool_paths = []
    for candidate in LOG_DIR.glob(
        ARTIFACT_PATTERNS["final_pool_json"]
    ):
        if not candidate.is_file():
            continue
        try:
            validate_final_pool_json(candidate)
        except Exception:
            continue
        valid_pool_paths.append(candidate)

    if len(valid_pool_paths) < 2:
        raise RuntimeError(
            "Delta Tracker nécessite au moins deux Final Pools V1.2 "
            "valides. Le run actuel ne dispose pas encore de baseline."
        )

    before_json = snapshot_glob(
        LOG_DIR,
        ARTIFACT_PATTERNS["delta_json"],
    )
    before_txt = snapshot_glob(
        LOG_DIR,
        ARTIFACT_PATTERNS["delta_txt"],
    )
    before_csv = snapshot_glob(
        LOG_DIR,
        ARTIFACT_PATTERNS["delta_csv"],
    )

    run_command(
        "delta",
        [
            sys.executable,
            "-m",
            "applications.delta_tracker",
        ],
        manifest,
    )

    json_path = newly_created_or_modified(
        LOG_DIR,
        ARTIFACT_PATTERNS["delta_json"],
        before_json,
    )
    txt_path = newly_created_or_modified(
        LOG_DIR,
        ARTIFACT_PATTERNS["delta_txt"],
        before_txt,
    )
    csv_path = newly_created_or_modified(
        LOG_DIR,
        ARTIFACT_PATTERNS["delta_csv"],
        before_csv,
    )

    if json_path is None:
        raise RuntimeError("Delta Tracker terminé sans nouveau JSON.")
    if txt_path is None:
        raise RuntimeError("Delta Tracker terminé sans nouveau TXT.")
    if csv_path is None:
        raise RuntimeError("Delta Tracker terminé sans nouveau CSV.")

    validation = validate_delta_json(
        json_path,
        expected_current_pool=final_pool_path,
        expected_current_count=pool_validation["count"],
    )

    manifest["steps"]["delta"]["artifacts"] = {
        "delta_json": str(json_path.resolve()),
        "delta_txt": str(txt_path.resolve()),
        "delta_csv": str(csv_path.resolve()),
    }
    manifest["steps"]["delta"]["validation"] = validation
    manifest["steps"]["delta"]["status"] = "DONE"
    save_manifest(manifest)


def list_handoff_zips():
    base = PROJECT_ROOT / "exports" / "chatgpt_handoff"
    if not base.exists():
        return {}
    return {
        path_identity(p): p.stat().st_mtime_ns
        for p in base.glob("handoff_v1_*.zip")
        if p.is_file()
    }


def new_handoff_zips(before):
    base = PROJECT_ROOT / "exports" / "chatgpt_handoff"
    if not base.exists():
        return []
    output = []
    for path in base.glob("handoff_v1_*.zip"):
        if not path.is_file():
            continue
        ident = path_identity(path)
        mtime = path.stat().st_mtime_ns
        old = before.get(ident)
        if old is None or mtime > old:
            output.append(path)
    return sorted(output, key=lambda p: p.stat().st_mtime_ns)



def step_lifecycle(manifest):
    require_completed(manifest, "final_pool")
    require_completed(manifest, "delta")

    final_pool_path = get_step_artifact(
        manifest,
        "final_pool",
        "final_pool_json",
    )
    delta_path = get_step_artifact(
        manifest,
        "delta",
        "delta_json",
    )

    if not file_exists(final_pool_path):
        raise RuntimeError("Final Pool JSON mémorisé introuvable.")
    if not file_exists(delta_path):
        raise RuntimeError("Delta JSON mémorisé introuvable.")

    pool_validation = validate_final_pool_json(
        final_pool_path
    )
    validate_delta_json(
        delta_path,
        expected_current_pool=final_pool_path,
        expected_current_count=pool_validation["count"],
    )

    before_json = snapshot_glob(
        LOG_DIR,
        ARTIFACT_PATTERNS["lifecycle_json"],
    )
    before_txt = snapshot_glob(
        LOG_DIR,
        ARTIFACT_PATTERNS["lifecycle_txt"],
    )

    run_command(
        "lifecycle",
        [
            sys.executable,
            "-m",
            "applications.lifecycle_daily_sync",
            "--final-pool",
            str(final_pool_path),
            "--delta",
            str(delta_path),
        ],
        manifest,
    )

    json_path = newly_created_or_modified(
        LOG_DIR,
        ARTIFACT_PATTERNS["lifecycle_json"],
        before_json,
    )
    txt_path = newly_created_or_modified(
        LOG_DIR,
        ARTIFACT_PATTERNS["lifecycle_txt"],
        before_txt,
    )

    if json_path is None:
        raise RuntimeError(
            "Lifecycle Sync terminé sans nouveau JSON."
        )
    if txt_path is None:
        raise RuntimeError(
            "Lifecycle Sync terminé sans nouveau TXT."
        )

    validation = validate_lifecycle_sync_json(
        json_path,
        expected_final_pool=final_pool_path,
        expected_delta=delta_path,
        expected_current_count=pool_validation["count"],
    )

    manifest["steps"]["lifecycle"]["artifacts"] = {
        "lifecycle_json": str(json_path.resolve()),
        "lifecycle_txt": str(txt_path.resolve()),
    }
    manifest["steps"]["lifecycle"]["validation"] = validation
    manifest["steps"]["lifecycle"]["status"] = "DONE"
    save_manifest(manifest)


def step_handoff(manifest):
    require_completed(manifest, "final_pool")
    require_completed(manifest, "delta")
    require_completed(manifest, "lifecycle")

    final_pool_path = get_step_artifact(
        manifest,
        "final_pool",
        "final_pool_json",
    )
    if not file_exists(final_pool_path):
        raise RuntimeError("Final Pool JSON mémorisé introuvable.")

    # Handoff V1 lit automatiquement le dernier Final Pool V1.2.
    require_latest_exact(
        ARTIFACT_PATTERNS["final_pool_json"],
        final_pool_path,
        "ChatGPT Handoff / Final Pool",
    )

    before = list_handoff_zips()
    chunk_size = int(manifest["settings"]["handoff_chunk_size"])

    run_command(
        "handoff",
        [
            sys.executable,
            "-m",
            "applications.chatgpt_handoff",
            "--chunk-size",
            str(chunk_size),
        ],
        manifest,
    )

    zips = new_handoff_zips(before)
    if not zips:
        raise RuntimeError("Handoff terminé sans nouveau ZIP.")

    all_zips = [p for p in zips if p.name.endswith("_ALL.zip")]
    chunk_zips = [p for p in zips if "_chunk_" in p.name]

    if not all_zips:
        raise RuntimeError("Handoff: ZIP _ALL.zip introuvable.")
    if not chunk_zips:
        raise RuntimeError("Handoff: aucun ZIP chunk produit.")

    manifest["steps"]["handoff"]["artifacts"] = {
        "all_zip": str(all_zips[-1].resolve()),
        "chunk_zips": [str(p.resolve()) for p in chunk_zips],
    }
    manifest["steps"]["handoff"]["validation"] = {
        "zip_count": len(zips),
        "chunk_count": len(chunk_zips),
    }
    manifest["steps"]["handoff"]["status"] = "DONE"
    save_manifest(manifest)


STEP_FUNCTIONS = {
    "main": step_main,
    "enrichissement": step_enrichissement,
    "preparation": step_preparation,
    "refresh": step_refresh,
    "recheck": step_recheck,
    "final_pool": step_final_pool,
    "delta": step_delta,
    "lifecycle": step_lifecycle,
    "handoff": step_handoff,
}


# ---------------------------------------------------------------------------
# RESUME + ORCHESTRATION
# ---------------------------------------------------------------------------

def normalize_manifest_for_resume(manifest):
    manifest_version = str(manifest.get("daily_run_version"))
    compatible_versions = {
        "1.0",
        "1.0.1",
        "1.0.2",
        "1.1.0",
        "1.1.1",
        "1.2.0",
        "1.2.1",
        "1.2.2",
    }
    if manifest_version not in compatible_versions:
        raise RuntimeError(
            f"Manifest Daily Run {manifest_version} "
            f"incompatible avec orchestrateur {DAILY_RUN_VERSION}."
        )

    # Hotfix 1.0.1 : on peut reprendre sans recollecter un run commencé
    # avec V1.0. Le manifest garde son run_id et ses artefacts exacts.
    manifest["daily_run_version"] = DAILY_RUN_VERSION

    # Migration des manifests anciens : toute étape absente est ajoutée en
    # PENDING, sans invalider les étapes métier déjà DONE.
    #
    # Cette boucle remplace deux blocs écrits à la main, l'un pour Delta,
    # l'autre pour Lifecycle. Chaque nouvelle étape du pipeline obligeait à
    # rapiécer la migration, et l'oubli se voyait seulement au moment d'une
    # reprise — c'est-à-dire au pire moment, quand un run a déjà échoué.
    steps = manifest.setdefault("steps", {})
    for nom in STEP_ORDER:
        if nom not in steps:
            steps[nom] = {
                "status": "PENDING",
                "started_at": None,
                "finished_at": None,
                "command": None,
                "log": None,
                "artifacts": {},
                "validation": {},
                "error": None,
            }

    if manifest.get("status") == "COMPLETED":
        raise RuntimeError(
            "Le dernier Daily Run est déjà COMPLETED : rien à reprendre."
        )

    manifest["resume_count"] = int(manifest.get("resume_count") or 0) + 1
    manifest["status"] = "RUNNING"
    manifest["finished_at"] = None
    manifest["last_error"] = None

    # Une étape RUNNING au moment d'un crash est considérée FAILED et
    # sera relancée ; les étapes DONE ne sont jamais relancées.
    for step in STEP_ORDER:
        row = manifest["steps"][step]
        if row.get("status") == "RUNNING":
            row["status"] = "FAILED"
            row["error"] = "Run précédent interrompu pendant cette étape."

    save_manifest(manifest)
    return manifest


def first_step_to_run(manifest):
    for step in STEP_ORDER:
        if step == "handoff" and not manifest["settings"]["handoff_enabled"]:
            continue
        if manifest["steps"][step]["status"] != "DONE":
            return step
    return None


def should_stop_after(manifest, step):
    stop_after = manifest["settings"].get("stop_after")
    return bool(stop_after and stop_after == step)


def mark_skipped_handoff(manifest):
    if manifest["settings"]["handoff_enabled"]:
        return
    row = manifest["steps"]["handoff"]
    if row["status"] == "PENDING":
        row["status"] = "SKIPPED"
        row["started_at"] = now_iso()
        row["finished_at"] = row["started_at"]
        row["error"] = None
        save_manifest(manifest)


def run_pipeline(manifest):
    settings = manifest["settings"]

    start_step = first_step_to_run(manifest)

    if start_step is None:
        manifest["status"] = "COMPLETED"
        manifest["finished_at"] = now_iso()
        save_manifest(manifest)
        return manifest

    start_index = STEP_ORDER.index(start_step)

    for step in STEP_ORDER[start_index:]:
        if step == "handoff" and not settings["handoff_enabled"]:
            mark_skipped_handoff(manifest)
            break

        if manifest["steps"][step]["status"] == "DONE":
            continue

        STEP_FUNCTIONS[step](manifest)

        if should_stop_after(manifest, step):
            manifest["status"] = "STOPPED_OK"
            manifest["finished_at"] = now_iso()
            save_manifest(manifest)
            print()
            print(f"✅ Arrêt volontaire après {step}.")
            return manifest

    manifest["status"] = "COMPLETED"
    manifest["finished_at"] = now_iso()
    save_manifest(manifest)
    return manifest


def print_final_summary(manifest):
    print()
    print("=" * 100)
    print("JOB HUNTER DAILY RUN V1.2 - BILAN")
    print("=" * 100)
    print("Run ID :", manifest["run_id"])
    print("Status :", manifest["status"])
    print()

    for step in STEP_ORDER:
        row = manifest["steps"][step]
        print(f"{step:<14}: {row['status']}")

    paths = manifest_paths(manifest["run_id"])
    print()
    print("Manifest JSON :", paths["json"])
    print("Manifest TXT  :", paths["txt"])

    pool_validation = (
        manifest["steps"].get("final_pool", {}).get("validation") or {}
    )
    if pool_validation:
        print()
        print("Final Pool :", pool_validation.get("count"))
        actions = pool_validation.get("actions") or {}
        for action in (
            "APPLY_NOW",
            "APPLY_NEXT",
            "REVIEW_FIRST",
            "DO_NOT_APPLY",
        ):
            print(f"  {action:<15}: {actions.get(action, 0)}")

    delta_validation = (
        manifest["steps"].get("delta", {}).get("validation") or {}
    )
    if delta_validation:
        counters = delta_validation.get("counters") or {}
        print()
        print("Delta Tracker :")
        for name in (
            "NEW",
            "REACTIVATED",
            "REPOSTED",
            "UPDATED",
            "UNCHANGED",
            "DISAPPEARED",
        ):
            print(f"  {name:<15}: {counters.get(name, 0)}")
        print(
            "  NEW APPLY_NOW  :",
            delta_validation.get("new_apply_now", 0),
        )

    lifecycle_validation = (
        manifest["steps"].get("lifecycle", {}).get("validation") or {}
    )
    if lifecycle_validation:
        print()
        print("Lifecycle Sync :")
        print(
            "  Current items :",
            lifecycle_validation.get("current_items", 0),
        )
        print(
            "  APPLIED policy:",
            lifecycle_validation.get("applied_policy"),
        )
        post_sync = lifecycle_validation.get("post_sync") or {}
        print(
            "  Non-USER APPLIED:",
            post_sync.get("non_user_applied", 0),
        )

    handoff = manifest["steps"].get("handoff", {})
    if handoff.get("status") == "DONE":
        print()
        print("Handoff ALL :", handoff["artifacts"].get("all_zip"))
        for path in handoff["artifacts"].get("chunk_zips", []):
            print("Handoff chunk:", path)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Job Hunter Belgium Daily Run V1.2"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Préflight uniquement, aucune collecte.",
    )
    parser.add_argument(
        "--resume-latest",
        action="store_true",
        help="Reprendre le dernier Daily Run interrompu.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_PREPARATION_LIMIT,
        help="Nombre max d'offres Application Preparation.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_HANDOFF_CHUNK_SIZE,
        help="Taille des lots ChatGPT Handoff.",
    )
    parser.add_argument(
        "--no-handoff",
        action="store_true",
        help="Exécuter jusqu’au Lifecycle Sync puis ignorer le Handoff.",
    )
    parser.add_argument(
        "--stop-after",
        choices=STEP_ORDER,
        default=None,
        help="Arrêt volontaire après cette étape.",
    )
    parser.add_argument(
        "--clear-lock",
        action="store_true",
        help="Supprime un lock abandonné puis quitte.",
    )
    return parser.parse_args()


def main_cli():
    args = parse_args()

    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    if args.clear_lock:
        if LOCK_PATH.exists():
            LOCK_PATH.unlink()
            print("✅ Lock supprimé :", LOCK_PATH)
        else:
            print("ℹ️ Aucun lock à supprimer.")
        return 0

    preflight = run_preflight()
    print_preflight(preflight)

    if not preflight["ok"]:
        return 1

    if args.check:
        return 0

    manifest = None

    try:
        if args.resume_latest:
            manifest = load_latest_manifest()
            manifest = normalize_manifest_for_resume(manifest)
        else:
            manifest = new_manifest(args)

        manifest["preflight"] = preflight
        save_manifest(manifest)

        acquire_lock(manifest["run_id"])

        result = run_pipeline(manifest)
        print_final_summary(result)

        # JOBHUNTER_BACKUP_RETENTION_V1_START
        if result["status"] == "COMPLETED":
            try:
                from database.backup_retention import enforce_backup_retention
                retention = enforce_backup_retention(keep=3, apply=True, write_report=True, verbose=True)
                if retention.get("errors"):
                    print("WARNING: backup retention completed with errors; Daily Run remains successful.")
            except Exception as retention_error:
                print("WARNING: backup retention failed; Daily Run remains successful:", retention_error)
        # JOBHUNTER_BACKUP_RETENTION_V1_END

        if result["status"] in {"COMPLETED", "STOPPED_OK"}:
            return 0
        return 1

    except Exception as exc:
        if manifest is not None:
            manifest["status"] = "FAILED"
            manifest["finished_at"] = now_iso()
            manifest["last_error"] = (
                f"{type(exc).__name__}: {exc}\n\n"
                + traceback.format_exc()
            )

            # COMMAND_OK signifie : subprocess terminé avec code 0,
            # mais validation d'artefact non finalisée. À la reprise,
            # cette étape sera relancée car seule DONE est considérée finie.
            for step in STEP_ORDER:
                row = manifest["steps"][step]
                if row.get("status") in {"RUNNING", "COMMAND_OK"}:
                    row["status"] = "FAILED"
                    if not row.get("error"):
                        row["error"] = (
                            "Étape interrompue ou validation d'artefact échouée."
                        )

            save_manifest(manifest)

        print()
        print("❌ DAILY RUN INTERROMPU")
        print(type(exc).__name__ + ":", exc)
        if manifest is not None:
            paths = manifest_paths(manifest["run_id"])
            print("Manifest :", paths["json"])
            print()
            print("Pour reprendre après correction :")
            print("python daily_run.py --resume-latest")
        return 1

    finally:
        release_lock()


if __name__ == "__main__":
    raise SystemExit(main_cli())
