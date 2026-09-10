"""
JOB REFRESH V1.2 - AUDIT OFFLINE

Usage:
python -m diagnostics.job_refresh_v12_audit
"""

import inspect

import applications.job_refresh_v12 as refresh


def check(label, condition, detail=""):
    ok = bool(condition)
    print(
        f"{'✅' if ok else '❌'} {label}"
        + (f" | {detail}" if detail else "")
    )
    return ok


def main():
    tests = []

    print("=" * 84)
    print("JOB REFRESH V1.2 - AUDIT OFFLINE")
    print("=" * 84)
    print()

    tests.append(check(
        "Version V1.2",
        refresh.REFRESH_VERSION == "1.2",
        refresh.REFRESH_VERSION,
    ))

    cases = {
        "CFG26046": (
            "https://travaillerpour.be/fr/jobs/"
            "cfg26046-controleur-ulc-bruxelles-mfx"
        ),
        "AFG26147": (
            "https://travaillerpour.be/fr/jobs/"
            "AFG26147-exemple"
        ),
        "XFC26104": (
            "https://travaillerpour.be/nl/jobs/"
            "xfc26104-gegevensbeheerder"
        ),
        "CNG26031": (
            "https://travaillerpour.be/fr/jobs/"
            "cng26031-test"
        ),
    }

    for expected, url in cases.items():
        got = refresh.parse_travaillerpour_external_id(url)
        tests.append(check(
            f"Parse TP {expected}",
            got == expected,
            str(got),
        ))

    tests.append(check(
        "URL invalide -> None",
        refresh.parse_travaillerpour_external_id(
            "https://travaillerpour.be/fr/jobs/offre-sans-code"
        ) is None,
    ))

    src = inspect.getsource(refresh.fetch_live_detail)
    tests.append(check(
        "Route TRAVAILLERPOUR branchée",
        'source == "TRAVAILLERPOUR"' in src,
    ))
    tests.append(check(
        "TP use_cache=False",
        "get_travaillerpour_job_detail" in src
        and "use_cache=False" in src,
    ))
    tests.append(check(
        "SmartRecruiters conservé",
        'source == "SMARTRECRUITERS"' in src,
    ))
    tests.append(check(
        "Forem conservé",
        'source == "FOREM"' in src,
    ))
    tests.append(check(
        "Actiris conservé",
        'source == "ACTIRIS"' in src,
    ))

    print()
    print(f"Tests : {sum(tests)}/{len(tests)}")

    if not all(tests):
        raise SystemExit("❌ JOB REFRESH V1.2 NON VALIDÉ OFFLINE.")

    print("✅ JOB REFRESH V1.2 VALIDÉ OFFLINE.")


if __name__ == "__main__":
    main()
