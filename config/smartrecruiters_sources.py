"""
JOB HUNTER BELGIUM
SMARTRECRUITERS DIRECT EMPLOYERS - CONFIG V1.0

Liste volontairement courte pour le premier test réel.
On pourra ajouter des employeurs après validation sans modifier le connecteur.
"""

SMARTRECRUITERS_VERSION = "1.0"

SMARTRECRUITERS_COMPANIES = [
    {
        "identifier": "SGS",
        "label": "SGS",
        "tracks": ["LAB_QC", "CHEMISTRY", "QUALITY"],
        "enabled": True,
    },
    {
        "identifier": "Eurofins",
        "label": "Eurofins",
        "tracks": ["LAB_QC", "CHEMISTRY", "QUALITY", "DATA"],
        "enabled": True,
    },
    {
        "identifier": "devoteam",
        "label": "Devoteam",
        "tracks": ["DATA", "BI"],
        "enabled": True,
    },
    {
        "identifier": "arhs",
        "label": "Arhs Group",
        "tracks": ["DATA", "BI"],
        "enabled": True,
    },
    {
        "identifier": "SopraSteria1",
        "label": "Sopra Steria",
        "tracks": ["DATA", "BI"],
        "enabled": True,
    },
]

SMARTRECRUITERS_COUNTRY = "be"
SMARTRECRUITERS_PAGE_SIZE = 100
SMARTRECRUITERS_TIMEOUT_SECONDS = 25

# Limite de détails récupérés dans le diagnostic live.
# None = toutes les offres belges trouvées.
SMARTRECRUITERS_LIVE_DETAIL_LIMIT = None

# Nombre d'offres pertinentes affichées dans le TXT.
SMARTRECRUITERS_TOP_N = 80
