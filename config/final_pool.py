"""
JOB HUNTER BELGIUM
FINAL APPLICATION POOL - CONFIG V1.1

V1.1 corrige V1.0 :
- dédoublonnage live plus robuste ;
- garde-fou final basé sur la description complète ;
- langue / credentials / compétences obligatoires ;
- quality hors domaine mécanique/métrologie ;
- Data adjacent traité avec prudence.
"""

FINAL_POOL_VERSION = "1.1"

CANDIDATE_LANGUAGES = {
    "fr": "C2",
    "en": "B1",
    "nl": "A2",
}

KNOWN_CREDENTIALS = {
    # Absence de preuve dans le profil connu = False.
    "forklift": False,
    "medical_lab_accreditation": False,
}

KNOWN_SKILLS = {
    "hplc": True,
    "uplc": True,
    "gmp": True,
    "sap": True,
    "lims": True,
    "trackwise": True,
    "microbiology": True,
    "endosafe": True,
    "cell_culture": False,
    "gdandt": False,
    "cmm": False,
    "metrology_precision": False,
    "haccp": False,
}

PREFERRED_LOCATION_TERMS = [
    "bruxelles", "brussel", "anderlecht", "saint-gilles", "sint-gillis",
    "woluwe", "uccle", "ukkel", "watermael-boitsfort", "watermaal-bosvoorde",
    "schaerbeek", "schaarbeek", "jette", "evere", "auderghem", "oudergem",
    "etterbeek", "ixelles", "elsene", "forest", "vorst", "molenbeek",
    "koekelberg", "ganshoren", "berchem", "saint-josse", "sint-joost",
    "zaventem", "diegem", "machelen", "vilvoorde", "drogenbos", "kortenberg",
    "wavre", "waver", "rixensart", "waterloo", "braine-l'alleud",
    "braine l'alleud", "ottignies", "louvain-la-neuve", "louvain la neuve",
    "1000", "1020", "1030", "1040", "1050", "1060", "1070", "1080",
    "1081", "1082", "1083", "1090", "1120", "1130", "1140", "1150",
    "1160", "1170", "1180", "1190", "1200", "1210",
    "1348", "1300", "1301", "1330", "1410", "1420", "1930", "1830", "3070",
]

CORE_LAB_TERMS = [
    "laborantin", "laborant", "laboratory technician", "lab technician",
    "technicien de laboratoire", "technicien laboratoire", "technicien chimiste",
    "chimiste", "chemist", "chemistry", "qc lab", "laboratory analyst",
    "lab analyst", "hplc", "uplc", "microbiolog",
]

PRODUCTION_SCIENCE_TERMS = [
    "production secteur chimie", "productieoperator chemie",
    "opérateur de production en chimie", "operateur de production en chimie",
    "opérateur de synthèse", "operateur de synthese",
    "salle blanche", "clean room", "cleanroom",
    "stérilisation pharmaceutique", "sterilisation pharmaceutique",
    "biotechnologie", "biotechnology",
    "préparation et production", "preparation et production",
    "opérateur technique de production", "operateur technique de production",
    "opérateur de production", "operateur de production",
    "production operator", "productieoperator",
]

QUALITY_TERMS = [
    "quality", "qualité", "qualite", "kwaliteits",
    "assurance qualité", "assurance qualite",
    "contrôle qualité", "controle qualite",
]

DATA_TERMS = [
    "data analyst", "data analist", "business data analyst",
    "business intelligence", "bi analyst", "bi developer",
    "power bi", "financial data analyst",
]

OFF_DOMAIN_TITLE_TERMS = [
    "piping", "soudure", "welding", "béton", "beton",
    "mécanique de précision", "mecanique de precision",
    "metaal", "metal", "construction", "carrosserie", "automobile",
]

# Description live : hors domaine mécanique / métrologie.
MECHANICAL_QUALITY_HARD_TERMS = [
    "contrôle tridimensionnel", "controle tridimensionnel", "mmt",
    "gd&t", "tolérancement géométrique", "tolerancement geometrique",
    "micromètre", "micrometre", "rugosimètre", "rugosimetre",
    "lecture de plans", "dessins industriels complexes",
    "mécanique de précision", "mecanique de precision",
    "first article inspection", "fai",
]

MECHANICAL_CONTEXT_TERMS = [
    "aéronautique", "aeronautique", "spatial", "défense", "defense",
    "pièces usinées", "pieces usinees", "métrologie", "metrologie",
]

HOSPITAL_QUALITY_TERMS = [
    "sécurité des soins", "securite des soins",
    "événements indésirables associés aux soins",
    "evenements indesirables associes aux soins",
    "qualité et sécurité des soins", "qualite et securite des soins",
    "patient", "institution hospitalière", "institution hospitaliere",
]

ELECTRICAL_QA_DEGREE_TERMS = [
    "bachelier en instrumentation",
    "bachelier en électricité",
    "bachelier en electricite",
    "bachelier en électromécanique",
    "bachelier en electromecanique",
]

# Dédoublonnage.
DUP_JACCARD_STRONG = 0.84
DUP_JACCARD_SAME_LOCATION = 0.70
DUP_TITLE_SAME_LOCATION = 0.80

MAX_TXT_ITEMS = 120
