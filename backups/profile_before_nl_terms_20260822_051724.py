"""
JOB HUNTER BELGIUM
PROFIL CANDIDAT - VERSION 5.1

V5.1 = couverture double diplôme + distinction collecte large / scoring strict.

Axes :
1. DATA / BI
   - spécialisation de bachelier Business Data Analyst ;
   - Python / SQL / Power BI / R / ETL / ML / Data Quality ;
   - expérience professionnelle Data encore junior.

2. CHIMIE / LABORATOIRE / PHARMA / QUALITY
   - bachelier en chimie ;
   - environ 3 ans d'expérience QC / laboratoire / pharma ;
   - GMP, SAP, LIMS, TrackWise ;
   - HPLC / UPLC / microbiologie / endotoxines.

3. BANQUE DE TERMES TRILINGUE
   - français ;
   - anglais ;
   - néerlandais.

Les connecteurs Forem et Actiris importent la même banque de recherche.
Le matcher utilise les mêmes synonymes afin que :
"technicien chimiste", "chemical technician" et "chemisch laborant"
soient reconnus comme le même univers métier.
"""


# ============================================================
# IDENTITÉ PROFESSIONNELLE
# ============================================================

PROFILE_NAME = "Oussama Aharroud"

PROFILE_TYPE = (
    "Data / Chemistry / Pharma QC / Quality / Laboratory"
)


# ============================================================
# PARCOURS
# ============================================================

YEARS_PHARMA_QC_EXPERIENCE = 3

HAS_DATA_ANALYSIS_SPECIALIZATION = True
HAS_CHEMISTRY_DEGREE = True
HAS_PHARMA_BACKGROUND = True


# ============================================================
# EXPÉRIENCE PAR FAMILLE
# ============================================================

EXPERIENCE_PROFILE = {

    "data_analytics": {
        "professional_years": 0.0,
        "effective_years": 1.0,
        "level": "junior",
    },

    "business_intelligence": {
        "professional_years": 0.0,
        "effective_years": 1.0,
        "level": "junior",
    },

    "business_analysis": {
        "professional_years": 0.0,
        "effective_years": 1.0,
        "level": "junior",
    },

    "data_engineering": {
        "professional_years": 0.0,
        "effective_years": 1.0,
        "level": "junior",
    },

    # Nouveau :
    # le diplôme de chimie + l'expérience QC/labo doivent
    # permettre de reconnaître les postes de chimie/labo
    # même hors pharma stricte.
    "chemistry_lab": {
        "professional_years": 3.0,
        "effective_years": 3.0,
        "level": "confirmed",
    },

    "pharma_qc": {
        "professional_years": 3.0,
        "effective_years": 3.0,
        "level": "confirmed",
    },

    "quality": {
        "professional_years": 3.0,
        "effective_years": 3.0,
        "level": "confirmed",
    },

    "hybrid_data_pharma": {
        "professional_years": 3.0,
        "effective_years": 3.0,
        "level": "confirmed_pharma_junior_data",
    },
}


# ============================================================
# LOCALISATIONS PRIORITAIRES
# ============================================================

PREFERRED_LOCATIONS = [

    "bruxelles",
    "brussels",
    "brussel",
    "bruxelles-capitale",
    "brussels capital",
    "région de bruxelles-capitale",
    "brussels hoofdstedelijk gewest",

    "anderlecht",
    "auderghem",
    "oudergem",
    "berchem-sainte-agathe",
    "sint-agatha-berchem",
    "etterbeek",
    "evere",
    "forest",
    "vorst",
    "ganshoren",
    "ixelles",
    "elsene",
    "jette",
    "koekelberg",
    "molenbeek",
    "saint-gilles",
    "sint-gillis",
    "saint-josse",
    "sint-joost",
    "schaerbeek",
    "schaarbeek",
    "uccle",
    "ukkel",
    "watermael-boitsfort",
    "watermaal-bosvoorde",
    "woluwe",

    "zaventem",
    "diegem",
    "machelen",
    "vilvoorde",

    "wavre",
    "rixensart",
    "genval",
    "braine-l'alleud",
    "braine l'alleud",
    "waterloo",
    "ottignies",
    "louvain-la-neuve",
    "mont-saint-guibert",
    "mont saint guibert",
    "drogenbos",
]

ACCEPT_ALL_BELGIUM = True


# ============================================================
# OUTILS DE BANQUE MULTILINGUE
# ============================================================

def _unique(values):

    return list(
        dict.fromkeys(
            value
            for value in values
            if value
        )
    )


def flatten_multilingual_concepts(
    concepts,
    languages=("fr", "en", "nl")
):

    values = []

    for language_map in concepts.values():

        for language in languages:

            values.extend(
                language_map.get(
                    language,
                    []
                )
            )

    return _unique(
        values
    )


# ============================================================
# BANQUE DATA / BI - FR / EN / NL
# ============================================================

