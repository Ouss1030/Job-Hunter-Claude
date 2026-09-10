"""
CHATGPT HANDOFF V1.0 - AUDIT

Usage:
    python -m diagnostics.chatgpt_handoff_v1_audit
"""

from collections import Counter

from applications.chatgpt_handoff import (
    BASE_CV_PREFERENCE,
    CANDIDATE_TRUTH,
    HANDOFF_VERSION,
    latest_file,
    load_json,
    select_items,
)


def check(label, condition, detail=""):
    ok = bool(condition)
    print(
        f"{'✅' if ok else '❌'} {label}"
        + (f" | {detail}" if detail else "")
    )
    return ok


def main():
    print("=" * 92)
    print("CHATGPT HANDOFF V1.0 - AUDIT")
    print("=" * 92)
    print()

    tests = []

    tests.append(check(
        "Version 1.0",
        HANDOFF_VERSION == "1.0",
        HANDOFF_VERSION,
    ))

    tests.append(check(
        "CV LabQC par défaut",
        BASE_CV_PREFERENCE == "CV_Oussama_Aharroud_LabQC.docx",
        BASE_CV_PREFERENCE,
    ))

    tests.append(check(
        "BDA marqué terminé",
        any(
            x.get("label") == "Bachelier de spécialisation Business Data Analysis"
            and x.get("status") == "completed"
            for x in CANDIDATE_TRUTH["degrees"]
        ),
    ))

    tests.append(check(
        "Master pharma non revendiqué",
        any(
            "Ne jamais présenter" in str(x.get("hard_rule") or "")
            for x in CANDIDATE_TRUTH["degrees"]
        ),
    ))

    source = latest_file("final_application_pool_v12_*.json")
    tests.append(check(
        "Final Pool V1.2 trouvé",
        source is not None,
        str(source),
    ))

    if source:
        payload = load_json(source)

        tests.append(check(
            "Pool version 1.2",
            str(payload.get("pool_version")) == "1.2",
            str(payload.get("pool_version")),
        ))

        apply_now = select_items(payload, ["APPLY_NOW"])
        tests.append(check(
            "37 APPLY_NOW",
            len(apply_now) == 37,
            str(len(apply_now)),
        ))

        tests.append(check(
            "Tous APPLY_NOW sont Guard PASS",
            all(x.get("guard_level") == "PASS" for x in apply_now),
        ))

        sources = Counter(
            str(x.get("source") or "").upper()
            for x in apply_now
        )
        tests.append(check(
            "7 SmartRecruiters dans APPLY_NOW",
            sources.get("SMARTRECRUITERS") == 7,
            str(sources.get("SMARTRECRUITERS")),
        ))

        tests.append(check(
            "1 TravaillerPour dans APPLY_NOW",
            sources.get("TRAVAILLERPOUR") == 1,
            str(sources.get("TRAVAILLERPOUR")),
        ))

        tests.append(check(
            "Aucun DO_NOT_APPLY exporté",
            all(
                x.get("recommended_action_v12") != "DO_NOT_APPLY"
                for x in apply_now
            ),
        ))

    print()
    print(f"Tests : {sum(tests)}/{len(tests)}")

    if not all(tests):
        raise SystemExit("❌ CHATGPT HANDOFF V1.0 NON VALIDÉ.")

    print("✅ CHATGPT HANDOFF V1.0 VALIDÉ.")


if __name__ == "__main__":
    main()
