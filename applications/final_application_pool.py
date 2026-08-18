"""
JOB HUNTER BELGIUM
FINAL APPLICATION POOL - VERSION 1.1

Lit le dernier final_application_pool_v1_*.json et applique :
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

from config.final_pool import (
    FINAL_POOL_VERSION,
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
    return contains_any(location, PREFERRED_LOCATION_TERMS)


def classify_track(title: str, current_track: str = "") -> str:
    t = normalize(title)
    if clean_text(current_track).upper() == "DATA" or contains_any(t, DATA_TERMS):
        return "DATA"
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
# Garde-fou description live
# ---------------------------------------------------------------------------

def _high_language_requirement(description: str, language: str) -> bool:
    d = normalize(description)

    if language == "nl":
        patterns = [
            r"\bneerlandais\b.{0,40}\b(c1|c2)\b",
            r"\bnederlands\b.{0,40}\b(c1|c2)\b",
            r"\bzeer goed nederlands\b",
            r"\bvlot nederlands\b",
            r"\bvloeiend nederlands\b",
            r"\btweetalig\b.{0,25}\b(nl|nederlands|fr)\b",
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
        ]
    else:
        return False

    return any(re.search(p, d) for p in patterns)


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


def build_pool_v11() -> dict:
    source_path = latest_file("final_application_pool_v1_*.json")
    if not source_path:
        raise RuntimeError("Aucun final_application_pool_v1_*.json trouvé.")

    source = load_json(source_path)
    original_pool = source.get("pool") or []

    guarded = [recompute_item(x) for x in original_pool]
    unique, duplicates, possible_duplicates = deduplicate(guarded)
    final = sort_pool(unique)

    for rank, item in enumerate(final, 1):
        item["pool_rank_v11"] = rank

    counts = Counter()
    for item in final:
        counts["total"] += 1
        counts[item.get("recommended_action_v11")] += 1
        counts[item.get("priority_v11")] += 1
        counts["TRACK_" + clean_text(item.get("track"))] += 1
        counts["GUARD_" + clean_text(item.get("guard_level"))] += 1
        if item.get("preferred_location"):
            counts["preferred_location"] += 1

    return {
        "pool_version": FINAL_POOL_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_pool_json": str(source_path),
        "summary": dict(counts),
        "duplicates_removed_count": len(duplicates),
        "duplicates_removed": duplicates,
        "possible_duplicates_count": len(possible_duplicates),
        "possible_duplicates": possible_duplicates,
        "pool": final,
    }


CSV_FIELDS = [
    "pool_rank_v11", "priority_v11", "recommended_action_v11",
    "guard_level", "guard_flags", "track", "preferred_location",
    "final_score_v11", "final_score", "queue_rank", "queue_score", "match_score",
    "pool_origin", "title", "company", "location", "source",
    "stable_item_key", "url",
]


def export_pool(payload: dict):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt_path = LOG_DIR / f"final_application_pool_v11_{stamp}.txt"
    json_path = LOG_DIR / f"final_application_pool_v11_{stamp}.json"
    csv_path = LOG_DIR / f"final_application_pool_v11_{stamp}.csv"

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
        "FINAL APPLICATION POOL V1.1",
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
        "POOL FINAL V1.1",
        "-" * 100,
    ]

    for item in payload["pool"][:MAX_TXT_ITEMS]:
        star = "⭐" if item.get("preferred_location") else " "
        lines.extend([
            f"{int(item.get('pool_rank_v11') or 0):>3}. {star} "
            f"{item.get('priority_v11'):<2} | {item.get('recommended_action_v11'):<12} | "
            f"{item.get('track'):<18} | F{float(item.get('final_score_v11') or 0):>5.1f}",
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
    payload = build_pool_v11()
    txt, js, csvp = export_pool(payload)
    s = payload["summary"]

    print()
    print("=" * 100)
    print("FINAL APPLICATION POOL V1.1")
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