DATA_SEARCH_CONCEPTS = {

    "data_analyst": {
        "fr": [
            "analyste de données",
            "analyste des données",
            "analyste data",
        ],
        "en": [
            "data analyst",
            "analytics analyst",
        ],
        "nl": [
            "data-analist",
            "data analist",
            "gegevensanalist",
        ],
    },

    "junior_data_analyst": {
        "fr": [
            "analyste de données junior",
            "analyste data junior",
        ],
        "en": [
            "junior data analyst",
            "entry level data analyst",
        ],
        "nl": [
            "junior data-analist",
            "junior data analist",
        ],
    },

    "business_data_analyst": {
        "fr": [
            "business data analyst",
            "analyste business data",
        ],
        "en": [
            "business data analyst",
        ],
        "nl": [
            "business data analyst",
            "bedrijfsdata-analist",
        ],
    },

    "data_quality": {
        "fr": [
            "analyste qualité des données",
            "qualité des données",
        ],
        "en": [
            "data quality analyst",
            "data quality officer",
            "data quality",
        ],
        "nl": [
            "data quality analyst",
            "datakwaliteitsanalist",
            "datakwaliteit",
        ],
    },

    "data_integrity": {
        "fr": [
            "intégrité des données",
            "analyste intégrité des données",
        ],
        "en": [
            "data integrity",
            "data integrity analyst",
        ],
        "nl": [
            "data-integriteit",
            "data integriteit",
            "data-integriteitsanalist",
        ],
    },

    "data_governance": {
        "fr": [
            "gouvernance des données",
            "analyste gouvernance des données",
        ],
        "en": [
            "data governance",
            "data governance analyst",
        ],
        "nl": [
            "datagovernance",
            "data governance analyst",
        ],
    },

    "data_steward": {
        "fr": [
            "data steward",
            "gestionnaire de données",
        ],
        "en": [
            "data steward",
            "data officer",
        ],
        "nl": [
            "data steward",
            "databeheerder",
        ],
    },

    "master_data": {
        "fr": [
            "master data",
            "gestion des données de référence",
        ],
        "en": [
            "master data analyst",
            "master data officer",
            "master data specialist",
        ],
        "nl": [
            "master data analyst",
            "master data beheerder",
            "stamgegevensbeheerder",
        ],
    },

    "reporting": {
        "fr": [
            "analyste reporting",
            "chargé de reporting",
            "reporting",
        ],
        "en": [
            "reporting analyst",
            "reporting officer",
            "reporting developer",
        ],
        "nl": [
            "rapportageanalist",
            "reporting analyst",
            "rapportering",
        ],
    },

    "power_bi": {
        "fr": [
            "analyste Power BI",
            "développeur Power BI",
            "Power BI",
        ],
        "en": [
            "Power BI analyst",
            "Power BI developer",
            "Power BI",
        ],
        "nl": [
            "Power BI analist",
            "Power BI ontwikkelaar",
            "Power BI",
        ],
    },

    "business_intelligence": {
        "fr": [
            "business intelligence",
            "analyste BI",
            "développeur BI",
        ],
        "en": [
            "business intelligence",
            "BI analyst",
            "BI developer",
        ],
        "nl": [
            "business intelligence",
            "BI-analist",
            "BI ontwikkelaar",
        ],
    },

    "business_analysis": {
        "fr": [
            "business analyst",
            "analyste business",
            "analyste fonctionnel",
            "analyste processus",
        ],
        "en": [
            "business analyst",
            "functional analyst",
            "process analyst",
            "operations analyst",
        ],
        "nl": [
            "business analist",
            "functioneel analist",
            "procesanalist",
            "operationeel analist",
        ],
    },

    "data_engineering": {
        "fr": [
            "data engineer",
            "ingénieur data",
            "ingénieur de données",
        ],
        "en": [
            "data engineer",
            "junior data engineer",
        ],
        "nl": [
            "data engineer",
            "data-engineer",
            "junior data engineer",
        ],
    },

    "etl": {
        "fr": [
            "ETL",
            "développeur ETL",
            "analyste ETL",
        ],
        "en": [
            "ETL",
            "ETL developer",
            "ETL analyst",
        ],
        "nl": [
            "ETL",
            "ETL ontwikkelaar",
            "ETL analist",
        ],
    },

    "data_integration": {
        "fr": [
            "intégration de données",
            "analyste intégration de données",
        ],
        "en": [
            "data integration",
            "data integration analyst",
            "data integration developer",
        ],
        "nl": [
            "data-integratie",
            "data integratie analist",
        ],
    },

    "sql": {
        "fr": [
            "analyste SQL",
            "développeur SQL",
        ],
        "en": [
            "SQL analyst",
            "SQL developer",
        ],
        "nl": [
            "SQL-analist",
            "SQL ontwikkelaar",
        ],
    },

    "database": {
        "fr": [
            "analyste base de données",
        ],
        "en": [
            "database analyst",
        ],
        "nl": [
            "databaseanalist",
        ],
    },

    "dashboard": {
        "fr": [
            "analyste tableaux de bord",
            "visualisation de données",
        ],
        "en": [
            "dashboard analyst",
            "data visualization",
            "data visualisation",
        ],
        "nl": [
            "dashboardanalist",
            "datavisualisatie",
        ],
    },

    "decision_support": {
        "fr": [
            "aide à la décision",
            "analyste décisionnel",
        ],
        "en": [
            "decision support analyst",
            "decision support",
        ],
        "nl": [
            "beslissingsondersteuning",
            "beslissingsanalist",
        ],
    },

    "data_management": {
        "fr": [
            "gestion des données",
            "opérations data",
        ],
        "en": [
            "data management",
            "data operations",
        ],
        "nl": [
            "databeheer",
            "data operations",
        ],
    },
}


# ============================================================
# BANQUE CHIMIE / LABO / QUALITY - FR / EN / NL
# ============================================================

