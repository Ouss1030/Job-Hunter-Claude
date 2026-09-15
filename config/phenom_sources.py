"""
JOB HUNTER BELGIUM
EMPLOYEURS PHENOM - CONFIG V1.0

Nature de l'accès
-----------------
Les sites carrière Phenom publient un sitemap.xml et exposent sur chaque
page d'offre un bloc JSON-LD `schema.org/JobPosting` — le format que Google
for Jobs exige, et qui existe précisément pour être lu par des machines.

C'est la meilleure qualité de données du projet, devant Workday et
SuccessFactors : titre, date de publication, géolocalisation et description
complète arrivent structurés, sans analyse de mise en page. Un changement
de design du site ne casse donc pas ce connecteur.

Le robots.txt d'UCB n'interdit que /apply, /chatbot, /jobcart et les
widgets ; les pages d'offres sont ouvertes. Rien à contourner.

Comment ajouter un employeur
----------------------------
1. python -m diagnostics.ats_fingerprint --entreprise <domaine>
   doit répondre PHENOM.
2. Repérer l'hôte du site carrière (careers.<domaine> en général).
3. Vérifier que https://<hote>/sitemap.xml contient des URL /job/.
4. Ajouter l'entrée ci-dessous, puis lancer
   python -m diagnostics.phenom_v1_live_test

Mesures du 22/08/2026.
"""

PHENOM_VERSION = "1.0"

PHENOM_COMPANIES = [
    {
        "host": "careers.ucb.com",
        "label": "UCB",
        "tracks": ["LAB_QC", "QUALITY", "PRODUCTION_SCIENCE", "DATA"],
        "enabled": True,
        "notes": "357 offres au sitemap, ~102 belges estimées. Sites de "
                 "Braine-l'Alleud et Anderlecht : francophones, contrairement "
                 "à J&J Beerse. Pharma belge, employeur cible prioritaire.",
    },
    {
        "host": "www.pgcareers.com",
        "label": "Procter & Gamble",
        "tracks": ["QUALITY", "PRODUCTION_SCIENCE", "DATA"],
        "enabled": True,
        "notes": "Site de production à Malines. À confirmer par le test live.",
    },
    {
        "host": "careers.proximus.com",
        "label": "Proximus",
        "tracks": ["DATA", "BI"],
        "enabled": True,
        "notes": "Télécom belge, forte activité data. À confirmer.",
    },
    {
        "host": "careers.roche.com",
        "label": "Roche",
        "tracks": ["LAB_QC", "QUALITY"],
        "enabled": False,
        "notes": "Peu de présence belge attendue. Activer après vérification.",
    },
]


def enabled_companies():
    configures = [c for c in PHENOM_COMPANIES if c.get("enabled")]
    # Employeurs decouverts automatiquement (config/ats_employers_v2.json) :
    # ajoutes a la suite, sans jamais remplacer une entree de cette liste.
    try:
        from sources.ats_employers_v2 import fusionner
        return fusionner("PHENOM_ATS", configures)
    except Exception:
        return configures
