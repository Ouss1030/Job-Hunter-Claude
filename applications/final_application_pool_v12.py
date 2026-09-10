"""
JOB HUNTER BELGIUM
FINAL APPLICATION POOL - VERSION 1.2

Construit le pool final directement depuis le dernier Application Recheck live et applique :
1. un dédoublonnage live plus robuste ;
2. un garde-fou final sur les descriptions ;
3. un reclassement APPLY_NOW / APPLY_NEXT / REVIEW_FIRST / DO_NOT_APPLY ;
4. A+ / A / B / C.

Aucune écriture DB.
Aucun appel réseau.
Aucune modification du Matcher/Gate/Queue.

Usage :
    python -m applications.final_application_pool
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from matching.verdict import evaluer as evaluer_verdict, FERMEE
from config.final_pool import (
    CANDIDATE_LANGUAGES,
    KNOWN_CREDENTIALS,
    KNOWN_SKILLS,
    PREFERRED_LOCATION_TERMS,
    CORE_LAB_TERMS,
    PRODUCTION_SCIENCE_TERMS,
    QUALITY_TERMS,
    DATA_TERMS,
    OFF_DOMAIN_TITLE_TERMS,
    MECHANICAL_QUALITY_HARD_TERMS,
    MECHANICAL_CONTEXT_TERMS,
    HOSPITAL_QUALITY_TERMS,
    ELECTRICAL_QA_DEGREE_TERMS,
    DUP_JACCARD_STRONG,
    DUP_JACCARD_SAME_LOCATION,
    DUP_TITLE_SAME_LOCATION,
    MAX_TXT_ITEMS,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

FINAL_POOL_VERSION = "1.3"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize(value: Any) -> str:
    text = clean_text(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'").replace("`", "'")
    text = re.sub(r"[^a-z0-9+#./' -]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def latest_file(pattern: str) -> Path | None:
    paths = list(LOG_DIR.glob(pattern))
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def contains_any(text: str, terms: list[str]) -> bool:
    n = normalize(text)
    return any(normalize(term) in n for term in terms)


def preferred_location(location: str) -> bool:
    """Correspondance géographique bornée : Evere ne doit pas matcher Beveren."""
    n = normalize(location)
    if not n:
        return False
    for term in PREFERRED_LOCATION_TERMS:
        t = normalize(term)
        if not t:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])"
        if re.search(pattern, n):
            return True
    return False


def classify_track(title: str, current_track: str = "") -> str:
    t = normalize(title)

    if clean_text(current_track).upper() == "DATA" or contains_any(t, DATA_TERMS):
        return "DATA"

    # Les formes inclusives telles que "Opérateur(trice)" deviennent
    # "operateur trice" après normalisation et ne doivent pas échapper
    # au track production.
    production_patterns = [
        r"\boperateur(?: trice)? de synthese\b",
        r"\boperateur(?: trice)? de production\b",
        r"\bproductieoperator\b",
        r"\bproduction operator\b",
    ]
    if any(re.search(pattern, t) for pattern in production_patterns):
        return "PRODUCTION_SCIENCE"

    if contains_any(t, PRODUCTION_SCIENCE_TERMS):
        return "PRODUCTION_SCIENCE"
    if contains_any(t, CORE_LAB_TERMS):
        return "LAB_QC"
    if contains_any(t, QUALITY_TERMS):
        return "QUALITY"
    return clean_text(current_track).upper() or "OTHER"

def off_domain_title(title: str) -> bool:
    return contains_any(title, OFF_DOMAIN_TITLE_TERMS)



# ---------------------------------------------------------------------------
# Construction directe depuis Recheck + Job Refresh live
# ---------------------------------------------------------------------------

def refresh_index(refresh_payload: list[dict]) -> dict[str, dict]:
    out = {}
    for item in refresh_payload:
        if not isinstance(item, dict):
            continue
        key = clean_text(item.get("stable_item_key"))
        if key:
            out[key] = item
    return out


def title_strength(track: str, title: str) -> int:
    if off_domain_title(title):
        return -12
    if track == "LAB_QC":
        return 10
    if track == "PRODUCTION_SCIENCE":
        return 8
    if track == "DATA":
        return 7
    if track == "QUALITY":
        return 4
    return 0


def baseline_score(item: dict) -> float:
    base = item.get("queue_score")
    if base is None:
        base = item.get("priority_score")
    if base is None:
        base = item.get("match_score")
    score = float(base or 0)

    if item.get("preferred_location"):
        score += 10

    score += title_strength(item.get("track") or "", item.get("title") or "")

    if item.get("pool_origin") == "RECHECK_STRETCH":
        score -= 12

    if item.get("off_domain_title"):
        score -= 10

    return round(score, 1)


def baseline_action(item: dict) -> tuple[str, str]:
    score = float(item.get("final_score") or 0)
    direct = item.get("pool_origin") == "READY_DOCUMENTS"
    preferred = bool(item.get("preferred_location"))
    off_domain = bool(item.get("off_domain_title"))
    track = item.get("track")

    if direct and preferred and not off_domain and score >= 110:
        return "A+", "APPLY_NOW"

    if direct and not off_domain and (
        score >= 110
        or (preferred and score >= 95)
        or (track in {"LAB_QC", "PRODUCTION_SCIENCE", "DATA"} and score >= 105)
    ):
        return "A", "APPLY_NOW"

    if direct and not off_domain and score >= 90:
        return "B", "APPLY_NEXT"

    if direct:
        return "C", "APPLY_NEXT"

    if score >= 100 and not off_domain:
        return "B", "REVIEW_OPTIONAL"
    return "C", "REVIEW_OPTIONAL"


def build_from_current_recheck(recheck: list[dict], refresh_map: dict[str, dict]) -> list[dict]:
    items = []
    missing_refresh = []
    stale_live = []

    for row in recheck:
        if not isinstance(row, dict):
            continue

        status = clean_text(row.get("status"))
        if status not in {"READY_DOCUMENTS", "STRETCH_REVIEW"}:
            continue

        key = clean_text(row.get("stable_item_key"))
        live = refresh_map.get(key)
        if not live:
            missing_refresh.append((key, row.get("title"), row.get("url")))
            continue

        detail = live.get("live_detail") or {}
        matching_text = clean_text(detail.get("matching_text"))
        live_ok = (
            bool(detail.get("success"))
            and not bool(detail.get("from_cache", False))
            and len(matching_text) >= 120
        )
        if not live_ok:
            stale_live.append((key, row.get("title"), row.get("url")))
            continue

        origin = "READY_DOCUMENTS" if status == "READY_DOCUMENTS" else "RECHECK_STRETCH"

        item = {
            "stable_item_key": key,
            "canonical_job_id": live.get("canonical_job_id"),
            "application_group_id": clean_text(
                live.get("application_group_id") or row.get("application_group_id")
            ),
            "title": clean_text(row.get("title")),
            "company": clean_text(row.get("company")),
            "location": clean_text(row.get("location")),
            "url": clean_text(row.get("url")),
            "source": clean_text(live.get("source")),
            "origin_source": clean_text(live.get("origin_source")),
            "queue_rank": row.get("queue_rank"),
            "queue_score": row.get("queue_score"),
            "match_score": row.get("match_score"),
            "priority_score": row.get("queue_score"),
            "cv_track": clean_text(row.get("cv_track")),
            "pool_origin": origin,
            "recheck_status": status,
            "recheck_version": clean_text(row.get("recheck_version")),
            "warnings": list(row.get("warnings") or []),
            "reasons": list(row.get("reasons") or []),
            "description": matching_text,
            "application_folder": live.get("application_folder"),
            "output_files": live.get("output_files") or {},
            "refresh_version": clean_text(live.get("refresh_version")),
        }

        item["track"] = classify_track(item["title"], item["cv_track"])
        item["preferred_location"] = preferred_location(item["location"])
        item["off_domain_title"] = off_domain_title(item["title"])
        item["final_score"] = baseline_score(item)
        priority, action = baseline_action(item)
        item["priority"] = priority
        item["recommended_action"] = action
        items.append(item)

    if missing_refresh:
        raise RuntimeError(
            "Final Pool V1.2 bloqué : éléments Recheck sans Job Refresh live : "
            + repr(missing_refresh[:10])
        )

    if stale_live:
        raise RuntimeError(
            "Final Pool V1.2 bloqué : descriptions live absentes/cache/trop courtes : "
            + repr(stale_live[:10])
        )

    return items


def validate_recheck_versions(recheck: list[dict]) -> str:
    versions = {
        clean_text(row.get("recheck_version"))
        for row in recheck
        if isinstance(row, dict) and clean_text(row.get("recheck_version"))
    }
    if len(versions) != 1:
        raise RuntimeError(f"Versions Recheck incohérentes : {sorted(versions)}")
    return next(iter(versions))


# ---------------------------------------------------------------------------
# Garde-fou description live
# ---------------------------------------------------------------------------

def _high_language_requirement(description: str, language: str) -> bool:
    """
    Détecte une exigence linguistique élevée explicite.

    V1.2 évite deux faux positifs :
    - les métadonnées Actiris "Néérlandais (atout) ... C1" ;
    - un "atout" situé dans la phrase suivante ne doit pas annuler une vraie
      exigence de la phrase courante.
    """
    raw = str(description or "")
    chunks = [
        normalize(chunk)
        for chunk in re.split(r"(?<=[.!?;:])\s+|[\r\n]+", raw)
        if normalize(chunk)
    ]

    if language == "nl":
        patterns = [
            r"\bneerlandais\b.{0,40}\b(c1|c2)\b",
            r"\bnederlands\b.{0,40}\b(c1|c2)\b",
            r"\bzeer goed nederlands\b",
            r"\bvlot nederlands\b",
            r"\bvloeiend nederlands\b",
            r"\bgoede beheersing van (?:het )?nederlands\b",
            r"\bje beheerst (?:het )?nederlands\b",
            r"\btweetalig\b.{0,30}\b(nl|nederlands|fr)\b",
            r"\bexcellent.{0,80}\bdutch\b",
            r"\bexcellent written and oral communication skills in dutch\b",
        ]
    elif language == "en":
        patterns = [
            r"\banglais\b.{0,40}\b(c1|c2)\b",
            r"\bengels\b.{0,40}\b(c1|c2)\b",
            r"\bzeer goed engels\b",
            r"\bvlot engels\b",
            r"\bfluent english\b",
            r"\bprofessional english\b",
            r"\banglais professionnel\b",
            r"\bexcellent.{0,80}\benglish\b",
            r"\bexcellent written and oral communication skills in dutch and english\b",
        ]
    else:
        return False

    optional_markers = [
        "atout", "un plus", "pluspunt", "asset", "nice to have",
        "mooi meegenomen", "preferred", "preferable", "bij voorkeur",
    ]

    for chunk in chunks:
        if not any(re.search(pattern, chunk) for pattern in patterns):
            continue
        if any(normalize(marker) in chunk for marker in optional_markers):
            continue
        return True

    return False

def _german_requirement(description: str) -> bool:
    d = normalize(description)
    return any([
        re.search(r"\ballemand\b.{0,30}\b(b2|c1|c2)\b", d),
        re.search(r"\bduits\b.{0,30}\b(b2|c1|c2)\b", d),
        "bilingue francais - allemand" in d,
        "bilingue français - allemand" in description.lower(),
    ])


def _mandatory_forklift(description: str) -> bool:
    d = normalize(description)
    markers = [
        "brevet cariste frontal",
        "brevet cariste",
        "heftruckattest",
    ]
    if not any(x in d for x in markers):
        return False
    hard = [
        "obligatoire", "indispensable", "must",
        "geldig heftruckattest", "in het bezit van",
        "vous possedez le brevet", "brevet obligatoire",
    ]
    return any(x in d for x in hard)


def _cell_culture_core(description: str, title: str) -> bool:
    d = normalize(description)
    t = normalize(title)
    return (
        "cell culture" in t
        or "culture cellulaire" in t
        or "performing cell passages" in d
        or "cell passages" in d
    )


def _mandatory_haccp(description: str) -> bool:
    d = normalize(description)
    if "haccp" not in d:
        return False
    markers = [
        "connaissance pratique",
        "maitrise",
        "maîtrise",
        "prerequis necessaires",
        "prérequis nécessaires",
        "must-have",
        "indispensable",
        "required",
    ]
    return any(normalize(x) in d for x in markers)


def _mechanical_quality_mismatch(description: str) -> bool:
    d = normalize(description)
    hard_count = sum(1 for x in MECHANICAL_QUALITY_HARD_TERMS if normalize(x) in d)
    ctx = any(normalize(x) in d for x in MECHANICAL_CONTEXT_TERMS)
    return hard_count >= 2 and ctx


def _hospital_quality_mismatch(description: str, title: str) -> bool:
    if "qualit" not in normalize(title):
        return False
    d = normalize(description)
    hits = sum(1 for x in HOSPITAL_QUALITY_TERMS if normalize(x) in d)
    return hits >= 2


def _electrical_qa_degree_mismatch(description: str) -> bool:
    d = normalize(description)
    degree_hit = any(normalize(x) in d for x in ELECTRICAL_QA_DEGREE_TERMS)
    context_hit = any(x in d for x in [
        "electricite", "electromecanique", "instrumentation",
        "equipements electriques", "pièces de reserve", "pieces de reserve",
    ])
    return degree_hit and context_hit


def _data_finance_gap(item: dict) -> bool:
    if item.get("track") != "DATA":
        return False
    d = normalize(item.get("description"))
    # Le profil Data est académique/projet, sans expérience pro Data/finance.
    finance_hits = sum(1 for x in [
        "finance", "comptabilite", "comptable", "valorisation",
        "inventaires", "concepts comptables", "sap business object",
    ] if x in d)
    return finance_hits >= 3


def _production_experience_gap(item: dict) -> str | None:
    track = item.get("track")
    title = normalize(item.get("title"))
    if track != "PRODUCTION_SCIENCE" and not any(x in title for x in [
        "operateur de production", "operator productie", "productieoperator",
        "operateur de synthese", "process operator",
    ]):
        return None

    d = normalize(item.get("description"))

    hard_patterns = [
        r"experience probante.{0,45}operateur.{0,20}synthese.{0,40}indispensable",
        r"experience indispensable.{0,50}conduite de process industriel",
        r"experience.{0,30}3 a 5 ans.{0,80}production",
        r"3 a 5 ans.{0,80}environnement de production",
    ]
    if any(re.search(p, d) for p in hard_patterns):
        return "BLOCK"

    review_patterns = [
        r"premiere experience.{0,60}operateur de production",
        r"experience en environnement de production industrielle",
        r"experience.{0,40}production industrielle",
        r"ervaring.{0,40}productieomgeving",
    ]
    if any(re.search(p, d) for p in review_patterns):
        return "REVIEW"

    return None


def _quality_management_experience_gap(item: dict) -> bool:
    """
    Un rôle de coordination/management qualité demandant plusieurs années
    dédiées n'est pas équivalent automatiquement à 3 ans de QC laboratoire.
    On conserve la candidature en REVIEW, pas en BLOCK.
    """
    if item.get("track") != "QUALITY":
        return False

    title = normalize(item.get("title"))
    if not any(term in title for term in [
        "quality coordinator",
        "coordinateur qualite",
        "responsable assurance qualite",
        "quality manager",
    ]):
        return False

    d = normalize(item.get("description"))
    patterns = [
        r"experience de 3 a 5 ans minimum.{0,80}fonction qualite",
        r"minimum 3 ans d'experience.{0,100}qualite",
        r"3 a 5 ans minimum.{0,100}qualite",
        r"minimaal 3 jaar.{0,100}kwaliteit",
    ]
    return any(re.search(pattern, d) for pattern in patterns)


def final_guard(item: dict) -> dict:
    title = clean_text(item.get("title"))
    desc = clean_text(item.get("description"))
    flags = []
    level = "PASS"  # PASS / REVIEW / VERIFY / BLOCK

    if off_domain_title(title):
        flags.append("Intitulé explicitement hors domaine chimie/pharma/labo")
        level = "BLOCK"

    if _mechanical_quality_mismatch(desc):
        flags.append(
            "Missions centrées métrologie mécanique / contrôle tridimensionnel / GD&T"
        )
        level = "BLOCK"

    if _electrical_qa_degree_mismatch(desc):
        flags.append(
            "Diplôme technique électricité/électromécanique/instrumentation demandé ; "
            "profil chimie non équivalent démontré"
        )
        level = "BLOCK"

    if _german_requirement(desc):
        flags.append("Allemand professionnel/B2+ demandé ; niveau candidat non démontré")
        if level != "BLOCK":
            level = "REVIEW"

    if _high_language_requirement(desc, "nl"):
        flags.append("Néerlandais C1/C2 ou aisance professionnelle détecté ; candidat B1")
        if level == "PASS":
            level = "REVIEW"

    if _high_language_requirement(desc, "en"):
        flags.append("Anglais C1/C2 ou aisance professionnelle détecté ; candidat B1")
        if level == "PASS":
            level = "REVIEW"

    if _mandatory_forklift(desc) and not KNOWN_CREDENTIALS["forklift"]:
        flags.append("Brevet/attestation cariste explicitement requis ; non démontré dans le profil")
        if level not in {"BLOCK"}:
            level = "VERIFY"

    if _cell_culture_core(desc, title) and not KNOWN_SKILLS["cell_culture"]:
        flags.append("Culture cellulaire au cœur du poste ; expérience candidat non démontrée")
        if level == "PASS":
            level = "REVIEW"

    if _mandatory_haccp(desc) and not KNOWN_SKILLS["haccp"]:
        flags.append("HACCP demandé comme connaissance pratique ; expérience non démontrée")
        if level == "PASS":
            level = "REVIEW"

    if _hospital_quality_mismatch(desc, title):
        flags.append(
            "Qualité hospitalière / sécurité des soins : expérience dédiée non démontrée"
        )
        if level == "PASS":
            level = "REVIEW"

    if _quality_management_experience_gap(item):
        flags.append(
            "Expérience dédiée de coordination/management qualité (3+ ans) demandée ; "
            "parcours candidat principalement QC laboratoire"
        )
        if level == "PASS":
            level = "REVIEW"

    if _data_finance_gap(item):
        flags.append(
            "Fonction Data fortement finance/comptabilité ; expérience professionnelle dédiée non démontrée"
        )
        if level == "PASS":
            level = "REVIEW"

    prod_gap = _production_experience_gap(item)
    if prod_gap == "BLOCK":
        flags.append(
            "Expérience spécifique de production/process explicitement indispensable et non démontrée"
        )
        level = "BLOCK"
    elif prod_gap == "REVIEW":
        flags.append(
            "Expérience de production industrielle demandée ; parcours candidat principalement QC/laboratoire"
        )
        if level == "PASS":
            level = "REVIEW"

    return {
        "guard_level": level,
        "guard_flags": flags,
    }


# ---------------------------------------------------------------------------
# Dédoublonnage
# ---------------------------------------------------------------------------

STOP_TOKENS = {
    "description", "fonction", "profil", "offre", "belgique", "temps",
    "travail", "contrat", "interim", "famille", "metiers", "lieu",
    "reference", "cree", "formulaire", "contact", "avantages", "poste",
    "compétences", "competences", "linguistiques",
}


def token_set(text: str) -> set[str]:
    toks = re.findall(r"[a-z0-9']{3,}", normalize(text))
    return {x for x in toks if x not in STOP_TOKENS}


def jaccard_description(a: dict, b: dict) -> float:
    sa = token_set(a.get("description") or "")
    sb = token_set(b.get("description") or "")
    if len(sa) < 8 or len(sb) < 8:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def norm_title(title: str) -> str:
    t = normalize(title)
    t = re.sub(r"\b[hmf]\s*/\s*[hmfv]\s*/\s*x\b", " ", t)
    for x in [
        "h f x", "m v x", "f h x", "x", "cdi", "interim",
        "temps plein", "vaste", "ploegen",
    ]:
        t = re.sub(rf"\b{re.escape(x)}\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def title_similarity(a: dict, b: dict) -> float:
    ta = norm_title(a.get("title") or "")
    tb = norm_title(b.get("title") or "")
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, ta, tb).ratio()


def canonical_place(location: str, description: str = "") -> str:
    n = normalize(location + " " + description[:1000])
    aliases = [
        ("braine-l-alleud", ["braine-l'alleud", "braine l'alleud", "braine l alleud", "1420"]),
        ("rebecq-bierghes", ["rebecq", "bierghes", "1430"]),
        ("louvain-la-neuve", ["louvain-la-neuve", "louvain la neuve", "1348", "ottignies"]),
        ("spa", ["spa", "4900"]),
        ("leuze-en-hainaut", ["leuze-en-hainaut", "leuze en hainaut", "7900"]),
        ("antoing-fontenoy", ["antoing", "fontenoy", "7643"]),
        ("wilrijk", ["wilrijk", "2610"]),
        ("zonhoven-genk", ["zonhoven", "genk", "3520"]),
        ("soumagne", ["soumagne"]),
    ]
    for label, terms in aliases:
        if any(normalize(x) in n for x in terms):
            return label

    cps = re.findall(r"\b\d{4}\b", normalize(location))
    if cps:
        return cps[0]
    words = [
        x for x in re.findall(r"[a-z]{4,}", normalize(location))
        if x not in {
            "belgique", "province", "region", "wallonne",
            "flamande", "brabant", "hainaut",
        }
    ]
    return words[0] if words else ""


def same_place(a: dict, b: dict) -> bool:
    pa = canonical_place(a.get("location") or "", a.get("description") or "")
    pb = canonical_place(b.get("location") or "", b.get("description") or "")
    return bool(pa and pb and pa == pb)


def duplicate_decision(a: dict, b: dict) -> tuple[str, float, str]:
    # HOLD / POSSIBLE / NONE
    if clean_text(a.get("url")) and clean_text(a.get("url")) == clean_text(b.get("url")):
        return "HOLD", 1.0, "same_url"

    ga = clean_text(a.get("application_group_id"))
    gb = clean_text(b.get("application_group_id"))
    if ga and gb and ga == gb:
        return "HOLD", 1.0, "same_application_group_id"

    jac = jaccard_description(a, b)
    tsim = title_similarity(a, b)
    place = same_place(a, b)

    # Très proche même si les agrégateurs donnent des villes différentes.
    if jac >= DUP_JACCARD_STRONG and tsim >= 0.90:
        return "HOLD", round(jac, 3), "strong_live_text"

    if place and jac >= DUP_JACCARD_SAME_LOCATION and tsim >= DUP_TITLE_SAME_LOCATION:
        return "HOLD", round(jac, 3), "same_place_live_text"

    if place and jac >= 0.45 and tsim >= 0.70:
        return "POSSIBLE", round(jac, 3), "possible_same_place"

    return "NONE", round(max(jac, tsim), 3), ""


def origin_rank(item: dict) -> int:
    return {
        "READY_DOCUMENTS": 0,
        "RESCUED_APPLY": 1,
        "RECHECK_STRETCH": 2,
        "RESCUE_STRETCH": 3,
    }.get(item.get("pool_origin"), 9)


def choose_primary(a: dict, b: dict) -> tuple[dict, dict]:
    def key(x):
        return (
            origin_rank(x),
            int(x.get("queue_rank") or 999999),
            -float(x.get("final_score") or 0),
        )
    return (a, b) if key(a) <= key(b) else (b, a)


def deduplicate(items: list[dict]):
    removed = set()
    holds = []
    possibles = []

    for i, a in enumerate(items):
        if i in removed:
            continue
        for j in range(i + 1, len(items)):
            if j in removed:
                continue
            b = items[j]
            decision, sim, method = duplicate_decision(a, b)
            if decision == "NONE":
                continue

            if decision == "POSSIBLE":
                possibles.append({
                    "a_key": a.get("stable_item_key"),
                    "a_title": a.get("title"),
                    "a_company": a.get("company"),
                    "b_key": b.get("stable_item_key"),
                    "b_title": b.get("title"),
                    "b_company": b.get("company"),
                    "similarity": sim,
                    "method": method,
                })
                continue

            primary, secondary = choose_primary(a, b)
            secondary_index = i if secondary is a else j
            removed.add(secondary_index)
            holds.append({
                "duplicate_key": secondary.get("stable_item_key"),
                "duplicate_title": secondary.get("title"),
                "duplicate_company": secondary.get("company"),
                "duplicate_url": secondary.get("url"),
                "primary_key": primary.get("stable_item_key"),
                "primary_title": primary.get("title"),
                "primary_company": primary.get("company"),
                "primary_url": primary.get("url"),
                "similarity": sim,
                "method": method,
            })
            if secondary_index == i:
                break

    unique = [x for idx, x in enumerate(items) if idx not in removed]
    return unique, holds, possibles


# ---------------------------------------------------------------------------
# Reclassement
# ---------------------------------------------------------------------------

def recompute_item(item: dict) -> dict:
    x = dict(item)
    x["track"] = classify_track(x.get("title") or "", x.get("track") or x.get("cv_track") or "")
    x["preferred_location"] = preferred_location(x.get("location") or "")
    x["off_domain_title"] = off_domain_title(x.get("title") or "")

    guard = final_guard(x)
    x.update(guard)

    # ------------------------------------------------------------------
    # Le verdict lisible, branche comme garde-fou
    # ------------------------------------------------------------------
    # Le score dit « combien », le verdict dit « pourquoi ». Les deux
    # peuvent diverger, et c'est arrive : au 9 septembre 2026, cinq offres
    # classees FERMEE atteignaient APPLY_NOW. Quatre etaient en realite des
    # erreurs du verdict, corrigees depuis ; mais la divergence, elle, est
    # structurelle — rien n'empechait le score de recommander une offre dont
    # une barriere etait prouvee.
    #
    # La regle est volontairement douce. Une offre FERMEE n'est pas
    # supprimee : elle passe en relecture, avec la phrase de l'annonce qui
    # la ferme. Un juge qui vient de se tromper cinq fois ne merite pas le
    # droit d'ecarter seul, seulement celui de faire lever les yeux.
    verdict = evaluer_verdict(x.get("description") or "")
    x["verdict"] = verdict.verdict
    x["verdict_version"] = verdict.version
    x["verdict_formation"] = bool(verdict.formation)
    x["verdict_obstacle"] = (verdict.barrieres[0].message
                             if verdict.barrieres else "")
    x["verdict_preuve"] = (verdict.barrieres[0].preuve
                           if verdict.barrieres else "")

    base_score = float(x.get("final_score") or x.get("queue_score") or x.get("match_score") or 0)
    penalty = 0
    if guard["guard_level"] == "REVIEW":
        penalty = 22
    elif guard["guard_level"] == "VERIFY":
        penalty = 18
    elif guard["guard_level"] == "BLOCK":
        penalty = 45

    x["final_score_v11"] = round(base_score - penalty, 1)

    if x.get("pool_origin") in {"RECHECK_STRETCH", "RESCUE_STRETCH"}:
        x["recommended_action_v11"] = "REVIEW_FIRST"
    elif guard["guard_level"] == "BLOCK":
        x["recommended_action_v11"] = "DO_NOT_APPLY"
    elif guard["guard_level"] in {"REVIEW", "VERIFY"}:
        x["recommended_action_v11"] = "REVIEW_FIRST"
    else:
        old_action = x.get("recommended_action")
        x["recommended_action_v11"] = (
            old_action if old_action in {"APPLY_NOW", "APPLY_NEXT"} else "APPLY_NEXT"
        )

    # Aucune offre dont une barriere est prouvee ne reste dans un panier
    # « postuler ». Elle devient relisible, jamais invisible.
    if (verdict.verdict == FERMEE
            and x["recommended_action_v11"] in {"APPLY_NOW", "APPLY_NEXT"}):
        x["recommended_action_v11"] = "REVIEW_FIRST"
        x["verdict_gate"] = "RETROGRADE_PAR_VERDICT"
        # Liste recreee : dict(item) est une copie de surface, et modifier
        # celle d'origine ferait fuir l'effet hors de cette fonction.
        x["reasons"] = list(x.get("reasons") or []) + [
            f"Verdict FERMEE — {x['verdict_obstacle']}"
        ]

    score = x["final_score_v11"]
    action = x["recommended_action_v11"]

    if action == "DO_NOT_APPLY":
        x["priority_v11"] = "C"
    elif action == "REVIEW_FIRST":
        x["priority_v11"] = "B" if score >= 95 else "C"
    elif x.get("preferred_location") and score >= 110:
        x["priority_v11"] = "A+"
    elif score >= 105:
        x["priority_v11"] = "A"
    elif score >= 90:
        x["priority_v11"] = "B"
    else:
        x["priority_v11"] = "C"

    return x


def sort_pool(items: list[dict]) -> list[dict]:
    action_order = {
        "APPLY_NOW": 0,
        "APPLY_NEXT": 1,
        "REVIEW_FIRST": 2,
        "DO_NOT_APPLY": 3,
    }
    priority_order = {"A+": 0, "A": 1, "B": 2, "C": 3}
    return sorted(
        items,
        key=lambda x: (
            action_order.get(x.get("recommended_action_v11"), 9),
            priority_order.get(x.get("priority_v11"), 9),
            -float(x.get("final_score_v11") or 0),
            int(x.get("queue_rank") or 999999),
        ),
    )


def build_pool_v12() -> dict:
    recheck_path = latest_file("application_recheck_v1_*.json")
    refresh_path = latest_file("job_refresh_v1_*.json")

    if not recheck_path:
        raise RuntimeError("Aucun application_recheck_v1_*.json trouvé.")
    if not refresh_path:
        raise RuntimeError("Aucun job_refresh_v1_*.json trouvé.")

    recheck = load_json(recheck_path)
    refresh = load_json(refresh_path)

    if not isinstance(recheck, list) or not isinstance(refresh, list):
        raise RuntimeError("Recheck/Refresh JSON invalide : listes attendues.")

    recheck_version = validate_recheck_versions(recheck)
    refresh_map = refresh_index(refresh)

    # Important : pas de Recall Rescue historique non rafraîchi.
    # Seules les offres ayant subi le Job Refresh live + Recheck courant entrent ici.
    base_items = build_from_current_recheck(recheck, refresh_map)

    guarded = [recompute_item(item) for item in base_items]
    unique, duplicates, possible_duplicates = deduplicate(guarded)
    final = sort_pool(unique)

    for rank, item in enumerate(final, 1):
        item["pool_rank_v12"] = rank
        # Aliases explicites de la version finale.
        item["final_score_v12"] = item.get("final_score_v11")
        item["recommended_action_v12"] = item.get("recommended_action_v11")
        item["priority_v12"] = item.get("priority_v11")

    counts = Counter()
    for item in final:
        counts["total"] += 1
        counts[item.get("recommended_action_v12")] += 1
        counts[item.get("priority_v12")] += 1
        counts["TRACK_" + clean_text(item.get("track"))] += 1
        counts["GUARD_" + clean_text(item.get("guard_level"))] += 1
        counts["SOURCE_" + clean_text(item.get("source")).upper()] += 1
        if item.get("preferred_location"):
            counts["preferred_location"] += 1

    return {
        "pool_version": FINAL_POOL_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "inputs": {
            "recheck_json": str(recheck_path),
            "recheck_version": recheck_version,
            "refresh_json": str(refresh_path),
            "recall_rescue_policy": "EXCLUDED_UNLESS_REFETCHED_AND_RECHECKED",
        },
        "summary": dict(counts),
        "duplicates_removed_count": len(duplicates),
        "duplicates_removed": duplicates,
        "possible_duplicates_count": len(possible_duplicates),
        "possible_duplicates": possible_duplicates,
        "pool": final,
    }


CSV_FIELDS = [
    "pool_rank_v12", "priority_v12", "recommended_action_v12",
    "verdict", "verdict_obstacle",
    "guard_level", "guard_flags", "track", "preferred_location",
    "final_score_v11", "final_score", "queue_rank", "queue_score", "match_score",
    "pool_origin", "title", "company", "location", "source",
    "stable_item_key", "url",
]


def export_pool(payload: dict):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt_path = LOG_DIR / f"final_application_pool_v12_{stamp}.txt"
    json_path = LOG_DIR / f"final_application_pool_v12_{stamp}.json"
    csv_path = LOG_DIR / f"final_application_pool_v12_{stamp}.csv"

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for item in payload["pool"]:
            row = dict(item)
            row["guard_flags"] = " | ".join(item.get("guard_flags") or [])
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})

    s = payload["summary"]
    lines = [
        "FINAL APPLICATION POOL V1.2",
        "=" * 100,
        f"Total unique              : {s.get('total', 0)}",
        f"Doublons retirés          : {payload.get('duplicates_removed_count', 0)}",
        f"Doublons possibles        : {payload.get('possible_duplicates_count', 0)}",
        "",
        f"APPLY_NOW                 : {s.get('APPLY_NOW', 0)}",
        f"APPLY_NEXT                : {s.get('APPLY_NEXT', 0)}",
        f"REVIEW_FIRST              : {s.get('REVIEW_FIRST', 0)}",
        f"DO_NOT_APPLY              : {s.get('DO_NOT_APPLY', 0)}",
        "",
        f"A+                        : {s.get('A+', 0)}",
        f"A                         : {s.get('A', 0)}",
        f"B                         : {s.get('B', 0)}",
        f"C                         : {s.get('C', 0)}",
        "",
        "POOL FINAL V1.2",
        "-" * 100,
    ]

    for item in payload["pool"][:MAX_TXT_ITEMS]:
        star = "⭐" if item.get("preferred_location") else " "
        lines.extend([
            f"{int(item.get('pool_rank_v12') or 0):>3}. {star} "
            f"{item.get('priority_v12'):<2} | {item.get('recommended_action_v12'):<12} | "
            f"{item.get('track'):<18} | F{float(item.get('final_score_v12') or 0):>5.1f}",
            f"     {item.get('title')}",
            f"     {item.get('company')} | {item.get('location')}",
        ])
        for flag in item.get("guard_flags") or []:
            lines.append(f"     ⚠ {flag}")
        lines.append(f"     {item.get('url')}")
        lines.append("")

    if payload.get("duplicates_removed"):
        lines.extend(["", "DOUBLONS RETIRÉS", "-" * 100])
        for d in payload["duplicates_removed"]:
            lines.extend([
                f"- {d.get('duplicate_title')} | {d.get('duplicate_company')}",
                f"  -> {d.get('primary_title')} | {d.get('primary_company')}",
                f"  similarité={d.get('similarity')} via {d.get('method')}",
            ])

    if payload.get("possible_duplicates"):
        lines.extend(["", "DOUBLONS POSSIBLES À NE PAS AUTO-FUSIONNER", "-" * 100])
        for d in payload["possible_duplicates"]:
            lines.extend([
                f"- {d.get('a_title')} | {d.get('a_company')}",
                f"  <> {d.get('b_title')} | {d.get('b_company')}",
                f"  similarité={d.get('similarity')} via {d.get('method')}",
            ])

    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return txt_path, json_path, csv_path


def main():
    payload = build_pool_v12()
    txt, js, csvp = export_pool(payload)
    s = payload["summary"]

    print()
    print("=" * 100)
    print("FINAL APPLICATION POOL V1.2")
    print("=" * 100)
    print("Unique          :", s.get("total", 0))
    print("Doublons retirés:", payload.get("duplicates_removed_count", 0))
    print("APPLY_NOW       :", s.get("APPLY_NOW", 0))
    print("APPLY_NEXT      :", s.get("APPLY_NEXT", 0))
    print("REVIEW_FIRST    :", s.get("REVIEW_FIRST", 0))
    print("DO_NOT_APPLY    :", s.get("DO_NOT_APPLY", 0))
    print()
    print("TXT  :", txt)
    print("JSON :", js)
    print("CSV  :", csvp)


if __name__ == "__main__":
    main()
