"""
Source unique de vérité candidat pour Job Hunter Belgium.

Toute donnée factuelle utilisée pour générer un CV, une lettre, un e-mail
ou un bundle ChatGPT doit provenir de ce module.

Version 1.0 — Hardening Step 4B.
"""

from __future__ import annotations

from copy import deepcopy


CANDIDATE_TRUTH_VERSION = "1.0"

DEFAULT_BASE_CV_NAME = "CV_Oussama_Aharroud_LabQC.docx"


CANDIDATE_TRUTH = {
    "identity": {
        "name": "Oussama AHARROUD",
        "location": "Bruxelles, Belgique",
    },
    "education": [
        {
            "degree": "Bachelier de spécialisation en Business Data Analysis",
            "institution": "EPHEC",
            "status": "Diplôme obtenu en 2026",
            "important": (
                "Toute mention 'en cours', 'en finalisation' ou équivalente "
                "dans un ancien CV est OBSOLÈTE."
            ),
        },
        {
            "degree": "Bachelier en Chimie industrielle",
            "institution": "Institut Paul Lambin",
            "status": "Diplôme obtenu",
        },
        {
            "degree": "Sciences pharmaceutiques",
            "institution": "UCLouvain",
            "status": (
                "Études suivies jusqu'au niveau Master 1 validé ; "
                "AUCUN diplôme de Master obtenu."
            ),
        },
    ],
    "professional_experience": {
        "pharma_qc_years": 3.0,
        "data_professional_years": 0.0,
        "roles": [
            {
                "company": "GSK",
                "dates": "05/2022 – 05/2023",
                "role": "Laborantin QC",
                "facts": [
                    "Contrôle microbiologique de produits finis",
                    "Manipulation aseptique sous flux laminaire",
                    "Détermination de la biocharge",
                    "Réception, transfert et gestion d'échantillons de production",
                    "Encodage et traçabilité dans SAP/LIMS",
                    "Travail sous GMP et SOP",
                ],
            },
            {
                "company": "Prothya Biosolutions",
                "dates": "06/2020 – 02/2022",
                "role": "Laborantin QC",
                "facts": [
                    "Analyses d'endotoxines via Endosafe MCS",
                    "Prélèvements d'eau",
                    "Manipulations aseptiques",
                    "Contrôles microbiologiques",
                    "Déviations sous TrackWise",
                    "Encodage dans LIMS et SAP",
                    "Correction et mise à jour de SOP",
                ],
            },
            {
                "company": "Corden Pharma",
                "dates": "01/2017 – 04/2017",
                "role": "Stage laboratoire",
                "facts": [
                    "Analyses de produits finis par HPLC/UPLC",
                    "Lecture/interprétation de chromatogrammes",
                    "Synthèse peptidique sur support solide (SPPS)",
                    "Préparation de solutions",
                ],
            },
            {
                "company": "Institut Meurice",
                "dates": "04/2017 – 06/2017",
                "role": "Stage laboratoire",
                "facts": [
                    "Analyse quantitative de métaux lourds dans les eaux par voltampérométrie",
                    "Préparation d'échantillons",
                    "Mesures pH/conductivité",
                    "Encodage et interprétation des résultats",
                ],
            },
        ],
    },
    "data_project": [
        "Projet Business Data Analysis sur plus de 3 000 enregistrements",
        "Python : ETL, nettoyage, standardisation, déduplication et validation",
        "SQL / SQL Server / SSIS / SSMS",
        "Power BI",
        "R / statistiques",
        "Random Forest / machine learning",
        "Qualité et intégrité des données",
    ],
    "languages": {
        "Français": "C2",
        "Anglais": "B1",
        "Néerlandais": "B1",
    },
    "supported_skills": [
        "Python",
        "pandas",
        "scikit-learn",
        "SQL",
        "SQL Server",
        "SSIS",
        "SSMS",
        "Power BI",
        "R",
        "Excel",
        "Random Forest",
        "ETL",
        "GMP",
        "BPF",
        "SOP",
        "SAP QM/MM",
        "LIMS",
        "TrackWise",
        "microbiologie",
        "biocharge",
        "asepsie",
        "Endosafe MCS",
        "HPLC",
        "UPLC",
        "voltampérométrie",
        "pH",
        "conductivité",
        # Éléments présents dans l'ancien Handoff et conservés ici
        # pour qu'ils ne puissent plus diverger.
        "ALCOA+",
        "statistiques",
        "machine learning",
        "data cleaning",
        "data integrity",
    ],
    "unsupported_or_not_proven": [
        "GC comme compétence pratiquée",
        "Empower",
        "HACCP comme expérience acquise",
        "Talend",
        "Apache Hop",
        "Tableau",
        "Oracle",
        "PL/SQL",
        "agrément/visa de technologue de laboratoire médical",
        "diplôme de Master",
        "expérience professionnelle Data/BI",
        # Éléments supplémentaires auparavant présents uniquement
        # dans applications/chatgpt_handoff.py.
        "culture cellulaire",
        "métrologie mécanique / GD&T / CMM",
        "allemand professionnel",
        "brevet cariste",
    ],
}


