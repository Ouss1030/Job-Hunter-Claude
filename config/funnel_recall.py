"""
JOB HUNTER BELGIUM
FUNNEL RECALL AUDIT - CONFIG V1.0

Cette configuration ne change AUCUNE décision du Matcher/Gate/Queue.
Elle définit uniquement les familles de titres que l'audit doit suivre
depuis le RAW jusqu'à la Queue.

L'objectif est le RECALL :
mieux vaut faire remonter trop de titres pour inspection que manquer
un vrai poste intéressant.
"""

FUNNEL_RECALL_VERSION = "1.0"

# Titres / concepts que l'utilisateur veut explicitement surveiller.
# FR / NL / EN pour couvrir les principales sources belges.
WATCH_BUCKETS = {
    "LAB_CORE": [
        "laborantin",
        "laborant",
        "laboratory technician",
        "laboratory technologist",
        "lab technician",
        "lab technologist",
        "technicien de laboratoire",
        "technicien laboratoire",
        "technologue de laboratoire",
        "laboratory analyst",
        "lab analyst",
        "analyste laboratoire",
        "analyste de laboratoire",
        "laboratoriumtechnicus",
        "laboratorium medewerker",
        "laboratoriummedewerker",
    ],
    "CHEMISTRY": [
        "chimiste",
        "chemist",
        "chemicus",
        "technicien chimiste",
        "chemical technician",
        "chemisch laborant",
        "analytical chemist",
        "analytisch laborant",
    ],
    "QC_QUALITY": [
        "qc",
        "quality control",
        "contrôle qualité",
        "controle qualite",
        "qc analyst",
        "qc technician",
        "qc technicien",
        "quality technician",
        "quality coordinator",
        "quality officer",
        "quality assistant",
        "quality medewerker",
        "kwaliteitsmedewerker",
        "kwaliteitscontrole",
        "kwaliteitscontroleur",
        "controleur qualité",
        "contrôleur qualité",
        "technicien qualité",
    ],
    "PHARMA_BIOTECH": [
        "pharma",
        "pharmaceutical",
        "farmaceut",
        "biotech",
        "biotechnology",
        "biotechnologie",
        "biochem",
        "microbiolog",
        "microbiology",
        "microbiologie",
    ],
    "PRODUCTION_ADJACENT": [
        "technicien de production",
        "technicien production",
        "production technician",
        "production technologist",
        "productietechnieker",
        "productietechnicus",
        "opérateur de production",
        "operateur de production",
        "production operator",
        "productieoperator",
        "operator productie",
        "process technician",
        "process operator",
        "procestechnieker",
        "manufacturing technician",
        "manufacturing operator",
        "technicien process",
        "technicien procédé",
        "technicien procede",
    ],
    "ANALYTICAL_INSTRUMENTS": [
        "hplc",
        "uplc",
        "chromatograph",
        "spectrometr",
        "spectrométr",
        "gc-ms",
        "lc-ms",
    ],
    "DATA_BI": [
        "data analyst",
        "data analist",
        "business data analyst",
        "business intelligence",
        "bi analyst",
        "bi developer",
        "power bi",
        "reporting analyst",
        "reporting analist",
        "data quality",
        "data engineer",
        "data scientist",
    ],
}

# Contexte qui rend un titre générique de production particulièrement
# intéressant pour le profil chimie/pharma/QC.
PRODUCTION_CONTEXT_TERMS = [
    "pharma",
    "pharmaceutical",
    "farmaceut",
    "chimie",
    "chemie",
    "chemical",
    "laboratoire",
    "laboratorium",
    "laboratory",
    "quality",
    "qualité",
    "kwaliteit",
    "qc",
    "gmp",
    "bpf",
    "microbiolog",
    "biotech",
    "biochem",
    "medical",
    "médical",
]

# Les buckets ci-dessous sont considérés comme suffisamment proches du profil
# pour déclencher une alerte HIGH si le Matcher les écarte AVANT détail.
HIGH_RECALL_BUCKETS = {
    "LAB_CORE",
    "CHEMISTRY",
    "QC_QUALITY",
    "ANALYTICAL_INSTRUMENTS",
}

# PRODUCTION_ADJACENT devient HIGH uniquement si le contexte scientifique /
# pharma / qualité est présent.
MAX_LOST_ITEMS_IN_TXT = 120
MAX_BACKLOG_ITEMS_IN_TXT = 100
