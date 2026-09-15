"""
JOB HUNTER BELGIUM
EMPLOYEURS WORKDAY - CONFIG V1.0

Pourquoi cette source existe
---------------------------
Mesuré le 20/08/2026 : sur 39 grands employeurs pharma/chimie belges, 7
seulement apparaissaient dans la base, presque tous via SmartRecruiters.
GSK, Janssen, Takeda, Baxter, Sanofi, Solvay, Umicore étaient absents.

Ces entreprises ne publient ni sur Forem/Actiris, ni sur Greenhouse,
Recruitee ou SmartRecruiters. Elles publient sur leur propre site carrière,
propulsé par Workday. C'est le seul chemin vers les employeurs pharma
directs, et donc vers la track LAB_QC en dehors de l'intérim.

Nature de l'accès
-----------------
Le connecteur interroge l'endpoint JSON que la page carrière publique
utilise elle-même. Aucune authentification, aucun blocage, aucune
protection contournée.

À distinguer du cas Jobat, écarté dans ce projet : Jobat renvoie un 403
pour bloquer les accès automatisés, et y accéder supposait de piloter un
navigateur pour passer outre. Ici il n'y a rien à contourner.

Réserve assumée : contrairement à Greenhouse, Recruitee et
SmartRecruiters, ce n'est pas une API documentée pour un usage externe.
C'est l'API interne d'un site public. Les conditions varient d'un
employeur à l'autre et l'endpoint peut changer sans préavis. Le connecteur
est donc écrit pour échouer proprement plutôt que pour insister.

Comment trouver un tenant
-------------------------
L'URL d'un site carrière Workday a cette forme :

    https://<tenant>.wd<N>.myworkdayjobs.com/<site>

Les trois éléments varient. L'outil diagnostics/workday_discovery.py teste
les combinaisons courantes et confirme celles qui répondent.

Tenants confirmés par requête réelle le 20/08/2026.
"""

WORKDAY_VERSION = "1.0"

