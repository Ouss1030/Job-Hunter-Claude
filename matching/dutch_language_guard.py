"""Global conservative language guard for JobHunter.

Rejects only descriptions that are clearly and predominantly Dutch.
Designed to complement (not replace) explicit language-requirement checks.
No network / no database access.
"""
from __future__ import annotations

import re
import unicodedata

GUARD_VERSION = "1.0"
MIN_TEXT_CHARS = 300
MIN_NL_SCORE = 14
MIN_NL_DISTINCT = 6
NL_DOMINANCE_RATIO = 1.60


def _norm(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'")
    text = re.sub(r"[^a-z0-9+#./' -]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Deliberately avoid highly ambiguous tokens such as "je", "de", "en", "we", "work".
NL_WORDS = {
    "jouw", "wij", "onze", "zoeken", "functie", "ervaring", "opleiding",
    "vereisten", "verantwoordelijkheden", "werkzaamheden", "solliciteren",
    "klant", "klanten", "beschikt", "hebt", "bent", "kwaliteitscontrole",
    "arbeidsvoorwaarden", "omgeving", "aanbod", "vacature", "taken",
    "uitvoeren", "materialen", "eindproducten", "binnenkomende", "rapportage",
    "analyseresultaten", "verbetering", "vaardigheden", "verwachten", "stalen",
    "opslag", "traceerbaarheid", "zorgvuldige", "werktijden", "verlofdagen",
    "werkomgeving", "meetresultaten", "diploma", "gerelateerd", "veld",
}
FR_WORDS = {
    "vous", "votre", "nous", "notre", "recherchons", "experience", "diplome",
    "responsabilites", "exigences", "offre", "poste", "francais", "competences",
    "candidat", "missions", "formation", "entreprise", "equipe", "activites",
    "qualite", "laboratoire", "travail", "rejoignez", "profil", "fonction",
    "connaissances", "responsable", "environnement", "avantages", "contrat",
}
EN_WORDS = {
    "you", "your", "our", "experience", "degree", "requirements",
    "responsibilities", "role", "position", "candidate", "english", "skills",
    "looking", "apply", "working", "team", "laboratory", "quality",
    "qualifications", "responsible", "environment", "benefits", "contract",
    "knowledge", "activities", "company", "opportunity", "required", "preferred",
}

NL_PHRASES = (
    "op zoek naar", "wij zoeken", "we zoeken", "je doet", "je voert", "je werkt",
    "je bent", "je hebt", "je beschikt", "sluit je aan", "kennis van het nederlands",
    "goede kennis van", "goed kunnen omgaan", "functieomschrijving",
)
FR_PHRASES = (
    "nous recherchons", "vous etes", "vous êtes", "vos responsabilites",
    "description de la fonction", "profil recherche", "ce poste", "votre profil",
)
EN_PHRASES = (
    "we are looking", "you will", "your responsibilities", "job description",
    "what you will", "the successful candidate", "required qualifications",
)


def _score(text: str, words: set[str], phrases: tuple[str, ...]) -> tuple[int, int, list[str]]:
    tokens = re.findall(r"\b[a-z][a-z0-9'-]*\b", text)
    counts: dict[str, int] = {}
    for token in tokens:
        if token in words:
            counts[token] = counts.get(token, 0) + 1
    # Cap repeated words so one repeated token cannot dominate the result.
    word_score = sum(min(count, 4) for count in counts.values())
    phrase_hits = [phrase for phrase in phrases if phrase in text]
    score = word_score + 3 * len(phrase_hits)
    markers = sorted(set(counts) | set(phrase_hits))
    return score, len(markers), markers


def analyze_dutch_dominance(text: object) -> dict:
    n = _norm(text)
    if len(n) < MIN_TEXT_CHARS:
        return {
            "predominantly_dutch": False,
            "text_chars": len(n),
            "nl_score": 0,
            "fr_score": 0,
            "en_score": 0,
            "nl_distinct": 0,
            "reason": "TEXT_TOO_SHORT",
        }

    nl_score, nl_distinct, nl_markers = _score(n, NL_WORDS, NL_PHRASES)
    fr_score, _, _ = _score(n, FR_WORDS, FR_PHRASES)
    en_score, _, _ = _score(n, EN_WORDS, EN_PHRASES)
    competitor = fr_score + en_score

    predominantly = (
        nl_score >= MIN_NL_SCORE
        and nl_distinct >= MIN_NL_DISTINCT
        and nl_score >= NL_DOMINANCE_RATIO * (competitor + 1)
    )

    return {
        "predominantly_dutch": bool(predominantly),
        "text_chars": len(n),
        "nl_score": int(nl_score),
        "fr_score": int(fr_score),
        "en_score": int(en_score),
        "nl_distinct": int(nl_distinct),
        "nl_markers": nl_markers[:20],
        "reason": "NL_DOMINANT" if predominantly else "NOT_NL_DOMINANT",
    }


def predominantly_dutch(text: object) -> bool:
    return bool(analyze_dutch_dominance(text)["predominantly_dutch"])


def job_body_text(job: object) -> str:
    """Prefer enriched/detail body, then description; avoid URL/site chrome."""
    for attr in ("detail_matching_text", "description"):
        value = getattr(job, attr, None)
        if value and len(str(value).strip()) >= 80:
            return str(value)
    return str(getattr(job, "description", "") or "")
