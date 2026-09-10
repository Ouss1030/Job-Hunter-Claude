"""
JOB HUNTER BELGIUM
EMPLOYEURS GREENHOUSE - CONFIG V1.0

Même principe que config/recruitee_sources.py et
config/smartrecruiters_sources.py : ajouter un employeur ne demande jamais
de toucher au connecteur.

Comment trouver le board_token
------------------------------
Ouvrir la page carrière de l'entreprise. Si elle est propulsée par
Greenhouse, l'URL contient :

    boards.greenhouse.io/<token>
    job-boards.greenhouse.io/<token>

Vérification en une requête :

    https://boards-api.greenhouse.io/v1/boards/<token>/jobs

Une réponse 200 avec une clé "jobs" confirme le token.

Rappel important
----------------
Greenhouse est un ATS, pas un site d'offres : on interroge un employeur,
pas la Belgique. Un employeur international renvoie ses offres du monde
entier, et le filtrage belge se fait chez nous, via sources/location_belgium.
Il est donc normal qu'un employeur ait beaucoup d'offres dont très peu de
belges.

Employeurs confirmés par requête réelle le 20/08/2026.
"""

GREENHOUSE_VERSION = "1.0"

GREENHOUSE_COMPANIES = [
    {
        "identifier": "collibra",
        "label": "Collibra",
        "tracks": ["DATA", "BI"],
        "enabled": True,
        "notes": "Data governance, siège à Bruxelles. 42 offres au 20/08, "
                 "dont 8 à Brussels, Belgium. Pertinent track DATA.",
    },
    {
        "identifier": "inthepocket",
        "label": "In The Pocket",
        "tracks": ["DATA", "BI"],
        "enabled": True,
        "notes": "Studio produit numérique (Gand). 19 offres belges au 20/08.",
    },
    {
        "identifier": "datacamp",
        "label": "DataCamp",
        "tracks": ["DATA", "BI"],
        "enabled": True,
        "notes": "Plateforme d'apprentissage data, bureau belge. "
                 "18 offres belges au 20/08.",
    },
    {
        "identifier": "showpad",
        "label": "Showpad",
        "tracks": ["DATA"],
        "enabled": False,
        "notes": "Entreprise d'origine gantoise mais 0 offre belge au 20/08 "
                 "(tout aux USA). Désactivé, à réactiver si le board change.",
    },
]


def enabled_companies():
    return [c for c in GREENHOUSE_COMPANIES if c.get("enabled")]
