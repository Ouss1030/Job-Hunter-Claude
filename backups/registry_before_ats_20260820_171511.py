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
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sources.forem import search_targeted_forem_jobs, convert_forem_job
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


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "source_settings.json"

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


def _collect_forem() -> list:
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
    return jobs


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
    return jobs


def _collect_talent() -> list:
    raw_jobs = search_targeted_talent_brussels_jobs()
    jobs = []
    for raw_job in raw_jobs:
        try:
            jobs.append(convert_talent_brussels_job(raw_job))
        except Exception as error:
            print("⚠️ Conversion Talent impossible :", error)
    return jobs


def _collect_travaillerpour() -> list:
    raw_jobs = search_targeted_travaillerpour_jobs()
    jobs = []
    for raw_job in raw_jobs:
        try:
            jobs.append(convert_travaillerpour_job(raw_job))
        except Exception as error:
            print("⚠️ Conversion Travaillerpour impossible :", error)
    return jobs


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
    raw_jobs = search_targeted_jobat_jobs()
    jobs = []
    for raw_job in raw_jobs:
        try:
            jobs.append(convert_jobat_job(raw_job))
        except Exception as error:
            print("⚠️ Conversion Jobat impossible :", error)
    return jobs


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
        notes="Nouvelle source V2.1. Recherche ciblée FR/EN, bruit NL filtré au maximum.",
    ),
)


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
        rows.append(
            {
                "key": spec.key,
                "source": spec.label,
                "active": bool(settings.get(spec.key, spec.enabled_default)),
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


def collect_enabled_sources() -> dict:
    """Collecte toutes les sources actives et renvoie le contrat attendu par main.py."""
    settings = load_source_settings()
    result: dict[str, list] = {spec.result_key: [] for spec in SOURCE_SPECS}
    errors: dict[str, str] = {}
    summaries: list[dict] = []

    print()
    print("=" * 76)
    print("                     REGISTRE DES SOURCES")
    print("=" * 76)
    for spec in sorted(SOURCE_SPECS, key=lambda item: item.priority):
        state = "ON " if settings.get(spec.key, spec.enabled_default) else "OFF"
        print(f"  [{state}] {spec.label:<22} langues={('/'.join(spec.languages)).upper()}")

    source_number = 0
    for spec in sorted(SOURCE_SPECS, key=lambda item: item.priority):
        enabled = bool(settings.get(spec.key, spec.enabled_default))
        if not enabled:
            summaries.append({"key": spec.key, "label": spec.label, "enabled": False, "count": 0, "error": None})
            continue

        source_number += 1
        print()
        print("=" * 76)
        print(f"              SOURCE {source_number} - {spec.label.upper()}")
        print("=" * 76)
        try:
            jobs = list(spec.collector() or [])
            result[spec.result_key] = jobs
            summaries.append({"key": spec.key, "label": spec.label, "enabled": True, "count": len(jobs), "error": None})
            print(f"{spec.label.upper()} - offres converties : {len(jobs)}")
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            errors[spec.key] = message
            summaries.append({"key": spec.key, "label": spec.label, "enabled": True, "count": 0, "error": message})
            print(f"❌ {spec.label} indisponible pour ce run : {message}")
            print("   Le pipeline continue avec les autres sources.")

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
    return result
