from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import date
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MASTER_PATH = PROJECT_ROOT / "config" / "master_search_terms.json"
MASTER_STRATEGY_PATH = PROJECT_ROOT / "config" / "master_search_strategy_v2.json"

GLOBAL_TITLE_EXCLUSIONS = re.compile(
    r"\b(?:senior|sr\.?|principal|staff|director|directeur|head|"
    r"vice\s+president|vp|manager|management|team\s+lead(?:er)?|"
    r"supervisor|superviseur|intern(?:ship)?|stage|stagiaire|stagiair|"
    r"trainee|apprentice(?:ship)?|student|phd|ph\.?d\.?|doctorat)\b",
    re.I,
)


def _normalize(value: str) -> str:
    value = str(value or "").replace("’", "'")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"[^a-z0-9+#]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _dedupe(values):
    out = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        key = _normalize(text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


@lru_cache(maxsize=1)
def get_master_search_terms() -> list[str]:
    try:
        payload = json.loads(MASTER_PATH.read_text(encoding="utf-8"))
        terms = payload.get("terms") or []
        terms = _dedupe(terms)
        if terms:
            return terms
    except Exception:
        pass

    # Safe fallback for pre-install/import edge cases.
    from config.profile import get_collection_search_terms
    return _dedupe(get_collection_search_terms())


def master_term_count() -> int:
    return len(get_master_search_terms())


def matching_master_terms(text: str) -> list[str]:
    haystack = _normalize(text)
    if not haystack:
        return []

    padded = f" {haystack} "
    matches = []

    for term in get_master_search_terms():
        needle = _normalize(term)
        if len(needle) < 2:
            continue
        if f" {needle} " in padded:
            matches.append(term)

    return matches


def matches_master_text(text: str) -> bool:
    return bool(matching_master_terms(text))


def matches_master_title(title: str) -> bool:
    title = str(title or "").strip()
    if not title:
        return False
    if GLOBAL_TITLE_EXCLUSIONS.search(title):
        return False
    return bool(matching_master_terms(title))


def master_track_hits(title: str) -> list[str]:
    if not matches_master_title(title):
        return []

    low = _normalize(title)
    out = []

    if re.search(
        r"\b(?:data|business analyst|power bi|reporting|dashboard|"
        r"data steward|data governance|data management|database|etl|sql)\b",
        low,
    ):
        out.append("DATA_BI")

    if re.search(
        r"\b(?:qc|qa|quality|qualite|controle qualite|assurance qualite|"
        r"labor|lab|chim|chem|analytical|microbio|hplc|uplc|chromato|"
        r"spectro|gmp|validation|qualification|formulation|cell culture|"
        r"culture cellulaire|production)\b",
        low,
    ):
        out.append("CHEM_LAB")

    if re.search(
        r"\b(?:lims|eln|laboratory informatics|lab systems|data integrity|"
        r"quality data|qc data|manufacturing data|scientific data)\b",
        low,
    ):
        out.append("HYBRID")

    if not out:
        # Master pool already established relevance. Keep it discoverable and
        # let downstream matcher/gate decide exact track.
        out.append("MASTER_POOL")

    return out


def get_source_query_terms(
    source_key: str,
    legacy_core_terms=None,
    rotation_buckets: int = 4,
) -> list[str]:
    """MASTER400 V2: CORE80 + one ROTATION80; FULL env returns all 400."""
    try:
        payload = json.loads(MASTER_STRATEGY_PATH.read_text(encoding="utf-8"))
        core = _dedupe(payload.get("core_terms") or [])
        buckets_obj = payload.get("rotation_buckets") or {}
        ordered = [_dedupe(buckets_obj.get(str(i)) or []) for i in range(1, 5)]
        master = _dedupe(core + [term for bucket_terms in ordered for term in bucket_terms])
        if len(core) == 80 and len(master) == 400 and all(len(x) == 80 for x in ordered):
            if str(os.environ.get("JOBHUNTER_MASTER_TERMS_FULL", "")).strip() == "1":
                active = master
                mode = "FULL"
            else:
                forced = str(os.environ.get("JOBHUNTER_ROTATION_BUCKET", "")).strip()
                bucket = int(forced) - 1 if forced in {"1","2","3","4"} else date.today().toordinal() % 4
                active = _dedupe(core + ordered[bucket])
                mode = f"CORE80+ROTATION80 {bucket + 1}/4"
            print("UNIFIED MASTER TERMS | "
                  f"source={str(source_key).upper()} | mode={mode} | "
                  f"active={len(active)} | master={len(master)}")
            return active
    except Exception:
        pass

    master = get_master_search_terms()
    core = _dedupe(legacy_core_terms or [])
    if str(os.environ.get("JOBHUNTER_MASTER_TERMS_FULL", "")).strip() == "1":
        active = master
        mode = "FULL-LEGACY"
    else:
        buckets = max(1, int(rotation_buckets or 1))
        core_keys = {_normalize(x) for x in core}
        secondary = [x for x in master if _normalize(x) not in core_keys]
        bucket = date.today().toordinal() % buckets
        selected = [term for index, term in enumerate(secondary) if index % buckets == bucket]
        active = _dedupe(core + selected)
        mode = f"LEGACY CORE+ROTATION {bucket + 1}/{buckets}"
    print("UNIFIED MASTER TERMS | "
          f"source={str(source_key).upper()} | mode={mode} | "
          f"active={len(active)} | master={len(master)}")
    return active


# JOBHUNTER_RAW_CATALOG_PRODUCTION_V1
# Catalogue/listing sources always use the complete 400-term discovery universe.
# Keyword-native query scheduling remains controlled separately by
# get_source_query_terms() and the existing active Master configuration.
FULL_CATALOG_MASTER_PATH = PROJECT_ROOT / "config" / "master_search_terms_full_400.json"


@lru_cache(maxsize=1)
def get_catalog_master_search_terms() -> list[str]:
    try:
        payload = json.loads(FULL_CATALOG_MASTER_PATH.read_text(encoding="utf-8"))
        raw_terms = payload.get("terms") or []

        # RAW CATALOG MASTER400 LOADER FIX V1
        # master_search_terms_full_400.json stores structured term objects.
        # Extract their actual textual value before normalization/deduplication.
        values = []
        for item in raw_terms:
            if isinstance(item, dict):
                item = (
                    item.get("term")
                    or item.get("value")
                    or item.get("label")
                    or ""
                )
            values.append(item)

        terms = _dedupe(values)
        if terms:
            return terms
    except Exception:
        pass
    return get_master_search_terms()


def catalog_master_term_count() -> int:
    return len(get_catalog_master_search_terms())


def matching_catalog_master_terms(text: str) -> list[str]:
    haystack = _normalize(text)
    if not haystack:
        return []

    padded = f" {haystack} "
    matches = []
    for term in get_catalog_master_search_terms():
        needle = _normalize(term)
        if len(needle) < 2:
            continue
        if f" {needle} " in padded:
            matches.append(term)
    return matches


def matches_catalog_master_text(text: str) -> bool:
    return bool(matching_catalog_master_terms(text))


def matches_catalog_master_title(title: str) -> bool:
    title = str(title or "").strip()
    if not title:
        return False
    if GLOBAL_TITLE_EXCLUSIONS.search(title):
        return False
    return bool(matching_catalog_master_terms(title))


# Compatibility: catalogue engines already calling matches_master_title()
# now use FULL 400 locally. Query scheduling is unaffected.
def matches_master_title(title: str) -> bool:
    return matches_catalog_master_title(title)
