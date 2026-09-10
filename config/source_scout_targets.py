"""
JOBHUNTER - SOURCE SCOUT BATCH TARGETS V1.0

Ce fichier ne branche aucune source dans le pipeline.
Il contient uniquement les sites à qualifier en lot.
"""

SOURCE_SCOUT_TARGETS = [
    {
        "key": "SANOFI",
        "label": "Sanofi",
        "url": "https://jobs.sanofi.com/en/location/belgium-jobs/2649/2802361/2",
        "priority": 1,
        "notes": "Pharma - Geel/Ghent/Diegem/Brussels; QC et labo très pertinents.",
    },
    {
        "key": "BAXTER",
        "label": "Baxter",
        "url": "https://jobs.baxter.com/en/location/belgium-jobs/152/2802361/2",
        "priority": 2,
        "notes": "Pharma/medtech - Lessines/Braine-l'Alleud; Quality/R&D.",
    },
    {
        "key": "NOVARTIS",
        "label": "Novartis",
        "url": "https://www.novartis.com/careers/career-search/tag/LOC_BE",
        "priority": 3,
        "notes": "Pharma - Belgique; Quality/Data/Business Analyst.",
    },
    {
        "key": "ABBVIE",
        "label": "AbbVie",
        "url": "https://careers.abbvie.com/en/jobs?location=Belgium",
        "priority": 4,
        "notes": "Pharma - à qualifier.",
    },
    {
        "key": "MSD",
        "label": "MSD",
        "url": "https://jobs.msd.com/gb/en/belgium-job-search",
        "priority": 5,
        "notes": "Pharma - Bruxelles; data/statistics/clinical possibles.",
    },
    {
        "key": "CSL",
        "label": "CSL / CSL Behring",
        "url": "https://jobs.csl.com/search/?q=&locationsearch=Belgium",
        "priority": 6,
        "notes": "Biotech - à qualifier; portail global.",
    },
    {
        "key": "ZOETIS",
        "label": "Zoetis",
        "url": "https://careers.zoetis.com/",
        "priority": 7,
        "notes": "Animal health / pharma; Louvain-la-Neuve connu comme site belge.",
    },
    {
        "key": "UNIVERCELLS",
        "label": "Univercells Technologies",
        "url": "https://www.univercellstech.com/careers/open-positions/",
        "priority": 8,
        "notes": "Biomanufacturing belge; les offres redirigent vers le portail Donaldson.",
    },
]
