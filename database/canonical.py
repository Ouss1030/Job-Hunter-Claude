"""
JOB HUNTER BELGIUM
CANONICAL DATABASE - VERSION 3.1.3

V3.1.3 (17/09/2026) — même algorithme, calcul paresseux de la description
--------------------------------------------------------------------------
Le run du 16/09/2026 (66 275 offres actives, 1,05 million de paires) a
passé 2 h 18 dans ce build : la similarité de description
(SequenceMatcher sur des textes jusqu'à 8 000 caractères) était calculée
pour chaque paire AVANT de vérifier si le titre, l'entreprise et le lieu
lui laissaient une chance. Désormais :

    intra  : la description n'est calculée que si titre >= 0.995,
             entreprise >= 0.90 et lieu >= 0.80 — en dessous, la paire
             est rejetée quelle que soit la description (evaluate_intra_pair
             rendait déjà None dans ce cas)
    cross  : la description n'est calculée que si la paire peut atteindre
             pair_score >= CROSS_REVIEW_PAIR_MIN avec D = 1 ; sinon elle ne
             peut être ni auto, ni review (exact_unique et evidence_enough
             impliquent pair_score >= 0.889), ni dépasser une paire qui
             le peut — D vaut alors 0 et la paire est inerte

Les paires témoins des sanity checks (août 2026) dont une offre a été
retirée sont désormais « sans objet » au lieu d'échouer.

Toutes les décisions, tous les scores persistés et tous les motifs sont
identiques à V3.1.2 : vérifié sur 6 000 paires réelles par
diagnostics/canonical_perf_shadow_v1.py (0 écart), passe 1 99 -> 19 min,
passe 2 55 -> 22 min. Seuils, formules et schéma inchangés.

Fixes par rapport à V3.1
-------------------------
1. Les noms de provinces (Hainaut, Brabant, Liège, Luxembourg, etc.)
   restent des informations de localisation utiles.
2. Une description ne peut servir de preuve forte que si elle contient
   au moins 250 caractères normalisés, exactement comme dans l'audit
   intra-source validé.
3. Compatibilité MAIN V10 : le résumé expose à nouveau la clé
   `candidate_pairs`, égale à `intra_candidate_pairs + cross_candidate_pairs`.
4. Les deux paires FOREM Data & Integration Architect qui avaient été
   fusionnées par V3.1 avec une preuve trop courte doivent rester séparées.

Pipeline
--------
raw_jobs actifs
    -> PASS 1 : déduplication intra-source ultra-stricte
    -> atoms
    -> PASS 2 : déduplication cross-source collision-aware
    -> canonical_jobs + canonical_job_sources

Aucune ligne raw_jobs n'est supprimée ou modifiée.

Lancement
---------
python -m database.canonical

Log
---
exports/logs/canonical_v313_YYYYMMDD_HHMMSS.txt
"""

import hashlib
import json
import re
import sys
import unicodedata
import uuid
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from database.db import DB_PATH, get_connection, get_raw_jobs_for_dedup, init_db


SCHEMA_VERSION = "3.1.3"
ALGORITHM_VERSION = "STRICT_CANONICAL_V3_1_3"

# Critères validés par l'audit intra-source.
MIN_DESCRIPTION_CHARS = 250
MAX_DESCRIPTION_CHARS = 8000

INTRA_TITLE_MIN = 0.995
INTRA_COMPANY_MIN = 0.97
INTRA_LOCATION_MIN = 0.95
INTRA_DESCRIPTION_AUTO_MIN = 0.995
INTRA_STRONG_DESCRIPTION_MIN = 0.88
INTRA_REVIEW_COMPANY_MIN = 0.90
INTRA_REVIEW_LOCATION_MIN = 0.80

CROSS_TITLE_MIN = 0.96
CROSS_COMPANY_MIN = 0.88
CROSS_LOCATION_MIN = 0.88
CROSS_DESCRIPTION_MIN = 0.72
CROSS_EXACT_TITLE_MIN = 0.985
CROSS_EXACT_COMPANY_MIN = 0.95
CROSS_EXACT_LOCATION_MIN = 0.95
CROSS_REVIEW_TITLE_MIN = 0.90
CROSS_REVIEW_PAIR_MIN = 0.63

MAX_GROUPS_PRINT = 50
MAX_REVIEWS_PRINT = 60

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# LOG
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


def start_logging():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = LOG_DIR / f"canonical_v313_{timestamp}.txt"
    file = path.open("w", encoding="utf-8")
    stdout = sys.stdout
    stderr = sys.stderr
    sys.stdout = Tee(stdout, file)
    sys.stderr = Tee(stderr, file)
    return {"path": path, "file": file, "stdout": stdout, "stderr": stderr}


def stop_logging(logger):
    sys.stdout = logger["stdout"]
    sys.stderr = logger["stderr"]
    try:
        logger["file"].close()
    except Exception:
        pass


# ============================================================
# NORMALISATION
# ============================================================

def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def remove_accents(value):
    normalized = unicodedata.normalize("NFKD", clean_text(value))
    return "".join(c for c in normalized if not unicodedata.combining(c))


def normalize_basic(value):
    value = remove_accents(value).lower().replace("’", "'").replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def to_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


TITLE_STOPWORDS = {
    "de", "du", "des", "la", "le", "les", "un", "une", "et", "en",
    "pour", "aux", "the", "of", "and", "for", "in", "van", "het",
    "een", "voor",
}