CHEMISTRY_LAB_SEARCH_CONCEPTS = {

    "chemical_technician": {
        "fr": [
            "technicien chimiste",
            "technicien en chimie",
        ],
        "en": [
            "chemical technician",
            "chemistry technician",
        ],
        "nl": [
            "chemisch technicus",
            "chemisch laborant",
        ],
    },

    "chemistry_assistant": {
        "fr": [
            "assistant chimiste",
            "assistant en chimie",
        ],
        "en": [
            "chemistry assistant",
            "chemical laboratory assistant",
        ],
        "nl": [
            "chemisch assistent",
            "laboratoriumassistent chemie",
        ],
    },

    "laboratory_technician": {
        "fr": [
            "laborantin",
            "technicien laboratoire",
            "technicien de laboratoire",
        ],
        "en": [
            "laboratory technician",
            "lab technician",
        ],
        "nl": [
            "laborant",
            "laboratoriumtechnicus",
            "labotechnicus",
            "technisch laborant",
        ],
    },

    "laboratory_analyst": {
        "fr": [
            "analyste laboratoire",
            "analyste de laboratoire",
        ],
        "en": [
            "laboratory analyst",
            "lab analyst",
        ],
        "nl": [
            "laboratoriumanalist",
            "lab analyst",
        ],
    },

    "analytical_chemistry": {
        "fr": [
            "chimie analytique",
        ],
        "en": [
            "analytical chemistry",
        ],
        "nl": [
            "analytische chemie",
        ],
    },

    "organic_chemistry": {
        "fr": [
            "chimie organique",
        ],
        "en": [
            "organic chemistry",
        ],
        "nl": [
            "organische chemie",
        ],
    },

    "inorganic_chemistry": {
        "fr": [
            "chimie inorganique",
        ],
        "en": [
            "inorganic chemistry",
        ],
        "nl": [
            "anorganische chemie",
        ],
    },

    "physical_chemistry": {
        "fr": [
            "chimie physique",
        ],
        "en": [
            "physical chemistry",
        ],
        "nl": [
            "fysische chemie",
        ],
    },

    "biochemistry": {
        "fr": [
            "biochimie",
        ],
        "en": [
            "biochemistry",
        ],
        "nl": [
            "biochemie",
        ],
    },

    "industrial_chemistry": {
        "fr": [
            "chimie industrielle",
        ],
        "en": [
            "industrial chemistry",
        ],
        "nl": [
            "industriële chemie",
            "industriele chemie",
        ],
    },

    "fine_chemistry": {
        "fr": [
            "chimie fine",
        ],
        "en": [
            "fine chemistry",
            "fine chemicals",
        ],
        "nl": [
            "fijnchemie",
            "fijne chemicaliën",
        ],
    },

    "quality_control": {
        "fr": [
            "contrôle qualité",
            "controle qualite",
            "QC",
            "laboratoire QC",
        ],
        "en": [
            "quality control",
            "QC",
            "QC laboratory",
            "QC lab",
        ],
        "nl": [
            "kwaliteitscontrole",
            "QC",
            "QC-laboratorium",
            "kwaliteitscontrolelaboratorium",
        ],
    },

    "quality_assurance": {
        "fr": [
            "assurance qualité",
            "assurance qualite",
            "QA",
            "laboratoire QA",
        ],
        "en": [
            "quality assurance",
            "QA",
            "QA laboratory",
            "QA lab",
        ],
        "nl": [
            "kwaliteitsborging",
            "kwaliteitszorg",
            "QA",
            "QA-laboratorium",
        ],
    },

    "qc_role": {
        "fr": [
            "technicien QC",
            "analyste QC",
        ],
        "en": [
            "QC technician",
            "QC analyst",
        ],
        "nl": [
            "QC-technicus",
            "QC-analist",
            "kwaliteitslaborant",
        ],
    },

    "qa_role": {
        "fr": [
            "analyste QA",
            "chargé assurance qualité",
        ],
        "en": [
            "QA analyst",
            "QA officer",
        ],
        "nl": [
            "QA-analist",
            "QA officer",
            "kwaliteitsmedewerker",
        ],
    },

    "physicochemical_analysis": {
        "fr": [
            "analyses physico-chimiques",
            "analyse physico-chimique",
        ],
        "en": [
            "physicochemical analysis",
            "physico-chemical analysis",
        ],
        "nl": [
            "fysisch-chemische analyse",
            "fysisch chemische analyses",
        ],
    },

    "microbiological_analysis": {
        "fr": [
            "analyses microbiologiques",
            "analyse microbiologique",
        ],
        "en": [
            "microbiological analysis",
            "microbiological testing",
        ],
        "nl": [
            "microbiologische analyse",
            "microbiologische testen",
        ],
    },

    "analytical_validation": {
        "fr": [
            "validation analytique",
            "validation de méthode",
            "validation de methode",
        ],
        "en": [
            "analytical validation",
            "method validation",
        ],
        "nl": [
            "analytische validatie",
            "methodevalidatie",
        ],
    },

    "traceability": {
        "fr": [
            "traçabilité",
            "tracabilite",
        ],
        "en": [
            "traceability",
        ],
        "nl": [
            "traceerbaarheid",
        ],
    },

    "lims": {
        "fr": [
            "LIMS",
        ],
        "en": [
            "LIMS",
            "laboratory information management system",
        ],
        "nl": [
            "LIMS",
            "laboratorium informatiemanagementsysteem",
        ],
    },

    "hplc": {
        "fr": ["HPLC"],
        "en": ["HPLC"],
        "nl": ["HPLC"],
    },

    "gc": {
        "fr": [
            "chromatographie en phase gazeuse",
        ],
        "en": [
            "gas chromatography",
            "GC chromatography",
        ],
        "nl": [
            "gaschromatografie",
            "GC chromatografie",
        ],
    },

    "uv_vis": {
        "fr": [
            "UV-Vis",
            "spectrophotométrie UV-Vis",
        ],
        "en": [
            "UV-Vis",
            "UV-Vis spectrophotometry",
        ],
        "nl": [
            "UV-Vis",
            "UV-Vis spectrofotometrie",
        ],
    },

    "infrared": {
        "fr": [
            "spectroscopie infrarouge",
        ],
        "en": [
            "infrared spectroscopy",
            "IR spectroscopy",
        ],
        "nl": [
            "infraroodspectroscopie",
            "IR-spectroscopie",
        ],
    },

    "ftir": {
        "fr": [
            "FTIR",
            "spectroscopie FTIR",
        ],
        "en": [
            "FTIR",
            "FTIR spectroscopy",
        ],
        "nl": [
            "FTIR",
            "FTIR-spectroscopie",
        ],
    },

    "nmr": {
        "fr": [
            "RMN",
            "résonance magnétique nucléaire",
        ],
        "en": [
            "NMR",
            "nuclear magnetic resonance",
        ],
        "nl": [
            "NMR",
            "kernmagnetische resonantie",
        ],
    },

    "mass_spectrometry": {
        "fr": [
            "spectrométrie de masse",
        ],
        "en": [
            "mass spectrometry",
        ],
        "nl": [
            "massaspectrometrie",
        ],
    },

    "chromatography": {
        "fr": [
            "chromatographie",
        ],
        "en": [
            "chromatography",
        ],
        "nl": [
            "chromatografie",
        ],
    },

    "titration": {
        "fr": [
            "titrage",
        ],
        "en": [
            "titration",
        ],
        "nl": [
            "titratie",
        ],
    },

    "distillation": {
        "fr": ["distillation"],
        "en": ["distillation"],
        "nl": ["destillatie"],
    },

    "extraction": {
        "fr": ["extraction"],
        "en": ["extraction"],
        "nl": ["extractie"],
    },

    "purification": {
        "fr": ["purification"],
        "en": ["purification"],
        "nl": ["zuivering"],
    },

    "cell_culture": {
        "fr": [
            "culture cellulaire",
        ],
        "en": [
            "cell culture",
        ],
        "nl": [
            "celkweek",
            "celcultuur",
        ],
    },

    "microbiology": {
        "fr": ["microbiologie"],
        "en": ["microbiology"],
        "nl": ["microbiologie"],
    },

    "enzymology": {
        "fr": ["enzymologie"],
        "en": ["enzymology"],
        "nl": ["enzymologie"],
    },

    "molecular_biology": {
        "fr": [
            "biologie moléculaire",
        ],
        "en": [
            "molecular biology",
        ],
        "nl": [
            "moleculaire biologie",
        ],
    },

    "pcr": {
        "fr": ["PCR"],
        "en": ["PCR"],
        "nl": ["PCR"],
    },

    "electrophoresis": {
        "fr": ["électrophorèse"],
        "en": ["electrophoresis"],
        "nl": ["elektroforese"],
    },

    "environmental_chemistry": {
        "fr": [
            "chimie environnementale",
        ],
        "en": [
            "environmental chemistry",
        ],
        "nl": [
            "milieuchemie",
            "omgevingschemie",
        ],
    },

    "water_analysis": {
        "fr": [
            "analyse eau",
            "analyse de l'eau",
        ],
        "en": [
            "water analysis",
            "water testing",
        ],
        "nl": [
            "wateranalyse",
            "wateronderzoek",
        ],
    },

    "air_analysis": {
        "fr": [
            "analyse air",
            "analyse de l'air",
        ],
        "en": [
            "air analysis",
            "air testing",
        ],
        "nl": [
            "luchtanalyse",
            "luchtonderzoek",
        ],
    },

    "soil_analysis": {
        "fr": [
            "analyse sol",
            "analyse de sol",
        ],
        "en": [
            "soil analysis",
            "soil testing",
        ],
        "nl": [
            "bodemanalyse",
            "bodemonderzoek",
        ],
    },

    "chemical_waste": {
        "fr": [
            "déchets chimiques",
            "dechets chimiques",
        ],
        "en": [
            "chemical waste",
        ],
        "nl": [
            "chemisch afval",
        ],
    },

    "laboratory_safety": {
        "fr": [
            "sécurité laboratoire",
            "securite laboratoire",
        ],
        "en": [
            "laboratory safety",
            "lab safety",
        ],
        "nl": [
            "laboratoriumveiligheid",
        ],
    },

    "reach": {
        "fr": ["REACH"],
        "en": ["REACH"],
        "nl": ["REACH"],
    },

    "clp": {
        "fr": ["CLP"],
        "en": ["CLP"],
        "nl": ["CLP"],
    },

    "pharmaceutical_industry": {
        "fr": [
            "industrie pharmaceutique",
            "pharmaceutique",
        ],
        "en": [
            "pharmaceutical industry",
            "pharmaceutical",
        ],
        "nl": [
            "farmaceutische industrie",
            "farmaceutisch",
        ],
    },

    "chemical_industry": {
        "fr": [
            "industrie chimique",
        ],
        "en": [
            "chemical industry",
        ],
        "nl": [
            "chemische industrie",
        ],
    },

    "food_industry": {
        "fr": [
            "agroalimentaire",
            "industrie alimentaire",
        ],
        "en": [
            "food industry",
            "food manufacturing",
        ],
        "nl": [
            "voedingsindustrie",
            "voedingsmiddelenindustrie",
        ],
    },

    "cosmetics": {
        "fr": [
            "cosmétique",
            "industrie cosmétique",
        ],
        "en": [
            "cosmetics",
            "cosmetic industry",
        ],
        "nl": [
            "cosmetica",
            "cosmetische industrie",
        ],
    },

    "pharmaceutical_production": {
        "fr": [
            "production pharmaceutique",
        ],
        "en": [
            "pharmaceutical production",
            "pharmaceutical manufacturing",
        ],
        "nl": [
            "farmaceutische productie",
        ],
    },

    "production_operator": {
        "fr": [
            "opérateur de production",
            "operateur de production",
        ],
        "en": [
            "production operator",
            "manufacturing operator",
        ],
        "nl": [
            "productieoperator",
            "operator productie",
        ],
    },

    "production_technician": {
        "fr": [
            "technicien de production",
            "technicien production",
        ],
        "en": [
            "production technician",
            "manufacturing technician",
        ],
        "nl": [
            "productietechnicus",
            "technicus productie",
        ],
    },

    "formulation": {
        "fr": ["formulation"],
        "en": ["formulation"],
        "nl": ["formulering"],
    },

    "iso": {
        "fr": [
            "norme ISO",
            "ISO qualité",
        ],
        "en": [
            "ISO standard",
            "ISO quality",
        ],
        "nl": [
            "ISO-norm",
            "ISO kwaliteit",
        ],
    },

    "gmp": {
        "fr": [
            "GMP",
            "BPF",
            "bonnes pratiques de fabrication",
        ],
        "en": [
            "GMP",
            "good manufacturing practices",
        ],
        "nl": [
            "GMP",
            "goede productiepraktijken",
        ],
    },

    "glp": {
        "fr": [
            "GLP",
            "bonnes pratiques de laboratoire",
        ],
        "en": [
            "GLP",
            "good laboratory practice",
        ],
        "nl": [
            "GLP",
            "goede laboratoriumpraktijken",
        ],
    },

    "scientific_rigor": {
        "fr": [
            "rigueur scientifique",
        ],
        "en": [
            "scientific rigor",
            "scientific rigour",
        ],
        "nl": [
            "wetenschappelijke nauwkeurigheid",
            "nauwkeurig wetenschappelijk werken",
        ],
    },

    "rd_laboratory": {
        "fr": [
            "laboratoire R&D",
            "laboratoire recherche et développement",
        ],
        "en": [
            "R&D laboratory",
            "research and development laboratory",
        ],
        "nl": [
            "R&D-laboratorium",
            "onderzoeks- en ontwikkelingslaboratorium",
        ],
    },
}


