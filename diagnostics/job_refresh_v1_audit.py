"""
Diagnostic JOB REFRESH V1

Usage:
    python -m diagnostics.job_refresh_v1_audit
"""

from applications.job_refresh import (
    parse_forem_external_id,
    parse_actiris_reference_and_type,
    assess_detail,
)


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f": {detail}" if detail else ""))
    return ok


def main():
    tests = []

    tests.append(check(
        "Parse external_id FOREM",
        parse_forem_external_id(
            "https://www.leforem.be/recherche-offres/offre-detail/1991467"
        ) == "1991467",
    ))

    ref, offer_type = parse_actiris_reference_and_type(
        "https://www.actiris.brussels/fr/citoyens/detail-offre-d-emploi/"
        "?reference=5906598&type=DirectOnline"
    )
    tests.append(check(
        "Parse ACTIRIS référence",
        ref == "5906598",
        str(ref),
    ))
    tests.append(check(
        "Parse ACTIRIS type",
        offer_type == "DirectOnline",
        str(offer_type),
    ))

    item_ok = {"base_cv_found": True}
    detail_ok = {
        "success": True,
        "from_cache": False,
        "matching_text": "x" * 300,
        "matching_text_length": 300,
    }
    a = assess_detail(item_ok, detail_ok)
    tests.append(check(
        "Live complet -> READY_FOR_DOCUMENTS",
        a["document_generation_status"] == "READY_FOR_DOCUMENTS",
        a["document_generation_status"],
    ))
    tests.append(check(
        "Live complet -> safe_to_generate",
        a["safe_to_generate_documents"] is True,
    ))

    detail_fail = {
        "success": False,
        "from_cache": False,
        "matching_text": "",
        "error": "404",
    }
    a = assess_detail(item_ok, detail_fail)
    tests.append(check(
        "Échec source -> WAITING_SOURCE_REVIEW",
        a["document_generation_status"] == "WAITING_SOURCE_REVIEW",
    ))

    detail_cache = {
        "success": True,
        "from_cache": True,
        "matching_text": "x" * 300,
    }
    a = assess_detail(item_ok, detail_cache)
    tests.append(check(
        "Cache seul refusé comme preuve live",
        a["job_live_status"] == "CACHE_ONLY"
        and a["safe_to_generate_documents"] is False,
    ))

    detail_short = {
        "success": True,
        "from_cache": False,
        "matching_text": "trop court",
    }
    a = assess_detail(item_ok, detail_short)
    tests.append(check(
        "Description trop courte bloquée",
        a["job_description_status"] == "TOO_SHORT"
        and a["safe_to_generate_documents"] is False,
    ))

    item_no_cv = {"base_cv_found": False}
    a = assess_detail(item_no_cv, detail_ok)
    tests.append(check(
        "CV absent -> WAITING_BASE_CV",
        a["document_generation_status"] == "WAITING_BASE_CV",
    ))

    print()
    print(f"Tests synthétiques : {sum(tests)}/{len(tests)}")

    if all(tests):
        print("✅ JOB REFRESH V1 VALIDÉ SUR LE DIAGNOSTIC.")
    else:
        raise SystemExit("❌ JOB REFRESH V1 NON VALIDÉ.")


if __name__ == "__main__":
    main()
