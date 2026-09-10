"""
JOB HUNTER BELGIUM
EMPLOYEURS SUCCESSFACTORS - CONFIG V1.0

Nature de l'accès — à lire avant d'ajouter un employeur
------------------------------------------------------
SuccessFactors n'expose aucune API publique documentée, contrairement à
Greenhouse, Recruitee ou SmartRecruiters. Vérifié le 20/08/2026 : sept
variantes d'endpoints (flux RSS, /services/xrm/, paramètres JSON) renvoient
toutes du HTML, et les pages ne portent pas de JSON-LD.

Ce connecteur lit donc le HTML. C'est le premier du projet dans ce cas, et
cela change trois choses :

  - il est plus fragile : un changement de mise en page le casse, là où une
    API a un contrat ;
  - il coûte une requête par offre, contre une pagination unique ailleurs ;
  - il demandera de la maintenance quand un site évoluera.

Ce qui rend l'accès légitime, et le distingue du cas Jobat écarté :

  - le robots.txt de ces sites autorise explicitement les chemins /job/
    (il ne bloque que /applybutton/, /talentcommunity/, /emailsubscribe/,
    /services/, /preapply/) ;
  - un sitemap.xml public liste les offres — un sitemap existe précisément
    pour que les machines indexent le site ;
  - le contenu est rendu côté serveur : aucun navigateur, aucun blocage à
    contourner.

Jobat renvoyait un 403 pour bloquer les accès automatisés. Ici le site
publie de quoi être lu.

Comment ajouter un employeur
----------------------------
1. python -m diagnostics.ats_fingerprint --entreprise <domaine>
   doit répondre SUCCESSFACTORS.
2. Trouver l'hôte du site carrière (jobs.<domaine> ou careers.<domaine>).
3. Vérifier que https://<hote>/sitemap.xml répond et contient des /job/.
4. Ajouter l'entrée ci-dessous, puis lancer
   python -m diagnostics.successfactors_v1_live_test

Décomptes belges mesurés le 20/08/2026 via les sitemaps.
"""

SUCCESSFACTORS_VERSION = "1.0"

SUCCESSFACTORS_COMPANIES = [
    {
        "host": "careers.umicore.com",
        "label": "Umicore",
        "tracks": ["LAB_QC", "CHEMISTRY", "PRODUCTION_SCIENCE", "QUALITY"],
        "enabled": True,
        "notes": "208 offres au sitemap, ~85 belges. Hoboken, Olen, Bruxelles. "
                 "Métallurgie et chimie des matériaux : laboratoires d'analyse.",
    },
    {
        "host": "jobs.puratos.com",
        "label": "Puratos",
        "tracks": ["LAB_QC", "QUALITY", "PRODUCTION_SCIENCE"],
        "enabled": True,
        "notes": "170 offres au sitemap, ~36 belges. Groot-Bijgaarden. "
                 "Agroalimentaire : contrôle qualité et laboratoires.",
    },
    {
        "host": "jobs.aquafin.be",
        "label": "Aquafin",
        "tracks": ["LAB_QC", "CHEMISTRY", "PRODUCTION_SCIENCE"],
        "enabled": True,
        "notes": "35 offres, ~8 belges. Traitement des eaux : procédés et "
                 "analyses. Annonces majoritairement en néerlandais.",
    },
    {
        "host": "careers.syensqo.com",
        "label": "Syensqo",
        "tracks": ["LAB_QC", "CHEMISTRY"],
        "enabled": True,
        "notes": "139 offres, ~7 belges (Bruxelles). Issu de la scission Solvay.",
    },
    {
        "host": "careers.solvay.com",
        "label": "Solvay",
        "tracks": ["LAB_QC", "CHEMISTRY"],
        "enabled": True,
        "notes": "59 offres, ~5 belges (Bruxelles).",
    },
]


def enabled_companies():
    return [c for c in SUCCESSFACTORS_COMPANIES if c.get("enabled")]