# ============================================================
# TERMES DE RECHERCHE CONNECTEURS
# ============================================================

# On utilise une occurrence représentative par langue et par concept.
# Les variantes supplémentaires restent disponibles dans le matcher.
#
# Cela limite l'explosion du nombre de requêtes Actiris,
# tout en couvrant réellement FR + EN + NL.

def _representative_terms(
    concepts
):

    values = []

    for language_map in concepts.values():

        for language in (
            "fr",
            "en",
            "nl",
        ):

            candidates = language_map.get(
                language,
                []
            )

            if candidates:

                values.append(
                    candidates[0]
                )

    return _unique(
        values
    )


DATA_COLLECTION_SEARCH_TERMS = (
    _representative_terms(
        DATA_SEARCH_CONCEPTS
    )
)


CHEMISTRY_LAB_COLLECTION_SEARCH_TERMS = (
    _representative_terms(
        CHEMISTRY_LAB_SEARCH_CONCEPTS
    )
)


COLLECTION_SEARCH_TERMS = _unique(
    DATA_COLLECTION_SEARCH_TERMS
    +
    CHEMISTRY_LAB_COLLECTION_SEARCH_TERMS
)


# ============================================================
# FAMILLES DE MÉTIERS
# ============================================================

TARGET_JOB_FAMILIES = {

    "data_analytics": _unique([

        "data analyst",
        "junior data analyst",
        "business data analyst",
        "analytics analyst",

        "analyste de données",
        "analyste des données",
        "analyste data",
        "analyste de données junior",

        "data-analist",
        "data analist",
        "gegevensanalist",
        "junior data-analist",

        "data quality analyst",
        "data quality officer",
        "analyste qualité des données",
        "datakwaliteitsanalist",

        "data steward",
        "data officer",
        "databeheerder",

        "data governance analyst",
        "analyste gouvernance des données",

        "master data analyst",
        "master data officer",
        "stamgegevensbeheerder",

        "reporting analyst",
        "reporting officer",
        "analyste reporting",
        "rapportageanalist",

        "statistical analyst",
        "analyste statistique",
        "statisticien",
        "statistisch analist",
    ]),


    "business_intelligence": _unique([

        "bi analyst",
        "bi analyst developer",
        "business intelligence analyst",
        "power bi analyst",
        "power bi developer",
        "bi developer",
        "business intelligence developer",
        "bi consultant",

        "analyste bi",
        "développeur bi",
        "analyste power bi",
        "développeur power bi",

        "bi-analist",
        "bi analist",
        "bi ontwikkelaar",
        "power bi analist",
        "power bi ontwikkelaar",

        "reporting analyst",
        "reporting developer",
        "rapportageanalist",
    ]),


    "business_analysis": _unique([

        "business analyst",
        "functional analyst",
        "business functional analyst",
        "process analyst",
        "operations analyst",
        "business process analyst",
        "business systems analyst",

        "analyste fonctionnel",
        "analyste business",
        "analyste processus",

        "business analist",
        "functioneel analist",
        "procesanalist",
        "operationeel analist",
    ]),


    "data_engineering": _unique([

        "data engineer",
        "junior data engineer",
        "data-engineer",

        "etl developer",
        "etl analyst",

        "data integration developer",
        "data integration analyst",

        "database analyst",
        "sql developer",
        "sql analyst",

        "data pipeline developer",

        "ingénieur data",
        "ingénieur de données",
        "analyste sql",
        "développeur sql",

        "etl ontwikkelaar",
        "etl analist",
        "sql-analist",
        "sql ontwikkelaar",
        "databaseanalist",
    ]),


    # ========================================================
    # NOUVELLE FAMILLE : CHIMIE / LABO
    # ========================================================

    "chemistry_lab": _unique([

        "technicien chimiste",
        "technicien en chimie",
        "assistant chimiste",
        "assistant en chimie",
        "laborantin",
        "technicien laboratoire",
        "technicien de laboratoire",
        "analyste laboratoire",
        "analyste de laboratoire",
        "analyste physico chimique",
        "analyste physico-chimique",

        "chemical technician",
        "chemistry technician",
        "chemistry assistant",
        "laboratory technician",
        "lab technician",
        "laboratory analyst",
        "lab analyst",
        "analytical technician",
        "analytical laboratory technician",

        "chemisch technicus",
        "chemisch laborant",
        "chemisch assistent",
        "laboratoriumassistent chemie",
        "laborant",
        "laboratoriumtechnicus",
        "labotechnicus",
        "technisch laborant",
        "laboratoriumanalist",
        "analytisch laborant",
        "kwaliteitslaborant",

    ]),


    "pharma_qc": _unique([

        "laborantin",
        "laborant",
        "laboratory technician",
        "lab technician",
        "laboratoriumtechnicus",
        "technisch laborant",

        "technicien qc",
        "technicien de laboratoire qc",
        "qc analyst",
        "qc technician",
        "analyste qc",
        "qc-analist",
        "qc-technicus",
        "kwaliteitslaborant",

        "laboratory analyst",
        "lab analyst",
        "analyste laboratoire",
        "laboratoriumanalist",

        "microbiology analyst",
        "microbiology technician",
        "analyste microbiologie",
        "microbiologisch analist",
        "microbiologisch laborant",
    ]),


    "quality": _unique([

        "quality analyst",
        "quality specialist",
        "quality officer",
        "qa officer",
        "qa analyst",
        "quality assurance",
        "quality control",
        "quality coordinator",
        "quality systems",

        "assurance qualité",
        "contrôle qualité",
        "coordinateur qualité",
        "assistant qualité",
        "collaborateur qualité",
        "collaborateur contrôle qualité",

        "kwaliteitsanalist",
        "kwaliteitsmedewerker",
        "kwaliteitscoördinator",
        "kwaliteitscontrole",
        "kwaliteitsborging",
        "kwaliteitszorg",
        "qa-analist",
    ]),


    "hybrid_data_pharma": _unique([

        "quality data analyst",
        "quality data specialist",
        "quality data officer",

        "data integrity analyst",
        "data integrity specialist",

        "gmp data analyst",
        "pharma data analyst",

        "laboratory data analyst",
        "lab data analyst",

        "lims analyst",
        "lims specialist",
        "lims administrator",

        "laboratory systems analyst",
        "quality systems analyst",

        "quality digitalization",
        "digital quality analyst",

        "manufacturing data analyst",
        "production data analyst",
        "operations data analyst",

        "lab informatics",
        "laboratory informatics",

        "laboratorium data analist",
        "kwaliteitsdata-analist",
        "lims analist",
    ]),
}


