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
from diagnostics.version_support import at_least


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
            at_least(str(payload.get("pool_version")), "1.2"),
            str(payload.get("pool_version")),
        ))

        apply_now = select_items(payload, ["APPLY_NOW"])
        tests.append(check(
            "Au moins une APPLY_NOW",
            len(apply_now) > 0,
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
        # Propriete, pas comptage exact.
        #
        # « == 7 » figeait le resultat d'un run precis : le pool change a
        # chaque collecte, donc l'audit devenait faux sans qu'aucun defaut
        # n'existe. C'est la meme famille que « _VERSION == "1.2" ».
        #
        # Ce qui doit rester vrai, c'est que le pool ne provient pas d'une
        # source unique : une concentration totale signalerait un filtre
        # casse en amont.
        tests.append(check(
            "APPLY_NOW vient de plusieurs sources",
            len(sources) >= 2,
            f"{len(sources)} sources : "
            + ", ".join(f"{k}={v}" for k, v in sources.most_common(6)),
        ))

        tests.append(check(
            "Aucune source ne represente la totalite du pool",
            not sources or max(sources.values()) < sum(sources.values()),
            f"source dominante : {sources.most_common(1)[0] if sources else '-'}",
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
