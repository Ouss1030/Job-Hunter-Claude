"""
JOB HUNTER BELGIUM
APPLICATION GATE V1.3.1 - SHADOW OVERLAY

Objectif
========
Tester trois défauts CONCRETS révélés par SmartRecruiters sans remplacer
matching/application_gate.py V1.2.

Corrections ciblées :
1. Master/PhD listé comme qualification structurée, même sans mot "required".
2. Offre V.I.E incompatible avec le profil candidat.
3. Intitulé explicitement immobilier / Real Estate hors domaine.

Cette surcouche appelle d'abord Gate V1.2, puis n'ajoute que des hard rejects
très conservateurs. Elle ne modifie ni Matcher, ni Queue, ni Canonical.

V1.3.1 corrige le faux positif critique où le mot français « vie »
était interprété comme l'acronyme V.I.E.

Après validation, ces règles pourront être intégrées proprement
dans Application Gate V1.3 natif.
"""

from __future__ import annotations

import re
import unicodedata

import matching.application_gate as base_gate


OVERLAY_VERSION = "1.3.1-shadow"

# Projet personnel : le candidat n'est pas éligible au dispositif V.I.E.
# Ce booléen sera ensuite déplacé dans le profil privé si V1.3 est validé.
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


def _contains_target_title_anchor(title):
    """
    Empêche un rejet immobilier si le titre est réellement un poste Data
    consacré à l'immobilier, p.ex. "Real Estate Data Analyst".
    """
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
        "contrôle qualité",
        "qc analyst",
    ]
    return any(anchor in t for anchor in anchors)