# ============================================================
# TITRES CONTEXTUELS / ANCRES CHIMIE-LABO - V5.1
# ============================================================

# Ces intitulés restent dans la banque de COLLECTE, mais ne sont
# plus des preuves métier suffisantes à eux seuls.
# Exemple : "technicien de production" peut concerner la pharma,
# mais aussi la mécanique, le bâtiment ou l'agroalimentaire.

CHEMISTRY_LAB_CONTEXTUAL_TITLES = _unique([
    "research technician",
    "technicien r&d",
    "r&d technician",
    "onderzoekstechnicus",

    "production technician",
    "manufacturing technician",
    "technicien de production",
    "technicien production",
    "productietechnicus",

    "opérateur de production",
    "operateur de production",
    "production operator",
    "productieoperator",
])


# Un titre contextuel n'est valorisé que si l'annonce contient au
# moins une ancre forte de chimie, laboratoire, pharma ou QC.
CHEMISTRY_LAB_CORE_ANCHORS = _unique([
    "laboratoire",
    "laboratory",
    "laboratorium",
    "lab",

    "chimie",
    "chemistry",
    "chemie",
    "chemical",
    "chemisch",

    "laborantin",
    "laborant",
    "laboratory technician",
    "laboratoriumtechnicus",
    "technisch laborant",

    "analytical chemistry",
    "chimie analytique",
    "analytische chemie",
    "physico-chimique",
    "physicochemical",
    "fysisch-chemische",

    "hplc",
    "uplc",
    "chromatographie",
    "chromatography",
    "chromatografie",
    "gas chromatography",
    "gaschromatografie",
    "ftir",
    "nmr",
    "rmn",
    "mass spectrometry",
    "spectrométrie de masse",
    "massaspectrometrie",

    "microbiologie",
    "microbiology",
    "microbiologie",
    "cell culture",
    "culture cellulaire",
    "celkweek",
    "pcr",

    "quality control",
    "contrôle qualité",
    "controle qualite",
    "kwaliteitscontrole",
    "qc",

    "gmp",
    "bpf",
    "glp",
    "lims",

    "pharma",
    "pharmaceutical",
    "pharmaceutique",
    "farmaceutisch",
    "biopharma",
    "biotech",

    "formulation",
    "formulering",
    "salle blanche",
    "cleanroom",
    "clean room",
])


