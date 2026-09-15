"""
JOB HUNTER BELGIUM
EMPLOYEURS RECRUITEE - CONFIG V1.0

Même principe que config/smartrecruiters_sources.py : ajouter un employeur
ne doit jamais demander de toucher au connecteur.

Comment trouver l'identifiant
-----------------------------
Ouvrir la page carrière de l'entreprise et regarder l'URL. Si elle contient
`<identifiant>.recruitee.com`, ou si la page renvoie vers `jobs.<domaine>`
propulsé par Recruitee, l'identifiant est celui du sous-domaine.

Vérification en une requête :

    https://<identifiant>.recruitee.com/api/offers/

Une réponse 200 avec une clé "offers" confirme l'identifiant.

Employeurs ci-dessous : confirmés par requête réelle le 19/08/2026.
Le nombre d'offres est celui observé ce jour-là, il varie.
"""

RECRUITEE_VERSION = "1.0"

RECRUITEE_COMPANIES = [
    {
        "identifier": "vito",
        "label": "VITO",
        "tracks": ["LAB_QC", "CHEMISTRY", "DATA", "PRODUCTION_SCIENCE"],
        "enabled": True,
        "notes": "Institut flamand de recherche technologique (Mol, Genk). "
                 "Chimie, environnement, laboratoires, data. 44 offres au 19/08.",
    },
    {
        "identifier": "galapagos",
        "label": "Galapagos",
        "tracks": ["LAB_QC", "CHEMISTRY", "QUALITY"],
        "enabled": True,
        "notes": "Biotech, Mechelen. 0 offre ouverte au 19/08, conservé car "
                 "l'employeur est très pertinent quand il recrute.",
    },
    {
        "identifier": "colruytgroup",
        "label": "Colruyt Group",
        "tracks": ["QUALITY", "PRODUCTION_SCIENCE", "DATA"],
        "enabled": True,
        "notes": "Distribution alimentaire : laboratoires qualité et sécurité "
                 "alimentaire. 8 offres au 19/08.",
    },
    {
        "identifier": "nrb",
        "label": "NRB",
        "tracks": ["DATA", "BI"],
        "enabled": True,
        "notes": "Groupe informatique liégeois. 33 offres belges au 20/08. "
                 "Track DATA, et implantation wallonne.",
    },
    {
        "identifier": "dataroots",
        "label": "Dataroots",
        "tracks": ["DATA", "BI"],
        "enabled": True,
        "notes": "Cabinet data/IA belge (Louvain). 12 offres belges au 20/08. "
                 "Cible directe du Bachelier Business Data Analysis.",
    },
    {
        "identifier": "isabelgroup",
        "label": "Isabel Group",
        "tracks": ["DATA", "BI"],
        "enabled": True,
        "notes": "Fintech bruxelloise. 6 offres belges au 20/08.",
    },
    {
        "identifier": "radix",
        "label": "Radix",
        "tracks": ["DATA", "BI"],
        "enabled": True,
        "notes": "Cabinet IA belge. 4 offres belges au 20/08.",
    },
    {
        "identifier": "sweco",
        "label": "Sweco Belgium",
        "tracks": ["PRODUCTION_SCIENCE", "DATA"],
        "enabled": False,
        "notes": "Bureau d'études (173 offres). Désactivé par défaut : "
                 "surtout de l'ingénierie civile, peu de laboratoire. "
                 "À activer si le Matcher montre des résultats.",
    },
]


def enabled_companies():
    configures = [c for c in RECRUITEE_COMPANIES if c.get("enabled")]
    # Employeurs decouverts automatiquement (config/ats_employers_v2.json) :
    # ajoutes a la suite, sans jamais remplacer une entree de cette liste.
    try:
        from sources.ats_employers_v2 import fusionner
        return fusionner("RECRUITEE", configures)
    except Exception:
        return configures
