"""
Diagnostic AI DOCUMENT GENERATOR V1
AUCUN appel API.

Usage :
    python -m diagnostics.ai_document_generator_v1_audit
"""

import tempfile
from pathlib import Path

from applications.ai_document_generator import (
    build_prompt,
    select_jobs,
    validate_generated_payload,
    output_paths,
)


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f": {detail}" if detail else ""))
    return ok


def good_payload():
    return {
        "language": "fr",
        "cv": {
            "headline": "TECHNICIEN LABORATOIRE QC – HPLC/UPLC",
            "summary": (
                "Laborantin QC avec 3 ans d'expérience pharmaceutique. "
                "Pratique HPLC/UPLC acquise chez Corden Pharma."
            ),
            "key_skills": ["GMP", "HPLC/UPLC", "SAP/LIMS", "Microbiologie"],
            "experiences": [
                {
                    "company": "GSK",
                    "role": "Laborantin QC",
                    "dates": "05/2022 – 05/2023",
                    "bullets": ["Contrôle microbiologique et traçabilité SAP/LIMS."],
                },
                {
                    "company": "Prothya Biosolutions",
                    "role": "Laborantin QC",
                    "dates": "06/2020 – 02/2022",
                    "bullets": ["Endosafe MCS, TrackWise, SOP."],
                },
                {
                    "company": "Corden Pharma",
                    "role": "Stage laboratoire",
                    "dates": "01/2017 – 04/2017",
                    "bullets": ["Analyses HPLC/UPLC et chromatogrammes."],
                },
                {
                    "company": "Institut Meurice",
                    "role": "Stage laboratoire",
                    "dates": "04/2017 – 06/2017",
                    "bullets": ["Voltampérométrie, pH et conductivité."],
                },
            ],
            "education": [
                "Bachelier de spécialisation en Business Data Analysis — EPHEC — diplôme obtenu en 2026",
                "Bachelier en Chimie industrielle — diplôme obtenu",
                "Sciences pharmaceutiques — niveau Master 1 validé, sans diplôme de Master",
            ],
            "data_project": [
                "Python, SQL, Power BI et ETL sur un projet de plus de 3 000 enregistrements."
            ],
            "languages": [
                "Français C2", "Anglais B1", "Néerlandais B1"
            ],
        },
        "cover_letter": {
            "subject": "Objet : Candidature – Technicien laboratoire QC",
            "salutation": "Madame, Monsieur,",
            "paragraphs": [
                "Votre offre correspond à mon expérience en QC pharmaceutique.",
                "Chez GSK et Prothya, j'ai travaillé sous GMP avec SAP/LIMS et SOP.",
                "Ma pratique HPLC/UPLC a été acquise chez Corden Pharma.",
            ],
            "closing": "Je vous prie d'agréer mes salutations distinguées.",
        },
        "email": {
            "subject": "Candidature – Technicien laboratoire QC – Oussama Aharroud",
            "body": "Bonjour, veuillez trouver ma candidature en pièces jointes.",
        },
        "alignment": {
            "top_matches": ["QC pharma", "HPLC/UPLC", "GMP"],
            "gaps_not_to_fake": ["GC"],
            "truth_check": ["BDA obtenu en 2026", "Pas de Master"],
        },
        "claims_requiring_verification": [],
    }


def main():
    tests = []

    refresh = [{
        "stable_item_key": "ITEM_OK",
        "title": "Technicien QC",
        "company": "Entreprise",
        "location": "Bruxelles",
        "url": "https://example.test",
        "cv_track": "LAB_QC",
        "job_live_status": "LIVE_CONFIRMED",
        "application_folder": "exports/applications/test",
        "output_files": {},
        "base_cv_path": "C:/tmp/cv.docx",
        "live_detail": {"matching_text": "x" * 800},
    }]
    recheck = [{
        "stable_item_key": "ITEM_OK",
        "status": "READY_DOCUMENTS",
        "queue_rank": 1,
        "cv_track": "LAB_QC",
    }]

    selected = select_jobs(recheck, refresh)
    tests.append(check(
        "READY_DOCUMENTS sélectionné",
        len(selected) == 1,
        str(len(selected)),
    ))

    recheck_bad = [{
        "stable_item_key": "ITEM_OK",
        "status": "REJECT",
        "queue_rank": 1,
    }]
    tests.append(check(
        "REJECT jamais sélectionné",
        len(select_jobs(recheck_bad, refresh)) == 0,
    ))

    prompt = build_prompt(selected[0], "CV SOURCE TEST")
    tests.append(check(
        "Prompt contient vérité BDA obtenu",
        "OBTENU en 2026" in prompt,
    ))
    tests.append(check(
        "Prompt interdit l'invention",
        "AUCUNE INVENTION" in prompt,
    ))
    tests.append(check(
        "Prompt contient description live",
        "x" * 200 in prompt,
    ))

    payload = good_payload()
    errors = validate_generated_payload(payload)
    tests.append(check(
        "Payload factuel accepté",
        errors == [],
        " | ".join(errors),
    ))

    bad = good_payload()
    bad["cv"]["education"][0] = (
        "Bachelier de spécialisation en Business Data Analysis — en cours"
    )
    errors = validate_generated_payload(bad)
    tests.append(check(
        "BDA 'en cours' bloqué",
        any("BDA" in e for e in errors),
        " | ".join(errors),
    ))

    bad = good_payload()
    bad["cv"]["summary"] += " Maîtrise d'Empower."
    errors = validate_generated_payload(bad)
    tests.append(check(
        "Empower inventé bloqué",
        any("Empower" in e for e in errors),
        " | ".join(errors),
    ))

    bad = good_payload()
    bad["claims_requiring_verification"] = ["3 ans de GC"]
    errors = validate_generated_payload(bad)
    tests.append(check(
        "Claim à vérifier bloque la génération",
        any("vérifier" in e for e in errors),
        " | ".join(errors),
    ))

    bad = good_payload()
    bad["cv"]["experiences"] = [
        x for x in bad["cv"]["experiences"]
        if x["company"] != "Corden Pharma"
    ]
    errors = validate_generated_payload(bad)
    tests.append(check(
        "Expérience Corden absente détectée",
        any("corden" in e.lower() for e in errors),
        " | ".join(errors),
    ))

    p = good_payload()
    tests.append(check(
        "HPLC/UPLC supporté non bloqué",
        validate_generated_payload(p) == [],
    ))

    print()
    print(f"Tests synthétiques : {sum(tests)}/{len(tests)}")
    if all(tests):
        print("✅ AI DOCUMENT GENERATOR V1 VALIDÉ SUR LE DIAGNOSTIC LOCAL.")
    else:
        raise SystemExit("❌ AI DOCUMENT GENERATOR V1 NON VALIDÉ.")


if __name__ == "__main__":
    main()