# ============================================================
# COMPÉTENCES DATA
# ============================================================

DATA_SKILLS = _unique([

    "python",
    "pandas",
    "numpy",
    "scikit-learn",
    "sklearn",

    "sql",
    "sql server",
    "ssms",
    "t-sql",

    "etl",
    "ssis",
    "data integration",
    "intégration de données",
    "data-integratie",
    "data pipelines",
    "data pipeline",

    "power bi",
    "business intelligence",
    "bi",

    "dashboard",
    "dashboards",
    "tableau de bord",
    "tableaux de bord",
    "dashboarding",

    "reporting",
    "rapportage",
    "rapportering",

    "kpi",
    "key performance indicator",
    "prestatie-indicator",

    "data analysis",
    "data analytics",
    "analyse de données",
    "analyse des données",
    "data-analyse",
    "gegevensanalyse",

    "statistics",
    "statistical analysis",
    "statistiques",
    "statistiek",
    "statistische analyse",

    "machine learning",
    "random forest",
    "xgboost",
    "predictive modeling",
    "predictive modelling",
    "feature engineering",
    "cross validation",
    "cross-validation",

    "data quality",
    "qualité des données",
    "datakwaliteit",

    "data cleaning",
    "nettoyage des données",
    "data opschoning",

    "data validation",
    "validation des données",
    "datavalidatie",

    "data integrity",
    "intégrité des données",
    "data-integriteit",

    "data governance",
    "gouvernance des données",
    "datagovernance",

    "master data",
    "données de référence",
    "stamgegevens",

    "deduplication",
    "déduplication",
    "normalization",
    "normalisation",
    "standardization",
    "standardisation",

    "database",
    "relational database",
    "base de données relationnelle",
    "relationele database",

    "data warehouse",
    "entrepôt de données",
    "datawarehouse",

    "data model",
    "data modeling",
    "modèle de données",
    "datamodel",

    "excel",
    "advanced excel",
    "excel avancé",

    "rstudio",
    "r studio",
    "r programming",
    "langage r",

    "data mining",
    "fouille de données",
    "datamining",

    "data visualization",
    "data visualisation",
    "visualisation de données",
    "datavisualisatie",

    "decision support",
    "aide à la décision",
    "beslissingsondersteuning",
])


# ============================================================
# PHARMA / QUALITY
# ============================================================

PHARMA_QUALITY_SKILLS = _unique([

    "gmp",
    "bpf",
    "bonnes pratiques de fabrication",
    "good manufacturing practices",
    "goede productiepraktijken",

    "glp",
    "bonnes pratiques de laboratoire",
    "good laboratory practice",
    "goede laboratoriumpraktijken",

    "sop",
    "procédure",
    "procédures",
    "procedures",
    "werkinstructies",

    "quality control",
    "contrôle qualité",
    "controle qualite",
    "kwaliteitscontrole",
    "qc",

    "quality assurance",
    "assurance qualité",
    "assurance qualite",
    "kwaliteitsborging",
    "kwaliteitszorg",
    "qa",

    "quality systems",
    "systèmes qualité",
    "kwaliteitssystemen",

    "data integrity",
    "intégrité des données",
    "integrite des donnees",
    "data-integriteit",

    "alcoa",
    "alcoa+",
    "audit trail",

    "deviation",
    "deviations",
    "déviation",
    "déviations",
    "afwijking",
    "afwijkingen",

    "investigation",
    "investigations",
    "onderzoek",

    "oos",
    "oot",
    "capa",

    "compliance",
    "conformité",
    "conformite",
    "naleving",

    "documentation gmp",
    "documentation qualité",
    "kwaliteitsdocumentatie",

    "traçabilité",
    "tracabilite",
    "traceability",
    "traceerbaarheid",

    "sap",
    "sap qm",
    "sap mm",

    "lims",
    "trackwise",

    "audit",
    "audits",

    "validation",
    "qualification",
    "kwalificatie",

    "amélioration continue",
    "amelioration continue",
    "continuous improvement",
    "continue verbetering",

    "5s",

    "pharmaceutical",
    "pharmaceutique",
    "pharma",
    "farmaceutisch",

    "reach",
    "clp",

    "iso",
    "iso standard",
    "norme iso",
    "iso-norm",

    "laboratory safety",
    "sécurité laboratoire",
    "laboratoriumveiligheid",
])


# ============================================================
# COMPÉTENCES LABORATOIRE / CHIMIE
# ============================================================

LAB_SKILL_CONCEPT_KEYS = [

    "analytical_chemistry",
    "organic_chemistry",
    "inorganic_chemistry",
    "physical_chemistry",
    "biochemistry",
    "industrial_chemistry",
    "fine_chemistry",

    "physicochemical_analysis",
    "microbiological_analysis",
    "analytical_validation",

    "lims",
    "hplc",
    "gc",
    "uv_vis",
    "infrared",
    "ftir",
    "nmr",
    "mass_spectrometry",
    "chromatography",

    "titration",
    "distillation",
    "extraction",
    "purification",

    "cell_culture",
    "microbiology",
    "enzymology",
    "molecular_biology",
    "pcr",
    "electrophoresis",

    "environmental_chemistry",
    "water_analysis",
    "air_analysis",
    "soil_analysis",

    "laboratory_safety",
    "formulation",
]


