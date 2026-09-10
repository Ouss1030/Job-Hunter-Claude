import re
"""
JOB HUNTER BELGIUM
MAIN - VERSION 10.9

Ajouts V10.4
============
- SmartRecruiters intégré nativement comme 5e canal de collecte ;
- SGS, Eurofins et Sopra Steria via Posting API ;
- descriptions SmartRecruiters déjà détaillées, sans second fetch ;
- Application Gate V1.3 production ;
- autorité canonique adaptée aux employeurs directs.

Historique V10.3
- avancement global clair sur 7 étapes ;
- barre de progression globale ;
- temps écoulé depuis le début à chaque étape ;
- durée de chaque grande étape ;
- chronomètre total en fin de run ;
- chronomètre également affiché en cas d'erreur fatale.

Pipeline V10.3 :
1. Collecte multisource
2. Sauvegarde RAW
3. Pré-sélection métier
4. Analyse complète Travaillerpour
5. Enrichissement standard + SmartRecruiters
6. Build canonique + classement dédupliqué
7. Application Gate V1.3.2 + shortlist de candidature
8. Application Queue V1 + anti-double-candidature
"""

import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from database.db import (
    get_connection,
    get_database_summary,
    save_raw_jobs,
    upsert_raw_job,
)
from database.enriched_batch import (
    enriched_persistence_batch,
    upsert_enriched_job,
)
from database.canonical import build_canonical

from sources.forem import search_targeted_forem_jobs, convert_forem_job
from sources.forem_detail import get_forem_job_detail

from sources.actiris import search_targeted_actiris_jobs, convert_actiris_job
from sources.actiris_detail import get_actiris_job_detail

from sources.talent_brussels import (
    search_targeted_talent_brussels_jobs,
    convert_talent_brussels_job,
)
from sources.talent_brussels_detail import get_talent_brussels_job_detail

from sources.travaillerpour import (
    search_targeted_travaillerpour_jobs,
    convert_travaillerpour_job,
)
from sources.travaillerpour_detail import get_travaillerpour_job_detail

from sources.smartrecruiters import fetch_smartrecruiters_jobs
from sources.jobat_detail import get_jobat_job_detail
from sources.scienceatwork import get_scienceatwork_job_detail
from sources.randstad import get_randstad_job_detail
from sources.jeffersonwells import get_jeffersonwells_job_detail
from sources.akkodis import get_akkodis_job_detail
from sources.gsk import get_gsk_job_detail
from sources.ucb import get_ucb_job_detail
from sources.iba import get_iba_job_detail
from sources.pfizer import get_pfizer_job_detail
from sources.takeda import get_takeda_job_detail
from sources.jnj import get_jnj_job_detail
from sources.quality_assistance import get_quality_assistance_job_detail
from sources.thermofisher import get_thermofisher_job_detail
from sources.sciensano import get_sciensano_job_detail
from sources.sanofi import get_sanofi_job_detail
from sources.baxter import get_baxter_job_detail
from sources.novartis import get_novartis_job_detail
from sources.registry import collect_enabled_sources
from sources.source_yield import print_source_yield_report

from database.reprise_stock import (
    REPRISE_STOCK_VERSION,
    charger_stock_actif,
    cles_de_collecte,
)
from matching.texte_parasite import raison_parasite
from matching.basic_matcher import score_job, print_job_match
from matching.application_gate import (
    export_application_gate,
    gate_summary,
    partition_gate_results,
)
from matching.application_gate_v13 import apply_application_gate
from matching.application_queue_v12 import (
    build_application_queue,
    export_application_queue,
    partition_application_queue,
    queue_summary,
)


# ============================================================
# CONFIG
# ============================================================

FOREM_MAX_PER_KEYWORD = 100
ACTIRIS_MAX_PER_KEYWORD = 100
TOP_RESULTS = 40
TOP_PRIORITY = 30
TOP_GATE_APPLY = 40
TOP_GATE_STRETCH = 25
TOP_GATE_VERIFY = 25
TOP_GATE_REJECT = 20
TOP_QUEUE_APPLY = 35
TOP_QUEUE_STRETCH = 20
TOP_QUEUE_VERIFY = 15
TOP_QUEUE_HOLD = 25
API_DELAY_SECONDS = 0.15

TRAVAILLERPOUR_REJECT_MASTER = True
TRAVAILLERPOUR_USER_OVER_26 = True

TOTAL_MAIN_STEPS = 8

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

RUN_STARTED_MONOTONIC = None
RUN_STARTED_WALL = None


# ============================================================
# TEMPS / AVANCEMENT
# ============================================================

def format_duration(seconds):
    seconds = max(0, int(round(float(seconds or 0))))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def get_run_elapsed_seconds():
    if RUN_STARTED_MONOTONIC is None:
        return 0.0
    return time.perf_counter() - RUN_STARTED_MONOTONIC


def make_progress_bar(completed, total, width=32):
    if total <= 0:
        ratio = 0.0
    else:
        ratio = min(max(completed / total, 0.0), 1.0)

    filled = int(round(ratio * width))
    bar = "#" * filled + "-" * (width - filled)
    percent = ratio * 100
    return f"[{bar}] {percent:6.1f}%"


