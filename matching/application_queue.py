"""
JOB HUNTER BELGIUM
APPLICATION QUEUE - VERSION 1.1

Objectif
========
Transformer les décisions de l'Application Gate en une file d'action stable :

    READY_APPLY     = candidature prioritaire à préparer
    READY_STRETCH   = candidature audacieuse mais raisonnable
    VERIFY_FIRST    = condition à confirmer avant de préparer les documents
    HOLD_DUPLICATE  = probable double candidature ; conserver mais ne pas postuler deux fois
    EXCLUDED        = Gate REJECT ; conservé seulement pour traçabilité

Principes
=========
- La Queue ne modifie ni RAW, ni Canonical, ni le Matcher, ni le Gate.
- Les doublons détectés ici sont des doublons de CANDIDATURE, pas des doublons de données.
- Aucun canonical_job n'est fusionné ou supprimé.
- Les zones préférées du profil utilisateur reçoivent un boost de priorité.
- Le profil de CV de base est choisi automatiquement : DATA, LAB_QC ou HYBRID.
- Un identifiant stable par URL/source est généré pour préparer le futur suivi des candidatures.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from matching.verdict import evaluer as evaluer_verdict
from config.profile import PREFERRED_LOCATIONS


QUEUE_VERSION = "1.1"

QUEUE_STATUS_ORDER = {
    "READY_APPLY": 5,
    "READY_STRETCH": 4,
    "VERIFY_FIRST": 3,
    "HOLD_DUPLICATE": 2,
    "EXCLUDED": 1,
}

QUEUE_STATUS_LABELS = {
    "READY_APPLY": "🟢 READY_APPLY",
    "READY_STRETCH": "🟡 READY_STRETCH",
    "VERIFY_FIRST": "🟠 VERIFY_FIRST",
    "HOLD_DUPLICATE": "🟣 HOLD_DUPLICATE",
    "EXCLUDED": "⚫ EXCLUDED",
}

CV_TRACKS = {
    "DATA": "CV Data / BI",
    "LAB_QC": "CV Lab / QC",
    "HYBRID": "CV Hybride Data + Pharma/Qualité",
}

DATA_FAMILIES = {
    "data_analytics",
    "business_intelligence",
    "business_analysis",
    "data_engineering",
}

LAB_FAMILIES = {
    "chemistry_lab",
    "pharma_qc",
    "quality",
}

HYBRID_FAMILIES = {
    "hybrid_data_pharma",
}

# Boosts modestes : le Gate reste la base de la décision.
FAMILY_PRIORITY_BOOST = {
    "chemistry_lab": 4.0,
    "pharma_qc": 5.0,
    "quality": 3.0,
    "hybrid_data_pharma": 5.0,
    "data_analytics": 4.0,
    "business_intelligence": 3.0,
    "business_analysis": 1.0,
    "data_engineering": 0.0,
}

PREFERRED_LOCATION_BOOST = 12.0
APPLY_STATUS_BOOST = 8.0
STRETCH_STATUS_BOOST = 0.0
VERIFY_STATUS_PENALTY = 20.0


# ============================================================
# NORMALISATION
# ============================================================

def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize(value):
    text = clean_text(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'").replace("`", "'")
    text = re.sub(r"[^a-z0-9+#./' -]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def stable_hash(value, prefix="AQ"):
    digest = hashlib.sha1(clean_text(value).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


# ============================================================
# IDENTITÉ STABLE D'OFFRE
# ============================================================

def source_reference_from_url(url):
    url = clean_text(url)
    if not url:
        return ""

    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    query = parse_qs(parsed.query)

    if "leforem.be" in host:
        match = re.search(r"offre-detail/(\d+)", path)
        if match:
            return f"FOREM:{match.group(1)}"

    if "actiris.brussels" in host:
        ref = (query.get("reference") or [""])[0]
        offer_type = (query.get("type") or [""])[0]
        if ref:
            return f"ACTIRIS:{ref}:{offer_type or 'UNKNOWN'}"

    if "travaillerpour.be" in host:
        slug = path.rstrip("/").split("/")[-1]
        if slug:
            return f"TRAVAILLERPOUR:{slug}"

    return url


def stable_application_item_key(source, url, canonical_job_id=None):
    ref = source_reference_from_url(url)
    base = ref or f"{clean_text(source)}|{clean_text(url)}|{canonical_job_id or ''}"
    return stable_hash(base, prefix="ITEM")


# ============================================================
# LOCALISATION
# ============================================================

_PREFERRED_NORM = tuple(sorted({normalize(v) for v in PREFERRED_LOCATIONS if normalize(v)}, key=len, reverse=True))


def location_is_preferred(location):
    norm = normalize(location)
    if not norm:
        return False

    if any(term and term in norm for term in _PREFERRED_NORM):
        return True

    # Certaines sources ne donnent que le code postal (ex. "1060, Belgique").
    # Si Bruxelles fait partie des préférences, tout code postal / commune
    # bruxelloise doit être considéré comme zone prioritaire.
    if location_anchor(location) == "bruxelles-capitale":
        return any(
            pref in _PREFERRED_NORM
            for pref in ("bruxelles", "brussels", "brussel", "bruxelles-capitale")
        )

    return False


BRUSSELS_POSTCODES = {
    "1000", "1020", "1030", "1040", "1050", "1060", "1070",
    "1080", "1081", "1082", "1083", "1090", "1120", "1130",
    "1140", "1150", "1160", "1170", "1180", "1190", "1200", "1210",
}

BRUSSELS_MUNICIPALITIES = {
    "bruxelles", "brussel", "brussels",
    "laeken", "laken", "neder-over-heembeek", "haren",
    "schaerbeek", "schaarbeek", "etterbeek", "ixelles", "elsene",
    "saint-gilles", "sint-gillis", "anderlecht",
    "molenbeek-saint-jean", "sint-jans-molenbeek",
    "koekelberg", "berchem-sainte-agathe", "sint-agatha-berchem",
    "ganshoren", "jette", "evere",
    "woluwe-saint-pierre", "sint-pieters-woluwe",
    "auderghem", "oudergem",
    "watermael-boitsfort", "watermaal-bosvoorde",
    "uccle", "ukkel", "forest", "vorst",
    "woluwe-saint-lambert", "sint-lambrechts-woluwe",
    "saint-josse-ten-noode", "sint-joost-ten-node",
}

def location_anchor(location):
    """
    Ancre géographique conservative pour la détection de double candidature.

    V1.1 :
    - les 19 communes de Bruxelles + leurs codes postaux sont regroupées
      sous une même ancre "bruxelles-capitale" ;
    - ailleurs, on conserve le comportement V1.0 basé sur la ville.
    """
    raw = clean_text(location)
    if not raw:
        return ""

    norm_raw = normalize(raw)

    postcode_match = re.search(r"\b(\d{4})\b", raw)
    if postcode_match and postcode_match.group(1) in BRUSSELS_POSTCODES:
        return "bruxelles-capitale"

    first = raw.split(",", 1)[0]
    first = re.sub(r"\([^)]*\)", " ", first)
    first = re.sub(r"\b\d{4}\b", " ", first)
    anchor = normalize(first)

    if anchor in BRUSSELS_MUNICIPALITIES:
        return "bruxelles-capitale"

    # Certaines sources mettent "Bruxelles" plus loin dans le champ location.
    if any(
        token in norm_raw
        for token in [
            "region de bruxelles-capitale",
            "brussels hoofdstedelijk gewest",
            "brussels-capital region",
        ]
    ):
        return "bruxelles-capitale"

    return anchor


# ============================================================
# CV TRACK
# ============================================================

def choose_cv_track(family, title=""):
    family = clean_text(family)
    ntitle = normalize(title)

    # Cas explicitement hybrides.
    if family in HYBRID_FAMILIES:
        return "HYBRID"

    # Data + pharma/qualité/labo dans le titre : CV hybride.
    if family in DATA_FAMILIES and any(
        token in ntitle
        for token in ["pharma", "quality", "qualite", "qc", "lims", "laboratory", "laboratoire"]
    ):
        return "HYBRID"

    if family in DATA_FAMILIES:
        return "DATA"

    if family in LAB_FAMILIES:
        return "LAB_QC"

    return "HYBRID"


# ============================================================
# FINGERPRINT DE CANDIDATURE
# ============================================================

TITLE_NOISE = {
    "h", "f", "x", "m", "v", "hf", "fx", "mv", "mx",
    "job", "offre", "vacature",
}

COMPANY_NOISE = {
    "belgium", "belgie", "belgique", "nv", "sa", "bv", "sprl", "srl",
    "mvm", "hr", "jobs", "job", "interim", "personnel", "services",
}


def normalized_title_tokens(title):
    text = normalize(title)

    # Marqueurs genre / contrat / ponctuation de sources.
    text = re.sub(r"\b(?:h\s*/\s*f\s*/\s*x|m\s*/\s*v\s*/\s*x|m\s*/\s*f\s*/\s*x)\b", " ", text)
    text = re.sub(r"\b(?:cdi|cdd|vast contract|vaste job)\b", " ", text)
    text = re.sub(r"\b(?:numero de reference|reference)\b\s*[:#-]*\s*[a-z0-9-]+", " ", text)

    tokens = [
        token for token in re.findall(r"[a-z0-9+#]+", text)
        if token not in TITLE_NOISE and len(token) > 1
    ]
    return tokens


def normalized_company_tokens(company):
    tokens = [
        token for token in re.findall(r"[a-z0-9]+", normalize(company))
        if token not in COMPANY_NOISE and len(token) > 1
    ]

    # Déduplique en conservant l'ordre : "BETUNED - BETUNED" -> "betuned".
    seen = set()
    result = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            result.append(token)
    return result


def tokens_key(tokens):
    return " ".join(tokens)


def token_jaccard(a, b):
    sa = set(a)
    sb = set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def sequence_similarity(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def company_similarity(company_a, company_b):
    ta = normalized_company_tokens(company_a)
    tb = normalized_company_tokens(company_b)
    if not ta or not tb:
        return 0.0

    ja = token_jaccard(ta, tb)
    seq = sequence_similarity(tokens_key(ta), tokens_key(tb))
    return max(ja, seq)


def title_similarity(title_a, title_b):
    ta = normalized_title_tokens(title_a)
    tb = normalized_title_tokens(title_b)
    if not ta or not tb:
        return 0.0

    ja = token_jaccard(ta, tb)
    seq = sequence_similarity(tokens_key(ta), tokens_key(tb))
    return max(ja, seq)




def record_title_similarity(a, b):
    """
    Similarité de titre tenant compte d'un préfixe de marque/recruteur.
    Exemple réel : "Smals - BI Analyst - Developer" vs "BI Analyst-Developer".
    On ne retire les tokens d'entreprise que si les entreprises sont déjà
    fortement similaires.
    """
    base = title_similarity(a.get("title"), b.get("title"))
    c_sim = company_similarity(a.get("company"), b.get("company"))
    if c_sim < 0.86:
        return base

    company_tokens = set(normalized_company_tokens(a.get("company"))) | set(
        normalized_company_tokens(b.get("company"))
    )
    if not company_tokens:
        return base

    ta = [t for t in normalized_title_tokens(a.get("title")) if t not in company_tokens]
    tb = [t for t in normalized_title_tokens(b.get("title")) if t not in company_tokens]
    if not ta or not tb:
        return base

    adjusted = max(
        token_jaccard(ta, tb),
        sequence_similarity(tokens_key(ta), tokens_key(tb)),
    )
    return max(base, adjusted)


def same_location(a, b):
    la = location_anchor(a)
    lb = location_anchor(b)
    if not la or not lb:
        return False
    return la == lb or la in lb or lb in la


def strong_application_duplicate(a, b):
    """
    Filtre suffisamment strict pour METTRE EN ATTENTE une double candidature.
    On ne fusionne rien : le secondaire reste visible avec HOLD_DUPLICATE.
    """
    if not same_location(a.get("location"), b.get("location")):
        return False

    t_sim = record_title_similarity(a, b)
    c_sim = company_similarity(a.get("company"), b.get("company"))

    # Cas exact / quasi exact.
    if t_sim >= 0.94 and c_sim >= 0.86:
        return True

    # Même entreprise quasi certaine + titre extrêmement proche.
    if c_sim >= 0.97 and t_sim >= 0.90:
        return True

    return False


def possible_application_duplicate(a, b):
    if not same_location(a.get("location"), b.get("location")):
        return False

    t_sim = record_title_similarity(a, b)
    c_sim = company_similarity(a.get("company"), b.get("company"))
    return t_sim >= 0.78 and c_sim >= 0.70


# ============================================================
# PRIORITÉ
# ============================================================

def queue_score(record):
    gate = record.get("gate") or {}
    score = float(gate.get("priority_score", 0) or 0)
    status = clean_text(gate.get("status"))
    family = clean_text(record.get("best_family") or gate.get("family"))

    if status == "APPLY":
        score += APPLY_STATUS_BOOST
    elif status == "STRETCH":
        score += STRETCH_STATUS_BOOST
    elif status == "VERIFY":
        score -= VERIFY_STATUS_PENALTY

    if location_is_preferred(record.get("location")):
        score += PREFERRED_LOCATION_BOOST

    score += FAMILY_PRIORITY_BOOST.get(family, 0.0)
    return round(score, 1)


def initial_queue_status(gate_status):
    if gate_status == "APPLY":
        return "READY_APPLY"
    if gate_status == "STRETCH":
        return "READY_STRETCH"
    if gate_status == "VERIFY":
        return "VERIFY_FIRST"
    return "EXCLUDED"


# ============================================================
# CONSTRUCTION À PARTIR DE RECORDS NORMALISÉS
# ============================================================

def _prepare_record(record, source_rank):
    gate = dict(record.get("gate") or {})
    family = clean_text(record.get("best_family") or gate.get("family"))
    gate_status = clean_text(gate.get("status"))

    item = {
        "queue_version": QUEUE_VERSION,
        "source_rank": source_rank,
        "canonical_job_id": record.get("canonical_job_id"),
        "title": clean_text(record.get("title")),
        "company": clean_text(record.get("company")),
        "location": clean_text(record.get("location")),
        "url": clean_text(record.get("url")),
        "source": clean_text(record.get("source")),
        "origin_source": clean_text(record.get("origin_source")),
        "match_score": float(record.get("match_score", 0) or 0),
        "best_family": family,
        "gate": gate,
        "gate_status": gate_status,
        "queue_status": initial_queue_status(gate_status),
        "queue_status_label": QUEUE_STATUS_LABELS[initial_queue_status(gate_status)],
        "queue_score": 0.0,
        "preferred_location": location_is_preferred(record.get("location")),
        "location_anchor": location_anchor(record.get("location")),
        "cv_track": choose_cv_track(family, record.get("title")),
        "cv_track_label": CV_TRACKS[choose_cv_track(family, record.get("title"))],
        "stable_item_key": stable_application_item_key(
            record.get("source"),
            record.get("url"),
            record.get("canonical_job_id"),
        ),
        "application_group_id": None,
        "duplicate_of_item_key": None,
        "duplicate_confidence": None,
        "possible_duplicate_item_keys": [],
        # Verdict lisible, calcule en amont ou il y a encore du texte.
        #
        # L'element de file ne transporte pas la description : il ne peut
        # donc pas juger lui-meme. Quand l'appelant n'a rien fourni — cas
        # d'un rejeu depuis un JSON de gate — le champ reste vide, et un
        # champ vide ne ferme jamais rien.
        "verdict": clean_text(record.get("verdict")),
        "verdict_obstacle": clean_text(record.get("verdict_obstacle")),
    }
    item["queue_score"] = queue_score(item)
    return item


def _queue_sort_key(item):
    return (
        QUEUE_STATUS_ORDER.get(item.get("queue_status"), 0),
        float(item.get("queue_score", 0) or 0),
        float(item.get("match_score", 0) or 0),
        -int(item.get("source_rank", 999999) or 999999),
    )


def apply_application_duplicate_guard(items):
    """
    Cherche les doublons seulement parmi APPLY/STRETCH.
    Un item HOLD_DUPLICATE ne disparaît jamais du JSON.
    """
    candidates = [
        item for item in items
        if item.get("queue_status") in {"READY_APPLY", "READY_STRETCH"}
    ]

    # Les meilleurs items deviennent naturellement les représentants.
    candidates.sort(
        key=lambda x: (
            float(x.get("queue_score", 0) or 0),
            float(x.get("match_score", 0) or 0),
            -int(x.get("source_rank", 999999) or 999999),
        ),
        reverse=True,
    )

    representatives = []

    for item in candidates:
        strong_rep = None
        possible = []

        for rep in representatives:
            if strong_application_duplicate(item, rep):
                strong_rep = rep
                break
            if possible_application_duplicate(item, rep):
                possible.append(rep["stable_item_key"])

        if strong_rep is not None:
            item["queue_status"] = "HOLD_DUPLICATE"
            item["queue_status_label"] = QUEUE_STATUS_LABELS["HOLD_DUPLICATE"]
            item["duplicate_of_item_key"] = strong_rep["stable_item_key"]
            item["duplicate_confidence"] = "STRONG"
            group_seed = strong_rep.get("application_group_id") or strong_rep["stable_item_key"]
            group_id = stable_hash(group_seed, prefix="GROUP")
            strong_rep["application_group_id"] = group_id
            item["application_group_id"] = group_id
        else:
            if possible:
                item["possible_duplicate_item_keys"] = possible
                item["duplicate_confidence"] = "POSSIBLE"
            representatives.append(item)

    # Tout représentant sans groupe reçoit son propre groupe stable.
    for item in items:
        if item.get("queue_status") in {"READY_APPLY", "READY_STRETCH", "VERIFY_FIRST"}:
            if not item.get("application_group_id"):
                item["application_group_id"] = stable_hash(
                    item["stable_item_key"],
                    prefix="GROUP",
                )

    _rendre_les_cles_uniques(items)

    return items


def _rendre_les_cles_uniques(items):
    """
    Garantit l'unicité de stable_item_key sans faire disparaître personne.

    La clé dérive de l'URL. Or deux connecteurs différents peuvent renvoyer
    la MÊME URL : le site carrière de NRB est un board Recruitee, donc le
    connecteur employeur et le connecteur ATS pointent au même endroit. Les
    deux offres reçoivent alors la même clé — ce qui est juste, c'est bien
    la même offre — mais Application Preparation refuse une file contenant
    deux fois la même clé et interrompt tout le Daily Run.

    Le doublon est déjà repéré et marqué HOLD_DUPLICATE juste au-dessus. Le
    principe du module est de ne rien fusionner : « le secondaire reste
    visible ». On lui donne donc une clé propre, dérivée de sa source, et
    duplicate_of_item_key continue de désigner le représentant.

    L'ordre de la file compte : elle est triée avant, donc le premier
    rencontré est le représentant et garde sa clé d'origine.
    """
    vues = {}
    for item in items:
        cle = item.get("stable_item_key")
        if not cle:
            continue
        if cle not in vues:
            vues[cle] = item
            continue

        # Doublon : on le rattache explicitement au représentant, puis on
        # lui forge une clé distincte à partir de sa propre source.
        if not item.get("duplicate_of_item_key"):
            item["duplicate_of_item_key"] = cle
        source = clean_text(item.get("source")) or "INCONNUE"
        nouvelle = stable_hash(f"{cle}|{source}|{item.get('url') or ''}",
                               prefix="ITEM")
        rang = 2
        while nouvelle in vues:
            nouvelle = stable_hash(f"{cle}|{source}|{rang}", prefix="ITEM")
            rang += 1
        item["stable_item_key"] = nouvelle
        item["stable_item_key_origine"] = cle
        vues[nouvelle] = item


def build_application_queue_from_gate_payload(payload):
    items = [
        _prepare_record(record, source_rank=index)
        for index, record in enumerate(payload, start=1)
    ]

    apply_application_duplicate_guard(items)
    items.sort(key=_queue_sort_key, reverse=True)

    for position, item in enumerate(items, start=1):
        item["queue_rank"] = position

    return items


# ============================================================
# ADAPTATEUR MAIN : tuples (job, match_result, gate)
# ============================================================

def _safe_attr(job, name, default=None):
    value = getattr(job, name, default)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _verdict_du_job(job) -> dict:
    """
    Verdict lisible de l'offre, calcule ici et nulle part ailleurs.

    C'est le dernier endroit de la chaine ou l'objet job existe encore avec
    son texte : au-dela, la file ne transporte que des metadonnees. Le
    calculer plus tard obligerait a rouvrir la base.

    Une exception ne doit jamais casser la construction de la file : sans
    verdict, la file fonctionne exactement comme avant.
    """
    try:
        texte = "\n".join(str(x) for x in (
            getattr(job, "title", "") or "",
            getattr(job, "detail_matching_text", None)
            or getattr(job, "description", "") or "",
        ))
        resultat = evaluer_verdict(texte)
        return {
            "verdict": resultat.verdict,
            "verdict_obstacle": (resultat.barrieres[0].message
                                 if resultat.barrieres else ""),
        }
    except Exception:
        return {"verdict": "", "verdict_obstacle": ""}


def build_application_queue(gated_jobs):
    payload = []
    for position, (job, match_result, gate) in enumerate(gated_jobs, start=1):
        payload.append({
            "rank": position,
            "canonical_job_id": _safe_attr(job, "canonical_job_id"),
            "title": _safe_attr(job, "title", ""),
            "company": _safe_attr(job, "company", ""),
            "location": _safe_attr(job, "location", ""),
            "url": _safe_attr(job, "url", ""),
            "source": _safe_attr(job, "source", ""),
            "origin_source": _safe_attr(job, "origin_source", ""),
            "match_score": match_result.get("score"),
            "best_family": match_result.get("best_family"),
            "gate": gate,
            **_verdict_du_job(job),
        })
    return build_application_queue_from_gate_payload(payload)


# ============================================================
# PARTITIONS / SUMMARY
# ============================================================

def partition_application_queue(items):
    result = {
        "READY_APPLY": [],
        "READY_STRETCH": [],
        "VERIFY_FIRST": [],
        "HOLD_DUPLICATE": [],
        "EXCLUDED": [],
    }
    for item in items:
        result[item["queue_status"]].append(item)
    return result


def queue_summary(items):
    parts = partition_application_queue(items)
    return {
        "total": len(items),
        "READY_APPLY": len(parts["READY_APPLY"]),
        "READY_STRETCH": len(parts["READY_STRETCH"]),
        "VERIFY_FIRST": len(parts["VERIFY_FIRST"]),
        "HOLD_DUPLICATE": len(parts["HOLD_DUPLICATE"]),
        "EXCLUDED": len(parts["EXCLUDED"]),
        "preferred_ready_apply": sum(
            1 for item in parts["READY_APPLY"] if item.get("preferred_location")
        ),
        "data_ready_apply": sum(
            1 for item in parts["READY_APPLY"] if item.get("cv_track") == "DATA"
        ),
        "lab_qc_ready_apply": sum(
            1 for item in parts["READY_APPLY"] if item.get("cv_track") == "LAB_QC"
        ),
        "hybrid_ready_apply": sum(
            1 for item in parts["READY_APPLY"] if item.get("cv_track") == "HYBRID"
        ),
    }


# ============================================================
# EXPORT
# ============================================================

def export_application_queue(items, project_root):
    root = Path(project_root)
    export_dir = root / "exports" / "logs"
    export_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = export_dir / f"application_queue_v1_{timestamp}.json"
    txt_path = export_dir / f"application_queue_v1_{timestamp}.txt"

    json_path.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    parts = partition_application_queue(items)
    summary = queue_summary(items)

    lines = []
    lines.append("APPLICATION QUEUE V1")
    lines.append("=" * 76)
    lines.append(f"Total              : {summary['total']}")
    lines.append(f"READY_APPLY        : {summary['READY_APPLY']}")
    lines.append(f"READY_STRETCH      : {summary['READY_STRETCH']}")
    lines.append(f"VERIFY_FIRST       : {summary['VERIFY_FIRST']}")
    lines.append(f"HOLD_DUPLICATE     : {summary['HOLD_DUPLICATE']}")
    lines.append(f"EXCLUDED           : {summary['EXCLUDED']}")
    lines.append(f"APPLY zone prior.  : {summary['preferred_ready_apply']}")
    lines.append("")

    order = [
        "READY_APPLY",
        "READY_STRETCH",
        "VERIFY_FIRST",
        "HOLD_DUPLICATE",
    ]

    for status in order:
        lines.append("=" * 76)
        lines.append(QUEUE_STATUS_LABELS[status])
        lines.append("=" * 76)

        for idx, item in enumerate(parts[status], start=1):
            loc = "⭐ zone prioritaire" if item.get("preferred_location") else "Belgique"
            lines.append(
                f"{idx:>3}. Queue {item['queue_score']:>6.1f} | "
                f"Match {item['match_score']:>5.1f} | {item['title']}"
            )
            lines.append(f"     {item['company']}")
            lines.append(f"     {item['location']} | {loc}")
            lines.append(
                f"     CV : {item['cv_track_label']} | "
                f"Famille : {item['best_family']}"
            )
            lines.append(f"     Stable key : {item['stable_item_key']}")

            if item.get("duplicate_of_item_key"):
                lines.append(
                    f"     ↳ probable double candidature de {item['duplicate_of_item_key']}"
                )
            if item.get("possible_duplicate_item_keys"):
                lines.append(
                    "     ↳ doublon possible : "
                    + ", ".join(item["possible_duplicate_item_keys"][:5])
                )

            gate = item.get("gate") or {}
            messages = (
                list(gate.get("hard_reasons", []))
                + list(gate.get("warnings", []))
                + list(gate.get("reasons", []))
            )
            for message in messages[:4]:
                lines.append(f"     ↳ {message}")

            lines.append(f"     {item['url']}")
            lines.append("")

    txt_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "json_path": json_path,
        "txt_path": txt_path,
        "summary": summary,
    }
