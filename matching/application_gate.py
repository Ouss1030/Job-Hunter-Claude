"""
JOB HUNTER BELGIUM
APPLICATION GATE - VERSION 1.2

Objectif
========
Transformer le score de proximité métier en décision de candidature :

    APPLY   = candidater maintenant
    STRETCH = candidature possible malgré un écart raisonnable
    VERIFY  = condition importante à confirmer avant candidature
    REJECT  = incompatibilité suffisamment certaine pour ne pas postuler

Principes
=========
- Le Gate ne remplace PAS le matcher.
- Le Gate travaille APRES enrichissement + canonicalisation.
- Les hard rejects sont volontairement conservateurs.
- Une simple mention de Master ne suffit pas : il doit être explicitement exigé.
- Une compétence absente ne devient bloquante que si le texte la présente
  explicitement comme obligatoire / indispensable / must-have.
- Règle utilisateur : un poste de technologue de laboratoire nécessitant
  un agrément / visa / reconnaissance professionnelle est toujours REJECT.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

from config.profile import EXPERIENCE_PROFILE, LANGUAGES


GATE_VERSION = "1.2"

STATUS_ORDER = {
    "APPLY": 4,
    "STRETCH": 3,
    "VERIFY": 2,
    "REJECT": 1,
}

STATUS_LABELS = {
    "APPLY": "🟢 APPLY",
    "STRETCH": "🟡 STRETCH",
    "VERIFY": "🟠 VERIFY",
    "REJECT": "🔴 REJECT",
}


# ============================================================
# PROFIL CANDIDAT UTILISÉ PAR LE GATE
# ============================================================

CANDIDATE = {
    "completed_degrees": [
        "Bachelier en chimie",
        "Bachelier de spécialisation Business Data Analyst",
    ],
    "chemistry_lab_professional_years": float(
        EXPERIENCE_PROFILE.get("chemistry_lab", {}).get("professional_years", 0.0)
    ),
    "data_professional_years": float(
        EXPERIENCE_PROFILE.get("data_analytics", {}).get("professional_years", 0.0)
    ),
    "data_effective_project_years": float(
        EXPERIENCE_PROFILE.get("data_analytics", {}).get("effective_years", 0.0)
    ),
    "languages": {
        "fr": LANGUAGES.get("french", {}).get("level", "C2"),
        "en": LANGUAGES.get("english", {}).get("level", "B1"),
        "nl": LANGUAGES.get("dutch", {}).get("level", "A2"),
    },
    # Information explicitement donnée par l'utilisateur.
    "has_medical_lab_technologist_accreditation": False,
}


DATA_FAMILIES = {
    "data_analytics",
    "business_intelligence",
    "business_analysis",
    "data_engineering",
}

CHEMISTRY_FAMILIES = {
    "chemistry_lab",
    "pharma_qc",
    "quality",
    "hybrid_data_pharma",
}


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


def phrase_regex(value):
    """
    Regex token-aware pour éviter les sous-chaînes accidentelles.

    Exemple important :
        "fabric" ne doit PAS matcher "fabrication".
    """
    nvalue = normalize(value)
    if not nvalue:
        return None
    pieces = [re.escape(piece) for piece in nvalue.split()]
    body = r"\s+".join(pieces)
    return rf"(?<![a-z0-9]){body}(?![a-z0-9])"


def iter_phrase_matches(text, phrase):
    pattern = phrase_regex(phrase)
    if not pattern:
        return ()
    return re.finditer(pattern, text)


def contains_phrase(text, phrase):
    pattern = phrase_regex(phrase)
    return bool(pattern and re.search(pattern, text))


def job_text(job):
    parts = [
        getattr(job, "title", ""),
        getattr(job, "description", ""),
        getattr(job, "detail_matching_text", ""),
        getattr(job, "experience_requirement", ""),
        getattr(job, "degree_requirement", ""),
        getattr(job, "language", ""),
        getattr(job, "contract_type", ""),
        getattr(job, "restriction", ""),
    ]
    return "\n".join(clean_text(part) for part in parts if clean_text(part))


# ============================================================
# MARQUEURS OBLIGATOIRES / OPTIONNELS
# ============================================================

MANDATORY_MARKERS = [
    "obligatoire",
    "obligatoirement",
    "requis",
    "requise",
    "requis(e)",
    "exige",
    "exigee",
    "exigé",
    "exigée",
    "indispensable",
    "imperatif",
    "impératif",
    "must have",
    "must-have",
    "required",
    "mandatory",
    "essential",
    "minimum",
    "at least",
    "minstens",
    "vereist",
    "verplicht",
    "noodzakelijk",
    "essentieel",
]

OPTIONAL_MARKERS = [
    "souhaite",
    "souhaité",
    "souhaitee",
    "souhaitée",
    "atout",
    "un plus",
    "serait un plus",
    "preferable",
    "préférable",
    "preferred",
    "nice to have",
    "nice-to-have",
    "asset",
    "pluspunt",
    "mooi meegenomen",
    "bij voorkeur",
    "voorkeur",
]


def context_window(text, start, end, radius=95):
    return text[max(0, start - radius): min(len(text), end + radius)]


def is_optional_context(window):
    norm = normalize(window)
    return any(marker in norm for marker in map(normalize, OPTIONAL_MARKERS))


def is_mandatory_context(window):
    norm = normalize(window)
    if is_optional_context(norm):
        return False
    return any(marker in norm for marker in map(normalize, MANDATORY_MARKERS))


# ============================================================
# DIPLOME
# ============================================================

MASTER_TERMS = [
    "master",
    "master's degree",
    "masters degree",
    "master degree",
    "diplome de master",
    "diplôme de master",
    "masterdiploma",
    "master diploma",
    "doctorat",
    "doctoraat",
    "phd",
]

BACHELOR_OR_MASTER_PATTERNS = [
    r"bachelor\s*(?:/|ou|or|of)\s*master",
    r"bachelier\s*(?:/|ou)\s*master",
    r"bachelor(?:niveau)?\s+of\s+master",
]


def detect_mandatory_master(text):
    norm = normalize(text)

    for pattern in BACHELOR_OR_MASTER_PATTERNS:
        if re.search(pattern, norm):
            # La présence d'une alternative bachelor empêche un hard reject
            # pour la même formulation générale.
            pass

    hits = []
    for term in MASTER_TERMS:
        nterm = normalize(term)
        for match in iter_phrase_matches(norm, nterm):
            window = context_window(norm, match.start(), match.end(), radius=100)

            # "Master Data" est un concept métier, pas un diplôme de Master.
            after = norm[match.end(): match.end() + 12]
            if nterm == "master" and re.match(r"\s+data\b", after):
                continue

            if re.search(r"bachelor\s*(?:/|ou|or|of)\s*master", window):
                continue
            if re.search(r"bachelier\s*(?:/|ou)\s*master", window):
                continue
            if is_mandatory_context(window):
                hits.append(window)

    # Formulations où l'obligation est portée directement par la structure.
    structural_patterns = [
        r"(?:minimum|minstens|at least)\s+(?:un\s+)?master",
        r"master(?:diploma| diploma| degree)?\s+(?:is\s+)?(?:required|mandatory|vereist|verplicht)",
        r"(?:diplome|diplôme)\s+de\s+master\s+(?:requis|obligatoire|exige|exigé)",
        r"niveau\s+master\s+(?:requis|obligatoire|minimum)",
    ]
    for pattern in structural_patterns:
        if re.search(pattern, norm):
            hits.append(pattern)

    return bool(hits)


# ============================================================
# EXPERIENCE
# ============================================================

EXPERIENCE_PATTERNS = [
    r"(?P<n>\d{1,2})\s*(?:ans|annees|année|années)\s+(?:d[' ]?experience|experience)",
    r"(?:minimum|min\.?|au moins)\s*(?P<n>\d{1,2})\s*(?:ans|annees|année|années)",
    r"(?P<n>\d{1,2})\s*(?:years?|yrs?)\s+(?:of\s+)?experience",
    r"(?:minimum|at least|min\.?)\s*(?P<n>\d{1,2})\s*(?:years?|yrs?)",
    r"(?P<n>\d{1,2})\s*jaar\s+ervaring",
    r"(?:minstens|minimaal)\s*(?P<n>\d{1,2})\s*jaar",
]


COMPANY_EXPERIENCE_MARKERS = [
    "notre agence",
    "notre entreprise",
    "notre societe",
    "notre société",
    "our company",
    "our agency",
    "notre groupe",
    "depuis",
    "since",
    "sinds",
    "recrutement",
    "recruitment",
    "rekrutering",
    "uitzend",
]

CANDIDATE_EXPERIENCE_MARKERS = [
    "vous ",
    "votre ",
    "tu ",
    "your ",
    "you ",
    "candidate",
    "candidat",
    "profil",
    "profile",
    "jij ",
    "jouw ",
    "je hebt",
    "u hebt",
]


def is_company_experience_context(window):
    nwindow = normalize(window)
    company_context = any(normalize(marker) in nwindow for marker in COMPANY_EXPERIENCE_MARKERS)
    candidate_context = any(normalize(marker) in nwindow for marker in CANDIDATE_EXPERIENCE_MARKERS)
    explicit_requirement = is_mandatory_context(nwindow)

    # Ne pas prendre l'ancienneté d'une agence/entreprise pour l'expérience
    # demandée au candidat.
    return bool(company_context and not candidate_context and not explicit_requirement)


def detect_required_experience_years(text):
    norm = normalize(text)
    mandatory_years = []
    optional_years = []

    for pattern in EXPERIENCE_PATTERNS:
        for match in re.finditer(pattern, norm):
            years = int(match.group("n"))
            window = context_window(norm, match.start(), match.end(), radius=90)

            if is_company_experience_context(window):
                continue

            if is_optional_context(window):
                optional_years.append(years)
                continue

            # Une phrase d'expérience est généralement une exigence même si
            # elle n'emploie pas explicitement le mot "obligatoire".
            mandatory_years.append(years)

    return {
        "mandatory": max(mandatory_years) if mandatory_years else None,
        "optional": max(optional_years) if optional_years else None,
    }


def candidate_professional_years(family):
    if family in DATA_FAMILIES:
        return CANDIDATE["data_professional_years"]
    if family in CHEMISTRY_FAMILIES:
        return CANDIDATE["chemistry_lab_professional_years"]
    return 0.0


# ============================================================
# SENIORITE
# ============================================================

DATA_HARD_SENIOR_TITLE_MARKERS = [
    "senior",
    "lead data",
    "lead bi",
    "principal data",
    "principal bi",
    "head of data",
    "head of bi",
    "data manager",
    "analytics manager",
    "data architect",
]


def has_hard_data_seniority(title, family):
    if family not in DATA_FAMILIES:
        return False
    norm_title = normalize(title)
    if "junior" in norm_title:
        return False
    return any(marker in norm_title for marker in DATA_HARD_SENIOR_TITLE_MARKERS)


# ============================================================
# AGREMENT / PROFESSIONS REGLEMENTEES
# ============================================================

MEDICAL_LAB_TITLE_MARKERS = [
    "technologue de laboratoire",
    "technologue de laboratoire medical",
    "technologue de laboratoire médical",
    "medical laboratory technologist",
    "medical laboratory technician",
    "medisch laboratorium technoloog",
    "medisch laboratoriumtechnoloog",
    "technoloog medische laboratoriumdiagnostiek",
]

ACCREDITATION_MARKERS = [
    "agrement",
    "agrément",
    "visa",
    "visum",
    "erkenning",
    "reconnaissance professionnelle",
    "professionele erkenning",
]


def detect_medical_lab_accreditation_block(title, text):
    if CANDIDATE["has_medical_lab_technologist_accreditation"]:
        return False

    ntitle = normalize(title)
    ntext = normalize(text)

    has_title = any(normalize(marker) in ntitle for marker in MEDICAL_LAB_TITLE_MARKERS)
    has_credential = any(normalize(marker) in ntext for marker in ACCREDITATION_MARKERS)

    return has_title and has_credential


def detect_unknown_mandatory_credential(text):
    """
    V1.2 : uniquement des credentials clairement personnels.

    Les mots génériques "certification/certificat" ne suffisent plus :
    dans les annonces Quality ils décrivent très souvent une certification
    ISO/GMP de l'entreprise ou un processus qualité, et non un document
    que le candidat doit posséder.
    """
    norm = normalize(text)
    credential_terms = [
        "agrement",
        "visa",
        "visum",
        "erkenning",
        "permis b",
        "rijbewijs b",
        "driving licence",
        "security clearance",
        "habilitation",
    ]

    for term in credential_terms:
        for match in iter_phrase_matches(norm, term):
            window = context_window(norm, match.start(), match.end(), radius=80)
            if is_mandatory_context(window):
                return term
    return None


FOREIGN_COUNTRY_MARKERS = {
    "canada": "Canada",
    "france": "France",
    "germany": "Allemagne",
    "deutschland": "Allemagne",
    "netherlands": "Pays-Bas",
    "nederland": "Pays-Bas",
    "switzerland": "Suisse",
    "suisse": "Suisse",
    "united kingdom": "Royaume-Uni",
    "royaume uni": "Royaume-Uni",
    "united states": "États-Unis",
    "usa": "États-Unis",
}


def detect_outside_belgium(location):
    nloc = normalize(location)
    if not nloc:
        return None

    # Les provinces belges peuvent contenir "Luxembourg" : la présence de
    # Belgique/België prime donc toujours.
    if any(marker in nloc for marker in ["belgique", "belgie", "belgium"]):
        return None

    for marker, label in FOREIGN_COUNTRY_MARKERS.items():
        if contains_phrase(nloc, marker):
            return label
    return None


STUDENT_TITLE_MARKERS = [
    "student",
    "studentenjob",
    "jobstudent",
    "etudiant",
    "étudiant",
]


def detect_student_role(title):
    ntitle = normalize(title)
    return any(contains_phrase(ntitle, marker) for marker in STUDENT_TITLE_MARKERS)


OBVIOUS_OUT_OF_DOMAIN_LAB_TITLE_MARKERS = [
    "laboratoire film",
    "film laboratory",
    "film lab",
    "laboratoire photo",
    "photo laboratory",
    "photographic laboratory",
]


def detect_obvious_domain_mismatch(title, family):
    if family not in CHEMISTRY_FAMILIES:
        return None
    ntitle = normalize(title)
    for marker in OBVIOUS_OUT_OF_DOMAIN_LAB_TITLE_MARKERS:
        if contains_phrase(ntitle, marker):
            return "Laboratoire cinéma/photo détecté : hors du domaine chimie/QC visé"
    return None


# ============================================================
# LANGUES
# ============================================================

LANGUAGE_ALIASES = {
    "fr": ["francais", "français", "french"],
    "en": ["anglais", "english", "engels"],
    "nl": ["neerlandais", "néerlandais", "dutch", "nederlands", "nl"],
}

LEVEL_RANK = {
    "A1": 1,
    "A2": 2,
    "B1": 3,
    "B2": 4,
    "C1": 5,
    "C2": 6,
}


def _dutch_is_fr_or_nl_alternative(segment):
    """Détecte une vraie alternative : français OU néerlandais, pas une double exigence."""
    s = normalize(segment)
    patterns = [
        r"\bfrench\s+(?:or|ou)\s+dutch\b",
        r"\bdutch\s+(?:or|ou)\s+french\b",
        r"\bfrancais\s+ou\s+neerlandais\b",
        r"\bneerlandais\s+ou\s+francais\b",
        r"\bfrans\s+of\s+nederlands\b",
        r"\bnederlands\s+of\s+frans\b",
    ]
    return any(re.search(pattern, s, re.I) for pattern in patterns)


def _dutch_professional_requirement_without_cefr(segment):
    """
    Exigences professionnelles courantes sans CECR explicite.
    On les mappe prudemment sur B2 afin qu'un candidat A2 soit signalé.
    """
    s = normalize(segment)

    strong_phrases = [
        "good knowledge of dutch",
        "good command of dutch",
        "professional dutch",
        "working proficiency in dutch",
        "bonne connaissance du neerlandais",
        "bonne connaissance en neerlandais",
        "maitrise du neerlandais",
        "maitrise neerlandais",
        "excellente connaissance du neerlandais",
        "tres bonne connaissance du neerlandais",
        "goede kennis van het nederlands",
        "goede kennis van nederlands",
        "goede kennis nederlands",
        "goede beheersing van het nederlands",
        "goede beheersing van nederlands",
        "vlot in het nederlands",
        "vlot nederlands",
        "zeer vlot nederlands",
        "vloeiend nederlands",
        "vlotte communicatievaardigheden in het nederlands",
        "tweetalig nl/fr",
        "tweetalig fr/nl",
        "bilingue fr/nl",
        "bilingue nl/fr",
        "bilingue francais/neerlandais",
        "bilingue neerlandais/francais",
    ]
    return any(normalize(phrase) in s for phrase in strong_phrases)


def detect_language_gaps(text):
    """
    Détecte les écarts linguistiques sans attribuer le niveau d'une langue
    voisine à une autre langue.

    V1.1 :
    - le texte est découpé par occurrences de langues ;
    - un niveau CECR est rattaché uniquement au segment de cette langue ;
    - C1/C2 n'est un hard reject que si l'exigence est explicitement
      obligatoire/requise dans ce même segment ;
    - sinon l'écart devient un warning -> STRETCH.
    """
    norm = normalize(text)
    gaps = []

    occurrences = []
    for code, aliases in LANGUAGE_ALIASES.items():
        for alias in aliases:
            nalias = normalize(alias)
            if not nalias:
                continue
            for match in iter_phrase_matches(norm, nalias):
                occurrences.append((match.start(), match.end(), code, nalias))

    occurrences.sort(key=lambda item: (item[0], item[1]))

    # Supprime les doublons qui commencent au même endroit
    deduped = []
    seen = set()
    for item in occurrences:
        key = (item[0], item[2])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    occurrences = deduped

    for idx, (start_pos, end_pos, code, alias) in enumerate(occurrences):
        candidate_level = CANDIDATE["languages"][code]
        candidate_rank = LEVEL_RANK[candidate_level]

        # Le segment s'arrête avant la prochaine langue détectée.
        next_start = len(norm)
        for j in range(idx + 1, len(occurrences)):
            if occurrences[j][0] > start_pos:
                next_start = occurrences[j][0]
                break

        # On garde aussi un petit contexte avant le nom de la langue pour
        # capter "niveau C1 en anglais".
        segment_start = max(0, start_pos - 45)
        segment_end = min(len(norm), next_start, end_pos + 180)
        segment = norm[segment_start:segment_end]

        if is_optional_context(segment):
            continue

        if code == "nl" and _dutch_is_fr_or_nl_alternative(segment):
            continue

        required_level = None
        explicit_levels = [
            value.upper()
            for value in re.findall(r"\b(a1|a2|b1|b2|c1|c2)\b", segment, re.I)
        ]
        if explicit_levels:
            required_level = max(explicit_levels, key=lambda value: LEVEL_RANK[value])
        elif any(word in segment for word in [
            "native", "mother tongue", "langue maternelle",
            "moedertaal", "perfect", "parfait", "vloeiend",
            "fluent", "courant", "couramment",
        ]):
            required_level = "C1"
        elif code == "nl" and _dutch_professional_requirement_without_cefr(segment):
            required_level = "B2"

        if not required_level or LEVEL_RANK[required_level] <= candidate_rank:
            continue

        implicit_dutch_requirement = bool(
            code == "nl"
            and _dutch_professional_requirement_without_cefr(segment)
        )
        mandatory = bool(
            is_mandatory_context(segment)
            or implicit_dutch_requirement
        )
        level_gap = LEVEL_RANK[required_level] - candidate_rank

        gaps.append({
            "language": code,
            "candidate_level": candidate_level,
            "required_level": required_level,
            "mandatory": mandatory,
            "hard": bool(mandatory and level_gap >= 2),
        })

    # Dédoublonnage : conserve l'écart le plus fort par langue.
    unique = {}
    for gap in gaps:
        key = gap["language"]
        current = unique.get(key)
        if current is None:
            unique[key] = gap
            continue

        current_rank = LEVEL_RANK[current["required_level"]]
        new_rank = LEVEL_RANK[gap["required_level"]]
        if new_rank > current_rank or (new_rank == current_rank and gap["hard"] and not current["hard"]):
            unique[key] = gap

    return list(unique.values())


# ============================================================
# COMPETENCES OBLIGATOIRES
# ============================================================

# Ce dictionnaire ne prétend pas représenter toutes les compétences du CV.
# Il sert uniquement à détecter quelques gaps techniques très explicites.
KNOWN_SKILLS = {
    "python": True,
    "sql": True,
    "power bi": True,
    "r": True,
    "pandas": True,
    "scikit-learn": True,
    "machine learning": True,
    "etl": True,
    "ssis": True,
    "sql server": True,
    "hplc": True,
    "uplc": True,
    "lims": True,
    "sap": True,
    "trackwise": True,
    "gmp": True,
    "glp": False,
    "gc": False,
    "ftir": False,
    "nmr": False,
    "mass spectrometry": False,
    "pcr": False,
    "cell culture": False,
    "azure": False,
    "microsoft fabric": False,
    "databricks": False,
    "spark": False,
    "sas": False,
    "alteryx": False,
}

SKILL_ALIASES = {
    "python": ["python"],
    "sql": ["sql"],
    "power bi": ["power bi"],
    "r": [" r ", "r language", "langage r"],
    "pandas": ["pandas"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "machine learning": ["machine learning", "apprentissage automatique"],
    "etl": ["etl"],
    "ssis": ["ssis", "sql server integration services"],
    "sql server": ["sql server", "mssql"],
    "hplc": ["hplc"],
    "uplc": ["uplc"],
    "lims": ["lims"],
    "sap": ["sap"],
    "trackwise": ["trackwise"],
    "gmp": ["gmp", "bpf"],
    "glp": ["glp", "bpl"],
    "gc": ["gas chromatography", "gaschromatografie", "chromatographie en phase gazeuse"],
    "ftir": ["ftir"],
    "nmr": ["nmr", "rmn"],
    "mass spectrometry": ["mass spectrometry", "spectrometrie de masse", "massaspectrometrie"],
    "pcr": ["pcr"],
    "cell culture": ["cell culture", "culture cellulaire", "celkweek"],
    "azure": ["azure"],
    "microsoft fabric": ["microsoft fabric", "fabric"],
    "databricks": ["databricks"],
    "spark": ["apache spark", "pyspark", " spark "],
    "sas": [" sas "],
    "alteryx": ["alteryx"],
}


def detect_mandatory_skill_gaps(text):
    norm = " " + normalize(text) + " "
    gaps = []

    for skill, aliases in SKILL_ALIASES.items():
        if KNOWN_SKILLS.get(skill, False):
            continue

        for alias in aliases:
            nalias = normalize(alias)
            if not nalias:
                continue
            for match in iter_phrase_matches(norm, nalias):
                window = context_window(norm, match.start(), match.end(), radius=85)
                if is_mandatory_context(window):
                    gaps.append(skill)
                    break
            if skill in gaps:
                break

    return sorted(set(gaps))


# ============================================================
# DECISION
# ============================================================

def gate_priority_score(match_score, status, penalties=0):
    status_bonus = {
        "APPLY": 15,
        "STRETCH": 5,
        "VERIFY": -5,
        "REJECT": -25,
    }[status]
    return round(max(0.0, min(115.0, float(match_score) + status_bonus - penalties)), 1)


def evaluate_application_gate(job, match_result):
    title = clean_text(getattr(job, "title", ""))
    location = clean_text(getattr(job, "location", ""))
    text = job_text(job)
    family = clean_text(match_result.get("best_family"))
    score = float(match_result.get("score", 0) or 0)
    provisional = bool(match_result.get("provisional", False))

    reasons = []
    warnings = []
    hard_reasons = []
    penalties = 0

    source_status = clean_text(
        getattr(job, "source_eligibility_status", "ELIGIBLE")
    ).upper() or "ELIGIBLE"
    source_reason = clean_text(
        getattr(job, "source_eligibility_reason", "")
    )

    # --------------------------------------------------------
    # 1. Source déjà certaine
    # --------------------------------------------------------
    if source_status == "INELIGIBLE":
        hard_reasons.append(source_reason or "Inéligible selon la source")

    # --------------------------------------------------------
    # 1B. Périmètre géographique : candidatures Belgique
    # --------------------------------------------------------
    outside_belgium = detect_outside_belgium(location)
    if outside_belgium:
        hard_reasons.append(
            f"Offre située hors Belgique ({outside_belgium})"
        )

    # --------------------------------------------------------
    # 2. Agrément technologue laboratoire
    # --------------------------------------------------------
    if detect_medical_lab_accreditation_block(title, text):
        hard_reasons.append(
            "Agrément/visa de technologue de laboratoire requis et non détenu"
        )

    # --------------------------------------------------------
    # 2B. Faux ami "laboratoire" hors chimie/QC
    # --------------------------------------------------------
    obvious_domain_mismatch = detect_obvious_domain_mismatch(title, family)
    if obvious_domain_mismatch:
        hard_reasons.append(obvious_domain_mismatch)

    # --------------------------------------------------------
    # 3. Diplôme Master explicitement obligatoire
    # --------------------------------------------------------
    mandatory_master = detect_mandatory_master(text)
    if mandatory_master:
        hard_reasons.append(
            "Master/doctorat explicitement obligatoire alors que les diplômes achevés sont de niveau bachelier"
        )

    # --------------------------------------------------------
    # 4. Seniorité Data structurellement incompatible
    # --------------------------------------------------------
    hard_data_seniority = has_hard_data_seniority(title, family)
    if hard_data_seniority:
        hard_reasons.append(
            "Intitulé Data/BI de niveau senior/lead/architect incompatible avec 0 an d'expérience professionnelle Data"
        )

    # --------------------------------------------------------
    # 5. Expérience demandée
    # --------------------------------------------------------
    exp = detect_required_experience_years(text)
    required_years = exp["mandatory"]
    candidate_years = candidate_professional_years(family)
    experience_gap = None

    if required_years is not None:
        experience_gap = max(0.0, float(required_years) - float(candidate_years))

        if family in DATA_FAMILIES:
            if required_years >= 3:
                hard_reasons.append(
                    f"{required_years} ans d'expérience Data obligatoires pour 0 an professionnel Data"
                )
            elif required_years >= 1:
                warnings.append(
                    f"{required_years} an(s) d'expérience professionnelle Data demandé(s) ; expérience surtout académique/projet"
                )
                penalties += 12 if required_years == 1 else 18

        elif family in CHEMISTRY_FAMILIES:
            if required_years >= 5:
                hard_reasons.append(
                    f"{required_years} ans d'expérience obligatoires pour environ 3 ans d'expérience QC/laboratoire"
                )
            elif required_years == 4:
                warnings.append(
                    "4 ans d'expérience demandés pour environ 3 ans détenus"
                )
                penalties += 10

    # --------------------------------------------------------
    # 5B. Familles Data exigeantes sans expérience pro Data
    # --------------------------------------------------------
    norm_title = normalize(title)
    junior_title = any(marker in norm_title for marker in [
        "junior", "graduate", "trainee", "starter", "debutant", "débutant"
    ])

    if (
        family in {"data_engineering", "business_analysis"}
        and not junior_title
        and CANDIDATE["data_professional_years"] <= 0
        and not hard_data_seniority
    ):
        warnings.append(
            "Famille Data plus exigeante avec 0 an d'expérience professionnelle Data"
        )
        penalties += 8

    # --------------------------------------------------------
    # 6. Langues
    # --------------------------------------------------------
    language_gaps = detect_language_gaps(text)
    for gap in language_gaps:
        language_name = {"fr": "français", "en": "anglais", "nl": "néerlandais"}[gap["language"]]
        message = (
            f"{language_name} {gap['required_level']} demandé ; niveau candidat {gap['candidate_level']}"
        )
        if gap["hard"]:
            hard_reasons.append(message)
        else:
            warnings.append(message)
            penalties += 10

    # --------------------------------------------------------
    # 7. Skills explicitement obligatoires manquants
    # --------------------------------------------------------
    mandatory_skill_gaps = detect_mandatory_skill_gaps(text)
    if mandatory_skill_gaps:
        if len(mandatory_skill_gaps) >= 2:
            hard_reasons.append(
                "Plusieurs compétences techniques explicitement obligatoires non détenues : "
                + ", ".join(mandatory_skill_gaps)
            )
        else:
            warnings.append(
                "Compétence explicitement obligatoire non démontrée : "
                + mandatory_skill_gaps[0]
            )
            penalties += 15

    # --------------------------------------------------------
    # 8. Credential inconnu
    # --------------------------------------------------------
    unknown_credential = detect_unknown_mandatory_credential(text)

    # --------------------------------------------------------
    # 8B. Offre explicitement étudiante
    # --------------------------------------------------------
    student_role = detect_student_role(title)

    # --------------------------------------------------------
    # DECISION PAR PRIORITE
    # --------------------------------------------------------
    if hard_reasons:
        status = "REJECT"

    # Un très faible fit métier ne mérite pas une vérification administrative :
    # on rejette d'abord le hors-cible, même si un certificat est mentionné.
    elif score < 35:
        status = "REJECT"
        hard_reasons.append("Correspondance métier trop faible (<35/100)")

    elif score < 50:
        status = "REJECT"
        hard_reasons.append("Correspondance métier faible (<50/100)")

    elif source_status == "VERIFY":
        status = "VERIFY"
        reasons.append(source_reason or "Éligibilité source à vérifier")

    elif student_role:
        status = "VERIFY"
        reasons.append(
            "Offre explicitement étudiante : statut étudiant à confirmer avant candidature"
        )

    elif unknown_credential:
        status = "VERIFY"
        reasons.append(
            f"Condition/certification obligatoire à vérifier : {unknown_credential}"
        )

    elif provisional:
        status = "VERIFY"
        reasons.append("Description insuffisamment fiable pour autoriser automatiquement une candidature")

    elif warnings:
        status = "STRETCH"

    elif score >= 65:
        status = "APPLY"

    else:
        status = "STRETCH"
        warnings.append("Score métier intermédiaire : candidature à examiner au cas par cas")
        penalties += 5

    if status == "APPLY":
        reasons.append("Aucun blocage fort détecté et correspondance métier suffisante")
    elif status == "STRETCH" and not reasons:
        reasons.append("Candidature possible, mais au moins un écart mérite d'être assumé")
    elif status == "VERIFY" and not reasons:
        reasons.append("Une condition importante doit être confirmée avant candidature")
    elif status == "REJECT" and not reasons:
        reasons.append("Au moins une incompatibilité forte a été détectée")

    priority = gate_priority_score(score, status, penalties)

    return {
        "gate_version": GATE_VERSION,
        "status": status,
        "status_label": STATUS_LABELS[status],
        "priority_score": priority,
        "match_score": score,
        "family": family,
        "reasons": reasons,
        "warnings": warnings,
        "hard_reasons": hard_reasons,
        "source_eligibility_status": source_status,
        "source_eligibility_reason": source_reason or None,
        "mandatory_master_detected": mandatory_master,
        "required_experience_years": required_years,
        "candidate_professional_years": candidate_years,
        "experience_gap_years": experience_gap,
        "language_gaps": language_gaps,
        "mandatory_skill_gaps": mandatory_skill_gaps,
        "unknown_mandatory_credential": unknown_credential,
        "medical_lab_accreditation_block": detect_medical_lab_accreditation_block(title, text),
        "outside_belgium": outside_belgium,
        "student_role": student_role,
        "obvious_domain_mismatch": obvious_domain_mismatch,
        "hard_data_seniority": hard_data_seniority,
        "provisional": provisional,
    }


def gate_sort_key(item):
    job, match_result, gate = item
    return (
        STATUS_ORDER.get(gate["status"], 0),
        gate["priority_score"],
        float(match_result.get("score", 0) or 0),
    )


def apply_application_gate(scored_jobs):
    gated = []
    for job, match_result in scored_jobs:
        gate = evaluate_application_gate(job, match_result)
        gated.append((job, match_result, gate))

    gated.sort(key=gate_sort_key, reverse=True)
    return gated


def partition_gate_results(gated_jobs):
    partitions = {
        "APPLY": [],
        "STRETCH": [],
        "VERIFY": [],
        "REJECT": [],
    }
    for item in gated_jobs:
        partitions[item[2]["status"]].append(item)
    return partitions


def gate_summary(gated_jobs):
    counts = Counter(gate["status"] for _, _, gate in gated_jobs)
    return {
        "total": len(gated_jobs),
        "APPLY": counts.get("APPLY", 0),
        "STRETCH": counts.get("STRETCH", 0),
        "VERIFY": counts.get("VERIFY", 0),
        "REJECT": counts.get("REJECT", 0),
    }


# ============================================================
# EXPORTS
# ============================================================

def _safe_attr(job, name, default=None):
    value = getattr(job, name, default)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def export_application_gate(gated_jobs, project_root):
    root = Path(project_root)
    export_dir = root / "exports" / "logs"
    export_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = export_dir / f"application_gate_v1_{timestamp}.json"
    txt_path = export_dir / f"application_gate_v1_{timestamp}.txt"

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
            "confidence": match_result.get("confidence_label"),
            "gate": gate,
        })

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    partitions = partition_gate_results(gated_jobs)
    summary = gate_summary(gated_jobs)

    lines = []
    lines.append("APPLICATION GATE V1")
    lines.append("=" * 76)
    lines.append(f"Total   : {summary['total']}")
    lines.append(f"APPLY   : {summary['APPLY']}")
    lines.append(f"STRETCH : {summary['STRETCH']}")
    lines.append(f"VERIFY  : {summary['VERIFY']}")
    lines.append(f"REJECT  : {summary['REJECT']}")
    lines.append("")

    for status in ["APPLY", "STRETCH", "VERIFY", "REJECT"]:
        lines.append("=" * 76)
        lines.append(STATUS_LABELS[status])
        lines.append("=" * 76)
        for idx, (job, match_result, gate) in enumerate(partitions[status], start=1):
            lines.append(
                f"{idx:>3}. {match_result.get('score', 0):>5.1f}/100 "
                f"| Gate {gate['priority_score']:>5.1f} | {clean_text(getattr(job, 'title', ''))}"
            )
            lines.append(f"     {clean_text(getattr(job, 'company', ''))}")
            lines.append(f"     {clean_text(getattr(job, 'location', ''))}")
            for reason in gate["hard_reasons"] + gate["warnings"] + gate["reasons"]:
                lines.append(f"     ↳ {reason}")
            lines.append(f"     {clean_text(getattr(job, 'url', ''))}")
            lines.append("")

    txt_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "json_path": json_path,
        "txt_path": txt_path,
        "summary": summary,
    }