LAB_SKILLS = _unique(
    flatten_multilingual_concepts(
        {
            key:
                CHEMISTRY_LAB_SEARCH_CONCEPTS[
                    key
                ]

            for key
            in LAB_SKILL_CONCEPT_KEYS
        }
    )
    +
    [

        # Abréviation technique réellement fréquente.
        "gc",

        "uplc",
        "karl fischer",
        "dissolution",

        "préparation d'échantillons",
        "preparation d echantillons",
        "sample preparation",
        "monstervoorbereiding",

        "échantillonnage",
        "echantillonnage",
        "sampling",
        "bemonstering",

        "matières premières",
        "matieres premieres",
        "raw materials",
        "grondstoffen",

        "produits finis",
        "finished products",
        "eindproducten",

        "stabilité",
        "stabilite",
        "stability",
        "stabiliteit",

        "bioburden",

        "endotoxines",
        "endotoxin",
        "endotoxins",
        "endosafe",
        "endosafe mcs",

        "asepsie",
        "aseptic",
        "aseptic technique",
        "aseptisch",

        "cleanroom",
        "clean room",
        "zone propre",
        "salle blanche",
        "cleanroomomgeving",

        "environmental monitoring",
        "monitoring environnemental",
        "omgevingsmonitoring",

        "water sampling",
        "échantillonnage eau",
        "waterbemonstering",

        "ph",
        "ph meter",
        "ph-meter",

        "conductivité",
        "conductivite",
        "conductivity",
        "geleidbaarheid",

        "cleaning validation",
        "validation nettoyage",
        "validation de nettoyage",
        "reinigingsvalidatie",

        "peptide synthesis",
        "synthèse peptidique",
        "peptidesynthese",
    ]
)


# ============================================================
# BUSINESS
# ============================================================

BUSINESS_SKILLS = _unique([

    "business analysis",
    "business analyse",
    "analyse business",

    "business intelligence",

    "requirements analysis",
    "business requirements",
    "analyse des besoins",
    "vereistenanalyse",

    "process improvement",
    "amélioration continue",
    "continue verbetering",

    "performance management",

    "decision support",
    "aide à la décision",
    "beslissingsondersteuning",

    "kpi",

    "reporting",
    "rapportage",

    "dashboard",
    "dashboards",

    "process analysis",
    "analyse de processus",
    "procesanalyse",

    "stakeholder",

    "budget",

    "pricing",

    "sales analysis",
    "analyse des ventes",
    "verkoopanalyse",
])


# ============================================================
# SOFTWARE
# ============================================================

SOFTWARE = _unique([

    "python",
    "r",
    "rstudio",

    "sql",
    "sql server",
    "ssms",
    "ssis",

    "power bi",
    "excel",

    "sap",
    "sap qm",
    "sap mm",

    "lims",
    "trackwise",

    "hplc",
    "uplc",

    "gc",
    "ftir",

    "endosafe",
])


# ============================================================
# LANGUES
# ============================================================

LANGUAGES = {

    "french": {
        "level": "C2",
        "keywords": [
            "français",
            "francais",
            "french",
            "frans",
            "fr",
        ],
    },

    "english": {
        "level": "B1",
        "keywords": [
            "anglais",
            "english",
            "engels",
            "en",
        ],
    },

    # Niveau réel indiqué par le candidat le 20/08/2026 : A2.
    # Le B1 déclaré auparavant faisait considérer au Gate qu'une exigence
    # B1/B2 était franchissable, et laissait passer des offres exigeant de
    # travailler en néerlandais (3 offres APPLY_NOW concernées au 18/08).
    "dutch": {
        "level": "A2",
        "keywords": [
            "néerlandais",
            "neerlandais",
            "dutch",
            "nederlands",
            "nl",
        ],
    },
}


# ============================================================
# FORMATION
# ============================================================

EDUCATION_KEYWORDS = _unique([

    # Data
    "data analyst",
    "business data analyst",
    "data science",
    "business intelligence",
    "informatique",
    "computer science",
    "informatica",
    "statistiques",
    "statistics",
    "statistiek",

    # Chimie
    "chimie",
    "chemistry",
    "chemie",

    "chimie industrielle",
    "industrial chemistry",
    "industriële chemie",

    "chimie analytique",
    "analytical chemistry",
    "analytische chemie",

    "biochimie",
    "biochemistry",
    "biochemie",

    # Pharma
    "pharmaceutique",
    "pharmaceutical",
    "farmaceutisch",

    "sciences pharmaceutiques",
    "pharmaceutical sciences",
    "farmaceutische wetenschappen",

    # Diplômes génériques
    "bachelier",
    "bachelor",
    "bacheloropleiding",

    "master",
])


# ============================================================
# EXPÉRIENCE / NIVEAU
# ============================================================

JUNIOR_KEYWORDS = _unique([

    "junior",

    "débutant",
    "debutant",
    "starter",

    "première expérience",
    "premiere experience",

    "graduate",

    "entry level",
    "entry-level",

    "junior profiel",
    "startfunctie",

    "0 à 2 ans",
    "0 a 2 ans",

    "1 à 2 ans",
    "1 a 2 ans",

    "0 tot 2 jaar",
    "1 tot 2 jaar",
])


SENIOR_KEYWORDS = _unique([

    "senior",
    "lead",
    "principal",
    "expert",
    "manager",
    "head",
    "director",
    "directeur",
    "directrice",
    "verantwoordelijke",
])


SOFT_PENALTY_KEYWORDS = [

    "10 years",
    "10 ans",
    "10 jaar",

    "8 years",
    "8 ans",
    "8 jaar",

    "7 years",
    "7 ans",
    "7 jaar",

    "6 years",
    "6 ans",
    "6 jaar",

    "5+ years",
    "5+ ans",
    "5+ jaar",
]


# ============================================================
# FORMATIONS RÉELLEMENT POSSÉDÉES
# ============================================================

# Le score de formation ne dépend plus uniquement du fait
# que l'annonce répète le nom du diplôme.
#
# L'Application Gate vérifiera ensuite les exigences
# administratives exactes (Master obligatoire, agrément, etc.).

PROFILE_EDUCATION_BY_FAMILY = {

    "data_analytics": {
        "qualified":
            HAS_DATA_ANALYSIS_SPECIALIZATION,

        "label":
            "Spécialisation de bachelier Business Data Analyst",
    },

    "business_intelligence": {
        "qualified":
            HAS_DATA_ANALYSIS_SPECIALIZATION,

        "label":
            "Spécialisation de bachelier Business Data Analyst",
    },

    "business_analysis": {
        "qualified":
            HAS_DATA_ANALYSIS_SPECIALIZATION,

        "label":
            "Spécialisation de bachelier Business Data Analyst",
    },

    "data_engineering": {
        "qualified":
            HAS_DATA_ANALYSIS_SPECIALIZATION,

        "label":
            "Spécialisation de bachelier Business Data Analyst",
    },

    "chemistry_lab": {
        "qualified":
            HAS_CHEMISTRY_DEGREE,

        "label":
            "Bachelier en chimie",
    },

    "pharma_qc": {
        "qualified":
            HAS_CHEMISTRY_DEGREE,

        "label":
            "Bachelier en chimie",
    },

    "quality": {
        "qualified":
            (
                HAS_CHEMISTRY_DEGREE
                and
                YEARS_PHARMA_QC_EXPERIENCE > 0
            ),

        "label":
            "Bachelier en chimie + expérience QC/Quality",
    },

    "hybrid_data_pharma": {
        "qualified":
            (
                HAS_CHEMISTRY_DEGREE
                and
                HAS_DATA_ANALYSIS_SPECIALIZATION
            ),

        "label":
            "Bachelier en chimie + spécialisation Business Data Analyst",
    },
}