WORKDAY_COMPANIES = [
    # Décomptes belges MESURÉS le 20/08/2026, pas les totaux mondiaux.
    # Un tenant sans offre belge est désactivé : il coûte des requêtes à
    # chaque run sans rien rapporter, et se réactive en une ligne.
    {
        "tenant": "gsk", "wd": "wd5", "site": "GSKCareers", "label": "GSK",
        "tracks": ["LAB_QC", "QUALITY", "PRODUCTION_SCIENCE"],
        "enabled": True,
        "notes": "50 offres belges. Wavre et Rixensart : QA, QC, production. "
                 "Ancien employeur du candidat (05/2022-05/2023).",
    },
    {
        "tenant": "jj", "wd": "wd5", "site": "JJ",
        "label": "Johnson & Johnson / Janssen",
        "tracks": ["LAB_QC", "QUALITY", "PRODUCTION_SCIENCE", "DATA"],
        "enabled": True,
        "notes": "135 résultats belges au 20/08 : Beerse, Geel. Le tenant est "
                 "'jj' et non 'jnj' — trouvé en lisant l'URL Workday dans le "
                 "HTML de careers.jnj.com, la sonde par devinette ayant échoué. "
                 "Sites flamands : beaucoup d'annonces en néerlandais.",
    },
    {
        "tenant": "abbott", "wd": "wd5", "site": "AbbottCareers", "label": "Abbott",
        "tracks": ["LAB_QC", "QUALITY", "PRODUCTION_SCIENCE"],
        "enabled": True,
        "notes": "12 offres belges. Machelen : Quality Operator, Operations "
                 "Support Technician. Diagnostic et dispositifs médicaux.",
    },
    {
        "tenant": "thermofisher", "wd": "wd5", "site": "ThermofisherCareers",
        "label": "Thermo Fisher",
        "tracks": ["LAB_QC", "CHEMISTRY", "QUALITY"],
        "enabled": True,
        "notes": "9 offres belges. Merelbeke, Gand : CMC analytique, "
                 "instrumentation de laboratoire.",
    },
    {
        "tenant": "danaher", "wd": "wd1", "site": "DanaherJobs", "label": "Danaher",
        "tracks": ["LAB_QC", "QUALITY", "PRODUCTION_SCIENCE"],
        "enabled": True,
        "notes": "6 offres belges. Bornem : Quality Engineer. Hoegaarden : "
                 "technicien. Groupe sciences de la vie (Cytiva, Pall, Beckman).",
    },
    {
        "tenant": "pfizer", "wd": "wd1", "site": "PfizerCareers", "label": "Pfizer",
        "tracks": ["LAB_QC", "QUALITY", "PRODUCTION_SCIENCE"],
        "enabled": True,
        "notes": "6 offres belges. Site de Puurs.",
    },
    {
        "tenant": "medtronic", "wd": "wd1", "site": "MedtronicCareers",
        "label": "Medtronic",
        "tracks": ["QUALITY", "PRODUCTION_SCIENCE"],
        "enabled": True,
        "notes": "2 offres belges (Bruxelles). Dispositifs médicaux.",
    },
    {
        "tenant": "amgen", "wd": "wd1", "site": "Careers", "label": "Amgen",
        "tracks": ["LAB_QC", "QUALITY"],
        "enabled": True,
        "notes": "2 offres belges (Diegem).",
    },
    {
        "tenant": "viatris", "wd": "wd5", "site": "External", "label": "Viatris",
        "tracks": ["LAB_QC", "QUALITY"],
        "enabled": True,
        "notes": "2 offres belges (Hoeilaart).",
    },
    {
        "tenant": "astrazeneca", "wd": "wd3", "site": "Careers",
        "label": "AstraZeneca",
        "tracks": ["LAB_QC", "QUALITY"],
        "enabled": True,
        "notes": "1 offre belge au 20/08. Faible mais l'employeur est pertinent.",
    },

    {
        "tenant": "lhoist", "wd": "wd3", "site": "Careers", "label": "Lhoist",
        "tracks": ["LAB_QC", "CHEMISTRY", "PRODUCTION_SCIENCE"],
        "enabled": True,
        "notes": "2 offres belges (Nivelles, Jemelle). Groupe chaux et "
                 "minéraux, siège belge. Faible volume mais employeur "
                 "directement pertinent.",
    },

    # --- désactivés : tenant valide, aucune offre belge mesurée ---
    {
        "tenant": "sanofi", "wd": "wd3", "site": "SanofiCareers", "label": "Sanofi",
        "tracks": ["LAB_QC", "QUALITY"], "enabled": False,
        "notes": "0 offre belge au 20/08 malgré des sites à Geel et Diegem. "
                 "Réactiver si Sanofi publie en Belgique.",
    },
    {
        "tenant": "baxter", "wd": "wd1", "site": "baxter", "label": "Baxter",
        "tracks": ["LAB_QC", "QUALITY"], "enabled": False,
        "notes": "0 offre belge au 20/08 malgré Lessines et Braine-l'Alleud.",
    },
    {
        "tenant": "lonza", "wd": "wd3", "site": "Lonza_Careers", "label": "Lonza",
        "tracks": ["LAB_QC", "QUALITY"], "enabled": False,
        "notes": "0 offre belge au 20/08 (16 résultats, aucun en Belgique).",
    },
    {
        "tenant": "catalent", "wd": "wd1", "site": "External", "label": "Catalent",
        "tracks": ["LAB_QC", "QUALITY"], "enabled": False,
        "notes": "0 offre belge au 20/08.",
    },
    {
        "tenant": "stryker", "wd": "wd1", "site": "StrykerCareers", "label": "Stryker",
        "tracks": ["QUALITY"], "enabled": False,
        "notes": "0 offre belge au 20/08.",
    },
    {
        "tenant": "novartis", "wd": "wd3", "site": "Novartis_Careers",
        "label": "Novartis", "tracks": ["LAB_QC", "QUALITY"], "enabled": False,
        "notes": "0 offre belge au 20/08.",
    },
    {
        "tenant": "sartorius", "wd": "wd3", "site": "SartoriusCareers",
        "label": "Sartorius", "tracks": ["LAB_QC"], "enabled": False,
        "notes": "0 offre belge au 20/08.",
    },
    {
        "tenant": "terumo", "wd": "wd3", "site": "External", "label": "Terumo",
        "tracks": ["QUALITY", "PRODUCTION_SCIENCE"], "enabled": False,
        "notes": "0 offre belge au 20/08 malgré le site de Haasrode.",
    },
    {
        "tenant": "zoetis", "wd": "wd5", "site": "zoetis", "label": "Zoetis",
        "tracks": ["LAB_QC"], "enabled": False,
        "notes": "0 offre belge au 20/08.",
    },
    {
        "tenant": "msd", "wd": "wd5", "site": "SearchJobs", "label": "MSD",
        "tracks": ["LAB_QC", "QUALITY"], "enabled": False,
        "notes": "0 offre belge au 20/08. Tenant trouvé par empreinte ATS.",
    },
    {
        "tenant": "elanco", "wd": "wd5", "site": "External_Career",
        "label": "Elanco", "tracks": ["LAB_QC"], "enabled": False,
        "notes": "0 offre belge au 20/08.",
    },
    {
        "tenant": "unilever", "wd": "wd3",
        "site": "Unilever_Experienced_Professionals", "label": "Unilever",
        "tracks": ["QUALITY", "PRODUCTION_SCIENCE"], "enabled": False,
        "notes": "0 offre belge au 20/08.",
    },
]



def enabled_companies():
    configures = [c for c in WORKDAY_COMPANIES if c.get("enabled")]
    # Employeurs decouverts automatiquement (config/ats_employers_v2.json) :
    # ajoutes a la suite, sans jamais remplacer une entree de cette liste.
    try:
        from sources.ats_employers_v2 import fusionner
        return fusionner("WORKDAY_ATS", configures)
    except Exception:
        return configures
