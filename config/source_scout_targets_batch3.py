"""JOBHUNTER - SOURCE SCOUT BATCH 3 DUAL TRACK.

Deux axes indépendants :
- DATA_JUNIOR
- LAB_QC

Ce fichier ne branche aucune source dans le pipeline.
"""

SOURCE_SCOUT_TARGETS = [
    # DATA JUNIOR
    {
        "key": "ACTIRIS",
        "label": "Actiris",
        "track": "DATA_JUNIOR",
        "url": "https://www.actiris.brussels/fr/citoyens/offres-demploi/",
        "priority": 1,
        "notes": "Agrégateur Bruxelles; peut exposer Junior Data/Business Analyst et rôles FR/EN.",
    },
    {
        "key": "DELAWARE",
        "label": "delaware Belgium",
        "track": "DATA_JUNIOR",
        "url": "https://www.delaware.pro/fr-be/careers",
        "priority": 2,
        "notes": "Junior Data & AI Consultant; SQL/Python/Power BI; no experience/young professional.",
    },
    {
        "key": "PWC_BE",
        "label": "PwC Belgium",
        "track": "DATA_JUNIOR",
        "url": "https://www.pwc.be/en/careers/students-graduates.html",
        "priority": 3,
        "notes": "Early careers; Business/Data Analytics et Technology/Advisory.",
    },
    {
        "key": "DELOITTE_BE",
        "label": "Deloitte Belgium",
        "track": "DATA_JUNIOR",
        "url": "https://www.deloitte.com/be/en/careers/graduates.html",
        "priority": 4,
        "notes": "Graduate Data & Analytics / AI & Data; vérifier niveau de diplôme et langues.",
    },
    {
        "key": "EY_BE",
        "label": "EY Belgium",
        "track": "DATA_JUNIOR",
        "url": "https://eycareers.be/fr/vacancies/",
        "priority": 5,
        "notes": "Graduate/entry-level Technology, Data & Analytics; Diegem/Brussels.",
    },
    {
        "key": "KPMG_BE",
        "label": "KPMG Belgium",
        "track": "DATA_JUNIOR",
        "url": "https://kpmg.com/be/en/careers/graduates.html",
        "priority": 6,
        "notes": "Graduate Technology/Engineering/Mathematics & Business Consulting.",
    },
    {
        "key": "SMALS",
        "label": "Smals",
        "track": "DATA_JUNIOR",
        "url": "https://www.smals.be/fr/jobs/list",
        "priority": 7,
        "notes": "Bruxelles; Data Functional Analyst, Data Quality, BI, statistiques; vérifier séniorité.",
    },

    # LAB / QC
    {
        "key": "SGS",
        "label": "SGS Belgium",
        "track": "LAB_QC",
        "url": "https://careers.smartrecruiters.com/SGS?search=wavre",
        "priority": 1,
        "notes": "Wavre; Bioanalysis, Biochimie, Molecular Biology, QA/GMP; SmartRecruiters existant.",
    },
    {
        "key": "CER_GROUPE",
        "label": "CER Groupe",
        "track": "LAB_QC",
        "url": "https://cergroupe.be/fr/emplois",
        "priority": 2,
        "notes": "Wallonie; recherche, bioproduction, testing, laboratoire; candidatures spontanées possibles.",
    },
    {
        "key": "CERBA_BE",
        "label": "Cerba HealthCare Belgium",
        "track": "LAB_QC",
        "url": "https://fr.jobs.cerbahealthcare.com/nos-entites/cerba-healthcare-belgium-recrute",
        "priority": 3,
        "notes": "Anderlecht/Gand; laboratoires médicaux, microbiologie, technologue labo.",
    },
    {
        "key": "LHOIST",
        "label": "Lhoist",
        "track": "LAB_QC",
        "url": "https://www.lhoist.com/en/about-us/careers",
        "priority": 4,
        "notes": "Belgique/Wallonie; chimie, qualité, R&D et early careers.",
    },
    {
        "key": "TOTALENERGIES",
        "label": "TotalEnergies",
        "track": "LAB_QC",
        "url": "https://jobs.totalenergies.com/fr_FR/careers",
        "priority": 5,
        "notes": "Belgique; laboratoire, chimie, quality et data possibles; portail global filtrable.",
    },
    {
        "key": "EXXONMOBIL",
        "label": "ExxonMobil Benelux",
        "track": "LAB_QC",
        "url": "https://jobs.exxonmobil.com/",
        "priority": 6,
        "notes": "Anvers; laboratoire/analytical/process/quality; portail global.",
    },
    {
        "key": "ASTRAZENECA",
        "label": "AstraZeneca",
        "track": "LAB_QC",
        "url": "https://careers.astrazeneca.com/location/belgium-country-jobs/7684/2802361/2",
        "priority": 7,
        "notes": "Déjà scoutée; Radancy disponible, à requalifier spécifiquement Lab/QC/Data junior.",
    },
]
