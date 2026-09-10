"""
JOB HUNTER BELGIUM
APPLICATION GATE - VERSION 1.3.1

Production layer au-dessus du Gate V1.2 validé.

Corrections V1.3 :
1. Master/doctorat exprimé comme qualification structurée.
2. Offre V.I.E explicitement identifiée.
3. Intitulé explicitement immobilier / Real Estate hors cible.

Correction V1.3.1 :
4. Remplace uniquement la détection Master du V1.2 pendant l'évaluation
   afin d'éviter les contaminations entre phrases, par exemple :

       Bachelor in chemistry required.
       A Master's degree is a plus.

   Le "required" de la première phrase ne doit PAS rendre le Master obligatoire.

Le fichier matching/application_gate.py V1.2 reste totalement inchangé.
"""

from __future__ import annotations

import re
import unicodedata
from contextlib import contextmanager

import matching.application_gate as base_gate


GATE_VERSION = "1.3.1"

CANDIDATE_VIE_ELIGIBLE = False


def _clean(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _norm(value):
    text = _clean(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        ch for ch in text
        if not unicodedata.combining(ch)
    )
    text = text.replace("’", "'").replace("`", "'")
    text = re.sub(r"[^a-z0-9+#./' -]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _sentence_chunks(text):
    """
    Découpe conservatrice par fins de phrase / puces / retours ligne.
    Le but est précisément d'empêcher qu'un "required" situé dans une
    phrase voisine contamine la mention Master.
    """
    raw = str(text or "")
    chunks = re.split(r"(?<=[.!?;:])\s+|[\r\n•●▪◦]+", raw)
    return [
        _clean(chunk)
        for chunk in chunks
        if _clean(chunk)
    ]


def _contains_master_term(text):
    n = _norm(text)
    master_terms = [
        "master",
        "master's degree",
        "masters degree",
        "master degree",
        "diplome de master",
        "masterdiploma",
        "master diploma",
        "doctorat",
        "doctoraat",
        "phd",
        "ph.d",
    ]
    return any(_norm(term) in n for term in master_terms)


def _bachelor_alternative(text):
    n = _norm(text)
    patterns = [
        r"bachelor.{0,60}(?:or|ou|/)\s*master",
        r"bachelier.{0,60}(?:ou|/)\s*master",
        r"master.{0,60}(?:or|ou|/)\s*bachelor",
        r"master.{0,60}(?:ou|/)\s*bachelier",
        r"bachelor\s*(?:/|or|ou|of)\s*master",
        r"bachelier\s*(?:/|ou)\s*master",
    ]
    return any(re.search(pattern, n) for pattern in patterns)


def _optional_master_sentence(sentence):
    n = _norm(sentence)

    optional_markers = [
        "is a plus",
        "est un plus",
        "serait un plus",
        "un plus",
        "a plus",
        "asset",
        "atout",
        "preferred",
        "preferable",
        "nice to have",
        "nice-to-have",
        "souhaite",
        "souhaitee",
        "pluspunt",
        "mooi meegenomen",
        "bij voorkeur",
        "voorkeur",
    ]

    if _bachelor_alternative(sentence):
        return True

    return any(_norm(marker) in n for marker in optional_markers)


def _explicit_master_requirement_sentence(sentence):
    """
    Exigence Master explicite dans LA MÊME phrase.
    """
    n = _norm(sentence)

    patterns = [
        r"(?:minimum|minstens|at least)\s+(?:un\s+|a\s+)?master",
        r"master(?:diploma| diploma| degree|'s degree|s degree)?"
        r".{0,35}(?:required|mandatory|must|vereist|verplicht|obligatoire|requis|exige)",
        r"(?:required|mandatory|must|vereist|verplicht|obligatoire|requis|exige)"
        r".{0,35}master",
        r"(?:diplome|diplôme)\s+de\s+master.{0,25}"
        r"(?:requis|obligatoire|exige|exigé)",
        r"niveau\s+master.{0,25}(?:requis|obligatoire|minimum)",
        r"master\s+avec\s+experience",
        r"master\s+met\s+ervaring",
        r"master\s+with\s+experience",
        r"master'?s?\s+or\s+ph\.?d",
        r"master\s+ou\s+(?:doctorat|docteur)",
    ]

    return any(re.search(pattern, n) for pattern in patterns)


def detect_mandatory_master_v131(text):
    """
    Détection Master utilisée à la place de celle du V1.2.

    Règles :
    - une simple mention ne suffit pas ;
    - une alternative Bachelor/Master ne bloque pas ;
    - "Master ... is a plus" ne bloque pas ;
    - une obligation explicite dans la même phrase bloque ;
    - une qualification structurée de type "Master's degree in X"
      sera traitée séparément par detect_structured_master_requirement().
    """
    for sentence in _sentence_chunks(text):
        if not _contains_master_term(sentence):
            continue

        if _optional_master_sentence(sentence):
            continue

        if _explicit_master_requirement_sentence(sentence):
            return True

    return False


@contextmanager
def _safe_master_detector_for_v12():
    """
    Le Gate V1.2 appelle son symbole global detect_mandatory_master().
    On remplace temporairement CE symbole uniquement pendant une évaluation.
    Toutes les autres règles V1.2 restent donc strictement identiques.
    """
    original = base_gate.detect_mandatory_master
    base_gate.detect_mandatory_master = detect_mandatory_master_v131
    try:
        yield
    finally:
        base_gate.detect_mandatory_master = original


def _contains_target_title_anchor(title):
    t = _norm(title)

    anchors = [
        "data analyst",
        "data engineer",
        "business analyst",
        "bi analyst",
        "power bi",
        "reporting analyst",
        "laborant",
        "laboratory",
        "laboratoire",
        "chimiste",
        "chemist",
        "quality control",
        "controle qualite",
        "qc analyst",
    ]
    return any(anchor in t for anchor in anchors)


def detect_real_estate_domain_mismatch(title):
    t = _norm(title)

    markers = [
        "real estate",
        "immobilier",
        "immobiliere",
        "vastgoed",
        "property manager",
        "property portfolio",
    ]

    if any(marker in t for marker in markers):
        if not _contains_target_title_anchor(title):
            return (
                "Intitulé explicitement immobilier / Real Estate : "
                "hors des domaines Data, chimie, laboratoire et QC visés"
            )

    return None


def _explicit_vie_offer(title, text=""):
    raw_title = _clean(title)
    norm_title = _norm(title)
    norm_text = _norm(text)

    if re.search(
        r"\bV\s*\.\s*I\s*\.\s*E\s*\.?(?=\s|$|\W)",
        raw_title,
        flags=re.IGNORECASE,
    ):
        return True

    if re.search(
        r"\bV\s*-\s*I\s*-\s*E\b",
        raw_title,
        flags=re.IGNORECASE,
    ):
        return True

    if re.search(r"\bVIE\b", raw_title):
        return True

    if re.search(r"\bvie\s+(?:programme|program)\b", norm_title):
        return True

    official_phrases = [
        "volontariat international en entreprise",
        "volunteer for international experience",
    ]
    return any(phrase in norm_text for phrase in official_phrases)


def detect_vie_ineligibility(title, text):
    if CANDIDATE_VIE_ELIGIBLE:
        return None

    if _explicit_vie_offer(title, text):
        return (
            "Offre V.I.E : profil candidat non éligible au dispositif "
            "(condition d'âge)"
        )

    return None


def _bachelor_alternative_near_master(text, start, end, radius=150):
    window = _norm(
        text[
            max(0, start - radius):
            min(len(text), end + radius)
        ]
    )

    patterns = [
        r"bachelor.{0,45}master",
        r"bachelier.{0,45}master",
        r"master.{0,45}bachelor",
        r"master.{0,45}bachelier",
        r"bachelor\s*(?:/|or|ou)\s*master",
        r"bachelier\s*(?:/|ou)\s*master",
    ]
    return any(re.search(pattern, window) for pattern in patterns)


def _optional_master_context(text, start, end, radius=130):
    window = _norm(
        text[
            max(0, start - radius):
            min(len(text), end + radius)
        ]
    )

    optional = [
        "plus",
        "asset",
        "atout",
        "preferred",
        "preferable",
        "nice to have",
        "souhaite",
        "souhaitee",
        "is a plus",
        "est un plus",
    ]
    return any(marker in window for marker in optional)


def detect_structured_master_requirement(text):
    """
    Qualification structurée ATS sans "required", par ex. :
        Qualifications: Master's degree in chemistry.

    L'alternative Bachelor/Master et le Master optionnel restent acceptés.
    """
    for sentence in _sentence_chunks(text):
        n = _norm(sentence)

        if not _contains_master_term(sentence):
            continue

        if _optional_master_sentence(sentence):
            continue

        structural_patterns = [
            r"\bmaster'?s?\s+degree\s+in\b",
            r"\bholds?\s+(?:a\s+)?master'?s?\s+degree\b",
            r"\bmaster\s+(?:of\s+science|of\s+engineering)\b",
            r"\bmaster\s+en\s+[a-z]",
            r"\bmaster\s+in\s+[a-z]",
            r"\bmaster\s+of\s+[a-z]",
            r"\bmaster\s+avec\s+experience\b",
            r"\bmaster\s+met\s+ervaring\b",
            r"\bmaster\s+with\s+experience\b",
            r"\bmaster'?s?\s+or\s+ph\.?d\b",
            r"\bmaster\s+ou\s+(?:doctorat|docteur)\b",
        ]

        for pattern in structural_patterns:
            if re.search(pattern, n):
                if re.search(r"\bmaster\s+data\b", n):
                    continue
                return True

    return False


def _append_unique(items, message):
    if message and message not in items:
        items.append(message)


def apply_v13_to_gate(job, match_result, gate):
    result = dict(gate)
    result["reasons"] = list(gate.get("reasons") or [])
    result["warnings"] = list(gate.get("warnings") or [])
    result["hard_reasons"] = list(gate.get("hard_reasons") or [])

    title = _clean(getattr(job, "title", ""))
    text = base_gate.job_text(job)

    v13_reasons = []

    real_estate = detect_real_estate_domain_mismatch(title)
    if real_estate:
        v13_reasons.append(real_estate)

    vie = detect_vie_ineligibility(title, text)
    if vie:
        v13_reasons.append(vie)

    structured_master = detect_structured_master_requirement(text)
    if (
        structured_master
        and not result.get("mandatory_master_detected")
    ):
        v13_reasons.append(
            "Master/doctorat exigé dans les qualifications structurées "
            "alors que les diplômes achevés sont de niveau bachelier"
        )
        result["mandatory_master_detected"] = True

    if v13_reasons:
        for reason in v13_reasons:
            _append_unique(result["hard_reasons"], reason)

        result["status"] = "REJECT"
        result["status_label"] = base_gate.STATUS_LABELS["REJECT"]
        result["priority_score"] = base_gate.gate_priority_score(
            float(match_result.get("score", 0) or 0),
            "REJECT",
            0,
        )

        result["reasons"] = [
            reason
            for reason in result["reasons"]
            if "Aucun blocage fort détecté" not in reason
        ]
        if not result["reasons"]:
            result["reasons"].append(
                "Au moins une incompatibilité forte a été détectée"
            )

    result["gate_version"] = GATE_VERSION
    result["v13_overlay"] = {
        "real_estate_domain_mismatch": real_estate,
        "vie_ineligible": vie,
        "structured_master_requirement": structured_master,
    }

    return result


def evaluate_application_gate(job, match_result):
    with _safe_master_detector_for_v12():
        gate_v12 = base_gate.evaluate_application_gate(job, match_result)

    return apply_v13_to_gate(job, match_result, gate_v12)


def apply_application_gate(scored_jobs):
    gated = []

    for job, match_result in scored_jobs:
        gate = evaluate_application_gate(job, match_result)
        gated.append((job, match_result, gate))

    gated.sort(
        key=base_gate.gate_sort_key,
        reverse=True,
    )
    return gated


partition_gate_results = base_gate.partition_gate_results
gate_summary = base_gate.gate_summary
export_application_gate = base_gate.export_application_gate
STATUS_LABELS = base_gate.STATUS_LABELS
STATUS_ORDER = base_gate.STATUS_ORDER
gate_sort_key = base_gate.gate_sort_key
