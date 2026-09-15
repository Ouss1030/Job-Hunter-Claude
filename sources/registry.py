"""
JOB HUNTER BELGIUM
SOURCE REGISTRY - VERSION 1.0

Centralise les sources de collecte et leur activation.

Objectifs :
- ne plus câbler la chaîne de collecte source par source dans main.py ;
- permettre à l'interface d'activer/désactiver une source ;
- isoler les erreurs : une source en panne ne fait pas perdre les autres ;
- rendre l'ajout de nouvelles sources beaucoup plus simple.

Le fichier config/source_settings.json contient uniquement les overrides utilisateur.
Si une source n'y figure pas, enabled_default est utilisé.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sources.forem import search_targeted_forem_jobs, convert_forem_job
from sources.forem_adaptive import get_forem_scheduler_plan, merge_cached_forem_results, mark_forem_scheduler_success
from sources.actiris import search_targeted_actiris_jobs, convert_actiris_job
from sources.talent_brussels import (
    search_targeted_talent_brussels_jobs,
    convert_talent_brussels_job,
)
from sources.travaillerpour import (
    search_targeted_travaillerpour_jobs,
    convert_travaillerpour_job,
)
from sources.smartrecruiters import fetch_smartrecruiters_jobs
from sources.jobat import search_targeted_jobat_jobs, convert_jobat_job
from sources.scienceatwork import collect_scienceatwork_jobs
from sources.randstad import collect_randstad_jobs
from sources.jeffersonwells import collect_jeffersonwells_jobs
from sources.akkodis import collect_akkodis_jobs
from sources.gsk import collect_gsk_jobs
from sources.ucb import collect_ucb_jobs
from sources.iba import collect_iba_jobs
from sources.pfizer import collect_pfizer_jobs
from sources.takeda import collect_takeda_jobs
from sources.jnj import collect_jnj_jobs
from sources.quality_assistance import collect_quality_assistance_jobs
from sources.thermofisher import collect_thermofisher_jobs
from sources.sciensano import collect_sciensano_jobs
from sources.sanofi import collect_sanofi_jobs
from sources.baxter import collect_baxter_jobs
from sources.novartis import collect_novartis_jobs
from sources.adzuna_api import collect_adzuna_jobs
from sources.careerjet_api import collect_careerjet_jobs
from sources.jooble_api import collect_jooble_jobs
from sources.prothya import collect_prothya_jobs
from sources.remotive import collect_remotive_jobs
from sources.direct_career_v1 import load_employer_configs, collect_direct_career_jobs
from sources.backlog_validator_v14 import (
    load_backlog as load_v14_backlog,
    make_backlog_collector,
)
from sources.agency_student_network_v1 import (
    collect_start_people_student_jobs,
    collect_synergie_student_jobs,
    collect_vdab_student_web_jobs,
)
from sources.student_sources_v1 import (
    collect_student_be_jobs,
    collect_studentjob_be_jobs,
    collect_randstad_student_jobs,
)
from sources.workday_pharma_v1 import (
    collect_air_liquide_jobs,
    collect_bms_jobs,
    collect_galderma_jobs,
    collect_amgen_jobs,
    collect_beigene_jobs,
    collect_elanco_jobs,
)
from sources.mega8_high_value import (
    collect_europharmajobs_jobs,
    collect_ictjob_jobs,
    collect_references_jobs,
    collect_swde_jobs,
    collect_arbeitnow_jobs,
)
from sources.source_metrics import clear_source_metrics, get_source_metrics
from sources.source_health import get_source_health, runtime_source_health
from sources.agfa import collect_agfa_jobs
from sources.umicore import collect_umicore_jobs
from sources.syensqo import collect_syensqo_jobs
from sources.solvay import collect_solvay_jobs
from sources.astrazeneca import collect_astrazeneca_jobs
from sources.amgen import collect_amgen_jobs
from sources.lonza import collect_lonza_jobs
from sources.roche import collect_roche_jobs
from sources.biowin import collect_biowin_jobs
from sources.biopark import collect_biopark_jobs
from sources.eurogentec import collect_eurogentec_jobs
from sources.trasis import collect_trasis_jobs
from sources.quantoom import collect_quantoom_jobs
from sources.hyloris import collect_hyloris_jobs
from sources.eyed_pharma import collect_eyed_pharma_jobs
from sources.nside import collect_nside_jobs
from sources.ire import collect_ire_jobs
from sources.novadip import collect_novadip_jobs
from sources.cer_groupe import collect_cer_groupe_jobs
from sources.kiomed import collect_kiomed_jobs
from sources.cerba import collect_cerba_jobs
from sources.msd import collect_msd_jobs
from sources.mega5_sources import collect_pauwels_jobs, collect_icon_jobs, collect_tmc_jobs, collect_qbd_group_jobs, collect_sopra_steria_jobs, collect_lilly_jobs, collect_thales_jobs
from sources.mega5_hold_sources import collect_odoo_hold_jobs
from sources.mega56_sources import collect_keyrus_jobs
from sources.mega58_sources import collect_medpace_jobs
from sources.mega59_sources import collect_univercells_tech_jobs, collect_lhoist_jobs
from sources.mega510_sources import collect_parexel_jobs, collect_polypeptide_jobs, collect_john_cockerill_jobs
from sources.mega512_sources import collect_amaris_jobs, collect_nrb_jobs, collect_iqvia_jobs, collect_capgemini_eng_jobs
from sources.mega513_sources import collect_abbvie_jobs, collect_csl_jobs, collect_boehringer_jobs
from sources.mega64_staffing import collect_experis_jobs, collect_synergie_jobs
from sources.mega65_staffing import collect_adecco_jobs, collect_manpower_jobs, collect_vivaldis_jobs, collect_select_hr_jobs, collect_agilitas_jobs, collect_ago_jobs, collect_lets_work_jobs, collect_oxford_global_jobs, collect_brunel_jobs, collect_austin_bright_jobs, collect_progressive_jobs
from sources.adecco_api import collect_adecco_jobs  # JOBHUNTER_ADECCO_JSON_V1
from sources.oxford_belgium import collect_oxford_global_jobs  # JOBHUNTER_OXFORD_BELGIUM_V1
from sources.mega67_high_value import collect_start_people_jobs, collect_tempo_team_jobs, collect_qjobs_jobs, collect_michael_page_jobs
from sources.mega67_high_value import collect_robert_half_jobs


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "source_settings.json"
SCHEDULER_SETTINGS_PATH = PROJECT_ROOT / "config" / "source_scheduler.json"

FOREM_MAX_PER_KEYWORD = 100
ACTIRIS_MAX_PER_KEYWORD = 100


@dataclass(frozen=True)
class SourceSpec:
    key: str
    result_key: str
    label: str
    collector: Callable[[], list]
    enabled_default: bool = True
    pipeline_group: str = "standard"
    languages: tuple[str, ...] = ("fr", "en")
    priority: int = 100
    notes: str = ""


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _origin(job) -> str:
    return (_clean(getattr(job, "origin_source", None)) or _clean(getattr(job, "source", None)) or "INCONNUE").upper()


# JOBHUNTER_UNIFIED_DETAIL_CONTRACT_V1
_DETAIL_ENRICH_THRESHOLD = 1000
_DETAIL_TARGET_SOURCES = {
    "JOBAT", "ACTIRIS", "FOREM", "TALENT_BRUSSELS", "TRAVAILLERPOUR"
}

def _detail_clean(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " | ".join(_detail_clean(x) for x in value if _detail_clean(x))
    if isinstance(value, dict):
        return " | ".join(_detail_clean(x) for x in value.values() if _detail_clean(x))
    return " ".join(str(value).split())

def _detail_pick(structured: dict, *keys):
    for key in keys:
        value = structured.get(key)
        if _detail_clean(value):
            return value
    return None

def _detail_is_relevant(job) -> bool:
    try:
        from matching.basic_matcher import score_job
        result = score_job(job)
        return bool(result.get("core_relevance"))
    except Exception:
        return False

def _fetch_existing_detail(source_key: str, job):
    source_key = str(source_key or "").upper()

    if source_key == "JOBAT":
        from sources.jobat_detail import get_jobat_job_detail
        return get_jobat_job_detail(
            getattr(job, "url", None),
            getattr(job, "external_id", None),
            use_cache=True,
            cache_only=True,
        )

    if source_key == "ACTIRIS":
        from sources.actiris_detail import get_actiris_job_detail
        return get_actiris_job_detail(
            getattr(job, "external_id", None),
            getattr(job, "actiris_offer_type", None),
            use_cache=True,
        )

    if source_key == "FOREM":
        from sources.forem_detail import get_forem_job_detail
        return get_forem_job_detail(
            getattr(job, "external_id", None) or getattr(job, "url", None),
            use_cache=True,
        )

    if source_key == "TALENT_BRUSSELS":
        from sources.talent_brussels_detail import get_talent_brussels_job_detail
        return get_talent_brussels_job_detail(
            getattr(job, "url", None),
            getattr(job, "external_id", None),
            use_cache=True,
        )

    if source_key == "TRAVAILLERPOUR":
        from sources.travaillerpour_detail import get_travaillerpour_job_detail
        return get_travaillerpour_job_detail(
            getattr(job, "url", None),
            getattr(job, "external_id", None),
            use_cache=True,
        )

    return {"success": False, "error": "Unsupported detail source."}

def _apply_detail_contract(job, detail: dict):
    if not detail or not detail.get("success"):
        setattr(job, "detail_enrichment_status", "FAILED")
        setattr(job, "detail_enrichment_error", _detail_clean((detail or {}).get("error")))
        return job

    current = _detail_clean(getattr(job, "description", None))
    matching_text = _detail_clean(detail.get("matching_text"))
    structured = detail.get("structured") or {}

    if matching_text and len(matching_text) > len(current):
        job.description = matching_text

    setattr(job, "full_description", matching_text or current)
    setattr(job, "detail_structured", structured)
    setattr(job, "detail_enrichment_status", "OK")
    setattr(job, "detail_from_cache", bool(detail.get("from_cache")))
    setattr(job, "detail_parser_version", detail.get("parser_version"))

    mapping = {
        "responsibilities": ("responsibilities", "tasks", "duties", "job_content", "job_description"),
        "requirements": ("requirements", "profile", "detailed_profile", "participation_section"),
        "qualifications": ("qualifications", "studies", "degree"),
        "education": ("education", "studies", "degree"),
        "experience": ("experience",),
        "skills": ("skills", "competencies", "competences"),
        "languages": ("languages", "language_section", "language"),
        "contract": ("contract_type", "work_regime"),
        "salary_detail": ("salary", "grade_scale"),
    }

    for target, aliases in mapping.items():
        value = _detail_pick(structured, *aliases)
        if value is not None:
            setattr(job, target, value)

    return job

def _enrich_relevant_details(jobs: list, source_key: str) -> list:
    source_key = str(source_key or "").upper()
    if source_key not in _DETAIL_TARGET_SOURCES:
        return jobs

    candidates = success = failed = cache_hits = 0

    for job in jobs:
        current = _detail_clean(getattr(job, "description", None))

        if len(current) >= _DETAIL_ENRICH_THRESHOLD:
            setattr(job, "detail_enrichment_status", "SKIPPED_RICH")
            continue

        if not _detail_is_relevant(job):
            setattr(job, "detail_enrichment_status", "SKIPPED_NOT_RELEVANT")
            continue

        candidates += 1
        try:
            detail = _fetch_existing_detail(source_key, job)
        except Exception as error:
            detail = {"success": False, "error": f"{type(error).__name__}: {error}"}

        if detail.get("success"):
            success += 1
            cache_hits += int(bool(detail.get("from_cache")))
        else:
            failed += 1

        _apply_detail_contract(job, detail)

    print(
        "DETAIL CONTRACT | "
        f"source={source_key} | candidates={candidates} | "
        f"success={success} | failed={failed} | cache={cache_hits}"
    )
    return jobs

def _collect_forem() -> list:
    plan = get_forem_scheduler_plan()

    print(
        "FOREM SCHEDULER | "
        f"profile={plan['profile']} | "
        f"live_terms={len(plan['live_terms'])} | "
        f"cache_only_terms={len(plan['cache_only_terms'])} | "
        f"bucket={plan.get('bucket_label')} | "
        f"full_due={int(bool(plan.get('full_due')))}"
    )

    raw_jobs = search_targeted_forem_jobs(
        search_terms=plan["live_terms"],
        max_per_keyword=FOREM_MAX_PER_KEYWORD,
    )

    raw_jobs, carry_stats = merge_cached_forem_results(
        raw_jobs,
        plan["cache_only_terms"],
    )

    print(
        "FOREM CACHE CARRY | "
        f"terms={carry_stats['cache_terms_loaded']} | "
        f"rows={carry_stats['cache_rows_loaded']} | "
        f"unique_total={len(raw_jobs)}"
    )

    mark_forem_scheduler_success(plan)

    jobs = []
    for raw_job in raw_jobs:
        try:
            job = convert_forem_job(raw_job)
            job.collection_channel = "FOREM"
            job.origin_source = "FOREM"
            jobs.append(job)
        except Exception as error:
            print("⚠️ Conversion Forem impossible :", error)
    return _enrich_relevant_details(jobs, "FOREM")


def _collect_actiris() -> list:
    raw_jobs = search_targeted_actiris_jobs(max_per_keyword=ACTIRIS_MAX_PER_KEYWORD)
    jobs = []
    for raw_job in raw_jobs:
        try:
            jobs.append(convert_actiris_job(raw_job))
        except Exception as error:
            print("⚠️ Conversion Actiris impossible :", error)

    origins = Counter(_origin(job) for job in jobs)
    if origins:
        print("ACTIRIS - provenance :")
        for origin, count in origins.most_common():
            print(f"  {origin:<15} {count}")
    return _enrich_relevant_details(jobs, "ACTIRIS")


def _collect_talent() -> list:
    raw_jobs = search_targeted_talent_brussels_jobs()
    jobs = []
    for raw_job in raw_jobs:
        try:
            jobs.append(convert_talent_brussels_job(raw_job))
        except Exception as error:
            print("⚠️ Conversion Talent impossible :", error)
    return _enrich_relevant_details(jobs, "TALENT_BRUSSELS")


def _collect_travaillerpour() -> list:
    raw_jobs = search_targeted_travaillerpour_jobs()
    jobs = []
    for raw_job in raw_jobs:
        try:
            jobs.append(convert_travaillerpour_job(raw_job))
        except Exception as error:
            print("⚠️ Conversion Travaillerpour impossible :", error)
    return _enrich_relevant_details(jobs, "TRAVAILLERPOUR")


def _collect_smartrecruiters() -> list:
    jobs, metas = fetch_smartrecruiters_jobs()
    failures = 0
    fatal_errors = 0
    for meta in metas:
        label = _clean(meta.get("label")) or _clean(meta.get("company_identifier"))
        belgium = int(meta.get("listings_belgium") or 0)
        converted = int(meta.get("jobs_converted") or 0)
        source_failures = len(meta.get("failures") or [])
        fatal = _clean(meta.get("fatal_error"))
        failures += source_failures
        fatal_errors += int(bool(fatal))
        print(
            f"  {label:<20} BE={belgium:<4} "
            f"converties={converted:<4} échecs={source_failures}"
        )
        if fatal:
            print("      ❌", fatal)
    print("SMARTRECRUITERS - échecs détail   :", failures)
    print("SMARTRECRUITERS - erreurs fatales :", fatal_errors)
    return jobs


def _collect_jobat() -> list:
    # Production policy V6: keep Jobat as a cache-only source until live access
    # becomes reliably usable again. Manual diagnostics can still request LIVE.
    raw_jobs = search_targeted_jobat_jobs(collection_mode="CACHE_ONLY")
    jobs = []
    for raw_job in raw_jobs:
        try:
            jobs.append(convert_jobat_job(raw_job))
        except Exception as error:
            print("⚠️ Conversion Jobat impossible :", error)
    return _enrich_relevant_details(jobs, "JOBAT")


def _collect_scienceatwork() -> list:
    return list(collect_scienceatwork_jobs() or [])


def _collect_randstad() -> list:
    return list(collect_randstad_jobs() or [])


def _collect_jeffersonwells() -> list:
    return list(collect_jeffersonwells_jobs() or [])


def _collect_akkodis() -> list:
    return list(collect_akkodis_jobs() or [])


def _collect_gsk() -> list:
    return list(collect_gsk_jobs() or [])


def _collect_ucb() -> list:
    return list(collect_ucb_jobs() or [])


def _collect_iba() -> list:
    return list(collect_iba_jobs() or [])


def _collect_pfizer() -> list:
    return list(collect_pfizer_jobs() or [])


def _collect_takeda() -> list:
    return list(collect_takeda_jobs() or [])


def _collect_jnj() -> list:
    return list(collect_jnj_jobs() or [])


def _collect_quality_assistance() -> list:
    return list(collect_quality_assistance_jobs() or [])


def _collect_thermofisher() -> list:
    return list(collect_thermofisher_jobs() or [])


def _collect_sciensano() -> list:
    return list(collect_sciensano_jobs() or [])


def _collect_sanofi() -> list:
    return list(collect_sanofi_jobs() or [])


def _collect_baxter() -> list:
    return list(collect_baxter_jobs() or [])


def _collect_novartis() -> list:
    return list(collect_novartis_jobs() or [])


def _collect_adzuna() -> list:
    return list(collect_adzuna_jobs() or [])


def _collect_careerjet() -> list:
    return list(collect_careerjet_jobs() or [])


def _collect_jooble() -> list:
    return list(collect_jooble_jobs() or [])


def _collect_prothya() -> list:
    return list(collect_prothya_jobs() or [])


def _collect_remotive() -> list:
    return list(collect_remotive_jobs() or [])


def _collect_air_liquide() -> list:
    return list(collect_air_liquide_jobs() or [])


def _collect_bms() -> list:
    return list(collect_bms_jobs() or [])


def _collect_galderma() -> list:
    return list(collect_galderma_jobs() or [])


def _collect_amgen() -> list:
    return list(collect_amgen_jobs() or [])


def _collect_beigene() -> list:
    return list(collect_beigene_jobs() or [])


def _collect_elanco() -> list:
    return list(collect_elanco_jobs() or [])


def _collect_europharmajobs() -> list:
    return list(collect_europharmajobs_jobs() or [])


def _collect_ictjob() -> list:
    return list(collect_ictjob_jobs() or [])


def _collect_references() -> list:
    return list(collect_references_jobs() or [])


def _collect_swde() -> list:
    return list(collect_swde_jobs() or [])


def _collect_arbeitnow() -> list:
    return list(collect_arbeitnow_jobs() or [])


def _collect_start_people_student() -> list:
    return list(collect_start_people_student_jobs() or [])


def _collect_synergie_student() -> list:
    return list(collect_synergie_student_jobs() or [])


def _collect_vdab_student_web() -> list:
    return list(collect_vdab_student_web_jobs() or [])


def _collect_student_be() -> list:
    return list(collect_student_be_jobs() or [])


def _collect_studentjob_be() -> list:
    return list(collect_studentjob_be_jobs() or [])


def _collect_randstad_student() -> list:
    return list(collect_randstad_student_jobs() or [])


def _make_direct_career_collector(key: str):
    def _collector():
        return list(collect_direct_career_jobs(key) or [])
    return _collector


SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec(
        key="FOREM",
        result_key="forem",
        label="Forem",
        collector=_collect_forem,
        languages=("fr", "en", "nl"),
        priority=10,
        notes="Source publique wallonne. Recherche large du pipeline historique.",
    ),
    SourceSpec(
        key="ADZUNA",
        result_key="adzuna",
        label="Adzuna Belgium API",
        collector=_collect_adzuna,
        languages=("fr", "en", "nl"),
        priority=12,
        notes="Official API. Equal targeting QC/Pharma/Lab + Junior Data/BI + QC/Data hybrid. Credentials required.",
    ),
    SourceSpec(
        key="CAREERJET",
        result_key="careerjet",
        label="Careerjet Belgium API",
        collector=_collect_careerjet,
        languages=("fr", "en", "nl"),
        priority=13,
        notes="Official Publisher API v4. QC/Pharma/Lab + Junior Data/BI. Requires API key + user IP.",
    ),
    SourceSpec(
        key="JOOBLE",
        result_key="jooble",
        label="Jooble Belgium API",
        collector=_collect_jooble,
        languages=("fr", "en", "nl"),
        priority=14,
        notes="Official Belgium REST API. Quota-aware rotating queries for QC/Pharma/Lab + Junior Data/BI.",
    ),
    SourceSpec(
        key="PROTHYA",
        result_key="prothya",
        label="Prothya Biosolutions Belgium",
        collector=_collect_prothya,
        languages=("fr", "en"),
        priority=15,
        notes="Direct Brussels pharma employer. QC + Business Automation/IT departments, target-title filtered.",
    ),
    SourceSpec(
        key="START_PEOPLE_STUDENT",
        result_key="start_people_student",
        label="Start People — Jobs étudiants",
        collector=_collect_start_people_student,
        languages=("fr","nl"),
        priority=18,
        notes="Dedicated Start People student-job listing. Strict real job detail URLs; STUDENT_ANY.",
    ),
    SourceSpec(
        key="SYNERGIE_STUDENT",
        result_key="synergie_student",
        label="Synergie — Jobs étudiants",
        collector=_collect_synergie_student,
        languages=("fr","nl"),
        priority=18,
        notes="Dedicated Synergie student-contract listing. Strict detail URLs; STUDENT_ANY.",
    ),
    SourceSpec(
        key="VDAB_STUDENT_WEB",
        result_key="vdab_student_web",
        label="VDAB — Student jobs public web",
        collector=_collect_vdab_student_web,
        languages=("nl","en","fr"),
        priority=19,
        notes="Public VDAB student-job web search; bounded read-only collection, no API credentials required. STUDENT_ANY.",
    ),
    SourceSpec(
        key="STUDENT_BE",
        result_key="student_be",
        label="Student.be — Jobs étudiants Belgique",
        collector=_collect_student_be,
        languages=("fr","en","nl"),
        priority=20,
        notes="Dedicated Belgian student jobs. Any genuine student-job domain accepted; Gate=VERIFY for student eligibility.",
    ),
    SourceSpec(
        key="STUDENTJOB_BE",
        result_key="studentjob_be",
        label="StudentJob.be — Jobs étudiants",
        collector=_collect_studentjob_be,
        languages=("fr","nl","en"),
        priority=21,
        notes="Dedicated student-job source. Any genuine job domain; low-value survey/game offers excluded.",
    ),
    SourceSpec(
        key="RANDSTAD_STUDENT",
        result_key="randstad_student",
        label="Randstad Belgium — Jobs étudiants",
        collector=_collect_randstad_student,
        languages=("fr","nl"),
        priority=22,
        notes="Randstad dedicated student-contract feed, separate from generic Randstad source.",
    ),
    SourceSpec(
        key="AIR_LIQUIDE",
        result_key="air_liquide",
        label="Air Liquide Belgium Workday",
        collector=_collect_air_liquide,
        languages=("fr","en","nl"),
        priority=15,
        notes="Public Workday endpoint. Belgium-only QC/Lab + Junior Data/BI + QC/Data hybrid.",
    ),
    SourceSpec(
        key="BMS",
        result_key="bms",
        label="Bristol Myers Squibb Belgium Workday",
        collector=_collect_bms,
        languages=("en","fr"),
        priority=15,
        notes="Public Workday endpoint. Belgium-only QC/Lab + Junior Data/BI + QC/Data hybrid.",
    ),
    SourceSpec(
        key="GALDERMA",
        result_key="galderma",
        label="Galderma Belgium Workday",
        collector=_collect_galderma,
        languages=("en","fr","nl"),
        priority=16,
        notes="Public Workday endpoint. Belgium-only QC/Lab + Junior Data/BI + QC/Data hybrid.",
    ),
    SourceSpec(
        key="AMGEN_WORKDAY",
        result_key="amgen_workday",
        label="Amgen Belgium Workday",
        collector=_collect_amgen,
        languages=("en","fr","nl"),
        priority=16,
        notes="Public Workday endpoint. Belgium-only QC/Lab + Junior Data/BI + QC/Data hybrid.",
    ),
    SourceSpec(
        key="BEIGENE",
        result_key="beigene",
        label="BeiGene / BeOne Belgium Workday",
        collector=_collect_beigene,
        languages=("en",),
        priority=17,
        notes="Public Workday endpoint. Belgium-only QC/Lab + Junior Data/BI + QC/Data hybrid.",
    ),
    SourceSpec(
        key="ELANCO",
        result_key="elanco",
        label="Elanco Belgium Workday",
        collector=_collect_elanco,
        languages=("en","nl"),
        priority=17,
        notes="Public Workday endpoint. Belgium-only QC/Lab + Junior Data/BI + QC/Data hybrid.",
    ),
    SourceSpec(
        key="REMOTIVE",
        result_key="remotive",
        label="Remotive Remote Jobs API",
        collector=_collect_remotive,
        languages=("en",),
        priority=16,
        notes="Official public remote-jobs API. Belgium/Europe/Worldwide filter; Junior Data/BI + QC/Data hybrid targeting.",
    ),
    SourceSpec(
        key="EUROPHARMAJOBS",
        result_key="europharmajobs",
        label="EuroPharmaJobs Belgium",
        collector=_collect_europharmajobs,
        languages=("en",),
        priority=16,
        notes="Belgium-filtered European pharma/science board. QC/Lab + junior Data/BI + hybrid roles.",
    ),
    SourceSpec(
        key="ICTJOB",
        result_key="ictjob",
        label="ICTjob Belgium",
        collector=_collect_ictjob,
        languages=("fr","en","nl"),
        priority=17,
        notes="Belgian IT/Data board. Junior Data Analyst/BI targeting; senior titles blocked.",
    ),
    SourceSpec(
        key="REFERENCES",
        result_key="references",
        label="Références.be",
        collector=_collect_references,
        languages=("fr",),
        priority=18,
        notes="Belgian francophone job board. Target-filtered QC/Lab and Junior Data/BI.",
    ),
    SourceSpec(
        key="SWDE",
        result_key="swde",
        label="SWDE",
        collector=_collect_swde,
        languages=("fr",),
        priority=19,
        notes="Official Walloon water employer. Laboratory/quality/data roles.",
    ),
    SourceSpec(
        key="ARBEITNOW",
        result_key="arbeitnow",
        label="Arbeitnow Europe API",
        collector=_collect_arbeitnow,
        languages=("en",),
        priority=19,
        notes="Free public European jobs API; Belgium-filtered QC/Lab and Junior Data/BI.",
    ),
    SourceSpec(
        key="ACTIRIS",
        result_key="actiris",
        label="Actiris",
        collector=_collect_actiris,
        languages=("fr", "en", "nl"),
        priority=20,
        notes="Source publique bruxelloise + partenaires.",
    ),
    SourceSpec(
        key="TALENT_BRUSSELS",
        result_key="talent",
        label="talent.brussels",
        collector=_collect_talent,
        languages=("fr", "nl"),
        priority=30,
        notes="Emplois de la Région de Bruxelles-Capitale.",
    ),
    SourceSpec(
        key="TRAVAILLERPOUR",
        result_key="travaillerpour",
        label="Travaillerpour.be",
        collector=_collect_travaillerpour,
        pipeline_group="special",
        languages=("fr", "nl"),
        priority=40,
        notes="Fonction publique fédérale. Traitement d'éligibilité spécifique.",
    ),
    SourceSpec(
        key="SMARTRECRUITERS",
        result_key="smartrecruiters",
        label="SmartRecruiters",
        collector=_collect_smartrecruiters,
        languages=("fr", "en", "nl"),
        priority=50,
        notes="Employeurs directs configurés via SmartRecruiters.",
    ),
    SourceSpec(
        key="JOBAT",
        result_key="jobat",
        label="Jobat",
        collector=_collect_jobat,
        languages=("fr", "en"),
        priority=60,
        notes="Source V2.1. Recherche ciblée FR/EN, bruit NL filtré au maximum.",
    ),
    SourceSpec(
        key="SCIENCEATWORK",
        result_key="scienceatwork",
        label="Science@Work",
        collector=_collect_scienceatwork,
        languages=("fr", "en"),
        priority=70,
        notes="Life sciences/labo/QA. Fiches détaillées publiques ; annonces NL filtrées à la source.",
    ),
    SourceSpec(
        key="RANDSTAD",
        result_key="randstad",
        label="Randstad",
        collector=_collect_randstad,
        languages=("fr", "en"),
        priority=80,
        notes="Collecte ciblée Data/BI + Lab/QC/R&D. Fiches complètes publiques ; NL et néerlandais professionnel filtrés.",
    ),
    SourceSpec(
        key="JEFFERSON_WELLS",
        result_key="jeffersonwells",
        label="Jefferson Wells",
        collector=_collect_jeffersonwells,
        languages=("fr", "en"),
        priority=90,
        notes="Consultance Engineering/Life Sciences. Préfiltre Data/BI + Lab/QC/Pharma ; fiches publiques FR/EN, NL filtré.",
    ),
    SourceSpec(
        key="AKKODIS",
        result_key="akkodis",
        label="Akkodis",
        collector=_collect_akkodis,
        languages=("fr", "en"),
        priority=100,
        notes="Consultance IT/Engineering/Life Sciences. Portail TalentSoft officiel Belgique ; préfiltre Data/BI + Lab/QC/Pharma, NL filtré.",
    ),
    SourceSpec(
        key="GSK",
        result_key="gsk",
        label="GSK",
        collector=_collect_gsk,
        languages=("fr", "en"),
        priority=110,
        notes="Employeur direct pharma/vaccins. Workday public Belgique ; préfiltre QC/Lab + Data/BI, stages et rôles seniors exclus.",
    ),
    SourceSpec(
        key="UCB",
        result_key="ucb",
        label="UCB",
        collector=_collect_ucb,
        languages=("fr", "en"),
        priority=120,
        notes="Employeur direct biopharma. Portail Phenom public Belgique/Braine/Bruxelles ; préfiltre QC/Lab/Analytical + Data/BI, rôles seniors et stages exclus.",
    ),
    SourceSpec(
        key="IBA",
        result_key="iba",
        label="IBA",
        collector=_collect_iba,
        languages=("fr", "en"),
        priority=130,
        notes="Employeur direct à Louvain-la-Neuve. SAP SuccessFactors public ; préfiltre QC/Lab/Analytical + Data/BI, rôles seniors et stages exclus.",
    ),
    SourceSpec(
        key="PFIZER",
        result_key="pfizer",
        label="Pfizer",
        collector=_collect_pfizer,
        languages=("fr", "en"),
        priority=140,
        notes="Employeur direct pharma. Workday public Belgique/Puurs ; préfiltre QC/Lab + Data/BI, stages et rôles seniors exclus.",
    ),
    SourceSpec(
        key="TAKEDA",
        result_key="takeda",
        label="Takeda",
        collector=_collect_takeda,
        languages=("fr", "en"),
        priority=150,
        notes="Employeur direct biopharma à Lessines. Site carrière officiel jobs.takeda.com ; cible Technicien Chimiste/Purification + QC/Lab + Data/BI, stages et rôles seniors exclus.",
    ),
    SourceSpec(
        key="JNJ",
        result_key="jnj",
        label="Johnson & Johnson / Janssen",
        collector=_collect_jnj,
        languages=("fr", "en"),
        priority=160,
        notes="Employeur direct pharma/MedTech. Workday public Belgique ; préfiltre QC/QA/Lab/Chimie + Data/BI, stages et rôles seniors exclus.",
    ),
    SourceSpec(
        key="QUALITY_ASSISTANCE",
        result_key="quality_assistance",
        label="Quality Assistance",
        collector=_collect_quality_assistance,
        languages=("fr", "en"),
        priority=170,
        notes="CRO analytique directe à Thuin. Site carrière public ; cible laboratoire/HPLC/chromatographie/QC + Data/BI, rôles leaders/commerciaux/stages exclus.",
    ),
    SourceSpec(
        key="THERMO_FISHER",
        result_key="thermofisher",
        label="Thermo Fisher Scientific",
        collector=_collect_thermofisher,
        languages=("fr", "en"),
        priority=180,
        notes="Employeur direct science/CRO. Portail Phenom public Belgique ; cible Lab/QC/QA/Analytical/Sample Management + Data/BI, rôles seniors/commerciaux/stages exclus.",
    ),
    SourceSpec(
        key="SCIENSANO",
        result_key="sciensano",
        label="Sciensano",
        collector=_collect_sciensano,
        enabled_default=False,
        languages=("fr", "en"),
        priority=190,
        notes="Source secondaire désactivée par défaut : portail jobs.sciensano.be instable/timeouts ; fallback index provisoire uniquement.",
    ),
    SourceSpec(
        key="SANOFI",
        result_key="sanofi",
        label="Sanofi",
        collector=_collect_sanofi,
        languages=("fr", "en"),
        priority=200,
        notes="Employeur direct pharma. Radancy public Belgique/Geel ; cible QC/Lab/Analytical + Data/BI, NL obligatoire et rôles seniors/stages exclus.",
    ),
    SourceSpec(
        key="BAXTER",
        result_key="baxter",
        label="Baxter",
        collector=_collect_baxter,
        languages=("fr", "en"),
        priority=210,
        notes="Employeur direct pharma/medtech. Radancy public Belgique/Lessines/Braine-l'Alleud ; cible Lab/QC/QA/R&D + Data, rôles seniors/leads exclus.",
    ),
    SourceSpec(
        key="NOVARTIS",
        result_key="novartis",
        label="Novartis",
        collector=_collect_novartis,
        languages=("fr", "en"),
        priority=220,
        notes="Employeur direct pharma. Career Search public Belgique/Puurs/Vilvoorde ; cible Business/Data Analyst + QC/Lab/QA, rôles seniors/managers exclus.",
    ),
    SourceSpec(
        key="AGFA",
        result_key="agfa",
        label="Agfa",
        collector=collect_agfa_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=72,
        notes="Batch 2.3 shadow validated; SuccessFactors; detail geography required.",
    ),
    SourceSpec(
        key="UMICORE",
        result_key="umicore",
        label="Umicore",
        collector=collect_umicore_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=73,
        notes="Batch 2.3 shadow validated; listing Belgium filter untrusted; detail geography mandatory.",
    ),
    SourceSpec(
        key="SYENSQO",
        result_key="syensqo",
        label="Syensqo",
        collector=collect_syensqo_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=74,
        notes="Batch 2.3 shadow validated; SuccessFactors; detail geography required.",
    ),
    SourceSpec(
        key="SOLVAY",
        result_key="solvay",
        label="Solvay",
        collector=collect_solvay_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=75,
        notes="Batch 2.3 shadow validated; SuccessFactors; detail geography required.",
    ),
    SourceSpec(
        key="ASTRAZENECA",
        result_key="astrazeneca",
        label="AstraZeneca",
        collector=collect_astrazeneca_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=76,
        notes="Official Belgium location page; detail geo validation.",
    ),
    SourceSpec(
        key="AMGEN",
        result_key="amgen",
        label="Amgen",
        collector=collect_amgen_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=77,
        notes="Official Belgium GeoNames country filter; detail geo validation.",
    ),
    SourceSpec(
        key="LONZA",
        result_key="lonza",
        label="Lonza",
        collector=collect_lonza_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=78,
        notes="Official Bornem/Verviers POST facets; strict Belgium listing truth.",
    ),
    SourceSpec(
        key="ROCHE",
        result_key="roche",
        label="Roche",
        collector=collect_roche_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=79,
        notes="Existing generic Phenom engine + Roche public Workday CXS details.",
    ),
    SourceSpec(
        key="BIOWIN",
        result_key="biowin",
        label="BioWin Job Board",
        collector=collect_biowin_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=80,
        notes="Wallonia/Brussels priority source; mandatory Dutch hard-gated.",
    ),
    SourceSpec(
        key="BIOPARK",
        result_key="biopark",
        label="BioPark.jobs",
        collector=collect_biopark_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=81,
        notes="Wallonia/Brussels priority source; mandatory Dutch hard-gated.",
    ),
    SourceSpec(
        key="EUROGENTEC",
        result_key="eurogentec",
        label="Kaneka Eurogentec",
        collector=collect_eurogentec_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=82,
        notes="Wallonia/Brussels priority source; mandatory Dutch hard-gated.",
    ),
    SourceSpec(
        key="TRASIS",
        result_key="trasis",
        label="Trasis",
        collector=collect_trasis_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=83,
        notes="Wallonia/Brussels priority source; mandatory Dutch hard-gated.",
    ),
    SourceSpec(
        key="QUANTOOM",
        result_key="quantoom",
        label="Quantoom Biosciences",
        collector=collect_quantoom_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=84,
        notes="Wallonia/Brussels priority source; mandatory Dutch hard-gated.",
    ),
    SourceSpec(
        key="HYLORIS",
        result_key="hyloris",
        label="Hyloris Pharmaceuticals",
        collector=collect_hyloris_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=85,
        notes="Wallonia/Brussels priority source; mandatory Dutch hard-gated.",
    ),
    SourceSpec(
        key="EYED_PHARMA",
        result_key="eyed_pharma",
        label="EyeD Pharma",
        collector=collect_eyed_pharma_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=86,
        notes="Wallonia/Brussels priority source; mandatory Dutch hard-gated.",
    ),
    SourceSpec(
        key="NSIDE",
        result_key="nside",
        label="N-SIDE",
        collector=collect_nside_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=87,
        notes="Cornerstone CSOD public API; Belgium strict geo gate.",
    ),
    SourceSpec(
        key="IRE",
        result_key="ire",
        label="IRE / IRE ELiT",
        collector=collect_ire_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=88,
        notes="Batch 4 Wallonia/Brussels direct career source.",
    ),
    SourceSpec(
        key="NOVADIP",
        result_key="novadip",
        label="Novadip Biosciences",
        collector=collect_novadip_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=89,
        notes="Batch 4 Wallonia/Brussels direct career source.",
    ),
    SourceSpec(
        key="CER_GROUPE",
        result_key="cer_groupe",
        label="CER Groupe",
        collector=collect_cer_groupe_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=90,
        notes="Batch 4 Wallonia/Brussels direct career source.",
    ),
    SourceSpec(
        key="KIOMED",
        result_key="kiomed",
        label="KiOmed Pharma",
        collector=collect_kiomed_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=91,
        notes="Batch 4 Wallonia/Brussels direct career source.",
    ),
    SourceSpec(
        key="CERBA",
        result_key="cerba",
        label="Cerba HealthCare Belgium",
        collector=collect_cerba_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=92,
        notes="Batch 4 independent conditional integration.",
    ),
    SourceSpec(
        key="MSD",
        result_key="msd",
        label="MSD Belgium",
        collector=collect_msd_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=95,
        notes="Batch 4 independent conditional integration.",
    ),
    SourceSpec(
        key="PAUWELS",
        result_key="pauwels",
        label="Pauwels Consulting",
        collector=collect_pauwels_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=96,
        notes="Mega Batch 5 independent hardened source.",
    ),
    SourceSpec(
        key="ICON",
        result_key="icon",
        label="ICON Belgium",
        collector=collect_icon_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=97,
        notes="Mega Batch 5 independent hardened source.",
    ),
    SourceSpec(
        key="TMC",
        result_key="tmc",
        label="The Member Company / TMC",
        collector=collect_tmc_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=99,
        notes="Mega Batch 5 independent hardened source.",
    ),
    SourceSpec(
        key="QBD_GROUP",
        result_key="qbd_group",
        label="QbD Group",
        collector=collect_qbd_group_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=100,
        notes="Mega Batch 5 independent hardened source.",
    ),
    SourceSpec(
        key="SOPRA_STERIA",
        result_key="sopra_steria",
        label="Sopra Steria Belgium",
        collector=collect_sopra_steria_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=103,
        notes="Mega Batch 5 independent hardened source.",
    ),
    SourceSpec(
        key="LILLY",
        result_key="lilly",
        label="Eli Lilly Belgium",
        collector=collect_lilly_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=104,
        notes="Mega Batch 5 independent hardened source.",
    ),
    SourceSpec(
        key="THALES",
        result_key="thales",
        label="Thales Belgium",
        collector=collect_thales_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=105,
        notes="Mega Batch 5 independent hardened source.",
    ),
    SourceSpec(
        key="ODOO",
        result_key="odoo",
        label="Odoo",
        collector=collect_odoo_hold_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=106,
        notes="Mega Batch 5.4 independently resolved HOLD source.",
    ),
    SourceSpec(
        key="KEYRUS",
        result_key="keyrus",
        label="Keyrus Belgium",
        collector=collect_keyrus_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=113,
        notes="Mega Batch 5.6 strict true-source integration.",
    ),
    SourceSpec(
        key="MEDPACE",
        result_key="medpace",
        label="Medpace Belgium",
        collector=collect_medpace_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=122,
        notes="Mega Batch 5.8 recovered source using native engine.",
    ),
    SourceSpec(
        key="UNIVERCELLS_TECH",
        result_key="univercells_tech",
        label="Univercells Technologies",
        collector=collect_univercells_tech_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=125,
        notes="Mega Batch 5.9 recovered/healthy source.",
    ),
    SourceSpec(
        key="LHOIST",
        result_key="lhoist",
        label="Lhoist",
        collector=collect_lhoist_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=126,
        notes="Mega Batch 5.9 recovered/healthy source.",
    ),
    SourceSpec(
        key="PAREXEL",
        result_key="parexel",
        label="Parexel Belgium",
        collector=collect_parexel_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=131,
        notes="Mega Batch 5.10 specific recovered source.",
    ),
    SourceSpec(
        key="POLYPEPTIDE",
        result_key="polypeptide",
        label="PolyPeptide Belgium",
        collector=collect_polypeptide_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=132,
        notes="Mega Batch 5.10 specific recovered source.",
    ),
    SourceSpec(
        key="JOHN_COCKERILL",
        result_key="john_cockerill",
        label="John Cockerill",
        collector=collect_john_cockerill_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=133,
        notes="Mega Batch 5.10 specific recovered source.",
    ),
    SourceSpec(
        key="AMARIS",
        result_key="amaris",
        label="Amaris Consulting",
        collector=collect_amaris_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=134,
        notes="Mega Batch 5.12 verified real job feed.",
    ),
    SourceSpec(
        key="NRB",
        result_key="nrb",
        label="KEYES (ex-NRB)",
        collector=collect_nrb_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=135,
        notes="Mega Batch 5.12 verified real job feed.",
    ),
    SourceSpec(
        key="IQVIA",
        result_key="iqvia",
        label="IQVIA Belgium",
        collector=collect_iqvia_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=136,
        notes="Mega Batch 5.12 verified real job feed.",
    ),
    SourceSpec(
        key="CAPGEMINI_ENG",
        result_key="capgemini_eng",
        label="Capgemini Belgium",
        collector=collect_capgemini_eng_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=137,
        notes="Mega Batch 5.12 verified real job feed.",
    ),
    SourceSpec(
        key="ABBVIE",
        result_key="abbvie",
        label="AbbVie Belgium",
        collector=collect_abbvie_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=138,
        notes="Mega Batch 5.13 verified official feed.",
    ),
    SourceSpec(
        key="CSL",
        result_key="csl",
        label="CSL Behring Belgium",
        collector=collect_csl_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=139,
        notes="Mega Batch 5.13 verified official feed.",
    ),
    SourceSpec(
        key="BOEHRINGER",
        result_key="boehringer",
        label="Boehringer Ingelheim Belgium",
        collector=collect_boehringer_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=140,
        notes="Mega Batch 5.13 verified official feed.",
    ),
    SourceSpec(
        key="EXPERIS",
        result_key="experis",
        label="Experis Belgium",
        collector=collect_experis_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=141,
        notes="Mega Batch 6.4 strict staffing connector.",
    ),
    SourceSpec(
        key="SYNERGIE",
        result_key="synergie",
        label="Synergie Belgium",
        collector=collect_synergie_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=142,
        notes="Mega Batch 6.4 strict staffing connector.",
    ),
    SourceSpec(
        key="ADECCO",
        result_key="adecco",
        label="Adecco Belgium",
        collector=collect_adecco_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=143,
        notes="Mega Batch 6.5 strict healthy staffing feed.",
    ),
    SourceSpec(
        key="MANPOWER",
        result_key="manpower",
        label="Manpower Belgium",
        collector=collect_manpower_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=144,
        notes="Mega Batch 6.5 strict healthy staffing feed.",
    ),
    SourceSpec(
        key="VIVALDIS",
        result_key="vivaldis",
        label="Vivaldis",
        collector=collect_vivaldis_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=145,
        notes="Mega Batch 6.5 strict healthy staffing feed.",
    ),
    SourceSpec(
        key="SELECT_HR",
        result_key="select_hr",
        label="Select HR",
        collector=collect_select_hr_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=147,
        notes="Mega Batch 6.5 strict healthy staffing feed.",
    ),
    SourceSpec(
        key="AGILITAS",
        result_key="agilitas",
        label="Proman / ex-Agilitas",
        collector=collect_agilitas_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=148,
        notes="Mega Batch 6.5 strict healthy staffing feed.",
    ),
    SourceSpec(
        key="AGO",
        result_key="ago",
        label="AGO Jobs & HR",
        collector=collect_ago_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=149,
        notes="Mega Batch 6.5 strict healthy staffing feed.",
    ),
    SourceSpec(
        key="LETS_WORK",
        result_key="lets_work",
        label="Let's Work",
        collector=collect_lets_work_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=150,
        notes="Mega Batch 6.5 strict healthy staffing feed.",
    ),
    SourceSpec(
        key="OXFORD_GLOBAL",
        result_key="oxford_global",
        label="Oxford Global Resources",
        collector=collect_oxford_global_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=152,
        notes="Mega Batch 6.5 strict healthy staffing feed.",
    ),
    SourceSpec(
        key="BRUNEL",
        result_key="brunel",
        label="Brunel Belgium",
        collector=collect_brunel_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=153,
        notes="Mega Batch 6.5 strict healthy staffing feed.",
    ),
    SourceSpec(
        key="AUSTIN_BRIGHT",
        result_key="austin_bright",
        label="Austin Bright",
        collector=collect_austin_bright_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=154,
        notes="Mega Batch 6.5 strict healthy staffing feed.",
    ),
    SourceSpec(
        key="PROGRESSIVE",
        result_key="progressive",
        label="Progressive Recruitment",
        collector=collect_progressive_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=155,
        notes="Mega Batch 6.5 strict healthy staffing feed.",
    ),
    SourceSpec(
        key="START_PEOPLE",
        result_key="start_people",
        label="Start People Belgium",
        collector=collect_start_people_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=156,
        notes="Mega Batch 6.7 high-value staffing source.",
    ),
    SourceSpec(
        key="TEMPO_TEAM",
        result_key="tempo_team",
        label="Tempo-Team Belgium",
        collector=collect_tempo_team_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=157,
        notes="Mega Batch 6.7 high-value staffing source.",
    ),
    SourceSpec(
        key="QJOBS",
        result_key="qjobs",
        label="Q Jobs Belgium",
        collector=collect_qjobs_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=159,
        notes="Mega Batch 6.7 high-value staffing source.",
    ),
    SourceSpec(
        key="MICHAEL_PAGE",
        result_key="michael_page",
        label="Michael Page BeLux",
        collector=collect_michael_page_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=160,
        notes="Mega Batch 6.7 high-value staffing source.",
    ),
    SourceSpec(
        key="ROBERT_HALF",
        result_key="robert_half",
        label="Robert Half Belgium",
        collector=collect_robert_half_jobs,
        enabled_default=True,
        pipeline_group="standard",
        languages=("fr", "en"),
        priority=158,
        notes="Mega Batch 6.8 Robert Half corrected URL feed.",
    ),
)


# V11 declarative direct-career expansion.
# Each enabled config row becomes a real independent SourceSpec while sharing
# one generic collector engine.
_direct_specs = []
for _cfg in load_employer_configs():
    _key = str(_cfg.get("key") or "").strip().upper()
    if not _key or any(_existing.key == _key for _existing in SOURCE_SPECS):
        continue
    _direct_specs.append(
        SourceSpec(
            key=_key,
            result_key=_key.lower(),
            label=str(_cfg.get("label") or _key),
            collector=_make_direct_career_collector(_key),
            enabled_default=True,
            pipeline_group="standard",
            languages=tuple(_cfg.get("languages") or ("fr","en","nl")),
            priority=int(_cfg.get("priority") or 45),
            notes="V11 declarative direct-career source. Generic JSON-LD/job-link engine; QC/Lab + Data junior + QC/Data hybrid.",
        )
    )
SOURCE_SPECS = tuple(SOURCE_SPECS) + tuple(_direct_specs)


# V14: validated backlog sources are declarative and share one generic engine.
_v14_specs = []
for _cfg in load_v14_backlog(include_all=False):
    _key = str(_cfg.get("key") or "").strip().upper()
    if not _key or any(_s.key == _key for _s in SOURCE_SPECS):
        continue
    _v14_specs.append(
        SourceSpec(
            key=_key,
            result_key=_key.lower(),
            label=str(_cfg.get("name") or _key),
            collector=make_backlog_collector(_key),
            enabled_default=True,
            pipeline_group=str(_cfg.get("pipeline_group") or "standard"),
            languages=tuple(_cfg.get("languages") or ("fr","nl","en")),
            priority=int(_cfg.get("priority") or 100),
            notes="V14 auto-validated public source | " + str(_cfg.get("probe_reason") or ""),
        )
    )
SOURCE_SPECS = tuple(SOURCE_SPECS) + tuple(_v14_specs)


def _default_settings() -> dict[str, bool]:
    return {spec.key: spec.enabled_default for spec in SOURCE_SPECS}


def load_source_settings() -> dict[str, bool]:
    settings = _default_settings()
    if not SETTINGS_PATH.exists():
        return settings
    try:
        payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        enabled = payload.get("enabled", payload)
        if isinstance(enabled, dict):
            for key, value in enabled.items():
                key = str(key).upper().strip()
                if key in settings:
                    settings[key] = bool(value)
    except Exception as error:
        print("⚠️ Lecture source_settings.json impossible :", error)
    return settings


def save_source_settings(settings: dict[str, bool]) -> Path:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized = _default_settings()
    for key, value in (settings or {}).items():
        key = str(key).upper().strip()
        if key in normalized:
            normalized[key] = bool(value)
    payload = {
        "version": 1,
        "enabled": normalized,
    }
    temp = SETTINGS_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(SETTINGS_PATH)
    return SETTINGS_PATH


def set_source_enabled(key: str, enabled: bool) -> Path:
    settings = load_source_settings()
    key = str(key).upper().strip()
    if key not in settings:
        raise KeyError(f"Source inconnue : {key}")
    settings[key] = bool(enabled)
    return save_source_settings(settings)


def list_source_status() -> list[dict]:
    settings = load_source_settings()
    rows = []
    for spec in sorted(SOURCE_SPECS, key=lambda item: item.priority):
        active = bool(settings.get(spec.key, spec.enabled_default))
        health = get_source_health(spec.key, enabled=active)
        rows.append(
            {
                "key": spec.key,
                "source": spec.label,
                "active": active,
                "health": health["health"],
                "collection_mode": health["collection_mode"],
                "health_reason": health["reason"],
                "groupe": spec.pipeline_group,
                "langues": "/".join(language.upper() for language in spec.languages),
                "notes": spec.notes,
            }
        )
    return rows


def enabled_source_specs() -> list[SourceSpec]:
    settings = load_source_settings()
    return [
        spec
        for spec in sorted(SOURCE_SPECS, key=lambda item: item.priority)
        if bool(settings.get(spec.key, spec.enabled_default))
    ]


def _load_source_scheduler_settings() -> dict:
    payload = {
        "version": 1,
        "workers": 1,
        "exclusive_sources": ["JOBAT"],
    }
    if not SCHEDULER_SETTINGS_PATH.exists():
        return payload
    try:
        raw = json.loads(SCHEDULER_SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            payload.update(raw)
    except Exception as error:
        print("⚠️ Lecture source_scheduler.json impossible :", error)
    return payload


def source_worker_count(workers_override: int | None = None) -> int:
    """
    V1 safety policy:
    - production default = 1 until explicitly enabled;
    - maximum = 6 workers;
    - env JOBHUNTER_SOURCE_WORKERS overrides config for diagnostics.
    """
    raw = workers_override

    if raw is None:
        env_value = os.environ.get("JOBHUNTER_SOURCE_WORKERS")
        if env_value not in {None, ""}:
            raw = env_value

    if raw is None:
        raw = _load_source_scheduler_settings().get("workers", 1)

    try:
        workers = int(raw)
    except Exception:
        workers = 1

    return max(1, min(6, workers))


def _source_lane_key(spec: SourceSpec) -> str:
    """
    Sources implemented by the same module are serialized in one lane.
    Registry wrapper collectors are source-specific and therefore receive
    one lane per source.
    """
    module = str(getattr(spec.collector, "__module__", "") or "")
    if module == __name__:
        return f"registry_wrapper:{spec.key}"

    # PERFORMANCE BIG GAINS V1
    # mega65 uses local HTTP sessions. Shared diagnostic publication is
    # protected in mega65_staffing.py, so each website can have its own lane.
    if module == "sources.mega65_staffing":
        return f"sources.mega65_staffing:{spec.key}"

    return module or f"collector:{spec.key}"


_LANE_WEIGHT_HINTS = {
    "registry_wrapper:JOBAT": 1000,
    "registry_wrapper:ACTIRIS": 1000,
    "sources.mega65_staffing:MANPOWER": 970,
    "sources.mega65_staffing:AGO": 960,
    "sources.mega65_staffing:BRUNEL": 950,
    "registry_wrapper:FOREM": 940,
    "sources.adecco_api": 930,
    "sources.mega67_high_value": 920,
    "sources.mega65_staffing:LETS_WORK": 900,
    "registry_wrapper:RANDSTAD": 780,
    "sources.mega65_staffing:SELECT_HR": 700,
    "sources.mega65_staffing:AGILITAS": 690,
    "sources.mega65_staffing:AUSTIN_BRIGHT": 680,
    "sources.mega65_staffing:PROGRESSIVE": 670,
    "sources.mega65_staffing:VIVALDIS": 660,
    "registry_wrapper:JEFFERSON_WELLS": 700,
    "registry_wrapper:SMARTRECRUITERS": 660,
    "registry_wrapper:GSK": 620,
    "registry_wrapper:PFIZER": 600,
}


def _lane_sort_key(item):
    lane_key, specs = item
    weight = int(_LANE_WEIGHT_HINTS.get(lane_key, 0))
    # More members means more serial work inside this family.
    weight += min(200, max(0, len(specs) - 1) * 20)
    first_priority = min(spec.priority for spec in specs)
    return (-weight, first_priority, lane_key)


def _run_one_source(
    spec: SourceSpec,
    source_number: int,
    enabled_total: int,
    *,
    scheduler_mode: str,
) -> tuple[dict, list, str | None]:
    source_started = time.perf_counter()
    print(
        f"SOURCE_PROGRESS | {source_number}/{enabled_total} | "
        f"key={spec.key} | label={spec.label} | START | mode={scheduler_mode}"
    )
    print()
    print("=" * 76)
    print(f"              SOURCE {source_number} - {spec.label.upper()}")
    print("=" * 76)

    jobs = []
    error_message = None

    try:
        clear_source_metrics(spec.key)
        jobs = list(spec.collector() or [])
        metrics = get_source_metrics(spec.key)
        runtime_health = runtime_source_health(
            spec.key,
            enabled=True,
            error=None,
            metrics=metrics,
        )
        summary = {
            "key": spec.key,
            "label": spec.label,
            "enabled": True,
            "count": len(jobs),
            "error": None,
            "metrics": metrics,
            "health": runtime_health["health"],
            "collection_mode": runtime_health["collection_mode"],
            "health_reason": runtime_health["reason"],
        }
        print(f"{spec.label.upper()} - offres converties : {len(jobs)}")
    except Exception as error:
        error_message = f"{type(error).__name__}: {error}"
        runtime_health = runtime_source_health(
            spec.key,
            enabled=True,
            error=error_message,
            metrics=None,
        )
        summary = {
            "key": spec.key,
            "label": spec.label,
            "enabled": True,
            "count": 0,
            "error": error_message,
            "metrics": None,
            "health": runtime_health["health"],
            "collection_mode": runtime_health["collection_mode"],
            "health_reason": runtime_health["reason"],
        }
        print(f"❌ {spec.label} indisponible pour ce run : {error_message}")
        print("   Le pipeline continue avec les autres sources.")

    source_elapsed = time.perf_counter() - source_started
    summary["duration_seconds"] = round(source_elapsed, 3)
    summary["scheduler_lane"] = _source_lane_key(spec)
    runtime_count = int(summary.get("count") or 0)
    runtime_status = "ERROR" if summary.get("error") else "OK"
    print(
        f"SOURCE_RUNTIME | {source_number}/{enabled_total} | key={spec.key} | "
        f"seconds={source_elapsed:.3f} | jobs={runtime_count} | status={runtime_status} | "
        f"mode={scheduler_mode}"
    )
    return summary, jobs, error_message


def _run_source_lane(
    lane_key: str,
    specs: list[SourceSpec],
    source_numbers: dict[str, int],
    enabled_total: int,
) -> list[tuple[SourceSpec, dict, list, str | None]]:
    print(
        f"SCHEDULER_LANE | key={lane_key} | sources={len(specs)} | "
        f"state=START"
    )
    outputs = []
    for spec in specs:
        summary, jobs, error_message = _run_one_source(
            spec,
            source_numbers[spec.key],
            enabled_total,
            scheduler_mode="PARALLEL",
        )
        outputs.append((spec, summary, jobs, error_message))
    print(
        f"SCHEDULER_LANE | key={lane_key} | sources={len(specs)} | "
        f"state=DONE"
    )
    return outputs


def collect_enabled_sources(workers_override: int | None = None) -> dict:
    """
    Collecte toutes les sources actives et renvoie le contrat attendu par main.py.

    Source Scheduler V1:
    - 1 worker = comportement séquentiel historique;
    - 2..4 workers = parallélisme réseau entre familles sûres;
    - les collecteurs du même module restent séquentiels;
    - l'ordre final des résultats reste celui de SOURCE_SPECS;
    - aucune écriture SQLite n'est déplacée dans les workers.
    """
    settings = load_source_settings()
    result: dict[str, list] = {spec.result_key: [] for spec in SOURCE_SPECS}
    errors: dict[str, str] = {}
    summaries_by_key: dict[str, dict] = {}

    print()
    print("=" * 76)
    print("                     REGISTRE DES SOURCES")
    print("=" * 76)
    for spec in sorted(SOURCE_SPECS, key=lambda item: item.priority):
        state = "ON " if settings.get(spec.key, spec.enabled_default) else "OFF"
        print(f"  [{state}] {spec.label:<22} langues={('/'.join(spec.languages)).upper()}")

    ordered_specs = sorted(SOURCE_SPECS, key=lambda item: item.priority)
    enabled_specs = [
        spec
        for spec in ordered_specs
        if bool(settings.get(spec.key, spec.enabled_default))
    ]
    enabled_total = len(enabled_specs)
    source_numbers = {
        spec.key: index
        for index, spec in enumerate(enabled_specs, 1)
    }

    workers = source_worker_count(workers_override)
    scheduler_mode = "SEQUENTIAL" if workers == 1 else "PARALLEL"

    print()
    print("=" * 76)
    print("                   SOURCE SCHEDULER V1")
    print("=" * 76)
    print(f"Workers demandés/appliqués : {workers}")
    print(f"Mode                      : {scheduler_mode}")
    print("Politique                  : même module => séquentiel")
    print("SQLite                     : hors workers / inchangé")

    if workers == 1:
        for spec in enabled_specs:
            summary, jobs, error_message = _run_one_source(
                spec,
                source_numbers[spec.key],
                enabled_total,
                scheduler_mode="SEQUENTIAL",
            )
            result[spec.result_key] = jobs
            summaries_by_key[spec.key] = summary
            if error_message:
                errors[spec.key] = error_message
    else:
        scheduler_settings = _load_source_scheduler_settings()
        raw_exclusive = scheduler_settings.get("exclusive_sources", ["JOBAT"])
        if not isinstance(raw_exclusive, list):
            raw_exclusive = ["JOBAT"]

        exclusive_keys = {
            str(value).strip().upper()
            for value in raw_exclusive
            if str(value).strip()
        }
        # V1 FIX1 hard safety: Jobat is always exclusive because its Edge
        # browser became dramatically slower under concurrent network load.
        exclusive_keys.add("JOBAT")

        exclusive_specs = [
            spec for spec in enabled_specs
            if spec.key.upper() in exclusive_keys
        ]
        parallel_specs = [
            spec for spec in enabled_specs
            if spec.key.upper() not in exclusive_keys
        ]

        print(
            "Exclusive sources          : "
            + (",".join(spec.key for spec in exclusive_specs) or "NONE")
        )

        # Phase A: sources that must not compete for browser/network resources.
        # They run in the historical sequential way.
        if exclusive_specs:
            print()
            print("=" * 76)
            print("             SOURCE SCHEDULER V1 FIX1 - EXCLUSIVE PHASE")
            print("=" * 76)
            for spec in exclusive_specs:
                summary, jobs, error_message = _run_one_source(
                    spec,
                    source_numbers[spec.key],
                    enabled_total,
                    scheduler_mode="EXCLUSIVE",
                )
                result[spec.result_key] = jobs
                summaries_by_key[spec.key] = summary
                if error_message:
                    errors[spec.key] = error_message

        # Phase B: all remaining independent source families.
        lanes: dict[str, list[SourceSpec]] = defaultdict(list)
        for spec in parallel_specs:
            lanes[_source_lane_key(spec)].append(spec)

        lane_items = sorted(lanes.items(), key=_lane_sort_key)
        print()
        print("=" * 76)
        print("              SOURCE SCHEDULER V1 FIX1 - PARALLEL PHASE")
        print("=" * 76)
        print(f"Parallel workers          : {workers}")
        print(f"Parallel lanes            : {len(lane_items)}")
        for lane_key, specs in lane_items:
            print(
                f"  LANE | {lane_key:<38} | "
                f"{','.join(spec.key for spec in specs)}"
            )

        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="jobhunter-source",
        ) as executor:
            future_map = {
                executor.submit(
                    _run_source_lane,
                    lane_key,
                    specs,
                    source_numbers,
                    enabled_total,
                ): lane_key
                for lane_key, specs in lane_items
            }

            for future in as_completed(future_map):
                lane_key = future_map[future]
                try:
                    outputs = future.result()
                except Exception as error:
                    print(
                        f"❌ SCHEDULER_LANE_ERROR | key={lane_key} | "
                        f"{type(error).__name__}: {error}"
                    )
                    continue

                for spec, summary, jobs, error_message in outputs:
                    result[spec.result_key] = jobs
                    summaries_by_key[spec.key] = summary
                    if error_message:
                        errors[spec.key] = error_message

    summaries: list[dict] = []
    for spec in ordered_specs:
        enabled = bool(settings.get(spec.key, spec.enabled_default))
        if not enabled:
            summaries.append(
                {
                    "key": spec.key,
                    "label": spec.label,
                    "enabled": False,
                    "count": 0,
                    "error": None,
                }
            )
            continue

        summary = summaries_by_key.get(spec.key)
        if summary is None:
            message = "SchedulerError: source result missing"
            errors[spec.key] = message
            summary = {
                "key": spec.key,
                "label": spec.label,
                "enabled": True,
                "count": 0,
                "error": message,
                "metrics": None,
                "duration_seconds": None,
                "scheduler_lane": _source_lane_key(spec),
            }
        summaries.append(summary)

    # IMPORTANT: preserve historical deterministic order of aggregated jobs.
    standard_jobs = []
    special_jobs = []
    for spec in SOURCE_SPECS:
        jobs = result.get(spec.result_key, [])
        if spec.pipeline_group == "standard":
            standard_jobs.extend(jobs)
        else:
            special_jobs.extend(jobs)

    result["standard_jobs"] = standard_jobs
    result["jobs"] = standard_jobs + special_jobs
    result["source_errors"] = errors
    result["source_summaries"] = summaries
    result["source_scheduler"] = {
        "version": "2.0-big-gains-v1",
        "workers": workers,
        "mode": scheduler_mode,
        "exclusive_sources": (
            sorted(exclusive_keys) if workers > 1 else []
        ),
    }
    return result


# ============================================================
# EXTENSION LOCALE — CONNECTEURS ATS PUBLICS
# ============================================================
#
# Les cinq connecteurs ATS construits dans ce dossier vivent dans
# sources/registry_ats_v1.py, pas ici. Ce bloc est le seul ajout local au
# registre : il est place en fin de fichier pour que le reste reste
# identique au projet principal et donc resynchronisable par simple copie.
#
# SOURCE_SPECS est relu a l'appel par list_source_status() et
# enabled_source_specs() : le reassigner ici suffit.

from sources.registry_ats_v1 import (  # noqa: E402
    _collect_greenhouse,
    _collect_vdab,
    _collect_phenom,
    _collect_recruitee,
    _collect_successfactors,
    _collect_workday,
)

SOURCE_SPECS = SOURCE_SPECS + (
    SourceSpec(
        key="RECRUITEE",
        result_key="recruitee",
        label="Recruitee",
        collector=_collect_recruitee,
        languages=("fr", "en", "nl"),
        priority=70,
        notes="ATS public. Employeurs dans config/recruitee_sources.py. "
              "country_code structure.",
    ),
    SourceSpec(
        key="GREENHOUSE",
        result_key="greenhouse",
        label="Greenhouse",
        collector=_collect_greenhouse,
        languages=("fr", "en", "nl"),
        priority=71,
        notes="ATS public. Localisation en texte libre : filtrage via "
              "sources/location_belgium.py.",
    ),
    SourceSpec(
        key="WORKDAY_ATS",
        result_key="workday_ats",
        label="Workday (ATS public)",
        collector=_collect_workday,
        languages=("fr", "en", "nl"),
        priority=72,
        notes="Connecteur ATS generique local, distinct du moteur "
              "sources/workday.py du projet principal.",
    ),
    SourceSpec(
        key="SUCCESSFACTORS_ATS",
        result_key="successfactors_ats",
        label="SuccessFactors (ATS public)",
        collector=_collect_successfactors,
        languages=("fr", "en", "nl"),
        priority=73,
        notes="Lecture sitemap public. Distinct du moteur "
              "sources/successfactors.py du projet principal.",
    ),
    SourceSpec(
        key="PHENOM_ATS",
        result_key="phenom_ats",
        label="Phenom (ATS public)",
        collector=_collect_phenom,
        languages=("fr", "en", "nl"),
        priority=74,
        notes="Sitemap public + JSON-LD schema.org/JobPosting. Distinct du "
              "moteur sources/phenom.py du projet principal.",
    ),
)

SOURCE_SPECS = SOURCE_SPECS + (
    SourceSpec(
        key="VDAB",
        result_key="vdab",
        label="VDAB (sitemap public)",
        collector=_collect_vdab,
        enabled_default=False,
        languages=("nl", "en"),
        priority=11,
        notes="DESACTIVE : verifie le 8 septembre 2026, les pages d'offres "
              "sont construites en JavaScript et alimentees par "
              "/api/vindeenjob/, interdit par robots.txt. Le sitemap "
              "fonctionne mais ne mene a aucun contenu lisible. A reactiver "
              "avec l'API officielle (ibm-api-key + X-IBM-Client-Id).",
    ),
)


# ============================================================
# EXTENSION LOCALE — ABSORPTION COMPLETE FOREM / ACTIRIS
# ============================================================
#
# Les catalogues entiers remplacent la recherche par termes. Le detail
# reste borne par run (config/absorption_settings.json). Voir
# sources/registry_absorption_v1.py ; ce bloc est le seul point d'entree.

from sources.registry_absorption_v1 import appliquer_absorption  # noqa: E402

SOURCE_SPECS = appliquer_absorption(SOURCE_SPECS)


# ============================================================
# EXTENSION LOCALE — EXPANSION DES SOURCES (ATS 2e generation + JSON-LD)
# ============================================================
#
# Lever, Ashby, Workable, Personio et l'extracteur universel sitemap +
# JSON-LD. Leurs employeurs viennent de config/ats_employers_v2.json,
# rempli par sources/source_discovery_v1.py. Voir registry_expansion_v1.py.

from sources.registry_expansion_v1 import specs_expansion  # noqa: E402

SOURCE_SPECS = SOURCE_SPECS + specs_expansion(SourceSpec)