def detect_real_estate_domain_mismatch(title):
    t = _norm(title)

    markers = [
        "real estate",
        "immobilier",
        "immobiliere",
        "immobilière",
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
    """
    Détecte UNIQUEMENT un vrai dispositif V.I.E.

    Important :
    - ne jamais assimiler le mot français "vie" à V.I.E ;
    - privilégier l'intitulé du poste ;
    - accepter la formulation officielle complète dans le texte.
    """
    raw_title = _clean(title)
    norm_title = _norm(title)
    norm_text = _norm(text)

    # V.I.E / V. I. E. avec points : non ambigu.
    if re.search(
        r"\bV\s*\.\s*I\s*\.\s*E\s*\.?(?=\s|$|\W)",
        raw_title,
        flags=re.IGNORECASE,
    ):
        return True

    # V-I-E : non ambigu.
    if re.search(
        r"\bV\s*-\s*I\s*-\s*E\b",
        raw_title,
        flags=re.IGNORECASE,
    ):
        return True

    # Acronyme VIE explicitement en MAJUSCULES dans le titre.
    if re.search(r"\bVIE\b", raw_title):
        return True

    # Après normalisation des points, le titre V.I.E devient "v.i.e" ou "vie".
    # On n'accepte "vie" que s'il est directement lié à "programme/program".
    if re.search(r"\bvie\s+(?:programme|program)\b", norm_title):
        return True

    # Formulation officielle complète : sûre même dans la description.
    official_phrases = [
        "volontariat international en entreprise",
        "volunteer for international experience",
    ]
    if any(phrase in norm_text for phrase in official_phrases):
        return True

    return False


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
    window = _norm(text[max(0, start - radius): min(len(text), end + radius)])

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
    window = _norm(text[max(0, start - radius): min(len(text), end + radius)])
    optional = [
        "plus",
        "asset",
        "atout",
        "preferred",
        "preferable",
        "préférable",
        "nice to have",
        "souhaite",
        "souhaité",
        "souhaitee",
        "souhaitée",
        "is a plus",
        "est un plus",
    ]
    return any(marker in window for marker in optional)


def detect_structured_master_requirement(text):
    """
    Gate V1.2 exige un marqueur explicite du type "required".
    Beaucoup d'ATS placent cependant les exigences sous "Qualifications"
    sous forme de puces :
        Qualifications: Master's degree in ...
        Qualifications: Master avec expérience ou Docteur...
        Holds master's degree...
    Ces formulations sont des exigences de profil même sans le mot required.

    Règle conservatrice :
    - alternative Bachelor acceptée => PAS de hard reject ;
    - Master explicitement présenté comme un plus => PAS de hard reject ;
    - sinon seules des structures très nettes sont reconnues.
    """
    raw = _clean(text)
    n = _norm(raw)

    structural_patterns = [
        r"\bmaster'?s?\s+degree\s+in\b",
        r"\bholds?\s+(?:a\s+)?master'?s?\s+degree\b",
        r"\bmaster\s+avec\s+experience\b",
        r"\bmaster\s+met\s+ervaring\b",
        r"\bmaster\s+with\s+experience\b",
        r"\bmaster\s+(?:of\s+science|of\s+engineering)\b",
        r"\bmaster\s+en\s+[a-z]",
        r"\bmaster\s+in\s+[a-z]",
        r"\bmaster\s+of\s+[a-z]",
        r"\bmaster'?s?\s+or\s+ph\.?d\b",
        r"\bmaster\s+ou\s+doctorat\b",
        r"\bmaster\s+ou\s+docteur\b",
    ]

    for pattern in structural_patterns:
        for m in re.finditer(pattern, n):
            if _bachelor_alternative_near_master(n, m.start(), m.end()):
                continue
            if _optional_master_context(n, m.start(), m.end()):
                continue

            # Évite le faux ami "Master Data".
            after = n[m.start(): m.end() + 20]
            if re.search(r"\bmaster\s+data\b", after):
                continue

            return True

    return False


def _append_unique(items, message):
    if message and message not in items:
        items.append(message)


def apply_overlay_to_gate(job, match_result, gate):
    """
    Modifie une copie du dict Gate afin de préserver le résultat V1.2 original.
    """
    result = dict(gate)
    result["reasons"] = list(gate.get("reasons") or [])
    result["warnings"] = list(gate.get("warnings") or [])
    result["hard_reasons"] = list(gate.get("hard_reasons") or [])

    title = _clean(getattr(job, "title", ""))
    text = base_gate.job_text(job)

    overlay_reasons = []

    real_estate = detect_real_estate_domain_mismatch(title)
    if real_estate:
        overlay_reasons.append(real_estate)

    vie = detect_vie_ineligibility(title, text)
    if vie:
        overlay_reasons.append(vie)

    structured_master = detect_structured_master_requirement(text)
    if (
        structured_master
        and not result.get("mandatory_master_detected")
    ):
        overlay_reasons.append(
            "Master/doctorat exigé dans les qualifications structurées "
            "alors que les diplômes achevés sont de niveau bachelier"
        )
        result["mandatory_master_detected"] = True

    if overlay_reasons:
        for reason in overlay_reasons:
            _append_unique(result["hard_reasons"], reason)

        result["status"] = "REJECT"
        result["status_label"] = base_gate.STATUS_LABELS["REJECT"]
        result["priority_score"] = base_gate.gate_priority_score(
            float(match_result.get("score", 0) or 0),
            "REJECT",
            0,
        )

        # Nettoie une éventuelle raison APPLY devenue contradictoire.
        result["reasons"] = [
            reason
            for reason in result["reasons"]
            if "Aucun blocage fort détecté" not in reason
        ]
        if not result["reasons"]:
            result["reasons"].append(
                "Au moins une incompatibilité forte a été détectée"
            )

    result["gate_version"] = OVERLAY_VERSION
    result["v13_overlay"] = {
        "real_estate_domain_mismatch": real_estate,
        "vie_ineligible": vie,
        "structured_master_requirement": structured_master,
    }

    return result


def apply_application_gate_v13(scored_jobs):
    """
    Drop-in replacement pour core_main.apply_application_gate.
    """
    gated_v12 = base_gate.apply_application_gate(scored_jobs)
    gated_v13 = []

    for job, match_result, gate in gated_v12:
        updated = apply_overlay_to_gate(job, match_result, gate)
        gated_v13.append((job, match_result, updated))

    gated_v13.sort(
        key=base_gate.gate_sort_key,
        reverse=True,
    )
    return gated_v13
