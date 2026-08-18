"""
JOB HUNTER BELGIUM
MATCHER V5.1

Objectif :
évaluer la pertinence RÉELLE d'une candidature.

NOUVEAUTÉS V5.0
================

1. Déduplication conceptuelle des synonymes :
   - procédures / procedures
   - traçabilité / tracabilite / traceability
   - contrôle qualité / controle qualite / quality control
   - etc.

2. Score de confiance :
   - HIGH
   - MEDIUM
   - LOW
   - PRE-SCORE

3. Score provisoire lorsque la description détaillée
   n'a pas pu être récupérée.

4. Plafonds stricts pour les postes Data senior :
   - Senior        -> max 55
   - Lead/Principal -> max 45
   - Manager/Head/Director -> max 35

5. Analyse du domaine pour Quality / Pharma QC :
   - pharma / chimie / laboratoire -> bonus
   - agro / alimentaire -> domaine adjacent
   - mécanique / automobile / textile -> pénalité

6. Expérience explicite :
   - utilisation prioritaire de l'expérience
     PROFESSIONNELLE réelle ;
   - les projets/formation ne deviennent pas artificiellement
     des années d'expérience professionnelle.

7. Les mentions Forem du type :
   "Entre 2 et 5 ans - Non"
   ne sont plus considérées comme une exigence obligatoire.

8. Double diplôme réellement pris en compte :
   - Bachelier en chimie pour Chemistry/Lab/QC/Quality ;
   - spécialisation Business Data Analyst pour Data/BI.

9. Nouvelle famille chemistry_lab :
   - chimie analytique / organique / inorganique / physique ;
   - laboratoire R&D / environnement / industrie ;
   - technicien chimiste / laborantin / analyste laboratoire.

10. Synonymes FR / EN / NL centralisés depuis config.profile.

11. Expérience explicite reconnue aussi en néerlandais.

12. PERFORMANCE : le contexte lexical d'une offre est calculé
    une seule fois puis réutilisé pour toutes les familles.

13. PRÉCISION : les titres génériques production / R&D ne sont
    plus suffisants seuls pour classer une offre Chemistry/Lab.
    Ils exigent une ancre chimie/labo/pharma/QC.

14. Domaines industriels éloignés FR/EN/NL renforcés
    (carrière, mine, métal, construction, électromécanique...).
"""


import re
import unicodedata

from functools import lru_cache


from config.profile import (
    TARGET_JOB_FAMILIES,

    DATA_SKILLS,
    PHARMA_QUALITY_SKILLS,
    LAB_SKILLS,
    BUSINESS_SKILLS,

    EDUCATION_KEYWORDS,

    PREFERRED_LOCATIONS,

    JUNIOR_KEYWORDS,
    SENIOR_KEYWORDS,

    LANGUAGES,

    FAMILY_WEIGHTS,

    EXPERIENCE_PROFILE,

    PROFILE_EDUCATION_BY_FAMILY,
    MULTILINGUAL_CONCEPT_ALIASES,
    CHEMISTRY_LAB_CONTEXTUAL_TITLES,
    CHEMISTRY_LAB_CORE_ANCHORS,

    ACCEPT_ALL_BELGIUM,
)


# ============================================================
# FAMILLES
# ============================================================

DATA_FAMILIES = {
    "data_analytics",
    "business_intelligence",
    "business_analysis",
    "data_engineering",
}


PHARMA_LAB_FAMILIES = {
    "chemistry_lab",
    "pharma_qc",
    "quality",
    "hybrid_data_pharma",
}


# ============================================================
# CONTEXTES SPÉCIAUX
# ============================================================

SPECIAL_KEYWORD_CONTEXTS = {
    "r": [
        "rstudio",
        "r studio",
        "r programming",
        "langage r",
        "programmation r",
        "r language",
        "python and r",
        "sql and r",
    ],
}


# ============================================================
# SENIORITÉ
# ============================================================

SENIOR_ONLY_KEYWORDS = [
    "senior",
]


LEAD_KEYWORDS = [
    "lead",
    "principal",
]


MANAGEMENT_KEYWORDS = [
    "manager",
    "head",
    "head of",
    "director",
    "directeur",
    "directrice",
    "responsable",
]


# ============================================================
# NORMALISATION
# ============================================================