FORBIDDEN_CANDIDATE_CLAIM_TERMS = {
    "empower": "Empower",
    "talend": "Talend",
    "apache hop": "Apache Hop",
    "pl/sql": "PL/SQL",
}


HARD_TRUTH_RULES = [
    "Ne jamais inventer une compétence ou une expérience.",
    "Ne jamais présenter le Master 1 en sciences pharmaceutiques comme un Master obtenu.",
    "Ne pas transformer environ 3 ans de QC en 2+ ans de maîtrise HPLC/GC.",
    "HPLC/UPLC doit rester formulé comme exposition/expérience réellement démontrée.",
    "Le Bachelier de spécialisation Business Data Analysis est terminé depuis juin 2026.",
]


def _find_education(fragment):
    fragment = fragment.casefold()
    for item in CANDIDATE_TRUTH["education"]:
        if fragment in item["degree"].casefold():
            return item
    raise KeyError(fragment)


def build_handoff_candidate_truth():
    """
    Adaptateur de compatibilité pour ChatGPT Handoff V1.

    Les faits ne sont PAS redéfinis ici : ils sont dérivés de CANDIDATE_TRUTH.
    """
    truth = CANDIDATE_TRUTH
    experience = truth["professional_experience"]

    chemistry = _find_education("chimie industrielle")
    bda = _find_education("business data analysis")
    pharma = _find_education("sciences pharmaceutiques")

    roles = [
        f"{row['company']} — {row['role']} — {row['dates']}"
        for row in experience["roles"]
    ]

    return {
        "identity": deepcopy(truth["identity"]),
        "degrees": [
            {
                "label": chemistry["degree"],
                "status": "completed",
            },
            {
                "label": bda["degree"].replace(
                    " de spécialisation en Business",
                    " de spécialisation Business",
                ),
                "status": "completed",
                "completed": "juin 2026",
            },
            {
                "label": pharma["degree"],
                "status": "Master 1 validé / études suivies",
                "hard_rule": (
                    "Ne jamais présenter ceci comme un Master obtenu."
                ),
            },
        ],
        "experience": {
            "pharma_qc_years_approx": experience["pharma_qc_years"],
            "roles": roles,
            "data_professional_years": experience["data_professional_years"],
        },
        "skills_demonstrated": list(truth["supported_skills"]),
        "languages": deepcopy(truth["languages"]),
        "not_demonstrated": list(truth["unsupported_or_not_proven"]),
        "hard_truth_rules": list(HARD_TRUTH_RULES),
        "forbidden_claim_terms": sorted(
            FORBIDDEN_CANDIDATE_CLAIM_TERMS.values()
        ),
    }