# ============================================================
# POIDS MATCHER V5
# ============================================================

# Total = 100 par famille.
#
# Différence importante par rapport à V4 :
# - le diplôme de chimie pèse réellement sur Chemistry/Lab/QC ;
# - la spécialisation BDA pèse réellement sur Data/BI ;
# - les plafonds de séniorité Data restent appliqués dans
#   le matcher, donc ce renforcement ne transforme pas
#   artificiellement un poste Senior en bon match.

FAMILY_WEIGHTS = {

    "data_analytics": {
        "job_title": 26,
        "data_skills": 28,
        "pharma_skills": 0,
        "lab_skills": 0,
        "business_skills": 7,
        "experience_level": 17,
        "location": 5,
        "languages": 4,
        "education": 13,
    },

    "business_intelligence": {
        "job_title": 26,
        "data_skills": 27,
        "pharma_skills": 0,
        "lab_skills": 0,
        "business_skills": 9,
        "experience_level": 17,
        "location": 5,
        "languages": 4,
        "education": 12,
    },

    "business_analysis": {
        "job_title": 25,
        "data_skills": 10,
        "pharma_skills": 0,
        "lab_skills": 0,
        "business_skills": 27,
        "experience_level": 17,
        "location": 5,
        "languages": 4,
        "education": 12,
    },

    "data_engineering": {
        "job_title": 26,
        "data_skills": 32,
        "pharma_skills": 0,
        "lab_skills": 0,
        "business_skills": 3,
        "experience_level": 17,
        "location": 5,
        "languages": 4,
        "education": 13,
    },

    "chemistry_lab": {
        "job_title": 28,
        "data_skills": 0,
        "pharma_skills": 10,
        "lab_skills": 29,
        "business_skills": 0,
        "experience_level": 18,
        "location": 4,
        "languages": 2,
        "education": 9,
    },

    "pharma_qc": {
        "job_title": 27,
        "data_skills": 0,
        "pharma_skills": 18,
        "lab_skills": 27,
        "business_skills": 0,
        "experience_level": 17,
        "location": 3,
        "languages": 2,
        "education": 6,
    },

    "quality": {
        "job_title": 25,
        "data_skills": 2,
        "pharma_skills": 33,
        "lab_skills": 8,
        "business_skills": 4,
        "experience_level": 17,
        "location": 3,
        "languages": 2,
        "education": 6,
    },

    "hybrid_data_pharma": {
        "job_title": 20,
        "data_skills": 21,
        "pharma_skills": 18,
        "lab_skills": 11,
        "business_skills": 4,
        "experience_level": 14,
        "location": 3,
        "languages": 2,
        "education": 7,
    },
}


# ============================================================
# ALIASES MULTILINGUES POUR LE MATCHER
# ============================================================

# Le matcher importe cette structure et la fusionne avec
# ses concepts historiques.
#
# Les clés restent stables et les variantes FR/EN/NL
# comptent comme UN concept, pas plusieurs points.

MULTILINGUAL_CONCEPT_ALIASES = {}


for concept, language_map in (
    DATA_SEARCH_CONCEPTS.items()
):

    MULTILINGUAL_CONCEPT_ALIASES[
        f"data_{concept}"
    ] = _unique(
        language_map.get("fr", [])
        +
        language_map.get("en", [])
        +
        language_map.get("nl", [])
    )


for concept, language_map in (
    CHEMISTRY_LAB_SEARCH_CONCEPTS.items()
):

    MULTILINGUAL_CONCEPT_ALIASES[
        f"chem_{concept}"
    ] = _unique(
        language_map.get("fr", [])
        +
        language_map.get("en", [])
        +
        language_map.get("nl", [])
    )


# ============================================================
# HELPERS PUBLICS
# ============================================================

def get_all_target_titles():

    titles = []

    for values in (
        TARGET_JOB_FAMILIES.values()
    ):

        titles.extend(
            values
        )

    return _unique(
        titles
    )


def get_all_skills():

    return _unique(
        DATA_SKILLS
        +
        PHARMA_QUALITY_SKILLS
        +
        LAB_SKILLS
        +
        BUSINESS_SKILLS
    )


def get_all_language_keywords():

    keywords = []

    for language in (
        LANGUAGES.values()
    ):

        keywords.extend(
            language[
                "keywords"
            ]
        )

    return _unique(
        keywords
    )


def get_collection_search_terms():

    return list(
        COLLECTION_SEARCH_TERMS
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print(
        "Profil :",
        PROFILE_NAME
    )

    print(
        "Type :",
        PROFILE_TYPE
    )

    print()

    print(
        "Expérience Pharma/QC :",
        YEARS_PHARMA_QC_EXPERIENCE,
        "ans"
    )

    print()

    print(
        "Expérience par famille :"
    )

    for family, data in (
        EXPERIENCE_PROFILE.items()
    ):

        print(
            f"{family:<25}",
            data
        )

    print()

    print(
        "Nombre d'intitulés matcher :",
        len(
            get_all_target_titles()
        )
    )

    print(
        "Nombre de compétences matcher :",
        len(
            get_all_skills()
        )
    )

    print(
        "Termes collecte DATA :",
        len(
            DATA_COLLECTION_SEARCH_TERMS
        )
    )

    print(
        "Termes collecte CHIMIE/LAB :",
        len(
            CHEMISTRY_LAB_COLLECTION_SEARCH_TERMS
        )
    )

    print(
        "Termes collecte TOTAL :",
        len(
            COLLECTION_SEARCH_TERMS
        )
    )

    print()

    for language in (
        "fr",
        "en",
        "nl",
    ):

        count = 0

        for language_map in (
            list(
                DATA_SEARCH_CONCEPTS.values()
            )
            +
            list(
                CHEMISTRY_LAB_SEARCH_CONCEPTS.values()
            )
        ):

            if language_map.get(
                language
            ):

                count += 1

        print(
            f"Concepts couverts en {language.upper()} :",
            count
        )