@lru_cache(maxsize=100000)
def normalize_text(value):

    if value is None:
        return ""

    value = str(value).lower()

    value = unicodedata.normalize(
        "NFKD",
        value
    )

    value = "".join(
        character
        for character in value
        if not unicodedata.combining(
            character
        )
    )

    value = re.sub(
        r"[^a-z0-9+#]+",
        " ",
        value
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()

    return value


# ============================================================
# CONCEPTS ÉQUIVALENTS
# ============================================================

CONCEPT_ALIASES = {

    # --------------------------------------------------------
    # QUALITY
    # --------------------------------------------------------

    "quality_control": [
        "contrôle qualité",
        "controle qualite",
        "quality control",
    ],

    "quality_assurance": [
        "assurance qualité",
        "assurance qualite",
        "quality assurance",
    ],

    "procedures": [
        "procédure",
        "procedure",
        "procédures",
        "procedures",
        "sop",
    ],

    "traceability": [
        "traçabilité",
        "tracabilite",
        "traceability",
    ],

    "compliance": [
        "conformité",
        "conformite",
        "compliance",
    ],

    "deviation": [
        "deviation",
        "deviations",
        "déviation",
        "déviations",
    ],

    "investigation": [
        "investigation",
        "investigations",
    ],

    "audit": [
        "audit",
        "audits",
    ],

    "continuous_improvement": [
        "amélioration continue",
        "amelioration continue",
        "continuous improvement",
    ],

    "gmp": [
        "gmp",
        "bpf",
        "bonnes pratiques de fabrication",
        "good manufacturing practices",
    ],

    "data_integrity": [
        "data integrity",
        "intégrité des données",
        "integrite des donnees",
    ],


    # --------------------------------------------------------
    # LABORATOIRE
    # --------------------------------------------------------

    "stability": [
        "stabilité",
        "stabilite",
        "stability",
    ],

    "chromatography": [
        "chromatographie",
        "chromatography",
    ],

    "raw_materials": [
        "matières premières",
        "matieres premieres",
        "raw materials",
    ],

    "finished_products": [
        "produits finis",
        "finished products",
    ],

    "sample_preparation": [
        "préparation d'échantillons",
        "preparation d echantillons",
        "sample preparation",
    ],

    "sampling": [
        "échantillonnage",
        "echantillonnage",
        "sampling",
    ],

    "analytical_chemistry": [
        "chimie analytique",
        "analytical chemistry",
    ],

    "physico_chemical": [
        "analyse physico-chimique",
        "analyse physico chimique",
        "physico-chemical analysis",
        "physicochemical analysis",
        "physico chemistry",
    ],

    "microbiology": [
        "microbiologie",
        "microbiology",
    ],

    "endotoxin": [
        "endotoxines",
        "endotoxin",
        "endotoxins",
        "endosafe",
        "endosafe mcs",
    ],

    "aseptic": [
        "asepsie",
        "aseptic",
        "aseptic technique",
    ],

    "cleanroom": [
        "cleanroom",
        "clean room",
        "zone propre",
        "salle blanche",
    ],

    "conductivity": [
        "conductivité",
        "conductivite",
        "conductivity",
    ],

    "method_validation": [
        "validation analytique",
        "analytical validation",
        "validation de méthode",
        "validation de methode",
        "method validation",
    ],


    # --------------------------------------------------------
    # DATA
    # --------------------------------------------------------

    "business_intelligence": [
        "business intelligence",
        "bi",
    ],

    "dashboard": [
        "dashboard",
        "dashboards",
    ],

    "data_analysis": [
        "data analysis",
        "data analytics",
        "analyse de données",
        "analyse des données",
    ],

    "statistics": [
        "statistics",
        "statistical analysis",
        "statistiques",
    ],

    "data_pipeline": [
        "data pipeline",
        "data pipelines",
    ],

    "predictive_modeling": [
        "predictive modeling",
        "predictive modelling",
    ],

    "cross_validation": [
        "cross validation",
        "cross-validation",
    ],


    # --------------------------------------------------------
    # LANGUES
    # --------------------------------------------------------

    "language_french": [
        "français",
        "francais",
        "french",
        "fr",
    ],

    "language_english": [
        "anglais",
        "english",
        "en",
    ],

    "language_dutch": [
        "néerlandais",
        "neerlandais",
        "dutch",
        "nederlands",
        "nl",
    ],
}


# ============================================================
# ALIASES TRILINGUES DU PROFIL V5
# ============================================================

# Si une clé V5 correspond à un concept déjà existant,
# on enrichit ce concept au lieu d'en créer un second.
#
# Exemple :
# chem_quality_control -> quality_control
#
# Ainsi FR / EN / NL restent un SEUL concept et ne
# donnent jamais plusieurs fois des points pour le même savoir-faire.

for multilingual_key, multilingual_aliases in (
    MULTILINGUAL_CONCEPT_ALIASES.items()
):

    base_key = multilingual_key

    for prefix in (
        "chem_",
        "data_",
    ):

        if base_key.startswith(
            prefix
        ):

            base_key = base_key[
                len(prefix):
            ]

            break


    target_key = (
        base_key

        if base_key in CONCEPT_ALIASES

        else multilingual_key
    )


    existing = list(
        CONCEPT_ALIASES.get(
            target_key,
            []
        )
    )


    CONCEPT_ALIASES[
        target_key
    ] = list(
        dict.fromkeys(
            existing
            +
            list(
                multilingual_aliases
            )
        )
    )


CONCEPT_LABELS = {
    "quality_control":
        "contrôle qualité",

    "quality_assurance":
        "assurance qualité",

    "procedures":
        "procédures / SOP",

    "traceability":
        "traçabilité",

    "compliance":
        "conformité",

    "deviation":
        "déviations",

    "investigation":
        "investigations",

    "audit":
        "audits",

    "continuous_improvement":
        "amélioration continue",

    "gmp":
        "GMP / BPF",

    "data_integrity":
        "data integrity",

    "stability":
        "stabilité",

    "chromatography":
        "chromatographie",

    "raw_materials":
        "matières premières",

    "finished_products":
        "produits finis",

    "sample_preparation":
        "préparation d'échantillons",

    "sampling":
        "échantillonnage",

    "analytical_chemistry":
        "chimie analytique",

    "physico_chemical":
        "analyse physico-chimique",

    "microbiology":
        "microbiologie",

    "endotoxin":
        "endotoxines / Endosafe",

    "aseptic":
        "asepsie",

    "cleanroom":
        "salle blanche / cleanroom",

    "conductivity":
        "conductivité",

    "method_validation":
        "validation analytique",

    "business_intelligence":
        "business intelligence",

    "dashboard":
        "dashboards",

    "data_analysis":
        "analyse de données",

    "statistics":
        "statistiques",

    "data_pipeline":
        "data pipelines",

    "predictive_modeling":
        "predictive modeling",

    "cross_validation":
        "cross-validation",

    "language_french":
        "français",

    "language_english":
        "anglais",

    "language_dutch":
        "néerlandais",
}


_ALIAS_TO_CONCEPT = None


def build_alias_map():

    global _ALIAS_TO_CONCEPT

    if _ALIAS_TO_CONCEPT is not None:
        return _ALIAS_TO_CONCEPT

    mapping = {}

    for concept, aliases in (
        CONCEPT_ALIASES.items()
    ):

        for alias in aliases:

            normalized = normalize_text(
                alias
            )

            mapping[
                normalized
            ] = concept

    _ALIAS_TO_CONCEPT = mapping

    return mapping


def get_concept_key(keyword):

    normalized = normalize_text(
        keyword
    )

    alias_map = build_alias_map()

    return alias_map.get(
        normalized,
        normalized
    )


def get_concept_label(keyword):

    concept = get_concept_key(
        keyword
    )

    return CONCEPT_LABELS.get(
        concept,
        keyword
    )


# ============================================================
# RECHERCHE MOT-CLÉ
# ============================================================

def keyword_in_text(
    keyword,
    text
):

    normalized_keyword = normalize_text(
        keyword
    )

    normalized_text = normalize_text(
        text
    )

    if not normalized_keyword:
        return False


    # --------------------------------------------------------
    # LANGAGE R
    # --------------------------------------------------------

    if normalized_keyword == "r":

        for context in (
            SPECIAL_KEYWORD_CONTEXTS[
                "r"
            ]
        ):

            if normalize_text(
                context
            ) in normalized_text:

                return True

        return False


    padded_text = (
        f" {normalized_text} "
    )

    padded_keyword = (
        f" {normalized_keyword} "
    )

    return (
        padded_keyword
        in padded_text
    )


# ============================================================
# MATCHS DÉDUPLIQUÉS
# ============================================================

def find_matches(
    text,
    keywords
):
    """
    Retourne des concepts uniques.

    Exemple :
    procédures + procedures
    => un seul résultat.
    """

    matches = []

    seen_concepts = set()


    for keyword in keywords:

        if not keyword_in_text(
            keyword,
            text
        ):
            continue


        concept = get_concept_key(
            keyword
        )


        if concept in seen_concepts:
            continue


        seen_concepts.add(
            concept
        )


        matches.append(
            get_concept_label(
                keyword
            )
        )


    return matches


# ============================================================
# TEXTE JOB
# ============================================================

def build_job_text(job):

    fields = [
        job.title,
        job.company,
        job.location,
        job.description,
        job.contract_type,
        job.language,
    ]

    return " ".join(
        str(field)
        for field in fields
        if field
    )


def build_education_text(job):
    """
    Évite qu'un titre comme :

    Data Analyst
    Master Data Officer

    soit automatiquement interprété comme
    une formation compatible.
    """

    text = (
        job.description
        or ""
    )

    title = (
        job.title
        or ""
    )


    if title:

        try:

            text = re.sub(
                re.escape(title),
                " ",
                text,
                flags=re.IGNORECASE
            )

        except Exception:
            pass


    return text


# ============================================================
# LANGUES
# ============================================================

def get_profile_language_keywords():

    keywords = []

    # Les codes FR / EN / NL sont trop courts :
    # "en" est notamment une préposition française.
    # On garde donc uniquement les noms de langues explicites
    # pour éviter des faux positifs systématiques.

    unsafe_short_codes = {
        "fr",
        "en",
        "nl",
    }


    for language_data in (
        LANGUAGES.values()
    ):

        for keyword in (
            language_data[
                "keywords"
            ]
        ):

            if normalize_text(
                keyword
            ) in unsafe_short_codes:

                continue


            keywords.append(
                keyword
            )


    return list(
        dict.fromkeys(
            keywords
        )
    )


# ============================================================
# BELGIQUE
# ============================================================

def is_belgian_job(job):

    location_text = (
        job.location
        or ""
    )

    belgium_keywords = [
        "belgique",
        "belgium",
        "belgie",

        "region wallonne",
        "region flamande",

        "region de bruxelles capitale",
        "brussels capital",
        "brussels hoofdstedelijk gewest",
    ]


    normalized_location = normalize_text(
        location_text
    )


    for keyword in belgium_keywords:

        if normalize_text(
            keyword
        ) in normalized_location:

            return True


    return False


# ============================================================
# SCORE DE COMPÉTENCES
# ============================================================

def calculate_skill_score(
    matched_skills,
    weight,
    saturation
):

    if weight <= 0:
        return 0

    if not matched_skills:
        return 0


    ratio = min(
        len(
            matched_skills
        ) / saturation,
        1
    )


    return (
        weight
        *
        ratio
    )


# ============================================================
# EXPÉRIENCE DEMANDÉE
# ============================================================

def requirement_is_marked_optional(
    normalized_text,
    match
):
    """
    Forem peut contenir :

    Entre 2 et 5 ans - Non

    où "Non" signifie que l'expérience
    n'est PAS une exigence obligatoire.
    """

    after = normalized_text[
        match.end():
        match.end() + 35
    ]


    optional_patterns = [
        r"^\s*non\b",
        r"^\s*not required\b",
        r"^\s*niet verplicht\b",
        r"^\s*niet vereist\b",
        r"^\s*neen\b",
    ]


    for pattern in optional_patterns:

        if re.search(
            pattern,
            after
        ):

            return True


    return False


def parse_required_experience(
    text
):

    normalized = normalize_text(
        text
    )


    results = []


    # --------------------------------------------------------
    # FOURCHETTES
    # --------------------------------------------------------

    range_patterns = [
        r"entre\s+(\d+)\s+et\s+(\d+)\s+ans",
        r"(\d+)\s+a\s+(\d+)\s+ans",
        r"(\d+)\s+to\s+(\d+)\s+years",
        r"tussen\s+(\d+)\s+en\s+(\d+)\s+jaar",
        r"(\d+)\s+tot\s+(\d+)\s+jaar",
    ]


    for pattern in range_patterns:

        for match in re.finditer(
            pattern,
            normalized
        ):

            if requirement_is_marked_optional(
                normalized,
                match
            ):
                continue


            minimum = int(
                match.group(1)
            )

            maximum = int(
                match.group(2)
            )


            if (
                0 <= minimum <= 20
                and
                minimum <= maximum <= 20
            ):

                results.append(
                    (
                        minimum,
                        maximum
                    )
                )


    # --------------------------------------------------------
    # MINIMUM
    # --------------------------------------------------------

    minimum_patterns = [
        r"minimum\s+(\d+)\s+ans",
        r"au\s+moins\s+(\d+)\s+ans",
        r"min\s+(\d+)\s+ans",
        r"(\d+)\s+ans\s+d\s+experience",
        r"(\d+)\s+years\s+of\s+experience",
        r"at\s+least\s+(\d+)\s+years",
        r"minimum\s+(\d+)\s+jaar",
        r"minstens\s+(\d+)\s+jaar",
        r"(\d+)\s+jaar\s+ervaring",
    ]


    for pattern in minimum_patterns:

        for match in re.finditer(
            pattern,
            normalized
        ):

            if requirement_is_marked_optional(
                normalized,
                match
            ):
                continue


            minimum = int(
                match.group(1)
            )


            if 0 <= minimum <= 20:

                results.append(
                    (
                        minimum,
                        None
                    )
                )


    if not results:

        return {
            "found": False,
            "minimum": None,
            "maximum": None,
        }


    results.sort(
        key=lambda item: item[0],
        reverse=True
    )


    minimum, maximum = (
        results[0]
    )


    return {
        "found": True,
        "minimum": minimum,
        "maximum": maximum,
    }


# ============================================================
# JUNIOR / SENIOR
# ============================================================

def has_junior_signal(
    text
):

    return bool(
        find_matches(
            text,
            JUNIOR_KEYWORDS
        )
    )


def find_raw_matches(
    text,
    keywords
):
    """
    Pour les niveaux de séniorité,
    on veut conserver les mots exacts.
    """

    result = []

    for keyword in keywords:

        if keyword_in_text(
            keyword,
            text
        ):

            result.append(
                keyword
            )

    return result


# ============================================================
# PLAFOND DATA SENIOR
# ============================================================

def get_data_seniority_cap(
    family_name,
    title,
    experience_requirement
):

    if family_name not in DATA_FAMILIES:

        return {
            "cap": None,
            "reason": None,
        }


    manager_matches = (
        find_raw_matches(
            title,
            MANAGEMENT_KEYWORDS
        )
    )


    lead_matches = (
        find_raw_matches(
            title,
            LEAD_KEYWORDS
        )
    )


    senior_matches = (
        find_raw_matches(
            title,
            SENIOR_ONLY_KEYWORDS
        )
    )


    # --------------------------------------------------------
    # MANAGEMENT
    # --------------------------------------------------------

    if manager_matches:

        return {
            "cap": 35,
            "reason": (
                "poste Data de niveau management"
            ),
        }


    # --------------------------------------------------------
    # LEAD / PRINCIPAL
    # --------------------------------------------------------

    if lead_matches:

        return {
            "cap": 45,
            "reason": (
                "poste Data Lead/Principal"
            ),
        }


    # --------------------------------------------------------
    # SENIOR
    # --------------------------------------------------------

    if senior_matches:

        return {
            "cap": 55,
            "reason": (
                "poste explicitement Senior"
            ),
        }


    # --------------------------------------------------------
    # ANNÉES EXPLICITES
    # --------------------------------------------------------

    if experience_requirement[
        "found"
    ]:

        minimum = (
            experience_requirement[
                "minimum"
            ]
        )


        if minimum >= 5:

            return {
                "cap": 50,
                "reason": (
                    f"{minimum}+ ans d'expérience "
                    f"demandés en Data"
                ),
            }


        if minimum >= 4:

            return {
                "cap": 58,
                "reason": (
                    f"{minimum}+ ans d'expérience "
                    f"demandés en Data"
                ),
            }


        if minimum >= 3:

            return {
                "cap": 65,
                "reason": (
                    f"{minimum}+ ans d'expérience "
                    f"demandés en Data"
                ),
            }


    return {
        "cap": None,
        "reason": None,
    }


# ============================================================
# EXPÉRIENCE
# ============================================================

def evaluate_experience_fit(
    family_name,
    title,
    full_text,
    weight
):

    profile = (
        EXPERIENCE_PROFILE[
            family_name
        ]
    )


    professional_years = float(
        profile[
            "professional_years"
        ]
    )


    effective_years = float(
        profile[
            "effective_years"
        ]
    )


    requirement = (
        parse_required_experience(
            full_text
        )
    )


    junior_signal = (
        has_junior_signal(
            full_text
        )
    )


    senior_matches = (
        find_raw_matches(
            title,
            SENIOR_KEYWORDS
        )
    )


    reasons = []

    penalty = 0


    # ========================================================
    # EXIGENCE EXPLICITE
    # ========================================================

    if requirement[
        "found"
    ]:

        candidate_years = (
            professional_years
        )


        minimum = (
            requirement[
                "minimum"
            ]
        )


        if candidate_years >= minimum:

            score = weight

            reasons.append(
                (
                    "Expérience professionnelle compatible : "
                    f"{candidate_years:g} an(s) "
                    f"vs minimum {minimum} an(s)"
                )
            )


        else:

            gap = (
                minimum
                -
                candidate_years
            )


            if gap <= 1:

                score = (
                    weight
                    *
                    0.65
                )


            elif gap <= 2:

                score = (
                    weight
                    *
                    0.35
                )


            else:

                score = 0


            reasons.append(
                (
                    "Expérience professionnelle inférieure : "
                    f"{candidate_years:g} an(s) "
                    f"vs {minimum} demandé(s)"
                )
            )


            if family_name in DATA_FAMILIES:

                if gap >= 3:
                    penalty += 15

                elif gap >= 2:
                    penalty += 8

                elif gap >= 1:
                    penalty += 3


            else:

                if gap >= 3:
                    penalty += 8

                elif gap >= 2:
                    penalty += 4

                elif gap >= 1:
                    penalty += 1


    # ========================================================
    # PAS D'EXIGENCE CLAIRE
    # ========================================================

    else:

        candidate_years = (
            effective_years
        )


        if junior_signal:

            score = weight

            reasons.append(
                (
                    "Niveau junior / première expérience "
                    "compatible"
                )
            )


        elif senior_matches:

            score = (
                weight
                *
                0.25
            )


        else:

            score = (
                weight
                *
                0.75
            )


    return {
        "score":
            score,

        "penalty":
            penalty,

        "required":
            requirement,

        "candidate_years":
            candidate_years,

        "senior_matches":
            senior_matches,

        "reasons":
            reasons,
    }


# ============================================================
# DOMAINE PHARMA / LABO
# ============================================================

STRONG_PHARMA_LAB_DOMAIN_KEYWORDS = [
    "pharma",
    "pharmaceutical",
    "pharmaceutique",
    "farmaceutisch",

    "biopharma",
    "biotech",
    "biotechnology",
    "biotechnologie",

    "laboratoire",
    "laboratory",
    "laboratorium",
    "lab",

    "laborantin",
    "laborant",
    "laboratory technician",
    "lab technician",
    "laboratoriumtechnicus",
    "technisch laborant",

    "technicien chimiste",
    "chemical technician",
    "chemisch technicus",

    "chimie",
    "chemistry",
    "chemie",
    "chemical",
    "chemisch",

    "microbiologie",
    "microbiology",

    "hplc",
    "uplc",
    "chromatographie",
    "chromatography",
    "chromatografie",

    "gmp",
    "bpf",

    "lims",

    "médical",
    "medical",
    "medisch",

    "diagnostic",
    "diagnostiek",

    "life sciences",
    "levenswetenschappen",

    "analytical chemistry",
    "chimie analytique",
    "analytische chemie",

    "industrial chemistry",
    "chimie industrielle",
    "industriële chemie",
]


ADJACENT_DOMAIN_KEYWORDS = [
    "agroalimentaire",
    "alimentaire",
    "food",
    "beverage",
    "boisson",
    "voeding",
    "voedingsindustrie",

    "cosmétique",
    "cosmetique",
    "cosmetics",
    "cosmetica",

    "eau",
    "water",
    "wateranalyse",

    "environnement",
    "environment",
    "milieu",
    "milieuchemie",
]


OFF_DOMAIN_QUALITY_KEYWORDS = [
    "automobile",
    "automotive",

    "mécanique",
    "mecanique",
    "mechanical",

    "usinage",
    "machining",

    "soudure",
    "welding",

    "métallurgie",
    "metallurgie",
    "metalworking",

    "textile",

    "construction",

    "électricité industrielle",
    "electricite industrielle",

    "électromécanique",
    "electromecanique",
    "electromechanical",
    "elektromechanica",
    "elektromechanisch",

    "carrière",
    "carriere",
    "quarry",
    "groeve",

    "mine",
    "mining",
    "mineur",
    "miner",
    "mijnbouw",

    "forage",
    "foreur",
    "drilling",
    "boorwerken",

    "ciment",
    "cement",
    "chaux",
    "lime",

    "métal",
    "metal",
    "metaal",
    "metaalindustrie",

    "mechanica",
    "mechanisch",
    "lassen",
    "laswerk",
    "textiel",
    "bouw",
    "bouwsector",
]


def evaluate_domain_fit(
    family_name,
    full_text
):

    if family_name not in PHARMA_LAB_FAMILIES:

        return {
            "adjustment": 0,
            "level": "not_applicable",
            "matches": [],
            "reasons": [],
        }


    strong_matches = (
        find_raw_matches(
            full_text,
            STRONG_PHARMA_LAB_DOMAIN_KEYWORDS
        )
    )


    adjacent_matches = (
        find_raw_matches(
            full_text,
            ADJACENT_DOMAIN_KEYWORDS
        )
    )


    off_matches = (
        find_raw_matches(
            full_text,
            OFF_DOMAIN_QUALITY_KEYWORDS
        )
    )


    reasons = []


    # ========================================================
    # DOMAINE FORT
    # ========================================================

    if strong_matches:

        adjustment = 6

        level = "strong"

        reasons.append(
            (
                "Domaine Pharma/Laboratoire cohérent : "
                +
                ", ".join(
                    strong_matches[:4]
                )
            )
        )


        if off_matches:

            adjustment = 2

            reasons.append(
                (
                    "Quelques signaux industriels éloignés : "
                    +
                    ", ".join(
                        off_matches[:3]
                    )
                )
            )


    # ========================================================
    # DOMAINE ADJACENT
    # ========================================================

    elif adjacent_matches:

        adjustment = 2

        level = "adjacent"

        reasons.append(
            (
                "Domaine adjacent transférable : "
                +
                ", ".join(
                    adjacent_matches[:3]
                )
            )
        )


    # ========================================================
    # DOMAINE ÉLOIGNÉ
    # ========================================================

    elif off_matches:

        adjustment = -15

        level = "off_domain"

        reasons.append(
            (
                "⚠️ Quality/QC dans un domaine éloigné : "
                +
                ", ".join(
                    off_matches[:4]
                )
            )
        )


    # ========================================================
    # DOMAINE INCONNU
    # ========================================================

    else:

        adjustment = 0

        level = "unknown"


    return {
        "adjustment":
            adjustment,

        "level":
            level,

        "matches":
            (
                strong_matches
                or
                adjacent_matches
                or
                off_matches
            ),

        "reasons":
            reasons,
    }


# ============================================================
# SIGNAL MÉTIER
# ============================================================

def has_core_relevance(
    family_name,
    title_matches,
    data_matches,
    pharma_matches,
    lab_matches,
    business_matches,
    contextual_title_matches=None,
    chemistry_anchor_matches=None
):

    contextual_title_matches = (
        contextual_title_matches
        or []
    )

    chemistry_anchor_matches = (
        chemistry_anchor_matches
        or []
    )

    if title_matches:
        return True


    if family_name in {
        "data_analytics",
        "business_intelligence",
        "data_engineering",
    }:

        return (
            len(
                data_matches
            )
            >= 2
        )


    if family_name == "business_analysis":

        return (
            len(
                business_matches
            ) >= 2
            or
            (
                len(
                    data_matches
                ) >= 1
                and
                len(
                    business_matches
                ) >= 1
            )
        )


    if family_name == "chemistry_lab":

        # V5.1 : un mot de procédé générique comme
        # "extraction" ou "distillation" ne suffit plus.
        # Il faut une ancre explicite chimie/labo/pharma/QC.
        anchor_ok = bool(
            chemistry_anchor_matches
        )

        contextual_title_ok = (
            bool(
                contextual_title_matches
            )
            and
            anchor_ok
        )

        skill_signal = (
            len(
                lab_matches
            ) >= 1
            or
            len(
                pharma_matches
            ) >= 1
        )

        return (
            contextual_title_ok
            or
            (
                anchor_ok
                and
                skill_signal
            )
        )


    if family_name == "pharma_qc":

        # V5.1 : même principe de précision que Chemistry/Lab.
        # Une technique de procédé isolée (ex. extraction) ne
        # suffit pas à qualifier une offre Pharma/QC.
        anchor_ok = bool(
            chemistry_anchor_matches
        )

        return (
            anchor_ok
            and
            (
                (
                    len(
                        lab_matches
                    ) >= 1
                    and
                    len(
                        pharma_matches
                    ) >= 1
                )
                or
                len(
                    lab_matches
                ) >= 2
                or
                len(
                    pharma_matches
                ) >= 2
            )
        )


    if family_name == "quality":

        return (
            len(
                pharma_matches
            )
            >= 2
        )


    if family_name == "hybrid_data_pharma":

        return (
            (
                len(
                    data_matches
                ) >= 1
                and
                len(
                    pharma_matches
                ) >= 1
            )
            or
            (
                len(
                    data_matches
                ) >= 1
                and
                len(
                    lab_matches
                ) >= 1
            )
        )


    return False


# ============================================================
# BONUS DE COHÉRENCE
# ============================================================

def calculate_domain_bonus(
    family_name,
    title_matches,
    data_matches,
    pharma_matches,
    lab_matches,
    business_matches
):

    bonus = 0


    if family_name == "chemistry_lab":

        # Un intitulé directement aligné avec le bachelier
        # en chimie (laborantin, technicien chimiste,
        # technicien laboratoire, laboratory analyst, ...)
        # est déjà un signal métier fort, même si
        # l'annonce détaillée est très courte.

        if title_matches:

            bonus += 7


        if len(
            lab_matches
        ) >= 1:

            bonus += 4


        if len(
            lab_matches
        ) >= 3:

            bonus += 3


        if len(
            pharma_matches
        ) >= 2:

            bonus += 2


    elif family_name == "pharma_qc":

        if (
            title_matches
            and
            len(
                lab_matches
            ) >= 1
            and
            len(
                pharma_matches
            ) >= 1
        ):

            bonus += 7


        if len(
            lab_matches
        ) >= 3:

            bonus += 4


        if len(
            pharma_matches
        ) >= 3:

            bonus += 3


    elif family_name == "quality":

        if (
            title_matches
            and
            len(
                pharma_matches
            ) >= 3
        ):

            bonus += 6


        if len(
            lab_matches
        ) >= 2:

            bonus += 3


    elif family_name in DATA_FAMILIES:

        # La spécialisation Business Data Analyst est une
        # qualification directe pour un intitulé Data/BI
        # junior, même si l'annonce est peu détaillée.
        # Les plafonds Senior/Lead/Manager restent appliqués
        # plus loin et empêchent tout gonflement artificiel.

        if title_matches:

            bonus += 7


        if len(
            data_matches
        ) >= 4:

            bonus += 3


    elif family_name == "hybrid_data_pharma":

        if (
            len(
                data_matches
            ) >= 2
            and
            (
                len(
                    pharma_matches
                ) >= 2
                or
                len(
                    lab_matches
                ) >= 2
            )
        ):

            bonus += 7


    return bonus


# ============================================================
# CONFIANCE DES DONNÉES
# ============================================================

def evaluate_confidence(job):
    """
    Détermine si le score est calculé
    sur une annonce réellement enrichie.
    """

    attempted = getattr(
        job,
        "detail_enrichment_attempted",
        False
    )


    # Pré-scoring avant appel DetailOffre.
    if not attempted:

        return {
            "level":
                "PRE-SCORE",

            "label":
                "Pré-score",

            "rank":
                0,

            "provisional":
                False,

            "reason":
                "Analyse avant enrichissement détaillé.",
        }


    success = getattr(
        job,
        "detail_enrichment_success",
        False
    )


    if not success:

        return {
            "level":
                "LOW",

            "label":
                "Faible",

            "rank":
                1,

            "provisional":
                True,

            "reason":
                (
                    "Description détaillée "
                    "non récupérée."
                ),
        }


    detail_length = int(
        getattr(
            job,
            "detail_matching_text_length",
            0
        )
        or 0
    )


    if detail_length >= 700:

        return {
            "level":
                "HIGH",

            "label":
                "Élevée",

            "rank":
                3,

            "provisional":
                False,

            "reason":
                (
                    "Description détaillée "
                    "suffisamment complète."
                ),
        }


    if detail_length >= 250:

        return {
            "level":
                "MEDIUM",

            "label":
                "Moyenne",

            "rank":
                2,

            "provisional":
                False,

            "reason":
                (
                    "Description détaillée "
                    "disponible mais relativement courte."
                ),
        }


    return {
        "level":
            "LOW",

        "label":
            "Faible",

        "rank":
            1,

        "provisional":
            True,

        "reason":
            (
                "Description détaillée "
                "trop courte pour un score fiable."
            ),
    }


# ============================================================
# FORMATION
# ============================================================

def get_education_matches(job):

    education_text = (
        build_education_text(
            job
        )
    )


    # Élimine les termes qui sont surtout
    # des intitulés de poste.
    ignored = {
        "data analyst",
        "business data analyst",
        "business intelligence",
    }


    filtered_keywords = [
        keyword
        for keyword in EDUCATION_KEYWORDS
        if normalize_text(
            keyword
        )
        not in {
            normalize_text(
                ignored_keyword
            )
            for ignored_keyword
            in ignored
        }
    ]


    return find_matches(
        education_text,
        filtered_keywords
    )


# ============================================================
# CONTEXTE LEXICAL PARTAGÉ V5.1
# ============================================================

def build_job_match_context(job):
    """
    Calcule une seule fois les recherches lexicales communes
    à toutes les familles.

    V5.0 recalculait DATA_SKILLS / LAB_SKILLS / etc. pour
    chaque famille, ce qui devenait très coûteux avec la
    banque trilingue.
    """

    title_text = (
        job.title
        or ""
    )

    full_text = (
        build_job_text(
            job
        )
    )

    location_text = (
        job.location
        or ""
    )

    return {
        "title_text":
            title_text,

        "full_text":
            full_text,

        "location_text":
            location_text,

        "data_matches":
            find_matches(
                full_text,
                DATA_SKILLS
            ),

        "pharma_matches":
            find_matches(
                full_text,
                PHARMA_QUALITY_SKILLS
            ),

        "lab_matches":
            find_matches(
                full_text,
                LAB_SKILLS
            ),

        "business_matches":
            find_matches(
                full_text,
                BUSINESS_SKILLS
            ),

        "education_matches":
            get_education_matches(
                job
            ),

        "location_matches":
            find_matches(
                location_text,
                PREFERRED_LOCATIONS
            ),

        "belgian_job":
            is_belgian_job(
                job
            ),

        "language_matches":
            find_matches(
                full_text,
                get_profile_language_keywords()
            ),

        "chemistry_contextual_title_matches":
            find_matches(
                title_text,
                CHEMISTRY_LAB_CONTEXTUAL_TITLES
            ),

        "chemistry_anchor_matches":
            find_raw_matches(
                full_text,
                CHEMISTRY_LAB_CORE_ANCHORS
            ),
    }


# ============================================================
# ÉVALUATION FAMILLE
# ============================================================

def evaluate_family(
    job,
    family_name,
    context=None
):

    weights = (
        FAMILY_WEIGHTS[
            family_name
        ]
    )


    if context is None:

        context = (
            build_job_match_context(
                job
            )
        )


    title_text = context[
        "title_text"
    ]


    full_text = context[
        "full_text"
    ]


    location_text = context[
        "location_text"
    ]


    reasons = []


    # ========================================================
    # TITRE
    # ========================================================

    title_matches = (
        find_matches(
            title_text,
            TARGET_JOB_FAMILIES[
                family_name
            ]
        )
    )


    title_score = (
        weights[
            "job_title"
        ]
        if title_matches
        else 0
    )


    contextual_title_matches = []
    chemistry_anchor_matches = []


    if family_name in {
        "chemistry_lab",
        "pharma_qc",
    }:

        chemistry_anchor_matches = context[
            "chemistry_anchor_matches"
        ]


    if family_name == "chemistry_lab":

        contextual_title_matches = context[
            "chemistry_contextual_title_matches"
        ]

        if (
            not title_matches
            and
            contextual_title_matches
            and
            chemistry_anchor_matches
        ):

            # Titre générique mais contexte métier prouvé.
            title_score = (
                weights[
                    "job_title"
                ]
                *
                0.65
            )


    # ========================================================
    # DATA
    # ========================================================

    data_matches = context[
        "data_matches"
    ]


    data_score = (
        calculate_skill_score(
            data_matches,
            weights[
                "data_skills"
            ],
            saturation=4
        )
    )


    # ========================================================
    # PHARMA QUALITY
    # ========================================================

    pharma_matches = context[
        "pharma_matches"
    ]


    pharma_score = (
        calculate_skill_score(
            pharma_matches,
            weights[
                "pharma_skills"
            ],
            saturation=5
        )
    )


    # ========================================================
    # LAB
    # ========================================================

    lab_matches = context[
        "lab_matches"
    ]


    lab_score = (
        calculate_skill_score(
            lab_matches,
            weights[
                "lab_skills"
            ],
            saturation=3
        )
    )


    # ========================================================
    # BUSINESS
    # ========================================================

    business_matches = context[
        "business_matches"
    ]


    business_score = (
        calculate_skill_score(
            business_matches,
            weights[
                "business_skills"
            ],
            saturation=4
        )
    )


    # ========================================================
    # FORMATION
    # ========================================================

    education_matches = context[
        "education_matches"
    ]


    profile_education = (
        PROFILE_EDUCATION_BY_FAMILY.get(
            family_name,
            {}
        )
    )


    profile_qualified = bool(
        profile_education.get(
            "qualified",
            False
        )
    )


    profile_education_label = (
        profile_education.get(
            "label"
        )
    )


    # ========================================================
    # CORE RELEVANCE
    # ========================================================

    core_relevance = (
        has_core_relevance(
            family_name,
            title_matches,
            data_matches,
            pharma_matches,
            lab_matches,
            business_matches,
            contextual_title_matches,
            chemistry_anchor_matches
        )
    )


    # Le score de formation dépend de la formation RÉELLEMENT
    # possédée par le candidat, pas uniquement de la présence
    # du mot "bachelier" dans l'annonce.
    education_score = (
        weights[
            "education"
        ]
        if (
            core_relevance
            and
            profile_qualified
        )
        else 0
    )


    # ========================================================
    # LOCALISATION
    # ========================================================

    location_matches = context[
        "location_matches"
    ]


    belgian_job = context[
        "belgian_job"
    ]


    if core_relevance:

        if location_matches:

            location_score = (
                weights[
                    "location"
                ]
            )


        elif (
            ACCEPT_ALL_BELGIUM
            and
            belgian_job
        ):

            location_score = (
                weights[
                    "location"
                ]
                *
                0.5
            )


        else:

            location_score = 0


    else:

        location_score = 0


    # ========================================================
    # LANGUES
    # ========================================================

    language_matches = context[
        "language_matches"
    ]


    if core_relevance:

        if language_matches:

            language_score = (
                weights[
                    "languages"
                ]
            )

        else:

            language_score = (
                weights[
                    "languages"
                ]
                *
                0.4
            )

    else:

        language_score = 0


    # ========================================================
    # EXPÉRIENCE
    # ========================================================

    experience_result = (
        evaluate_experience_fit(
            family_name,
            title_text,
            full_text,
            weights[
                "experience_level"
            ]
        )
    )


    experience_score = (
        experience_result[
            "score"
        ]
        if core_relevance
        else 0
    )


    experience_penalty = (
        experience_result[
            "penalty"
        ]
        if core_relevance
        else 0
    )


    # ========================================================
    # BONUS MÉTIER
    # ========================================================

    domain_bonus = (
        calculate_domain_bonus(
            family_name,
            title_matches,
            data_matches,
            pharma_matches,
            lab_matches,
            business_matches
        )
    )


    if not core_relevance:
        domain_bonus = 0


    # ========================================================
    # DOMAINE SECTORIEL
    # ========================================================

    domain_fit = (
        evaluate_domain_fit(
            family_name,
            full_text
        )
    )


    domain_adjustment = (
        domain_fit[
            "adjustment"
        ]
        if core_relevance
        else 0
    )


    # ========================================================
    # SCORE BRUT
    # ========================================================

    raw_score = (
        title_score
        +
        data_score
        +
        pharma_score
        +
        lab_score
        +
        business_score
        +
        experience_score
        +
        location_score
        +
        language_score
        +
        education_score
        +
        domain_bonus
        +
        domain_adjustment
    )


    final_score = (
        raw_score
        -
        experience_penalty
    )


    # ========================================================
    # INTERNATIONAL
    # ========================================================

    international_penalty = 0


    if (
        core_relevance
        and
        not belgian_job
    ):

        international_penalty = 15

        final_score -= 15


    # ========================================================
    # PLAFOND DATA SENIOR
    # ========================================================

    seniority_cap = (
        get_data_seniority_cap(
            family_name,
            title_text,
            experience_result[
                "required"
            ]
        )
    )


    cap_applied = False


    if (
        seniority_cap[
            "cap"
        ]
        is not None
        and
        final_score
        >
        seniority_cap[
            "cap"
        ]
    ):

        final_score = (
            seniority_cap[
                "cap"
            ]
        )

        cap_applied = True


    # ========================================================
    # HORS CIBLE
    # ========================================================

    if not core_relevance:

        final_score = min(
            final_score,
            15
        )


    final_score = max(
        0,
        min(
            final_score,
            100
        )
    )


    final_score = round(
        final_score,
        1
    )


    # ========================================================
    # EXPLICATIONS
    # ========================================================

    if title_matches:

        reasons.append(
            (
                "Intitulé compatible : "
                +
                ", ".join(
                    title_matches[:3]
                )
            )
        )


    if (
        family_name == "chemistry_lab"
        and
        contextual_title_matches
        and
        chemistry_anchor_matches
        and
        not title_matches
    ):

        reasons.append(
            (
                "Intitulé contextuel Chemistry/Lab : "
                +
                ", ".join(
                    contextual_title_matches[:2]
                )
                +
                " | ancre : "
                +
                ", ".join(
                    chemistry_anchor_matches[:3]
                )
            )
        )


    if data_matches:

        reasons.append(
            (
                "Compétences Data : "
                +
                ", ".join(
                    data_matches[:8]
                )
            )
        )


    if pharma_matches:

        reasons.append(
            (
                "Compétences Pharma/Quality : "
                +
                ", ".join(
                    pharma_matches[:8]
                )
            )
        )


    if lab_matches:

        reasons.append(
            (
                "Compétences laboratoire : "
                +
                ", ".join(
                    lab_matches[:8]
                )
            )
        )


    if business_matches:

        reasons.append(
            (
                "Compétences Business : "
                +
                ", ".join(
                    business_matches[:6]
                )
            )
        )


    if (
        core_relevance
        and
        profile_qualified
        and
        profile_education_label
    ):

        reasons.append(
            (
                "Formation candidat pertinente : "
                +
                profile_education_label
            )
        )


    if education_matches:

        reasons.append(
            (
                "Formation demandée/détectée dans l'annonce : "
                +
                ", ".join(
                    education_matches[:4]
                )
            )
        )


    if core_relevance:

        reasons.extend(
            experience_result[
                "reasons"
            ]
        )


        reasons.extend(
            domain_fit[
                "reasons"
            ]
        )


        if location_matches:

            reasons.append(
                (
                    "Localisation prioritaire : "
                    +
                    ", ".join(
                        location_matches[:2]
                    )
                )
            )


        elif (
            belgian_job
            and
            ACCEPT_ALL_BELGIUM
        ):

            reasons.append(
                (
                    "Belgique acceptée, "
                    "hors zone prioritaire"
                )
            )


        else:

            reasons.append(
                "⚠️ Offre hors Belgique"
            )


        if language_matches:

            reasons.append(
                (
                    "Langues détectées : "
                    +
                    ", ".join(
                        language_matches[:3]
                    )
                )
            )


        if domain_bonus:

            reasons.append(
                (
                    "Bonus forte cohérence métier : "
                    f"+{domain_bonus}"
                )
            )


        if experience_penalty:

            reasons.append(
                (
                    "⚠️ Pénalité expérience : "
                    f"-{experience_penalty}"
                )
            )


        if cap_applied:

            reasons.append(
                (
                    "⚠️ Score plafonné à "
                    f"{seniority_cap['cap']}/100 : "
                    f"{seniority_cap['reason']}"
                )
            )


    else:

        reasons.append(
            "Aucun signal métier suffisant"
        )


    return {
        "family":
            family_name,

        "score":
            final_score,

        "core_relevance":
            core_relevance,

        "title_score":
            round(
                title_score,
                1
            ),

        "data_score":
            round(
                data_score,
                1
            ),

        "pharma_score":
            round(
                pharma_score,
                1
            ),

        "lab_score":
            round(
                lab_score,
                1
            ),

        "business_score":
            round(
                business_score,
                1
            ),

        "experience_score":
            round(
                experience_score,
                1
            ),

        "experience_penalty":
            experience_penalty,

        "location_score":
            round(
                location_score,
                1
            ),

        "language_score":
            round(
                language_score,
                1
            ),

        "education_score":
            round(
                education_score,
                1
            ),

        "domain_bonus":
            domain_bonus,

        "domain_adjustment":
            domain_adjustment,

        "domain_level":
            domain_fit[
                "level"
            ],

        "international_penalty":
            international_penalty,

        "seniority_cap":
            seniority_cap[
                "cap"
            ],

        "cap_applied":
            cap_applied,

        "title_matches":
            title_matches,

        "data_matches":
            data_matches,

        "pharma_matches":
            pharma_matches,

        "lab_matches":
            lab_matches,

        "business_matches":
            business_matches,

        "education_matches":
            education_matches,

        "reasons":
            reasons,
    }


# ============================================================
# SCORE GLOBAL
# ============================================================

def score_job(job):

    family_results = []


    context = (
        build_job_match_context(
            job
        )
    )


    for family_name in (
        TARGET_JOB_FAMILIES
    ):

        result = evaluate_family(
            job,
            family_name,
            context=context
        )

        family_results.append(
            result
        )


    family_results.sort(
        key=lambda result: (
            result[
                "core_relevance"
            ],
            result[
                "score"
            ]
        ),
        reverse=True
    )


    best_result = (
        family_results[0]
    )


    score = (
        best_result[
            "score"
        ]
    )


    core_relevance = (
        best_result[
            "core_relevance"
        ]
    )


    confidence = (
        evaluate_confidence(
            job
        )
    )


    provisional = (
        confidence[
            "provisional"
        ]
    )


    # ========================================================
    # RECOMMANDATION
    # ========================================================

    if provisional:

        recommendation = (
            "⚠️ SCORE PROVISOIRE"
        )


    elif not core_relevance:

        recommendation = (
            "🔴 HORS CIBLE"
        )


    elif score >= 90:

        recommendation = (
            "🔥 EXCELLENT MATCH"
        )


    elif score >= 80:

        recommendation = (
            "🟢 TRÈS PERTINENT"
        )


    elif score >= 65:

        recommendation = (
            "🟢 PERTINENT"
        )


    elif score >= 50:

        recommendation = (
            "🟡 À EXAMINER"
        )


    elif score >= 35:

        recommendation = (
            "⚪ POTENTIEL"
        )


    else:

        recommendation = (
            "🔴 FAIBLE"
        )


    return {
        "score":
            score,

        "recommendation":
            recommendation,

        "core_relevance":
            core_relevance,

        "best_family":
            best_result[
                "family"
            ],

        "reasons":
            best_result[
                "reasons"
            ],

        "details":
            best_result,

        "confidence":
            confidence,

        "confidence_level":
            confidence[
                "level"
            ],

        "confidence_label":
            confidence[
                "label"
            ],

        "confidence_rank":
            confidence[
                "rank"
            ],

        "provisional":
            provisional,

        "all_family_scores": {
            result[
                "family"
            ]:
                result[
                    "score"
                ]
            for result
            in family_results
        },
    }


# ============================================================
# AFFICHAGE
# ============================================================

def print_job_match(
    job,
    result
):

    print()

    print(
        "=" * 72
    )

    print(
        f"{result['recommendation']} "
        f"- {result['score']}/100"
    )

    print(
        "=" * 72
    )


    print(
        "Titre       :",
        job.title
    )

    print(
        "Entreprise  :",
        job.company
    )

    print(
        "Lieu        :",
        job.location
    )

    print(
        "Famille     :",
        result[
            "best_family"
        ]
    )

    print(
        "Confiance   :",
        result[
            "confidence_label"
        ]
    )

    print(
        "URL         :",
        job.url
    )


    if result[
        "provisional"
    ]:

        print()

        print(
            "⚠️ ATTENTION : ce score est PROVISOIRE."
        )

        print(
            "   ",
            result[
                "confidence"
            ][
                "reason"
            ]
        )


    print()

    print(
        "Pourquoi :"
    )


    for reason in (
        result[
            "reasons"
        ]
    ):

        print(
            "  +",
            reason
        )


    print()

    print(
        "Scores par famille :"
    )


    sorted_families = sorted(
        result[
            "all_family_scores"
        ].items(),
        key=lambda item:
            item[1],
        reverse=True
    )


    for family, score in (
        sorted_families
    ):

        print(
            f"  {family:<25} "
            f"{score:>5.1f}"
        )


# ============================================================
# TEST SIMPLE
# ============================================================

if __name__ == "__main__":

    from sources.forem import (
        get_forem_jobs,
        convert_forem_job,
    )


    print()
    print(
        "=" * 70
    )

    print(
        "             MATCHER V5.1"
    )

    print(
        "=" * 70
    )


    raw_jobs = (
        get_forem_jobs(
            max_jobs=100
        )
    )


    results = []


    for raw_job in raw_jobs:

        job = convert_forem_job(
            raw_job
        )

        result = score_job(
            job
        )

        if result[
            "core_relevance"
        ]:

            results.append(
                (
                    job,
                    result
                )
            )


    results.sort(
        key=lambda item: (
            item[1][
                "score"
            ]
        ),
        reverse=True
    )


    for job, result in (
        results[:20]
    ):

        print_job_match(
            job,
            result
        )