class MainProgressTracker:
    def __init__(self, total_steps=TOTAL_MAIN_STEPS):
        self.total_steps = total_steps
        self.step_started_at = None
        self.step_number = None
        self.step_label = None
        self.step_durations = []

    def start_step(self, number, label):
        self.step_number = number
        self.step_label = label
        self.step_started_at = time.perf_counter()

        print()
        print("=" * 76)
        print(f"AVANCEMENT GLOBAL - ÉTAPE {number}/{self.total_steps}")
        print("=" * 76)
        print(make_progress_bar(number - 1, self.total_steps))
        print("Étape      :", label)
        print("Écoulé     :", format_duration(get_run_elapsed_seconds()))
        print("Heure      :", datetime.now().strftime("%H:%M:%S"))
        print()

    def finish_step(self):
        if self.step_started_at is None:
            return

        duration = time.perf_counter() - self.step_started_at
        self.step_durations.append(
            {
                "number": self.step_number,
                "label": self.step_label,
                "duration": duration,
            }
        )

        print()
        print("-" * 76)
        print(
            f"✅ ÉTAPE {self.step_number}/{self.total_steps} TERMINÉE - "
            f"{self.step_label}"
        )
        print(make_progress_bar(self.step_number, self.total_steps))
        print("Durée étape :", format_duration(duration))
        print("Temps total :", format_duration(get_run_elapsed_seconds()))
        print("-" * 76)

        self.step_started_at = None

    def print_final_timing(self):
        print()
        print("=" * 76)
        print("                  CHRONOMÈTRE DU RUN")
        print("=" * 76)
        print()

        if RUN_STARTED_WALL is not None:
            print("Début       :", RUN_STARTED_WALL.strftime("%d/%m/%Y %H:%M:%S"))

        print("Fin         :", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        print("Durée totale:", format_duration(get_run_elapsed_seconds()))

        if self.step_durations:
            print()
            print("Durée par grande étape :")
            for item in self.step_durations:
                print(
                    f"  {item['number']}/{self.total_steps} "
                    f"{format_duration(item['duration'])} | {item['label']}"
                )

        print()
        print(make_progress_bar(self.total_steps, self.total_steps))


# ============================================================
# LOGGER
# ============================================================

class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            try:
                stream.write(data)
                stream.flush()
            except Exception:
                pass

    def flush(self):
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass


def start_main_logging():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = LOG_DIR / f"job_hunter_main_v10_4_1_{timestamp}.txt"
    file = path.open("w", encoding="utf-8")

    stdout = sys.stdout
    stderr = sys.stderr

    sys.stdout = Tee(stdout, file)
    sys.stderr = Tee(stderr, file)

    return {
        "path": path,
        "file": file,
        "stdout": stdout,
        "stderr": stderr,
    }


def stop_main_logging(logger):
    sys.stdout = logger["stdout"]
    sys.stderr = logger["stderr"]
    try:
        logger["file"].close()
    except Exception:
        pass


# ============================================================
# TEXT
# ============================================================

def clean_value(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_value(value):
    return clean_value(value).lower().replace("’", "'")


# ============================================================
# JOB IDENTITY
# ============================================================

def get_job_source(job):
    return (getattr(job, "source", None) or "INCONNUE").upper()


def get_job_origin(job):
    origin = getattr(job, "origin_source", None)
    if origin:
        return str(origin).upper()
    return get_job_source(job)


def get_job_collection_channel(job):
    value = getattr(job, "collection_channel", None)
    if value:
        return str(value).upper()
    return get_job_source(job)


def get_job_external_id(job):
    return clean_value(getattr(job, "external_id", None))


# ============================================================
# ACTIRIS OFFER TYPE
# ============================================================

def get_actiris_offer_type(job):
    direct = getattr(job, "actiris_offer_type", None)
    if direct:
        return direct

    if not job.url:
        return None

    try:
        parsed = urlparse(job.url)
        query = parse_qs(parsed.query)
        values = query.get("type", [])
        if values:
            return values[0]
    except Exception:
        pass

    return None


# ============================================================
# COLLECT FOREM
# ============================================================

def collect_forem_jobs():
    print()
    print("=" * 76)
    print("                     SOURCE 1 - FOREM")
    print("=" * 76)

    raw_jobs = search_targeted_forem_jobs(max_per_keyword=FOREM_MAX_PER_KEYWORD)
    jobs = []

    for raw_job in raw_jobs:
        try:
            job = convert_forem_job(raw_job)
            job.collection_channel = "FOREM"
            job.origin_source = "FOREM"
            jobs.append(job)
        except Exception as error:
            print("⚠️ Conversion Forem impossible :", error)

    print()
    print("FOREM - offres converties :", len(jobs))
    return jobs


# ============================================================
# COLLECT ACTIRIS
# ============================================================

def collect_actiris_jobs():
    print()
    print("=" * 76)
    print("                    SOURCE 2 - ACTIRIS")
    print("=" * 76)

    raw_jobs = search_targeted_actiris_jobs(max_per_keyword=ACTIRIS_MAX_PER_KEYWORD)
    jobs = []

    for raw_job in raw_jobs:
        try:
            jobs.append(convert_actiris_job(raw_job))
        except Exception as error:
            print("⚠️ Conversion Actiris impossible :", error)

    print()
    print("ACTIRIS - offres converties :", len(jobs))

    origins = Counter(get_job_origin(job) for job in jobs)
    print()
    print("ACTIRIS - provenance :")
    for origin, count in origins.most_common():
        print(f"  {origin:<15} {count}")

    return jobs


# ============================================================
# COLLECT TALENT
# ============================================================

def collect_talent_jobs():
    print()
    print("=" * 76)
    print("                SOURCE 3 - TALENT.BRUSSELS")
    print("=" * 76)

    raw_jobs = search_targeted_talent_brussels_jobs()
    jobs = []

    for raw_job in raw_jobs:
        try:
            jobs.append(convert_talent_brussels_job(raw_job))
        except Exception as error:
            print("⚠️ Conversion Talent impossible :", error)

    print()
    print("TALENT.BRUSSELS - offres :", len(jobs))
    return jobs


# ============================================================
# COLLECT TRAVAILLERPOUR
# ============================================================

def collect_travaillerpour_jobs():
    print()
    print("=" * 76)
    print("                SOURCE 4 - TRAVAILLERPOUR")
    print("=" * 76)

    raw_jobs = search_targeted_travaillerpour_jobs()
    jobs = []

    for raw_job in raw_jobs:
        try:
            jobs.append(convert_travaillerpour_job(raw_job))
        except Exception as error:
            print("⚠️ Conversion Travaillerpour impossible :", error)

    print()
    print("TRAVAILLERPOUR - offres :", len(jobs))
    return jobs


# ============================================================
# COLLECT SMARTRECRUITERS
# ============================================================

def collect_smartrecruiters_jobs():
    print()
    print("=" * 76)
    print("           SOURCE 5 - SMARTRECRUITERS DIRECT EMPLOYERS")
    print("=" * 76)

    jobs, metas = fetch_smartrecruiters_jobs()

    total_failures = 0
    fatal_errors = 0

    for meta in metas:
        label = clean_value(meta.get("label")) or clean_value(
            meta.get("company_identifier")
        )
        belgium = int(meta.get("listings_belgium") or 0)
        converted = int(meta.get("jobs_converted") or 0)
        failures = len(meta.get("failures") or [])
        fatal = clean_value(meta.get("fatal_error"))

        total_failures += failures
        fatal_errors += int(bool(fatal))

        print(
            f"  {label:<20} "
            f"BE={belgium:<4} "
            f"converties={converted:<4} "
            f"échecs={failures}"
        )
        if fatal:
            print("      ❌", fatal)

    print()
    print("SMARTRECRUITERS - offres converties :", len(jobs))
    print("SMARTRECRUITERS - échecs détail      :", total_failures)
    print("SMARTRECRUITERS - erreurs fatales    :", fatal_errors)

    return jobs

# ============================================================
# COLLECT ALL
# ============================================================

def collect_all_jobs():
    # V10.5 : la liste des sources n'est plus câblée ici.
    # Le registre central sources/registry.py décide quelles sources sont actives.
    return collect_enabled_sources()


# ============================================================
# RAW DATABASE
# ============================================================

def persist_initial_raw_collection(all_jobs):
    print()
    print("=" * 76)
    print("          DATABASE V2.1 - SAUVEGARDE RAW INITIALE")
    print("=" * 76)
    print()
    print("Offres à sauvegarder :", len(all_jobs))

    result = save_raw_jobs(
        all_jobs,
        notes=(
            "MAIN V10.5 - RAW immédiatement après collecte "
            "avant tout filtre métier"
        ),
    )

    print()
    print("RUN DB       :", result["run_id"])
    print("Total        :", result["total"])
    print("Insérées     :", result["inserted"])
    print("Mises à jour :", result["updated"])
    print("Erreurs      :", result["errors"])

    if result["error_details"]:
        print()
        print("ERREURS RAW :")
        for error in result["error_details"][:20]:
            print("  ", error)

    return result


def persist_enriched_job(job, run_id):
    try:
        upsert_enriched_job(job, run_id=run_id)
        return True
    except Exception as error:
        print()
        print("⚠️ DATABASE UPDATE impossible")
        print("Source :", get_job_source(job))
        print("ID     :", getattr(job, "external_id", None))
        print("Titre  :", job.title)
        print("Erreur :", error)
        return False


THIN_DESCRIPTION_SECOND_GATE_LIMIT = 300

THIN_DESCRIPTION_TITLE_PATTERNS = [
    r"\bjunior\s+data\s+analyst\b",
    r"\bdata\s+analyst\b",
    r"\banalyste\s+(?:de\s+)?donn[eé]es\b",
    r"\bbi\s+analyst\b",
    r"\banalyste\s+bi\b",
    r"\bpower\s*bi\b",
    r"\bdata\s+quality\b",
    r"\bdata\s+steward\b",
    r"\bmaster\s+data\b",
    r"\bdata\s+integrity\b",
    r"\blab(?:oratory)?\s+assistant\b",
    r"\blab(?:oratory)?\s+(?:technician|analyst)\b",
    r"\btechnicien(?:ne)?\s+(?:de\s+)?laboratoire\b",
    r"\blaborantin(?:e)?\b",
    r"\banalyste\s+(?:de\s+)?laboratoire\b",
    r"\bqc\s+(?:analyst|technician|specialist|officer)\b",
    r"\banalyst(?:e)?\s+qc\b",
    r"\bquality\s+control\b",
    r"\bcontr[oô]le\s+qualit[eé]\b",
    r"\bquality\s+assurance\b",
    r"\bassurance\s+qualit[eé]\b",
    r"\bqa\s+(?:officer|specialist|associate|technician|analyst)\b",
    r"\bdata\s+coordinator\b",
    r"\bjunior\s+data\s+scientist\b",
    r"\b(?:production|manufacturing|bioprocess|process)\s+technician\b",
    r"\btechnicien(?:ne)?\s+chimiste\b",
]

THIN_DESCRIPTION_TITLE_EXCLUSIONS = [
    r"\bsenior\b",
    r"\bsr\.?\b",
    r"\bprincipal\b",
    r"\bstaff\b",
    r"\bdirector\b",
    r"\bdirecteur\b",
    r"\bhead\b",
    r"\bvp\b",
    r"\bmanager\b",
    r"\bteam\s+lead(?:er)?\b",
    r"\bsupervisor\b",
    r"\bsuperviseur\b",
    r"\bintern(?:ship)?\b",
    r"\bstage\b",
    r"\bstagiaire\b",
    r"\bstudent\b",
    r"\btrainee\b",
    r"\bapprentice\b",
    r"\bph\.?d\.?\b",
    r"\bdoctorat\b",
    r"\bqualified\s+person\b",
]


def should_second_gate_thin_description(job):
    title = str(getattr(job, "title", "") or "").strip()
    description = str(getattr(job, "description", "") or "").strip()

    if len(description) >= THIN_DESCRIPTION_SECOND_GATE_LIMIT:
        return False

    if not title:
        return False

    if any(
        re.search(pattern, title, re.I)
        for pattern in THIN_DESCRIPTION_TITLE_EXCLUSIONS
    ):
        return False

    return any(
        re.search(pattern, title, re.I)
        for pattern in THIN_DESCRIPTION_TITLE_PATTERNS
    )


# ============================================================
# PRE SCORE
# ============================================================

def pre_score_jobs(jobs):
    results = []
    total = len(jobs)

    for index, job in enumerate(jobs, start=1):
        try:
            results.append((job, score_job(job)))
        except Exception as error:
            print()
            print("⚠️ Erreur pré-score :", job.source, "|", job.title)
            print(error)

        if total and (index % 500 == 0 or index == total):
            print(
                f"Pré-score standard : {index}/{total} "
                f"({index / total * 100:.1f}%) | "
                f"écoulé {format_duration(get_run_elapsed_seconds())}"
            )

    return results


def select_candidate_jobs(pre_scored_jobs):
    selected = []
    second_gate_count = 0

    for job, result in pre_scored_jobs:
        if result["core_relevance"]:
            selected.append((job, result))
            continue

        if should_second_gate_thin_description(job):
            selected.append((job, result))
            second_gate_count += 1

    if second_gate_count:
        print(
            "Second gate descriptions courtes :",
            second_gate_count,
            "offre(s) ajoutée(s) avant enrichissement",
        )

    return selected


# ============================================================
# DETAIL ROUTER
# ============================================================

def get_job_detail(job):
    source = get_job_source(job)

    if source == "FOREM":
        return get_forem_job_detail(job.external_id, use_cache=True)

    if source == "ACTIRIS":
        return get_actiris_job_detail(
            reference=job.external_id,
            offer_type=get_actiris_offer_type(job),
            use_cache=True,
        )

    if source == "TALENT_BRUSSELS":
        return get_talent_brussels_job_detail(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
        )

    if source == "SMARTRECRUITERS":
        text = clean_value(getattr(job, "description", ""))
        if text:
            return {
                "success": True,
                "matching_text": text,
                "matching_text_length": len(text),
                "structured": {},
                "from_cache": True,
                "error": None,
            }
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": {},
            "from_cache": True,
            "error": "SmartRecruiters : description détaillée vide.",
        }

    if source == "JOBAT":
        return get_jobat_job_detail(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
        )

    if source == "SCIENCEATWORK":
        # La collecte Science@Work récupère déjà la fiche complète.
        # On réutilise ce texte ici pour éviter un second appel réseau inutile.
        text = clean_value(getattr(job, "description", ""))
        if text:
            return {
                "success": True,
                "matching_text": text,
                "matching_text_length": len(text),
                "structured": {
                    "title": clean_value(getattr(job, "title", "")),
                    "company": clean_value(getattr(job, "company", "")),
                    "location": clean_value(getattr(job, "location", "")),
                    "contract_type": clean_value(getattr(job, "contract_type", "")),
                    "language": clean_value(getattr(job, "language", "")),
                    "date_published": clean_value(getattr(job, "date_published", "")),
                },
                "from_cache": True,
                "error": None,
            }
        return get_scienceatwork_job_detail(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
        )

    if source == "RANDSTAD":
        # La collecte Randstad récupère déjà la fiche complète.
        text = clean_value(getattr(job, "description", ""))
        if text:
            return {
                "success": True,
                "matching_text": text,
                "matching_text_length": len(text),
                "structured": {
                    "title": clean_value(getattr(job, "title", "")),
                    "company": clean_value(getattr(job, "company", "")),
                    "location": clean_value(getattr(job, "location", "")),
                    "contract_type": clean_value(getattr(job, "contract_type", "")),
                    "language": clean_value(getattr(job, "language", "")),
                    "date_published": clean_value(getattr(job, "date_published", "")),
                    "randstad_reference": clean_value(getattr(job, "randstad_reference", "")),
                },
                "from_cache": True,
                "error": None,
            }
        return get_randstad_job_detail(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
        )

    if source == "JEFFERSON_WELLS":
        text = clean_value(getattr(job, "description", ""))
        if text:
            return {
                "success": True,
                "matching_text": text,
                "matching_text_length": len(text),
                "structured": {
                    "title": clean_value(getattr(job, "title", "")),
                    "company": clean_value(getattr(job, "company", "")),
                    "location": clean_value(getattr(job, "location", "")),
                    "contract_type": clean_value(getattr(job, "contract_type", "")),
                    "language": clean_value(getattr(job, "language", "")),
                    "date_published": clean_value(getattr(job, "date_published", "")),
                    "bullhorn_job_id": clean_value(getattr(job, "bullhorn_job_id", "")),
                },
                "from_cache": True,
                "error": None,
            }
        return get_jeffersonwells_job_detail(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
        )

    if source == "AKKODIS":
        text = clean_value(getattr(job, "description", ""))
        if text:
            return {
                "success": True,
                "matching_text": text,
                "matching_text_length": len(text),
                "structured": {
                    "title": clean_value(getattr(job, "title", "")),
                    "company": clean_value(getattr(job, "company", "")),
                    "location": clean_value(getattr(job, "location", "")),
                    "contract_type": clean_value(getattr(job, "contract_type", "")),
                    "language": clean_value(getattr(job, "language", "")),
                    "date_published": clean_value(getattr(job, "date_published", "")),
                    "akkodis_reference": clean_value(getattr(job, "akkodis_reference", "")),
                    "industry": clean_value(getattr(job, "industry", "")),
                },
                "from_cache": True,
                "error": None,
            }
        return get_akkodis_job_detail(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
        )

    if source == "GSK":
        text = clean_value(getattr(job, "description", ""))
        if text:
            return {
                "success": True,
                "matching_text": text,
                "matching_text_length": len(text),
                "structured": {
                    "title": clean_value(getattr(job, "title", "")),
                    "company": "GSK",
                    "location": clean_value(getattr(job, "location", "")),
                    "contract_type": clean_value(getattr(job, "contract_type", "")),
                    "language": clean_value(getattr(job, "language", "")),
                    "date_published": clean_value(getattr(job, "date_published", "")),
                    "external_path": clean_value(getattr(job, "workday_external_path", "")),
                    "job_requisition_id": clean_value(getattr(job, "gsk_requisition_id", "")),
                },
                "from_cache": True,
                "error": None,
            }
        return get_gsk_job_detail(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
        )

    if source == "UCB":
        text = clean_value(getattr(job, "description", ""))
        if text:
            return {
                "success": True,
                "matching_text": text,
                "matching_text_length": len(text),
                "structured": {
                    "title": clean_value(getattr(job, "title", "")),
                    "company": "UCB",
                    "location": clean_value(getattr(job, "location", "")),
                    "contract_type": clean_value(getattr(job, "contract_type", "")),
                    "language": clean_value(getattr(job, "language", "")),
                    "date_published": clean_value(getattr(job, "date_published", "")),
                    "phenom_job_seq_no": clean_value(getattr(job, "phenom_job_seq_no", "")),
                },
                "from_cache": True,
                "error": None,
            }
        return get_ucb_job_detail(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
        )

    if source == "THERMO_FISHER":
        text = clean_value(getattr(job, "description", ""))
        if text:
            return {
                "success": True,
                "matching_text": text,
                "matching_text_length": len(text),
                "structured": {
                    "title": clean_value(getattr(job, "title", "")),
                    "company": "Thermo Fisher Scientific",
                    "location": clean_value(getattr(job, "location", "")),
                    "contract_type": clean_value(getattr(job, "contract_type", "")),
                    "language": clean_value(getattr(job, "language", "")),
                    "date_published": clean_value(getattr(job, "date_published", "")),
                    "phenom_job_seq_no": clean_value(getattr(job, "phenom_job_seq_no", "")),
                },
                "from_cache": True,
                "error": None,
            }
        return get_thermofisher_job_detail(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
        )

    if source == "IBA":
        text = clean_value(getattr(job, "description", ""))
        if text:
            return {
                "success": True,
                "matching_text": text,
                "matching_text_length": len(text),
                "structured": {
                    "title": clean_value(getattr(job, "title", "")),
                    "company": "IBA",
                    "location": clean_value(getattr(job, "location", "")),
                    "contract_type": clean_value(getattr(job, "contract_type", "")),
                    "language": clean_value(getattr(job, "language", "")),
                    "date_published": clean_value(getattr(job, "date_published", "")),
                    "successfactors_job_id": clean_value(getattr(job, "successfactors_job_id", "")),
                    "category": clean_value(getattr(job, "job_category", "")),
                    "seniority": clean_value(getattr(job, "seniority_level", "")),
                    "work_regime": clean_value(getattr(job, "work_regime", "")),
                },
                "from_cache": True,
                "error": None,
            }
        return get_iba_job_detail(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
        )

    if source == "PFIZER":
        text = clean_value(getattr(job, "description", ""))
        if text:
            return {
                "success": True,
                "matching_text": text,
                "matching_text_length": len(text),
                "structured": {
                    "title": clean_value(getattr(job, "title", "")),
                    "company": "Pfizer",
                    "location": clean_value(getattr(job, "location", "")),
                    "contract_type": clean_value(getattr(job, "contract_type", "")),
                    "language": clean_value(getattr(job, "language", "")),
                    "date_published": clean_value(getattr(job, "date_published", "")),
                    "external_path": clean_value(getattr(job, "workday_external_path", "")),
                    "job_requisition_id": clean_value(getattr(job, "pfizer_requisition_id", "")),
                },
                "from_cache": True,
                "error": None,
            }
        return get_pfizer_job_detail(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
        )

    if source == "TAKEDA":
        text = clean_value(getattr(job, "description", ""))
        if text:
            return {
                "success": True,
                "matching_text": text,
                "matching_text_length": len(text),
                "structured": {
                    "title": clean_value(getattr(job, "title", "")),
                    "company": "Takeda",
                    "location": clean_value(getattr(job, "location", "")),
                    "contract_type": clean_value(getattr(job, "contract_type", "")),
                    "language": clean_value(getattr(job, "language", "")),
                    "date_published": clean_value(getattr(job, "date_published", "")),
                    "external_path": clean_value(getattr(job, "workday_external_path", "")),
                    "job_requisition_id": clean_value(getattr(job, "takeda_requisition_id", "")),
                },
                "from_cache": True,
                "error": None,
            }
        return get_takeda_job_detail(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
        )

    if source == "JNJ":
        text = clean_value(getattr(job, "description", ""))
        if text:
            return {
                "success": True,
                "matching_text": text,
                "matching_text_length": len(text),
                "structured": {
                    "title": clean_value(getattr(job, "title", "")),
                    "company": "Johnson & Johnson / Janssen",
                    "location": clean_value(getattr(job, "location", "")),
                    "contract_type": clean_value(getattr(job, "contract_type", "")),
                    "language": clean_value(getattr(job, "language", "")),
                    "date_published": clean_value(getattr(job, "date_published", "")),
                    "external_path": clean_value(getattr(job, "workday_external_path", "")),
                    "job_requisition_id": clean_value(getattr(job, "jnj_requisition_id", "")),
                },
                "from_cache": True,
                "error": None,
            }
        return get_jnj_job_detail(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
        )

    if source == "QUALITY_ASSISTANCE":
        text = clean_value(getattr(job, "description", ""))
        if text:
            return {
                "success": True,
                "matching_text": text,
                "matching_text_length": len(text),
                "structured": {
                    "title": clean_value(getattr(job, "title", "")),
                    "company": "Quality Assistance",
                    "location": clean_value(getattr(job, "location", "")),
                    "contract_type": clean_value(getattr(job, "contract_type", "")),
                    "language": clean_value(getattr(job, "language", "")),
                    "date_published": clean_value(getattr(job, "date_published", "")),
                    "quality_assistance_job_id": clean_value(getattr(job, "quality_assistance_job_id", "")),
                },
                "from_cache": True,
                "error": None,
            }
        return get_quality_assistance_job_detail(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
        )

    if source == "SCIENSANO":
        text = clean_value(getattr(job, "description", ""))
        known_detail_success = getattr(job, "detail_enrichment_success", None)
        # A search-index snippet is intentionally stored in description so the
        # matcher has some evidence, but it must never be upgraded to a full
        # detail merely because it is non-empty.
        if text and known_detail_success is not False:
            return {
                "success": True,
                "matching_text": text,
                "matching_text_length": len(text),
                "structured": {
                    "title": clean_value(getattr(job, "title", "")),
                    "company": "Sciensano",
                    "location": clean_value(getattr(job, "location", "")),
                    "contract_type": clean_value(getattr(job, "contract_type", "")),
                    "language": clean_value(getattr(job, "language", "")),
                    "date_published": clean_value(getattr(job, "date_published", "")),
                    "sciensano_job_id": clean_value(getattr(job, "sciensano_job_id", "")),
                    "application_deadline": clean_value(getattr(job, "application_deadline", "")),
                },
                "from_cache": True,
                "error": None,
            }
        return get_sciensano_job_detail(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
            fallback={
                "title": clean_value(getattr(job, "title", "")),
                "location": clean_value(getattr(job, "location", "")),
                "contract_type": clean_value(getattr(job, "contract_type", "")),
                "listing_language": clean_value(getattr(job, "language", "")),
                "search_snippet": clean_value(getattr(job, "sciensano_search_snippet", "")) or text,
                "matching_text": text,
                "discovery_only": bool(getattr(job, "sciensano_discovery_only", False)),
                "application_deadline": clean_value(getattr(job, "application_deadline", "")),
            },
        )

    if source in {"SANOFI", "BAXTER", "NOVARTIS"}:
        text = clean_value(getattr(job, "description", ""))
        if text:
            company_map = {"SANOFI": "Sanofi", "BAXTER": "Baxter", "NOVARTIS": "Novartis"}
            return {
                "success": True,
                "matching_text": text,
                "matching_text_length": len(text),
                "structured": {
                    "title": clean_value(getattr(job, "title", "")),
                    "company": company_map[source],
                    "location": clean_value(getattr(job, "location", "")),
                    "contract_type": clean_value(getattr(job, "contract_type", "")),
                    "language": clean_value(getattr(job, "language", "")),
                    "date_published": clean_value(getattr(job, "date_published", "")),
                    "external_id": clean_value(getattr(job, "external_id", "")),
                },
                "from_cache": True,
                "error": None,
            }
        detail_func = {
            "SANOFI": get_sanofi_job_detail,
            "BAXTER": get_baxter_job_detail,
            "NOVARTIS": get_novartis_job_detail,
        }[source]
        return detail_func(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
            fallback={
                "title": clean_value(getattr(job, "title", "")),
                "location": clean_value(getattr(job, "location", "")),
                "date_published": clean_value(getattr(job, "date_published", "")),
            },
        )

    if source == "TRAVAILLERPOUR":
        return get_travaillerpour_job_detail(
            url=job.url,
            external_id=job.external_id,
            use_cache=True,
        )

    return {
        "success": False,
        "matching_text": "",
        "matching_text_length": 0,
        "structured": {},
        "from_cache": False,
        "error": f"Source sans enrichisseur : {source}",
    }


# ============================================================
# STRUCTURED DATA
# ============================================================

def apply_actiris_structured_data(job, detail):
    structured = detail.get("structured", {}) or {}

    title = structured.get("title")
    if title and (not job.title or job.title == "Titre inconnu"):
        job.title = title

    company = structured.get("company")
    if company and (not job.company or job.company == "Employeur non précisé"):
        job.company = company

    location = structured.get("location")
    if location and (not job.location or job.location == "Lieu non précisé"):
        job.location = location

    contract = structured.get("contract_type")
    if contract and not job.contract_type:
        job.contract_type = contract

    languages = structured.get("languages", []) or []
    if languages:
        job.language = ", ".join(languages)

    job.experience_requirement = structured.get("experience")


def apply_talent_structured_data(job, detail):
    structured = detail.get("structured", {}) or {}

    if structured.get("contract_type"):
        job.contract_type = structured["contract_type"]
    if structured.get("salary"):
        job.salary = structured["salary"]

    languages = structured.get("languages", []) or []
    if languages:
        job.language = ", ".join(languages)

    job.application_deadline = structured.get("deadline")
    job.degree_requirement = structured.get("degree")
    job.experience_requirement = structured.get("experience")


def apply_travaillerpour_structured_data(job, detail):
    structured = detail.get("structured", {}) or {}

    if structured.get("title"):
        job.title = structured["title"]
    if structured.get("company"):
        job.company = structured["company"]

    location = structured.get("location")
    if location:
        if "belg" in normalize_value(location):
            job.location = location
        else:
            job.location = location + ", Belgique"

    if structured.get("contract_type"):
        job.contract_type = structured["contract_type"]
    if structured.get("language"):
        job.language = structured["language"]
    if structured.get("salary"):
        job.salary = structured["salary"]

    job.application_deadline = structured.get("deadline")
    job.degree_requirement = structured.get("degree")
    job.experience_requirement = structured.get("experience")
    job.restriction = structured.get("restriction")
    job.function_level = structured.get("function_level")
    job.recruitment_type = structured.get("recruitment_type")
    job.grade_scale = structured.get("grade_scale")
    job.positions_count = structured.get("positions_count")


def apply_jobat_structured_data(job, detail):
    structured = detail.get("structured", {}) or {}

    if structured.get("title"):
        job.title = structured["title"]
    if structured.get("company"):
        job.company = structured["company"]
    if structured.get("location"):
        job.location = structured["location"]
    if structured.get("contract_type"):
        job.contract_type = structured["contract_type"]
    if structured.get("language"):
        job.language = structured["language"]
    if structured.get("date_published"):
        job.date_published = structured["date_published"]


def apply_structured_data(job, detail):
    source = get_job_source(job)

    if source == "ACTIRIS":
        apply_actiris_structured_data(job, detail)
    elif source == "TALENT_BRUSSELS":
        apply_talent_structured_data(job, detail)
    elif source == "JOBAT":
        apply_jobat_structured_data(job, detail)
    elif source == "SCIENCEATWORK":
        structured = detail.get("structured", {}) or {}
        if structured.get("title"):
            job.title = structured["title"]
        if structured.get("company"):
            job.company = structured["company"]
        if structured.get("location"):
            job.location = structured["location"]
        if structured.get("contract_type"):
            job.contract_type = structured["contract_type"]
        if structured.get("language"):
            job.language = structured["language"]
        if structured.get("date_published"):
            job.date_published = structured["date_published"]
        job.degree_requirement = structured.get("degree")
        job.job_category = structured.get("category")
    elif source == "RANDSTAD":
        structured = detail.get("structured", {}) or {}
        if structured.get("title"):
            job.title = structured["title"]
        if structured.get("company"):
            job.company = structured["company"]
        if structured.get("location"):
            job.location = structured["location"]
        if structured.get("contract_type"):
            job.contract_type = structured["contract_type"]
        if structured.get("language"):
            job.language = structured["language"]
        if structured.get("date_published"):
            job.date_published = structured["date_published"]
        job.randstad_reference = structured.get("randstad_reference")
    elif source == "JEFFERSON_WELLS":
        structured = detail.get("structured", {}) or {}
        if structured.get("title"):
            job.title = structured["title"]
        if structured.get("company"):
            job.company = structured["company"]
        if structured.get("location"):
            job.location = structured["location"]
        if structured.get("contract_type"):
            job.contract_type = structured["contract_type"]
        if structured.get("language"):
            job.language = structured["language"]
        if structured.get("date_published"):
            job.date_published = structured["date_published"]
        job.bullhorn_job_id = structured.get("bullhorn_job_id")
        job.valid_through = structured.get("valid_through")
    elif source == "AKKODIS":
        structured = detail.get("structured", {}) or {}
        if structured.get("title"):
            job.title = structured["title"]
        if structured.get("company"):
            job.company = structured["company"]
        if structured.get("location"):
            job.location = structured["location"]
        if structured.get("contract_type"):
            job.contract_type = structured["contract_type"]
        if structured.get("language"):
            job.language = structured["language"]
        if structured.get("date_published"):
            job.date_published = structured["date_published"]
        job.akkodis_reference = structured.get("akkodis_reference")
        job.industry = structured.get("industry")
        job.job_category = structured.get("category")
        job.experience_requirement = structured.get("experience")
    elif source == "GSK":
        structured = detail.get("structured", {}) or {}
        if structured.get("title"):
            job.title = structured["title"]
        job.company = "GSK"
        if structured.get("location"):
            job.location = structured["location"]
        if structured.get("contract_type"):
            job.contract_type = structured["contract_type"]
        if structured.get("language"):
            job.language = structured["language"]
        if structured.get("date_published"):
            job.date_published = structured["date_published"]
        job.workday_external_path = structured.get("external_path")
        job.gsk_requisition_id = structured.get("job_requisition_id") or structured.get("external_id")
    elif source == "UCB":
        structured = detail.get("structured", {}) or {}
        if structured.get("title"):
            job.title = structured["title"]
        job.company = "UCB"
        if structured.get("location"):
            job.location = structured["location"]
        if structured.get("contract_type"):
            job.contract_type = structured["contract_type"]
        if structured.get("language"):
            job.language = structured["language"]
        if structured.get("date_published"):
            job.date_published = structured["date_published"]
        job.phenom_job_seq_no = structured.get("phenom_job_seq_no") or structured.get("external_id")
    elif source == "THERMO_FISHER":
        structured = detail.get("structured", {}) or {}
        if structured.get("title"):
            job.title = structured["title"]
        job.company = "Thermo Fisher Scientific"
        if structured.get("location"):
            job.location = structured["location"]
        if structured.get("contract_type"):
            job.contract_type = structured["contract_type"]
        if structured.get("language"):
            job.language = structured["language"]
        if structured.get("date_published"):
            job.date_published = structured["date_published"]
        job.phenom_job_seq_no = structured.get("phenom_job_seq_no") or structured.get("external_id")
        job.thermofisher_job_id = job.phenom_job_seq_no
    elif source == "IBA":
        structured = detail.get("structured", {}) or {}
        if structured.get("title"):
            job.title = structured["title"]
        job.company = "IBA"
        if structured.get("location"):
            job.location = structured["location"]
        if structured.get("contract_type"):
            job.contract_type = structured["contract_type"]
        if structured.get("language"):
            job.language = structured["language"]
        if structured.get("date_published"):
            job.date_published = structured["date_published"]
        job.successfactors_job_id = structured.get("successfactors_job_id") or structured.get("external_id")
        job.job_category = structured.get("category")
        job.seniority_level = structured.get("seniority")
        job.work_regime = structured.get("work_regime")
    elif source == "PFIZER":
        structured = detail.get("structured", {}) or {}
        if structured.get("title"):
            job.title = structured["title"]
        job.company = "Pfizer"
        if structured.get("location"):
            job.location = structured["location"]
        if structured.get("contract_type"):
            job.contract_type = structured["contract_type"]
        if structured.get("language"):
            job.language = structured["language"]
        if structured.get("date_published"):
            job.date_published = structured["date_published"]
        job.workday_external_path = structured.get("external_path")
        job.pfizer_requisition_id = structured.get("job_requisition_id") or structured.get("external_id")
    elif source == "TAKEDA":
        structured = detail.get("structured", {}) or {}
        if structured.get("title"):
            job.title = structured["title"]
        job.company = "Takeda"
        if structured.get("location"):
            job.location = structured["location"]
        if structured.get("contract_type"):
            job.contract_type = structured["contract_type"]
        if structured.get("language"):
            job.language = structured["language"]
        if structured.get("date_published"):
            job.date_published = structured["date_published"]
        job.workday_external_path = structured.get("external_path")
        job.takeda_requisition_id = structured.get("job_requisition_id") or structured.get("external_id")
    elif source == "JNJ":
        structured = detail.get("structured", {}) or {}
        if structured.get("title"):
            job.title = structured["title"]
        job.company = "Johnson & Johnson / Janssen"
        if structured.get("location"):
            job.location = structured["location"]
        if structured.get("contract_type"):
            job.contract_type = structured["contract_type"]
        if structured.get("language"):
            job.language = structured["language"]
        if structured.get("date_published"):
            job.date_published = structured["date_published"]
        job.workday_external_path = structured.get("external_path")
        job.jnj_requisition_id = structured.get("job_requisition_id") or structured.get("external_id")
    elif source == "QUALITY_ASSISTANCE":
        structured = detail.get("structured", {}) or {}
        if structured.get("title"):
            job.title = structured["title"]
        job.company = "Quality Assistance"
        if structured.get("location"):
            job.location = structured["location"]
        if structured.get("contract_type"):
            job.contract_type = structured["contract_type"]
        if structured.get("language"):
            job.language = structured["language"]
        if structured.get("date_published"):
            job.date_published = structured["date_published"]
        job.quality_assistance_job_id = structured.get("quality_assistance_job_id") or structured.get("external_id")
    elif source == "SCIENSANO":
        structured = detail.get("structured", {}) or {}
        if structured.get("title"):
            job.title = structured["title"]
        job.company = "Sciensano"
        if structured.get("location"):
            job.location = structured["location"]
        if structured.get("contract_type"):
            job.contract_type = structured["contract_type"]
        if structured.get("language"):
            job.language = structured["language"]
        if structured.get("date_published"):
            job.date_published = structured["date_published"]
        job.sciensano_job_id = structured.get("sciensano_job_id") or structured.get("external_id")
        job.application_deadline = structured.get("application_deadline")
    elif source in {"SANOFI", "BAXTER", "NOVARTIS"}:
        structured = detail.get("structured", {}) or {}
        if structured.get("title"):
            job.title = structured["title"]
        job.company = {"SANOFI": "Sanofi", "BAXTER": "Baxter", "NOVARTIS": "Novartis"}[source]
        if structured.get("location"):
            job.location = structured["location"]
        if structured.get("contract_type"):
            job.contract_type = structured["contract_type"]
        if structured.get("language"):
            job.language = structured["language"]
        if structured.get("date_published"):
            job.date_published = structured["date_published"]
        if source == "SANOFI":
            job.sanofi_job_id = structured.get("sanofi_job_id") or structured.get("external_id")
        elif source == "BAXTER":
            job.baxter_job_id = structured.get("baxter_job_id") or structured.get("external_id")
        else:
            job.novartis_job_id = structured.get("novartis_job_id") or structured.get("external_id")
        job.radancy_requisition_id = structured.get("requisition_id")

    elif source == "TRAVAILLERPOUR":
        apply_travaillerpour_structured_data(job, detail)


def apply_detail_description(job, detail):
    detailed = detail.get("matching_text", "") or ""
    if not detailed:
        return

    # Un bloc « offres similaires » n'est pas une description.
    #
    # Point de passage unique de tout texte enrichi : c'est ici, et nulle
    # part ailleurs, qu'une extraction ratee contaminait a la fois
    # detail_matching_text ET description. Le refus est donc pose ici.
    #
    # On n'ecrit rien : la description d'origine, si elle existe, vaut
    # toujours mieux qu'une liste d'autres postes. L'echec est nomme, pour
    # qu'il se voie a la relecture au lieu de passer pour un succes.
    raison = raison_parasite(detailed)
    if raison:
        job.detail_enrichment_success = False
        job.detail_enrichment_error = raison
        return

    original = job.description or ""
    if original:
        if detailed not in original:
            job.description = original + "\n\n" + detailed
    else:
        job.description = detailed

    job.detail_matching_text = detailed


# ============================================================
# TRAVAILLERPOUR ELIGIBILITY
# ============================================================

def evaluate_travaillerpour_eligibility(job, detail):
    structured = detail.get("structured", {}) or {}

    degree_original = clean_value(structured.get("degree"))
    degree = normalize_value(degree_original)
    restriction = normalize_value(structured.get("restriction"))
    recruitment_type = normalize_value(structured.get("recruitment_type"))

    if TRAVAILLERPOUR_REJECT_MASTER:
        forbidden_terms = ["master", "doctorat", "doctoraat", "phd"]
        if any(term in degree for term in forbidden_terms):
            return {
                "status": "INELIGIBLE",
                "reason": "Diplôme Master ou supérieur obligatoire",
                "degree": degree_original,
            }

    if TRAVAILLERPOUR_USER_OVER_26:
        combined = restriction + " " + recruitment_type
        markers = [
            "-26",
            "moins de 26",
            "convention premier emploi",
            "convention de premier emploi",
        ]
        if any(marker in combined for marker in markers):
            return {
                "status": "INELIGIBLE",
                "reason": "Offre réservée aux moins de 26 ans / premier emploi",
                "degree": degree_original,
            }

    if (
        "réservé aux fonctionnaires" in restriction
        or "reserve aux fonctionnaires" in restriction
    ):
        return {
            "status": "VERIFY",
            "reason": "Offre réservée aux fonctionnaires - statut à vérifier",
            "degree": degree_original,
        }

    if not degree:
        return {
            "status": "VERIFY",
            "reason": "Niveau de diplôme non identifié",
            "degree": None,
        }

    bachelor_terms = [
        "bachelier",
        "bachelor",
        "graduat",
        "enseignement supérieur de type court",
        "hoger onderwijs van het korte type",
    ]
    if any(term in degree for term in bachelor_terms):
        return {
            "status": "ELIGIBLE",
            "reason": f"Diplôme compatible : {degree_original}",
            "degree": degree_original,
        }

    lower_terms = [
        "secondaire",
        "secundair",
        "cess",
        "pas de diplôme",
        "pas de diplome",
        "geen diploma",
    ]
    if any(term in degree for term in lower_terms):
        return {
            "status": "ELIGIBLE",
            "reason": f"Diplôme compatible : {degree_original}",
            "degree": degree_original,
        }

    return {
        "status": "VERIFY",
        "reason": f"Niveau de diplôme à vérifier : {degree_original}",
        "degree": degree_original,
    }


# ============================================================
# FULL TRAVAILLERPOUR
# ============================================================

@enriched_persistence_batch
def prepare_all_travaillerpour_jobs(jobs, database_run_id):
    print()
    print("=" * 76)
    print("       CONTRÔLE COMPLET TRAVAILLERPOUR")
    print("=" * 76)
    print()

    results = []
    success_count = 0
    failure_count = 0
    cache_count = 0
    relevant_count = 0
    database_update_success = 0
    database_update_errors = 0

    eligibility_counts = Counter()
    reason_counts = Counter()
    degree_counts = Counter()

    total = len(jobs)

    for index, job in enumerate(jobs, start=1):
        job.detail_enrichment_attempted = True

        try:
            detail = get_travaillerpour_job_detail(
                url=job.url,
                external_id=job.external_id,
                use_cache=True,
            )
        except Exception as error:
            detail = {
                "success": False,
                "matching_text": "",
                "matching_text_length": 0,
                "structured": {},
                "from_cache": False,
                "error": str(error),
            }

        if detail.get("success"):
            success_count += 1
            if detail.get("from_cache", False):
                cache_count += 1

            job.detail_enrichment_success = True
            job.detail_matching_text_length = int(
                detail.get("matching_text_length", 0) or 0
            )
            job.detail_from_cache = bool(detail.get("from_cache", False))
            job.detail_enrichment_error = None

            apply_travaillerpour_structured_data(job, detail)
            apply_detail_description(job, detail)
            eligibility = evaluate_travaillerpour_eligibility(job, detail)
        else:
            failure_count += 1
            job.detail_enrichment_success = False
            job.detail_matching_text_length = 0
            job.detail_from_cache = False
            job.detail_enrichment_error = detail.get("error")

            eligibility = {
                "status": "VERIFY",
                "reason": "Impossible de vérifier le diplôme et les conditions",
                "degree": None,
            }

        job.source_eligibility_status = eligibility["status"]
        job.source_eligibility_reason = eligibility["reason"]

        eligibility_counts[eligibility["status"]] += 1
        reason_counts[eligibility["reason"]] += 1
        degree_counts[eligibility.get("degree") or "INCONNU"] += 1

        if persist_enriched_job(job, database_run_id):
            database_update_success += 1
        else:
            database_update_errors += 1

        try:
            result = score_job(job)
        except Exception as error:
            print(f"[{index:>3}/{total}] ❌ MATCHER | {job.title}")
            print("         ↳", error)
            continue

        if result["core_relevance"]:
            relevant_count += 1

        results.append((job, result))

        status_label = {
            "ELIGIBLE": "✅ ELIGIBLE",
            "INELIGIBLE": "❌ INELIGIBLE",
            "VERIFY": "⚠️ VERIFY",
        }.get(eligibility["status"], "⚠️ ?")

        relevance_label = "🎯 METIER" if result["core_relevance"] else "— hors cible"
        degree_display = getattr(job, "degree_requirement", None) or "?"

        print(
            f"[{index:>3}/{total}] "
            f"{result['score']:>5.1f}/100 | "
            f"{status_label:<13} | "
            f"{relevance_label:<11} | "
            f"{degree_display:<20} | "
            f"{job.title[:40]}"
        )

        if eligibility["status"] != "ELIGIBLE":
            print("         ↳", eligibility["reason"])

        if detail.get("success") and not detail.get("from_cache", False):
            time.sleep(API_DELAY_SECONDS)

    return {
        "jobs": results,
        "success": success_count,
        "failures": failure_count,
        "from_cache": cache_count,
        "relevant": relevant_count,
        "eligibility_counts": eligibility_counts,
        "reason_counts": reason_counts,
        "degree_counts": degree_counts,
        "database_update_success": database_update_success,
        "database_update_errors": database_update_errors,
    }


# ============================================================
# STANDARD ENRICHMENT
# ============================================================

@enriched_persistence_batch
def enrich_standard_candidates(candidate_jobs, database_run_id):
    print()
    print("=" * 76)
    print("       ENRICHISSEMENT STANDARD + SMARTRECRUITERS")
    print("=" * 76)
    print()

    results = []
    success_count = 0
    failure_count = 0
    cache_count = 0
    database_update_success = 0
    database_update_errors = 0
    total = len(candidate_jobs)
    # JOBHUNTER_OBSERVABILITY_V1_ENRICHMENT
    enrichment_runtime = defaultdict(lambda: {"jobs": 0, "seconds": 0.0, "success": 0, "cache": 0, "failures": 0})

    for index, (job, old_result) in enumerate(candidate_jobs, start=1):
        source = get_job_source(job)
        origin = get_job_origin(job)
        job.detail_enrichment_attempted = True
        detail_started = time.perf_counter()

        try:
            detail = get_job_detail(job)
        except Exception as error:
            detail = {
                "success": False,
                "matching_text": "",
                "matching_text_length": 0,
                "structured": {},
                "from_cache": False,
                "error": str(error),
            }

        detail_elapsed = time.perf_counter() - detail_started

        if detail.get("success"):
            success_count += 1
            if detail.get("from_cache", False):
                cache_count += 1

            job.detail_enrichment_success = True
            job.detail_matching_text_length = int(
                detail.get("matching_text_length", 0) or 0
            )
            job.detail_from_cache = bool(detail.get("from_cache", False))
            job.detail_enrichment_error = None

            apply_structured_data(job, detail)
            apply_detail_description(job, detail)
        else:
            failure_count += 1
            job.detail_enrichment_success = False
            job.detail_matching_text_length = 0
            job.detail_from_cache = False
            job.detail_enrichment_error = detail.get("error")

        runtime = enrichment_runtime[source]
        runtime["jobs"] += 1
        runtime["seconds"] += detail_elapsed
        if detail.get("success"):
            runtime["success"] += 1
            if detail.get("from_cache", False): runtime["cache"] += 1
        else:
            runtime["failures"] += 1

        job.source_eligibility_status = "ELIGIBLE"
        job.source_eligibility_reason = None

        if persist_enriched_job(job, database_run_id):
            database_update_success += 1
        else:
            database_update_errors += 1

        new_result = score_job(job)
        results.append((job, new_result))

        confidence_source = (
            (new_result.get("confidence") or {}).get("source")
        )

        if new_result["provisional"]:
            confidence = "⚠️ PROV."
        elif confidence_source == "JOBAT_SEARCH_CARD":
            confidence = "🟡 CARD"
        elif new_result["confidence_level"] == "HIGH":
            confidence = "✅ HIGH"
        elif new_result["confidence_level"] == "MEDIUM":
            confidence = "🟡 MED."
        else:
            confidence = "⚪ LOW"

        title_bonus = float(new_result.get("jobat_title_bonus") or 0)
        bonus_suffix = (
            f" | 🎯 TITRE +{title_bonus:.0f}"
            if source == "JOBAT" and title_bonus > 0
            else ""
        )

        print(
            f"[{index:>4}/{total}] "
            f"{source:<16} | "
            f"{origin[:12]:<12} | "
            f"{new_result['score']:>5.1f}/100 | "
            f"{confidence:<8} | "
            f"{job.title[:44]}"
            f"{bonus_suffix}"
        )

        if detail.get("success") and not detail.get("from_cache", False):
            time.sleep(API_DELAY_SECONDS)

    print()
    print("ENRICHMENT_RUNTIME_SUMMARY")
    for runtime_source, runtime in sorted(enrichment_runtime.items(), key=lambda item: item[1]["seconds"], reverse=True):
        avg = runtime["seconds"] / max(1, runtime["jobs"])
        print(
            f"ENRICH_RUNTIME | source={runtime_source} | jobs={runtime['jobs']} | seconds={runtime['seconds']:.3f} | "
            f"avg={avg:.3f} | success={runtime['success']} | cache={runtime['cache']} | failures={runtime['failures']}"
        )

    return {
        "jobs": results,
        "success": success_count,
        "failures": failure_count,
        "from_cache": cache_count,
        "database_update_success": database_update_success,
        "database_update_errors": database_update_errors,
    }


# ============================================================
# RESULTS HELPERS
# ============================================================

def get_relevant_travaillerpour_results(prepared):
    return [
        (job, result)
        for job, result in prepared
        if result["core_relevance"]
    ]


def result_sort_key(item):
    job, result = item
    reliable = 0 if result["provisional"] else 1
    return reliable, result["confidence_rank"], result["score"]


# ============================================================
# CANONICAL MAPPING
# ============================================================

def load_canonical_mapping(build_id):
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT
                cjs.canonical_job_id,
                cjs.collection_channel,
                cjs.origin_source,
                cjs.source_external_id,
                cj.canonical_key,
                cj.member_count,
                cj.source_count,
                cj.preferred_raw_job_id
            FROM canonical_job_sources AS cjs
            JOIN canonical_jobs AS cj
              ON cj.id = cjs.canonical_job_id
            WHERE cjs.build_id = ?
            """,
            (build_id,),
        ).fetchall()
    finally:
        connection.close()

    mapping = {}
    members_by_canonical = defaultdict(list)

    for row in rows:
        data = dict(row)
        key = (
            clean_value(data["collection_channel"]).upper(),
            clean_value(data["source_external_id"]),
        )
        mapping[key] = data
        members_by_canonical[int(data["canonical_job_id"])].append(data)

    return mapping, members_by_canonical


# ============================================================
# REPRESENTATIVE CHOICE
# ============================================================

def representative_quality(item):
    job, result = item

    reliable = 0 if result["provisional"] else 1
    detail_success = 1 if getattr(job, "detail_enrichment_success", False) else 0
    source = get_job_source(job)
    origin = get_job_origin(job)

    if source in {"FOREM", "TRAVAILLERPOUR", "TALENT_BRUSSELS"}:
        authority = 100
    elif source == "SMARTRECRUITERS":
        # Posting API de l'employeur direct.
        authority = 99
    elif source == "ACTIRIS" and origin == "ACTIRIS":
        authority = 98
    elif source == "ACTIRIS" and origin == "VDAB_FOREM":
        authority = 82
    elif source == "ACTIRIS" and origin == "PARTNER":
        authority = 72
    else:
        authority = 60

    return (
        reliable,
        result["confidence_rank"],
        result["score"],
        detail_success,
        authority,
    )


# ============================================================
# CANONICAL ELIGIBILITY
# ============================================================

def canonical_group_eligibility(items):
    statuses = []

    for job, result in items:
        statuses.append(
            (
                getattr(job, "source_eligibility_status", "ELIGIBLE"),
                getattr(job, "source_eligibility_reason", None),
                get_job_source(job),
            )
        )

    ineligible = [value for value in statuses if value[0] == "INELIGIBLE"]
    if ineligible:
        reasons = []
        for status, reason, source in ineligible:
            text = f"{source}: {reason}" if reason else source
            if text not in reasons:
                reasons.append(text)
        return "INELIGIBLE", " | ".join(reasons)

    verify = [value for value in statuses if value[0] == "VERIFY"]
    if verify:
        reasons = []
        for status, reason, source in verify:
            text = f"{source}: {reason}" if reason else source
            if text not in reasons:
                reasons.append(text)
        return "VERIFY", " | ".join(reasons)

    return "ELIGIBLE", None


# ============================================================
# COLLAPSE SCORED RAW -> CANONICAL
# ============================================================

# ============================================================
# REPRISE DU STOCK ACTIF
# ============================================================

# Interrupteur volontaire : la reprise change le volume traite par le gate
# et la file. Pouvoir la couper sans toucher a la logique evite d'avoir a
# defaire quoi que ce soit si un run doit rester strictement comparable aux
# precedents.
REPRISE_STOCK_ACTIVE = True


def reprendre_le_stock_actif(deja_notees):
    """
    Note les offres actives de la base absentes de la recolte du jour.

    Sans cela, le pipeline ne juge que ce que les connecteurs viennent de
    rapporter. Une offre collectee il y a trois jours, toujours ouverte, ne
    repasse jamais devant le matcheur — meme si son texte a ete enrichi
    depuis, meme si le matcheur a ete corrige depuis.

    Aucun reseau : ces offres sont deja en base, avec leur texte. Le filtre
    applique est exactement celui de la recolte fraiche — la pertinence
    metier — de sorte qu'une offre reprise entre dans la file aux memes
    conditions qu'une offre du jour, ni plus ni moins.
    """
    if not REPRISE_STOCK_ACTIVE:
        return []

    reprises = charger_stock_actif(cles_de_collecte(
        job for job, _result in deja_notees))
    if not reprises:
        return []

    retenues = []
    for job in reprises:
        try:
            result = score_job(job)
        except Exception:
            # Une offre du stock qui fait echouer le scoring ne doit pas
            # interrompre le run : elle est simplement laissee de cote.
            continue
        if result.get("core_relevance"):
            retenues.append((job, result))

    print()
    print("=" * 100)
    print("REPRISE DU STOCK ACTIF V" + REPRISE_STOCK_VERSION)
    print("=" * 100)
    print(f"Offres actives non revues par la recolte : {len(reprises)}")
    print(f"Retenues comme pertinentes               : {len(retenues)}")
    print("Ces offres n'auraient pas ete jugees par ce run sans la reprise.")

    return retenues


def collapse_scored_by_canonical(scored_jobs, build_id):
    mapping, members_by_canonical = load_canonical_mapping(build_id)
    groups = defaultdict(list)
    missing = []

    for item in scored_jobs:
        job, result = item
        key = (get_job_collection_channel(job), get_job_external_id(job))
        metadata = mapping.get(key)

        if metadata is None:
            fallback = (
                "RAW_FALLBACK",
                get_job_collection_channel(job),
                get_job_external_id(job),
            )
            groups[fallback].append(item)
            missing.append(key)
            continue

        groups[int(metadata["canonical_job_id"])].append(item)

    collapsed = []
    duplicate_raw_removed = 0
    multi_scored_groups = 0

    for canonical_id, items in groups.items():
        representative_job, representative_result = max(
            items,
            key=representative_quality,
        )

        group_status, group_reason = canonical_group_eligibility(items)
        representative_job.source_eligibility_status = group_status
        representative_job.source_eligibility_reason = group_reason

        if isinstance(canonical_id, int):
            member_rows = members_by_canonical.get(canonical_id, [])

            representative_job.canonical_job_id = canonical_id
            representative_job.canonical_member_count = (
                int(member_rows[0]["member_count"]) if member_rows else len(items)
            )
            representative_job.canonical_source_count = (
                int(member_rows[0]["source_count"]) if member_rows else len(items)
            )
            representative_job.canonical_key = (
                member_rows[0]["canonical_key"] if member_rows else None
            )
            representative_job.canonical_sources = [
                {
                    "collection_channel": row["collection_channel"],
                    "origin_source": row["origin_source"],
                    "source_external_id": row["source_external_id"],
                }
                for row in member_rows
            ]
        else:
            representative_job.canonical_job_id = None
            representative_job.canonical_member_count = 1
            representative_job.canonical_source_count = 1
            representative_job.canonical_key = None
            representative_job.canonical_sources = [
                {
                    "collection_channel": get_job_collection_channel(representative_job),
                    "origin_source": get_job_origin(representative_job),
                    "source_external_id": get_job_external_id(representative_job),
                }
            ]

        if len(items) > 1:
            multi_scored_groups += 1
            duplicate_raw_removed += len(items) - 1

        collapsed.append((representative_job, representative_result))

    collapsed.sort(key=result_sort_key, reverse=True)

    return {
        "jobs": collapsed,
        "input_count": len(scored_jobs),
        "output_count": len(collapsed),
        "duplicates_removed": duplicate_raw_removed,
        "multi_scored_groups": multi_scored_groups,
        "missing_mapping_count": len(missing),
        "missing_mapping": missing,
    }


# ============================================================
# CANONICAL BUILD SUMMARY
# ============================================================

def print_canonical_build_summary(canonical_result, collapse_result):
    summary = canonical_result["summary"]

    print()
    print("=" * 76)
    print("                CANONICAL V3 - BUILD + COLLAPSE")
    print("=" * 76)
    print()
    print("Build ID                   :", summary["build_id"])
    print("RAW dans build             :", summary["raw_jobs"])
    print("Paires candidates          :", summary["candidate_pairs"])
    print("Arêtes auto acceptées      :", summary["accepted_edges"])
    print("Groupes fusionnés          :", summary["merged_groups"])
    print("Canonical jobs DB          :", summary["canonical_jobs"])
    print("Review candidates          :", summary["reviews"])
    print()
    print("Résultats scorés RAW       :", collapse_result["input_count"])
    print("Résultats canoniques       :", collapse_result["output_count"])
    print("Doublons retirés du ranking:", collapse_result["duplicates_removed"])
    print("Groupes multi-RAW scorés   :", collapse_result["multi_scored_groups"])
    print("Mappings introuvables      :", collapse_result["missing_mapping_count"])

    if collapse_result["missing_mapping"]:
        print()
        print("⚠️ Premiers mappings introuvables :")
        for item in collapse_result["missing_mapping"][:20]:
            print("   ", item)


# ============================================================
# ELIGIBILITY / CLASSIFICATION
# ============================================================

def partition_by_eligibility(jobs):
    eligible = []
    verify = []
    ineligible = []

    for item in jobs:
        job, result = item
        status = getattr(job, "source_eligibility_status", "ELIGIBLE")

        if status == "INELIGIBLE":
            ineligible.append(item)
        elif status == "VERIFY":
            verify.append(item)
        else:
            eligible.append(item)

    return {
        "eligible": eligible,
        "verify": verify,
        "ineligible": ineligible,
    }


def classify_jobs(jobs):
    categories = {
        "excellent": [],
        "very_relevant": [],
        "relevant": [],
        "to_review": [],
        "potential": [],
        "weak": [],
        "provisional": [],
    }

    for item in jobs:
        job, result = item

        if result["provisional"]:
            categories["provisional"].append(item)
            continue

        score = result["score"]

        if score >= 90:
            key = "excellent"
        elif score >= 80:
            key = "very_relevant"
        elif score >= 65:
            key = "relevant"
        elif score >= 50:
            key = "to_review"
        elif score >= 35:
            key = "potential"
        else:
            key = "weak"

        categories[key].append(item)

    return categories


def get_priority_jobs(jobs):
    priorities = []

    for item in jobs:
        job, result = item

        if getattr(job, "source_eligibility_status", "ELIGIBLE") != "ELIGIBLE":
            continue
        if result["provisional"]:
            continue
        if result["score"] < 65:
            continue
        if result["confidence_level"] not in {"HIGH", "MEDIUM"}:
            continue

        priorities.append(item)

    return priorities


# ============================================================
# SOURCE STATS / LABELS
# ============================================================

def print_source_counts(jobs):
    counts = Counter(get_job_source(job) for job, result in jobs)
    print()
    print("Répartition par source représentative :")
    for source, count in counts.most_common():
        print(f"  {source:<20} {count}")


def print_origin_counts(jobs):
    counts = Counter(get_job_origin(job) for job, result in jobs)
    print()
    print("Répartition par origine représentative :")
    for origin, count in counts.most_common():
        print(f"  {origin:<20} {count}")


def canonical_sources_label(job):
    sources = getattr(job, "canonical_sources", []) or []
    labels = []

    for source in sources:
        channel = clean_value(source.get("collection_channel"))
        external_id = clean_value(source.get("source_external_id"))
        label = f"{channel}:{external_id}"
        if label not in labels:
            labels.append(label)

    if labels:
        return " + ".join(labels)

    return get_job_source(job)


# ============================================================
# TP AUDIT
# ============================================================

def print_travaillerpour_audit(preparation):
    print()
    print("=" * 76)
    print("             AUDIT TRAVAILLERPOUR COMPLET")
    print("=" * 76)
    print()
    print("Offres analysées            :", len(preparation["jobs"]))
    print("Descriptions récupérées     :", preparation["success"])
    print("Depuis cache                :", preparation["from_cache"])
    print("Échecs détail               :", preparation["failures"])
    print("Pertinentes métier          :", preparation["relevant"])
    print("Updates DB réussies         :", preparation["database_update_success"])
    print("Erreurs update DB           :", preparation["database_update_errors"])

    eligibility = preparation["eligibility_counts"]
    print()
    print("Éligibilité catalogue :")
    print("  ✅ ELIGIBLE   :", eligibility.get("ELIGIBLE", 0))
    print("  ⚠️ VERIFY     :", eligibility.get("VERIFY", 0))
    print("  ❌ INELIGIBLE :", eligibility.get("INELIGIBLE", 0))

    print()
    print("Diplômes :")
    for degree, count in preparation["degree_counts"].most_common():
        print(f"  {degree:<40} {count}")


# ============================================================
# DB SUMMARY
# ============================================================

def print_database_summary():
    summary = get_database_summary()

    print()
    print("=" * 76)
    print("                  DATABASE V2.1 - ETAT")
    print("=" * 76)
    print()
    print("Database              :", summary["database_path"])
    print("raw_jobs              :", summary["tables"]["raw_jobs"]["rows"])
    print("collection_runs       :", summary["tables"]["collection_runs"]["rows"])
    print("raw_job_run_items     :", summary["tables"]["raw_job_run_items"]["rows"])

    payload = summary.get("payload_stats", {})
    if payload:
        print("raw_payload_json      :", payload.get("raw_payload_count"))
        print("enriched_payload_json :", payload.get("enriched_payload_count"))

    print()
    print("RAW par source :")
    for item in summary["source_counts"]:
        print(f"  {item['source']:<20} {item['count']}")


# ============================================================
# APPLICATION GATE - AFFICHAGE
# ============================================================

def print_gate_bucket(title, items, limit):
    print()
    print("=" * 76)
    print(title)
    print("=" * 76)

    if not items:
        print("Aucune offre dans cette catégorie.")
        return

    for position, (job, result, gate) in enumerate(items[:limit], start=1):
        print()
        print(
            f"{position:>2}. "
            f"MATCH {result['score']:>5.1f}/100 "
            f"| GATE {gate['priority_score']:>5.1f} "
            f"| CAN {getattr(job, 'canonical_job_id', None)}"
        )
        print(f"    {job.title}")
        print(f"    {job.company}")
        print(f"    {job.location}")
        print("    Sources  :", canonical_sources_label(job))
        print("    Famille  :", result.get("best_family"))

        messages = (
            list(gate.get("hard_reasons", []))
            + list(gate.get("warnings", []))
            + list(gate.get("reasons", []))
        )

        for message in messages[:5]:
            print("    ↳", message)

        print(f"    {job.url}")


def print_application_gate_shortlists(gate_partitions, gate_export):
    print()
    print("=" * 76)
    print("                 APPLICATION GATE V1")
    print("=" * 76)
    print()

    summary = gate_export["summary"]
    print("Offres évaluées :", summary["total"])
    print("🟢 APPLY        :", summary["APPLY"])
    print("🟡 STRETCH      :", summary["STRETCH"])
    print("🟠 VERIFY       :", summary["VERIFY"])
    print("🔴 REJECT       :", summary["REJECT"])
    print()
    print("TXT Gate        :", gate_export["txt_path"])
    print("JSON Gate       :", gate_export["json_path"])

    print_gate_bucket(
        "       🟢 CANDIDATER MAINTENANT - APPLY",
        gate_partitions["APPLY"],
        TOP_GATE_APPLY,
    )

    print_gate_bucket(
        "       🟡 CANDIDATURES AUDACIEUSES - STRETCH",
        gate_partitions["STRETCH"],
        TOP_GATE_STRETCH,
    )

    print_gate_bucket(
        "       🟠 À VÉRIFIER AVANT CANDIDATURE - VERIFY",
        gate_partitions["VERIFY"],
        TOP_GATE_VERIFY,
    )

    print_gate_bucket(
        "       🔴 NE PAS POSTULER - REJECT",
        gate_partitions["REJECT"],
        TOP_GATE_REJECT,
    )



# ============================================================
# APPLICATION QUEUE V1
# ============================================================

def print_queue_bucket(title, items, limit):
    print()
    print("=" * 76)
    print(title)
    print("=" * 76)

    if not items:
        print("Aucune offre dans cette catégorie.")
        return

    for position, item in enumerate(items[:limit], start=1):
        star = "⭐" if item.get("preferred_location") else " "
        print()
        print(
            f"{position:>2}. {star} "
            f"QUEUE {item.get('queue_score', 0):>6.1f} | "
            f"MATCH {item.get('match_score', 0):>5.1f} | "
            f"CAN {item.get('canonical_job_id')}"
        )
        print(f"    {item.get('title', '')}")
        print(f"    {item.get('company', '')}")
        print(f"    {item.get('location', '')}")
        print(f"    CV      : {item.get('cv_track_label', '')}")
        print(f"    Famille : {item.get('best_family', '')}")
        print(f"    Stable  : {item.get('stable_item_key', '')}")

        if item.get("duplicate_of_item_key"):
            print("    ↳ HOLD : probable double candidature de", item["duplicate_of_item_key"])

        possible = item.get("possible_duplicate_item_keys") or []
        if possible:
            print("    ↳ Doublon possible :", ", ".join(possible[:4]))

        gate = item.get("gate") or {}
        messages = (
            list(gate.get("hard_reasons", []))
            + list(gate.get("warnings", []))
            + list(gate.get("reasons", []))
        )
        for message in messages[:4]:
            print("    ↳", message)

        print(f"    {item.get('url', '')}")


def print_application_queue_summary(queue_partitions, queue_export):
    print()
    print("=" * 76)
    print("                 APPLICATION QUEUE V1")
    print("=" * 76)
    print()

    summary = queue_export["summary"]
    print("Offres évaluées      :", summary["total"])
    print("🟢 READY_APPLY       :", summary["READY_APPLY"])
    print("🟡 READY_STRETCH     :", summary["READY_STRETCH"])
    print("🟠 VERIFY_FIRST      :", summary["VERIFY_FIRST"])
    print("🟣 HOLD_DUPLICATE    :", summary["HOLD_DUPLICATE"])
    print("⚫ EXCLUDED          :", summary["EXCLUDED"])
    print("⭐ APPLY zone prior.  :", summary["preferred_ready_apply"])
    print()
    print("CV DATA APPLY        :", summary["data_ready_apply"])
    print("CV LAB/QC APPLY      :", summary["lab_qc_ready_apply"])
    print("CV HYBRIDE APPLY     :", summary["hybrid_ready_apply"])
    print()
    print("TXT Queue            :", queue_export["txt_path"])
    print("JSON Queue           :", queue_export["json_path"])

    print_queue_bucket(
        "       🟢 FILE PRIORITAIRE - READY_APPLY",
        queue_partitions["READY_APPLY"],
        TOP_QUEUE_APPLY,
    )
    print_queue_bucket(
        "       🟡 FILE AUDACIEUSE - READY_STRETCH",
        queue_partitions["READY_STRETCH"],
        TOP_QUEUE_STRETCH,
    )
    print_queue_bucket(
        "       🟠 À VÉRIFIER AVANT DOCUMENTS - VERIFY_FIRST",
        queue_partitions["VERIFY_FIRST"],
        TOP_QUEUE_VERIFY,
    )
    print_queue_bucket(
        "       🟣 ANTI-DOUBLE-CANDIDATURE - HOLD_DUPLICATE",
        queue_partitions["HOLD_DUPLICATE"],
        TOP_QUEUE_HOLD,
    )


# ============================================================
# MAIN
# ============================================================

def main():
    tracker = MainProgressTracker()

    print()
    print("=" * 76)
    print("                  JOB HUNTER BELGIUM")
    print(" FOREM + ACTIRIS + TALENT.BRUSSELS + TRAVAILLERPOUR + SMARTRECRUITERS")
    print("                    MATCHER V5.1")
    print("                    MAIN V10.4.1")
    print("     DATABASE V2.1 + CANONICAL V3 + GATE V1.3 + QUEUE V1")
    print("=" * 76)
    print()
    print("Démarrage :", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    print("Étapes prévues :", TOTAL_MAIN_STEPS)

    # ========================================================
    # STEP 1
    # ========================================================
    tracker.start_step(1, "Collecte multisource")

    collection = collect_all_jobs()
    all_jobs = collection["jobs"]
    standard_jobs = collection["standard_jobs"]
    travaillerpour_jobs = collection["travaillerpour"]

    print()
    print("=" * 76)
    print("                  COLLECTE TERMINÉE")
    print("=" * 76)
    for source_summary in collection.get("source_summaries", []):
        if not source_summary.get("enabled"):
            continue
        label = str(source_summary.get("label") or source_summary.get("key") or "SOURCE")
        count = int(source_summary.get("count") or 0)
        error = source_summary.get("error")
        suffix = "  ⚠️ ERREUR" if error else ""
        print(f"{label[:20]:<20}: {count}{suffix}")
    print("TOTAL               :", len(all_jobs))

    tracker.finish_step()

    # ========================================================
    # STEP 2
    # ========================================================
    tracker.start_step(2, "Sauvegarde RAW V2.1")

    database_run = persist_initial_raw_collection(all_jobs)
    database_run_id = database_run["run_id"]

    print_source_yield_report(collection, database_run_id)

    tracker.finish_step()

    # ========================================================
    # STEP 3
    # ========================================================
    tracker.start_step(3, "Pré-sélection métier + SmartRecruiters")

    standard_pre_scored = pre_score_jobs(standard_jobs)
    standard_candidates = select_candidate_jobs(standard_pre_scored)

    print()
    print("Offres standard collectées :", len(standard_jobs))
    print("Candidates métier          :", len(standard_candidates))
    print("Écartées avant détail      :", len(standard_jobs) - len(standard_candidates))
    print("✅ Toutes sont déjà préservées dans raw_jobs.")

    tracker.finish_step()

    # ========================================================
    # STEP 4
    # ========================================================
    tracker.start_step(4, "Analyse complète Travaillerpour")

    tp_preparation = prepare_all_travaillerpour_jobs(
        travaillerpour_jobs,
        database_run_id,
    )
    tp_relevant = get_relevant_travaillerpour_results(tp_preparation["jobs"])
    print_travaillerpour_audit(tp_preparation)

    tracker.finish_step()

    # ========================================================
    # STEP 5
    # ========================================================
    tracker.start_step(5, "Enrichissement standard + SmartRecruiters")

    standard_enrichment = enrich_standard_candidates(
        standard_candidates,
        database_run_id,
    )

    raw_scored = standard_enrichment["jobs"] + tp_relevant

    # Le stock actif rejoint la recolte AVANT la deduplication canonique :
    # quand une offre est presente des deux cotes, c'est la version fraiche
    # qui est retenue comme representante.
    raw_scored = raw_scored + reprendre_le_stock_actif(raw_scored)

    raw_scored.sort(key=result_sort_key, reverse=True)

    tracker.finish_step()

    # ========================================================
    # STEP 6
    # ========================================================
    tracker.start_step(6, "Build canonique + classement dédupliqué")

    canonical_result = build_canonical()
    canonical_build_id = canonical_result["summary"]["build_id"]

    collapse_result = collapse_scored_by_canonical(
        raw_scored,
        canonical_build_id,
    )
    canonical_scored = collapse_result["jobs"]

    print_canonical_build_summary(canonical_result, collapse_result)

    tracker.finish_step()

    # ========================================================
    # STEP 7 - APPLICATION GATE V1.3
    # ========================================================
    tracker.start_step(7, "Application Gate V1.3.2 + shortlist")

    gated_jobs = apply_application_gate(canonical_scored)
    gate_partitions = partition_gate_results(gated_jobs)
    gate_export = export_application_gate(gated_jobs, PROJECT_ROOT)
    gate_counts = gate_summary(gated_jobs)

    tracker.finish_step()

    # ========================================================
    # STEP 8 - APPLICATION QUEUE V1
    # ========================================================
    tracker.start_step(8, "Application Queue V1 + anti-double-candidature")

    queued_jobs = build_application_queue(gated_jobs)
    queue_partitions = partition_application_queue(queued_jobs)
    queue_export = export_application_queue(queued_jobs, PROJECT_ROOT)
    queue_counts = queue_summary(queued_jobs)

    tracker.finish_step()

    # ========================================================
    # PARTITIONS SOURCE / LEGACY
    # ========================================================
    partitions = partition_by_eligibility(canonical_scored)
    eligible_jobs = partitions["eligible"]
    verify_jobs = partitions["verify"]
    ineligible_jobs = partitions["ineligible"]
    categories = classify_jobs(eligible_jobs)

    # ========================================================
    # RESULTS
    # ========================================================
    print()
    print("=" * 76)
    print("                 RÉSULTATS V10.4.1")
    print("=" * 76)
    print()
    print("Offres collectées RAW        :", len(all_jobs))
    print("Résultats scorés RAW         :", len(raw_scored))
    print("Résultats canoniques         :", len(canonical_scored))
    print("Doublons retirés du ranking  :", collapse_result["duplicates_removed"])
    print("Mappings canoniques manquants:", collapse_result["missing_mapping_count"])
    print()
    print("Éligibles au classement      :", len(eligible_jobs))
    print("Éligibilité à vérifier       :", len(verify_jobs))
    print("Inéligibles mais pertinents  :", len(ineligible_jobs))
    print()
    print("🔥 Excellent 90+              :", len(categories["excellent"]))
    print("🟢 Très pertinent 80-89       :", len(categories["very_relevant"]))
    print("🟢 Pertinent 65-79            :", len(categories["relevant"]))
    print("🟡 À examiner 50-64           :", len(categories["to_review"]))
    print("⚪ Potentiel 35-49            :", len(categories["potential"]))
    print("🔴 Faible <35                 :", len(categories["weak"]))
    print("⚠️ Provisoires               :", len(categories["provisional"]))
    print()
    print("Application Gate V1.3.2 :")
    print("  🟢 APPLY                   :", gate_counts["APPLY"])
    print("  🟡 STRETCH                 :", gate_counts["STRETCH"])
    print("  🟠 VERIFY                  :", gate_counts["VERIFY"])
    print("  🔴 REJECT                  :", gate_counts["REJECT"])
    print()
    print("Application Queue V1 :")
    print("  🟢 READY_APPLY             :", queue_counts["READY_APPLY"])
    print("  🟡 READY_STRETCH           :", queue_counts["READY_STRETCH"])
    print("  🟠 VERIFY_FIRST            :", queue_counts["VERIFY_FIRST"])
    print("  🟣 HOLD_DUPLICATE          :", queue_counts["HOLD_DUPLICATE"])
    print("  ⚫ EXCLUDED                :", queue_counts["EXCLUDED"])
    print("  ⭐ APPLY zone prioritaire   :", queue_counts["preferred_ready_apply"])

    print_source_counts(eligible_jobs)
    print_origin_counts(eligible_jobs)
    print_database_summary()

    # ========================================================
    # INELIGIBLE
    # ========================================================
    if ineligible_jobs:
        print()
        print("=" * 76)
        print("       ❌ OFFRES CANONIQUES PERTINENTES MAIS INÉLIGIBLES")
        print("=" * 76)

        for job, result in ineligible_jobs:
            print()
            print(f"{result['score']:>5.1f}/100 | {job.title}")
            print("    Canonical :", getattr(job, "canonical_job_id", None))
            print("    Sources   :", canonical_sources_label(job))
            print("    Employeur :", job.company)
            print("    Diplôme   :", getattr(job, "degree_requirement", None))
            print("    Motif     :", getattr(job, "source_eligibility_reason", None))
            print("    URL       :", job.url)

    # ========================================================
    # VERIFY
    # ========================================================
    if verify_jobs:
        print()
        print("=" * 76)
        print("             ⚠️ ÉLIGIBILITÉ CANONIQUE À VÉRIFIER")
        print("=" * 76)

        for job, result in verify_jobs:
            print()
            print(f"{result['score']:>5.1f}/100 | {job.title}")
            print("    Canonical :", getattr(job, "canonical_job_id", None))
            print("    Sources   :", canonical_sources_label(job))
            print("    Motif     :", getattr(job, "source_eligibility_reason", None))
            print("    URL       :", job.url)

    # ========================================================
    # TOP CANONICAL
    # ========================================================
    print()
    print("=" * 76)
    print(f"              TOP {TOP_RESULTS} CANONIQUE ÉLIGIBLE")
    print("=" * 76)

    for job, result in eligible_jobs[:TOP_RESULTS]:
        print()
        print("CANONICAL :", getattr(job, "canonical_job_id", None))
        print("MEMBRES   :", getattr(job, "canonical_member_count", 1))
        print("SOURCES   :", canonical_sources_label(job))
        print("SOURCE REP:", get_job_source(job))
        print("ORIGINE   :", get_job_origin(job))
        print_job_match(job, result)

        if get_job_source(job) == "TRAVAILLERPOUR":
            print("Diplôme fédéral :", getattr(job, "degree_requirement", None))
            print("Deadline        :", getattr(job, "application_deadline", None))

    # ========================================================
    # APPLICATION GATE SHORTLISTS
    # ========================================================
    print_application_gate_shortlists(gate_partitions, gate_export)

    # ========================================================
    # APPLICATION QUEUE
    # ========================================================
    print_application_queue_summary(queue_partitions, queue_export)

    tracker.print_final_timing()


# ============================================================
# RUN
# ============================================================

def run():
    global RUN_STARTED_MONOTONIC, RUN_STARTED_WALL

    RUN_STARTED_MONOTONIC = time.perf_counter()
    RUN_STARTED_WALL = datetime.now()

    logger = start_main_logging()

    try:
        print()
        print("TXT automatique :")
        print(logger["path"])
        print("Chronomètre démarré :", RUN_STARTED_WALL.strftime("%d/%m/%Y %H:%M:%S"))

        main()

        print()
        print("=" * 76)
        print("RUN V10.4.1 TERMINÉ")
        print("=" * 76)
        print()
        print("Durée totale :", format_duration(get_run_elapsed_seconds()))
        print("Fichier résultat :")
        print(logger["path"])

    except Exception as error:
        print()
        print("=" * 76)
        print("❌ ERREUR FATALE V10.3")
        print("=" * 76)
        print(type(error).__name__, ":", error)
        print("Temps écoulé avant erreur :", format_duration(get_run_elapsed_seconds()))
        raise

    finally:
        path = logger["path"]
        elapsed = format_duration(get_run_elapsed_seconds())
        stop_main_logging(logger)

        print()
        print("TXT généré automatiquement :")
        print(path)
        print("Temps total écoulé :", elapsed)




# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1
from sources.unified_discovery import matches_master_title
_ud_original_should_second_gate_thin_description = should_second_gate_thin_description

def should_second_gate_thin_description(job):
    if _ud_original_should_second_gate_thin_description(job):
        return True

    title = str(getattr(job, "title", "") or "").strip()
    description = str(getattr(job, "description", "") or "").strip()

    if len(description) >= THIN_DESCRIPTION_SECOND_GATE_LIMIT:
        return False

    return matches_master_title(title)

if __name__ == "__main__":
    run()