def normalize_title(value):
    text = normalize_basic(value)
    for pattern in (
        r"\bh\s*f\s*x\b",
        r"\bm\s*f\s*x\b",
        r"\bm\s*v\s*x\b",
        r"\bhfx\b",
        r"\bmfx\b",
        r"\bmvx\b",
    ):
        text = re.sub(pattern, " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_variants(value):
    raw = clean_text(value)
    variants = set()
    normalized = normalize_title(raw)
    if normalized:
        variants.add(normalized)

    # "Data Engineer Health Sector, Smals" -> sans suffixe société.
    if "," in raw:
        before, after = raw.rsplit(",", 1)
        if len(normalize_basic(before).split()) >= 2 and 1 <= len(normalize_basic(after).split()) <= 3:
            candidate = normalize_title(before)
            if candidate:
                variants.add(candidate)

    # "SMALS - BI Developer" -> "BI Developer".
    parts = re.split(r"\s[-–—:]\s", raw, maxsplit=1)
    if len(parts) == 2:
        if 1 <= len(normalize_basic(parts[0]).split()) <= 3 and len(normalize_basic(parts[1]).split()) >= 2:
            candidate = normalize_title(parts[1])
            if candidate:
                variants.add(candidate)

    return variants


def title_fingerprint(value):
    tokens = [
        token for token in normalize_title(value).split()
        if len(token) >= 2 and token not in TITLE_STOPWORDS
    ]
    return " ".join(sorted(set(tokens))) if tokens else ""


COMPANY_NOISE = {
    "sa", "nv", "bv", "bvba", "sprl", "srl", "asbl", "vzw",
    "belgium", "belgie", "belgique", "recruitment", "recrutement", "interim",
}


def normalize_company(value):
    return " ".join(
        token for token in normalize_basic(value).split()
        if token not in COMPANY_NOISE
    )


# IMPORTANT V3.1.1 : uniquement des mots génériques.
# Les noms propres de provinces restent présents : Hainaut, Brabant, Liège,
# Luxembourg, etc. Cela corrige le faux L=0 du Quality Coordinator.
LOCATION_NOISE = {
    "belgique", "belgium", "belgie",
    "province", "region", "regionale",
    "wallonne", "wallon", "wallonie",
    "flamande", "flamand", "vlaanderen",
    "orientale", "occidentale",
    "du", "de", "la", "le",
}


def extract_postal_code(value):
    match = re.search(r"\b(\d{4})\b", clean_text(value))
    return match.group(1) if match else ""


def location_tokens(value):
    return {
        token for token in normalize_basic(value).split()
        if token not in LOCATION_NOISE and not token.isdigit() and len(token) >= 3
    }


def location_key(job):
    if job["_postal"]:
        return "POSTAL:" + job["_postal"]
    tokens = sorted(job["_location_tokens"])
    if tokens:
        return "TOKENS:" + "|".join(tokens)
    return "UNKNOWN"


def normalize_description(value):
    return normalize_basic(value)[:MAX_DESCRIPTION_CHARS]


def description_hash(value):
    if not value or len(value) < MIN_DESCRIPTION_CHARS:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ============================================================
# SIMILARITÉS
# ============================================================

def sequence_similarity(a, b):
    a = clean_text(a)
    b = clean_text(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def token_jaccard(a, b):
    set_a = set(clean_text(a).split())
    set_b = set(clean_text(b).split())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def containment_similarity(a, b):
    a = clean_text(a)
    b = clean_text(b)
    if len(a) < 4 or len(b) < 4:
        return 0.0
    if a in b or b in a:
        return 1.0
    set_a = set(a.split())
    set_b = set(b.split())
    if not set_a or not set_b:
        return 0.0
    smaller, larger = (set_a, set_b) if len(set_a) <= len(set_b) else (set_b, set_a)
    return len(smaller & larger) / len(smaller)


def title_similarity(job_a, job_b):
    best = 0.0
    for title_a in job_a["_title_variants"]:
        for title_b in job_b["_title_variants"]:
            seq = sequence_similarity(title_a, title_b)
            jac = token_jaccard(title_a, title_b)
            cont = containment_similarity(title_a, title_b)
            best = max(best, seq, seq * 0.65 + jac * 0.35, cont)
    return min(best, 1.0)


def company_similarity(job_a, job_b):
    a = job_a["_company_norm"]
    b = job_b["_company_norm"]
    if not a or not b:
        return 0.0
    seq = sequence_similarity(a, b)
    jac = token_jaccard(a, b)
    cont = containment_similarity(a, b)
    return min(max(seq, seq * 0.60 + jac * 0.40, cont), 1.0)


def location_similarity(job_a, job_b):
    postal_a = job_a["_postal"]
    postal_b = job_b["_postal"]
    tokens_a = job_a["_location_tokens"]
    tokens_b = job_b["_location_tokens"]

    if postal_a and postal_b:
        return 1.0 if postal_a == postal_b else 0.0

    if tokens_a and tokens_b:
        intersection = tokens_a & tokens_b
        if not intersection:
            return 0.0
        if tokens_a <= tokens_b or tokens_b <= tokens_a:
            return 0.98
        overlap = len(intersection) / len(tokens_a | tokens_b)
        if overlap >= 0.50:
            return 0.90
        return 0.60

    # Deux localisations identiques ne doivent jamais devenir 0 uniquement
    # parce que la normalisation a retiré tous les mots génériques.
    raw_a = normalize_basic(job_a.get("location"))
    raw_b = normalize_basic(job_b.get("location"))
    if raw_a and raw_b and raw_a == raw_b:
        return 0.98

    if not clean_text(job_a.get("location")) or not clean_text(job_b.get("location")):
        return 0.40
    return 0.0


def description_similarity(job_a, job_b):
    a = job_a["_description_norm"]
    b = job_b["_description_norm"]

    # Critère identique à l'audit validé : 250 caractères minimum.
    if len(a) < MIN_DESCRIPTION_CHARS or len(b) < MIN_DESCRIPTION_CHARS:
        return 0.0

    seq = sequence_similarity(a, b)
    jac = token_jaccard(a, b)
    return min(max(seq, seq * 0.60 + jac * 0.40), 1.0)


# ============================================================
# PRÉPARATION RAW
# ============================================================

def prepare_jobs(raw_jobs):
    output = []
    for raw_job in raw_jobs:
        job = dict(raw_job)
        variants = title_variants(job.get("title"))
        job["_title_variants"] = variants
        job["_title_norm"] = normalize_title(job.get("title"))
        job["_fingerprints"] = {
            title_fingerprint(v) for v in variants if title_fingerprint(v)
        }
        job["_company_norm"] = normalize_company(job.get("company"))
        job["_postal"] = extract_postal_code(job.get("location"))
        job["_location_tokens"] = location_tokens(job.get("location"))

        detail_text = clean_text(job.get("detail_matching_text"))
        description_source = detail_text if detail_text else job.get("description")
        job["_description_norm"] = normalize_description(description_source)
        job["_description_hash"] = description_hash(job["_description_norm"])
        output.append(job)
    return output


def _scores_partiels(job_a, job_b):
    """Titre, entreprise, lieu : les trois scores bon marché, avant toute description."""
    return (
        title_similarity(job_a, job_b),
        company_similarity(job_a, job_b),
        location_similarity(job_a, job_b),
    )


def _assembler_raw_pair(job_a, job_b, title_score, company_score, location_score, description_score):
    hash_a = job_a["_description_hash"]
    hash_b = job_b["_description_hash"]
    exact_description = bool(hash_a and hash_b and hash_a == hash_b)

    date_a = clean_text(job_a.get("date_published"))
    date_b = clean_text(job_b.get("date_published"))
    same_publication_date = bool(date_a and date_a == date_b)

    pair_score = (
        title_score * 0.44
        + company_score * 0.30
        + location_score * 0.18
        + description_score * 0.08
    )

    return {
        "raw_job_id_a": int(job_a["id"]),
        "raw_job_id_b": int(job_b["id"]),
        "title_score": round(title_score, 6),
        "company_score": round(company_score, 6),
        "location_score": round(location_score, 6),
        "description_score": round(description_score, 6),
        "pair_score": round(pair_score, 6),
        "exact_description": exact_description,
        "same_publication_date": same_publication_date,
    }


# ============================================================
# PASS 1 : INTRA-SOURCE
# ============================================================

def calculate_raw_pair(job_a, job_b):
    title_score, company_score, location_score = _scores_partiels(job_a, job_b)
    description_score = description_similarity(job_a, job_b)
    return _assembler_raw_pair(job_a, job_b, title_score, company_score, location_score, description_score)


def build_intra_candidate_pairs(jobs):
    buckets = defaultdict(list)
    for index, job in enumerate(jobs):
        channel = clean_text(job.get("collection_channel")).upper()
        title = job["_title_norm"]
        if len(title) >= 5:
            buckets[(channel, title)].append(index)

    pairs = set()
    for indexes in buckets.values():
        for i in range(len(indexes)):
            for j in range(i + 1, len(indexes)):
                a, b = indexes[i], indexes[j]
                pairs.add((min(a, b), max(a, b)))
    return pairs


def evaluate_intra_pair(job_a, job_b):
    title_score, company_score, location_score = _scores_partiels(job_a, job_b)
    if title_score < INTRA_TITLE_MIN:
        return None
    if company_score < INTRA_REVIEW_COMPANY_MIN or location_score < INTRA_REVIEW_LOCATION_MIN:
        # Ni auto, ni strong, ni review : la description ne changerait rien (V3.1.3).
        return None
    result = _assembler_raw_pair(job_a, job_b, title_score, company_score, location_score,
                                 description_similarity(job_a, job_b))

    auto_merge = (
        result["title_score"] >= INTRA_TITLE_MIN
        and result["company_score"] >= INTRA_COMPANY_MIN
        and result["location_score"] >= INTRA_LOCATION_MIN
        and result["same_publication_date"]
        and (
            result["exact_description"]
            or result["description_score"] >= INTRA_DESCRIPTION_AUTO_MIN
        )
    )

    strong = (
        not auto_merge
        and result["company_score"] >= INTRA_COMPANY_MIN
        and result["location_score"] >= INTRA_LOCATION_MIN
        and result["description_score"] >= INTRA_STRONG_DESCRIPTION_MIN
    )

    review = (
        not auto_merge
        and not strong
        and result["company_score"] >= INTRA_REVIEW_COMPANY_MIN
        and result["location_score"] >= INTRA_REVIEW_LOCATION_MIN
    )

    if not auto_merge and not strong and not review:
        return None

    if auto_merge:
        level = "AUTO_INTRA_STRICT"
    elif strong:
        level = "STRONG_REVIEW"
    else:
        level = "REVIEW"

    reason = (
        f"{level}; D={result['description_score']:.3f}; "
        + ("même date" if result["same_publication_date"] else "date différente/inconnue")
    )

    result.update({
        "scope": "INTRA",
        "auto_merge": auto_merge,
        "strong": strong,
        "review": review,
        "reason": reason,
    })
    return result


class RawUnionFind:
    def __init__(self, jobs):
        self.parent = {int(job["id"]): int(job["id"]) for job in jobs}
        self.rank = {int(job["id"]): 0 for job in jobs}

    def find(self, raw_id):
        if self.parent[raw_id] != raw_id:
            self.parent[raw_id] = self.find(self.parent[raw_id])
        return self.parent[raw_id]

    def union(self, a, b):
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a == root_b:
            return False
        if self.rank[root_a] < self.rank[root_b]:
            root_a, root_b = root_b, root_a
        self.parent[root_b] = root_a
        if self.rank[root_a] == self.rank[root_b]:
            self.rank[root_a] += 1
        return True


def build_intra_atoms(jobs, intra_results):
    uf = RawUnionFind(jobs)
    auto_edges = [r for r in intra_results if r["auto_merge"]]
    auto_edges.sort(
        key=lambda e: (e["exact_description"], e["description_score"], e["pair_score"]),
        reverse=True,
    )

    accepted = []
    for edge in auto_edges:
        if uf.union(edge["raw_job_id_a"], edge["raw_job_id_b"]):
            accepted.append(edge)

    groups = defaultdict(list)
    for job in jobs:
        groups[uf.find(int(job["id"]))].append(job)

    atoms = []
    for atom_id, members in enumerate(groups.values(), start=1):
        channels = {clean_text(m.get("collection_channel")).upper() for m in members}
        if len(channels) != 1:
            raise RuntimeError("Atom intra-source invalide : plusieurs canaux.")
        variants = set()
        fingerprints = set()
        for member in members:
            variants |= member["_title_variants"]
            fingerprints |= member["_fingerprints"]
        atoms.append({
            "atom_id": atom_id,
            "channel": next(iter(channels)),
            "members": members,
            "title_variants": variants,
            "fingerprints": fingerprints,
        })

    return atoms, accepted


# ============================================================
# SOURCE / PRIMARY
# ============================================================

def source_authority(job):
    channel = clean_text(job.get("collection_channel")).upper()
    origin = clean_text(job.get("origin_source")).upper()
    if channel in {"FOREM", "TRAVAILLERPOUR", "TALENT_BRUSSELS"}:
        return 100
    if channel == "ACTIRIS":
        if origin == "ACTIRIS":
            return 98
        if origin == "VDAB_FOREM":
            return 82
        if origin == "PARTNER":
            return 72
        return 70
    return 60


def primary_score(job):
    score = float(source_authority(job))
    if int(job.get("detail_enrichment_success") or 0) == 1:
        score += 20
    score += min(10, len(clean_text(job.get("description"))) / 1000)
    if clean_text(job.get("company")):
        score += 2
    if clean_text(job.get("location")):
        score += 2
    return score


def choose_primary(group):
    return max(group, key=lambda job: (primary_score(job), -int(job["id"])))


def choose_atom_primary(atom):
    return choose_primary(atom["members"])


# ============================================================
# PASS 2 : CROSS-SOURCE COLLISION-AWARE
# ============================================================

def atom_signature(atom):
    primary = choose_atom_primary(atom)
    fingerprints = sorted(atom["fingerprints"])
    title_key = fingerprints[0] if fingerprints else primary["_title_norm"]
    return (title_key, primary["_company_norm"], location_key(primary))


def build_signature_counts(atoms):
    counts = defaultdict(int)
    for atom in atoms:
        counts[(atom["channel"], atom_signature(atom))] += 1
    return counts


def build_cross_candidate_pairs(atoms):
    title_buckets = defaultdict(list)
    fingerprint_buckets = defaultdict(list)
    by_id = {atom["atom_id"]: atom for atom in atoms}

    for atom in atoms:
        for title in atom["title_variants"]:
            if len(title) >= 5:
                title_buckets[title].append(atom["atom_id"])
        for fingerprint in atom["fingerprints"]:
            if len(fingerprint) >= 5:
                fingerprint_buckets[fingerprint].append(atom["atom_id"])

    pairs = set()

    def add_bucket(atom_ids):
        for i in range(len(atom_ids)):
            for j in range(i + 1, len(atom_ids)):
                a = by_id[atom_ids[i]]
                b = by_id[atom_ids[j]]
                if a["channel"] == b["channel"]:
                    continue
                pairs.add(tuple(sorted((a["atom_id"], b["atom_id"]))))

    for bucket in title_buckets.values():
        add_bucket(bucket)
    for bucket in fingerprint_buckets.values():
        add_bucket(bucket)
    return pairs


def best_raw_pair_between_atoms(atom_a, atom_b):
    candidates = []
    for job_a in atom_a["members"]:
        for job_b in atom_b["members"]:
            title_score, company_score, location_score = _scores_partiels(job_a, job_b)
            # Borne haute du pair_score avec D = 1 : en dessous du seuil review, la
            # paire est inerte quelle que soit sa description (V3.1.3).
            borne = title_score * 0.44 + company_score * 0.30 + location_score * 0.18 + 0.08
            description_score = description_similarity(job_a, job_b) if borne >= CROSS_REVIEW_PAIR_MIN else 0.0
            candidates.append(_assembler_raw_pair(job_a, job_b, title_score, company_score,
                                                  location_score, description_score))
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda r: (r["pair_score"], r["description_score"], r["title_score"]),
    )


def evaluate_cross_atoms(atom_a, atom_b, signature_counts):
    result = best_raw_pair_between_atoms(atom_a, atom_b)
    if result is None or result["title_score"] < 0.78:
        return None

    count_a = signature_counts[(atom_a["channel"], atom_signature(atom_a))]
    count_b = signature_counts[(atom_b["channel"], atom_signature(atom_b))]
    ambiguous = count_a > 1 or count_b > 1

    exact_unique = (
        not ambiguous
        and result["title_score"] >= CROSS_EXACT_TITLE_MIN
        and result["company_score"] >= CROSS_EXACT_COMPANY_MIN
        and result["location_score"] >= CROSS_EXACT_LOCATION_MIN
    )

    evidence_enough = (
        result["title_score"] >= CROSS_TITLE_MIN
        and result["company_score"] >= CROSS_COMPANY_MIN
        and result["location_score"] >= CROSS_LOCATION_MIN
        and result["description_score"] >= CROSS_DESCRIPTION_MIN
    )

    auto_merge = exact_unique or evidence_enough
    review = (
        not auto_merge
        and result["title_score"] >= CROSS_REVIEW_TITLE_MIN
        and result["pair_score"] >= CROSS_REVIEW_PAIR_MIN
    )

    reason_parts = [f"signature {'ambiguë' if ambiguous else 'unique'} ({count_a} vs {count_b})"]
    if exact_unique:
        reason_parts.append("cross exact unique")
    if evidence_enough:
        reason_parts.append("cross description forte")
    if ambiguous and not auto_merge:
        reason_parts.append(f"preuve description insuffisante D={result['description_score']:.3f}")

    result.update({
        "scope": "CROSS",
        "atom_id_a": atom_a["atom_id"],
        "atom_id_b": atom_b["atom_id"],
        "ambiguous_signature": ambiguous,
        "signature_count_a": count_a,
        "signature_count_b": count_b,
        "auto_merge": auto_merge,
        "strong": False,
        "review": review,
        "reason": "; ".join(reason_parts),
    })
    return result


class AtomUnionFind:
    def __init__(self, atoms):
        self.parent = {a["atom_id"]: a["atom_id"] for a in atoms}
        self.rank = {a["atom_id"]: 0 for a in atoms}
        self.channels = {a["atom_id"]: {a["channel"]} for a in atoms}

    def find(self, atom_id):
        if self.parent[atom_id] != atom_id:
            self.parent[atom_id] = self.find(self.parent[atom_id])
        return self.parent[atom_id]

    def can_union(self, a, b):
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a == root_b:
            return False
        return not (self.channels[root_a] & self.channels[root_b])

    def union(self, a, b):
        if not self.can_union(a, b):
            return False
        root_a = self.find(a)
        root_b = self.find(b)
        if self.rank[root_a] < self.rank[root_b]:
            root_a, root_b = root_b, root_a
        self.parent[root_b] = root_a
        self.channels[root_a] |= self.channels[root_b]
        if self.rank[root_a] == self.rank[root_b]:
            self.rank[root_a] += 1
        return True


def build_final_groups(atoms, cross_results):
    uf = AtomUnionFind(atoms)
    auto_edges = [r for r in cross_results if r["auto_merge"]]
    auto_edges.sort(
        key=lambda e: (e["description_score"], e["pair_score"], e["title_score"]),
        reverse=True,
    )

    accepted = []
    blocked = []
    for edge in auto_edges:
        if uf.union(edge["atom_id_a"], edge["atom_id_b"]):
            accepted.append(edge)
        else:
            blocked.append(edge)

    atom_by_id = {a["atom_id"]: a for a in atoms}
    grouped_atoms = defaultdict(list)
    for atom in atoms:
        grouped_atoms[uf.find(atom["atom_id"])].append(atom["atom_id"])

    groups = []
    for atom_ids in grouped_atoms.values():
        members = []
        for atom_id in atom_ids:
            members.extend(atom_by_id[atom_id]["members"])
        groups.append(members)

    return groups, accepted, blocked


# ============================================================
# SQLITE CANONICAL
# ============================================================

def init_canonical_schema():
    init_db()
    connection = get_connection()
    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS canonical_builds (
                build_id TEXT PRIMARY KEY,
                schema_version TEXT NOT NULL,
                algorithm_version TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                raw_jobs_count INTEGER DEFAULT 0,
                candidate_pairs_count INTEGER DEFAULT 0,
                auto_edges_count INTEGER DEFAULT 0,
                auto_merge_groups_count INTEGER DEFAULT 0,
                canonical_jobs_count INTEGER DEFAULT 0,
                singleton_count INTEGER DEFAULT 0,
                merged_raw_jobs_count INTEGER DEFAULT 0,
                review_candidates_count INTEGER DEFAULT 0,
                notes TEXT
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS canonical_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                build_id TEXT NOT NULL,
                canonical_key TEXT NOT NULL,
                preferred_raw_job_id INTEGER NOT NULL,
                title TEXT,
                company TEXT,
                location TEXT,
                description TEXT,
                url TEXT,
                date_published TEXT,
                contract_type TEXT,
                language TEXT,
                salary TEXT,
                first_seen TEXT,
                last_seen TEXT,
                member_count INTEGER NOT NULL,
                source_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (build_id) REFERENCES canonical_builds(build_id) ON DELETE CASCADE,
                FOREIGN KEY (preferred_raw_job_id) REFERENCES raw_jobs(id),
                UNIQUE (build_id, canonical_key)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS canonical_job_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                build_id TEXT NOT NULL,
                canonical_job_id INTEGER NOT NULL,
                raw_job_id INTEGER NOT NULL,
                collection_channel TEXT NOT NULL,
                origin_source TEXT,
                source_external_id TEXT NOT NULL,
                is_primary INTEGER NOT NULL DEFAULT 0,
                link_method TEXT NOT NULL,
                link_score REAL,
                evidence_json TEXT,
                linked_at TEXT NOT NULL,
                FOREIGN KEY (build_id) REFERENCES canonical_builds(build_id) ON DELETE CASCADE,
                FOREIGN KEY (canonical_job_id) REFERENCES canonical_jobs(id) ON DELETE CASCADE,
                FOREIGN KEY (raw_job_id) REFERENCES raw_jobs(id),
                UNIQUE (build_id, raw_job_id)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS dedup_review_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                build_id TEXT NOT NULL,
                raw_job_id_a INTEGER NOT NULL,
                raw_job_id_b INTEGER NOT NULL,
                pair_score REAL NOT NULL,
                title_score REAL NOT NULL,
                company_score REAL NOT NULL,
                location_score REAL NOT NULL,
                description_score REAL NOT NULL,
                reason TEXT,
                decision TEXT NOT NULL DEFAULT 'REVIEW',
                evidence_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (build_id) REFERENCES canonical_builds(build_id) ON DELETE CASCADE,
                FOREIGN KEY (raw_job_id_a) REFERENCES raw_jobs(id),
                FOREIGN KEY (raw_job_id_b) REFERENCES raw_jobs(id),
                UNIQUE (build_id, raw_job_id_a, raw_job_id_b)
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_canonical_jobs_build ON canonical_jobs(build_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_canonical_sources_build ON canonical_job_sources(build_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_canonical_sources_job ON canonical_job_sources(canonical_job_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_canonical_sources_raw ON canonical_job_sources(raw_job_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_dedup_review_build ON dedup_review_candidates(build_id)")
        connection.commit()
    finally:
        connection.close()


def generate_build_id():
    return f"CANON311_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def make_canonical_key(group):
    identities = [
        f"{clean_text(job.get('collection_channel'))}:{clean_text(job.get('source_external_id'))}"
        for job in group
    ]
    digest = hashlib.sha1("|".join(sorted(identities)).encode("utf-8")).hexdigest()[:20]
    return f"CAN_{digest}"


def deduplicate_reviews(reviews):
    output = {}
    for candidate in reviews:
        key = tuple(sorted((candidate["raw_job_id_a"], candidate["raw_job_id_b"])))
        previous = output.get(key)
        if previous is None or candidate["pair_score"] > previous["pair_score"]:
            output[key] = candidate
    result = list(output.values())
    result.sort(key=lambda r: (r["pair_score"], r["description_score"]), reverse=True)
    return result


def make_raw_to_atom(atoms):
    return {
        int(member["id"]): atom["atom_id"]
        for atom in atoms
        for member in atom["members"]
    }


def persist_build(
    build_id,
    jobs,
    atoms,
    intra_pair_count,
    cross_pair_count,
    groups,
    accepted_intra,
    accepted_cross,
    reviews,
):
    connection = get_connection()
    raw_to_atom = make_raw_to_atom(atoms)
    atom_by_id = {a["atom_id"]: a for a in atoms}

    try:
        connection.execute("""
            INSERT INTO canonical_builds (
                build_id, schema_version, algorithm_version, started_at, status,
                raw_jobs_count, candidate_pairs_count, auto_edges_count, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            build_id,
            SCHEMA_VERSION,
            ALGORITHM_VERSION,
            now_iso(),
            "RUNNING",
            len(jobs),
            intra_pair_count + cross_pair_count,
            len(accepted_intra) + len(accepted_cross),
            "V3.1.1: 250-char evidence + province-safe location + collision-aware cross.",
        ))

        merged_groups = 0
        singleton_count = 0
        merged_raw_jobs = 0

        for group in groups:
            if len(group) == 1:
                singleton_count += 1
            else:
                merged_groups += 1
                merged_raw_jobs += len(group)

            primary = choose_primary(group)
            primary_id = int(primary["id"])
            canonical_key = make_canonical_key(group)
            source_count = len({clean_text(j.get("collection_channel")).upper() for j in group})

            first_seen_values = [clean_text(j.get("first_seen")) for j in group if clean_text(j.get("first_seen"))]
            last_seen_values = [clean_text(j.get("last_seen")) for j in group if clean_text(j.get("last_seen"))]

            cursor = connection.execute("""
                INSERT INTO canonical_jobs (
                    build_id, canonical_key, preferred_raw_job_id,
                    title, company, location, description, url, date_published,
                    contract_type, language, salary, first_seen, last_seen,
                    member_count, source_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                build_id,
                canonical_key,
                primary_id,
                clean_text(primary.get("title")),
                clean_text(primary.get("company")),
                clean_text(primary.get("location")),
                clean_text(primary.get("description")),
                clean_text(primary.get("url")),
                clean_text(primary.get("date_published")),
                clean_text(primary.get("contract_type")),
                clean_text(primary.get("language")),
                clean_text(primary.get("salary")),
                min(first_seen_values) if first_seen_values else None,
                max(last_seen_values) if last_seen_values else None,
                len(group),
                source_count,
                now_iso(),
            ))
            canonical_job_id = cursor.lastrowid

            group_atom_ids = {raw_to_atom[int(j["id"])] for j in group}
            atom_primary_ids = {
                atom_id: int(choose_atom_primary(atom_by_id[atom_id])["id"])
                for atom_id in group_atom_ids
            }

            for member in group:
                raw_id = int(member["id"])
                atom_id = raw_to_atom[raw_id]
                atom = atom_by_id[atom_id]
                is_primary = raw_id == primary_id

                if is_primary:
                    link_method = "PRIMARY"
                elif len(atom["members"]) > 1 and raw_id != atom_primary_ids[atom_id]:
                    link_method = "AUTO_INTRA_STRICT"
                elif len(group_atom_ids) > 1:
                    link_method = "AUTO_CROSS_STRICT"
                elif len(atom["members"]) > 1:
                    link_method = "AUTO_INTRA_STRICT"
                else:
                    link_method = "SINGLETON"

                connection.execute("""
                    INSERT INTO canonical_job_sources (
                        build_id, canonical_job_id, raw_job_id,
                        collection_channel, origin_source, source_external_id,
                        is_primary, link_method, link_score, evidence_json, linked_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    build_id,
                    canonical_job_id,
                    raw_id,
                    clean_text(member.get("collection_channel")),
                    clean_text(member.get("origin_source")),
                    clean_text(member.get("source_external_id")),
                    1 if is_primary else 0,
                    link_method,
                    1.0 if is_primary or link_method == "SINGLETON" else None,
                    to_json({"algorithm": ALGORITHM_VERSION, "link_method": link_method}),
                    now_iso(),
                ))

        for candidate in reviews:
            connection.execute("""
                INSERT INTO dedup_review_candidates (
                    build_id, raw_job_id_a, raw_job_id_b,
                    pair_score, title_score, company_score, location_score,
                    description_score, reason, decision, evidence_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                build_id,
                candidate["raw_job_id_a"],
                candidate["raw_job_id_b"],
                candidate["pair_score"],
                candidate["title_score"],
                candidate["company_score"],
                candidate["location_score"],
                candidate["description_score"],
                candidate.get("reason"),
                "STRONG_REVIEW" if candidate.get("strong") else "REVIEW",
                to_json(candidate),
                now_iso(),
            ))

        connection.execute("""
            UPDATE canonical_builds
            SET finished_at = ?, status = ?, auto_merge_groups_count = ?,
                canonical_jobs_count = ?, singleton_count = ?,
                merged_raw_jobs_count = ?, review_candidates_count = ?
            WHERE build_id = ?
        """, (
            now_iso(),
            "COMPLETED",
            merged_groups,
            len(groups),
            singleton_count,
            merged_raw_jobs,
            len(reviews),
            build_id,
        ))
        connection.commit()

        return {
            "build_id": build_id,
            "raw_jobs": len(jobs),
            "atoms": len(atoms),
            "candidate_pairs": intra_pair_count + cross_pair_count,
            "intra_candidate_pairs": intra_pair_count,
            "cross_candidate_pairs": cross_pair_count,
            "accepted_intra_edges": len(accepted_intra),
            "accepted_cross_edges": len(accepted_cross),
            "accepted_edges": len(accepted_intra) + len(accepted_cross),
            "merged_groups": merged_groups,
            "merged_raw_jobs": merged_raw_jobs,
            "singletons": singleton_count,
            "canonical_jobs": len(groups),
            "reviews": len(reviews),
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


# ============================================================
# BUILD PUBLIC - utilisé par MAIN V10
# ============================================================

def build_canonical():
    init_canonical_schema()
    jobs = prepare_jobs(get_raw_jobs_for_dedup(active_only=True))

    print("\n" + "=" * 80)
    print("PREPARATION V3.1.2")
    print("=" * 80)
    print("\nRAW actifs :", len(jobs))
    print("Longueur minimale description preuve :", MIN_DESCRIPTION_CHARS)

    # PASS 1
    intra_pairs = build_intra_candidate_pairs(jobs)
    intra_results = []
    for index_a, index_b in intra_pairs:
        result = evaluate_intra_pair(jobs[index_a], jobs[index_b])
        if result:
            intra_results.append(result)

    intra_auto = [r for r in intra_results if r["auto_merge"]]
    intra_strong = [r for r in intra_results if r.get("strong")]
    intra_review = [r for r in intra_results if r.get("review") or r.get("strong")]
    atoms, accepted_intra = build_intra_atoms(jobs, intra_results)

    print("\nPASS 1 - INTRA-SOURCE")
    print("Paires candidates :", len(intra_pairs))
    print("AUTO proposées    :", len(intra_auto))
    print("AUTO acceptées    :", len(accepted_intra))
    print("STRONG non auto   :", len(intra_strong))
    print("Atoms obtenus     :", len(atoms))

    print("\nAUTO INTRA ACCEPTÉES :")
    if not accepted_intra:
        print("  aucune")
    else:
        by_id = {int(job["id"]): job for job in jobs}
        for edge in accepted_intra:
            a = by_id[edge["raw_job_id_a"]]
            b = by_id[edge["raw_job_id_b"]]
            print(
                f"  {a.get('collection_channel')} | "
                f"{a.get('source_external_id')} + {b.get('source_external_id')} | "
                f"D={edge['description_score']:.3f} | "
                f"date={'OUI' if edge['same_publication_date'] else 'NON'} | "
                f"{a.get('title')}"
            )

    # PASS 2
    cross_pairs = build_cross_candidate_pairs(atoms)
    signature_counts = build_signature_counts(atoms)
    atom_by_id = {a["atom_id"]: a for a in atoms}

    cross_results = []
    for atom_id_a, atom_id_b in cross_pairs:
        result = evaluate_cross_atoms(
            atom_by_id[atom_id_a],
            atom_by_id[atom_id_b],
            signature_counts,
        )
        if result:
            cross_results.append(result)

    cross_auto = [r for r in cross_results if r["auto_merge"]]
    cross_review = [r for r in cross_results if r["review"]]
    groups, accepted_cross, blocked_cross = build_final_groups(atoms, cross_results)

    print("\nPASS 2 - CROSS-SOURCE")
    print("Paires candidates :", len(cross_pairs))
    print("AUTO proposées    :", len(cross_auto))
    print("AUTO acceptées    :", len(accepted_cross))
    print("AUTO bloquées     :", len(blocked_cross))
    print("REVIEW            :", len(cross_review))

    for edge in blocked_cross:
        candidate = dict(edge)
        candidate["auto_merge"] = False
        candidate["review"] = True
        candidate["reason"] = clean_text(candidate.get("reason")) + "; blocage same-channel atom"
        cross_review.append(candidate)

    reviews = deduplicate_reviews(intra_review + cross_review)
    build_id = generate_build_id()
    summary = persist_build(
        build_id,
        jobs,
        atoms,
        len(intra_pairs),
        len(cross_pairs),
        groups,
        accepted_intra,
        accepted_cross,
        reviews,
    )

    return {
        "summary": summary,
        "jobs": jobs,
        "atoms": atoms,
        "groups": groups,
        "intra_results": intra_results,
        "accepted_intra_edges": accepted_intra,
        "cross_results": cross_results,
        "accepted_cross_edges": accepted_cross,
        "reviews": reviews,
    }


# ============================================================
# QUERIES / REPORT
# ============================================================

def find_canonical_id(build_id, collection_channel, source_external_id):
    connection = get_connection()
    try:
        row = connection.execute("""
            SELECT canonical_job_id
            FROM canonical_job_sources
            WHERE build_id = ?
              AND collection_channel = ?
              AND source_external_id = ?
        """, (build_id, collection_channel, str(source_external_id))).fetchone()
        return int(row["canonical_job_id"]) if row else None
    finally:
        connection.close()


def print_summary(summary):
    print("\n" + "=" * 80)
    print("CANONICAL V3.1.2 - RESULTAT")
    print("=" * 80)
    print("\nBuild                     :", summary["build_id"])
    print("RAW                       :", summary["raw_jobs"])
    print("Atoms après intra         :", summary["atoms"])
    print("Paires INTRA              :", summary["intra_candidate_pairs"])
    print("Arêtes INTRA acceptées    :", summary["accepted_intra_edges"])
    print("Paires CROSS              :", summary["cross_candidate_pairs"])
    print("Arêtes CROSS acceptées    :", summary["accepted_cross_edges"])
    print("Groupes fusionnés         :", summary["merged_groups"])
    print("RAW groupes fusionnés     :", summary["merged_raw_jobs"])
    print("Singletons                :", summary["singletons"])
    print("Canonical jobs            :", summary["canonical_jobs"])
    print("Review candidates         :", summary["reviews"])
    print("\nDoublons RAW retirés      :", summary["raw_jobs"] - summary["canonical_jobs"])


def print_auto_groups(groups):
    merged = [group for group in groups if len(group) > 1]
    print("\n" + "=" * 80)
    print("GROUPES AUTO-FUSIONNES V3.1.2")
    print("=" * 80)
    if not merged:
        print("\nAucun groupe fusionné.")
        return

    for position, group in enumerate(merged[:MAX_GROUPS_PRINT], start=1):
        primary = choose_primary(group)
        channels = defaultdict(int)
        for member in group:
            channels[clean_text(member.get("collection_channel")).upper()] += 1
        print(
            f"\n[{position}] {make_canonical_key(group)} | "
            f"{len(group)} RAW | {dict(channels)}"
        )
        print(
            "    PRIMARY :",
            primary.get("collection_channel"), "|",
            primary.get("source_external_id"), "|",
            primary.get("title"),
        )
        for member in group:
            print(
                "    -",
                member.get("collection_channel"), "|",
                member.get("origin_source"), "|",
                member.get("source_external_id"), "|",
                member.get("company"), "|",
                member.get("location"),
            )


def print_reviews(jobs, reviews):
    by_id = {int(job["id"]): job for job in jobs}
    print("\n" + "=" * 80)
    print("TOP REVIEW CANDIDATES V3.1.1")
    print("=" * 80)
    if not reviews:
        print("\nAucun candidat manuel.")
        return

    for position, candidate in enumerate(reviews[:MAX_REVIEWS_PRINT], start=1):
        a = by_id.get(candidate["raw_job_id_a"])
        b = by_id.get(candidate["raw_job_id_b"])
        if not a or not b:
            continue
        print(
            f"\n[{position}] {candidate.get('scope', '?')} | "
            f"PAIR={candidate['pair_score']:.3f} | "
            f"T={candidate['title_score']:.3f} | "
            f"C={candidate['company_score']:.3f} | "
            f"L={candidate['location_score']:.3f} | "
            f"D={candidate['description_score']:.3f}"
        )
        print("    A :", a.get("collection_channel"), "|", a.get("source_external_id"), "|", a.get("title"))
        print("        ", a.get("company"), "|", a.get("location"))
        print("    B :", b.get("collection_channel"), "|", b.get("source_external_id"), "|", b.get("title"))
        print("        ", b.get("company"), "|", b.get("location"))
        print("    Motif :", candidate.get("reason"))


# ============================================================
# SANITY CHECKS
# ============================================================

def sanity_pair(build_id, label, channel_a, external_a, channel_b, external_b, expect_same):
    canonical_a = find_canonical_id(build_id, channel_a, external_a)
    canonical_b = find_canonical_id(build_id, channel_b, external_b)
    if canonical_a is None or canonical_b is None:
        # Les paires temoins datent d'aout 2026 ; une offre retiree (is_active = 0) n'entre
        # plus dans le build. Le controle est alors sans objet, ni reussi ni echoue (V3.1.3).
        print("\n⏭", label, "— offre retiree, contrôle sans objet")
        print(f"    {channel_a} {external_a} -> {canonical_a}")
        print(f"    {channel_b} {external_b} -> {canonical_b}")
        return None
    same = canonical_a == canonical_b
    valid = same if expect_same else not same
    print("\n" + ("✅" if valid else "❌"), label)
    print(f"    {channel_a} {external_a} -> {canonical_a}")
    print(f"    {channel_b} {external_b} -> {canonical_b}")
    print("    Attendu :", "MÊME CANONICAL" if expect_same else "CANONICALS DIFFÉRENTS")
    return valid


def run_sanity_checks(build_id):
    print("\n" + "=" * 80)
    print("SANITY CHECKS V3.1.2")
    print("=" * 80)

    checks = [
        sanity_pair(build_id, "DaJobs QC Drogenbos", "FOREM", "1980485", "ACTIRIS", "5905785", True),
        sanity_pair(build_id, "UNIQUE laboratoire localisations différentes", "FOREM", "2019144", "ACTIRIS", "5926946", False),
        sanity_pair(build_id, "Talentus HPLC Drogenbos vs Anderlecht", "FOREM", "1990802", "ACTIRIS", "5906598", False),
        sanity_pair(build_id, "FOREM Quality Coordinator description exacte", "FOREM", "2017946", "FOREM", "2017950", True),
        sanity_pair(build_id, "ACTIRIS Senior Data Analyst description identique", "ACTIRIS", "5911013", "ACTIRIS", "5911081", True),
        sanity_pair(build_id, "ACTIRIS BI Developer description quasi-identique", "ACTIRIS", "5892534", "ACTIRIS", "5892507", True),
        sanity_pair(build_id, "FOREM Animal Health Sales Director", "FOREM", "1994631", "FOREM", "1994627", True),
        sanity_pair(build_id, "Vivaldi contrôle qualité date différente", "ACTIRIS", "5918412", "ACTIRIS", "5906771", False),
        sanity_pair(build_id, "Adecco Kwaliteitscontroleur D=0.972 date différente", "FOREM", "2015031", "FOREM", "2012925", False),
        sanity_pair(build_id, "FOREM BI Developer deux contenus différents", "FOREM", "1970812", "FOREM", "1970811", False),
        sanity_pair(build_id, "FOREM Data Engineer Health Sector deux contenus différents", "FOREM", "1986887", "FOREM", "1986888", False),
        sanity_pair(build_id, "FOREM Data & Integration Architect 2009962/2009951 preuve insuffisante", "FOREM", "2009962", "FOREM", "2009951", False),
        sanity_pair(build_id, "FOREM Data & Integration Architect 1954635/1954633 preuve insuffisante", "FOREM", "1954635", "FOREM", "1954633", False),
    ]

    applicables = [c for c in checks if c is not None]
    print("\nSanity checks réussis :", sum(1 for result in applicables if result), "/", len(applicables),
          f"(sans objet : {len(checks) - len(applicables)})")
    return all(applicables)


def count_raw_jobs():
    connection = get_connection()
    try:
        row = connection.execute("SELECT COUNT(*) AS count FROM raw_jobs").fetchone()
        return int(row["count"])
    finally:
        connection.close()


# ============================================================
# MAIN STANDALONE
# ============================================================

def main():
    logger = start_logging()
    try:
        print("\n" + "=" * 80)
        print("       JOB HUNTER - CANONICAL DATABASE V3.1.3")
        print("=" * 80)
        print("\nSQLite    :", DB_PATH)
        print("Schema    :", SCHEMA_VERSION)
        print("Algorithm :", ALGORITHM_VERSION)
        print("TXT       :", logger["path"])

        raw_before = count_raw_jobs()
        result = build_canonical()
        summary = result["summary"]

        print_summary(summary)
        print_auto_groups(result["groups"])
        print_reviews(result["jobs"], result["reviews"])
        sanity_ok = run_sanity_checks(summary["build_id"])

        raw_after = count_raw_jobs()
        print("\n" + "=" * 80)
        print("RAW INTEGRITY")
        print("=" * 80)
        print("\nraw_jobs avant :", raw_before)
        print("raw_jobs après :", raw_after)
        raw_ok = raw_before == raw_after
        print("\n" + ("✅ RAW inchangé." if raw_ok else "❌ Nombre RAW modifié."))

        print("\n" + "=" * 80)
        print("VALIDATION V3.1.3")
        print("=" * 80)
        print()
        if raw_ok and sanity_ok:
            print("✅ DATABASE CANONICAL V3.1.3 VALIDÉE.")
            print("\nMAIN V10 peut ensuite être relancé sans modification.")
        else:
            print("⚠️ Ne pas relancer MAIN V10.")
            print("Inspecter ce TXT avant de poursuivre.")

        print("\nFichier résultat :")
        print(logger["path"])
    finally:
        path = logger["path"]
        stop_logging(logger)
        print("\nTXT généré automatiquement :")
        print(path)


if __name__ == "__main__":
    main()