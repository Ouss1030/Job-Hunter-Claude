"""
JOB REFRESH V1.1 - DIAGNOSTIC OFFLINE

Aucun appel réseau.
Aucune écriture DB.
Aucun snapshot de candidature.

Usage:
    python -m diagnostics.job_refresh_v11_audit
"""

from applications.job_refresh_v11 import (
    REFRESH_VERSION,
    assess_detail,
    parse_actiris_reference_and_type,
    parse_forem_external_id,
    parse_smartrecruiters_identity,
    smartrecruiters_detail_to_refresh_payload,
)


def check(label, condition, detail=""):
    ok = bool(condition)
    print(
        f"{'✅' if ok else '❌'} {label}"
        + (f" | {detail}" if detail else "")
    )
    return ok


def synthetic_sr_detail():
    return {
        "id": "744000999999999",
        "uuid": "11111111-2222-3333-4444-555555555555",
        "name": "QC Laboratory Analyst",
        "company": {"name": "Eurofins"},
        "location": {
            "city": "Brussels",
            "region": "Brussels",
            "country": "be",
            "remote": False,
        },
        "typeOfEmployment": {"label": "Full-time"},
        "language": {"label": "English"},
        "department": {"label": "Laboratory"},
        "function": {"label": "Quality"},
        "experienceLevel": {"label": "Entry level"},
        "applyUrl": "https://example.test/apply",
        "jobAd": {
            "sections": {
                "companyDescription": {
                    "text": (
                        "<p>CORPORATE_BOILERPLATE pharmaceutical data "
                        "laboratory quality.</p>"
                    )
                },
                "jobDescription": {
                    "text": (
                        "<p>Perform QC analyses on samples and document "
                        "results according to GMP.</p>"
                    )
                },
                "qualifications": {
                    "text": "<p>Bachelor in chemistry accepted.</p>"
                },
                "additionalInformation": {
                    "text": "<p>Training is provided.</p>"
                },
            }
        },
    }


def main():
    tests = []

    print("=" * 86)
    print("JOB REFRESH V1.1 - DIAGNOSTIC OFFLINE")
    print("=" * 86)
    print()

    tests.append(check(
        "Version 1.1",
        REFRESH_VERSION == "1.1",
        REFRESH_VERSION,
    ))

    tests.append(check(
        "Parse FOREM",
        parse_forem_external_id(
            "https://www.leforem.be/recherche-offres/offre-detail/1991467"
        ) == "1991467",
    ))

    ref, offer_type = parse_actiris_reference_and_type(
        "https://www.actiris.brussels/fr/citoyens/detail-offre-d-emploi/"
        "?reference=5906598&type=DirectOnline"
    )
    tests.append(check("Parse ACTIRIS ref", ref == "5906598", str(ref)))
    tests.append(check(
        "Parse ACTIRIS type",
        offer_type == "DirectOnline",
        str(offer_type),
    ))

    sr_item = {
        "source": "SMARTRECRUITERS",
        "origin_source": "Eurofins",
        "url": (
            "https://jobs.smartrecruiters.com/Eurofins/"
            "744000139933016-qc-laborant"
        ),
    }
    company, posting = parse_smartrecruiters_identity(sr_item)
    tests.append(check(
        "Parse SR jobs URL company",
        company == "Eurofins",
        str(company),
    ))
    tests.append(check(
        "Parse SR jobs URL posting",
        posting == "744000139933016",
        str(posting),
    ))

    api_item = {
        "source": "SMARTRECRUITERS",
        "url": (
            "https://api.smartrecruiters.com/v1/companies/SGS/"
            "postings/744000144053379"
        ),
    }
    company2, posting2 = parse_smartrecruiters_identity(api_item)
    tests.append(check("Parse SR API company", company2 == "SGS", str(company2)))
    tests.append(check(
        "Parse SR API posting",
        posting2 == "744000144053379",
        str(posting2),
    ))

    ext_item = {
        "source": "SMARTRECRUITERS",
        "external_id": "SopraSteria1:744000055501810",
        "url": "",
    }
    company3, posting3 = parse_smartrecruiters_identity(ext_item)
    tests.append(check(
        "Parse SR external_id",
        (company3, posting3)
        == ("SopraSteria1", "744000055501810"),
        f"{company3}:{posting3}",
    ))

    payload = smartrecruiters_detail_to_refresh_payload(
        "Eurofins",
        "744000999999999",
        synthetic_sr_detail(),
    )
    tests.append(check(
        "SR conversion success",
        payload["success"] is True
        and payload["matching_text_length"] >= 120,
        str(payload["matching_text_length"]),
    ))
    tests.append(check(
        "Corporate exclu du matching_text",
        "CORPORATE_BOILERPLATE" not in payload["matching_text"],
    ))
    tests.append(check(
        "Corporate conservé structuré",
        "CORPORATE_BOILERPLATE"
        in payload["structured"]["company_description"],
    ))
    tests.append(check(
        "Qualifications exposées au Recheck",
        "Bachelor in chemistry"
        in payload["structured"]["profile"],
    ))

    item_ok = {"base_cv_found": True}
    detail_ok = {
        "success": True,
        "from_cache": False,
        "matching_text": "x" * 300,
        "matching_text_length": 300,
    }
    assessment = assess_detail(item_ok, detail_ok)
    tests.append(check(
        "Live complet -> READY_FOR_DOCUMENTS",
        assessment["document_generation_status"] == "READY_FOR_DOCUMENTS"
        and assessment["safe_to_generate_documents"] is True,
    ))

    assessment = assess_detail(
        item_ok,
        {
            "success": False,
            "from_cache": False,
            "matching_text": "",
            "error": "SmartRecruiters HTTP 404 : offre fermée.",
        },
    )
    tests.append(check(
        "404 reste SOURCE_FETCH_FAILED",
        assessment["job_live_status"] == "SOURCE_FETCH_FAILED"
        and "404" in assessment["reason"],
        assessment["reason"],
    ))

    assessment = assess_detail(
        item_ok,
        {
            "success": True,
            "from_cache": True,
            "matching_text": "x" * 300,
        },
    )
    tests.append(check(
        "Cache refusé comme preuve live",
        assessment["job_live_status"] == "CACHE_ONLY"
        and assessment["safe_to_generate_documents"] is False,
    ))

    assessment = assess_detail(
        item_ok,
        {
            "success": True,
            "from_cache": False,
            "matching_text": "court",
        },
    )
    tests.append(check(
        "Description courte bloquée",
        assessment["job_description_status"] == "TOO_SHORT",
    ))

    assessment = assess_detail(
        {"base_cv_found": False},
        detail_ok,
    )
    tests.append(check(
        "CV absent bloqué",
        assessment["document_generation_status"] == "WAITING_BASE_CV",
    ))

    print()
    print(f"Tests : {sum(tests)}/{len(tests)}")

    if not all(tests):
        raise SystemExit("❌ JOB REFRESH V1.1 NON VALIDÉ OFFLINE.")

    print("✅ JOB REFRESH V1.1 VALIDÉ OFFLINE.")


if __name__ == "__main__":
    main()
